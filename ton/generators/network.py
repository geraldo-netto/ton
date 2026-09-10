"""Network identifier generators: IPv4, IPv6, MAC address.

Three separate types share one module since they all draw bytes and
format them.

``ipv4`` / ``ipv6`` spec::

    {
      "type":  "ipv4",
      "cidr":  "10.0.0.0/8"          // optional, default 0.0.0.0/0
    }

``mac`` spec::

    {
      "type":      "mac",
      "separator": ":",              // optional, default ":"
      "uppercase": false,            // optional, default false
      "oui":       "00:1A:2B",       // optional 24-bit prefix
      "invalidProbability": 0        // 0..1 chance of five-octet output
    }
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._scalars import coerce_bool
from .._transforms import TransformResult

# ---------------------------------------------------------------------------
# IPv4 / IPv6
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IPNetworkSpec:
    network_int: int  # first usable address (network address)
    size: int  # number of addresses in the block
    version: int  # 4 or 6


def _prepare_ip(spec: Mapping[str, Any], default_cidr: str, version: int) -> IPNetworkSpec:
    cidr = str(spec.get("cidr", default_cidr))
    network = ipaddress.ip_network(cidr, strict=False)
    if network.version != version:
        raise ValueError(
            f"ip generator expected IPv{version} CIDR, got {cidr!r} (IPv{network.version})"
        )
    return IPNetworkSpec(
        network_int=int(network.network_address),
        size=network.num_addresses,
        version=version,
    )


def _draw_ip(prepared: IPNetworkSpec, rng: Random) -> str:
    offset = rng.randrange(prepared.size) if prepared.size > 1 else 0
    address = prepared.network_int + offset
    if prepared.version == 4:
        return ".".join(str(address >> shift & 0xFF) for shift in (24, 16, 8, 0))
    return socket.inet_ntop(socket.AF_INET6, address.to_bytes(16, "big"))


class IPv4Generator(Generator):
    """Random IPv4 inside a CIDR block (default 0.0.0.0/0)."""

    type_name = "ipv4"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> IPNetworkSpec:
        return _prepare_ip(spec, default_cidr="0.0.0.0/0", version=4)

    def generate(self, prepared: IPNetworkSpec, rng: Random) -> str:
        return _draw_ip(prepared, rng)

    def prove(self, prepared: IPNetworkSpec, result: TransformResult) -> ProofResult:
        return _prove_ip(prepared, result)


class IPv6Generator(Generator):
    """Random IPv6 inside a CIDR block (default ::/0)."""

    type_name = "ipv6"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> IPNetworkSpec:
        return _prepare_ip(spec, default_cidr="::/0", version=6)

    def generate(self, prepared: IPNetworkSpec, rng: Random) -> str:
        return _draw_ip(prepared, rng)

    def prove(self, prepared: IPNetworkSpec, result: TransformResult) -> ProofResult:
        return _prove_ip(prepared, result)


def _prove_ip(prepared: IPNetworkSpec, result: TransformResult) -> ProofResult:
    try:
        address = ipaddress.ip_address(result.value)
    except ValueError:
        return proof_result(False, "value is not an IP address")
    numeric = int(address)
    return proof_result(
        address.version == prepared.version
        and prepared.network_int <= numeric < prepared.network_int + prepared.size,
        "IP address is outside its configured network",
    )


# ---------------------------------------------------------------------------
# MAC address
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MACSpec:
    separator: str
    uppercase: bool
    oui_bytes: bytes | None  # 3-byte prefix or None
    invalid_probability: Fraction


class MACGenerator(Generator):
    """Random 48-bit MAC, with optional five-octet negative-test output."""

    type_name = "mac"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> MACSpec:
        separator = spec.get("separator", ":")
        if not isinstance(separator, str) or separator not in (":", "-", ""):
            raise ValueError("mac 'separator' must be ':', '-', or an empty string")
        oui_value = spec.get("oui")
        oui_bytes = _parse_oui(oui_value) if oui_value is not None else None
        return MACSpec(
            separator=separator,
            uppercase=coerce_bool(spec, "uppercase", type_name="mac", default=False),
            oui_bytes=oui_bytes,
            invalid_probability=_invalid_probability(spec.get("invalidProbability", 0)),
        )

    def generate(self, prepared: MACSpec, rng: Random) -> str:
        octet_count = _mac_octet_count(prepared.invalid_probability, rng)
        prefix = prepared.oui_bytes or b""
        raw = prefix + rng.randbytes(octet_count - len(prefix))
        octets = (f"{byte:02X}" if prepared.uppercase else f"{byte:02x}" for byte in raw)
        return prepared.separator.join(octets)

    def prove(self, prepared: MACSpec, result: TransformResult) -> ProofResult:
        raw = _allowed_mac_bytes(prepared, result.value)
        if raw is None:
            return proof_result(False, "value violates the configured MAC validity distribution")
        value = result.value
        case_ok = value == (value.upper() if prepared.uppercase else value.lower())
        prefix_ok = prepared.oui_bytes is None or raw.startswith(prepared.oui_bytes)
        return proof_result(
            case_ok and prefix_ok,
            "MAC address violates its format or OUI",
        )


def _invalid_probability(value: Any) -> Fraction:
    """Keep decimal and float probabilities exact, without a precision ceiling."""
    message = "mac 'invalidProbability' must be a finite number between 0 and 1"
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(message)
    try:
        probability = Fraction(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    if not 0 <= probability <= 1:
        raise ValueError(message)
    return probability


def _mac_octet_count(probability: Fraction, rng: Random) -> int:
    """Choose five or six octets; endpoints consume no selection randomness."""
    if probability == 0:
        return 6
    if probability == 1:
        return 5
    return 5 if rng.randrange(probability.denominator) < probability.numerator else 6


def _allowed_mac_bytes(prepared: MACSpec, value: str) -> bytes | None:
    for octets, allowed in (
        (6, prepared.invalid_probability < 1),
        (5, prepared.invalid_probability > 0),
    ):
        if allowed:
            raw = _mac_bytes(value, prepared.separator, octets)
            if raw is not None:
                return raw
    return None


def _mac_bytes(value: str, separator: str, octets: int) -> bytes | None:
    compact = _compact_mac(value, separator, octets)
    if compact is None:
        return None
    try:
        raw = bytes.fromhex(compact)
    except ValueError:
        return None
    # fromhex ignores ASCII whitespace, so textual width alone is insufficient.
    return raw if len(raw) == octets else None


def _compact_mac(value: str, separator: str, octets: int) -> str | None:
    if not separator:
        return value if len(value) == 2 * octets else None
    if len(value) != 3 * octets - 1 or any(
        value[index] != separator for index in range(2, len(value), 3)
    ):
        return None
    return "".join(value[index : index + 2] for index in range(0, len(value), 3))


def _parse_oui(value: Any) -> bytes:
    """Parse a 24-bit OUI prefix like '00:1A:2B' or '00-1A-2B' or '001A2B'."""
    if not isinstance(value, str):
        raise ValueError("mac 'oui' must be a string")
    separator = ":" if ":" in value else "-" if "-" in value else ""
    raw = _mac_bytes(value, separator, 3)
    if raw is None:
        raise ValueError(
            "mac 'oui' must be 24 bits (6 hex chars), written as "
            f"AABBCC, AA:BB:CC, or AA-BB-CC (got {value!r})"
        )
    return raw
