"""Turns a run's check results into IntegrityIssue rows.

Each issue is one row keyed by source, check and subject. A run that still
observes it updates it; a run whose check ran and no longer observes it marks
it resolved. A check that was skipped, and a member or subscription that was
deferred, leave their issues exactly as they were: not seeing something is
only evidence it's fixed when the check actually looked.

An open issue that comes to cover something new (Finding.refs) is treated as
unread again: it loses its acknowledgement and is emailed about afresh.
"""

import dataclasses
from datetime import timedelta

from django.db import transaction

from .models import IntegrityIssue, IntegrityRun

# Resolved issues are diagnostic history, so keep them well past the run
# interval.
RETENTION = timedelta(days=90)


@dataclasses.dataclass
class RecordResult:
    # Issues seen for the first time, or again after being resolved.
    new: list = dataclasses.field(default_factory=list)
    resolved: list = dataclasses.field(default_factory=list)


def issue_key(source, check, subject):
    return f"{source}:{check}:{subject}"[:255]


def _details(finding):
    details = {
        "mm": finding.mm,
        "stripe": finding.stripe,
        "cause": finding.cause,
        "action": finding.action,
        **finding.extra,
    }
    if finding.refs:
        details["refs"] = sorted(finding.refs)
    return details


def _upsert(source, check, finding, now, result):
    key = issue_key(source, check, finding.subject)
    values = {
        "check_name": check,
        "source": source,
        "severity": finding.severity,
        "message": finding.message[:255],
        "details": _details(finding),
        "profile_id": finding.profile_id,
        "stripe_ref": finding.stripe_ref,
        "last_seen": now,
    }

    issue = IntegrityIssue.objects.filter(key=key).first()
    if issue is None:
        issue = IntegrityIssue.objects.create(key=key, first_seen=now, **values)
        result.new.append(issue)
        return

    previous_refs = set((issue.details or {}).get("refs", ()))
    reopened = issue.resolved_at is not None
    for field, value in values.items():
        setattr(issue, field, value)

    if reopened:
        # A new occurrence: alert and ask for acknowledgement again.
        issue.first_seen = now
        issue.occurrences = 1
        issue.resolved_at = None
        issue.notified_severity = ""
        issue.acknowledged_by = None
        issue.acknowledged_at = None
    else:
        issue.occurrences += 1
        if set(finding.refs) - previous_refs:
            # It covers something nobody has looked at yet.
            issue.notified_severity = ""
            issue.acknowledged_by = None
            issue.acknowledged_at = None
    issue.save()

    if reopened:
        result.new.append(issue)


def record_results(
    results,
    now,
    scope_profile_id=None,
    deferred_profiles=(),
    deferred_refs=(),
):
    """Write one run's CheckResults. Returns a RecordResult.

    `scope_profile_id` limits resolution to one member's issues, for a member
    re-check that never looked at anyone else.
    """
    result = RecordResult()
    with transaction.atomic():
        for (source, check), findings in results.findings.items():
            observed = set()
            for finding in findings:
                key = issue_key(source, check, finding.subject)
                if key in observed:
                    continue
                observed.add(key)
                _upsert(source, check, finding, now, result)

            stale = IntegrityIssue.objects.filter(
                source=source, check_name=check, resolved_at__isnull=True
            ).exclude(key__in=observed)
            if scope_profile_id is not None:
                stale = stale.filter(profile_id=scope_profile_id)
            if deferred_profiles:
                stale = stale.exclude(profile_id__in=list(deferred_profiles))
            if deferred_refs:
                stale = stale.exclude(stripe_ref__in=list(deferred_refs))

            for issue in stale:
                issue.resolved_at = now
                issue.save(update_fields=["resolved_at"])
                result.resolved.append(issue)
    return result


def open_issues():
    return IntegrityIssue.objects.filter(resolved_at__isnull=True)


def delete_old(now):
    """Drop resolved issues and runs past the retention period, keeping the
    latest complete run so staleness can always be measured."""
    cutoff = now - RETENTION
    IntegrityIssue.objects.filter(resolved_at__lt=cutoff).delete()

    old_runs = IntegrityRun.objects.filter(started_at__lt=cutoff)
    latest_complete = last_complete_run()
    if latest_complete is not None:
        old_runs = old_runs.exclude(pk=latest_complete.pk)
    old_runs.delete()


def full_runs():
    return IntegrityRun.objects.filter(profile__isnull=True).exclude(
        trigger=IntegrityRun.Trigger.MEMBER
    )


def last_complete_run():
    return (
        full_runs()
        .filter(status=IntegrityRun.Status.COMPLETE)
        .order_by("-finished_at")
        .first()
    )
