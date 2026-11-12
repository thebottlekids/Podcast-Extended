import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

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


def _extract_json_objects(text: str) -> List[str]:
    """Return every complete top-level JSON object in ``text``, in order.

    Handles the concatenated-objects failure shape seen in production
    (2026-10-03): the model emits two JSON objects back-to-back, e.g.
    '{"ad_segments":[]}{"ad_segments":[]}'. Plain json.loads rejects the
    pair ("Extra data"); the truncation repair then trims to the LAST
    brace, giving '}{"ad_segments":[]}' -- also invalid.

    Brace scanning is string-aware: braces inside string values are
    structural-noise and never counted.
    """
    objects: List[str] = []
    depth = 0
    in_string = False
    escaped = False
    start_idx = None
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    objects.append(text[start_idx : i + 1])
                    start_idx = None
    return objects


def _dedupe_duplicate_keys_first_wins(object_text: str) -> Optional[str]:
    """Collapse duplicate JSON keys, keeping the FIRST occurrence.

    Production shape (2026-10-03, ModelCall 28273): the model wrote
    'adSegments' AND 'ad_segments' (and 'ads') inside one object, plus a
    concatenated duplicate object. After camelCase normalization this
    leaves duplicate 'ad_segments' keys; Python's json.loads silently
    keeps the LAST, which can drop the key that carried the actual
    predictions. First-occurrence-wins preserves whichever spelling the
    model populated first.

    Must inspect RAW key/value pairs -- a plain json.loads would collapse
    duplicates (last-wins) before this function ever sees them.
    """

    def _first_wins(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        deduped_pairs: Dict[str, Any] = {}
        for key, value in pairs:
            if key not in deduped_pairs:
                deduped_pairs[key] = value
        return deduped_pairs

    decoder = json.JSONDecoder(object_pairs_hook=_first_wins)
    try:
        obj, _ = decoder.raw_decode(object_text)
    except Exception:  # pylint: disable=broad-except
        return None
    if not isinstance(obj, dict):
        return None
    # Compare against a last-wins decode to detect whether any duplicate
    # keys existed at all; if not, keep the original text untouched.
    try:
        plain, _ = json.JSONDecoder().raw_decode(object_text)
    except Exception:  # pylint: disable=broad-except
        return None
    if plain == obj:
        return None  # nothing duplicated; keep the original text
    return json.dumps(obj)


def _normalize_json_keys(text: str) -> str:
    """Rename camelCase top-level keys to the schema's snake_case names.

    Production shape (2026-10-03): 'adSegments' instead of 'ad_segments'.
    Field names inside ad_segments items (segment_offset / confidence) are
    single words and unaffected.
    """
    return re.sub(r'"adSegments"', '"ad_segments"', text)


def _fix_swapped_brackets(text: str) -> Optional[str]:
    """Try to correct paren/bracket confusion outside string values.

    Production shape (2026-10-03, ModelCall 27441): '{"ad_segments":[])' --
    a stray ')' after a correctly-closed array. Returns the repaired text
    when one of the attempts yields valid JSON, else None. Braces are never
    rewritten (only parens/brackets are confused in practice), and string
    values are untouched.

    Attempts, in order (each followed by closing any brackets left open):
    1. delete stray parens (spurious closers -- the observed shape);
    2. map parens to brackets (wrong-type closers).
    """
    if "(" not in text and ")" not in text:
        return None
    candidates = [
        _string_aware_map(text, {"(": None, ")": None}),
        _string_aware_map(text, {"(": "[", ")": "]"}),
    ]
    for candidate in candidates:
        fixed = _close_missing_brackets(candidate)
        if _is_valid_json(fixed):
            return fixed
    return None


def _string_aware_map(text: str, mapping: Dict[str, Optional[str]]) -> str:
    """Apply a character mapping outside string literals only."""
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch in mapping:
            replacement = mapping[ch]
            if replacement is not None:
                out.append(replacement)
        else:
            out.append(ch)
    return "".join(out)


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


def clean_and_parse_model_output(  # pylint: disable=too-many-branches,too-many-statements
    model_output: str,
) -> AdSegmentPredictionList:
    """Parse an LLM response into an :class:`AdSegmentPredictionList`.

    Tolerates the response malformations observed in production
    (2026-10-03): concatenated duplicate objects, camelCase keys,
    duplicated object keys with conflicting values, stray parens where a
    bracket belongs, and mid-JSON truncation. Unrecoverable output raises.
    """
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

    # Normalize camelCase keys the model sometimes emits despite the
    # prompt contract ("adSegments" instead of "ad_segments").
    model_output = _normalize_json_keys(model_output)

    # A response containing duplicated keys (e.g. the model wrote both
    # 'adSegments' and 'ad_segments') parses "successfully" but Python's
    # json silently keeps the LAST duplicate -- which can drop the key
    # carrying the actual predictions. So build interpretations instead of
    # trusting the single as-is parse: last-wins (ordinary json.loads
    # semantics) and first-wins (keeps whichever spelling was populated
    # first). When several interpretations parse, the one with the most
    # predictions wins; ties keep the earliest (prompt-contract) reading.
    candidate_texts: List[str] = []
    first_wins = _dedupe_duplicate_keys_first_wins(model_output)
    if first_wins is not None:
        candidate_texts.append(first_wins)
    candidate_texts.append(model_output)

    parsed: List[AdSegmentPredictionList] = []
    for candidate in candidate_texts:
        try:
            parsed.append(AdSegmentPredictionList.parse_raw(candidate))
        except Exception as candidate_error:
            logger.debug(f"Candidate parse failed: {candidate_error}")

    if parsed:
        best = max(parsed, key=lambda r: len(r.ad_segments))
        if len(parsed) > 1 and best is parsed[0]:
            logger.info(
                "Duplicate-key response parsed multiple ways; kept the "
                "first-occurrence interpretation"
            )
        elif len(parsed) > 1:
            logger.info(
                "Duplicate-key response parsed multiple ways; kept the "
                "last-occurrence interpretation"
            )
        if len(best.ad_segments) == 0 and best is not parsed[-1]:
            # Both interpretations parsed; keep best anyway (already chosen
            # by max). No-op branch kept for clarity of the tie-break rule.
            pass
        return best

    first_error: Exception
    try:
        AdSegmentPredictionList.parse_raw(model_output)
        raise AssertionError("unreachable: a parse that succeeded above failed here")
    except Exception as err:
        first_error = err
    logger.debug(f"Initial parse failed: {first_error}")

    # Repair attempt A: concatenated JSON objects -- the model repeated
    # its answer. Plain repair cannot fix this shape because trimming to
    # the last brace keeps the pair boundary ('}{'), which is invalid.
    # Collapse duplicate keys (first occurrence wins) inside each
    # object, then take the first object that parses.
    objects = _extract_json_objects(model_output)
    if len(objects) > 1:
        best_concat: Optional[AdSegmentPredictionList] = None
        for obj in objects:
            candidates = [obj]
            deduped = _dedupe_duplicate_keys_first_wins(obj)
            if deduped is not None:
                candidates.insert(0, deduped)
            for candidate in candidates:
                try:
                    result = AdSegmentPredictionList.parse_raw(candidate)
                except Exception:
                    continue
                if best_concat is None or len(result.ad_segments) > len(
                    best_concat.ad_segments
                ):
                    best_concat = result
        if best_concat is not None:
            logger.info(
                "Parsed model output after extracting objects from a "
                "concatenated response (duplicate-object shape)"
            )
            return best_concat

    # Repair attempt B: swapped bracket types (paren where bracket belongs).
    swapped = _fix_swapped_brackets(model_output)
    if swapped is not None:
        try:
            result = AdSegmentPredictionList.parse_raw(swapped)
            logger.info("Parsed model output after correcting swapped brackets")
            return result
        except Exception as swap_error:
            logger.debug(f"Bracket-swap repair parse failed: {swap_error}")

    # Legacy repair path: truncated JSON.
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
