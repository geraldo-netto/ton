"""Unit tests for the row-generation engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from random import Random
from typing import Any, ClassVar

import pytest

from ton._compiler import CompiledPlan, EngineCompiler
from ton._config import ConfigError
from ton._engine import (
    Engine,
    GeneratorExecutionError,
    ProofError,
    ProofEvaluationError,
    TemplateError,
    TransformExecutionError,
    ValidatorExecutionError,
)
from ton._proof import ProofResult
from ton._registry import make_registry
from ton._transforms import (
    BaseTransform,
    IdentityTransform,
    TransformCapabilities,
    TransformProof,
    TransformResult,
)
from ton.generators import Generator, PairedGenerator


def test_engine_yields_requested_row_count(basic_config: dict) -> None:
    basic_config["rows"] = 5
    rows = list(Engine(basic_config, rng=Random(0)))
    assert len(rows) == 5


def test_rows_emitted_updates_at_each_yield(basic_config: dict) -> None:
    engine = Engine(basic_config, rng=Random(0))
    rows = iter(engine)

    next(rows)

    assert engine.rows_emitted == 1
    rows.close()


def test_compiled_plan_is_immutable() -> None:
    assert CompiledPlan.__dataclass_params__.frozen is True


def test_compiled_tokens_resolve_direct_generation_fields(basic_config: dict) -> None:
    engine = Engine(basic_config, rng=Random(0))

    resolved = engine._plan.resolved_tokens
    assert len(resolved) == 1
    assert resolved[0].field is engine._plan.prepared[resolved[0].token.type_key]
    assert resolved[0].direct is True


def test_direct_generation_matches_slow_path_and_skips_proof_objects(
    basic_config: dict, monkeypatch: Any
) -> None:
    direct = Engine.from_config(basic_config, seed=7)
    slow = Engine.from_config(basic_config, seed=7)
    slow._plan = replace(
        slow._plan,
        resolved_tokens=tuple(replace(token, direct=False) for token in slow._plan.resolved_tokens),
    )

    assert list(direct) == list(slow)

    guarded = Engine.from_config(basic_config, seed=7)
    monkeypatch.setattr(
        guarded._proof,
        "evaluate",
        lambda *args, **kwargs: pytest.fail("direct path evaluated proof"),
    )
    assert len(list(guarded)) == basic_config["rows"]


def test_paired_fields_and_generator_errors_bypass_direct_path() -> None:
    paired = Engine(
        {
            "rows": 1,
            "format": "$word[id]$:$word$",
            "types": {"word": {"type": "hash", "algorithm": "ntlm", "values": ["secret"]}},
        }
    )
    assert paired._plan.resolved_tokens[0].direct is False
    plain, digest = list(paired)[0].split(":")
    assert plain == "secret"
    assert digest

    class BrokenGenerator(Generator):
        type_name = "broken"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            raise RuntimeError("boom")

    broken = Engine(
        {"rows": 1, "format": "$v$", "types": {"v": {"type": "broken"}}},
        registry={"broken": BrokenGenerator()},
    )
    with pytest.raises(GeneratorExecutionError, match="BrokenGenerator.*RuntimeError: boom"):
        list(broken)

    class BrokenPairGenerator(PairedGenerator):
        type_name = "broken_pair"

        def generate_pair(self, prepared: Any, rng: Random) -> tuple[str, str]:
            raise RuntimeError("pair boom")

    broken_pair = Engine(
        {
            "rows": 1,
            "format": "$v[id]$",
            "types": {"v": {"type": "broken_pair"}},
        },
        registry={"broken_pair": BrokenPairGenerator()},
    )
    with pytest.raises(GeneratorExecutionError, match="BrokenPairGenerator.*pair boom"):
        list(broken_pair)


@pytest.mark.parametrize("location", ["root", "oneOf", "distribution"])
@pytest.mark.parametrize("crash", [False, True])
def test_nested_validator_attribution_matches_root(
    location, crash, caplog, capsys, tmp_path, monkeypatch
):
    """REL-047: nested validator failures retain their component, row and CLI category."""
    import json

    from ton import api
    from ton.cli import main

    class Explode:
        type_name = "explode"

        def __init__(self):
            self.calls = 0

        def validate(self, value):
            self.calls += 1
            if self.calls == 1:
                return True
            if crash:
                raise RuntimeError("validator boom")
            return False

    child = {"type": "string", "values": ["x"], "validators": ["acme.explode"]}
    spec = child
    if location == "oneOf":
        spec = {"type": "oneOf", "choices": [child]}
    if location == "distribution":
        spec = {
            "type": "string",
            "values": ["unused"],
            "transforms": [
                {
                    "type": "distribution",
                    "choices": [
                        {"weight": 1, "spec": child},
                        {"weight": 0, "spec": {"type": "string", "values": ["unused"]}},
                    ],
                },
            ],
        }
    config = {"rows": 3, "format": "$x$", "types": {"x": spec}}
    engine = Engine.from_config(config, validators={"acme.explode": Explode()})
    error_type = ValidatorExecutionError if crash else api.ValidationError
    with caplog.at_level("ERROR", logger="ton"), pytest.raises(error_type) as raised:
        list(engine)
    if crash:
        assert raised.value.reference == "explode"
        assert raised.value.type_key == "x"
        assert isinstance(raised.value.cause, RuntimeError)
        failures = [r for r in caplog.records if getattr(r, "event", "") == "generate_failed"]
        assert len(failures) == 1
        assert (failures[0].stage, failures[0].reference, failures[0].row) == (
            "Validator",
            "explode",
            2,
        )
    caplog.clear()
    catalog = api.build_extension_catalog()
    catalog.register_validator("acme", "explode", Explode())
    monkeypatch.setattr(api, "build_extension_catalog", lambda **kwargs: catalog)
    path = tmp_path / "validator.json"
    path.write_text(json.dumps(config))
    assert main([str(path), "--entry-points"]) == (3 if crash else 2)
    assert "explode" in capsys.readouterr().err
    terminal = next(r for r in caplog.records if getattr(r, "event", "") == "cli_failed")
    assert terminal.error_category == ("pipeline" if crash else "validation")
    assert terminal.rows_written == 1


def test_pipeline_failures_identify_transform_validator_and_proof_stages() -> None:
    class BrokenTransform(BaseTransform):
        type_name = "broken_transform"

        def apply(self, prepared, value, rng):
            raise RuntimeError("transform boom")

    transform_config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "broken_transform"}],
            }
        },
    }
    transform_engine = Engine(transform_config, transforms={"broken_transform": BrokenTransform()})
    with pytest.raises(TransformExecutionError, match="Transform broken_transform.*transform boom"):
        list(transform_engine)

    class BrokenValidator:
        type_name = "broken_validator"

        def validate(self, value: str) -> bool:
            raise RuntimeError("validator boom")

    validator_config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "validators": ["broken_validator"],
            }
        },
    }
    validator_engine = Engine(validator_config, validators={"broken_validator": BrokenValidator()})
    with pytest.raises(ValidatorExecutionError, match="Validator broken_validator.*validator boom"):
        list(validator_engine)

    class BrokenProof(Generator):
        type_name = "broken_proof"

        def generate(self, prepared, rng):
            return "x"

        def prove(self, prepared, result):
            raise RuntimeError("proof boom")

    proof_config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "broken_proof"}},
    }
    proof_engine = Engine(proof_config, registry={"broken_proof": BrokenProof()}, proof_mode="all")
    with pytest.raises(ProofEvaluationError, match="Source proof broken_proof.*proof boom"):
        list(proof_engine)

    class BrokenTransformProof(BaseTransform):
        type_name = "broken_transform_proof"

        def prove(self, prepared, before, after):
            raise RuntimeError("transform proof boom")

    transform_proof_config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "broken_transform_proof"}],
            }
        },
    }
    transform_proof_engine = Engine(
        transform_proof_config,
        transforms={"broken_transform_proof": BrokenTransformProof()},
        proof_mode="all",
    )
    with pytest.raises(
        ProofEvaluationError,
        match="Transform proof broken_transform_proof.*transform proof boom",
    ):
        list(transform_proof_engine)


def test_engine_runtime_state_uses_compiled_plan(basic_config: dict) -> None:
    engine = Engine.from_config(basic_config, seed=1)

    assert engine.total_rows == engine._plan.rows
    assert set(engine._plan.prepared) == {"n"}
    assert not hasattr(engine, "_types")
    assert list(engine) != []


def test_engine_is_deterministic_for_a_seed(basic_config: dict) -> None:
    first = list(Engine(basic_config, rng=Random(123)))
    second = list(Engine(basic_config, rng=Random(123)))
    assert first == second


def test_engine_rejects_unknown_template_var(basic_config: dict) -> None:
    basic_config["format"] = "$missing$"
    with pytest.raises(ConfigError):
        Engine(basic_config)


def test_engine_rejects_unknown_type(basic_config: dict) -> None:
    basic_config["types"]["n"]["type"] = "nope"
    with pytest.raises(TemplateError):
        Engine(basic_config)


def test_engine_wraps_unexpected_prepare_error_as_template_error() -> None:
    """A buggy third-party generator that raises a non-ValueError must still
    surface as TemplateError so the CLI maps to exit 2 (REL-012)."""
    from ton.generators import Generator

    class BrokenGenerator(Generator):
        type_name = "broken"

        def prepare(self, spec: Mapping[str, Any], context: Any = None) -> Any:
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


def test_engine_pairs_ntlm_within_a_row() -> None:
    config = {
        "rows": 3,
        "format": "$word[id]$=$word$",
        "types": {"word": {"type": "hash", "algorithm": "ntlm", "values": ["alpha", "beta"]}},
    }
    for row in Engine(config, rng=Random(0)):
        plain, _, digest = row.partition("=")
        from ton.generators.hash import _ntlm_digest

        expected = _ntlm_digest(plain)
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


def test_lazy_registry_discovers_distribution_choice_types() -> None:
    config = {
        "rows": 20,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["not drawn"],
                "transforms": [
                    {
                        "type": "distribution",
                        "choices": [
                            {"weight": 1, "spec": {"type": "string", "values": ["s"]}},
                            {
                                "weight": 1,
                                "spec": {
                                    "type": "integer",
                                    "minValue": 1,
                                    "maxValue": 1,
                                },
                            },
                        ],
                    }
                ],
            }
        },
    }

    assert set(Engine.from_config(config, seed=0)) == {"s", "1"}


@pytest.mark.parametrize(
    "transforms",
    ["distribution", [None], [{}]],
)
def test_transform_child_discovery_ignores_malformed_specs(transforms: Any) -> None:
    config = {
        "rows": 0,
        "format": "$v$",
        "types": {"v": {"type": "string", "values": ["x"]}},
    }
    compiler = EngineCompiler(config, None, None, None)

    assert compiler._transform_child_specs({"transforms": transforms}) == ()


def test_engine_preserves_paired_value_through_identity_transform() -> None:
    config = {
        "rows": 1,
        "format": "$word[id]$=$word$",
        "types": {
            "word": {
                "type": "hash",
                "algorithm": "ntlm",
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
                "type": "hash",
                "algorithm": "ntlm",
                "values": ["alpha"],
                "transforms": [{"type": "plugin.unpaired"}],
            }
        },
    }

    transform = UnpairedTransform()
    with pytest.raises(TemplateError, match="does not accept paired"):
        Engine(config, transforms={"plugin.unpaired": transform})


@pytest.mark.parametrize("chain", [["plugin.drop"], ["plugin.drop", "identity"]])
def test_engine_rejects_id_reference_after_transform_drops_pairing(chain: list[str]) -> None:
    class DropPairTransform(BaseTransform):
        type_name: ClassVar[str] = "drop"
        capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(True, False)

        def apply(self, prepared, value, rng):
            del prepared, rng
            return TransformResult(value.value)

    config = {
        "rows": 1,
        "format": "$word[id]$",
        "types": {
            "word": {
                "type": "hash",
                "algorithm": "ntlm",
                "values": ["alpha"],
                "transforms": [{"type": reference} for reference in chain],
            }
        },
    }

    transforms = {"plugin.drop": DropPairTransform(), "identity": IdentityTransform()}
    with pytest.raises(TemplateError, match=r"cannot use \[id\].*does not preserve pairing"):
        Engine(config, transforms=transforms)


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
    field = engine._plan.prepared["v"]

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
    engine = Engine(
        config, transforms={"plugin.failproof": FailingProofTransform()}, proof_mode="all"
    )
    field = engine._plan.prepared["v"]
    source = TransformResult("x")
    _, steps = engine._apply_transforms_with_trace("v", field, source)

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
    seen_specs: list[Mapping[str, Any] | None] = []
    original_make_failure = proofcheck.ProofChecker._make_failure

    def track_spec(self: Any, **kwargs: Any) -> Any:
        seen_specs.append(kwargs["spec"])
        return original_make_failure(self, **kwargs)

    monkeypatch.setattr(proofcheck.ProofChecker, "_make_failure", track_spec)
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
    assert all(spec is None for spec in seen_specs)
    assert all(failure.spec == {"type": "failing"} for failure in engine.proof_failures)


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


def test_default_engine_does_not_build_unused_generators(monkeypatch) -> None:
    import ton._registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "make_registry",
        lambda: pytest.fail("full generator catalog constructed"),
    )

    assert list(Engine({"rows": 1, "format": "$v$", "types": {"v": {"type": "name"}}}))


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
    class FailingFirstRowGenerator(Generator):
        type_name = "sampled"

        def __init__(self) -> None:
            self.count = 0

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            self.count += 1
            return f"row-{self.count}"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared
            return ProofResult(ok=result.value != "row-1", reason="bad first row")

    config = {"rows": 3, "format": "$v$", "types": {"v": {"type": "sampled"}}}
    rows = list(
        Engine.from_config(
            config,
            registry={"sampled": FailingFirstRowGenerator()},
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


@pytest.mark.parametrize("rate", [0, -1, True, False, 2.9, float("nan"), float("inf")])
def test_engine_rejects_bad_proof_sample_rate(basic_config: dict, rate) -> None:
    """CLI-022: API sampling must reject non-positive or non-integral rates."""
    with pytest.raises(ValueError, match="proof_sample_rate"):
        Engine.from_config(basic_config, proof_mode="sample", proof_sample_rate=rate)


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


def test_distribution_short_circuits_unrelated_source_generation() -> None:
    class UnusedSource(Generator):
        type_name = "unused_source"

        def generate(self, prepared, rng):
            pytest.fail("distribution executed its unrelated source")

        def prove(self, prepared, result):
            pytest.fail("distribution proved its unrelated source")

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "unused_source",
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
    registry = {**make_registry(), "unused_source": UnusedSource()}

    assert list(Engine(config, registry=registry, rng=Random(0), proof_mode="all")) == ["yes"]
