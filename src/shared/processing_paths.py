import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Set


@dataclass
class ProcessingPaths:
    post_processed_audio_path: Path


# Number of characters taken from a post GUID for the collision suffix.
GUID_SUFFIX_LENGTH = 8


def _path_identity_keys(path: Path) -> Set[str]:
    """Return the string forms a path can be recognised by.

    Stored paths were written by different code eras (absolute, already
    resolved, trailing-slash variants), so ownership comparisons are made on
    both the literal and the resolved form.
    """
    keys = {str(path)}
    try:
        keys.add(str(path.resolve()))
    except OSError:  # pragma: no cover - resolution is best-effort
        pass
    return keys


def _taken_path_keys(taken_paths: AbstractSet[str]) -> Set[str]:
    keys: Set[str] = set()
    for taken in taken_paths:
        if taken:
            keys |= _path_identity_keys(Path(taken))
    return keys


def post_guid_suffix(post_guid: str | None) -> str | None:
    """Return the ``<guid8>`` fragment used to disambiguate a filename."""
    if not post_guid:
        return None
    compact = re.sub(r"[^0-9a-zA-Z]", "", post_guid)
    if not compact:
        return None
    return compact[:GUID_SUFFIX_LENGTH]


def disambiguate_processed_path(
    path: Path,
    *,
    post_guid: str | None,
    taken_paths: AbstractSet[str] = frozenset(),
) -> Path:
    """Suffix ``path`` with ``_<guid8>`` when another post already owns it.

    Ownership is passed in explicitly (``taken_paths`` holds the
    ``processed_audio_path`` values claimed by *other* posts in the feed)
    because ``src/shared`` must not touch the database.

    Rules, deliberately ownership-based rather than existence-based:

    * not owned by another post -> returned unchanged, so a post keeps the
      exact filename it has always had;
    * owned by another post -> the basename gains ``_<guid8>`` before the
      extension (``Scott Horton.mp3`` -> ``Scott Horton_28a011cd.mp3``);
    * no GUID available -> unchanged (legacy callers/posts without a guid);
    * a file that exists on disk but is claimed by no post is still returned
      unchanged: existence alone must never move a post's path, or
      re-processed posts would silently migrate to a new filename.

    The suffix is applied to whatever basename the caller derived (downloader
    filename, title sanitizer, ...), never re-derived from ``post.title``,
    because those sanitizers differ.
    """
    suffix = post_guid_suffix(post_guid)
    if suffix is None or not taken_paths:
        return path
    owned_by_other_post = _path_identity_keys(path) & _taken_path_keys(taken_paths)
    if not owned_by_other_post:
        return path
    return path.with_name(f"{path.stem}_{suffix}{path.suffix or '.mp3'}")


def paths_from_unprocessed_path(
    unprocessed_path: str,
    feed_title: str,
    *,
    post_guid: str | None = None,
    taken_paths: AbstractSet[str] = frozenset(),
) -> ProcessingPaths:
    unprocessed_filename = Path(unprocessed_path).name
    # Sanitize feed_title to prevent illegal characters in paths
    # Keep spaces, alphanumeric. Remove others.
    sanitized_feed_title = re.sub(r"[^a-zA-Z0-9\s_.-]", "", feed_title).strip()
    # Remove any trailing dots that might result from sanitization
    sanitized_feed_title = sanitized_feed_title.rstrip(".")
    # Replace spaces with underscores for friendlier directory names
    sanitized_feed_title = re.sub(r"\s+", "_", sanitized_feed_title)

    candidate_path = get_srv_root() / sanitized_feed_title / unprocessed_filename

    return ProcessingPaths(
        post_processed_audio_path=disambiguate_processed_path(
            candidate_path, post_guid=post_guid, taken_paths=taken_paths
        ),
    )


def get_job_unprocessed_path(post_guid: str, job_id: str, post_title: str) -> Path:
    """Return a unique per-job path for the unprocessed audio file.

    Layout: in/jobs/{post_guid}/{job_id}/{sanitized_title}.mp3
    """
    # Keep same sanitization behavior used for download filenames
    sanitized_title = re.sub(r"[^a-zA-Z0-9\s]", "", post_title).strip()
    return get_in_root() / "jobs" / post_guid / job_id / f"{sanitized_title}.mp3"


# ---- New centralized data-root helpers ----


def get_instance_dir() -> Path:
    """Absolute instance directory inside the container.

    Defaults to /app/src/instance. Can be overridden via PODLY_INSTANCE_DIR for tests.
    """
    return Path(os.environ.get("PODLY_INSTANCE_DIR", "/app/src/instance"))


def get_base_podcast_data_dir() -> Path:
    """Root under which podcasts (in/srv) live, e.g., /app/src/instance/data."""
    return Path(
        os.environ.get("PODLY_PODCAST_DATA_DIR", str(get_instance_dir() / "data"))
    )


def get_in_root() -> Path:
    return get_base_podcast_data_dir() / "in"


def get_srv_root() -> Path:
    return get_base_podcast_data_dir() / "srv"
