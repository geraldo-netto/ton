"""Proof-check collaborator extracted from the engine (ARCH-001).

:class:`ProofChecker` owns everything the engine used to inline for
``--proof-check``: mode/sample-rate validation, the audit failure list,
the per-row sampling decision, building :class:`~ton._proof.ProofFailure`
records from generator and transform proofs, and the structured logging.

The engine keeps only a thin seam: it feeds each rendered field's
source/transform trace to :meth:`ProofChecker.evaluate` and raises
``ProofError`` when a strict-mode failure is returned. Keeping the raise
in the engine avoids a circular import (``ProofError`` subclasses the
engine's ``TemplateError``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import PreparedField, ProofFailure, TransformStep
from ._transforms import TransformResult

#: Upper bound on the number of detailed audit failures retained in
#: memory. Beyond this the total count and per-type tallies keep
#: growing, but no further full ProofFailure records (with their copied
#: spec dicts) are stored, so a long run with systematic failures cannot
#: exhaust memory (SCAL-001).
MAX_AUDIT_SAMPLE = 1000
PROOF_MODES = ("off", "sample", "all", "audit")
ProofFailureSink = Callable[[ProofFailure], None]


class ProofFailureSinkError(Exception):
    """A configured proof-failure sink could not accept a record."""


class ProofChecker:
    """Own the proof-check state and failure-building for one engine."""

    def __init__(
        self,
        *,
        mode: str,
        sample_rate: int,
        seed: int | None,
        redact: bool = False,
        failure_sink: ProofFailureSink | None = None,
    ) -> None:
        self.mode = validate_proof_mode(mode)
        self.sample_rate = validate_proof_sample_rate(sample_rate)
        self.seed = seed
        #: When set, retained audit records are masked (DG-002).
        self.redact = redact
        #: Optional bounded-memory destination for every audit failure.
        self.failure_sink = failure_sink
        #: Bounded sample of detailed failures (see MAX_AUDIT_SAMPLE).
        self.failures: list[ProofFailure] = []
        #: Total audit failures seen, independent of the sample cap.
        self.failure_count = 0
        #: Per-type total audit failures, for provenance attribution.
        self.failure_counts: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def reset(self) -> None:
        """Clear collected audit failures before a fresh iteration."""
        self.failures.clear()
        self.failure_count = 0
        self.failure_counts.clear()

    def should_check(self, rows_emitted: int) -> bool:
        if self.mode == "off":
            return False
        if self.mode == "sample":
            return (rows_emitted + 1) % self.sample_rate == 0
        return True

    def evaluate(
        self,
        type_key: str,
        field: PreparedField,
        source_result: TransformResult,
        steps: tuple[TransformStep, ...],
        *,
        rows_emitted: int,
        spec: Mapping[str, Any],
    ) -> ProofFailure | None:
        """Record proof failures for one rendered field.

        Returns the failure the engine should raise on (strict ``all``/
        ``sample`` modes); in ``audit`` mode failures are collected and
        ``None`` is returned so iteration continues.
        """
        if not self.should_check(rows_emitted):
            return None
        failures = self.build_failures(
            type_key,
            field,
            source_result,
            steps,
            row=rows_emitted + 1,
            spec=spec if self.mode != "audit" else None,
        )
        if not failures:
            return None
        if self.mode == "audit":
            for failure in failures:
                if self.failure_sink is not None or len(self.failures) < MAX_AUDIT_SAMPLE:
                    failure = replace(failure, spec=dict(spec))
                self._record_audit(failure)
                self._log_failure(failure)
            return None
        self._log_failure(failures[0])
        return failures[0]

    def _record_audit(self, failure: ProofFailure) -> None:
        """Tally, retain a bounded sample, and stream every audit failure."""
        self.failure_count += 1
        self.failure_counts[failure.type_key] = self.failure_counts.get(failure.type_key, 0) + 1
        visible = failure.redacted() if self.redact else failure
        if len(self.failures) < MAX_AUDIT_SAMPLE:
            self.failures.append(visible)
        if self.failure_sink is not None:
            try:
                self.failure_sink(visible)
            except ProofFailureSinkError:
                raise
            except Exception as exc:
                raise ProofFailureSinkError(str(exc)) from exc

    def build_failures(
        self,
        type_key: str,
        field: PreparedField,
        source_result: TransformResult,
        steps: tuple[TransformStep, ...],
        *,
        row: int = 0,
        spec: Mapping[str, Any] | None = None,
    ) -> tuple[ProofFailure, ...]:
        """Return every proof failure for a field's source + transform trace."""
        failures = list(self._source_failures(type_key, field, source_result, row, spec))
        for step in steps:
            proof = step.prepared.transform.prove(
                step.prepared.prepared,
                step.before,
                step.after,
            )
            if not proof.ok:
                failures.append(
                    self._make_failure(
                        type_key=type_key,
                        stage="transform",
                        reference=step.prepared.transform.type_name,
                        reason=proof.reason,
                        result=step.after,
                        row=row,
                        spec=spec,
                    )
                )
        return tuple(failures)

    def log_summary(self) -> None:
        """Emit the end-of-run proof summary when checking is enabled."""
        if not self.enabled:
            return
        _logger.info(
            "proof_check_summary mode=%s failures=%d",
            self.mode,
            self.failure_count,
            extra={
                "event": LogEvent.PROOF_CHECK_SUMMARY.value,
                "mode": self.mode,
                "failures": self.failure_count,
            },
        )

    def _source_failures(
        self,
        type_key: str,
        field: PreparedField,
        source_result: TransformResult,
        row: int,
        spec: Mapping[str, Any] | None,
    ) -> tuple[ProofFailure, ...]:
        if not field.uses_source:
            return ()
        proof = field.generator.prove(field.source_prepared, source_result)
        if proof.ok:
            return ()
        return (
            self._make_failure(
                type_key=type_key,
                stage="source",
                reference=field.generator.type_name,
                reason=proof.reason,
                result=source_result,
                row=row,
                spec=spec,
            ),
        )

    def _make_failure(
        self,
        *,
        type_key: str,
        stage: str,
        reference: str,
        reason: str,
        result: TransformResult,
        row: int,
        spec: Mapping[str, Any] | None,
    ) -> ProofFailure:
        return ProofFailure(
            row=row,
            type_key=type_key,
            stage=stage,
            reference=reference,
            reason=reason,
            value=result.value,
            id_value=result.id_value,
            seed=self.seed,
            spec=dict(spec) if spec is not None else None,
        )

    @staticmethod
    def _log_failure(failure: ProofFailure) -> None:
        _logger.warning(
            "proof_check_failed row=%d type_key=%s stage=%s reference=%s",
            failure.row,
            failure.type_key,
            failure.stage,
            failure.reference,
            extra={
                "event": LogEvent.PROOF_CHECK_FAILED.value,
                "row": failure.row,
                "type_key": failure.type_key,
                "stage": failure.stage,
                "reference": failure.reference,
                "reason": failure.reason,
            },
        )


def validate_proof_mode(proof_mode: str) -> str:
    if proof_mode not in PROOF_MODES:
        raise ValueError("proof_mode must be 'off', 'sample', 'all', or 'audit'")
    return proof_mode


def validate_proof_sample_rate(proof_sample_rate: int) -> int:
    parsed = int(proof_sample_rate)
    if parsed < 1:
        raise ValueError("proof_sample_rate must be >= 1")
    return parsed
