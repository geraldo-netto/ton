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

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-037 | open | M | Every clear proof-audit failure copies the full field spec and serializes it into every JSONL record (`_proofcheck.py:111-115`, `_proofaudit.py:38-53`). A large value pool multiplied by many failures creates avoidable multiplicative copying/output. Emit specs once (or by stable reference/fingerprint) while preserving a streaming, self-describing report. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-012 | open | M | `atomic_output` clears `tmp_name` immediately after `os.replace`/`os.link` and then fsyncs the directory (`_output.py:88-99`). If directory fsync fails, the context reports an output error even though the new final file is already published and cannot be rolled back, making retry/recovery ambiguous. Define a post-publish failure contract and preserve enough state to report that the destination changed. |
| ROB-013 | open | M | With both `--output` and `--proof-report`, the inner data context publishes first and the outer report context finalizes second (`cli.py:337-349,505-533`). A report chmod/replace/fsync failure after generation therefore returns exit 1 with the data file committed and the report missing/old. Implement recoverable two-target publication or explicitly surface the partial-commit state and recovery steps. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-012 | open | S | The governance scan skips any tracked file containing one NUL byte (`tests/test_data_governance.py:62-78`). Adding a NUL to a text fixture therefore bypasses all private-path and credential patterns, and binary fixtures are never scanned. Search raw bytes regardless of NULs (or use a binary-aware scanner) and add an evasion regression test. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|

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
