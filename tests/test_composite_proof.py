"""Proof-check recursion into composite generators (REL-001)."""

from __future__ import annotations

from random import Random
from typing import Any

import pytest

from ton._engine import Engine, ProofError
from ton._proof import ProofResult
from ton._transforms import BaseTransform, TransformProof, TransformResult
from ton.generators import Generator
from ton.generators.base import ChildPipelineGenerator, ChildPipelineSpec
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


def _registry() -> dict[str, Generator]:
    from ton._registry import default_registry

    reg = default_registry()
    reg["reject"] = _RejectGenerator()
    reg["permissive"] = _PermissiveGenerator()
    return reg


def _one_of(*choices: dict[str, Any]) -> tuple[OneOfGenerator, Any]:
    gen = OneOfGenerator()
    prepared = gen.prepare_composite({"choices": list(choices)}, _registry())
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
    ok_spec = gen.prepare_composite(
        {"choices": [{"weight": 1, "spec": {"type": "string", "values": ["a"]}}]},
        _registry(),
    )
    assert gen.prove(ok_spec, TransformResult("a")).ok

    bad_spec = gen.prepare_composite(
        {"choices": [{"weight": 1, "spec": {"type": "reject"}}]},
        _registry(),
    )
    assert not gen.prove(bad_spec, TransformResult("x")).ok


def test_weighted_legacy_prove_membership() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare({"values": ["red", "green"], "weights": [1, 1]})
    assert gen.prove(prepared, TransformResult("red")).ok
    rejected = gen.prove(prepared, TransformResult("blue"))
    assert not rejected.ok
    assert "weighted 'values'" in rejected.reason


def test_distribution_transform_prove_accepts_and_rejects() -> None:
    transform = DistributionTransform()
    ok_spec = transform.prepare_composite(
        {
            "choices": [
                {"weight": 1, "spec": {"type": "string", "values": ["a"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["b"]}},
            ]
        },
        _registry(),
    )
    before = TransformResult("src")
    assert transform.prove(ok_spec, before, TransformResult("a")).ok

    bad_spec = transform.prepare_composite(
        {
            "choices": [
                {"weight": 1, "spec": {"type": "reject"}},
                {"weight": 1, "spec": {"type": "reject"}},
            ]
        },
        _registry(),
    )
    assert not transform.prove(bad_spec, before, TransformResult("x")).ok


def _sequence_of(spec: dict[str, Any]) -> tuple[SequenceOfGenerator, Any]:
    gen = SequenceOfGenerator()
    return gen, gen.prepare_composite(spec, _registry())


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
