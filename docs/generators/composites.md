# Composite generators

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `weighted`

Sampling uses exact proportional weights and integer draws. Finite decimal weights
retain their ratios at any magnitude; zero-weight choices are never selected.

Pick one alternative with probability proportional to its effective weight.
Omitted `weight` defaults to `1.0`. Sampling is uniform (1/N per entry) when
all effective weights are equal.

For example, the omitted weight below is 1, so `rare` has probability 1/10
and `common` has probability 9/10:

```json
{"type": "weighted", "choices": [
  {"weight": 9, "spec": {"type": "string", "values": ["common"]}},
  {"spec": {"type": "string", "values": ["rare"]}}
]}
```

Any registered generator can be weighted, not just literal strings:

| field     | type     | description                                                       |
|-----------|----------|-------------------------------------------------------------------|
| `choices` | object[] | each entry is `{"weight": number?, "spec": <type spec>}` — `weight` defaults to `1.0` when omitted |

```json
{"type": "weighted",
 "choices": [
   {"weight": 70, "spec": {"type": "string", "values": ["common"]}},
   {"weight": 30, "spec": {"type": "integer", "minValue": 0,
                            "maxValue": 99, "padWithZero": false}}
 ]}
```

```
common
common
97
60
```

Composite `choices` may themselves nest `weighted` / `oneOf` / `sequence_of`. Paired generators (`hash`) cannot be used as a composite child — the `[id]` half would be unreachable from outside the wrapper, so the engine rejects such configs at construction time.
Choice wrappers accept only `weight` and `spec`; misspelled or extra keys are
rejected with an indexed configuration path and a suggestion when available.

## `oneOf`

Pick uniformly between several nested type specs. Same as `weighted` with equal weights, just less typing.

| field     | type     | description                                |
|-----------|----------|--------------------------------------------|
| `choices` | object[] | each entry is itself a full type spec      |

```json
{"type": "oneOf",
 "choices": [
   {"type": "string", "values": ["alpha"]},
   {"type": "string", "values": ["beta"]},
   {"type": "integer", "minValue": 0, "maxValue": 9, "padWithZero": false}
 ]}
```

```
alpha
beta
beta
beta
```

## `sequence_of`

Concatenate `count` independent draws from a single child spec, joined by an optional separator. Handy for compound identifiers that don't fit cleanly into the `regex` quantifier surface.

| field       | type   | description                                              |
|-------------|--------|----------------------------------------------------------|
| `count`     | int    | draws per row (N ≥ 1)                                    |
| `separator` | string | inserted between draws (default empty)                   |
| `spec`      | object | child type spec                                          |

```json
{"type": "sequence_of",
 "count": 4,
 "separator": "-",
 "spec": {"type": "integer", "minValue": 0, "maxValue": 9, "padWithZero": false}}
```

```
2-9-1-4
1-7-7-7
6-3-1-7
0-6-6-9
```

See also [transform chains](../transforms.md) and [paired-reference restrictions](../configuration.md#paired-references-nameid).
