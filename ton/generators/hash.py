"""Generic digest generator.

Picks a plaintext word from ``values`` and hashes it with a selected
``hashlib`` algorithm. The ``hash`` type is paired: ``$word$`` renders
the digest and ``$word[id]$`` renders the plaintext used for that row.

``lmhash`` remains a separate Windows NT-hash specialty because it uses
MD4 over UTF-16LE input, not the byte-oriented algorithms here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import PairedGenerator, coerce_int, require_string_tuple

_HASHERS: dict[str, Callable[[bytes], str]] = {
    "md5": lambda data: hashlib.md5(data, usedforsecurity=False).hexdigest(),
    "sha1": lambda data: hashlib.sha1(data, usedforsecurity=False).hexdigest(),
    "sha256": lambda data: hashlib.sha256(data).hexdigest(),
    "sha512": lambda data: hashlib.sha512(data).hexdigest(),
}
_ALGORITHMS = tuple(sorted((*_HASHERS, "bcrypt")))
_BCRYPT_ALPHABET = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


@dataclass(frozen=True)
class HashSpec:
    pairs: tuple[tuple[str, str], ...]


class HashGenerator(PairedGenerator):
    """Generate ``(plaintext, digest)`` pairs from a fixed word list."""

    type_name = "hash"

    def prepare(self, spec: Mapping[str, Any]) -> HashSpec:
        words = require_string_tuple(spec)
        algorithm = str(spec.get("algorithm", "sha256")).lower()
        if algorithm not in _ALGORITHMS:
            raise ValueError(
                "hash 'algorithm' must be one of "
                f"{list(_ALGORITHMS)} (got {algorithm!r})"
            )
        if algorithm == "bcrypt":
            rounds = coerce_int(spec, "rounds", type_name="hash", default=12)
            if not 4 <= rounds <= 31:
                raise ValueError("hash 'rounds' must be between 4 and 31")
            return HashSpec(
                pairs=tuple((word, _bcrypt_digest(word, rounds)) for word in words)
            )
        hash_one = _HASHERS[algorithm]
        return HashSpec(
            pairs=tuple((word, hash_one(word.encode("utf-8"))) for word in words)
        )

    def generate_pair(self, prepared: HashSpec, rng: Random) -> tuple[str, str]:
        """Return ``(plaintext, digest)`` drawn from the precomputed pool."""
        return rng.choice(prepared.pairs)


def _bcrypt_digest(plaintext: str, rounds: int) -> str:
    try:
        import bcrypt
    except ImportError as exc:
        raise ValueError(
            "hash algorithm 'bcrypt' requires installing ton[bcrypt]"
        ) from exc
    salt = _bcrypt_salt(plaintext, rounds)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("ascii")


def _bcrypt_salt(plaintext: str, rounds: int) -> bytes:
    raw = hashlib.sha256(plaintext.encode("utf-8")).digest()[:16]
    return f"$2b${rounds:02d}$".encode("ascii") + _bcrypt_base64(raw)


def _bcrypt_base64(raw: bytes) -> bytes:
    out = bytearray()
    index = 0
    while index < len(raw):
        c1 = raw[index]
        index += 1
        out.append(_BCRYPT_ALPHABET[(c1 >> 2) & 0x3F])
        c1 = (c1 & 0x03) << 4
        if index >= len(raw):
            out.append(_BCRYPT_ALPHABET[c1 & 0x3F])
            break
        c2 = raw[index]
        index += 1
        c1 |= (c2 >> 4) & 0x0F
        out.append(_BCRYPT_ALPHABET[c1 & 0x3F])
        c1 = (c2 & 0x0F) << 2
        if index >= len(raw):
            out.append(_BCRYPT_ALPHABET[c1 & 0x3F])
            break
        c2 = raw[index]
        index += 1
        c1 |= (c2 >> 6) & 0x03
        out.append(_BCRYPT_ALPHABET[c1 & 0x3F])
        out.append(_BCRYPT_ALPHABET[c2 & 0x3F])
    return bytes(out[:22])
