"""The `watchlist.*` audit actions are registered before any route emits them (E08-T07, #4706).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, so the write is refused), so
the three actions are pinned here by name, independently of the registry, and the two docs that
list the vocabulary (24 section 15.5, the closed set; 21 section 3.10.1) are held to them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action

ROOT = Path(__file__).resolve().parents[5]
_ACTIONS = frozenset({"watchlist.created", "watchlist.updated", "watchlist.deleted"})


def test_the_three_watchlist_actions_are_registered_by_exact_name() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("watchlist")} == _ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS


@pytest.mark.parametrize("name", ["watchlist.renamed", "watchlist.reordered", "watchlists.update"])
def test_a_watchlist_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """E08-D07's analytics events (`.renamed`, `.reordered`, ...) are not audit actions: a rename
    or a reorder is a replace, recorded `watchlist.updated`."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_the_docs_list_the_three_watchlist_actions() -> None:
    plan = ROOT / "docs" / "plan"
    schema = (plan / "21-database-schema.md").read_text(encoding="utf-8")
    must_audit = schema.split("Actions that MUST be audited", 1)[1].split("\n\n", 1)[0]
    internal = (plan / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = " ".join(closed[: closed.index("\n### ")].split())
    for vocabulary in (must_audit, closed):
        assert all(f"`{action}`" in vocabulary for action in _ACTIONS)
