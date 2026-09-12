"""Profile.save — the hand-rolled half of the model's timestamp handling.

`modified` is not an auto_now field; save() sets it by hand, and re-adds it to
a caller's `update_fields` so that the targeted writes the state machine makes
(`save(update_fields=["state"])`) don't leave the timestamp stale. Both halves
of that are asserted here because neither is expressed by a field declaration
where Django would maintain it — which also makes this the part most likely to
drift on a framework upgrade.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from profile.models import Profile
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def stored(profile):
    return Profile.objects.get(pk=profile.pk)


def backdate(profile, days=1):
    """Move `modified` into the past without going through save()."""
    Profile.objects.filter(pk=profile.pk).update(
        modified=timezone.now() - timedelta(days=days)
    )
    return stored(profile).modified


class TestModifiedTimestamp:
    def test_a_targeted_save_still_advances_modified(self):
        profile = ProfileFactory()
        before = backdate(profile)

        profile.state = "active"
        profile.save(update_fields=["state"])

        assert stored(profile).modified > before

    def test_the_named_field_is_still_written(self):
        # The guard against "fixing" the above by widening the UPDATE.
        profile = ProfileFactory()

        profile.state = "active"
        profile.save(update_fields=["state"])

        assert stored(profile).state == "active"

    def test_an_unrestricted_save_advances_modified(self):
        profile = ProfileFactory()
        before = backdate(profile)

        profile.save()

        assert stored(profile).modified > before

    def test_modified_is_not_duplicated_when_already_named(self):
        profile = ProfileFactory()
        before = backdate(profile)

        profile.save(update_fields=["modified"])

        assert stored(profile).modified > before


class TestEmptyUpdateFields:
    """`update_fields=[]` means "write nothing" — not "write modified"."""

    def test_nothing_is_written(self):
        profile = ProfileFactory()
        before = backdate(profile)

        profile.first_name = "Renamed"
        profile.save(update_fields=[])

        reread = stored(profile)
        assert reread.first_name != "Renamed"
        assert reread.modified == before
