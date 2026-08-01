"""Reusable output-target policy and sink primitives."""

from __future__ import annotations

import os
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from math import isfinite
from typing import TextIO, cast

from ._logging import LogEvent
from ._logging import logger as _logger


class OutputEncodingError(OSError):
    """A configured codec could not encode generated output.

    Encoding failures are output errors, not invalid configuration: the
    codec is valid, but a generated value is not representable in it.
    ``field_name`` identifies a field when the failing value can be traced
    before row rendering; otherwise it is ``None`` for the rendered row.
    """

    def __init__(self, encoding: str, reason: str, *, field_name: str | None = None) -> None:
        self.encoding = encoding
        self.field_name = field_name
        self.reason = reason
        context = f"field {field_name!r}" if field_name is not None else "rendered row"
        super().__init__(f"cannot encode {context} as {encoding!r}: {reason}")


class OutputPublishedError(OSError):
    """Publication changed the destination but durability confirmation failed."""

    def __init__(self, path: str, cause: OSError) -> None:
        self.path = path
        self.destination_changed = True
        self.cause = cause
        super().__init__(
            f"output was published to {path}, but finalization failed: {cause}; "
            "inspect the destination before retrying"
        )


class PartialOutputCommitError(OSError):
    """Multiple requested outputs did not finish as one all-or-nothing unit."""

    def __init__(
        self,
        published_paths: tuple[str, ...],
        failed_path: str,
        cause: Exception,
    ) -> None:
        self.published_paths = published_paths
        self.failed_path = failed_path
        self.cause = cause
        published = ", ".join(published_paths)
        super().__init__(
            f"partial output commit; published/changed: {published}; failed target: "
            f"{failed_path}; inspect these paths and keep or remove them consistently "
            f"before retrying: {cause}"
        )


@dataclass(frozen=True)
class StagedOutput:
    """Inspection record for an unpublished same-directory output stage."""

    path: str
    owner_pid: int | None
    created_at_ns: int
    age_seconds: float
    owner_running: bool | None

    @property
    def managed(self) -> bool:
        """Whether TON can identify the stage owner and creation time."""
        return self.owner_pid is not None


@dataclass(frozen=True)
class _StagedCandidate:
    report: StagedOutput
    device: int
    inode: int


def validate_output_target(path: str, *, no_clobber: bool = False) -> bool:
    """Validate ``path`` and return whether it names an existing FIFO."""
    if os.path.islink(path):
        raise OSError(f"refusing to replace symbolic-link output: {path}")
    if not os.path.exists(path):
        return False
    target = os.stat(path)
    if not (stat.S_ISREG(target.st_mode) or stat.S_ISFIFO(target.st_mode)):
        _log_special_file_rejected(path, target.st_mode)
        raise OSError(f"refusing to write to special file (not a regular file): {path}")
    if no_clobber:
        raise OSError(f"refusing to overwrite existing file: {path}")
    return stat.S_ISFIFO(target.st_mode)


@contextmanager
def atomic_output(
    path: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
    no_clobber: bool = False,
) -> Iterator[TextIO]:
    """Yield a temporary stream and atomically replace ``path`` on success."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    basename = os.path.basename(path)
    tmp_name = ""
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            newline="\n",
            dir=directory,
            prefix=_stage_prefix(basename),
            suffix=".tmp",
            delete=False,
        ) as stream:
            tmp_name = stream.name
            yield cast(TextIO, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, mode)
        try:
            if no_clobber:
                os.link(tmp_name, path)
                published = True
                os.unlink(tmp_name)
            else:
                destination_existed = os.path.exists(path)
                os.replace(tmp_name, path)
                published = True
                if destination_existed:
                    _logger.warning(
                        "output_overwrite path=%s committed=true",
                        path,
                        extra={
                            "event": LogEvent.OUTPUT_OVERWRITE.value,
                            "path": path,
                            "committed": True,
                        },
                    )
            tmp_name = ""
            _fsync_directory(directory)
        except OSError as exc:
            if published:
                raise OutputPublishedError(path, exc) from exc
            raise
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)


def inspect_staged_outputs(path: str) -> tuple[StagedOutput, ...]:
    """Return unpublished stages associated with output ``path``.

    Managed stages carry their creating PID and timestamp in the filename.
    Older unowned ``.<basename>.*.tmp`` files are reported but never removed
    automatically because a live writer cannot be ruled out safely.
    """
    return tuple(candidate.report for candidate in _staged_candidates(path))


def cleanup_staged_outputs(
    path: str,
    *,
    stale_after_seconds: float = 86_400,
) -> tuple[str, ...]:
    """Remove managed stages older than ``stale_after_seconds`` whose owner exited."""
    if (
        isinstance(stale_after_seconds, bool)
        or not isinstance(stale_after_seconds, (int, float))
        or not isfinite(stale_after_seconds)
        or stale_after_seconds < 0
    ):
        raise ValueError("stale_after_seconds must be a finite non-negative number")
    removed: list[str] = []
    for candidate in _staged_candidates(path):
        report = candidate.report
        if (
            not report.managed
            or report.age_seconds < stale_after_seconds
            or report.owner_running is not False
        ):
            continue
        if _remove_abandoned_stage(candidate):
            removed.append(report.path)
    if removed:
        _fsync_directory(os.path.dirname(os.path.abspath(path)) or ".")
    return tuple(removed)


def _stage_prefix(basename: str) -> str:
    return f".{basename}.ton-{os.getpid()}-{time.time_ns()}-"


def _staged_candidates(path: str) -> list[_StagedCandidate]:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    basename = os.path.basename(path)
    file_prefix = f".{basename}."
    now_ns = time.time_ns()
    candidates: list[_StagedCandidate] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.startswith(file_prefix) or not entry.name.endswith(".tmp"):
                continue
            try:
                target = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(target.st_mode):
                continue
            owner_pid, created_at_ns = _parse_stage_owner(entry.name, file_prefix)
            created_at_ns = created_at_ns or target.st_mtime_ns
            candidates.append(
                _StagedCandidate(
                    report=StagedOutput(
                        path=entry.path,
                        owner_pid=owner_pid,
                        created_at_ns=created_at_ns,
                        age_seconds=max(0.0, (now_ns - created_at_ns) / 1_000_000_000),
                        owner_running=(
                            _process_is_running(owner_pid) if owner_pid is not None else None
                        ),
                    ),
                    device=target.st_dev,
                    inode=target.st_ino,
                )
            )
    return sorted(candidates, key=lambda candidate: candidate.report.path)


def _parse_stage_owner(name: str, file_prefix: str) -> tuple[int | None, int | None]:
    payload = name[len(file_prefix) : -len(".tmp")]
    parts = payload.split("-", 3)
    if len(parts) != 4 or parts[0] != "ton" or not parts[3]:
        return None, None
    try:
        pid = int(parts[1])
        created_at_ns = int(parts[2])
    except ValueError:
        return None, None
    if pid < 1 or created_at_ns < 1:
        return None, None
    return pid, created_at_ns


def _remove_abandoned_stage(candidate: _StagedCandidate) -> bool:
    report = candidate.report
    if report.owner_pid is None or _process_is_running(report.owner_pid) is not False:
        return False
    try:
        current = os.stat(report.path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != candidate.device
        or current.st_ino != candidate.inode
    ):
        return False
    try:
        os.unlink(report.path)
    except FileNotFoundError:
        return False
    return True


def _process_is_running(pid: int) -> bool | None:
    if pid == os.getpid():
        return True
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError):
        return False
    except OSError:
        return None
    return True


def _windows_process_is_running(pid: int) -> bool | None:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    get_exit_code.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = open_process(0x1000, False, pid)
    if not handle:
        return False if ctypes.get_last_error() == 87 else None  # type: ignore[attr-defined]
    try:
        exit_code = wintypes.DWORD()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == 259
    finally:
        close_handle(handle)


@contextmanager
def open_output_path(
    path: str,
    *,
    no_clobber: bool = False,
    encoding: str = "utf-8",
) -> Iterator[TextIO]:
    """Open a validated path with FIFO or atomic regular-file semantics."""
    if validate_output_target(path, no_clobber=no_clobber):
        with _open_fifo(path, encoding=encoding) as stream:
            yield stream
        return
    with atomic_output(
        path,
        encoding=encoding,
        mode=target_mode(path),
        no_clobber=no_clobber,
    ) as stream:
        yield stream


@contextmanager
def _open_fifo(path: str, *, encoding: str) -> Iterator[TextIO]:
    """Open and descriptor-check a FIFO without following symlinks."""
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        target = os.fstat(descriptor)
        if not stat.S_ISFIFO(target.st_mode):
            _log_special_file_rejected(path, target.st_mode)
            raise OSError(f"refusing output target that changed before FIFO open: {path}")
        with os.fdopen(
            descriptor,
            "w",
            encoding=encoding,
            newline="\n",
            closefd=True,
        ) as stream:
            descriptor = -1
            yield cast(TextIO, stream)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _log_special_file_rejected(path: str, mode: int) -> None:
    _logger.error(
        "output_special_file_rejected path=%s mode=%o",
        path,
        mode,
        extra={
            "event": LogEvent.OUTPUT_SPECIAL_FILE_REJECTED.value,
            "path": path,
            "mode": mode,
        },
    )


def target_mode(path: str) -> int:
    """Preserve destination permissions or apply the process file-creation mask."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        return _new_file_mode(directory)


def _new_file_mode(directory: str) -> int:
    """Probe default file permissions without mutating the process umask."""
    with tempfile.TemporaryDirectory(prefix=".ton-mode.", dir=directory) as probe_dir:
        probe_path = os.path.join(probe_dir, "probe")
        descriptor = os.open(
            probe_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666,
        )
        try:
            return stat.S_IMODE(os.fstat(descriptor).st_mode)
        finally:
            os.close(descriptor)


def _fsync_directory(directory: str) -> None:
    """Persist a published directory entry where directory fsync is supported."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
