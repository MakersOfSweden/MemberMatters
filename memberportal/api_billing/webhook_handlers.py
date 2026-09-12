"""Per-event handlers for the Stripe webhook.

`StripeWebhook.post` (api_billing/views.py) owns the transport concerns —
signature verification, the profile row lock, scoping and idempotency — and
then dispatches here. Each handler runs inside that transaction with the
member's Profile row already locked, so all external I/O (emails, SMS,
activate/deactivate, Stripe calls) must be deferred with
`transaction.on_commit`; anything synchronous would hold the row lock for the
duration of the upstream call and can blow past Stripe's ~30s webhook timeout.
"""

import dataclasses
import enum
import logging

import stripe
from constance import config
from django.db import transaction
from django.utils import timezone
from sentry_sdk import capture_exception

from profile.models import CancelTriggeredBy, SignupTriggeredBy
from services.emails import send_email_to_admin

from .stripe_utils import invoice_subscription_id, is_subscription_invoice

logger = logging.getLogger("billing")


class UnrecognisedInvoiceSchema(Exception):
    """A subscription invoice exposed no subscription id under either schema."""


class EventScope(enum.Enum):
    IN_SCOPE = "in_scope"
    IGNORE = "ignore"


@dataclasses.dataclass(frozen=True)
class WebhookContext:
    event_id: str
    event_type: str
    data: dict
    profile: "Profile"  # noqa: F821 — already select_for_update()'d by the view


def classify_event_scope(event_type, data, profile):
    """Decide whether an event concerns the member's current subscription.

    The customer may own unrelated invoices/subs (admin one-offs, memberbucks,
    replayed cancelled subs) that we must not act on.
    """
    if event_type == "customer.subscription.deleted":
        if data.get("id") != profile.stripe_subscription_id:
            return EventScope.IGNORE
        return EventScope.IN_SCOPE

    subscription_id = invoice_subscription_id(data)
    if not subscription_id:
        # A one-off invoice with no subscription is ordinary and ignorable.
        # But if Stripe's own billing_reason says a subscription generated
        # this invoice and we still couldn't find its id, the endpoint's API
        # version has moved past what invoice_subscription_id() knows how to
        # read. Say so loudly — the silent failure mode is that every renewal
        # is dropped while the endpoint keeps answering 200.
        if is_subscription_invoice(data):
            message = (
                f"{event_type} for invoice {data.get('id')} has "
                f"billing_reason={data.get('billing_reason')!r} but exposes no "
                "subscription id under either payload schema. Check the API "
                "version on the Stripe webhook endpoint."
            )
            logger.error(message)
            capture_exception(UnrecognisedInvoiceSchema(message))
        return EventScope.IGNORE

    if subscription_id != profile.stripe_subscription_id:
        return EventScope.IGNORE
    return EventScope.IN_SCOPE


def handle_invoice_paid(ctx):
    profile = ctx.profile
    data = ctx.data
    invoice_status = data["status"]

    profile.user.log_event("Membership payment received.", "stripe")

    if invoice_status == "paid" and not profile.subscription_first_created:
        profile.subscription_first_created = timezone.now()
        profile.save(update_fields=["subscription_first_created"])

    # A state_locked member is by invariant subscription_status=inactive.
    # If an invoice.paid arrives anyway (late/out-of-order delivery, or
    # an admin manually marked an old invoice paid in Stripe), preserve
    # the lock — do NOT flip subscription_status to "active" and do
    # NOT auto-activate. Notify the admin so they can investigate.
    if profile.state_locked and profile.state != "active" and invoice_status == "paid":
        profile.user.log_event(
            "Invoice paid for a state_locked member — held; "
            "admin must unlock + reconcile.",
            "stripe",
        )

        held_full_name = profile.get_full_name()
        held_user_email = profile.user.email

        def _on_commit_locked_paid_admin(
            full_name=held_full_name,
            user_email=held_user_email,
            user=profile.user,
        ):
            admin_subject = (
                f"Action Required: locked member {full_name} had an invoice paid"
            )
            admin_message = (
                f"{full_name} ({user_email}) is currently "
                "state-locked, but Stripe just reported a paid "
                "invoice on their subscription. The portal has "
                "NOT activated them. Investigate whether to "
                "unlock + activate, or to void the Stripe "
                "subscription."
            )
            try:
                send_email_to_admin(
                    subject=admin_subject,
                    template_vars={
                        "title": admin_subject,
                        "message": admin_message,
                    },
                    user=user,
                    reply_to=user.email,
                )
            except Exception as e:
                capture_exception(e)

        transaction.on_commit(_on_commit_locked_paid_admin)

    # If they aren't an active member, are allowed to signup, and have paid the invoice
    # then lets activate their account (this could be a new OR returning member)
    elif (
        profile.state != "active"
        and profile.can_signup()["success"]
        and invoice_status == "paid"
    ):
        profile.subscription_status = "active"
        profile.save(update_fields=["subscription_status"])

        profile.user.log_event(
            "Activated membership because member met all requirements.",
            "stripe",
        )

        # Both callbacks deferred to on_commit so the I/O can't
        # extend the row lock past Stripe's 30s webhook timeout.
        # The paid-confirmation email is registered first so it
        # arrives before activate()'s welcome email — the body
        # references "another email message confirming this was
        # successful" which is the welcome that follows.
        paid_subject = "Your payment was successful."
        paid_message = (
            "Thanks for making a membership payment using our "
            "online payment system. You've already met all of "
            "the requirements for activating your site access. "
            "Please check for another email message confirming "
            "this was successful."
        )

        def _on_commit_paid_email(
            user=profile.user,
            subject=paid_subject,
            message=paid_message,
        ):
            try:
                user.email_notification(subject, message)
                user.log_event(
                    "Payment-received email sent.",
                    "email",
                )
            except Exception as e:
                capture_exception(e)

        transaction.on_commit(_on_commit_paid_email)

        def _on_commit_paid_activate(profile=profile):
            try:
                profile.complete_signup(SignupTriggeredBy.INVOICE_PAID)
            except Exception as e:
                capture_exception(e)

        transaction.on_commit(_on_commit_paid_activate)

    # If they aren't an active member, are NOT allowed to signup, and have paid the invoice
    # then we need to let them know and mark the subscription as active
    # (this could be a new OR returning member that's been too long since induction etc.)
    elif profile.state != "active" and invoice_status == "paid":
        profile.subscription_status = "active"
        profile.save(update_fields=["subscription_status"])

        profile.user.log_event(
            "Did not activate membership because member did not meet all requirements.",
            "stripe",
        )

        paid_subject = "Your payment was received — additional steps needed"
        paid_message = (
            "Thanks for making a membership payment using our "
            "online payment system. Your access isn't enabled yet "
            "because you still need to complete your induction. "
            f"Please log in to {config.SITE_URL} and finish the "
            "induction step to activate your membership."
        )
        # Capture at decision time — state may shift before on_commit fires.
        notify_admin = profile.state != "noob"

        def _on_commit_paid_no_activate(
            profile=profile,
            subject=paid_subject,
            message=paid_message,
            notify_admin=notify_admin,
        ):
            # See _on_commit_paid_activate for why each call
            # is wrapped independently.
            try:
                profile.user.email_notification(subject, message)
            except Exception as e:
                capture_exception(e)
            if notify_admin:
                admin_subject = "Action Required: Verify returning member"
                admin_message = (
                    "An existing member (or someone who clicked 'skip signup I just want an account') "
                    "has setup a membership subscription. You must now decide whether to enable their site access."
                )
                try:
                    send_email_to_admin(
                        admin_subject,
                        template_vars={
                            "title": admin_subject,
                            "message": admin_message,
                        },
                        reply_to=profile.user.email,
                    )
                except Exception as e:
                    capture_exception(e)

        transaction.on_commit(_on_commit_paid_no_activate)

    # in all other instances, we don't care about a paid invoice and can ignore it


def handle_invoice_payment_failed(ctx):
    profile = ctx.profile

    profile.user.log_event("Membership payment failed", "stripe")

    failed_subject = "Your membership payment failed"
    failed_message = (
        "Hi there, we tried to collect your membership payment but "
        "weren't successful. Please update your billing method or contact "
        "us if you need more time. We'll try again a few times, but if we're unable to "
        "collect your payment soon, your membership may be cancelled."
    )

    def _on_commit_payment_failed(
        profile=profile,
        subject=failed_subject,
        message=failed_message,
    ):
        try:
            profile.user.email_notification(subject, message)
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_on_commit_payment_failed)


def handle_subscription_deleted(ctx):
    profile = ctx.profile
    deleted_subscription_id = ctx.data["id"]
    full_name = profile.get_full_name()

    profile.membership_plan = None
    profile.stripe_subscription_id = None
    profile.subscription_status = "inactive"
    profile.save(
        update_fields=[
            "membership_plan",
            "stripe_subscription_id",
            "subscription_status",
        ]
    )

    # Void open invoices — Stripe doesn't auto-void on cancel.
    # On on_commit so the Stripe call can't extend the row lock.
    # If voiding fails, the deleted subscription's open invoices
    # may still be visible to the customer in Stripe — email
    # admin so they can void manually.
    def _on_commit_void_open_invoices(
        subscription_id=deleted_subscription_id,
        user=profile.user,
        full_name=full_name,
    ):
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
                        f"{invoice.id} after subscription cancel.",
                        "stripe",
                        str(e),
                    )
                    failure_subject = (
                        f"Action Required: void Stripe invoice "
                        f"{invoice.id} for {full_name}"
                    )
                    failure_message = (
                        f"The Stripe subscription "
                        f"{subscription_id} for {full_name} "
                        "was cancelled, but voiding open "
                        f"invoice {invoice.id} failed. Please "
                        "void it manually in Stripe so the "
                        "customer isn't shown an unpaid "
                        "invoice."
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
        except stripe.error.StripeError as e:
            # Couldn't even list invoices — don't know which
            # are open, so ask admin to audit the cancelled
            # sub.
            capture_exception(e)
            user.log_event(
                f"Failed to list open invoices for cancelled "
                f"subscription {subscription_id}; admin must "
                "audit Stripe manually.",
                "stripe",
                str(e),
            )
            failure_subject = (
                f"Action Required: audit cancelled Stripe "
                f"subscription {subscription_id} for {full_name}"
            )
            failure_message = (
                f"The Stripe subscription {subscription_id} "
                f"for {full_name} was cancelled, but we "
                "couldn't list its open invoices to void "
                "them. Please check Stripe and void any "
                "open invoices manually."
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

    transaction.on_commit(_on_commit_void_open_invoices)

    # Notify the operator that this member's Stripe sub ended out
    # of band. Stripe-specific messaging stays here, not in
    # complete_cancel. Registered before the complete_cancel
    # callback so it lands before the member-facing access-
    # disabled email that deactivate() sends.
    admin_cancel_subject = f"The membership for {full_name} was just cancelled"
    admin_cancel_message = (
        f"The Stripe subscription for {full_name} ended, so "
        "their membership has been cancelled. Their site "
        "access has been turned off."
    )

    def _on_commit_admin_cancel_email(
        user=profile.user,
        subject=admin_cancel_subject,
        message=admin_cancel_message,
    ):
        try:
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": message},
                user=user,
                reply_to=user.email,
            )
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_on_commit_admin_cancel_email)

    def _on_commit_complete_cancel(profile=profile):
        try:
            profile.complete_cancel(CancelTriggeredBy.SUBSCRIPTION_DELETED)
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(_on_commit_complete_cancel)


HANDLERS = {
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_invoice_payment_failed,
    "customer.subscription.deleted": handle_subscription_deleted,
}
