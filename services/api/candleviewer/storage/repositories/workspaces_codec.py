"""Pure mapping helpers for the workspaces repository (E15-T01): rows, payloads, no-op compare.

No SQL and no I/O. `workspaces_sqlalchemy.py` runs the statements; this module turns rows into the
driver-free dataclasses, builds bound parameters/payloads, compares writes type-strictly and maps
unique violations to typed conflicts.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    LayoutRow,
    PaneFields,
    WorkspaceConflictError,
    WorkspaceFields,
    WorkspaceRow,
)

UNIQUE_RULES: dict[str, tuple[str, str | None]] = {
    "ux_ws_name": ("name_taken", "name"),
    "ux_lay_name": ("name_taken", "name"),
    "ux_lay_slot": ("hotkey_slot_taken", "hotkey_slot"),
    "ux_ws_default": ("concurrent_update", None),
    "ux_lay_default": ("concurrent_update", None),
}


def decode_obj(value: Any) -> dict[str, Any]:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 (D25). Local on purpose: `storage` may not import `ingestion` (M10)."""
    value = (int(time.time() * 1000) & 0xFFFFFFFFFFFF) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    return uuid.UUID(int=(value & ~(0x3 << 62)) | (0x2 << 62))


def same_fields(a: WorkspaceFields | LayoutFields, b: WorkspaceFields | LayoutFields) -> bool:
    """Type-strict equality: Python `1 == True == 1.0`, canonical JSON keeps them apart."""
    return canonical(dataclasses.asdict(a)) == canonical(dataclasses.asdict(b))


def ws_row(m: Any) -> WorkspaceRow:  # private: SQLAlchemy RowMapping is Mapping[Any, Any]
    return WorkspaceRow(**dict(m))


def pane_row(m: Any) -> PaneFields:
    return PaneFields(
        slot_index=m["slot_index"],
        pane_kind=m["pane_kind"],
        symbol=m["symbol"],
        interval_code=m["interval_code"],
        chart_template_id=m["chart_template_id"],
        indicator_preset_ids=tuple(str(i) for i in m["indicator_preset_ids"]),
        pane_config=decode_obj(m["pane_config"]),
        scale_mode=m["scale_mode"],
    )


def lay_row(m: Any, panes: tuple[PaneFields, ...]) -> LayoutRow:
    d = dict(m)
    spec = decode_obj(d.pop("grid_spec"))
    return LayoutRow(grid_spec=spec or None, panes=panes, **d)


def lay_params(fields: LayoutFields) -> dict[str, Any]:
    return {
        "name": fields.name,
        "grid_preset": fields.grid_preset,
        "grid_spec": canonical(fields.grid_spec or {}),
        "crosshair_sync": fields.crosshair_sync,
        "level_sync": fields.level_sync,
        "symbol_sync": fields.symbol_sync,
        "hotkey_slot": fields.hotkey_slot,
        "is_default": fields.is_default,
    }


def pane_payload(panes: tuple[PaneFields, ...]) -> str:
    """One JSON document for the multi-row INSERT; pane rows get fresh ids (D25)."""
    return canonical(
        [
            {
                "id": str(uuid7()),
                "slot_index": p.slot_index,
                "pane_kind": p.pane_kind,
                "symbol": p.symbol,
                "interval_code": p.interval_code,
                "chart_template_id": p.chart_template_id,
                "indicator_preset_ids": list(p.indicator_preset_ids),
                "pane_config": p.pane_config,
                "scale_mode": p.scale_mode,
            }
            for p in panes
        ]
    )


def map_integrity(exc: IntegrityError) -> WorkspaceConflictError | None:
    """unique_violation (SQLSTATE 23505) on a known index -> typed conflict; else None."""
    orig: Any = exc.orig
    if getattr(orig, "sqlstate", None) != "23505":
        return None
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            rule = UNIQUE_RULES.get(str(name))
            return None if rule is None else WorkspaceConflictError(*rule)
    return None


def ws_params(fields: WorkspaceFields) -> dict[str, Any]:
    return {
        "name": fields.name,
        "is_default": fields.is_default,
        "icon_token": fields.icon_token,
        "sort_order": fields.sort_order,
    }
