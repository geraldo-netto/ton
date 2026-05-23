"""Monotonic counter generator.

Spec fields::

    {
      "type":     "sequence",
      "start":    1,        // optional, default 0
      "step":     1,        // optional, default 1
      "padWidth": 6         // optional, zero-pad output to this width
    }

State lives on the prepared spec (one ``itertools.count`` per engine
instance). When the engine is replicated across worker processes via
:func:`ton.concurrency.fork_engine`, each worker starts its own
counter -- callers that need globally-unique ids across workers
should set ``start`` to ``worker_id * chunk_size``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from random import Random
from typing import Any, Iterator, Mapping

from .base import Generator, pad_with_zero


@dataclass(frozen=True)
class SequenceSpec:
    counter: Iterator[int]
    pad_width: int


class SequenceGenerator(Generator):
    """Emit the next integer in a per-engine counter."""

    type_name = "sequence"

    def prepare(self, spec: Mapping[str, Any]) -> SequenceSpec:
        start = int(spec.get("start", 0))
        step = int(spec.get("step", 1))
        if step == 0:
            raise ValueError("sequence 'step' must be non-zero")
        return SequenceSpec(
            counter=count(start, step),
            pad_width=int(spec.get("padWidth", 0)),
        )

    def generate(self, prepared: SequenceSpec, rng: Random) -> str:
        # rng is intentionally unused -- the value is deterministic by design.
        value = str(next(prepared.counter))
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value
