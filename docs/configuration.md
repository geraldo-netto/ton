# Configuration and templates

[Documentation](README.md) · [Project overview](../README.md)

A config is a JSON object describing the row count, text template and named
field specifications. Save it to a file for the CLI or pass the mapping to the
[Python API](library.md).

## Root settings

```json
{
  "encoding": "UTF-8",
  "rows": 10,
  "format": "$timestamp$;$cpu_type$;$cpu_usage$",
  "types": {
    "timestamp": {"type": "date",    "minValue": "1100-01-01", "maxValue": "2050-12-31", "format": "%Y-%m-%d %H:%M:%S"},
    "cpu_type":  {"type": "string",  "values": ["AMD", "Intel", "ARM"]},
    "cpu_usage": {"type": "decimal", "minValue": 0.0, "maxValue": 100.0, "decimals": 2, "padWithZero": false}
  }
}
```

- `rows` — how many rows to emit (non-negative integer; no fixed maximum).
- `format` — the template; any `$name$` segment is a variable that must be declared in `types`. `$$` renders a literal `$`. A trailing `[id]` (e.g. `$word[id]$`) requests the paired-id facet of a paired generator — see [Paired references](#paired-references-nameid).
- `types` — a map of variable name to type spec.
- `encoding` — optional; the text codec used for file output and stdout (default `utf-8`). Must be a text codec Python recognizes; stdout is temporarily reconfigured for the run and restored afterward.
- `maxRowWidth` — optional positive integer bounding the complete rendered row; omitted by default.
- A value that the configured codec cannot represent is an output error (CLI exit `1`), not a configuration error.

Unknown root keys and unknown keys owned by built-in generators/transforms are
rejected, including inside nested composite specs. Diagnostics include the full
config path and a suggestion for close typos. Plugin generators keep an open
key namespace unless they declare `config_keys`; existing plugin-specific
options remain valid.

## Row width

Rows have no implicit width ceiling. Set the optional top-level `maxRowWidth`
positive integer when an operator-controlled guard is required. The limit
covers the complete rendered row—literals and all placeholders—and raises
`TemplateError` before the row is yielded or written.

## Field pipelines

Each field spec selects a `type`. Its optional `transforms` list runs in order,
and its optional `validators` list checks the final value after proof checking
on checked rows. See [transforms and validators](transforms.md),
[proof modes](proofs.md), and the [generator reference](generators.md).

## Paired references (`$name[id]$`)

Any **paired** generator (currently `hash`; third parties can opt in via `PairedGenerator`) returns a `(id_value, primary_value)` tuple per row. The template engine routes:

- `$name$` → `primary_value`
- `$name[id]$` → `id_value`

The two facets stay consistent within a single row, so a single plaintext is shown alongside its own hash. Paired generators cannot be used as children of a composite generator (`weighted`, `oneOf`, `sequence_of`) — the `[id]` half would be unreachable from outside the wrapper, so the engine rejects such configs at construction time.
