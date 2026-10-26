"""What members and other services see of the profile fields.

A hidden field's stored data is kept and shown to admins, but members, and the
services they sign in to, only see the fields that aren't hidden. Where there
is no screen name to show, the first and last name stand in for it.
"""

import pytest
from constance.test import override_config
from django.urls import reverse

from membermatters.oidc_provider_settings import userinfo
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

ADDRESS = {
    "line1": "Storgatan 1",
    "postal_code": "123 45",
    "city": "Stockholm",
    "country": "SE",
}


class TestOwnProfile:
    def get(self, authed_client):
        response = authed_client.get("/api/profile/")
        assert response.status_code == 200
        return response.json()

    def test_the_fields_that_are_not_hidden_are_shown(self, authed_client, member):
        profile = self.get(authed_client)

        assert profile["phone"] == member.phone
        assert profile["screenName"] == member.screen_name
        # Hidden by default.
        assert "vehicleRegistrationPlate" not in profile
        assert "address" not in profile

    @override_config(PROFILE_FIELD_PHONE="hidden", PROFILE_FIELD_SCREEN_NAME="hidden")
    def test_hidden_fields_are_left_out_even_with_data_stored(
        self, authed_client, member
    ):
        profile = self.get(authed_client)

        assert "phone" not in profile
        assert "screenName" not in profile
        assert profile["firstName"] == member.first_name

    @override_config(PROFILE_FIELD_ADDRESS="optional")
    def test_the_address_is_shown_when_it_is_collected(self, authed_client, member):
        member.address = ADDRESS
        member.save()

        assert self.get(authed_client)["address"] == ADDRESS


class TestScreenName:
    def test_the_screen_name_is_the_display_name(self):
        profile = ProfileFactory(screen_name="ada")

        assert profile.get_visible_screen_name() == "ada"
        assert profile.get_display_name() == "ada"

    def test_without_one_the_full_name_stands_in(self):
        profile = ProfileFactory(screen_name=None, first_name="Ada", last_name="L")

        assert profile.get_visible_screen_name() is None
        assert profile.get_display_name() == "Ada L"

    @override_config(PROFILE_FIELD_SCREEN_NAME="hidden")
    def test_a_hidden_screen_name_is_not_shown(self):
        profile = ProfileFactory(screen_name="ada", first_name="Ada", last_name="L")

        assert profile.get_visible_screen_name() is None
        assert profile.get_display_name() == "Ada L"

    @override_config(PROFILE_FIELD_SCREEN_NAME="hidden")
    def test_admins_still_see_a_hidden_screen_name(self, admin_client):
        profile = ProfileFactory(screen_name="ada")

        response = admin_client.get(reverse("GetMembers"))

        members = {member["id"]: member for member in response.json()}
        assert members[profile.user.id]["screenName"] == "ada"

    @override_config(PROFILE_FIELD_SCREEN_NAME="hidden")
    def test_the_members_list_leaves_a_hidden_screen_name_out(self, authed_client):
        profile = ProfileFactory(active=True, screen_name="ada")

        response = authed_client.get("/api/tools/members/")

        members = {member["id"]: member for member in response.json()}
        assert members[profile.id]["screenName"] is None


class TestSignInClaims:
    def claims(self, profile):
        return userinfo({}, profile.user)

    def test_the_screen_name_is_the_username(self):
        claims = self.claims(ProfileFactory(screen_name="ada"))

        assert claims["nickname"] == "ada"
        assert claims["preferred_username"] == "ada"

    def test_without_a_screen_name_the_full_name_is_the_username(self):
        profile = ProfileFactory(screen_name=None, first_name="Ada", last_name="L")

        claims = self.claims(profile)

        assert claims["nickname"] == "Ada L"
        assert claims["preferred_username"] == "Ada L"

    @override_config(PROFILE_FIELD_PHONE="hidden")
    def test_a_hidden_phone_number_is_not_passed_on(self):
        claims = self.claims(ProfileFactory(phone="+61417000001"))

        assert claims["phone_number"] == "NO_PHONENUMBER"

    def test_a_phone_number_is_passed_on(self):
        claims = self.claims(ProfileFactory(phone="+61417000001"))

        assert claims["phone_number"] == "+61417000001"


@override_config(PROFILE_FIELD_SCREEN_NAME="optional")
def test_the_members_list_reads_the_setting_once(
    authed_client, django_assert_max_num_queries
):
    for _ in range(5):
        ProfileFactory(active=True)

    with django_assert_max_num_queries(4) as queries:
        authed_client.get("/api/tools/members/")

    reads = [q for q in queries.captured_queries if "constance" in q["sql"]]
    assert len(reads) == 1
