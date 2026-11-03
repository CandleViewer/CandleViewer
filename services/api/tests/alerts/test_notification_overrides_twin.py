"""E40-S02 (#1130, BQ-5): the Python twin of the critical-override constant is the JSON source,
field for field, and holds the invariants the settings refusal and the evaluator rely on."""

from __future__ import annotations

import json
from pathlib import Path

import candleviewer
from candleviewer.alerts._generated import notification_overrides as twin

_SOURCE = (
    Path(candleviewer.__file__).resolve().parents[3]
    / "packages/protocol/notification-overrides.json"
)


def test_the_twin_is_the_json_source() -> None:
    doc = json.loads(_SOURCE.read_text(encoding="utf-8"))
    assert twin.VERSION == doc["version"] and twin.STATUS == doc["status"]
    assert twin.USER_ALERTS_OVERRIDE is doc["user_alerts_override"]
    assert twin.CATEGORIES == tuple(doc["categories"])
    assert twin.CHANNELS == tuple(doc["channels"])
    assert twin.LOCKED_CELLS == {(c["category"], c["channel"]) for c in doc["locked_cells"]}
    assert [o._asdict() for o in twin.OVERRIDES] == doc["overrides"]
    assert twin.OVERRIDE_CHANNELS == tuple(doc["override_channels"])
    assert twin.OVERRIDE_TONE == doc["override_tone"]


def test_user_alerts_never_override_and_every_override_is_listed_once() -> None:
    assert twin.USER_ALERTS_OVERRIDE is False
    ids = [o.id for o in twin.OVERRIDES]
    assert ids == [f"CO-{n}" for n in range(1, 13)]
    assert {o.category for o in twin.OVERRIDES} <= set(twin.CATEGORIES) - {"alerts"}
