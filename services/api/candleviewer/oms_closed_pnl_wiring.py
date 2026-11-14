"""The closed-PnL comparison's divergence record over the order lane's audit writer (E29-S06 #981
slice 5c; 24 Sec.8.13 "The divergence record", Sec.15.5 `pnl.divergence_detected`).

`oms` may not import `audit` (C-3.3), so the record's action and actor are copied here and pinned
equal to the registry and to `oms_wiring.SYSTEM_ACTOR` by test, as `oms_stream_wiring` does. The
writer is the lane's own (`oms_wiring`, #913 L2), whose WAL the order audit shares: `strained`
reads its append failure and its buffer's depth first, so the comparison writes nothing into a
writer under strain and owes the record to a later pass (the orchestrator's ruling Q6 of
2026-11-05). `write` is the writer's unkeyed `emit`, durable or it raises (C-2.9), as `system:oms`,
severity `warning`, outcome `success`, its object the record (`closed_pnl_record`), and never
inside a store call.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from candleviewer.oms.closed_pnl_compare import DivergenceRecord
from candleviewer.oms_stream_wiring import AuditEmitter

#: 24 Sec.15.5's action, registered in `audit/actions.py` (a test pins the two equal).
DIVERGENCE_DETECTED: Final = "pnl.divergence_detected"
#: `oms_wiring.SYSTEM_ACTOR`, which this module cannot import (the runtime imports this one).
SYSTEM_ACTOR: Final = "system:oms"
#: PROPOSED: the records the writer holds uncommitted past which it is strained, two of its
#: flusher's batches (`AuditWriter`'s `flush_batch_size`, 500).
STRAIN_DEPTH: Final = 1000


@runtime_checkable
class StrainReadings(Protocol):
    """`AuditWriter`'s two strain readings: its append failure, its uncommitted records."""

    @property
    def append_failure_active(self) -> bool: ...
    @property
    def buffer_depth(self) -> int: ...


class DivergenceAudit:
    """`closed_pnl_compare.DivergenceWriter` over the lane's audit writer (module docstring)."""

    def __init__(self, writer: AuditEmitter, *, environment: str) -> None:
        self._writer, self._environment = writer, environment

    def strained(self) -> bool:
        """Its append failure or `STRAIN_DEPTH` records uncommitted; a writer that reads neither
        is taken as strained, so nothing is written into it."""
        w = self._writer
        if not isinstance(w, StrainReadings):
            return True
        return w.append_failure_active or w.buffer_depth >= STRAIN_DEPTH

    async def write(self, record: DivergenceRecord) -> None:
        await self._writer.emit(
            DIVERGENCE_DETECTED, actor_label=SYSTEM_ACTOR, actor_user_id=None,
            object_kind="closed_pnl_record", object_id=str(record.record_id), outcome="success",
            severity="warning", reason=record.reason, after_state=dict(record.after_state),
            request_id=None, env=self._environment,
        )  # fmt: skip
