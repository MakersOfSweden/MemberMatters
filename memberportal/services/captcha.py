import ipaddress
import logging

import requests
from constance import config
from rest_framework.settings import api_settings
from rest_framework.throttling import BaseThrottle

logger = logging.getLogger("captcha")

# Provider-specific details (Cloudflare Turnstile) live only in this file.
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# (connect, read) seconds. NOT settings.REQUEST_TIMEOUT (0.05s) — a siteverify
# round-trip can't finish in 50ms, so reusing it would fail closed every time.
# Kept tight because this call blocks a request thread, and under ASGI Django
# 3.2 runs every sync view on one shared thread-sensitive executor: a slow
# verify delays unrelated requests, not just this one.
VERIFY_TIMEOUT = (2, 3)


def captcha_enabled() -> bool:
    return bool(
        config.ENABLE_CAPTCHA and config.CAPTCHA_SITE_KEY and config.CAPTCHA_SECRET_KEY
    )


def _client_ip(request):
    # remoteip is optional, and must be the client's own address. Only
    # MM_NUM_PROXIES tells us how many X-Forwarded-For hops are ours to trust:
    # unset, DRF hands back the whole chain ("1.2.3.4, 5.6.7.8"), whose hops
    # are either a proxy of ours or attacker-supplied. Send nothing rather
    # than a wrong address.
    if api_settings.NUM_PROXIES is None:
        return None
    ident = (BaseThrottle().get_ident(request) or "").strip()
    try:
        parsed = ipaddress.ip_address(ident)
    except ValueError:
        return None
    # A private or loopback address means the hop count is off — we're looking
    # at our own proxy, which tells the provider nothing.
    return ident if parsed.is_global else None


def _allowed_hostnames() -> set:
    # Empty default skips the check, so native WebView origins keep working.
    raw = (config.CAPTCHA_ALLOWED_HOSTNAMES or "").strip()
    return {h.strip() for h in raw.split(",") if h.strip()}


def verify_captcha(request, action=None) -> bool:
    # No-op pass when unconfigured so fresh installs / CI work with zero config.
    if not captcha_enabled():
        return True

    token = request.data.get("captchaToken")
    if not token:
        return False

    payload = {"secret": config.CAPTCHA_SECRET_KEY, "response": token}
    client_ip = _client_ip(request)
    if client_ip:
        payload["remoteip"] = client_ip

    try:
        resp = requests.post(SITEVERIFY_URL, data=payload, timeout=VERIFY_TIMEOUT)
        # requests doesn't raise on 4xx/5xx and an error page is HTML, so
        # .json() can raise ValueError — catch it too and fail closed.
        result = resp.json()
    except (requests.RequestException, ValueError):
        # Log so a Cloudflare outage / bad key (which blocks all gated flows)
        # is diagnosable.
        logger.warning("CAPTCHA siteverify request failed", exc_info=True)
        return False

    if not result.get("success"):
        logger.info("CAPTCHA verification rejected: %s", result.get("error-codes"))
        return False

    # Defence in depth (the site key is public): bind the token to the form that
    # minted it, and — only when configured — to one of our own hostnames.
    if action is not None and result.get("action") != action:
        return False

    allowed = _allowed_hostnames()
    if allowed and result.get("hostname") not in allowed:
        return False

    return True
