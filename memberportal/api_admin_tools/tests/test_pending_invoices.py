"""Admin Pending Invoices panel and out-of-band mark-paid.

An invoice-billed member owes an invoice at signup and again at every renewal.
Bank transfer and cash are how many of those members pay, so every one of those
invoices must be listable and markable — not just the first.
"""

from types import SimpleNamespace

import pytest
import stripe
from django.urls import reverse

from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db

SUBSCRIPTION_ID = "sub_member"

OWING = [
    pytest.param("noob", "pending", id="signup"),
    pytest.param("active", "active", id="renewal"),
    pytest.param("active", "cancelling", id="final-renewal"),
]

NOT_OWING = [
    pytest.param(
        {"billing_method": "card", "state": "active", "subscription_status": "active"},
        id="card-member",
    ),
    pytest.param(
        {"state": "inactive", "subscription_status": "inactive"},
        id="subscription-ended",
    ),
]


def build_invoice(invoice_id="in_open", subscription=SUBSCRIPTION_ID, schema="legacy"):
    data = {
        "id": invoice_id,
        "number": "INV-0001",
        "amount_due": 5500,
        "currency": "aud",
        "created": 1700000000,
        "due_date": 1702592000,
        "hosted_invoice_url": "https://invoice.stripe.com/i/test",
    }
    if schema == "basil":
        data["parent"] = {"subscription_details": {"subscription": subscription}}
    else:
        data["subscription"] = subscription
    return stripe.Invoice.construct_from(data, "sk_test")


def invoice_member(subscription_id=SUBSCRIPTION_ID, **overrides):
    return ProfileFactory(
        **{
            "billing_method": "invoice",
            "stripe_subscription_id": subscription_id,
            "membership_plan": PaymentPlanFactory(),
            **overrides,
        }
    )


class _InvoiceList:
    def __init__(self, data):
        self.data = data

    def auto_paging_iter(self):
        return iter(self.data)


@pytest.fixture
def stripe_invoices(monkeypatch):
    """Stands in for the stripe.Invoice calls both views make, recording each."""
    fake = SimpleNamespace(open=[], calls=[], list_error=None)

    def _list(**params):
        fake.calls.append(("list", params))
        if fake.list_error is not None:
            raise fake.list_error
        return _InvoiceList(fake.open)

    def _retrieve(invoice_id):
        fake.calls.append(("retrieve", invoice_id))
        return next(invoice for invoice in fake.open if invoice.id == invoice_id)

    def _pay(invoice_id, **params):
        fake.calls.append(("pay", invoice_id, params))

    def _modify(invoice_id, **params):
        fake.calls.append(("modify", invoice_id, params))

    for name, fn in (
        ("list", _list),
        ("retrieve", _retrieve),
        ("pay", _pay),
        ("modify", _modify),
    ):
        monkeypatch.setattr(stripe.Invoice, name, fn)
    return fake


def listed(client):
    response = client.get(reverse("PendingInvoices"))
    assert response.status_code == 200
    return [row["invoiceId"] for row in response.data]


def mark_paid(client, invoice_id="in_open"):
    return client.post(
        reverse("MarkInvoicePaid", args=[invoice_id]), {"comment": "bank transfer"}
    )


def paid(stripe_invoices):
    return [call[1] for call in stripe_invoices.calls if call[0] == "pay"]


class TestPendingInvoices:
    @pytest.mark.parametrize("state, subscription_status", OWING)
    def test_an_open_invoice_is_listed_at_signup_and_at_every_renewal(
        self, admin_client, stripe_invoices, state, subscription_status
    ):
        invoice_member(state=state, subscription_status=subscription_status)
        stripe_invoices.open = [build_invoice()]

        assert listed(admin_client) == ["in_open"]

    def test_a_row_carries_what_an_admin_needs_to_match_a_payment(
        self, admin_client, stripe_invoices
    ):
        profile = invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice()]

        [row] = admin_client.get(reverse("PendingInvoices")).data

        assert row == {
            "memberId": profile.user.id,
            "memberName": profile.get_full_name(),
            "memberEmail": profile.user.email,
            "planName": profile.membership_plan.name,
            "invoiceId": "in_open",
            "invoiceNumber": "INV-0001",
            "amountDue": 5500,
            "currency": "aud",
            "created": 1700000000,
            "dueDate": 1702592000,
            "hostedInvoiceUrl": "https://invoice.stripe.com/i/test",
        }

    def test_every_open_invoice_of_a_member_is_listed(
        self, admin_client, stripe_invoices
    ):
        # An unpaid renewal does not stop Stripe issuing the next one.
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice("in_new"), build_invoice("in_old")]

        assert listed(admin_client) == ["in_new", "in_old"]

    def test_the_nested_subscription_field_is_read(self, admin_client, stripe_invoices):
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice(schema="basil")]

        assert listed(admin_client) == ["in_open"]

    @pytest.mark.parametrize("overrides", NOT_OWING)
    def test_an_invoice_outside_an_invoice_billed_membership_is_not_listed(
        self, admin_client, stripe_invoices, overrides
    ):
        invoice_member(**overrides)
        stripe_invoices.open = [build_invoice()]

        assert listed(admin_client) == []

    def test_an_invoice_on_an_untracked_subscription_is_not_listed(
        self, admin_client, stripe_invoices
    ):
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice(subscription="sub_someone_else")]

        assert listed(admin_client) == []

    def test_stripe_is_asked_once_however_many_members_owe(
        self, admin_client, stripe_invoices
    ):
        for n in range(3):
            invoice_member(
                subscription_id=f"sub_{n}", state="active", subscription_status="active"
            )
        stripe_invoices.open = [
            build_invoice(f"in_{n}", subscription=f"sub_{n}") for n in range(3)
        ]

        assert sorted(listed(admin_client)) == ["in_0", "in_1", "in_2"]
        assert stripe_invoices.calls == [
            (
                "list",
                {"status": "open", "collection_method": "send_invoice", "limit": 100},
            )
        ]

    def test_nobody_on_invoice_billing_means_no_stripe_call(
        self, admin_client, stripe_invoices
    ):
        assert listed(admin_client) == []
        assert stripe_invoices.calls == []

    def test_a_stripe_outage_is_reported_rather_than_shown_as_nothing_owed(
        self, admin_client, stripe_invoices
    ):
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.list_error = stripe.error.APIConnectionError("down")

        response = admin_client.get(reverse("PendingInvoices"))

        assert response.status_code == 503

    def test_a_non_admin_cannot_list_invoices(self, authed_client, stripe_invoices):
        response = authed_client.get(reverse("PendingInvoices"))

        assert response.status_code == 403
        assert stripe_invoices.calls == []


class TestMarkInvoicePaid:
    @pytest.mark.parametrize("state, subscription_status", OWING)
    def test_an_open_invoice_can_be_marked_paid_at_signup_and_at_every_renewal(
        self, admin_client, stripe_invoices, state, subscription_status
    ):
        invoice_member(state=state, subscription_status=subscription_status)
        stripe_invoices.open = [build_invoice()]

        response = mark_paid(admin_client)

        assert response.status_code == 200
        assert paid(stripe_invoices) == ["in_open"]
        assert ("pay", "in_open", {"paid_out_of_band": True}) in stripe_invoices.calls

    def test_the_nested_subscription_field_is_read(self, admin_client, stripe_invoices):
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice(schema="basil")]

        assert mark_paid(admin_client).status_code == 200
        assert paid(stripe_invoices) == ["in_open"]

    @pytest.mark.parametrize("overrides", NOT_OWING)
    def test_an_invoice_outside_an_invoice_billed_membership_is_refused(
        self, admin_client, stripe_invoices, overrides
    ):
        invoice_member(**overrides)
        stripe_invoices.open = [build_invoice()]

        assert mark_paid(admin_client).status_code == 400
        assert paid(stripe_invoices) == []

    def test_an_invoice_with_no_subscription_is_refused(
        self, admin_client, stripe_invoices
    ):
        # A one-off charge in the same Stripe account, e.g. a memberbucks top-up.
        invoice_member(state="active", subscription_status="active")
        stripe_invoices.open = [build_invoice(subscription=None)]

        assert mark_paid(admin_client).status_code == 400
        assert paid(stripe_invoices) == []
