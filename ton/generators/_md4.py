"""Pure-Python MD4 fallback (RFC 1320).

OpenSSL 3 disables MD4 in its default provider, so ``hashlib.new("md4", ...)``
fails on most modern Linux distributions. This module is a self-contained
implementation that we fall back to so the lmhash generator keeps working
without optional dependencies.

MD4 is cryptographically broken; we use it here only because the Windows
NT hash format (the entire point of the ``lmhash`` type) is defined as
``MD4(password.encode("utf-16le"))``. Do not use this for anything that
needs security.
"""

from __future__ import annotations

import struct

_MASK32 = 0xFFFFFFFF

_R1_K = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
_R1_S = (3, 7, 11, 19) * 4

_R2_K = (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15)
_R2_S = (3, 5, 9, 13) * 4

_R3_K = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
_R3_S = (3, 9, 11, 15) * 4


def _rl(value: int, bits: int) -> int:
    value &= _MASK32
    return ((value << bits) | (value >> (32 - bits))) & _MASK32


def _f(x: int, y: int, z: int) -> int:
    return (x & y) | ((~x) & _MASK32 & z)


def _g(x: int, y: int, z: int) -> int:
    return (x & y) | (x & z) | (y & z)


def _h(x: int, y: int, z: int) -> int:
    return x ^ y ^ z


def md4(data: bytes) -> bytes:
    """Return the 16-byte MD4 digest of ``data``."""
    msg = bytearray(data)
    bit_length = (len(data) * 8) & 0xFFFFFFFFFFFFFFFF

    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0x00)
    msg += struct.pack("<Q", bit_length)

    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476

    for offset in range(0, len(msg), 64):
        x = list(struct.unpack("<16I", bytes(msg[offset : offset + 64])))
        aa, bb, cc, dd = a, b, c, d

        for k, s in zip(_R1_K, _R1_S):
            a = _rl(a + _f(b, c, d) + x[k], s)
            a, b, c, d = d, a, b, c

        for k, s in zip(_R2_K, _R2_S):
            a = _rl(a + _g(b, c, d) + x[k] + 0x5A827999, s)
            a, b, c, d = d, a, b, c

        for k, s in zip(_R3_K, _R3_S):
            a = _rl(a + _h(b, c, d) + x[k] + 0x6ED9EBA1, s)
            a, b, c, d = d, a, b, c

        a = (a + aa) & _MASK32
        b = (b + bb) & _MASK32
        c = (c + cc) & _MASK32
        d = (d + dd) & _MASK32

    return struct.pack("<4I", a, b, c, d)
