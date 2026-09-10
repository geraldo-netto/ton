"""Explicit mapping-key/list-index locations for owned generator specifications."""

type SpecPath = tuple[str | int, ...]


def format_spec_path(path: SpecPath) -> str:
    """Render a location for diagnostics; never parse this text to traverse a spec."""
    return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(".")
