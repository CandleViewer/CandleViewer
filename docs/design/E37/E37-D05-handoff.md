# E37-D05 — Hand-off (§A–§F; the node-graph editor pack)

Components: **CMP-146** … **CMP-153**, **CMP-236** … **CMP-238**, the SCR-082 variants of **CMP-158**, **CMP-234** and **CMP-235**, and **CMP-254 NodeListOutline** (PROPOSED id). The spec is `E37-D05.md`; this file places it, states the contract, carries the copy-ready A-rows, the Storybook list with fixtures and the test hooks. Status as the spec: Draft, owner approval pending (#2701).

## §A Placement

Where each consuming story reads which part (spec section numbers).

| Consumer                                              | Reads                                                                                    |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| E37-S01 canvas, palette, ports, pointer connect       | §2; §3.1 … §3.7, §3.12 … §3.14; §4; §5; §7; §8.1 (canvas, palette, connect rows); §D; §E |
| E37-S02 node library and inspector                    | §3.2 … §3.5, §3.8; §8.1 (node, type, part rows); §9 (FZ-1 … FZ-4, FZ-10 … FZ-13)         |
| E37-S03 validation, cycles, orphans                   | §3.10; §8.1 (validation, problems, refusal rows); FI-3, FI-4, FI-10                      |
| E37-S04 round-trip switching, the indicator, the diff | §3.11; §8.1 (indicator, panel rows); §8.2; §9 (FZ-5 … FZ-9, FZ-14 … FZ-16); §10          |
| E37-S05 keyboard-equal authoring                      | §3.15; §6; §8.1 (aria, announce, outline, connect rows)                                  |
| E37-Q01 the black-box test plan                       | §2; §10; §13; §E                                                                         |
| E37-D06 design QA                                     | §13, run verbatim                                                                        |

## §B The contract table

`15`'s Props lines are the contract, amended by §C's rows; the types are E37-T01's (`PORTS`:12, :96). States, tokens and names point at the spec's sheets.

| Component | Props (`15` line; §C row)                                                                                                                                                         | Notes                                                  |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| CMP-146   | `nodes` · `edges` · `onNodesChange` · `onEdgesChange` · `onConnect(source, sourcePort, target, targetPort)` · `readOnly?` (`15`:1795; A-1, A-2)                                   | the edge carries its ports, as the shipped `GraphEdge` |
| CMP-147   | `trigger` · `timeframe?` · `position` · `selected?` (`15`:1828; A-4)                                                                                                              | one `trigger` output, no edge                          |
| CMP-148   | `metric` · `operator` · `value` · `position` · `selected?` (`15`:1837; A-5)                                                                                                       | ports, not handles                                     |
| CMP-149   | `actionType` · `params` · `position` · `selected?` (`15`:1846; A-6)                                                                                                               | the stop lines are §9's                                |
| CMP-150   | `gateType: "all_of" \| "any_of" \| "none_of" \| "n_of"` · `n?` · `inputCount` · `position` · `selected?` (`15`:1854; A-7)                                                         | `none_of`, `n_of` badged from creation                 |
| CMP-151   | `text` · `position` · `color?` (`15`:1862; A-8)                                                                                                                                   | outside the IR and its hash                            |
| CMP-152   | `source` · `target` · `selected?` · `label?` (`15`:1870; A-9)                                                                                                                     | `label` = the order index only                         |
| CMP-153   | `node` · `onChange` · `onClose` (`15`:1879; A-10)                                                                                                                                 | titled by the node's name                              |
| CMP-158   | none for the rule-editor variant (`15`:1926)                                                                                                                                      | sentence FZ-1 + FZ-2                                   |
| CMP-234   | `diagnostics` · `onFocusAnchor` (`15`:3022; A-11)                                                                                                                                 | `anchor.kind` node or edge on SCR-082                  |
| CMP-235   | `mode` · `onChange` · `lossyWarning?` · `dirty` (`15`:3032; A-12)                                                                                                                 | the constructs = the panel's rows                      |
| CMP-236   | `categories` · `query` · `onQueryChange` · `onAddNode(type, position?)` (`15`:3041; A-13)                                                                                         | each entry gains `graphOnly`, `needsNativeStop`        |
| CMP-237   | `kind` · `dataType: PortType` · `connected` · `label` · `compatible?` (`15`:3050; A-14)                                                                                           | six types incl. `trigger`                              |
| CMP-238   | `bounds` · `viewport` · `nodes` · `onNavigate` (`15`:3059; A-15)                                                                                                                  | `aria-hidden`                                          |
| CMP-254   | PROPOSED (A-16): `rule` · `selection` · `onSelect` · `onConnect` · `onDisconnect` · `onDelete` · `onRename` · `onInspect` · `onCollapse` · `onMove` · `diagnostics` · `readOnly?` | E37-S05 types them                                     |

## §C Copy-ready rows (applied only by the closing PR, after #5448 and #5495 merge; never in this PR)

One `15` commit with the `E37-D05 —` lead-in (E36-D03's form), then the `14` lines. Each Old text or anchor stands exactly once in its file at the base (G-SHEET checks); the re-pin commit re-reads them after D03's `15` rows land (D05-C3). Tokens, Storybook additions, Motion and Usage are D03 §12's rows, not repeated here.

- **A-1 → `15` CMP-146, Props** (D02 §17). After "`onConnect` · `readOnly?`." add: " **E37-D05 —** `onConnect(source, sourcePort, target, targetPort)`, as the shipped `GraphEdge` (memo C7); the region is described by the rule's plain-language sentence (E37-D02 §14)."
- **A-2 → `15` CMP-146, API sketch** (D02 §17). Old: "onConnect: (source: string, target: string) => void;". New: "onConnect: (source: string, sourcePort: string, target: string, targetPort: string) => void;".
- **A-3 → `15` CMP-146, A11y** (D04 A-14, F-15). Old: "this is the primary accessible-equivalent mechanism for the node-graph". New: "this is the primary accessible-equivalent mechanism for every construct the form represents; for graph-only constructs the node list (`Alt+L`, E37-D02 §8) is the complete non-spatial equivalent".
- **A-4 → `15` CMP-147, A11y** (D02 §17). After "`aria-label="Trigger node: on bar close, 5m"`." add: " **E37-D05 —** the header word "Check when"; one `trigger` output and no edge (the trigger is the leftmost clause, E37-D02 §5)."
- **A-5 → `15` CMP-148, Purpose and A11y** (D02 §17; D04 A-2). Old: "with input/output handles for logic-gate wiring". New: "with input and output ports for logic-gate wiring (kinds comparison · arithmetic · temporal; the `graph-only` badge on a kind outside the form subset — E37-D05)". Old: ""Connect output of condition node"". New: ""Output port, condition result, not connected" (E37-D04 A-2)".
- **A-6 → `15` CMP-149, Purpose** (D02 §17; A1). Old: "node type representing an action (place order, modify SL, flatten, etc.)." New: "node type representing an action (place order, modify SL, flatten, etc.). **E37-D05 —** a stop action carries "only tighten" and "Rules never loosen a stop."; `place_order` shows its non-emptiable native stop field and the other order-placing actions a read-only stop line (E37-D02 C19 / C20); no widening variant."
- **A-7 → `15` CMP-150, Props** (D02 §17; D02-C12). Old: "`gateType: "AND"|"OR"|"NOT"`". New: "`gateType: "all_of" | "any_of" | "none_of" | "n_of"` · `n?` (**E37-D05 —** `none_of` and `n_of` badged `graph-only` from creation; collapse via `graph_layout.collapsed`)".
- **A-8 → `15` CMP-151, Purpose** (D02 §17). Old: "free-text annotation node, non-executable, for author documentation within the graph." New: "free-text annotation node, non-executable, for author documentation within the graph. **E37-D05 —** a `graph_layout.comments` entry, outside the IR and its hash; no ports."
- **A-9 → `15` CMP-152, Props** (D02 §17). Old: "`source` · `target` · `selected?` · `label?`." New: "`source` · `target` · `selected?` · `label?`. **E37-D05 —** `label` is the order index only (port names sit on the node); the invalid-preview state is a solid danger line with the ✕ mark."
- **A-10 → `15` CMP-153, Storybook** (D02 §17; D05-C3). Old: "TriggerNodeInspector, ConditionNodeInspector, ActionNodeInspector." New: "TriggerNodeInspector, ConditionNodeInspector, ActionNodeInspector. **E37-D05 —** LogicGateNodeInspector, CommentNodeInspector, DetailsDisclosure, FocusReturn." Applied after D03's A-31, which appends its own clause to this line (`D03`:421; D05-C3).
- **A-11 → `15` CMP-234, Props** (D02 §17). After "**SCR-088's Issues segment reuses this component** (E36-D03 §5)." add: " **E37-D05 —** on SCR-082 `anchor.kind` is `"node"` or `"edge"`, populated from the compile issues' node ids by E37-S04; a port as a third kind is PROPOSED (`DANGLING_PORT`)."
- **A-12 → `15` CMP-235, A11y** (D02 §17). After "the round-trip indicator lives on CMP-145 (E36-D02 §16), not here." add: " **E37-D05 —** on SCR-082 `lossyWarning.constructs` is the "What won't round-trip" panel's rows; `dirty` prompts "Apply your changes before switching?" with Apply · Discard · Cancel; a clean switch has no confirmation."
- **A-13 → `15` CMP-236, Purpose and Props** (D02 §17). Old: "(triggers, metrics, comparators, logic gates, actions, comments)". New: "(Triggers · Conditions · Logic · Actions · Comments — memo R4; condition kinds are sub-rows)". After "`onAddNode(type, position?)`." add: " **E37-D05 —** each entry gains `graphOnly` (the badge in the palette) and `needsNativeStop` (`place_order`)."
- **A-14 → `15` CMP-237, Purpose and A11y** (D02 §17; D04 A-2). Old: "(boolean, number, price, side, action)". New: "(boolean, number, price, side, action, trigger)". Old: "("Input, boolean, not connected")". New: "("Input port, boolean, not connected"; a boolean output names its role, "condition result" or "boolean value" — E37-D04 A-2)".
- **A-15 → `15` CMP-238, A11y** (D04 A-18, F-30). Old: "the node list in CMP-153 NodeInspectorDrawer". New: "the node list (`Alt+L`, E37-D02 §8)".
- **A-16 → `15`, the new entry** (D02 §17; D02-G5; the id re-checked at the closing PR, D05-Q1). Before "### CMP-239 FreshnessMarker (E08-D04, data-confidence vocabulary)" add the block below and one blank line.

  ```text
  ### CMP-254 NodeListOutline

  - **Tier**: Organism (rule engine) · **Purpose**: **E37-D05 —** the rule's outline on SCR-082, co-equal with CMP-146 and never removed: a "Check when" row, the "Only if (all must be true)" rows nested by gate, the "Then, in order" rows, and the "Graph-only", "Not connected yet" and "Problems" groups; every canvas operation has a twin here (E37-D02 §8, E37-D04 §4). PROPOSED.
  - **Props**: PROPOSED, typed by E37-S05: `rule` · `selection` · `onSelect` · `onConnect(source, sourcePort, target, targetPort)` · `onDisconnect` · `onDelete` · `onRename` · `onInspect` · `onCollapse` · `onMove` · `diagnostics` · `readOnly?`.
  - **A11y**: a `region` "Outline" around the `role="tree"` "Rule outline — {name}", `treeitem` rows, `group` children, one roving stop, type-ahead; the row menu on `Shift+F10`; the connect-target picker lists every port, compatible first, with the refusal sentence beside each incompatible one; a tab under the canvas at 1280 × 800.
  - **Tokens**: `color.surface.raised`, `color.border.default`, `color.focus.ring`, `space.inset.sm`, `size.row.height`, `type.ui.body`, `type.ui.caption`.
  - **Storybook**: Outline, Tab1280, GraphOnlyGroup, ProblemsGroup, ConnectPicker, NotConnectedGroup.
  - **Tests**: unit, visual, axe, keyboard (every E37-D04 K row with an outline twin).
  ```

- **A-17 → `14` SCR-082, States** (D02-C8). Old: "cycle detected ("This graph has a loop — remove the connection from X to Y") ·". New: "cycle detected ("This graph has a loop — remove the connection from X to Y") · orphan or dangling ("{node} reaches no action." or "{node}: {port} input is not connected.", a warning while editing and an error on save; US-RULE-005) · conflict on save (the `412 version_conflict` dialog; US-RULE-006) ·".
- **A-18 → `14` SCR-082, the pointer line** (`T` DoD). After "- **Design (wireframe → hi-fi, E37-D02):**" (its line, and after E37-D03's A-47 and E37-D04's A-16 lines) add the line: "- **Hand-off pack (E37-D05):** [E37-D05.md](../design/E37/E37-D05.md) (E37-D05; owner approval pending) — the frame index, the spec sheets, the token map, the copy deck and its JSON twin, the Storybook fixtures and the design acceptance checklist for E37-D06."

## §D Storybook and the prop fixtures (BQ-19)

Every story renders in dark and light at compact density, under the title `RuleEngine/<Name>/<Story>`; each component a D03 motion row animates (CMP-146, CMP-147 … CMP-151, CMP-152, CMP-153) adds a `ReducedMotion` story with `data-motion="reduce"` on the root. Fixtures are named, deterministic objects; E37-S01 creates the files under `packages/fixtures` (`D03`:353). No random id, no `Date.now`: node ids are `n1`, `n2`, …, positions are fixed canvas units, every timestamp is "13:42:10 UTC" and the version is 3.

| Fixture           | Content                                                                                                                                                                                                                        |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `s-form`          | D02's S-form (`D02`:123): `n1` trigger "bar closes · 1m" at (0, 0), `n2` condition "Position is open" at (240, 0), `n3` action "Tighten stop · 2.0 × ATR 14" at (480, 0); one edge `n2` → `n3` `when`; the trigger has no edge |
| `s-graph`         | D02's S-graph (`D02`:501): `n1` trigger, `n2` shared condition, `n3` `all of`, `n4` `any of`, `n5` action; `n2` → `n3` input 1 and `n4` input 1, `n4` → `n3` input 2, `n3` → `n5` `when`; positions on a 240-unit grid         |
| `s-form-mismatch` | `s-form` with the second IR differing in the action's ATR multiplier (`D02`:501); diverging node `n3`                                                                                                                          |
| `review-60`       | the 60-node auto-layout review graph (`D03`:353)                                                                                                                                                                               |
| `tier-b-61`       | `review-60` plus one comparison, the first Tier B graph (PROPOSED id)                                                                                                                                                          |
| `over-budget-121` | the first Tier C graph, the banner frame (`D03`:353)                                                                                                                                                                           |
| `budget-200`      | the 200-node benchmark graph (`D03`:353)                                                                                                                                                                                       |
| `invalid-connect` | `s-form` with a connect from `n2`'s boolean output in flight to a number input (PROPOSED id)                                                                                                                                   |
| `cycle`           | `s-graph` with `n3` → `n4` added, the path `n3` → `n4` → `n3` (PROPOSED id)                                                                                                                                                    |
| `orphan`          | `s-form` plus `n4` condition with no connection and `n3`'s `when` cleared (PROPOSED id)                                                                                                                                        |

| Component         | Story                                                                                           | Fixture (props)                                                                      | State shown                                 |
| ----------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------- |
| CMP-146           | EmptyCanvas                                                                                     | `nodes: []`, `edges: []`                                                             | FI-1                                        |
| CMP-146           | SimpleChain                                                                                     | `s-form`                                                                             | FI-2                                        |
| CMP-146           | BranchingLogic                                                                                  | `s-graph`                                                                            | FI-12                                       |
| CMP-146           | ReadOnly                                                                                        | `s-form`, `readOnly: true`                                                           | FI-14                                       |
| CMP-146           | KeyboardNavDemo                                                                                 | `s-form`, focus on `n2`                                                              | the roving order                            |
| CMP-146           | FormViewToggleDemo                                                                              | `s-graph`, chip state 2                                                              | FI-7                                        |
| CMP-146           | TierA · TierB · TierC                                                                           | `review-60` · `tier-b-61` · `over-budget-121`                                        | Tier A, B, C                                |
| CMP-146           | Marquee · DragSnap                                                                              | `s-graph`; `s-form` with `n2` dragged                                                | selection; M-9, M-10                        |
| CMP-146           | AutoLayout · AutoLayoutReducedMotion                                                            | `review-60`                                                                          | M-13, safe and reduce                       |
| CMP-146           | ForcedColors                                                                                    | `s-graph`                                                                            | `forced-colors: active`                     |
| CMP-147           | OnBarClose · OnFill · OnTimer                                                                   | `s-form` `n1` with each trigger                                                      | N-1                                         |
| CMP-148           | Default · Connected · KeyboardConnectDemo                                                       | `s-form` `n2`, unconnected, connected, connecting                                    | N-1, PT-4                                   |
| CMP-149           | PlaceOrder · ModifySl · Flatten                                                                 | `s-form` `n3` with each action                                                       | N-1; FZ-3, FZ-10                            |
| CMP-150           | And · Or · Not                                                                                  | `s-graph` `n3` / `n4`; a `none_of` gate                                              | N-1; the `graph-only` badge                 |
| CMP-151           | Default                                                                                         | one comment at (0, 120)                                                              | N-1                                         |
| CMP-147 … CMP-151 | Hover · Dragging · SelectedAndFocused · ReadOnly · ReducedMotion                                | `s-form` (`s-graph` for CMP-150; one comment for CMP-151, without Dragging's port)   | N-2, N-6, N-5, N-10                         |
| CMP-152           | Default · Selected · Labelled                                                                   | `s-form` edge `n2` → `n3`                                                            | ED-1, ED-2, ED-4                            |
| CMP-152           | InvalidPreview · ValidPreview · Hover · Focused                                                 | `invalid-connect`; `s-form`                                                          | ED-3, ED-5, ED-6, ED-7                      |
| CMP-152           | ConnectReducedMotion · CyclePath                                                                | `s-form`; `cycle`                                                                    | M-3 reduce; ED-9                            |
| CMP-153           | TriggerNodeInspector · ConditionNodeInspector · ActionNodeInspector                             | `s-form` `n1` / `n2` / `n3`                                                          | open                                        |
| CMP-153           | LogicGateNodeInspector · CommentNodeInspector · DetailsDisclosure · FocusReturn · ReducedMotion | `s-graph` `n3`; one comment; `s-form` `n3`                                           | A-10; M-16                                  |
| CMP-158           | InRuleEditor                                                                                    | none                                                                                 | default                                     |
| CMP-234           | GraphAnchored · Valid · WithErrors · WithWarnings                                               | `cycle`; `s-form`; `orphan`                                                          | FI-4, FI-10                                 |
| CMP-235           | GraphActive · LossyWarning · DirtyUnsaved                                                       | `s-form`; `s-graph`; `s-form` edited                                                 | the four indicator states; the dirty prompt |
| CMP-236           | Default · Searching · NoResults · CategoryCollapsed · Compact · Comfortable                     | the vocabulary fixture; query "atr"; query "zzz"                                     | the four states; two densities              |
| CMP-237           | InputUnconnected · OutputConnected · IncompatibleTarget                                         | `s-form` `n3` `when`; `n2` output; `invalid-connect`                                 | PT-1, PT-5, PT-3                            |
| CMP-237           | Matrix · Dangling · Focused                                                                     | the six types × the twelve cells; `orphan`; `s-form`                                 | the 36 cells; PT-13; PT-14                  |
| CMP-238           | SmallGraph · LargeGraph · WithErrorNodes · Compact · Comfortable                                | `s-form`; `budget-200`; `budget-200` with three error nodes                          | M1, M2, M3                                  |
| CMP-254           | Outline · Tab1280 · GraphOnlyGroup · ProblemsGroup · ConnectPicker · NotConnectedGroup          | `s-graph`; `s-graph` at 1280 × 800; `s-graph`; `orphan`; `invalid-connect`; `orphan` | §3.15's states                              |

## §E Test hooks (PROPOSED)

- **Role and name first:** tests query the accessibility tree by the names of §8.1's `aria pattern` rows ("Rule graph — {name}", "Rule outline — {name}", the port pattern).
- **The deck is the fixture of every string assertion:** a test imports the key, never retypes the text; the 36 `rules.graph.connect.*` rows assert `canConnect` cell by cell.
- **State attributes:** `data-tier` (`a` · `b` · `c`) and `data-zoom-band` on CMP-146; `data-roundtrip` on the chip (the four results, `checking`, `stale`); `data-motion` read from the root only.
- **The frozen strings:** each `frozen:FZ-n` test asserts the rendered text equals §9's string byte for byte.
- **No `data-testid`** unless an element has no role.
- **Per component:** axe; its K rows (SC-1); the live-region cadence (one polite sentence per completed operation).

## §F References and the copy deck as data

- **Motion:** D03 §7 by pinned reference (spec §5). **Keyboard, script, landmarks:** D04 §4–§6 by id (spec §6). **Tiers:** D03 §8 (spec §7).
- **The copy deck as data:** `docs/design/E37/E37-D05-copy-deck.jsonl` holds every row of spec §8.1 and §9 and §8.2's cited keys as JSON Lines, one row per line: the first line carries `pack`, `version`, `base`, `fields` and §8.4's slot `samples`; each row line carries `"list": "rows"` (key, text, component, state, max_length, context, kind, status, source) or `"list": "cited"` (key, text, where). The tool fails if the twin and the tables differ; with the spec, this hand-off and the pins file absent it checks the twin alone (deck-only mode).
- **The audit:** `python3 -I docs/design/_tools/e37_d05_handoff_audit.py --check`.
