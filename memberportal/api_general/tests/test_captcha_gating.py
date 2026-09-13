"""CAPTCHA gating on the public endpoints: signup, web and mobile login, and
requesting a password reset.

The verify helper's own rules are in test_captcha_verify.py. These pin where
each endpoint calls it — before any account, session, token or reset exists —
that it passes the endpoint's own form action, and that a solved challenge
still lets the normal flow through.
"""

import base64
import hashlib
import hmac
from urllib.parse import urlencode

import pytest
from constance.test import override_config
from rest_framework.throttling import SimpleRateThrottle

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.override_config(
        ENABLE_CAPTCHA=True,
        CAPTCHA_SITE_KEY="site-key",
        CAPTCHA_SECRET_KEY="secret-key",
    ),
]

# UserFactory's default.
PASSWORD = "test-password"

# (path, the action its frontend widget mints tokens for)
GATED = [
    ("/api/register/", "register"),
    ("/api/login/", "login"),
    ("/api/token/obtain/", "login"),
    ("/api/password/reset/", "password_reset"),
]

DISCOURSE_SECRET = "discourse-secret"


@pytest.fixture(autouse=True)
def _throttle_rates(enable_throttling):
    # Every endpoint here has a throttle scope, and a scoped view can't run
    # without its rate.
    pass


def credentials(member, **extra):
    return {"email": member.user.email, "password": PASSWORD, **extra}


def solved(action):
    return {"success": True, "action": action, "hostname": "portal.example.org"}


def discourse_sso():
    # Not a marker: a test-level override_config marker replaces the module's
    # instead of adding to it, which would silently switch CAPTCHA off here.
    return override_config(
        ENABLE_DISCOURSE_SSO_PROTOCOL=True,
        DISCOURSE_SSO_PROTOCOL_SECRET_KEY=DISCOURSE_SECRET,
    )


def signed_sso():
    sso = base64.b64encode(
        urlencode(
            {
                "nonce": "nonce",
                "return_sso_url": "https://forum.example.org/session/sso_login",
            }
        ).encode()
    ).decode()
    sig = hmac.new(DISCOURSE_SECRET.encode(), sso.encode(), hashlib.sha256)
    return {"sso": sso, "sig": sig.hexdigest()}


def test_config_advertises_captcha_and_its_site_key(api_client):
    response = api_client.get("/api/config/")

    assert response.data["features"]["enableCaptcha"] is True
    assert response.data["keys"]["captchaSiteKey"] == "site-key"


def test_config_does_not_advertise_captcha_while_it_is_off(api_client):
    with override_config(ENABLE_CAPTCHA=False):
        response = api_client.get("/api/config/")

    assert response.data["features"]["enableCaptcha"] is False


@pytest.mark.parametrize("path", [path for path, _ in GATED])
def test_refuses_a_request_without_a_token(api_client, member, siteverify, path):
    response = api_client.post(path, credentials(member), format="json")

    assert response.status_code == 400
    assert response.data == {"message": "error.captchaFailed"}
    assert siteverify.calls == []


@pytest.mark.parametrize("path", [path for path, _ in GATED])
def test_refuses_a_rejected_token(api_client, member, siteverify, path):
    siteverify.result = {"success": False, "error-codes": ["invalid-input-response"]}

    body = credentials(member, captchaToken="token")
    response = api_client.post(path, body, format="json")

    assert response.status_code == 400
    assert response.data == {"message": "error.captchaFailed"}
    assert len(siteverify.calls) == 1


@pytest.mark.parametrize("path, action", GATED)
def test_refuses_a_token_solved_on_another_form(
    api_client, member, siteverify, path, action
):
    siteverify.result = solved("register" if action != "register" else "login")

    body = credentials(member, captchaToken="token")
    response = api_client.post(path, body, format="json")

    assert response.data == {"message": "error.captchaFailed"}


def test_solved_web_login_signs_in(api_client, member, siteverify):
    siteverify.result = solved("login")

    body = credentials(member, captchaToken="token")
    response = api_client.post("/api/login/", body, format="json")

    assert response.status_code == 200
    assert api_client.session["_auth_user_id"] == str(member.user.pk)


def test_rejected_web_login_signs_nobody_in(api_client, member, siteverify):
    siteverify.result = {"success": False}

    body = credentials(member, captchaToken="token")
    api_client.post("/api/login/", body, format="json")

    assert "_auth_user_id" not in api_client.session


def test_solved_mobile_login_issues_tokens(api_client, member, siteverify):
    siteverify.result = solved("login")

    body = credentials(member, captchaToken="token")
    response = api_client.post("/api/token/obtain/", body, format="json")

    assert response.status_code == 200
    assert {"access", "refresh"} <= response.data.keys()


def test_solved_signup_reaches_validation(api_client, siteverify):
    siteverify.result = solved("register")

    response = api_client.post(
        "/api/register/", {"captchaToken": "token"}, format="json"
    )

    assert response.status_code == 400
    assert "email" in response.data


def test_solved_reset_request_starts_a_reset(api_client, member, siteverify):
    siteverify.result = solved("password_reset")

    response = api_client.post(
        "/api/password/reset/",
        {"email": member.user.email, "captchaToken": "token"},
        format="json",
    )

    assert response.data == {"success": True}
    member.user.refresh_from_db()
    assert member.user.password_reset_key is not None


def test_rejected_reset_request_starts_no_reset(api_client, member, siteverify):
    siteverify.result = {"success": False}

    api_client.post(
        "/api/password/reset/",
        {"email": member.user.email, "captchaToken": "token"},
        format="json",
    )

    member.user.refresh_from_db()
    assert member.user.password_reset_key is None


def test_solved_reset_request_for_an_unknown_email_still_succeeds(
    api_client, siteverify
):
    siteverify.result = solved("password_reset")

    response = api_client.post(
        "/api/password/reset/",
        {"email": "nobody@example.com", "captchaToken": "token"},
        format="json",
    )

    assert response.data == {"success": True}


@pytest.mark.parametrize(
    "body",
    [{"token": "a-reset-token"}, {"token": "a-reset-token", "password": "x" * 12}],
    ids=["validate", "submit"],
)
def test_using_an_emailed_reset_token_is_not_challenged(api_client, siteverify, body):
    response = api_client.post("/api/password/reset/", body, format="json")

    assert response.data == {"success": False}
    assert siteverify.calls == []


def test_sso_login_still_needs_a_token(api_client, member, siteverify):
    with discourse_sso():
        body = credentials(member, sso=signed_sso())
        response = api_client.post("/api/login/", body, format="json")

    assert response.data == {"message": "error.captchaFailed"}


def test_sso_handshake_for_a_signed_in_member_is_not_challenged(
    authed_client, siteverify
):
    with discourse_sso():
        body = {"sso": signed_sso()}
        response = authed_client.post("/api/login/", body, format="json")

    assert response.status_code == 200
    assert "redirect" in response.data
    assert siteverify.calls == []


@pytest.mark.parametrize(
    "path, scope", [("/api/login/", "login"), ("/api/token/obtain/", "token_obtain")]
)
def test_throttled_login_is_refused_before_calling_out(
    api_client, member, siteverify, monkeypatch, path, scope
):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1/hour")
    siteverify.result = solved("login")
    body = credentials(member, password="wrong-password", captchaToken="token")

    api_client.post(path, body, format="json")
    response = api_client.post(path, body, format="json")

    assert response.status_code == 429
    assert len(siteverify.calls) == 1
