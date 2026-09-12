"""Profile.signup_stage — the single source of truth for the signup wizard.

The frontend renders whichever signup view this returns, so every branch is a
screen a member can land on and the mapping is part of the contract. The
branches are ordered, and the order matters more than it looks: `locked` is
tested before `accountonly`, and `active` before `inactive`.

Driven by the same runtime config as can_signup, which this delegates to.

It is a property, not a method — reading it runs a can_signup() query.
"""

import pytest

from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db


NO_REQUIREMENTS = {
    "TERMS_ACCEPTANCE_CARDS": "[]",
    "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": False,
    "MOODLE_INDUCTION_ENABLED": False,
    "CANVAS_INDUCTION_ENABLED": False,
    "REQUIRE_ACCESS_CARD": False,
}


def only(**overrides):
    return pytest.mark.override_config(**{**NO_REQUIREMENTS, **overrides})


class TestTerminalStates:
    """States that short-circuit before the noob signup funnel is consulted."""

    @only()
    @pytest.mark.parametrize("state", ["noob", "inactive", "accountonly"])
    def test_a_locked_member_reports_locked_whatever_their_state(self, state):
        profile = ProfileFactory(state=state, state_locked=True)

        assert profile.signup_stage == "locked"

    @only()
    def test_an_active_member_is_managed_even_when_locked(self):
        # The guard is `state_locked and state != "active"`, so the lock is
        # invisible here for an active member. Pinned as defence in depth:
        # set_state_locked refuses to produce this combination, but a row that
        # predates the invariant must still render as a managed member.
        profile = ProfileFactory(active=True, state_locked=True)

        assert profile.signup_stage == "managed"

    @only()
    def test_an_account_only_member(self):
        profile = ProfileFactory(accountonly=True)

        assert profile.signup_stage == "account_only"

    @only()
    def test_an_active_member_is_managed(self):
        profile = ProfileFactory(active=True)

        assert profile.signup_stage == "managed"

    @only()
    def test_an_inactive_member_has_lapsed(self):
        profile = ProfileFactory(inactive=True)

        assert profile.signup_stage == "lapsed"


class TestTheNoobFunnel:
    """The branches a member walks while signing up."""

    @only()
    def test_no_plan_chosen_yet(self):
        profile = ProfileFactory(membership_plan=None)

        assert profile.signup_stage == "needs_plan"

    @only(REQUIRE_ACCESS_CARD=True)
    def test_a_plan_but_unmet_requirements(self):
        profile = ProfileFactory(membership_plan=PaymentPlanFactory(), rfid=None)

        assert profile.signup_stage == "needs_requirements"

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True)
    def test_an_invoice_signup_waits_for_payment(self):
        # An invoice signup goes "pending" at billing time — before terms,
        # induction and access card — so this branch sits after can_signup
        # rather than before it.
        profile = ProfileFactory(
            membership_plan=PaymentPlanFactory(), subscription_pending=True
        )

        assert profile.signup_stage == "awaiting_payment"

    @only(ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=True, REQUIRE_ACCESS_CARD=True)
    def test_unmet_requirements_outrank_a_pending_payment(self):
        # The ordering the source comment defends: an invoice signup goes
        # "pending" at billing time, before terms/induction/access card, so a
        # member can be both awaiting payment and short of requirements. The
        # requirements screen wins — swapping the two branches is otherwise
        # invisible, since no other test has a member in both positions.
        profile = ProfileFactory(
            membership_plan=PaymentPlanFactory(), subscription_pending=True, rfid=None
        )

        assert profile.signup_stage == "needs_requirements"

    @only()
    def test_everything_satisfied_still_falls_through_to_needs_requirements(self):
        # Current behaviour, pinned rather than endorsed: with a plan chosen,
        # every requirement met and no pending subscription, the member is
        # sent back to the requirements screen with nothing left to do.
        # It is the function's catch-all return, and in practice a member in
        # this position has usually already been activated by complete_signup
        # (making them "managed"), so the screen is rarely reached.
        profile = ProfileFactory(membership_plan=PaymentPlanFactory())

        assert profile.can_signup()["success"] is True
        assert profile.signup_stage == "needs_requirements"


class TestAccountOnly:
    """Profile.set_account_only — the offboarding transition.

    Downgrades a member to an account with no site access. Unlike activate()
    and deactivate(), it writes with a bare save() rather than
    save(update_fields=[...]), so it persists every field on the in-memory
    instance — pinned below because those two are explicit that update_fields
    is what stops a stale `self` reverting concurrent writes.
    """

    @only()
    def test_it_moves_the_member_to_accountonly(self):
        profile = ProfileFactory(active=True)

        profile.set_account_only()

        profile.refresh_from_db()
        assert profile.state == "accountonly"

    @only()
    def test_it_writes_the_whole_instance_not_just_the_state(self):
        profile = ProfileFactory(active=True)
        profile.first_name = "Renamed"  # unsaved, unrelated to the transition

        profile.set_account_only()

        profile.refresh_from_db()
        assert profile.first_name == "Renamed"

    @only()
    def test_the_member_is_reported_as_account_only_afterwards(self):
        profile = ProfileFactory(active=True)

        profile.set_account_only()

        assert profile.signup_stage == "account_only"
