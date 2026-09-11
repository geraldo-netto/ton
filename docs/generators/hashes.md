# Hashes and paired values

[Documentation](../README.md) · [Generator index](../generators.md)

Examples use `--seed 1`; see [how to run them](../generators.md#running-the-examples).

## `hash` (paired)

Digest drawn from a fixed plaintext list. **Paired**: a single row may reference both the digest (`$word$`) and the plaintext (`$word[id]$`).

| field       | type     | description                                          |
|-------------|----------|------------------------------------------------------|
| `algorithm` | string   | `md5`, `sha1`, `sha256` (default), `sha512`, `bcrypt`, or `ntlm` |
| `values`    | string[] | non-empty plaintext pool                            |
| `rounds`    | int      | bcrypt cost (default `12`; range `4`–`31`)          |
| `cache`     | boolean  | cache selected bcrypt digests (default `false`)     |

`bcrypt` requires the optional `ton[bcrypt]` extra and accepts `rounds` from `4` to `31` (default `12`). TON derives a stable bcrypt salt from the plaintext so synthetic fixtures remain reproducible.
Plaintext entries are limited by bcrypt's format to 72 UTF-8 bytes and are
rejected during config preparation when they exceed that boundary.
Digest caching is disabled by default so memory does not grow with the selected
plaintext pool. Operators may set `cache: true` for bcrypt workloads that
prefer reusing expensive digests and can accommodate one cached value per
selected plaintext. Inexpensive digest algorithms are recomputed without a
duplicate cache.

> **Fixture-data warning:** Treat every `hash` output as synthetic fixture data,
> never as stored credentials. Deterministic bcrypt salts are unsuitable for
> password storage, and MD5, SHA-1, and NTLM are weak or legacy algorithms.

```json
{
  "rows": 4,
  "format": "$word[id]$ -> $word$",
  "types": {"word": {"type": "hash", "algorithm": "sha256",
                     "values": ["password", "secret", "admin"]}}
}
```

```
password -> 5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8
admin -> 8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918
password -> 5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8
secret -> 2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b
```

### NTLM hashes

Set `algorithm` to `ntlm` for the canonical Windows NT hash (MD4 of UTF-16LE plaintext). It is intentionally insecure and should only be used for synthetic credential fixtures.

```json
{
  "rows": 4,
  "format": "$word[id]$ -> $word$",
  "types": {"word": {"type": "hash", "algorithm": "ntlm",
                     "values": ["password", "secret", "admin"]}}
}
```

```
password -> 8846f7eaee8fb117ad06bdd830b7586c
admin -> 209c6174da490caeb422f3fa5a7ae634
password -> 8846f7eaee8fb117ad06bdd830b7586c
secret -> 878d8014606cda29677a44efa1353fc7
```

See [paired template references](../configuration.md#paired-references-nameid) for the tuple contract and composite restrictions.
