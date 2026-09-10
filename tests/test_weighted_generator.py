"""Tests for the weighted generator."""

from __future__ import annotations

from collections import Counter
from math import isfinite
from random import Random

import pytest

from ton._registry import make_registry
from ton.generators.base import PreparationContext
from ton.generators.weighted import WeightedGenerator


def _choices(*weights: object) -> dict[str, object]:
    """Build a composite weighted spec carrying ``weights`` in order."""
    return {
        "type": "weighted",
        "choices": [
            {"weight": weight, "spec": {"type": "string", "values": [f"v{index}"]}}
            for index, weight in enumerate(weights)
        ],
    }


@pytest.mark.parametrize("value", [None, {}, [], "not-numeric"])
def test_exact_weights_reject_non_numeric_inputs(value) -> None:
    """SCALE-016: exact arithmetic retains contextual numeric validation."""
    with pytest.raises(ValueError, match="must be numeric"):
        WeightedGenerator().prepare(_choices(value, 1), PreparationContext(make_registry()))


def test_weighted_rejects_empty_choices() -> None:
    """REL-048: validate current choices with a real composite context."""
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="non-empty list"):
        generator.prepare(_choices(), PreparationContext(make_registry()))


def test_weighted_rejects_malformed_choice() -> None:
    """REL-048: reject the malformed wrapper, not a missing context."""
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="must be an object"):
        generator.prepare({"choices": [1]}, PreparationContext(make_registry()))


def test_weighted_rejects_negative_weight() -> None:
    """REL-048: exercise weight validation rather than the context guard."""
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="non-negative"):
        generator.prepare(_choices(-1), PreparationContext(make_registry()))


def test_weighted_rejects_zero_total() -> None:
    """REL-048: reach zero-total validation through the supported schema."""
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="sum to a positive number"):
        generator.prepare(_choices(0, 0), PreparationContext(make_registry()))


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_weighted_rejects_non_finite_weights(weight: float) -> None:
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="finite"):
        generator.prepare(_choices(weight, 1), PreparationContext(make_registry()))


def test_weighted_accepts_finite_weights_whose_raw_sum_would_overflow() -> None:
    """Finite representable weights must not be rejected for their sum (SCALE-008)."""
    generator = WeightedGenerator()

    prepared = generator.prepare(_choices(1e308, 1e308), PreparationContext(make_registry()))

    assert all(isfinite(bound) for bound in prepared.cum_weights)
    counts = Counter(generator.generate(prepared, Random(seed)) for seed in range(400))
    assert set(counts) == {"v0", "v1"}
    assert abs(counts["v0"] - counts["v1"]) < 120


def test_weighted_still_rejects_weights_that_are_all_zero() -> None:
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="must sum to a positive number"):
        generator.prepare(_choices(0, 0), PreparationContext(make_registry()))


@pytest.mark.parametrize(
    ("spec", "path"),
    [
        (_choices(True), r"choices\[0\]\.weight"),
        (_choices(False), r"choices\[0\]\.weight"),
    ],
)
def test_weighted_rejects_boolean_weights(spec: dict[str, object], path: str) -> None:
    generator = WeightedGenerator()
    with pytest.raises(ValueError, match=path):
        generator.prepare(spec, PreparationContext(make_registry()))


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
                    {"weight": 70, "spec": {"type": "string", "values": ["STR"]}},
                    {
                        "weight": 30,
                        "spec": {
                            "type": "integer",
                            "minValue": 0,
                            "maxValue": 9,
                            "padWithZero": False,
                        },
                    },
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
    prepared = gen.prepare(
        {
            "type": "weighted",
            "choices": [
                {"weight": 0, "spec": {"type": "string", "values": ["never"]}},
                {"weight": 1, "spec": {"type": "string", "values": ["always"]}},
            ],
        },
        PreparationContext(make_registry()),
    )

    assert prepared.cum_weights == (0.0, 1.0)
    assert gen.generate(prepared, Random(0)) == "always"


def test_weighted_composite_accepts_core_qualified_child_type() -> None:
    gen = WeightedGenerator()
    prepared = gen.prepare(
        {
            "type": "weighted",
            "choices": [
                {"weight": 1, "spec": {"type": "core.string", "values": ["ok"]}},
            ],
        },
        PreparationContext(make_registry()),
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
                    {
                        "weight": 1,
                        "spec": {
                            "type": "weighted",
                            "choices": [
                                {"weight": 1, "spec": {"type": "string", "values": ["inner-a"]}},
                                {"weight": 1, "spec": {"type": "string", "values": ["inner-b"]}},
                            ],
                        },
                    },
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
    generator = WeightedGenerator()
    spec = {
        "choices": [
            {"weight": 1, "spec": {"type": "string", "values": ["x"]}},
        ],
    }
    with pytest.raises(ValueError, match="composite"):
        generator.prepare(spec)


def test_weighted_composite_rejects_unknown_nested_type() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {"weight": 1, "spec": {"type": "no_such_type"}},
                ],
            }
        },
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

    from ton import api

    config = {
        "rows": 300,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [
                    {"spec": {"type": "string", "values": ["A"]}},
                    {"spec": {"type": "string", "values": ["B"]}},
                    {"spec": {"type": "string", "values": ["C"]}},
                ],
            }
        },
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
        "types": {
            "v": {
                "type": "weighted",
                "choices": [{"weight": "abc", "spec": {"type": "string", "values": ["x"]}}],
            }
        },
    }
    with pytest.raises(TemplateError, match="numeric"):
        list(api.generate(config))


def test_weighted_composite_rejects_boolean_weight_with_path() -> None:
    gen = WeightedGenerator()
    registry = make_registry()

    with pytest.raises(ValueError, match=r"choices\[0\]\.weight"):
        gen.prepare(
            {
                "choices": [
                    {"weight": True, "spec": {"type": "string", "values": ["x"]}},
                ]
            },
            PreparationContext(registry),
        )


def test_weighted_composite_rejects_unknown_wrapper_key_with_suggestion() -> None:
    gen = WeightedGenerator()
    registry = make_registry()

    with pytest.raises(ValueError, match=r"weighted\.choices\[0\]\.weigth.*Did you mean 'weight'"):
        gen.prepare(
            {
                "choices": [
                    {"weigth": 1, "spec": {"type": "string", "values": ["x"]}},
                ]
            },
            PreparationContext(registry),
        )


def test_weighted_composite_rejects_choice_missing_spec() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [{"weight": 1, "spec": {"values": ["x"]}}],
            }
        },
    }
    with pytest.raises(TemplateError, match="type"):
        list(api.generate(config))


def test_weighted_composite_rejects_non_mapping_choice() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": ["not-an-object"],
            }
        },
    }
    with pytest.raises(TemplateError, match="weight"):
        list(api.generate(config))


def test_weighted_composite_rejects_non_mapping_child_spec() -> None:
    from ton import api
    from ton._engine import TemplateError

    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "weighted",
                "choices": [{"weight": 1, "spec": "not-an-object"}],
            }
        },
    }
    with pytest.raises(TemplateError, match="must be an object"):
        list(api.generate(config))
