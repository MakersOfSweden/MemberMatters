from django.db import migrations


def delete_empty_settings(apps, schema_editor):
    """Deletes settings stored as NULL, which constance 4 can't read.

    picklefield stored None as NULL, for example after the settings API was
    sent {"value": null}. constance 3.1 read such a row as missing and stored
    the default. constance 4 fails every read and write of it, its admin page
    included, and its 0003 migration leaves the row alone. Without the row
    the portal stores the default the next time it reads the setting, as
    before.
    """
    apps.get_model("constance", "Constance").objects.filter(value=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("api_general", "0007_import_home_page_cards_after_constance"),
    ]
    # constance's 0003 converts the pickled settings to JSON. 0006 copies them
    # as stored, 0007 unpickles HOME_PAGE_CARDS and this clears what 0003
    # skips, so all three have to run first. Nothing else orders them:
    # `migrate constance` would run 0003 alone. As 0003 can't be reversed,
    # api_general can't be migrated back past this point either.
    run_before = [
        ("constance", "0003_drop_pickle"),
    ]

    operations = [
        migrations.RunPython(delete_empty_settings, migrations.RunPython.noop),
    ]
