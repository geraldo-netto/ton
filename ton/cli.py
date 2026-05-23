"""Command-line entry point for TON."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from random import Random
from typing import TextIO

from . import __version__
from ._config import ConfigError, load
from ._engine import Engine, TemplateError
from ._logging import configure_stderr

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: Rows per write() syscall when streaming to a file. Picked to be big
#: enough to amortize Python attribute / interpreter overhead but small
#: enough to keep peak memory bounded for wide rows (TODO SCALE-001).
_BATCH_ROWS = 1024


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ton",
        description="TON: mass data generator. Render rows from a JSON template.",
    )
    parser.add_argument("config", help="Path to the JSON config file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Write rows to this file instead of stdout.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed the RNG for reproducible output.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print final row count, elapsed time, and rows/sec to stderr.",
    )
    parser.add_argument(
        "--progress",
        type=int,
        metavar="EVERY",
        default=0,
        help="Emit a JSON progress line to stderr every EVERY rows (0 disables).",
    )
    parser.add_argument(
        "--log-level",
        choices=sorted(_LOG_LEVELS.keys()),
        default=None,
        help="Attach a stderr handler to the 'ton' logger at this level (OBS-003).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a shell exit code."""
    args = _build_parser().parse_args(argv)
    if args.log_level is not None:
        configure_stderr(_LOG_LEVELS[args.log_level])
    return _run(args)


def _run(args: argparse.Namespace) -> int:
    """Execute the parsed command. Split out of main() so flag handling
    stays small as new options are added."""
    try:
        return _run_inner(args)
    except KeyboardInterrupt:
        print("ton: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI safety net
        # Anything not mapped below leaks here -- log it cleanly so the
        # user gets 'ton: ...' + exit 3 instead of a stack trace
        # (REL-013).
        print(f"ton: unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


def _run_inner(args: argparse.Namespace) -> int:
    try:
        engine = _build_engine(args)
    except FileNotFoundError as exc:
        print(f"ton: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, TemplateError, json.JSONDecodeError) as exc:
        print(f"ton: invalid config: {exc}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    try:
        with _open_output(args.output) as stream:
            rows_written = _stream(engine, stream, args.progress)
    except OSError as exc:
        print(f"ton: cannot write output: {exc}", file=sys.stderr)
        return 1
    if args.verbose:
        _report(rows_written, time.perf_counter() - started)
    return 0


def _build_engine(args: argparse.Namespace) -> Engine:
    rng = Random(args.seed) if args.seed is not None else Random()
    config = load(args.config)
    # --progress already prints JSON; reuse the same interval as the
    # engine's logger milestone so structured handlers see the same
    # boundaries.
    return Engine(config, rng=rng, milestone_rows=args.progress)


@contextmanager
def _open_output(path: str | None) -> Iterator[TextIO]:
    if path is None:
        yield sys.stdout
        return
    with open(path, "w", encoding="utf-8") as fh:
        yield fh


def _stream(engine: Engine, stream: TextIO, progress_every: int) -> int:
    """Write rows in batches, optionally emitting JSON progress lines
    on stderr every ``progress_every`` rows (TODO SCALE-001, OBS-002).

    Returns the total row count for use by --verbose summaries.
    """
    buffer: list[str] = []
    count = 0
    started = time.perf_counter()
    for row in engine:
        buffer.append(row)
        buffer.append("\n")
        count += 1
        if len(buffer) >= _BATCH_ROWS * 2:
            stream.write("".join(buffer))
            buffer.clear()
        if progress_every and count % progress_every == 0:
            _emit_progress(count, time.perf_counter() - started)
    if buffer:
        stream.write("".join(buffer))
    return count


def _emit_progress(rows: int, elapsed: float) -> None:
    payload = {
        "rows": rows,
        "elapsed_seconds": round(elapsed, 3),
        "rows_per_second": round(rows / elapsed, 1) if elapsed > 0 else None,
    }
    print(json.dumps(payload), file=sys.stderr, flush=True)


def _report(rows: int, elapsed: float) -> None:
    rate = round(rows / elapsed, 1) if elapsed > 0 else float("inf")
    print(
        f"ton: wrote {rows} rows in {elapsed:.3f}s ({rate} rows/s)",
        file=sys.stderr,
    )
