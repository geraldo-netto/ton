"""Evaluate nested generator operations with an explicit stack (SCALE-007)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Literal

from ._validation import ValidationError, ValidatorHookError


class OperationError(RuntimeError):
    """Retain the originating component until the engine supplies field/row context."""

    def __init__(self, stage: str, reference: str, cause: Exception) -> None:
        self.stage = stage
        self.reference = reference
        self.cause = cause
        super().__init__(str(cause))


@dataclass(frozen=True)
class Call:
    target: Any
    operation: str
    args: tuple[Any, ...]
    proof_stage: Literal["source", "transform"] | None = None


type Steps = Generator[Call, Any, Any]
type _Frame = tuple[Call, Steps]


def cooperative[F: Callable[..., Any]](operation: F) -> F:
    """Tie stack dispatch to this method, so subclass overrides keep their semantics."""
    operation._ton_cooperative = True  # type: ignore[attr-defined]
    return operation


def run_steps(target: Any, operation: str, *args: Any) -> Any:
    """Drive cooperative composite operations while leaf hooks keep their normal API."""
    request: Call | None = Call(target, operation, args)
    stack: list[_Frame] = []
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
                    stack.append((request, stepper(*request.args)))
                    result = None
            except Exception as exc:
                error = _attribute_error(request, exc)
            request, result = _resume(stack, result, error)
        return result
    finally:
        for _request, steps in reversed(stack):
            steps.close()


def _resume(stack: list[_Frame], result: Any, error: Exception | None) -> tuple[Call | None, Any]:
    while stack:
        owner, steps = stack[-1]
        try:
            request = steps.throw(error) if error is not None else steps.send(result)
            return request, None
        except StopIteration as completed:
            stack.pop()
            result, error = completed.value, None
        except Exception as exc:
            stack.pop()
            error = _attribute_error(owner, exc)
    if error is not None:
        raise error
    return None, result


def _attribute_error(request: Call, error: Exception) -> Exception:
    if isinstance(error, (OperationError, ValidationError, ValidatorHookError)):
        return error
    if request.operation == "generate":
        return OperationError("Generator", type(request.target).__name__, error)
    if request.operation == "apply":
        return OperationError("Transform", request.target.type_name, error)
    if request.operation == "prove" and request.proof_stage is not None:
        return OperationError(
            f"{request.proof_stage.capitalize()} proof", request.target.type_name, error
        )
    return error
