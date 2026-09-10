"""Independent grammar checks for the stack-safe JSON reader."""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from ton._json import parse_json


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        "[]",
        "null",
        "true",
        "false",
        "0",
        "-123",
        "1.234567890123456789",
        "1e10000",
        '"escaped \\n\\t\\u00e9\\ud83d\\ude00"',
        ' { "key": [1, {"nested": [false, null, "{}[]"]}, 2], "empty": {} } \n',
        '{"duplicate": 1, "duplicate": 2}',
        "[[], {}, [[], {}]]",
    ],
)
def test_json_reader_matches_standard_scalar_and_container_semantics(text):
    """SCALE-017: iterative traversal preserves JSON values, ordering and precision."""
    expected = json.loads(text, parse_float=Decimal)
    assert parse_json(text) == expected
    if isinstance(expected, dict):
        assert list(parse_json(text)) == list(expected)


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "[",
        "{",
        "[1",
        '{"x":1',
        "[1,]",
        '{"x":1,}',
        "[,1]",
        "{,}",
        "[1 2]",
        '{"x":1 "y":2}',
        '{"x" 1}',
        "{x:1}",
        "{1:2}",
        '"unterminated',
        '"bad\nstring"',
        '"\\q"',
        "01",
        "-01",
        "1.",
        "1e",
        "true false",
        "[]{}",
        "[}",
        "{]",
        "[1,,2]",
        '{"x":}',
        '{"x": [1, {"y":}]}',
        "\ufeff{}",
    ],
)
def test_json_reader_rejects_malformed_input_at_the_standard_position(text):
    """SCALE-017: depth support cannot relax commas, keys, escapes or numeric grammar."""
    with pytest.raises(json.JSONDecodeError) as expected:
        json.loads(text)
    with pytest.raises(json.JSONDecodeError) as actual:
        parse_json(text)
    assert actual.value.pos == expected.value.pos
    assert actual.value.doc == text


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_json_reader_preserves_standard_nonfinite_scalar_decoding(text):
    """SCALE-017: config field validation remains responsible for finite bounds."""
    expected = json.loads(text)
    actual = parse_json(text)
    assert math.isnan(actual) if math.isnan(expected) else actual == expected
