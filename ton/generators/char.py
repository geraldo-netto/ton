"""Character-sequence generator."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from random import Random
from typing import Any

from .._contracts import Generator
from .._pool import StringPool
from .._proof import ProofResult, proof_result
from .._scalars import coerce_int, require_string_tuple
from .._transforms import TransformResult


@dataclass(frozen=True)
class CharSpec:
    values: tuple[str, ...]
    max_char: int

    @cached_property
    def tokens(self) -> dict[str, tuple[str, ...]]:
        buckets: dict[str, list[str]] = {}
        for token in dict.fromkeys(self.values):
            if token:
                buckets.setdefault(token[0], []).append(token)
        return {first: tuple(tokens) for first, tokens in buckets.items()}

    @cached_property
    def widths(self) -> tuple[int, int]:
        return min(map(len, self.values)), max(map(len, self.values))


class CharGenerator(Generator):
    """Concatenate ``maxChar`` random picks from ``values`` (with replacement)."""

    type_name = "char"
    config_keys = frozenset(("maxChar", "values"))

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> CharSpec:
        values = require_string_tuple(spec)
        max_char = coerce_int(spec, "maxChar", type_name="char")
        if max_char < 1:
            raise ValueError(f"char 'maxChar' must be >= 1 (got {max_char})")
        return CharSpec(values=StringPool(values), max_char=max_char)

    def generate(self, prepared: CharSpec, rng: Random) -> str:
        return "".join(rng.choices(prepared.values, k=prepared.max_char))

    def prove(self, prepared: CharSpec, result: TransformResult) -> ProofResult:
        return proof_result(
            _matches_tokens(prepared, result.value), "value is not a valid char sequence"
        )


def _matches_tokens(prepared: CharSpec, value: str) -> bool:
    minimum, maximum = prepared.widths
    count = prepared.max_char
    if not minimum * count <= len(value) <= maximum * count:
        return False
    if minimum == maximum:
        return not maximum or all(
            value[index : index + maximum] in prepared.values
            for index in range(0, len(value), maximum)
        )
    if minimum == 0:
        return _minimum_draws(prepared, value) <= count
    return _exact_draws(prepared, value)


def _ends(prepared: CharSpec, value: str, position: int) -> Iterator[int]:
    for token in prepared.tokens.get(value[position], ()):
        if value.startswith(token, position):
            yield position + len(token)


def _minimum_draws(prepared: CharSpec, value: str) -> int:
    """Empty tokens can pad any feasible segmentation to the requested count."""
    pending = {0: 0}
    for position in range(len(value)):
        count = pending.pop(position, None)
        if count is not None:
            for end in _ends(prepared, value, position):
                pending[end] = min(pending.get(end, count + 1), count + 1)
    return pending.get(len(value), prepared.max_char + 1)


def _exact_draws(prepared: CharSpec, value: str) -> bool:
    """Propagate draw-count bitsets once per position; discard consumed positions."""
    pending = {0: 1}
    mask = (1 << (prepared.max_char + 1)) - 1
    for position in range(len(value)):
        counts = pending.pop(position, 0)
        if counts:
            following = (counts << 1) & mask
            for end in _ends(prepared, value, position):
                pending[end] = pending.get(end, 0) | following
    return bool(pending.get(len(value), 0) & (1 << prepared.max_char))
