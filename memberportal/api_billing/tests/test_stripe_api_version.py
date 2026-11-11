"""The Stripe API version MemberMatters sends with its requests."""

import stripe
from django.apps import apps


def test_startup_applies_the_pinned_api_version(settings, monkeypatch):
    # Pin a version the stripe library doesn't default to, so the test sees the
    # setting take effect rather than the library's own default.
    monkeypatch.setattr(stripe, "api_version", None)
    settings.STRIPE_API_VERSION = "2023-10-16"

    apps.get_app_config("api_billing").ready()

    assert stripe.api_version == "2023-10-16"
