"""Monotonic counter generator.

Spec fields::

    {
      "type":     "sequence",
      "start":    0,        // optional, default 0
      "step":     1,        // optional, default 1
      "padWidth": 6         // optional, zero-pad output to this width
    }

State lives on the prepared spec (one ``itertools.count`` per engine
instance). When the engine is replicated across worker processes via
:func:`ton.concurrency.fork_engine`, TON automatically offsets each
worker's configured ``start`` by its exact preceding-row count and
``step``. Do not apply an additional manual worker offset.

Thread-safety (CONC-003)
-----------------------------
``itertools.count`` is **not** thread-safe; reading the counter from
multiple Python threads against the same prepared spec can hand out
duplicate or skipped ids. The TON engine is single-threaded by
contract -- construct one :class:`ton.api.Engine` (or call
:func:`ton.concurrency.fork_engine`) per worker / thread so each owns
its own ``SequenceSpec.counter``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import count
from random import Random
from typing import Any

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator, coerce_int, int_to_str, pad_with_zero, proof_result, str_to_int


@dataclass(frozen=True)
class SequenceSpec:
    counter: Iterator[int]
    start: int
    step: int
    pad_width: int


class SequenceGenerator(Generator):
    """Emit the next integer in a per-engine counter."""

    type_name = "sequence"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> SequenceSpec:
        start = coerce_int(spec, "start", type_name="sequence", default=0)
        step = coerce_int(spec, "step", type_name="sequence", default=1)
        if step == 0:
            raise ValueError("sequence 'step' must be non-zero")
        pad_width = coerce_int(spec, "padWidth", type_name="sequence", default=0)
        if pad_width < 0:
            raise ValueError("sequence 'padWidth' must be >= 0")
        return SequenceSpec(
            counter=count(start, step),
            start=start,
            step=step,
            pad_width=pad_width,
        )

    def generate(self, prepared: SequenceSpec, rng: Random) -> str:
        # rng is intentionally unused -- the value is deterministic by design.
        value = int_to_str(next(prepared.counter))
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value

    def prove(self, prepared: SequenceSpec, result: TransformResult) -> ProofResult:
        try:
            value = str_to_int(result.value)
        except ValueError:
            return proof_result(False, "sequence value is not an integer")
        if result.value != int_to_str(value).zfill(prepared.pad_width):
            return proof_result(False, "sequence value violates its padding contract")
        delta = value - prepared.start
        valid = delta % prepared.step == 0 and delta // prepared.step >= 0
        return proof_result(valid, "sequence value is outside its configured progression")
