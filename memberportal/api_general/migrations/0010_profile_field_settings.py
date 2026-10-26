from constance.codecs import dumps, loads
from django.db import migrations

# The old switches and their defaults, frozen here: an old setting that was
# never stored behaved as its default.
OLD_DEFAULTS = {
    "MEMBER_CAN_EDIT_BASIC_DETAILS": True,
    "MEMBER_CAN_EDIT_EMAIL": True,
    "REQUIRE_SCREEN_NAME": True,
    "COLLECT_VEHICLE_REGISTRATION_PLATE": False,
}

# The new settings and their defaults, frozen here for the same reason.
NEW_DEFAULTS = {
    "PROFILE_FIELD_EMAIL": "required",
    "PROFILE_FIELD_NAME": "required",
    "PROFILE_FIELD_PHONE": "required",
    "PROFILE_FIELD_SCREEN_NAME": "required",
    "PROFILE_FIELD_VEHICLE_PLATE": "hidden",
}


def _read(Constance, key, default):
    row = Constance.objects.filter(key=key).first()
    if row is None or row.value is None:
        return default
    try:
        return loads(row.value)
    except (TypeError, ValueError):
        return default


def _write(Constance, values, defaults):
    """Stores the values that differ from their defaults.

    A setting that isn't stored reads as its default, so a fresh install, or
    one that never changed the switches, gets no rows at all.
    """
    for key, value in values.items():
        if value == defaults[key]:
            Constance.objects.filter(key=key).delete()
        else:
            Constance.objects.update_or_create(
                key=key, defaults={"value": dumps(value)}
            )


def to_profile_field_settings(apps, schema_editor):
    """Sets the PROFILE_FIELD_* settings from the switches they replace.

    MEMBER_CAN_EDIT_BASIC_DETAILS covered name, phone and email, and
    MEMBER_CAN_EDIT_EMAIL only took effect while it was on. A field members
    couldn't edit becomes "required, only admins edit". The phone was always
    required at signup, so it stays required. The old settings are deleted.
    """
    Constance = apps.get_model("constance", "Constance")

    old = {}
    for key, default in OLD_DEFAULTS.items():
        value = _read(Constance, key, default)
        old[key] = value if isinstance(value, bool) else default

    can_edit_basic = old["MEMBER_CAN_EDIT_BASIC_DETAILS"]
    can_edit_email = can_edit_basic and old["MEMBER_CAN_EDIT_EMAIL"]
    basic = "required" if can_edit_basic else "required_admin_edits"

    _write(
        Constance,
        {
            "PROFILE_FIELD_EMAIL": (
                "required" if can_edit_email else "required_admin_edits"
            ),
            "PROFILE_FIELD_NAME": basic,
            "PROFILE_FIELD_PHONE": basic,
            "PROFILE_FIELD_SCREEN_NAME": (
                "required" if old["REQUIRE_SCREEN_NAME"] else "optional"
            ),
            "PROFILE_FIELD_VEHICLE_PLATE": (
                "optional" if old["COLLECT_VEHICLE_REGISTRATION_PLATE"] else "hidden"
            ),
        },
        NEW_DEFAULTS,
    )
    Constance.objects.filter(key__in=OLD_DEFAULTS).delete()


def to_old_switches(apps, schema_editor):
    """Sets the old switches back from the PROFILE_FIELD_* settings.

    Values the switches can't express are rounded towards what members could
    do before: a field that isn't "required" for members to edit counts as
    locked, and any screen name setting but "required" as optional.
    """
    Constance = apps.get_model("constance", "Constance")

    new = {key: _read(Constance, key, default) for key, default in NEW_DEFAULTS.items()}

    _write(
        Constance,
        {
            "MEMBER_CAN_EDIT_BASIC_DETAILS": new["PROFILE_FIELD_NAME"] == "required",
            "MEMBER_CAN_EDIT_EMAIL": new["PROFILE_FIELD_EMAIL"] == "required",
            "REQUIRE_SCREEN_NAME": new["PROFILE_FIELD_SCREEN_NAME"] == "required",
            "COLLECT_VEHICLE_REGISTRATION_PLATE": (
                new["PROFILE_FIELD_VEHICLE_PLATE"] != "hidden"
            ),
        },
        OLD_DEFAULTS,
    )
    Constance.objects.filter(key__in=NEW_DEFAULTS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("api_general", "0009_char32_uuid_fields"),
        # The values are read and written in constance 4's JSON encoding, which
        # its 0003 migration converts the stored settings to.
        ("constance", "0003_drop_pickle"),
    ]

    operations = [
        migrations.RunPython(to_profile_field_settings, to_old_switches),
    ]
