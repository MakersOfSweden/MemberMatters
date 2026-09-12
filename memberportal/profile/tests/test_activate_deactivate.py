"""Profile.activate / Profile.deactivate — the transitions themselves.

complete_signup and complete_cancel decide *whether* a member's state should
change; these two do the changing. They are covered here directly because they
carry behaviour the callers don't exercise: the already-in-that-state guard,
the on_transition hook, and the rule that a failure in any one notification
must not skip the ones after it or the device sync.

That last rule is the reason the notifications are individually wrapped in the
source. An "active" member whose devices were never told their tag is a worse
outcome than a missed email, so sync_access() has to be reached regardless.
"""

import pytest

from profile.models import UserEventLog
from tests.factories import ProfileFactory
from tests.helpers import member_with_a_door, subjects_to

pytestmark = pytest.mark.django_db


class TestActivate:
    def test_activating_a_noob_flips_the_state(self):
        profile = ProfileFactory()

        assert profile.activate() is True

        profile.refresh_from_db()
        assert profile.state == "active"

    def test_an_already_active_member_is_a_no_op(self, outbox, device_commands):
        profile, _ = member_with_a_door(active=True)

        assert profile.activate() is False

        assert subjects_to(outbox, profile) == []
        assert device_commands == []

    def test_a_noob_gets_the_application_and_welcome_emails(self, outbox, sms_outbox):
        profile = ProfileFactory()

        profile.activate()

        subjects = subjects_to(outbox, profile)
        assert any(s.startswith("Welcome to") for s in subjects)
        assert len(subjects) == 2
        # The noob branch is email-only; SMS belongs to the re-enable branch.
        assert sms_outbox == []

    def test_reactivating_takes_the_sms_and_access_enabled_branch(
        self, outbox, sms_outbox
    ):
        profile = ProfileFactory(inactive=True)

        profile.activate()

        subjects = subjects_to(outbox, profile)
        assert not any(s.startswith("Welcome to") for s in subjects)
        assert any("enabled" in s for s in subjects)
        assert [body for number, body in sms_outbox if number == profile.phone]

    def test_the_members_devices_are_synced(self, device_commands):
        profile, door = member_with_a_door()

        profile.activate()

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_the_on_transition_hook_receives_the_state_pair(self):
        profile = ProfileFactory(inactive=True)
        seen = []

        profile.activate(
            on_transition=lambda before, after: seen.append((before, after))
        )

        assert seen == [("inactive", "active")]

    def test_a_failing_hook_does_not_block_the_rest(self, outbox, device_commands):
        # The hook is caller-supplied, so it is the most likely thing to
        # raise. It is wrapped in capture_exception for exactly this reason.
        profile, door = member_with_a_door()

        def boom(before, after):
            raise RuntimeError("hook exploded")

        assert profile.activate(on_transition=boom) is True

        assert subjects_to(outbox, profile)
        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_an_admin_activation_is_recorded_against_both_parties(self, admin_request):
        profile = ProfileFactory()

        profile.activate(request=admin_request)

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="activated member"
        ).exists()
        assert UserEventLog.objects.filter(
            user=admin_request.user, description__contains=profile.get_full_name()
        ).exists()

    def test_a_failing_email_does_not_skip_the_device_sync(
        self, monkeypatch, device_commands
    ):
        # The contract the individual try/except blocks exist for: Postmark
        # being down must not leave an "active" member whose devices were
        # never told their tag.
        from profile.models import User

        profile, door = member_with_a_door()
        monkeypatch.setattr(
            User, "email_welcome", lambda self: (_ for _ in ()).throw(RuntimeError())
        )

        assert profile.activate() is True

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_a_systemic_activation_is_recorded_as_system(self):
        profile = ProfileFactory()

        profile.activate()

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="system activated member"
        ).exists()


class TestDeactivate:
    def test_deactivating_an_active_member_flips_the_state(self):
        profile = ProfileFactory(active=True)

        assert profile.deactivate() is True

        profile.refresh_from_db()
        assert profile.state == "inactive"

    def test_an_already_inactive_member_is_a_no_op(self, outbox, device_commands):
        profile, _ = member_with_a_door(inactive=True)

        assert profile.deactivate() is False

        assert subjects_to(outbox, profile) == []
        assert device_commands == []

    @pytest.mark.parametrize("state", ["noob", "accountonly"])
    def test_it_also_pulls_other_states_to_inactive(self, state):
        # The guard is only against "inactive" — deactivate() itself does not
        # care where the member started. complete_cancel is what routes noob
        # and accountonly away from here.
        profile = ProfileFactory(state=state)

        assert profile.deactivate() is True

        profile.refresh_from_db()
        assert profile.state == "inactive"

    def test_the_default_reason_sends_the_generic_access_disabled_email(self, outbox):
        profile = ProfileFactory(active=True)

        profile.deactivate()

        bodies = [m["HtmlBody"] for m in outbox if m["To"] == profile.user.email]
        assert bodies
        assert not any("subscription has ended" in body for body in bodies)

    def test_the_subscription_ended_reason_sends_the_specific_one(self, outbox):
        profile = ProfileFactory(active=True)

        profile.deactivate(reason="subscription_ended")

        assert any(
            "subscription has ended" in m["HtmlBody"]
            for m in outbox
            if m["To"] == profile.user.email
        )

    def test_the_member_is_texted(self, sms_outbox):
        profile = ProfileFactory(active=True)

        profile.deactivate()

        assert [body for number, body in sms_outbox if number == profile.phone]

    def test_the_members_devices_are_synced(self, device_commands):
        profile, door = member_with_a_door(active=True)

        profile.deactivate()

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_the_on_transition_hook_receives_the_state_pair(self):
        profile = ProfileFactory(active=True)
        seen = []

        profile.deactivate(
            on_transition=lambda before, after: seen.append((before, after))
        )

        assert seen == [("active", "inactive")]

    def test_a_failing_hook_does_not_block_the_rest(self, outbox, device_commands):
        profile, door = member_with_a_door(active=True)

        def boom(before, after):
            raise RuntimeError("hook exploded")

        assert profile.deactivate(on_transition=boom) is True

        assert subjects_to(outbox, profile)
        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_a_failing_email_does_not_skip_the_sms_or_the_sync(
        self, monkeypatch, sms_outbox, device_commands
    ):
        # Both later steps are downstream of the email in source order, so a
        # single shared try block would swallow them with it.
        from profile.models import User

        profile, door = member_with_a_door(active=True)
        monkeypatch.setattr(
            User,
            "email_disable_member_access",
            lambda self: (_ for _ in ()).throw(RuntimeError()),
        )

        assert profile.deactivate() is True

        assert [body for number, body in sms_outbox if number == profile.phone]
        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_a_failing_sms_does_not_skip_the_sync(self, monkeypatch, device_commands):
        from services import sms as sms_module

        profile, door = member_with_a_door(active=True)
        monkeypatch.setattr(
            sms_module.SMS,
            "send_deactivated_access",
            lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError()),
        )

        assert profile.deactivate() is True

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_an_admin_deactivation_is_recorded_against_both_parties(
        self, admin_request
    ):
        profile = ProfileFactory(active=True)

        profile.deactivate(request=admin_request)

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="deactivated member"
        ).exists()
        assert UserEventLog.objects.filter(
            user=admin_request.user, description__contains=profile.get_full_name()
        ).exists()

    def test_a_systemic_deactivation_is_recorded_as_system(self):
        profile = ProfileFactory(active=True)

        profile.deactivate()

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="system deactivated member"
        ).exists()
