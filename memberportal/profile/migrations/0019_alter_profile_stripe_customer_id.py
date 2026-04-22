from django.db import migrations, models


def blank_stripe_customer_id_to_null(apps, schema_editor):
    Profile = apps.get_model("profile", "Profile")
    Profile.objects.filter(stripe_customer_id="").update(stripe_customer_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0018_profile_billing_method"),
    ]

    operations = [
        migrations.RunPython(
            blank_stripe_customer_id_to_null,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="profile",
            name="stripe_customer_id",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=100,
                null=True,
                unique=True,
            ),
        ),
    ]
