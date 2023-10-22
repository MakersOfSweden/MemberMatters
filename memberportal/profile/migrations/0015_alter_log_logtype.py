# Generated by Django 3.2.20 on 2023-10-22 05:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0014_auto_20231022_1450"),
    ]

    operations = [
        migrations.AlterField(
            model_name="log",
            name="logtype",
            field=models.CharField(
                choices=[
                    ("generic", "Generic log entry"),
                    ("usage", "Generic usage access"),
                    ("stripe", "Stripe related event"),
                    ("memberbucks", "Memberbucks related event"),
                    ("spacebucks", "Spacebucks related event"),
                    ("profile", "Member profile was edited or updated"),
                    ("interlock", "Interlock device related event"),
                    ("door", "Door device related event"),
                    ("memberbucksdevice", "Memberbucks device related event"),
                    ("email", "An email was sent or attempted to be sent"),
                    ("admin", "An admin performed an action"),
                    ("error", "An event or action caused an error"),
                    ("xero", "Generic xero log entry"),
                ],
                default="generic",
                max_length=30,
                verbose_name="Type of action/event",
            ),
        ),
    ]
