"""The member details a new Stripe customer is created with.

Stripe gets the email, the full name, the phone number and the address; a
hidden or blank field isn't sent.
"""

import pytest
from constance.test import override_config

from api_billing.views import ensure_stripe_customer
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

ADDRESS = {
    "line1": "Storgatan 1",
    "postal_code": "123 45",
    "city": "Stockholm",
    "country": "SE",
}


def created_with(stripe_api):
    [(name, _args, kwargs)] = [
        call for call in stripe_api.calls if call[0] == "Customer.create"
    ]
    return kwargs


def test_a_customer_gets_the_email_name_and_phone(stripe_api):
    profile = ProfileFactory(first_name="Ada", last_name="Lovelace")

    assert ensure_stripe_customer(profile.user) == (True, None)

    assert created_with(stripe_api) == {
        "email": profile.user.email,
        "name": "Ada Lovelace",
        "phone": profile.phone,
    }
    profile.refresh_from_db()
    assert profile.stripe_customer_id == "cus_created"


@override_config(PROFILE_FIELD_ADDRESS="optional")
def test_a_collected_address_is_sent(stripe_api):
    profile = ProfileFactory(address=ADDRESS)

    ensure_stripe_customer(profile.user)

    assert created_with(stripe_api)["address"] == ADDRESS


def test_a_hidden_address_is_not_sent(stripe_api):
    # The address is hidden by default; one stored before stays out of Stripe.
    profile = ProfileFactory(address=ADDRESS)

    ensure_stripe_customer(profile.user)

    assert "address" not in created_with(stripe_api)


@override_config(PROFILE_FIELD_PHONE="hidden")
def test_a_hidden_phone_number_is_not_sent(stripe_api):
    profile = ProfileFactory()

    ensure_stripe_customer(profile.user)

    assert "phone" not in created_with(stripe_api)


@override_config(PROFILE_FIELD_PHONE="optional")
def test_a_blank_phone_number_is_not_sent(stripe_api):
    profile = ProfileFactory(phone="")

    ensure_stripe_customer(profile.user)

    assert "phone" not in created_with(stripe_api)


def test_an_existing_customer_is_not_changed(stripe_api):
    profile = ProfileFactory(stripe_customer_id="cus_existing")
    stripe_api.customers["cus_existing"] = {"id": "cus_existing"}

    assert ensure_stripe_customer(profile.user) == (True, None)

    assert stripe_api.names() == ["Customer.retrieve"]
