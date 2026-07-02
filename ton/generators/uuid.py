"""UUID value generator.

Spec fields::

    {
      "type":      "uuid",
      "version":   4,             // optional, 1 or 4 (default 4)
      "uppercase": false          // optional, default false
    }

Notes:

* Both versions are built from 16 bytes drawn from the spec's
  :class:`random.Random`, so output stays seed-reproducible. The version
  1 variant is therefore *synthetic*: it carries a random node/clock
  rather than the host's real MAC address and clock, so generated data
  never leaks host hardware/network identifiers (DG-003).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, coerce_int

_SUPPORTED_VERSIONS = (1, 4)


@dataclass(frozen=True)
class UUIDSpec:
    version: int
    uppercase: bool


class UUIDGenerator(Generator):
    """Emit a UUID string (version 1 or 4)."""

    type_name = "uuid"

    def prepare(self, spec: Mapping[str, Any]) -> UUIDSpec:
        version = coerce_int(spec, "version", type_name="uuid", default=4)
        if version not in _SUPPORTED_VERSIONS:
            raise ValueError(f"uuid 'version' must be 1 or 4, got {version}")
        return UUIDSpec(version=version, uppercase=bool(spec.get("uppercase", False)))

    def generate(self, prepared: UUIDSpec, rng: Random) -> str:
        # Both versions are built from 16 bytes drawn from the seeded RNG:
        # output stays reproducible and the v1 variant carries a random
        # node/clock instead of the host MAC + real clock (DG-003).
        value = uuid.UUID(bytes=rng.randbytes(16), version=prepared.version)
        text = str(value)
        return text.upper() if prepared.uppercase else text
