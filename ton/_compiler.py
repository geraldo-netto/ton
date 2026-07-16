"""Compile-time plan contract for the runtime Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._proof import PreparedField
from ._template import Token
from ._transforms import Transform
from ._validation import Validator
from .generators import Generator


@dataclass(frozen=True)
class CompiledPlan:
    """Immutable configuration artifacts required by row generation."""

    template: str
    types: Mapping[str, Mapping[str, Any]]
    rows: int
    tokens: tuple[Token, ...]
    registry: Mapping[str, Generator]
    transforms: Mapping[str, Transform]
    validators: Mapping[str, Validator]
    prepared: Mapping[str, PreparedField]
    has_paired: bool
    literals: tuple[str, ...]
    plan_tokens: tuple[Token, ...]
