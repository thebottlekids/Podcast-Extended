from __future__ import annotations

from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask

from app.auth.authentik_settings import AuthentikSettings
from app.extensions import db
from app.models import User
from app.routes.authentik_routes import authentik_bp

SETTINGS = AuthentikSettings(
    enabled=True,
    issuer="https://auth.example.com/application/o/podcast-extended-oidc",
    client_id="test-client-id",
    redirect_uri="https://podcast.example.com/api/auth/authentik/callback",
    authorization_endpoint="https://auth.example.com/application/o/authorize/",
    token_endpoint="https://auth.example.com/application/o/token/",
    userinfo_endpoint="https://auth.example.com/application/o/userinfo/",
)

DISABLED_SETTINGS = AuthentikSettings(
    enabled=False,
    issuer=None,
    client_id=None,
    redirect_uri=None,
    authorization_endpoint=None,
    token_endpoint=None,
    userinfo_endpoint=None,
)


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        AUTHENTIK_SETTINGS=SETTINGS,
    )
    db.init_app(flask_app)
    with flask_app.app_context():
        db.create_all()
        admin = User(username="chitchat", role="admin")
        admin.set_password("password")
        db.session.add(admin)
        db.session.commit()

    flask_app.register_blueprint(authentik_bp)

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def test_status_reports_enabled(app: Flask) -> None:
    client = app.test_client()
    response = client.get("/api/auth/authentik/status")
    assert response.status_code == 200
    assert response.get_json() == {"enabled": True}


def test_status_reports_disabled(app: Flask) -> None:
    app.config["AUTHENTIK_SETTINGS"] = DISABLED_SETTINGS
    client = app.test_client()
    response = client.get("/api/auth/authentik/status")
    assert response.status_code == 200
    assert response.get_json() == {"enabled": False}


def test_login_returns_authorization_url_with_pkce(app: Flask) -> None:
    client = app.test_client()
    response = client.get("/api/auth/authentik/login")
    assert response.status_code == 200

    data = response.get_json()
    parsed = urlparse(data["authorization_url"])
    params = parse_qs(parsed.query)
    assert params["client_id"] == [SETTINGS.client_id]
    assert "state" in params
    assert "code_challenge" in params
    assert params["code_challenge_method"] == ["S256"]

    with client.session_transaction() as session:
        assert session["authentik_oauth_state"] == params["state"][0]
        assert "authentik_pkce_verifier" in session


def test_login_disabled_returns_404(app: Flask) -> None:
    app.config["AUTHENTIK_SETTINGS"] = DISABLED_SETTINGS
    client = app.test_client()
    response = client.get("/api/auth/authentik/login")
    assert response.status_code == 404


def test_callback_rejects_state_mismatch(app: Flask) -> None:
    client = app.test_client()
    with client.session_transaction() as session:
        session["authentik_oauth_state"] = "expected-state"
        session["authentik_pkce_verifier"] = "verifier"

    response = client.get(
        "/api/auth/authentik/callback?state=wrong-state&code=abc",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["Location"]


@mock.patch("app.routes.authentik_routes.get_userinfo")
@mock.patch("app.routes.authentik_routes.exchange_code_for_token")
def test_callback_success_logs_in_as_admin(
    mock_exchange: mock.MagicMock, mock_userinfo: mock.MagicMock, app: Flask
) -> None:
    mock_exchange.return_value = {"access_token": "fake-token"}
    mock_userinfo.return_value = {
        "sub": "some-authentik-user-id",
        "email": "someone@example.com",
    }

    client = app.test_client()
    with client.session_transaction() as session:
        session["authentik_oauth_state"] = "expected-state"
        session["authentik_pkce_verifier"] = "verifier"

    response = client.get(
        "/api/auth/authentik/callback?state=expected-state&code=abc",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    with app.app_context():
        admin = User.query.filter_by(username="chitchat").first()

    with client.session_transaction() as session:
        assert session["user_id"] == admin.id
        # State/verifier are consumed, not left lying around for reuse.
        assert "authentik_oauth_state" not in session
        assert "authentik_pkce_verifier" not in session


def test_callback_maps_every_identity_to_the_same_admin_account(app: Flask) -> None:
    """Two different Authentik identities both land on the one local admin
    account -- this is a single-admin household deployment, not per-person
    Podly accounts (see get_admin_user)."""
    with app.app_context():
        second_admin_check = User.query.filter_by(role="admin").count()
        assert second_admin_check == 1

    for sub in ("user-a", "user-b"):
        with mock.patch(
            "app.routes.authentik_routes.exchange_code_for_token",
            return_value={"access_token": "fake-token"},
        ), mock.patch(
            "app.routes.authentik_routes.get_userinfo",
            return_value={"sub": sub, "email": f"{sub}@example.com"},
        ):
            client = app.test_client()
            with client.session_transaction() as session:
                session["authentik_oauth_state"] = "state"
                session["authentik_pkce_verifier"] = "verifier"

            response = client.get(
                "/api/auth/authentik/callback?state=state&code=abc",
                follow_redirects=False,
            )
            assert response.status_code == 302

            with app.app_context():
                admin = User.query.filter_by(username="chitchat").first()
            with client.session_transaction() as session:
                assert session["user_id"] == admin.id
