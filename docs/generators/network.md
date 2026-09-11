# Network addresses

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `ipv4` / `ipv6`

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

## `mac`

Generates syntactically valid [48-bit MAC addresses](https://www.rfc-editor.org/rfc/rfc9542.html#section-2.1): six hexadecimal octets, optionally with a fixed 24-bit prefix. Values may be unicast, multicast, or broadcast; vendor allocation and uniqueness are not verified.

| field                | type   | description |
|----------------------|--------|-------------|
| `separator`          | string | `:`, `-`, or `""` for compact hex (default `:`) |
| `uppercase`          | bool   | Uppercase the hex (default `false`) |
| `oui`                | string | Exactly three hex octets: `001A2B`, `00:1A:2B`, or `00-1A-2B`. Whitespace, mixed separators, and misplaced separators are rejected. |
| `invalidProbability` | number | Probability of intentionally invalid output, from `0` to `1` (default `0`). `0` produces only valid addresses; `1` produces only invalid values. |

```json
{"type": "mac", "oui": "00:1A:2B"}
```

```
00:1a:2b:b1:65:22
00:1a:2b:58:b7:91
00:1a:2b:6a:f1:d8
00:1a:2b:3e:61:cd
```

For negative testing, invalid values contain **five octets** instead of six. They retain the configured prefix, separator, and case. Each row is selected independently, so the proportion in a finite batch is approximate; the same seed reproduces the same rows. Decimal JSON probabilities are sampled exactly, including very small nonzero values.

This example selects invalid output with probability 25% per row:

```json
{"type": "mac", "oui": "00:1A:2B", "invalidProbability": 0.25}
```

```
00:1a:2b:58:b7:91
00:1a:2b:4c:41
00:1a:2b:d4:7e
00:1a:2b:10:e5:78
```

Proof checking validates this configured contract: intentional five-octet values pass when `invalidProbability > 0`, and six-octet addresses pass when `invalidProbability < 1`. Wrong prefixes, case, or layouts still fail. Configuration errors are rejected at every probability.
