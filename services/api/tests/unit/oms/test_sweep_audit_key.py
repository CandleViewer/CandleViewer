"""#4560: the unplaced-entry sweep's void record has a key of its own (C-2.9).

An entry's take-profit request record is keyed `(tp.modified, <stop id>)` (`oms/submit.py`'s
`_STOP_ACTIONS`; a stop-loss's is `sl.attached`), and an amend's request is keyed
`(sl.modified | tp.modified, <stop id>)`. A void keyed the same as a request would be deduped
against it and lost. The sweep names its voids by their reason, as the stop gate names its own
(`<reason>:<row id>`), so no void's record id is any request's.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from candleviewer.audit.writer import keyed_record_id
from candleviewer.oms.ports import KeyedRecord
from candleviewer.oms_wiring import OmsAudit, _sweep_audit
from candleviewer.storage.repositories.recorded_stops import SWEEP_REASON, StopKind, SweptStop

#: Every request record a stop row's id may carry: the entry's attach and an amend's.
_REQUESTS = ("sl.attached", "sl.modified", "tp.modified")


class _Audit:
    """Records what the hook writes, nothing else."""

    def __init__(self) -> None:
        self.records: list[KeyedRecord] = []

    async def write(self, record: KeyedRecord) -> None:
        self.records.append(record)


@pytest.mark.parametrize(
    ("kind", "action"), [("stop_loss", "sl.modified"), ("take_profit", "tp.modified")]
)
async def test_a_swept_voids_record_id_is_no_request_records_id_for_its_row(
    kind: StopKind, action: str
) -> None:
    stop = SweptStop(UUID(int=1), UUID(int=2), UUID(int=3), kind)
    audit = _Audit()

    await _sweep_audit(cast(OmsAudit, audit))((stop,))  # the hook needs `write` only

    [record] = audit.records
    assert (record.action, record.name) == (action, f"{SWEEP_REASON}:{stop.id}")
    requests = {keyed_record_id(request, str(stop.id)) for request in _REQUESTS}
    assert keyed_record_id(record.action, record.name) not in requests


async def test_a_sweep_run_again_over_the_same_row_writes_the_same_record_id() -> None:
    stop = SweptStop(UUID(int=1), UUID(int=2), UUID(int=3), "take_profit")
    first, again = _Audit(), _Audit()

    await _sweep_audit(cast(OmsAudit, first))((stop,))
    await _sweep_audit(cast(OmsAudit, again))((stop,))

    [one], [two] = first.records, again.records
    assert keyed_record_id(one.action, one.name) == keyed_record_id(two.action, two.name)
