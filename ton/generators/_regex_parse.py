"""Small in-house regex parser for the ``regex`` generator (DEP-001).

Replaces the dependency on CPython's private ``sre_parse`` /
``sre_constants`` (which carry no compatibility guarantee and moved to
``re._parser`` / ``re._constants`` on 3.13) with a vendored
recursive-descent parser over the supported common subset:

* literals and the ``.`` any-char,
* character classes ``[abc]`` / ``[^abc]`` / ``[a-z]``,
* the ``\\d \\w \\s`` escapes and their negations,
* quantifiers ``? * + {n} {n,m} {n,}`` (with lazy ``?`` suffix),
* alternation ``a|b`` and groups ``(...)`` / ``(?:...)``,
* anchors ``^ $ \\b`` (accepted and ignored).

Nodes are ``(op, arg)`` tuples whose shapes match what the emitter in
:mod:`ton.generators.regex` consumes, so the emit/flatten/expansion code
is unchanged.
"""

from __future__ import annotations

import enum
import re
from typing import Any


class RegexParseError(ValueError):
    """Raised when a pattern is outside the supported regex subset."""


class Op(enum.Enum):
    LITERAL = "literal"
    NOT_LITERAL = "not_literal"
    ANY = "any"
    IN = "in"
    BRANCH = "branch"
    SUBPATTERN = "subpattern"
    MAX_REPEAT = "max_repeat"
    MIN_REPEAT = "min_repeat"
    CATEGORY = "category"
    AT = "at"
    RANGE = "range"
    NEGATE = "negate"


class Category(enum.Enum):
    DIGIT = "digit"
    NOT_DIGIT = "not_digit"
    WORD = "word"
    NOT_WORD = "not_word"
    SPACE = "space"
    NOT_SPACE = "not_space"


# Public aliases mirroring the sre_constants names the emitter used.
LITERAL = Op.LITERAL
NOT_LITERAL = Op.NOT_LITERAL
ANY = Op.ANY
IN = Op.IN
BRANCH = Op.BRANCH
SUBPATTERN = Op.SUBPATTERN
MAX_REPEAT = Op.MAX_REPEAT
MIN_REPEAT = Op.MIN_REPEAT
CATEGORY = Op.CATEGORY
AT = Op.AT
RANGE = Op.RANGE
NEGATE = Op.NEGATE

CATEGORY_DIGIT = Category.DIGIT
CATEGORY_NOT_DIGIT = Category.NOT_DIGIT
CATEGORY_WORD = Category.WORD
CATEGORY_NOT_WORD = Category.NOT_WORD
CATEGORY_SPACE = Category.SPACE
CATEGORY_NOT_SPACE = Category.NOT_SPACE

#: Sentinel for an open-ended upper repeat bound (``*``, ``+``, ``{n,}``).
MAXREPEAT = object()

_CATEGORY_ESCAPES = {
    "d": CATEGORY_DIGIT,
    "D": CATEGORY_NOT_DIGIT,
    "w": CATEGORY_WORD,
    "W": CATEGORY_NOT_WORD,
    "s": CATEGORY_SPACE,
    "S": CATEGORY_NOT_SPACE,
}
_CONTROL_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
    "0": "\0",
}
_BRACE_RE = re.compile(r"\{(\d+)(,(\d*))?\}")
MAX_GROUP_NESTING = 100

Node = tuple[Any, Any]


def parse(pattern: str) -> list[Node]:
    """Parse ``pattern`` into a list of ``(op, arg)`` nodes."""
    parser = _Parser(pattern)
    nodes = parser.parse_alternation()
    if parser.pos != len(parser.text):
        raise RegexParseError(f"unbalanced parenthesis at position {parser.pos}")
    return nodes


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.group_depth = 0

    def _peek(self) -> str | None:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def parse_alternation(self) -> list[Node]:
        alternatives = [self.parse_concat()]
        while self._peek() == "|":
            self.pos += 1
            alternatives.append(self.parse_concat())
        if len(alternatives) == 1:
            return alternatives[0]
        return [(BRANCH, (None, alternatives))]

    def parse_concat(self) -> list[Node]:
        nodes: list[Node] = []
        while True:
            char = self._peek()
            if char is None or char in "|)":
                break
            nodes.append(self._parse_quantified())
        return nodes

    def _parse_quantified(self) -> Node:
        atom = self._parse_atom()
        return self._apply_quantifier(atom)

    def _parse_atom(self) -> Node:
        char = self.text[self.pos]
        if char == "(":
            return self._parse_group()
        if char == "[":
            return self._parse_class()
        if char == "\\":
            return self._parse_escape(in_class=False)
        if char == ".":
            self.pos += 1
            return (ANY, None)
        if char in "^$":
            self.pos += 1
            return (AT, char)
        if char in "*+?":
            raise RegexParseError(f"nothing to repeat at position {self.pos}")
        self.pos += 1
        return (LITERAL, ord(char))

    def _apply_quantifier(self, atom: Node) -> Node:
        bounds = self._read_quantifier()
        if bounds is None:
            return atom
        lo, hi = bounds
        op = MAX_REPEAT
        if self._peek() == "?":  # lazy quantifier; same expansion semantics
            self.pos += 1
            op = MIN_REPEAT
        return (op, (lo, hi, [atom]))

    def _read_quantifier(self) -> tuple[int, Any] | None:
        char = self._peek()
        if char == "*":
            self.pos += 1
            return (0, MAXREPEAT)
        if char == "+":
            self.pos += 1
            return (1, MAXREPEAT)
        if char == "?":
            self.pos += 1
            return (0, 1)
        if char == "{":
            return self._read_brace()
        return None

    def _read_brace(self) -> tuple[int, Any] | None:
        match = _BRACE_RE.match(self.text, self.pos)
        if match is None:
            return None  # a bare '{' is a literal, handled as an atom
        lo = int(match.group(1))
        if match.group(2) is None:
            hi: Any = lo
        elif match.group(3) == "":
            hi = MAXREPEAT
        else:
            hi = int(match.group(3))
        if hi is not MAXREPEAT and hi < lo:
            raise RegexParseError("min repeat greater than max repeat")
        self.pos = match.end()
        return (lo, hi)

    def _parse_group(self) -> Node:
        self.pos += 1  # consume '('
        if self.group_depth >= MAX_GROUP_NESTING:
            raise RegexParseError(f"group nesting exceeds MAX_GROUP_NESTING ({MAX_GROUP_NESTING})")
        self.group_depth += 1
        try:
            if self.text[self.pos : self.pos + 2] == "?:":
                self.pos += 2
            elif self._peek() == "?":
                raise RegexParseError("unsupported group extension")
            sub = self.parse_alternation()
            if self._peek() != ")":
                raise RegexParseError("missing ), unterminated subpattern")
            self.pos += 1
            return (SUBPATTERN, (None, 0, 0, sub))
        finally:
            self.group_depth -= 1

    def _parse_class(self) -> Node:
        self.pos += 1  # consume '['
        items: list[Node] = []
        if self._peek() == "^":
            self.pos += 1
            items.append((NEGATE, None))
        while True:
            char = self._peek()
            if char is None:
                raise RegexParseError("unterminated character set")
            if char == "]":
                self.pos += 1
                return (IN, items)
            items.append(self._parse_class_member())

    def _parse_class_member(self) -> Node:
        item = self._parse_class_atom()
        if (
            item[0] is LITERAL
            and self._peek() == "-"
            and self.text[self.pos + 1 : self.pos + 2]
            not in (
                "]",
                "",
            )
        ):
            self.pos += 1  # consume '-'
            hi = self._parse_class_atom()
            if hi[0] is not LITERAL:
                raise RegexParseError("bad character range")
            return (RANGE, (item[1], hi[1]))
        return item

    def _parse_class_atom(self) -> Node:
        if self.text[self.pos] == "\\":
            return self._parse_escape(in_class=True)
        char = self.text[self.pos]
        self.pos += 1
        return (LITERAL, ord(char))

    def _parse_escape(self, *, in_class: bool) -> Node:
        if self.pos + 1 >= len(self.text):
            raise RegexParseError("bad escape (end of pattern)")
        nxt = self.text[self.pos + 1]
        self.pos += 2
        if nxt in _CATEGORY_ESCAPES:
            return (CATEGORY, _CATEGORY_ESCAPES[nxt])
        if nxt == "b":
            # word-boundary anchor outside a class; backspace inside one.
            return (LITERAL, 0x08) if in_class else (AT, "b")
        if nxt in _CONTROL_ESCAPES:
            return (LITERAL, ord(_CONTROL_ESCAPES[nxt]))
        return (LITERAL, ord(nxt))
