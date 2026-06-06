"""Tests for transform contracts."""

from __future__ import annotations

from random import Random
from typing import Any

from ton._transforms import BaseTransform, TransformProof, TransformResult
from ton._registry import default_registry
from ton.transforms import DistributionTransform


class EchoTransform(BaseTransform):
    type_name = "echo"

    def apply(
        self,
        prepared: Any,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        del prepared, rng
        return value


def test_transform_result_reports_pairing() -> None:
    assert not TransformResult("value").is_paired
    assert TransformResult("value", id_value="id").is_paired


def test_base_transform_prepare_and_prove_defaults() -> None:
    transform = EchoTransform()
    prepared = transform.prepare({"type": "echo"})
    result = transform.apply(prepared, TransformResult("x"), Random(0))

    assert result.value == "x"
    assert transform.prove(prepared, result, result) == TransformProof(ok=True)


def test_distribution_transform_chooses_prepared_candidate() -> None:
    transform = DistributionTransform()
    prepared = transform.prepare_composite(
        {
            "type": "distribution",
            "choices": [
                {"weight": 0, "spec": {"type": "string", "values": ["never"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["always"]}},
            ],
        },
        default_registry(),
    )

    result = transform.apply(prepared, TransformResult("ignored"), Random(0))

    assert result == TransformResult("always")


def test_distribution_transform_requires_two_choices() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare_composite(
            {
                "type": "distribution",
                "choices": [
                    {"spec": {"type": "string", "values": ["only"]}},
                ],
            },
            default_registry(),
        )
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")
