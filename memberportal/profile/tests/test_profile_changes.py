"""Applying submitted profile fields according to their PROFILE_FIELD_* settings.

The phone field offers every value, so it carries most of the rules. Each
test sets its setting with override_config.
"""

import pytest
from constance.test import override_config
from django.contrib.auth import get_user_model

from profile.models import Profile
from profile.profile_changes import (
    ADMIN,
    MEMBER,
    SIGNUP,
    ProfileConflict,
    ProfileFieldErrors,
    check_profile_changes,
    save_profile_changes,
    stored_values,
)
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PHONE = "+61417000001"
OTHER_PHONE = "+61417000002"


def errors_of(values, data, actor):
    with pytest.raises(ProfileFieldErrors) as excinfo:
        check_profile_changes(values, data, actor)
    return excinfo.value.errors


def phone(mode):
    return override_config(PROFILE_FIELD_PHONE=mode)


def stored(**overrides):
    """A member's stored values that pass with the default settings."""
    return {
        "email": "member@example.com",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "phone": PHONE,
        "screenName": "ada",
        "vehicleRegistrationPlate": "",
        "address": {},
        **overrides,
    }


def full_signup(**overrides):
    """A signup payload that passes with the default settings."""
    return {
        "email": "new@example.com",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "phone": PHONE,
        "screenName": "ada",
        **overrides,
    }


class TestHidden:
    @phone("hidden")
    @pytest.mark.parametrize("actor", [SIGNUP, MEMBER, ADMIN])
    def test_a_hidden_field_is_ignored_whatever_is_sent(self, actor):
        changes = check_profile_changes(stored(), {"phone": OTHER_PHONE}, actor)

        assert "phone" not in changes

    @phone("hidden")
    def test_a_hidden_field_is_never_required(self):
        changes = check_profile_changes({}, full_signup(phone=""), SIGNUP)

        assert "phone" not in changes

    @phone("hidden")
    def test_a_hidden_field_is_not_even_cleaned(self):
        # Nothing is stored, so an invalid value doesn't matter.
        check_profile_changes({}, full_signup(phone="not a number"), SIGNUP)


class TestOptional:
    @phone("optional")
    @pytest.mark.parametrize("actor", [SIGNUP, MEMBER, ADMIN])
    def test_it_is_accepted_and_may_be_cleared(self, actor):
        assert check_profile_changes(stored(), {"phone": ""}, actor) == {"phone": ""}

    @phone("optional")
    def test_it_may_be_left_blank_at_signup(self):
        changes = check_profile_changes({}, full_signup(phone=""), SIGNUP)

        assert changes["phone"] == ""


class TestOptionalAdminEdits:
    @phone("optional_admin_edits")
    def test_a_member_may_fill_it_in_while_it_is_empty(self):
        assert check_profile_changes(stored(phone=""), {"phone": PHONE}, MEMBER) == {
            "phone": PHONE
        }

    @phone("optional_admin_edits")
    @pytest.mark.parametrize("new", [OTHER_PHONE, ""])
    def test_a_member_cannot_change_or_clear_it_once_it_has_a_value(self, new):
        errors = errors_of(stored(), {"phone": new}, MEMBER)

        assert errors == {"phone": ["error.fieldLocked"]}

    @phone("optional_admin_edits")
    def test_the_member_form_sending_the_stored_value_back_is_fine(self):
        assert check_profile_changes(stored(), {"phone": PHONE}, MEMBER) == {}

    @phone("optional_admin_edits")
    def test_an_admin_can_change_and_clear_it(self):
        assert check_profile_changes(stored(), {"phone": ""}, ADMIN) == {"phone": ""}

    @phone("optional_admin_edits")
    def test_it_may_be_left_blank_at_signup(self):
        assert check_profile_changes({}, full_signup(phone=""), SIGNUP)["phone"] == ""


class TestRequired:
    @phone("required")
    @pytest.mark.parametrize("actor", [MEMBER, ADMIN])
    def test_it_can_be_changed(self, actor):
        assert check_profile_changes(stored(), {"phone": OTHER_PHONE}, actor) == {
            "phone": OTHER_PHONE
        }

    @phone("required")
    @pytest.mark.parametrize("actor", [MEMBER, ADMIN])
    def test_it_cannot_be_cleared(self, actor):
        errors = errors_of(stored(), {"phone": ""}, actor)

        assert errors == {"phone": ["error.fieldRequired"]}

    @phone("required")
    def test_it_must_be_filled_in_at_signup(self):
        errors = errors_of({}, full_signup(phone=""), SIGNUP)

        assert errors == {"phone": ["error.fieldRequired"]}

    @phone("required")
    @pytest.mark.parametrize("actor", [MEMBER, ADMIN])
    def test_a_blank_stored_value_must_be_filled_in_before_anything_else_saves(
        self, actor
    ):
        # The form changes only the screen name; the phone was never filled in.
        errors = errors_of(
            stored(phone="", screenName="old"), {"screenName": "new"}, actor
        )

        assert errors == {"phone": ["error.fieldRequired"]}


class TestRequiredAdminEdits:
    @phone("required_admin_edits")
    def test_a_member_must_fill_it_in_while_it_is_empty(self):
        errors = errors_of(stored(phone=""), {"phone": ""}, MEMBER)

        assert errors == {"phone": ["error.fieldRequired"]}
        assert check_profile_changes(stored(phone=""), {"phone": PHONE}, MEMBER) == {
            "phone": PHONE
        }

    @phone("required_admin_edits")
    def test_a_member_cannot_change_it_once_it_has_a_value(self):
        errors = errors_of(stored(), {"phone": OTHER_PHONE}, MEMBER)

        assert errors == {"phone": ["error.fieldLocked"]}

    @phone("required_admin_edits")
    def test_an_admin_can_change_it_but_not_clear_it(self):
        assert check_profile_changes(stored(), {"phone": OTHER_PHONE}, ADMIN) == {
            "phone": OTHER_PHONE
        }
        assert errors_of(stored(), {"phone": ""}, ADMIN) == {
            "phone": ["error.fieldRequired"]
        }

    @phone("required_admin_edits")
    def test_it_must_be_filled_in_at_signup(self):
        errors = errors_of({}, full_signup(phone=""), SIGNUP)

        assert errors == {"phone": ["error.fieldRequired"]}


class TestChecking:
    def test_a_field_left_out_keeps_its_stored_value(self):
        assert check_profile_changes(stored(), {}, MEMBER) == {}

    def test_every_field_that_fails_is_listed(self):
        errors = errors_of(
            {},
            full_signup(email="not-an-email", firstName="", phone="12"),
            SIGNUP,
        )

        assert errors == {
            "email": ["validation.invalidEmail"],
            "firstName": ["error.fieldRequired"],
            "phone": ["validation.invalidPhone"],
        }

    def test_the_email_and_name_are_always_required(self):
        errors = errors_of({}, {}, SIGNUP)

        assert {"email", "firstName", "lastName"} <= set(errors)

    def test_values_are_stored_cleaned(self):
        changes = check_profile_changes(
            {},
            full_signup(email=" New@Example.com ", screenName=" ada "),
            SIGNUP,
        )

        assert changes["email"] == "new@example.com"
        assert changes["screenName"] == "ada"

    @override_config(
        PROFILE_FIELD_EMAIL="required_admin_edits",
        PROFILE_FIELD_PHONE="required_admin_edits",
    )
    def test_a_locked_value_stored_before_the_current_rules_is_not_a_change(self):
        # A mixed-case email, and a national number from before phones were
        # stored in E.164. The form sends back the cleaned forms.
        old = stored(email="Member@Example.com", phone="0417 000 001")

        changes = check_profile_changes(
            old, {"email": "member@example.com", "phone": PHONE}, MEMBER
        )

        assert changes == {}

    @override_config(PROFILE_FIELD_SCREEN_NAME="optional")
    def test_a_blank_screen_name_stored_as_empty_text_is_not_a_change(self):
        assert (
            check_profile_changes(stored(screenName=""), {"screenName": ""}, MEMBER)
            == {}
        )

    @override_config(PROFILE_FIELD_ADDRESS="required")
    def test_the_address_is_required_as_a_whole(self):
        errors = errors_of({}, full_signup(), SIGNUP)

        assert errors == {"address": ["error.fieldRequired"]}


class TestSave:
    def test_it_writes_the_changes_and_returns_old_and_new_values(self):
        profile = ProfileFactory(phone=PHONE)

        changed = save_profile_changes(profile, {"phone": OTHER_PHONE}, MEMBER)

        assert changed == {"phone": (PHONE, OTHER_PHONE)}
        profile.refresh_from_db()
        assert profile.phone == OTHER_PHONE

    def test_the_instance_passed_in_is_updated_too(self):
        profile = ProfileFactory()

        save_profile_changes(profile, {"email": "new@example.com"}, MEMBER)

        assert profile.user.email == "new@example.com"  # no refresh_from_db

    def test_only_the_columns_that_change_are_written(self):
        profile = ProfileFactory()
        # Changed behind the in-memory copy, as a webhook would.
        Profile.objects.filter(pk=profile.pk).update(memberbucks_balance=12.5)
        get_user_model().objects.filter(pk=profile.user.pk).update(staff=True)

        save_profile_changes(profile, {"phone": OTHER_PHONE}, MEMBER)

        profile.refresh_from_db()
        assert profile.memberbucks_balance == 12.5
        assert profile.user.staff is True

    @phone("optional_admin_edits")
    def test_the_rules_use_the_stored_values_not_the_instance(self):
        # The instance still says the phone is empty, but it was filled in
        # since, so the member's one chance is used up.
        profile = ProfileFactory(phone="")
        Profile.objects.filter(pk=profile.pk).update(phone=PHONE)

        with pytest.raises(ProfileFieldErrors) as excinfo:
            save_profile_changes(profile, {"phone": OTHER_PHONE}, MEMBER)

        assert excinfo.value.errors == {"phone": ["error.fieldLocked"]}

    def test_nothing_is_written_when_a_field_fails(self):
        profile = ProfileFactory(phone=PHONE)

        with pytest.raises(ProfileFieldErrors):
            save_profile_changes(
                profile, {"phone": OTHER_PHONE, "firstName": ""}, ADMIN
            )

        profile.refresh_from_db()
        assert profile.phone == PHONE

    def test_an_email_another_member_has_is_a_conflict(self):
        other = ProfileFactory()
        profile = ProfileFactory()

        with pytest.raises(ProfileConflict) as excinfo:
            save_profile_changes(profile, {"email": other.user.email.upper()}, ADMIN)

        assert excinfo.value.message == "error.accountAlreadyExists"

    def test_a_screen_name_another_member_has_is_a_conflict(self):
        other = ProfileFactory(screen_name="ada")
        profile = ProfileFactory()

        with pytest.raises(ProfileConflict) as excinfo:
            save_profile_changes(profile, {"screenName": "ADA"}, MEMBER)

        assert excinfo.value.message == "error.screenNameAlreadyExists"
        assert other.screen_name == "ada"

    def test_keeping_your_own_email_and_screen_name_is_not_a_conflict(self):
        profile = ProfileFactory(screen_name="ada")

        changed = save_profile_changes(
            profile,
            {"email": profile.user.email, "screenName": "ada", "phone": OTHER_PHONE},
            MEMBER,
        )

        assert set(changed) == {"phone"}

    def test_a_race_on_the_unique_constraint_is_a_conflict(self, monkeypatch):
        # Another member takes the screen name between the check and the write.
        other = ProfileFactory(screen_name="taken")
        profile = ProfileFactory()
        calls = []

        def check_only_after_the_race(changes, user=None):
            calls.append(changes)
            if len(calls) > 1:
                raise ProfileConflict("error.screenNameAlreadyExists")

        monkeypatch.setattr(
            "profile.profile_changes.check_unique", check_only_after_the_race
        )

        with pytest.raises(ProfileConflict) as excinfo:
            save_profile_changes(profile, {"screenName": other.screen_name}, MEMBER)

        assert excinfo.value.message == "error.screenNameAlreadyExists"

    def test_stored_values_reads_every_field(self):
        profile = ProfileFactory(address={"city": "Stockholm"})

        values = stored_values(profile)

        assert values["email"] == profile.user.email
        assert values["firstName"] == profile.first_name
        assert values["address"] == {"city": "Stockholm"}
