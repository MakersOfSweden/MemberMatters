"""Fixtures for the Stripe webhook and billing API tests.

Deliberately local to `api_billing` rather than added to the top-level
conftest/factories: nothing outside billing needs a Stripe-subscribed member,
and keeping the new seams here means this package can be reviewed — and
rebased — without touching the shared fixtures every other suite depends on.

The stub strategy follows memberportal/conftest.py: patch each service at its
module boundary. The autouse `_no_network` guard is the backstop — any Stripe
call these fixtures fail to intercept raises NetworkAccessInTestError naming
api.stripe.com, instead of hanging or, worse, silently passing.
"""

import factory
import pytest
from constance.test import override_config

from api_admin_tools.models import MemberTier, PaymentPlan
from tests.factories import ProfileFactory


class MemberTierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MemberTier

    # name, description and stripe_id are all unique on the model.
    name = factory.Sequence(lambda n: f"Tier {n}")
    description = factory.Sequence(lambda n: f"Tier {n} description")
    stripe_id = factory.Sequence(lambda n: f"prod_tier{n}")


class PaymentPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentPlan

    name = factory.Sequence(lambda n: f"Plan {n}")
    description = "Test plan"
    stripe_id = factory.Sequence(lambda n: f"price_plan{n}")
    member_tier = factory.SubFactory(MemberTierFactory)
    cost = 5500
    interval_count = 1
    interval = "month"


CUSTOMER_ID = "cus_test123"
SUBSCRIPTION_ID = "sub_test123"


@pytest.fixture
def subscribed_member(db):
    """An invoice-billing member awaiting their first payment.

    The webhook resolves the Profile by stripe_customer_id and then scopes the
    event against stripe_subscription_id, so both must be set for any event to
    reach a handler.

    subscription_status is "pending" because that is what PaymentPlanSignup
    writes for billing_method="invoice", and it is load bearing: the handler
    evaluates can_signup() *before* it sets the status to "active", and
    can_signup() counts "subscription" as an unmet requirement for any status
    outside ("active", "pending"). A member left at "inactive" here would
    therefore take the requirements-unmet branch and never activate.
    """
    return ProfileFactory(
        subscription_pending=True,
        billing_method="invoice",
        stripe_customer_id=CUSTOMER_ID,
        stripe_subscription_id=SUBSCRIPTION_ID,
        membership_plan=PaymentPlanFactory(),
    )


@pytest.fixture(autouse=True)
def webhook_secret(request):
    """Configure a signing secret for every test in this package.

    STRIPE_WEBHOOK_SECRET defaults to "" (constance_config.py), and the view
    fails closed with 503 when it is unset — so without this, every
    behavioural test would pass vacuously against the wrong branch. Tests that
    are *about* the unset case override it back with the usual marker, which
    is applied after this fixture and therefore wins.

    Skipped for tests with no database: constance persists through the DB
    backend, so touching config would drag the payload-accessor unit tests
    into needing django_db purely as a fixture side effect.
    """
    if not {"db", "transactional_db", "django_db_setup"} & set(request.fixturenames):
        yield
        return

    with override_config(STRIPE_WEBHOOK_SECRET="whsec_test"):
        yield


@pytest.fixture
def stripe_event(monkeypatch):
    """Bypass signature verification and inject a decoded event.

    Returns a setter taking either `event=<dict>` or `exc=<Exception>`. Tests
    POST a placeholder body, since construct_event never parses it here.
    """
    holder = {}

    def _construct_event(payload, sig_header, secret):
        if "exc" in holder:
            raise holder["exc"]
        return holder["event"]

    monkeypatch.setattr(
        "api_billing.views.stripe.Webhook.construct_event", _construct_event
    )

    def _set(event=None, exc=None):
        holder.clear()
        if exc is not None:
            holder["exc"] = exc
        else:
            holder["event"] = event

    return _set


class StripeAPIRecorder:
    """Records stripe.Invoice.* / stripe.Subscription.* calls made by handlers."""

    def __init__(self):
        self.calls = []
        self.open_invoices = []
        self.invoices = {}
        self.raise_on = {}

    def _record(self, name):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            failure = self.raise_on.get(name)
            if isinstance(failure, list):
                # Per-call script: one entry consumed per invocation, None
                # meaning "this one succeeds". Lets a test fail the first
                # void_invoice and still assert the second was attempted.
                failure = failure.pop(0) if failure else None
            if failure is not None:
                raise failure
            return self._result(name, *args, **kwargs)

        return _call

    def _result(self, name, *args, **kwargs):
        if name == "Invoice.list":
            return _InvoiceList(self.open_invoices)
        if name == "Invoice.retrieve":
            return self.invoices.get(args[0], {})
        return {}

    def names(self):
        return [name for name, _, _ in self.calls]


class _InvoiceList:
    """Minimal stand-in for Stripe's ListObject (auto_paging_iter only)."""

    def __init__(self, data):
        self.data = data

    def auto_paging_iter(self):
        return iter(self.data)


@pytest.fixture
def stripe_api(monkeypatch):
    recorder = StripeAPIRecorder()
    for target in (
        "Invoice.list",
        "Invoice.pay",
        "Invoice.retrieve",
        "Invoice.modify",
        "Invoice.void_invoice",
        "Invoice.finalize_invoice",
        "Subscription.retrieve",
        "Subscription.delete",
    ):
        cls, method = target.split(".")
        monkeypatch.setattr(
            f"stripe.{cls}.{method}", recorder._record(target), raising=False
        )
    return recorder


# --- payload builders -------------------------------------------------------
#
# Parametrized over both Stripe payload schemas so invoice_subscription_id()
# is exercised in each. `legacy` exposes the flat Invoice.subscription;
# `basil` (API 2025-03-31) exposes parent.subscription_details.subscription
# and omits the flat key entirely.


@pytest.fixture(params=["legacy", "basil"])
def invoice_schema(request):
    return request.param


def build_invoice(
    schema="legacy",
    *,
    customer=CUSTOMER_ID,
    subscription=SUBSCRIPTION_ID,
    status="paid",
    billing_reason="subscription_cycle",
    invoice_id="in_test123",
    **extra,
):
    data = {
        "id": invoice_id,
        "customer": customer,
        "status": status,
        "billing_reason": billing_reason,
        **extra,
    }
    if subscription is not None:
        if schema == "basil":
            data["parent"] = {"subscription_details": {"subscription": subscription}}
        else:
            data["subscription"] = subscription
    return data


def build_event(event_type, obj, event_id="evt_test123", previous_attributes=None):
    data = {"object": obj}
    if previous_attributes is not None:
        data["previous_attributes"] = previous_attributes
    return {"id": event_id, "type": event_type, "data": data}


@pytest.fixture
def post_webhook(api_client):
    """POST to the webhook endpoint. Body is ignored — see `stripe_event`."""

    def _post():
        return api_client.post(
            "/api/billing/stripe-webhook/",
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=stub",
        )

    return _post
