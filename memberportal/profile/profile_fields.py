"""The member profile fields, and the settings that decide how each is handled.

Every field has a PROFILE_FIELD_* setting saying whether members are asked for
it, whether it is required, and who can change it after signup. Signup, the
member's own profile edit and the admin's edit of a member all read the rules
from here, so the three can't drift apart.

This module is imported by membermatters/constance_config.py while Django's
settings load, so it must not import models or touch the database at import
time. `constance.config` is lazy and safe to import.
"""

import logging
from dataclasses import dataclass
from typing import Callable

import phonenumbers
from constance import config
from django.conf import settings

from profile.phone import to_e164

logger = logging.getLogger("profile")

# Values of the PROFILE_FIELD_* settings. Each field offers a subset.

# Not collected. Data already stored is kept and shown only to admins.
HIDDEN = "hidden"
# The member enters and edits it, and may leave it blank.
OPTIONAL = "optional"
# The member may enter it once while it is empty; after that only admins edit.
OPTIONAL_ADMIN_EDITS = "optional_admin_edits"
# The member must enter it, can edit it, and can't clear it.
REQUIRED = "required"
# The member must enter it once; after that only admins edit.
REQUIRED_ADMIN_EDITS = "required_admin_edits"

# Reserved, not offered by any field yet. "Admin enters" means the member never
# enters the value, only an admin does; a required one holds signup until an
# admin has filled it in.
# TODO: offer these when the access card moves into this list, replacing
# REQUIRE_ACCESS_CARD and MEMBER_CAN_ENTER_ACCESS_CARD. The rules need adjusting
# first: signup has to wait for an admin, as Profile.can_signup() does for the
# card today, and member entry must stay limited to the signup states (noob,
# accountonly), as AssignAccessCard does.
OPTIONAL_ADMIN_ENTERS = "optional_admin_enters"
REQUIRED_ADMIN_ENTERS = "required_admin_enters"

MODE_LABELS = {
    HIDDEN: "Hidden",
    OPTIONAL: "Optional",
    OPTIONAL_ADMIN_EDITS: "Optional, only admins edit",
    REQUIRED: "Required",
    REQUIRED_ADMIN_EDITS: "Required, only admins edit",
}

REQUIRED_MODES = (REQUIRED, REQUIRED_ADMIN_EDITS)
ADMIN_EDITS_MODES = (OPTIONAL_ADMIN_EDITS, REQUIRED_ADMIN_EDITS)

# The email is the login, and the name is used by Stripe and in emails, so
# neither can be hidden or optional.
IDENTITY_MODES = (REQUIRED, REQUIRED_ADMIN_EDITS)
ALL_MODES = (HIDDEN, OPTIONAL, OPTIONAL_ADMIN_EDITS, REQUIRED, REQUIRED_ADMIN_EDITS)


def mode_choices(modes):
    """The (value, label) pairs for a settings dropdown."""
    return tuple((mode, MODE_LABELS[mode]) for mode in modes)


class FieldError(ValueError):
    """A submitted value that can't be stored.

    `key` is the i18n key the frontend shows for it.
    """

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _text(value, max_length, too_long_key):
    """Trim a submitted text value. None counts as blank."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FieldError("error.invalidValue")
    value = value.strip()
    if len(value) > max_length:
        raise FieldError(too_long_key)
    return value


def clean_email(value):
    # Imported here rather than at the top: see the module docstring.
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    value = _text(value, 255, "error.emailTooLong").lower()
    if value:
        try:
            validate_email(value)
        except ValidationError:
            raise FieldError("validation.invalidEmail")
    return value


def clean_first_name(value):
    return _text(value, 30, "error.firstNameTooLong")


def clean_last_name(value):
    return _text(value, 30, "error.lastNameTooLong")


def clean_phone(value):
    """Store the number in E.164, reading a national number as one from
    PROFILE_DEFAULT_PHONE_REGION."""
    # Generous limit on what is typed: spaces and dashes count, and the E.164
    # result is never longer than the column's 16 characters.
    value = _text(value, 32, "validation.invalidPhone")
    if not value:
        return ""
    try:
        return to_e164(value, config.PROFILE_DEFAULT_PHONE_REGION)
    except ValueError:
        raise FieldError("validation.invalidPhone")


def clean_screen_name(value):
    # Blank is stored as NULL so members without one don't collide on the
    # unique constraint.
    return _text(value, 30, "error.screenNameTooLong") or None


def clean_vehicle_plate(value):
    return _text(value, 30, "error.vehiclePlateTooLong")


@dataclass(frozen=True)
class AddressPart:
    key: str
    max_length: int
    # Whether an address must have this part. An address is either left blank
    # or has all its required parts.
    required: bool


# The parts of an address, named as in Stripe's address object so the stored
# value can be compared with Stripe's as it is. Stripe also has "state", which
# isn't used here yet; add it when a space needs it.
ADDRESS_PARTS = (
    AddressPart("line1", 200, required=True),
    AddressPart("line2", 200, required=False),
    AddressPart("postal_code", 20, required=True),
    AddressPart("city", 100, required=True),
    # A two-letter ISO 3166 code, as Stripe expects.
    AddressPart("country", 2, required=True),
)


def clean_address(value):
    """Store an address as a dict of its non-blank parts, or {} for none."""
    if value is None or value == "":
        return {}
    if not isinstance(value, dict):
        raise FieldError("error.invalidValue")

    parts = {part.key: part for part in ADDRESS_PARTS}
    if set(value) - set(parts):
        raise FieldError("error.invalidValue")

    address = {}
    for part in ADDRESS_PARTS:
        if part.key == "country":
            # Checked against the list of countries rather than by length, so
            # "SWE" reads as an unknown country, not as too long.
            text = _text(value.get(part.key), 100, "validation.invalidCountry").upper()
            if text and text not in phonenumbers.SUPPORTED_REGIONS:
                raise FieldError("validation.invalidCountry")
        else:
            text = _text(value.get(part.key), part.max_length, "error.addressTooLong")
        if text:
            address[part.key] = text

    if address and any(
        part.required and part.key not in address for part in ADDRESS_PARTS
    ):
        raise FieldError("error.addressIncomplete")

    return address


@dataclass(frozen=True)
class ProfileField:
    # Its name in the API, in the forms and in features.profileFields.
    key: str
    # The PROFILE_FIELD_* setting. First and last name share one.
    setting: str
    # The values that setting may take.
    modes: tuple
    # Where it is stored: on the User ("user") or the Profile ("profile").
    model: str
    column: str
    # Turns a submitted value into the stored one, or raises FieldError.
    clean: Callable[[object], object]


FIELDS = (
    ProfileField(
        "email", "PROFILE_FIELD_EMAIL", IDENTITY_MODES, "user", "email", clean_email
    ),
    ProfileField(
        "firstName",
        "PROFILE_FIELD_NAME",
        IDENTITY_MODES,
        "profile",
        "first_name",
        clean_first_name,
    ),
    ProfileField(
        "lastName",
        "PROFILE_FIELD_NAME",
        IDENTITY_MODES,
        "profile",
        "last_name",
        clean_last_name,
    ),
    ProfileField(
        "phone", "PROFILE_FIELD_PHONE", ALL_MODES, "profile", "phone", clean_phone
    ),
    ProfileField(
        "screenName",
        "PROFILE_FIELD_SCREEN_NAME",
        ALL_MODES,
        "profile",
        "screen_name",
        clean_screen_name,
    ),
    ProfileField(
        "vehicleRegistrationPlate",
        "PROFILE_FIELD_VEHICLE_PLATE",
        ALL_MODES,
        "profile",
        "vehicle_registration_plate",
        clean_vehicle_plate,
    ),
    ProfileField(
        "address",
        "PROFILE_FIELD_ADDRESS",
        ALL_MODES,
        "profile",
        "address",
        clean_address,
    ),
)

FIELDS_BY_KEY = {field.key: field for field in FIELDS}


def default_mode(field):
    """The setting's default, as declared in CONSTANCE_CONFIG."""
    return settings.CONSTANCE_CONFIG[field.setting][0]


def setting_modes(setting):
    """The values a PROFILE_FIELD_* setting may take, or None for any other
    setting."""
    for field in FIELDS:
        if field.setting == setting:
            return field.modes
    return None


def profile_fields_config():
    """The field settings as the forms read them, for the site config."""
    return {
        "profileFields": {field.key: field_mode(field.key) for field in FIELDS},
        "addressParts": [
            {"key": part.key, "required": part.required, "maxLength": part.max_length}
            for part in ADDRESS_PARTS
        ],
    }


def field_mode(key):
    """The current setting for a field.

    Falls back to the field's default when the stored value isn't one the
    field allows. The settings API used to store any value.
    """
    field = FIELDS_BY_KEY[key]
    mode = getattr(config, field.setting)
    if mode in field.modes:
        return mode

    default = default_mode(field)
    logger.warning(
        "%s is %r, which the %s field doesn't allow; using %r.",
        field.setting,
        mode,
        key,
        default,
    )
    return default
