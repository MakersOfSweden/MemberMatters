"""The move from the old profile switches to the PROFILE_FIELD_* settings.

The suite runs with --no-migrations, so the RunPython functions are called
directly against the current models.
"""

import importlib

import pytest
from constance.codecs import dumps, loads
from constance.models import Constance
from django.apps import apps

migration = importlib.import_module(
    "api_general.migrations.0010_profile_field_settings"
)

pytestmark = pytest.mark.django_db

OLD_KEYS = (
    "MEMBER_CAN_EDIT_BASIC_DETAILS",
    "MEMBER_CAN_EDIT_EMAIL",
    "REQUIRE_SCREEN_NAME",
    "COLLECT_VEHICLE_REGISTRATION_PLATE",
)


def store(**values):
    for key, value in values.items():
        Constance.objects.update_or_create(key=key, defaults={"value": dumps(value)})


def stored():
    return {row.key: loads(row.value) for row in Constance.objects.all()}


def effective(defaults):
    """What the portal reads: a setting that isn't stored reads as its default."""
    return {**defaults, **{k: v for k, v in stored().items() if k in defaults}}


def migrate():
    migration.to_profile_field_settings(apps, None)
    return effective(migration.NEW_DEFAULTS)


def test_an_install_that_never_changed_the_switches_gets_the_defaults():
    assert migrate() == {
        "PROFILE_FIELD_EMAIL": "required",
        "PROFILE_FIELD_NAME": "required",
        "PROFILE_FIELD_PHONE": "required",
        "PROFILE_FIELD_SCREEN_NAME": "required",
        "PROFILE_FIELD_VEHICLE_PLATE": "hidden",
    }


def test_settings_left_at_their_defaults_are_not_stored():
    # So a fresh install gets no rows, as with any other setting.
    store(MEMBER_CAN_EDIT_BASIC_DETAILS=True, COLLECT_VEHICLE_REGISTRATION_PLATE=True)

    migrate()

    assert stored() == {"PROFILE_FIELD_VEHICLE_PLATE": "optional"}


def test_the_old_switches_are_deleted():
    store(
        MEMBER_CAN_EDIT_BASIC_DETAILS=True,
        MEMBER_CAN_EDIT_EMAIL=True,
        REQUIRE_SCREEN_NAME=True,
        COLLECT_VEHICLE_REGISTRATION_PLATE=True,
    )

    migrate()

    assert not set(OLD_KEYS) & set(stored())


def test_other_settings_are_left_alone():
    store(SITE_NAME="Makerspace")

    migrate()

    assert stored()["SITE_NAME"] == "Makerspace"


@pytest.mark.parametrize(
    "basic, email, expected",
    [
        (True, True, ("required", "required", "required")),
        # Only the email was locked.
        (True, False, ("required_admin_edits", "required", "required")),
        # The basic-details switch locked email too, whatever its own switch.
        (False, True, ("required_admin_edits",) * 3),
        (False, False, ("required_admin_edits",) * 3),
    ],
)
def test_locked_details_become_required_with_only_admins_editing(
    basic, email, expected
):
    store(MEMBER_CAN_EDIT_BASIC_DETAILS=basic, MEMBER_CAN_EDIT_EMAIL=email)

    settings = migrate()

    assert (
        settings["PROFILE_FIELD_EMAIL"],
        settings["PROFILE_FIELD_NAME"],
        settings["PROFILE_FIELD_PHONE"],
    ) == expected


@pytest.mark.parametrize(
    "required, expected", [(True, "required"), (False, "optional")]
)
def test_the_screen_name_keeps_whether_it_was_required(required, expected):
    store(REQUIRE_SCREEN_NAME=required)

    assert migrate()["PROFILE_FIELD_SCREEN_NAME"] == expected


@pytest.mark.parametrize("collected, expected", [(True, "optional"), (False, "hidden")])
def test_the_vehicle_plate_keeps_whether_it_was_collected(collected, expected):
    store(COLLECT_VEHICLE_REGISTRATION_PLATE=collected)

    assert migrate()["PROFILE_FIELD_VEHICLE_PLATE"] == expected


def test_a_switch_stored_as_something_other_than_true_or_false_counts_as_its_default():
    store(MEMBER_CAN_EDIT_BASIC_DETAILS="no", REQUIRE_SCREEN_NAME=None)

    settings = migrate()

    assert settings["PROFILE_FIELD_NAME"] == "required"
    assert settings["PROFILE_FIELD_SCREEN_NAME"] == "required"


class TestReverse:
    def reverse(self):
        migration.to_old_switches(apps, None)
        return effective(migration.OLD_DEFAULTS)

    @pytest.mark.parametrize(
        "old",
        [
            dict(
                MEMBER_CAN_EDIT_BASIC_DETAILS=True,
                MEMBER_CAN_EDIT_EMAIL=True,
                REQUIRE_SCREEN_NAME=True,
                COLLECT_VEHICLE_REGISTRATION_PLATE=False,
            ),
            dict(
                MEMBER_CAN_EDIT_BASIC_DETAILS=True,
                MEMBER_CAN_EDIT_EMAIL=False,
                REQUIRE_SCREEN_NAME=False,
                COLLECT_VEHICLE_REGISTRATION_PLATE=True,
            ),
        ],
    )
    def test_going_back_restores_the_old_switches(self, old):
        store(**old)
        migrate()

        assert self.reverse() == old

    def test_going_back_rounds_values_the_switches_cannot_express(self):
        store(
            PROFILE_FIELD_NAME="required",
            PROFILE_FIELD_EMAIL="required",
            PROFILE_FIELD_SCREEN_NAME="optional_admin_edits",
            PROFILE_FIELD_VEHICLE_PLATE="required",
        )

        settings = self.reverse()

        assert settings["REQUIRE_SCREEN_NAME"] is False
        assert settings["COLLECT_VEHICLE_REGISTRATION_PLATE"] is True
        assert not any(key.startswith("PROFILE_FIELD_") for key in stored())
