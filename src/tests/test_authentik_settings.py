from __future__ import annotations

from unittest import mock

import pytest

from app.auth.authentik_settings import load_authentik_settings

DISCOVERY_DOC = {
    "authorization_endpoint": "https://auth.example.com/application/o/authorize/",
    "token_endpoint": "https://auth.example.com/application/o/token/",
    "userinfo_endpoint": "https://auth.example.com/application/o/userinfo/",
}

_ENV_VARS = ("AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_REDIRECT_URI")


def test_disabled_when_env_vars_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    settings = load_authentik_settings()
    assert settings.enabled is False


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AUTHENTIK_ISSUER",
        "https://auth.example.com/application/o/podcast-extended-oidc/",
    )
    monkeypatch.setenv("AUTHENTIK_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "AUTHENTIK_REDIRECT_URI",
        "https://podcast.example.com/api/auth/authentik/callback",
    )


@mock.patch("app.auth.authentik_settings.httpx.Client")
def test_enabled_with_successful_discovery(
    mock_client_cls: mock.MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_response = mock.MagicMock()
    mock_response.json.return_value = DISCOVERY_DOC
    mock_response.raise_for_status.return_value = None
    mock_client = mock.MagicMock()
    mock_client.get.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_client

    _set_required_env(monkeypatch)
    settings = load_authentik_settings()

    assert settings.enabled is True
    assert settings.client_id == "client-id"
    assert settings.authorization_endpoint == DISCOVERY_DOC["authorization_endpoint"]
    assert settings.token_endpoint == DISCOVERY_DOC["token_endpoint"]
    assert settings.userinfo_endpoint == DISCOVERY_DOC["userinfo_endpoint"]


@mock.patch("app.auth.authentik_settings.httpx.Client")
def test_disabled_when_discovery_fails(
    mock_client_cls: mock.MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client_cls.return_value.__enter__.side_effect = RuntimeError(
        "connection refused"
    )

    _set_required_env(monkeypatch)
    settings = load_authentik_settings()

    # Fails closed: Authentik being briefly unreachable disables SSO rather
    # than crashing app boot.
    assert settings.enabled is False
