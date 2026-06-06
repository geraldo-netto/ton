"""Tests for transform contracts."""

from __future__ import annotations

from random import Random
from typing import Any

from ton._transforms import BaseTransform, TransformProof, TransformResult


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
