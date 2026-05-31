import nh3
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Mirrors the frontend DOMPurify policy used for the terms-acceptance cards
# (TermsAcceptanceCard.vue): a small set of safe formatting tags plus links
# that may keep their target. Admin-authored card content only, but we
# sanitise server-side so the email render gets the same guarantees the
# in-app cards already have. link_rel below stamps rel on every link, so it
# must not also appear in the allowed attributes.
ALLOWED_TAGS = {"a", "b", "br", "em", "i", "li", "ol", "p", "span", "strong", "ul"}
ALLOWED_ATTRIBUTES = {"a": {"href", "target"}}


@register.filter
def sanitize_html(value):
    if not value:
        return ""
    return mark_safe(
        nh3.clean(
            str(value),
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            link_rel="noopener noreferrer",
        )
    )
