from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional, Set

import requests
import validators

from shared.interfaces import Post
from shared.processing_paths import get_in_root

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = str(get_in_root())

# A single dropped connection or DNS blip otherwise strands a post forever:
# nothing re-queues a job once it has failed once (see JobsManager), so the
# episode silently never reaches the feed. Retry transient network errors
# here rather than relying on an outer layer to notice and resubmit.
DOWNLOAD_MAX_ATTEMPTS = 4
DOWNLOAD_RETRY_BACKOFF_SECONDS = 5
RETRYABLE_DOWNLOAD_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class DownloadError(Exception):
    """Raised when a podcast episode can't be downloaded (e.g. missing or
    invalid download URL). This runs inside a background worker thread, not a
    Flask request context, so it must not use flask.abort() -- the generic
    exception handler in PodcastProcessor.process() catches this and marks
    the job failed with a clear message."""


class PodcastDownloader:
    """
    Handles downloading podcast episodes with robust file checking and path management.
    """

    def __init__(
        self, download_dir: str = DOWNLOAD_DIR, logger: Optional[logging.Logger] = None
    ):
        self.download_dir = download_dir
        self.logger = logger or logging.getLogger(__name__)

    def download_episode(self, post: Post, dest_path: str) -> Optional[str]:
        """
        Download a podcast episode if it doesn't already exist.

        Args:
            post: The Post object containing the podcast episode to download

        Returns:
            Path to the downloaded file, or None if download failed
        """
        # Destination is required; ensure parent directory exists
        download_path = dest_path
        Path(download_path).parent.mkdir(parents=True, exist_ok=True)
        if not download_path:
            self.logger.error(f"Invalid download path for post {post.id}")
            return None

        # First, check if the file truly exists and has nonzero size.
        try:
            if os.path.isfile(download_path) and os.path.getsize(download_path) > 0:
                self.logger.info("Episode already downloaded.")
                return download_path
            self.logger.info("File is zero bytes, re-downloading.")  # else

        except FileNotFoundError:
            # Covers both "file actually missing" and "broken symlink"
            pass

        # If we get here, the file is missing or zero bytes -> perform download
        audio_link = post.download_url
        if audio_link is None or not validators.url(audio_link):
            raise DownloadError(f"Invalid or missing download URL for post {post.id}")

        self.logger.info(f"Downloading {audio_link} into {download_path}...")
        referer = "https://open.acast.com/" if "acast.com" in audio_link else None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": referer,
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                with requests.get(
                    audio_link, stream=True, timeout=60, headers=headers
                ) as response:
                    if response.status_code == 200:
                        with open(download_path, "wb") as file:
                            for chunk in response.iter_content(chunk_size=8192):
                                file.write(chunk)
                        self.logger.info("Download complete.")
                        return download_path

                    self.logger.info(
                        f"Failed to download the podcast episode, response: {response.status_code}"
                    )
                    return None
            except RETRYABLE_DOWNLOAD_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= DOWNLOAD_MAX_ATTEMPTS:
                    break
                wait_seconds = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
                self.logger.warning(
                    "Transient network error downloading %s (attempt %d/%d): %s. "
                    "Retrying in %ds.",
                    audio_link,
                    attempt,
                    DOWNLOAD_MAX_ATTEMPTS,
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        raise DownloadError(
            f"Failed to download episode for post {post.id} after "
            f"{DOWNLOAD_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def get_and_make_download_path(self, post_title: str) -> Path:
        """
        Generate the download path for a post and create necessary directories.

        Args:
            post_title: The title of the post to generate a path for

        Returns:
            Path object for the download location
        """
        sanitized_title = sanitize_title(post_title)

        post_directory = sanitized_title
        post_filename = sanitized_title + ".mp3"

        post_directory_path = Path(self.download_dir) / post_directory

        post_directory_path.mkdir(parents=True, exist_ok=True)

        return post_directory_path / post_filename


_MAX_SANITIZED_TITLE_LENGTH = 150


def sanitize_title(title: str) -> str:
    """Sanitize a title for use in file paths.

    Falls back to a stable hash of the original title when sanitization would
    otherwise produce an empty/whitespace-only string (e.g. an all-emoji or
    all-punctuation RSS title), and truncates to a safe max length so
    extremely long titles can't blow past filesystem path limits.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9\s]", "", title).strip()
    if not sanitized:
        digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
        sanitized = f"untitled_{digest}"
    return sanitized[:_MAX_SANITIZED_TITLE_LENGTH]


def find_audio_link(entry: Any) -> str:
    """Find the audio link in a feed entry."""
    audio_mime_types: Set[str] = {
        "audio/mpeg",
        "audio/mp3",
        "audio/x-mp3",
        "audio/mpeg3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/aac",
        "audio/wav",
        "audio/x-wav",
        "audio/ogg",
        "audio/opus",
        "audio/flac",
    }

    for url in _iter_enclosure_audio_urls(entry, audio_mime_types):
        return url
    for url in _iter_link_audio_urls(entry, audio_mime_types, match_any_audio=False):
        return url
    for url in _iter_link_audio_urls(entry, audio_mime_types, match_any_audio=True):
        return url

    return str(getattr(entry, "id", ""))


def _iter_enclosure_audio_urls(entry: Any, audio_mime_types: Set[str]) -> Iterator[str]:
    enclosures = getattr(entry, "enclosures", None) or []
    for enclosure in enclosures:
        enc_type = (getattr(enclosure, "type", "") or "").lower()
        if enc_type not in audio_mime_types:
            continue
        href = getattr(enclosure, "href", None)
        if href:
            yield str(href)
        url = getattr(enclosure, "url", None)
        if url:
            yield str(url)


def _iter_link_audio_urls(
    entry: Any,
    audio_mime_types: Set[str],
    *,
    match_any_audio: bool,
) -> Iterator[str]:
    links = getattr(entry, "links", None) or []
    for link in links:
        link_type = (getattr(link, "type", "") or "").lower()
        if match_any_audio:
            if not link_type.startswith("audio/"):
                continue
        else:
            if link_type not in audio_mime_types:
                continue

        href = getattr(link, "href", None)
        if href:
            yield str(href)


# Backward compatibility - create a default instance
_default_downloader = PodcastDownloader()


def download_episode(post: Post, dest_path: str) -> Optional[str]:
    return _default_downloader.download_episode(post, dest_path)


def get_and_make_download_path(post_title: str) -> Path:
    return _default_downloader.get_and_make_download_path(post_title)
