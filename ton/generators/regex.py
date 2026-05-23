"""Regex-based string generator.

Spec fields::

    {
      "type":    "regex",
      "pattern": "[A-Z]{3}-\\d{4}"   // any common-subset regex
    }

Supports the regex constructs that show up in fixture/identifier
patterns: literals, character classes (``[abc]``, ``[^abc]``,
``[a-z]``), the standard escapes (``\\d \\w \\s`` and their negations),
quantifiers (``? * + {n} {n,m}``), alternation (``a|b``), and groups
(``(...)``, ``(?:...)``). Unbounded quantifiers (``*`` and ``+``) are
capped at ``MAX_UNBOUNDED_REPEAT`` extra repetitions so generation
always terminates. Anchors (``^``, ``$``, ``\\b``) are accepted and
ignored.

Implementation reuses CPython's internal ``sre_parse`` AST so we
don't ship a hand-written regex parser. The module is private
across Python versions but stable in practice (3.9-3.12 tested).
"""

from __future__ import annotations

import string
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, cast

with warnings.catch_warnings():
    # sre_parse / sre_constants are deprecated on 3.12 but still present;
    # 3.13+ moved them under re._parser / re._constants.
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import sre_constants
        import sre_parse
    except ImportError:  # pragma: no cover - py 3.13+ moved them
        from re import _constants as sre_constants  # type: ignore[attr-defined,no-redef]
        from re import _parser as sre_parse  # type: ignore[attr-defined,no-redef]

from .base import Generator

#: Upper bound on the *extra* repetitions allowed for ``*`` and ``+``.
MAX_UNBOUNDED_REPEAT = 8

#: Upper bound on the literal repeat count in ``{N}`` / ``{N,M}``. Without
#: this cap, ``a{1_000_000}`` quietly produces a million-character row
#: (TODO SCALE-002).
MAX_LITERAL_REPEAT = 10_000

_PRINTABLE_ASCII = tuple(chr(c) for c in range(0x20, 0x7F))
_DIGITS = tuple(string.digits)
_WORD = tuple(string.ascii_letters + string.digits + "_")
_SPACE = tuple(" \t\n\r\f\v")


@dataclass(frozen=True)
class RegexSpec:
    parsed: Any  # sre_parse.SubPattern


class RegexGenerator(Generator):
    """Emit strings matching the supplied regex ``pattern``."""

    type_name = "regex"

    def prepare(self, spec: Mapping[str, Any]) -> RegexSpec:
        pattern = spec.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("regex 'pattern' must be a non-empty string")
        try:
            parsed = sre_parse.parse(pattern)
        except sre_constants.error as exc:
            raise ValueError(f"regex 'pattern' is not a valid regex: {exc}") from exc
        _reject_oversized_repeats(cast(Iterable[tuple[Any, Any]], parsed))
        return RegexSpec(parsed=parsed)

    def generate(self, prepared: RegexSpec, rng: Random) -> str:
        return _emit(prepared.parsed, rng)


# ---------------------------------------------------------------------------
# AST -> string
# ---------------------------------------------------------------------------


def _reject_oversized_repeats(seq: Iterable[tuple[Any, Any]]) -> None:
    """Walk the AST and reject any literal ``{lo,hi}`` whose ``lo`` (or
    finite ``hi``) exceeds :data:`MAX_LITERAL_REPEAT` (TODO SCALE-002)."""
    for op, arg in seq:
        if op in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT):
            lo, hi, sub = arg
            bounded_hi = hi if hi != sre_constants.MAXREPEAT else lo
            if max(lo, bounded_hi) > MAX_LITERAL_REPEAT:
                raise ValueError(
                    "regex 'pattern' literal repeat exceeds "
                    f"MAX_LITERAL_REPEAT ({MAX_LITERAL_REPEAT})"
                )
            _reject_oversized_repeats(sub)
        elif op is sre_constants.BRANCH:
            for alt in arg[1]:
                _reject_oversized_repeats(alt)
        elif op is sre_constants.SUBPATTERN:
            _reject_oversized_repeats(arg[3])


def _emit(seq: Iterable[tuple[Any, Any]], rng: Random) -> str:
    parts: list[str] = []
    for op, arg in seq:
        parts.append(_emit_node(op, arg, rng))
    return "".join(parts)


def _emit_node(op: Any, arg: Any, rng: Random) -> str:
    handler = _EMIT_HANDLERS.get(op)
    if handler is None:
        raise ValueError(f"regex generator: unsupported construct {op!r}")
    return handler(arg, rng)


def _emit_literal(arg: Any, rng: Random) -> str:
    return chr(arg)


def _emit_not_literal(arg: Any, rng: Random) -> str:
    return _pick_excluding({chr(arg)}, rng)


def _emit_any(arg: Any, rng: Random) -> str:
    return _pick_excluding({"\n"}, rng)


def _emit_branch(arg: Any, rng: Random) -> str:
    _, alternatives = arg
    return _emit(rng.choice(alternatives), rng)


def _emit_subpattern(arg: Any, rng: Random) -> str:
    # (group, add_flags, del_flags, sub)
    return _emit(arg[3], rng)


def _emit_category(arg: Any, rng: Random) -> str:
    return rng.choice(_category_pool(arg))


def _emit_at(arg: Any, rng: Random) -> str:
    return ""  # anchor, no output


def _emit_range(arg: Any, rng: Random) -> str:
    lo, hi = arg
    return chr(rng.randint(lo, hi))


def _emit_repeat(arg: tuple[int, int, Any], rng: Random) -> str:
    lo, hi, sub = arg
    if hi == sre_constants.MAXREPEAT:
        hi = lo + MAX_UNBOUNDED_REPEAT
    count = rng.randint(lo, hi)
    return "".join(_emit(sub, rng) for _ in range(count))


def _pick_in(items: Iterable[tuple[Any, Any]], rng: Random) -> str:
    item_list = list(items)
    negate = item_list and item_list[0][0] is sre_constants.NEGATE
    if negate:
        item_list = item_list[1:]
    pool = _flatten_in(item_list)
    if negate:
        return _pick_excluding(set(pool), rng)
    if not pool:
        raise ValueError("regex generator: empty character class")
    return rng.choice(pool)


def _flatten_in(items: Iterable[tuple[Any, Any]]) -> list[str]:
    pool: list[str] = []
    for op, arg in items:
        if op is sre_constants.LITERAL:
            pool.append(chr(arg))
        elif op is sre_constants.RANGE:
            lo, hi = arg
            pool.extend(chr(c) for c in range(lo, hi + 1))
        elif op is sre_constants.CATEGORY:
            pool.extend(_category_pool(arg))
        else:
            raise ValueError(f"regex generator: unsupported class element {op!r}")
    return pool


def _pick_excluding(excluded: set[str], rng: Random) -> str:
    pool = [c for c in _PRINTABLE_ASCII if c not in excluded]
    if not pool:
        raise ValueError("regex generator: cannot satisfy negated class")
    return rng.choice(pool)


def _category_pool(category: Any) -> tuple[str, ...]:
    if category is sre_constants.CATEGORY_DIGIT:
        return _DIGITS
    if category is sre_constants.CATEGORY_NOT_DIGIT:
        return tuple(c for c in _PRINTABLE_ASCII if c not in _DIGITS)
    if category is sre_constants.CATEGORY_WORD:
        return _WORD
    if category is sre_constants.CATEGORY_NOT_WORD:
        return tuple(c for c in _PRINTABLE_ASCII if c not in _WORD)
    if category is sre_constants.CATEGORY_SPACE:
        return _SPACE
    if category is sre_constants.CATEGORY_NOT_SPACE:
        return tuple(c for c in _PRINTABLE_ASCII if c not in _SPACE)
    raise ValueError(f"regex generator: unsupported category {category!r}")


#: Dispatch table for _emit_node. Defined after every handler so the
#: dict literal can reference the names directly.
_EMIT_HANDLERS = {
    sre_constants.LITERAL: _emit_literal,
    sre_constants.NOT_LITERAL: _emit_not_literal,
    sre_constants.ANY: _emit_any,
    sre_constants.IN: _pick_in,
    sre_constants.MAX_REPEAT: _emit_repeat,
    sre_constants.MIN_REPEAT: _emit_repeat,
    sre_constants.BRANCH: _emit_branch,
    sre_constants.SUBPATTERN: _emit_subpattern,
    sre_constants.CATEGORY: _emit_category,
    sre_constants.AT: _emit_at,
    sre_constants.RANGE: _emit_range,
}
