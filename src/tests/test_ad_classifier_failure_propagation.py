"""
Tests that AdClassifier.classify() reports failure/incompleteness via its
return value instead of silently swallowing it.

Regression coverage for a real production bug: classification failures were
logged and discarded, so PodcastProcessor proceeded straight to cutting audio
with zero (or partial) ad identifications and the episode shipped completely
unedited with no error surfaced anywhere.
"""

from typing import Any, Generator, List, Tuple
from unittest.mock import MagicMock

import pytest
from flask import Flask
from jinja2 import Template

from app.extensions import db
from app.models import Post, TranscriptSegment
from podcast_processor.ad_classifier import AdClassifier, ClassifyException
from shared.config import Config
from shared.test_utils import create_standard_test_config


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


@pytest.fixture
def test_config() -> Config:
    return create_standard_test_config()


def _make_classifier(test_config: Config) -> AdClassifier:
    """AdClassifier with a mocked db_session returning no existing identifications
    and boundary refinement disabled, so classify()'s control flow can be
    exercised without a real LLM/DB round trip."""
    mock_db_session = MagicMock()
    mock_db_session.query.return_value.join.return_value.filter.return_value.all.return_value = (
        []
    )
    classifier = AdClassifier(config=test_config, db_session=mock_db_session)
    classifier.boundary_refiner = None
    return classifier


def _make_post() -> Post:
    # AdClassifier.classify() is beartype-checked at runtime, so a MagicMock
    # won't satisfy the `post: Post` type hint -- use a real (unpersisted)
    # instance instead.
    return Post(id=1, feed_id=1, guid="test-guid", download_url="http://x", title="t")


def _make_segments(n: int) -> List[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=i,
            post_id=1,
            sequence_num=i,
            start_time=float(i),
            end_time=float(i + 1),
            text=f"segment {i}",
        )
        for i in range(n)
    ]


def test_classify_returns_true_on_full_completion(
    test_config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = _make_classifier(test_config)
        segments = _make_segments(5)

        def fake_step(
            _params: Any,
            _prev_overlap: Any,
            current_index: int,
            _all_segments: Any,
        ) -> Tuple[int, List[Any]]:
            return len(segments) - current_index, []

        classifier._step = fake_step  # type: ignore[method-assign]

        result = classifier.classify(
            transcript_segments=segments,
            system_prompt="sys",
            user_prompt_template=Template("{{ x }}"),
            post=_make_post(),
        )

        assert result is True


def test_classify_returns_false_when_step_raises(
    test_config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = _make_classifier(test_config)
        segments = _make_segments(5)

        def fake_step(*_args: Any, **_kwargs: Any) -> Tuple[int, List[Any]]:
            raise ClassifyException("no progress possible")

        classifier._step = fake_step  # type: ignore[method-assign]

        result = classifier.classify(
            transcript_segments=segments,
            system_prompt="sys",
            user_prompt_template=Template("{{ x }}"),
            post=_make_post(),
        )

        assert result is False


def test_classify_returns_false_when_no_progress_made(
    test_config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = _make_classifier(test_config)
        segments = _make_segments(5)

        def fake_step(
            _params: Any,
            _prev_overlap: Any,
            _current_index: int,
            _all_segments: Any,
        ) -> Tuple[int, List[Any]]:
            # Simulate a step that makes zero progress -- classify() should
            # treat this as an incomplete run rather than reporting success.
            return 0, []

        classifier._step = fake_step  # type: ignore[method-assign]

        result = classifier.classify(
            transcript_segments=segments,
            system_prompt="sys",
            user_prompt_template=Template("{{ x }}"),
            post=_make_post(),
        )

        assert result is False


def test_classify_returns_true_for_empty_transcript(
    test_config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = _make_classifier(test_config)

        result = classifier.classify(
            transcript_segments=[],
            system_prompt="sys",
            user_prompt_template=Template("{{ x }}"),
            post=_make_post(),
        )

        assert result is True
