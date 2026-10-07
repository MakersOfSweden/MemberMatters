import json
import pickle
import re
from base64 import b64decode

from django.db import migrations

from services.sanitize import clean_html

# Only Material Design Icons are loaded, so any other name showed no icon.
ICON_NAME = re.compile(r"mdi-[a-z0-9-]+")
DEFAULT_ICON = "mdi-link-variant"


def legacy_links(card):
    """Converts a HOME_PAGE_CARDS card's link to DashboardCard.links.

    The precedence mirrors the old DashboardCard.vue: routerLink, then url, then
    the links list. Links with no target are dropped, and a missing button text
    falls back to the card's title, so every imported card can be saved again.
    """
    title = card.get("title") or ""

    router_link = card.get("routerLink")
    if isinstance(router_link, dict) and router_link.get("name"):
        return [{"label": card.get("btn_text") or title, "route": router_link["name"]}]

    if card.get("url"):
        return [{"label": card.get("btn_text") or title, "url": card["url"]}]

    return [
        {"label": link.get("btn_text") or title, "url": link["url"]}
        for link in card.get("links") or []
        if isinstance(link, dict) and link.get("url")
    ]


def import_home_page_cards(apps, schema_editor):
    try:
        Constance = apps.get_model("constance", "Constance")
    except LookupError:
        # constance's own migrations have not run yet, so HOME_PAGE_CARDS cannot
        # be read from this state. A new install has nothing to import, and an
        # upgrade still has the setting to recreate the cards from.
        return

    DashboardCard = apps.get_model("api_general", "DashboardCard")

    home_page_cards = Constance.objects.filter(key="HOME_PAGE_CARDS").first()
    if home_page_cards is None:
        # Never customised, so the dashboard showed constance's placeholder cards.
        return

    try:
        # Still pickled, as constance kept every setting until its 0003
        # migration, and since constance 4 its model doesn't unpickle them.
        # 0008 runs before 0003 to keep it that way.
        cards = json.loads(pickle.loads(b64decode(home_page_cards.value)))
    except (TypeError, ValueError):
        cards = None

    if not isinstance(cards, list):
        print(
            "\n  HOME_PAGE_CARDS is not a valid JSON array, so no dashboard cards "
            "were imported. Recreate them in Admin Tools -> Dashboard Cards."
        )
        return

    DashboardCard.objects.bulk_create(
        DashboardCard(
            position=position,
            title=(card.get("title") or "")[:255],
            icon=(
                card["icon"]
                if ICON_NAME.fullmatch(str(card.get("icon") or ""))
                else DEFAULT_ICON
            )[:100],
            description=clean_html(card.get("description")),
            links=legacy_links(card),
        )
        for position, card in enumerate(c for c in cards if isinstance(c, dict))
    )


def delete_dashboard_cards(apps, schema_editor):
    apps.get_model("api_general", "DashboardCard").objects.all().delete()


class Migration(migrations.Migration):
    # No dependency on constance: this migration is already applied on
    # installs where constance's own migrations are not, and Django rejects
    # that history as inconsistent.
    dependencies = [
        ("api_general", "0004_dashboardcard"),
    ]

    operations = [
        migrations.RunPython(import_home_page_cards, delete_dashboard_cards),
    ]
