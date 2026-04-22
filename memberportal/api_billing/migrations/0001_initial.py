from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProcessedStripeEvent",
            fields=[
                (
                    "event_id",
                    models.CharField(max_length=255, primary_key=True, serialize=False),
                ),
                ("event_type", models.CharField(max_length=100)),
                ("processed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Processed Stripe Event",
                "verbose_name_plural": "Processed Stripe Events",
            },
        ),
    ]
