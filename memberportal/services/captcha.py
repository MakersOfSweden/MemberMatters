import ipaddress
import logging

import requests
from constance import config
from rest_framework.throttling import BaseThrottle

logger = logging.getLogger("captcha")

# Provider-specific details (Cloudflare Turnstile) live only in this file.
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# NOT settings.REQUEST_TIMEOUT (0.05s) — a siteverify round-trip can't finish in
# 50ms, so reusing it would fail closed on every verification.
VERIFY_TIMEOUT = 5  # seconds


def captcha_enabled() -> bool:
    return bool(
        config.ENABLE_CAPTCHA and config.CAPTCHA_SITE_KEY and config.CAPTCHA_SECRET_KEY
    )


def _client_ip(request):
    # remoteip must be a single IP, but DRF's get_ident returns the whole XFF
    # chain ("1.2.3.4, 5.6.7.8") under the default NUM_PROXIES. Isolate the last
    # hop; omit remoteip (it's optional) if it doesn't parse as an IP.
    ident = (BaseThrottle().get_ident(request) or "").strip()
    candidate = ident.rsplit(",", 1)[-1].strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


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
