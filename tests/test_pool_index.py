"""Indexed proof membership preserves ordered pool sampling."""

from random import Random

import pytest

from ton._transforms import TransformResult
from ton.generators.string import StringGenerator


class CountedQuery(str):
    __hash__ = str.__hash__

    def __eq__(self, other):
        self.comparisons = getattr(self, "comparisons", 0) + 1
        return super().__eq__(other)


@pytest.mark.parametrize("size", [100, 1000, 10000])
def test_string_proof_membership_work_is_independent_of_pool_size(size):
    """PERF-044: repeated proof lookups must not scan the ordered draw pool."""
    generator = StringGenerator()
    values = [f"value-{index}" for index in range(size)] + ["value-0"]
    prepared = generator.prepare({"values": values})
    expected_rng, actual_rng = Random(42), Random(42)
    assert [generator.generate(prepared, actual_rng) for _ in range(100)] == [
        expected_rng.choice(values) for _ in range(100)
    ]
    query = CountedQuery(f"value-{size - 1}")
    for _ in range(5):
        assert generator.prove(prepared, TransformResult(query)).ok
    assert query.comparisons <= 10
    assert not generator.prove(prepared, TransformResult("absent")).ok
    assert tuple(prepared.values) == tuple(values)


def test_pool_index_is_lazy_reused_and_survives_serialization():
    """PERF-044: sampling and invalid non-string probes allocate no proof index."""
    import pickle
    from copy import deepcopy

    from ton._pool import StringPool

    visits = []

    class CountedPool(StringPool):
        def __iter__(self):
            visits.append(1)
            return super().__iter__()

    pool = CountedPool(("a", "a", "b"))
    assert Random(42).choice(pool) in {"a", "b"}
    assert [] not in pool
    assert visits == []
    assert "a" in pool and "missing" not in pool and "b" in pool
    assert visits == [1]
    for copy in (deepcopy(StringPool(pool)), pickle.loads(pickle.dumps(StringPool(pool)))):
        assert tuple(copy) == ("a", "a", "b")
        assert "a" in copy and "missing" not in copy
