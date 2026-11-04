"""Condition-DAG evaluation with full NodeTrace (11.5 E3/E4/E5, 11.9).

Evaluation is synchronous over an immutable snapshot. ``None`` is false and never coerces to 0
(E3). Short-circuited children are traced with ``result=None`` (E4). Children run in array
order (E5). Temporal / cross state is per scope instance and per ``node_id``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Final

from candleviewer.rules.errors import ConstantTypeError
from candleviewer.rules.evaluator.snapshot import MetricSnapshot, Value
from candleviewer.rules.ir.models import (
    ArithmeticNode,
    BooleanNode,
    Comparison,
    ConditionNode,
    Literal_,
    MetricRef,
    Operand,
    TemporalNode,
)

#: Hard cap on temporal ring-buffer length (DoS control; window_ms <= 86 400 000).
MAX_TEMPORAL_EVENTS = 10_000


@dataclass(frozen=True, slots=True)
class NodeTrace:
    node_id: str
    op: str
    result: bool | None  # None = not evaluated (short-circuit) or skipped
    left_value: Any = None
    right_value: Any = None


@dataclass(slots=True)
class _Temporal:
    true_since: int | None = None
    events: deque[int] = field(default_factory=lambda: deque(maxlen=MAX_TEMPORAL_EVENTS))
    last_result: bool | None = None
    last_change: int | None = None


@dataclass(slots=True)
class InstanceState:
    """Per-scope-instance node state; dropped when the active rule version changes."""

    prev: dict[str, tuple[Value, Value]] = field(default_factory=dict)
    temporal: dict[str, _Temporal] = field(default_factory=dict)


class EvalContext:
    def __init__(
        self,
        snapshot: MetricSnapshot,
        state: InstanceState,
        now_ms: int,
        checkpoint: Callable[[], None],
    ) -> None:
        self.snapshot = snapshot
        self.state = state
        self.now_ms = now_ms
        self.checkpoint = checkpoint
        self.trace: list[NodeTrace] = []
        self.skipped_reason: str | None = None
        self.metric_values: dict[str, Value] = {}

    def _unavailable(self, reason: str) -> None:
        if self.skipped_reason is None:
            self.skipped_reason = reason


def operand_value(op: Operand, ctx: EvalContext) -> Value:
    if isinstance(op, Literal_):
        return op.value()  # a number as a Decimal, decimal text too (#5807)
    if isinstance(op, MetricRef):
        mv = ctx.snapshot.get(op)
        ctx.metric_values[op.metric] = mv.value
        if mv.value is None:
            ctx._unavailable(mv.reason or "unavailable")
        return mv.value
    return _arith(op, ctx)


def _num(v: Value) -> Decimal | None:
    return v if isinstance(v, Decimal) else None


def _arith(node: ArithmeticNode, ctx: EvalContext) -> Value:
    vals = [_num(operand_value(o, ctx)) for o in node.operands]
    if any(v is None for v in vals):
        return None  # None propagates; never 0 (E3)
    nums = [v for v in vals if v is not None]
    a = nums[0]
    try:
        match node.op:
            case "add":
                return sum(nums, Decimal(0))
            case "sub":
                return a - sum(nums[1:], Decimal(0))
            case "mul":
                out = Decimal(1)
                for v in nums:
                    out *= v
                return out
            case "div":
                for v in nums[1:]:
                    if v == 0:
                        return None
                    a /= v
                return a
            case "abs":
                return abs(a)
            case "neg":
                return -a
            case "min":
                return min(nums)
            case "max":
                return max(nums)
            case "pct_of":
                if len(nums) < 2 or nums[1] == 0:
                    return None
                return a / nums[1] * 100
    except (InvalidOperation, DivisionByZero):
        return None
    return None  # pragma: no cover - exhaustive Literal


def _skip_subtree(node: ConditionNode, ctx: EvalContext) -> None:
    ctx.trace.append(NodeTrace(node.node_id, node.op, None))
    if isinstance(node, BooleanNode):
        for c in node.children:
            _skip_subtree(c, ctx)
    elif isinstance(node, TemporalNode):
        _skip_subtree(node.child, ctx)


def evaluate(node: ConditionNode, ctx: EvalContext) -> bool:
    ctx.checkpoint()
    if isinstance(node, Comparison):
        return _compare(node, ctx)
    if isinstance(node, BooleanNode):
        return _boolean(node, ctx)
    return _temporal(node, ctx)


def _boolean(node: BooleanNode, ctx: EvalContext) -> bool:
    idx = len(ctx.trace)
    ctx.trace.append(NodeTrace(node.node_id, node.op, None))
    need = node.n if node.op == "n_of" and node.n is not None else 1
    trues = 0
    result: bool | None = None
    children = node.children
    for i, child in enumerate(children):
        if result is not None:
            _skip_subtree(child, ctx)
            continue
        r = evaluate(child, ctx)
        trues += r
        remaining = len(children) - i - 1
        if node.op == "all_of" and not r:
            result = False
        elif node.op in ("any_of", "none_of") and r:
            result = node.op == "any_of"
        elif node.op == "n_of" and (trues >= need or trues + remaining < need):
            result = trues >= need
    if result is None:
        result = {"all_of": True, "any_of": False, "none_of": True}.get(node.op, trues >= need)
    ctx.trace[idx] = NodeTrace(node.node_id, node.op, result)
    return result


def _ordered(a: Value, b: Value) -> tuple[Decimal, Decimal] | None:
    x, y = _num(a), _num(b)
    return None if x is None or y is None else (x, y)


def _compare(node: Comparison, ctx: EvalContext) -> bool:
    left = operand_value(node.left, ctx)
    right = operand_value(node.right, ctx) if node.right is not None else None
    right2 = operand_value(node.right2, ctx) if node.right2 is not None else None
    result = _apply(node, left, right, right2, ctx)
    ctx.trace.append(NodeTrace(node.node_id, node.op, result, left, right))
    return result


def _apply(node: Comparison, left: Value, right: Value, right2: Value, ctx: EvalContext) -> bool:
    op = node.op
    if op in ("crosses_above", "crosses_below", "changed"):
        prev = ctx.state.prev.get(node.node_id)
        ctx.state.prev[node.node_id] = (left, right)
        if prev is None or left is None:
            return False  # no previous snapshot => no phantom cross (11.6)
        if op == "changed":
            return prev[0] is not None and prev[0] != left
        now, before = _ordered(left, right), _ordered(prev[0], prev[1])
        if now is None or before is None:
            return False
        if op == "crosses_above":
            return before[0] <= before[1] and now[0] > now[1]
        return before[0] >= before[1] and now[0] < now[1]
    if left is None:
        return False  # E3: None is false, never 0
    if op == "is_true":
        return left is True
    if op == "is_false":
        return left is False
    if op == "in_set":
        return isinstance(left, str) and left in node.set_values
    if op == "not_in_set":
        return isinstance(left, str) and left not in node.set_values
    if right is None:
        return False
    if op in ("eq", "neq"):
        pair = _ordered(left, right)
        if pair is not None and node.tolerance is not None:
            same = abs(pair[0] - pair[1]) <= node.tolerance
        else:
            same = left == right
        return same if op == "eq" else not same
    pair = _ordered(left, right)
    if pair is None:
        return False
    a, b = pair
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "lt":
        return a < b
    if op == "lte":
        return a <= b
    hi = _num(right2)
    if hi is None:
        return False
    lo, hi = min(b, hi), max(b, hi)
    inside = lo <= a <= hi
    return inside if op == "between" else not inside


def _temporal(node: TemporalNode, ctx: EvalContext) -> bool:
    idx = len(ctx.trace)
    ctx.trace.append(NodeTrace(node.node_id, node.op, None))
    child = evaluate(node.child, ctx)
    st = ctx.state.temporal.setdefault(node.node_id, _Temporal())
    now = ctx.now_ms
    horizon = now - node.window_ms
    if node.op == "sustained_for":
        st.true_since = (st.true_since if st.true_since is not None else now) if child else None
        result = st.true_since is not None and now - st.true_since >= node.window_ms
    elif node.op == "stable_for":
        if st.last_result is None or st.last_result != child:
            st.last_change = now
        st.last_result = child
        result = st.last_change is not None and now - st.last_change >= node.window_ms
    else:
        if child:
            st.events.append(now)
        while st.events and st.events[0] < horizon:
            st.events.popleft()
        need = 1 if node.op == "occurred_within" else node.min_count
        result = len(st.events) >= need
    ctx.trace[idx] = NodeTrace(node.node_id, node.op, result)
    return result


def referenced_metrics(node: ConditionNode) -> list[MetricRef]:
    """All metric refs in array (deterministic) order."""
    out: list[MetricRef] = []

    def operand(o: Operand | None) -> None:
        if isinstance(o, MetricRef):
            out.append(o)
        elif isinstance(o, ArithmeticNode):
            for x in o.operands:
                operand(x)

    def walk(n: ConditionNode) -> None:
        if isinstance(n, Comparison):
            operand(n.left)
            operand(n.right)
            operand(n.right2)
        elif isinstance(n, BooleanNode):
            for c in n.children:
                walk(c)
        else:
            walk(n.child)

    walk(node)
    return out


#: The comparisons that order their operands (`_ordered`): each operand of one is a number.
ORDERED_OPS: Final = frozenset(
    {"gt", "gte", "lt", "lte", "between", "outside", "crosses_above", "crosses_below"}
)
#: Why `check_constants` refuses a constant.
NOT_A_NUMBER: Final = "Constant should be a decimal number"


def _reads_as_number(text: str) -> bool:
    """Text the rule validator reads as a number (`validator._const_unit`): a percentage, or any
    text `Decimal` reads, `NaN` and `Infinity` among them."""
    if text.endswith("%"):
        return True
    try:
        Decimal(text)
    except ArithmeticError:
        return False
    return True


def check_constants(node: ConditionNode, loc: tuple[str | int, ...] = ("conditions",)) -> None:
    """Refuse the first constant under `node` the evaluator cannot read as its place needs, with
    `ConstantTypeError` at its path (#5807): where a comparison orders its operands (`ORDERED_OPS`)
    or an arithmetic node computes, a constant must be a number (`Literal_.value` a `Decimal`), and
    anywhere, text that reads as a number must be decimal text. A stored rule holding another is
    refused at load (`manager.quarantine_path`) and never evaluated, so no number is compared as
    text. Other text, in `eq`, `neq` or `changed`, is an enum value."""
    if isinstance(node, BooleanNode):
        for i, child in enumerate(node.children):
            check_constants(child, (*loc, "children", i))
    elif isinstance(node, TemporalNode):
        check_constants(node.child, (*loc, "child"))
    else:
        number = node.op in ORDERED_OPS
        for name, op in (("left", node.left), ("right", node.right), ("right2", node.right2)):
            if op is not None:
                _check_operand(op, number, (*loc, name))


def _check_operand(op: Operand, number: bool, loc: tuple[str | int, ...]) -> None:
    if isinstance(op, ArithmeticNode):
        for i, child in enumerate(op.operands):
            _check_operand(child, True, (*loc, "operands", i))
    elif isinstance(op, Literal_):
        value = op.value()
        if isinstance(value, Decimal):
            return
        if number or (isinstance(value, str) and _reads_as_number(value)):
            raise ConstantTypeError((*loc, "const"), NOT_A_NUMBER)
