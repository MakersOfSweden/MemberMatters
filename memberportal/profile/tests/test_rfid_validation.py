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
