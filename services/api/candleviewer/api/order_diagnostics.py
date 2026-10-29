"""`getOrderDiagnostics`' exchange records (E29-T07 #915, PR 1; 22 `OrderDiagnostics`,
`ExchangeCallRecord`; SR-E29-08, SR-E29-09; E29 threat model section 6, OM-I05, OM-I06).

An order's events carry, under `record`, the allow-listed record the exchange adapter built of
the call behind the step (`exchange.bybit.record`), which the store redacted before insert
(`storage.repositories.exchange_payload`). Each is served only after two checks on the way out,
and a record that fails either is never served: the read fails closed (`RecordRefused`, the
route's `503`), never a partial answer.

1. The store's redactor again: the stored record must be its own output, unchanged by a second
   pass. Anything the pass would mask (a key, a signature, a recv-window credential, a signed
   string echoed in a message) was not stored by the adapter's allow-list and is refused.
2. The contract's closed shape: the generated `ExchangeCallRecord`, strict and with no member it
   does not name, at every level. Only the members it validated are served.

Nothing here logs a value of a record (C-12.6): a refusal names the event and the check.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Any, Final

import structlog
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload
from candleviewer.storage.repositories.orders import OrderEventRow

__all__ = ["RECORD_KEY", "RecordRefused", "exchange_calls"]

#: The event payload's member holding the call's record (`oms.commands._record`).
RECORD_KEY: Final = "record"
#: The members the route computes from the event, which a stored record never names (#4997).
_COMPUTED: Final = frozenset({"event_id", "at"})


class RecordRefused(Exception):
    """A stored record the checks refuse (module docstring): names the event and the check."""

    def __init__(self, event_id: int, check: str) -> None:
        super().__init__(f"event {event_id}: {check}")
        self.event_id, self.check = event_id, check


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _call(event: OrderEventRow, record: object) -> dict[str, object]:
    if not isinstance(record, Mapping) or _COMPUTED & set(record):  # never its own link or time
        raise RecordRefused(event.id, "shape")
    stored = {RECORD_KEY: dict(record)}
    if redact_exchange_payload(stored) != stored:  # check 1: the redactor would change it
        raise RecordRefused(event.id, "redaction")
    at = event.event_ts.astimezone(UTC).isoformat(timespec="microseconds")
    candidate = {**record, "event_id": event.id, "at": at}
    try:  # check 2: the contract's closed shape, strictly
        shaped = api.ExchangeCallRecord.model_validate_json(json.dumps(candidate), strict=True)
    except (ValidationError, TypeError, ValueError):
        raise RecordRefused(event.id, "contract") from None
    return shaped.model_dump(mode="json", exclude_unset=True)


def exchange_calls(events: Sequence[OrderEventRow]) -> list[dict[str, object]]:
    """22 `OrderDiagnostics.exchange_calls`: each event's record, in the events' order (oldest
    first), linked by `event_id`; `RecordRefused` for any record the checks refuse, logged."""
    calls: list[dict[str, object]] = []
    for event in events:
        record = event.payload.get(RECORD_KEY)
        if record is None:
            continue
        try:
            calls.append(_call(event, record))
        except RecordRefused as refused:
            _log().error("oms_diagnostics_record_refused", event_id=event.id, check=refused.check)
            raise
    return calls
