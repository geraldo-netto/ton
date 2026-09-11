"""Proof-check recursion into composite generators (REL-001)."""

from __future__ import annotations

import pickle
from copy import deepcopy
from random import Random
from typing import Any

import pytest

from ton._contracts import Generator, PreparationContext
from ton._engine import Engine, ProofError
from ton._pipeline import ChildPipelineGenerator, DrawnValue
from ton._proof import PreparedPipeline, ProofResult
from ton._transforms import BaseTransform, TransformProof, TransformResult
from ton._validation import ValidationError
from ton.generators.one_of import OneOfGenerator
from ton.generators.sequence_of import SequenceOfGenerator
from ton.generators.weighted import WeightedGenerator
from ton.transforms.distribution import DistributionTransform


class _RejectGenerator(Generator):
    """Generator whose proof always fails -- lets us drive the fail path."""

    type_name = "reject"

    def generate(self, prepared: Any, rng: Random) -> str:
        del prepared, rng
        return "x"

    def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
        del prepared, result
        return ProofResult(ok=False, reason="always rejects")


class _PermissiveGenerator(Generator):
    type_name = "permissive"

    def generate(self, prepared: Any, rng: Random) -> str:
        del prepared, rng
        return "anything"


class _RejectTransform(BaseTransform):
    type_name = "reject_transform"

    def prove(self, prepared, before, after):
        del prepared, before, after
        return TransformProof(ok=False, reason="nested transform rejects")


class _SuffixTransform(BaseTransform):
    """Marks the value so a skipped candidate transform is visible."""

    type_name = "suffix"
    config_keys = frozenset()

    def apply(self, prepared: Any, value: TransformResult, rng: Random) -> TransformResult:
        del prepared, rng
        return TransformResult(value.value + "!")


def _registry() -> dict[str, Generator]:
    from ton._registry import make_registry

    reg = make_registry()
    reg["reject"] = _RejectGenerator()
    reg["permissive"] = _PermissiveGenerator()
    return reg


@pytest.mark.parametrize("serialization", ["pickle", "deepcopy"])
@pytest.mark.parametrize("transformed", [False, True])
def test_traced_draw_and_audit_roundtrips_preserve_proof_ownership(serialization, transformed):
    """CONC-020: reconstructible strings must preserve the selected rejecting branch."""

    def roundtrip(value):
        return pickle.loads(pickle.dumps(value)) if serialization == "pickle" else deepcopy(value)

    child = {"type": "reject"}
    reason = "always rejects"
    if transformed:
        child = {"type": "string", "values": ["x"], "transforms": [{"type": "reject_transform"}]}
        reason = "nested transform rejects"
    field_spec = {
        "type": "weighted",
        "choices": [
            {"spec": child, "weight": 1},
            {"spec": {"type": "permissive"}, "weight": 0},
        ],
    }
    engine = Engine(
        {"rows": 1, "format": "$x$", "types": {"x": field_spec}},
        registry=_registry(),
        transforms={"reject_transform": _RejectTransform()},
        proof_mode="audit",
    )
    field = engine._plan.prepared["x"]
    value = field.generator.generate(field.source_prepared, Random(0))
    copied_field, copied_value = roundtrip((field, value))
    assert copied_value == value == "x"
    assert copied_value.owner is copied_field.source_prepared.distribution
    proof = copied_field.generator.prove(
        copied_field.source_prepared, TransformResult(copied_value)
    )
    assert not proof.ok and reason in proof.reason
    assert list(engine) == ["x"]
    failure = roundtrip(engine.proof_failures[0])
    assert failure.row == 1 and failure.type_key == "x" and reason in failure.reason
    assert failure.spec == engine.proof_failures[0].spec
    # SCALE-027: completed diagnostics detach draws; live values above still
    # preserve proof ownership through both supported serialization paths.
    assert type(failure.value) is str
    assert failure.value == "x"
    assert failure == engine.proof_failures[0]


@pytest.mark.parametrize("mode", ["all", "audit"])
@pytest.mark.parametrize("kind", ["weighted", "distribution"])
def test_selected_child_rejection_is_evaluated_once(mode, kind) -> None:
    """REL-038: preserve the first rejection even when a second call would raise."""
    calls = []

    class RejectOnce(_RejectGenerator):
        def prove(self, prepared, result):
            calls.append(result.value)
            if len(calls) > 1:
                raise RuntimeError("proof called twice")
            return ProofResult(False, "original rejection")

    choices = [
        {"spec": {"type": "reject"}, "weight": 1},
        {"spec": {"type": "permissive"}, "weight": 0},
    ]
    field = {"type": "weighted", "choices": choices}
    if kind == "distribution":
        field = {
            "type": "string",
            "values": ["source"],
            "transforms": [{"type": "distribution", "choices": choices}],
        }
    registry = _registry()
    registry["reject"] = RejectOnce()
    engine = Engine(
        {"rows": 1, "format": "$x$", "types": {"x": field}}, registry=registry, proof_mode=mode
    )
    if mode == "all":
        with pytest.raises(ProofError, match="original rejection"):
            list(engine)
    else:
        assert list(engine) == ["x"]
        assert len(engine.proof_failures) == 1
        assert engine.proof_failures[0].reason.endswith("original rejection")
    assert calls == ["x"]


def _context() -> PreparationContext:
    return PreparationContext(_registry())


def _one_of(*choices: dict[str, Any]) -> tuple[OneOfGenerator, Any]:
    gen = OneOfGenerator()
    prepared = gen.prepare({"choices": list(choices)}, _context())
    return gen, prepared


def test_one_of_prove_accepts_when_a_child_accepts() -> None:
    gen, prepared = _one_of({"type": "permissive"}, {"type": "reject"})
    assert gen.prove(prepared, TransformResult("anything")).ok


def test_one_of_prove_rejects_when_no_child_accepts() -> None:
    gen, prepared = _one_of({"type": "reject"})
    proof = gen.prove(prepared, TransformResult("x"))
    assert not proof.ok
    assert "no oneOf choice" in proof.reason


def test_nested_transform_proof_uses_exact_generation_trace() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["x"],
                        "transforms": [{"type": "reject_transform"}],
                    }
                ],
            }
        },
    }

    engine = Engine(
        config,
        transforms={"reject_transform": _RejectTransform()},
        proof_mode="all",
    )
    with pytest.raises(ProofError, match="nested transform rejects"):
        list(engine)


def test_nested_transform_proof_reports_source_failure() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "reject",
                        "transforms": [{"type": "identity"}],
                    }
                ],
            }
        },
    }

    engine = Engine(config, registry=_registry(), proof_mode="all")
    with pytest.raises(ProofError, match="always rejects"):
        list(engine)


def test_nested_pipeline_proof_is_permissive_without_generation_trace() -> None:
    pipeline = ChildPipelineGenerator()
    prepared = PreparedPipeline(_RejectGenerator(), {}, (), True)

    assert pipeline.prove(prepared, TransformResult("external")).ok


def test_weighted_composite_prove_accepts_and_rejects() -> None:
    gen = WeightedGenerator()
    ok_spec = gen.prepare(
        {"choices": [{"weight": 1, "spec": {"type": "string", "values": ["a"]}}]},
        _context(),
    )
    assert gen.prove(ok_spec, TransformResult("a")).ok

    bad_spec = gen.prepare(
        {"choices": [{"weight": 1, "spec": {"type": "reject"}}]},
        _context(),
    )
    assert not gen.prove(bad_spec, TransformResult("x")).ok


def test_distribution_transform_prove_accepts_and_rejects() -> None:
    transform = DistributionTransform()
    ok_spec = transform.prepare(
        {
            "choices": [
                {"weight": 1, "spec": {"type": "string", "values": ["a"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["b"]}},
            ]
        },
        _context(),
    )
    before = TransformResult("src")
    assert transform.prove(ok_spec, before, TransformResult("a")).ok

    bad_spec = transform.prepare(
        {
            "choices": [
                {"weight": 1, "spec": {"type": "reject"}},
                {"weight": 1, "spec": {"type": "reject"}},
            ]
        },
        _context(),
    )
    assert not transform.prove(bad_spec, before, TransformResult("x")).ok


def _sequence_of(spec: dict[str, Any]) -> tuple[SequenceOfGenerator, Any]:
    gen = SequenceOfGenerator()
    return gen, gen.prepare(spec, _context())


def test_sequence_of_prove_without_separator_is_permissive() -> None:
    gen, prepared = _sequence_of({"count": 2, "spec": {"type": "string", "values": ["a"]}})
    assert gen.prove(prepared, TransformResult("aa")).ok


def test_sequence_of_prove_wrong_part_count_is_permissive() -> None:
    gen, prepared = _sequence_of(
        {"count": 2, "separator": "-", "spec": {"type": "string", "values": ["a"]}}
    )
    # Only one part -> cannot map to 2 elements, stay permissive.
    assert gen.prove(prepared, TransformResult("a")).ok


def test_sequence_of_prove_checks_each_element() -> None:
    gen, prepared = _sequence_of(
        {"count": 2, "separator": "-", "spec": {"type": "string", "values": ["a"]}}
    )
    assert gen.prove(prepared, TransformResult("a-a")).ok

    reject_gen, reject_prepared = _sequence_of(
        {"count": 2, "separator": "-", "spec": {"type": "reject"}}
    )
    proof = reject_gen.prove(reject_prepared, TransformResult("x-x"))
    assert not proof.ok
    assert "sequence_of element failed" in proof.reason


def test_root_transform_candidates_run_their_own_pipeline() -> None:
    """A root distribution candidate's transforms and validators must run (REL-020)."""
    engine = Engine(
        {
            "rows": 1,
            "format": "$x$",
            "types": {
                "x": {
                    "type": "string",
                    "values": ["root-src"],
                    "transforms": [
                        {
                            "type": "distribution",
                            "choices": [
                                {
                                    "weight": 1,
                                    "spec": {
                                        "type": "string",
                                        "values": ["cand"],
                                        "transforms": [{"type": "suffix"}],
                                    },
                                },
                                {"weight": 0, "spec": {"type": "string", "values": ["other"]}},
                            ],
                        }
                    ],
                }
            },
        },
        transforms={"distribution": DistributionTransform(), "suffix": _SuffixTransform()},
    )

    assert list(engine) == ["cand!"]


def test_root_transform_candidate_validators_reject_like_root_validators() -> None:
    """A nested validator failure is a ValidationError, not a transform crash (REL-020)."""
    engine = Engine(
        {
            "rows": 1,
            "format": "$x$",
            "types": {
                "x": {
                    "type": "string",
                    "values": ["src"],
                    "transforms": [
                        {
                            "type": "distribution",
                            "choices": [
                                {
                                    "weight": 1,
                                    "spec": {
                                        "type": "string",
                                        "values": [""],
                                        "validators": ["non_empty"],
                                    },
                                },
                                {"weight": 0, "spec": {"type": "string", "values": ["other"]}},
                            ],
                        }
                    ],
                }
            },
        },
        transforms={"distribution": DistributionTransform()},
    )

    with pytest.raises(ValidationError, match="Nested value failed validator"):
        list(engine)


def test_one_of_proves_the_branch_that_ran() -> None:
    """A permissive sibling must not mask the selected child's failure (REL-021)."""
    engine = Engine(
        {
            "rows": 1,
            "format": "$x$",
            "types": {
                "x": {
                    "type": "oneOf",
                    "choices": [
                        {
                            "type": "string",
                            "values": ["a"],
                            "transforms": [{"type": "reject_transform"}],
                        },
                        {
                            "type": "string",
                            "values": ["b"],
                            "transforms": [{"type": "reject_transform"}],
                        },
                    ],
                }
            },
        },
        transforms={"reject_transform": _RejectTransform()},
        proof_mode="all",
    )

    with pytest.raises(ProofError, match="oneOf choice failed its own proof"):
        list(engine)


def test_one_of_stays_permissive_for_values_it_did_not_draw() -> None:
    """An external value is still proven against every choice (REL-021)."""
    gen = OneOfGenerator()
    prepared = gen.prepare(
        {"choices": [{"type": "string", "values": ["a"]}, {"type": "string", "values": ["b"]}]},
        _context(),
    )

    assert gen.prove(prepared, TransformResult("b")).ok
    assert not gen.prove(prepared, TransformResult("zzz")).ok


def test_one_of_ignores_draw_tags_from_another_composite() -> None:
    """Identity is checked, not merely 'is tagged': a foreign draw falls back (REL-021)."""
    gen = OneOfGenerator()
    source = gen.prepare({"choices": [{"type": "string", "values": ["a"]}]}, _context())
    other = gen.prepare({"choices": [{"type": "string", "values": ["a"]}]}, _context())

    tagged = gen.generate(source, Random(0))
    assert isinstance(tagged, DrawnValue)

    # Proven by a different oneOf: its draws name children this spec does not own,
    # so it must fall back to the any-choice rule instead of trusting the tag.
    assert gen.prove(other, TransformResult(tagged)).ok
    assert not gen.prove(other, TransformResult("not-a-choice")).ok


@pytest.mark.parametrize("size", [1, 1000])
@pytest.mark.parametrize("kind", ["oneOf", "weighted"])
def test_composite_proof_work_depends_only_on_selected_draws(monkeypatch, size, kind) -> None:
    """PERF-040: proving a selected child must not revisit its whole candidate pool."""
    from ton import _pipeline

    child = {"type": "string", "values": ["x"]}
    choices = [child if kind == "oneOf" else {"spec": child} for _ in range(size)]
    engine = Engine(
        {"rows": 1, "format": "$x$", "types": {"x": {"type": kind, "choices": choices}}}
    )
    field = engine._plan.prepared["x"]
    value = field.generator.generate(field.source_prepared, Random(0))
    calls = []

    def counted_id(obj):
        calls.append(obj)
        return id(obj)

    monkeypatch.setattr(_pipeline, "id", counted_id, raising=False)
    assert field.generator.prove(field.source_prepared, TransformResult(value)).ok
    assert len(calls) <= 2


@pytest.mark.parametrize(
    ("field", "extra_transforms"),
    [
        (
            {
                "type": "weighted",
                "choices": [
                    {
                        "weight": 1,
                        "spec": {
                            "type": "string",
                            "values": ["a"],
                            "transforms": [{"type": "reject_transform"}],
                        },
                    },
                    {
                        "weight": 1,
                        "spec": {
                            "type": "string",
                            "values": ["b"],
                            "transforms": [{"type": "reject_transform"}],
                        },
                    },
                ],
            },
            {},
        ),
        (
            {
                "type": "string",
                "values": ["src"],
                "transforms": [
                    {
                        "type": "distribution",
                        "choices": [
                            {
                                "weight": 1,
                                "spec": {
                                    "type": "string",
                                    "values": ["a"],
                                    "transforms": [{"type": "reject_transform"}],
                                },
                            },
                            {
                                "weight": 1,
                                "spec": {
                                    "type": "string",
                                    "values": ["b"],
                                    "transforms": [{"type": "reject_transform"}],
                                },
                            },
                        ],
                    }
                ],
            },
            {"distribution": DistributionTransform()},
        ),
    ],
    ids=["weighted", "distribution"],
)
def test_weighted_choice_sets_prove_the_selected_child(field, extra_transforms) -> None:
    """A permissive sibling must not mask the drawn child's failure (REL-022)."""
    engine = Engine(
        {"rows": 1, "format": "$x$", "types": {"x": field}},
        transforms={"reject_transform": _RejectTransform(), **extra_transforms},
        proof_mode="all",
    )

    with pytest.raises(ProofError, match="nested transform rejects"):
        list(engine)


def test_weighted_stays_permissive_for_values_it_did_not_draw() -> None:
    """An external value is still proven against every choice (REL-022)."""
    gen = WeightedGenerator()
    prepared = gen.prepare(
        {
            "choices": [
                {"weight": 1, "spec": {"type": "string", "values": ["a"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["b"]}},
            ]
        },
        _context(),
    )

    assert gen.prove(prepared, TransformResult("b")).ok
    assert not gen.prove(prepared, TransformResult("zzz")).ok


@pytest.mark.parametrize("separator", ["-", "", "a"], ids=["plain", "empty", "ambiguous"])
def test_sequence_of_proves_every_element_it_generated(separator: str) -> None:
    """Concatenation must not drop the elements' proof context (REL-023)."""
    engine = Engine(
        {
            "rows": 1,
            "format": "$x$",
            "types": {
                "x": {
                    "type": "sequence_of",
                    "count": 2,
                    "separator": separator,
                    "spec": {
                        "type": "string",
                        "values": ["a"],
                        "transforms": [{"type": "reject_transform"}],
                    },
                }
            },
        },
        transforms={"reject_transform": _RejectTransform()},
        proof_mode="all",
    )

    with pytest.raises(ProofError, match="sequence_of element failed its own proof"):
        list(engine)


def test_stack_dispatch_respects_overridden_plugin_operations() -> None:
    """SCALE-007: cooperative base hooks must not bypass a plugin's overrides."""

    class Override(OneOfGenerator):
        def generate(self, prepared, rng):
            return "override"

        def prove(self, prepared, result):
            return ProofResult(result.value == "override")

    registry = _registry()
    registry["override"] = Override()
    child = {"type": "override", "choices": [{"type": "string", "values": ["wrong"]}]}
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": "oneOf", "choices": [child]}}}
    assert list(Engine(config, registry=registry, proof_mode="all")) == ["override"]


def test_standalone_distribution_preserves_selected_child_proof() -> None:
    """SCALE-007: direct distribution operations use the same work-stack semantics."""
    prepared = WeightedGenerator().prepare({"choices": [{"spec": {"type": "reject"}}]}, _context())
    value = prepared.distribution.choose(Random(0))
    proof = prepared.distribution.prove(TransformResult(value))
    assert value == "x"
    assert not proof.ok
    assert proof.reason == "always rejects"


def test_nested_generator_exception_unwinds_the_work_stack() -> None:
    """SCALE-007: leaf exceptions propagate once through nested runtime operations."""
    from ton import api
    from ton._proof import _trace_enabled

    calls = []

    class Broken(Generator):
        def generate(self, prepared, rng):
            calls.append("called")
            raise RuntimeError("leaf generation failed")

    registry = _registry()
    registry["broken"] = Broken()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {
            "x": {
                "type": "oneOf",
                "choices": [{"type": "weighted", "choices": [{"spec": {"type": "broken"}}]}],
            }
        },
    }
    with pytest.raises(api.GeneratorExecutionError, match="leaf generation failed"):
        list(Engine(config, registry=registry, proof_mode="all"))
    assert calls == ["called"]
    assert _trace_enabled.get() is True
