"""Profile.set_admin_disabled_access — the access pause.

A third state axis, orthogonal to both `state` and `subscription_status`: an
operator can revoke a member's door access during a dispute without cancelling
their billing or touching their membership state.

The pause is enforced in access.Doors.get_tags(), which filters on
`admin_disabled_access=False` alongside `state="active"`. That query is the
real contract, so it is asserted directly here rather than inferred from the
flag — a pause that sets the column but never reaches a device is not a pause.

get_tags() returns a (tags, md5-of-tags) tuple, so the helper below unwraps it.
Comparing against the tuple makes a `not in` assertion pass for the wrong
reason, since the raw tag string is never an element of it.
"""

import pytest

from profile.models import UserEventLog
from tests.factories import ProfileFactory
from tests.helpers import member_with_a_door, subjects_to

pytestmark = pytest.mark.django_db


def tags_on(door):
    """The tag list from get_tags()'s (tags, hash) return."""
    return door.get_tags()[0]


class TestTheFlag:
    def test_pausing_persists(self):
        profile = ProfileFactory()

        profile.set_admin_disabled_access(True)

        profile.refresh_from_db()
        assert profile.admin_disabled_access is True

    def test_resuming_persists(self):
        profile = ProfileFactory(admin_disabled_access=True)

        profile.set_admin_disabled_access(False)

        profile.refresh_from_db()
        assert profile.admin_disabled_access is False

    def test_the_in_memory_instance_is_left_stale(self):
        # Current behaviour, pinned deliberately rather than asserted as
        # correct: the write lands on the re-read copy taken under
        # select_for_update and `self` is never updated to match.
        # set_state_locked does do this (`self.state_locked = locked`), so the
        # two admin setters disagree. Harmless today — MemberAdminDisabledAccess
        # returns a bare {"success": True} and reads nothing back — but a
        # caller that trusted `self` here would be reading the old value.
        profile = ProfileFactory()

        profile.set_admin_disabled_access(True)

        assert profile.admin_disabled_access is False  # no refresh_from_db
        profile.refresh_from_db()
        assert profile.admin_disabled_access is True


class TestEffectiveAccess:
    def test_a_paused_member_is_dropped_from_the_door_tag_list(self):
        profile, door = member_with_a_door(active=True)
        assert profile.rfid in tags_on(door)

        profile.set_admin_disabled_access(True)

        assert profile.rfid not in tags_on(door)

    def test_resuming_puts_them_back(self):
        profile, door = member_with_a_door(active=True, admin_disabled_access=True)
        assert profile.rfid not in tags_on(door)

        profile.set_admin_disabled_access(False)

        assert profile.rfid in tags_on(door)

    def test_the_members_access_rows_are_left_alone(self):
        # The pause is a filter, not a revocation — resuming has to be a pure
        # flag flip, so the M2M rows must survive.
        profile, door = member_with_a_door(active=True)

        profile.set_admin_disabled_access(True)

        assert list(profile.doors.all()) == [door]


class TestDeviceSync:
    def test_pausing_syncs_the_members_devices(self, device_commands):
        profile, door = member_with_a_door(active=True)

        profile.set_admin_disabled_access(True)

        assert (door.serial_number, {"type": "sync_users"}) in device_commands

    def test_an_unchanged_flag_does_not_touch_the_devices(self, device_commands):
        profile, door = member_with_a_door(active=True)

        profile.set_admin_disabled_access(False)  # already False

        assert device_commands == []

    def test_a_non_active_member_is_still_synced(self, device_commands):
        # The flag is inert for a noob (get_tags already excludes them on
        # state), but the sync is unconditional — cheap, and it keeps the
        # device list correct if their state changes underneath.
        profile, door = member_with_a_door()

        profile.set_admin_disabled_access(True)

        assert (door.serial_number, {"type": "sync_users"}) in device_commands


class TestNotifications:
    def test_pausing_an_active_member_tells_them(self, outbox, sms_outbox):
        profile = ProfileFactory(active=True)

        profile.set_admin_disabled_access(True)

        assert any("disabled" in s for s in subjects_to(outbox, profile))
        assert [body for number, body in sms_outbox if number == profile.phone]

    def test_resuming_an_active_member_tells_them(self, outbox, sms_outbox):
        profile = ProfileFactory(active=True, admin_disabled_access=True)

        profile.set_admin_disabled_access(False)

        assert any("enabled" in s for s in subjects_to(outbox, profile))
        assert [body for number, body in sms_outbox if number == profile.phone]

    @pytest.mark.parametrize("state", ["noob", "inactive", "accountonly"])
    def test_a_non_active_member_is_not_notified(self, state, outbox, sms_outbox):
        # Their effective access never changed — it was already nil — so
        # telling them it was turned off would be misleading.
        profile = ProfileFactory(state=state)

        profile.set_admin_disabled_access(True)

        assert subjects_to(outbox, profile) == []
        assert sms_outbox == []

    def test_an_unchanged_flag_notifies_nobody(self, outbox, sms_outbox):
        profile = ProfileFactory(active=True)

        profile.set_admin_disabled_access(False)  # already False

        assert subjects_to(outbox, profile) == []
        assert sms_outbox == []


class TestNotificationIsolation:
    """Each notification is wrapped separately, so one failure isn't fatal."""

    def test_a_failing_email_does_not_skip_the_sms_or_the_sync(
        self, monkeypatch, sms_outbox, device_commands
    ):
        from profile.models import User

        profile, door = member_with_a_door(active=True)
        monkeypatch.setattr(
            User,
            "email_disable_member_access",
            lambda self: (_ for _ in ()).throw(RuntimeError()),
        )

        profile.set_admin_disabled_access(True)

        assert [body for number, body in sms_outbox if number == profile.phone]
        # sync_access runs before the notifications here, but assert it anyway:
        # the ordering is not what the caller depends on, the outcome is.
        assert (door.serial_number, {"type": "sync_users"}) in device_commands
        profile.refresh_from_db()
        assert profile.admin_disabled_access is True

    def test_a_failing_sms_does_not_undo_the_pause(self, monkeypatch):
        from services import sms as sms_module

        profile = ProfileFactory(active=True)
        monkeypatch.setattr(
            sms_module.SMS,
            "send_deactivated_access",
            lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError()),
        )

        profile.set_admin_disabled_access(True)

        profile.refresh_from_db()
        assert profile.admin_disabled_access is True


class TestAuditTrail:
    def test_an_admin_pause_is_recorded_against_both_parties(self, admin_request):
        profile = ProfileFactory(active=True)

        profile.set_admin_disabled_access(True, request=admin_request)

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="Access paused by admin"
        ).exists()
        assert UserEventLog.objects.filter(
            user=admin_request.user, description__contains="paused access for"
        ).exists()

    def test_resuming_says_resumed(self, admin_request):
        profile = ProfileFactory(active=True, admin_disabled_access=True)

        profile.set_admin_disabled_access(False, request=admin_request)

        assert UserEventLog.objects.filter(
            user=profile.user, description__contains="Access resumed by admin"
        ).exists()

    def test_an_unchanged_flag_is_not_audited(self, admin_request):
        profile = ProfileFactory(active=True)

        profile.set_admin_disabled_access(False, request=admin_request)

        assert not UserEventLog.objects.exists()
