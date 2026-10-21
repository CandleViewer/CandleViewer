"""#3998 tripwire: `GUARDED_PRIVILEGES` pins exactly what the revisions revoke from `cv_app`.

Each revision's `upgrade()` is read with the module-level strings and helpers it names, never its
`downgrade()`, whose re-GRANT is a rollback and not the head's grants, in chain order
(`down_revision`). Every `REVOKE <privileges> ON <tables> FROM ... cv_app` is collected, inside
`EXECUTE '...'` strings too, and a later table-level `GRANT ... TO cv_app` (or `TO PUBLIC`) takes
its privilege back out; a column grant (`GRANT UPDATE (replayed_at)`, 0033) gives back no table
privilege. A REVOKE with no pinned entry fails, so does an entry with no REVOKE, and so does a
statement naming the role in a shape this reader does not know: nothing is skipped silently.
Tip-agnostic, like `test_revision_ids.py`: a new revision is read without a change here.
"""

from __future__ import annotations

import ast
import re
import warnings
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from candleviewer.storage.guarded_privileges import GUARDED_PRIVILEGES

_VERSIONS = Path(__file__).resolve().parents[3] / "candleviewer" / "migrations" / "versions"
_ROLE = "cv_app"
_TABLE_PRIVILEGES = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN"}
)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
#: One GRANT or REVOKE, to its `;`, the `'` that closes an `EXECUTE` string, or the text's end.
_STATEMENT = re.compile(r"\b(GRANT|REVOKE)\b(.*?)(?=;|'|\Z)", re.I | re.S)
_SHAPE = {
    "REVOKE": re.compile(
        r"\s+(?P<privileges>.+?)\s+ON\s+(?:TABLE\s+)?(?P<objects>.+?)\s+FROM\s+(?P<roles>.+?)"
        r"(?:\s+(?:CASCADE|RESTRICT))?\s*",
        re.I | re.S,
    ),
    "GRANT": re.compile(
        r"\s+(?P<privileges>.+?)\s+ON\s+(?:TABLE\s+)?(?P<objects>.+?)\s+TO\s+(?P<roles>.+?)"
        r"(?:\s+WITH\s+GRANT\s+OPTION)?\s*",
        re.I | re.S,
    ),
}
#: Objects that are not tables (0037's `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC`).
_NOT_A_TABLE = re.compile(
    r"(?:FUNCTION|PROCEDURE|ROUTINE|SEQUENCE|SCHEMA|DATABASE|DOMAIN|TYPE|LANGUAGE|TABLESPACE"
    r"|LARGE\s+OBJECT|FOREIGN|PARAMETER|ALL\s+(?:FUNCTIONS|PROCEDURES|ROUTINES|SEQUENCES))\b",
    re.I,
)
_PRIVILEGE = re.compile(
    r"\s*(?P<name>[A-Za-z]+(?:\s+PRIVILEGES)?)\s*(?P<columns>\([^)]*\))?\s*", re.I
)
_TABLE = re.compile(r'\s*(?:"?public"?\.)?"?(?P<name>[a-z_][a-z0-9_]*)"?\s*')

Effects = dict[str, set[str]]


def _assigned(tree: ast.Module, name: str) -> object:
    """The constant a module-level `name = ...` (plain or annotated) assigns; None if absent."""
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        value = getattr(node, "value", None)
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and value is not None:
            return ast.literal_eval(value)
    return None


def _upgrade_sql(tree: ast.Module) -> Iterator[str]:
    """The strings `upgrade()` runs, in source order: its literals and those of the module-level
    constants and helpers it names, each once; an f-string or a `+` with `{}` for each value."""
    scope: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name != "downgrade":
            scope[node.name] = node
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            scope.update({t.id: node.value for t in targets if isinstance(t, ast.Name)})
    seen: set[str] = {"upgrade"}

    def visit(node: ast.AST) -> Iterator[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            parts = (str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values)
            yield "".join(parts)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            yield "".join("".join(visit(side)) or "{}" for side in (node.left, node.right))
        elif isinstance(node, ast.Name) and node.id in scope and node.id not in seen:
            seen.add(node.id)
            yield from visit(scope[node.id])
        else:
            for child in ast.iter_child_nodes(node):
                yield from visit(child)

    yield from visit(scope["upgrade"])


def _chain(sources: Mapping[str, str]) -> list[ast.Module]:
    """The revision modules in apply order, from the root (`down_revision = None`) to the head."""
    by_parent: dict[object, tuple[object, ast.Module]] = {}
    for name, source in sources.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # a `\:` in 0001's SQL text
            tree = ast.parse(source)
        parent = _assigned(tree, "down_revision")
        assert parent not in by_parent, f"{name}: a second child of {parent!r}"
        by_parent[parent] = (_assigned(tree, "revision"), tree)
    chain: list[ast.Module] = []
    parent = None
    while parent in by_parent:
        parent, tree = by_parent.pop(parent)
        chain.append(tree)
    assert not by_parent, f"revisions off the chain: {sorted(map(str, by_parent))}"
    return chain


def _privileges(text: str) -> set[str] | None:
    """The table-level privileges a list names, or None if it is not a privilege list. A column
    item (`UPDATE (replayed_at)`) neither grants nor revokes the table privilege."""
    found: set[str] = set()
    for item in re.split(r",(?![^(]*\))", text):
        match = _PRIVILEGE.fullmatch(item)
        if match is None:
            return None
        name = " ".join(match["name"].upper().split())
        named = _TABLE_PRIVILEGES if name in {"ALL", "ALL PRIVILEGES"} else {name}
        if not named <= _TABLE_PRIVILEGES:
            return None
        if match["columns"] is None:
            found |= named
    return found


def _effects(sources: Mapping[str, str]) -> tuple[Effects, list[str]]:
    """What the upgrades leave revoked from `cv_app`, per table, and each statement naming the role
    that does not parse."""
    revoked: Effects = {}
    unread: list[str] = []
    for tree in _chain(sources):
        for sql in _upgrade_sql(tree):
            for verb, body in _STATEMENT.findall(_COMMENT.sub(" ", sql)):
                verb, statement = verb.upper(), " ".join(f"{verb} {body}".split())
                shape = _SHAPE[verb].fullmatch(body)
                if shape is None:
                    if re.search(rf"\b{_ROLE}\b", body, re.I):
                        unread.append(statement)
                    continue
                roles = {r.strip().strip('"').lower() for r in shape["roles"].split(",")}
                if _ROLE not in roles and (verb == "REVOKE" or "public" not in roles):
                    continue
                if _NOT_A_TABLE.match(shape["objects"]):
                    continue
                tables = [_TABLE.fullmatch(t) for t in shape["objects"].split(",")]
                privileges = _privileges(shape["privileges"])
                if privileges is None or any(t is None for t in tables):
                    unread.append(statement)
                    continue
                for table in (t["name"] for t in tables if t is not None):
                    if verb == "REVOKE":
                        revoked.setdefault(table, set()).update(privileges)
                    else:
                        revoked.get(table, set()).difference_update(privileges)
    return {t: p for t, p in revoked.items() if p}, unread


def _drift(pinned: Mapping[str, frozenset[str]], revoked: Effects) -> list[str]:
    """Each difference between the pinned table and what the revisions revoke, as a fix to make."""
    out: list[str] = []
    for table in sorted(pinned.keys() | revoked.keys()):
        want, have = revoked.get(table, set()), pinned.get(table, frozenset())
        out += [f"pin {table} {p}: a revision revokes it" for p in sorted(want - have)]
        out += [f"unpin {table} {p}: no revision revokes it" for p in sorted(have - want)]
    return out


def _revision(rev: str, parent: str | None, up: str, down: str = "''") -> str:
    """A revision's source; `up` and `down` are the expressions their `op.execute` runs."""
    return (
        f"revision = {rev!r}\ndown_revision = {parent!r}\n"
        f"def upgrade():\n    op.execute({up})\n"
        f"def downgrade():\n    op.execute({down})\n"
    )


def test_guarded_privileges_are_what_the_revisions_revoke_from_cv_app() -> None:
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(_VERSIONS.glob("*.py"))}
    revoked, unread = _effects(sources)
    assert unread == [], "a GRANT or REVOKE naming cv_app that this tripwire cannot read"
    assert _drift(GUARDED_PRIVILEGES, revoked) == [], "storage/guarded_privileges.py"


def test_tripwire_fails_on_a_revoke_with_no_entry_and_an_entry_with_no_revoke() -> None:
    up = "DO $B$ BEGIN EXECUTE 'REVOKE DELETE, TRUNCATE ON t1, public.t2 FROM cv_app'; END $B$;"
    revoked, _ = _effects({"a.py": _revision("a", None, repr(up))})
    pinned = {"t1": frozenset({"DELETE", "TRUNCATE"}), "t3": frozenset({"DELETE"})}
    assert _drift(pinned, revoked) == [
        "pin t2 DELETE: a revision revokes it",
        "pin t2 TRUNCATE: a revision revokes it",
        "unpin t3 DELETE: no revision revokes it",
    ]


def test_tripwire_reads_upgrade_only_and_a_later_table_grant_gives_a_privilege_back() -> None:
    up_b = "GRANT DELETE ON t1 TO PUBLIC; GRANT UPDATE (c) ON t2 TO cv_app;"
    up_a, down_a = "REVOKE DELETE, UPDATE ON t1, t2 FROM cv_app, cv_ro", "GRANT ALL ON t2 TO cv_app"
    sources = {  # listed out of apply order: the chain, not the file order, decides "later"
        "b.py": _revision("b", "a", repr(up_b)),
        "a.py": _revision("a", None, repr(up_a), repr(down_a)),
    }
    assert _effects(sources) == ({"t1": {"UPDATE"}, "t2": {"DELETE", "UPDATE"}}, [])


@pytest.mark.parametrize(
    ("up", "statement"),
    [
        ("'GRANT pg_write_all_data TO cv_app'", None),
        ("'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cv_app'", None),
        ("'REVOKE GRANT OPTION FOR DELETE ON t1 FROM cv_app'", None),
        ("f'REVOKE {verbs} ON t1 FROM cv_app'", "REVOKE {} ON t1 FROM cv_app"),
        ("'REVOKE {} ON t1 FROM cv_app'.format(verbs)", "REVOKE {} ON t1 FROM cv_app"),
        ("'REVOKE DELETE ON ' + table + ' FROM cv_app'", "REVOKE DELETE ON {} FROM cv_app"),
    ],
)
def test_tripwire_reports_a_statement_naming_cv_app_that_it_cannot_read(
    up: str, statement: str | None
) -> None:
    expected = statement or ast.literal_eval(up)
    assert _effects({"a.py": _revision("a", None, up)}) == ({}, [expected])


def test_tripwire_skips_other_roles_objects_and_comments() -> None:
    up = (
        "-- REVOKE DELETE ON t1 FROM cv_app\nREVOKE DELETE ON t1 FROM cv_ro;\n"
        "REVOKE EXECUTE ON FUNCTION f() FROM PUBLIC; GRANT USAGE ON SCHEMA public TO cv_app;"
    )
    assert _effects({"a.py": _revision("a", None, repr(up))}) == ({}, [])
