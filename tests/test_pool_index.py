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


class UnhashableText(str):
    def __eq__(self, other):
        return str.__eq__(self, other)


@pytest.mark.parametrize("value,accepted", [("allowed", True), ("absent", False)])
def test_unhashable_string_subclass_source_proofs(value, accepted):
    """REL-060: equality-compatible strings remain valid membership queries."""
    generator = StringGenerator()
    prepared = generator.prepare({"values": ["allowed", "allowed", "other"]})
    assert generator.prove(prepared, TransformResult(UnhashableText(value))).ok is accepted


@pytest.mark.parametrize(
    "algorithm,cache", [("sha256", False), ("ntlm", False), ("bcrypt", False), ("bcrypt", True)]
)
@pytest.mark.parametrize("value,accepted", [("allowed", True), ("absent", False)])
def test_unhashable_string_subclass_paired_plaintext_proofs(algorithm, cache, value, accepted):
    """REL-060: hash proofs accept unhashable plaintext without bypassing digest checks."""
    from ton.generators.hash import HashGenerator

    generator = HashGenerator()
    spec = {"algorithm": algorithm, "values": ["allowed"]}
    if algorithm == "bcrypt":
        spec.update(rounds=4, cache=cache)
    prepared = generator.prepare(spec)
    _, digest = generator.generate_pair(prepared, Random(42))
    assert generator.prove(prepared, TransformResult(digest, UnhashableText(value))).ok is accepted
    assert not generator.prove(prepared, TransformResult("wrong", UnhashableText(value))).ok


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


@pytest.mark.parametrize(
    "algorithm, cache", [("sha256", False), ("ntlm", False), ("bcrypt", False), ("bcrypt", True)]
)
def test_hash_plaintext_membership_does_not_scan_the_pool(algorithm, cache):
    """PERF-045: pool indexing preserves digest checks and both bcrypt policies."""
    from ton.generators.hash import HashGenerator

    class LastRandom(Random):
        def choice(self, values):
            return values[-1]

    values = ["value-0", *(f"value-{index}" for index in range(1000))]
    spec = {"algorithm": algorithm, "values": values}
    if algorithm == "bcrypt":
        spec.update(rounds=4, cache=cache)
    generator = HashGenerator()
    prepared = generator.prepare(spec)
    plaintext, digest = generator.generate_pair(prepared, LastRandom())
    query = CountedQuery(plaintext)
    for _ in range(5):
        assert generator.prove(prepared, TransformResult(digest, query)).ok
    assert query.comparisons <= 20
    assert not generator.prove(prepared, TransformResult(digest, "absent")).ok
    assert not generator.prove(prepared, TransformResult("wrong", plaintext)).ok
    assert not generator.prove(prepared, TransformResult(digest)).ok
    assert tuple(prepared.words) == tuple(values)
    if algorithm == "bcrypt":
        assert prepared.cache == ({plaintext: digest} if cache else None)


def test_email_domain_membership_does_not_scan_the_pool():
    """PERF-046: index domains while retaining exact configured spelling and draws."""
    from ton.generators.identity import EmailGenerator

    queries = []

    class CountedEmail(str):
        def rpartition(self, separator):
            local, delimiter, domain = super().rpartition(separator)
            query = CountedQuery(domain)
            queries.append(query)
            return local, delimiter, query

    class LastRandom(Random):
        def choice(self, values):
            return values[-1]

    domains = ["D0.example", *(f"D{i}.example" for i in range(1000))]
    generator = EmailGenerator()
    prepared = generator.prepare({"domains": domains})
    value = generator.generate(prepared, LastRandom())
    for _ in range(5):
        assert generator.prove(prepared, TransformResult(CountedEmail(value))).ok
    assert sum(query.comparisons for query in queries) <= 10
    local = value.rpartition("@")[0]
    assert not generator.prove(prepared, TransformResult(f"{local}@d999.example")).ok
    assert not generator.prove(prepared, TransformResult(f"{local}@absent.example")).ok
    assert tuple(prepared.domains) == tuple(domains)
    rng = Random(42)
    expected_rng = Random(42)
    from ton.generators._identity_data import FAMILY_NAMES, GIVEN_NAMES

    for _ in range(100):
        given = expected_rng.choice(GIVEN_NAMES).lower()
        family = expected_rng.choice(FAMILY_NAMES).lower()
        assert (
            generator.generate(prepared, rng) == f"{given}.{family}@{expected_rng.choice(domains)}"
        )
