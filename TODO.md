# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Resource policy: TON is a batch-processing system. Do not reject valid jobs or
impose hard CPU, memory, row-width, expansion, pool-size, or precision caps.
Prefer streaming, lazy evaluation, chunking, spill-to-disk, and explicit
operator-controlled settings that do not introduce restrictive defaults.

Last full rescan: 2026-08-01 (all categories; cache/build files and directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-017 | open | M | Entry-point allowlisting trusts only `ep.name` (`_registry.py:236-237`) and reuses that name set across generator, transform, and validator groups. Any installed distribution can publish the same allowed name (in any group) and execute during `ep.load()()`. Bind trust to at least group + distribution identity + entry-point name, reject duplicate providers deterministically, and expose the stronger selector through API/CLI. |
| SEC-018 | open | S | `ProofFailure.redacted()` masks `value`, `id_value`, and `spec` but preserves the generator/transform-controlled `reason` (`_proof.py:77-92`). A plugin can return `ProofResult(False, reason=f"bad {result.value}")`, so `--redact-proof-failures` still leaks the generated value through reports and structured logs. Redact or structurally constrain untrusted reasons and add an echoing-reason regression test. |
| SEC-019 | open | S | Validator failures embed the complete generated value in `ValidationError` (`_engine.py:402-408`), and the CLI prints that exception to stderr (`cli.py:368-372`) with no redaction option. Remove raw values from the default diagnostic (or apply the same explicit redaction policy as proof failures) so credential-like fixture data is not disclosed. |
| SEC-020 | open | M | FIFO output opening has a symlink-swap race: `validate_output_target()` checks `islink`/`stat` and returns `True`, then `open_output_path()` later calls path-based `open()` (`_output.py:33-59,109-112`). In a writable shared directory an attacker can replace the checked FIFO with a symlink before open and redirect the write. Open with no-follow flags where available, validate the opened descriptor with `fstat`, and test a swapped target. |
| SEC-021 | open | S | CI executes mutable third-party action tags (`actions/checkout@v4`, `actions/setup-python@v5`; `.github/workflows/ci.yml:21-24,39-42,68-71,84-87`). Pin actions to reviewed commit SHAs (with version comments) so a moved/compromised tag cannot change trusted build code. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-029 | open | M | Pairing capability is not preserved as compiled state. A transform that accepts but drops pairing lets a requested `$field[id]$` silently render the transformed primary value; adding a later pairing-preserving transform makes `PreparedField.is_paired` look only at the last transform and render `""` (`_proof.py:32-37`, `_engine.py:355-360,387-393`). Fold the complete chain once, reject `[id]` references after pairing is lost, and cover both drop-only and drop-then-identity chains. |
| REL-030 | open | M | `DecimalGenerator` coerces bounds to binary `float` and renders through `step / scale` float division (`generators/decimal.py:64-87,132-136`). Exact JSON integers above 2^53 collapse (e.g. bounds `9007199254740992..9007199254740993` emit only the lower value), and large fixed bounds render binary-float artifacts. Preserve raw values as `Decimal`/scaled integers and format without float conversion. |
| REL-031 | open | S | The vendored regex parser treats unsupported escapes as literals (`generators/_regex_parse.py:263-275`) instead of rejecting them. Patterns such as `(a)\1` and `\x41` generate `a1` and `x41`, which do not match the supplied regex. Explicitly reject unsupported backreferences/escape forms (or implement them) and verify generated output against every accepted construct. |
| REL-032 | open | L | Proof checking is permissive for every non-composite built-in: only `weighted`, `oneOf`, and `sequence_of` override `Generator.prove`; all other sources inherit `ProofResult(ok=True)` (`generators/base.py:154-162`). Consequently `--proof-check all/audit` cannot detect a faulty core integer, regex, hash, date, etc. implementation. Add real proof hooks by generator family and mutation tests proving each core type can fail. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-035 | open | S | Default Engine construction still instantiates every built-in generator: after `_resolve_registry()` builds the referenced-only registry, `EngineCompiler.__init__` calls `build_extension_catalog()` solely for transforms/validators, whose catalog constructor calls `default_registry()` (`_compiler.py:64-67`, `_registry.py:58-69,203-211`). Build the default transform/validator maps without constructing an unused full generator catalog. |
| PERF-036 | open | M | Non-bcrypt hashes eagerly digest the entire `values` pool during prepare (`generators/hash.py:83-86`). Thus `--validate`, `rows: 0`, and small jobs pay CPU/memory for every SHA/NTLM value even when none or few are selected. Use the lazy per-plaintext cache already implemented for bcrypt without capping the pool. |
| PERF-037 | open | M | Every clear proof-audit failure copies the full field spec and serializes it into every JSONL record (`_proofcheck.py:111-115`, `_proofaudit.py:38-53`). A large value pool multiplied by many failures creates avoidable multiplicative copying/output. Emit specs once (or by stable reference/fingerprint) while preserving a streaming, self-describing report. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCAL-018 | open | S | `_validate_rows` rejects jobs above `MAX_ROWS = 1_000_000_000` (`_config.py:42-45,171-175`). Row iteration is already streaming, so this is a hard workload cap contrary to the repository policy. Accept arbitrary non-negative Python integers and leave duration/storage decisions to the operator. |
| SCAL-019 | open | S | Every job has an implicit `DEFAULT_MAX_ROW_WIDTH = 2_000_000`, and `_bounded_row` rejects larger rendered rows even when `maxRowWidth` is omitted (`_config.py:45,128-135`, `_engine.py:339-344`). Make the guard opt-in (or operator-configured without a restrictive default) while retaining explicit width enforcement when requested. |
| SCAL-020 | open | S | `CharGenerator.prepare` rejects `maxChar > 100_000` through `MAX_CHAR_LENGTH` (`generators/char.py:12-14,28-34`). Remove the hard row-size cap and make generation honor the requested count without introducing a replacement fixed limit. |
| SCAL-021 | open | S | `BytesGenerator.prepare` rejects `length > 1_000_000` through `MAX_BYTES_LENGTH` (`generators/bytes.py:43-44,58-68`). Remove the hard size cap and use chunked generation/encoding where needed rather than rejecting a valid large byte field. |
| SCAL-022 | open | S | `TextGenerator.prepare` rejects `count > 10_000` through `MAX_TEXT_COUNT` (`generators/text.py:94-96,110-118`). Remove the hard workload cap and generate/join incrementally without imposing a new restrictive default. |
| SCAL-023 | open | M | `SequenceOfGenerator.prepare` rejects `count > 10_000`, and generation materializes a list containing every child result (`generators/sequence_of.py:39-41,69-95`). Remove the cap and rework accumulation so large requested sequences are not rejected solely by a fixed policy limit. |
| SCAL-024 | open | S | `SequenceGenerator.prepare` rejects `padWidth > 100_000` through `MAX_SEQUENCE_PAD_WIDTH` (`generators/sequence.py:38-39,53-67`). Remove the fixed row-width cap and honor operator-requested padding. |
| SCAL-025 | open | M | Regex preparation rejects otherwise supported patterns through fixed literal-repeat, total-expansion, and group-nesting caps (`generators/regex.py:38-51,71-85,116-166`; `generators/_regex_parse.py:97,203-219`). Replace recursive/eager expansion paths with overflow-safe lazy/iterative handling and operator-controlled settings rather than fixed rejection thresholds. |
| SCAL-026 | open | S | Bcrypt accepts only rounds 4..12 even though the format supports higher costs (`generators/hash.py:49,75-80`). `MAX_BCRYPT_ROUNDS` is a hard CPU-policy cap; validate only the algorithm's representable range and let operators choose the intended cost. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|
| CONC-016 | open | S | Sequence shard offsets are correct only for bare `sequence` with explicit `start` and `step=1`: `_offset_sequence_spec` defaults `start` to 1 instead of the generator's 0, adds `offset` instead of `offset * step`, and ignores `core.sequence` (`concurrency.py:190-205`). Normalize the reference and apply the generator's exact start/step semantics; current shards shift defaults, overlap for `step=2`, and duplicate qualified sequences. |
| CONC-017 | open | L | Sequence partitioning assumes one counter draw per output row (`concurrency.py:122-127,190-205`). Repeated placeholders (`$id$,$id$`) and `sequence` nested under `sequence_of` draw multiple times, so later workers start inside earlier workers' ranges and duplicate ids. Compute offsets from the compiled draw plan (including composite multiplicity) or assign each worker a provably disjoint counter stream. |

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-012 | open | M | `atomic_output` clears `tmp_name` immediately after `os.replace`/`os.link` and then fsyncs the directory (`_output.py:88-99`). If directory fsync fails, the context reports an output error even though the new final file is already published and cannot be rolled back, making retry/recovery ambiguous. Define a post-publish failure contract and preserve enough state to report that the destination changed. |
| ROB-013 | open | M | With both `--output` and `--proof-report`, the inner data context publishes first and the outer report context finalizes second (`cli.py:337-349,505-533`). A report chmod/replace/fsync failure after generation therefore returns exit 1 with the data file committed and the report missing/old. Implement recoverable two-target publication or explicitly surface the partial-commit state and recovery steps. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|
| ARCH-021 | open | M | `_resolve` wraps source generation, transform application, proof evaluation, and validators in one broad exception boundary, then logs/rethrows every unexpected stage failure as `Generator ... raised ...` (`_engine.py:346-385`). Give each pipeline stage its own typed failure context so transform/validator/plugin defects identify the actual component instead of falsely blaming the source generator. |

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|
| PAT-021 | open | M | `distribution` is modeled as a post-source transform but discards its input (`transforms/distribution.py:33-40`), so every row first executes an unrelated source generator (including expensive/stateful sources) and then throws that value away. Model distribution as a source-selection strategy or add an explicit pre-source/short-circuit stage so the domain pipeline does not perform meaningless work. |

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|
| PLUG-020 | open | M | `_validate_nested_generator_keys` recursively interprets every plugin-owned mapping containing a `type` key as a nested generator spec (`_config.py:246-258`). A plugin's ordinary metadata such as `{"type":"string","custom":1}` is therefore validated against the core string schema and rejected. Let each composite extension declare its actual nested-spec locations instead of inferring from arbitrary mappings. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-019 | open | S | Normal CLI/library generation runs structural validation plus `compile_plan`, but extension-owned key validation runs only through `api.validate_config` (`_config.py:73-104`, `cli.py:268-300`). A typo such as integer `padWithZeros` is rejected by `ton --validate` yet silently ignored by the real run. Use one canonical validation path for validate-only and generation. |
| CLI-020 | open | S | Catalog validation compiles only fields referenced by the template (`_config.py:85-103`, `_compiler.py:107-150`). An unused field with `type: missing` or inverted integer bounds is therefore reported as valid by `ton --validate`, despite help promising per-field spec validation. Resolve and prepare every declared field during validation without changing generation's lazy runtime plan. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-021 | open | S | The canonical validation docs promise available-name diagnostics for types and transforms (`api.py:121-129`), but `_resolve_transform` and `_resolve_validators` report only the missing reference (`_compiler.py:186-200`); the success event also omits available validators (`_config.py:105-113`). Include sorted available transforms/validators and namespace guidance consistently. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-012 | open | S | The governance scan skips any tracked file containing one NUL byte (`tests/test_data_governance.py:62-78`). Adding a NUL to a text fixture therefore bypasses all private-path and credential patterns, and binary fixtures are never scanned. Search raw bytes regardless of NULs (or use a binary-aware scanner) and add an evasion regression test. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|
| DEP-011 | open | M | `bcrypt>=4` admits behavior-changing releases while TON does not normalize bcrypt's 72-byte plaintext boundary (`pyproject.toml:29-36`, `generators/hash.py:69-82,88-104`). With installed bcrypt 5.0.0, a >72-byte value passes `--validate` and fails only on its first selected row; other admitted versions can behave differently. Define stable TON semantics (prefer early byte-length validation) and constrain/test the supported dependency range. |

## platform

| id | status | effort | description |
|----|--------|--------|-------------|
| PLAT-013 | open | M | The date portability allowlist includes locale-dependent directives (`%a/%A/%b/%B/%c/%p/%x/%X/%Z`; `generators/date.py:31,64-76`). Identical seeded configs can therefore emit different text under another process locale/OS even though the CLI promises reproducible output. Either implement locale-neutral formatting for the supported contract or document and test locale dependence explicitly. |

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-028 | open | S | The CLI catch-all comment/docs promise a traceback with `--log-level`, but `_run` calls `_logger.error` without `exc_info` rather than `logger.exception` (`cli.py:202-213`; `README.md:1025`). Debug handlers receive no traceback. Emit the unexpected event with exception information while keeping the user-facing stderr line concise. |
| OBS-029 | open | S | Audit CLI runs emit `proof_check_summary` twice: `ProofChecker.log_summary()` logs it when Engine iteration ends, then `_report_proof_audit()` logs the same event again (`_proofcheck.py:168-181`, `cli.py:412-427`). Use a distinct CLI presentation event or print without re-emitting the canonical summary so consumers see one terminal record per run. |
| OBS-030 | open | S | Output-write failures derive `rows_written` from `engine.rows_emitted - resume_from` (`cli.py:350-360`), but Engine increments `rows_emitted` before yielding and `_stream` increments `written` only after a successful write (`_engine.py:299-313`, `cli.py:577-591`). A first-row encoding/write failure is logged as one row written. Preserve the actual sink count through the failure boundary. |
| OBS-031 | open | S | `output_overwrite` is emitted during preflight as soon as a target exists (`_output.py:33-59`), before generation or atomic replacement. Failed/interrupted jobs leave the old file intact but still claim an overwrite; README also says the file was “truncated” (`README.md:1022`). Emit a committed-replacement event after publication and use a separate preflight warning if desired. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-030 | open | S | The streaming library example calls `sink.write(row)` twice inside one loop (`README.md:218-220`), duplicating every generated row for readers who copy it. Remove the duplicate line and lock the snippet with a documentation test. |
| DOC-031 | open | S | README documents deterministic bcrypt salts but does not state they are unsuitable for password storage (`README.md:950-954`); that warning exists only in a private code comment (`generators/hash.py:115-118`), while Safety notes mention only NTLM. Add a prominent user-facing warning for deterministic bcrypt (and weak fixture-only hashes). |
| DOC-032 | open | S | README calls entry-point loading “sandboxed per-entry” (`README.md:1033`), but the implementation merely catches exceptions after executing arbitrary package code in the TON process (`_registry.py:234-246`). Replace “sandboxed” with “failure-isolated” and state clearly that opt-in plugins have the caller's full process privileges. |
| DOC-033 | open | S | `generators/sequence.py:7` documents `start` defaulting to 1 while implementation and README use 0 (`sequence.py:53-55`, `README.md:749-753`). Correct the module example so copied configs and shard reasoning use the actual default. |
