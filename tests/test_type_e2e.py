"""End-to-end JSON-driven type tests.

Each ``tests/e2e_configs/<name>.json`` is a real config the engine
can consume. Every row is checked against a type-specific predicate
defined below. Weighted configs additionally pin the observed
distribution to its declared (or default-uniform) weights so a
regression in the sampler is impossible to miss.

Running ``pytest tests/test_type_e2e.py -v`` prints one line per
config file so the per-type coverage is visible at a glance.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import string
import uuid as uuid_mod
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from ton import api

E2E_DIR = Path(__file__).parent / "e2e_configs"
SEED = 1
DISTRIBUTION_SLACK = 0.10  # +/-10pp tolerance on observed vs expected probability


# ---------------------------------------------------------------------------
# Predicates: assertion fn (rows, full_config) -> None
# Each row is already known to be ``str``; predicate may raise AssertionError.
# ---------------------------------------------------------------------------


def _check_boolean(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    allowed = {spec["whenTrue"], spec["whenFalse"]}
    assert all(r in allowed for r in rows)
    counts = Counter(rows)
    # Uniform 50/50 -> each label > 25% of rows for n=200.
    for label in allowed:
        assert counts[label] / len(rows) > 0.25


def _check_integer(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    lo, hi = int(spec["minValue"]), int(spec["maxValue"])
    for r in rows:
        v = int(r)
        assert lo <= v <= hi


def _check_integer_padded(rows: list[str], config: dict[str, Any]) -> None:
    _check_integer(rows, config)
    spec = config["types"]["v"]
    width = max(len(str(spec["minValue"])), len(str(spec["maxValue"])))
    assert all(len(r) == width for r in rows)


def _check_decimal(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    lo, hi = float(spec["minValue"]), float(spec["maxValue"])
    decimals = int(spec["decimals"])
    pattern = re.compile(rf"^-?\d+\.\d{{{decimals}}}$")
    for r in rows:
        assert pattern.match(r), r
        v = float(r)
        assert lo <= v <= hi


def _check_char(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    pool = set(spec["values"])
    max_char = int(spec["maxChar"])
    for r in rows:
        assert len(r) == max_char
        assert set(r) <= pool


def _check_string(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    allowed = set(spec["values"])
    assert all(r in allowed for r in rows)
    # No weights: should be uniform-ish; every value should appear.
    seen = set(rows)
    assert seen == allowed


def _check_weighted_skewed(rows: list[str], config: dict[str, Any]) -> None:
    choices = config["types"]["v"]["choices"]
    values = [choice["spec"]["values"][0] for choice in choices]
    raw_weights = [float(choice["weight"]) for choice in choices]
    total = sum(raw_weights)
    expected = {v: w / total for v, w in zip(values, raw_weights, strict=True)}
    counts = Counter(rows)
    n = len(rows)
    for label, p in expected.items():
        observed = counts[label] / n
        assert abs(observed - p) < DISTRIBUTION_SLACK, (
            f"weighted({label}): observed {observed:.3f}, expected {p:.3f}"
        )


def _check_weighted_uniform_default(rows: list[str], config: dict[str, Any]) -> None:
    """A choice without ``weight`` defaults to uniform: 1/N per entry."""
    values = [choice["spec"]["values"][0] for choice in config["types"]["v"]["choices"]]
    counts = Counter(rows)
    n = len(rows)
    expected = 1 / len(values)
    for v in values:
        observed = counts[v] / n
        assert abs(observed - expected) < DISTRIBUTION_SLACK, (
            f"weighted-uniform({v}): observed {observed:.3f}, expected {expected:.3f}"
        )


def _check_weighted_composite(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    choices = spec["choices"]
    raw_weights = [float(c.get("weight", 1.0)) for c in choices]
    total = sum(raw_weights)
    expected_labels = [c["spec"]["values"][0] for c in choices]
    expected = {label: w / total for label, w in zip(expected_labels, raw_weights, strict=True)}
    counts = Counter(rows)
    n = len(rows)
    for label, p in expected.items():
        observed = counts[label] / n
        assert abs(observed - p) < DISTRIBUTION_SLACK


def _check_oneOf(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    expected_labels = [c["values"][0] for c in spec["choices"]]
    expected = 1 / len(expected_labels)
    counts = Counter(rows)
    n = len(rows)
    for label in expected_labels:
        observed = counts[label] / n
        assert abs(observed - expected) < DISTRIBUTION_SLACK


def _check_sequence_of(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    count = int(spec["count"])
    separator = spec.get("separator", "")
    child = spec["spec"]
    lo, hi = int(child["minValue"]), int(child["maxValue"])
    for r in rows:
        parts = r.split(separator) if separator else [r[i] for i in range(len(r))]
        assert len(parts) == count
        for p in parts:
            v = int(p)
            assert lo <= v <= hi


def _check_date(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    fmt = spec["format"]
    # Compare the components represented by these date/datetime fixture formats.
    lo = datetime.strptime(datetime.fromisoformat(spec["minValue"]).strftime(fmt), fmt)
    hi = datetime.strptime(datetime.fromisoformat(spec["maxValue"]).strftime(fmt), fmt)
    for r in rows:
        parsed = datetime.strptime(r, fmt)
        assert lo <= parsed <= hi


@pytest.mark.parametrize(
    "value", ["2023-12-31 23:59:59", "2024-12-31 00:00:01", "2024-12-31 12:00:00"]
)
def test_date_oracle_rejects_values_outside_exact_bounds(value) -> None:
    """REL-045: datetime output cannot extend a midnight upper bound."""
    config = json.loads((E2E_DIR / "date.json").read_text())
    config["types"]["v"]["format"] = "%Y-%m-%d %H:%M:%S"
    _check_date(["2024-01-01 00:00:00", "2024-12-31 00:00:00"], config)
    with pytest.raises(AssertionError):
        _check_date([value], config)


def test_date_oracle_accepts_date_projection_of_datetime_bounds() -> None:
    """REL-045: omitted time components represent the date containing the bound."""
    config = json.loads((E2E_DIR / "date.json").read_text())
    config["types"]["v"].update(minValue="2024-01-01T12:00:00", maxValue="2024-01-02T12:00:00")
    _check_date(["2024-01-01", "2024-01-02"], config)


def _check_timestamp_unix(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    lo_dt = datetime.fromisoformat(spec["minValue"])
    hi_dt = datetime.fromisoformat(spec["maxValue"]).replace(hour=23, minute=59, second=59)
    lo = int(lo_dt.timestamp())
    hi = int(hi_dt.timestamp())
    multiplier = 1 if spec.get("unit", "seconds") == "seconds" else 1000
    for r in rows:
        v = int(r) // multiplier
        # Date-only bounds are interpreted as UTC midnight; allow a one-day
        # window of slack on each side for local-timezone interpretation.
        assert lo - 86400 <= v <= hi + 86400, r


def _check_uuid(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    expected_version = int(spec.get("version", 4))
    for r in rows:
        parsed = uuid_mod.UUID(r)
        assert parsed.version == expected_version


def _check_sequence(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    start = int(spec.get("start", 0))
    step = int(spec.get("step", 1))
    for i, r in enumerate(rows):
        assert int(r) == start + i * step


def _check_bytes(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    length = int(spec["length"])
    if spec.get("encoding", "hex") == "hex":
        for r in rows:
            assert len(r) == 2 * length
            assert all(c in string.hexdigits for c in r)


def _check_ipv4(rows: list[str], config: dict[str, Any]) -> None:
    network = ipaddress.IPv4Network(config["types"]["v"]["cidr"], strict=False)
    for r in rows:
        assert ipaddress.IPv4Address(r) in network


def _check_ipv6(rows: list[str], config: dict[str, Any]) -> None:
    network = ipaddress.IPv6Network(config["types"]["v"]["cidr"], strict=False)
    for r in rows:
        assert ipaddress.IPv6Address(r) in network


def _check_mac(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    oui = spec["oui"].replace(":", "").replace("-", "").lower()
    pattern = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    for r in rows:
        assert pattern.match(r), r
        prefix = r.replace(":", "")[:6].lower()
        assert prefix == oui


def _check_name(rows: list[str], config: dict[str, Any]) -> None:
    for r in rows:
        parts = r.split(" ")
        assert len(parts) == 2
        assert all(parts)


def _check_email(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    domains = set(spec.get("domains", []))
    pattern = re.compile(r"^[a-z]+\.[a-z]+@[a-z.]+$")
    for r in rows:
        assert pattern.match(r), r
        local, domain = r.split("@")
        if domains:
            assert domain in domains


def _check_phone(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    template = spec["format"]
    pattern = re.escape(template).replace(r"\#", r"\d")
    matcher = re.compile(f"^{pattern}$")
    for r in rows:
        assert matcher.match(r), r


def _check_text(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["v"]
    count = int(spec["count"])
    for r in rows:
        # Single-line output; words separated by single spaces.
        words = r.split(" ")
        assert len(words) == count


def _check_regex(rows: list[str], config: dict[str, Any]) -> None:
    pattern = config["types"]["v"]["pattern"]
    matcher = re.compile(f"^{pattern}$")
    for r in rows:
        assert matcher.match(r), r


def _check_ntlm(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["word"]
    plain_pool = set(spec["values"])
    hex_pattern = re.compile(r"^[0-9a-f]{32}$")
    seen_pairs: dict[str, str] = {}
    for r in rows:
        plain, hashed = r.split("|")
        assert plain in plain_pool
        assert hex_pattern.match(hashed)
        # Same plaintext always maps to the same hash within and across rows.
        if plain in seen_pairs:
            assert seen_pairs[plain] == hashed
        else:
            seen_pairs[plain] = hashed


def _check_hash(rows: list[str], config: dict[str, Any]) -> None:
    spec = config["types"]["word"]
    plain_pool = set(spec["values"])
    algorithm = spec["algorithm"]
    hex_pattern = re.compile(r"^[0-9a-f]{64}$")
    seen_pairs: dict[str, str] = {}
    for r in rows:
        plain, digest = r.split("|")
        assert plain in plain_pool
        assert hex_pattern.match(digest)
        expected = getattr(hashlib, algorithm)(plain.encode("utf-8")).hexdigest()
        assert digest == expected
        if plain in seen_pairs:
            assert seen_pairs[plain] == digest
        else:
            seen_pairs[plain] = digest


_CHECKERS: dict[str, Callable[[list[str], dict[str, Any]], None]] = {
    "boolean.json": _check_boolean,
    "integer.json": _check_integer,
    "integer_padded.json": _check_integer_padded,
    "decimal.json": _check_decimal,
    "char.json": _check_char,
    "string.json": _check_string,
    "weighted_skewed.json": _check_weighted_skewed,
    "weighted_uniform_default.json": _check_weighted_uniform_default,
    "weighted_composite.json": _check_weighted_composite,
    "oneOf.json": _check_oneOf,
    "sequence_of.json": _check_sequence_of,
    "date.json": _check_date,
    "datetime.json": _check_date,
    "timestamp_unix.json": _check_timestamp_unix,
    "uuid.json": _check_uuid,
    "sequence.json": _check_sequence,
    "bytes.json": _check_bytes,
    "ipv4.json": _check_ipv4,
    "ipv6.json": _check_ipv6,
    "mac.json": _check_mac,
    "name.json": _check_name,
    "email.json": _check_email,
    "phone.json": _check_phone,
    "text.json": _check_text,
    "regex.json": _check_regex,
    "hash.json": _check_hash,
    "ntlm.json": _check_ntlm,
}


def _discovered_files() -> list[str]:
    return sorted(p.name for p in E2E_DIR.glob("*.json"))


def test_every_e2e_config_has_a_checker() -> None:
    """Coverage guard: each JSON file must map to a predicate."""
    missing = set(_discovered_files()) - set(_CHECKERS)
    assert not missing, f"unmapped e2e configs: {sorted(missing)}"


def test_every_builtin_type_has_an_e2e_config() -> None:
    """Coverage guard: each built-in generator type must be exercised."""
    from ton.generators import BUILTIN_GENERATOR_CLASSES

    builtin_types = {cls.type_name for cls in BUILTIN_GENERATOR_CLASSES}
    documented_types: set[str] = set()
    for name in _discovered_files():
        config = json.loads((E2E_DIR / name).read_text())
        for spec in config["types"].values():
            documented_types.add(spec["type"])
    missing = builtin_types - documented_types
    assert not missing, f"types without an e2e config: {sorted(missing)}"


@pytest.mark.parametrize("filename", sorted(_CHECKERS.keys()))
def test_e2e_type(filename: str) -> None:
    config = json.loads((E2E_DIR / filename).read_text())
    rows = list(api.generate(config, seed=SEED))
    assert len(rows) == config["rows"]
    assert all(isinstance(r, str) and r for r in rows)
    _CHECKERS[filename](rows, config)
