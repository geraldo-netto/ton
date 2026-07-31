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
:func:`ton.concurrency.fork_engine`, each worker starts its own
counter -- callers that need globally-unique ids across workers
should set ``start`` to ``worker_id * chunk_size``.

Thread-safety (TODO CONC-003)
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
from .base import Generator, coerce_int, pad_with_zero, proof_result


@dataclass(frozen=True)
class SequenceSpec:
    counter: Iterator[int]
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
            pad_width=pad_width,
        )

    def generate(self, prepared: SequenceSpec, rng: Random) -> str:
        # rng is intentionally unused -- the value is deterministic by design.
        value = str(next(prepared.counter))
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value

    def prove(self, prepared: SequenceSpec, result: TransformResult) -> ProofResult:
        try:
            int(result.value)
        except ValueError:
            return proof_result(False, "sequence value is not an integer")
        valid = not prepared.pad_width or len(result.value) >= prepared.pad_width
        return proof_result(valid, "sequence value violates its padding contract")
