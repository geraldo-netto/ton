"""Unit tests for the row-generation engine."""

from __future__ import annotations

from random import Random
from threading import Barrier, Thread
from typing import Any

import pytest

from ton._engine import Engine, ProofError, TemplateError
from ton._proof import ProofResult
from ton._transforms import (
    BaseTransform,
    TransformCapabilities,
    TransformProof,
    TransformResult,
)
from ton.generators import Generator


def test_engine_yields_requested_row_count(basic_config: dict) -> None:
    basic_config["rows"] = 5
    rows = list(Engine(basic_config, rng=Random(0)))
    assert len(rows) == 5


def test_engine_is_deterministic_for_a_seed(basic_config: dict) -> None:
    first = list(Engine(basic_config, rng=Random(123)))
    second = list(Engine(basic_config, rng=Random(123)))
    assert first == second


def test_engine_rejects_unknown_template_var(basic_config: dict) -> None:
    basic_config["format"] = "$missing$"
    with pytest.raises(TemplateError):
        Engine(basic_config)


def test_engine_rejects_unknown_type(basic_config: dict) -> None:
    basic_config["types"]["n"]["type"] = "nope"
    with pytest.raises(TemplateError):
        Engine(basic_config)


def test_engine_wraps_unexpected_prepare_error_as_template_error() -> None:
    """A buggy third-party generator that raises a non-ValueError must still
    surface as TemplateError so the CLI maps to exit 2 (REL-012)."""
    from collections.abc import Mapping
    from typing import Any

    from ton.generators import Generator

    class BrokenGenerator(Generator):
        type_name = "broken"

        def prepare(self, spec: Mapping[str, Any]) -> Any:
            raise RuntimeError("third-party plugin blew up")

        def generate(self, prepared: Any, rng: Random) -> str:
            return ""

    registry = {"broken": BrokenGenerator()}
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "broken"}},
    }
    with pytest.raises(TemplateError, match="RuntimeError"):
        Engine(config, registry=registry)


def test_engine_pairs_lmhash_within_a_row() -> None:
    config = {
        "rows": 3,
        "format": "$word[id]$=$word$",
        "types": {"word": {"type": "lmhash", "values": ["alpha", "beta"]}},
    }
    for row in Engine(config, rng=Random(0)):
        plain, _, digest = row.partition("=")
        from ton.generators.lmhash import LMHashGenerator
        expected = LMHashGenerator._nt_hash(plain)
        assert digest == expected


def test_engine_rejects_concurrent_iteration(basic_config: dict) -> None:
    basic_config["rows"] = 2
    engine = Engine(basic_config, rng=Random(0))
    iterator = iter(engine)
    next(iterator)

    errors: list[BaseException] = []
    barrier = Barrier(2)

    def _iterate_again() -> None:
        barrier.wait()
        try:
            list(engine)
        except BaseException as exc:  # noqa: BLE001 - test captures thread failure
            errors.append(exc)

    thread = Thread(target=_iterate_again)
    thread.start()
    barrier.wait()
    thread.join(timeout=2)
    list(iterator)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "concurrently" in str(errors[0])


def test_engine_applies_transform_chain_to_single_value() -> None:
    class PrefixTransform(BaseTransform):
        type_name = "prefix"

        def apply(
            self,
            prepared: Any,
            value: TransformResult,
            rng: Random,
        ) -> TransformResult:
            del rng
            return TransformResult(f"{prepared['prefix']}{value.value}")

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "plugin.prefix", "prefix": "pre-"}],
            }
        },
    }

    rows = list(
        Engine(
            config,
            transforms={"plugin.prefix": PrefixTransform()},
            rng=Random(0),
        )
    )

    assert rows == ["pre-x"]


def test_engine_preserves_paired_value_through_identity_transform() -> None:
    config = {
        "rows": 1,
        "format": "$word[id]$=$word$",
        "types": {
            "word": {
                "type": "lmhash",
                "values": ["alpha"],
                "transforms": [{"type": "identity"}],
            }
        },
    }

    assert list(Engine(config, rng=Random(0))) == [
        "alpha=c89eee2b363e6de65346d055e0c839e1"
    ]


def test_engine_rejects_transform_that_cannot_accept_paired_input() -> None:
    class UnpairedTransform(BaseTransform):
        type_name = "unpaired"
        capabilities = TransformCapabilities(accepts_paired=False)

    config = {
        "rows": 1,
        "format": "$word[id]$=$word$",
        "types": {
            "word": {
                "type": "lmhash",
                "values": ["alpha"],
                "transforms": [{"type": "plugin.unpaired"}],
            }
        },
    }

    with pytest.raises(TemplateError, match="does not accept paired"):
        Engine(config, transforms={"plugin.unpaired": UnpairedTransform()})


def test_engine_collects_source_proof_failure() -> None:
    class ProvingGenerator(Generator):
        type_name = "proving"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="not allowed")

    config = {"rows": 1, "format": "$v$", "types": {"v": {"type": "proving"}}}
    engine = Engine(config, registry={"proving": ProvingGenerator()})
    field = engine._prepared["v"]

    failures = engine._proof_failures("v", field, TransformResult("bad"), ())

    assert failures[0].stage == "source"
    assert failures[0].reference == "proving"
    assert failures[0].reason == "not allowed"


def test_engine_collects_transform_proof_failure() -> None:
    class FailingProofTransform(BaseTransform):
        type_name = "failproof"

        def prove(
            self,
            prepared: Any,
            before: TransformResult,
            after: TransformResult,
        ) -> TransformProof:
            del prepared, before, after
            return TransformProof(ok=False, reason="transform mismatch")

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "plugin.failproof"}],
            }
        },
    }
    engine = Engine(config, transforms={"plugin.failproof": FailingProofTransform()})
    field = engine._prepared["v"]
    source = TransformResult("x")
    _, steps = engine._apply_transforms_with_trace(field, source)

    failures = engine._proof_failures("v", field, source, steps)

    assert failures[0].stage == "transform"
    assert failures[0].reference == "failproof"
    assert failures[0].reason == "transform mismatch"


def test_engine_strict_proof_mode_raises_with_context() -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    config = {"rows": 1, "format": "$v$", "types": {"v": {"type": "failing"}}}
    engine = Engine.from_config(
        config,
        registry={"failing": FailingGenerator()},
        seed=123,
        proof_mode="all",
    )

    with pytest.raises(ProofError, match="row 1.*'v'.*bad value"):
        list(engine)


def test_engine_audit_proof_mode_records_failures_without_stopping() -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    config = {"rows": 2, "format": "$v$", "types": {"v": {"type": "failing"}}}
    engine = Engine.from_config(
        config,
        registry={"failing": FailingGenerator()},
        seed=123,
        proof_mode="audit",
    )

    assert list(engine) == ["bad", "bad"]
    assert len(engine.proof_failures) == 2
    assert engine.proof_failures[0].seed == 123
    assert engine.proof_failures[0].spec == {"type": "failing"}


def test_engine_rejects_unknown_proof_mode(basic_config: dict) -> None:
    with pytest.raises(ValueError, match="proof_mode"):
        Engine(basic_config, proof_mode="sometimes")
