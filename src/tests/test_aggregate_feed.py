import pytest

from app.extensions import db
from app.feeds import get_user_aggregate_posts
from app.models import Feed, Post, UserFeed


def test_get_user_aggregate_posts_auth_disabled(app, tmp_path):
    """Test that all feeds are included when auth is disabled."""
    with app.app_context():
        app.config["REQUIRE_AUTH"] = False

        # Create feeds
        feed1 = Feed(rss_url="http://feed1.com", title="Feed 1")
        feed2 = Feed(rss_url="http://feed2.com", title="Feed 2")
        db.session.add_all([feed1, feed2])
        db.session.commit()

        # Create posts. is_post_publishable() requires the processed audio to
        # exist on disk, so write real files.
        audio1 = tmp_path / "post1.mp3"
        audio1.write_bytes(b"audio")
        audio2 = tmp_path / "post2.mp3"
        audio2.write_bytes(b"audio")

        post1 = Post(
            feed_id=feed1.id,
            title="Post 1",
            guid="1",
            whitelisted=True,
            processed_audio_path=str(audio1),
            download_url="http://url1",
        )
        post2 = Post(
            feed_id=feed2.id,
            title="Post 2",
            guid="2",
            whitelisted=True,
            processed_audio_path=str(audio2),
            download_url="http://url2",
        )
        db.session.add_all([post1, post2])
        db.session.commit()

        # Call function
        posts = get_user_aggregate_posts(user_id=999)  # User ID shouldn't matter

        assert len(posts) == 2
        assert post1 in posts
        assert post2 in posts


def test_get_user_aggregate_posts_auth_enabled(app, tmp_path):
    """Test that only subscribed feeds are included when auth is enabled."""
    with app.app_context():
        app.config["REQUIRE_AUTH"] = True

        # Create feeds
        feed1 = Feed(rss_url="http://feed1.com", title="Feed 1")
        feed2 = Feed(rss_url="http://feed2.com", title="Feed 2")
        db.session.add_all([feed1, feed2])
        db.session.commit()

        # Create posts. is_post_publishable() requires the processed audio to
        # exist on disk, so write real files.
        audio1 = tmp_path / "post1.mp3"
        audio1.write_bytes(b"audio")
        audio2 = tmp_path / "post2.mp3"
        audio2.write_bytes(b"audio")

        post1 = Post(
            feed_id=feed1.id,
            title="Post 1",
            guid="1",
            whitelisted=True,
            processed_audio_path=str(audio1),
            download_url="http://url1",
        )
        post2 = Post(
            feed_id=feed2.id,
            title="Post 2",
            guid="2",
            whitelisted=True,
            processed_audio_path=str(audio2),
            download_url="http://url2",
        )
        db.session.add_all([post1, post2])
        db.session.commit()

        # Subscribe user to feed1 only
        user_feed = UserFeed(user_id=1, feed_id=feed1.id)
        db.session.add(user_feed)
        db.session.commit()

        # Call function
        posts = get_user_aggregate_posts(user_id=1)

        assert len(posts) == 1
        assert post1 in posts
        assert post2 not in posts
