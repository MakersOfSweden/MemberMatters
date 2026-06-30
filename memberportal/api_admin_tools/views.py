import json
from datetime import datetime

import stripe
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from constance import config
from constance.backends.database.models import Constance as ConstanceSetting
from django.db import IntegrityError, transaction
from django.db.models import F, Sum, Value, CharField, Count, Max
from django.db.models.functions import Concat
from django.db.utils import OperationalError
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework import permissions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey
from sentry_sdk import capture_exception
from sentry_sdk import capture_message

from access import models
from access.models import DoorLog, InterlockLog
from api_billing.views import (
    ensure_stripe_customer,
    _email_admin_cancel_failed,
)
from memberbucks.models import (
    MemberBucks,
    MemberbucksProductPurchaseLog,
)
from profile.models import (
    Profile,
    SignupTriggeredBy,
    CancelTriggeredBy,
    User,
    UserEventLog,
)
from profile.phone import to_e164
from services import sms
from services.emails import send_email_to_admin
from .models import MemberTier, PaymentPlan


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
        except OperationalError as error:
            capture_exception(error)


class GetMembers(APIView):
    """
    get: This method returns a list of members.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request):
        filtered = []

        members_queryset = User.objects.select_related("profile")

        screenName = request.GET.get("screenName")
        if screenName is not None:
            members_queryset = members_queryset.filter(profile__screen_name=screenName)

        members = members_queryset.all()

        for member in members:
            filtered.append(member.profile.get_basic_profile())

        return Response(filtered)


class MakeMember(APIView):
    """
    post: Activate a member ("Make Member") — admin override.

    Deactivation is not handled here — it flows through
    MemberCancelMembership.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        result = member.profile.complete_signup(
            SignupTriggeredBy.ADMIN_OVERRIDE_ACTIVATE,
            request=request,
        )
        return Response({"success": True, "outcome": result.outcome.value})


class MemberAdminDisabledAccess(APIView):
    """
    post: Pause/resume a member's door access (admin override).

    Orthogonal to state / subscription_status — flips the
    `admin_disabled_access` flag so an operator can revoke access during a
    dispute or pause without cancelling billing. Body: {"disabled": true|false}
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        disabled = request.data.get("disabled")
        if not isinstance(disabled, bool):
            return Response(status=status.HTTP_400_BAD_REQUEST)
        member.profile.set_admin_disabled_access(disabled, request=request)
        return Response({"success": True})


class MemberCancelMembership(StripeAPIView):
    """
    post: Admin cancels a member's membership.

    Body: {"timing": "at_period_end" | "immediately"}

    With a live Stripe subscription, orchestrates the Stripe cancel here
    then complete_cancel(ADMIN_OVERRIDE_CANCEL) reacts on the profile
    side; "immediately" records a "Xd Yh remaining" audit entry. With no
    live subscription, deactivates the member directly.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        profile = member.profile

        # No live subscription (Stripe disabled, or never subscribed):
        # nothing to cancel in Stripe, so just deactivate the member.
        if not profile.stripe_subscription_id:
            profile.complete_cancel(
                CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL, request=request
            )
            admin_subject = (
                f"{request.user.get_full_name()} cancelled "
                f"{profile.get_full_name()}'s membership (no live subscription)."
            )
            try:
                send_email_to_admin(
                    subject=admin_subject,
                    template_vars={
                        "title": admin_subject,
                        "message": admin_subject,
                    },
                    user=request.user,
                    reply_to=request.user.email,
                )
            except Exception as e:
                capture_exception(e)
            return Response({"success": True})

        timing = request.data.get("timing", "at_period_end")
        if timing not in ("at_period_end", "immediately"):
            return Response(
                {"success": False, "message": "billing.invalidTiming"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if timing == "at_period_end":
            return self._cancel_at_period_end(request, profile)
        return self._cancel_immediately(request, profile)

    def _cancel_at_period_end(self, request, profile):
        # Schedule cancel-at-period-end on Stripe. complete_cancel is NOT
        # called yet — the actual deactivation flows through
        # customer.subscription.deleted when the period ends.
        failed = False
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=profile.pk)

            if not locked.stripe_subscription_id:
                return Response(
                    {"success": False, "message": "paymentPlan.notExists"},
                    status=status.HTTP_409_CONFLICT,
                )

            try:
                modified = stripe.Subscription.modify(
                    locked.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
                failed = True
            else:
                if not modified.cancel_at_period_end:
                    failed = True
                else:
                    locked.subscription_status = "cancelling"
                    locked.save(update_fields=["subscription_status"])

                    locked.user.log_event(
                        f"Admin scheduled membership cancellation at "
                        f"period end (by {request.user.get_full_name()}).",
                        "admin",
                    )

                    member_subject = "Your membership cancellation is scheduled"
                    member_message = (
                        "An admin has scheduled your membership to cancel at "
                        "the end of the current billing period. Your access "
                        "continues until then."
                    )
                    admin_subject = (
                        f"{request.user.get_full_name()} cancelled "
                        f"{locked.get_full_name()}'s membership (at period end)."
                    )
                    actor = request.user
                    member_user = locked.user

                    def _on_commit_notifications():
                        try:
                            member_user.email_notification(
                                member_subject, member_message
                            )
                        except Exception as e:
                            capture_exception(e)
                        try:
                            send_email_to_admin(
                                subject=admin_subject,
                                template_vars={
                                    "title": admin_subject,
                                    "message": admin_subject,
                                },
                                user=actor,
                                reply_to=actor.email,
                            )
                        except Exception as e:
                            capture_exception(e)

                    transaction.on_commit(_on_commit_notifications)
                    return Response({"success": True})

        if failed:
            _email_admin_cancel_failed(request.user)
        return Response({"success": False})

    def _cancel_immediately(self, request, profile):
        # Immediate cancel: capture period_end for the audit "Xd Yh remaining"
        # line, do Stripe-side cleanup (void invoices + Subscription.delete)
        # on_commit, then call complete_cancel(ADMIN_OVERRIDE_CANCEL) for the
        # profile-side reaction.
        with transaction.atomic():
            locked = Profile.objects.select_for_update().get(pk=profile.pk)

            if not locked.stripe_subscription_id:
                return Response(
                    {"success": False, "message": "paymentPlan.notExists"},
                    status=status.HTTP_409_CONFLICT,
                )

            subscription_id = locked.stripe_subscription_id
            full_name = locked.get_full_name()

            # Capture current_period_end so operators have the unused window
            # for prorated refunds. If Stripe is unreachable we still cancel
            # locally — the remaining line just gets omitted.
            period_end_dt = None
            try:
                stripe_sub = stripe.Subscription.retrieve(subscription_id)
                period_end_ts = getattr(stripe_sub, "current_period_end", None)
                if period_end_ts:
                    period_end_dt = datetime.fromtimestamp(
                        period_end_ts, tz=timezone.utc
                    )
            except stripe.error.StripeError as e:
                capture_exception(e)

            locked.membership_plan = None
            locked.stripe_subscription_id = None
            locked.subscription_status = "inactive"
            locked.save(
                update_fields=[
                    "membership_plan",
                    "stripe_subscription_id",
                    "subscription_status",
                ]
            )

            if period_end_dt:
                remaining = period_end_dt - timezone.now()
                if remaining.total_seconds() > 0:
                    days = remaining.days
                    hours = remaining.seconds // 3600
                    locked.user.log_event(
                        f"Admin cancelled membership immediately with "
                        f"{days}d {hours}h remaining on the current billing "
                        f"period (period_end={period_end_dt.isoformat()}).",
                        "stripe",
                    )

            member_subject = "Your membership has been cancelled"
            member_message = (
                "An admin has cancelled your membership effective "
                "immediately. Your subscription has been ended and any open "
                "invoices voided. If this is unexpected, please let us know."
            )
            admin_subject = (
                f"{request.user.get_full_name()} cancelled "
                f"{full_name}'s membership (immediately)."
            )
            actor = request.user
            member_user = locked.user

            # Registered before _on_commit_stripe_cleanup / _on_commit_complete_cancel
            # so the explanation email lands before deactivate()'s access-
            # disabled notification, matching the at-period-end ordering.
            def _on_commit_notifications():
                try:
                    member_user.email_notification(member_subject, member_message)
                except Exception as e:
                    capture_exception(e)
                try:
                    send_email_to_admin(
                        subject=admin_subject,
                        template_vars={
                            "title": admin_subject,
                            "message": admin_subject,
                        },
                        user=actor,
                        reply_to=actor.email,
                    )
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_on_commit_notifications)

            def _on_commit_stripe_cleanup(
                subscription_id=subscription_id,
                user=locked.user,
                full_name=full_name,
            ):
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
                        stripe.Subscription.delete(
                            subscription_id, invoice_now=False, prorate=False
                        )
                    except stripe.error.StripeError as e:
                        capture_exception(e)
                        user.log_event(
                            f"Failed to delete subscription {subscription_id} "
                            "on Stripe after admin DB cancel; manual cleanup "
                            "required.",
                            "stripe",
                        )
                        failure_subject = (
                            f"Action Required: clean up Stripe subscription "
                            f"{subscription_id} for {full_name}"
                        )
                        failure_message = (
                            f"An admin cancelled {full_name}'s membership in "
                            "the portal, but the Stripe-side cleanup failed. "
                            f"Subscription {subscription_id} and any open "
                            "invoices may still be live in Stripe — please "
                            "void/delete them manually."
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

            def _on_commit_complete_cancel(profile=locked):
                try:
                    profile.complete_cancel(
                        CancelTriggeredBy.ADMIN_OVERRIDE_CANCEL,
                        request=request,
                    )
                except Exception as e:
                    capture_exception(e)

            transaction.on_commit(_on_commit_complete_cancel)

        return Response({"success": True})


class MemberStateLock(APIView):
    """
    post: Lock or unlock a member's state against automated changes.

    Body: {"locked": true|false}. Locking is refused (409) for an active
    member or one with a live subscription — see Profile.set_state_locked
    and the state_locked invariant.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        locked = request.data.get("locked")
        if not isinstance(locked, bool):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if not member.profile.set_state_locked(locked, request=request):
            return Response(
                {"success": False, "message": "adminTools.lockNotAllowed"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response({"success": True})


class Doors(APIView):
    """
    get: returns a list of doors.
    put: updates a specific door.
    delete: deletes a specific door.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        doors = models.Doors.objects.all()

        def get_door(door):
            logs = models.DoorLog.objects.filter(door_id=door.id)

            # Query to get the statistics
            stats = (
                logs.select_related("user__profile")
                .values("door_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("door_id"),
                    last_swipe=Max("date"),
                )
                .order_by("-total_swipes")
            )

            return {
                "id": door.id,
                "name": door.name,
                "description": door.description,
                "ipAddress": door.ip_address,
                "serialNumber": door.serial_number,
                "lastSeen": door.last_seen,
                "offline": door.get_unavailable(),
                "defaultAccess": door.all_members,
                "maintenanceLockout": door.locked_out,
                "playThemeOnSwipe": door.play_theme,
                "postDiscordOnSwipe": door.post_to_discord,
                "postSlackOnSwipe": door.post_to_slack,
                "exemptFromSignin": door.exempt_signin,
                "hiddenToMembers": door.hidden,
                "totalSwipes": logs.count(),
                "userStats": stats,
            }

        return Response(map(get_door, doors))

    def put(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if door.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if door.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        door.name = data.get("name")
        door.description = data.get("description")
        door.ip_address = data.get("ipAddress")
        door.serial_number = data.get("serialNumber")
        door.all_members = data.get("defaultAccess")
        door.locked_out = data.get("maintenanceLockout")
        door.play_theme = data.get("playThemeOnSwipe")
        door.post_to_discord = data.get("postDiscordOnSwipe")
        door.post_to_slack = data.get("postSlackOnSwipe")
        door.exempt_signin = data.get("exemptFromSignin")
        door.hidden = data.get("hiddenToMembers")
        door.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.doors.add(door)
                else:
                    member.profile.doors.remove(door)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or door.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            door.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        door.delete()

        return Response()


class Interlocks(APIView):
    """
    get: returns a list of interlocks.
    put: update a specific interlock.
    delete: delete a specific interlock.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        interlocks = models.Interlock.objects.all()

        def get_interlock(interlock):
            # Calculate total on time
            logs = InterlockLog.objects.filter(interlock_id=interlock.id)
            total_time = logs.aggregate(total_time=Sum("total_time")).get("total_time")
            total_time_seconds = total_time.total_seconds() if total_time else 0

            # Retrieve stats
            stats = (
                logs.select_related("user_started__profile")
                .values("interlock_id")
                .annotate(
                    screen_name=F("user_started__profile__screen_name"),
                    full_name=Concat(
                        F("user_started__profile__first_name"),
                        Value(" "),
                        F("user_started__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("total_time"),
                    total_seconds=Sum("total_time"),
                )
                .order_by("-total_seconds", "-total_swipes")
            )

            return {
                "id": interlock.id,
                "authorised": interlock.authorised,
                "name": interlock.name,
                "description": interlock.description,
                "ipAddress": interlock.ip_address,
                "lastSeen": interlock.last_seen,
                "offline": interlock.get_unavailable(),
                "defaultAccess": interlock.all_members,
                "maintenanceLockout": interlock.locked_out,
                "playThemeOnSwipe": interlock.play_theme,
                "exemptFromSignin": interlock.exempt_signin,
                "hiddenToMembers": interlock.hidden,
                "totalTimeSeconds": total_time_seconds,
                "userStats": list(stats),
            }

        return Response(map(get_interlock, interlocks))

    def put(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if interlock.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if interlock.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        interlock.name = data.get("name")
        interlock.description = data.get("description")
        interlock.ip_address = data.get("ipAddress")
        interlock.all_members = data.get("defaultAccess")
        interlock.locked_out = data.get("maintenanceLockout")
        interlock.play_theme = data.get("playThemeOnSwipe")
        interlock.exempt_signin = data.get("exemptFromSignin")
        interlock.hidden = data.get("hiddenToMembers")
        interlock.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.interlocks.add(interlock)
                else:
                    member.profile.interlocks.remove(interlock)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or interlock.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            interlock.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        interlock.delete()

        return Response()


class MemberbucksDevices(APIView):
    """
    get: returns a list of memberbucks devices.
    put: update a specific memberbucks device.
    delete: delete a specific memberbucks device.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        devices = models.MemberbucksDevice.objects.all()

        def get_device(device):
            # Calculate total transaction volume
            purchases = MemberbucksProductPurchaseLog.objects.filter(
                memberbucks_device_id=device.id, success=True
            )
            total_count = purchases.count()
            total_volume = (
                purchases.aggregate(total_volume=Sum("price")).get("total_volume") or 0
            ) / 100

            # Retrieve stats
            stats = (
                purchases.select_related("user__profile")
                .values("memberbucks_device_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_purchases=Count("price"),
                    total_volume=(Sum("price") or 0) / 100,
                )
                .order_by("-total_purchases", "-total_volume")
            )

            return {
                "id": device.id,
                "authorised": device.authorised,
                "name": device.name,
                "description": device.description,
                "ipAddress": device.ip_address,
                "lastSeen": device.last_seen,
                "offline": device.get_unavailable(),
                "defaultAccess": device.all_members,
                "maintenanceLockout": device.locked_out,
                "playThemeOnSwipe": device.play_theme,
                "exemptFromSignin": device.exempt_signin,
                "hiddenToMembers": device.hidden,
                "totalPurchases": total_count,
                "totalVolume": total_volume,
                "userStats": list(stats),
            }

        return Response(map(get_device, devices))

    def put(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)

        data = request.data

        device.name = data.get("name")
        device.description = data.get("description")
        device.ip_address = data.get("ipAddress")

        device.all_members = data.get("defaultAccess")
        device.locked_out = data.get("maintenanceLockout")
        device.play_theme = data.get("playThemeOnSwipe")
        device.exempt_signin = data.get("exemptFromSignin")
        device.hidden = data.get("hiddenToMembers")

        device.save()

        return Response()

    def delete(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)
        device.delete()

        return Response()


class MemberAccess(APIView):
    """
    get: This method gets a member's access permissions.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)

        return Response(member.profile.get_access_permissions(ignore_user_state=True))


class MemberWelcomeEmail(APIView):
    """
    post: This method sends a welcome email to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        member.email_welcome()

        return Response()


class MemberSendSms(APIView):
    """
    post: This method sends a custom sms alert to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        sms_body = request.data["smsBody"]

        if not config.SMS_ENABLE:
            return Response(
                {"success": False, "message": "SMS functionality not enabled."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not member.profile.phone:
            return Response(
                {"success": False, "message": "Member does not have a phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # check if the sms body exists, is at least 1 character, and isn't more than 320 characters
        if not sms_body or len(sms_body) < 1 or len(sms_body) > 320:
            return Response(
                {"success": False, "message": "SMS body is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sms_message = sms.SMS()
        sms_message.send_custom_notification(
            to_number=member.profile.phone,
            message=sms_body,
            portal_user_sender=request.user,
            portal_user_recipient=member,
        )

        return Response()


class MemberEnsureStripeCustomer(StripeAPIView):
    """
    post: This method ensures that a Stripe customer exists for the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = get_object_or_404(User, id=member_id)

        ok, err = ensure_stripe_customer(member)
        if ok:
            return Response(
                {
                    "success": True,
                    "message": f"Stripe customer exists with ID: {member.profile.stripe_customer_id}",
                }
            )
        else:
            return Response(
                {
                    "success": False,
                    "message": "Failed to create Stripe customer. Please try again later.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class RFIDCheck(APIView):
    """
    get: Checks whether an RFID value is already assigned to another member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        rfid = request.GET.get("rfid", "").strip()
        exclude_member_id = request.GET.get("excludeMemberId")

        if not rfid:
            return Response({"inUse": False})

        query = Profile.objects.filter(rfid=rfid)
        if exclude_member_id:
            query = query.exclude(user_id=exclude_member_id)

        existing = query.first()
        if existing:
            return Response({"inUse": True, "usedBy": existing.get_full_name()})

        return Response({"inUse": False})


class MemberProfile(APIView):
    """
    put: This method updates a member's profile.
    """

    permission_classes = (permissions.IsAdminUser,)

    def put(self, request, member_id):
        if not member_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = json.loads(request.body)
        member = get_object_or_404(User, id=member_id)

        rfid = (body.get("rfidCard") or "").strip() or None
        rfid_changed = member.profile.rfid != rfid

        if (
            rfid
            and rfid_changed
            and Profile.objects.filter(rfid=rfid).exclude(user_id=member_id).exists()
        ):
            return Response(
                {"message": "validation.rfidAlreadyInUse"},
                status=status.HTTP_409_CONFLICT,
            )

        # Empty string maps to NULL so unset handles don't collide on the
        # case-insensitive unique constraint.
        screen_name = (body.get("screenName") or "").strip() or None
        email = (body.get("email") or "").lower()

        if (
            email
            and User.objects.filter(email__iexact=email).exclude(pk=member.pk).exists()
        ):
            return Response(
                {"message": "error.accountAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        if (
            screen_name
            and Profile.objects.filter(screen_name__iexact=screen_name)
            .exclude(pk=member.profile.pk)
            .exists()
        ):
            return Response(
                {"message": "error.screenNameAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        # Store the phone number in E.164 format.
        phone = (body.get("phone") or "").strip()
        if phone:
            try:
                phone = to_e164(phone, config.PROFILE_DEFAULT_PHONE_REGION)
            except ValueError:
                return Response(
                    {"message": "validation.invalidPhone"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        member.email = email
        member.profile.first_name = body.get("firstName")
        member.profile.last_name = body.get("lastName")
        member.profile.rfid = rfid
        member.profile.phone = phone
        member.profile.screen_name = screen_name
        member.profile.vehicle_registration_plate = body.get("vehicleRegistrationPlate")
        member.profile.exclude_from_email_export = body.get("excludeFromEmailExport")

        try:
            with transaction.atomic():
                member.save()
                member.profile.save()
        except IntegrityError:
            if (
                email
                and User.objects.filter(email__iexact=email)
                .exclude(pk=member.pk)
                .exists()
            ):
                return Response(
                    {"message": "error.accountAlreadyExists"},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"message": "error.screenNameAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        if rfid_changed:
            for door in member.profile.doors.all():
                door.sync()

        return Response()


class ManageMembershipTier(StripeAPIView):
    """
    get: gets a membership tier.
    post: creates a new membership tier.
    put: updates a membership tier.
    delete: deletes a membership tier.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_tier(self, tier: MemberTier):
        return {
            "id": tier.id,
            "name": tier.name,
            "description": tier.description,
            "visible": tier.visible,
            "featured": tier.featured,
            "stripeId": tier.stripe_id,
        }

    def get(self, request, tier_id=None):
        if tier_id:
            try:
                tier = MemberTier.objects.get(pk=tier_id)
                return Response(self.get_tier(tier))

            except MemberTier.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_tiers = []

            for tier in MemberTier.objects.all():
                formatted_tiers.append(self.get_tier(tier))

            return Response(formatted_tiers)

    def post(self, request):
        body = request.data

        try:
            product = stripe.Product.create(
                name=body["name"], description=body["description"]
            )
            tier = MemberTier.objects.create(
                name=body["name"],
                description=body["description"],
                visible=body["visible"],
                featured=body["featured"],
                stripe_id=product.id,
            )

            return Response(self.get_tier(tier))

        except stripe.error.AuthenticationError:
            return Response(
                {"success": False, "message": "error.stripeNotConfigured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, tier_id):
        body = request.data

        tier = MemberTier.objects.get(pk=tier_id)

        tier.name = body["name"]
        tier.description = body["description"]
        tier.visible = body["visible"]
        tier.featured = body["featured"]
        tier.save()

        return Response(self.get_tier(tier))

    def delete(self, request, tier_id):
        tier = MemberTier.objects.get(pk=tier_id)
        tier.delete()

        return Response()


class ManageMembershipTierPlan(StripeAPIView):
    """
    get: gets an individual or a list of payment plans.
    post: creates a new payment plan.

    """

    permission_classes = (permissions.IsAdminUser,)

    def get_plan(self, plan: PaymentPlan):
        return {
            "id": plan.id,
            "name": plan.name,
            "description": plan.description,
            "stripeId": plan.stripe_id,
            "memberTier": plan.member_tier.id,
            "visible": plan.visible,
            "currency": plan.currency,
            "cost": plan.cost / 100,  # convert to dollars
            "intervalCount": plan.interval_count,
            "interval": plan.interval,
        }

    def get(self, request, plan_id=None, tier_id=None):
        if plan_id:
            try:
                plan = PaymentPlan.objects.get(pk=plan_id)
                return Response(self.get_plan(plan))

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        if tier_id:
            try:
                formatted_plans = []

                for plan in PaymentPlan.objects.filter(member_tier=tier_id):
                    formatted_plans.append(self.get_plan(plan))

                return Response(formatted_plans)

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_plans = []

            for plan in PaymentPlan.objects.all():
                formatted_plans.append(self.get_plan(plan))

            return Response(formatted_plans)

    def post(self, request, tier_id=None):
        if tier_id is not None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        member_tier = MemberTier.objects.get(pk=body["memberTier"])

        stripe_plan = stripe.Price.create(
            unit_amount=round(body["cost"]),
            currency=str(body["currency"]).lower(),
            recurring={
                "interval": body["interval"],
                "interval_count": body["intervalCount"],
            },
            product=member_tier.stripe_id,
        )

        plan = PaymentPlan.objects.create(
            name=body["name"],
            description=body.get("description", ""),
            stripe_id=stripe_plan.id,
            member_tier_id=body["memberTier"],
            visible=body["visible"],
            currency=str(body["currency"]).lower(),
            cost=round(body["cost"]),
            interval_count=body["intervalCount"],
            interval=body["interval"],
        )

        return Response(self.get_plan(plan))

    def put(self, request, plan_id):
        body = request.data

        plan = PaymentPlan.objects.get(pk=plan_id)

        plan.name = body["name"]
        plan.description = body.get("description", "")
        plan.visible = body["visible"]
        plan.cost = body["cost"]
        plan.save()

        return Response(self.get_plan(plan))

    def delete(self, request, plan_id):
        plan = PaymentPlan.objects.get(pk=plan_id)
        plan.delete()

        return Response()


class MemberBillingInfo(StripeAPIView):
    """
    get: This method gets a member's billing info.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)
        current_plan = member.profile.membership_plan

        billing_info = {}

        if current_plan:
            s = None

            # if we have a subscription id, fetch the details
            if member.profile.stripe_subscription_id:
                s = stripe.Subscription.retrieve(
                    member.profile.stripe_subscription_id,
                )

            # if we got subscription details
            if s:
                billing_info["subscription"] = {
                    "status": member.profile.subscription_status,
                    "billingCycleAnchor": s.billing_cycle_anchor,
                    "currentPeriodEnd": s.current_period_end,
                    "cancelAt": s.cancel_at,
                    "cancelAtPeriodEnd": s.cancel_at_period_end,
                    "startDate": s.start_date,
                    "membershipTier": member.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": member.profile.membership_plan.get_object(),
                }
            else:
                billing_info["subscription"] = None

        # get the most recent memberbucks transactions and order them by date
        recent_transactions = MemberBucks.objects.filter(user=member).order_by("date")[
            ::-1
        ][:100]

        def get_transaction(transaction):
            return transaction.get_transaction_display()

        billing_info["memberbucks"] = {
            "balance": member.profile.memberbucks_balance,
            "stripe_card_last_digits": member.profile.stripe_card_last_digits,
            "stripe_card_expiry": member.profile.stripe_card_expiry,
            "transactions": map(get_transaction, recent_transactions),
            "lastPurchase": member.profile.last_memberbucks_purchase,
        }

        return Response(billing_info)


class MemberLogs(APIView):
    """
    get: This method gets a member's logs.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        user = User.objects.get(id=member_id)

        user_event_logs = []
        door_logs = []
        interlock_logs = []

        for user_event_log in UserEventLog.objects.order_by("-date").filter(user=user)[
            :1000
        ]:
            user_event_logs.append(
                {
                    "date": user_event_log.date,
                    "description": user_event_log.description,
                    "logtype": user_event_log.get_logtype_display(),
                }
            )

        for door_log in DoorLog.objects.order_by("-date").filter(user=user)[:500]:
            door_logs.append(
                {
                    "date": door_log.date,
                    "door": door_log.door.name,
                    "success": door_log.success,
                }
            )

        for interlock_log in InterlockLog.objects.filter(user_started=user)[:1000]:
            status = None

            if not interlock_log.success:
                status = -1
            else:
                status = 1 if interlock_log.date_ended else 0

            interlock_logs.append(
                {
                    "interlockName": interlock_log.interlock.name,
                    "dateStarted": interlock_log.date_started,
                    "totalTime": interlock_log.total_time,
                    "totalCost": (interlock_log.total_cost or 0) / 100,
                    "status": status,
                    "userEnded": (
                        interlock_log.user_ended.get_full_name()
                        if interlock_log.user_ended
                        else None
                    ),
                }
            )

        logs = {
            "userEventLogs": user_event_logs,
            "doorLogs": door_logs,
            "interlockLogs": interlock_logs,
        }

        return Response(logs)


class ManageSettings(APIView):
    """
    get: This method gets a constance setting value or values.
    put: This method updates a constance setting value.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_setting(self, setting):
        return {
            "key": setting.key,
            "value": setting.value,
        }

    def get(self, request, setting_key=None):
        if setting_key:
            try:
                setting = ConstanceSetting.objects.get(key=setting_key)
                return Response(self.get_setting(setting))

            except ConstanceSetting.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            settings = []

            for setting in ConstanceSetting.objects.all():
                settings.append(self.get_setting(setting))

            return Response(settings)

    def put(self, request, setting_key=None):
        if not setting_key:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        try:
            setting = ConstanceSetting.objects.get(key=setting_key)
            setting.value = body["value"]
            setting.save()

            return Response(self.get_setting(setting))

        except ConstanceSetting.DoesNotExist as e:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PendingInvoices(StripeAPIView):
    """
    get: Returns a list of members with an outstanding (open) Stripe invoice
    for their subscription. Used by the admin Pending Invoices panel to
    facilitate off-Stripe payment collection (bank transfer, cash, etc.)
    while still using the Stripe subscription mechanism.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        # Intentionally no ENABLE_INVOICE_BILLING gate: existing invoice
        # subscriptions keep billing in Stripe even when new invoice signups
        # are disabled, so admins still need this view to record off-Stripe
        # payments for those members. The frontend shows a config warning.
        pending_members = User.objects.select_related("profile").filter(
            profile__subscription_status="pending"
        )

        results = []
        for member in pending_members:
            profile = member.profile
            if not profile.stripe_subscription_id:
                continue

            try:
                invoices = stripe.Invoice.list(
                    subscription=profile.stripe_subscription_id,
                    status="open",
                    limit=1,
                )
                if not invoices.data:
                    continue
                invoice = invoices.data[0]
            except stripe.error.StripeError as e:
                capture_exception(e)
                continue

            plan = profile.membership_plan
            results.append(
                {
                    "memberId": member.id,
                    "memberName": profile.get_full_name(),
                    "memberEmail": member.email,
                    "planName": plan.name if plan else None,
                    "invoiceId": invoice.id,
                    "invoiceNumber": invoice.number,
                    "amountDue": invoice.amount_due,
                    "currency": invoice.currency,
                    "created": invoice.created,
                    "dueDate": invoice.due_date,
                    "hostedInvoiceUrl": invoice.hosted_invoice_url,
                }
            )

        return Response(results)


class MarkInvoicePaid(StripeAPIView):
    """
    post: Marks a Stripe invoice as paid out-of-band (e.g. bank transfer,
    cash) without charging through Stripe. An optional comment is stored on
    the invoice's metadata for audit trail purposes.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, invoice_id):
        # No ENABLE_INVOICE_BILLING gate — admins must be able to record
        # off-Stripe payments for legacy invoice subscriptions even after
        # new invoice signups are disabled.
        comment = (request.data.get("comment") or "").strip()

        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
        except stripe.error.StripeError as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "message": "Failed to retrieve invoice from Stripe.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Only allow paying invoices that belong to a member whose subscription
        # is currently pending — this prevents marking arbitrary invoices in the
        # Stripe account (memberbucks top-ups, unrelated charges, etc.) as paid.
        member_profile = (
            Profile.objects.filter(
                stripe_subscription_id=invoice.subscription,
                subscription_status="pending",
            ).first()
            if invoice.subscription
            else None
        )
        if member_profile is None:
            return Response(
                {
                    "success": False,
                    "message": "Invoice is not for a pending membership subscription.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stripe.Invoice.pay(invoice_id, paid_out_of_band=True)
        except stripe.error.StripeError as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "message": "Failed to mark invoice as paid in Stripe.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if comment:
            try:
                stripe.Invoice.modify(
                    invoice_id,
                    metadata={
                        # User id (not email) so we don't ship staff PII to
                        # Stripe. Internal lookups can resolve id → user.
                        "marked_paid_by_user_id": str(request.user.id),
                        "marked_paid_comment": comment[:500],
                    },
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
                request.user.log_event(
                    f"Failed to attach audit comment to Stripe invoice "
                    f"{invoice_id} (invoice was still marked paid).",
                    "stripe",
                    data=comment,
                )

        request.user.log_event(
            f"Marked Stripe invoice {invoice_id} as paid out-of-band.",
            "stripe",
            data=comment,
        )
        member_profile.user.log_event(
            f"Admin {request.user.get_full_name()} marked Stripe invoice "
            f"{invoice_id} as paid out-of-band.",
            "stripe",
            data=comment,
        )

        return Response({"success": True})


class SignupPreview(APIView):
    """
    get: Renders the welcome email exactly as members receive it, plus the
    terms & conditions cards, so admins can preview signup content. Quick
    admin tool — no member context, just the configured content.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        # Mirror Profile.email_welcome()'s card source so the preview matches.
        raw_cards = config.WELCOME_EMAIL_CARDS or config.HOME_PAGE_CARDS
        try:
            cards = json.loads(raw_cards)
        except (ValueError, TypeError):
            cards = []

        email_vars = {"title": f"Welcome to {config.SITE_OWNER}", "cards": cards}
        welcome_email_html = render_to_string(
            "email_welcome.html", {"email": email_vars, "config": config}
        )

        try:
            terms_cards = json.loads(config.TERMS_ACCEPTANCE_CARDS)
        except (ValueError, TypeError):
            terms_cards = []

        return Response(
            {
                "welcomeEmailHtml": welcome_email_html,
                "termsAcceptanceCards": terms_cards,
            }
        )
