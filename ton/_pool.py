"""Ordered string sampling with a lazy, reusable membership index."""

from functools import cached_property


class StringPool(tuple[str, ...]):
    """Keep duplicate draw weights; pay for the index only on a membership check."""

    @cached_property
    def _members(self) -> frozenset[str]:
        return frozenset(self)

    def __contains__(self, value: object) -> bool:
        return isinstance(value, str) and value in self._members
