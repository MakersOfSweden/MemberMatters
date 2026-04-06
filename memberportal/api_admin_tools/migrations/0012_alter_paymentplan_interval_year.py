from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0011_alter_paymentplan_interval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentplan",
            name="interval",
            field=models.CharField(
                choices=[
                    ("day", "Day"),
                    ("week", "Week"),
                    ("month", "Month"),
                    ("year", "Year"),
                ],
                max_length=10,
            ),
        ),
    ]
