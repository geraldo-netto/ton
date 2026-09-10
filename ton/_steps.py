"""Evaluate nested generator operations with an explicit stack (SCALE-007)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Call:
    target: Any
    operation: str
    args: tuple[Any, ...]


type Steps = Generator[Call, Any, Any]


def cooperative[F: Callable[..., Any]](operation: F) -> F:
    """Tie stack dispatch to this method, so subclass overrides keep their semantics."""
    operation._ton_cooperative = True  # type: ignore[attr-defined]
    return operation


def run_steps(target: Any, operation: str, *args: Any) -> Any:
    """Drive cooperative composite operations while leaf hooks keep their normal API."""
    request: Call | None = Call(target, operation, args)
    stack: list[Steps] = []
    result: Any = None
    try:
        while request is not None:
            error: Exception | None = None
            try:
                method = getattr(request.target, request.operation)
                if not getattr(method, "_ton_cooperative", False):
                    result = method(*request.args)
                else:
                    stepper = getattr(request.target, f"_{request.operation}_steps")
                    stack.append(stepper(*request.args))
                    result = None
            except Exception as exc:
                error = exc
            request, result = _resume(stack, result, error)
        return result
    finally:
        for steps in reversed(stack):
            steps.close()


def _resume(stack: list[Steps], result: Any, error: Exception | None) -> tuple[Call | None, Any]:
    while stack:
        try:
            request = stack[-1].throw(error) if error is not None else stack[-1].send(result)
            return request, None
        except StopIteration as completed:
            stack.pop()
            result, error = completed.value, None
        except Exception as exc:
            stack.pop()
            error = exc
    if error is not None:
        raise error
    return None, result
