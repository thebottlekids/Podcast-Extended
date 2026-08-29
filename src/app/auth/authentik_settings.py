from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger("global_logger")

_DISCOVERY_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True, frozen=True)
class AuthentikSettings:
    enabled: bool
    issuer: str | None
    client_id: str | None
    redirect_uri: str | None
    authorization_endpoint: str | None
    token_endpoint: str | None
    userinfo_endpoint: str | None


_DISABLED = AuthentikSettings(
    enabled=False,
    issuer=None,
    client_id=None,
    redirect_uri=None,
    authorization_endpoint=None,
    token_endpoint=None,
    userinfo_endpoint=None,
)


def load_authentik_settings() -> AuthentikSettings:
    """Load Authentik OIDC settings from the environment.

    Unlike Discord SSO, this has no database-backed config UI: it's a single
    fixed identity provider for the household's own Authentik instance, not
    a per-deployment toggle end users configure. All three env vars are
    required to enable it.
    """
    issuer = (os.environ.get("AUTHENTIK_ISSUER") or "").strip().rstrip("/")
    client_id = (os.environ.get("AUTHENTIK_CLIENT_ID") or "").strip()
    redirect_uri = (os.environ.get("AUTHENTIK_REDIRECT_URI") or "").strip()

    if not (issuer and client_id and redirect_uri):
        return _DISABLED

    endpoints = _discover_endpoints(issuer)
    if endpoints is None:
        logger.warning(
            "Authentik SSO not enabled: could not fetch OIDC discovery document "
            "from issuer %s",
            issuer,
        )
        return _DISABLED

    authorization_endpoint, token_endpoint, userinfo_endpoint = endpoints
    return AuthentikSettings(
        enabled=True,
        issuer=issuer,
        client_id=client_id,
        redirect_uri=redirect_uri,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        userinfo_endpoint=userinfo_endpoint,
    )


def _discover_endpoints(issuer: str) -> tuple[str, str, str] | None:
    """Fetch the standard OIDC discovery document for `issuer`.

    A live fetch (rather than hardcoding Authentik's endpoint layout) means
    this keeps working across Authentik versions/reconfigurations without a
    code change. Failing closed (SSO disabled, not a boot crash) matters
    here: Podly must still start if Authentik is briefly unreachable.
    """
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        with httpx.Client(timeout=_DISCOVERY_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
        return (
            str(data["authorization_endpoint"]),
            str(data["token_endpoint"]),
            str(data["userinfo_endpoint"]),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Authentik OIDC discovery fetch failed for %s: %s", url, exc)
        return None


def reload_authentik_settings(app: "Flask") -> AuthentikSettings:
    """Reload Authentik settings and update app config."""
    settings = load_authentik_settings()
    app.config["AUTHENTIK_SETTINGS"] = settings
    return settings
