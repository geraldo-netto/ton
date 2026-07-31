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

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator, coerce_int, proof_result

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


@dataclass(frozen=True)
class TextSpec:
    unit: str
    count: int


class TextGenerator(Generator):
    """Lorem-style text: ``count`` words / sentences / paragraphs."""

    type_name = "text"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> TextSpec:
        unit = str(spec.get("unit", "words"))
        if unit not in _UNITS:
            raise ValueError(f"text 'unit' must be one of {_UNITS} (got {unit!r})")
        count = coerce_int(spec, "count", type_name="text", default=5)
        if count < 1:
            raise ValueError("text 'count' must be >= 1")
        return TextSpec(unit=unit, count=count)

    def generate(self, prepared: TextSpec, rng: Random) -> str:
        if prepared.unit == "words":
            return _words(prepared.count, rng)
        if prepared.unit == "sentences":
            return " ".join(_sentence(rng) for _ in range(prepared.count))
        return " ".join(_paragraph(rng) for _ in range(prepared.count))

    def prove(self, prepared: TextSpec, result: TransformResult) -> ProofResult:
        if prepared.unit == "words":
            valid = _valid_words(result.value.split(), prepared.count)
        else:
            sentences = result.value.split(". ")
            sentences[-1] = sentences[-1].removesuffix(".")
            sentence_ok = all(_valid_sentence(sentence) for sentence in sentences)
            expected = (
                len(sentences) == prepared.count
                if prepared.unit == "sentences"
                else prepared.count * 3 <= len(sentences) <= prepared.count * 6
            )
            valid = result.value.endswith(".") and sentence_ok and expected
        return proof_result(valid, "value is not valid generated text")


def _words(count: int, rng: Random) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(count))


def _sentence(rng: Random) -> str:
    length = rng.randint(6, 14)
    body = _words(length, rng)
    return body[:1].upper() + body[1:] + "."


def _paragraph(rng: Random) -> str:
    sentences = rng.randint(3, 6)
    return " ".join(_sentence(rng) for _ in range(sentences))


def _valid_words(words: list[str], count: int) -> bool:
    return len(words) == count and all(word.lower() in _WORDS for word in words)


def _valid_sentence(sentence: str) -> bool:
    words = sentence.split()
    return 6 <= len(words) <= 14 and _valid_words(words, len(words))
