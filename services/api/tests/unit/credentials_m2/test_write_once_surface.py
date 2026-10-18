"""Write-once guard for `api_keys` ciphertext, application layer (#2336, slice 1 of 2).

The data AAD binds no `key_version` (Security sign-off on #835, deviation 2, SR-003). That is sound
only while a credential id is never re-sealed: every key version is its own row, so the row id
already pins it. These tests hold the premise in code: after INSERT, no M2 port method, no M10
statement and no in-memory fake path can change `PROTECTED_COLUMNS`. They pass on `main`, as a
regression guard; the Postgres trigger that enforces the same rule lands in slice 2. They stop an
honest regression, not a deliberate bypass: the trigger is the enforcement.

The SQL tripwire reads every string constant under `candleviewer/`, migrations included. A second
tripwire reads every Python reference to the `api_keys` Table outside `db/models.py` (which defines
it) and the migrations (DDL), so a SQLAlchemy Core or ORM write, which names the table with no SQL
string, is caught as well. The same SQL scan also pins the single writer of the non-protected
`last_used_at` column: the broker's debounced touch (21 §3.2.2, #2580). Neither reads SQL
assembled from parts (f-string fragments, `+`): AGENTS.md §5.2 forbids string-built SQL and the
`cv-raw-sql-string-interpolation` Semgrep rule rejects it in `text()` and `execute()` calls.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import re
import types
import typing
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.store import CredentialStore, InMemoryCredentialStore, KcvStore
from candleviewer.storage.repositories import credentials_sqlalchemy as adapter
from tests.unit.credentials_m2._helpers import _store
from tests.unit.credentials_m2._vectors import AuditLog, FakeClock, kek
from tests.unit.credentials_m2._write_once import (
    CIPHERTEXT_PARAMS,
    PROTECTED_COLUMNS,
    SqlWrite,
    writes_to,
)

_ADAPTER = adapter.SqlAlchemyCredentialStore
_PKG = Path(__file__).resolve().parents[3] / "candleviewer"
#: Modules that may name the `api_keys` Table in code (`db/models.py` defines it). One added here
#: can write through the Table with no SQL string: add it only after a security review.
_TABLE_USERS = frozenset({Path("db/models.py")})
#: `str` parameters a non-insert port method may take; any other `str` could carry ciphertext.
_PLAIN_STR = frozenset({"env", "dek_ref"})
#: `rewrap`'s `(action, fields)` (#2266) goes only to the injected audit-row builder, redacted
#: into `audit_log`. The SQL scan below pins what an api_keys UPDATE assigns, not what it binds.
_AUDIT_RECORD = ("audit", tuple[str, dict[str, str]])
#: The CAS kwargs of the in-memory checks: v(n) -> v(n+1), with its row record.
_CAS: dict[str, Any] = {"env": "demo", "audit": ("security.credential_rewrapped", {})}
_SQL_WRITE = re.compile(r"\b(?:update|insert\s+into|merge\s+into)\b", re.IGNORECASE)


def _methods(cls: type) -> dict[str, Callable[..., Any]]:
    """The public coroutine methods declared on `cls`: what the signature checks inspect."""
    return {
        n: f
        for n, f in vars(cls).items()
        if not n.startswith("_") and inspect.iscoroutinefunction(f)
    }


def _public(cls: type) -> set[str]:
    """Every public name on `cls`: a sync, decorated, property or inherited member included."""
    return {n for n in dir(cls) if not n.startswith("_")}


def _ports() -> set[str]:
    return _public(CredentialStore) | _public(KcvStore)


def _classes(hint: Any) -> set[Any]:
    """The non-None members of an annotation: `UUID | None` gives `{UUID}`."""
    union = typing.get_origin(hint) in (typing.Union, types.UnionType)
    return set(typing.get_args(hint) if union else (hint,)) - {type(None)}


def _ciphertext_carriers(method: Callable[..., Any]) -> list[str]:
    """Parameters of `method` that could carry a sealed value. A non-insert port method may take
    ids, versions, a limit, `env` and the wrapped-DEK ref; bytes, mappings, `Any` or any other
    `str` could hold ciphertext under an innocent name."""
    hints = typing.get_type_hints(method)
    carriers = []
    for name in inspect.signature(method).parameters:
        kinds = _classes(hints.get(name, typing.Any))
        audit = (name, hints.get(name)) == _AUDIT_RECORD
        plain = audit or kinds <= {UUID, int} or (kinds == {str} and name in _PLAIN_STR)
        if name != "self" and (name in CIPHERTEXT_PARAMS or not plain):
            carriers.append(name)
    return carriers


@pytest.mark.parametrize("surface", [CredentialStore, _ADAPTER], ids=["port", "adapter"])
def test_port_methods_other_than_insert_take_no_ciphertext(surface: type) -> None:
    port = _methods(CredentialStore)
    methods = {n: m for n, m in _methods(surface).items() if n in port}
    assert {"insert", "rewrap", "mark_revoked", "touch_last_used"} <= set(methods)
    carriers = {n: _ciphertext_carriers(m) for n, m in methods.items() if n != "insert"}
    assert {n: c for n, c in carriers.items() if c} == {}


def test_adapter_public_surface_is_exactly_the_credential_and_kcv_ports() -> None:
    assert _public(_ADAPTER) == _ports()


async def _reseal(self: object, key_id: UUID, blob: bytes) -> None: ...


class _Resealer:
    reseal = _reseal


def _hide_async(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A decorator that turns `async def` into a plain function returning the awaitable."""
    return lambda *args, **kwargs: fn(*args, **kwargs)


@pytest.mark.parametrize(
    "member",
    [
        lambda self, key_id, blob: None,
        property(lambda self: None),
        classmethod(lambda cls, key_id, blob: None),
        _hide_async(_reseal),
    ],
    ids=["sync method", "property", "classmethod", "decorated coroutine"],
)
def test_public_surface_check_sees_a_member_added_in_any_form(member: object) -> None:
    mutated = type("Mutated", (_ADAPTER,), {"reseal": member})
    assert _public(mutated) - _ports() == {"reseal"}


def test_public_surface_check_sees_an_inherited_member() -> None:
    mutated = type("Mutated", (_ADAPTER, _Resealer), {})
    assert _public(mutated) - _ports() == {"reseal"}


@pytest.mark.parametrize(
    "surface", [CredentialStore, _ADAPTER, InMemoryCredentialStore], ids=["port", "adapter", "fake"]
)
def test_port_rewrap_moves_only_the_wrap(surface: type) -> None:
    params = list(inspect.signature(vars(surface)["rewrap"]).parameters)
    assert params == ["self", "key_id", "env", "from_version", "dek_ref", "kek_version", "audit"]


# -- The M10 adapter's SQL
def _statements() -> dict[str, str]:
    """SQL text of every module-level `sa.text(...)` statement in the M10 credential adapter."""
    return {n: v.text for n, v in vars(adapter).items() if isinstance(v, sa.TextClause)}


def _protected_sets(sql: str) -> list[str]:
    """Protected columns an UPDATE of api_keys in `sql` assigns. A SET list that yields no column
    is reported as `?`: the guard cannot prove it safe."""
    hits: list[str] = []
    for write in writes_to(sql):
        if write.kind == "update":
            hits += sorted(write.targets & PROTECTED_COLUMNS) or ([] if write.targets else ["?"])
    return hits


def _overwrites(sql: str) -> list[str]:
    """`upsert` and `merge` writes to api_keys in `sql`: INSERT-or-replace re-seals by design."""
    return [w.kind for w in writes_to(sql) if w.kind in ("upsert", "merge")]


def _scopes_using(tree: ast.AST, name: str, scope: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """The class/function nesting of every read of the module-level name `name` under `tree`."""
    if isinstance(tree, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        scope += (tree.name,)
    read = isinstance(tree, ast.Name) and tree.id == name and isinstance(tree.ctx, ast.Load)
    found = [scope] if read else []
    for child in ast.iter_child_nodes(tree):
        found += _scopes_using(child, name, scope)
    return found


def test_adapter_update_statements_set_no_protected_column() -> None:
    statements = _statements()
    updating = {n for n, s in statements.items() if "update" in {w.kind for w in writes_to(s)}}
    assert {"_REVOKE", "_REWRAP", "_TOUCH"} <= updating  # the scan sees the real UPDATEs
    hits = {name: _protected_sets(sql) for name, sql in statements.items()}
    assert {name: cols for name, cols in hits.items() if cols} == {}


def test_adapter_has_no_upsert_or_merge_on_api_keys() -> None:
    statements = _statements()
    assert [w.kind for w in writes_to(statements["_INSERT"])] == ["insert"]  # the scan sees it
    assert {n: o for n, sql in statements.items() if (o := _overwrites(sql))} == {}


def test_adapter_inserts_api_keys_only_from_insert() -> None:
    inserting = {n for n, s in _statements().items() if "insert" in {w.kind for w in writes_to(s)}}
    tree = ast.parse(Path(adapter.__file__).read_text(encoding="utf-8"))
    assert inserting == {"_INSERT"}
    assert _scopes_using(tree, "_INSERT") == [("SqlAlchemyCredentialStore", "insert")]


# -- The in-memory fake the unit suites run on
def _protected(row: dict[str, Any]) -> dict[str, Any]:
    return {c: row[c] for c in sorted(PROTECTED_COLUMNS)}


async def test_in_memory_store_mutators_leave_ciphertext_unchanged(
    broker: CredentialBroker, store: InMemoryCredentialStore
) -> None:
    key_id = (await _store(broker)).key_id
    before = _protected(store.rows[key_id])
    await store.rewrap(key_id, from_version=1, dek_ref="v1:00", kek_version=2, **_CAS)
    store.activate(key_id, "rotating")
    await store.touch_last_used(key_id)
    await store.mark_revoked(key_id)
    row = store.rows[key_id]
    assert _protected(row) == before
    assert (row["kek_version"], row["status"], row["revoked"]) == (2, "rotating", True)


async def _apply(store: InMemoryCredentialStore, key_id: UUID, op: str, n: int) -> None:
    match op:
        case "revoke":
            await store.mark_revoked(key_id)
        case "rewrap":
            await store.rewrap(
                key_id, from_version=n, dek_ref=f"v1:{n:02x}", kek_version=n + 1, **_CAS
            )
        case "touch":
            await store.touch_last_used(key_id)
        case _:
            store.activate(key_id, ("pending", "active", "rotating", "revoked")[n % 4])


@settings(max_examples=60, deadline=None, derandomize=True)  # the same 60 sequences every run
@given(
    ops=st.lists(
        st.tuples(st.sampled_from(["revoke", "rewrap", "touch", "activate"]), st.integers(0, 3)),
        max_size=30,
    )
)
def test_in_memory_store_any_mutator_sequence_leaves_ciphertext_unchanged(
    ops: list[tuple[str, int]],
) -> None:
    async def run() -> None:
        store = InMemoryCredentialStore()
        broker = CredentialBroker(store, AuditLog(), kek(), clock=FakeClock())
        key_id = (await _store(broker)).key_id
        before = _protected(store.rows[key_id])
        for op, n in ops:
            await _apply(store, key_id, op, n)
        assert _protected(store.rows[key_id]) == before
        assert list(store.rows) == [key_id]

    asyncio.run(run())


# -- The broker mints every credential id
async def test_store_mints_a_fresh_credential_id_per_call(
    broker: CredentialBroker, store: InMemoryCredentialStore
) -> None:
    first = (await _store(broker)).key_id
    sealed = _protected(store.rows[first])
    second = (await _store(broker)).key_id  # the same account, label, key and secret again
    assert first != second
    assert {first.version, second.version} == {4}
    assert set(store.rows) == {first, second}
    assert _protected(store.rows[first]) == sealed  # the second call did not re-seal the first


def test_store_takes_no_credential_id_from_its_caller() -> None:
    params = inspect.signature(CredentialBroker.store).parameters
    hints = typing.get_type_hints(CredentialBroker.store)
    assert [n for n in params if UUID in _classes(hints.get(n))] == ["account_id"]


# -- Tripwire over all application code
def _api_keys_modules(root: Path) -> Iterator[tuple[Path, ast.Module]]:
    """`(path relative to root, parsed tree)` of each module under `root` that mentions api_keys."""
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "api_keys" in source.lower():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)  # migration 0001's `\:` in SQL text
                tree = ast.parse(source)
            yield path.relative_to(root), tree


def _prose(tree: ast.Module) -> set[ast.expr]:
    """Bare expression statements (docstrings): prose, not code."""
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Expr)}


def _api_keys_sql(root: Path = _PKG) -> list[tuple[str, str]]:
    """`(path:line, text)` of each string constant under `root` that names api_keys and reads as a
    write. Migrations are scanned too: they run as the schema owner and may backfill. Bare string
    statements (docstrings) are prose and skipped."""
    found = []
    for rel, tree in _api_keys_modules(root):
        prose = _prose(tree)
        found += [
            (f"{rel}:{n.lineno}", n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n not in prose
            if "api_keys" in n.value.lower() and _SQL_WRITE.search(n.value)
        ]
    return found


def _writes(sql: str) -> list[SqlWrite]:
    """`writes_to(sql)`, or nothing for SQL the reader cannot read: `_risks` reports that."""
    try:
        return writes_to(sql)
    except ValueError:
        return []


def _risks(sql: str) -> list[str]:
    """Why `sql` could re-seal an api_keys row; empty when it cannot. Unreadable SQL is a risk."""
    try:
        return _protected_sets(sql) + _overwrites(sql)
    except ValueError as exc:
        return [f"unreadable SQL ({exc})"]


def _sql_scan(root: Path = _PKG) -> tuple[int, dict[str, list[str]]]:
    """`(UPDATEs read, {path:line: reasons})` for the api_keys writes under `root`."""
    found = _api_keys_sql(root)
    updates = sum(w.kind == "update" for _, sql in found for w in _writes(sql))
    return updates, {where: risks for where, sql in found if (risks := _risks(sql))}


def test_no_candleviewer_sql_updates_a_protected_api_keys_column() -> None:
    updates, risks = _sql_scan()
    assert updates >= 3  # the scan reaches the adapter's three UPDATEs
    assert risks == {}


def _uses_of(name: str, root: Path = _PKG) -> list[tuple[str, tuple[str, ...]]]:
    """`(module, class/function nesting)` of every reference to `name` under `root`: an attribute
    read (a call, a bound-method callback, a `functools.partial` argument), an import of it, or the
    exact string `name` (a `getattr`). A `def name` is a definition, not a reference."""
    found: list[tuple[str, tuple[str, ...]]] = []

    def walk(node: ast.AST, rel: str, scope: tuple[str, ...]) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            scope += (node.name,)
        match node:
            case ast.Attribute(attr=attr) | ast.alias(name=attr) | ast.Constant(value=attr) if (
                attr == name
            ):
                found.append((rel, scope))
        for child in ast.iter_child_nodes(node):
            walk(child, rel, scope)

    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if name in source:
            walk(ast.parse(source), path.relative_to(root).as_posix(), ())
    return found


def test_only_the_debounced_touch_sets_api_keys_last_used_at() -> None:
    """#2580 (21 §3.2.2): one debouncer owns the write-amplification guard. The only SQL that
    updates `last_used_at` is the adapter's `_TOUCH`, run only by `touch_last_used`, which only the
    broker's debounced `_touch` reaches (INSERT column lists are not read: #2777)."""
    setting = [
        sql for _, sql in _api_keys_sql() for w in _writes(sql) if "last_used_at" in w.targets
    ]
    tree = ast.parse(Path(adapter.__file__).read_text(encoding="utf-8"))
    assert setting == [adapter._TOUCH.text]
    assert _scopes_using(tree, "_TOUCH") == [("SqlAlchemyCredentialStore", "touch_last_used")]
    assert _uses_of("touch_last_used") == [("secrets/broker.py", ("CredentialBroker", "_touch"))]
    adapter_module = "storage/repositories/credentials_sqlalchemy.py"
    assert [where for where in _uses_of("_TOUCH") if where[0] != adapter_module] == []


@pytest.mark.parametrize(
    "source",
    [
        "async def f(store, k):\n    await store.touch_last_used(k)",  # a direct call
        "def f(store):\n    return store.touch_last_used",  # a bound-method callback
        (
            "from functools import partial\n"
            "def f(store, k):\n    return partial(store.touch_last_used, k)"
        ),
        'def f(store, k):\n    return getattr(store, "touch_last_used")(k)',
    ],
)
def test_uses_of_sees_every_way_to_reach_the_touch(tmp_path: Path, source: str) -> None:
    assert _uses_of("touch_last_used", _tree(tmp_path, {"m.py": source})) == [("m.py", ("f",))]


def test_uses_of_ignores_a_definition_and_sees_an_import(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "store.py": "class S:\n    async def touch_last_used(self, k): ...",
            "other.py": "from repo import _TOUCH",
        },
    )
    assert _uses_of("touch_last_used", root) == []
    assert _uses_of("_TOUCH", root) == [("other.py", ())]


def _api_keys_line(node: ast.AST) -> int | None:
    """The line where `node` names the `api_keys` Table: the identifier (a name, an attribute, an
    import) or the exact string that `Table(...)`, `table(...)` or `__tablename__` take."""
    match node:
        case (
            ast.Name(id="api_keys")
            | ast.Attribute(attr="api_keys")
            | ast.Constant(value="api_keys")
        ):
            return node.lineno
        case ast.alias(name=name, asname=asname) if "api_keys" in (name.rpartition(".")[2], asname):
            return node.lineno
        case _:
            return None


def _api_keys_table_uses(root: Path = _PKG, allowed: frozenset[Path] = _TABLE_USERS) -> list[str]:
    """`path:line` of each Python reference to the `api_keys` Table under `root`, outside the
    `allowed` modules and the migrations (DDL). Core and ORM write through the Table with no SQL
    string at all, so `update(api_keys).values(secret_enc=...)` passes the string scan."""
    uses = set()
    for rel, tree in _api_keys_modules(root):
        if rel in allowed or rel.parts[0] == "migrations":
            continue
        prose = _prose(tree)
        uses |= {
            f"{rel}:{line}"
            for n in ast.walk(tree)
            if n not in prose and (line := _api_keys_line(n)) is not None
        }
    return sorted(uses)


def test_no_candleviewer_code_references_the_api_keys_table_outside_its_definition() -> None:
    assert _api_keys_table_uses() == []
    assert _api_keys_table_uses(allowed=frozenset())  # the scan reaches the Table definition


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write `files` (relative path -> source) under `root`: a stand-in for `candleviewer/`."""
    for rel, source in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(source + "\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("rel", "source", "risk"),
    [
        ("repo.py", 'S = "UPDATE api_keys SET secret_enc = :s WHERE id = :id"', "secret_enc"),
        ("repo.py", 'S = "UPDATE api_keys SET " + columns', "?"),
        (
            "repo.py",
            'S = "INSERT INTO api_keys SELECT 1 ON CONFLICT (id) DO UPDATE SET a = 1"',
            "upsert",
        ),
        ("migrations/x.py", 'op.execute("UPDATE api_keys SET enc_alg = :a")', "enc_alg"),
        (
            "repo.py",
            'M = "can\'t update api_keys now"',
            "unreadable SQL (unterminated quote in SQL)",
        ),
        (
            "repo.py",
            'M = "cannot update api_keys"',
            "unreadable SQL (no SET list found for the api_keys UPDATE)",
        ),
        (
            "migrations/x.py",
            'op.execute("DO $$ UPDATE api_keys SET id = id $$")',
            "unreadable SQL (dollar quoting not supported)",
        ),
    ],
    ids=["update", "concat", "upsert", "migration", "bad quote", "no SET list", "dollar body"],
)
def test_sql_tripwire_flags_a_string_that_could_re_seal_a_row_or_cannot_be_read(
    tmp_path: Path, rel: str, source: str, risk: str
) -> None:
    _, risks = _sql_scan(_tree(tmp_path, {rel: source}))  # a string it cannot read must not raise
    assert risks == {f"{rel}:1": [risk]}


@pytest.mark.parametrize(
    ("source", "updates"),
    [
        ('S = "SELECT id FROM api_keys WHERE id = :id"', 0),
        ('S = "UPDATE api_keys SET dek_ref = :d, kek_version = :v WHERE id = :id"', 1),
        ('S = "UPDATE api_keys_archive SET secret_enc = :s"', 0),
        ('"""UPDATE api_keys SET secret_enc = :s (a docstring, not SQL)."""', 0),
    ],
    ids=["select", "re-wrap columns", "other table", "docstring"],
)
def test_sql_tripwire_passes_a_string_that_cannot_re_seal_a_row(
    tmp_path: Path, source: str, updates: int
) -> None:
    assert _sql_scan(_tree(tmp_path, {"repo.py": source})) == (updates, {})


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        (
            "from candleviewer.db.models import api_keys\nstmt = update(api_keys).values(a=1)",
            ["repo.py:1", "repo.py:2"],
        ),
        (
            "from candleviewer.db import models\nstmt = sa.update(models.api_keys).values(a=1)",
            ["repo.py:2"],
        ),
        ("from candleviewer.db.models import api_keys as keys", ["repo.py:1"]),
        ("class ApiKey(Base):\n    __tablename__ = 'api_keys'", ["repo.py:2"]),
        ("t = sa.Table('api_keys', sa.MetaData(), autoload_with=engine)", ["repo.py:1"]),
    ],
    ids=["imported name", "module attribute", "import alias", "orm mapping", "reflected table"],
)
def test_table_tripwire_flags_a_core_or_orm_reference_to_the_api_keys_table(
    tmp_path: Path, source: str, lines: list[str]
) -> None:
    assert _api_keys_table_uses(_tree(tmp_path, {"repo.py": source})) == lines


@pytest.mark.parametrize(
    ("rel", "source"),
    [
        ("repo.py", "fk = ForeignKey('api_keys.id')"),
        ("repo.py", "q = sa.text('SELECT id FROM api_keys WHERE id = :id')"),
        ("repo.py", '"""api_keys"""'),
        ("db/models.py", "api_keys = Table('api_keys', metadata)"),
        ("migrations/x.py", "op.create_table('api_keys')"),
    ],
    ids=["foreign key", "read-only SQL", "docstring", "its definition", "migration DDL"],
)
def test_table_tripwire_passes_what_does_not_name_the_table_in_code(
    tmp_path: Path, rel: str, source: str
) -> None:
    assert _api_keys_table_uses(_tree(tmp_path, {rel: source})) == []


# -- The guard itself: it must see what it claims to see
@pytest.mark.parametrize(
    ("head", "tail"),  # where `column = :x` sits in the SET list: first, last, behind a CASE
    [
        ("{c} = :x, ", ""),
        ("", ", {c} = :x"),
        ("status = CASE WHEN :r THEN 'a' ELSE status END, ", ", {c} = :x"),
    ],
    ids=["first", "last", "behind-case"],
)
@pytest.mark.parametrize("column", sorted(PROTECTED_COLUMNS))
@pytest.mark.parametrize("name", ["_REVOKE", "_REWRAP", "_TOUCH"])
def test_guard_flags_a_protected_column_added_to_an_adapter_update(
    name: str, column: str, head: str, tail: str
) -> None:
    mutated = (
        _statements()[name]
        .replace(" SET ", " SET " + head.format(c=column), 1)
        .replace(" WHERE ", tail.format(c=column) + " WHERE ", 1)
    )
    assert column in _risks(mutated)


def test_guard_flags_an_update_of_the_key_id_tail() -> None:
    """`key_id_last4` comes from the plaintext key id at INSERT: it freezes with the sealed id."""
    assert _risks("UPDATE api_keys SET key_id_last4 = :t WHERE id = :id") == ["key_id_last4"]


def test_guard_flags_an_upsert_added_to_the_adapter_insert() -> None:
    mutated = _statements()["_INSERT"] + " ON CONFLICT (id) DO UPDATE SET label = :label"
    assert "upsert" in _risks(mutated)


def test_guard_flags_an_update_whose_set_list_it_cannot_read() -> None:
    assert _risks("UPDATE api_keys SET ") == ["?"]


_PROBES = [  # (sql, the writes found as "kind:columns", space separated)
    ("update API_KEYS set Secret_Enc = :s where id = :id", "update:secret_enc"),
    ('UPDATE api_keys SET "enc_alg" = :a', "update:enc_alg"),
    ("UPDATE api_keys SET a = coalesce(b, c), d = 'x, id = 1' -- , e", "update:a,d"),
    ("UPDATE api_keys SET a = E'it\\'s, id = x', b = 2", "update:a,b"),
    ("UPDATE api_keys SET (enc_nonce, a) = (:n, 1), b = 2", "update:a,b,enc_nonce"),
    ("UPDATE ONLY public.api_keys AS k SET id = :i FROM t", "update:id"),
    ("UPDATE api_keys * SET secret_enc = :s", "update:secret_enc"),
    ("UPDATE ONLY api_keys * AS k SET id = :i", "update:id"),
    ("UPDATE api_keys SET a = x IS DISTINCT FROM y, id = :i", "update:a,id"),
    (
        "UPDATE api_keys SET a = CASE WHEN :r THEN 1 ELSE 2 END, secret_enc = :s",
        "update:a,secret_enc",
    ),
    ("UPDATE api_keys SET a = CASE b WHEN 1 THEN 2 END, id = :i", "update:a,id"),
    ("UPDATE api_keys SET a = ARRAY[x, 1] || secret_enc, b = c[1, 2] || id", "update:a,b"),
    ("UPDATE api_keys SET ip_whitelist[id] = :x, a = 1", "update:a,ip_whitelist"),
    ("WITH m AS (UPDATE api_keys SET dek_ref = :d RETURNING id) SELECT 1", "update:dek_ref"),
    ("INSERT INTO api_keys SELECT 1 ON CONFLICT (id) DO UPDATE SET a = 1", "insert: upsert:a"),
    ("MERGE INTO api_keys k USING t ON k.id = t.id WHEN MATCHED THEN UPDATE SET a = 1", "merge:"),
    ("SELECT id FROM api_keys FOR UPDATE", ""),
    ("UPDATE api_keys_archive SET secret_enc = :s", ""),
]


@pytest.mark.parametrize(("sql", "expected"), _PROBES)
def test_writes_to_reads_set_targets_through_literals_comments_quoting_and_expressions(
    sql: str, expected: str
) -> None:
    assert " ".join(f"{w.kind}:{','.join(sorted(w.targets))}" for w in writes_to(sql)) == expected


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("UPDATE api_keys SET a = 'x, secret_enc = :s", "unterminated quote"),
        ('UPDATE api_keys SET a = 1, "secret_enc = :s', "unterminated quote"),
        ("DO $$ BEGIN UPDATE api_keys SET id = 1; END $$", "dollar quoting"),
        ("UPDATE api_keys SET label = $q$ where $q$, secret_enc = :s", "dollar quoting"),
        ("UPDATE api_keys SET label = $1, secret_enc = :s", "dollar quoting"),
        ("UPDATE api_keys WHERE id = :id", "SET list"),
        ("UPDATE api_keys", "SET list"),
        ("UPDATE api_keys AS k, other SET a = 1", "SET list"),
    ],
)
def test_writes_to_refuses_sql_it_cannot_read_instead_of_under_reading_it(
    sql: str, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        writes_to(sql)


_COLUMNS = ("a", "b", "id", "secret_enc", "enc_nonce")  # plain and protected names
_ATOMS = st.sampled_from(
    list(_COLUMNS)
    + [f'"{c}"' for c in _COLUMNS]
    + ["1", "NULL", ":p", "now()", "'x, id = 1'", "'it''s'", "E'it\\'s, secret_enc'"]
)


def _expressions(e: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    """Expressions built from `e`: commas, CASE branches, clause words and comments in places a
    SET-list reader must not mistake for the end of an assignment or the start of a new one."""
    return st.one_of(
        st.builds("coalesce({}, {})".format, e, e),
        st.builds("CASE WHEN {} THEN {} ELSE {} END".format, e, e, e),
        st.builds("CASE {} WHEN {} THEN {} END".format, e, e, e),
        st.builds("ARRAY[{}, {}]".format, e, e),
        st.builds("{}[1, {}]".format, e, e),
        st.builds("{} IS NOT DISTINCT FROM {}".format, e, e),
        st.builds("({})".format, e),
        st.builds("(SELECT {} FROM t WHERE {})".format, e, e),
        st.builds("{} /* , secret_enc = 1 */".format, e),
        st.builds("{} -- , id = 1\n".format, e),
    )


def _single(column: str, value: str, quote: str) -> tuple[list[str], str]:
    return [column], f"{quote.format(column)} = {value}"


def _several(columns: list[str], value: str, quote: str) -> tuple[list[str], str]:
    names, values = ", ".join(quote.format(c) for c in columns), ", ".join([value] * len(columns))
    return columns, f"({names}) = ROW({values})"


_VALUES = st.recursive(_ATOMS, _expressions, max_leaves=6)
_QUOTING = st.sampled_from(["{}", '"{}"'])
_ASSIGNMENTS = st.one_of(
    st.builds(_single, st.sampled_from(_COLUMNS), _VALUES, _QUOTING),
    st.builds(
        _several,
        st.lists(st.sampled_from(_COLUMNS), min_size=2, max_size=3, unique=True),
        _VALUES,
        _QUOTING,
    ),
)
_HEADS = ["UPDATE api_keys", "UPDATE ONLY public.api_keys AS k", 'UPDATE "api_keys" *']
_TAILS = ["", " WHERE id = :id", " FROM t WHERE t.id = id RETURNING id", ";"]


@settings(max_examples=250, deadline=None, derandomize=True)  # the same 250 lists every run
@given(
    assignments=st.lists(_ASSIGNMENTS, min_size=1, max_size=4),
    head=st.sampled_from(_HEADS),
    tail=st.sampled_from(_TAILS),
)
def test_writes_to_reads_exactly_the_assigned_columns_whatever_the_expressions(
    assignments: list[tuple[list[str], str]], head: str, tail: str
) -> None:
    sql = f"{head} SET {', '.join(text for _, text in assignments)}{tail}"
    assigned = frozenset(c for columns, _ in assignments for c in columns)
    assert writes_to(sql) == [SqlWrite("update", assigned)]
