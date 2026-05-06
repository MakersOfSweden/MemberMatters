from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0020_alter_profile_stripe_customer_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="pending_signup_email_sent",
            field=models.BooleanField(default=False),
        ),
    ]
