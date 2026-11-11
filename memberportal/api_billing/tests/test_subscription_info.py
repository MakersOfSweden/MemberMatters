"""The subscription summaries shown to members and admins.

Stripe API 2025-03-31.basil moved current_period_end from the subscription to
its items, and MemberMatters requests a clover version, so the subscription
here is shaped the way Stripe now returns it.
"""

import pytest
import stripe
from django.urls import reverse
from rest_framework.test import APIClient

from membermatters.dates import from_unix
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db

PERIOD_END = 1790000000


@pytest.fixture
def subscriber():
    return ProfileFactory(
        membership_plan=PaymentPlanFactory(), stripe_subscription_id="sub_1"
    )


@pytest.fixture(autouse=True)
def clover_subscription(monkeypatch):
    subscription = stripe.Subscription.construct_from(
        {
            "id": "sub_1",
            "billing_cycle_anchor": 1780000000,
            "cancel_at": None,
            "cancel_at_period_end": False,
            "start_date": 1780000000,
            "collection_method": "charge_automatically",
            "latest_invoice": None,
            "items": {
                "object": "list",
                "data": [{"id": "si_1", "current_period_end": PERIOD_END}],
            },
        },
        "sk_test",
    )
    monkeypatch.setattr(
        stripe.Subscription, "retrieve", lambda *args, **kwargs: subscription
    )


def test_members_see_when_their_period_ends(subscriber):
    client = APIClient()
    client.force_authenticate(user=subscriber.user)

    response = client.get(reverse("SubscriptionInfo"))

    assert response.data["subscription"]["currentPeriodEnd"] == from_unix(PERIOD_END)


def test_admins_see_when_a_members_period_ends(admin_client, subscriber):
    response = admin_client.get(
        reverse("MemberSubscriptionInfo", args=[subscriber.user.id])
    )

    assert response.data["subscription"]["currentPeriodEnd"] == from_unix(PERIOD_END)
