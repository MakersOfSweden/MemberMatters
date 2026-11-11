"""Fixtures for the integrity check tests.

`fake_stripe` stands in for the Stripe API at the SDK's class methods, the
module boundary, and hands back real StripeObjects so the snapshot code is
exercised against the types it gets in production. Write methods are patched
to fail the test outright: a run must only read.
"""

import pytest
import stripe
from constance.test import override_config

from api_admin_tools.models import PaymentPlan

ADMIN_ADDRESS = "admin@example.com"
SITE_URL = "https://portal.example.org"
WEBHOOK_URL = f"{SITE_URL}/api/billing/stripe-webhook/"

# Long enough ago that nothing falls inside the settle window.
LONG_AGO = 1_600_000_000

WRITE_METHODS = (
    (stripe.Subscription, ("create", "modify", "delete", "cancel")),
    (stripe.Invoice, ("create", "modify", "pay", "void_invoice", "finalize_invoice")),
    (stripe.Customer, ("create", "modify", "delete")),
    (stripe.Price, ("create", "modify")),
)


def stripe_subscription(
    subscription_id,
    customer,
    price,
    status="active",
    collection_method="charge_automatically",
    cancel_at_period_end=False,
    cancel_at=None,
    canceled_at=None,
    ended_at=None,
    created=LONG_AGO,
    invoice_status="paid",
    invoice_paid_at=LONG_AGO,
):
    latest_invoice = None
    if invoice_status is not None:
        latest_invoice = {
            "id": f"in_{subscription_id}",
            "object": "invoice",
            "status": invoice_status,
            "billing_reason": "subscription_create",
            "status_transitions": {
                "paid_at": invoice_paid_at if invoice_status == "paid" else None
            },
        }
    return {
        "id": subscription_id,
        "object": "subscription",
        "customer": customer,
        "status": status,
        "collection_method": collection_method,
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": cancel_at,
        "canceled_at": canceled_at,
        "ended_at": ended_at,
        "created": created,
        "items": {
            "object": "list",
            "data": [{"id": f"si_{subscription_id}", "price": {"id": price}}],
        },
        "latest_invoice": latest_invoice,
    }


def _missing(kind, object_id):
    return stripe.error.InvalidRequestError(
        f"No such {kind}: '{object_id}'", "id", code="resource_missing"
    )


class FakeStripe:
    def __init__(self):
        self.subscriptions = {}
        # Prices default to whatever matches the PaymentPlan, so a test only
        # sets the ones it wants to differ.
        self.prices = {}
        self.missing_prices = set()
        self.endpoints = [
            {
                "id": "we_site",
                "url": WEBHOOK_URL,
                "status": "enabled",
                "enabled_events": ["*"],
            }
        ]
        self.events = []
        # Method name → exception to raise from it.
        self.errors = {}
        self.calls = []
        self.writes = []

    def add(self, *args, **kwargs):
        subscription = stripe_subscription(*args, **kwargs)
        self.subscriptions[subscription["id"]] = subscription
        return subscription

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        error = self.errors.get(name)
        if error is not None:
            raise error

    @staticmethod
    def _page(data, url):
        return stripe.ListObject.construct_from(
            {"object": "list", "data": data, "has_more": False, "url": url}, "sk_test"
        )

    def subscription_list(self, **params):
        self._record("Subscription.list", **params)
        data = [
            subscription
            for subscription in self.subscriptions.values()
            if subscription["status"] != "canceled"
            and params.get("customer") in (None, subscription["customer"])
        ]
        return self._page(data, "/v1/subscriptions")

    def subscription_retrieve(self, subscription_id, **params):
        self._record("Subscription.retrieve", subscription_id, **params)
        if subscription_id not in self.subscriptions:
            raise _missing("subscription", subscription_id)
        return stripe.Subscription.construct_from(
            self.subscriptions[subscription_id], "sk_test"
        )

    def price_retrieve(self, price_id, **params):
        self._record("Price.retrieve", price_id)
        if price_id in self.missing_prices:
            raise _missing("price", price_id)
        price = self.prices.get(price_id)
        if price is None:
            plan = PaymentPlan.objects.filter(stripe_id=price_id).first()
            if plan is None:
                raise _missing("price", price_id)
            price = {
                "id": price_id,
                "active": True,
                "unit_amount": plan.cost,
                "currency": plan.currency,
                "recurring": {
                    "interval": plan.interval,
                    "interval_count": plan.interval_count,
                },
            }
        return stripe.Price.construct_from(price, "sk_test")

    def webhook_endpoint_list(self, **params):
        self._record("WebhookEndpoint.list", **params)
        return self._page(self.endpoints, "/v1/webhook_endpoints")

    def event_list(self, **params):
        self._record("Event.list", **params)
        return self._page(self.events, "/v1/events")

    def calls_to(self, name):
        return [call for call in self.calls if call[0] == name]


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(stripe.Subscription, "list", fake.subscription_list)
    monkeypatch.setattr(stripe.Subscription, "retrieve", fake.subscription_retrieve)
    monkeypatch.setattr(stripe.Price, "retrieve", fake.price_retrieve)
    monkeypatch.setattr(stripe.WebhookEndpoint, "list", fake.webhook_endpoint_list)
    monkeypatch.setattr(stripe.Event, "list", fake.event_list)

    for cls, names in WRITE_METHODS:
        for name in names:

            def write(*args, _name=f"{cls.__name__}.{name}", **kwargs):
                fake.writes.append(_name)
                raise AssertionError(f"The integrity check called {_name}")

            monkeypatch.setattr(cls, name, write)
    return fake


@pytest.fixture
def billing_on(db):
    """Turn on membership billing with a test key, so the check runs.

    BILLING_AUDIT_MAX_RPS is raised so the throttle doesn't slow the suite;
    the throttle itself is tested with a fake clock.
    """
    with override_config(
        ENABLE_STRIPE=True,
        ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True,
        STRIPE_SECRET_KEY="sk_test_integrity",
        BILLING_AUDIT_ENABLED=True,
        BILLING_AUDIT_MAX_RPS=10_000,
        EMAIL_ADMIN=ADMIN_ADDRESS,
        SITE_URL=SITE_URL,
    ):
        yield


def admin_mail(outbox):
    return [message for message in outbox if message["To"] == ADMIN_ADDRESS]
