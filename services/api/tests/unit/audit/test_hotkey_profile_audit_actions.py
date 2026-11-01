"""The `hotkey_profile.*` audit actions are registered with the routes that emit them (E10-T05,
#5211; 24 Sec.15.5, BQ-7).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, so the write is refused), so
the four actions are pinned here by name, independently of the registry; the routes emit each as a
literal, which the registered-action scan reads; and the two docs that list the vocabulary (24
section 15.5, the closed set, now without "not registered yet"; 21 section 3.10.1) are held to them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action
from tests.unit.audit.test_router_actions_registered import _emitted

ROOT = Path(__file__).resolve().parents[5]
_ACTIONS = frozenset(
    {
        "hotkey_profile.created",
        "hotkey_profile.updated",
        "hotkey_profile.deleted",
        "hotkey_profile.activated",
    }
)


def test_the_four_hotkey_profile_actions_are_registered_by_exact_name() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("hotkey_profile")} == _ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS


def test_the_routes_emit_each_action_as_a_literal_the_scan_reads() -> None:
    """#2144's scan reads the literal first argument of an emit call; the four, and the probe's
    `rbac.denied`, are each one."""
    assert _emitted("api/hotkey_profiles.py") == _ACTIONS | {"rbac.denied"}


@pytest.mark.parametrize(
    "name", ["hotkey_profile.renamed", "hotkey_profile.deactivated", "hotkey_profiles.created"]
)
def test_a_hotkey_profile_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """A rename is a replace (`.updated`), and the profile an activation deactivates gets no
    record of its own: `.activated` names it as `previous_active_id`."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_the_docs_list_the_four_actions_as_registered() -> None:
    plan = ROOT / "docs" / "plan"
    schema = (plan / "21-database-schema.md").read_text(encoding="utf-8")
    must_audit = schema.split("Actions that MUST be audited", 1)[1].split("\n\n", 1)[0]
    internal = (plan / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = " ".join(closed[: closed.index("\n### ")].split())
    for vocabulary in (must_audit, closed):
        assert all(f"`{action}`" in vocabulary for action in _ACTIONS)
    for action in _ACTIONS:
        assert f"`{action}` (not registered yet" not in closed
