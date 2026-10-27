from django.urls import path

from . import views

urlpatterns = [
    path(
        "api/admin/billing/integrity/",
        views.IntegrityStatus.as_view(),
        name="IntegrityStatus",
    ),
    path(
        "api/admin/billing/integrity/issues/",
        views.IntegrityIssues.as_view(),
        name="IntegrityIssues",
    ),
    path(
        "api/admin/billing/integrity/issues/<int:issue_id>/acknowledge/",
        views.IntegrityIssueAcknowledge.as_view(),
        name="IntegrityIssueAcknowledge",
    ),
    path(
        "api/admin/billing/integrity/run/",
        views.IntegrityRunNow.as_view(),
        name="IntegrityRunNow",
    ),
    path(
        "api/admin/members/<int:member_id>/billing-integrity/",
        views.MemberIntegrityIssues.as_view(),
        name="MemberIntegrityIssues",
    ),
]
