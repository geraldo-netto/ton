"""Generic digest generator.

Picks a plaintext word from ``values`` and hashes it with a selected
``hashlib`` algorithm. The ``hash`` type is paired: ``$word$`` renders
the digest and ``$word[id]$`` renders the plaintext used for that row.

The ``ntlm`` algorithm produces the Windows NT hash: MD4 over UTF-16LE
plaintext. It is intentionally available only for synthetic fixtures.
"""

from __future__ import annotations

import binascii
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from random import Random
from typing import Any

from ._md4 import md4 as _pure_md4
from .base import PairedWordPoolGenerator, WordPairSpec, coerce_int, require_string_tuple


def _select_md4_backend() -> Callable[[bytes], bytes]:
    """Select an MD4 backend, falling back when OpenSSL disables MD4."""
    try:
        hashlib.new("md4", b"").digest()
    except ValueError:
        return _pure_md4
    return lambda data: hashlib.new("md4", data).digest()


_MD4: Callable[[bytes], bytes] = _select_md4_backend()


def _ntlm_digest(plaintext: str) -> str:
    """Return the canonical Windows NT hash for ``plaintext``."""
    return binascii.hexlify(_MD4(plaintext.encode("utf-16le"))).decode("ascii")


_HASHERS: dict[str, Callable[[bytes], str]] = {
    "md5": lambda data: hashlib.md5(data, usedforsecurity=False).hexdigest(),
    "sha1": lambda data: hashlib.sha1(data, usedforsecurity=False).hexdigest(),
    "sha256": lambda data: hashlib.sha256(data).hexdigest(),
    "sha512": lambda data: hashlib.sha512(data).hexdigest(),
}
_ALGORITHMS = tuple(sorted((*_HASHERS, "bcrypt", "ntlm")))
_BCRYPT_ALPHABET = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
MAX_BCRYPT_ROUNDS = 12


@dataclass(frozen=True)
class BcryptPairSpec:
    """Validated bcrypt pool with digests cached only after selection."""

    words: tuple[str, ...]
    rounds: int
    cache: dict[str, str] = field(default_factory=dict, compare=False, repr=False)


class HashGenerator(PairedWordPoolGenerator):
    """Generate ``(plaintext, digest)`` pairs from a fixed word list."""

    type_name = "hash"

    def prepare(
        self, spec: Mapping[str, Any], context: Any = None
    ) -> WordPairSpec | BcryptPairSpec:
        words = require_string_tuple(spec)
        algorithm = str(spec.get("algorithm", "sha256")).lower()
        if algorithm not in _ALGORITHMS:
            raise ValueError(
                f"hash 'algorithm' must be one of {list(_ALGORITHMS)} (got {algorithm!r})"
            )
        if algorithm == "bcrypt":
            rounds = coerce_int(spec, "rounds", type_name="hash", default=12)
            if not 4 <= rounds <= MAX_BCRYPT_ROUNDS:
                raise ValueError(
                    f"hash 'rounds' must be between 4 and MAX_BCRYPT_ROUNDS ({MAX_BCRYPT_ROUNDS})"
                )
            _load_bcrypt()
            return BcryptPairSpec(words=words, rounds=rounds)
        if algorithm == "ntlm":
            return WordPairSpec(pairs=tuple((word, _ntlm_digest(word)) for word in words))
        hash_one = _HASHERS[algorithm]
        return WordPairSpec(pairs=tuple((word, hash_one(word.encode("utf-8"))) for word in words))

    def generate_pair(
        self, prepared: WordPairSpec | BcryptPairSpec, rng: Random
    ) -> tuple[str, str]:
        if isinstance(prepared, BcryptPairSpec):
            plaintext = rng.choice(prepared.words)
            digest = prepared.cache.get(plaintext)
            if digest is None:
                digest = _bcrypt_digest(plaintext, prepared.rounds)
                prepared.cache[plaintext] = digest
            return plaintext, digest
        return super().generate_pair(prepared, rng)


def _bcrypt_digest(plaintext: str, rounds: int) -> str:
    bcrypt = _load_bcrypt()
    salt = _bcrypt_salt(plaintext, rounds)
    return str(bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("ascii"))


def _load_bcrypt() -> Any:
    try:
        import bcrypt  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise ValueError("hash algorithm 'bcrypt' requires installing ton[bcrypt]") from exc
    return bcrypt


def _bcrypt_salt(plaintext: str, rounds: int) -> bytes:
    # Deterministic fixture salt: this makes seeded TON output reproducible,
    # but it is not real bcrypt per-value salting and must not be used for
    # password storage or security-sensitive hashes.
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
