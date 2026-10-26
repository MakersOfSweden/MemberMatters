"""Signing up, with each profile field following its PROFILE_FIELD_* setting."""

import pytest
from constance.test import override_config

from profile.models import Profile, User
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
ADDRESS = {
    "line1": "Storgatan 1",
    "postal_code": "123 45",
    "city": "Stockholm",
    "country": "SE",
}


@pytest.fixture(autouse=True)
def _throttle_rates(enable_throttling):
    # Register is throttle-scoped, and a scoped view can't run without its rate.
    pass


def payload(**overrides):
    return {
        "email": "Ada@Example.com",
        "password": PASSWORD,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "screenName": "ada",
        "phone": "+61417123456",
        **overrides,
    }


def signup(api_client, **overrides):
    return api_client.post("/api/register/", payload(**overrides), format="json")


def new_profile():
    return Profile.objects.get(user__email="ada@example.com")


def test_a_signup_stores_the_cleaned_values(api_client):
    response = signup(api_client, screenName=" ada ", phone="0417 123 456")

    assert response.status_code == 201
    profile = new_profile()
    assert profile.first_name == "Ada"
    assert profile.screen_name == "ada"
    assert profile.phone == "+61417123456"
    assert profile.user.check_password(PASSWORD)


def test_every_error_comes_back_at_once(api_client):
    response = api_client.post(
        "/api/register/", {"email": "not-an-email"}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {
        "email": ["validation.invalidEmail"],
        "firstName": ["error.fieldRequired"],
        "lastName": ["error.fieldRequired"],
        "phone": ["error.fieldRequired"],
        "screenName": ["error.fieldRequired"],
        "password": ["error.fieldRequired"],
    }


def test_the_password_is_checked_against_the_name(api_client):
    response = signup(api_client, password="AdaLovelace1")

    assert response.status_code == 400
    assert "error.passwordTooSimilar" in response.json()["password"]


def test_the_phone_may_still_be_sent_as_mobile(api_client):
    # As signup forms from before the field settings do.
    body = payload(mobile="+61417123456")
    del body["phone"]

    response = api_client.post("/api/register/", body, format="json")

    assert response.status_code == 201
    assert new_profile().phone == "+61417123456"


class TestFieldSettings:
    @override_config(PROFILE_FIELD_PHONE="hidden")
    def test_a_hidden_field_is_neither_required_nor_stored(self, api_client):
        response = signup(api_client, phone="+61417999999")

        assert response.status_code == 201
        assert new_profile().phone == ""

    @override_config(PROFILE_FIELD_PHONE="optional")
    def test_an_optional_field_may_be_left_blank(self, api_client):
        response = signup(api_client, phone="")

        assert response.status_code == 201
        assert new_profile().phone == ""

    @override_config(PROFILE_FIELD_SCREEN_NAME="optional")
    def test_an_optional_screen_name_is_stored_as_null_when_blank(self, api_client):
        response = signup(api_client, screenName="")

        assert response.status_code == 201
        assert new_profile().screen_name is None

    @pytest.mark.parametrize("mode", ["required", "required_admin_edits"])
    def test_a_required_field_must_be_filled_in(self, api_client, mode):
        with override_config(PROFILE_FIELD_SCREEN_NAME=mode):
            response = signup(api_client, screenName="")

        assert response.status_code == 400
        assert response.json() == {"screenName": ["error.fieldRequired"]}

    @override_config(PROFILE_FIELD_VEHICLE_PLATE="optional")
    def test_a_collected_vehicle_plate_is_stored(self, api_client):
        response = signup(api_client, vehicleRegistrationPlate=" ABC123 ")

        assert response.status_code == 201
        assert new_profile().vehicle_registration_plate == "ABC123"

    def test_the_vehicle_plate_is_hidden_by_default(self, api_client):
        response = signup(api_client, vehicleRegistrationPlate="ABC123")

        assert response.status_code == 201
        assert not new_profile().vehicle_registration_plate

    @override_config(PROFILE_FIELD_ADDRESS="required")
    def test_a_required_address_must_be_complete(self, api_client):
        response = signup(api_client, address={"city": "Stockholm"})

        assert response.status_code == 400
        assert response.json() == {"address": ["error.addressIncomplete"]}

    @override_config(PROFILE_FIELD_ADDRESS="optional")
    def test_an_address_is_stored(self, api_client):
        response = signup(api_client, address=ADDRESS)

        assert response.status_code == 201
        assert new_profile().address == ADDRESS

    def test_the_address_is_hidden_by_default(self, api_client):
        response = signup(api_client, address=ADDRESS)

        assert response.status_code == 201
        assert new_profile().address == {}


class TestConflicts:
    def test_an_email_already_used_is_a_conflict(self, api_client):
        ProfileFactory(user__email="ada@example.com")

        response = signup(api_client)

        assert response.status_code == 409
        assert response.json() == {"message": "error.accountAlreadyExists"}

    def test_a_screen_name_already_used_is_a_conflict(self, api_client):
        ProfileFactory(screen_name="ADA")

        response = signup(api_client)

        assert response.status_code == 409
        assert response.json() == {"message": "error.screenNameAlreadyExists"}
        assert not User.objects.filter(email="ada@example.com").exists()
