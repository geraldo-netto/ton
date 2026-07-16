"""Tests for the composite generators added in PAT-011 (oneOf, sequence_of).

Also covers the shared :func:`ton.generators.base.prepare_child_spec`
helper, REL-019's paired-nested guard, and the LogEvent enum surface.
"""

from __future__ import annotations

from collections import Counter
from random import Random
from typing import Any

import pytest

from ton import api
from ton._engine import Engine, TemplateError
from ton._logging import LogEvent
from ton.generators.base import Generator, prepare_child_spec
from ton.generators.one_of import OneOfGenerator
from ton.generators.sequence_of import (
    MAX_SEQUENCE_OF_COUNT,
    SequenceOfGenerator,
)

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
    assert list(api.generate(config, seed=7)) == list(api.generate(config, seed=7))


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
                "choices": [{"type": "lmhash", "values": ["a"]}],
            }
        },
    }
    with pytest.raises(TemplateError, match="paired"):
        list(api.generate(config))


def test_one_of_direct_prepare_rejected() -> None:
    with pytest.raises(ValueError, match="composite"):
        OneOfGenerator().prepare({"choices": [_string_spec("x")]})


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
            assert p.isdigit() and 0 <= int(p) <= 9


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


def test_sequence_of_rejects_count_above_cap() -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "sequence_of",
                "count": MAX_SEQUENCE_OF_COUNT + 1,
                "spec": _string_spec("X"),
            }
        },
    }
    with pytest.raises(TemplateError, match="MAX_SEQUENCE_OF_COUNT"):
        list(api.generate(config))


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
                "spec": {"type": "lmhash", "values": ["a"]},
            }
        },
    }
    with pytest.raises(TemplateError, match="paired"):
        list(api.generate(config))


def test_sequence_of_direct_prepare_rejected() -> None:
    with pytest.raises(ValueError, match="composite"):
        SequenceOfGenerator().prepare(
            {
                "count": 1,
                "spec": _string_spec("x"),
            }
        )


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
        prepare_child_spec("custom", "'spec'", "not-a-mapping", {})


def test_prepare_child_spec_rejects_missing_type_field() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        prepare_child_spec("custom", "'spec'", {"values": ["x"]}, {})


def test_prepare_child_spec_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        prepare_child_spec("custom", "'spec'", {"type": "nope"}, {})


def test_generator_nested_type_hook_defaults_empty_and_is_extensible() -> None:
    class Composite(Generator):
        type_name = "composite"

        def nested_types(self, spec):
            return tuple(spec["children"])

        def generate(self, prepared, rng):
            return ""

    assert Generator.nested_types(Composite(), {}) == ()
    assert Composite().nested_types({"children": ["string", "integer"]}) == (
        "string",
        "integer",
    )


@pytest.mark.parametrize(
    ("generator", "spec", "expected"),
    [
        (
            OneOfGenerator(),
            {"choices": [{"type": "string"}, {"type": "sequence_of", "spec": {"type": "char"}}]},
            ("string", "sequence_of", "char"),
        ),
        (
            SequenceOfGenerator(),
            {"spec": {"type": "oneOf", "choices": [{"type": "integer"}]}},
            ("oneOf", "integer"),
        ),
    ],
)
def test_builtin_composites_declare_transitive_nested_types(generator, spec, expected) -> None:
    assert generator.nested_types(spec) == expected


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
                    {"weight": 1, "spec": {"type": "lmhash", "values": ["a"]}},
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
