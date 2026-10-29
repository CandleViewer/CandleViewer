"""Contract (#913, E29-T04): the recorded stop's storage, `21-database-schema.md` section 3.3.11.

Ruling 1 on G-6 (#3972) gives E29-T04's contract PR the table that `24-internal-schemas.md`
section 8.8 rule 6 describes: per position and per side a stop request sets, one row per stop the
OMS requests, written ahead of the request and never from a read; one request in flight per
position and one row in force per side; a row that ends with its position; the TP/SL order it
binds, released once; the read that resolves a request left unanswered; no DELETE or TRUNCATE;
and its audit link. Read from the document, never from a copy, and held to the `orders` table it
sits beside, so the two keep one vocabulary.
"""

from __future__ import annotations

import inspect
import re
from typing import get_args

import pytest

from candleviewer.account_health_wiring import AccountHealthRuntime
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.oms import stream_consumer
from candleviewer.oms.ports import NoReconciliation
from candleviewer.oms.stream_consumer import REAPPLY_TIMEOUT_S, Outcome
from candleviewer.oms_stream_wiring import StreamWiring
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW

_PLAN = OPENAPI_SPEC_PATH.parent
_DOC = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
_INTERNAL_DOC = (_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
_ARCH = (_PLAN / "20-architecture.md").read_text(encoding="utf-8")
_SECTION = _DOC.split("#### 3.3.11 `recorded_stops`", 1)[1].split("\n### 3.4 ", 1)[0]
_TABLE_DDL = _SECTION.split("CREATE TABLE recorded_stops (", 1)[1].split("\n);", 1)[0]
_GUARD = _SECTION.split("CREATE FUNCTION rs_guard()", 1)[1].split("```", 1)[0]
_ORDERS = _DOC.split("#### 3.3.4 `orders`", 1)[1].split("#### 3.3.5 ", 1)[0]
#: The request's values: every column but `status`, the binding and the three later times.
_REQUEST = (
    "id exchange_account_id symbol position_idx position_side kind source order_id tpsl_mode "
    "trigger_price size trailing_distance trailing_active_price audit_record_id actor_user_id "
    "created_at"
).split()
_COLUMNS = [*_REQUEST[:13], "exchange_order_id", "status", *_REQUEST[13:]]
_COLUMNS += ["answered_at", "in_force_at", "closed_at", "released_at", "position_marker"]


def _words(text: str) -> str:
    return " ".join(text.split())


def _missing(text: str, *statements: str) -> list[str]:
    return [statement for statement in statements if statement not in text]


def _check(sql: str, name: str) -> str:
    """The body of CHECK `name` in `sql`, on one line."""
    [body] = re.findall(rf"CONSTRAINT {name} +CHECK \((.*?)\)(?:,\n|\n\Z|$)", sql, re.DOTALL)
    return _words(body)


def _listed(sql: str, name: str, column: str) -> list[str]:
    """The values of `column IN (...)` in CHECK `name`."""
    [values] = re.findall(rf"{column} IN \(([^)]*)\)", _check(sql, name))
    return [value.strip("' ") for value in values.split(",")]


def _unique_index(name: str) -> tuple[str, str]:
    """The key and the predicate of the partial unique index `name`."""
    [(key, predicate)] = re.findall(
        rf"CREATE UNIQUE INDEX {name} +ON recorded_stops \(([^)]*)\)\n +WHERE (.*);", _SECTION
    )
    return str(key), str(predicate)


def test_the_table_has_the_columns_its_column_list_names() -> None:
    declared = _TABLE_DDL.split("\n  CONSTRAINT ", 1)[0]
    assert [line.split()[0] for line in declared.strip().splitlines()] == _COLUMNS
    rows = re.findall(r"^\| `([a-z_]+)` +\|", _SECTION, re.MULTILINE)
    assert rows == _COLUMNS
    numeric = {"trigger_price", "size", "trailing_distance", "trailing_active_price"}
    typed = {line.split()[0] for line in _TABLE_DDL.splitlines() if "numeric(38,18)" in line}
    assert typed == numeric  # the type of the `orders` prices and quantities
    assert re.search(r"^ +price +numeric\(38,18\),$", _ORDERS, re.MULTILINE)


@pytest.mark.parametrize(
    ("name", "column", "values"),
    [
        ("rs_side", "position_side", ["Buy", "Sell"]),
        ("rs_kind", "kind", ["stop_loss", "take_profit"]),
        ("rs_source", "source", ["entry_attach", "trading_stop", "restore"]),
        ("rs_mode", "tpsl_mode", ["Full", "Partial"]),
        ("rs_status", "status", ["pending", "in_force", "replaced", "ended", "void"]),
    ],
)
def test_each_closed_column_admits_exactly_its_values(
    name: str, column: str, values: list[str]
) -> None:
    assert _listed(_TABLE_DDL, name, column) == values


def test_the_shared_columns_take_the_values_the_orders_table_takes() -> None:
    assert _listed(_TABLE_DDL, "rs_side", "position_side") == _listed(_ORDERS, "ord_side", "side")
    mode = _listed(_ORDERS, "ord_tpslmode", "tpsl_mode")
    assert _listed(_TABLE_DDL, "rs_mode", "tpsl_mode") == mode
    assert _check(_TABLE_DDL, "rs_posidx") == _check(_ORDERS, "ord_posidx")


def test_the_numbers_are_bounded_and_a_trail_has_both_or_neither() -> None:
    assert _check(_TABLE_DDL, "rs_px") == "trigger_price > 0"
    size = "(tpsl_mode = 'Partial' AND size > 0 OR tpsl_mode = 'Full' AND size IS NULL) IS TRUE"
    assert _check(_TABLE_DDL, "rs_size") == size  # NULL-safe: a bare CHECK passes NULL
    trail = _check(_TABLE_DDL, "rs_trail")
    assert trail.startswith("num_nonnulls(trailing_distance, trailing_active_price) <> 1 AND")
    assert "kind = 'stop_loss' AND trailing_distance > 0 AND trailing_active_price > 0" in trail
    finite = re.findall(r"(\w+) <> 'NaN'", _check(_TABLE_DDL, "rs_finite"))
    assert finite == ["trigger_price", "size", "trailing_distance", "trailing_active_price"]


def test_a_row_is_written_ahead_by_a_request_and_never_by_a_read() -> None:
    """24 section 8.8 rule 6: written before the request leaves; nothing a read reports."""
    assert "audit_record_id       uuid NOT NULL," in _TABLE_DDL
    assert _check(_TABLE_DDL, "rs_entry") == "(source = 'entry_attach') = (order_id IS NOT NULL)"
    assert _check(_TABLE_DDL, "rs_restore") == "source <> 'restore' OR kind = 'stop_loss'"
    assert not _missing(
        _words(_SECTION),
        "A row is inserted before its request leaves (write-ahead, as S8), `pending` and in "
        "flight (`answered_at` NULL), and only by a stop request the OMS sends",
        "`source` has no value for a read, so nothing an exchange read alone reports ever "
        "becomes a row",
        "a refusal makes the row `void` and leaves the row in force as it was",
        "A pending row, answered or not, stays matchable for the push that follows its request "
        "(24 §8.5 step 3c) and displaces nothing until a read shows its stop",
        "An entry's row is never voided blind (C-2.6)",
    )


#: The table of what each step of an entry order does to its rows (R10, the 2026-10-21 ruling).
_STEPS = _SECTION.split("**An entry's rows at each step of its order", 1)[1].split(
    "**Ends with its position.**", 1
)[0]


def test_an_entry_row_is_voided_only_once_the_exchange_confirms_its_entry_unfilled() -> None:
    """A KILL after the send or an end out of `unknown` leaves the rows waiting for the complete
    read, which settles them from what the exchange shows; an entry never sent, written ahead, and
    an exchange-confirmed terminal with zero count (`cancelled` or `expired`) void them (the
    orchestrator's rulings of 14:26Z); the sweep voids only an entry never placed (CR-2A-01), and a
    void never meets a recorded fill (SEC-2A-01)."""
    cells = [
        [cell.strip() for cell in line.strip("|").split(" | ")]
        for line in _STEPS.splitlines()
        if line.startswith("| ") and not line.startswith("| ---")
    ]
    effects = {row[0]: row[1] for row in cells[1:]}  # the header row first
    waits = (
        "Any other step into `killed`, `expired`, `cancelled`, `rejected` or `held`: a KILL after "
        "the send, any end out of `unknown`, an expiry or a cancel with no exchange count (a "
        "locally timed expiry, a cancel's own answer), an end reconciliation or the operator "
        "decided"
    )
    assert effects[waits] == "none: `pending`, **waiting for the complete read**"
    refused = (
        "`submitting` → `rejected`: the create's own answer refused it, or the command port's "
        "`EXPIRED_UNSENT` ended a resumed create no lookup found within the venue's 24 h history "
        "(24 §8.3 rule 6)"
    )
    assert effects[refused] == "`void`"
    confirmed = [step for step, rows in effects.items() if rows == "`void`"]
    assert len(confirmed) == 3
    never_sent = "`validated` → `killed`: a KILL before the send (`abandon`), so never sent"
    assert confirmed[1] == never_sent
    assert confirmed[2].startswith(
        "→ `cancelled` or `expired`, an exchange-confirmed terminal with zero count: the order's "
        "own end push (`REMOTE_CANCELLED`, `EXPIRE`) reporting a zero cumulative fill"
    )
    assert not _missing(
        _words(_SECTION),
        "it becomes `void` only once the exchange confirms that its entry ended unfilled, once "
        "its entry is known never to have been sent, or once a complete read shows its entry "
        "filled and its stop absent",
        "a step that cannot know whether the entry filled leaves them `pending`, waiting for the "
        "complete read: B1's own fill count can lag a fill the exchange holds back",
        "voids the pending rows of an entry never placed, audited `sl.modified` (`tp.modified` "
        "for a take-profit side) with reason `unplaced_entry_swept`",
        "It never voids a row waiting for the complete read.",
        "the send's step commits `submit_attempts` with its `order_events` row before the create "
        "can leave, as B1 starts `submitting`'s place only once that write committed and never "
        "after a refused one",
        "A row waiting for the complete read is resolved by that read too",
        "The statement that voids them also needs the order to hold no recorded fill",
    )
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert not _missing(
        rule,
        "an entry never sent, or one the exchange confirms ended unfilled, leaves the prior record "
        "in force",
        "an exchange-confirmed terminal with zero count: the order's own end push, `cancelled` or "
        "`expired`, reporting a zero cumulative fill",
        "its entry was never sent (a KILL before the send, which is written ahead",
        "or an entry that ended with no such confirmation (a KILL after the send, any end out of "
        "`unknown`, or a locally timed expiry or a cancel's own answer, which report no count: the "
        "record is then waiting for the complete read",
    )


def test_one_request_is_in_flight_per_position_and_one_row_is_in_force_per_side() -> None:
    """Two writers never interleave on a position, and a position has one recorded stop."""
    key = "exchange_account_id, symbol, position_idx"
    in_flight = "status = 'pending' AND answered_at IS NULL AND kind = 'stop_loss'"
    assert _unique_index("ux_rs_in_flight") == (key, in_flight)
    assert _unique_index("ux_rs_in_force") == (f"{key}, kind", "status = 'in_force'")
    assert not _missing(
        _words(_SECTION),
        "Every request records its stop-loss side",
        "so `ux_rs_in_flight` admits one request in flight per position: a second writer's "
        "insert is refused (SQLSTATE 23505) until the first has its answer",
        "puts it `in_force` and, in the same transaction, the row in force for its position "
        "and kind `replaced` (`ux_rs_in_force`)",
        "A request whose outcome stays unknown keeps its position in flight, so no other stop "
        "request leaves for the position until its row is resolved",
    )


def test_an_unanswered_request_is_resolved_by_a_read_before_the_next_stop_request() -> None:
    """A row in flight has an owner and an end: the complete read of 24 section 8.8 rule 6,
    never a timer, so a writer that is gone never blocks its position for good."""
    assert not _missing(
        _words(_SECTION),
        "A row left unanswered past its request's bound, or found unanswered at startup, is "
        "resolved before any other stop request for its key leaves, by the complete read of 24 "
        "§8.8 rule 6",
        "a read that shows its stop puts it `in_force`, as above",
        "one that shows neither the stop nor an order that matches it nor a resting entry that "
        "carries it nor a fill of its entry makes it `void`, audited `sl.modified` "
        "(`tp.modified` for a take-profit side) with reason `in_flight_resolved`",
        "The two rows of one request come from one INSERT and share its `created_at`; a "
        "request the read did not find filled is answered in one decision and never half voided",
        "no row is ever resolved by a time-based expiry",
        "The writer of its request owns the resolution: E29-T04 for an entry's attach and the "
        "trading-stop path, E29-T06 for its 24 §8.5 step 5 restore",
    )
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert (
        "a complete read after the request's timeout shows neither the stop nor an order that "
        "matches it nor a resting entry that carries it (the position, and, for a Partial side "
        "or for a Full side whose position the read shows flat or on the other side, the open "
        "orders and the order history from 5 s before the request (no further back than 4 weeks, "
        "`MAX_HISTORY_WINDOWS`: a miss older than that is held as a span miss while the "
        "position is flat or on the other side and shows a stop; while it is open on the row's "
        "side the miss decides, as inside the span), where a Full-mode stop that "
        "already fired is an order that matches it, never a reason to void the record, and "
        "where, while the position is open on the record's side, a matching order that history "
        "shows ended with no fill (cancelled, deactivated or rejected) is the stop absent, not "
        "a match, while one that filled matches whatever its end status)" in rule
    )


def test_the_complete_read_ends_each_case_on_the_row_as_ruled() -> None:
    """#913 S3-H rulings (issuecomment-6376192722), with the code lens's folds on #4353: Q1, a fill
    of the entry ends the wait durably on the row (`replaced`, or `void` with
    `entry_filled_stop_absent`, a stop-loss's paged while its position is open), no memo; Q3, the
    history read when flat or on the other side, a fired Full-mode stop a match, and the key held
    through `WAITING_ENTRY` visible until E29-T06 resolves it; the read's order (stop, match,
    resting entry, fill, none); Q2, Q6 to Q10 as the plan recommended. 21 owns the rows, 24 the
    read and the pipeline, 20 the startup, the stop and the metric."""
    section = _words(_SECTION)
    assert not _missing(
        section,
        "it becomes `void` only once the exchange confirms that its entry ended unfilled, once its "
        "entry is known never to have been sent, or once a complete read shows its entry filled "
        "and its stop absent (below)",
        "for a Partial side or for a Full side whose position the read shows flat or on the "
        "other side, the open orders and the order history from 5 s before the request, a "
        "history read covering only the venue's spans, 24 §14.1, and reaching back no further "
        "than 4 weeks (`MAX_HISTORY_WINDOWS`), a miss older than that held as a span miss while "
        "the position is flat or on the other side and shows a stop; while it is open on the "
        "row's side the miss decides, as inside the span): a read that shows its stop "
        "puts it `in_force`, as above (a native trail shown only by its distance and "
        "activation price, never by the trigger it moves; while `Position` carries no "
        "activation price, `[O-4]`, a trail request whose position shows a trail by its "
        "distance is held, counted as `held_for_reconciliation` and logged once, until "
        "E29-T06's pass or until `Position` carries the activation price, E29-K01, and a "
        "position that shows no stop at all is never held on this rule)",
        "one that shows an order that matches it, open or in that history (a Full-mode stop "
        "that already fired among them, never taken for a foreign order), answers it and "
        "leaves it `pending` for E29-T05 to materialise (24 §8.3 rule 7), a Partial side going "
        "in force only once that row exists, except that while the position is open on the "
        "row's side a matching order the history shows ended with no fill (cancelled, "
        "deactivated or rejected) is the stop absent, not a match, and a matching order that "
        "filled matches whatever its end status; one that shows a fill of its entry, and "
        "neither its stop nor an order that matches it nor a resting entry that carries it, is "
        "decided as a waiting row's fill is (below), so an unanswered entry that filled is "
        "never voided `in_flight_resolved`",
        "from what the exchange shows, each side on its own (Bybit holds a position's "
        "stop-loss and take-profit as separate facts, so one can be present without the other) "
        "and in this order: a read that shows its stop puts it `in_force`; one that shows an "
        "order that matches it answers it and leaves it `pending`, as above; one that shows "
        "its entry still resting with the stop attached keeps it, its request still in flight; "
        "one that shows a fill of its entry ends the wait on the row itself, never in memory: "
        "`replaced` when a later row of its key and kind is in force (by that later row's "
        "transaction for an answered row, or by the read's own write for an unanswered one), "
        "and otherwise `void` with reason `entry_filled_stop_absent`, audited as above and "
        "counted, and paged for a stop-loss side while the position is open on its side, since "
        "a filled entry whose stop-loss is not on its open position is a C-2.6 exposure: the read "
        "clears the key for the protective re-attach (B1's `sl_missing`) and places no stop "
        "itself; and one that shows none of these makes it `void`, with the unanswered row's "
        "reason (`in_flight_resolved`)",
        "A row the read answered while its entry's order ended without knowing its fill still "
        "waits through that order (`WAITING_ENTRY`, the settle table's \"waiting for the complete "
        'read" row), so its key stays refused, counted as `held_for_reconciliation` '
        "(`20-architecture.md` §12.1) and logged once per key, and paged once per hold when the "
        "read shows its position open with no stop at all, a C-2.6 exposure only that pass "
        "clears; E29-T06's pass must resolve those rows (24 §8.5)",
        "when a read shows one side, that side goes in force and the other is answered, the "
        "next read answering it should a crash come between the two writes. A filled entry's "
        "sides are each decided as above. An entry partly filled and still resting is decided "
        "as a fill for its filled part, the open part being what C-2.6 protects.",
        "Putting a row in force, or replacing one, stamps `answered_at` if it is still NULL",
        "The read runs once per key at a time and at most 8 at once in the process (C-2.18), "
        "one of the 8 kept for an attach's read, as C-12.7 keeps a reserve for the protective "
        "paths; one that fails, or does not answer within its bounds (5 s a venue read, 15 s "
        "the whole read), decides nothing, and a key whose read cleared nothing, failed or "
        "not, waits 5 s, the refusal's `Retry-After`, before an entry's request asks the venue "
        "again, while an attach takes the reserved slot or joins the read already running on "
        "its key",
        "At startup the read also runs eagerly, for the waiting keys of the process environment's "
        "accounts, after `void_orphans` and without holding `ready` (`20-architecture.md` §6.2), "
        "and every unanswered row created before the runtime started waits for it whatever its "
        "age: the startup floor, its start read from the database's clock",
        "A `restore` row's read is E29-T06's: the gate keeps its key refused and pages it once.",
        "A history miss decides nothing only where it can hide a match: a row whose request is "
        "older than the venue's 24 h span and whose position is flat or on the other side, or "
        "a demo row past the venue's 7 d less 24 §8.3 rule 6's one-day margin, that no read "
        "shows matched is held, counted as `held_for_reconciliation` and logged once, and "
        "E29-T06's pass resolves it (24 §8.5); inside the spans a miss decides, and so does a "
        "live miss past them while the position is open on the row's side, as live keeps "
        "filled orders in its history; a key whose position, open on either side, shows no "
        "stop at all is never held on this rule.",
        "E29-T06's pass also resolves the rows held through `WAITING_ENTRY`, which no read of "
        "E29-T04's can decide",
        "and the complete read's (`in_flight_resolved`, and `entry_filled_stop_absent`, whose "
        "record carries `position_state`, `open` (a position on the row's side) or `flat` "
        "(none on its side, the other side's included), so a naked window that a close or a "
        "liquidation ended stays on the record unpaged; and, for a stop-loss side, the "
        "`in_flight_resolved` void of an entry the read did not find where a miss proves "
        "nothing, while the position is open with no stop at all, whose record carries "
        "`position_state` too and which pages `entry_unseen`, no stop), is audited write-ahead "
        "too",
    )
    rules = _words(_INTERNAL_DOC.split("**The pipeline's own rules", 1)[1].split("**8.4.1 ", 1)[0])
    assert not _missing(
        rules,
        "answers `409 stop_request_in_flight` at once with `Retry-After: 5` and starts that read, "
        "which runs on after the answer so the client's retry can find the key resolved",
        "an attach (B1's `attach_stop`, §8.9's path) waits up to 2 s for the read, then is "
        "refused as the entry is, B1 landing in `sl_missing`",
    )
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert (
        "A complete read that shows a fill of its entry, waiting or unanswered, and neither "
        "its stop nor an order that matches it nor the entry still resting, ends the wait on "
        "the record itself (`21-database-schema.md` §3.3.11), each side on its own: replaced "
        "when a later record of its kind is in force, and otherwise void with reason "
        "`entry_filled_stop_absent`, paged for a stop-loss while its position is open on its "
        "side, a C-2.6 exposure: the read clears the key so the protective re-attach can "
        "leave, and places no stop itself" in rule
    )
    assert (
        "whether a position read echoes a trail's activation price (`activePrice`), and whether "
        "a re-sent armed trail is re-based at the market)" in rule
    )
    reconciliation = _INTERNAL_DOC.split("### 8.5 Reconciliation algorithm", 1)[1]
    reconciliation = _words(reconciliation.split("### 8.6 ", 1)[0])
    assert (
        "- **The recorded stops held for reconciliation (E29-T04 S3-H, `21-database-schema.md` "
        "§3.3.11).** A row the complete read answered while its entry's order ended without "
        "knowing its fill keeps its key refused "
        '(`oms_stop_resolutions_total{outcome="held_for_reconciliation"}`, `20-architecture.md` '
        "§12.1), and so do a row a history miss past the venue's span could not decide and a "
        "trail request held while `Position` carries no activation price: this pass must resolve "
        "exactly those rows (a trail request once its own position read carries the activation "
        "price, E29-K01, `[O-4]`, and until then it stays held and visible), from its own reads "
        "of the entry's fill and the position's stop, as the complete read decides them; until "
        "it does, each such key stays refused and visible, never released silently. A held row "
        "whose position is open with no stop at all comes first: this pass reconciles it before "
        "anything else, and the protective attach follows that decision in the same pass "
        "(C-2.6)." in reconciliation
    )
    runtime = _words(_ARCH.split("**OMS runtime (E29-T04 slice 3, #913).**", 1)[1])
    assert not _missing(
        runtime,
        "is as built by #913 slice 3 (sub-slices B to H)",
        "Then it starts the complete read for those accounts' waiting stop requests "
        "(`21-database-schema.md` §3.3.11) and goes on without waiting for it: the read never "
        "holds `ready`, so a venue outage at boot holds no order entry, and the hydration's "
        "re-attaches join it; an account the binding refuses (soft-deleted, or keyless) is paged "
        "and its keys stay refused, never read;",
        "cancels what remains, the startup task and the complete read's tasks",
    )
    metrics = _ARCH.split("### 12.1 ", 1)[1].split("### 12.2 ", 1)[0]
    name = "`oms_stop_resolutions_total{outcome}`"
    [row] = [line for line in metrics.splitlines() if name in line]
    listed = row.split("by outcome, a closed set:", 1)[1]
    outcomes = (
        "in_force",
        "replaced",
        "answered",
        "entry_resting",
        "in_flight_resolved",
        "entry_filled_stop_absent",
        "held_for_reconciliation",
        "read_failed",
    )
    assert all(f"`{outcome}`" in listed for outcome in outcomes)
    assert "| counter |" in row
    assert not _missing(
        _words(row),
        "**page on a stop-loss's `entry_filled_stop_absent` while its position is open on its "
        "side**, a C-2.6 exposure, **and once per hold on a key held through `WAITING_ENTRY` "
        "whose position is open with no stop at all**, a C-2.6 exposure only that pass clears",
        "its catalogue entry lands with S3-H's gate (H3)",
        "a trail request stays held until that pass or until `Position` carries the activation "
        "price, E29-K01",
    )


def test_a_row_ends_with_its_position_so_no_later_position_inherits_it() -> None:
    ends = "closing execution that takes the position to zero, or a read whose instance marker "
    assert not _missing(
        _words(_SECTION),
        "that shows the key flat or absent, or holding a position of the other side (a "
        "one-way reversal, a new position on the key), ends every row in force for the key "
        "(`ended`)",
        f"so does a {ends}differs from the row's (`[O-4]`, E29-K01)",
        "None of these ends a pending row (24 §8.8 rule 6)",
        "So a later position never inherits an old stop",
        "`position_marker` holds the marker of the position the row protects, set once: by the "
        "trading-stop writer's position read, or by the read that puts the row in force",
    )
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert not _missing(
        rule,
        "shows the key flat or absent, or holding a position of the other side (a one-way "
        "reversal, a new position on the key), once the trade executions",
        f"A {ends}differs from the record's (`[O-4]`, E29-K01), ends it as such a read "
        "does; the record keeps the marker of the position it protects, set once",
    )
    assert _words(_check(_TABLE_DDL, "rs_times")).startswith(
        "(closed_at IS NOT NULL) = (status IN ('replaced','ended','void'))"
    )
    marker = "position_marker IS NULL OR char_length(position_marker) BETWEEN 1 AND 64"
    assert _check(_TABLE_DDL, "rs_marker") == marker


def test_the_guard_keeps_the_request_and_admits_only_the_lifecycle_moves() -> None:
    assert [c for c in _REQUEST if not re.search(rf"NEW\.{c}\b.*OLD\.{c}\b", _GUARD, re.S)] == []
    once = ["answered_at", "in_force_at", "closed_at", "released_at", "position_marker"]
    pattern = r"WHEN OLD\.(\w+) IS NOT NULL AND NEW\.\1 IS DISTINCT FROM OLD\.\1 THEN '\1'"
    assert re.findall(pattern, _GUARD) == once
    guard = " ".join(re.sub(r"--[^\n]*", "", _GUARD).split())
    assert not _missing(
        guard,  # one bind, one stamped release, and never a bind again
        "WHEN NEW.exchange_order_id IS DISTINCT FROM OLD.exchange_order_id "
        "AND NOT (OLD.exchange_order_id IS NULL AND OLD.released_at IS NULL) "
        "AND NOT (NEW.exchange_order_id IS NULL AND NEW.released_at IS NOT NULL) "
        "THEN 'exchange_order_id'",
        "WHEN NEW.released_at IS DISTINCT FROM OLD.released_at AND OLD.exchange_order_id IS NULL "
        "THEN 'released_at'",
    )
    assert "<>" not in guard.split("THEN 'closed_at'", 1)[1].split("THEN 'exchange_order_id'")[0]
    assert _check(_TABLE_DDL, "rs_release") == "released_at IS NULL OR exchange_order_id IS NULL"
    assert not _missing(
        _words(_SECTION),
        "`exchange_order_id` is bound at most once",
        "it is cleared only by its release, the one of 24 §8.3 rule 7",
        "which stamps `released_at` (`rs_release`), and it is never bound again",
    )
    moves = re.findall(r"\('(\w+)','(\w+)'\)", _words(_GUARD.split("NOT IN", 1)[1]))
    assert moves == [
        ("pending", "in_force"),
        ("pending", "void"),
        ("pending", "replaced"),
        ("pending", "ended"),
        ("in_force", "replaced"),
        ("in_force", "ended"),
    ]
    assert "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_rs_guard';" in _GUARD
    assert "ALTER TABLE recorded_stops ENABLE ALWAYS TRIGGER trg_rs_guard;" in _GUARD


def test_a_pending_record_answered_ok_ends_as_one_in_force_and_says_so() -> None:
    """#4010's CR-G6-R4-05 (f), the orchestrator's ruling: a flat read ends no pending record but
    one the exchange answered `ok` that no resting entry carries, which ends as one in force does
    and keeps `in_force_at` NULL, so it never reads as an end a read confirmed in force."""
    guard = " ".join(re.sub(r"--[^\n]*", "", _GUARD).split())
    assert (
        "WHEN OLD.status = 'pending' AND NEW.status = 'ended' AND OLD.answered_at IS NULL "
        "THEN 'status'"
    ) in guard
    times = _words(_check(_TABLE_DDL, "rs_times"))
    assert "(in_force_at IS NOT NULL OR status <> 'in_force')" in times
    assert "(status <> 'ended' OR num_nonnulls(in_force_at, answered_at) > 0)" in times
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert not _missing(
        rule,
        "A flat read ends no pending record, except one whose request the exchange answered `ok`, "
        "that no resting entry carries and that is not waiting for the complete read",
        "Apart from that end, a pending record ends only once its request is known not to have "
        "placed the stop",
        "its end is marked as one no read confirmed in force",
    )
    assert not _missing(
        _words(_SECTION),
        "An `ended` row with no `in_force_at` is that end, answered and never shown",
        "and that is not waiting for the complete read (an entry's row whose entry ended with no "
        "confirmed count, which that read's fill test resolves, above)",
        "`pending` → `in_force`, `void`, `replaced` or, once answered (`answered_at` set before "
        "the move), `ended`",
    )


def test_no_role_deletes_or_truncates_the_record() -> None:
    """SR-E29-05's pattern: a statement trigger refuses TRUNCATE whatever the role, and the app
    and read-only roles hold neither DELETE nor TRUNCATE."""
    assert not _missing(
        _GUARD,
        "CREATE TRIGGER trg_rs_no_truncate BEFORE TRUNCATE ON recorded_stops\n"
        "  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();",
        "ALTER TABLE recorded_stops ENABLE ALWAYS TRIGGER trg_rs_no_truncate;",
    )
    assert not _missing(
        _words(_SECTION),
        "`cv_app` and `cv_ro` hold no DELETE or TRUNCATE on the table where the roles exist, and "
        "`trg_rs_no_truncate` (BEFORE TRUNCATE, `ENABLE ALWAYS`, 0003's `audit_refuse_truncate()`) "
        "refuses a TRUNCATE by any role, SR-E29-05's pattern",
    )


def test_the_writers_readers_and_audit_link_are_the_ones_the_rulings_name() -> None:
    assert not _missing(
        _words(_SECTION),
        "E29-T04 writes an entry's attach (24 §8.8 rule 1) in B1's `VALIDATE` transaction",
        "which rule-engine trails and breakeven (24 §10.7, E32) always go through",
        "E29-T06 writes 24 §8.5 step 5's restore, only while the row it read is still in force",
        "E29-T05 materialises a recorded side's triggered order as an `orders` row with "
        "provenance `recorded_stop` (§3.3.4)",
        "the OMS cancel service, which refuses to cancel a recorded stop while its position is "
        "open",
        "(`sl.attached`, `sl.modified`, `sl.loosened`, and `tp.modified` for a take-profit side, "
        "24 §15.5)",
        "`audit_record_id` is that record's writer-assigned `record_id` (§3.10.1)",
    )
    vocabulary = _INTERNAL_DOC.split("### 15.5 ", 1)[1].split("### 15.6 ", 1)[0]
    actions = ("`sl.attached`", "`sl.modified`", "`sl.loosened`", "`tp.modified`")
    assert _missing(vocabulary, *actions) == []  # the closed set holds each action cited


def test_the_table_is_registered_where_21_registers_one() -> None:
    erd = _DOC.split("### 2.2 ", 1)[1].split("### 2.3 ", 1)[0]
    assert not _missing(
        erd,
        "exchange_accounts ||--o{ recorded_stops : protects",
        "orders |o--o{ recorded_stops : attaches",
        "    recorded_stops {\n        uuid id PK\n",
    )
    retention = _DOC.split("\n## 7. ", 1)[1].split("\n## 8. ", 1)[0]
    assert re.search(r"^\| `recorded_stops` \(PG\) +\| ∞ +\| — +\| ∞ +\|", retention, re.M)
    plan = _DOC.split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [revision] = [row for row in plan.splitlines() if row.startswith("| `0043_order_submission`")]
    assert "`recorded_stops` (§3.3.11)" in revision and "**E29-T04 #913**" in revision
    classes = _DOC.split("\n## 12. ", 1)[1]
    assert re.search(r"^\| `recorded_stops` +\| monetary columns +\| P1 +\|", classes, re.M)
    [actor] = re.findall(r"^\| `recorded_stops` +\| `actor_user_id` +\| P0 +\|.*$", classes, re.M)
    assert "A user id (0043), never a name, email or IP; `ON DELETE RESTRICT` keeps" in actor
    assert "actor_user_id         uuid REFERENCES users(id) ON DELETE RESTRICT," in _TABLE_DDL


def test_the_rules_it_cites_keep_their_numbers() -> None:
    """24 section 8.8 rule 6 and section 8.3 rule 7 are cited by number here and in 21; a
    renumbering fails this contract instead of leaving the citations dangling."""
    record = _INTERNAL_DOC.split("### 8.8 ", 1)[1].split("### 8.9 ", 1)[0]
    pairing = _INTERNAL_DOC.split("### 8.3 ", 1)[1].split("### 8.4 ", 1)[0]
    assert "\n6. **The recorded stop (SR-E29-06" in record
    assert "\n7. **Pairing through the bound id (SR-E29-03).**" in pairing
    assert not _missing(_SECTION, "24 §8.8 rule 6", "24 §8.3 rule 7")


def test_rule_7_releases_a_record_only_by_its_successors_bind() -> None:
    """Rule 7's release, which 21's "Binding" cites (#848, the orchestrator's ruling of
    2026-10-23 in LANE-43): a record's binding is released only when its successor, the OMS's own
    later record, binds the same `orderId`, the release first in one transaction. A foreign or
    venue change in place keeps the binding, so section 8.5 step 5 still compares the order's row
    with the record and puts the recorded stop back over a looser one (C-2.6); an end keeps the
    id, so a stop that closed its position still pairs; and the materialised `orders` row is never
    released."""
    head = "\n7. **Pairing through the bound id (SR-E29-03).**"
    rule = _words(_INTERNAL_DOC.split(head, 1)[1].split("\n", 1)[0])
    binding = _words(_SECTION.split("**Binding.**", 1)[1].split("\n\n", 1)[0])
    assert not _missing(
        rule,
        "each recorded side's `recorded_stops` row binds that `orderId` once, as its "
        "`exchange_order_id`, in the transaction that materialises the order's row (on the "
        "order push that follows its request, §8.9; in §8.5 step 3c or 3d; or on §8.12 step 3's "
        "read of a fill's order) or by its bind as a successor (below)",
        "That binding is released (`exchange_order_id` cleared and `released_at` stamped, "
        "`rs_release`; never bound again) only by its successor's bind: the OMS's own later "
        "record of the side binding the same `orderId` once its own match accepts the order "
        "(§8.8 rule 6), the release first and the bind after it, in one transaction, so both "
        "happen or neither does.",
        "Where more than one live record of the side matches the order, the latest of them "
        "binds, at materialisation or as the successor; never two. Later and latest order a "
        "side's records by `created_at`, then `id`.",
        "Both run where a push or a read of the order reaches its row: on the push at §8.12 step "
        "1, beside `TERMS_CHANGED`, and on the read at §8.5 step 3a or 3b, as step 3c skips an "
        "order already bound.",
        "E29-T05 releases on the push and E29-T06 on the read.",
        "A successor whose terms equal its predecessor's shows no change on the push, so it "
        "binds at the next pass's step 3a or 3b, the predecessor staying in force and bound "
        "meanwhile.",
        "A foreign or venue in-place change keeps the binding (`[O-4]`): `TERMS_CHANGED` "
        "updates the materialised row as the sixth point below bounds it, and §8.5 step 5 "
        "compares that row with the record and restores the recorded stop over a looser one "
        "(SR-E29-06, C-2.6).",
        "An end never releases it: a record that ends with its position, or whose order is "
        "cancelled, rejected, expired or deactivated, keeps the id, so the fills of a stop that "
        "closed its position still pair; a record that has ended keeps it whatever a later push "
        "or read of its order shows, and a successor binds an order that has ended only when "
        "that order ended `filled`.",
        "The materialised `orders` row is never released.",
    )
    assert not _missing(
        binding,
        "in the transaction that materialises the side's TP/SL order as an `orders` row (on the "
        "order push that follows the request, 24 §8.9; in reconciliation, 24 §8.5 step 3c or 3d; "
        "or on the private-stream consumer's read of a fill's order, 24 §8.12 step 3), or by its "
        "bind as a successor (below)",
        "Where more than one live record of the side matches the order, the latest (by "
        "`created_at`, then `id`) binds; never two.",
        "It is released only by its successor's bind: the OMS's own later record binding the "
        "same `orderId`, release first in that transaction; a foreign or venue in-place change "
        "keeps the binding (`[O-4]`), `TERMS_CHANGED` updates the materialised row, and 24 §8.5 "
        "step 5 compares it with the record and restores.",
        "The end of the row keeps it, so the fills of a stop that closed its position still pair.",
    )
    log = (
        "\n### 19.30 2026-10-23 — §8.3 rule 7, §8.5, §8.12, and 21 §3.3.11: a recorded stop's "
        "binding is released only by its successor's bind (E29-T05, #848)\n"
    )
    assert log in _INTERNAL_DOC


def test_8_12_says_the_runtime_runs_the_consumer_and_logs_it_as_19_51() -> None:
    """E29-T05 S8b (#848): 24 section 8.12 as built, logged as section 19.51 after E08-T09's 19.50.
    The banner no longer says nothing runs the consumer; `StreamedAccounts` is account health's
    last good tracking read, read in place, never an account tracked for a replayed or owed call
    alone; the runtime's `stream` phase announces the stand-ins; a position row held as dated
    ahead of the store's clock is applied again once the clock is back in sync, which the
    consumer's re-sync now runs, bounded; and an account its disable closed (#898 B3b2) waits for
    health's next tracking read, told apart by its set object, keyed on that status alone."""
    head = "### 8.12 The private-stream consumer (E29-T05)"
    section = _words(_INTERNAL_DOC.split(head, 1)[1].split("\n---\n", 1)[0])
    assert "contract first: nothing runs it yet" not in section
    assert not _missing(
        section,
        "_Added for E29-T05 (#848); as built since its wiring slice (S8b): the OMS runtime runs "
        "it._",
        "The consumer's dead-man's-switch window opens at its start, where the OMS runtime sets "
        "`ready`, not at boot,",
        "which is the set account health monitors: its last good tracking read "
        "(`AccountHealthRuntime.streamed`), read in place from the lane, never an account it "
        "tracks for a replayed or owed dead-man's-switch call alone,",
        "The OMS runtime's `stream` phase announces each stand-in it binds,",
        "the OMS runtime wires it on the real backend, and the fake backend composes no OMS.",
        "and applied again once the clock is back in sync.",
        "**Readiness (the orchestrator's ruling of 2026-10-25).** Once the runtime is `ready`, "
        "the `/readyz` `oms` check (`20-architecture.md` §6.2) is `degraded` while the consumer "
        "has not started, while it has faulted",
        "Each read answers one set, the same object until health's next read replaces it, equal "
        "or not, so the consumer tells one read from the next (a disabled account, below).",
        "a disabled account waits for health's next tracking read (below)",
        "So the consumer takes that read as the status comes and does not restart the account "
        "while it stays in place: while it holds, no refused subscribe counts a defect or pages.",
        "The hold is keyed on that status alone, never on a refused subscribe, which stays a "
        "defect and pages",
    )
    assert "While the consumer runs, the `/readyz`" not in section  # fails closed from `ready`
    log = "### 19.51 2026-10-28 — §8.12: the private-stream consumer runs (E29-T05, #848)\n"
    assert log in _INTERNAL_DOC  # a later entry may follow it: slice 4's gap test keeps them whole
    entry = _words(_INTERNAL_DOC.split(log, 1)[1].split("\n### ", 1)[0])
    assert not _missing(
        entry,
        "This number follows `main`'s last entry, §19.50; an entry that lands first takes it",
        f"bounded at {REAPPLY_TIMEOUT_S:g} s and counted `reapply_timeout`",
        "the Readiness paragraph names the not-started case.",
        "No REST, WS, table, column, chart or `machine_hash` change;",
        "an account its disable closed (`closed`, `account_disabled`) is not restarted while the "
        "health tracking read taken as the status comes stays in place,",
        "The hold is keyed on that status, never on a refused subscribe.",
    )


def test_8_12_names_the_wallet_clock_the_stand_ins_signals_and_the_holds_windows() -> None:
    """E29-T05 S9 (#848): 24 section 8.12 as built. A wallet row is refused once it is dated more
    than the position store's future skew ahead of the exchange-synced clock, never the host's,
    and counted `wallet_ahead`; the stand-in reconciliation's refusal is named by the log, the
    count and the page the consumer gives it, never `oms_reconciliation_unavailable`, which nothing
    emits; and a disable's hold is never called absolute: the paragraph and `_hold`'s docstring
    name its two windows, a carry on #848. The stand-in's and account health's docstrings say the
    same. Its section 19 entry is found by its title, whatever number it lands as."""
    head = "### 8.12 The private-stream consumer (E29-T05)"
    section = _words(_INTERNAL_DOC.split(head, 1)[1].split("\n---\n", 1)[0])
    skew = f"{MAX_FUTURE_SKEW.total_seconds():g} s"
    assert "not dated ahead of the host clock" not in section
    assert "oms_reconciliation_unavailable" not in section
    assert "it lists the account only once it is enabled again" not in section
    assert not _missing(
        section,
        f"| `wallet` | dated no more than {skew} (`MAX_FUTURE_SKEW`) ahead of the exchange-synced "
        "clock (`ExchangeWallClock`) |",
        "one dated further ahead is refused before it, logged and counted (`wallet_ahead`),",
        "the consumer logs it (`stream_resync_refused`), counts it "
        '(`oms_stream_outcomes_total{stage="consumer",outcome="reconciliation_unavailable"}`) '
        'and pages once per episode ("an account\'s reconciliation request was refused"),',
        "a read made after the disable lists the account only once it is enabled again,",
        "Two windows remain, each of which can page once, on demo or testnet only and with no "
        "protection effect, as a live process fails closed until E29-T06; their fix is a carry "
        "on #848.",
        "A health read already in flight when the disable commits publishes a set made before it "
        "once the hold is taken, which releases the hold.",
        "brings no `account_disabled` status to hold on, so the restart before health's next "
        "read meets the closed key.",
        "`refuse_live_without_freeze(environment, lockout)` (`oms_stream_wiring`) raises "
        "`FreezeUnavailable` while the lockout as bound is the paging stand-in, which cannot "
        "freeze,",
    )
    assert "refuse_live_without_freeze(" in inspect.getsource(StreamWiring.refuse_live)
    held = _words(inspect.getdoc(stream_consumer.StreamConsumer._hold) or "")
    assert not _missing(
        held,
        "Two windows can still page once, on demo or testnet only",
        "a carry on #848: a health read in flight as the disable commits publishes its set after "
        "this hold is taken, which releases it; and a disable while the account has no stream "
        "open brings no status to hold on.",
    )
    stand_in = _words(inspect.getdoc(NoReconciliation) or "")
    assert "oms_reconciliation_unavailable" not in stand_in
    assert "logs (`stream_resync_refused`), counts (`reconciliation_unavailable`)" in stand_in
    health = _words(inspect.getdoc(AccountHealthRuntime) or "")
    assert "dated ahead of the host clock" not in health
    assert f"dated more than {skew} (`MAX_FUTURE_SKEW`) ahead of the exchange-synced" in health
    assert {"wallet_ahead", "reconciliation_unavailable"} <= set(get_args(Outcome.__value__))
    source = inspect.getsource(stream_consumer)
    assert '"stream_resync_refused"' in source
    assert '"an account\'s reconciliation request was refused"' in source
    title = (
        r"^### 19\.\d+ 2026-10-29 — §8\.12: the wallet row's clock, the stand-in "
        r"reconciliation's signals and the disable hold's windows, as built \(E29-T05, #848\)$"
    )
    found = re.search(title, _INTERNAL_DOC, re.MULTILINE)
    assert found is not None
    entry = _words(_INTERNAL_DOC.split(found.group(0), 1)[1].split("\n### ", 1)[0])
    assert not _missing(
        entry,
        f"a wallet row is refused when it is dated more than {skew} (`MAX_FUTURE_SKEW`) ahead of "
        "the exchange-synced clock (`ExchangeWallClock`:",
        "not ahead of the host clock, and the refusal is logged and counted (`wallet_ahead`).",
        "the log `stream_resync_refused`, the count "
        '`oms_stream_outcomes_total{stage="consumer",outcome="reconciliation_unavailable"}` and '
        'the page "an account\'s reconciliation request was refused", once per episode,',
        "the paragraph no longer calls the hold absolute but names its two windows,",
        "Their fix is a carry on #848; `StreamConsumer._hold`'s docstring says the same.",
        "the lockout's paging stand-in, which cannot freeze, is a start-up refusal for "
        "`CV_ENVIRONMENT=live` too,",
        "No REST, WS, table, column, chart or `machine_hash` change.",
    )
