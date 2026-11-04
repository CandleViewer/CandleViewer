# E49-D01 — Design-QA audit protocol and the per-screen ledger

**Ticket:** E49-D01 (#1330) · Task · Sprint 23 · labels `type/chore`, `area/design-system`, `design`,
`design-qa`, `a11y`, `priority/p1` · parent E49 · **Status: Draft — owner approval pending; BQ-0 … BQ-9 are
the defaults built, ruling pending (§2).** Branch `design/e49-design-qa-protocol`. **Slice: PR 1 of 2** —
this protocol, its self-check `scripts/design_qa_ledger_check.py`, the fixture ledgers under
`tests/fixtures/design_qa/` and one cross-link line in `16` §12. PR 2 (the closing slice) commits the two
ledgers and the pilot results after E47-X01 (#1326) lands. Both PRs carry `Refs #1330` and `Partial:`.

**Base.** Every cite is to `main` at `a53a5b438`. Blockers: E47-K01, E47-T01, E47-T02 and E47-T03 are
merged; E47-X01 (#1326) is open and non-gating for authoring (orchestrator ruling, 2026-11-04): DR-1 holds
its place until it lands. E47-D01 (#1300) is authored in parallel; it is cited "if it merges as is" (DR-2).

**Honest scope.** Agent-authored. Nothing in this slice audits a screen, and no participant, reviewer or
timing is claimed. Every number is PROPOSED unless RULED; every pilot finding will be labelled
`(agent-run)`; the actionable rate and the effort figures do not exist until PR 2. Findings are routed,
never edited into a spec, a catalogue or a build (ticket Out of scope "Fixing anything").

## 1. Acceptance and Definition-of-Done trace

| Row   | Asks                                                                | State | Where                                                                    |
| ----- | ------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------ |
| AC 1  | one ledger row per catalogue SCR id; a missing id fails             | done  | §11; `E_MISSING` (fixture `missing-row.csv`); the ledger itself in PR 2  |
| AC 2  | a finding is actionable without a conversation                      | done  | §10's record: the clause, token or state, expected, observed, cell, pair |
| AC 3  | ≥ 80 % of pilot findings actionable; ambiguous steps revised        | PR 2  | §13; the pilot runs after E47-X01 lands                                  |
| AC 4  | an accepted exception names owner, reason and follow-up key         | done  | §12; `E_EXCEPTION` (fixture `exception-without-owner.csv`)               |
| AC 5  | 3 themes × 2 densities per audited screen, or a written N/A         | done  | §8's cell matrix and its N/A rule                                        |
| DoD 1 | protocol merged; reviewed by the design-system lead and an engineer | owner | the owner's `approved` comment (agent-delivery adaptation)               |
| DoD 2 | ledger committed; self-check green in CI                            | PR 2  | the ledger in PR 2; CI wiring is Deviation V-3                           |
| DoD 3 | 10-screen pilot run, findings filed, actionable rate recorded       | PR 2  | §13                                                                      |
| DoD 4 | calibrated effort figures size E49-S04                              | PR 2  | §13; a comment on #1384                                                  |
| DoD 5 | severity mapping agreed with QA and recorded                        | owner | §7 (PROPOSED); walkthrough item 1                                        |
| DoD 6 | `16` §12 cross-links the protocol                                   | done  | one line after the checklist (BQ-1)                                      |
| DoD 7 | design sign-off recorded on the ticket                              | owner | §18                                                                      |
| DoD 8 | pilot findings walked through at Sprint Review                      | PR 2  | §18's session protocol                                                   |
| DoD 9 | merged via merge queue with required approvals                      | open  | the orchestrator merges after two approving reviews (C-10.1)             |

## 2. The questions BQ-0 … BQ-9 — defaults built; ruling pending (comment 6634720626)

The list is comment 6634720626 on #1330. Each bullet below is the ORCH-default as built; it flips to RULED
when the ruling of record lands.

- **BQ-0 — standing rules.** Built as: text first, `Refs #1330` + `Partial:` while E47-X01 is open; the
  E09-D09 T2 standing gate (`.claude/rules/32-design-specs.md`) applies to every gated control the protocol
  names; findings routed, never fixed; demo env and fixture symbols only (C-2.11); ≤ 1,500 counted lines
  per PR (C-4.8); the shared helper imported, never copied; E47-D04 (focus) and E47-D09 (keys) outrank this
  protocol (a disagreement is an F-row); the ≤ 10-item checklist (§18) is posted at READY.
- **BQ-1 — one procedure, not two.** Built as: E09-D11 §16 (PS-1..PS-10) is the spine (§5); this protocol
  adds the screen layer; ONE cross-link line in `16` §12 supersedes E09-D11's A-1; the five groups of `16`
  §12 are copied, not four (§4); PR 1 = protocol + self-check + fixtures, PR 2 = ledgers + pilot.
- **BQ-2 — two ledgers, no exporter change.** Built as: `e49-design-qa-ledger.csv` stays the finding
  ledger in the exporter's five columns; `e49-design-qa-screens.csv` is the per-screen ledger; the
  self-check cross-checks them (§11). Both land in PR 2, whose body states that its merge starts the
  failing push run until the owner provisions the secret and a transport (walkthrough item 3).
- **BQ-3 — the row set and E47's verdicts.** Built as: 149 rows (the `### SCR-` headings); the ten
  reserved ids are named (§11) and rejected; two added columns `e47_verdict` and `e47_ref` are read from
  the E47-D02 register, never retyped; the owning epic is derived from each screen's stories, ties listed.
- **BQ-4 — one severity scale.** Built as: P0..P3 only (§7); P0 only for `03`'s P0 class; PS-7 and the
  E47 labels mapped onto it; any WCAG 2.2 AA failure ≥ P2; Info → notes, never a finding row. PROPOSED;
  "agreed with QA" is walkthrough item 1.
- **BQ-5 — the audit order.** Built as: the first tier by NAME = SCR-030, SCR-050, SCR-060, SCR-063,
  SCR-074; then by Must-story weight from `18` §2, ties by id, computed by the tool (§6); chart sampling
  keeps the ticket's 030..054 range at three SYNTHETIC densities (§9).
- **BQ-6 — the evidence standard.** Built as: Penpot boards (page name + id only) vs Storybook or fixture
  builds; demo env and fixture symbols only; a written N/A per missing cell; the reference-machine,
  `balanced`-profile and diagnostics checks are an owner-run leg (§8); text-only legs draw no boards.
- **BQ-7 — the pilot.** Built as: the top ten of §6's order that are built at the base (§6.2);
  "actionable" judged by the two independent review lenses against §10's six fields, rate `(agent-run)`;
  filing per PS-9; effort as measured agent wall time beside the 15 / 45-minute seeds, never converted.
- **BQ-8 — exceptions and near-duplicates.** Built as: the follow-up key is an existing backlog key or a
  `post-ga` issue number, validated by the self-check; this PR files none; near-duplicates go to `15` as
  A-rows to the catalogue owner, never a new id (§12).
- **BQ-9 — the self-check.** Built as: `scripts/design_qa_ledger_check.py` with fixtures under
  `tests/fixtures/design_qa/`; it imports the shared helper by path; `--check` / `--self-test` in the
  E09-D12 shape; pytest under `scripts/tests/`; CI wiring is Deviation V-3 (§20).

## 3. Method

1. **Spine.** E09-D11 §16 (E09-D11 :515–526) is the merged design-QA procedure for later epics (RULED BQ-25
   there). This protocol takes PS-1..PS-10 unchanged (§5) and adds what a screen sweep needs: the clause
   list, the order, the severity map, the evidence cells, the sampling rule, the record, the two ledgers
   and the exception rule.
2. **Clauses.** The checklist of `16` §12 (`16` :686–724) is copied item by item into §4; the self-check
   compares each row with the base, so a reworded clause fails.
3. **Inputs read, not retyped.** The screen list from `14` (149 headings, `14` :13–35 for the bands), the
   story weights from `18` §2 (`18` :44), the E47 verdicts from `docs/plan/a11y/47-audit-register.json`
   (catalogue: 47-audit-catalogue.md :5), the severity taxonomy from `03` §11.3 (`03` :320–327) and the
   exporter's header from `tools/ga_defects/ledger.py` (ledger.py :17).
4. **Precedents for form.** E05-D05 (component-library QA, E05-D05 :1), E09-D11 (auth surfaces),
   E12-D13 (fixture-only captures, E12-D13 :3) and E08-D14.

## 4. The clauses (the five groups of `16` §12, verbatim)

The ticket's Scope says "four checklist groups" and then lists five; `16` §12 has five (F-1). Every finding
names one clause id. The floor column is the lowest severity a finding of that clause may carry (§7).

| Clause  | Group                   | Checklist item (verbatim)                                                                                                                                                                                        | Floor |
| ------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| DQ-TV-1 | Tokens & visual         | Uses only published Tier-2/Tier-3 tokens — zero hardcoded hex/px values in the spec or the implementation.                                                                                                       | P3    |
| DQ-TV-2 | Tokens & visual         | Verified in all three themes (dark, light, high-contrast) at both density modes (compact, comfortable) — visual parity confirmed, no theme/density-specific layout breakage.                                     | P3    |
| DQ-TV-3 | Tokens & visual         | Passes the automated contrast-matrix check for every colour pair it introduces or touches.                                                                                                                       | P2    |
| DQ-TV-4 | Tokens & visual         | CVD (colour-blindness) simulation reviewed for any new colour-carrying state.                                                                                                                                    | P2    |
| DQ-BS-1 | Behaviour & states      | Every documented State (default/hover/focus/active/disabled/loading/error/empty) has a corresponding Figma variant and Storybook story.                                                                          | P3    |
| DQ-BS-2 | Behaviour & states      | Disabled states use the disabled-with-reason pattern (CMP-079), never a bare disabled control, for any RBAC/env-gated action.                                                                                    | P2    |
| DQ-BS-3 | Behaviour & states      | Loading/empty/error states are explicitly designed, not left as "the same as default but greyed out."                                                                                                            | P2    |
| DQ-AX-1 | Accessibility           | Keyboard-interaction table completed and matches an implemented, tested keyboard path (not aspirational).                                                                                                        | P2    |
| DQ-AX-2 | Accessibility           | Accessible-name/role table completed.                                                                                                                                                                            | P2    |
| DQ-AX-3 | Accessibility           | For any canvas/WebGL-adjacent component: DOM-mirror/windowed-tree/non-spatial-alternative strategy explicitly specified per `05-accessibility-standard.md` §6, not deferred to "engineering will figure it out." | P2    |
| DQ-AX-4 | Accessibility           | Motion-safe/motion-reduce pair specified for any animated property.                                                                                                                                              | P2    |
| DQ-AX-5 | Accessibility           | Hit targets meet the 24px minimum (compact) / 40-44px (comfortable), or an essential-exception is logged with its compensating control.                                                                          | P2    |
| DQ-AX-6 | Accessibility           | Accessibility role has signed off (§13).                                                                                                                                                                         | P2    |
| DQ-TS-1 | Trading-specific safety | Any component touching order placement, position modification, or rule arming states its confirm-gate variant (standard/typed/hold) explicitly and the keyboard-only path for that gate is tested.               | P1    |
| DQ-TS-2 | Trading-specific safety | Any heuristic/estimated value is chip-tagged and links to its methodology InfoPanel.                                                                                                                             | P2    |
| DQ-TS-3 | Trading-specific safety | Demo/Live env context is visually unambiguous wherever the component can trigger a trading action.                                                                                                               | P1    |
| DQ-CO-1 | Consistency             | Reuses an existing CMP-* rather than introducing a near-duplicate (checked against the catalogue index before a new ID is requested).                                                                            | P3    |
| DQ-CO-2 | Consistency             | Storybook stories match the full Variants × States matrix stated in the catalogue entry.                                                                                                                         | P3    |
| DQ-CO-3 | Consistency             | Component or screen composes only published-library Figma components (no local detached overrides).                                                                                                              | P3    |

"Figma" in a clause reads as Penpot (agent-delivery adaptation); the clause text stays verbatim. The
Accessibility floor is the ticket's "P2 minimum"; the two safety floors follow `03`'s P1 class (a broken
gate with a workaround) and rise to P0 under §7's rule.

## 5. The procedure for one screen

PS-1..PS-10 of E09-D11 §16 apply unchanged. The screen layer adds DQ-1..DQ-8:

- **DQ-1 Pick.** The next unaudited row of §6's order; a screen not built at the base keeps an empty
  verdict (§11) and is skipped, never marked `not-applicable` for being unbuilt.
- **DQ-2 Inputs (PS-1).** The screen's `14` entry (its States, A11y and Design sign-off acceptance
  checklist lines), its spec under `docs/design/`, its Penpot page (name + id only), its stories and the
  E47 register row; each read at the base (PS-2).
- **DQ-3 Cells.** Capture the six cells of §8 (or write each N/A), on a demo session with fixture symbols.
- **DQ-4 Walk the clauses.** §4 in order, each clause pass / finding / not-applicable with a reason;
  accessibility clauses take E47's verdict as recorded and add only what E47 does not cover (AD-10).
- **DQ-5 Write rows (PS-5, PS-6).** One finding, one record (§10), one severity (§7); a known record cited
  by id, not restated.
- **DQ-6 Route (PS-9).** P0, P1 and security rows: an issue by id, class and clause; the rest: the finding
  ledger and a comment on the open owner ticket. Never a fix in the QA PR (PS-10).
- **DQ-7 Ledger row.** Verdict, counts, bug keys and notes per §11; the self-check must stay green.
- **DQ-8 Time.** Record the wall time per screen for §13's effort model.

E47-D04 (focus) and E47-D09 (keys) outrank every clause: where the build follows them and a screen spec
does not, the finding goes to the screen spec's owner as an F-row, never a silent merge.

## 6. Audit order and the pilot

### 6.1 The first tier and the weight rule

Trading-critical screens go first, by name; the ticket's ids are re-read at the base (F-2): SCR-051 is the
heatmap settings dialog and SCR-070 the algo monitor, so both fall to their weight. Every other screen is
ordered by its count of Must stories in `18` §2 (a story counts once per screen its Screens cell names),
ties by id. The tool computes the order (`--order`); nobody hand-orders it.

| Tier  | SCR     | Name                                              | Must stories |
| ----- | ------- | ------------------------------------------------- | ------------ |
| first | SCR-030 | Chart panel (price + footprint)                   | 13           |
| first | SCR-050 | Heatmap + DOM ladder panel (the DeepDOM analogue) | 6            |
| first | SCR-060 | Order ticket panel (single account)               | 6            |
| first | SCR-063 | Positions & orders grid panel                     | 8            |
| first | SCR-074 | Environment switcher (Demo ↔ Live)                | 4            |

### 6.2 The pilot ten (PROPOSED; computed at the base)

The top ten of the order whose E47-D02 coverage is built (`covered`, `partial` or `unreachable: built, not
mounted`); a screen that is not built is skipped for the next built one. Coverage is E47-D02's at its
audited sha; PR 2 re-computes the ten at its own base. Of the first tier only SCR-030 is built.

| #   | SCR     | Name                                            | Rank | Must stories | E47 coverage                    |
| --- | ------- | ----------------------------------------------- | ---- | ------------ | ------------------------------- |
| 1   | SCR-030 | Chart panel (price + footprint)                 | 1    | 13           | unreachable: built, not mounted |
| 2   | SCR-010 | App shell (global chrome)                       | 14   | 4            | partial                         |
| 3   | SCR-041 | Symbol/interval quick-switcher (in-chart)       | 30   | 3            | unreachable: built, not mounted |
| 4   | SCR-103 | Symbol info / instrument detail                 | 38   | 3            | unreachable: built, not mounted |
| 5   | SCR-152 | Disconnected / reconnecting state               | 44   | 3            | partial                         |
| 6   | SCR-001 | Login                                           | 45   | 2            | covered                         |
| 7   | SCR-004 | Forced password change                          | 46   | 2            | covered                         |
| 8   | SCR-011 | Navigation rail (expanded) & workspace switcher | 47   | 2            | covered                         |
| 9   | SCR-014 | Notification centre (right-rail drawer)         | 49   | 2            | partial                         |
| 10  | SCR-015 | Global toast host                               | 50   | 2            | covered                         |

## 7. The severity map (PROPOSED)

The ledger records P0..P3 only (`03` :320–327). The ticket's four anchors stand verbatim in the rule column.

| Source label                                                                                     | Ledger | Rule                                                                        |
| ------------------------------------------------------------------------------------------------ | ------ | --------------------------------------------------------------------------- |
| a secret shown, or a safety-clause breach that can send an order in the wrong env or unconfirmed | P0     | `03`'s P0 class only; an issue at once (PS-9)                               |
| PS-7 Blocking                                                                                    | P1     | a frozen string, a focus-map regression, a task not completable by keyboard |
| E47 blocker                                                                                      | P1     | recorded from the register, never re-derived                                |
| token drift that changes a trading signal's meaning                                              | P1     | ticket anchor                                                               |
| PS-7 Major                                                                                       | P2     | —                                                                           |
| E47 major                                                                                        | P2     | —                                                                           |
| missing designed empty/error state                                                               | P2     | ticket anchor                                                               |
| a11y AA violation                                                                                | P2     | ticket anchor: P2 minimum, whatever its source label                        |
| PS-7 Minor                                                                                       | P3     | raised to P2 when the clause is an Accessibility clause                     |
| E47 minor                                                                                        | P3     | raised to P2 when it is a WCAG 2.2 AA failure                               |
| wrong-but-readable spacing                                                                       | P3     | ticket anchor                                                               |
| PS-7 Info, E47 info                                                                              | notes  | never a finding row                                                         |

## 8. The evidence standard

**Cells.** Each audited screen is compared in six cells: dark, light and high-contrast × compact and
comfortable (`16` :693). The reference is the screen's Penpot boards (page name + id, never a host or file
reference); the build is its Storybook stories or a fixture build. A missing cell carries its written N/A
reason in the record (AC 5's "Or" arm), for example "no high-contrast board drawn: the text is binding".

**Hard rule (C-2.11, ticket Security notes).** Captures use the demo environment and fixture symbols only:
never a live account, never a real API key fragment, never a real balance. A capture that breaks the rule is
deleted and the run continues (PS-10); the row records only that a capture was withdrawn.

**Owner-run leg.** The reference machine, the `balanced` performance profile of SCR-118 (`14` :2513) and
SCR-046's diagnostics confirming the engine is not in `degraded-2d` (`14` :1122) need a running desktop
build; the agent run names this leg and its hardware class and never claims it.

**Files.** Capture PNGs ride in PR 2 under `qa/evidence/e49/design-qa/` and count under the C-4.8 note;
text-only legs draw no boards.

## 9. The sampling rule for chart surfaces

SCR-030 … SCR-054 (the ticket's range; `14` §3 is 030..049 and 050..059 is order flow, F-3) are audited at
three data densities — sparse, typical and extreme footprint density — each a labelled SYNTHETIC sample from
the seeded chart-engine bench generators (`packages/chart-engine/bench/fixtures/`). No recorded symbol-day
exists; a re-check row for E49-S04 names the screens to repeat once a capture does.

## 10. The finding record (AC 2)

Every finding, in the ledger and in any issue, carries these fields; a record missing one is not filed:

1. **Clause** — one §4 id, with its group.
2. **Token or state** — Tier-2/Tier-3 names only, never hex: "uses `color.surface.raised` where the spec
   says `color.surface.sunken`"; or the state name from the screen's `14` States line.
3. **Expected** — the value from the Penpot board or the spec, with its cite.
4. **Observed** — the value in the build, with the story or fixture build named.
5. **Cell** — the theme and density it reproduces in (or "all six").
6. **Pair** — the reference and build capture file names.

Plus the PS-5 cells: class (implementation defect, accepted divergence, specification gap), severity (§7),
owner ticket, and the reproduction note.

## 11. The two ledgers and the self-check

**Finding ledger** `docs/plan/backlog/artifacts/e49-design-qa-ledger.csv` — the exporter's header
`finding_id,severity,status,component,opened` (ledger.py :17): `finding_id` is `DQA-nnnn`, `severity`
P0..P3, `status` open|in-progress|fixed|accepted|wontfix, `component` the screen id, `opened` an ISO date.
This schema is owned here (ledger.py :1); the exporter is unchanged.

**Screen ledger** `docs/plan/backlog/artifacts/e49-design-qa-screens.csv` — one row per `### SCR-` heading:
`screen_id,screen_name,owning_epic,auditor,audit_date,verdict,p0,p1,p2,p3,bug_keys,notes,e47_verdict,e47_ref`.
The verdict is `pass`, `findings`, `accepted-exception` or `not-applicable`, or empty while the screen is
unaudited. Reserved ids (never rows): SCR-007, SCR-008, SCR-009, SCR-105, SCR-106, SCR-107, SCR-108,
SCR-109, SCR-138, SCR-139.

**Self-check rules** (`scripts/design_qa_ledger_check.py --ledger SCREENS FINDINGS`):

| Code          | Fails when                                                                                      |
| ------------- | ----------------------------------------------------------------------------------------------- |
| `E_HEADER`    | the screen ledger's header is not the one above                                                 |
| `E_MISSING`   | a catalogue id has no row (AC 1)                                                                |
| `E_EXTRA`     | a row's id is not a catalogue heading; `E_RESERVED` when it is a reserved id                    |
| `E_DUP`       | an id appears twice                                                                             |
| `E_NAME`      | a row's name differs from its catalogue heading                                                 |
| `E_VERDICT`   | the verdict is outside the four words and empty                                                 |
| `E_AUDIT`     | an audited row lacks auditor or ISO date, or an unaudited row carries either, a count or a key  |
| `E_COUNTS`    | a count is not a whole number; `pass` with a finding; `findings` with none                      |
| `E_BUGKEY`    | a `findings` row has no bug key, or a key is not `#N`, a backlog key or a `DQA-nnnn` id         |
| `E_EXCEPTION` | an `accepted-exception` row lacks `owner:` or `reason:` in its notes, or a follow-up key (AC 4) |
| `E_NA`        | a `not-applicable` row lacks `reason:` in its notes                                             |
| `E_EPIC`      | the owning epic is not `Enn`, or `Enn;Enn` for a tie                                            |
| `E_E47`       | `e47_verdict` differs from the register's verdict, or `e47_ref` from its audited sha (9 hex)    |
| `E_FINDINGS`  | the finding ledger fails the exporter's parser or has a malformed row                           |
| `E_CROSS`     | a row's four counts differ from its screen's finding rows, or a `DQA-` key names no finding row |

## 12. Accepted exceptions and near-duplicates

An `accepted-exception` row carries `owner: <ticket key or the owner>; reason: <text>` in its notes and its
follow-up key in `bug_keys`: an existing backlog key or a `#N` issue labelled `post-ga` (plan-first: no new
follow-up tickets; an exception that needs one is a question to the orchestrator). The E49-T03 inventory
(#1342) holds the owner-dated risks; an exception that is a risk is cited there, not restated. A
near-duplicate component found in the pilot is an A-row to `15` for the catalogue owner; no new `CMP-` or
`SCR-` id is created (ticket Out of scope).

## 13. The pilot and the effort model (PR 2)

The pilot audits §6.2's ten screens by §5. Each finding is classified actionable or needs-clarification by
the two independent review lenses against §10's six fields; the rate is stated `(agent-run)` and the owner's
confirmation is pending until recorded. A step that produced an ambiguous finding is revised in PR 2 before
the sweep is commissioned (AC 3). Effort is the measured agent wall time per pilot screen, labelled, beside
the ticket's seeds (about 15 minutes per simple state screen, 45 per dense trading screen), never converted;
the sizing note for E49-S04 is a comment on #1384.

## 14. Findings from authoring this protocol

| F    | Finding                                                                                       | Evidence                                         | Routed to                      |
| ---- | --------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------ |
| F-1  | the ticket and E05-D05 say "four" checklist groups; `16` §12 has five                         | `16` :690, :697, :703, :712, :718; E05-D05 :4    | E49 plan JSON (the owner)      |
| F-2  | the ticket's first-tier ids are stale: SCR-051 is a settings dialog, SCR-070 the algo monitor | `14` :1234, :1534, :1687                         | E49 plan JSON (the owner)      |
| F-3  | the chart band is 030..049; the ticket's 030..054 sampling range spans order flow             | `14` :27–28                                      | E49 plan JSON (the owner)      |
| F-4  | the ticket's per-screen columns collide with the exporter's per-finding header                | ledger.py :17; run.py :21                        | E49-T02 #1341 (comment)        |
| F-5  | E09-D11's A-1 cross-link was never applied to `16` §12                                        | E09-D11 :513                                     | this PR (one line, BQ-1)       |
| F-6  | the ticket says 159 ledger rows; the catalogue has 149 headings and ten reserved ids          | `14` :25, :32, :34                               | E49 plan JSON (the owner)      |
| F-7  | three severity scales are in force (`03`, PS-7, E47)                                          | `03` :324–327; E09-D11 :523                      | §7; walkthrough item 1         |
| F-8  | most screens are not built, so the evidence standard cannot be met for them yet               | 47-audit-catalogue.md :18                        | E49-S04 #1384 (comment)        |
| F-9  | the ticket body's sprint (S22) is stale; the JSON's is Sprint 23                              | the ticket Context; `docs/plan/backlog/E49.json` | E49 plan JSON (the owner)      |
| F-10 | the export's push target is unprovisioned and the pushgateway binds to the loopback interface | design-qa-ledger-export.yml :36–41               | the owner (walkthrough item 3) |
| F-11 | there is no `docs` CI job to wire the self-check into                                         | `.github/workflows/pr.yml` path filter `docs`    | E49-T01 #1340 (comment)        |

All eleven are documentary (read from the repository), not `(heuristic)`.

## 15. Adopted decisions

| AD    | Decision                                                                             | An audit violates it if …                                                | Owner ticket  |
| ----- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ------------- |
| AD-1  | every finding names one §4 clause, whose text is `16` §12's verbatim                 | a finding names no clause, or a clause text differs from the base        | E49-S04 #1384 |
| AD-2  | the ledger severity is P0..P3 by §7                                                  | a row carries Blocking/Major/Minor/Info, or an AA failure below P2       | E49-S04 #1384 |
| AD-3  | two ledgers: findings in the exporter's header, screens in §11's header              | the finding ledger's header differs from the exporter's                  | E49-T02 #1341 |
| AD-4  | the order is the first tier, then Must-story weight, ties by id, tool-computed       | a screen is audited out of the tool's order without a written reason     | E49-S04 #1384 |
| AD-5  | captures are demo env and fixture symbols only                                       | a capture shows a live account, a key fragment or a real balance         | E49-D05 #1394 |
| AD-6  | each audited screen has six cells or a written N/A per missing cell                  | an audited row has a cell with neither a capture nor a reason            | E49-S04 #1384 |
| AD-7  | chart surfaces 030..054 are sampled at three labelled SYNTHETIC densities            | a chart finding names no density, or a sample is unlabelled              | E49-S04 #1384 |
| AD-8  | a finding carries §10's six fields                                                   | a filed finding lacks any one of them                                    | E49-S04 #1384 |
| AD-9  | an accepted exception names owner, reason and an existing or `post-ga` follow-up key | an `accepted-exception` row fails `E_EXCEPTION`                          | E49-T03 #1342 |
| AD-10 | E47's verdict is recorded from its register, never re-derived                        | `e47_verdict` differs from the register, or an a11y verdict is re-judged | E47-D02 #1301 |
| AD-11 | effort is measured agent time beside the human seeds, never converted                | a calibrated figure is stated without its measurement and label          | E49-S04 #1384 |

## 16. Prior art (public knowledge only)

- **WCAG-EM** (W3C's evaluation methodology) samples a site by a structured sample of key pages and states
  plus a random sample; §6's first tier plus weight is the structured part, and §9's three densities sample
  the data-dependent states. No random sample is taken: the sweep covers every row.
- **Nielsen's severity ratings** (0–4: frequency, impact, persistence) informed keeping one scale; §7 uses
  `03`'s P0..P3 because the exporter and the triage SLAs read it.
- **Design-system audit practice** (component inventories against a published library) is DQ-CO-1..3's
  shape; near-duplicates are consolidation notes, not new components.

No third-party screenshot or product capture is used.

## 17. Open questions

| OQ   | Question                                                                                  | Owner         |
| ---- | ----------------------------------------------------------------------------------------- | ------------- |
| OQ-1 | is the severity map agreed with QA as written (DoD 5)?                                    | the owner     |
| OQ-2 | which transport carries the export to the pushgateway without publishing it (C-12.9)?     | the owner     |
| OQ-3 | does E47-X01's threat model add an evidence rule for a11y mirrors or live regions (DR-1)? | E47-X01 #1326 |
| OQ-4 | which CI job runs the self-check once a `docs` lane exists (V-3)?                         | E49-T01 #1340 |

## 18. Owner session protocol and walkthrough

**Session (about 30 minutes, the owner alone or with QA).** Read §4, §7 and §11 against one pilot screen's
record in PR 2; open that screen's six cells; judge each of its findings actionable or not; record the
rate and any step to revise. Nothing is claimed for the session until the owner records it.

**Walkthrough checklist (≤ 10 items; posted on #1330 at READY).**

1. §7's severity map: agree it as QA, or amend it.
2. §11's two-ledger split instead of changing the exporter.
3. Provision the export's secret and a tailnet transport before PR 2 merges; the pushgateway stays unpublished.
4. 149 rows with the ten reserved ids rejected (§11).
5. The first tier by name (§6.1) and the weight rule.
6. The evidence cells and the owner-run reference-machine leg (§8).
7. The pilot ten (§6.2) and the actionable-rate method (§13).
8. The exception key: an existing backlog key or a `post-ga` issue (§12).
9. The CI wiring deviation (V-3) and the comment on E49-T01.
10. Comment `approved` on #1330, or name what to change.

## 19. Delta rows and deviations

| Row  | Kind      | Text                                                                                                              |
| ---- | --------- | ----------------------------------------------------------------------------------------------------------------- |
| DR-1 | delta     | E47-X01 (#1326) is open; its outcome is cited here when it lands; PR 2 waits for it                               |
| DR-2 | delta     | E47-D01 (#1300) is cited "if it merges as is": its findings map 1:1 onto E47-D02's severities, so §7 holds        |
| V-1  | deviation | the PR title is a conventional commit (`docs(design-system): …`); the ticket's "E49-D01: …" form is not (C-4.10)  |
| V-2  | deviation | the brief's `apps/web` paths and pnpm commands do not apply: no `apps/web` change                                 |
| V-3  | deviation | no `docs` CI job exists; the self-check runs in the governance unit tests and its local `--check` is the evidence |
| V-4  | deviation | the protocol uses Penpot for the ticket's Figma (agent-delivery adaptation)                                       |

## 20. The self-check of this pack

`python3 -I -B scripts/design_qa_ledger_check.py --check` runs the gates below over this file, the tool, the
fixtures and the changed paths; `--self-test` plants each mutation in memory and passes only when each trips
its own gate and no other; `--fill` writes §6's tables and §20.3; `--order` prints the full order.

### 20.1 Fixtures

| Fixture                        | Expected codes |
| ------------------------------ | -------------- |
| `complete.csv`                 | none           |
| `missing-row.csv`              | `E_MISSING`    |
| `bad-verdict.csv`              | `E_VERDICT`    |
| `exception-without-owner.csv`  | `E_EXCEPTION`  |
| `findings-without-bug-key.csv` | `E_BUGKEY`     |

### 20.2 Gates

G-CITE, G-KEYCITE, G-CLAUSES, G-SEVERITY, G-ORDER, G-RESERVED, G-FIXTURES, G-LEDGER, G-AC, G-BQ,
G-DECISIONS, G-OQ, G-WALK, G-NOCLOSE, G-PUBLIC, G-HYGIENE, G-HELPER, G-UNTOUCHED and G-MUTLIST.

### 20.3 Mutations

| M    | Gate        | Mutation                             |
| ---- | ----------- | ------------------------------------ |
| M-01 | G-CITE      | a cite past the end of ledger.py     |
| M-02 | G-KEYCITE   | a pinned line reworded               |
| M-03 | G-CLAUSES   | a clause reworded                    |
| M-04 | G-CLAUSES   | a safety floor lowered               |
| M-05 | G-SEVERITY  | Blocking mapped to P2                |
| M-06 | G-ORDER     | SCR-051 put in the first tier        |
| M-07 | G-ORDER     | a pilot rank drifts                  |
| M-08 | G-RESERVED  | a reserved id dropped                |
| M-09 | G-FIXTURES  | the complete fixture loses a row     |
| M-10 | G-FIXTURES  | the fixture table drifts             |
| M-11 | G-LEDGER    | no ledgers outside slice PR 1        |
| M-12 | G-AC        | an AC state outside the vocabulary   |
| M-13 | G-BQ        | the BQ heading names another comment |
| M-14 | G-BQ        | a default without its built line     |
| M-15 | G-DECISIONS | an owner ticket with the wrong issue |
| M-16 | G-OQ        | an open question owned by nobody     |
| M-17 | G-WALK      | an eleventh walkthrough item         |
| M-18 | G-NOCLOSE   | a closing keyword                    |
| M-19 | G-PUBLIC    | a URL                                |
| M-20 | G-PUBLIC    | a stray HTML comment                 |
| M-21 | G-HYGIENE   | trailing whitespace                  |
| M-22 | G-HELPER    | the helper edited                    |
| M-23 | G-UNTOUCHED | an owner document edited             |
| M-24 | G-UNTOUCHED | the cross-link grows                 |
| M-25 | G-MUTLIST   | the list drifts                      |
