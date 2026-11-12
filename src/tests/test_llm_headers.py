"""Tests for provider-specific LLM headers (change set A).

Covers the helper itself and every litellm call site that must attach the
OpenCode Go session header: the ad classifier, both boundary refiners, and the
``POST /api/config/test-llm`` probe.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from litellm.types.utils import Choices

from app.extensions import db
from app.models import ModelCall
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.boundary_refiner import BoundaryRefiner
from podcast_processor.word_boundary_refiner import WordBoundaryRefiner
from shared.config import Config
from shared.llm_headers import (
    LLM_USER_AGENT,
    OPENCODE_SESSION_HEADER,
    is_opencode_base_url,
    llm_extra_headers,
    opencode_session_id,
)
from shared.test_utils import create_standard_test_config

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
LOCAL_OLLAMA_BASE_URL = "http://192.168.1.242:11434/v1"


def _config(base_url: str | None) -> Config:
    return create_standard_test_config().model_copy(
        update={"openai_base_url": base_url}
    )


def _mock_response(content: str = "not-json") -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock(spec=Choices)
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _segments() -> List[Dict[str, Any]]:
    return [
        {"sequence_num": 0, "start_time": 0.0, "end_time": 5.0, "text": "hello"},
        {"sequence_num": 1, "start_time": 5.0, "end_time": 10.0, "text": "world"},
    ]


class TestLlmExtraHeaders:
    def test_no_base_url_means_no_headers(self) -> None:
        assert llm_extra_headers(None) == {}
        assert llm_extra_headers("") == {}
        assert llm_extra_headers("   ") == {}

    @pytest.mark.parametrize(
        "base_url",
        [
            LOCAL_OLLAMA_BASE_URL,
            "https://api.openai.com/v1",
            "https://opencode.ai.example.com/v1",
            "https://notopencode.ai/v1",
            "https://opencode.ai.attacker.test/v1",
        ],
    )
    def test_non_opencode_lanes_get_no_headers(self, base_url: str) -> None:
        assert llm_extra_headers(base_url) == {}
        assert is_opencode_base_url(base_url) is False

    @pytest.mark.parametrize(
        "base_url",
        [
            OPENCODE_BASE_URL,
            "https://opencode.ai/zen/go/v1/",
            "opencode.ai/zen/go/v1",
            "http://OPENCODE.AI/zen/go/v1",
            "https://zen.opencode.ai/v1",
        ],
    )
    def test_opencode_lane_gets_session_and_user_agent(self, base_url: str) -> None:
        headers = llm_extra_headers(base_url)
        assert headers[OPENCODE_SESSION_HEADER] == opencode_session_id()
        assert headers["User-Agent"] == LLM_USER_AGENT
        assert set(headers) == {OPENCODE_SESSION_HEADER, "User-Agent"}
        assert is_opencode_base_url(base_url) is True

    def test_session_id_is_stable_and_well_formed(self) -> None:
        session_id = opencode_session_id()
        assert session_id == opencode_session_id()
        assert (
            session_id == llm_extra_headers(OPENCODE_BASE_URL)[OPENCODE_SESSION_HEADER]
        )
        assert session_id.startswith("podly-")
        suffix = session_id[len("podly-") :]
        assert len(suffix) == 16
        assert all(char in "0123456789abcdef" for char in suffix)


def test_ad_classifier_attaches_headers(app: Flask) -> None:
    with app.app_context():
        classifier = AdClassifier(
            config=_config(OPENCODE_BASE_URL), db_session=db.session
        )
        model_call = ModelCall(
            post_id=0,
            model_name="openai/glm-5.3-flash",
            prompt="test prompt",
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            status="pending",
        )
        db.session.add(model_call)
        db.session.commit()

        with patch("litellm.completion", return_value=_mock_response("{}")) as mocked:
            classifier._call_model(
                model_call_obj=model_call, system_prompt="test system prompt"
            )

        headers = mocked.call_args.kwargs["headers"]
        assert headers[OPENCODE_SESSION_HEADER] == opencode_session_id()


def test_ad_classifier_sends_empty_headers_for_local_lane(app: Flask) -> None:
    with app.app_context():
        classifier = AdClassifier(
            config=_config(LOCAL_OLLAMA_BASE_URL), db_session=db.session
        )
        model_call = ModelCall(
            post_id=0,
            model_name="openai/glm-5.3-flash:cloud",
            prompt="test prompt",
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            status="pending",
        )
        db.session.add(model_call)
        db.session.commit()

        with patch("litellm.completion", return_value=_mock_response("{}")) as mocked:
            classifier._call_model(
                model_call_obj=model_call, system_prompt="test system prompt"
            )

        assert mocked.call_args.kwargs["headers"] == {}


@pytest.mark.parametrize(
    "base_url,expect_header",
    [(OPENCODE_BASE_URL, True), (LOCAL_OLLAMA_BASE_URL, False)],
)
def test_boundary_refiner_attaches_headers_per_lane(
    base_url: str, expect_header: bool
) -> None:
    refiner = BoundaryRefiner(config=_config(base_url))
    with patch("litellm.completion", return_value=_mock_response()) as mocked:
        refiner.refine(
            ad_start=0.0,
            ad_end=5.0,
            confidence=0.9,
            all_segments=_segments(),
        )

    headers = mocked.call_args.kwargs["headers"]
    if expect_header:
        assert headers[OPENCODE_SESSION_HEADER] == opencode_session_id()
        assert headers["User-Agent"] == LLM_USER_AGENT
    else:
        assert headers == {}


@pytest.mark.parametrize(
    "base_url,expect_header",
    [(OPENCODE_BASE_URL, True), (LOCAL_OLLAMA_BASE_URL, False)],
)
def test_word_boundary_refiner_attaches_headers_per_lane(
    base_url: str, expect_header: bool
) -> None:
    refiner = WordBoundaryRefiner(config=_config(base_url))
    with patch("litellm.completion", return_value=_mock_response()) as mocked:
        refiner.refine(
            ad_start=0.0,
            ad_end=5.0,
            confidence=0.9,
            all_segments=_segments(),
        )

    headers = mocked.call_args.kwargs["headers"]
    if expect_header:
        assert headers[OPENCODE_SESSION_HEADER] == opencode_session_id()
        assert headers["User-Agent"] == LLM_USER_AGENT
    else:
        assert headers == {}


@pytest.mark.parametrize(
    "base_url,expect_header",
    [(OPENCODE_BASE_URL, True), (LOCAL_OLLAMA_BASE_URL, False)],
)
def test_config_test_llm_route_attaches_headers_per_lane(
    base_url: str, expect_header: bool
) -> None:
    from app.routes import config_routes

    app = Flask(__name__)
    app.register_blueprint(config_routes.config_bp)
    client = app.test_client()

    original_api_base = getattr(config_routes.litellm, "api_base", None)
    original_api_key = getattr(config_routes.litellm, "api_key", None)
    try:
        with patch.object(
            config_routes.litellm, "completion", return_value=MagicMock()
        ) as mocked:
            response = client.post(
                "/api/config/test-llm",
                json={
                    "llm": {
                        "llm_api_key": "test-key",
                        "llm_model": "openai/glm-5.3-flash",
                        "openai_base_url": base_url,
                    }
                },
            )
    finally:
        config_routes.litellm.api_base = original_api_base
        config_routes.litellm.api_key = original_api_key

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    headers = mocked.call_args.kwargs["headers"]
    if expect_header:
        assert headers[OPENCODE_SESSION_HEADER] == opencode_session_id()
    else:
        assert headers == {}
