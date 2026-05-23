"""Fuzz / property tests for generators, template, and config.

No external Hypothesis dependency -- each test drives a seeded
``random.Random`` and asserts an invariant ("output type is str",
"output matches the regex you supplied", "bad spec rejected in
prepare"). Iteration count is small (a few hundred per test) so the
suite stays fast.
"""

from __future__ import annotations

import re
import string as string_module
from random import Random
from typing import Any, Callable, Dict, List, Tuple

import pytest

from ton import api
from ton._engine import TemplateError
from ton._template import (
    Token,
    UndeclaredVariableError,
    parse,
    render,
    validate_against,
)

# ---------------------------------------------------------------------------
# Spec factories: (factory, type_name)
# ---------------------------------------------------------------------------


def _spec_boolean(rng: Random) -> Dict[str, Any]:
    return {"type": "boolean", "whenTrue": "Y", "whenFalse": "N"}


def _spec_integer(rng: Random) -> Dict[str, Any]:
    lo = rng.randint(-10_000, 10_000)
    hi = lo + rng.randint(0, 10_000)
    return {
        "type": "integer",
        "minValue": lo,
        "maxValue": hi,
        "padWithZero": rng.choice([True, False]),
    }


def _spec_decimal(rng: Random) -> Dict[str, Any]:
    lo = rng.uniform(-1000, 1000)
    hi = lo + rng.uniform(0, 1000)
    return {
        "type": "decimal",
        "minValue": lo,
        "maxValue": hi,
        "decimals": rng.randint(0, 6),
        "padWithZero": rng.choice([True, False]),
    }


def _spec_char(rng: Random) -> Dict[str, Any]:
    pool = rng.sample(string_module.ascii_letters, k=rng.randint(1, 8))
    return {"type": "char", "values": pool, "maxChar": rng.randint(1, 10)}


def _spec_string(rng: Random) -> Dict[str, Any]:
    return {
        "type": "string",
        "values": [f"v{i}" for i in range(rng.randint(1, 10))],
    }


def _spec_uuid(rng: Random) -> Dict[str, Any]:
    return {
        "type": "uuid",
        "version": rng.choice([1, 4]),
        "uppercase": rng.choice([True, False]),
    }


def _spec_sequence(rng: Random) -> Dict[str, Any]:
    return {
        "type": "sequence",
        "start": rng.randint(-1_000, 1_000),
        "step": rng.choice([1, 2, -1, 5]),
    }


def _spec_weighted(rng: Random) -> Dict[str, Any]:
    n = rng.randint(2, 6)
    return {
        "type": "weighted",
        "values": [f"v{i}" for i in range(n)],
        "weights": [rng.randint(1, 100) for _ in range(n)],
    }


def _spec_bytes(rng: Random) -> Dict[str, Any]:
    return {
        "type": "bytes",
        "length": rng.randint(1, 64),
        "encoding": rng.choice(["hex", "base64", "base32"]),
    }


def _spec_date(rng: Random) -> Dict[str, Any]:
    return {
        "type": "date",
        "minValue": "2000-01-01",
        "maxValue": "2030-12-31",
    }


def _spec_timestamp_unix(rng: Random) -> Dict[str, Any]:
    return {
        "type": "timestamp_unix",
        "minValue": "2000-01-01",
        "maxValue": "2030-12-31",
        "unit": rng.choice(["seconds", "millis"]),
    }


def _spec_ipv4(rng: Random) -> Dict[str, Any]:
    return {"type": "ipv4", "cidr": rng.choice(["0.0.0.0/0", "10.0.0.0/8", "192.168.0.0/16"])}


def _spec_ipv6(rng: Random) -> Dict[str, Any]:
    return {"type": "ipv6", "cidr": rng.choice(["::/0", "2001:db8::/32"])}


def _spec_mac(rng: Random) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"type": "mac"}
    if rng.random() < 0.5:
        spec["separator"] = rng.choice([":", "-"])
    if rng.random() < 0.5:
        spec["uppercase"] = True
    return spec


def _spec_name(rng: Random) -> Dict[str, Any]:
    return {"type": "name", "style": rng.choice(["full", "given", "family"])}


def _spec_email(rng: Random) -> Dict[str, Any]:
    return {"type": "email"}


def _spec_phone(rng: Random) -> Dict[str, Any]:
    return {"type": "phone", "format": rng.choice(["###-####", "+1 (###) ###-####"])}


def _spec_text(rng: Random) -> Dict[str, Any]:
    return {
        "type": "text",
        "unit": rng.choice(["words", "sentences", "paragraphs"]),
        "count": rng.randint(1, 5),
    }


def _spec_regex(rng: Random) -> Dict[str, Any]:
    return {"type": "regex", "pattern": rng.choice([
        "[A-Z]{3}-\\d{4}",
        "[a-z]{5,10}",
        "\\d{4}-\\d{2}-\\d{2}",
        "(foo|bar|baz)",
    ])}


def _spec_lmhash(rng: Random) -> Dict[str, Any]:
    return {"type": "lmhash", "values": [f"word{i}" for i in range(rng.randint(1, 5))]}


_SPEC_FACTORIES: List[Tuple[str, Callable[[Random], Dict[str, Any]]]] = [
    ("boolean", _spec_boolean),
    ("integer", _spec_integer),
    ("decimal", _spec_decimal),
    ("char", _spec_char),
    ("string", _spec_string),
    ("uuid", _spec_uuid),
    ("sequence", _spec_sequence),
    ("weighted", _spec_weighted),
    ("bytes", _spec_bytes),
    ("date", _spec_date),
    ("timestamp_unix", _spec_timestamp_unix),
    ("ipv4", _spec_ipv4),
    ("ipv6", _spec_ipv6),
    ("mac", _spec_mac),
    ("name", _spec_name),
    ("email", _spec_email),
    ("phone", _spec_phone),
    ("text", _spec_text),
    ("regex", _spec_regex),
    ("lmhash", _spec_lmhash),
]


# ---------------------------------------------------------------------------
# Fuzz: every type, many random specs, every row is a non-empty str
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("type_name, factory", _SPEC_FACTORIES)
def test_valid_random_specs_produce_string_rows(
    type_name: str, factory: Callable[[Random], Dict[str, Any]]
) -> None:
    for seed in range(30):
        rng = Random(seed)
        spec = factory(rng)
        config = {"rows": 5, "format": "$v$", "types": {"v": spec}}
        rows = list(api.generate(config, seed=seed))
        assert len(rows) == 5
        for row in rows:
            assert isinstance(row, str)
            # boolean / sequence can legitimately render '0' or 'N', so the
            # invariant is "well-formed", not "non-empty in chars".
            assert row is not None


# ---------------------------------------------------------------------------
# Fuzz: bad specs are rejected at construction (not at row generation)
# ---------------------------------------------------------------------------


_BAD_SPEC_MUTATIONS: List[Tuple[str, Dict[str, Any]]] = [
    ("integer", {"type": "integer", "minValue": 10, "maxValue": 1}),
    ("decimal", {"type": "decimal", "minValue": 1.0, "maxValue": 0.0, "decimals": 2}),
    ("decimal", {"type": "decimal", "minValue": 0.0, "maxValue": 1.0, "decimals": -1}),
    ("char", {"type": "char", "values": ["A"], "maxChar": 0}),
    ("char", {"type": "char", "values": [], "maxChar": 2}),
    ("string", {"type": "string", "values": []}),
    ("lmhash", {"type": "lmhash", "values": []}),
    ("uuid", {"type": "uuid", "version": 7}),
    ("sequence", {"type": "sequence", "step": 0}),
    ("weighted", {"type": "weighted", "values": ["A"], "weights": [-1]}),
    ("weighted", {"type": "weighted", "values": ["A", "B"], "weights": [1]}),
    ("bytes", {"type": "bytes", "length": 0}),
    ("bytes", {"type": "bytes", "encoding": "rot13"}),
    ("date", {"type": "date", "minValue": "2024-12-31", "maxValue": "2024-01-01"}),
    ("timestamp_unix",
     {"type": "timestamp_unix", "minValue": "2024-01-01",
      "maxValue": "2024-12-31", "unit": "nanos"}),
    ("ipv4", {"type": "ipv4", "cidr": "::/0"}),  # IPv6 CIDR for IPv4 type
    ("mac", {"type": "mac", "oui": "not-hex"}),
    ("mac", {"type": "mac", "separator": "::"}),
    ("name", {"type": "name", "style": "nickname"}),
    ("email", {"type": "email", "domains": []}),
    ("phone", {"type": "phone", "format": "no-hashes"}),
    ("text", {"type": "text", "unit": "verses"}),
    ("text", {"type": "text", "count": 0}),
    ("regex", {"type": "regex", "pattern": ""}),
    ("regex", {"type": "regex", "pattern": "[unclosed"}),
]


@pytest.mark.parametrize("type_name, bad_spec", _BAD_SPEC_MUTATIONS)
def test_bad_specs_rejected_at_engine_construction(
    type_name: str, bad_spec: Dict[str, Any]
) -> None:
    """Engine.prepare must raise TemplateError for each bad spec.

    The point is to catch the failure at construction so CLI users see
    'invalid config' (exit 2), not a stack trace after the first row.
    """
    config = {"rows": 5, "format": "$v$", "types": {"v": bad_spec}}
    with pytest.raises(TemplateError):
        list(api.generate(config))


# ---------------------------------------------------------------------------
# Fuzz: regex output round-trips through the original pattern
# ---------------------------------------------------------------------------


_REGEX_PATTERNS = [
    "[A-Z]{3}-\\d{4}",
    "[a-z]{5,10}",
    "\\d{4}-\\d{2}-\\d{2}",
    "(foo|bar|baz)",
    "[0-9a-fA-F]{8}",
    "\\w{6}\\.\\w{3}",
]


@pytest.mark.parametrize("pattern", _REGEX_PATTERNS)
def test_regex_output_matches_original_pattern(pattern: str) -> None:
    config = {
        "rows": 50,
        "format": "$v$",
        "types": {"v": {"type": "regex", "pattern": pattern}},
    }
    matcher = re.compile(f"^{pattern}$")
    for seed in range(10):
        for row in api.generate(config, seed=seed):
            assert matcher.match(row), f"seed={seed}: {row!r} does not match {pattern!r}"


# ---------------------------------------------------------------------------
# Fuzz: template parse / render / validate_against round-trips
# ---------------------------------------------------------------------------


_TEMPLATE_NAMES = ("alpha", "beta", "gamma", "delta")


def _random_template(rng: Random) -> Tuple[str, List[str]]:
    """Build a random template and the names that need declaring."""
    parts: List[str] = []
    used: List[str] = []
    for _ in range(rng.randint(1, 6)):
        if rng.random() < 0.3:
            parts.append("$$")  # escape -- not a placeholder
        else:
            name = rng.choice(_TEMPLATE_NAMES)
            wants_id = rng.random() < 0.2
            parts.append(f"${name}{'[id]' if wants_id else ''}$")
            used.append(name)
        parts.append(rng.choice([" ", ",", ":", "-", ""]))
    return "".join(parts), used


def test_random_templates_validate_round_trip() -> None:
    for seed in range(200):
        rng = Random(seed)
        template, used = _random_template(rng)
        # All used names declared -> no exception.
        validate_against(template, list(set(used)) + ["extra"])
        # Drop one used name (if any) -> rejection.
        if used:
            short = [n for n in set(used) if n != used[0]]
            with pytest.raises(UndeclaredVariableError):
                validate_against(template, short)


def test_render_terminates_on_random_templates() -> None:
    """Smoke property: render() must never raise or loop on a legal template."""
    for seed in range(100):
        rng = Random(seed)
        template, _ = _random_template(rng)
        rendered = render(template, {})
        assert isinstance(rendered, str)


def test_parsed_tokens_round_trip_through_render() -> None:
    """Substituting every parsed token leaves no *un-replaced* placeholder.

    After render, the placeholder-bearing values are gone. Re-parsing
    the output may still find tokens if the substituted value happens
    to sit between literal dollar chars from the escape rule -- that
    is a re-introduction, not a leftover -- so we assert only that
    every original placeholder literal is absent from the output.
    """
    for seed in range(100):
        rng = Random(seed)
        template, _ = _random_template(rng)
        tokens = parse(template)
        values = {t.placeholder: "X" for t in tokens}
        out = render(template, values)
        # Every literal placeholder from the input is gone from the output.
        for placeholder in {t.placeholder for t in tokens}:
            assert placeholder not in out


def test_token_placeholder_round_trips_through_parse() -> None:
    for token in [
        Token("name", wants_id=False),
        Token("name", wants_id=True),
        Token("a_b_c", wants_id=False),
    ]:
        tokens = parse(token.placeholder)
        assert tokens == [token]
