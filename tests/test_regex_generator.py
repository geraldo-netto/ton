"""Tests for the regex generator."""

from __future__ import annotations

import re
from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.regex import RegexGenerator


def _draw(pattern: str, seed: int = 0) -> str:
    gen = RegexGenerator()
    prepared = gen.prepare({"pattern": pattern})
    return gen.generate(prepared, Random(seed))


@pytest.mark.parametrize(
    "pattern",
    [
        "abc",
        "[A-Z]{3}-\\d{4}",
        "(foo|bar)",
        "a?b+c*",
        "\\d{3}\\.\\d{2}",
        "[a-z0-9]{8}",
        "[^0-9a-zA-Z]",
        "(?:cat|dog|fish)",
        "x{2,5}",
        "\\w{4}",
    ],
)
def test_generated_value_matches_pattern(pattern: str) -> None:
    rng_seeds = range(20)
    matcher = re.compile(f"^{pattern}$")
    for seed in rng_seeds:
        value = _draw(pattern, seed=seed)
        assert matcher.match(value), f"seed={seed}: {value!r} does not match {pattern!r}"


def test_rejects_empty_pattern() -> None:
    with pytest.raises(ValueError):
        RegexGenerator().prepare({"pattern": ""})


def test_rejects_invalid_regex() -> None:
    with pytest.raises(ValueError):
        RegexGenerator().prepare({"pattern": "[unclosed"})


@pytest.mark.parametrize("pattern", [r"^foo$", r"(^foo$)", r"(^foo|^bar)$", r"^(foo$|bar$)"])
def test_edge_anchors_match_generated_values(pattern: str) -> None:
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": pattern})
    value = generator.generate(prepared, Random(0))

    assert generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize(
    "pattern",
    [
        r"a^b",
        r"a$b",
        r"a\bb",
        r"(a^b)",
        r"a(^b|c)",
        r"(a$|b)c",
        r"(^a)+",
        r"(a\b|b)",
    ],
)
def test_rejects_unsupported_anchor_positions(pattern: str) -> None:
    with pytest.raises(ValueError, match="unsupported positional anchor"):
        RegexGenerator().prepare({"pattern": pattern})


def test_unbounded_repeat_terminates() -> None:
    value = _draw("a+", seed=0)
    assert re.match(r"^a+$", value)


def test_unbounded_repeat_has_seeded_unbounded_support() -> None:
    first = _draw("a*", seed=95)
    second = _draw("a*", seed=95)
    assert first == "a" * 10
    assert second == first


@pytest.mark.parametrize(
    "pattern",
    [
        "a{2,}",  # open-ended brace
        "a+?",  # lazy quantifier
        "a*?",
        "x{2,5}?",
        "\\w{3}",
        "\\S{2}",
    ],
)
def test_vendored_parser_matches_reference(pattern: str) -> None:
    matcher = re.compile(f"^{pattern}$")
    for seed in range(20):
        value = _draw(pattern, seed=seed)
        assert matcher.match(value), f"seed={seed}: {value!r} !~ {pattern!r}"


def test_bare_brace_is_literal() -> None:
    # '{' not forming a valid quantifier is a literal char.
    assert _draw("a{") == "a{"


def test_class_backspace_escape() -> None:
    assert _draw("[\\b]") == "\b"


def test_control_and_literal_escapes() -> None:
    assert _draw("a\\n") == "a\n"
    assert _draw("a\\@") == "a@"


@pytest.mark.parametrize("pattern", [r"(a)\1", r"\x41", r"\u0041", r"\07"])
def test_unsupported_escape_forms_are_rejected(pattern: str) -> None:
    with pytest.raises(ValueError, match="unsupported .*escape"):
        RegexGenerator().prepare({"pattern": pattern})


@pytest.mark.parametrize(
    "pattern",
    [
        "*a",  # nothing to repeat
        "a{5,2}",  # min > max
        "(?=x)",  # unsupported group extension
        "(abc",  # missing close paren
        "[a-\\d]",  # bad character range
        "[z-a]",  # reversed character range
        "[z-a0]",  # reversed range must not disappear beside valid members
        "a\\",  # trailing backslash
        "a)",  # leftover close paren
    ],
)
def test_vendored_parser_rejects_bad_patterns(pattern: str) -> None:
    with pytest.raises(ValueError):
        RegexGenerator().prepare({"pattern": pattern})


@pytest.mark.parametrize("pattern", ["[]", "[^ -~]"])
def test_rejects_invalid_character_classes_at_prepare(pattern: str) -> None:
    with pytest.raises(ValueError, match="character class"):
        RegexGenerator().prepare({"pattern": pattern})


def test_deep_group_nesting_uses_iterative_pipeline() -> None:
    pattern = "(" * 2_000 + "a" + ")" * 2_000

    assert _draw(pattern) == "a"


def test_character_classes_are_resolved_during_prepare(monkeypatch) -> None:
    from ton.generators import regex

    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "([a-z]|[0-9]){3}"})
    monkeypatch.setattr(regex, "_in_pool", lambda items: pytest.fail("resolved class again"))

    assert re.fullmatch(r"([a-z]|[0-9]){3}", generator.generate(prepared, Random(0)))


def test_not_literal_pool_is_resolved_during_prepare(monkeypatch) -> None:
    from ton.generators import regex

    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "[^x]{3}"})
    monkeypatch.setattr(
        regex, "_excluding_pool", lambda excluded: pytest.fail("resolved exclusion again")
    )

    assert re.fullmatch(r"[^x]{3}", generator.generate(prepared, Random(0)))


@pytest.mark.parametrize(
    ("pattern", "pool"),
    [
        ("[a-z]", tuple("abcdefghijklmnopqrstuvwxyz")),
        ("[^x]", tuple(chr(code) for code in range(0x20, 0x7F) if chr(code) != "x")),
    ],
)
def test_prepared_regex_pools_preserve_seeded_choices(pattern: str, pool: tuple[str, ...]) -> None:
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": pattern})

    for seed in range(20):
        assert generator.generate(prepared, Random(seed)) == Random(seed).choice(pool)
