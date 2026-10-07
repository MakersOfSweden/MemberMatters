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
