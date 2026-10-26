"""The profile field settings as the public site config reports them."""

import pytest
from constance.test import override_config
from django.urls import reverse

pytestmark = pytest.mark.django_db


def get_features(api_client):
    response = api_client.get(reverse("get_config"))
    assert response.status_code == 200
    return response.json()["features"]


def test_the_old_flags_are_gone(api_client):
    # The forms read features.profileFields instead.
    features = get_features(api_client)

    assert "requireScreenName" not in features["signup"]
    assert "collectVehicleRegistrationPlate" not in features["signup"]
    assert "profile" not in features


class TestProfileFields:
    def test_every_field_and_its_setting_is_listed(self, api_client):
        assert get_features(api_client)["profileFields"] == {
            "email": "required",
            "firstName": "required",
            "lastName": "required",
            "phone": "required",
            "screenName": "required",
            "vehicleRegistrationPlate": "hidden",
            "address": "hidden",
        }

    @override_config(
        PROFILE_FIELD_NAME="required_admin_edits",
        PROFILE_FIELD_PHONE="optional_admin_edits",
        PROFILE_FIELD_ADDRESS="optional",
    )
    def test_the_settings_are_reported_as_they_are(self, api_client):
        fields = get_features(api_client)["profileFields"]

        assert fields["firstName"] == "required_admin_edits"
        assert fields["lastName"] == "required_admin_edits"
        assert fields["phone"] == "optional_admin_edits"
        assert fields["address"] == "optional"

    @override_config(PROFILE_FIELD_PHONE="nonsense")
    def test_a_value_the_field_does_not_allow_is_reported_as_the_default(
        self, api_client
    ):
        assert get_features(api_client)["profileFields"]["phone"] == "required"

    def test_the_address_parts_are_listed_in_order(self, api_client):
        assert get_features(api_client)["addressParts"] == [
            {"key": "line1", "required": True, "maxLength": 200},
            {"key": "line2", "required": False, "maxLength": 200},
            {"key": "postal_code", "required": True, "maxLength": 20},
            {"key": "city", "required": True, "maxLength": 100},
            {"key": "country", "required": True, "maxLength": 2},
        ]
