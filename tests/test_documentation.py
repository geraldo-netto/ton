"""Tests that keep public documentation examples accurate."""

from __future__ import annotations

import io
import json
import re
import tomllib
from pathlib import Path

import pytest

from ton import api
from ton._engine import TemplateError
from ton._registry import make_registry

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PRE_COMMIT = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
SEQUENCE_MODULE = (ROOT / "ton" / "generators" / "sequence.py").read_text(encoding="utf-8")


def test_library_streaming_example_preserves_record_boundaries() -> None:
    """Running the documented snippet must yield separable records (DOC-009).

    Counting the literal only proved the text was present; rows carry no
    terminator, so the previous snippet concatenated every record.
    """
    snippet = README.split("# Streaming form for large outputs", 1)[1].split("```", 1)[0]
    assert 'sink.write(f"{row}\\n")' in snippet

    config = {
        "rows": 3,
        "format": "$x$",
        "types": {"x": {"type": "integer", "minValue": 1, "maxValue": 9}},
    }
    sink = io.StringIO()
    for row in api.generate(config, seed=42):
        sink.write(f"{row}\n")

    assert sink.getvalue().splitlines() == list(api.generate(config, seed=42))


def test_generated_rows_carry_no_line_terminator() -> None:
    """The premise of the streaming guidance: a bare write would concatenate."""
    config = {
        "rows": 3,
        "format": "$x$",
        "types": {"x": {"type": "integer", "minValue": 1, "maxValue": 9}},
    }

    rows = list(api.generate(config, seed=42))

    assert all(not row.endswith("\n") for row in rows)
    assert len("".join(rows).splitlines()) == 1


def test_documented_quality_commands_match_ci_and_pre_commit_gate() -> None:
    commands = (
        "ruff check ton tests",
        "ruff format --check ton tests",
        "mypy ton",
        "pyright ton",
    )

    for command in commands:
        assert command in README
        assert command in CI
        assert command in PRE_COMMIT
    assert "mypy ton tests" not in README


def test_sequence_worker_guidance_uses_automatic_offsets() -> None:
    assert "automatically offsets" in SEQUENCE_MODULE
    assert "worker_id * chunk_size" not in SEQUENCE_MODULE


def test_closed_review_ids_are_not_left_as_todo_annotations() -> None:
    marker = re.compile(r"\bTO" + r"DO\s+[A-Z]+-\d+\b")
    python_files = tuple((ROOT / "ton").rglob("*.py")) + tuple((ROOT / "tests").rglob("*.py"))

    stale = [
        str(path.relative_to(ROOT))
        for path in python_files
        if marker.search(path.read_text(encoding="utf-8"))
    ]

    assert stale == []


_TYPE_EXAMPLE = re.compile(r"```json\n(\{.*?\})\n```\n\n```\n(.*?)```", re.S)


def _documented_type_examples() -> list[tuple[str, dict, str]]:
    """Return every (type name, spec, expected output) example in the README."""
    examples = []
    for spec_text, expected in _TYPE_EXAMPLE.findall(README):
        try:
            spec = json.loads(spec_text)
        except json.JSONDecodeError:
            continue
        if isinstance(spec, dict) and isinstance(spec.get("type"), str):
            examples.append((spec["type"], spec, expected))
    return examples


def test_readme_documents_type_examples() -> None:
    """Guard the parser itself: a silent no-match would make the check vacuous."""
    examples = _documented_type_examples()

    assert len(examples) >= 20
    assert {"decimal", "char", "phone"} <= {name for name, _spec, _expected in examples}


@pytest.mark.parametrize(
    ("name", "spec", "expected"),
    [
        pytest.param(*example, id=f"{index}-{example[0]}")
        for index, example in enumerate(_documented_type_examples())
    ],
)
def test_documented_type_example_output_is_reproducible(
    name: str, spec: dict, expected: str
) -> None:
    """Every example must match the documented `--seed 1` command (DOC-003..005)."""
    config = {"rows": 4, "format": "$x$", "types": {"x": spec}}

    rows = list(api.generate(config, seed=1))

    assert "".join(f"{row}\n" for row in rows) == expected


def test_documented_builtin_type_count_matches_the_catalog() -> None:
    """The stated count is derived from the catalog, not restated by hand (DOC-006)."""
    words = {21: "Twenty-one", 22: "Twenty-two", 23: "Twenty-three", 24: "Twenty-four"}
    count = len(make_registry())

    assert f"{words[count]} built-in types." in README


def test_documented_entry_point_table_parses_to_flat_names() -> None:
    """A namespaced entry-point key must be quoted or TOML nests it (DOC-007)."""
    block = README.split("[project.entry-points.", 1)[1]
    toml_text = "[project.entry-points." + block.split("```", 1)[0]

    parsed = tomllib.loads(toml_text)["project"]["entry-points"]

    assert parsed["ton.transforms"] == {"my_ns.my_transform": "my_pkg.transforms:MyTransform"}
    assert parsed["ton.generators"] == {"my_type": "my_pkg.generators:MyGenerator"}


def test_documented_decimal_sampling_matches_the_implementation() -> None:
    """The README describes fixed-point sampling, including its rejection (DOC-002)."""
    section = README.split("#### `decimal`", 1)[1].split("#### ", 1)[0]
    assert "fixed-point" in section
    assert "rejected" in section

    inward = {"type": "decimal", "minValue": 0.01, "maxValue": 0.02, "decimals": 1}
    with pytest.raises(TemplateError, match="no value representable"):
        list(api.generate({"rows": 1, "format": "$x$", "types": {"x": inward}}))

    singleton = {"type": "decimal", "minValue": 0.5, "maxValue": 0.5, "decimals": 1}
    config = {"rows": 3, "format": "$x$", "types": {"x": singleton}}
    assert list(api.generate(config, seed=1, proof_mode="all")) == ["0.5"] * 3


def test_documented_char_semantics_are_draw_count_not_length() -> None:
    """maxChar counts draws from a pool that may hold multi-character entries (DOC-012)."""
    section = README.split("#### `char`", 1)[1].split("#### ", 1)[0]
    assert "number of draws" in section

    config = {
        "rows": 2,
        "format": "$x$",
        "types": {"x": {"type": "char", "values": ["ab"], "maxChar": 2}},
    }

    assert list(api.generate(config, seed=1, proof_mode="all")) == ["abab", "abab"]
