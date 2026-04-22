from django.db import models


class ProcessedStripeEvent(models.Model):
    """Idempotency record for Stripe webhook events.

    Stripe retries webhook deliveries on non-2xx responses or timeouts for up
    to ~3 days. We store every successfully-validated event id here and
    skip duplicates so retries don't re-run side effects (emails, SMS, state
    changes). Cleaned up periodically by an admin/cron task."""

    event_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Processed Stripe Event"
        verbose_name_plural = "Processed Stripe Events"
