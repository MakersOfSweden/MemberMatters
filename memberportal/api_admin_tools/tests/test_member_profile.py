"""An admin editing a member's profile, each field following its setting.

Admins can change any field that isn't hidden, including the "only admins
edit" ones, but can't leave a required field blank. The access card isn't one
of the profile fields yet and keeps its own handling.
"""

import pytest
from constance.test import override_config
from django.urls import reverse

from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PHONE = "+61417000001"


@pytest.fixture
def profile(db):
    return ProfileFactory(phone=PHONE)


def form(profile, **changes):
    """What the admin profile form sends: every field, changed or not."""
    return {
        "email": profile.user.email,
        "rfidCard": profile.rfid or "",
        "firstName": profile.first_name,
        "lastName": profile.last_name,
        "phone": profile.phone,
        "screenName": profile.screen_name,
        "vehicleRegistrationPlate": profile.vehicle_registration_plate or "",
        **changes,
    }


def save(admin_client, profile, body):
    return admin_client.put(
        reverse("MemberProfile", args=[profile.user.id]), body, format="json"
    )


def test_an_admin_can_change_a_members_details(admin_client, profile):
    response = save(
        admin_client,
        profile,
        form(profile, email="New@Example.com", lastName="Hopper", rfidCard="1234"),
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.user.email == "new@example.com"
    assert profile.last_name == "Hopper"
    assert profile.rfid == "1234"


@override_config(
    PROFILE_FIELD_NAME="required_admin_edits",
    PROFILE_FIELD_PHONE="required_admin_edits",
)
def test_an_admin_can_change_fields_only_admins_edit(admin_client, profile):
    response = save(
        admin_client, profile, form(profile, firstName="Grace", phone="+61417000002")
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.first_name == "Grace"
    assert profile.phone == "+61417000002"


@pytest.mark.parametrize("field", ["email", "firstName", "phone", "screenName"])
def test_an_admin_cannot_leave_a_required_field_blank(admin_client, profile, field):
    response = save(admin_client, profile, form(profile, **{field: ""}))

    assert response.status_code == 400
    assert response.json() == {field: ["error.fieldRequired"]}


def test_a_blank_required_field_must_be_filled_in_first(admin_client):
    # An old record with no phone, from before it was checked.
    profile = ProfileFactory(phone="")

    response = save(admin_client, profile, form(profile, lastName="Hopper"))

    assert response.status_code == 400
    assert response.json() == {"phone": ["error.fieldRequired"]}


@override_config(PROFILE_FIELD_PHONE="optional")
def test_an_optional_field_may_be_cleared(admin_client, profile):
    response = save(admin_client, profile, form(profile, phone=""))

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.phone == ""


def test_a_hidden_field_is_kept_as_stored(admin_client):
    # The vehicle plate is hidden by default.
    profile = ProfileFactory(vehicle_registration_plate="ABC123")

    response = save(
        admin_client, profile, form(profile, vehicleRegistrationPlate="XYZ789")
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.vehicle_registration_plate == "ABC123"


def test_an_email_another_member_has_is_a_conflict(admin_client, profile):
    other = ProfileFactory()

    response = save(admin_client, profile, form(profile, email=other.user.email))

    assert response.status_code == 409
    assert response.json() == {"message": "error.accountAlreadyExists"}


def test_an_access_card_another_member_has_is_a_conflict(admin_client, profile):
    ProfileFactory(rfid="1234")

    response = save(admin_client, profile, form(profile, rfidCard="1234"))

    assert response.status_code == 409
    assert response.json() == {"message": "accessCard.alreadyInUse"}
    profile.refresh_from_db()
    assert profile.rfid is None


def test_the_access_card_is_kept_when_it_is_not_sent(admin_client):
    profile = ProfileFactory(rfid="1234", phone=PHONE)
    body = form(profile, lastName="Hopper")
    del body["rfidCard"]

    response = save(admin_client, profile, body)

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.rfid == "1234"


def test_nothing_is_saved_when_a_field_fails(admin_client, profile):
    response = save(admin_client, profile, form(profile, rfidCard="5678", firstName=""))

    assert response.status_code == 400
    profile.refresh_from_db()
    assert profile.rfid is None
    assert profile.first_name == "Test"


def test_only_the_columns_that_change_are_written(admin_client, profile):
    form_body = form(profile, lastName="Hopper")
    # Changed after the admin opened the form, as a webhook would.
    type(profile).objects.filter(pk=profile.pk).update(memberbucks_balance=12.5)

    save(admin_client, profile, form_body)

    profile.refresh_from_db()
    assert profile.memberbucks_balance == 12.5
