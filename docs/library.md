# Python library

[Documentation](README.md) · [Project overview](../README.md)

```python
from ton import api

# One-shot, deterministic:
rows = list(api.generate_from_file("examples/dna.json", seed=42))

# Streaming form for large outputs. Rows carry no line terminator, so a
# text sink needs one -- writing the bare row concatenates every record:
for row in api.generate(config_dict, seed=42):
    sink.write(f"{row}\n")

# Exceptions, Engine, and the LogEvent enum are all re-exported:
try:
    rows = list(api.generate(bad_config))
except (api.ConfigError, api.TemplateError, api.OutputEncodingError) as exc:
    ...  # the config is invalid, or a value could not be encoded
except api.PipelineStageError as exc:
    ...  # a generator/transform/validator/proof hook raised at row time
```

## Engine lifecycle

For finer control, construct an `Engine` directly:

```python
from ton import api

engine = api.Engine.from_file("examples/dna.json", seed=42)
print(engine.total_rows, engine.rows_emitted)   # 10, 0
for row in engine:
    ...
print(engine.rows_emitted)                       # 10

# Or with an in-memory config + custom registry / milestone:
engine = api.Engine.from_config(
    config_dict,
    seed=42,
    milestone_rows=100_000,   # emits engine_milestone log events
)
```

An `Engine` is single-shot: iterate it once, then construct a new Engine for
another pass. This gives the RNG, proof checker, and stateful generators such
as `sequence` one unambiguous lifecycle. Calling `api.generate(...)` again
constructs a fresh Engine and reproduces seeded output.

## Configuration helpers

- `validate_config(config, *, catalog=None) -> None` validates structure,
  references, extension-owned keys, and prepared generator specs. It raises
  `ConfigError` on invalid input and returns `None` on success.
- `output_encoding(config) -> str` returns the configured top-level encoding,
  or `"utf-8"` when omitted.
- `normalize_reference(reference) -> str` qualifies bare extension names with
  `core.` and preserves qualified names. Invalid identifiers raise
  `RegistryError`.

## Public types and errors

- `RegistryError` reports invalid, duplicate, or ambiguous extension
  registrations.
- `Transform` and `Validator` are runtime-checkable protocols for post-source
  processing and final-value checks.
- `Engine.provenance` returns immutable `ProvenanceRecord` entries containing
  each field's source type, transform chain, proof settings/failure count, and
  plugin package/version when available.
- `ProofFailure` is the immutable audit record delivered to the public
  `ProofFailureSink` callback type.

`OutputEncodingError` is the public output-domain error for a value that a
configured text codec cannot represent. Its `encoding` attribute names the
codec, `field_name` identifies the source field when known (otherwise `None`
for a rendered row), and the message includes the codec failure reason.

## Generation options

`generate(config, *, seed=None, registry=None, transforms=None,
validators=None, proof_mode="off", proof_sample_rate=1,
milestone_rows=0, redact_proof_failures=False, proof_failure_sink=None)` and `generate_from_file`
accept the same generation options. For example:

```python
catalog = api.build_extension_catalog()
rows = api.generate_from_file(
    "config.json",
    seed=42,
    validators=catalog.validators(),
    proof_mode="sample",
    proof_sample_rate=100,
    redact_proof_failures=True,
)
```

`proof_mode` is `off`, `sample`, `all`, or `audit`; sample mode checks every
Nth row. Redaction removes values, plugin-controlled reasons, and specs from
strict failure diagnostics, retained audit failures, and CLI proof reports.
Structured logs always omit generated values, specs, and proof reasons. Redaction
can be used with `sample` or `all` without creating a proof report and does not
alter generated rows.

See [proof checking and reports](proofs.md) for audit sinks and redaction,
[extension authoring](extensions.md) for plugins, and [concurrency](concurrency.md)
for worker Engines and shard output. Commands and example paths assume the repository root.
