from django.contrib import admin
from .models import *
from import_export.admin import ImportExportModelAdmin
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from django.utils import timezone
from subscriptions import records
from subscriptions.admin import SubscriptionInline


class UserResource(resources.ModelResource):
    first_name = fields.Field(
        column_name="first_name",
        attribute="first_name",
        widget=ForeignKeyWidget(Profile, "first_name"),
    )
    last_name = fields.Field(
        column_name="last_name",
        attribute="last_name",
        widget=ForeignKeyWidget(Profile, "last_name"),
    )
    screen_name = fields.Field(
        column_name="screen_name",
        attribute="screen_name",
        widget=ForeignKeyWidget(Profile, "screen_name"),
    )
    rfid = fields.Field(
        column_name="rfid", attribute="rfid", widget=ForeignKeyWidget(Profile, "rfid")
    )
    state = fields.Field(
        column_name="state",
        attribute="state",
        widget=ForeignKeyWidget(Profile, "state"),
    )

    def dehydrate_first_name(self, user):
        try:
            return user.profile.first_name
        except Exception:
            return ""

    def dehydrate_last_name(self, user):
        try:
            return user.profile.last_name
        except Exception:
            return ""

    def dehydrate_screen_name_name(self, user):
        try:
            return user.profile.screen_name
        except Exception:
            return ""

    def dehydrate_rfid(self, user):
        try:
            return user.profile.rfid
        except Exception:
            return None

    def dehydrate_state(self, user):
        try:
            return user.profile.state
        except Exception:
            return "noob"

    def before_import_row(self, row, **kwargs):
        user, created = User.objects.get_or_create(
            email=row["email"],
            defaults={
                "email": row["email"],
                "email_verified": True,
                "admin": row["admin"],
                "staff": row["staff"],
            },
        )

        # new User needs a Profile
        if created:
            # mandatory fields with profile
            Profile.objects.create(
                user=user,
                first_name=row["first_name"],
                last_name=row["last_name"],
                screen_name=row["screen_name"],
                rfid=row["rfid"] or None,
            )

    def skip_row(self, instance, original, row, import_validation_errors):
        return row["email"] == "default@example.com"

    class Meta:
        model = User
        import_id_fields = ["email"]
        # import-export 4 exports only these, in this order. It's the column
        # order version 3 produced: the declared Profile columns, then User's.
        fields = (
            "first_name",
            "last_name",
            "screen_name",
            "rfid",
            "state",
            "email",
            "staff",
            "admin",
        )


@admin.register(User)
class AdminLogAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [UserResource]
    pass


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    readonly_fields = ("created", "subscription_first_created")
    inlines = [SubscriptionInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # The billing check sends admins here to correct the billing columns.
        # That edit bypasses the subscription writer, so bring the member's
        # subscription rows in line with what was entered.
        if set(form.changed_data) & set(records.MIRRORED_FIELDS):
            locked = Profile.objects.select_for_update().get(pk=obj.pk)
            records.adopt_profile_columns(locked)


@admin.register(UserEventLog)
class UserEventLogAdmin(admin.ModelAdmin):
    readonly_fields = ("date",)


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    readonly_fields = ("date",)
