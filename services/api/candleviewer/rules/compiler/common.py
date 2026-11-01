"""Shared helpers for the editor-model compilers (E35-T04).

Hostile-input bounds are enforced *before* any model is walked (security note: the compiler must
not itself be the DoS vector), and everything here is iterative so depth cannot exhaust the stack.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import ValidationError

from candleviewer.rules.ir.canonical import IrValueError
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.issues import Issue, RuleCompileError

MAX_ITEMS = 20_000  # total dict/list/scalar values in one editor document
MAX_DEPTH = 64  # nesting of the condition tree / document
MAX_GRAPH_NODES = 1_000
MAX_GRAPH_EDGES = 4_000
#: Comparison, boolean and temporal nodes under a rule's `conditions`, once at each place a node
#: occurs. The graph editor's own bound is the same number: either editor can store what it draws.
MAX_CONDITION_NODES = 1_000


def bounds_error(what: str) -> RuleCompileError:
    """The refusal of a document over the bounds: one `schema_error` naming both limits."""
    limits = f"(limit {MAX_ITEMS} values, {MAX_DEPTH} levels)"
    text = f"The {what} is too large or too deeply nested to compile {limits}."
    return RuleCompileError([Issue("$", "schema_error", text, klass="syntax")])


class ConditionNodeBoundError(RuleCompileError):
    """`conditions` holds more than `MAX_CONDITION_NODES` nodes: one `schema_error` at `conditions`.
    `cap` names the refusal for the counter that keeps it (`rule_authoring_cap_refused_total`)."""

    cap: ClassVar[Literal["condition_nodes"]] = "condition_nodes"


def condition_node_error() -> ConditionNodeBoundError:
    """The refusal of a rule over the node bound, its limit in the message."""
    text = f"A rule holds at most {MAX_CONDITION_NODES} condition nodes."
    return ConditionNodeBoundError([Issue("conditions", "schema_error", text, klass="syntax")])


def count_condition_nodes(doc: Any, limit: int = MAX_CONDITION_NODES + 1) -> int:
    """The condition nodes of `doc["conditions"]`, counted up to `limit`: each object reached from
    `conditions` through `children` and `child`, once at each place it occurs. Operands and actions
    are not nodes. Iterative, so depth cannot exhaust the stack."""
    stack: list[Any] = [doc.get("conditions")] if isinstance(doc, dict) else []
    count = 0
    while stack and count < limit:
        node = stack.pop()
        if isinstance(node, dict):
            count += 1
            stack.append(node.get("child"))
            children = node.get("children")
            if isinstance(children, (list, tuple)):
                stack.extend(children)
    return count


def count_values(doc: Any) -> int:
    """The values in `doc` as `check_bounds` counts them, for a document already within them."""
    stack, count = [doc], 0
    while stack:
        cur = stack.pop()
        count += 1
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
    return count


def check_bounds(doc: Any, what: str) -> None:
    """Reject over-sized or over-deep documents before walking them. Every value stacked and every
    child of the one at hand is still to be counted, so a container is refused by its length
    before its children are stacked, and the stack never holds more than `MAX_ITEMS`. A document
    within those bounds is then held to `MAX_CONDITION_NODES`, still before any model is built."""
    stack: list[tuple[Any, int]] = [(doc, 0)]
    count = 0
    while stack:
        cur, depth = stack.pop()
        count += 1
        wide = len(cur) if isinstance(cur, (dict, list, tuple)) else 0
        if count + len(stack) + wide > MAX_ITEMS or depth > MAX_DEPTH:
            raise bounds_error(what)
        if isinstance(cur, dict):
            stack.extend((v, depth + 1) for v in cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend((v, depth + 1) for v in cur)
    if count_condition_nodes(doc) > MAX_CONDITION_NODES:
        raise condition_node_error()


def _loc(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif isinstance(part, str) and part.isidentifier():
            out += f".{part}" if out else part
        # discriminator tags like 'comparison' are noise for the user; skipped.
    return out or "$"


def schema_issues(exc: ValidationError) -> list[Issue]:
    return [
        Issue(_loc(e["loc"]), "schema_error", str(e["msg"]), klass="syntax")
        for e in exc.errors(include_url=False, include_input=False, include_context=False)
    ]


def value_issues(exc: IrValueError) -> list[Issue]:
    """``schema_issues`` for a value the hash cannot hold (a non-finite number in ``params``)."""
    return [Issue(_loc(exc.loc), "schema_error", exc.reason, klass="syntax")]


def build_rule(doc: dict[str, Any]) -> Rule:
    try:
        return Rule.model_validate(doc)
    except ValidationError as exc:
        raise RuleCompileError(schema_issues(exc)) from exc
