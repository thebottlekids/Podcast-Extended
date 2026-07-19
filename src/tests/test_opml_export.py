from __future__ import annotations

from typing import Generator
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import pytest
from flask import Flask, Response, g

from app.auth import AuthSettings
from app.auth.middleware import init_auth_middleware
from app.auth.state import failure_rate_limiter
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User, UserFeed
from app.routes.auth_routes import auth_bp
from app.routes.feed_routes import feed_bp
from app.writer.client import writer_client

EXPECTED_FILENAME = "podcast-extended-subscriptions.opml"


def _make_app(require_auth: bool) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SESSION_COOKIE_NAME="podly_session",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    settings = AuthSettings(
        require_auth=require_auth,
        admin_username="admin",
        admin_password="password",
    )
    app.config["AUTH_SETTINGS"] = settings
    app.config["REQUIRE_AUTH"] = require_auth

    db.init_app(app)
    with app.app_context():
        db.create_all()
        admin = User(username="admin", role="admin")
        admin.set_password("password")
        db.session.add(admin)
        member = User(username="member", role="user", feed_allowance=10)
        member.set_password("password")
        db.session.add(member)
        db.session.commit()

    failure_rate_limiter._storage.clear()  # pylint: disable=protected-access

    init_auth_middleware(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(feed_bp)

    # Static stub routes win over feed_bp's converter rules, mirroring
    # test_session_auth.py, so token access can be tested without real RSS.
    @app.route("/feed/2", methods=["GET"])
    def feed_two() -> Response:
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("rss-ok", mimetype="text/plain")

    @app.route("/api/posts/<string:guid>/download", methods=["GET"])
    def download(guid: str) -> Response:
        del guid
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("download", mimetype="text/plain")

    return app


def _seed_feeds(app: Flask) -> None:
    """Feed 1 = default landing feed; member joins feed 2; feed 3 admin-only."""
    with app.app_context():
        landing = Feed(title="Landing & Friends", rss_url="https://example.com/1.xml")
        joined = Feed(title='the "Quoted" pödcast', rss_url="https://example.com/2.xml")
        hidden = Feed(title="Admin Only", rss_url="https://example.com/3.xml")
        db.session.add_all([landing, joined, hidden])
        db.session.commit()

        member = User.query.filter_by(username="member").one()
        db.session.add(UserFeed(user_id=member.id, feed_id=joined.id))
        post = Post(
            feed_id=joined.id,
            guid="episode-1",
            download_url="https://example.com/audio.mp3",
            title="Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()


@pytest.fixture
def auth_app() -> Generator[Flask, None, None]:
    app = _make_app(require_auth=True)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def noauth_app() -> Generator[Flask, None, None]:
    app = _make_app(require_auth=False)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _login(client, username: str = "admin") -> None:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "password"}
    )
    assert response.status_code == 200


def _export(client):
    return client.post("/api/user/opml-export")


def _outlines(response) -> list[ET.Element]:
    root = ET.fromstring(response.data)
    assert root.tag == "opml"
    assert root.get("version") == "2.0"
    assert root.find("head/title") is not None
    body = root.find("body")
    assert body is not None
    return list(body.findall("outline"))


def test_requires_auth_when_enabled(auth_app: Flask) -> None:
    client = auth_app.test_client()
    response = _export(client)
    assert response.status_code == 401


def test_admin_exports_all_feeds_sorted(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client)

    response = _export(client)
    assert response.status_code == 200
    outlines = _outlines(response)
    titles = [o.get("title") for o in outlines]
    assert titles == ["Admin Only", "Landing & Friends", 'the "Quoted" pödcast']

    for outline in outlines:
        assert outline.get("type") == "rss"
        assert outline.get("text") == outline.get("title")
        xml_url = outline.get("xmlUrl") or ""
        parsed = urlparse(xml_url)
        assert parsed.path.startswith("/feed/")
        params = parse_qs(parsed.query)
        assert params.get("feed_token")
        assert params.get("feed_secret")


def test_regular_user_exports_only_visible_feeds(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client, username="member")

    response = _export(client)
    assert response.status_code == 200
    outlines = _outlines(response)
    paths = sorted(urlparse(o.get("xmlUrl") or "").path for o in outlines)
    # Feed 1 (default landing) + feed 2 (joined); feed 3 must be absent.
    assert paths == ["/feed/1", "/feed/2"]


def test_noauth_exports_all_feeds_without_credentials(noauth_app: Flask) -> None:
    _seed_feeds(noauth_app)
    client = noauth_app.test_client()

    response = _export(client)
    assert response.status_code == 200
    outlines = _outlines(response)
    assert len(outlines) == 3
    for outline in outlines:
        xml_url = outline.get("xmlUrl") or ""
        assert urlparse(xml_url).query == ""

    with noauth_app.app_context():
        assert FeedAccessToken.query.count() == 0


def test_empty_export_is_valid_opml(auth_app: Flask) -> None:
    client = auth_app.test_client()
    _login(client)

    response = _export(client)
    assert response.status_code == 200
    assert _outlines(response) == []


def test_response_headers(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client)

    response = _export(client)
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/x-opml")
    assert "charset=utf-8" in response.headers["Content-Type"]
    assert EXPECTED_FILENAME in response.headers["Content-Disposition"]
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"


def test_special_characters_produce_valid_xml(auth_app: Flask) -> None:
    with auth_app.app_context():
        feed = Feed(
            title='<Ads> & "Sons" — l\'émission 🎙️',
            rss_url="https://example.com/x.xml?a=1&b=2",
        )
        db.session.add(feed)
        db.session.commit()

    client = auth_app.test_client()
    _login(client)

    response = _export(client)
    assert response.status_code == 200
    outlines = _outlines(response)  # ET.fromstring already proves well-formed XML
    assert outlines[-1].get("title") == '<Ads> & "Sons" — l\'émission 🎙️'


def test_exported_credentials_allow_anonymous_feed_access(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client, username="member")

    response = _export(client)
    assert response.status_code == 200
    outline_by_path = {
        urlparse(o.get("xmlUrl") or "").path: o for o in _outlines(response)
    }
    feed2_url = urlparse(outline_by_path["/feed/2"].get("xmlUrl") or "")
    params = {k: v[0] for k, v in parse_qs(feed2_url.query).items()}

    anon_client = auth_app.test_client()
    rss = anon_client.get("/feed/2", query_string=params)
    assert rss.status_code == 200
    assert rss.data == b"rss-ok"

    episode = anon_client.get("/api/posts/episode-1/download", query_string=params)
    assert episode.status_code == 200


def test_repeated_exports_reuse_tokens(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client, username="member")

    first = _export(client)
    second = _export(client)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data == second.data

    with auth_app.app_context():
        member = User.query.filter_by(username="member").one()
        per_feed = FeedAccessToken.query.filter_by(
            user_id=member.id, revoked=False
        ).count()
        # One token per visible feed (landing + joined), no duplicates.
        assert per_feed == 2


def test_share_link_token_is_reused_by_export(auth_app: Flask) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client)

    share = client.post("/api/feeds/2/share-link")
    assert share.status_code == 201
    share_payload = share.get_json()

    response = _export(client)
    assert response.status_code == 200
    outline_by_path = {
        urlparse(o.get("xmlUrl") or "").path: o for o in _outlines(response)
    }
    params = parse_qs(urlparse(outline_by_path["/feed/2"].get("xmlUrl") or "").query)
    assert params["feed_token"][0] == share_payload["feed_token"]
    assert params["feed_secret"][0] == share_payload["feed_secret"]


def test_token_failure_returns_generic_error(
    auth_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_feeds(auth_app)
    client = auth_app.test_client()
    _login(client)

    original_action = writer_client.action

    def _fail_bulk(action_name, params, wait=True):  # type: ignore[no-untyped-def]
        if action_name == "bulk_get_or_create_feed_access_tokens":
            return None
        return original_action(action_name, params, wait=wait)

    monkeypatch.setattr(writer_client, "action", _fail_bulk)

    response = _export(client)
    assert response.status_code == 500
    payload = response.get_json()
    assert payload == {"error": "Failed to generate OPML export."}
    assert b"feed_secret" not in response.data
    assert b"<opml" not in response.data
