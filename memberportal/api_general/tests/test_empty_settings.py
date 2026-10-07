"""api_general 0008: settings stored as NULL, which constance 4 can't read.

The suite runs with --no-migrations, so the RunPython function is called
directly.
"""

import importlib

import pytest
from constance import config
from constance.models import Constance
from django.apps import apps

from tests.helpers import pickled_setting

migration = importlib.import_module("api_general.migrations.0008_delete_empty_settings")

pytestmark = pytest.mark.django_db


def test_an_empty_setting_falls_back_to_its_default():
    # What the settings API stored for {"value": null} before constance 4.
    Constance.objects.create(key="SITE_OWNER", value=None)
    Constance.objects.create(key="SITE_NAME", value=pickled_setting("Makerspace"))

    migration.delete_empty_settings(apps, None)

    assert list(Constance.objects.values_list("key", flat=True)) == ["SITE_NAME"]
    assert config.SITE_OWNER == "MemberMatters"
