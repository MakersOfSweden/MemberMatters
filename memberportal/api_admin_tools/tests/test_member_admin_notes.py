"""MemberAdminNotes — the admin-only note attached to a member.

The feature's whole premise is that the member cannot see the note, so the
tests are weighted towards who *cannot* read it rather than the CRUD, which is
a single text column. The three leak paths are the member's own profile
endpoint, the admin member list (which also answers to API keys), and the note
endpoint itself.
"""

import json

import pytest
from rest_framework_api_key.models import APIKey

from profile.models import ADMIN_NOTES_MAX_LENGTH
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def notes_url(member):
    return f"/api/admin/members/{member.user.id}/notes/"


class TestAdminAccess:
    def test_get_returns_empty_string_for_a_member_with_no_note(
        self, admin_client, member
    ):
        response = admin_client.get(notes_url(member))

        assert response.status_code == 200
        assert response.json() == {"adminNotes": ""}

    def test_put_stores_the_note(self, admin_client, member):
        response = admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": "Owes a locker key."}),
            content_type="application/json",
        )

        assert response.status_code == 200
        member.refresh_from_db()
        assert member.admin_notes == "Owes a locker key."

    def test_put_overwrites_rather_than_appends(self, admin_client, member):
        member.admin_notes = "First"
        member.save()

        admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": "Second"}),
            content_type="application/json",
        )

        member.refresh_from_db()
        assert member.admin_notes == "Second"

    def test_put_with_an_empty_string_clears_the_note(self, admin_client, member):
        member.admin_notes = "Something"
        member.save()

        response = admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": ""}),
            content_type="application/json",
        )

        assert response.status_code == 200
        member.refresh_from_db()
        assert member.admin_notes == ""

    def test_put_without_the_key_is_rejected_rather_than_clearing(
        self, admin_client, member
    ):
        # The sibling profile endpoint assigns body.get(...) unconditionally, so
        # a client that omits a field silently blanks it. A note is exactly the
        # value that must not disappear that way.
        member.admin_notes = "Do not lose me."
        member.save()

        response = admin_client.put(
            notes_url(member),
            data=json.dumps({}),
            content_type="application/json",
        )

        assert response.status_code == 400
        member.refresh_from_db()
        assert member.admin_notes == "Do not lose me."

    def test_put_writes_an_audit_log_entry_without_the_body(
        self, admin_client, admin_member, member
    ):
        admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": "Sensitive detail."}),
            content_type="application/json",
        )

        logs = member.get_logs()
        assert logs.count() == 1
        entry = logs.first()
        assert admin_member.get_full_name() in entry.description
        assert "Sensitive detail." not in entry.description
        assert "Sensitive detail." not in (entry.data or "")

    def test_a_note_at_the_length_limit_is_accepted(self, admin_client, member):
        at_limit = "x" * ADMIN_NOTES_MAX_LENGTH

        response = admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": at_limit}),
            content_type="application/json",
        )

        assert response.status_code == 200
        member.refresh_from_db()
        assert len(member.admin_notes) == ADMIN_NOTES_MAX_LENGTH

    def test_an_over_length_note_is_rejected_and_not_truncated(
        self, admin_client, member
    ):
        member.admin_notes = "Previous note."
        member.save()

        response = admin_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": "x" * (ADMIN_NOTES_MAX_LENGTH + 1)}),
            content_type="application/json",
        )

        assert response.status_code == 400
        # A message key the frontend can render, unlike the bare HTML page
        # Django returns once the body passes DATA_UPLOAD_MAX_MEMORY_SIZE.
        assert response.json()["message"] == "error.adminNotesTooLong"
        assert response.json()["maxLength"] == ADMIN_NOTES_MAX_LENGTH

        member.refresh_from_db()
        assert member.admin_notes == "Previous note."

    def test_unknown_member_is_404_not_500(self, admin_client):
        assert admin_client.get("/api/admin/members/999999/notes/").status_code == 404


class TestTheMemberCannotSeeIt:
    def test_the_member_cannot_read_their_own_note(self, authed_client, member):
        member.admin_notes = "Invisible to them."
        member.save()

        response = authed_client.get(notes_url(member))

        assert response.status_code == 403

    def test_the_member_cannot_write_their_own_note(self, authed_client, member):
        response = authed_client.put(
            notes_url(member),
            data=json.dumps({"adminNotes": "Self-serve."}),
            content_type="application/json",
        )

        assert response.status_code == 403
        member.refresh_from_db()
        assert member.admin_notes == ""

    def test_a_member_cannot_read_another_members_note(self, authed_client):
        other = ProfileFactory(admin_notes="Someone else's business.")

        assert authed_client.get(notes_url(other)).status_code == 403

    def test_the_note_is_absent_from_the_member_profile_endpoint(
        self, authed_client, member
    ):
        member.admin_notes = "Invisible to them."
        member.save()

        payload = json.dumps(authed_client.get("/api/profile/").json())

        assert "Invisible to them." not in payload
        assert "adminNotes" not in payload

    def test_anonymous_callers_are_refused(self, api_client, member):
        assert api_client.get(notes_url(member)).status_code in (401, 403)


class TestApiKeyCallersAreExcluded:
    """`GetMembers` and `SignupProgress` answer to HasAPIKey; this must not."""

    @pytest.fixture
    def api_key_client(self, api_client):
        _, key = APIKey.objects.create_key(name="integration")
        api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        return api_client

    def test_an_api_key_cannot_read_the_note(self, api_key_client, member):
        member.admin_notes = "Not for integrations."
        member.save()

        response = api_key_client.get(notes_url(member))

        # 401 rather than 403: HasAPIKey is a permission class reading the
        # header directly, so with it off the view there is no authenticated
        # identity at all and DRF reports unauthenticated. Either code is a
        # refusal; what matters is that the body does not come back.
        assert response.status_code in (401, 403)
        assert "Not for integrations." not in response.content.decode()

    def test_the_admin_member_list_carries_the_flag_but_not_the_body(
        self, api_key_client, member
    ):
        member.admin_notes = "Not for integrations."
        member.save()

        response = api_key_client.get("/api/admin/members/")

        assert response.status_code == 200
        payload = response.json()
        assert "Not for integrations." not in json.dumps(payload)
        row = next(row for row in payload if row["id"] == member.user.id)
        assert row["hasAdminNotes"] is True


class TestHasAdminNotesFlag:
    def test_false_when_the_note_is_empty(self, admin_client, member):
        assert member.get_basic_profile()["hasAdminNotes"] is False

    def test_false_when_the_note_is_whitespace_only(self, member):
        # A textarea a user tabbed through should not light up the indicator.
        member.admin_notes = "   \n  "
        member.save()

        assert member.get_basic_profile()["hasAdminNotes"] is False

    def test_true_once_a_note_is_set(self, member):
        member.admin_notes = "Anything"
        member.save()

        assert member.get_basic_profile()["hasAdminNotes"] is True
