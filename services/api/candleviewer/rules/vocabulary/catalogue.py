"""Action / trigger / operator catalogues (24-internal-schemas.md 11.2, 11.6).

Every `ActionType` / `TriggerType` / `ComparisonOp` literal in the IR must be
described here; the completeness tests enforce it. Permissions are advisory
for the UI - the authoritative check happens at execution time (E35-S03/S04).
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SIDE = {"type": "string", "enum": ["buy", "sell"]}
_ORDER_TYPE = {"type": "string", "enum": ["market", "limit"]}
_QTY = {"type": "number", "exclusiveMinimum": 0}
_PCT = {"type": "number", "exclusiveMinimum": 0, "maximum": 100}
_STOP_MODE = {
    "type": "string",
    "enum": ["absolute", "offset_from_entry", "offset_from_price", "atr", "structure"],
}


def _obj(required: list[str], props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": props,
        "additionalProperties": True,
    }


@dataclass(frozen=True, slots=True)
class ActionSpec:
    type: str
    title: str
    params_schema: dict[str, Any]
    permissions: tuple[str, ...] = ()
    places_orders: bool = False
    idempotent: bool = False
    guarded: bool = False
    note: str = ""
    loosens_risk: bool = False


_STOP_PARAMS = _obj(
    ["mode", "value"],
    {
        "mode": _STOP_MODE,
        "value": {"type": "number"},
        "only_tighten": {"type": "boolean", "default": True},
    },
)
_OW = ("orders:write",)
#: Declared permission for arming a rule live, surfaced on the catalogue: the seeded RBAC code
#: (migration 0015). `rules` may not import `auth` (M15); tests pin it to `Permission` (#2624).
ARM_LIVE_PERMISSION = "rules:arm_live"
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec("place_order", "Place order", _obj(["side", "order_type", "qty_mode"], {"side": _SIDE, "order_type": _ORDER_TYPE, "qty_mode": {"type": "string"}, "qty": _QTY, "profile": {"type": "string"}, "price": {"type": "number"}, "stop_loss": {"type": "object"}, "take_profits": {"type": "array"}, "algo": {"type": "object"}}), _OW, True, False, True, "Full trade-group path including sizing and native SL."),
    ActionSpec("modify_stop_loss", "Modify stop loss", _STOP_PARAMS, _OW, False, True, True, "only_tighten=false needs rules.loosen_stop.", True),
    ActionSpec("modify_take_profit", "Modify take profit", _STOP_PARAMS, _OW, False, True, True),
    ActionSpec("move_to_breakeven", "Move stop to breakeven", _obj([], {"offset_ticks": {"type": "integer", "default": 2}}), _OW, False, True, True, "Never loosens."),
    ActionSpec("scale_out", "Scale out", _obj(["order_type"], {"qty_pct": _PCT, "qty": _QTY, "order_type": _ORDER_TYPE}), _OW, False, False, True, "Reduce-only."),
    ActionSpec("scale_in", "Scale in", _obj([], {"qty_pct": _PCT, "qty": _QTY}), _OW, True, False, True, "Subject to profile caps."),
    ActionSpec("flatten_position", "Flatten position", _obj([], {"symbols": {"type": "array", "items": {"type": "string"}}}), _OW, False, True, True, "Reduce-only market."),
    ActionSpec("flatten_all_positions", "Flatten all positions", _obj([], {"symbols": {"type": "array", "items": {"type": "string"}}}), _OW, False, True, True, "Reduce-only market."),
    ActionSpec("reverse_position", "Reverse position", _obj([], {}), _OW, True, False, True, "Flatten then open the opposite side, with native SL."),
    ActionSpec("cancel_order", "Cancel order", _obj([], {"purpose": {"type": "string"}}), _OW, False, True, False),
    ActionSpec("cancel_all_orders", "Cancel all orders", _obj([], {"purpose": {"type": "string"}}), _OW, False, True, False),
    ActionSpec("halt_new_orders", "Halt new orders", _obj(["scope", "until"], {"scope": {"type": "string"}, "until": {"type": "string", "enum": ["next_utc_day", "duration_ms", "manual"]}}), (), False, True, False, "Circuit breaker."),
    ActionSpec("resume_new_orders", "Resume new orders", _obj([], {"scope": {"type": "string"}}), (ARM_LIVE_PERMISSION,), False, True, True),
    ActionSpec("reduce_leverage", "Reduce leverage", _obj([], {"target": {"type": "number"}, "by": {"type": "number"}}), _OW, False, True, True),
    ActionSpec("widen_stop", "Widen stop", _STOP_PARAMS, (*_OW, "rules.loosen_stop"), False, False, True, "Loosens risk; owner-only permission.", True),
    ActionSpec("tighten_stop", "Tighten stop", _STOP_PARAMS, _OW, False, True, True, "Never loosens."),
    ActionSpec("arm_chase_limit", "Arm chase limit", _obj([], {"params": {"type": "object"}}), _OW, True, False, True),
    ActionSpec("start_iceberg_slice", "Start iceberg slice", _obj([], {"params": {"type": "object"}}), _OW, True, False, True),
    ActionSpec("start_twap", "Start TWAP", _obj([], {"params": {"type": "object"}}), _OW, True, False, True),
    ActionSpec("send_notification", "Send notification", _obj(["channel", "severity", "template"], {"channel": {"type": "string"}, "severity": {"type": "string"}, "template": {"type": "string"}, "vars": {"type": "object"}}), (), False, False, False),
    ActionSpec("log_journal_tag", "Log journal tag", _obj(["tag"], {"tag": {"type": "string"}, "note": {"type": "string"}}), (), False, True, False, "Closes the rule/outcome loop."),
    ActionSpec("set_variable", "Set variable", _obj(["name", "value"], {"name": {"type": "string"}, "value": {}, "ttl_ms": {"type": "integer"}}), (), False, True, False, "Rule-scoped variable store."),
    ActionSpec("emit_signal", "Emit signal", _obj(["signal_name"], {"signal_name": {"type": "string"}, "payload": {"type": "object"}}), (), False, False, False, "Chains rules."),
    ActionSpec("pause_rule", "Pause rule", _obj(["rule_id"], {"rule_id": {"type": "string"}}), (), False, True, False, "A rule may pause itself."),
    ActionSpec("enable_rule", "Enable rule", _obj(["rule_id"], {"rule_id": {"type": "string"}}), (), False, True, False, "Cannot target itself."),
)  # fmt: skip

TARGET_SEMANTICS = {
    "scope_accounts": "every account in the rule scope",
    "originating_account": "the account whose event fired the rule",
    "all_accounts": "every account the author can trade",
}

TRIGGERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "on_price_update": ("Per trade; debounce recommended", ()),
    "on_bar_close": ("When a bar closes", ("timeframe",)),
    "on_order_fill": ("When an order fills", ()),
    "on_position_open": ("When a position opens", ()),
    "on_position_close": ("When a position closes", ()),
    "on_position_update": ("When a position changes", ()),
    "on_timer": ("Fixed interval", ("interval_ms",)),
    "on_metric_change": ("When a named metric changes", ("metric",)),
    "on_signal": ("When another rule emits a signal", ()),
    "on_schedule": ("UTC cron schedule", ("cron",)),
    "pre_trade_check": ("Synchronous veto before any order submission", ()),
    "on_book_update": ("Throttled to 10 Hz", ()),
    "on_liquidation": ("When a liquidation prints", ()),
}  # fmt: skip

# Operator id -> (arity, applicable unit classes). "numeric" = every number unit.
NUMERIC = ("price", "qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore")
OPERATORS: dict[str, tuple[int, tuple[str, ...]]] = {
    **{op: (2, NUMERIC) for op in ("gt", "gte", "lt", "lte", "crosses_above", "crosses_below")},
    "eq": (2, (*NUMERIC, "enum", "bool")),
    "neq": (2, (*NUMERIC, "enum", "bool")),
    "between": (3, NUMERIC),
    "outside": (3, NUMERIC),
    "changed": (1, (*NUMERIC, "enum", "bool")),
    "is_true": (1, ("bool",)),
    "is_false": (1, ("bool",)),
    "in_set": (2, ("enum",)),
    "not_in_set": (2, ("enum",)),
}  # fmt: skip
