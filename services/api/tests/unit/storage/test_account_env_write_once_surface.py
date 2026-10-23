"""`exchange_accounts.env` is write-once in the application as well (#2333, C-2.11), and so are
`id`, `exchange_uid` and `kind` (#3968, SR-E27-13): an account's identity.

`trg_ea_env_write_once` (revision `0041_account_env_write_once`) refuses any change of `env` in the
database, and `trg_ea_identity_write_once` (`0050_ea_identity_write_once`) any change of `id`,
`exchange_uid` or `kind`. These tests hold the same premise in code, as `tests/unit/credentials_m2/
test_write_once_surface.py` does for `api_keys`: after the INSERT that creates an account, no SQL
string under `candleviewer/` assigns an identity column in an UPDATE or upsert of
`exchange_accounts`, and none MERGEs into it; the `exchange_accounts` Table is named in code only
where it is defined, to read it by the modules in `_READERS` (the profiles and trade-group stores),
and, in the pinned table of guarded privileges (#3998), as a `str` key of the dict display it
assigns to `GUARDED_PRIVILEGES` (any other reference there, a second dict's key included, is
flagged); and the PATCH body of `/exchange-accounts/{accountId}` carries no identity column. The
store's own patch and its typed error for a refusal are pinned in
`test_accounts_store_sqlalchemy.py`. They stop an honest regression, not a deliberate bypass: the
triggers are the enforcement.

The migrations are not scanned: they run as the schema owner, the trigger refuses them like any
other writer, and they hold the trigger's own SQL. Neither scan reads SQL assembled from parts
(f-string fragments, `+`): AGENTS.md §5.2 forbids string-built SQL and the
`cv-raw-sql-string-interpolation` Semgrep rule rejects it in `text()` and `execute()` calls.
"""

from __future__ import annotations

import ast
import re
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import UpdateExchangeAccountRequest
from candleviewer.storage.repositories import accounts_sqlalchemy as store
from tests.unit.credentials_m2._write_once import SqlWrite, writes_to

_API = Path(__file__).resolve().parents[3]
_PKG = _API / "candleviewer"
_CONTRACT = _API.parents[1] / "docs" / "plan" / "22-api-openapi.yaml"
_TABLE = "exchange_accounts"
_SQL_WRITE = re.compile(r"\b(?:update|insert\s+into|merge\s+into)\b", re.IGNORECASE)
#: Where the Table is defined; and the modules that name it in code, to read it only (each one
#: added here with its reason): the profiles store scopes a profile to a live account with
#: `exchange_accounts.c` and `select_from`; the trade-group store selects a group's accounts
#: FOR SHARE (`exchange_accounts.c`) to require them live while it inserts the legs (#905).
_DEFINITION = Path("db/models.py")
_READERS = frozenset(
    {
        Path("storage/repositories/account_profiles_sqlalchemy.py"),
        Path("storage/repositories/trade_groups_sqlalchemy.py"),
    }
)
_READS = frozenset({"import", "columns", "select_from"})
#: The pinned table of what the revisions revoke from `cv_app` (#3998) names the table only as a
#: `str` key of the dict display it assigns to `GUARDED_PRIVILEGES` (`key`), which the boot check
#: binds as a `has_table_privilege` parameter: no row is read or written. Any other reference in
#: it, a second dict's key or a Name or attribute key included, is still flagged.
_PRIVILEGE_TABLE = Path("storage/guarded_privileges.py")
_ENVIRONMENT = ("env", "environment")
#: The columns an account's identity is made of, each write-once in the database (0041, 0050).
_IDENTITY = ("env", "id", "exchange_uid", "kind")
#: The names a client could send for `id`, `exchange_uid` or `kind` (#3968).
_IDENTITY_FIELDS = ("id", "exchange_uid", "uid", "kind")


def _modules(root: Path) -> Iterator[tuple[Path, ast.Module]]:
    """`(path relative to root, parsed tree)` of each module under `root` that mentions the
    table, `migrations/versions` aside."""
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        source = path.read_text(encoding="utf-8")
        if rel.parts[:2] != ("migrations", "versions") and _TABLE in source.lower():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)  # a `\:` in some SQL text
                tree = ast.parse(source)
            yield rel, tree


def _prose(tree: ast.Module) -> set[ast.expr]:
    """Bare expression statements (docstrings): prose, not code."""
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Expr)}


# -- The SQL the application can send
def _sql(root: Path) -> list[tuple[str, str]]:
    """`(path:line, text)` of each string constant under `root` that names the table and reads as
    a write. Bare string statements (docstrings) are prose and skipped."""
    found = []
    for rel, tree in _modules(root):
        prose = _prose(tree)
        found += [
            (f"{rel.as_posix()}:{n.lineno}", n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n not in prose
            if _TABLE in n.value.lower() and _SQL_WRITE.search(n.value)
        ]
    return found


def _writes(sql: str) -> list[SqlWrite]:
    """`writes_to(sql)` for the table, or nothing for SQL the reader cannot read: `_risks`
    reports that."""
    try:
        return writes_to(sql, _TABLE)
    except ValueError:
        return []


def _risks(sql: str) -> list[str]:
    """Why `sql` could change an account's identity (`env`, `id`, `exchange_uid`, `kind`); empty
    when it cannot. A SET list that yields no column (`?`), a MERGE (its SET lists are not read) and
    unreadable SQL are risks too."""
    try:
        writes = writes_to(sql, _TABLE)
    except ValueError as exc:
        return [f"unreadable SQL ({exc})"]
    risks: list[str] = []
    for write in writes:
        if write.kind == "merge":
            risks.append("merge")
        elif write.kind in ("update", "upsert"):
            assigned = [column for column in _IDENTITY if column in write.targets]
            risks += assigned or ([] if write.targets else ["?"])
    return risks


def _scan(root: Path = _PKG) -> tuple[int, dict[str, list[str]]]:
    """`(UPDATEs read, {path:line: risks})` for the table's writes under `root`."""
    found = _sql(root)
    updates = sum(w.kind == "update" for _, sql in found for w in _writes(sql))
    return updates, {where: risks for where, sql in found if (risks := _risks(sql))}


def test_no_candleviewer_sql_changes_an_accounts_identity() -> None:
    updates, risks = _scan()
    assert updates >= 4  # the store's patch and soft delete, the self-check's disarm and its mark
    assert risks == {}


#: Ways the store's `_UPDATE` could assign `env`: the mutant the review of #3959 named, and others.
_ENV_ASSIGNMENTS = [
    "env = CAST('live' AS exchange_env), ",
    "env = :env, ",
    '"env" = :env, ',
    "(env, label) = (:e, :l), ",
]


@pytest.mark.parametrize("assignment", _ENV_ASSIGNMENTS)
def test_the_scan_flags_env_added_to_the_stores_patch(assignment: str) -> None:
    mutated = store._UPDATE.text.replace(" SET ", " SET " + assignment, 1)
    assert _risks(mutated) == ["env"]


#: Ways the store's `_UPDATE` could assign `id`, `exchange_uid` or `kind` (#3968), and the risk
#: flagged.
_UID_AND_KIND_ASSIGNMENTS = {
    "id": ("id = :new_id, ", ["id"]),
    "uid": ("exchange_uid = :exchange_uid, ", ["exchange_uid"]),
    "quoted uid": ('"exchange_uid" = :u, ', ["exchange_uid"]),
    "kind": ("kind = CAST('sub' AS account_kind), ", ["kind"]),
    "row of both": ("(exchange_uid, kind) = (:u, :k), ", ["exchange_uid", "kind"]),
}


@pytest.mark.parametrize(
    ("assignment", "risk"),
    list(_UID_AND_KIND_ASSIGNMENTS.values()),
    ids=list(_UID_AND_KIND_ASSIGNMENTS),
)
def test_the_scan_flags_an_identity_column_added_to_the_stores_patch(
    assignment: str, risk: list[str]
) -> None:
    mutated = store._UPDATE.text.replace(" SET ", " SET " + assignment, 1)
    assert _risks(mutated) == risk


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write `files` (relative path -> source) under `root`: a stand-in for `candleviewer/`."""
    for rel, source in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(source + "\n", encoding="utf-8")
    return root


#: A string that could change `env`, or that the reader cannot read, and the risk flagged.
_RISKY_SQL = {
    "update": ('S = "UPDATE exchange_accounts SET env = :e WHERE id = :id"', "env"),
    "aliased": ('S = "UPDATE ONLY public.exchange_accounts AS ea SET label = :l, env = :e"', "env"),
    "upsert": (
        'S = "INSERT INTO exchange_accounts AS ea (id) VALUES (:id) '
        'ON CONFLICT (id) DO UPDATE SET env = EXCLUDED.env"',
        "env",
    ),
    "merge": (
        'S = "MERGE INTO exchange_accounts a USING t ON a.id = t.id WHEN MATCHED THEN DO NOTHING"',
        "merge",
    ),
    "uid": ('S = "UPDATE exchange_accounts SET exchange_uid = :u WHERE id = :id"', "exchange_uid"),
    "kind upsert": (
        'S = "INSERT INTO exchange_accounts AS ea (id) VALUES (:id) '
        'ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind"',
        "kind",
    ),
    "concat": ('S = "UPDATE exchange_accounts SET " + columns', "?"),
    "dollar body": (
        'S = "DO $$ BEGIN UPDATE exchange_accounts SET env = 1; END $$"',
        "unreadable SQL (dollar quoting not supported)",
    ),
}
#: `(module, source, UPDATEs read)` the scan passes.
_SAFE_SQL = {
    "other columns": (
        "repo.py",
        'S = "UPDATE exchange_accounts SET label = :l, env_note = :n WHERE id = :id"',
        1,
    ),
    "row lock": ("repo.py", 'S = "SELECT env FROM exchange_accounts WHERE id = :id FOR UPDATE"', 0),
    "other table": ("repo.py", 'S = "UPDATE exchange_accounts_archive SET env = :e"', 0),
    "docstring": ("repo.py", '"""UPDATE exchange_accounts SET env = :e (prose, not SQL)."""', 0),
    "migration": (
        "migrations/versions/x.py",
        'op.execute("UPDATE exchange_accounts SET env = :e")',
        0,
    ),
}


@pytest.mark.parametrize(("source", "risk"), list(_RISKY_SQL.values()), ids=list(_RISKY_SQL))
def test_the_scan_flags_a_string_that_could_change_identity_or_cannot_be_read(
    tmp_path: Path, source: str, risk: str
) -> None:
    _, risks = _scan(_tree(tmp_path, {"repo.py": source}))
    assert risks == {"repo.py:1": [risk]}


@pytest.mark.parametrize(
    ("rel", "source", "updates"), list(_SAFE_SQL.values()), ids=list(_SAFE_SQL)
)
def test_the_scan_passes_a_string_that_cannot_change_identity(
    tmp_path: Path, rel: str, source: str, updates: int
) -> None:
    assert _scan(_tree(tmp_path, {rel: source})) == (updates, {})


# -- The Table, which Core and the ORM write through with no SQL string
def _pinned_keys(tree: ast.Module) -> set[ast.expr]:
    """The `str` keys of the dict display that a module-level `GUARDED_PRIVILEGES = ...` (plain or
    annotated) assigns, through a `MappingProxyType(...)` call or not; nothing else is exempt."""
    keys: set[ast.expr] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "GUARDED_PRIVILEGES" for t in targets):
            continue
        value = node.value
        match value:
            case ast.Call(func=ast.Name(id="MappingProxyType"), args=[inner]):
                value = inner
            case ast.Call(func=ast.Attribute(attr="MappingProxyType"), args=[inner]):
                value = inner
        if isinstance(value, ast.Dict):
            keys |= {
                k for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    return keys


def _shape(node: ast.AST, parent: ast.AST | None, pinned: set[ast.expr]) -> str | None:
    """How `node` names the Table: `import`, `columns` (`exchange_accounts.c`), `select_from`
    (its argument), `key` (one of the `pinned` keys of `GUARDED_PRIVILEGES`), `other`
    (`sa.update(exchange_accounts)`, `exchange_accounts.insert()`, an ORM `__tablename__`, a
    reflected `Table(...)`, any other dict key), or None when it does not name it."""
    match node:
        case ast.alias(name=name, asname=asname) if _TABLE in (name.rpartition(".")[2], asname):
            return "import"
        case ast.Name(id="exchange_accounts") | ast.Attribute(attr="exchange_accounts"):
            match parent:
                case ast.Attribute(attr="c", value=value) if value is node:
                    return "columns"
                case ast.Call(func=ast.Attribute(attr="select_from"), args=[arg]) if arg is node:
                    return "select_from"
            return "other"
        case ast.Constant(value="exchange_accounts"):
            return "key" if node in pinned else "other"
        case _:
            return None


def _table_uses(root: Path = _PKG) -> list[tuple[Path, int, str]]:
    """`(module, line, shape)` of each Python reference to the Table under `root`, outside
    `migrations/versions` (DDL); docstrings are prose and skipped."""
    found: list[tuple[Path, int, str]] = []

    def walk(
        node: ast.AST,
        parent: ast.AST | None,
        rel: Path,
        prose: set[ast.expr],
        pinned: set[ast.expr],
    ) -> None:
        if node not in prose and (shape := _shape(node, parent, pinned)) is not None:
            found.append((rel, int(getattr(node, "lineno", 0)), shape))
        for child in ast.iter_child_nodes(node):
            walk(child, node, rel, prose, pinned)

    for rel, tree in _modules(root):
        pinned = _pinned_keys(tree) if rel == _PRIVILEGE_TABLE else set()
        walk(tree, None, rel, _prose(tree), pinned)
    return found


def _table_writers(root: Path = _PKG) -> list[str]:
    """`path:line` of each reference that could write the Table: any outside its definition, the
    readers and the privilege table, in a reader any but a read, in the privilege table any but a
    `str` key of `GUARDED_PRIVILEGES`."""
    return [
        f"{rel.as_posix()}:{line}"
        for rel, line, shape in _table_uses(root)
        if rel != _DEFINITION
        and (rel != _PRIVILEGE_TABLE or shape != "key")
        and (rel not in _READERS or shape not in _READS)
    ]


def test_only_the_definition_and_the_listed_readers_name_the_accounts_table() -> None:
    seen = {_DEFINITION, _PRIVILEGE_TABLE, *_READERS}
    assert {rel for rel, _, _ in _table_uses()} == seen  # the scan sees all
    assert _table_writers() == []


_IN_READER = min(_READERS).as_posix()
#: The privilege table's own shape: an annotated assignment through `MappingProxyType(...)`.
_PINNED = (
    "GUARDED_PRIVILEGES: Final = MappingProxyType({'exchange_accounts': frozenset({'DELETE'})})"
)
#: `(module, source, path:line flagged)`: a reference that could write the Table.
_TABLE_WRITES = {
    "any use elsewhere": (
        "repo.py",
        "from candleviewer.db.models import exchange_accounts\n"
        "q = sa.select(exchange_accounts.c.id)",
        ["repo.py:1", "repo.py:2"],
    ),
    "module attribute": (
        "repo.py",
        "from candleviewer.db import models\nstmt = sa.update(models.exchange_accounts)",
        ["repo.py:2"],
    ),
    "orm mapping": (
        "repo.py",
        "class Account(Base):\n    __tablename__ = 'exchange_accounts'",
        ["repo.py:2"],
    ),
    "reflected": (
        "repo.py",
        "t = sa.Table('exchange_accounts', sa.MetaData(), autoload_with=engine)",
        ["repo.py:1"],
    ),
    "reader core update": (
        _IN_READER,
        "stmt = sa.update(exchange_accounts).values(env='live')",
        [f"{_IN_READER}:1"],
    ),
    "reader table update": (
        _IN_READER,
        "stmt = exchange_accounts.update().values(env='live')",
        [f"{_IN_READER}:1"],
    ),
    "privilege table reflects it": (
        _PRIVILEGE_TABLE.as_posix(),
        "t = sa.Table('exchange_accounts', sa.MetaData(), autoload_with=engine)",
        [f"{_PRIVILEGE_TABLE.as_posix()}:1"],
    ),
    "a dict key elsewhere": ("repo.py", "P = {'exchange_accounts': 1}", ["repo.py:1"]),
    "privilege table second dict": (
        _PRIVILEGE_TABLE.as_posix(),
        _PINNED + "\nOTHER = {'exchange_accounts': 1}",
        [f"{_PRIVILEGE_TABLE.as_posix()}:2"],
    ),
    "privilege table attribute key": (
        _PRIVILEGE_TABLE.as_posix(),
        "GUARDED_PRIVILEGES = {models.exchange_accounts: frozenset()}",
        [f"{_PRIVILEGE_TABLE.as_posix()}:1"],
    ),
    "privilege table name key": (
        _PRIVILEGE_TABLE.as_posix(),
        "GUARDED_PRIVILEGES = {exchange_accounts: frozenset()}",
        [f"{_PRIVILEGE_TABLE.as_posix()}:1"],
    ),
}
#: `(module, source)`: names the Table only to read it, or does not name it in code.
_TABLE_READS = {
    "reader reads": (
        _IN_READER,
        "from candleviewer.db.models import exchange_accounts\n_EA = exchange_accounts.c\n"
        "q = sa.select(_EA.id).select_from(exchange_accounts)",
    ),
    "foreign key": ("repo.py", "fk = ForeignKey('exchange_accounts.id')"),
    "read-only SQL": ("repo.py", "q = sa.text('SELECT id FROM exchange_accounts WHERE id = :id')"),
    "docstring": ("repo.py", '"""exchange_accounts"""'),
    "privilege table key": (_PRIVILEGE_TABLE.as_posix(), _PINNED),
    "privilege table plain dict": (
        _PRIVILEGE_TABLE.as_posix(),
        "GUARDED_PRIVILEGES = {'exchange_accounts': frozenset({'DELETE'})}",
    ),
    "its definition": (
        _DEFINITION.as_posix(),
        "exchange_accounts = Table('exchange_accounts', md)",
    ),
}


@pytest.mark.parametrize(
    ("rel", "source", "lines"), list(_TABLE_WRITES.values()), ids=list(_TABLE_WRITES)
)
def test_the_table_scan_flags_a_reference_that_could_write_it(
    tmp_path: Path, rel: str, source: str, lines: list[str]
) -> None:
    assert _table_writers(_tree(tmp_path, {rel: source})) == lines


@pytest.mark.parametrize(("rel", "source"), list(_TABLE_READS.values()), ids=list(_TABLE_READS))
def test_the_table_scan_passes_what_cannot_write_it(tmp_path: Path, rel: str, source: str) -> None:
    assert _table_writers(_tree(tmp_path, {rel: source})) == []


# -- The client-facing PATCH body
def _account_path_item() -> dict[str, Any]:
    """The contract's `/exchange-accounts/{accountId}` path item, parsed alone: the whole file
    takes seconds to parse, this item milliseconds."""
    text = _CONTRACT.read_text(encoding="utf-8")
    item = re.search(r"^  /exchange-accounts/\{accountId\}:\n(.*?)^  \S", text, re.M | re.S)
    assert item is not None
    parsed: dict[str, Any] = yaml.safe_load(item.group(1))
    return parsed


def test_the_patch_body_has_no_environment_and_refuses_one() -> None:
    """`PATCH /exchange-accounts/{accountId}` takes `UpdateExchangeAccountRequest`, generated from
    the contract (`additionalProperties: false`): no `env` or `environment` field, and one sent
    anyway is refused, so the request never reaches the store."""
    body = _account_path_item()["patch"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/UpdateExchangeAccountRequest"}
    assert UpdateExchangeAccountRequest.model_config.get("extra") == "forbid"
    assert not set(_ENVIRONMENT) & set(UpdateExchangeAccountRequest.model_fields)
    for name in _ENVIRONMENT:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            UpdateExchangeAccountRequest.model_validate({"label": "renamed", name: "live"})


def test_the_patch_body_has_no_identity_column_and_refuses_one() -> None:
    """#3968 (SR-E27-13, AC-23): the same body carries no `id`, `exchange_uid` or `kind`, and one
    sent anyway is refused before the store."""
    assert not set(_IDENTITY_FIELDS) & set(UpdateExchangeAccountRequest.model_fields)
    for name in _IDENTITY_FIELDS:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            UpdateExchangeAccountRequest.model_validate({"label": "renamed", name: "sub"})
