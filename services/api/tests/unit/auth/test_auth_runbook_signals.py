"""`docs/ops/runbooks/auth-rbac.md`, "Session and invite signals (#2319)": the table is what an
on-call reads while investigating, so each cell is a finished statement and the probe row says what
the code does (#2319 review: its Audit-row cell stopped at "the counter is not")."""

from __future__ import annotations

import re
from pathlib import Path

from candleviewer.api import sessions
from candleviewer.api.sessions import (
    PROBE_AUDIT_WINDOW_S,
    PROBE_AUDITS_GLOBAL_PER_WINDOW,
    PROBE_AUDITS_PER_WINDOW,
)

_RUNBOOK = Path(__file__).resolve().parents[5] / "docs" / "ops" / "runbooks" / "auth-rbac.md"
#: Words a finished clause does not end on: a cell that does is cut off, or lost its last words.
_DANGLING = frozenset(
    "a an and are as at but by for if in is not of on or than the to was with".split()
)


def _rows() -> dict[str, list[str]]:
    """series (labels dropped) -> [meaning, audit row], from the table under the heading."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    rows: dict[str, list[str]] = {}
    for line in text[text.index("**Session and invite signals (#2319).**") :].splitlines():
        if line.startswith("| `"):
            series, *cells = (cell.strip() for cell in line.strip().strip("|").split("|"))
            rows[re.sub(r"\{.*\}", "", series).strip("`")] = cells
        elif rows:
            break  # the line after the table
    return rows


def test_no_signal_cell_ends_on_a_word_that_needs_another() -> None:
    rows = _rows()
    assert "auth_session_revoke_denied_total" in rows  # the table was read
    cells = [cell for row in rows.values() for cell in row]
    assert [c[-30:] for c in cells if re.findall(r"[a-z]+", c.lower())[-1] in _DANGLING] == []


def test_the_probe_row_gives_the_shipped_row_budgets_and_says_every_probe_is_counted() -> None:
    _, audit = _rows()["auth_session_revoke_denied_total"]
    assert PROBE_AUDIT_WINDOW_S == 60.0  # "a minute"
    per_user, overall = PROBE_AUDITS_PER_WINDOW, PROBE_AUDITS_GLOBAL_PER_WINDOW
    assert f"{per_user} a minute per user and {overall} overall" in audit
    assert "every probe is counted" in audit  # not budgeted; the past-budget tests prove it


def test_the_runbook_names_every_log_line_a_counted_probe_with_no_row_leaves() -> None:
    code = Path(sessions.__file__).read_text(encoding="utf-8")
    lines = set(re.findall(r'"(auth\.session_revoke_denied\.[a-z_]+)"', code))
    assert len(lines) == 4  # unaudited, audit_unavailable, audit_slow, audit_failed_late
    runbook = _RUNBOOK.read_text(encoding="utf-8")
    assert [line for line in sorted(lines) if f"`{line}`" not in runbook] == []
