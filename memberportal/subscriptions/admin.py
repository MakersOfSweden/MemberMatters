from django.contrib import admin

from .models import Subscription

FIELDS = (
    "state",
    "legacy_status",
    "plan",
    "billing_method",
    "external_ref",
    "started_at",
    "cancel_at",
    "cancelled_at",
    "version",
)


class ReadOnly:
    """Subscriptions change through subscriptions/records.py only."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ("id", "payer", *FIELDS[:5], "started_at", "cancelled_at")
    list_filter = ("state", "legacy_status", "provider", "billing_method")
    list_select_related = ("payer__user", "plan")
    search_fields = (
        "external_ref",
        "payer__first_name",
        "payer__last_name",
        "payer__user__email",
    )


class SubscriptionInline(ReadOnly, admin.TabularInline):
    """A member's subscriptions, newest first, on their Profile page."""

    model = Subscription
    fk_name = "payer"
    fields = FIELDS
    readonly_fields = FIELDS
    extra = 0
    show_change_link = True
