"""`auth.session_locked` is registered before `POST /auth/lock` emits it (E09-S03-F1, #4743).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, so the lock answers 503), so
the action is pinned here by name, independently of the registry; it stays on the writer, never the
journal-first lane (ADR-0037 Q1, as unlock's and extend's records); and the two docs that list the
vocabulary (24 section 15.5, the closed set; 21 section 3.10.1) are held to it.
"""

from __future__ import annotations

from pathlib import Path

from candleviewer.audit.actions import AUDIT_ACTIONS, LANE_ACTIONS, validate_action

ROOT = Path(__file__).resolve().parents[5]
_ACTION = "auth.session_locked"


def test_auth_session_locked_is_registered_by_exact_name() -> None:
    assert _ACTION in AUDIT_ACTIONS and validate_action(_ACTION) == _ACTION
    assert {a for a in AUDIT_ACTIONS if a.startswith("auth.session_lock")} == {_ACTION}


def test_auth_session_locked_stays_on_the_writer_never_the_lane() -> None:
    assert _ACTION not in LANE_ACTIONS


def test_the_docs_list_auth_session_locked_as_registered() -> None:
    plan = ROOT / "docs" / "plan"
    schema = (plan / "21-database-schema.md").read_text(encoding="utf-8")
    must_audit = schema.split("Actions that MUST be audited", 1)[1].split("\n\n", 1)[0]
    internal = (plan / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = " ".join(closed[: closed.index("\n### ")].split())
    for vocabulary in (must_audit, closed):
        assert f"`{_ACTION}`" in vocabulary
    assert f"`{_ACTION}` (not registered yet" not in closed
