"""E.164 phone-number normalisation, shared by signup, profile
self-edit and the admin member editor."""

import phonenumbers


def to_e164(raw, default_region=None):
    """Return ``raw`` as an E.164 string (e.g. ``"+46701234567"``).

    ``raw`` may be international (``"+46701234567"``) or national
    (``"0701234567"``); a national number is interpreted using
    ``default_region`` — an ISO-3166 alpha-2 code such as ``"SE"``.

    Raises ``ValueError`` if ``raw`` is empty or not a valid number.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("phone number is empty")
    try:
        parsed = phonenumbers.parse(raw, default_region or None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"could not parse phone number: {exc}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("not a valid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
