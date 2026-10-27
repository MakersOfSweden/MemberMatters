"""The Django admin: subscriptions are shown read-only, and an admin's edit of a
member's billing columns brings their subscription rows along."""

from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.urls import reverse

from profile.admin import ProfileAdmin
from profile.models import Profile
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser(client):
    admin_user = ProfileFactory(user__admin_user=True, user__is_superuser=True).user
    client.force_login(admin_user)
    return admin_user


@pytest.fixture
def member():
    return ProfileFactory(
        subscription_active=True,
        stripe_subscription_id="sub_1",
        membership_plan=PaymentPlanFactory(),
    )


def test_the_subscription_list_renders(client, superuser, member):
    response = client.get(reverse("admin:subscriptions_subscription_changelist"))

    assert response.status_code == 200
    assert b"sub_1" in response.content


def test_a_subscription_cannot_be_changed(client, superuser, member):
    subscription = member.subscriptions.get()
    url = reverse("admin:subscriptions_subscription_change", args=[subscription.pk])

    client.post(url, {"state": Subscription.State.CANCELLED})

    subscription.refresh_from_db()
    assert subscription.state == Subscription.State.ACTIVE


def test_the_profile_page_lists_the_subscriptions(client, superuser, member):
    response = client.get(reverse("admin:profile_profile_change", args=[member.pk]))

    assert response.status_code == 200
    assert b'id="subscriptions-group"' in response.content


def save_in_admin(profile, superuser, changed):
    model_admin = ProfileAdmin(Profile, admin.site)
    form = SimpleNamespace(changed_data=changed)
    model_admin.save_model(
        SimpleNamespace(user=superuser), profile, form=form, change=True
    )


def test_an_edited_status_reaches_the_subscription(superuser, member):
    member.subscription_status = "inactive"
    member.stripe_subscription_id = None
    member.membership_plan = None

    save_in_admin(
        member,
        superuser,
        ["subscription_status", "stripe_subscription_id", "membership_plan"],
    )

    assert Profile.objects.get(pk=member.pk).current_subscription is None
    assert member.subscriptions.get().state == Subscription.State.CANCELLED


def test_other_edits_leave_the_subscriptions_alone(superuser, member):
    version = member.subscriptions.get().version
    member.first_name = "Renamed"

    save_in_admin(member, superuser, ["first_name"])

    assert member.subscriptions.get().version == version
