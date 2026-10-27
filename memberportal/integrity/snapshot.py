"""Fetches what Stripe says, in as few requests as possible.

One page of Subscription.list covers 100 live subscriptions, with each latest
invoice expanded, so a full run costs about one request per 100 members plus
one per plan and a few more. Only subscriptions a member tracks that aren't in
that listing (ended, or unknown to Stripe) are fetched one by one.

Every request goes through the StripeReader. A part that fails is recorded in
`snapshot.skipped`, and the checks that need it are skipped.
"""

from datetime import timedelta

import stripe

from api_billing.webhook_handlers import HANDLERS
from membermatters.dates import from_unix

from .stripe_reader import StripeBudgetExceeded
from .data import (
    EVENTS,
    PRICES,
    SUBSCRIPTIONS,
    WEBHOOK_ENDPOINTS,
    SkippedPart,
    StripeEvent,
    StripeInvoice,
    StripePrice,
    StripeSnapshot,
    StripeSubscription,
    StripeWebhookEndpoint,
)

# The events the webhook acts on. An endpoint that doesn't send one of these
# loses billing state.
HANDLED_EVENTS = tuple(HANDLERS)

UNDELIVERED_EVENTS_WINDOW = timedelta(days=7)


def _id(value):
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def _when(value):
    return from_unix(value) if value else None


def parse_subscription(data):
    items = (data.get("items") or {}).get("data") or []
    price_ids = tuple(
        price_id for price_id in (_id(item.get("price")) for item in items) if price_id
    )

    latest_invoice = None
    invoice = data.get("latest_invoice")
    if isinstance(invoice, dict):
        transitions = invoice.get("status_transitions") or {}
        latest_invoice = StripeInvoice(
            id=invoice.get("id"),
            status=invoice.get("status"),
            billing_reason=invoice.get("billing_reason"),
            paid_at=_when(transitions.get("paid_at")),
        )

    return StripeSubscription(
        id=data["id"],
        customer=_id(data.get("customer")),
        status=data.get("status") or "",
        cancel_at_period_end=bool(data.get("cancel_at_period_end")),
        cancel_at=_when(data.get("cancel_at")),
        canceled_at=_when(data.get("canceled_at")),
        ended_at=_when(data.get("ended_at")),
        created=_when(data.get("created")),
        collection_method=data.get("collection_method"),
        price_ids=price_ids,
        latest_invoice=latest_invoice,
    )


def parse_price(data):
    recurring = data.get("recurring") or {}
    return StripePrice(
        id=data["id"],
        active=bool(data.get("active")),
        unit_amount=data.get("unit_amount"),
        currency=data.get("currency"),
        interval=recurring.get("interval"),
        interval_count=recurring.get("interval_count"),
    )


def parse_webhook_endpoint(data):
    return StripeWebhookEndpoint(
        id=data["id"],
        url=data.get("url") or "",
        status=data.get("status") or "",
        enabled_events=tuple(data.get("enabled_events") or ()),
    )


def parse_event(data):
    obj = (data.get("data") or {}).get("object") or {}
    return StripeEvent(
        id=data["id"],
        type=data.get("type") or "",
        created=_when(data.get("created")),
        customer=_id(obj.get("customer")),
    )


def _is_missing(error):
    return (
        isinstance(error, stripe.error.InvalidRequestError)
        and getattr(error, "code", None) == "resource_missing"
    )


def describe_error(error):
    if isinstance(error, stripe.error.AuthenticationError):
        return "Stripe refused the secret key"
    message = getattr(error, "user_message", None) or str(error) or type(error).__name__
    return f"Stripe error: {message}"


def _fetch_part(snapshot, part, fetch, optional=False):
    """Run one fetch, recording why it failed if it does.

    `optional` parts are ones a restricted key may lack permission for. That
    skips their checks without making every run incomplete.
    """
    if snapshot.budget_exhausted:
        snapshot.skipped[part] = SkippedPart(
            "the run used up its Stripe request budget"
        )
        return
    try:
        fetch()
    except StripeBudgetExceeded as error:
        snapshot.budget_exhausted = True
        snapshot.skipped[part] = SkippedPart(str(error))
    except stripe.error.PermissionError as error:
        snapshot.skipped[part] = SkippedPart(
            f"the Stripe key may not read {part.replace('_', ' ')}",
            incomplete=not optional,
        )
    except stripe.error.StripeError as error:
        snapshot.skipped[part] = SkippedPart(describe_error(error))


def build_snapshot(
    reader, tracked_subscription_ids, price_ids, now, customer_id=None, full=True
):
    """Fetch Stripe's side of everything the checks compare.

    A full run lists every live subscription. A member re-check (full=False)
    lists only `customer_id`'s, and skips the account-wide parts.
    """
    snapshot = StripeSnapshot(taken_at=now)

    def fetch_subscriptions():
        params = {"expand": ["data.latest_invoice"]}
        if not full:
            if not customer_id:
                params = None
            else:
                params["customer"] = customer_id
        if params is not None:
            for data in reader.list_all(stripe.Subscription.list, **params):
                subscription = parse_subscription(data)
                snapshot.subscriptions[subscription.id] = subscription

        for subscription_id in sorted(set(tracked_subscription_ids)):
            if subscription_id in snapshot.subscriptions:
                continue
            try:
                data = reader.call(
                    stripe.Subscription.retrieve,
                    subscription_id,
                    expand=["latest_invoice"],
                )
            except stripe.error.InvalidRequestError as error:
                if _is_missing(error):
                    snapshot.missing_subscriptions.add(subscription_id)
                else:
                    snapshot.fetch_errors.append(
                        f"{subscription_id}: {describe_error(error)}"
                    )
                continue
            snapshot.subscriptions[subscription_id] = parse_subscription(data)

    _fetch_part(snapshot, SUBSCRIPTIONS, fetch_subscriptions)
    if not full:
        return snapshot

    def fetch_prices():
        for price_id in sorted(set(price_ids)):
            try:
                data = reader.call(stripe.Price.retrieve, price_id)
            except stripe.error.InvalidRequestError as error:
                if not _is_missing(error):
                    raise
                snapshot.missing_prices.add(price_id)
                continue
            snapshot.prices[price_id] = parse_price(data)

    def fetch_webhook_endpoints():
        snapshot.webhook_endpoints = [
            parse_webhook_endpoint(data)
            for data in reader.list_all(stripe.WebhookEndpoint.list)
        ]

    def fetch_events():
        since = int((now - UNDELIVERED_EVENTS_WINDOW).timestamp())
        snapshot.undelivered_events = [
            parse_event(data)
            for data in reader.list_all(
                stripe.Event.list,
                delivery_success=False,
                types=list(HANDLED_EVENTS),
                created={"gte": since},
            )
        ]

    _fetch_part(snapshot, PRICES, fetch_prices)
    _fetch_part(snapshot, WEBHOOK_ENDPOINTS, fetch_webhook_endpoints, optional=True)
    _fetch_part(snapshot, EVENTS, fetch_events, optional=True)
    return snapshot
