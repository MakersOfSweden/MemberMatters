"""Profile.set_state_locked — the admin lock on automated state changes.

`state_locked` is the flag both state machines consult first: a locked member
is refused activation by complete_signup and refused deactivation by
complete_cancel. Those refusals are covered in the state-machine files; this
one covers the setter that is supposed to produce the flag, which the rest of
the suite has so far set as a factory field instead.

The setter is not symmetric with the flag's use, and that asymmetry is the
subject of most of what follows — see TestLockingIsRefused.
"""

import pytest

from profile.models import UserEventLog
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def lock_events(profile):
    return UserEventLog.objects.filter(
        user=profile.user, description__contains="Account state"
    )


class TestLocking:
    def test_a_noob_with_no_subscription_can_be_locked(self):
        profile = ProfileFactory()

        assert profile.set_state_locked(True) is True

        profile.refresh_from_db()
        assert profile.state_locked is True

    def test_the_in_memory_instance_is_updated_too(self):
        # The write goes to a re-read copy taken under select_for_update, so
        # `self` would otherwise still report the old value to its caller.
        profile = ProfileFactory()

        profile.set_state_locked(True)

        assert profile.state_locked is True  # no refresh_from_db

    def test_unlocking_succeeds(self):
        profile = ProfileFactory(state_locked=True)

        assert profile.set_state_locked(False) is True

        profile.refresh_from_db()
        assert profile.state_locked is False

    @pytest.mark.parametrize("locked", [True, False])
    def test_setting_it_to_what_it_already_is_is_a_no_op(self, locked):
        profile = ProfileFactory(state_locked=locked)

        assert profile.set_state_locked(locked) is True

        # Reported as success, but nothing was written and nothing audited —
        # the early return happens before the log_event calls.
        assert not lock_events(profile).exists()


class TestLockingIsRefused:
    """The refusal rule, which is wider than the flag's own use.

    Locking is refused for an active member or one with any subscription that
    is not "inactive". Both halves are asserted here as current behaviour;
    whether the first half is intended is the open question in M43, because
    complete_cancel's lock branch — and its tests — are built on exactly the
    active+locked state this refuses to create.
    """

    def test_an_active_member_cannot_be_locked(self):
        profile = ProfileFactory(active=True)

        assert profile.set_state_locked(True) is False

        profile.refresh_from_db()
        assert profile.state_locked is False

    @pytest.mark.parametrize("status", ["active", "pending", "cancelling"])
    def test_a_member_with_a_live_subscription_cannot_be_locked(self, status):
        # "cancelling" is the interesting one: a member whose subscription is
        # on its way out is precisely who an operator would want to
        # grandfather, and it is refused.
        profile = ProfileFactory(subscription_status=status)

        assert profile.set_state_locked(True) is False

        profile.refresh_from_db()
        assert profile.state_locked is False

    def test_the_refusal_does_not_apply_to_unlocking(self):
        # The guard is `if locked and (...)`, so unlocking is always allowed.
        # Reaching this state at all takes a factory — see the class docstring.
        profile = ProfileFactory(active=True, state_locked=True)

        assert profile.set_state_locked(False) is True

        profile.refresh_from_db()
        assert profile.state_locked is False

    def test_no_sequence_of_calls_produces_an_active_locked_member(self):
        """Pins M43: the state complete_cancel's lock branch exists to serve
        cannot be built through this API.

        Locking first and activating afterwards does not work either — the
        admin-override path in complete_signup clears the flag on the way
        through, which is asserted in the signup state-machine file.
        """
        profile = ProfileFactory()
        assert profile.set_state_locked(True) is True

        # Subscribing now blocks any further lock change from taking effect,
        # and activating clears the lock. Either way the member never arrives
        # at active+locked.
        profile.state = "active"
        profile.save(update_fields=["state"])

        assert profile.set_state_locked(True) is False


class TestAuditTrail:
    def test_an_admin_lock_is_recorded_against_both_parties(self, admin_request):
        profile = ProfileFactory()

        profile.set_state_locked(True, request=admin_request)

        assert lock_events(profile).count() == 1
        assert "locked by admin" in lock_events(profile).first().description
        # And the operator's own log carries who they did it to.
        operator_events = UserEventLog.objects.filter(user=admin_request.user)
        assert operator_events.count() == 1
        assert profile.get_full_name() in operator_events.first().description

    def test_a_systemic_change_records_only_the_member_side(self):
        # request=None is the path taken by anything that isn't an operator
        # acting in the admin UI.
        profile = ProfileFactory()

        profile.set_state_locked(True)

        assert lock_events(profile).count() == 1
        assert UserEventLog.objects.exclude(user=profile.user).count() == 0

    def test_unlocking_says_unlocked(self):
        profile = ProfileFactory(state_locked=True)

        profile.set_state_locked(False)

        assert "unlocked by admin" in lock_events(profile).first().description
