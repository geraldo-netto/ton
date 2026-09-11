"""Tests for the composite generators added in PAT-011 (oneOf, sequence_of).

Also covers the shared :func:`ton._contracts.prepare_child_spec`
helper, REL-019's paired-nested guard, and the LogEvent enum surface.
"""

from __future__ import annotations

from collections import Counter
from random import Random
from typing import Any

import pytest

from ton import api
from ton._contracts import Generator, PreparationContext, prepare_child_spec
from ton._engine import Engine, TemplateError
from ton._logging import LogEvent
from ton._validation import ValidationError
from ton.generators.one_of import OneOfGenerator
from ton.generators.sequence_of import SequenceOfGenerator

# ---------------------------------------------------------------------------
# oneOf
# ---------------------------------------------------------------------------


def _string_spec(value: str) -> dict[str, Any]:
    return {"type": "string", "values": [value]}


def test_one_of_picks_uniformly() -> None:
    config = {
        "rows": 300,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [_string_spec("A"), _string_spec("B"), _string_spec("C")],
            }
        },
    }
    counts = Counter(api.generate(config, seed=0))
    assert set(counts.keys()) == {"A", "B", "C"}
    # Uniform over 3 choices, 300 draws: each ~100 +/- generous slack.
    for label in "ABC":
        assert counts[label] > 40


def test_one_of_seed_deterministic() -> None:
    config = {
        "rows": 20,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [_string_spec(s) for s in ("x", "y", "z")],
            }
        },
    }
    first = list(api.generate(config, seed=7))
    second = list(api.generate(config, seed=7))
    assert first == second


def test_one_of_rejects_empty_choices() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "oneOf", "choices": []}},
    }
    with pytest.raises(TemplateError, match="non-empty"):
        list(api.generate(config))


def test_one_of_rejects_missing_choices_key() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "oneOf"}},
    }
    with pytest.raises(TemplateError, match="non-empty"):
        list(api.generate(config))


def test_one_of_rejects_paired_child() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [{"type": "hash", "algorithm": "ntlm", "values": ["a"]}],
            }
        },
    }
    with pytest.raises(TemplateError, match="paired"):
        list(api.generate(config))


def test_one_of_direct_prepare_rejected() -> None:
    generator = OneOfGenerator()
    spec = {"choices": [_string_spec("x")]}
    with pytest.raises(ValueError, match="composite"):
        generator.prepare(spec)


def test_one_of_can_nest_inside_weighted() -> None:
    config = {
        "rows": 50,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {
                        "weight": 1,
                        "spec": {
                            "type": "oneOf",
                            "choices": [_string_spec("inner-A"), _string_spec("inner-B")],
                        },
                    },
                ],
            }
        },
    }
    rows = list(api.generate(config, seed=0))
    assert all(r in {"inner-A", "inner-B"} for r in rows)


def test_one_of_applies_nested_transform_pipeline() -> None:
    config = {
        "rows": 10,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["source"],
                        "transforms": [
                            {
                                "type": "distribution",
                                "choices": [
                                    {"spec": _string_spec("A")},
                                    {"spec": _string_spec("B")},
                                ],
                            }
                        ],
                    }
                ],
            }
        },
    }

    assert set(api.generate(config, seed=0, proof_mode="all")) <= {"A", "B"}


def test_one_of_rejects_unknown_nested_transform() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["source"],
                        "transforms": [{"type": "missing"}],
                    }
                ],
            }
        },
    }

    with pytest.raises(api.ConfigError, match="Unknown transform 'missing'"):
        api.validate_config(config)


@pytest.mark.parametrize("transforms", ["identity", [{}]])
def test_one_of_rejects_malformed_nested_transforms(transforms: Any) -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["source"],
                        "transforms": transforms,
                    }
                ],
            }
        },
    }

    with pytest.raises(api.ConfigError, match="must be a list|with a string 'type'"):
        api.validate_config(config)


def test_one_of_runs_nested_validators() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": [""],
                        "validators": ["non_empty"],
                    }
                ],
            }
        },
    }

    with pytest.raises(ValidationError, match="non_empty"):
        list(api.generate(config))


@pytest.mark.parametrize("validators", ["non_empty", [123]])
def test_one_of_rejects_malformed_nested_validators(validators: Any) -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["source"],
                        "validators": validators,
                    }
                ],
            }
        },
    }

    with pytest.raises(api.ConfigError, match="Validators|Validator references"):
        api.validate_config(config)


def test_one_of_rejects_unknown_nested_validator() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "oneOf",
                "choices": [
                    {
                        "type": "string",
                        "values": ["source"],
                        "validators": ["missing"],
                    }
                ],
            }
        },
    }

    with pytest.raises(api.ConfigError, match="Unknown validator 'missing'"):
        api.validate_config(config)


# ---------------------------------------------------------------------------
# sequence_of
# ---------------------------------------------------------------------------


def test_sequence_of_concatenates_count_draws_with_separator() -> None:
    config = {
        "rows": 5,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 4,
                "separator": "-",
                "spec": {"type": "integer", "minValue": 0, "maxValue": 9, "padWithZero": False},
            }
        },
    }
    rows = list(api.generate(config, seed=0))
    for row in rows:
        parts = row.split("-")
        assert len(parts) == 4
        for p in parts:
            assert p.isdigit()
            assert 0 <= int(p) <= 9


def test_sequence_of_empty_separator_concatenates_directly() -> None:
    config = {
        "rows": 5,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 3,
                "spec": _string_spec("X"),
            }
        },
    }
    rows = list(api.generate(config, seed=0))
    assert all(row == "XXX" for row in rows)


def test_sequence_of_rejects_count_zero() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 0,
                "spec": _string_spec("X"),
            }
        },
    }
    with pytest.raises(TemplateError, match=">= 1"):
        list(api.generate(config))


def test_sequence_of_honors_large_operator_requested_count() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 10_001,
                "spec": _string_spec("X"),
            }
        },
    }
    assert list(api.generate(config)) == ["X" * 10_001]


def test_sequence_of_rejects_non_string_separator() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 2,
                "separator": 42,
                "spec": _string_spec("X"),
            }
        },
    }
    with pytest.raises(TemplateError, match="separator"):
        list(api.generate(config))


def test_sequence_of_rejects_paired_child() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 2,
                "spec": {"type": "hash", "algorithm": "ntlm", "values": ["a"]},
            }
        },
    }
    with pytest.raises(TemplateError, match="paired"):
        list(api.generate(config))


def test_sequence_of_direct_prepare_rejected() -> None:
    generator = SequenceOfGenerator()
    spec = {
        "count": 1,
        "spec": _string_spec("x"),
    }
    with pytest.raises(ValueError, match="composite"):
        generator.prepare(spec)


def test_sequence_of_can_nest_other_composites() -> None:
    config = {
        "rows": 4,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": 2,
                "separator": "|",
                "spec": {
                    "type": "weighted",
                    "choices": [{"weight": 1, "spec": _string_spec("Z")}],
                },
            }
        },
    }
    assert list(api.generate(config, seed=0)) == ["Z|Z"] * 4


# ---------------------------------------------------------------------------
# prepare_child_spec direct error paths
# ---------------------------------------------------------------------------


def test_prepare_child_spec_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        prepare_child_spec("custom", ("spec",), "not-a-mapping", {})


def test_prepare_child_spec_rejects_missing_type_field() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        prepare_child_spec("custom", ("spec",), {"values": ["x"]}, {})


def test_prepare_child_spec_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        prepare_child_spec("custom", ("spec",), {"type": "nope"}, {})


def test_preparation_context_resolves_children_through_shared_registry() -> None:
    registry = {"string": api.build_extension_catalog().get_data_type("string")}
    context = PreparationContext(registry)

    generator, prepared = context.prepare_child(
        "custom", ("spec",), {"type": "string", "values": ["x"]}
    )

    assert generator.generate(prepared, Random(0)) == "x"


def test_generator_nested_spec_hook_defaults_empty_and_is_extensible() -> None:
    class Composite(Generator):
        type_name = "composite"

        def nested_specs(self, spec):
            return tuple(
                (("children", index), child) for index, child in enumerate(spec["children"])
            )

        def generate(self, prepared, rng):
            return ""

    assert Generator.nested_specs(Composite(), {}) == ()
    assert Composite().nested_specs({"children": [{"type": "string"}, {"type": "integer"}]}) == (
        (("children", 0), {"type": "string"}),
        (("children", 1), {"type": "integer"}),
    )
    assert not hasattr(Generator, "nested_types")
    assert not hasattr(Generator, "_nested_type_names")


@pytest.mark.parametrize(
    ("generator", "spec", "expected"),
    [
        (
            OneOfGenerator(),
            {"choices": [{"type": "string"}, {"type": "sequence_of", "spec": {"type": "char"}}]},
            (
                (("choices", 0), {"type": "string"}),
                (("choices", 1), {"type": "sequence_of", "spec": {"type": "char"}}),
            ),
        ),
        (
            SequenceOfGenerator(),
            {"spec": {"type": "oneOf", "choices": [{"type": "integer"}]}},
            ((("spec",), {"type": "oneOf", "choices": [{"type": "integer"}]}),),
        ),
    ],
)
def test_builtin_composites_declare_direct_owned_specs(generator, spec, expected) -> None:
    assert generator.nested_specs(spec) == expected


def test_plugin_composite_must_declare_prepared_children() -> None:
    """ARCH-023: compilation cannot silently accept children worker traversal cannot see."""

    class Undeclared(Generator):
        type_name = "undeclared"

        def prepare(self, spec, context=None):
            return context.prepare_child(self.type_name, ("child",), spec["child"])

        def generate(self, prepared, rng):
            return prepared[0].generate(prepared[1], rng)

    registry = api.build_extension_catalog().generators()
    registry["undeclared"] = Undeclared()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {
            "x": {"type": "undeclared", "child": {"type": "sequence"}},
        },
    }
    with pytest.raises(TemplateError, match="types.x.child.*nested_specs"):
        Engine(config, registry=registry)


def test_plugin_composite_uses_public_preparation_context() -> None:
    """ARCH-023: declared plugin children prepare and receive worker sequence offsets."""

    class Wrapper(Generator):
        type_name = "wrapper"

        def prepare(self, spec, context=None):
            assert context is not None
            return context.prepare_child("wrapper", ("child",), spec["child"])

        def nested_specs(self, spec):
            return ((("child",), spec["child"]),)

        def generate(self, prepared, rng):
            generator, child = prepared
            return f"[{generator.generate(child, rng)}]"

    registry = api.build_extension_catalog().generators()
    registry["wrapper"] = Wrapper()
    config = {
        "rows": 4,
        "format": "$value$",
        "types": {
            "value": {
                "type": "wrapper",
                "child": {"type": "sequence"},
            }
        },
    }

    assert list(Engine(config, registry=registry)) == ["[0]", "[1]", "[2]", "[3]"]
    worker = api.fork_engine(
        config,
        parent_seed=0,
        worker_id=1,
        workers=2,
        rows=2,
        options=api.EngineOptions(registry=registry),
    )
    assert list(worker) == ["[2]", "[3]"]


# ---------------------------------------------------------------------------
# REL-019: weighted also blocks paired children (regression guard)
# ---------------------------------------------------------------------------


def test_weighted_rejects_paired_child_type() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {
                        "weight": 1,
                        "spec": {"type": "hash", "algorithm": "ntlm", "values": ["a"]},
                    },
                ],
            }
        },
    }
    with pytest.raises(TemplateError, match="paired"):
        list(api.generate(config))


# ---------------------------------------------------------------------------
# PAT-010: LogEvent enum surface + on-the-wire values
# ---------------------------------------------------------------------------


def test_log_event_enum_values_are_canonical_strings() -> None:
    # Every member must serialise to a snake_case ASCII string so
    # downstream JSON / log handlers see stable identifiers across
    # Python versions.
    for member in LogEvent:
        assert isinstance(member.value, str)
        assert member.value == member.value.lower()
        assert all(ch.isalnum() or ch == "_" for ch in member.value)


def test_log_event_enum_supports_value_round_trip() -> None:
    assert LogEvent("engine_constructed") is LogEvent.ENGINE_CONSTRUCTED
    assert LogEvent.ENGINE_PROGRESS.value == "engine_progress"


def test_engine_emits_log_event_value_in_extra(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="ton"):
        list(
            api.generate(
                {
                    "rows": 1,
                    "format": "$n$",
                    "types": {
                        "n": {"type": "integer", "minValue": 0, "maxValue": 1, "padWithZero": False}
                    },
                },
                seed=0,
            )
        )
    events = {getattr(r, "event", None) for r in caplog.records}
    assert LogEvent.ENGINE_CONSTRUCTED.value in events
    assert LogEvent.ENGINE_COMPLETED.value in events


def test_engine_total_rows_property() -> None:
    engine = Engine.from_config(
        {
            "rows": 17,
            "format": "$n$",
            "types": {"n": {"type": "integer", "minValue": 0, "maxValue": 1, "padWithZero": False}},
        },
        seed=0,
    )
    assert engine.total_rows == 17
    rng = Random()
    del rng  # placate unused-warning lint on the Random import elsewhere


@pytest.mark.parametrize("key", ["child", "item[0]", "", "'quoted'"])
def test_plugin_child_preparation_keeps_distinct_occurrences(key):
    """PLUG-023: diagnostic path spellings cannot identify prepared children."""

    class Branch(Generator):
        type_name = "branch"

        def nested_specs(self, spec):
            return tuple(((name,), child) for name, child in spec.items() if name != "type")

        def prepare(self, spec, context=None):
            return tuple(
                context.prepare_child(self.type_name, location, child)
                for location, child in self.nested_specs(spec)
            )

        def generate(self, prepared, rng):
            return "/".join(generator.generate(child, rng) for generator, child in prepared)

    registry = api.build_extension_catalog().generators()
    registry["branch"] = Branch()
    field = {
        "type": "branch",
        "a": {"type": "branch", key: {"type": "string", "values": ["nested"]}},
        "a." + key: {"type": "string", "values": ["literal"]},
    }
    config = {"rows": 2, "format": "$x$", "types": {"x": field}}
    assert list(api.generate(config, registry=registry, proof_mode="all")) == ["nested/literal"] * 2
