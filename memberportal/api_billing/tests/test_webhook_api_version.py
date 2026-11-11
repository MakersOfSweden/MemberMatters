"""Webhook events are only accepted in the Stripe API majors MemberMatters
supports, and everything else is rejected loudly.

A rejected event must leave no trace in the dedup table, so that Stripe's
retries can still be processed if MemberMatters is updated to accept the
version within the three days Stripe keeps retrying.
"""

import pytest
from django.conf import settings

from api_billing.models import ProcessedStripeEvent
from api_billing.stripe_utils import api_version_major

from .conftest import build_event, build_invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def sentry(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "api_billing.views.capture_message",
        lambda message, **kwargs: sent.append((message, kwargs)),
    )
    return sent


def subjects(outbox):
    return [message["Subject"] for message in outbox]


def paid(api_version, event_id="evt_1"):
    event = build_event(
        "invoice.paid",
        build_invoice("basil"),
        event_id=event_id,
        api_version=api_version,
    )
    if api_version is None:
        del event["api_version"]
    return event


def test_the_request_version_is_one_of_at_most_two_accepted_majors():
    # The version MemberMatters is on, plus at most one newer to move to.
    majors = settings.STRIPE_WEBHOOK_API_MAJORS
    assert 1 <= len(majors) <= 2
    assert api_version_major(settings.STRIPE_API_VERSION) == majors[0]


@pytest.mark.parametrize(
    "version, major",
    [
        ("2025-09-30.clover", "clover"),
        ("2026-02-25.clover", "clover"),
        ("2024-04-10", None),
        ("", None),
        (None, None),
    ],
)
def test_the_major_is_the_named_release(version, major):
    assert api_version_major(version) == major


@pytest.mark.parametrize(
    "version", ["2025-09-30.clover", "2026-02-25.clover", "2026-03-25.dahlia"]
)
def test_any_version_of_an_accepted_major_is_processed(
    post_webhook, stripe_event, subscribed_member, sentry, outbox, version
):
    stripe_event(event=paid(version))

    response = post_webhook()

    assert response.status_code == 200
    assert ProcessedStripeEvent.objects.filter(event_id="evt_1").exists()
    assert sentry == []


@pytest.mark.parametrize(
    "version",
    ["2024-04-10", "2025-03-31.basil", "2026-09-30.endive", None],
    ids=["unnamed", "older-major", "newer-major", "missing"],
)
def test_any_other_version_is_rejected_and_not_recorded(
    post_webhook, stripe_event, subscribed_member, sentry, version
):
    stripe_event(event=paid(version))

    response = post_webhook()

    assert response.status_code == 400
    assert f"API version {version}" in response.data["error"]
    assert "clover and dahlia" in response.data["error"]
    assert not ProcessedStripeEvent.objects.exists()
    subscribed_member.refresh_from_db()
    assert subscribed_member.state == "noob"


def test_a_rejection_is_logged_and_sent_to_sentry(
    post_webhook, stripe_event, subscribed_member, sentry, caplog
):
    stripe_event(event=paid("2024-04-10"))

    post_webhook()

    [(message, kwargs)] = sentry
    assert kwargs == {"level": "error"}
    assert "evt_1 (invoice.paid)" in message
    assert any(
        record.levelname == "ERROR" and record.message == message
        for record in caplog.records
    )


def test_the_admin_is_emailed_once_per_version(
    post_webhook, stripe_event, subscribed_member, sentry, outbox
):
    for event_id, version in [
        ("evt_1", "2024-04-10"),
        ("evt_2", "2024-04-10"),
        ("evt_3", "2025-03-31.basil"),
    ]:
        stripe_event(event=paid(version, event_id=event_id))
        post_webhook()

    assert subjects(outbox) == [
        "Action Required: Stripe webhooks rejected (API version 2024-04-10)",
        "Action Required: Stripe webhooks rejected (API version 2025-03-31.basil)",
    ]
    # Every rejection still reaches Sentry.
    assert len(sentry) == 3


def test_an_event_type_membermatters_ignores_is_not_an_alarm(
    post_webhook, stripe_event, sentry, outbox
):
    stripe_event(event=build_event("charge.refunded", {}, api_version="2024-04-10"))

    response = post_webhook()

    assert response.status_code == 200
    assert sentry == []
    assert outbox == []


def test_a_forged_event_is_not_an_alarm(post_webhook, stripe_event, sentry, outbox):
    stripe_event(exc=ValueError("bad signature"))

    post_webhook()

    assert sentry == []
    assert outbox == []
