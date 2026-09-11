# Dates and timestamps

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `date`

Uniform calendar datetime between ISO-8601 bounds. Formatting uses a portable,
locale-neutral `strftime` subset so seeded output stays identical across systems.
Names and composite forms use invariant English/C-locale spellings.
Supported directives are `%a`, `%A`, `%b`, `%B`, `%c`, `%d`, `%H`, `%I`,
`%j`, `%m`, `%M`, `%p`, `%S`, `%U`, `%w`, `%W`, `%x`, `%X`, `%y`, `%Y`,
`%z`, `%Z`, `%f`, and `%%`. `%Z` renders `UTC` plus a numeric offset rather
than a host-specific timezone abbreviation.

Aware bounds are compared as instants and rendered in `minValue`'s timezone.
Generation and proofs use the interval's representable local datetimes in
years 1–9999, including when converting `maxValue` would exceed that calendar.

| field       | type   | description                                       |
|-------------|--------|---------------------------------------------------|
| `minValue`  | string | ISO 8601 (date or datetime), inclusive            |
| `maxValue`  | string | ISO 8601 (date or datetime), inclusive            |
| `format`    | string | portable format (default `%Y-%m-%d %H:%M:%S`)     |

```json
{"type": "date", "minValue": "2024-01-01", "maxValue": "2024-12-31", "format": "%Y-%m-%d %H:%M:%S"}
```

```
2024-02-22 04:21:55
2024-08-09 01:21:52
2024-11-25 02:39:17
2024-11-07 13:39:08
```

## `timestamp_unix`

Same bounds semantics as `date` but emits epoch seconds (or millis).

| field       | type   | description                                  |
|-------------|--------|----------------------------------------------|
| `minValue`  | string | ISO 8601 (date or datetime), inclusive       |
| `maxValue`  | string | ISO 8601 (date or datetime), inclusive       |
| `unit`      | string | `seconds` (default) or `millis`              |

Each unit draws uniformly from the integer timestamps contained in the
inclusive interval. Fractional ISO bounds are rounded inward to the next
representable second or millisecond.

```json
{"type": "timestamp_unix", "minValue": "2024-01-01", "maxValue": "2024-12-31", "unit": "seconds"}
```

```
1708575715
1723166512
1732502357
1730986748
```
