from datetime import timedelta
from django.utils import timezone
from membermatters.celeryapp import app
from api_billing.models import ProcessedStripeEvent
import logging

logger = logging.getLogger("celery:api_billing")

# Stripe retries webhooks for ~72h; 30 days is a safe retention for
# forensic lookups. Tune if the table grows unexpectedly.
EVENT_RETENTION_DAYS = 30


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        timedelta(days=1),
        cleanup_processed_stripe_events.s(),
        name="cleanup_processed_stripe_events",
    )


@app.task
def cleanup_processed_stripe_events():
    cutoff = timezone.now() - timedelta(days=EVENT_RETENTION_DAYS)
    deleted, _ = ProcessedStripeEvent.objects.filter(
        processed_at__lt=cutoff
    ).delete()
    logger.info(f"Deleted {deleted} expired Stripe webhook dedup rows")
