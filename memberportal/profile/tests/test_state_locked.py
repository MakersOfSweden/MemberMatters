"""Profile.set_state_locked — the admin lock on automated state changes.

`state_locked` is the flag both state machines consult first: a locked member
is refused activation by complete_signup and refused deactivation by
complete_cancel. Those refusals are covered in the state-machine files; this
one covers the setter that is supposed to produce the flag, which the rest of
the suite has so far set as a factory field instead.

Locking is refused for an active member and allowed everywhere else. The lock
guards against *automated* activation, so it only means anything while a
member is still noob or inactive — see TestLockingASignupInProgress, which is
that use case end to end.
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


class TestLockingAnActiveMember:
    """Refused: there is no coherent "active and locked" state.

    An active member has already been activated, so the lock has nothing left
    to guard. Allowing it produced a flag that read as protection but was
    cleared by the next admin activation — M43.
    """

    def test_an_active_member_cannot_be_locked(self):
        profile = ProfileFactory(active=True)

        assert profile.set_state_locked(True) is False

        profile.refresh_from_db()
        assert profile.state_locked is False

    def test_the_refusal_is_not_audited(self):
        # Nothing happened, so nothing is written — the refusal returns before
        # the log_event calls.
        profile = ProfileFactory(active=True)

        profile.set_state_locked(True)

        assert not lock_events(profile).exists()

    def test_the_in_memory_instance_is_left_alone(self):
        profile = ProfileFactory(active=True)

        profile.set_state_locked(True)

        assert profile.state_locked is False  # no refresh_from_db

    def test_unlocking_an_active_member_still_works(self):
        # Defence in depth: the API can no longer produce active+locked, but
        # an operator must still be able to clear one that exists — a direct
        # DB edit, or a row predating the invariant.
        profile = ProfileFactory(active=True, state_locked=True)

        assert profile.set_state_locked(False) is True

        profile.refresh_from_db()
        assert profile.state_locked is False


class TestLockingASignupInProgress:
    """A live subscription is not grounds for refusal.

    The old rule also refused any member whose subscription_status was not
    "inactive", which ruled out the member the lock is actually for: a noob
    mid-signup whose invoice is about to clear. Refusal is on `state` alone.
    """

    @pytest.mark.parametrize("status", ["active", "pending", "cancelling"])
    def test_a_noob_with_a_live_subscription_can_be_locked(self, status):
        profile = ProfileFactory(subscription_status=status)

        assert profile.set_state_locked(True) is True

        profile.refresh_from_db()
        assert profile.state_locked is True

    def test_an_inactive_member_can_be_locked(self):
        profile = ProfileFactory(inactive=True, subscription_active=True)

        assert profile.set_state_locked(True) is True

        profile.refresh_from_db()
        assert profile.state_locked is True

    def test_a_locked_signup_is_not_activated_when_the_invoice_clears(self):
        # The use case end to end: an operator locks a member mid-signup, and
        # the invoice.paid webhook must then leave them alone.
        from profile.models import CompleteSignupOutcome, SignupTriggeredBy

        profile = ProfileFactory(subscription_pending=True)
        assert profile.set_state_locked(True) is True

        profile.subscription_status = "active"
        profile.save(update_fields=["subscription_status"])
        result = profile.complete_signup(SignupTriggeredBy.INVOICE_PAID)

        assert result.outcome == CompleteSignupOutcome.STATE_LOCKED
        profile.refresh_from_db()
        assert profile.state == "noob"

    @pytest.mark.override_config(
        TERMS_ACCEPTANCE_CARDS="[]",
        MOODLE_INDUCTION_ENABLED=False,
        CANVAS_INDUCTION_ENABLED=False,
        REQUIRE_ACCESS_CARD=False,
    )
    def test_an_unlocked_member_in_the_same_position_is_activated(self):
        # The control: without the lock the same webhook activates them, which
        # is what makes the test above meaningful rather than vacuous.
        from profile.models import CompleteSignupOutcome, SignupTriggeredBy

        profile = ProfileFactory(subscription_active=True)

        result = profile.complete_signup(SignupTriggeredBy.INVOICE_PAID)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED
        profile.refresh_from_db()
        assert profile.state == "active"


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
