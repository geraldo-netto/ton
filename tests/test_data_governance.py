"""Repository-level data governance guards."""

from __future__ import annotations

import re
import subprocess
import traceback
from pathlib import Path
from random import Random
from typing import Any, ClassVar

import pytest

from ton import api
from ton._engine import Engine
from ton._proof import REDACTED, ProofFailure
from ton._proofcheck import ProofChecker
from ton._transforms import BaseTransform, TransformResult
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
    + b"|[A-Z]:\\\\Us"
    + b"ers\\\\"
    + b"|AK"
    + b"IA[0-9A-Z]{16}"
    + b"|gh"
    + b"[pousr]_[A-Za-z0-9]{20,}"
    + b"|xox"
    + b"[abprs]-[A-Za-z0-9-]{10,}"
    + b"|eyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}"
)


def _contains_private_or_secret(data: bytes) -> bool:
    """Scan raw bytes; NULs do not make a tracked file exempt."""
    return PRIVATE_OR_SECRET_RE.search(data) is not None


@pytest.mark.parametrize(
    "candidate",
    [
        b"C:" + b"\\Users\\" + b"person\\file.txt",
        b"AK" + b"IA" + b"1234567890ABCDEF",
        b"gh" + b"p_" + b"0123456789abcdefghijkl",
        b"xox" + b"b-" + b"1234567890-token",
        b"eyJ" + b"abcdefghijk.abcdefghijkl.abcdefghijkl",
    ],
)
def test_governance_pattern_detects_representative_credentials(candidate: bytes) -> None:
    assert _contains_private_or_secret(candidate)


def test_governance_scan_cannot_be_bypassed_with_nul_byte() -> None:
    assert _contains_private_or_secret(b"binary\x00/ho" + b"me/person/file")


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
        if _contains_private_or_secret(data):
            offenders.append(relative)
    assert offenders == []


def test_ci_actions_are_pinned_to_commit_shas() -> None:
    workflows = (REPO_ROOT / ".github" / "workflows").glob("*.y*ml")
    action_lines = [
        line
        for path in workflows
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.search(r"uses:\s+[^@\s]+@", line)
    ]

    assert action_lines
    assert all(re.search(r"@[0-9a-f]{40}\s+#\s+v\d", line) for line in action_lines)


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


class _LeakyProofTransform(BaseTransform):
    """Proof hook raising a message a plugin must not be able to publish."""

    type_name = "leaky_proof"
    config_keys: ClassVar[frozenset[str] | None] = frozenset()

    def prove(self, prepared: Any, before: Any, after: Any) -> Any:
        del prepared, before, after
        raise ValueError("private-proof-value")


LEAKY_CONFIG = {
    "rows": 1,
    "format": "$x$",
    "types": {"x": {"type": "string", "values": ["a"], "transforms": [{"type": "leaky_proof"}]}},
}


def test_redaction_hides_proof_hook_exception_text_everywhere() -> None:
    """Message, chained traceback and attribute must all stay clean (DG-004)."""
    with pytest.raises(api.ProofEvaluationError) as excinfo:
        list(
            api.generate(
                LEAKY_CONFIG,
                seed=1,
                transforms={"leaky_proof": _LeakyProofTransform()},
                proof_mode="all",
                redact_proof_failures=True,
            )
        )

    error = excinfo.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert "private-proof-value" not in str(error)
    assert "private-proof-value" not in rendered
    assert error.__cause__ is None
    assert error.cause is None
    # Safe structural context is retained.
    assert error.cause_type == "ValueError"
    assert "Transform proof" in str(error)
    assert "leaky_proof" in str(error)


def test_proof_hook_diagnostics_stay_complete_without_redaction() -> None:
    """Redaction is what removes plugin text; debugging is unaffected otherwise."""
    with pytest.raises(api.ProofEvaluationError) as excinfo:
        list(
            api.generate(
                LEAKY_CONFIG,
                seed=1,
                transforms={"leaky_proof": _LeakyProofTransform()},
                proof_mode="all",
            )
        )

    assert "private-proof-value" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None
