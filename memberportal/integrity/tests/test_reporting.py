"""The weekly digest, the management command, the scheduled tasks and the
Prometheus gauges."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from prometheus_client import CollectorRegistry

from integrity import emails, schedule, store, tasks
from integrity.metrics import LAST_COMPLETE, OPEN_ISSUES, IntegrityCollector
from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from tests.factories import PaymentPlanFactory, ProfileFactory

from .conftest import admin_mail

pytestmark = pytest.mark.django_db


def issue(severity=Severity.WARNING, **overrides):
    values = {
        "key": f"legacy:check:{IntegrityIssue.objects.count()}",
        "check_name": "unpaid_but_active",
        "severity": severity,
        "source": Source.LEGACY,
        "message": "Unpaid in Stripe, still active here",
    }
    values.update(overrides)
    return IntegrityIssue.objects.create(**values)


class TestDigest:
    def test_lists_open_warnings_and_critical_issues(self, billing_on, outbox):
        issue(Severity.CRITICAL, profile=ProfileFactory(first_name="Anna"))
        issue(Severity.WARNING)
        issue(Severity.INFO)
        issue(Severity.WARNING, acknowledged_at=timezone.now())

        assert emails.send_digest() is True

        [mail] = admin_mail(outbox)
        assert (
            mail["Subject"]
            == "Weekly billing check: 1 critical, 1 warning, 1 info open"
        )
        assert mail["HtmlBody"].count("Unpaid in Stripe, still active here") == 2
        assert "1 acknowledged issue not listed" in mail["HtmlBody"]

    def test_says_nothing_about_acknowledged_issues_when_there_are_none(
        self, billing_on, outbox
    ):
        issue(Severity.WARNING)

        emails.send_digest()

        [mail] = admin_mail(outbox)
        assert "acknowledged" not in mail["HtmlBody"]
        assert "This week: 1 new, 0 resolved." in mail["HtmlBody"]

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"acknowledged_at": timezone.now()}, id="acknowledged"),
            pytest.param({"severity": Severity.INFO}, id="info"),
            pytest.param({"resolved_at": timezone.now()}, id="resolved"),
        ],
    )
    def test_sends_nothing_without_open_issues_to_act_on(
        self, billing_on, outbox, overrides
    ):
        issue(**overrides)

        assert emails.send_digest() is False
        assert admin_mail(outbox) == []


class TestCommand:
    def test_refuses_while_the_check_is_off(self, db):
        with pytest.raises(CommandError, match="billing check is off"):
            call_command("check_stripe_drift")

    def test_a_dry_run_prints_findings_and_records_nothing(
        self, billing_on, fake_stripe, capsys
    ):
        profile = ProfileFactory(
            state="active",
            subscription_status="active",
            stripe_customer_id="cus_anna",
            stripe_subscription_id="sub_anna",
            membership_plan=PaymentPlanFactory(),
        )
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        call_command("check_stripe_drift", "--dry-run")

        output = capsys.readouterr().out
        assert "Billing check complete" in output
        assert "[warning] unpaid_but_active" in output
        assert IntegrityIssue.objects.count() == 0
        assert IntegrityRun.objects.count() == 0

    def test_records_a_command_run(self, billing_on, fake_stripe, outbox):
        call_command("check_stripe_drift", "--no-email")

        run = IntegrityRun.objects.get()
        assert run.trigger == IntegrityRun.Trigger.COMMAND
        assert admin_mail(outbox) == []

    def test_checks_one_member(self, billing_on, fake_stripe):
        profile = ProfileFactory()

        call_command("check_stripe_drift", "--member", str(profile.user_id))

        run = IntegrityRun.objects.get()
        assert run.trigger == IntegrityRun.Trigger.MEMBER
        assert run.profile == profile

    def test_a_failed_run_exits_with_an_error(self, billing_on, fake_stripe):
        import stripe

        fake_stripe.errors["Subscription.list"] = stripe.error.APIError("down")

        with pytest.raises(CommandError, match="failed"):
            call_command("check_stripe_drift", "--no-email")


class TestTasks:
    def test_runs_at_night_in_the_sites_time_zone(self, settings):
        scheduled = {}

        class Sender:
            def add_periodic_task(self, schedule, signature, **kwargs):
                scheduled[kwargs["name"]] = schedule

        tasks.setup_periodic_tasks(Sender())

        daily = scheduled["integrity_daily_checks"]
        assert daily.hour == {3} and daily.minute == {15}
        assert daily.tz == ZoneInfo(settings.TIME_ZONE)
        weekly = scheduled["integrity_weekly_digest"]
        assert weekly.day_of_week == {1}

    def test_does_nothing_while_the_check_is_off(self, db, fake_stripe):
        tasks.run_integrity_checks()

        assert IntegrityRun.objects.count() == 0
        assert fake_stripe.calls == []

    def test_the_nightly_run_clears_old_history(self, billing_on, fake_stripe):
        old = issue(resolved_at=timezone.now() - store.RETENTION - timedelta(days=1))

        tasks.run_integrity_checks()

        assert not IntegrityIssue.objects.filter(pk=old.pk).exists()
        assert IntegrityRun.objects.get().status == IntegrityRun.Status.COMPLETE

    def test_skips_quietly_while_another_run_is_running(self, billing_on, fake_stripe):
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        tasks.run_integrity_checks()

        assert fake_stripe.calls == []


@pytest.mark.parametrize(
    "hour,minute,day",
    [(2, 0, 21), (3, 15, 22), (23, 0, 22)],
    ids=["before-tonights-run", "at-the-run", "late-evening"],
)
def test_the_next_daily_check(settings, hour, minute, day):
    site_time = ZoneInfo(settings.TIME_ZONE)

    due = schedule.next_daily_check(
        datetime(2026, 10, 21, hour, minute, tzinfo=site_time)
    )

    assert due == datetime(2026, 10, day, 3, 15, tzinfo=site_time)


def test_delete_old_keeps_the_last_complete_run(db):
    long_ago = timezone.now() - store.RETENTION - timedelta(days=5)
    kept = IntegrityRun.objects.create(
        trigger=IntegrityRun.Trigger.SCHEDULE,
        status=IntegrityRun.Status.COMPLETE,
        started_at=long_ago,
        finished_at=long_ago,
    )
    dropped = IntegrityRun.objects.create(
        trigger=IntegrityRun.Trigger.SCHEDULE,
        status=IntegrityRun.Status.FAILED,
        started_at=long_ago,
    )

    store.delete_old(timezone.now())

    assert IntegrityRun.objects.filter(pk=kept.pk).exists()
    assert not IntegrityRun.objects.filter(pk=dropped.pk).exists()


def test_the_gauges_report_staleness_and_open_issues(db):
    finished = timezone.now() - timedelta(hours=5)
    IntegrityRun.objects.create(
        trigger=IntegrityRun.Trigger.SCHEDULE,
        status=IntegrityRun.Status.COMPLETE,
        finished_at=finished,
    )
    issue(Severity.CRITICAL)
    issue(Severity.CRITICAL)
    issue(Severity.WARNING, acknowledged_at=timezone.now())
    registry = CollectorRegistry()
    registry.register(IntegrityCollector())

    assert registry.get_sample_value(LAST_COMPLETE) == pytest.approx(
        finished.timestamp()
    )
    assert (
        registry.get_sample_value(
            OPEN_ISSUES, {"severity": "critical", "source": "legacy"}
        )
        == 2
    )
    assert (
        registry.get_sample_value(
            OPEN_ISSUES, {"severity": "warning", "source": "legacy"}
        )
        is None
    )
