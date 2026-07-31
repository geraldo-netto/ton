# TON Architecture

TON separates config parsing, type registration, row generation, transforms,
and proof checking so each extension point has a narrow contract.

## Public Surface

`ton.api` is the stable library facade. Private modules such as
`ton._engine`, `ton._registry`, and `ton._config` can change between releases.
Applications should build registries and catalogs through `ton.api`.

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
`ExtensionCatalog`; if a plugin registers `plugin.string`, the legacy
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

## Generation Pipeline

For each template field, `Engine` prepares an explicit pipeline:

1. Source data type: `Generator.prepare(spec, preparation_context)`.
2. Ordered transform chain: `Transform.prepare_composite()`.
3. Per-row source generation.
4. Per-row transform application.
5. Optional proof checking.
6. Per-row validator checks.

Prepared specs are cached during engine construction. Row generation only
performs draws, transform application, rendering, and optional proof checks.

## Transform Contract

Transforms declare whether they accept paired inputs and whether they preserve
pairing. This lets TON reject incompatible chains at preparation time. For
example, a transform that does not preserve pairing cannot safely support both
`$name$` and `$name[id]$` for the same field.

The built-in `distribution` transform chooses among two or more prepared
candidate data-type specs. The legacy `weighted` generator delegates its
composite choice behavior to the same distribution implementation while
preserving existing `weighted` config shapes.

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

## Compatibility

Existing configs using unqualified built-in type names remain supported.
Existing `weighted` legacy and composite forms remain supported. Plugin loading
remains opt-in for both CLI and library callers.
