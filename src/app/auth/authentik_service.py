from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.auth.authentik_settings import AuthentikSettings
from app.models import User

logger = logging.getLogger("global_logger")

_SCOPES = "openid profile email"


class AuthentikAuthError(Exception):
    """Base error for Authentik auth failures."""


class NoAdminUserError(AuthentikAuthError):
    """No local admin account exists to map an Authentik login onto."""


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def generate_oauth_state() -> str:
    """Generate a secure random state parameter for OAuth2 CSRF protection."""
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> PkcePair:
    """Generate an RFC 7636 PKCE code_verifier/code_challenge (S256) pair.

    The Authentik provider for Podly is a public client (no client_secret,
    see the OAuth2Provider record) -- PKCE is what stands in for a client
    secret here, so this is required, not optional hardening.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def build_authorization_url(
    settings: AuthentikSettings, state: str, code_challenge: str
) -> str:
    """Build the Authentik OIDC authorization URL."""
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.authorization_endpoint}?{urlencode(params)}"


def exchange_code_for_token(
    settings: AuthentikSettings, code: str, code_verifier: str
) -> dict[str, Any]:
    """Exchange an authorization code for tokens (synchronous).

    No client_secret is sent: the provider is a public client, authenticated
    by the PKCE code_verifier instead.
    """
    assert settings.token_endpoint is not None
    with httpx.Client() as client:
        response = client.post(
            settings.token_endpoint,
            data={
                "client_id": settings.client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def get_userinfo(settings: AuthentikSettings, access_token: str) -> dict[str, Any]:
    """Fetch OIDC userinfo (used only for logging which identity signed in --
    the resulting Podly session always maps to the local admin account, see
    get_admin_user())."""
    assert settings.userinfo_endpoint is not None
    with httpx.Client() as client:
        response = client.get(
            settings.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def get_admin_user() -> User:
    """Return the local admin account that every Authentik login maps onto.

    Access control lives in Authentik (the OIDC Application's policy binding
    restricts who can complete the login at all, see the household's
    homelab-admins group) rather than in per-identity Podly accounts -- this
    is a single-admin household deployment, not a multi-tenant one.
    """
    admin = User.query.filter_by(role="admin").order_by(User.id.asc()).first()
    if admin is None:
        raise NoAdminUserError("No local admin account exists")
    return admin  # type: ignore[no-any-return]
