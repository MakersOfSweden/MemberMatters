"""One-off backfill: rewrite stored phone numbers to E.164.

After the 0023 migration tightened the phone regex to E.164, existing
rows are preserved as-is (Profile.save doesn't call full_clean, so the
validator never fires on legacy data). This command walks every profile
with a non-empty phone, attempts to parse it via ``profile.phone.to_e164``
with the operator-supplied fallback region, and rewrites rows that aren't
already E.164. Unparseable rows are logged and skipped — no row is ever
overwritten with a worse value.

Example:

    python3 manage.py backfill_phone_e164 --region AU
    python3 manage.py backfill_phone_e164 --region SE --dry-run
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from profile.models import Profile
from profile.phone import to_e164


# Matches the regex on Profile.phone (migration 0023). Pre-check so we
# can skip rows that already conform — keeps the command idempotent.
E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


class Command(BaseCommand):
    help = "Rewrite stored phone numbers to E.164 format using a fallback region."

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            required=True,
            help=(
                "ISO-3166 alpha-2 fallback region (e.g. AU, SE) used to "
                "interpret national-format numbers. Numbers already in "
                "international (+...) form are parsed without it."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        region = options["region"].strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", region):
            raise CommandError(
                f"--region must be an ISO-3166 alpha-2 code (got {region!r})"
            )
        dry_run = options["dry_run"]

        rewritten = 0
        unchanged = 0
        failed = 0
        already_e164 = 0

        qs = Profile.objects.exclude(phone="").only("id", "phone", "user__email")
        total = qs.count()

        for p in qs.select_related("user").iterator():
            raw = p.phone or ""
            if E164_RE.match(raw):
                already_e164 += 1
                continue

            try:
                normalised = to_e164(raw, region)
            except ValueError as exc:
                failed += 1
                self.stderr.write(
                    f"FAIL profile={p.id} email={p.user.email!r} "
                    f"phone={raw!r}: {exc}"
                )
                continue

            if normalised == raw:
                unchanged += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"DRY  profile={p.id} email={p.user.email!r} "
                    f"{raw!r} -> {normalised!r}"
                )
            else:
                # Per-row transaction so a single bad row can't roll back
                # the batch. update_fields keeps unrelated columns intact.
                with transaction.atomic():
                    p.phone = normalised
                    p.save(update_fields=["phone"])
                self.stdout.write(
                    f"OK   profile={p.id} email={p.user.email!r} "
                    f"{raw!r} -> {normalised!r}"
                )
            rewritten += 1

        action = "would rewrite" if dry_run else "rewrote"
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. scanned={total} {action}={rewritten} "
                f"already_e164={already_e164} unchanged={unchanged} "
                f"failed={failed}"
            )
        )
