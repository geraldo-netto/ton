"""Tests for transform contracts."""

from __future__ import annotations

from math import isfinite
from random import Random
from typing import Any

from ton._registry import make_registry
from ton._transforms import (
    BaseTransform,
    TransformCapabilities,
    TransformProof,
    TransformResult,
    fold_paired_capabilities,
)
from ton.generators.base import PreparationContext
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


def test_fold_paired_capabilities_reports_first_incompatible_stage() -> None:
    result = fold_paired_capabilities(
        True,
        (
            TransformCapabilities(accepts_paired=True, preserves_pairing=True),
            TransformCapabilities(),
            TransformCapabilities(accepts_paired=True, preserves_pairing=True),
        ),
    )

    assert result.incompatible_index == 1
    assert result.preserves_pairing is False


def test_fold_paired_capabilities_tracks_pairing_loss() -> None:
    result = fold_paired_capabilities(
        True,
        (TransformCapabilities(accepts_paired=True, preserves_pairing=False),),
    )

    assert result.incompatible_index is None
    assert result.preserves_pairing is False


def test_transform_result_reports_pairing() -> None:
    assert not TransformResult("value").is_paired
    assert TransformResult("value", id_value="id").is_paired


def test_base_transform_prepare_and_prove_defaults() -> None:
    transform = EchoTransform()
    prepared = transform.prepare({"type": "echo"}, None)
    result = transform.apply(prepared, TransformResult("x"), Random(0))

    assert result.value == "x"
    assert transform.prove(prepared, result, result) == TransformProof(ok=True)


def test_distribution_transform_chooses_prepared_candidate() -> None:
    transform = DistributionTransform()
    prepared = transform.prepare(
        {
            "type": "distribution",
            "choices": [
                {"weight": 0, "spec": {"type": "string", "values": ["never"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["always"]}},
            ],
        },
        PreparationContext(make_registry()),
    )

    assert prepared.cum_weights == (0.0, 1.0)
    result = transform.apply(prepared, TransformResult("ignored"), Random(0))

    assert result == TransformResult("always")


def test_distribution_transform_declares_nested_specs() -> None:
    transform = DistributionTransform()
    first = {"type": "string", "values": ["a"]}
    second = {"type": "integer", "minValue": 1, "maxValue": 2}

    assert transform.nested_specs(
        {"choices": [{"spec": first}, {"weight": 2, "spec": second}]}
    ) == ((("choices", 0, "spec"), first), (("choices", 1, "spec"), second))
    assert transform.nested_specs({"choices": "invalid"}) == ()


def test_distribution_transform_requires_two_choices() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare(
            {
                "type": "distribution",
                "choices": [
                    {"spec": {"type": "string", "values": ["only"]}},
                ],
            },
            PreparationContext(make_registry()),
        )
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_distribution_transform_rejects_negative_weight() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare(
            {
                "type": "distribution",
                "choices": [
                    {"weight": -1, "spec": {"type": "string", "values": ["bad"]}},
                    {"weight": 2, "spec": {"type": "string", "values": ["ok"]}},
                ],
            },
            PreparationContext(make_registry()),
        )
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_distribution_transform_rejects_boolean_weight_with_path() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare(
            {
                "type": "distribution",
                "choices": [
                    {"weight": True, "spec": {"type": "string", "values": ["bad"]}},
                    {"weight": 1, "spec": {"type": "string", "values": ["ok"]}},
                ],
            },
            PreparationContext(make_registry()),
        )
    except ValueError as exc:
        assert "choices[0].weight" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_distribution_transform_rejects_unknown_choice_key() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare(
            {
                "type": "distribution",
                "choices": [
                    {"spec": {"type": "string", "values": ["bad"]}, "extra": True},
                    {"spec": {"type": "string", "values": ["ok"]}},
                ],
            },
            PreparationContext(make_registry()),
        )
    except ValueError as exc:
        assert "distribution.choices[0].extra" in str(exc)
        assert "spec, weight" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_distribution_transform_rejects_zero_total_weight() -> None:
    transform = DistributionTransform()

    try:
        transform.prepare(
            {
                "type": "distribution",
                "choices": [
                    {"weight": 0, "spec": {"type": "string", "values": ["a"]}},
                    {"weight": 0, "spec": {"type": "string", "values": ["b"]}},
                ],
            },
            PreparationContext(make_registry()),
        )
    except ValueError as exc:
        assert "positive number" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_distribution_accepts_finite_weights_whose_raw_sum_would_overflow() -> None:
    """The distribution transform shares the scaled accumulation (SCALE-008)."""
    transform = DistributionTransform()

    prepared = transform.prepare(
        {
            "type": "distribution",
            "choices": [
                {"weight": 1e308, "spec": {"type": "string", "values": ["a"]}},
                {"weight": 1e308, "spec": {"type": "string", "values": ["b"]}},
            ],
        },
        PreparationContext(make_registry()),
    )

    assert all(isfinite(bound) for bound in prepared.cum_weights)
    drawn = {
        transform.apply(prepared, TransformResult("src"), Random(seed)).value for seed in range(40)
    }
    assert drawn == {"a", "b"}
