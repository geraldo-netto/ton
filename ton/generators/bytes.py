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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, coerce_int


def _encode_hex(raw: bytes) -> str:
    return raw.hex()


def _encode_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _encode_base32(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii")


_ENCODERS: dict[str, Callable[[bytes], str]] = {
    "hex": _encode_hex,
    "base64": _encode_base64,
    "base32": _encode_base32,
}

# Divisible by both base64's 3-byte and base32's 5-byte input blocks, so
# independently encoded chunks concatenate without interior padding.
_ENCODING_CHUNK_BYTES = 65_520


@dataclass(frozen=True)
class BytesSpec:
    length: int
    encode: Callable[[bytes], str]


class BytesGenerator(Generator):
    """Emit ``length`` random bytes encoded as hex / base64 / base32."""

    type_name = "bytes"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> BytesSpec:
        length = coerce_int(spec, "length", type_name="bytes", default=16)
        if length < 1:
            raise ValueError("bytes 'length' must be >= 1")
        encoding = str(spec.get("encoding", "hex"))
        if encoding not in _ENCODERS:
            raise ValueError(
                f"bytes 'encoding' must be one of {sorted(_ENCODERS)} (got {encoding!r})"
            )
        return BytesSpec(length=length, encode=_ENCODERS[encoding])

    def generate(self, prepared: BytesSpec, rng: Random) -> str:
        remaining = prepared.length
        chunks: list[str] = []
        while remaining:
            size = min(remaining, _ENCODING_CHUNK_BYTES)
            chunks.append(prepared.encode(rng.randbytes(size)))
            remaining -= size
        return "".join(chunks)
