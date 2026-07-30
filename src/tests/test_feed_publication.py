"""Tests for client-facing feed publication rules.

Covers the invariants a derived Podly feed must hold for a hosted podcast
client (Pocket Casts, AntennaPod) to treat it as a standalone podcast:
only playable episodes are advertised, episode identity is Podly's own, and
generated URLs use the configured public origin.
"""

import datetime
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.feeds import (
    _get_base_url,
    _normalized_public_base_url,
    generate_feed_xml,
    is_post_publishable,
    public_feed_guid,
)
from app.models import Feed, Post

ATOM_NS = "http://www.w3.org/2005/Atom"


def _make_feed(**kwargs):
    feed = Feed(rss_url=kwargs.pop("rss_url", "http://example.com/feed"), **kwargs)
    db.session.add(feed)
    db.session.commit()
    return feed


def _make_post(feed, tmp_path, title, guid, *, whitelisted=True, audio=True, day=1):
    processed_path = None
    if audio:
        tmp_path.mkdir(parents=True, exist_ok=True)
        audio_file = tmp_path / f"{guid}.mp3"
        audio_file.write_bytes(b"audio")
        processed_path = str(audio_file)

    post = Post(
        feed_id=feed.id,
        title=title,
        guid=guid,
        download_url=f"http://publisher.example.com/{guid}.mp3",
        processed_audio_path=processed_path,
        whitelisted=whitelisted,
        release_date=datetime.datetime(2024, 1, day, tzinfo=datetime.timezone.utc),
    )
    db.session.add(post)
    db.session.commit()
    return post


def _item_titles(xml_bytes):
    root = ET.fromstring(xml_bytes)
    return [item.findtext("title") for item in root.iter("item")]


# --- publication eligibility -------------------------------------------------


def test_missing_processed_file_is_not_publishable(app, tmp_path):
    """A cleaned-up or hand-deleted file must drop the episode from the feed."""
    with app.app_context():
        feed = _make_feed(title="Feed")
        post = _make_post(feed, tmp_path, "Gone", "gone")

        assert is_post_publishable(post) is True

        # Retention cleanup deletes audio; the DB row can outlive the file.
        tmp_path.joinpath("gone.mp3").unlink()

        assert is_post_publishable(post) is False
        assert _item_titles(generate_feed_xml(feed)) == []


def test_title_filter_excludes_already_whitelisted_post(app, tmp_path):
    """Title rules are enforced at publication, not only at ingest.

    Episodes ingested before a rule existed are already whitelisted, so the
    rule has to be applied when the feed is rendered or it never takes effect.
    """
    with app.app_context():
        feed = _make_feed(title="Feed", title_filter_exclude="weekly")
        kept = _make_post(feed, tmp_path, "Main Episode", "keep", day=2)
        excluded = _make_post(feed, tmp_path, "Weekly Roundup", "drop", day=1)

        assert is_post_publishable(kept) is True
        assert is_post_publishable(excluded) is False
        assert _item_titles(generate_feed_xml(feed)) == ["Main Episode"]


def test_title_filter_include_requires_a_match(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed", title_filter_include="regz")
        match = _make_post(feed, tmp_path, "REGZ and friends", "in", day=2)
        other = _make_post(feed, tmp_path, "Something else", "out", day=1)

        assert is_post_publishable(match) is True
        assert is_post_publishable(other) is False
        assert _item_titles(generate_feed_xml(feed)) == ["REGZ and friends"]


def test_retention_count_caps_published_items(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed", episode_retention_count=2)
        _make_post(feed, tmp_path, "Newest", "a", day=3)
        _make_post(feed, tmp_path, "Middle", "b", day=2)
        _make_post(feed, tmp_path, "Oldest", "c", day=1)

        assert _item_titles(generate_feed_xml(feed)) == ["Newest", "Middle"]


def test_items_are_ordered_newest_first(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed")
        _make_post(feed, tmp_path, "Oldest", "a", day=1)
        _make_post(feed, tmp_path, "Newest", "c", day=3)
        _make_post(feed, tmp_path, "Middle", "b", day=2)

        assert _item_titles(generate_feed_xml(feed)) == ["Newest", "Middle", "Oldest"]


# --- episode identity --------------------------------------------------------


def test_public_guid_is_stable_and_distinct_from_upstream(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed")
        upstream_guid = "90653652-589a-4d51-bd3a-b495000f7c4b"
        post = _make_post(feed, tmp_path, "Episode", upstream_guid)

        first = public_feed_guid(post)

        assert first.startswith("urn:uuid:")
        assert upstream_guid not in first
        # Deterministic across calls -- refreshes must not remint identity.
        assert public_feed_guid(post) == first


def test_public_guid_differs_across_feeds_for_same_upstream_guid():
    """A shared upstream GUID must not collide between two Podly feeds.

    Post.guid is unique in the database, so this exercises the helper directly
    rather than persisting two rows with the same GUID.
    """
    post_a = SimpleNamespace(feed_id=1, guid="shared-guid")
    post_b = SimpleNamespace(feed_id=2, guid="shared-guid")

    assert public_feed_guid(post_a) != public_feed_guid(post_b)


def test_feed_xml_publishes_namespaced_guid_and_podly_enclosure(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed")
        post = _make_post(feed, tmp_path, "Episode", "upstream-guid")

        xml = generate_feed_xml(feed)
        root = ET.fromstring(xml)
        item = next(root.iter("item"))

        assert item.findtext("guid") == public_feed_guid(post)
        assert item.find("guid").get("isPermaLink") == "false"
        assert "upstream-guid" not in item.findtext("guid")

        enclosure = item.find("enclosure")
        assert enclosure.get("type") == "audio/mpeg"
        assert f"/api/posts/{post.guid}/download" in enclosure.get("url")
        # The publisher's audio must never be advertised.
        assert "publisher.example.com" not in xml


def test_feed_xml_advertises_atom_self_link(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed")
        _make_post(feed, tmp_path, "Episode", "guid")

        root = ET.fromstring(generate_feed_xml(feed))
        self_link = root.find(f"./channel/{{{ATOM_NS}}}link")

        assert self_link is not None
        assert self_link.get("rel") == "self"
        assert self_link.get("type") == "application/rss+xml"
        assert self_link.get("href").endswith(f"/feed/{feed.id}")


# --- public origin -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://podcast.example.net", "https://podcast.example.net"),
        ("https://podcast.example.net/", "https://podcast.example.net"),
        ("https://podcast.example.net/podly/", "https://podcast.example.net/podly"),
        ("  https://podcast.example.net  ", "https://podcast.example.net"),
        ("https://podcast.example.net/?x=1", "https://podcast.example.net"),
    ],
)
def test_public_base_url_is_normalized(monkeypatch, raw, expected):
    monkeypatch.setenv("PUBLIC_BASE_URL", raw)
    assert _normalized_public_base_url() == expected


@pytest.mark.parametrize("raw", ["", "   ", "podcast.example.net", "ftp://host/x"])
def test_invalid_public_base_url_is_ignored(monkeypatch, raw):
    monkeypatch.setenv("PUBLIC_BASE_URL", raw)
    assert _normalized_public_base_url() is None


def test_public_base_url_overrides_request_headers(monkeypatch, app):
    """The explicit origin wins over request inference.

    waitress strips X-Forwarded-* unless given a trusted_proxy, so behind a
    tunnel the inferred scheme can be http even when the feed is served over
    HTTPS -- which some clients reject inside an https feed.
    """
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://podcast.example.net")
    with app.test_request_context("/feed/1", headers={"Host": "192.168.1.10:5040"}):
        assert _get_base_url() == "https://podcast.example.net"


def test_generated_urls_use_public_base_url(monkeypatch, app, tmp_path):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://podcast.example.net")
    with app.app_context():
        feed = _make_feed(title="Feed")
        _make_post(feed, tmp_path, "Episode", "guid")

        xml = generate_feed_xml(feed)

        assert "https://podcast.example.net/feed/" in xml
        assert "https://podcast.example.net/api/posts/" in xml
        assert "http://localhost:5001" not in xml
