from asgiref.sync import sync_to_async
from django.http import HttpRequest

from profile.models import Profile
from api_admin_tools.models import *
from .models import ProcessedStripeEvent

from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

import stripe
import logging
from services.canvas import Canvas
from services.moodle_integration import (
    moodle_get_course_activity_completion_status,
    moodle_get_user_from_email,
)
from services.emails import send_email_to_admin
from constance import config
from django.db import transaction
from django.db.utils import OperationalError
from sentry_sdk import capture_exception
from django.utils import timezone

logger = logging.getLogger("billing")


def ensure_stripe_customer(user):
    """
    Ensures a Stripe customer exists for the given user, creating one if needed.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    profile = user.profile
    if profile.stripe_customer_id:
        try:
            customer = stripe.Customer.retrieve(profile.stripe_customer_id)
            if not customer.get("deleted"):
                return True, None
        except stripe.error.InvalidRequestError:
            profile.stripe_customer_id = None
            profile.save()

    try:
        user.log_event("Attempting to create stripe customer.", "stripe")
        customer = stripe.Customer.create(
            email=user.email,
            name=profile.get_full_name(),
            phone=profile.phone,
        )
        profile.stripe_customer_id = customer.id
        profile.save()
        user.log_event(
            f"Created stripe customer {profile.get_full_name()} (Stripe ID: {customer.id}).",
            "stripe",
        )
        return True, None
    except stripe.error.StripeError as e:
        capture_exception(e)
        user.log_event("Error while creating stripe customer.", "stripe")
        return False, str(e)


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
        profile = request.user.profile
        customer_exists = True

        # check that the customer exists and isn't deleted
        if profile.stripe_customer_id:
            try:
                customer = stripe.Customer.retrieve(profile.stripe_customer_id)
                if customer.get("deleted") or not customer:
                    customer_exists = False

            except stripe.error.InvalidRequestError as error:
                # Invalid parameters were supplied to Stripe's API
                capture_exception(error)

                # if the customer doesn't exist then remove the Stripe customer id
                if error.http_status == 404:
                    profile.stripe_customer_id = None
                    profile.save()

                    customer_exists = False

        else:
            customer_exists = False

        if not customer_exists:
            try:
                request.user.log_event(
                    "Attempting to create stripe customer.", "stripe"
                )
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=profile.get_full_name(),
                    phone=profile.phone,
                )

                profile.stripe_customer_id = customer.id
                profile.save()

                request.user.log_event(
                    f"Created stripe customer {request.user.profile.get_full_name()} (Stripe ID: {customer.id}).",
                    "stripe",
                )

                intent = stripe.SetupIntent.create(customer=profile.stripe_customer_id)

                return Response({"clientSecret": intent.client_secret})

            except stripe.error.StripeError as e:
                request.user.log_event(
                    "Unknown stripe while saving payment details.",
                    "stripe",
                    request,
                )
                capture_exception(e)

                return Response(
                    {
                        "success": False,
                        "message": str(e),
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            except Exception as e:
                request.user.log_event(
                    "Unknown other error while saving payment details.",
                    "stripe",
                    request,
                )
                capture_exception(e)
                return Response(
                    {
                        "success": False,
                        "message": "Unknown error (unrelated to stripe).",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        else:
            intent = stripe.SetupIntent.create(customer=profile.stripe_customer_id)

            return Response({"clientSecret": intent.client_secret})

    def post(self, request):
        profile = request.user.profile
        payment_method_id = request.data.get("paymentMethodId")

        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

        profile.stripe_card_last_digits = payment_method["card"]["last4"]
        profile.stripe_card_expiry = f"{str(payment_method['card']['exp_month']).zfill(2)}/{str(payment_method['card']['exp_year'])}"
        profile.stripe_payment_method_id = payment_method_id
        profile.save()

        # attached the payment method to the customer
        stripe.PaymentMethod.attach(
            payment_method_id,
            customer=profile.stripe_customer_id,
        )
        # Set the default payment method on the customer
        stripe.Customer.modify(
            profile.stripe_customer_id,
            invoice_settings={
                "default_payment_method": payment_method_id,
            },
        )

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
        profile = request.user.profile

        if profile.stripe_payment_method_id:
            stripe.PaymentMethod.detach(profile.stripe_payment_method_id)

        profile.stripe_payment_method_id = ""
        profile.stripe_card_last_digits = ""
        profile.stripe_card_expiry = ""
        profile.save()
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
    ):
        attempts += 1

        if attempts > 3:
            request.user.log_event(
                "Too many attempts while creating subscription.",
                "stripe",
                "",
            )
            return Response(
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

            subscription = stripe.Subscription.create(**subscription_params)

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
                    )

            return subscription

        except stripe.error.InvalidRequestError as e:
            capture_exception(e)
            error = e.json_body.get("error")

            if (
                error["code"] == "resource_missing"
                and "default payment method" in error["message"]
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
                    request, new_plan, billing_method, attempts
                )

            if (
                error["code"] == "resource_missing"
                and "a similar object exists in live mode" in error["message"]
            ):
                request.user.log_event(
                    "InvalidRequestError (used test key with production object) from Stripe while "
                    "creating subscription.",
                    "stripe",
                    error,
                )

                return Response(
                    {
                        "success": False,
                        "message": error["message"],
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            else:
                request.user.log_event(
                    "InvalidRequestError from Stripe while creating subscription.",
                    "stripe",
                    error,
                )
                return Response(
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
            return Response(
                {
                    "success": False,
                    "message": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request, plan_id):
        current_plan = request.user.profile.membership_plan
        new_plan = PaymentPlan.objects.get(pk=plan_id)

        if current_plan:
            return Response({"success": False}, status=status.HTTP_409_CONFLICT)

        billing_method = request.data.get("billingMethod", "card")
        if billing_method not in ("card", "invoice"):
            billing_method = "card"

        # Server-side guard: ignore invoice billing if feature is disabled
        if billing_method == "invoice" and not config.ENABLE_INVOICE_BILLING:
            billing_method = "card"

        # For invoice billing, the user skipped the card step so customer may not exist yet
        if billing_method == "invoice":
            ok, err = ensure_stripe_customer(request.user)
            if not ok:
                return Response(
                    {"success": False, "message": err},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        new_subscription = self.create_subscription(request, new_plan, billing_method)

        try:
            if new_subscription.status == "active":
                request.user.profile.stripe_subscription_id = new_subscription.id
                request.user.profile.membership_plan = new_plan
                request.user.profile.subscription_status = (
                    "pending" if billing_method == "invoice" else "active"
                )
                request.user.profile.billing_method = billing_method
                request.user.profile.save()

                request.user.log_event(
                    "Successfully created subscription in Stripe.",
                    "stripe",
                    "",
                )

                return Response({"success": True})

            elif new_subscription.status == "incomplete":
                # if we got here, that means the subscription wasn't successfully created
                request.user.log_event(
                    f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                    "stripe",
                    "",
                )

                return Response(
                    {"success": True, "message": "signup.subscriptionFailed"}
                )

            else:
                request.user.log_event(
                    f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                    "stripe",
                    "",
                )
                return Response({"success": True})

        except KeyError as e:
            capture_exception(e)
            return new_subscription or e


class CanSignup(APIView):
    """
    get: checks if the member is eligible to signup, and what actions they need to complete.
    """

    def get(self, request):
        return Response(request.user.profile.can_signup())


class AssignAccessCard(APIView):
    """
    post: assigns the access card to the member.
    """

    def post(self, request):
        profile = request.user.profile
        profile.rfid = request.data["accessCard"]
        profile.save()

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


class CompleteSignup(StripeAPIView):
    """
    post: completes the member's signup if they have completed all requirements and enables access
    """

    def post(self, request):
        member_profile = request.user.profile

        if member_profile.subscription_status not in ("active", "pending"):
            return Response(
                {
                    "success": False,
                    "message": "signup.requirementsNotMet",
                    "items": ["No active subscription found."],
                }
            )

        signupCheck = member_profile.can_signup()

        if signupCheck["success"]:
            # For invoice billing: all requirements met, but don't activate
            # until invoice is paid. Pre-stage default door/interlock access —
            # safe because access.get_tags() only includes state="active"
            # profiles.
            if member_profile.subscription_status == "pending":
                member_profile.add_default_access()

                return Response(
                    {
                        "success": True,
                        "awaitingPayment": True,
                        "message": "signup.awaitingInvoicePayment",
                    }
                )

            member_profile.add_default_access()

            # activate() owns the welcome/access-enabled emails and SMS; it
            # is idempotent so a concurrent invoice.paid webhook cannot cause
            # duplicate notifications here.
            member_profile.activate()

            return Response({"success": True})

        return Response(
            {
                "success": False,
                "message": "signup.requirementsNotMet",
                "items": signupCheck["requiredSteps"],
            }
        )


class SkipSignup(APIView):
    """
    post: skips the billing/tier signup process if they just want an account
    """

    def post(self, request):
        profile = request.user.profile

        # Only valid as an opt-out from a brand-new signup. If the member
        # already has any kind of subscription (active, pending, cancelling)
        # flipping state to "accountonly" silently revokes their access
        # while Stripe keeps billing — caller must cancel the subscription
        # first via /api/billing/myplan/cancel/.
        if profile.state != "noob" or profile.subscription_status != "inactive":
            return Response(
                {
                    "success": False,
                    "message": "signup.skipNotAllowed",
                },
                status=status.HTTP_409_CONFLICT,
            )

        profile.set_account_only()

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
            s = stripe.Subscription.retrieve(
                request.user.profile.stripe_subscription_id,
                expand=["latest_invoice"],
            )

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


class PaymentPlanResumeCancel(StripeAPIView):
    """
    post: attempts to cancel a member's payment plan.
    """

    def post(self, request, resume):
        current_plan = request.user.profile.membership_plan
        resume = True if resume == "resume" else False

        if not current_plan:
            request.user.log_event(
                "Member tried to modify nonexistant membership plan.", "stripe"
            )
            return Response(
                {"success": False, "message": "paymentPlan.notExists"},
                status=status.HTTP_404_NOT_FOUND,
            )

        else:
            if resume and not request.user.profile.stripe_subscription_id:
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

                new_subscription = PaymentPlanSignup().create_subscription(
                    request, current_plan, billing_method
                )

                try:
                    if new_subscription.status == "active":
                        request.user.profile.stripe_subscription_id = (
                            new_subscription.id
                        )
                        request.user.profile.subscription_status = (
                            "pending" if billing_method == "invoice" else "active"
                        )
                        request.user.profile.save()

                        request.user.log_event(
                            "Successfully created subscription in Stripe.",
                            "stripe",
                            "",
                        )

                        return Response({"success": True})

                    elif new_subscription.status == "incomplete":
                        # if we got here, that means the subscription wasn't successfully created
                        request.user.log_event(
                            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                            "stripe",
                            "",
                        )

                        return Response(
                            {"success": True, "message": "signup.subscriptionFailed"}
                        )

                    else:
                        request.user.log_event(
                            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                            "stripe",
                            "",
                        )
                        return Response({"success": True})

                except KeyError as e:
                    capture_exception(e)
                    return new_subscription or e

            elif resume:
                modified_subscription = stripe.Subscription.modify(
                    request.user.profile.stripe_subscription_id,
                    cancel_at_period_end=False,
                )

                if not modified_subscription.cancel_at_period_end:
                    request.user.profile.subscription_status = "active"
                    request.user.profile.save()
                    subject = f"{request.user.get_full_name()} resumed their cancelling membership plan."
                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": subject,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )
                    return Response({"success": True})

                else:
                    subject = f"{request.user.get_full_name()} tried to resume their cancelling membership plan but it failed."
                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": subject,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )

            else:
                # Pending invoice subscription: void any open invoice(s) and cancel immediately.
                # Stripe does not auto-void open invoices when a subscription is cancelled, so
                # they would otherwise linger in the customer's Stripe portal.
                if request.user.profile.subscription_status == "pending":
                    subscription_id = request.user.profile.stripe_subscription_id
                    open_invoices = stripe.Invoice.list(
                        subscription=subscription_id, status="open"
                    )
                    for invoice in open_invoices.auto_paging_iter():
                        stripe.Invoice.void_invoice(invoice.id)

                    # No period has elapsed and nothing was paid, so we explicitly
                    # don't want Stripe to generate a final/proration invoice.
                    stripe.Subscription.delete(
                        subscription_id, invoice_now=False, prorate=False
                    )

                    # If this was a noob who never activated, drop the default
                    # door/interlock access that CompleteSignup pre-staged so we
                    # don't leave dangling M2M links. For returning members
                    # (state="inactive"), leave their historical access intact.
                    if request.user.profile.state == "noob":
                        request.user.profile.doors.clear()
                        request.user.profile.interlocks.clear()

                    request.user.profile.membership_plan = None
                    request.user.profile.stripe_subscription_id = None
                    request.user.profile.subscription_status = "inactive"
                    # billing_method is intentionally preserved — keeping the
                    # member's prior preference simplifies a future flow that
                    # lets them switch billing method directly.
                    request.user.profile.save()

                    request.user.log_event(
                        "Cancelled pending invoice subscription.", "stripe"
                    )
                    subject = f"{request.user.get_full_name()} cancelled their pending membership (no payment was made)."
                    send_email_to_admin(
                        subject=subject,
                        template_vars={"title": subject, "message": subject},
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    return Response({"success": True})

                modified_subscription = stripe.Subscription.modify(
                    request.user.profile.stripe_subscription_id,
                    cancel_at_period_end=True,
                )

                if modified_subscription.cancel_at_period_end == True:
                    request.user.profile.subscription_status = "cancelling"
                    request.user.profile.save()
                    subject = f"{request.user.get_full_name()} requested to cancel their membership plan."
                    description = "No further action is required, the subscription will automatically cancel at the end of the current billing period."

                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": description,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )

                    subject = "You've requested to cancel your membership plan."
                    description = "No further action is required, the subscription will automatically cancel at the end of the current billing period. You can cancel this request at any time from the member portal."
                    request.user.email_notification(subject, description)

                    request.user.log_event(
                        subject,
                        "stripe",
                    )
                    return Response({"success": True})

                else:
                    subject = f"{request.user.get_full_name()} requested to cancel their membership plan but it failed."

                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": "We're not sure what happened, you should check Stripe and contact the member.",
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )

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
            logger.error(e)
            capture_exception(e)
            return Response({"error": "Error validating Stripe signature."})

        data = event["data"]
        event_type = event["type"]
        event_id = event["id"]

        # Whole-handler transaction: the dedup row and any state changes
        # commit or roll back together. If processing raises after the dedup
        # row was inserted, the rollback releases the event id so Stripe's
        # retry can re-process — otherwise a partial failure would leave the
        # member permanently stuck (e.g. paid but never activated).
        # Trade-off: a retry can re-fire emails/SMS, but that is a far better
        # failure mode than a paid member with no access.
        with transaction.atomic():
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

            data = data["object"]

            # Some Stripe events (e.g. account-level ones) don't carry a customer
            # reference — we can't do anything useful with those.
            customer_id = data.get("customer")
            if not customer_id:
                return Response()

            try:
                # select_for_update serialises concurrent webhook deliveries
                # for the same member. Without it, two events with different
                # ids (e.g. an admin replay) can both read state != "active"
                # before either commits, and the "payment successful" email
                # at line 955 fires twice — activate()'s own lock catches
                # the state flip but not the surrounding notifications.
                member_profile = Profile.objects.select_for_update().get(
                    stripe_customer_id=customer_id
                )
            except Profile.DoesNotExist:
                # Stripe sends events for customers we don't track (e.g. one-off
                # charges, deleted profiles). Don't sentry-spam on these — info
                # log only, so we still have a trail without paging anyone.
                logger.info(
                    "Webhook event for unknown stripe_customer_id; ignoring."
                )
                return Response()
            except Profile.MultipleObjectsReturned as e:
                # stripe_customer_id is unique at the DB level, so this should
                # be impossible — capture loudly and bail.
                capture_exception(e)
                return Response()

            # Scope events to the member's current membership subscription —
            # the customer can have unrelated invoices/subscriptions (admin
            # one-offs, memberbucks charges, prior cancelled subs replayed by
            # Stripe, etc.) and acting on those would falsely activate the
            # member, send misleading "payment failed" emails, or wipe the
            # current subscription on a stale deletion event. The admin
            # "mark paid out-of-band" tool has the same guard.
            if event_type in ("invoice.paid", "invoice.payment_failed"):
                invoice_subscription = data.get("subscription")
                if (
                    not invoice_subscription
                    or invoice_subscription != member_profile.stripe_subscription_id
                ):
                    return Response()
            elif event_type == "customer.subscription.deleted":
                if data.get("id") != member_profile.stripe_subscription_id:
                    return Response()

            if event_type == "invoice.paid":
                invoice_status = data["status"]

                member_profile.user.log_event("Membership payment received.", "stripe")

                if (
                    invoice_status == "paid"
                    and not member_profile.subscription_first_created
                ):
                    member_profile.subscription_first_created = timezone.now()
                    member_profile.save()

                # If they aren't an active member, are allowed to signup, and have paid the invoice
                # then lets activate their account (this could be a new OR returning member)
                if (
                    member_profile.state != "active"
                    and member_profile.can_signup()["success"]
                    and invoice_status == "paid"
                ):
                    subject = "Your payment was successful."
                    message = (
                        "Thanks for making a membership payment using our online payment system. "
                        "You've already met all of the requirements for activating your site access. Please check "
                        "for another email message confirming this was successful."
                    )
                    member_profile.user.email_notification(subject, message)

                    # For invoice billing the member may pay the invoice (via
                    # the Stripe email link) before the frontend ever calls
                    # /complete-signup/ to pre-stage access. Stage defaults
                    # here so activate()'s sync_access actually pushes their
                    # tags.
                    if member_profile.billing_method == "invoice":
                        member_profile.add_default_access()

                    # set the subscription status to active
                    member_profile.subscription_status = "active"
                    member_profile.save()

                    # activate their access card
                    member_profile.activate()

                    member_profile.user.log_event(
                        "Activated membership because member met all requirements.",
                        "stripe",
                    )

                # If they aren't an active member, are NOT allowed to signup, and have paid the invoice
                # then we need to let them know and mark the subscription as active
                # (this could be a new OR returning member that's been too long since induction etc.)
                elif member_profile.state != "active" and invoice_status == "paid":
                    subject = "Your payment was successful."
                    message = (
                        "Thanks for making a membership payment using our online payment system. "
                        "You haven't yet met all of the requirements for automatically activating your site access. "
                        "You'll receive confirmation that your site access is enabled soon, or we'll be in touch. "
                        "If you don't hear from us soon or require assistance, please contact us."
                    )
                    member_profile.user.email_notification(subject, message)

                    member_profile.subscription_status = "active"
                    member_profile.save()

                    # if this is a returning member then send the exec an email (new members have
                    # already had this sent)
                    if member_profile.state != "noob":
                        subject = "Action Required: Verify returning member"
                        title = subject
                        message = (
                            "An existing member (or someone who clicked 'skip signup I just want an account') "
                            "has setup a membership subscription. You must now decide whether to enable their site access."
                        )
                        send_email_to_admin(
                            subject,
                            template_vars={
                                "title": title,
                                "message": message,
                            },
                            reply_to=member_profile.user.email,
                        )

                    member_profile.user.log_event(
                        "Did not activate membership because member did not meet all requirements.",
                        "stripe",
                    )

                # in all other instances, we don't care about a paid invoice and can ignore it

            if event_type == "invoice.payment_failed":
                subject = "Your membership payment failed"
                message = (
                    "Hi there, we tried to collect your membership payment but "
                    "weren't successful. Please update your billing method or contact "
                    "us if you need more time. We'll try again a few times, but if we're unable to "
                    "collect your payment soon, your membership may be cancelled."
                )

                member_profile.user.email_notification(subject, message)
                member_profile.user.log_event("Membership payment failed", "stripe")

            if event_type == "customer.subscription.deleted":
                # Void any invoices still open against this subscription. Stripe does
                # not auto-void them on cancellation, so without this they linger in
                # the customer's Stripe portal indefinitely. Safe for both card and
                # invoice billing — paid/void/uncollectible invoices are not listed.
                try:
                    open_invoices = stripe.Invoice.list(
                        subscription=data["id"], status="open"
                    )
                    for invoice in open_invoices.auto_paging_iter():
                        stripe.Invoice.void_invoice(invoice.id)
                except stripe.error.StripeError as e:
                    capture_exception(e)

                previous_state = member_profile.state

                if previous_state == "active":
                    # Member had site access — deactivate and notify.
                    subject = "Your membership has been cancelled"
                    message = (
                        "You will receive another email shortly confirming that your access has been deactivated. Your "
                        "membership was cancelled because we couldn't collect your payment, or you chose not to renew it."
                    )
                    member_profile.deactivate()
                    member_profile.user.email_notification(subject, message)

                    admin_subject = f"The membership for {member_profile.get_full_name()} was just cancelled"
                    admin_message = (
                        f"The Stripe subscription for {member_profile.get_full_name()} ended, so their membership has "
                        f"been cancelled. Their site access has been turned off."
                    )
                    send_email_to_admin(
                        admin_subject,
                        template_vars={
                            "title": admin_subject,
                            "message": admin_message,
                        },
                        reply_to=member_profile.user.email,
                        user=member_profile.user,
                    )
                elif previous_state == "noob":
                    # Signup lapsed without the member ever activating (e.g. invoice
                    # billing where the invoice went past due and Stripe auto-cancelled).
                    # They never had access — don't send "access disabled" messaging.
                    # Drop the default door/interlock rows that CompleteSignup
                    # pre-staged so they don't linger for a future re-enrolment.
                    member_profile.doors.clear()
                    member_profile.interlocks.clear()

                    subject = "Your membership signup has lapsed"
                    message = (
                        "We weren't able to collect your membership payment in time, "
                        "so your pending signup has been cancelled. You can sign up "
                        "again at any time from the member portal."
                    )
                    member_profile.user.email_notification(subject, message)
                # state in {"inactive", "accountonly"}: quiet cleanup only — they
                # already lacked access (or opted out), so no notification fires.

                member_profile.membership_plan = None
                member_profile.stripe_subscription_id = None
                member_profile.subscription_status = "inactive"
                member_profile.save()

                member_profile.user.log_event(
                    "Membership was cancelled due to Stripe subscription ending",
                    "stripe",
                )

        return Response()
