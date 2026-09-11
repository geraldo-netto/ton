# Generator reference

[Documentation](README.md) · [Project overview](../README.md)

Twenty-two built-in types. Each may be referenced by its bare name or its
qualified `core.name`, for example `integer` or `core.integer`.

| Group | Types |
|---|---|
| [Numbers and counters](generators/numeric.md) | [boolean](generators/numeric.md#boolean), [integer](generators/numeric.md#integer), [decimal](generators/numeric.md#decimal), [sequence](generators/numeric.md#sequence) |
| [Strings and bytes](generators/strings.md) | [char](generators/strings.md#char), [string](generators/strings.md#string), [bytes](generators/strings.md#bytes), [text](generators/strings.md#text), [regex](generators/strings.md#regex) |
| [Composites](generators/composites.md) | [weighted](generators/composites.md#weighted), [oneOf](generators/composites.md#oneof), [sequence_of](generators/composites.md#sequence_of) |
| [Dates and timestamps](generators/datetime.md) | [date](generators/datetime.md#date), [timestamp_unix](generators/datetime.md#timestamp_unix) |
| [Network addresses](generators/network.md) | [ipv4 / ipv6](generators/network.md#ipv4--ipv6), [mac](generators/network.md#mac) |
| [Synthetic identities](generators/identity.md) | [uuid](generators/identity.md#uuid), [name](generators/identity.md#name), [email](generators/identity.md#email), [phone](generators/identity.md#phone) |
| [Hashes](generators/hashes.md) | [hash](generators/hashes.md#hash-paired), including [NTLM](generators/hashes.md#ntlm-hashes) |

## Running the examples

Every output block in this reference was produced with `--seed 1`. For a type
spec example, save it as `types.x` in a four-row config:

```json
{"rows": 4, "format": "$x$", "types": {"x": {"type": "integer", "minValue": 1, "maxValue": 9}}}
```

Save the config as `config.json`, then run from the repository root:

```bash
python -m ton config.json --seed 1
```

The hash examples already contain complete four-row configs with paired
placeholders. Use those configs unchanged. The automated documentation tests
verify the displayed output against the seeded generator.

For root settings and placeholders, see [configuration](configuration.md).
Field specs can also include [transforms and validators](transforms.md).
