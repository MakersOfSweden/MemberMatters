"""The membership subscription PaymentPlanSignup creates in Stripe."""

import pytest
import stripe
from rest_framework.test import APIRequestFactory

from api_billing.views import PaymentPlanSignup
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def created(monkeypatch):
    """The parameters of every Subscription.create call."""
    calls = []

    def _create(**params):
        calls.append(params)
        return stripe.Subscription.construct_from(
            {"id": "sub_new", "latest_invoice": None}, "sk_test"
        )

    monkeypatch.setattr(stripe.Subscription, "create", _create)
    return calls


@pytest.mark.parametrize("billing_method", ["card", "invoice"])
def test_new_subscriptions_use_classic_billing_mode(created, billing_method):
    # Stripe defaults to flexible from 2025-09-30.clover; every subscription
    # created before that is classic, so new ones must be too.
    profile = ProfileFactory(stripe_customer_id="cus_1")
    request = APIRequestFactory().post("/")
    request.user = profile.user

    subscription, error = PaymentPlanSignup().create_subscription(
        request, PaymentPlanFactory(), billing_method=billing_method
    )

    assert error is None
    [params] = created
    assert params["billing_mode"] == {"type": "classic"}
    if billing_method == "invoice":
        assert params["collection_method"] == "send_invoice"
