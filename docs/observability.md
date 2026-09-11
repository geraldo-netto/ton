# Logging and progress

[Documentation](README.md) · [Project overview](../README.md)

Library code emits structured INFO events on a single logger named `ton`. Attach a handler the usual way (`logging.getLogger("ton")`) or pass `--log-level` on the CLI to get a stderr handler for free. The event identifier lives in `record.event` and matches a value from the `api.LogEvent` enum:

| event                                 | when                                                |
|---------------------------------------|-----------------------------------------------------|
| `engine_constructed`                  | Engine built, rows/types/paired-flag known          |
| `engine_milestone`                    | every `milestone_rows` rows during iteration        |
| `engine_progress`                     | CLI progress tick (also emitted as JSON on stderr)  |
| `engine_completed`                    | iterator exhausted                                  |
| `engine_forked`                       | `fork_engine` produced a worker Engine              |
| `prepare_failed` / `generate_failed`  | a Generator raised during prepare / generate        |
| `transform_prepared`                  | a field's transform was prepared at construction    |
| `config_validated`                    | `validate_config` passed catalog-aware checks       |
| `proof_check_failed`                  | a value failed its proof check (per-row detail)     |
| `proof_check_summary`                 | end-of-run proof summary (`mode`, `failures`)       |
| `registry_discovered`                 | built-in registry built (once per process)          |
| `plugin_registered`                   | a namespaced plugin was registered in the catalog   |
| `entry_point_loaded`                  | third-party plugin instantiated                     |
| `entry_point_failed`                  | third-party plugin raised on load — entry skipped   |
| `entry_points_summary`                | per-process summary of loaded / failed entries      |
| `output_overwrite`                    | an existing regular output was atomically replaced  |
| `output_special_file_rejected`        | `-o` target was not a regular file or FIFO          |
| `resume_overshoot`                    | `--resume-from` exceeded `total_rows`               |
| `cli_unexpected_error`                | CLI top-level catch-all (traceback in handler)      |
| `cli_failed`                          | terminal CLI failure with safe category/counts      |

See [CLI logging flags](cli.md#flags), [library milestones](library.md#engine-lifecycle),
and [proof reports and redaction](proofs.md) for configuration and diagnostic output.
