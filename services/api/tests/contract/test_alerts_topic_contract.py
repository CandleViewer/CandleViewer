"""Contract (E40-T04 PR-B): the `alerts` topic's payloads are §15.7 `AlertUpdate` exactly.

Every frame the rig receives is validated against the §13-§15 schemas already
(`tests/unit/ws/_seq_support.validate`); this module pins the schema diff: the item a delivery
becomes carries exactly the properties `cv://ws/v1/alerts.schema.json` declares (so a field added
on either side fails here), a snapshot and a delta validate against the published bundle in
`packages/protocol`, and no SECRET column of `alerts` (migration 0014) can reach the wire.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import candleviewer
from candleviewer.alerts.ws_topic import delivery_item
from tests.alerts._alerts_ws import USER_A, FakeReader

_ROOT = Path(candleviewer.__file__).resolve().parents[3]
_BUNDLE = json.loads((_ROOT / "packages/protocol/ws-schemas.json").read_text(encoding="utf-8"))
_SCHEMAS: dict[str, Any] = (
    {s["$id"]: s for s in _BUNDLE["schemas"]}
    if isinstance(_BUNDLE["schemas"], list)
    else dict(_BUNDLE["schemas"])
)
_ALERTS = _SCHEMAS["cv://ws/v1/alerts.schema.json"]
_REGISTRY = Registry().with_resources(
    (sid, Resource.from_contents(doc)) for sid, doc in _SCHEMAS.items()
)


def _validate(payload: dict[str, Any]) -> None:
    errors = list(Draft202012Validator(_ALERTS, registry=_REGISTRY).iter_errors(payload))
    assert not errors, [e.message for e in errors]


def test_an_item_carries_exactly_the_schemas_properties() -> None:
    reader = FakeReader()
    item = delivery_item(reader.add(USER_A))
    declared = _ALERTS["properties"]["deliveries"]["items"]["properties"]
    assert set(item) == set(declared)
    assert set(_ALERTS["properties"]) == {"deliveries", "unacked_count"}


def test_snapshot_and_delta_payloads_validate() -> None:
    reader = FakeReader()
    rows = [
        reader.add(USER_A),
        reader.add(USER_A, status="acked", acked_at=reader.rows[101].queued_at),
        reader.add(USER_A, channel="email", status="failed", error_message="relay timeout"),
        reader.add(USER_A, context={"storm_summary": True}, severity=None, body=""),
    ]
    _validate({"deliveries": [delivery_item(r) for r in rows], "unacked_count": 1})
    _validate({"deliveries": []})


def test_no_secret_column_of_alerts_can_reach_an_item() -> None:
    migration = Path(candleviewer.__file__).parent / "migrations/versions/0014_alerts.py"
    secret = set(re.findall(r"(webhook_\w+_enc)", migration.read_text(encoding="utf-8")))
    assert secret, "0014 names its SECRET columns"
    reader = FakeReader()
    row = reader.add(USER_A, context={name: "x" for name in secret} | {"symbol": "BTCUSDT"})
    text = json.dumps(delivery_item(row))
    assert not any(name in text for name in secret) and '"context"' not in text
