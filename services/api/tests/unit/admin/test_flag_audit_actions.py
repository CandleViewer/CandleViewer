"""E42-T03: the audit actions the flag service emits are registered, so `audit.emit` accepts them
instead of failing the write with an unregistered action."""

from __future__ import annotations

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action


@pytest.mark.parametrize("action", ["flags.change", "maintenance.enabled", "maintenance.disabled"])
def test_flag_service_actions_are_registered(action: str) -> None:
    assert action in AUDIT_ACTIONS
    assert validate_action(action) == action


def test_an_unregistered_maintenance_action_is_still_refused() -> None:
    with pytest.raises(UnknownAuditAction):
        validate_action("maintenance.toggled")
