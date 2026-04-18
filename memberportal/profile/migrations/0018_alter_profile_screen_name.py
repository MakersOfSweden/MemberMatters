from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0017_alter_log_logtype"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="screen_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Screen Name",
            ),
        ),
    ]
