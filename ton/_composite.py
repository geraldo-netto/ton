"""Public cooperative composite contract, backed by the shared pipeline executor."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Generator as StepGenerator
from dataclasses import dataclass
from random import Random
from typing import Any, cast

from ._contracts import Generator
from ._pipeline import ChildDraw, DrawnValue, prove_draws, proven_draws
from ._proof import ProofResult, _trace_enabled
from ._steps import Call, Steps, cooperative, run_steps
from ._transforms import TransformResult
from ._validation import validation_transaction


@dataclass(frozen=True)
class ChildCall:
    """Yield a prepared child request and receive its generated string."""

    generator: Generator
    prepared: Any


type ChildSteps = StepGenerator[ChildCall, str, str]


class CompositeGenerator(Generator):
    """Generate through child requests without consuming the Python call stack.

    Implement ``generate_steps`` instead of ``generate``. Yield ``ChildCall``
    for each actual draw, then return the formatted string. Checked rows prove
    those exact draws automatically before calling ``prove_output``. Exceptions
    are thrown into the yielding iterator; its ``finally`` blocks always run.
    """

    @abstractmethod
    def generate_steps(self, prepared: Any, rng: Random) -> ChildSteps:
        """Yield child requests and return the composite's final string."""
        raise NotImplementedError  # pragma: no cover

    @cooperative
    def generate(self, prepared: Any, rng: Random) -> str:
        return cast(str, run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: Any, rng: Random) -> Steps:
        draws: list[ChildDraw] | None = [] if _trace_enabled.get() else None
        steps = self.generate_steps(prepared, rng)
        try:
            value = yield from _drive_children(steps, rng, draws)
        finally:
            steps.close()
        if not isinstance(value, str):
            raise TypeError("generate_steps must return a string")
        return value if draws is None else DrawnValue(value, tuple(draws), prepared)

    @cooperative
    def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: Any, result: TransformResult) -> Steps:
        draws = proven_draws(result, prepared)
        if draws is None:
            return ProofResult(False, "Composite value has no matching child trace")
        proof = yield from prove_draws(draws, "Composite child")
        return self.prove_output(prepared, result) if proof.ok else proof

    def prove_output(self, prepared: Any, result: TransformResult) -> ProofResult:
        """Optionally check the composite's formatting after all child proofs pass."""
        return ProofResult(True)


def _drive_children(steps: ChildSteps, rng: Random, draws: list[ChildDraw] | None) -> Steps:
    value: Any = None
    error: Exception | None = None
    while True:
        try:
            child = steps.throw(error) if error is not None else steps.send(value)
        except StopIteration as completed:
            return completed.value
        try:
            with validation_transaction():
                value = yield Call(child.generator, "generate", (child.prepared, rng))
        except Exception as exc:
            error = exc
        else:
            error = None
            if draws is not None:
                draws.append(ChildDraw(child.generator, child.prepared, value))
