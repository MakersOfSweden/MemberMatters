import uuid

from django.db import migrations

import membermatters.fields


class Migration(migrations.Migration):
    # Only the migration state changes: the column is char(32) already, except
    # on a database created under Django 5 on MariaDB 10.7+, which this fixes.
    # See membermatters/fields.py.
    dependencies = [
        ("api_general", "0008_delete_empty_settings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="emailverificationtoken",
                    name="verification_token",
                    field=membermatters.fields.Char32UUIDField(default=uuid.uuid4),
                ),
            ],
            database_operations=[
                membermatters.fields.uuid_columns_to_char32(
                    ("api_general_emailverificationtoken", "verification_token")
                ),
            ],
        ),
    ]
