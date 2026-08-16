"""Profile.can_signup — the gate complete_signup delegates to.

Everything here is driven by runtime (django-constance) config rather than
code, so the tests are organised by config axis: terms, subscription,
induction, access card. The `override_config` marker comes from the constance
pytest plugin, which registers itself via an entry point.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


# Constance defaults that make can_signup pass, so each test below can switch
# on exactly the one axis it is about. Note that the shipped defaults are NOT
# all-off: MOODLE_INDUCTION_ENABLED and REQUIRE_ACCESS_CARD both default True.
NO_REQUIREMENTS = {
    "TERMS_ACCEPTANCE_CARDS": "[]",
    "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": False,
    "MOODLE_INDUCTION_ENABLED": False,
    "CANVAS_INDUCTION_ENABLED": False,
    "REQUIRE_ACCESS_CARD": False,
}

TERMS_CARDS = '[{"icon": "mdi-check", "title": "Rules", "body_html": "<p>Hi</p>"}]'


def only(**overrides):
    """override_config with every requirement off except the ones named."""
    return pytest.mark.override_config(**{**NO_REQUIREMENTS, **overrides})


@only()
def test_no_requirements_configured_allows_signup():
    result = ProfileFactory().can_signup()

    assert result == {"success": True, "requiredSteps": []}


def test_shipped_defaults_require_induction_and_access_card():
    # Pinned deliberately: a fresh install requires both, and the ordering of
    # requiredSteps drives which step the signup wizard opens on.
    result = ProfileFactory().can_signup()

    assert result["success"] is False
    assert result["requiredSteps"] == ["induction", "accessCard"]


class TestTermsAcceptance:
    @only(TERMS_ACCEPTANCE_CARDS=TERMS_CARDS)
    def test_required_when_cards_configured_and_not_accepted(self):
        result = ProfileFactory().can_signup()

        assert result["requiredSteps"] == ["termsAcceptance"]

    @only(TERMS_ACCEPTANCE_CARDS=TERMS_CARDS)
    def test_satisfied_once_accepted(self):
        profile = ProfileFactory(terms_accepted_at=timezone.now())

        assert profile.can_signup()["success"] is True

    @only(TERMS_ACCEPTANCE_CARDS="not json")
    def test_malformed_config_is_treated_as_no_cards(self):
        # can_signup swallows the JSON error rather than 500ing the signup
        # flow — an operator typo must not lock every member out of signup.
        assert ProfileFactory().can_signup()["success"] is True


class TestSubscription:
    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_required_when_stripe_enabled_and_subscription_inactive(self):
        result = ProfileFactory().can_signup()

        assert result["requiredSteps"] == ["subscription"]

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    @pytest.mark.parametrize("status", ["active", "pending"])
    def test_active_and_pending_both_satisfy_it(self, status):
        # "pending" counts: an invoice signup is allowed through to the
        # awaiting-payment branch rather than being blocked here.
        profile = ProfileFactory(subscription_status=status)

        assert profile.can_signup()["success"] is True

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_cancelling_does_not_satisfy_it(self):
        profile = ProfileFactory(subscription_cancelling=True)

        assert profile.can_signup()["requiredSteps"] == ["subscription"]

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False)
    def test_not_required_when_stripe_is_disabled(self):
        assert ProfileFactory().can_signup()["success"] is True


class TestInduction:
    @only(MOODLE_INDUCTION_ENABLED=True)
    def test_required_for_a_member_who_has_never_been_inducted(self):
        result = ProfileFactory(last_induction=None).can_signup()

        assert result["requiredSteps"] == ["induction"]

    @only(CANVAS_INDUCTION_ENABLED=True)
    def test_canvas_gates_it_the_same_way_as_moodle(self):
        result = ProfileFactory(last_induction=None).can_signup()

        assert result["requiredSteps"] == ["induction"]

    @only(MOODLE_INDUCTION_ENABLED=True, MAX_INDUCTION_DAYS=180)
    def test_recent_induction_satisfies_it(self):
        profile = ProfileFactory(last_induction=timezone.now() - timedelta(days=10))

        assert profile.can_signup()["success"] is True

    @only(MOODLE_INDUCTION_ENABLED=True, MAX_INDUCTION_DAYS=180)
    def test_stale_induction_requires_re_induction(self):
        profile = ProfileFactory(last_induction=timezone.now() - timedelta(days=181))

        assert profile.can_signup()["requiredSteps"] == ["induction"]

    @only(MOODLE_INDUCTION_ENABLED=True, MAX_INDUCTION_DAYS=0)
    def test_max_induction_days_zero_disables_re_induction_only(self):
        # 0 means "never expire an induction", not "induction is optional".
        # An arbitrarily old induction still counts...
        inducted = ProfileFactory(last_induction=timezone.now() - timedelta(days=9999))
        assert inducted.can_signup()["success"] is True

        # ...but a member who has never been inducted is still blocked.
        never = ProfileFactory(last_induction=None)
        assert never.can_signup()["requiredSteps"] == ["induction"]

    @only(MOODLE_INDUCTION_ENABLED=False, CANVAS_INDUCTION_ENABLED=False)
    def test_not_required_when_no_provider_is_enabled(self):
        assert ProfileFactory(last_induction=None).can_signup()["success"] is True


class TestAccessCard:
    @only(REQUIRE_ACCESS_CARD=True)
    def test_required_when_configured_and_no_tag_assigned(self):
        result = ProfileFactory(rfid=None).can_signup()

        assert result["requiredSteps"] == ["accessCard"]

    @only(REQUIRE_ACCESS_CARD=True)
    def test_satisfied_by_an_assigned_tag(self):
        profile = ProfileFactory(with_rfid=True)

        assert profile.can_signup()["success"] is True

    @only(REQUIRE_ACCESS_CARD=False)
    def test_not_required_when_disabled(self):
        assert ProfileFactory(rfid=None).can_signup()["success"] is True


@pytest.mark.override_config(
    TERMS_ACCEPTANCE_CARDS=TERMS_CARDS,
    ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True,
    MOODLE_INDUCTION_ENABLED=True,
    CANVAS_INDUCTION_ENABLED=False,
    REQUIRE_ACCESS_CARD=True,
)
def test_all_requirements_are_reported_together_and_in_order():
    # The frontend signup wizard walks requiredSteps in order, so the sequence
    # is part of the contract, not an implementation detail.
    result = ProfileFactory(
        terms_accepted_at=None, last_induction=None, rfid=None
    ).can_signup()

    assert result["success"] is False
    assert result["requiredSteps"] == [
        "termsAcceptance",
        "subscription",
        "induction",
        "accessCard",
    ]
