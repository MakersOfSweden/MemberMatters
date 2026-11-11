from django.core.management.base import BaseCommand, CommandError

from integrity import runner
from integrity.models import IntegrityRun
from profile.models import Profile


class Command(BaseCommand):
    help = (
        "Compare membership subscriptions with Stripe and record any drift, as "
        "the nightly Celery task does. For installs without Celery, run it daily "
        "from cron. Only reads: it never changes a member or anything in Stripe."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--member",
            type=int,
            metavar="USER_ID",
            help="Check only this member, by user ID.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what the checks find without recording it or sending email.",
        )
        parser.add_argument(
            "--no-email",
            action="store_true",
            help="Record the findings but don't email EMAIL_ADMIN.",
        )

    def handle(self, *args, **options):
        if not runner.is_enabled():
            raise CommandError(
                "The billing check is off. It needs BILLING_AUDIT_ENABLED, "
                "ENABLE_STRIPE, ENABLE_STRIPE_MEMBERSHIP_PAYMENTS and "
                "STRIPE_SECRET_KEY."
            )

        profile = None
        if options["member"] is not None:
            profile = Profile.objects.filter(user_id=options["member"]).first()
            if profile is None:
                raise CommandError(f"No member with user ID {options['member']}.")

        try:
            outcome = runner.run(
                (
                    IntegrityRun.Trigger.MEMBER
                    if profile
                    else IntegrityRun.Trigger.COMMAND
                ),
                profile=profile,
                dry_run=options["dry_run"],
                notify=not options["no_email"],
            )
        except runner.AlreadyRunning:
            raise CommandError("Another billing check is running. Try again later.")

        run = outcome.run
        self.stdout.write(
            f"Billing check {run.status}: {run.members_checked} members checked, "
            f"{run.stripe_requests} Stripe requests."
        )
        if run.error:
            self.stdout.write(f"Error: {run.error}")
        for entry in run.skipped_checks:
            label = entry["check"] or "fetch"
            self.stdout.write(f"Skipped {label}: {entry['reason']}")

        if options["dry_run"]:
            for source, _ctx, results in outcome.checked:
                for (_source, check), findings in results.findings.items():
                    for finding in findings:
                        self.stdout.write(
                            f"[{finding.severity}] {check} ({_source}): "
                            f"{finding.message} — MemberMatters: {finding.mm or '-'}; "
                            f"Stripe: {finding.stripe or '-'}"
                        )
        else:
            self.stdout.write(
                f"{run.new_issues} new, {run.resolved_issues} resolved, "
                f"{run.open_issues} open."
            )

        if run.status == IntegrityRun.Status.FAILED:
            raise CommandError("The billing check failed.")
