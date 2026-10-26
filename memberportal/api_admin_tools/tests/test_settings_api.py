"""Admin API that reads and writes constance settings straight from its table."""

import pytest
from constance import config
from django.urls import reverse

pytestmark = pytest.mark.django_db


def setting_url(key):
    return reverse("ManageSettings", args=[key])


def test_a_setting_is_read_as_its_value(admin_client):
    config.SITE_NAME = "Makerspace"

    response = admin_client.get(setting_url("SITE_NAME"))

    assert response.json() == {"key": "SITE_NAME", "value": "Makerspace"}


def test_the_list_holds_every_stored_setting(admin_client):
    config.SITE_NAME = "Makerspace"
    config.ENABLE_STRIPE = False

    response = admin_client.get(reverse("ManageSettings"))

    assert {s["key"]: s["value"] for s in response.json()} == {
        "SITE_NAME": "Makerspace",
        "ENABLE_STRIPE": False,
    }


@pytest.mark.parametrize(
    "key, value", [("SITE_NAME", "Hackerspace"), ("ENABLE_STRIPE", True)]
)
def test_a_written_setting_is_what_the_portal_reads(admin_client, key, value):
    setattr(config, key, "placeholder")

    response = admin_client.put(setting_url(key), {"value": value}, format="json")

    assert response.json() == {"key": key, "value": value}
    assert getattr(config, key) == value


def test_an_unknown_setting_is_not_found(admin_client):
    assert admin_client.get(setting_url("NOPE")).status_code == 404
    assert (
        admin_client.put(setting_url("NOPE"), {"value": 1}, format="json").status_code
        == 404
    )


def test_members_cannot_use_it(authed_client):
    assert authed_client.get(reverse("ManageSettings")).status_code == 403


@pytest.mark.parametrize(
    "key, value",
    [
        ("PROFILE_FIELD_PHONE", "nonsense"),
        ("PROFILE_FIELD_PHONE", None),
        # Email and name offer only the two required values.
        ("PROFILE_FIELD_EMAIL", "hidden"),
        ("PROFILE_FIELD_NAME", "optional"),
    ],
)
def test_a_profile_field_setting_refuses_a_value_the_field_does_not_allow(
    admin_client, key, value
):
    setattr(config, key, "required")

    response = admin_client.put(setting_url(key), {"value": value}, format="json")

    assert response.status_code == 400
    assert response.json() == {"message": "error.invalidValue"}
    assert getattr(config, key) == "required"


@pytest.mark.parametrize(
    "key, value",
    [
        ("PROFILE_FIELD_PHONE", "optional_admin_edits"),
        ("PROFILE_FIELD_EMAIL", "required_admin_edits"),
    ],
)
def test_a_profile_field_setting_takes_a_value_the_field_allows(
    admin_client, key, value
):
    setattr(config, key, "required")

    response = admin_client.put(setting_url(key), {"value": value}, format="json")

    assert response.json() == {"key": key, "value": value}
    assert getattr(config, key) == value
