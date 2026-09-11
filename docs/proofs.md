# Proof checking and audit reports

[Documentation](README.md) · [Project overview](../README.md)

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

## CLI usage

Proof checking can validate generated values during a run:

```bash
ton config.json --proof-check sample --proof-sample-rate 1000
ton config.json --proof-check all
ton config.json --proof-check audit --proof-report proof-audit.jsonl
ton config.json --proof-check audit --proof-report safe-audit.jsonl \
  --redact-proof-failures
```

Strict modes (`sample` and `all`) stop on the first proof failure with row,
field, stage, and reason. Audit mode keeps generating rows and records proof
failures for library callers via `Engine.proof_failures`.

## Report format

Proof reports are UTF-8 JSON Lines with one `ton.proof-audit/v2` object per
failure. Each object contains `row`, `type_key`, `stage`, `reference`, `reason`,
`value`, paired `id_value`, `seed`, and `spec_ref`, plus a `redacted` boolean.
The first clear record for each stable spec fingerprint also contains `spec`;
later records carry only the same `spec_ref`, avoiding repeated large specs. The
CLI streams every failure to the report even after the bounded in-memory
`Engine.proof_failures` sample is full. Reports contain clear values by default;
`--redact-proof-failures` replaces `value`, `reason` and a present `id_value`
with `"<redacted>"`, and writes `spec`/`spec_ref` as `null`. It preserves the
row, field, stage, reference and seed so failures can still be located.

## Library audit sinks

Library callers can stream every audit failure without retaining it in memory
by passing a callable as `proof_failure_sink` to `EngineOptions`,
`Engine.from_config`, or `api.generate`. Worker and shard helpers receive it through
their `options` parameter. The sink is
valid only with `proof_mode="audit"`; it must be installed before iteration.
`Engine.set_proof_failure_sink(...)` supports resources opened after engine
construction and enforces that lifecycle.

## Report publication

Proof-report files use atomic replacement and honor `--no-clobber`. An
open/write failure exits `1`, removes temporary report/data files, and never
publishes a partial regular-file report.

If atomic replacement succeeds but the final directory sync fails, TON reports
that the destination changed and tells the operator to inspect it before
retrying. The published file is complete; its crash-durability could not be
confirmed.

When both `--output` and `--proof-report` are requested, a late failure can
leave the data file published while the report remains old or absent. TON calls
this a `partial output commit`, lists the changed and failed paths, and instructs
the operator to inspect and keep or remove them consistently before retrying.

See [library generation options](library.md#generation-options),
[CLI exit codes](cli.md#exit-codes), and [structured log events](observability.md).
