import pytest
from django.core.exceptions import ValidationError

from .factories import MemberFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile():
    return MemberFactory.create().profile


def _set_rfid(profile, value):
    profile.rfid = value
    profile.full_clean()


def test_non_numeric_rfid_rejected(profile):
    with pytest.raises(ValidationError):
        _set_rfid(profile, "NA")
    with pytest.raises(ValidationError):
        _set_rfid(profile, "ABC123")
    with pytest.raises(ValidationError):
        _set_rfid(profile, "1234NA")


def test_short_numeric_rfid_accepted(profile):
    _set_rfid(profile, "1")


def test_empty_rfid_accepted(profile):
    _set_rfid(profile, "")  # blank=True


def test_none_rfid_accepted(profile):
    _set_rfid(profile, None)  # null=True


def test_numeric_rfid_accepted(profile):
    _set_rfid(profile, "12345343")  # 8 digits, boundary


def test_rfid_too_long_rejected(profile):
    with pytest.raises(ValidationError):
        _set_rfid(profile, "123456789")  # 9 digits
