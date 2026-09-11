"""Internal generated text carries metadata without copying its string storage."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceText:
    value: str
    trace: object


def plain_text(value: str | TraceText) -> str:
    return value.value if isinstance(value, TraceText) else value
