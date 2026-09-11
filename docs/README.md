# TON documentation

[Project overview and quick start](../README.md)

Commands and relative example paths in these guides assume the repository root.
From an uninstalled checkout, use `python -m ton` wherever a command starts with `ton`.

| Task | Guide |
|---|---|
| Run TON, select CLI flags, resume output | [Command-line interface](cli.md) |
| Define rows, templates, encoding and paired placeholders | [Configuration](configuration.md) |
| Choose a built-in type and reproduce its examples | [Generator reference](generators.md) |
| Apply transforms and final-value validators | [Transforms and validators](transforms.md) |
| Generate rows from Python and inspect an Engine | [Python library](library.md) |
| Write or load generator, transform and validator plugins | [Extensions](extensions.md) |
| Partition work and merge process output | [Parallel generation](concurrency.md) |
| Check generated values and write audit reports | [Proof checking](proofs.md) |
| Monitor progress and consume structured events | [Logging and progress](observability.md) |
| Understand compilation, ownership and runtime boundaries | [Architecture](architecture.md) |
| Set up a checkout and run quality checks | [Development](development.md) |
| Run saved benchmarks and read the measured results | [Benchmarks](benchmarks.md) |

## Example configs

- [CPU telemetry](../examples/hwmetrics.json): timestamps, CPU families and usage.
- [SNP records](../examples/dna.json): record ids, chromosomes, positions and genotypes.
- [Synthetic NT hashes](../examples/winhash.json): paired plaintext and digest fixtures.
  See the [hash fixture guidance](generators/hashes.md#hash-paired).
