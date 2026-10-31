# E22 Big trades and bubbles: black-box test plan

Ticket: E22-Q01 (#713). Status: v1.0, the deliverable of #713 (its PR closes the ticket, BQ-14), written on the before-writing question list's
defaults, all ruled (section R: the ruling of record, #713 comment 6537475047 on the list 6536429292). It holds the conventions, the scope, the test
matrix, the cases for US-BIG-001, 002, 003, 004 and 006, the E22 story and task Gherkin, the cross-surface agreement cases, the edge matrix and the
boundary table the threat model hands to this plan, the four exploratory charters, the honesty checklist, the time-control strategy, the destructive and
fixture protocol, the fixture catalogue, the entry and exit criteria with the regression subset and the triage convention, the traceability and the open
questions. E22-Q02 to E22-Q05 automate, measure, audit and execute it; this plan contains no code.

## 0. Conventions

- **Base and READY sha.** The plan was written at `origin/main` `f2ae72d68b072924b338d2302c1c142834dd718e` (`f2ae72d68`) and rebased onto
  `7e13e073a066d296b205e075c6b3335d7fc096ff` (`7e13e073a`), where every cite was re-checked: between the two only `26` changed among the cited files, and
  this plan cites `26` by section through D05. The BQ list was read at `93025160e`; between it and `f2ae72d68` only docs landed that this plan cites (the
  merged E22-D05 pack and its deck, two `14` / `15` catalogue rows), and no cited code line moved. Every † and every blocked row was re-grepped at `origin/main`
  `9afa0b29d500dc18cc7568a5ec21c659470f13bf` (`9afa0b29d`), the READY base: the nine † rows still have no emitter, no blocked row changed status, and the
  only cited file that moved since `7e13e073a` is `14`, whose SCR-053 lines did not (the #422 rider carried by BQ-24).
- **Expectations come from the specification, not the implementation.** Each case cites its source:
  - `US-BIG-nnn/k` is scenario k of that story in `docs/plan/11-user-stories.md` §12 (`11`:2172–2290); the global acceptance criteria are `11`:42–49;
  - `S01` to `S05` and `T01`, `T02`, `T04` are the Gherkin of E22-S01 to S05 and E22-T01, T02, T04 in `docs/plan/backlog/E22.json` (`E22J`; the one-line
    bodies at S01 :377, S02 :404, S03 :432, S04 :459, S05 :485, T01 :539, T02 :565, T04 :614); `S03.4` is E22-S03's fourth scenario, in ticket order;
  - `22` is `docs/plan/22-api-openapi.yaml`, cited by operation id and schema name (`getTrades`, `getMetrics`; `PublicTrade`, `TradesPageMeta`, `Limit`,
    `Cursor`), with a line only where a rule is quoted; `23` is `docs/plan/23-ws-protocol.md` (§6.1's `trades` bullets at `23`:786–792, §14.2 `TradesBatch` at
    `23`:2830–2880, the kind-3 note at `23`:257); `24` is `docs/plan/24-internal-schemas.md` (§2.10 rules at `24`:595–601; the metric table at `24`:1125–1129);
  - `LIM` is `services/api/candleviewer/orderflow/limits.py`; `TM` is `docs/security/threat-models/E22-big-trades.md` (§9 abuse cases, `TM`:203–225);
  - `D02` to `D04` are `docs/design/E22/E22-D02.md` to `E22-D04.md`; `D05` is the merged hand-off pack `docs/design/E22/E22-D05.md`; the **deck** is
    `docs/design/E22/E22-D05-copy.json`, cited by key and the line its entry starts on (`d02.13.cp04`);
  - `GB` is the big-trade golden `packages/fixtures/golden/bigtrade/`; `BYB` is `packages/fixtures/bybit/`; `CONF` is
    `packages/fixtures/golden/bars/conformance/`;
  - `E13P` and `E16P` are the merged plans `docs/qa/test-plans/e13-indicators.md` and `e16-recorder.md` (their form is followed, never their content).
- **Where the ticket text and the merged sources differ**, the case follows the merged source (BQ-04): each difference is a row in section 10
  and the case is marked **blocked on** its owner. Where merged sources differ from each other, the case says so. Nothing is guessed: a hook, metric, string,
  field or number that no merged source states is a † or a blocked row with an owner, never a value of this plan's.
- **Environment.** Staging only, never live (ticket Technical notes; `03`:418–419; C-13.5). No real key, no account identifier and no production
  row appears in a step, a fixture or an evidence file; screenshots carry no account identifier (ticket Security notes). Two modes, each case naming its own:
  - **E-REPLAY**: the staging stack fed by the fixture replay of section 6 (`03`:418, "Fixture replay for most"); exact expected values come from the
    fixtures. Feeding a fixture into the staging trade stream is FX-G3 (section 6).
  - **E-DEMO**: the demo profile, whose market data is Bybit's live public stream (`03`:419); no fixture value can be asserted there, so an E-DEMO case
    asserts an invariant only (the same print flagged alike on every surface, `dropped` and `coalesced_count` accounting, `effective` echoes).
- **Case ids:** `E22-Q01-Cnn` (BQ-03). The line under the id names the layer (`03` §2: `contract`, `integration`, `e2e`, `perf`, `a11y`),
  the mode and state it covers (section 2) and what it mirrors. **[R]** joins the regression subset (section 7); **[F]** marks a failure path; **blocked on**
  an owner means that owner must answer or ship first; the case is still executable the day the blocker clears, never untestable (BQ-12).
- **Sources, in order** (BQ-07): (1) the wire: `sub_ok.effective` (`big_trade_threshold`, `big_trade_mode`, defaults included, `23`:790)
  and each `TradesBatch` item (`is_big_trade`, `cluster_size`) and frame field (`dropped`, `coalesced`, `coalesced_count`, `big_trade_threshold`;
  `23`:2838–2880), and REST `TradesPageMeta` (`22`:19648–19662) > (2) an API answer: a `22` status and rule, a `23` `sub_ok` or `err` code > (3) the
  presentation: a tape row's accessible name, a bubble's DOM-mirror name and tooltip, quoted from the deck (presentation only, and the case says so). Canvas
  pixels are never an expected value: a bubble is read through its sparse DOM-mirror node and its tooltip (D02:255, D02:269). Every case also names a
  secondary record: a counter or frame field (section 10's lists); a read-only case with none says "none (a read)". A † after a metric or event marks one
  that nothing emits on `main` at the base: the case asserts its stand-in from section 10 until the owner ships it.
- **The fourth case field is named Source** (BQ-03): "Source: where the expected value comes from, in ladder order, then the 2nd record".
- **Strings** (BQ-19): every expected string is a deck entry quoted verbatim by key, or a `22` / `23` rule name. Three deck entries have no merged
  words (`d05.05.range` and `d05.06.memory`, status `proposed`; `d05.07.feed`, `named-elsewhere`; D05:300–302): a case that needs them asserts behaviour, not
  text, and is blocked on the owner. Number grouping is compared by digits and separators, not byte for byte, while D05-C-14 is open (D05:304, D05:539).
- **Time and destruction:** sections 4 and 5 bind every case. No case sleeps or relies on more than 5 minutes of real elapsed time (`E16P` section 4's bound);
  E22 deletes nothing, and every case runs on a scratch stack.

## 1. Scope and references

**In scope:** SCR-053 (`14`:1257) with the tape organism, the threshold and bubble control strip, the CMP-112 marks on the chart with their legend and DOM
mirror, and CMP-227 "(estimated)"; the five stories US-BIG-001, 002, 003, 004 and 006 (`11`:2174–2286) with the Gherkin of E22-S01 to S05, the merged task
Gherkin of E22-T01, T02 and T04 (BQ-01 (a): 15 + 25 + 14 = 54 scenario rows); the global acceptance criteria #3, #5, #6 and #7
(`11`:44, :46–48); the ticket's cross-surface invariant and edge matrix as section 3.7; the threat model's boundary-table duty and AC1, AC2, AC3 and AC8
(`TM`:179, `TM`:207–209, `TM`:214; BQ-09); the four exploratory charters (section 3.8, BQ-10). **Out of scope** (ticket;
section 8): the automated suite (E22-Q02), perf scripts and every measured budget (E22-Q03), the a11y audit (E22-Q04), security abuse cases other than those
named above (E22-X02), US-BIG-005 alerts (E22-S06, Backlog sprint, `E22J`:510), E22-T03 (the ADR task, not merged: referenced only).

**Global criteria that do not apply here** (BQ-01): #1 and #2 (RBAC, audit, `11`:42–43) apply to the read routes only, because the one state-changing path, a
saved threshold, has no route at the base (D05-G-2, D05:535); #4 (fps, `11`:45) is E22-Q03's; #8 (`11`:49) needs a trading-capable control and SCR-053 has
none. Each is stated in section 9's table, not dropped.

**Read first:** `03` §11 and §16; `11`:2172–2290; `22` `getTrades` and `getMetrics`; `23` §6.1 `trades`, §14.2, §3.4 kind 3; `24` §2.10; `LIM`; `TM` §7–§10;
D05 (§0, §3, §5, §6, §8.4, §9, §11) and the deck; D02 §4 (the state table, D02:114–142), §5 (the pause model, D02:144–184), §9 (D02:273–275); D04 §8 and §9
(D04:318–373).

**Deviations from the ticket** (repeated in the PR; BQ-02 to BQ-04, BQ-24): the path is `docs/qa/test-plans/e22-big-trades.md` (the ticket names
none; its Repo paths are the generic chart-engine brief); the case ids are `E22-Q01-Cnn`, which E22-Q02 (#752) is expected to reference; the PR title is a
conventional commit (the ticket's `E22-Q01: …` form is not, C-4.10); the DoD's "reviewed by the story owners and the Security engineer" is replaced by one
independent read plus the orchestrator's read, as #422 was; the ticket's "executed" and "QA sign-off" cannot be met at the base (every frontend surface is
unbuilt, D05:56–57), so section 7 says so and the execution record is E22-Q05's (#755). Items the merged sources read differently from the ticket: the
clustering maximum (5 000 ms on REST only, 2 000 ms on WS: C56, C57); "a screen with six states" (D02 draws 23, D02:120–142); the third surface
`GET /market/metrics` (not served at the base: C55); the counter names (shipped with a `cv_ws_` prefix: section 10); the popover content (C37); the replay
note (C02, section 4); "threshold percentile 0-100" (the engine refuses 0 and 100: C21). Each is a section 10 row.

## R. Rulings applied

The before-writing question list (BQ-01 to BQ-25, posted on #713 as comment 6536429292, read from `main` `93025160e`) proposed a default for every
question, and the orchestrator's ruling of record (#713 comment 6537475047, 2026-10-31, under the 2026-10-29 delegation) rules **all 25 as proposed**, with
these riders: cites by operation id, schema and field, with lines only where a rule is quoted (BQ-02); the deck's PROPOSED percentile range against the
engine's bounds is a C-row, the plan citing the engine meanwhile (BQ-08: C-PCT, C21); the ETHUSDT and SOLUSDT windows scanned before the plan says no
recorded print reaches the default (BQ-11, U5: C16); the counters' read path on staging an open question to the observability owner (BQ-16: OQ-1); the
metrics leg one row blocked on #645 / #658 with an aggregate stand-in (BQ-05: C55, G-M1); the PR closes #713 on the document (BQ-14). The seven departures
from #422 are confirmed by name (BQ-25; listed in its row). A later ruling that changes a row changes the sections it names in one pass.

| BQ    | Question                              | Default applied in this plan                                                                                                                                                                                                                                                                                                                                                                 | Sections           | Status                                                                        |
| ----- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ----------------------------------------------------------------------------- |
| BQ-01 | scenarios covered                     | (a) 15 `11` scenarios + 25 story + 14 task = 54 rows; global ACs #3, #5, #6, #7; the cross-surface and edge items as 3.7; the `TM` rows of BQ-09                                                                                                                                                                                                                                             | 1, 3, 9            | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-02 | path, one file, no tool               | (a) `docs/qa/test-plans/e22-big-trades.md`; no audit tool, no pins file; the READY sha and re-grep recorded in section 0 by hand                                                                                                                                                                                                                                                             | 0, 1               | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-03 | ids, sections, fourth field           | (a) `E22-Q01-Cnn`; the template's ten sections plus R; the fourth field named **Source**                                                                                                                                                                                                                                                                                                     | 0, all             | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-04 | ticket text vs merged sources         | the merged source wins; each difference a section 10 row with its owner; the case "blocked on" it                                                                                                                                                                                                                                                                                            | 0, 1, 10           | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-05 | the third surface                     | (a) the invariant on WS item, REST item and bubble mirror per print id; `GET /market/metrics` not served at the base: one blocked row (G-M1) on #645 / #658, with an aggregate stand-in                                                                                                                                                                                                      | 3.7 (C50, C55), 10 | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-06 | the documented limits and divergences | (a) assert the shipped or drawn rule; the four divergences (cluster flag, cluster size, cluster position, tier 2) are C-rows on their owners                                                                                                                                                                                                                                                 | 3.7 (C51–C54), 10  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-07 | the source ladder                     | (a) wire > API answer > presentation; canvas pixels never an expected value                                                                                                                                                                                                                                                                                                                  | 0                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-08 | the edge matrix                       | (a) every row against the shipped bound; the 5 000 ms row as "REST only" (C-row); the percentile-range and threshold-0 rows with their C-rows; every threshold-mode case blocked on E22-S02                                                                                                                                                                                                  | 3.7 (C56–C57), 10  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-09 | the `TM` boundary cases               | (a) one boundary-table row per `LIM` constant reachable on a public surface; status from `22` / `23`, never `TM`'s "400"; AC1–AC3 and AC8; the rest named to X02 / Q03 / Q04                                                                                                                                                                                                                 | 3.7 (C56, C57), 8  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-10 | the four charters                     | (a) mission / areas / checks / debrief, each executable only after its stories land; E22-Q05 runs them                                                                                                                                                                                                                                                                                       | 3.8                | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-11 | fixtures                              | (a) the section 6 table; synthetic stand-ins labelled synthetic; the missing items as FX-G rows with a proposed owner; nothing filed                                                                                                                                                                                                                                                         | 6                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-12 | cases not producible on staging       | (a) each names a seeded synthetic sequence delivered by E22-Q03's burst harness (FX-G4), the in-process helpers cited as white-box evidence only; no new hook                                                                                                                                                                                                                                | 3, 4, 6            | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-13 | the honesty checklist                 | (a) one block per estimate site (clustering, percentile, cap); drawn strings asserted; popover accuracy against `24`:597; the missing failure mode, "Why estimated?" and the bar-rule sentence are C-rows; no wording invented                                                                                                                                                               | 3.9                | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-14 | entry and exit                        | (a) entry not met for UI cases, met for wire cases once FX-G3 runs; the PR closes #713 on the document; the execution record is E22-Q05's                                                                                                                                                                                                                                                    | 7                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-15 | triage                                | (a) P0 unreported loss and foreign or wrong-symbol data; P1 badge, popover, cross-surface disagreement outside the documented limits, wrong effective threshold; P2 a11y, legibility, lost pause or focus; P3 wording                                                                                                                                                                        | 7.1                | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-16 | counters and the † table              | (a) the shipped names asserted; the ticket's names a C-row; the no-emitter names as † rows with a stand-in; the read path an open question                                                                                                                                                                                                                                                   | 10                 | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-17 | out of scope and hand-off             | Q02 / Q03 / Q04 / Q05 / X02 / D06 / K01 / S06 as section 8; one black-box a11y leg and a keyboard-only and screen-reader smoke kept here                                                                                                                                                                                                                                                     | 8, 3.7 (C62, C63)  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-18 | a11y and perf observables             | (a) KR, FP, AN rows by id; reduced motion identical; what QA sees without instruments; fps and budgets are E22-Q03's                                                                                                                                                                                                                                                                         | 3.7 (C62–C64)      | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-19 | strings                               | every string a deck key or a `22` / `23` rule name; three un-worded entries assert behaviour; digits compared, not grouping                                                                                                                                                                                                                                                                  | 0                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-20 | D05's open rows                       | (a) carried by id with owner lane and due date; "blocked on" only where a row changes an expected value                                                                                                                                                                                                                                                                                      | 10                 | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-21 | clocks                                | print time for the engine; injected sequences need no wall wait; aging by a second print 60 s later in print time; `CV_TEST_CLOCK` not used                                                                                                                                                                                                                                                  | 4                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-22 | role legs                             | one row per route asserting the server's answer; settings-write legs blocked on E22-S02; `TM` AC14–AC16 are X02's                                                                                                                                                                                                                                                                            | 2.1, 3.7 (C61)     | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-23 | destructive protocol                  | reduced: a scratch stack per run; counters read before and after each burst case; another user's or symbol's data in a frame is P0; persistence legs blocked                                                                                                                                                                                                                                 | 5                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-24 | PR shape and calendar                 | one PR, branch `chore/e22-qa-plan`, title `docs(order-flow): add the E22 big-trade black-box test plan (E22-Q01)`, `Closes #713`, labels `type/test` `area/order-flow` `priority/p1` `qa`; `large-pr-approved` by the orchestrator if > 800 lines; no `security-review`; not late                                                                                                            | PR, 0              | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |
| BQ-25 | departures from #422                  | confirmed by name: (1) the fourth field renamed Source; (2) the backend is merged, so wire cases run today; (3) `TM` gives this plan AC1–AC3, AC8 and the boundary table only; (4) the third surface is not mounted; (5) the burst is not producible from a recording and a replay does not drive the live publisher; (6) three estimate sites; (7) no tool, no new hook, no outside dry run | R                  | RULED (orchestrator, 2026-10-31, #713 ruling of record — 6536429292's answer) |

## 2. The test matrix

The dimensions: **role** OWNER, MANAGER, VIEWER, plus the view-as leg (a session state: D02 S21, S23, D02:140, :142); **action** subscribe and read the
tape (WS), read a page (REST), pause and resume, inspect a row or a bubble, filter and pick columns, set the threshold, set clustering, switch the bubble
scale; **state** streaming, high rate (coalescing), paused, paused with a full ring, disconnected, stale, reconnect backfill, partial history, empty or thin,
filtered-empty, over-threshold (capped), clustering on.

**2.1 Role by action** (BQ-22). A cell is the server's answer (`22` `x-rbac`; `services/api/tests/contract/rbac/matrix.yaml`); a case asserts
that answer and never a role name. Client-only actions (pause, filter, columns, scale) send no request. The threshold and clustering controls are
settings writes for the panel (D05 §5) with no route at the base (D05-G-2, D05:535): VIEWER and view-as see them as T2 with the deck reason before any
request (`d02.13.cp24`), and the server legs are blocked on E22-S02 (#715).

| Action                        | Operation (permission · scope)                                                  | OWNER    | MANAGER  | VIEWER                                                                       | view-as                                 | Cases         |
| ----------------------------- | ------------------------------------------------------------------------------- | -------- | -------- | ---------------------------------------------------------------------------- | --------------------------------------- | ------------- |
| read a page                   | `getTrades` (`marketdata:read` · none; `22`:4724; matrix.yaml:947–951 executed) | `200`    | `200`    | `200`                                                                        | `200`                                   | C15, C32, C61 |
| subscribe the tape            | WS `trades.{symbol}` (a read; `23`:748)                                         | `sub_ok` | `sub_ok` | `sub_ok`                                                                     | `sub_ok`                                | C01, C61      |
| read metrics                  | `getMetrics` (`marketdata:read` · none; matrix.yaml:903–909 `not_mounted`)      | blocked  | blocked  | blocked                                                                      | blocked                                 | C55           |
| pause, inspect, filter, scale | none (client state)                                                             | yes      | yes      | yes (D02 S23: "pause, the display filters and Big only still work", D02:142) | yes                                     | C04, C42, C61 |
| set threshold, set clustering | no route at the base (D05-G-2); PROPOSED `settings:write` (D02 S23)             | blocked  | blocked  | T2 "Your role can't change settings." (`d02.13.cp24`)                        | T2 "Read-only while viewing as {user}." | C20, C21, C61 |

Unauthenticated: `401` on `getTrades` (matrix.yaml:947–951 outcomes; `api/trades.py`:184–185). A caller without `marketdata:read` is `403`
(`api/trades.py`:186–187); that leg and `TM` AC16 are E22-X02's (section 8).

**2.2 Action by state.** A cell names the cases that cover it. **n/a**: no such cell. **same**: no source states a different answer, so the streaming
column covers it. **none**: no source states the result; the case asserts the wire only and an OQ row asks.

| Action                 | streaming | high rate | paused | ring full | disconnected | stale | backfill | partial | empty / thin | filtered-empty | capped | clustered |
| ---------------------- | --------- | --------- | ------ | --------- | ------------ | ----- | -------- | ------- | ------------ | -------------- | ------ | --------- |
| subscribe / read       | C01, C15  | C02       | C04    | C05       | C06          | C11   | C07      | C09     | C10          | n/a            | C19    | C32       |
| pause / resume         | C04       | C03       | C04    | C05       | C06 (T2)     | C11   | same     | same    | same         | same           | same   | C35       |
| inspect a row / bubble | C13, C30  | C03       | C13    | same      | same         | same  | same     | same    | same         | n/a            | C17    | C33       |
| filter / columns       | C42, C43  | same      | C42    | same      | same         | same  | same     | same    | C44          | C44            | same   | same      |
| set threshold          | C16, C18  | n/a       | none   | n/a       | C06 (T2)     | same  | n/a      | C25     | same         | same           | C19    | same      |
| set clustering         | C35, C38  | same      | C35    | same      | C06 (T2)     | same  | n/a      | same    | same         | same           | same   | C35       |
| symbol switch          | C65       | same      | C65    | same      | same         | same  | same     | same    | same         | same           | same   | same      |

## 3. Cases by user story

Each case starts from a fresh seed of the fixtures it names (section 6) and runs as OWNER unless its header says otherwise. A case is: preconditions,
steps, expected, source. A tester who did not write the plan can run any case from sections 4 to 6 alone. `K(pre)` and `K(post)` are the counter reads of
section 5. "The publisher" is the `trades.{symbol}` publisher (`services/api/candleviewer/ws/trades_publish.py`, cited `TP`); "the route" is `getTrades`
(`services/api/candleviewer/api/trades.py`, cited `TR`). A UI case is blocked on its story until that story is merged (section 7); its wire half runs first.

### 3.1 US-BIG-001 Time and sales tape (Must)

**E22-Q01-C01 The tape renders each print with ms time, price, size and the feed's taker side, newest first [R]** (`integration`, `e2e`; E-REPLAY ·
streaming; mirrors US-BIG-001/1, S01.1; UI half blocked on E22-S01 #714)

- Pre: FX-CLEAN BTCUSDT replayed (section 6); the panel open on BTCUSDT at compact density.
- Steps: subscribe `trades.BTCUSDT` with no options and read `sub_ok` and the `snap`; read every later `d` for 60 s; read the tape's top 25 rows and their
  accessible names; compare each row's side with the fixture frame's `S` for the same trade id.
- Expected: `sub_ok.effective` carries `cluster_window_ms` 0, `cluster_tolerance_ticks` 0, `big_trade_threshold` and `big_trade_mode`, defaults included
  (`23`:787, `23`:790); the `snap` holds at most 200 items, oldest first (`23`:748; `TP`:34–35, `TP`:87); each item has `ts_ms`, `price`, `size` and `side`
  (`23`:2845) and `side` equals the fixture's `S` lower-cased, the taker side (`22` `PublicTrade.side`, `22`:19626–19631; `BYB/2026-10-05/README.trades.md`:4–5).
  Each row shows the Time cell as `HH:MM:SS.mmm`, then Price, Size, Notional and Side in D02's column order (column headers "Time" · "Price" · "Size" ·
  "Notional" · "Side", `d02.13.cp16`), newest at the top; the Side word and its glyph come from the item's `side`, never from price movement
  (S01.1 "never inferred client-side"). A row's accessible name follows the deck template, side first ("Sell, 18.75 BTC at 64,012.0, 1.2M, whale,
  14:02:11.208" is the drawn example, `d02.13.cp26`; template D02:112).
- Source: the `snap` and `d` items > the fixture's `S` > the row names (presentation). 2nd: `cv_ws_frames_emitted_total{topic="trades"}` rises
  (`services/api/candleviewer/ws/metrics.py`:157–161, cited `WM`).

**E22-Q01-C02 At 2 000 prints/s the frames coalesce and every print is accounted for [R]** (`integration`; E-REPLAY with FX-G4 · high rate; mirrors
US-BIG-001/2 (wire half), S01.2 (wire half), T02.5; blocked on FX-G4, E22-Q03 #753)

- Pre: a synthetic sequence of 120 000 BTCUSDT prints at 2 000 prints/s for 60 s, generated from a stated seed by the burst harness (FX-G4), with every
  trade id unique and every price on tick; `K(pre)` read.
- Steps: subscribe `trades.BTCUSDT` with no options; drive the sequence; collect every `snap` and `d` for the run plus 1 s; count items and sum `dropped`.
- Expected: frames go out at most one per 100 ms window per option set (`TP`:22–23, `TP`:84–85); a frame that appended more than one source batch has
  `coalesced: true` and `coalesced_count` > 1 (`23`:792; `TP`:27–29, `TP`:459); items are appended, never merged (`23`:792); the count of items received
  plus the summed `dropped` equals the prints injected after the snapshot (`23`:789, `23`:2868–2871: "never silent"); with no `min_size`, any `dropped`
  is `overflow` shedding (`TP`:25–27, `TP`:105–108), which this rate does not reach (500 per window budget, 5 000 pending).
- Source: the frames > the injected count. 2nd: `cv_ws_tape_frames_coalesced_total` rises (`WM`:170–173; `TP`:487–488);
  `cv_ws_tape_prints_dropped_total{reason="overflow"}` delta equals the summed `dropped` (`WM`:162–169; `TP`:483–486).
- Note: the ticket's note that "a replayed burst is a valid test of the live path" does not hold at the base: the replay injector publishes trades into a
  session's own bus namespace (`services/api/candleviewer/replay/injector.py`:75–77, :285–287) and the publisher serves live subscriptions only
  (`TP`:376–379, `TP`:608–609), so FX-G4 feeds the live path (section 4, OQ-3).

**E22-Q01-C03 At 2 000 prints/s the tape shows the coalescing factor and no row vanishes silently** (`e2e`; E-REPLAY with FX-G4 · high rate; mirrors
US-BIG-001/2 (UI half), S01.2 (UI half); blocked on E22-S01 #714 and FX-G4)

- Pre: as C02; the panel open and live.
- Steps: watch the panel for 60 s; read the readout; count the DOM rows of the log; pause, scroll the ring, resume.
- Expected: the readout shows the rate and the per-frame factor ("2 010 /s (1 s) · 33 /frame" is the drawn form, `d02.13.cp03`; digits per
  section 0); the log holds at most 60 rows including dividers (`14`:1275; D05:226); no visible stutter; while paused, the ring holds every print the frames
  delivered, up to the ring size (`14`:1275 "ring buffer of 10 000 prints"), and a print missing from the ring that no `dropped` counted is P0 (section 7.1).
  Measured fps and the 55 fps floor are E22-Q03's (`11`:2189; D05:225).
- Source: C02's frames > the ring count while paused > the readout (presentation). 2nd: as C02.

**E22-Q01-C04 Pause freezes the tape, buffering continues, and resume says how many were buffered [R]** (`e2e`; E-REPLAY · paused; mirrors
US-BIG-001/3, S01.3; D02 S2–S5; blocked on E22-S01 #714, FX-G4 and FX-G3)

- Pre: FX-CLEAN BTCUSDT prints delivered at 50 prints/s through FX-G4 (FX-CLEAN alone averages about 0.05 prints/s, section 6); the panel live.
- Steps: (a) rest the pointer 150 ms over the list, then move 1 px; read the chip; leave the list. (b) press `P` with panel focus; wait 60 s; read the chip;
  press `P`. (c) count the rows inserted under the divider; read the announcement region once.
- Expected: (a) the list freezes, the chip reads "Paused — {n} prints buffered" with n rising as prints arrive ("Paused — 412 prints buffered",
  `d02.13.cp04`; D02 P1, P2); leaving resumes. (b) the hard pause never resumes on its own (D02 P6, P7; S4 testability, D02:123); the pause button has
  `aria-pressed="true"` (D02 S4). (c) the buffered prints are inserted under a `presentation` divider "— {n} prints while paused —" (`d02.13.cp09`,
  deck:105; D02 P12), never replayed; the inserted count equals the chip's last count (D02 S5 testability); "Resumed, {n} prints inserted" is said once
  (`d02.13.cp23`; AN-03, D05:404).
- Source: the frames' item count while paused > the divider and chip counts (presentation). 2nd: none (client state; `tape.paused` † and `tape.resumed` †,
  section 10).

**E22-Q01-C05 A paused tape whose ring fills keeps the window and counts what it did not keep [F]** (`e2e`; E-REPLAY with FX-G4 · ring full; mirrors
D02 S22, P14; edge of US-BIG-001/3; blocked on E22-S01 #714 (D02-G7, PROPOSED policy) and FX-G4)

- Pre: FX-G4 at 2 000 prints/s; the ring at its 10 000-print default (`14`:1275).
- Steps: hard-pause; keep the burst on for 6 s; read the chip; resume; read the divider and the announcement.
- Expected: the chip flips to "Paused — buffer full · 10 000 kept" (`d02.13.cp04`) and the visible window never moves; on resume the divider reads
  "— 12 000 prints while paused · 2 000 not kept —" (`d02.13.cp09`) and "Resumed, 10 000 prints inserted, 2 000 not kept" is said once
  (`d02.13.cp23`; AN-04, D05:405); a focused row is never evicted (D04 FP-09, D04:359). The eviction policy is PROPOSED (D02-G7, D02:485): the
  case asserts the counts, not the order of eviction, until E22-S01 closes D02-G7.
- Source: the injected count (12 000) > the divider and chip (presentation). 2nd: the client `ringbuffer_trimmed` event † (section 10).

**E22-Q01-C06 A dropped WebSocket shows the disconnected state, then the resubscribe reseeds without duplicates [R] [F]** (`e2e`, `integration`; E-REPLAY ·
disconnected; mirrors S01.4; D02 S10; edge "WS disconnect"; UI half blocked on E22-S01 #714)

- Pre: FX-CLEAN BTCUSDT live in the panel for at least 200 prints.
- Steps: drop the socket (close the transport from the test harness); read the panel; press `P`; restore the socket; read the new `snap`; compare the ids
  in the tape before and after.
- Expected: the in-panel strip reads "Disconnected — last data {mm:ss}" ("Disconnected — last data 00:12", `d02.04.s10`) and the feed chip
  "Offline" (`d02.13.cp05`); rows freeze under the scrim; the pause button carries `aria-disabled="true"` with the reason "Nothing to pause while
  disconnected." (`d02.13.cp24`; PROPOSED, the E17-D01 §7 owner's); on resubscribe the `snap` carries the last 200 items (`23`:748; `TP`:87) and
  the tape shows each trade id once (S01.4 "without duplicating rows"; D02 S16 dedupes by `id` on the structured path, D02:135).
- Source: the `snap` ids > the row ids (presentation). 2nd: none (a read); the feed sentences are `d05.07.feed` (deck:464, named elsewhere), asserted as one
  announcement per episode, not by text.

**E22-Q01-C07 Reconnect backfill marks the gap, loads the missed prints once, and survives a disconnect mid-burst [F]** (`e2e`, `integration`;
E-REPLAY · backfill; mirrors D02 S15, S16; edge "WS disconnect mid-burst"; blocked on E22-S01 #714; the mid-burst leg also on FX-G4)

- Pre: FX-RECON: `BYB/2026-10-05/ws/publicTrade_BTCUSDT.jsonl` (frames 1–2 live, reconnect, frame 3 live) with `rest/recent_trade_BTCUSDT.json` (ids 0001,
  0003–0007; 0001, 0003, 0007 overlap live, 0004–0006 fill the gap; `BYB/2026-10-05/README.trades.md`:6–7); separately `reconnect_publicTrade_ETHUSDT.jsonl`
  (`BYB/README.md`:31).
- Steps: replay frames 1–2; drop the socket for 8 s (D02 S15 testability); replay frame 3; press Load missed prints; count rows and ids. Repeat with FX-G4
  at 2 000 prints/s, dropping the socket mid-burst.
- Expected: a `presentation` divider "— gap {t1} → {t2} —" (`d02.13.cp09`), the chip "Reconstructed after gap" (`d02.13.cp05`) and the
  button "Load missed prints" (`d02.13.cp10`); after the REST load the missed prints sit under the divider "— {n} prints while disconnected —" and
  "{n} missed prints loaded" is said once (`d02.13.cp23`); each id appears once (ids 0004–0006 inserted, 0001, 0003, 0007 not repeated). The
  REST page is the hot tape only, the last 1 000 prints (`TR`:3–4; `22`:4662–4664): a gap longer than that is not fully loadable, and the case asserts what
  the page returns, never more. Mid-burst: the resubscribe `snap` holds the last 200 items and no id repeats across `snap` and the later `d` frames.
- Source: the REST page and the `snap` ids > the divider count (presentation). 2nd: `cv_ws_frames_emitted_total{topic="trades"}` (`WM`:157–161).

**E22-Q01-C08 A lost bus window re-snapshots the tape as `upstream_desync`, with no duplicate and no silent gap [F]** (`integration`; E-REPLAY with FX-G4 ·
sequence gap; edge "sequence gap"; blocked on FX-G4 and FX-G6)

- Pre: a live `trades.BTCUSDT` subscription; a synthetic trade sequence with a 150-print hole (the shape of the synthetic `CONF` gap tape,
  `CONF/README.md`:13; no recorded trade-gap fixture exists, FX-G6).
- Steps: drive the sequence so the server loses the hole; read the frames.
- Expected: on the bus's overflow marker the publisher catches each held symbol up from the hot tape and re-snapshots every live `trades` subscription with
  `meta.reason: "upstream_desync"` (`TP`:20–21, `TP`:525–534; `23`:1197); the client replaces its state from the `snap` and shows each id once; the tape
  marks the seam as D02 S15 draws it. A print the hot tape still holds reappears; prints older than the hot tape are not claimed.
- Source: the `snap` reason and ids > the tape (presentation). 2nd: `cv_ws_resync_total{reason="upstream_desync"}` rises by one per re-snapshotted
  subscription (`services/api/candleviewer/ws/sequencing.py`:112, :189–197, :1181–1182).

**E22-Q01-C09 Partial history names the first available timestamp [F]** (`e2e`; E-REPLAY · partial; mirrors S01.5, global AC #7; D02 S14; blocked on
E22-S01 #714 and OQ-4)

- Pre: FX-NEWLIST, the synthetic newly listed symbol recorded from 11:17Z (`CONF/README.md`:15); the panel open on it.
- Steps: scroll the tape past its oldest row.
- Expected: a `presentation` divider at the seam "— No history before {HH:MM:SS}. Recording started then. —" (`d02.13.cp09`) whose time is the
  first available timestamp (`11`:48; `30`:387). What that timestamp names, the hot tape's head or the recording start, is not stated (OQ-4); the case
  asserts that the divider's time equals the oldest print the panel can reach by REST (`getTrades` with no `from`; `TR`:3–4), and is blocked on OQ-4 for the
  recording start.
- Source: the oldest REST item's `ts` > the divider (presentation). 2nd: none (a read).

**E22-Q01-C10 Loading, an empty snapshot and a thin symbol read as states, never as a broken panel** (`e2e`; E-REPLAY · loading, empty, thin; mirrors
D02 S11, S12; edge "thin-book / low-volume symbol"; blocked on E22-S01 #714)

- Pre: (a) the snapshot delayed 3 s (D02 S11 testability, D02:130); (b) a symbol with no prints after `from` (D02 S12); (c) FX-THIN, the synthetic thin
  ETHUSDT tape, most 1 m intervals empty (`CONF/README.md`:14).
- Steps: open the panel in each; read the header readout and the log.
- Expected: (a) no placeholder rows; the readout and the empty line read "Loading…" (`d02.13.cp03`; `d02.13.cp11`); (b) "No prints yet ·
  last print {HH:MM:SS}" (`d02.13.cp11`) with the time when history knows one; (c) the readout falls to "0 /s · quiet" between prints (`d02.13.cp03`) and no
  stale chip shows while the transport is up and prints are merely rare unless the trades age passes T1 (C11).
- Source: the `snap` (empty `trades` array, `23`:2838) > the panel text (presentation). 2nd: none (a read).

**E22-Q01-C11 A stale feed keeps the rows and shows the stale chip beside any pause chip** (`e2e`; E-REPLAY · stale; mirrors D02 S8, S9; blocked on
E22-S01 #714)

- Pre: FX-CLEAN live; the transport up.
- Steps: stop the trades fixture for 12 s, then 30 s (D02 S8, S9 testability); pause during the stale span.
- Expected: rows are kept, never re-sorted; the chip reads "Stale 12s", then the strong "Stale 30s" (`d02.13.cp05`); with a pause, both chips show,
  never merged (D02 P10); one assertive announcement at T2, not one per symbol (D02 S9 testability, D02:128).
- Source: the absence of `d` frames > the chips (presentation). 2nd: none.

**E22-Q01-C12 Under the fallback ladder every print stays represented** (`e2e`; E-REPLAY with FX-G4 · high rate, rung 3; mirrors D02 S7, S19; blocked on
E22-S01 #714 and FX-G4)

- Pre: FX-G4 at 2 000 prints/s with the harness's rung forced (D02 S19 testability, D02:138); separately `throttle_multiplier` 4 on the gateway fixture
  (D02 S7, D02:126).
- Steps: read the log; pause; read again.
- Expected: tier-0 prints of one frame collapse into one row "{n} small prints · Σ {size}" with the badge "compressed" ("27 small prints · Σ 1.9",
  `d02.13.cp15`); tier 1 and 2 rows are never compressed; a pause expands the compressed rows; the ring is intact (D02 D12, D02:284). S7 shows no
  tape chip; every print is a raw row or a merged row with its count (D02:126).
- Source: C02's item count > the expanded row count. 2nd: none.

**E22-Q01-C13 Clicking or focusing a row pauses first, then selects it, and the crosshair jumps to its time** (`e2e`; E-REPLAY · streaming; mirrors
D02 S6, D04 FP-01; `14`:1272; blocked on E22-S01 #714, FX-G4 and FX-G3)

- Pre: FX-CLEAN at 500 prints/s (FX-G4) with a chart on BTCUSDT synced.
- Steps: click row 5; read the chip, the selection and the crosshair time; press `Esc`.
- Expected: the Paused chip appears before the selection, in the same frame; the crosshair time equals the row's time (D02 S6 testability, D02:125); `Esc`
  returns to live with focus on the grid and no row active (D04 FP-05, D04:355).
- Source: the row's `ts_ms` > the crosshair readout (presentation). 2nd: `tape.print_clicked` † (section 10).

**E22-Q01-C14 A row's name, tier and side read in words and glyphs, not colour alone** (`a11y`, `e2e`; E-REPLAY with FX-G1 · streaming; mirrors global AC
#3, D02 §3, §10; blocked on E22-S01 #714 and FX-G1)

- Pre: a tier-0, a tier-1 and a tier-2 print in the tape (FX-G1 gives prints at and above the threshold).
- Steps: read each row's accessible name; switch the OS to greyscale; read the rows.
- Expected: tier 1 shows the glyph `●` after Size and weight 500; tier 2 the glyph `◆`, weight 700 and a lighter band (D05:275–281, the copy of D02:101–112);
  the name carries the tier word only on tiers 1–2 ("big" / "whale") and the side first (D05:286); in greyscale every tier stays distinct by weight, glyph and
  edge mark (D02 §10).
- Source: the item's `is_big_trade` and side > the name (presentation). 2nd: none.

### 3.2 US-BIG-002 Big-trade threshold highlighting (Must)

At the base no threshold can be set: the publisher and the route take their config from `lambda _symbol: BigTradeConfig()` (`TP`:204; `TR`:158), the app
wiring passes none (`services/api/candleviewer/app.py`:1809–1816), and no text connects a saved threshold to the engine (D05-G-2, D05:215, D05:535). Every
symbol therefore runs mode `notional` at 250 000 USDT (`bigtrade_models.py`:30–31; `23`:790). Every case that sets a mode or a value is **blocked on E22-S02
(#715) and the `22` owner** (BQ-08); the default-threshold legs run today.

**E22-Q01-C15 The effective threshold is echoed on every surface, defaults included [R]** (`contract`, `integration`; E-REPLAY and E-DEMO · streaming;
mirrors US-BIG-002 NFR "evaluation backend-side", T01.2 (echo half), the strip's always-visible readout (D02 D18))

- Pre: FX-CLEAN BTCUSDT (E-REPLAY), or the demo profile's live public stream (E-DEMO).
- Steps: subscribe `trades.BTCUSDT`; read `sub_ok.effective`, the `snap` and three `d` frames; read `getTrades?symbol=BTCUSDT` `meta`; read the strip.
- Expected: `sub_ok.effective.big_trade_threshold` is "250000" and `big_trade_mode` "notional" (`23`:790; `bigtrade_models.py`:30–31); every `TradesBatch`
  carries `big_trade_threshold` (`23`:2838, `23`:2873–2875); `TradesPageMeta` carries the same `big_trade_threshold` and `big_trade_mode` (`22`
  `TradesPageMeta`, both required); the strip reads "eff. 250k USDT" (`d02.13.cp06`) whenever the panel is open (D02 D18: "the effective readout is always
  visible"). A binary subscriber keeps the value from `sub_ok.effective` and the latest structured frame (`23`:2875).
- Source: the three wire values, equal > the strip (presentation). 2nd: none (a read).

**E22-Q01-C16 At 250 000 USDT notional the qualifying prints carry the flag, the marker and the size label [R]** (`integration`, `e2e`; E-REPLAY with FX-G1 ·
streaming; mirrors US-BIG-002/1, S02.1, T01.1; UI half blocked on E22-S02 #715 and E22-S01 #714; the input on FX-G1)

- Pre: the default threshold (250 000 USDT notional, so no threshold is set); FX-G1, a print sequence with notionals 249 999.9, 250 000 and 250 000.1 USDT
  among ordinary prints. **No recorded trade fixture reaches 250 000 USDT** (BQ-11 rider U5, scanned for this plan over every print, notional = price ×
  size): `clean_publicTrade_BTCUSDT.jsonl` maximum 31 562.70 (542 prints; `GB/README.md`:17–18 says the same), `clean_publicTrade_ETHUSDT.jsonl`
  1 025.02 (519), `clean_publicTrade_SOLUSDT.jsonl` 72.36 (556), `recorded_publicTrade_BTCUSDT.jsonl` 8 274.85 (46), `reconnect_publicTrade_ETHUSDT.jsonl`
  207.70 (30), `publicTrade_BTCUSDT.jsonl` and `rest/recent_trade_BTCUSDT.json` 94 681.50 (all under `BYB/2026-10-05/`).
- Steps: subscribe `trades.BTCUSDT`; drive FX-G1; read each item's `is_big_trade`; read `getTrades` for the same window; read the tape rows.
- Expected: `is_big_trade` is true for 250 000 and 250 000.1 and false for 249 999.9: the engine flags `measure >= effective` (`bigtrade.py`:171–173), and
  notional is price × qty (`bigtrade.py`:10, :158–159); REST gives the same flags for the same ids (`22` `getTrades`: "the two agree on the flagged prints");
  each flagged row shows the tier-1 glyph `●` after Size, weight 500 and a 2 px side-hue accent (D05:275–279), and the Notional cell its size label
  ("1.2M" form, `d02.13.cp21`). On the recorded window at the default the flagged set is empty, which is itself the parity result (`GB/summary.json` case
  `notional_250000`, `flagged` 0, summary.json:20–31; T01.1's independent query is the golden's DuckDB recompute, `GB/README.md`:30–32, white-box evidence).
- Source: the WS and REST flags per id > the golden counts > the rows (presentation). 2nd: `bigtrade_flagged_total{mode="notional"}` rises by 2
  (`services/api/candleviewer/orderflow/bigtrade_metrics.py`:26–28, cited `BM`).

**E22-Q01-C17 The highlight follows the server's flag, never a client comparison of notional against the threshold** (`e2e`; E-REPLAY with FX-G1 ·
capped; mirrors S02.1 (second line); blocked on E22-S02 #715 and the `22` owner (no threshold can be set; D05-G-2))

- Pre: the threshold set to 30 000 USDT notional on FX-DENSE (the D02 S18 setup, D02:137), so the cap engages and the effective threshold rises above the
  configured one.
- Steps: read the strip's effective value; read the flags of prints whose notional lies between the configured and the effective threshold; read their rows.
- Expected: prints between 30 000 and the effective threshold carry `is_big_trade: false` (`bigtrade.py`:191–193: the effective threshold is the base raised
  to the window's p80 while capped) and their rows stay tier 0; a client that compared notional with the configured 30 000 would highlight them, so any such
  row highlighted is a failure (P1, section 7.1). Prints at or above the effective threshold stay flagged and keep flowing ("never suppresses",
  `24`:598).
- Source: the item flags > the rows (presentation). 2nd: none.

**E22-Q01-C18 Percentile mode shows the effective absolute threshold, marked estimated, and updates it as the distribution moves** (`integration`, `e2e`;
E-REPLAY · streaming; mirrors US-BIG-002/2, S02.2, T01.2; blocked on E22-S02 #715 and the `22` owner)

- Pre: BTCUSDT set to percentile 99 over a 1 h window; FX-GOLD replayed (542 prints, 2.99 h).
- Steps: subscribe; read `sub_ok.effective`, then each frame's `big_trade_threshold` across the window; read the strip.
- Expected: before the symbol's tape opens the echo is provisional and carries the notional default, and the first `snap` carries the engine's threshold
  (`23`:790; `TP`:271–284); the threshold changes at most once per 5 s of print time (`LIM`:38 `THRESHOLD_REFRESH_US`; `bigtrade.py`:163–168) and every frame
  carries the current value (`23`:790); the flagged count over the window is 24 (`GB/summary.json` case `percentile_99_1h`, `flagged` 24); the strip reads
  "eff. {value} USDT" with the CMP-227 chip "(estimated)" ("eff. 220k USDT" and "(estimated)" are the drawn forms, `d02.13.cp06`), whose name is
  "Estimated, Big trade" (D02:242, not in the deck). The estimator's rank error within 1 % of an exact quantile (T01.2; `24`:599) is the golden's white-box check
  (`GB/README.md`:33–34), not a black-box value.
- Source: the frames' threshold sequence > the golden count > the strip (presentation). 2nd: none (a read).

**E22-Q01-C19 A threshold that flags more than 20 % of prints raises a warning and caps the highlight [F]** (`integration`, `e2e`; E-REPLAY · capped; mirrors
US-BIG-002/3, S02.3, T01.5; D02 S18; blocked on E22-S02 #715 and the `22` owner)

- Pre: notional 30 000 USDT on FX-DENSE (synthetic, `CONF/README.md`:12; D02 S18 testability "23.5 %", D02:137).
- Steps: subscribe; read the frames' `big_trade_threshold` before and after the cap; read the warning strip and its actions; choose Apply, then repeat and
  choose Keep.
- Expected: the cap engages only with at least 20 samples and more than 20 % flagged (`LIM`:39–41; `bigtrade.py`:185–190), and in percentile mode only above
  p80 (`bigtrade.py`:106–109); the effective threshold rises to the window's p80 (`24`:598); the strip reads "Threshold flags {p} % of prints — raised to {v}
  USDT (the window's p80); prints between {t} and {v} are not flagged" (`d02.13.cp12`) with the actions "Apply {v}" and "Keep {t}" (`d02.13.cp10`) and the
  chip "capped" (`d02.13.cp06`); flagged prints stay tier 1 (D05:282). On the golden window the percentile-99 case records exactly one cap entry
  (`GB/summary.json` case `percentile_99_1h`).
- Source: the threshold step in the frames > the strip (presentation). 2nd: the engine's threshold-too-low counter rises once per cap entry
  (`BM`:40–42).

**E22-Q01-C20 Each symbol restores its own threshold across a switch, a reload and a new session** (`e2e`; E-REPLAY · streaming; mirrors S02.4; blocked on
E22-S02 #715, the `22` owner (D05-G-2, D02 G4) and E15)

- Pre: BTCUSDT set to 250 000 notional, ETHUSDT to 100 000 notional.
- Steps: switch symbols back and forth; reload; sign out and in; read each symbol's strip and `sub_ok.effective`.
- Expected: each symbol restores its own value without re-entry; the keys are the PROPOSED `bigtrade.threshold_mode` and `bigtrade.threshold_value`, one
  row per key per user with the symbol inside the value (D05:203–208); writes debounced 500 ms and at most 200 symbols per user (D05:214; `LIM`:32). The
  effective value shown comes from `sub_ok.effective` and the frames, never from the saved value (D05:216).
- Source: `sub_ok.effective` per symbol > the strip. 2nd: one `settings.change` audit record per write (D05:214), blocked with the route.

**E22-Q01-C21 A negative, non-numeric or out-of-range threshold is refused inline and changes nothing [F]** (`e2e`; E-REPLAY · streaming; mirrors S02.5;
edge "threshold percentile 0 and 100"; blocked on E22-S02 #715 and D05-G-4)

- Pre: BTCUSDT at notional 250 000.
- Steps: enter -1, then "abc", then (percentile mode) 0 and 100; read the field's message; watch the WS for any `sub` or `ctl`.
- Expected: an inline validation message, the previous value retained, and no subscription change sent (no `sub`, `ctl` or `unsub` frame; S02.5). The
  engine's bounds: a value must be finite and at least 0, and a percentile strictly between 0 and 100 (`bigtrade_models.py`:40–41,
  `0 < self.value < 100`). The deck's PROPOSED message says "Enter a value of 0 or more; a percentile is 0 to 100." (`d05.05.range`; D05:302), which admits
  0 and 100: a C-row (C-PCT, section 10). The case asserts the behaviour (0 and 100 refused in percentile mode), not the text.
- Source: the WS frame log (no change) > the field state (presentation). 2nd: none.

**E22-Q01-C22 The same trade id delivered twice after a resubscribe counts once** (`integration`; E-REPLAY · backfill; mirrors T01.6)

- Pre: FX-RECON BTCUSDT: live frames 1–2, reconnect, frame 3, with the REST page whose ids 0001, 0003 and 0007 overlap live (`BYB/2026-10-05/README.trades.md`:6–7).
- Steps: replay the sequence; read every `snap` and `d` and the `getTrades` page.
- Expected: each trade id appears once in the tape's history and once on the page; the engine skips an id it has seen ("duplicate after resubscribe: counted
  once everywhere", `bigtrade.py`:147–148), so thresholds, clusters and counters count it once.
- Source: the item ids > `BM` `bigtrade_prints_evaluated_total` delta equals the distinct ids (`BM`:23–25). 2nd: as source.

**E22-Q01-C23 A threshold of 0 flags every print until the too-low guard caps it** (`integration`; E-REPLAY · capped; edge "threshold = 0"; blocked on
E22-S02 #715 and the `22` owner)

- Pre: BTCUSDT at notional 0 on FX-CLEAN.
- Steps: subscribe; read the first 19 flagged items, then the 20th sample's refresh.
- Expected: 0 is a valid value (`bigtrade_models.py`:40); every print is flagged (`>=`, `bigtrade.py`:171); once the window holds at least 20 samples with
  more than 20 % flagged, the cap engages at the next 5 s refresh and C19's strip shows (`LIM`:38–41; `bigtrade.py`:185–193).
- Source: the item flags and the threshold step > the strip. 2nd: as C19.

**E22-Q01-C24 A threshold above every print flags nothing, and the golden parity holds [R]** (`integration`, `contract`; E-REPLAY · streaming; edge
"threshold above every print"; mirrors T01.1 (empty-set half), T04.1)

- Pre: FX-GOLD (the 542-print BTCUSDT window, `GB/README.md`:10–15) at the default 250 000 USDT.
- Steps: subscribe and replay; read `getTrades` pages over the window; count `is_big_trade: true`.
- Expected: zero flagged items on both surfaces (`GB/summary.json` case `notional_250000`, `flagged` 0); the tape shows no tier-1 or tier-2 row. T04.1's
  independent recomputation is `services/api/tests/unit/orderflow/test_bigtrade_golden_parity.py` (`GB/README.md`:6), cited as white-box evidence: its
  green run on the READY sha is attached, never re-run as a black-box step.
- Source: the item flags > the golden count. 2nd: `BM` `bigtrade_flagged_total` unchanged.

**E22-Q01-C25 Percentile mode with less history than its window flags nothing until the estimate exists** (`integration`; E-REPLAY · partial; edge
"percentile with less recorded history than the window"; blocked on E22-S02 #715 and the `22` owner)

- Pre: BTCUSDT at percentile 99 over 1 h; FX-NEWLIST (synthetic, 20 000 prints from 11:17Z, `CONF/README.md`:15).
- Steps: subscribe at the first print; read the echo, the flags and the threshold until the window holds an estimate; reconfigure the window once.
- Expected: the percentile threshold has no value until the window holds an estimate (`bigtrade.py`:110, :179–181), so nothing is flagged (`bigtrade.py`:169,
  :171: `_effective is not None`); the echo is provisional with the notional default until the tape opens (`TP`:271–284); a reconfigure restarts the warm-up
  (`bigtrade.py`:115–120); the window is bounded 60 s to 24 h (`LIM`:35–36). REST reads only the hot tape, the last 1 000 prints (`TR`:3–4), so a 1 h window
  is asserted on WS only.
- Source: the frames' threshold and flags. 2nd: none.

### 3.3 US-BIG-003 Bubble plotting on the chart (Must)

Every case here is **blocked on E22-S03 (#716)** (no bubble layer at the base, D05:57) and, for its input, on FX-G1 (no recorded print reaches the default
threshold, C16). A bubble is read through its DOM-mirror node and its tooltip, never its pixels (section 0).

**E22-Q01-C26 Each qualifying print draws at its price and time, sized by notional, side by shape and colour** (`e2e`; E-REPLAY with FX-G1 · streaming;
mirrors US-BIG-003/1, S03.1)

- Pre: FX-G1 with flagged prints at 1×, 1.5×, 2×, 3× and 4× the threshold, buy and sell; a chart on BTCUSDT with the overlay on.
- Steps: read each mirror node's accessible name and tooltip; read the legend row; count mirror nodes against flagged items.
- Expected: one mirror node per flagged print, none for an unflagged one (only qualifying prints are drawn, D02:249); a single mark's name follows
  "Big sell, 1,200,000 USDT, 64,012.0, 14:02:11" (`d03.04.r01`) and its tooltip "Big sell · 1.2M USDT · 64,012.0 · 14:02:11.208" (`d02.13.cp19`), with the
  item's side, price and time; the legend row reads "Big trades · area-linear · 250k → 3 px · 1M → 24 px · >1M labelled" (`d02.13.cp20`). The radius law
  (area-linear 3.0 / 10.2 / 14.1 / 19.7 / 24.0 px at 1× to 4×, D02:249) is the engine's and is E22-S03's unit test and E22-D06's design QA, never read off
  pixels here. Above 4× a mark carries a label ("1.2M", "18.9M", `d02.13.cp21`).
- Source: the item flags, prices and times > the mirror names (presentation). 2nd: none.

**E22-Q01-C27 Log scaling stops extreme prints dominating, and the legend says so** (`e2e`; E-REPLAY with FX-G1 · streaming; mirrors US-BIG-003/2, S03.2)

- Pre: as C26, plus one print at 40× the threshold.
- Steps: switch the scale select to log; read the legend row.
- Expected: the legend reads "Big trades · log · 250k → 3 px · 1M → 24 px · >1M labelled" (`d03.05.r01`); the strip's scale select shows "log"
  (`d02.13.cp13`). No settings key holds the scale (D05-G-3), so the choice is not asserted across a reload.
- Source: the legend (presentation). 2nd: none.

**E22-Q01-C28 Many coincident qualifying prints draw one bubble with a count badge** (`e2e`; E-REPLAY with FX-G1 · clustered; mirrors US-BIG-003/3, S03.3;
also blocked on E22-S04 #717)

- Pre: clustering at 250 ms / 1 tick (blocked on the clustering control, C35); FX-G1 with seven flagged sell prints at one price within 250 ms.
- Steps: read the mirror nodes and the tooltip.
- Expected: one mirror node "Cluster of 7, 1,900,000 USDT, sell, 14:02:11, estimated" (`d03.04.r02`; the drawn example), not seven; the tooltip "Cluster ×7 ·
  1.9M USDT · Sell · 7 prints within 250 ms / 1 tick · first print 14:02:11.208 · bar 14:02 · (estimated)" (`d02.13.cp19`); the wire carries one item with
  `cluster_size` 7 (`23`:791).
- Source: the item's `cluster_size` > the mirror and tooltip (presentation). 2nd: `BM` `bigtrade_clusters_emitted_total` rises (`BM`:29–31).

**E22-Q01-C29 Past the density ceiling the LOD ladder sheds smaller marks and says so, without changing which prints are big [F]** (`e2e`; E-REPLAY with FX-G4 ·
high rate; mirrors S03.4; also blocked on E22-K01 #608)

- Pre: FX-G4 with more flagged prints in view than the LOD trigger (≤ 500 visible instances, `26` §3.6 via D05:229; the engine's hard cap 5 000, `LIM`:30).
- Steps: zoom out; read the corner badge and the mirror count; compare flagged ids on the wire before and after the zoom.
- Expected: the corner badge "Smaller prints hidden at this zoom" (`d02.13.cp22`); the set of flagged item ids is unchanged by the zoom ("shedding never
  changes which prints are big", D02:253). The 500 and 5 000 figures are two layers (D05:233); the ≥ 55 fps hold is E22-Q03's.
- Source: the item flags (unchanged) > the badge (presentation). 2nd: none.

**E22-Q01-C30 Hovering a bubble or focusing its mirror gives the same details to the eye and to a screen reader [R]** (`e2e`, `a11y`; E-REPLAY with FX-G1 ·
streaming; mirrors S03.5, global AC #3)

- Pre: as C26 and C28.
- Steps: hover a single mark and a cluster; Tab to a mirror node; press `Enter`.
- Expected: the tooltip shows time, price, size, notional, side and, for a cluster, the constituent count (`d02.13.cp19`); the mirror name carries the same
  facts in words (`d03.04.r01`, `d03.04.r02`); `Enter` on a mirror node locates the print and moves focus to the plot (D04 KR-6, D04:330).
- Source: the item > the tooltip and name (presentation). 2nd: `tape.print_clicked` † with `source: bubble` (D05:244; section 10).

**E22-Q01-C31 A mark turns aged 60 s after its print, the eye hides the layer, and the tape still flags** (`e2e`; E-REPLAY with FX-G1 · streaming; mirrors
D04 D4-12, D02 D22)

- Pre: one flagged print at t; a second print at t + 60 s in print time (section 4; no wall wait).
- Steps: read the mark's state before and after the second print; press the legend's eye button; read the tape.
- Expected: the mark changes band once, 60 s after its print on the data clock, and on a quiet symbol only when the next print moves that clock (D04 D4-12;
  D05:332); the eye button's name is "Big trades visible" (`d03.05.r02`) and pressing it hides the layer while the tape keeps its tiers (D02 D22, D02:251).
  The aged opacity token is pending (D03 CR-1, D05:59): the case asserts the state change through the mirror, not a value.
- Source: print time > the mirror state (presentation). 2nd: none.

### 3.4 US-BIG-004 Print clustering (Must)

The engine's rule, which every clustering case asserts (BQ-13): the key is `(side, price_bucket)` with `price_bucket = floor(price / (tick ×
max(1, tolerance)))`; a print joins its key's open cluster if `ts_event <= first_ts_event + window`; the window is anchored on the first print and does not
slide; there is no tolerance check against the anchor price (`bigtrade_cluster.py`:5–10, :75–77, cited `BC`; `24`:597). The cluster takes its first print's
`id`, `ts_ms` and `price`, the total `size`, and `cluster_size` (`23`:791; `22` `getTrades`).

**E22-Q01-C32 With 250 ms and 1 tick, REST and WS return the same clusters, sized as the sum [R]** (`integration`, `contract`; E-REPLAY · clustered; mirrors
US-BIG-004/1 (wire half), S04.1 (wire half), T02.4 (membership half))

- Pre: FX-GOLD at the default threshold.
- Steps: `getTrades?symbol=BTCUSDT&cluster_window_ms=250&cluster_tolerance_ticks=1` paged over the window; subscribe `trades.BTCUSDT` with the same options
  and replay the window; compare items by first id.
- Expected: the REST and WS items match one for one on first `id`, `ts_ms`, `price`, total `size` and `cluster_size` (`22` `getTrades`; `23`:791); each
  `size` is the sum of its members' sizes; `sub_ok.effective` echoes 250 and 1 (`23`:790). The golden's case `notional_100000_cluster_250ms_1tick` records
  532 clusters from 542 prints at that config (`GB/summary.json`:4–18; its threshold is 100 000, so it is cited for the cluster count only).
- Source: the two surfaces per first id. 2nd: `BM` `bigtrade_clusters_emitted_total` rises.

**E22-Q01-C33 A clustered print reads as one row and one bubble with its constituent count** (`e2e`; E-REPLAY with FX-G1 · clustered; mirrors US-BIG-004/1
(UI half), S04.1 (UI half); blocked on E22-S04 #717, E22-S03 #716)

- Pre: as C28.
- Steps: read the tape row and its name; read the bubble's tooltip.
- Expected: one row with the cell `×7` after the Side word (shown only where `cluster_size` is on the wire, D05:284; `d02.13.cp15`), named "cluster of 7"
  in the row name (D05:284); one bubble with the tooltip of `d02.13.cp19`. The story says the size is the sum of the **qualifying** prints (`11`:2237–2239);
  the engine sums every evaluated member, flagged or not (`bigtrade.py`:174; `24`:600): the case asserts the engine's sum and C53 carries the C-row.
- Source: the item's `size` and `cluster_size` > the row and tooltip (presentation). 2nd: none.

**E22-Q01-C34 Clustering is signalled on both encodings and decodes to the same counts** (`contract`, `integration`; E-REPLAY · clustered; mirrors T02.2)

- Pre: two subscriptions to `trades.BTCUSDT` at 250 ms / 1 tick, one structured, one binary.
- Steps: replay FX-GOLD; decode both streams; compare cluster membership counts per first id.
- Expected: structured frames carry `cluster_size` > 1 for merged prints (`23`:2857); a window holding a cluster of more than one print leaves structured
  for the binary subscriber too (`23`:257; `TP`:30–33, `TP`:467), so both decode identical counts. T02.2 says "binary kind 3 records set flags bit2": at the
  base no kind-3 record carries a multi-print cluster, so bit2 is never set on `trades` (C-row C-BIT2, section 10); the case asserts the shipped rule.
- Source: the decoded counts per first id. 2nd: none.

**E22-Q01-C35 Changing the window to 1 s recomputes from stored prints at once and keeps the scroll and pause** (`e2e`, `integration`; E-REPLAY ·
clustered; mirrors US-BIG-004/2, S04.2; D02 S17; UI half blocked on E22-S04 #717, the control on D05-C-12)

- Pre: clustering at 250 ms / 1 tick; the tape paused and scrolled 3 rows.
- Steps: set the window to 1 000 ms (a `ctl` or a re-`sub` with the new `cluster_window_ms`); read the frames and the tape.
- Expected: the engine re-clusters its buffered open-cluster prints under the new config without a restart (`bigtrade.py`:115–124; `BC`:16–20); the tape
  shows a `presentation` divider at the seam ("— clustering on from here —" / "— clustering off from here —", `d02.13.cp09`) and the badge follows the option
  (D02 S17); the scroll position and the pause survive (S04.2). Whether a `ctl` of the cluster options re-snapshots is not stated (`23`:789 says so of
  `min_size` only): OQ-5; the case accepts either a `snap` with `reason` `reconfigure` or `d` frames, and asserts no row duplicated.
- Source: the frames > the divider and the pause chip (presentation). 2nd: none.

**E22-Q01-C36 A cluster that crosses a bar boundary belongs to the bar of its first print** (`integration`, `e2e`; E-REPLAY with FX-G1 · clustered; mirrors
US-BIG-004/3, S04.3, T01.4; UI half blocked on E22-S04 #717 and C-row C-BAR)

- Pre: a synthetic pair of same-side prints in one price bucket, 150 ms apart, at 14:01:59.900 and 14:02:00.050, with the window at 250 ms (FX-G1).
- Steps: read the item; read the bubble's position and tooltip.
- Expected: one item whose `ts_ms` is the first print's (`23`:791); the cluster belongs to the bar holding its first print (`24`:597; `BC`:21); the tooltip
  names the first print's time and its bar ("first print 14:02:11.208 · bar 14:02" is the drawn form, `d02.13.cp19`). The story asks that the rule be
  "documented in the tooltip" (`11`:2243–2244); the drawn tooltip names the bar but states no rule (C-row C-BAR, owner D02's owner with E22-S04): the case
  asserts the bar, and the rule sentence is blocked.
- Source: the item's `ts_ms` > the tooltip (presentation). 2nd: none.

**E22-Q01-C37 While clustering is on, the "(estimated)" badge shows with the word in its name, and its popover matches the rule [R] [F]** (`e2e`, `a11y`;
E-REPLAY · clustered; mirrors S04.4, global AC #6; blocked on E22-S04 #717 and the C-rows C-FAIL and C-WHY)

- Pre: clustering at 250 ms / 1 tick.
- Steps: read the chips row; read the CMP-227 chip's accessible name; hover and focus it and read the tooltip; press `Enter`.
- Expected: the chip "(estimated)" (`d02.13.cp06`) sits after the mode chip "Reconstructed 250 ms / 1 tick" (`d02.13.cp07`) and is visible iff
  `cluster_window_ms > 0` (D02:212, D02:275); its name is "Estimated, Trade cluster" (`d03.04.r03`) and contains the literal word "estimated" (S04.4); the
  tooltip reads "Prints at the same price and side within 250 ms / 1 tick are shown as one row. Enter opens Why estimated?" (`d02.13.cp18`), which names
  the window and the tolerance. It names **no failure mode** (S04.4 asks for at least one; `30`:386): C-row C-FAIL. "Why estimated?" opens SCR-058's
  `big_trade` section, which has no wording yet (D02 G10; D05:609 NOT FOUND): C-row C-WHY. The case passes the presence and name checks and stays blocked on
  the two C-rows. A missing badge is P1 (`30`:386; section 7.1).
- Source: `sub_ok.effective.cluster_window_ms` > the chip and its name (presentation). 2nd: none.

**E22-Q01-C38 With the window at 0 nothing merges and no badge shows [R]** (`integration`, `e2e`; E-REPLAY and E-DEMO · streaming; mirrors S04.5; UI half
blocked on E22-S04 #717)

- Pre: the default subscription (`cluster_window_ms` 0, `23`:787).
- Steps: subscribe; read every item's `cluster_size`; read the chips row.
- Expected: every item has `cluster_size` 1 (`23`:791: "no clustering and no added latency"); the mode chip reads "Raw prints" (`d02.13.cp07`) and neither
  the reconstructed chip nor "(estimated)" shows (D02:275). The served default is 0 while D02 draws "Reconstructed 250 ms / 1 tick" as the default
  (D05-C-6, D05:219): which the panel opens with is E22-S04's, and the case asserts the badge against the option actually sent.
- Source: the items > the chips (presentation). 2nd: none.

**E22-Q01-C39 The same window gives identical clusters however the prints are batched** (`integration`; E-REPLAY with FX-G4 · clustered; mirrors T01.3,
T04.3; blocked on FX-G4)

- Pre: FX-GOLD delivered twice through FX-G4, once in batches of 1 and once in random batch sizes from a stated seed.
- Steps: subscribe with 250 ms / 1 tick for each run; compare items.
- Expected: identical cluster count, membership (first id and `cluster_size`), total size and first-print time in both runs; the engine sorts each batch
  and every boundary is print time (`bigtrade.py`:3–8; `BC`:7–10). The batch-split determinism tests of T01 and T04 are white-box evidence, cited not
  re-run.
- Source: the two runs' items. 2nd: none.

**E22-Q01-C40 The golden drift check names the first diverging print** (`contract`, review; mirrors T04.2)

- Pre: the READY sha.
- Steps: confirm that the golden parity test (`services/api/tests/unit/orderflow/test_bigtrade_golden_parity.py`, `GB/README.md`:6) runs in the required
  backend unit job and attach its last green result; read its failure message format from the test.
- Expected: the test exists and runs in a required job; T04.2's "names the first diverging print id and field" is the test's own assertion, cited as
  white-box evidence. A black-box tester cannot change the engine, so this case is a review step, never a mutation.
- Source: the CI result. 2nd: none.

**E22-Q01-C41 Tolerance 0 and 1 cluster alike; 20 ticks widens the bucket; the bucket edge splits neighbours** (`integration`; E-REPLAY · clustered; edge
"tolerance at 0 and 20 ticks"; the bucket-edge leg on FX-G1)

- Pre: FX-GOLD (tick 0.1, `GB/summary.json`:55).
- Steps: `getTrades` at 250 ms with tolerance 0, then 1, then 20; compare clusters; then FX-G1: two same-side prints 0.1 apart across a bucket edge, and two
  1.9 apart inside one 20-tick bucket (2.0 wide at tick 0.1).
- Expected: tolerance 0 and 1 give identical clusters (`BC`:75–77: `max(1, tolerance)`); tolerance 20 groups prints in buckets 20 ticks wide; two prints one
  tick apart on either side of a bucket edge do not merge, and two prints inside one bucket do, whatever their distance (`BC`:5–6; `24`:597). This is the
  rule the popover's accuracy is checked against (section 3.9).
- Source: the REST pages > the bucket arithmetic. 2nd: none.

### 3.5 US-BIG-005 Big-trade alerts (Should): out of scope

US-BIG-005 (`11`:2251–2267) is E22-S06's, in the Backlog sprint (`E22J`:510), and is not in this plan's ticket list (BQ-01). No case.

### 3.6 US-BIG-006 Tape filters and columns (Should)

Every case here is **blocked on E22-S05 (#718)**. Filtering is client-side over the buffered store (`11`:2286).

**E22-Q01-C42 A size and side filter shows only matching prints, as a removable chip, and clearing restores them at once [R]** (`e2e`; E-REPLAY · streaming;
mirrors US-BIG-006/1, S05.1)

- Pre: FX-CLEAN BTCUSDT with at least 1 000 prints buffered.
- Steps: open the filter (`Ctrl+F`), set Sell and a minimum notional of 50 000 USDT, apply; read the chips and the readout; remove the chips; count rows.
- Expected: only sell rows at or above the minimum show; the chips read in the deck's form ("≥ 10 000 USDT", "Sell only", and the remove name "Remove filter
  ≥ 10 000 USDT", `d02.13.cp08`, with this case's value); the readout adds "+{n} filtered" (`d02.13.cp03`); "Filter applied: 2 filters active" is said once
  (`d02.12.r22`); clearing restores the hidden rows immediately, the buffered store unchanged (S05.1); no `sub`, `ctl` or `unsub` frame goes out (a display
  filter, D02 D15: only the reconstructed toggle re-subscribes).
- Source: the ring (unchanged) > the rows (presentation). 2nd: `tape.filter_changed` † (section 10).

**E22-Q01-C43 A cumulative-delta column appears and persists in the layout** (`e2e`; E-REPLAY · streaming; mirrors US-BIG-006/2, S05.2; also blocked on E15)

- Pre: the default columns.
- Steps: open Columns…, enable "Σ delta — client sum" (`d02.13.cp17`); reload; sign out and in.
- Expected: the column appears as a client sum of signed size (D02 D11); it persists across reload and sessions (S05.2) once E15's layout persistence lands;
  no key for it is named in D05 §5, so persistence is blocked on E15.
- Source: the column header (presentation). 2nd: none.

**E22-Q01-C44 A filter that matches nothing shows the explicit empty state with a clear action [F]** (`e2e`; E-REPLAY · filtered-empty; mirrors
US-BIG-006/3, S05.3; D02 S13)

- Pre: FX-THIN (synthetic thin ETHUSDT, `CONF/README.md`:14).
- Steps: set a minimum notional of 10 000 USDT (D02 S13 testability, D02:132).
- Expected: "No prints above 10 000 USDT in the last 5 min" (`d02.13.cp11`) with the button "Clear filter" (`d02.13.cp10`); the store intact; pressing
  Clear filter restores the rows.
- Source: the ring > the empty state (presentation). 2nd: none.

**E22-Q01-C45 The buffer size shows a memory estimate and resizing keeps the visible rows** (`e2e`; E-REPLAY · streaming; mirrors S05.4; also blocked on
`d05.06.memory` (PROPOSED))

- Pre: the ring at 10 000 (`14`:1275).
- Steps: change the buffer size to 20 000, then to 60 000.
- Expected: an estimated memory figure sits beside the size (the deck's PROPOSED form "10 000 prints ≈ 2.4 MB", `d05.06.memory`: behaviour asserted, not the
  text); the visible rows stay; the size cannot exceed 50 000 prints or 32 MiB (`LIM`:28–29; `TM` AC18 is E22-Q03's).
- Source: the visible row ids before and after > the field (presentation). 2nd: none.

**E22-Q01-C46 Filters and columns work from the keyboard alone** (`e2e`, `a11y`; E-REPLAY · streaming; mirrors S05.5)

- Pre: panel focus.
- Steps: `Ctrl+F`; set a filter; Tab to a chip and remove it; open the column menu and move a column with `Alt+↑` / `Alt+↓`.
- Expected: `Ctrl+F` opens the filter popover with focus in the minimum-notional field (D04 KR-4, D04:328); chips are added and removed by keys; `Alt+↑` /
  `Alt+↓` move a column only inside the open CMP-056 menu (D04 KR-5, D04:329); `Esc` clears the input first, then closes (D04 KR-2).
- Source: the focus order and the column order (presentation). 2nd: none.

**E22-Q01-C47 The Big only preset shows only flagged rows and counts the rest** (`e2e`; E-REPLAY with FX-G1 · streaming; mirrors D02 S20)

- Pre: FX-G1 at 500 prints/s with flagged prints.
- Steps: press the "Big only" chip (`d02.13.cp07`); read the rows and the readout.
- Expected: every visible row carries `●` or `◆` (D02 S20 testability, D02:139); the chip has `aria-pressed="true"`; "+{n} filtered" counts the hidden prints;
  "Big only on" is said once (`d02.12.r22`). The preset reads the server flag (S20).
- Source: the item flags > the rows (presentation). 2nd: none.

**E22-Q01-C48 A reload with filters and columns set restores them** (`e2e`; E-REPLAY · streaming; edge "reload with filters and columns set"; also blocked
on E15)

- Pre: a filter and a column set as in C42 and C43.
- Steps: reload; read the chips and the columns.
- Expected: the columns persist in the layout (S05.2); whether display filters persist is not stated by any merged source (OQ-6): the case asserts the columns
  and records the filters' state.
- Source: the layout read back (blocked) > the panel. 2nd: none.

### 3.7 Cross-cutting cases: the cross-surface invariant, the boundary table, observability, errors, roles, keys and the edge rows

**The invariant** (ticket; `E22J`:240; BQ-05): the same print is flagged identically on every surface that serves it. At the base three surfaces
serve a per-print flag: the WS item (`23`:790, `23`:2858–2861), the REST item (`22` `PublicTrade.is_big_trade`) and the bubble, read through its mirror node
and tooltip. `GET /market/metrics` is not served at the base and carries no per-print flag even when served (C55).

**E22-Q01-C49 REST serves 5 000 ms clustering and narrows its read window above 2 000 ms** (`contract`; E-REPLAY · clustered; edge "clustering window at
the 5 000 ms maximum (REST only)"; C-row C-5000)

- Pre: FX-GOLD.
- Steps: `getTrades` with `cluster_window_ms=5000` and no `from` / `to`; then with `from` / `to` 15 min apart, then 15 min + 1 ms apart.
- Expected: 5 000 is accepted on REST (`LIM`:15; `22` `getTrades` `cluster_window_ms` maximum 5000); above 2 000 ms the read window narrows to 15 min, so
  15 min is `200` and 15 min + 1 ms is `400` `invalid_time_range` (`LIM`:13; `TR`:247–256; `22`:4685–4687). The ticket's "clustering window at 0 and at the
  5 000 ms maximum" holds on REST only: the WS bound is 2 000 ms (`LIM`:16; `23`:787) and the panel's control stops there (D05-C-3, D05:142), so the UI
  reaches neither 5 000 nor any refusal (C57).
- Source: the REST answers. 2nd: `BM` `bigtrade_range_rejected_total{endpoint}` rises once for the refusal (`BM`:53–57).

**E22-Q01-C50 The same print is flagged alike on the WS item, the REST item and the bubble [R]** (`integration`, `e2e`; E-REPLAY with FX-G1, and E-DEMO ·
streaming and clustered; mirrors T02.4 (flag half), US-BIG-002 NFR, the ticket's core invariant; bubble leg blocked on E22-S03 #716)

- Pre: E-REPLAY: FX-G1 with flagged and unflagged prints, notional mode; E-DEMO: the live public stream for 10 min at the default threshold.
- Steps: capture `trades.BTCUSDT` with options O; read `getTrades` with the same options for the same span; read the bubble mirror nodes; join all three on
  print id (a cluster on its first id). Repeat for O = no clustering and O = 250 ms / 1 tick.
- Expected: for every id in both captures, `is_big_trade` is equal on WS and REST and a mirror node exists iff the flag is true (`22` `getTrades`: "the two
  agree on the flagged prints and on cluster membership"; `23`:791); the join is one to one for clusters too. A difference is allowed only in the cases C51
  names. On E-DEMO the set is likely empty at 250 000 USDT, and the case records the count it compared; E-REPLAY with FX-G1 is the non-empty run.
- Source: the per-id join of the three surfaces. 2nd: `BM` `bigtrade_flagged_total` delta equals the distinct flagged ids received.

**E22-Q01-C51 Where the surfaces may differ, they differ only for the documented reasons** (`integration`; E-REPLAY with FX-G1 · capped, percentile, late;
mirrors `23`:791's bounded agreement; the percentile and cap legs blocked on E22-S02 #715)

- Pre: three runs: percentile mode; a cap engaged (C19's setup); a print delivered more than 500 ms after its cluster's deadline (FX-G1).
- Steps: run C50's join in each.
- Expected: a WS-versus-REST difference appears only in these three conditions ("the two can differ in percentile mode, when the over-flagging cap engages,
  or for a print arriving more than 500 ms late (`LATE_GRACE_US`)", `23`:791; `TP`:96–98); in every other run C50 holds. A difference outside them is P1
  (section 7.1).
- Source: the per-id join and the run's condition. 2nd: none.

**E22-Q01-C52 A cluster is big when any member print is flagged, not when its total crosses the threshold** (`integration`; E-REPLAY with FX-G1 · clustered;
divergence 1 of BQ-06; C-row C-CFLAG; FX-G1 needs FX-G4)

- Pre: FX-G1: at 250 ms / 1 tick, seven same-side prints at 40 000 USDT each (total 280 000, no member at 250 000), and a second cluster with one member at
  260 000.
- Steps: read both clusters on WS and REST.
- Expected: the first cluster has `is_big_trade: false` and the second `true` on both surfaces: "on a cluster it is true when any member print is flagged:
  the engine flags prints, and exposes no cluster-level evaluation of the cluster's total" (`22` `getTrades`; `23`:791, `23`:2861). A reader of US-BIG-004
  ("qualifying prints merge", `11`:2237–2239) may expect the first to be big: C-row C-CFLAG to the `22` / `23` / `24` owners; the case asserts the shipped rule.
- Source: the two surfaces. 2nd: none.

**E22-Q01-C53 A cluster's size sums every member, and its mark sits at the vwap while its row sits at the first print** (`integration`, `e2e`; E-REPLAY
with FX-G1 · clustered; divergences 2 and 3 of BQ-06; C-rows C-CSIZE, C-CPOS; mark leg blocked on E22-S03 #716)

- Pre: FX-G1: at 250 ms / 20 ticks, one flagged sell at 64 012.0 and four unflagged sells inside the same bucket at other prices within 250 ms.
- Steps: read the item; read the tape row and the bubble's mirror and tooltip.
- Expected: one item whose `size` is the sum of all five (the engine clusters every evaluated print, flagged or not: `bigtrade.py`:174; `24`:600 "The buffer
  holds all evaluated prints (not only flagged ones)"), whose `price` and `ts_ms` are the first print's (`23`:791); the row shows that price; the mark sits at
  the cluster's `vwap` and `first_ts_event` (D03:206), so its price can differ from the row's. C-CSIZE (the story says the sum of the qualifying prints,
  `11`:2237–2239) and C-CPOS (D03:206 against `23`:791) go to the `24` owner and D03's owner; the case asserts the shipped and drawn rules.
- Source: the item > the row and the mirror (presentation). 2nd: none.

**E22-Q01-C54 The whale tier and the bubble cap are a client-side 4× of the one server threshold** (`e2e`; E-REPLAY with FX-G1 · streaming; divergence 4
of BQ-06; C-row C-TIER2; blocked on E22-S01 #714, E22-S03 #716)

- Pre: FX-G1 with prints at 3.9× and 4.0× the threshold.
- Steps: read the rows' tier and the marks' labels.
- Expected: the 4.0× print is tier 2 (`◆`, weight 700, D05:275–281) and its mark is at the cap with a label; the 3.9× print is tier 1. Tier 2 is "a
  client-side 4× multiple" of the one engine threshold (D02:101, D02 G8; D05-C-11, D05:536), and the bubble cap is the same 4× (D02:249). S02.1 forbids a
  client-side comparison of notional against the threshold (`E22J`:404): C-row C-TIER2 to E22-S02 and D04's owner; the case asserts D02's rule and that the
  tier-1 boundary itself follows the server flag (C17).
- Source: the item flags and notionals > the rows and marks (presentation). 2nd: none.

**E22-Q01-C55 The metrics leg: `GET /market/metrics` is not served at the base; the aggregate stand-in agrees** (`contract`; E-REPLAY with FX-G1 · streaming;
the ticket's third surface; **blocked on #645 / #658** for the per-series leg; G-row G-M1)

- Pre: FX-G1 at the default threshold.
- Steps: read the composition allow-list and the RBAC matrix rows for `getMetrics`; over a fixed span, count the flagged items the tape received and read the
  engine's flagged counter before and after.
- Expected: `getMetrics` is a contract-first operation not mounted at the base (`services/api/tests/unit/architecture/composition_allowlist.json`:105–108;
  `services/api/tests/contract/rbac/matrix.yaml`:903–909, `state: not_mounted`); the app wires the `trades` topic (`services/api/candleviewer/app.py`:1809–1816), and
  `getMetrics` is `not_mounted` (matrix.yaml:903–909). When served, `big_trade_notional` is the largest print notional in a 1 000 ms window and
  `big_trade_zscore` a z-score over 500 prints (`22` `getMetrics`, `22`:4892–4894; `24`:1125–1126; `services/api/candleviewer/rules/vocabulary/metrics.py`:38–39):
  aggregates, never a per-print flag, and `trade_cluster` (`24`:1129) has no `MetricCode` in `22`. The stand-in, aggregate only and never per print: the
  `bigtrade_flagged_total{mode}` delta (`BM`:26–28) equals the count of distinct flagged items the tape received over the span. When the route is served,
  the case adds: for each 1 000 ms window, the served `big_trade_notional` equals the largest notional among the tape's items in that window.
- Source: the two test-config files > the counter delta. 2nd: as source.

**E22-Q01-C56 REST boundary table: every reachable bound answers with `22`'s status and rule [R] [F]** (`contract`; E-REPLAY · streaming; mirrors `TM` AC1,
AC2, AC3, AC8 (REST half) and `TM`:179's boundary-table duty)

- Pre: FX-CLEAN BTCUSDT; a session with `marketdata:read`.
- Steps: one `getTrades` request per row below; read the status, the problem code or rule, and the `field`.
- Expected (`TR`:167–212; `22`:4685–4698, the "Errors as built" paragraph): a parameter outside its schema is **422** `validation_failed` with
  `errors[].field` (as `query.cluster_window_ms`) and the failed `rule`; a malformed `from`, `to`, `min_size` or `cursor` is **400**; `invalid_time_range` and
  `invalid_min_size` are **400**. `TM` writes "400" for AC2 and AC8 (`TM`:208, `TM`:214): C-row C-400 to the `TM` owner (E22-X01); the table follows `22`.

  | Bound (constant)                              | value: expected                   | value+1 (or just past): expected                                         | 0: expected                 | negative: expected                              | non-finite / non-integer: expected                                                |
  | --------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------ | --------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------- |
  | window 6 h (`TRADES_MAX_WINDOW_MS`, `LIM`:12) | `to - from` = 6 h: `200` (AC3)    | 6 h + 1 ms: `400` `invalid_time_range` (AC3)                             | `from` = `to`: `200`        | `from` > `to`: `400` `invalid_time_range` (AC3) | `from` = epoch 0, `to` = now: `400` `invalid_time_range` (AC1); `from=abc`: `400` |
  | window 15 min above 2 000 ms (`LIM`:13)       | C49                               | C49                                                                      | n/a                         | n/a                                             | n/a                                                                               |
  | `limit` 500 (`TRADES_MAX_LIMIT`, `LIM`:14)    | 500: `200`                        | 501: `422` `query.limit` (AC2)                                           | 0: `422` (AC2)              | -1: `422` (AC2)                                 | 1.5: `422` (AC2)                                                                  |
  | `cursor` 512 characters (`22` `Cursor`)       | 512: length bound only, not `422` | 513: `422`, length bound only (AC2)                                      | empty: `400`                | n/a                                             | one that does not decode: `400` (AC2); the expiry and refusal rules: C-CURSOR     |
  | `cluster_window_ms` 5 000 (`LIM`:15)          | 5000: `200` (C49)                 | 5001: `422` `query.cluster_window_ms` (AC8)                              | 0: `200`, no clustering     | -1: `422` (AC8)                                 | 2.5: `422` (AC8)                                                                  |
  | `cluster_tolerance_ticks` 20 (`LIM`:17)       | 20: `200`                         | 21: `422` `query.cluster_tolerance_ticks` (AC8)                          | 0: `200` (C41)              | -1: `422`                                       | 1.5: `422`                                                                        |
  | `min_size` floor (SR-E22-03, `LIM`:50–54)     | the floor: `200`                  | just below the floor: `400` `invalid_min_size`, `detail` names the floor | 0: `400` `invalid_min_size` | -1: `400` `invalid_min_size`                    | NaN: `400` `invalid_min_size`; 33 characters: `422`                               |

  The cursor's expiry and refusal rules (`22` `Cursor`, `TM` AC2) are not asserted at the base: the 512 and 513 cells check the length bound only, and an
  unissued or edited cursor is not asserted (C-row C-CURSOR, routed to E22-X02).
  The empty cursor, the 512-character cursor and the `min_size` rows assert the status only; their messages are not compared (section 0). `TM` AC1 also says
  "no DB query": a black-box tester asserts the answer only (the `TM` control is E22-X02's).

- Source: the status, code and `field` per row. 2nd: `BM` `bigtrade_range_rejected_total{endpoint}` rises once per `invalid_time_range` and
  `invalid_min_size` row (`BM`:53–57).

**E22-Q01-C57 WS boundary table: an out-of-range option is refused per topic, never clamped, and nothing is subscribed [R] [F]** (`contract`; E-REPLAY ·
streaming; mirrors T02.3, `TM` AC8 (WS half); edge "clustering window at 0 and at the WS maximum")

- Pre: a live connection.
- Steps: one `sub` of `trades.BTCUSDT` per row; read `sub_ok`; then confirm that no `d` frame arrives for a refused topic.

  | Option                    | accepted  | refused (each `invalid_options`, `field` the option's name, the message naming the range)     |
  | ------------------------- | --------- | --------------------------------------------------------------------------------------------- |
  | `cluster_window_ms`       | 0, 2000   | 2001; 5001 (the REST maximum, AC8); 999999 (T02.3); -1; 2.5; "250"                            |
  | `cluster_tolerance_ticks` | 0, 20     | 21 (AC8); -1; 1.5                                                                             |
  | `min_size`                | the floor | below the floor, negative, non-finite (`TM` AC4 is E22-X02's; this row asserts the code only) |

- Expected: refusals are per topic in `sub_ok`, never clamped; "cluster_window_ms must be 0 to 2000." is the shape of the message (`23`:788); the topic is not
  subscribed (`23`:788; T02.3); `min_size` refusals are `invalid_options` with `field: "min_size"` (`23`:787). REST answers the same values with 422 by
  intent (`22`:4696–4697): each surface keeps its own refusal shape.
- Source: `sub_ok` per topic. 2nd: `cv_ws_trades_subscribe_rejected_total{reason="cluster_range"}` rises once per cluster refusal and
  `{reason="min_size_floor"}` per `min_size` refusal (`WM`:174–182; `TP`:179–188, `TP`:294).

**E22-Q01-C58 Server-side filtering is never silent: `dropped` reports exactly what `min_size` removed [R]** (`integration`; E-REPLAY and E-DEMO ·
streaming; mirrors T02.1)

- Pre: FX-CLEAN BTCUSDT; `K(pre)` read.
- Steps: subscribe `trades.BTCUSDT` with `min_size` 0.5 (at or above the instrument's floor); replay; for each frame, count the fixture prints below 0.5 since
  the previous frame.
- Expected: no item has `size` below 0.5; each frame's `dropped` equals the prints below 0.5 since the previous frame (`23`:789; `23`:2868–2871); a frame
  goes out for drops alone (`TP`:25–26); a `ctl` changing `min_size` never re-snapshots (`23`:789). On E-DEMO the invariant "items + dropped = prints the
  REST page shows for the span without `min_size`" is asserted instead of exact counts.
- Source: the frames against the fixture > `K(post)`. 2nd: `cv_ws_tape_prints_dropped_total{reason="min_size"}` delta equals the summed `dropped`
  (`WM`:162–169; `TP`:483–484).

**E22-Q01-C59 The counters read before and after a burst account for every print** (`integration`; E-REPLAY with FX-G4 · high rate; the ticket's
Observability note; blocked on FX-G4 and OQ-1 (the read path))

- Pre: `K(pre)`: every shipped counter of section 10's list.
- Steps: run C02's burst with `min_size` set; read `K(post)`.
- Expected: `cv_ws_tape_prints_dropped_total{reason}` delta equals the frames' summed `dropped`, split by `min_size` and `overflow`;
  `cv_ws_tape_frames_coalesced_total` delta equals the frames with `coalesced_count` > 1; `bigtrade_prints_evaluated_total` delta equals the distinct prints
  injected; `bigtrade_state_truncated_total` unchanged below the SR-E22-05 caps (`BM`:35–39). The ticket's names `tape_prints_dropped_total` and
  `tape_frames_coalesced_total` are shipped with the `cv_ws_` prefix (`WM`:165–173): C-row C-NAMES.
- Source: the frames > the counter deltas. 2nd: as source.

**E22-Q01-C60 Every error reaches the user as an actionable sentence, with the code behind a details disclosure** (`e2e`; E-REPLAY · disconnected,
refusals; mirrors global AC #5; blocked on E22-S01 #714, E22-S02 #715)

- Pre: the panel open.
- Steps: cause a REST `503` (the trade stream not running, `TR`:200–202), a WS `invalid_options` (C57) through the panel where a control can reach it, and a
  disconnect (C06).
- Expected: each shows a sentence in domain language; no raw stack trace and no bare code; the code is reachable in a details disclosure (`11`:46). The
  sentences for these refusals are not in the deck (feed episodes are `d05.07.feed`, named elsewhere; the range message is `d05.05.range`, PROPOSED): the case
  asserts the pattern and that no server `title`, `detail` or WS `message` text reaches the DOM unmapped, and is blocked on the owners' words.
- Source: the API answer > the DOM (presentation). 2nd: none.

**E22-Q01-C61 Reads work for every role; the settings controls are gated with their reason** (`contract`, `e2e`; E-REPLAY · streaming; mirrors D02 S21, S23,
section 2.1; the UI half blocked on E22-S01 #714; the write legs on E22-S02 #715)

- Pre: FX-USERS: OWNER, a MANAGER, a VIEWER and a view-as session.
- Steps: as each, `getTrades` and `sub` `trades.BTCUSDT`; open the strip and the column menu; try each write control.
- Expected: every read answers `200` / `sub_ok` (`22` `getTrades` `x-rbac` `marketdata:read` · none; matrix.yaml:947–951); unauthenticated is `401`
  (`TR`:184–185). VIEWER: the write controls keep their role and label with `aria-disabled="true"`, the lock glyph and the notice "Read-only — your role
  can't change settings." (`d02.13.cp24`); view-as: "Read-only while viewing as {user}." (`d02.13.cp24`); pause, display filters and Big only still work
  (D02 S23 testability, D02:142). A permission-less caller's `403` and `TM` AC14–AC16 are E22-X02's.
- Source: the API answers > the gated controls (presentation). 2nd: none (a read).

**E22-Q01-C62 The whole tape flow runs from the keyboard, and a screen-reader pass hears what the design says** (`a11y`, `e2e`; E-REPLAY with FX-G1 ·
streaming, paused; smoke for global AC #3; blocked on E22-S01 #714; the audit is E22-Q04's)

- Pre: FX-G1 at 500 prints/s; a screen reader on; the whale opt-in off, then on.
- Steps: with the keyboard only: focus the panel, `P` to pause and resume, arrows through rows, `Enter` on a row, `Esc`, `Ctrl+Home`, `Ctrl+F` and the
  filter, the column menu, the strip, a bubble's mirror node. Listen for one minute with the opt-in off, then on.
- Expected: the keys behave as D04 KR-1 to KR-7 and the focus as FP-01 to FP-12 (D04:318–373; lifted by hash in D05 §9.5); focus stays on the same print
  through a pause and a resume and "Resumed, {n} prints inserted" is said once (FP-04); with the opt-in off no whale is announced, and with it on at most one
  whale sentence in any 5 s ("Whale sell, 410k at 64,012.0", `d04.07.an01`; AN-01, AN-02, the throttle at D05:411–417); no announcement per row arrival
  (AN-07); the opt-in's label is "Announce whale prints (tape)" (`d04.07.optin`; its setting key is PROPOSED, D05:438–443). Reduced motion makes no visible
  difference: every tape and bubble change is a cut in both modes (D05 §9.2–§9.3, D4-01 to D4-14).
- Source: the focus position and the announcement log. 2nd: none.

**E22-Q01-C63 Every state is carried in text, never by colour alone** (`a11y`; E-REPLAY · every state of section 2.2; the one black-box a11y leg (BQ-17);
blocked on E22-S01 #714, E22-S03 #716)

- Pre: greyscale rendering.
- Steps: reproduce S2, S4, S8, S10, S13, S17 and S18 and the capped and clustered marks; read each.
- Expected: each state shows its words (the Paused chip, "Stale 12s", "Offline", the filtered-empty line, the clustering divider, the warning strip,
  "capped", "(estimated)"; deck `d02.13.cp04`, `cp05`, `cp06`, `cp09`, `cp11`, `cp12`), and side reads as the word Buy or Sell beside its glyph (`11`:44;
  D02 §10).
- Source: the DOM text (presentation). 2nd: none.

**E22-Q01-C64 Both densities and all three themes stay legible** (`e2e`; E-REPLAY · streaming; smoke for charter CH4; blocked on E22-S01 #714)

- Pre: compact and comfortable (D05 §8.1); dark, light and high contrast (D05:288–290; the ticket says two themes, the design resolves three).
- Steps: open the panel in each of the six combinations; read the row height, the chip rows and the strip.
- Expected: no truncated chip text, no overlapping rows, the strip summary on one line at the 332 px minimum ("▸ Threshold 250k · area-linear · 250 ms
  (estimated)", `d02.13.cp14`); row heights 24 px compact and 32 px comfortable (D05:263). Contrast values are E22-Q04's.
- Source: the DOM (presentation). 2nd: none.

**E22-Q01-C65 Switching symbol mid-pause never shows the old symbol's prints under the new one** (`integration`, `e2e`; E-REPLAY · paused; edge "symbol
switch mid-pause"; UI half blocked on E22-S01 #714 and OQ-2)

- Pre: BTCUSDT hard-paused with 400 prints buffered; FX-CLEAN for BTCUSDT and ETHUSDT.
- Steps: switch the panel to ETHUSDT; read the frames and the rows; switch back.
- Expected: after the switch, every frame's `symbol` and every row is ETHUSDT (`23`:2840); no BTCUSDT print appears under ETHUSDT (wrong-symbol data is P0,
  section 7.1). What happens to the pause and its buffered count on a switch is stated by no merged source (D02 §5 and D04 §9 name no symbol switch): OQ-2;
  the case records it.
- Source: the frames' `symbol` > the rows. 2nd: none.

### 3.8 Exploratory charters (session-based, 90 minutes each)

The form is `03` §11.2's: mission, areas to probe, checks (what looks wrong), and a debrief note (`03`:316–318; 60–120 min, the ticket fixes 90). This plan
writes the charters; E22-Q05 (#755) runs them after E22-S01 to S05 are built and holds the debrief (`E22J`:350). Each lists what the plan already knows, so
the session hunts for what it does not. The merged tape charter `docs/qa/charters/E08-charter-6-tape-bursts.md` is the precedent form.

**CH1 The tape at extreme print rates, looking for silent data loss.** Mission: find a print that is neither shown, nor buffered, nor counted. Areas: 500,
2 000 and 5 000 prints/s through FX-G4; pause during a burst; a full ring while paused (S22); the fallback ladder (S19); a disconnect mid-burst (C07); `min_size`
on and off. Checks: a print in the injected sequence that no row, no ring entry, no `dropped` and no `coalesced_count` accounts for (P0, section 7.1); a
"/frame" readout that does not move while rows are merged (`d02.13.cp03`); "+N filtered" that disagrees with the filter; a counter delta that disagrees with
the frames (C59). Known going in: E08 charter F6-2, recorded there as a question (`docs/qa/charters/E08-charter-6-tape-bursts.md`:39). Debrief: every unaccounted print with its id, rate and frame.

**CH2 Threshold and clustering configuration, looking for disagreement between the tape, the bubbles and the metrics.** Mission: find a print flagged on
one surface and not another outside C51's three reasons. Areas: notional, percentile and absolute-size modes; the cap entering and leaving; windows 0, 250,
1 000, 2 000 ms and tolerances 0, 1, 20; a window change while paused; late prints; the `getMetrics` aggregates once served. Checks: C50's join failing; a
bubble with no flagged item or a flagged item with no bubble; a tier that follows a client comparison (C17); the badge or the readout disagreeing with
`sub_ok.effective`. Known going in: the four divergences C52, C53 (two) and C54 and the popover gaps of section 3.9. Debrief: each disagreement with its id,
config and the three surfaces' values.

**CH3 The paused state, looking for state or focus loss.** Mission: lose the pause, the buffered count or the focused print. Areas: the pause rows P1–P14
and S2–S6, S22; D04 FP-01 to FP-12 (lifted by hash, D05 §9.5); a stale feed and a disconnect while paused (P10, FP-10); a symbol switch mid-pause (C65); a
window change mid-pause (C35); a reload. Checks: a resume nobody asked for; a chip count that differs from the inserted rows; focus on `body` or on a moving
row; a focused print evicted (FP-09). Known going in: the full-ring policy is PROPOSED (D02-G7, D02:485); no source states what a symbol switch does to a
pause (OQ-2). Debrief: the sequence of keys and events before each loss.

**CH4 Density, looking for legibility failures at both densities and in every theme.** Mission: find text that cannot be read or a state that cannot be
told apart. Areas: compact and comfortable (D05 §8.1); dark, light and high contrast (D05:288–290: the ticket says two themes, the design resolves three);
greyscale; 200 % zoom and the narrow panel (332 px, D05:267); the strip, the chips row, the warning strip, the bubble labels and the cluster badge. Checks:
truncated or overlapping text; a tier, side or state carried by colour alone (C63); the "(estimated)" chip squeezed out. Debrief: screenshots with no account
identifier (ticket Security notes), each with density, theme and zoom.

### 3.9 The honesty checklist (R2 §6.4 "badge present, popover accurate, thresholds visible", `30`:404; ticket AC 2)

One block per site where the design draws an estimate. Each check is a case step above; this table is what E22-Q05 ticks per build. A missing or wrong
badge is P1 (`30`:386; section 7.1). No wording is invented: where the text the check needs does not exist, the row names the C-row and its owner.

| #     | Site                         | Check                                                                                                                                         | Expected (deck key or rule)                                                                                                                       | Case     | Status                                            |
| ----- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------- |
| HC-1  | clustering: the chips row    | the badge is present whenever `cluster_window_ms > 0` and absent at 0                                                                         | "(estimated)" `d02.13.cp06`, after "Reconstructed 250 ms / 1 tick" `d02.13.cp07`; visible iff the window > 0 (D02:212, D02:275)                   | C37, C38 | executable once E22-S04 lands                     |
| HC-2  | clustering: the badge's name | the accessible name holds the literal word "estimated"                                                                                        | "Estimated, Trade cluster" `d03.04.r03`                                                                                                           | C37      | executable once E22-S04 lands                     |
| HC-3  | clustering: the popover      | it names the window and the tolerance, matching the option sent                                                                               | "Prints at the same price and side within 250 ms / 1 tick are shown as one row. Enter opens Why estimated?" `d02.13.cp18`                         | C37      | executable once E22-S04 lands                     |
| HC-4  | clustering: popover accuracy | its words do not contradict the implemented rule: same side, one price bucket of tick × max(1, tolerance), window anchored on the first print | `BC`:5–10, :75–77; `24`:597. "same price … within 1 tick" is looser than the bucket rule (prints one tick apart across an edge do not merge, C41) | C37, C41 | C-row C-ACC (D02's owner, E22-S04)                |
| HC-5  | clustering: a failure mode   | the popover names at least one failure mode (S04.4; `30`:386)                                                                                 | none drawn                                                                                                                                        | C37      | blocked: C-row C-FAIL (D02's owner, E22-S04 #717) |
| HC-6  | clustering: "Why estimated?" | the methodology it opens matches the rule                                                                                                     | SCR-058's `big_trade` section: no wording (D02 G10; D05:609 NOT FOUND)                                                                            | C37      | blocked: C-row C-WHY (E22-S04 #717, E25-D05)      |
| HC-7  | clustering: the bar rule     | the tooltip states the bar-attribution rule (`11`:2243–2244)                                                                                  | the drawn tooltip names "bar 14:02" and no rule (`d02.13.cp19`)                                                                                   | C36      | blocked: C-row C-BAR (D02's owner, E22-S04)       |
| HC-8  | clustering: legend and marks | the legend row and the cluster mirror name carry the word while clustering is on                                                              | "(estimated)" in `d02.13.cp20`; "…, estimated" in `d03.04.r02`                                                                                    | C28, C33 | executable once E22-S03, S04 land                 |
| HC-9  | percentile mode              | the effective value shows with the badge                                                                                                      | "eff. 220k USDT" + "(estimated)" `d02.13.cp06`; name "Estimated, Big trade" (D02:242, not in the deck); the P² estimate (`bigtrade.py`:11–12)     | C18      | blocked on E22-S02 #715 (no way to set the mode)  |
| HC-10 | the cap                      | the effective value differs from the configured one and the panel says so                                                                     | the chip "capped" `d02.13.cp06`; the strip `d02.13.cp12`                                                                                          | C19      | blocked on E22-S02 #715                           |
| HC-11 | effective thresholds visible | the strip's readout is always visible and equals the wire                                                                                     | "eff. 250k USDT" `d02.13.cp06` = `sub_ok.effective.big_trade_threshold` = each frame's = REST `meta` (`23`:790; `22` `TradesPageMeta`)            | C15      | wire half executable at the base                  |

"Thresholds visible in the inspector" (`30`:404) names no inspector for SCR-053; this plan reads it as the strip's readout (HC-11) plus SCR-058's
`big_trade` section once it exists (HC-6). `14`'s "(estimated)" row does not list SCR-053 (D02 G9, D02:473): the `14` owner's row, carried.

## 4. Time control

No case sleeps or waits more than 5 minutes (`E16P` section 4's bound). The engine runs on print time only, so injected sequences need no wall-clock wait
(BQ-21).

**4.1 What the shipped hook moves.** `CV_TEST_CLOCK` feeds the auth clock only (`services/api/candleviewer/auth/testnet_clock.py`; as `E13P` section 4.1
records); no big-trade, publisher or panel timer reads it, and no case here uses it.

**4.2 The strategy, need by need.**

| Need                                                                           | Mechanism                                                                                                                                                                 | Cases                             |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| the threshold refresh (5 s of print time, `LIM`:38) and the percentile warm-up | **print time inside the injected sequence**: the sequence carries the timestamps; no wall wait (`bigtrade.py`:3–8, :163)                                                  | C18, C23, C25                     |
| a cluster's close (first print + window; late grace 500 ms, `TP`:96–98)        | print time for the close by a later print; the reader's clock passes the deadline plus 500 ms within 2.5 s of real time for the close by clock (`TP`:24–25)               | C32, C51                          |
| the publisher's 100 ms window (`TP`:84–85)                                     | real time: frames arrive within 100 ms windows; a case reads frames, never one window's timing                                                                            | C02, C58                          |
| a bubble's aging at 60 s (D4-12)                                               | a second print 60 s later **in print time**; on a quiet symbol the band changes only when the next print moves the data clock (D05:332)                                   | C31                               |
| the soft pause (150 ms at rest), the 30 s park, the 5 s whale window           | the browser clock (`page.clock`), no wait (D02 P1, P3; D05:411–417)                                                                                                       | C04, C62                          |
| a stale feed at 10 s and 30 s (D02 S8, S9)                                     | real time: the fixture stops; the case waits at most 35 s                                                                                                                 | C11                               |
| a burst at 2 000 prints/s (and 500, 5 000)                                     | **FX-G4**, a seeded synthetic sequence at a stated rate into the live path; the replay injector feeds a replay session's own namespace, not the live publisher (C02 note) | C02, C03, C05, C12, C29, C39, C59 |

Every case names its clock, and no assertion sits on an exact boundary instant: the stale chip is read after 12 s, never at 10.

## 5. The destructive and fixture protocol

Nothing in E22 deletes data (BQ-23): the surfaces are reads, and the only write is the PROPOSED `bigtrade.*` settings keys, which have no route
(D05:205–215). The protocol is therefore reduced:

- **Scratch stack.** Each run uses its own stack, fed by the fixtures it names, destroyed after; never shared with a live process (C-2.11).
- **The counter reads `K`.** `K(pre)` and `K(post)` are reads of the shipped counters of section 10, taken before and after each burst case; a case's
  expected delta is written from its steps before the run, never from the system's report. Their read path on staging is OQ-1.
- **Safety stops.** Data of another symbol in a frame or a row (C65), or any user- or account-bearing field in a frame (`TM` AC12 is E22-X02's), is **P0**
  whatever else passes (section 7.1).
- **Persistence legs** (per-symbol memory C20, columns C43, reload C48) run only once E22-S02, E22-S05 and E15 land; until then they are blocked.
- **Fixtures.** Recorded, redacted Bybit captures and the synthetic tapes of section 6, each labelled as what it is (C-13.5); no test reaches `*.bybit.com`
  or `*.bytick.com`; no fixture is edited by hand.

## 6. The fixture catalogue

All market data is the recorded corpus `BYB/2026-10-05/` (built from documented shapes and earlier recordings, exception #1778 group A, `BYB/README.md`:44–47,
plus the 2026-10-19 live capture, `BYB/README.md`:54–57), the big-trade golden `GB`, and the synthetic conformance tapes of `CONF`, each labelled for what it
is (C-13.5). No key, account or production row. The ticket's R2 set ("normal session, high-volatility burst, WS disconnect + resync, sequence gap,
thin-book symbol", `30`:401) maps as below; a synthetic tape is never called recorded.

| Handle     | R2 item / need                 | Content                                                                                                                                                                                                                            | Provenance                                                                                    | Cases                                          |
| ---------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| FX-CLEAN   | normal session                 | `BYB/2026-10-05/ws/clean_publicTrade_{BTCUSDT,ETHUSDT,SOLUSDT}.jsonl`, 360 frames each, clean 3 h windows (`BYB/README.md`:29); 542 / 519 / 556 prints                                                                             | documented-shape corpus (exception #1778 A)                                                   | C01, C06, C11, C15, C42, C58, C65              |
| FX-GOLD    | normal session, expected flags | `GB/trades_BTCUSDT.csv.gz`: the BTCUSDT window above, 542 prints over 2.99 h; `GB/summary.json`: notional 250 000 flags 0; percentile 99 / 1 h flags 24 with one cap entry; notional 100 000 at 250 ms / 1 tick gives 532 clusters | from the corpus through the production parser; "NOT a full symbol-day" (`GB/README.md`:10–23) | C18, C24, C32, C34, C39, C41, C49              |
| FX-LIVE20  | recorded live frames           | `BYB/2026-10-05/ws/recorded_publicTrade_BTCUSDT.jsonl`, 20 frames, 46 prints (`BYB/README.md`:36)                                                                                                                                  | Bybit mainnet public stream, recorded 2026-10-19 (`BYB/README.md`:54–57)                      | C01 (shape check)                              |
| FX-RECON   | WS disconnect + resync         | `ws/publicTrade_BTCUSDT.jsonl` (frames 1–2, reconnect, 3) with `rest/recent_trade_BTCUSDT.json`; `ws/reconnect_publicTrade_ETHUSDT.jsonl`, 30 frames (`BYB/README.md`:31)                                                          | documented shape, "NOT a live capture" (`BYB/2026-10-05/README.trades.md`:1–7)                | C07, C22                                       |
| FX-GAP     | sequence gap                   | `CONF/tapes/btcusdt-2026-09-02-gap.jsonl.gz`: a 150-print gap, 80 recovered (`CONF/README.md`:13); the recorded gap file is an order-book one (`BYB/README.md`:30)                                                                 | **synthetic** (`CONF/README.md`:3–4)                                                          | C08 (shape of the hole)                        |
| FX-THIN    | thin-book symbol               | `CONF/tapes/ethusdt-2026-09-03-thin.jsonl.gz`, 3 000 prints (`CONF/README.md`:14)                                                                                                                                                  | **synthetic**                                                                                 | C10, C44                                       |
| FX-NEWLIST | partial history                | `CONF/tapes/newlist-2026-09-04.jsonl.gz`, recorded from 11:17Z, 20 000 prints (`CONF/README.md`:15)                                                                                                                                | **synthetic**                                                                                 | C09, C25                                       |
| FX-DENSE   | dense tape (D02 S18, S22)      | `CONF/tapes/btcusdt-2026-09-01.jsonl.gz`, 200 000 prints (`CONF/README.md`:12)                                                                                                                                                     | **synthetic**                                                                                 | C17, C19                                       |
| FX-USERS   | roles                          | OWNER, a MANAGER, a VIEWER and a view-as session, made per run                                                                                                                                                                     | synthetic per run                                                                             | C61                                            |
| FX-G1      | a print at or above 250 000    | **none recorded**: the scan of C16 finds a maximum of 94 681.50 USDT over every trade fixture; a seeded synthetic sequence with stated notionals is used meanwhile                                                                 | **synthetic**, through FX-G4                                                                  | C14, C16, C26–C31, C33, C36, C47, C50–C55, C62 |
| FX-G2      | high-volatility burst          | **none for trades**: `ws/burst_tickers_BTCUSDT.jsonl` is tickers, 601 frames (`BYB/README.md`:32); FX-CLEAN averages about 0.05 prints/s                                                                                           | —                                                                                             | (FX-G4 stands in)                              |

**Fixture gaps** (BQ-11 (a), BQ-12 (a); nothing is filed from here). **FX-G1** a recorded print at or above the default threshold: proposed owner E22-Q03
(#753), with the recorder (E16) for a capture; meanwhile a seeded synthetic sequence. **FX-G2** a recorded burst: E22-Q03 (#753), whose scope is a replayed
burst at 500 / 2 000 / 5 000 prints/s (`E22J`:294). **FX-G3** a seed script and a replay feed that push a fixture into the staging trade stream: proposed
owner E22-Q02 (#752). **FX-G4** the burst harness that delivers a seeded synthetic print sequence at a stated rate into the live path: E22-Q03 (#753); the
in-process helpers that drive the publisher today (`services/api/tests/_bigtrades.py`:1–3, the `World`) are test code a staging tester cannot run, cited as
white-box evidence only. **FX-G5** the read path for Prometheus counters on staging (OQ-1). **FX-G6** a recorded trade sequence gap (only an order-book gap
is recorded): E22-Q03 with E16. Every case that needs one says "blocked on" it and names the injection; a case that names FX-G1 is blocked on FX-G4 until a recorded print
exists; none is marked untestable (ticket AC 3).

## 7. Entry and exit criteria, the regression subset and triage

**Entry** (`03`:407; BQ-14). E22-S01 to S05 are merged to `main`, CI is green, and a deployable build runs on the staging stack; the
fixtures of section 6 and FX-G3, FX-G4 exist; the `22` `getTrades` and `23` §6.1 `trades` contract tests are green; every open question a case depends on is
answered, or the case is marked blocked on it. **At the base** (`7e13e073a`) the backend is merged (E22-T01, T02, T04, X01) and every frontend surface is
unbuilt (no tape feature, no bubble layer, D05:56–57); E22-S01 to S05 are Sprint 12 (`E22J`:377–485). The entry criteria are therefore met for the wire
cases once FX-G3 runs and not met for the UI cases, which is why this PR closes #713 on the document (as #404 and #422 did) and the execution record is
E22-Q05's (#755). The ticket's "six states" are the six Gherkin states D02 lists first (D02:116); D02 draws 23 (D02:120–142).

**Exit** (`03`:403, :409). Every case has a recorded result (pass or fail, build sha, mode), a blocked case carrying its question or owner id; no P0 or P1 is
open; every **[R]** case is automated by E22-Q02 or listed manual with an owner, and every **[F]** case ran; every counter a case names was observed (a †
one by its stand-in, section 10); the charters ran with a debrief (E22-Q05), the perf report (E22-Q03) and the a11y audit (E22-Q04) are attached; section 9
has no gap and every section 10 row is answered or accepted by its owner. This plan's sign-off is necessary, not sufficient: E22-Q05 assembles the epic's.

**Regression subset.** The [R] cases (16 of 65: C01, C02, C04, C06, C15, C16, C24, C30, C32, C37, C38, C42, C50, C56, C57, C58) run every sprint after
exit and on any change to `services/api/candleviewer/orderflow/bigtrade*.py`, `orderflow/limits.py`, `ws/trades_publish.py`, `api/trades.py`, the tape and
bubble code of E22-S01 to S05, the `22` `getTrades` operation, `23` §6.1 `trades` and §14.2, or the deck: the automated ones in CI (E22-Q02), the rest in the
sprint's QA pass. A flaky member is quarantined within 24 h with an owner (C-9.3). Every story section has an **[F]** case: 3.1 C05 to C09; 3.2 C19, C21;
3.3 C29; 3.4 C37; 3.6 C44; 3.7 C56, C57.

### 7.1 Defect triage for this epic

The severities are `03` §11.3's (`03`:322–327); this table maps E22's failures onto them. A missing `(estimated)` badge is P1 by R2 exit criterion 4
(`30`:386) and the ticket.

| Severity | E22 failures                                                                                                                                                                                                                                                                             |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P0**   | a print lost from the stream, the ring or the store with no frame field and no counter reporting it (loss that is not reported); data of another user, account or symbol in a frame, a page or a row                                                                                     |
| **P1**   | a missing or wrong `(estimated)` badge; a popover that contradicts the implemented rule; a flagged set that differs between the WS item, the REST item and the bubble outside C51's three reasons; a wrong effective threshold shown; a highlight that follows a client comparison (C17) |
| **P2**   | an a11y AA failure; a legibility failure at either density or in any theme; a lost pause, buffered count or focus                                                                                                                                                                        |
| **P3**   | wording, spacing, digit grouping while D05-C-14 is open                                                                                                                                                                                                                                  |

Zero open P0 or P1 to leave In Test (`03`:47, :409). Defect reports carry no account identifier in text or screenshots (ticket Security notes).

## 8. What this plan references and does not contain

- E22-Q02 (#752): the automation of these cases and the seed script and replay feed (FX-G3); it is expected to reference the ids `E22-Q01-Cnn` (its suite is linked from this plan's traceability table, `E22J`:267) and takes D04's
  28 `Q02-nn` assertion ids (D05:63).
- E22-Q03 (#753): every budget this plan cites and never measures (≥ 55 fps at 2 000 prints/s, `11`:2189; 5 000 visible bubbles, `11`:2228; D05 §6), the burst
  harness (FX-G4), FX-G1, FX-G2, FX-G6, and `TM` AC9, AC10, AC17, AC18 (`TM`:215–216, :223–224).
- E22-Q04 (#754): the accessibility audit (D05 §9; D04 §10–§14); this plan keeps one black-box leg (C63) and a keyboard and screen-reader smoke (C62).
- E22-Q05 (#755): executes this plan and the charters CH1 to CH4, holds the debrief and assembles the epic's sign-off (`E22J`:350).
- E22-X02 (#756): `TM` AC4 to AC7, AC11 to AC16 and AC19, and the security review of these surfaces (`E22J`:668); AC1 and AC8 are shared, and this plan
  asserts only the black-box answer (C56, C57).
- E22-D06 (#751): design QA of the built surfaces against D05; E22-K01 (#608): the bubble instancing cost and the LOD numbers (D05-C-9); E22-S06 and
  US-BIG-005: alerts, Backlog sprint.

## 9. Traceability

Scenarios are numbered in source order. Every scenario of US-BIG-001, 002, 003, 004 and 006 (15), E22-S01 to S05 (25) and E22-T01, T02, T04 (14) maps to a
case: 54 of 54 (BQ-01); a blocked case still maps, its blocked half marked in the case. Every Must story has an **[F]** case: US-BIG-001 C05;
002 C19; 003 C29; 004 C37.

| Source     | Scenario to cases                                  |
| ---------- | -------------------------------------------------- |
| US-BIG-001 | 1 C01 · 2 C02, C03 · 3 C04                         |
| US-BIG-002 | 1 C16 · 2 C18 · 3 C19                              |
| US-BIG-003 | 1 C26 · 2 C27 · 3 C28                              |
| US-BIG-004 | 1 C32, C33 · 2 C35 · 3 C36                         |
| US-BIG-006 | 1 C42 · 2 C43 · 3 C44                              |
| E22-S01    | 1 C01 · 2 C02, C03 · 3 C04 · 4 C06 · 5 C09         |
| E22-S02    | 1 C16, C17 · 2 C18 · 3 C19 · 4 C20 · 5 C21         |
| E22-S03    | 1 C26 · 2 C27 · 3 C28 · 4 C29 · 5 C30              |
| E22-S04    | 1 C32, C33 · 2 C35 · 3 C36 · 4 C37 · 5 C38         |
| E22-S05    | 1 C42 · 2 C43 · 3 C44 · 4 C45 · 5 C46              |
| E22-T01    | 1 C16, C24 · 2 C18 · 3 C39 · 4 C36 · 5 C19 · 6 C22 |
| E22-T02    | 1 C58 · 2 C34 · 3 C57 · 4 C32, C50 · 5 C02         |
| E22-T04    | 1 C24 · 2 C40 · 3 C39                              |

The global acceptance criteria: **#3** a11y C14, C30, C46, C62, C63 · **#5** actionable errors C60 · **#6** the estimated badge C37 and section 3.9 (HC-1 to
HC-11), C18 · **#7** partial history C09.

The ticket's items: the cross-surface invariant C50 to C55 · the edge matrix: threshold 0 C23; threshold above every print C24; percentile with less history
than the window C25; clustering window 0 C38, C57 and 5 000 ms C49 (REST only), C57 (WS 2 000); tolerance 0 and 20 C41, C56, C57; WS disconnect mid-burst C07;
sequence gap C08; thin-book symbol C10, C44; symbol switch mid-pause C65; reload with filters and columns C48 · the four charters CH1 to CH4 · the fixture
list section 6 · entry, exit and triage section 7 · the honesty checklist section 3.9 · the observability counters C02, C58, C59 and section 10 · the
performance observables C03, C29 · keyboard-only and screen reader C62.

The threat model's rows (`TM` §7, §9; BQ-09): the boundary-table duty (`TM`:179) C56, C57 · AC1 C56 · AC2 C56 · AC3 C56 · AC8 C56, C57; AC4 to AC7, AC9 to
AC19 are section 8's.

## 10. Open questions

Each row is a question for the owner of the source it names, not a guess (BQ-04, BQ-20). A case it blocks says so; the other cases of the same
story run. Every † and blocked row is re-grepped at the READY sha (section 0).

**10.1 D05's open rows carried by id** (D05 §11, D05:495–541; due 2026-12-11, the start of Sprint 12, D05:495). A case is blocked on a row only where the row
changes an expected value: **D05-C-3** 2 000 against 5 000 (C49, C57; E22-S04 #717); **D05-C-6** the served default window 0 against the drawn 250 ms (C38;
E22-S04 with the `22` owner); **D05-C-11** tier 2 client-side (C54; D04's owner, E22-S01); **D05-C-12** and **D05-C-13** the Rows control's presets and
five keys for four inputs (C20, C35; D02's owner, E22-S02, E22-S04); **D05-C-14** digit grouping (section 0; the `15` owner); **D05-G-2** no write path from a
saved threshold to the engine (every threshold-mode case; the `22` owner through E22-S02 #715); **D05-G-3** no key for the scale or tier 2 (C27, C54);
**D05-G-4** the range message (C21; D02's owner, E22-S02); **D05-G-1** D02's boards undrawn (#507): this plan asserts the text, never drawings. Parent rows that
bind: D02-G4 (no tape keymap context, C62), D02-G7 (the full-ring policy, C05), D02 G10 (the `big_trade` methodology section, HC-6), D02 G11 and D02-G1 (the
`tape.*` events have no schema, the † table), D02 Q6 and Q7 (open, bind E22-S02: C19), A15-4 to A15-8 (open, the `15` owner: C42 to C46), D03-Q2, Q3, Q4
(open), D04 G-2 (the opt-in's key, C62) and G-5 (the tape frame test, C03).

**10.2 This plan's differences between the ticket and the merged sources** (C-rows; each case asserts the merged source):

| Row      | Difference                                                                                                                                                                                   | Cases     | Owner                                      |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------------------ |
| C-5000   | the ticket's "clustering window … at the 5 000 ms maximum" holds on REST only; WS stops at 2 000 (`LIM`:15–16; `23`:787–788) and so does the panel (D05-C-3)                                 | C49, C57  | E22-S04 #717                               |
| C-PCT    | the deck's PROPOSED `d05.05.range` says "a percentile is 0 to 100", while the engine refuses 0 and 100 (`bigtrade_models.py`:41, `0 < self.value < 100`); the plan cites the engine's bounds | C21       | E22-D05 (a versioned delta), E22-S02 #715  |
| C-400    | `TM` AC2 and AC8 expect "400"; `22` answers a parameter outside its schema with 422 `validation_failed` (`22`:4691–4697)                                                                     | C56       | the `TM` owner, E22-X01                    |
| C-CURSOR | `22` `Cursor` and `TM` AC2 set cursor expiry and refusal rules that this plan cannot assert at the base                                                                                      | C56       | the `22` owner with E22-X02 #756           |
| C-BIT2   | T02.2 says binary kind-3 records set flags bit2; a window holding a multi-print cluster leaves structured, so bit2 is not set on `trades` (`23`:257; `TP`:30–33, :467)                       | C34       | the `23` owner, E22-T02                    |
| C-CFLAG  | a cluster is big when any member is flagged, with no test of the total (`23`:791, `23`:2861)                                                                                                 | C52       | the `22`, `23`, `24` owners                |
| C-CSIZE  | US-BIG-004/1 sums the qualifying prints; the engine sums every evaluated member (`bigtrade.py`:174; `24`:600)                                                                                | C33, C53  | the `24` owner with the `11` owner         |
| C-CPOS   | the mark sits at the cluster's `vwap` (D03:206); the item and the row carry the first print's price (`23`:791)                                                                               | C53       | D03's owner with the `23` owner            |
| C-TIER2  | tier 2 and the bubble cap are a client-side 4× (D02:101, D02:249); S02.1 forbids a client comparison against the threshold                                                                   | C54       | E22-S02 #715, D04's owner (D05-C-11)       |
| C-ACC    | the popover says "same price … within 250 ms / 1 tick"; the rule is a price bucket with no anchor check (`BC`:5–6; `24`:597)                                                                 | C37, C41  | D02's owner, E22-S04 #717                  |
| C-FAIL   | the popover names no failure mode (S04.4; `30`:386)                                                                                                                                          | C37       | D02's owner, E22-S04 #717                  |
| C-WHY    | "Why estimated?" opens a section with no wording (D02 G10; D05:609)                                                                                                                          | C37       | E22-S04 #717, E25-D05                      |
| C-BAR    | US-BIG-004/3 wants the bar rule in the tooltip; the drawn tooltip names the bar only (`d02.13.cp19`)                                                                                         | C36       | D02's owner, E22-S04 #717                  |
| C-NAMES  | the ticket's `tape_prints_dropped_total` and `tape_frames_coalesced_total` ship as `cv_ws_tape_prints_dropped_total{reason}` and `cv_ws_tape_frames_coalesced_total` (`WM`:162–173)          | C59       | the ticket text (E22-Q01's own; no action) |
| C-14DATA | `14`:1271 says "thresholds applied client-side; percentile thresholds computed server-side via GET /api/v1/market/metrics"; the threshold is the engine's, echoed on the tape (`23`:790)     | C15, C17  | the `14` owner                             |
| C-STATES | the ticket says "six states"; D02 draws 23 with the six Gherkin ones first (D02:116, D02:120–142)                                                                                            | section 7 | none (the plan covers the 23)              |
| C-THEMES | the ticket says both themes; the design resolves three (D05:288–290)                                                                                                                         | C64, CH4  | none (the plan covers three)               |

**10.3 Open questions** (no merged source answers them; both readings stated where there are two):

- **OQ-1** How a QA tester on the staging stack reads the counters (BQ-16 rider). The process registry is served by a private-bind
  `/metrics` listener on `CV_METRICS_BIND` (`services/api/candleviewer/observability/metrics_server.py`:1–4) and by the health router's `/metrics`
  (`services/api/candleviewer/api/health.py`:159–161). This corrects the BQ list's U1, which found no route. Who on staging may read it, and from where, is
  not stated. Owner: the observability owner (E04 / E42). Until answered, a case whose 2nd record is a counter asserts the frame fields as its stand-in
  (C02, C58, C59).
- **OQ-2** What a symbol switch does to a pause and its buffered count (C65). D02 §5 and D04 §9 name no symbol switch. Owner: E22-S01 #714 with D02's owner.
- **OQ-3** Whether a replay session serves `trades.{symbol}` end to end (C02). Reading A (ticket; `30`:383 R2 exit 1): one pipeline for live and replay, so a
  replayed burst tests the live path. Reading B (`TP`:376–379, `TP`:608–609): the publisher serves live subscriptions only and a replay subscription stays
  pending; not run. Owner: E22-T02's owner with E26. The plan uses FX-G4 into the live path meanwhile.
- **OQ-4** What D02 S14's "first available timestamp" names: the hot tape's head or the recording start (C09). Owner: E22-S01 with E16-D05.
- **OQ-5** Whether a `ctl` that changes `cluster_window_ms` or `cluster_tolerance_ticks` re-snapshots (C35); `23`:789 says so of `min_size` only. Owner: the
  `23` owner through E22-S04.
- **OQ-6** Whether the display filters persist across a reload (C48); S05.2 says so of the columns only. Owner: E22-S05 #718 with E15.
- **OQ-7** How many DOM-mirror nodes the bubble layer keeps at 5 000 marks (C26, C29; "sparse", D02:269). Owner: E22-S03 #716 with E22-K01 #608.

**10.4 The third surface** (BQ-05): **G-M1** `GET /market/metrics` is not mounted at the base and its big-trade series are aggregates
(C55). The per-series leg is blocked on #645 / #658; the stand-in is the aggregate counter check of C55, never per print.

**Known gaps: metrics and events with no emitter on `main`** (a `git grep` of `services/`, `apps/`, `packages/`, `tools/` and `infra/` at the base finds
none; a † marks each use in a case). A case asserts the stand-in until the owner ships it. Emitters that **exist** and are asserted directly:
`cv_ws_frames_emitted_total{topic}`, `cv_ws_tape_prints_dropped_total{reason}` (`min_size`, `overflow`), `cv_ws_tape_frames_coalesced_total`,
`cv_ws_trades_subscribe_rejected_total{reason}` (`min_size_floor`, `cluster_range`, `sub_cap_user`, `option_sets`, `symbols`) (`WM`:157–182);
`cv_ws_resync_total{reason}` (`services/api/candleviewer/ws/sequencing.py`:189–197); `bigtrade_prints_evaluated_total`, `bigtrade_flagged_total`,
`bigtrade_clusters_emitted_total`, `bigtrade_eval_latency_seconds`, `bigtrade_state_truncated_total`, the threshold-too-low counter,
`bigtrade_input_rejected_total`, `bigtrade_range_rejected_total` (`BM`:23–57); and the frame fields `dropped`, `coalesced`, `coalesced_count`
(`23`:2868–2880).

| Metric or event                                                                        | Cases              | Named by (owner)                                                          | Assert meanwhile                                                                 |
| -------------------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `ws_subscribe_rejected_total{reason}` with `sub_cap_connection` and `rbac`             | C57                | `TM`:229–230 (E22-X01)                                                    | `cv_ws_trades_subscribe_rejected_total{reason}` for the reasons it has           |
| `bigtrade_state_truncated_total{kind}` (`cluster_keys`, `prints_buffer`)               | C59                | `TM`:230 (E22-X01); shipped with a `symbol` label                         | `bigtrade_state_truncated_total{symbol}` (`BM`:35–39)                            |
| `bigtrade_fanout_dropped_total`                                                        | C02, C59           | `TM`:231 (E22-X01)                                                        | the frames' `dropped` and `cv_ws_tape_prints_dropped_total{reason="overflow"}`   |
| `bigtrade_client_resync_total`                                                         | C06, C08           | `TM`:232 (E22-X01)                                                        | `cv_ws_resync_total{reason}`                                                     |
| the client `ringbuffer_trimmed` event                                                  | C05                | `TM`:233 (E22-S01)                                                        | the chip "Paused — buffer full · 10 000 kept" and the divider's "not kept" count |
| `tape.paused`, `tape.resumed`, `tape.filter_changed`, `tape.print_clicked` (analytics) | C04, C13, C30, C42 | `14`:1278; D05 §7 "named, unsourced" (the analytics-event contract owner) | the chip, the divider and the announcement for each action                       |
| `bigtrade_threshold_changed_total{mode}`, `bigtrade_cluster_config_changed_total`      | C18, C35           | `E22J`:404, :459 (E22-S02, E22-S04; D05:246)                              | `sub_ok.effective` after the change                                              |
| the burst harness, the seed script and the replay feed (FX-G3, FX-G4)                  | section 6          | E22-Q02 #752, E22-Q03 #753                                                | —                                                                                |
| the read path for counters on staging (FX-G5)                                          | C02, C58, C59      | OQ-1 (E04 / E42)                                                          | the frame fields                                                                 |
