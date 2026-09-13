"""The CAPTCHA verify helper, services/captcha.py.

Every gated endpoint delegates to verify_captcha, so its rules are pinned here:
while CAPTCHA is off nothing calls out, and while it is on anything short of a
passing verdict for this form fails closed.
"""

import pytest
import requests
from constance.test import override_config
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from services import captcha
from services.captcha import captcha_enabled, verify_captcha

# Constance reads go through the database backend.
pytestmark = pytest.mark.django_db

KEYS = {"CAPTCHA_SITE_KEY": "site-key", "CAPTCHA_SECRET_KEY": "secret-key"}
enabled = pytest.mark.override_config(ENABLE_CAPTCHA=True, **KEYS)


@pytest.fixture(autouse=True)
def _reset_missing_keys_warning(monkeypatch):
    monkeypatch.setattr(captcha, "_warned_missing_keys", None)


def make_request(data=None, **meta):
    django_request = APIRequestFactory().post(
        "/", {} if data is None else data, format="json", **meta
    )
    return Request(django_request, parsers=[JSONParser()])


def solved(**verdict):
    return {
        "success": True,
        "action": "login",
        "hostname": "portal.example.org",
        **verdict,
    }


def test_off_by_default_and_never_calls_out(siteverify):
    assert captcha_enabled() is False
    assert verify_captcha(make_request(), action="login") is True
    assert siteverify.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {**KEYS, "ENABLE_CAPTCHA": False},
        {**KEYS, "ENABLE_CAPTCHA": True, "CAPTCHA_SITE_KEY": ""},
        {**KEYS, "ENABLE_CAPTCHA": True, "CAPTCHA_SECRET_KEY": ""},
    ],
    ids=["flag-off", "no-site-key", "no-secret-key"],
)
def test_needs_the_flag_and_both_keys(siteverify, overrides):
    with override_config(**overrides):
        assert captcha_enabled() is False
        assert verify_captcha(make_request(), action="login") is True
    assert siteverify.calls == []


def test_warns_once_per_misconfiguration(caplog):
    with override_config(ENABLE_CAPTCHA=True, **{**KEYS, "CAPTCHA_SITE_KEY": ""}):
        captcha_enabled()
        captcha_enabled()
    with override_config(ENABLE_CAPTCHA=True, **{**KEYS, "CAPTCHA_SECRET_KEY": ""}):
        captcha_enabled()

    warnings = [r.getMessage() for r in caplog.records if r.name == "captcha"]
    assert len(warnings) == 2
    assert "CAPTCHA_SITE_KEY" in warnings[0]
    assert "CAPTCHA_SECRET_KEY" in warnings[1]


@enabled
@pytest.mark.parametrize(
    "body",
    [{}, {"captchaToken": ""}, {"captchaToken": ["token"]}, ["token"]],
    ids=["absent", "empty", "not-a-string", "array-body"],
)
def test_fails_without_a_usable_token_and_never_calls_out(siteverify, body):
    assert verify_captcha(make_request(body), action="login") is False
    assert siteverify.calls == []


@enabled
def test_passes_a_verdict_for_this_form(siteverify):
    siteverify.result = solved()

    request = make_request({"captchaToken": "token"})
    assert verify_captcha(request, action="login") is True

    [call] = siteverify.calls
    assert call["url"] == captcha.SITEVERIFY_URL
    assert call["data"] == {"secret": "secret-key", "response": "token"}
    # requests has no default timeout; without one a stalled provider hangs.
    assert call["timeout"] == captcha.VERIFY_TIMEOUT


@enabled
def test_fails_a_rejected_verdict(siteverify):
    siteverify.result = {"success": False, "error-codes": ["invalid-input-response"]}

    request = make_request({"captchaToken": "token"})
    assert verify_captcha(request, action="login") is False


@enabled
@pytest.mark.parametrize(
    "attribute, failure",
    [
        ("raises", requests.ConnectTimeout()),
        ("raises", requests.ConnectionError()),
        ("result", ValueError("an HTML error page, not JSON")),
        ("result", ["valid JSON", "but not an object"]),
        ("result", None),
    ],
    ids=["timeout", "unreachable", "not-json", "json-array", "json-null"],
)
def test_fails_closed_and_logs_when_the_provider_misbehaves(
    siteverify, caplog, attribute, failure
):
    setattr(siteverify, attribute, failure)

    request = make_request({"captchaToken": "token"})
    assert verify_captcha(request, action="login") is False
    assert [r.levelname for r in caplog.records if r.name == "captcha"] == ["ERROR"]


@enabled
def test_rejects_and_logs_a_token_solved_on_another_form(siteverify, caplog):
    siteverify.result = solved(action="register")

    request = make_request({"captchaToken": "token"})
    assert verify_captcha(request, action="login") is False

    [record] = [r for r in caplog.records if r.name == "captcha"]
    assert "'register'" in record.getMessage()


@enabled
@pytest.mark.parametrize(
    "allowed, hostname, passes",
    [
        ("", "clone.example.net", True),
        ("portal.example.org, www.example.org", "www.example.org", True),
        ("Portal.Example.org", "portal.example.org", True),
        ("portal.example.org", "clone.example.net", False),
    ],
    ids=["unset-skips-the-check", "listed", "listed-in-another-case", "unlisted"],
)
def test_hostname_allow_list(siteverify, allowed, hostname, passes):
    siteverify.result = solved(hostname=hostname)

    with override_config(CAPTCHA_ALLOWED_HOSTNAMES=allowed):
        request = make_request({"captchaToken": "token"})
        assert verify_captcha(request, action="login") is passes


@enabled
def test_logs_a_token_solved_on_an_unlisted_hostname(siteverify, caplog):
    siteverify.result = solved(hostname="clone.example.net")

    with override_config(CAPTCHA_ALLOWED_HOSTNAMES="portal.example.org"):
        request = make_request({"captchaToken": "token"})
        assert verify_captcha(request, action="login") is False

    [record] = [r for r in caplog.records if r.name == "captcha"]
    assert "'clone.example.net'" in record.getMessage()


@enabled
@pytest.mark.parametrize(
    "num_proxies, forwarded_for, remoteip",
    [
        # Public addresses throughout: the documentation ranges (203.0.113.0/24
        # and friends) aren't is_global, so they'd be dropped as a private hop.
        (None, "8.8.8.8", None),
        (1, "8.8.8.8", "8.8.8.8"),
        (1, "1.1.1.1, 8.8.8.8", "8.8.8.8"),
        (1, "10.0.0.5", None),
        (1, "not-an-address", None),
    ],
    ids=[
        "hop-count-unset",
        "client",
        "spoofed-entry-ignored",
        "private-hop",
        "garbage",
    ],
)
def test_sends_remoteip_only_for_a_trusted_public_address(
    siteverify, settings, num_proxies, forwarded_for, remoteip
):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": num_proxies}
    siteverify.result = solved()

    request = make_request(
        {"captchaToken": "token"}, HTTP_X_FORWARDED_FOR=forwarded_for
    )
    verify_captcha(request, action="login")

    assert siteverify.calls[0]["data"].get("remoteip") == remoteip
