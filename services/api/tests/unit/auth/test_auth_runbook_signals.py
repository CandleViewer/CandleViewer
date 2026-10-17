"""`docs/ops/runbooks/auth-rbac.md`, "Session and invite signals (#2319)": the table is what an
on-call reads while investigating, so each cell is a finished statement and the probe row says what
the code does (#2319 review: its Audit-row cell stopped at "the counter is not"). The paragraphs
under it triage a probe hit by what its `object_id` finds in `sessions` (#3054)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from candleviewer.api import sessions
from candleviewer.api.sessions import (
    PROBE_AUDIT_WINDOW_S,
    PROBE_AUDITS_GLOBAL_PER_WINDOW,
    PROBE_AUDITS_PER_WINDOW,
)

_RUNBOOK = Path(__file__).resolve().parents[5] / "docs" / "ops" / "runbooks" / "auth-rbac.md"
_SCHEMA = _RUNBOOK.parents[2] / "plan" / "21-database-schema.md"
_PACKAGE = Path(sessions.__file__).resolve().parents[1]  # `candleviewer/`
#: A statement that drops `sessions` rows, written as every repository here writes SQL
#: (`DELETE FROM drawings ...`): any case and spacing, the table quoted or schema-qualified.
_SESSIONS_ROW_DELETE = re.compile(r'\bDELETE\s+FROM\s+(?:"?\w+"?\.)?"?sessions\b', re.IGNORECASE)
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
    # #3054 (3) and its review: a hit is triaged by what its `object_id` finds in `sessions`.
    # Another user's row and the caller's own ended one were covered; an id with no row at all is
    # the third case. It is an unknown id, never called harmless (it may be another user's, leaked);
    # the runbook says how to tell a stale client from a probe, and what an empty lookup is worth.
    triage = _paragraph("A lone `auth_session_revoke_denied_total` hit")
    assert "another user's row means a probe" in triage  # the part that was there
    no_row = _paragraph("A hit whose `object_id` has no `sessions` row")
    assert "treat it as a probe unless the actor's own history explains it" in no_row
    assert "a missing row never makes a hit harmless" in no_row
    lookup = ("`audit_log`", "`session_id`", "`actor_user_id`")  # whose id it was, and the caller's
    assert [name for name in lookup if name not in no_row] == []
    assert "read several different ids with no row from one user as a probe" in no_row


def test_the_probe_triage_does_not_present_the_sessions_retention_as_shipped() -> None:
    # #3054 review: no code deletes a `sessions` row today. Section 7 of the schema doc is the
    # policy, and the paragraph says the job that applies it has not shipped.
    no_row = _paragraph("A hit whose `object_id` has no `sessions` row")
    assert "the job that applies it has not shipped" in no_row
    assert "`docs/plan/21-database-schema.md`" in no_row and "section 7" in no_row


def test_the_probe_triage_sends_the_session_id_search_through_the_indexes_the_schema_has() -> None:
    # #3054 review: `audit_log` has no `session_id` index, so a search on it alone scans the table.
    # The runbook says so, and points at the indexes that exist; if the schema ever indexes
    # `session_id`, this fails and the paragraph has to change.
    schema = _SCHEMA.read_text(encoding="utf-8")
    indexed = set(re.findall(r"^CREATE INDEX \w+\s+ON audit_log \(([^)]*)\)", schema, re.MULTILINE))
    assert {"actor_user_id, event_ts DESC", "action, event_ts DESC"} <= indexed
    assert [columns for columns in indexed if "session_id" in columns] == []
    no_row = _paragraph("A hit whose `object_id` has no `sessions` row")
    assert "`session_id` is not indexed" in no_row
    assert "start from the indexed `action` or `actor_user_id`" in no_row


@pytest.mark.parametrize(
    ("sql", "drops_sessions_rows"),
    [
        ("DELETE FROM sessions WHERE expires_at < :cutoff", True),
        ("delete\n    from public.sessions where true", True),
        ('DELETE FROM "public"."sessions" WHERE true', True),
        ("DELETE FROM sessions_rotation WHERE true", False),
        ("DELETE FROM replay_sessions WHERE id = :id", False),
        ("UPDATE sessions SET revoked_at = :now", False),
    ],
)
def test_the_sessions_row_delete_pattern_matches_the_table_and_no_other(
    sql: str, drops_sessions_rows: bool
) -> None:
    assert bool(_SESSIONS_ROW_DELETE.search(sql)) is drops_sessions_rows


def test_no_code_drops_a_sessions_row_while_the_runbook_says_the_job_has_not_shipped() -> None:
    # #3054 review: the wording pin above holds the sentence, not the fact. A job that drops
    # `sessions` rows (section 7 of the schema doc, 30 days after expiry) makes "today a missing row
    # means the id was never issued" false: an old id has no row either. This fails then, so the
    # job's author edits the no-row paragraph of the runbook and the pins above with it.
    droppers = [
        str(path.relative_to(_PACKAGE))
        for path in sorted(_PACKAGE.rglob("*.py"))
        if _SESSIONS_ROW_DELETE.search(path.read_text(encoding="utf-8"))
    ]
    assert droppers == [], (
        f"{droppers} drop `sessions` rows, but the no-row paragraph of "
        "docs/ops/runbooks/auth-rbac.md says the retention job has not shipped: update it "
        "and the probe-triage tests above"
    )


def test_the_failed_login_telemetry_names_the_mfa_refusal_of_a_disabled_user() -> None:
    # #3054 (1): the counter's runbook text lists the rows it counts, so it says that
    # `POST /auth/mfa/verify` also counts the `auth.login_failed` row of a user disabled since the
    # password step, on the method the request named.
    telemetry = _paragraph("Telemetry for failed logins:")
    assert "`user_disabled`" in telemetry and "disabled since the password step" in telemetry
