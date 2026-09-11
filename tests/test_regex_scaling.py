"""SCALE-023: regex proofs release obsolete match positions."""

import re
import tracemalloc
from itertools import product
from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.regex import RegexGenerator


def test_nullable_repeat_proof_memory_grows_with_frontier_not_history():
    generator = RegexGenerator()
    peaks = []
    for count in [50, 100, 200]:
        prepared = generator.prepare({"pattern": f"(?:a?){{{count}}}a{{{count}}}"})
        value = generator.generate(prepared, Random(42))
        tracemalloc.start()
        try:
            assert generator.prove(prepared, TransformResult(value)).ok
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    assert peaks[-1] < peaks[0] * 6, peaks
    assert peaks[-1] < 2_000_000


@pytest.mark.parametrize(
    "pattern",
    [
        "(?:a?){3}a{3}",
        "(?:a?)*",
        "(?:a?){2,4}",
        "(?:(?:a?){2}){3}",
        "(?:a|ab){1,3}",
        "(?:a*|b?){2,3}",
        "(?:ab?)*b",
        "(?:(?:a|b)*a?)+",
        "(?:a{0}){5}",
        "(?:ab){2}",
        "(a+)+",
        "a{2,}b{0,3}",
    ],
)
def test_compact_matcher_agrees_with_small_pattern_oracle(pattern):
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": pattern})
    for length in range(7):
        for chars in product("ab", repeat=length):
            value = "".join(chars)
            assert generator.prove(prepared, TransformResult(value)).ok == bool(
                re.fullmatch(pattern, value)
            ), (pattern, value)


def test_huge_nullable_repeat_proof_does_not_expand_empty_iterations():
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "(?:a?){1000000000000}"})
    assert generator.prove(prepared, TransformResult("")).ok
    assert generator.prove(prepared, TransformResult("aaa")).ok
    assert not generator.prove(prepared, TransformResult("b")).ok
    prepared = generator.prepare({"pattern": "a{1000000000000}"})
    assert not generator.prove(prepared, TransformResult("a")).ok


def test_deep_group_proofs_use_heap_continuations_without_recursion_changes():
    """SCALE-023: sharing continuations preserves stack safety on acceptance and rejection."""
    import sys

    limit = sys.getrecursionlimit()
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "(" * 2000 + "a" + ")" * 2000})
    assert generator.prove(prepared, TransformResult("a")).ok
    assert not generator.prove(prepared, TransformResult("b")).ok
    assert sys.getrecursionlimit() == limit
