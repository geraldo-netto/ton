# TON

> Mass data generator: synthesize structured test data from a JSON template.

TON renders rows of structured text from a small JSON description. Use it to
produce CSV, TSV, log records, or fixtures, including runs with millions of rows.
Generation streams one row at a time and supports reproducible seeds, plugins,
proof checks and process partitioning.

Python 3.12 or newer. TON has zero required third-party runtime dependencies.
The optional `bcrypt` hash algorithm requires the `ton[bcrypt]` extra.

## Quick start

From a checkout of this repository:

```bash
python -m ton examples/hwmetrics.json --seed 42
python -m ton examples/hwmetrics.json --seed 42 -o hwmetrics.csv
```

To install the `ton` command from that checkout:

```bash
pip install -e .
ton examples/hwmetrics.json --seed 42
```

## Define a config

Save this as `config.json`:

```json
{
  "rows": 4,
  "format": "$id$,$name$",
  "types": {
    "id": {"type": "sequence", "start": 1},
    "name": {"type": "string", "values": ["Ada", "Lin", "Sam"]}
  }
}
```

Generate rows with `python -m ton config.json --seed 1`.
See [configuration and templates](docs/configuration.md) for the schema and
[the generator reference](docs/generators.md) for available types and examples.

## Documentation

Start with the [documentation index](docs/README.md), or jump to a guide:

- [CLI](docs/cli.md): flags, exit codes, output and recovery.
- [Python library](docs/library.md): streaming rows and Engine lifecycle.
- [Extensions](docs/extensions.md): plugin contracts and loading.
- [Parallel generation](docs/concurrency.md): workers, shards and merging.
- [Proof checking](docs/proofs.md), [transforms and validators](docs/transforms.md),
  and [logging](docs/observability.md).
- [Architecture](docs/architecture.md), [development](docs/development.md),
  and [benchmarks](docs/benchmarks.md).

## Bundled examples

- [CPU telemetry](examples/hwmetrics.json).
- [SNP records](examples/dna.json).
- [Synthetic NT hashes](examples/winhash.json); see the
  [hash fixture guidance](docs/generators/hashes.md#hash-paired).

## License

[BSD 3-Clause](LICENSE)
