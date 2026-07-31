"""Tests for the per-generator output-size caps (SCALE-002)."""

from __future__ import annotations

import base64
from random import Random

import pytest

from ton._engine import Engine, TemplateError
from ton.generators import Generator
from ton.generators.bytes import BytesGenerator
from ton.generators.char import CharGenerator
from ton.generators.regex import (
    MAX_LITERAL_REPEAT,
    MAX_TOTAL_EXPANSION,
    RegexGenerator,
)
from ton.generators.sequence import MAX_SEQUENCE_PAD_WIDTH, SequenceGenerator
from ton.generators.text import TextGenerator


def test_char_honors_large_operator_requested_length() -> None:
    spec = {"values": ["A"], "maxChar": 100_001}
    prepared = CharGenerator().prepare(spec)
    assert CharGenerator().generate(prepared, Random(0)) == "A" * 100_001


def test_bytes_honors_large_operator_requested_length() -> None:
    generator = BytesGenerator()
    prepared = generator.prepare({"length": 1_000_001, "encoding": "base64"})

    assert len(base64.b64decode(generator.generate(prepared, Random(0)))) == 1_000_001


def test_text_honors_large_operator_requested_count() -> None:
    generator = TextGenerator()
    prepared = generator.prepare({"unit": "words", "count": 10_001})

    assert len(generator.generate(prepared, Random(0)).split()) == 10_001


def test_sequence_rejects_pad_width_above_cap() -> None:
    with pytest.raises(ValueError, match="MAX_SEQUENCE_PAD_WIDTH"):
        SequenceGenerator().prepare({"padWidth": MAX_SEQUENCE_PAD_WIDTH + 1})


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


def test_row_width_counts_literals_and_all_placeholders() -> None:
    config = {
        "rows": 1,
        "maxRowWidth": 5,
        "format": "x$a$$b$",
        "types": {
            "a": {"type": "string", "values": ["aa"]},
            "b": {"type": "string", "values": ["bb"]},
        },
    }
    assert list(Engine(config)) == ["xaabb"]
    config["maxRowWidth"] = 4
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(Engine(config))


def test_row_width_is_unbounded_when_limit_is_omitted() -> None:
    wide = "x" * 2_000_001
    config = {"rows": 1, "format": wide, "types": {"v": {"type": "string", "values": [""]}}}

    assert list(Engine(config)) == [wide]


def test_row_width_guards_composite_and_unknown_width_values() -> None:
    composite = {
        "rows": 1,
        "maxRowWidth": 3,
        "format": "$v$",
        "types": {"v": {"type": "oneOf", "choices": [{"type": "string", "values": ["wide"]}]}},
    }
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(Engine(composite))

    class UnknownWidth(Generator):
        type_name = "unknown"

        def generate(self, prepared, rng) -> str:
            return "wide"

    unknown = {"rows": 1, "maxRowWidth": 3, "format": "$v$", "types": {"v": {"type": "unknown"}}}
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(Engine(unknown, registry={"unknown": UnknownWidth()}))
