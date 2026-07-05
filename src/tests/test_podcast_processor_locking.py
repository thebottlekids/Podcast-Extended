"""
Tests for PodcastProcessor's per-GUID lock lifecycle: acquiring an in-use lock
raises, and releasing a lock removes its dict entry so
PodcastProcessor.locks doesn't grow without bound over the process's
lifetime (one entry per distinct post GUID ever processed).
"""

from unittest.mock import MagicMock

from app.extensions import db
from app.models import Feed, Post, ProcessingJob
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.podcast_downloader import PodcastDownloader
from podcast_processor.podcast_processor import PodcastProcessor, ProcessorException
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.transcription_manager import TranscriptionManager
from shared.test_utils import create_standard_test_config


def _make_processor() -> PodcastProcessor:
    return PodcastProcessor(
        config=create_standard_test_config(),
        transcription_manager=MagicMock(spec=TranscriptionManager),
        ad_classifier=MagicMock(spec=AdClassifier),
        audio_processor=MagicMock(spec=AudioProcessor),
        status_manager=MagicMock(spec=ProcessingStatusManager),
        db_session=db.session,
        downloader=MagicMock(spec=PodcastDownloader),
    )


def _make_post(guid: str, tmp_path) -> Post:
    """Caller must already be inside an active app context."""
    feed = Feed(
        title="Test Feed",
        description="d",
        author="a",
        rss_url=f"https://example.com/{guid}.xml",
    )
    db.session.add(feed)
    db.session.commit()

    post = Post(
        guid=guid,
        title="Test Episode",
        download_url=f"https://example.com/{guid}.mp3",
        feed_id=feed.id,
        unprocessed_audio_path=str(tmp_path / "raw.mp3"),
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_second_acquire_for_same_guid_raises_while_locked(app, tmp_path) -> None:
    with app.app_context():
        PodcastProcessor.locks.clear()
        processor = _make_processor()
        post = _make_post("guid-locking-1", tmp_path)

        processor._acquire_processing_lock(
            post, ProcessingJob(id="job-1"), post.guid, "job-1", "Feed"
        )

        try:
            try:
                processor._acquire_processing_lock(
                    post, ProcessingJob(id="job-2"), post.guid, "job-2", "Feed"
                )
                assert False, "expected ProcessorException for an in-progress lock"
            except ProcessorException as e:
                assert "Processing job in progress" in str(e)
        finally:
            PodcastProcessor.locks[post.guid].release()
            PodcastProcessor.locks.pop(post.guid, None)


def test_lock_entry_is_removed_after_release_via_process_cleanup(app, tmp_path) -> None:
    with app.app_context():
        PodcastProcessor.locks.clear()
        processor = _make_processor()
        post = _make_post("guid-locking-2", tmp_path)

        processor._acquire_processing_lock(
            post, ProcessingJob(id="job-1"), post.guid, "job-1", "Feed"
        )
        assert post.guid in PodcastProcessor.locks

        # Mirror the cleanup logic in process()'s finally block.
        with PodcastProcessor.lock_lock:
            lock = PodcastProcessor.locks.get(post.guid)
            if lock is not None and lock.locked():
                lock.release()
                PodcastProcessor.locks.pop(post.guid, None)

        assert post.guid not in PodcastProcessor.locks


def test_reacquire_after_cleanup_succeeds_with_fresh_lock(app, tmp_path) -> None:
    with app.app_context():
        PodcastProcessor.locks.clear()
        processor = _make_processor()
        post = _make_post("guid-locking-3", tmp_path)

        processor._acquire_processing_lock(
            post, ProcessingJob(id="job-1"), post.guid, "job-1", "Feed"
        )
        with PodcastProcessor.lock_lock:
            PodcastProcessor.locks[post.guid].release()
            PodcastProcessor.locks.pop(post.guid, None)

        # Should succeed again now that the old entry is gone, not raise
        # "Processing job in progress" against a stale released lock.
        processor._acquire_processing_lock(
            post, ProcessingJob(id="job-2"), post.guid, "job-2", "Feed"
        )

        PodcastProcessor.locks[post.guid].release()
        PodcastProcessor.locks.pop(post.guid, None)
