from collections import defaultdict

from django.db import migrations, models


def normalize_screen_names(apps, schema_editor):
    Profile = apps.get_model("profile", "Profile")

    Profile.objects.filter(screen_name="").update(screen_name=None)

    profiles = list(
        Profile.objects.exclude(screen_name__isnull=True).only("pk", "screen_name")
    )
    taken = {p.screen_name.lower() for p in profiles}

    groups = defaultdict(list)
    for p in profiles:
        groups[p.screen_name.lower()].append(p)

    for group in groups.values():
        if len(group) <= 1:
            continue
        group.sort(key=lambda p: p.pk)
        for n, loser in enumerate(group[1:], start=1):
            # The winner keeps the shared lowercase key, so leave it in
            # `taken` — only add the loser's new candidate.
            base = loser.screen_name
            i = n
            while True:
                suffix = f"-{i}"
                candidate = base[: 30 - len(suffix)] + suffix
                if candidate.lower() not in taken:
                    break
                i += 1
            loser.screen_name = candidate
            loser.save(update_fields=["screen_name"])
            taken.add(candidate.lower())


def add_screen_name_lower_index(apps, schema_editor):
    # MySQL's default utf8mb4_*_ci collation already makes the column-level
    # unique constraint case-insensitive. Postgres and SQLite default to
    # case-sensitive collations, so add a functional unique index on
    # LOWER(screen_name) to close the race where the iexact pre-check passes
    # but two different-case screen_names both insert.
    if schema_editor.connection.vendor == "mysql":
        return
    schema_editor.execute(
        "CREATE UNIQUE INDEX profile_screen_name_lower_uniq "
        'ON profile_profile (LOWER("screen_name"));'
    )


def drop_screen_name_lower_index(apps, schema_editor):
    if schema_editor.connection.vendor == "mysql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS profile_screen_name_lower_uniq;")


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0021_profile_pending_signup_email_sent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="screen_name",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=30,
                null=True,
                verbose_name="Screen Name",
            ),
        ),
        migrations.RunPython(
            normalize_screen_names,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="profile",
            name="screen_name",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=30,
                null=True,
                unique=True,
                verbose_name="Screen Name",
            ),
        ),
        migrations.RunPython(
            add_screen_name_lower_index,
            reverse_code=drop_screen_name_lower_index,
        ),
    ]
