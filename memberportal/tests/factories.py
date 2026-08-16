"""Shared model factories.

Kept in one package rather than per-app because the models cross app
boundaries: a Profile needs a User from `profile`, and the default-access
assertions need Doors/Interlocks from `access`.

Deliberately *not* built on `fixtures/initial.json` — that file is the
production seed data, and coupling tests to it makes it un-editable.
"""

import factory
from django.contrib.auth import get_user_model

from access.models import Doors, Interlock
from profile.models import Profile

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """A bare User with no Profile — use ProfileFactory for a real member."""

    class Meta:
        model = User

    # Every unique column gets a Sequence. `email` is unique, so a fixed value
    # would make the second instance in any test blow up on the constraint.
    email = factory.Sequence(lambda n: f"member{n}@example.com")
    password = "test-password"

    class Params:
        staff_user = factory.Trait(staff=True)
        admin_user = factory.Trait(staff=True, admin=True)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Route through the real manager so password hashing and the
        # normalize_email() call stay in the code path under test. The manager
        # signature only accepts email/password/is_superuser, so anything else
        # is applied afterwards.
        password = kwargs.pop("password", None)
        email = kwargs.pop("email")
        is_superuser = kwargs.pop("is_superuser", False)

        user = model_class.objects.create_user(
            email, password=password, is_superuser=is_superuser
        )

        for field, value in kwargs.items():
            setattr(user, field, value)
        if kwargs:
            user.save(update_fields=list(kwargs))

        return user


class ProfileFactory(factory.django.DjangoModelFactory):
    """A member: a User plus their Profile. Defaults to a fresh 'noob'."""

    class Meta:
        model = Profile

    user = factory.SubFactory(UserFactory)

    # screen_name is unique (profile/migrations/0022_screen_name_unique.py), so
    # this must be a Sequence too. A hardcoded value only survives until a test
    # needs a second member.
    screen_name = factory.Sequence(lambda n: f"member{n}")
    first_name = "Test"
    last_name = factory.Sequence(lambda n: f"Member{n}")
    # Valid E.164, so full_clean() passes for tests that call it.
    phone = factory.Sequence(lambda n: f"+61417{n:06d}")

    # rfid is unique but nullable; NULLs don't collide, so the default is None
    # and only the `with_rfid` trait allocates a tag.
    rfid = None

    class Params:
        # Membership states, matching Profile.STATES.
        active = factory.Trait(state="active")
        inactive = factory.Trait(state="inactive")
        accountonly = factory.Trait(state="accountonly")

        # Subscription states, matching Profile.SUBSCRIPTION_STATES. Kept
        # separate from `state` because the two are genuinely independent —
        # that independence is most of what the signup state machine encodes.
        subscription_active = factory.Trait(subscription_status="active")
        subscription_pending = factory.Trait(subscription_status="pending")
        subscription_cancelling = factory.Trait(subscription_status="cancelling")

        # RFID tags are numeric strings; keep them inside the 20-char column.
        with_rfid = factory.Trait(rfid=factory.Sequence(lambda n: str(1000000 + n)))


class DoorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Doors

    name = factory.Sequence(lambda n: f"Door {n}")
    description = "Test door"
    # Unique, and the value device commands are addressed to: sync/lock/unlock
    # group_send to `serial_number`, and skip entirely when it is falsy.
    serial_number = factory.Sequence(lambda n: f"door-serial-{n}")
    authorised = True


class InterlockFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Interlock

    name = factory.Sequence(lambda n: f"Interlock {n}")
    description = "Test interlock"
    serial_number = factory.Sequence(lambda n: f"interlock-serial-{n}")
    authorised = True
