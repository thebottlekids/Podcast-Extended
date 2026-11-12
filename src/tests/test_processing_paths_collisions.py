"""Tests for the ownership-based title-collision fix (change set B, helper layer).

Two posts that share a title derive the same processed filename
(``srv/<Feed>/<Title>.mp3``). These tests pin the disambiguation contract in
``shared.processing_paths``: ownership, not existence, decides the suffix, the
legacy single-post path never changes, and the suffix is ``_<guid8>`` before the
extension.
"""

from pathlib import Path

import pytest

from shared.processing_paths import (
    ProcessingPaths,
    disambiguate_processed_path,
    get_srv_root,
    paths_from_unprocessed_path,
    post_guid_suffix,
)

GUID_FIRST = "28a011cd-0000-4000-8000-aaaaaaaaaaaa"
GUID_SECOND = "77ddccbb-0000-4000-8000-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def _data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PODLY_PODCAST_DATA_DIR", str(tmp_path / "data"))


def _canonical() -> Path:
    return get_srv_root() / "Part_Of_The_Problem" / "Scott Horton.mp3"


def test_legacy_single_post_path_is_unchanged() -> None:
    """No other owner -> byte-identical legacy path (no silent migration)."""
    paths = paths_from_unprocessed_path(
        "/app/src/instance/data/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_FIRST,
    )

    assert paths == ProcessingPaths(post_processed_audio_path=_canonical())


def test_same_title_posts_get_distinct_paths() -> None:
    first = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3", "Part Of The Problem", post_guid=GUID_FIRST
    )
    second = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=frozenset({str(first.post_processed_audio_path)}),
    )

    assert first.post_processed_audio_path == _canonical()
    assert second.post_processed_audio_path == (
        get_srv_root() / "Part_Of_The_Problem" / "Scott Horton_77ddccbb.mp3"
    )
    assert first.post_processed_audio_path != second.post_processed_audio_path


def test_suffix_uses_guid_without_dashes() -> None:
    second = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=frozenset({str(_canonical())}),
    )

    assert post_guid_suffix(GUID_SECOND) == "77ddccbb"
    assert second.post_processed_audio_path.name == "Scott Horton_77ddccbb.mp3"


def test_taken_path_matches_through_resolved_form() -> None:
    """Stored paths were written by different eras; compare resolved forms."""
    odd_form = str(_canonical().parent) + "/./" + _canonical().name

    second = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=frozenset({odd_form}),
    )

    assert second.post_processed_audio_path.name == "Scott Horton_77ddccbb.mp3"


def test_path_owned_by_sibling_is_not_a_collision_for_its_owner() -> None:
    """A post's own path is never in its taken_paths set."""
    first = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_FIRST,
        taken_paths=frozenset(
            {str(get_srv_root() / "Part_Of_The_Problem" / "Scott Horton_77ddccbb.mp3")}
        ),
    )

    assert first.post_processed_audio_path == _canonical()


def test_no_guid_means_no_suffix() -> None:
    """Legacy callers/tests without a guid keep the old behaviour."""
    paths = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        taken_paths=frozenset({str(_canonical())}),
    )

    assert paths.post_processed_audio_path == _canonical()


def test_empty_taken_paths_means_no_suffix() -> None:
    paths = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=frozenset(),
    )

    assert paths.post_processed_audio_path == _canonical()


def test_suffix_only_touches_the_basename() -> None:
    nested = get_srv_root() / "Feed" / "Title.mp3"

    result = disambiguate_processed_path(
        nested,
        post_guid=GUID_SECOND,
        taken_paths=frozenset({str(nested)}),
    )

    assert result.parent == nested.parent
    assert result.name == "Title_77ddccbb.mp3"
    assert result.suffix == ".mp3"


def test_non_mp3_extension_is_preserved() -> None:
    candidate = get_srv_root() / "Feed" / "Title.m4a"

    result = disambiguate_processed_path(
        candidate,
        post_guid=GUID_SECOND,
        taken_paths=frozenset({str(candidate)}),
    )

    assert result.name == "Title_77ddccbb.m4a"


def test_single_post_disambiguation_is_stable_across_calls() -> None:
    """Re-deriving must not keep changing the filename."""
    taken = frozenset({str(_canonical())})
    first = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=taken,
    )
    again = paths_from_unprocessed_path(
        "/in/Scott Horton.mp3",
        "Part Of The Problem",
        post_guid=GUID_SECOND,
        taken_paths=taken,
    )

    assert first == again
