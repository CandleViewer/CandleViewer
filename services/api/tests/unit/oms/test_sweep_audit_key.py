"""#4560: the unplaced-entry sweep's void record has a key of its own (C-2.9).

An entry's stop request record is keyed `(sl.modified | tp.modified, <stop id>)`; a void keyed the
same would be deduped against it and lost. The sweep names its voids by their reason, as the stop
gate names its own (`<reason>:<row id>`).
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from candleviewer.oms.ports import KeyedRecord
from candleviewer.oms_wiring import SWEEP_REASON, OmsAudit, _sweep_audit
from candleviewer.storage.repositories.recorded_stops import StopKind, SweptStop


class _Audit:
    """Records what the hook writes, nothing else."""

    def __init__(self) -> None:
        self.records: list[KeyedRecord] = []

    async def write(self, record: KeyedRecord) -> None:
        self.records.append(record)


@pytest.mark.parametrize(
    ("kind", "action"), [("stop_loss", "sl.modified"), ("take_profit", "tp.modified")]
)
async def test_a_swept_void_is_keyed_by_its_reason_never_as_the_rows_request(
    kind: StopKind, action: str
) -> None:
    stop = SweptStop(UUID(int=1), UUID(int=2), UUID(int=3), kind)
    audit = _Audit()

    await _sweep_audit(cast(OmsAudit, audit))((stop,))  # the hook needs `write` only

    [record] = audit.records
    assert (record.action, record.name) == (action, f"{SWEEP_REASON}:{stop.id}")
    assert record.name != str(stop.id)  # the entry's stop request record's key (oms/submit.py)
