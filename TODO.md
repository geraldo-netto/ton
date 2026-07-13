# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-13 (all categories).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-010 | open | M | Composite generators have no total-expansion budget. `generators/sequence_of.py:40` caps `count` per level (10_000) but nesting multiplies: `sequence_of{10_000} > sequence_of{10_000} > char{maxChar:100_000}` passes `--validate` and materializes ~1e13 chars/row (verified: 200x200x200 -> 8 MB row in 1.5s). `regex` already guards this with MAX_TOTAL_EXPANSION; `sequence_of`/`oneOf`/`weighted` need the same product cap. |
| SEC-011 | open | S | `generators/hash.py:48` bcrypt-hashes every entry of an unbounded `values` list at prepare time (up to 2^12 rounds each). `--validate` runs `prepare`, so a "validate only, no rows" invocation performs unbounded KDF work (1000 words ~= minutes of CPU). Cap `values` length for bcrypt or hash lazily. |
| SEC-012 | open | S | `cli.py:496` `_target_mode` flips the process-wide umask to 0 and restores it to read it. In an embedding/threaded process any file created in that window lands at 0666/0777. Derive the mode without mutating global umask. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|
| CX-010 | open | M | `_engine.py:95` `Engine.__init__` is a 59-line constructor doing 12 jobs (template parse, registry resolve, transform/validator catalogs, RNG, ProofChecker, validate, prepare, paired scan, segment split, milestone, logging). CC low but SRP-heavy; split compile-time setup into a plan object. |
| CX-011 | open | S | Near the CC<=10 limit (all at 9, none over): `generators/regex.py:98` `_reject_oversized_repeats`, `_logging.py:70` `configure_stderr`, `_config.py:158` `_validate_type_spec`. Watch on next change. |

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|
| DUP-010 | open | M | Paired-transform capability rule implemented twice: `_config.py:191` `_validate_transforms` and `_engine.py:366` `_prepare_transforms` both walk transforms, check `accepts_paired`, and fold `preserves_pairing`. Two error types, one rule -- will drift. |
| DUP-011 | open | S | Composite dispatch `if generator.is_composite: prepare_composite(...) else prepare(...)` copy-pasted at `_engine.py:334` and `_config.py:237`. |
| DUP-012 | open | S | `"core."` prefix stripping duplicated at `_engine.py:597` `_runtime_type_name` and `generators/base.py:315` `prepare_child_spec`; the registry owns that convention. |
| DUP-013 | open | S | `generators/base.py:225` `coerce_int` and `:259` `coerce_float` repeat the same 8-line `_MISSING`/default resolution preamble. |
| DUP-014 | open | S | Identical config-error mapping try/except (FileNotFoundError->1, ConfigError/TemplateError/JSONDecodeError->2) in `cli.py:240` `_validate_config` and `cli.py:258` `_prepare_engine`. |
| DUP-015 | open | S | Proof-mode value list `off/sample/all/audit` hard-coded in `cli.py:109` (argparse choices) and `_proofcheck.py:227` (`validate_proof_mode`). |

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-020 | open | S | `generators/decimal.py:38-39` derives the step range with `math.ceil(min*scale)` / `math.floor(max*scale)` on binary floats, so representation error shifts the bounds. Verified: `{"minValue":0.07,"maxValue":0.07,"decimals":2}` -> `0.07*100 == 7.000000000000001` -> `min_step=8 > max_step=7` -> prepare raises "decimal range contains no value representable with 2 decimal place(s)" for a valid config; `{"minValue":0.07,"maxValue":0.29,"decimals":2}` yields `min_step=8, max_step=28`, so 0.07 and 0.29 are never emitted. 134/2000 two-decimal values are affected. Compute steps from the decimal string / integer math instead of float multiply. |
| REL-021 | open | S | `generators/decimal.py:64-66` draws `rng.uniform(min,max)` then rounds to the step grid, so the two boundary steps get half the probability of interior ones. Verified: `{"minValue":0,"maxValue":0.2,"decimals":1}` over 60k draws -> 0.0 25%, 0.1 50%, 0.2 25% (uniform would be 33/33/33). `round()` also uses banker's rounding, biasing exact .5 ties. Draw `rng.randint(min_step, max_step)` instead. |
| REL-022 | open | M | `_engine.py:420` `__iter__` resets `_rows_emitted` and the ProofChecker but not the RNG or generator-owned state, so a second iteration of the same Engine is not reproducible even with `seed=`. Verified: `e = Engine.from_config(cfg, seed=42)` with an `integer` + `sequence` field -> pass 1 `['2 1','1 2','5 3']`, pass 2 `['4 4','4 5','3 6']`. Either re-seed + re-prepare stateful specs on each `__iter__`, or document the Engine as single-shot and refuse a second iteration. |
| REL-023 | open | S | `_engine.py:114` `dict(transforms or build_extension_catalog().transforms())` tests truthiness, so an explicitly empty mapping is silently replaced by the full built-in catalog (the sibling `validators` line correctly uses `is not None`). Verified: `Engine.from_config(cfg, transforms={})` on a config whose field declares `{"type":"identity"}` renders rows instead of raising `TemplateError: Unknown transform`. Use `transforms if transforms is not None else ...`. |
| REL-024 | open | S | `generators/_regex_parse.py:236` `_parse_class_member` accepts a reversed range: `[z-a]` builds `RANGE(122,97)` and `regex.py:235` `_flatten_range` expands `range(122,98)` to `[]`. Alone it is caught as an empty class, but `[z-a0]` silently prepares with a one-character pool, so `{"pattern":"[z-a0]{4}"}` always emits "0000" where `re` would reject the pattern. Raise `RegexParseError("bad character range")` when `hi < lo`. |
| REL-025 | open | S | `_engine.py:497` wraps a row-time generator crash in `TemplateError`, but `cli.py:290` `_execute` only catches `OSError` / `ProofError` / `ValidationError`, so it falls through to the `_run` catch-all: a plugin generator raising on row 500 exits 3 with "ton: unexpected error: TemplateError: ..." instead of the documented config-error exit 2. Catch `TemplateError` in `_execute`. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-020 | open | M | Hot path pays the proof/transform machinery even when unused. `_engine.py:510` `_generate_single` allocates a `TransformResult` per field per row, `:546` `_apply_transforms_with_trace` builds a steps tuple, and `:525` `_handle_proof_failures` does a `self._types[...]` lookup + `ProofChecker.evaluate` call on every field of every row -- all no-ops when the field has no transforms/validators and `proof_mode="off"` (the default). Measured on a 2-field integer+string config: 2.55 us/row baseline vs 1.02 us/row with a fast path that still keeps the try/except and the paired branch (2.5x). Precompute a per-token plan and branch once. |
| PERF-021 | open | M | `generators/regex.py:209` `_pick_in` rebuilds the `lru_cache` key on every emitted character: `tuple(items)` allocation plus a nested-tuple hash. Measured 0.30 us of the 0.59 us spent per character; `[A-Za-z0-9]{20}` costs 11.7 us/row vs 3.9 us with a pre-resolved pool (~3x). `:169` `_emit_not_literal` likewise allocates a `frozenset` per character. Resolve `IN` / `NOT_LITERAL` nodes to concrete pools once in `prepare`. |
| PERF-022 | open | S | Per-character `rng.choice` in a genexp: `generators/char.py:37` and `generators/text.py:129`. `rng.choices(values, k=n)` is ~4x faster (`maxChar=64`: 10.2 -> 2.5 us/row). Caveat: changes the seeded RNG stream, so existing seeds stop reproducing byte-for-byte. |
| PERF-023 | open | S | `transforms/distribution.py:34` `WeightedChoiceSet.choose` and `generators/weighted.py:112` call `rng.choices(range(n), cum_weights=..., k=1)[0]` per row -- allocates a `range` + result list and re-derives the total each draw. A direct `bisect(cum_weights, rng.random() * cum_weights[-1])` is ~4x faster (0.35 -> 0.08 us/op). |
| PERF-024 | open | S | `generators/network.py:59` `_draw_ip` constructs an `ipaddress.IPv4Address`/`IPv6Address` object per row solely to `str()` it (0.88 us/op vs ~0.5 us formatting the octets from the int). |
| PERF-025 | open | S | `generators/identity.py:117` `PhoneGenerator.generate` walks the whole format string char-by-char and calls `rng.randint(0, 9)` per `#` on every row (3.05 us/row). Precompute the literal segments + digit count at prepare time and fill with one `rng.choices(_DIGITS, k=n)`. |
| PERF-026 | open | S | `_proofcheck.py:195` `_make_failure` copies the entire field spec (`dict(spec)`) for every failure *before* `:111` `_record_audit` applies `MAX_AUDIT_SAMPLE`. In audit mode with a systematically failing field, every row pays a dict copy that is immediately discarded. Build the record lazily (or drop `spec` once the cap is hit). |
| PERF-027 | open | S | `cli.py:520` `_stream` issues two `stream.write()` calls per row and only *flushes* every `--batch-rows`; the flag's help text (`cli.py:78`) claims it "buffers N rendered rows per write() syscall". Behavior and documentation disagree. Actual batching (`"\n".join(batch)`) saves only ~0.06 us/row next to ~2.5 us/row of generation, so the docs mismatch is the larger defect. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCAL-010 | open | M | The only documented multiprocess recipe defeats the engine's streaming design: `concurrency.py:21-30` has each worker `return list(eng)`, materializing `rows // workers` rendered rows in the worker and pickling all of them back through the pool pipe. At `rows=1e9` / 8 workers that is ~125M rows (multi-GB) per worker. The Engine itself streams correctly (`_engine.py:420` yields row by row, O(1) memory) -- ship a streaming/shard-to-file recipe or a chunked helper instead. |
| SCAL-011 | open | M | Per-row width is effectively unbounded: `_config.py:46` `MAX_ROW_WIDTH_GUIDANCE` (2 MB) is documentation only -- nothing enforces it, and it describes *one* placeholder. A template with k placeholders of `{"type":"bytes","length":1000000,"encoding":"hex"}` builds k x 2 MB of strings inside `_engine.py:453` `_render_row`. Related to SEC-010 (composite multiplication). |
| SCAL-012 | open | S | `cli.py:522` `--resume-from` generates and discards every skipped row, so sharding an N-row job into k offset shards costs O(k*N) total generation. README:84 admits the cost, but README:83 still presents offset-sharding as a parallel recipe; point users at `fork_engine` (O(N) total) instead. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|
| CONC-010 | open | M | `Engine` cannot cross a process boundary. `_engine.py:140` stores a `threading.Lock` (verified: `TypeError: cannot pickle '_thread.lock' object`), and `generators/bytes.py:24-28` stores bare `lambda`s in `BytesSpec.encode` so even a prepared spec fails to pickle (`PicklingError`). Under the spawn/forkserver start methods (Windows/macOS default; forkserver is the 3.14 Linux default) no engine or prepared spec can be sent to or returned from a worker. Add `__getstate__`/`__setstate__` that drop and rebuild the lock, and replace the encoder lambdas with module-level functions. |
| CONC-011 | open | S | `concurrency.py:19` docstring recipe computes `rows_per_worker = config["rows"] // workers`, silently dropping `rows % workers` rows (`rows=10`, `workers=4` -> 8 rows generated). Give the remainder to the last worker, or ship a `chunk_rows()` helper so the split is not hand-rolled at every call site. |
| CONC-012 | open | S | `fork_engine` does not offset stateful generators: every worker's `sequence` counter restarts at `start`, so the documented recipe emits duplicate ids across workers. The caveat exists in `generators/sequence.py:13-17`, but not in the `concurrency.py:13-33` recipe users actually copy. Offset `start` by `worker_id * rows` in `fork_engine` (or refuse to fork a config containing a `sequence` without an explicit offset). |
| CONC-013 | open | S | `_engine.py:420` `__iter__` is a generator function, so the `_iteration_lock` guard is not taken until the first `next()`. Two threads can both obtain an iterator from `iter(engine)` / `api.generate(...)` and the "cannot be iterated concurrently" `RuntimeError` surfaces only when the second one advances, far from the offending call. Acquire the lock in a non-generator `__iter__` that returns an inner generator. |

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-010 | open | S | `cli.py:479` `os.replace(tmp_name, path)` destroys a symlinked `--output`: `os.stat` follows the link so the `S_ISREG` gate passes, then the rename replaces the *link* with a regular file and the real target is never written. Verified: `ln -s real.txt link.txt; ton c.json -o link.txt` -> `link.txt` is now a regular file, `real.txt` still holds its old content (plain `open(path,"w")` would have written through). Resolve the target with `os.path.realpath` before choosing the temp dir / rename target, or refuse symlinks explicitly. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|
| ARCH-010 | open | S | `EngineOptions` (DEC-001) did not stop option drift: `_engine.py:213` `Engine.from_file` and `concurrency.py:77` `fork_engine` both omit `validators` and `redact_proof_failures`. Concrete effect: `fork_engine` cannot pass plugin validators, so a config with a `validators` list works in the parent but dies in the worker with `TemplateError: Unknown validator`; and audit-mode workers cannot redact. Make `EngineOptions` the only construction surface. |
| ARCH-011 | open | M | `Engine` mixes compile-time (`_validate`, `_build_prepared`, `_prepare_transforms`, `_resolve_transform`, `_resolve_validators`) with runtime (`__iter__`, `_render_row`, `_resolve`, `_generate_*`). ProofChecker was already extracted (ARCH-001); do the same for the compile half. |
| ARCH-012 | open | M | Atomic-write, special-file rejection, and umask/permission preservation (`cli.py:390-499`) are library-grade output concerns trapped in the CLI; `ton.api` callers writing to a file get none of it. Extract an output-sink module. |
| ARCH-013 | open | M | LSP/OCP: `generators/base.py:72` makes the base `Generator.prepare` *raise* for `is_composite` subclasses, so the interface is not uniformly callable and every caller must branch on the flag (see DUP-011). A single `prepare(spec, context)` carrying the registry removes the flag, the raising default, and both branches. |

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DEC-010 | open | M | **Circular import, reproducible failure.** `generators/weighted.py:55` imports `..transforms.distribution`, which imports `..generators` back (`distribution.py:11-12`). `import ton.transforms` / `import ton.transforms.distribution` therefore raises `ImportError: cannot import name 'WeightedChoiceSet' from partially initialized module` unless `ton.generators` happens to be fully imported first. `_registry.py:168` already hides this with a function-local deferred import. Fix: move `WeightedChoiceSet` / `prepare_distribution` / `validate_weights` into a neutral module both packages import. |
| DEC-011 | open | S | `_registry.py:121` `ExtensionCatalog._flattened` returns the *live* cached dict from `generators()`/`transforms()`/`validators()`; any caller mutating it corrupts catalog internals. Only `registry_with_entry_points:432` avoids this, via an explicit copy plus a warning comment. Return a copy or `MappingProxyType`. |
| DEC-012 | open | S | `generators/base.py:315` hard-codes the registry's `core.` namespace convention inside the generator layer (see DUP-012). |
| DEC-013 | open | S | Bidirectional coupling: `_proofcheck.py:26` imports `PreparedField`/`TransformStep` from `_engine` (TYPE_CHECKING only) while `_engine` imports `ProofChecker`. The trace value objects belong in `_proof.py`. |
| DEC-014 | open | M | OCP: `_engine.py:559` `_collect_nested_types` / `_walk_value_for_types` hard-code the assumption that *any* nested mapping with a `"type"` key is a generator reference, so the lazy registry silently depends on undocumented composite-spec shape (and sweeps up transform `type`s too, which `make_registry` then drops). Let composite generators declare their nested type names instead. |

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
| CLI-014 | open | M | A config `encoding` that cannot encode the rendered rows escapes as an unhandled `UnicodeEncodeError` through the top-level catch-all: exit code 3, "ton: unexpected error" (verified with `{"encoding":"ascii"}` and a non-ASCII `format`). Should be a config/output error (exit 1/2) with a pointed message. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-010 | open | M | Unknown config keys are silently ignored at every level. `_config._validate_root:131` checks only for *missing* required keys, and no generator rejects extra spec keys: `{"seed": 42}` at top level does nothing, and a `padwithzero` typo silently disables padding (verified). Reject or warn on unknown keys. |
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
| OBS-020 | open | M | Audit proof failures are undiagnosable from the CLI. `--proof-check audit` prints only a count and tells the user to rerun with `--log-level warning`, but `proof_check_failed` deliberately omits the value/spec (`_proofcheck.py:208`) and the CLI never exposes `Engine.proof_failures`. There is no CLI path to learn *which* value failed. Add a proof-report output (and then `--redact-proof-failures`, see CLI-010, would finally mean something). |
| OBS-021 | open | M | A failed run emits no terminal structured event. `_execute` (`cli.py:299-307`) catches `OSError` / `ProofError` / `ValidationError` and prints to stderr without logging; `engine_completed` is only emitted on full iteration. A structured-log consumer sees `engine_constructed` and then silence, and cannot distinguish an aborted run from a crashed process. |
| OBS-022 | open | S | `_install_progress_handler` (`cli.py:588`) forces the shared `ton` logger to level INFO whenever `--progress` is passed, overriding a stricter `--log-level error/critical` set in the same invocation and leaking the level change to any handler a library caller attached to `ton`. |
| OBS-023 | open | S | `cli.py:593` `_report` prints `inf rows/s` when elapsed rounds to 0 (`ton: wrote 0 rows in 0.000s (inf rows/s)`); the progress event guards the same division with `None` (`cli.py:546`) — two behaviors for one calculation. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-010 | open | S | `README.md:78-80` documents chunked generation as three `--resume-from 0/500000/1000000` runs, but the CLI has no row-limit option: each run generates *all* `rows` and only skips a prefix, so chunk-0 contains the whole dataset and the chunks overlap. Either document `fork_engine` for chunking or add a `--max-rows`/`--limit` flag. |
| DOC-020 | open | S | `README.md:256` ("Output to stdout uses the stream's own encoding") is false: `cli._open_output:398` routes stdout through `_reconfigured_stdout(encoding)`, applying the config's `encoding` to stdout as well. Verified: `{"encoding": "ascii"}` with a non-ASCII `format` crashes on stdout. |
| DOC-021 | open | S | `README.md:435` says a field's `validators` entries are "a built-in or namespaced validator name" — TON ships **no** built-in validators (`catalog.list_validators()` is empty), so only plugin-provided names can ever resolve. |
| DOC-022 | open | M | Shipped public API is undocumented. `README.md` "Library use" and the `ton/api.py:8-22` "supported surface" list both omit `validate_config`, `output_encoding`, `normalize_reference`, `RegistryError`, `Transform`, `Validator`, `ProvenanceRecord`, `Engine.provenance`, and the `validators=` / `proof_mode` / `proof_sample_rate` / `redact_proof_failures` keyword arguments of `generate` / `generate_from_file`, all of which are in `api.__all__`. |
| DOC-023 | open | S | README type-reference tables omit shipped defaults and caps: `bytes.length` defaults to 16 (table implies required), `text.count` defaults to 5, `sequence.padWidth` is capped by `MAX_SEQUENCE_PAD_WIDTH`, `hash.rounds` is absent from the field table. |
| DOC-024 | open | S | `README.md:59` `--batch-rows` ("Rows buffered per `write()` syscall") describes an implementation that does not exist — see CLI-011; the value is a flush interval. |