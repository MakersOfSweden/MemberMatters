from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from sentry_sdk import capture_exception

from profile.models import Profile

from . import runner, schedule
from .links import stripe_dashboard_url, stripe_test_mode
from .models import IntegrityIssue, IntegrityRun, Severity, Source
from .sources import SOURCES
from .store import full_runs, last_complete_run, open_issues

# A complete run older than this means the nightly check has stopped.
STALE_AFTER = timedelta(hours=36)

MAX_ISSUES = 500

_SHOWN_DETAILS = ("mm", "stripe", "cause", "action")


def serialize_run(run):
    if run is None:
        return None
    return {
        "id": run.id,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "status": run.status,
        "trigger": run.trigger,
        "stripeRequests": run.stripe_requests,
        "membersChecked": run.members_checked,
        "newIssues": run.new_issues,
        "resolvedIssues": run.resolved_issues,
        "openIssues": run.open_issues,
        "skippedChecks": run.skipped_checks,
        "error": run.error,
    }


def serialize_issue(issue):
    details = issue.details or {}
    profile = issue.profile
    return {
        "id": issue.id,
        "check": issue.check_name,
        "severity": issue.severity,
        "source": issue.source,
        "message": issue.message,
        "mm": details.get("mm", ""),
        "stripe": details.get("stripe", ""),
        "cause": details.get("cause", ""),
        "action": details.get("action", ""),
        "extra": {k: v for k, v in details.items() if k not in _SHOWN_DETAILS},
        "memberId": profile.user_id if profile else None,
        "memberName": profile.get_full_name() if profile else None,
        "stripeRef": issue.stripe_ref,
        "stripeUrl": stripe_dashboard_url(issue.stripe_ref),
        "firstSeen": issue.first_seen,
        "lastSeen": issue.last_seen,
        "occurrences": issue.occurrences,
        "resolvedAt": issue.resolved_at,
        "acknowledged": issue.is_acknowledged,
        "acknowledgedBy": (
            issue.acknowledged_by.profile.get_full_name()
            if issue.acknowledged_by and hasattr(issue.acknowledged_by, "profile")
            else None
        ),
        "acknowledgedAt": issue.acknowledged_at,
        "notes": issue.notes,
    }


def _issues():
    return IntegrityIssue.objects.select_related(
        "profile", "acknowledged_by__profile"
    ).order_by("-last_seen")


class IntegrityStatus(APIView):
    """
    get: The billing check's last runs and the open issue counts.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        enabled = runner.is_enabled()
        last_complete = last_complete_run()
        stale = enabled and (
            last_complete is None
            or last_complete.finished_at is None
            or last_complete.finished_at < timezone.now() - STALE_AFTER
        )

        counts = {severity: 0 for severity in Severity.values}
        unacknowledged = open_issues().filter(acknowledged_at__isnull=True)
        for row in unacknowledged.values("severity").annotate(total=Count("pk")):
            counts[row["severity"]] = row["total"]
        counts["acknowledged"] = (
            open_issues().exclude(acknowledged_at__isnull=True).count()
        )

        celery_configured = bool(settings.CELERY_BROKER_URL)
        sources = [Source.ACCOUNT, *(source.name for source in SOURCES)]
        return Response(
            {
                "enabled": enabled,
                "celeryConfigured": celery_configured,
                "schedule": schedule.describe(),
                # Nothing runs on schedule without Celery; a cron job running
                # check_stripe_drift keeps its own times.
                "nextRun": (
                    schedule.next_daily_check()
                    if enabled and celery_configured
                    else None
                ),
                "running": full_runs()
                .filter(status=IntegrityRun.Status.RUNNING)
                .exists(),
                "lastRun": serialize_run(full_runs().order_by("-started_at").first()),
                "lastCompleteRun": serialize_run(last_complete),
                "stale": stale,
                "counts": counts,
                "sources": [
                    {"value": value, "label": Source(value).label} for value in sources
                ],
                "stripeTestMode": stripe_test_mode(),
            }
        )


class IntegrityIssues(APIView):
    """
    get: Billing integrity issues. `status` is open (the default),
    acknowledged or resolved; `severity` and `source` filter further.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        state = request.query_params.get("status", "open")
        issues = _issues()
        if state == "resolved":
            issues = issues.filter(resolved_at__isnull=False).order_by("-resolved_at")
        elif state == "acknowledged":
            issues = issues.filter(
                resolved_at__isnull=True, acknowledged_at__isnull=False
            )
        else:
            issues = issues.filter(
                resolved_at__isnull=True, acknowledged_at__isnull=True
            )

        severity = request.query_params.get("severity")
        if severity:
            issues = issues.filter(severity=severity)
        source = request.query_params.get("source")
        if source:
            issues = issues.filter(source=source)

        return Response([serialize_issue(issue) for issue in issues[:MAX_ISSUES]])


class IntegrityIssueAcknowledge(APIView):
    """
    post: Acknowledges an open issue, with an optional note. Acknowledged
    issues stay open until a run no longer sees them, but never cause email.
    delete: Withdraws the acknowledgement.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, issue_id):
        issue = get_object_or_404(_issues(), pk=issue_id, resolved_at__isnull=True)
        issue.acknowledged_by = request.user
        issue.acknowledged_at = timezone.now()
        issue.notes = (request.data.get("note") or "").strip()[:1000]
        issue.save(update_fields=["acknowledged_by", "acknowledged_at", "notes"])

        if issue.profile is not None:
            issue.profile.user.log_event(
                f"Billing issue acknowledged by {request.user.get_full_name()}: "
                f"{issue.message}",
                "admin",
                issue.notes,
            )
        return Response(serialize_issue(issue))

    def delete(self, request, issue_id):
        issue = get_object_or_404(_issues(), pk=issue_id)
        issue.acknowledged_by = None
        issue.acknowledged_at = None
        issue.save(update_fields=["acknowledged_by", "acknowledged_at"])
        return Response(serialize_issue(issue))


class IntegrityRunNow(APIView):
    """
    post: Queues a full billing check on the Celery worker.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        from .tasks import run_integrity_checks

        if not runner.is_enabled():
            return Response(
                {"success": False, "message": "billingIntegrity.disabled"},
                status=status.HTTP_409_CONFLICT,
            )
        if not settings.CELERY_BROKER_URL:
            return Response(
                {"success": False, "message": "billingIntegrity.noCelery"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if full_runs().filter(status=IntegrityRun.Status.RUNNING).exists():
            return Response(
                {"success": False, "message": "billingIntegrity.alreadyRunning"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            run_integrity_checks.delay(
                trigger=IntegrityRun.Trigger.MANUAL, user_id=request.user.id
            )
        except Exception as error:
            capture_exception(error)
            return Response(
                {"success": False, "message": "billingIntegrity.noCelery"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"success": True}, status=status.HTTP_202_ACCEPTED)


class MemberIntegrityIssues(APIView):
    """
    get: A member's open billing integrity issues, acknowledged or not.
    post: Re-checks just this member against Stripe, then returns their open
    issues. Costs at most two Stripe requests.
    """

    permission_classes = (permissions.IsAdminUser,)

    def _response(self, profile, run=None):
        issues = _issues().filter(profile=profile, resolved_at__isnull=True)
        return Response(
            {
                "enabled": runner.is_enabled(),
                "run": serialize_run(run),
                "issues": [serialize_issue(issue) for issue in issues],
            }
        )

    def get(self, request, member_id):
        profile = get_object_or_404(Profile, user_id=member_id)
        return self._response(profile)

    def post(self, request, member_id):
        profile = get_object_or_404(Profile, user_id=member_id)
        if not runner.is_enabled():
            return Response(
                {"success": False, "message": "billingIntegrity.disabled"},
                status=status.HTTP_409_CONFLICT,
            )
        outcome = runner.run(
            IntegrityRun.Trigger.MEMBER, user=request.user, profile=profile
        )
        return self._response(profile, outcome.run)
