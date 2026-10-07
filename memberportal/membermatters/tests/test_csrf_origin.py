"""Pins how Django 4's CSRF Origin check treats the ways a POST reaches Django.

Since Django 4.0 the browser's Origin header has to match the scheme and host
Django believes it is serving, or be listed in CSRF_TRUSTED_ORIGINS. Members
authenticate with a session, so this applies to every change they make, not
just to the admin login form.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.test import Client

from tests.factories import ProfileFactory

# Any well-formed secret works: the check only needs cookie and token to agree.
CSRF_SECRET = "a" * 32

SOURCES = {
    # nginx as set up in docs/POST_INSTALL_STEPS.md
    "production proxy": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_X_FORWARDED_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://portal.example.org",
        "HTTP_REFERER": "https://portal.example.org/",
        "HTTP_X_FORWARDED_PROTO": "https",
    },
    # The case docs/UPGRADING.md warns about: TLS ends at the proxy, which
    # doesn't say so, so Django compares against http://portal.example.org.
    "proxy without X-Forwarded-Proto": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_X_FORWARDED_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://portal.example.org",
        "HTTP_REFERER": "https://portal.example.org/",
    },
    # The container's own nginx reached on its published port, as after
    # GETTING_STARTED's `docker create -p 8000:8000`: no proxy and no TLS.
    "container nginx on port 8000": {
        "HTTP_HOST": "portal.example.org:8000",
        "HTTP_X_FORWARDED_HOST": "portal.example.org:8000",
        "HTTP_ORIGIN": "http://portal.example.org:8000",
        "HTTP_REFERER": "http://portal.example.org:8000/",
    },
    # The same request when nginx forwarded $host, which drops the port.
    "container nginx dropping the port": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_X_FORWARDED_HOST": "portal.example.org",
        "HTTP_ORIGIN": "http://portal.example.org:8000",
        "HTTP_REFERER": "http://portal.example.org:8000/",
    },
    # A proxy in front that adds the default port, as nginx's
    # `Host $host:$server_port` does. The browser leaves it out of Origin, so
    # the container's nginx has to drop it before Django compares the two.
    "default port left in": {
        "HTTP_HOST": "portal.example.org:443",
        "HTTP_X_FORWARDED_HOST": "portal.example.org:443",
        "HTTP_ORIGIN": "https://portal.example.org",
        "HTTP_REFERER": "https://portal.example.org/",
        "HTTP_X_FORWARDED_PROTO": "https",
    },
    # quasar.config.js proxies /admin and /openid with changeOrigin: true
    "frontend dev server": {
        "HTTP_HOST": "127.0.0.1:8000",
        "HTTP_ORIGIN": "http://localhost:8080",
        "HTTP_REFERER": "http://localhost:8080/",
    },
    "another site": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_X_FORWARDED_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://attacker.example",
        "HTTP_REFERER": "https://attacker.example/",
        "HTTP_X_FORWARDED_PROTO": "https",
    },
}


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/logout/", "/admin/login/"])
@pytest.mark.parametrize(
    "source, rejected",
    [
        ("production proxy", False),
        ("proxy without X-Forwarded-Proto", True),
        ("container nginx on port 8000", False),
        ("container nginx dropping the port", True),
        ("default port left in", True),
        ("frontend dev server", False),
        ("another site", True),
    ],
)
def test_csrf_origin_check(path, source, rejected):
    client = Client(enforce_csrf_checks=True)
    if path == "/api/logout/":
        # DRF only enforces CSRF on session-authenticated requests.
        client.force_login(ProfileFactory().user)
    client.cookies["csrftoken"] = CSRF_SECRET

    response = client.post(
        path,
        {"csrfmiddlewaretoken": CSRF_SECRET},
        HTTP_X_CSRFTOKEN=CSRF_SECRET,
        **SOURCES[source],
    )

    rejected_by_csrf = response.status_code == 403 and b"CSRF" in response.content
    assert rejected_by_csrf is rejected


NGINX_CONF = Path(__file__).resolve().parents[3] / "docker" / "nginx.conf"


def container_nginx_forwarded_host(scheme, host):
    """Evaluates the container nginx's $forwarded_host map as nginx does: the
    regexes in order, the first match wins, and otherwise the default."""
    entries = re.search(
        r'map "\$proxied_scheme://\$http_host" \$forwarded_host \{(.*?)\}',
        NGINX_CONF.read_text(),
        re.S,
    ).group(1)
    for pattern, value in re.findall(r"~(\S+)\s+(\S+);", entries):
        match = re.search(pattern.replace("(?<", "(?P<"), f"{scheme}://{host}")
        if match:
            return match.expand(re.sub(r"\$(\w+)", r"\\g<\1>", value))
    return host


def test_the_container_nginx_forwards_the_mapped_host():
    # USE_X_FORWARDED_HOST makes Django read X-Forwarded-Host rather than
    # Host, so both carry the same value.
    host_headers = re.findall(
        r"proxy_set_header\s+((?:X-Forwarded-)?Host)\s+(\S+);",
        NGINX_CONF.read_text(),
    )
    assert {name for name, _ in host_headers} == {"Host", "X-Forwarded-Host"}
    assert {value for _, value in host_headers} == {"$forwarded_host"}


@pytest.mark.parametrize(
    "scheme, host, forwarded",
    [
        ("https", "portal.example.org", "portal.example.org"),
        # "default port left in" above
        ("https", "portal.example.org:443", "portal.example.org"),
        ("http", "portal.example.org:80", "portal.example.org"),
        ("https", "portal.example.org:8443", "portal.example.org:8443"),
        # "container nginx on port 8000" above
        ("http", "portal.example.org:8000", "portal.example.org:8000"),
        # Not the scheme's default port, so the browser shows it too.
        ("http", "portal.example.org:443", "portal.example.org:443"),
    ],
)
def test_the_container_nginx_drops_only_the_default_port(scheme, host, forwarded):
    assert container_nginx_forwarded_host(scheme, host) == forwarded


def test_production_trusts_no_extra_origins():
    # Settings are read once per process, so load the production ones in a
    # fresh interpreter.
    env = {
        **os.environ,
        "MM_ENV": "Production",
        "MM_SECRET_KEY": "test",
        "MM_ALLOWED_HOSTS": "portal.example.org",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, membermatters.settings as s; "
            "print(json.dumps(s.CSRF_TRUSTED_ORIGINS))",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == []
