"""The profile field list: its cleanup functions and the PROFILE_FIELD_* settings.

Signup, the member's own edit and the admin edit all read these, so a value
cleaned differently here would be stored differently everywhere.
"""

import pytest
from constance.test import override_config
from django.conf import settings

from profile import profile_fields
from profile.profile_fields import (
    FIELDS,
    FieldError,
    clean_address,
    clean_email,
    clean_first_name,
    clean_phone,
    clean_screen_name,
    clean_vehicle_plate,
    field_mode,
    setting_modes,
)

pytestmark = pytest.mark.django_db


def error_key(clean, value):
    with pytest.raises(FieldError) as excinfo:
        clean(value)
    return excinfo.value.key


class TestCleanEmail:
    def test_it_is_trimmed_and_lowercased(self):
        assert clean_email("  Member@Example.COM ") == "member@example.com"

    def test_blank_and_none_are_empty(self):
        assert clean_email("") == ""
        assert clean_email(None) == ""

    def test_an_invalid_address_is_refused(self):
        assert error_key(clean_email, "not-an-email") == "validation.invalidEmail"

    def test_an_address_over_255_characters_is_refused(self):
        address = "a" * 250 + "@example.com"

        assert error_key(clean_email, address) == "error.emailTooLong"


class TestCleanText:
    def test_names_are_trimmed(self):
        assert clean_first_name("  Ada ") == "Ada"

    def test_a_name_over_30_characters_is_refused(self):
        assert error_key(clean_first_name, "a" * 31) == "error.firstNameTooLong"

    def test_a_blank_screen_name_is_stored_as_null(self):
        # NULL, so members without one don't collide on the unique constraint.
        assert clean_screen_name("   ") is None
        assert clean_screen_name(None) is None

    def test_a_screen_name_is_trimmed(self):
        assert clean_screen_name(" ada ") == "ada"

    def test_a_vehicle_plate_is_trimmed(self):
        assert clean_vehicle_plate(" ABC123 ") == "ABC123"

    @pytest.mark.parametrize("value", [42, ["Ada"], {"first": "Ada"}, True])
    def test_anything_but_text_is_refused(self, value):
        assert error_key(clean_first_name, value) == "error.invalidValue"


class TestCleanPhone:
    @override_config(PROFILE_DEFAULT_PHONE_REGION="SE")
    def test_a_national_number_is_read_in_the_default_region(self):
        assert clean_phone("070-123 45 67") == "+46701234567"

    @override_config(PROFILE_DEFAULT_PHONE_REGION="SE")
    def test_an_international_number_keeps_its_own_country(self):
        assert clean_phone("+61 417 123 456") == "+61417123456"

    def test_blank_is_empty(self):
        assert clean_phone("  ") == ""
        assert clean_phone(None) == ""

    @pytest.mark.parametrize("value", ["12", "not a number", "1" * 40])
    def test_an_invalid_number_is_refused(self, value):
        assert error_key(clean_phone, value) == "validation.invalidPhone"


class TestSettings:
    @pytest.mark.parametrize("field", FIELDS, ids=lambda field: field.key)
    def test_every_field_has_a_setting_with_a_default_it_allows(self, field):
        default, _help, field_type = settings.CONSTANCE_CONFIG[field.setting]

        assert default in field.modes
        # The dropdown in the settings page offers exactly the field's values.
        choices = settings.CONSTANCE_ADDITIONAL_FIELDS[field_type][1]["choices"]
        assert tuple(value for value, _label in choices) == field.modes

    def test_the_reserved_admin_enters_values_are_not_offered_yet(self):
        offered = {mode for field in FIELDS for mode in field.modes}

        assert profile_fields.OPTIONAL_ADMIN_ENTERS not in offered
        assert profile_fields.REQUIRED_ADMIN_ENTERS not in offered

    def test_first_and_last_name_share_one_setting(self):
        fields = {field.key: field for field in FIELDS}

        assert fields["firstName"].setting == fields["lastName"].setting

    def test_setting_modes_is_none_for_other_settings(self):
        assert setting_modes("SITE_NAME") is None
        assert setting_modes("PROFILE_FIELD_EMAIL") == profile_fields.IDENTITY_MODES


class TestFieldMode:
    @override_config(PROFILE_FIELD_PHONE="optional_admin_edits")
    def test_it_is_the_setting(self):
        assert field_mode("phone") == "optional_admin_edits"

    @override_config(PROFILE_FIELD_SCREEN_NAME="nonsense")
    def test_a_value_the_field_does_not_allow_falls_back_to_the_default(self, caplog):
        assert field_mode("screenName") == "required"

        warnings = [r.getMessage() for r in caplog.records if r.name == "profile"]
        assert any("PROFILE_FIELD_SCREEN_NAME" in w for w in warnings)

    @override_config(PROFILE_FIELD_EMAIL="hidden")
    def test_a_value_only_other_fields_allow_falls_back_too(self):
        # Hidden is a real value, but the email can't be hidden.
        assert field_mode("email") == "required"


class TestCleanAddress:
    FULL = {
        "line1": "Storgatan 1",
        "line2": "c/o Andersson",
        "postal_code": "123 45",
        "city": "Stockholm",
        "country": "SE",
    }

    def test_a_full_address_is_kept(self):
        assert clean_address(dict(self.FULL)) == self.FULL

    def test_parts_are_trimmed_and_blank_ones_dropped(self):
        address = {**self.FULL, "line1": "  Storgatan 1 ", "line2": "  "}

        cleaned = clean_address(address)

        assert cleaned["line1"] == "Storgatan 1"
        assert "line2" not in cleaned

    def test_the_country_is_uppercased(self):
        assert clean_address({**self.FULL, "country": "se"})["country"] == "SE"

    @pytest.mark.parametrize("value", [None, "", {}, {"line1": "  "}])
    def test_nothing_filled_in_is_no_address(self, value):
        assert clean_address(value) == {}

    @pytest.mark.parametrize("missing", ["line1", "postal_code", "city", "country"])
    def test_an_address_needs_all_its_required_parts(self, missing):
        address = {k: v for k, v in self.FULL.items() if k != missing}

        assert error_key(clean_address, address) == "error.addressIncomplete"

    def test_the_second_line_is_never_required(self):
        address = {k: v for k, v in self.FULL.items() if k != "line2"}

        assert clean_address(address) == address

    @pytest.mark.parametrize("country", ["XX", "SWE", "Sweden"])
    def test_an_unknown_country_is_refused(self, country):
        address = {**self.FULL, "country": country}

        assert error_key(clean_address, address) == "validation.invalidCountry"

    def test_an_unknown_part_is_refused(self):
        # Stripe has a state, but this portal doesn't collect one yet.
        address = {**self.FULL, "state": "Stockholms län"}

        assert error_key(clean_address, address) == "error.invalidValue"

    @pytest.mark.parametrize("value", ["Storgatan 1", ["Storgatan 1"], 42])
    def test_anything_but_an_object_is_refused(self, value):
        assert error_key(clean_address, value) == "error.invalidValue"

    def test_a_part_that_is_too_long_is_refused(self):
        address = {**self.FULL, "city": "a" * 101}

        assert error_key(clean_address, address) == "error.addressTooLong"

    def test_a_part_that_is_not_text_is_refused(self):
        address = {**self.FULL, "postal_code": 12345}

        assert error_key(clean_address, address) == "error.invalidValue"


def test_admins_see_the_stored_address(admin_client):
    from django.urls import reverse

    from tests.factories import ProfileFactory

    profile = ProfileFactory(address=dict(TestCleanAddress.FULL))

    response = admin_client.get(reverse("GetMembers"))

    members = {member["id"]: member for member in response.json()}
    assert members[profile.user.id]["address"] == TestCleanAddress.FULL
