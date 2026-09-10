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
from ._scalars import coerce_int
from ._specsnapshot import snapshot_spec
from ._steps import OperationError
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


class ProofHookError(RuntimeError):
    """A generator or transform proof hook raised unexpectedly."""

    def __init__(self, stage: str, reference: str, cause: Exception) -> None:
        if isinstance(cause, OperationError) and cause.stage.endswith(" proof"):
            stage = cause.stage.removesuffix(" proof").lower()
            reference, cause = cause.reference, cause.cause
        self.stage = stage
        self.reference = reference
        self.cause = cause
        super().__init__(str(cause))


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
        self.failure_sink: ProofFailureSink | None = None
        self.set_failure_sink(failure_sink)
        #: Bounded sample of detailed failures (see MAX_AUDIT_SAMPLE).
        self.failures: list[ProofFailure] = []
        #: Total audit failures seen, independent of the sample cap.
        self.failure_count = 0
        #: Per-type total audit failures, for provenance attribution.
        self.failure_counts: dict[str, int] = {}
        #: Audit-facing spec copies, one per field (ARCH-006).
        self._audit_specs: dict[str, Mapping[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def reset(self) -> None:
        """Clear collected audit failures before a fresh iteration."""
        self.failures.clear()
        self.failure_count = 0
        self.failure_counts.clear()

    def set_failure_sink(self, failure_sink: ProofFailureSink | None) -> None:
        """Validate and install the destination for streamed audit failures."""
        if failure_sink is not None and self.mode != "audit":
            raise ValueError("proof_failure_sink requires proof_mode='audit'")
        if failure_sink is not None and not callable(failure_sink):
            raise TypeError("proof_failure_sink must be callable")
        self.failure_sink = failure_sink

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
            retained = self._audit_spec(type_key, spec)
            for failure in failures:
                if self.failure_sink is not None or len(self.failures) < MAX_AUDIT_SAMPLE:
                    failure = replace(failure, spec=retained)
                visible = self._record_audit(failure)
                self._log_failure(visible)
            return None
        visible = failures[0].redacted() if self.redact else failures[0]
        self._log_failure(visible)
        return visible

    def _audit_spec(self, type_key: str, spec: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return this field's audit-facing spec copy, created once per engine.

        Separate from the engine's snapshot so a sink that mutates what it
        receives cannot reach the specs generation prepared from, and cached
        per field so every failure shares one object -- the audit writer keys
        its fingerprint cache on that identity (ARCH-006, PERF-003).
        """
        retained = self._audit_specs.get(type_key)
        if retained is None:
            retained = snapshot_spec(spec, immutable=True)
            self._audit_specs[type_key] = retained
        return retained

    def _record_audit(self, failure: ProofFailure) -> ProofFailure:
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
        return visible

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
            try:
                proof = step.prepared.transform.prove(
                    step.prepared.prepared,
                    step.before,
                    step.after,
                )
            except Exception as exc:
                raise ProofHookError("transform", step.prepared.transform.type_name, exc) from exc
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
        failures: list[ProofFailure] = []
        if field.uses_source:
            try:
                proof = field.generator.prove(field.source_prepared, source_result)
            except Exception as exc:
                raise ProofHookError("source", field.generator.type_name, exc) from exc
            if not proof.ok:
                failures.append(
                    self._make_failure(
                        type_key=type_key,
                        stage="source",
                        reference=field.generator.type_name,
                        reason=proof.reason,
                        result=source_result,
                        row=row,
                        spec=spec,
                    )
                )
        return tuple(failures)

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
            },
        )


def validate_proof_mode(proof_mode: str) -> str:
    if proof_mode not in PROOF_MODES:
        raise ValueError("proof_mode must be 'off', 'sample', 'all', or 'audit'")
    return proof_mode


def validate_proof_sample_rate(proof_sample_rate: int) -> int:
    parsed = coerce_int(
        {"proof_sample_rate": proof_sample_rate}, "proof_sample_rate", type_name="proof"
    )
    if parsed < 1:
        raise ValueError("proof_sample_rate must be >= 1")
    return parsed
