"""E37-D02 node-editor audit: every number the SCR-082 hi-fi spec quotes, from the repo.

Standalone, offline, stdlib only; it executes no repo code, calls no API and contacts no host.
It reads the token JSON, ``pairs.mjs``, the shipped rule-graph package, ``rules/ir/form.py``,
the keymap, the plan documents and the merged sibling specs AS TEXT and prints, with a source
label on every row: (1) the WCAG 2.x ratio of every fg / bg pair SCR-082 renders in dark / light /
high-contrast (``themes.json`` layering) against the role's bar, comparing the UNROUNDED ratio as
``tools/contrast/generate.mjs`` does; ``rejected-*`` and ``decorative`` rows are reported, never
gated; (2) every token the spec binds, resolved or MISSING (the ``color.edge.*`` / ``color.port.*``
/ ``color.accent.subtle`` / ``radius.full`` rows print MISSING: the DS change request's evidence);
(3) which pairs ``pairs.mjs`` registers (a text scan) and which the spec PROPOSES; (4) the shipped
vocabulary the boards quote: the six port types and every refused-pair sentence of ``ports.ts``,
the six ``RuleGraphError`` codes, the five ``GraphNodeType`` values, the seven graph-only reason
strings of ``form.py``, the ``Rules``-context keymap rows with their chords; (5) the string gates:
the four indicator words on SCR-081 and SCR-082 agree for 1 / 3 / 4 and differ only for 2, the
form's state-2 string and "node-only" appear only in rows that quote their source, the two
recovery sentences are present verbatim, the two loosening sentences #4137 supersedes are absent,
no local path or host, and - with ``--pr-body`` - no closing keyword; (6) the A2 gates of the
orchestrator's ruling, each as a ruling sentence AND anchored to the frame rows that draw it: both
mismatch rows draw the ``mismatch`` badge (glyph + word), the danger outline, the selection and
the node-list row selected and focused; both graph-only frames draw the ``graph-only`` badge; no
clause of sections 0 and 2-5 pairs the trigger with an edge into the root and the CMP-147 cell
says **no edge**; every T2 of a frame row names its key or the one notice, the P0 row carries its
keyed reason, the P0 paragraph the lock, the armed frame ``Save`` among its T2 writes, every keyed
reason at most 60 characters; the native stop on the CMP-149 row, the Action inspector row and
board 07 for every ``places_orders`` action of ``catalogue.py``, on the first two rows each action
paired with its own stop clause (``place_order`` with the non-emptiable field, ``sl.note`` and
``sl.kept``; ``scale_in`` and the other four each with their read-only sentence verbatim); the
four indicator words
verbatim in the Word cell of their frame row and in the copy deck, and an ``Arm…`` class named
on every frame row (the pre-PR lens's F-8 and F-1); S-graph's pinned wiring, every gate
reaching the action through one root (the text approval's b-1); (7) the structure counts
(``<!-- audit:NAME=VALUE -->`` markers).

``--self-test [SPEC]`` runs the text reviews' 21 frame-level mutations of those elements on the
spec in memory (the file is never written): each must exit 1 with exactly one new FAIL, and the
clean spec must exit 0 before and after.

``--json`` prints one object (the board script's NUM / TERMS and check-nums consume it).
``--check <spec> [--pr-body FILE]`` re-derives every marker, runs every gate and the cite check:
for every ``file:line`` cite whose needle is registered in CITES the needle is searched by
content - at the cited line OK; at one other line WARN (drifted; exit 0); absent or found more
than once FAIL (exit 1). Every ``C-x.y`` cited must exist verbatim in CONSTITUTION.md.

Usage: python3 -I docs/design/_tools/e37_d02_node_editor_audit.py [--json]
       python3 -I docs/design/_tools/e37_d02_node_editor_audit.py --check SPEC [--pr-body FILE]
       python3 -I docs/design/_tools/e37_d02_node_editor_audit.py --self-test [SPEC]
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "docs/plan"
RULES = ROOT / "services/api/candleviewer/rules"
GRAPH_PKG = ROOT / "packages/rule-graph"
TOKENS = ROOT / "packages/ui/tokens"
SPEC = ROOT / "docs/design/E37/E37-D02.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
MULTI = re.MULTILINE

# Cite keys the spec uses (inside backticks, ``KEY``:LINE) -> the file they name.
FILES: dict[str, Path] = {
    "02": PLAN / "02-definition-of-ready-done.md",
    "05": PLAN / "05-accessibility-standard.md",
    "10": PLAN / "10-personas.md",
    "11": PLAN / "11-user-stories.md",
    "12": PLAN / "12-sitemap.md",
    "13": PLAN / "13-user-flows.md",
    "14": PLAN / "14-screens-catalogue.md",
    "15": PLAN / "15-component-catalogue.md",
    "16": PLAN / "16-design-system-brief.md",
    "18": PLAN / "18-traceability-matrix.md",
    "20": PLAN / "20-architecture.md",
    "22": PLAN / "22-api-openapi.yaml",
    "24": PLAN / "24-internal-schemas.md",
    "30": PLAN / "30-release-roadmap.md",
    "32": PLAN / "32-risk-register.md",
    "24-OD": ROOT / "docs/research/24-owner-decisions.md",
    "CONSTITUTION.md": ROOT / "CONSTITUTION.md",
    "ADR-0007": PLAN / "27-adrs/ADR-0007-rule-ir.md",
    "ADR-0026": PLAN / "27-adrs/ADR-0026-rule-ir-canonicalisation.md",
    "ADR-0029": PLAN / "27-adrs/ADR-0029-rule-graph-library.md",
    "E09-D09": ROOT / "docs/design/E09/E09-D09.md",
    "E30-D02": ROOT / "docs/design/E30/E30-D02.md",
    "E25-D01": ROOT / "docs/design/E25/E25-D01.md",
    "E33-D02": ROOT / "docs/design/E33/E33-D02.md",
    "E36-D02": ROOT / "docs/design/E36/E36-D02.md",
    "E36-D03": ROOT / "docs/design/E36/E36-D03.md",
    "E36-D04": ROOT / "docs/design/E36/E36-D04.md",
    "E35-D02": ROOT / "docs/design/E35/E35-D02.md",
    "E35-D03": ROOT / "docs/design/E35/E35-D03.md",
    "E37-D01": ROOT / "docs/design/research/e37-node-graph-vs-list.md",
    "form.py": RULES / "ir/form.py",
    "graph.py": RULES / "compiler/graph.py",
    "catalogue.py": RULES / "vocabulary/catalogue.py",
    "validator.py": RULES / "validator.py",
    "model.ts": GRAPH_PKG / "src/model.ts",
    "ports.ts": GRAPH_PKG / "src/ports.ts",
    "errors.ts": GRAPH_PKG / "src/errors.ts",
    "toGraph.ts": GRAPH_PKG / "src/adapter/toGraph.ts",
    "keymap.json": ROOT / "apps/web/src/keymap/keymap.json",
    "semantic-dark.tokens.json": TOKENS / DARK,
    "semantic-light.tokens.json": TOKENS / LIGHT,
    "pairs.mjs": ROOT / "tools/contrast/pairs.mjs",
}

# The registered needles: (key, line) -> a substring that identifies the line by content.
CITES: dict[tuple[str, int], str] = {
    ("14", 79): "### 0.5 Global invariants",
    ("14", 85): "RBAC denies server-side; the UI presents",
    ("14", 86): "equal-status non-canvas alternative",
    ("14", 1819): "a rule with no action cannot be saved",
    ("14", 1822): "**`Round-trips ✓`** — the IR compiled from this form",
    ("14", 1823): "**`Graph-only construct — read-only here`**",
    ("14", 1824): "Keep the form version (the graph layout will be regenerated)",
    ("14", 1825): "saving is permitted as a draft only, arming is blocked",
    ("14", 1831): "[E36-D02.md](../design/E36/E36-D02.md) · [E36-D02-handoff.md]",
    ("14", 1834): "### SCR-082 — Rule editor — node-graph mode",
    ("14", 1836): "Visual node editor over the **same IR**",
    ("14", 1839): '+--- Rule: "ATR trail 2x"',
    ("14", 1842): "(on bar close)--+",
    ("14", 1844): "| [Metrics]",
    ("14", 1846): "(swing_low 5)---------( max )---(modify_stop)",
    ("14", 1847): "only tighten |",
    ("14", 1850): "[ minimap ]  zoom 100%  [auto-layout]",
    ("14", 1852): "[ Validate ] [ Simulate ] [ Save ] [ Arm... ]  errors: 0",
    ("14", 1856): "**Components:** CMP-146 NodeGraphCanvas",
    ("14", 1857): "stored alongside the IR as presentation metadata",
    ("14", 1858): "`Ctrl+L` auto-layout; `Space+drag` pan",
    ("14", 1859): "remove the connection from X to Y",
    ("14", 1860): "mirrored for this direction",
    ("14", 1861): "every node in this graph maps to a form-editor construct",
    ("14", 1862): "What won't round-trip",
    ("14", 1863): "the same two explicit recovery choices as SCR-081",
    ("14", 1864): "draft-save only, arming blocked, stated in text",
    ("14", 1865): "the round-trip equivalence test (author in form",
    ("14", 1867): "ATR 14, output connects to Multiply input A",
    ("14", 1868): "warning banner above 120 nodes",
    ("14", 1869): "`rule.graph_saved`",
    ("14", 1871): "auto-layout result reviewed on a 60-node graph",
    ("14", 1872): "**UX research (E37-D01):**",
    ("14", 1916): "### SCR-085 — Rule arming dialog",
    ("14", 1918): "step-up 2FA for Live",
    ("14", 1968): "### SCR-088 — Rule IR inspector",
    ("14", 1976): "the diff view used by the round-trip check drawn",
    ("14", 1978): "the drawn CMP-240 tree, account ids masked",
    ("14", 3093): "### 12.5 Design sign-off gate",
    (
        "14",
        3099,
    ): "SCR-081 and SCR-082 additionally require the form↔graph round-trip equivalence test",
    ("15", 69): "### CMP-003 SegmentedControl",
    ("15", 197): "### CMP-016 Tooltip",
    ("15", 206): "### CMP-017 Popover",
    ("15", 224): "### CMP-019 Icon",
    ("15", 288): "### CMP-026 EmptyState",
    ("15", 307): "### CMP-028 Callout",
    ("15", 375): "### CMP-035 Countdown",
    ("15", 412): "### CMP-039 FocusRing",
    ("15", 464): "### CMP-044 ConfirmDialog",
    ("15", 482): "### CMP-046 Drawer",
    ("15", 799): "### CMP-079 RbacGate",
    ("15", 1663): "### CMP-146 NodeGraphCanvas",
    ("15", 1666): "`onConnect` · `readOnly?`",
    ("15", 1667): "the primary accessible-equivalent mechanism for the node-graph",
    ("15", 1668): "**Tokens**: `color.surface.canvas`, `color.edge.default/selected`",
    ("15", 1674): 'type: "trigger" | "condition" | "action" | "logicGate" | "comment";',
    ("15", 1688): "onConnect: (source: string, target: string) => void;",
    ("15", 1696): "### CMP-147 NodeGraphNode — TriggerNode",
    ("15", 1700): 'aria-label="Trigger node: on bar close, 5m"',
    ("15", 1701): "**Tokens**: `color.node.trigger`",
    ("15", 1705): "### CMP-148 NodeGraphNode — ConditionNode",
    ("15", 1707): "with input/output handles for logic-gate wiring",
    ("15", 1709): '"Connect output of condition node"',
    ("15", 1710): "**Tokens**: `color.node.condition`",
    ("15", 1714): "### CMP-149 NodeGraphNode — ActionNode",
    ("15", 1719): "PlaceOrder, ModifySl, Flatten",
    ("15", 1722): "### CMP-150 NodeGraphNode — LogicGateNode",
    ("15", 1725): '`gateType: "AND"|"OR"|"NOT"`',
    ("15", 1726): "**Tokens**: `color.node.logic`",
    ("15", 1730): "### CMP-151 NodeGraphNode — CommentNode",
    ("15", 1734): "**Tokens**: `color.node.comment`",
    ("15", 1738): "### CMP-152 NodeGraphEdge",
    ("15", 1742): '"Delete connection"',
    ("15", 1743): "**Tokens**: `color.edge.default/selected`.",
    ("15", 1747): "### CMP-153 NodeInspectorDrawer",
    ("15", 1749): "keeping on-canvas node chrome minimal",
    ("15", 1751): "inherits CMP-046 Drawer",
    ("15", 1781): "### CMP-157 MetricPickerCombobox",
    ("15", 1790): "### CMP-158 SafetyInvariantNotice",
    ("15", 1792): "pinned directly above the action bar",
    ("15", 1796): '`role="note"`, always visible in both CMP-145 and CMP-146',
    ("15", 2640): "### CMP-227 EstimatedBadge",
    ("15", 2725): "### CMP-234 ValidationPanel",
    ("15", 2728): 'anchor:{kind:"row"|"node"|"edge",id}',
    ("15", 2729): "the sole mechanism by which a keyboard user navigates graph diagnostics",
    ("15", 2730): "`color.status.warn` and the bare `color.status.danger` do not exist",
    ("15", 2735): "### CMP-235 EditorModeToggle",
    ("15", 2738): "`lossyWarning?: {constructs: string[]}` · `dirty: boolean`",
    ("15", 2739): "the switch is **allowed**",
    ("15", 2744): "### CMP-236 NodePalette",
    ("15", 2746): "(triggers, metrics, comparators, logic gates, actions, comments)",
    ("15", 2747): "`categories: {id,label,nodes:{type,label,description,icon}[]}[]`",
    (
        "15",
        2748,
    ): "selecting a palette entry and pressing `Enter` inserts it connected to the current",
    ("15", 2749): "**Tokens**: `color.surface.raised`, `space.2`",
    ("15", 2753): "### CMP-237 NodePort",
    ("15", 2755): "(boolean, number, price, side, action)",
    ("15", 2756): '`kind: "in"|"out"`',
    ("15", 2757): '"Input, boolean, not connected"',
    ("15", 2758): "**Tokens**: `color.port.*`, `radius.full`",
    ("15", 2762): "### CMP-238 Minimap",
    ("15", 2765): "`nodes: {id,rect,severity?}[]`",
    ("15", 2766): "the equivalent keyboard navigation is the node list in CMP-153",
    ("15", 2767): "**Tokens**: `color.surface.sunken`, `color.accent.subtle`",
    ("24", 2978): "authoring surface of record",
    ("24", 2979): "node positions; ignored by the engine",
    ("24", 3032): "class BooleanNode(BaseModel):",
    ("24", 3377): "### 11.4 Form editor ↔ node editor round-trip",
    ("24", 3392): "**Form subset** (`form_compatible == true`)",
    ("24", 3394): "this rule uses graph-only features",
    ("24", 3396): 'a disagreement shows as "server differs"',
    ("24", 3398): "`MULTIPLE_SINKS` means the actions hang off more than one condition",
    ("24", 3445): "### 11.6 Vocabulary",
    ("24", 3447): "**Triggers** — `on_price_update`",
    ("24", 3456): "| `modify_stop_loss`",
    ("24", 3458): "| `move_to_breakeven`",
    ("24", 3483): "| New-rule gate",
    ("24", 3485): "| Disconnect guard",
    ("22", 282): "answers `403 view_as_read_only` and changes nothing",
    ("22", 592): "- code: view_as_read_only",
    ("22", 658): "- code: version_conflict",
    ("22", 7377): "  /rules/{ruleId}:",
    ("22", 7382): "summary: Get a rule with its active IR",
    ("22", 7401): "operationId: updateRule",
    ("22", 7404): "Every save creates an immutable new `rule_versions` row",
    ("22", 7436): "operationId: deleteRule",
    ("22", 7438): "Refused with `conflict` while the rule is `armed`",
    ("22", 7546): "operationId: validateRule",
    ("22", 7570): "a failing IR is still a 200 with `valid: false`",
    ("22", 7686): "operationId: setRuleMode",
    ("22", 12956): "operationId: getRuleVocabulary",
    ("22", 12985): "Engine offline - the registry is empty or not wired.",
    ("22", 13005): "/rules/{ruleId}/compile:",
    ("22", 13010): "operationId: compileRule",
    ("22", 13030): "counterpart_model:",
    ("22", 13035): "the server never reconciles",
    ("22", 13048): "blocks_arming: { type: boolean }",
    ("22", 13049): "round_trip:",
    ("22", 14430): "Omitting it accepts last-write-wins.",
    ("22", 19242): "editor: { type: string, enum: [form, graph], default: form }",
    ("22", 19249): "Node/edge coordinates for the node-graph editor. Ignored by the engine.",
    ("05", 28): "### 3.1 Design rules",
    ("05", 38): "### 3.2 Default hotkey map (v1)",
    ("05", 74): "| **Rule builder (node graph)** | Add node",
    ("05", 75): "Connect focused ports",
    ("05", 76): "Delete focused node/edge",
    ("05", 85): "`Ctrl+K` (command palette, the recovery mechanism",
    ("05", 88): "Tracking note — rule-builder node-graph keyboard spec",
    ("05", 90): "### 3.4 Focus management in dense layouts",
    ("05", 94): "Rule Builder canvas) is a labelled ARIA landmark",
    ("05", 95): "rule-graph nodes): only one cell/row is in the natural Tab order",
    ("05", 97): "**Modal dialogs**",
    ("05", 99): "**Visible focus indicator**",
    ("05", 100): "**Target size**",
    ("05", 101): "**Dragging alternatives**",
    ("05", 121): "## 5. Contrast in the dark theme",
    ("05", 125): "**Text contrast (WCAG 1.4.3, AA)**",
    ("05", 126): "**Non-text/UI component contrast (WCAG 1.4.11, AA)**",
    ("05", 131): "**Text resize (WCAG 1.4.4, AA)**",
    ("05", 202): "## 7. Reduced motion",
    ("05", 206): "replaced with instant state changes or a single low-amplitude cross-fade",
    ("05", 208): "**No content flashes more than 3 times per second**",
    ("05", 209): "Reduced-motion is a **design-system token/mode**",
    ("05", 257): "## 10. Accessibility acceptance-criteria template",
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
    ("11", 3637): "my original layout rather than an auto-layout",
    ("11", 3708): "#### US-RULE-005",
    ("11", 3710): "so that complex logic is easier to see",
    ("11", 3713): "Scenario: Build by graph",
    ("11", 3716): "Scenario: Invalid connection",
    ("11", 3719): "Scenario: Layout aids",
    ("11", 3722): "Scenario: Cycle in the graph (error)",
    ("11", 3724): "the offending cycle is highlighted as a path",
    ("11", 3725): "Scenario: Orphan and dangling nodes (edge)",
    ("11", 3727): "listed by node name in a jump-to-node error list",
    ("11", 3731): "connected CVD divergence output to AND input 1",
    ("11", 3734): 'badged "node-only" immediately',
    ("11", 3741): "#### US-RULE-006",
    ("11", 3749): "Scenario: Unsaved changes",
    ("11", 3752): "Scenario: Read-only fallback",
    ("11", 3758): '"round-trip integrity failure"',
    ("11", 3759): "Scenario: Concurrent edit in two tabs (error)",
    ("11", 3762): "naming the other editor and session",
    ("11", 3766): '"edit as a new draft version"',
    ("11", 3769): "preserves the node-only sub-tree byte-for-byte",
    ("12", 78): "Same rule, alternate editor bound to shared IR",
    ("12", 287): "Which rule editor renders first",
    ("13", 305): "## 10. Rule creation",
    ("13", 312): "B{Start in form or graph?}",
    ("13", 316): "wire connections",
    ("18", 375): "| **US-RULE-005** Node-graph editor",
    ("18", 376): "| **US-RULE-006** Editor round-trip switching",
    ("18", 599): "| **SCR-082** | Rule editor — node-graph mode",
    ("18", 857): "| CMP-146 | NodeGraphCanvas",
    ("18", 949): "| CMP-238 | Minimap",
    ("20", 718): "rule-graph/                 # pure rule IR",
    ("30", 139): "| **E37** | Rule node-graph editor | R3",
    ("30", 443): "| **E37 Rule node-graph editor** |",
    ("30", 456): "5. Rule round-trip: a corpus of ≥30 rules",
    ("32", 465): "### RSK-034",
    ("32", 537): "### RSK-040",
    ("32", 1058): "| R5 Credential & key security",
    ("02", 53): "Design has been Done for ≥2 sprints",
    ("16", 147): "## 5. Iconography",
    ("16", 208): "## 8. Layout grid",
    ("16", 483): "### 11.4 Per-component handoff checklist",
    ("16", 591): "## 12. Design QA checklist",
    ("24-OD", 18): "Both form/condition-list editor AND visual node-graph editor in v1",
    ("CONSTITUTION.md", 128): "**C-2.6 Native exchange stop-loss invariant.**",
    ("CONSTITUTION.md", 164): "**C-2.12 Server-side authority.**",
    ("CONSTITUTION.md", 401): "**C-4.8**",
    ("CONSTITUTION.md", 438): "**C-4.13**",
    ("CONSTITUTION.md", 443): "**C-4.14** Flags may never gate",
    ("CONSTITUTION.md", 495): "**C-6.1 Contract first.**",
    ("CONSTITUTION.md", 898): "**C-14.1**",
    ("CONSTITUTION.md", 1111): "**C-16.5 Single-source-of-truth registry.**",
    ("ADR-0007", 49): "semantically lossless** and cosmetically best-effort",
    ("ADR-0007", 50): "not a dataflow engine; cycles and multiple sinks are compile errors",
    ("ADR-0026", 3): "- Status: **proposed**",
    ("ADR-0029", 13): "Use **@xyflow/react (React Flow) 12.x, pinned exactly**",
    ("ADR-0029", 14): "connect is a keyboard state machine in our code",
    ("ADR-0029", 15): "**Provisional soft cap of 120 nodes**",
    ("ADR-0029", 18): "**Auto-layout runs in a web worker**",
    (
        "ADR-0029",
        20,
    ): "`graph_layout` is persisted separately and excluded from the canonical IR hash",
    ("E09-D09", 32): "### 2.1 The decision rule",
    ("E09-D09", 46): "### 2.2 The four treatments",
    ("E09-D09", 48): "- **T1 Enabled.**",
    ("E09-D09", 49): "- **T2 Disabled with a visible reason (D4).**",
    ("E09-D09", 83): "### 3.1 The keys",
    ("E09-D09", 89): '`rbac.permission`        | "Your role can\'t {verb}."',
    ("E09-D09", 90): '`rbac.owner_only`        | "Only the owner can {verb}."',
    ("E09-D09", 95): '`rbac.view_as`           | "Read-only while viewing as {user}."',
    ("E09-D09", 99): "### 3.2 The verb table",
    ("E09-D09", 224): "### 9.1 `aria-disabled` versus `disabled`",
    ("E09-D09", 238): "### 9.3 Keys on a T2 control",
    (
        "E30-D02",
        128,
    ): "disabled = `opacity.disabled` on the control with the reason as full-opacity text",
    ("E25-D01", 329): "### 9.5 Catalogue amendments",
    (
        "E25-D01",
        334,
    ): '**"Hollow, dashed or hatched = estimated or absent, never a side or direction."**',
    ("E36-D02", 42): "## 0. The planned boards",
    ("E36-D02", 66): "the `place_order` native stop field is non-emptiable",
    ("E36-D02", 79): "| The lane agreements",
    ("E36-D02", 101): "## 3. The state inventory",
    ("E36-D02", 105): "| **02-1 draft** (S1)",
    ("E36-D02", 107): "| **02-3 valid** (S2)",
    ("E36-D02", 109): "| **02-5 armed** (ARMED-DEMO)",
    ("E36-D02", 110): "| **02-6 vocabulary-unavailable**",
    (
        "E36-D02",
        114,
    ): "**Viewing as (E09-D09 §2.1 step 3a) — a treatment of every frame, not a seventh state:**",
    ("E36-D02", 116): "## 4. The round-trip indicator contract",
    ("E36-D02", 158): "**The action picker:**",
    ("E36-D02", 162): '| `place_order` "Place order"',
    ("E36-D02", 118): "**Props (names PROPOSED, mapped to the audit event):**",
    ("E36-D02", 122): '"This rule is fully editable in both the form and the graph editor."',
    ("E36-D02", 123): 'Open in the graph editor to change this." — the lead-in',
    ("E36-D02", 124): '| 3 `mismatch` — **"Round-trip mismatch"**',
    ("E36-D02", 125): '| 4 `unverified` — **"Not verified"**',
    ("E36-D02", 126): "**Checking…** (`checking: true`)",
    ("E36-D02", 127): "**since your last save** (`staleSince` set)",
    ("E36-D02", 129): "The indicator is mirrored on SCR-082",
    ("E36-D02", 215): "## 12. Keyboard, focus and targets",
    ("E36-D02", 260): "## 14. Copy deck",
    ("E36-D02", 264): "**Recovery choices (PROPOSED, from `14`'s two",
    ("E36-D02", 268): "**Safety lines:**",
    ("E36-D02", 270): "**The five validation strings",
    ("E36-D02", 272): "**Form validity is not a T2 reason**",
    ("E36-D02", 273): "**View-as (E09-D09 §2.1 step 3a):**",
    ("E36-D02", 276): "**T2 reason keys**",
    ("E36-D02", 287): "| `rule.arm.simulate_first`",
    ("E36-D02", 288): "| `rule.arm.unverified`",
    ("E36-D02", 289): "| `rule.save.mismatch`",
    ("E36-D02", 293): "## 15. Themes and densities",
    ("E36-D02", 345): "## 16. `15` amendments",
    ("E36-D02", 369): "## 19. Heuristic evaluation",
    ("E36-D02", 419): "| D02-G11 |",
    ("E36-D02", 421): "| D02-G13 |",
    ("E36-D03", 89): "`form` is the default, memo Q7 RULED",
    ("E36-D03", 96): "## 3. SCR-080 states and the status words",
    ("E36-D03", 102): "| DRAFT      |",
    ("E36-D03", 104): "| ARMED-DEMO |",
    ("E36-D03", 105): "| ARMED-LIVE |",
    ("E36-D03", 118): "## 5. SCR-088 anatomy",
    ("E36-D03", 122): "## 6. SCR-088 states",
    ("E36-D03", 142): "## 9. The `15` contributions",
    ("E36-D03", 194): '"The node editor is off for this workspace." (PROPOSED)',
    ("E36-D04", 115): "## 2. The equal-status frame",
    ("E36-D04", 344): "| K-08 |",
    ("E36-D04", 345): "| K-09 |",
    ("E36-D04", 348): "| K-12 |",
    ("E36-D04", 726): "the node-list panel (`Alt+L`) and SCR-082's keys are theirs (K-12)",
    ("E35-D02", 173): "## 4. SCR-085 anatomy",
    ("E35-D02", 212): "## 5. SCR-085 state inventory",
    ("E35-D03", 269): "## 7. SCR-088 deltas",
    ("E37-D01", 10): "## Locked, not relitigated",
    ("E37-D01", 105): "## 3. The stimulus corpus",
    ("E37-D01", 223): "### 7.1 R1",
    ("E37-D01", 227): "### 7.2 R2",
    ("E37-D01", 231): "### 7.3 R3",
    ("E37-D01", 235): "### 7.4 R4",
    ("E37-D01", 239): "### 7.5 R5",
    ("E37-D01", 243): "## 8. Node-editor principles",
    ("E37-D01", 249): "| P1  |",
    ("E37-D01", 251): "| P3  |",
    ("E37-D01", 252): "| P4  |",
    ("E37-D01", 258): "| P10 |",
    ("E37-D01", 330): "| A2  |",
    ("E37-D01", 253): "| P5  |",
    ("E37-D01", 254): "| P6  |",
    ("E37-D01", 256): "| P8  |",
    ("E37-D01", 257): "| P9  |",
    ("E37-D01", 259): "| P11 |",
    ("E37-D01", 260): "| P12 |",
    ("E37-D01", 262): "**Reflow note.**",
    ("E37-D01", 266): "### 9.1 Contradictions",
    ("E37-D01", 275): "| C4  |",
    ("E37-D01", 278): "| C7  |",
    ("E37-D01", 280): "| C9  |",
    ("E37-D01", 281): "| C10 |",
    ("E37-D01", 283): "| C12 |",
    ("E37-D01", 285): "| C14 |",
    ("E37-D01", 287): "| C16 |",
    ("E37-D01", 288): "| C17 |",
    ("E37-D01", 290): "### 9.2 Contract and definition gaps",
    ("E37-D01", 298): "| G3  |",
    ("E37-D01", 301): "| G6  |",
    ("E37-D01", 302): "| G7  |",
    ("E37-D01", 304): "| G9  |",
    ("E37-D01", 305): "| G10 |",
    ("E37-D01", 307): "### 9.3 Open questions",
    ("E37-D01", 313): "| Q1  |",
    ("E37-D01", 314): "| Q2  |",
    ("E37-D01", 315): "| Q3  |",
    ("E37-D01", 318): "| Q6  |",
    ("E37-D01", 319): "| Q7  |",
    ("E37-D01", 323): "### 9.4 Catalogue and plan amendments",
    ("E37-D01", 329): "| A1  |",
    ("E37-D01", 334): "| A6  |",
    ("E37-D01", 337): "| A9  |",
    ("E37-D01", 338): "| A10 |",
    ("E37-D01", 340): "## 10. Failure path",
    ("E37-D01", 346): "## 11. Inputs handed to E37-D04",
    ("E37-D01", 348): "**E37-D02 adopts it PROPOSED and E37-D04 verifies it.",
    ("form.py", 23): "arithmetic operand in",
    ("form.py", 31): "temporal op '{node.op}' is graph-only",
    ("form.py", 35): "temporal node must directly wrap a comparison",
    ("form.py", 37): "nested deeper than two levels",
    ("form.py", 42): "boolean op '{node.op}' is graph-only",
    ("form.py", 49): "boolean nested inside root any_of",
    ("form.py", 87): "node fans out to {n} consumers",
    ("form.py", 91): "def form_compatible",
    ("graph.py", 6): "comparison|boolean|temporal|arithmetic|action",
    ("graph.py", 8): "left|right|right2|in|child|when",
    ("graph.py", 10): "exactly one ``when`` edge from the single root condition",
    ("graph.py", 12): "Well-formedness (cycles, multiple sinks, orphans, dangling ports)",
    ("graph.py", 14): "form-subset detector flags as graph-only",
    # :182 repeats :172's token at a shallower indent (any needle of it also hits :172): left
    # unregistered, counted as such.
    ("graph.py", 172): '                    "multiple_sinks",',
    ("graph.py", 201): '_err("orphan_node", f"nodes.{o}"',
    ("catalogue.py", 42): "places_orders: bool = False",
    ("catalogue.py", 63): "RETIRED_ACTIONS = frozenset",
    ("catalogue.py", 65): 'ActionSpec("place_order", "Place order"',
    ("catalogue.py", 70): 'ActionSpec("scale_in", "Scale in"',
    ("catalogue.py", 73): 'ActionSpec("reverse_position", "Reverse position"',
    ("catalogue.py", 80): 'ActionSpec("arm_chase_limit", "Arm chase limit"',
    ("validator.py", 202): '"native_stop_violation"',
    ("E33-D02", 107): "| C-2.6 + C-4.14 on every algo child",
    ("catalogue.py", 66): "only_tighten=false is refused",
    ("model.ts", 3): "export type GraphNodeType",
    ("model.ts", 14): "export interface GraphEdge",
    ("model.ts", 34): "readonly collapsed: readonly string[];",
    ("model.ts", 35): "readonly comments: readonly CommentNode[];",
    ("ports.ts", 10): '["boolean", "number", "price", "side", "action", "trigger"]',
    ("ports.ts", 20): "80 characters (the OQ9 ruling; §3.1 says 60)",
    ("ports.ts", 23): "export const PORT_COMPAT = frozen({",
    ("ports.ts", 26): 'number: "A true or false result can\'t be used as a number.",',
    ("ports.ts", 37): 'action: "A number can\'t run an action.",',
    ("ports.ts", 69): "A trigger can't run an action without a condition.",
    ("ports.ts", 70): "A trigger can't connect to another trigger.",
    ("ports.ts", 86): "export const NODE_PORTS = frozen({",
    ("errors.ts", 6): "`CYCLE_DETECTED`: the graph holds a cycle",
    ("errors.ts", 7): "`DANGLING_PORT`: a required input port has no connection.",
    ("errors.ts", 8): "`ORPHAN_NODE`: a node reaches no action.",
    ("errors.ts", 9): "`NOT_FORM_REPRESENTABLE`: the rule uses a graph-only construct",
    ("errors.ts", 12): "`MULTIPLE_SINKS`: the actions hang off more than one condition",
    ("toGraph.ts", 50): '{ id: "trigger", type: "trigger"',
    ("keymap.json", 266): '"id": "chart.undo"',
    ("keymap.json", 275): '"id": "chart.redo"',
    ("keymap.json", 565): '"id": "rules.save_draft"',
    ("keymap.json", 584): '"id": "rules.validate"',
    ("keymap.json", 599): '"id": "rules.graph_mode"',
    ("keymap.json", 638): '"id": "rules.delete"',
    ("keymap.json", 654): '"id": "rules.select_all"',
    ("keymap.json", 663): '"id": "rules.group"',
    ("keymap.json", 672): '"id": "rules.auto_layout"',
    ("keymap.json", 684): '"id": "rules.pan"',
    ("keymap.json", 693): '"id": "rules.cycle_nodes"',
    ("keymap.json", 702): '"id": "rules.inspect_node"',
    ("keymap.json", 721): '"id": "rules.rename"',
    ("semantic-dark.tokens.json", 6): '"color.surface.canvas": {',
    ("semantic-dark.tokens.json", 18): '"color.surface.sunken": {',
    ("semantic-dark.tokens.json", 258): '"color.node.trigger": {',
    ("semantic-dark.tokens.json", 274): '"color.node.comment": {',
    ("semantic-light.tokens.json", 66): '"color.node.trigger":',
    ("semantic-light.tokens.json", 70): '"color.node.comment":',
    ("pairs.mjs", 42): '{ fg: "color.focus.ring", bg: "color.surface.canvas"',
    ("pairs.mjs", 77): '{ fg: "color.node.trigger", bg: "color.surface.canvas"',
    ("pairs.mjs", 81): '{ fg: "color.node.comment", bg: "color.surface.canvas"',
    ("pairs.mjs", 86): '{ fg: "color.border.selected", bg: "color.surface.app"',
}

# element | fg | bg | role -- every pair SCR-082 draws (spec section 16, rows in order). A line
# indented by two spaces continues the record above it (no physical line passes 100 columns).
PAIRS_TABLE = """
header title, node label, node-list row, dialog text
  | color.text.primary | color.surface.canvas | text
sentence fragments, port names, captions | color.text.secondary | color.surface.canvas | text
the zoom readout and the footer caption | color.text.tertiary | color.surface.canvas | text
node body label, action-bar labels, palette entry | color.text.primary | color.surface.raised | text
T2 reason, palette description, inspector help | color.text.secondary | color.surface.raised | text
T2 kept label (E09-D09 section 2.2) | color.text.tertiary | color.surface.raised | text
trigger node stripe on the canvas | color.node.trigger | color.surface.canvas | non-text
condition node stripe on the canvas | color.node.condition | color.surface.canvas | non-text
action node stripe on the canvas | color.node.action | color.surface.canvas | non-text
logic gate stripe on the canvas | color.node.logic | color.surface.canvas | non-text
comment node stripe on the canvas | color.node.comment | color.surface.canvas | non-text
trigger stripe if inset in the node body (never drawn: two of five sit under the bar)
  | color.node.trigger | color.surface.raised | rejected-non-text
condition stripe if inset in the node body
  | color.node.condition | color.surface.raised | rejected-non-text
action stripe if inset in the node body
  | color.node.action | color.surface.raised | rejected-non-text
logic gate stripe if inset in the node body
  | color.node.logic | color.surface.raised | rejected-non-text
comment stripe if inset in the node body
  | color.node.comment | color.surface.raised | rejected-non-text
edge default ink (the fallback for the missing color.edge.default)
  | color.text.tertiary | color.surface.canvas | non-text
edge selected ink, selected node outline, minimap viewport
  | color.border.selected | color.surface.canvas | non-text
minimap viewport on the minimap well | color.border.selected | color.surface.sunken | non-text
unconnected port ring | color.text.tertiary | color.surface.raised | non-text
error outline, cycle path, invalid-preview edge
  | color.status.danger.default | color.surface.canvas | non-text
error outline against the node body | color.status.danger.default | color.surface.raised | non-text
orphan / dangling warning outline | color.status.warning.default | color.surface.canvas | non-text
graph-only badge word, chip 2 word, warning banner
  | color.text.primary | color.status.warning.subtle | text
graph-only badge glyph, chip 2 glyph
  | color.status.warning.strong | color.status.warning.subtle | non-text
mismatch badge word, chip 3 word | color.text.primary | color.status.danger.subtle | text
mismatch badge glyph, chip 3 glyph (dark danger.strong = palette.amber.400)
  | color.status.danger.strong | color.status.danger.subtle | non-text
chip 1 word | color.text.primary | color.status.success.subtle | text
chip 1 glyph | color.status.success.strong | color.status.success.subtle | non-text
chip 4 word, Checking, the DRAFT pill | color.text.primary | color.surface.hover | text
since your last save; the ? glyph | color.text.secondary | color.surface.hover | text
CMP-158 sentence, the engine-down banner's info twin
  | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
the engine-down banner's second line | color.text.secondary | color.status.danger.subtle | text
focus ring on the canvas (nodes, ports, edges) | color.focus.ring | color.surface.canvas | non-text
focus ring on the node body, cards and the action bar
  | color.focus.ring | color.surface.raised | non-text
focus ring on the minimap well | color.focus.ring | color.surface.sunken | non-text
focus ring on a graph-only badge | color.focus.ring | color.status.warning.subtle | non-text
focus ring on a mismatch badge | color.focus.ring | color.status.danger.subtle | non-text
Save, Save draft | color.text.on-action | color.action.primary.default | text
the selected node-list row | color.text.primary | color.surface.selected | text
the node-list pane and the minimap well labels | color.text.primary | color.surface.sunken | text
the node label in high contrast (claimed) | color.text.primary | color.surface.raised | hc-text
border.default as edge ink: below the bar, so never the edge ink
  | color.border.default | color.surface.canvas | rejected-non-text
E09-D09 T2 keeps text.tertiary for a disabled label
  | color.text.disabled | color.surface.raised | rejected-text
the node body hairline | color.border.default | color.surface.raised | decorative
"""
# Every token the spec binds (sections 2-16); the last ten are the `15` entries' names that do not
# exist (expected MISSING, spec section 16 request 1) or the names the spec proposes.
BINDINGS = (
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.hover",
    "color.surface.selected",
    "color.surface.sunken",
    "color.surface.overlay",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.action.primary.default",
    "color.focus.ring",
    "color.border.default",
    "color.border.selected",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.status.warning.default",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.danger.default",
    "color.status.danger.subtle",
    "color.status.danger.strong",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.node.trigger",
    "color.node.condition",
    "color.node.action",
    "color.node.logic",
    "color.node.comment",
    "radius.control",
    "radius.card",
    "radius.badge",
    "radius.circle",
    "border.thick",
    "border.focus",
    "opacity.disabled",
    "size.target.min",
    "size.icon.sm",
    "size.control.height",
    "space.inset.sm",
    "space.inset.md",
    "space.stack.md",
    "type.ui.body",
    "type.ui.caption",
    "type.ui.heading-sm",
    "font.family.mono",
    "motion.duration.instant",
    "color.edge.default",
    "color.edge.selected",
    "color.port.boolean",
    "color.port.number",
    "color.port.price",
    "color.port.side",
    "color.port.action",
    "color.port.trigger",
    "color.accent.subtle",
    "radius.full",
)
# The ruling sentences of the orchestrator's A2 gates: each must stand in the spec verbatim. They
# alone do not prove a frame draws the element (a sentence survives the element's removal from the
# frame row that draws it), so check_frames() anchors each gate to those rows as well.
GATES: dict[str, str] = {
    "state-3 badge on the diverging nodes only": (
        "State 3 marks only the diverging node(s) named by `round_trip.diff[].path` with the "
        "`mismatch` badge (glyph + word) plus the danger outline, selects it and focuses its "
        "node-list row."
    ),
    "state-2 badge from creation": (
        "State 2 marks every graph-only node with the `graph-only` badge (glyph + word) at "
        "creation, independently of the chip"
    ),
    "no trigger edge": (
        'The trigger node is the leftmost "Check when" clause and carries **no edge** to the '
        "root condition"
    ),
    "T2 anatomy: the lock leads the full label": (
        'a CMP-019 `lock` glyph (`decorative=false`, named "Not available") leads the **full '
        "label**"
    ),
    "T2 anatomy: aria-disabled, never disabled": (
        '`aria-disabled="true"` and never the `disabled` attribute'
    ),
    "T2 anatomy: the view-as leg first": (
        'the view-as leg (`rbac.view_as` "Read-only while viewing as {user}.") is the first '
        "leg on **every** write control"
    ),
    "A1: the native stop on every order-placing action node": (
        "every action node that places an order shows its native stop on the node card and in the "
        "inspector, as the merged texts have it"
    ),
    # The text approval's b-1: the second gate must reach the action, or S-graph is an orphan.
    "S-graph: one root, no gate without an action": (
        "the shared condition feeds `all of` input 1 and `any of` input 1, `any of` feeds `all of` "
        "input 2 and `all of` feeds the action's `when` input"
    ),
}
RECOVERY = (
    "Keep the form version — the graph's {diverging node} is replaced by this form's Row {n}.",
    "Keep the graph version — your form edits since the last save are discarded.",
)
INDICATOR_WORDS = (
    "Round-trips ✓",
    "Unsupported in form view",
    "Round-trip mismatch",
    "Not verified",
)
# The pre-PR lens's F-8: each of the four words must stand verbatim in the Word cell of its §4 frame
# row and in §15's "Indicator words" line, not merely somewhere in the spec.
WORD_FRAMES = (
    ("round-trip-identical", "Round-trips ✓"),
    ("round-trip-graph-only", "Unsupported in form view"),
    ("round-trip-mismatch", "Round-trip mismatch"),
    ("round-trip-unverified", "Not verified"),
)
# The pre-PR lens's F-1: every `SCR-082 / …` row of §3 and §4 names `Arm…`'s class - a T2 key, the
# validity look, the armed frame's `Disarm`, or an enabled `Arm…` that names the satisfied new-rule
# gate (`24` §11.7).
ARM_CLASS = re.compile(
    r"`Arm…` (?:T2 `rule\.[a-z_.]+`|T2 → the banner|V \"|replaced by `Disarm`"
    r"|T1 — the new-rule gate satisfied \(`24`:3483\))"
)
# M-1 of the text review: the A2 gates anchored to the frame rows that draw them.
# (1) Both mismatch rows draw every element of the state-3 drawing (BQ-8): label -> the row text.
MISMATCH_ROWS = ("round-trip-mismatch", "round-trip-mismatch-dialog")
MISMATCH_ELEMENTS = (
    ("the `mismatch` badge (glyph + word)", re.compile(r"badged `mismatch` \(glyph \+ word\)")),
    (
        "the danger outline on the diverging node",
        re.compile(r"the diverging node outlined `color\.status\.danger\.default`"),
    ),
    ("the node selected on the canvas", re.compile(r"\*\*selected\*\*;")),
    (
        "the node-list row selected and focused",
        re.compile(r"node-list row \*\*selected and focused"),
    ),
)
# (2) Both graph-only frames draw the state-2 badge.
GRAPH_ONLY_ROWS = ("editing-graph-only", "round-trip-graph-only")
GRAPH_ONLY_BADGE = re.compile(r"badged `graph-only` \(glyph \+ word\)")
# (2b) The text-delta lens's M-1: S-graph's §20 wiring gate anchored to the frame row that draws
# S-graph and to §0's S-graph clause (a gate sentence alone survives the row losing the wiring);
# the gate count is part of the anchor, so "one logic gate, wired as …" fails too.
S_GRAPH_WIRED = "wired as §20 pins it"
S_GRAPH_ROW_TEXT = f"feeding two logic gates, {S_GRAPH_WIRED}"
S_GRAPH_S0_TEXT = f"one condition feeding two gates, {S_GRAPH_WIRED}"
S_GRAPH_ROW = "editing-graph-only"
S_GRAPH_CLAUSE = re.compile(r"\*\*S-graph\*\* \(([^)]*)")
# (3) No clause of the drawn sections pairs the trigger with an edge into the root (BQ-21); the
# CMP-147 cell must say **no edge** (checked on its own, so the scan skips that row).
TRIGGER = re.compile(r"\btrigger", re.IGNORECASE)
# The fold delta's dm-4: every verb the records name for an edge, plus the arrow.
EDGE_WORD = re.compile(
    r"\b(?:edges?|connect(?:ion|ions|ed|ing|s)?|wir(?:e|es|ed|ing)|feed(?:s|ing)?|fed"
    r"|link(?:s|ed|ing)?|join(?:s|ed|ing)?)\b|→|->",
    re.IGNORECASE,
)
ROOT_WORD = re.compile(r"\broot\b", re.IGNORECASE)
NEGATED = re.compile(
    r"no edge|\bnever\b|\brefused\b|\bwithout\b|can't|\bwith none\b", re.IGNORECASE
)
CLAUSE = re.compile(r"(?<=[.;])\s+| \| ")
# (4) Every T2 in a frame row names its key or points at the one notice / banner; the P0 row
# carries its keyed reason verbatim; the P0 paragraph carries the lock; the armed frame keeps
# `Save` in its T2 list (the pre-PR lens's F-3).
T2_BARE = re.compile(r"(?<!never )(?<!not )\bT2\b(?! `(?:rbac|rule)\.| → the (?:notice|banner))")
P0_PARAGRAPH = "**The mismatch frame — the P0 Gherkin"
P0_LOCK = "T2 with the lock, the full labels"
ARMED_T2_LIST = re.compile(r"every write \(([^)]*)\) T2 → the notice")
# (5) A1 on each surface that draws an order-placing action: the row's first cell -> the section.
A1_SURFACES = (
    ("the CMP-149 action-node row", "| CMP-149 ActionNode", "## 5. ", "## 6. "),
    ("the Action inspector row", "| CMP-153 Action ", "## 9. ", "## 10. "),
    ("board 07's row", "| 07 ", "## 0. ", "## 1. "),
)
A1_MECHANICS = ("non-emptiable", "read-only")
A1_FULL_SET = ("`sl.note`", "`sl.kept`")
# The fold delta's DM-1: on the CMP-149 and inspector rows each action is paired with its own stop
# clause (the row split at "; "): `place_order` with the field, `scale_in` with the position's
# read-only sentence, every other order-placing action with the server's read-only sentence.
A1_CLAUSE = re.compile(r";\s+")
A1_SERVER_STOP = ('"Stop: attached by the server (native SL)."',)
A1_STOP: dict[str, tuple[str, ...]] = {
    "place_order": ("non-emptiable", *A1_FULL_SET),
    "scale_in": ('"Stop: the position\'s native stop, held by Bybit (exchange)."',),
}
FORM_STATE2 = "Graph-only construct — read-only here"  # the form's word: quoted only in C-rows
QUOTING = ("D02-C", "memo A9", "memo C17", "`11`:3734", "`14`:1823")  # rows that may quote a source
# #4137 (a rule action never loosens a stop, for any role) supersedes these two sentences: the gate
# fails if either appears. Split so this file never contains the literals it forbids.
SUPERSEDED = (
    r"This rule may wid[e]n the stop — owner-only, audited\.",
    r"Only the owner can loos[e]n a stop\.",
)
# Private paths and hosts that never belong in a public file: generic patterns only, no personal
# word and no hostname, whole or split (the opener's gate owns those).
FORBIDDEN = (
    r"/(?:home|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"relay\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
)
CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b\s*:?\s*#[0-9]+", re.IGNORECASE)


# ------------------------------------------------------------------ helpers -----------------------
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def lines_of(path: Path) -> list[str]:
    return read(path).split("\n")


def line(path: Path, n: int) -> str:
    rows = lines_of(path)
    return rows[n - 1] if 0 < n <= len(rows) else ""


def rows(table: str) -> list[list[str]]:
    """One record per line; a line indented by two spaces continues the record above it."""
    records: list[str] = []
    for ln in table.strip("\n").splitlines():
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        elif ln:
            records.append(ln.strip())
    return [[c.strip() for c in rec.split(" | ")] for rec in records]


def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


# ------------------------------------------------------------------ tokens and contrast -----------
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads(read(TOKENS / f) or "{}")
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return str(value)


def luminance(hex6: str) -> float:
    r, g, b = (int(hex6.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def registered_pairs() -> set[tuple[str, str]]:
    text = read(FILES["pairs.mjs"])
    return set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', text))


def matrix() -> dict[str, Any]:
    themes = {name: load_theme(name) for name in THEMES}
    reg = registered_pairs()
    out: list[dict[str, Any]] = []
    for element, fg, bg, role in rows(PAIRS_TABLE):
        gated = not role.startswith("rejected") and role != "decorative"
        bar = BAR.get(role.removeprefix("rejected-"))
        cells: dict[str, str] = {}
        verdict = "PASS"
        for name, toks in themes.items():
            if role == "hc-text" and name != "high-contrast":
                cells[name] = "-"
                continue
            f, b = resolve(toks, fg), resolve(toks, bg)
            if "MISSING" in (f, b):
                cells[name] = "MISSING"
                verdict = "FAIL" if gated else verdict
                continue
            ratio = contrast(f, b)
            cells[name] = show(ratio)
            if gated and bar is not None and ratio < bar:
                verdict = "FAIL"
        out.append(
            {
                "element": element,
                "fg": fg,
                "bg": bg,
                "role": role,
                "registered": (fg, bg) in reg,
                "gated": gated,
                **cells,
                "verdict": verdict if gated else "reported",
            }
        )
    gated_rows = [r for r in out if r["gated"]]
    return {
        "rows": out,
        "gated": len(gated_rows),
        "fail": sum(r["verdict"] == "FAIL" for r in gated_rows),
        "registered": sum(r["registered"] for r in gated_rows),
        "proposed": sum(not r["registered"] for r in gated_rows),
    }


def bindings() -> dict[str, Any]:
    themes = {name: load_theme(name) for name in THEMES}
    out = {t: {name: resolve(toks, t) for name, toks in themes.items()} for t in BINDINGS}
    missing = sorted(t for t, v in out.items() if v["dark"] == "MISSING")
    return {"tokens": out, "missing": missing, "missing_count": len(missing)}


# ------------------------------------------------------------------ shipped vocabulary ------------
def form_reasons() -> list[str]:
    return re.findall(r'out\.append\(f"[^"]*?: ([^"]+)"\)', read(FILES["form.py"]))


def order_actions() -> list[str]:
    """Every ``places_orders`` action of the shipped catalogue: A1's set (``catalogue.py`` :42)."""
    out: list[str] = []
    for row in lines_of(FILES["catalogue.py"]):
        name = re.match(r'\s+ActionSpec\("([a-z_]+)"', row)
        flag = re.search(r"\), (?:_OW|\((?:[A-Z_]+,)?\)), (True|False),", row)
        if name and flag and flag.group(1) == "True":
            out.append(name.group(1))
    return out


def rule_graph() -> dict[str, Any]:
    errors = read(FILES["errors.ts"])
    ports = read(FILES["ports.ts"])
    model = read(FILES["model.ts"])
    codes = re.findall(r'^\s+"([A-Z_]+)",$', errors, MULTI)
    types_m = re.search(r"const TYPES = \[([^\]]+)\]", ports)
    port_types = re.findall(r'"([a-z]+)"', types_m.group(1)) if types_m else []
    compat_m = re.search(r"PORT_COMPAT = frozen\(\{(.*?)\n\} as const", ports, re.DOTALL)
    body = compat_m.group(1) if compat_m else ""
    refused = re.findall(r'^\s+[a-z]+: "([^"]+)",$', body, MULTI)
    allowed = len(re.findall(r"^\s+[a-z]+: true,$", body, MULTI))
    union_m = re.search(r"export type GraphNodeType = ([^;]+);", model)
    node_types = re.findall(r'"([A-Za-z]+)"', union_m.group(1)) if union_m else []
    kinds_m = re.search(
        r"export const NODE_PORTS = frozen\(\{(.*?)\n\} as const\)", ports, re.DOTALL
    )
    kinds = re.findall(r"^\s+([a-zA-Z]+): \{ type:", kinds_m.group(1), MULTI) if kinds_m else []
    return {
        "error_codes": codes,
        "port_types": port_types,
        "node_types": node_types,
        "node_kinds": kinds,
        "refused": refused,
        "refused_pairs": len(refused),
        "allowed_pairs": allowed,
        "longest_refusal": max((len(s) for s in refused), default=0),
        "trigger_node_emitted": '{ id: "trigger", type: "trigger"' in read(FILES["toGraph.ts"]),
        "collapsed_carrier": "readonly collapsed: readonly string[];" in model,
    }


def keymap() -> dict[str, Any]:
    text = read(FILES["keymap.json"])
    data = json.loads(text) if text else {"commands": []}
    cmds = [c for c in data.get("commands", []) if str(c.get("id", "")).startswith("rules.")]
    return {
        "rules_commands": len(cmds),
        "commands": {
            c["id"]: [c.get("label"), c.get("defaultBinding"), c.get("screens")] for c in cmds
        },
        "alt_l_bound": text.count('"Alt+L"'),
        "ctrl_shift_l_bound": text.count('"Ctrl+Shift+L"'),
        "scr082_scoped": sorted(c["id"] for c in cmds if c.get("screens") == ["SCR-082"]),
    }


def indicators() -> dict[str, Any]:
    cat = lines_of(FILES["14"])

    def word(needle: str) -> str:
        for row in cat:
            if needle in row:
                m = re.search(r"\*\*`([^`]+)`\*\*", row)
                return m.group(1) if m else "NOT FOUND"
        return "NOT FOUND"

    scr081 = [
        word("the IR compiled from this form is byte-identical"),
        word("the stored IR contains a construct the form editor cannot represent"),
        word("the two representations compile to different IR"),
        word("saving is permitted as a draft only, arming is blocked"),
    ]
    scr082 = [
        word("every node in this graph maps to a form-editor construct"),
        word("this is the state the owner decision specifically requires"),
        word("compile from graph and compile from the stored form representation differ"),
        word("draft-save only, arming blocked, stated in text"),
    ]
    e36 = read(FILES["E36-D02"])
    return {
        "scr081": scr081,
        "scr082": scr082,
        "differing": sum(a != b for a, b in zip(scr081, scr082, strict=True)),
        "e36_d02_words": [w for w in INDICATOR_WORDS if w in e36],
        "recovery_in_e36_d02": all(s in e36 for s in RECOVERY),
    }


# ------------------------------------------------------------------ spec structure ----------------
def ids(prefix: str, body: str) -> list[int]:
    return sorted({int(x) for x in re.findall(rf"^\| {prefix}-?(\d+) +\|", body, MULTI)})


def table_rows(body: str, first_cell: str) -> int:
    return len(re.findall(rf"^\| {re.escape(first_cell)}", body, MULTI))


def structure(spec: str) -> dict[str, Any]:
    s3 = section(spec, "## 3. ", "## 4. ")
    s4 = section(spec, "## 4. ", "## 5. ")
    s5 = section(spec, "## 5. ", "## 6. ")
    s6 = section(spec, "## 6. ", "## 7. ")
    s7 = section(spec, "## 7. ", "## 8. ")
    s8 = section(spec, "## 8. ", "## 9. ")
    s9 = section(spec, "## 9. ", "## 10. ")
    s10 = section(spec, "## 10. ", "## 11. ")
    s13 = section(spec, "## 13. ", "## 14. ")
    s15 = section(spec, "## 15. ", "## 16. ")
    s17 = section(spec, "## 17. ", "## 18. ")
    s21 = section(spec, "## 21. ", "## 22. ")
    ac = section(spec, "## Acceptance-criteria trace", "## 0. ")
    boards = section(spec, "## 0. ", "## 1. ")
    node_header = re.search(r"^\| Node +\|(.+)\|$", s5, MULTI)
    node_states = [c.strip() for c in node_header.group(1).split("|")] if node_header else []
    node_rows = table_rows(s5, "CMP-14") + table_rows(s5, "CMP-15")
    reasons = re.findall(r"^\| `(r(?:bac|ule)\.[a-z_.]+)` +\| \"([^\"]+)\"", s15, MULTI)
    return {
        "screen_states": table_rows(s3, "`SCR-082 / "),
        "indicator_frames": table_rows(s4, "`SCR-082 / round-trip-"),
        "node_types": node_rows,
        "node_states": len(node_states),
        "node_cells": node_rows * len(node_states),
        "port_cells": len(re.findall(r"^\| P\d+ ", s6, MULTI)),
        "edge_states": len(re.findall(r"^\| E\d+ ", s6, MULTI)),
        "refusal_rows": table_rows(s6, "`"),
        "palette_states": table_rows(s7, "`"),
        "inventory_rows": len(re.findall(r"^\| O\d+ ", s8, MULTI)),
        "inspector_types": table_rows(s9, "CMP-153 "),
        "tiers": len(re.findall(r"^\| Tier [ABC] ", s10, MULTI)),
        "minimap_states": len(re.findall(r"^\| M\d+ ", s10, MULTI)),
        "keyboard_rows": table_rows(s13, "`"),
        "reason_keys": len(reasons),
        "reason_max_chars": max((len(v) for _, v in reasons), default=0),
        "reason_rows": reasons,
        "amendment_rows": len(re.findall(r"^\| (?:CMP-\d+|NodeListOutline)", s17, MULTI)),
        "c": ids("D02-C", s21),
        "g": ids("D02-G", s21),
        "q": ids("D02-Q", s21),
        "boards": len(re.findall(r"^\| (\d\d) +\| `E37-D02 / ", boards, MULTI)),
        "light_boards": len(
            re.findall(r"^\| \d\d +\| `E37-D02 / [^|]+\|[^|]+\|[^|]+\| yes", boards, MULTI)
        ),
        "ac_rows": sum(
            1 for ln in ac.split("\n") if ln.startswith(("| Sc. ", "| Box ", "| Note", "| DoD"))
        ),
        "pending": "PENDING" in boards,
    }


def markers(spec: str) -> dict[str, Any]:
    st = structure(spec)
    rg = rule_graph()
    km = keymap()
    mx = matrix()
    bd = bindings()
    ind = indicators()
    return {
        "screen_states": st["screen_states"],
        "indicator_frames": st["indicator_frames"],
        "node_types": st["node_types"],
        "node_states": st["node_states"],
        "node_cells": st["node_cells"],
        "port_cells": st["port_cells"],
        "edge_states": st["edge_states"],
        "palette_states": st["palette_states"],
        "minimap_states": st["minimap_states"],
        "inspector_types": st["inspector_types"],
        "tiers": st["tiers"],
        "inventory_rows": st["inventory_rows"],
        "refusal_rows": st["refusal_rows"],
        "keyboard_rows": st["keyboard_rows"],
        "reason_keys": st["reason_keys"],
        "amendment_rows": st["amendment_rows"],
        "boards": st["boards"],
        "light_boards": st["light_boards"],
        "ac_rows": st["ac_rows"],
        "c": len(st["c"]),
        "g": len(st["g"]),
        "q": len(st["q"]),
        "ports.types": len(rg["port_types"]),
        "ports.refused": rg["refused_pairs"],
        "ports.allowed": rg["allowed_pairs"],
        "ports.longest": rg["longest_refusal"],
        "errors.codes": len(rg["error_codes"]),
        "model.types": len(rg["node_types"]),
        "ports.kinds": len(rg["node_kinds"]),
        "form.reasons": len(form_reasons()),
        "keymap.rules_commands": km["rules_commands"],
        "keymap.alt_l": km["alt_l_bound"],
        "keymap.scr082_scoped": len(km["scr082_scoped"]),
        "matrix.gated": mx["gated"],
        "matrix.fail": mx["fail"],
        "matrix.registered": mx["registered"],
        "matrix.proposed": mx["proposed"],
        "tokens.missing": bd["missing_count"],
        "indicators.differing": ind["differing"],
    }


def derived(spec: str) -> dict[str, Any]:
    return {
        "matrix": matrix(),
        "bindings": bindings(),
        "rule_graph": rule_graph(),
        "form": {"reasons": form_reasons()},
        "keymap": keymap(),
        "indicators": indicators(),
        "structure": structure(spec),
        "markers": markers(spec),
    }


# ------------------------------------------------------------------ --check -----------------------
MARKER = re.compile(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->")
KEY_TOKEN = re.compile(
    r"`([^`\s]+)`(?=\s?:\d)|\b(E\d\d-D\d\d|ADR-\d{4}|CONSTITUTION\.md)\b(?=\s?:\d)"
)
LINE_TOKEN = re.compile(r"(?<![\w:]):(\d{1,5})\b")


def cites_in(text: str) -> list[tuple[str, int, int]]:
    """Every (key, line, spec line number) cite: a backticked or plain key, then :N tokens."""
    out: list[tuple[str, int, int]] = []
    for no, row in enumerate(text.split("\n"), start=1):
        if row.startswith("<!--"):
            continue
        events: list[tuple[int, str, str]] = []
        for m in KEY_TOKEN.finditer(row):
            events.append((m.start(), "key", m.group(1) or m.group(2)))
        for m in LINE_TOKEN.finditer(row):
            events.append((m.start(), "line", m.group(1)))
        key = None
        for _, kind, value in sorted(events):
            if kind == "key":
                key = value if value in FILES else None
            elif key is not None:
                out.append((key, int(value), no))
    return out


def check_cites(text: str, label: str = "spec") -> tuple[list[str], list[str], int, int]:
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
            warns.append(
                f"WARN cited line drifted: `{key}`:{n} ({label} line {at}) now at :{hits[0]}"
            )
        elif not hits:
            fails.append(f"FAIL needle not found: `{key}`:{n} ({label} line {at}) {needle!r}")
        else:
            fails.append(f"FAIL ambiguous needle: `{key}`:{n} ({label} line {at}) found at {hits}")
    return fails, warns, checked, unregistered


def check_rules(text: str) -> list[str]:
    """Every cited ``C-x.y`` must be declared: a line of CONSTITUTION.md opening ``**C-x.y``."""
    declared = {
        m.group(1)
        for row in lines_of(FILES["CONSTITUTION.md"])
        if (m := re.match(r"\*\*(C-\d+\.\d+)\b", row.strip()))
    }
    return [
        f"FAIL rule id not declared in CONSTITUTION.md: {rid}"
        for rid in sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
        if rid not in declared
    ]


def check_markers(text: str, derived_markers: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in MARKER.finditer(text):
        name, value = m.group(1), m.group(2)
        seen.add(name)
        if name not in derived_markers:
            out.append(f"FAIL unknown marker audit:{name}")
        elif str(derived_markers[name]) != value:
            out.append(f"FAIL marker audit:{name}={value} but derived {derived_markers[name]}")
    for name in sorted(set(derived_markers) - seen):
        out.append(
            f"FAIL marker audit:{name} missing from the spec (derived {derived_markers[name]})"
        )
    return out


def check_strings(spec: str, st: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for name, sentence in GATES.items():
        if sentence not in spec:
            out.append(f"FAIL gate missing: {name}")
    for word in INDICATOR_WORDS:
        if word not in spec:
            out.append(f"FAIL indicator word missing: {word!r}")
    for sentence in RECOVERY:
        if sentence not in spec:
            out.append(f"FAIL recovery sentence missing: {sentence!r}")
    for pattern in SUPERSEDED:
        if re.search(pattern, spec):
            out.append(f"FAIL superseded loosening sentence present: /{pattern}/")
    for no, row in enumerate(spec.split("\n"), start=1):
        low = row.lower()
        if ("node-only" in low or FORM_STATE2 in row) and not any(q in row for q in QUOTING):
            out.append(f"FAIL line {no} uses a source's word outside a quoting row")
    rg = rule_graph()
    if st["refusal_rows"] != rg["refused_pairs"]:
        out.append(
            f"FAIL the refusal table has {st['refusal_rows']} rows, ports.ts refuses "
            f"{rg['refused_pairs']} pairs"
        )
    for sentence in rg["refused"]:
        if sentence not in spec:
            out.append(f"FAIL refusal sentence missing: {sentence!r}")
    if st["reason_max_chars"] > 60:
        out.append(f"FAIL a keyed reason exceeds 60 characters ({st['reason_max_chars']})")
    if st["reason_keys"] == 0:
        out.append("FAIL no keyed reason rows found in the copy deck")
    for key, string in st["reason_rows"]:
        if not string.endswith("."):
            out.append(f"FAIL reason {key} has no full stop")
    s3 = section(spec, "## 3. ", "## 4. ")
    s4 = section(spec, "## 4. ", "## 5. ")
    for frame, word in WORD_FRAMES:
        row = next((r for r in s4.split("\n") if r.startswith(f"| `SCR-082 / {frame}`")), "")
        cells = re.split(r"(?<!\\)\|", row)
        if len(cells) < 4 or f"**{word}**" not in cells[3]:
            out.append(f"FAIL the Word cell of `SCR-082 / {frame}` lacks the verbatim {word!r}")
    s15 = section(spec, "## 15. ", "## 16. ")
    words_line = next((r for r in s15.split("\n") if r.startswith("- **Indicator words:**")), "")
    for _, word in WORD_FRAMES:
        if f'"{word}"' not in words_line:
            out.append(f"FAIL the Indicator words line of the copy deck lacks {word!r}")
    for row in (s3 + s4).split("\n"):
        if row.startswith("| `SCR-082 / ") and not ARM_CLASS.search(row):
            out.append(f"FAIL frame row {row.split('`')[1]} names no `Arm…` class")
    return out


def frame_row(body: str, frame: str) -> str:
    return next((r for r in body.split("\n") if r.startswith(f"| `SCR-082 / {frame}`")), "")


def check_frames(spec: str, st: dict[str, Any]) -> list[str]:
    """The A2 gates anchored to the frame rows that draw them (one FAIL per element per row)."""
    out: list[str] = []
    s3 = section(spec, "## 3. ", "## 4. ")
    s4 = section(spec, "## 4. ", "## 5. ")
    frames = s3 + s4
    for frame in MISMATCH_ROWS:
        row = frame_row(s4, frame)
        for label, pattern in MISMATCH_ELEMENTS:
            if not pattern.search(row):
                out.append(f"FAIL frame `SCR-082 / {frame}` does not draw {label}")
    for frame in GRAPH_ONLY_ROWS:
        if not GRAPH_ONLY_BADGE.search(frame_row(frames, frame)):
            out.append(f"FAIL frame `SCR-082 / {frame}` does not draw the `graph-only` badge")
    if S_GRAPH_ROW_TEXT not in frame_row(frames, S_GRAPH_ROW):
        out.append(f"FAIL S-graph wiring not anchored in `SCR-082 / {S_GRAPH_ROW}`")
    s_graph = S_GRAPH_CLAUSE.search(section(spec, "## 0. ", "## 1. "))
    if not s_graph or S_GRAPH_S0_TEXT not in s_graph.group(1):
        out.append("FAIL S-graph wiring not anchored in the §0 S-graph clause")
    drawn = "\n".join((section(spec, "## 0. ", "## 1. "), section(spec, "## 2. ", "## 6. "))).split(
        "\n"
    )
    for row in drawn:
        if row.startswith("| CMP-147"):
            cells = row.split(" | ")
            if len(cells) < 2 or "**no edge**" not in cells[1]:
                out.append("FAIL the CMP-147 default cell does not draw **no edge**")
            continue
        for clause in CLAUSE.split(row):
            if (
                TRIGGER.search(clause)
                and EDGE_WORD.search(clause)
                and ROOT_WORD.search(clause)
                and not NEGATED.search(clause)
            ):
                out.append(f"FAIL a trigger→root edge is drawn: {clause.strip()[:90]!r}")
    for row in frames.split("\n"):
        if row.startswith("| `SCR-082 / ") and T2_BARE.search(row):
            out.append(f"FAIL frame row {row.split('`')[1]} has a T2 without its key or notice")
    reasons = dict(st["reason_rows"])
    p0_row = frame_row(s4, "round-trip-mismatch")
    if "`rule.save.mismatch`" not in p0_row or reasons.get("rule.save.mismatch", "?") not in p0_row:
        out.append("FAIL frame `SCR-082 / round-trip-mismatch` lacks the keyed reason verbatim")
    p0 = next((r for r in s4.split("\n") if r.startswith(P0_PARAGRAPH)), "")
    if P0_LOCK not in p0:
        out.append("FAIL the P0 paragraph does not put the lock on `Save` and `Arm…`")
    armed = ARMED_T2_LIST.search(frame_row(s3, "read-only-armed"))
    if not armed or "`Save`" not in armed.group(1):
        out.append(
            "FAIL frame `SCR-082 / read-only-armed` does not list `Save` among its T2 writes"
        )
    order_set = order_actions()
    for label, first, start, end in A1_SURFACES:
        body = section(spec, start, end)
        row = next((r for r in body.split("\n") if r.startswith(first)), "")
        want = [*A1_MECHANICS, "`place_order`"]
        if first != "| 07 ":
            want += [*(f"`{a}`" for a in order_set), *A1_FULL_SET]
        missing = [w for w in dict.fromkeys(want) if w not in row]
        unpaired: list[str] = []
        if first != "| 07 ":
            clauses = A1_CLAUSE.split(row)
            for action in order_set:
                stop = A1_STOP.get(action, A1_SERVER_STOP)
                if not any(f"`{action}`" in c and all(s in c for s in stop) for c in clauses):
                    unpaired.append(action)
        if not order_set or missing or unpaired:
            detail = f"{missing or 'no set'}" if not order_set or missing else ""
            if unpaired:
                detail += f"{'; ' if detail else ''}no own stop clause for {unpaired}"
            out.append(f"FAIL A1: {label} does not draw the native stop ({detail})")
    return out


def check_hygiene(text: str, label: str) -> list[str]:
    return [
        f"FAIL {label}: forbidden pattern /{p}/ present"
        for p in FORBIDDEN
        if re.search(p, text, re.IGNORECASE)
    ]


def evaluate(spec: str) -> tuple[list[str], list[str], int, int, dict[str, Any]]:
    """Every spec gate on the text in memory: (problems, drift warnings, checked, unregistered)."""
    d = derived(spec)
    st = d["structure"]
    problems = check_markers(spec, d["markers"]) + check_rules(spec)
    problems += check_strings(spec, st) + check_frames(spec, st) + check_hygiene(spec, "spec")
    if not st["pending"]:
        problems.append("FAIL section 0 does not read PENDING")
    fails, warns, checked, unregistered = check_cites(spec)
    return problems + fails, warns, checked, unregistered, d


def check(spec_path: Path, pr_body: Path | None) -> int:
    spec = read(spec_path)
    problems, warns, checked, unregistered, d = evaluate(spec)
    if pr_body is not None:
        body = read(pr_body)
        if CLOSING.search(body):
            problems.append("FAIL PR body carries a closing keyword")
        problems += check_hygiene(body, "PR body")
        if "Refs #875" not in body or "Partial:" not in body:
            problems.append("FAIL PR body lacks `Refs #875` or the `Partial:` line")
    for w in warns:
        print(w)
    for p in problems:
        print(p)
    verdict = "FAIL" if problems else "OK"
    mx = d["matrix"]
    print(
        f"{verdict}: {len(MARKER.findall(spec))} markers, {checked} registered cites checked "
        f"({unregistered} unregistered), {len(warns)} drift warning(s), {len(problems)} "
        f"problem(s); matrix {mx['gated']} gated rows, {mx['fail']} FAIL, {mx['registered']} "
        f"registered, {mx['proposed']} PROPOSED; {d['bindings']['missing_count']} MISSING tokens"
    )
    return 1 if problems else 0


# The text review's 15 frame-level mutations of the A2 elements (M-1), the fold delta's four
# (DM-1 O03-O05, dm-4), the text approval's b-1 and the text-delta lens's M-1, run in memory by
# --self-test: name -> (old, new); each must raise exactly one new FAIL (exit 1).
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "the state-3 badge off the mismatch row",
        (
            "the diverging node outlined `color.status.danger.default` at `border.thick`, badged "
            "`mismatch` (glyph + word), **selected**; its node-list row **selected and focused** "
            "(`14`:1863)"
        ),
        (
            "the diverging node outlined `color.status.danger.default` at `border.thick`, "
            "**selected**; its node-list row **selected and focused** (`14`:1863)"
        ),
    ),
    (
        "the mismatch row drawn hue-only",
        (
            "badged `mismatch` (glyph + word), **selected**; its node-list row **selected and "
            "focused** (`14`:1863)"
        ),
        (
            "tinted `color.status.danger.subtle`, **selected**; its node-list row **selected and "
            "focused** (`14`:1863)"
        ),
    ),
    (
        "every node outlined, not the diverging one",
        "| the diverging node outlined `color.status.danger.default` at `border.thick`, badged",
        "| every node outlined `color.status.danger.default` at `border.thick`, badged",
    ),
    (
        "the node-list row no longer selected and focused",
        "its node-list row **selected and focused** (`14`:1863)",
        "its node-list row (`14`:1863)",
    ),
    (
        "the state-2 badge off `editing-graph-only`",
        "S-graph: one condition node badged `graph-only` (glyph + word) feeding",
        "S-graph: one condition node feeding",
    ),
    (
        "the state-2 badge off `round-trip-graph-only`",
        "| every graph-only node badged `graph-only` (glyph + word) from creation;",
        "| every graph-only node from creation;",
    ),
    (
        "a trigger→root edge in section 2's S-form paragraph",
        "One edge: the condition's boolean output to the action's `when` input",
        (
            "Two edges: the trigger's output to the root condition, and the condition's boolean "
            "output to the action's `when` input"
        ),
    ),
    (
        "a trigger→root edge in the CMP-147 default cell",
        "one output port (`trigger`), **no edge** (§2)",
        "one output port (`trigger`), one edge to the root condition (§2)",
    ),
    (
        "a trigger→root edge in the `editing` row",
        "| the full anatomy with S-form (§2);",
        "| the full anatomy with S-form (§2) and the trigger's edge to the root condition;",
    ),
    (
        "the lock dropped from the P0 paragraph's `Save` and `Arm…`",
        "T2 with the lock, the full labels",
        "T2 with the full labels",
    ),
    (
        "the keyed reason dropped from the mismatch row",
        (
            '**`Save` and `Arm…` T2 `rule.save.mismatch`** "Saving is blocked until the '
            'mismatch is resolved." (`E36-D02`:289)'
        ),
        "**`Save` and `Arm…` T2 `rule.save.mismatch`** (`E36-D02`:289)",
    ),
    (
        "`Save` dropped from `read-only-armed`'s T2 list",
        '"+ Add node", `Save`, each row menu\'s Connect / Rename / Delete) T2 → the notice',
        '"+ Add node", each row menu\'s Connect / Rename / Delete) T2 → the notice',
    ),
    (
        "the stop off the CMP-149 row",
        (
            "; every order-placing action shows its native stop on the card and in the "
            "inspector (A1 RULED, §1 row 14): `place_order` the non-emptiable native stop "
            "field (`E36-D02`:162) with `sl.note` beneath it and `sl.kept` on a clear attempt; "
            "`scale_in` the read-only line "
            '"Stop: the position\'s native stop, held by Bybit (exchange)."; '
            "`reverse_position`, "
            "`arm_chase_limit`, `start_iceberg_slice` and `start_twap` the read-only line "
            '"Stop: attached by the server (native SL)." (an algo only when it opens a position; '
            'a reduce-only algo reads "reduce-only, no new stop", `E33-D02`:107)'
        ),
        "",
    ),
    (
        "the stop off the Action inspector row",
        (
            "; for `place_order` the non-emptiable native stop field (`E36-D02`:162) with "
            "`sl.note` beneath it and `sl.kept` on a clear attempt; for `scale_in` the read-only "
            '"Stop: the position\'s native stop, held by Bybit (exchange)."; '
            "for `reverse_position`, "
            "`arm_chase_limit`, `start_iceberg_slice` and `start_twap` the read-only "
            '"Stop: attached by the server (native SL)." (an algo only when it opens a position; '
            'a reduce-only algo reads "reduce-only, no new stop", `E33-D02`:107) (A1)'
        ),
        "",
    ),
    (
        "the stop off board 07",
        (
            "; a `place_order` with its non-emptiable native stop field, `sl.note` beneath it "
            "and `sl.kept` on a clear attempt; a `scale_in` with the position's native stop as "
            "read-only text"
        ),
        "; a `place_order`",
    ),
    # The fold delta's DM-1 (O03-O05): one stop clause removed while every action id stays.
    (
        "the server sentence off the inspector row, the four ids kept",
        (
            "`arm_chase_limit`, `start_iceberg_slice` and `start_twap` the read-only "
            '"Stop: attached by the server (native SL)." (an algo only when it opens a position; '
            'a reduce-only algo reads "reduce-only, no new stop", `E33-D02`:107) (A1)'
        ),
        "`arm_chase_limit`, `start_iceberg_slice` and `start_twap` their order parameters (A1)",
    ),
    (
        "the `scale_in` sentence off the CMP-149 row, the id kept",
        (
            "`scale_in` the read-only line "
            '"Stop: the position\'s native stop, held by Bybit (exchange)."; '
        ),
        "`scale_in` its size line; ",
    ),
    (
        "`sl.note` off the inspector row's `place_order` clause",
        (
            "for `place_order` the non-emptiable native stop field (`E36-D02`:162) with "
            "`sl.note` beneath it and `sl.kept` on a clear attempt"
        ),
        (
            "for `place_order` the non-emptiable native stop field (`E36-D02`:162) with "
            "`sl.kept` on a clear attempt"
        ),
    ),
    # The fold delta's dm-4: a trigger→root edge written with a verb outside the old list.
    (
        "a trigger→root edge with another verb in the `editing` row",
        "| the full anatomy with S-form (§2);",
        "| the full anatomy with S-form (§2), the trigger feeding the root condition;",
    ),
    # The text approval's b-1: S-graph's second gate wired to nothing (the r2 script's orphan).
    (
        "S-graph's `any of` left without a path to the action",
        "`any of` feeds `all of` input 2 and `all of` feeds the action's `when` input",
        "`all of` feeds the action's `when` input",
    ),
    # The text-delta lens's M-1: the S-graph frame row no longer carries the §20 wiring.
    (
        "S-graph's wiring clause off the `editing-graph-only` row",
        "feeding two logic gates, wired as §20 pins it;",
        "feeding two logic gates;",
    ),
)


def self_test(spec_path: Path) -> int:
    """Run MUTATIONS on the spec in memory: each one exit 1 with one new FAIL; then exit 0."""
    spec = read(spec_path)
    before = spec_path.read_bytes() if spec_path.exists() else b""
    base, _, _, _, _ = evaluate(spec)
    ok = not base
    print(f"clean spec: rc {1 if base else 0} ({len(base)} problem(s))")
    for p in base:
        print(f"  {p}")
    for no, (name, old, new) in enumerate(MUTATIONS, start=1):
        if spec.count(old) < 1:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _, _, _, _ = evaluate(spec.replace(old, new, 1))
        fresh = [p for p in got if p not in base]
        rc = 1 if got else 0
        caught = rc == 1 and len(fresh) == 1
        ok = ok and caught
        print(
            f"mutation {no:02d} {name}: rc {rc}, {len(fresh)} new FAIL"
            f"{'' if caught else ' - NOT CAUGHT EXACTLY ONCE'}"
        )
        for p in fresh:
            print(f"  {p}")
    restored, _, _, _, _ = evaluate(spec)
    same = (spec_path.read_bytes() if spec_path.exists() else b"") == before
    ok = ok and not restored and same
    print(
        f"restore: rc {1 if restored else 0}; spec file byte-identical: {same}; "
        f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations in memory"
    )
    return 0 if ok else 1


# ------------------------------------------------------------------ report ------------------------
def report(d: dict[str, Any]) -> str:
    mx, bd, rg, km, ind, st = (
        d["matrix"],
        d["bindings"],
        d["rule_graph"],
        d["keymap"],
        d["indicators"],
        d["structure"],
    )
    out = ["# E37-D02 node-editor audit", ""]
    out.append("| element | fg | bg | role | registered | dark | light | high-contrast | verdict |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in mx["rows"]:
        out.append(
            f"| {r['element']} | {r['fg']} | {r['bg']} | {r['role']} | "
            f"{'registered' if r['registered'] else 'PROPOSED'} | {r['dark']} | {r['light']} | "
            f"{r['high-contrast']} | {r['verdict']} |"
        )
    out.append("")
    out.append(
        f"- Matrix: {mx['gated']} gated rows, {mx['fail']} FAIL, {mx['registered']} registered in "
        f"pairs.mjs, {mx['proposed']} PROPOSED."
    )
    out.append(f"- MISSING tokens ({bd['missing_count']}): {bd['missing']}")
    out.append(
        f"- rule-graph: codes {rg['error_codes']}; port types {rg['port_types']}; node types "
        f"{rg['node_types']}; node kinds {rg['node_kinds']}; refused pairs {rg['refused_pairs']} "
        f"(longest {rg['longest_refusal']} chars), allowed {rg['allowed_pairs']}; trigger node "
        f"emitted without an edge: {rg['trigger_node_emitted']}; collapsed carrier: "
        f"{rg['collapsed_carrier']}"
    )
    out.append(f"- form.py reason strings ({len(d['form']['reasons'])}): {d['form']['reasons']}")
    out.append(
        f"- keymap: {km['rules_commands']} rules.* commands; Alt+L bound {km['alt_l_bound']}x; "
        f"Ctrl+Shift+L bound {km['ctrl_shift_l_bound']}x; scoped SCR-082: {km['scr082_scoped']}"
    )
    out.append(
        f"- indicators: SCR-081 {ind['scr081']}; SCR-082 {ind['scr082']}; differing "
        f"{ind['differing']}; E36-D02 carries {ind['e36_d02_words']}; recovery sentences in "
        f"E36-D02: {ind['recovery_in_e36_d02']}"
    )
    out.append(f"- spec structure: {st}")
    return "\n".join(out)


USAGE = (
    "usage: e37_d02_node_editor_audit.py [--json] | --check SPEC [--pr-body FILE] "
    "| --self-test [SPEC]\n"
    "  --check needs the spec path (and takes the PR body path after --pr-body)"
)


def main(argv: list[str]) -> int:
    # The report holds non-ASCII text ("✓", "—"): write UTF-8 whatever the console code page is.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--self-test" in argv:
        i = argv.index("--self-test")
        return self_test(Path(argv[i + 1]) if i + 1 < len(argv) else SPEC)
    if "--check" in argv:
        if argv.index("--check") + 1 >= len(argv) or (
            "--pr-body" in argv and argv.index("--pr-body") + 1 >= len(argv)
        ):
            print(USAGE, file=sys.stderr)
            return 2
        spec_path = Path(argv[argv.index("--check") + 1])
        body = Path(argv[argv.index("--pr-body") + 1]) if "--pr-body" in argv else None
        return check(spec_path, body)
    d = derived(read(SPEC))
    if "--json" in argv:
        print(json.dumps(d, indent=2, ensure_ascii=False, default=str))
    else:
        print(report(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
