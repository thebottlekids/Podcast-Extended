import pytest
from pydantic import ValidationError

from podcast_processor.model_output import (
    AdSegmentPrediction,
    AdSegmentPredictionList,
    clean_and_parse_model_output,
)


def test_clean_parse_output() -> None:
    model_outupt = """
extra stuff bla bla
{"ad_segments": [{"segment_offset": 123.45, "confidence": 0.7}]}. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(
                segment_offset=123.45,
                confidence=0.7,
            )
        ]
    )


def test_parse_multiple_segments_output() -> None:
    model_outupt = """
{"ad_segments": [
    {"segment_offset": 123.45, "confidence": 0.7},
    {"segment_offset": 23.45, "confidence": 0.8},
    {"segment_offset": 45.67, "confidence": 0.9}
]
}"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=123.45, confidence=0.7),
            AdSegmentPrediction(segment_offset=23.45, confidence=0.8),
            AdSegmentPrediction(segment_offset=45.67, confidence=0.9),
        ]
    )


def test_clean_parse_output_malformed() -> None:
    model_outupt = """
{"ad_segments": uhoh1.7, 1114.8, 1116.4, 1118.2, 1119.5, 1121.0, 1123.2, 1125.2], "confidence": 0.7}. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    with pytest.raises(ValidationError):
        clean_and_parse_model_output(model_outupt)


def test_clean_parse_output_with_content_type() -> None:
    model_output = """
{"ad_segments": [{"segment_offset": 12.0, "confidence": 0.86}], "content_type": "promotional_external", "confidence": 0.91}
"""

    assert clean_and_parse_model_output(model_output) == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=12.0, confidence=0.86)],
        content_type="promotional_external",
        confidence=0.91,
    )


def test_clean_parse_output_truncated_missing_closing_brackets() -> None:
    """Test parsing truncated JSON missing closing ]} at the end."""
    model_output = '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=10.5, confidence=0.92)]
    )


def test_clean_parse_output_truncated_multiple_segments() -> None:
    """Test parsing truncated JSON with multiple complete segments but missing closing."""
    model_output = '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92},{"segment_offset":25.0,"confidence":0.85}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=10.5, confidence=0.92),
            AdSegmentPrediction(segment_offset=25.0, confidence=0.85),
        ]
    )


def test_clean_parse_output_truncated_with_content_type() -> None:
    """Test parsing truncated JSON that includes content_type but is missing final }."""
    model_output = '{"ad_segments":[{"segment_offset":12.0,"confidence":0.86}],"content_type":"promotional_external","confidence":0.92'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=12.0, confidence=0.86)],
        content_type="promotional_external",
        confidence=0.92,
    )


def test_clean_parse_output_concatenated_objects() -> None:
    """Duplicate-object shape seen 2026-10-03 (ModelCall 27122): the model
    emitted the same JSON object twice back-to-back; json.loads rejects the
    pair with "Extra data"."""
    model_output = '{"ad_segments":[]}\n\n{"ad_segments":[]}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(ad_segments=[])


def test_clean_parse_output_swapped_bracket() -> None:
    """Stray-paren shape seen 2026-10-03 (ModelCall 27441): a ')' after an
    already-closed array."""
    model_output = '{"ad_segments":[])'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(ad_segments=[])


def test_clean_parse_output_camel_case_and_duplicate_keys() -> None:
    """Mixed-key shape seen 2026-10-03 (ModelCall 28273): the model wrote
    'adSegments', 'ad_segments' and 'ads' in one object, then repeated a
    bare object. camelCase is normalized; duplicate keys resolve first-wins.
    """
    model_output = '{"adSegments":[],"ad_segments":[],"ads":[]}\n\n{"ad_segments":[]}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(ad_segments=[])


def test_clean_parse_output_camel_case_with_data_keeps_first() -> None:
    """When duplicate keys conflict, the FIRST occurrence must win: a
    response with data in 'adSegments' but an empty 'ad_segments' must not
    silently lose the predictions to json.loads' last-wins semantics."""
    model_output = (
        '{"adSegments":[{"segment_offset":42.0,"confidence":0.8}],' '"ad_segments":[]}'
    )
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=42.0, confidence=0.8)]
    )


def test_clean_parse_output_concatenated_with_data() -> None:
    """Concatenated duplicate objects where only the first carries data:
    the object with the most predictions must win."""
    model_output = (
        '{"adSegments":[{"segment_offset":42.0,"confidence":0.8}],'
        '"ad_segments":[],"ads":[]}\n\n{"ad_segments":[]}'
    )
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=42.0, confidence=0.8)]
    )


def test_clean_parse_output_string_values_with_structural_chars() -> None:
    """Brackets/braces/parens inside string values are structural-noise for
    the scanners and must be preserved untouched (paren in a phone number,
    brace in prose)."""
    model_output = (
        '{"ad_segments": [], "note": "call (555) 123-4567 {ok}", ' '"confidence": 0.4}'
    )
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(ad_segments=[], confidence=0.4)


def test_clean_parse_output_prose_with_unbalanced_brace_tail() -> None:
    """Trailing prose containing an unclosed brace must not corrupt the
    leading JSON object."""
    model_output = '{"ad_segments": [], "confidence": 0.4} Some prose { unclosed'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(ad_segments=[], confidence=0.4)
