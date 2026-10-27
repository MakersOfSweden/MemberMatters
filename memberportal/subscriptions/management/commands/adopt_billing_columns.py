"""Bring every member's subscription rows in line with their billing columns.

Run it after a rollback to code from before the Subscription table, before
deploying the newer code again: the older code wrote only the columns. Safe to
run at any time, since a member whose rows already match is left alone.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from profile.models import Profile
from subscriptions import records


class Command(BaseCommand):
    help = "Bring every member's subscription rows in line with their billing columns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count the members whose rows would change, and change nothing.",
        )

    def handle(self, *args, dry_run=False, **options):
        candidates = list(
            Profile.objects.filter(records.has_billing_columns_q())
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        changed = 0
        for pk in candidates:
            with transaction.atomic():
                profile = Profile.objects.select_for_update().get(pk=pk)
                if dry_run:
                    changed += not records.mirror_matches(profile)
                else:
                    changed += records.adopt_profile_columns(profile)

        verb = "Would change" if dry_run else "Changed"
        self.stdout.write(
            f"{verb} the subscriptions of {changed} of {len(candidates)} members."
        )
