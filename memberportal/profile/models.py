from django.db import models, transaction
from django.utils import timezone
from datetime import timedelta, datetime
import pytz
from django.utils.timezone import make_aware
from django.contrib.auth.models import (
    BaseUserManager,
    AbstractBaseUser,
    PermissionsMixin,
)
from django.core.validators import RegexValidator
from django.conf import settings
from constance import config
from api_general.models import SiteSession
from api_admin_tools.models import PaymentPlan
import json
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from services.emails import send_single_email, send_email_to_admin
from services import sms
from sentry_sdk import capture_exception
from django_prometheus.models import ExportModelOperationsMixin

logger = logging.getLogger("profile")

utc = pytz.UTC

LOG_TYPES = (
    ("generic", "Generic Event"),
    ("stripe", "Stripe Event"),
    ("memberbucks", "Memberbucks Updated"),
    ("spacebucks", "Spacebucks Updated"),  # the old internal name for memberbucks
    ("profile", "Member Profile Updated"),
    ("interlock", "Interlock Event"),
    ("door", "Door Event"),
    ("memberbucksdevice", "Memberbucks Event"),
    ("email", "Email Sent"),
    ("sms", "SMS Sent"),
    ("admin", "Admin Action"),
    ("error", "Unhandled Error"),
    ("xero", "Xero Event"),
)


class Log(ExportModelOperationsMixin("log"), models.Model):
    id = models.AutoField(primary_key=True)
    logtype = models.CharField(
        "Type of action/event", choices=LOG_TYPES, max_length=30, default="generic"
    )
    description = models.CharField("Description of action/event", max_length=500)
    data = models.TextField(
        "Extra data for debugging action/event", blank=True, null=True
    )
    date = models.DateTimeField(auto_now_add=True)
    door = models.ForeignKey(
        "access.Doors",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        blank=True,
    )
    interlock = models.ForeignKey(
        "access.Interlock",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        blank=True,
    )
    memberbucks_device = models.ForeignKey(
        "access.MemberbucksDevice",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        blank=True,
    )


class UserEventLog(ExportModelOperationsMixin("user-event-log"), Log):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.description}"


class EventLog(ExportModelOperationsMixin("event-log"), Log):
    def __str__(self):
        if self.door:
            return f"{self.door.name} {self.logtype} log - {self.description}"
        elif self.interlock:
            return f"{self.interlock.name} {self.logtype} log - {self.description}"
        elif self.memberbucks_device:
            return f"{self.memberbucks_device.name} {self.logtype} log - {self.description}"
        else:
            return f"{self.logtype} log - {self.description}"


def log_event(
    description,
    event_type="generic",
    data="",
    door=None,
    interlock=None,
    memberbucks_device=None,
):
    EventLog(
        description=description,
        logtype="generic" if event_type is None else event_type,
        data=data,
        door=door,
        interlock=interlock,
        memberbucks_device=memberbucks_device,
    ).save()


class UserManager(BaseUserManager):
    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD + "__iexact": username})

    def create_user(self, email, password=None, is_superuser=False):
        """
        Creates and saves a User with the given email and password.
        """
        if not email:
            raise ValueError("Users must have an email address")

        user = self.model(email=self.normalize_email(email))

        user.is_superuser = is_superuser
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_staffuser(self, email, password):
        """
        Creates and saves a staff user with the given email and password.
        """
        user = self.create_user(
            email,
            password=password,
        )
        user.staff = True
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password):
        """
        Creates and saves a superuser with the given email and password.
        """
        user = self.create_user(
            email,
            password=password,
            is_superuser=True,
        )
        user.staff = True
        user.admin = True
        user.save(using=self._db)
        return user


class User(ExportModelOperationsMixin("user"), AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(
        verbose_name="email address",
        max_length=255,
        unique=True,
    )
    id = models.AutoField(primary_key=True)
    email_verified = models.BooleanField(default=True)
    password_reset_key = models.UUIDField(default=None, blank=True, null=True)
    password_reset_expire = models.DateTimeField(default=None, blank=True, null=True)
    staff = models.BooleanField(default=False)  # an admin user for the portal
    admin = models.BooleanField(default=False)  # a portal superuser

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # Email & Password are required by default.

    objects = UserManager()

    def __str__(self):
        try:
            return f"{self.get_full_name()} ({self.profile.screen_name}) - {self.email}"
        except:
            return f"(NO PROFILE) - {self.email}"

    def get_short_name(self):
        return self.profile.get_short_name()

    def get_full_name(self):
        return self.profile.get_full_name()

    @property
    def is_staff(self):
        "Is the user a member of staff?"
        return self.staff

    @property
    def is_admin(self):
        "Is the user a admin member?"
        return self.admin

    def log_event(self, description: str, event_type, data=""):
        UserEventLog(
            description=description, logtype=event_type, user=self, data=data
        ).save()

    def __send_email(self, subject, template_vars, template_name=None):
        return send_single_email(
            to_email=self.email,
            subject=subject,
            template_vars=template_vars,
            user=self,
            template_name=template_name,
        )

    def email_link(
        self, subject: str, title: str, message: str, link: str, btn_text: str
    ):
        template_vars = {
            "title": title,
            "message": message,
            "link": link,
            "btn_text": btn_text,
        }

        return self.__send_email(
            subject=subject,
            template_vars=template_vars,
            template_name="email_with_button.html",
        )

    def email_notification(self, subject: str, message: str):
        template_vars = {"title": subject, "message": message}
        return self.__send_email(subject, template_vars=template_vars)

    def email_password_reset(self, link: str):
        template_vars = {"link": link}

        return self.__send_email(
            f"Reset your {config.SITE_OWNER} password",
            template_vars,
            template_name="email_password_reset.html",
        )

    def email_membership_application(self):
        if config.ENABLE_MEMBERSHIP_APPLICATION_USER_EMAIL:
            subject = "Your membership application has been submitted"
            message = "Thanks for submitting your membership application! Your membership application has been submitted and you are now a 'member applicant'. Your membership will be officially accepted shortly, but we have granted site access immediately. You will receive an email confirming that your access card has been enabled. If for some reason your membership is rejected within this period, you will receive an email with further information."

            self.email_notification(subject, message)

        subject = f"A new person just completed signup: {self.profile.get_full_name()}"
        message = f"{self.profile.get_full_name()} just completed all steps required to sign up and now has full membership. Their site access has been enabled."
        template_vars = {"message": message}

        return send_email_to_admin(
            subject, template_vars=template_vars, reply_to=self.email, user=self
        )

    def email_welcome(self):
        cards = (
            config.WELCOME_EMAIL_CARDS
            if config.WELCOME_EMAIL_CARDS
            else config.HOME_PAGE_CARDS
        )
        cards = json.loads(cards)

        subject = f"Welcome to {config.SITE_OWNER}"
        template_vars = {"title": subject, "cards": cards}

        if self.__send_email(
            subject=subject,
            template_vars=template_vars,
            template_name="email_welcome.html",
        ):
            return "Successfully sent welcome email to user. ✉"

        return False

    def email_disable_member_access(self):
        return self.email_notification(
            f"Your {config.SITE_OWNER} site access has been disabled.",
            f"Your access to {config.SITE_OWNER} has been disabled. "
            f"If this is unexpected, please let us know.",
        )

    def email_subscription_ended(self):
        return self.email_notification(
            f"Your {config.SITE_OWNER} site access has been disabled.",
            f"Your access to {config.SITE_OWNER} has been disabled because "
            "your membership subscription has ended. This is usually due to "
            "a failed membership payment. If this is unexpected, please let "
            "us know.",
        )

    def email_enable_member_access(self):
        message = f"Great news {self.profile.first_name}, your {config.SITE_OWNER} site access has been enabled."
        subject = f"Your {config.SITE_OWNER} site access has been enabled."

        return self.email_notification(subject, message)

    def reset_password(self):
        with transaction.atomic():
            self.log_event("Password reset requested", "profile")
            self.password_reset_key = uuid.uuid4()
            self.password_reset_expire = timezone.now() + timedelta(hours=24)
            self.save(update_fields=["password_reset_key", "password_reset_expire"])
            url = (
                f"{config.SITE_URL}/profile/password/reset/"
                f"{self.password_reset_key}"
            )

            def _send_reset_email(user=self, url=url):
                try:
                    user.email_password_reset(url)
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_send_reset_email)

        return True


class CompleteSignupOutcome(str, Enum):
    ACTIVATED = "activated"
    ALREADY_ACTIVE = "already_active"
    AWAITING_PAYMENT = "awaiting_payment"
    REQUIREMENTS_UNMET = "requirements_unmet"
    NO_SUBSCRIPTION = "no_subscription"
    STATE_LOCKED = "state_locked"


class SignupTriggeredBy(str, Enum):
    MEMBER_SELF_SERVE = "member_self_serve"
    SUBSCRIPTION_CREATED = "subscription_created"
    INVOICE_PAID = "invoice_paid"
    ADMIN_OVERRIDE_ACTIVATE = "admin_override_activate"


@dataclass
class CompleteSignupResult:
    outcome: CompleteSignupOutcome
    required_steps: list = field(default_factory=list)


class CancelTriggeredBy(str, Enum):
    MEMBER_SELF_CANCEL = "member_self_cancel"
    ADMIN_OVERRIDE_CANCEL = "admin_override_cancel"
    SUBSCRIPTION_DELETED = "subscription_deleted"


class CompleteCancelOutcome(str, Enum):
    DEACTIVATED = "deactivated"
    STATE_LOCKED = "state_locked"
    SIGNUP_LAPSED = "signup_lapsed"
    ALREADY_DEACTIVATED = "already_deactivated"


@dataclass
class CompleteCancelResult:
    outcome: CompleteCancelOutcome
    previous_state: str = ""


class Profile(ExportModelOperationsMixin("profile"), models.Model):
    STATES = (
        ("noob", "Needs Induction"),
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("accountonly", "Account only"),
    )

    SUBSCRIPTION_STATES = (
        ("inactive", "Inactive"),
        ("active", "Active"),
        ("cancelling", "Cancelling"),
        ("pending", "Pending"),
    )

    class Meta:
        permissions = [
            ("change_staff", "Can change if the user is a staff member or not"),
            ("manage_access", "Can manage a user's access permissions"),
            ("deactivate_member", "Can deactivate or activate a member"),
            ("see_personal_details", "Can see and update a member's personal details"),
            ("manage_memberbucks_balance", "Can see and modify memberbucks balance"),
            ("member_logs", "Can see a members log"),
        ]

    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    digital_id_token = models.UUIDField(
        "Digital ID Token", default=uuid.uuid4, null=True, blank=True
    )
    digital_id_token_expire = models.DateTimeField(
        editable=False, default=datetime.now, null=True, blank=True
    )
    created = models.DateTimeField(editable=False)
    modified = models.DateTimeField()
    screen_name = models.CharField(
        "Screen Name",
        max_length=30,
        blank=True,
        null=True,
        unique=True,
        default=None,
    )
    first_name = models.CharField("First Name", max_length=30)
    last_name = models.CharField("Last Name", max_length=30)
    phone_regex = RegexValidator(
        regex=r"^\+[1-9]\d{1,14}$",
        message="Phone number must be in E.164 format, e.g. +61417123456.",
    )
    phone = models.CharField(validators=[phone_regex], max_length=16, blank=True)
    state = models.CharField(max_length=11, default="noob", choices=STATES)
    vehicle_registration_plate = models.CharField(max_length=30, blank=True, null=True)

    membership_plan = models.ForeignKey(
        PaymentPlan,
        on_delete=models.PROTECT,
        related_name="membership_plan",
        null=True,
        blank=True,
    )

    rfid = models.CharField(
        "RFID Tag", max_length=20, unique=True, null=True, blank=True
    )
    doors = models.ManyToManyField("access.Doors", blank=True)
    interlocks = models.ManyToManyField("access.Interlock", blank=True)
    memberbucks_balance = models.FloatField(default=0.0)
    last_memberbucks_purchase = models.DateTimeField(default=timezone.now)
    must_update_profile = models.BooleanField(default=False)
    exclude_from_email_export = models.BooleanField(default=False)

    last_seen = models.DateTimeField(default=None, blank=True, null=True)
    last_induction = models.DateTimeField(default=None, blank=True, null=True)
    terms_accepted_at = models.DateTimeField(default=None, blank=True, null=True)

    stripe_customer_id = models.CharField(
        max_length=100, blank=True, null=True, unique=True, default=None
    )
    stripe_card_expiry = models.CharField(
        max_length=10, blank=True, null=True, default=""
    )
    stripe_card_last_digits = models.CharField(
        max_length=4, blank=True, null=True, default=""
    )
    stripe_payment_method_id = models.CharField(
        max_length=100, blank=True, null=True, default=""
    )
    stripe_subscription_id = models.CharField(
        max_length=100, blank=True, null=True, default=""
    )
    subscription_status = models.CharField(
        max_length=10, default="inactive", choices=SUBSCRIPTION_STATES
    )
    subscription_first_created = models.DateTimeField(
        default=None, blank=True, null=True, editable=False
    )

    BILLING_METHODS = (
        ("card", "Card"),
        ("invoice", "Invoice"),
    )

    billing_method = models.CharField(
        max_length=10,
        default="card",
        choices=BILLING_METHODS,
    )

    # One-shot guard for the "Signup received, awaiting payment" email
    # sent by CompleteSignup on invoice signups.
    pending_signup_email_sent = models.BooleanField(default=False)

    # Revokes door access without cancelling billing or touching `state`.
    admin_disabled_access = models.BooleanField(default=False)

    # Locks `state` only; `subscription_status` still follows Stripe.
    state_locked = models.BooleanField(default=False)

    def __str__(self):
        return str(self.user)

    def generate_digital_id_token(self):
        self.digital_id_token = uuid.uuid4()
        self.digital_id_token_expire = make_aware(
            datetime.now() + timedelta(minutes=10)
        )
        self.save()

        return self.digital_id_token

    def validate_digital_id_token(self, token: str):
        if make_aware(
            datetime.now()
        ) < self.digital_id_token_expire and self.digital_id_token == uuid.UUID(token):
            return True

        else:
            return False

    def sync_access(self):
        for door in self.doors.all():
            door.sync()

        for interlock in self.interlocks.all():
            interlock.sync()

    def add_default_access(self):
        # Pre-stage default door/interlock access. Idempotent (M2M.add).
        # Safe to call before activation: access.get_tags() filters by
        # state="active", so these rows do not grant access until the
        # member is actually activated.
        from access.models import Doors, Interlock

        for door in Doors.objects.filter(all_members=True):
            self.doors.add(door)
        for interlock in Interlock.objects.filter(all_members=True):
            self.interlocks.add(interlock)

    def remove_default_access(self):
        # Remove pre-staged default-access rows on a cancellation path that
        # bypasses deactivate() (noob / accountonly cancel). Targeted
        # .remove() preserves bespoke admin grants (rows whose
        # Doors/Interlock has all_members=False) — see L15 in BUGS_FOUND.md
        # for why blanket .clear() is the wrong shape.
        from access.models import Doors, Interlock

        self.doors.remove(*Doors.objects.filter(all_members=True))
        self.interlocks.remove(*Interlock.objects.filter(all_members=True))

    def _log_state_lock_refusal(self, triggered_by, action):
        # Four sinks: audit log (admin UI), aggregator (logger), Sentry
        # (alerting), admin email (operator nudge to review).
        name = self.get_full_name()
        triggered_label = getattr(triggered_by, "value", str(triggered_by))

        try:
            self.user.log_event(
                f"state_locked refused {action} (triggered_by={triggered_label}); "
                f"state kept as {self.state}",
                "admin",
            )
        except Exception as e:
            capture_exception(e)

        logger.warning(
            f"state_locked refusal: profile={self.pk} action={action} "
            f"triggered_by={triggered_label} state={self.state}"
        )

        try:
            capture_exception(
                Exception(
                    f"state_locked refusal: {action} blocked "
                    f"(triggered_by={triggered_label}, state={self.state})"
                )
            )
        except Exception as e:
            capture_exception(e)

        subject = f"Locked member {name}: {action} preserved state"
        message = (
            f"{action.capitalize()} for locked member {name} was triggered "
            f"by {triggered_label}. State kept as {self.state}. Review "
            "whether their grandfathered access still applies."
        )
        try:
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": message},
                user=self.user,
                reply_to=self.user.email,
            )
        except Exception as e:
            capture_exception(e)

    def complete_signup(self, triggered_by, request=None):
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=self.pk)
            previous_state = locked.state

            if locked.state == "active":
                return CompleteSignupResult(CompleteSignupOutcome.ALREADY_ACTIVE)

            if (
                locked.state_locked
                and triggered_by != SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE
            ):
                locked._log_state_lock_refusal(triggered_by, "activation")
                return CompleteSignupResult(CompleteSignupOutcome.STATE_LOCKED)

            if triggered_by == SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE:
                # An active member is never locked (the state_locked invariant).
                if locked.state_locked:
                    locked.state_locked = False
                    locked.save(update_fields=["state_locked"])
                locked.add_default_access()
            else:
                if (
                    config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS
                    and locked.subscription_status not in ("active", "pending")
                ):
                    return CompleteSignupResult(CompleteSignupOutcome.NO_SUBSCRIPTION)

                signup_check = locked.can_signup()
                if not signup_check["success"]:
                    return CompleteSignupResult(
                        CompleteSignupOutcome.REQUIREMENTS_UNMET,
                        required_steps=signup_check["requiredSteps"],
                    )

                if locked.subscription_status == "pending":
                    if not locked.pending_signup_email_sent:
                        pending_subject = (
                            "Your signup has been received — awaiting payment"
                        )
                        pending_message = (
                            f"Hi {locked.first_name}, thanks for signing "
                            f"up to {config.SITE_OWNER}! We've received your "
                            "signup and you'll receive an invoice from Stripe "
                            "shortly. Once it's paid, your access will be "
                            "enabled automatically and we'll send you a "
                            "welcome email."
                        )

                        def _on_commit_pending_signup(
                            user=locked.user,
                            subject=pending_subject,
                            message=pending_message,
                        ):
                            try:
                                user.email_notification(subject, message)
                                user.log_event(
                                    "Awaiting-payment email sent for pending invoice signup.",
                                    "email",
                                )
                            except Exception as e:
                                capture_exception(e)

                        transaction.on_commit(_on_commit_pending_signup)

                        # Set pessimistically: if Postmark drops the email we
                        # accept losing it rather than risk a duplicate when
                        # the user re-enters this flow.
                        locked.pending_signup_email_sent = True
                        locked.save(update_fields=["pending_signup_email_sent"])

                    return CompleteSignupResult(CompleteSignupOutcome.AWAITING_PAYMENT)

                locked.add_default_access()

        self.activate(request)
        trigger_label = getattr(triggered_by, "value", str(triggered_by))
        self.user.log_event(
            f"Activated via {trigger_label} (from {previous_state}).",
            "profile",
        )
        return CompleteSignupResult(CompleteSignupOutcome.ACTIVATED)

    def deactivate(self, request=None, on_transition=None, reason="admin"):
        # Lock + re-read state to keep concurrent callers (e.g. Stripe webhook
        # retries racing an admin action) from double-running side effects.
        # External I/O (email/SMS, sync_access) runs after the lock is
        # released so a slow Postmark/Twilio call cannot serialize concurrent
        # webhook deliveries or push the handler past Stripe's 30s timeout.
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=self.pk)
            if locked.state == "inactive":
                return False
            previous_state = locked.state

            if request:
                request.user.log_event(
                    f"{request.user.profile.get_full_name()} deactivated member ({self.get_full_name()}).",
                    "admin",
                )
                self.user.log_event(
                    f"{request.user.profile.get_full_name()} deactivated member.",
                    "admin",
                )
            else:
                self.user.log_event(
                    f"system deactivated member ({self.get_full_name()}).",
                    "profile",
                )

            # update_fields so a stale `self` can't revert concurrent
            # writes to other columns (e.g. webhook clearing stripe_*).
            self.state = "inactive"
            self.save(update_fields=["state"])

        if on_transition is not None:
            try:
                on_transition(previous_state, "inactive")
            except Exception as e:
                capture_exception(e)

        # Each notification is wrapped independently so a single
        # Postmark/Twilio failure does not skip later notifications or
        # sync_access — leaving an "inactive" member with devices still
        # holding their tag is worse than a missed email.
        try:
            if reason == "subscription_ended":
                self.user.email_subscription_ended()
            else:
                self.user.email_disable_member_access()
        except Exception as e:
            capture_exception(e)
        try:
            sms.SMS().send_deactivated_access(self.phone)
        except Exception as e:
            capture_exception(e)
        self.sync_access()
        return True

    def complete_cancel(self, triggered_by, request=None):
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=self.pk)
            previous_state = locked.state

            if previous_state in ("inactive", "accountonly"):
                # accountonly bypasses deactivate(), so drop any pre-staged
                # default-access rows here. inactive has already been
                # through deactivate() and keeps its M2M intentionally
                # (get_tags filters by state).
                if previous_state == "accountonly":
                    locked.remove_default_access()
                return CompleteCancelResult(
                    outcome=CompleteCancelOutcome.ALREADY_DEACTIVATED,
                    previous_state=previous_state,
                )

            if (
                previous_state == "active"
                and locked.state_locked
                and triggered_by != CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL
            ):
                self._log_state_lock_refusal(triggered_by, "cancellation")
                return CompleteCancelResult(
                    outcome=CompleteCancelOutcome.STATE_LOCKED,
                    previous_state=previous_state,
                )

            if previous_state == "noob":
                # noob never goes through deactivate(), so drop any
                # pre-staged default-access rows here.
                locked.remove_default_access()
                if triggered_by == CancelTriggeredBy.SUBSCRIPTION_DELETED:
                    lapsed_subject = "Your membership signup has lapsed"
                    lapsed_message = (
                        "We weren't able to collect your membership payment "
                        "in time, so your pending signup has been cancelled. "
                        "You can sign up again at any time from the member "
                        "portal."
                    )

                    def _on_commit_lapsed(
                        user=locked.user,
                        subject=lapsed_subject,
                        message=lapsed_message,
                    ):
                        try:
                            user.email_notification(subject, message)
                            user.log_event(
                                "Signup-lapsed email sent (subscription deleted before activation).",
                                "email",
                            )
                        except Exception as e:
                            capture_exception(e)

                    transaction.on_commit(_on_commit_lapsed)
                return CompleteCancelResult(
                    outcome=CompleteCancelOutcome.SIGNUP_LAPSED,
                    previous_state=previous_state,
                )

        reason = (
            "subscription_ended"
            if triggered_by == CancelTriggeredBy.SUBSCRIPTION_DELETED
            else "admin"
        )
        self.deactivate(request, reason=reason)
        trigger_label = getattr(triggered_by, "value", str(triggered_by))
        self.user.log_event(
            f"Cancelled via {trigger_label}.",
            "profile",
        )
        return CompleteCancelResult(
            outcome=CompleteCancelOutcome.DEACTIVATED,
            previous_state=previous_state,
        )

    def set_admin_disabled_access(self, disabled, request=None):
        # Admin-only toggle for the access pause (orthogonal to state /
        # subscription).
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=self.pk)
            was_disabled = locked.admin_disabled_access

            if locked.admin_disabled_access != disabled:
                locked.admin_disabled_access = disabled
                locked.save(update_fields=["admin_disabled_access"])

            if request and was_disabled != disabled:
                action = "paused" if disabled else "resumed"
                request.user.log_event(
                    f"{request.user.profile.get_full_name()} {action} access "
                    f"for {self.get_full_name()}.",
                    "admin",
                )
                self.user.log_event(f"Access {action} by admin.", "admin")

        if was_disabled == disabled:
            return

        # Push the updated tag list to devices and notify the member — but
        # only when their effective access actually changed (state="active").
        # For non-active members, the flag is inert and notifying about an
        # access change they never had would be misleading.
        self.sync_access()

        if self.state != "active":
            return

        if disabled:
            try:
                self.user.email_disable_member_access()
            except Exception as e:
                capture_exception(e)
            try:
                sms.SMS().send_deactivated_access(self.phone)
            except Exception as e:
                capture_exception(e)
        else:
            try:
                self.user.email_enable_member_access()
            except Exception as e:
                capture_exception(e)
            try:
                sms.SMS().send_activated_access(self.phone)
            except Exception as e:
                capture_exception(e)

    def set_state_locked(self, locked, request=None):
        # Returns False if locking was refused; unlocking always succeeds.
        with transaction.atomic():
            profile = Profile.objects.select_for_update().get(pk=self.pk)

            if locked and (
                profile.state == "active" or profile.subscription_status != "inactive"
            ):
                return False

            if profile.state_locked == locked:
                self.state_locked = locked
                return True

            profile.state_locked = locked
            profile.save(update_fields=["state_locked"])

            action = "locked" if locked else "unlocked"
            if request:
                request.user.log_event(
                    f"{request.user.profile.get_full_name()} {action} the "
                    f"account state for {self.get_full_name()}.",
                    "admin",
                )
            self.user.log_event(f"Account state {action} by admin.", "admin")

        self.state_locked = locked
        return True

    def activate(self, request=None, on_transition=None):
        # Lock + re-read state to keep concurrent callers (e.g. CompleteSignup
        # racing the invoice.paid webhook) from double-running side effects.
        # External I/O (email/SMS, sync_access) runs after the lock is
        # released — see deactivate() for the rationale.
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=self.pk)
            if locked.state == "active":
                return False
            previous_state = locked.state

            if request:
                request.user.log_event(
                    f"{request.user.profile.get_full_name()} activated member ({self.get_full_name()}).",
                    "admin",
                )
                self.user.log_event(
                    f"{request.user.profile.get_full_name()} activated member.",
                    "admin",
                )
            else:
                self.user.log_event(
                    f"system activated member ({self.get_full_name()})",
                    "profile",
                )

            # See deactivate() for why update_fields is required here.
            self.state = "active"
            self.save(update_fields=["state"])

        # Fires only for the caller whose lock won the state flip — gives
        # callers a single-shot hook for trigger-specific side effects
        # (e.g. complete_signup(INVOICE_PAID)'s "payment received" email).
        if on_transition is not None:
            try:
                on_transition(previous_state, "active")
            except Exception as e:
                capture_exception(e)

        # Each notification wrapped independently so a single Postmark/Twilio
        # failure doesn't skip later steps — leaving an "active" member
        # whose devices were never told their tag is worse than a missed
        # email.
        if previous_state == "noob":
            try:
                self.user.email_membership_application()
            except Exception as e:
                capture_exception(e)
            try:
                self.user.email_welcome()
            except Exception as e:
                capture_exception(e)
        else:
            try:
                sms.SMS().send_activated_access(self.phone)
            except Exception as e:
                capture_exception(e)
            try:
                self.user.email_enable_member_access()
            except Exception as e:
                capture_exception(e)

        self.sync_access()
        return True

    def set_account_only(self):
        self.state = "accountonly"
        self.save()

    def email_profile_to(self, to_email: str):
        message = (
            f"{self.get_full_name()} has just signed up on the portal."
            f"Their email is {self.user.email}."
        )
        template_vars = {"title": "New member signup", "message": message}
        subject = "A new member signed up! ({})".format(self.get_full_name())

        return send_single_email(
            to_email,
            subject,
            template_vars=template_vars,
            user=self.user,
            reply_to=self.user.email,
        )

    def get_logs(self):
        return UserEventLog.objects.filter(user=self.user)

    def get_full_name(self):
        return self.first_name + " " + self.last_name

    def get_short_name(self):
        return self.first_name

    def update_last_seen(self):
        # update_fields so a stale `self` can't revert concurrent writes.
        self.last_seen = timezone.now()
        return self.save(update_fields=["last_seen"])

    def update_last_induction(self):
        # update_fields so a stale `self` can't revert concurrent writes.
        self.last_induction = timezone.now()
        return self.save(update_fields=["last_induction"])

    def update_terms_accepted_at(self):
        # update_fields so a stale `self` can't revert concurrent writes.
        self.terms_accepted_at = timezone.now()
        return self.save(update_fields=["terms_accepted_at"])

    def is_signed_into_site(self):
        sessions = SiteSession.objects.filter(user=self.user, signout_date=None)

        return True if len(sessions) else False

    @property
    def signup_stage(self):
        # Single source of truth for which signup view the frontend renders.
        if self.state_locked and self.state != "active":
            return "locked"
        if self.state == "accountonly":
            return "account_only"
        if self.state == "active":
            return "managed"
        if self.state == "inactive":
            return "lapsed"
        # state == "noob" below
        if not self.membership_plan:
            return "needs_plan"
        # Required steps before payment status: an invoice signup goes
        # "pending" at billing time, i.e. before terms/induction/access card.
        if not self.can_signup()["success"]:
            return "needs_requirements"
        if self.subscription_status == "pending":
            return "awaiting_payment"
        return "needs_requirements"

    def get_basic_profile(self):
        """
        Returns a user's profile with a basic amount of info.
        :return: {}
        """
        return {
            "id": self.user.id,
            "admin": self.user.is_staff,
            "email": self.user.email,
            "excludeFromEmailExport": self.exclude_from_email_export,
            "registrationDate": self.created.strftime("%m/%d/%Y, %H:%M:%S"),
            "lastUpdatedProfile": self.modified.strftime("%m/%d/%Y, %H:%M:%S"),
            "screenName": self.screen_name,
            "name": {
                "first": self.first_name,
                "last": self.last_name,
                "full": self.get_full_name(),
            },
            "phone": self.phone,
            "state": self.state,
            "vehicleRegistrationPlate": self.vehicle_registration_plate,
            "rfid": self.rfid,
            "memberBucks": {
                "balance": self.memberbucks_balance,
                "lastPurchase": (
                    self.last_memberbucks_purchase.strftime("%m/%d/%Y, %H:%M:%S")
                    if self.last_memberbucks_purchase
                    else None
                ),
            },
            "updateProfileRequired": self.must_update_profile,
            "lastSeen": (
                self.last_seen.strftime("%m/%d/%Y, %H:%M:%S")
                if self.last_seen
                else None
            ),
            "lastInduction": (
                self.last_induction.strftime("%m/%d/%Y, %H:%M:%S")
                if self.last_induction
                else None
            ),
            "termsAcceptedAt": (
                self.terms_accepted_at.strftime("%m/%d/%Y, %H:%M:%S")
                if self.terms_accepted_at
                else None
            ),
            "stripe": {
                "cardExpiry": self.stripe_card_expiry,
                "last4": self.stripe_card_last_digits,
            },
            "subscriptionStatus": self.subscription_status,
            "stateLocked": self.state_locked,
            "adminDisabledAccess": self.admin_disabled_access,
        }

    def get_access_permissions(self, ignore_user_state=False):
        """
        returns a dictionary of the user's access permissions
        :return:
        """
        doors = []
        interlocks = []

        user_active = self.state == "active"

        if ignore_user_state:
            user_active = True

        from access.models import Doors, Interlock

        for door in Doors.objects.all():
            if door.hidden:
                continue

            if door in self.doors.all() and user_active:
                doors.append(
                    {
                        "name": door.name,
                        "access": True,
                        "id": door.id,
                        "locked_out": door.locked_out,
                        "offline": door.get_unavailable(),
                    }
                )

            else:
                doors.append(
                    {
                        "name": door.name,
                        "access": False,
                        "id": door.id,
                        "locked_out": door.locked_out,
                        "offline": door.get_unavailable(),
                    }
                )

        for interlock in Interlock.objects.all():
            if interlock.hidden:
                continue

            if interlock in self.interlocks.all() and user_active:
                interlocks.append(
                    {
                        "name": interlock.name,
                        "access": True,
                        "id": interlock.id,
                        "locked_out": interlock.locked_out,
                        "offline": interlock.get_unavailable(),
                    }
                )

            else:
                interlocks.append(
                    {
                        "name": interlock.name,
                        "access": False,
                        "id": interlock.id,
                        "locked_out": interlock.locked_out,
                        "offline": interlock.get_unavailable(),
                    }
                )

        return {"doors": doors, "interlocks": interlocks}

    def can_signup(self):
        """Checks if a member can signup. Returns {"success": True/False, "reasons": [String<list of reasons>]}"""
        required_steps = []

        try:
            terms_cards = json.loads(config.TERMS_ACCEPTANCE_CARDS)
        except (ValueError, TypeError):
            terms_cards = []

        if terms_cards and self.terms_accepted_at is None:
            required_steps.append("termsAcceptance")

        if (
            config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS
            and self.subscription_status not in ("active", "pending")
        ):
            required_steps.append("subscription")

        # First-time induction is always required when an induction
        # provider is enabled. MAX_INDUCTION_DAYS only controls *re*-
        # induction: 0 disables the recurring requirement but does not
        # let first-timers skip.
        induction_enabled = (
            config.CANVAS_INDUCTION_ENABLED or config.MOODLE_INDUCTION_ENABLED
        )
        last_inducted = self.last_induction

        if induction_enabled and last_inducted is None:
            required_steps.append("induction")
        elif induction_enabled and config.MAX_INDUCTION_DAYS > 0:
            furthest_previous_date = timezone.now() - timedelta(
                days=config.MAX_INDUCTION_DAYS
            )
            if last_inducted < furthest_previous_date:
                required_steps.append("induction")

        # check if they have an RFID card assigned (only if required by config)
        if config.REQUIRE_ACCESS_CARD and not self.rfid:
            required_steps.append("accessCard")

        if len(required_steps):
            return {"success": False, "requiredSteps": required_steps}

        else:
            return {"success": True, "requiredSteps": []}

    def save(self, *args, **kwargs):
        """On save, update timestamps"""
        if not self.id:
            self.created = timezone.now()
        self.modified = timezone.now()
        # Mirror Django's auto_now behavior: when the caller restricts
        # the UPDATE to specific columns via update_fields, ensure
        # `modified` rides along — otherwise targeted writes (e.g.
        # save(update_fields=["state"])) would leave the timestamp
        # stale.
        # An explicitly-empty update_fields means "save nothing" — don't
        # turn it into a modified-only UPDATE.
        update_fields = kwargs.get("update_fields")
        if update_fields and "modified" not in update_fields:
            kwargs["update_fields"] = list(update_fields) + ["modified"]
        return super(Profile, self).save(*args, **kwargs)
