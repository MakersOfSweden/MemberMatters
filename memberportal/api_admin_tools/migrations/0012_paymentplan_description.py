from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0011_alter_paymentplan_interval"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentplan",
            name="description",
            field=models.CharField(
                blank=True,
                default="",
                max_length=250,
                verbose_name="Description",
            ),
        ),
    ]
