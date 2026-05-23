"""UUID value generator.

Spec fields::

    {
      "type":      "uuid",
      "version":   4,             // optional, 1 or 4 (default 4)
      "uppercase": false          // optional, default false
    }

Notes:

* UUID4 is drawn from the spec's :class:`random.Random` so the engine
  remains seed-reproducible. UUID1 uses the host clock + node id and
  is *not* reproducible -- the seed has no effect for that variant.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator

_SUPPORTED_VERSIONS = (1, 4)


@dataclass(frozen=True)
class UUIDSpec:
    version: int
    uppercase: bool


class UUIDGenerator(Generator):
    """Emit a UUID string (version 1 or 4)."""

    type_name = "uuid"

    def prepare(self, spec: Mapping[str, Any]) -> UUIDSpec:
        version = int(spec.get("version", 4))
        if version not in _SUPPORTED_VERSIONS:
            raise ValueError(f"uuid 'version' must be 1 or 4, got {version}")
        return UUIDSpec(version=version, uppercase=bool(spec.get("uppercase", False)))

    def generate(self, prepared: UUIDSpec, rng: Random) -> str:
        if prepared.version == 4:
            # Build a UUID4 from 16 random bytes drawn from the seeded RNG
            # so output stays reproducible.
            value = uuid.UUID(bytes=rng.randbytes(16), version=4)
        else:
            value = uuid.uuid1()
        text = str(value)
        return text.upper() if prepared.uppercase else text
