"""A member editing their own profile, each field following its setting."""

import pytest
from constance.test import override_config

from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PHONE = "+61417000001"
OTHER_PHONE = "+61417000002"


@pytest.fixture
def profile(member):
    member.phone = PHONE
    member.save()
    return member


def form(profile, **changes):
    """What the profile form sends: every field, changed or not."""
    return {
        "email": profile.user.email,
        "firstName": profile.first_name,
        "lastName": profile.last_name,
        "phone": profile.phone,
        "screenName": profile.screen_name,
        "vehicleRegistrationPlate": profile.vehicle_registration_plate or "",
        **changes,
    }


def save(authed_client, body):
    return authed_client.put("/api/profile/", body, format="json")


def test_a_member_can_change_their_details(authed_client, profile):
    response = save(
        authed_client,
        form(
            profile,
            email="New@Example.com",
            firstName="Grace",
            phone="0417 000 002",
            screenName="grace",
        ),
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.user.email == "new@example.com"
    assert profile.first_name == "Grace"
    assert profile.phone == OTHER_PHONE
    assert profile.screen_name == "grace"


def test_a_required_field_cannot_be_cleared(authed_client, profile):
    response = save(authed_client, form(profile, screenName=""))

    assert response.status_code == 400
    assert response.json() == {"screenName": ["error.fieldRequired"]}


def test_an_invalid_value_is_refused_by_field(authed_client, profile):
    response = save(authed_client, form(profile, phone="12", email="nope"))

    assert response.status_code == 400
    assert response.json() == {
        "email": ["validation.invalidEmail"],
        "phone": ["validation.invalidPhone"],
    }


def test_an_email_another_member_has_is_a_conflict(authed_client, profile):
    other = ProfileFactory()

    response = save(authed_client, form(profile, email=other.user.email))

    assert response.status_code == 409
    assert response.json() == {"message": "error.accountAlreadyExists"}


def test_a_hidden_field_is_not_written(authed_client, profile):
    # The vehicle plate is hidden by default.
    response = save(authed_client, form(profile, vehicleRegistrationPlate="ABC123"))

    assert response.status_code == 200
    profile.refresh_from_db()
    assert not profile.vehicle_registration_plate


class TestOnlyAdminsEdit:
    @override_config(PROFILE_FIELD_NAME="required_admin_edits")
    def test_the_form_sending_the_stored_values_back_saves(
        self, authed_client, profile
    ):
        response = save(authed_client, form(profile, screenName="changed"))

        assert response.status_code == 200
        profile.refresh_from_db()
        assert profile.screen_name == "changed"

    @override_config(PROFILE_FIELD_NAME="required_admin_edits")
    def test_a_member_cannot_change_a_locked_field(self, authed_client, profile):
        response = save(authed_client, form(profile, firstName="Grace"))

        assert response.status_code == 400
        assert response.json() == {"firstName": ["error.fieldLocked"]}
        profile.refresh_from_db()
        assert profile.first_name == "Test"

    @override_config(PROFILE_FIELD_PHONE="optional_admin_edits")
    def test_a_member_fills_in_an_empty_field_once(self, authed_client, profile):
        profile.phone = ""
        profile.save()

        first = save(authed_client, form(profile, phone=PHONE))
        profile.refresh_from_db()
        second = save(authed_client, form(profile, phone=OTHER_PHONE))

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.json() == {"phone": ["error.fieldLocked"]}
        profile.refresh_from_db()
        assert profile.phone == PHONE
