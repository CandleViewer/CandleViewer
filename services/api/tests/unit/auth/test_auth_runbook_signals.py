"""`docs/ops/runbooks/auth-rbac.md`, "Session and invite signals (#2319)": the table is what an
on-call reads while investigating, so each cell is a finished statement and the probe row says what
the code does (#2319 review: its Audit-row cell stopped at "the counter is not"). The paragraphs
under it triage a probe hit by what its `object_id` finds in `sessions` (#3054)."""

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


def _paragraph(start: str) -> str:
    """The runbook paragraph that begins with *start*, on one line."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    assert start in text, f"the runbook has no paragraph that begins {start!r}"
    at = text.index(start)
    return " ".join(text[at : text.index("\n\n", at)].split())


def test_the_probe_triage_classifies_a_hit_whose_id_has_no_sessions_row() -> None:
    # #3054 (3): a hit is triaged by what its `object_id` finds in `sessions`. Another user's row
    # and the caller's own ended one were covered; an id with no row at all (never issued, or
    # reaped) is the third case, and the runbook says how to tell the two readings apart.
    triage = _paragraph("A lone `auth_session_revoke_denied_total` hit")
    assert "another user's row means a probe" in triage  # the part that was there
    no_row = _paragraph("A hit whose `object_id` has no `sessions` row")
    assert "never issued" in no_row and "reaped" in no_row
    assert "`audit_log`" in no_row and "`session_id`" in no_row  # the lookup that tells them apart
    assert "probe" in no_row  # and what to do with the answer


def test_the_failed_login_telemetry_names_the_mfa_refusal_of_a_disabled_user() -> None:
    # #3054 (1): the counter's runbook text lists the rows it counts, so it says that
    # `POST /auth/mfa/verify` also counts the `auth.login_failed` row of a user disabled since the
    # password step, on the method the request named.
    telemetry = _paragraph("Telemetry for failed logins:")
    assert "`user_disabled`" in telemetry and "disabled since the password step" in telemetry
