from collections import defaultdict

from django.db import migrations, models


def normalize_screen_names(apps, schema_editor):
    Profile = apps.get_model("profile", "Profile")

    Profile.objects.filter(screen_name="").update(screen_name=None)

    groups = defaultdict(list)
    for profile in (
        Profile.objects.exclude(screen_name__isnull=True)
        .only("pk", "screen_name")
        .iterator()
    ):
        groups[profile.screen_name.lower()].append(profile)

    for group in groups.values():
        if len(group) <= 1:
            continue
        group.sort(key=lambda p: p.pk)
        for loser in group[1:]:
            suffix = f"-{loser.pk}"
            new_name = loser.screen_name[: 30 - len(suffix)] + suffix
            loser.screen_name = new_name
            loser.save(update_fields=["screen_name"])


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
    ]
