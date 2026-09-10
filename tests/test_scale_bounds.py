"""Tests for operator-controlled generator scale."""

from __future__ import annotations

import base64
import os
import sys
from random import Random

import pytest

from ton import _recursion, api
from ton._engine import Engine, TemplateError
from ton._specsnapshot import snapshot_spec
from ton.generators import Generator
from ton.generators.base import int_to_str, str_to_int
from ton.generators.bytes import BytesGenerator
from ton.generators.char import CharGenerator
from ton.generators.regex import RegexGenerator
from ton.generators.sequence import SequenceGenerator
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


def test_sequence_honors_large_operator_requested_padding() -> None:
    generator = SequenceGenerator()
    prepared = generator.prepare({"start": 1, "padWidth": 100_001})

    assert generator.generate(prepared, Random(0)) == "0" * 100_000 + "1"


def test_regex_honors_large_literal_repeat() -> None:
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "a{10001}"})

    assert generator.generate(prepared, Random(0)) == "a" * 10_001


def test_regex_accepts_unbounded_quantifiers_at_any_lo() -> None:
    RegexGenerator().prepare({"pattern": "a+"})
    RegexGenerator().prepare({"pattern": "a*"})


def test_regex_prepares_nested_repeats_without_eager_expansion() -> None:
    assert RegexGenerator().prepare({"pattern": "(?:a{5000}){5000}"}) is not None


def test_regex_accepts_pattern_within_total_expansion() -> None:
    prepared = RegexGenerator().prepare({"pattern": "a{10000}"})
    assert prepared is not None


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
    engine = Engine(unknown, registry={"unknown": UnknownWidth()})
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(engine)


BIG = 10**4300


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("rows", [0, 2])
def test_large_padded_integer_bounds(sign: int, rows: int) -> None:
    """SCALE-005: padding must use arbitrary-size conversion during preparation."""
    before = sys.get_int_max_str_digits()
    bound = sign * BIG
    config = {
        "rows": rows,
        "format": "$x$",
        "types": {
            "x": {"type": "integer", "minValue": bound, "maxValue": bound, "padWithZero": True}
        },
    }
    expected = ("-" if sign < 0 else "") + "1" + "0" * 4300
    assert list(api.generate(config, proof_mode="all")) == [expected] * rows
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize(
    ("label", "spec"),
    [
        ("integer", {"type": "integer", "minValue": BIG, "maxValue": BIG}),
        ("sequence", {"type": "sequence", "start": BIG}),
        ("decimal", {"type": "decimal", "minValue": 0, "maxValue": 1, "decimals": 4301}),
    ],
)
def test_numeric_rendering_has_no_digit_ceiling(label: str, spec: dict) -> None:
    """CPython's 4,300-digit int->str limit is not TON's ceiling (SCALE-005)."""
    config = {"rows": 1, "format": "$x$", "types": {"x": spec}}

    rows = list(api.generate(config, seed=1, proof_mode="all"))

    assert len(rows[0].lstrip("-")) > 4300
    if label != "decimal":
        assert rows[0] == "1" + "0" * 4300


def test_oversized_rendering_does_not_change_the_process_limit() -> None:
    """The fix must not reach for a process-global setting (SCALE-005)."""
    before = sys.get_int_max_str_digits()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "integer", "minValue": BIG, "maxValue": BIG}},
    }

    list(api.generate(config, seed=1))

    assert sys.get_int_max_str_digits() == before


def test_int_conversion_helpers_stay_as_strict_as_int() -> None:
    """The arbitrary-size fallback must not widen what counts as an integer."""
    assert str_to_int(int_to_str(BIG)) == BIG
    assert str_to_int(int_to_str(-BIG)) == -BIG
    for text in ("abc", "1.5", "", "1e5"):
        with pytest.raises(ValueError):
            str_to_int(text)


def _nested_one_of(levels: int) -> dict:
    spec: dict = {"type": "string", "values": ["x"]}
    for _ in range(levels):
        spec = {"type": "oneOf", "choices": [spec]}
    return {"rows": 1, "format": "$x$", "types": {"x": spec}}


def test_deeply_nested_composites_prepare_and_generate() -> None:
    """A chain far past the default recursion limit must produce its row (SCALE-007)."""
    assert list(api.generate(_nested_one_of(600), seed=1, proof_mode="all")) == ["x"]


def test_nesting_beyond_the_process_stack_reports_the_operator_remedy() -> None:
    """Past what the stack supports TON explains the fix; it does not crash."""
    too_deep = _recursion.max_supported_depth() + 50

    with pytest.raises(TemplateError, match="TON imposes no nesting limit of its own"):
        list(api.generate(_nested_one_of(too_deep), seed=1))


def test_depth_headroom_only_ever_raises_the_limit() -> None:
    """A caller that already raised the limit keeps its own setting."""
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(original + 50_000)
    try:
        _recursion.ensure_depth_headroom(10)
        assert sys.getrecursionlimit() == original + 50_000
    finally:
        sys.setrecursionlimit(original)


def test_spec_snapshot_is_stack_safe_independently_of_the_limit() -> None:
    """Snapshotting runs before head-room is sized, so it must not recurse."""
    spec: dict = {"type": "string", "values": ["x"]}
    for _ in range(5_000):
        spec = {"type": "oneOf", "choices": [spec]}

    copied = snapshot_spec(spec)

    # Walk both iteratively: a deep == would recurse in the assertion itself.
    depth, original, clone = 0, spec, copied
    while clone["type"] == "oneOf":
        assert clone is not original
        original, clone = original["choices"][0], clone["choices"][0]
        depth += 1

    assert depth == 5_000
    assert clone == {"type": "string", "values": ["x"]}
    assert clone is not original


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX resource module (PLAT-015)")
def test_unlimited_stack_falls_back_to_an_assumed_size(monkeypatch) -> None:
    """An unlimited RLIMIT_STACK still yields a usable depth (SCALE-007)."""
    import resource

    monkeypatch.setattr(
        resource, "getrlimit", lambda _which: (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    )

    assert _recursion._stack_bytes() == _recursion.DEFAULT_STACK_BYTES
    assert _recursion.max_supported_depth() > 0
