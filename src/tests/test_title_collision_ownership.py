"""Integration tests for the ownership-based title-collision fix (change set B).

Two posts in one feed can share a title ("Scott Horton"), and both then derive
``srv/<Feed>/<Title>.mp3``. These tests cover the three consumers that could
adopt or delete the wrong file:

* ``_check_existing_processed_audio`` — the adopt site,
* ``_acquire_processing_lock`` — the site that mints the processed filename,
* ``app.posts.remove_associated_files`` / ``_collect_processed_paths`` — the
  unlink site and its fallbacks.

Two derivations exist in the codebase and both are exercised here: the real
processed path (feed title with spaces -> underscores, from
``paths_from_unprocessed_path``) and the adopt site's historical variant (feed
title run through ``sanitize_title``, spaces preserved).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.extensions import db
from app.models import Feed, Post, ProcessingJob
from app.posts import (
    _collect_processed_paths,
    other_post_processed_paths,
    remove_associated_files,
)
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.podcast_downloader import PodcastDownloader, sanitize_title
from podcast_processor.podcast_processor import PodcastProcessor
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.transcription_manager import TranscriptionManager
from shared.processing_paths import get_srv_root, post_guid_suffix
from shared.test_utils import create_standard_test_config

FEED_TITLE = "Part Of The Problem"
POST_TITLE = "Scott Horton"
GUID_OLD = "28a011cd-0000-4000-8000-aaaaaaaaaaaa"
GUID_NEW = "77ddccbb-0000-4000-8000-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def _data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PODLY_PODCAST_DATA_DIR", str(tmp_path / "data"))


def _processor() -> PodcastProcessor:
    return PodcastProcessor(
        config=create_standard_test_config(),
        transcription_manager=MagicMock(spec=TranscriptionManager),
        ad_classifier=MagicMock(spec=AdClassifier),
        audio_processor=MagicMock(spec=AudioProcessor),
        status_manager=MagicMock(spec=ProcessingStatusManager),
        db_session=db.session,
        downloader=MagicMock(spec=PodcastDownloader),
    )


def _processed_path() -> Path:
    """The real processed path both same-title posts derive."""
    return get_srv_root() / "Part_Of_The_Problem" / f"{sanitize_title(POST_TITLE)}.mp3"


def _adopt_site_path() -> Path:
    """The path ``_check_existing_processed_audio`` derives (spaces kept)."""
    return (
        get_srv_root()
        / sanitize_title(FEED_TITLE)
        / f"{sanitize_title(POST_TITLE)}.mp3"
    )


def _suffixed(path: Path, guid: str) -> Path:
    return path.with_name(f"{path.stem}_{post_guid_suffix(guid)}.mp3")


def _seed_feed() -> Feed:
    feed = Feed(title=FEED_TITLE, rss_url="https://example.com/potp.xml")
    db.session.add(feed)
    db.session.commit()
    return feed


def _add_post(feed: Feed, guid: str, processed_path: str | None = None) -> Post:
    post = Post(
        guid=guid,
        title=POST_TITLE,
        download_url=f"https://example.com/{guid}.mp3",
        feed_id=feed.id,
        unprocessed_audio_path=str(
            Path("/data/in") / f"{sanitize_title(POST_TITLE)}.mp3"
        ),
        processed_audio_path=processed_path,
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    return post


def _write_audio(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-mp3-bytes")


def test_other_post_processed_paths_excludes_own_row(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        owned = _processed_path()
        post_old = _add_post(feed, GUID_OLD, str(owned))
        post_new = _add_post(feed, GUID_NEW)

        assert other_post_processed_paths(post_new) == frozenset({str(owned)})
        assert other_post_processed_paths(post_old) == frozenset()


def test_check_existing_processed_audio_does_not_adopt_sibling_file(app) -> None:
    """Adopt site: the canonical file belongs to the sibling -> not adopted."""
    with app.app_context():
        feed = _seed_feed()
        canonical = _adopt_site_path()
        _write_audio(canonical)
        _add_post(feed, GUID_OLD, str(canonical))
        post_new = _add_post(feed, GUID_NEW)

        processor = _processor()

        assert processor._check_existing_processed_audio(post_new) is False
        assert post_new.processed_audio_path is None
        assert canonical.exists()


def test_check_existing_processed_audio_adopts_own_suffixed_file(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        canonical = _adopt_site_path()
        own_path = _suffixed(canonical, GUID_NEW)
        _write_audio(canonical)
        _write_audio(own_path)
        _add_post(feed, GUID_OLD, str(canonical))
        post_new = _add_post(feed, GUID_NEW)

        processor = _processor()

        assert processor._check_existing_processed_audio(post_new) is True
        assert post_new.processed_audio_path == str(own_path.resolve())


def test_check_existing_processed_audio_keeps_legacy_solo_adoption(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        canonical = _adopt_site_path()
        _write_audio(canonical)
        post = _add_post(feed, GUID_NEW)

        processor = _processor()

        assert processor._check_existing_processed_audio(post) is True
        assert post.processed_audio_path == str(canonical.resolve())


def test_acquire_processing_lock_mints_suffixed_path_for_second_post(app) -> None:
    with app.app_context():
        PodcastProcessor.locks.clear()
        feed = _seed_feed()
        _add_post(feed, GUID_OLD, str(_processed_path()))
        post_new = _add_post(feed, GUID_NEW)

        processor = _processor()
        minted = processor._acquire_processing_lock(
            post_new, ProcessingJob(id="job-new"), post_new.guid, "job-new", FEED_TITLE
        )

        try:
            assert Path(minted) == _suffixed(_processed_path(), GUID_NEW)
        finally:
            lock = PodcastProcessor.locks.pop(post_new.guid, None)
            if lock is not None and lock.locked():
                lock.release()


def test_acquire_processing_lock_keeps_canonical_for_uncontested_post(app) -> None:
    with app.app_context():
        PodcastProcessor.locks.clear()
        feed = _seed_feed()
        post = _add_post(feed, GUID_NEW)

        processor = _processor()
        minted = processor._acquire_processing_lock(
            post, ProcessingJob(id="job-solo"), post.guid, "job-solo", FEED_TITLE
        )

        try:
            assert Path(minted) == _processed_path()
        finally:
            lock = PodcastProcessor.locks.pop(post.guid, None)
            if lock is not None and lock.locked():
                lock.release()


def test_collect_processed_paths_never_returns_sibling_file(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        canonical = _processed_path()
        _add_post(feed, GUID_OLD, str(canonical))
        post_new = _add_post(feed, GUID_NEW)

        resolved = {path.resolve() for path in _collect_processed_paths(post_new)}

        assert canonical.resolve() not in resolved
        assert _suffixed(canonical, GUID_NEW).resolve() in resolved


def test_remove_associated_files_keeps_sibling_file(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        canonical = _processed_path()
        _write_audio(canonical)
        _add_post(feed, GUID_OLD, str(canonical))
        post_new = _add_post(feed, GUID_NEW)

        # The unprocessed-path helper derives its directory at import time from
        # the app data root; stub it so this test only exercises file cleanup.
        with patch("app.posts.get_and_make_download_path", return_value=None):
            remove_associated_files(post_new)

        assert canonical.exists()


def test_remove_associated_files_deletes_only_own_suffixed_file(app) -> None:
    with app.app_context():
        feed = _seed_feed()
        canonical = _processed_path()
        own_path = _suffixed(canonical, GUID_NEW)
        _write_audio(canonical)
        _write_audio(own_path)
        _add_post(feed, GUID_OLD, str(canonical))
        post_new = _add_post(feed, GUID_NEW, str(own_path))

        with patch("app.posts.get_and_make_download_path", return_value=None):
            remove_associated_files(post_new)

        assert not own_path.exists()
        assert canonical.exists()
