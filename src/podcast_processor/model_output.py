import json
import logging
from typing import List, Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AdSegmentPrediction(BaseModel):
    segment_offset: float
    confidence: float


class AdSegmentPredictionList(BaseModel):
    ad_segments: List[AdSegmentPrediction]
    content_type: Optional[
        Literal[
            "technical_discussion",
            "educational/self_promo",
            "promotional_external",
            "transition",
        ]
    ] = None
    confidence: Optional[float] = None


def _close_missing_brackets(text: str) -> str:
    """Append whatever closing brackets/braces the counts say are missing.

    Closes innermost-first: the ad_segments array, then the outer object.
    """
    open_braces = text.count("{")
    close_braces = text.count("}")
    open_brackets = text.count("[")
    close_brackets = text.count("]")

    missing_brackets = open_brackets - close_brackets
    missing_braces = open_braces - close_braces

    if missing_brackets > 0:
        text += "]" * missing_brackets
    if missing_braces > 0:
        text += "}" * missing_braces

    return text


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except Exception:  # pylint: disable=broad-except
        return False


def _attempt_json_repair(json_str: str) -> str:
    """
    Attempt to repair truncated JSON by adding missing closing brackets, and
    only if that alone doesn't yield valid JSON, dropping an incomplete
    trailing element first.

    This handles cases where the LLM response was cut off mid-JSON. Two
    shapes show up in practice:

    1. Every field present is already complete and only the closing
       brackets/braces themselves were cut off, e.g.
       '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92}'
       Here we must NOT discard anything -- trailing fields like
       content_type/confidence may be complete and worth keeping.

    2. The trailing element itself is incomplete -- cut off mid-key,
       mid-string, or (common for this schema, since both segment fields are
       bare numbers) mid-number with no closing quote to anchor a trim on,
       e.g. '..."confidence":0.92},{"segment_offset":15.0,"conf'. Naively
       closing brackets here still leaves invalid JSON, so we drop back to
       the last element the model finished emitting and close out from
       there.
    """
    # Count opening and closing brackets/braces
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    # If brackets are balanced, no repair needed
    if open_braces == close_braces and open_brackets == close_brackets:
        return json_str

    logger.warning(
        f"Detected unbalanced JSON: {open_braces} '{{' vs {close_braces} '}}', "
        f"{open_brackets} '[' vs {close_brackets} ']'. Attempting repair."
    )

    repaired = json_str.rstrip().rstrip(",")

    # Strategy 1: assume only the closing brackets/braces were cut off.
    closed = _close_missing_brackets(repaired)
    if _is_valid_json(closed):
        logger.info("Repaired JSON by closing missing brackets/braces")
        return closed

    # Strategy 2: the trailing element is genuinely incomplete. Truncate to
    # the last fully-closed object and discard whatever partial element
    # trails it.
    last_complete_object_end = repaired.rfind("}")
    if last_complete_object_end != -1:
        dropped = repaired[last_complete_object_end + 1 :]
        repaired = repaired[: last_complete_object_end + 1]
        if dropped.strip():
            logger.debug(f"Dropped incomplete trailing element: {dropped[:200]!r}")

    repaired = _close_missing_brackets(repaired)
    logger.info(
        "Repaired JSON by truncating to the last complete element and "
        "closing remaining brackets/braces"
    )

    return repaired


def clean_and_parse_model_output(model_output: str) -> AdSegmentPredictionList:
    start_marker, end_marker = "{", "}"

    assert (
        model_output.count(start_marker) >= 1
    ), f"No opening brace found in: {model_output[:200]}"

    start_idx = model_output.index(start_marker)
    model_output = model_output[start_idx:]

    # If we have at least as many closing braces as opening braces, trim to the last
    # closing brace to drop any trailing non-JSON content. Otherwise, keep the
    # content as-is so we can attempt repair on truncated JSON.
    open_braces = model_output.count(start_marker)
    close_braces = model_output.count(end_marker)
    if close_braces >= open_braces and close_braces > 0:
        model_output = model_output[: 1 + model_output.rindex(end_marker)]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    # First attempt: try to parse as-is
    try:
        return AdSegmentPredictionList.parse_raw(model_output)
    except Exception as first_error:
        logger.debug(f"Initial parse failed: {first_error}")

        # Second attempt: try to repair truncated JSON
        try:
            repaired_output = _attempt_json_repair(model_output)
            result = AdSegmentPredictionList.parse_raw(repaired_output)
            logger.info("Successfully parsed model output after JSON repair")
            return result
        except Exception as repair_error:
            logger.error(
                f"JSON repair also failed. Original output (first 500 chars): {model_output[:500]}"
            )
            # Re-raise the original error with more context
            raise first_error from repair_error
