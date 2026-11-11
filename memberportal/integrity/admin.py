from django.contrib import admin

from .models import IntegrityIssue, IntegrityRun


@admin.register(IntegrityIssue)
class IntegrityIssueAdmin(admin.ModelAdmin):
    list_display = (
        "message",
        "severity",
        "check_name",
        "source",
        "profile",
        "last_seen",
        "occurrences",
        "resolved_at",
    )
    list_filter = ("severity", "check_name", "source")
    search_fields = ("key", "message", "stripe_ref")
    raw_id_fields = ("profile",)


@admin.register(IntegrityRun)
class IntegrityRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "trigger",
        "status",
        "stripe_requests",
        "members_checked",
        "new_issues",
        "resolved_issues",
        "open_issues",
    )
    list_filter = ("status", "trigger")
    raw_id_fields = ("profile",)
