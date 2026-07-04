"""Repository-level data governance guards."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from random import Random
from typing import Any

import pytest

from ton._engine import Engine
from ton._proof import REDACTED, ProofFailure
from ton._proofcheck import ProofChecker
from ton._transforms import TransformResult
from ton.generators import Generator
from ton.generators.base import coerce_int

REPO_ROOT = Path(__file__).resolve().parent.parent
_SENSITIVE_ASSIGNMENTS = (
    b"API[_-]?KEY",
    b"SEC" + b"RET",
    b"TOK" + b"EN",
    b"PASS" + b"WORD",
)
PRIVATE_OR_SECRET_RE = re.compile(
    b"/ho"
    + b"me/|/back"
    + b"ups/|"
    + rb"|".join(marker + rb"\s*[=:]" for marker in _SENSITIVE_ASSIGNMENTS)
    + b"|PRIVATE "
    + b"KEY|BEGIN "
    + b"RSA|BEGIN "
    + b"OPENSSH"
)


def test_tracked_text_files_do_not_contain_private_paths_or_secrets() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    offenders: list[str] = []
    for relative in result.stdout.splitlines():
        path = REPO_ROOT / relative
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        if PRIVATE_OR_SECRET_RE.search(data):
            offenders.append(relative)
    assert offenders == []


def test_proof_failure_redacted_masks_sensitive_fields() -> None:
    failure = ProofFailure(
        row=1,
        type_key="secret",
        stage="source",
        reference="string",
        reason="bad",
        value="sensitive-value",
        id_value="sensitive-id",
        spec={"type": "string", "values": ["sensitive-value"]},
    )
    redacted = failure.redacted()
    assert redacted.value == REDACTED
    assert redacted.id_value == REDACTED
    assert redacted.spec is None
    # Diagnostic fields survive.
    assert redacted.row == 1
    assert redacted.reference == "string"


def test_proof_failure_redacted_keeps_missing_id_value_none() -> None:
    failure = ProofFailure(
        row=1, type_key="v", stage="source", reference="string", reason="bad", value="x"
    )
    assert failure.redacted().id_value is None


def test_engine_redacts_retained_audit_failures() -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            del prepared, rng
            return "top-secret"

        def prove(self, prepared: Any, result: TransformResult) -> Any:
            from ton._proof import ProofResult

            del prepared, result
            return ProofResult(ok=False, reason="nope")

    engine = Engine.from_config(
        {"rows": 1, "format": "$v$", "types": {"v": {"type": "failing"}}},
        registry={"failing": FailingGenerator()},
        proof_mode="audit",
        redact_proof_failures=True,
    )
    list(engine)
    record = engine.proof_failures[0]
    assert record.value == REDACTED
    assert record.spec is None


def test_proof_checker_keeps_raw_failures_by_default() -> None:
    checker = ProofChecker(mode="audit", sample_rate=1, seed=None)
    checker._record_audit(
        ProofFailure(row=1, type_key="v", stage="source", reference="s", reason="r", value="raw")
    )
    assert checker.failures[0].value == "raw"


@pytest.mark.parametrize("raw", [3.9, True])
def test_coerce_int_rejects_non_integral_numerics(raw: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        coerce_int({"value": raw}, "value", type_name="test")


def test_coerce_int_accepts_integral_float() -> None:
    assert coerce_int({"value": 3.0}, "value", type_name="test") == 3
