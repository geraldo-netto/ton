"""Child pipeline execution and exact draw traces."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, cast

from ._contracts import Generator
from ._proof import PreparedTransform, ProofResult, TransformStep, _trace_enabled
from ._steps import Call, Steps, cooperative, run_steps
from ._transforms import TransformResult
from ._validation import ValidationError, validate_with_reference


@dataclass(frozen=True)
class ChildDraw:
    """One child draw: the generator/prepared pair and the text it produced."""

    generator: Generator
    prepared: Any
    value: str


class DrawnValue(str):
    """Generated text tagged with the child draw(s) that produced it.

    Composite generators (``oneOf``, ``weighted``, ``sequence_of``) and the
    ``distribution`` transform pick one branch at row time but used to prove
    a value by asking *every* branch. A branch whose proof is permissive
    then masked the selected branch's failure (REL-021, REL-022, REL-023).
    Carrying the draws lets each composite prove exactly what ran.

    It subclasses ``str`` so the value stays an ordinary string everywhere
    else -- rendering, transforms, validators, and output are unaffected.
    """

    draws: tuple[ChildDraw, ...]
    owner: object

    def __new__(cls, value: str, draws: tuple[ChildDraw, ...], owner: object) -> DrawnValue:
        instance = super().__new__(cls, value)
        instance.draws = draws
        instance.owner = owner
        return instance

    def __getnewargs_ex__(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (str(self), self.draws, self.owner), {}


def drawn(generator: Generator, prepared: Any, value: str, owner: object) -> str:
    """Tag ``value`` with the single child draw that produced it."""
    if not _trace_enabled.get():
        return value
    return DrawnValue(value, (ChildDraw(generator, prepared, value),), owner)


def proven_draws(result: TransformResult, owner: object) -> tuple[ChildDraw, ...] | None:
    """Return draws belonging to this prepared composite in constant time (PERF-040).

    External or re-derived values retain the composite's ordinary fallback.
    Ownership is carried by the value, so pickle/deepcopy preserve the relationship.
    """
    value = result.value
    if not isinstance(value, DrawnValue) or value.owner is not owner:
        return None
    return value.draws


def prove_draws(draws: tuple[ChildDraw, ...], label: str) -> Steps:
    """Prove every recorded draw against the child that produced it."""
    for draw in draws:
        proof = yield Call(
            draw.generator,
            "prove",
            (draw.prepared, TransformResult(draw.value)),
            proof_stage="source",
        )
        if not proof.ok:
            reason = f"{label} failed its own proof"
            return ProofResult(
                ok=False, reason=f"{reason}: {proof.reason}" if proof.reason else reason
            )
    return ProofResult(ok=True)


class _GeneratedChildValue(str):
    """String carrying the exact nested transform trace until proofing."""

    pipeline: ChildPipelineSpec
    source: TransformResult
    steps: tuple[TransformStep, ...]

    def __new__(
        cls,
        value: str,
        pipeline: ChildPipelineSpec,
        source: TransformResult,
        steps: tuple[TransformStep, ...],
    ) -> _GeneratedChildValue:
        instance = super().__new__(cls, value)
        instance.pipeline = pipeline
        instance.source = source
        instance.steps = steps
        return instance

    def __getnewargs_ex__(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (str(self), self.pipeline, self.source, self.steps), {}


@dataclass(frozen=True)
class ChildPipelineSpec:
    """Prepared source and transform stages for one composite child."""

    generator: Generator
    source_prepared: Any
    transforms: tuple[PreparedTransform, ...]
    uses_source: bool
    validators: tuple[Any, ...] = ()


class ChildPipelineGenerator(Generator):
    """Adapt a nested field pipeline to the existing generator protocol."""

    type_name = "child_pipeline"

    @cooperative
    def generate(self, prepared: ChildPipelineSpec, rng: Random) -> str:
        return cast(str, run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: ChildPipelineSpec, rng: Random) -> Steps:
        source = TransformResult(
            (yield Call(prepared.generator, "generate", (prepared.source_prepared, rng)))
            if prepared.uses_source
            else ""
        )
        result = source
        steps: list[TransformStep] | None = [] if _trace_enabled.get() else None
        for transform in prepared.transforms:
            before = result
            result = yield Call(transform.transform, "apply", (transform.prepared, before, rng))
            if steps is not None:
                steps.append(TransformStep(transform, before, result))
        for validator in prepared.validators:
            if not validate_with_reference(validator, result.value):
                raise ValidationError(f"Nested value failed validator {validator.type_name!r}")
        if steps is None:
            return result.value
        return _GeneratedChildValue(result.value, prepared, source, tuple(steps))

    @cooperative
    def prove(self, prepared: ChildPipelineSpec, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: ChildPipelineSpec, result: TransformResult) -> Steps:
        value = result.value
        if not isinstance(value, _GeneratedChildValue) or value.pipeline is not prepared:
            return ProofResult(ok=True)
        if prepared.uses_source:
            source_proof = yield Call(
                prepared.generator,
                "prove",
                (prepared.source_prepared, value.source),
                proof_stage="source",
            )
            if not source_proof.ok:
                return source_proof
        for step in value.steps:
            proof = yield Call(
                step.prepared.transform,
                "prove",
                (step.prepared.prepared, step.before, step.after),
                proof_stage="transform",
            )
            if not proof.ok:
                return ProofResult(ok=False, reason=proof.reason)
        return ProofResult(ok=True)
