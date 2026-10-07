"""The member import and export on the Django admin's User page.

UserResource declares the Profile columns as fields of User, which has none of
them. Exporting fills them through dehydrate_ methods; importing creates the
Profile in before_import_row. These pin what the admin produces and accepts
today.
"""

import pytest
import tablib
from django.urls import reverse

from profile.admin import UserResource
from profile.models import Profile, User
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

IMPORT_HEADERS = "email,staff,admin,first_name,last_name,screen_name,rfid"


def export_csv():
    dataset = UserResource().export(queryset=User.objects.order_by("email"))
    return dataset.csv.replace("\r\n", "\n")


def import_csv(text):
    return UserResource().import_data(
        tablib.Dataset().load(text, format="csv"), dry_run=False, raise_errors=True
    )


def test_export_writes_one_row_per_user():
    ProfileFactory(
        user__email="alice@example.com",
        user__staff_user=True,
        first_name="Alice",
        last_name="Admin",
        screen_name="alice",
        rfid="1234567",
        state="active",
    )
    UserFactory(email="bob@example.com")  # no Profile

    assert export_csv() == (
        "first_name,last_name,screen_name,rfid,state,email,staff,admin\n"
        # screen_name has no working dehydrate method (it's misspelled), so it
        # stays empty.
        "Alice,Admin,,1234567,active,alice@example.com,1,0\n"
        ",,,,noob,bob@example.com,0,0\n"
    )


def test_import_creates_members_and_leaves_the_default_admin_alone():
    # The account `loaddata initial` creates.
    default = ProfileFactory(
        user__email="default@example.com",
        user__admin_user=True,
        first_name="Default",
        last_name="Admin",
        screen_name="the_admin",
    )

    result = import_csv(
        f"{IMPORT_HEADERS}\n"
        "carol@example.com,0,0,Carol,Member,carol,7654321\n"
        "default@example.com,0,0,Default,Admin,,\n"
    )

    assert (result.totals["update"], result.totals["skip"]) == (1, 1)
    carol = Profile.objects.get(user__email="carol@example.com")
    assert (carol.first_name, carol.last_name, carol.screen_name, carol.rfid) == (
        "Carol",
        "Member",
        "carol",
        "7654321",
    )
    assert carol.user.email_verified is True
    default.user.refresh_from_db()
    assert (default.user.staff, default.user.admin) == (True, True)


def test_import_updates_an_existing_members_flags():
    dave = ProfileFactory(
        user__email="dave@example.com", first_name="Dave", last_name="Staff"
    )

    import_csv(f"{IMPORT_HEADERS}\ndave@example.com,1,0,Dave,Staff,,\n")

    dave.user.refresh_from_db()
    assert (dave.user.staff, dave.user.admin) == (True, False)


@pytest.fixture
def superuser_client(client):
    admin = ProfileFactory(user__admin_user=True, user__is_superuser=True)
    client.force_login(admin.user)
    return client


def format_choices(client, view):
    form = client.get(reverse(f"admin:profile_user_{view}")).context["form"]
    return {label: value for value, label in form.fields["format"].choices if value}


def test_the_admin_offers_every_format(superuser_client):
    # The spreadsheet formats need the extras in requirements.txt.
    assert list(format_choices(superuser_client, "export")) == [
        "csv",
        "xls",
        "xlsx",
        "tsv",
        "ods",
        "json",
        "yaml",
        "html",
    ]
    assert list(format_choices(superuser_client, "import")) == [
        "csv",
        "xls",
        "xlsx",
        "tsv",
        "ods",
        "json",
        "yaml",
        "html",
    ]
    changelist = superuser_client.get(reverse("admin:profile_user_changelist"))
    assert changelist.status_code == 200


def test_the_admin_export_downloads_the_same_csv(superuser_client):
    ProfileFactory(user__email="alice@example.com", first_name="Alice")
    url = reverse("admin:profile_user_export")
    form = superuser_client.get(url).context["form"]

    response = superuser_client.post(
        url,
        {
            "format": format_choices(superuser_client, "export")["csv"],
            "resource": "0",
            **{name: "on" for name in form.fields if name.startswith("userresource_")},
        },
    )

    assert response["Content-Type"] == "text/csv"
    assert response.content.decode().replace("\r\n", "\n") == export_csv()
