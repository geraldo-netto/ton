"""Unit tests for the row-generation engine."""

from __future__ import annotations

from random import Random
from typing import Any, ClassVar

import pytest

from ton._compiler import CompiledPlan
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


def test_compiled_plan_is_immutable() -> None:
    assert CompiledPlan.__dataclass_params__.frozen is True


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

    with pytest.raises(RuntimeError, match="concurrently"):
        iter(engine)

    assert list(iterator) != []


def test_engine_pickle_state_excludes_and_rebuilds_iteration_lock(basic_config: dict) -> None:
    engine = Engine(basic_config, rng=Random(0))

    state = engine.__getstate__()
    assert "_iteration_lock" not in state

    restored = object.__new__(Engine)
    restored.__setstate__(state)
    assert restored._iteration_lock.acquire(blocking=False)
    restored._iteration_lock.release()


def test_engine_applies_transform_chain_to_single_value() -> None:
    class PrefixTransform(BaseTransform):
        type_name: ClassVar[str] = "prefix"

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


def test_engine_resolves_unqualified_custom_transform_key() -> None:
    class PrefixTransform(BaseTransform):
        type_name: ClassVar[str] = "prefix"

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
                "transforms": [{"type": "prefix", "prefix": "pre-"}],
            }
        },
    }

    assert list(Engine(config, transforms={"prefix": PrefixTransform()})) == ["pre-x"]


def test_engine_rejects_unknown_transform() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "plugin.missing"}],
            }
        },
    }

    with pytest.raises(TemplateError, match="Unknown transform"):
        Engine(config)


def test_engine_keeps_explicitly_empty_transform_catalog() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "identity"}],
            }
        },
    }

    with pytest.raises(TemplateError, match="Unknown transform"):
        Engine(config, transforms={})


def test_lazy_registry_does_not_treat_transform_type_as_generator(monkeypatch) -> None:
    import ton._compiler as compiler_module

    requested: list[set[str]] = []
    real_make_registry = compiler_module.make_registry

    def recording_registry(type_names=None):
        requested.append(set(type_names or ()))
        return real_make_registry(type_names)

    monkeypatch.setattr(compiler_module, "make_registry", recording_registry)
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "identity"}],
            }
        },
    }

    assert list(Engine(config)) == ["x"]
    assert requested == [{"string"}, {"string"}]


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

    assert list(Engine(config, rng=Random(0))) == ["alpha=c89eee2b363e6de65346d055e0c839e1"]


def test_engine_rejects_transform_that_cannot_accept_paired_input() -> None:
    class UnpairedTransform(BaseTransform):
        type_name: ClassVar[str] = "unpaired"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(accepts_paired=False)

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

    failures = engine._proof.build_failures("v", field, TransformResult("bad"), ())

    assert failures[0].stage == "source"
    assert failures[0].reference == "proving"
    assert failures[0].reason == "not allowed"


def test_engine_collects_transform_proof_failure() -> None:
    class FailingProofTransform(BaseTransform):
        type_name: ClassVar[str] = "failproof"

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

    failures = engine._proof.build_failures("v", field, source, steps)

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


def test_engine_refuses_second_iteration_without_resetting_audit_failures() -> None:
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
        proof_mode="audit",
    )

    assert list(engine) == ["bad"]
    assert len(engine.proof_failures) == 1
    with pytest.raises(RuntimeError, match="single-shot"):
        list(engine)
    assert len(engine.proof_failures) == 1


def test_fresh_engines_repeat_seeded_random_and_sequence_state() -> None:
    config = {
        "rows": 3,
        "format": "$random$ $id$",
        "types": {
            "random": {"type": "integer", "minValue": 1, "maxValue": 5},
            "id": {"type": "sequence", "start": 10},
        },
    }

    first = list(Engine.from_config(config, seed=42))
    second = list(Engine.from_config(config, seed=42))

    assert first == second
    assert [row.split()[1] for row in first] == ["10", "11", "12"]


def test_engine_audit_proof_failures_bounded_but_counted(monkeypatch: Any) -> None:
    import ton._proofcheck as proofcheck

    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    monkeypatch.setattr(proofcheck, "MAX_AUDIT_SAMPLE", 2)
    config = {"rows": 5, "format": "$v$", "types": {"v": {"type": "failing"}}}
    engine = Engine.from_config(
        config,
        registry={"failing": FailingGenerator()},
        proof_mode="audit",
    )

    list(engine)
    # Detail retained is capped, but the total count and provenance
    # per-type tally stay accurate (SCAL-001).
    assert len(engine.proof_failures) == 2
    assert engine.proof_failure_count == 5
    assert engine.provenance[0].proof_failures == 5


def test_engine_provenance_reports_source_transforms_and_proof_state() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "identity"}],
            }
        },
    }
    engine = Engine.from_config(config, proof_mode="sample", proof_sample_rate=5)

    assert engine.provenance[0].type_key == "v"
    assert engine.provenance[0].source_type == "string"
    assert engine.provenance[0].transforms == ("identity",)
    assert engine.provenance[0].proof_mode == "sample"
    assert engine.provenance[0].proof_sample_rate == 5


def test_engine_provenance_attributes_plugin_package() -> None:
    from types import SimpleNamespace
    from unittest import mock

    from ton._registry import catalog_with_entry_points

    class WidgetGenerator(Generator):
        type_name = "widget"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "w"

    ep = mock.Mock()
    ep.name = "acme.widget"
    ep.value = "acme_pkg:WidgetGenerator"
    ep.load.return_value = WidgetGenerator
    ep.dist = SimpleNamespace(name="acme-pkg", version="9.9.9")

    def _entry_points(group: str) -> list[Any]:
        return [ep] if group == "ton.generators" else []

    with mock.patch("ton._registry.entry_points", side_effect=_entry_points):
        catalog = catalog_with_entry_points()

    config = {"rows": 1, "format": "$v$", "types": {"v": {"type": "acme.widget"}}}
    engine = Engine(config, registry=catalog.generators())

    record = engine.provenance[0]
    assert record.source_type == "widget"
    assert record.plugin_package == "acme-pkg"
    assert record.plugin_version == "9.9.9"


def test_engine_provenance_omits_plugin_package_for_builtins() -> None:
    engine = Engine({"rows": 1, "format": "$v$", "types": {"v": {"type": "name"}}})

    assert engine.provenance[0].plugin_package is None
    assert engine.provenance[0].plugin_version is None


def test_engine_provenance_reports_repeated_type_once() -> None:
    engine = Engine(
        {
            "rows": 1,
            "format": "$name$:$name$",
            "types": {"name": {"type": "name"}},
        },
    )

    assert [record.type_key for record in engine.provenance] == ["name"]


def test_engine_rejects_unknown_proof_mode(basic_config: dict) -> None:
    with pytest.raises(ValueError, match="proof_mode"):
        Engine(basic_config, proof_mode="sometimes")


def test_engine_sample_proof_mode_skips_unsampled_rows() -> None:
    class FailingSecondRowGenerator(Generator):
        type_name = "sampled"

        def __init__(self) -> None:
            self.count = 0

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            self.count += 1
            return f"row-{self.count}"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared
            return ProofResult(ok=result.value != "row-2", reason="bad second row")

    config = {"rows": 3, "format": "$v$", "types": {"v": {"type": "sampled"}}}
    rows = list(
        Engine.from_config(
            config,
            registry={"sampled": FailingSecondRowGenerator()},
            proof_mode="sample",
            proof_sample_rate=2,
        )
    )

    assert rows == ["row-1", "row-2", "row-3"]


def test_engine_sample_proof_mode_checks_sampled_rows() -> None:
    class AlwaysFailingGenerator(Generator):
        type_name = "sampled"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="sampled failure")

    config = {"rows": 2, "format": "$v$", "types": {"v": {"type": "sampled"}}}
    engine = Engine.from_config(
        config,
        registry={"sampled": AlwaysFailingGenerator()},
        proof_mode="sample",
        proof_sample_rate=2,
    )

    with pytest.raises(ProofError, match="sampled failure"):
        list(engine)


def test_engine_rejects_bad_proof_sample_rate(basic_config: dict) -> None:
    with pytest.raises(ValueError, match="proof_sample_rate"):
        Engine(basic_config, proof_mode="sample", proof_sample_rate=0)


def test_engine_applies_distribution_transform() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["ignored"],
                "transforms": [
                    {
                        "type": "distribution",
                        "choices": [
                            {"weight": 0, "spec": {"type": "string", "values": ["no"]}},
                            {"weight": 1, "spec": {"type": "string", "values": ["yes"]}},
                        ],
                    }
                ],
            }
        },
    }

    assert list(Engine(config, rng=Random(0))) == ["yes"]
