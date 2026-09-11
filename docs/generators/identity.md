# Synthetic identities

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `uuid`

UUID4 (default) or synthetic UUID1. Both versions are built from the seeded RNG,
so output is reproducible and UUID1 never exposes the host clock, node id, or MAC address.

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

## `name`

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

## `email`

`<given>.<family>@<domain>`. The local part (`<given>.<family>`) is lowercased;
configured domains preserve their spelling and case. For example,
`domains: ["EXAMPLE.COM"]` produces addresses ending in `@EXAMPLE.COM`.

| field     | type     | description                                                              |
|-----------|----------|--------------------------------------------------------------------------|
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

## `phone`

Replace every `#` in `format` with a random decimal digit.

| field    | type   | description                                               |
|----------|--------|-----------------------------------------------------------|
| `format` | string | pattern with `#` placeholders (must include at least one) |

```json
{"type": "phone", "format": "+1 (###) ###-####"}
```

```
+1 (187) 244-6700
+1 (847) 047-2990
+1 (059) 324-0244
+1 (222) 420-8561
```
