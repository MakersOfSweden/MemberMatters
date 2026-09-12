"""Guards on the factories themselves.

Mostly one thing: every unique column must be sequenced. A factory that
hardcodes a unique value works fine for a single-object test and then fails on
the first test that needs two, which is a confusing place to discover it.
"""

import pytest

from access.models import Doors, Interlock
from profile.models import Profile
from tests.factories import (
    DoorFactory,
    InterlockFactory,
    ProfileFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def test_two_members_can_coexist():
    # Profile.screen_name and User.email are both unique; a fixed value in
    # either would raise IntegrityError here.
    first = ProfileFactory()
    second = ProfileFactory()

    assert Profile.objects.count() == 2
    assert first.screen_name != second.screen_name
    assert first.user.email != second.user.email


def test_two_devices_can_coexist():
    # Doors/Interlock have unique name and serial_number.
    DoorFactory()
    DoorFactory()
    InterlockFactory()
    InterlockFactory()

    assert Doors.objects.count() == 2
    assert Interlock.objects.count() == 2


def test_user_password_is_hashed_by_the_real_manager():
    # The factory routes through UserManager.create_user rather than
    # Model.objects.create, so tests exercise the same path the app uses.
    user = UserFactory(password="hunter2")

    assert user.password != "hunter2"
    assert user.check_password("hunter2")


def test_email_is_normalised_by_the_manager():
    user = UserFactory(email="Member@EXAMPLE.COM")

    # normalize_email() lowercases the domain only — asserting the real
    # behaviour, not what one might assume it does.
    assert user.email == "Member@example.com"


def test_member_defaults_to_a_fresh_noob():
    profile = ProfileFactory()

    assert profile.state == "noob"
    assert profile.subscription_status == "inactive"
    assert profile.state_locked is False
    assert profile.rfid is None
    assert profile.last_induction is None
    assert profile.terms_accepted_at is None


@pytest.mark.parametrize(
    "trait,field,expected",
    [
        ("active", "state", "active"),
        ("inactive", "state", "inactive"),
        ("accountonly", "state", "accountonly"),
        ("subscription_active", "subscription_status", "active"),
        ("subscription_pending", "subscription_status", "pending"),
        ("subscription_cancelling", "subscription_status", "cancelling"),
    ],
)
def test_state_traits(trait, field, expected):
    profile = ProfileFactory(**{trait: True})

    assert getattr(profile, field) == expected


def test_rfid_trait_allocates_unique_tags():
    first = ProfileFactory(with_rfid=True)
    second = ProfileFactory(with_rfid=True)

    assert first.rfid and second.rfid
    assert first.rfid != second.rfid


def test_staff_trait_reaches_the_user():
    profile = ProfileFactory(user__staff_user=True)

    assert profile.user.staff is True
    assert profile.user.admin is False


def test_no_network_guard_blocks_outbound_connections(_no_network):
    import socket

    from conftest import NetworkAccessInTestError

    with pytest.raises(NetworkAccessInTestError):
        socket.create_connection(("api.stripe.com", 443), timeout=1)
