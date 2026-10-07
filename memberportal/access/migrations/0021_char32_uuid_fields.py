import uuid

from django.db import migrations

import membermatters.fields


class Migration(migrations.Migration):
    # Only the migration state changes: the column is char(32) already, except
    # on a database created under Django 5 on MariaDB 10.7+, which this fixes.
    # See membermatters/fields.py.
    dependencies = [
        ("access", "0020_accesscontrolleddevice_post_to_slack"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="interlocklog",
                    name="id",
                    field=membermatters.fields.Char32UUIDField(
                        default=uuid.uuid4, primary_key=True, serialize=False
                    ),
                ),
            ],
            database_operations=[
                membermatters.fields.uuid_columns_to_char32(
                    ("access_interlocklog", "id")
                ),
            ],
        ),
    ]
