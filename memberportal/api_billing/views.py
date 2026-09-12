from asgiref.sync import sync_to_async
from django.http import HttpRequest

from profile.models import (
    Profile,
    CompleteSignupOutcome,
    CompleteSignupResult,
    SignupTriggeredBy,
    CancelTriggeredBy,
)
from api_admin_tools.models import *
from .models import ProcessedStripeEvent
from .webhook_handlers import (
    HANDLERS,
    EventScope,
    WebhookContext,
    classify_event_scope,
    handle_orphan_invoice_paid,
)

from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

import stripe
import logging
import uuid
from services.canvas import Canvas
from services.moodle_integration import (
    moodle_get_course_activity_completion_status,
    moodle_get_user_from_email,
)
from services.emails import send_email_to_admin
from constance import config
from django.db import transaction, IntegrityError
from django.db.utils import OperationalError
from django.shortcuts import get_object_or_404
from sentry_sdk import capture_exception

logger = logging.getLogger("billing")


def ensure_stripe_customer(user):
    """
    Ensures a Stripe customer exists for the given user, creating one if needed.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    with transaction.atomic():
        # Lock so concurrent signups don't create duplicate Stripe customers.
        profile = Profile.objects.select_for_update().get(pk=user.profile.pk)

        if profile.stripe_customer_id:
            try:
                customer = stripe.Customer.retrieve(profile.stripe_customer_id)
                if not customer.get("deleted"):
                    user.profile.stripe_customer_id = profile.stripe_customer_id
                    return True, None
            except stripe.error.InvalidRequestError:
                profile.stripe_customer_id = None
                profile.save(update_fields=["stripe_customer_id"])

        try:
            user.log_event("Attempting to create stripe customer.", "stripe")
            customer = stripe.Customer.create(
                email=user.email,
                name=profile.get_full_name(),
                phone=profile.phone,
            )
            profile.stripe_customer_id = customer.id
            profile.save(update_fields=["stripe_customer_id"])
            # Mirror to caller's instance (read directly downstream).
            user.profile.stripe_customer_id = customer.id
            user.log_event(
                f"Created stripe customer {profile.get_full_name()} (Stripe ID: {customer.id}).",
                "stripe",
            )
            return True, None
        except stripe.error.StripeError as e:
            capture_exception(e)
            user.log_event("Error while creating stripe customer.", "stripe", str(e))
            return False, "billing.stripeError"


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
        except OperationalError as error:
            capture_exception(error)


class MemberBucksAddCard(StripeAPIView):
    """
    get: gets the client secret used to add new card details.
    post: saves the customers card details.
    """

    def get(self, request):
        ok, err = ensure_stripe_customer(request.user)
        if not ok:
            return Response(
                {"success": False, "message": err},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            intent = stripe.SetupIntent.create(
                customer=request.user.profile.stripe_customer_id
            )
        except stripe.error.StripeError as e:
            capture_exception(e)
            request.user.log_event(
                "Stripe error while creating SetupIntent.", "stripe", str(e)
            )
            return Response(
                {"success": False, "message": "billing.stripeError"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"clientSecret": intent.client_secret})

    def post(self, request):
        payment_method_id = request.data.get("paymentMethodId")

        with transaction.atomic():
            # Lock so concurrent add-card requests serialize.
            profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            try:
                # Attach + set default before persisting card metadata —
                # if Stripe rejects the PM, the DB stays consistent.
                stripe.PaymentMethod.attach(
                    payment_method_id,
                    customer=profile.stripe_customer_id,
                )
                payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                stripe.Customer.modify(
                    profile.stripe_customer_id,
                    invoice_settings={"default_payment_method": payment_method_id},
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
                request.user.log_event(
                    "Stripe error while attaching payment method.",
                    "stripe",
                    str(e),
                )
                return Response(
                    {"success": False, "message": "billing.stripeError"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            profile.stripe_card_last_digits = payment_method["card"]["last4"]
            profile.stripe_card_expiry = f"{str(payment_method['card']['exp_month']).zfill(2)}/{str(payment_method['card']['exp_year'])}"
            profile.stripe_payment_method_id = payment_method_id
            profile.save(
                update_fields=[
                    "stripe_card_last_digits",
                    "stripe_card_expiry",
                    "stripe_payment_method_id",
                ]
            )

            # Mirror to caller's instance.
            request.user.profile.stripe_card_last_digits = (
                profile.stripe_card_last_digits
            )
            request.user.profile.stripe_card_expiry = profile.stripe_card_expiry
            request.user.profile.stripe_payment_method_id = (
                profile.stripe_payment_method_id
            )

        # Email outside the atomic — a Postmark blip mustn't roll back the
        # successful card attachment.
        subject = f"You just added a payment card to your {config.SITE_OWNER} account."
        try:
            request.user.email_notification(
                subject,
                "Don't worry, your card details are stored safe "
                "with Stripe and are not on our servers. You "
                "can remove this card at any time via the "
                f"{config.SITE_NAME}.",
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                {"message": "error.postmarkNotConfigured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response()

    def delete(self, request):
        with transaction.atomic():
            # Lock so concurrent delete/add-card requests serialize.
            profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            if profile.stripe_payment_method_id:
                try:
                    stripe.PaymentMethod.detach(profile.stripe_payment_method_id)
                except stripe.error.InvalidRequestError:
                    # Already detached / unknown — fall through to DB cleanup.
                    pass
                except stripe.error.StripeError as e:
                    capture_exception(e)
                    request.user.log_event(
                        "Stripe error while detaching payment method.",
                        "stripe",
                        str(e),
                    )
                    return Response(
                        {"success": False, "message": "billing.stripeError"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

            profile.stripe_payment_method_id = ""
            profile.stripe_card_last_digits = ""
            profile.stripe_card_expiry = ""
            profile.save(
                update_fields=[
                    "stripe_payment_method_id",
                    "stripe_card_last_digits",
                    "stripe_card_expiry",
                ]
            )

            # Mirror to caller's instance.
            request.user.profile.stripe_payment_method_id = ""
            request.user.profile.stripe_card_last_digits = ""
            request.user.profile.stripe_card_expiry = ""

        return Response()


class MemberTiers(StripeAPIView):
    """
    get: gets a list of all membership tiers.
    """

    def get(self, request):
        tiers = MemberTier.objects.filter(visible=True)
        formatted_tiers = []

        for tier in tiers:
            plans = []

            for plan in tier.plans.filter(visible=True):
                plans.append(plan.get_object())

            formatted_tiers.append(tier.get_object())

        return Response(formatted_tiers)


class PaymentPlanSignup(StripeAPIView):
    """
    post: attempts to sign the member up to a new payment plan.
    """

    def create_subscription(
        self,
        request: HttpRequest,
        new_plan: PaymentPlan,
        billing_method: str = "card",
        attempts: int = 0,
        idempotency_token: str = None,
    ):
        """Returns (subscription, error_response); exactly one is None.

        `idempotency_token` is generated per top-level call and reused
        across this function's recursive retries. A genuinely new POST
        from the member must pass a fresh token (or omit it so we
        generate one) — otherwise Stripe replays the cached response
        from the previous attempt for ~24h and the member is locked
        out of retrying after a card decline / SCA failure.
        """
        attempts += 1
        if idempotency_token is None:
            idempotency_token = uuid.uuid4().hex

        if attempts > 3:
            request.user.log_event(
                "Too many attempts while creating subscription.",
                "stripe",
                "",
            )
            return None, Response(
                {
                    "success": False,
                    "message": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            subscription_params = {
                "customer": request.user.profile.stripe_customer_id,
                "items": [{"price": new_plan.stripe_id}],
            }
            if billing_method == "invoice":
                subscription_params["collection_method"] = "send_invoice"
                subscription_params["days_until_due"] = config.INVOICE_DAYS_UNTIL_DUE

            # Token bounds idempotency to this request; `attempts` lets
            # the resource_missing retry below get a fresh key inside
            # the same request instead of Stripe's cached failure.
            subscription = stripe.Subscription.create(
                **subscription_params,
                idempotency_key=(
                    f"signup-{request.user.id}-{new_plan.id}"
                    f"-{idempotency_token}-{attempts}"
                ),
            )

            # For send_invoice subscriptions, Stripe delays finalizing the first
            # invoice by ~1 hour before auto-sending it. Finalize it immediately
            # so the member receives the invoice right away — Stripe then emails
            # it automatically as part of send_invoice collection behavior. If
            # this call fails (rate limit, transient API error), Stripe's built-in
            # auto-finalize still runs within ~1 hour, so the subscription is
            # still usable — the member just gets their invoice email delayed.
            if billing_method == "invoice" and subscription.latest_invoice:
                # latest_invoice is an id string when not expanded, but a dict
                # when expand=["latest_invoice"] is added later. Accept both.
                latest_invoice_id = getattr(
                    subscription.latest_invoice, "id", subscription.latest_invoice
                )
                try:
                    stripe.Invoice.finalize_invoice(latest_invoice_id)
                except stripe.error.StripeError as e:
                    capture_exception(e)
                    request.user.log_event(
                        "Failed to finalize invoice immediately; "
                        "Stripe will auto-finalize within ~1 hour.",
                        "stripe",
                        str(e),
                    )

            return subscription, None

        except stripe.error.InvalidRequestError as e:
            capture_exception(e)
            error = (e.json_body or {}).get("error") or {}
            error_code = error.get("code", "")
            error_message = error.get("message", "")

            if (
                error_code == "resource_missing"
                and "default payment method" in error_message
            ):
                request.user.log_event(
                    "InvalidRequestError (missing default payment method) from Stripe while creating subscription.",
                    "stripe",
                    error,
                )

                # try to set the default and try again
                stripe.Customer.modify(
                    request.user.profile.stripe_customer_id,
                    invoice_settings={
                        "default_payment_method": request.user.profile.stripe_payment_method_id,
                    },
                )

                return self.create_subscription(
                    request, new_plan, billing_method, attempts, idempotency_token
                )

            if (
                error_code == "resource_missing"
                and "a similar object exists in live mode" in error_message
            ):
                request.user.log_event(
                    "InvalidRequestError (used test key with production object) from Stripe while "
                    "creating subscription.",
                    "stripe",
                    error,
                )

                return None, Response(
                    {
                        "success": False,
                        "message": error_message,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            else:
                request.user.log_event(
                    "InvalidRequestError from Stripe while creating subscription.",
                    "stripe",
                    error,
                )
                return None, Response(
                    {
                        "success": False,
                        "message": None,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            request.user.log_event(
                "InvalidRequestError from Stripe while creating subscription.",
                "stripe",
                e,
            )
            capture_exception(e)
            return None, Response(
                {
                    "success": False,
                    "message": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request, plan_id):
        # Refuse before any Stripe call so a locked member can't pay into a void.
        if request.user.profile.state_locked:
            return Response(
                {"success": False, "message": "billing.stateLocked"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Gate ONLY on this view: renewals (invoice.paid webhook), pending
        # invoices being paid, CompleteSignup for already-created subs, and
        # PaymentPlanResume for cancelling members must all keep working.
        if not config.ENABLE_NEW_SUBSCRIPTIONS:
            return Response(
                {"success": False, "message": "billing.newSubscriptionsDisabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        new_plan = get_object_or_404(PaymentPlan, pk=plan_id)

        billing_method = request.data.get("billingMethod", "card")
        if billing_method not in ("card", "invoice"):
            billing_method = "card"

        if billing_method == "invoice" and not config.ENABLE_INVOICE_BILLING:
            return Response(
                {"success": False, "message": "billing.invoiceDisabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # For invoice billing, the user skipped the card step so customer may not exist yet
        if billing_method == "invoice":
            ok, err = ensure_stripe_customer(request.user)
            if not ok:
                return Response(
                    {"success": False, "message": err},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        # Lock so concurrent signups serialize and the second one sees
        # membership_plan set, returning 409 instead of creating a second sub.
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            # Re-check under the row lock: an admin lock that races the
            # outer check would otherwise leave an orphan Stripe sub on a
            # locked member.
            if locked_profile.state_locked:
                return Response(
                    {"success": False, "message": "billing.stateLocked"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if locked_profile.membership_plan:
                return Response({"success": False}, status=status.HTTP_409_CONFLICT)

            new_subscription, error_response = self.create_subscription(
                request, new_plan, billing_method
            )
            if error_response is not None:
                return error_response

            if new_subscription.status == "active":
                locked_profile.stripe_subscription_id = new_subscription.id
                locked_profile.membership_plan = new_plan
                locked_profile.subscription_status = (
                    "pending" if billing_method == "invoice" else "active"
                )
                locked_profile.billing_method = billing_method
                locked_profile.pending_signup_email_sent = False
                locked_profile.save(
                    update_fields=[
                        "stripe_subscription_id",
                        "membership_plan",
                        "subscription_status",
                        "billing_method",
                        "pending_signup_email_sent",
                    ]
                )

                request.user.log_event(
                    "Successfully created subscription in Stripe.",
                    "stripe",
                    "",
                )

        if new_subscription.status == "active":
            # Outside the atomic so complete_signup can take its own lock.
            locked_profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)
            return Response({"success": True})

        request.user.log_event(
            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
            "stripe",
            "",
        )

        # Cancel the non-active sub (e.g. incomplete from SCA) so it
        # doesn't dangle on the customer and trigger a duplicate next try.
        _cancel_failed_subscription(request.user, new_subscription.id)

        return Response({"success": False, "message": "signup.subscriptionFailed"})


class CanSignup(APIView):
    """
    get: checks if the member is eligible to signup, and what actions they need to complete.
    """

    def get(self, request):
        return Response(request.user.profile.can_signup())


class AcceptTerms(APIView):
    """
    post: records that the member has accepted the configured Terms &
    Conditions cards. Server is the source of truth for what was
    accepted, so no body is required.
    """

    def post(self, request):
        request.user.profile.update_terms_accepted_at()
        return Response({"success": True})


class AssignAccessCard(APIView):
    """
    post: assigns the access card to the member during first-time signup.
    """

    def post(self, request):
        if not config.MEMBER_CAN_ENTER_ACCESS_CARD:
            return Response(
                {"success": False, "message": "accessCard.memberEntryDisabled"},
                status=status.HTTP_403_FORBIDDEN,
            )

        access_card = (request.data.get("accessCard") or "").strip()
        if not access_card:
            return Response(
                {"success": False, "message": "accessCard.required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lock + re-read so a concurrent admin (state/rfid mutation) or
        # the same user double-submitting can't slip writes past these
        # checks. The cross-profile RFID-collision case is still caught
        # by the unique constraint below — locks on different rows don't
        # help there.
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            if locked_profile.state not in ("noob", "accountonly"):
                request.user.log_event(
                    f"Member tried to self-rebind RFID while state={locked_profile.state}; refused.",
                    "profile",
                )
                return Response(
                    {"success": False, "message": "accessCard.adminRebindRequired"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if locked_profile.rfid:
                request.user.log_event(
                    "Member tried to self-rebind RFID but one is already set; refused.",
                    "profile",
                )
                return Response(
                    {"success": False, "message": "accessCard.alreadyBound"},
                    status=status.HTTP_409_CONFLICT,
                )

            if (
                Profile.objects.filter(rfid=access_card)
                .exclude(pk=locked_profile.pk)
                .exists()
            ):
                request.user.log_event(
                    "Member tried to bind an RFID already held by another member; refused.",
                    "profile",
                )
                return Response(
                    {"success": False, "message": "accessCard.alreadyInUse"},
                    status=status.HTTP_409_CONFLICT,
                )

            locked_profile.rfid = access_card
            try:
                locked_profile.save(update_fields=["rfid"])
            except IntegrityError:
                # Cross-profile race: another member's request committed
                # the same RFID between our pre-check and our save. The
                # DB unique constraint is the authoritative gate; surface
                # the same 409 the pre-check would have.
                request.user.log_event(
                    "Member tried to bind an RFID already held by another member; "
                    "refused (race lost on unique constraint).",
                    "profile",
                )
                return Response(
                    {"success": False, "message": "accessCard.alreadyInUse"},
                    status=status.HTTP_409_CONFLICT,
                )

        request.user.log_event(
            "Member self-bound RFID.",
            "profile",
        )

        return Response({"success": True})


class CheckInductionStatus(APIView):
    """
    post: checks if the member has completed the induction (via the canvas/moodle API).
    """

    def post(self, request):
        if "induction" not in request.user.profile.can_signup()["requiredSteps"]:
            return Response({"success": True, "score": 0, "notRequired": True})

        score = 0

        if config.MOODLE_INDUCTION_ENABLED:
            try:
                moodle_user = moodle_get_user_from_email(request.user.email)
                activities = moodle_get_course_activity_completion_status(
                    config.MOODLE_INDUCTION_COURSE_ID, moodle_user["id"]
                )
                score = activities["percentage_completed"]
            except RuntimeError as e:
                # Helper raises RuntimeError when 0 or >1 Moodle users match
                # the member's email. Most common case: member hasn't set up
                # their Moodle account yet — return a friendly response so
                # the frontend can prompt them, instead of 500-ing.
                logger.info("Moodle lookup for %s: %s", request.user.email, e)
                return Response(
                    {
                        "success": False,
                        "score": 0,
                        "message": "signup.noMoodleAccount",
                    }
                )
            except Exception as e:
                # Network / JSON / unexpected Moodle response — log and
                # surface a generic error rather than leaking the trace.
                capture_exception(e)
                return Response(
                    {
                        "success": False,
                        "score": 0,
                        "message": "signup.moodleUnavailable",
                    }
                )

        elif config.CANVAS_INDUCTION_ENABLED:
            try:
                canvas_api = Canvas()
            except OperationalError as error:
                capture_exception(error)
                logger.error(error)
                return Response({"success": False, "score": 0})

            score = (
                canvas_api.get_student_score_for_course(
                    config.CANVAS_INDUCTION_COURSE_ID, request.user.email
                )
                or 0
            )

        try:
            if score or config.MIN_INDUCTION_SCORE == 0:
                induction_passed = score >= config.MIN_INDUCTION_SCORE

                if induction_passed:
                    request.user.profile.update_last_induction()

                    return Response({"success": True, "score": score})
            return Response({"success": False, "score": score})

        except Exception as e:
            capture_exception(e)
            logger.error(e)
            return Response({"success": False, "score": 0, "error": str(e)})


def _serialize_complete_signup(result: CompleteSignupResult) -> Response:
    if result.outcome == CompleteSignupOutcome.ACTIVATED:
        return Response({"success": True})
    if result.outcome == CompleteSignupOutcome.ALREADY_ACTIVE:
        return Response({"success": True})
    if result.outcome == CompleteSignupOutcome.AWAITING_PAYMENT:
        return Response(
            {
                "success": True,
                "awaitingPayment": True,
                "message": "signup.awaitingInvoicePayment",
            }
        )
    if result.outcome == CompleteSignupOutcome.REQUIREMENTS_UNMET:
        return Response(
            {
                "success": False,
                "message": "signup.requirementsNotMet",
                "items": result.required_steps,
            }
        )
    if result.outcome == CompleteSignupOutcome.STATE_LOCKED:
        return Response(
            {"success": False, "message": "billing.stateLocked"},
            status=status.HTTP_403_FORBIDDEN,
        )
    # NO_SUBSCRIPTION
    return Response(
        {
            "success": False,
            "message": "signup.requirementsNotMet",
            "items": ["No active subscription found."],
        }
    )


class CompleteSignup(StripeAPIView):
    """
    post: completes the member's signup if they have completed all requirements and enables access
    """

    def post(self, request):
        result = request.user.profile.complete_signup(
            SignupTriggeredBy.MEMBER_SELF_SERVE
        )
        return _serialize_complete_signup(result)


class SkipSignup(APIView):
    """
    post: skips the billing/tier signup process if they just want an account
    """

    def post(self, request):
        # Only valid for a brand-new signup with no subscription. Flipping
        # state="accountonly" while a Stripe sub is live revokes access but
        # keeps billing — caller must cancel via /api/billing/myplan/cancel/
        # first. Lock + re-read so a concurrent webhook can't flip
        # subscription_status between the check and the write.
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            if (
                locked_profile.state != "noob"
                or locked_profile.subscription_status != "inactive"
            ):
                return Response(
                    {
                        "success": False,
                        "message": "signup.skipNotAllowed",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            locked_profile.state = "accountonly"
            locked_profile.save(update_fields=["state"])

        return Response({"success": True})


class SubscriptionInfo(StripeAPIView):
    """
    get: retrieves information about the members subscription.
    """

    def get(self, request):
        current_plan = request.user.profile.membership_plan

        if not current_plan or not request.user.profile.stripe_subscription_id:
            return Response({"success": False})

        else:
            try:
                s = stripe.Subscription.retrieve(
                    request.user.profile.stripe_subscription_id,
                    expand=["latest_invoice"],
                )
            except stripe.error.StripeError as e:
                # Degrade gracefully rather than 500 when Stripe is slow/down.
                capture_exception(e)
                return Response({"success": False, "unavailable": True})

            if s:
                invoice_url = None
                if s.latest_invoice and hasattr(s.latest_invoice, "hosted_invoice_url"):
                    invoice_url = s.latest_invoice.hosted_invoice_url

                subscription = {
                    "billingCycleAnchor": s.billing_cycle_anchor,
                    "currentPeriodEnd": s.current_period_end,
                    "cancelAt": s.cancel_at,
                    "cancelAtPeriodEnd": s.cancel_at_period_end,
                    "startDate": s.start_date,
                    "collectionMethod": s.collection_method,
                    "invoiceUrl": invoice_url,
                    "membershipTier": request.user.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": request.user.profile.membership_plan.get_object(),
                }
                return Response({"success": True, "subscription": subscription})

            return Response({"success": False})


def _no_plan_response(user):
    user.log_event("Member tried to modify nonexistant membership plan.", "stripe")
    return Response(
        {"success": False, "message": "paymentPlan.notExists"},
        status=status.HTTP_404_NOT_FOUND,
    )


def _email_admin_orphan_subscription(user, subscription_id):
    """Stripe subscription was created but we couldn't clean it up — admin
    needs to delete it manually so it doesn't keep billing the customer.
    Deferred to on_commit so callers can invoke this from inside a
    transaction without holding the row lock across Postmark I/O."""
    subject = (
        f"Action Required: orphan Stripe subscription {subscription_id} "
        f"for {user.get_full_name()}"
    )
    message = (
        f"A subscription signup for {user.get_full_name()} failed (the "
        "subscription wasn't activated by Stripe), and our automatic "
        f"cleanup of subscription {subscription_id} also failed. Please "
        "delete it in Stripe so the customer isn't billed."
    )

    def _send(user=user, subject=subject, message=message):
        try:
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": message},
                user=user,
                reply_to=user.email,
            )
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_send)


def _cancel_failed_subscription(user, subscription_id):
    """Best-effort cleanup of a Stripe subscription we just created but
    that came back in a non-active status (e.g. SCA-incomplete). On
    Stripe failure, alerts admin to delete it manually."""
    try:
        stripe.Subscription.delete(subscription_id, invoice_now=False, prorate=False)
    except stripe.error.StripeError as e:
        capture_exception(e)
        user.log_event(
            f"Failed to cancel orphaned subscription {subscription_id}.",
            "stripe",
            str(e),
        )
        _email_admin_orphan_subscription(user, subscription_id)


def _email_admin_resume_failed(user):
    """Resume request didn't flip cancel_at_period_end — admin investigates.
    Wrapped + on_commit so a Postmark blip can't 500 the user-facing call."""
    subject = (
        f"{user.get_full_name()} tried to resume their cancelling "
        "membership plan but it failed."
    )

    def _send(user=user, subject=subject):
        try:
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": subject},
                user=user,
                reply_to=user.email,
            )
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_send)
    user.log_event(subject, "stripe")


def _email_admin_cancel_failed(user):
    """Cancel request didn't flip cancel_at_period_end — admin investigates.
    Wrapped + on_commit so a Postmark blip can't 500 the user-facing call."""
    subject = (
        f"{user.get_full_name()} requested to cancel their membership "
        "plan but it failed."
    )
    message = (
        "We're not sure what happened, you should check Stripe and "
        "contact the member."
    )

    def _send(user=user, subject=subject, message=message):
        try:
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": message},
                user=user,
                reply_to=user.email,
            )
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_send)
    user.log_event(subject, "stripe")


class PaymentPlanResume(StripeAPIView):
    """
    post: resumes a member's cancelling subscription, or re-creates one
    against their existing membership_plan if no subscription is live.
    """

    def post(self, request):
        if request.user.profile.state_locked:
            return Response(
                {"success": False, "message": "billing.stateLocked"},
                status=status.HTTP_403_FORBIDDEN,
            )

        current_plan = request.user.profile.membership_plan

        if not current_plan:
            return _no_plan_response(request.user)

        if not request.user.profile.stripe_subscription_id:
            return self._resume_by_recreating(request, current_plan)

        return self._resume_cancelling(request)

    def _resume_by_recreating(self, request, current_plan):
        request.user.log_event(
            "Member tried to resume a payment plan that doesn't exist - creating it.",
            "stripe",
        )

        billing_method = request.user.profile.billing_method
        if billing_method == "invoice":
            ok, err = ensure_stripe_customer(request.user)
            if not ok:
                return Response(
                    {"success": False, "message": err},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        # Lock so two concurrent resume clicks don't both create a
        # subscription. Mirrors PaymentPlanSignup.post.
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            # Re-check under the row lock — see PaymentPlanSignup.post for
            # the orphan-Stripe-sub rationale.
            if locked_profile.state_locked:
                return Response(
                    {"success": False, "message": "billing.stateLocked"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if locked_profile.stripe_subscription_id:
                return Response({"success": False}, status=status.HTTP_409_CONFLICT)

            (
                new_subscription,
                error_response,
            ) = PaymentPlanSignup().create_subscription(
                request, current_plan, billing_method
            )
            if error_response is not None:
                return error_response

            if new_subscription.status == "active":
                locked_profile.stripe_subscription_id = new_subscription.id
                locked_profile.subscription_status = (
                    "pending" if billing_method == "invoice" else "active"
                )
                locked_profile.pending_signup_email_sent = False
                locked_profile.save(
                    update_fields=[
                        "stripe_subscription_id",
                        "subscription_status",
                        "pending_signup_email_sent",
                    ]
                )

                request.user.log_event(
                    "Successfully created subscription in Stripe.",
                    "stripe",
                    "",
                )

        if new_subscription.status == "active":
            # Outside the atomic so complete_signup can take its own lock.
            locked_profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)
            return Response({"success": True})

        request.user.log_event(
            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
            "stripe",
            "",
        )

        # Cancel the non-active sub so a retry doesn't duplicate it.
        _cancel_failed_subscription(request.user, new_subscription.id)

        return Response({"success": False, "message": "signup.subscriptionFailed"})

    def _resume_cancelling(self, request):
        # Lock so a concurrent webhook can't null stripe_subscription_id
        # while we're in the middle of resuming.
        failed = False
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            # Status must actually be "cancelling" — otherwise we'd be
            # sending the misleading "resumed cancelling plan" admin
            # email on an already-active sub.
            if (
                not locked_profile.stripe_subscription_id
                or locked_profile.subscription_status != "cancelling"
            ):
                return Response(
                    {"success": False, "message": "paymentPlan.notExists"},
                    status=status.HTTP_409_CONFLICT,
                )

            # StripeError must be caught (not raised) so the atomic
            # commits cleanly and the failure-email helper outside this
            # block can fire on_commit. Letting it propagate would roll
            # back, drop pending on_commit callbacks, and 500 the user.
            try:
                modified_subscription = stripe.Subscription.modify(
                    locked_profile.stripe_subscription_id,
                    cancel_at_period_end=False,
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
                request.user.log_event(
                    "Stripe error while resuming cancelling subscription.",
                    "stripe",
                    str(e),
                )
                failed = True
            else:
                if modified_subscription.cancel_at_period_end:
                    failed = True
                else:
                    locked_profile.subscription_status = "active"
                    locked_profile.save(update_fields=["subscription_status"])

                    subject = f"{request.user.get_full_name()} resumed their cancelling membership plan."
                    request.user.log_event(subject, "stripe")

                    member_subject = "Your membership has been resumed"
                    member_message = (
                        "Your cancellation request has been reversed and "
                        "your membership will continue billing as normal."
                    )

                    def _on_commit_resume_notifications(
                        admin_subject=subject,
                        user=request.user,
                        member_subject=member_subject,
                        member_message=member_message,
                    ):
                        try:
                            send_email_to_admin(
                                subject=admin_subject,
                                template_vars={
                                    "title": admin_subject,
                                    "message": admin_subject,
                                },
                                user=user,
                                reply_to=user.email,
                            )
                        except Exception as e:
                            capture_exception(e)
                        try:
                            user.email_notification(member_subject, member_message)
                        except Exception as e:
                            capture_exception(e)

                    transaction.on_commit(_on_commit_resume_notifications)
                    return Response({"success": True})

        # Outside the atomic — failure email fires regardless of any
        # rollback in the with block (there isn't one, but be explicit).
        if failed:
            _email_admin_resume_failed(request.user)
        return Response({"success": False})


class PaymentPlanCancel(StripeAPIView):
    """
    post: cancels a member's payment plan — pending invoice subs are
    deleted immediately; active subs are scheduled to cancel at period end.
    """

    def post(self, request):
        if not request.user.profile.membership_plan:
            return _no_plan_response(request.user)

        if request.user.profile.subscription_status == "pending":
            return self._cancel_pending(request)
        return self._cancel_active(request)

    def _cancel_pending(self, request):
        # Pending invoice sub: commit the DB cancel under the row lock,
        # then push Stripe cleanup + profile-side reaction to on_commit.
        # Stripe orchestration stays here; the profile-side reaction (clear
        # pre-staged access, audit log) lives in Profile.complete_cancel().
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            # Re-read under the lock — a webhook may have flipped us
            # out of "pending" between the outer check and the lock.
            if (
                locked_profile.subscription_status != "pending"
                or not locked_profile.stripe_subscription_id
            ):
                return Response(
                    {"success": False, "message": "paymentPlan.notExists"},
                    status=status.HTTP_409_CONFLICT,
                )

            subscription_id = locked_profile.stripe_subscription_id

            locked_profile.membership_plan = None
            locked_profile.stripe_subscription_id = None
            locked_profile.subscription_status = "inactive"
            # billing_method is intentionally preserved — keeping the
            # member's prior preference simplifies a future flow that
            # lets them switch billing method directly.
            locked_profile.save(
                update_fields=[
                    "membership_plan",
                    "stripe_subscription_id",
                    "subscription_status",
                ]
            )

            cancelled_subject = (
                f"{request.user.get_full_name()} cancelled their pending "
                "membership (no payment was made)."
            )
            member_subject = "Your pending membership signup has been cancelled."
            member_message = (
                "We've cancelled your pending membership signup at your "
                "request. No payment was taken. You can sign up again at "
                "any time from the member portal."
            )

            def _on_commit_cancel_notifications(
                admin_subject=cancelled_subject,
                user=request.user,
                member_subject=member_subject,
                member_message=member_message,
            ):
                try:
                    send_email_to_admin(
                        subject=admin_subject,
                        template_vars={
                            "title": admin_subject,
                            "message": admin_subject,
                        },
                        user=user,
                        reply_to=user.email,
                    )
                except Exception as e:
                    capture_exception(e)
                try:
                    user.email_notification(member_subject, member_message)
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_on_commit_cancel_notifications)

            def _on_commit_stripe_cleanup(
                subscription_id=subscription_id,
                user=request.user,
            ):
                # See today's _cancel_pending for the failure-mode rationale.
                try:
                    try:
                        open_invoices = stripe.Invoice.list(
                            subscription=subscription_id, status="open"
                        )
                        for invoice in open_invoices.auto_paging_iter():
                            try:
                                stripe.Invoice.void_invoice(invoice.id)
                            except stripe.error.StripeError as e:
                                capture_exception(e)
                                user.log_event(
                                    f"Failed to void open invoice "
                                    f"{invoice.id} during pending-cancel.",
                                    "stripe",
                                    str(e),
                                )
                        stripe.Subscription.delete(
                            subscription_id, invoice_now=False, prorate=False
                        )
                    except stripe.error.StripeError as e:
                        capture_exception(e)
                        user.log_event(
                            f"Failed to delete pending subscription "
                            f"{subscription_id} on Stripe after DB cancel; "
                            "manual cleanup required.",
                            "stripe",
                            str(e),
                        )
                        failure_subject = (
                            f"Action Required: clean up Stripe subscription "
                            f"{subscription_id} for {user.get_full_name()}"
                        )
                        failure_message = (
                            f"{user.get_full_name()} cancelled their pending "
                            "membership in the portal, but the Stripe-side "
                            f"cleanup failed. Subscription {subscription_id} "
                            "and any open invoices may still be live in "
                            "Stripe — please void/delete them manually."
                        )
                        try:
                            send_email_to_admin(
                                subject=failure_subject,
                                template_vars={
                                    "title": failure_subject,
                                    "message": failure_message,
                                },
                                user=user,
                                reply_to=user.email,
                            )
                        except Exception as email_err:
                            capture_exception(email_err)
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_on_commit_stripe_cleanup)

            def _on_commit_complete_cancel(profile=locked_profile):
                try:
                    profile.complete_cancel(CancelTriggeredBy.MEMBER_SELF_CANCEL)
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_on_commit_complete_cancel)

        return Response({"success": True})

    def _cancel_active(self, request):
        # Schedule cancellation at period end. complete_cancel is NOT called
        # here — the actual deactivation happens when the
        # customer.subscription.deleted webhook arrives at period end.
        failed = False
        with transaction.atomic():
            locked_profile = Profile.objects.select_for_update().get(
                pk=request.user.profile.pk
            )

            if not locked_profile.stripe_subscription_id:
                return Response(
                    {"success": False, "message": "paymentPlan.notExists"},
                    status=status.HTTP_409_CONFLICT,
                )

            # Already scheduled to cancel — treat a repeat request as a no-op.
            if locked_profile.subscription_status == "cancelling":
                return Response({"success": True})

            # StripeError must be caught so the atomic commits cleanly and
            # the failure-email helper outside this block can fire.
            try:
                modified_subscription = stripe.Subscription.modify(
                    locked_profile.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
                request.user.log_event(
                    "Stripe error while scheduling cancel-at-period-end.",
                    "stripe",
                    str(e),
                )
                failed = True
            else:
                if not modified_subscription.cancel_at_period_end:
                    failed = True
                else:
                    locked_profile.subscription_status = "cancelling"
                    locked_profile.save(update_fields=["subscription_status"])

                    cancel_subject = (
                        f"{request.user.get_full_name()} requested to cancel "
                        "their membership plan."
                    )
                    request.user.log_event(
                        "You've requested to cancel your membership plan.",
                        "stripe",
                    )

                    def _on_commit_cancel_notifications(
                        admin_subject=cancel_subject,
                        user=request.user,
                    ):
                        description = (
                            "No further action is required, the subscription "
                            "will automatically cancel at the end of the "
                            "current billing period."
                        )
                        try:
                            send_email_to_admin(
                                subject=admin_subject,
                                template_vars={
                                    "title": admin_subject,
                                    "message": description,
                                },
                                user=user,
                                reply_to=user.email,
                            )
                        except Exception as e:
                            capture_exception(e)

                        member_subject = (
                            "You've requested to cancel your membership plan."
                        )
                        member_description = (
                            "No further action is required, the subscription "
                            "will automatically cancel at the end of the "
                            "current billing period. You can cancel this "
                            "request at any time from the member portal."
                        )
                        try:
                            user.email_notification(member_subject, member_description)
                        except Exception as e:
                            capture_exception(e)

                    transaction.on_commit(_on_commit_cancel_notifications)
                    return Response({"success": True})

        if failed:
            _email_admin_cancel_failed(request.user)
        return Response({"success": False})


class StripeWebhook(StripeAPIView):
    """
    post: processes a Stripe webhook event.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        # Fail closed when no signing secret is configured. The endpoint is
        # publicly reachable and unauthenticated by design (Stripe can't
        # present a session/JWT), so signature verification is the *only*
        # gate. Without it, anyone who guesses a stripe_customer_id can
        # forge invoice.paid / customer.subscription.deleted events and
        # activate or cancel arbitrary members.
        webhook_secret = config.STRIPE_WEBHOOK_SECRET
        if not webhook_secret:
            logger.error(
                "STRIPE_WEBHOOK_SECRET is not configured; rejecting webhook event."
            )
            return Response(
                {"error": "Webhook signing not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        signature = request.headers.get("stripe-signature")
        try:
            event = stripe.Webhook.construct_event(
                payload=request.body, sig_header=signature, secret=webhook_secret
            )
        except Exception as e:
            # Deliberately 200: a non-2xx would make Stripe retry a forged or
            # corrupt payload for ~3 days.
            logger.error(e)
            capture_exception(e)
            return Response({"error": "Error validating Stripe signature."})

        data = event["data"]
        event_type = event["type"]
        event_id = event["id"]

        # Bail before taking a row lock or writing a dedup row for the
        # account-level events we have no handler for.
        handler = HANDLERS.get(event_type)
        if handler is None:
            return Response()

        # Atomic wraps dedup row + DB writes; on raise, rollback releases
        # the event id for Stripe's retry. External I/O (emails, SMS,
        # activate/deactivate, Stripe Invoice.void) is deferred via
        # on_commit so slow upstreams can't extend the row lock past
        # Stripe's ~30s webhook timeout. Trade-off: on_commit failures
        # don't retry — a missed receipt email is better than a paid
        # member who never activates.
        with transaction.atomic():
            data = data["object"]

            # Some Stripe events (e.g. account-level ones) don't carry a customer
            # reference — we can't do anything useful with those.
            customer_id = data.get("customer")
            if not customer_id:
                return Response()

            try:
                # Lock to serialise concurrent webhook deliveries for the
                # same member; activate()'s own lock guards state but not
                # the surrounding notifications.
                locked_profile = Profile.objects.select_for_update().get(
                    stripe_customer_id=customer_id
                )
            except Profile.DoesNotExist:
                # Customers we don't track (one-off charges, etc.) — info-log only.
                logger.info("Webhook event for unknown stripe_customer_id; ignoring.")
                return Response()
            except Profile.MultipleObjectsReturned as e:
                # stripe_customer_id is unique at the DB level — should be impossible.
                capture_exception(e)
                return Response()

            # Run the scope check BEFORE the dedup insert so an out-of-scope
            # event doesn't poison its own retries — fix it, redeliver, and
            # processing picks up cleanly.
            scope = classify_event_scope(event_type, data, locked_profile)
            if scope is EventScope.IGNORE:
                return Response()

            # Idempotency: Stripe retries deliveries for up to ~3 days on non-2xx
            # responses or timeouts. Skip any event id we've already processed so
            # side effects (emails, SMS, state changes) don't fire twice.
            if event_id:
                _, created = ProcessedStripeEvent.objects.get_or_create(
                    event_id=event_id,
                    defaults={"event_type": event_type},
                )
                if not created:
                    return Response()

            context = WebhookContext(
                event_id=event_id,
                event_type=event_type,
                data=data,
                profile=locked_profile,
            )

            # An orphaned payment takes no state action, so unlike an
            # out-of-scope event there is nothing to fix and redeliver — it
            # passes through dedup so retries produce one alert, not one per
            # delivery.
            if scope is EventScope.ORPHAN_PAID:
                handle_orphan_invoice_paid(context)
            else:
                handler(context)

        return Response()
