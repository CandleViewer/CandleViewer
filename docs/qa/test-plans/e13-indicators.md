# E13 Indicator framework and the v1 set: black-box test plan

Ticket: E13-Q01 (#422). Status: v1.0, the deliverable of #422 (its PR closes the ticket, BQ-21), reviewed by the QA lead, one backend engineer and one frontend engineer, written
on the before-writing question list's defaults, all ruled (section R: the ruling of record, #422 issuecomment-6532529903). It holds the conventions, the
scope, the test matrix, the cases for US-IND-001 to US-IND-008, the E13 story and task Gherkin and the E13-X01 abuse cases, the
time-control strategy, the destructive and fixture protocol, the fixture catalogue, the entry and exit criteria with the
regression subset, the traceability and the open questions. E13-Q02 to E13-Q06 execute it; this plan contains no code.

## 0. Conventions

- **READY sha.** Every † and every blocked row of this plan was re-grepped at `origin/main` `54f4a82d217392751750b824162c638a11e607da` (`54f4a82d2`), the READY sha; the plan states
  nothing about `main` that is newer than it. Between the first draft's base (`b43dfb1fa`) and the READY sha two docs-only commits landed (E45 / E08 backlog
  rows; E15-D10's `14` and `15` catalogue rows): no row changed status, and the `14` cites became SCR-034 / SCR-035 / SCR-036 sections, not lines. E13-T01 (#425), E13-S01
  to S08 (#424 and the others) stay open and E13-T02 (#426), E13-T03 (#427) stay merged; if E13-T01, S01 or S02 land in Sprint 07, the rows they unblock are re-greped
  at the then READY sha and this line is updated in the same pass.

- **Expectations come from the specification, not the implementation.** Each case cites its source:
  - `US-IND-nnn/k` is scenario k of that story in `docs/plan/11-user-stories.md` §7 (`11`:1344–1497);
  - `S01` to `S08` and `T01` to `T03` are the Gherkin of E13-S01 to S08 and E13-T01 to T03 in `docs/plan/backlog/E13.json`;
    `S03.5` is E13-S03's fifth scenario, in ticket order;
  - `22` is `docs/plan/22-api-openapi.yaml`, cited by operation id and schema name (`listIndicators`, `listIndicatorPresets`,
    `createIndicatorPreset`, `updateIndicatorPreset`, `deleteIndicatorPreset`; `IndicatorDescriptor`, `IndicatorPresetInput`,
    `IndicatorPresetStyle`, `WorkspaceBundle`); `23` is `docs/plan/23-ws-protocol.md` (§6.1's `indicators` topic row and its bullets, cited by
    bullet name: Options, Identity, Snapshot and deltas, Amended bars and generations, Refusals, Live only, As built; the §6.3 `indicators` row); `24` is `docs/plan/24-internal-schemas.md` (§7.4 the kernels);
  - `D02` to `D05` are `docs/design/E13/E13-D02.md` to `E13-D05.md`; `D06` is `E13-D06.md` (its §3 data contract, §6 commit
    model, §8.1 budgets, §8.3 frozen set, §8.4 code map, §12 gates, §14 Q-rows, §15.2 G-rows); the **deck** is
    `docs/design/E13/E13-D06-copy.json`, cited by key (`d02.12.rNN`, `d03.13.rNN`, `d04.10.r01`, `d05.lr05`, `d02.07.errored`,
    `indicator.*`); T2 is a gated control with a visible reason, T4 a server refusal shown at the point of action;
  - `TM` is `docs/security/threat-models/E13-indicators.md` (abuse cases `AC-01` to `AC-24`, `TM`:328–351; the §3 bounds
    table, `TM`:97–126); `GV` is the golden-vector set `packages/fixtures/golden/indicators/` and its `manifest.json`;
  - `E16` is the template plan `docs/qa/test-plans/e16-recorder.md` (its form is followed, never its content).
- **Where the ticket text and the merged design differ**, the case follows the merged design (`E16`:21–24's rule, proposed as
  BQ-03): each difference is a row in section 10 and the case is marked **blocked on** its owner. Where merged sources differ
  from each other, the case says so. Nothing is guessed: a hook, metric, string, field or number that no merged source states
  is a † or a blocked row with an owner, never a value of this plan's.
- **Environment:** the seeded stack of section 6: a keyless testnet profile, migrated databases with the 18 built-in presets
  (`21` §10.5), the recorded fixtures replayed into the bar store and the chart. Never live (`03` §17, C-13.5). No network,
  no real key, no production data: every user, session and bearer is synthetic and made per run, and no host, key, account,
  user name or private record id appears in a step, a fixture or an evidence file.
- **Case ids:** `E13-Q01-Cnn` (ruled as BQ-05; the ticket's `E13-TC-nnn` is a deviation, section 1). The line under the id
  names the layer (`03` §2: `unit`, `contract`, `integration`, `e2e`, `perf`, `security`, `a11y`), the role and state it covers
  (section 2) and what it mirrors. **[R]** joins the regression subset (section 7); **[F]** marks a failure path (the ticket's
  AC: every story section has one); **blocked on** an owner means that owner must answer first.
- **Oracles, in order:** (1) the kernel's value: the `GV` vector at a named bar index (tolerance per `manifest.json`:
  `abs(kernel - reference) <= 1e-8 * max(1, abs(reference))`, `None` positions equal) and, for a `compute: server`
  instance, the point the WS topic serves > (2) an API assertion: a `22` status and rule, a `23` `sub_ok` or `err` code >
  (3) the legend text or the DOM-mirror row (presentation only, and the case says so). For a `client_worker` indicator the
  only value oracle is the parity pack (E13-Q05, #458): the case asserts presence, warm-up (`null`, never 0: `22`
  `IndicatorDescriptor.warmup_bars`) and text, never numerics at 1e-8. Every case also names a secondary oracle: an audit
  action (`indicator_preset.created` / `.updated` / `.deleted`, D06 §3.1; server-side only, D06 §8.2) or a metric from the
  stories' Observability sections; a pass whose secondary record is missing fails the case, and a read-only case says "none
  (a read)". A † after a metric or event marks one that nothing emits on `main` at the base: the case asserts its stand-in from
  the Known gaps table of section 10 until the owner ships it.
- **Strings:** every expected string is a deck entry quoted verbatim, or a `22` / `23` rule name. A state with no deck row
  (D06 Q-12, Q-13, Q-15, Q-17) asserts the drawn pattern (CMP-027 / CMP-015 / CMP-045) and that no server text reaches the
  DOM (D06 §8.3 row (6)), and is marked blocked on the owner's words.
- **Time and destruction:** sections 4 and 5 bind every case. No case sleeps or relies on more than 5 minutes of real elapsed
  time, and every case that deletes runs on the scratch database only.

## 1. Scope and references

**In scope:** the catalogue and the three screens SCR-034, SCR-035, SCR-036 with the CMP-199 legend rows and the CMP-224 count
chip (E13-S01), the eight indicator families of E13-S02 to S07 as the 28 descriptors `listIndicators` serves at the base
(section 6: nine `compute: server`, nineteen `client_worker`), the metric exposure and referential guard (E13-S08), the
plugin runtime's visible behaviour (E13-T01), the kernel and the WS topic (E13-T02), the preset routes (E13-T03), the
ticket's seven cross-cutting items and the 24 abuse cases `TM` §11 hands to this plan (`TM`:389: "consumes AC-01..AC-24 and the
§3 boundary table; no control of its own"). **Out of scope:** automation code (E13-Q02), the perf harness (E13-Q03), the a11y
audit (E13-Q04), the parity pack (E13-Q05), the charters and chaos (E13-Q06), section 8.

**Read first:** `03` §4.2, §11 and §16; `11`:1344–1497; `22` tag `workspaces` (`/indicators`, `/indicator-presets*`); `23`
§6.1 `indicators`; `24` §7.4; ADR-0034 (`docs/plan/27-adrs/ADR-0034-indicator-compute-placement.md`); D02 to D06 and the deck;
`14` SCR-034 to SCR-036; `TM`; `GV` `manifest.json`.

**Deviations from the ticket** (repeated in the PR; ruled as BQ-03 to BQ-05, BQ-20, BQ-21): the path is
`docs/qa/test-plans/e13-indicators.md` (the ticket says `qa/plans/e13-indicators.md`; the template's folder); the case ids are
`E13-Q01-Cnn` (the ticket says `E13-TC-nnn`, which is retired: E13-Q02 (#455) references the `E13-Q01-Cnn` ids, BQ-05); the PR title is a conventional commit (the
ticket's `E13-Q01: …` form is not, C-4.10); the DoD lines "executed at least once against a build" and "QA sign-off" cannot be
met at the base (every frontend surface is unbuilt, D06 §0 :54–62; E13-T01 #425 open), so section 7's entry criteria say so and
the execution record is E13-Q06's (#459). Story items the merged design reads differently from the ticket or the story:
US-IND-002/2 (the ribbon: no descriptor, D02 CG-5), US-IND-003's NFR (no field persists a sub-pane height, D06-G-3), SCR-034's
"descriptions" (an empty labelled slot, D02 CG-6), Recents ("store pending", D02 CG-3), the Style tab (absent until E05-T01,
D06 C-b), the MA cross (metric only, D06 Q-14), SCR-034's "custom composite" (no descriptor): each is a section 10 row.

## R. Rulings applied

The before-writing question list (BQ-01 to BQ-22, posted on #422, read from `main` `e607a3f104`) proposed a default for every question and the
orchestrator's ruling of record (#422 issuecomment-6532529903, 2026-10-30, under the 2026-10-29 delegation) rules **all 22 as proposed**, with three riders: every † and blocked row
re-greped at the READY sha (section 0); the four OMS-path abuse legs (AC-10, AC-11, AC-23, AC-24) name E13-X02 (#466) / E28-X03 (#976) as the controls' executors and assert only the black-box
answer (C34, C41, section 8); cites by operation id and schema name, lines only where a rule is quoted. A later ruling that changes a row changes the sections it names in one pass.

| BQ    | Question                      | Default applied in this plan                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Sections                | Status                                                               |
| ----- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- | -------------------------------------------------------------------- |
| BQ-01 | stories and scenarios covered | US-IND-001..008 (24 scenarios), E13-S01..S08 (46), E13-T01..T03 (15), the ticket's seven cross-cutting items, `TM` AC-01..AC-24; E13-Q02..Q06 referenced only                                                                                                                                                                                                                                                                                                                  | 1, 3, 9                 | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-02 | the v1 set asserted           | the 28 descriptors `listIndicators` serves at the base (`V1_INDICATORS`: nine `compute: server`, nineteen `client_worker`); `delta` a rule metric, never served; the three story items with no descriptor (the MA ribbon D02 CG-5, the MA cross D06 Q-14, the composite of `14` SCR-034) get a case marked blocked on their owner, never a guessed id                                                                                                                          | 1, 3.2, 6, 10           | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-03 | ticket text vs merged design  | the merged design wins over the ticket text; each difference a section 10 row                                                                                                                                                                                                                                                                                                                                                                                                  | 1, 10                   | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-04 | path                          | `docs/qa/test-plans/e13-indicators.md`                                                                                                                                                                                                                                                                                                                                                                                                                                         | 1                       | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-05 | case ids                      | `E13-Q01-Cnn` (the template's form); the deviation row says E13-Q02 (#455) references these ids and the ticket's `E13-TC-nnn` is retired                                                                                                                                                                                                                                                                                                                                       | 0, 1                    | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-06 | sections                      | the template's ten plus section R; every case Pre / Steps / Expected / Oracle with `[R]` / `[F]` and "blocked on"                                                                                                                                                                                                                                                                                                                                                              | all                     | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-07 | matrix dimensions             | roles OWNER, MANAGER, VIEWER plus view-as; nine actions; nine states                                                                                                                                                                                                                                                                                                                                                                                                           | 2                       | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-08 | oracle ladder                 | the golden vectors at 1e-8 relative and the WS point > the API answer > the legend / mirror as presentation; value identity legend = WS point = rule vocabulary's metric = the sizer's kernel ATR; `client_worker` numerics are the parity pack's (E13-Q05)                                                                                                                                                                                                                    | 0, 3.4 (C34)            | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-09 | strings                       | every string is a deck key of `E13-D06-copy.json` or a `22` / `23` rule name, verbatim; the four stateless rows assert the drawn pattern and "no server text in the DOM", blocked on the owner's words                                                                                                                                                                                                                                                                         | 0, 3.9 (C62)            | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-10 | clocks                        | `CV_TEST_CLOCK` moves the auth clock only; `page.clock` for browser timers; warm-up is a bar count; VWAP / funding anchors are event time; the 30 s lease grace and the recompute timeout run on the server's real clock with no hook (a Known-gap row: the case waits ≤ 35 s or is blocked); no replay `sub` of `indicators.*` until E26                                                                                                                                      | 4                       | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-11 | fixture catalogue             | recorded, redacted Bybit fixtures only (C-13.5): the 2026-10-05 corpus `packages/fixtures/bybit/2026-10-05/` and the golden inputs (`kline_gap`, `synthetic_day`, `tape_1m`); no mid-day-start fixture on `main`, so the partial-CVD case is written against FX-PARTIAL and blocked on E13-Q05 (#458, its Scope); the seed script and the bar-replay feed are FX-G rows with E13-Q02 (#455) as the proposed owner; nothing filed (the freeze)                                  | 5, 6                    | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-12 | RBAC legs                     | one row per `22` `x-rbac` operation and the `23` §6.3 topic row; the server's answer asserted, never a role name; VIEWER T2 before any request and `403` by direct call; the cross-user preset `404` identical; `403 builtin_immutable`; the MANAGER count-only row blocked on E13-S08 (#465), whose operation is missing                                                                                                                                                      | 2.1, 3.9 (C61)          | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-13 | the problem-code matrix       | one leg per D06 §8.4 row; status and rule by API, the deck sentence where §8.4 names one, else the refusal pattern with no `title`, `detail`, `errors[].message` or WS `message` in the DOM                                                                                                                                                                                                                                                                                    | 3.9 (C62)               | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-14 | performance budgets           | budgets cited, never re-measured (D06 §8.1): 250 ms add, 100 ms re-tune, 2 ms pane redraw, O(1) tree ops, ≥ 55 fps and never under 30 fps for ten indicators, ≤ 18 / 40 draw calls; the fps-floor observation reads the engine's stats API through the E12-Q03 `ChartProbe` diagnostics island, blocked on E11-T07 / E46-S01; E13-Q03 (#456) is the measuring artefact; no probe added                                                                                         | 3.1 (C07), 3.3 (C33)    | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-15 | a11y vs E13-Q04               | D05 §14.1 referenced by hash, E13-Q04 executes it; this plan's UI cases are smoke; one black-box leg kept: every state carried in text, not colour                                                                                                                                                                                                                                                                                                                             | 3.1 (C08), 3.9 (C65), 8 | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-16 | the † table                   | one row per metric or event a case names that nothing emits at the base (the † table in `E16`'s form), re-grepped at the READY sha `54f4a82d2`; the stand-in asserted meanwhile. The emitters that exist (six in `metrics.py`, plus `indicator_preset_denied_total{reason}` and `indicator_presets_total{builtin}`) are asserted directly and are not rows                                                                                                                     | 10                      | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-17 | new hooks                     | no new hook, metric, string or number: every hook used exists or is a † / blocked row; no outside dry run for this plan (the routing's condition); the frozen set's "test hooks" are cited as white-box evidence only                                                                                                                                                                                                                                                          | 4, 6, 10                | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-18 | "destructive" here            | the soft delete and the un-star only; a scratch database per run, `P(pre)` / `P(post)` preset counts, the audit chain head; a built-in or a foreign row changed is P0                                                                                                                                                                                                                                                                                                          | 5                       | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-19 | open questions carried        | D06 Q-11..Q-17 by id with D06's owner lanes, plus this plan's OQ rows (the three descriptors, the `phase` label, the sub-pane height, the bundle import, the CVD pane, the referencing-objects lookup); both readings each                                                                                                                                                                                                                                                     | 10                      | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-20 | PR shape                      | one PR, one file, branch `test/e13-q01-indicators-plan`, title `docs(charting-ui): add the E13 indicator black-box test plan (E13-Q01)`, body `Closes #422`, labels `type/test`, `area/charting-ui`, `priority/p1`, `qa`; `large-pr-approved` at READY if over 800 lines; no `security-review` (the AC-01 to AC-24 content is black-box legs citing the threat model's controls, no control of its own); review = the independent Sonnet one-look plus the orchestrator's read | PR                      | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-21 | closing on the document       | the PR closes #422 on the plan alone (as #404 did); section 7's Entry criteria state that every frontend surface is unbuilt at the base and E13-T01 (#425) is open; the execution record is E13-Q06's (#459)                                                                                                                                                                                                                                                                   | 1, 7                    | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |
| BQ-22 | calendar                      | not late: READY within Sprint 06 (2026-10-30..11-05) so E13-Q02 can reference the ids; the ticket is Sprint 07; no lateness note                                                                                                                                                                                                                                                                                                                                               | PR                      | RULED (orchestrator, 2026-10-30, #422 ruling of record — 6532529903) |

## 2. The test matrix

The dimensions (ruled as BQ-07): **role** OWNER, MANAGER, VIEWER, plus the view-as leg (a session state: D06 §12, D05
T2-01..T2-04); **action** catalogue read, add, re-tune, remove, reorder / hide, star / save preset, replace, un-star, subscribe
(a `compute: server` instance); **state** empty chart, populated, at a client cap (20 instances / 6 sub-panes), at a server cap
(8 per user / 32 per symbol / 128 per process), warming up, errored, referenced by an armed rule, catalogue unavailable,
backend unreachable.

**2.1 Role by action.** A cell is the server's answer (`22` `x-rbac`; the `23` §6.3 row); a case asserts that answer and never a
role name. Add, re-tune, remove, reorder and hide of a `client_worker` instance are client state with no operation: for VIEWER
and view-as they are T2 before any request (D06 §12: `rbac.permission` under one header notice, T2-05..T2-07; `rbac.view_as`,
T2-01..T2-04) and the cell says so. "Server" means the answer `22` gives for the caller's permissions: MANAGER's permission set
is the RBAC seed's, not this plan's, so the case asserts what the server answers (OQ-7).

| Action                         | Operation (permission · scope)                                                                     | OWNER          | MANAGER                                 | VIEWER                                     | view-as                                 | Cases              |
| ------------------------------ | -------------------------------------------------------------------------------------------------- | -------------- | --------------------------------------- | ------------------------------------------ | --------------------------------------- | ------------------ |
| catalogue read                 | `listIndicators` (`marketdata:read` · none)                                                        | `200`          | `200`                                   | `200`                                      | `200`                                   | C01, C61           |
| list presets                   | `listIndicatorPresets` (`workspaces:read` · self)                                                  | own + built-in | own + built-in                          | server                                     | the viewed user's, read-only            | C13, C16, C61      |
| add (client_worker)            | none (client state)                                                                                | yes            | yes                                     | T2 `rbac.permission`, no request           | T2 `rbac.view_as`, no request           | C02, C61           |
| subscribe (server)             | WS `indicators.{symbol}.{bar_type}.{param}` (`marketdata:read` · none, `23` §6.3 `indicators` row) | `sub_ok`       | `sub_ok`                                | `sub_ok` (a read)                          | `sub_ok` (a read)                       | C22, C63           |
| re-tune, remove, reorder, hide | none (client state); the referential guard is E13-S08's                                            | yes            | yes; the blocked-removal count-only row | T2 `rbac.permission`                       | T2 `rbac.view_as`                       | C03, C04, C57, C61 |
| star / save preset             | `createIndicatorPreset` (`workspaces:write` · self · CSRF)                                         | `201`          | server                                  | `403` (T2 before it; AC-19 by direct call) | T2 `rbac.view_as`; `403` by direct call | C13, C14, C61      |
| replace                        | `updateIndicatorPreset` (`workspaces:write` · self · CSRF)                                         | `200`          | server                                  | `403`                                      | `403` by direct call                    | C13, C15, C16      |
| un-star                        | `deleteIndicatorPreset` (`workspaces:write` · self · CSRF)                                         | `204`          | server                                  | `403`                                      | `403` by direct call                    | C13, C17, C61      |

Cross-user: a `GET`, `PUT` or `DELETE` of another user's, a stale or a deleted `presetId` is one identical `404` whatever the
caller's role (`22` `updateIndicatorPreset`; `TM` AC-01, AC-02): C16. A built-in is `403` rule `builtin_immutable` for every
role (AC-03): C15.

**2.2 Action by state.** A cell names the cases that cover it. **n/a**: no such cell. **same**: no source states a different
answer, so the populated column covers it. **none**: no source states the result, so nothing is asserted.

| Action             | empty | populated | client cap 20 / 6       | server cap 8 / 32 / 128 | warming up | errored | referenced | catalogue unavailable | backend unreachable |
| ------------------ | ----- | --------- | ----------------------- | ----------------------- | ---------- | ------- | ---------- | --------------------- | ------------------- |
| catalogue read     | C01   | C01       | same                    | same                    | same       | same    | same       | C06                   | C19                 |
| add                | C02   | C05       | C09                     | C63                     | C24        | same    | same       | C06                   | C19                 |
| subscribe (server) | C22   | C22       | n/a                     | C63                     | C24, C38   | C11     | same       | same                  | C19                 |
| re-tune            | n/a   | C03, C10  | same                    | C63                     | same       | C11     | C57 (D17)  | same                  | C19                 |
| remove             | n/a   | C04       | C09 (frees a slot)      | same                    | same       | C11     | C57, C60   | same                  | same                |
| reorder / hide     | n/a   | C08, C09  | C09 (hiding frees none) | same                    | same       | same    | same       | same                  | same                |
| star / save preset | C13   | C13       | C14 (500)               | n/a                     | same       | same    | same       | same                  | C19                 |
| replace            | n/a   | C13       | same                    | n/a                     | same       | same    | same       | same                  | C19                 |
| un-star            | n/a   | C13, C17  | same                    | n/a                     | same       | same    | same       | same                  | C19                 |

## 3. Cases by user story

Each case starts from a fresh seed of the fixtures it names (section 6) and runs as OWNER unless its header says otherwise.
A case is: preconditions, steps, expected, oracle. A tester who did not write the plan can run any case from sections 4 to 6
alone. `P(pre)` and `P(post)` are the preset counts of section 5; `GV[set, indicator, i]` is the golden vector's value at bar
index i.

### 3.1 US-IND-001 Add, configure and remove indicators (Must)

**E13-Q01-C01 The catalogue serves the v1 set and the library renders it [R]** (`contract`, `e2e`; OWNER · empty; mirrors T02.3,
S01 landing; `22` `listIndicators`; D02 §9 :333–334; deck `d02.12.r01`..`r05`)

- Pre: FX-EMPTY; a chart on BTCUSDT 1m with no indicator.
- Steps: read `listIndicators` and `listIndicatorPresets`; open SCR-034 from the toolbar's Indicators button; read the tabs, the
  groups, the tags and the built-in preset rows; press each category tab.
- Expected: `200` with 28 `items`, each with `id`, `name`, `pane`, `compute`, `params_schema` (the `IndicatorDescriptor` required
  set) and a `params_schema` that is legal JSON Schema; exactly nine are `compute: server` (`sma`, `ema`, `vwap`, `atr`, `adx`,
  `rsi`, `zigzag`, `volume`, `cvd`: `catalogue.py` :615–619; `24`:1306) and no item is `delta` (`catalogue.py` :621–624);
  `listIndicatorPresets` returns the 18 built-ins of `21` §10.5 with `is_builtin: true` and `owner_user_id: null`, first. The
  dialog's title and placeholder are "Add indicator" · "Search indicators"; the tabs "All" · "Overlay" · "Sub-pane" ·
  "Order-flow"; the groups "Favourites" · "Recents" · "Trend" · "Momentum" · "Volatility" · "Volume" · "Order flow", Recents
  reading "store pending — CG-3" (D02 CG-3); every `compute: server` entry carries "Requires recorded history", an
  `estimated` one "(estimated)"; a built-in's rows follow its entry flat ("Trend · Overlay · 4 presets" → "ema(21) · preset"),
  and the nine built-ins whose indicator the catalogue does not serve are hidden, never disabled (D02 §9 :334). The
  "Order-flow" tab lists `category: orderflow` (D06 §3.3). Descriptions are an empty labelled slot (D02 CG-6).
- Oracle: the two reads > the DOM (a presentation check). 2nd: none (a read).

**E13-Q01-C02 Add EMA(21) renders in the price pane with the kernel's value [R]** (`e2e`, `integration`; OWNER · empty to
populated; mirrors US-IND-001/1, S01.1, T02.1; D02 D6 :146; D06 §8.1 :257; `23` §6.1 "Options" to "Snapshot and deltas")

- Pre: FX-TAPE loaded (180 closed bars); FX-EMPTY presets.
- Steps: in SCR-034 type "ema", press `Enter`; watch the legend row and the WS frames; read the announcement region; read the
  entry's action after the add.
- Expected: the legend row appears at once with value "—" and the word "computing…"; a `sub` of `indicators.BTCUSDT.time.1`
  with one entry `{indicator: "ema", params: {n: 21}}` answers `sub_ok` whose `effective` echoes the instance with every param
  and its read-only `key`; the snapshot holds the last `history` closed-bar points, oldest first, `null` before `warmup_bars`
  and never 0 or NaN; the row's value fills, "EMA 21 added to price pane" is announced once (never per bar), the entry's
  action reads "Add second instance" and its tag "On chart ×1"; the dialog stays open. The first visible window is mounted and
  computed within 250 ms for a 100k-bar series (`14` SCR-034 Performance via D06 §8.1): the figure is cited, E13-Q03 measures it (FX-100K is an
  FX-G row).
- Oracle: the WS point at bar i equals `GV[tape_1m, ema, i]` within the manifest tolerance, and the legend value equals the WS
  point at the cursor bar (presentation) > `sub_ok` > the strings. 2nd: `indicator_subscriptions{bucket="1"}` reads 1 and
  `indicator_cache_misses_total` rises by one (`metrics.py` :45–48); `indicator.added`†.

**E13-Q01-C03 A parameter change recomputes without a reload: the server leg commits on Apply, the worker leg within 100 ms
[R]** (`e2e`, `contract`; OWNER · populated; mirrors US-IND-001/2, S01.2, T01.3; D06 §6; D02 D13 :191; `23` §6.1 "Options"; deck
`d02.12.r18`, `r23`, `r24`)

- Pre: C02's EMA(21) (server) and a WMA(20) (`client_worker`) on the chart.
- Steps: open EMA 21's Settings from the legend gear; read the initial focus and the help line under Period; type 34; watch the
  WS frames; press Apply. Repeat on WMA 20 → 34 and watch the tile and the chart.
- Expected: focus lands on the Inputs tab (D06 C-a); the help reads "1–5000 bars"; the tile shows the committed curve with
  "Preview on Apply — this indicator is computed on the server." and no `ctl` leaves before Apply (D06 §8.3 row (4)); Apply
  sends one `ctl` whose `instances` carries the new params, answered by a `snap`, never a `d` (`23` §6.1 "Options": `instances` is an
  identity option), and the legend reads the new value with no chart reload; "Applying…" shows only past 100 ms. The WMA leg
  recomputes the visible window within 100 ms (`14` SCR-035 Performance via D06 §8.1; "Updating…" only past 100 ms), the chart previews the
  change display-only, and Apply commits with no request. Neither leg reloads the chart or re-keys any other instance.
- Oracle: the `snap`'s points equal `GV[tape_1m, ema, i]` for n = 34 if the vector set holds that spec, else the kernel's
  value through the parity pack (E13-Q05) > the frame sequence (`ctl` → `snap`) > the legend. 2nd:
  `indicator_recompute_total{reason="param_change"}` rises by one for the server leg (`metrics.py` :54–59);
  `indicator.settings_changed`†.

**E13-Q01-C04 Remove shows a 10-second Undo and frees the slot [R]** (`e2e`; OWNER · populated; mirrors US-IND-001/3, S01.3;
D05 FM-09, FM-10; deck `d02.12.r36`; `limits.py` :74)

- Pre: three instances, EMA 21 (server) among them; SCR-036 open.
- Steps: focus EMA 21 in the tree and press `Del`; read the toast, the focus target and the announcement; move the browser clock
  by 10 s; repeat on another instance and press Undo inside the 10 s.
- Expected: the row leaves the pane and the legend; the toast reads "EMA 21 removed." with "Undo" (a `Tab` stop that takes no
  focus), the announcement "EMA 21 removed. Undo available for 10 seconds"; focus lands on the next tree item, else the group
  header, else Add indicator; after 10 s the toast is gone; Undo restores the instance to the pane and the legend. The server
  instance is released: the user's held count drops and the instance folds for its 30 s grace before it is removed
  (`limits.py` :72–74) — asserted by polling `indicator_subscriptions{bucket}` with a deadline of 35 s and asserting on the first settle (section 4). The "template
  diff" half of US-IND-001/3 is **blocked on D06 Q-6** (no template surface is drawn).
- Oracle: the legend and tree state > the toast and focus (presentation) > the gauge. 2nd: `indicator.removed`†.

**E13-Q01-C05 A second instance takes the next slot and is told apart by parameters** (`e2e`; OWNER · populated; mirrors S01.4;
deck `d02.12.r04`, `r06`, `r13`; D06 §10.5; `23` §6.1 "Identity")

- Pre: C02's EMA(21).
- Steps: in SCR-034 open EMA again; press "Add second instance"; read the labels, the announcement and the WS frames; then add
  EMA with source `hl2` and read its label.
- Expected: the second instance is labelled "EMA 21 (2)" and announced "EMA 21 (2) added to price pane"; it takes the next free
  palette slot and the next tier on its pane (D03 §3.4 via D06 §10.5: a pair is never shared on a pane); two entries of one
  request with the same `key` would be `invalid_options` (`23` §6.1 "Identity"), so the client holds one server instance for the shared
  key and the chart counts two (D02 D5 :140); the `hl2` instance is labelled "EMA 21 · hl2" and carries its own `key`. The
  chart's count chip reads "Ind 3".
- Oracle: the WS `effective` (one key for the identical pair, a distinct key for `hl2`) > the labels (presentation). 2nd:
  `indicator_cache_hits_total` rises when the shared key is joined (`metrics.py` :45–48).

**E13-Q01-C06 The catalogue cannot be loaded [F]** (`e2e`, `contract`; OWNER · catalogue unavailable; mirrors S01.5; `22`
`listIndicators` `503`; D02 §9 :333; D06 §3.2, §8.4, Q-12)

- Pre: two instances on the chart; the stack answers `listIndicators` with `503`, then `401`, then a body with a hostile
  `title` and `detail`.
- Steps: open SCR-034 each time; read the list region and the Retry control; let the route recover and press Retry.
- Expected: skeleton rows with `aria-busy` while loading (CMP-015), then a CMP-027 error with Retry; no partial list is shown
  as complete; the two instances keep rendering; no `title`, `detail` or `errors[].message` from the body reaches the DOM
  (D06 §8.3 row (6)); `401` follows the shell's session flow, not an E13 string (D06 §8.4); Retry re-reads and the list fills.
  The failure sentence is **blocked on D06 Q-12** (no deck row): the pattern is asserted, not the words.
- Oracle: the responses > the DOM scanned for the injected text (a presentation check). 2nd: none (a read).

**E13-Q01-C07 Ten indicators across three panes keep the frame budget; blocked on the diagnostics island** (`perf`, `e2e`;
OWNER · populated; mirrors S01.6, US-IND-001 NFR; D06 §8.1 :262; D03:178; D02 D27 :306; deck `d03.13.r09`, `d02.12.r42`)

- Pre: FX-TAPE; ten instances: the price pane and two sub-panes (RSI, MACD), the rest overlays; a 600 px compact pane.
- Steps: scroll and zoom through the series for 60 s; read the engine stats; read the legend and the chip.
- Expected: at least 55 fps and never below the 30 fps floor (`11`:1360; `06` budget #2); at most 18 draw calls per pane and 40
  per chart, a tier never adding a call (D03:178 via D06 §8.1); the legend shows at most ⌊0.3 × pane height / row height⌋ rows,
  never fewer than 3, the rest behind "+N more" counting rows not series (a 600 px compact pane: 7 rows and "+6 more"; the
  announcement "6 more series"); the chip reads "Ind 10". **How to observe:** the engine publishes `fps`, `frameTimeMsP50`,
  `frameTimeMsP95` and `drawCalls` on its stats API (`packages/chart-engine/src/api/types.ts` :164–170); no UI surface shows
  them at the base, and the proposed reader is the E12-Q03 `ChartProbe` diagnostics island
  (`apps/web/e2e/specs/e12-bars/chart-probe.ts` :3–8, `test.fixme` until E11-T07 / E46-S01 land) — the case is **blocked on it**;
  E13-Q03 (#456) is the measuring artefact and this plan adds no probe.
- Oracle: the stats reading through the island > the legend and chip (presentation). 2nd: `indicator_active_instances`†.

**E13-Q01-C08 The keyboard-only path completes with focus returned** (`e2e`, `a11y`; OWNER · populated; mirrors S01.7; D06
§5.1–§5.3, §7; D05 FM-01..FM-10 by id; deck `d02.12.r42`, `r44`)

- Pre: FX-TAPE; one instance on the chart.
- Steps: by keyboard alone: open SCR-034 (`Ctrl+K` "Add indicator…" or the toolbar button), type, arrow down, `Enter`; `Esc`
  twice; open the legend row's Settings, change Period, Apply; open SCR-036 from the count chip; `Space` on the item; `Alt+↓`;
  `Del` on an unreferenced item.
- Expected: SCR-034 opens with the combobox focused and the query empty; the list is not a `Tab` stop; `Esc` clears a
  non-empty query first, then closes and returns to the invoker; SCR-035 opens on the Inputs tab and Apply returns focus to the
  invoker; SCR-036 opens on the first tree item; `Space` announces "EMA 21 hidden" then "EMA 21 shown"; `Alt+↓` moves the
  item and announces "EMA 21 moved up, 2 of 4"-form once; `Del` removes with focus on the successor (FM-09); focus is visible at
  every stop. This is smoke only: the spoken strings, the announcement cadence and the axe pass are E13-Q04's (D05 §14.1 by
  hash, D06 §9.2).
- Oracle: the request log (no request for the client-state actions) > the focus target at each step (UI only). 2nd: none.

**E13-Q01-C09 The 20-instance and 6-sub-pane caps are client gates with no network call [F]** (`e2e`; OWNER · client cap;
mirrors `TM` AC-14; D02 D5 :140; D06 §8.3 row (3), §12 T2-09..T2-11, D06-G-4; deck `indicator.cap_instances`, `d02.12.r28`)

- Pre: FX-TAPE; 19 overlays and 5 sub-panes already added.
- Steps: add a 20th instance; try a 21st from SCR-034, from the palette and from the tree's "Add second instance"; hide one and
  try again; add a 6th sub-pane indicator, then a 7th; read the chip; remove one and try again.
- Expected: the 20th is added; "Add to chart" for the 21st is `aria-disabled` with "This chart has the maximum of 20
  indicators. Remove one to add another." in the DOM at mount, and no request or WS frame is sent; the palette command is
  greyed with the reason as its hint; a hidden instance still counts ("Hiding does not free an indicator slot."); the 7th
  sub-pane reads "This chart has the maximum of 6 sub-panes. Remove a sub-pane indicator to add another."; the chip reads
  "Ind 20"; a removal frees the slot. A layout save with more than 16 preset references is refused by the `22` schema
  (`LayoutPaneInput.indicator_preset_ids` `maxItems: 16`; D06-G-4): stated, not resolved (OQ-8). The
  preset-or-template-load half of AC-14 is **blocked on E15-S07** (C20).
- Oracle: the request log (none) > the control state and reason (presentation). 2nd: `indicator_cap_rejected_total` is
  unchanged (the gate is the client's).

**E13-Q01-C10 The live preview is display-only and the commit model holds [R]** (`e2e`; OWNER · populated and referenced;
mirrors D02 D11, D12 :187; D06 §6 table; D05 T2-14; deck `d02.12.r19`, `r23`, `indicator.style_pending`)

- Pre: an unreferenced WMA(20), a server EMA(21) and (once E13-S08 lands) an EMA referenced by an armed rule (FX-RULE).
- Steps: on WMA type 34, watch the tile and the chart, press `Esc`; type 0, read Apply and the field; press `Tab` away; on EMA
  type 34 and watch the frames; open the Style tab.
- Expected: the tile's caption reads "Preview: last 200 bars, display-only"; the chart previews the change display-only and `Esc`
  restores the committed values; 0 is refused, never clamped: the field keeps the typed value with `aria-invalid` and "Period
  must be between 1 and 5000." beside it, Apply keeps its label at `opacity.disabled` with "Fix the highlighted field first."
  (form validity is not T2); blur commits nothing; the server leg shows "Preview on Apply — this indicator is computed on the
  server." and sends no `ctl` before Apply; the Style tab shows one note "Style tokens arrive with E13-D04" and no gated
  control (D06 C-b; the enabled state once E05-T01 lands). The referenced leg (the D17 guard) is C57's.
- Oracle: the request and frame logs > the control states (presentation). 2nd: no `indicator_recompute_total` change before
  Apply.

**E13-Q01-C11 A failed computation isolates one instance and renders no transport text [F]** (`e2e`, `contract`; OWNER ·
errored; mirrors T01.5; D02 D27 errored :292; D06 §9.3, Q-16; `23` §6.1 "Refusals"; deck `d02.07.errored`, `d02.12.r42`, `r43`)

- Pre: three instances. The server leg: a first computation the full-recompute executor cannot start (`23` §6.1 "Refusals": both of the 2
  slots busy, SR-E13-04) answers `internal_error`. The worker leg (a plugin that throws inside `compute()`) has **no black-box
  fault seam at the base**: it is E13-T01's unit test, cited as white-box evidence, and the leg is **blocked on a seam** (Known
  gaps).
- Steps: provoke the server refusal with a `sub` carrying a hostile `message`; read the row, the announcement and the chip;
  operate the eye on the errored row.
- Expected: the row shows an error glyph, the word "error", value "—" and the detail "Compute failed: <reason>" where `<reason>`
  is "History for this indicator can't be computed right now." (the closed map; PROPOSED, **blocked on Q-16** for the words);
  "EMA 21: compute failed" is announced once; the chip reads "Ind 3 · 1 error"; the other two instances keep rendering; the WS
  `message` never reaches the DOM; the eye stays operable; the chart does not crash.
- Oracle: the `err` / `sub_ok` code > the DOM scanned for the injected text (presentation). 2nd:
  `indicator_cap_rejected_total{cap="recompute"}` rises by one (`metrics.py` :66–72); `indicator_instance_errors_total`†.

**E13-Q01-C12 Degradation sheds frequency, not correctness; blocked on the diagnostics island** (`perf`; OWNER · populated;
mirrors T01.4; D06 §8.1 :262; `06` §4.3)

- Pre: C07's ten-indicator scene under the §4.2 worst-case load generator (an FX-G row).
- Steps: run the load for 60 s; read the legend values at a fixed cursor bar; read the stats.
- Expected: indicator pane redraws coalesce to every second frame under load (D03:476–488 via D06 §8.1) and every legend value
  still equals the kernel's at that bar; the pane redraw stays ≤ 2 ms per frame (`06`:78). The cadence reading is **blocked on
  the diagnostics island** (C07); the value leg runs.
- Oracle: `GV[tape_1m, <indicator>, i]` for the server rows > the stats. 2nd: none.

**E13-Q01-C13 Star, save as default, replace and un-star round-trip through the preset routes [R]** (`e2e`, `contract`; OWNER ·
populated; mirrors T03 CRUD, S01 preset consumption; `22` `createIndicatorPreset`, `updateIndicatorPreset`,
`deleteIndicatorPreset`; D06 §3.1; deck `d02.12.r03`, `r07`, `r14`, `r24`, `r25`)

- Pre: FX-EMPTY presets; C02's EMA(21); `P(pre)`.
- Steps: star EMA in SCR-034; open the palette; in SCR-035 set 34, press "Save as default for this indicator", read the row,
  Save; Save again with the same name; press Replace; "Reset to catalogue defaults", then "Reset to my default"; un-star in
  SCR-034; read the Favourites group.
- Expected: the star sends `createIndicatorPreset` (`is_favourite: true`) → `201` with a server-minted `id`,
  `owner_user_id` the caller, `is_builtin: false`; Favourites lists it and the palette offers "Add favourite: EMA 21"; the save
  row shows "Preset name" prefilled "EMA 34", Save → `201` and "Saved as your default for EMA"; the second save answers `409`
  rule `name_taken` → "A preset named 'EMA 34' exists." / "Replace", and Replace sends `updateIndicatorPreset` → `200` (the
  last write wins, no precondition); "Reset to my default" applies the saved `params` (stored complete and canonical); the
  un-star sends `deleteIndicatorPreset` → `204` and the group reads "No favourites yet." / "Star an indicator to keep it here.";
  every write carries the CSRF token.
- Oracle: `P(post)` − `P(pre)`: live +1 after the star, +2 after the save, +2 after the replace, then +1 live and +1 deleted >
  the statuses > the strings. 2nd: `indicator_preset.created` ×2, `.updated` ×1, `.deleted` ×1, each written ahead of the row
  (D06 §8.2); `indicator_presets_total{builtin="false"}` moves with the live count (`metrics_catalogue.py` :2628–2638).

**E13-Q01-C14 Preset refusals name the rule, store nothing and never clamp [F]** (`contract`, `security`; OWNER · populated;
mirrors T03.3, T03.4, `TM` AC-04..AC-08; `22` `createIndicatorPreset`, `IndicatorPresetInput`, `IndicatorPresetStyle`; deck
`d02.12.r12`, `r19`)

- Pre: FX-EMPTY presets; `P(pre)`; a user at 499 live presets for the cap leg.
- Steps: `POST` `atr` with `params.n` in {−1, 0, 5001, 1e9, "14", null, NaN, 1.5} and with an extra key; with `n: 5000`; with
  `indicator_code` in {"nope", "atr_trail", 33 × "a", "ATR", "../x", "ema;drop"}; with `style` `{"line": "#ff0000"}`,
  `{"line": "url(javascript:1)"}`, `{"__proto__": {"x": 1}}`, `{"w": 1e308}`; with `is_builtin: true`, `owner_user_id`, `id`,
  `deleted_at`; with `params` of 5 KiB, of depth 6, of 65 keys; with a 2 MiB body; with a 81-character name; the 500th and
  501st presets; "Fast" then "fast" on `ema`.
- Expected: `422 validation_failed` per bound with the first defect only, naming the bound and never the value (`minimum`,
  `maximum`, `type` or `multipleOf` on `params.n`; `additionalProperties` on `params`); `n: 5000` is `201`; `invalid_indicator_code`
  or `unknown_indicator`, the message echoing no value; `style_not_allowed` for every style (only `{}` is accepted until the
  vocabulary ships: `IndicatorPresetStyle`; D06 §8.3 row (2)), never a silent drop; the server-managed fields are refused as
  unknown properties; `params_too_large` / `params_too_deep` / `params_too_many_keys`; `413 payload_too_large` before the body
  is parsed; `string_too_long`; the 500th is `201`, the 501st `409` rule `limit_reached` → "You have the maximum of 500 saved
  presets. Delete one to star another."; "fast" is `409` `name_taken` and "Fast" is untouched. In SCR-035 a `422` on `params`
  renders as the field's `d02.12.r19` sentence, never the server's `title` or `detail`; no 500 anywhere.
- Oracle: `P(pre)` equals `P(post)` but for the valid saves > the status and rule per call > the inline text. 2nd: no audit
  record for a refusal (the write-ahead record precedes a write that happens); `indicator_preset_denied_total` unchanged (its
  reasons are `not_owner` and `builtin_immutable` only, `metrics_catalogue.py` :2640–2650).

**E13-Q01-C15 Built-ins are present, immutable and copied on customise [F]** (`contract`, `e2e`; OWNER, MANAGER · populated;
mirrors T03.1, `TM` AC-03; `21` §10.5; `22` `updateIndicatorPreset`; D06 §8.4, Q-17)

- Pre: FX-EMPTY (the seed ran).
- Steps: read `listIndicatorPresets`; `PUT` and `DELETE` `ema(21)`'s built-in id as each role; star `ema(21)` in SCR-034 and
  read what is sent; star `cvd(never reset)`.
- Expected: 18 built-ins, `is_builtin: true`, `owner_user_id: null`, `style: {}`, `is_favourite: false`, names verbatim from
  `21` §10.5, ids stable across runs (uuid5); every write on one is `403` rule `builtin_immutable` and the row is unchanged; the
  star sends `createIndicatorPreset` (a user-owned copy that may keep the name), never a `PUT`; the `cvd(never reset)` copy is
  `422` rule `enum` on `params.anchor` (`21` §10.5: the served `cvd` anchors are `session` and `utc_day`, `catalogue.py` :610–613)
  and the nine built-ins whose indicator is unserved are hidden in SCR-034 (C01). The words for a `403 builtin_immutable` are
  **blocked on Q-17**: the refusal pattern with no server text is asserted.
- Oracle: `P` built-in rows unchanged (a change is P0, section 5) > the statuses > the DOM. 2nd:
  `indicator_preset_denied_total{reason="builtin_immutable"}` rises by one per refusal and `rbac.denied` is audited
  (`metrics_catalogue.py` :2644–2646).

**E13-Q01-C16 Another user's preset is one identical `404` [F]** (`security`, `contract`; MANAGER as B, OWNER as A · populated;
mirrors T03.2, `TM` AC-01, AC-02, IR-01; `22` `updateIndicatorPreset`, `deleteIndicatorPreset`; D06 §3.1)

- Pre: FX-USERS: A owns a live preset, a deleted preset and no built-in; B owns one preset.
- Steps: as B `PUT` and `DELETE` A's live id, A's deleted id and a random UUID; as B read `listIndicatorPresets`; as A read the
  row.
- Expected: the three ids answer one identical `404` body each on `PUT` and on `DELETE` (existence is not disclosed); A's row
  keeps its `updated_at` and `deleted_at`; B's list holds only B's rows and the built-ins, no `owner_user_id` of A in any
  item. `22` declares no single-preset `GET`: AC-01's `GET` leg is the list leg (AC-02), noted in OQ-9.
- Oracle: the bodies compared byte for byte > `P` unchanged for A > the list. 2nd:
  `indicator_preset_denied_total{reason="not_owner"}` rises by one per foreign-id write and `rbac.denied` is audited.

**E13-Q01-C17 Deletion is soft and reversible at the data layer** (`contract`, `integration`; OWNER · populated; mirrors T03.5;
`22` `deleteIndicatorPreset`)

- Pre: C13's saved preset; `P(pre)`.
- Steps: `DELETE` it; read the list; `DELETE` it again; create a preset with the same name; un-star a favourite whose row was
  deleted from another session.
- Expected: `204`; the row remains with `deleted_at` set and leaves the list; the second `DELETE` is `404`; the name is free
  again (`201`); the un-star of a gone preset renders no server text and the star re-syncs from `listIndicatorPresets` (D06
  §3.1; the words are Q-17's).
- Oracle: `P(post)`: live −1, deleted +1, no row removed (a hard delete is P0) > the statuses > the star state. 2nd:
  `indicator_preset.deleted` once; `indicator_presets_total{builtin="false"}` −1.

**E13-Q01-C18 A symbol and timeframe switch rebuilds the whole stack and stays within the churn bound [F]** (`e2e`,
`integration`; OWNER · populated; mirrors the ticket's cross-cutting item 6; T01 scope (`recompute(range)` on a switch);
`23` §6.1 "Identity", :785; `limits.py` :61–74; deck `d02.12.r27`, `r40`)

- Pre: FX-TAPE on BTCUSDT 1m and a second recorded symbol; eight server instances and two `client_worker` ones.
- Steps: switch the chart to the second symbol; switch 1m → 5m; read the legend, the chip and the Alerts tab's metric key;
  then flip symbol a third time within 30 s.
- Expected: every row reads "computing…" then its value; the chip stays "Ind 10"; each server instance's `key` changes (it
  binds the bar series' `spec_hash`, `23` §6.1 "Identity") and the Alerts tab's metric key names the new timeframe in the `ema(21, 5m)`
  form; the released instances fold for their 30 s grace. Two full flips of eight within 30 s stay under the churn bound of 24
  (`limits.py` :66–71); variant b: a third flip inside the grace is refused `subscription_limit` whose message says the released
  instances still count until they expire, retryable (`23` §6.1 "As built") — rendered as `d02.12.r10`'s per-user sentence, never the WS
  `message`.
- Oracle: the WS `effective` keys > the legend and chip (presentation). 2nd: `indicator_cache_misses_total` rises by eight per
  flip; variant b `indicator_cap_rejected_total{cap="user"}` rises by one.

**E13-Q01-C19 Backend unreachable: the library fails honestly and server rows go stale, never live [F]** (`e2e`; OWNER ·
backend unreachable; mirrors the ticket's cross-cutting item 7, S01.5; D02 D27 stale; `23` §7.2 `meta.stale`; deck
`d02.12.r27`, `r40`, `r43`)

- Pre: four instances, two of them server; SCR-035's Alerts tab open on one.
- Steps: stop the API and refuse the WS reconnect for 10 s; move the browser clock past 2 s; open SCR-034; read the rows, the
  chip and the Alerts tab; let the stack return.
- Expected: SCR-034 shows the CMP-027 error with Retry (C06); the `client_worker` rows keep rendering; after 2 s without an
  expected update each server row freezes its value in `color.text.tertiary` with "Stale 7s"-form and "last 13:42:05"-form in
  its detail, "stale" in the accessible name, no "computing…" and no bounded-end timer; the chip reads "Ind 4 · 2 stale"; the
  Alerts tab reads "Stale 7s · last 13:42:05"-form; nothing is announced per tick; the first frame after the reconnect (a `snap`
  or `d`) clears the state. A `snap` carrying `meta.stale: true` renders the same.
- Oracle: the harness's timestamped frame log > the DOM (presentation). 2nd: `indicator_subscriptions{bucket}` returns to its
  pre-outage value after the reconnect.

**E13-Q01-C20 A hostile `WorkspaceBundle` import is refused whole; blocked on E15-S07** (`security`, `contract`; OWNER ·
populated; mirrors the ticket's cross-cutting item 5, `TM` AC-04, AC-09, IR-06, IR-10; `22` `WorkspaceBundle`)

- Pre: a bundle of 201 presets; one whose preset JSON is 1.1 MiB; one mixing valid presets and one invalid; one whose item
  carries `is_builtin: true` or `owner_user_id`; a user at 499 live presets. **No operation takes a bundle at the base** (`22`
  `WorkspaceBundle`: "Import (E15-S07; no operation takes a bundle yet)"): the case is **blocked on E15-S07 (#560)**.
- Steps (once it lands): import each bundle; export the user's bundle.
- Expected: each is refused whole (`422` / `413`), nothing imported, `P` unchanged; an item carrying `is_builtin` or
  `owner_user_id` is refused, never honoured; an import past 500 live presets is refused; the export holds only the caller's live
  presets, never a built-in or another user's, at most 500 and never truncated to the import limits.
- Oracle: `P(pre)` equals `P(post)` on every refusal > the statuses. 2nd: no `indicator_preset.imported` record on a refusal
  (ACT, D06 §3.1).

**E13-Q01-C21 A time-based indicator is disabled over a renko series; blocked on Q-15** (`e2e`; OWNER · populated; mirrors T01
scope (the renko guard); D06 Q-15)

- Pre: a renko series on the chart.
- Steps: open SCR-034; read the entries of time-based indicators.
- Expected: the control is disabled with a tooltip; its sentence has no deck row, so the words are **blocked on Q-15**: the
  pattern is asserted, the text is not.
- Oracle: the control state (presentation). 2nd: none.

### 3.2 US-IND-002 Moving averages family (Must/Should)

**E13-Q01-C22 SMA and EMA match the reference to 1e-8 on every fixture day, through the kernel and the topic [R]** (`integration`,
`contract`; OWNER · populated; mirrors US-IND-002/1, S02.1, T02.1; `GV` `manifest.json`; `23` §6.1 "Snapshot and deltas")

- Pre: FX-TAPE, FX-GAP and FX-SYN loaded in turn; FX-EMPTY presets.
- Steps: subscribe `indicators.BTCUSDT.time.1` with `sma` (n 20) and `ema` (n 21) at their defaults, `history` 1 000; read
  the snapshot; append the remaining bars of the day through the replay feed and read each `d`.
- Expected: every point equals `GV[<set>, sma | ema, i]` within the manifest tolerance (`abs(kernel - reference) <= 1e-8 *
max(1, abs(reference))`, `None` positions equal; `kernel_values` compared bit for bit after parsing to binary64); on FX-GAP
  the densified fillers (bars 200–214 removed and refilled) publish no point, so the points carry the indexes of the real bars
  (`23` §6.1 "Snapshot and deltas") and the vector's `None` positions line up; on FX-SYN the zero-volume bars and the 1-, 7- and 30-bar gaps produce
  the vector's values. The worker mirror and the five `client_worker` MAs (`wma`, `vwma`, `smma`, `dema`, `tema`: `catalogue.py`
  :428–462, no golden set at the base) are E13-Q05's (#458) numerics: this plan asserts their presence and warm-up only (C24).
- Oracle: `GV` > the WS frames. 2nd: `indicator_compute_seconds{indicator="sma"|"ema", where="server"}` has observations
  (`metrics.py` :38–43).

**E13-Q01-C23 An MA ribbon of five lengths is one expandable legend entry; blocked on D02 CG-5** (`e2e`; OWNER · populated;
mirrors US-IND-002/2, S02.2; D02 D16, CG-5; D06 §10.5, §15.2)

- Pre: **no ribbon descriptor exists at the base** (`listIndicators` serves 28 ids, none a ribbon: D02 CG-5 :652, owner E13-S02
  #424 with E13-T02): the case is **blocked on CG-5**; nothing is guessed about its id or params.
- Steps (once it lands): add the ribbon; read the legend row; press `→` and `←` on the row; read the series.
- Expected: one instance, one legend row with a disclosure chevron showing the five lengths; expanded, five sub-rows each with
  value and eye; `←/→` collapse and expand it inside the legend's roving stop (D05 KL-01); the five series are five tiers of
  one hue, told apart by weight and dash, never colour alone (D03 §7.2 via D06 §10.5); the ribbon counts as 5 series for the
  draw-call budget in one instanced line pass (S02 Performance: E13-Q03 measures).
- Oracle: the DOM (presentation) > the draw-call reading (C07's island). 2nd: `indicator.added`†.

**E13-Q01-C24 Insufficient history renders from the first valid bar, states the count and never a zero [R] [F]** (`e2e`,
`contract`; OWNER · warming up; mirrors US-IND-002/3, S02.3, T01.2, T02.4; `22` `IndicatorDescriptor.warmup_bars`,
`nullable_when`; `24`:1166; D02 D27 insufficient history; deck `d02.12.r13`, `r27`, `r40`, `d05.lr05`)

- Pre: FX-TAPE's first 180 bars loaded; the remaining bars held back by the replay feed.
- Steps: add EMA 200 and WMA 200; read the rows, the announcement, the WS snapshot and the Alerts tab; release bars one at a
  time until the first value lands.
- Expected: `warmup_bars` for `ema` at n = 200 is 200 (`24`:1166: the warm-up equals `n` for the MAs; `catalogue.py` :30–31:
  the first value is on bar `warmup_bars`); the server snapshot carries `null` for every point before it, never 0 or NaN
  (`23` §6.1 "Snapshot and deltas"); the legend row's value reads the `d02.12.r40` form "34 more bars needed" with the fixture's count (warm-up minus
  loaded, recomputed as bars arrive), the series starts at the first valid bar and no zero-valued series is drawn; "EMA 200
  needs 34 more bars"-form is announced once on add; the Alerts tab reads "—" with the `nullable_when` reason and
  "Unavailable: warm-up"; when the first value lands, "EMA 200 ready" is announced once (deck `d05.lr05`, PROPOSED under A29:
  the words are **blocked on D06 Q-1**, the event is asserted). The WMA row behaves the same (its numerics E13-Q05's).
- Oracle: `GV[tape_1m, ema, i]` is `None` for i < 199 at n = 200 if the set holds that spec, else the `null` rule of `23` §6.1 "Snapshot and deltas" >
  the snapshot > the row text. 2nd: none per tick (D02 D27: no announcement per bar).

**E13-Q01-C25 A source selection changes the result and the key; blocked on the `source` parameter** (`e2e`, `contract`; OWNER ·
populated; mirrors S02.4; `catalogue.py` :421–426; deck `d02.12.r04`, `r18`)

- Pre: **`sma` and `ema` serve one parameter, `n`, at the base** (`catalogue.py` :421–426: `(_period(20),)`, `(_period(21),)`); the
  `source` and `offset` parameters of E13-S02's scope are not served, so the case is **blocked on E13-S02 (#424) with E13-T02**;
  the deck's label "EMA 21 · hl2" and help "Source: series available on this chart" stand ready.
- Steps (once served): add SMA 20 on `close` and a second on `hl2`; read the labels, the keys and the values.
- Expected: two distinct series and two distinct `key`s (`23` §6.1 "Identity": the key binds every param); the second labelled "EMA 21 ·
  hl2"-form; an unavailable source refused with "Choose a source available on this chart." (`d02.12.r19`).
- Oracle: the WS `effective` keys and points > the labels. 2nd: `indicator_cache_misses_total` +2.

**E13-Q01-C26 Incremental equals full: the bar-by-bar series equals the snapshot, and a restart re-primes to the same values [R]**
(`integration`; OWNER · populated; mirrors S02.5, T01.1, T02 scope (`snapshot()` / `restore()`); `23` §6.1 "Snapshot and deltas" to "Amended bars and generations")

- Pre: FX-TAPE; SMA 20 and EMA 21 subscribed before the first bar.
- Steps: replay the day bar by bar and record every `d`; then subscribe a fresh connection with `history` 1 000 and read the
  snapshot; restart the API mid-day and resubscribe.
- Expected: the sequence of `d` points equals the snapshot point for point (incremental equals full), and both equal `GV`; after
  the restart the re-primed instance serves the same points (a restart resumes without recomputing a day: T02 scope). The
  property-based legs over a generated 100k-bar series (T01.1, S02.5) are white-box: E13-T01's `assertPluginConforms` kit and
  E13-T02's tests, cited as evidence; FX-100K is an FX-G row.
- Oracle: `GV` > the two frame sets compared. 2nd: `indicator_recompute_total{reason="backfill"}` rises on the re-prime
  (`metrics.py` :54–59).

**E13-Q01-C27 The MA cross is a metric only; blocked on D06 Q-14** (`contract`; OWNER · populated; mirrors S02 scope (a derived
boolean or marker output); D06 Q-14)

- Pre: no merged design draws a cross marker and no descriptor serves one at the base: **blocked on Q-14** (the owner on #2701)
  and on E13-S02 (#424).
- Steps (once ruled): add the cross; read the legend and the chart.
- Expected: under the default reading nothing is drawn and the metric is exposed to the editors (C55); under a marker ruling the
  marker carries a text label (D03 §4.4: ▲ and ▼ reserved for a direction with a word).
- Oracle: the vocabulary read > the DOM. 2nd: none.

### 3.3 US-IND-003 Oscillators (Must/Should)

**E13-Q01-C28 RSI(14) opens a linked sub-pane with guide levels and a shared crosshair [R]** (`e2e`, `integration`; OWNER ·
populated; mirrors US-IND-003/1, S03.1; `catalogue.py` :510–512; D03:256–263 via D06 §10.5; D06 §5.1 (the splitter); deck
`d03.13.r08`, `d04.10.r01`)

- Pre: FX-TAPE; a chart with the price pane only.
- Steps: add RSI 14; read the pane, the gutter, the legend row and the announcement; move the crosshair; press the splitter's
  keys.
- Expected: a new sub-pane with its own scale appears below the price pane; the gutter shows the guide levels "30" and "70"; the
  crosshair and the time axis are shared, and the keyboard data cursor reads the RSI value at the focused bar alongside OHLCV
  (E11's cursor); the row reads the "RSI 14 62.4" form with the mirror row the same; the announcement is "RSI 14 added to a new
  sub-pane" (deck `d04.10.r01`, PROPOSED: the words are **blocked on D06 Q-4**, the event asserted); the pane's label row is a
  `Tab` stop and the splitter moves by `↑/↓` 2 %, `Shift` 10 %, `Home` equal, `End` max (E11-D02 D14 via D06 §5.1). The default
  ratio and the floor are D04 G-13's proposals (0.2 from the price pane; 48 px, R315 BQ-7), asserted as such and **blocked on
  E13-T01 (#425)** confirming them.
- Oracle: the WS point equals `GV[tape_1m, rsi, i]` (`rsi` is `compute: server`) > the pane and gutter (presentation). 2nd:
  `indicator_subpanes_active`†.

**E13-Q01-C29 Confirmed divergences are a glyph plus a label, and the metric is estimated** (`e2e`; OWNER · populated; mirrors
US-IND-003/2, S03.2; S03 scope (`*_divergence`, `confidence="estimated"`); deck `d03.13.r02`, `d02.12.r04`)

- Pre: FX-TAPE with RSI 14; the divergence detection control of S03's scope (no served parameter at the base: the control is
  **blocked on E13-S03 (#460)**).
- Steps (once it lands): enable detection; read the markers, the tooltip, the mirror and the library tag.
- Expected: each confirmed divergence is a marker reading "Div ▲" or "Div ▼" with "Bullish divergence" / "Bearish divergence" in
  the tooltip and the mirror; no unconfirmed pivot is marked (S03 test plan); the divergence metric carries "(estimated)" in
  SCR-034 and `estimated: true` in its descriptor. The never-colour-alone leg is C65's.
- Oracle: the descriptor's `estimated` > the DOM (presentation). 2nd: none.

**E13-Q01-C30 Removing the last indicator in a sub-pane collapses it and redistributes the height [R]** (`e2e`; OWNER ·
populated; mirrors US-IND-003/3, S03.3; D03:256–263 via D06 §10.5; deck `d02.12.r31`, `r36`)

- Pre: RSI 14 and ATR 14 in two sub-panes; a recorded pane-height set.
- Steps: remove ATR 14 from the tree; read the panes; Undo; remove it again and let the toast expire; press "Collapse" then
  "Expand" on the RSI pane row's menu.
- Expected: the ATR sub-pane collapses; the remaining panes take the freed height in proportion and the price pane never
  shrinks below its own minimum (D03:261; the value is D04 G-13); Undo restores the pane; the pane row's menu offers "Collapse"
  and "Expand"; under reduced motion the change is instant (D04 M4 / M5 by cite). Tree operations never force a full chart
  rebuild (`14` SCR-036 Performance via D06 §8.1: the other rows keep their values with no "computing…").
- Oracle: the pane geometry read from the DOM-mirror and the stats (presentation) > the toast. 2nd: `indicator.removed`†; a log
  on pane collapse (S03 Observability; no emitter at the base, a † row).

**E13-Q01-C31 Sub-pane heights persist per layout; blocked on D06-G-3** (`integration`; OWNER · populated; mirrors S03.4,
US-IND-003 NFR; D06-G-3; `22` `LayoutPaneInput`)

- Pre: **no field persists an indicator sub-pane's height at the base** (D06-G-3: `LayoutPaneInput` carries slot, kind, symbol,
  interval, template, preset ids, `pane_config` and scale mode; `PaneConfig.settings` is the nearest flat carrier): the case is
  **blocked on E15 with E13-T03 (#427)**, consumer E13-S03 (#460).
- Steps (once a field exists): resize the RSI sub-pane; save the layout; reload; read the height.
- Expected: the sub-pane returns at the same height for that layout; another layout is unaffected.
- Oracle: the layout read-back > the pane geometry. 2nd: none.

**E13-Q01-C32 MACD emits three outputs into one sub-pane under one legend row** (`e2e`; OWNER · populated; mirrors S03.5;
`catalogue.py` :513–517; `22` `IndicatorOutput`; D02 D15 via D06 §10.5)

- Pre: FX-TAPE.
- Steps: add MACD at its defaults; read the pane, the legend row and its accessible name; open the row's settings.
- Expected: one sub-pane with a zero line in the gutter ("0", `d03.13.r08`); one row with the three values in kernel order and
  three mini swatches in one hue and three shapes; the accessible name labels each by `IndicatorOutput.name` ("MACD line",
  "Signal line", "Histogram": `catalogue.py` :515) in the "MACD 12 26 9: MACD line 12.4, Signal line 9.8, Histogram 2.6" form;
  one eye for the row. The per-output Show toggle is a Style-tab control with no field (D02 CG-7, D03 G-9; the tab's token
  controls absent until E05-T01, D06 C-b): **blocked on E13-T02 (#426)**. `macd` is `client_worker`: its numerics are E13-Q05's.
- Oracle: the descriptor's `outputs` order > the DOM (presentation). 2nd: none.

**E13-Q01-C33 Four sub-panes degrade gracefully and the price pane keeps its floor; the seventh is refused [F]** (`e2e`, `perf`;
OWNER · populated and client cap; mirrors S03.6, `TM` AC-14; D04 G-13 via D06 §15.2; D06 §8.1; deck `indicator.cap_instances`)

- Pre: FX-TAPE; a 1280 × 800 viewport (the minimum, D06 §10.4).
- Steps: add RSI, MACD, ATR and ADX, each to a new sub-pane; read the price pane's height; add a fifth and a sixth; try a
  seventh.
- Expected: with four sub-panes the price pane retains at least the design floor — D04 G-13's 48 px proposal (R315 BQ-7),
  **blocked on E13-T01 (#425)** for the confirmed value — and the frame budget holds (≥ 55 fps: C07's observation); the
  seventh add is `aria-disabled` with "This chart has the maximum of 6 sub-panes. Remove a sub-pane indicator to add another."
  and sends nothing (C09); indicator pane redraws coalesce under load (C12).
- Oracle: the pane geometry > the control state (presentation) > the stats reading (blocked, C07). 2nd:
  `indicator_subpanes_active`†.

### 3.4 US-IND-004 Volatility and band indicators (Must/Should)

**E13-Q01-C34 ATR(14) is one value everywhere: legend, topic, rule vocabulary and the sizer's kernel [R]** (`integration`,
`contract`, `security`; OWNER · populated; mirrors US-IND-004/1, S04.1, the ticket's cross-cutting item 1, `TM` AC-10, AC-23,
AC-24, IR-12; `catalogue.py` :502–504; `rules/vocabulary/metrics.py` :138–150; `accounts/sizer.py` :47–50; deck `d02.12.r27`)

- Pre: FX-TAPE; ATR 14 on the chart (server); the rule vocabulary; the E28 sizing path as E28-X03 executes it.
- Steps: at bar i read the legend value, the WS point, `GET /rules/vocabulary`'s `atr` row and, through the sizing path, the ATR
  the kernel serves; open the Alerts tab.
- Expected: legend = WS point = `GV[tape_1m, atr, i]`; the vocabulary binds `atr` to the `atr` kernel's `atr` output
  (`vocabulary/metrics.py` :142), with the unit, params, warm-up (14 at the default, `24`:1166) and `nullable_when` from the
  catalogue, never a list of its own; the sizing path reads the kernel's ATR only — `AtrSource` is `"kernel"` and a worker,
  client, preset or cached value falls back (`sizer.py` :47–50); a client-supplied ATR field is refused with `422` (`extra=forbid`,
  AC-10); the Alerts tab reads "Metric key" with the instance key, "Current value" in the "64,011.0 · as of 13:42:05" form and
  the note "Stop sizing uses the account profile's ATR period and multiple, not this instance." The missing / NaN / stale /
  parity-flagged legs (AC-23: `AtrUnavailable` `missing`, `parity_flagged`, `stale`, `warmup`, `nan`, `sizer.py` :49–50) and
  the preset-field leg (AC-24) are E28-X03's (#976) to execute, and E13-X02 (#466) verifies the controls: this plan asserts only the black-box answer (no `source` other than
  the kernel's ever sizes a stop; the refusal status) and describes no way to provoke it. The `resolve()` read of E13-S08's registry surface is **blocked on E13-S08 (#465)**.
- Oracle: `GV` > the four reads compared bit for bit > the Alerts tab (presentation). 2nd: `indicator_cache_hits_total` rises as
  each consumer joins the one instance; `indicator_parity_mismatch_total{indicator="atr"}`† stays 0 (its stand-in: the parity
  pack's result, E13-Q05); `indicator_atr_unavailable_total{reason}`†.

**E13-Q01-C35 Bollinger(20, 2) renders three bands under one row; the channel and its contrast are referenced** (`e2e`; OWNER ·
populated; mirrors US-IND-004/2, S04.2; `catalogue.py` :419 (`_BANDS`); D03 §4.3 via D06 §10.5; D06 §10.2)

- Pre: FX-TAPE.
- Steps: add Bollinger at its defaults; read the row, the series and the Style tab.
- Expected: three series ("Upper band", "Middle line", "Lower band": `catalogue.py` :419) under one row with three values; the
  middle line is told from the MA family by its dash tier and the band edges share one fill opacity (D03 ladder via D06 §10.5);
  the shaded channel's toggle ("Fill to lower band") is a Style-tab control with no field (D02 CG-7) and its token
  `opacity.indicator.fill` is "published by D04 §2, not shipped" (D06 §10.2): **blocked on E13-T02 (#426) and E05-T01**. The
  candle-contrast measurement against the WCAG non-text threshold is S04's contrast test and E13-Q04's audit (section 8), not
  this plan's. `bollinger` is `client_worker`: numerics are E13-Q05's.
- Oracle: the DOM (presentation). 2nd: none.

**E13-Q01-C36 A period of 0 is refused inline, in the preset route and on the topic, and nothing recomputes [F]** (`e2e`,
`contract`; OWNER · populated; mirrors US-IND-004/3, S04.3, T03.3; D02 D11 :183; `22` `IndicatorPresetInput.params`; `23` §6.1 "Refusals";
deck `d02.12.r19`, `indicator.style_pending`)

- Pre: ATR 14 on the chart.
- Steps: in SCR-035 type 0, then 5001, then 2.5 into Period; press `Tab`, then Apply; `POST` a preset with `n: 0`; send a `sub`
  with `n: 0`.
- Expected: the field shows "Period must be between 1 and 5000." inline, keeps the typed value with `aria-invalid`, and the
  committed value stays in the model (the previous value is retained); Apply is at `opacity.disabled` with "Fix the highlighted
  field first."; no request, `ctl` or recomputation is issued; the preset route answers `422` with `minimum` on `params.n` naming
  the bound, never the value; the topic answers `sub_ok` `invalid_options` with `field: "instances"`, the message naming the
  entry's position, the param and its bound (`23` §6.1 "Refusals") — the UI never sends it, so it renders nothing (D06 §8.4: a client bug).
- Oracle: the request and frame logs (empty) > the two refusals > the inline text. 2nd: `indicator_recompute_total` unchanged.

**E13-Q01-C37 ATR and ADX use Wilder smoothing: the vectors match and the DI lines are labelled [R]** (`integration`, `e2e`;
OWNER · populated; mirrors S04.4, T02.1; `GV`; `catalogue.py` :505–509; deck `d03.13.r07`)

- Pre: FX-TAPE, FX-GAP (the true-range-across-gap case) and FX-SYN.
- Steps: subscribe `atr` and `adx` at their defaults on each set; read the points; read the chart's end labels and the mirror
  row.
- Expected: every point equals `GV[<set>, atr | adx, i]` within tolerance; `adx` serves three outputs (`adx`, `plus_di`,
  `minus_di`: `catalogue.py` :507) with the end labels "+DI" and "−DI" and the mirror row in the "ADX 24.1, +DI 18.2, −DI 12.9"
  form. The EMA-smoothed discriminating fixture is S04's white-box test, cited.
- Oracle: `GV` > the frames > the labels (presentation). 2nd: `indicator_compute_seconds{indicator="atr"|"adx",
where="server"}` has observations.

**E13-Q01-C38 ADX with fewer than its warm-up bars emits nothing and says how many are missing [F]** (`contract`, `e2e`; OWNER ·
warming up; mirrors S04.5; `24`:1166 (`adx` 28); `23` §6.1 "Snapshot and deltas"; deck `d02.12.r40`)

- Pre: 20 closed bars loaded.
- Steps: subscribe `adx` at n = 14; add it on the chart; read the snapshot, the row and the Alerts tab.
- Expected: `warmup_bars` is 28 at the default (`24`:1166: 2n); every point is `null`, never 0; the row reads the "34 more bars
  needed" form with 8; no zero is drawn; the Alerts tab reads "Unavailable: warm-up" with the `nullable_when` sentence.
- Oracle: the snapshot (`null`) > the row text. 2nd: none per tick.

### 3.5 US-IND-005 Trend tools (Must/Should)

**E13-Q01-C39 Supertrend flips carry a marker, a label and the legend's direction word** (`e2e`; OWNER · populated; mirrors
US-IND-005/1, S05.1; D03 §4.4 via D06 §10.5; deck `d03.13.r01`)

- Pre: FX-TAPE.
- Steps: add Supertrend at its defaults; read the markers, their DOM labels and the legend row.
- Expected: each direction flip is a CMP-195 marker labelled "Flip up" or "Flip down" in the DOM; the legend's direction reads
  "▲ up" or "▼ down" (a word beside the glyph: ▲ and ▼ are reserved for a direction with a word); the current direction is in
  the row. `supertrend` is `client_worker`: numerics are E13-Q05's.
- Oracle: the DOM (presentation). 2nd: none.

**E13-Q01-C40 Confirmed swings are named metrics with the kernel's values [R]** (`integration`, `contract`; OWNER · populated;
mirrors US-IND-005/2, S05.2; `catalogue.py` :553–565; `rules/vocabulary/metrics.py` :146–147; `24`:1156, :1166; deck
`d03.13.r03`)

- Pre: FX-TAPE and FX-SYN; Zig Zag at its defaults (`depth` 5, `deviation_pct` 0: `catalogue.py` :557–559).
- Steps: subscribe `zigzag`; read the points; read `GET /rules/vocabulary` for `swing_high` and `swing_low`; read the pivot
  labels.
- Expected: the two outputs `swing_high` and `swing_low` equal `GV[<set>, zigzag, i]`; the vocabulary binds `swing_high` and
  `swing_low` to the `zigzag` kernel's outputs with "Most recent confirmed pivot high" / "… low" (`vocabulary/metrics.py`
  :146–147) and the catalogue's params (`depth` 5, `deviation_pct` 0, `24`:1166); each pivot's label is its swing value in the
  "63,980" form. The structure-based trailing-stop consumer is E32-S04's (`TM` IR-11), referenced.
- Oracle: `GV` > the frames > the vocabulary read. 2nd: `indicator_compute_seconds{indicator="zigzag", where="server"}`.

**E13-Q01-C41 A provisional leg is dashed, labelled and never published, so no consumer or picker can read it [R] [F]**
(`integration`, `security`, `e2e`; OWNER · populated; mirrors US-IND-005/3, S05.3, S05.4, the ticket's cross-cutting item 2,
`TM` AC-11, IR-11; `23` §6.1 "Snapshot and deltas"; D02 D27 provisional; D06-G-2; deck `d02.12.r40`, `d03.13.r03`)

- Pre: FX-TAPE replayed to a bar where the last leg is unconfirmed.
- Steps: read the WS points; read the legend row and the chart; read `swing_high` through the vocabulary; replay until the leg
  confirms or vanishes; open the alert and rule editors' metric pickers.
- Expected: the topic serves closed, confirmed pivots only — no point carries the unconfirmed leg's value (`24` §7.4 never
  publishes it; `23` §6.1 "Snapshot and deltas": only closed bars are served); the chart draws the last leg dashed with the word "provisional" in the
  row's value column; the vocabulary's `swing_high` is the last confirmed pivot; when the leg later vanishes no value ever
  changed downstream. The controls' executors are E13-X02 (#466) and E28-X03 (#976); this leg asserts only what the topic and the vocabulary answer (no unconfirmed value is
  served or readable) and describes no way to provoke it. The picker leg ("never selectable in an alert / rule picker") is E40's, E36's and E37's surface
  (D06-G-2): **blocked on E13-S08 (#465) and those epics**; the `resolve()` leg of AC-11 likewise. The worker channel's
  `provisional=true` flag is E13-T01's (S05 scope), white-box.
- Oracle: the WS frames scanned for the provisional value (none) > the vocabulary read > the row text (presentation). 2nd:
  `indicator_provisional_published_total`† stays 0 forever (`TM`:361).

**E13-Q01-C42 The Ichimoku cloud projects 26 bars ahead without touching the bar model** (`e2e`; OWNER · populated; mirrors
S05.5; D03 Q-1 via D06 Q-8)

- Pre: FX-TAPE.
- Steps: add Ichimoku at its defaults; scroll to the right edge; move the crosshair over the projected region; read the time
  axis and the price scale before and after.
- Expected: the cloud renders beyond the last bar; the bar model does not gain bars and the price scale does not shift; the
  crosshair over the projected region reads the cloud values with no OHLCV; the two cloud boundaries are told apart without
  colour (D03 Q-1's default: one hue, weight and dash). The heaviest v1 indicator's cost is E13-Q03's (S05 Performance).
- Oracle: the time axis' bar count (unchanged) > the cursor read-out (presentation). 2nd: none.

**E13-Q01-C43 A late amendment recomputes from that bar forward and republishes; blocked on a late-trade replay** (`integration`,
`contract`; OWNER · populated; mirrors S05.6, T02.5; `23` §6.1 "Amended bars and generations"; `metrics.py` :54–59)

- Pre: FX-TAPE with Zig Zag and EMA 21 subscribed; a replay that re-closes a bar with a late trade — **no such fixture or feed
  exists at the base** (FX-G3): the case is **blocked on the bar-replay feed's owner**.
- Steps (once it exists): replay to a confirmed pivot; inject the late trade; read the `d`.
- Expected: a `d` re-publishes each point from the amended bar forward whose value changed, with `amended: true`; the client
  replaces stored points by key `(key, generation, index)`; the legs the pivot formed are recomputed and any consumer is served
  the corrected value; a generation change is a `snap` with `meta.reason: "generation_swap"`, never a `d`.
- Oracle: the frames > the legend. 2nd: `indicator_recompute_total{reason="amended"}` rises by one;
  `indicator_zigzag_reprovisionalised_total`†.

### 3.6 US-IND-006 Volume-based indicators (Must/Should)

**E13-Q01-C44 The volume histogram encodes up and down by pattern and word, with an optional volume MA [R]** (`e2e`,
`integration`; OWNER · populated; mirrors US-IND-006/1, S06.1; `catalogue.py` :583–590; D03 §4.2, §5 via D06 §10.5; deck
`d03.13.r04`)

- Pre: FX-TAPE.
- Steps: add Volume (server, pane `both`) to a sub-pane; read the bars, the tooltip and the mirror; add Volume MA (n 20); read
  the row.
- Expected: each bar's value equals `GV[tape_1m, volume, i]`; an up bar and a down bar are told apart by the candle tokens, the
  notch glyph and the words "up" / "down" after the value in the tooltip and the mirror, never a hatch and never colour alone;
  the volume MA is a separate optional instance (`volume_ma`, `client_worker`) drawn as a line over the histogram; the
  histogram is one instanced quad pass (S06 Performance: E13-Q03 measures draw calls).
- Oracle: `GV` > the tooltip and mirror words (presentation). 2nd: `indicator_compute_seconds{indicator="volume",
where="server"}`.

**E13-Q01-C45 Classic CVD equals the dedicated CVD pane for the same anchor; blocked on E23** (`integration`; OWNER · populated;
mirrors US-IND-006/2, S06.2; `catalogue.py` :610–613; `GV` `tape_1m`)

- Pre: FX-TAPE (180 tape-built bars with aggressor delta, the set E23 also consumes); CVD at `anchor: session` and at
  `utc_day` (the two served anchors). **The dedicated CVD pane is E23's and not on `main`:** the identity leg is **blocked on
  E23**; the stand-in is the topic.
- Steps: subscribe `cvd` at each anchor; read the points; compare to the vector; once E23 lands, read the pane's value at bar i.
- Expected: every point equals `GV[tape_1m, cvd, i]` for the anchor; the pane's value at bar i equals the same point (the one
  kernel, ADR-0034); the rule vocabulary's `cvd` is bound to the same output (`vocabulary/metrics.py` :140).
- Oracle: `GV` > the frames > the pane. 2nd: `indicator_cache_hits_total` rises when the pane joins the running instance.

**E13-Q01-C46 Partial history renders only where prints exist, with a marker and a dated sentence; blocked on E13-Q05 [F]**
(`e2e`, `integration`; OWNER, MANAGER · populated; mirrors US-IND-006/3, S06.3, the ticket's cross-cutting item 3; D02 D27
before-history; deck `d02.12.r41`, `r42`)

- Pre: FX-PARTIAL, a symbol-day whose recording starts mid-day — **no such fixture exists at the base**; E13-Q05 (#458) owns it
  (its Scope): the case is **blocked on E13-Q05**, nothing is filed.
- Steps (once it exists): add CVD over a range that predates the first recorded print; read the series, the row's glyph and
  detail, the announcement, and the same row as MANAGER.
- Expected: the series draws only where prints exist; the row carries the partial-history glyph and its detail reads the
  `d02.12.r41` form "History starts 2026-09-01 00:00 UTC — recording began then. CVD starts there." with the fixture's
  timestamp (the stem's wording is under review in E16-D01 §4, which owns the final text); the Owner sees "Open recorder", the
  Manager the sentence only; "CVD history starts 1 September"-form is announced once; no point before the first print is served
  or drawn (`23` §6.1 "Snapshot and deltas"); the short-circuit queries no storage for data known not to exist (S06 Security: an integration leg).
- Oracle: the frames (no point before the first print) > the row (presentation). 2nd: `indicator_cvd_partial_history_total{symbol}`†.

**E13-Q01-C47 A symbol with no recorded prints gets a statement of need, never a flat zero [F]** (`e2e`, `contract`; OWNER ·
populated; mirrors S06.4, US-MKT-006 dependency; `24`:1166; `vocabulary/metrics.py` :130–137; `22` `getRuleVocabulary`; deck
`d02.12.r27`)

- Pre: a symbol off the recorded-symbol list.
- Steps: read `getRuleVocabulary` for that symbol; add CVD, Volume and VWAP on its chart; read the rows and the Alerts tab.
- Expected: the vocabulary reports `cvd`, `volume` (`bar_volume`), `vwap` and `vwap_band_sigma` unavailable with the recorder
  action (`24`:1166: they keep `requires_recording`); no point with value 0 is served or drawn; the Alerts tab's availability
  row is the fail-closed "Unavailable: <reason>" form (D02 D18 :205–207) — the recording-on variant reads "Requires recorded
  history for BTCUSDT — recording is on"; the not-recorded sentence has no deck row and is **blocked on D06 Q-13**'s owner (the
  pattern is asserted).
- Oracle: the vocabulary read > the frames (no zero) > the row (presentation). 2nd: `indicator_cap_rejected_total` unchanged (a
  refusal of need, not of a cap).

**E13-Q01-C48 One delta computation serves every consumer** (`integration`; OWNER · populated; mirrors S06.5, T02.2; `23` §6.1 "Identity";
`metrics.py` :45–48)

- Pre: FX-TAPE; CVD subscribed on two connections and read by the rule vocabulary.
- Steps: read the cache counters before; open the second subscription; add a rule reading `cvd` (once E13-S08's resolver lands;
  until then the second subscription alone); read the counters after one bar close.
- Expected: the server computes each `(symbol, key)` once per bar close however many subscriptions and consumers read it
  (`23` §6.1 "Identity"); the second reader is a cache hit, not a miss. The footprint and Deep-Stats consumers are E18's and E19's; the
  call-count assertion is S06's white-box test, cited.
- Oracle: `indicator_cache_hits_total` +1 and `indicator_cache_misses_total` unchanged on the join > the two frame sets equal.
  2nd: `indicator_compute_seconds{indicator="cvd"}` gains one observation per bar close, not two.

**E13-Q01-C49 MFI over a zero-volume synthetic bar follows the descriptor's `nullable_when`, never a division error**
(`e2e`; OWNER · populated; mirrors S06.6; `catalogue.py` :603–609; FX-SYN)

- Pre: FX-SYN (densified zero-volume bars, seed 20261019).
- Steps: add MFI at its defaults; read the rows over the zero-volume bars and the descriptor's `nullable_when`.
- Expected: the descriptor says "None until n+1 bars exist (n changes of the typical price), and while the money flow of the
  last n changes is 0." (`catalogue.py` :606–607); the ticket says the previous value is carried forward: the two differ, the
  case follows the descriptor (section 0's rule) and the difference is OQ-10. No NaN, no error row, no zero drawn where the rule
  says `null`. `mfi` is `client_worker`: numerics are E13-Q05's.
- Oracle: the descriptor text > the row (presentation). 2nd: none.

### 3.7 US-IND-007 Session and anchored VWAP (Must/Should)

**E13-Q01-C50 Session VWAP resets at the anchor and the reset is marked [R]** (`integration`, `e2e`; OWNER · populated;
mirrors US-IND-007/1, S07.1; `catalogue.py` :464–478; `GV` `synthetic_day`; D03:232 via D06 §10.5; D06 Q-13)

- Pre: FX-SYN (1 440 one-minute slots from 2026-10-05T12:00Z with the manifest's session anchor) and FX-TAPE.
- Steps: subscribe `vwap` at `anchor: session` (the one served anchor, D06-G-1); replay across the session boundary; read the
  points and the chart at the boundary.
- Expected: every point equals `GV[<set>, vwap, i]`, the running value restarting at the boundary the vector encodes; the
  reset is the session boundary line of E11-D02 D8 (1 px dashed, a reserved geometry, never an identity); the reset is never
  inferred from a discontinuity alone (S07 scope). The marker's label words are **blocked on D06 Q-13**; the reset log (S07
  Observability) has no emitter at the base (a † row). Time is event time inside the replayed bars, never wall time (section 4).
- Oracle: `GV` > the frames > the boundary line (presentation). 2nd: the reset log†.

**E13-Q01-C51 The σ envelopes are outputs with labelled values; their toggles are referenced** (`e2e`, `contract`; OWNER ·
populated; mirrors US-IND-007/2, S07.2; `catalogue.py` :464–478; `21` §10.5; `vocabulary/metrics.py` :150; deck `d03.13.r05`)

- Pre: FX-TAPE; VWAP at its defaults; the built-in `vwap(session, ±1σ, ±2σ)`.
- Steps: read the descriptor's `outputs`; read the chart's band labels and the legend; read the vocabulary's `vwap_band_sigma`;
  add the built-in.
- Expected: the envelopes are `vwap` outputs (`sigma`, `upper_1` / `lower_1` … `upper_3` / `lower_3`: `catalogue.py` :466–476;
  `21` §10.5: "the bands are `vwap` outputs, not params"), labelled "±1σ" · "±2σ" · "±3σ" with their values in the "±1σ 63,940.1 /
  64,040.3" form; `vwap_band_sigma` is bound to the `band_sigma` output ("Distance from VWAP in standard deviations"); the
  built-in applies with `params {"anchor": "session"}`. The per-band Show toggle is a Style-tab control with no field (D02
  CG-7): **blocked on E13-T02 (#426)**.
- Oracle: `GV[tape_1m, vwap, i]` for every output > the labels (presentation). 2nd: none.

**E13-Q01-C52 A funding anchor resets at each settlement; blocked on D06-G-1** (`integration`; OWNER · populated; mirrors
US-IND-007/3, S07.3; D06-G-1; `packages/fixtures/bybit/2026-10-05/rest/funding_history_BTCUSDT_8h.json`,
`funding_history_ETHUSDT_4h.json`)

- Pre: **the served `vwap` anchor is `session` only** (`catalogue.py` :477; D06-G-1: week, month, funding and `custom_ts` have
  no parameter shape): the case is **blocked on E13-T02 (#426) with E13-S07 (#464)**. The corpus holds two funding schedules
  (8 h and 4 h) for the day it lands.
- Steps (once served): set the anchor to funding on BTCUSDT and on ETHUSDT; replay across a settlement.
- Expected: the reset follows each symbol's actual settlement schedule from the instrument metadata, never a hard-coded 8 h; a
  `custom_ts` outside the SR-E13-04 window or the listing-to-now range is `422` (`TM` SR-E13-05, AC-13), with no backfill job
  started.
- Oracle: the frames at the settlements > the refusal. 2nd: `indicator_cap_rejected_total{cap="window"}` for AC-13.

**E13-Q01-C53 One kernel, one answer with the anchored-VWAP drawing; blocked on E14** (`integration`; OWNER · populated;
mirrors S07.4; S07 scope (the kernel shared with E14))

- Pre: the E14 anchored-VWAP drawing: **not on `main`**; the case is **blocked on E14** and runs stubbed in S07's own tests
  until then.
- Steps (once it lands): anchor a drawing and an indicator at the same timestamp; read both at every bar.
- Expected: identical values at every bar.
- Oracle: the two series compared bit for bit > `GV`. 2nd: `indicator_cache_hits_total` +1 (one instance serves both).

**E13-Q01-C54 No prints since the anchor: no value, no line at the last price, and the legend says why [F]** (`contract`, `e2e`;
OWNER · populated; mirrors S07.5; `23` §6.1 "Snapshot and deltas"; `22` `IndicatorDescriptor.nullable_when`; D06 Q-13)

- Pre: a session whose first bars hold no prints (FX-SYN's gap runs), or an anchor in the future once `custom_ts` is served.
- Steps: subscribe `vwap`; read the points before the first print; read the row.
- Expected: every point before the first print after the anchor is `null`, never 0 (`23` §6.1 "Snapshot and deltas") and no line is drawn at the last
  price; the row's value is the legend's dash (D06 Q-13's default); the sentence stating why has no deck row and is **blocked on
  Q-13**: the `nullable_when` text of the descriptor is what the Alerts tab shows meanwhile.
- Oracle: the frames (`null`) > the chart (no line) > the row (presentation). 2nd: none.

### 3.8 US-IND-008 Indicator alert and rule exposure (Must)

**E13-Q01-C55 An enabled indicator's metric is selectable with its current value; the picker is referenced** (`e2e`, `contract`;
OWNER · populated; mirrors US-IND-008/1, S08.1; `22` `getRuleVocabulary`; D02 D18 :205–207; D06-G-2; deck `d02.12.r27`)

- Pre: FX-TAPE on a 5m chart; EMA 21 on it.
- Steps: open the Alerts tab; read "Metric key" and "Current value"; press "Create alert from this indicator"; read
  `getRuleVocabulary`.
- Expected: the metric key is in the `ema(21, 5m)` form (S08 scope; the deck's `d02.12.r26` quotes it), derived from the
  instance key, never the display name; the current value reads the "64,011.0 · as of 13:42:05" form from the last WS point;
  "Create alert from this indicator" opens SCR-091 with the metric prefilled (E40 owns it); the vocabulary lists `ema` with the
  catalogue's params and `params_schema` (`vocabulary/metrics.py` :130–137). The editor pickers' rows, announcement and
  current-value display are E40's, E36's and E37's surfaces (D06-G-2): **blocked on E13-S08 (#465) and those epics**.
- Oracle: the vocabulary read > the Alerts tab (presentation). 2nd: none (a read).

**E13-Q01-C56 Two EMA(21) instances with different sources carry distinct labels and keys; blocked on `source`** (`e2e`;
OWNER · populated; mirrors US-IND-008/2, S08.2; C25; deck `d02.12.r04`)

- Pre: as C25 (**blocked on E13-S02 (#424)**: no `source` parameter at the base). With identical params the ordinal form
  "EMA 21 (2)" applies today (C05).
- Steps (once served): add EMA 21 on `close` and on `hl2`; read the labels and the keys in the Alerts tab and the vocabulary.
- Expected: "EMA 21" and "EMA 21 · hl2", each with its own metric key; a user-chosen display name never becomes the key (`TM`
  IR-15).
- Oracle: the keys (`spec_hash` distinct) > the labels. 2nd: none.

**E13-Q01-C57 Removing a referenced indicator is blocked with the list, and Disarm acts from the dialog [R] [F]** (`e2e`,
`contract`, `security`; OWNER, MANAGER · referenced; mirrors US-IND-008/3, S08.3, `TM` AC-16, IR-23; D02 D17, D24 :234–245;
D05 FM-05, FM-06; D06 §8.3 rows (5), (7), §3.2, D02 CG-2; deck `indicator.references_open`, `d02.12.r26`, `r38`, `r39`)

- Pre: FX-RULE: EMA 21 referenced by an armed rule on a LIVE account and by one on a DEMO account, and by an enabled alert, one
  of them another user's. **The referencing-objects operation does not exist at the base** (D02 CG-2; E13-S08 #465): the
  server-answer half is **blocked on E13-S08**; the dialog's anatomy is asserted once it lands.
- Steps: press `Del` on the item; read the dialog, its initial focus and every row; press Disarm on the own rule; read the
  announcement and the audited `reason`; press Done; re-open and press "Remove EMA 21" once the list is clear; as MANAGER
  repeat; in SCR-035 change Period and press Apply.
- Expected: an `alertdialog` titled "Can't remove EMA 21 yet" with the body in the "2 armed rules and 1 alert use ema(21, 5m).
  Disarm or edit them first." form; initial focus on Done, nothing acting on the key-up that opened it; each own rule row in
  the "ATR breakout · Armed · LIVE ▲ · BTCUSDT · Main" form with the environment badge "LIVE" or "DEMO" as word + icon on
  every row (frozen (7)), with Disarm and Edit; Disarm sends `setRuleMode` with the `reason` "disarmed from the indicator
  manager: ema(21, 5m) is being removed", the row reads "Disabled ✓" and "Rule 'ATR breakout' disarmed" is announced; the alert
  row's Disable announces "Alert 'ATR spike' disabled"; other users' objects are one count-only row "2 other objects (not
  yours)" with no names (AC-16); "Remove EMA 21" is disabled with "Resolve every reference first" until the list is clear and
  there is no "remove anyway"; a MANAGER with no own object reads "Only other users' objects use ema(21, 5m). An Owner can disarm
  or edit them; nothing you own blocks this." and the reason "Resolve every reference first — an Owner must do this."; Done
  returns focus to the item. The re-tune variant is titled "Can't change EMA 21 yet" with "Apply as new instance" (counting
  against the 20) and never an "apply anyway"; the quick-edit's blur reverts with "Not applied — this indicator is used by 2
  armed rules". No reason names another user's rule.
- Oracle: the server's answer (once it exists) > the `setRuleMode` request and its audited `reason` > the dialog (presentation).
  2nd: the `setRuleMode` audit record (E35's); `indicator_removal_blocked_total`†; `indicator.remove_blocked`† (none is emitted
  for a blocked removal: D02:323).

**E13-Q01-C58 Metric identity survives a restart and a rename [R]** (`integration`, `e2e`; OWNER · populated; mirrors S08.4,
US-IND-008 NFR; `23` §6.1 "Identity"; `GV` `spec_hash_vectors.json`; D05 FM-11; deck `d02.12.r44`)

- Pre: FX-TAPE; EMA 21 on a 5m chart; its key recorded.
- Steps: in SCR-036 press `F2`, rename the item, `Enter`; read the Alerts tab's key; restart the API and reload the app; read the
  key again; compare to the spec-hash vector for the same spec.
- Expected: "Renamed to Fast EMA"-form is announced and the label changes; the metric key does not (it is the `spec_hash` of the
  indicator, every param, the bar series' `spec_hash` and the bar source, `23` §6.1 "Identity"; never the display name); after the restart
  the same instance resolves to the same key, equal to `spec_hash_vectors.json`'s entry for that spec
  (`indicator_spec_version` 1). The rule-stays-valid half is **blocked on E13-S08 (#465)**.
- Oracle: the spec-hash vector > the WS `effective.key` before and after > the Alerts tab. 2nd: none.

**E13-Q01-C59 An unresolvable reference fails at save time, naming the key; blocked on E13-S08 [F]** (`contract`; OWNER ·
populated; mirrors S08.5, US-IND-008 NFR; S08 scope (save-time resolution))

- Pre: a rule or alert referencing a key whose instance was removed. **Blocked on E13-S08 (#465)** and the editors' owners (E35,
  E40): no save-time resolution exists at the base.
- Steps (once it lands): save the rule; try to arm it.
- Expected: the save is `422` naming the unresolvable key; the rule is never armed in an unresolvable state; the rejection is
  rendered as the editor's sentence, never the server's `detail`.
- Oracle: the status and the named key > the rule's state. 2nd: `metric_resolution_failures_total{key}`†; the save-time log with
  the rule id (S08 Observability).

**E13-Q01-C60 The guard cannot be bypassed from the client; blocked on E13-S08 [F]** (`security`, `integration`; OWNER ·
referenced; mirrors S08.6, `TM` AC-17, IR-16)

- Pre: as C57. **No operation deletes an indicator instance at the base** (instances are client state and WS leases; the guard
  is E13-S08's): **blocked on E13-S08 (#465)**; OQ-11 carries both readings of what the direct call is.
- Steps (once it exists): issue the delete directly against the referenced instance; race it with arming a rule.
- Expected: the server rejects with the referencing objects listed, independently of any client check; the race ends with
  either the delete refused or the arm refused, never both committed (fail-closed), and the rule's state unchanged.
- Oracle: the two statuses and the rule's state. 2nd: the guard log (S08); `indicator_removal_blocked_total`†.

### 3.9 Cross-cutting cases: roles, the problem codes, the WS caps, the renderer, the carriers and the telemetry

**E13-Q01-C61 The role grid holds for every read and write, and gated controls are T2 [R] [F]** (`security`, `contract`, `e2e`;
OWNER, MANAGER, VIEWER, view-as; mirrors `TM` AC-19, AC-01..AC-03; D06 §12, D05 T2-01..T2-07; section 2.1; `22` `x-rbac`;
`23` §6.3 `indicators` row)

- Pre: FX-USERS: a session per role and a view-as session; FX-EMPTY presets plus one preset per writer.
- Steps: as each role read `listIndicators`, `listIndicatorPresets` and subscribe the topic; send each preset write (create,
  replace, delete) as each role, once without the CSRF token and once unauthenticated; as VIEWER and view-as, tab to the star,
  Add to chart, Apply, Save as default, the tree's writes; press Enter and Space on each.
- Expected: every cell as section 2.1: the reads `200` and `sub_ok` for every role (`marketdata:read`, `workspaces:read`);
  VIEWER's writes `403` rule `required_permissions` by direct call (AC-19), a missing token `403` `csrf_token_invalid`,
  unauthenticated `401`; MANAGER's writes answer what the server gives its permission set (OQ-7), scoped to its own presets
  (C16); in the UI every VIEWER write is T2 before any request — `aria-disabled`, the full label kept, the lock glyph, the
  reason in the DOM at mount, one header notice per surface (`rbac.permission`, T2-05..T2-07) — and the view-as leg greys every
  write first (`rbac.view_as`, T2-01..T2-04); Enter or Space changes nothing and re-shows the reason once; a reason names a
  capability, never data (frozen (5): ≤ 60 characters, a full stop); presets and the audit are unchanged by any refusal.
- Oracle: statuses > `P(pre)` equals `P(post)` > the control states (presentation). 2nd: one `rbac.denied` per refused write
  (`actions.py` :344); `indicator_preset_denied_total` unchanged (its reasons are the target's, not the role's).

**E13-Q01-C62 Every declared problem code is mapped, never echoed [F]** (`contract`, `e2e`; OWNER · populated; mirrors D06 §8.4,
§8.3 row (6); `22` `updateIndicatorPreset` (the evaluation order); `23` §6.1 "Refusals" to "Live only"; deck `d02.12.r10`, `r12`, `r19`, `r25`,
`d02.07.errored`)

- Pre: the stack with a fault fixture for `503` on the store and on the audit write; a user at 500 presets; a hostile `title`,
  `detail`, `errors[].message` and WS `message` injected into every refusal.
- Steps: trip each row of the table through the UI path that reaches it and by direct call; read the status, the rule and the
  DOM.
- Expected, one leg per row of D06 §8.4:

| Code                                            | Reached by                                                              | Expected in the DOM                                                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `401` unauthenticated / session_idle_locked     | any route with an expired session                                       | the shell's session flow; no E13 string (Q-17)                                                           |
| `403` builtin_immutable                         | a write on a built-in (C15)                                             | the refusal pattern, no server text; words **blocked on Q-17**                                           |
| `403` required_permissions / csrf_token_invalid | VIEWER's direct call; a missing token (C61)                             | never reached from the UI (T2 first); by direct call, the generic refusal; words **blocked on Q-17**     |
| `404` not_found                                 | a stale, deleted or foreign `presetId` (C16, C17)                       | no server text; the star re-syncs from `listIndicatorPresets`; words **blocked on Q-17**                 |
| `409` name_taken                                | the second save of one name (C13)                                       | "A preset named 'EMA 34' exists." / "Replace" (`d02.12.r25`)                                             |
| `409` limit_reached                             | the 501st preset (C14)                                                  | "You have the maximum of 500 saved presets. Delete one to star another." (`d02.12.r12`)                  |
| `413` payload_too_large                         | a body over 16 KiB (C14)                                                | the refusal pattern; words **blocked on Q-17**                                                           |
| `422` validation_failed                         | a bound (C14, C36); `immutable_field`; `uuid_parsing`                   | the field bound → `d02.12.r19`'s sentence; the other rules are client bugs with no sentence (Q-17)       |
| `503` store_unavailable / audit_unavailable     | the fault fixture; `listIndicators` `503` (C06)                         | the presets' words **blocked on Q-17**; the catalogue's CMP-027 with Retry, words **blocked on Q-12**    |
| `sub_ok` invalid_options                        | a hostile `sub` by direct call (C36)                                    | never sent by the UI; nothing rendered; words **blocked on Q-17**                                        |
| `sub_ok` subscription_limit                     | the 9th / 33rd / 129th instance (C63)                                   | `d02.12.r10`'s three sentences by cap, with "Retry" for the symbol and process caps                      |
| `err` / `sub_ok` internal_error                 | the executor refusal (C11)                                              | "Compute failed: <reason>" with the closed map's sentence (`d02.07.errored`; words **blocked on Q-16**)  |
| `sub_ok` unknown_topic                          | a replay `sub` of `indicators.*`; the engine off (`23` §6.1 "As built") | never sent by the UI for a server instance (replay is out of scope until E26); words **blocked on Q-17** |

The evaluation order of `/indicator-presets*` holds when several apply (`22` `updateIndicatorPreset`: `401`; `403` permission,
CSRF; `413`; `422` path, query, body; `404`; `403` `builtin_immutable`; `422` `immutable_field`; `409`; the write; `503` wherever
storage or the audit record fails): a `PUT` on a built-in with a bad body answers `422` before `403`. No `title`, `detail`,
`errors[].message` or WS `message` reaches the DOM in any leg.

- Oracle: the status and rule per leg > the DOM scanned for the injected text (presentation). 2nd: no audit record on a `503`
  `audit_unavailable` write and nothing stored (write-ahead, C-2.9).

**E13-Q01-C63 The server caps and the topic's refusals are the server's words, never a client count [F]** (`contract`, `e2e`;
OWNER as A, a second user as B · server cap; mirrors `TM` AC-12, AC-20, IR-31, IR-41; `23` §6.1 "Options" to "As built"; `limits.py` :61–74; deck
`d02.12.r10`, `r11`)

- Pre: FX-TAPE on one symbol; users able to hold 33 instances on one symbol between them; a process near 128 held instances (a
  harness leg).
- Steps: as A add eight distinct server instances, then a ninth; as the group reach 32 on one symbol, then a 33rd; reach 128
  process-wide, then a 129th; send a `sub` naming a `client_worker` indicator, an unknown indicator, a param the descriptor
  lacks, a `compute` key, two entries with one key, `history` 1 001; join an instance another user already runs; send a replay
  `sub`; churn as C18 variant b.
- Expected: the ninth is `sub_ok` `subscription_limit` naming the cap `user`, rendered "You have the maximum of 8
  server-computed indicators. Remove one to add another." inline under the entry (CMP-027, polite); the 33rd names `symbol` →
  "Server-computed indicators are at capacity for this symbol." with Retry, never a spinner; the 129th names `process` →
  "Server-computed indicators are at capacity. Try again later." with Retry; joining a running instance counts against the user's
  cap only; each malformed `sub` is `invalid_options` with `field: "instances"` (or `history`) and the message names the entry's
  position, never a key the server does not know (`23` §6.1 "Refusals"); `compute` in the options is `invalid_options` (IR-41, AC-20); a
  replay `sub` is `unknown_topic`; the UI shows "Subscribing…" while in flight and never renders the WS `message`. `TM` AC-12's
  `429` and `409 indicator_symbol_cap` are not the contract's words: the plan follows `23` (`subscription_limit`; OQ-12).
- Oracle: the `sub_ok` codes and `effective` > `indicator_subscriptions{bucket="8"}` reads 1 for A > the strings
  (presentation). 2nd: `indicator_cap_rejected_total{cap="user"|"symbol"|"process"}` rises by one per refusal (`metrics.py`
  :64–70).

**E13-Q01-C64 A hostile `params_schema` renders the closed control subset only [F]** (`e2e`, `security`; OWNER · populated;
mirrors `TM` AC-22, IR-14, IR-37, SR-E13-09; D06 §8.3 row (1); D02 D10 :166–179; `catalogue.py` :583; deck `d02.12.r21`, `r22`)

- Pre: a test double serving `listIndicators` with one descriptor whose `params_schema` carries a `$ref`, a 10 000-character
  `title`, HTML in a `title` and an `enum` label, a `pattern`, a `description`, nesting depth 50, an unknown `type`, a
  `__proto__` key and a free `additionalProperties` field; and the real `volume` descriptor (no parameters).
- Steps: open SCR-035 for each; time the render; read the rows.
- Expected: only stepper, select, toggle and swatch render; the unknown type and the free field render the read-only row
  "Unsupported parameter type — this parameter can't be edited here." (CMP-036), never an input; `title`, `enum` labels and the
  row's raw `default` are text nodes (no markup interpreted); `$ref`, `pattern` and `description` are ignored; the depth-50 and
  10 000-character schema render in under 100 ms with no hang and no HTML injected; `__proto__` corrupts nothing (null-prototype
  parsing, IR-14); `volume` reads "This indicator has no parameters." on the Inputs tab.
- Oracle: the DOM (text nodes, no injected element) and the render timing (presentation). 2nd: none.

**E13-Q01-C65 Every state is carried in text, never colour alone** (`a11y`, `e2e`; OWNER · populated; mirrors US-IND-003/2,
US-IND-005/1, US-IND-005/3, US-IND-006/1, the stories' Accessibility notes; D02 D27; D06 §10.4; deck `d02.12.r40`, `r42`,
`r44`, `d03.13.r01`..`r04`)

- Pre: a chart holding a warming-up, a provisional, an errored, a hidden, a locked, a stale and a rule-referenced instance, a
  Supertrend flip, a divergence (once C29 lands) and the volume histogram.
- Steps: read each legend row's visible text and accessible name, the tree row, the markers' DOM labels and the tooltip words.
- Expected: warming up → the "34 more bars needed" form; provisional → "provisional"; errored → "error"; hidden → "hidden" in the
  accessible name and value "—"; locked → "EMA 21 locked" announced and the lock glyph; stale → "stale" in the name and "Stale
  7s"-form; referenced → "used by rules" in the name; flips → "Flip up" / "Flip down" and "▲ up" / "▼ down"; divergences → "Div
  ▲" / "Div ▼" with "Bullish divergence" / "Bearish divergence"; volume → "up" / "down" after the value; the LIVE / DEMO badge
  is word + icon (C57). Smoke only: the contrast pairs, the greyscale and CVD renders (D06 §10.4) and the announcement cadence
  are E13-Q04's (#457).
- Oracle: the accessible names and text nodes (presentation). 2nd: none.

**E13-Q01-C66 The telemetry a case names exists or its stand-in is recorded** (`contract`; OWNER; mirrors the ticket's
Observability; `metrics_catalogue.py` :2624–2652; `metrics.py` :38–72; section 10's Known gaps)

- Pre: the stack after C02, C13 and C63.
- Steps: read the metrics endpoint; for each metric a case names, record its presence or its † stand-in.
- Expected: present with the catalogue's labels: `indicator_compute_seconds{indicator,where}`, `indicator_cache_hits_total`,
  `indicator_cache_misses_total`, `indicator_recompute_total{reason}` (`amended` | `param_change` | `backfill`),
  `indicator_subscriptions{bucket}` (`1` | `2-4` | `5-7` | `8`, never a user id), `indicator_cap_rejected_total{cap}` (`user` |
  `symbol` | `process` | `window` | `recompute`), `indicator_presets_total{builtin}`, `indicator_preset_denied_total{reason}`
  (`not_owner` | `builtin_immutable`); every † metric and the six analytics events absent, each recorded against its stand-in
  (section 10). A † metric still absent when its naming ticket is Done is a defect against that ticket, not a pass.
- Oracle: the endpoint's series set. 2nd: none.

## 4. Time control

No case sleeps or waits more than 5 minutes. Warm-ups come from how many closed bars the seed holds, resets from event time inside
the replayed bars, browser timers from `page.clock`, and nothing else moves a clock (ruled as BQ-10).

**4.1 What the shipped hook moves.** `CV_TEST_CLOCK` with `CV_TEST_CLOCK_FILE` feeds the **auth clock only** (`services/api/candleviewer/auth/testnet_clock.py`
:3–5; `apps/web/e2e/support/serverClock.ts` :5–12: idle lock, lifetime, step-up, MFA windows, lockouts). No indicator, lease or session-anchor clock is wired to it,
and no `22` operation sets a clock. No case in this plan uses it; its gate (keyless testnet, both variables together, an absolute file path) is `E16` C55's and stands.

**4.2 The strategy, need by need.**

| Need                                                                                                                                                         | Mechanism                                                                                                                                                                                                                                | Cases                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| a warm-up (`warmup_bars`: 20, 21, 28, 200 …)                                                                                                                 | a **bar count**, never a clock: the replay feed holds back bars and releases them one at a time; the expected count is warm-up minus loaded, written from the descriptor before the run                                                  | C24, C38, C54          |
| the UTC session boundary; a funding settlement                                                                                                               | **event time inside the replayed bars** (`GV` `synthetic_day`: 1 440 slots from 2026-10-05T12:00Z with its session anchor; the corpus' funding schedules), never wall time                                                               | C50, C52               |
| UI timers: the 10 s Undo, "still computing…" at 2 s, the 2 s stale rule, "Updating…" / "Applying…" past 100 ms, the 300 ms result-count debounce (D05 LR-12) | the browser clock (`page.clock`), no wait; the 100 ms figures are asserted as captions that appear only past the threshold, never as a measurement (E13-Q03 measures)                                                                    | C03, C04, C08, C19     |
| the 30 s release grace of a server instance (`limits.py` :74 `INSTANCE_GRACE_US`) and the 24-instance churn bound (`limits.py` :71)                          | the server's real clock: **no hook at the base** (a Known-gap row); a case polls the gauge with a deadline of 35 s, inside the 5-minute bound, and asserts on the first settle, never at the grace instant                               | C04, C18               |
| the recompute timeout (`limits.py` :86 `RECOMPUTE_TIMEOUT_S` 5.0) → "history unavailable · Retry"                                                            | the server's real clock, no hook: poll `indicator_instance_errors_total` or the row state with a deadline of 6 s and assert on the first settle; the executor refusal (both slots busy) is the black-box path to the errored row instead | C11                    |
| a restart (re-prime from stored bars; key stability)                                                                                                         | a real API restart on the scratch stack within the bound                                                                                                                                                                                 | C26, C58               |
| a late trade re-closing a bar                                                                                                                                | a late-trade replay: **blocked** (FX-G3)                                                                                                                                                                                                 | C43                    |
| a replay session                                                                                                                                             | not used: a replay `sub` of `indicators.*` is `unknown_topic` until E26 (`23` §6.1 "Live only"), so no server instance is read through replay                                                                                            | C63 (the refusal only) |

Every case names its clock, and no assertion sits on an exact boundary instant: the grace gauge is polled with a 35 s deadline and read on the first settle, never at 30; the Undo after 10 s moved, never at 9.9.

## 5. The destructive and fixture protocol

Nothing in E13 deletes market data (ruled as BQ-18): the deleting operations are `deleteIndicatorPreset` (a soft delete, `deleted_at`; T03.5) and the un-star
path, and nothing else writes storage a user can see. Every case runs on the scratch stack; the cases that write or delete presets (C13 to C17, C20, C61, C62)
follow the protocol below in full. The WS cases (C02, C04, C18, C63) assert gauge and counter deltas, never storage.

- **Scratch database.** Its own Postgres database, migrated to head with the `0040_indicator_presets` seed (`21` §3.8.4, §10.5), created for the run and destroyed
  after it; never shared with a demo, staging or live process (C-2.11). Pre-flight, before any request: the profile is keyless testnet, the 18 built-in rows are present
  with their fixed ids, and no user preset exists. A failed pre-flight stops the case.
- **The preset counts `P`.** `P(pre)` and `P(post)` are a read-only query: live rows (`deleted_at IS NULL`) by owner and by `is_builtin`, deleted rows by owner, a hash
  of the 18 built-in rows, and the audit chain head. A case's expected delta is written from its steps before the run, never from the system's report.
- **Assertions.** "Nothing was stored" (refusals, reads, gated controls): `P(pre)` equals `P(post)` row for row, ignoring only audit growth. "Exactly this": the
  live and deleted counts move by the stated numbers for the stated owner, the built-in hash is unchanged, and the audit holds one `indicator_preset.created` /
  `.updated` / `.deleted` record per write, written ahead of the row (D06 §8.2; C-2.9), with the actor and no preset body or foreign user id.
- **Safety stops.** A case aborts and the stack is destroyed if `P(pre)` differs from the seed or the scratch marker is missing. A built-in row changed, a row of
  another owner touched, or a hard delete (a row gone rather than `deleted_at` set) is **P0** whatever else passes (`03` §11.3: data loss, security breach). A
  worker, client or preset ATR sizing a stop (C34) or a provisional value published (C41) is P0 (`03` §11.3: incorrect sizing). A parity mismatch on a rule-eligible
  metric is P1 (S04 Observability).
- **Fixtures.** Recorded, redacted Bybit captures only (C-13.5): the corpus `packages/fixtures/bybit/2026-10-05/` (its `README.trades.md` :1–4 marks the trade files
  "documented-shape, NOT a live capture", trade ids synthetic, no credentials or UIDs) and the golden set `GV`, whose `manifest.json` names each input's provenance and
  hashes every file. No test, local or CI, reaches `*.bybit.com` or `*.bytick.com`; no fixture is edited by hand (`GV`'s "GENERATED - do not hand-edit"); a
  regenerated vector needs the kernel's `build_version` bumped (`manifest.json` `$note`). Every fixture is named by its section 6 handle and no key, account or
  production row appears in one.

## 6. The fixture catalogue

All market data is the recorded, redacted corpus `packages/fixtures/bybit/2026-10-05/` and the golden set `packages/fixtures/golden/indicators/` built from it
(C-13.5); no key, account or production row. The ticket's three symbol-days map as: normal = FX-TAPE, gap = FX-GAP, partial recording starting mid-day = FX-PARTIAL
(blocked).

| Handle     | Ticket item                           | Content                                                                                                                                                                                                                                                                              | Seeded by                                                                                  |
| ---------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| FX-EMPTY   | fresh install                         | migrated databases, the 18 built-in presets (`21` §10.5), no user preset, a chart with no indicator                                                                                                                                                                                  | stack boot                                                                                 |
| FX-TAPE    | a normal day                          | `inputs_tape_1m.jsonl`: 180 tape-built BTCUSDT 1m bars with aggressor delta (`packages/fixtures/golden/bars/time_bars_BTCUSDT.jsonl`, the E12-S01 golden; no gap); vectors `vectors_tape_1m.jsonl` for `sma`, `ema`, `rsi`, `atr`, `adx`, `vwap`, `cvd`, `delta`, `volume`, `zigzag` | the replay feed into the bar store and the chart (FX-G1)                                   |
| FX-GAP     | a gap day                             | `inputs_kline_gap.jsonl`: 450 BTCUSDT 1m klines from `rest/kline_BTCUSDT_1_page{0,1,2}.json` read by the production page parser, bars 200–214 removed and refilled by `BarSeries.densify()` (15 synthetic bars); delta 0; vectors `vectors_kline_gap.jsonl`                          | as FX-TAPE                                                                                 |
| FX-SYN     | support: gaps, zero volume, a session | `inputs_synthetic_day.jsonl`: 1 440 one-minute slots from 2026-10-05T12:00Z, seed 20261019, gaps of 1, 7 and 30 bars refilled by `densify()`, zero-volume bars, flat runs, an outside bar; vectors `vectors_synthetic_day.jsonl`                                                     | as FX-TAPE                                                                                 |
| FX-USERS   | roles                                 | users A and B with `workspaces:write`, a MANAGER, a VIEWER V and a view-as session; synthetic per run (`TM` §9)                                                                                                                                                                      | the RBAC seed and the session service, per run                                             |
| FX-RULE    | a referenced instance                 | an armed rule on a LIVE and on a DEMO account referencing `ema(21, 5m)`, an enabled alert, and one referencing object of another user                                                                                                                                                | **blocked on E13-S08 (#465)**: the referencing-objects operation does not exist (D02 CG-2) |
| FX-PARTIAL | partial recording starting mid-day    | a symbol-day whose recorded prints start mid-day                                                                                                                                                                                                                                     | **blocked on E13-Q05 (#458)**, which owns it (its Scope); nothing filed                    |
| FX-100K    | the perf dataset                      | a generated 100k-bar series (T01.1, S02.5) and the §4.2 worst-case load generator                                                                                                                                                                                                    | **FX-G4**: E13-Q03 (#456) owns the harness                                                 |
| FX-FUNDING | the funding anchor                    | `rest/funding_history_BTCUSDT_8h.json`, `rest/funding_history_ETHUSDT_4h.json` (two schedules)                                                                                                                                                                                       | the corpus; consumed once the anchor is served (C52)                                       |

**Fixture gaps** (nothing is filed from here: the filing freeze). FX-G1: a seed script and a bar-replay feed that pushes a `GV` input into the bar store and the
chart (no `cvdev` seed module exists at the base; proposed owner E13-Q02 #455). FX-G2: the mid-day fixture (E13-Q05 #458). FX-G3: a late-trade replay that re-closes
a bar (C43; proposed owner E13-Q02 with E13-T02). FX-G4: FX-100K and the load generator (E13-Q03 #456). FX-G5: the diagnostics island that reads the engine stats
(E11-T07 / E46-S01; C07, C12, C33). FX-G6: black-box fault seams — a plugin that throws (C11) and a store or audit `503` on the preset routes (C62; the unit-test
outage fixture of `services/api/tests/indicator_presets/test_presets_outage.py` is not a black-box seam). The backend team agrees this catalogue at the review.

## 7. Entry and exit criteria, and the regression subset

**Entry** (`03` §16). E13-T01 to T03 and E13-S01 to S08 are merged to `main`, CI is green and a deployable build runs on the scratch stack; the fixtures of
section 6 and the FX-G1, FX-G5 and FX-G6 tools exist; the `22` `workspaces` and `23` §6.1 `indicators` contract tests are green; every open question a case
depends on is answered, or that case is marked blocked on it. **At the base** (`54f4a82d2`) E13-T02 (#426) and E13-T03 (#427) are merged, E13-T01 (#425) and
E13-S01 to S08 are open and every frontend surface is unbuilt (D06 §0 :54–62): the entry criteria are not met, which is why this PR closes #422 on the document
(ruled as BQ-21, as #404 did) and the execution record is E13-Q06's (#459). Every frontend surface (SCR-034, SCR-035, SCR-036) is unbuilt at the base and E13-T01 (#425) is open.

**Exit** (the epic's QA sign-off, `03` §16). Every case has a recorded result (pass or fail, build sha, environment), a blocked case carrying its question or
owner id; no P0 or P1 is open (section 5's P0 and P1 rules); every **[R]** case is automated by E13-Q02 or listed manual with an owner, and every **[F]** case
ran; every audit action and metric a case names was observed (a † metric by its stand-in, section 10); the benchmark (E13-Q03), the a11y audit (E13-Q04) and the
parity pack (E13-Q05) are attached; section 9 has no gap and every section 10 row is answered or accepted by its owner. This plan's sign-off is necessary, not
sufficient: E13-Q06 (#459) assembles the epic's.

**Regression subset.** The [R] cases (20 of 66: C01 to C04, C10, C13, C22, C24, C26, C28, C30, C34, C37, C40, C41, C44, C50, C57, C58, C61) run every sprint
after exit and on any change to `services/api/candleviewer/orderflow/indicators/`, `api/indicator_presets*`,
`storage/repositories/indicator_presets.py`, `rules/vocabulary/metrics.py`, `packages/chart-engine/src/plugins/indicator/`,
`apps/web/src/features/indicators/`, the `22` indicator operations, `23` §6.1 `indicators` or the deck: the automated ones in CI's E2E and contract jobs
(E13-Q02), the rest in the sprint's QA pass. A flaky member is quarantined within 24 h with an owner (C-9.3), never retried silently. Every story section has an
**[F]** case: 3.1 C06, C09, C11, C14 to C16, C18, C19; 3.2 C24; 3.3 C33; 3.4 C36, C38; 3.5 C41; 3.6 C46, C47; 3.7 C54; 3.8 C57, C59, C60; 3.9 C61 to C64 — the
ticket's named failure modes map as: catalogue fetch failure C06, insufficient history C24 and C38, unrecorded symbol C47, blocked removal C57, invalid
parameter C36.

## 8. What this plan references and does not contain

- E13-Q02 (#455): the automation of these cases, the seed script and the bar-replay feed (FX-G1), the late-trade replay (FX-G3); it references the ids
  `E13-Q01-Cnn` (ruled as BQ-05) and executes `TM` AC-14's UI half. E13-Q06 (#459): the exploratory charters, the chaos scenarios, the black-box execution of
  AC-08, AC-12, AC-14, AC-15 and AC-22 and the epic's QA sign-off.
- E13-Q03 (#456): every budget this plan cites and never measures — the ten-indicator scene (≥ 55 fps, never under 30), the four-sub-pane scene, the Ichimoku and
  VWAP worst cases of E13-K01, the 250 ms add and the 100 ms re-tune, the ≤ 2 ms pane redraw and the degradation cadence, the draw-call counts (≤ 18 per pane, ≤ 40
  per chart), the 20 / 6 cap confirmation (`TM`:105) and AC-15; FX-G4.
- E13-Q04 (#457): the accessibility audit — D05 §14.1's three Gherkin blocks (lifted by hash in D06 §9.2, sha256 `49dfdd4ceff5` at D06's base), §14.2's rows,
  the axe pass, the announcement cadence, the contrast pairs and the greyscale / CVD renders (D06 §10.4). This plan's UI cases are smoke only (proposed as
  BQ-15); C65 keeps the one black-box leg (states carried in text).
- E13-Q05 (#458): the parity pack — every `client_worker` indicator's numerics and the worker mirror of the nine server kernels within the manifest tolerance,
  AC-21, `indicator_parity_mismatch_total`'s behaviour, and FX-PARTIAL (FX-G2).
- E13-X02 (#466): the security execution of AC-01 to AC-20, AC-23 and AC-24 and the controls' verification; E28-X03 (#976): the ATR-sizing legs AC-10, AC-23, AC-24
  (C34 names them) and, with E13-X02, AC-11 (C41); each leg of this plan asserts only the black-box answer. E13-D07 (#454): the design QA of the built surfaces against D06.

## 9. Traceability

Scenarios are numbered in source order. Every scenario of US-IND-001 to US-IND-008 (24), E13-S01 to S08 (46) and E13-T01 to T03 (15) maps to a case: 85 of 85;
a blocked case still maps, its blocked half marked in the case. Every Must story has an **[F]** case: US-IND-001 C06; 002 C24; 003 C33; 004 C36; 005 C41; 006 C47;
007 C54; 008 C57. Deliberate gaps, each with its reason and owner, are the blocked cases of section 10.

| Source     | Scenario to cases                                     |
| ---------- | ----------------------------------------------------- |
| US-IND-001 | 1 C02 · 2 C03 · 3 C04                                 |
| US-IND-002 | 1 C22 · 2 C23 · 3 C24                                 |
| US-IND-003 | 1 C28 · 2 C29 · 3 C30                                 |
| US-IND-004 | 1 C34 · 2 C35 · 3 C36                                 |
| US-IND-005 | 1 C39 · 2 C40 · 3 C41                                 |
| US-IND-006 | 1 C44 · 2 C45 · 3 C46                                 |
| US-IND-007 | 1 C50 · 2 C51 · 3 C52                                 |
| US-IND-008 | 1 C55 · 2 C56 · 3 C57                                 |
| E13-S01    | 1 C02 · 2 C03 · 3 C04 · 4 C05 · 5 C06 · 6 C07 · 7 C08 |
| E13-S02    | 1 C22 · 2 C23 · 3 C24 · 4 C25 · 5 C26                 |
| E13-S03    | 1 C28 · 2 C29 · 3 C30 · 4 C31 · 5 C32 · 6 C33         |
| E13-S04    | 1 C34 · 2 C35 · 3 C36 · 4 C37 · 5 C38                 |
| E13-S05    | 1 C39 · 2 C40 · 3 C41 · 4 C41 · 5 C42 · 6 C43         |
| E13-S06    | 1 C44 · 2 C45 · 3 C46 · 4 C47 · 5 C48 · 6 C49         |
| E13-S07    | 1 C50 · 2 C51 · 3 C52 · 4 C53 · 5 C54                 |
| E13-S08    | 1 C55 · 2 C56 · 3 C57 · 4 C58 · 5 C59 · 6 C60         |
| E13-T01    | 1 C26 · 2 C24 · 3 C03 · 4 C12 · 5 C11                 |
| E13-T02    | 1 C22, C37 · 2 C48 · 3 C01 · 4 C24, C38 · 5 C43       |
| E13-T03    | 1 C15 · 2 C16 · 3 C14 · 4 C14 · 5 C17                 |

The ticket's cross-cutting items: 1 value identity C34 · 2 the provisional swing C41 · 3 partial CVD history C46 · 4 ten indicators C07 · 5 the preset round trip
and the hostile bundle C13, C20 · 6 the symbol and timeframe switch C18 · 7 backend unreachable C06, C19.

Abuse cases of `TM` §9: AC-01 C16 · AC-02 C16 · AC-03 C15 · AC-04 C14, C20 · AC-05 C14 · AC-06 C14 · AC-07 C14 · AC-08 C14 · AC-09 C20 · AC-10 C34 · AC-11 C41 ·
AC-12 C63 · AC-13 C52 · AC-14 C09, C33 · AC-15 E13-Q03 (section 8) · AC-16 C57 · AC-17 C60 · AC-18 C62 · AC-19 C61 · AC-20 C63 · AC-21 E13-Q05 (section 8) ·
AC-22 C64 · AC-23 C34 · AC-24 C34.

## 10. Open questions

13 † rows re-grepped at the READY sha `54f4a82d2` (section 0): all 13 still have no emitter, none changed status. Each is a question for the owner of the source it names, not a guess (ruled as BQ-19). A case it blocks says so; the other cases of the same story run. D06's own
open questions are carried by id with D06's owner lanes and are never re-decided here: **Q-1** the warm-up-complete words "EMA 200 ready" (C24; the owner on
#2701); **Q-4** the sub-pane add announcement (C28; the owner); **Q-11** no parameter-edit debounce is specified (C03, C10; E13-S01 with E13-T01); **Q-12** the
failed-catalogue words (C06, C62; the owner); **Q-13** the VWAP / CVD reset label, the no-print state and the `since_load` notice (C47, C50, C54; the owner;
E13-S06 and E13-S07 consume); **Q-14** the MA cross, metric only (C27; the owner); **Q-15** the renko tooltip words (C21; the owner); **Q-16** the compute-failed
map's words (C11, C62; the owner); **Q-17** the words for the preset and topic refusals with no deck row (C06, C15, C17, C62, C63; the owner).

- **OQ-1** Three story items have no descriptor at the base (C23, C27; blocked on E13-S02 #424 with E13-T02 #426, and on D06 Q-14 and the `14` owner). Reading A
  (US-IND-002/2, S02.2, S02 scope, `14` SCR-034 Type): the MA ribbon, the MA cross and a "custom composite" are v1 entries. Reading B (`22` `listIndicators` and
  `catalogue.py` :615–619): the v1 set is the 28 ids and none is a ribbon, a cross or a composite; D02 CG-5 draws the ribbon as E13-S02 will add it.
- **OQ-2** The compute histogram's label (C03, C66; owner: the E13-S01..S07 and E13-T01 ticket text, with E13-T02 #426). Reading A (the stories' Observability,
  T01: `indicator_compute_seconds{indicator,phase=full|incremental}`). Reading B (the base, `metrics.py` :38–43): `{indicator,where}`, `where="server"`. The plan
  asserts the base's label and marks `phase` †.
- **OQ-3** Sub-pane heights persisted per layout (C31; blocked on E15 with E13-T03 #427, consumer E13-S03 #460). Reading A (US-IND-003 NFR, S03.4, S03 scope: "E13
  writes the values, E15 owns the workspace envelope"). Reading B (D06-G-3; `22` `LayoutPaneInput`): no field carries a height; the ratio lives in the engine only.
- **OQ-4** The hostile `WorkspaceBundle` (C20; blocked on E15-S07 #560). Reading A (the ticket's item 5, T03 scope, AC-09): an import path exists to attack.
  Reading B (`22` `WorkspaceBundle`: "no operation takes a bundle yet"): only the schema's rules can be asserted, once E15-S07 lands.
- **OQ-5** The dedicated CVD pane (C45; blocked on E23). Reading A (US-IND-006/2, S06.2): the indicator matches the pane exactly. Reading B (the base): no pane
  exists; the topic's point against `GV` is the stand-in and the pane is compared when E23 lands.
- **OQ-6** The referencing-objects lookup and FX-RULE (C57, C60; blocked on E13-S08 #465). Reading A (US-IND-008/3, S08.3, S08.6, D02 D24): the server returns the
  referencing rules and alerts, filtered to what the caller may see, and a direct delete is refused with them. Reading B (D02 CG-2; `22`): no operation exists, so
  the dialog cannot render a server answer and no direct call can be made; each rule row needs the account's `env` as its own field (D06 §15.2, frozen (7)).
- **OQ-7** MANAGER's permission set (C61, section 2.1; owner: the `04` and RBAC-seed owners). Reading A (`22` `x-rbac`: permissions, not roles; the UI's T2 for
  VIEWER only, D06 §12): a MANAGER with `workspaces:write` saves presets. Reading B: a seed that withholds it makes every MANAGER write `403`. The server is the
  control, so the cases assert its answer.
- **OQ-8** 16 against 20 (C09; owner: E15, the layout owner, with E13-S08 #465). Reading A (`TM`:110, D02 D5, frozen (3)): a chart holds up to 20 instances.
  Reading B (`22` `LayoutPaneInput.indicator_preset_ids` `maxItems: 16`): a layout save with more than 16 preset references is refused (D06-G-4). Stated, not
  resolved.
- **OQ-9** `TM` AC-01's single-preset `GET` (C16; owner: the `TM` lane, E13-X02 #466). Reading A (AC-01): `GET /indicator-presets/{id}` exists. Reading B (`22`):
  the preset routes are list, create, replace and delete; the `GET` leg is the list's (AC-02).
- **OQ-10** MFI over a zero-volume bar (C49; owner: E13-S06 #463 with E13-T02). Reading A (S06.6): the previous value is carried forward. Reading B
  (`catalogue.py` :606–607 `nullable_when`): `None` while the money flow of the last n changes is 0. The case follows the descriptor.
- **OQ-11** The direct delete of an indicator instance (C60; owner: E13-S08 #465 with the `22` owner). Reading A (S08.6, AC-17): an operation deletes an
  instance server-side and the guard refuses it. Reading B (the base): instances are client state and WS leases; `unsub` releases a lease and no route deletes one.
- **OQ-12** The churn and symbol-cap codes (C63; owner: the `TM` lane with the `23` owner). Reading A (`TM` AC-12): `429` for churn beyond 20 per second and
  `409 indicator_symbol_cap`. Reading B (`23` §6.1 "Refusals" to "As built"; `limits.py` :71): `subscription_limit` naming `user`, `symbol` or `process`, and the 24-instance churn bound
  with a retryable message. The plan follows `23`.
- **OQ-13** The `source` and `offset` parameters (C25, C56; owner: E13-S02 #424 with E13-T02 #426). Reading A (S02 scope, S02.4, US-IND-008/2): every MA takes
  `length`, `source` and `offset`. Reading B (`catalogue.py` :421–462): one parameter, `n`.
- **OQ-14** The divergence detection control (C29; owner: E13-S03 #460). Reading A (US-IND-003/2, S03.2): detection can be enabled. Reading B (the base): no
  parameter or control exists.
- **OQ-15** The sizing record's source field (C34; owner: E28-T03 / E28-X03). Reading A (`TM` AC-10, AC-23): the record names `source=kernel` or
  `source=fallback`. Reading B (`sizer.py` :47–50): `AtrSource` and `AtrUnavailable` are typed; the record's field name is E28's to state. The plan asserts the
  literal set and names the owner.

**Known gaps: metrics, events and hooks with no emitter on `main`** (a `git grep` of `services/`, `infra/`, `packages/`, `apps/`, `tools/` and `tests/` at
`54f4a82d2` finds none; a † marks each use in a case). A case asserts the stand-in until the owner ships it or amends its ticket. Emitters that **exist** at the
base and are asserted directly: `indicator_compute_seconds{indicator,where}`, `indicator_cache_hits_total`, `indicator_cache_misses_total`,
`indicator_recompute_total{reason}`, `indicator_subscriptions{bucket}`, `indicator_cap_rejected_total{cap}` (`metrics.py` :38–72), `indicator_presets_total{builtin}`
and `indicator_preset_denied_total{reason}` (`metrics_catalogue.py` :2624–2652).

| Metric, event or hook                                                                                                                                               | Cases                          | Named by (owner)                                                                                            | Assert meanwhile                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `indicator.added`, `indicator.settings_changed`, `indicator.removed`, `indicator.reordered`, `indicator.visibility_toggled`, `indicator.remove_blocked` (analytics) | C02 to C05, C08, C23, C30, C57 | `14` SCR-034..036, D02 D30, the stories (no transport, schema or registry: D12-G-7; the `20` / `24` owners) | the legend and tree state and the deck announcement for each action                                   |
| `indicator_parity_mismatch_total{indicator}`                                                                                                                        | C34                            | the stories' Observability; `TM`:359 (E13-Q05 #458, E13-T04)                                                | the parity pack's result for the indicator                                                            |
| `indicator_active_instances{indicator}`                                                                                                                             | C07                            | S01..S07, T01                                                                                               | the chart's instance count and `indicator_subscriptions{bucket}` for the server ones                  |
| `indicator_compute_seconds{…,phase}`                                                                                                                                | C03                            | S01..S07, T01 (OQ-2)                                                                                        | `indicator_compute_seconds{indicator,where="server"}`                                                 |
| `indicator_instance_errors_total{indicator}`                                                                                                                        | C11                            | T01                                                                                                         | the errored row and the chip's "· 1 error" suffix                                                     |
| `indicator_subpanes_active`; the pane collapse / creation log                                                                                                       | C28, C30, C33                  | S03                                                                                                         | the DOM-mirror's pane count                                                                           |
| `indicator_zigzag_reprovisionalised_total`                                                                                                                          | C43                            | S05                                                                                                         | `indicator_recompute_total{reason="amended"}`                                                         |
| `indicator_cvd_partial_history_total{symbol}`                                                                                                                       | C46                            | S06                                                                                                         | the row's partial-history glyph and sentence                                                          |
| the anchor-reset log                                                                                                                                                | C50                            | S07                                                                                                         | the boundary line and `GV`                                                                            |
| `metric_resolution_failures_total{key}`, `indicator_removal_blocked_total`                                                                                          | C57, C59, C60                  | S08                                                                                                         | the `422` naming the key; the dialog                                                                  |
| `indicator_provisional_published_total`                                                                                                                             | C41                            | `TM`:361 (E13-S05 #462)                                                                                     | the WS frames scanned for the provisional value (none)                                                |
| `indicator_atr_unavailable_total{reason}`                                                                                                                           | C34                            | `TM`:363 (E28-T03, E13-S08)                                                                                 | the sizing record's reason (E28's, OQ-15)                                                             |
| `indicator_output_bytes{where}`                                                                                                                                     | C09                            | `TM`:358 (ADR-0034; E13-T01)                                                                                | none: the worker memory cap is E13-T01's bench                                                        |
| the bar-replay feed and the seed script (FX-G1); the late-trade replay (FX-G3)                                                                                      | C02, C22, C24, C26, C43        | section 6 (E13-Q02 #455 proposed)                                                                           | —                                                                                                     |
| the mid-day fixture FX-PARTIAL (FX-G2)                                                                                                                              | C46                            | E13-Q05 #458                                                                                                | —                                                                                                     |
| FX-100K and the load generator (FX-G4)                                                                                                                              | C02, C07, C12, C26             | E13-Q03 #456                                                                                                | the budgets cited, never measured here                                                                |
| the diagnostics island that shows the engine stats (FX-G5)                                                                                                          | C07, C12, C33                  | E11-T07 / E46-S01 (`chart-probe.ts` :3–8)                                                                   | —                                                                                                     |
| a plugin fault seam; a store / audit `503` seam on the preset routes (FX-G6)                                                                                        | C11, C62                       | E13-T01 #425; E13-T03 #427                                                                                  | the executor refusal (`internal_error`) for the errored row; the unit-test outage fixture as evidence |
| a hook on the 30 s release grace and the 5 s recompute timeout                                                                                                      | C04, C11, C18                  | `limits.py` :74, :86 (E13-T02 #426)                                                                         | a bounded real-time wait (section 4)                                                                  |
| the referencing-objects operation (D02 CG-2) and FX-RULE                                                                                                            | C10, C57, C60                  | E13-S08 #465                                                                                                | —                                                                                                     |
