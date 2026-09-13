"""Payload accessors — pure functions, no DB, no Django.

These read Stripe payloads whose shape depends on the API version configured
on the *webhook endpoint*, which the portal does not control: MemberMatters is
self-hosted, so one deployment's Stripe account predates
2025-03-31.basil and another's does not. Payloads are written as literals here
rather than through the shared builder, because the cases that matter are
precisely the ones a well-behaved builder would not construct.
"""

from api_billing.stripe_utils import (
    format_invoice_amount,
    invoice_billing_reason,
    invoice_subscription_id,
    is_subscription_invoice,
)


class TestInvoiceSubscriptionId:
    def test_it_reads_the_legacy_flat_field(self):
        assert invoice_subscription_id({"subscription": "sub_123"}) == "sub_123"

    def test_it_reads_the_basil_nested_field(self):
        payload = {"parent": {"subscription_details": {"subscription": "sub_123"}}}

        assert invoice_subscription_id(payload) == "sub_123"

    def test_an_explicit_null_under_basil_is_not_overridden_by_a_stale_flat_field(self):
        # The whole reason the lookup tests `"subscription" in details` rather
        # than its truthiness. Under basil an explicit null means "no
        # subscription on this invoice"; falling back to a leftover flat field
        # would attribute a one-off invoice to a membership subscription and
        # let it drive activation.
        payload = {
            "subscription": "sub_stale",
            "parent": {"subscription_details": {"subscription": None}},
        }

        assert invoice_subscription_id(payload) is None

    def test_a_parent_without_subscription_details_falls_back_to_the_flat_field(self):
        # An invoice can carry a parent for a non-subscription reason, in
        # which case the legacy field is still the authority.
        payload = {"subscription": "sub_123", "parent": {"type": "quote_details"}}

        assert invoice_subscription_id(payload) == "sub_123"

    def test_a_null_parent_falls_back_to_the_flat_field(self):
        payload = {"subscription": "sub_123", "parent": None}

        assert invoice_subscription_id(payload) == "sub_123"

    def test_an_invoice_with_no_subscription_anywhere_yields_none(self):
        assert invoice_subscription_id({"id": "in_123"}) is None


class TestBillingReason:
    def test_it_reads_the_billing_reason(self):
        assert invoice_billing_reason({"billing_reason": "subscription_cycle"}) == (
            "subscription_cycle"
        )

    def test_a_missing_billing_reason_is_none(self):
        assert invoice_billing_reason({}) is None


class TestFormatInvoiceAmount:
    def test_it_renders_cents_as_a_decimal_with_the_currency(self):
        assert (
            format_invoice_amount({"amount_paid": 5500, "currency": "aud"})
            == "55.00 AUD"
        )

    def test_it_falls_back_to_amount_due(self):
        # An invoice marked paid out of band carries amount_due but may not
        # carry amount_paid.
        assert format_invoice_amount({"amount_due": 1250, "currency": "eur"}) == (
            "12.50 EUR"
        )

    def test_amount_paid_wins_when_both_are_present(self):
        payload = {"amount_paid": 5500, "amount_due": 9900, "currency": "aud"}

        assert format_invoice_amount(payload) == "55.00 AUD"

    def test_a_zero_amount_is_rendered_not_treated_as_missing(self):
        # A fully discounted renewal is still a renewal.
        assert (
            format_invoice_amount({"amount_paid": 0, "currency": "aud"}) == "0.00 AUD"
        )

    def test_prefer_due_ignores_a_zero_amount_paid(self):
        # An unpaid invoice carries amount_paid=0, which must not be read as
        # "nothing is owed" when rendering what the member still has to pay.
        payload = {"amount_paid": 0, "amount_due": 5500, "currency": "aud"}

        assert format_invoice_amount(payload, prefer="due") == "55.00 AUD"

    def test_prefer_due_still_falls_back_to_amount_paid(self):
        assert (
            format_invoice_amount(
                {"amount_paid": 5500, "currency": "aud"}, prefer="due"
            )
            == "55.00 AUD"
        )

    def test_a_missing_currency_yields_the_bare_number(self):
        assert format_invoice_amount({"amount_paid": 5500}) == "55.00"

    def test_a_payload_with_no_amount_degrades_to_a_description(self):
        # Never interpolate None into member-facing copy.
        assert format_invoice_amount({}) == "your membership fee"


class TestIsSubscriptionInvoice:
    def test_every_subscription_reason_counts(self):
        for reason in (
            "subscription_create",
            "subscription_cycle",
            "subscription_update",
            "subscription_threshold",
        ):
            assert is_subscription_invoice({"billing_reason": reason}) is True

    def test_a_one_off_invoice_does_not(self):
        assert is_subscription_invoice({"billing_reason": "manual"}) is False

    def test_a_missing_billing_reason_does_not(self):
        # Must not raise on the None — this guards the branch that decides
        # whether a missing subscription id is an alarm or business as usual.
        assert is_subscription_invoice({}) is False
