import pytest

from podcast_processor.model_output import clean_and_parse_model_output


def test_clean_and_parse_model_output_well_formed():
    output = '{"ad_segments": [{"segment_offset": 10.5, "confidence": 0.92}]}'
    result = clean_and_parse_model_output(output)
    assert len(result.ad_segments) == 1
    assert result.ad_segments[0].segment_offset == 10.5
    assert result.ad_segments[0].confidence == 0.92


def test_clean_and_parse_model_output_repairs_truncation_mid_number():
    # Matches the truncation shape seen in production: the response is cut
    # off after a bare numeric value (no closing quote to anchor a repair
    # regex on), mid-way through a later element in a long ad_segments list.
    output = (
        '{"ad_segments": [{"segment_offset": 1107.6, "confidence": 0.9},'
        '{"segment_offset": 1111.5, "confidence": 0.9},'
        '{"segment_offset": 1113.8, "confidence": 0.'
    )
    result = clean_and_parse_model_output(output)
    assert [seg.segment_offset for seg in result.ad_segments] == [1107.6, 1111.5]


def test_clean_and_parse_model_output_repairs_truncation_mid_key():
    output = (
        '{"ad_segments": [{"segment_offset": 10.5, "confidence": 0.92},'
        '{"segment_offset": 20.0, "conf'
    )
    result = clean_and_parse_model_output(output)
    assert [seg.segment_offset for seg in result.ad_segments] == [10.5]


def test_clean_and_parse_model_output_repairs_truncation_mid_string_value():
    output = (
        '{"ad_segments": [{"segment_offset": 10.5, "confidence": 0.92}],'
        '"content_type": "educ'
    )
    result = clean_and_parse_model_output(output)
    assert [seg.segment_offset for seg in result.ad_segments] == [10.5]


def test_clean_and_parse_model_output_no_recoverable_content_raises():
    with pytest.raises(Exception):
        clean_and_parse_model_output('{"ad_segments": [{"segment_offset": 10.5, "conf')
