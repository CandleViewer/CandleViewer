"""Semantic validator for the rule IR (E35-T04) - a safety gate, not a convenience.

Pure and synchronous: ``validate_rule(rule, registry, permissions)`` -> ``RuleValidationResult``.
Errors block saving; warnings do not, but *safety-class* warnings block arming
(``PUT /rules/{id}/mode``). The IR is data: nothing here evaluates or parses expressions.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from candleviewer.rules.ir import (
    BooleanNode,
    Comparison,
    Literal_,
    MetricRef,
    Rule,
    TemporalNode,
)
from candleviewer.rules.issues import Issue
from candleviewer.rules.limits import above_cap, cap_message
from candleviewer.rules.vocabulary.catalogue import ACTIONS, OPERATORS
from candleviewer.rules.vocabulary.registry import MetricRegistry

LOOSEN_STOP_PERMISSION = "rules.loosen_stop"
_ACTION_SPECS = {a.type: a for a in ACTIONS}
_HIGH_FREQUENCY = frozenset({"on_price_update", "on_book_update", "on_position_update",
                             "on_metric_change"})  # fmt: skip
_ORDER_ACTIONS = frozenset({"place_order", "scale_in", "scale_out", "reverse_position",
                            "flatten_position", "flatten_all_positions", "arm_chase_limit",
                            "start_iceberg_slice", "start_twap"})  # fmt: skip
_ORDER_TRIGGERS = frozenset({"on_order_fill", "on_position_open", "on_position_close",
                             "on_position_update"})  # fmt: skip
_STOP_ACTIONS = frozenset({"modify_stop_loss", "widen_stop", "tighten_stop", "move_to_breakeven"})
_TF = re.compile(r"^(\d+)([smhdw])$")
_TF_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
_MAX_PRICE_RATE = 600  # evaluations/min ceiling for per-trade triggers (10 Hz throttle)
_UNKNOWN = "?"  # unit of an expression whose unit we cannot (or need not) infer


@dataclass(slots=True)
class RuleValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    referenced_variables: list[str] = field(default_factory=list)
    referenced_actions: list[str] = field(default_factory=list)
    estimated_evaluations_per_minute: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def blocks_arming(self) -> bool:
        """Any error, or any open safety-class warning, refuses ``mode=armed``."""
        return bool(self.errors) or any(w.klass == "safety" for w in self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "referenced_variables": self.referenced_variables,
            "referenced_actions": self.referenced_actions,
            "estimated_evaluations_per_minute": self.estimated_evaluations_per_minute,
            "blocks_arming": self.blocks_arming,
        }


def estimate_evaluations_per_minute(rule: Rule) -> int:
    t = rule.trigger
    if t.type in ("on_price_update", "on_book_update"):
        if t.debounce_ms > 0:
            return min(_MAX_PRICE_RATE, max(1, 60_000 // t.debounce_ms))
        return _MAX_PRICE_RATE
    if t.type == "on_bar_close" and t.timeframe:
        m = _TF.match(t.timeframe)
        return max(1, 60_000 // (int(m[1]) * _TF_MS[m[2]])) if m and int(m[1]) else 1
    if t.type == "on_timer" and t.interval_ms:
        return max(1, 60_000 // t.interval_ms)
    if t.type == "on_schedule":
        return 1
    return 60 if t.debounce_ms == 0 else min(60, max(1, 60_000 // t.debounce_ms))


def _const_unit(c: Literal_) -> str:
    v = c.const
    if isinstance(v, str):
        if v.endswith("%"):
            return "pct"
        try:
            Decimal(v)
        except ArithmeticError:
            return "enum"
        return _UNKNOWN  # a decimal serialised as a string: fits any numeric unit
    return "bool" if isinstance(v, bool) else _UNKNOWN  # bare numbers fit any numeric unit


class _Validator:
    def __init__(
        self, rule: Rule, registry: MetricRegistry, permissions: Collection[str], limit_caps: bool
    ) -> None:
        self.rule, self.registry, self.perms = rule, registry, permissions
        self.limit_caps = limit_caps
        self.out = RuleValidationResult()
        self.metrics: set[str] = set()

    def err(self, path: str, code: str, msg: str, klass: str = "semantics") -> None:
        self.out.errors.append(Issue(path, code, msg, "error", klass, ()))  # type: ignore[arg-type]

    def warn(self, path: str, code: str, msg: str, klass: str = "semantics") -> None:
        self.out.warnings.append(Issue(path, code, msg, "warning", klass, ()))  # type: ignore[arg-type]

    # ----- operands -------------------------------------------------------------------------
    def unit_of(self, op: Any, path: str) -> str:
        if isinstance(op, MetricRef):
            self.metrics.add(op.metric)
            d = self.registry.get(op.metric)
            if d is None:
                self.err(path, "unknown_metric", f"Metric '{op.metric}' is not in the vocabulary.")
                return _UNKNOWN
            return d.unit
        if isinstance(op, Literal_):
            return _const_unit(op)
        units = [self.unit_of(o, f"{path}.operands[{i}]") for i, o in enumerate(op.operands)]
        known = [u for u in units if u != _UNKNOWN]
        if op.op in ("add", "sub", "min", "max") and len(set(known)) > 1:
            self.err(path, "type_mismatch", f"Cannot {op.op} values of different units: "
                     + " and ".join(sorted(set(known))) + ".")  # fmt: skip
            return _UNKNOWN
        if op.op in ("mul", "div"):
            return _UNKNOWN
        if op.op == "pct_of":
            return units[0]
        return known[0] if known else _UNKNOWN

    # ----- conditions -----------------------------------------------------------------------
    def comparison(self, c: Comparison, path: str) -> None:
        spec = OPERATORS[c.op]
        arity, allowed = spec
        left = self.unit_of(c.left, f"{path}.left")
        rights = [(n, getattr(c, n)) for n in ("right", "right2") if getattr(c, n) is not None]
        if len(rights) + 1 != arity and c.op not in ("in_set", "not_in_set"):
            self.err(path, "schema_error", f"Operator '{c.op}' needs {arity} operand(s) in node {c.node_id}.", "syntax")  # fmt: skip
        units = [left, *(self.unit_of(v, f"{path}.{n}") for n, v in rights)]
        for u in units:
            if u != _UNKNOWN and u not in allowed:
                self.err(path, "operator_not_applicable", f"Operator '{c.op}' does not apply to a {u} value in node {c.node_id}.")  # fmt: skip
        known = {u for u in units if u != _UNKNOWN}
        if known and not (known <= {"enum"} or known <= {"bool"}) and len(known) > 1:
            self.err(path, "type_mismatch", f"Node {c.node_id} compares {' with '.join(sorted(known))} without an explicit conversion.")  # fmt: skip
        if c.op in ("in_set", "not_in_set") and not c.set_values:
            self.err(f"{path}.set_values", "missing_action_param", f"Node {c.node_id} needs at least one value to test against.")  # fmt: skip
        if all(isinstance(x, Literal_) for x in (c.left, *(v for _, v in rights))) and rights:
            self.warn(path, "unreachable_branch", f"Node {c.node_id} compares constants only, so it is always true or always false.")  # fmt: skip
        if c.op in ("between", "outside") and isinstance(c.right, Literal_) and isinstance(c.right2, Literal_):  # fmt: skip
            lo, hi = c.right.const, c.right2.const
            if isinstance(lo, (int, Decimal)) and isinstance(hi, (int, Decimal)) and lo > hi:
                self.err(path, "unreachable_branch", f"Node {c.node_id} has its lower bound above its upper bound.")  # fmt: skip

    def condition(self, n: Any, path: str) -> None:
        if isinstance(n, Comparison):
            self.comparison(n, path)
        elif isinstance(n, TemporalNode):
            self.condition(n.child, f"{path}.child")
        elif isinstance(n, BooleanNode):
            if n.op == "n_of" and (n.n is None or n.n > len(n.children)):
                self.err(path, "unreachable_branch", f"Node {n.node_id} needs {n.n} of {len(n.children)} conditions, which can never hold.")  # fmt: skip
            for i, ch in enumerate(n.children):
                self.condition(ch, f"{path}.children[{i}]")

    # ----- actions and safety ---------------------------------------------------------------
    def actions(self) -> None:
        r = self.rule
        for i, a in enumerate(r.actions):
            base = f"actions[{i}]"
            self.out.referenced_actions.append(a.type)
            spec = _ACTION_SPECS.get(a.type)
            if spec is None:
                self.err(base, "schema_error", f"Unknown action '{a.type}'.", "syntax")
                continue
            for req in spec.params_schema.get("required", []):
                if a.params.get(req) is None:
                    self.err(f"{base}.params.{req}", "missing_action_param", f"Action {i + 1} ({spec.title}) is missing '{req}'.")  # fmt: skip
            only_tighten = a.params.get("only_tighten", True)
            if (a.type == "widen_stop" or only_tighten is False) and a.type in _STOP_ACTIONS:
                if LOOSEN_STOP_PERMISSION not in self.perms and "*" not in self.perms:
                    self.err(f"{base}.params.only_tighten", "permission_required", f"Loosening a stop needs the {LOOSEN_STOP_PERMISSION} permission (owner only).", "safety")  # fmt: skip
            if (a.type in _STOP_ACTIONS and (a.params.get("remove") or a.params.get("cancel"))) or (
                a.type == "place_order"
                and (("stop_loss" in a.params and not a.params["stop_loss"])
                     or a.params.get("require_native_stop") is False)
            ):  # fmt: skip
                self.err(base, "native_stop_violation", f"Action {i + 1} would leave a position without its native exchange stop-loss, which is never allowed.", "safety")  # fmt: skip
            self.feedback(a, base)

    def feedback(self, a: Any, base: str) -> None:
        t = self.rule.trigger.type
        loop = (
            (t in _ORDER_TRIGGERS and a.type in _ORDER_ACTIONS and not a.dry_run_only)
            or (t == "on_signal" and a.type == "emit_signal")
            or (a.type in ("enable_rule", "pause_rule") and a.type == "enable_rule"
                and str(a.params.get("rule_id")) == str(self.rule.rule_id))
        )  # fmt: skip
        if loop:
            self.err(base, "feedback_loop", f"This rule's own action ({a.type}) would re-trigger it on {t}; the rule would loop. Change the trigger or the action.", "safety")  # fmt: skip

    def guards(self) -> None:
        r = self.rule
        if r.trigger.type in _HIGH_FREQUENCY and (
            "cooldown_ms" not in r.limits.model_fields_set or r.limits.cooldown_ms == 0
        ):
            self.warn("guards.cooldown_seconds", "guard_missing", "No cooldown set; rule may fire on every update.", "safety")  # fmt: skip
        est = self.out.estimated_evaluations_per_minute
        if est >= 300:
            self.warn("trigger", "high_frequency", f"This rule would evaluate about {est} times a minute.", "performance")  # fmt: skip

    def budget(self) -> None:
        """SR-104: no role may save an action budget above its hard cap (issue #3232)."""
        for name in above_cap(self.rule.limits):
            self.err(f"limits.{name}", "schema_error", cap_message(name), "safety")

    def run(self) -> RuleValidationResult:
        r = self.rule
        if r.trigger.type == "on_metric_change" and r.trigger.metric:
            self.metrics.add(r.trigger.metric)
            if self.registry.get(r.trigger.metric) is None:
                self.err("trigger.metric", "unknown_metric", f"Trigger metric '{r.trigger.metric}' is not in the vocabulary.")  # fmt: skip
        self.condition(r.conditions, "conditions")
        self.actions()
        self.out.estimated_evaluations_per_minute = estimate_evaluations_per_minute(r)
        self.guards()
        if self.limit_caps:
            self.budget()
        self.out.referenced_variables = sorted(self.metrics)
        self.out.referenced_actions = sorted(set(self.out.referenced_actions))
        return self.out


def validate_rule(
    rule: Rule,
    registry: MetricRegistry,
    permissions: Collection[str] = (),
    *,
    limit_caps: bool = False,
) -> RuleValidationResult:
    """Validate one rule in isolation (conflicts between rules are E35-S07). `limit_caps` holds
    its action budget to the hard caps of `rules.limits`: the rule paths pass it, and alerts (E40),
    which share `RuleLimits`, do not."""
    return _Validator(rule, registry, permissions, limit_caps).run()


__all__ = ["RuleValidationResult", "estimate_evaluations_per_minute", "validate_rule"]
