"""E28-T05 (#909, slice S4b; C-6.2): `trade_groups` frames rendered from the E28 seed's two fired
groups (`tests/fixtures/e28/seed.sql`), by the wired topic on a real hub, validate against
`cv://ws/v1/trade_groups.schema.json` and carry no `client_group_ref`, `created_by` or `note`, key
or value: the `v: 1` schema still declares `client_group_ref` (S0's R1S-01)."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.accounts.trade_groups import record_from_rows
from candleviewer.storage.repositories.trade_groups import TradeGroupRecord
from tests.contract.ws._harness import validate_frame
from tests.unit.accounts.test_e28_fixture_set import _seed
from tests.unit.accounts.test_trade_group_repository import _GROUP_ROW, _LEG_ROW, _MARK
from tests.unit.ws.test_trade_groups_scope import _conn, _entry, _wired

_E28_A, _E28_C = (
    UUID("e28f0000-0000-4000-8000-0000000000d1"),
    UUID("e28f0000-0000-4000-8000-0000000000d3"),
)
_PRIVATE = frozenset({"client_group_ref", "created_by", "note"})


def _value(name: str, raw: Any) -> Any:
    """A seed column as the store reads it: ids, times and decimals typed, the rest as written."""
    if not isinstance(raw, str):
        return raw
    if name == "id" or name.endswith("_id") or name == "created_by":
        return UUID(raw)
    if name.endswith("_at"):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return Decimal(raw) if name.endswith(("_qty", "_price", "_usd", "_leverage")) else raw


def _rows(seeded: dict[str, Any], base: Any) -> Any:
    """`base` (a whole stored row, its note a planted `_MARK`) with the seed's columns."""
    names = {f.name for f in fields(base)}
    return replace(base, **{k: _value(k, v) for k, v in seeded.items() if k in names})


def _seeded() -> list[TradeGroupRecord]:
    """The two seeded groups as stored: cancelled before any fill."""
    legs = [_rows(leg, _LEG_ROW) for leg in _seed("trade_group_legs")]
    return [
        TradeGroupRecord(group=row, legs=tuple(leg for leg in legs if leg.trade_group_id == row.id))
        for row in (_rows(group, _GROUP_ROW) for group in _seed("trade_groups"))
    ]


def test_frames_rendered_from_the_e28_seed_validate_and_carry_no_private_field() -> None:
    """The snapshot holds both groups as fired (open, each leg submitted); then each leg and each
    group moves to what the seed stores: four leg deltas and two terminal ones, all valid."""
    stored = _seeded()
    fired = [
        replace(
            record,
            group=replace(record.group, status="open", closed_at=None),
            legs=tuple(replace(leg, status="submitted", closed_at=None) for leg in record.legs),
        )
        for record in stored
    ]
    hub, topic, _, router = _wired(*(record_from_rows(record) for record in fired))
    conn = _conn(hub, router, _E28_A, _E28_C)
    conn.sub(_entry(_E28_A, _E28_C))
    for record in map(record_from_rows, stored):
        for leg in record.legs:
            topic.leg_changed(leg)
        topic.group_changed(record.group)
    frames = conn.take()
    assert [(f["t"], len(f["p"]["trade_groups"])) for f in frames] == [("snap", 2)] + [("d", 1)] * 6
    for frame in frames:
        validate_frame(frame)
    items = [item for frame in frames for item in frame["p"]["trade_groups"]]
    assert [item["status"] for item in items[2:]] == ["open", "open", "cancelled"] * 2
    assert not any(_PRIVATE & set(item) for item in items)
    text = json.dumps(frames)
    private = {r.group.client_group_ref for r in stored} | {str(r.group.created_by) for r in stored}
    assert _MARK not in text and not any(value in text for value in private)
