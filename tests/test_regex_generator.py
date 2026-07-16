"""Tests for the regex generator."""

from __future__ import annotations

import re
from random import Random

import pytest

from ton.generators._regex_parse import MAX_GROUP_NESTING
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


def test_anchors_ignored() -> None:
    value = _draw(r"^foo$", seed=0)
    assert value == "foo"


def test_unbounded_repeat_terminates() -> None:
    # 'a+' would loop forever if uncapped; we cap at MAX_UNBOUNDED_REPEAT.
    value = _draw("a+", seed=0)
    assert re.match(r"^a+$", value)


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


def test_rejects_excessive_group_nesting_at_prepare() -> None:
    pattern = "(" * (MAX_GROUP_NESTING + 1) + "a" + ")" * (MAX_GROUP_NESTING + 1)

    with pytest.raises(ValueError, match="MAX_GROUP_NESTING"):
        RegexGenerator().prepare({"pattern": pattern})
