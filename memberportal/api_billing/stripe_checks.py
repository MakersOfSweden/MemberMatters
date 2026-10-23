"""Checks behind the Stripe card on the admin Payment Overview page.

Each check is a row with the same shape as the admin Email delivery page uses:
key, label, status (ok, warning, error, info or unknown), value and detail.

The static checks only read MemberMatters' own settings. The connection test
calls Stripe with read-only requests: it never creates or changes anything
there, so it is safe to run against a live account.
"""

from urllib.parse import urlsplit

import stripe
from constance import config
from django.conf import settings
from django.urls import reverse

from api_billing.webhook_handlers import HANDLERS
from profile.models import Profile

OK, WARNING, ERROR, INFO, UNKNOWN = "ok", "warning", "error", "info", "unknown"
_SEVERITY = {OK: 0, INFO: 0, UNKNOWN: 1, WARNING: 2, ERROR: 3}

STRIPE_TIMEOUT_SECONDS = 10

HANDLED_EVENTS = sorted(HANDLERS)

SECRET_KEY_PREFIXES = {
    "sk_live_": ("Standard", "live"),
    "sk_test_": ("Standard", "test"),
    "rk_live_": ("Restricted", "live"),
    "rk_test_": ("Restricted", "test"),
}
PUBLISHABLE_KEY_PREFIXES = {"pk_live_": "live", "pk_test_": "test"}

# One cheap list call per Stripe resource MemberMatters uses, to find resources
# the key has no access to. Payment methods are left out: listing them needs a
# customer id.
PERMISSION_PROBES = [
    ("Customers", "customers"),
    ("Subscriptions", "subscriptions"),
    ("Invoices", "invoices"),
    ("Products", "products"),
    ("Prices", "prices"),
    ("Payment Intents", "payment_intents"),
    ("Setup Intents", "setup_intents"),
]

SKIPPED = "Skipped because the connection to Stripe failed."


def _row(key, label, status, value="", detail="", items=None):
    return {
        "key": key,
        "label": label,
        "status": status,
        "value": value,
        "detail": detail,
        # Problems listed one per bullet under the row.
        "items": items or [],
    }


def _worst(rows):
    return max((row["status"] for row in rows), key=_SEVERITY.get, default=OK)


def _secret_key():
    """(kind, mode) of STRIPE_SECRET_KEY, or None if it isn't a secret key."""
    key = config.STRIPE_SECRET_KEY or ""
    for prefix, kind_and_mode in SECRET_KEY_PREFIXES.items():
        if key.startswith(prefix):
            return kind_and_mode
    return None


def _publishable_key_mode():
    key = config.STRIPE_PUBLISHABLE_KEY or ""
    for prefix, mode in PUBLISHABLE_KEY_PREFIXES.items():
        if key.startswith(prefix):
            return mode
    return None


def webhook_url():
    return config.SITE_URL.rstrip("/") + reverse("StripeWebhook")


def _webhooks_needed():
    """Webhooks drive membership payments, including subscriptions that are
    still running after membership payments were switched off."""
    return (
        config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS
        or Profile.objects.exclude(stripe_subscription_id__isnull=True)
        .exclude(stripe_subscription_id="")
        .exists()
    )


def _not_needed(rows):
    """Downgrade webhook problems to info when nothing uses webhooks."""
    for row in rows:
        if row["status"] in (WARNING, ERROR):
            row["status"] = INFO
            row["detail"] = (
                f"{row['detail']} Webhooks are only needed for membership "
                "payments, which are off, and no member has a Stripe "
                "subscription."
            ).strip()
    return rows


def _key_problems():
    """(status, problem) for each thing wrong with the two API keys."""
    problems = []

    secret = config.STRIPE_SECRET_KEY or ""
    kind_and_mode = _secret_key()
    if not secret:
        problems.append(
            (ERROR, "Secret key is not set, so MemberMatters can't talk to Stripe.")
        )
    elif kind_and_mode is None:
        what = (
            "is a publishable key"
            if secret.startswith("pk_")
            else "doesn't look like a Stripe secret key"
        )
        problems.append(
            (
                ERROR,
                f"Secret key {what}. Secret keys start with rk_ (restricted) "
                "or sk_.",
            )
        )
    elif kind_and_mode[0] == "Standard":
        problems.append(
            (
                WARNING,
                "Secret key is a standard key, which can do anything in the "
                "Stripe account. Use a restricted key with only the permissions "
                "MemberMatters needs.",
            )
        )

    publishable = config.STRIPE_PUBLISHABLE_KEY or ""
    mode = _publishable_key_mode()
    if not publishable:
        problems.append(
            (
                ERROR,
                "Publishable key is not set, so members can't enter card details.",
            )
        )
    elif mode is None:
        problems.append(
            (
                ERROR,
                "Publishable key doesn't look like a Stripe publishable key. "
                "Publishable keys start with pk_live_ or pk_test_.",
            )
        )
    elif kind_and_mode is not None and kind_and_mode[1] != mode:
        problems.append(
            (
                ERROR,
                f"Publishable key is in {mode} mode, but the secret key is in "
                f"{kind_and_mode[1]} mode. Both must come from the same mode, or "
                "card payments fail.",
            )
        )

    return problems


def _check_keys():
    kind_and_mode = _secret_key()
    value = (
        f"{kind_and_mode[0]} key, {kind_and_mode[1]} mode"
        if kind_and_mode
        else "Not usable"
    )
    problems = _key_problems()
    return _row(
        "keys",
        "API keys",
        _worst([{"status": status} for status, _ in problems]),
        value,
        items=[problem for _, problem in problems],
    )


def _check_webhook_secret():
    label = "Webhook signing secret"
    secret = config.STRIPE_WEBHOOK_SECRET or ""
    if not secret:
        return _row(
            "webhook_secret",
            label,
            ERROR,
            "Not set",
            "STRIPE_WEBHOOK_SECRET is not set, so every webhook from Stripe "
            "is rejected.",
        )
    if not secret.startswith("whsec_"):
        return _row(
            "webhook_secret",
            label,
            WARNING,
            "Set",
            "Stripe signing secrets start with whsec_. Copy it from the "
            "webhook endpoint in the Stripe dashboard.",
        )
    return _row("webhook_secret", label, OK, "Set")


def _check_webhook_url():
    label = "Webhook URL"
    site_url = config.SITE_URL or ""
    if not site_url:
        return _row(
            "webhook_url",
            label,
            ERROR,
            "Unknown",
            "SITE_URL is not set, so the webhook address can't be worked out.",
        )

    url = webhook_url()
    if site_url.rstrip("/") == settings.CONSTANCE_CONFIG["SITE_URL"][0].rstrip("/"):
        return _row(
            "webhook_url",
            label,
            WARNING,
            url,
            "SITE_URL is still the default. Set it to the address this site "
            "is reached on.",
        )
    if urlsplit(url).scheme != "https":
        return _row(
            "webhook_url",
            label,
            WARNING,
            url,
            "Stripe only sends live mode webhooks to https addresses.",
        )
    return _row("webhook_url", label, OK, url)


def get_static_checks():
    """Checks that only read MemberMatters' settings; no call to Stripe."""
    if not config.ENABLE_STRIPE:
        return {
            "checks": [
                _row(
                    "stripe",
                    "Stripe",
                    INFO,
                    "Off",
                    "ENABLE_STRIPE is off, so MemberMatters doesn't use Stripe.",
                )
            ],
            "canTest": False,
        }

    webhook_rows = [_check_webhook_secret(), _check_webhook_url()]
    if not _webhooks_needed():
        _not_needed(webhook_rows)

    return {
        "checks": [
            _check_keys(),
            *webhook_rows,
            _row(
                "api_version",
                "API version",
                INFO,
                f"Enforced {settings.STRIPE_API_VERSION}",
            ),
        ],
        "canTest": _secret_key() is not None,
    }


def _http_client():
    return stripe.RequestsClient(timeout=STRIPE_TIMEOUT_SECONDS)


def _stripe_client():
    return stripe.StripeClient(
        config.STRIPE_SECRET_KEY,
        stripe_version=settings.STRIPE_API_VERSION,
        max_network_retries=0,
        http_client=_http_client(),
    )


def _error_text(error):
    return error.user_message or str(error) or type(error).__name__


def _check_connection(client, mode):
    """The connection row, and whether the rest of the test can go on."""
    label = "Connection"
    try:
        products = client.products.list(params={"limit": 1})
    except stripe.AuthenticationError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Key rejected",
                f"Stripe rejected the secret key: {_error_text(e)}",
            ),
            False,
        )
    except stripe.PermissionError:
        # Authenticated, just not allowed to list products; the permissions
        # row reports that.
        return _row("connection", label, OK, f"Connected, {mode} mode"), True
    except stripe.APIConnectionError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Can't reach Stripe",
                f"Could not connect to Stripe: {_error_text(e)}",
            ),
            False,
        )
    except stripe.StripeError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Error",
                f"Stripe returned an error: {_error_text(e)}",
            ),
            False,
        )

    value = f"Connected, {mode} mode"
    headers = products.last_response.headers if products.last_response else {}
    answered = headers.get("Stripe-Version")
    if answered and answered != settings.STRIPE_API_VERSION:
        return (
            _row(
                "connection",
                label,
                WARNING,
                value,
                f"MemberMatters asked for API version "
                f"{settings.STRIPE_API_VERSION}, but Stripe answered in "
                f"{answered}.",
            ),
            True,
        )
    return _row("connection", label, OK, value), True


def _check_permissions(client):
    label = "Permissions"
    missing, unchecked = [], []
    for name, resource in PERMISSION_PROBES:
        try:
            getattr(client, resource).list(params={"limit": 1})
        except stripe.PermissionError:
            missing.append(f"Missing permission: {name}")
        except stripe.StripeError as e:
            unchecked.append(f"Couldn't check {name}: {_error_text(e)}")

    total = len(PERMISSION_PROBES)
    if missing:
        return _row(
            "permissions",
            label,
            ERROR,
            f"Missing {len(missing)} of {total}",
            items=missing + unchecked,
        )
    if unchecked:
        return _row(
            "permissions",
            label,
            UNKNOWN,
            f"Couldn't check {len(unchecked)} of {total}",
            items=unchecked,
        )
    return _row("permissions", label, OK, f"Read access to all {total} resources")


def _near_miss(url, expected):
    """Why `url` is close to, but not, the webhook address; None if it isn't."""
    got, want = urlsplit(url), urlsplit(expected)
    same_host = got.netloc.lower() == want.netloc.lower()
    if same_host and got.scheme == want.scheme and got.path == want.path.rstrip("/"):
        return (
            f"{url} is missing the trailing slash. This site only takes "
            "webhooks at the address with the slash, so every delivery fails."
        )
    if same_host and got.path == want.path:
        return f"{url} uses {got.scheme} instead of {want.scheme}."
    if got.path == want.path:
        return (
            f"{url} points at {got.netloc}, but SITE_URL is {want.netloc}. "
            "One of them is wrong."
        )
    return None


def _webhook_version_row(endpoint):
    ours = settings.STRIPE_API_VERSION
    # No version on the endpoint means Stripe uses the account's default,
    # which changes whenever the account is upgraded.
    theirs = endpoint.api_version or "the account default"
    return _row(
        "webhook_api_version",
        "Webhook API version",
        OK if theirs == ours else WARNING,
        f"Enforced {ours}, endpoint sends {theirs}",
    )


def _endpoint_problems(endpoint, duplicates):
    """(status, problem) for each thing wrong with this site's endpoint."""
    problems = []

    if duplicates:
        problems.append(
            (
                WARNING,
                f"Found {duplicates + 1} endpoints for this site. Each signs "
                "events with its own secret, so only one can match "
                "STRIPE_WEBHOOK_SECRET. Delete the extras.",
            )
        )

    if endpoint.status != "enabled":
        problems.append(
            (
                ERROR,
                f"The endpoint is {endpoint.status}, so Stripe isn't sending "
                "events to it.",
            )
        )

    enabled = set(endpoint.enabled_events or [])
    missing = [event for event in HANDLED_EVENTS if event not in enabled]
    if missing and "*" not in enabled:
        problems.append((ERROR, f"Missing events: {', '.join(missing)}."))

    if not config.STRIPE_WEBHOOK_SECRET:
        problems.append(
            (
                ERROR,
                "STRIPE_WEBHOOK_SECRET is not set, so every webhook is rejected.",
            )
        )

    return problems


def _check_webhook(client, mode):
    label = "Webhook endpoint"
    try:
        endpoints = list(
            client.webhook_endpoints.list(params={"limit": 100}).auto_paging_iter()
        )
    except stripe.PermissionError:
        return [
            _row(
                "webhook",
                label,
                UNKNOWN,
                "Can't check",
                items=["Missing permission: Webhook Endpoints (read)"],
            )
        ]
    except stripe.StripeError as e:
        return [
            _row(
                "webhook",
                label,
                UNKNOWN,
                "Can't check",
                items=[f"Stripe returned an error: {_error_text(e)}"],
            )
        ]

    expected = webhook_url()
    matches = [endpoint for endpoint in endpoints if endpoint.url == expected]
    if not matches:
        near = [_near_miss(endpoint.url, expected) for endpoint in endpoints]
        near = [reason for reason in near if reason]
        if near:
            items = near
        elif endpoints:
            items = [
                f"Stripe only has endpoints for other addresses: "
                f"{', '.join(endpoint.url for endpoint in endpoints)}."
            ]
        else:
            items = [f"Stripe has no webhook endpoints in {mode} mode."]
        return [_row("webhook", label, ERROR, "No endpoint for this site", items=items)]

    # Prefer an enabled endpoint when there are several.
    matches.sort(key=lambda endpoint: endpoint.status != "enabled")
    endpoint = matches[0]
    problems = _endpoint_problems(endpoint, duplicates=len(matches) - 1)
    status = _worst([{"status": status} for status, _ in problems])
    # Stripe never shows an endpoint's signing secret again, so even a clean
    # result can't confirm STRIPE_WEBHOOK_SECRET matches it.
    value = {
        OK: "Looks correctly set up",
        WARNING: "Set up, with warnings",
        ERROR: "Not set up correctly",
    }[status]
    return [
        _row(
            "webhook",
            label,
            status,
            value,
            items=[problem for _, problem in problems],
        ),
        _webhook_version_row(endpoint),
    ]


def run_connection_test():
    """Read-only calls to Stripe: the key, its permissions and the webhook
    endpoint."""
    if not config.ENABLE_STRIPE:
        return {"checks": [_row("connection", "Connection", INFO, "Stripe is off")]}

    kind_and_mode = _secret_key()
    if kind_and_mode is None:
        return {
            "checks": [
                _row(
                    "connection",
                    "Connection",
                    ERROR,
                    "Not tested",
                    "Set a valid STRIPE_SECRET_KEY first.",
                )
            ]
        }

    mode = kind_and_mode[1]
    client = _stripe_client()
    connection, connected = _check_connection(client, mode)
    if not connected:
        return {
            "checks": [
                connection,
                _row("permissions", "Permissions", UNKNOWN, "Skipped", SKIPPED),
                _row("webhook", "Webhook endpoint", UNKNOWN, "Skipped", SKIPPED),
            ]
        }

    webhook_rows = _check_webhook(client, mode)
    if not _webhooks_needed():
        _not_needed(webhook_rows)

    return {"checks": [connection, _check_permissions(client), *webhook_rows]}
