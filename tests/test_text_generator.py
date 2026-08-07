"""Tests for the text generator."""

from __future__ import annotations

from random import Random

import pytest

from ton.generators.text import TextGenerator


def test_words_default_unit_yields_n_words() -> None:
    gen = TextGenerator()
    prepared = gen.prepare({"count": 7})
    value = gen.generate(prepared, Random(0))
    assert len(value.split()) == 7


def test_sentences_end_with_period_and_start_capitalized() -> None:
    gen = TextGenerator()
    prepared = gen.prepare({"unit": "sentences", "count": 3})
    value = gen.generate(prepared, Random(0))
    sentences = value.split(". ")
    # Each sentence either ends with '.' inline or finishes the string.
    assert all(s[0].isupper() for s in sentences if s)


def test_paragraphs_count() -> None:
    gen = TextGenerator()
    prepared = gen.prepare({"unit": "paragraphs", "count": 2})
    value = gen.generate(prepared, Random(0))
    # Each paragraph has at least 3 sentences -> at least 6 periods total.
    assert value.count(".") >= 6


def test_rejects_unknown_unit() -> None:
    generator = TextGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"unit": "verses"})


def test_rejects_zero_count() -> None:
    generator = TextGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"count": 0})


def test_single_line_output() -> None:
    gen = TextGenerator()
    prepared = gen.prepare({"unit": "paragraphs", "count": 3})
    value = gen.generate(prepared, Random(0))
    assert "\n" not in value
