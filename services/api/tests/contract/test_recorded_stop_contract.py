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

import re

import pytest

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH

_PLAN = OPENAPI_SPEC_PATH.parent
_DOC = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
_INTERNAL_DOC = (_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
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
    assert effects["`submitting` → `rejected`: the create's own answer refused it"] == "`void`"
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
        "it becomes `void` only once the exchange confirms that its entry ended unfilled, or once "
        "its entry is known never to have been sent",
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
        "carries it makes it `void`, audited `sl.modified` (`tp.modified` for a take-profit side) "
        "with reason `in_flight_resolved`",
        "The two rows of one request are answered together",
        "no row is ever resolved by a time-based expiry",
        "The writer of its request owns the resolution: E29-T04 for an entry's attach and the "
        "trading-stop path, E29-T06 for its 24 §8.5 step 5 restore",
    )
    rule = _words(_INTERNAL_DOC.split("6. **The recorded stop (SR-E29-06", 1)[1].split("\n", 1)[0])
    assert (
        "a complete read after the request's timeout shows neither the stop nor an order that "
        "matches it nor a resting entry that carries it (the position, and for a Partial side the "
        "open orders and the order history since the request)" in rule
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
        "A flat read ends no pending record, except one whose request the exchange answered `ok` "
        "and that no resting entry carries",
        "its end is marked as one no read confirmed in force",
    )
    assert not _missing(
        _words(_SECTION),
        "An `ended` row with no `in_force_at` is that end, answered and never shown",
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
