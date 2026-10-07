"""How settings behave when the database misbehaves.

Before constance 4, a failed read looked like a missing setting, so constance
stored the default over the real value (jazzband/django-constance#348).
MemberMatters carried its own backend to stop that; these pin that constance's
own backend now does.
"""

import pytest
from constance import config
from constance.codecs import loads
from constance.models import Constance
from django.db import OperationalError, connection

pytestmark = pytest.mark.django_db


def fail_the_first_settings_read():
    failed = []

    def wrapper(execute, sql, params, many, context):
        if not failed and sql.startswith("SELECT") and "constance_constance" in sql:
            failed.append(sql)
            raise OperationalError("server closed the connection unexpectedly")
        return execute(sql, params, many, context)

    return wrapper


def test_a_failed_read_raises_and_keeps_the_stored_value():
    config.SITE_NAME = "Makerspace"

    # Only the first query fails, like a dropped connection that recovers, so
    # a backend that swallowed the error could write the default back.
    with connection.execute_wrapper(fail_the_first_settings_read()):
        with pytest.raises(OperationalError):
            config.SITE_NAME

    assert config.SITE_NAME == "Makerspace"


def test_a_missing_setting_is_stored_with_its_default():
    assert config.SITE_NAME == "MemberMatters Portal"
    stored = Constance.objects.get(key="SITE_NAME").value
    assert loads(stored) == "MemberMatters Portal"
