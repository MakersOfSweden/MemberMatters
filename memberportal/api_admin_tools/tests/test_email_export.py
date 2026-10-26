"""Admin toggle that opts a member out of, or back in to, the email export.

The toggle used to re-send the whole admin profile form with the flag, so it
saved any unsaved edits along with it and failed whenever the form didn't
validate. It now has its own endpoint that writes only the flag.
"""

import pytest
from django.urls import reverse

from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def export_url(profile):
    return reverse("MemberEmailExport", args=[profile.user.id])


@pytest.mark.parametrize("exclude", [True, False])
def test_the_flag_is_set_to_what_was_sent(admin_client, exclude):
    profile = ProfileFactory(exclude_from_email_export=not exclude)

    response = admin_client.post(
        export_url(profile), {"excludeFromEmailExport": exclude}, format="json"
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.exclude_from_email_export is exclude


def test_nothing_else_on_the_profile_is_written(admin_client):
    profile = ProfileFactory()
    # Changed behind the in-memory copy, as an edit elsewhere would. A full-row
    # save from the toggle would write the old name back.
    type(profile).objects.filter(pk=profile.pk).update(first_name="Changed")

    admin_client.post(
        export_url(profile), {"excludeFromEmailExport": True}, format="json"
    )

    profile.refresh_from_db()
    assert profile.first_name == "Changed"
    assert profile.exclude_from_email_export is True


@pytest.mark.parametrize("value", [None, "true", 1])
def test_anything_but_a_boolean_is_refused(admin_client, value):
    profile = ProfileFactory()

    response = admin_client.post(
        export_url(profile), {"excludeFromEmailExport": value}, format="json"
    )

    assert response.status_code == 400
    profile.refresh_from_db()
    assert profile.exclude_from_email_export is False


def test_a_member_cannot_use_it(authed_client):
    profile = ProfileFactory()

    response = authed_client.post(
        export_url(profile), {"excludeFromEmailExport": True}, format="json"
    )

    assert response.status_code == 403
    profile.refresh_from_db()
    assert profile.exclude_from_email_export is False


def test_an_unknown_member_is_not_found(admin_client):
    response = admin_client.post(
        reverse("MemberEmailExport", args=[999999]),
        {"excludeFromEmailExport": True},
        format="json",
    )

    assert response.status_code == 404


def test_saving_the_profile_form_leaves_the_flag_alone(admin_client):
    profile = ProfileFactory(exclude_from_email_export=True)

    response = admin_client.put(
        reverse("MemberProfile", args=[profile.user.id]),
        {
            "email": profile.user.email,
            "rfidCard": "",
            "firstName": profile.first_name,
            "lastName": profile.last_name,
            "phone": profile.phone,
            "screenName": profile.screen_name,
            "vehicleRegistrationPlate": "",
        },
        format="json",
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.exclude_from_email_export is True
