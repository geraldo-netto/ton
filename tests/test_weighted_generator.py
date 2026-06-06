"""Tests for the weighted generator."""

from __future__ import annotations

from collections import Counter
from random import Random

import pytest

from ton._registry import default_registry
from ton.generators.weighted import WeightedGenerator


def test_weighted_parallel_arrays_distribution() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare({"values": ["A", "B"], "weights": [9, 1]})
    rng = Random(0)
    counts = Counter(gen.generate(prepared, rng) for _ in range(2000))
    # 90/10 split; allow generous slack.
    assert counts["A"] > counts["B"] * 4


def test_weighted_record_form() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare({
        "values": [{"value": "x", "weight": 1}, {"value": "y", "weight": 0}],
    })
    rng = Random(0)
    assert all(gen.generate(prepared, rng) == "x" for _ in range(50))


def test_weighted_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": [], "weights": []})


def test_weighted_rejects_mismatched_weights() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A", "B"], "weights": [1]})


def test_weighted_rejects_negative_weight() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A"], "weights": [-1]})


def test_weighted_rejects_zero_total() -> None:
    with pytest.raises(ValueError):
        WeightedGenerator().prepare({"values": ["A", "B"], "weights": [0, 0]})


# ---------------------------------------------------------------------------
# Composite form: 'choices' with nested type specs (any registered type).
# ---------------------------------------------------------------------------


def test_weighted_composite_mixes_types_via_engine() -> None:
    """A weighted 'choices' spec routes draws through nested generators."""
    from ton import api

    config = {
        "rows": 200,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {"weight": 70,
                     "spec": {"type": "string", "values": ["STR"]}},
                    {"weight": 30,
                     "spec": {"type": "integer",
                              "minValue": 0, "maxValue": 9,
                              "padWithZero": False}},
                ],
            }
        },
    }
    rows = list(api.generate(config, seed=0))
    str_hits = sum(1 for r in rows if r == "STR")
    int_hits = sum(1 for r in rows if r.isdigit())
    assert str_hits + int_hits == 200
    # 70/30 split; allow wide slack.
    assert str_hits > int_hits


def test_weighted_composite_uses_distribution_delegate() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare_composite(
        {
            "type": "weighted",
            "choices": [
                {"weight": 0, "spec": {"type": "string", "values": ["never"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["always"]}},
            ],
        },
        default_registry(),
    )

    assert gen.generate(prepared, Random(0)) == "always"


def test_weighted_composite_accepts_core_qualified_child_type() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare_composite(
        {
            "type": "weighted",
            "choices": [
                {"weight": 1, "spec": {"type": "core.string", "values": ["ok"]}},
            ],
        },
        default_registry(),
    )

    assert gen.generate(prepared, Random(0)) == "ok"


def test_weighted_composite_can_nest_inside_weighted() -> None:
    from ton import api

    config = {
        "rows": 50,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {"weight": 1, "spec": {
                        "type": "weighted",
                        "choices": [
                            {"weight": 1, "spec": {"type": "string",
                                                    "values": ["inner-a"]}},
                            {"weight": 1, "spec": {"type": "string",
                                                    "values": ["inner-b"]}},
                        ],
                    }},
                    {"weight": 0, "spec": {"type": "string", "values": ["zzz"]}},
                ],
            }
        },
    }
    rows = list(api.generate(config, seed=0))
    assert all(r in {"inner-a", "inner-b"} for r in rows)


def test_weighted_composite_rejects_direct_prepare_call() -> None:
    """``WeightedGenerator.prepare`` cannot resolve nested specs without
    the engine's registry; calling it on a composite spec is an error."""
    with pytest.raises(ValueError, match="composite"):
        WeightedGenerator().prepare({
            "choices": [
                {"weight": 1, "spec": {"type": "string", "values": ["x"]}},
            ],
        })


def test_weighted_composite_rejects_unknown_nested_type() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {
            "type": "weighted",
            "choices": [
                {"weight": 1, "spec": {"type": "no_such_type"}},
            ],
        }},
    }
    with pytest.raises(TemplateError, match="no_such_type"):
        list(api.generate(config))


def test_weighted_composite_rejects_empty_choices() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "weighted", "choices": []}},
    }
    with pytest.raises(TemplateError, match="non-empty"):
        list(api.generate(config))


def test_weighted_composite_defaults_to_uniform_when_weight_omitted() -> None:
    """A choice without a ``weight`` field contributes 1.0 (uniform fallback)."""
    from collections import Counter

    from ton import api

    config = {
        "rows": 300,
        "format": "$v$",
        "types": {"v": {
            "type": "weighted",
            "choices": [
                {"spec": {"type": "string", "values": ["A"]}},
                {"spec": {"type": "string", "values": ["B"]}},
                {"spec": {"type": "string", "values": ["C"]}},
            ],
        }},
    }
    counts = Counter(api.generate(config, seed=0))
    # Uniform over 3 choices: each ~100 +/- generous slack.
    assert set(counts) == {"A", "B", "C"}
    for label in "ABC":
        assert 50 < counts[label] < 200


def test_weighted_composite_rejects_non_numeric_weight() -> None:
    """Explicit but malformed ``weight`` is still rejected."""
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {
            "type": "weighted",
            "choices": [{"weight": "abc",
                         "spec": {"type": "string", "values": ["x"]}}],
        }},
    }
    with pytest.raises(TemplateError, match="numeric"):
        list(api.generate(config))


def test_weighted_composite_rejects_choice_missing_spec() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {
            "type": "weighted",
            "choices": [{"weight": 1, "spec": {"values": ["x"]}}],
        }},
    }
    with pytest.raises(TemplateError, match="type"):
        list(api.generate(config))


def test_weighted_composite_rejects_non_mapping_choice() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {
            "type": "weighted",
            "choices": ["not-an-object"],
        }},
    }
    with pytest.raises(TemplateError, match="weight"):
        list(api.generate(config))
