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
      "oui":       "00:1A:2B"        // optional 24-bit prefix
    }
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator

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
    address = ipaddress.ip_address(prepared.network_int + offset)
    return str(address)


class IPv4Generator(Generator):
    """Random IPv4 inside a CIDR block (default 0.0.0.0/0)."""

    type_name = "ipv4"

    def prepare(self, spec: Mapping[str, Any]) -> IPNetworkSpec:
        return _prepare_ip(spec, default_cidr="0.0.0.0/0", version=4)

    def generate(self, prepared: IPNetworkSpec, rng: Random) -> str:
        return _draw_ip(prepared, rng)


class IPv6Generator(Generator):
    """Random IPv6 inside a CIDR block (default ::/0)."""

    type_name = "ipv6"

    def prepare(self, spec: Mapping[str, Any]) -> IPNetworkSpec:
        return _prepare_ip(spec, default_cidr="::/0", version=6)

    def generate(self, prepared: IPNetworkSpec, rng: Random) -> str:
        return _draw_ip(prepared, rng)


# ---------------------------------------------------------------------------
# MAC address
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MACSpec:
    separator: str
    uppercase: bool
    oui_bytes: bytes | None  # 3-byte prefix or None


class MACGenerator(Generator):
    """Random 48-bit MAC, optionally with a fixed OUI prefix."""

    type_name = "mac"

    def prepare(self, spec: Mapping[str, Any]) -> MACSpec:
        separator = str(spec.get("separator", ":"))
        if separator and len(separator) > 1:
            raise ValueError("mac 'separator' must be a single character")
        oui_value = spec.get("oui")
        oui_bytes = _parse_oui(oui_value) if oui_value is not None else None
        return MACSpec(
            separator=separator,
            uppercase=bool(spec.get("uppercase", False)),
            oui_bytes=oui_bytes,
        )

    def generate(self, prepared: MACSpec, rng: Random) -> str:
        if prepared.oui_bytes is not None:
            raw = prepared.oui_bytes + rng.randbytes(3)
        else:
            raw = rng.randbytes(6)
        octets = (f"{byte:02x}" for byte in raw)
        text = prepared.separator.join(octets) if prepared.separator else "".join(octets)
        return text.upper() if prepared.uppercase else text


def _parse_oui(value: Any) -> bytes:
    """Parse a 24-bit OUI prefix like '00:1A:2B' or '00-1A-2B' or '001A2B'."""
    if not isinstance(value, str):
        raise ValueError("mac 'oui' must be a string")
    cleaned = value.replace(":", "").replace("-", "").lower()
    if len(cleaned) != 6:
        raise ValueError(f"mac 'oui' must be 24 bits (6 hex chars), got {value!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"mac 'oui' is not hex: {value!r}") from exc
