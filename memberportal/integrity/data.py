"""Plain data the checks work on: what MemberMatters says and what Stripe says.

Nothing here touches the database or the network, so the checks can be tested
with values written out by hand.
"""

import dataclasses
from datetime import datetime, timedelta
from typing import Optional


@dataclasses.dataclass(frozen=True)
class LocalBilling:
    """One member's subscription as a local source records it.

    `status` uses the vocabulary of Profile.subscription_status: inactive,
    active, cancelling or pending. The source for the Subscription table maps
    onto the same values, so the checks don't change.
    """

    profile_id: int
    name: str
    customer_id: Optional[str]
    subscription_id: Optional[str]
    status: str
    price_id: Optional[str]
    billing_method: str
    member_state: str
    state_locked: bool = False
    # Set only by the source for the Subscription table: the member's current
    # row, how many of their rows are live, and what the Profile columns
    # mirroring it say, read in the same query.
    subscription_pk: Optional[int] = None
    subscription_state: Optional[str] = None
    live_subscriptions: int = 0
    mirror: Optional["LocalBilling"] = None


@dataclasses.dataclass(frozen=True)
class StripeInvoice:
    id: str
    status: Optional[str]
    billing_reason: Optional[str]
    paid_at: Optional[datetime]


@dataclasses.dataclass(frozen=True)
class StripeSubscription:
    id: str
    customer: Optional[str]
    status: str
    cancel_at_period_end: bool
    cancel_at: Optional[datetime]
    canceled_at: Optional[datetime]
    ended_at: Optional[datetime]
    created: Optional[datetime]
    collection_method: Optional[str]
    price_ids: tuple
    latest_invoice: Optional[StripeInvoice] = None

    @property
    def cancel_scheduled(self):
        return self.cancel_at_period_end or self.cancel_at is not None

    @property
    def last_changed(self):
        """The latest moment Stripe's side of this subscription is known to have
        changed, so a webhook about it may still be on its way."""
        moments = [self.created, self.canceled_at, self.ended_at]
        if self.latest_invoice is not None:
            moments.append(self.latest_invoice.paid_at)
        moments = [moment for moment in moments if moment is not None]
        return max(moments) if moments else None


@dataclasses.dataclass(frozen=True)
class StripePrice:
    id: str
    active: bool
    unit_amount: Optional[int]
    currency: Optional[str]
    interval: Optional[str]
    interval_count: Optional[int]


@dataclasses.dataclass(frozen=True)
class StripeWebhookEndpoint:
    id: str
    url: str
    status: str
    enabled_events: tuple


@dataclasses.dataclass(frozen=True)
class StripeEvent:
    id: str
    type: str
    created: Optional[datetime]
    customer: Optional[str]


@dataclasses.dataclass(frozen=True)
class PlanInfo:
    id: int
    name: str
    stripe_id: str
    cost: int
    currency: str
    interval: str
    interval_count: int
    visible: bool


@dataclasses.dataclass(frozen=True)
class SkippedPart:
    """A part of the snapshot that couldn't be fetched, and why.

    `incomplete` is False when the part was skipped on purpose and will be
    every time, e.g. a restricted key without permission to read webhook
    endpoints. Those don't make a run incomplete.
    """

    reason: str
    incomplete: bool = True


# The parts of a snapshot a check can depend on.
SUBSCRIPTIONS = "subscriptions"
PRICES = "prices"
WEBHOOK_ENDPOINTS = "webhook_endpoints"
EVENTS = "events"


@dataclasses.dataclass
class StripeSnapshot:
    taken_at: datetime
    # Every live subscription (or, on a member re-check, every subscription of
    # the member's customer), plus each one a member tracks that Stripe still
    # knows about, whatever its status.
    subscriptions: dict = dataclasses.field(default_factory=dict)
    # Subscription ids a member tracks that Stripe answered 404 for.
    missing_subscriptions: set = dataclasses.field(default_factory=set)
    prices: dict = dataclasses.field(default_factory=dict)
    missing_prices: set = dataclasses.field(default_factory=set)
    webhook_endpoints: list = dataclasses.field(default_factory=list)
    undelivered_events: list = dataclasses.field(default_factory=list)
    skipped: dict = dataclasses.field(default_factory=dict)
    # Single objects that couldn't be fetched. What they concern is deferred,
    # and the run counts as incomplete.
    fetch_errors: list = dataclasses.field(default_factory=list)
    budget_exhausted: bool = False

    def has(self, part):
        return part not in self.skipped


@dataclasses.dataclass(frozen=True)
class Finding:
    """One thing a check found wrong.

    `subject` identifies what it is about within its check, so the same
    problem seen on the next run updates the same issue.
    """

    check: str
    severity: str
    subject: str
    message: str
    profile_id: Optional[int] = None
    # The Subscription row it is about, if any.
    subscription_pk: Optional[int] = None
    stripe_ref: str = ""
    # What MemberMatters says and what Stripe says, in a few words each.
    mm: str = ""
    stripe: str = ""
    # The likely cause and what an admin should do next.
    cause: str = ""
    action: str = ""
    extra: dict = dataclasses.field(default_factory=dict, compare=False)


@dataclasses.dataclass
class CheckContext:
    local: list
    snapshot: StripeSnapshot
    plans: list
    now: datetime
    # Stripe changes newer than this are left for the next run, since the
    # webhook announcing them may not have arrived yet.
    settle: timedelta = timedelta(0)
    webhook_url: str = ""
    handled_events: tuple = ()
    # True on a member re-check, which only fetched that member's customer.
    member_scope: bool = False
    deferred_profiles: set = dataclasses.field(default_factory=set)
    deferred_refs: set = dataclasses.field(default_factory=set)

    def is_deferred(self, profile_id=None, ref=None):
        return (profile_id is not None and profile_id in self.deferred_profiles) or (
            ref is not None and ref in self.deferred_refs
        )
