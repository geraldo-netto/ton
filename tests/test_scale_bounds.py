"""Tests for operator-controlled generator scale."""

from __future__ import annotations

import base64
import json
import os
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from random import Random

import pytest

from ton import api
from ton._engine import Engine, TemplateError
from ton._scalars import int_to_str, str_to_int
from ton._specsnapshot import snapshot_spec
from ton.generators import Generator
from ton.generators.bytes import BytesGenerator
from ton.generators.char import CharGenerator
from ton.generators.regex import RegexGenerator
from ton.generators.sequence import SequenceGenerator
from ton.generators.text import TextGenerator


def test_char_honors_large_operator_requested_length() -> None:
    spec = {"values": ["A"], "maxChar": 100_001}
    prepared = CharGenerator().prepare(spec)
    assert CharGenerator().generate(prepared, Random(0)) == "A" * 100_001


def test_bytes_honors_large_operator_requested_length() -> None:
    generator = BytesGenerator()
    prepared = generator.prepare({"length": 1_000_001, "encoding": "base64"})

    assert len(base64.b64decode(generator.generate(prepared, Random(0)))) == 1_000_001


def test_text_honors_large_operator_requested_count() -> None:
    generator = TextGenerator()
    prepared = generator.prepare({"unit": "words", "count": 10_001})

    assert len(generator.generate(prepared, Random(0)).split()) == 10_001


def test_sequence_honors_large_operator_requested_padding() -> None:
    generator = SequenceGenerator()
    prepared = generator.prepare({"start": 1, "padWidth": 100_001})

    assert generator.generate(prepared, Random(0)) == "0" * 100_000 + "1"


def test_regex_honors_large_literal_repeat() -> None:
    generator = RegexGenerator()
    prepared = generator.prepare({"pattern": "a{10001}"})

    assert generator.generate(prepared, Random(0)) == "a" * 10_001


def test_regex_accepts_unbounded_quantifiers_at_any_lo() -> None:
    RegexGenerator().prepare({"pattern": "a+"})
    RegexGenerator().prepare({"pattern": "a*"})


def test_regex_prepares_nested_repeats_without_eager_expansion() -> None:
    assert RegexGenerator().prepare({"pattern": "(?:a{5000}){5000}"}) is not None


def test_regex_accepts_pattern_within_total_expansion() -> None:
    prepared = RegexGenerator().prepare({"pattern": "a{10000}"})
    assert prepared is not None


def test_row_width_counts_literals_and_all_placeholders() -> None:
    config = {
        "rows": 1,
        "maxRowWidth": 5,
        "format": "x$a$$b$",
        "types": {
            "a": {"type": "string", "values": ["aa"]},
            "b": {"type": "string", "values": ["bb"]},
        },
    }
    assert list(Engine(config)) == ["xaabb"]
    config["maxRowWidth"] = 4
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(Engine(config))


def test_row_width_is_unbounded_when_limit_is_omitted() -> None:
    wide = "x" * 2_000_001
    config = {"rows": 1, "format": wide, "types": {"v": {"type": "string", "values": [""]}}}

    assert list(Engine(config)) == [wide]


def test_row_width_guards_composite_and_unknown_width_values() -> None:
    composite = {
        "rows": 1,
        "maxRowWidth": 3,
        "format": "$v$",
        "types": {"v": {"type": "oneOf", "choices": [{"type": "string", "values": ["wide"]}]}},
    }
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(Engine(composite))

    class UnknownWidth(Generator):
        type_name = "unknown"

        def generate(self, prepared, rng) -> str:
            return "wide"

    unknown = {"rows": 1, "maxRowWidth": 3, "format": "$v$", "types": {"v": {"type": "unknown"}}}
    engine = Engine(unknown, registry={"unknown": UnknownWidth()})
    with pytest.raises(TemplateError, match="maxRowWidth"):
        list(engine)


BIG = 10**4300


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("transform", [False, True])
@pytest.mark.parametrize(
    "weights,draws",
    [
        (("1e-400", "1e-400"), [(0, "v1"), (1, "v2")]),
        (("1e400", "1e400"), [(0, "v1"), (1, "v2")]),
        (("1e-400", "1e400"), [(0, "v1"), (1, "v2"), (10**800, "v2")]),
    ],
)
def test_exact_weight_thresholds_preserve_all_positive_choices(
    as_json, transform, weights, draws, tmp_path
) -> None:
    """SCALE-016: exact integer draws preserve tiny, huge and zero-weight intervals."""

    class Draw(Random):
        def __init__(self, value):
            super().__init__(0)
            self.value = value

        def randrange(self, stop):
            assert 0 <= self.value < stop
            return self.value

    weights = ("0", *weights, "0")
    distribution = {
        "type": "weighted",
        "choices": [
            {"weight": Decimal(weight), "spec": {"type": "string", "values": [f"v{index}"]}}
            for index, weight in enumerate(weights)
        ],
    }
    field = distribution
    if transform:
        distribution["type"] = "distribution"
        field = {"type": "string", "values": ["unused"], "transforms": [distribution]}
    config = {"rows": 1, "format": "$x$", "types": {"x": field}}
    if as_json:
        payload = json.dumps(config, default=str)
        for weight in weights:
            payload = payload.replace(json.dumps(weight), weight)
        path = tmp_path / "weights.json"
        path.write_text(payload)
        config = api.load_config(path)
    for draw, expected in draws:
        assert list(api.Engine(config, rng=Draw(draw), proof_mode="all")) == [expected]


@pytest.mark.parametrize("sign", ["", "+", "-"])
@pytest.mark.parametrize("kind", ["integer", "sequence"])
def test_arbitrary_size_integer_text_settings(sign, kind) -> None:
    """SCALE-015: valid integer text has no process conversion-limit ceiling."""
    before = sys.get_int_max_str_digits()
    value = sign + "1" + "0" * 4999
    options = {"minValue": value, "maxValue": value} if kind == "integer" else {"start": value}
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": kind, **options}}}
    assert list(api.generate(config, proof_mode="all")) == [value.removeprefix("+")]
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize("value", ["1" * 5000 + ".0", "1" * 5000 + "x", "1__0"])
def test_arbitrary_size_integer_text_rejects_malformed_input(value) -> None:
    """SCALE-015: the unlimited parser retains strict integer syntax."""
    with pytest.raises(ValueError, match="must be an integer"):
        SequenceGenerator().prepare({"start": value})


@pytest.mark.parametrize("value", [Fraction(3, 2), Fraction(-3, 2)])
@pytest.mark.parametrize("kind", ["integer", "text", "sequence"])
def test_fractional_integer_settings_are_rejected(value, kind) -> None:
    """REL-049: integer settings must not truncate rational inputs."""
    from ton.concurrency import fork_engine

    options = {
        "integer": {"minValue": value, "maxValue": value},
        "text": {"unit": "words", "count": value},
        "sequence": {"start": value, "step": value},
    }
    config = {"rows": 1, "format": "$x$", "types": {"x": {"type": kind, **options[kind]}}}
    with pytest.raises(ValueError, match="must be an integer"):
        list(api.generate(config, proof_mode="all"))
    with pytest.raises(ValueError, match="must be an integer"):
        fork_engine(config, parent_seed=0, worker_id=1, workers=2)


@pytest.mark.parametrize("kind", ["integer", "text", "sequence"])
def test_integral_rational_settings_preserve_exact_values(kind) -> None:
    """REL-049: integral rational bounds, counts and worker starts remain valid."""
    from ton.concurrency import fork_engine

    value = Fraction(6, 2)
    options = {
        "integer": {"minValue": value, "maxValue": value},
        "text": {"unit": "words", "count": value},
        "sequence": {"start": value, "step": value},
    }
    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": kind, **options[kind]}}}
    rows = list(
        fork_engine(config, parent_seed=0, worker_id=1, workers=2, rows=1, proof_mode="all")
    )
    if kind == "text":
        assert len(rows[0].split()) == 3
    else:
        assert rows == (["6"] if kind == "sequence" else ["3"])


def test_decimal_generation_ignores_default_exponent_ceiling() -> None:
    """SCALE-014: a finite million-digit exponent remains generatable and provable."""
    bound = Decimal("1e1000000")
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "decimal", "minValue": bound, "maxValue": bound, "decimals": 0}},
    }
    assert list(api.generate(config, proof_mode="all")) == ["1" + "0" * 1_000_000]


@pytest.mark.parametrize(
    "bounds, expected",
    [
        (("-1.29", "-1.21"), "-1.2"),
        (("1.21", "1.29"), "1.3"),
        (("1e-1000", "0.1"), "0.1"),
        (("-0.1", "-1e-1000"), "-0.1"),
    ],
)
def test_decimal_scaling_is_exact_under_restrictive_context(bounds, expected) -> None:
    """SCALE-014: rounding is sign-correct and independent of caller Decimal settings."""
    from ton.generators.decimal import DecimalGenerator

    generator = DecimalGenerator()
    # Use a nonempty rounded range with exactly one representable step.
    lo, hi = bounds
    if expected == "-1.2":
        hi = "-1.2"
    elif expected == "1.3":
        hi = "1.3"
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 2, 2, -2
        prepared = generator.prepare({"minValue": lo, "maxValue": hi, "decimals": 1})
        assert generator.generate(prepared, Random(0)) == expected


@pytest.mark.parametrize("suffix", ["", ",", "," + "1" + "0" * 4300])
def test_regex_prepares_arbitrary_size_repeat_counts(suffix: str) -> None:
    """SCALE-010: preparing a zero-row job must not expand or cap repeats."""
    before = sys.get_int_max_str_digits()
    count = "1" + "0" * 4300
    pattern = "a{" + count + suffix + "}"
    config = {"rows": 0, "format": "$x$", "types": {"x": {"type": "regex", "pattern": pattern}}}
    assert list(api.generate(config)) == []
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("padding", [False, True])
def test_decimal_accepts_arbitrary_integer_bounds(sign: int, padding: bool) -> None:
    """SCALE-009: exact integer bounds must never pass through limited str(int)."""
    before = sys.get_int_max_str_digits()
    bound = sign * BIG
    spec = {
        "type": "decimal",
        "minValue": bound,
        "maxValue": bound,
        "decimals": 2,
        "padWithZero": padding,
    }
    config = {"rows": 0, "format": "$x$", "types": {"x": spec}}
    assert list(api.generate(config)) == []
    config["rows"] = 2
    expected = ("-" if sign < 0 else "") + "1" + "0" * 4300 + ".00"
    assert list(api.generate(config, proof_mode="all")) == [expected] * 2
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("rows", [0, 2])
def test_large_padded_integer_bounds(sign: int, rows: int) -> None:
    """SCALE-005: padding must use arbitrary-size conversion during preparation."""
    before = sys.get_int_max_str_digits()
    bound = sign * BIG
    config = {
        "rows": rows,
        "format": "$x$",
        "types": {
            "x": {"type": "integer", "minValue": bound, "maxValue": bound, "padWithZero": True}
        },
    }
    expected = ("-" if sign < 0 else "") + "1" + "0" * 4300
    assert list(api.generate(config, proof_mode="all")) == [expected] * rows
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize(
    ("label", "spec"),
    [
        ("integer", {"type": "integer", "minValue": BIG, "maxValue": BIG}),
        ("sequence", {"type": "sequence", "start": BIG}),
        ("decimal", {"type": "decimal", "minValue": 0, "maxValue": 1, "decimals": 4301}),
    ],
)
def test_numeric_rendering_has_no_digit_ceiling(label: str, spec: dict) -> None:
    """CPython's 4,300-digit int->str limit is not TON's ceiling (SCALE-005)."""
    config = {"rows": 1, "format": "$x$", "types": {"x": spec}}

    rows = list(api.generate(config, seed=1, proof_mode="all"))

    assert len(rows[0].lstrip("-")) > 4300
    if label != "decimal":
        assert rows[0] == "1" + "0" * 4300


def test_oversized_rendering_does_not_change_the_process_limit() -> None:
    """The fix must not reach for a process-global setting (SCALE-005)."""
    before = sys.get_int_max_str_digits()
    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "integer", "minValue": BIG, "maxValue": BIG}},
    }

    list(api.generate(config, seed=1))

    assert sys.get_int_max_str_digits() == before


def test_int_conversion_helpers_stay_as_strict_as_int() -> None:
    """The arbitrary-size fallback must not widen what counts as an integer."""
    assert str_to_int(int_to_str(BIG)) == BIG
    assert str_to_int(int_to_str(-BIG)) == -BIG
    for text in ("abc", "1.5", "", "1e5"):
        with pytest.raises(ValueError):
            str_to_int(text)


def _nested_one_of(levels: int) -> dict:
    spec: dict = {"type": "string", "values": ["x"]}
    for _ in range(levels):
        spec = {"type": "oneOf", "choices": [spec]}
    return {"rows": 1, "format": "$x$", "types": {"x": spec}}


def test_deeply_nested_composites_prepare_and_generate() -> None:
    """A chain far past the default recursion limit must produce its row (SCALE-007)."""
    assert list(api.generate(_nested_one_of(600), seed=1, proof_mode="all")) == ["x"]


def test_nesting_has_no_estimated_process_stack_ceiling() -> None:
    """SCALE-007: valid specs exceed the removed 1,024-level estimate."""
    before = sys.getrecursionlimit()
    assert list(api.generate(_nested_one_of(1500), seed=1, proof_mode="all")) == ["x"]
    assert sys.getrecursionlimit() == before


def test_nested_generation_preserves_a_callers_larger_recursion_limit() -> None:
    """A caller that already raised the limit keeps its own setting."""
    original = sys.getrecursionlimit()
    sys.setrecursionlimit(original + 50_000)
    try:
        assert list(api.generate(_nested_one_of(600))) == ["x"]
        assert sys.getrecursionlimit() == original + 50_000
    finally:
        sys.setrecursionlimit(original)


def test_spec_snapshot_is_stack_safe_independently_of_the_limit() -> None:
    """SCALE-007: snapshotting must be stack-safe independently of preparation."""
    spec: dict = {"type": "string", "values": ["x"]}
    for _ in range(5_000):
        spec = {"type": "oneOf", "choices": [spec]}

    copied = snapshot_spec(spec)

    # Walk both iteratively: a deep == would recurse in the assertion itself.
    depth, original, clone = 0, spec, copied
    while clone["type"] == "oneOf":
        assert clone is not original
        original, clone = original["choices"][0], clone["choices"][0]
        depth += 1

    assert depth == 5_000
    assert clone == {"type": "string", "values": ["x"]}
    assert clone is not original


def test_snapshot_preserves_shared_subgraphs_with_linear_copy_work() -> None:
    """SCALE-012: copy each distinct container once and isolate caller mutations."""
    visits = []

    class CountedDict(dict):
        def items(self):
            visits.append(id(self))
            return super().items()

    node = CountedDict(values=["original"])
    leaf = node
    for _ in range(14):
        node = CountedDict(left=node, right=node)
    clone = snapshot_spec(node)
    assert len(visits) == len(set(visits)) == 15
    for _ in range(14):
        assert clone["left"] is clone["right"]
        clone = clone["left"]
    leaf["values"].append("mutated")
    assert clone["values"] == ["original"]


def test_snapshot_preserves_cyclic_metadata_without_recursion() -> None:
    """SCALE-012: cycles refer to the isolated copy, never the caller's graph."""
    original = {"children": []}
    original["children"].append(original)
    clone = snapshot_spec(original)
    assert clone is not original
    assert clone["children"] is not original["children"]
    assert clone["children"][0] is clone


@pytest.mark.parametrize("immutable", [False, True])
def test_snapshot_preserves_mapping_order_and_aliases(immutable) -> None:
    """ARCH-022: a snapshot preserves ordered plugin metadata and graph identity."""
    shared = {"first": 1, "second": 2}
    original = {"left": shared, "right": shared}
    copied = snapshot_spec(original, immutable=immutable)
    assert list(copied) == ["left", "right"]
    assert list(copied["left"]) == ["first", "second"]
    assert copied["left"] is copied["right"]
    shared["third"] = 3
    assert list(copied["left"]) == ["first", "second"]


def test_engine_preserves_order_sensitive_plugin_metadata() -> None:
    """ARCH-022: snapshot normalization cannot reverse a plugin's output."""

    class Ordered(Generator):
        def generate(self, prepared, rng):
            return ":".join(prepared["metadata"])

    config = {
        "rows": 1,
        "format": "$x$",
        "types": {"x": {"type": "ordered", "metadata": {"first": 1, "second": 2}}},
    }
    assert list(api.generate(config, registry={"ordered": Ordered()})) == ["first:second"]


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX resource module (PLAT-015)")
def test_nested_generation_needs_no_finite_stack_report(monkeypatch) -> None:
    """SCALE-007: an unlimited POSIX stack needs no estimate to generate nested values."""
    import resource

    monkeypatch.setattr(
        resource, "getrlimit", lambda _which: (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    )

    before = sys.getrecursionlimit()
    assert list(api.generate(_nested_one_of(600), proof_mode="all")) == ["x"]
    assert sys.getrecursionlimit() == before


def test_nested_generation_works_without_resource_module(monkeypatch) -> None:
    """PLAT-016: nested generation works without importing POSIX modules."""
    monkeypatch.setitem(sys.modules, "resource", None)
    before = sys.getrecursionlimit()
    assert list(api.generate(_nested_one_of(600), proof_mode="all")) == ["x"]
    assert sys.getrecursionlimit() == before


@pytest.mark.parametrize("catalog", [False, True])
@pytest.mark.parametrize("rows", [0, 1])
def test_deep_composites_are_stack_safe_without_global_mutation(catalog, rows) -> None:
    """SCALE-007: arbitrary nesting works with both catalogs without changing process limits."""
    import subprocess

    program = f"""
import sys
from ton import api
before = sys.getrecursionlimit()
leaf = {{"type": "string", "values": ["x"]}}
spec = leaf
for index in range(1500):
    if index % 4 == 0:
        spec = {{"type": "oneOf", "choices": [spec]}}
    elif index % 4 == 1:
        spec = {{"type": "weighted", "choices": [{{"spec": spec}}]}}
    elif index % 4 == 2:
        spec = {{"type": "sequence_of", "count": 1, "spec": spec}}
    else:
        spec = {{**leaf, "transforms": [{{"type": "distribution", "choices": [
            {{"weight": 1, "spec": spec}}, {{"weight": 0, "spec": leaf}}]}}]}}
config = {{"rows": {rows}, "format": "$x$", "types": {{"x": spec}}}}
registry = api.build_extension_catalog().generators() if {catalog!r} else None
assert list(api.generate(config, registry=registry, proof_mode="all")) == ["x"] * {rows}
assert sys.getrecursionlimit() == before
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("catalog", [False, True])
def test_cyclic_generator_specs_report_the_owning_path(catalog) -> None:
    """SCALE-007: a cyclic ownership graph cannot be prepared as a finite spec tree."""
    spec = {"type": "oneOf", "choices": []}
    spec["choices"].append(spec)
    config = {"rows": 0, "format": "$x$", "types": {"x": spec}}
    registry = api.build_extension_catalog().generators() if catalog else None
    with pytest.raises(
        api.TemplateError, match=r"Cyclic generator specification at types.x.choices\[0\]"
    ):
        list(api.generate(config, registry=registry))


def test_deep_composite_failure_can_be_audited() -> None:
    """SCALE-007: rejection and audit serialization remain stack-safe at depth."""
    import io

    from ton._proofaudit import ProofAuditWriter

    class Reject(Generator):
        def generate(self, prepared, rng):
            return "x"

        def prove(self, prepared, result):
            return api.ProofResult(False, "deep rejection")

    config = _nested_one_of(1200)
    leaf = config["types"]["x"]
    while leaf["type"] == "oneOf":
        leaf = leaf["choices"][0]
    leaf["type"] = "reject"
    registry = api.build_extension_catalog().generators()
    registry["reject"] = Reject()
    stream = io.StringIO()
    engine = api.Engine(
        config, registry=registry, proof_mode="audit", proof_failure_sink=ProofAuditWriter(stream)
    )
    assert list(engine) == ["x"]
    assert engine.proof_failure_count == 1
    assert engine.proof_failures[0].reason.endswith("deep rejection")
    assert stream.getvalue().endswith("}\n")
    assert '"schema":"ton.proof-audit/v2"' in stream.getvalue()
