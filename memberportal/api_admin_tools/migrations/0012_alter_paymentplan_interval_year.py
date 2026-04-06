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
                choices=[("Month", "month"), ("Week", "week"), ("Day", "day"), ("Year", "year")],
                max_length=10,
            ),
        ),
    ]
