"""Fixed-count composite generator (PAT-011).

Concatenates ``count`` independent draws from a single child generator,
joined by an optional ``separator``. Useful for compound identifiers
(e.g. four hex octets), comma-separated lists, repeat counts that don't
fit cleanly into the ``regex`` generator's quantifier surface, etc.

Spec::

    {
      "type":      "sequence_of",
      "count":     4,
      "separator": "-",
      "spec":      {"type": "integer", "minValue": 0, "maxValue": 9,
                    "padWithZero": false}
    }

``count`` is capped at :data:`MAX_SEQUENCE_OF_COUNT` so a misconfigured
``1_000_000`` does not produce gigabyte rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar

from .base import (
    Generator,
    assert_below_cap,
    coerce_int,
    prepare_child_spec,
)

#: Upper bound on ``count`` so the generator stays bounded under
#: misconfiguration (mirrors MAX_TEXT_COUNT / MAX_CHAR_LENGTH).
MAX_SEQUENCE_OF_COUNT = 10_000


@dataclass(frozen=True)
class SequenceOfSpec:
    count: int
    separator: str
    child: tuple[Generator, Any]


class SequenceOfGenerator(Generator):
    """Concatenate ``count`` independent draws from a single child generator."""

    type_name = "sequence_of"
    is_composite: ClassVar[bool] = True

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> SequenceOfSpec:
        count = coerce_int(spec, "count", type_name="sequence_of")
        if count < 1:
            raise ValueError("sequence_of 'count' must be >= 1")
        assert_below_cap(
            "sequence_of",
            "count",
            count,
            MAX_SEQUENCE_OF_COUNT,
            "MAX_SEQUENCE_OF_COUNT",
        )
        separator = spec.get("separator", "")
        if not isinstance(separator, str):
            raise ValueError("sequence_of 'separator' must be a string")
        child = prepare_child_spec("sequence_of", "'spec'", spec.get("spec"), registry)
        return SequenceOfSpec(count=count, separator=separator, child=child)

    def generate(self, prepared: SequenceOfSpec, rng: Random) -> str:
        child_gen, child_prepared = prepared.child
        parts = [child_gen.generate(child_prepared, rng) for _ in range(prepared.count)]
        if prepared.separator:
            return prepared.separator.join(parts)
        return "".join(parts)
