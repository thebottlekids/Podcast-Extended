import logging
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy.orm import object_session

from app.extensions import db
from app.models import Post
from app.writer.client import writer_client
from podcast_processor.podcast_downloader import get_and_make_download_path

logger = logging.getLogger("global_logger")


def other_post_processed_paths(
    post: Post, db_session: Any | None = None
) -> frozenset[str]:
    """Return processed-audio paths claimed by *other* posts in the same feed.

    Two posts that share a title derive the same processed filename, so the
    path alone cannot tell "mine" from "theirs". ``shared.processing_paths``
    deliberately has no DB access, so this ownership query is the
    ``taken_paths`` signal its callers pass in.

    Fails open (empty set) when the post has no feed/guid yet or the query
    fails, which degrades to the pre-fix path derivation instead of breaking a
    download or cleanup path.
    """
    feed_id = getattr(post, "feed_id", None)
    guid = getattr(post, "guid", None)
    if feed_id is None or not guid:
        return frozenset()

    session = db_session if db_session is not None else object_session(post)
    if session is None:
        session = db.session

    try:
        rows = (
            session.query(Post.processed_audio_path)
            .filter(
                Post.feed_id == feed_id,
                Post.guid != guid,
                Post.processed_audio_path.isnot(None),
            )
            .all()
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Could not load processed audio paths for feed %s; "
            "using legacy path derivation",
            feed_id,
            exc_info=True,
        )
        return frozenset()

    return frozenset(str(row[0]) for row in rows if row[0])


def _collect_processed_paths(post: Post) -> List[Path]:
    """Collect all possible processed audio paths to check for a post.

    Every derived candidate (fallbacks 2-4) is filtered through the
    ownership-aware disambiguation helper, so a same-title collision can never
    hand ``remove_associated_files`` a path that belongs to another post.
    """
    import re

    from podcast_processor.podcast_downloader import sanitize_title
    from shared.processing_paths import (
        disambiguate_processed_path,
        get_srv_root,
        paths_from_unprocessed_path,
    )

    processed_paths_to_check: List[Path] = []
    post_guid = getattr(post, "guid", None)
    taken_paths = other_post_processed_paths(post)

    # 1. Check database path first (most reliable if set)
    if post.processed_audio_path:
        processed_paths_to_check.append(Path(post.processed_audio_path))

    # 2. Compute path using paths_from_unprocessed_path (matches processor logic)
    if post.unprocessed_audio_path and post.feed and post.feed.title:
        processing_paths = paths_from_unprocessed_path(
            post.unprocessed_audio_path,
            post.feed.title,
            post_guid=post_guid,
            taken_paths=taken_paths,
        )
        if processing_paths:
            processed_paths_to_check.append(processing_paths.post_processed_audio_path)

    # 3. Fallback: compute expected path from post/feed titles
    if post.feed and post.feed.title and post.title:
        safe_feed_title = sanitize_title(post.feed.title)
        safe_post_title = sanitize_title(post.title)
        processed_paths_to_check.append(
            disambiguate_processed_path(
                get_srv_root() / safe_feed_title / f"{safe_post_title}.mp3",
                post_guid=post_guid,
                taken_paths=taken_paths,
            )
        )

        # 4. Also check with underscore-style sanitization
        sanitized_feed_title = re.sub(r"[^a-zA-Z0-9\s_.-]", "", post.feed.title).strip()
        sanitized_feed_title = sanitized_feed_title.rstrip(".")
        sanitized_feed_title = re.sub(r"\s+", "_", sanitized_feed_title)
        processed_paths_to_check.append(
            disambiguate_processed_path(
                get_srv_root() / sanitized_feed_title / f"{safe_post_title}.mp3",
                post_guid=post_guid,
                taken_paths=taken_paths,
            )
        )

    return processed_paths_to_check


def _dedupe_and_find_existing(paths: List[Path]) -> tuple[List[Path], Optional[Path]]:
    """Deduplicate paths and find the first existing one."""
    seen: set[Path] = set()
    unique_paths: List[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(resolved)

    existing_path: Optional[Path] = None
    for p in unique_paths:
        if p.exists():
            existing_path = p
            break

    return unique_paths, existing_path


def _remove_file_if_exists(path: Optional[Path], file_type: str, post_id: int) -> None:
    """Remove a file if it exists and log the result."""
    if not path:
        logger.debug(f"{file_type} path is None for post {post_id}.")
        return

    if not path.exists():
        logger.debug(f"No {file_type} file to remove for post {post_id}.")
        return

    try:
        path.unlink()
        logger.info(f"Removed {file_type} file: {path}")
    except OSError as e:
        logger.error(f"Failed to remove {file_type} file {path}: {e}")


def remove_associated_files(post: Post) -> None:
    """
    Remove unprocessed and processed audio files associated with a post.
    Computes paths from post/feed metadata to ensure files are found even
    if database paths are already cleared.

    We check multiple possible locations for processed audio because the path
    calculation has varied over time and between different code paths.
    """
    try:
        # Collect and find processed audio path
        processed_paths = _collect_processed_paths(post)
        unique_paths, processed_abs_path = _dedupe_and_find_existing(processed_paths)

        # Compute expected unprocessed audio path
        unprocessed_abs_path: Optional[Path] = None
        if post.title:
            unprocessed_path = get_and_make_download_path(post.title)
            if unprocessed_path:
                unprocessed_abs_path = Path(unprocessed_path).resolve()

        # Fallback: if we couldn't find a processed path, try using the stored path directly
        if processed_abs_path is None and post.processed_audio_path:
            processed_abs_path = Path(post.processed_audio_path).resolve()

        # Remove audio files
        _remove_file_if_exists(unprocessed_abs_path, "unprocessed audio", post.id)

        if processed_abs_path:
            _remove_file_if_exists(processed_abs_path, "processed audio", post.id)
        elif unique_paths:
            logger.debug(
                f"No processed audio file to remove for post {post.id}. "
                f"Checked paths: {[str(p) for p in unique_paths]}"
            )
        else:
            logger.debug(
                f"Could not determine processed audio path for post {post.id}."
            )

    except Exception as e:  # pylint: disable=broad-except
        logger.error(
            f"Unexpected error in remove_associated_files for post {post.id}: {e}",
            exc_info=True,
        )


def clear_post_processing_data(post: Post) -> None:
    """
    Clear all processing data for a post including:
    - Audio files (unprocessed and processed)
    - Database entries (transcript segments, identifications, model calls, processing jobs)
    - Reset relevant post fields
    """
    try:
        logger.info(
            f"Starting to clear processing data for post: {post.title} (ID: {post.id})"
        )

        # Remove audio files first
        remove_associated_files(post)

        writer_client.action(
            "clear_post_processing_data", {"post_id": post.id}, wait=True
        )

        logger.info(
            f"Successfully cleared all processing data for post: {post.title} (ID: {post.id})"
        )

    except Exception as e:
        logger.error(
            f"Error clearing processing data for post {post.id}: {e}",
            exc_info=True,
        )
        raise PostException(f"Failed to clear processing data: {str(e)}") from e


def clear_ad_detection_data(post: Post) -> dict[str, Any] | None:
    """
    Clear ad detection results for a post, preserving transcription.
    This allows retrying ad detection without re-transcribing.
    """
    try:
        logger.info(
            f"Clearing ad detection data for post: {post.title} (ID: {post.id})"
        )

        result = writer_client.action(
            "clear_ad_detection", {"post_id": post.id}, wait=True
        )

        logger.info(
            f"Successfully cleared ad detection data for post: {post.title} (ID: {post.id})"
        )

        return result.data if result else None

    except Exception as e:
        logger.error(
            f"Error clearing ad detection data for post {post.id}: {e}",
            exc_info=True,
        )
        raise PostException(f"Failed to clear ad detection data: {str(e)}") from e


def clear_audio_processing_data(post: Post) -> dict[str, Any] | None:
    """
    Clear processed audio for a post, preserving transcription and ad detection.
    This allows retrying just the audio processing step without re-transcribing or re-detecting.
    """
    try:
        logger.info(
            f"Clearing audio processing data for post: {post.title} (ID: {post.id})"
        )

        result = writer_client.action(
            "clear_audio_processing", {"post_id": post.id}, wait=True
        )

        logger.info(
            f"Successfully cleared audio processing data for post: {post.title} (ID: {post.id})"
        )

        return result.data if result else None

    except Exception as e:
        logger.error(
            f"Error clearing audio processing data for post {post.id}: {e}",
            exc_info=True,
        )
        raise PostException(f"Failed to clear audio processing data: {str(e)}") from e


class PostException(Exception):
    pass
