"""Random-bytes generator with hex / base64 / base32 encoding.

Spec fields::

    {
      "type":     "bytes",
      "length":   16,                // raw bytes to draw (>=1)
      "encoding": "hex"              // hex | base64 | base32 (default hex)
    }

Useful for opaque tokens, salts, fixture session ids.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, Callable

from .base import Generator

_ENCODERS: dict[str, Callable[[bytes], str]] = {
    "hex": lambda raw: raw.hex(),
    "base64": lambda raw: base64.b64encode(raw).decode("ascii"),
    "base32": lambda raw: base64.b32encode(raw).decode("ascii"),
}

#: Upper bound on raw bytes drawn per row (TODO SCALE-002).
MAX_BYTES_LENGTH = 1_000_000


@dataclass(frozen=True)
class BytesSpec:
    length: int
    encode: Callable[[bytes], str]


class BytesGenerator(Generator):
    """Emit ``length`` random bytes encoded as hex / base64 / base32."""

    type_name = "bytes"

    def prepare(self, spec: Mapping[str, Any]) -> BytesSpec:
        length = int(spec.get("length", 16))
        if length < 1:
            raise ValueError("bytes 'length' must be >= 1")
        if length > MAX_BYTES_LENGTH:
            raise ValueError(
                f"bytes 'length' exceeds MAX_BYTES_LENGTH ({MAX_BYTES_LENGTH})"
            )
        encoding = str(spec.get("encoding", "hex"))
        if encoding not in _ENCODERS:
            raise ValueError(
                f"bytes 'encoding' must be one of {sorted(_ENCODERS)} (got {encoding!r})"
            )
        return BytesSpec(length=length, encode=_ENCODERS[encoding])

    def generate(self, prepared: BytesSpec, rng: Random) -> str:
        return prepared.encode(rng.randbytes(prepared.length))
