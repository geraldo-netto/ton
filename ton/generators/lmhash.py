"""LM/NTLM-style hash generator.

Picks a plaintext word from ``values`` and produces the MD4 hash of its
UTF-16LE encoding (the NT hash used by Windows credential storage).

The ``lmhash`` type is *paired*: the rendered row may reference both the
hash (``$word$``) and the plaintext that produced it (``$word[id]$``).
See :class:`ton.generators.base.PairedGenerator` for the contract.
"""

from __future__ import annotations

import binascii
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, Callable

from ._md4 import md4 as _pure_md4
from .base import PairedGenerator, require_string_tuple


def _select_md4_backend() -> Callable[[bytes], bytes]:
    """Pick the MD4 implementation once at import time.

    OpenSSL 3 disables MD4 by default, in which case ``hashlib.new('md4')``
    raises ValueError. We probe once and bind the chosen backend so the
    hot path stays free of per-call try/except.
    """
    try:
        hashlib.new("md4", b"").digest()
    except ValueError:
        return _pure_md4
    return lambda data: hashlib.new("md4", data).digest()


_MD4: Callable[[bytes], bytes] = _select_md4_backend()


@dataclass(frozen=True)
class LMHashSpec:
    """Precomputed ``(plaintext, hash)`` pairs.

    Hashing happens once at :meth:`LMHashGenerator.prepare` time
    instead of per-row -- the row hot path is a single ``rng.choice``
    against the precomputed tuple, with no cache eviction risk on
    long-running jobs with large word lists (TODO PERF-009).
    """

    pairs: tuple[tuple[str, str], ...]


class LMHashGenerator(PairedGenerator):
    """Generate (plaintext, NT-hash) pairs from a fixed word list."""

    type_name = "lmhash"

    def prepare(self, spec: Mapping[str, Any]) -> LMHashSpec:
        words = require_string_tuple(spec)
        return LMHashSpec(pairs=tuple((w, self._nt_hash(w)) for w in words))

    def generate_pair(self, prepared: LMHashSpec, rng: Random) -> tuple[str, str]:
        """Return ``(plaintext, hash)`` drawn from the precomputed pool."""
        return rng.choice(prepared.pairs)

    @staticmethod
    def _nt_hash(plaintext: str) -> str:
        """MD4 of the UTF-16LE plaintext (canonical Windows NT hash)."""
        raw = _MD4(plaintext.encode("utf-16le"))
        return binascii.hexlify(raw).decode("ascii")
