"""Stack head-room for deeply nested composite specs (SCALE-007).

Composite nesting has no documented ceiling, but three of the four stages
that descend a spec tree used to recurse: discovery, unknown-key validation,
and the config snapshot. Those are iterative now, so their depth costs no
stack at all.

Preparation and row generation still descend once per level, because a
composite generator resolves its children from inside its own ``prepare``
and ``generate``. That is the published extension contract, so the depth
they can reach is bounded by the interpreter's recursion limit and, beneath
it, the process stack. This module raises the limit to fit the workload
rather than rejecting the workload to fit the limit, and stops raising it
short of the point where the C stack would fault -- reporting the operator's
own remedy instead of crashing.

The bound is the process stack, which the operator controls (``ulimit -s``);
:data:`FRAME_STACK_BYTES` is the conservative per-frame estimate used to
translate that into frames.
"""

from __future__ import annotations

import sys

#: Bytes of process stack one nesting level is assumed to need. Measured at
#: roughly 3.2 KB per level on an 8 MB stack; doubled so the computed bound
#: stays well short of a fault, since per-level cost grows with depth.
BYTES_PER_LEVEL = 8192

#: Assumed stack when the platform does not report a finite limit.
DEFAULT_STACK_BYTES = 8 * 1024 * 1024

#: Python frames one nesting level costs in the deepest recursive stage.
FRAMES_PER_LEVEL = 12

#: Frames reserved for the caller's own stack and the non-nested work.
BASE_FRAMES = 500


class NestingTooDeepError(ValueError):
    """A spec nests deeper than the process stack can safely support."""


def _stack_bytes() -> int:
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX platforms
        return DEFAULT_STACK_BYTES
    soft, _hard = resource.getrlimit(resource.RLIMIT_STACK)
    if soft in (resource.RLIM_INFINITY, 0) or soft < 0:
        return DEFAULT_STACK_BYTES
    return int(soft)


def max_supported_depth() -> int:
    """Return the deepest nesting this process's stack can safely support."""
    return max(_stack_bytes() // BYTES_PER_LEVEL, 1)


def ensure_depth_headroom(depth: int) -> None:
    """Ensure the recursion limit accommodates ``depth`` nested levels.

    Only ever raises the limit, so a caller that has already raised it keeps
    its own setting.
    """
    supported = max_supported_depth()
    if depth > supported:
        raise NestingTooDeepError(
            f"spec nests {depth} levels; this process's stack safely supports about "
            f"{supported}. Raise the stack limit (for example 'ulimit -s 65536') and "
            f"retry -- TON imposes no nesting limit of its own, but preparation and "
            f"row generation descend once per level through the extension contract."
        )
    needed = BASE_FRAMES + FRAMES_PER_LEVEL * max(depth, 0)
    if needed > sys.getrecursionlimit():
        sys.setrecursionlimit(needed)
