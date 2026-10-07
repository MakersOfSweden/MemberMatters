"""Signing in to other services through the portal (django-oidc-provider).

Runs the authorization code flow the way a relying party such as a wiki does:
the member is sent to authorize, the service swaps the code for tokens, checks
the ID token's signature, and reads userinfo, which carries the membership
claims from oidc_provider_settings.
"""

from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oidc_provider.models import Client, ResponseType, RSAKey

from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

REDIRECT_URI = "https://wiki.example.org/callback"
LOGOUT_URI = "https://wiki.example.org/signed-out"
# The length of the secrets the admin generates.
SECRET = "5ec2e7" * 10
SCOPE = "openid profile email membershipinfo"


@pytest.fixture
def signing_key():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return RSAKey.objects.create(
        key=private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
    )


def relying_party(jwt_alg):
    client = Client.objects.create(
        name="Wiki",
        client_type="confidential",
        client_id="wiki",
        client_secret=SECRET,
        jwt_alg=jwt_alg,
        require_consent=False,
        _redirect_uris=REDIRECT_URI,
        _post_logout_redirect_uris=LOGOUT_URI,
    )
    # Normally created by oidc_provider's migrations, which this suite skips.
    code, _ = ResponseType.objects.get_or_create(
        value="code", defaults={"description": "code (Authorization Code Flow)"}
    )
    client.response_types.add(code)
    return client


def sign_in(client, member):
    """The member's browser at authorize, then the service at the token endpoint."""
    client.force_login(member.user)
    response = client.get(
        "/api/openid/authorize",
        {
            "client_id": "wiki",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "state": "xyz",
            "nonce": "n-0S6",
        },
    )
    assert response.status_code == 302, response.content
    redirect = urlsplit(response["Location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT_URI
    query = parse_qs(redirect.query)
    assert query["state"] == ["xyz"]

    response = client.post(
        "/api/openid/token",
        {
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": "wiki",
            "client_secret": SECRET,
        },
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def member():
    return ProfileFactory(
        user__email="ada@example.com",
        first_name="Ada",
        last_name="Lovelace",
        screen_name="ada",
        state="active",
    )


def assert_id_token_claims(claims, member):
    assert claims["iss"] == "http://testserver/api/openid"
    assert claims["aud"] == "wiki"
    assert claims["sub"] == str(member.user.pk)
    assert claims["nonce"] == "n-0S6"


def test_an_rs256_id_token_verifies_against_the_published_keys(
    client, member, signing_key
):
    relying_party("RS256")

    tokens = sign_in(client, member)

    keys = client.get("/api/openid/jwks").json()["keys"]
    assert [key["kid"] for key in keys] == [signing_key.kid]
    header = jwt.get_unverified_header(tokens["id_token"])
    assert (header["alg"], header["kid"]) == ("RS256", signing_key.kid)
    claims = jwt.decode(
        tokens["id_token"],
        jwt.PyJWK(keys[0]).key,
        algorithms=["RS256"],
        audience="wiki",
    )
    assert_id_token_claims(claims, member)


def test_an_hs256_id_token_verifies_with_the_client_secret(client, member):
    relying_party("HS256")

    tokens = sign_in(client, member)

    claims = jwt.decode(
        tokens["id_token"], SECRET, algorithms=["HS256"], audience="wiki"
    )
    assert_id_token_claims(claims, member)


def test_userinfo_carries_the_membership_claims(client, member, signing_key):
    relying_party("RS256")
    tokens = sign_in(client, member)

    userinfo = client.get(
        "/api/openid/userinfo",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    ).json()

    assert {
        key: userinfo[key]
        for key in (
            "sub",
            "email",
            "given_name",
            "family_name",
            "preferred_username",
            "state",
            "active",
            "groups",
        )
    } == {
        "sub": str(member.user.pk),
        "email": "ada@example.com",
        "given_name": "Ada",
        "family_name": "Lovelace",
        "preferred_username": "ada",
        "state": "active",
        "active": True,
        "groups": ["active"],
    }


def test_signing_out_returns_to_the_service(client, member, signing_key):
    relying_party("RS256")
    tokens = sign_in(client, member)

    response = client.get(
        "/api/openid/end-session",
        {"id_token_hint": tokens["id_token"], "post_logout_redirect_uri": LOGOUT_URI},
    )

    assert response.status_code == 302
    assert response["Location"].startswith(LOGOUT_URI)
