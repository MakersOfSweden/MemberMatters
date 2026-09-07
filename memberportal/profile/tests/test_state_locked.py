"""Profile.set_state_locked — the admin lock on automated state changes.

`state_locked` is the flag both state machines consult first: a locked member
is refused activation by complete_signup and refused deactivation by
complete_cancel. Those refusals are covered in the state-machine files; this
one covers the setter that is supposed to produce the flag, which the rest of
the suite has so far set as a factory field instead.

Locking is allowed from any state. It used to be refused for an active member
or one with a live subscription, which made the flag's primary use case
unreachable — see TestGrandfathering, which is that use case end to end.
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


class TestLockingFromAnyState:
    """Locking has no preconditions.

    The refusal these replace (active, or any subscription_status other than
    "inactive") ruled out precisely the state the flag exists to protect. The
    lock decouples the access decision from the billing decision, so neither
    is grounds for refusing it — M43.
    """

    def test_an_active_member_can_be_locked(self):
        profile = ProfileFactory(active=True)

        assert profile.set_state_locked(True) is True

        profile.refresh_from_db()
        assert profile.state_locked is True

    @pytest.mark.parametrize("status", ["active", "pending", "cancelling"])
    def test_a_member_with_a_live_subscription_can_be_locked(self, status):
        # "cancelling" is the one that mattered most: a member whose
        # subscription is on its way out is exactly who an operator reaches
        # for the lock to protect, and it was refused.
        profile = ProfileFactory(active=True, subscription_status=status)

        assert profile.set_state_locked(True) is True

        profile.refresh_from_db()
        assert profile.state_locked is True

    def test_unlocking_an_active_member_still_works(self):
        profile = ProfileFactory(active=True, state_locked=True)

        assert profile.set_state_locked(False) is True

        profile.refresh_from_db()
        assert profile.state_locked is False


class TestGrandfathering:
    """The use case the lock was built for, end to end.

    A member paying out-of-band is active and carries a Stripe subscription
    that is about to disappear. An operator locks them; the deletion webhook
    must then leave their access alone.
    """

    def test_a_locked_active_member_survives_subscription_deletion(self):
        from profile.models import CancelTriggeredBy, CompleteCancelOutcome

        profile = ProfileFactory(active=True, subscription_active=True)
        assert profile.set_state_locked(True) is True

        result = profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert result.outcome == CompleteCancelOutcome.STATE_LOCKED
        profile.refresh_from_db()
        assert profile.state == "active"

    def test_an_unlocked_member_in_the_same_position_is_deactivated(self):
        # The control: without the lock the same webhook removes access, which
        # is what makes the test above meaningful rather than vacuous.
        from profile.models import CancelTriggeredBy, CompleteCancelOutcome

        profile = ProfileFactory(active=True, subscription_active=True)

        result = profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert result.outcome == CompleteCancelOutcome.DEACTIVATED
        profile.refresh_from_db()
        assert profile.state == "inactive"


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
