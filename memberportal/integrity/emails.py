"""Emails to EMAIL_ADMIN about integrity issues. Never to members.

A daily email that is usually empty gets filtered, and one listing forty rows
gets ignored, so a run only emails about what's new:

- a critical issue an admin hasn't been told about, or a warning that became
  critical: one email per run, listing just those;
- the first run on an install: one summary instead of an alert per issue;
- a run that fails or is cut short: one email when the trouble starts, and one
  when a run completes again, not one every night.

Everything else waits for the weekly digest. Acknowledged issues never cause
an email.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from sentry_sdk import capture_exception

from services.emails import send_email_to_admin

from .links import member_url, page_url, stripe_dashboard_url
from .models import IntegrityIssue, IntegrityRun, Severity
from .store import full_runs, last_complete_run, open_issues

logger = logging.getLogger("integrity")

TEMPLATE = "email_integrity_report.html"

# Rows listed in one email; the page has the rest.
MAX_LISTED = 30

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _plural(count, word, plural=None):
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _when(moment):
    return timezone.localtime(moment).strftime("%d %b %Y, %H:%M").lstrip("0")


def _row(issue):
    details = issue.details or {}
    profile = issue.profile
    return {
        "severity": issue.get_severity_display(),
        "critical": issue.severity == Severity.CRITICAL,
        "name": profile.get_full_name() if profile else "Stripe account",
        "message": issue.message,
        "mm": details.get("mm", ""),
        "stripe": details.get("stripe", ""),
        "cause": details.get("cause", ""),
        "action": details.get("action", ""),
        "member_url": member_url(profile),
        "stripe_url": stripe_dashboard_url(issue.stripe_ref),
    }


def _sorted(issues):
    return sorted(
        issues, key=lambda issue: (_SEVERITY_ORDER[issue.severity], issue.first_seen)
    )


def _counts(issues):
    counts = {severity: 0 for severity in Severity.values}
    for issue in issues:
        counts[issue.severity] += 1
    return counts


def _counts_text(counts):
    parts = []
    if counts[Severity.CRITICAL]:
        parts.append(f"{counts[Severity.CRITICAL]} critical")
    if counts[Severity.WARNING]:
        parts.append(_plural(counts[Severity.WARNING], "warning"))
    if counts[Severity.INFO]:
        parts.append(f"{counts[Severity.INFO]} info")
    return ", ".join(parts) or "nothing"


def _send(subject, intro, issues=(), summary=""):
    rows = [_row(issue) for issue in _sorted(issues)[:MAX_LISTED]]
    if len(issues) > MAX_LISTED:
        summary = (
            f"{summary} The first {MAX_LISTED} of {len(issues)} are listed here; "
            "the billing integrity page has them all."
        ).strip()
    send_email_to_admin(
        subject=subject,
        template_name=TEMPLATE,
        template_vars={
            "title": subject,
            "intro": intro,
            "issues": rows,
            "summary": summary,
            "link": page_url(),
            "btn_text": "Review billing issues",
        },
    )


def _mark_notified(issues):
    for issue in issues:
        issue.notified_severity = issue.severity
        issue.save(update_fields=["notified_severity"])


def after_run(run):
    """Send whatever a finished full run calls for. Never raises."""
    try:
        _after_run(run)
    except Exception as error:
        capture_exception(error)
        logger.exception("Couldn't send the integrity emails for run %s", run.pk)


def _after_run(run):
    previous = (
        full_runs()
        .exclude(pk=run.pk)
        .exclude(status=IntegrityRun.Status.RUNNING)
        .filter(started_at__lte=run.started_at)
        .order_by("-started_at")
        .first()
    )
    troubled = (IntegrityRun.Status.FAILED, IntegrityRun.Status.INCOMPLETE)

    if run.status in troubled:
        if previous is None or previous.status not in troubled:
            send_trouble(run)
        if run.status == IntegrityRun.Status.FAILED:
            return
    elif previous is not None and previous.status in troubled:
        send_recovered(run)

    first_run = (
        not full_runs()
        .exclude(pk=run.pk)
        .filter(
            status__in=(
                IntegrityRun.Status.COMPLETE,
                IntegrityRun.Status.INCOMPLETE,
            )
        )
        .exists()
    )
    if first_run:
        send_first_summary(run)
        return

    unalerted = [
        issue
        for issue in open_issues()
        .filter(severity=Severity.CRITICAL, acknowledged_at__isnull=True)
        .exclude(notified_severity=Severity.CRITICAL)
        .select_related("profile")
    ]
    if unalerted:
        send_alert(run, unalerted)


def send_alert(run, issues):
    count = len(issues)
    subject = f"Billing check: {_plural(count, 'new critical issue')}"
    still_open = _counts(
        open_issues()
        .filter(acknowledged_at__isnull=True)
        .exclude(pk__in=[issue.pk for issue in issues])
    )
    _send(
        subject,
        intro=(
            f"The billing check on {_when(run.started_at)} found "
            f"{_plural(count, 'new critical issue')}. MemberMatters and Stripe "
            "disagree about these members. Nothing was changed automatically."
        ),
        issues=issues,
        summary=f"Also still open: {_counts_text(still_open)}.",
    )
    _mark_notified(issues)


def send_first_summary(run):
    issues = list(open_issues().select_related("profile"))
    counts = _counts(issues)
    if issues:
        subject = f"First billing check: {_counts_text(counts)}"
        intro = (
            "MemberMatters now compares every membership subscription with Stripe "
            f"each night. The first check found {_counts_text(counts)}. Nothing "
            "was changed automatically. From now on you'll get an email when a "
            "new critical issue appears, and a weekly digest."
        )
    else:
        subject = "First billing check: no issues found"
        intro = (
            "MemberMatters now compares every membership subscription with Stripe "
            "each night. The first check found nothing wrong. You'll get an email "
            "when a critical issue appears, and a weekly digest while any are open."
        )
    critical = [issue for issue in issues if issue.severity == Severity.CRITICAL]
    _send(subject, intro=intro, issues=critical)
    _mark_notified(issues)


def _skipped_text(run):
    reasons = sorted(
        {entry["reason"] for entry in run.skipped_checks if entry["reason"]}
    )
    return "; ".join(reasons)


def send_trouble(run):
    if run.status == IntegrityRun.Status.FAILED:
        subject = "Billing check failed"
        intro = (
            f"The billing check on {_when(run.started_at)} couldn't compare "
            f"subscriptions with Stripe: {run.error or 'unknown error'}. You'll get "
            "one more email when it works again."
        )
    else:
        subject = "Billing check couldn't finish"
        intro = (
            f"The billing check on {_when(run.started_at)} skipped some checks: "
            f"{_skipped_text(run) or 'see the billing integrity page'}. Issues "
            "those checks found before stay open until they run again. You'll get "
            "one more email when a run completes."
        )
    _send(subject, intro=intro)


def send_recovered(run):
    _send(
        "Billing check is working again",
        intro=(
            f"The billing check on {_when(run.started_at)} completed after earlier "
            "runs failed or were cut short."
        ),
    )


def send_digest(now=None):
    """The weekly digest of open issues. Sends nothing unless a warning or
    critical issue is open and unacknowledged. Returns whether it sent."""
    now = now or timezone.now()
    issues = list(open_issues().select_related("profile"))
    needs_attention = [issue for issue in issues if not issue.is_acknowledged]
    listed = [issue for issue in needs_attention if issue.severity != Severity.INFO]
    if not listed:
        return False

    acknowledged = len(issues) - len(needs_attention)
    counts = _counts(needs_attention)
    week_ago = now - timedelta(days=7)
    new_this_week = IntegrityIssue.objects.filter(first_seen__gte=week_ago).count()
    resolved_this_week = IntegrityIssue.objects.filter(
        resolved_at__gte=week_ago
    ).count()

    last_complete = last_complete_run()
    if last_complete is None:
        last_run_text = "No billing check has completed yet."
    else:
        last_run_text = (
            f"The last complete check ran on {_when(last_complete.started_at)}."
        )

    summary = [f"This week: {new_this_week} new, {resolved_this_week} resolved."]
    if acknowledged:
        summary.append(f"{_plural(acknowledged, 'acknowledged issue')} not listed.")
    summary.append(last_run_text)
    _send(
        f"Weekly billing check: {_counts_text(counts)} open",
        intro="Membership subscriptions where MemberMatters and Stripe still disagree.",
        issues=listed,
        summary=" ".join(summary),
    )
    return True
