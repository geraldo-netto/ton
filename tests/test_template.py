"""Unit tests for the template parser and renderer."""

from __future__ import annotations

import pytest

from ton._template import (
    Token,
    UndeclaredVariableError,
    parse,
    render,
    validate_against,
)


def test_parse_extracts_each_placeholder() -> None:
    tokens = parse("$a$-$b$:$c$")
    assert tokens == [
        Token("a", wants_id=False),
        Token("b", wants_id=False),
        Token("c", wants_id=False),
    ]


def test_parse_detects_id_suffix() -> None:
    tokens = parse("$word[id]$ -> $word$")
    assert tokens == [
        Token("word", wants_id=True),
        Token("word", wants_id=False),
    ]


def test_token_placeholder_round_trip() -> None:
    assert Token("x", wants_id=False).placeholder == "$x$"
    assert Token("x", wants_id=True).placeholder == "$x[id]$"


def test_render_substitutes_known_placeholders() -> None:
    out = render("$a$/$b$", {"$a$": "1", "$b$": "2"})
    assert out == "1/2"


def test_render_leaves_unknown_placeholders_untouched() -> None:
    out = render("$a$/$b$", {"$a$": "1"})
    assert out == "1/$b$"


def test_parse_skips_dollar_escape() -> None:
    assert parse("cost: $$5 and $price$") == [Token("price", wants_id=False)]


def test_render_unescapes_dollar() -> None:
    out = render("cost: $$5 and $price$", {"$price$": "99"})
    assert out == "cost: $5 and 99"


def test_render_double_escape_round_trip() -> None:
    out = render("$$$$", {})
    assert out == "$$"


def test_parse_handles_escape_around_placeholder() -> None:
    tokens = parse("$$$name$$$")
    assert tokens == [Token("name", wants_id=False)]
    out = render("$$$name$$$", {"$name$": "X"})
    assert out == "$X$"


def test_validate_against_accepts_declared() -> None:
    validate_against("$a$-$b$", ["a", "b", "extra"])


def test_validate_against_rejects_undeclared() -> None:
    with pytest.raises(UndeclaredVariableError, match="missing"):
        validate_against("$a$-$missing$", ["a"])


def test_validate_against_skips_dollar_escape() -> None:
    # $$ is not a placeholder, so 'missing' isn't a name to declare.
    validate_against("cost: $$5 and $a$", ["a"])


def test_validate_against_treats_id_suffix_as_same_key() -> None:
    # Paired refs $name$ and $name[id]$ resolve to the same declared name.
    validate_against("$word[id]$ -> $word$", ["word"])
