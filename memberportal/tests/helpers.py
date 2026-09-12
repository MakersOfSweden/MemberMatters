"""Shared test helpers.

Sits alongside `factories.py` for the same reason: these cross app boundaries,
and the alternative — a private copy per file — had already produced four
byte-identical definitions of `subjects_to`.
"""

import pytest

from tests.factories import DoorFactory, ProfileFactory

# The shipped constance defaults are NOT all-off: MOODLE_INDUCTION_ENABLED and
# REQUIRE_ACCESS_CARD both default True. Switching every signup requirement off
# lets a test about the state machine avoid satisfying can_signup as well, and
# lets a test about one requirement turn back on exactly that one.
NO_REQUIREMENTS = {
    "TERMS_ACCEPTANCE_CARDS": "[]",
    "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": False,
    "MOODLE_INDUCTION_ENABLED": False,
    "CANVAS_INDUCTION_ENABLED": False,
    "REQUIRE_ACCESS_CARD": False,
}


def only(**overrides):
    """override_config with every signup requirement off except those named."""
    return pytest.mark.override_config(**{**NO_REQUIREMENTS, **overrides})


def subjects_to(outbox, profile):
    """Subjects of the mail sent to this member, in send order."""
    return [
        message["Subject"] for message in outbox if message["To"] == profile.user.email
    ]


def member_with_a_door(**kwargs):
    """A member with an RFID tag holding default access to one door."""
    door = DoorFactory(all_members=True)
    profile = ProfileFactory(with_rfid=True, **kwargs)
    profile.add_default_access()
    return profile, door
