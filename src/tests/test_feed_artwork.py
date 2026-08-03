"""Channel artwork must be exposed as itunes:image, not only RSS <image>.

Podcast clients read show artwork from itunes:image; PyRSS2Gen emits only the
RSS 2.0 <image> element, which they ignore -- leaving the artwork blank.
"""

import datetime
import xml.etree.ElementTree as ET

from app.extensions import db
from app.feeds import generate_aggregate_feed_xml, generate_feed_xml
from app.models import Feed, Post

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

ARTWORK = "https://cdn.example.com/show-art.jpg"


def _feed_with_episode(tmp_path, image_url=ARTWORK):
    feed = Feed(rss_url="http://example.com/feed", title="Feed", image_url=image_url)
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
        image_url="https://cdn.example.com/episode-art.jpg",
        release_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    )
    db.session.add(post)
    db.session.commit()
    return feed


def test_channel_exposes_itunes_image(app, tmp_path):
    with app.app_context():
        feed = _feed_with_episode(tmp_path)

        channel = ET.fromstring(generate_feed_xml(feed)).find("channel")
        itunes_image = channel.find(f"{ITUNES}image")

        assert itunes_image is not None
        assert itunes_image.get("href") == ARTWORK


def test_channel_keeps_rss_image_too(app, tmp_path):
    """The RSS 2.0 element stays for readers that use it."""
    with app.app_context():
        feed = _feed_with_episode(tmp_path)

        channel = ET.fromstring(generate_feed_xml(feed)).find("channel")

        assert channel.findtext("image/url") == ARTWORK


def test_channel_artwork_omitted_when_feed_has_none(app, tmp_path):
    with app.app_context():
        feed = _feed_with_episode(tmp_path, image_url=None)

        channel = ET.fromstring(generate_feed_xml(feed)).find("channel")

        assert channel.find(f"{ITUNES}image") is None


def test_episode_artwork_still_present(app, tmp_path):
    """Channel artwork must not displace per-episode artwork."""
    with app.app_context():
        feed = _feed_with_episode(tmp_path)

        item = next(ET.fromstring(generate_feed_xml(feed)).iter("item"))
        episode_image = item.find(f"{ITUNES}image")

        assert episode_image is not None
        assert episode_image.get("href") == "https://cdn.example.com/episode-art.jpg"


def test_aggregate_feed_has_channel_artwork(app, tmp_path):
    with app.app_context():
        app.config["REQUIRE_AUTH"] = False
        _feed_with_episode(tmp_path)

        channel = ET.fromstring(generate_aggregate_feed_xml(None)).find("channel")
        itunes_image = channel.find(f"{ITUNES}image")

        assert itunes_image is not None
        assert itunes_image.get("href").endswith(".png")
        # Same asset as the RSS <image>, so clients agree on the artwork.
        assert itunes_image.get("href") == channel.findtext("image/url")
