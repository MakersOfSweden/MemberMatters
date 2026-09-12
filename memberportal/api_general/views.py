import sentry_sdk
from django.contrib.auth import (
    authenticate,
    login,
    logout,
)
import logging
from constance import config
import json
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.utils.timezone import make_aware
import datetime
from pytz import UTC as utc
from profile.models import User, Profile
from profile.phone import to_e164

from rest_framework import status, permissions, generics, serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Kiosk, SiteSession, EmailVerificationToken
from services.discord import post_kiosk_swipe_to_discord
from services.slack import post_kiosk_swipe_to_slack
from services.captcha import verify_captcha, captcha_enabled
import base64
from urllib.parse import parse_qs, urlencode
import hmac
import hashlib

logger = logging.getLogger("general")


def _parse_terms_acceptance_cards():
    try:
        return json.loads(config.TERMS_ACCEPTANCE_CARDS)
    except (ValueError, TypeError):
        return []


class GetConfig(APIView):
    """
    get: This method returns the site config used to customise the front end.
    """

    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        user_is_admin = request.user.is_authenticated and request.user.is_admin
        features = {
            "memberbucks_topup_options": json.loads(
                config.STRIPE_MEMBERBUCKS_TOPUP_OPTIONS
            ),
            "enableProxyVoting": config.ENABLE_PROXY_VOTING,
            "enableStripe": config.ENABLE_STRIPE
            and len(config.STRIPE_PUBLISHABLE_KEY) > 0
            and len(config.STRIPE_SECRET_KEY) > 0,
            "enableCaptcha": captcha_enabled(),
            "enableMembershipPayments": config.ENABLE_STRIPE
            and config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS,
            "enableNewSubscriptions": config.ENABLE_NEW_SUBSCRIPTIONS,
            "forceSignupCompletion": config.FORCE_SIGNUP_COMPLETION,
            "enableMemberBucks": config.ENABLE_MEMBERBUCKS,
            "enableRegistration": config.ENABLE_REGISTRATION,
            "registrationDisabledMessage": config.REGISTRATION_DISABLED_MESSAGE,
            "signup": {
                "inductionLink": config.INDUCTION_ENROL_LINK,
                "enableInduction": config.MOODLE_INDUCTION_ENABLED
                or config.CANVAS_INDUCTION_ENABLED,
                "requireAccessCard": config.REQUIRE_ACCESS_CARD,
                "memberCanEnterAccessCard": config.MEMBER_CAN_ENTER_ACCESS_CARD,
                "postInductionUrl": config.POST_INDUCTION_URL,
                "collectVehicleRegistrationPlate": config.COLLECT_VEHICLE_REGISTRATION_PLATE,
                "requirePrivacyConsent": config.SIGNUP_REQUIRE_PRIVACY_CONSENT,
                "privacyPolicyUrl": config.SIGNUP_PRIVACY_POLICY_URL,
                "privacyPolicyText": config.SIGNUP_PRIVACY_POLICY_TEXT,
                "termsAcceptanceCards": _parse_terms_acceptance_cards(),
                "requireScreenName": config.REQUIRE_SCREEN_NAME,
                "defaultPhoneRegion": config.PROFILE_DEFAULT_PHONE_REGION,
                "enableMembershipApplicationEmail": config.ENABLE_MEMBERSHIP_APPLICATION_USER_EMAIL,
            },
            "profile": {
                "canEditBasicDetails": config.MEMBER_CAN_EDIT_BASIC_DETAILS,
                "canEditEmail": config.MEMBER_CAN_EDIT_EMAIL,
            },
            "enableWebcams": config.ENABLE_WEBCAMS,
            "siteBanner": config.SITE_BANNER,
            "enableSiteSignIn": config.ENABLE_PORTAL_SITE_SIGN_IN,
            "enableMembersOnSite": config.ENABLE_PORTAL_MEMBERS_ON_SITE,
            "sms": {
                "enable": config.SMS_ENABLE,
                "senderId": config.SMS_SENDER_ID,
                "footer": config.SMS_FOOTER,
            },
            "enableStatsPage": config.ENABLE_STATS_PAGE,
            "enableLastSeenPage": config.ENABLE_LAST_SEEN_PAGE or user_is_admin,
            "enableRecentSwipesPage": config.ENABLE_RECENT_SWIPES_PAGE or user_is_admin,
            "enableReportIssue": config.ENABLE_REPORT_ISSUE,
            "enableMembershipStatusCard": config.ENABLE_MEMBERSHIP_STATUS_CARD,
            "enableInvoiceBilling": config.ENABLE_INVOICE_BILLING,
            "invoiceBillingNote": (
                config.INVOICE_BILLING_NOTE if config.ENABLE_INVOICE_BILLING else ""
            ),
        }

        keys = {
            "stripePublishableKey": config.STRIPE_PUBLISHABLE_KEY,
            "captchaSiteKey": config.CAPTCHA_SITE_KEY,
        }

        with open("../package.json") as f:
            package = json.load(f)
            version = package.get("version")

        try:
            homepage_cards = json.loads(config.HOME_PAGE_CARDS)
        except:
            homepage_cards = [
                {
                    "title": "Error loading configuration",
                    "description": "There was an error loading the home page cards configuration. Please try re-saving the configuration in the admin panel.",
                    "icon": "mdi-alert",
                    "url": "#",
                    "btn_text": "",
                },
            ]

        try:
            webcam_links = json.loads(config.WEBCAM_PAGE_URLS)
        except:
            webcam_links = [
                ["Error Loading Webcam Configuration", ""],
            ]

        response = {
            "version": version,
            "loggedIn": request.user.is_authenticated,
            "general": {
                "siteName": config.SITE_NAME,
                "siteOwner": config.SITE_OWNER,
                "siteLocaleCurrency": config.SITE_LOCALE_CURRENCY,
            },
            "contact": {
                "admin": config.EMAIL_ADMIN,
                "sysadmin": config.EMAIL_SYSADMIN,
                "address": config.SITE_MAIL_ADDRESS,
            },
            "images": {
                "siteLogo": config.SITE_LOGO,
                "statsCard": config.STATS_CARD_IMAGE,
                "siteFavicon": config.SITE_FAVICON,
                "menuBackground": config.MENU_BACKGROUND,
            },
            "theme": {
                "themePrimary": config.THEME_PRIMARY,
                "themeToolbar": config.THEME_TOOLBAR,
                "themeAccent": config.THEME_ACCENT,
            },
            "homepageCards": homepage_cards,
            "webcamLinks": webcam_links,
            "keys": keys,
            "features": features,
            "analyticsId": config.GOOGLE_ANALYTICS_MEASUREMENT_ID,
            "sentryDSN": config.SENTRY_DSN_FRONTEND,
        }

        return Response(response)


class Login(APIView):
    """
    WEB_ONLY

    post: Attempts to authenticate a user then logs them in if successful.
    """

    permission_classes = (permissions.AllowAny,)
    # Previously unthrottled; the scope bounds the new synchronous CAPTCHA
    # verify below so it can't be used for outbound amplification.
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"

    def post(self, request):
        body = request.data
        discourse_nonce = None
        discourse_redirect = None
        discourse_login = False
        secret = config.DISCOURSE_SSO_PROTOCOL_SECRET_KEY.encode("utf-8")

        if body.get("sso") is not None:
            if config.ENABLE_DISCOURSE_SSO_PROTOCOL:
                sso_data = body.get("sso")
                computed_signature = hmac.new(
                    secret, sso_data["sso"].encode("utf-8"), digestmod=hashlib.sha256
                ).hexdigest()

                sso_payload = parse_qs(base64.b64decode(sso_data["sso"]))
                sig = sso_data["sig"]

                if computed_signature == sig:
                    discourse_nonce = sso_payload[b"nonce"][0].decode("utf-8")
                    discourse_redirect = sso_payload[b"return_sso_url"][0].decode(
                        "utf-8"
                    )
                    discourse_login = True

                else:
                    # if the sig doesn't match then exit
                    return Response(status=status.HTTP_400_BAD_REQUEST)

            else:
                # if sso is disabled then exit
                return Response(status=status.HTTP_400_BAD_REQUEST)

        if request.user.is_authenticated:
            if discourse_login:
                payload = {
                    "nonce": discourse_nonce,
                    "email": request.user.email,
                    "external_id": request.user.id,
                    "username": request.user.profile.screen_name,
                    "name": request.user.profile.get_full_name(),
                }
                payload = base64.b64encode(urlencode(payload).encode("utf-8"))
                computed_signature = hmac.new(
                    secret, payload, digestmod=hashlib.sha256
                ).hexdigest()

                return Response(
                    {
                        "redirect": f"{discourse_redirect}?sso={payload.decode('utf-8')}&sig={computed_signature}"
                    },
                    status=status.HTTP_200_OK,
                )

            else:
                return Response(status=status.HTTP_200_OK)

        if body.get("email") is None or body.get("password") is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Gate the email/password branch only, not the SSO handshake.
        if body.get("sso") is None and not verify_captcha(request, action="login"):
            return Response(
                {"message": "error.captchaFailed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(username=body.get("email"), password=body.get("password"))

        # correct login details
        if user is not None:
            # if their email is verified
            if user.email_verified:
                login(request, user)

                if discourse_login:
                    payload = {
                        "nonce": discourse_nonce,
                        "email": user.email,
                        "external_id": user.id,
                        "username": user.profile.screen_name,
                        "name": user.profile.get_full_name(),
                    }
                    payload = base64.b64encode(urlencode(payload).encode("utf-8"))
                    computed_signature = hmac.new(
                        secret, payload, digestmod=hashlib.sha256
                    ).hexdigest()

                    return Response(
                        {
                            "redirect": f"{discourse_redirect}?sso={payload.decode('utf-8')}&sig={computed_signature}"
                        },
                        status=status.HTTP_200_OK,
                    )

                else:
                    return Response(status=status.HTTP_200_OK)

            else:
                with transaction.atomic():
                    new_token = EmailVerificationToken.objects.create(user=user)
                    verify_url = (
                        f"{config.SITE_URL}/profile/email/"
                        f"{new_token.verification_token}/verify/"
                    )

                    def _send_verification_email(user=user, url=verify_url):
                        try:
                            user.email_link(
                                "Action Required: Verify Email",
                                "Verify Email",
                                "Please verify your email address to activate your account.",
                                url,
                                "Verify Now",
                            )
                        except Exception as e:
                            sentry_sdk.capture_exception(e)

                    transaction.on_commit(_send_verification_email)

                return Response(
                    {"message": "loginCard.emailNotVerified"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        logger.info("user was None")
        return Response(status=status.HTTP_401_UNAUTHORIZED, data={})


class LoginKiosk(APIView):
    """
    KIOSK_ONLY

    post: Attempts to authenticate a user then logs them in if successful.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        if request.user.is_authenticated:
            return Response(status=status.HTTP_200_OK)

        body = json.loads(request.body.decode("utf-8"))

        if body.get("cardId") is None or body.get("kioskId") is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            kiosk = Kiosk.objects.get(kiosk_id=body.get("kioskId"))

        except Kiosk.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        if not kiosk.authorised:
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            user = Profile.objects.get(rfid=body.get("cardId")).user

        except Profile.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        if not user.email_verified:
            return Response(
                {"message": "error.emailNotVerified"}, status=status.HTTP_403_FORBIDDEN
            )

        # rfid matches a user so log them in
        if user is not None:
            login(request, user)
            return Response(status=status.HTTP_200_OK)

        else:
            return Response(status=status.HTTP_401_UNAUTHORIZED)


class Logout(APIView):
    """
    WEB_ONLY, KIOSK_ONLY

    post: Ends the user's session and logs them out.
    """

    def post(self, request):
        logout(request)

        return Response({"success": True})


class ResetPassword(APIView):
    """
    post: Handles the various stages of the password reset flow.
    """

    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)

    def get_throttles(self):
        if self.request.data.get("token"):
            self.throttle_scope = "password_reset_use"
        else:
            self.throttle_scope = "password_reset_request"
        return super().get_throttles()

    def post(self, request):
        body = request.data
        token = body.get("token")
        password = body.get("password")

        # If we get a reset token and no password, the token is being validated
        if token and not password:
            try:
                user = User.objects.get(password_reset_key=token)
            except (User.DoesNotExist, DjangoValidationError, ValueError, TypeError):
                # DoesNotExist: no such token. (Django)ValidationError /
                # ValueError / TypeError: `token` isn't a parseable UUID
                # (UUIDField re-raises bad input as ValidationError) — a
                # garbage token is just an invalid one, not a 500.
                return Response({"success": False})

            now = timezone.now()
            if (
                user.password_reset_expire is not None
                and now < user.password_reset_expire
            ):
                return Response({"success": True})

            # Token expired — clear it. Conditional UPDATE keyed on the
            # original token so a concurrent reset_password() that
            # rotated the key between our get() and now isn't clobbered:
            # the filter no longer matches the new key, so zero rows
            # update and the fresh reset stays intact.
            User.objects.filter(pk=user.pk, password_reset_key=token).update(
                password_reset_key=None,
                password_reset_expire=None,
            )
            return Response({"success": False})

        # If we get a reset token and password, the password should be reset
        if token and password:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(
                        password_reset_key=token
                    )
                    now = timezone.now()
                    if (
                        user.password_reset_expire is not None
                        and now < user.password_reset_expire
                    ):
                        try:
                            validate_password(password, user=user)
                        except DjangoValidationError as e:
                            return Response(
                                {"success": False, "errors": list(e.messages)},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        user.set_password(password)
                        user.password_reset_key = None
                        user.password_reset_expire = None
                        user.save(
                            update_fields=[
                                "password",
                                "password_reset_key",
                                "password_reset_expire",
                            ]
                        )
                        return Response({"success": True})

                    # Expired — clear so the row stops matching the stale
                    # token. Mirrors the validate-only branch above.
                    user.password_reset_key = None
                    user.password_reset_expire = None
                    user.save(
                        update_fields=["password_reset_key", "password_reset_expire"]
                    )
            except (User.DoesNotExist, DjangoValidationError, ValueError, TypeError):
                # See the validate-only branch above: an unparseable token
                # is an invalid token, not an internal error.
                pass
            return Response({"success": False})

        # No token: the "request a reset" path. Gate with CAPTCHA before the
        # email lookup so a failed check can't be used to enumerate addresses.
        if not verify_captcha(request, action="password_reset"):
            return Response(
                {"message": "error.captchaFailed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Always return success so the response cannot enumerate registered
        # email addresses (M13).
        email = (body.get("email") or "").lower()
        if email:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                user = None
            if user is not None:
                user.reset_password()
        return Response({"success": True})


class ProfileDetail(generics.GenericAPIView):
    """
    get: Gets the user profile object.
    put: Updates the user profile object.
    """

    def get(self, request):
        p = request.user.profile
        user = request.user

        response = {
            "id": user.id,
            "email": user.email,
            "fullName": p.get_full_name(),
            "firstName": p.first_name,
            "lastName": p.last_name,
            "screenName": p.screen_name,
            "phone": p.phone,
            "memberStatus": p.state,
            "signupStage": p.signup_stage,
            "adminDisabledAccess": p.admin_disabled_access,
            "vehicleRegistrationPlate": p.vehicle_registration_plate,
            "lastInduction": p.last_induction,
            "lastSeen": p.last_seen,
            "firstJoined": p.created,
            "profileUpdateRequired": p.must_update_profile,
            "financial": {
                "memberBucks": {
                    "lastPurchase": p.last_memberbucks_purchase,
                    "balance": p.memberbucks_balance,
                    "savedCard": {
                        "last4": p.stripe_card_last_digits,
                        "expiry": p.stripe_card_expiry,
                    },
                },
                "membershipPlan": (
                    p.membership_plan.get_object() if p.membership_plan else None
                ),
                "membershipTier": (
                    p.membership_plan.member_tier.get_object()
                    if p.membership_plan
                    else None if p.membership_plan else None
                ),
                "subscriptionState": p.subscription_status,
                "billingMethod": p.billing_method,
            },
            "permissions": {"staff": user.is_staff},
        }

        return Response(response)

    def put(self, request):
        p = request.user.profile
        body = json.loads(request.body)
        can_edit_basic = config.MEMBER_CAN_EDIT_BASIC_DETAILS
        can_edit_email = can_edit_basic and config.MEMBER_CAN_EDIT_EMAIL
        # Empty string maps to NULL so unset handles don't collide on the
        # case-insensitive unique constraint.
        screen_name = (body.get("screenName") or "").strip() or None
        email = None

        if can_edit_email:
            email = (body.get("email") or "").lower()

            # check if email is specified
            if not email:
                return Response(status=status.HTTP_400_BAD_REQUEST)

            # check if email is already in use (case-insensitive, excluding self)
            if (
                User.objects.filter(email__iexact=email)
                .exclude(pk=request.user.pk)
                .exists()
            ):
                return Response(
                    {"message": "error.accountAlreadyExists"},
                    status=status.HTTP_409_CONFLICT,
                )

        # check if screen name is already in use (case-insensitive, excluding self)
        if (
            screen_name
            and Profile.objects.filter(screen_name__iexact=screen_name)
            .exclude(pk=p.pk)
            .exists()
        ):
            return Response(
                {"message": "error.screenNameAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        # Normalise the phone number to E.164 (only editable when
        # can_edit_basic, so only validated then).
        phone = ""
        if can_edit_basic:
            phone = (body.get("phone") or "").strip()
            if phone:
                try:
                    phone = to_e164(phone, config.PROFILE_DEFAULT_PHONE_REGION)
                except ValueError:
                    return Response(
                        {"message": "validation.invalidPhone"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        try:
            with transaction.atomic():
                p.screen_name = screen_name
                p.vehicle_registration_plate = body.get("vehicleRegistrationPlate")
                profile_fields = ["screen_name", "vehicle_registration_plate"]

                if can_edit_basic:
                    p.first_name = body.get("firstName")
                    p.last_name = body.get("lastName")
                    p.phone = phone
                    profile_fields += ["first_name", "last_name", "phone"]
                    if can_edit_email:
                        request.user.email = email
                        request.user.save(update_fields=["email"])

                # update_fields restricts UPDATE to columns this view
                # owns — concurrent writes elsewhere on the row (Stripe
                # webhook, admin, access events) aren't reverted by a
                # stale full-row save. Profile.save() rides `modified`
                # along automatically.
                p.save(update_fields=profile_fields)
        except IntegrityError:
            # Race with a concurrent register/update: pre-checks passed
            # but a unique constraint tripped on insert. Re-check to
            # identify which collision occurred.
            if can_edit_email and (
                User.objects.filter(email__iexact=email)
                .exclude(pk=request.user.pk)
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

        return Response({"success": True})


class ApiPassword(APIView):
    """
    put: Change the user's password.
    """

    def put(self, request):
        user = request.user
        body = json.loads(request.body)
        current = body.get("current")
        new = body.get("new")

        if user.check_password(current):
            user.set_password(new)
            user.save()

            return Response({"success": True})

        return Response(status=status.HTTP_403_FORBIDDEN)


class DigitalId(APIView):
    """
    get: retrieves the user's digital id token.
    """

    def get(self, request):
        return Response(
            {"success": True, "token": request.user.profile.generate_digital_id_token()}
        )


class Kiosks(APIView):
    """
    get: retrieves a list of all kiosks.
    post: creates a new kiosk.
    put: update an existing kiosk.
    delete: delete an existing kiosk.
    """

    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        if not request.user.is_authenticated and not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)

        kiosks = Kiosk.objects.all()

        def get_kiosk(kiosk):
            return {
                "id": kiosk.id,
                "name": kiosk.name,
                "kioskId": kiosk.kiosk_id,
                "kioskIp": kiosk.ip_address,
                "lastSeen": kiosk.last_seen,
                "playTheme": kiosk.play_theme,
                "authorised": kiosk.authorised,
            }

        return Response(list(map(get_kiosk, kiosks)))

    def put(self, request, id=None):
        body = request.data

        try:
            if id:
                kiosk = Kiosk.objects.get(id=id)

                kiosk.ip_address = request.META.get(
                    "HTTP_X_REAL_IP", request.META.get("REMOTE_ADDR")
                )
                kiosk.checkin()
                if not request.user.is_authenticated and not request.user.is_staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                kiosk = Kiosk.objects.get(kiosk_id=body.get("kioskId"))

        except Kiosk.DoesNotExist:
            kiosk = Kiosk.objects.create(
                last_seen=make_aware(datetime.datetime.now()),
                kiosk_id=body.get("kioskId"),
                name=body.get("kioskId"),
                play_theme=False,
            )

        if request.user.is_authenticated and request.user.is_staff:
            if body.get("playTheme"):
                kiosk.play_theme = body.get("playTheme")

            if body.get("name"):
                kiosk.name = body.get("name")

            if body.get("authorised") is not None:
                kiosk.authorised = body.get("authorised")

        kiosk.save()

        return Response()

    def delete(self, request, id):
        if not request.user.is_authenticated and not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)

        kiosk = Kiosk.objects.get(id=id)
        kiosk.delete()

        return Response()


class SiteSignIn(APIView):
    """
    post: sign a member in.
    """

    def post(self, request):
        body = request.data
        guests = body.get("guests")

        SiteSession.objects.create(user=request.user, guests=guests)
        post_kiosk_swipe_to_discord(request.user.profile.get_full_name(), True)

        for door in request.user.profile.doors.all():
            door.sync()

        for interlock in request.user.profile.interlocks.all():
            interlock.sync()

        return Response()


class SiteSignOut(APIView):
    """
    put: sign a member out.
    """

    def put(self, request):
        sessions = (
            SiteSession.objects.filter(user=request.user)
            .filter(signout_date__isnull=True)
            .all()
        )
        for session in sessions:
            session.signout()
        if config.ENABLE_DISCORD_INTEGRATION and config.SLACK_DOOR_WEBHOOK:
            post_kiosk_swipe_to_discord(request.user.profile.get_full_name(), False)

        for door in request.user.profile.doors.all():
            door.sync()

        for interlock in request.user.profile.interlocks.all():
            interlock.sync()

        return Response()


class UserSiteSession(APIView):
    """
    get: checks if the member is signed into the site.
    """

    def get(self, request):
        sessions = SiteSession.objects.filter(
            user=request.user, signout_date=None
        ).order_by("-signin_date")

        return Response(sessions.values()[0] if len(sessions) else False)


class LoggedIn(APIView):
    """
    get: checks if the member is logged into the portal.
    """

    def get(self, request):
        if request.user.is_authenticated:
            return Response(status=status.HTTP_200_OK)

        return Response(status=status.HTTP_401_UNAUTHORIZED)


# Maps Django password-validator error codes (AUTH_PASSWORD_VALIDATORS)
# to frontend i18n keys; unknown codes fall back to error.passwordInvalid.
PASSWORD_VALIDATION_ERROR_KEYS = {
    "password_too_short": "error.passwordTooShort",
    "password_too_common": "error.passwordTooCommon",
    "password_entirely_numeric": "error.passwordEntirelyNumeric",
    "password_too_similar": "error.passwordTooSimilar",
    "password_compromised": "error.passwordCompromised",
}

REQUIRE_MOBILE = True  # TODO: migrate to a constance flag


class RegisterSerializer(serializers.Serializer):
    # Every error message is an i18n key resolved by the frontend, not
    # English text. Keep these in sync with the `error` block in
    # src-frontend/src/i18n/*/index.ts.
    email = serializers.EmailField(
        required=True,
        max_length=255,
        error_messages={
            "required": "error.fieldRequired",
            "null": "error.fieldRequired",
            "blank": "error.fieldRequired",
            "invalid": "validation.invalidEmail",
            "max_length": "error.emailTooLong",
        },
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        min_length=8,
        max_length=128,
        error_messages={
            "required": "error.fieldRequired",
            "null": "error.fieldRequired",
            "blank": "error.fieldRequired",
            "min_length": "error.passwordTooShort",
            "max_length": "error.passwordTooLong",
        },
    )
    firstName = serializers.CharField(
        required=True,
        max_length=30,
        allow_blank=False,
        error_messages={
            "required": "error.fieldRequired",
            "null": "error.fieldRequired",
            "blank": "error.fieldRequired",
            "max_length": "error.firstNameTooLong",
        },
    )
    lastName = serializers.CharField(
        required=True,
        max_length=30,
        allow_blank=False,
        error_messages={
            "required": "error.fieldRequired",
            "null": "error.fieldRequired",
            "blank": "error.fieldRequired",
            "max_length": "error.lastNameTooLong",
        },
    )
    screenName = serializers.CharField(
        required=False,
        max_length=30,
        allow_blank=True,
        allow_null=True,
        default=None,
        error_messages={"max_length": "error.screenNameTooLong"},
    )
    # allow_null: the form posts null for fields it isn't collecting;
    # validate() normalises that to "".
    mobile = serializers.CharField(
        required=False,
        max_length=16,
        allow_blank=True,
        allow_null=True,
        default="",
        error_messages={"max_length": "error.mobileTooLong"},
    )
    vehicleRegistrationPlate = serializers.CharField(
        required=False,
        max_length=30,
        allow_blank=True,
        allow_null=True,
        default="",
        error_messages={"max_length": "error.vehiclePlateTooLong"},
    )

    def validate_email(self, value):
        return value.lower()

    def validate_screenName(self, value):
        return (value or "").strip() or None

    def validate(self, attrs):
        # A null mobile / vehicle plate (see allow_null above) becomes ""
        # so the Profile row always gets a string, not None. The plate is
        # also dropped entirely unless the site collects it.
        attrs["mobile"] = (attrs.get("mobile") or "").strip()
        attrs["vehicleRegistrationPlate"] = (
            (attrs.get("vehicleRegistrationPlate") or "").strip()
            if config.COLLECT_VEHICLE_REGISTRATION_PLATE
            else ""
        )

        if REQUIRE_MOBILE and not attrs["mobile"]:
            raise serializers.ValidationError({"mobile": "error.fieldRequired"})

        # Store the phone number in E.164 format.
        if attrs["mobile"]:
            try:
                attrs["mobile"] = to_e164(
                    attrs["mobile"], config.PROFILE_DEFAULT_PHONE_REGION
                )
            except ValueError:
                raise serializers.ValidationError({"mobile": "validation.invalidPhone"})

        if not attrs.get("screenName") and config.REQUIRE_SCREEN_NAME:
            raise serializers.ValidationError(
                {"screenName": "error.screenNameRequired"}
            )

        # Run Django's AUTH_PASSWORD_VALIDATORS — min-length is already
        # covered by the field's min_length=8, but this also picks up
        # CommonPassword / NumericPassword / PwnedPasswords from
        # settings.py, plus UserAttributeSimilarity against the email
        # and names on this signup. first_name / last_name aren't real
        # User fields (they live on Profile), but the similarity
        # validator just getattrs them, so setting them on an unsaved
        # User instance is enough.
        pseudo_user = User(email=attrs["email"])
        pseudo_user.first_name = attrs["firstName"]
        pseudo_user.last_name = attrs["lastName"]
        try:
            validate_password(attrs["password"], user=pseudo_user)
        except DjangoValidationError as e:
            # Map each validator's error code to an i18n key, de-duped
            # (a pwned + common password trips two validators).
            keys = list(
                dict.fromkeys(
                    PASSWORD_VALIDATION_ERROR_KEYS.get(
                        err.code, "error.passwordInvalid"
                    )
                    for err in e.error_list
                )
            )
            raise serializers.ValidationError({"password": keys})

        return attrs


def _send_register_emails(new_user, profile, verification_token):
    """Postmark sends queued via transaction.on_commit so a Postmark
    outage cannot 500 the request after the user/profile rows commit.
    Each send is independently captured — one failure does not abort
    the others."""

    verification_url = (
        f"{config.SITE_URL}/profile/email/"
        f"{verification_token.verification_token}/verify/"
    )

    def _send_verification_email():
        try:
            new_user.email_link(
                "Action Required: Verify Email",
                "Verify Email",
                "Please verify your email address to activate your account.",
                verification_url,
                "Verify Now",
            )
        except Exception as e:
            sentry_sdk.capture_exception(e)

    def _send_admin_notification():
        try:
            profile.email_profile_to(config.EMAIL_ADMIN)
        except Exception as e:
            sentry_sdk.capture_exception(e)

    transaction.on_commit(_send_verification_email)
    transaction.on_commit(_send_admin_notification)

    if not config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS:
        induction_subject = f"Action Required: {config.SITE_OWNER} New Member Signup"
        induction_title = "Next Step: Register for an Induction"
        induction_message = (
            f"Hi {profile.first_name}, thanks for signing up! The next step "
            "to becoming a fully fledged member is to book in for an "
            "induction. During this induction we will go over the basic "
            f"safety and operational aspects of {config.SITE_OWNER}. To book "
            "in, click the link below."
        )
        induction_link = config.POST_INDUCTION_URL
        induction_btn = "Register for Induction"

        def _send_induction_email():
            try:
                new_user.email_link(
                    induction_subject,
                    induction_title,
                    induction_message,
                    induction_link,
                    induction_btn,
                )
            except Exception as e:
                sentry_sdk.capture_exception(e)

        transaction.on_commit(_send_induction_email)


def _subscribe_to_mailchimp(new_user, profile):
    if not config.MAILCHIMP_API_KEY:
        return

    def _subscribe():
        try:
            import mailchimp_marketing

            client = mailchimp_marketing.Client()
            client.set_config(
                {
                    "api_key": config.MAILCHIMP_API_KEY,
                    "server": config.MAILCHIMP_SERVER,
                }
            )
            client.lists.add_list_member(
                config.MAILCHIMP_LIST_ID,
                {
                    "email_address": new_user.email,
                    "email_type": "html",
                    "status": "subscribed",
                    "merge_fields": {
                        "FNAME": profile.first_name,
                        "LNAME": profile.last_name,
                        "PHONE": profile.phone,
                    },
                    "vip": False,
                    "tags": [config.MAILCHIMP_TAG],
                },
            )
        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.error(e)

    transaction.on_commit(_subscribe)


class CaptchaTokenObtainPairView(TokenObtainPairView):
    """
    Gated /api/token/obtain/ (mobile login). Ungated it would let an attacker
    credential-stuff here and bypass the /api/login/ CAPTCHA; shares the "login"
    action since it's the same form on mobile.
    """

    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "token_obtain"

    def post(self, request, *args, **kwargs):
        if not verify_captcha(request, action="login"):
            return Response(
                {"message": "error.captchaFailed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().post(request, *args, **kwargs)


class Register(APIView):
    """
    post: registers a new member.
    """

    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "register"

    def post(self, request):
        if not config.ENABLE_REGISTRATION:
            return Response(
                {
                    "message": "error.registrationClosed",
                    "detail": config.REGISTRATION_DISABLED_MESSAGE,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not verify_captcha(request, action="register"):
            return Response(
                {"message": "error.captchaFailed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        # Pre-flight uniqueness checks. The DB constraint (User.email
        # already unique; Profile.screen_name unique after the M32
        # migration) is the authoritative source for races — see the
        # IntegrityError handler below. The 409 on duplicate email is a
        # deliberate UX trade-off (account-existence enumeration); the
        # alternative — silently emailing "you already have an account" —
        # was considered worse for the typical signup mistake.
        # __iexact rather than = catches any mixed-case rows already in
        # the DB (Postgres email column is case-sensitive by default).
        if User.objects.filter(email__iexact=data["email"]).exists():
            return Response(
                {"message": "error.accountAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )
        if (
            data["screenName"]
            and Profile.objects.filter(screen_name__iexact=data["screenName"]).exists()
        ):
            return Response(
                {"message": "error.screenNameAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                new_user = User.objects.create(
                    email=data["email"],
                    email_verified=False,
                )
                new_user.set_password(data["password"])
                new_user.save(update_fields=["password"])

                profile = Profile.objects.create(
                    user=new_user,
                    first_name=data["firstName"],
                    last_name=data["lastName"],
                    screen_name=data["screenName"],
                    phone=data["mobile"],
                    vehicle_registration_plate=data["vehicleRegistrationPlate"],
                )

                verification_token = EmailVerificationToken.objects.create(
                    user=new_user
                )

                _send_register_emails(new_user, profile, verification_token)
                _subscribe_to_mailchimp(new_user, profile)
        except IntegrityError:
            # Race with another concurrent register: pre-checks passed but
            # a unique constraint tripped on insert. Re-check to identify
            # which collision occurred.
            if User.objects.filter(email__iexact=data["email"]).exists():
                return Response(
                    {"message": "error.accountAlreadyExists"},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"message": "error.screenNameAlreadyExists"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(status=status.HTTP_201_CREATED)


class VerifyEmail(APIView):
    """
    post: registers a new member.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request, verify_token):
        try:
            verification_token = EmailVerificationToken.objects.get(
                verification_token=verify_token
            )
        except (EmailVerificationToken.DoesNotExist, ValueError):
            return Response(
                {"message": "error.emailVerificationFailed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = verification_token.user
        is_fresh = utc.localize(
            datetime.datetime.now()
        ) < verification_token.creation_date + datetime.timedelta(hours=24)

        with transaction.atomic():
            # Compare-and-delete: only one concurrent request can claim
            # the token. The loser gets affected_rows=0 and a clean 401.
            deleted_count, _ = EmailVerificationToken.objects.filter(
                pk=verification_token.pk
            ).delete()
            if deleted_count == 0:
                return Response(
                    {"message": "error.emailVerificationFailed"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            if is_fresh:
                user.email_verified = True
                user.save(update_fields=["email_verified"])

        if is_fresh:
            # Session login runs after the DB commit so a session-store
            # write cannot extend the transaction's row-lock window.
            login(request, user)
            return Response()

        # Expired tokens do not auto-resend. Logging in with valid
        # credentials + an unverified email already triggers a fresh
        # verification email (see Login.post), so the explicit resend
        # path exists without an unauthenticated amplifier here.
        return Response(
            {"message": "error.emailVerificationExpired"},
            status=status.HTTP_403_FORBIDDEN,
        )
