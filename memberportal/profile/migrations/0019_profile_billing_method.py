from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0018_alter_profile_screen_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="billing_method",
            field=models.CharField(
                choices=[("card", "Card"), ("invoice", "Invoice")],
                default="card",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="subscription_status",
            field=models.CharField(
                choices=[
                    ("inactive", "Inactive"),
                    ("active", "Active"),
                    ("cancelling", "Cancelling"),
                    ("pending", "Pending"),
                ],
                default="inactive",
                max_length=10,
            ),
        ),
    ]
