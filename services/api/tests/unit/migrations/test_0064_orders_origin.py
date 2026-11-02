"""The `orders` origin revision (E35-T11 #5003 slice 3a; 21 Sec.3.3.4 "Origin", 24 Sec.8.1):
offline render, plan-doc parity, the model mirror, the lock bracket, the downgrade, the single
head, the lockfile and the ledger row.

The revision's id and parent are read from its file, so the provisional number and the parent it
is re-parented onto at merge (C-5.3) change nothing here. Real Postgres: the `migrations` CI job's
round trip and `tests/integration/storage/test_orders_origin_migration.py` (C-5.5)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import fields
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, Text

from candleviewer.db import models
from candleviewer.storage.repositories.orders import (
    MAX_ORIGIN_REF_CHARS,
    NewOrder,
    OrderOrigin,
    OrderRow,
    require_origin,
)

_ROOT = Path(__file__).resolve().parents[3]
_REPO = _ROOT.parents[1]
_DOC = _REPO / "docs" / "plan" / "21-database-schema.md"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_LOCKFILE = _ROOT / "candleviewer" / "migrations" / "lockfile.json"
_HEADING = "3.3.4 `orders`"
_RULE = "3f2b8c1e-5d4a-4e6f-9a0b-1c2d3e4f5a6b"
_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|DO|COMMENT|REVOKE|LOCK|GRANT)\b")


def _ids(path: Path) -> tuple[str, str]:
    """The `revision` and `down_revision` string literals a version file assigns."""
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found[node.target.id] = node.value.value
    return found["revision"], found["down_revision"]


[_FILE] = sorted(_VERSIONS.glob("*_orders_origin.py"))
_REV, _PREV = _ids(_FILE)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#5003)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space inside a bracket, and fold the `;`
    alembic appends, as the 0043 suite does."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


@cache
def _section() -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {_HEADING}", 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _check(name: str) -> str:
    """The body of the model's CHECK named `name`."""
    [body] = [
        " ".join(str(c.sqltext).split())
        for c in models.orders.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith(f"_{name}")
    ]
    return body


def test_the_revision_adds_two_nullable_columns_and_their_checks() -> None:
    """21 Sec.3.3.4's fourth block is the upgrade word for word: two nullable `text` columns with
    no default, then each CHECK added `NOT VALID` and validated (C-5.6), the `db.models` mirror
    holding the same bodies (`alembic check` diffs no CHECK, so they are pinned here)."""
    assert _section().count("```sql") == 4
    block = _norm(_section().split("```sql")[4].split("```", 1)[0])
    assert block in _up()
    assert _in_order(
        _up(),
        [
            _LOCK_ON,
            "ALTER TABLE orders ADD COLUMN origin text;",
            "ALTER TABLE orders ADD COLUMN origin_ref text;",
            f"ADD CONSTRAINT ord_origin CHECK ({_check('ord_origin')}) NOT VALID;",
            "ALTER TABLE orders VALIDATE CONSTRAINT ord_origin;",
            f"ADD CONSTRAINT ord_origin_ref CHECK ({_check('ord_origin_ref')}) NOT VALID;",
            "ALTER TABLE orders VALIDATE CONSTRAINT ord_origin_ref;",
            _LOCK_OFF,
        ],
    )
    columns = list(models.orders.c)
    assert [c.name for c in columns[-3:]] == ["provenance", "origin", "origin_ref"]
    for column in columns[-2:]:
        assert isinstance(column.type, Text) and column.nullable
        assert (column.server_default, column.comment) == (None, None)
    seven = "origin IN (" + ",".join(f"'{v}'" for v in get_args(OrderOrigin)) + ")"
    assert _check("ord_origin") == f"origin IS NULL OR {seven}"
    assert _check("ord_origin_ref") == (
        "CASE WHEN origin IS NULL THEN origin_ref IS NULL WHEN origin = 'rule' THEN origin_ref "
        f"IS NOT NULL AND origin_ref ~ '{models.GROUP_REF_PATTERN}' ELSE true END"
    )


def test_the_section_states_the_third_arm_and_the_revision_its_slot() -> None:
    """The Origin paragraph names the revision's slot, `ord_origin_ref`'s third arm and the
    ledger row; no `0058` pin is left in the section's origin rows."""
    assert f"**Origin (E35-S03, #863; revision `{_REV[:4]}`).**" in _section()
    assert "leaves it free for any other origin, which 24 §8.1 gives other uses" in _section()
    rows = [line for line in _section().splitlines() if line.startswith("| `origin")]
    assert len(rows) == 2 and all(f"(`{_REV[:4]}`)" in row for row in rows)
    plan = _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [row] = [line for line in plan.splitlines() if line.startswith(f"| `{_REV}`")]
    assert "**E35-T11 #5003**" in row and "the downgrade drops both" in row


@pytest.mark.parametrize("render", [_up, _down], ids=["upgrade", "downgrade"])
def test_nothing_changes_the_schema_outside_the_lock_timeout_bracket(
    render: Callable[[], str],
) -> None:
    sql = render()
    assert sql.count("SET LOCAL lock_timeout") == 2
    assert not _DDL.search(sql.split(_LOCK_ON, 1)[0])
    assert not _DDL.search(sql.split(_LOCK_OFF, 1)[1])


def test_the_upgrade_is_additive_and_the_downgrade_drops_the_checks_then_the_columns() -> None:
    """C-5.1: nothing but the two columns and their CHECKs, no index, grant or backfill; C-5.2: the
    downgrade drops what the upgrade added, the CHECKs first."""
    body = _up().split(_LOCK_ON, 1)[1].split(_LOCK_OFF, 1)[0]
    for absent in ("INDEX", "GRANT ", "REVOKE ", "UPDATE ", "INSERT INTO ", "DEFAULT", "DROP "):
        assert absent not in body
    assert _in_order(
        _down(),
        [
            _LOCK_ON,
            "ALTER TABLE orders DROP CONSTRAINT ord_origin_ref;",
            "ALTER TABLE orders DROP CONSTRAINT ord_origin;",
            "ALTER TABLE orders DROP COLUMN origin_ref;",
            "ALTER TABLE orders DROP COLUMN origin;",
            _LOCK_OFF,
        ],
    )


def test_the_revision_sits_on_the_single_head() -> None:
    """One revision per PR (C-5.3): it follows the newest revision below its own number, the
    parent it names, and `alembic heads` is it alone."""
    assert _FILE.stem == _REV and re.fullmatch(r"\d{4}_orders_origin", _REV)
    below = sorted(p.stem for p in _VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py") if p.stem < _REV)
    assert _PREV == below[-1]
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")
    heads = [line for line in _alembic("heads").splitlines() if line.strip()]
    assert heads == [f"{_REV} (head)"]


def test_the_lockfile_names_the_revision() -> None:
    """`tools/ci/verify_migration_lockfile.py`'s ledger: the file's path, its bytes' digest and
    its parent."""
    entry = json.loads(_LOCKFILE.read_text(encoding="utf-8"))["revisions"][_REV]
    assert entry == {
        "path": str(_FILE.relative_to(_REPO)),
        "sha256": hashlib.sha256(_FILE.read_bytes()).hexdigest(),
        "down_revision": _PREV,
    }


#: (origin, origin_ref) pairs the two CHECKs admit, and pairs they refuse, a type error included,
#: and the free arm's text one character past the store's bound (`MAX_ORIGIN_REF_CHARS`), which
#: the store refuses ahead of the CHECK, as the next revision to touch `orders` will.
_ADMITTED: list[tuple[object, object]] = [
    (None, None), ("rule", _RULE), ("hotkey", "F5"), ("ticket", None), ("api", "not-a-uuid"),
    ("algo_child", str(UUID(int=7))), ("hotkey", "x" * 64),
]  # fmt: skip
_REFUSED: list[tuple[object, object]] = [
    (None, "x"), (None, _RULE), ("rule", None), ("rule", "not-a-uuid"), ("rule", _RULE.upper()),
    ("manual", None), ("Rule", _RULE), ("ticket", 7), (["rule"], _RULE),
    ("hotkey", "x" * 65), ("api", "x" * 4096),
]  # fmt: skip
_NEW: dict[str, Any] = {
    "id": UUID(int=1), "exchange_account_id": UUID(int=2), "order_link_id": "cv",
    "symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Market",
    "qty": Decimal("0.010"),
}  # fmt: skip
_ROW: dict[str, Any] = dict.fromkeys(f.name for f in fields(OrderRow))


@pytest.mark.parametrize(("origin", "ref"), _ADMITTED)
def test_a_row_keeps_an_origin_the_checks_admit(origin: object, ref: object) -> None:
    pair: dict[str, Any] = {"origin": origin, "origin_ref": ref}
    order, row = NewOrder(**_NEW | pair), OrderRow(**_ROW | pair)
    assert (order.origin, order.origin_ref) == (row.origin, row.origin_ref) == (origin, ref)


@pytest.mark.parametrize(("origin", "ref"), _REFUSED)
def test_a_row_refuses_an_origin_the_checks_refuse_naming_no_value(
    origin: object, ref: object
) -> None:
    """`NewOrder` and `OrderRow` refuse, before any statement, what `ord_origin` and
    `ord_origin_ref` refuse (`require_origin`), and the refusal names no value."""
    pair: dict[str, Any] = {"origin": origin, "origin_ref": ref}
    for build in (lambda: NewOrder(**_NEW | pair), lambda: OrderRow(**_ROW | pair)):
        with pytest.raises(ValueError) as refused:
            build()
        named = (_RULE, "not-a-uuid", "manual", "x" * 65)
        assert all(value not in str(refused.value) for value in named)


def test_the_free_arm_of_origin_ref_is_bounded_at_sixty_four_characters() -> None:
    """The CHECK's third arm leaves `origin_ref` free for any origin but `rule`; the store holds
    that text to 64 characters, so a writer of another origin cannot store an unbounded value
    before the CHECK takes the bound with the next revision that touches `orders` (R1S-04):
    pinned at its edge for each of the six origins, and a rule's ref is its UUID alone."""
    assert MAX_ORIGIN_REF_CHARS == 64
    for origin in set(get_args(OrderOrigin)) - {"rule"}:
        require_origin(origin, "x" * 64)
        with pytest.raises(ValueError, match="at most 64 characters"):
            require_origin(origin, "x" * 65)
    with pytest.raises(ValueError, match="canonical UUID text"):
        require_origin("rule", "x" * 36)
