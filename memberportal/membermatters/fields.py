import uuid

from django.db import migrations, models


class Char32UUIDField(models.UUIDField):
    """A UUIDField that stays char(32) on MySQL and MariaDB.

    Since Django 5.0, UUIDField uses MariaDB 10.7's native uuid type and sends
    values in its dashed form. Columns created by earlier Django versions are
    char(32) and can't hold those values, so every insert fails and every lookup
    misses. This keeps all MySQL and MariaDB installs on char(32) and 32-digit
    hex, whatever the server version, as Django's 5.0 release notes suggest.
    Other databases are unaffected.
    """

    def db_type(self, connection):
        if connection.vendor == "mysql":
            return "char(32)"
        return super().db_type(connection)

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        if connection.vendor == "mysql" and isinstance(value, uuid.UUID):
            return value.hex
        return value


def uuid_columns_to_char32(*columns):
    """A migration operation that turns native MariaDB uuid columns into char(32).

    Only a database created under Django 5 on MariaDB 10.7 or later has them,
    because the migrations that add these fields create native columns there.
    Everywhere else this does nothing. `columns` are (table, column) pairs.
    """

    def forwards(apps, schema_editor):
        connection = schema_editor.connection
        if connection.vendor != "mysql":
            return
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            for table, column in columns:
                cursor.execute(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = %s "
                    "AND column_name = %s",
                    [table, column],
                )
                data_type, is_nullable = cursor.fetchone()
                if data_type != "uuid":
                    continue
                null = "NULL" if is_nullable == "YES" else "NOT NULL"
                # Through char(36) so rows keep their value: uuid converts to
                # the dashed form, which doesn't fit in 32 characters.
                cursor.execute(
                    f"ALTER TABLE {quote(table)} MODIFY {quote(column)} char(36) {null}"
                )
                cursor.execute(
                    f"UPDATE {quote(table)} SET {quote(column)} = "
                    f"REPLACE({quote(column)}, '-', '')"
                )
                cursor.execute(
                    f"ALTER TABLE {quote(table)} MODIFY {quote(column)} char(32) {null}"
                )

    return migrations.RunPython(forwards, migrations.RunPython.noop)
