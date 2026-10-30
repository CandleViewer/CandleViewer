"""The reconciliation audit actions are registered before any code emits them (E29-T06 #914 PR 1;
SR-E29-17, the E29 threat model).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, so the write is refused), so
the two actions are pinned here by name, independently of the registry, and the closed vocabulary
of 24 Sec.15.5 is held to them, with the paragraph that says what each record holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action

ROOT = Path(__file__).resolve().parents[5]
_ACTIONS = frozenset({"oms.reconcile", "order.adopted_untracked"})


def test_the_two_reconciliation_actions_are_registered_by_exact_name() -> None:
    assert _ACTIONS <= AUDIT_ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS
    assert {a for a in AUDIT_ACTIONS if a.startswith("oms.reconcile")} == {
        "oms.reconcile",
        "oms.reconcile_anomaly",
    }


@pytest.mark.parametrize(
    "name", ["oms.reconciled", "oms.reconcile_requested", "order.adopted", "oms.untracked_adopted"]
)
def test_a_reconciliation_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """A manual request and an operator's decision are `oms.reconcile` with their `stage`, never
    actions of their own; no human adoption exists in v1 (D6, BQ-17), so neither does its
    action."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_24_lists_both_in_its_closed_set_and_says_what_each_record_holds() -> None:
    internal = (ROOT / "docs" / "plan" / "24-internal-schemas.md").read_text(encoding="utf-8")
    vocabulary = internal[internal.index("### 15.5 Audited action vocabulary") :]
    vocabulary = " ".join(vocabulary[: vocabulary.index("\n### ")].split())
    assert all(f"`{action}`" in vocabulary for action in _ACTIONS)
    for stage in ("`finished`", "`requested`", "`resolved`"):
        assert stage in vocabulary
    assert "No human adopt action exists" in vocabulary
