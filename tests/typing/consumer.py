"""Typed third-party implementations using only the installed TON facade."""

from collections.abc import Mapping
from random import Random
from typing import Any, ClassVar

from ton import api

type Locations = tuple[tuple[tuple[str | int, ...], Mapping[str, Any]], ...]


class Source(api.Generator):
    type_name = "source"

    def generate(self, prepared: Any, rng: Random) -> str:
        return "x"

    def partition(self, spec: Mapping[str, Any], offset: int) -> api.PartitionSpec:
        return api.PartitionSpec()


class Bracket(api.CompositeGenerator):
    type_name = "bracket"

    def nested_specs(self, spec: Mapping[str, Any]) -> Locations:
        return ((("spec",), spec["spec"]),)

    def prepare(
        self, spec: Mapping[str, Any], context: api.PreparationContext | None = None
    ) -> tuple[api.Generator, Any]:
        if context is None:
            raise ValueError("requires a preparation context")
        return context.prepare_child(self.type_name, ("spec",), spec["spec"])

    def generate_steps(self, prepared: Any, rng: Random) -> api.ChildSteps:
        value = yield api.ChildCall(*prepared)
        return f"[{value}]"


class Suffix:
    type_name: ClassVar[str] = "suffix"
    config_keys: ClassVar[frozenset[str] | None] = frozenset()
    capabilities: ClassVar[api.TransformCapabilities] = api.TransformCapabilities()
    requires_source: ClassVar[bool] = True

    def nested_specs(self, spec: Mapping[str, Any]) -> Locations:
        return ()

    def prepare(self, spec: Mapping[str, Any], context: Any) -> None:
        return None

    def apply(self, prepared: Any, value: api.TransformResult, rng: Random) -> api.TransformResult:
        return api.TransformResult(value.value + "!")

    def prove(
        self, prepared: Any, before: api.TransformResult, after: api.TransformResult
    ) -> api.TransformProof:
        return api.TransformProof(after.value == before.value + "!")


class HasValue:
    type_name = "has_value"

    def validate(self, value: str) -> bool:
        return bool(value)


source: api.Generator = Source()
partitioner: api.Partitionable = Source()
transform: api.Transform = Suffix()
validator: api.Validator = HasValue()
config: dict[str, Any] = {
    "rows": 1,
    "format": "$x$",
    "types": {
        "x": {
            "type": "bracket",
            "spec": {"type": "source"},
            "transforms": [{"type": "suffix"}],
            "validators": ["has_value"],
        },
    },
}
options = api.EngineOptions(
    seed=7,
    registry={"source": source, "bracket": Bracket()},
    transforms={"suffix": transform},
    validators={"has_value": validator},
    proof_mode="all",
)
assert list(api.Engine.from_options(config, options)) == ["[x]!"]
worker = api.fork_engine(config, parent_seed=7, worker_id=0, workers=1, options=options)
assert list(worker) == ["[x]!"]
