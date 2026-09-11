"""Root and nested pipelines share proof-before-validation ordering."""

import pytest

from ton import api


class RejectingSource(api.Generator):
    type_name = "reject"

    def generate(self, prepared, rng):
        return ""

    def prove(self, prepared, result):
        return api.ProofResult(False, "source rejection")


class RejectingTransform:
    type_name = "reject_transform"
    config_keys = frozenset()
    capabilities = api.TransformCapabilities()
    requires_source = True

    def nested_specs(self, spec):
        return ()

    def prepare(self, spec, context):
        return None

    def apply(self, prepared, value, rng):
        return value

    def prove(self, prepared, before, after):
        return api.TransformProof(False, "transform rejection")


def wrap(leaf, kind):
    if kind == "root":
        return leaf
    if kind == "oneOf":
        return {"type": "oneOf", "choices": [leaf]}
    if kind == "weighted":
        return {"type": "weighted", "choices": [{"spec": leaf}]}
    if kind == "sequence_of":
        return {"type": "sequence_of", "count": 1, "spec": leaf}
    return {
        "type": "string",
        "values": ["unused"],
        "transforms": [
            {"type": "distribution", "choices": [{"spec": leaf}, {"spec": leaf}]},
        ],
    }


@pytest.mark.parametrize("kind", ["root", "oneOf", "weighted", "sequence_of", "distribution"])
@pytest.mark.parametrize("failure", ["source", "transform"])
@pytest.mark.parametrize(
    "mode,rate,expected,audits",
    [
        ("all", 1, api.ProofError, 0),
        ("audit", 1, api.ValidationError, 1),
        ("sample", 1, api.ProofError, 0),
        ("sample", 2, api.ValidationError, 0),
        ("off", 1, api.ValidationError, 0),
    ],
)
def test_pipeline_proof_precedes_validation_at_every_depth(
    kind, failure, mode, rate, expected, audits
):
    """ARCH-031: nesting never suppresses a checked proof behind a validator failure."""
    snapshot = api.build_extension_catalog().snapshot()
    registry = {**snapshot.generators, "example.reject": RejectingSource()}
    transforms = {**snapshot.transforms, "example.reject": RejectingTransform()}
    leaf = (
        {"type": "example.reject"}
        if failure == "source"
        else {
            "type": "string",
            "values": [""],
            "transforms": [{"type": "example.reject"}],
        }
    )
    leaf["validators"] = ["non_empty"]
    config = {"rows": 1, "format": "$x$", "types": {"x": wrap(leaf, kind)}}
    engine = api.Engine.from_config(
        config,
        registry=registry,
        transforms=transforms,
        seed=42,
        proof_mode=mode,
        proof_sample_rate=rate,
    )
    with pytest.raises(expected):
        list(engine)
    assert len(engine.proof_failures) == audits
    if audits:
        assert failure + " rejection" in engine.proof_failures[0].reason


class RejectingPair(api.PairedGenerator):
    type_name = "reject_pair"

    def generate_pair(self, prepared, rng):
        return "id", ""

    def prove(self, prepared, result):
        return api.ProofResult(False, "paired source rejection")


@pytest.mark.parametrize(
    "mode,expected,audits",
    [
        ("all", api.ProofError, 0),
        ("audit", api.ValidationError, 1),
        ("off", api.ValidationError, 0),
    ],
)
def test_paired_pipeline_keeps_proof_before_validation(mode, expected, audits):
    """ARCH-031: cached paired values use the shared stage ordering as well."""
    engine = api.Engine.from_config(
        {
            "rows": 1,
            "format": "$x$:$x[id]$",
            "types": {
                "x": {"type": "reject_pair", "validators": ["non_empty"]},
            },
        },
        registry={"reject_pair": RejectingPair()},
        proof_mode=mode,
    )
    with pytest.raises(expected):
        list(engine)
    assert engine.proof_failure_count == audits


def test_failed_proof_discards_pending_child_validation():
    """ARCH-031: aborted rows leave no queued validators in subsequent/standalone draws."""
    from ton._validation import _pending

    snapshot = api.build_extension_catalog().snapshot()
    registry = {**snapshot.generators, "reject": RejectingSource()}
    engine = api.Engine.from_config(
        {
            "rows": 1,
            "format": "$x$",
            "types": {
                "x": wrap(
                    {"type": "reject", "validators": ["non_empty"]},
                    "oneOf",
                )
            },
        },
        registry=registry,
        proof_mode="all",
    )
    with pytest.raises(api.ProofError):
        list(engine)
    assert _pending.get() is None
    child, prepared = engine._plan.prepared["x"].source_prepared.children[0]
    with pytest.raises(api.ValidationError, match="Nested value"):
        child.generate(prepared, None)
    assert list(
        api.generate(
            {"rows": 1, "format": "ok", "types": {"x": {"type": "string", "values": ["ok"]}}},
            proof_mode="all",
        )
    ) == ["ok"]
    assert _pending.get() is None


@pytest.mark.parametrize("kind", ["root", "oneOf", "weighted", "sequence_of", "distribution"])
@pytest.mark.parametrize("mode", ["off", "all"])
def test_leaf_transform_chains_do_not_dispatch_each_stage(monkeypatch, kind, mode):
    """PERF-043: shared leaf execution avoids a cooperative request per stage."""
    from ton import _pipeline
    from ton._transforms import BaseTransform

    class Identity(BaseTransform):
        type_name = "identity"

    leaf = {"type": "string", "values": ["value"], "transforms": [{"type": "identity"}] * 4}
    engine = api.Engine.from_config(
        {"rows": 5, "format": "$x$", "types": {"x": wrap(leaf, kind)}},
        transforms={**api.build_extension_catalog().snapshot().transforms, "identity": Identity()},
        proof_mode=mode,
        seed=42,
    )
    original = _pipeline.Call
    requests = []

    def counted(target, operation, args, **kwargs):
        if operation == "apply" and target.type_name == "identity":
            requests.append(operation)
        return original(target, operation, args, **kwargs)

    monkeypatch.setattr(_pipeline, "Call", counted)
    assert list(engine) == ["value"] * 5
    assert requests == []
