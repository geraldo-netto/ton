# Writing and loading extensions

[Documentation](README.md) · [Project overview](../README.md)

Custom plugins register via three entry-point groups in any installed package: `ton.generators` (data types), `ton.transforms`, and `ton.validators`:

## Generators and composites

Generator extensions implement `prepare(spec, context)` and `generate(prepared, rng)`.
Preparation runs once per engine. Composite generators resolve children with
`context.prepare_child(parent_type, location, child_spec)` and declare their owned
child locations with `nested_specs(spec)`. Discovery reads only these declarations;
ordinary plugin metadata remains opaque. Each location is a tuple of literal mapping keys
and list indices, for example
`("choices", 0, "spec")` or `("dotted.key",)`. Pass the same tuple to `prepare_child`.

A composite generator using the public API:

```python
from ton import api

class BracketGenerator(api.CompositeGenerator):
    type_name = "bracket"
    config_keys = frozenset({"spec"})

    def nested_specs(self, spec):
        return ((("spec",), spec["spec"]),)

    def prepare(self, spec, context=None):
        return context.prepare_child(self.type_name, ("spec",), spec["spec"])

    def generate_steps(self, prepared, rng):
        value = yield api.ChildCall(*prepared)
        return f"[{value}]"

registry = api.build_extension_catalog().generators()
registry["example.bracket"] = BracketGenerator()
config = {"rows": 2, "format": "$x$", "types": {
    "x": {"type": "example.bracket", "spec": {"type": "string", "values": ["x"]}}
}}
rows = list(api.generate(config, registry=registry, seed=1))
assert rows == ["[x]", "[x]"]
```

`CompositeGenerator.generate_steps` returns an `api.ChildSteps` iterator: yield
`api.ChildCall(generator, prepared)` for each child draw, receive its string,
and return the formatted result. Execution and proof use an explicit stack,
including children with transforms or validators. Proofs check only the children
actually drawn, using their original values even when the composite reformats them.
Override `prove_output(prepared, result)` for an additional formatting proof.
A standalone proof requires the traced value returned by `generate`.

Unexpected child generator and transform exceptions reach the yield as `api.ChildExecutionError`, with `stage`,
`reference`, and `cause` identifying the originating hook. Plugins can catch it
and yield a fallback; abandoned child validators and traces are discarded.
Validation rejections remain `api.ValidationError`. Iterators are closed on failure
and interruption, so plugin `finally` cleanup runs. Proof checks precede validators
for root and nested pipelines; unchecked rows validate immediately.

## Namespaced registrations

Built-in types and transforms live in `core`. Bare names such as `integer`
resolve to `core.integer`. Built-ins cannot be removed or replaced through
`ExtensionCatalog`; registering `plugin.string` leaves the bare `string` alias
bound to `core.string`.

The catalog also supports explicit registration. For example, after defining
`CustomerIdGenerator` and `MaskTransform` in your plugin:

```python
from ton import api

catalog = api.build_extension_catalog()
catalog.register_data_type("acme", "customer_id", CustomerIdGenerator())
catalog.register_transform("acme", "mask", MaskTransform())
```

The corresponding config references are `acme.customer_id` and `acme.mask`.
Entry-point names may also be qualified (`acme.customer_id`) or unqualified
(`customer_id`, placed in the `plugin` namespace).

## Entry points

```toml
[project.entry-points."ton.generators"]
my_type = "my_pkg.generators:MyGenerator"

[project.entry-points."ton.transforms"]
"my_ns.my_transform" = "my_pkg.transforms:MyTransform"
```

## Catalogs and instance ownership

`build_extension_catalog` is the canonical loading API; it returns a namespaced `ExtensionCatalog` exposing `generators()`, `transforms()`, and `validators()`:

```python
catalog = api.build_extension_catalog(include_entry_points=True)
snapshot = catalog.snapshot()
for row in api.generate(config_dict,
                        registry=snapshot.generators,
                        transforms=snapshot.transforms,
                        validators=snapshot.validators):
    ...
```

`ExtensionCatalog` treats registered generator instances as prototypes. Each
`catalog.generators()` call returns fresh deep-copied instances, so reusing a
catalog across Engines does not share generator state. Engine construction also
copies supplied registry, transform, and validator mappings together, so reusing
an `EngineOptions` or registry mapping is safe. Read-only mapping containers are
accepted; registered aliases and shared dependencies stay shared within one
Engine. Supplied plugin instances remain unchanged. Generator attributes
must therefore support `copy.deepcopy`. Use `catalog.snapshot()` when combining
generators, transforms, and validators: it clones all three kinds atomically and
preserves dependencies shared between them within that snapshot.

Plugins implement their protocols entirely against `ton.api`: alongside `Generator`
and `PairedGenerator`, the facade exports the contract types a transform, validator,
or proof hook has to name — `PreparationContext`, `TransformResult`, `TransformProof`,
`TransformCapabilities`, and `ProofResult`. No private module import is required.

## Loading failures and trust

A broken plugin discovered through broad `--entry-points` loading is isolated:
failures are logged as `entry_point_failed` and skipped, so one bad package does
not abort the catalog build. Duplicate providers for the same group and
entry-point name are rejected before plugin code loads.
Entry points execute installed package code while loading, so TON loads them only when explicitly requested, either through `api.build_extension_catalog(include_entry_points=True)` or the CLI `--entry-points` flag. To load only named providers, pass exact `GROUP:DISTRIBUTION:NAME` selectors through `allowed_entry_points` or repeat the CLI `--entry-point GROUP:DISTRIBUTION:NAME` option. Every exact selector must be installed and load successfully; missing, duplicate, or broken selected providers raise `RegistryError` and make the CLI exit `2`. Distribution names are normalized case-insensitively across `.`, `_`, and `-`; name-only allowlists are rejected.

These rules apply to all three extension groups. Plugin code is imported and
constructed with the caller's full process privileges; enable only trusted
packages. Entry-point names and values are sanitized to printable ASCII before
logging (control codes and Unicode lookalikes become `?`).

## Transforms

Transforms declare whether they accept paired inputs and whether they preserve
pairing. This lets TON reject incompatible chains at preparation time. For
example, a transform that does not preserve pairing cannot safely support both
`$name$` and `$name[id]$` for the same field.

Transforms implement `prepare(spec, context)`, `apply(prepared, value, rng)`,
and `prove(prepared, before, after)`. Their `nested_specs(spec)` declaration
identifies any owned generator children, resolved with `context.prepare_child`.

A transform using the public API:

```python
from ton import api

class SuffixTransform:
    type_name = "suffix"
    config_keys = frozenset({"suffix"})
    capabilities = api.TransformCapabilities()
    requires_source = True

    def nested_specs(self, spec):
        return ()

    def prepare(self, spec, context):
        return spec["suffix"]

    def apply(self, prepared, value, rng):
        return api.TransformResult(value.value + prepared)

    def prove(self, prepared, before, after):
        return api.TransformProof(ok=after.value == before.value + prepared)

config = {"rows": 2, "format": "$x$", "types": {
    "x": {"type": "string", "values": ["x"],
          "transforms": [{"type": "example.suffix", "suffix": "!"}]}
}}
rows = list(api.generate(config, transforms={"example.suffix": SuffixTransform()},
                         proof_mode="all"))
assert rows == ["x!", "x!"]
```

## Validators

A validator implements `type_name` and `validate(value) -> bool`. It checks the
final generated string; returning `False` raises `api.ValidationError`.
Unexpected exceptions surface as `api.ValidatorExecutionError` at the Engine
boundary. Register instances with `catalog.register_validator(namespace, name, instance)`
or supply a validator mapping when constructing an Engine.

A validator using the public API:

```python
from ton import api

class HasBang:
    type_name = "has_bang"

    def validate(self, value):
        return value.endswith("!")

config = {"rows": 2, "format": "$x$", "types": {
    "x": {"type": "string", "values": ["ok!"], "validators": ["example.has_bang"]}
}}
rows = list(api.generate(config, validators={"example.has_bang": HasBang()}))
assert rows == ["ok!", "ok!"]
```

See [validator configuration](transforms.md#validators) and
[pipeline ordering](architecture.md#pipeline-ordering-and-traces).

## Worker partitioning

Generators and transforms can implement the optional `api.Partitionable` capability:
`partition(spec, offset)` returns an `api.PartitionSpec`. The offset counts draw
slots reserved for earlier workers, including repeated template references and
parent multiplicities. For a composite drawing its `spec` child `count` times:

```python
def partition(self, spec, offset):
    return api.PartitionSpec(child_offsets={("spec",): offset * spec["count"]})
```

Child locations match the tuples declared by `nested_specs`, relative to that
extension's own spec. Unlisted children inherit the incoming offset. Stateful
leaves can return `updates`, for example `{"start": spec["start"] + offset * spec["step"]}`.
Updates must preserve the type, pipeline stages, and owned child containers;
unknown child locations and negative/non-integer offsets are rejected. Partition
hooks run on worker-owned copies of supplied plugins. Built-in `sequence` and
`sequence_of` use this same capability; custom stateful generators must declare
their own partition behavior when they require disjoint ranges.

See [worker construction and spawned processes](concurrency.md#worker-options)
for option ownership and serialization, and [configuration pipelines](transforms.md)
for built-in transforms and validators.
