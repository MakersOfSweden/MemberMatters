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
from django.utils.translation import gettext
import datetime
from profile.models import User, Profile
from api_billing.stripe_customer import update_stripe_customer_on_commit
from profile.profile_changes import (
    MEMBER,
    SIGNUP,
    ProfileConflict,
    ProfileFieldErrors,
    check_profile_changes,
    check_unique,
    columns,
    save_profile_changes,
)
from profile.profile_fields import (
    FIELDS,
    HIDDEN,
    field_mode,
    profile_fields_config,
)

from rest_framework import status, permissions, generics, serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Kiosk, SiteSession, EmailVerificationToken, DashboardCard
from services.discord import post_kiosk_swipe_to_discord
from services.slack import post_kiosk_swipe_to_slack
from services.captcha import verify_captcha, captcha_enabled
from services.email_i18n import member_email_translation
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
                "requirePrivacyConsent": config.SIGNUP_REQUIRE_PRIVACY_CONSENT,
                "privacyPolicyUrl": config.SIGNUP_PRIVACY_POLICY_URL,
                "privacyPolicyText": config.SIGNUP_PRIVACY_POLICY_TEXT,
                "termsAcceptanceCards": _parse_terms_acceptance_cards(),
                "defaultPhoneRegion": config.PROFILE_DEFAULT_PHONE_REGION,
                "enableMembershipApplicationEmail": config.ENABLE_MEMBERSHIP_APPLICATION_USER_EMAIL,
            },
            # Each profile field's PROFILE_FIELD_* value, and the parts of an
            # address. See profile/profile_fields.py.
            **profile_fields_config(),
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
            "dashboardCards": [
                card.get_object() for card in DashboardCard.objects.filter(enabled=True)
            ],
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
                    "username": request.user.profile.get_display_name(),
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

        # Every request that reaches a password check is gated, including the
        # SSO one: an already-authenticated handshake returned above, so what
        # remains is a credential guess. A Discourse-initiated login puts a
        # valid sso/sig pair in the browser URL, and the nonce isn't checked
        # for reuse, so a pair harvested once would otherwise carry unlimited
        # guesses past the CAPTCHA. The web form sends a token on this branch.
        if not verify_captcha(request, action="login"):
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
                        "username": user.profile.get_display_name(),
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
                            user.email_verification(url)
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
            "address": p.address,
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

        # A member only sees the fields that aren't hidden, even where data
        # stored before the field was hidden is kept.
        for field in FIELDS:
            if field_mode(field.key) == HIDDEN:
                response.pop(field.key, None)

        return Response(response)

    def put(self, request):
        # Each field follows its PROFILE_FIELD_* setting: see
        # profile/profile_changes.py for what a member may change.
        try:
            changed = save_profile_changes(request.user.profile, request.data, MEMBER)
        except ProfileFieldErrors as error:
            return Response(error.errors, status=status.HTTP_400_BAD_REQUEST)
        except ProfileConflict as conflict:
            return Response(
                {"message": conflict.message}, status=status.HTTP_409_CONFLICT
            )

        update_stripe_customer_on_commit(request.user.profile, changed)

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
                last_seen=timezone.now(),
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


class RegisterSerializer(serializers.Serializer):
    """The password on a signup. The profile fields are checked by
    check_profile_changes(); the view passes their cleaned values in as
    context["profile"] for the password similarity check."""

    # Every error message is an i18n key resolved by the frontend, not
    # English text. Keep these in sync with the `error` block in
    # src-frontend/src/i18n/*/index.ts.
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

    def validate(self, attrs):
        profile = self.context.get("profile", {})

        # Run Django's AUTH_PASSWORD_VALIDATORS — min-length is already
        # covered by the field's min_length=8, but this also picks up
        # CommonPassword / NumericPassword / PwnedPasswords from
        # settings.py, plus UserAttributeSimilarity against the email
        # and names on this signup. first_name / last_name aren't real
        # User fields (they live on Profile), but the similarity
        # validator just getattrs them, so setting them on an unsaved
        # User instance is enough.
        pseudo_user = User(email=profile.get("email", ""))
        pseudo_user.first_name = profile.get("firstName", "")
        pseudo_user.last_name = profile.get("lastName", "")
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


def _signup_profile_data(data):
    """The submitted profile fields of a signup.

    Signup forms from before the PROFILE_FIELD_* settings post the phone as
    "mobile". It is still accepted, for one release, so a tab left open during
    an upgrade can sign up.
    """
    data = dict(data.items())
    if "phone" not in data and "mobile" in data:
        data["phone"] = data["mobile"]
    return data


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
            new_user.email_verification(verification_url)
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
        with member_email_translation(new_user):
            induction_subject = gettext(
                "Action Required: %(site_owner)s New Member Signup"
            ) % {"site_owner": config.SITE_OWNER}
            induction_title = gettext("Next Step: Register for an Induction")
            induction_message = gettext(
                "Hi %(first_name)s, thanks for signing up! The next step to "
                "becoming a fully fledged member is to book in for an induction. "
                "During this induction we will go over the basic safety and "
                "operational aspects of %(site_owner)s. To book in, click the "
                "link below."
            ) % {"first_name": profile.first_name, "site_owner": config.SITE_OWNER}
            induction_btn = gettext("Register for Induction")
        induction_link = config.POST_INDUCTION_URL

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
    Gated /api/token/obtain/ (the retired phone app's login). Ungated it would
    let an attacker credential-stuff here and bypass the /api/login/ CAPTCHA;
    shares the "login" action since the app used the same login form.
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

        # The profile fields follow their PROFILE_FIELD_* settings; hidden
        # ones are dropped. Both checks run so every error comes back at once.
        errors = {}
        values = {}
        try:
            values = check_profile_changes(
                {}, _signup_profile_data(request.data), SIGNUP
            )
        except ProfileFieldErrors as error:
            errors.update(error.errors)

        serializer = RegisterSerializer(data=request.data, context={"profile": values})
        if not serializer.is_valid():
            errors.update(serializer.errors)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        password = serializer.validated_data["password"]

        # Pre-flight uniqueness checks. The DB constraint (User.email
        # already unique; Profile.screen_name unique after the M32
        # migration) is the authoritative source for races — see the
        # IntegrityError handler below. The 409 on duplicate email is a
        # deliberate UX trade-off (account-existence enumeration); the
        # alternative — silently emailing "you already have an account" —
        # was considered worse for the typical signup mistake.
        try:
            check_unique(values)
        except ProfileConflict as conflict:
            return Response(
                {"message": conflict.message}, status=status.HTTP_409_CONFLICT
            )

        try:
            with transaction.atomic():
                new_user = User.objects.create(
                    email=values["email"],
                    email_verified=False,
                )
                new_user.set_password(password)
                new_user.save(update_fields=["password"])

                profile = Profile.objects.create(
                    user=new_user, **columns(values, "profile")
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
            try:
                check_unique(values)
            except ProfileConflict as conflict:
                return Response(
                    {"message": conflict.message}, status=status.HTTP_409_CONFLICT
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
        is_fresh = (
            timezone.now()
            < verification_token.creation_date + datetime.timedelta(hours=24)
        )

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
