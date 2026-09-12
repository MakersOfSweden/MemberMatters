"""Profile.complete_cancel — the membership cancellation state machine.

The interesting part is not the four CompleteCancelOutcome values but what
each one does to the member's default door/interlock rows. Three paths reach
cancellation and only two of them go through deactivate():

- "active"                  -> deactivate(), which keeps the M2M rows because
                               get_tags() already filters on state="active"
- "noob" / "accountonly"    -> bypass deactivate(), so they must drop the
                               pre-staged default-access rows themselves
- "inactive"                -> already done

Dropping them has to be a targeted .remove() of the all_members devices, not a
blanket .clear(), or a bespoke admin grant is silently destroyed on cancel.
"""

import pytest

from profile.models import CancelTriggeredBy, CompleteCancelOutcome, UserEventLog
from tests.factories import DoorFactory, InterlockFactory, ProfileFactory

pytestmark = pytest.mark.django_db


def subjects_to(outbox, profile):
    return [
        message["Subject"] for message in outbox if message["To"] == profile.user.email
    ]


class TestDeactivation:
    @pytest.mark.parametrize(
        "triggered_by",
        [
            CancelTriggeredBy.MEMBER_SELF_CANCEL,
            CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL,
            CancelTriggeredBy.SUBSCRIPTION_DELETED,
        ],
    )
    def test_an_active_member_is_deactivated(self, triggered_by):
        profile = ProfileFactory(active=True)

        result = profile.complete_cancel(triggered_by)

        assert result.outcome == CompleteCancelOutcome.DEACTIVATED
        assert result.previous_state == "active"
        profile.refresh_from_db()
        assert profile.state == "inactive"

    def test_deactivation_is_audited(self):
        profile = ProfileFactory(active=True)

        profile.complete_cancel(CancelTriggeredBy.MEMBER_SELF_CANCEL)

        assert UserEventLog.objects.filter(
            user=profile.user,
            description__contains="Cancelled via member_self_cancel",
        ).exists()

    def test_deactivation_syncs_the_members_devices(self, device_commands):
        # The mirror of activation: an "inactive" member whose devices still
        # hold their tag can keep opening the door.
        door = DoorFactory(all_members=True)
        profile = ProfileFactory(active=True)
        profile.add_default_access()

        profile.complete_cancel(CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL)

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_an_active_member_keeps_their_access_rows(self):
        # Deliberate: get_tags() filters by state="active", so the rows grant
        # nothing while inactive, and keeping them makes reactivation a pure
        # state flip.
        door = DoorFactory(all_members=True)
        profile = ProfileFactory(active=True)
        profile.add_default_access()

        profile.complete_cancel(CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL)

        assert list(profile.doors.all()) == [door]

    def test_a_deleted_subscription_sends_the_subscription_ended_email(self, outbox):
        # Distinct from the generic "access disabled" email: this one explains
        # that the membership payment is what lapsed.
        profile = ProfileFactory(active=True)

        profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert any(
            "subscription has ended" in message["HtmlBody"]
            for message in outbox
            if message["To"] == profile.user.email
        )

    def test_an_admin_cancel_sends_the_generic_access_disabled_email(self, outbox):
        profile = ProfileFactory(active=True)

        profile.complete_cancel(CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL)

        bodies = [
            message["HtmlBody"]
            for message in outbox
            if message["To"] == profile.user.email
        ]
        assert bodies
        assert not any("subscription has ended" in body for body in bodies)


class TestStateLock:
    """Defence in depth — the API cannot produce an active locked member.

    set_state_locked refuses to lock an active member, and a locked member
    cannot be activated, so every test below builds the state by writing the
    column directly. The branch is kept because a direct DB edit or a row
    predating the invariant can still reach it, and silently deactivating
    such a member is the worse failure.
    """

    @pytest.mark.parametrize(
        "triggered_by",
        [
            CancelTriggeredBy.MEMBER_SELF_CANCEL,
            CancelTriggeredBy.SUBSCRIPTION_DELETED,
            CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL,
        ],
    )
    def test_a_locked_active_member_is_not_deactivated(self, triggered_by):
        profile = ProfileFactory(active=True, state_locked=True)

        result = profile.complete_cancel(triggered_by)

        assert result.outcome == CompleteCancelOutcome.STATE_LOCKED
        assert result.previous_state == "active"
        profile.refresh_from_db()
        assert profile.state == "active"

    def test_the_refusal_is_recorded_against_the_member(self):
        profile = ProfileFactory(active=True, state_locked=True)

        profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        refusals = UserEventLog.objects.filter(
            user=profile.user,
            description__contains="state_locked refused cancellation",
        )
        assert refusals.count() == 1
        assert "triggered_by=subscription_deleted" in refusals.first().description

    def test_unlocking_first_is_what_lets_a_cancel_through(self):
        profile = ProfileFactory(active=True, state_locked=True)

        assert profile.set_state_locked(False) is True
        result = profile.complete_cancel(CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL)

        assert result.outcome == CompleteCancelOutcome.DEACTIVATED
        profile.refresh_from_db()
        assert profile.state == "inactive"

    def test_the_lock_only_guards_the_active_state(self):
        # A locked noob still lapses — the lock protects existing access, and
        # a noob has none.
        profile = ProfileFactory(state_locked=True)

        result = profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert result.outcome == CompleteCancelOutcome.SIGNUP_LAPSED


class TestSignupLapsed:
    def test_a_noob_signup_lapses_rather_than_deactivating(self):
        profile = ProfileFactory()

        result = profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert result.outcome == CompleteCancelOutcome.SIGNUP_LAPSED
        assert result.previous_state == "noob"
        profile.refresh_from_db()
        # Stays a noob: they never had access to lose, and they can sign up
        # again without an admin resurrecting them from "inactive".
        assert profile.state == "noob"

    def test_a_lapsed_signup_is_told_why(
        self, django_capture_on_commit_callbacks, outbox
    ):
        profile = ProfileFactory()

        with django_capture_on_commit_callbacks(execute=True):
            profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert subjects_to(outbox, profile) == ["Your membership signup has lapsed"]

    def test_the_lapsed_email_does_not_fire_without_a_commit(self, outbox):
        # Same guard as the awaiting-payment email: it rides
        # transaction.on_commit, so the test above would pass vacuously
        # without the capture.
        profile = ProfileFactory()

        profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert subjects_to(outbox, profile) == []

    def test_only_a_deleted_subscription_sends_the_lapsed_email(
        self, django_capture_on_commit_callbacks, outbox
    ):
        # A member cancelling their own pending signup already knows.
        profile = ProfileFactory()

        with django_capture_on_commit_callbacks(execute=True):
            result = profile.complete_cancel(CancelTriggeredBy.MEMBER_SELF_CANCEL)

        assert result.outcome == CompleteCancelOutcome.SIGNUP_LAPSED
        assert subjects_to(outbox, profile) == []


class TestAlreadyDeactivated:
    @pytest.mark.parametrize("state", ["inactive", "accountonly"])
    def test_nothing_happens_to_a_member_who_is_already_out(self, state):
        profile = ProfileFactory(state=state)

        result = profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert result.outcome == CompleteCancelOutcome.ALREADY_DEACTIVATED
        assert result.previous_state == state
        profile.refresh_from_db()
        assert profile.state == state


class TestDefaultAccessCleanup:
    """The paths that bypass deactivate() must drop pre-staged access rows."""

    @pytest.mark.parametrize("state", ["noob", "accountonly"])
    def test_default_access_is_dropped(self, state):
        DoorFactory(all_members=True)
        InterlockFactory(all_members=True)
        profile = ProfileFactory(state=state)
        profile.add_default_access()
        assert profile.doors.exists() and profile.interlocks.exists()

        profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert not profile.doors.exists()
        assert not profile.interlocks.exists()

    @pytest.mark.parametrize("state", ["noob", "accountonly"])
    def test_bespoke_admin_grants_survive(self, state):
        # The reason cleanup is a targeted .remove() of the all_members
        # devices rather than a .clear(): a door an admin granted this member
        # specifically is not the space's default access and must not be
        # collateral damage on cancel.
        DoorFactory(all_members=True)
        bespoke_door = DoorFactory(all_members=False)
        bespoke_interlock = InterlockFactory(all_members=False)
        profile = ProfileFactory(state=state)
        profile.add_default_access()
        profile.doors.add(bespoke_door)
        profile.interlocks.add(bespoke_interlock)

        profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)

        assert list(profile.doors.all()) == [bespoke_door]
        assert list(profile.interlocks.all()) == [bespoke_interlock]
