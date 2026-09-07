"""Proof-check recursion into composite generators (REL-001)."""

from __future__ import annotations

from random import Random
from typing import Any

import pytest

from ton._engine import Engine, ProofError
from ton._proof import ProofResult
from ton._transforms import BaseTransform, TransformProof, TransformResult
from ton._validation import ValidationError
from ton.generators import Generator
from ton.generators.base import (
    ChildPipelineGenerator,
    ChildPipelineSpec,
    DrawnValue,
    PreparationContext,
)
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
    from ton._registry import default_registry

    reg = default_registry()
    reg["reject"] = _RejectGenerator()
    reg["permissive"] = _PermissiveGenerator()
    return reg


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
    prepared = ChildPipelineSpec(_RejectGenerator(), {}, (), True)

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
