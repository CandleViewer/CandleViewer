"""E42-T05: the audit actions the ops surfaces emit are registered, so `audit.emit` accepts them
instead of failing the operation with an unregistered action."""

from __future__ import annotations

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action


@pytest.mark.parametrize(
    "action",
    [
        "incident.acknowledged",
        "backup.run",
        "backup.verified",
        "backup.restore",
        "backup.downloaded",
    ],
)
def test_ops_actions_are_registered(action: str) -> None:
    assert action in AUDIT_ACTIONS
    assert validate_action(action) == action


def test_the_ticket_wording_backup_restored_is_not_a_second_restore_action() -> None:
    with pytest.raises(UnknownAuditAction):
        validate_action("backup.restored")
