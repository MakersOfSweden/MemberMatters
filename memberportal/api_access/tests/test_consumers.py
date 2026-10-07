"""Access-control devices over websockets, driven through the real ASGI app.

Door, interlock and memberbucks controllers hold a websocket open to the
portal. They connect, prove themselves with an API key, and then exchange JSON
commands: the card list and swipe logs for doors, sessions for interlocks,
payments for memberbucks devices, and the commands the portal pushes to them
through the channel layer (bump, lock, unlock, reboot, sync, lockout).

These tests send that traffic through the project's ASGI routing, auth
middleware and consumers with Channels' WebsocketCommunicator, which calls the
application directly, so Daphne itself is not involved. The channel layer is
the in-memory one from settings_test; set MM_TEST_REDIS_URL (for example
redis://localhost:6379/1) to run the same tests on channels_redis instead.
"""

import os
import uuid
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import InMemoryChannelLayer, get_channel_layer
from channels.testing import WebsocketCommunicator
from django.utils import timezone

from access.models import (
    AccessControlledDeviceAPIKey,
    DoorLog,
    Doors,
    InterlockLog,
    MemberbucksDevice,
)
from memberbucks.models import MemberBucks
from membermatters.asgi import application
from profile.models import EventLog
from tests.factories import DoorFactory, InterlockFactory, ProfileFactory

# The consumers do their database work through database_sync_to_async, outside
# the test's own transaction, so the rows they read and write have to be real.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def channel_layer(settings):
    redis_url = os.environ.get("MM_TEST_REDIS_URL")
    if redis_url:
        # A fresh prefix per test keeps runs from seeing each other's groups.
        settings.CHANNEL_LAYERS = {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {
                    "hosts": [redis_url],
                    "prefix": f"mm-test-{uuid.uuid4().hex}",
                },
            }
        }
    return get_channel_layer()


@pytest.fixture
def api_key():
    return AccessControlledDeviceAPIKey.objects.create_key(name="test device")[1]


def run(scenario):
    async_to_sync(scenario)()


async def connect(device_type, serial_number):
    communicator = WebsocketCommunicator(
        application, f"/ws/access/{device_type}/{serial_number}"
    )
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def authenticate(communicator, secret_key):
    await communicator.send_json_to(
        {"command": "authenticate", "secret_key": secret_key}
    )
    return await communicator.receive_json_from()


async def open_session(device_type, device, secret_key):
    """Connects and authenticates, then reads past what is pushed on connect."""
    communicator = await connect(device_type, device.serial_number)
    assert await authenticate(communicator, secret_key) == {"authorised": True}
    while (await communicator.receive_json_from())[
        "command"
    ] != "update_device_locked_out":
        pass
    return communicator


async def send(communicator, message):
    await communicator.send_json_to(message)
    return await communicator.receive_json_from()


def test_an_unknown_door_is_commissioned_and_turned_away():
    async def scenario():
        communicator = await connect("door", "new-door-1")
        assert await communicator.receive_output() == {"type": "websocket.close"}
        await communicator.disconnect()

    run(scenario)

    door = Doors.objects.get(serial_number="new-door-1")
    assert door.authorised is False
    assert door.hidden is True


def test_an_authorised_door_with_a_valid_key_gets_the_card_list(api_key):
    door = DoorFactory()
    member = ProfileFactory(active=True, with_rfid=True)
    member.doors.add(door)
    ProfileFactory(active=True, with_rfid=True)  # no access to this door

    async def scenario():
        communicator = await connect("door", door.serial_number)
        assert await authenticate(communicator, api_key) == {"authorised": True}

        sync = await communicator.receive_json_from()
        assert sync["command"] == "sync"
        assert sync["tags"] == [member.rfid]

        assert await communicator.receive_json_from() == {
            "command": "update_device_locked_out",
            "locked_out": False,
        }

        assert await send(communicator, {"command": "ping"}) == {"command": "pong"}
        await communicator.disconnect()

    run(scenario)


def test_a_wrong_key_is_refused_and_disconnected(api_key):
    door = DoorFactory()

    async def scenario():
        communicator = await connect("door", door.serial_number)
        assert await authenticate(communicator, "not-a-key") == {"authorised": False}
        assert await communicator.receive_output() == {"type": "websocket.close"}
        await communicator.disconnect()

    run(scenario)


def test_a_command_before_authenticating_is_refused():
    door = DoorFactory()

    async def scenario():
        communicator = await connect("door", door.serial_number)
        assert await send(communicator, {"command": "sync"}) == {"authorised": False}
        assert await communicator.receive_output() == {"type": "websocket.close"}
        await communicator.disconnect()

    run(scenario)


def test_commands_from_the_portal_reach_the_door(api_key, channel_layer):
    door = DoorFactory()

    async def scenario():
        communicator = await open_session("door", door, api_key)

        # What the admin buttons call: each one is a group_send addressed to
        # the door's serial number, turned into a command by the consumer.
        for send_command, command in [
            (door.bump, "bump"),
            (door.lock, "lock"),
            (door.unlock, "unlock"),
            (door.reboot, "reboot"),
            (door.sync, "sync"),
        ]:
            await sync_to_async(send_command)()
            assert (await communicator.receive_json_from())["command"] == command

        # The admin's maintenance lockout: the consumer rereads the door.
        await sync_to_async(Doors.objects.filter(pk=door.pk).update)(locked_out=True)
        await channel_layer.group_send(
            door.serial_number, {"type": "update_device_locked_out"}
        )
        assert await communicator.receive_json_from() == {
            "command": "update_device_locked_out",
            "locked_out": True,
        }

        await communicator.disconnect()

    run(scenario)


def test_swipes_are_logged_and_acknowledged(api_key):
    door = DoorFactory()
    member = ProfileFactory(active=True, with_rfid=True)

    async def scenario():
        communicator = await open_session("door", door, api_key)

        assert await send(
            communicator, {"command": "log_access", "card_id": member.rfid}
        ) == {"command": "log_access", "success": True}

        # A refused swipe is logged, and the door is sent a fresh card list.
        assert await send(
            communicator, {"command": "log_access_denied", "card_id": member.rfid}
        ) == {"command": "log_access_denied", "success": True}
        assert (await communicator.receive_json_from())["command"] == "sync"

        # An unknown card is still acknowledged, so the door doesn't retry.
        assert await send(
            communicator, {"command": "log_access", "card_id": "999999999"}
        ) == {"command": "log_access", "success": True}

        await communicator.disconnect()

    run(scenario)

    logs = DoorLog.objects.filter(door=door).order_by("id")
    assert [(log.user_id, log.success) for log in logs] == [
        (member.user_id, True),
        (member.user_id, False),
    ]


def test_disconnecting_is_logged_and_leaves_the_door_group(api_key, channel_layer):
    door = DoorFactory()

    async def scenario():
        communicator = await open_session("door", door, api_key)
        await communicator.disconnect()

    run(scenario)

    assert EventLog.objects.filter(door=door, description="Device disconnected.")
    if isinstance(channel_layer, InMemoryChannelLayer):
        assert not channel_layer.groups.get(door.serial_number)


def test_an_interlock_session_runs_from_swipe_to_end(api_key):
    interlock = InterlockFactory()
    member = ProfileFactory(active=True, with_rfid=True)
    member.interlocks.add(interlock)

    async def scenario():
        communicator = await open_session("interlock", interlock, api_key)

        started = await send(
            communicator,
            {"command": "interlock_session_start", "card_id": member.rfid},
        )
        assert started["command"] == "interlock_session_start"

        assert await send(
            communicator,
            {
                "command": "interlock_session_end",
                "card_id": member.rfid,
                "session_id": started["session_id"],
                "session_kwh": 0.5,
            },
        ) == {"command": "interlock_session_end", "success": True}

        await communicator.disconnect()
        return started["session_id"]

    session_id = async_to_sync(scenario)()

    session = InterlockLog.objects.get(id=session_id)
    assert session.date_ended is not None
    assert session.user_ended_id == member.user_id
    assert session.total_kwh == 0.5
    # Under ten seconds, so it is free.
    assert session.total_cost == 0


def test_an_interlock_turns_away_a_member_without_access(api_key, sms_outbox):
    interlock = InterlockFactory()
    member = ProfileFactory(active=True, with_rfid=True)

    async def scenario():
        communicator = await open_session("interlock", interlock, api_key)
        assert await send(
            communicator,
            {"command": "interlock_session_start", "card_id": member.rfid},
        ) == {"command": "interlock_session_rejected", "reason": "rejected"}
        await communicator.disconnect()

    run(scenario)

    rejected = InterlockLog.objects.get(interlock=interlock)
    assert (rejected.success, rejected.reason) == (False, "rejected")
    assert rejected.date_ended is not None
    assert len(sms_outbox) == 1


def test_reauthenticating_an_interlock_ends_its_open_sessions(api_key):
    interlock = InterlockFactory()
    member = ProfileFactory(active=True)
    stale = InterlockLog.objects.create(interlock=interlock, user_started=member.user)

    async def scenario():
        communicator = await open_session("interlock", interlock, api_key)
        await communicator.disconnect()

    run(scenario)

    stale.refresh_from_db()
    assert stale.date_ended is not None


def test_a_memberbucks_device_debits_a_member(api_key, outbox):
    device = MemberbucksDevice.objects.create(
        name="Vending machine", serial_number="vending-1", authorised=True
    )
    member = ProfileFactory(
        active=True,
        with_rfid=True,
        # Outside the device's one-purchase-per-three-seconds limit.
        last_memberbucks_purchase=timezone.now() - timedelta(hours=1),
    )
    MemberBucks.objects.create(
        user=member.user, amount=10, transaction_type="cash", description="Top up"
    )

    async def scenario():
        communicator = await open_session("memberbucks", device, api_key)

        assert await send(
            communicator, {"command": "balance", "card_id": member.rfid}
        ) == {"command": "balance", "balance": 1000, "success": True}

        # Pins the units as the consumer handles them today: "amount" is
        # compared with the balance in dollars, and replies are in cents.
        assert await send(
            communicator, {"command": "debit", "card_id": member.rfid, "amount": 2}
        ) == {"command": "debit", "balance": 800, "amount": -200, "success": True}

        refused = await send(
            communicator, {"command": "debit", "card_id": member.rfid, "amount": 50}
        )
        assert (refused["success"], refused["reason"]) == (False, "insufficient_funds")

        await communicator.disconnect()

    run(scenario)

    member.refresh_from_db()
    assert member.memberbucks_balance == 8
    assert MemberBucks.objects.filter(user=member.user, amount=-2).count() == 1
    assert len(outbox) == 2  # the purchase and the refused debit
