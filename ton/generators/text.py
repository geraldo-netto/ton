"""Lorem-style text generator.

Spec fields::

    {
      "type":  "text",
      "unit":  "words" | "sentences" | "paragraphs",   // default: words
      "count": 5
    }

Ships a small built-in word list so the generator stays dependency-free.
Sentence length is randomized in a narrow range; paragraphs contain
several sentences. Output is always a single line (paragraph
separators are spaces, not newlines) so it stays safe inside CSV
fields and other line-oriented sinks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, assert_below_cap, coerce_int

_WORDS: tuple[str, ...] = (
    "lorem",
    "ipsum",
    "dolor",
    "sit",
    "amet",
    "consectetur",
    "adipiscing",
    "elit",
    "sed",
    "do",
    "eiusmod",
    "tempor",
    "incididunt",
    "ut",
    "labore",
    "et",
    "dolore",
    "magna",
    "aliqua",
    "enim",
    "ad",
    "minim",
    "veniam",
    "quis",
    "nostrud",
    "exercitation",
    "ullamco",
    "laboris",
    "nisi",
    "aliquip",
    "ex",
    "ea",
    "commodo",
    "consequat",
    "duis",
    "aute",
    "irure",
    "in",
    "reprehenderit",
    "voluptate",
    "velit",
    "esse",
    "cillum",
    "fugiat",
    "nulla",
    "pariatur",
    "excepteur",
    "sint",
    "occaecat",
    "cupidatat",
    "non",
    "proident",
    "sunt",
    "culpa",
    "qui",
    "officia",
    "deserunt",
    "mollit",
    "anim",
    "id",
    "est",
    "laborum",
)

_UNITS = ("words", "sentences", "paragraphs")

#: Upper bound on ``count``. A misconfigured value of 1e7 paragraphs would
#: blow up memory and stall the pipeline (TODO SCALE-002).
MAX_TEXT_COUNT = 10_000


@dataclass(frozen=True)
class TextSpec:
    unit: str
    count: int


class TextGenerator(Generator):
    """Lorem-style text: ``count`` words / sentences / paragraphs."""

    type_name = "text"

    def prepare(self, spec: Mapping[str, Any]) -> TextSpec:
        unit = str(spec.get("unit", "words"))
        if unit not in _UNITS:
            raise ValueError(f"text 'unit' must be one of {_UNITS} (got {unit!r})")
        count = coerce_int(spec, "count", type_name="text", default=5)
        if count < 1:
            raise ValueError("text 'count' must be >= 1")
        assert_below_cap("text", "count", count, MAX_TEXT_COUNT, "MAX_TEXT_COUNT")
        return TextSpec(unit=unit, count=count)

    def generate(self, prepared: TextSpec, rng: Random) -> str:
        if prepared.unit == "words":
            return _words(prepared.count, rng)
        if prepared.unit == "sentences":
            return " ".join(_sentence(rng) for _ in range(prepared.count))
        return " ".join(_paragraph(rng) for _ in range(prepared.count))


def _words(count: int, rng: Random) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(count))


def _sentence(rng: Random) -> str:
    length = rng.randint(6, 14)
    body = _words(length, rng)
    return body[:1].upper() + body[1:] + "."


def _paragraph(rng: Random) -> str:
    sentences = rng.randint(3, 6)
    return " ".join(_sentence(rng) for _ in range(sentences))
