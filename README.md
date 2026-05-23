# TON

> Mass data generator: synthesize structured test data from a JSON template.

TON renders rows of structured text from a small JSON description. It is
useful when you need a few million lines of plausible-looking CSV, TSV,
log records, or fixtures and you do not want to glue together a
one-off Python script every time.

## Install

```bash
pip install -e .
```

Python 3.9 or newer. TON has zero runtime dependencies.

## Run without installing

TON has no third-party runtime requirements, so from a checkout you
can invoke it straight from the repo root:

```bash
# from the repo root, no pip install needed
python -m ton examples/hwmetrics.json
```

The current directory is on `sys.path` automatically, so Python finds
the `ton/` package without `pip install`. Run from somewhere else by
pointing `PYTHONPATH` at the checkout:

```bash
PYTHONPATH=/path/to/ton python -m ton /path/to/config.json
```

The same flags described below (`--seed`, `--output`, `--verbose`,
`--progress`) work in this mode.

## Usage

```bash
ton examples/hwmetrics.json
```

Pin the RNG for reproducible output:

```bash
ton examples/hwmetrics.json --seed 42
```

Stream to a file (avoids buffering in your shell):

```bash
ton examples/hwmetrics.json -o hwmetrics.csv
```

Observability flags (everything goes to stderr; stdout stays clean
for piping):

```bash
ton examples/dna.json --verbose                  # final rows/s summary
ton examples/dna.json --progress 100000          # JSON progress every N rows
```

`ton` only ever writes generated rows to stdout. Errors go to stderr
with a `ton:` prefix. Exit codes: `0` success, `1` missing config or
output error, `2` invalid config / unknown variable, `3` unexpected
error, `130` interrupted (Ctrl-C).

You can also run via the module form:

```bash
python -m ton examples/hwmetrics.json
```

## Library use

`ton.api` is the only stable public surface. Everything under
`ton._engine`, `ton._template`, `ton._registry`, `ton._config` is
private (single leading underscore) and may change between releases.

```python
from ton import api

rows = list(api.generate_from_file("examples/dna.json", seed=42))

for row in api.generate(config_dict, seed=42):
    sink.write(row)

# Exceptions and Engine are re-exported from ton.api too:
try:
    rows = list(api.generate(bad_config))
except (api.ConfigError, api.TemplateError) as exc:
    ...
```

Custom generators register via the `ton.generators` entry-point group
in any installed package:

```toml
[project.entry-points."ton.generators"]
uuid = "my_pkg.generators:UuidGenerator"
```

Parallel runs use `ton.concurrency`:

```python
from ton import api, concurrency
config = api.load_config("examples/dna.json")
eng = concurrency.fork_engine(config, parent_seed=42, worker_id=0, rows=1_000_000)
for row in eng:
    ...
```

## Config format

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

- `rows` — how many rows to emit (non-negative integer).
- `format` — the template; any `$name$` segment is a variable that
  must be declared in `types`. `$$` renders a literal `$`.
- `types` — a map of variable name to type spec.

### Type reference

Twenty built-in types. Every output below was produced with
`--seed 1` on a 4-row config of the form
`{"rows": 4, "format": "$x$", "types": {"x": <spec>}}` so the
examples are byte-reproducible.

#### `boolean`

Pick one of two literals with equal probability.

| field        | type   | description              |
|--------------|--------|--------------------------|
| `whenTrue`   | string | rendered when "true"     |
| `whenFalse`  | string | rendered when "false"    |

```json
{"type": "boolean", "whenTrue": "Y", "whenFalse": "N"}
```

```
Y
Y
N
Y
```

#### `integer`

Uniform integer in `[minValue, maxValue]`, optionally zero-padded.
Padding width spans the wider of the min/max rendering (so negative
values line up with positives).

| field         | type    | description                           |
|---------------|---------|---------------------------------------|
| `minValue`    | int     | inclusive lower bound                 |
| `maxValue`    | int     | inclusive upper bound (>= `minValue`) |
| `padWithZero` | bool    | left-pad to a fixed width             |

```json
{"type": "integer", "minValue": 1, "maxValue": 9999, "padWithZero": true}
```

```
2202
9326
1034
4180
```

Unpadded with negatives:

```json
{"type": "integer", "minValue": -100, "maxValue": 100, "padWithZero": false}
```

```
-66
45
95
-84
```

#### `decimal`

Uniform float in `[minValue, maxValue]`, rounded and formatted to
exactly `decimals` digits after the decimal point.

| field         | type    | description                                  |
|---------------|---------|----------------------------------------------|
| `minValue`    | number  | inclusive lower bound                        |
| `maxValue`    | number  | inclusive upper bound (>= `minValue`)        |
| `decimals`    | int     | digits after the decimal point (>= 0)        |
| `padWithZero` | bool    | left-pad to a fixed width including sign + dot |

```json
{"type": "decimal", "minValue": 0.0, "maxValue": 100.0, "decimals": 2, "padWithZero": false}
```

```
13.44
84.74
76.38
25.51
```

#### `char`

Concatenate `maxChar` random picks from `values` (with replacement).

| field      | type      | description                              |
|------------|-----------|------------------------------------------|
| `values`   | string[]  | non-empty alphabet                       |
| `maxChar`  | int       | output length (1 ≤ N ≤ `MAX_CHAR_LENGTH`) |

```json
{"type": "char", "values": ["A", "C", "G", "T"], "maxChar": 6}
```

```
CAGATT
TTCATA
TTATGC
AGAAAA
```

#### `string`

Pick one literal uniformly from `values`.

| field    | type     | description           |
|----------|----------|-----------------------|
| `values` | string[] | non-empty literal pool |

```json
{"type": "string", "values": ["Intel", "AMD", "ARM"]}
```

```
Intel
ARM
Intel
AMD
```

#### `weighted`

Like `string`, but the per-value probability is proportional to its
weight. Two shapes accepted (parallel arrays or `[{value, weight}]`
records).

| field     | type           | description                                |
|-----------|----------------|--------------------------------------------|
| `values`  | string[]       | non-empty literal pool                     |
| `weights` | number[]       | non-negative, same length as `values`      |

```json
{"type": "weighted", "values": ["Intel", "AMD", "ARM"], "weights": [90, 8, 2]}
```

```
Intel
Intel
Intel
Intel
```

(Skew toward `Intel` matches the 90/8/2 weighting.)

#### `date`

Uniform calendar datetime between ISO-8601 bounds, formatted with
`strftime`.

| field       | type   | description                                       |
|-------------|--------|---------------------------------------------------|
| `minValue`  | string | ISO 8601 (date or datetime), inclusive            |
| `maxValue`  | string | ISO 8601 (date or datetime), inclusive            |
| `format`    | string | `strftime` format (default `%Y-%m-%d %H:%M:%S`)   |

```json
{"type": "date", "minValue": "2024-01-01", "maxValue": "2024-12-31",
 "format": "%Y-%m-%d %H:%M:%S"}
```

```
2024-02-22 04:21:55
2024-08-09 01:21:52
2024-11-25 02:39:17
2024-11-07 13:39:08
```

#### `timestamp_unix`

Same bounds semantics as `date` but emits epoch seconds (or millis).

| field       | type   | description                                  |
|-------------|--------|----------------------------------------------|
| `minValue`  | string | ISO 8601 (date or datetime), inclusive       |
| `maxValue`  | string | ISO 8601 (date or datetime), inclusive       |
| `unit`      | string | `seconds` (default) or `millis`              |

```json
{"type": "timestamp_unix", "minValue": "2024-01-01", "maxValue": "2024-12-31",
 "unit": "seconds"}
```

```
1708575715
1723166512
1732502357
1730986748
```

#### `uuid`

UUID4 (default) or UUID1. UUID4 is built from the seeded RNG, so it
is reproducible; UUID1 uses the host clock + node id and ignores
the seed.

| field        | type | description                          |
|--------------|------|--------------------------------------|
| `version`    | int  | `1` or `4` (default `4`)             |
| `uppercase`  | bool | upper-case the hex (default `false`) |

```json
{"type": "uuid", "version": 4}
```

```
f5b16522-4a58-4791-9f6a-f1d8303e61cd
c4bb86c3-d1c4-4710-bc34-4c4189eb2f1e
7bd5d47e-446f-4ec2-a3d8-11736110e578
1bcccea6-9676-4e61-96c6-e9c92d99bf35
```

#### `sequence`

Monotonic counter, useful for primary keys / row ids. State lives on
the prepared spec, so each Engine instance has its own counter.

| field      | type | description                       |
|------------|------|-----------------------------------|
| `start`    | int  | first value (default `0`)         |
| `step`     | int  | non-zero increment (default `1`)  |
| `padWidth` | int  | zero-pad to this width (`0` off)  |

```json
{"type": "sequence", "start": 1000, "step": 1}
```

```
1000
1001
1002
1003
```

#### `bytes`

Random bytes encoded for transport.

| field      | type   | description                                 |
|------------|--------|---------------------------------------------|
| `length`   | int    | raw byte count (1 ≤ N ≤ `MAX_BYTES_LENGTH`) |
| `encoding` | string | `hex` (default), `base64`, or `base32`      |

```json
{"type": "bytes", "length": 8, "encoding": "hex"}
```

```
f5b165224a58b791
df6af1d8303e61cd
c4bb86c3d1c42710
3c344c4189eb2f1e
```

```json
{"type": "bytes", "length": 16, "encoding": "base64"}
```

```
9bFlIkpYt5HfavHYMD5hzQ==
xLuGw9HEJxA8NExBiesvHg==
e9XUfkRvzsKj2BFzYRDleA==
G8zOppZ2LmEWxunJLZm/NQ==
```

#### `ipv4` / `ipv6`

Random IP inside a CIDR block.

| field   | type   | description                                  |
|---------|--------|----------------------------------------------|
| `cidr`  | string | CIDR (defaults `0.0.0.0/0` or `::/0`)        |

```json
{"type": "ipv4", "cidr": "10.0.0.0/16"}
```

```
10.0.68.203
10.0.32.79
10.0.130.152
10.0.60.95
```

```json
{"type": "ipv6", "cidr": "2001:db8::/32"}
```

```
2001:db8:414c:343c:1027:c4d1:c386:bbc4
2001:db8:7311:d8a3:c2ce:6f44:7ed4:d57b
2001:db8:c9e9:c616:612e:7696:a6ce:cc1b
2001:db8:f1fd:42a2:9755:d4c1:3a90:2931
```

#### `mac`

48-bit MAC address, optionally with a fixed 24-bit OUI prefix.

| field        | type   | description                                |
|--------------|--------|--------------------------------------------|
| `separator`  | string | single char between octets (default `:`)   |
| `uppercase`  | bool   | upper-case the hex (default `false`)       |
| `oui`        | string | 24-bit prefix (`00:1A:2B`, `00-1A-2B`, …)  |

```json
{"type": "mac", "oui": "00:1A:2B"}
```

```
00:1a:2b:b1:65:22
00:1a:2b:58:b7:91
00:1a:2b:6a:f1:d8
00:1a:2b:3e:61:cd
```

#### `name`

Random person name from built-in given/family pools.

| field   | type   | description                            |
|---------|--------|----------------------------------------|
| `style` | string | `full` (default), `given`, or `family` |

```json
{"type": "name", "style": "full"}
```

```
Dara Silva
Bobby Ito
Chen Patel
Omar Patel
```

#### `email`

`<given>.<family>@<domain>`, lowercased.

| field     | type     | description                                                    |
|-----------|----------|----------------------------------------------------------------|
| `domains` | string[] | optional override; default is `example.com / .org / .net / test.invalid` |

```json
{"type": "email"}
```

```
dara.silva@example.com
ines.davila@test.invalid
omar.patel@test.invalid
felix.davila@test.invalid
```

#### `phone`

Replace every `#` in `format` with a random decimal digit.

| field    | type   | description                                  |
|----------|--------|----------------------------------------------|
| `format` | string | pattern with `#` placeholders (must include at least one) |

```json
{"type": "phone", "format": "+1 (###) ###-####"}
```

```
+1 (291) 417-7763
+1 (170) 669-0743
+1 (915) 000-8063
+1 (608) 377-8353
```

#### `text`

Lorem-style words, sentences, or paragraphs (single-line output, safe
inside CSV).

| field   | type   | description                                          |
|---------|--------|------------------------------------------------------|
| `unit`  | string | `words` (default), `sentences`, or `paragraphs`      |
| `count` | int    | how many units (1 ≤ N ≤ `MAX_TEXT_COUNT`)            |

```json
{"type": "text", "unit": "words", "count": 6}
```

```
sed irure qui proident occaecat amet
dolore elit ea occaecat nisi ex
esse nostrud non ut adipiscing ea
ipsum mollit culpa nostrud laboris reprehenderit
```

#### `regex`

Produce strings matching a user-supplied regex. Supports literals,
character classes, escapes (`\d \w \s` and their negations),
quantifiers, alternation, and groups. Unbounded `*` / `+` are capped
at `MAX_UNBOUNDED_REPEAT` extra repeats; literal `{N}` quantifiers
are capped at `MAX_LITERAL_REPEAT`.

| field     | type   | description                       |
|-----------|--------|-----------------------------------|
| `pattern` | string | non-empty regex                   |

```json
{"type": "regex", "pattern": "[A-Z]{3}-\\d{4}"}
```

```
SZY-4177
UMZ-1706
TYY-7439
KAA-8063
```

#### `lmhash` (paired)

Canonical Windows NT hash (MD4 of UTF-16LE plaintext) drawn from a
fixed word list. **Paired**: a single row may reference both the
hash (`$word$`) and the plaintext that produced it (`$word[id]$`).
Intentionally insecure — use only for synthetic credential fixtures.

| field    | type     | description                |
|----------|----------|----------------------------|
| `values` | string[] | non-empty plaintext pool   |

```json
{
  "rows": 4,
  "format": "$word[id]$ -> $word$",
  "types": {"word": {"type": "lmhash", "values": ["password", "secret", "admin"]}}
}
```

```
password -> 8846f7eaee8fb117ad06bdd830b7586c
admin -> 209c6174da490caeb422f3fa5a7ae634
password -> 8846f7eaee8fb117ad06bdd830b7586c
secret -> 878d8014606cda29677a44efa1353fc7
```

### Paired references (`$name[id]$`)

Any **paired** generator (currently `lmhash`; third parties can opt in
via `PairedGenerator`) returns a `(id_value, primary_value)` tuple per
row. The template engine routes:

- `$name$` → `primary_value`
- `$name[id]$` → `id_value`

The two facets stay consistent within a single row, so a single
plaintext is shown alongside its own hash.

## Bundled example configs

- [`examples/hwmetrics.json`](examples/hwmetrics.json) — timestamped CPU telemetry.
- [`examples/dna.json`](examples/dna.json) — SNP records (`rsID`, chromosome, position, genotype).
- [`examples/winhash.json`](examples/winhash.json) — NT-hash rainbow-table seed.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check ton tests
mypy ton
```

Behavior guidelines for AI agents live in [`AGENTS.md`](AGENTS.md);
review findings are tracked in [`TODO.md`](TODO.md).

## License

[BSD 3-Clause](LICENSE)
