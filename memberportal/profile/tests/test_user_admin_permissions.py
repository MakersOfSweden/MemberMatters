"""Who may import and export users on the Django admin's User page.

Portal staff can log in to the Django admin, which refuses them the User list.
The import and export views used to let them in anyway, so a staff member
could download every member and import themselves the admin flag.
"""

import pytest
from django.urls import reverse

from profile.models import User
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

VIEWS = [
    ("get", "admin:profile_user_import"),
    ("post", "admin:profile_user_process_import"),
    ("get", "admin:profile_user_export"),
    ("post", "admin:profile_user_export"),
]


@pytest.mark.parametrize("method, view", VIEWS)
def test_staff_are_refused(client, method, view):
    staff = ProfileFactory(user__staff_user=True)
    client.force_login(staff.user)

    response = getattr(client, method)(reverse(view))

    assert response.status_code == 403
    assert not User.objects.get(pk=staff.user.pk).admin


@pytest.mark.parametrize(
    "view", ["admin:profile_user_import", "admin:profile_user_export"]
)
def test_superusers_are_let_in(client, view):
    admin = ProfileFactory(user__admin_user=True, user__is_superuser=True)
    client.force_login(admin.user)

    assert client.get(reverse(view)).status_code == 200
