# Transforms and validators

[Documentation](README.md) · [Project overview](../README.md)

Type specs may include an ordered `transforms` list. Built-in specs accept bare names such as
`{"type": "integer"}`; built-ins can also be referenced with the
explicit `core.` namespace, for example `{"type": "core.integer"}`.

## Validators

Type specs may also include a `validators` list of validator references.
Validators run after source generation, transforms, and any enabled proof checks. The built-in
`non_empty` validator rejects empty strings; plugins may add namespaced
validators such as `plugin.check`:

```json
{"type": "string", "values": ["ok"], "validators": ["non_empty"]}
```

## Distribution

The built-in `distribution` transform chooses among two or more prepared
candidate type specs. It is a source-independent first stage: TON does not
draw the field's nominal source before selecting a candidate.

```json
{
  "type": "string",
  "values": ["not drawn"],
  "transforms": [
    {
      "type": "distribution",
      "choices": [
        {"weight": 80, "spec": {"type": "string", "values": ["common"]}},
        {"weight": 20, "spec": {"type": "integer", "minValue": 1, "maxValue": 9}}
      ]
    }
  ]
}
```

## Identity

The built-in `identity` transform is an explicit no-op. It returns generated
values unchanged and preserves paired values, so it is mainly useful when a
config or test needs a transform step without changing output.

## Plugin references

Plugins register namespaced data types and transforms through the public
catalog API or trusted entry points. A plugin-provided type can be referenced
with its qualified name:

```json
{"type": "acme.customer_id", "prefix": "CUST"}
```

Load installed plugin entry points explicitly:

```bash
ton config.json --entry-points --list-namespaces
```

See [extension authoring](extensions.md#transforms) for transform contracts,
[configuration](configuration.md) for field placement, and [proof checking](proofs.md)
for validation of generated values.
