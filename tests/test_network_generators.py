"""Tests for the ipv4 / ipv6 / mac generators."""

from __future__ import annotations

import ipaddress
import re
from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.network import (
    IPv4Generator,
    IPv6Generator,
    MACGenerator,
)


def test_ipv4_default_range_returns_valid_address() -> None:
    gen = IPv4Generator()
    prepared = gen.prepare({})
    value = gen.generate(prepared, Random(0))
    assert isinstance(ipaddress.IPv4Address(value), ipaddress.IPv4Address)


def test_ipv4_respects_cidr() -> None:
    gen = IPv4Generator()
    prepared = gen.prepare({"cidr": "10.0.0.0/24"})
    rng = Random(0)
    for _ in range(20):
        value = gen.generate(prepared, rng)
        assert ipaddress.IPv4Address(value) in ipaddress.IPv4Network("10.0.0.0/24")


def test_single_address_cidrs_format_without_a_draw() -> None:
    assert IPv4Generator().generate(
        IPv4Generator().prepare({"cidr": "192.0.2.1/32"}), Random(0)
    ) == ("192.0.2.1")
    assert IPv6Generator().generate(
        IPv6Generator().prepare({"cidr": "2001:db8::/128"}), Random(0)
    ) == ("2001:db8::")


def test_ipv4_rejects_ipv6_cidr() -> None:
    generator = IPv4Generator()
    with pytest.raises(ValueError):
        generator.prepare({"cidr": "::/0"})


def test_ipv6_respects_cidr() -> None:
    gen = IPv6Generator()
    prepared = gen.prepare({"cidr": "2001:db8::/32"})
    value = gen.generate(prepared, Random(0))
    assert ipaddress.IPv6Address(value) in ipaddress.IPv6Network("2001:db8::/32")


def test_mac_format_default_separator() -> None:
    gen = MACGenerator()
    prepared = gen.prepare({})
    value = gen.generate(prepared, Random(0))
    assert re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", value)


def test_mac_uppercase_and_dash_separator() -> None:
    gen = MACGenerator()
    prepared = gen.prepare({"separator": "-", "uppercase": True})
    value = gen.generate(prepared, Random(0))
    assert re.fullmatch(r"([0-9A-F]{2}-){5}[0-9A-F]{2}", value)


def test_mac_oui_prefix_enforced() -> None:
    gen = MACGenerator()
    prepared = gen.prepare({"oui": "00:1A:2B"})
    value = gen.generate(prepared, Random(0))
    assert value.startswith("00:1a:2b:")


def test_mac_rejects_bad_oui() -> None:
    generator = MACGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"oui": "not-hex"})


def test_mac_rejects_multichar_separator() -> None:
    generator = MACGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"separator": "::"})


@pytest.mark.parametrize(
    "spec",
    [
        {"separator": "a"},
        {"separator": ""},
        {"separator": "a", "uppercase": True, "oui": "AA:BB:CC"},
    ],
)
def test_mac_proof_parses_generated_octets_structurally(spec: dict[str, object]) -> None:
    generator = MACGenerator()
    prepared = generator.prepare(spec)
    value = generator.generate(prepared, Random(0))

    assert generator.prove(prepared, TransformResult(value)).ok


@pytest.mark.parametrize(
    ("separator", "value"),
    [
        (":", "00:11:22:33:44"),
        (":", "00:11:22:33:44:5g"),
        (":", "00-11:22:33:44:55"),
        ("a", "00a11a22a33a44b55"),
        ("", "00112233445566"),
    ],
)
def test_mac_proof_rejects_malformed_layout(separator: str, value: str) -> None:
    generator = MACGenerator()
    prepared = generator.prepare({"separator": separator})

    assert not generator.prove(prepared, TransformResult(value)).ok
