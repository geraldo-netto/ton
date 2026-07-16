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

Implementation uses a small vendored parser (:mod:`ton.generators._regex_parse`)
rather than CPython's private ``sre_parse`` / ``sre_constants``, which carry
no compatibility guarantee and moved to ``re._parser`` / ``re._constants``
on 3.13 (DEP-001).
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from random import Random
from typing import Any, cast

from . import _regex_parse as rx
from ._regex_parse import RegexParseError
from .base import Generator

#: Upper bound on the *extra* repetitions allowed for ``*`` and ``+``.
MAX_UNBOUNDED_REPEAT = 8

#: Upper bound on the literal repeat count in ``{N}`` / ``{N,M}``. Without
#: this cap, ``a{1_000_000}`` quietly produces a million-character row
#: (TODO SCALE-002).
MAX_LITERAL_REPEAT = 10_000

#: Upper bound on the *total* characters one row can expand to. The
#: per-node MAX_LITERAL_REPEAT check is blind to multiplicative nesting:
#: ``(a{5000}){5000}`` passes it node-by-node yet materializes ~25M
#: chars/row. This cap bounds the product of nested repeats so a config
#: cannot drive unbounded memory use (SEC-001).
MAX_TOTAL_EXPANSION = 1_000_000

_PRINTABLE_ASCII = tuple(chr(c) for c in range(0x20, 0x7F))
_DIGITS = tuple(string.digits)
_WORD = tuple(string.ascii_letters + string.digits + "_")
_SPACE = tuple(" \t\n\r\f\v")
#: Pool for ``.`` (any char except newline); computed once (PERF-001).
_ANY_POOL = tuple(c for c in _PRINTABLE_ASCII if c != "\n")


@dataclass(frozen=True)
class RegexSpec:
    parsed: tuple[tuple[Any, Any], ...]


class RegexGenerator(Generator):
    """Emit strings matching the supplied regex ``pattern``."""

    type_name = "regex"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> RegexSpec:
        pattern = spec.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("regex 'pattern' must be a non-empty string")
        try:
            parsed = rx.parse(pattern)
        except RegexParseError as exc:
            raise ValueError(f"regex 'pattern' is not a valid regex: {exc}") from exc
        _reject_oversized_repeats(cast(Iterable[tuple[Any, Any]], parsed))
        if _max_expansion(cast(Iterable[tuple[Any, Any]], parsed)) > MAX_TOTAL_EXPANSION:
            raise ValueError(
                "regex 'pattern' can expand beyond MAX_TOTAL_EXPANSION "
                f"({MAX_TOTAL_EXPANSION}) characters per row"
            )
        return RegexSpec(parsed=_prepare_nodes(cast(Iterable[tuple[Any, Any]], parsed)))

    def generate(self, prepared: RegexSpec, rng: Random) -> str:
        parts: list[str] = []
        _emit_into(prepared.parsed, rng, parts)
        return "".join(parts)


# ---------------------------------------------------------------------------
# AST -> string
# ---------------------------------------------------------------------------


def _prepare_nodes(seq: Iterable[tuple[Any, Any]]) -> tuple[tuple[Any, Any], ...]:
    """Freeze the parsed AST and resolve character classes before generation."""
    prepared: list[tuple[Any, Any]] = []
    for op, arg in seq:
        if op is rx.IN:
            arg = _in_pool(tuple(arg))
        elif op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
            arg = (arg[0], arg[1], _prepare_nodes(arg[2]))
        elif op is rx.BRANCH:
            arg = (arg[0], tuple(_prepare_nodes(alt) for alt in arg[1]))
        elif op is rx.SUBPATTERN:
            arg = (arg[0], arg[1], arg[2], _prepare_nodes(arg[3]))
        prepared.append((op, arg))
    return tuple(prepared)


def _reject_oversized_repeats(seq: Iterable[tuple[Any, Any]]) -> None:
    """Walk the AST and reject any literal ``{lo,hi}`` whose ``lo`` (or
    finite ``hi``) exceeds :data:`MAX_LITERAL_REPEAT` (TODO SCALE-002)."""
    for op, arg in seq:
        if op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
            lo, hi, sub = arg
            bounded_hi = hi if hi != rx.MAXREPEAT else lo
            if max(lo, bounded_hi) > MAX_LITERAL_REPEAT:
                raise ValueError(
                    "regex 'pattern' literal repeat exceeds "
                    f"MAX_LITERAL_REPEAT ({MAX_LITERAL_REPEAT})"
                )
            _reject_oversized_repeats(sub)
        elif op is rx.BRANCH:
            for alt in arg[1]:
                _reject_oversized_repeats(alt)
        elif op is rx.SUBPATTERN:
            _reject_oversized_repeats(arg[3])
        elif op is rx.IN:
            _reject_invalid_character_class(arg)


def _reject_invalid_character_class(items: Iterable[tuple[Any, Any]]) -> None:
    try:
        _in_pool(tuple(items))
    except ValueError as exc:
        raise ValueError(f"regex 'pattern' has invalid character class: {exc}") from exc


def _max_expansion(seq: Iterable[tuple[Any, Any]]) -> int:
    """Return the maximum characters ``seq`` can emit for one row (SEC-001).

    Repeats multiply their sub-expansion, so nested quantifiers compound
    -- this is what the per-node :func:`_reject_oversized_repeats` check
    cannot see.
    """
    return sum(_node_expansion(op, arg) for op, arg in seq)


def _node_expansion(op: Any, arg: Any) -> int:
    if op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
        lo, hi, sub = arg
        reps = lo + MAX_UNBOUNDED_REPEAT if hi == rx.MAXREPEAT else hi
        return int(reps) * _max_expansion(sub)
    if op is rx.BRANCH:
        return max((_max_expansion(alt) for alt in arg[1]), default=0)
    if op is rx.SUBPATTERN:
        return _max_expansion(arg[3])
    if op is rx.AT:
        return 0
    return 1  # literals, classes, categories, any, range -> one char each


def _emit_into(seq: Iterable[tuple[Any, Any]], rng: Random, out: list[str]) -> None:
    """Append each node's rendering directly to ``out``.

    Caller-supplied accumulator so nested calls (notably
    :func:`_emit_repeat` and :func:`_emit_branch`) reuse the same list
    instead of allocating a fresh list per AST node (TODO PERF-010).
    """
    for op, arg in seq:
        handler = _EMIT_HANDLERS.get(op)
        if handler is None:
            raise ValueError(f"regex generator: unsupported construct {op!r}")
        handler(arg, rng, out)


def _emit_literal(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(chr(arg))


def _emit_not_literal(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(rng.choice(_excluding_pool(frozenset((chr(arg),)))))


def _emit_any(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(rng.choice(_ANY_POOL))


def _emit_branch(arg: Any, rng: Random, out: list[str]) -> None:
    _, alternatives = arg
    _emit_into(rng.choice(alternatives), rng, out)


def _emit_subpattern(arg: Any, rng: Random, out: list[str]) -> None:
    # (group, add_flags, del_flags, sub)
    _emit_into(arg[3], rng, out)


def _emit_category(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(rng.choice(_category_pool(arg)))


def _emit_at(arg: Any, rng: Random, out: list[str]) -> None:
    pass  # anchor, no output


def _emit_range(arg: Any, rng: Random, out: list[str]) -> None:
    lo, hi = arg
    out.append(chr(rng.randint(lo, hi)))


def _emit_repeat(arg: tuple[int, int, Any], rng: Random, out: list[str]) -> None:
    lo, hi, sub = arg
    if hi == rx.MAXREPEAT:
        hi = lo + MAX_UNBOUNDED_REPEAT
    count = rng.randint(lo, hi)
    for _ in range(count):
        _emit_into(sub, rng, out)


def _pick_in(pool: tuple[str, ...], rng: Random, out: list[str]) -> None:
    out.append(rng.choice(pool))


@lru_cache(maxsize=256)
def _in_pool(items: tuple[tuple[Any, Any], ...]) -> tuple[str, ...]:
    """Resolve a character-class node to its concrete pool once (PERF-001).

    Ranges and categories are expanded a single time per distinct class
    and the result is memoized, so ``[a-z]{20}`` / ``[^x]{100}`` no
    longer rebuild the pool per character, per row.
    """
    item_list = list(items)
    negate = bool(item_list) and item_list[0][0] is rx.NEGATE
    if negate:
        return _excluding_pool(frozenset(_flatten_in(item_list[1:])))
    pool = _flatten_in(item_list)
    if not pool:
        raise ValueError("regex generator: empty character class")
    return tuple(pool)


def _flatten_literal(arg: Any) -> list[str]:
    return [chr(arg)]


def _flatten_range(arg: Any) -> list[str]:
    lo, hi = arg
    return [chr(c) for c in range(lo, hi + 1)]


def _flatten_category(arg: Any) -> list[str]:
    return list(_category_pool(arg))


def _flatten_in(items: Iterable[tuple[Any, Any]]) -> list[str]:
    pool: list[str] = []
    for op, arg in items:
        handler = _FLATTEN_HANDLERS.get(op)
        if handler is None:
            raise ValueError(f"regex generator: unsupported class element {op!r}")
        pool.extend(handler(arg))
    return pool


@lru_cache(maxsize=256)
def _excluding_pool(excluded: frozenset[str]) -> tuple[str, ...]:
    """Printable-ASCII pool minus ``excluded``, memoized (PERF-001)."""
    pool = tuple(c for c in _PRINTABLE_ASCII if c not in excluded)
    if not pool:
        raise ValueError("regex generator: cannot satisfy negated class")
    return pool


def _negated_pool(included: tuple[str, ...]) -> tuple[str, ...]:
    excluded = frozenset(included)
    return tuple(c for c in _PRINTABLE_ASCII if c not in excluded)


#: Category -> character pool. Negated pools are computed once at import
#: instead of rebuilt on every draw, and the whole thing replaces the
#: six-branch if/return ladder with an O(1) lookup (CX-001).
_CATEGORY_POOLS = {
    rx.CATEGORY_DIGIT: _DIGITS,
    rx.CATEGORY_NOT_DIGIT: _negated_pool(_DIGITS),
    rx.CATEGORY_WORD: _WORD,
    rx.CATEGORY_NOT_WORD: _negated_pool(_WORD),
    rx.CATEGORY_SPACE: _SPACE,
    rx.CATEGORY_NOT_SPACE: _negated_pool(_SPACE),
}


def _category_pool(category: Any) -> tuple[str, ...]:
    pool = _CATEGORY_POOLS.get(category)
    if pool is None:
        raise ValueError(f"regex generator: unsupported category {category!r}")
    return pool


#: Dispatch table for _emit_node. Defined after every handler so the
#: dict literal can reference the names directly.
_EMIT_HANDLERS = {
    rx.LITERAL: _emit_literal,
    rx.NOT_LITERAL: _emit_not_literal,
    rx.ANY: _emit_any,
    rx.IN: _pick_in,
    rx.MAX_REPEAT: _emit_repeat,
    rx.MIN_REPEAT: _emit_repeat,
    rx.BRANCH: _emit_branch,
    rx.SUBPATTERN: _emit_subpattern,
    rx.CATEGORY: _emit_category,
    rx.AT: _emit_at,
    rx.RANGE: _emit_range,
}

_FLATTEN_HANDLERS = {
    rx.LITERAL: _flatten_literal,
    rx.RANGE: _flatten_range,
    rx.CATEGORY: _flatten_category,
}
