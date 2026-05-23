"""Tests for the regex generator."""

from __future__ import annotations

import re
from random import Random

import pytest

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
