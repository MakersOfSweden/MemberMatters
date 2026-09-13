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
# Kept as tight as the round-trip allows, because this blocks the one thread the
# whole process shares: under ASGI, Django 3.2 runs every sync view and Channels
# runs every sync consumer handler on asgiref's single thread-sensitive executor,
# so a stalled verify also delays unrelated requests and door swipes.
VERIFY_TIMEOUT = (1, 2)


_warned_missing_keys = None


def captcha_enabled() -> bool:
    global _warned_missing_keys

    if not config.ENABLE_CAPTCHA:
        _warned_missing_keys = None
        return False

    missing = [
        name
        for name in ("CAPTCHA_SITE_KEY", "CAPTCHA_SECRET_KEY")
        if not getattr(config, name)
    ]
    if not missing:
        _warned_missing_keys = None
        return True

    # Latched on which keys are missing, so this stays out of the per-request
    # log but still re-fires if the config shifts to a different broken state.
    if _warned_missing_keys != set(missing):
        logger.warning(
            f"ENABLE_CAPTCHA is on but {' and '.join(missing)} not set — CAPTCHA "
            f"is inactive and signup, login and password reset are ungated."
        )
        _warned_missing_keys = set(missing)
    return False


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
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def verify_captcha(request, action=None) -> bool:
    # No-op pass when unconfigured so fresh installs / CI work with zero config.
    if not captcha_enabled():
        return True

    # A JSON array or bare-string body parses to a list/str, which has no .get.
    data = request.data
    token = data.get("captchaToken") if isinstance(data, dict) else None
    if not token or not isinstance(token, str):
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
        if not isinstance(result, dict):
            raise ValueError("siteverify did not answer with a JSON object")
    except (requests.RequestException, ValueError):
        # Error, not warning: reaching here means signup, login and password
        # reset are all failing closed, so it should stand out in the log.
        logger.error("CAPTCHA siteverify request failed", exc_info=True)
        return False

    if not result.get("success"):
        logger.info("CAPTCHA verification rejected: %s", result.get("error-codes"))
        return False

    # Defence in depth (the site key is public): bind the token to the form that
    # minted it, and — only when configured — to one of our own hostnames.
    if action is not None and result.get("action") != action:
        logger.warning(
            "CAPTCHA token was solved for action %r, expected %r",
            result.get("action"),
            action,
        )
        return False

    allowed = _allowed_hostnames()
    hostname = str(result.get("hostname") or "").lower()
    if allowed and hostname not in allowed:
        logger.warning(
            "CAPTCHA token was solved on %r, not in CAPTCHA_ALLOWED_HOSTNAMES",
            hostname,
        )
        return False

    return True
