"""The stuck-order detector's audit action is registered before any code emits it (E29-T08 #916;
SR-E29-17, the E29 threat model; 24-internal-schemas.md Sec.15.5, Sec.8.13).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS`, so the action is pinned here by name,
independently of the registry, to the one the detector's sinks write (`incidents.AUDIT_ACTION`),
and 24's closed vocabulary is held to it, with the paragraph that says what the record holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action
from candleviewer.oms.incidents import AUDIT_ACTION

ROOT = Path(__file__).resolve().parents[5]
_ACTION = "oms.incident"


def test_the_incident_action_is_registered_by_exact_name_and_is_the_detectors() -> None:
    assert AUDIT_ACTION == _ACTION
    assert _ACTION in AUDIT_ACTIONS
    assert validate_action(_ACTION) == _ACTION


@pytest.mark.parametrize("name", ["oms.incidents", "oms.stuck_order", "oms.incident_raised"])
def test_an_incident_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """One action for every kind: the kind is the record's reason, never an action of its own."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_24_lists_it_in_its_closed_set_and_says_what_its_record_holds() -> None:
    internal = (ROOT / "docs" / "plan" / "24-internal-schemas.md").read_text(encoding="utf-8")
    vocabulary = internal[internal.index("### 15.5 Audited action vocabulary") :]
    vocabulary = " ".join(vocabulary[: vocabulary.index("\n### ")].split())
    assert f"`oms.no_intent_detected`, `{_ACTION}`, `system.startup`" in vocabulary
    for held in (
        "registered before its first emitter (SR-E29-17)",
        "written ahead of every other sink",
        "the order its object (`object_kind` `order`) for the kinds `in_flight`, `unknown` and "
        "`pending`, the exchange account (`exchange_account`) for `naked` and `account_stale`",
        "ids and fixed text only, never a price, a size or a payload",
        "that incident reaches neither `system_events` nor the bus",
    ):
        assert held in vocabulary, held
