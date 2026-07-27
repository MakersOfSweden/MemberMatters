from django.db import migrations, models


def lowercase_interval_values(apps, schema_editor):
    PaymentPlan = apps.get_model("api_admin_tools", "PaymentPlan")
    for old, new in (("Day", "day"), ("Week", "week"), ("Month", "month")):
        PaymentPlan.objects.filter(interval=old).update(interval=new)


def uppercase_interval_values(apps, schema_editor):
    PaymentPlan = apps.get_model("api_admin_tools", "PaymentPlan")
    for old, new in (("day", "Day"), ("week", "Week"), ("month", "Month")):
        PaymentPlan.objects.filter(interval=old).update(interval=new)


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0011_alter_paymentplan_interval"),
    ]

    operations = [
        migrations.RunPython(
            lowercase_interval_values, reverse_code=uppercase_interval_values
        ),
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
