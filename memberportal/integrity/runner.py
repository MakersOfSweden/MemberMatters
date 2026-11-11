"""Runs the integrity checks: fetch Stripe, read MemberMatters, compare, record.

A run only reads. It writes IntegrityRun and IntegrityIssue rows and may email
EMAIL_ADMIN, but never changes a member, never calls a Stripe write endpoint
and never emails a member.
"""

import dataclasses
import logging
from datetime import timedelta

import stripe
from constance import config
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from sentry_sdk import capture_exception

from api_admin_tools.models import PaymentPlan

from . import emails
from .checks import defer_unsettled, run_checks
from .data import SUBSCRIPTIONS, CheckContext, PlanInfo
from .models import IntegrityLock, IntegrityRun, Severity
from .snapshot import (
    HANDLED_EVENTS,
    build_snapshot,
    describe_error,
    is_missing,
    parse_subscription,
)
from .sources import SOURCES
from .store import open_issues, record_results
from .stripe_reader import StripeBudgetExceeded, StripeReader

logger = logging.getLogger("integrity")

# Stripe changes newer than this are left for the next run: the webhook that
# announces them may still be on its way, or being retried.
SETTLE = timedelta(minutes=30)

# A run still marked running after this long died with its worker.
RUN_TIMEOUT = timedelta(hours=2)


class AlreadyRunning(Exception):
    """Another run is in progress."""


def is_enabled():
    return bool(
        config.BILLING_AUDIT_ENABLED
        and config.ENABLE_STRIPE
        and config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS
        and config.STRIPE_SECRET_KEY
    )


def webhook_url():
    return config.SITE_URL.rstrip("/") + reverse("StripeWebhook")


def load_plans():
    return [
        PlanInfo(
            id=plan.pk,
            name=plan.name,
            stripe_id=plan.stripe_id,
            cost=plan.cost,
            currency=plan.currency,
            interval=plan.interval,
            interval_count=plan.interval_count,
            visible=plan.visible,
        )
        for plan in PaymentPlan.objects.order_by("pk")
    ]


def mark_dead_runs(now):
    IntegrityRun.objects.filter(
        status=IntegrityRun.Status.RUNNING, started_at__lt=now - RUN_TIMEOUT
    ).update(
        status=IntegrityRun.Status.FAILED,
        finished_at=now,
        error="The run never finished. Its worker probably stopped.",
    )


def is_running():
    return IntegrityRun.objects.filter(status=IntegrityRun.Status.RUNNING).exists()


def start(run, now):
    """Save `run` as running, or raise AlreadyRunning if another run is.

    One run at a time, member re-checks included: two runs recording the
    same issue at once would both try to create it.
    """
    IntegrityLock.objects.get_or_create(pk=1)
    with transaction.atomic():
        # Taken before anything is read, so a run starting at the same moment
        # waits here until this one is saved, and then sees it.
        IntegrityLock.objects.filter(pk=1).update(taken_at=now)
        mark_dead_runs(now)
        if is_running():
            raise AlreadyRunning()
        run.save()


def confirm_criticals(ctx, results, source, reader):
    """Read both sides again for each critical finding before it's recorded.

    The members are read after Stripe, so a webhook that lands mid-run shows
    on both sides. A change made after Stripe was read shows on the member's
    side only, though: a member who cancels mid-run looks like "cancelling
    here, renews in Stripe". A critical finding is emailed about at once, so
    the subscriptions it concerns are fetched again and its member reloaded.
    If anything changed, or couldn't be fetched, the member and subscriptions
    are deferred to the next run: their findings are dropped and their issues
    left as they are.

    Returns why some findings couldn't be confirmed, if any couldn't.
    """
    critical = [
        finding
        for findings in results.findings.values()
        for finding in findings
        if finding.severity == Severity.CRITICAL
    ]
    seen = {local.profile_id: local for local in ctx.local}
    profile_ids = sorted({f.profile_id for f in critical if f.profile_id is not None})
    reloaded = {}
    if profile_ids:
        reloaded = {local.profile_id: local for local in source.load(profile_ids)}

    fetched = {}
    errors = []

    def unchanged_in_stripe(subscription_id):
        if subscription_id not in fetched:
            try:
                data = reader.call(
                    stripe.Subscription.retrieve,
                    subscription_id,
                    expand=["latest_invoice"],
                )
                fetched[subscription_id] = parse_subscription(data)
            except (StripeBudgetExceeded, stripe.error.StripeError) as error:
                if is_missing(error):
                    fetched[subscription_id] = None
                else:
                    errors.append(
                        f"couldn't confirm {subscription_id}: {describe_error(error)}"
                    )
                    fetched[subscription_id] = error
        fresh = fetched[subscription_id]
        if isinstance(fresh, Exception):
            return False
        return fresh == ctx.snapshot.subscriptions.get(subscription_id)

    deferred_profiles = set()
    deferred_refs = set()
    for finding in critical:
        subscription_ids = set()
        if finding.stripe_ref.startswith("sub_"):
            subscription_ids.add(finding.stripe_ref)
        member = seen.get(finding.profile_id)
        if member is not None and member.subscription_id:
            subscription_ids.add(member.subscription_id)

        confirmed = all(unchanged_in_stripe(ref) for ref in sorted(subscription_ids))
        if member is not None and reloaded.get(member.profile_id) != member:
            confirmed = False
        if confirmed:
            continue
        if member is not None:
            deferred_profiles.add(member.profile_id)
        deferred_refs |= subscription_ids

    if deferred_profiles or deferred_refs:
        ctx.deferred_profiles |= deferred_profiles
        ctx.deferred_refs |= deferred_refs
        for key, findings in results.findings.items():
            results.findings[key] = [
                finding
                for finding in findings
                if finding.profile_id not in deferred_profiles
                and finding.stripe_ref not in deferred_refs
            ]
    return errors


@dataclasses.dataclass
class RunOutcome:
    run: IntegrityRun
    # (source name, CheckContext, CheckResults) per source checked.
    checked: list = dataclasses.field(default_factory=list)
    recorded: list = dataclasses.field(default_factory=list)


def run(
    trigger,
    user=None,
    profile=None,
    dry_run=False,
    notify=True,
    reader=None,
    sources=SOURCES,
):
    """Run the checks once and return a RunOutcome.

    `profile` limits the run to one member: only their customer is fetched,
    account-wide checks are skipped and only their issues can resolve.
    `dry_run` writes nothing and sends nothing.
    """
    now = timezone.now()
    run = IntegrityRun(
        trigger=trigger, triggered_by=user, profile=profile, started_at=now
    )
    if not dry_run:
        start(run, now)

    outcome = RunOutcome(run=run)
    try:
        _execute(outcome, now, profile, dry_run, reader, sources)
    except Exception as error:
        capture_exception(error)
        logger.exception("Integrity run %s failed", run.pk)
        run.status = IntegrityRun.Status.FAILED
        run.error = str(error) or type(error).__name__

    run.finished_at = timezone.now()
    if not dry_run:
        run.save()
        if notify and run.is_full:
            emails.after_run(run)
    return outcome


def _execute(outcome, now, profile, dry_run, reader, sources):
    run = outcome.run
    member_scope = profile is not None
    profile_ids = [profile.pk] if member_scope else None

    stripe.api_key = config.STRIPE_SECRET_KEY
    if reader is None:
        reader = StripeReader(rate=config.BILLING_AUDIT_MAX_RPS)

    # Which subscriptions to fetch is decided before Stripe is read...
    tracked = set()
    customer_id = None
    for source in sources:
        for local in source.load(profile_ids):
            if local.subscription_id:
                tracked.add(local.subscription_id)
            if member_scope and local.customer_id:
                customer_id = local.customer_id

    plans = load_plans()
    snapshot = build_snapshot(
        reader,
        tracked_subscription_ids=tracked,
        price_ids=[plan.stripe_id for plan in plans if plan.stripe_id],
        now=now,
        customer_id=customer_id,
        full=not member_scope,
    )
    run.stripe_requests = reader.requests

    skipped = []
    incomplete = bool(snapshot.fetch_errors)
    for error in snapshot.fetch_errors:
        skipped.append({"check": "", "source": "", "reason": error})

    for index, source in enumerate(sources):
        # ...but what each member's record says is read after, so a webhook
        # that landed while Stripe was being read shows on both sides instead
        # of as drift.
        local = source.load(profile_ids)
        ctx = CheckContext(
            local=local,
            snapshot=snapshot,
            plans=plans,
            now=now,
            settle=timedelta(0) if member_scope else SETTLE,
            webhook_url=webhook_url(),
            handled_events=HANDLED_EVENTS,
            member_scope=member_scope,
        )
        defer_unsettled(ctx)
        results = run_checks(
            ctx, source.name, include_account=index == 0, on_error=capture_exception
        )
        if not member_scope:
            for reason in confirm_criticals(ctx, results, source, reader):
                incomplete = True
                skipped.append({"check": "", "source": source.name, "reason": reason})
        outcome.checked.append((source.name, ctx, results))
        run.members_checked = max(run.members_checked, len(local))

        for (result_source, check), part in results.skipped.items():
            incomplete = incomplete or part.incomplete
            skipped.append(
                {"check": check, "source": result_source, "reason": part.reason}
            )

        if not dry_run:
            recorded = record_results(
                results,
                now=now,
                scope_profile_id=profile.pk if member_scope else None,
                deferred_profiles=ctx.deferred_profiles,
                deferred_refs=ctx.deferred_refs,
            )
            outcome.recorded.append(recorded)
            run.new_issues += len(recorded.new)
            run.resolved_issues += len(recorded.resolved)

    # Again, now that the confirmations are counted too.
    run.stripe_requests = reader.requests
    run.skipped_checks = skipped
    if not dry_run:
        issues = open_issues()
        if member_scope:
            issues = issues.filter(profile=profile)
        run.open_issues = issues.count()

    subscriptions = snapshot.skipped.get(SUBSCRIPTIONS)
    if subscriptions is not None and subscriptions.incomplete:
        run.status = IntegrityRun.Status.FAILED
        run.error = f"Couldn't read subscriptions from Stripe: {subscriptions.reason}"
    elif incomplete:
        run.status = IntegrityRun.Status.INCOMPLETE
    else:
        run.status = IntegrityRun.Status.COMPLETE
