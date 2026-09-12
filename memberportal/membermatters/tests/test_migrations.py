"""Guards that make the ``--no-migrations`` default safe.

The suite builds its schema straight from the models (see ``pytest.ini``),
which is a large speedup but moves two failure modes out of the default run.
Both are cheap to assert directly.
"""

import io

import pytest
from django.core.management import call_command
from django.db import connection


@pytest.mark.django_db
def test_models_and_migrations_have_not_drifted(settings):
    # Under --no-migrations the schema comes from the models, so a model field
    # with no matching migration still gets a column and every test passes —
    # right up until a real deployment runs migrate and doesn't have it.
    #
    # MIGRATION_MODULES has to be put back first. pytest-django implements
    # --no-migrations by mapping every app to None, which Django reads as
    # "unmigrated" — and makemigrations skips unmigrated apps, so the check
    # would find nothing to report and pass vacuously. The project itself never
    # sets MIGRATION_MODULES, so {} is the real configuration.
    settings.MIGRATION_MODULES = {}

    try:
        call_command(
            "makemigrations", "--check", "--dry-run", verbosity=0, stdout=io.StringIO()
        )
    except SystemExit:  # raised with a non-zero status when changes are pending
        pytest.fail(
            "Models and migrations have drifted — run `python manage.py "
            "makemigrations` and commit the result."
        )


@pytest.mark.django_db
def test_screen_name_lower_index_follows_the_backend_and_the_migration_flag():
    """Pins where the case-insensitive screen_name guarantee actually exists.

    profile/0022 adds a functional UNIQUE index on LOWER(screen_name) in raw
    SQL, to close the race where the iexact pre-check passes but two
    different-case names both insert. Raw SQL is invisible to Django's model
    state, and that has two consequences this asserts together:

    - On SQLite the index does not survive even with migrations. A later
      AlterField (0023_alter_profile_phone) rebuilds the table, and the
      rebuild only recreates indexes Django knows from model state.
    - Under --no-migrations the schema is built from the models, so the index
      is never created on any backend.

    Which leaves exactly one configuration where the constraint is real:
    Postgres with --migrations. That is why the CI Postgres leg opts back in,
    and this is the test that would fail if that stopped being true.

    Verified against a live Postgres: with --migrations the index is present
    and a CaseTest/casetest pair is rejected; with --no-migrations it is
    absent and the pair inserts.

    Stated as current behaviour, not intent. When the underlying issue is
    fixed by expressing the constraint on the model, this test is what will
    fail and point at itself.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM django_migrations "
            "WHERE app = 'profile' AND name = '0022_screen_name_unique'"
        )
        migrations_ran = cursor.fetchone()[0] > 0

        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename='profile_profile' "
                "AND indexname='profile_screen_name_lower_uniq'"
            )
        else:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='profile_screen_name_lower_uniq'"
            )
        index_present = bool(cursor.fetchall())

    should_exist = connection.vendor == "postgresql" and migrations_ran
    assert index_present is should_exist
