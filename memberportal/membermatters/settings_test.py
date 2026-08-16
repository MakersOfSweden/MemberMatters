"""Settings used by the test suite.

Layered on top of the real settings rather than replacing them, so tests
exercise the production configuration wherever it is safe to do so. Only the
handful of settings that make a test run non-hermetic — file writes, outbound
network, shared rate-limit state — are overridden here, and each override
below says which one it is neutralising.

Activated via ``DJANGO_SETTINGS_MODULE`` in ``pytest.ini``.
"""

import os
import tempfile

from .settings import *  # noqa: F401,F403
from .settings import AUTH_PASSWORD_VALIDATORS, REST_FRAMEWORK

# The real LOGGING config attaches a RotatingFileHandler to MM_LOG_LOCATION,
# which defaults to the in-container path /usr/src/logs/django.log. Django
# configures logging during setup, so on a machine without that path the test
# run dies at import time — before a single test is collected. Routing
# everything to a null handler removes the failure mode instead of papering
# over it with an env var. Loggers propagate to root here (the real config
# sets propagate=False per logger), which is also what makes pytest's caplog
# fixture able to see project log records.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "WARNING"},
}

# Default to an in-memory SQLite DB: no file to clean up, no interference with
# the dev db.sqlite3. MM_TEST_DB=postgres selects the CI matrix leg — the only
# configuration where select_for_update() actually emits a lock (SQLite sets
# has_select_for_update = False and the query compiler silently drops the
# clause), so the concurrency design in Profile's state transitions is only
# genuinely covered there.
if os.environ.get("MM_TEST_DB") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "membermatters"),
            "USER": os.environ.get("POSTGRES_USER", "membermatters"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "membermatters"),
            "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

# Both legs drop the django_prometheus DB wrapper used in the real settings:
# the per-query metrics add nothing under test and its collectors complicate
# teardown across the many databases pytest-django creates.

# PwnedPasswordsValidator calls the Have I Been Pwned API over HTTPS, and
# validate_password() sits on the Register and ResetPassword paths. Dropping
# just that one validator keeps the rest of the password rules real, so tests
# still assert genuine validation behaviour. Tests that specifically cover the
# pwned check re-add it via the `enable_pwned_validator` fixture.
AUTH_PASSWORD_VALIDATORS = [
    validator
    for validator in AUTH_PASSWORD_VALIDATORS
    if "pwned" not in validator["NAME"].lower()
]

# Argon2/PBKDF2 hashing dominates the runtime of any suite that creates users
# through the real manager, which is exactly what the factories do.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# DRF throttling keys off client IP into the Django cache, and every test
# request arrives from the same address. With the real rates (register is
# 60/hour) a file of registration tests starts returning 429 partway through.
# Throttle behaviour itself is covered by tests that opt back in via the
# `enable_throttling` fixture.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": (),
    "DEFAULT_THROTTLE_RATES": {},
}

# Pinned rather than inherited: the real settings only pick the in-memory layer
# when MM_ENV is unset or non-production, and device commands (Doors.sync,
# Interlock.lock, ...) are asserted by draining this layer.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# No .delay()/apply_async call sites exist in the codebase today (Celery is
# only used for periodic tasks), so these are belt-and-braces against a future
# task call reaching for a broker that isn't there.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"

# Real default is the in-container /usr/src/data/media/.
MEDIA_ROOT = tempfile.mkdtemp(prefix="mm-test-media-")
