"""The member details a Stripe customer holds, and keeping them up to date.

Stripe gets the email, the name (first and last together), the phone number
and the address, from the profile fields. A hidden field is never sent.
"""

import stripe
from constance import config
from django.db import transaction
from sentry_sdk import capture_exception

from profile.profile_changes import stored_values
from profile.profile_fields import HIDDEN, field_mode
from services.emails import send_email_to_admin


def customer_details(values):
    """The Stripe customer fields for a member's profile values.

    `values` is {field key: value}, as profile_changes.stored_values() gives
    it. Hidden and blank fields are left out.
    """
    details = {
        "email": values["email"],
        "name": f"{values['firstName']} {values['lastName']}",
    }
    if field_mode("phone") != HIDDEN and values.get("phone"):
        details["phone"] = values["phone"]
    if field_mode("address") != HIDDEN and values.get("address"):
        details["address"] = dict(values["address"])
    return details


# The parts of a Stripe address. The portal doesn't collect "state" (see
# ADDRESS_PARTS in profile_fields.py), so it is always blank on its side.
STRIPE_ADDRESS_KEYS = ("line1", "line2", "postal_code", "city", "state", "country")

# The profile fields each Stripe customer field is made from.
STRIPE_FIELDS = {
    "email": ("email",),
    "name": ("firstName", "lastName"),
    "phone": ("phone",),
    "address": ("address",),
}

STRIPE_FIELD_LABELS = {
    "email": "Email",
    "name": "Name",
    "phone": "Phone",
    "address": "Address",
}


def _stripe_value(key, values):
    """What the Stripe customer field `key` holds for these profile values."""
    if key == "name":
        return f"{values['firstName']} {values['lastName']}"
    return values[key] or ("" if key != "address" else {})


def _comparable(key, value):
    """A Stripe or portal value in a form the two can be compared in: blank
    is "", text is trimmed, the email ignores case, and an address has every
    part."""
    if key == "address":
        value = value or {}
        return {part: (value.get(part) or "").strip() for part in STRIPE_ADDRESS_KEYS}
    value = (value or "").strip()
    return value.lower() if key == "email" else value


def _to_stripe(key, value):
    """A value as Customer.modify takes it. A blank one is sent as "", which
    Stripe reads as "remove"."""
    if key == "address":
        return (
            {part: value.get(part, "") for part in STRIPE_ADDRESS_KEYS} if value else ""
        )
    return value


def _describe(key, value):
    if key == "address":
        parts = [
            value.get(part) for part in STRIPE_ADDRESS_KEYS if value and value.get(part)
        ]
        return f'"{", ".join(parts)}"' if parts else "nothing"
    return f'"{value}"' if value else "nothing"


def update_stripe_customer_on_commit(profile, changed):
    """Copies a profile edit to the member's Stripe customer once it commits.

    `changed` is what save_profile_changes() returned. A detail is only
    updated where Stripe still has the value the portal had before the edit.
    One that differs was changed in Stripe some other way, so it is left
    alone, logged on the member and emailed to the admin. Hidden fields are
    never sent.
    """
    keys = [
        key
        for key, fields in STRIPE_FIELDS.items()
        if any(field in changed for field in fields)
        and all(field_mode(field) != HIDDEN for field in fields)
    ]
    if not keys or not profile.stripe_customer_id:
        return

    new = stored_values(profile)
    old = {**new, **{key: before for key, (before, _after) in changed.items()}}
    user = profile.user
    customer_id = profile.stripe_customer_id

    transaction.on_commit(lambda: _update_customer(user, customer_id, keys, old, new))


def _update_customer(user, customer_id, keys, old, new):
    if not config.ENABLE_STRIPE or not config.STRIPE_SECRET_KEY:
        return
    stripe.api_key = config.STRIPE_SECRET_KEY

    drifted = []
    try:
        customer = stripe.Customer.retrieve(customer_id)
        if customer.get("deleted"):
            return

        updates = {}
        for key in keys:
            in_stripe = customer.get(key)
            if _comparable(key, in_stripe) == _comparable(key, _stripe_value(key, old)):
                updates[key] = _to_stripe(key, _stripe_value(key, new))
            else:
                drifted.append(
                    (key, in_stripe, _stripe_value(key, old), _stripe_value(key, new))
                )

        if updates:
            stripe.Customer.modify(customer_id, **updates)
            user.log_event(
                f"Updated the Stripe customer's {', '.join(updates)}.", "stripe"
            )
    except stripe.error.StripeError as e:
        capture_exception(e)
        user.log_event("Error while updating the Stripe customer.", "stripe", str(e))
        return

    if drifted:
        _report_drift(user, customer_id, drifted)


def _report_drift(user, customer_id, drifted):
    details = " ".join(
        f"{STRIPE_FIELD_LABELS[key]}: Stripe has {_describe(key, in_stripe)}, the "
        f"portal had {_describe(key, before)} and now has {_describe(key, after)}."
        for key, in_stripe, before, after in drifted
    )
    names = ", ".join(STRIPE_FIELD_LABELS[key].lower() for key, *_ in drifted)
    user.log_event(
        f"Didn't update the Stripe customer's {names}: Stripe didn't have what "
        "the portal had before the change.",
        "stripe",
        details,
    )

    subject = f"{user.get_full_name()}'s details in Stripe weren't updated"
    message = (
        f"{user.get_full_name()}'s profile was changed in the portal, but some "
        f"of their details on Stripe customer {customer_id} weren't updated, "
        "because Stripe no longer had what the portal had before the change. "
        "They may have been edited in Stripe directly. Please compare them and "
        f"update Stripe by hand if needed. {details}"
    )
    try:
        send_email_to_admin(
            subject=subject,
            template_vars={"title": subject, "message": message},
            user=user,
            reply_to=user.email,
        )
    except Exception as e:
        capture_exception(e)
