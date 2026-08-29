from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask

from app.auth.authentik_service import (
    NoAdminUserError,
    build_authorization_url,
    generate_pkce_pair,
    get_admin_user,
)
from app.auth.authentik_settings import AuthentikSettings
from app.extensions import db
from app.models import User


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(flask_app)
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def settings() -> AuthentikSettings:
    return AuthentikSettings(
        enabled=True,
        issuer="https://auth.example.com/application/o/podcast-extended-oidc",
        client_id="test-client-id",
        redirect_uri="https://podcast.example.com/api/auth/authentik/callback",
        authorization_endpoint="https://auth.example.com/application/o/authorize/",
        token_endpoint="https://auth.example.com/application/o/token/",
        userinfo_endpoint="https://auth.example.com/application/o/userinfo/",
    )


def test_generate_pkce_pair_challenge_matches_verifier() -> None:
    pair = generate_pkce_pair()
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert pair.challenge == expected_challenge
    # RFC 7636 requires the verifier to be 43-128 characters.
    assert 43 <= len(pair.verifier) <= 128


def test_generate_pkce_pair_is_random() -> None:
    a = generate_pkce_pair()
    b = generate_pkce_pair()
    assert a.verifier != b.verifier
    assert a.challenge != b.challenge


def test_build_authorization_url_includes_pkce_and_no_secret(
    settings: AuthentikSettings,
) -> None:
    url = build_authorization_url(settings, state="abc123", code_challenge="chal123")
    parsed = urlparse(url)
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == settings.authorization_endpoint
    )
    params = parse_qs(parsed.query)
    assert params["client_id"] == [settings.client_id]
    assert params["redirect_uri"] == [settings.redirect_uri]
    assert params["response_type"] == ["code"]
    assert params["state"] == ["abc123"]
    assert params["code_challenge"] == ["chal123"]
    assert params["code_challenge_method"] == ["S256"]
    assert "client_secret" not in params


def test_get_admin_user_returns_admin(app: Flask) -> None:
    with app.app_context():
        user = User(username="chitchat", role="admin")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

        admin = get_admin_user()
        assert admin.username == "chitchat"


def test_get_admin_user_raises_when_no_admin_exists(app: Flask) -> None:
    with app.app_context():
        user = User(username="limited", role="user")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

        with pytest.raises(NoAdminUserError):
            get_admin_user()
