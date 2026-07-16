# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-16 (all categories; cache files/directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-010 | open | S | Define one shared maximum total-expansion budget and overflow-safe product helper for composite generator preparation, aligned with `regex.MAX_TOTAL_EXPANSION`. |
| SEC-013 | open | S | Apply the total-expansion budget to nested `sequence_of` specs; reject products above the cap during validation/prepare. |
| SEC-014 | open | S | Propagate and enforce the total-expansion budget through nested `oneOf` and `weighted` branches. |
| SEC-015 | open | S | Add boundary and adversarial nesting tests proving composite expansion is accepted at the cap and rejected above it without materializing output. |
| SEC-011 | open | S | `generators/hash.py:48` bcrypt-hashes every entry of an unbounded `values` list at prepare time (up to 2^12 rounds each). `--validate` runs `prepare`, so a "validate only, no rows" invocation performs unbounded KDF work (1000 words ~= minutes of CPU). Cap `values` length for bcrypt or hash lazily. |
| SEC-012 | open | S | `_output.py:85` `target_mode` flips the process-wide umask to 0 and restores it to read it. In an embedding/threaded process any file created in that window lands at 0666/0777. Derive the mode without mutating global umask. |
| SEC-016 | open | S | `DecimalGenerator.prepare` computes `10 ** decimals` with no upper bound. A local or uploaded config such as `{"decimals": 1000000000}` can consume unbounded CPU/memory during normal construction or `--validate`; define and enforce a decimal precision cap before exponentiation. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|
| DUP-010 | open | S | Composite-child validation/preparation is implemented twice in `generators/base.py:prepare_child_spec` and `_distribution.py:_prepare_child`, including type lookup, paired rejection, and composite dispatch. Consolidate on the `PreparationContext` path so `oneOf`/`sequence_of` and weighted/distribution cannot drift. |
| DUP-011 | open | M | `_config.validate_with_catalog` and `_compiler.EngineCompiler` independently resolve types/transforms/validators and prepare generator specs. The duplicate pipelines already differ in exception mapping and catalog access; extract one canonical compilation/validation service used by `--validate` and Engine construction. |

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-025 | open | S | CI runs `ruff format --check` with `continue-on-error: true`, while the repository pre-commit hook treats the same check as mandatory. Formatting failures can merge despite the documented local/CI parity; make the CI step blocking or document the intentional difference. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-032 | open | S | `ExtensionCatalog.generators()` deep-copies every generator prototype on every call, and catalog validation calls it repeatedly per field (`_validate_type_reference`, `_validate_transforms`, list operations). Cache name-only views and create one Engine-scoped registry snapshot per validation/build. |
| PERF-033 | open | S | `CompiledPlan` retains unused `template`, `registry`, `transforms`, `validators`, and `plan_tokens` fields after compilation. Remove dead runtime state so each Engine does not keep redundant mappings/plugin objects alive. |
| PERF-034 | open | S | Proof audit detail suppression is only decided before building all failures for a field. When source plus transform failures cross `MAX_AUDIT_SAMPLE`, specs for over-cap failures are still copied; pass a remaining-detail budget or build records lazily per failure. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCAL-010 | open | S | Replace the `concurrency.py` worker contract that returns `list(eng)` with a bounded-memory shard-to-file or chunk-streaming primitive. |
| SCAL-013 | open | S | Add multiprocess tests proving the replacement preserves exact row counts/order expectations and does not accumulate an entire worker shard in memory. |
| SCAL-014 | open | S | Rewrite the documented multiprocessing recipe to use the bounded-memory primitive and explain output merge/cleanup behavior. |
| SCAL-011 | open | S | Define row-width limit semantics for literals plus all placeholders, including whether the existing 2 MB guidance becomes a hard default or configurable cap. |
| SCAL-015 | open | S | Compute a conservative prepared worst-case width for fixed/bounded generators and reject templates whose aggregate width exceeds the configured limit. |
| SCAL-016 | open | S | Enforce a runtime row-width guard for generators whose maximum cannot be known during prepare, before unbounded content is retained or written. |
| SCAL-017 | open | S | Add aggregate-placeholder, composite, boundary, and unknown-width tests; document the row-width limit and error. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DEC-010 | open | S | `ton.api` claims to be the only supported public facade, but README examples require `from ton import concurrency` and `ton.concurrency` exposes public helpers independently. Decide whether concurrency is supported, then re-export/document it through the facade or narrow the facade claim. |

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|
| PLUG-010 | open | S | Reserved `core` namespace is not reserved. `_registry.py:147` only blocks *replacing* an existing core name, so an entry point named `core.foo` (or `catalog.register_data_type("core", "foo", ...)`) lands in the core namespace and `_flatten:134` promotes it to the bare alias `foo`. Verified. Contradicts `docs/architecture.md:12-31` ("plugins register additional namespaced types", built-ins isolated in `core`). Reject `core` for non-built-in registration. |
| PLUG-014 | open | M | Catalog generator prototypes are deep-copied per registry, but transforms and validators are returned as shared instances and their lifecycle/statelessness contract is undocumented. Define one extension-instance policy and test two Engines built from a reused catalog with stateful transform/validator fixtures. |
| PLUG-015 | open | S | Validator entry points receive no runtime contract check: any object is registered, listed, and accepted by config validation, then fails at row generation with a missing `validate`/`type_name` attribute. Validate the `Validator` protocol during direct and entry-point registration, matching generator/transform handling. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-015 | open | S | Translate `UnicodeEncodeError` from stdout and file streaming into the chosen domain error and documented CLI exit code without the unexpected-error banner. |
| CLI-016 | open | S | Add CLI tests for non-encodable literals/generated values on stdout and atomic file output, including partial-file cleanup. |
| CLI-017 | open | S | A transform spec with a non-string `type` reaches `normalize_reference`, raises `AttributeError`, and makes `ton config.json --validate` exit 3 with an unexpected-error banner. Map malformed transform references to the normal invalid-config exit 2 path. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-017 | open | S | Add typo, nested-spec, and plugin-extension tests; document unknown-key validation and migration expectations. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-010 | open | M | Structured `prepare_failed`, `generate_failed`, `entry_point_failed`, and CLI unexpected-error diagnostics interpolate arbitrary exception text. Plugin/config exceptions can therefore place source values or secrets into logs; define safe diagnostic fields and sanitize/redact exception messages at trust boundaries. |
| DG-011 | open | S | The tracked-file governance test detects only a small marker set and Unix `/home`/`/backups` paths. Add representative cloud/token formats and Windows user paths without embedding live-secret-shaped literals directly in the repository. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|
| DEP-010 | open | S | `pyright` is invoked by `.githooks/pre-commit:38` and by the CI typecheck job (`.github/workflows/ci.yml:49`) but is not declared in the `dev` extra (`pyproject.toml:33`). After `pip install -e ".[dev]"` the hook aborts every commit with "pyright not found on PATH". Add it to `dev`. |

## platform

| id | status | effort | description |
|----|--------|--------|-------------|
| PLAT-012 | open | S | Date format validation rejects platform-specific flags but accepts unsupported/platform-dependent directives such as `%s`; `strftime` may expand them on Unix and reject or render them literally on Windows. Define and validate a portable directive allowlist across the declared OS matrix. |

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-020 | open | S | Define a bounded proof-audit report schema and CLI destination/format, including redaction semantics and behavior when the sample cap is reached. |
| OBS-024 | open | S | Emit retained `Engine.proof_failures` through the proof-audit report path and make `--redact-proof-failures` affect that visible output. |
| OBS-025 | open | S | Add CLI tests for clear/redacted reports, sampling caps, paired values, and report-write failures; update proof-audit help/docs. |
| OBS-021 | open | S | Define one terminal structured failure event schema with error category, exit code, progress counts, and safe diagnostic fields. |
| OBS-026 | open | S | Emit the terminal failure event from each handled `_execute` failure path exactly once while preserving existing stderr and exit behavior. |
| OBS-027 | open | S | Add structured-log tests distinguishing completed, validation-failed, proof-failed, output-failed, and unexpected-crash runs. |
| OBS-022 | open | S | `_install_progress_handler` (`cli.py:588`) forces the shared `ton` logger to level INFO whenever `--progress` is passed, overriding a stricter `--log-level error/critical` set in the same invocation and leaking the level change to any handler a library caller attached to `ton`. |
| OBS-023 | open | S | `cli.py:593` `_report` prints `inf rows/s` when elapsed rounds to 0 (`ton: wrote 0 rows in 0.000s (inf rows/s)`); the progress event guards the same division with `None` (`cli.py:546`) — two behaviors for one calculation. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-010 | open | S | `README.md:78-80` documents chunked generation as three `--resume-from 0/500000/1000000` runs, but the CLI has no row-limit option: each run generates *all* `rows` and only skips a prefix, so chunk-0 contains the whole dataset and the chunks overlap. Either document `fork_engine` for chunking or add a `--max-rows`/`--limit` flag. |
| DOC-020 | open | S | `README.md:256` ("Output to stdout uses the stream's own encoding") is false: `cli._open_output:398` routes stdout through `_reconfigured_stdout(encoding)`, applying the config's `encoding` to stdout as well. Verified: `{"encoding": "ascii"}` with a non-ASCII `format` crashes on stdout. |
| DOC-022 | open | S | Document public helper functions `validate_config`, `output_encoding`, and `normalize_reference` with signatures, behavior, and errors. |
| DOC-025 | open | S | Document public extension/error/value types `RegistryError`, `Transform`, `Validator`, and `ProvenanceRecord`, plus `Engine.provenance`. |
| DOC-026 | open | S | Complete `generate` / `generate_from_file` documentation for `validators=`, `proof_mode`, `proof_sample_rate`, and `redact_proof_failures`, with a minimal example. |
| DOC-027 | open | S | Add a documentation/API-surface test or checklist that compares `api.__all__` with the supported-surface and README references. |
| DOC-023 | open | S | README type-reference tables omit shipped defaults/caps: `bytes.length` defaults to 16 (table implies required), `text.count` defaults to 5, and `hash.rounds` is absent from the field table. |
| DOC-028 | open | S | README's UUID section says UUID1 uses the host clock/node and ignores the seed, but `UUIDGenerator` constructs both v1 and v4 from seeded random bytes specifically to avoid host-data leakage. Correct the behavior and reproducibility text. |
| DOC-029 | open | S | The public API overview and exception list omit the exported `OutputEncodingError`, including when callers should catch it and its `encoding` / `field_name` context attributes. |
