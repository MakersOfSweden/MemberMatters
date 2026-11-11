"""The admin API behind the Billing Integrity page and the Billing tab banner."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db

STATUS = "/api/admin/billing/integrity/"
ISSUES = "/api/admin/billing/integrity/issues/"
RUN = "/api/admin/billing/integrity/run/"


def issue(profile=None, severity=Severity.CRITICAL, **overrides):
    values = {
        "key": f"legacy:ended_in_stripe:{IntegrityIssue.objects.count()}",
        "check_name": "ended_in_stripe",
        "severity": severity,
        "source": Source.LEGACY,
        "message": "Cancelled in Stripe, still active here",
        "profile": profile,
        "stripe_ref": "sub_anna",
        "details": {"mm": "active", "stripe": "canceled", "cause": "c", "action": "a"},
    }
    values.update(overrides)
    return IntegrityIssue.objects.create(**values)


def acknowledge_path(issue_id):
    return f"{ISSUES}{issue_id}/acknowledge/"


def member_path(profile):
    return f"/api/admin/members/{profile.user_id}/billing-integrity/"


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", STATUS),
        ("get", ISSUES),
        ("post", RUN),
        ("post", acknowledge_path(1)),
        ("get", "/api/admin/members/1/billing-integrity/"),
        ("post", "/api/admin/members/1/billing-integrity/"),
    ],
)
def test_members_are_refused(authed_client, method, path):
    assert getattr(authed_client, method)(path).status_code == 403


class TestStatus:
    def test_counts_open_issues_by_severity(self, admin_client, billing_on):
        issue(severity=Severity.CRITICAL)
        issue(severity=Severity.WARNING)
        issue(severity=Severity.WARNING, acknowledged_at=timezone.now())
        issue(severity=Severity.WARNING, resolved_at=timezone.now())

        body = admin_client.get(STATUS).json()

        assert body["counts"] == {
            "critical": 1,
            "warning": 1,
            "info": 0,
            "acknowledged": 1,
        }
        assert body["enabled"] is True
        assert body["stripeTestMode"] is True

    def test_is_stale_without_a_recent_complete_run(self, admin_client, billing_on):
        IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.SCHEDULE,
            status=IntegrityRun.Status.COMPLETE,
            finished_at=timezone.now() - timedelta(hours=40),
        )

        assert admin_client.get(STATUS).json()["stale"] is True

    def test_is_fresh_after_last_nights_run(self, admin_client, billing_on):
        run = IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.SCHEDULE,
            status=IntegrityRun.Status.COMPLETE,
            finished_at=timezone.now() - timedelta(hours=10),
        )

        body = admin_client.get(STATUS).json()

        assert body["stale"] is False
        assert body["lastCompleteRun"]["id"] == run.id

    def test_a_member_recheck_isnt_the_last_run(self, admin_client, billing_on):
        IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.MEMBER,
            status=IntegrityRun.Status.COMPLETE,
            finished_at=timezone.now(),
            profile=ProfileFactory(),
        )

        body = admin_client.get(STATUS).json()

        assert body["lastRun"] is None
        assert body["stale"] is True

    def test_reports_the_schedule_and_the_next_run(
        self, admin_client, billing_on, settings
    ):
        body = admin_client.get(STATUS).json()

        assert body["schedule"] == {
            "dailyCheckAt": "03:15",
            "weeklyDigestDay": "mon",
            "weeklyDigestAt": "08:15",
            "timeZone": settings.TIME_ZONE,
        }
        assert body["nextRun"].endswith("Z")

    def test_has_no_next_run_without_celery(self, admin_client, billing_on, settings):
        settings.CELERY_BROKER_URL = None

        assert admin_client.get(STATUS).json()["nextRun"] is None

    def test_is_never_stale_while_the_check_is_off(self, admin_client):
        body = admin_client.get(STATUS).json()

        assert body["enabled"] is False
        assert body["stale"] is False


class TestIssues:
    def test_lists_open_unacknowledged_issues_by_default(self, admin_client):
        profile = ProfileFactory(first_name="Anna", last_name="Svensson")
        shown = issue(profile)
        issue(acknowledged_at=timezone.now())
        issue(resolved_at=timezone.now())

        [row] = admin_client.get(ISSUES).json()

        assert row["id"] == shown.id
        assert row["memberId"] == profile.user_id
        assert row["memberName"] == "Anna Svensson"
        assert row["mm"] == "active"
        assert row["stripe"] == "canceled"
        assert row["stripeUrl"] == "https://dashboard.stripe.com/subscriptions/sub_anna"

    @pytest.mark.parametrize("state", ["acknowledged", "resolved"])
    def test_filters_by_status(self, admin_client, state):
        issue()
        wanted = issue(
            acknowledged_at=timezone.now() if state == "acknowledged" else None,
            resolved_at=timezone.now() if state == "resolved" else None,
        )

        rows = admin_client.get(ISSUES, {"status": state}).json()

        assert [row["id"] for row in rows] == [wanted.id]

    def test_filters_by_severity(self, admin_client):
        issue(severity=Severity.CRITICAL)
        warning = issue(severity=Severity.WARNING)

        rows = admin_client.get(ISSUES, {"severity": "warning"}).json()

        assert [row["id"] for row in rows] == [warning.id]


class TestAcknowledge:
    def test_records_who_and_why(self, admin_client, admin_member):
        profile = ProfileFactory()
        open_issue = issue(profile)

        response = admin_client.post(
            acknowledge_path(open_issue.id), {"note": "Comped by the board"}
        )

        assert response.status_code == 200
        open_issue.refresh_from_db()
        assert open_issue.acknowledged_by == admin_member.user
        assert open_issue.notes == "Comped by the board"
        assert open_issue.resolved_at is None
        assert profile.user.usereventlog_set.filter(
            description__startswith="Billing issue acknowledged"
        ).exists()

    def test_can_be_withdrawn(self, admin_client):
        acknowledged = issue(acknowledged_at=timezone.now())

        admin_client.delete(acknowledge_path(acknowledged.id))

        acknowledged.refresh_from_db()
        assert acknowledged.acknowledged_at is None

    def test_a_resolved_issue_cant_be_acknowledged(self, admin_client):
        resolved = issue(resolved_at=timezone.now())

        assert admin_client.post(acknowledge_path(resolved.id)).status_code == 404


class TestRunNow:
    def test_queues_a_run(self, admin_client, admin_member, billing_on, monkeypatch):
        queued = []
        monkeypatch.setattr(
            "integrity.tasks.run_integrity_checks.delay",
            lambda **kwargs: queued.append(kwargs),
        )

        response = admin_client.post(RUN)

        assert response.status_code == 202
        assert queued == [
            {"trigger": IntegrityRun.Trigger.MANUAL, "user_id": admin_member.user_id}
        ]

    def test_needs_celery(self, admin_client, billing_on, settings):
        settings.CELERY_BROKER_URL = None

        response = admin_client.post(RUN)

        assert response.status_code == 503
        assert response.json()["message"] == "billingIntegrity.noCelery"

    def test_refuses_while_the_check_is_off(self, admin_client):
        assert admin_client.post(RUN).status_code == 409

    @pytest.mark.parametrize(
        "trigger", [IntegrityRun.Trigger.SCHEDULE, IntegrityRun.Trigger.MEMBER]
    )
    def test_refuses_while_a_run_is_running(self, admin_client, billing_on, trigger):
        IntegrityRun.objects.create(trigger=trigger)

        response = admin_client.post(RUN)

        assert response.status_code == 409
        assert response.json()["message"] == "billingIntegrity.alreadyRunning"
        assert admin_client.get(STATUS).json()["running"] is True


class TestMember:
    def test_lists_the_members_open_issues(self, admin_client):
        profile = ProfileFactory()
        mine = issue(profile, acknowledged_at=timezone.now())
        issue(ProfileFactory())
        issue(profile, resolved_at=timezone.now())

        body = admin_client.get(member_path(profile)).json()

        assert [row["id"] for row in body["issues"]] == [mine.id]

    def test_rechecks_just_that_member(self, admin_client, billing_on, fake_stripe):
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

        body = admin_client.post(member_path(profile)).json()

        assert body["run"]["status"] == IntegrityRun.Status.COMPLETE
        assert body["run"]["stripeRequests"] == 1
        assert [row["check"] for row in body["issues"]] == ["unpaid_but_active"]

    def test_recheck_waits_for_a_running_run(self, admin_client, billing_on):
        profile = ProfileFactory()
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        response = admin_client.post(member_path(profile))

        assert response.status_code == 409
        assert response.json()["message"] == "billingIntegrity.alreadyRunning"

    def test_recheck_needs_the_check_on(self, admin_client):
        profile = ProfileFactory()

        assert admin_client.post(member_path(profile)).status_code == 409

    def test_unknown_member(self, admin_client):
        assert (
            admin_client.get("/api/admin/members/99999/billing-integrity/").status_code
            == 404
        )


def test_anonymous_requests_are_refused():
    assert APIClient().get(STATUS).status_code in (401, 403)
