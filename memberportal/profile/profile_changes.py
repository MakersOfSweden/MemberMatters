"""Applies submitted profile fields, following each field's PROFILE_FIELD_* setting.

Signup, the member's own profile edit and the admin's edit of a member all go
through here. What each may do with a field depends on its setting:

| Setting               | Signup             | Member edit                       | Admin edit                 |
|-----------------------|--------------------|-----------------------------------|----------------------------|
| hidden                | ignored            | ignored                           | ignored                    |
| optional              | accepted           | accepted                          | accepted                   |
| optional_admin_edits  | accepted           | accepted while the stored value   | accepted                   |
|                       |                    | is empty, then locked             |                            |
| required              | must be filled in  | accepted, can't be cleared        | accepted, can't be cleared |
| required_admin_edits  | must be filled in  | must be filled in while empty,    | accepted, can't be cleared |
|                       |                    | then locked                       |                            |

"Required" is checked on the result: the stored values with the accepted
changes applied. A blank required field on an old record therefore has to be
filled in before any other change to the profile saves.
"""

from django.db import IntegrityError, transaction

from profile.profile_fields import (
    ADMIN_EDITS_MODES,
    FIELDS,
    FIELDS_BY_KEY,
    HIDDEN,
    REQUIRED_MODES,
    FieldError,
    field_mode,
)

SIGNUP = "signup"
MEMBER = "member"
ADMIN = "admin"


class ProfileFieldErrors(Exception):
    """Submitted values that can't be stored, as {field key: [i18n key]}.

    The same shape DRF gives serializer errors, which the signup form already
    shows.
    """

    def __init__(self, errors):
        super().__init__(errors)
        self.errors = errors


class ProfileConflict(Exception):
    """The email or screen name is already used by another member.

    `message` is the i18n key for it.
    """

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def is_blank(value):
    return value is None or value == "" or value == {}


def columns(values, model):
    """{column: value} for the fields in `values` stored on `model`, "user" or
    "profile"."""
    return {
        FIELDS_BY_KEY[key].column: value
        for key, value in values.items()
        if FIELDS_BY_KEY[key].model == model
    }


def stored_values(profile):
    """{field key: stored value} for every field, hidden ones included."""
    return {
        field.key: getattr(
            profile.user if field.model == "user" else profile, field.column
        )
        for field in FIELDS
    }


def _same(field, value, stored):
    """Whether a cleaned value is what is already stored.

    The stored value is cleaned too, so one saved before the current rules
    (a mixed-case email, a phone number not yet in E.164) still counts as the
    same when the form sends it back.
    """
    if value == stored:
        return True
    try:
        return field.clean(stored) == value
    except FieldError:
        return False


def check_profile_changes(stored, data, actor):
    """Works out which submitted values to store.

    `stored` is {field key: stored value} for the member, or {} at signup.
    `data` is the submitted payload; fields it leaves out keep their stored
    value. Returns {field key: cleaned value} for the values that change, or
    at signup for every submitted field that isn't hidden. Raises
    ProfileFieldErrors listing every field that can't be stored.
    """
    errors = {}
    changes = {}

    for field in FIELDS:
        mode = field_mode(field.key)
        if mode == HIDDEN:
            continue

        current = stored.get(field.key)
        if field.key in data:
            try:
                value = field.clean(data[field.key])
            except FieldError as error:
                errors[field.key] = [error.key]
                continue

            if actor == SIGNUP:
                changes[field.key] = value
            elif not _same(field, value, current):
                locked = (
                    actor == MEMBER
                    and mode in ADMIN_EDITS_MODES
                    and not is_blank(current)
                )
                if locked:
                    errors[field.key] = ["error.fieldLocked"]
                    continue
                changes[field.key] = value

        if mode in REQUIRED_MODES and is_blank(changes.get(field.key, current)):
            errors[field.key] = ["error.fieldRequired"]

    if errors:
        raise ProfileFieldErrors(errors)
    return changes


def check_unique(changes, user=None):
    """Raises ProfileConflict if a changed email or screen name is taken.

    `user` is the member being changed, left out of the check; None at signup.
    Both are compared ignoring case, as their unique constraints are.
    """
    # Imported here so this module can be imported before the apps are ready.
    from profile.models import Profile, User

    email = changes.get("email")
    if email:
        others = User.objects.filter(email__iexact=email)
        if user is not None:
            others = others.exclude(pk=user.pk)
        if others.exists():
            raise ProfileConflict("error.accountAlreadyExists")

    screen_name = changes.get("screenName")
    if screen_name:
        others = Profile.objects.filter(screen_name__iexact=screen_name)
        if user is not None:
            others = others.exclude(user=user)
        if others.exists():
            raise ProfileConflict("error.screenNameAlreadyExists")


def save_profile_changes(profile, data, actor):
    """Checks a member's or admin's edit of a profile and stores it.

    The profile and user rows are locked and re-read first, so two requests
    can't both use a member's one chance to fill in an "only admins edit"
    field, and only the columns that change are written, so concurrent writes
    to the rest of the row (webhooks, the admin, access events) are kept.

    Returns {field key: (old value, new value)} for what changed, and updates
    `profile` (and its user) to match. Raises ProfileFieldErrors or
    ProfileConflict.
    """
    from profile.models import Profile

    try:
        with transaction.atomic():
            locked = (
                Profile.objects.select_for_update()
                .select_related("user")
                .get(pk=profile.pk)
            )
            stored = stored_values(locked)
            changes = check_profile_changes(stored, data, actor)
            check_unique(changes, user=locked.user)

            user_columns, profile_columns = [], []
            for key, value in changes.items():
                field = FIELDS_BY_KEY[key]
                if field.model == "user":
                    setattr(locked.user, field.column, value)
                    user_columns.append(field.column)
                else:
                    setattr(locked, field.column, value)
                    profile_columns.append(field.column)

            if user_columns:
                locked.user.save(update_fields=user_columns)
            if profile_columns:
                locked.save(update_fields=profile_columns)
    except IntegrityError:
        # A concurrent signup or edit took the email or screen name between
        # the check above and the write.
        check_unique(changes, user=profile.user)
        raise ProfileConflict(
            "error.accountAlreadyExists"
            if "email" in changes
            else "error.screenNameAlreadyExists"
        )

    for key, value in changes.items():
        field = FIELDS_BY_KEY[key]
        setattr(profile.user if field.model == "user" else profile, field.column, value)

    return {key: (stored[key], value) for key, value in changes.items()}
