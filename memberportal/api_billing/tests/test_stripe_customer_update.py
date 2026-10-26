"""Copying a profile edit to the member's Stripe customer.

A detail is only changed in Stripe where Stripe still has what the portal had
before the edit. One that differs was changed in Stripe some other way: it is
left alone, logged on the member and emailed to the admin.
"""

import pytest
import stripe
from constance.test import override_config
from django.urls import reverse

from profile.models import Profile, UserEventLog
from tests.factories import ProfileFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.override_config(
        ENABLE_STRIPE=True,
        STRIPE_SECRET_KEY="sk_test_123",
        EMAIL_ADMIN="admin@example.com",
    ),
]

CUSTOMER_ID = "cus_member"
PHONE = "+61417000001"
# After the member's name, as it is once the edit is saved.
DRIFT_SUBJECT = "'s details in Stripe weren't updated"


@pytest.fixture
def profile(db):
    return ProfileFactory(
        first_name="Test",
        last_name="Member",
        phone=PHONE,
        stripe_customer_id=CUSTOMER_ID,
    )


@pytest.fixture
def customer(stripe_api, profile):
    """The Stripe customer, holding what the portal has."""
    stripe_api.customers[CUSTOMER_ID] = {
        "id": CUSTOMER_ID,
        "email": profile.user.email,
        "name": "Test Member",
        "phone": PHONE,
        "address": None,
    }
    return stripe_api.customers[CUSTOMER_ID]


@pytest.fixture
def member_client(api_client, profile):
    api_client.force_authenticate(user=profile.user)
    return api_client


def form(profile, **changes):
    return {
        "email": profile.user.email,
        "firstName": profile.first_name,
        "lastName": profile.last_name,
        "phone": profile.phone,
        "screenName": profile.screen_name,
        **changes,
    }


@pytest.fixture
def save(member_client, profile, django_capture_on_commit_callbacks):
    """A member's profile edit, with what runs after it commits."""

    def _save(**changes):
        with django_capture_on_commit_callbacks(execute=True):
            response = member_client.put(
                "/api/profile/", form(profile, **changes), format="json"
            )
        assert response.status_code == 200, response.content
        return response

    return _save


def modified(stripe_api):
    return [
        kwargs for name, _args, kwargs in stripe_api.calls if name == "Customer.modify"
    ]


def drift_emails(outbox):
    return [m for m in outbox if m["Subject"].endswith(DRIFT_SUBJECT)]


def test_changed_details_are_copied_to_stripe(stripe_api, customer, save, outbox):
    save(email="new@example.com", firstName="Ada", phone="+61417000002")

    assert modified(stripe_api) == [
        {"email": "new@example.com", "name": "Ada Member", "phone": "+61417000002"}
    ]
    assert drift_emails(outbox) == []


def test_only_the_changed_details_are_sent(stripe_api, customer, save):
    save(lastName="Lovelace")

    assert modified(stripe_api) == [{"name": "Test Lovelace"}]


def test_an_edit_that_changes_nothing_stripe_holds_calls_nothing(
    stripe_api, customer, save
):
    save(screenName="changed")

    assert stripe_api.calls == []


def test_a_detail_changed_in_stripe_is_left_alone_and_reported(
    stripe_api, customer, save, outbox, profile
):
    customer["email"] = "edited-in-stripe@example.com"

    save(email="new@example.com", firstName="Ada")

    # The name still matched, so it was updated; the email wasn't.
    assert modified(stripe_api) == [{"name": "Ada Member"}]
    [email] = drift_emails(outbox)
    assert email["Subject"] == "Ada Member's details in Stripe weren't updated"
    assert email["To"] == "admin@example.com"
    assert "edited-in-stripe@example.com" in email["HtmlBody"]
    assert CUSTOMER_ID in email["HtmlBody"]
    assert UserEventLog.objects.filter(
        user=profile.user, description__startswith="Didn't update the Stripe customer"
    ).exists()


def test_nothing_is_modified_when_every_detail_differs(
    stripe_api, customer, save, outbox
):
    customer["phone"] = "+61499999999"

    save(phone="+61417000002")

    assert modified(stripe_api) == []
    assert len(drift_emails(outbox)) == 1


def test_the_email_is_compared_ignoring_case(stripe_api, customer, save, profile):
    customer["email"] = profile.user.email.upper()

    save(email="new@example.com")

    assert modified(stripe_api) == [{"email": "new@example.com"}]


@override_config(PROFILE_FIELD_PHONE="optional")
def test_a_detail_blank_in_both_counts_as_the_same(stripe_api, customer, save, profile):
    # Blank in the portal, and missing (None) in Stripe.
    Profile.objects.filter(pk=profile.pk).update(phone="")
    customer["phone"] = None

    save(phone="+61417000002")

    assert modified(stripe_api) == [{"phone": "+61417000002"}]


@override_config(PROFILE_FIELD_PHONE="optional")
def test_a_cleared_detail_is_removed_from_stripe(stripe_api, customer, save):
    save(phone="")

    assert modified(stripe_api) == [{"phone": ""}]


@override_config(PROFILE_FIELD_ADDRESS="optional")
def test_an_address_is_sent_with_every_part(stripe_api, customer, save):
    save(
        address={
            "line1": "Storgatan 1",
            "postal_code": "123 45",
            "city": "Stockholm",
            "country": "SE",
        }
    )

    assert modified(stripe_api) == [
        {
            "address": {
                "line1": "Storgatan 1",
                "line2": "",
                "postal_code": "123 45",
                "city": "Stockholm",
                "state": "",
                "country": "SE",
            }
        }
    ]


@override_config(PROFILE_FIELD_ADDRESS="optional")
def test_an_address_with_a_state_set_in_stripe_is_left_alone(
    stripe_api, customer, save, outbox
):
    # The portal doesn't collect a state, so this one was set in Stripe.
    customer["address"] = {"state": "Stockholms län"}

    save(
        address={
            "line1": "Storgatan 1",
            "postal_code": "123 45",
            "city": "Stockholm",
            "country": "SE",
        }
    )

    assert modified(stripe_api) == []
    assert len(drift_emails(outbox)) == 1


def test_a_member_without_a_stripe_customer_is_left_out(
    stripe_api, member_client, profile, django_capture_on_commit_callbacks
):
    profile.stripe_customer_id = None
    profile.save()

    with django_capture_on_commit_callbacks(execute=True):
        member_client.put(
            "/api/profile/", form(profile, firstName="Ada"), format="json"
        )

    assert stripe_api.calls == []


def test_a_deleted_customer_is_left_alone(stripe_api, customer, save):
    customer["deleted"] = True

    save(firstName="Ada")

    assert stripe_api.names() == ["Customer.retrieve"]


def test_a_stripe_error_is_logged_and_the_edit_stands(
    stripe_api, customer, save, outbox, profile
):
    stripe_api.raise_on["Customer.modify"] = stripe.error.APIConnectionError("down")

    save(firstName="Ada")

    profile.refresh_from_db()
    assert profile.first_name == "Ada"
    assert drift_emails(outbox) == []
    assert UserEventLog.objects.filter(
        user=profile.user, description="Error while updating the Stripe customer."
    ).exists()


@override_config(ENABLE_STRIPE=False)
def test_nothing_is_sent_while_stripe_is_off(stripe_api, customer, save):
    save(firstName="Ada")

    assert stripe_api.calls == []


def test_an_admin_edit_is_copied_too(
    stripe_api, customer, profile, admin_client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.put(
            reverse("MemberProfile", args=[profile.user.id]),
            {**form(profile, lastName="Lovelace"), "rfidCard": ""},
            format="json",
        )

    assert response.status_code == 200
    assert modified(stripe_api) == [{"name": "Test Lovelace"}]
