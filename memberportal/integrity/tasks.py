import logging

from django.contrib.auth import get_user_model
from django.utils import timezone
from django_celery_beat.tzcrontab import TzAwareCrontab

from membermatters.celeryapp import app

from . import emails, runner, store
from .models import IntegrityRun
from .schedule import DAILY_CHECK, WEEKLY_DIGEST, site_time_zone

logger = logging.getLogger("celery:integrity")


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    site_time = site_time_zone()
    sender.add_periodic_task(
        TzAwareCrontab(**DAILY_CHECK, tz=site_time),
        run_integrity_checks.s(),
        expires=3600,
        name="integrity_daily_checks",
    )
    sender.add_periodic_task(
        TzAwareCrontab(**WEEKLY_DIGEST, tz=site_time),
        send_integrity_digest.s(),
        expires=3600,
        name="integrity_weekly_digest",
    )


@app.task
def run_integrity_checks(trigger=IntegrityRun.Trigger.SCHEDULE, user_id=None):
    if not runner.is_enabled():
        logger.info("Billing check skipped: it's off or Stripe isn't configured.")
        return

    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    try:
        outcome = runner.run(trigger, user=user)
    except runner.AlreadyRunning:
        logger.info("Billing check skipped: another run is in progress.")
        return

    logger.info(
        f"Billing check {outcome.run.status}: {outcome.run.open_issues} open "
        f"issues, {outcome.run.stripe_requests} Stripe requests."
    )
    if trigger == IntegrityRun.Trigger.SCHEDULE:
        store.delete_old(timezone.now())


@app.task
def send_integrity_digest():
    if not runner.is_enabled():
        return
    emails.send_digest()
