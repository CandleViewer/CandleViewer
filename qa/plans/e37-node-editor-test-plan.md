# E37 node-graph editor — black-box test plan

Ticket: E37-Q01 (issue #1066). Owner: QA. Authored 2026-11-03. Status: **authored, mapped, not
executed; peer review by a second SDET and the E37 frontend lead, the dry run and the sign-off are
pending (§16).** E37-S01 to E37-S05 and E37-T02 are open, so every case is written from the design
hand-off before the code exists and says in its Needs column what it still waits for.

Path: the ticket names none ("with the QA test-plan set"), so the plan sits flat in `qa/plans/`,
beside the E28 and E47 plans, under the QA CODEOWNER. Check script:
`qa/plans/_tools/e37_q01_plan_check.py` (§0).

Written against the observable surface only, so that it survives refactors of the stories it tests:
no case names an internal function, module or private field.

- **Stories:** `US-RULE-001`, `002`, `003`, `005` and `006` (28 Gherkin scenarios,
  `docs/plan/11-user-stories.md` §20) and the 36 scenarios of E37-S01 to E37-S05 and E37-T02
  (`docs/plan/backlog/E37.json`).
- **Screens and components:** `SCR-082` with `SCR-080`, `SCR-081`, `SCR-084`, `SCR-085` and
  `SCR-088` as entry and observation points (`docs/plan/14-screens-catalogue.md`; story map `18`
  §2.20; flow F10, `13` §10); components by name only (`CMP-146` to `CMP-153`, `157`, `158`, `234`
  to `238`, `257`).
- **REST** (`docs/plan/22-api-openapi.yaml`): `GET /rules/vocabulary`, `GET /rules/accounts`,
  `POST /rules`, `GET`, `PUT` and `DELETE /rules/{ruleId}`, `POST /rules/{ruleId}/compile`,
  `POST /rules/validate`, `GET /rules/{ruleId}/versions`,
  `GET /rules/{ruleId}/versions/{versionId}`, `PUT /rules/{ruleId}/mode` and `GET /admin/audit`. The
  one other read is the operational route `GET /metrics` (the Prometheus scrape, outside `22`'s API
  surface).
- **Design record:** E37-D02 (frames, gated controls), E37-D03, E37-D04 (keyboard map K-01 to K-25,
  screen-reader script S-01 to S-12, landmarks L-1 to L-8) and the E37-D05 hand-off pack with its
  copy deck (`docs/design/E37/`).
- **Security references, cited and not copied:** the E36 authoring abuse cases
  (`docs/security/abuse-cases/e36-rule-authoring.md`, `AC-RA-nn`) and the rule-engine threat model
  (`docs/security/threat-models/e35-rule-engine.md`); the E37 threat model (E37-X01) is not written
  yet.
- **Fixtures that exist:** the 30-rule round-trip corpus
  (`services/api/tests/fixtures/rule_corpus/`) and the five files of `tests/fixtures/e37/`.

## 0. How to use this plan

- **Audience and environment:** a QA engineer with a staging URL, the users, accounts and symbols of
  §13 and a Chromium-family browser with DevTools; no step needs source code. The demo environment
  only, with `rules.node_editor` on (`FT-FLAG`) unless a case turns it off; never a live account,
  key, real identifier or real P&L (C-13.5). No case arms a rule on live: flows end at `Arm…`, where
  the editor hands over to SCR-085 (the editor binds no arm key).
- **Case ids:** `E37-TC-<group><nn>`, stable for E37-Q02, E37-Q06 and defect reports. Groups: A
  canvas and palette (E37-S01) · B node library and inspector (E37-S02) · C validation (E37-S03) · D
  round-trip switching (E37-S04) · E keyboard authoring (E37-S05) · F layout, search and minimap
  (E37-T02) · G roles, flows and crafted requests. `[R]` after an id marks the regression subset
  E37-Q06 merges into the product pack. Boundary and negative rows are `E37-NB-nn` (§9); conflicts
  and questions are `C-nn` and `Q-nn` (§15). Never renumber; retire a case by marking it withdrawn.
- **Columns:** ID (with the title) · Covers · Preconditions (handles of §13) · Steps (numbered, the
  last an observation) · Expected (with evidence codes) · Events (§12) · Auto · Needs.
- **Covers:** `Un.k` is scenario k of `US-RULE-00n` in the order of `11` §20 (`U1`, `U2`, `U3`,
  `U5`, `U6`); `S0n.k` is scenario k of E37-S0n's Gherkin and `T02.k` of E37-T02's; §14 prints all
  64 titles. Also `FI-n` (the frame index of the hand-off pack), `K-nn` (§11), `DA-n` (E37-D06's
  checklist, not re-traced here) and `AC-RA-nn`.
- **Auto:** `Q02-1` to `Q02-10` are E37-Q02's ten specs (§14, table 2); `Q02+` a candidate beyond
  them; `Q03` the corpus and fuzz gate; `Q04` performance; `Q05` the accessibility audit; `X02`
  abuse cases; `man` manual only. The column is a proposal until E37-Q02 agrees it.
- **Needs:** what a case waits for beyond its group's story: an owed fixture or toggle (`FX-…`,
  `FT-…`), the form editor (`E36-S02`, `E36-S03`) or a rule seed that does not exist yet;
  `pending E37-S05` marks a chord or behaviour the hand-off leaves undecided. A case with an unmet
  Need is recorded `blocked-pending-dependency`, never pass or fail.
- **Quotes:** the deck's text byte for byte, then `[key · M]`, `[key · R]` or `[key · P]`: the
  deck's key and the string's status (M merged, R RULED, P PROPOSED, awaiting the owner's approval
  on #2701). A string cited from the E36-D05 deck with no status of its own carries its key alone. A
  script printed every quote from the deck and the check script compares each, so a PROPOSED string
  that moves is re-pinned in one pass. A `{slot}` stays as the deck writes it. Where the deck has no
  string the case describes the observation without a quote and a Q-row asks for the string.
- **Status and oracles:** every case is mapped, not executed (§16). Oracles, in order: the contract
  (`22`) and the seeded roles (`services/api/candleviewer/auth/rbac_seed.json`); the design record;
  `14` and `11`; the tickets' prose. Where documents disagree the case names the source it follows
  and a C-row lists the conflict; where none decides, a Q-row asks; a recorded answer is never a
  pass by default.
- **The canonical hash has no screen of its own** (the ticket's AC 4). Three proxies, in order: the
  round-trip chip's word; the hash stamp of SCR-088; `GET /rules/{ruleId}/versions`, read only,
  whose `ir_hash` is the stored hash. SCR-088 shows the IR as stored, not canonical (C-04), so two
  exports are compared byte for byte only with no edit between them. The hash covers everything
  outside the presentation block and the save metadata: name, id, `version`, `mode`, `enabled` and
  `description` included; `editor` and `graph_layout` are not covered
  (`docs/plan/27-adrs/ADR-0026-rule-ir-canonicalisation.md` rule 4). So "the same rule" means one
  stored rule, not two built alike, and a save whose hash matches a version the rule already has
  returns that version (Q-13).
- **Evidence codes:** `HAR` network export or curl transcript · `SS` screenshot · `A11Y`
  accessibility-tree snapshot or screen-reader transcript · `AUD` `GET /admin/audit` extract · `MET`
  `GET /metrics` before and after · `ANA` analytics events captured on `window` · `T` timing. The
  app dispatches each analytics event as a `CustomEvent` named `cv:analytics` on `window`, its
  `detail` holding the event's `name` and properties: in the console,
  `addEventListener("cv:analytics", e => console.log(JSON.stringify(e.detail)))`. A pressed T2
  control, an opened panel and a chosen connect target emit nothing.
- **Audit step:** every audit read is made as OWNER (a Viewer holds no `audit:read` and a Manager
  sees only its own entries), filtered by `actor_user_id`, or by `subject_type` and `subject_id`.
  Expect each event once per causing action under a name in §12's row, with the acting user and no
  secret, and record which name was written. A 403 refusal writes one row (C-2.9), but at the base
  the permission gate of the rules writes none (C-16): the first run records that as a
  `priority/p1-high` defect under §0.1. A refusal of shape before authorisation writes none (record
  one if found).
- **Clock and teardown:** `{HH:MM:SS}` strings are read against a frozen clock (`FT-CLOCK`). A case
  that changes a rule deletes it or restores its fixture; versions never rewind, so the next case
  starts from a fresh draft.
- **The check script:** `python3 -I qa/plans/_tools/e37_q01_plan_check.py --check` re-derives the
  traceability table, the connect grid and the quotes from their sources, checks the shape of the
  matrix, and checks that every quote bracket and every case, row and scenario reference resolves;
  it fails on a difference. `--self-test` mutates the plan in memory and expects each gate to catch
  its own mutation. It reads files only; run it after any edit and after a copy deck changes.
- **Out of scope:** the automation (E37-Q02), the corpus and fuzz gate (E37-Q03), the 200-node and
  500 ms measurements (E37-Q04), the accessibility audit (E37-Q05), the charters and sign-off
  (E37-Q06), the threat model and abuse cases (E37-X01, E37-X02) and design QA (E37-D06).

## 0.1 Defect conventions and triage for this epic

Severity follows `docs/plan/03-testing-strategy.md` §11.3. Epic overrides: the node editor can
change what an armed rule does, so a silent change is the worst case.

<!-- prettier-ignore -->
| Observation | Severity and handling |
| --- | --- |
| A canonical hash that changes on a switch with no edit (E37-TC-D01, E37-TC-D08); a version of an armed rule changed in place (E37-TC-D11); a write accepted from a Viewer or for an account outside the caller's grants (E37-TC-G04 to E37-TC-G07); a graph holding an error or a cycle saved as valid or armed (E37-TC-C02, E37-TC-C06, E37-TC-C13); a native-stop string softened or removed (E37-TC-B11, E37-TC-B12) | `priority/p0-critical`, a release blocker (`30` §7.3 criteria 5 and 10) |
| A 403 refusal with no audit row, or a second row for one action (C-2.9) | `priority/p1-high` |
| A control or chord that changes a read-only graph (E37-TC-A16, E37-TC-E16) | `priority/p1-high` |
| An operation reachable only on the canvas, or a keyboard path that cannot finish (E37-TC-E03, E37-TC-E06 to E37-TC-E10) | `priority/p1-high` (the A11y gate of `30` §7.4); a missing announcement `priority/p2-normal` |
| A refused connection without its sentence, or a deck string that differs from its quote | `priority/p2-normal`; `priority/p1-high` for a frozen string (the fourteen of §12's note) |
| A budget in §0.3 missed | `priority/p2-normal`; `priority/p1-high` when it blocks the flow |
| Copy that differs from the story or the hand-off without misstating a limit or a reason | `priority/p3-low`; `priority/p2-normal` when it misstates one |

**Every report** uses `.github/ISSUE_TEMPLATE/bug_report.yml` and names the case id and Covers code,
the numbered steps, the environment (build sha, flags, toggles), the redacted request and response,
expected (with the source followed) against actual, and the evidence codes. A defect against a §15
row cites it and is triaged as needs-clarification until it settles. The QA owner of E37-Q06 triages
within the SLA of `03` §11.3; a hash change, a mutated armed version or an accepted Viewer write
goes the same day to the Owner and the security engineer of E37-X02.

## 0.2 Entry and exit criteria

<!-- prettier-ignore -->
| Id | Entry criterion (before a group is executed) | Checked by |
| --- | --- | --- |
| EN-1 | The implementing story is merged and In Test (`03` §16) on a build with CI green, and the case's Needs are met | the ticket status and the build sha in §16 |
| EN-2 | `rules.node_editor` is on in staging and every route the group calls answers: not `501`, not the plain `404` of a route not mounted | a probe call per route |
| EN-3 | The users, accounts and symbols of §13.1 and §13.2 exist in staging and the corpus rules load | the seed's run log in §16 (Q-10) |
| EN-4 | Every fixture and toggle a case's Needs names exists; a case without it is recorded `blocked-pending-dependency` | §16 rows |
| EN-5 | The copy decks are at the head this plan quotes: the check script passes, and the plan is peer-reviewed (§16) | its output and the §16 boxes |

<!-- prettier-ignore -->
| Id | Exit criterion (before E37 is Done) | Checked by |
| --- | --- | --- |
| EX-1 | Every scenario of §14 has an executed case with pass or fail recorded on its story (`03` §16); zero Must scenarios uncovered | §14 and the story comments |
| EX-2 | Zero open `priority/p0-critical` or `priority/p1-high` defects from this plan | the board's E37 bug view |
| EX-3 | The `[R]` cases pass on the release candidate | E37-Q06's regression pack |
| EX-4 | Every boundary and negative row (§9) executed, or named catalogue only with its reason; each refusal's audit row asserted | E37-Q02, E37-X02 and E37-Q06 reports |
| EX-5 | The five assertions of §0.3 measured within budget | E37-Q04's report |
| EX-6 | The 25 rows of §11 walked, each pass or fail, with no operation reachable only on the canvas | §11's result column; E37-Q05's audit |
| EX-7 | Each §15 row settled by its owner (a contract or docs change, or a ruling) or accepted with a named owner and an expiry | the change or ruling, linked from the row |
| EX-8 | A QA sign-off comment on E37 and on each story, pass or fail per §14 scenario | the issues |

## 0.3 Perceived-performance assertions

A missed budget is a functional defect (§0.1). Each assertion names the ticket that measures it;
this plan supplies the graphs and the observation.

<!-- prettier-ignore -->
| Id | Budget | Source | Assertion | Measured by | Cases |
| --- | --- | --- | --- | --- | --- |
| P-1 | Compile and diff ≤ 500 ms p95 for a 100-node graph | `14` SCR-082 Performance | on a save and on a mode switch only, never on a keystroke, a drag or a pan: the HAR shows no compile call during editing | E37-Q04 | E37-TC-D03, E37-TC-F06 |
| P-2 | 200 nodes at 60 fps | `14` SCR-082 Performance | pan and zoom on the 200-node graph with the minimap shown | E37-Q04 | E37-TC-F06 |
| P-3 | Auto-layout on 200 nodes | E37-T02 (large-graph budget) | the main thread is not blocked beyond 100 ms and the transition completes within 400 ms; the reduced-motion variant repositions without transit | E37-Q04 | E37-TC-F06 |
| P-4 | A zoom change re-lays out nothing | E37-D02 §10 constraint | node text wraps at the same places at 100 % and at 50 %; the zoom band only toggles visibility | E37-Q04 | E37-TC-A09 |
| P-5 | Soft cap above 120 nodes is a warning, not a block | `14` SCR-082 Performance | at 121 nodes the banner shows and every operation still works | E37-Q04 | E37-TC-F05 |

## 1. Group A — Canvas and palette (US-RULE-005, the pointer half; E37-S01)

Screens SCR-082, with SCR-080 and SCR-081 as entry points. Endpoints `GET /rules/vocabulary`,
`POST /rules/{ruleId}/compile`, `PUT /rules/{ruleId}` (with `If-Match`),
`GET /rules/{ruleId}/versions`. Every case is mapped, not executed, and waits for E37-S01 (canvas,
palette, ports and pointer connect). "The S-form rule" is E37-D02 §2's three nodes: the trigger "bar
closes · 1m", the condition "Position is open" and the action "Tighten stop · 2.0 × ATR 14", one
edge from the condition to the action's `when` input.

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-A01 Empty canvas and an empty save | E37-NB-08; FI-1 | OWNER; `FT-FLAG` on; a new rule started at `/rules/new` with Graph chosen (flow F10), nothing added | 1. Open the new rule's graph route. 2. Read the canvas, the outline's rows and the action bar. 3. Focus `Save` and press `Enter`; focus `Arm…` and press `Enter`. 4. Read `Validate` and `Simulate`. | 1: "Start from a trigger" [rules.graph.hint.empty · M] centred on the canvas with "Pick one in the palette, or press Enter on it in the node list." [rules.graph.hint.empty_more · P]; the palette open on Triggers; no round-trip chip yet (Q-05). 2: the outline's first row reads "Check when — no trigger yet" [rules.graph.outline.no_trigger · P]. 3: `Save` keeps its full label and `aria-disabled="true"` (the validity look, never T2) with the reason "A rule needs at least one action — add one to save." [rules.editor.validation.no_action]; `Arm…` likewise with "Fix the errors first." [rules.editor.validity.arm]; both stay focusable and a press sends no request. 4: both are enabled. SS, A11Y, HAR. | none | Q02+ | — |
| E37-TC-A02 Palette categories and search | U5.1 | OWNER; an empty draft; the vocabulary served (`GET /rules/vocabulary` answers 200) | 1. Open the graph route and read the palette. 2. Type `atr` in the search field. 3. Clear the field, collapse the Actions category and reload the page. | 1: region "Palette" [rules.graph.aria.region_palette · P] holds the listbox "Node types" [rules.graph.aria.palette · P] and the field "Search node types" [rules.graph.aria.palette_search · P]; five categories, Triggers first: "Triggers" [rules.graph.palette.cat_triggers · P], "Conditions" [rules.graph.palette.cat_conditions · P], "Logic" [rules.graph.palette.cat_logic · P], "Actions" [rules.graph.palette.cat_actions · P] and "Comments" [rules.graph.palette.cat_comments · P]; each header reads "{category} ({n})" [rules.graph.palette.category_count · P] with the counts of E37-TC-B01. 2: entries across categories narrow to the matches and the count is announced once, politely: "{n} node types match" [rules.graph.announce.search_count · P]. 3: the collapsed state holds for the session (a per-viewer convenience; record whether it survives the reload). SS, A11Y. | none | Q02+ | — |
| E37-TC-A03 Palette with no results | S01 scope; E37-D02 §7 | as E37-TC-A02 | 1. Type `zzz` in the palette's search field. 2. Activate the clear control by keyboard. | 1: "No node types match '{query}'." [rules.graph.palette.no_results · P] with `{query}` = `zzz`, and the categories stay collapsed below it. 2: the control reads "Clear search" [rules.graph.palette.clear · P]; the full list returns with the field empty. SS, A11Y. | none | Q02+ | — |
| E37-TC-A04 [R] Author a minimal graph by pointer | U5.1, S01.1 | OWNER; ACC-1; SYM-REC; a new draft rule at `/rules/new` with Graph chosen | 1. Drag a trigger (bar closes, 1m), a comparison condition (set in the inspector to the metric `position_open`, "is true") and the vocabulary's stop-tightening action (2.0 × ATR 14, only tighten) from the palette onto the canvas: the S-form rule (`FX-S-FORM` is the seeded form of the same rule). 2. Connect the condition's output port to the action's `when` input; the trigger carries no edge. 3. Press `Validate`. 4. Press `Save`. 5. `GET /rules/{ruleId}/versions`, then `GET /rules/{ruleId}/versions/{versionId}` for the newest. | 1 and 2: three nodes and one edge render, the edge ending on the ports named in step 2. 3: the strip reads "No problems — 0 errors · 0 warnings." [rules.graph.problems.none · P] with the footer "errors: 0 · warnings: 0". 4: the HAR shows `POST /rules/{ruleId}/compile` and then `PUT /rules/{ruleId}` with `If-Match`, the PUT's `ir` equal to the compile response's; the header reads "v{n} · Last saved {HH:MM:SS} UTC" [rules.editor.header.saved], the chip "Round-trips ✓" [rules.editor.roundtrip.identical] and the live region "Saved as version {n}." [rules.graph.announce.saved · P]. 5: the list names a new version with an `ir_hash`; the version's own IR carries `editor` `graph`. FI-2. HAR, SS, ANA, AUD. | `rule.graph_node_added` ×3, `rule.graph_edge_added`, `rule.graph_saved`, `rule.roundtrip_verified` `{identical}` | Q02-1 | — |
| E37-TC-A05 Insert without dragging | S01.3 | OWNER; a draft holding the trigger and the condition "Position is open" | 1. Select the condition. 2. Focus the palette entry for the stop-tightening action and press `Enter`. 3. Select the trigger. 4. Focus a palette entry under Conditions and press `Enter`. | 2: the action is inserted, connected to the condition's free compatible port, becomes the selection and takes focus; the live region says "Added {node} after {selection}" [rules.graph.announce.added_after · P] (`{node}` the action, `{selection}` the condition). 4: a trigger output accepts no pair, so the new condition is inserted unconnected, placed right of the selection, takes focus, and the live region says "Added {node} — not connected" [rules.graph.announce.added · P]. No request is sent. HAR, A11Y. | `rule.graph_node_added` ×2 | Q02-2 | — |
| E37-TC-A06 [R] The connect matrix | U5.2, S01.2 | OWNER; an empty draft | 1. Add one node of every kind the palette offers: a trigger, comparison, arithmetic and temporal conditions, a logic gate and an action. 2. For every pair of an output port and an input port a pointer can reach, drag from the output and release on the input, noting the two port types. 3. Fill §10's grid with `R` (reached) or `U` (no output or no input of that type exists on any node). | 2: the seven compatible pairs of §10 show the halo while dragging and connect, one edge each; every other reached pair shows the ✕ mark, a solid danger preview (never dashed) and, at the target, the sentence of §10's cell verbatim; no edge is made. 3: the `U` cells are asserted by CMP-237's Matrix story, not here (Q-14). No sentence is T2. SS, HAR. | `rule.graph_connect_rejected` `{fromType, toType}` per refused drop | Q02-5 | — |
| E37-TC-A07 [R] A boolean output onto a number input | U5.2, S01.2 | OWNER; a draft holding "Position is open" (a boolean output) and a comparison condition with a number input | 1. (`FX-INVALID-CONNECT` names this editor state.) Drag from the boolean output of "Position is open" toward the number input and hold over it. 2. Release. 3. Read the target port, the inline message and the action bar. | 1: compatible targets take the halo; over the number input the preview is a solid danger line ending in the ✕ mark. 2: no edge is made and the source stays. 3: the target port shows the incompatible state and the sentence "A true or false result can't be used as a number." [rules.graph.connect.boolean.number · P] sits inline at the target (4 s or until the next pointer move) and is announced once, politely; `Save` and `Arm…` keep the class they had (never T2). FI-3. SS, A11Y. | `rule.graph_connect_rejected` `{boolean, number}` | Q02-5 | — |
| E37-TC-A08 The other refusals | U5.2 | OWNER; a draft holding a trigger, two comparison conditions, a logic gate "all of" and an action | 1. Connect the first condition to the action's `when` input, then drag the second condition's output onto the same input. 2. Drag from the gate's output onto the gate's own input. 3. Connect the first condition to a gate input, then drag from the same output onto the same input again. | 1: refused, "This input already has a connection." [rules.graph.refusal.occupied · P] at the target. 2: refused, "A node can't connect to itself." [rules.graph.refusal.self_loop · P] (the self-loop sentence, not E37-TC-C02's loop sentence). 3: the first connects; the second is refused, "Those ports are already connected." [rules.graph.refusal.duplicate · P]. Each refusal is announced once and none is T2. The refusals with no screen path are in E37-NB-33. SS, HAR. | `rule.graph_connect_rejected` per refusal | Q02+ | — |
| E37-TC-A09 Pan, zoom and fit | S01 scope; DA-14 | OWNER; the S-form rule with the minimap shown | 1. Pan with `Space` and drag, then with the wheel. 2. Zoom with the wheel, then with the controls "Zoom out" [rules.graph.canvas.zoom_out · P], "Zoom in" [rules.graph.canvas.zoom_in · P] and "Fit to screen" [rules.graph.canvas.fit · P]. 3. Read the readout at 100 %, 60 % and 40 %. 4. Press `Ctrl+0`. 5. Compare screenshots of one node at 100 % and 50 %. | 1: the canvas pans and the minimap's viewport rectangle follows. 2 and 3: the readout is the text swap "{zoom}%" [rules.graph.canvas.zoom_readout · P] (for example 100%), never announced; the zoom bands (75 % and above, 50 to 74 %, below 50 %) only toggle visibility (E37-D05 §7). 4: `Ctrl+0` resets the canvas zoom (E37-S01's scope; its clash with the browser's page-zoom reset is E37-D04's C-4). 5: the node's text wraps at the same places at both zooms (P-4). SS, T. | none | man | — |
| E37-TC-A10 Select, multi-select and delete | S01 scope | OWNER; a draft holding the S-form rule and one unconnected comparison condition | 1. Click a node; marquee-select two; press `Ctrl+A`. 2. Select the connected condition and press `Del`; choose Cancel. 3. Press `Del` again and confirm. 4. Select the unconnected condition and press `Del`. 5. Select an edge, read its menu and delete it. | 1: the selection follows the pointer and `Ctrl+A` selects every node. 2: a dialog titled "Delete {node} and its {n} connections?" [rules.graph.dialog.delete_title · P] (`{node}` the condition, `{n}` its connections) with "Delete" [rules.graph.dialog.delete · P] and "Cancel" [rules.graph.dialog.cancel · P]; Cancel changes nothing. 3: the node and its edges go; the live region says "Deleted {node} and {n} connections" [rules.graph.announce.deleted · P], or "Deleted {node} and 1 connection" [rules.graph.announce.deleted_one · P] for one connection. 4: the shipped keymap marks `rules.delete` as always confirming while E37-D02 §3 confirms only a node with connections (C-08): follow the keymap and record whether the dialog shows; a silent delete is not a pass until C-08 settles, and when it deletes the live region says "Deleted {node}" [rules.graph.announce.deleted_none · P]. 5: the affordance "Delete connection" [rules.graph.edge.delete · M] removes the edge. SS, A11Y. | none | Q02+ | pending E37-S05 |
| E37-TC-A11 Undo and redo | U5.6; S01 scope | OWNER; an empty draft | 1. Add a node, add a second, connect them, move the first, delete the second. 2. Press `Ctrl+Z` five times, reading the canvas after each. 3. Redo with `Ctrl+Y`, then with `Ctrl+Shift+Z`. | 2: the operations unwind in reverse: the delete, the move, the connect, then each add; each undo is announced once, "Undid {operation}" [rules.graph.announce.undid · P] with `{operation}` the operation's name; a deleted node returns with its edges. 3: redo replays forward in the same order; the chords are PROPOSED in the hand-off (`rules.undo` and `rules.redo` unregistered, C-09), so record which one works and mark the other `blocked`. A11Y. | none | Q02+ | pending E37-S05 |
| E37-TC-A12 Leaving the editor with unsaved edits | U6.2 | OWNER; a saved draft open in the graph editor | 1. Move a node (an unsaved edit). 2. Navigate to `/rules` through the app's navigation. 3. Choose Cancel. 4. Repeat step 2 and choose Discard. 5. Repeat the edit and step 2 and choose Apply. 6. `GET /rules/{ruleId}/versions`. | 2: a dialog titled "Apply your changes before switching?" [rules.graph.dialog.switch_title · P] with "Apply" [rules.graph.dialog.apply · P], "Discard" [rules.graph.dialog.discard · P] and "Cancel" [rules.graph.dialog.cancel · P] (the deck's one dirty prompt, written for a switch; Q-15 asks whether a route change reuses it). 3: Cancel stays with the edit. 4: Discard leaves, nothing saved. 5: Apply saves and leaves; the move is presentation, so the newest `ir_hash` equals the one before it (Q-13 records whether a version row is written). HAR, SS. | `rule.graph_saved` on Apply only | Q02+ | — |
| E37-TC-A13 [R] Two graph tabs, one rule | S01.5 | OWNER; a saved draft at version n open in tab 1 and tab 2 | 1. In tab 2 change the condition's threshold and press `Save` (version n + 1). 2. In tab 1 change the same rule differently and press `Save`. 3. Read the dialog; choose Cancel; press `Save` again; choose Reload. 4. `GET /rules/{ruleId}/versions`. | 2: the HAR shows `PUT /rules/{ruleId}` with `If-Match` n answered `412 version_conflict`. 3: a modal dialog "Someone saved version {n} from the {form} editor in another session. Reload to see it, then re-apply your changes." [rules.graph.dialog.conflict · P] (`{n}` = n + 1; `{form}` = graph, the other session having saved from the graph editor) with Reload and Cancel only, no overwrite and no third choice; Cancel keeps tab 1's edits unsaved; Reload shows version n + 1 and drops them. 4: exactly one new version, tab 2's. FI-11. HAR, SS, AUD. | `rule.graph_saved` ×1 (tab 2) | Q02-8 | — |
| E37-TC-A14 [R] Feature flag off | S01.6 | OWNER; RULE-FORM-1 saved; `FT-FLAG` off | 1. Open `/rules` and the row menu of RULE-FORM-1. 2. Open the rule in the form editor and read its mode toggle. 3. Navigate directly to `/rules/{ruleId}/graph`. 4. Edit and save the rule in the form editor. | 1 and 2: no graph entry in the row menu and no Graph segment in the toggle; where a note shows it reads "The node editor is off for this workspace." [rules.list.note.node_editor] (an absence with a note, never T2). 3: the graph route renders no editor and no rule content. 4: the form editor saves as usual. SS, HAR. | none | Q02+ | E36-S02 |
| E37-TC-A15 [R] Engine and vocabulary unavailable | E37-NB-11; FI-13 | OWNER; the S-form rule saved as a draft and open in the graph editor; `FT-VOCAB` ready (manual stand-in: stop the staging engine) | 1. With the editor open make `GET /rules/vocabulary` answer 503 (`FT-VOCAB`) and reload. 2. Read the area above the header, the palette, an inspector's pickers and the round-trip chip. 3. Press `Validate`, `Simulate`, `Save` and `Arm…`. 4. Restore the engine and reload. | 2: a danger banner above the header, the one notice, reads "The rule engine is not running — armed rules are not evaluating. Your native stops are held by the exchange and are unaffected." [rules.editor.banner.engine_down · P]; palette entries, the inspector's pickers and "+ Add node" are T2 pointing at the banner; existing nodes stay readable; the chip reads "Not verified" [rules.editor.roundtrip.unverified]. 3: `Validate`, `Simulate`, `Save` and `Arm…` are T2 pointing at the banner (a save answers `503` while the engine is down and the edits stay in the graph, unsaved); `Discard changes` stays enabled. 4: everything returns with the edits intact. FI-13. SS, A11Y, HAR. | none | Q02-9 | FT-VOCAB |
| E37-TC-A16 [R] An armed rule, viewed | U6.6; FI-14 | OWNER; RULE-ARMED-1 armed on demo | 1. Open `/rules/{ruleId}/graph`. 2. Read the header pill, the line under the header and a node. 3. Attempt every write: a palette entry, "+ Add node", an inspector field, a row menu's Connect, Rename and Delete, and `Save`. 4. Read `Arm…`. | 1 and 2: the pill reads "ARMED-DEMO" [rules.list.status.armed_demo]; nodes show values as text, ports are inert, the region carries `aria-readonly`, nothing is dimmed; the one notice reads "This version is armed and cannot change under the engine. Disarm to edit, or edit as a new draft version." [rules.editor.armed.notice] with "Disarm to edit" [rules.editor.armed.disarm] and "Edit as a new draft version" [rules.editor.armed.new_version]. 3: every write is T2 and points at the notice (no per-control string); nothing changes and the HAR shows no request. 4: `Arm…` is replaced by `Disarm`, enabled. FI-14. SS, A11Y, HAR. | none | Q02+ | — |

## 2. Group B — Node library and inspector (US-RULE-002, US-RULE-003; E37-S02)

Screens SCR-082 and the inspector drawer (CMP-153). Endpoint `GET /rules/vocabulary` is the oracle
for what is offered. Every case is mapped, not executed, and waits for E37-S02 (node types, the
vocabulary on canvas, the inspector).

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-B01 [R] The whole vocabulary is reachable | S02.1, U2.1, U3.1 | OWNER; MGR-A; `GET /rules/vocabulary` saved as the oracle | 1. As OWNER `curl` `GET /rules/vocabulary` and list every trigger, metric and action id with its unit and description. 2. Open a draft in the graph editor and read every palette category and the metric picker (seven categories). 3. For each id of step 1 find its palette entry or picker option and record its unit and description. 4. Compare the counts per category. 5. Find each metric family US-RULE-002 "Catalogue" names and each action US-RULE-003 "Catalogue" names in the response; record any the response lacks. 6. Repeat steps 1 to 4 as MGR-A. | 3 and 4: every metric and every action of the response is reachable with its unit and description and the counts equal; nothing the response lacks is offered and nothing is hard-coded: MGR-A's palette follows MGR-A's response (the vocabulary varies by the caller's permissions). 5: a family or action the story names and the response lacks is recorded against E35, whose catalogue is the oracle. HAR, SS. | none | Q02+ | — |
| E37-TC-B02 The five node types | U5.1 | OWNER; an empty draft | 1. Add one node of each type: a trigger, a condition, an action, a logic gate and a comment. 2. Read each node's header word and its accessible name in the accessibility tree. | 2: the header words are "Trigger" [rules.graph.type.trigger · M], "Condition" [rules.graph.type.condition · M], "Action" [rules.graph.type.action · M], "Logic gate" [rules.graph.type.logic_gate · M] and "Comment" [rules.graph.type.comment · M]; the trigger's header word is "Check when" [rules.graph.outline.check_when · M]; each accessible name follows "{Type} node: {sentence fragment}" [rules.graph.aria.node · P] (`{Type}` the header word, then the node's sentence fragment, never an id or an operator symbol). The trigger has one `trigger` output and no input; the comment has no ports. A11Y, SS. | none | Q02+ | — |
| E37-TC-B03 Each trigger type | S02 scope | OWNER; `GET /rules/vocabulary` saved | 1. Read the served vocabulary's triggers (E37-D02 §9 counts thirteen). 2. On a fresh draft, for each trigger: insert it from the palette and open its inspector. 3. Set its required parameter (the timeframe of a bar-close trigger, the interval of a timer) and save. | 2: every served trigger inserts as the single "Check when" node and the inspector offers the trigger picker with each trigger's description. 3: the required parameter is asked for and, once set, the draft saves with the stored trigger carrying it (`GET /rules/{ruleId}`). HAR, SS. | `rule.graph_node_added` per insert | man | — |
| E37-TC-B04 A second trigger is refused | S02.5; E37-NB-01 | OWNER; a draft holding the trigger "bar closes · 1m" | 1. Read the palette's Triggers category. 2. Try to add a second trigger by drag and by `Enter` on a trigger entry, wherever the palette offers one. 3. Read the canvas, the outline and the Problems region. | 2: E37-D02 §7 draws the second trigger entry as absent, not locked, while S02.5 asks for a refusal that names the existing trigger; record which the build does: an absent entry, a refusal message or both (the deck has no string for the message: Q-01). 3: either way the graph keeps one trigger and stays valid, with no error and no second "Check when" row. SS, A11Y. | none | Q02+ | — |
| E37-TC-B05 A condition node | U2.1 | OWNER; a draft holding a trigger | 1. Add a condition. 2. Open its inspector; choose the metric `atr` (n 14) in the metric picker, the operator "is above" and the value 2.0. 3. Read the node and its output port. | 2: the picker (seven categories) lists metrics with their units; the node reads "ATR 14 is above 2.0" with the unit beside the value. 3: the output port is boolean and its role word is "condition result" [rules.graph.port.condition_result · P]; its accessible name follows "{Input \| Output} port, {type}, {connected to {node} \| not connected}" [rules.graph.aria.port · P]. Comparison, arithmetic and temporal conditions are all `condition` nodes; one outside the form subset carries the badge of E37-TC-B08. SS, A11Y. | `rule.graph_node_added` | Q02+ | — |
| E37-TC-B06 [R] Estimated metrics are text | S02.2, U2.3 | OWNER; ACC-1; SYM-REC | 1. For each of `iceberg_present_at_level`, `distance_to_liquidity_cluster`, `in_stop_hunt_zone`, `stop_run_detected` and `market_regime`: add a condition and select the metric. 2. Read the node, the picker option and the rule's plain-language sentence (the canvas region's description). 3. Take a greyscale screenshot and turn on forced colours. | 2: "(estimated)" appears as text on the node, as a tag in the picker option and in the rule's sentence. 3: the text is still there in greyscale and in forced colours: it is never a colour or an icon alone. A11Y, SS. | `rule.graph_estimated_metric_used` `{metric}` | Q02+ | — |
| E37-TC-B07 An unavailable metric is explained | S02.3, U2.2 | OWNER; SYM-NOREC (a symbol with no recording) | 1. Open a draft whose symbol is SYM-NOREC. 2. Call `GET /rules/vocabulary` for that symbol. 3. Open a condition's picker and find a metric that needs recorded data. 4. Activate its start-recording action. | 2: the metrics that need recorded data are served `available: false` with the recorder action that would satisfy them. 3: the picker shows the option disabled, names the missing dependency and offers a one-click start-recording action; the option cannot be picked. 4: a recording starts for the symbol (observe it on the recording screen or its status route) and the option becomes available. HAR, SS. | none | man | — |
| E37-TC-B08 Logic gates | U5.1, U5.7 | OWNER; an empty draft | 1. Add a gate of each kind from the palette. 2. On each, press the add-input control twice. 3. For "at least n of" set n to 2. 4. Read the palette entries and the nodes for badges and open the outline's Graph-only group. | 1: the gate verbs read "all of" [rules.graph.node.gate_all_of · P], "any of" [rules.graph.node.gate_any_of · P], "none of" [rules.graph.node.gate_none_of · P] and "at least {n} of" [rules.graph.node.gate_n_of · P] (`{n}` = 2). 2: the control reads "+ input" [rules.graph.node.add_input · P] and adds one input port per press. 4: "none of" and "at least n of" carry the badge "graph-only" [rules.graph.badge.graph_only · M] in the palette already and on the node from creation (glyph and word) and appear in the outline's "Graph-only" [rules.graph.outline.group_graph_only · P] group; "all of" and "any of" carry none. SS, A11Y. | `rule.graph_node_added` ×4 | Q02+ | — |
| E37-TC-B09 Action scope is shown | U3.2 | OWNER; MGR-A; ACC-1; SYM-REC | 1. Add each action of a sample (a stop action, a partial close, a place-order action, a notification and `flatten_all_positions`) and open its inspector. 2. Read the node, the inspector and the rule's plain-language sentence. | 2: each action node and the sentence state the accounts and positions the action may affect (the sentence ends with the "Acts on …" clause of E37-D02 §2: account, symbol and environment); the scope is the rule's and an action never offers an account outside the caller's grants. SS, A11Y. | none | man | — |
| E37-TC-B10 `flatten_all_positions` is armed only with its acknowledgement | E37-NB-05 | OWNER; RULE-ARMABLE-1 | 1. In a draft of ACC-1 holding a trigger and a condition (as E37-TC-B11), add the `flatten_all_positions` action, connect it to the condition's output and open its inspector. 2. With the box unticked press `Save`, then read `Arm…`. 3. Tick the box and read `Arm…`. 4. Press `Arm…`, read SCR-085's arm step and cancel it. 5. As OWNER `PUT /rules/{ruleId}/mode` to armed on RULE-ARMABLE-1 with a fresh `Idempotency-Key` and no `acknowledge_flatten_all`. 6. Read `GET /rules/{ruleId}` and `GET /admin/audit`. | 1: the inspector carries the box "I understand this flattens every open position on the accounts in scope." [rules.editor.flatten.ack · R]. 2: `Save` is unaffected (the HAR shows the `PUT` and a new version: E36-D02 puts the acknowledgement in the arm request, not at save, C-17); `Arm…` takes the validity look with the reason "Tick ‘I understand’ on Flatten all positions first." [rules.editor.validity.flatten], never T2. 3: `Arm…` is enabled (T1 into SCR-085 for the OWNER). 4: the client may hold the key until the owner of `22` decides (E35-D02 D02-CG1); the observation is that SCR-085 opens and the editor arms nothing. 5: 422 `acknowledgement_required`, the last arming check, so the rule is armable and every earlier check passes. 6: the rule is not armed and one `rule.mode_refused` row names the code. HAR, SS, AUD. | `rule.mode_refused` | Q02+ | RULE-ARMABLE-1 |
| E37-TC-B11 [R] The stop strings, byte for byte | S02 scope; FZ-1, FZ-6 to FZ-9 | OWNER; a draft holding a trigger and a condition | 1. Add the vocabulary's stop-tightening action and read it. 2. Add `place_order`; read its palette entry and its stop field; try to empty the field with `Delete`, `Backspace`, select-all and type nothing, and the clear glyph. 3. Add `scale_in`, then each of `reverse_position`, `arm_chase_limit`, `start_iceberg_slice` and `start_twap`; read each node and inspector. 4. Search the palette and the action picker for any action that widens a stop. | 1: the node shows "only tighten" [rules.graph.node.only_tighten · M] and the line "Rules never loosen a stop." [rules.editor.stop.never_loosen · R]. 2: the entry's second line reads "needs a native stop" [rules.graph.palette.needs_stop · P]; every clear attempt leaves the value and shows "Kept at 63,900.0 — every position keeps a native stop. Move it instead." [rules.editor.stop.kept · M] (63,900.0 is the instance: the stop's own value fills it) beside the field's note; the field stays editable to tighten. 3: `scale_in` shows "Stop: the position's native stop, held by Bybit (exchange)." [rules.graph.node.stop_exchange · P]; the other four show "Stop: attached by the server (native SL)." [rules.graph.node.stop_server · P] when the action opens a position (a reduce-only algo shows a "reduce-only, no new stop" line instead, which the deck does not carry). 4: none offers to widen a stop. Each string is compared byte for byte with its quote, copied from the accessibility tree and never retyped. A11Y, SS. | none | Q02+ | — |
| E37-TC-B12 [R] The native-stop notice cannot be dismissed | S02 scope | OWNER; MGR-A; VIEWER-1; RULE-ARMED-1 | 1. Open an empty draft and read the notice above the action bar. 2. Walk the editor through its states: empty, editing, a refused connection, a cycle, a graph-only badge, the mismatch frame (`FT-MISMATCH`), unavailable vocabulary (`FT-VOCAB`), over budget and an armed rule. 3. Repeat step 1 as MGR-A, and as VIEWER-1 on a rule it owns. 4. Look for a dismiss control and press `Esc` over the notice. | 1 and 2: in every state the notice is present, `role="note"` (never a stop), and reads "Every position keeps a native stop — you can move it, not delete it." [rules.editor.notice.native_stop_1 · M] then "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app." [rules.editor.notice.native_stop_2 · P]. 3: the same for every role. 4: there is no dismiss control and `Esc` does not remove it. A11Y, SS. | none | Q02+ | FT-MISMATCH, FT-VOCAB |
| E37-TC-B13 [R] A forbidden action is not silently offered | S02.4, U3.3 | MGR-SIM (ACC-1, no `orders:write`); MGR-A (ACC-1, ACC-2, `orders:write`); ACC-2 | 1. As MGR-SIM open a draft scoped to ACC-1 and read every action entry in the palette and the picker. 2. Read each order-placing action's entry (`place_order`, `scale_in`, `reverse_position`, `arm_chase_limit`, `start_iceberg_slice`, `start_twap`). 3. Open the scope selector and read `GET /rules/accounts`. 4. Repeat steps 1 and 2 as MGR-A. 5. `GET /rules/vocabulary` as each. | 2: the order-placing actions appear only in the simulate framing, with the restriction the vocabulary serves beside each (record the text). 3: ACC-2, which MGR-SIM cannot trade, is listed neither in the selector nor in `GET /rules/accounts`. 4: MGR-A's entries follow MGR-A's response. 5: each palette equals its own response (E37-TC-B01). The crafted saves are E37-TC-G06 and E37-TC-G07. SS, HAR. | none | Q02-7 | — |
| E37-TC-B14 A comment node is presentation only | U1.4, U1.5 | OWNER; RULE-LAYOUT-1 saved and open in the graph editor | 1. Note the newest `ir_hash` from `GET /rules/{ruleId}/versions`. 2. Edit one comment's text, move the other comment and add a third; press `Save`. 3. Read `GET /rules/{ruleId}/versions` again. 4. Open SCR-088 and read the stamp. | 3 and 4: the newest `ir_hash` and the stamp equal step 1's: comments live in the presentation block, outside the hash (Q-13 records whether a version row is written). No condition or action carries a comment's text. HAR, SS. | `rule.graph_saved` | Q03 | — |
| E37-TC-B15 The inspector | S02 scope; E37-D05 §7 (R1) | OWNER; the S-form rule | 1. Focus a node and press `Enter`. 2. Edit a parameter and press `Esc`. 3. Reopen it with a double-click, then press the close control. 4. At 1280 × 800 and 200 % zoom open the action's inspector and scroll. | 1: a drawer opens on the right, titled by the node's accessible name. 2 and 3: `Esc` and Close return focus to the node. 4: the body scrolls under a sticky title and footer and no field is cut off (R1). A11Y, SS. | `rule.graph_inspector_opened` | Q02+ | — |
| E37-TC-B16 An inspector edit does not re-layout | S02.6 | OWNER; RULE-LAYOUT-1 open in the graph editor | 1. Record each node's position (a screenshot, or the stored layout read back after a save). 2. Open the condition's inspector, change its threshold from 1 to 1.5 and save. 3. Read the positions again and the newest `ir_hash`. 4. Change only a comment's text, save and read the `ir_hash`. | 2 and 3: no auto-layout runs and every position is unchanged; the `ir_hash` differs from step 1's (a semantic parameter changed). 4: the `ir_hash` equals step 3's (Q-13 records the version row). SS, HAR. | none | Q02+ | — |

## 3. Group C — Validation (US-RULE-005 cycle, orphan; US-RULE-001 quarantine; E37-S03)

Screens SCR-082 and the Problems region (CMP-234). Endpoints `POST /rules/validate`,
`POST /rules/{ruleId}/compile`, `PUT /rules/{ruleId}`. Every case is mapped, not executed, and waits
for E37-S03 (diagnostics on the offending node, cycles, orphans, quarantine). `Save` and `Arm…` take
the validity look when a graph has errors (never T2; a press sends no request).

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-C01 An error on the offending node | S03.1, U5.1 | OWNER; a draft holding a trigger, a comparison condition with its value empty and an action, connected | 1. Press `Ctrl+Enter`. 2. Read the condition node, the Problems region and the footer counters. 3. Press `Enter` on the entry. | 1: the HAR shows the validation call. 2: the node shows an error treatment of text and a glyph, never colour alone; the strip opens with the entry first, anchored to that node; the footer counters read one error; the live region says "Validation — {n} errors, {m} warnings" [rules.graph.validation.announce · P] (`{n}` = 1, `{m}` the warnings). 3: focus moves to the node. HAR, SS, A11Y, MET. | `rule.graph_validation_run` `{errors, warnings, durationMs}` | Q02+ | — |
| E37-TC-C02 [R] A cycle is refused and drawn as a path | S03.2, U5.4 | OWNER; a draft holding a trigger, two logic gates A "all of" and B "any of", a condition and an action, with A feeding B | 1. (`FX-CYCLE` names this editor state.) Drag from B's output onto one of A's inputs, so that A would depend on B and B on A. 2. Read the target, the canvas and the Problems region. 3. Press `Validate`, then `Save`. 4. Search the HAR for any request body carrying the loop. | 1 and 2: refused; the sentence "This would make a loop — {A} already depends on {B}." [rules.graph.validation.loop_refused · P] (`{A}` A's name, `{B}` B's) sits at the target and no edge is made; every edge on the would-be path and every node on it is marked in text and glyph (never colour alone) and the Problems region enumerates the path with "This graph has a loop — remove the connection from {X} to {Y}." [rules.graph.validation.cycle · M] (`{X}` and `{Y}` are accessible names, never ids; `CYCLE_DETECTED` is in the details disclosure). 3: `Save` and `Arm…` take the validity look: "Fix the errors to save." [rules.editor.validity.save] and "Fix the errors first." [rules.editor.validity.arm]. 4: no compile, validate or save body ever holds the loop. FI-4. HAR, SS, A11Y. | `rule.graph_cycle_rejected` | Q02-5 | — |
| E37-TC-C03 A cyclic model by API | U5.4 | OWNER; `curl` with the session and the CSRF token; a saved draft | 1. `POST /rules/{ruleId}/compile` with `editor` `graph` and a model whose edges close a loop (`n3` to `n4` and `n4` to `n3`). 2. Repeat with the same model as `counterpart_model`. 3. `GET /rules/{ruleId}/versions`. | 1 and 2: the server refuses the model with a blocking issue and returns no IR: a cyclic IR is never produced (which issue code carries it is Q-09). 3: no version was written. HAR. | none | X02 | — |
| E37-TC-C04 An orphan warns | S03.3, U5.5 | MGR-A; ACC-1; a draft holding the S-form rule plus a comparison condition with no connection | 1. (`FX-ORPHAN` names this editor state.) Read the unconnected condition and the Problems region. 2. Read `Save` and `Arm…`. | 1: the node shows a warning treatment of glyph and text with an outline; the strip lists "{node} reaches no action." [rules.graph.validation.orphan · P] (`{node}` the condition's name) as a warning; the footer counts one warning. 2: while only warnings stand `Save` is enabled and `Arm…` is T2 with "Simulate first — {fires} fires or {hours} h." [rule.arm.simulate_first] (the OWNER's `Arm…` is E37-TC-C13). FI-10. SS, A11Y. | none | Q02-6 | — |
| E37-TC-C05 A dangling required input | U5.5 | MGR-A; ACC-1; a draft holding the S-form rule with its edge removed, so the action's `when` input is unconnected | 1. Read the action node and its empty input port. 2. Read the Problems region. | 1: the port's ring is marked and its accessible name says it is not connected; the node shows a warning treatment. 2: the strip lists "{node}: {port} input is not connected." [rules.graph.validation.dangling · P] (`{node}` the action's name, `{port}` the input's label, "run when" [rules.graph.portlabel.when · M]) as a warning; the condition, now reaching no action, is listed by E37-TC-C04's entry. FI-10. SS, A11Y. | none | Q02-6 | — |
| E37-TC-C06 [R] Save blocks on both | S03.3, U5.5 | MGR-A; ACC-1; the drafts of E37-TC-C04 and E37-TC-C05 together (an orphan condition and the action's `when` unconnected) | 1. (`FX-ORPHAN` names this editor state.) Press `Save`. 2. Read the Problems region and the action bar. 3. Press `Enter` on each entry. | 1 and 2: the warnings of editing become blocking errors on save: the HAR shows no `PUT`; the strip lists each node by its accessible name with a jump-to-node action; `Save` takes the validity look with "Fix the errors to save." [rules.editor.validity.save] and `Arm…` with "Fix the errors first." [rules.editor.validity.arm]; neither is T2. 3: focus moves to the entry's node. E37-S03 says a graph with an error saves "as a draft" only, US-RULE-005 says save is blocked and E37-D02 §3 draws the validity look: follow E37-D02 and record whether a draft is saved (C-07). FI-10. HAR, SS, A11Y. | `rule.graph_save_blocked` `{reason}` | Q02-6 | — |
| E37-TC-C07 The problems list navigates | S03.1 | MGR-A; ACC-1; a draft with one error and one warning | 1. Move to the Problems region with `Ctrl+\`. 2. Read the entries and the footer. 3. Press `Enter` on each entry. 4. Fix both and read the strip. | 1: the region is named "Problems" [rules.graph.aria.region_problems · P] around an unnamed `log`, errors first. 2: each entry is a button and the footer counters equal the entries. 3: focus moves to the entry's node. 4: the strip collapses to "No problems — 0 errors · 0 warnings." [rules.graph.problems.none · P]. A11Y, SS. | `rule.graph_validation_run` | Q02+ | — |
| E37-TC-C08 Both editors report the same diagnostics | S03.4 | OWNER; one stored rule whose IR has a comparison missing its value | 1. Open the rule in the form editor and press `Validate`; record the diagnostics. 2. Open the same rule in the graph editor and press `Validate`; record them. 3. Compare. | 3: the two editors return the same set of diagnostics with the same severities; the form anchors each to its row and the graph to its node. HAR, SS. | none | Q03 | E36-S03 |
| E37-TC-C09 [R] Validation service unavailable | S03.5 | MGR-A; ACC-1; the S-form rule saved as a draft; `FT-COMPILE` ready (manual stand-in: stop the staging engine) | 1. Make `POST /rules/validate` and `POST /rules/{ruleId}/compile` unreachable (`FT-COMPILE`). 2. Edit, press `Validate`, then `Save`, then read `Arm…` and the chip. 3. Restore the service and press `Validate`. | 2: the chip reads "Not verified" [rules.editor.roundtrip.unverified] with the tooltip "Not verified — the compile service is unreachable. You can save a draft; arming is blocked until the rule is verified." [rules.editor.roundtrip.tip.unverified]; `Save` is enabled and saves a draft only; `Arm…` is T2 with "Not verified — arming is blocked." [rule.arm.unverified]; the graph is never presented as valid. 3: the chip returns to a verified word. FI-9. SS, A11Y, HAR. | `rule.roundtrip_verified` `{unverified}` | Q02-9 | FT-COMPILE |
| E37-TC-C10 [R] A quarantined rule | S03.6, U1.6 | OWNER; RULE-CORRUPT-1 (truncated), RULE-CORRUPT-2 (a field of the wrong type at a named JSON path) and RULE-CORRUPT-3 (an IR version the engine does not support), each seeded into a rule of ACC-1 | 1. Open each rule's `/rules/{ruleId}/graph`. 2. Read the page, the header pill and the actions. 3. Try to edit, save and arm. 4. Look for an export control and use it. 5. Read the rule's fire history. | 2: the rule opens read-only and disarmed, names the failing JSON path (RULE-CORRUPT-2's path is in the README of `tests/fixtures/e37/`; the other two name the point of failure the build finds) and says it cannot be read; the wording on this screen is not in the deck (Q-02). 3: no node is editable, no write goes out and no partial graph is rendered as editable. 4: an export of the stored document as JSON is offered. 5: the fire history stays empty: nothing was executed. HAR, SS, A11Y. | none | Q02-10 | FT-CORRUPT |
| E37-TC-C11 The server is stricter than the client | S03 scope | MGR-A; ACC-1; a draft whose graph passes the editor's own checks (no cycle, orphan or dangling port) but holds 11 action nodes | 1. Press `Validate`. 2. Press `Save`. 3. Read the HAR, the Problems region and the node a diagnostic names. | 1 and 2: the server's validator refuses the eleventh action (the bound is 10, E35's BD-03); the editor blocks, anchors the diagnostic on a node when it names one, and never presents the graph as valid. 3: one validation call per press: no silent retry. HAR, SS. | `rule.graph_validation_run` | X02 | — |
| E37-TC-C12 Validation is rate limited | E37-NB-24 | OWNER; the S-form rule; a console script that presses `Validate` 25 times in one second | 1. Run the script. 2. Read the HAR and the editor. 3. Read `GET /admin/audit`. | 2: the first calls answer 200; once the per-user burst (20, shared with compile) is spent calls answer `429 rate_limited` with `Retry-After`; the editor never shows "valid" on a `429`, does not crash and does not loop on retries; the wording on screen is not in the deck (Q-03). 3: the `429` writes no audit row. HAR, SS, AUD. | none | man | — |
| E37-TC-C13 [R] Arming is routed, never done here | S03 scope; DA-15 | OWNER; MGR-A; ACC-1; a valid draft MGR-A created (the S-form rule saved) | 1. As MGR-A read `Arm…` on the valid draft. 2. Add an error and read `Arm…` again. 3. As OWNER read `Arm…` on the valid draft and press it. 4. Cancel the dialog. 5. Read the HAR of the whole session. | 1: `Arm…` is T2 "Simulate first — {fires} fires or {hours} h." [rule.arm.simulate_first] (`{fires}` and `{hours}` as the build states them). 2: with the error it takes the validity look "Fix the errors first." [rules.editor.validity.arm]. 3: for the OWNER `Arm…` is enabled and opens SCR-085; the editor arms nothing itself. 5: no request to `PUT /rules/{ruleId}/mode` came from the editor, and `GET /rules/{ruleId}` shows the rule not armed. HAR, SS. | none | Q02+ | — |
| E37-TC-C14 [R] A quarantined rule that was armed | S03.6, U1.6 | OWNER; RULE-CORRUPT-2 seeded on a rule row of ACC-1 whose mode is armed (`FT-CORRUPT` writes the mode as well as the IR) | 1. Open the rule's `/rules/{ruleId}/graph` (reading it, or the engine evaluating it, force-disarms an armed rule whose stored IR cannot be read). 2. Read `GET /rules/{ruleId}`. 3. Read `GET /admin/audit` for the rule. 4. Open the rule again and read the audit log. | 1: as E37-TC-C10: read-only, the failing JSON path named, an export offered. 2: the mode no longer reads `armed` (the force-disarm sets `disabled`). 3: one `rule.disarmed` row, written by the server with no actor, naming the cause `quarantined`. 4: no second row: the disarm is written once. HAR, AUD. | `rule.disarmed` | Q02-10 | FT-CORRUPT |

## 4. Group D — Round-trip switching (US-RULE-006, US-RULE-001; E37-S04)

Screens SCR-082 and SCR-081 (the form side), with SCR-088 for the stamp and the diff. Endpoints
`POST /rules/{ruleId}/compile` (with `counterpart_model`), `PUT /rules/{ruleId}`,
`GET /rules/{ruleId}/versions`. Every case is mapped, not executed, and waits for E37-S04; a case
that switches editors also waits for the form editor (`E36-S02`). `Alt+G` switches editors.

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-D01 [R] Switch without editing | U1.1, U6.1, S04.1 | OWNER; RULE-FORM-1 (RC-11, authored in the form) | 1. Open RULE-FORM-1 in the form editor; export its IR from SCR-088 and note the stamp and the newest `ir_hash`. 2. Press `Alt+G` to the graph editor; read the chip; export and read the stamp. 3. Press `Alt+G` back to the form; read the chip and export. 4. Repeat the round once more and read `GET /rules/{ruleId}/versions`. 5. In the graph editor, with no edit made, press `Save`, read the response and export again. 6. `GET /rules/{ruleId}/versions`. | 2 to 4: the chip reads "Round-trips ✓" [rules.editor.roundtrip.identical] at every hop; the stamp and the `ir_hash` are equal at every hop; the HAR shows one `POST /rules/{ruleId}/compile` per switch; the exports are byte-equal pairwise (no edit between them); after step 4 the versions list holds no new version (the newest `ir_hash` is step 1's) and the HAR holds no `PUT`: a switch alone writes no version. 5: the response names the version carrying the `ir_hash` of step 1, and the export is byte-equal to the one before the save (U1.1: no changes, save, the stored IR identical; Q-13 records whether a row is written). 6: every listed version carries that `ir_hash`. FI-6. HAR, SS. | `rule.roundtrip_verified` `{identical}` per switch | Q02-3 | E36-S02 |
| E37-TC-D02 The four indicator words and their tooltips | S04 scope; FI-6 to FI-9 | OWNER; RULE-FORM-1; RULE-GRAPH-NESTED (RC-28); `FX-S-FORM-MISMATCH`; `FT-COMPILE` and `FT-MISMATCH` ready | 1. State 1: open RULE-FORM-1 in the graph editor; read the chip and its tooltip. 2. State 2: open RULE-GRAPH-NESTED; read the chip, its tooltip and the inset. 3. State 3: with `FT-MISMATCH` open `FX-S-FORM-MISMATCH`; read the chip and its tooltip. 4. State 4: with `FT-COMPILE` open the S-form rule; read the chip and its tooltip. 5. For each change read the live region. | 1: "Round-trips ✓" [rules.editor.roundtrip.identical] with "This rule is fully editable in both the form and the graph editor." [rules.editor.roundtrip.tip.identical]. 2: "Unsupported in form view" [rules.graph.indicator.graph_only · M] with "The form shows {n} graph-only parts as read-only cards. Everything else stays editable there." [rules.graph.indicator.tip_graph_only · P] (`{n}` the count of graph-only parts) and the inset "Graph-only — read-only in the form" [rules.graph.indicator.inset · P]. 3: "Round-trip mismatch" [rules.editor.roundtrip.mismatch] with "The form and the graph compile to different rules. Saving is blocked until you choose which version to keep." [rules.editor.roundtrip.tip.mismatch · M]. 4: "Not verified" [rules.editor.roundtrip.unverified] with "Not verified — the compile service is unreachable. You can save a draft; arming is blocked until the rule is verified." [rules.editor.roundtrip.tip.unverified]. 5: each change is announced once, politely, as "Round-trip: {word}" [rules.editor.name.roundtrip] (`{word}` the chip's word). The chip is a status, never a control, except state 2's, which opens E37-TC-D05's panel. FI-6 to FI-9. SS, A11Y. | `rule.roundtrip_verified` `{result}` per state | Q02+ | FX-S-FORM-MISMATCH, FT-MISMATCH, FT-COMPILE, E36-S02 |
| E37-TC-D03 Checking and stale | S04 scope | OWNER; the S-form rule saved; `FT-CLOCK` | 1. Start a HAR. 2. Drag a node, type in the inspector for 60 s and pan, reading the chip throughout. 3. Press `Save` and read the chip during the call. 4. Edit again and read the chip. 5. Read the chip's tooltip. | 2: no compile call appears in the HAR and the chip does not change (P-1). 3: while the compile runs the chip reads "Checking…" [rules.editor.roundtrip.checking] (`aria-busy`, no spinner), then the result. 4: the chip keeps its last word and adds "· since your last save" [rules.editor.roundtrip.stale]: an edit never un-verifies a rule, only the next save does. 5: the tooltip ends with the suffix " Last verified {HH:MM:SS} UTC." [rules.graph.indicator.stale_suffix · P] (record the time the build shows: Q-06). FI-17, FI-18. HAR, SS, A11Y, T. | none | Q02+ | FT-CLOCK |
| E37-TC-D04 [R] A graph-only construct is badged at creation | U5.7, S04.2, U1.2 | OWNER; the S-form rule open in the graph editor | 1. (`FX-S-GRAPH` seeds the result.) Add a second action and a second logic gate. 2. Fan the condition "Position is open" into both gates (drag its output to an input of each). 3. Read the condition, the chip and the header. 4. Save. 5. Export the IR from SCR-088 and read it. | 2 and 3: the shared condition is badged "graph-only" [rules.graph.badge.graph_only · M] at once (glyph and word, never colour alone); the chip changes to "Unsupported in form view" [rules.graph.indicator.graph_only · M] with the inset "Graph-only — read-only in the form" [rules.graph.indicator.inset · P]; E37-S04 and `14` write "node-only" where the deck's word is graph-only (C-05): record any header line the build adds. 4: the save writes `rule.roundtrip_verified` `{graph_only_construct}`. 5: the stored IR records the construct (record the marker's name). FI-7, FI-12. SS, A11Y, AUD. | `rule.graph_node_added`, `rule.roundtrip_verified` `{graph_only_construct}` | Q02-4 | — |
| E37-TC-D05 [R] The "What won't round-trip" panel | S04 scope; DA-5 | OWNER; the result of E37-TC-D04 or RULE-GRAPH-NESTED (RC-28) | 1. Press the chip, or press `Enter` on it. 2. Read the panel. 3. Activate a row. 4. Press `Esc`. 5. Open the outline with `Alt+L` and read its Graph-only group. 6. Start an analytics capture and open the panel again. | 1 and 2: a popover (`role="dialog"`) anchored to the chip, titled "What won't round-trip" [rules.graph.panel.title · M]; one row per graph-only node: a button carrying the node's accessible name, the construct sentence ("shared condition {A}, used by {n} gates" [rules.graph.panel.fan_out · P] for a shared condition, `{A}` its name, `{n}` the gate count) and "The form shows this as a read-only card." [rules.graph.panel.row_note · P]; a footer "Open the form view" [rules.graph.panel.open_form · P]. 3: focus moves to the node, the canvas scrolls to it and its outline row is selected. 4: the panel closes and focus returns to the chip. 5: the same nodes are listed under "Graph-only" [rules.graph.outline.group_graph_only · P]. 6: opening the panel emits no analytics or audit event. FI-5. SS, A11Y, ANA. | none | Q02-4 | — |
| E37-TC-D06 The form shows the read-only part | U1.2, U6.3 | OWNER; RC-09 (arithmetic), RC-15 (stable for), RC-21 (n of), RC-22 (within), RC-24 (count), RC-25 (none of) and RC-28 (a shared node) stored as rules | 1. Open each rule in the form editor. 2. Read the card that stands in place of the graph-only part, its sentence and its action. 3. Edit an editable field and save. 4. Activate the card's edit-in-graph action. | 2: the card's sentence is the form editor's: "{A} minus {B} is above {x}" [rules.editor.card.arithmetic] (RC-09), "{A} has not changed for {w}" [rules.editor.card.stable] (RC-15), "at least {n} of: …" [rules.editor.card.n_of] (RC-21), "{A} happened within the last {w}" [rules.editor.card.within] (RC-22), "{A} happened at least {n} times in {w}" [rules.editor.card.count] (RC-24) and "none of: {A}, {B}" [rules.editor.card.none_of] (RC-25); a nested gate reads "either ({A} and {B}) or {C}" [rules.editor.card.nested] and RC-28's shared condition "shared condition {A}, used by {n} gates" [rules.graph.panel.fan_out · P]; the part is never dropped or rewritten and the rest is editable. 3: the save keeps the card's part (E37-TC-D07 compares bytes). 4: it opens the graph editor on the same rule. The switch from state 2 shows no confirmation (hand-off A-12) where `14` says a confirmation names the read-only parts (C-12): record whether one appears. SS, A11Y. | none | Q02-4 | E36-S02 |
| E37-TC-D07 Unrepresentable after an edit | U6.7 | OWNER; RULE-FORM-1 | 1. Open RULE-FORM-1 in the graph editor, add an "at least n of" gate over its two conditions and save. 2. Export the IR from SCR-088 (export A). 3. Open the form editor and read the gate's part. 4. Change an editable threshold in the form and save. 5. Export again (export B) and compare the gate's sub-tree in A and B. | 3: the sub-tree is a read-only card with its plain-language description ("at least {n} of: …" [rules.editor.card.n_of]); the rest is editable. 5: outside the edited threshold A and B are byte-equal: the sub-tree is preserved byte for byte. SS, HAR. | `rule.graph_saved` | Q02-4 | E36-S02 |
| E37-TC-D08 [R] The hash proof fails | U6.4, S04.3 | OWNER; RULE-FORM-1; `FT-MISMATCH` ready (the injector makes the post-switch hash differ) | 1. Note the newest `ir_hash`. 2. With `FT-MISMATCH` on, switch from the form to the graph editor without editing. 3. Read the screen, the HAR and the analytics capture. 4. Read `GET /rules/{ruleId}/versions` and `GET /metrics`. | 2 and 3: the switch is aborted and the editor stays where it was; the rule is untouched; an integrity-failure error shows both hashes and a downloadable diff (the wording is not in the deck: Q-07); one high-severity telemetry event is emitted. 4: no new version and the same `ir_hash`; `rule_graph_roundtrip_mismatch_total` rises by one. SS, HAR, ANA, MET. | `rule.roundtrip_integrity_failure` `{hashBefore, hashAfter, ruleId}` | man | FT-MISMATCH, E36-S02 |
| E37-TC-D09 [R] The mismatch frame | S04.4 | OWNER; `FX-S-FORM-MISMATCH`; `FT-MISMATCH` | 1. Open the rule in the graph editor. 2. Read the chip, the action bar and the canvas. 3. Read the outline. 4. Activate the diff control. | 1 and 2: the chip reads "Round-trip mismatch" [rules.editor.roundtrip.mismatch] with "The form and the graph compile to different rules. Saving is blocked until you choose which version to keep." [rules.editor.roundtrip.tip.mismatch · M]; `Save` and `Arm…` are T2 with one reason beside the pair, "Saving is blocked until the mismatch is resolved." [rule.save.mismatch · P], both pointing at it; `Discard changes` stays enabled; the diverging node (the action) is outlined, badged "mismatch" [rules.graph.badge.mismatch · M] (glyph and word) and selected. 3: its outline row is selected and focused. 4: the control reads "View diff" [rules.editor.mismatch.view_diff] and opens SCR-088's diff naming the diverging path. FI-8. SS, A11Y. | `rule.roundtrip_verified` `{mismatch}` | man | FX-S-FORM-MISMATCH, FT-MISMATCH |
| E37-TC-D10 [R] The two recovery choices | S04.4 | as E37-TC-D09 | 1. Open the mismatch dialog from the chip. 2. Read it and press `Esc`. 3. Reopen it and wait 60 s. 4. Choose the form version; then restore the setup, reopen the dialog and choose the graph version. 5. Read `GET /rules/{ruleId}/versions` and `GET /admin/audit`. | 1 and 2: a modal dialog offering exactly "Keep the form version — the graph's {diverging node} is replaced by this form's Row {n}." [rules.editor.mismatch.keep_form · M] (`{diverging node}` the action's name, `{n}` the form's row), "Keep the graph version — your form edits since the last save are discarded." [rules.editor.mismatch.keep_graph · M] and "Cancel" [rules.graph.dialog.cancel · P]; no third choice, no merge, no timer; `Esc` cancels and focus returns to the chip. 3: nothing changes: it is never resolved automatically. 4: each choice resolves to that side: the stored version's `ir_hash` equals that side's compile. 5: one audited row per choice. FI-16. SS, A11Y, AUD. | `rule.roundtrip_mismatch_resolved` `{choice}` | man | FX-S-FORM-MISMATCH, FT-MISMATCH |
| E37-TC-D11 [R] Switching an armed rule | U6.6, S04.5 | OWNER; RULE-ARMED-1 armed on demo | 1. Open it in the graph editor, press `Alt+G`, then `Alt+G` again. 2. Attempt a first edit in each editor. 3. Choose to edit as a new draft version. 4. Read `GET /rules/{ruleId}` (`active_version_id` decides) and `GET /rules/{ruleId}/versions` (`is_active`; a list without it is recorded against `22`). 5. Repeat steps 1 and 2, then choose to disarm and edit. | 1: viewing is permitted in both editors with no confirmation. 2: the first edit changes nothing and re-shows the one notice (E37-TC-A16). 3: the control reads "Edit as a new draft version" [rules.editor.armed.new_version] and a new draft opens as editing. 4: the active version and the armed version's `ir_hash` are unchanged. 5: the control reads "Disarm to edit" [rules.editor.armed.disarm]; after it the rule is no longer armed and edits work; no `PUT /rules/{ruleId}/mode` with `armed` is sent from the editor. HAR, SS, AUD. | none | Q02+ | E36-S02 |
| E37-TC-D12 The layout survives a form-side edit | U1.5, S04.6 | OWNER; RULE-LAYOUT-1 | 1. Open it in the graph editor; record positions and comments; note the newest `ir_hash`. 2. Switch to the form, change a threshold and save. 3. Switch back. 4. Read positions, comments and the `ir_hash`. 5. Set the threshold back in the form and save; read the `ir_hash`. | 4: the original hand-placed positions and both comments are shown, not an auto-layout; the `ir_hash` differs from step 1's only because of the threshold. 5: the `ir_hash` returns to step 1's value (Q-13 records the version rows). SS, HAR. | `rule.graph_saved` | Q03 | E36-S02 |
| E37-TC-D13 Two tabs across editors | U6.5, S04.7 | OWNER; a saved draft at version n open in the form editor in tab 1 and in the graph editor in tab 2 | 1. In tab 1 change a threshold and save (version n + 1). 2. In tab 2 change the same rule and press `Save`. 3. Read the dialog and choose Reload. 4. `GET /rules/{ruleId}/versions`. | 2: `412 version_conflict`. 3: the dialog "Someone saved version {n} from the {form} editor in another session. Reload to see it, then re-apply your changes." [rules.graph.dialog.conflict · P] with `{form}` = form (the other session saved from the form editor), Reload and Cancel, no overwrite. 4: exactly one new version, tab 1's. FI-11. HAR, SS, AUD. | `rule.saved` | Q02-8 | E36-S02 |
| E37-TC-D14 The unsaved-changes prompt on a switch | U6.2 | OWNER; a saved draft open in the graph editor | 1. Move a node and change a threshold (unsaved). 2. Press `Alt+G`. 3. Choose Cancel. 4. Press `Alt+G` and choose Discard. 5. Repeat the edits, press `Alt+G` and choose Apply. 6. Read the versions. | 2: the dialog "Apply your changes before switching?" [rules.graph.dialog.switch_title · P] with "Apply" [rules.graph.dialog.apply · P], "Discard" [rules.graph.dialog.discard · P] and "Cancel" [rules.graph.dialog.cancel · P]. 3: Cancel stays in the graph editor with the edits. 4: Discard switches with the edits dropped and no version. 5: Apply saves (one new version) and then switches; the chip is checked for the save and for the switch. HAR, SS. | `rule.graph_saved` on Apply only | Q02+ | E36-S02 |
| E37-TC-D15 A migrated rule | U1.3, U6.8; E37-NB-10 | OWNER; RULE-OLDIR (a rule stored under an IR version older than the current) | 1. Open RULE-OLDIR in the graph editor. 2. Read `GET /rules/{ruleId}/versions` and the audit log. 3. Switch to the form and back. 4. Read the versions and the audit again. 5. Read the rule's mode. | 1 and 2: the rule is migrated on open, the migration is logged once and appears as its own version entry. 3 and 4: the comparison is against the post-migration hash and no second migration entry appears. 5: the rule stays disarmed until reviewed. HAR, AUD. | none | man | RULE-OLDIR, E36-S02 |
| E37-TC-D16 Cosmetic differences, one hash | U1.4 | OWNER; RULE-GRAPH-NESTED (RC-28) stored as rule X | 1. Export X's IR from SCR-088 and note the newest `ir_hash`. 2. Edit the export by hand into RULE-GRAPH-EQUIV: reverse every object's key order, write `1.50` where it holds `1.5` and rename each node id. 3. Save it as the next version of X (`PUT /rules/{ruleId}` with the edited document). 4. In the graph editor move a node and edit a comment; save. 5. Read `GET /rules/{ruleId}/versions`. | 3 and 5: the response names the version carrying step 1's `ir_hash` (Q-13: whether a row is written): cosmetic differences never change the hash. 4: the `ir_hash` still equals step 1's. HAR. | none | Q03 | — |
| E37-TC-D17 [R] A corpus sample by hand | U1.1, U1.2, U6.1 | OWNER; RC-11, RC-09, RC-21, RC-22, RC-25 and RC-28 stored as rules | 1. For each rule record the newest `ir_hash`. 2. Hop form to graph to form, then graph to form to graph, with `Alt+G`, reading the chip and the stamp at every hop. 3. Read the form's view of each graph-only rule. | 2: the stamp and the `ir_hash` are equal at every hop for every rule; a rule's golden hash (§13.3, first 12 hex characters) is the reference for the document imported unchanged, while a created rule hashes its own id (§0), so its stamp differs from the golden by design. 3: RC-09, RC-21, RC-22, RC-25 and RC-28 show read-only cards (E37-TC-D06) and never degrade to editable text. HAR, SS. | `rule.roundtrip_verified` per hop | Q03 | E36-S02 |
| E37-TC-D18 The fuzz invariant, a spot check | U1.7 | OWNER; RC-24, RC-29 and RC-30 stored as rules | 1. For each rule hop twice around form, graph, form (graph-only rules in the graph editor only). 2. Read the stamp at every hop. | 2: the stamp is unchanged at every hop, and a hop that cannot represent a document says so instead of emitting a lossy one. The 10,000-document run is E35's and E37-Q03's gate; this is the by-hand sample. HAR. | none | Q03 | E36-S02 |

## 5. Group E — Keyboard authoring (US-RULE-005, the keyboard half; E37-S05)

Screens SCR-082 and its outline (CMP-257, PROPOSED), the Problems region and the action bar. The
keyboard map is E37-D04 §4 (K-01 to K-25, printed in §11 with an empty result column); the
screen-reader script is E37-D04 §5. Every case is mapped, not executed, and waits for E37-S05. A
chord the hand-off leaves PROPOSED or unregistered is marked `pending E37-S05`. A case run by
keyboard uses no pointer; the screen reader of record is NVDA with Chrome, and the live region's
transcript is the evidence.

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-E01 Landmarks and entry | DA-16; S05 scope | OWNER; the S-form rule; NVDA with Chrome, or the accessibility tree | 1. Load the page and press `Tab` from the header. 2. Press `Tab` at the graph region and again after leaving it. 3. Press `Ctrl+\` repeatedly. 4. Read the region names and roles. 5. At 1280 × 800 read the outline and Problems regions. | 1: the first stop is the mode toggle (CMP-235). 2: `Tab` enters the graph region once and leaves it once; it never cycles nodes (K-23). 3: `Ctrl+\` visits five regions in order: "Palette" [rules.graph.aria.region_palette · P], the rule graph, "Outline" [rules.graph.aria.region_outline · P], "Problems" [rules.graph.aria.region_problems · P] and "Rule actions" [rules.graph.aria.region_actions · P]. 4: the graph region is named "Rule graph — {name}" [rules.graph.aria.region · P] with the role description "rule graph" [rules.graph.aria.roledescription · P] (PROPOSED until E37-Q05's run) and the hint "Arrow keys move between nodes and ports. Enter connects or opens a node. Alt+L opens the outline." [rules.graph.aria.hint · P] on entry; the foot row is the toolbar "Canvas view" [rules.graph.aria.toolbar_canvas · P] and the action bar's toolbar "Actions" [rules.graph.aria.toolbar_actions · P]. 5: the outline and Problems are tabs under the canvas, one stop, only the selected panel shown. A11Y, SS. | none | Q05 | — |
| E37-TC-E02 Roving navigation | K-10, K-12, K-22, K-23 | OWNER; the S-form rule | 1. Focus a node and press `↑`, `↓`, `←` and `→`. 2. On an output port press `↓`, `←` and `→`. 3. On a connection press `↑`, `↓` and `←`. 4. Press `Esc` from each. 5. Read the announcements and watch the viewport. | 1: `↑` and `↓` move to the previous and next node in the rule's reading order, `←` and `→` to the node's first input and first output port; each node is announced with "Node {index} of {size}." [rules.graph.aria.position · P] (`{index}` of `{size}`) and its name follows "{Type} node: {sentence fragment}" [rules.graph.aria.node · P]. 2: `↓` goes to the port's connections, `←` and `→` to the node's other ports. 3: `↑` and `↓` move to the next and previous connection of the port and `←` returns to the port. 4: `Esc` returns focus to the graph region. 5: the viewport follows focus, clear of the minimap, with no transit. A11Y. | none | Q02+ | — |
| E37-TC-E03 [R] Connect by keyboard | S05.2, U5.6 | OWNER; a draft holding the condition "CVD divergence" and an "all of" gate | 1. Focus the condition's output port and press `Enter`. 2. Press `→` or `↓` to the gate's first input. 3. Press `Enter`. 4. Read the live region at each step. | 1: "Connecting from output port, {type} — choose an input" [rules.graph.announce.connect_from_output · P] (`{type}` boolean), then once "{available} inputs available, {unavailable} not available." [rules.graph.announce.availability · P]. 2: the target reads "{target}, {portName} — can connect, {index} of {size}" [rules.graph.announce.candidate · P] (`{target}`, `{portName}`, `{index}` of `{size}`), compatible targets first. 3: the edge is made and the live region says "connected {A} output to {B} input {n}" [rules.graph.announce.connected · P] (`{A}` "CVD divergence", `{B}` the gate's name, `{n}` 1); the story's example names the gate "AND" where the deck and E37-D02 call it "all of" (C-06): record the gate's word. 4: one polite sentence per step, none per arrow press beyond the port's name. A11Y, ANA. | `rule.graph_edge_added`, `rule.graph_keyboard_authoring_used` `{connect, canvas}` | Q02-2 | — |
| E37-TC-E04 [R] An incompatible target is announced | S05.3, U5.6 | OWNER; a draft holding "Position is open" (a boolean output) and a comparison condition with a number input | 1. Focus the boolean output and press `Enter`. 2. Arrow to the number input. 3. Press `Enter` on it. 4. Arrow to a compatible target and press `Enter`. 5. Repeat step 1 and press `Esc`. | 2: the target reads "{target}, {portName}. {reason}" [rules.graph.announce.candidate_refused · P] with `{reason}` = "A true or false result can't be used as a number." [rules.graph.connect.boolean.number · P]; unavailable targets come after the available ones and every one is reachable (DA-10). 3: the sentence is spoken again, no edge is made and focus stays on the pending connect. 4: the compatible target connects. 5: the live region says "Cancelled" [rules.graph.announce.cancelled · P] and focus returns to the source port. A11Y, HAR. | `rule.graph_keyboard_connect_rejected` `{boolean, number}` | Q02-5 | — |
| E37-TC-E05 No target | S05 scope | OWNER; a draft holding only a trigger | 1. Focus the trigger's output port and press `Enter`. 2. Read the live region. | 2: the live region says "No input can take this connection." [rules.graph.announce.none_available · P]. A11Y. | none | Q02+ | — |
| E37-TC-E06 [R] A whole rule with no pointer | S05.1, U5.6 | OWNER; the keyboard only; a rule X whose newest version was built by pointer as in E37-TC-A04 with an "all of" gate between the condition and the action | 1. Select all and delete; save nothing. 2. By keyboard add the trigger, the condition, the gate and the action from the palette (`Enter` on each entry). 3. Connect them with the port flow of E37-TC-E03. 4. Edit the parameters in the inspector. 5. Press `Save`. 6. `GET /rules/{ruleId}/versions`. | 2 to 4: no pointer is used and the live region speaks one sentence per completed operation. 5: the save succeeds with the chip "Round-trips ✓" [rules.editor.roundtrip.identical]. 6: the newest `ir_hash` equals the pointer-built version's: the same rule built both ways stores one hash (Q-13 records whether a version row is written). HAR, A11Y, AUD. | `rule.graph_keyboard_authoring_used` `{operation, surface}`, `rule.graph_saved` | Q02-2 | — |
| E37-TC-E07 Outline twins: structure (K-01 to K-05) | S05.4, DA-4 | OWNER; the S-form rule; the outline open (`Alt+L`, or its tab at 1280 × 800) | 1. Add a node with "+ Add node" [rules.graph.outline.add_node · P] and `Enter` on a palette entry in the listbox. 2. Delete a node from its row menu (`Shift+F10`, "Delete" [rules.graph.outline.menu_delete · P]). 3. Rename one with "Rename" [rules.graph.outline.menu_rename · P] or `F2`. 4. Connect two nodes with "Connect…" [rules.graph.outline.menu_connect · P] and its target picker. 5. Remove the edge with "Disconnect…" [rules.graph.outline.menu_disconnect · P]. | 1: "Added {node} after {selection}" [rules.graph.announce.added_after · P] or "Added {node} — not connected" [rules.graph.announce.added · P]. 2: the confirmation of E37-TC-A10 (C-08), then "Deleted {node} and {n} connections" [rules.graph.announce.deleted · P]. 3: "Renamed to {name}" [rules.graph.announce.renamed · P]. 4: the picker lists every port of the graph, the compatible ones first and each refused one with its sentence beside it; the connect is announced "connected {A} output to {B} input {n}" [rules.graph.announce.connected · P]. 5: the connection list opens and "Disconnected {A} from {B}" [rules.graph.announce.disconnected · P] is said. No operation needs the canvas. A11Y. | `rule.graph_keyboard_authoring_used` `{operation, outline}` per operation | Q05 | pending E37-S05 |
| E37-TC-E08 Outline twins: selection and views (K-06 to K-12) | S05.4 | as E37-TC-E07; a gate with two inputs | 1. Select a row with `Space`, select more rows and press `Ctrl+A`. 2. Collapse and expand a gate row with the row menu ("Collapse" [rules.graph.outline.menu_collapse · P], "Expand" [rules.graph.outline.menu_expand · P]). 3. Press the auto-layout control. 4. Select a row far from the viewport. 5. Use the zoom controls. 6. Open a node with "Inspect" [rules.graph.outline.menu_inspect · P] and with `Enter` on its row. | 1: selection is synchronised both ways with the canvas and the live region says "{n} nodes selected" [rules.graph.announce.selected · P] once, coalesced. 2: "Collapsed {gate} — {n} nodes" [rules.graph.announce.collapsed · P] (`{gate}`, `{n}` the nodes hidden). 3: "Auto-layout applied — Undo auto-layout" [rules.graph.announce.auto_layout · P]; the list is unchanged. 4: the canvas scrolls to the node and nothing is announced for a view change. 5: the readout changes as text and nothing is announced. 6: the drawer opens, titled by the node's name. A11Y. | `rule.graph_keyboard_authoring_used` per operation | Q05 | — |
| E37-TC-E09 Outline twins: tasks (K-13 to K-19) | S05.4 | as E37-TC-E07; a draft with one error | 1. Press `Enter` on a Problems row. 2. Press `Alt+G` (clean graph, then dirty). 3. Press `Save`. 4. Press `Ctrl+Enter`. 5. Press `Simulate`. 6. Undo and redo. 7. Open the inspector's "Position" [rules.graph.inspector.position · P] group and use its four buttons ("Nudge node left" [rules.graph.inspector.nudge_left · P], "Nudge node up" [rules.graph.inspector.nudge_up · P], "Nudge node down" [rules.graph.inspector.nudge_down · P], "Nudge node right" [rules.graph.inspector.nudge_right · P]), then `Ctrl+←` and its siblings in quick succession. | 1: focus moves to the node and the live region speaks its name and the message. 2: the dirty prompt first (E37-TC-D14); the form's region name is spoken. 3: the live region says "Saved as version {n}." [rules.graph.announce.saved · P]. 4: "Validation — {n} errors, {m} warnings" [rules.graph.validation.announce · P]; the keyboard validate's own sentences are "No problems found." [rules.graph.announce.validation_clean · P] and "{count} problems. First: {first} {more} more problems in the problems list." [rules.graph.announce.validation_failed · P] (D05-C4: record which the build speaks). 5: SCR-084 opens and its title is spoken. 6: "Undid {operation}" [rules.graph.announce.undid · P]. 7: each settled burst is announced once, "Moved {name} {parts}, now x {x}, y {y}." [rules.graph.announce.moved_by · P] (`{parts}` such as "40 right and 8 down"); `Ctrl+S` does nothing on SCR-082 (K-15). A11Y. | `rule.graph_keyboard_authoring_used` per operation | Q05 | pending E37-S05 |
| E37-TC-E10 The rest of the map (K-20 to K-25) | S05.4, DA-16, DA-17 | OWNER; the S-form rule with a graph-only node | 1. Press `Alt+L`. 2. Arrow to the Graph-only group. 3. Press `Esc` in a connect, in the inspector and on the canvas, innermost first. 4. Press `Tab` on the canvas. 5. Press `Ctrl+D`, `Alt+↑` and `Alt+↓` on the canvas. 6. Press `Ctrl+Shift+N`. 7. Read the HAR of the whole walk. | 1: `Alt+L` opens the outline once E37-S05 registers it (unregistered at the base) and the list's name and the current row are spoken. 2: the group's count is spoken on entry. 3: each `Esc` closes only the innermost layer and a cancelled connect says "Cancelled" [rules.graph.announce.cancelled · P]. 4: `Tab` only enters and leaves the region. 5: the form's duplicate and reorder chords do nothing on SCR-082. 6: no node is added (the chord clash is E37-D04's C-6). 7: no request to `PUT /rules/{ruleId}/mode`: no chord arms a rule (DA-15). A11Y, HAR. | none | Q05 | pending E37-S05 |
| E37-TC-E11 The outline's structure | S05 scope; DA-4 | OWNER; RULE-GRAPH-NESTED (RC-28) with one orphan condition added | 1. Open the outline. 2. Read its groups and one row's text. 3. Press `Shift+F10` on a row. 4. Type the first letters of a node's name. 5. At 1280 × 800 read the tabs. | 2: the tree is named "Rule outline — {name}" [rules.graph.aria.outline · P] and holds the groups "Check when" [rules.graph.outline.check_when · M], "Only if (all must be true)" [rules.graph.outline.only_if · M], "Then, in order" [rules.graph.outline.then · M], "Graph-only" [rules.graph.outline.group_graph_only · P], "Problems" [rules.graph.outline.group_problems · P] and "Not connected yet" [rules.graph.outline.group_not_connected · P]; each row carries its badge, its name and its connections in text; one roving stop. 3: the row menu opens with Connect…, Disconnect…, Inspect, Rename and Delete (and Move up and Move down on actions). 4: type-ahead focuses the match. 5: the tabs read "Outline" and "Problems (n)" under the canvas. A11Y, SS. | none | Q05 | — |
| E37-TC-E12 One undo history | S05.5, U5.6 | OWNER; an empty draft | 1. Make six edits alternating pointer and keyboard: add by drag, add by `Enter`, connect by drag, connect by keyboard, move by drag and move by `Ctrl+→`. 2. Press `Ctrl+Z` six times. | 2: the edits unwind in one chronological order, newest first, whatever the input; each undo says "Undid {operation}" [rules.graph.announce.undid · P] once. The undo chord is PROPOSED (C-09). A11Y. | none | Q02+ | pending E37-S05 |
| E37-TC-E13 A burst of ten nodes | S05.6 | OWNER; an empty draft; NVDA's speech viewer or the live region's transcript | 1. Add ten nodes in rapid succession by `Enter` on palette entries. 2. Read the live region's transcript. | 2: fewer sentences than operations are spoken, the last names the final state and there is no queue of ten. E37-D04 states the coalescing rule for nudges only (Q-04): record the transcript and its count; ten separate sentences fail S05.6 unless Q-04 rules otherwise. A11Y. | `rule.graph_node_added` ×10 | man | — |
| E37-TC-E14 An edge by keyboard | K-05; S05 scope | OWNER; the S-form rule | 1. Focus the condition and press `→` onto its output port, then `↓` onto the connection. 2. Read the connection's name. 3. Open its menu and read it. 4. Press `Delete`. | 2: the name follows "connection: {A} output to {B} input {n}" [rules.graph.aria.connection · P]. 3: the menu offers "Delete connection" [rules.graph.edge.delete · M]. 4: the connection goes, the live region says "Disconnected {A} from {B}" [rules.graph.announce.disconnected · P] (`{A}` the condition, `{B}` the action) and focus goes to the source node. A11Y. | `rule.graph_keyboard_authoring_used` `{disconnect, canvas}` | Q02+ | — |
| E37-TC-E15 The form toggle is an equal alternative | S05 scope | OWNER; the S-form rule; reduced motion on in the system settings | 1. Read the mode toggle's segments and position. 2. Press `Tab` from the page start. 3. Add an edge and move focus between nodes. | 1: the segments read "Form" [rules.editor.mode.form] and "Graph" [rules.editor.mode.graph] at equal weight; the toggle is the first focus stop (E37-D04 L-1) and reads as an alternative, not a fallback. 3: under reduced motion no edge animation runs and focus moves without transit. SS, A11Y. | none | Q05 | — |
| E37-TC-E16 [R] Write chords while read-only | DA-15; S05 scope | RULE-ARMED-1 as OWNER; VIEWER-1 on a rule it owns; OWNER viewing as MGR-A (the E42 view-as flow) | 1. In each of the three conditions press each write chord: add a node (`Enter` on a palette entry), delete, rename, connect, group, auto-layout, undo and nudge, and validate while viewing as. 2. Read the live region and the notice. 3. Read the HAR, the analytics capture and the audit log. | 1 and 2: every write chord changes nothing and re-shows the one notice once with one polite announcement: "This version is armed and cannot change under the engine. Disarm to edit, or edit as a new draft version." [rules.editor.armed.notice] for the armed rule, "Your role can't change rules." [rbac.permission.change_rules] for the Viewer and "Read-only while viewing as {user}." [rbac.view_as] for view-as (`{user}` MGR-A's display name). 3: no mutation request, no analytics event and no audit row. A11Y, HAR, ANA, AUD. | none | Q02+ | — |
| E37-TC-E17 Moving a node at the edge | K-19 | OWNER; a draft with a node placed at the canvas bound | 1. Focus the node. 2. Press `Ctrl+←` at the left bound, then four times in succession ending at the bound. 3. Read the live region. | 2: a nudge that cannot move says "{name} is at the edge of the canvas, x {x}, y {y}." [rules.graph.announce.at_edge · P] (`{name}`, `{x}`, `{y}`); a burst that ends at the bound adds " Stopped at the edge of the canvas." [rules.graph.announce.stopped_at_edge · P] to its sentence; one sentence per settled burst. A11Y. | none | man | pending E37-S05 |

## 6. Group F — Layout, search and minimap (E37-T02)

Screens SCR-082 only. Every case is mapped, not executed, and waits for E37-T02. The 60-, 121- and
200-node graphs are E37-S01's fixtures (§13.4), loaded unchanged by the staging seed (Q-10).

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-F01 [R] Auto-layout never changes meaning | T02.1, U5.3 | OWNER; RULE-GRAPH-NESTED (RC-28) stored and open in the graph editor | 1. Note the newest `ir_hash` and record every node's position. 2. Press `Ctrl+L`. 3. Read the positions and the live region. 4. Press `Save`. 5. Read `GET /rules/{ruleId}/versions`. | 2 and 3: only positions change; the live region says "Auto-layout applied — Undo auto-layout" [rules.graph.announce.auto_layout · P], with the inline control "Undo auto-layout" [rules.graph.canvas.undo_layout · P] (the main control reads "Auto-layout" [rules.graph.canvas.auto_layout · P]). 4 and 5: the newest `ir_hash` equals step 1's (Q-13 records whether a version row is written). HAR, SS, ANA. | `rule.graph_autolayout_used` `{nodeCount, durationMs}` | Q03 | — |
| E37-TC-F02 Auto-layout is undoable as one step | T02.2, U5.3 | as E37-TC-F01 | 1. Record every node's position. 2. Press `Ctrl+L`. 3. Press `Ctrl+Z` once. 4. Press `Ctrl+L` again and activate the inline undo control instead. | 3: every node returns to its step 1 position in one undo step. 4: the inline control does the same and emits no analytics event. SS, ANA. | none | Q02+ | pending E37-S05 |
| E37-TC-F03 A form-authored rule opens laid out | T02.3 | OWNER; RULE-FORM-1 (RC-11, authored in the form, no stored layout) | 1. Open `/rules/{ruleId}/graph`. 2. Read the canvas. | 2: a readable layout is generated automatically; no two nodes overlap and no edge crosses another beyond what the structure needs (RC-11 is a tree: none). SS. | none | Q02+ | E36-S02 |
| E37-TC-F04 The 60-node review graph | U5.3, DA-6 | OWNER; `FX-REVIEW-60` seeded as a draft rule | 1. Open the rule. 2. Read the canvas tier (`data-tier` on the canvas element). 3. Press `Ctrl+L`. 4. Review the result. | 2: tier `a` and no warning banner. 3 and 4: the layout is arranged without changing the graph; the reviewer records readability. This is the graph E37-D06's DA-6 reviews. SS. | `rule.graph_autolayout_used` | man | FX-REVIEW-60 |
| E37-TC-F05 The tiers and the soft cap | E37-NB-15; FI-15 | OWNER; `FX-REVIEW-60`, `FX-TIER-B-61` and `FX-OVER-BUDGET-121` seeded as draft rules | 1. Open `FX-REVIEW-60` and read the tier. 2. Add one node. 3. Open `FX-OVER-BUDGET-121` and read the tier and the banner. 4. Delete one node. 5. Add one back. 6. At 121 nodes pan, select, connect and press `Save`. | 1: tier `a`. 2: 61 nodes, tier `b`, no banner (`FX-TIER-B-61` is the same graph). 3: tier `c` with a warning banner above the canvas reading "This graph has {n} nodes — above 120 the editor may slow down." [rules.graph.banner.over_budget · P] (`{n}` = 121). 4: 120 nodes: the banner goes and the tier is `b`. 5: the banner returns. 6: every operation works: the cap is a warning, never a block (P-5). SS, A11Y. | none | man | FX-REVIEW-60, FX-TIER-B-61, FX-OVER-BUDGET-121 |
| E37-TC-F06 200 nodes stay usable | T02.4, E37-NB-07 | OWNER; `FX-BUDGET-200` seeded as a draft rule; the browser's performance panel | 1. Open the rule. 2. Pan, zoom, select a node, connect two nodes and open an inspector. 3. Press `Ctrl+L` and watch the page. 4. Turn on reduced motion and press `Ctrl+L` again. | 2: every operation works with no visible stall (E37-Q04 measures P-1 to P-3). 3: a determinate progress affordance shows while the layout runs, the page never freezes and the transition completes within 400 ms. 4: the nodes reposition without transit. FI-15. SS, T. | `rule.graph_autolayout_used` | Q04 | FX-BUDGET-200 |
| E37-TC-F07 Search, jump and announce | T02.5 | OWNER; RULE-GRAPH-NESTED (RC-28) with one node renamed to a known name | 1. Find the node search (record where the build places it). 2. Search by a node's name, then by a metric and then by an action id. 3. Move through the results by keyboard and activate one. 4. Open the outline and search there. | 2: results filter by name, metric or action id. 3: focus moves to the node, the viewport centres on it and the move is announced (the sentence is not in the deck: Q-08). 4: the same results are reachable in the outline. SS, A11Y. | `rule.graph_search_used` | Q02+ | — |
| E37-TC-F08 The minimap | T02 scope | OWNER; `FX-BUDGET-200` with three nodes in error | 1. Read the minimap. 2. Click and drag its viewport rectangle. 3. Look for error markers. 4. Press `Tab` through the page. 5. Read the accessibility tree around it. | 1 and 2: the rectangle tracks the viewport and a click or drag navigates. 3: nodes in error carry severity dots that serve as the navigation aid. 4 and 5: the minimap is `aria-hidden`, holds no focusable and has no tab stop; the outline is its equivalent. SS, A11Y. | none | man | FX-BUDGET-200 |
| E37-TC-F09 Layout persists | E37-NB-27, U1.5 | OWNER; RULE-LAYOUT-1 | 1. Move one node and save. 2. Reload. 3. Switch to the form and back. 4. Read the positions after each step and the newest `ir_hash`. | 2 to 4: the moved position survives the reload, the switch and the save and the `ir_hash` never changes (Q-13 records the version rows). SS, HAR. | `rule.graph_saved` | Q03 | E36-S02 |

## 7. Group G — Roles, flows and crafted requests

Roles are OWNER, MGR-A, MGR-SIM, MGR-B and VIEWER-1 (§13.1). The flow is F10 (`13` §10). The
crafted-request cases are the black-box half of the ticket's role coverage; the E36 abuse catalogue
(`AC-RA-03`, `AC-RA-12`, `AC-RA-13`, `AC-RA-19`, `AC-RA-22`) is cited, not copied, and E37-X02
executes it. Every case is mapped, not executed, and waits for E37-S01 and E37-S02 as its row says.
A crafted call is made with `curl` under the role's session and CSRF token; a mode call also carries
a fresh `Idempotency-Key` (`setRuleMode` requires one, and a call without it answers 400
`idempotency_key_required` before any arming check). Every audit read is made as OWNER (§0).

<!-- prettier-ignore -->
| ID | Covers | Preconditions | Steps | Expected | Events | Auto | Needs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E37-TC-G01 [R] The graph-start flow | `13` §10 (F10) | OWNER; ACC-1; SYM-REC | 1. Open `/rules/new` and choose Graph. 2. Author the rule of E37-TC-A04. 3. Press `Validate`, then `Save`. 4. Read the rule's mode. 5. Press `Arm…` and read SCR-085. 6. Cancel. 7. Read `GET /rules/{ruleId}` and the audit log. | 3: the rule saves as a draft, simulate-only (a create lands disarmed). 5: `Arm…` opens SCR-085 (environment, scope confirmation and safety summary; Live needs a step-up). 7: the rule is not armed and the audit log holds no arming row. HAR, SS, AUD. | `rule.graph_saved`, `rule.roundtrip_verified` | Q02-1 | — |
| E37-TC-G02 Entry from the rules list | `13` §10 | OWNER; RULE-FORM-1 | 1. Open `/rules`. 2. Open the row menu of RULE-FORM-1 and choose its graph editor. 3. Read the page. 4. On `/rules/new` read the start choice. | 2 and 3: `/rules/{ruleId}/graph` opens with the rule laid out (E37-TC-F03). 4: the start choice offers Graph beside Form. SS. | none | Q02+ | E36-S02 |
| E37-TC-G03 An out-of-scope deep link | S01.4 | MGR-B (ACC-3 only); OWNER; a rule scoped to ACC-1 | 1. As MGR-B open `/rules/{ruleId}/graph` for the ACC-1 rule. 2. Read the page and the HAR. 3. Read `GET /admin/audit`. | 2: no rule content is rendered or returned (no name, node, scope or account id in the DOM or in any response body); the refusal is a 403 or the unseen 404 of a rule the caller does not own (E36's AC-RA-12 expects the 404, S01.4 says 403: Q-09). 3: record the audit row if one is written. HAR, SS, AUD. | `rbac.denied` | Q02-7 | — |
| E37-TC-G04 [R] The Viewer's read-only view | S01.4 | VIEWER-1 (`rules:read`; read grant ACC-1); a rule of ACC-1 that VIEWER-1 owns | 1. Open `/rules/{ruleId}/graph`. 2. Read the notice and attempt every write: a palette entry, "+ Add node", an inspector field, a row menu's Connect, Rename and Delete, `Save` and `Arm…`. 3. Read `Disarm`, `Delete rule…` and `Discard changes`. 4. Press `Validate` and read the chip. | 1: the editor opens read-only (the route is shown, C-01; on a rule it does not own the base answers 404, recorded under C-01) with the one notice "Your role can't change rules." [rbac.permission.change_rules]. 2: every write is T2 pointing at the notice, changes nothing and sends no request. 3: `Disarm` and `Delete rule…` are T2 with the same key; `Discard changes` is enabled when there is something to discard. 4: validation and compile are `rules:read` calls and are permitted; the chip shows the word the compile returns (Q-11 asks what shows when it fails). FI-14. SS, A11Y, HAR. | none | Q02-7 | — |
| E37-TC-G05 [R] A Viewer's crafted write | S01.4 | VIEWER-1; OWNER (step 5 and the audit); a rule of ACC-1 with its versions listed | 1. `PUT /rules/{ruleId}` with a valid `If-Match` and body. 2. `POST /rules`. 3. `PUT /rules/{ruleId}/mode` to simulate. 4. `DELETE /rules/{ruleId}`. 5. As OWNER read `GET /rules/{ruleId}` (`active_version_id` decides) and `GET /rules/{ruleId}/versions` (`is_active`; a list without it is recorded against `22`). 6. Read `GET /admin/audit`. | 1 to 4: 403 each, with no rule content. 5: versions and active version unchanged: no state change. 6: one `rbac.denied` row per refused call. The two read-class calls (`POST /rules/validate`, `POST /rules/{ruleId}/compile`) answer 200: they need `rules:read`. HAR, AUD. | `rbac.denied` ×4 | X02 | — |
| E37-TC-G06 [R] A crafted save for an ungranted account | S02.4 | MGR-A (ACC-1, ACC-2); ACC-3; a rule of ACC-1 that MGR-A created | 1. `PUT /rules/{ruleId}` with a valid `If-Match` and a body whose scope names ACC-3. 2. Repeat with ACC-3 in an action parameter. 3. Read `GET /rules/{ruleId}/versions`. 4. Read `GET /admin/audit`. | 1 and 2: 403 each and nothing is stored. 3: versions unchanged: no state change. 4: one audit row per refusal under a name in §12's denial row. HAR, AUD. | `rbac.denied` ×2 | X02 | — |
| E37-TC-G07 [R] A crafted order action | S02.4, U3.3 | MGR-SIM (ACC-1, no `orders:write`); MGR-A (ACC-1, ACC-2, `orders:write`, no `rules:arm_live`); a draft of ACC-1 that MGR-SIM created; RULE-ARMABLE-1; RULE-ARMABLE-2 | 1. As MGR-SIM `PUT /rules/{ruleId}` with a valid `If-Match`, saving a `place_order` action on the draft (S02.4's "a crafted save containing one", read as the order-placing action; the out-of-scope reading is E37-TC-G06). 2. As MGR-SIM `PUT /rules/{ruleId}/mode` to armed on RULE-ARMABLE-1 (demo) with a fresh `Idempotency-Key`. 3. As MGR-A the same call on RULE-ARMABLE-2 (demo and live). 4. Read `GET /rules/{ruleId}` for each rule and `GET /admin/audit`. | 1: the save is accepted and the rule stays disarmed (AC-RA-19). 2: 403 `orders_write_required`: the checks before it (a valid version, no safety warning, the simulation run, the promotion gate) pass on the primed rule, and a manager without `orders:write` is refused before any live check. 3: 403, the code recorded: `permission_required` (`22`'s code) or `forbidden` with a `rule_scope_denied` row from the route's scope check, which runs first; MGR-A holds `orders:write`, so the refusal is the missing `rules:arm_live` and the step-up check is not reached. 4: neither primed rule is armed, so no state change; one refusal row per call, `rule.mode_refused` (step 2) and `rule_scope_denied` or `rule.mode_refused` (step 3), which §12's `rbac.denied` row lists as the stand-ins. HAR, AUD. | `rule.mode_refused` (step 2); `rule_scope_denied` or `rule.mode_refused` (step 3) | X02 | RULE-ARMABLE-1, RULE-ARMABLE-2 |
| E37-TC-G08 Arming without a step-up | S03 scope | OWNER; RULE-ARMABLE-2 (scope includes live) | 1. As OWNER `PUT /rules/{ruleId}/mode` to armed on RULE-ARMABLE-2 with a fresh `Idempotency-Key` and no fresh live step-up. 2. Repeat without the `Idempotency-Key`. 3. Read `GET /rules/{ruleId}` and `GET /admin/audit`. 4. Walk the editor, press `Arm…` and read the HAR. | 1: 403 `step_up_required`: the OWNER holds `rules:arm_live` and every earlier check passes on the primed rule. 2: 400 `idempotency_key_required`, before every arming check. 3: the rule is not armed; the route's scope check writes the high-severity `rule_live_scope_armed` row ahead of each call's refusal, so step 1's refusal has two rows (that one, then `rule.mode_refused`). 4: the editor never calls `PUT /rules/{ruleId}/mode`; `Arm…` only opens SCR-085. HAR, AUD. | `rule_live_scope_armed`, `rule.mode_refused` | X02 | RULE-ARMABLE-2 |
| E37-TC-G09 A save without `If-Match` | D02-G11 | OWNER; a saved draft | 1. `PUT /rules/{ruleId}` with a valid body and neither `If-Match` nor `expected_version`. 2. Read `GET /rules/{ruleId}/versions`. 3. In the editor press `Save` and read the HAR. | 1: 400. 2: no new version. 3: the editor's save always carries `If-Match` (E37-TC-A04, E37-TC-A13). HAR. | none | X02 | — |
| E37-TC-G10 Scope withdrawn while editing | AC-RA-13; Q06 C4 | OWNER; MGR-A (ACC-1, ACC-2); a rule of ACC-1 that MGR-A created, open in MGR-A's editor | 1. As OWNER withdraw ACC-1 from MGR-A. 2. In MGR-A's editor change the rule and press `Save`. 3. Reload MGR-A's editor and read the palette, the scope selector, `GET /rules/accounts` and `GET /rules/vocabulary`. 4. Read `GET /admin/audit`. | 2: 403 and nothing is stored. 3: ACC-1 is gone from the selector and from `GET /rules/accounts`, and its actions from the vocabulary. 4: one audit row for the refused save. HAR, AUD. | `rbac.denied` | man | — |
| E37-TC-G11 [R] Live arming is the owner's | S03 scope | MGR-A (ACC-1); OWNER; RULE-ARMABLE-2 (a rule of ACC-1 whose scope includes live, created by MGR-A) | 1. As MGR-A open the rule and read `Arm…`. 2. As OWNER open it and press `Arm…`. 3. Cancel. | 1: `Arm…` is T2 with "Only the owner can arm rules against live." [rbac.owner_only.arm_live], ahead of the compile-state keys. 2: it opens SCR-085 and the editor arms nothing itself. SS, A11Y, HAR. | none | Q02-7 | RULE-ARMABLE-2 |

## 8. State × role matrix

Thirteen SCR-082 states by four roles: the ticket's nine plus Round-trips ✓, orphan or dangling,
conflict on save and over budget, which E37-D02 draws as frames of their own. "Checking" and "stale"
are chip modifiers (E37-TC-D03); viewing as another user is a treatment of every frame (E37-TC-E16).

Roles (§13.1): OWNER (`*`); MGR-A (`rules:write`, `orders:write`, ACC-1 and ACC-2); MGR-SIM
(`rules:write`, no `orders:write`, ACC-1); VIEWER-1 (`rules:read`, read grant ACC-1). Codes: `W`
writes enabled; `Ws` the same with order-placing actions in the simulate framing; `RO` read only,
every write T2 with `rbac.permission.change_rules` pointing at the one notice; `NR` not reachable.
Control classes are E37-D02 §3's: T1 enabled; T2 disabled with a visible reason (lock glyph,
`aria-disabled`, the reason in the DOM); validity look (disabled by graph validity: no lock, its own
reason); O an outcome chip. `Arm…` is T1 into SCR-085's override step for the OWNER and T2
`rule.arm.simulate_first` on a draft for a manager (E37-D02 §2), unless a state key comes first
(`rule.save.mismatch`, then `rule.arm.unverified`). **A denied entry names its attempt and asserts
403, no state change (versions and active version unchanged) and one `rbac.denied` audit row.**

<!-- prettier-ignore -->
| # | State (frame) | OWNER | MGR-A | MGR-SIM | VIEWER-1 |
| --- | --- | --- | --- | --- | --- |
| 1 | empty (FI-1) | W · `Validate` and `Simulate` T1; `Save` and `Arm…` take the validity look (`rules.editor.validation.no_action`, `rules.editor.validity.arm`) · E37-TC-A01 | W · the same controls and classes as the OWNER · E37-TC-A01 | Ws · the same controls; order-placing entries in the simulate framing · E37-TC-A01, E37-TC-B13 | RO · palette entries, "+ Add node", `Save`, `Arm…` T2; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G04, E37-TC-G05 |
| 2 | editing (FI-2) | W · `Validate`, `Simulate`, `Save` T1; `Arm…` T1 into SCR-085; chip O · E37-TC-A04 | W · `Validate`, `Simulate`, `Save` T1; `Arm…` T2 `rule.arm.simulate_first`; chip O; an action naming ACC-3: 403 · no state change · one `rbac.denied` audit row · E37-TC-A04, E37-TC-G06 | Ws · as MGR-A with the simulate framing; a crafted arm of the primed `place_order` rule: 403 · no state change · one `rbac.denied` audit row (written as `rule.mode_refused`, §12) · E37-TC-B13, E37-TC-G07 | RO · every write T2, `Discard changes` enabled when dirty; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G04, E37-TC-G05 |
| 3 | invalid connection (FI-3) | W · the refusal is validation, never T2; `Save` T1; `Arm…` T1 · E37-TC-A07 | W · the refusal is validation, never T2; `Save` T1; `Arm…` T2 `rule.arm.simulate_first` · E37-TC-A07 | Ws · as MGR-A · E37-TC-A07 | NR · ports are inert and a connect cannot start; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G05 |
| 4 | cycle detected (FI-4) | W · `Save` and `Arm…` take the validity look (`rules.editor.validity.save`, `rules.editor.validity.arm`) · E37-TC-C02 | W · the same validity look, never T2 · E37-TC-C02 | Ws · the same validity look · E37-TC-C02 | NR · a cycle is never stored and cannot be drawn; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G05 |
| 5 | unsupported in form view (FI-7, FI-12, FI-5) | W · `Validate`, `Simulate`, `Save` T1; `Arm…` T1; the chip opens the panel, its rows and "Open the form view" are T1 · E37-TC-D04, E37-TC-D05 | W · as OWNER with `Arm…` T2 `rule.arm.simulate_first` · E37-TC-D04, E37-TC-D05 | Ws · as MGR-A · E37-TC-D04 | RO · the panel is readable and its rows focus nodes (T1); every write T2; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-D05, E37-TC-G05 |
| 6 | round-trip mismatch (FI-8, FI-16) | W · `Save` and `Arm…` T2 `rule.save.mismatch` (one reason beside the pair); "View diff" and `Discard changes` T1; the dialog offers two choices · E37-TC-D09, E37-TC-D10 | W · as OWNER · E37-TC-D09, E37-TC-D10 | Ws · as OWNER · E37-TC-D10 | RO · "View diff" T1; the two choices, `Save` and `Arm…` T2; a crafted resolving save: 403 · no state change · one `rbac.denied` audit row · E37-TC-D09, E37-TC-G05 |
| 7 | not verified (FI-9) | W · `Save` T1 (a draft only); `Arm…` T2 `rule.arm.unverified`; chip O · E37-TC-C09 | W · as OWNER · E37-TC-C09 | Ws · as OWNER · E37-TC-C09 | RO · chip only, writes T2 (Q-11 asks what the chip shows when a Viewer's compile fails); crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G04, E37-TC-G05 |
| 8 | engine unavailable (FI-13) | W · palette, pickers, "+ Add node", `Validate`, `Simulate`, `Save` and `Arm…` T2 pointing at the banner; `Discard changes` T1 · E37-TC-A15 | W · as OWNER · E37-TC-A15 | Ws · as OWNER · E37-TC-A15 | RO · the banner shows and every write is T2 with the permission reason; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-A15, E37-TC-G05 |
| 9 | read-only, armed (FI-14) | W · every write T2 pointing at the armed notice; `Disarm` replaces `Arm…` (T1); "Disarm to edit" and "Edit as a new draft version" T1 · E37-TC-A16, E37-TC-D11 | W · as OWNER · E37-TC-D11 | Ws · as OWNER · E37-TC-D11 | RO · every write T2, `Disarm`, `Delete rule…` and both armed-notice controls T2; crafted save or disarm: 403 · no state change · one `rbac.denied` audit row · E37-TC-G04, E37-TC-G05 |
| 10 | Round-trips ✓ (FI-6) | W · `Validate`, `Simulate`, `Save` T1; `Arm…` T1; chip O · E37-TC-D01 | W · as OWNER with `Arm…` T2 `rule.arm.simulate_first` · E37-TC-D01 | Ws · as MGR-A · E37-TC-D01 | RO · chip O, every write T2; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-D02, E37-TC-G05 |
| 11 | orphan or dangling (FI-10) | W · while warnings: `Save` and `Arm…` T1; once a save turns them into errors the validity look · E37-TC-C04, E37-TC-C06 | W · while warnings: `Save` T1, `Arm…` T2 `rule.arm.simulate_first`; then the validity look · E37-TC-C06 | Ws · as MGR-A · E37-TC-C06 | NR · a stored rule cannot hold either; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-G05 |
| 12 | conflict on save (FI-11) | W · the dialog offers Reload and Cancel only, no overwrite · E37-TC-A13 | W · as OWNER · E37-TC-A13 | Ws · as OWNER · E37-TC-A13 | NR · a Viewer cannot save; crafted save: 403 · no state change · one `rbac.denied` audit row · E37-TC-G05 |
| 13 | over budget (FI-15) | W · a warning banner, never a block; `Validate`, `Simulate`, `Save` T1; `Arm…` T1 · E37-TC-F05 | W · as OWNER with `Arm…` T2 `rule.arm.simulate_first` · E37-TC-F05 | Ws · as MGR-A · E37-TC-F05 | RO · the banner shows, every write T2; crafted write: 403 · no state change · one `rbac.denied` audit row · E37-TC-F05, E37-TC-G05 |

## 9. Boundary and negative catalogue

Rows E37-NB-01 to E37-NB-11 are the ticket's eleven; the rest come from E35's boundaries (BD-01 to
BD-03), the performance tiers, the contract's limits and the hostile-input references. "Catalogue
only" means no case runs the row step by step: E37-Q06's charter or E37-X02 does. The `Q06` column
names the charter of E37-Q06 that should explore the row: C1 break the round-trip, C2 abuse the
graph, C3 mixed modality, C4 permission and environment edges.

<!-- prettier-ignore -->
| NB | Input | Expected observation | Source | Case | Q06 |
| --- | --- | --- | --- | --- | --- |
| E37-NB-01 | a second trigger | the entry is absent or the insertion refused; the graph keeps one trigger and stays valid (Q-01) | S02.5; E37-D02 §7 | E37-TC-B04 | C2 |
| E37-NB-02 | a connection that closes a loop | refused at the target; the cycle drawn as a path; no IR holds it | S03.2; US-RULE-005 | E37-TC-C02, E37-TC-C03 | C2 |
| E37-NB-03 | a node that reaches no action | a warning while editing, a blocking error on save | S03.3; US-RULE-005 | E37-TC-C04, E37-TC-C06 | C2 |
| E37-NB-04 | a required input left unconnected | the same warning, then error | S03.3; US-RULE-005 | E37-TC-C05, E37-TC-C06 | C2 |
| E37-NB-05 | `flatten_all_positions` without its acknowledgement | `Save` is unaffected; `Arm…` takes the validity look until the box is ticked; a crafted arm without it is 422 `acknowledgement_required` | E36-D02:187; `14` SCR-085 (C-17) | E37-TC-B10 | C2 |
| E37-NB-06 | an action scoped to an account the caller cannot trade | not listed in the editor; a crafted save is 403 with an audit row | S02.4 | E37-TC-G06, E37-TC-B13 | C4 |
| E37-NB-07 | a 200-node graph | every operation works; layout shows progress and never freezes | T02.4; `14` SCR-082 | E37-TC-F06 | C2 |
| E37-NB-08 | save of an empty rule | refused: the rule needs an action | `14` SCR-081; E37-D02 §3 | E37-TC-A01 | C2 |
| E37-NB-09 | two tabs save one rule | `412 version_conflict`, one new version, no overwrite | S01.5, S04.7 | E37-TC-A13, E37-TC-D13 | C1 |
| E37-NB-10 | a rule stored under an older IR version | migrated once, its own version entry, disarmed until reviewed | U1.3, U6.8 | E37-TC-D15 | C1 |
| E37-NB-11 | the vocabulary or engine unavailable | banner, writes T2, chip Not verified | `14` SCR-082; E37-D02 §3 | E37-TC-A15 | C4 |
| E37-NB-12 | a logic gate with 32 inputs, then a 33rd | 32 accepted; the 33rd refused, by the editor or by the server naming the path (E35 BD-01) | `24` §11.3 through E35 | catalogue only | C2 |
| E37-NB-13 | an arithmetic node with 8 operands, then a 9th | the same (E35 BD-02) | `24` §11.3 through E35 | catalogue only | C2 |
| E37-NB-14 | 10 action nodes, then an 11th | 10 accepted; the 11th refused by the server with its path (E35 BD-03) | `24` §11.3 through E35 | E37-TC-C11 | C2 |
| E37-NB-15 | 120 and 121 nodes | the banner shows at 121 only; nothing is blocked | `14` SCR-082 Performance | E37-TC-F05 | C2 |
| E37-NB-16 | a crafted compile at 1,000 and at 1,001 condition nodes | 1,000 accepted; 1,001: `compileRule` answers `422 rule_ir_invalid`, `validateRule` answers 200 with `valid: false` and one `schema_error` at path `conditions`; the form core's own bound is 200 and 201 (AC-RA-16; Q-16) | `22` `compileRule`, `validateRule` | catalogue only | C2 |
| E37-NB-17 | a connection from a node to itself | refused with the self-loop sentence | E37-D05 §8.1 | E37-TC-A08 | C2 |
| E37-NB-18 | an edge that already exists | refused with the duplicate sentence | E37-D05 §8.1 | E37-TC-A08 | C2 |
| E37-NB-19 | a second edge into an occupied single-slot input | refused with the occupied sentence | E37-D02 §6 | E37-TC-A08 | C2 |
| E37-NB-20 | a node deleted while a connect is pending | the connect aborts cleanly; no edge points at a missing node (E37-NB-33's unknown-node sentence is the protocol's answer) | E37-D02 §6 | catalogue only | C2 |
| E37-NB-21 | undo after a save | the edits unwind; no saved version is rewritten (versions never rewind) | `22` `updateRule` | catalogue only | C2 |
| E37-NB-22 | two nodes with one name, and a very long name | the duplicate reads "{name} (node {index})" [rules.graph.aria.disambiguated · P]; the long name stays inside the node's fixed box | E37-D02 §5 | catalogue only | C3 |
| E37-NB-23 | a node renamed to an empty name | refused or reverted; no node is left without an accessible name | E37-D04 §5 | catalogue only | C2 |
| E37-NB-24 | the per-user rate limit on compile and validate | `429`, never "valid", no crash, no audit row | `22` `validateRule` | E37-TC-C12 | C1 |
| E37-NB-25 | markup, bidi controls and `javascript:` text in a name and a comment | rendered as text, never as markup or a link (AC-RA-05) | the E36 abuse cases | catalogue only | C2 |
| E37-NB-26 | a foreign rule document pasted onto the canvas | refused by the editor's checks or the server's; nothing partial is stored | E37-Q06 charter 2 | catalogue only | C2 |
| E37-NB-27 | a layout-only save | the `ir_hash` is unchanged (Q-13 records the version row) | US-RULE-001 | E37-TC-F09, E37-TC-B14 | C1 |
| E37-NB-28 | executable-looking text in a comment or a layout | ignored by the evaluator and outside the hash (AC-RA-04) | the E36 abuse cases | catalogue only | C2 |
| E37-NB-29 | a trigger wired straight to an action | refused: "A trigger can't run an action without a condition." [rules.graph.connect.trigger.action · P] | E37-D05 §8.1 | E37-TC-A06 | C2 |
| E37-NB-30 | `Ctrl+Shift+N` on the canvas | adds no node | DA-17 | E37-TC-E10 | C3 |
| E37-NB-31 | the feature flag toggled mid-session | the open editor keeps working; the next navigation shows the absence and its note; record both | E37-Q06 charter 4 | catalogue only | C4 |
| E37-NB-32 | the kill switch engaged mid-edit | no rule acts or arms while it is engaged (C-2.21); record what the editor shows and that edits and drafts still save | `30` §7.3 criterion 7 | catalogue only | C4 |
| E37-NB-33 | the five protocol refusals: no output, not an input, no source, no target, unknown node | the sentences "This node has no output." [rules.graph.refusal.no_output · P], "That port is not an input of this node." [rules.graph.refusal.no_input · P], "Choose an output port first." [rules.graph.refusal.no_source · P], "Choose an input port first." [rules.graph.refusal.no_target · P] and "That node is no longer in the rule." [rules.graph.refusal.unknown_node · P]; the sources describe no screen path to them | E37-D05 §8.1 | catalogue only | C2 |

## 10. The connect grid

The 36 sentences `PORT_COMPAT` gives for an output of the row's type onto an input of the column's
type, printed from the deck. A cell reads "connects" for the seven compatible pairs; every other
cell is the sentence shown at the target and spoken by the keyboard connect. E37-TC-A06 marks each
pair `R` or `U` on a run; the check script compares every cell with the deck.

<!-- prettier-ignore -->
| from \ to | boolean | number | price | side | action | trigger |
| --- | --- | --- | --- | --- | --- | --- |
| **boolean** | connects | A true or false result can't be used as a number. | A true or false result can't be used as a price. | A true or false result can't be used as a side. | connects | A true or false result can't connect to a trigger. |
| **number** | A number can't be used as true or false. | connects | connects | A number can't be used as a side. | A number can't run an action. | A number can't connect to a trigger. |
| **price** | A price can't be used as true or false. | connects | connects | A price can't be used as a side. | A price can't run an action. | A price can't connect to a trigger. |
| **side** | A side can't be used as true or false. | A side can't be used as a number. | A side can't be used as a price. | connects | A side can't run an action. | A side can't connect to a trigger. |
| **action** | An action can't be used as true or false. | An action can't be used as a number. | An action can't be used as a price. | An action can't be used as a side. | An action can't run another action. | An action can't connect to a trigger. |
| **trigger** | A trigger can't be used as true or false. | A trigger can't be used as a number. | A trigger can't be used as a price. | A trigger can't be used as a side. | A trigger can't run an action without a condition. | A trigger can't connect to another trigger. |

## 11. The keyboard inventory

K-01 to K-25 are E37-D04 §4's map. Binding: D decided in the shipped keymap, P proposed. Each row is
one pass and one fail in a walk of the named cases; the Result column stays empty until a run fills
it (`pass`, `fail` or `blocked`, with the build sha). Zero operations may be reachable only on the
canvas (E37-TC-E07 to E37-TC-E10).

<!-- prettier-ignore -->
| K | Operation | Binding | Outline twin | Announcement | Cases | Result |
| --- | --- | --- | --- | --- | --- | --- |
| K-01 | add a node | `Enter` on a palette entry (D); `Ctrl+Shift+N` (P, clashes with a global chord, E37-D04 C-6) | "+ Add node", then the palette listbox | "Added {node} after {selection}" [rules.graph.announce.added_after · P] or "Added {node} — not connected" [rules.graph.announce.added · P] | E37-TC-A05, E37-TC-E07 | |
| K-02 | delete a node | `Del` (D; the keymap confirms always, C-08) | row menu Delete | "Deleted {node} and {n} connections" [rules.graph.announce.deleted · P] | E37-TC-A10, E37-TC-E07 | |
| K-03 | rename | `F2` (D) | row menu Rename; `F2` on a row | "Renamed to {name}" [rules.graph.announce.renamed · P] | E37-TC-E07 | |
| K-04 | connect | `Enter` on a port, the arrows, `Enter` (built in the keyboard core) | row menu Connect…, the target picker | "connected {A} output to {B} input {n}" [rules.graph.announce.connected · P] | E37-TC-E03, E37-TC-E07 | |
| K-05 | disconnect | `Delete` on a connection | row menu Disconnect… | "Disconnected {A} from {B}" [rules.graph.announce.disconnected · P] | E37-TC-E14, E37-TC-E07 | |
| K-06 | select | `Space` on a node or a row | the row's selection, both ways | "{n} nodes selected" [rules.graph.announce.selected · P] | E37-TC-E08 | |
| K-07 | multi-select | `Space` on more nodes; `Ctrl+A` (D) | the same | "{n} nodes selected" [rules.graph.announce.selected · P] | E37-TC-A10, E37-TC-E08 | |
| K-08 | group | `Ctrl+G` (D) | row menu Collapse or Expand on a gate | "Collapsed {gate} — {n} nodes" [rules.graph.announce.collapsed · P] | E37-TC-E08 | |
| K-09 | auto-layout | `Ctrl+L` (D); the foot row's control | the same control | "Auto-layout applied — Undo auto-layout" [rules.graph.announce.auto_layout · P] | E37-TC-E08, E37-TC-F01 | |
| K-10 | pan | none needed: the viewport follows focus; `Space` and drag (D) is the pointer's | selecting a row scrolls the canvas to the node | none (a view change) | E37-TC-E02, E37-TC-E08 | |
| K-11 | zoom | the foot row's controls (P); `Ctrl+0` (P, no binding, E37-D04 C-4) | not needed | none; the readout text changes | E37-TC-A09, E37-TC-E08 | |
| K-12 | open the inspector | `Enter` on a node (D) | row menu Inspect; `Enter` on a row | the drawer's title | E37-TC-B15, E37-TC-E08 | |
| K-13 | jump to a diagnostic | `Enter` on a Problems entry | the Problems group's row | the node's name and the message | E37-TC-C01, E37-TC-E09 | |
| K-14 | switch editor | `Alt+G` (D), the dirty prompt first | the same | the form's region name | E37-TC-D14, E37-TC-E09 | |
| K-15 | save | `Save` in the action bar; `Ctrl+S` is SCR-081's only | the same | "Saved as version {n}." [rules.graph.announce.saved · P] (P; E37-D04 records none) | E37-TC-A04, E37-TC-E09 | |
| K-16 | validate | `Ctrl+Enter` (D); `Validate` | the same | "Validation — {n} errors, {m} warnings" [rules.graph.validation.announce · P] | E37-TC-C01, E37-TC-E09 | |
| K-17 | simulate | `Simulate` in the action bar, opening SCR-084 | the same | SCR-084's title | E37-TC-E09 | |
| K-18 | undo or redo | `Ctrl+Z`; `Ctrl+Y` (P: `rules.undo` and `rules.redo` are unregistered, C-09) | the same stack | "Undid {operation}" [rules.graph.announce.undid · P] | E37-TC-A11, E37-TC-E12 | |
| K-19 | move a node | `Ctrl+←` and its siblings (D); the 8 and 32 px steps and the sentence (P) | not needed: position is cosmetic | "Moved {name} {parts}, now x {x}, y {y}." [rules.graph.announce.moved_by · P] | E37-TC-E09, E37-TC-E17 | |
| K-20 | open the outline | `Alt+L` (P, unregistered) | none | the list's name and the current row | E37-TC-E10 | |
| K-21 | enumerate badged nodes | `Alt+L`, then the arrows to the Graph-only group | the Graph-only group | the group's count on entry | E37-TC-E10, E37-TC-D05 | |
| K-22 | cancel | `Esc`, innermost first | the same | "Cancelled" [rules.graph.announce.cancelled · P] | E37-TC-E04, E37-TC-E10 | |
| K-23 | cycle nodes | `Tab`, rebound to the arrows on SCR-082 so that it only enters and leaves | none (the outline is its own stop) | none | E37-TC-E01, E37-TC-E10 | |
| K-24 | duplicate | `Ctrl+D`, the form's; none on SCR-082 | none | none | E37-TC-E10 | |
| K-25 | reorder | `Alt+↑` and `Alt+↓`, the form's; none on SCR-082 | none | none | E37-TC-E10 | |

## 12. Audit and analytics events

The audit step (§0) passes when the event appears once per causing action under any name in its row;
record which. The six events of E37-D05 §10 come first; events only the stories name are marked
`[story]`. "Registered at the base" says what the build writes today (re-check at run time); an
event not yet registered is expected under its own name once its story ships, and until then under
the registered stand-in of its row.

<!-- prettier-ignore -->
| Event | Source | Properties | Kind | Registered at the base | Cases |
| --- | --- | --- | --- | --- | --- |
| `rule.graph_saved` | `14` SCR-082; E37-D05 §10 | none beyond the version the server writes | audit | no; a save writes `rule.updated`, a create `rule.created` | E37-TC-A04, E37-TC-A12, E37-TC-A13, E37-TC-B14, E37-TC-D07, E37-TC-D12, E37-TC-D14, E37-TC-E06, E37-TC-F09, E37-TC-G01 |
| `rule.roundtrip_verified` | `14` SCR-082; E37-D05 §10 | `{result}`: identical, graph_only_construct, mismatch or unverified | audit | no | E37-TC-A04, E37-TC-C09, E37-TC-D01, E37-TC-D02, E37-TC-D04, E37-TC-D09, E37-TC-D17, E37-TC-G01 |
| `rule.roundtrip_mismatch_resolved` | `14` SCR-082; E37-D05 §10 | `{choice}`: keep_form or keep_graph | audit | no | E37-TC-D10 |
| `rule.graph_node_added` | E37-D05 §10; E37-S01, E37-S02 | none in E37-D05 §10; `{type}` in the stories (C-11) | analytics | no | E37-TC-A04, E37-TC-A05, E37-TC-B03, E37-TC-B05, E37-TC-B08, E37-TC-D04, E37-TC-E13 |
| `rule.graph_autolayout_used` | E37-D05 §10; E37-T02 | none in E37-D05 §10; `{nodeCount, durationMs}` in E37-T02 (C-11); the inline undo emits nothing | analytics | no | E37-TC-F01, E37-TC-F04, E37-TC-F06 |
| `rule.graph_keyboard_authoring_used` | E37-D05 §10; E37-D04 | `{operation, surface}`, surface canvas or outline (PROPOSED) | analytics | no | E37-TC-E03, E37-TC-E06, E37-TC-E07, E37-TC-E08, E37-TC-E09, E37-TC-E14 |
| `rule.graph_edge_added` [story] | E37-S01 | none | analytics | no | E37-TC-A04, E37-TC-E03 |
| `rule.graph_connect_rejected` [story] | E37-S01 | `{fromType, toType}` | analytics | no | E37-TC-A06, E37-TC-A07, E37-TC-A08 |
| `rule.graph_validation_run` [story] | E37-S03 | `{errors, warnings, durationMs}` | analytics | no | E37-TC-C01, E37-TC-C07, E37-TC-C11 |
| `rule.graph_cycle_rejected` [story] | E37-S03 | none | analytics | no | E37-TC-C02 |
| `rule.graph_save_blocked` [story] | E37-S03 | `{reason}` | analytics | no | E37-TC-C06 |
| `rule.graph_estimated_metric_used` [story] | E37-S02 | `{metric}` | analytics | no | E37-TC-B06 |
| `rule.graph_inspector_opened` [story] | E37-S02 | none | analytics | no | E37-TC-B15 |
| `rule.roundtrip_integrity_failure` [story] | E37-S04 | `{hashBefore, hashAfter, ruleId}` | high-severity telemetry | no | E37-TC-D08 |
| `rule.graph_keyboard_connect_rejected` [story] | E37-S05 | `{fromType, toType}` | analytics | no | E37-TC-E04 |
| `rule.graph_search_used` [story] | E37-T02 | none | analytics | no | E37-TC-F07 |
| `rule.saved` | `14` SCR-081 (the form editor's save) | the version written | audit | the audit step also accepts `rule.updated` | E37-TC-D13 |
| `rbac.denied` | the backend; `22` | the refused call | audit | yes; a scope or arming refusal may instead write `rule.scope_refused`, `rule_scope_denied` or `rule.mode_refused` | E37-TC-G03, E37-TC-G05, E37-TC-G06, E37-TC-G10 |
| `rule.mode_refused` | the backend; `22` `setRuleMode` | the refused mode change and its code | audit | yes; on a live scope the route's scope check writes `rule_live_scope_armed` (high severity) ahead of it | E37-TC-B10, E37-TC-G07, E37-TC-G08 |
| `rule.disarmed` | the backend; the force-disarm of a rule whose stored IR cannot be read | the cause (`quarantined`); written by the server, no actor | audit | yes | E37-TC-C14 |
| `rule_graph_roundtrip_mismatch_total` | E37-S04 | a counter; alert on any non-zero in staging | metric | no | E37-TC-D08 |
| `rule_graph_compile_duration_ms` | E37-S01, E37-S04 | a timing | metric | no | E37-TC-A04 |
| `rule_graph_validation_duration_ms` | E37-S03 | a timing | metric | no | E37-TC-C01 |
| `rule_graph_layout_duration_ms` | E37-T02 | a timing | metric | no | E37-TC-F06 |

**Frozen strings.** FZ-1 to FZ-14 (E37-D05 §9) are asserted byte for byte in E37-TC-B08, E37-TC-B11,
E37-TC-D02, E37-TC-D04, E37-TC-D05, E37-TC-D09 and E37-TC-D10; the four E36-D05 strings (the
native-stop notice, the ratchet line and the engine banner) in E37-TC-A15, E37-TC-B11 and
E37-TC-B12. A rewording of any of them needs design and security review.

## 13. Fixtures and seeds

Each fixture has a handle, a recipe or source, its cases and a status ("exists", "in this PR" or
"owed"); a case that needs an owed item says so in its Needs column. The staging seed and the fault
toggles have no owner on record (Q-10): each is a required capability with a proposed owner. A
non-Owner reaches only a rule it created (E09-D09 A-5; `04` §7.2.2 rows 23 to 25) and the OWNER
reaches every rule, so a role's case acts on a rule the seed creates as that role.

### 13.1 Users and accounts

<!-- prettier-ignore -->
| Handle | Role and permissions | Accounts | Status |
| --- | --- | --- | --- |
| OWNER | owner (`*`) | all | owed: the staging seed (Q-10) |
| MGR-A | manager: `rules:read`, `rules:write`, `orders:write` | ACC-1, ACC-2 | owed: the staging seed |
| MGR-SIM | manager: `rules:read`, `rules:write`, no `orders:write` on its accounts | ACC-1 | owed: the staging seed |
| MGR-B | manager as MGR-A | ACC-3 only | owed: the staging seed |
| VIEWER-1 | viewer: `rules:read`; owns one rule of ACC-1, written by the seed (a Viewer cannot create one) | read grant ACC-1 | owed: the staging seed |
| ACC-1, ACC-2, ACC-3 | demo accounts with fake keys; no real key, token or identifier anywhere | | owed: the staging seed |

### 13.2 Symbols

<!-- prettier-ignore -->
| Handle | What | Status |
| --- | --- | --- |
| SYM-REC | BTCUSDT with a complete recorded window, so recording-dependent metrics are available | owed: the staging seed |
| SYM-NOREC | ETHUSDT with no recording, so those metrics are unavailable (E37-TC-B07) | owed: the staging seed |

### 13.3 The corpus and the rule seeds

RC-01 to RC-30 are the 30 hand-authored rules of E35-Q02
(`services/api/tests/fixtures/rule_corpus/`, with `golden_hashes.json`; 21 authored in the form and
9 in the graph editor), reused without a fork. The table is printed from the files; the hash column
is the first 12 hex characters of the golden hash. This plan adds no rule to the corpus.

<!-- prettier-ignore -->
| RC | File | Editor | Trigger | Operators | Actions | Golden hash |
| --- | --- | --- | --- | --- | --- | --- |
| RC-01 | `01_sys_native_sl_watchdog.json` | form | on_position_update | is_true, sustained_for | modify_stop_loss, send_notification | `e4e2c18b831c` |
| RC-02 | `02_sys_daily_loss_lockout.json` | form | on_order_fill | lte | halt_new_orders, send_notification | `f6ca760db695` |
| RC-03 | `03_sys_max_positions_guard.json` | form | pre_trade_check | gte | send_notification | `4b3a395dadb8` |
| RC-04 | `04_sys_clock_drift_block.json` | form | on_signal | in_set | halt_new_orders | `829bde099c1a` |
| RC-05 | `05_sys_stale_feed_block.json` | form | pre_trade_check | gt | send_notification | `f12a28342894` |
| RC-06 | `06_sys_breakeven_at_1r.json` | form | on_position_update | gte | move_to_breakeven | `1109b7daf8be` |
| RC-07 | `07_sys_time_stop.json` | form | on_timer | all_of, gt, lt | flatten_position, log_journal_tag | `fc0e4a3ba3a4` |
| RC-08 | `08_sys_funding_flip_flatten.json` | form | on_metric_change | all_of, gte, lt | flatten_position, log_journal_tag | `279f0505d7ee` |
| RC-09 | `09_atr_trailing_stop.json` | graph | on_bar_close 5m | add, gt, mul | tighten_stop | `f1a9d26f84e0` |
| RC-10 | `10_cancel_if_spread_too_wide.json` | form | on_book_update | outside, sustained_for | cancel_all_orders, send_notification | `9a28cf97af8f` |
| RC-11 | `11_breakeven_after_1r_template.json` | form | on_position_update | all_of, gte, is_true | move_to_breakeven, log_journal_tag | `b4f49d151043` |
| RC-12 | `12_rsi_oversold_bounce_entry.json` | form | on_bar_close 15m | all_of, crosses_above, is_true | place_order | `50cee02b96bb` |
| RC-13 | `13_vwap_reclaim_short_exit.json` | form | on_price_update | crosses_below | modify_take_profit | `eaf118b66d49` |
| RC-14 | `14_scale_out_at_2r.json` | form | on_bar_close 1m | gte | scale_out, log_journal_tag | `ee0604ed6d68` |
| RC-15 | `15_add_on_cvd_confirmation.json` | graph | on_bar_close 1m | gt, stable_for | scale_in | `51eedeb1f4c4` |
| RC-16 | `16_flatten_all_on_liquidation_cascade.json` | form | on_liquidation | gt | flatten_all_positions, send_notification | `eec5aff6637c` |
| RC-17 | `17_reverse_on_stop_run.json` | form | on_price_update | all_of, eq, is_true | reverse_position | `7efc3aa3951f` |
| RC-18 | `18_resume_after_drawdown_recovery.json` | form | on_schedule | lt | resume_new_orders | `08a0907ebbb6` |
| RC-19 | `19_leverage_cap.json` | form | on_position_open | any_of, gt, outside | reduce_leverage | `4a84a4ba57c3` |
| RC-20 | `20_widen_stop_through_funding_owner.json` | form | on_timer | between | widen_stop | `70855613d6dc` |
| RC-21 | `21_chase_limit_on_imbalance.json` | graph | on_book_update | gt, n_of | arm_chase_limit | `ad2a58111806` |
| RC-22 | `22_iceberg_accumulation.json` | graph | on_price_update | all_of, is_true, occurred_within | start_iceberg_slice | `f285ebfc7ce6` |
| RC-23 | `23_twap_on_regime_change.json` | form | on_metric_change | all_of, changed, not_in_set | start_twap | `0506e43e8301` |
| RC-24 | `24_repeated_big_trades_signal.json` | graph | on_price_update | count_within, gt | set_variable, emit_signal | `f10d604e5fba` |
| RC-25 | `25_quiet_market_pause.json` | graph | on_timer | gt, none_of | pause_rule | `69af5840acad` |
| RC-26 | `26_re_enable_scalper_on_volatility.json` | form | on_bar_close 1h | gt | enable_rule | `c9fdd923057f` |
| RC-27 | `27_cancel_bracket_on_close.json` | form | on_position_close | is_false | cancel_order, log_journal_tag | `2d8ddc5d4dd9` |
| RC-28 | `28_shared_atr_band.json` | graph | on_bar_close 1h | add, all_of, any_of, gt, lt, sub; shared node | send_notification | `d7743036af63` |
| RC-29 | `29_premium_divergence_alert.json` | graph | on_metric_change | abs, all_of, gt, lt, max, neq, pct_of | send_notification | `569211891ae4` |
| RC-30 | `30_funding_net_cost_guard.json` | graph | on_timer | div, gt, min, mul, neg, sub | log_journal_tag | `204fd1832e08` |

<!-- prettier-ignore -->
| Handle | Source and recipe | Used by | Status |
| --- | --- | --- | --- |
| RULE-FORM-1 | RC-11, stored by `POST /rules` | E37-TC-A14, E37-TC-D01, E37-TC-D02, E37-TC-D07, E37-TC-D08, E37-TC-F03, E37-TC-G02 | exists |
| RULE-GRAPH-NESTED | RC-28 (nested gates and a shared node), stored by `POST /rules` | E37-TC-D02, E37-TC-D16, E37-TC-E11, E37-TC-F01, E37-TC-F07 | exists |
| RULE-GRAPH-EQUIV | the hand-edited export of RULE-GRAPH-NESTED in E37-TC-D16 step 2 (key order reversed, `1.50` for `1.5`, node ids renamed) | E37-TC-D16 | recipe, made by the tester |
| RULE-OLDIR | a rule stored under an IR version older than the current one; the schema defines one IR version today, so it cannot exist until a second ships | E37-TC-D15 | owed by E35 |
| RULE-ARMED-1 | `tests/fixtures/e37/armed_demo_rule.json`: RC-09 with `scope.environments` set to `["demo"]` and `mode` `simulate`; a create lands disarmed, so the seed step arms it on demo through `PUT /rules/{ruleId}/mode`: a demo arm needs no step-up, but it needs a completed simulation run on the exact version, and the promotion gate (5 fires or 24 h) or, for the OWNER, a written `reason` in its place | E37-TC-A16, E37-TC-B12, E37-TC-D11, E37-TC-E16 | in this PR (the file); the seed step is owed (Q-10) |
| RULE-ARMABLE-1 | a rule of ACC-1 that MGR-SIM creates, with a `place_order` and a `flatten_all_positions` action, scope demo, mode simulate, whose newest version has a completed simulation run and has met the promotion gate (5 fires or 24 h), so every arming check before the one a case probes passes; the seed step primes it (`FT-CLOCK`); the OWNER reaches it too | E37-TC-B10, E37-TC-G07 | owed (Q-10) |
| RULE-ARMABLE-2 | RULE-ARMABLE-1's recipe with `scope.environments` set to `["demo", "live"]`, created by MGR-A while the seed grants it `rules:arm_live` (a live scope needs it at save), primed the same way (a new scope is a new hash, so it needs its own simulation run); the seed withdraws the grant before the cases | E37-TC-G07, E37-TC-G08, E37-TC-G11 | owed (Q-10) |
| RULE-CORRUPT-1 | `tests/fixtures/e37/corrupt_ir_truncated.json`: a document cut mid-object, unparsable on purpose | E37-TC-C10 | in this PR (the file) |
| RULE-CORRUPT-2 | `tests/fixtures/e37/corrupt_ir_schema_violation.json`: one field of the wrong type at a named JSON path (in the README) | E37-TC-C10, E37-TC-C14 | in this PR (the file) |
| RULE-CORRUPT-3 | `tests/fixtures/e37/corrupt_ir_unsupported_version.json`: an IR version number the engine does not support | E37-TC-C10 | in this PR (the file) |
| RULE-LAYOUT-1 | `tests/fixtures/e37/layout_hand_placed.json`: RC-11 with a `graph_layout` of hand-placed positions and two comment notes (the corpus has none with a layout) | E37-TC-B14, E37-TC-B16, E37-TC-D12, E37-TC-F09 | in this PR (the file) |

The three corrupted rules cannot be created through the API, which validates its input: they are
seeded at the database level (`FT-CORRUPT`), and E37-TC-C14 seeds RULE-CORRUPT-2 on a row whose mode
is armed as well. `tests/fixtures/e37/README.md` says what each file is for, which cases use it and
how to seed it; nothing real is in any file.

### 13.4 Graph fixtures

These are the Storybook fixtures E37-D05's hand-off §D names, which E37-S01 creates under
`packages/fixtures`. E37-S01 defines each graph's composition (E37-D03 §8 and §11, and the hand-off
§D, give only the sizes: 60, 61 and 121 nodes, and 200 nodes with about 260 edges), within the
schema's bounds (a gate takes at most 32 inputs, a rule at most 10 actions). The staging seed loads
E37-S01's fixture files and does not rebuild them from a second recipe, so the seed and the
Storybook graph are one graph (Q-10). Node ids are `n1`, `n2`, …; positions are fixed canvas units
on a 240-unit grid; no random id and no wall-clock value. Three of the ten are editor states, not
stored rules: a cycle is never stored, a connect in flight has no stored form and an unconnected
node has no place in the IR; the tester builds those from the case's own preconditions.

<!-- prettier-ignore -->
| Handle | Pack name | Recipe | Used by | Status |
| --- | --- | --- | --- | --- |
| FX-S-FORM | `s-form` | the S-form rule: `n1` trigger "bar closes · 1m" at (0, 0), `n2` condition "Position is open" at (240, 0), `n3` action "Tighten stop · 2.0 × ATR 14" at (480, 0); one edge `n2` to `n3` `when`; no edge from the trigger | E37-TC-A04 | owed by E37-S01 |
| FX-S-GRAPH | `s-graph` | `n1` trigger, `n2` shared condition, `n3` "all of", `n4` "any of", `n5` action; `n2` into input 1 of `n3` and of `n4`, `n4` into input 2 of `n3`, `n3` to `n5` `when` | E37-TC-D04 | owed by E37-S01 |
| FX-S-FORM-MISMATCH | `s-form-mismatch` | `s-form` with a second IR that differs in the action's ATR multiplier; the diverging node is `n3` | E37-TC-D02, E37-TC-D09, E37-TC-D10 | owed by E37-S04 |
| FX-REVIEW-60 | `review-60` | the 60-node auto-layout review graph (composition: E37-S01's) | E37-TC-F04, E37-TC-F05 | owed by E37-S01 |
| FX-TIER-B-61 | `tier-b-61` | `review-60` plus one comparison, the first Tier B graph (PROPOSED id) | E37-TC-F05 | owed by E37-S01 |
| FX-OVER-BUDGET-121 | `over-budget-121` | the first Tier C graph: 121 nodes (composition: E37-S01's) | E37-TC-F05 | owed by E37-S01 |
| FX-BUDGET-200 | `budget-200` | the 200-node, about 260-edge benchmark graph E37-Q04 measures (composition: E37-S01's) | E37-TC-F06, E37-TC-F08 | owed by E37-S01 |
| FX-INVALID-CONNECT | `invalid-connect` | `s-form` with a connect from `n2`'s boolean output in flight to a number input (PROPOSED id) | E37-TC-A07 | editor state, built by the tester |
| FX-CYCLE | `cycle` | `s-graph` with `n3` to `n4` added, so the path `n3`, `n4`, `n3` closes (PROPOSED id) | E37-TC-C02 | editor state, built by the tester |
| FX-ORPHAN | `orphan` | `s-form` plus `n4`, a condition with no connection; E37-TC-C06 also clears `n3`'s `when` (PROPOSED id) | E37-TC-C04, E37-TC-C06 | editor state, built by the tester |

### 13.5 Fault toggles

<!-- prettier-ignore -->
| Handle | What it does | Manual stand-in | Proposed owner | Status |
| --- | --- | --- | --- | --- |
| FT-FLAG | turns `rules.node_editor` on or off | an operator setting in staging | the operator | exists |
| FT-VOCAB | `GET /rules/vocabulary` answers 503 | stop the staging engine | E37-Q02 (a stub or proxy fault) | owed |
| FT-COMPILE | `POST /rules/validate` and `POST /rules/{ruleId}/compile` are unreachable | stop the staging engine | E37-Q02 | owed |
| FT-MISMATCH | the two sides of a switch compile to different hashes, or the post-switch hash differs | none | E37-S04 | owed |
| FT-CORRUPT | seeds a stored IR the API would refuse, at the database level, and for E37-TC-C14 the rule row's mode `armed` | none | E37-Q02 with E35 | owed |
| FT-CLOCK | freezes the clock for the `{HH:MM:SS}` strings | record the time shown beside the server's | E37-Q02 | owed |

## 14. Traceability

The 64 titles are copied by script from `11` §20 and the Gherkin of `E37.json`, verbatim and in
story order. The Cases and Auto columns are derived from the case tables; the check script
re-derives both and fails on a difference, and on any scenario with no case. `11` writes "node-only"
in U1.2's title where the deck says graph-only (C-05); titles stay as the sources write them.

<!-- prettier-ignore -->
| Code | Source | Scenario (title verbatim) | Cases | Auto |
| --- | --- | --- | --- | --- |
| U1.1 | US-RULE-001 | Round trip | E37-TC-D01, E37-TC-D17 | Q02-3, Q03 |
| U1.2 | US-RULE-001 | Node-only construct | E37-TC-D04, E37-TC-D06, E37-TC-D17 | Q02-4, Q03 |
| U1.3 | US-RULE-001 | Version migration | E37-TC-D15 | man |
| U1.4 | US-RULE-001 | Canonical serialisation (error/edge) | E37-TC-B14, E37-TC-D16 | Q03 |
| U1.5 | US-RULE-001 | Presentation data survives the round trip (edge) | E37-TC-B14, E37-TC-D12, E37-TC-F09 | Q03 |
| U1.6 | US-RULE-001 | Schema violation on load (error) | E37-TC-C10, E37-TC-C14 | Q02-10 |
| U1.7 | US-RULE-001 | Round-trip fuzz invariant | E37-TC-D18 | Q03 |
| U2.1 | US-RULE-002 | Catalogue | E37-TC-B01, E37-TC-B05 | Q02+ |
| U2.2 | US-RULE-002 | Unavailable metric | E37-TC-B07 | man |
| U2.3 | US-RULE-002 | Estimated metric | E37-TC-B06 | Q02+ |
| U3.1 | US-RULE-003 | Catalogue | E37-TC-B01 | Q02+ |
| U3.2 | US-RULE-003 | Action scope | E37-TC-B09 | man |
| U3.3 | US-RULE-003 | Forbidden action | E37-TC-B13, E37-TC-G07 | Q02-7, X02 |
| U5.1 | US-RULE-005 | Build by graph | E37-TC-A02, E37-TC-A04, E37-TC-B02, E37-TC-B08, E37-TC-C01 | Q02+, Q02-1 |
| U5.2 | US-RULE-005 | Invalid connection | E37-TC-A06, E37-TC-A07, E37-TC-A08 | Q02-5, Q02+ |
| U5.3 | US-RULE-005 | Layout aids | E37-TC-F01, E37-TC-F02, E37-TC-F04 | Q03, Q02+, man |
| U5.4 | US-RULE-005 | Cycle in the graph (error) | E37-TC-C02, E37-TC-C03 | Q02-5, X02 |
| U5.5 | US-RULE-005 | Orphan and dangling nodes (edge) | E37-TC-C04, E37-TC-C05, E37-TC-C06 | Q02-6 |
| U5.6 | US-RULE-005 | Keyboard-only construction (a11y edge) | E37-TC-A11, E37-TC-E03, E37-TC-E04, E37-TC-E06, E37-TC-E12 | Q02+, Q02-2, Q02-5 |
| U5.7 | US-RULE-005 | Graph-only construct is marked at creation time (edge) | E37-TC-B08, E37-TC-D04 | Q02+, Q02-4 |
| U6.1 | US-RULE-006 | Switch | E37-TC-D01, E37-TC-D17 | Q02-3, Q03 |
| U6.2 | US-RULE-006 | Unsaved changes | E37-TC-A12, E37-TC-D14 | Q02+ |
| U6.3 | US-RULE-006 | Read-only fallback | E37-TC-D06 | Q02-4 |
| U6.4 | US-RULE-006 | Hash proof on every switch (edge) | E37-TC-D08 | man |
| U6.5 | US-RULE-006 | Concurrent edit in two tabs (error) | E37-TC-D13 | Q02-8 |
| U6.6 | US-RULE-006 | Switch while armed (edge) | E37-TC-A16, E37-TC-D11 | Q02+ |
| U6.7 | US-RULE-006 | Unrepresentable-after-edit (error) | E37-TC-D07 | Q02-4 |
| U6.8 | US-RULE-006 | Migration during a switch (edge) | E37-TC-D15 | man |
| S01.1 | E37-S01 | Author a minimal graph by pointer | E37-TC-A04 | Q02-1 |
| S01.2 | E37-S01 | Incompatible connection is refused with a reason | E37-TC-A06, E37-TC-A07 | Q02-5 |
| S01.3 | E37-S01 | Non-drag insertion works | E37-TC-A05 | Q02-2 |
| S01.4 | E37-S01 | Viewer is denied (security edge) | E37-TC-G03, E37-TC-G04, E37-TC-G05 | Q02-7, X02 |
| S01.5 | E37-S01 | Concurrent save is rejected (error) | E37-TC-A13 | Q02-8 |
| S01.6 | E37-S01 | Feature flag off | E37-TC-A14 | Q02+ |
| S02.1 | E37-S02 | The whole vocabulary is reachable on canvas | E37-TC-B01 | Q02+ |
| S02.2 | E37-S02 | Estimated metrics are badged as text | E37-TC-B06 | Q02+ |
| S02.3 | E37-S02 | Unavailable metric is explained, not hidden | E37-TC-B07 | man |
| S02.4 | E37-S02 | A forbidden action is not silently offered (security edge) | E37-TC-B13, E37-TC-G06, E37-TC-G07 | Q02-7, X02 |
| S02.5 | E37-S02 | Second trigger is refused (error) | E37-TC-B04 | Q02+ |
| S02.6 | E37-S02 | Inspector editing does not disturb the layout (edge) | E37-TC-B16 | Q02+ |
| S03.1 | E37-S03 | An error is shown on the offending node | E37-TC-C01, E37-TC-C07 | Q02+ |
| S03.2 | E37-S03 | A cycle is refused and drawn as a path | E37-TC-C02 | Q02-5 |
| S03.3 | E37-S03 | Orphans warn on canvas and block on save | E37-TC-C04, E37-TC-C06 | Q02-6 |
| S03.4 | E37-S03 | Both editors report identical diagnostics (contract) | E37-TC-C08 | Q03 |
| S03.5 | E37-S03 | Validation service unavailable (failure) | E37-TC-C09 | Q02-9 |
| S03.6 | E37-S03 | Quarantined rule (error edge) | E37-TC-C10, E37-TC-C14 | Q02-10 |
| S04.1 | E37-S04 | Switching without editing preserves the IR | E37-TC-D01 | Q02-3 |
| S04.2 | E37-S04 | A graph-only construct is declared at creation time | E37-TC-D04 | Q02-4 |
| S04.3 | E37-S04 | Hash proof fails on switch (failure path) | E37-TC-D08 | man |
| S04.4 | E37-S04 | Mismatch is never auto-resolved (error) | E37-TC-D09, E37-TC-D10 | man |
| S04.5 | E37-S04 | Switching an armed rule (edge) | E37-TC-D11 | Q02+ |
| S04.6 | E37-S04 | Layout survives a form-side edit (edge) | E37-TC-D12 | Q03 |
| S04.7 | E37-S04 | Concurrent edit in two tabs (error) | E37-TC-D13 | Q02-8 |
| S05.1 | E37-S05 | Build a complete rule without a pointer | E37-TC-E06 | Q02-2 |
| S05.2 | E37-S05 | A connection is announced | E37-TC-E03 | Q02-2 |
| S05.3 | E37-S05 | An incompatible target is announced, not merely ignored (error) | E37-TC-E04 | Q02-5 |
| S05.4 | E37-S05 | Every canvas operation exists in the node list (a11y gate) | E37-TC-E07, E37-TC-E08, E37-TC-E09, E37-TC-E10 | Q05 |
| S05.5 | E37-S05 | Undo is shared (edge) | E37-TC-E12 | Q02+ |
| S05.6 | E37-S05 | Announcement flooding is prevented (edge) | E37-TC-E13 | man |
| T02.1 | E37-T02 | Auto-layout never changes semantics | E37-TC-F01 | Q03 |
| T02.2 | E37-T02 | Auto-layout is undoable as one step | E37-TC-F02 | Q02+ |
| T02.3 | E37-T02 | A form-authored rule opens laid out | E37-TC-F03 | Q02+ |
| T02.4 | E37-T02 | Large-graph budget (performance edge) | E37-TC-F06 | Q04 |
| T02.5 | E37-T02 | Search jumps and announces | E37-TC-F07 | Q02+ |

**Table 2: E37-Q02's ten specs.** Derived the same way; a spec with no case fails the check.

<!-- prettier-ignore -->
| Q02 spec | What it asserts (E37-Q02) | Cases |
| --- | --- | --- |
| Q02-1 | pointer author and save | E37-TC-A04, E37-TC-G01 |
| Q02-2 | keyboard-only, the same hash | E37-TC-A05, E37-TC-E03, E37-TC-E06 |
| Q02-3 | round-trip switch | E37-TC-D01 |
| Q02-4 | graph-only construct | E37-TC-D04, E37-TC-D05, E37-TC-D06, E37-TC-D07 |
| Q02-5 | invalid connection and cycle | E37-TC-A06, E37-TC-A07, E37-TC-C02, E37-TC-E04 |
| Q02-6 | orphan and dangling | E37-TC-C04, E37-TC-C05, E37-TC-C06 |
| Q02-7 | RBAC | E37-TC-B13, E37-TC-G03, E37-TC-G04, E37-TC-G11 |
| Q02-8 | concurrency | E37-TC-A13, E37-TC-D13 |
| Q02-9 | engine unavailable | E37-TC-A15, E37-TC-C09 |
| Q02-10 | quarantine | E37-TC-C10, E37-TC-C14 |

**Table 3: E37-D06's design acceptance checklist.** DA-1 to DA-17 run on the built screen, not here;
the cases that overlap cite the row: DA-2 and DA-3 (E37-TC-A07, E37-TC-C02), DA-4 (E37-TC-E07,
E37-TC-E11), DA-5 (E37-TC-D05), DA-6 (E37-TC-F04), DA-10 (E37-TC-E04), DA-14 (E37-TC-A09,
E37-TC-E15), DA-15 (E37-TC-C13, E37-TC-E10, E37-TC-E16), DA-16 and DA-17 (E37-TC-E01, E37-TC-E10).

## 15. Documentation conflicts and questions

Two kinds of row, each numbered and citing its public source; both are findings recorded here and
not settled here. **C-rows** are conflicts between documents: the case names the source it follows
and a defect against a row cites it. **Q-rows** are questions PROPOSED to the named owner and move
with that ticket; none is a pass by default.

### 15.1 C-rows: conflicts between documents

<!-- prettier-ignore -->
| Id | Conflict | Plan follows | Cases |
| --- | --- | --- | --- |
| C-01 | The Viewer. `14` SCR-080's RBAC line, `12` R-160 and R-162 (`docs/plan/12-sitemap.md`), E37-S01's "Viewer is denied" Gherkin and this ticket's AC 3 say a viewer is denied: route hidden, 403, no rule content. The design record gives a Viewer a read-only view of its own rules with the route shown: E09-D09 A-5 (`docs/design/E09/E09-D09.md:450`), E36-D03 D03-C23 (`docs/design/E36/E36-D03.md:382`) and E37-D02 §3 ("A Viewer": every write T2 "Your role can't change rules."). The seed gives `viewer` `rules:read`, and `compileRule` and `validateRule` need only `rules:read` (`22`), so a Viewer's compile and validate are permitted | the contract, the seed and the design record: a Viewer opens SCR-082 read-only on a rule it owns (the base answers 404 on another's); a crafted write is 403 with no state change and one `rbac.denied` row; a build that answers 403 to a read the contract permits is recorded, not passed. PROPOSED to E37-S01's owner: its Gherkin follows the design record | E37-TC-G04, E37-TC-G05, the matrix's fourth column |
| C-02 | Role names. "manager with `rules:author`": no such code is seeded (E09-D09 A-5; `12` R-160); the seed's codes are `rules:read`, `rules:write` and `rules:arm_live`. "Manager without live-arming" (US-RULE-003) names no seeded code either: no manager holds `rules:arm_live`, and the served vocabulary marks the order-placing actions simulate-only for a manager without `orders:write` | `rules:author` is read as `rules:write`; MGR-SIM, a manager without `orders:write`, stands for "without live-arming" | E37-TC-B13, E37-TC-G07 |
| C-03 | Audit names. `14` SCR-082 and E37-D05 §10 name `rule.graph_saved`, `rule.roundtrip_verified` and `rule.roundtrip_mismatch_resolved`; the backend writes `rule.created`, `rule.updated`, `rule.armed`, `rule.disarmed`, `rule.mode_refused`, `rule.scope_refused` and `rbac.denied`; none of the three graph names is registered at the base | the audit step: the event once per action under any name in its §12 row, the tester recording which | every case with an audit event |
| C-04 | SCR-088 shows the IR as stored, not its canonical form (E36-D03 §5, a PROPOSED contract gap), so no screen shows the canonical hash | the three proxies of §0; exports are compared byte for byte only with no edit between them | E37-TC-D01, E37-TC-D16, E37-TC-D17 |
| C-05 | "node-only" (US-RULE-005 and E37-S04) against "graph-only" (`14` SCR-082's badge words, E37-D02-C15, E37-D05 FZ-13) | graph-only, the deck's word; a build that shows "node-only" is recorded | E37-TC-B08, E37-TC-D04 |
| C-06 | The story's "connected CVD divergence output to AND input 1" (US-RULE-005) against the gate's word: the deck and E37-D02 write "all of" | the template of `rules.graph.announce.connected` filled with each node's own accessible name | E37-TC-E03 |
| C-07 | Saving with errors: E37-S03 says a graph with an error saves as a draft only and US-RULE-005 says "blocking errors on save", while E37-D02 §3 draws `Save` with the validity look (a press focuses the first entry; nothing is saved) | E37-D02 §3; the tester records whether a draft is saved | E37-TC-C06 |
| C-08 | Delete confirmation: E37-D02-Q5 and E37-D04 K-02 confirm only a node with connections; the shipped keymap's `rules.delete` confirms always (E37-D04 C-10) | the shipped keymap; a silent delete is recorded and is not a pass until this row settles | E37-TC-A10, E37-TC-E07 |
| C-09 | Undo and redo chords: E37-S01 says `Ctrl+Z` and `Ctrl+Shift+Z`; E37-D04 K-18 says `Ctrl+Z` and `Ctrl+Y`, PROPOSED as `rules.undo` and `rules.redo`; neither is registered | `Ctrl+Z`; the tester records which redo chord works | E37-TC-A11, E37-TC-E12 |
| C-10 | Test hooks: E37-D05's hand-off §E says "No `data-testid` unless an element has no role"; E37-Q02's scope adds `data-testid` on nodes, ports, edges, palette rows, node-list rows and the indicator | this plan queries the accessibility tree by role and name; the split is E37-Q02's and E37-S01's to settle | every case's Auto column |
| C-11 | Event properties: E37-D05 §10 gives `rule.graph_node_added` and `rule.graph_autolayout_used` no properties; E37-S01 and E37-S02 give the first `{type}` and E37-T02 gives the second `{nodeCount, durationMs}` | the tester records the properties seen; neither reading fails | E37-TC-A04, E37-TC-F01 |
| C-12 | The switch confirmation: `14` SCR-082's state 2 says switching to the form "shows a confirmation naming the read-only parts before the switch"; E37-D02-C6 and hand-off §C A-12 say a clean switch has no confirmation, only the dirty prompt | A-12, PROPOSED until the pack is approved; a confirmation that appears is recorded | E37-TC-D06, E37-TC-D11 |
| C-13 | Retired: the ticket's execution brief names automated tests where its Test plan makes this a document, a boilerplate mismatch in the ticket; recorded in the PR notes | — | — |
| C-14 | Performance wording: US-RULE-005's "at least 55 fps with 100 nodes" against `14` SCR-082's "200 nodes at 60 fps" with a soft cap above 120 nodes (ADR-0029); the server bounds a model at 1,000 condition nodes | `14` and the ADR; E37-Q04 measures | E37-TC-F05, E37-TC-F06, E37-NB-15, E37-NB-16 |
| C-15 | `14` SCR-082's refusal example ("A metric output can't connect to a trigger input") paraphrases the port-compatibility sentences the deck carries (E37-D02-C7) | the deck's 36 sentences (§10) | E37-TC-A06, E37-TC-A07 |
| C-16 | The permission gate of the rules writes no audit row at the base. `30` §7.3 criterion 10 and the ticket's AC 3 ask for 403, no state change and an audit row on every refused combination; at the base the gate that checks `rules:write` refuses a Viewer with 403 and writes no row, and `22` `queryAuditLog` lets only the Owner read every entry | the roadmap and the ticket: one `rbac.denied` row per refusal; the first run records the missing row as a `priority/p1-high` defect (§0.1). PROPOSED to the API owner of E35 and the RBAC-matrix owner of E09 | E37-TC-G05, the matrix's fourth column |
| C-17 | The `flatten_all_positions` acknowledgement. E37-S02's scope and `14` SCR-081's validation list read as an acknowledgement at save; E36-D02 (`docs/design/E36/E36-D02.md:187`) and `14` SCR-085 put it on arming: the box gates `Arm…` and travels in the arm request, and the save has no such field. The arm request itself diverges: `22`'s `setRuleMode` body is `additionalProperties: false` while the shipped route accepts `acknowledge_flatten_all` (E35-D02 D02-CG1) | the design record and the arming leg: `Save` is unaffected, `Arm…` takes the validity look until the box is ticked, a crafted arm without it is 422 `acknowledgement_required`, the shipped code's answer; a build that blocks the save on it is recorded | E37-TC-B10, E37-NB-05 |

### 15.2 Q-rows: proposed questions

<!-- prettier-ignore -->
| Id | To the owner of | Question | Source | Cases |
| --- | --- | --- | --- | --- |
| Q-01 | E37-S02 | A second trigger: E37-D02 §7 draws no second trigger entry (absent, not locked) while S02.5 asks for a refusal message naming the existing trigger, and the deck has no string for it. Which is built, and what is the message? | E37-D02 §7; S02.5 | E37-TC-B04 |
| Q-02 | E37-S03 | The wording of the quarantine state on SCR-082 is not in the E37 deck; E36-D05's deck has `rule.quarantined` (the list), `rules.list.reason.quarantined` and `rules.ir.state.quarantined` (SCR-088, naming the failing path). Which does SCR-082 show? | E36-D05 deck; S03.6 | E37-TC-C10 |
| Q-03 | E37-S03 | How the editor presents `429 rate_limited` on validate and compile (no deck string): a message, a back-off or silence? | `22` `validateRule`; E37-NB-24 | E37-TC-C12 |
| Q-04 | E37-S05 | The coalescing rule for a burst of node adds: E37-D04 states it for nudges only (once per settled burst) and S05.6 asks for "the agreed rule" | E37-D04 §5; S05.6 | E37-TC-E13 |
| Q-05 | E37-S04 | What the chip shows before the first save (E37-D02-Q2: it appears on the first save) | E37-D02 §3 | E37-TC-A01 |
| Q-06 | E37-S04 with the contract's owner | The stale suffix names the time of the last compile and no response carries one (E37-D02-G2) | E37-D05 §11 | E37-TC-D03 |
| Q-07 | E37-S04 | The wording of the "round-trip integrity failure" error and its diff download: no deck string | US-RULE-006; S04.3 | E37-TC-D08 |
| Q-08 | E37-T02 | The announcement when a search jump moves focus: no deck string | T02.5 | E37-TC-F07 |
| Q-09 | the API owner (E35) | A foreign rule's route: S01.4 says 403, E36's AC-RA-12 expects the unseen 404 (E35's plan Q3 asked); and which issue code a cyclic model carries (E35's plan Q2) | S01.4; AC-RA-12; `docs/qa/e35-rule-engine-test-plan.md` §9 | E37-TC-G03, E37-TC-C03 |
| Q-10 | E37-Q02 and E37-S04 | Owners of the staging seed (the users, accounts, symbols, rules and graphs of §13) and of the fault toggles: `FT-VOCAB`, `FT-COMPILE`, `FT-CORRUPT` and `FT-CLOCK` proposed to E37-Q02 (with E35 for the stored-IR seed), `FT-MISMATCH` to E37-S04. E35's plan asked twice (its Q5 and Q6) and no owner is recorded | `docs/qa/e35-rule-engine-test-plan.md` §9 | every case's Needs column |
| Q-11 | E37-S04 | A Viewer's compile is a permitted `rules:read` call: what does the chip show when it fails (E37-D02 gives Not verified for a 503 and while viewing as)? | E37-D02 §4 | E37-TC-G04 |
| Q-12 | — | Retired: a dependency, not a question; the form editor's tickets (E36-S02, E36-S03) are named in each case's Needs column and in the PR notes | — | — |
| Q-13 | E37-T02 with E35 | A save whose hash matches a version the rule already has returns that version with `created: false` and stores nothing (`22` `updateRule`: "also a save that matches an existing version"; `RulesManager.update`), and ADR-0026 keeps `graph_layout` out of the hash, so a layout-only change, or a threshold set back to an earlier value, writes no row and the new layout is not stored. Where does a moved layout persist, and does the editor say the save changed nothing? | `22` `updateRule`; ADR-0026 rules 1 and 4 | E37-TC-A12, E37-TC-B14, E37-TC-B16, E37-TC-D01, E37-TC-D12, E37-TC-D16, E37-TC-E06, E37-TC-F01, E37-TC-F09 |
| Q-14 | E37-S01 | Which of the 36 port-type pairs have real ports on the canvas: E37-D02 §5 names the trigger's `trigger` output, the comparison's boolean output and typed inputs, the action's `when` input and the gate's boolean ports, and no node with an output of type price, side or action or an input of type trigger. List the port types of each node kind | E37-D02 §5, §6 | E37-TC-A06 |
| Q-15 | E37-S01 | The dirty prompt on a route change: the deck's one prompt is written for a switch and S01's navigation guard has no row | E37-D05 §8.1 | E37-TC-A12 |
| Q-16 | E36-S01 | The form editor's core refuses a model past 200 condition nodes (AC-RA-16: 201 open read-only) and the contract bounds 1,000: does the graph editor share the 200 limit? | AC-RA-16; `22` | E37-NB-16 |

## 16. Dry-run record and sign-off

**Status: pending, not executed.** Every case waits for its story: E37-S01 to E37-S05 and E37-T02
are open, the form side waits for E36-S02 and E36-S03, and the owed fixtures and toggles of §13 have
no owner yet (Q-10). No result below is fabricated. Rows are appended as each dependency lands,
never overwritten; a case whose route answers `501`, or whose Needs are unmet, is recorded
`blocked-pending-dependency`, never pass or fail.

<!-- prettier-ignore -->
| Group or cases | Build sha | Environment | Fixture | Result | Evidence | Defect |
| --- | --- | --- | --- | --- | --- | --- |
| Check script (EN-5) | | repository | this plan | pending | | |
| Group A, E37-TC-A01 to E37-TC-A16 | | staging | §13 | pending (E37-S01) | | |
| Group B, E37-TC-B01 to E37-TC-B16 | | staging | §13 | pending (E37-S02) | | |
| Group C, E37-TC-C01 to E37-TC-C14 | | staging | §13 | pending (E37-S03, FT-COMPILE, FT-CORRUPT) | | |
| Group D, E37-TC-D01 to E37-TC-D18 | | staging | §13 | pending (E37-S04, E36-S02, FT-MISMATCH) | | |
| Group E, E37-TC-E01 to E37-TC-E17 | | staging | §13 | pending (E37-S05) | | |
| Group F, E37-TC-F01 to E37-TC-F09 | | staging | §13 | pending (E37-T02, the graph fixtures) | | |
| Group G, E37-TC-G01 to E37-TC-G11 | | staging | §13 | pending (E37-S01, E37-S02, the staging seed) | | |
| Keyboard inventory, K-01 to K-25 (§11) | | staging | §13 | pending (E37-S05) | | |
| Perceived performance, P-1 to P-5 (§0.3) | | reference hardware | FX-BUDGET-200 | pending (E37-Q04) | | |

### Sign-off

- [ ] Peer review by a second SDET and the E37 frontend lead, each expected result confirmed
      observable. **Pending.**
- [ ] Entry and exit criteria (§0.2) and the triage convention (§0.1) agreed with the Owner and the
      Architect. **Pending.**
- [ ] Dry run recorded with pass or fail and evidence per case (above). **Pending.**
- [x] Every one of the 64 scenarios of §14 maps to at least one case, with no gap (the check
      script).
- [x] Every boundary and negative row names its input, expectation, source and charter (§9); no case
      names an internal function, module path or private field; no case needs a live exchange or a
      real credential, and no automated check needs a wall-clock sleep.
- [x] Linked from `docs/plan/18-traceability-matrix.md` §2.20 and from the `## Test plan` of E37,
      E37-S01 to E37-S05 and E37-T02; automation candidates tagged for E37-Q02 (§0, §14).
- [ ] Fixtures QA owns defined and the data ones created and checked in (§13): the corpus and
      `tests/fixtures/e37/` exist; the graphs, the seed and the toggles are owed. **Partial.**
- [ ] QA sign-off comment on epic E37, after E37-Q06. **Pending.**
