"""E37-D01 node-graph audit: every number the research memo quotes, from the repo.

Standalone, offline, stdlib only; nothing here is user evidence. It reads the plan documents, the
shipped rule-engine code and the shipped graph package as text, and - when the shipped package
``candleviewer.rules.ir`` imports from ``services/api`` - also runs ``form_incompatibility_reasons``
over the memo's corpus rows expressed as IR documents (otherwise the verdicts are marked
"assumed" from the detector's own reason strings and the output says so). It prints, with a
source label on every row: (1) the form-subset verdict, node, edge and depth count for every
corpus row of memo section 3; (2) the graph-only reason strings of ``rules/ir/form.py``; (3) the
stable ``RuleGraphError`` codes, the port types and the refused-pair sentences of
``packages/rule-graph``; (4) the node-type union of ``model.ts`` and of CMP-146; (5) the registered
``rules.*`` commands of the shipped keymap with their chords, and the chord conflicts with the plan
tables; (6) the whole-word count matrix for the vocabulary decision test; (7) the four indicator
words on SCR-081 and SCR-082 and the six names of state 2; (8) the node, stroke and chain count of
the SCR-082 ASCII wireframe; (9) the structure counts of the memo and the protocol. A row reads
NOT FOUND when an anchor moved; the tool never guesses a value and never calls the API.

``--json`` prints one object (the board script's NUM / TERMS and the check-nums consume it).
``--check <memo> [--protocol <file>]`` re-derives every ``<!-- audit:NAME=VALUE -->`` marker and
runs the cite check: for every ``file:line`` cite whose needle is registered in CITES the needle
is searched by content - at the cited line OK; at one other line WARN (drifted; exit 0); absent or
found more than once FAIL (exit 1). Every ``C-x.y`` cited must exist verbatim in CONSTITUTION.md.

Usage: python3 -I docs/design/_tools/e37_d01_node_graph_audit.py [--json]
       python3 -I docs/design/_tools/e37_d01_node_graph_audit.py --check MEMO [--protocol FILE]
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "docs/plan"
RULES = ROOT / "services/api/candleviewer/rules"
GRAPH_PKG = ROOT / "packages/rule-graph"
MEMO = ROOT / "docs/design/research/e37-node-graph-vs-list.md"
PROTOCOL = ROOT / "docs/design/research/e37-d01-session-protocol.md"

# Cite keys the memo uses (inside backticks, ``KEY``:LINE or ``KEY`` :LINE) -> the file they name.
FILES: dict[str, Path] = {
    "05": PLAN / "05-accessibility-standard.md",
    "10": PLAN / "10-personas.md",
    "11": PLAN / "11-user-stories.md",
    "12": PLAN / "12-sitemap.md",
    "13": PLAN / "13-user-flows.md",
    "14": PLAN / "14-screens-catalogue.md",
    "15": PLAN / "15-component-catalogue.md",
    "17": PLAN / "17-ux-diagrams.md",
    "18": PLAN / "18-traceability-matrix.md",
    "20": PLAN / "20-architecture.md",
    "22": PLAN / "22-api-openapi.yaml",
    "24": PLAN / "24-internal-schemas.md",
    "30": PLAN / "30-release-roadmap.md",
    "32": PLAN / "32-risk-register.md",
    "09": ROOT / "docs/research/09-execution-risk-tools.md",
    "24-OD": ROOT / "docs/research/24-owner-decisions.md",
    "CONSTITUTION.md": ROOT / "CONSTITUTION.md",
    "ADR-0007": PLAN / "27-adrs/ADR-0007-rule-ir.md",
    "ADR-0026": PLAN / "27-adrs/ADR-0026-rule-ir-canonicalisation.md",
    "ADR-0029": PLAN / "27-adrs/ADR-0029-rule-graph-library.md",
    "E09-D09": ROOT / "docs/design/E09/E09-D09.md",
    "E30-D02": ROOT / "docs/design/E30/E30-D02.md",
    "E36-D01": ROOT / "docs/design/research/e36-rules-in-words.md",
    "E36-D02": ROOT / "docs/design/E36/E36-D02.md",
    "E36-D03": ROOT / "docs/design/E36/E36-D03.md",
    "E36-D04": ROOT / "docs/design/E36/E36-D04.md",
    "E35-D01": ROOT / "docs/design/research/e35-rule-arming-trust.md",
    "form.py": RULES / "ir/form.py",
    "models.py": RULES / "ir/models.py",
    "graph.py": RULES / "compiler/graph.py",
    "catalogue.py": RULES / "vocabulary/catalogue.py",
    "model.ts": GRAPH_PKG / "src/model.ts",
    "ports.ts": GRAPH_PKG / "src/ports.ts",
    "errors.ts": GRAPH_PKG / "src/errors.ts",
    "toGraph.ts": GRAPH_PKG / "src/adapter/toGraph.ts",
    "keymap.json": ROOT / "apps/web/src/keymap/keymap.json",
}

# The registered needles: (key, line) -> a substring that identifies the line by content.
CITES: dict[tuple[str, int], str] = {
    ("14", 79): "### 0.5 Global invariants",
    ("14", 85): "RBAC denies server-side; the UI presents",
    ("14", 86): "equal-status non-canvas alternative",
    ("14", 1813): "**Action vocabulary surfaced:**",
    ("14", 1819): "byte-identical to the IR compiled from the stored graph representation",
    ("14", 1820): "Graph-only construct — read-only here",
    ("14", 1821): "Keep the form version (the graph layout will be regenerated)",
    ("14", 1822): "saving is permitted as a draft only, arming is blocked",
    ("14", 1824): "'identical'|'graph_only_construct'|'mismatch'|'unverified'",
    ("14", 1835): '+--- Rule: "ATR trail 2x"',
    ("14", 1836): '+--- Rule: "ATR trail 2x"',
    ("14", 1838): "| [Triggers]",
    ("14", 1839): "(on bar close)--+",
    ("14", 1841): "(atr 14)----(x 2.0)--+",
    ("14", 1843): "(swing_low 5)---------( max )---(modify_stop)",
    ("14", 1844): "| [Logic]",
    ("14", 1845): "(position_side == long)-+",
    ("14", 1847): "[ minimap ]  zoom 100%  [auto-layout]",
    ("14", 1854): "stored alongside the IR as presentation metadata",
    ("14", 1855): "`Ctrl+L` auto-layout; `Space+drag` pan",
    ("14", 1856): "remove the connection from X to Y",
    ("14", 1857): "mirrored for this direction",
    ("14", 1858): "every node in this graph maps to a form-editor construct",
    ("14", 1859): "What won't round-trip",
    ("14", 1860): "the same two explicit recovery choices as SCR-081",
    ("14", 1861): "draft-save only, arming blocked, stated in text",
    ("14", 1862): "the round-trip equivalence test (author in form",
    ("14", 1864): "ATR 14, output connects to Multiply input A",
    ("14", 1865): "warning banner above 120 nodes",
    ("14", 1866): "(**audited**). **Stories:** US-RULE-009",
    ("14", 1868): "auto-layout result reviewed on a 60-node graph",
    ("14", 1874): "which editor it opens in.",
    ("14", 1877): "'Opens in the form editor'",
    ("14", 1971): "the round-trip diff as a path table",
    ("14", 3058): "082 (node list)",
    ("10", 90): "Will happily learn a node-graph editor if it is faster than a form",
    ("10", 94): "Occasional wrist strain",
    ("10", 131): "keyboard-first operation",
    ("10", 243): "Node editors that become spaghetti",
    ("10", 250): "the hardest a11y surface in the product",
    ("10", 256): "in graph topological order",
    ("10", 257): "input 2 of 3, numeric, connected to ATR(14) output",
    ("10", 258): "`Enter` on a source port, arrow to a target port",
    ("10", 259): "`Delete` on a focused edge",
    ("10", 260): "`Ctrl+K` opens a searchable command palette",
    ("10", 261): "`Ctrl+arrows` pan",
    ("10", 262): "Semantics unchanged, announced, undoable",
    ("10", 264): "use the canvas only for inspection",
    ("10", 266): "The plain-language rule summary is the accessible description of the whole rule",
    ("10", 268): "(metric / comparison / logic / action / risk-control)",
    ("10", 270): "errors never mention IR, JSON paths or node ids",
    ("10", 273): "in the form editor; open it in the node editor; see the identical graph",
    ("11", 3633): "live in a separate `presentation` block",
    ("11", 3634): "Scenario: Presentation data survives the round trip (edge)",
    ("11", 3637): "my original layout rather than an auto-layout",
    ("11", 3697): '"A AND (B OR C)" using grouping controls',
    ("11", 3710): "so that complex logic is easier to see",
    ("11", 3713): "Scenario: Build by graph",
    ("11", 3716): "Scenario: Invalid connection",
    ("11", 3719): "Scenario: Layout aids",
    ("11", 3721): "arranged without changing semantics, and the change is undoable",
    ("11", 3727): "listed by node name in a jump-to-node error list",
    ("11", 3730): "tab to its output port, press Enter to start a connection",
    ("11", 3731): "connected CVD divergence output to AND input 1",
    ("11", 3732): "Scenario: Graph-only construct is marked at creation time (edge)",
    ("11", 3733): "fanning one node's output into two consumers",
    ("11", 3734): 'badged "node-only" immediately',
    ("11", 3752): "Scenario: Read-only fallback",
    ("11", 3754): "read-only for that portion with a clear explanation and an edit-in-node action",
    ("11", 3758): '"round-trip integrity failure"',
    ("11", 3766): '"edit as a new draft version"',
    ("11", 3769): "preserves the node-only sub-tree byte-for-byte",
    ("13", 305): "## 10. Rule creation (form + node editor, shared IR)",
    ("13", 312): "B{Start in form or graph?}",
    ("13", 316): "wire connections",
    ("13", 343): "## 11. Rule firing & native SL backstop",
    ("12", 78): "Same rule, alternate editor bound to shared IR",
    ("12", 287): "Which rule editor renders first",
    ("15", 224): "### CMP-019 Icon",
    ("15", 799): "### CMP-079 RbacGate",
    ("15", 1664): "`onConnect` · `readOnly?`",
    ("15", 1665): "the primary accessible-equivalent mechanism for the node-graph",
    ("15", 1672): 'type: "trigger" | "condition" | "action" | "logicGate" | "comment";',
    ("15", 1698): 'aria-label="Trigger node: on bar close, 5m"',
    ("15", 1705): "with input/output handles for logic-gate wiring",
    ("15", 1707): '"Connect output of condition node"',
    ("15", 1717): "PlaceOrder, ModifySl, Flatten",
    ("15", 1722): "vs. the form editor's implicit grouping",
    ("15", 1736): "### CMP-152 NodeGraphEdge",
    ("15", 1740): '"Delete connection"',
    ("15", 2725): 'anchor:{kind:"row"|"node"|"edge",id}',
    ("15", 2726): "the sole mechanism by which a keyboard user navigates graph diagnostics",
    ("15", 2736): "the switch is **allowed**",
    ("15", 2743): "(triggers, metrics, comparators, logic gates, actions, comments)",
    (
        "15",
        2745,
    ): "selecting a palette entry and pressing `Enter` inserts it connected to the current",
    ("15", 2750): "### CMP-237 NodePort",
    ("15", 2752): "(boolean, number, price, side, action)",
    ("15", 2753): '`kind: "in"|"out"`',
    ("15", 2754): '"Input, boolean, not connected"',
    ("15", 2763): "the equivalent keyboard navigation is the node list in CMP-153",
    ("24", 2926): "Owner decision #11: **both**",
    ("24", 2954): "authoring surface of record",
    ("24", 2955): "node positions; ignored by the engine",
    ("24", 2992): "class Comparison(BaseModel):",
    ("24", 3003): "class ArithmeticNode(BaseModel):",
    ("24", 3008): "class BooleanNode(BaseModel):",
    ("24", 3014): "class TemporalNode(BaseModel):",
    ("24", 3368): "**Form subset** (`form_compatible == true`)",
    ("24", 3370): "this rule uses graph-only features",
    ("24", 3374): "`MULTIPLE_SINKS` means the actions hang off more than one condition",
    ("22", 7083): "`editor` records which editor last authored it",
    ("22", 7200): "type: trigger.metric",
    ("22", 12844): "/rules/{ruleId}/compile:",
    ("22", 12849): "operationId: compileRule",
    ("22", 12869): "counterpart_model:",
    ("22", 12874): "the server never reconciles",
    ("22", 12887): "blocks_arming: { type: boolean }",
    ("22", 12888): "round_trip:",
    ("05", 74): "| **Rule builder (node graph)** | Add node",
    ("05", 75): "Connect focused ports",
    ("05", 76): "Delete focused node/edge",
    ("05", 85): "`Ctrl+K` (command palette, the recovery mechanism",
    ("05", 88): "Tracking note — rule-builder node-graph keyboard spec",
    ("05", 131): "**Text resize (WCAG 1.4.4, AA)**",
    ("05", 165): "Satisfies WCAG 1.3.1 for the heuristic-data caveat",
    ("17", 446): "Toggle Demo/Live switch flow",
    ("17", 448): "including chart/DOM/graph-editor canvases",
    ("30", 443): "auto-layout; node search; validation with error surfacing",
    ("30", 1018): "Node-editor auto-layout and node search",
    ("32", 465): "### RSK-034",
    ("32", 537): "### RSK-040",
    ("32", 1058): "| R5 Credential & key security",
    ("20", 1289): "modify_stop_loss(price=close-2*atr, only_tighten=true)",
    ("09", 62): 'drag-and-drop "block" strategy editor',
    ("09", 165): "close - 3 * atr(14)",
    ("24-OD", 18): "Both form/condition-list editor AND visual node-graph editor in v1",
    ("CONSTITUTION.md", 128): "**C-2.6 Native exchange stop-loss invariant.**",
    ("CONSTITUTION.md", 443): "**C-4.14** Flags may never gate a safety invariant",
    ("ADR-0007", 49): "semantically lossless** and cosmetically best-effort",
    ("ADR-0007", 50): "not a dataflow engine; cycles and multiple sinks are compile errors",
    ("ADR-0007", 66): "arbitrary dataflow constructs users may expect from tools like Kryll",
    ("ADR-0026", 54): "**Mismatch telemetry**",
    ("ADR-0029", 13): "Use **@xyflow/react (React Flow) 12.x, pinned exactly**",
    ("ADR-0029", 14): "connect is a keyboard state machine in our code",
    ("ADR-0029", 15): "**Provisional soft cap of 120 nodes**",
    ("ADR-0029", 18): "**Auto-layout runs in a web worker**",
    ("E09-D09", 32): "### 2.1 The decision rule",
    ("E09-D09", 46): "### 2.2 The four treatments",
    ("E09-D09", 83): "### 3.1 The keys",
    ("E09-D09", 95): "| `rbac.view_as`",
    ("E09-D09", 224): "### 9.1 `aria-disabled` versus `disabled`",
    ("E09-D09", 238): "### 9.3 Keys on a T2 control",
    (
        "E30-D02",
        128,
    ): "disabled = `opacity.disabled` on the control with the reason as full-opacity text",
    ("E36-D02", 114): 'Read-only while viewing as {user}."** ({user} is the view-as target',
    ("E36-D02", 122): '"This rule is fully editable in both the form and the graph editor."',
    ("E36-D02", 123): 'Open in the graph editor to change this." — the lead-in',
    ("E36-D02", 124): '| 3 `mismatch` — **"Round-trip mismatch"**',
    ("E36-D02", 125): '| 4 `unverified` — **"Not verified"**',
    ("E36-D02", 126): "**Checking…** (`checking: true`)",
    ("E36-D02", 129): "The indicator is mirrored on SCR-082",
    ("E36-D02", 263): "**Indicator words:**",
    ("E36-D02", 272): "**Form validity is not a T2 reason**",
    ("E36-D03", 89): "`form` is the default, memo Q7 RULED",
    ("E36-D03", 194): '"The node editor is off for this workspace." (PROPOSED)',
    ("E36-D04", 43): "the **mandated non-canvas alternative** to SCR-082",
    ("E36-D04", 107): "tested against the **inventory**, not the sentence",
    ("E36-D04", 116): "the node-list panel (`Alt+L`) is theirs",
    ("E36-D04", 334): "| K-08 |",
    ("E36-D04", 335): "| K-09 |",
    ("E36-D01", 62): "## 2. The rules-in-words corpus",
    ("E36-D01", 69): '"trail two ATRs but never loosen"',
    ("E36-D01", 71): '"ATR trailing stop (ratchet)"',
    ("E36-D01", 87): "fifteen of eighteen",
    ("E36-D01", 136): "### 5.1 R1",
    ("E36-D01", 140): "### 5.2 R2",
    ("E36-D01", 144): "### 5.3 R3",
    ("E36-D01", 158): "### 5.5 R5",
    ("E35-D01", 317): "## 7. Terminology check",
    ("E35-D01", 321): "the graph node (E37-D01)",
    ("form.py", 23): "arithmetic operand in",
    ("form.py", 31): "temporal op '{node.op}' is graph-only",
    ("form.py", 35): "temporal node must directly wrap a comparison",
    ("form.py", 37): "nested deeper than two levels",
    ("form.py", 42): "boolean op '{node.op}' is graph-only",
    ("form.py", 46): 'depth == 0 and node.op == "all_of" and child.op == "any_of"',
    ("form.py", 49): "boolean nested inside root any_of",
    ("form.py", 87): "node fans out to {n} consumers",
    ("form.py", 91): "def form_compatible",
    ("models.py", 329): 'editor: Literal["form", "graph"] = "form"',
    ("graph.py", 6): "comparison|boolean|temporal|arithmetic|action",
    ("graph.py", 8): "left|right|right2|in|child|when",
    ("graph.py", 10): "exactly one ``when`` edge from the single root condition",
    ("graph.py", 12): "Well-formedness (cycles, multiple sinks, orphans, dangling ports)",
    ("graph.py", 14): "form-subset detector flags as graph-only",
    ("catalogue.py", 63): "RETIRED_ACTIONS = frozenset",
    ("catalogue.py", 97): "TRIGGERS: dict[str, tuple[str, tuple[str, ...]]] = {",
    ("model.ts", 3): "export type GraphNodeType",
    ("model.ts", 14): "export interface GraphEdge",
    ("model.ts", 34): "readonly collapsed: readonly string[];",
    ("ports.ts", 10): '["boolean", "number", "price", "side", "action", "trigger"]',
    ("ports.ts", 20): "80 characters (the OQ9 ruling; §3.1 says 60)",
    ("ports.ts", 23): "export const PORT_COMPAT = frozen({",
    ("ports.ts", 37): 'action: "A number can\'t run an action.",',
    ("ports.ts", 65): "A trigger can't be used as true or false.",
    ("ports.ts", 69): "A trigger can't run an action without a condition.",
    ("errors.ts", 6): "`CYCLE_DETECTED`: the graph holds a cycle",
    ("errors.ts", 9): "`NOT_FORM_REPRESENTABLE`: the rule uses a graph-only construct",
    ("toGraph.ts", 50): '{ id: "trigger", type: "trigger"',
    ("keymap.json", 599): '"id": "rules.graph_mode"',
    ("keymap.json", 663): '"id": "rules.group"',
    ("keymap.json", 672): '"id": "rules.auto_layout"',
    ("keymap.json", 721): '"id": "rules.rename"',
}

# ------------------------------------------------------------------ the corpus (memo section 3) --
# A condition tree: ("cmp", metric, op, const | None) or (boolean_op, [children]).
Tree = tuple[Any, ...]


def cmp(metric: str, op: str, const: float | str | None = None) -> Tree:
    return ("cmp", metric, op, const)


CORPUS: list[dict[str, Any]] = [
    {
        "row": 1,
        "label": "move my stop to break-even once I'm up 1R",
        "trigger": {"type": "on_position_update"},
        "tree": cmp("unrealised_r_multiple", "gte", 1.0),
        "actions": [("move_to_breakeven", {"offset_ticks": 2})],
        "rules": 1,
    },
    {
        "row": 2,
        "label": "trail two ATRs but never loosen",
        "trigger": {"type": "on_bar_close", "timeframe": "1m"},
        "tree": cmp("position_open", "is_true"),
        "actions": [("modify_stop_loss", {"mode": "atr", "value": 2.0, "only_tighten": True})],
        "rules": 1,
    },
    {"row": 3, "label": "SCR-083 T1", "same_as": 1},
    {"row": 4, "label": "SCR-083 T2", "same_as": 2},
    {
        "row": 5,
        "label": "SCR-083 T3 structure (swing) trailing stop",
        "trigger": {"type": "on_bar_close", "timeframe": "5m"},
        "tree": cmp("position_side", "eq", "long"),
        "actions": [("tighten_stop", {"mode": "structure", "value": 10})],
        "rules": 1,
    },
    {
        "row": 6,
        "label": "SCR-083 T4 partial TP ladder at 1R/2R/3R",
        "trigger": {"type": "on_position_update"},
        "tree": cmp("unrealised_r_multiple", "gte", 1.0),
        "actions": [("scale_out", {"qty_pct": 33, "order_type": "market"})],
        "rules": 3,
    },
    {
        "row": 7,
        "label": "SCR-083 T5 time stop (close after N minutes)",
        "trigger": {"type": "on_timer", "interval_ms": 60000},
        "tree": (
            "all_of",
            [cmp("time_in_trade_ms", "gt", 1800000), cmp("unrealised_r_multiple", "lt", 0.2)],
        ),
        "actions": [("flatten_position", {}), ("log_journal_tag", {"tag": "time-stop"})],
        "rules": 1,
    },
    {
        "row": 8,
        "label": "SCR-083 T6 cancel working orders when spread > N bps",
        "trigger": {"type": "on_book_update"},
        "tree": cmp("spread_bps", "gt", 8),
        "actions": [("cancel_all_orders", {"purpose": "entry"})],
        "rules": 1,
    },
    {
        "row": 9,
        "label": "SCR-083 T7 daily loss lockout",
        "trigger": {"type": "on_position_close"},
        "tree": cmp("daily_loss_pct", "gte", 2),
        "actions": [
            ("halt_new_orders", {"scope": "account", "until": "next_utc_day"}),
            ("send_notification", {"channel": "push", "severity": "high"}),
        ],
        "rules": 1,
    },
    {
        "row": 10,
        "label": "SCR-083 T8 halt on tape-speed spike",
        "trigger": {"type": "on_price_update", "debounce_ms": 1000},
        "tree": cmp("tape_speed_zscore", "gt", 3),
        "actions": [("halt_new_orders", {"scope": "account", "until": "duration_ms"})],
        "rules": 1,
    },
    {
        "row": 11,
        "label": "SCR-083 T9 avoid stops inside a detected liquidity cluster",
        "trigger": {"type": "on_bar_close", "timeframe": "1m"},
        "tree": (
            "all_of",
            [cmp("distance_to_liquidity_cluster", "lte", 5), cmp("position_side", "eq", "long")],
        ),
        "actions": [
            ("tighten_stop", {"mode": "offset_from_price", "value": 10, "only_tighten": True})
        ],
        "rules": 1,
    },
    {
        "row": 12,
        "label": "SCR-083 T10 reduce leverage when funding exceeds a threshold",
        "trigger": {"type": "on_metric_change", "metric": "funding_rate"},
        "tree": cmp("funding_rate", "gt", 0.05),
        "actions": [("reduce_leverage", {"target": 5})],
        "rules": 1,
    },
    {
        "row": 13,
        "label": "SCR-083 T11 flatten before funding settlement",
        "trigger": {"type": "on_timer", "interval_ms": 60000},
        "tree": (
            "all_of",
            [cmp("time_to_funding_ms", "lte", 300000), cmp("position_open", "is_true")],
        ),
        "actions": [("flatten_position", {})],
        "rules": 1,
    },
    {
        "row": 14,
        "label": "SCR-083 T12 re-arm chase when the book thins",
        "trigger": {"type": "on_book_update"},
        "tree": ("any_of", [cmp("book_pressure", "lt", -0.5), cmp("liquidity_pulled", "is_true")]),
        "actions": [("arm_chase_limit", {})],
        "rules": 1,
    },
    {
        "row": 15,
        "label": "10 section 6 scenario 1: BE at 1R, then trail 1.5xATR(14)",
        "trigger": {"type": "on_bar_close", "timeframe": "1m"},
        "tree": cmp("unrealised_r_multiple", "gte", 1.0),
        "actions": [("modify_stop_loss", {"mode": "atr", "value": 1.5})],
        "rules": 2,
    },
    {"row": 16, "label": "a firing, not a rule", "na": "not a rule"},
    {"row": 17, "label": "trail 10 ticks under the 20 EMA", "na": "not expressible"},
    {"row": 18, "label": "Bybit's native trailing stop", "na": "not expressible"},
]

WORDS = (
    "node", "port", "edge", "connection", "handle", "wire",
    "block", "socket", "link", "step", "input",
)  # fmt: skip
WORD_GROUPS: dict[str, list[Path]] = {
    "docs/plan": sorted(PLAN.glob("*.md")),
    "packages/rule-graph/src": sorted(p for p in GRAPH_PKG.glob("src/**/*.ts") if p.is_file()),
    "services/api/candleviewer/rules": sorted(RULES.glob("**/*.py")),
}
STATE2_NAMES: list[tuple[str, int, str]] = [
    ("14", 1859, "Unsupported in form view"),
    ("14", 1820, "Graph-only construct — read-only here"),
    ("11", 3734, "node-only"),
    ("24", 3370, "graph-only features"),
    ("14", 1824, "graph_only_construct"),
    ("14", 1856, "editable here in read-only summary form"),
]
INDICATOR_WORDS = ["Round-trips ✓", "", "Round-trip mismatch", "Not verified"]


# ------------------------------------------------------------------ helpers -----------------------
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def lines_of(path: Path) -> list[str]:
    return read(path).split("\n")


def line(path: Path, n: int) -> str:
    rows = lines_of(path)
    return rows[n - 1] if 0 < n <= len(rows) else ""


def tree_stats(tree: Tree) -> tuple[int, int, int]:
    """(condition nodes, edges inside the condition tree, depth) of a tree spec."""
    if tree[0] == "cmp":
        return 1, 0, 1
    nodes, edges, depth = 1, 0, 0
    for child in tree[1]:
        n, e, d = tree_stats(child)
        nodes, edges, depth = nodes + n, edges + e + 1, max(depth, d)
    return nodes, edges, depth + 1


def tree_ir(tree: Tree, seq: list[int]) -> dict[str, Any]:
    seq[0] += 1
    nid = f"c{seq[0]}"
    if tree[0] == "cmp":
        _, metric, op, const = tree
        out: dict[str, Any] = {"node_id": nid, "op": op, "left": {"metric": metric}}
        if const is not None:
            out["right"] = {"const": const}
        return out
    return {"node_id": nid, "op": tree[0], "children": [tree_ir(c, seq) for c in tree[1]]}


def rule_ir(row: dict[str, Any]) -> dict[str, Any]:
    seq = [0]
    return {
        "rule_id": f"00000000-0000-0000-0000-00000000{row['row']:04d}",
        "version": 1,
        "name": f"E37-D01 corpus row {row['row']}",
        "enabled": True,
        "mode": "simulate",
        "scope": {"level": "symbol", "symbols": ["BTCUSDT"], "applies_to": "open_positions"},
        "trigger": row["trigger"],
        "conditions": tree_ir(row["tree"], seq),
        "actions": [
            {"node_id": f"a{i + 1}", "type": t, "params": p}
            for i, (t, p) in enumerate(row["actions"])
        ],
    }


def shipped_detector() -> tuple[Any, Any, str]:
    """(Rule, form_incompatibility_reasons, source) when the shipped package imports."""
    api = ROOT / "services/api"
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    try:
        models = importlib.import_module("candleviewer.rules.ir.models")
        form = importlib.import_module("candleviewer.rules.ir.form")
    except ImportError as exc:  # pydantic or the package absent: "assumed", and the output says so
        return None, None, f"assumed (candleviewer.rules.ir not importable: {type(exc).__name__})"
    return models.Rule, form.form_incompatibility_reasons, "form_incompatibility_reasons run"


def corpus() -> dict[str, Any]:
    rule_cls, detector, source = shipped_detector()
    rows: list[dict[str, Any]] = []
    for row in CORPUS:
        base = next((r for r in CORPUS if r["row"] == row.get("same_as")), row)
        if "na" in row:
            rows.append({"row": row["row"], "label": row["label"], "verdict": row["na"]})
            continue
        cn, ce, depth = tree_stats(base["tree"])
        nodes, edges = 1 + cn + len(base["actions"]), ce + len(base["actions"])
        verdict, reasons = "form (assumed)", ["assumed"]
        if detector is not None:
            reasons = list(detector(rule_cls.model_validate(rule_ir(base))))
            verdict = "form" if not reasons else "graph-only"
        rows.append(
            {
                "row": row["row"],
                "label": row["label"],
                "nodes": nodes,
                "edges": edges,
                "depth": depth,
                "rules": base["rules"],
                "verdict": verdict,
                "reasons": reasons,
            }
        )
    expressible = [r for r in rows if "nodes" in r]
    return {
        "source": source,
        "rows": len(rows),
        "expressible": len(expressible),
        "graph_only": sum(r["verdict"].startswith("graph-only") for r in expressible),
        "any_of": sum(
            1 for r in CORPUS if "tree" in r and r["tree"][0] == "any_of" and "same_as" not in r
        ),
        "multi_rule": sum(1 for r in expressible if r["rules"] > 1),
        "max_nodes": max(r["nodes"] for r in expressible),
        "max_depth": max(r["depth"] for r in expressible),
        "per_row": rows,
    }


def form_reasons() -> list[str]:
    text = read(FILES["form.py"])
    return re.findall(r'out\.append\(f"[^"]*?: ([^"]+)"\)', text)


def wireframe() -> dict[str, Any]:
    """Nodes, strokes and the longest chain of the SCR-082 ASCII picture (`14` SCR-082)."""
    text = read(FILES["14"])
    start = text.find('+--- Rule: "ATR trail 2x"')
    if start < 0:
        return {"nodes": "NOT FOUND"}
    block = text[start : text.find("```", start)]
    rows = block.split("\n")
    tokens: list[tuple[int, int, int, str]] = []  # (row, start, end, label)
    for r, row in enumerate(rows):
        for m in re.finditer(r"\(([^()]*)\)", row):
            tokens.append((r, m.start(), m.end(), m.group(1).strip()))
    same_line: list[tuple[str, str]] = []
    feeders: list[str] = []
    sinks: list[str] = []
    for r, row in enumerate(rows):
        here = [t for t in tokens if t[0] == r]
        for a, b in pairwise(here):
            if re.fullmatch(r"-+", row[a[2] : b[1]]):
                same_line.append((a[3], b[3]))
        if here:
            last = here[-1]
            tail = row[last[2] :]
            if re.match(r"-*\+", tail):
                feeders.append(last[3])
            elif not tail.strip().startswith("-"):
                sinks.append(last[3])
    # the convergence node: the one with a long dash run arriving on its own line
    conv = next((b for a, b in same_line if "max" in b), None)
    edges = same_line + [(f, conv) for f in feeders if conv]
    nodes = [t[3] for t in tokens]

    def longest(node: str, seen: frozenset[str]) -> int:
        nxt = [b for a, b in edges if a == node and b not in seen]
        return 1 + max((longest(b, seen | {b}) for b in nxt), default=0)

    return {
        "nodes": len(nodes),
        "labels": nodes,
        "sinks": sinks,
        "strokes": len(edges),
        "chain": max(longest(n, frozenset({n})) for n in nodes),
        "into_max": sum(1 for _, b in edges if b == conv),
        "palette_groups": len(re.findall(r"\[[A-Z][a-z]+\]", block)),
    }


def rule_graph() -> dict[str, Any]:
    errors = read(FILES["errors.ts"])
    ports = read(FILES["ports.ts"])
    model = read(FILES["model.ts"])
    codes = re.findall(r'^\s+"([A-Z_]+)",$', errors, re.MULTILINE)
    types_m = re.search(r"const TYPES = \[([^\]]+)\]", ports)
    port_types = re.findall(r'"([a-z]+)"', types_m.group(1)) if types_m else []
    compat_m = re.search(r"PORT_COMPAT = frozen\(\{(.*?)\n\} as const", ports, re.DOTALL)
    refused = (
        re.findall(r'^\s+[a-z]+: "([^"]+)",$', compat_m.group(1), re.MULTILINE) if compat_m else []
    )
    allowed = (
        len(re.findall(r"^\s+[a-z]+: true,$", compat_m.group(1), re.MULTILINE)) if compat_m else 0
    )
    union_m = re.search(r"export type GraphNodeType = ([^;]+);", model)
    node_types = re.findall(r'"([A-Za-z]+)"', union_m.group(1)) if union_m else []
    number_to_action = next((s for s in refused if s.startswith("A number can't run")), "NOT FOUND")
    trigger_to_action = next(
        (s for s in refused if s.startswith("A trigger can't run")), "NOT FOUND"
    )
    trigger_accepted = (
        any(
            re.search(rf"^\s+{t}: \{{[^}}]*?\n\s+trigger: true", compat_m.group(1), re.MULTILINE)
            for t in port_types
        )
        if compat_m
        else False
    )
    return {
        "error_codes": codes,
        "port_types": port_types,
        "node_types": node_types,
        "refused_pairs": len(refused),
        "allowed_pairs": allowed,
        "number_to_action": number_to_action,
        "trigger_to_action": trigger_to_action,
        "any_input_accepts_trigger": trigger_accepted,
        "trigger_node_emitted": '{ id: "trigger", type: "trigger"' in read(FILES["toGraph.ts"]),
    }


def components() -> dict[str, Any]:
    cat = read(FILES["15"])
    m146 = re.search(r'type: ("[a-zA-Z]+"(?: \| "[a-zA-Z]+")+);', cat)
    m237 = re.search(r"type compatibility \(([a-z, ]+)\) at connect time", cat)
    return {
        "cmp146_types": re.findall(r'"([A-Za-z]+)"', m146.group(1)) if m146 else "NOT FOUND",
        "cmp237_types": [t.strip() for t in m237.group(1).split(",")] if m237 else "NOT FOUND",
        "cmp148_handle": sum(1 for ln in lines_of(FILES["15"])[1703:1711] if "handle" in ln),
    }


def keymap() -> dict[str, Any]:
    text = read(FILES["keymap.json"])
    data = json.loads(text) if text else {"commands": []}
    rules = [c for c in data.get("commands", []) if str(c.get("id", "")).startswith("rules.")]
    return {
        "rules_commands": len(rules),
        "commands": {c["id"]: [c.get("label"), c.get("defaultBinding")] for c in rules},
        "ctrl_shift_l_bound": text.count('"Ctrl+Shift+L"'),
        "ctrl_l_command": next(
            (c["id"] for c in rules if c.get("defaultBinding") == "Ctrl+L"), "NOT FOUND"
        ),
        "alt_l_bound": text.count('"Alt+L"'),
    }


def plan_chords() -> dict[str, Any]:
    p10 = lines_of(FILES["10"])
    p05 = lines_of(FILES["05"])
    p14 = line(FILES["14"], 1855)
    p17 = line(FILES["17"], 446)
    return {
        "p10_rows": sum(1 for ln in p10[255:262] if ln.startswith("| ")),
        "p10_ctrl_shift_l": sum("Ctrl+Shift+L" in ln for ln in p10[255:262]),
        "p05_rows": sum(1 for ln in p05[73:76] if "|" in ln),
        "p14_items": len([x for x in p14.split(";") if x.strip()]) if p14 else "NOT FOUND",
        "p17_ctrl_shift_l_global": "Ctrl+Shift+L" in p17 and "Demo/Live" in p17,
    }


def indicators() -> dict[str, Any]:
    cat = lines_of(FILES["14"])

    def word(n: int) -> str:
        m = re.search(r"\*\*`([^`]+)`\*\*", cat[n - 1]) if n <= len(cat) else None
        return m.group(1) if m else "NOT FOUND"

    scr081 = [word(n) for n in (1819, 1820, 1821, 1822)]
    scr082 = [word(n) for n in (1858, 1859, 1860, 1861)]
    names = []
    for key, n, needle in STATE2_NAMES:
        names.append({"name": needle, "at": f"{key}:{n}", "found": needle in line(FILES[key], n)})
    return {
        "scr081": scr081,
        "scr082": scr082,
        "differing": sum(a != b for a, b in zip(scr081, scr082, strict=True)),
        "state2_names": len(names),
        "state2_all_found": all(x["found"] for x in names),
        "names": names,
    }


def words() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for group, paths in WORD_GROUPS.items():
        counter: Counter[str] = Counter()
        for p in paths:
            text = read(p).lower()
            for w in WORDS:
                counter[w] += len(re.findall(rf"\b{w}s?\b", text))
        out[group] = dict(counter)
    return out


def teardown_rows(memo: str) -> int:
    sec = section(memo, "## 4. Competitive teardown", "## 5. ")
    return sum(1 for ln in sec.split("\n") if ln.startswith("| **"))


# ------------------------------------------------------------------ memo structure ----------------
def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def ids(prefix: str, body: str) -> list[int]:
    return sorted({int(x) for x in re.findall(rf"^\| {prefix}-?(\d+) +\|", body, re.MULTILINE)})


def structure(memo: str, protocol: str) -> dict[str, Any]:
    f_rows = re.findall(r"^\| F(\d+) +\|.*?\| (S[1-4]) +\|", memo, re.MULTILINE)
    sev = Counter(s for _, s in f_rows)
    ac = section(memo, "## Acceptance-criteria trace", "## 0. ")
    minutes = re.search(r"= \*\*(\d+) min\*\*", protocol)
    return {
        "rq": ids("RQ", section(memo, "## 2. Research questions", "## 3. ")),
        "h": len(re.findall(r"\| H(\d+): ", section(memo, "## 2. Research questions", "## 3. "))),
        "sc": ids("SC", section(memo, "## 1. Source conflicts", "## 2. ")),
        "f": sorted({int(a) for a, _ in f_rows}),
        "f_sev": {k: sev.get(k, 0) for k in ("S4", "S3", "S2", "S1")},
        "r": sorted({int(x) for x in re.findall(r"^### 7\.\d R(\d) ", memo, re.MULTILINE)}),
        "p": ids("P", section(memo, "## 8. Node-editor principles", "## 9. ")),
        "c": ids("C", section(memo, "### 9.1", "### 9.2")),
        "g": ids("G", section(memo, "### 9.2", "### 9.3")),
        "q": ids("Q", section(memo, "### 9.3", "### 9.4")),
        "a": ids("A", section(memo, "### 9.4", "## 10. ")),
        "boards": len(re.findall(r"^\| (\d\d) +\| `E37-D01 / ", memo, re.MULTILINE)),
        "ac_rows": sum(1 for ln in ac.split("\n") if ln.startswith(("| AC", "| DoD"))),
        "teardown_vendors": teardown_rows(memo),
        "protocol_sections": len(re.findall(r"^## \d\. ", protocol, re.MULTILINE)),
        "protocol_minutes": (minutes.group(1) if minutes else "NOT FOUND"),
        "limitation_statement": "Nothing here is observed" in memo,
    }


def derived(memo: str, protocol: str) -> dict[str, Any]:
    c = corpus()
    w = wireframe()
    rg = rule_graph()
    st = structure(memo, protocol)
    ind = indicators()
    return {
        "corpus": c,
        "wireframe": w,
        "form": {"reasons": form_reasons()},
        "rule_graph": rg,
        "components": components(),
        "keymap": keymap(),
        "plan_chords": plan_chords(),
        "indicators": ind,
        "words": words(),
        "structure": st,
        "markers": {
            "form.reasons": len(form_reasons()),
            "keymap.rules_commands": keymap()["rules_commands"],
            "boards": st["boards"],
            "sc": len(st["sc"]),
            "rq": len(st["rq"]),
            "h": st["h"],
            "corpus.rows": c["rows"],
            "corpus.expressible": c["expressible"],
            "corpus.graph_only": c["graph_only"],
            "corpus.any_of": c["any_of"],
            "corpus.max_nodes": c["max_nodes"],
            "wire.nodes": w["nodes"],
            "wire.strokes": w.get("strokes"),
            "wire.chain": w.get("chain"),
            "wire.into_max": w.get("into_max"),
            "teardown.vendors": st["teardown_vendors"],
            "ports.types": len(rg["port_types"]),
            "ports.refused": rg["refused_pairs"],
            "f": len(st["f"]),
            "f.s4": st["f_sev"]["S4"],
            "f.s3": st["f_sev"]["S3"],
            "f.s2": st["f_sev"]["S2"],
            "f.s1": st["f_sev"]["S1"],
            "r": len(st["r"]),
            "p": len(st["p"]),
            "c": len(st["c"]),
            "g": len(st["g"]),
            "q": len(st["q"]),
            "a": len(st["a"]),
        },
    }


# ------------------------------------------------------------------ --check -----------------------
MARKER = re.compile(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->")
KEY_TOKEN = re.compile(
    r"`([^`\s]+)`(?=\s?:\d)|\b(E\d\d-D\d\d|ADR-\d{4}|CONSTITUTION\.md)\b|`(ADR-\d{4}|E\d\d-D\d\d)`"
)
LINE_TOKEN = re.compile(r"(?<![\w:]):(\d{1,5})\b")


def cites_in(text: str) -> list[tuple[str, int, int]]:
    """Every (key, line, memo line number) cite: a backticked or plain key, then :N tokens."""
    out: list[tuple[str, int, int]] = []
    for no, row in enumerate(text.split("\n"), start=1):
        if row.startswith("<!--") or "`` " in row:
            continue
        events: list[tuple[int, str, str]] = []
        for m in KEY_TOKEN.finditer(row):
            events.append((m.start(), "key", m.group(1) or m.group(2) or m.group(3)))
        for m in LINE_TOKEN.finditer(row):
            events.append((m.start(), "line", m.group(1)))
        key = None
        for _, kind, value in sorted(events):
            if kind == "key":
                key = value if value in FILES else None
            elif key is not None:
                out.append((key, int(value), no))
    return out


def check_cites(text: str) -> tuple[list[str], list[str], int, int]:
    fails: list[str] = []
    warns: list[str] = []
    checked = unregistered = 0
    for key, n, at in cites_in(text):
        needle = CITES.get((key, n))
        if needle is None:
            unregistered += 1
            continue
        checked += 1
        hits = [i for i, row in enumerate(lines_of(FILES[key]), start=1) if needle in row]
        if hits == [n]:
            continue
        if len(hits) == 1:
            warns.append(f"WARN cited line drifted: `{key}`:{n} (memo line {at}) now at :{hits[0]}")
        elif not hits:
            fails.append(f"FAIL needle not found: `{key}`:{n} (memo line {at}) {needle!r}")
        else:
            fails.append(f"FAIL ambiguous needle: `{key}`:{n} (memo line {at}) found at {hits}")
    return fails, warns, checked, unregistered


def check_rules(text: str) -> list[str]:
    const = read(FILES["CONSTITUTION.md"])
    return [
        f"FAIL rule id not in CONSTITUTION.md: {rid}"
        for rid in sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
        if f"**{rid}" not in const and f"{rid} " not in const
    ]


def check_markers(text: str, markers: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in MARKER.finditer(text):
        name, value = m.group(1), m.group(2)
        seen.add(name)
        if name not in markers:
            out.append(f"FAIL unknown marker audit:{name}")
        elif str(markers[name]) != value:
            out.append(f"FAIL marker audit:{name}={value} but derived {markers[name]}")
    for name in sorted(set(markers) - seen):
        out.append(f"FAIL marker audit:{name} missing from the memo (derived {markers[name]})")
    return out


def check(memo_path: Path, protocol_path: Path) -> int:
    memo, protocol = read(memo_path), read(protocol_path)
    d = derived(memo, protocol)
    problems = check_markers(memo, d["markers"]) + check_rules(memo + protocol)
    fails, warns, checked, unregistered = check_cites(memo + "\n" + protocol)
    problems += fails
    for w in warns:
        print(w)
    for p in problems:
        print(p)
    verdict = "FAIL" if problems else "OK"
    print(
        f"{verdict}: {len(MARKER.findall(memo))} markers, {checked} registered cites checked "
        f"({unregistered} unregistered), {len(warns)} drift warning(s), "
        f"{len(problems)} problem(s); corpus {d['corpus']['source']}"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ report ------------------------
def report(d: dict[str, Any]) -> str:
    c, w, rg, km, ind, st = (
        d["corpus"],
        d["wireframe"],
        d["rule_graph"],
        d["keymap"],
        d["indicators"],
        d["structure"],
    )
    out = ["# E37-D01 node-graph audit", ""]
    out.append(
        f"- Corpus ({c['source']}): {c['rows']} rows, {c['expressible']} expressible, "
        f"{c['graph_only']} graph-only, {c['any_of']} with any_of, max {c['max_nodes']} nodes, "
        f"max depth {c['max_depth']}."
    )
    out.append("")
    out.append("| row | nodes | edges | depth | rules | verdict |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    for r in c["per_row"]:
        out.append(
            f"| {r['row']} | {r.get('nodes', '-')} | {r.get('edges', '-')} | {r.get('depth', '-')} "
            f"| {r.get('rules', '-')} | {r['verdict']} |"
        )
    out.append("")
    out.append(f"- Wireframe (`14` SCR-082): {w}")
    out.append(f"- form.py reason strings ({len(d['form']['reasons'])}): {d['form']['reasons']}")
    out.append(
        f"- rule-graph: codes {rg['error_codes']}; port types {rg['port_types']}; "
        f"node types {rg['node_types']}; refused pairs {rg['refused_pairs']}, allowed "
        f"{rg['allowed_pairs']}; number->action {rg['number_to_action']!r}; trigger->action "
        f"{rg['trigger_to_action']!r}; any input accepts trigger: {rg['any_input_accepts_trigger']}"
    )
    out.append(f"- components: {d['components']}")
    out.append(
        f"- keymap: {km['rules_commands']} rules.* commands; Ctrl+Shift+L bound "
        f"{km['ctrl_shift_l_bound']}x; Ctrl+L -> {km['ctrl_l_command']}; "
        f"Alt+L bound {km['alt_l_bound']}x"
    )
    out.append(f"- plan chords: {d['plan_chords']}")
    out.append(
        f"- indicators: SCR-081 {ind['scr081']}; SCR-082 {ind['scr082']}; differing "
        f"{ind['differing']}; state-2 names {ind['state2_names']} "
        f"(all found: {ind['state2_all_found']})"
    )
    out.append("- word matrix (whole word, plural tolerated):")
    for group, counts in d["words"].items():
        out.append(f"  - {group}: {counts}")
    out.append(f"- memo structure: {st}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if "--check" in argv:
        memo_path = Path(argv[argv.index("--check") + 1])
        protocol_path = (
            Path(argv[argv.index("--protocol") + 1]) if "--protocol" in argv else PROTOCOL
        )
        return check(memo_path, protocol_path)
    d = derived(read(MEMO), read(PROTOCOL))
    if "--json" in argv:
        print(json.dumps(d, indent=2, ensure_ascii=False, default=str))
    else:
        print(report(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
