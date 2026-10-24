"""E29-T04 (#913): the order-submission system stores take no principal, so no route may reach them.

`SubmissionStore` writes an order's first rows (its group and leg, the order, its recorded stops
and its replay anchor), `IdempotencyAnchorStore` finds and decides anchors (`record_outcome`, by
id), and `RecordedStopStore` records, settles and sweeps (`void_orphans`) the stops of any
account, each with no scope check: the OMS calls them through its M14 facades
(`SubmissionRepository`, `IdempotencyAnchorRepository`, `RecordedStopRepository`) after its own
admission, and the trade-group builders the first persist reuses (`require_live`, `group_row`,
`leg_row`, `in_order`, `insert_group_statement`) write groups and legs the same way. A reference
to that surface anywhere else in `candleviewer` (an `api/` router, a WS topic, a job) fails here;
each consumer PR (E29-T04's slice 2b and slice 3 among them) adds its file to `ALLOWED` and is
reviewed as an RBAC bypass first (C-12.4; the `test_trade_group_store_callers.py` precedent,
CR-2A-04, SEC-2A-04).

Slice 2b: `oms/fakes.py` implements the three stores in memory for the OMS's unit suites, under
the same contract as the Postgres adapters (`tests/unit/oms/submission_contract.py`). It is a test
double: it holds no principal and checks none, as the adapters do not, and no composition root
wires it (slice 3's wiring binds the Postgres adapters), so it opens no route to them.
`oms/idempotency.py` reads and decides anchors for the principal it is handed, which slice 3's
route takes from the authenticated session after its admission (scope and arm, 22 Idempotency),
never from the request: `find` is keyed by that principal, so another's key reads as missing
(SR-E29-07), and an anchor is decided only by the id that read returned.
`oms/commands.py`, B1's command port, records and settles the stop requests of `attach_stop`
through `RecordedStopRepository`: only B1's `sl_pending` invoke calls it, for the order whose
machine runs it, and it reads that order's row by the account the command names (OM-I02); no route
reaches it, and slice 3's routes reach B1 only through the OMS facade, after their admission.
`oms/submit.py`, the submission pipeline, builds an order's first persist (`create_first`, through
B1's step writer) and decides its anchor through `oms/idempotency.py`: its principal is the one
slice 3's route took from the authenticated session after its admission, never a request field,
every row it writes is the request's own account's (`TradingAccounts` resolved it by id alone,
SR-E27-21), and no route reaches it but that one, after scope, the arm token and the replay lookup.
`oms_wiring.py` (slice 3E, C-12.4) builds the Postgres adapters and the M14 facades over them
for the OMS runtime alone, and mounts no route; its startup sweep calls `void_orphans` once per
account of the process's own environment, before anything hydrates (20 Sec.6.2).
`oms/stop_resolution.py`, S3-H's complete read, answers, puts in force, replaces and voids the
waiting rows of one key through `RecordedStopRepository`, with the account the key names (C-12.4):
its callers are the stop-request gate and the startup pass (H3), after the submit pipeline's or
B1's own admission, and no route reaches it.
`oms/stop_gate.py`, that gate (H3), reads a key's waiting rows, an account's waiting keys and the
database's clock through `RecordedStopRepository`, and runs the complete read: a key is the
admitted request's (`submit.py`) or the stored order's (`commands.py`), an account the startup
sweep's, of the process's environment (C-2.11), resolved through the command port's
`TradingAccounts` before any venue read, and no route reaches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
#: The system ports, their adapters, the M14 facades, their principal-less methods and the
#: trade-group builders the first persist made public.
NAMES = re.compile(
    r"(?<!\w)(SubmissionStore|SqlAlchemySubmissionStore|SubmissionRepository"
    r"|IdempotencyAnchorStore|SqlAlchemyIdempotencyAnchorStore|IdempotencyAnchorRepository"
    r"|RecordedStopStore|SqlAlchemyRecordedStopStore|RecordedStopRepository"
    r"|create_first|record_outcome|void_orphans"
    r"|require_live|group_row|leg_row|in_order|insert_group_statement)\b"
)
ALLOWED = frozenset(
    {
        "oms/commands.py",
        "oms/fakes.py",
        "oms/idempotency.py",
        "oms/order_steps.py",
        "oms/repository.py",
        "oms/stop_gate.py",
        "oms/stop_resolution.py",
        "oms/submit.py",
        "oms_wiring.py",
        "storage/repositories/idempotency_anchors.py",
        "storage/repositories/idempotency_anchors_sqlalchemy.py",
        "storage/repositories/recorded_stops.py",
        "storage/repositories/recorded_stops_sqlalchemy.py",
        "storage/repositories/submissions.py",
        "storage/repositories/submissions_sqlalchemy.py",
        "storage/repositories/trade_groups_sqlalchemy.py",
    }
)


def test_the_order_submission_stores_are_referenced_only_by_the_oms_and_the_stores() -> None:
    users = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*.py")
        if NAMES.search(p.read_text(encoding="utf-8"))
    }
    assert users == ALLOWED


def test_the_pattern_matches_the_names_and_not_their_longer_neighbours() -> None:
    assert NAMES.search("store: SubmissionStore") and NAMES.search("await s.void_orphans(scope)")
    assert NAMES.search("RecordedStopRepository(store)") and NAMES.search("group_row(m)")
    assert not NAMES.search("except SubmissionStoreError:") and not NAMES.search("in_order_of()")
    assert not NAMES.search("void_orphans_statement(scope, at)")  # the statement is the adapter's
    assert not NAMES.search("FirstPersist(anchor=anchor)")  # the request's rows, not the port
