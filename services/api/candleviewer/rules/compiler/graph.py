"""Graph-editor front-end: ``compile_graph`` / ``to_graph_model`` (E35-T04, ADR-0007 rule 4).

Graph model = the rule envelope (``rule_id``, ``scope``, ``trigger``, ``limits`` ...) plus
``nodes`` and ``edges``:

* node: ``{"id", "type": comparison|boolean|temporal|arithmetic|action, "data": {...}}``; ``data``
  holds the node's own fields (``op``, ``window_ms``, ``params``, inline metric/const operands).
* edge: ``{"from": producer_id, "to": consumer_id, "port": left|right|right2|in|child|when}``.
  ``in`` edges (boolean children, arithmetic operands) keep their order in ``edges``. Each action
  has exactly one ``when`` edge from the single root condition.

Well-formedness (cycles, multiple sinks, orphans, dangling ports) is reported by node id. A node
feeding several consumers is *shared*: it expands to the same ``node_id`` at each use, which the
form-subset detector flags as graph-only (recorded in ``graph_layout`` at compile time).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from candleviewer.rules.compiler.common import (
    MAX_CONDITION_NODES,
    MAX_DEPTH,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_ITEMS,
    bounds_error,
    build_rule,
    check_bounds,
    condition_node_error,
    count_values,
)
from candleviewer.rules.ir import (
    ArithmeticNode,
    BooleanNode,
    Comparison,
    Rule,
    TemporalNode,
    form_incompatibility_reasons,
)
from candleviewer.rules.issues import Issue, RuleCompileError

_TYPES = ("comparison", "boolean", "temporal", "arithmetic", "operand", "action")
_CONDITIONS = ("comparison", "boolean", "temporal")  # the nodes `MAX_CONDITION_NODES` counts
_PORTS = ("left", "right", "right2", "in", "child", "when")
_OPERAND_PORTS = ("left", "right", "right2")
_UNARY = ("is_true", "is_false", "changed", "in_set", "not_in_set")
_Ins = dict[str, dict[str, list[str]]]


def _err(code: str, path: str, msg: str, *ids: str) -> Issue:
    return Issue(path, code, msg, klass="syntax", node_ids=ids)


def _fail(*issues: Issue) -> RuleCompileError:
    return RuleCompileError(list(issues))


def _find_cycle(adj: dict[str, list[str]]) -> list[str] | None:
    """Iterative DFS; returns an ordered node-id path closing on its first node, or None."""
    color: dict[str, int] = {}
    for start in sorted(adj):
        if color.get(start):
            continue
        path: list[str] = []
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            n, i = stack.pop()
            if i == 0:
                color[n] = 1
                path.append(n)
            kids = adj.get(n, [])
            if i < len(kids):
                stack.append((n, i + 1))
                k = kids[i]
                if color.get(k) == 1:
                    return [*path[path.index(k) :], k]
                if not color.get(k):
                    stack.append((k, 0))
            else:
                color[n] = 2
                path.pop()
    return None


def _index(model: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes, edges = model.get("nodes"), model.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        raise _fail(_err("schema_error", "nodes", "A graph needs a list of nodes and edges."))
    if len(nodes) > MAX_GRAPH_NODES or len(edges) > MAX_GRAPH_EDGES:
        raise _fail(_err("schema_error", "nodes", "The graph has too many nodes or edges."))
    by_id: dict[str, dict[str, Any]] = {}
    issues: list[Issue] = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            issues.append(_err("schema_error", f"nodes[{i}]", f"Node {i + 1} has no id."))
            continue
        nid = n["id"]
        if nid in by_id:
            issues.append(_err("schema_error", f"nodes[{i}]", f"Duplicate node id {nid}.", nid))
        if n.get("type") not in _TYPES or not isinstance(n.get("data", {}), dict):
            issues.append(
                _err("schema_error", f"nodes[{i}]", f"Node {nid} has an unknown type.", nid)
            )
        by_id[nid] = n
    clean: list[dict[str, Any]] = []
    for i, e in enumerate(edges):
        if not (isinstance(e, dict) and e.get("from") in by_id and e.get("to") in by_id
                and e.get("port") in _PORTS):  # fmt: skip
            issues.append(
                _err("dangling_port", f"edges[{i}]", f"Edge {i + 1} joins a missing node or port.")
            )
        else:
            clean.append(e)
    if issues:
        raise _fail(*issues)
    return by_id, clean


def _required_ports(n: dict[str, Any]) -> list[str]:
    data = n.get("data", {})
    t = n["type"]
    if t == "temporal":
        return ["child"]
    if t in ("boolean", "arithmetic"):
        return ["in"]
    if t == "action":
        return ["when"]
    if t == "operand":
        return []
    # comparison: inline operands in ``data`` satisfy a port; arity decided by the operator.
    arity = {
        "is_true": 1,
        "is_false": 1,
        "changed": 1,
        "in_set": 1,
        "not_in_set": 1,
        "between": 3,
        "outside": 3,
    }.get(str(data.get("op")), 2)
    return [p for p in _OPERAND_PORTS[:arity] if p not in data]


def _wellformed(by_id: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[str, _Ins]:
    adj: dict[str, list[str]] = defaultdict(list)
    ins: _Ins = defaultdict(lambda: defaultdict(list))
    for e in edges:
        adj[e["to"]].append(e["from"])
        ins[e["to"]][e["port"]].append(e["from"])
    cycle = _find_cycle(adj)
    if cycle is not None:
        raise _fail(
            _err("cycle_detected", "edges", "The graph contains a cycle: "
                 + " -> ".join(cycle) + ". Rules must be acyclic.", *cycle[:-1])
        )  # fmt: skip
    issues: list[Issue] = []
    actions = sorted(i for i, n in by_id.items() if n["type"] == "action")
    if not actions:
        issues.append(_err("orphan_node", "nodes", "The graph has no action node."))
    for nid, n in sorted(by_id.items()):
        for p in _required_ports(n):
            if not ins[nid].get(p):
                issues.append(
                    _err(
                        "dangling_port",
                        f"nodes.{nid}",
                        f"Node {nid} is missing its '{p}' input.",
                        nid,
                    )
                )
        if n["type"] == "action" and len(ins[nid].get("when", [])) > 1:
            issues.append(
                _err(
                    "multiple_sinks",
                    f"nodes.{nid}",
                    f"Action {nid} has more than one condition feeding it.",
                    nid,
                )
            )
    roots = sorted({s for a in actions for s in ins[a].get("when", [])})
    if len(roots) > 1:
        issues.append(
            _err(
                "multiple_sinks",
                "edges",
                "Conditions must reduce to a single boolean; found " + ", ".join(roots) + ".",
                *roots,
            )
        )
    if issues:
        raise _fail(*issues)
    reach: set[str] = set()
    todo = [roots[0]]
    while todo:
        cur = todo.pop()
        if cur not in reach:
            reach.add(cur)
            todo.extend(s for ps in ins[cur].values() for s in ps)
    orphans = sorted(i for i in by_id if i not in reach and i not in actions)
    if orphans:
        raise _fail(
            *(
                _err("orphan_node", f"nodes.{o}", f"Node {o} does not lead to any action.", o)
                for o in orphans
            )
        )
    return roots[0], ins


def _copy_values(n: dict[str, Any], port: dict[str, list[str]]) -> int:
    """The values one copy of `n` adds to the expanded conditions, as `check_bounds` counts them:
    its object, each data value it keeps, its node id and the list holding its inputs. Each input
    charges its own copy."""
    data, t = n.get("data", {}), n["type"]
    if t == "operand":
        return 1 + sum(count_values(v) for v in data.values())
    if t == "comparison":
        set_keys = {p for p in _OPERAND_PORTS if port.get(p)}
    else:
        set_keys = {"child" if t == "temporal" else "children" if t == "boolean" else "operands"}
    kept = sum(count_values(v) for k, v in data.items() if k != "node_id" and k not in set_keys)
    return 2 + kept + (t not in ("comparison", "temporal"))


def compile_graph(model: dict[str, Any], rule_id: Any = None) -> Rule:
    """Compile a graph-editor model to the canonical IR; structural faults raise (no IR). The
    graph compiler charges shared-node copies against the document bounds: every copy is charged
    before it is built, so an expansion past `MAX_ITEMS` values or `MAX_CONDITION_NODES` condition
    nodes is refused, never materialised."""
    check_bounds(model, "graph model")
    by_id, edges = _index(model)
    root, ins = _wellformed(by_id, edges)
    budget = MAX_ITEMS  # the values the expanded conditions may still add
    nodes = MAX_CONDITION_NODES  # the condition nodes they may still hold
    costs: dict[str, int] = {}  # one copy's own values, per node

    def build(nid: str, depth: int) -> dict[str, Any]:
        nonlocal budget, nodes
        if depth > MAX_DEPTH:
            raise _fail(
                _err("schema_error", f"nodes.{nid}", "The graph is nested too deeply.", nid)
            )
        n = by_id[nid]
        if nid not in costs:
            costs[nid] = _copy_values(n, ins[nid])
        budget -= costs[nid]
        if budget < 0:
            raise bounds_error("graph model")
        if n["type"] in _CONDITIONS:
            nodes -= 1
            if nodes < 0:
                raise condition_node_error()
        if n["type"] == "operand":  # metric ref / {const}: a leaf with no node_id of its own
            return dict(n.get("data", {}))
        out: dict[str, Any] = {**n.get("data", {}), "node_id": nid}
        port = ins[nid]
        if n["type"] == "comparison":
            for p in _OPERAND_PORTS:
                if port.get(p):
                    out[p] = build(port[p][0], depth + 1)
        elif n["type"] == "temporal":
            out["child"] = build(port["child"][0], depth + 1)
        else:
            key = "children" if n["type"] == "boolean" else "operands"
            out[key] = [build(s, depth + 1) for s in port["in"]]
        return out

    doc = {k: v for k, v in model.items() if k not in ("nodes", "edges")}
    if rule_id is not None:
        doc["rule_id"] = rule_id
    doc["editor"] = "graph"
    doc["conditions"] = build(root, 0)
    # Action order is semantic (on_error=abort_remaining): it follows the node-list order, never
    # the id sort order (E35-Q02 found ids like a10 < a2 reordering actions across the hop).
    doc["actions"] = [
        {**n.get("data", {}), "node_id": n["id"]} for n in model["nodes"] if n["type"] == "action"
    ]
    rule = build_rule(doc)
    reasons = form_incompatibility_reasons(rule)
    if reasons:  # marked at compile time so the form editor renders read-only on first load
        layout = dict(rule.graph_layout or {})
        layout["node_only_constructs"] = reasons
        rule = rule.model_copy(update={"graph_layout": layout})
    return rule


_NODE_FIELDS = {"node_id", "children", "child", "operands", "left", "right", "right2"}


def _layout(
    order: list[str], parents: dict[str, list[str]], root_first: list[str]
) -> dict[str, Any]:
    """Deterministic layered placement: column = longest path from the actions (x), row = order."""
    depth: dict[str, int] = {}
    for nid in root_first:  # parents are always visited before children in ``root_first``
        depth[nid] = max((depth[p] + 1 for p in parents.get(nid, []) if p in depth), default=0)
    rows: dict[int, int] = defaultdict(int)
    out: dict[str, Any] = {}
    for nid in sorted(order, key=lambda i: (depth[i], root_first.index(i))):
        d = depth[nid]
        out[nid] = {"x": 280 * d, "y": 120 * rows[d]}
        rows[d] += 1
    return {"auto": True, "positions": out}


def to_graph_model(ir: Rule) -> dict[str, Any]:
    """Decompile any IR to the graph model; auto-layout is deterministic when absent."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    parents: dict[str, list[str]] = defaultdict(list)
    topo: list[str] = []
    counter = [0]

    def add_edge(src: str, dst: str, port: str) -> None:
        edges.append({"from": src, "to": dst, "port": port})
        parents[src].append(dst)

    def own(node: Any) -> dict[str, Any]:
        d = node.model_dump(mode="python", exclude_none=True)
        return {k: v for k, v in d.items() if k not in _NODE_FIELDS}

    def operand(op: Any, consumer: str, port: str) -> None:
        if isinstance(op, ArithmeticNode):
            visit(op, consumer, port)
            return
        counter[0] += 1
        oid = f"{consumer}.{port}.{counter[0]}"
        nodes[oid] = {
            "id": oid,
            "type": "operand",
            "data": op.model_dump(mode="python", exclude_none=True),
        }
        topo.append(oid)
        add_edge(oid, consumer, port)

    def visit(node: Any, consumer: str, port: str) -> None:
        nid = node.node_id
        add_edge(nid, consumer, port)
        if nid in nodes:  # shared node: already expanded
            return
        topo.append(nid)
        if isinstance(node, Comparison):
            nodes[nid] = {"id": nid, "type": "comparison", "data": own(node)}
            for p in ("left", "right", "right2"):
                v = getattr(node, p)
                if v is not None:
                    operand(v, nid, p)
        elif isinstance(node, BooleanNode):
            nodes[nid] = {"id": nid, "type": "boolean", "data": own(node)}
            for c in node.children:
                visit(c, nid, "in")
        elif isinstance(node, TemporalNode):
            nodes[nid] = {"id": nid, "type": "temporal", "data": own(node)}
            visit(node.child, nid, "child")
        else:
            nodes[nid] = {"id": nid, "type": "arithmetic", "data": own(node)}
            for o in node.operands:
                operand(o, nid, "in")

    for a in ir.actions:
        nodes[a.node_id] = {
            "id": a.node_id,
            "type": "action",
            "data": a.model_dump(mode="python", exclude={"node_id"}),
        }
        topo.append(a.node_id)
        visit(ir.conditions, a.node_id, "when")
    model = ir.model_dump(mode="python", exclude={"conditions", "actions", "graph_layout"})
    model["editor"] = "graph"
    action_ids = [a.node_id for a in ir.actions]  # actions first, in IR order (order is semantic)
    model["nodes"] = [nodes[i] for i in action_ids] + [
        nodes[i] for i in sorted(nodes) if i not in set(action_ids)
    ]
    model["edges"] = edges
    model["graph_layout"] = ir.graph_layout or _layout(list(nodes), parents, topo)
    return model
