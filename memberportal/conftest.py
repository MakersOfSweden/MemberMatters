"""Shared fixtures for the backend suite.

Every external dependency gets exactly one stub location here, so a test never
has to invent its own way of neutralising Stripe, Postmark or the network.
"""

import socket

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from tests.factories import (  # noqa: F401  (re-exported for convenience)
    DoorFactory,
    InterlockFactory,
    ProfileFactory,
    UserFactory,
)

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class NetworkAccessInTestError(RuntimeError):
    """Raised when a test tries to reach a non-loopback address."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly on any outbound connection.

    The codebase talks to Stripe, Postmark, Twilio, Mailchimp, Moodle, Canvas,
    Discord and Slack. Without this, forgetting to stub one of them produces a
    slow, intermittent CI failure that reads as flakiness. With it, the failure
    is immediate and names the host — and the suite runs offline.

    Both connect() and getaddrinfo() are guarded: on a machine with no network
    the DNS lookup fails first, and its error message says nothing useful about
    which test reached for which service.

    Loopback stays open for the Postgres matrix leg. (psycopg2 connects below
    the Python socket layer and is unaffected either way.)
    """
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def _check(host):
        if host not in _LOOPBACK:
            raise NetworkAccessInTestError(
                f"Test attempted a network connection to {host!r}. Stub the "
                f"service at its module boundary instead — see conftest.py."
            )

    def guarded_connect(self, address, *args, **kwargs):
        _check(address[0] if isinstance(address, tuple) else address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        _check(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Drop cache state between tests.

    DRF throttling accumulates its per-IP history in the Django cache, and
    every test request arrives from the same address, so tests using the
    `enable_throttling` fixture would otherwise leak counts into each other.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Capture outbound email instead of sending it.

    Autouse because email is a side channel almost everywhere it appears —
    activate(), deactivate(), register, password reset — and a test about
    membership state shouldn't have to know that.

    Note that this is NOT redundant with the network guard: POSTMARK_API_KEY
    defaults to the placeholder "PLEASE_CHANGE_ME", which is truthy, so
    send_single_email() takes the Postmark branch on a default install rather
    than the "not configured" branch.

    Returns the list of send() kwargs, in send order — Subject, To, HtmlBody,
    From, ReplyTo.
    """
    sent = []

    class _RecordingEmails:
        def send(self, **kwargs):
            sent.append(kwargs)
            return {"ErrorCode": 0, "Message": "OK"}

    class _RecordingPostmarkClient:
        def __init__(self, *args, **kwargs):
            self.emails = _RecordingEmails()

    monkeypatch.setattr("services.emails.PostmarkClient", _RecordingPostmarkClient)
    return sent


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def member(db):
    """A plain member in the default 'noob' state."""
    return ProfileFactory()


@pytest.fixture
def admin_member(db):
    """A member whose User is flagged staff — what the admin APIs check."""
    return ProfileFactory(user__staff_user=True)


@pytest.fixture
def authed_client(member):
    client = APIClient()
    client.force_authenticate(user=member.user)
    return client


@pytest.fixture
def admin_client(admin_member):
    client = APIClient()
    client.force_authenticate(user=admin_member.user)
    return client


@pytest.fixture
def enable_throttling(settings):
    """Restore the real DRF throttle rates for tests that assert on them."""
    from membermatters.settings import REST_FRAMEWORK as REAL_REST_FRAMEWORK

    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": REAL_REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
        "DEFAULT_THROTTLE_RATES": REAL_REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
    }
    return settings.REST_FRAMEWORK


@pytest.fixture
def enable_pwned_validator(settings):
    """Restore PwnedPasswordsValidator for tests that cover it.

    Such tests must stub the HTTP call themselves — `_no_network` still
    applies, which is the point: the validator runs, the API is not contacted.
    """
    from membermatters.settings import (
        AUTH_PASSWORD_VALIDATORS as REAL_AUTH_PASSWORD_VALIDATORS,
    )

    settings.AUTH_PASSWORD_VALIDATORS = REAL_AUTH_PASSWORD_VALIDATORS
    return settings.AUTH_PASSWORD_VALIDATORS


@pytest.fixture
def device_commands(monkeypatch):
    """Record commands sent to access-control devices.

    Doors and Interlocks are driven over Channels, not HTTP: sync(), lock(),
    unlock(), reboot() and bump() all group_send() to the device's serial
    number. Recording at the channel layer means tests assert the real side
    effect of e.g. Profile.activate() rather than mocking out sync_access().

    Draining the in-memory layer by receiving from it isn't viable here —
    group_send only reaches channels that have joined the group, and each
    async_to_sync() call runs on a fresh event loop, which asyncio.Queue
    refuses to be shared across.

    Returns a list of (group, message) tuples, in send order.
    """
    from channels.layers import InMemoryChannelLayer

    sent = []
    real_group_send = InMemoryChannelLayer.group_send

    async def recording_group_send(self, group, message):
        sent.append((group, message))
        return await real_group_send(self, group, message)

    monkeypatch.setattr(InMemoryChannelLayer, "group_send", recording_group_send)
    return sent
