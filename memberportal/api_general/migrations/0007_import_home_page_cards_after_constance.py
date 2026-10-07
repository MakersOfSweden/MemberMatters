import importlib

from django.db import migrations

first_import = importlib.import_module(
    "api_general.migrations.0005_import_home_page_cards"
)


def import_home_page_cards_if_none(apps, schema_editor):
    """Runs 0005's import again, now that constance's migrations have run.

    0005 can't depend on constance, so on an install upgrading from a release
    it runs before constance has moved its table, finds nothing to read, and
    imports no cards. Installs where 0005 did import them, or where an admin
    has created cards since, already have some and are left alone.
    """
    if apps.get_model("api_general", "DashboardCard").objects.exists():
        return

    first_import.import_home_page_cards(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("api_general", "0006_finish_constance_table_move"),
    ]

    operations = [
        migrations.RunPython(import_home_page_cards_if_none, migrations.RunPython.noop),
    ]
