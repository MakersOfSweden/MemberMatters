"""Profile.complete_signup — the membership activation state machine.

Highest blast radius in the codebase: access control and billing both hang off
`state`. CompleteSignupOutcome already enumerates the expected results, so the
branches read as a truth table.

Emails are asserted through the shared `outbox` fixture, which stands in for
the Postmark client. State-lock refusals are asserted through the UserEventLog
audit trail, since that is the sink an operator actually sees.
"""

import pytest

from profile.models import (
    CompleteSignupOutcome,
    Profile,
    SignupTriggeredBy,
    UserEventLog,
)
from tests.factories import DoorFactory, InterlockFactory, ProfileFactory

pytestmark = pytest.mark.django_db


# Every signup requirement switched off, so tests that are about the state
# machine don't have to satisfy can_signup as well. Tests about the
# requirements gate turn the relevant ones back on.
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
    return [
        message["Subject"] for message in outbox if message["To"] == profile.user.email
    ]


class TestShortCircuits:
    @only()
    def test_an_already_active_member_is_left_alone(self):
        profile = ProfileFactory(active=True)

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.ALREADY_ACTIVE
        profile.refresh_from_db()
        assert profile.state == "active"

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True, REQUIRE_ACCESS_CARD=True)
    def test_already_active_wins_over_every_other_check(self):
        # The active check runs first, so a member who is active but would
        # otherwise fail every gate is still reported ALREADY_ACTIVE rather
        # than NO_SUBSCRIPTION or REQUIREMENTS_UNMET.
        profile = ProfileFactory(active=True, rfid=None)

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.ALREADY_ACTIVE


class TestStateLock:
    @only()
    @pytest.mark.parametrize(
        "triggered_by",
        [
            SignupTriggeredBy.MEMBER_SELF_SERVE,
            SignupTriggeredBy.SUBSCRIPTION_CREATED,
            SignupTriggeredBy.INVOICE_PAID,
            SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE,
        ],
    )
    def test_a_locked_member_is_not_activated(self, triggered_by):
        profile = ProfileFactory(state_locked=True)

        result = profile.complete_signup(triggered_by)

        assert result.outcome == CompleteSignupOutcome.STATE_LOCKED
        profile.refresh_from_db()
        assert profile.state == "noob"
        assert profile.state_locked is True

    @only()
    def test_the_refusal_is_recorded_against_the_member(self):
        # Four sinks in the code (audit log, logger, Sentry, admin email);
        # the audit log is the one an operator actually sees.
        profile = ProfileFactory(state_locked=True)

        profile.complete_signup(SignupTriggeredBy.INVOICE_PAID)

        refusals = UserEventLog.objects.filter(
            user=profile.user, description__contains="state_locked refused activation"
        )
        assert refusals.count() == 1
        assert "triggered_by=invoice_paid" in refusals.first().description

    @only()
    def test_an_admin_override_does_not_clear_the_lock(self):
        # The override skips the gates the system inferred — billing, signup
        # requirements — not a decision an operator recorded. Only an
        # explicit unlock does that.
        profile = ProfileFactory(state_locked=True)

        result = profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert result.outcome == CompleteSignupOutcome.STATE_LOCKED
        profile.refresh_from_db()
        assert profile.state == "noob"
        assert profile.state_locked is True

    @only()
    def test_unlocking_first_is_what_lets_the_override_through(self):
        # The two-step an operator actually performs, and the control that
        # keeps the refusal above from passing for the wrong reason.
        profile = ProfileFactory(state_locked=True)

        assert profile.set_state_locked(False) is True
        result = profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED
        profile.refresh_from_db()
        assert profile.state == "active"


class TestTheLockedRow:
    """Every decision is made on the row re-read under select_for_update.

    The lock-and-re-read exists so a caller holding a stale instance — a
    webhook retry, a queued task — cannot drive the state machine from values
    that have since changed. Reading `self` instead of the re-read copy is
    invisible to every other test here, because they all act on an instance
    that already agrees with the database.
    """

    @only()
    def test_a_stale_instance_does_not_win_over_the_locked_row(self):
        profile = ProfileFactory()
        Profile.objects.filter(pk=profile.pk).update(state_locked=True)
        assert profile.state_locked is False  # stale in memory

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.STATE_LOCKED
        profile.refresh_from_db()
        assert profile.state == "noob"

    @only()
    def test_a_stale_instance_does_not_reactivate_an_active_member(self):
        profile = ProfileFactory()
        Profile.objects.filter(pk=profile.pk).update(state="active")

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.ALREADY_ACTIVE


class TestSubscriptionGate:
    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    @pytest.mark.parametrize("subscription_status", ["inactive", "cancelling"])
    def test_no_usable_subscription_blocks_activation(self, subscription_status):
        profile = ProfileFactory(subscription_status=subscription_status)

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.NO_SUBSCRIPTION
        profile.refresh_from_db()
        assert profile.state == "noob"

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False)
    def test_the_subscription_gate_is_skipped_when_stripe_is_off(self):
        # A space that doesn't bill through Stripe must still be able to
        # activate members who have no subscription at all.
        profile = ProfileFactory(subscription_status="inactive")

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_an_admin_override_bypasses_the_subscription_gate(self):
        profile = ProfileFactory(subscription_status="inactive")

        result = profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED


class TestRequirementsGate:
    @only(REQUIRE_ACCESS_CARD=True, MOODLE_INDUCTION_ENABLED=True)
    def test_unmet_requirements_are_reported_back_to_the_caller(self):
        profile = ProfileFactory(rfid=None, last_induction=None)

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.REQUIREMENTS_UNMET
        # The exact list, because the signup wizard routes on it.
        assert result.required_steps == ["induction", "accessCard"]
        profile.refresh_from_db()
        assert profile.state == "noob"

    @only(REQUIRE_ACCESS_CARD=True, MOODLE_INDUCTION_ENABLED=True)
    def test_an_admin_override_bypasses_the_requirements_gate(self):
        profile = ProfileFactory(rfid=None, last_induction=None)

        result = profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED


class TestAwaitingPayment:
    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_a_pending_subscription_parks_the_member(
        self, django_capture_on_commit_callbacks, outbox
    ):
        profile = ProfileFactory(subscription_pending=True)

        with django_capture_on_commit_callbacks(execute=True):
            result = profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)

        assert result.outcome == CompleteSignupOutcome.AWAITING_PAYMENT
        profile.refresh_from_db()
        assert profile.state == "noob"
        assert profile.pending_signup_email_sent is True
        assert subjects_to(outbox, profile) == [
            "Your signup has been received — awaiting payment"
        ]

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_the_awaiting_payment_email_is_sent_only_once(
        self, django_capture_on_commit_callbacks, outbox
    ):
        # pending_signup_email_sent is set pessimistically: a dropped email is
        # preferred over a duplicate when the member re-enters the flow.
        profile = ProfileFactory(subscription_pending=True)

        with django_capture_on_commit_callbacks(execute=True):
            profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)
        with django_capture_on_commit_callbacks(execute=True):
            result = profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)

        assert result.outcome == CompleteSignupOutcome.AWAITING_PAYMENT
        assert subjects_to(outbox, profile) == [
            "Your signup has been received — awaiting payment"
        ]

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_the_email_does_not_fire_without_a_commit(self, outbox):
        # Guards the assertions above: the notification rides
        # transaction.on_commit, so a test that forgets to flush the callbacks
        # would pass vacuously.
        profile = ProfileFactory(subscription_pending=True)

        profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)

        assert subjects_to(outbox, profile) == []

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_payment_arriving_later_activates_the_member(self):
        profile = ProfileFactory(subscription_pending=True)
        profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)

        # invoice.paid flips the subscription to active, then re-enters.
        profile.subscription_status = "active"
        profile.save(update_fields=["subscription_status"])
        result = profile.complete_signup(SignupTriggeredBy.INVOICE_PAID)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED
        profile.refresh_from_db()
        assert profile.state == "active"


class TestActivation:
    @only()
    def test_a_successful_signup_activates_and_is_audited(self):
        profile = ProfileFactory()

        result = profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED
        assert result.required_steps == []
        profile.refresh_from_db()
        assert profile.state == "active"
        assert UserEventLog.objects.filter(
            user=profile.user,
            description__contains="Activated via member_self_serve (from noob)",
        ).exists()

    @only()
    def test_default_access_is_granted_on_activation(self):
        default_door = DoorFactory(all_members=True)
        default_interlock = InterlockFactory(all_members=True)
        opt_in_door = DoorFactory(all_members=False)
        profile = ProfileFactory()

        profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert list(profile.doors.all()) == [default_door]
        assert list(profile.interlocks.all()) == [default_interlock]
        assert opt_in_door not in profile.doors.all()

    @only()
    def test_an_admin_override_also_grants_default_access(self):
        default_door = DoorFactory(all_members=True)
        profile = ProfileFactory()

        profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert list(profile.doors.all()) == [default_door]

    @only()
    def test_activation_syncs_the_members_devices(self, device_commands):
        # sync_access() pushes the new tag list to every device the member can
        # use — without it an "active" member still can't open the door.
        door = DoorFactory(all_members=True)
        profile = ProfileFactory()

        profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    @only()
    def test_a_noob_activation_sends_the_welcome_email(self, outbox):
        # previous_state == "noob" takes the application/welcome branch rather
        # than the "access re-enabled" branch.
        profile = ProfileFactory()

        profile.complete_signup(SignupTriggeredBy.MEMBER_SELF_SERVE)

        assert any(
            subject.startswith("Welcome to") for subject in subjects_to(outbox, profile)
        )

    @only()
    def test_reactivating_an_inactive_member_takes_the_other_email_branch(self, outbox):
        profile = ProfileFactory(inactive=True)

        result = profile.complete_signup(SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE)

        assert result.outcome == CompleteSignupOutcome.ACTIVATED
        subjects = subjects_to(outbox, profile)
        assert not any(subject.startswith("Welcome to") for subject in subjects)
        assert any("site access has been enabled" in s for s in subjects)
