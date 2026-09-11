"""Child pipeline execution and exact draw traces."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, cast

from ._contracts import Generator
from ._proof import PreparedPipeline, PreparedTransform, ProofResult, TransformStep, _trace_enabled
from ._steps import Call, Steps, _attribute_error, cooperative, run_steps
from ._tracetext import TraceText, plain_text
from ._transforms import TransformResult
from ._validation import validate_pipeline


@dataclass(frozen=True)
class ChildDraw:
    """One child draw: the generator/prepared pair and the text it produced."""

    generator: Generator
    prepared: Any
    value: str | TraceText


@dataclass(frozen=True, slots=True)
class DrawTrace:
    draws: tuple[ChildDraw, ...]
    owner: object


@dataclass(frozen=True, slots=True)
class PipelineTrace:
    pipeline: PreparedPipeline
    source: TransformResult
    steps: tuple[TransformStep, ...]


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


def drawn(
    generator: Generator, prepared: Any, value: str | TraceText, owner: object
) -> str | TraceText:
    """Tag ``value`` with the single child draw that produced it."""
    if not _trace_enabled.get():
        return value
    return TraceText(plain_text(value), DrawTrace((ChildDraw(generator, prepared, value),), owner))


def as_result(value: str | TraceText) -> TransformResult:
    if isinstance(value, TraceText):
        return TransformResult(value.value, _trace=value)
    return TransformResult(value)


def public_value(value: str | TraceText) -> str:
    """Materialize a string wrapper only at a public operation boundary."""
    if not isinstance(value, TraceText):
        return value
    trace = value.trace
    if isinstance(trace, DrawTrace):
        return DrawnValue(value.value, trace.draws, trace.owner)
    pipeline_trace = cast(PipelineTrace, trace)
    return _GeneratedChildValue(
        value.value, pipeline_trace.pipeline, pipeline_trace.source, pipeline_trace.steps
    )


def public_result(result: TransformResult) -> TransformResult:
    if result._trace is None or result.value is not result._trace.value:
        return result
    return TransformResult(public_value(result._trace), result.id_value)


def _result_trace(result: TransformResult) -> object | None:
    if result._trace is not None and result.value is result._trace.value:
        return result._trace.trace
    value = result.value
    if isinstance(value, DrawnValue):
        return DrawTrace(value.draws, value.owner)
    if isinstance(value, _GeneratedChildValue):
        return PipelineTrace(value.pipeline, value.source, value.steps)
    return None


def proven_draws(result: TransformResult, owner: object) -> tuple[ChildDraw, ...] | None:
    """Return draws belonging to this prepared composite in constant time (PERF-040).

    External or re-derived values retain the composite's ordinary fallback.
    Ownership is carried by the value, so pickle/deepcopy preserve the relationship.
    """
    trace = _result_trace(result)
    if not isinstance(trace, DrawTrace) or trace.owner is not owner:
        return None
    return trace.draws


def prove_draws(draws: tuple[ChildDraw, ...], label: str) -> Steps:
    """Prove every recorded draw against the child that produced it."""
    for draw in draws:
        proof = yield Call(
            draw.generator,
            "prove",
            (draw.prepared, as_result(draw.value)),
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

    pipeline: PreparedPipeline
    source: TransformResult
    steps: tuple[TransformStep, ...]

    def __new__(
        cls,
        value: str,
        pipeline: PreparedPipeline,
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


class TransformPipeline:
    """Execute the same ordered transform chain for root and child pipelines."""

    @cooperative
    def apply_chain(
        self, transforms: tuple[PreparedTransform, ...], result: TransformResult, rng: Random
    ) -> tuple[TransformResult, tuple[TransformStep, ...]]:
        final, steps = cast(
            tuple[TransformResult, tuple[TransformStep, ...]],
            run_steps(self, "apply_chain", transforms, result, rng),
        )
        return public_result(final), steps

    def _apply_chain_steps(
        self, transforms: tuple[PreparedTransform, ...], result: TransformResult, rng: Random
    ) -> Steps:
        steps: list[TransformStep] | None = [] if _trace_enabled.get() else None
        for transform in transforms:
            before = result
            if transform.cooperative_apply:
                result = yield Call(transform.transform, "apply", (transform.prepared, before, rng))
            else:
                result = _apply_leaf(transform, before, rng)
            if steps is not None:
                steps.append(TransformStep(transform, before, result))
        return result, tuple(steps) if steps is not None else ()


def _apply_leaf(
    transform: PreparedTransform, before: TransformResult, rng: Random
) -> TransformResult:
    try:
        return transform.apply(transform.prepared, before, rng)
    except Exception as exc:
        raise _attribute_error(Call(transform.transform, "apply", ()), exc) from exc


TRANSFORM_PIPELINE = TransformPipeline()


class ChildPipelineGenerator(Generator):
    """Adapt a nested field pipeline to the existing generator protocol."""

    type_name = "child_pipeline"

    @cooperative
    def generate(self, prepared: PreparedPipeline, rng: Random) -> str:
        return public_value(run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: PreparedPipeline, rng: Random) -> Steps:
        source = as_result(
            (yield Call(prepared.generator, "generate", (prepared.source_prepared, rng)))
            if prepared.uses_source
            else ""
        )
        result, steps = yield Call(
            TRANSFORM_PIPELINE, "apply_chain", (prepared.transforms, source, rng)
        )
        validate_pipeline(prepared.validators, result.value, "Nested value", defer=True)
        if not _trace_enabled.get():
            return result.value
        return TraceText(result.value, PipelineTrace(prepared, source, steps))

    @cooperative
    def prove(self, prepared: PreparedPipeline, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: PreparedPipeline, result: TransformResult) -> Steps:
        value = _result_trace(result)
        if not isinstance(value, PipelineTrace) or value.pipeline is not prepared:
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
