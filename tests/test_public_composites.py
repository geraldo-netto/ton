"""ARCH-032: third-party composites need only the supported public API."""

import subprocess
import sys
from random import Random

import pytest

from ton import api


class Bracket(api.CompositeGenerator):
    type_name = "bracket"
    config_keys = frozenset({"spec"})

    def nested_specs(self, spec):
        return ((("spec",), spec["spec"]),)

    def prepare(self, spec, context=None):
        return context.prepare_child(self.type_name, ("spec",), spec["spec"])

    def generate_steps(self, prepared, rng):
        value = yield api.ChildCall(*prepared)
        return f"[{value}]"


class Leaf(api.Generator):
    type_name = "leaf"

    def generate(self, prepared, rng):
        if prepared.get("crash") == "generate":
            raise LookupError("leaf generation")
        if prepared.get("crash") == "interrupt":
            raise KeyboardInterrupt
        return prepared.get("value", "x")

    def prove(self, prepared, result):
        if prepared.get("crash") == "prove":
            raise LookupError("leaf proof")
        return api.ProofResult(prepared.get("valid", True), "leaf rejection")


class LeafTransform:
    type_name = "leaf_transform"
    config_keys = frozenset({"crash"})
    capabilities = api.TransformCapabilities()
    requires_source = True

    def nested_specs(self, spec):
        return ()

    def prepare(self, spec, context):
        return spec

    def apply(self, prepared, value, rng):
        if prepared.get("crash") == "apply":
            raise LookupError("leaf transform")
        return api.TransformResult(value.value.upper())

    def prove(self, prepared, before, after):
        if prepared.get("crash") == "prove":
            raise LookupError("leaf transform proof")
        return api.TransformProof(after.value == before.value.upper())


def nested(spec, depth):
    for _ in range(depth):
        spec = {"type": "bracket", "spec": spec}
    return spec


def engine(spec, mode="all", registry=None, rows=1):
    snapshot = api.build_extension_catalog().snapshot()
    return api.Engine.from_config(
        {"rows": rows, "format": "$x$", "types": {"x": spec}},
        seed=7,
        proof_mode=mode,
        registry={**snapshot.generators, "bracket": Bracket(), "leaf": Leaf(), **(registry or {})},
        transforms={**snapshot.transforms, "leaf_transform": LeafTransform()},
    )


def test_public_composite_generation_and_proof_beyond_recursion_limit():
    """ARCH-032: ordinary public plugin hooks compile, generate and prove without recursion."""
    script = """
import sys
from tests.test_public_composites import engine, nested
limit = sys.getrecursionlimit()
depth = limit + 50
spec = nested({"type": "leaf", "transforms": [{"type": "leaf_transform"}]}, depth)
for mode in ("all", "off"):
    assert list(engine(spec, mode)) == ["[" * depth + "X" + "]" * depth]
assert sys.getrecursionlimit() == limit
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "crash,stage,reference,error",
    [
        ("generate", "Generator", "Leaf", api.GeneratorExecutionError),
        ("prove", "Source proof", "leaf", api.ProofEvaluationError),
        ("transform", "Transform", "leaf_transform", api.TransformExecutionError),
        ("transform_prove", "Transform proof", "leaf_transform", api.ProofEvaluationError),
    ],
)
def test_public_composite_retains_originating_hook(crash, stage, reference, error):
    leaf = {"type": "leaf", "crash": crash}
    if crash.startswith("transform"):
        leaf["transforms"] = [
            {"type": "leaf_transform", "crash": "prove" if crash.endswith("prove") else "apply"}
        ]
    with pytest.raises(error) as caught:
        list(engine(nested(leaf, 4)))
    assert caught.value.stage == stage
    assert caught.value.reference == reference
    assert caught.value.cause_type == "LookupError"
    assert isinstance(caught.value.__cause__, LookupError)


class First(api.CompositeGenerator):
    type_name = "first"

    def nested_specs(self, spec):
        return tuple((("choices", i), child) for i, child in enumerate(spec["choices"]))

    def prepare(self, spec, context=None):
        return tuple(
            context.prepare_child(self.type_name, location, child)
            for location, child in self.nested_specs(spec)
        )

    def generate_steps(self, prepared, rng):
        return (yield api.ChildCall(*prepared[0]))


@pytest.mark.parametrize("valid", [False, True])
def test_public_composite_proves_only_actual_draws_after_formatting(valid):
    spec = nested(
        {
            "type": "first",
            "choices": [
                {"type": "leaf", "valid": valid},
                {"type": "leaf", "valid": not valid},
            ],
        },
        3,
    )
    run = engine(spec, "audit", {"first": First()})
    assert list(run) == ["[[[x]]]"]
    assert run.proof_failure_count == (0 if valid else 1)
    if not valid:
        assert "leaf rejection" in run.proof_failures[0].reason


class ClosingBracket(Bracket):
    closed = 0

    def generate_steps(self, prepared, rng):
        try:
            return (yield api.ChildCall(*prepared))
        finally:
            type(self).closed += 1


@pytest.mark.parametrize(
    "crash,error",
    [
        ("generate", api.GeneratorExecutionError),
        ("interrupt", KeyboardInterrupt),
    ],
)
def test_public_composite_closes_user_steps_on_failure(crash, error):
    ClosingBracket.closed = 0
    run = engine(
        nested({"type": "leaf", "crash": crash}, 4), registry={"bracket": ClosingBracket()}
    )
    with pytest.raises(error):
        list(run)
    assert ClosingBracket.closed == 4
    assert list(engine({"type": "leaf"})) == ["x"]


def test_standalone_composite_proof_requires_its_own_draw_trace():
    child = Leaf()
    composite = Bracket()
    prepared = (child, {"type": "leaf"})
    text = composite.generate(prepared, Random(7))
    assert text == "[x]"
    assert composite.prove(prepared, api.TransformResult(text)).ok
    assert not composite.prove(prepared, api.TransformResult(str(text))).ok
    assert not composite.prove((child, {}), api.TransformResult(text)).ok


class RejectingBracket(Bracket):
    def prove_output(self, prepared, result):
        return api.ProofResult(False, "bracket format rejection")


def test_public_composite_can_prove_its_own_output():
    with pytest.raises(api.ProofError, match="bracket format rejection"):
        list(engine(nested({"type": "leaf"}, 1), registry={"bracket": RejectingBracket()}))


class Join(First):
    def generate_steps(self, prepared, rng):
        values = []
        for child in prepared:
            values.append((yield api.ChildCall(*child)))
        return ":".join(values)


class RecoverFirst(First):
    def generate_steps(self, prepared, rng):
        try:
            return (yield api.ChildCall(*prepared[0]))
        except (api.ChildExecutionError, api.ValidationError):
            return (yield api.ChildCall(*prepared[1]))


@pytest.mark.parametrize("mode", ["all", "audit", "off"])
def test_public_composite_recovery_discards_abandoned_validation_and_draws(mode):
    """ARCH-032: failed child subtrees cannot invalidate a successfully recovered result."""
    spec = {
        "type": "recover",
        "choices": [
            {
                "type": "join",
                "choices": [
                    {"type": "leaf", "value": "", "validators": ["non_empty"]},
                    {"type": "leaf", "crash": "generate"},
                ],
            },
            {"type": "leaf", "value": "fallback", "validators": ["non_empty"]},
        ],
    }
    run = engine(spec, mode, {"recover": RecoverFirst(), "join": Join()})
    assert list(run) == ["fallback"]
    assert run.proof_failure_count == 0


@pytest.mark.parametrize("mode", ["all", "off"])
def test_public_composite_zero_and_multiple_draws(mode):
    registry = {"join": Join()}
    assert list(engine({"type": "join", "choices": []}, mode, registry)) == [""]
    assert list(
        engine(
            {
                "type": "join",
                "choices": [
                    {"type": "leaf", "value": "a"},
                    {"type": "leaf", "value": "b"},
                ],
            },
            mode,
            registry,
        )
    ) == ["a:b"]


class BadReturn(Bracket):
    def generate_steps(self, prepared, rng):
        yield api.ChildCall(*prepared)
        return 42


def test_public_composite_rejects_non_string_return():
    with pytest.raises(api.GeneratorExecutionError, match="must return a string"):
        list(engine(nested({"type": "leaf"}, 1), registry={"bracket": BadReturn()}))


def test_standalone_composite_child_failure_closes_iterator():
    ClosingBracket.closed = 0
    with pytest.raises(api.ChildExecutionError) as caught:
        ClosingBracket().generate((Leaf(), {"crash": "generate"}), Random(0))
    assert caught.value.reference == "Leaf"
    assert isinstance(caught.value.cause, LookupError)
    assert ClosingBracket.closed == 1
