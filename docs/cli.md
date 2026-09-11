# Command-line interface

[Documentation](README.md) · [Project overview](../README.md)

Commands in these guides run from the repository root after installation.
For an uninstalled checkout, use `python -m ton` in place of `ton`.

## Run a config

```bash
ton examples/hwmetrics.json
```

Pin the RNG for reproducible output:

```bash
ton examples/hwmetrics.json --seed 42
```

Stream to a file (avoids buffering in your shell):

```bash
ton examples/hwmetrics.json -o hwmetrics.csv
```

## Flags

| flag                   | description                                                                          |
|------------------------|--------------------------------------------------------------------------------------|
| `--seed <int>`         | Seed the RNG for reproducible output.                                                |
| `-o`, `--output PATH`  | Write rows to a file instead of stdout. Accepts a regular file or a FIFO; refuses other targets (`/dev/*`, …). |
| `--no-clobber`         | Fail instead of overwriting an existing `--output` or `--proof-report` file.          |
| `--resume-from N`      | Generate and discard the first `N` rows before writing output (paired with `--seed`). |
| `--validate`           | Validate the config and exit without generating rows.                                |
| `--batch-rows N`       | Flush output every N written rows (default `1024`).                                  |
| `--progress N`         | Emit a JSON progress line on stderr every `N` rows (also surfaces a logger event).   |
| `--verbose`            | Print final row count, elapsed time, and rows/sec to stderr.                         |
| `--log-level LEVEL`    | Attach a stderr handler to the `ton` logger (`debug`/`info`/`warning`/`error`/`critical`). |
| `--proof-check MODE`   | Proof-check generated values: `off`, `sample`, `all`, or `audit` (collect, don't abort). |
| `--proof-sample-rate N`| With `--proof-check sample`, check every `N`th generated row.                        |
| `--proof-report PATH`  | With audit mode, stream every failure as UTF-8 JSON Lines to `PATH`.                 |
| `--redact-proof-failures` | Mask values, paired ids, reasons, and field specs in proof diagnostics and reports. |
| `--list-namespaces`    | List available namespaces, data types, transforms, and validators, then exit.        |
| `--entry-points`       | Load trusted third-party plugins from the `ton.generators`, `ton.transforms`, and `ton.validators` entry-point groups. |
| `--entry-point GROUP:DISTRIBUTION:NAME` | Allow only this exact trusted entry-point provider; repeat for multiple providers. |
| `-h`, `--help` | Print command-line help. |
| `--version`            | Print the package version.                                                           |

Proof failures alone do not make `--proof-check audit` fail: a completed run
exits `0`, with the failure count printed to stderr (`ton: proof-check audit: …`).
Validator rejection or an execution/output error still fails the run.
Add `--proof-report PATH` for diagnostic values/specs. Each proof failure also
emits a value-free `proof_check_failed` log event (see `--log-level warning`).
Logs, progress and summaries go to stderr; stdout carries generated rows.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, including a completed audit run with proof failures. |
| `1` | Missing config, input/output failure, or refused special-file target. |
| `2` | Invalid arguments/configuration, unknown variable, strict proof failure, or validator rejection. |
| `3` | Unexpected error, including a generator, transform, validator or proof hook raising during generation. |
| `130` | Interrupted with Ctrl-C. |

## Run without installing

TON has no third-party runtime requirements, so from a checkout you can invoke it straight from the repo root:

```bash
# from the repo root, no pip install needed
python -m ton examples/hwmetrics.json
```

The current directory is on `sys.path` automatically, so Python finds the `ton/` package without `pip install`. Run from somewhere else by pointing `PYTHONPATH` at the checkout:

```bash
PYTHONPATH=/path/to/ton python -m ton /path/to/config.json
```

Every flag in this guide works the same way in module form.

## Output and recovery

- `-o PATH` refuses to open a target that is not a regular file or FIFO. A stray `--output /dev/sda` aborts with exit code `1` and an `output_special_file_rejected` log event.
- `--no-clobber` upgrades the silent overwrite to a hard refusal.
- Regular `-o PATH` writes are staged through a same-directory temp file and atomically replace the final path only after generation succeeds. FIFO targets remain direct streams, opened without following symlinks where supported and verified from the opened descriptor before writing.
- Staged filenames use a hashed destination prefix plus owner and creation metadata. Library callers can use `api.inspect_staged_outputs(PATH)` to report abandoned stages and `api.cleanup_staged_outputs(PATH, stale_after_seconds=...)` to remove only old, managed stages whose creating process is confirmed dead. Inspection recognizes only stages with the destination's hashed prefix. Matching files without valid ownership metadata are reported but never removed automatically.

`--resume-from` is for restarting one seeded stream: it still generates the
skipped prefix and does not limit the number of later rows.

See [proof-report publication](proofs.md#report-publication) for failures
affecting both data and audit files, [structured events](observability.md), and
[process partitioning](concurrency.md) for parallel output.
