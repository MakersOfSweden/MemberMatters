"""No SMS is sent while the phone field is hidden.

A hidden field's stored data is kept but not used, so a number stored before
the field was hidden gets no swipe alerts, access notices or admin messages.
"""

import pytest
from constance.test import override_config
from django.urls import reverse

from profile.models import UserEventLog
from services import sms
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PHONE = "+61417000001"


def test_an_sms_is_sent_while_the_phone_is_collected(sms_outbox):
    profile = ProfileFactory(phone=PHONE)

    sms.SMS().send_inactive_swipe_alert(PHONE, portal_user_recipient=profile.user)

    assert [to for to, _body in sms_outbox] == [PHONE]


@override_config(PROFILE_FIELD_PHONE="hidden")
@pytest.mark.parametrize(
    "send",
    [
        "send_inactive_swipe_alert",
        "send_locked_out_swipe_alert",
        "send_deactivated_access",
        "send_activated_access",
    ],
)
def test_no_sms_is_sent_while_the_phone_is_hidden(sms_outbox, send):
    profile = ProfileFactory(phone=PHONE)

    getattr(sms.SMS(), send)(PHONE, portal_user_recipient=profile.user)

    assert sms_outbox == []
    assert UserEventLog.objects.filter(
        user=profile.user,
        description="Skipped sending SMS because the phone field is hidden",
    ).exists()


@override_config(SMS_ENABLE=True, PROFILE_FIELD_PHONE="hidden")
def test_an_admin_cannot_send_an_sms_while_the_phone_is_hidden(
    admin_client, sms_outbox, monkeypatch
):
    # SMS_ENABLE builds a Twilio client; none is needed to refuse.
    monkeypatch.setattr(sms, "Client", lambda *args: None)
    profile = ProfileFactory(phone=PHONE)

    response = admin_client.post(
        reverse("MemberSendSms", args=[profile.user.id]),
        {"smsBody": "Hello"},
        format="json",
    )

    assert response.status_code == 400
    assert sms_outbox == []
