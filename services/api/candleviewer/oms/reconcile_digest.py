"""The account's latest reconciliation pass as a digest (E29-S07 #1028, BQ-9; 24-internal-schemas.md
Sec.8.5 "The digest", 22 `getReconciliationDigest`, `ReconciliationDigest`). Pure, but for the
store's one log line: no I/O, no clock, no interpreter.

`digest_of` cuts a pass's `oms.reconcile` record (`stage: finished`, its `after_state` as
`reconcile_report.audit_state` writes it) to what a client reads: the pass's id, trigger and
result, its `gap_window` and `confirmed_at` (the window's end, when the pass read the exchange),
each list of the report but `errors` as the report holds it (order link ids, `exec_id`s, symbols),
`position_drift` with both values, and `unprotected`, the symbols of its `no_record_in_force`
errors (BQ-9 of #914). Each list is cut to its first `MAX_DIGEST_ITEMS`, and `counts` gives each
full length (C-2.18); each entry's text is cut to `MAX_ENTRY_TEXT`, an empty one named, as the
report names its errors' (22 `ReconciliationDigestIds`). Never an error's class, a credential, an
exchange message or a payload (C-12.6). `confirmed_us` tells a pass that read the exchange from one
whose reads were lost, which confirmed nothing and is digested by no caller (`DigestRecords`).

`ReconcileDigests` keeps the latest digest per account, keyed by the account's id (C-2.11), as its
JSON document, so no reader changes what is kept: at most `MAX_DIGEST_ACCOUNTS`, the least recently
reported dropped first, logged once with the count and no id (C-2.18). A record the builder refuses
leaves the account with none (fail closed: the read is a `404`), never the pass before it. In
memory only: after a restart it holds none until the account's next pass reports. Written and read
on the serving loop.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import structlog

from .reconcile_report import EMPTY_TEXT, NO_RECORD_IN_FORCE

__all__ = [
    "DIGEST_LISTS",
    "MAX_DIGEST_ACCOUNTS",
    "MAX_DIGEST_ITEMS",
    "MAX_ENTRY_TEXT",
    "ReconcileDigests",
    "confirmed_us",
    "digest_of",
]

#: The report's lists a digest carries as they are (24 Sec.8.5 "The report"), in its order.
DIGEST_LISTS: Final = (
    "corrected", "resolved_from_history", "abandoned", "newly_unknown", "untracked", "anomalies",
    "held", "foreign_stops", "unpaired", "sl_repaired", "sl_restored", "sl_restore_refused",
    "sl_tighter",
)  # fmt: skip
#: The entries a digest's list holds at most (22 `ReconciliationDigestIds`).
MAX_DIGEST_ITEMS: Final = 256
#: An entry's longest text (22 `ReconciliationDigestIds`' `maxLength`), the report's own cap.
MAX_ENTRY_TEXT: Final = 64
#: The accounts `ReconcileDigests` keeps a digest for, the least recently reported dropped first.
MAX_DIGEST_ACCOUNTS: Final = 4096
_DRIFT: Final = ("symbol", "position_idx", "side_before", "qty_before", "side_after", "qty_after")
#: The record's members a digest reads (`audit_state` writes each): a record without one is not a
#: pass's, a `ValueError`.
_READ: Final = (
    "pass_id", "trigger", "result", "gap_window", *DIGEST_LISTS, "position_drift", "errors",
)  # fmt: skip
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _at(us: object) -> str:
    """Microseconds since the epoch as 22's UTC `date-time`."""
    if type(us) is not int:
        raise ValueError("a report's window is two integers of microseconds")
    at = _EPOCH + timedelta(microseconds=us)
    return at.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _listed(state: Mapping[str, object], name: str) -> Sequence[object]:
    if name not in state:
        raise ValueError("a report's field is missing")
    value = state[name]
    if not isinstance(value, list | tuple):
        raise ValueError("a report's field is a list")
    return value


def _window(state: Mapping[str, object]) -> tuple[int, int]:
    window = _listed(state, "gap_window")
    if len(window) == 2:
        start, end = window
        if type(start) is int and type(end) is int:
            return start, end
    raise ValueError("a report's window is two integers of microseconds")


def _entry(value: object) -> str:
    """A list entry as 22 `ReconciliationDigestIds` holds it (module docstring)."""
    return str(value)[:MAX_ENTRY_TEXT] or EMPTY_TEXT


def _drifted(entry: object) -> dict[str, object]:
    if not isinstance(entry, Mapping) or any(key not in entry for key in _DRIFT):
        raise ValueError("a drift entry is not one the report writes")
    return {key: entry[key] for key in _DRIFT}


def confirmed_us(state: Mapping[str, object]) -> int | None:
    """When the pass of the record `state` read the exchange (its window's end, the digest's
    `confirmed_at`), in microseconds; None for a pass whose reads were lost, which confirmed
    nothing: `reconcile_phases`' report of one has an empty window and an error at step 1. A
    `ValueError` for a record that is not one `audit_state` writes."""
    start, end = _window(state)
    if start == end and any(
        isinstance(error, Mapping) and error.get("step") == "1"
        for error in _listed(state, "errors")
    ):
        return None
    return end


def digest_of(account_id: UUID, state: Mapping[str, object]) -> dict[str, object]:
    """The digest of the record `state` (module docstring); a `ValueError` for a record that is not
    one `audit_state` writes, a member missing included."""
    if any(name not in state for name in _READ):
        raise ValueError("a record audit_state wrote has every member")
    start, end = _window(state)
    lists = {name: [_entry(entry) for entry in _listed(state, name)] for name in DIGEST_LISTS}
    drift = [_drifted(entry) for entry in _listed(state, "position_drift")]
    unprotected = [
        _entry(error["subject"])
        for error in _listed(state, "errors")
        if isinstance(error, Mapping) and error.get("kind") == NO_RECORD_IN_FORCE
        if error.get("subject")
    ]
    full: dict[str, list[Any]] = {**lists, "position_drift": drift, "unprotected": unprotected}
    # The record's own `result` member (`audit_state`'s `report.result`, a `PassResult` the server
    # computes), never an exchange envelope: the marker records SR-040's false positive.
    result = state["result"]  # nosemgrep: cv-untrusted-exchange-response reason=the-oms.reconcile-records-own-result-member-not-an-exchange-envelope-SR-040-#1028 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    return {
        "exchange_account_id": str(account_id),
        "pass_id": str(state["pass_id"]),
        "trigger": state["trigger"],
        "result": result,
        "gap_window": {"from": _at(start), "to": _at(end)},
        "confirmed_at": _at(end),
        **{name: entries[:MAX_DIGEST_ITEMS] for name, entries in full.items()},
        "counts": {name: len(entries) for name, entries in full.items()},
    }


class ReconcileDigests:
    """The latest digest per account (module docstring): `keep` as each pass's record is written,
    `latest` for the route, both on the serving loop."""

    def __init__(self, *, max_accounts: int = MAX_DIGEST_ACCOUNTS) -> None:
        self._max = max_accounts
        self._kept: OrderedDict[UUID, str] = OrderedDict()
        self._overflowed = False

    def keep(self, account_id: UUID, state: Mapping[str, object]) -> None:
        """The account's digest becomes the one of `state`, its pass's record; one the builder
        refuses leaves the account with none (it raises), never the pass before it."""
        self._kept.pop(account_id, None)
        self._kept[account_id] = json.dumps(digest_of(account_id, state), separators=(",", ":"))
        while len(self._kept) > self._max:
            self._kept.popitem(last=False)
            if not self._overflowed:
                self._overflowed = True
                _log().warning("reconcile_digests_full", accounts=len(self._kept))

    def latest(self, account_id: UUID) -> str | None:
        """The account's digest as its JSON document, or None when no pass has reported since the
        process started (or it was dropped past the bound)."""
        return self._kept.get(account_id)
