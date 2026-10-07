"""The one-off import of the HOME_PAGE_CARDS constance setting into DashboardCard.

The suite runs with --no-migrations, so the RunPython functions are called
directly against the current models.
"""

import importlib
import json

import pytest
from constance.models import Constance
from django.apps import apps

from api_general.models import DashboardCard
from tests.helpers import pickled_setting

migration = importlib.import_module(
    "api_general.migrations.0005_import_home_page_cards"
)
second_import = importlib.import_module(
    "api_general.migrations.0007_import_home_page_cards_after_constance"
)

pytestmark = pytest.mark.django_db


def set_constance(key, value):
    # Pickled, as the import reads it before constance's 0003 converts it.
    Constance.objects.update_or_create(
        key=key, defaults={"value": pickled_setting(value)}
    )


def run_import():
    migration.import_home_page_cards(apps, None)


def test_imports_each_legacy_link_shape_in_order():
    set_constance(
        "HOME_PAGE_CARDS",
        json.dumps(
            [
                {
                    "title": "Wiki",
                    "description": "<p>The <b>rule book</b>.</p>",
                    "icon": "mdi-book",
                    "url": "https://bms.wiki",
                    "btn_text": "Read Wiki",
                },
                {
                    "title": "Member Bucks",
                    "description": "Pay for things.",
                    "icon": "mdi-cash",
                    "routerLink": {"name": "memberbucks", "params": {"x": "y"}},
                    "btn_text": "Member Bucks",
                },
                {
                    "title": "Discord",
                    "description": "Chat.",
                    "icon": "mdi-chat",
                    "links": [
                        {"url": "https://a.example", "btn_text": "A", "newLine": True},
                        {"url": "https://b.example", "btn_text": "B"},
                    ],
                },
            ]
        ),
    )

    run_import()

    cards = [card.get_admin_object() for card in DashboardCard.objects.all()]
    for card in cards:
        del card["id"]
    assert cards == [
        {
            "title": "Wiki",
            "icon": "mdi-book",
            "description": "<p>The <b>rule book</b>.</p>",
            "links": [{"label": "Read Wiki", "url": "https://bms.wiki"}],
            "enabled": True,
            "position": 0,
        },
        {
            "title": "Member Bucks",
            "icon": "mdi-cash",
            "description": "Pay for things.",
            "links": [{"label": "Member Bucks", "route": "memberbucks"}],
            "enabled": True,
            "position": 1,
        },
        {
            "title": "Discord",
            "icon": "mdi-chat",
            "description": "Chat.",
            "links": [
                {"label": "A", "url": "https://a.example"},
                {"label": "B", "url": "https://b.example"},
            ],
            "enabled": True,
            "position": 2,
        },
    ]


def test_imported_cards_can_be_saved_again():
    set_constance(
        "HOME_PAGE_CARDS",
        json.dumps(
            [
                {
                    "title": "Wiki",
                    "description": '<h3>Rules</h3><p onclick="x">Read</p>',
                    "icon": "class",
                    "url": "https://bms.wiki",
                },
                {
                    "title": "Discord",
                    "icon": "mdi-chat",
                    "links": [
                        {"url": "", "btn_text": "Empty"},
                        {"btn_text": "Missing"},
                        {"url": "https://a.example"},
                    ],
                },
            ]
        ),
    )

    run_import()

    wiki, discord = DashboardCard.objects.all()
    assert wiki.icon == "mdi-link-variant"
    assert wiki.description == "Rules<p>Read</p>"
    assert wiki.links == [{"label": "Wiki", "url": "https://bms.wiki"}]
    assert discord.links == [{"label": "Discord", "url": "https://a.example"}]


def test_missing_setting_imports_nothing():
    run_import()

    assert not DashboardCard.objects.exists()


@pytest.mark.parametrize("value", ["not json", '{"title": "Wiki"}'])
def test_invalid_setting_imports_nothing(value):
    set_constance("HOME_PAGE_CARDS", value)

    run_import()

    assert not DashboardCard.objects.exists()


def test_reverse_deletes_the_cards():
    DashboardCard.objects.create(title="Wiki", icon="mdi-book")

    migration.delete_dashboard_cards(apps, None)

    assert not DashboardCard.objects.exists()


def test_the_second_import_fills_an_empty_dashboard():
    set_constance(
        "HOME_PAGE_CARDS", json.dumps([{"title": "Wiki", "icon": "mdi-book"}])
    )

    second_import.import_home_page_cards_if_none(apps, None)

    assert list(DashboardCard.objects.values_list("title", flat=True)) == ["Wiki"]


def test_the_second_import_leaves_existing_cards_alone():
    DashboardCard.objects.create(title="Edited since", icon="mdi-book")
    set_constance(
        "HOME_PAGE_CARDS", json.dumps([{"title": "Wiki", "icon": "mdi-book"}])
    )

    second_import.import_home_page_cards_if_none(apps, None)

    assert list(DashboardCard.objects.values_list("title", flat=True)) == [
        "Edited since"
    ]
