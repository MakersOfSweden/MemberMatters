"""The Stripe checks on the admin Payment Overview page.

The connection test runs against a fake HTTP transport, so the real stripe
client still builds the requests, parses the responses and turns 401/403
answers into its own error types.
"""

import json
from urllib.parse import urlsplit

import pytest
import stripe
from constance.test import override_config
from django.apps import apps
from django.conf import settings
from django.urls import reverse

from api_billing import stripe_checks
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

SITE_URL = "https://portal.example.org"
WEBHOOK_URL = f"{SITE_URL}/api/billing/stripe-webhook/"
VERSION = settings.STRIPE_API_VERSION
HANDLED = [
    "customer.subscription.deleted",
    "customer.subscription.updated",
    "invoice.paid",
    "invoice.payment_failed",
]


class FakeStripe(stripe.HTTPClient):
    """Answers each Stripe path with a canned response; lists default to empty."""

    name = "fake"

    def __init__(self):
        super().__init__()
        self.responses = {}
        self.calls = []
        self.answer_version = VERSION

    def request(self, method, url, headers, post_data=None, *, _usage=None):
        path = urlsplit(url).path
        self.calls.append((method, path, headers.get("Stripe-Version")))
        response = self.responses.get(path)
        if isinstance(response, Exception):
            raise response
        status, body = response or (200, listing())
        return json.dumps(body), status, {"Stripe-Version": self.answer_version}

    def close(self):
        pass


def listing(*items):
    return {"object": "list", "data": list(items), "has_more": False, "url": "/"}


def endpoint(**overrides):
    return {
        "id": "we_1",
        "object": "webhook_endpoint",
        "url": WEBHOOK_URL,
        "status": "enabled",
        "enabled_events": HANDLED,
        "api_version": VERSION,
        "livemode": True,
        **overrides,
    }


def denied():
    return (
        403,
        {
            "error": {
                "type": "invalid_request_error",
                "message": "The provided key does not have the required "
                "permissions for this endpoint.",
            }
        },
    )


@pytest.fixture(autouse=True)
def stripe_config():
    with override_config(
        ENABLE_STRIPE=True,
        ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True,
        STRIPE_SECRET_KEY="rk_live_key",
        STRIPE_PUBLISHABLE_KEY="pk_live_key",
        STRIPE_WEBHOOK_SECRET="whsec_test",
        SITE_URL=SITE_URL,
    ):
        yield


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(stripe_checks, "_http_client", lambda: fake)
    return fake


def rows(result):
    return {row["key"]: row for row in result["checks"]}


def static():
    return rows(stripe_checks.get_static_checks())


def connection_test():
    return rows(stripe_checks.run_connection_test())


def test_startup_applies_the_pinned_api_version(settings, monkeypatch):
    # The pinned version matches the stripe library's own default today, so
    # pin a different one to see the setting, not the default, take effect.
    monkeypatch.setattr(stripe, "api_version", None)
    settings.STRIPE_API_VERSION = "2023-10-16"

    apps.get_app_config("api_billing").ready()

    assert stripe.api_version == "2023-10-16"


class TestStaticChecks:
    def test_a_complete_setup_passes(self):
        result = stripe_checks.get_static_checks()

        assert result["canTest"] is True
        checks = rows(result)
        assert {key: row["status"] for key, row in checks.items()} == {
            "keys": "ok",
            "webhook_secret": "ok",
            "webhook_url": "ok",
            "api_version": "info",
        }
        assert checks["keys"]["value"] == "Restricted key, live mode"
        assert checks["webhook_url"]["value"] == WEBHOOK_URL
        assert checks["api_version"]["value"] == f"Enforced {VERSION}"
        # Rows that pass carry no explanation or bullets.
        assert all(not row["detail"] and not row["items"] for row in checks.values())

    def test_no_row_shows_a_key(self):
        with override_config(STRIPE_SECRET_KEY="sk_live_secret123"):
            payload = json.dumps(stripe_checks.get_static_checks())

        assert "secret123" not in payload
        assert "pk_live_key" not in payload
        assert "whsec_test" not in payload

    def test_a_standard_secret_key_is_a_warning(self):
        with override_config(STRIPE_SECRET_KEY="sk_live_key"):
            row = static()["keys"]

        assert row["status"] == "warning"
        assert row["value"] == "Standard key, live mode"
        [problem] = row["items"]
        assert problem.startswith("Secret key is a standard key")

    @pytest.mark.parametrize(
        "key, can_test", [("", False), ("pk_live_key", False), ("nonsense", False)]
    )
    def test_a_missing_or_wrong_secret_key_is_an_error(self, key, can_test):
        with override_config(STRIPE_SECRET_KEY=key):
            result = stripe_checks.get_static_checks()

        row = rows(result)["keys"]
        assert row["status"] == "error"
        assert row["value"] == "Not usable"
        assert row["items"][0].startswith("Secret key")
        assert result["canTest"] is can_test

    def test_a_publishable_key_in_the_other_mode_is_an_error(self):
        with override_config(STRIPE_PUBLISHABLE_KEY="pk_test_key"):
            row = static()["keys"]

        assert row["status"] == "error"
        [problem] = row["items"]
        assert "test mode, but the secret key is in live mode" in problem

    def test_every_key_problem_gets_its_own_bullet(self):
        with override_config(
            STRIPE_SECRET_KEY="sk_live_key", STRIPE_PUBLISHABLE_KEY=""
        ):
            row = static()["keys"]

        # The worst of the two decides the row's status.
        assert row["status"] == "error"
        assert [problem.split(" is ")[0] for problem in row["items"]] == [
            "Secret key",
            "Publishable key",
        ]

    def test_a_missing_webhook_secret_is_an_error(self):
        with override_config(STRIPE_WEBHOOK_SECRET=""):
            assert static()["webhook_secret"]["status"] == "error"

    def test_webhook_problems_are_only_info_when_nothing_uses_webhooks(self):
        with override_config(
            ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False, STRIPE_WEBHOOK_SECRET=""
        ):
            row = static()["webhook_secret"]

        assert row["status"] == "info"
        assert "only needed for membership payments" in row["detail"]

    def test_members_still_on_a_subscription_keep_webhooks_needed(self):
        ProfileFactory(stripe_subscription_id="sub_1")

        with override_config(
            ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False, STRIPE_WEBHOOK_SECRET=""
        ):
            assert static()["webhook_secret"]["status"] == "error"

    def test_the_default_site_url_is_a_warning(self):
        with override_config(SITE_URL="https://membermatters.org"):
            assert static()["webhook_url"]["status"] == "warning"

    def test_a_plain_http_site_url_is_a_warning(self):
        with override_config(SITE_URL="http://portal.example.org"):
            row = static()["webhook_url"]

        assert row["status"] == "warning"
        assert "https" in row["detail"]

    def test_with_stripe_off_there_is_nothing_to_check(self):
        with override_config(ENABLE_STRIPE=False):
            result = stripe_checks.get_static_checks()

        assert result["canTest"] is False
        assert [row["key"] for row in result["checks"]] == ["stripe"]


class TestConnection:
    def test_a_working_setup_passes_every_check(self, fake_stripe):
        fake_stripe.responses["/v1/webhook_endpoints"] = (200, listing(endpoint()))

        checks = connection_test()

        assert {key: row["status"] for key, row in checks.items()} == {
            "connection": "ok",
            "permissions": "ok",
            "webhook": "ok",
            "webhook_api_version": "ok",
        }
        assert checks["connection"]["value"] == "Connected, live mode"
        assert checks["permissions"]["value"] == "Read access to all 7 resources"
        assert checks["webhook"]["value"] == "Looks correctly set up"
        # Rows that pass carry no explanation or bullets.
        assert all(not row["detail"] and not row["items"] for row in checks.values())

    def test_only_reads_are_sent_with_the_pinned_version(self, fake_stripe):
        connection_test()

        assert fake_stripe.calls
        assert {method for method, _, _ in fake_stripe.calls} == {"get"}
        assert {version for _, _, version in fake_stripe.calls} == {VERSION}

    def test_an_answer_in_another_version_is_a_warning(self, fake_stripe):
        fake_stripe.answer_version = "2099-01-01"

        row = connection_test()["connection"]

        assert row["status"] == "warning"
        assert "2099-01-01" in row["detail"]

    def test_a_rejected_key_stops_the_test(self, fake_stripe):
        fake_stripe.responses["/v1/products"] = (
            401,
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid API Key provided: rk_live_***key",
                }
            },
        )

        checks = connection_test()

        assert checks["connection"]["status"] == "error"
        assert "Invalid API Key" in checks["connection"]["detail"]
        assert checks["permissions"]["status"] == "unknown"
        assert checks["webhook"]["status"] == "unknown"
        assert len(fake_stripe.calls) == 1

    def test_stripe_being_unreachable_stops_the_test(self, fake_stripe):
        fake_stripe.responses["/v1/products"] = stripe.APIConnectionError("timed out")

        checks = connection_test()

        assert checks["connection"]["value"] == "Can't reach Stripe"
        assert checks["webhook"]["value"] == "Skipped"

    def test_each_missing_permission_is_its_own_bullet(self, fake_stripe):
        fake_stripe.responses["/v1/invoices"] = denied()
        fake_stripe.responses["/v1/setup_intents"] = denied()

        row = connection_test()["permissions"]

        assert row["status"] == "error"
        assert row["value"] == "Missing 2 of 7"
        assert row["items"] == [
            "Missing permission: Invoices",
            "Missing permission: Setup Intents",
        ]
        assert not row["detail"]

    def test_no_access_to_products_still_counts_as_connected(self, fake_stripe):
        fake_stripe.responses["/v1/products"] = denied()

        checks = connection_test()

        assert checks["connection"]["status"] == "ok"
        assert checks["permissions"]["items"] == ["Missing permission: Products"]

    def test_no_access_to_webhook_endpoints_says_so(self, fake_stripe):
        fake_stripe.responses["/v1/webhook_endpoints"] = denied()

        row = connection_test()["webhook"]

        assert row["status"] == "unknown"
        assert row["value"] == "Can't check"
        assert row["items"] == ["Missing permission: Webhook Endpoints (read)"]

    def test_the_connection_test_needs_a_secret_key(self, fake_stripe):
        with override_config(STRIPE_SECRET_KEY=""):
            checks = connection_test()

        assert checks["connection"]["status"] == "error"
        assert fake_stripe.calls == []


class TestWebhookEndpoint:
    def check(self, fake_stripe, *endpoints):
        fake_stripe.responses["/v1/webhook_endpoints"] = (200, listing(*endpoints))
        return connection_test()

    def webhook(self, fake_stripe, *endpoints):
        return self.check(fake_stripe, *endpoints)["webhook"]

    def test_no_endpoints_at_all(self, fake_stripe):
        row = self.webhook(fake_stripe)

        assert row["status"] == "error"
        assert row["value"] == "No endpoint for this site"
        assert row["items"] == ["Stripe has no webhook endpoints in live mode."]

    def test_endpoints_for_other_sites_are_listed(self, fake_stripe):
        row = self.webhook(fake_stripe, endpoint(url="https://shop.example.org/hook"))

        assert row["status"] == "error"
        assert "https://shop.example.org/hook" in row["items"][0]

    def test_a_missing_trailing_slash_is_pointed_out(self, fake_stripe):
        row = self.webhook(fake_stripe, endpoint(url=WEBHOOK_URL.rstrip("/")))

        assert row["status"] == "error"
        assert "missing the trailing slash" in row["items"][0]

    def test_http_instead_of_https_is_pointed_out(self, fake_stripe):
        row = self.webhook(
            fake_stripe, endpoint(url=WEBHOOK_URL.replace("https", "http"))
        )

        assert "uses http instead of https" in row["items"][0]

    def test_another_host_on_our_path_points_at_site_url(self, fake_stripe):
        row = self.webhook(
            fake_stripe,
            endpoint(url="https://old.example.org/api/billing/stripe-webhook/"),
        )

        assert "but SITE_URL is portal.example.org" in row["items"][0]

    def test_a_disabled_endpoint_is_an_error(self, fake_stripe):
        row = self.webhook(fake_stripe, endpoint(status="disabled"))

        assert row["status"] == "error"
        assert row["value"] == "Not set up correctly"
        assert row["items"] == [
            "The endpoint is disabled, so Stripe isn't sending events to it."
        ]

    def test_missing_events_are_named(self, fake_stripe):
        row = self.webhook(
            fake_stripe,
            endpoint(enabled_events=["invoice.paid", "invoice.payment_failed"]),
        )

        assert row["status"] == "error"
        assert row["items"] == [
            "Missing events: customer.subscription.deleted, "
            "customer.subscription.updated."
        ]

    @pytest.mark.parametrize(
        "events", [["*"], [*HANDLED, "charge.refunded"]], ids=["all", "extra"]
    )
    def test_all_or_extra_events_are_fine(self, fake_stripe, events):
        row = self.webhook(fake_stripe, endpoint(enabled_events=events))

        assert row["status"] == "ok"
        assert row["items"] == []

    def test_every_endpoint_problem_is_its_own_bullet(self, fake_stripe):
        with override_config(STRIPE_WEBHOOK_SECRET=""):
            row = self.webhook(
                fake_stripe, endpoint(status="disabled", enabled_events=HANDLED[:3])
            )

        assert row["status"] == "error"
        assert len(row["items"]) == 3
        assert row["items"][2].startswith("STRIPE_WEBHOOK_SECRET is not set")

    def test_two_endpoints_for_this_site_are_a_warning(self, fake_stripe):
        row = self.webhook(
            fake_stripe,
            endpoint(id="we_1", status="disabled"),
            endpoint(id="we_2"),
        )

        assert row["status"] == "warning"
        assert row["value"] == "Set up, with warnings"
        # The enabled one is the one checked, so only the duplicate is reported.
        [problem] = row["items"]
        assert problem.startswith("Found 2 endpoints for this site")

    def test_an_endpoint_in_another_api_version_is_a_warning(self, fake_stripe):
        checks = self.check(fake_stripe, endpoint(api_version="2025-03-31.basil"))

        row = checks["webhook_api_version"]
        assert row["status"] == "warning"
        assert row["value"] == f"Enforced {VERSION}, endpoint sends 2025-03-31.basil"
        # The version has its own row, so the endpoint itself is fine.
        assert checks["webhook"]["status"] == "ok"

    def test_an_unpinned_endpoint_is_a_warning(self, fake_stripe):
        row = self.check(fake_stripe, endpoint(api_version=None))["webhook_api_version"]

        assert row["status"] == "warning"
        assert row["value"] == f"Enforced {VERSION}, endpoint sends the account default"

    def test_webhook_problems_are_only_info_when_nothing_uses_webhooks(
        self, fake_stripe
    ):
        with override_config(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False):
            row = self.webhook(fake_stripe)

        assert row["status"] == "info"


class TestViews:
    def test_admins_get_the_static_checks(self, admin_client):
        response = admin_client.get(reverse("StripeChecks"))

        assert response.status_code == 200
        assert response.data["canTest"] is True

    def test_admins_can_run_the_connection_test(self, admin_client, fake_stripe):
        response = admin_client.post(reverse("StripeConnectionTest"))

        assert response.status_code == 200
        assert response.data["checks"][0]["key"] == "connection"

    @pytest.mark.parametrize(
        "name, method",
        [
            ("StripeChecks", "get"),
            ("StripeConnectionTest", "post"),
        ],
    )
    def test_members_cant_see_the_checks(
        self, authed_client, fake_stripe, name, method
    ):
        response = getattr(authed_client, method)(reverse(name))

        assert response.status_code == 403
        assert fake_stripe.calls == []
