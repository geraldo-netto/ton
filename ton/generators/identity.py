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

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from ._identity_data import EMAIL_DOMAINS, FAMILY_NAMES, GIVEN_NAMES
from .base import Generator, require_string_tuple

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


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailSpec:
    domains: tuple[str, ...]


class EmailGenerator(Generator):
    """Random ``<given>.<family>@<domain>`` style email."""

    type_name = "email"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> EmailSpec:
        if "domains" not in spec:
            return EmailSpec(domains=tuple(EMAIL_DOMAINS))
        return EmailSpec(domains=require_string_tuple(spec, key="domains"))

    def generate(self, prepared: EmailSpec, rng: Random) -> str:
        local = f"{rng.choice(GIVEN_NAMES).lower()}.{rng.choice(FAMILY_NAMES).lower()}"
        return f"{local}@{rng.choice(prepared.domains)}"


# ---------------------------------------------------------------------------
# phone
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhoneSpec:
    segments: tuple[str, ...]


_DIGITS = "0123456789"


class PhoneGenerator(Generator):
    """Render a phone number by replacing ``#`` in ``format`` with a digit."""

    type_name = "phone"

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
