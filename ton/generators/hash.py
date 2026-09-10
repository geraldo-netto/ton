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

from .._proof import ProofResult
from .._transforms import TransformResult
from ._md4 import md4 as _pure_md4
from .base import PairedGenerator, coerce_bool, coerce_int, proof_result, require_string_tuple


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
BCRYPT_MAX_ROUNDS = 31


@dataclass(frozen=True)
class BcryptPairSpec:
    """Validated bcrypt pool with optional operator-controlled caching."""

    words: tuple[str, ...]
    rounds: int
    cache: dict[str, str] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class DigestPairSpec:
    """Validated pool for inexpensive deterministic digests."""

    words: tuple[str, ...]
    algorithm: str


class HashGenerator(PairedGenerator):
    """Generate ``(plaintext, digest)`` pairs from a fixed word list."""

    type_name = "hash"

    def prepare(
        self, spec: Mapping[str, Any], context: Any = None
    ) -> DigestPairSpec | BcryptPairSpec:
        words = require_string_tuple(spec)
        algorithm = str(spec.get("algorithm", "sha256")).lower()
        if algorithm not in _ALGORITHMS:
            raise ValueError(
                f"hash 'algorithm' must be one of {list(_ALGORITHMS)} (got {algorithm!r})"
            )
        if algorithm == "bcrypt":
            rounds = coerce_int(spec, "rounds", type_name="hash", default=12)
            if not 4 <= rounds <= BCRYPT_MAX_ROUNDS:
                raise ValueError("hash 'rounds' must be between 4 and 31")
            oversized = next((word for word in words if len(word.encode("utf-8")) > 72), None)
            if oversized is not None:
                raise ValueError("hash bcrypt 'values' entries must be at most 72 UTF-8 bytes")
            _load_bcrypt()
            cache: dict[str, str] | None = (
                {} if coerce_bool(spec, "cache", type_name="hash", default=False) else None
            )
            return BcryptPairSpec(words=words, rounds=rounds, cache=cache)
        for option in ("cache", "rounds"):
            if option in spec:
                raise ValueError(f"hash {option!r} is supported only for the bcrypt algorithm")
        return DigestPairSpec(words=words, algorithm=algorithm)

    def generate_pair(
        self, prepared: DigestPairSpec | BcryptPairSpec, rng: Random
    ) -> tuple[str, str]:
        if isinstance(prepared, BcryptPairSpec):
            plaintext = rng.choice(prepared.words)
            return plaintext, _bcrypt_digest_cached(prepared, plaintext)
        plaintext = rng.choice(prepared.words)
        return plaintext, _digest(prepared.algorithm, plaintext)

    def prove(
        self, prepared: DigestPairSpec | BcryptPairSpec, result: TransformResult
    ) -> ProofResult:
        plaintext = result.id_value
        if plaintext is None or plaintext not in prepared.words:
            return proof_result(False, "hash plaintext is not in 'values'")
        if isinstance(prepared, BcryptPairSpec):
            expected = _bcrypt_digest_cached(prepared, plaintext)
        else:
            expected = _digest(prepared.algorithm, plaintext)
        return proof_result(result.value == expected, "digest does not match plaintext")


def _bcrypt_digest_cached(prepared: BcryptPairSpec, plaintext: str) -> str:
    if prepared.cache is None:
        return _bcrypt_digest(plaintext, prepared.rounds)
    digest = prepared.cache.get(plaintext)
    if digest is None:
        digest = _bcrypt_digest(plaintext, prepared.rounds)
        prepared.cache[plaintext] = digest
    return digest


def _digest(algorithm: str, plaintext: str) -> str:
    if algorithm == "ntlm":
        return _ntlm_digest(plaintext)
    return _HASHERS[algorithm](plaintext.encode("utf-8"))


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
