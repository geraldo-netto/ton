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
(``(...)``, ``(?:...)``). Unbounded quantifiers (``*`` and ``+``) use a
geometric draw with unbounded support and almost-sure termination.
Start/end anchors are supported only where they assert
the boundary of every generated alternative; word-boundary anchors are
rejected during preparation.

Implementation uses a small vendored parser (:mod:`ton.generators._regex_parse`)
rather than CPython's private ``sre_parse`` / ``sre_constants``, which carry
no compatibility guarantee and moved to ``re._parser`` / ``re._constants``
on 3.13 (DEP-001).
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from random import Random
from typing import Any

from .._proof import ProofResult
from .._transforms import TransformResult
from . import _regex_parse as rx
from ._regex_parse import RegexParseError
from .base import Generator, proof_result

_PRINTABLE_ASCII = tuple(chr(c) for c in range(0x20, 0x7F))
_DIGITS = tuple(string.digits)
_WORD = tuple(string.ascii_letters + string.digits + "_")
_SPACE = tuple(" \t\n\r\f\v")
#: Pool for ``.`` (any char except newline); computed once (PERF-001).
_ANY_POOL = tuple(c for c in _PRINTABLE_ASCII if c != "\n")
_AnchorWorkItem = tuple[tuple[tuple[Any, Any], ...], bool, bool]


@dataclass(frozen=True)
class RegexSpec:
    pattern: str
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
        _validate_anchors(parsed)
        prepared = _prepare_nodes(parsed)
        try:
            re.compile(pattern)
        except RecursionError:
            pass  # The iterative vendored parser already validated deep nesting.
        except re.error as exc:
            raise ValueError(f"regex 'pattern' is not a valid regex: {exc}") from exc
        return RegexSpec(pattern=pattern, parsed=prepared)

    def generate(self, prepared: RegexSpec, rng: Random) -> str:
        parts: list[str] = []
        _emit_into(prepared.parsed, rng, parts)
        return "".join(parts)

    def prove(self, prepared: RegexSpec, result: TransformResult) -> ProofResult:
        return proof_result(
            re.fullmatch(prepared.pattern, result.value) is not None,
            "value does not match regex 'pattern'",
        )


# ---------------------------------------------------------------------------
# AST -> string
# ---------------------------------------------------------------------------


def _validate_anchors(seq: Iterable[tuple[Any, Any]]) -> None:
    work: list[_AnchorWorkItem] = [(tuple(seq), True, True)]
    while work:
        nodes, at_start, at_end = work.pop()
        for index, (op, arg) in enumerate(nodes):
            node_at_start = at_start and index == 0
            node_at_end = at_end and index == len(nodes) - 1
            _validate_anchor_position(op, arg, node_at_start, node_at_end)
            _append_nested_anchor_work(work, op, arg, node_at_start, node_at_end)


def _validate_anchor_position(op: Any, arg: Any, at_start: bool, at_end: bool) -> None:
    if op is not rx.AT:
        return
    if (arg == "^" and at_start) or (arg == "$" and at_end):
        return
    raise ValueError(f"regex 'pattern' has unsupported positional anchor {arg!r}")


def _append_nested_anchor_work(
    work: list[_AnchorWorkItem],
    op: Any,
    arg: Any,
    at_start: bool,
    at_end: bool,
) -> None:
    if op is rx.SUBPATTERN:
        work.append((tuple(arg[3]), at_start, at_end))
    elif op is rx.BRANCH:
        work.extend((tuple(branch), at_start, at_end) for branch in arg[1])
    elif op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
        work.append((tuple(arg[2]), False, False))


def _prepare_nodes(seq: Iterable[tuple[Any, Any]]) -> tuple[tuple[Any, Any], ...]:
    """Resolve pools and prepare nested AST nodes without Python recursion."""
    prepared: list[tuple[Any, Any]] = []
    work: list[tuple[tuple[Any, Any], list[tuple[Any, Any]]]] = [
        (node, prepared) for node in reversed(tuple(seq))
    ]
    while work:
        (op, arg), target = work.pop()
        if op is rx.IN:
            target.append((op, _prepare_in_pool(arg)))
        elif op is rx.NOT_LITERAL:
            target.append((op, _excluding_pool(frozenset((chr(arg),)))))
        elif op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
            child: list[tuple[Any, Any]] = []
            target.append((op, (arg[0], arg[1], child)))
            work.extend((node, child) for node in reversed(tuple(arg[2])))
        elif op is rx.BRANCH:
            alternatives: list[list[tuple[Any, Any]]] = [[] for _ in arg[1]]
            target.append((op, (arg[0], alternatives)))
            for source, destination in reversed(tuple(zip(arg[1], alternatives, strict=True))):
                work.extend((node, destination) for node in reversed(tuple(source)))
        elif op is rx.SUBPATTERN:
            child = []
            target.append((op, (arg[0], arg[1], arg[2], child)))
            work.extend((node, child) for node in reversed(tuple(arg[3])))
        else:
            target.append((op, arg))
    return tuple(prepared)


def _prepare_in_pool(items: Iterable[tuple[Any, Any]]) -> tuple[str, ...]:
    try:
        return _in_pool(tuple(items))
    except ValueError as exc:
        raise ValueError(f"regex 'pattern' has invalid character class: {exc}") from exc


def _emit_into(seq: Iterable[tuple[Any, Any]], rng: Random, out: list[str]) -> None:
    """Append nodes iteratively so nesting does not consume the Python stack."""
    work: list[tuple[str, Any]] = [("node", node) for node in reversed(tuple(seq))]
    while work:
        kind, payload = work.pop()
        if kind == "repeat":
            remaining, sub = payload
            if remaining:
                work.append(("repeat", (remaining - 1, sub)))
                work.extend(("node", node) for node in reversed(tuple(sub)))
            continue
        op, arg = payload
        if op in (rx.MAX_REPEAT, rx.MIN_REPEAT):
            lo, hi, sub = arg
            work.append(("repeat", (_repeat_count(rng, lo, hi), sub)))
        elif op is rx.BRANCH:
            work.extend(("node", node) for node in reversed(tuple(rng.choice(arg[1]))))
        elif op is rx.SUBPATTERN:
            work.extend(("node", node) for node in reversed(tuple(arg[3])))
        else:
            handler = _EMIT_HANDLERS.get(op)
            if handler is None:
                raise ValueError(f"regex generator: unsupported construct {op!r}")
            handler(arg, rng, out)


def _repeat_count(rng: Random, minimum: int, maximum: Any) -> int:
    if maximum != rx.MAXREPEAT:
        return rng.randint(minimum, maximum)
    count = minimum
    while rng.getrandbits(1):
        count += 1
    return count


def _emit_literal(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(chr(arg))


def _emit_not_literal(pool: tuple[str, ...], rng: Random, out: list[str]) -> None:
    out.append(rng.choice(pool))


def _emit_any(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(rng.choice(_ANY_POOL))


def _emit_category(arg: Any, rng: Random, out: list[str]) -> None:
    out.append(rng.choice(_category_pool(arg)))


def _emit_at(arg: Any, rng: Random, out: list[str]) -> None:
    pass  # anchor, no output


def _emit_range(arg: Any, rng: Random, out: list[str]) -> None:
    lo, hi = arg
    out.append(chr(rng.randint(lo, hi)))


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
    rx.CATEGORY: _emit_category,
    rx.AT: _emit_at,
    rx.RANGE: _emit_range,
}

_FLATTEN_HANDLERS = {
    rx.LITERAL: _flatten_literal,
    rx.RANGE: _flatten_range,
    rx.CATEGORY: _flatten_category,
}
