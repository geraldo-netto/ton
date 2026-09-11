"""Tests that keep public documentation examples accurate."""

from __future__ import annotations

import io
import json
import re
import shlex
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from textwrap import dedent
from urllib.parse import unquote, urlsplit

import pytest

from ton import api
from ton._config import ROOT_KEYS
from ton._engine import TemplateError
from ton._registry import make_registry
from ton.cli import _build_parser

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
README = (ROOT / "README.md").read_text(encoding="utf-8")
LIBRARY = (DOCS / "library.md").read_text(encoding="utf-8")
EXTENSIONS = (DOCS / "extensions.md").read_text(encoding="utf-8")
DEVELOPMENT = (DOCS / "development.md").read_text(encoding="utf-8")
GENERATOR_INDEX = (DOCS / "generators.md").read_text(encoding="utf-8")
GENERATOR_GUIDES = tuple(sorted((DOCS / "generators").glob("*.md")))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PRE_COMMIT = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
SEQUENCE_MODULE = (ROOT / "ton" / "generators" / "sequence.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("documentation", [LIBRARY, api.__doc__], ids=["library-guide", "api"])
def test_library_streaming_example_preserves_record_boundaries(documentation) -> None:
    """Running the documented snippet must yield separable records (DOC-009).

    Counting the literal only proved the text was present; rows carry no
    terminator, so the previous snippet concatenated every record.
    """
    match = re.search(
        r"(?m)^([ \t]*)for row in api.generate\(config_dict, seed=42\):\n\1    sink.write[^\n]+",
        documentation,
    )
    assert match is not None
    snippet = dedent(match.group())

    config = {
        "rows": 3,
        "format": "$x$",
        "types": {"x": {"type": "integer", "minValue": 1, "maxValue": 9}},
    }
    sink = io.StringIO()
    exec(snippet, {"api": api, "config_dict": config, "sink": sink})

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
        assert command in DEVELOPMENT
        assert command in CI
        assert command in PRE_COMMIT
    assert "mypy ton tests" not in DEVELOPMENT


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


_TYPE_EXAMPLE = re.compile(r"```json\n(\{(?:(?!```).)*?\})\n```\n\n```\n(.*?)```", re.S)


def _documented_type_examples() -> list[tuple[str, dict, str]]:
    """Read both field specs and complete paired configs from all reference pages."""
    examples = []
    for guide in GENERATOR_GUIDES:
        for index, (spec_text, expected) in enumerate(
            _TYPE_EXAMPLE.findall(guide.read_text(encoding="utf-8"))
        ):
            spec = json.loads(spec_text)
            config = {"rows": 4, "format": "$x$", "types": {"x": spec}} if "type" in spec else spec
            examples.append((f"{guide.stem}-{index}", config, expected))
    return examples


def test_reference_documents_type_examples() -> None:
    """Guard the parser itself: a silent no-match would make the check vacuous."""
    examples = _documented_type_examples()

    assert len(examples) >= 20
    assert {"decimal", "char", "phone", "weighted", "hash"} <= {
        spec["type"] for _, config, _ in examples for spec in config["types"].values()
    }


@pytest.mark.parametrize(
    ("name", "config", "expected"),
    [
        pytest.param(*example, id=f"{index}-{example[0]}")
        for index, example in enumerate(_documented_type_examples())
    ],
)
def test_documented_type_example_output_is_reproducible(
    name: str, config: dict, expected: str
) -> None:
    """Every example must match the documented `--seed 1` command (DOC-003..005)."""
    rows = list(api.generate(config, seed=1))

    assert "".join(f"{row}\n" for row in rows) == expected


def test_documented_builtin_type_count_matches_the_catalog() -> None:
    """The stated count is derived from the catalog, not restated by hand (DOC-006)."""
    words = {21: "Twenty-one", 22: "Twenty-two", 23: "Twenty-three", 24: "Twenty-four"}
    count = len(make_registry())

    assert f"{words[count]} built-in types." in GENERATOR_INDEX


def test_documented_entry_point_table_parses_to_flat_names() -> None:
    """A namespaced entry-point key must be quoted or TOML nests it (DOC-007)."""
    block = EXTENSIONS.split("[project.entry-points.", 1)[1]
    toml_text = "[project.entry-points." + block.split("```", 1)[0]

    parsed = tomllib.loads(toml_text)["project"]["entry-points"]

    assert parsed["ton.transforms"] == {"my_ns.my_transform": "my_pkg.transforms:MyTransform"}
    assert parsed["ton.generators"] == {"my_type": "my_pkg.generators:MyGenerator"}


def test_documented_decimal_sampling_matches_the_implementation() -> None:
    """The numeric reference describes fixed-point sampling, including its rejection (DOC-002)."""
    section = (DOCS / "generators" / "numeric.md").read_text(encoding="utf-8")
    section = section.split("## `decimal`", 1)[1].split("## ", 1)[0]
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
    section = (DOCS / "generators" / "strings.md").read_text(encoding="utf-8")
    section = section.split("## `char`", 1)[1].split("## ", 1)[0]
    assert "number of draws" in section

    config = {
        "rows": 2,
        "format": "$x$",
        "types": {"x": {"type": "char", "values": ["ab"], "maxChar": 2}},
    }

    assert list(api.generate(config, seed=1, proof_mode="all")) == ["abab", "abab"]


def test_documented_generator_extension_contract() -> None:
    """DOC-036: execute the published composite against the public compiler API."""
    snippet = EXTENSIONS.split("A composite generator using the public API:", 1)[1]
    snippet = snippet.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(snippet, namespace)
    assert namespace["rows"] == ["[x]", "[x]"]


def test_documented_transform_extension_contract() -> None:
    """DOC-037: execute the documented preparation, application and proof hooks."""
    guide = EXTENSIONS
    snippet = guide.split("A transform using the public API:", 1)[1]
    snippet = snippet.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(snippet, namespace)
    assert namespace["rows"] == ["x!", "x!"]


def test_documented_mixed_default_weights() -> None:
    """DOC-043: omitted weight contributes one, not an independent 1/N probability."""
    from random import Random

    class Quantile(Random):
        def __init__(self, quantile):
            super().__init__(0)
            self.quantile = quantile

        def randrange(self, stop):
            return int(self.quantile * stop)

    guide = (DOCS / "generators" / "composites.md").read_text(encoding="utf-8")
    example = guide.split("For example, the omitted weight below is 1", 1)[1]
    field = json.loads(example.split("```json\n", 1)[1].split("```", 1)[0])
    config = {"rows": 1, "format": "$x$", "types": {"x": field}}
    results = [
        next(iter(api.Engine(config, rng=Quantile((index + 0.5) / 100)))) for index in range(100)
    ]
    assert results == ["common"] * 90 + ["rare"] * 10


def _prose(text: str) -> str:
    """Ignore fenced examples when resolving Markdown headings and links."""
    return re.sub(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$", "", text)


def _headings(path: Path) -> dict[str, str]:
    counts: Counter[str] = Counter()
    headings = {}
    for title in re.findall(r"(?m)^#{1,6} (.+)$", _prose(path.read_text(encoding="utf-8"))):
        slug = re.sub(r"[^\w\- ]", "", title).lower().replace(" ", "-")
        anchor = f"{slug}-{counts[slug]}" if counts[slug] else slug
        counts[slug] += 1
        headings[anchor] = title
    return headings


def _local_links(path: Path) -> list[tuple[Path, str]]:
    links = []
    text = _prose(path.read_text(encoding="utf-8"))
    for destination in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", text):
        parsed = urlsplit(destination)
        if not parsed.scheme and not parsed.netloc:
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            links.append((target, unquote(parsed.fragment)))
    return links


@pytest.mark.parametrize(
    "path",
    [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))],
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_documentation_local_links_and_anchors_resolve(path):
    """DOC-046: moving a page must not break examples, sources or section links."""
    for target, fragment in _local_links(path):
        assert target.is_relative_to(ROOT), (path, target)
        assert target.is_file(), (path, target)
        if fragment and target.suffix == ".md":
            assert fragment in _headings(target), (path, target, fragment)


def test_every_guide_is_reachable_from_the_project_readme():
    """DOC-046: new reference pages must be discoverable through documentation navigation."""
    guides = set(DOCS.rglob("*.md"))
    pending = [ROOT / "README.md"]
    visited = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(target for target, _ in _local_links(current) if target in guides)
    assert guides <= visited


def test_generator_index_links_every_builtin_to_its_own_reference():
    """DOC-046: the split preserves one authoritative section per registered type."""
    links = set(_local_links(DOCS / "generators.md"))
    for name in make_registry():
        sections = [
            (guide, anchor)
            for guide in GENERATOR_GUIDES
            for anchor, title in _headings(guide).items()
            if f"`{name}`" in title
        ]
        assert len(sections) == 1, (name, sections)
        assert sections[0] in links, name


def test_cli_reference_covers_every_option():
    guide = (DOCS / "cli.md").read_text(encoding="utf-8")
    table = "\n".join(line for line in guide.splitlines() if line.startswith("|"))
    documented = set(re.findall(r"(?<!\w)--?[a-z][a-z-]*", table))
    declared = {option for action in _build_parser()._actions for option in action.option_strings}
    assert declared <= documented


def test_configuration_reference_covers_root_settings():
    guide = (DOCS / "configuration.md").read_text(encoding="utf-8")
    guide = guide.split("## Root settings", 1)[1].split("\n## ", 1)[0]
    settings = set(re.findall(r"(?m)^- `([^`]+)`", guide))
    assert settings == ROOT_KEYS


def test_readme_quick_start_config_and_command_arguments():
    config = json.loads(README.split("```json\n", 1)[1].split("```", 1)[0])
    api.validate_config(config)
    assert len(list(api.generate(config, seed=1))) == config["rows"]
    commands = re.findall(r"(?m)^(?:ton |python -m ton )(.+)$", README)
    assert commands
    for command in commands:
        arguments = _build_parser().parse_args(shlex.split(command))
        assert (ROOT / arguments.config).is_file()


def test_documented_validator_extension_contract():
    snippet = EXTENSIONS.split("A validator using the public API:", 1)[1]
    snippet = snippet.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(snippet, namespace)
    assert namespace["rows"] == ["ok!", "ok!"]
    assert not namespace["HasBang"]().validate("no suffix")


def test_documented_shard_recipe_runs_in_spawned_processes(tmp_path, monkeypatch):
    """DOC-046: the relocated complete recipe must preserve row order and encoding."""
    guide = (DOCS / "concurrency.md").read_text(encoding="utf-8")
    snippet = guide.split("```python\n", 1)[1].split("```", 1)[0]
    script = tmp_path / "shards.py"
    script.write_text(snippet, encoding="utf-8")
    config = {
        "rows": 7,
        "encoding": "utf-16",
        "format": "é:$x$",
        "types": {"x": {"type": "sequence"}},
    }
    (tmp_path / "huge.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(variable, str(tmp_path))
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "combined.txt").read_text(encoding="utf-16").splitlines() == [
        f"é:{index}" for index in range(7)
    ]
    assert not list(tmp_path.glob("ton-shards-*"))
