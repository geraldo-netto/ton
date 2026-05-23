"""Template parser and row renderer.

A template is a string with variables wrapped in ``$``::

    "$year$-$month$-$date$ ;hg;$cpu_type$"

A variable may carry a ``[id]`` suffix (e.g. ``$word[id]$``); the suffix
asks the engine for the *source* value of a paired generator (currently
``lmhash``) rather than its primary output.

To include a literal ``$`` in the template, double it: ``$$``. The
sequence ``$$`` is consumed by the parser and rendered as a single
``$`` character. Placeholders themselves cannot contain a literal
``$`` in their name (the inner regex stops at the next ``$``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Mapping, Tuple

#: One token = either the literal escape ``$$`` (group 0 only) or a
#: placeholder ``$NAME$`` where ``NAME`` has no ``$`` in it (group 1).
#: The alternation order matters: ``$$`` must be matched before the
#: placeholder branch so ``$$name$$`` parses as ``$ + name + $`` rather
#: than ``placeholder name`` + leftover dollars.
_TOKEN_RE = re.compile(r"\$\$|\$([^$]+?)\$")
_ID_SUFFIX = "[id]"
_LITERAL_DOLLAR = "$$"


@dataclass(frozen=True)
class Token:
    """One ``$...$`` placeholder parsed from the template."""

    #: Name of the type spec to render (the ``[id]`` suffix is stripped).
    type_key: str
    #: True if the placeholder was ``$name[id]$`` (paired-source request).
    wants_id: bool

    @property
    def placeholder(self) -> str:
        """Literal ``$...$`` token as written in the template."""
        suffix = _ID_SUFFIX if self.wants_id else ""
        return f"${self.type_key}{suffix}$"


def parse(template: str) -> List[Token]:
    """Extract every placeholder token (``$NAME$`` / ``$NAME[id]$``).

    ``$$`` escapes are skipped; they are not placeholders. Result is
    memoized so config-side validation and engine-side rendering share
    the same parse work (TODO PERF-007).
    """
    return list(_parse_cached(template))


@lru_cache(maxsize=256)
def _parse_cached(template: str) -> Tuple[Token, ...]:
    tokens: List[Token] = []
    for match in _TOKEN_RE.finditer(template):
        if match.group(0) == _LITERAL_DOLLAR:
            continue
        raw = match.group(1)
        wants_id = raw.endswith(_ID_SUFFIX)
        key = raw[: -len(_ID_SUFFIX)] if wants_id else raw
        tokens.append(Token(type_key=key, wants_id=wants_id))
    return tuple(tokens)


class UndeclaredVariableError(ValueError):
    """A template placeholder references a name not declared in ``types``."""


def validate_against(template: str, declared: Iterable[str]) -> None:
    """Raise if any placeholder in ``template`` is missing from ``declared``.

    Single source of truth for the "template references undeclared
    variable" check (TODO DEC-002). Both ``ton.config`` and
    ``ton.engine`` call this so neither has to know how the template
    is parsed.
    """
    declared_set = set(declared)
    for token in parse(template):
        if token.type_key not in declared_set:
            raise UndeclaredVariableError(
                f"Template references undeclared variable {token.type_key!r}"
            )


def render(template: str, values: Mapping[str, str]) -> str:
    """Substitute placeholders in ``template`` using a single regex pass.

    ``values`` is keyed by the literal placeholder text (``$name$`` or
    ``$name[id]$``). ``$$`` is rendered as a single ``$``. Unknown
    placeholders are left in place. One regex pass replaces every
    match, so the cost is O(template_length) per row.
    """
    def _sub(match: re.Match[str]) -> str:
        if match.group(0) == _LITERAL_DOLLAR:
            return "$"
        placeholder = match.group(0)
        return values.get(placeholder, placeholder)

    return _TOKEN_RE.sub(_sub, template)
