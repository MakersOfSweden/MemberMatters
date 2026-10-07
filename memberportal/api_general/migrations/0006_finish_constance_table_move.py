from django.db import migrations

OLD_TABLE = "constance_config"
NEW_TABLE = "constance_constance"


def finish_constance_table_move(apps, schema_editor):
    """Copies what django-constance 3.1's own move left behind.

    constance's 0002 copies constance_config into constance_constance with SQL
    that doesn't quote the key column. KEY is reserved in MySQL and MariaDB, so
    there the copy fails, 0002 swallows the error, and every setting stays in
    the old table while the portal reads the new, empty one. Elsewhere 0002 has
    already dropped the old table and this does nothing.

    The old table's values win. Anything the new table holds under the same key
    was written while the portal couldn't see the setting: constance stores a
    setting's default the first time it is read and not found. Values are
    copied as stored, so they aren't pickled a second time.
    """
    connection = schema_editor.connection
    if OLD_TABLE not in connection.introspection.table_names():
        return

    quote = connection.ops.quote_name
    old, new = quote(OLD_TABLE), quote(NEW_TABLE)
    key, value = quote("key"), quote("value")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {key} FROM {new}")
        existing = {row[0] for row in cursor.fetchall()}

        cursor.execute(f"SELECT {key}, {value} FROM {old}")
        rows = cursor.fetchall()

        cursor.executemany(
            f"UPDATE {new} SET {value} = %s WHERE {key} = %s",
            [
                (row_value, row_key)
                for row_key, row_value in rows
                if row_key in existing
            ],
        )
        cursor.executemany(
            f"INSERT INTO {new} ({key}, {value}) VALUES (%s, %s)",
            [row for row in rows if row[0] not in existing],
        )
        cursor.execute(f"DROP TABLE {old}")


class Migration(migrations.Migration):
    dependencies = [
        ("api_general", "0005_import_home_page_cards"),
        ("constance", "0002_migrate_from_old_table"),
    ]

    operations = [
        migrations.RunPython(finish_constance_table_move, migrations.RunPython.noop),
    ]
