"""The closed-PnL divergence action is registered before its first emitter (E29-S06 #981; 24
Sec.15.5: "E29-S06 registers it in `audit/actions.py`, with a test, before its first emitter").

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS`, so the action is pinned here by name,
independently of the registry, and the closed set of 24 Sec.15.5 is held to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action

ROOT = Path(__file__).resolve().parents[5]
_ACTION = "pnl.divergence_detected"


def test_the_divergence_action_is_the_one_registered_pnl_action() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("pnl.")} == {_ACTION}
    assert validate_action(_ACTION) == _ACTION


@pytest.mark.parametrize(
    "name", ["pnl.divergence", "pnl.divergence_cleared", "pnl.venue_missing", "oms.pnl_divergence"]
)
def test_a_closed_pnl_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """A cleared flag writes no record, and a missing venue figure is the same action with its
    own reason (24 Sec.8.13), never an action of its own."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_24_lists_it_in_its_closed_set_without_the_pending_note() -> None:
    internal = (ROOT / "docs" / "plan" / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = " ".join(closed[: closed.index("\n### ")].split())
    assert f"`{_ACTION}`," in closed
    assert f"`{_ACTION}` (not registered yet" not in closed
