"""The `instruments.refresh.*` audit actions are registered before the route emits them (E08-T10,
#5111, Q3).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, so the route answers
`503 audit_unavailable`), so both actions are pinned here by name, independently of the registry,
and the closed set in 24 section 15.5 is held to them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action

ROOT = Path(__file__).resolve().parents[5]
_ACTIONS = frozenset({"instruments.refresh.requested", "instruments.refresh.completed"})


def test_instruments_refresh_actions_are_registered_by_exact_name() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("instruments.")} == _ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS


@pytest.mark.parametrize(
    "name", ["instruments.refresh", "instruments.refresh.cancelled", "instrument.refresh.requested"]
)
def test_instruments_refresh_unlisted_action_is_refused(name: str) -> None:
    """A cancelled job runs no `on_done`, so it has no record of its own (24 section 15.5)."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_instruments_refresh_actions_are_in_the_closed_set_of_24() -> None:
    internal = (ROOT / "docs" / "plan" / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = " ".join(closed[: closed.index("\n### ")].split())
    assert all(f"`{action}`" in closed for action in _ACTIONS)
    assert (
        "(not registered yet" not in closed.split("`instruments.refresh.requested` and", 1)[1][:400]
    )
