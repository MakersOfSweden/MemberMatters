import uuid

from django.db import migrations

import membermatters.fields


class Migration(migrations.Migration):
    # Only the migration state changes: the columns are char(32) already, except
    # on a database created under Django 5 on MariaDB 10.7+, which this fixes.
    # See membermatters/fields.py.
    dependencies = [
        ("profile", "0025_terms_accepted_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="profile",
                    name="digital_id_token",
                    field=membermatters.fields.Char32UUIDField(
                        blank=True,
                        default=uuid.uuid4,
                        null=True,
                        verbose_name="Digital ID Token",
                    ),
                ),
                migrations.AlterField(
                    model_name="user",
                    name="password_reset_key",
                    field=membermatters.fields.Char32UUIDField(
                        blank=True, default=None, null=True
                    ),
                ),
            ],
            database_operations=[
                membermatters.fields.uuid_columns_to_char32(
                    ("profile_profile", "digital_id_token"),
                    ("profile_user", "password_reset_key"),
                ),
            ],
        ),
    ]
