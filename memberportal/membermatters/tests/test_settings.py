"""Guards on the test settings themselves.

Each assertion here corresponds to one override in ``settings_test.py``. If
someone reorganises the real settings and an override stops applying, these
fail immediately and loudly — rather than the suite silently starting to write
log files, hit the Have I Been Pwned API, or 429 itself partway through a file.
"""

import logging
import os

from django.conf import settings


def test_no_file_log_handler_is_configured():
    # The real LOGGING config opens a RotatingFileHandler at MM_LOG_LOCATION
    # during django.setup(), which fails outright when that path doesn't exist.
    assert not [
        handler
        for handler in settings.LOGGING["handlers"].values()
        if "filename" in handler
    ]

    # And functionally: nothing in the live handler tree writes to a real file.
    # pytest installs its own FileHandler on /dev/null, which is exempt.
    live_file_handlers = [
        handler
        for logger in [logging.getLogger()]
        + [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        for handler in getattr(logger, "handlers", [])
        if isinstance(handler, logging.FileHandler)
        and handler.baseFilename != os.devnull
    ]
    assert not live_file_handlers


def test_database_is_ephemeral():
    database = settings.DATABASES["default"]

    # Neither leg uses the django_prometheus wrapper the real settings pick:
    # its per-query metrics add nothing under test and complicate teardown.
    assert not database["ENGINE"].startswith("django_prometheus")

    if "postgres" in database["ENGINE"]:
        # The CI matrix leg. Django creates and drops test_<NAME> around the
        # run, so the name itself isn't worth pinning.
        assert database["ENGINE"] == "django.db.backends.postgresql"
    else:
        assert database["ENGINE"] == "django.db.backends.sqlite3"
        # Asserted as a property rather than a literal: the configured value
        # is ":memory:", but once Django sets the test database up it rewrites
        # NAME to "file:memorydb_default?mode=memory&cache=shared". Both are
        # in-memory; comparing to either literal makes this test depend on
        # whether a db-using test ran first.
        assert "memory" in database["NAME"]


def test_pwned_passwords_validator_is_disabled():
    # Live HTTPS call from validate_password(), reached via Register and
    # ResetPassword. Tests that cover it opt back in with a fixture.
    names = [validator["NAME"] for validator in settings.AUTH_PASSWORD_VALIDATORS]
    assert not any("pwned" in name.lower() for name in names)
    # The remaining validators must still be in force, or password-rule tests
    # would pass vacuously.
    assert any("MinimumLengthValidator" in name for name in names)


def test_throttling_is_disabled_by_default():
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] == ()
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] == {}
    # Overriding the rates must not have dropped the rest of the DRF config.
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]


def test_channel_layer_is_in_memory():
    # Device commands are asserted by draining this layer, not by mocking.
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
    assert backend == "channels.layers.InMemoryChannelLayer"


def test_email_and_celery_do_not_leave_the_process():
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
