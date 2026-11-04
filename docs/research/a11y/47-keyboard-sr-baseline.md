# E47-D01 — UX research: the keyboard-only and screen-reader trading baseline

- **Ticket:** E47-D01 (issue #1300) · **Status:** Draft, text-first, pre-staged. All eight `blocked_by` tickets (E44-T01..T06, E44-K01, E44-X02) are open, so this PR is `Refs #1300` plus a `Partial:` line and closes nothing; no commit or body carries a closing keyword (BQ-0). The BQ list is posted (comment 6634720172) and **this memo is built exactly on its ORCH-defaults; the ruling is pending**. Every finding is `(heuristic)`; every decision is **PROPOSED**, owner approval pending; the orchestrator's design approval adopts the PROPOSED decisions as interim rulings under the 2026-10-29 delegation, and the owner can reverse any one by one line (agent-delivery adaptations, owner decision 2026-09-25). A change this memo proposes to an owner document is an A row (§12.4), never an edit.
- **Method:** a heuristic evaluation (Nielsen's N1–N10, the trading rules of `05` §3 and §6, and the WCAG 2.2 success criteria), the task script of `05` §8.2 item 3 walked against main's code and the merged E47 specs, two proxy walkthroughs, and a short public-practice scan (§1). **No session was run: no participant, timing, count of focus losses or quote exists, and none is invented.**
- **Scope (ticket):** the task script over SCR-100 / SCR-102, SCR-030, SCR-045, SCR-050, SCR-060, SCR-063, SCR-074, SCR-116, SCR-117, SCR-013, SCR-012, SCR-081, SCR-082 and SCR-121..SCR-123; the announcement-verbosity default (deliverable 4); the top-10 list for E47-D02 (deliverable 2).
- **Out of scope (ticket):** visual design, wireframes and tokens (E47-D02/D03 onward); mobile screen readers; Safari and non-Electron targets; remediation (findings become rows, not fixes).
- **Proxies, not participants:** X1 an NVDA daily driver and X2 a keyboard-only low-vision trader, both standing in for the ticket's two external experts (BQ-8's two proxies). The owner (P1, `10` §2) is the first participant §11 runs, never a proxy here. A proxy is a reading of the documented goals, never an observed person.
- **Ids:** BQ pre-writing question (its ORCH-default is built here) · T task · F finding · W walkthrough step · AD adopted decision · S session-protocol step · C contradiction between binding texts · G gap · A proposed owner-document amendment (not edited) · OQ open question · TOP top-10 row.
- **Pin.** Every `path:line` cite is at `main` `a53a5b4385eb9fbf73ad530900065a0f8626e523`.
- **Shorthand.** `NN` = `docs/plan/NN-*.md`; `E47J` = `docs/plan/backlog/E47.json` (line 61 is this ticket's body, line 86 E47-D02's); `CAT` = `docs/plan/a11y/47-audit-catalogue.md`; `REG` = `docs/plan/a11y/47-audit-register.json` (cited by finding id); `D04`..`D13` = `docs/design/E47/E47-D04.md`..`E47-D13.md`; `KMAP` = `apps/web/src/keymap/keymap.json`; `CHS` = `apps/web/src/keymap/Cheatsheet.tsx`; `HOST` = `apps/web/src/keymap/KeymapHost.tsx`; `MODEL` = `apps/web/src/features/a11y-preferences/model.ts`; `PW` = `apps/web/src/chart/a11y/politeWriter.ts`; `CTP` = `apps/web/src/chart/a11y/ChartTablePanel.tsx`; `SHELL` = `apps/web/src/features/app-shell/ShellLayout.tsx`; `TREE` = `apps/web/src/routes/tree.tsx`; `SRR` = `docs/qa/a11y/sr/README.md`; `README` = `docs/design/README.md`; `CONST` = `CONSTITUTION.md`. Companion check: `docs/design/_tools/e47_d01_research_audit.py` (`--check`, `--self-test`).

## Acceptance-criteria trace (E47-D01, issue #1300)

Status key: **done** = delivered as worded · **done (text)** = delivered as text; nothing in it was run · **heuristic-only** = delivered through the adaptation, pending the owner's run · **open** = needs the owner's sessions or decision and is not claimed · **not applicable** = no product code.

| Ticket AC or deliverable                                                                               | Where          | Status                         | Note                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------ | -------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| AC1 "Study executed against the real build": five sessions on the R4 build, NVDA 2024.x pinned         | §11            | open                           | no session was run; the protocol is written (5-minute ceiling, no coaching, keystroke log, Demo-only rig, the NVDA speech-viewer log)                        |
| AC2 "Findings are actionable and traceable": SCR, CMP where one applies, WCAG 2.2 SC, severity         | §3, §3.2       | done (two rows usability-only) | every F row carries them, `(heuristic)`; F-2 and F-7 are best-practice rows with no SC failed (§3's legend); §3.2 screens the AA SCs; G-ROWS checks each row |
| AC3 "Announcement flooding is quantified, not guessed": announcements per minute and a cadence         | §5, AD-1, AD-2 | heuristic-only                 | per setting, SYNTHETIC, from the merged E47-D07 replay; the subjective rating is open (§11)                                                                  |
| AC4 "Participant cannot complete a task (failure path)": a blocker with its exact keystroke sequence   | §3, §9, §11 S4 | open                           | no blocker is found at the sha (§2); the protocol records the keystroke log; G-KEYS refuses a blocker row without one                                        |
| AC5 "No trading risk introduced by the study": every order task on Bybit demo with the Live gate off   | §11 S2, AD-7   | done (text)                    | a protocol rule; no order was placed                                                                                                                         |
| Deliverable 1: the findings report at `docs/research/a11y/47-keyboard-sr-baseline.md`, severity-ranked | this file, §3  | done                           | one file holding the memo, the top-10 and the protocol (BQ-2)                                                                                                |
| Deliverable 2: a one-page top-10 consumed by E47-D02                                                   | §7             | done                           | pasted on #1300 at READY; linked from E47-D02 (#1301) at merge                                                                                               |
| Deliverable 3: session recordings and transcripts stored per the retention policy                      | §11.1          | not applicable                 | N/A — owner protocol, restricted store; no recording exists                                                                                                  |
| Deliverable 4: a proposed announcement-verbosity default backed by the flooding data                   | §5, AD-1       | heuristic-only                 | PROPOSED; backed by SYNTHETIC counts, not observed flooding                                                                                                  |
| Measures per task: completion, time vs a mouse control, focus-loss count, "where am I?" count, quotes  | §2, §11.3      | open                           | per task, operator counts only, an "operator ratio, not a time" (BQ-7); the rest is on the session sheet                                                     |
| Performance note: a mirror announcement > 200 ms is a finding forwarded to E46                         | §11.3, OQ-2    | open                           | needs a run; routed to E46 when observed                                                                                                                     |
| Observability: severity counts recorded on the E47 epic as the baseline                                | §3.1           | open                           | posted once on the E47 epic at merge (BQ-4)                                                                                                                  |
| DoD: findings report merged, peer-reviewed by the Accessibility role                                   | this PR        | open                           | owner approval pending                                                                                                                                       |
| DoD: top-10 attached to the ticket and linked from E47-D02                                             | §7             | open                           | at READY and at merge                                                                                                                                        |
| DoD: every blocker has a follow-up ticket or is folded into a named E47 design ticket's scope          | §3, §9         | done                           | zero blockers at the sha; every row is routed to one named ticket or engineering-only (BQ-4); no new issue is filed                                          |
| DoD: CDO sign-off recorded on the ticket; Accessibility role co-signs                                  | §12            | open                           | the owner's `approved` comment (agent-delivery adaptations)                                                                                                  |
| DoD: recordings stored and access-restricted; consent forms filed                                      | §11.1          | not applicable                 | N/A — owner protocol, restricted store                                                                                                                       |
| README: the research board on the ticket's Penpot page                                                 | §0             | not applicable                 | text-only under the 2026-10-29 delegation (BQ-9); the README :44 / :54 waiver as ruled for packs                                                             |
| Brief: `apps/web` paths, `pnpm` commands, Storybook, axe, coverage                                     | Deviation 3    | not applicable                 | no UI code in a research ticket                                                                                                                              |

## Deviations

1. **Method.** The five moderated sessions become the heuristic evaluation (§3), the task walk (§2), the proxy walkthroughs (§4), the SYNTHETIC flooding count (§5), the owner session protocol (§11) and the owner walkthrough checklist (§12), per the ticket's adaptation clause (`E47J`:61). AC1 and AC4 stay **open**.
2. **Text-first, pre-staged.** The blockers are open, so this PR is `Refs #1300` with a `Partial:` line and no closing keyword (BQ-0). No board is drawn (BQ-9).
3. **Template noise.** The brief's `apps/web` paths, its `pnpm` commands, its "E47-D01: …" PR title and its closing line are recorded here as deviations: the PR title is the conventional `docs(design-system): …` (C-4.10) and the PR is `Refs #1300`.
4. **Inverted order.** E47-D02 (#1301) and E47-D03..D10 and D13 merged before this memo; D01 becomes the task-level verification of the merged set (BQ-3, C4).
5. **Public scan.** The fetch tool could not reach the vendor and W3C hosts on 2026-11-04; §6 rests on pages already fetched and cited in merged texts, with their dates, and adds no new quote.

## BQ list — defaults built; ruling pending (comment 6634720172)

The pre-writing questions are posted on #1300 (comment 6634720172). This memo is built exactly on their ORCH-defaults; the heading flips to RULED when the ruling lands.

| BQ   | Question                              | ORCH-default built here                                                                                                                                             | Where              |
| ---- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| BQ-0 | Standing rules                        | `Refs #1300` + `Partial:`; branch `design/e47-a11y-baseline-research`; T2 applied where a row touches a control; D04 and D09 outrank the epic specs; Demo-only      | header, Deviations |
| BQ-1 | Done when no session can run          | an AC trace; AC1 and AC4 open into the protocol; AC2 done; AC3 heuristic-only; AC5 a protocol rule; recordings and consent "N/A — owner protocol, restricted store" | AC trace, §11      |
| BQ-2 | Report path and file set              | the ticket's path; one file with memo, top-10 and protocol; nothing under `docs/qa/` or `qa/evidence/`; `05` §8.4's "counts toward none" quoted                     | this file, §1      |
| BQ-3 | D02..D13 merged before D01            | D01 verifies the merged set task by task; a gap is an F row to the owning spec's ticket; D02's absorption AC met through §9                                         | §2, §3, §9         |
| BQ-4 | Finding shape, severity, routing      | blocker / major / minor 1:1 onto D02's names; SCR, CMP, SC, task, `(heuristic)`, keystrokes for a blocker, a D02 id or "new"; one named owner; no new issues        | §3, §9             |
| BQ-5 | The task script against what is built | the ticket's seven tasks plus `05`'s two, in `05`'s order; completable / blocker / not built at the sha; "flatten" traced on `positions.close_all`                  | §2                 |
| BQ-6 | Flooding and the cadence              | per-minute counts from E47-D07's seeded fast script over 2 minutes at 10 Hz, SYNTHETIC; the cadence answer binary; the default PROPOSED                             | §5, AD-1, AD-2     |
| BQ-7 | Timing nobody can take                | operator counts per task, "operator ratio, not a time"; a ratio > 3 a `(heuristic)` candidate; times and the 200 ms check open                                      | §2, §11.3          |
| BQ-8 | Heuristics, proxies, public sources   | Nielsen + `05`'s trading rules + WCAG 2.2; two proxies; a short public scan with URL and fetched date, no third-party screenshot                                    | §1, §4, §6         |
| BQ-9 | Tool, boards, size, downstream        | `e47_d01_research_audit.py` in the E09-D12 shape importing the shared helper, its test first; no boards; memo + tool + test under the ceiling                       | §0, §10, §13       |

## 0. Research boards — none in this PR

Text-only under the 2026-10-29 delegation (BQ-9): `README`:44 and `README`:54 ask every design ticket, research included, for Penpot evidence; the waiver ruled for hand-off packs is applied here, and the findings are tables per the ticket's accessibility notes (structured markdown, no screenshot-only finding). If the ruling requires boards, they land in a later push of this PR and §0 names them.

## 1. Method note (agent-delivery adaptation, owner decision 2026-09-25)

The ticket asks for five moderated 60-minute sessions on the R4 Electron build with NVDA 2024.x pinned (`E47J`:61; `05`:263). No R4 build, no Live gate and no participant exist, so the sessions become (1) the task script walked against main's code and the merged specs at the pin (§2); (2) a heuristic evaluation (§3); (3) two proxy walkthroughs (§4); (4) a SYNTHETIC flooding count from the merged E47-D07 replay (§5); (5) a public-practice scan (§6); and (6) a protocol the owner can run (§11). `05` §8.4 governs what this memo is: "An agent-run pass is recorded as "(heuristic)" and counts toward none of the §8.1 passes." (`05`:293–294). Nothing is written under `docs/qa/` or `qa/evidence/`.

Heuristics: Nielsen's N1–N10; `05`'s trading rules (keyboard-first as a speed requirement, `05`:15; the escape hatch `Alt+T`, `05`:57; the throttled ambient region, `05`:185; the task-based pass, `05`:274–280; the severity bar, `05`:282); the WCAG 2.2 AA success criteria. The register vocabulary is D02's (`CAT`:9, `CAT`:56).

## 2. The task script at the sha (`05` §8.2 item 3 order; BQ-5)

Verdicts: **completable** (the path exists keyboard + SR, read from main's code and the merged spec; no screen reader was run, so it is not an observed pass, and S4 re-verifies it) · **blocker** (it exists and cannot be finished keyboard + SR) · **not built at the sha** (D02's "not auditable at sha"; E47-T04's `SURFACE PENDING`, `SRR`:28). Operator counts: K keystrokes on the shortest keyboard + NVDA path, P pointer actions for the same goal; an "operator ratio, not a time" (BQ-7).

| T   | Task (source)                                                                                                 | Surface           | Verdict              | Operator count (K / P) | Evidence                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------- | ----------------- | -------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| T1  | switch symbol via the watchlist search (`05`:275)                                                             | SCR-100, SCR-102  | not built at the sha | not counted            | SCR-100 (`14`:2298) is not built; the global symbol search (`14`:2344) is mounted (`SHELL`:60) but no chart panel is        |
| T2  | place and cancel a limit order on the ticket (`05`:276; ticket task 4)                                        | SCR-060, SCR-063  | not built at the sha | not counted            | SCR-060 (`14`:1445) and SCR-063 (`14`:1534) are not built; the cancel key is `05`:63                                        |
| T3  | read the last 5 bars via the mirror and via `Alt+T`, compare parity (`05`:277; the five bars are `E47J`:61's) | SCR-030, SCR-045  | not built at the sha | not counted            | `Alt+T` is registered (`KMAP`:337–340), the table panel is built (`CTP`:63) and mounted by no route; SCR-030 is not mounted |
| T4  | inspect one footprint bar's price levels (ticket task 3)                                                      | SCR-030, SCR-045  | not built at the sha | not counted            | as T3                                                                                                                       |
| T5  | read the top 10 DOM levels (ticket task 5)                                                                    | SCR-050           | not built at the sha | not counted            | SCR-050 (`14`:1195) is not built; its trade keys are unresolved (F-8)                                                       |
| T6  | Demo→Live: the confirm dialog operable, the badge change announced (`05`:279)                                 | SCR-074, SCR-075  | not built at the sha | not counted            | SCR-074 (`14`:1770) is not built and the Live gate is E44's (blocked_by); walked on the merged specs only (W2)              |
| T7  | the admin form: names, roles, values of every control (`05`:280)                                              | SCR-121..SCR-123  | not built at the sha | not counted            | SCR-121 and SCR-122 are not built, so the task as worded cannot run; SCR-123 is reachable and its open rows are F-4 and F-5 |
| T8  | open and change one accessibility preference (ticket task 6; US-SET-007)                                      | SCR-117           | completable          | not counted            | the screen is routed (`TREE`:58); its open rows are F-3 and F-4                                                             |
| T9  | find the binding for "flatten" via the cheatsheet (ticket task 7)                                             | SCR-013 (CMP-094) | completable          | ≈ 13 / 1–3 (ratio > 3) | traced on `positions.close_all` (`KMAP`:615–618) as `D09`:233 does; the sheet is mounted (`HOST`:165); F-1, F-2             |

T9's count: `Ctrl+/` opens the sheet with focus on Close (`CHS`:30–31); NVDA's browse-mode toggle, then the table quick key seven times (the sheet renders one captioned table per context in first-use order, Positions seventh, `CHS`:101–111), three row moves to "Close all in view (confirm)" and one cell move to its binding: about 13 keystrokes against one shortcut or click and a scroll for a sighted pointer user. Two of the nine tasks are completable and none is a blocker at the sha; seven need surfaces that are not built. `05`'s rule-engine flatten (`05`:278) is a tenth task the BQ default does not list; it is not built at the sha (`14`:1895, `14`:1942) and waits on the ruling (OQ-6). The ticket's two rule editors (SCR-081, SCR-082) carry no task in BQ-5's nine; both routes render a stub at the sha (`TREE`:83), so their keyboard paths, the non-drag twins of `D09`:175–178 included (2.5.7), are not assessable and route to E47-S03 (G3).

## 3. Heuristic evaluation (every finding `(heuristic)`)

Severity (`05`:282; D02's names 1:1, BQ-4): **blocker** (a task cannot be completed keyboard + SR only) · **major** (awkward but completable, or a spec-level risk to a core trading task) · **minor**. D02's fourth tier, info (`CAT`:56), has no row here. An SC cell `n/a (usability, …)` marks a best-practice finding that fails no WCAG SC (F-2, F-7). An SC the register leaves empty is assigned by this memo and says so in Evidence. "D02 id" is an existing register id (`REG`, cited, not restated) or "new".

| F   | Finding                                                                                                                                                                                                                                                                                                                                                                       | SCR              | CMP     | SC                        | Task | Severity | Keystrokes | D02 id              | Route                        | Evidence                                                                                 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------- | ------------------------- | ---- | -------- | ---------- | ------------------- | ---------------------------- | ---------------------------------------------------------------------------------------- |
| F-1 | `(heuristic)` A trader who knows the task as "flatten" finds no row by that word: the label is "Close all in view (confirm)", and `05`'s documented `Ctrl+Shift+F` is bound to nothing, so the key a reader learned from `05` does nothing at all (N2, N4).                                                                                                                   | SCR-013          | CMP-094 | 2.4.6                     | T9   | major    | —          | new                 | E47-D09 (#1308)              | `05`:64 · `KMAP`:615–618 · `D09`:395 · `D09`:417                                         |
| F-2 | `(heuristic)` The sheet has no search at the sha: 85 rows in nine tables are read one table at a time, an operator ratio above 3 for a task the sighted user finishes at a glance (N7). The merged spec has the search; it is unbuilt.                                                                                                                                        | SCR-013          | CMP-094 | n/a (usability, `05`:15)  | T9   | major    | —          | new                 | E47-S08 (#1322)              | `CHS`:101–111 · `D09`:233                                                                |
| F-3 | `(heuristic)` Two links on the settings pages keep the browser's default blue on the dark surface; a low-vision keyboard user changing a preference cannot see where the link is (text below 1.4.3's 4.5:1 floor; the register holds the ratio).                                                                                                                              | SCR-116, SCR-117 | CMP-086 | 1.4.3                     | T8   | major    | —          | A11Y-F-0018         | E47-D05 (#1304)              | `REG` A11Y-F-0018                                                                        |
| F-4 | `(heuristic)` At 320 CSS px the navigation rail stays expanded and squeezes the main region, so a 400 % zoom user scrolls in two dimensions on the settings and invite forms.                                                                                                                                                                                                 | SCR-117, SCR-123 | —       | 1.4.10                    | T7   | minor    | —          | A11Y-F-0016         | E47-D05 (#1304)              | `REG` A11Y-F-0016                                                                        |
| F-5 | `(heuristic)` The admin invite page is reached only through the rail, one way where 2.4.5 asks for more than one.                                                                                                                                                                                                                                                             | SCR-123          | —       | 2.4.5                     | T7   | minor    | —          | A11Y-F-0029         | engineering-only (as routed) | `REG` A11Y-F-0029                                                                        |
| F-6 | `(heuristic)` No merged text caps the chart's cursor region and its panel region together, and four chart announcements have a politeness and a moment but no string, so T3's parity read cannot be scripted word for word once SCR-030 mounts.                                                                                                                               | SCR-030          | —       | 4.1.3                     | T3   | major    | —          | A11Y-R-E12-D11-F-01 | E47-D07 (#1306)              | `REG` A11Y-R-E12-D11-F-01, A11Y-R-E12-D11-F-05 (SC assigned here; the register has none) |
| F-7 | `(heuristic)` At the shipped default (`significant`) no caller flags an update significant, so a screen-reader user hears no ambient price at all: silence, not flooding, is the default's risk; the trader must poll the mirror, which `05` frames as the user's choice. Minor, not major: the mirror and `Alt+T` read the price on demand, so no task is blocked or slowed. | SCR-117, SCR-030 | —       | n/a (usability, `05`:187) | T8   | minor    | —          | new                 | E47-D07 (#1306)              | `MODEL`:25 · `PW`:103 · `D07`:255 · `05`:185 · `05`:187                                  |
| F-8 | `(heuristic)` Reading the ladder, an SR user presses `Enter` on a row out of grid habit; three texts disagree on what `Enter` does there and one places a limit order. The merged spec names no key until it is ruled, so T5 stays unsafe to script.                                                                                                                          | SCR-050          | CMP-108 | 3.3.4                     | T5   | major    | —          | new                 | E47-D09 (#1308)              | `05`:67 · `D06`:428                                                                      |
| F-9 | `(heuristic)` A disconnected or reconnecting watchlist row's text resolves to the live text colour; the state rides only on the panel's status words, so a low-vision user scanning rows while switching symbol cannot see which are stale.                                                                                                                                   | SCR-100          | —       | 1.4.1                     | T1   | major    | —          | A11Y-R-E08-D12-F-01 | E47-D03 (#1302)              | `REG` A11Y-R-E08-D12-F-01 (SC assigned here; the register has none)                      |

### 3.1 The baseline counts (BQ-4; posted once on the E47 epic at merge)

Rows of this memo: blocker 0 · major 6 · minor 3 · total 9; new to the register 4 (F-1, F-2, F-7, F-8); cited from it 5. Tasks: completable 2, blocker 0, not built at the sha 7. The register's own counts stay D02's (`CAT`:9).

### 3.2 The WCAG 2.2 AA screen (what decides a keyboard and SR trading UI)

Every AA criterion that decides the task surfaces has one line; "not assessable" and "not assessed" are listed, never implied clear. Status: **finding** (an F row) · **no finding (heuristic)** · **not assessable at the sha** (the surface is not built) · **not assessed** (with the reason). The source is the merged cross-walk that meets the criterion (D04 §11, D09 §13) or the register.

| SC                                  | Task surfaces              | Source at the pin         | Status at the sha                                                                                  |
| ----------------------------------- | -------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------- |
| 1.4.1 Use of colour                 | T1 (SCR-100)               | `D04`:325                 | finding: F-9                                                                                       |
| 1.4.3 Contrast (minimum)            | T8 (SCR-116, SCR-117)      | `REG` A11Y-F-0018         | finding: F-3                                                                                       |
| 1.4.10 Reflow                       | T7, T8                     | `D04`:326                 | finding: F-4                                                                                       |
| 2.1.1 Keyboard                      | T1–T9, SCR-081, SCR-082    | `D09`:275                 | no finding (heuristic) on T8 and T9; the other surfaces are not built at the sha (§2, G3)          |
| 2.1.2 No keyboard trap              | T9 (CMP-094)               | `D04`:328                 | no finding (heuristic): `Esc` closes the sheet and focus returns (`CHS`:30–31)                     |
| 2.4.3 Focus order                   | T2, T6, `05`:278's flatten | `D04`:330                 | not assessable at the sha: SCR-060, SCR-074 and the rule-engine flatten are not built              |
| 2.4.5 Multiple ways                 | T7 (SCR-123)               | `REG` A11Y-F-0029         | finding: F-5                                                                                       |
| 2.4.6 Headings and labels           | T9 (SCR-013)               | `KMAP`:615–618            | finding: F-1                                                                                       |
| 2.4.7 Focus visible                 | T8, T9                     | `D04`:331                 | not assessed: a ring is judged on a rendered build (S1), not from code text; no finding is claimed |
| 2.4.11 Focus not obscured (minimum) | T2, T5                     | `D04`:332                 | not assessable at the sha: SCR-060 and SCR-050 are not built                                       |
| 2.5.7 Dragging movements            | SCR-082                    | `D09`:285                 | not assessable at the sha: the editor route renders a stub (G3)                                    |
| 2.5.8 Target size (minimum)         | every pointer target       | `D09`:282                 | not assessed: a pointer criterion, outside a keyboard + SR walk                                    |
| 3.2.1 On focus, 3.2.2 On input      | T2, T3, T5                 | `D04`:333, `D04`:334      | not assessable at the sha: the order ticket, SCR-030 and SCR-050 are not built                     |
| 3.3.4 Error prevention              | T5 (SCR-050)               | `05`:67                   | finding: F-8                                                                                       |
| 3.3.8 Accessible authentication     | sign-in (TOTP), not a task | `E47J`:61 (the task list) | not assessed: sign-in is outside the ticket's task script; listed so it is not read as clear       |
| 4.1.2 Name, role, value             | T7, T9                     | `D04`:335                 | not assessable at the sha for T7 (SCR-121, SCR-122 not built); no finding (heuristic) on T9        |
| 4.1.3 Status messages               | T3, T8                     | `D04`:336                 | finding: F-6                                                                                       |

### 3.3 T2 applicability (the E09-D09 T2 standing gate; BQ-0)

No AD or TOP row specifies a control: AD-1, AD-2 and AD-3 set a preference default, a cadence and a taxonomy row, AD-4 a search word, AD-5 a key binding, AD-6 a register record and AD-7 a session rule; TOP-1 and TOP-2 restate AD-5 and AD-4. None gates a control on a view-as context, a permission, an account or environment leg or a registered state, so G-T2.1a to G-T2.6 bind no row of this memo; it draws no frame and writes no reason string. The gated controls the script meets are specified by their owning specs, and a session checks them as built on the sheet (§11.3):

| Task | A T2 control the session may meet                        | What the session checks                                                                                                                              |
| ---- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| T2   | an order-ticket control shown disabled with a reason     | G-T2.1b: it stays in the Tab order; G-T2.1c: the reason is spoken from its description; G-T2.3: `Enter` changes nothing and re-shows the reason once |
| T6   | the environment switch while the Live gate is off        | the same three                                                                                                                                       |
| T7   | an admin form control outside the signed-in role's scope | the same three; admin navigation is T3 hidden, outside the gate                                                                                      |

A miss is an F row routed to the control's owning spec, never a fix here.

## 4. Proxy walkthroughs (proxies, not participants)

| W   | Proxy and goal                                                | Path at the sha                                              | Where it breaks `(heuristic)`                                                    |
| --- | ------------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| W1  | X1, NVDA daily driver: "what is the flatten key?"             | `Ctrl+/`, then reads the sheet table by table in browse mode | no row says flatten (F-1); seven tables before Positions (F-2)                   |
| W2  | X1: switches to Live on the merged specs only                 | the environment switcher and its confirm, as specified       | not built at the sha; the badge text in the region name is `05`:150's, to verify |
| W3  | X2, keyboard-only low-vision at 400 %: changes one preference | the settings route, then the accessibility screen            | the rail squeezes main (F-4); the default-blue links are hard to see (F-3)       |
| W4  | X1: watches a fast market at the default verbosity            | the shipped default `significant`                            | hears no ambient price (F-7); the fills and rejects are heard (§5)               |

## 5. Announcement flooding: SYNTHETIC counts and the cadence answer (AC3; BQ-6)

SYNTHETIC: E47-D07's seeded fast script (BTCUSDT, seed 1306, quote and mark at 10 Hz, prints at 40 Hz, `D07`:442) replayed by its own merged tool, every setting, at each cadence option. The merged script runs one minute; this memo's tool sets its duration to 2 minutes (the BQ-6 window), so the figures are this memo's, not D07's. A line is one spoken announcement; "polite" lines are ambient composites, "assertive" lines the fill and the reject the script contains. This tool re-derives every figure (G-FLOOD).

| Setting                          | Polite lines in 2 min (1 s / 2 s / 5 s) | Polite per minute at 2 s | Assertive lines in 2 min |
| -------------------------------- | --------------------------------------- | ------------------------ | ------------------------ |
| Off                              | 0 / 0 / 0                               | 0                        | 2                        |
| On significant change (default)  | 0 / 0 / 0                               | 0                        | 2                        |
| Always · Low                     | 0 / 0 / 0                               | 0                        | 2                        |
| Always · Normal                  | 23 / 23 / 22                            | 11.5                     | 2                        |
| Always · High (= Normal)         | 23 / 23 / 22                            | 11.5                     | 2                        |
| Always · Normal, whale prints on | 21 / 21 / 21                            | 10.5                     | 2                        |
| Reduce announcements on          | 0 / 0 / 0                               | 0                        | 2                        |

- **The unit is spoken composites per 2 minutes**, not D07's "field reads in the stream's minute" (`D07`:255): Always · Normal's 22 field reads make 11 composites in that minute, as `D07`:255 states. Whale prints add field reads (D07's 23) but lengthen each composite (about 44 characters against 39), so the speech estimate spaces them further apart and the composites fall to 21.
- **At the default the count is zero** (`MODEL`:25; `PW`:103): the AC's premise, flooding at default verbosity, does not hold at the sha (F-7). Flooding needs "Always": about 11.5 composites a minute at each of the three cadence options, far under the 30 a minute a strict 2 s cadence would allow, because the speech estimate, not the cadence, spaces them (`D07`:639's Q3).
- **The cadence answer to D05-G4 (`D05`:382) and D07-Q2 (`D07`:638): binary — the 2 s default and the 1 / 2 / 5 s options are not refuted; there is no measured value.** The three cadences give 23, 23 and 22 lines: the cadence barely binds in the synthetic stream, so no new number is proposed (AD-2). A re-check row goes to E47-Q02 (#1355), which measures speech rates.
- **The subjective rating** stays open (§11, S6; OQ-1).

## 6. Public-practice scan (BQ-8; no new fetch, see Deviation 5)

Only rows that decide something here; each rests on a page already fetched and cited in a merged text, with that text's fetched date. No third-party screenshot.

| Source (fetched date, citing text)                                                  | What it decides                                                                                              | URL                                                            |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| NVDA user guide, Browse Mode (2026-10-22, the E11-D07 reserved-keys file)           | the table quick key and browse-mode reading behind T9's count (§2)                                           | <https://download.nvaccess.org/documentation/userGuide.html>   |
| NVDA commands quick reference, Single Letter Navigation (2026-10-22, the same file) | the same count; the keys the protocol logs (S5)                                                              | <https://download.nvaccess.org/documentation/keyCommands.html> |
| WAI-ARIA APG grid pattern (2026-10-19, the E11-D01 research memo)                   | `Page Down` moves by "an author-determined number of rows": grid keys navigate, the reading habit behind F-8 | <https://www.w3.org/WAI/ARIA/apg/patterns/grid/>               |

## 7. Top 10 things that must change (deliverable 2; for E47-D02)

Ranked by the cost to a keyboard or screen-reader trader; each row has one owner. Pasted on #1300 at READY and linked from E47-D02 (#1301) at merge.

| TOP    | Must change                                                                                           | From      | Owner           |
| ------ | ----------------------------------------------------------------------------------------------------- | --------- | --------------- |
| TOP-1  | one ruled `Enter` on the ladder before SCR-050's keyboard path ships; until then no order on `Enter`  | F-8, AD-5 | E47-D09 (#1308) |
| TOP-2  | "flatten" finds `positions.close_all` in the sheet and the palette, or the flatten-all command exists | F-1, AD-4 | E47-D09 (#1308) |
| TOP-3  | build the cheatsheet search the merged spec defines                                                   | F-2       | E47-S08 (#1322) |
| TOP-4  | mount SCR-045's table and SCR-030 so `Alt+T` and the parity task can run                              | T3, T4    | E47-S01 (#1316) |
| TOP-5  | write the four missing chart announcement strings                                                     | F-6       | E47-D07 (#1306) |
| TOP-6  | name which ambient updates are significant, so the default is not silent                              | F-7, AD-3 | E47-D07 (#1306) |
| TOP-7  | settings link colour to AA on every theme                                                             | F-3       | E47-D05 (#1304) |
| TOP-8  | watchlist connection text distinct from primary text                                                  | F-9       | E47-D03 (#1302) |
| TOP-9  | the rail collapses at 320 CSS px                                                                      | F-4       | E47-D05 (#1304) |
| TOP-10 | the owner runs §11 on the R4 build before the epic claims AA                                          | AC1, AC4  | owner           |

## 8. Adopted decisions AD-1..AD-7 (heuristic, PROPOSED)

Each stays PROPOSED; a reviewer marks it satisfied or violated from the named artefact alone.

| AD   | Decision (PROPOSED)                                                                                    | Violates if                                                                                                    | From      | Owner                            |
| ---- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- | --------- | -------------------------------- |
| AD-1 | the shipped verbosity default stays "On significant change" (`MODEL`:25), as E47-D07 has it            | a SCR-117 frame or spec selects "Always" by default, or cites this memo for a flooding measure                 | §5, F-7   | E47-D07 (#1306), E47-S07 (#1321) |
| AD-2 | the cadence stays 2 s by default with 1 / 2 / 5 s options; this memo supplies no measured value        | a spec cites E47-D01 for a cadence other than 2 s, or drops an option                                          | §5        | E47-D05 (#1304)                  |
| AD-3 | before AD-1 is final, the taxonomy names which ambient updates are significant                         | E47-D07's taxonomy has no row naming a significant ambient update while the default is "On significant change" | F-7       | E47-D07 (#1306)                  |
| AD-4 | the word "flatten" finds `positions.close_all` in SCR-013's and SCR-012's search                       | typing "flatten" in either search returns no row while no flatten-all command exists                           | F-1       | E47-D09 (#1308), E47-S08 (#1322) |
| AD-5 | no plain `Enter` places an order on a grid a reader reaches by arrows until one ladder model is ruled  | a SCR-050 spec or frame binds plain `Enter` to an order placement before the ruling                            | F-8       | E47-D09 (#1308)                  |
| AD-6 | a session blocker enters the register in its record shape with its keystroke sequence (§9)             | a D01 session blocker reaches the register without screens, SC, severity or the keystrokes                     | AC4, BQ-4 | E47-D02 (#1301)                  |
| AD-7 | every order task in a session runs on Bybit demo with the Live gate off (C-2.11), checked on the sheet | a session sheet lacks the environment check before T2                                                          | AC5       | owner                            |

## 9. D02's absorption AC: blocker records in the register's shape (BQ-3, BQ-4)

E47-D02's AC "Research findings are absorbed" (`E47J`:86) asks for every D01 blocker in the register with its evidence linked. **This memo has no blocker at the sha** (§3.1), so it emits none; #1301 can close on that statement. A blocker from the owner's sessions enters `REG` with the register's own fields: `id` (the next free), `screens`, `sc`, `level`, `severity` = `blocker`, `source` = "E47-D01 research", `title`, `remedy`, `designOwner`, `status` = `open`, plus the keystroke sequence and the session id in its evidence; one the auditors cannot reproduce is recorded as such with the reason (AD-6).

## 10. Downstream feeds

| Ticket          | Takes from this memo                                               |
| --------------- | ------------------------------------------------------------------ |
| E47-D02 (#1301) | §7 and §9: the top-10 and the absorption statement (its AC)        |
| E47-D05 (#1304) | §5's answer to D05-G4 and D05-Q1 (`D05`:390); AD-2; F-3, F-4       |
| E47-D07 (#1306) | §5's answer to D07-Q2; AD-1, AD-3; F-6, F-7                        |
| E47-D09 (#1308) | F-1, F-8; AD-4, AD-5                                               |
| E47-S08 (#1322) | F-2; AD-4                                                          |
| E47-S01 (#1316) | TOP-4                                                              |
| E47-Q01 (#1314) | §2's task table and §11's scripts as expected-result inputs; C5    |
| E47-Q02 (#1355) | §5's re-check row (the measured rates); §11's speech-viewer method |
| E47-X01 (#1326) | the surfaces of §2; C5                                             |
| E49-D01 (#1330) | §11 as a protocol method                                           |

## 11. Owner session protocol (ready to run; nothing below has been run)

### 11.1 Participants, consent, data

Up to five sessions of 60 minutes: the owner, up to two account managers, and the two external assistive-technology participants the ticket names, recruited by the owner (OQ-4). Each participant chooses their own AT, verbosity and speech rate, gets a break every 20 minutes, and is briefed that this is a private internal tool under NDA. Recordings, speech-viewer logs and consent forms go to the owner's restricted store, never the docs tree (OQ-5); account ids are redacted from anything published. Seeded fixture users only on the admin screens.

### 11.2 Rig and preconditions

| S   | Step                                                                                                                                                                                                             |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1  | the R4 Electron production build, Windows 11 23H2, NVDA pinned per `SRR`'s changelog; default hotkey map, dark theme, default verbosity                                                                          |
| S2  | **Demo only** (C-2.11): the environment badge reads DEMO and the Live gate is off, checked and initialled on the sheet before any order task (AC5)                                                               |
| S3  | a second machine captures screen and audio; NVDA's speech viewer log is saved to text for the announcement count                                                                                                 |
| S4  | **5-minute ceiling** per task, a moderator-side bound, never a participant-facing timer; breaks and moderator pauses are excluded from elapsed time; at the ceiling the task is a blocker with its keystroke log |
| S5  | **no coaching:** the moderator never names a key or a workaround before the failure is recorded; a keystroke logger runs throughout                                                                              |
| S6  | a mouse-using control run of the same script gives the time ratio; a ratio above 3 on a core trading task is a finding even if it completes                                                                      |
| S7  | a pilot with an internal tester first; pilot data is excluded                                                                                                                                                    |

### 11.3 Recording sheet

Session id · date · initials · persona or role · AT and version · speech rate · build sha · environment check (S2) · per task T1–T9: completion (yes / no / with help), elapsed seconds (breaks and moderator pauses excluded), mouse-control seconds, focus losses, "where am I?" count, the keystroke sequence on a failure · per T2 control met: in the Tab order, reason spoken, `Enter` re-shows it (§3.3) · the speech-viewer log's polite and assertive lines per minute over a 2-minute fast market at default verbosity, then at "Always" · the participant's 1–5 usability rating of each · any mirror announcement later than 200 ms after a focus move (a finding forwarded to E46, OQ-2) · verbatim quotes on flooding.

Decision rules: a task no participant completes keyboard + SR only is a blocker (`05`:282) and enters `REG` per §9; a §3 row no session reproduces is demoted with a note; AD-1 changes only if both NVDA sessions rate the default unusable; three findings are spot-reproduced independently before publication.

### 11.4 Agenda (60 min)

| Minutes | Step                                                           |
| ------- | -------------------------------------------------------------- |
| 0–5     | consent, AT set-up, the environment check (S2)                 |
| 5–20    | T1, T3, T4                                                     |
| 20–22   | break                                                          |
| 22–40   | T2, T5, T6                                                     |
| 40–42   | break                                                          |
| 42–52   | T7, T8, T9                                                     |
| 52–60   | the 2-minute fast market at two settings, the ratings, debrief |

## 12. Owner walkthrough checklist (posted on #1300 at READY)

1. Confirm the proxies X1 and X2 stand in for the two external participants until you recruit them (OQ-4).
2. Confirm D01 verifies the merged D02..D13 set instead of shaping it (BQ-3, C4).
3. Approve or override AD-1: the default stays "On significant change"; the synthetic default count is zero (§5).
4. Approve or override AD-2: 2 s default, 1 / 2 / 5 s options, no measured value (§5, D05-G4).
5. Decide AD-4: "flatten" as a search word for "Close all in view", or a flatten-all command (F-1).
6. Decide with E47-D09 the ladder `Enter` model, and confirm AD-5 meanwhile (F-8).
7. Open the cheatsheet with `Ctrl+/` and find "Close all in view" with the keyboard yourself (T9).
8. Confirm the zero-blocker baseline and the counts to post on the E47 epic (§3.1).
9. Name the restricted store for recordings and consent forms (OQ-5).
10. Comment `approved` on #1300, or leave rework notes citing F, AD, C, G or OQ ids.

## 13. Contradictions, gaps and open questions

### 13.1 Contradictions (none resolved silently)

| C   | Contradiction                                                                                                                                          | This memo's resolution (PROPOSED) · owner                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| C1  | `05`:185 describes a polite ambient region updated every 2 s by default vs the shipped default `significant`, which reads none (`MODEL`:25; `D07`:255) | AD-1 keeps the shipped default; A1 · E47-D07 (#1306)           |
| C2  | `05`:64 "Flatten all" on `Ctrl+Shift+F` vs no flatten-all command and `Ctrl+Shift+W` on close-all (`KMAP`:615–618; `D09`:395)                          | traced on close-all (T9); AD-4 · E47-D09 (#1308)               |
| C3  | the ladder's `Enter`: `05`:67 places a limit; the merged texts disagree (`D06`:428)                                                                    | AD-5 meanwhile · E47-D09 (#1308)                               |
| C4  | the ticket has D01 shaping D02..D09 (`E47J`:61) vs D02..D10 and D13 merged first (`D13`:7)                                                             | D01 verifies the merged set (BQ-3) · owner                     |
| C5  | E47-Q01 and E47-X01 list E47-D01 for themes, contrast and CVD (`E47J`:424, `E47J`:574) vs E47-D03 and E47-T03 owning them                              | this memo carries no contrast or CVD number · E47-Q01, E47-X01 |

### 13.2 Gaps (none invented; each routed)

| G   | Gap                                                                                                                                                                                                             | Owner                            |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| G1  | `D05`:50, `D05`:382, `D05`:390 and `D07`:638 cite the cadence as `05`:151; at the pin that line is the CVD gate and the cadence is `05`:185                                                                     | E47-D05 (#1304), E47-D07 (#1306) |
| G2  | no R4 build, no Live gate (E44) and no recruited external participant exist, so AC1 cannot start                                                                                                                | owner                            |
| G3  | the rule editors SCR-081 and SCR-082 are ticket surfaces with no task in BQ-5's nine and a stub route at the sha (`TREE`:83); their keyboard and non-drag paths (2.1.1, 2.5.7; `D09`:175–178) wait on the build | E47-S03 (#1317)                  |

### 13.3 Open questions

| OQ   | Question                                                                                         | Owner |
| ---- | ------------------------------------------------------------------------------------------------ | ----- |
| OQ-1 | the participants' subjective rating of the default and of "Always" (§11.3)                       | owner |
| OQ-2 | the time ratio against the mouse control, and whether a mirror announcement lags 200 ms (to E46) | owner |
| OQ-3 | does any session overturn AD-1 or AD-2                                                           | owner |
| OQ-4 | who recruits the two external AT participants; `10` names only the owner and managers            | owner |
| OQ-5 | where the restricted store for recordings and consent forms is                                   | owner |
| OQ-6 | does `05`'s rule-engine flatten (`05`:278) join the script as a tenth task (BQ-5 lists nine)     | owner |

### 13.4 Proposed owner-document amendments (A rows; none edited here)

| A   | Owner text                                                         | Proposed amendment (PROPOSED)                                                                   | From     | Owner                       |
| --- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- | -------- | --------------------------- |
| A1  | `05`:185 reads as if ambient narration were on by default          | say that the default reads significant updates only, and the 2 s cadence applies under "Always" | C1, AD-1 | owner, with E47-D07 (#1306) |
| A2  | `05`:64 names a flatten-all command the registry does not have     | align the row with the registry, or register the command                                        | C2       | owner, with E47-D09 (#1308) |
| A3  | E47-Q01's and E47-X01's dependency lines cite E47-D01 for contrast | cite E47-D03 and E47-T03                                                                        | C5       | owner (the plan JSON)       |

## 14. Audit tool and its mutations

`docs/design/_tools/e47_d01_research_audit.py` imports `spec_audit_lib` from main and keeps only this memo's rows; `docs/design/_tools/test_e47_d01_research_audit.py` was written first. Every mutation trips exactly its own gate.

| M    | Gate        | Mutation                              |
| ---- | ----------- | ------------------------------------- |
| M-1  | G-AC        | a scenario name reworded              |
| M-2  | G-BQ        | the BQ heading says RULED             |
| M-3  | G-TASKS     | a task verdict outside the vocabulary |
| M-4  | G-ROWS      | a finding loses its heuristic label   |
| M-5  | G-ROWS      | a finding with an unknown severity    |
| M-6  | G-KEYS      | a blocker without its keystrokes      |
| M-7  | G-D02       | a register id that does not exist     |
| M-8  | G-ROUTE     | a finding routed to an agent          |
| M-9  | G-COUNTS    | the baseline counts drift             |
| M-10 | G-FLOOD     | a synthetic count edited by hand      |
| M-11 | G-CITE      | a cite past the end of its document   |
| M-12 | G-CHECKLIST | an eleventh checklist item            |
| M-13 | G-NOCLOSE   | a closing keyword                     |
| M-14 | G-PUBLIC    | a local path                          |
| M-15 | G-PUBLIC    | a URL outside the public scan         |
| M-16 | G-UNTOUCHED | an owner document edited              |
| M-17 | G-MUTLIST   | the list drifts                       |
| M-18 | G-ROWS      | a finding without its SC              |
| M-19 | G-SC        | an AA criterion drops off the screen  |
| M-20 | G-T2        | the T2 applicability note is missing  |

## 15. References

`05` §1, §3, §6.2, §8 · `10` §2–§3 · `11` US-SET-007 · `14` SCR-012, SCR-013, SCR-030, SCR-045, SCR-050, SCR-060, SCR-063, SCR-074, SCR-081, SCR-082, SCR-100, SCR-102, SCR-116, SCR-117, SCR-121..SCR-123 · `15` CMP-086, CMP-094, CMP-108 · `CAT` §1 · `REG` · `D04`..`D13` · `SRR` · issues #1300, #1301, #1302, #1304, #1306, #1308, #1314, #1316, #1317, #1321, #1322, #1326, #1330, #1355
