"""Migrating a database from the last release (v3.8.0) to this branch.

A release has no dashboard cards yet (api_general 0004 onwards) and keeps its
settings pickled in constance 2.9's constance_config table. This rolls the test
database back to that shape and migrates forward, as `migrate` does when the
container starts. It needs real migrations, so it only runs on the
--migrations leg.
"""

import json

import pytest
from constance import config
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from api_general.models import DashboardCard
from tests.helpers import pickled_setting

pytestmark = pytest.mark.django_db(transaction=True)

LAST_RELEASE = [("api_general", "0003_auto_20211005_0015"), ("constance", None)]


def migrate(targets=None, fake=False):
    executor = MigrationExecutor(connection)
    executor.migrate(targets or executor.loader.graph.leaf_nodes(), fake=fake)


@pytest.fixture
def release_database(request):
    if request.config.getoption("nomigrations"):
        pytest.skip("needs real migrations; runs on the --migrations leg")

    # constance's 0003 (pickle to JSON) can't be reversed. Rolling back drops
    # the table it converted, so it only has to be marked unapplied.
    migrate([("constance", "0002_migrate_from_old_table")], fake=True)
    migrate(LAST_RELEASE)
    yield
    migrate()  # leave the full schema for the tests that follow


def upgrade_in_one_go():
    migrate()


def upgrade_api_general_first():
    # The order this branch used before api_general 0006 existed: 0005 runs
    # while constance's table is still unmoved, so it can't import anything.
    migrate([("api_general", "0005_import_home_page_cards")])
    migrate([("constance", "0002_migrate_from_old_table")])
    migrate()


def upgrade_constance_first():
    # What `manage.py migrate constance` does. The settings may only become
    # JSON after api_general has moved and read them.
    migrate([("constance", "0003_drop_pickle")])
    migrate()


def upgrade_after_constance_3_1_failed_the_move():
    # Where this branch left MySQL and MariaDB while it used constance 3.1:
    # 0002 recorded as applied, every setting still in the old table. Then
    # `migrate constance`, so 0006 has to move them before 0003 converts.
    migrate([("constance", "0001_initial")])
    migrate([("constance", "0002_migrate_from_old_table")], fake=True)
    upgrade_constance_first()


@pytest.mark.parametrize(
    "upgrade",
    [
        upgrade_in_one_go,
        upgrade_api_general_first,
        upgrade_constance_first,
        upgrade_after_constance_3_1_failed_the_move,
    ],
)
def test_a_release_keeps_its_settings_and_gets_its_dashboard_cards(
    release_database, upgrade
):
    cards = [
        {"title": "Wiki", "icon": "mdi-book", "url": "https://wiki.example"},
        {"title": "Chat", "icon": "mdi-chat", "url": "https://chat.example"},
    ]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE constance_config (id integer PRIMARY KEY, "
            f"{quote('key')} varchar(255) NOT NULL UNIQUE, value text NULL)"
        )
        cursor.executemany(
            f"INSERT INTO constance_config (id, {quote('key')}, value) "
            "VALUES (%s, %s, %s)",
            [
                (1, "SITE_NAME", pickled_setting("Old Makerspace")),
                (2, "ENABLE_STRIPE", pickled_setting(False)),
                (3, "HOME_PAGE_CARDS", pickled_setting(json.dumps(cards))),
                (4, "SITE_OWNER", None),  # how None was stored
            ],
        )

    upgrade()

    assert config.SITE_NAME == "Old Makerspace"
    assert config.ENABLE_STRIPE is False
    assert config.SITE_OWNER == "MemberMatters"  # the default
    assert list(DashboardCard.objects.values_list("title", flat=True)) == [
        "Wiki",
        "Chat",
    ]
    assert "constance_config" not in connection.introspection.table_names()
