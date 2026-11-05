"""Single-writer guard for the `bars_*` tables (E12 threat model BR-05, BR-08).

The bar tables have one production writer: `BarWriter` (`bars/writer.py`), which stamps every row
with its `source`, `generation`, `index` and `row_checksum` (`bars/rows.py`). The reader withholds
a row whose provenance does not verify, so a second path that writes rows without it would turn
valid bars into integrity failures. So no code under `candleviewer/` may write a `bars_*` row
but through `BarWriter`.

The scan reads the parsed code (`ast`), not raw text. It flags:
- a SQL statement that writes to a `bars_*` table (`INSERT INTO`, `UPDATE`, `COPY`,
  `MERGE INTO`, `TRUNCATE`; quoted or schema-qualified; f-string fields read as a stand-in);
- a row-write call (`write_rows`, `write_row`, ILP `row`/`dataframe`, asyncpg bulk copies)
  whose table argument is a `bars_*` name: a literal, an f-string starting `bars_`, a call to
  `table_for` (the one function that names a bar table for a write), or a module name assigned
  from one of those;
- a use of the bar tables' ILP schemas outside `storage/questdb/schemas.py` (a line serialiser
  needs one to write a row).
A second scan pins who names `table_for`: its definition and the writer only.
"""

from __future__ import annotations

import ast
import re
import warnings
from pathlib import Path

import pytest

from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.repositories.market_data import MarketDataRepository

_PACKAGE = Path(__file__).resolve().parents[3] / "candleviewer"
_WRITER = Path("bars/writer.py")
_ROWS = Path("bars/rows.py")
_SCHEMAS = Path("storage/questdb/schemas.py")
_NAME = r'(?:"?\w+"?\s*\.\s*)?"?bars_\w+"?'
_WRITE_SQL = re.compile(
    rf"\b(?:INSERT\s+INTO|UPDATE|COPY|MERGE\s+INTO|TRUNCATE(?:\s+TABLE)?)\s+{_NAME}",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_WRITE_CALLS = frozenset(
    {"write_rows", "write_row", "row", "dataframe", "copy_records_to_table", "copy_to_table"}
)
_TABLE_KEYWORDS = frozenset({"table", "table_name", "name"})
_TABLE_FOR = "table_for"
_SCHEMA_NAMES = re.compile(r"^(?:BAR_SCHEMAS_BY_FAMILY|BARS_[A-Z]+_SCHEMA)$")


def _parse(source: str) -> ast.Module:
    """Parse quietly: another module's invalid string escape is its own lint's business."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _name(node: ast.AST) -> str:
    """The last name of `x` or `a.b.x`."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _text(node: ast.AST) -> str | None:
    """A string constant, or an f-string with `x` standing in for each field."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "x" for v in node.values)
    return None


def _bars_table(node: ast.AST | None, tainted: set[str]) -> bool:
    """`node` evaluates to a `bars_*` table name."""
    if node is None:
        return False
    text = _text(node)
    if text is not None:
        return text.startswith("bars_")
    if isinstance(node, ast.Call):
        return _name(node.func) == _TABLE_FOR
    return isinstance(node, ast.Name) and node.id in tainted


def _tainted(tree: ast.AST) -> set[str]:
    """Names this module assigns a `bars_*` table name to (one pass per new name)."""
    names: set[str] = set()
    while True:
        before = len(names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
                if _bars_table(node.value, names):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    names.update(t.id for t in targets if isinstance(t, ast.Name))
        if len(names) == before:
            return names


def _findings(source: str) -> list[str]:
    """Each place in `source` that writes a `bars_*` row or picks up a bar table's ILP schema."""
    tree = _parse(source)
    tainted = _tainted(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        text = _text(node)
        if text is not None and _WRITE_SQL.search(_COMMENT.sub(" ", text)):
            found.append("statement")
        if isinstance(node, ast.Call) and _name(node.func) in _WRITE_CALLS:
            named = {k.arg: k.value for k in node.keywords if k.arg in _TABLE_KEYWORDS}
            first = node.args[0] if node.args else next(iter(named.values()), None)
            if _bars_table(first, tainted):
                found.append("write")
        elif isinstance(node, ast.Name | ast.Attribute) and _SCHEMA_NAMES.match(_name(node)):
            found.append("schema")
        elif isinstance(node, ast.ImportFrom):
            if any(_SCHEMA_NAMES.match(alias.name) for alias in node.names):
                found.append("schema")
    return found


def _table_for_users(source: str) -> bool:
    """`source` names `table_for` (a call, the function passed on, an import or a string)."""
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Name | ast.Attribute) and _name(node) == _TABLE_FOR:
            return True
        if isinstance(node, ast.alias) and node.name == _TABLE_FOR:
            return True
        if isinstance(node, ast.FunctionDef) and node.name == _TABLE_FOR:
            return True
        if isinstance(node, ast.Constant) and node.value == _TABLE_FOR:
            return True
    return False


@pytest.mark.parametrize(
    ("snippet", "finding"),
    [
        ('await w.write_rows("bars_time", rows, "ts")', "write"),
        ('await w.write_rows(f"bars_{family}", rows, "ts")', "write"),
        ('table = f"bars_{family}"\nawait self._writer.write_rows(table, rows, "ts")', "write"),
        ('t: str = "bars_tick"\nalias = t\nawait w.write_rows(alias, rows, "ts")', "write"),
        ('await w.write_rows(table="bars_range", rows=rows, ts_us_key="ts")', "write"),
        ('await w.write_rows(table_for(spec), rows, "ts")', "write"),
        ('await w.write_rows(rows_mod.table_for(spec), rows, "ts")', "write"),
        ('sender.row("bars_volume", symbols={}, columns={}, at=ts)', "write"),
        ('await conn.copy_records_to_table("bars_delta", records=rows)', "write"),
        ('await conn.execute("INSERT INTO bars_time (ts) VALUES ($1)", ts)', "statement"),
        ('await conn.execute("insert into \\"bars_tick\\" (ts) values ($1)", ts)', "statement"),
        ('await conn.execute(f"INSERT INTO {db}.bars_{kind} (ts) VALUES ($1)")', "statement"),
        ('await conn.execute("UPDATE bars_time SET close = 1")', "statement"),
        ('conn.execute("INSERT /* x */ INTO -- y\\n bars_renko (ts) VALUES (1)")', "statement"),
        ('await conn.execute("TRUNCATE TABLE bars_time")', "statement"),
        ('line = serialize_ilp_line(BAR_SCHEMAS_BY_FAMILY["time"], fields, ts)', "schema"),
        ("line = serialize_ilp_line(schemas.BARS_TIME_SCHEMA, fields, ts)", "schema"),
        ("from candleviewer.storage.questdb.schemas import BAR_SCHEMAS_BY_FAMILY", "schema"),
    ],
)
def test_the_guard_finds_every_form(snippet: str, finding: str) -> None:
    assert finding in _findings(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        'await w.write_rows("trades", rows, "ts")',
        'await w.write_rows(table, rows, "ts")',  # a pass-through: the caller names the table
        'await conn.fetch("SELECT ts FROM bars_time WHERE symbol = $1", sym)',
        'table = f"bars_{spec.kind}"\nmetric.labels(table, reason).inc()',
        "await conn.execute(\"INSERT INTO klines (note) VALUES ('bars_time')\")",
    ],
)
def test_the_guard_ignores_reads_labels_and_other_tables(snippet: str) -> None:
    assert _findings(snippet) == []


def test_only_the_bar_writer_writes_bars_rows() -> None:
    found = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_PACKAGE)
        if relative != _SCHEMAS and (hits := _findings(path.read_text("utf-8"))):
            found[relative] = sorted(set(hits))
    # `BarWriter._write_one` hands each batch to its sink under the name `table_for` gave it.
    assert found == {_WRITER: ["write"]}


def test_only_the_bar_writer_names_a_bar_table_for_a_write() -> None:
    users = {
        path.relative_to(_PACKAGE)
        for path in sorted(_PACKAGE.rglob("*.py"))
        if _table_for_users(path.read_text("utf-8"))
    }
    assert users == {_ROWS, _WRITER}


def test_the_market_data_repository_has_no_bars_writer() -> None:
    """BR-05: the storage repository reads bars; it never writes them (the bar writer does)."""
    assert not hasattr(QuestDbMarketDataRepository, "write_bars")
    assert not hasattr(MarketDataRepository, "write_bars")
    assert not [
        name
        for cls in (QuestDbMarketDataRepository, MarketDataRepository)
        for name in vars(cls)
        if name.startswith("write") and "bar" in name
    ]
