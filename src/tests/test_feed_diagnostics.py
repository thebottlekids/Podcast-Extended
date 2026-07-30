"""Tests for feed diagnostics and title-filter re-application."""

import datetime

from app.extensions import db
from app.feeds import feed_diagnostics, posts_failing_title_filter
from app.models import Feed, Post


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


def test_posts_failing_title_filter_finds_pre_existing_whitelisted(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed", title_filter_exclude="weekly")
        _make_post(feed, tmp_path, "Main Episode", "keep")
        stale = _make_post(feed, tmp_path, "Weekly Roundup", "drop")
        # Not whitelisted, so not a candidate for unwhitelisting.
        _make_post(feed, tmp_path, "Weekly Extra", "already-off", whitelisted=False)

        failing = posts_failing_title_filter(feed)

        assert [p.id for p in failing] == [stale.id]


def test_posts_failing_title_filter_empty_without_rules(app, tmp_path):
    with app.app_context():
        feed = _make_feed(title="Feed")
        _make_post(feed, tmp_path, "Weekly Roundup", "a")

        assert posts_failing_title_filter(feed) == []


def test_feed_diagnostics_counts(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://podcast.example.net")
    with app.app_context():
        feed = _make_feed(
            title="Feed", title_filter_exclude="weekly", episode_retention_count=5
        )
        _make_post(feed, tmp_path, "Good", "good")
        _make_post(feed, tmp_path, "Weekly Roundup", "filtered")
        _make_post(feed, tmp_path, "No Audio", "noaudio", audio=False)
        _make_post(feed, tmp_path, "Not Whitelisted", "off", whitelisted=False)
        gone = _make_post(feed, tmp_path, "Missing File", "gone")
        tmp_path.joinpath("gone.mp3").unlink()

        report = feed_diagnostics(feed)

        assert report["feed_id"] == feed.id
        assert report["counts"]["total"] == 5
        assert report["counts"]["whitelisted"] == 4
        assert report["counts"]["whitelisted_without_audio"] == 1
        assert report["counts"]["processed_file_missing"] == 1
        assert report["counts"]["excluded_by_title_filter"] == 1
        assert report["counts"]["publishable"] == 1
        assert report["title_filters"]["exclude"] == "weekly"
        assert report["episode_retention_count"] == 5
        assert gone.title == "Missing File"


def test_feed_diagnostics_flags_public_origin(app, tmp_path, monkeypatch):
    with app.app_context():
        feed = _make_feed(title="Feed")

        monkeypatch.setenv("PUBLIC_BASE_URL", "https://podcast.example.net")
        report = feed_diagnostics(feed)
        assert report["public_origin"]["scheme"] == "https"
        assert report["public_origin"]["explicitly_configured"] is True
        assert report["public_origin"]["is_loopback_or_private"] is False

        # No explicit origin: falls back to localhost, which no hosted podcast
        # client can reach.
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        report = feed_diagnostics(feed)
        assert report["public_origin"]["explicitly_configured"] is False
        assert report["public_origin"]["is_loopback_or_private"] is True


def test_feed_diagnostics_identity_is_clean(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://podcast.example.net")
    with app.app_context():
        feed = _make_feed(title="Feed")
        _make_post(feed, tmp_path, "A", "90653652-589a-4d51-bd3a-b495000f7c4b")
        _make_post(feed, tmp_path, "B", "b", day=2)

        report = feed_diagnostics(feed)

        assert report["identity"]["duplicate_published_guids"] == 0
        assert report["identity"]["published_guid_matches_upstream"] == 0


def test_private_host_detection(app, monkeypatch):
    from app.feeds import _is_private_host

    assert _is_private_host("127.0.0.1") is True
    assert _is_private_host("localhost") is True
    assert _is_private_host("192.168.1.242") is True
    assert _is_private_host(None) is True
    assert _is_private_host("podcast.example.net") is False
