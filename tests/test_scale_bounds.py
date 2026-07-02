"""Tests for the per-generator output-size caps (SCALE-002)."""

from __future__ import annotations

import pytest

from ton.generators.bytes import MAX_BYTES_LENGTH, BytesGenerator
from ton.generators.char import MAX_CHAR_LENGTH, CharGenerator
from ton.generators.regex import (
    MAX_LITERAL_REPEAT,
    MAX_TOTAL_EXPANSION,
    RegexGenerator,
)
from ton.generators.text import MAX_TEXT_COUNT, TextGenerator


def test_char_rejects_max_char_above_cap() -> None:
    with pytest.raises(ValueError, match="MAX_CHAR_LENGTH"):
        CharGenerator().prepare({"values": ["A"], "maxChar": MAX_CHAR_LENGTH + 1})


def test_char_accepts_max_char_at_cap() -> None:
    spec = {"values": ["A"], "maxChar": MAX_CHAR_LENGTH}
    prepared = CharGenerator().prepare(spec)
    assert prepared.max_char == MAX_CHAR_LENGTH


def test_bytes_rejects_length_above_cap() -> None:
    with pytest.raises(ValueError, match="MAX_BYTES_LENGTH"):
        BytesGenerator().prepare({"length": MAX_BYTES_LENGTH + 1})


def test_text_rejects_count_above_cap() -> None:
    with pytest.raises(ValueError, match="MAX_TEXT_COUNT"):
        TextGenerator().prepare({"count": MAX_TEXT_COUNT + 1})


def test_regex_rejects_oversized_literal_repeat() -> None:
    big = MAX_LITERAL_REPEAT + 1
    with pytest.raises(ValueError, match="MAX_LITERAL_REPEAT"):
        RegexGenerator().prepare({"pattern": f"a{{{big}}}"})


def test_regex_rejects_oversized_literal_inside_group() -> None:
    big = MAX_LITERAL_REPEAT + 1
    with pytest.raises(ValueError, match="MAX_LITERAL_REPEAT"):
        RegexGenerator().prepare({"pattern": f"(ab){{{big}}}"})


def test_regex_rejects_oversized_literal_inside_alternation() -> None:
    big = MAX_LITERAL_REPEAT + 1
    with pytest.raises(ValueError, match="MAX_LITERAL_REPEAT"):
        RegexGenerator().prepare({"pattern": f"x|a{{{big}}}"})


def test_regex_accepts_unbounded_quantifiers_at_any_lo() -> None:
    # 'a+' (unbounded) is still allowed; only literal lo/hi exceeding
    # MAX_LITERAL_REPEAT trip the cap.
    RegexGenerator().prepare({"pattern": "a+"})
    RegexGenerator().prepare({"pattern": "a*"})


def test_regex_rejects_nested_repeats_exceeding_total_expansion() -> None:
    # Each node is within MAX_LITERAL_REPEAT, but nesting multiplies:
    # 5000 * 5000 = 25M chars/row (SEC-001).
    with pytest.raises(ValueError, match="MAX_TOTAL_EXPANSION"):
        RegexGenerator().prepare({"pattern": "(?:a{5000}){5000}"})


def test_regex_accepts_pattern_within_total_expansion() -> None:
    # A single large-but-bounded repeat stays under the total cap.
    prepared = RegexGenerator().prepare({"pattern": "a{10000}"})
    assert prepared is not None
    assert MAX_TOTAL_EXPANSION == 1_000_000
