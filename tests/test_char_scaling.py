"""PERF-049: exact token segmentation with bounded repeated matching work."""

from itertools import product
from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.char import CharGenerator


@pytest.mark.parametrize("count", [100, 500, 1000])
def test_ambiguous_char_proof_matches_each_position_once(count):
    class Counted(str):
        calls = 0

        def startswith(self, prefix, start=0, end=None):
            self.calls += 1
            return super().startswith(prefix, start, len(self) if end is None else end)

    generator = CharGenerator()
    prepared = generator.prepare({"values": ["a", "aa"], "maxChar": count})
    value = Counted("a" * (count + count // 2))
    assert generator.prove(prepared, TransformResult(value)).ok
    assert value.calls <= 4 * len(value)


@pytest.mark.parametrize(
    "pool",
    [
        ["a"],
        ["a", "b"],
        ["a", "aa"],
        ["", "a"],
        ["", ""],
        ["", "ab", "a", "ba"],
        ["ab", "ba"],
        ["a", "aba", "a"],
    ],
)
@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_char_proof_matches_exhaustive_concatenation_oracle(pool, count):
    generator = CharGenerator()
    prepared = generator.prepare({"values": pool, "maxChar": count})
    expected = {"".join(parts) for parts in product(pool, repeat=count)}
    candidates = expected | {"".join(chars) for n in range(7) for chars in product("ab", repeat=n)}
    candidates.add("unexpected")
    for value in candidates:
        assert generator.prove(prepared, TransformResult(value)).ok == (value in expected), value
    rng = Random(42)
    assert generator.generate(prepared, Random(42)) == "".join(rng.choices(pool, k=count))


def test_empty_tokens_allow_large_draw_counts_without_large_bitsets():
    generator = CharGenerator()
    prepared = generator.prepare({"values": ["", "ab"], "maxChar": 10**100})
    assert generator.prove(prepared, TransformResult("abab")).ok
    assert not generator.prove(prepared, TransformResult("aba")).ok
