"""Reading Stripe's side: parsing its objects and coping when parts fail."""

from datetime import datetime, timezone

import pytest
import stripe

from integrity.data import EVENTS, PRICES, SUBSCRIPTIONS, WEBHOOK_ENDPOINTS
from integrity.snapshot import build_snapshot, parse_subscription
from integrity.stripe_reader import StripeReader

from .conftest import stripe_subscription

NOW = datetime(2026, 10, 21, 3, 15, tzinfo=timezone.utc)


def fast_reader(**kwargs):
    return StripeReader(rate=10_000, sleep=lambda seconds: None, **kwargs)


def test_parses_a_subscription_with_its_latest_invoice():
    data = stripe.Subscription.construct_from(
        stripe_subscription(
            "sub_1",
            "cus_1",
            "price_1",
            status="past_due",
            cancel_at_period_end=True,
            cancel_at=1_700_000_000,
            invoice_status="open",
        ),
        "sk_test",
    )

    subscription = parse_subscription(data)

    assert subscription.id == "sub_1"
    assert subscription.customer == "cus_1"
    assert subscription.status == "past_due"
    assert subscription.price_ids == ("price_1",)
    assert subscription.cancel_scheduled
    assert subscription.cancel_at == datetime.fromtimestamp(1_700_000_000, timezone.utc)
    assert subscription.latest_invoice.status == "open"
    assert subscription.latest_invoice.paid_at is None


def test_an_unexpanded_invoice_and_customer_object_are_handled():
    data = stripe_subscription("sub_1", "cus_1", "price_1")
    data["latest_invoice"] = "in_1"
    data["customer"] = {"id": "cus_1", "object": "customer"}

    subscription = parse_subscription(stripe.Subscription.construct_from(data, "sk"))

    assert subscription.latest_invoice is None
    assert subscription.customer == "cus_1"


@pytest.mark.django_db
class TestBuildSnapshot:
    def test_a_member_recheck_reads_only_their_customer(self, fake_stripe):
        fake_stripe.add("sub_1", "cus_1", "price_1")
        fake_stripe.add("sub_2", "cus_2", "price_1")

        snapshot = build_snapshot(
            fast_reader(), ["sub_1"], ["price_1"], NOW, customer_id="cus_1", full=False
        )

        assert list(snapshot.subscriptions) == ["sub_1"]
        assert fake_stripe.calls_to("Price.retrieve") == []

    def test_records_tracked_subscriptions_stripe_doesnt_know(self, fake_stripe):
        snapshot = build_snapshot(fast_reader(), ["sub_gone"], [], NOW)

        assert snapshot.missing_subscriptions == {"sub_gone"}
        assert snapshot.has(SUBSCRIPTIONS)

    def test_a_failed_part_skips_only_that_part(self, fake_stripe):
        fake_stripe.errors["Event.list"] = stripe.error.APIError("down")

        snapshot = build_snapshot(fast_reader(), [], [], NOW)

        assert not snapshot.has(EVENTS)
        assert snapshot.skipped[EVENTS].incomplete
        assert snapshot.has(SUBSCRIPTIONS) and snapshot.has(WEBHOOK_ENDPOINTS)

    def test_used_up_budget_skips_the_rest(self, fake_stripe):
        fake_stripe.add("sub_1", "cus_1", "price_1")

        snapshot = build_snapshot(
            fast_reader(max_requests=1), ["sub_1"], ["price_1"], NOW
        )

        assert snapshot.has(PRICES)
        assert snapshot.budget_exhausted
        for part in (WEBHOOK_ENDPOINTS, EVENTS, SUBSCRIPTIONS):
            assert snapshot.skipped[part].incomplete

    def test_reads_subscriptions_last(self, fake_stripe):
        build_snapshot(fast_reader(), [], ["price_1"], NOW)

        assert fake_stripe.calls[-1][0] == "Subscription.list"

    def test_asks_only_for_recent_undelivered_billing_events(self, fake_stripe):
        build_snapshot(fast_reader(), [], [], NOW)

        [(_name, _args, params)] = fake_stripe.calls_to("Event.list")
        assert params["delivery_success"] is False
        assert "invoice.paid" in params["types"]
        assert params["created"] == {"gte": int(NOW.timestamp()) - 7 * 24 * 3600}
