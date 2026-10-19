"""Notify-only alert compiler (E40-T02) - the security gate that keeps alerts from acting.

``AlertCompiler.compile(raw)`` turns an untrusted ``condition_ir`` JSON value into a
``CompiledAlert`` or raises ``AlertIrInvalid``. Steps, in order (each fails closed):

1. Structural **allow-list** walk over the raw JSON - every object must classify as one of
   ``PERMITTED_KINDS`` with exactly that kind's keys. Anything else (an ``actions`` key, an
   action node nested in ``variables``, a renamed key, a unicode look-alike op) is refused by
   construction; a deny-list would fail open the day E35 adds a node kind. Size/depth bounded.
2. Schema validation against ``AlertConditionIr`` (``extra="forbid"`` pydantic models).
3. Trigger validation (``RuleTrigger`` per-type requirements, 5-field UTC cron, timeframe).
4. Metric resolution against E35's ``MetricRegistry``: unknown -> offending ``node_id`` plus
   the nearest valid names; E35's semantic validator for operator/unit checks.
5. ``condition_hash`` via E35's canonicalisation (``rules.ir.canonical.condition_hash``).
6. Estimated detector metrics flagged for the UI's "(estimated)" qualifier.

``validate_template`` checks a Mustache ``message_template`` against the placeholder allow-list.
Pure, synchronous and side-effect free; no I/O.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator
from typing import Any, get_args
from uuid import UUID

from pydantic import ValidationError

from candleviewer.alerts.errors import AlertIrInvalid, AlertIssue, RejectReason
from candleviewer.alerts.models import AlertCondition, CompiledAlert
from candleviewer.domain.primitives import RuleId
from candleviewer.rules.ir import Action, Rule, RuleLimits, RuleScope
from candleviewer.rules.ir.canonical import condition_hash
from candleviewer.rules.ir.models import (
    ActionType,
    ArithmeticOp,
    BooleanOp,
    ComparisonOp,
    TemporalOp,
)
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary.registry import MetricRegistry

MAX_NODES = 512
MAX_DEPTH = 32

COMPARISON_OPS = frozenset(get_args(ComparisonOp))
LOGICAL_OPS = frozenset(get_args(BooleanOp))
TEMPORAL_OPS = frozenset(get_args(TemporalOp))
ARITHMETIC_OPS = frozenset(get_args(ArithmeticOp))
ACTION_TYPES = frozenset(get_args(ActionType))

#: Exact key set per permitted node kind. Nothing outside this table can appear in an alert.
PERMITTED_KINDS: dict[str, frozenset[str]] = {
    "root": frozenset({"ir_version", "trigger", "conditions", "variables", "limits"}),
    "trigger": frozenset({"type", "timeframe", "interval_ms", "cron", "metric", "debounce_ms"}),
    "comparison": frozenset(
        {"node_id", "op", "left", "right", "right2", "set_values", "tolerance"}
    ),
    "logical": frozenset({"node_id", "op", "children", "n"}),
    "temporal": frozenset({"node_id", "op", "child", "window_ms", "min_count"}),
    "operand:metric": frozenset({"metric", "params", "symbol", "account_id", "timeframe"}),
    "operand:const": frozenset({"const"}),
    "operand:arith": frozenset({"node_id", "op", "operands"}),
    "limits": frozenset(RuleLimits.model_fields),
}
_SCALAR = (str, int, float, bool, type(None))
#: Supported bar timeframes (the bar-close set); anything else, e.g. 9999w, is a 422.
TIMEFRAMES = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"})
_CRON_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_CRON_ATOM = re.compile(r"^(\*|[0-9]{1,2}(-[0-9]{1,2})?)(/[0-9]{1,2})?$", re.ASCII)
_NOTIFY = Action(
    node_id="__alert_notify",
    type="send_notification",
    params={"channel": "in_app", "severity": "info", "template": ""},
)
_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
#: Explicit allow-list of leaf names per namespace (never a deny-list: it fails open). Shared
#: with the future renderer's context. No account/api/key/email/owner/webhook field exists here.
TEMPLATE_FIELDS: dict[str, frozenset[str]] = {
    "market": frozenset({
        "symbol", "last", "last_price", "price", "bid", "ask", "mark", "mark_price", "index",
        "index_price", "funding_rate", "open_interest", "volume_24h", "change_24h_pct",
    }),
    "footprint": frozenset({
        "delta", "volume", "poc", "imbalance", "cvd", "buy_volume", "sell_volume",
        "sell_stack_size", "buy_stack_size", "timeframe",
    }),
    "position": frozenset({
        "side", "size", "entry", "entry_price", "unrealised_pnl", "leverage", "liquidation_price",
    }),
    "alert": frozenset({"name", "id", "triggered_at", "condition_summary", "severity"}),
}  # fmt: skip
_SEGMENT = re.compile(r"^[a-z][a-z0-9_]{0,48}$", re.ASCII)
_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,48}$")


def _reject(reason: RejectReason, field: str, rule: str, msg: str, node_id: str | None) -> None:
    raise AlertIrInvalid(reason, [AlertIssue(field, rule, msg, node_id)])


def _not_permitted(path: str, msg: str, node_id: str | None) -> None:
    _reject("action_node", path, "not_permitted", msg, node_id)


class _Walker:
    """Allow-list walk over raw JSON: classify every object, check its exact key set."""

    def __init__(self) -> None:
        self.count = 0

    def enter(self, path: str, depth: int, node_id: str | None) -> None:
        self.count += 1
        if self.count > MAX_NODES or depth > MAX_DEPTH:
            msg = f"The alert is too large (at most {MAX_NODES} nodes, {MAX_DEPTH} levels deep)."
            _reject("too_large", path, "too_large", msg, node_id)

    @staticmethod
    def obj(v: Any, path: str, what: str, node_id: str | None) -> dict[Any, Any]:
        if not isinstance(v, dict):
            _not_permitted(path, f"Expected {what} here.", node_id)
            raise AssertionError  # pragma: no cover - _not_permitted always raises
        return v

    @staticmethod
    def keys(kind: str, obj: dict[Any, Any], path: str, node_id: str | None, *nested: str) -> None:
        """Exact key set for ``kind``; every value not named in ``nested`` must be a scalar."""
        allowed = PERMITTED_KINDS[kind]
        for k, v in obj.items():
            if not isinstance(k, str) or k not in allowed:
                label = "an action" if k in ("actions", "action", "type", "params") else repr(k)
                where = kind.split(":")[0]
                _not_permitted(f"{path}.{k}", f"Alerts only notify: {label} is not allowed in a "
                               f"{where} node.", node_id)  # fmt: skip
            elif k not in nested and not isinstance(v, _SCALAR):
                _not_permitted(f"{path}.{k}", f"'{k}' must be a plain value.", node_id)

    def root(self, raw: Any) -> None:
        o = self.obj(raw, "condition_ir", "an alert condition object", None)
        self.enter("condition_ir", 0, None)
        self.keys("root", o, "condition_ir", None, "trigger", "conditions", "variables", "limits")
        for kind in ("trigger", "limits"):
            if kind in o:
                self.enter(kind, 1, None)
                self.keys(kind, self.obj(o[kind], kind, f"a {kind} object", None), kind, None)
        if "conditions" in o:
            self.condition(o["conditions"], "conditions", 1, None)
        if "variables" in o:
            for name, op in self.obj(o["variables"], "variables", "an object", None).items():
                if not isinstance(name, str) or not _VARIABLE_NAME.fullmatch(name):
                    _not_permitted(f"variables.{name}", "Variable names use lowercase letters, "
                                   "digits and underscores.", None)  # fmt: skip
                self.operand(op, f"variables.{name}", 1, None)

    def condition(self, v: Any, path: str, depth: int, parent: str | None) -> None:
        o = self.obj(v, path, "a condition node", parent)
        nid = o.get("node_id") if isinstance(o.get("node_id"), str) else parent
        self.enter(path, depth, nid)
        op = o.get("op") if isinstance(o.get("op"), str) else None
        if op in LOGICAL_OPS:
            self.keys("logical", o, path, nid, "children")
            kids = o.get("children")
            if not isinstance(kids, list):
                _not_permitted(f"{path}.children", "Expected a list of conditions.", nid)
                return
            if len(kids) > MAX_NODES:  # size, not an action: keep the rejection label honest
                self.enter(path, MAX_DEPTH + 1, nid)
            for i, ch in enumerate(kids):
                self.condition(ch, f"{path}.children[{i}]", depth + 1, nid)
        elif op in TEMPORAL_OPS:
            self.keys("temporal", o, path, nid, "child")
            self.condition(o.get("child"), f"{path}.child", depth + 1, nid)
        elif op in COMPARISON_OPS:
            self.keys("comparison", o, path, nid, "left", "right", "right2", "set_values")
            for side in ("left", "right", "right2"):
                if o.get(side) is not None:
                    self.operand(o[side], f"{path}.{side}", depth + 1, nid)
            sv = o.get("set_values", [])
            if not isinstance(sv, list) or not all(isinstance(s, str) for s in sv):
                _not_permitted(f"{path}.set_values", "Expected a list of strings.", nid)
        else:
            _not_permitted(path, f"'{op}' is not a condition an alert can use.", nid)

    def operand(self, v: Any, path: str, depth: int, parent: str | None) -> None:
        o = self.obj(v, path, "a metric, a constant or arithmetic", parent)
        nid = o.get("node_id") if isinstance(o.get("node_id"), str) else parent
        self.enter(path, depth, nid)
        if "metric" in o:
            self.keys("operand:metric", o, path, nid, "params")
            params = self.obj(o.get("params", {}), f"{path}.params", "an object", nid)
            for k, pv in params.items():
                if not isinstance(k, str) or not isinstance(pv, _SCALAR):
                    _not_permitted(f"{path}.params.{k}", "Metric parameters are plain values.", nid)
        elif "const" in o:
            self.keys("operand:const", o, path, nid)
        elif isinstance(o.get("op"), str) and o["op"] in ARITHMETIC_OPS:
            self.keys("operand:arith", o, path, nid, "operands")
            ops = o.get("operands")
            if not isinstance(ops, list):
                _not_permitted(f"{path}.operands", "Expected a list of operands.", nid)
                return
            for i, sub in enumerate(ops):
                self.operand(sub, f"{path}.operands[{i}]", depth + 1, nid)
        else:
            _not_permitted(path, "Only metrics, constants and arithmetic are allowed here.", nid)


def _cron_ok(expr: str) -> bool:
    fields = expr.split(" ")
    if len(fields) != 5:
        return False
    for f, (lo, hi) in zip(fields, _CRON_FIELDS, strict=True):
        for atom in f.split(","):
            if not _CRON_ATOM.fullmatch(atom):
                return False
            nums = [int(n) for n in re.findall(r"[0-9]+", atom.split("/")[0])]
            step = atom.split("/")[1] if "/" in atom else "1"
            if any(not lo <= n <= hi for n in nums) or int(step) == 0:
                return False
            if len(nums) == 2 and nums[0] > nums[1]:
                return False
    return True


def _check_trigger(c: AlertCondition, registry: MetricRegistry) -> None:
    t = c.trigger
    if t.type == "on_bar_close" and (t.timeframe or "") not in TIMEFRAMES:
        _reject("bad_trigger", "trigger.timeframe", "bad_trigger",
                "A bar-close alert needs a timeframe such as 1m, 5m, 1h or 1d.", None)  # fmt: skip
    if t.type == "on_schedule" and not _cron_ok(t.cron or ""):
        _reject("bad_trigger", "trigger.cron", "bad_trigger",
                "A scheduled alert needs a 5-field UTC cron like '0 9 * * 1-5'.", None)  # fmt: skip
    if t.type == "on_metric_change" and registry.get(t.metric or "") is None:
        _reject("unknown_metric", "trigger.metric", "unknown_metric",
                f"Trigger metric '{t.metric}' is not a known metric.", None)  # fmt: skip


def _metric_refs(raw: dict[str, Any]) -> Iterator[tuple[str, str | None, str]]:
    """(metric, owning node_id, path) for every metric operand in the walked raw tree."""

    def visit(v: Any, path: str, nid: str | None) -> Iterator[tuple[str, str | None, str]]:
        if isinstance(v, dict):
            nid = v["node_id"] if isinstance(v.get("node_id"), str) else nid
            if isinstance(v.get("metric"), str) and path != "trigger":
                yield v["metric"], nid, path
            for k, sub in v.items():
                if k not in ("params", "const", "trigger", "limits"):
                    yield from visit(sub, f"{path}.{k}" if path else k, nid)
        elif isinstance(v, list):
            for i, sub in enumerate(v):
                yield from visit(sub, f"{path}[{i}]", nid)

    yield from visit(raw, "", None)


def _check_metrics(raw: dict[str, Any], registry: MetricRegistry) -> tuple[str, ...]:
    names: list[str] = []
    for metric, nid, path in _metric_refs(raw):
        if registry.get(metric) is None:
            near = tuple(difflib.get_close_matches(metric, registry.names(), n=3, cutoff=0.5))
            hint = f" Did you mean {', '.join(near)}?" if near else ""
            where = f" in node {nid}" if nid else ""
            raise AlertIrInvalid("unknown_metric", [AlertIssue(
                path, "unknown_metric", f"Unknown metric '{metric}'{where}.{hint}", nid, near,
            )])  # fmt: skip
        names.append(metric)
    return tuple(sorted(set(names)))


def _schema_issues(exc: ValidationError) -> list[AlertIssue]:
    out = []
    for e in exc.errors(include_url=False, include_input=False)[:20]:
        field = ".".join(str(p) for p in e["loc"]) or "condition_ir"
        out.append(AlertIssue(field, "schema_error", str(e["msg"])))
    return out


def _placeholder_ok(name: str, metrics: frozenset[str]) -> bool:
    ns, dot, leaf = name.partition(".")
    if not dot or ns not in TEMPLATE_FIELDS or not _SEGMENT.fullmatch(leaf):
        return False  # exactly <namespace>.<leaf>: no deeper paths, no unicode, no whitespace
    # Context derived from the condition: metrics it references are available as market/footprint.
    return leaf in TEMPLATE_FIELDS[ns] or (ns in ("market", "footprint") and leaf in metrics)


def validate_template(template: str, metrics: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Every ``{{placeholder}}`` must be an allow-listed ``namespace.field`` (or a metric the
    compiled condition references); returns the names. Only spaces/tabs may pad the name."""
    allowed_metrics = frozenset(metrics)
    names: list[str] = []
    for m in _PLACEHOLDER.finditer(template):
        raw = m.group(1)
        name = raw.strip(" \t")  # a newline or any other char inside a placeholder is refused
        if not _placeholder_ok(name, allowed_metrics):
            _reject("bad_template", "message_template", "placeholder_not_allowed",
                    f"Placeholder '{{{{{raw[:60]}}}}}' is not allowed. Use market.*, "
                    "footprint.*, position.* or alert.* values.", None)  # fmt: skip
        names.append(name)
    rest = _PLACEHOLDER.sub("", template)
    if "{{" in rest or "}}" in rest:
        _reject("bad_template", "message_template", "placeholder_not_allowed",
                "The message has an unclosed '{{' or a stray '}}'.", None)  # fmt: skip
    return tuple(names)


class AlertCompiler:
    """Compile an untrusted ``condition_ir`` into a notify-only ``CompiledAlert``."""

    def __init__(self, registry: MetricRegistry) -> None:
        self._registry = registry

    def compile(self, raw: Any) -> CompiledAlert:
        _Walker().root(raw)  # 1. structural allow-list (fails closed on any unknown shape)
        try:
            cond = AlertCondition.model_validate(raw)  # 2. AlertConditionIr schema
        except ValidationError as exc:
            reason: RejectReason = "bad_trigger" if _is_trigger_error(exc) else "schema"
            raise AlertIrInvalid(reason, _schema_issues(exc)) from None
        _check_trigger(cond, self._registry)  # 3.
        metrics = _check_metrics(raw, self._registry)  # 4. registry resolution
        self._semantic(cond)
        dumped = cond.model_dump(mode="python", exclude_none=False)
        estimated = tuple(
            m for m in metrics if (d := self._registry.get(m)) and d.confidence == "estimated"
        )
        return CompiledAlert(
            condition=cond,
            condition_ir=cond.model_dump(mode="json", exclude_defaults=True),
            condition_hash=condition_hash(dumped),  # 5. shared with E35 rules
            metrics=metrics,
            estimated_metrics=estimated,  # 6.
        )

    def _semantic(self, cond: AlertCondition) -> None:
        """E35's semantic validator (operators, units) over the condition, notify-only."""
        rule = Rule(
            rule_id=RuleId(UUID(int=0)), version=1, name="alert", enabled=False, mode="disabled",
            scope=RuleScope(level="global"), trigger=cond.trigger, conditions=cond.conditions,
            actions=(_NOTIFY,), limits=cond.limits or RuleLimits(),
        )  # fmt: skip
        result = validate_rule(rule, self._registry)
        if result.errors:
            issues = [AlertIssue(i.path, i.code, i.message) for i in result.errors]
            raise AlertIrInvalid("schema", issues)


def _is_trigger_error(exc: ValidationError) -> bool:
    return any(e["loc"][:1] == ("trigger",) for e in exc.errors(include_url=False))


__all__ = [
    "MAX_DEPTH", "MAX_NODES", "PERMITTED_KINDS", "AlertCompiler", "validate_template",
]  # fmt: skip
