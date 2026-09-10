# TON Architecture

TON separates config parsing, type registration, row generation, transforms,
and proof checking so each extension point has a narrow contract.

## Public Surface

`ton.api` is the stable library facade. Private modules such as
`ton._engine`, `ton._registry`, and `ton._config` can change between releases.
Applications should build registries and catalogs through `ton.api`.

Generator and preparation contracts live below the catalog and runtime layers
in `ton._contracts`; namespace resolution lives in `ton._references`. Neither
imports concrete generators or the compiler. `ton._pipeline` owns child execution
and draw traces. Shared scalar parsing and formatting live in `ton._scalars`, so
JSON decoding and CLI integer handling do not depend on generator implementations.

## Namespaced Registrations

Built-in data types and transforms live in the `core` namespace. Legacy config
references such as `"type": "integer"` remain valid aliases for
`"type": "core.integer"`.

Plugins register additional namespaced data types, transforms, and validators:

```python
from ton import api

catalog = api.build_extension_catalog()
catalog.register_data_type("acme", "customer_id", CustomerIdGenerator())
catalog.register_transform("acme", "mask", MaskTransform())
```

Plugin registrations are resolved by qualified name, such as
`acme.customer_id`. Built-ins cannot be removed or replaced through
`ExtensionCatalog`; if a plugin registers `plugin.string`, the bare
`string` alias still resolves to `core.string`.

Entry-point loading is opt-in. When enabled, TON loads:

- `ton.generators`
- `ton.transforms`
- `ton.validators`

Entry-point names may be qualified (`acme.customer_id`) or unqualified
(`customer_id`, which is placed in the `plugin` namespace).

Catalog registrations are prototypes. Each registry snapshot deep-copies
generators, transforms, and validators, preserving qualified/bare aliases
within that snapshot while isolating mutable extension state between Engines.
Use `catalog.snapshot()` to obtain all three kinds under one lock with a shared
copy memo, preserving dependencies between a generator, transform, and validator.
Its `CatalogSnapshot` exposes `generators`, `transforms`, and `validators` mappings.
Engine construction treats supplied mappings as prototypes too, normalizing their
containers and copying all three extension kinds with one memo. Reusing mappings
or `EngineOptions` therefore creates independent runtime state without breaking
within-engine aliases or shared dependencies. Plugin attributes must support
deep copying; runtime mutations do not change the caller's supplied prototypes.

## Generation Pipeline

For each template field, `Engine` prepares an explicit pipeline:

1. Source data type: `Generator.prepare(spec, preparation_context)`.
2. Ordered transform chain: `Transform.prepare(spec, preparation_context)`.
3. Per-row source generation, unless the first transform explicitly declares
   that it replaces the source.
4. Per-row transform application.
5. Optional proof checking.
6. Per-row validator checks.

Prepared specs are cached during engine construction. Row generation only
performs required draws, transform application, rendering, and optional proof
checks.

The compiler prepares declared children before their parents using an explicit
work stack. Built-in composites use work stacks for generation and proof too;
nesting has no estimated stack ceiling and does not change the process recursion
limit. Cyclic generator ownership is rejected with its configuration path.
Compilation and worker partitioning use the same ownership records from
`ton._specgraph`: literal child locations, owning extensions, and owner specs.
Preparation includes declared source children; workers traverse only children
that execute when a transform replaces the source. Their traversal policies
remain separate while resolution and ownership stay consistent.
Worker partitioning calls the optional `Partitionable.partition(spec, offset)`
capability on sources and transforms. `PartitionSpec` carries owner-setting
updates and child offsets keyed by declared locations. This replaces concrete
generator checks, preserves opaque metadata, and supports custom multiplicities
and stateful transforms without changes to the worker traversal.

## Transform Contract

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

The built-in `distribution` transform chooses among two or more prepared
candidate data-type specs. The `weighted` generator uses the same distribution
implementation. Both accept a `choices` list of objects containing a generator
`spec` and an optional `weight` (default `1.0`). Use string-generator children
for literal choices; `values` and `weights` are not weighted-generator options.

The built-in `identity` transform returns values unchanged and preserves
paired values. It provides an explicit no-op transform for configs and tests
that need a transform stage without changing generated output.

## Proof Checking

Generators and transforms can implement proof hooks that verify generated
values satisfy their prepared spec. `Engine` supports:

- `off`: no checks.
- `sample`: check every Nth row.
- `all`: check every row and fail on the first proof failure.
- `audit`: check every row, collect proof failures, and keep generating.

Audit failures are available through the bounded in-memory
`Engine.proof_failures` sample. A configured proof-audit sink receives every
failure as it is checked, independently of that retention boundary; the CLI
uses it for `--proof-report` UTF-8 JSON Lines output. Pipeline metadata is
available through `Engine.provenance`, which reports the source type, transform
chain, proof mode, sample rate, and failure count per field.

Structured proof-check logs include identifiers such as row, field, stage, and
reference. They do not include raw generated values. Proof reports include
values, paired ids, and field specs unless `--redact-proof-failures` is set.

## Configuration references

Built-in types can be named with either their bare name or `core.name`.
Plugin types use qualified names. Entry-point loading is opt-in for both CLI
and library callers. Weighted generation has one schema: `choices`.
