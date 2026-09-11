# Strings and bytes

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `char`

Concatenate `maxChar` random picks from `values` (with replacement).

| field      | type      | description                              |
|------------|-----------|------------------------------------------|
| `values`   | string[]  | non-empty pool; entries may be longer than one character |
| `maxChar`  | int       | number of draws (N ≥ 1), not output length |

`maxChar` counts draws, so the output is `maxChar` characters only when every
pool entry is a single character. With `{"values": ["ab"], "maxChar": 2}` each
row is `abab` — two draws of a two-character entry.

```json
{"type": "char", "values": ["A", "C", "G", "T"], "maxChar": 6}
```

```
ATTCCC
GTAATC
TACGAT
TAAGTC
```

## `string`

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

## `bytes`

Random bytes encoded for transport.

| field      | type   | description                                 |
|------------|--------|---------------------------------------------|
| `length`   | int    | raw byte count (default `16`; N ≥ 1)                      |
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

## `text`

Lorem-style words, sentences, or paragraphs (single-line output, safe inside CSV).

| field   | type   | description                                          |
|---------|--------|------------------------------------------------------|
| `unit`  | string | `words` (default), `sentences`, or `paragraphs`      |
| `count` | int    | how many units (default `5`; N ≥ 1)                    |

```json
{"type": "text", "unit": "words", "count": 6}
```

```
sed irure qui proident occaecat amet
dolore elit ea occaecat nisi ex
esse nostrud non ut adipiscing ea
ipsum mollit culpa nostrud laboris reprehenderit
```

## `regex`

Produce strings matching a user-supplied regex. Supports literals, character
classes, escapes (`\d \w \s` and their negations), quantifiers, alternation,
and groups. Start/end anchors are supported at the boundary of every
alternative; internal start/end anchors and word-boundary anchors are rejected
during preparation. Unbounded `*` / `+` use a geometric distribution: every
finite repetition count is reachable and each draw terminates with probability
1. Explicit quantifiers and group nesting have no fixed expansion ceiling;
nested patterns are prepared and emitted iteratively.

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
