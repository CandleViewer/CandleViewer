# E49-D01 — Design-QA audit protocol and the per-screen ledger

**Ticket:** E49-D01 (#1330) · Task · Sprint 23 · labels `type/chore`, `area/design-system`, `design`,
`design-qa`, `a11y`, `priority/p1` · parent E49 · **Status: Draft — owner approval pending; BQ-0 … BQ-9 are
RULED (§2).** Branch `design/e49-design-qa-protocol`. **Slice: PR 1 of 2** —
this protocol, its self-check `scripts/design_qa_ledger_check.py`, the fixture ledgers under
`tests/fixtures/design_qa/` and one cross-link line in `16` §12. PR 2 (the closing slice) commits the two
ledgers and the pilot results after E47-X01 (#1326) lands. Both PRs carry `Refs #1330` and `Partial:`.

**Base.** Every cite is to `main` at `aa0a02b8c`, the base of the ruling fold, where every cited line was
re-read unchanged (written at `a53a5b438`; the BQ list was posted at `2132de8db`). The shared helper is
imported at its `main` blob `15793f79cf92` (G-HELPER). Blockers: E47-K01, E47-T01, E47-T02 and E47-T03 are
merged; E47-X01 (#1326) is open and non-gating for authoring (orchestrator ruling, 2026-11-04): DR-1 holds its
place until it lands. E47-D01 (#1300) is authored in parallel; it is cited "if it merges as is" (DR-2).

**Honest scope.** Agent-authored. Nothing in this slice audits a screen, and no participant, reviewer or
timing is claimed. Every number is PROPOSED unless RULED; every pilot finding will be labelled
`(agent-run)`; the actionable rate and the effort figures do not exist until PR 2. Findings are routed,
never edited into a spec, a catalogue or a build (ticket Out of scope "Fixing anything").

## 1. Acceptance and Definition-of-Done trace

| Row   | Asks                                                                | State | Where                                                                       |
| ----- | ------------------------------------------------------------------- | ----- | --------------------------------------------------------------------------- |
| AC 1  | one ledger row per catalogue SCR id; a missing id fails             | PR 2  | the rule is done (§11 `E_MISSING`, fixture `missing-row.csv`); ledger: PR 2 |
| AC 2  | a finding is actionable without a conversation                      | done  | §10's record: the clause, token or state, expected, observed, cell, pair    |
| AC 3  | ≥ 80 % of pilot findings actionable; ambiguous steps revised        | PR 2  | §13; the pilot runs after E47-X01 lands                                     |
| AC 4  | an accepted exception names owner, reason and follow-up key         | done  | §12; `E_EXCEPTION` (fixture `exception-without-owner.csv`)                  |
| AC 5  | 3 themes × 2 densities per audited screen, or a written N/A         | done  | §8's cell matrix and its N/A rule                                           |
| DoD 1 | protocol merged; reviewed by the design-system lead and an engineer | owner | the owner's `approved` comment (agent-delivery adaptation)                  |
| DoD 2 | ledger committed; self-check green in CI                            | PR 2  | the ledger in PR 2; CI wiring is Deviation V-3                              |
| DoD 3 | 10-screen pilot run, findings filed, actionable rate recorded       | PR 2  | §13                                                                         |
| DoD 4 | calibrated effort figures size E49-S04                              | PR 2  | §13; a comment on #1384                                                     |
| DoD 5 | severity mapping agreed with QA and recorded                        | owner | §7 (RULED as amended); walkthrough item 1                                   |
| DoD 6 | `16` §12 cross-links the protocol                                   | done  | one line after the checklist (BQ-1)                                         |
| DoD 7 | design sign-off recorded on the ticket                              | owner | §18                                                                         |
| DoD 8 | pilot findings walked through at Sprint Review                      | PR 2  | §18's session protocol                                                      |
| DoD 9 | merged via merge queue with required approvals                      | open  | the orchestrator merges after two approving reviews (C-10.1)                |

## 2. The questions BQ-0 … BQ-9 — RULED (comment 6637510034)

The list is comment 6634720626 on #1330; its ruling of record, comment 6637510034, replaces BQ-4's default.

- **BQ-0 — standing rules.** RULED: AGREE +rider. Built as: text first, `Refs #1330` + `Partial:` while
  E47-X01 is open; the E09-D09 T2 standing gate (`.claude/rules/32-design-specs.md`) applies to every gated
  control the protocol names; findings routed, never fixed; demo env and fixture symbols only (C-2.11); ≤
  1,500 counted lines per PR (C-4.8); the shared helper imported, never copied; E47-D04 (focus) and E47-D09
  (keys) outrank this protocol (a disagreement is an F-row); the ≤ 10-item checklist (§18) is posted at READY.
  Rider: the helper is pinned by its git blob (Base); the walkthrough, the export's transport, the agreement
  with QA and the delegated sign-off stay owner items (§18).
- **BQ-1 — one procedure, not two.** RULED: AGREE +rider. Built as: E09-D11 §16 (PS-1..PS-10) is the spine
  (§5); this protocol adds the screen layer; ONE cross-link line in `16` §12 supersedes E09-D11's A-1; the
  five groups of `16` §12 are copied, not four (§4, V-5); PR 1 = protocol + self-check + fixtures, PR 2 =
  ledgers + pilot. Rider: §11.1 maps PS-6's classes, the verdicts and the finding statuses, one row per
  E49-S04 resolution, `wontfix` refused; DQ-BS-2 applies through `14` §0.5 rule 5 and G-T2 (§8.2).
- **BQ-2 — two ledgers, no exporter change.** RULED: AGREE +rider. Built as: `e49-design-qa-ledger.csv` stays
  the finding ledger in the exporter's five columns; `e49-design-qa-screens.csv` is the per-screen ledger; the
  self-check cross-checks them (§11). Both land in PR 2, whose body states that its merge starts the failing
  push run until the owner provisions the secret and a transport (walkthrough item 3). Rider: §11 names the
  file each consumer reads (C-1, C-2) and makes `finding_id` a resolvable reference.
- **BQ-3 — the row set and E47's verdicts.** RULED: AGREE +rider. Built as: 149 rows (the `### SCR-`
  headings); the ten reserved ids are named (§11) and rejected; two added columns `e47_verdict` and `e47_ref`
  are read from the E47-D02 register, never retyped; the owning epic is derived from each screen's stories,
  ties listed. Rider: the register is read at its pinned blob; the epic comes from `14`'s `Stories:` lines
  (§11); V-6.
- **BQ-4 — one severity scale.** RULED: AMEND. Built as: the amended map (§7): P0..P3, the four anchors and
  PS-7 stand; an E47 row takes the register's own priority (T01 rows), and a review row takes P0 for a task
  not completable by keyboard and screen reader (`05` :282), else the ruled SC rule (e47-t01-sweep.md :512);
  P0 for a non-a11y row stays `03`'s class; "agreed with QA" is walkthrough item 1.
- **BQ-5 — the audit order.** RULED: AGREE +rider. Built as: the first tier by NAME = SCR-030, SCR-050,
  SCR-060, SCR-063, SCR-074; then by Must-story weight from `18` §2, ties by id, computed by the tool (§6);
  chart sampling keeps the ticket's 030..054 range at three SYNTHETIC densities (§9). Rider: the re-check row
  goes to E18's QA ticket (§9); the id corrections are V-7.
- **BQ-6 — the evidence standard.** RULED: AGREE +rider. Built as: Penpot boards (page name + id only) vs
  Storybook or fixture builds; demo env and fixture symbols only; a written N/A per missing cell; the
  reference-machine, `balanced`-profile and diagnostics checks are an owner-run leg (§8); text-only legs draw
  no boards. Rider: boards by page name and id only (R7); pilot captures are embedded in the PR body (§8).
- **BQ-7 — the pilot.** RULED: AGREE +rider. Built as: the top ten of §6's order that are built at the base
  (§6.2); "actionable" judged by the two independent review lenses against §10's six fields, rate
  `(agent-run)`; filing per PS-9; effort as measured agent wall time beside the 15 / 45-minute seeds, never
  converted. Rider: never an unbuilt row (§6.2); a security-shaped row goes privately to the orchestrator
  (DQ-6).
- **BQ-8 — exceptions and near-duplicates.** RULED: AGREE. Built as: the follow-up key is an existing backlog
  key or a `post-ga` issue number, checked by form only (no network call); this PR files none; near-duplicates
  go to `15` as A-rows to the catalogue owner, never a new id (§12).
- **BQ-9 — the self-check.** RULED: AGREE +rider. Built as: `scripts/design_qa_ledger_check.py` with fixtures
  under `tests/fixtures/design_qa/`; it imports the shared helper by path; `--check` / `--self-test` in the
  E09-D12 shape; pytest under `scripts/tests/`; CI wiring is Deviation V-3 (§20). Rider: the SCR ids come from
  `catalogue.py`'s `parse_screens`, loaded by path; V-3 names the `governance` job as the home.

## 3. Method

1. **Spine.** E09-D11 §16 (E09-D11 :515–526, RULED BQ-25 there) is the merged design-QA procedure; its
   PS-1..PS-10 apply unchanged (§5) and this protocol adds the screen layer (§4 to §12).
2. **Clauses.** The checklist of `16` §12 (`16` :686–724) is copied item by item into §4; the self-check
   compares each row with the base, so a reworded clause fails.
3. **Inputs read, not retyped.** The screen list from `14` by `catalogue.py`'s `parse_screens` (149 headings,
   `14` :13–35 for the bands), the story weights from `18` §2 (`18` :44), the E47 verdicts from
   `docs/plan/a11y/47-audit-register.json` at its pinned blob (catalogue: 47-audit-catalogue.md :5), the
   severity taxonomy from `03` §11.3 (`03` :320–327) and the exporter's header from
   `tools/ga_defects/ledger.py` (ledger.py :17).

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
  Where the register has no verdict for the screen (`not auditable at sha`), the row records that and
  nothing is re-derived. An AA failure the walk observes anyway (focus not visible or obscured, a
  keyboard trap, reflow at 400 %, forced colours, a drag with no single-pointer alternative) is filed
  at P2 minimum under the nearest §4 clause, labelled `not E47-verified`, and routed to the E47 owner;
  it never replaces E47's verdict (ticket Out of scope "The WCAG audit itself").
- **DQ-5 Write rows (PS-5, PS-6).** One finding, one record (§10), one severity (§7); a known record cited
  by id, not restated.
- **DQ-6 Route (PS-9).** P0 and P1 rows: an issue by id, class and clause; a security-shaped row: to the
  orchestrator privately, in the ledger by id and class only; the rest: the finding ledger and a comment
  on the open owner ticket. Never a fix in the QA PR (PS-10).
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
audited sha; PR 2 re-computes the ten at its own base. Of the first tier only SCR-030 is built: the
pilot says so and takes the next built screens, never an unbuilt row.

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

## 7. The severity map (RULED as amended; QA agreement pending)

The ledger records P0..P3 only (`03` :320–327). The ticket's four anchors stand verbatim in the rule column.
An E47-sourced row takes the register's own priority where it has one: a T01 row its `priority`
(`docs/plan/a11y/findings.json`). A D02 review row has no level or priority in the register: it takes P0
when it is a task that cannot be completed by keyboard and screen reader (`05` :282), and otherwise the
ruled rule read from its SC (e47-t01-sweep.md :512). P0 for a non-a11y row stays `03` §11.3's own class.

| Source label                                                                                     | Ledger         | Rule                                                                                                 |
| ------------------------------------------------------------------------------------------------ | -------------- | ---------------------------------------------------------------------------------------------------- |
| a secret shown, or a safety-clause breach that can send an order in the wrong env or unconfirmed | P0             | `03`'s P0 class only (a non-a11y row); an issue at once (PS-9)                                       |
| PS-7 Blocking                                                                                    | P1             | a frozen string, a focus-map regression, a task not completable by keyboard (a keyboard trap is one) |
| token drift that changes a trading signal's meaning                                              | P1             | ticket anchor                                                                                        |
| E47 T01 row                                                                                      | its `priority` | the T01 register's own, recorded, never re-derived                                                   |
| E47 review row: a task not completable by keyboard and screen reader                             | P0             | `05` :282                                                                                            |
| E47 review row: Level A                                                                          | P0 or P1       | P0 if it blocks a `05` §8.2 task or any operation on the screen, else P1                             |
| E47 review row: AA                                                                               | P2 or P1       | P1 on a money-moving or authentication path                                                          |
| PS-7 Major                                                                                       | P2             | —                                                                                                    |
| missing designed empty/error state                                                               | P2             | ticket anchor                                                                                        |
| a11y AA violation                                                                                | P2             | ticket anchor: P2 minimum, whatever its source label                                                 |
| PS-7 Minor                                                                                       | P3             | raised to P2 when the clause is an Accessibility clause                                              |
| wrong-but-readable spacing                                                                       | P3             | ticket anchor                                                                                        |
| PS-7 Info, E47 info                                                                              | notes          | never a finding row                                                                                  |

## 8. The evidence standard

**Cells.** Each audited screen is compared in six cells: dark, light and high-contrast × compact and
comfortable (`16` :693). The reference is the screen's Penpot boards (page name + id, never a host or file
reference, R7); the build is its Storybook stories or a fixture build. A missing cell carries its written N/A
reason in the record (AC 5's "Or" arm), for example "no high-contrast board drawn: the text is binding".

**Hard rule (C-2.11, ticket Security notes).** Captures use the demo environment and fixture symbols only:
never a live account, never a real API key fragment, never a real balance. A capture that breaks the rule is
deleted and the run continues (PS-10); the row records only that a capture was withdrawn.

**Owner-run leg.** The reference machine, the `balanced` performance profile of SCR-118 (`14` :2513) and
SCR-046's diagnostics confirming the engine is not in `degraded-2d` (`14` :1122) need a running desktop
build; the agent run names this leg and its hardware class and never claims it.

**Motion and forced colours.** A screen with an animated property adds a reduced-motion capture beside
its default one (DQ-AX-4); a screen whose state is carried by colour adds a forced-colours capture. Each
takes the same written-N/A rule as a missing cell.

**Files.** A PR that embeds pilot captures embeds them in its body (`docs/design/README.md` :44–57); the
PNGs and any pilot run record beyond §13 go under `docs/qa/`, in no new directory, and count under the
C-4.8 note; text-only legs draw no boards.

### 8.1 Evidence per clause

A capture pair proves a visual clause only. Each clause passes on the evidence named here; a finding cites
the same artefact as its §10 field 6.

| Clause  | Passes when                                                                               | Evidence                                                    |
| ------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| DQ-TV-1 | the build and the board use token names only                                              | the six-cell pair and the story's token list                |
| DQ-TV-2 | the six cells match the boards with no theme- or density-only breakage                    | the six-cell pair                                           |
| DQ-TV-3 | the contrast matrix (`05` :300) reports no `A11Y-C001` for a pair the screen uses         | the matrix report named by its run (`05` :164 for HC)       |
| DQ-TV-4 | the same report has no `A11Y-C003` for a colour-carrying state of the screen              | the matrix report                                           |
| DQ-BS-1 | every `14` States line has a board and a story                                            | the board ids and the story names                           |
| DQ-BS-2 | §8.2's T2 checks hold for every gated control                                             | an accessibility-tree dump and a keyboard transcript        |
| DQ-BS-3 | loading, empty and error each have a board and a story of their own                       | the pair per state                                          |
| DQ-AX-1 | each keyboard-table row is reproduced: key, focus target, announced text                  | the keyboard transcript and the named keyboard test         |
| DQ-AX-2 | the tree's role and name per control match the spec's name/role table                     | the accessibility-tree dump of the story                    |
| DQ-AX-3 | the `05` §6 layer the spec names exists and the table view is reached by keyboard         | the tree dump and the transcript, at all three §9 densities |
| DQ-AX-4 | the reduced-motion capture shows no animated property the pair names                      | the default and reduced-motion captures                     |
| DQ-AX-5 | every target is ≥ 24 px compact and 40–44 px comfortable, or a logged essential exception | box sizes in CSS px per density (`05` :104)                 |
| DQ-AX-6 | the owner's approval of the screen ticket is recorded (agent delivery; Done tickets only) | the approval comment on the screen ticket                   |
| DQ-TS-1 | the confirm gate's variant is stated and completed by keyboard alone                      | the keyboard transcript and the named keyboard test         |
| DQ-TS-2 | each estimated value carries its chip and the chip opens its InfoPanel                    | the pair and the transcript                                 |
| DQ-TS-3 | the Demo or Live context is visible in every cell where the screen can trade              | the six-cell pair                                           |
| DQ-CO-1 | every component is an existing `CMP-` id                                                  | the story's component list against `15`                     |
| DQ-CO-2 | the stories cover the catalogue entry's Variants × States                                 | the story list against the `15` entry                       |
| DQ-CO-3 | the board composes library components with no detached override                           | the board's layer list                                      |

### 8.2 The T2 checks for DQ-BS-2

The E09-D09 T2 standing gate (`.claude/rules/32-design-specs.md`) is read, not restated: each line below
names its check, and a miss is a DQ-BS-2 finding at P2. DQ-BS-2 copies `16` :700 and applies through
`14` §0.5 rule 5 (`14` :85): a hidden admin affordance (step 1) or a server refusal (step 2) is never
recorded as a missing disabled-with-reason.

| Check   | What the auditor confirms on the build                                       | Evidence                   |
| ------- | ---------------------------------------------------------------------------- | -------------------------- |
| G-T2.1a | the control keeps its native role and full label                             | tree dump                  |
| G-T2.1b | `aria-disabled="true"`, not the `disabled` attribute; still in the Tab order | tree dump and transcript   |
| G-T2.1c | the reason node is in the DOM at mount and linked by `aria-describedby`      | tree dump                  |
| G-T2.1d | CMP-079 wraps the control                                                    | the story's component list |
| G-T2.2  | the label and reason tokens are the gate's, never a disabled-opacity token   | the story's token list     |
| G-T2.3  | `Enter`, `Space` or a hotkey changes nothing and re-shows the reason once    | transcript                 |
| G-T2.4  | the reason is one of the gate's registered keys                              | tree dump                  |

## 9. The sampling rule for chart surfaces

SCR-030 … SCR-054 (the ticket's range; `14` §3 is 030..049 and 050..059 is order flow, F-3) are audited at
three data densities — sparse, typical and extreme footprint density — each a labelled SYNTHETIC sample from
the seeded chart-engine bench generators (`packages/chart-engine/bench/fixtures/`). No recorded symbol-day
exists; a re-check row for E18's QA ticket (as #497 ruled) names the screens to repeat once one does.
DQ-AX-3's mirror and table view are checked at every density, the extreme one included.

## 10. The finding record (AC 2)

Every finding, in the ledger and in any issue, carries these fields; a record missing one is not filed:

1. **Clause** — one §4 id, with its group.
2. **Token or state** — Tier-2/Tier-3 names only, never hex: "uses `color.surface.raised` where the spec
   says `color.surface.sunken`"; or the state name from the screen's `14` States line.
3. **Expected** — the value from the Penpot board or the spec, with its cite.
4. **Observed** — the value in the build, with the story or fixture build named.
5. **Cell** — the theme and density it reproduces in (or "all six").
6. **Pair** — the reference and build capture file names, or for a non-visual clause the §8.1 artefact
   (tree dump, keyboard transcript, measurement or matrix report).

Plus the PS-5 cells: class (implementation defect, accepted divergence, specification gap), severity (§7),
owner ticket, and the reproduction note.

## 11. The two ledgers and the self-check

**Finding ledger** `docs/plan/backlog/artifacts/e49-design-qa-ledger.csv` — the exporter's header
`finding_id,severity,status,component,opened` (ledger.py :17, :3–4): `finding_id` is a resolvable
reference — an issue `#N` for a P0, P1 or security row, an E47 register id (`A11Y-…`) for an E47 row, else
a `DQA-nnnn` id minted in this file — so the ledger indexes issues and never replaces them; `severity`
P0..P3, `status` open|in-progress|fixed|accepted (no `wontfix`, §11.1), `component` the screen id,
`opened` an ISO date. This schema is owned here (ledger.py :1); the exporter is unchanged, and the path is
the one run.py :21 reads and the export watches (design-qa-ledger-export.yml :10–11).

**Screen ledger** `docs/plan/backlog/artifacts/e49-design-qa-screens.csv`, a path the export does not
watch — one row per `### SCR-` heading, 149, the number `14` and `18` both carry:
`screen_id,screen_name,owning_epic,auditor,audit_date,verdict,p0,p1,p2,p3,bug_keys,notes,e47_verdict,e47_ref`.
The verdict is `pass`, `findings`, `accepted-exception` or `not-applicable`, or empty while the screen is
unaudited. `owning_epic` comes from the screen's `Stories:` lines in `14`, ties listed (`Enn;Enn`), never
guessed; `e47_verdict` and `e47_ref` are read from the register's `screens[]` at its pinned blob, as
`catalogue.py` pins its inputs. Reserved ids (never rows): SCR-007, SCR-008, SCR-009, SCR-105, SCR-106,
SCR-107, SCR-108, SCR-109, SCR-138, SCR-139.

**Who reads which file.** The exporter reads the finding ledger; per-screen verdicts (E49-D05, E49-S04)
read the screen ledger, not the exporter's path both tickets name (C-1, C-2). PR 2's body states that
merging the finding file starts one failing push run (run.py :24, exit 2) until walkthrough item 3 is done.

**Self-check rules** (`scripts/design_qa_ledger_check.py --ledger SCREENS FINDINGS`):

| Code          | Fails when                                                                                                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `E_HEADER`    | the screen ledger's header is not the one above                                                                                                                                   |
| `E_MISSING`   | a catalogue id has no row (AC 1)                                                                                                                                                  |
| `E_EXTRA`     | a row's id is not a catalogue heading; `E_RESERVED` when it is a reserved id                                                                                                      |
| `E_DUP`       | an id appears twice                                                                                                                                                               |
| `E_NAME`      | a row's name differs from its catalogue heading                                                                                                                                   |
| `E_VERDICT`   | the verdict is outside the four words and empty                                                                                                                                   |
| `E_AUDIT`     | an audited row lacks auditor or ISO date, or an unaudited row carries either, a count or a key                                                                                    |
| `E_COUNTS`    | a count is not a whole number; `pass` with a finding; `findings` with none                                                                                                        |
| `E_BUGKEY`    | a `findings` row has no bug key, or a key is not `#N`, a backlog key or a finding ledger id                                                                                       |
| `E_EXCEPTION` | an `accepted-exception` row lacks `owner:` or `reason:` in its notes, or a follow-up key (AC 4); or its notes name DQ-AX-n, DQ-BS-2 or DQ-TS-1 without `control:`                 |
| `E_NA`        | a `not-applicable` row lacks `reason:` in its notes                                                                                                                               |
| `E_EPIC`      | the owning epic is not `Enn`, or `Enn;Enn` for a tie                                                                                                                              |
| `E_E47`       | `e47_verdict` differs from the register's verdict, or `e47_ref` from its audited sha (9 hex)                                                                                      |
| `E_FINDINGS`  | the finding ledger fails the exporter's parser, has a malformed row or a `wontfix` status, or a `finding_id` that is not a resolvable reference (a P0 or P1 row minted as `DQA-`) |
| `E_CROSS`     | a row's four counts differ from its screen's finding rows, or a `DQA-` key names no finding row                                                                                   |

### 11.1 Classes, verdicts, statuses and resolutions

One row per E49-S04 resolution; `wontfix` is not a design-QA resolution before GA (the epic's bar is
pass-or-accepted), and the self-check refuses it.

| PS-6 class            | Screen verdict       | Finding status | E49-S04 resolution   |
| --------------------- | -------------------- | -------------- | -------------------- |
| implementation defect | `findings`           | `fixed`        | `fixed`              |
| specification gap     | `findings`           | `fixed`        | `spec-corrected`     |
| accepted divergence   | `accepted-exception` | `accepted`     | `accepted-exception` |

## 12. Accepted exceptions and near-duplicates

An `accepted-exception` row carries `owner: <ticket key or the owner>; reason: <text>` in its notes and its
follow-up key in `bug_keys`: an existing backlog key or a `#N` issue labelled `post-ga`, checked by form only
(plan-first: no new follow-up tickets; an exception that needs one is a question to the orchestrator). The
E49-T03 inventory (#1342) holds the owner-dated risks; an exception that is a risk is cited there, not
restated. An exception on an Accessibility clause, DQ-BS-2 or DQ-TS-1 names that clause in its notes and adds
`control: <the compensating control>` (`05` :360, the essential exception at `05` :104), citing the E47
limitation or the E49-T03 row it rests on; the self-check fails it without `control:`. A near-duplicate
component found in the pilot is an A-row to `15` for the catalogue owner; no new `CMP-` or `SCR-` id is
created (ticket Out of scope).

## 13. The pilot and the effort model (PR 2)

The pilot audits §6.2's ten screens by §5. Each finding is classified actionable or needs-clarification by
the two independent review lenses against §10's six fields; the rate is stated `(agent-run)` and the owner's
confirmation is pending until recorded. A step that produced an ambiguous finding is revised in PR 2 before
the sweep is commissioned (AC 3). Effort is the measured agent wall time per pilot screen, labelled, beside
the ticket's seeds (about 15 minutes per simple state screen, 45 per dense trading screen), never converted;
the sizing note for E49-S04 is a comment on #1384. The seeds are the ticket's as given; where a pilot
screen gets a screen-reader spot check (`05` §8.2), its time is recorded as a separate leg.

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
| F-8  | most screens are not built, so the evidence standard cannot be met for them yet               | 47-audit-catalogue.md :16, :18                   | E49-S04 #1384 (comment)        |
| F-9  | the ticket body's sprint (S22) is stale; the JSON's is Sprint 23                              | the ticket Context; `docs/plan/backlog/E49.json` | E49 plan JSON (the owner)      |
| F-10 | the export's push target is unprovisioned and the pushgateway binds to the loopback interface | design-qa-ledger-export.yml :36–41               | the owner (walkthrough item 3) |
| F-11 | there is no `docs` CI job to wire the self-check into                                         | pr.yml :297–299 (a path filter)                  | E49-T01 #1340 (comment)        |

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

| Row  | Kind      | Text                                                                                                                                                                                                                                 |
| ---- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| DR-1 | delta     | E47-X01 (#1326) is open; its outcome is cited here when it lands; PR 2 waits for it                                                                                                                                                  |
| DR-2 | delta     | E47-D01 (#1300) is cited "if it merges as is": its findings map 1:1 onto E47-D02's severities, so §7 holds                                                                                                                           |
| V-1  | deviation | the PR title is a conventional commit (`docs(design-system): …`); the ticket's "E49-D01: …" form is not (C-4.10)                                                                                                                     |
| V-2  | deviation | the brief's `apps/web` paths and pnpm commands do not apply: no `apps/web` change                                                                                                                                                    |
| V-3  | deviation | DoD 2's "green in CI": the home is a step in the `governance` job (GOV-008, governance.yml :107–108), named in the comment to E49-T01; a workflow edit is a C-10.2 path, so it is not made here; the local `--check` is the evidence |
| V-4  | deviation | the protocol uses Penpot for the ticket's Figma (agent-delivery adaptation)                                                                                                                                                          |
| V-5  | deviation | the ticket says four checklist groups; `16` §12 has five (`16` :690–718)                                                                                                                                                             |
| V-6  | deviation | the ticket's "SCR-001 … SCR-159" is 149 rows: ten ids are reserved                                                                                                                                                                   |
| V-7  | deviation | the ticket's first-tier ids SCR-051 and SCR-070 are corrected to SCR-063 by name (§6.1)                                                                                                                                              |
| C-1  | contract  | to E49-D05 #1394 (comment): per-screen verdicts are read from the screen ledger, not the finding path                                                                                                                                |
| C-2  | contract  | to E49-S04 #1384 (comment): the same, and its resolutions map by §11.1                                                                                                                                                               |

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

G-CITE, G-KEYCITE, G-CLAUSES, G-EVIDENCE, G-SEVERITY, G-ORDER, G-RESERVED, G-FIXTURES, G-LEDGER, G-AC, G-BQ,
G-RESOLUTIONS, G-DECISIONS, G-OQ, G-WALK, G-NOCLOSE, G-PUBLIC, G-HYGIENE, G-HELPER, G-UNTOUCHED and G-MUTLIST.

### 20.3 Mutations

| M    | Gate          | Mutation                             |
| ---- | ------------- | ------------------------------------ |
| M-01 | G-CITE        | a cite past the end of ledger.py     |
| M-02 | G-KEYCITE     | a pinned line reworded               |
| M-03 | G-CLAUSES     | a clause reworded                    |
| M-04 | G-CLAUSES     | a safety floor lowered               |
| M-05 | G-SEVERITY    | Blocking mapped to P2                |
| M-06 | G-ORDER       | SCR-051 put in the first tier        |
| M-07 | G-ORDER       | a pilot rank drifts                  |
| M-08 | G-RESERVED    | a reserved id dropped                |
| M-09 | G-FIXTURES    | the complete fixture loses a row     |
| M-10 | G-FIXTURES    | the fixture table drifts             |
| M-11 | G-LEDGER      | no ledgers outside slice PR 1        |
| M-12 | G-AC          | an AC state outside the vocabulary   |
| M-13 | G-BQ          | the heading loses its ruling         |
| M-14 | G-BQ          | a default without its built line     |
| M-15 | G-DECISIONS   | an owner ticket with the wrong issue |
| M-16 | G-OQ          | an open question owned by nobody     |
| M-17 | G-WALK        | an eleventh walkthrough item         |
| M-18 | G-NOCLOSE     | a closing keyword                    |
| M-19 | G-PUBLIC      | a URL                                |
| M-20 | G-PUBLIC      | a stray HTML comment                 |
| M-21 | G-HYGIENE     | trailing whitespace                  |
| M-22 | G-HELPER      | the helper edited                    |
| M-23 | G-UNTOUCHED   | an owner document edited             |
| M-24 | G-UNTOUCHED   | the cross-link grows                 |
| M-25 | G-MUTLIST     | the list drifts                      |
| M-26 | G-EVIDENCE    | a clause without its evidence row    |
| M-27 | G-EVIDENCE    | a T2 check dropped                   |
| M-28 | G-BQ          | the AMEND ruled as AGREE             |
| M-29 | G-RESOLUTIONS | wontfix as a resolution              |
