"""The closed-PnL divergence record over the order lane's audit writer (E29-S06 #981 slice 5c;
`oms_closed_pnl_wiring`): the action and actor pinned to the registry and the runtime, the exact
record a divergence writes, its after-state through the real `redact()` with every key kept, a real
`AuditWriter` built and its strain read before any emit (the orchestrator's ruling Q6)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer import oms_closed_pnl_wiring as wiring
from candleviewer import oms_wiring
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditWriter
from candleviewer.oms.closed_pnl_compare import (
    DIVERGENCE,
    VENUE_MISSING,
    DivergenceRecord,
    Tolerance,
    after_state,
)
from candleviewer.storage.repositories.closed_pnl import ClosedPnlRecordRow, record_id
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.audit.audit_waits import virtual

ACCOUNT, T0 = UUID(int=0xA1), datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
#: 24 Sec.15.5's after-state: the record's account, symbol and venue order id, the figures, their
#: difference and the tolerance, with its floor (PROPOSED, Sec.19.138).
KEYS = {
    "account_id", "symbol", "exchange_order_id", "closed_pnl", "local_net_pnl", "gross_pnl",
    "fee_pnl", "funding_pnl", "difference", "tolerance", "tolerance_floor",
}  # fmt: skip
ROW = ClosedPnlRecordRow(
    id=record_id(ACCOUNT, "x1"), exchange_account_id=ACCOUNT, exchange_order_id="x1",
    symbol="ETHUSDT", side="long", position_idx=0, trade_group_id=None, qty=Decimal(3),
    avg_entry_price=Decimal(1195), avg_exit_price=Decimal(1180), leverage=Decimal(10),
    closed_pnl=Decimal("-47.4065323"), gross_pnl=Decimal(-45), fee_pnl=Decimal("-4.275"),
    funding_pnl=Decimal(0), opened_at=T0, closed_at=T0, venue_created_at=T0, settled_at=T0,
    final_at=None, divergent=False, audited_local_net=None, audited_closed_pnl=None,
    updated_at=T0,
)  # fmt: skip
STATE = after_state(
    ROW, Decimal("-49.275"), Decimal("-1.8684677"), Tolerance(Decimal("1e-8"), Decimal("0.01"))
)


class Emitter:
    """The writer's `emit`, each call kept, and its two strain readings."""

    def __init__(self, *, failing: bool = False, depth: int = 0) -> None:
        self.append_failure_active, self.buffer_depth = failing, depth
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.calls.append((action, fields))


def test_the_action_and_the_actor_are_the_registrys_and_the_runtimes() -> None:
    assert wiring.DIVERGENCE_DETECTED in AUDIT_ACTIONS
    assert wiring.DIVERGENCE_DETECTED == "pnl.divergence_detected"
    assert wiring.SYSTEM_ACTOR == oms_wiring.SYSTEM_ACTOR


@virtual
@pytest.mark.parametrize("reason", [DIVERGENCE, VENUE_MISSING])
async def test_a_record_is_the_writers_unkeyed_emit_as_system_oms_of_its_object(
    reason: Any,
) -> None:
    """D10: the actor, severity, outcome, reason and object 24 Sec.15.5 names, nothing more."""
    emitter = Emitter()
    await wiring.DivergenceAudit(emitter, environment="demo").write(
        DivergenceRecord(ROW.id, reason, STATE)
    )
    assert emitter.calls == [
        (
            "pnl.divergence_detected",
            {
                "actor_label": "system:oms", "actor_user_id": None,
                "object_kind": "closed_pnl_record", "object_id": str(ROW.id),
                "outcome": "success", "severity": "warning", "reason": reason,
                "after_state": STATE, "request_id": None, "env": "demo",
            },
        )
    ]  # fmt: skip


def test_the_after_state_has_exactly_its_keys_and_redact_keeps_every_one() -> None:
    """Money as text, the signed difference local - venue; no key a redaction fragment matches."""
    assert set(STATE) == KEYS
    assert redact(STATE) == STATE
    assert STATE["difference"] == "-1.8684677" and STATE["local_net_pnl"] == "-49.275"
    assert (STATE["closed_pnl"], STATE["tolerance"], STATE["tolerance_floor"]) == (
        "-47.4065323", "1E-8", "0.01",
    )  # fmt: skip


def test_a_real_writer_builds_the_record_and_keeps_its_after_state(tmp_path: Path) -> None:
    """`AuditWriter.build`, `emit`'s validating half: the action registered, the state redacted."""
    writer = AuditWriter(FakeAuditRepository(), str(tmp_path / "lane.wal"))
    built = writer.build(
        wiring.DIVERGENCE_DETECTED, actor_label=wiring.SYSTEM_ACTOR, after_state=STATE,
        object_kind="closed_pnl_record", object_id=str(ROW.id), reason=DIVERGENCE,
    )  # fmt: skip
    assert built.after_state == STATE
    assert isinstance(writer, wiring.StrainReadings)


@pytest.mark.parametrize(
    ("failing", "depth", "strained"),
    [
        (False, 0, False),
        (False, wiring.STRAIN_DEPTH - 1, False),
        (False, wiring.STRAIN_DEPTH, True),
        (True, 0, True),
    ],
)
def test_the_writer_is_strained_by_an_append_failure_or_a_deep_buffer(
    failing: bool, depth: int, strained: bool
) -> None:
    audit = wiring.DivergenceAudit(Emitter(failing=failing, depth=depth), environment="demo")
    assert audit.strained() is strained


def test_a_writer_that_reads_no_strain_is_taken_as_strained() -> None:
    class Bare:
        async def emit(self, action: str, **fields: Any) -> None:
            raise AssertionError("never written into")

    assert wiring.DivergenceAudit(Bare(), environment="demo").strained() is True
