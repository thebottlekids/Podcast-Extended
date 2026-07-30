"""itunes:duration must reflect the processed audio, never the original."""

import datetime
import xml.etree.ElementTree as ET

import pytest

from app.extensions import db
from app.feeds import _format_itunes_duration, generate_feed_xml
from app.models import Feed, Post

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _feed_with_post(tmp_path, *, duration, processed_duration):
    feed = Feed(rss_url="http://example.com/feed", title="Feed")
    db.session.add(feed)
    db.session.commit()

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")

    post = Post(
        feed_id=feed.id,
        title="Episode",
        guid="guid",
        download_url="http://example.com/a.mp3",
        processed_audio_path=str(audio),
        whitelisted=True,
        duration=duration,
        processed_duration=processed_duration,
        release_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    )
    db.session.add(post)
    db.session.commit()
    return feed


def _published_duration(xml_bytes):
    root = ET.fromstring(xml_bytes)
    item = next(root.iter("item"))
    return item.findtext(f"{{{ITUNES_NS}}}duration")


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (3600, "01:00:00"),
        (3661, "01:01:01"),
        (59, "00:00:59"),
        (7325, "02:02:05"),
    ],
)
def test_format_itunes_duration(seconds, expected):
    assert _format_itunes_duration(seconds) == expected


@pytest.mark.parametrize("value", [None, 0, -5, "not a number"])
def test_format_itunes_duration_rejects_unusable(value):
    assert _format_itunes_duration(value) is None


def test_published_duration_is_the_processed_length(app, tmp_path):
    """The ad-free file is shorter than the publisher's original."""
    with app.app_context():
        feed = _feed_with_post(tmp_path, duration=3600, processed_duration=3180)

        published = _published_duration(generate_feed_xml(feed))

        assert published == "00:53:00"  # 3180s, not the original 3600s
        assert published != "01:00:00"


def test_duration_omitted_when_processed_length_unknown(app, tmp_path):
    """Episodes processed before this was recorded must not fall back to
    post.duration -- an overstated duration is worse than none, since clients
    read the true length from the file."""
    with app.app_context():
        feed = _feed_with_post(tmp_path, duration=3600, processed_duration=None)

        assert _published_duration(generate_feed_xml(feed)) is None
