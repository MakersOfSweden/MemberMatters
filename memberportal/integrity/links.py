"""Links from an issue to where an admin can act on it."""

from constance import config

# Stripe object id prefix → dashboard section.
_DASHBOARD_PATHS = (
    ("sub_", "subscriptions"),
    ("cus_", "customers"),
    ("price_", "prices"),
    ("we_", "webhooks"),
    ("evt_", "events"),
    ("in_", "invoices"),
)


def _site_url():
    return (config.SITE_URL or "").rstrip("/")


def stripe_test_mode():
    return (config.STRIPE_SECRET_KEY or "").startswith(("sk_test_", "rk_test_"))


def stripe_dashboard_url(ref):
    if not ref:
        return None
    for prefix, path in _DASHBOARD_PATHS:
        if ref.startswith(prefix):
            mode = "/test" if stripe_test_mode() else ""
            return f"https://dashboard.stripe.com{mode}/{path}/{ref}"
    return None


def member_url(profile):
    if profile is None:
        return None
    return f"{_site_url()}/manage/members/{profile.user_id}"


def page_url():
    return f"{_site_url()}/manage/billing-integrity"
