"""Contract (#913, E29-T04): the recorded stop's storage, `21-database-schema.md` section 3.3.11.

Ruling 1 on G-6 (#3972) gives E29-T04's contract PR the table that `24-internal-schemas.md`
section 8.8 rule 6 describes: per position and per side a stop request sets, one row per stop the
OMS requests, written ahead of the request and never from a read; one request in flight per
position and one row in force per side; a row that ends with its position; the TP/SL order it
binds; and its audit link. Read from the document, never from a copy, and held to the `orders`
table it sits beside, so the two keep one vocabulary.
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
_COLUMNS += ["answered_at", "in_force_at", "closed_at"]


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
        "An entry's row that its entry leaves unfilled becomes `void`",
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
        "A request whose outcome stays unknown keeps its position in flight",
    )


def test_a_row_ends_with_its_position_so_no_later_position_inherits_it() -> None:
    assert not _missing(
        _words(_SECTION),
        "that shows the key flat or absent, or holding a position of the other side (a "
        "one-way reversal, a new position on the key), ends every row in force for the key "
        "(`ended`)",
        "It ends no pending row (24 §8.8 rule 6)",
        "So a later position never inherits an old stop",
    )
    assert _words(_check(_TABLE_DDL, "rs_times")).startswith(
        "(closed_at IS NOT NULL) = (status IN ('replaced','ended','void'))"
    )


def test_the_guard_keeps_the_request_and_admits_only_the_lifecycle_moves() -> None:
    assert [c for c in _REQUEST if not re.search(rf"NEW\.{c}\b.*OLD\.{c}\b", _GUARD, re.S)] == []
    once = ["answered_at", "in_force_at", "closed_at"]
    pattern = r"WHEN OLD\.(\w+) IS NOT NULL AND NEW\.\1 IS DISTINCT FROM OLD\.\1 THEN '\1'"
    assert re.findall(pattern, _GUARD) == once
    assert "WHEN NEW.exchange_order_id <> OLD.exchange_order_id THEN 'exchange_order_id'" in _GUARD
    moves = re.findall(r"\('(\w+)','(\w+)'\)", _words(_GUARD.split("NOT IN", 1)[1]))
    assert moves == [
        ("pending", "in_force"),
        ("pending", "void"),
        ("pending", "replaced"),
        ("in_force", "replaced"),
        ("in_force", "ended"),
    ]
    assert "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_rs_guard';" in _GUARD
    assert "ALTER TABLE recorded_stops ENABLE ALWAYS TRIGGER trg_rs_guard;" in _GUARD


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
    [planned] = [row for row in plan.splitlines() if row.startswith("| `NNNN_recorded_stops`")]
    assert "**E29-T04 #913**, planned: with the slice that first writes a record" in planned
    classes = _DOC.split("\n## 12. ", 1)[1]
    assert re.search(r"^\| `recorded_stops` +\| monetary columns +\| P1 +\|", classes, re.M)
    assert "`cv_app` holds no DELETE on the table where the role exists" in _SECTION
