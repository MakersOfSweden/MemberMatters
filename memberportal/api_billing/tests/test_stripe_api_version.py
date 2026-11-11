"""The Stripe API version MemberMatters sends with its requests, and the
stripe-python behaviour it relies on."""

import stripe
from django.apps import apps


def test_startup_applies_the_pinned_api_version(settings, monkeypatch):
    # Pin a version the stripe library doesn't default to, so the test sees the
    # setting take effect rather than the library's own default.
    monkeypatch.setattr(stripe, "api_version", None)
    settings.STRIPE_API_VERSION = "2023-10-16"

    apps.get_app_config("api_billing").ready()

    assert stripe.api_version == "2023-10-16"


def test_stripe_objects_are_still_dicts():
    assert issubclass(stripe.StripeObject, dict), (
        "From stripe-python 15, Stripe objects aren't dicts: they have no .get() "
        "and iterating one raises TypeError. MemberMatters reads them as dicts, "
        "e.g. in api_billing/webhook_handlers.py and integrity/snapshot.py, so "
        "convert them with .to_dict() before bumping stripe."
    )
