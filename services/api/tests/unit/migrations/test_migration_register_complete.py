"""21 Sec.9.4 keeps one row per Alembic revision, ascending, each naming its parent (C-11.2).

Reads the revision files and the plan document only; no database. A new revision without its
register row, a row naming no file, a duplicate row, an out-of-order row, a row whose Parent is not
the file's down_revision, or a second head fails here. Each failure mode has a seeded mutation test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _find_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "services" / "api" / "pyproject.toml").is_file():
            return parent
    raise AssertionError("repository root (services/api/pyproject.toml) not found")


_ROOT = _find_root()
_DOC = _ROOT / "docs" / "plan" / "21-database-schema.md"
_VERSIONS = _ROOT / "services" / "api" / "candleviewer" / "migrations" / "versions"
_START = "### 9.4 "
_END = "### 9.5 "
_PLAN_ERA = "#### Plan-era names with no revision file"

_ROW = re.compile(r"^\| `(\d{4}_[a-z0-9_]+)`\s*\|\s*(`\d{4}_[a-z0-9_]+`|-)[^|]*\|", re.MULTILINE)


def _register_text(doc: str) -> str:
    for heading in (_START, _END):
        assert doc.count(heading) == 1, f"21 must have exactly one '{heading}' heading"
    assert _PLAN_ERA in doc, f"21 Sec.9.4 lost its '{_PLAN_ERA}' heading"
    section = doc.split(_START, 1)[1].split(_END, 1)[0]
    assert _PLAN_ERA in section, f"'{_PLAN_ERA}' must sit inside Sec.9.4"
    return section.split(_PLAN_ERA, 1)[0]


def _rows(doc: str) -> list[tuple[str, str | None]]:
    """(revision id, parent id or None for the '-' root marker) per register row, in order."""
    return [
        (m.group(1), None if m.group(2) == "-" else m.group(2).strip("`"))
        for m in _ROW.finditer(_register_text(doc))
    ]


def _down_revision(path: Path) -> str | None:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "down_revision":
            return ast.literal_eval(node.value) if node.value else None
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "down_revision" for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert value is None or isinstance(value, str), f"{path.name}: down_revision type"
            return value
    raise AssertionError(f"{path.name} declares no down_revision")


def _heads(parents: dict[str, str | None]) -> list[str]:
    """The revisions no other revision names as its parent; Alembic needs exactly one."""
    named = set(parents.values())
    return sorted(r for r in parents if r not in named)


def _revision_ids() -> list[str]:
    return sorted(p.stem for p in _VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


def _problems(doc: str, files: list[str]) -> list[str]:
    rows = _rows(doc)
    ids = [r for r, _ in rows]
    found: list[str] = []
    found += [f"no row for {r}" for r in sorted(set(files) - set(ids))]
    found += [f"row without a file: {r}" for r in sorted(set(ids) - set(files))]
    found += [f"duplicate row: {r}" for r in sorted({r for r in ids if ids.count(r) > 1})]
    if ids != sorted(ids):
        found.append("rows are not ascending by revision id")
    for rev, parent in rows:
        if rev in files:
            actual = _down_revision(_VERSIONS / f"{rev}.py")
            if actual != parent:
                found.append(f"{rev}: row says {parent}, file says {actual}")
    return found


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_register_matches_revision_files() -> None:
    assert _problems(_doc(), _revision_ids()) == []


def test_register_has_a_parent_for_every_non_root_row() -> None:
    rows = _rows(_doc())
    assert len(rows) == len(_revision_ids()), "a register row lacks the Parent cell"
    with_parent = [r for r, p in rows if p is not None]
    assert len(with_parent) == len(rows) - 1, "exactly the root row may show '-'"
    assert [r for r, p in rows if p is None] == ["0001_identity_rbac_sessions_mfa"]


def test_revision_chain_has_a_single_head() -> None:
    parents = {i: _down_revision(_VERSIONS / f"{i}.py") for i in _revision_ids()}
    heads = _heads(parents)
    assert len(heads) == 1, f"expected one head, found {heads}"


def test_mutation_second_head_is_reported() -> None:
    parents = {i: _down_revision(_VERSIONS / f"{i}.py") for i in _revision_ids()}
    (head,) = _heads(parents)
    forked = parents | {"9999_zz_fork": parents[head]}  # a second child of the head's parent
    assert _heads(forked) == sorted([head, "9999_zz_fork"])


def test_down_revision_reads_a_plain_assignment(tmp_path: Path) -> None:
    plain = tmp_path / "0001_x.py"
    plain.write_text('revision = "0001_x"\ndown_revision = "0000_y"\n', encoding="utf-8")
    assert _down_revision(plain) == "0000_y"


def test_section_headings_are_asserted() -> None:
    for broken in (_doc().replace(_START, "### 9.4x ", 1), _doc().replace(_PLAN_ERA, "x", 1)):
        try:
            _register_text(broken)
        except AssertionError:
            continue
        raise AssertionError("a missing heading was not reported")


def _row_line(doc: str, rev: str) -> str:
    return next(ln for ln in doc.splitlines() if ln.startswith(f"| `{rev}`"))


def test_mutation_missing_row_is_reported() -> None:
    doc = _doc()
    mutated = doc.replace(_row_line(doc, "0004_instruments") + "\n", "", 1)
    assert mutated != doc
    assert "no row for 0004_instruments" in _problems(mutated, _revision_ids())


def test_mutation_stray_row_is_reported() -> None:
    doc = _doc()
    line = _row_line(doc, "0004_instruments")
    mutated = doc.replace(line, line.replace("0004_instruments", "0004_zz_ghost", 1), 1)
    assert "row without a file: 0004_zz_ghost" in _problems(mutated, _revision_ids())


def test_mutation_duplicate_row_is_reported() -> None:
    doc = _doc()
    line = _row_line(doc, "0004_instruments")
    mutated = doc.replace(line, line + "\n" + line, 1)
    assert "duplicate row: 0004_instruments" in _problems(mutated, _revision_ids())


def test_mutation_out_of_order_is_reported() -> None:
    doc = _doc()
    a, b = _row_line(doc, "0004_instruments"), _row_line(doc, "0005_mfa_totp_replay_guard")
    mutated = doc.replace(a + "\n" + b, b + "\n" + a, 1)
    assert mutated != doc
    assert "rows are not ascending by revision id" in _problems(mutated, _revision_ids())


def test_mutation_wrong_parent_is_reported() -> None:
    doc = _doc()
    line = _row_line(doc, "0008_system_events")
    mutated = doc.replace(
        line, line.replace("`0007_sessions_idle_timeout`", "`0004_instruments`", 1)
    )
    assert mutated != doc
    assert _problems(mutated, _revision_ids()) == [
        "0008_system_events: row says 0004_instruments, file says 0007_sessions_idle_timeout"
    ]
