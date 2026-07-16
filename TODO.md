# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-13 (all categories).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-010 | open | S | Define one shared maximum total-expansion budget and overflow-safe product helper for composite generator preparation, aligned with `regex.MAX_TOTAL_EXPANSION`. |
| SEC-013 | open | S | Apply the total-expansion budget to nested `sequence_of` specs; reject products above the cap during validation/prepare. |
| SEC-014 | open | S | Propagate and enforce the total-expansion budget through nested `oneOf` and `weighted` branches. |
| SEC-015 | open | S | Add boundary and adversarial nesting tests proving composite expansion is accepted at the cap and rejected above it without materializing output. |
| SEC-011 | open | S | `generators/hash.py:48` bcrypt-hashes every entry of an unbounded `values` list at prepare time (up to 2^12 rounds each). `--validate` runs `prepare`, so a "validate only, no rows" invocation performs unbounded KDF work (1000 words ~= minutes of CPU). Cap `values` length for bcrypt or hash lazily. |
| SEC-012 | open | S | `cli.py:496` `_target_mode` flips the process-wide umask to 0 and restores it to read it. In an embedding/threaded process any file created in that window lands at 0666/0777. Derive the mode without mutating global umask. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|
| CX-010 | open | S | Introduce an immutable compiled-plan value object for prepared fields, template segments, pairing metadata, and resolved catalogs currently assembled in `Engine.__init__`. |
| CX-012 | open | S | Extract template parsing, registry resolution, validation, and field preparation from `Engine.__init__` into a compiler that returns the compiled plan. |
| CX-013 | open | S | Reduce `Engine.__init__` to runtime-state initialization from the compiled plan and add focused compiler/constructor tests. |
| CX-011 | open | S | Near the CC<=10 limit (all at 9, none over): `generators/regex.py:98` `_reject_oversized_repeats`, `_logging.py:70` `configure_stderr`, `_config.py:158` `_validate_type_spec`. Watch on next change. |

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|
| DUP-010 | open | S | Extract a pure paired-transform capability fold that checks `accepts_paired` and computes whether pairing is preserved. |
| DUP-016 | open | S | Route `_config._validate_transforms` and `_engine._prepare_transforms` through the shared capability fold while preserving their public error types/messages. |
| DUP-017 | open | S | Add parity tests proving config validation and engine preparation accept/reject the same paired-transform chains. |
| DUP-011 | open | S | Composite dispatch `if generator.is_composite: prepare_composite(...) else prepare(...)` copy-pasted at `_engine.py:334` and `_config.py:237`. |
| DUP-012 | open | S | `"core."` prefix stripping duplicated at `_engine.py:597` `_runtime_type_name` and `generators/base.py:315` `prepare_child_spec`; the registry owns that convention. |
| DUP-013 | open | S | `generators/base.py:225` `coerce_int` and `:259` `coerce_float` repeat the same 8-line `_MISSING`/default resolution preamble. |
| DUP-014 | open | S | Identical config-error mapping try/except (FileNotFoundError->1, ConfigError/TemplateError/JSONDecodeError->2) in `cli.py:240` `_validate_config` and `cli.py:258` `_prepare_engine`. |
| DUP-015 | open | S | Proof-mode value list `off/sample/all/audit` hard-coded in `cli.py:109` (argparse choices) and `_proofcheck.py:227` (`validate_proof_mode`). |

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-020 | open | S | Extend the compiled field/token plan with flags and resolved references needed to identify the no-transform, no-validator, proof-off path once at prepare time. |
| PERF-028 | open | S | Add a direct single-value generation fast path that skips `TransformResult`, trace tuples, type lookup, and `ProofChecker.evaluate` when the compiled plan marks them unused. |
| PERF-029 | open | S | Add behavior parity tests and a benchmark guard for the default proof-off fast path, including paired and exception-wrapping branches. |
| PERF-021 | open | S | Resolve regex `IN` nodes to immutable concrete character pools during prepare so generation performs no tuple-key construction or nested hashing. |
| PERF-030 | open | S | Resolve regex `NOT_LITERAL` exclusions/pools during prepare so generation performs no per-character `frozenset` allocation. |
| PERF-031 | open | S | Add regex equivalence tests and focused benchmarks for prepared `IN` and `NOT_LITERAL` pools. |
| PERF-022 | open | S | Per-character `rng.choice` in a genexp: `generators/char.py:37` and `generators/text.py:129`. `rng.choices(values, k=n)` is ~4x faster (`maxChar=64`: 10.2 -> 2.5 us/row). Caveat: changes the seeded RNG stream, so existing seeds stop reproducing byte-for-byte. |
| PERF-023 | open | S | `transforms/distribution.py:34` `WeightedChoiceSet.choose` and `generators/weighted.py:112` call `rng.choices(range(n), cum_weights=..., k=1)[0]` per row -- allocates a `range` + result list and re-derives the total each draw. A direct `bisect(cum_weights, rng.random() * cum_weights[-1])` is ~4x faster (0.35 -> 0.08 us/op). |
| PERF-024 | open | S | `generators/network.py:59` `_draw_ip` constructs an `ipaddress.IPv4Address`/`IPv6Address` object per row solely to `str()` it (0.88 us/op vs ~0.5 us formatting the octets from the int). |
| PERF-025 | open | S | `generators/identity.py:117` `PhoneGenerator.generate` walks the whole format string char-by-char and calls `rng.randint(0, 9)` per `#` on every row (3.05 us/row). Precompute the literal segments + digit count at prepare time and fill with one `rng.choices(_DIGITS, k=n)`. |
| PERF-026 | open | S | `_proofcheck.py:195` `_make_failure` copies the entire field spec (`dict(spec)`) for every failure *before* `:111` `_record_audit` applies `MAX_AUDIT_SAMPLE`. In audit mode with a systematically failing field, every row pays a dict copy that is immediately discarded. Build the record lazily (or drop `spec` once the cap is hit). |
| PERF-027 | open | S | `cli.py:520` `_stream` issues two `stream.write()` calls per row and only *flushes* every `--batch-rows`; the flag's help text (`cli.py:78`) claims it "buffers N rendered rows per write() syscall". Behavior and documentation disagree. Actual batching (`"\n".join(batch)`) saves only ~0.06 us/row next to ~2.5 us/row of generation, so the docs mismatch is the larger defect. |

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
| SCAL-012 | open | S | `cli.py:522` `--resume-from` generates and discards every skipped row, so sharding an N-row job into k offset shards costs O(k*N) total generation. README:84 admits the cost, but README:83 still presents offset-sharding as a parallel recipe; point users at `fork_engine` (O(N) total) instead. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|
| CONC-012 | open | S | `fork_engine` does not offset stateful generators: every worker's `sequence` counter restarts at `start`, so the documented recipe emits duplicate ids across workers. The caveat exists in `generators/sequence.py:13-17`, but not in the `concurrency.py:13-33` recipe users actually copy. Offset `start` by `worker_id * rows` in `fork_engine` (or refuse to fork a config containing a `sequence` without an explicit offset). |

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-010 | open | S | `cli.py:479` `os.replace(tmp_name, path)` destroys a symlinked `--output`: `os.stat` follows the link so the `S_ISREG` gate passes, then the rename replaces the *link* with a regular file and the real target is never written. Verified: `ln -s real.txt link.txt; ton c.json -o link.txt` -> `link.txt` is now a regular file, `real.txt` still holds its old content (plain `open(path,"w")` would have written through). Resolve the target with `os.path.realpath` before choosing the temp dir / rename target, or refuse symlinks explicitly. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|
| ARCH-011 | open | S | Define a compiler boundary and compiled-plan API that contains validation, field preparation, transform resolution, validator resolution, and pairing analysis. |
| ARCH-014 | open | S | Move compile-time methods from `Engine` into the compiler without changing configuration errors or extension resolution. |
| ARCH-015 | open | S | Make runtime `Engine` consume only the compiled plan for iteration, rendering, value resolution, and proof evaluation; add boundary tests. |
| ARCH-012 | open | S | Extract output target validation and special-file/symlink policy from `cli.py` into a reusable output-sink module. |
| ARCH-016 | open | S | Move atomic temporary-file replacement, cleanup, and interrupted-write behavior into the output sink. |
| ARCH-017 | open | S | Move permission/umask preservation into the output sink and expose the sink through the supported library API. |
| ARCH-018 | open | S | Add CLI/API parity tests for successful writes, special files, replacement failure, cleanup, and preserved permissions. |
| ARCH-013 | open | S | Introduce a preparation context carrying registry/composite resolution and make `Generator.prepare(spec, context)` uniformly callable. |
| ARCH-019 | open | S | Migrate built-in atomic and composite generators to the uniform preparation interface, removing `is_composite` dispatch branches. |
| ARCH-020 | open | S | Update the public generator extension contract and tests so third-party composites implement the same preparation interface. |

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DEC-017 | open | S | Implement nested-type discovery for each built-in composite generator and use it during lazy registry construction. |
| DEC-018 | open | S | Remove `_engine._walk_value_for_types` and add tests proving transform mappings are ignored while plugin composite children are discovered. |

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|
| PAT-020 | open | S | Parameter Object is half-applied: `EngineOptions` exists but five call sites still re-enumerate the option list (see ARCH-010). Route `api.generate`, `api.generate_from_file`, `Engine.from_file`, `cli._build_engine`, `concurrency.fork_engine` through it. |

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|
| PLUG-010 | open | S | Reserved `core` namespace is not reserved. `_registry.py:147` only blocks *replacing* an existing core name, so an entry point named `core.foo` (or `catalog.register_data_type("core", "foo", ...)`) lands in the core namespace and `_flatten:134` promotes it to the bare alias `foo`. Verified. Contradicts `docs/architecture.md:12-31` ("plugins register additional namespaced types", built-ins isolated in `core`). Reject `core` for non-built-in registration. |
| PLUG-011 | open | S | Validator plugins are unreachable from two of the three public builders: `concurrency.fork_engine` and `Engine.from_file` take no `validators` argument, so a config with a `validators` list raises `TemplateError: Unknown validator` in every forked worker (verified). Same root cause as ARCH-010. |
| PLUG-012 | open | S | Generator-instance lifetime is undocumented and inconsistent. `_registry.default_registry` promises "fresh instances so per-spec state stays Engine-scoped", but `ExtensionCatalog` builds its generator dict once and hands the *same* plugin instances to every Engine built from that catalog (README's catalog example reuses one catalog). Third-party generators that keep state on `self` silently share it across engines; `generators/base.py` never states the required statelessness. |
| PLUG-013 | open | S | The `ton.validators` extension point ships with zero reference implementation: `catalog.list_validators()` is `()` and `--list-namespaces` prints an empty `validators:` line. No built-in validator, no example plugin, no doc'd way to try the feature without authoring a distribution. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-010 | open | S | `--redact-proof-failures` is a no-op for CLI users. It only masks the retained `Engine.proof_failures` records, which the CLI never emits (`cli.py:315` `_report_proof_audit` prints a count), and the `proof_check_failed` log event (`_proofcheck.py:208`) already carries no `value`/`spec`. The flag changes no CLI-visible output. |
| CLI-011 | open | S | `--batch-rows` help ("Buffer N rendered rows per write() syscall", `cli.py:78`) and the README flag table misdescribe the behavior: `_stream` (`cli.py:520`) writes every row immediately and only calls `stream.flush()` every N rows. It is a flush interval, not a write batch. |
| CLI-012 | open | S | `--progress N` silently doubles as `milestone_rows=N` (`cli.py:377`), so any handler attached to the `ton` logger receives both `engine_progress` and `engine_milestone` at the same cadence. Undocumented coupling between an output flag and an engine option. |
| CLI-013 | open | S | `--progress` counts *generated* rows while `--verbose` counts *written* rows (`cli.py:520-535`); with `--resume-from N` the progress JSON reports rows that were never written and the two summaries disagree. |
| CLI-014 | open | S | Define whether configured output-encoding failures are configuration errors (exit 2) or output errors (exit 1), and add a pointed domain error carrying encoding/field context. |
| CLI-015 | open | S | Translate `UnicodeEncodeError` from stdout and file streaming into the chosen domain error and documented CLI exit code without the unexpected-error banner. |
| CLI-016 | open | S | Add CLI tests for non-encodable literals/generated values on stdout and atomic file output, including partial-file cleanup. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-010 | open | S | Define the unknown-key policy and canonical allowed root/field keys, including extension-owned namespaces and error-message suggestions for typos. |
| CFG-015 | open | S | Reject unknown root and common field keys during configuration validation with path-aware errors. |
| CFG-016 | open | S | Add a declarative allowed-key contract for generators/transforms/validators and enforce it for built-ins without blocking plugin-specific keys. |
| CFG-017 | open | S | Add typo, nested-spec, and plugin-extension tests; document unknown-key validation and migration expectations. |
| CFG-011 | open | S | `generators/boolean.py:26` reads `spec["whenTrue"]` / `spec["whenFalse"]` directly, so a missing key surfaces as `Invalid spec for 'x': KeyError: 'whenTrue'` instead of the uniform "<type> 'key' is required" message every other generator produces via `base.coerce_*` / `require_*`. |
| CFG-012 | open | S | Validation limits that reject configs are undocumented: `_config.MAX_ROWS` (1e9), `regex.MAX_TOTAL_EXPANSION` (`generators/regex.py:51`), `_regex_parse.MAX_GROUP_NESTING` (`:97`), `sequence.MAX_SEQUENCE_PAD_WIDTH`. README:785 mentions only `MAX_UNBOUNDED_REPEAT` / `MAX_LITERAL_REPEAT`. |
| CFG-013 | open | S | `_config.MAX_ROW_WIDTH_GUIDANCE:46` is dead: defined and documented as the worst-case row-width ceiling, referenced by nothing, enforced nowhere. Either enforce it or drop it. |
| CFG-014 | open | S | Two of the three shipped example configs are never executed by the suite: only `examples/dna.json` is run (`tests/test_coverage_fillers.py:38`); `examples/hwmetrics.json` and `examples/winhash.json` can rot unnoticed while README advertises all three. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|
| DEP-010 | open | S | `pyright` is invoked by `.githooks/pre-commit:38` and by the CI typecheck job (`.github/workflows/ci.yml:49`) but is not declared in the `dev` extra (`pyproject.toml:33`). After `pip install -e ".[dev]"` the hook aborts every commit with "pyright not found on PATH". Add it to `dev`. |

## platform

| id | status | effort | description |
|----|--------|--------|-------------|
| PLAT-010 | open | S | `cli.py:428` and `cli.py:463` open output in text mode with default newline translation, so on Windows every row terminator becomes CRLF while POSIX writes LF. Byte-level output (and any checksum over it) is not reproducible across the OS matrix CI declares. Pass `newline="\n"`. |
| PLAT-011 | open | S | `concurrency.py:15-30` docstring's `multiprocessing.Pool` example lacks an `if __name__ == "__main__":` guard; under the spawn start method (Windows always, macOS default) copying it re-imports the module and raises RuntimeError. Guard the example. |

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
| DOC-021 | open | S | `README.md:435` says a field's `validators` entries are "a built-in or namespaced validator name" — TON ships **no** built-in validators (`catalog.list_validators()` is empty), so only plugin-provided names can ever resolve. |
| DOC-022 | open | S | Document public helper functions `validate_config`, `output_encoding`, and `normalize_reference` with signatures, behavior, and errors. |
| DOC-025 | open | S | Document public extension/error/value types `RegistryError`, `Transform`, `Validator`, and `ProvenanceRecord`, plus `Engine.provenance`. |
| DOC-026 | open | S | Complete `generate` / `generate_from_file` documentation for `validators=`, `proof_mode`, `proof_sample_rate`, and `redact_proof_failures`, with a minimal example. |
| DOC-027 | open | S | Add a documentation/API-surface test or checklist that compares `api.__all__` with the supported-surface and README references. |
| DOC-023 | open | S | README type-reference tables omit shipped defaults and caps: `bytes.length` defaults to 16 (table implies required), `text.count` defaults to 5, `sequence.padWidth` is capped by `MAX_SEQUENCE_PAD_WIDTH`, `hash.rounds` is absent from the field table. |
| DOC-024 | open | S | `README.md:59` `--batch-rows` ("Rows buffered per `write()` syscall") describes an implementation that does not exist — see CLI-011; the value is a flush interval. |
