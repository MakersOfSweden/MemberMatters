"""UUIDs on MySQL and MariaDB keep the char(32) columns earlier Django created.

Django 5 would otherwise send MariaDB 10.7+ dashed values those columns can't
hold. Verified by hand on MariaDB 10.11: a database migrated by Django 4.2
failed to create members under 5.2 and found none of its old tokens, and works
with Char32UUIDField; a database created under 5.2 gets its native uuid
columns converted, rows included.
"""

import uuid
from types import SimpleNamespace

import pytest
from django.db import connection, models

from access.models import InterlockLog
from api_general.models import EmailVerificationToken
from membermatters.fields import Char32UUIDField
from profile.models import Profile, User

MARIADB = SimpleNamespace(
    vendor="mysql", features=SimpleNamespace(has_native_uuid_field=True)
)
MYSQL = SimpleNamespace(
    vendor="mysql", features=SimpleNamespace(has_native_uuid_field=False)
)
VALUE = uuid.UUID("378d87b4-fef7-4ea3-8b30-e77e2eb102f4")


@pytest.mark.parametrize(
    "model, name",
    [
        (Profile, "digital_id_token"),
        (User, "password_reset_key"),
        (EmailVerificationToken, "verification_token"),
        (InterlockLog, "id"),
    ],
)
def test_every_uuid_field_keeps_char32(model, name):
    assert type(model._meta.get_field(name)) is Char32UUIDField


@pytest.mark.parametrize("server", [MARIADB, MYSQL], ids=["mariadb", "mysql"])
def test_mysql_and_mariadb_get_32_hex_digits(server):
    field = Char32UUIDField()

    assert field.db_type(server) == "char(32)"
    assert field.get_db_prep_value(VALUE, server) == VALUE.hex


@pytest.mark.skipif(connection.vendor == "mysql", reason="covered by the test above")
def test_other_databases_get_what_uuidfield_gives():
    field = Char32UUIDField()
    plain = models.UUIDField()

    assert field.db_type(connection) == plain.db_type(connection)
    assert field.get_db_prep_value(VALUE, connection) == plain.get_db_prep_value(
        VALUE, connection
    )
