"""Rule IR pydantic models (`docs/plan/24-internal-schemas.md` section 11.2, E35-T01).

Structural typing only: semantic validation (metric existence, units, action params) is E35-T04.
Every model is frozen and ``extra="forbid"``: ``additionalProperties: false`` is a security
control (nothing may be smuggled into a stored IR). The IR is data, never code (ADR-0007 R1).
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    StrictStr,
    Tag,
    model_validator,
)
from pydantic_core import PydanticCustomError

from candleviewer.domain.primitives import AccountId, Environment, Notional, RuleId, Symbol, UserId

METRIC_PATTERN = r"^[a-z][a-z0-9_]{1,48}$"
MAX_BOOLEAN_CHILDREN = 32
MAX_ARITHMETIC_OPERANDS = 8
MAX_ACTIONS = 10
MIN_WINDOW_MS = 100
MAX_WINDOW_MS = 86_400_000

_CFG = ConfigDict(frozen=True, extra="forbid")

ComparisonOp = Literal[
    "gt", "gte", "lt", "lte", "eq", "neq", "between", "outside", "crosses_above",
    "crosses_below", "changed", "is_true", "is_false", "in_set", "not_in_set",
]  # fmt: skip
ArithmeticOp = Literal["add", "sub", "mul", "div", "abs", "min", "max", "neg", "pct_of"]
BooleanOp = Literal["all_of", "any_of", "none_of", "n_of"]
TemporalOp = Literal["sustained_for", "occurred_within", "count_within", "stable_for"]
TriggerType = Literal[
    "on_price_update", "on_bar_close", "on_order_fill", "on_position_open", "on_position_close",
    "on_position_update", "on_timer", "on_metric_change", "on_signal", "on_schedule",
    "pre_trade_check", "on_book_update", "on_liquidation",
]  # fmt: skip
ActionType = Literal[
    "place_order", "modify_stop_loss", "modify_take_profit", "cancel_order", "cancel_all_orders",
    "move_to_breakeven", "scale_out", "scale_in", "flatten_position", "flatten_all_positions",
    "reverse_position", "halt_new_orders", "resume_new_orders", "reduce_leverage", "widen_stop",
    "tighten_stop", "arm_chase_limit", "start_iceberg_slice", "start_twap", "send_notification",
    "log_journal_tag", "set_variable", "emit_signal", "pause_rule", "enable_rule",
]  # fmt: skip

_BOOLEAN_OPS = frozenset({"all_of", "any_of", "none_of", "n_of"})
_TEMPORAL_OPS = frozenset({"sustained_for", "occurred_within", "count_within", "stable_for"})


def _plain_decimal(d: Decimal) -> str:
    """The JSON form of a ``Decimal`` param: ``canonical.dec_str``'s digits, so a stored or returned
    value re-hashes as it hashed (``1E-7`` is ``"0.0000001"``, ``3.0`` is ``"3"``). Mirrored, not
    imported: ``canonical`` imports these models."""
    return "0" if d == 0 else format(d.normalize(), "f")


def _one_refusal(v: Any) -> Any:
    """One clear error for a value no member holds, in place of one per member."""
    if (isinstance(v, float) and not math.isfinite(v)) or (
        isinstance(v, Decimal) and not v.is_finite()
    ):
        raise PydanticCustomError("finite_number", "Input should be a finite number")
    if v is not None and not isinstance(v, (bool, int, float, Decimal, str)):
        raise PydanticCustomError(
            "plain_value", "Input should be a plain value (true/false, a number, text or null)"
        )
    return v


#: A metric parameter value, typed like ``Literal_``: a JSON number arrives as a ``Decimal``, which
#: the hash canonicalises (``0.5`` and ``0.50`` alike). Strict members, so a JSON ``1.0`` stays a
#: number (``Literal_``'s lax union reads it as ``True``). ``None`` stays valid, as it was before
#: (a stored rule holding one keeps loading); NaN, a list or an object is one clear 422.
ParamValue = Annotated[
    StrictBool
    | StrictInt
    | Annotated[Decimal, PlainSerializer(_plain_decimal, return_type=str, when_used="json")]
    | StrictStr
    | None,
    BeforeValidator(_one_refusal),
]


class MetricRef(BaseModel):
    model_config = _CFG
    metric: Annotated[str, Field(pattern=METRIC_PATTERN)]
    params: dict[str, ParamValue] = Field(default_factory=dict)
    symbol: Symbol | None = None
    account_id: AccountId | None = None
    timeframe: str | None = None


class Literal_(BaseModel):
    """Constant operand; ``{"const": ...}`` in JSON."""

    model_config = _CFG
    const: bool | int | Decimal | str


class ArithmeticNode(BaseModel):
    model_config = _CFG
    node_id: str
    op: ArithmeticOp
    operands: Annotated[
        tuple[Operand, ...], Field(min_length=1, max_length=MAX_ARITHMETIC_OPERANDS)
    ]


def _operand_tag(v: Any) -> str | None:
    if isinstance(v, dict):
        if "metric" in v:
            return "metric"
        if "const" in v:
            return "const"
        return "arith" if "operands" in v else None
    if isinstance(v, MetricRef):
        return "metric"
    if isinstance(v, Literal_):
        return "const"
    return "arith" if isinstance(v, ArithmeticNode) else None


Operand = Annotated[
    Annotated[MetricRef, Tag("metric")]
    | Annotated[Literal_, Tag("const")]
    | Annotated[ArithmeticNode, Tag("arith")],
    Discriminator(
        _operand_tag,
        custom_error_type="invalid_operand",
        custom_error_message="operand must be a metric ref, a {const} literal or arithmetic",
    ),
]


class Comparison(BaseModel):
    model_config = _CFG
    node_id: str
    op: ComparisonOp
    left: Operand
    right: Operand | None = None
    right2: Operand | None = None
    set_values: tuple[str, ...] = ()
    tolerance: Decimal | None = None


class BooleanNode(BaseModel):
    model_config = _CFG
    node_id: str
    op: BooleanOp
    children: Annotated[
        tuple[ConditionNode, ...], Field(min_length=1, max_length=MAX_BOOLEAN_CHILDREN)
    ]
    n: Annotated[int, Field(ge=1)] | None = None


class TemporalNode(BaseModel):
    model_config = _CFG
    node_id: str
    op: TemporalOp
    child: ConditionNode
    window_ms: Annotated[int, Field(ge=MIN_WINDOW_MS, le=MAX_WINDOW_MS)]
    min_count: Annotated[int, Field(ge=1)] = 1


def _condition_tag(v: Any) -> str | None:
    if isinstance(v, dict):
        op = v.get("op")
        if op in _BOOLEAN_OPS:
            return "boolean"
        if op in _TEMPORAL_OPS:
            return "temporal"
        return "comparison" if op is not None else None
    if isinstance(v, Comparison):
        return "comparison"
    if isinstance(v, BooleanNode):
        return "boolean"
    return "temporal" if isinstance(v, TemporalNode) else None


ConditionNode = Annotated[
    Annotated[Comparison, Tag("comparison")]
    | Annotated[BooleanNode, Tag("boolean")]
    | Annotated[TemporalNode, Tag("temporal")],
    Discriminator(
        _condition_tag,
        custom_error_type="invalid_condition",
        custom_error_message="condition must be a comparison, boolean or temporal node",
    ),
]


class Action(BaseModel):
    model_config = _CFG
    node_id: str
    type: ActionType
    params: dict[str, Any]
    on_error: Literal["abort_remaining", "continue", "retry_once"] = "abort_remaining"
    targets: Literal["scope_accounts", "originating_account", "all_accounts"] = "scope_accounts"
    dry_run_only: bool = False


class RuleScope(BaseModel):
    model_config = _CFG
    level: Literal["global", "account", "symbol", "position", "trade_group"]
    account_ids: tuple[AccountId, ...] = ()
    symbols: tuple[Symbol, ...] = ()
    applies_to: Literal["open_positions", "pending_orders", "account", "any"] = "any"
    # SAFE DEFAULT (24-internal-schemas.md 11.5 E12): demo only. Never widen.
    environments: tuple[Environment, ...] = ("demo",)
    exclude_algo_children: bool = True


_TRIGGER_REQUIRED = {
    "on_timer": "interval_ms",
    "on_bar_close": "timeframe",
    "on_schedule": "cron",
    "on_metric_change": "metric",
}


class Trigger(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {"if": {"properties": {"type": {"const": t}}}, "then": {"required": [f]}}
                for t, f in _TRIGGER_REQUIRED.items()
            ]
        },
    )
    type: TriggerType
    timeframe: str | None = None
    interval_ms: Annotated[int, Field(ge=100)] | None = None
    cron: str | None = None
    metric: str | None = None
    debounce_ms: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def _required_field(self) -> Trigger:
        field = _TRIGGER_REQUIRED.get(self.type)
        if field is not None and getattr(self, field) is None:
            raise ValueError(f"trigger {self.type} requires {field}")
        return self


class RuleLimits(BaseModel):
    model_config = _CFG
    once: bool = False
    once_per: Literal["position", "day", "group", "rule_lifetime"] | None = None
    cooldown_ms: Annotated[int, Field(ge=0)] = 1000
    max_fires_per_hour: Annotated[int, Field(ge=1)] = 60
    max_fires_per_day: Annotated[int, Field(ge=1)] = 500
    max_actions_per_fire: Annotated[int, Field(ge=1, le=MAX_ACTIONS)] = 10
    max_notional_per_fire: Notional | None = None
    max_daily_notional: Notional | None = None
    require_confirmation: bool = False
    evaluation_timeout_ms: Annotated[int, Field(ge=10, le=5000)] = 250
    kill_switch_on_error_count: Annotated[int, Field(ge=1)] = 5


class Rule(BaseModel):
    model_config = _CFG
    rule_id: RuleId
    version: Annotated[int, Field(ge=1)]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=2000)] = ""
    enabled: bool
    mode: Literal["disabled", "simulate", "armed"]
    scope: RuleScope
    trigger: Trigger
    conditions: ConditionNode
    actions: Annotated[tuple[Action, ...], Field(min_length=1, max_length=MAX_ACTIONS)]
    limits: RuleLimits = Field(default_factory=RuleLimits)
    editor: Literal["form", "graph"] = "form"
    graph_layout: dict[str, Any] | None = None
    # Persistence metadata (E35-T02 owns the columns); optional here and not part of ir_hash.
    created_by: UserId | None = None
    created_at: int | None = None
    updated_at: int | None = None
    ir_version: Literal[1] = 1


for _m in (ArithmeticNode, Comparison, BooleanNode, TemporalNode, Rule):
    _m.model_rebuild()
