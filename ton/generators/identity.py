"""Name / email / phone generators (lightweight, no external faker).

Three independent types sharing built-in word lists from
:mod:`._identity_data`. Callers needing locale-specific data should
register a custom generator via the ``ton.generators`` entry point.

``name`` spec::

    {
      "type":  "name",
      "style": "full"            // full (default) | given | family
    }

``email`` spec::

    {
      "type":    "email",
      "domains": ["example.com"]  // optional override; default mix
    }

``phone`` spec::

    {
      "type":   "phone",
      "format": "+1 (###) ###-####"   // '#' is one decimal digit
    }
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._scalars import require_string_tuple
from .._transforms import TransformResult
from ._identity_data import EMAIL_DOMAINS, FAMILY_NAMES, GIVEN_NAMES

_LOWER_GIVEN_NAMES = frozenset(name.lower() for name in GIVEN_NAMES)
_LOWER_FAMILY_NAMES = frozenset(name.lower() for name in FAMILY_NAMES)

# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

_NAME_STYLES = ("full", "given", "family")


@dataclass(frozen=True)
class NameSpec:
    style: str


class NameGenerator(Generator):
    """Random person name from built-in given/family pools."""

    type_name = "name"
    config_keys = frozenset(("style",))

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> NameSpec:
        style = str(spec.get("style", "full"))
        if style not in _NAME_STYLES:
            raise ValueError(f"name 'style' must be one of {_NAME_STYLES} (got {style!r})")
        return NameSpec(style=style)

    def generate(self, prepared: NameSpec, rng: Random) -> str:
        if prepared.style == "given":
            return rng.choice(GIVEN_NAMES)
        if prepared.style == "family":
            return rng.choice(FAMILY_NAMES)
        return f"{rng.choice(GIVEN_NAMES)} {rng.choice(FAMILY_NAMES)}"

    def prove(self, prepared: NameSpec, result: TransformResult) -> ProofResult:
        if prepared.style == "given":
            valid = result.value in GIVEN_NAMES
        elif prepared.style == "family":
            valid = result.value in FAMILY_NAMES
        else:
            given, separator, family = result.value.partition(" ")
            valid = bool(separator and given in GIVEN_NAMES and family in FAMILY_NAMES)
        return proof_result(valid, "value is not a configured name")


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailSpec:
    domains: tuple[str, ...]


class EmailGenerator(Generator):
    """Random ``<given>.<family>@<domain>`` style email."""

    type_name = "email"
    config_keys = frozenset(("domains",))

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> EmailSpec:
        if "domains" not in spec:
            return EmailSpec(domains=tuple(EMAIL_DOMAINS))
        domains = require_string_tuple(spec, key="domains")
        for domain in domains:
            _validate_email_domain(domain)
        return EmailSpec(domains=domains)

    def generate(self, prepared: EmailSpec, rng: Random) -> str:
        local = f"{rng.choice(GIVEN_NAMES).lower()}.{rng.choice(FAMILY_NAMES).lower()}"
        return f"{local}@{rng.choice(prepared.domains)}"

    def prove(self, prepared: EmailSpec, result: TransformResult) -> ProofResult:
        local, separator, domain = result.value.rpartition("@")
        given, dot, family = local.partition(".")
        valid = bool(
            separator
            and dot
            and given in _LOWER_GIVEN_NAMES
            and family in _LOWER_FAMILY_NAMES
            and domain in prepared.domains
        )
        return proof_result(valid, "value is not a configured email")


# ---------------------------------------------------------------------------
# phone
# ---------------------------------------------------------------------------


def _validate_email_domain(domain: str) -> None:
    """Validate DNS label syntax while preserving the configured spelling."""
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"email domain {domain!r} is not a valid domain") from exc
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    if re.fullmatch(rf"{label}(?:\.{label})*", ascii_domain) is None:
        raise ValueError(f"email domain {domain!r} is not a valid domain")


@dataclass(frozen=True)
class PhoneSpec:
    segments: tuple[str, ...]


_DIGITS = "0123456789"


class PhoneGenerator(Generator):
    """Render a phone number by replacing ``#`` in ``format`` with a digit."""

    type_name = "phone"
    config_keys = frozenset(("format",))

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> PhoneSpec:
        pattern = str(spec.get("format", "+1 (###) ###-####"))
        if "#" not in pattern:
            raise ValueError("phone 'format' must contain at least one '#'")
        return PhoneSpec(segments=tuple(pattern.split("#")))

    def generate(self, prepared: PhoneSpec, rng: Random) -> str:
        digits = rng.choices(_DIGITS, k=len(prepared.segments) - 1)
        return (
            "".join(
                segment + digit
                for segment, digit in zip(prepared.segments[:-1], digits, strict=True)
            )
            + prepared.segments[-1]
        )

    def prove(self, prepared: PhoneSpec, result: TransformResult) -> ProofResult:
        position = 0
        for segment in prepared.segments[:-1]:
            if not result.value.startswith(segment, position):
                return proof_result(False, "phone literal segment does not match")
            position += len(segment)
            if position >= len(result.value) or result.value[position] not in _DIGITS:
                return proof_result(False, "phone digit does not match")
            position += 1
        valid = result.value[position:] == prepared.segments[-1]
        return proof_result(valid, "phone suffix does not match")
