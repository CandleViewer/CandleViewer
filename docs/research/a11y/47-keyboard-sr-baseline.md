# E47-D01 — UX research: the keyboard-only and screen-reader trading baseline

- **Ticket:** E47-D01 (issue #1300) · **Status:** Draft, text-first, pre-staged. All eight `blocked_by` tickets (E44-T01..T06, E44-K01, E44-X02) are open, so this PR is `Refs #1300` plus a `Partial:` line and closes nothing; no commit or body carries a closing keyword (BQ-0). The BQ list (comment 6634720172) is **RULED** by the ruling of record (comment 6637509239: AGREE 2, AGREE with a rider 6, AMEND 2); this memo is built on its defaults with both AMENDs and every rider applied. Every finding is `(heuristic)`; every decision is **PROPOSED**, owner approval pending; the orchestrator's design approval adopts the PROPOSED decisions as interim rulings under the 2026-10-29 delegation, and the owner can reverse any one by one line (agent-delivery adaptations, owner decision 2026-09-25). A change this memo proposes to an owner document is an A row (§13.4), never an edit.
- **Offline (BQ-0 rider):** the memo and its tool run nothing live, open no network connection and contact no CandleViewer or exchange host; every identity in the protocol is a seeded fixture one (the ticket's Security notes).
- **Method:** a heuristic evaluation (Nielsen's N1–N10, the trading rules of `05` §3 and §6, and the WCAG 2.2 success criteria), the task script of `05` §8.2 item 3 walked against main's code and the merged E47 specs, two persona-coded proxy walkthroughs, and a short public-practice scan (§1). **No session was run: no participant, timing, count of focus losses or quote exists, and none is invented.**
- **Scope (ticket):** the task script over SCR-100 / SCR-102, SCR-030, SCR-045, SCR-050, SCR-060, SCR-063, SCR-074, SCR-116, SCR-117, SCR-013, SCR-012, SCR-081, SCR-082 and SCR-121..SCR-123; the announcement-verbosity default (deliverable 4); the top-10 list for E47-D02 (deliverable 2).
- **Out of scope (ticket):** visual design, wireframes and tokens (E47-D02/D03 onward); mobile screen readers; Safari and non-Electron targets; remediation (findings become rows, not fixes).
- **Proxies, not participants (BQ-8, AMEND):** X1 is a **P3** proxy, the NVDA daily driver (`10`:164, "the most likely persona to use a screen reader or high zoom"); X2 is an **M1** proxy, the keyboard-only low-vision trader (`10`:250, the rule author whose node-graph model is keyboard and screen-reader complete; 200 % and 400 % zoom, `10`:268). Both stand in for the ticket's two external experts and stay labelled proxies, never participants. The owner (P1, `10` §2) is the first participant §11 runs.
- **Ids:** BQ pre-writing question · T task · F finding (review-table row) · W walkthrough step · AD adopted decision · S session-protocol step · AT matrix row · CH AT output channel · C contradiction between binding texts · G gap · A proposed owner-document amendment (not edited) · OQ open question · TOP top-10 row.
- **Pin.** Every `path:line` cite is at `main` `aa0a02b8c54c877c39718f101abf69467cb4a2d6`.
- **Shorthand.** `NN` = `docs/plan/NN-*.md`; `E47J` = `docs/plan/backlog/E47.json` (line 61 is this ticket's body, line 86 E47-D02's); `CAT` = `docs/plan/a11y/47-audit-catalogue.md`; `REG` = `docs/plan/a11y/47-audit-register.json` (cited by finding id); `D04`..`D13` = `docs/design/E47/E47-D04.md`..`E47-D13.md`; `KMAP` = `apps/web/src/keymap/keymap.json`; `CHS` = `apps/web/src/keymap/Cheatsheet.tsx`; `HOST` = `apps/web/src/keymap/KeymapHost.tsx`; `MODEL` = `apps/web/src/features/a11y-preferences/model.ts`; `PW` = `apps/web/src/chart/a11y/politeWriter.ts`; `CTP` = `apps/web/src/chart/a11y/ChartTablePanel.tsx`; `SHELL` = `apps/web/src/features/app-shell/ShellLayout.tsx`; `TREE` = `apps/web/src/routes/tree.tsx`; `SRR` = `docs/qa/a11y/sr/README.md`; `XC`, `CDC`, `FPI`, `DOM`, `RFE` = the E47-T04 scripts `docs/qa/a11y/sr/scripts/00-cross-cutting.md`, `10-chart-data-cursor.md`, `20-footprint-inspection.md`, `30-dom-ladder.md`, `40-rule-form-editor.md`; `README` = `docs/design/README.md`; `CONST` = `CONSTITUTION.md`. Companion check: `docs/design/_tools/e47_d01_research_audit.py` (`--check`, `--self-test`, `--repin`).

## Acceptance-criteria trace (E47-D01, issue #1300)

Status key: **done** = delivered as worded · **done (text)** = delivered as text; nothing in it was run · **heuristic-only** = delivered through the adaptation, pending the owner's run · **open** = needs the owner's sessions or decision and is not claimed · **owner protocol** = an owner-run item that puts nothing in the repository (`05`:293–294) · **not applicable** = no product code.

| Ticket AC or deliverable                                                                               | Where          | Status                         | Note                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------ | -------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC1 "Study executed against the real build": five sessions on the R4 build, NVDA 2024.x pinned         | §11            | open                           | no session was run; the protocol is written (5-minute ceiling, no coaching, keystroke log, Demo-only rig, the speech-viewer channel CH-SPEECH-VIEWER)                                             |
| AC2 "Findings are actionable and traceable": SCR, CMP where one applies, WCAG 2.2 SC, severity         | §3, §3.1, §3.3 | done (two rows usability-only) | every F row carries them in the review-table shape, `(heuristic)`; F-2 and F-3 are best-practice rows with no SC failed; register findings are cited by id (§3.1); G-ROWS and G-REVIEW check them |
| AC3 "Announcement flooding is quantified, not guessed": announcements per minute and a cadence         | §5, AD-1, AD-2 | heuristic-only                 | quoted from E47-D07's merged matrix (SYNTHETIC, its stream minute); the subjective rating is open (§11)                                                                                           |
| AC4 "Participant cannot complete a task (failure path)": a blocker with its exact keystroke sequence   | §3, §9, §11 S4 | open                           | no blocker is found at the sha (§2); a session blocker carries its keystrokes in the Sentence; G-KEYS refuses a blocker row without them                                                          |
| AC5 "No trading risk introduced by the study": every order task on Bybit demo with the Live gate off   | §11 S2, AD-7   | done (text)                    | a protocol rule; no order was placed                                                                                                                                                              |
| Deliverable 1: the findings report at `docs/research/a11y/47-keyboard-sr-baseline.md`, severity-ranked | this file, §3  | done                           | one file holding the memo, the top-10 and the protocol (BQ-2)                                                                                                                                     |
| Deliverable 2: a one-page top-10 consumed by E47-D02                                                   | §7             | done                           | pasted on #1300 at READY; linked from E47-D02 (#1301) at merge                                                                                                                                    |
| Deliverable 3: session recordings and transcripts stored per the retention policy                      | §11.1          | owner protocol                 | an owner-leg line: capture per `SRR`'s Capture procedure (`SRR`:32); nothing recorded enters the repository                                                                                       |
| Deliverable 4: a proposed announcement-verbosity default backed by the flooding data                   | §5, AD-1       | heuristic-only                 | PROPOSED; backed by D07's SYNTHETIC counts, not observed flooding                                                                                                                                 |
| Measures per task: completion, time vs a mouse control, focus-loss count, "where am I?" count, quotes  | §2, §11.3      | open                           | per task, operator counts only, an "operator ratio, not a time" (BQ-7); the rest is on the session sheet                                                                                          |
| Performance note: a mirror announcement > 200 ms is a finding forwarded to E46                         | §11.3, OQ-2    | open                           | needs a run; routed to E46 only when someone observes it                                                                                                                                          |
| Observability: severity counts recorded on the E47 epic as the baseline                                | §3.2           | open                           | posted on the E47 epic (#73) beside D02's open 4 / 26 / 64 / 12 (`CAT`:9) as "D01 heuristic rows", not a second baseline (BQ-4)                                                                   |
| DoD: findings report merged, peer-reviewed by the Accessibility role                                   | this PR        | open                           | owner approval pending                                                                                                                                                                            |
| DoD: top-10 attached to the ticket and linked from E47-D02                                             | §7             | open                           | at READY and at merge                                                                                                                                                                             |
| DoD: every blocker has a follow-up ticket or is folded into a named E47 design ticket's scope          | §3, §9         | done                           | zero blockers at the sha; every row is routed in the register's vocabulary (BQ-4); no new issue is filed                                                                                          |
| DoD: CDO sign-off recorded on the ticket; Accessibility role co-signs                                  | §12            | open                           | the owner's `approved` comment (agent-delivery adaptations)                                                                                                                                       |
| DoD: recordings stored and access-restricted; consent forms filed                                      | §11.1          | owner protocol                 | the owner's restricted store (OQ-5); nothing enters the repository                                                                                                                                |
| README: the research board on the ticket's Penpot page                                                 | §0             | not applicable                 | waived for this memo by the ruling of record (BQ-9); Deviation 6; checklist item 8                                                                                                                |
| Brief: `apps/web` paths, `pnpm` commands, Storybook, axe, coverage                                     | Deviation 3    | not applicable                 | no UI code in a research ticket                                                                                                                                                                   |

## Deviations

1. **No sessions run.** The five moderated sessions become the heuristic evaluation (§3), the task walk (§2), the proxy walkthroughs (§4), the flooding counts quoted from E47-D07 (§5), the owner session protocol (§11) and the owner walkthrough checklist (§12), per the ticket's adaptation clause (`E47J`:61). AC1 and AC4 stay **open**.
2. **Text-first, pre-staged.** The blockers are open, so this PR is `Refs #1300` with a `Partial:` line and no closing keyword (BQ-0).
3. **The ticket's title, paths and commands.** The brief's `apps/web` paths, its `pnpm` commands, its "E47-D01: …" PR title and its closing line are recorded here as deviations: the PR title is the conventional `docs(design-system): …` (C-4.10) and the PR is `Refs #1300`.
4. **Inverted order.** E47-D02 (#1301) and E47-D03..D10 and D13 merged before this memo; D01 is the task-level walk of the merged set (BQ-3, C4).
5. **Public scan.** No page was fetched for this memo; §6 rests on pages already fetched and cited in merged texts, with their dates, and adds no new quote.
6. **No Penpot evidence: waived.** `README`:44 and `README`:57 asks every design ticket, research included, for a Penpot page and PNGs. The ruling of record (comment 6637509239, BQ-9) waives that requirement for this research memo under the 2026-10-29 delegation, as ruled for the #1479 pack; the owner may veto through checklist item 8.

## BQ list — RULED (comment 6637509239)

The pre-writing questions are posted on #1300 (comment 6634720172); the ruling of record is comment 6637509239. A row reads the ruled text this memo builds; an AMEND replaces the default.

| BQ   | Question                              | Verdict      | Ruled text built here                                                                                                                                                                                                                         | Where              |
| ---- | ------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| BQ-0 | Standing rules                        | AGREE +rider | `Refs #1300` + `Partial:`, no closing keyword; branch and `docs(design-system):` title valid, the ticket's title and paths as Deviation lines; rider: nothing live, no network, no host named, seeded fixture identities                      | header, Deviations |
| BQ-1 | Done when no session can run          | AGREE        | an AC trace; AC1 and AC4 open behind the protocol; AC2 done (heuristic); AC3 heuristic-only; AC5 a protocol rule; recordings and consent are owner-protocol items that put nothing in the repository                                          | AC trace, §11      |
| BQ-2 | Report path and file set              | AGREE +rider | the ticket's path, one file; rider: capture is `SRR`'s Capture procedure, cited not restated; nothing recorded enters the repository; retention is an owner-leg line                                                                          | this file, §11.1   |
| BQ-3 | D02..D13 merged before D01            | AGREE +rider | D01 is the task-level walk of the merged set; rider: this PR edits no register, findings, routing or catalogue file; D02 absorbs through one `reviews` entry after merge; a D02 finding is cited by id, never re-minted                       | §2, §3.1, §9       |
| BQ-4 | Finding shape, severity, routing      | AMEND        | the review-table shape `catalogue.py` parses: F-n ids, Screen / Clause / Severity / Sentence / Owner, the count marker, keystrokes inside a blocker's Sentence, the register's owner vocabulary; counts posted on #73 as "D01 heuristic rows" | §3, §3.2, §9       |
| BQ-5 | The task script against what is built | AGREE +rider | `05`'s order and the verdict words; "flatten" traced on `positions.close_all`; rider: `05`'s three extra tasks, the rule-engine flatten walked as T6; each task names its E47-T04 oracle; `SURFACE PENDING` cross-referenced                  | §2                 |
| BQ-6 | Flooding and the cadence              | AGREE +rider | the binary cadence answer; rider: per-minute counts quoted from D07's matrix, no second simulator; the 2-minute window is the observed-session protocol's; the stale `05`:151 pointer goes as C6                                              | §5, §11.3, C6      |
| BQ-7 | Timing nobody can take                | AGREE        | operator counts, "operator ratio, not a time"; a ratio over 3 a `(heuristic)` candidate; the time ratio and the 200 ms latency open, the latter to E46 only when observed                                                                     | §2, §11.3          |
| BQ-8 | Heuristics, proxies, public sources   | AMEND        | proxies carry persona codes (P3 for the NVDA daily driver, M1 for the keyboard-only low-vision proxy); the E19-D01 BQ-12 scan form; the public gate built from `public_re(omit=("url", "www"))`                                               | header, §4, §6     |
| BQ-9 | Tool, boards, size, downstream        | AGREE +rider | text-only waived for this memo (Deviation 6, checklist item 8); the tool in the house shape, inline `--check` / `--self-test`, no separate test file; size stated at the first push; C5 for the stale theme and contrast pointers             | §0, §13.1, §14     |

## 0. Research boards — none (waived by the ruling)

The ruling of record (BQ-9) waives text-only for this research memo under the 2026-10-29 delegation: a research memo and protocol is not a screen, as ruled for the #1479 pack. `README`:44 and `README`:57 still tells the `code-reviewer` to fail a design PR without a Penpot page, so the PR body carries Deviation 6 and the owner checklist offers text-only or boards (§12, item 8). The findings are tables per the ticket's accessibility notes (structured markdown, no screenshot-only finding).

## 1. Method note (agent-delivery adaptation, owner decision 2026-09-25)

The ticket asks for five moderated 60-minute sessions on the R4 Electron build with NVDA 2024.x pinned (`E47J`:61; `05`:263). No R4 build, no Live gate and no participant exist, so the sessions become (1) the task script walked against main's code and the merged specs at the pin (§2); (2) a heuristic evaluation (§3); (3) two persona-coded proxy walkthroughs (§4); (4) the flooding counts quoted from E47-D07's merged matrix (§5); (5) a public-practice scan (§6); and (6) a protocol the owner can run (§11). `05` §8.4 governs what this memo is: "An agent-run pass is recorded as "(heuristic)" and counts toward none of the §8.1 passes." (`05`:293–294). Nothing is written under `docs/qa/` or `qa/evidence/`.

Heuristics: Nielsen's N1–N10; `05`'s trading rules (keyboard-first as a speed requirement, `05`:15; the escape hatch `Alt+T`, `05`:57; the throttled ambient region, `05`:185; the task-based pass, `05`:274–280; the severity bar, `05`:282); the WCAG 2.2 AA success criteria. The register vocabulary is D02's (`CAT`:9, `CAT`:56).

## 2. The task script at the sha (`05` §8.2 item 3 order; BQ-5)

Verdicts: **completable** (the path exists keyboard + SR, read from main's code and the merged spec; no screen reader was run, so it is not an observed pass, and S4 re-verifies it) · **blocker** (it exists and cannot be finished keyboard + SR) · **not built at the sha** (D02's "not auditable at sha"; the cross-reference is E47-T04's `SURFACE PENDING`, `SRR`:28). Operator counts: K keystrokes on the shortest keyboard + NVDA path, P pointer actions for the same goal; an "operator ratio, not a time" (BQ-7). The T04 oracle is the E47-T04 script step that already covers the task; this memo cites it and restates none.

| T   | Task (source)                                                                                                 | Surface           | Verdict              | Operator count (K / P) | T04 oracle                                            | Evidence                                                                                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------- | ----------------- | -------------------- | ---------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | switch symbol via the watchlist search (`05`:275)                                                             | SCR-100, SCR-102  | not built at the sha | not counted            | XC-04 (`XC`:36)                                       | SCR-100 (`14`:2298) is not built; the global symbol search (`14`:2344) is mounted (`SHELL`:60) but no chart panel is                               |
| T2  | place and cancel a limit order on the ticket (`05`:276; ticket task 4)                                        | SCR-060, SCR-063  | not built at the sha | not counted            | DOM-06, DOM-09, DOM-11 (`DOM`:42, `DOM`:45, `DOM`:47) | SCR-060 (`14`:1445) and SCR-063 (`14`:1534) are not built; the cancel key is `05`:63                                                               |
| T3  | read the last 5 bars via the mirror and via `Alt+T`, compare parity (`05`:277; the five bars are `E47J`:61's) | SCR-030, SCR-045  | not built at the sha | not counted            | CDC-02, CDC-04, CDC-07 (`CDC`:35, `CDC`:37, `CDC`:40) | `Alt+T` is registered (`KMAP`:337–340), the table panel is built (`CTP`:63) and mounted by no route; SCR-030 is not mounted                        |
| T4  | inspect one footprint bar's price levels (ticket task 3)                                                      | SCR-030, SCR-045  | not built at the sha | not counted            | FPI-02, FPI-06 (`FPI`:36, `FPI`:40)                   | as T3                                                                                                                                              |
| T5  | read the top 10 DOM levels (ticket task 5)                                                                    | SCR-050           | not built at the sha | not counted            | DOM-03..DOM-05 (`DOM`:39–41)                          | SCR-050 (`14`:1195) is not built; its trade keys are unresolved (F-4)                                                                              |
| T6  | trigger a rule-engine flatten; the position-closed event announced, focus not stolen (`05`:278)               | SCR-081, SCR-082  | not built at the sha | not counted            | RFE-06, XC-07 (`RFE`:38, `XC`:39)                     | both rule-editor routes render a stub (`TREE`:83; `14`:1895, `14`:1942); RFE-06 arms a rule and XC-07 reads a fill, no step fires a flatten        |
| T7  | Demo→Live: the confirm dialog operable, the badge change announced (`05`:279)                                 | SCR-074, SCR-075  | not built at the sha | not counted            | XC-01 (`XC`:33), the badge read only                  | SCR-074 (`14`:1770) is not built and the Live gate is E44's (blocked_by); walked on the merged specs only (W2)                                     |
| T8  | the admin form: names, roles, values of every control (`05`:280)                                              | SCR-121..SCR-123  | not built at the sha | not counted            | none                                                  | SCR-121 and SCR-122 are not built, so the task as worded cannot run; SCR-123 is reachable and its open rows are A11Y-F-0016 and A11Y-F-0029 (§3.1) |
| T9  | open and change one accessibility preference (ticket task 6; US-SET-007)                                      | SCR-117           | completable          | not counted            | XC-05 (`XC`:37), one preference by shortcut           | the screen is routed (`TREE`:58); its open rows are A11Y-F-0018 and A11Y-F-0016 (§3.1) and F-3                                                     |
| T10 | find the binding for "flatten" via the cheatsheet (ticket task 7)                                             | SCR-013 (CMP-094) | completable          | ≈ 13 / 1–3 (ratio > 3) | none                                                  | traced on `positions.close_all` (`KMAP`:615–618) as `D09`:233 does; the sheet is mounted (`HOST`:165); F-1, F-2                                    |

T10's count: `Ctrl+/` opens the sheet with focus on Close (`CHS`:30–31); NVDA's browse-mode toggle, then the table quick key seven times (the sheet renders one captioned table per context in first-use order, Positions seventh, `CHS`:101–111), three row moves to "Close all in view (confirm)" and one cell move to its binding: about 13 keystrokes against one shortcut or click and a scroll for a sighted pointer user. Two of the ten tasks are completable and none is a blocker at the sha; eight need surfaces that are not built. `05` §8.2 item 3 adds three tasks to the ticket's seven (`05`:278–280), so T6 walks the rule-engine flatten; its rule editors' own keyboard paths, the non-drag twins of `D09`:175–178 included (2.5.7), are not assessable and route to E47-S03 (G2).

## 3. Heuristic evaluation (every finding `(heuristic)`; BQ-4's review-table shape)

Severity (`05`:282; D02's words, BQ-4): **blocker** (a task cannot be completed keyboard + SR only) · **major** (awkward but completable, or a spec-level risk to a core trading task) · **minor** · **info**. The table is in the shape `docs/plan/a11y/_tools/catalogue.py` parses: ids F-1..F-n, the Screen column attributes each row, the Clause names the SC (`n/a (usability, …)` marks a best-practice row that fails none: F-2, F-3), a blocker's keystroke sequence stands inside its Sentence (`keystrokes:` then the sequence), the remedy follows the Sentence after a middle dot, and the Owner is the register's vocabulary (E47-D03..D10 or engineering-only). A result that is already a register finding is never a row here (§3.1).

<!-- audit:f=4/0/3/1/0 -->

| F   | Task | CMP     | Evidence                                                | Screen           | Clause                    | Severity | Sentence                                                                                                                                                                                                                                                                                                                                            | Owner                                                                  |
| --- | ---- | ------- | ------------------------------------------------------- | ---------------- | ------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-1 | T10  | CMP-094 | `05`:64 · `KMAP`:615–618 · `D09`:395 · `D09`:417        | SCR-013          | 2.4.6                     | major    | `(heuristic)` A trader who knows the task as "flatten" finds no row by that word: the label is "Close all in view (confirm)", and `05`'s documented `Ctrl+Shift+F` is bound to nothing, so the key a reader learned from `05` does nothing at all (N2, N4) · "flatten" finds `positions.close_all`, or the flatten-all command is registered (AD-4) | E47-D09                                                                |
| F-2 | T10  | CMP-094 | `CHS`:101–111 · `D09`:233                               | SCR-013          | n/a (usability, `05`:15)  | major    | `(heuristic)` The sheet has no search at the sha: 85 rows in nine tables are read one table at a time, an operator ratio above 3 for a task the sighted user finishes at a glance (N7) · build the search the merged spec defines                                                                                                                   | engineering-only (E47-S08 #1322 builds the search `D09`:233 specifies) |
| F-3 | T9   | —       | `MODEL`:25 · `PW`:103 · `D07`:255 · `05`:185 · `05`:187 | SCR-117, SCR-030 | n/a (usability, `05`:187) | minor    | `(heuristic)` At the shipped default (`significant`) no caller flags an update significant, so a screen-reader user hears no ambient price at all: silence, not flooding, is the default's risk; minor, not major, because the mirror and `Alt+T` read the price on demand · name which ambient updates are significant (AD-3)                      | E47-D07                                                                |
| F-4 | T5   | CMP-108 | `05`:67 · `D06`:428                                     | SCR-050          | 3.3.4                     | major    | `(heuristic)` Reading the ladder, an SR user presses `Enter` on a row out of grid habit; three texts disagree on what `Enter` does there and one places a limit order, and the merged spec names no key until it is ruled, so T5 stays unsafe to script · rule one ladder `Enter` model; until then no order on plain `Enter` (AD-5)                | E47-D09                                                                |

### 3.1 Register findings the walk meets (cited by id, never re-minted; BQ-3)

| Register id         | Screen           | Task   | Severity | Owner            | What the walk meets `(heuristic)`                                                                                                                   |
| ------------------- | ---------------- | ------ | -------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| A11Y-F-0018         | SCR-116, SCR-117 | T9     | major    | E47-D05          | two settings links keep the default blue on the dark surface; a low-vision keyboard user changing a preference cannot see where the link is (1.4.3) |
| A11Y-F-0016         | SCR-117, SCR-123 | T8, T9 | minor    | E47-D05          | at 320 CSS px the rail stays expanded, so a 400 % zoom user scrolls in two dimensions on the settings and invite forms (1.4.10)                     |
| A11Y-F-0029         | SCR-123          | T8     | minor    | engineering-only | the invite page is reached only through the rail, one way (2.4.5)                                                                                   |
| A11Y-R-E12-D11-F-01 | SCR-030          | T3     | major    | E47-D07          | no merged text caps the cursor region and the panel region together, so T3's parity read cannot be scripted word for word                           |
| A11Y-R-E12-D11-F-05 | SCR-030          | T3     | major    | E47-D07          | four chart announcements have a politeness and a moment but no string                                                                               |
| A11Y-R-E08-D12-F-01 | SCR-100          | T1     | major    | E47-D03          | a disconnected or reconnecting watchlist row resolves to the live text colour; a low-vision user switching symbol cannot see which rows are stale   |

### 3.2 The counts (BQ-4; posted on #73 as "D01 heuristic rows")

D01 heuristic rows: blocker 0 · major 3 · minor 1 · info 0 · total 4; register findings cited 6, never re-minted. Tasks: completable 2, blocker 0, not built at the sha 8. They are posted on the E47 epic (#73) beside D02's open 4 / 26 / 64 / 12 (`CAT`:9), never as a second baseline; the register's own counts stay D02's.

### 3.3 The WCAG 2.2 AA screen (what decides a keyboard and SR trading UI)

Every AA criterion that decides the task surfaces has one line; "not assessable" and "not assessed" are listed, never implied clear. Status: **finding** (an F row) · **register** (a §3.1 id) · **no finding (heuristic)** · **not assessable at the sha** (the surface is not built) · **not assessed** (with the reason). The source is the merged cross-walk that meets the criterion (D04 §11, D09 §13) or the register.

| SC                                  | Task surfaces              | Source at the pin         | Status at the sha                                                                                        |
| ----------------------------------- | -------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------- |
| 1.4.1 Use of colour                 | T1 (SCR-100)               | `D04`:325                 | register: A11Y-R-E08-D12-F-01 (the register names no SC; the walk reads it under 1.4.1)                  |
| 1.4.3 Contrast (minimum)            | T9 (SCR-116, SCR-117)      | `REG` A11Y-F-0018         | register: A11Y-F-0018                                                                                    |
| 1.4.10 Reflow                       | T8, T9                     | `D04`:326                 | register: A11Y-F-0016                                                                                    |
| 2.1.1 Keyboard                      | T1–T10, SCR-081, SCR-082   | `D09`:275                 | no finding (heuristic) on T9 and T10; the other surfaces are not built at the sha (§2, G2)               |
| 2.1.2 No keyboard trap              | T10 (CMP-094)              | `D04`:328                 | no finding (heuristic): `Esc` closes the sheet and focus returns (`CHS`:30–31)                           |
| 2.4.3 Focus order                   | T2, T6, T7                 | `D04`:330                 | not assessable at the sha: SCR-060, the rule-engine flatten and SCR-074 are not built                    |
| 2.4.5 Multiple ways                 | T8 (SCR-123)               | `REG` A11Y-F-0029         | register: A11Y-F-0029                                                                                    |
| 2.4.6 Headings and labels           | T10 (SCR-013)              | `KMAP`:615–618            | finding: F-1                                                                                             |
| 2.4.7 Focus visible                 | T9, T10                    | `D04`:331                 | not assessed: a ring is judged on a rendered build (S1), not from code text; no finding is claimed       |
| 2.4.11 Focus not obscured (minimum) | T2, T5                     | `D04`:332                 | not assessable at the sha: SCR-060 and SCR-050 are not built                                             |
| 2.5.7 Dragging movements            | SCR-082                    | `D09`:285                 | not assessable at the sha: the editor route renders a stub (G2)                                          |
| 2.5.8 Target size (minimum)         | every pointer target       | `D09`:282                 | not assessed: a pointer criterion, outside a keyboard + SR walk                                          |
| 3.2.1 On focus, 3.2.2 On input      | T2, T3, T5                 | `D04`:333, `D04`:334      | not assessable at the sha: the order ticket, SCR-030 and SCR-050 are not built                           |
| 3.3.4 Error prevention              | T5 (SCR-050)               | `05`:67                   | finding: F-4                                                                                             |
| 3.3.8 Accessible authentication     | sign-in (TOTP), not a task | `E47J`:61 (the task list) | not assessed: sign-in is outside the ticket's task script; listed so it is not read as clear             |
| 4.1.2 Name, role, value             | T8, T10                    | `D04`:335                 | not assessable at the sha for T8 (SCR-121, SCR-122 not built); no finding (heuristic) on T10             |
| 4.1.3 Status messages               | T3, T6, T9                 | `D04`:336                 | register: A11Y-R-E12-D11-F-01, A11Y-R-E12-D11-F-05 (no SC in the register); T6 not assessable at the sha |

### 3.4 T2 applicability (the E09-D09 T2 standing gate; BQ-0)

No AD or TOP row specifies a control: AD-1, AD-2 and AD-3 set a preference default, a cadence and a taxonomy row, AD-4 a search word, AD-5 a key binding, AD-6 a register record and AD-7 a session rule; TOP-1 and TOP-2 restate AD-5 and AD-4. None gates a control on a view-as context, a permission, an account or environment leg or a registered state, so G-T2.1a to G-T2.6 bind no row of this memo; it draws no frame and writes no reason string. The gated controls the script meets are specified by their owning specs, and a session checks them as built on the sheet (§11.3):

| Task | A T2 control the session may meet                        | What the session checks                                                                                                                              |
| ---- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| T2   | an order-ticket control shown disabled with a reason     | G-T2.1b: it stays in the Tab order; G-T2.1c: the reason is spoken from its description; G-T2.3: `Enter` changes nothing and re-shows the reason once |
| T7   | the environment switch while the Live gate is off        | the same three                                                                                                                                       |
| T8   | an admin form control outside the signed-in role's scope | the same three; admin navigation is T3 hidden, outside the gate                                                                                      |

A miss is an F row routed to the control's owning spec, never a fix here.

## 4. Proxy walkthroughs (persona-coded proxies, not participants; BQ-8)

| W   | Proxy and goal                                                           | Path at the sha                                              | Where it breaks `(heuristic)`                                                              |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| W1  | X1 (P3 proxy), NVDA daily driver: "what is the flatten key?"             | `Ctrl+/`, then reads the sheet table by table in browse mode | no row says flatten (F-1); seven tables before Positions (F-2)                             |
| W2  | X1 (P3 proxy): switches to Live on the merged specs only                 | the environment switcher and its confirm, as specified       | not built at the sha; the badge text in the region name is `05`:150's, to verify           |
| W3  | X2 (M1 proxy), keyboard-only low-vision at 400 %: changes one preference | the settings route, then the accessibility screen            | the rail squeezes main (A11Y-F-0016); the default-blue links are hard to see (A11Y-F-0018) |
| W4  | X1 (P3 proxy): watches a fast market at the default verbosity            | the shipped default `significant`                            | hears no ambient price (F-3); the fills and rejects are heard (§5)                         |

## 5. Announcement flooding: quoted from E47-D07, and the cadence answer (AC3; BQ-6)

The counts are E47-D07's own (`D07`:257–265): its seeded fast script (BTCUSDT, seed 1306, `D07`:442) re-run in each setting by its merged tool, counted as field reads in the stream's minute. This memo quotes them and runs no simulator of its own (BQ-6 rider); this tool checks every quoted figure against D07's matrix at the pin (G-FLOOD).

| Setting                          | Field reads in D07's stream minute |
| -------------------------------- | ---------------------------------- |
| Off                              | 0                                  |
| On significant change            | 0                                  |
| Always · Low                     | 0                                  |
| Always · Normal                  | 22                                 |
| Always · High (= Normal)         | 22                                 |
| Always · Normal, whale prints on | 23                                 |
| Reduce announcements on          | 0                                  |

- **At the shipped default the count is 0** (`MODEL`:25; `PW`:103): the AC's premise, flooding at default verbosity, does not hold at the sha (F-3). Flooding needs "Always": 22 field reads in D07's minute at Always · Normal, spoken as 11 composites (`D07`:255).
- **The cadence answer to D05-G4 (`D05`:382) and D07-Q2 (`D07`:638): binary — the 2 s default and the 1 / 2 / 5 s options are not refuted; there is no measured value.** D07's replay spaces the composites 5.47 / 5.47 / 5.47 s apart at the three cadences (`D07`:639): the speech estimate, not the cadence, binds in the synthetic stream, so no new number is proposed (AD-2). A re-check row goes to E47-Q02 (#1355), which measures speech rates.
- **The 2-minute window** belongs to the observed-session protocol (§11.3), never to a synthetic figure beside D07's minute; the subjective rating stays open (OQ-1).

## 6. Public-practice scan (BQ-8; the E19-D01 BQ-12 form)

Public documentation only, a URL and a fetched date per row, else "unsourced observation"; no CandleViewer or exchange host is contacted, and no third-party screenshot is used. Each row rests on a page already fetched and cited in a merged text, with that text's fetched date (Deviation 5).

| Source (fetched date, citing text)                                                  | What it decides                                                                                              | URL                                                            |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| NVDA user guide, Browse Mode (2026-10-22, the E11-D07 reserved-keys file)           | the table quick key and browse-mode reading behind T10's count (§2)                                          | <https://download.nvaccess.org/documentation/userGuide.html>   |
| NVDA commands quick reference, Single Letter Navigation (2026-10-22, the same file) | the same count; the keys the protocol logs (S5)                                                              | <https://download.nvaccess.org/documentation/keyCommands.html> |
| WAI-ARIA APG grid pattern (2026-10-19, the E11-D01 research memo)                   | `Page Down` moves by "an author-determined number of rows": grid keys navigate, the reading habit behind F-4 | <https://www.w3.org/WAI/ARIA/apg/patterns/grid/>               |

## 7. Top 10 things that must change (deliverable 2; for E47-D02)

Ranked by the cost to a keyboard or screen-reader trader; each row has one owner. Pasted on #1300 at READY and linked from E47-D02 (#1301) at merge.

| TOP    | Must change                                                                                           | From                | Owner           |
| ------ | ----------------------------------------------------------------------------------------------------- | ------------------- | --------------- |
| TOP-1  | one ruled `Enter` on the ladder before SCR-050's keyboard path ships; until then no order on `Enter`  | F-4, AD-5           | E47-D09 (#1308) |
| TOP-2  | "flatten" finds `positions.close_all` in the sheet and the palette, or the flatten-all command exists | F-1, AD-4           | E47-D09 (#1308) |
| TOP-3  | build the cheatsheet search the merged spec defines                                                   | F-2                 | E47-S08 (#1322) |
| TOP-4  | mount SCR-045's table and SCR-030 so `Alt+T` and the parity task can run                              | T3, T4              | E47-S01 (#1316) |
| TOP-5  | write the four missing chart announcement strings                                                     | A11Y-R-E12-D11-F-05 | E47-D07 (#1306) |
| TOP-6  | name which ambient updates are significant, so the default is not silent                              | F-3, AD-3           | E47-D07 (#1306) |
| TOP-7  | settings link colour to AA on every theme                                                             | A11Y-F-0018         | E47-D05 (#1304) |
| TOP-8  | watchlist connection text distinct from primary text                                                  | A11Y-R-E08-D12-F-01 | E47-D03 (#1302) |
| TOP-9  | the rail collapses at 320 CSS px                                                                      | A11Y-F-0016         | E47-D05 (#1304) |
| TOP-10 | the owner runs §11 on the R4 build before the epic claims AA                                          | AC1, AC4            | owner           |

## 8. Adopted decisions AD-1..AD-7 (heuristic, PROPOSED)

Each stays PROPOSED; a reviewer marks it satisfied or violated from the named artefact alone.

| AD   | Decision (PROPOSED)                                                                                                                 | Violates if                                                                                                                        | From      | Owner                            |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | --------- | -------------------------------- |
| AD-1 | the shipped verbosity default stays "On significant change" (`MODEL`:25), as E47-D07 has it                                         | a SCR-117 frame or spec selects "Always" by default, or cites this memo for a flooding measure                                     | §5, F-3   | E47-D07 (#1306), E47-S07 (#1321) |
| AD-2 | the cadence stays 2 s by default with 1 / 2 / 5 s options; this memo supplies no measured value                                     | a spec cites E47-D01 for a cadence other than 2 s, or drops an option                                                              | §5        | E47-D05 (#1304)                  |
| AD-3 | before AD-1 is final, the taxonomy names which ambient updates are significant                                                      | E47-D07's taxonomy has no row naming a significant ambient update while the default is "On significant change"                     | F-3       | E47-D07 (#1306)                  |
| AD-4 | the word "flatten" finds `positions.close_all` in SCR-013's and SCR-012's search                                                    | typing "flatten" in either search returns no row while no flatten-all command exists                                               | F-1       | E47-D09 (#1308), E47-S08 (#1322) |
| AD-5 | no plain `Enter` places an order on a grid a reader reaches by arrows until one ladder model is ruled                               | a SCR-050 spec or frame binds plain `Enter` to an order placement before the ruling                                                | F-4       | E47-D09 (#1308)                  |
| AD-6 | a session blocker is a new F row of §3 with its keystroke sequence in the Sentence, absorbed through D02's one `reviews` entry (§9) | a D01 session blocker reaches the register without screen, clause, severity or keystrokes, or under a `D01-nn` or `A11Y-F-nnnn` id | AC4, BQ-4 | E47-D02 (#1301)                  |
| AD-7 | every order task in a session runs on Bybit demo with the Live gate off (C-2.11), checked on the sheet                              | a session sheet lacks the environment check before T2                                                                              | AC5       | owner                            |

## 9. D02's absorption AC: one `reviews` entry, nothing re-minted (BQ-3, BQ-4)

E47-D02's AC "Research findings are absorbed" (`E47J`:86) asks for every D01 blocker in the register with its evidence linked. This PR edits none of `47-audit-register.json`, `findings.json`, `47-routing.json` or `_tools/catalogue.py`: they are #1301's and #1323's, and the catalogue is generated (`CAT`:3); G-UNTOUCHED holds it. §3's table is in the review-table shape the catalogue parses, so D02's absorption is its own one-entry `reviews` addition naming this file after this memo merges: the register mints `A11Y-R-E47-D01-F-n`, and the Screen column attributes each row, so no routing attribution is needed. A task result that is already a register finding is cited by its id (§3.1) and never re-minted. **This memo has no blocker at the sha**; a blocker from the owner's sessions is added as a new F row with its keystroke sequence in the Sentence and enters through the same entry; one the auditors cannot reproduce is recorded as such with the reason (AD-6).

## 10. Downstream feeds

| Ticket          | Takes from this memo                                                                |
| --------------- | ----------------------------------------------------------------------------------- |
| E47-D02 (#1301) | §7 and §9: the top-10 and the one `reviews` entry (its AC)                          |
| E47-D05 (#1304) | §5's answer to D05-G4 and D05-Q1 (`D05`:390); AD-2; C6                              |
| E47-D07 (#1306) | §5's answer to D07-Q2; AD-1, AD-3; F-3; C6                                          |
| E47-D09 (#1308) | F-1, F-4; AD-4, AD-5                                                                |
| E47-S08 (#1322) | F-2; AD-4                                                                           |
| E47-S01 (#1316) | TOP-4                                                                               |
| E47-Q01 (#1314) | §2's task table and §11's scripts as expected-result inputs; C5                     |
| E47-Q02 (#1355) | §5's re-check row (the measured rates); §11's speech-viewer method                  |
| E47-X01 (#1326) | the surfaces of §2; the AT baseline of §11.5 and §11.6 under their stable names; C5 |
| E49-D01 (#1330) | §11 as a protocol method                                                            |

## 11. Owner session protocol (ready to run; nothing below has been run)

### 11.1 Participants, consent, data

Up to five sessions of 60 minutes: the owner (P1), up to two account managers (P2), and the two external assistive-technology participants the ticket names, recruited by the owner (OQ-4). Each participant chooses their own AT, verbosity and speech rate, gets a break every 20 minutes, and is briefed that this is a private internal tool under NDA. Capture follows `SRR`'s Capture procedure (`SRR`:32), cited here and not restated; nothing recorded in a session enters the repository. Storing recordings and consent forms per the research retention policy is an owner-leg line: the owner's restricted store (OQ-5). Every account, user and key identity a session touches is a seeded fixture one.

### 11.2 Rig and preconditions

| S   | Step                                                                                                                                                                                                             |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1  | AT-1's combination (§11.5): the R4 Electron production build, Windows 11 23H2, NVDA pinned per `SRR`'s changelog; default hotkey map, dark theme, default verbosity                                              |
| S2  | **Demo only** (C-2.11): the environment badge reads DEMO and the Live gate is off, checked and initialled on the sheet before any order task (AC5)                                                               |
| S3  | a second machine captures screen and audio for the moderator; CH-SPEECH-VIEWER and CH-AT-LOG are saved as text for the announcement count (§11.6)                                                                |
| S4  | **5-minute ceiling** per task, a moderator-side bound, never a participant-facing timer; breaks and moderator pauses are excluded from elapsed time; at the ceiling the task is a blocker with its keystroke log |
| S5  | **no coaching:** the moderator never names a key or a workaround before the failure is recorded; a keystroke logger runs throughout                                                                              |
| S6  | a mouse-using control run of the same script gives the time ratio; a ratio above 3 on a core trading task is a finding even if it completes                                                                      |
| S7  | a pilot with an internal tester first; pilot data is excluded                                                                                                                                                    |

### 11.3 Recording sheet

Session id · date · initials · persona or role · AT and version · speech rate · build sha · environment check (S2) · per task T1–T10: completion (yes / no / with help), elapsed seconds (breaks and moderator pauses excluded), mouse-control seconds, focus losses, "where am I?" count, the keystroke sequence on a failure · per T2 control met: in the Tab order, reason spoken, `Enter` re-shows it (§3.4) · from CH-SPEECH-VIEWER, the polite and assertive lines per minute over the protocol's 2-minute fast market at default verbosity, then at "Always" · the participant's 1–5 usability rating of each · any mirror announcement later than 200 ms after a focus move (a finding forwarded to E46, OQ-2) · verbatim quotes on flooding, kept in the owner's store.

Decision rules: a task no participant completes keyboard + SR only is a blocker (`05`:282) and becomes an F row per §9; a §3 row no session reproduces is demoted with a note; AD-1 changes only if both NVDA sessions rate the default unusable; three findings are spot-reproduced independently before publication.

### 11.4 Agenda (60 min)

| Minutes | Step                                                           |
| ------- | -------------------------------------------------------------- |
| 0–5     | consent, AT set-up, the environment check (S2)                 |
| 5–20    | T1, T3, T4                                                     |
| 20–22   | break                                                          |
| 22–40   | T2, T5, T6, T7                                                 |
| 40–42   | break                                                          |
| 42–52   | T8, T9, T10                                                    |
| 52–60   | the 2-minute fast market at two settings, the ratings, debrief |

### 11.5 AT baseline: the `05` §8.1 rows (stable names for E47-X01)

| AT   | `05` §8.1 row | Combination                            | In this protocol                                                               |
| ---- | ------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| AT-1 | #1, `05`:263  | NVDA on the Electron shell, Windows 11 | the rig (S1); no pass run, and an agent pass counts toward none (`05`:293–294) |
| AT-2 | #2, `05`:264  | JAWS on the Electron shell, Windows 11 | a participant's own choice only; its full pass is the Accessibility role's     |
| AT-3 | #3, `05`:265  | NVDA on Chromium, Windows 11           | not a production target; not run                                               |
| AT-4 | #4, `05`:266  | VoiceOver on the Electron shell, macOS | a participant's own choice only; its full pass is before GA                    |

### 11.6 AT output channels (stable names for E47-X01)

| CH               | Channel                                         | What a session keeps                                                      |
| ---------------- | ----------------------------------------------- | ------------------------------------------------------------------------- |
| CH-SPEECH        | what the screen reader speaks                   | heard live; the moderator notes lag and flooding                          |
| CH-BRAILLE       | the braille display's output                    | recorded only when a participant uses a display; otherwise "not observed" |
| CH-SPEECH-VIEWER | NVDA's speech viewer, saved as text             | the announcement count (§11.3)                                            |
| CH-AT-LOG        | the screen reader's log at Debug, saved as text | the timing check behind OQ-2                                              |

## 12. Owner walkthrough checklist (posted on #1300 before merge)

1. Confirm the proxies X1 (P3) and X2 (M1) stand in for the two external participants until you recruit them (OQ-4).
2. Confirm D01 verifies the merged D02..D13 set instead of shaping it (BQ-3, C4).
3. Approve or override AD-1: the default stays "On significant change"; D07's default count is zero (§5).
4. Approve or override AD-2: 2 s default, 1 / 2 / 5 s options, no measured value (§5, D05-G4).
5. Decide AD-4, "flatten" as a search word or a flatten-all command (F-1); try it: open the cheatsheet with `Ctrl+/` and find "Close all in view" with the keyboard (T10).
6. Decide with E47-D09 the ladder `Enter` model, and confirm AD-5 meanwhile (F-4).
7. Confirm the four D01 heuristic rows and the counts to post on #73 beside D02's 4 / 26 / 64 / 12 (§3.2).
8. Text-only or boards: the ruling waived the Penpot page for this memo (Deviation 6, `README`:44 and `README`:57); keep it text-only, or ask for research boards in a later push.
9. Name the restricted store for recordings and consent forms (OQ-5).
10. Comment `approved` on #1300, or leave rework notes citing F, AD, C, G or OQ ids.

## 13. Contradictions, gaps and open questions

### 13.1 Contradictions (none resolved silently)

| C   | Contradiction                                                                                                                                          | This memo's resolution (PROPOSED) · owner                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| C1  | `05`:185 describes a polite ambient region updated every 2 s by default vs the shipped default `significant`, which reads none (`MODEL`:25; `D07`:255) | AD-1 keeps the shipped default; A1 · E47-D07 (#1306)               |
| C2  | `05`:64 "Flatten all" on `Ctrl+Shift+F` vs no flatten-all command and `Ctrl+Shift+W` on close-all (`KMAP`:615–618; `D09`:395)                          | traced on close-all (T10); AD-4 · E47-D09 (#1308)                  |
| C3  | the ladder's `Enter`: `05`:67 places a limit; the merged texts disagree (`D06`:428)                                                                    | AD-5 meanwhile · E47-D09 (#1308)                                   |
| C4  | the ticket has D01 shaping D02..D09 (`E47J`:61) vs D02..D10 and D13 merged first (`D13`:7)                                                             | D01 verifies the merged set (BQ-3) · owner                         |
| C5  | E47-Q01 and E47-X01 list E47-D01 for themes, contrast and CVD (`E47J`:424, `E47J`:574) vs E47-D03 and E47-T03 owning them                              | this memo carries no contrast or CVD number; A3 · E47-Q01, E47-X01 |
| C6  | `D05`:50, `D05`:382, `D05`:390 and `D07`:638 cite the cadence as `05`:151; at the pin that line is the CVD gate and the cadence is `05`:185            | the pointer moves to `05`:185 · E47-D05 (#1304), E47-D07 (#1306)   |

### 13.2 Gaps (none invented; each routed)

| G   | Gap                                                                                                                                                                       | Owner           |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| G1  | no R4 build, no Live gate (E44) and no recruited external participant exist, so AC1 cannot start                                                                          | owner           |
| G2  | the rule editors SCR-081 and SCR-082 render a stub route at the sha (`TREE`:83); T6 and their keyboard and non-drag paths (2.1.1, 2.5.7; `D09`:175–178) wait on the build | E47-S03 (#1317) |

### 13.3 Open questions

| OQ   | Question                                                                                                                                | Owner |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| OQ-1 | the participants' subjective rating of the default and of "Always" (§11.3)                                                              | owner |
| OQ-2 | the time ratio against the mouse control, and whether a mirror announcement lags 200 ms (to E46)                                        | owner |
| OQ-3 | does any session overturn AD-1 or AD-2                                                                                                  | owner |
| OQ-4 | who recruits the two external AT participants; `10` names their needs (P3, `10`:164; M1, `10`:250) but no persona is an external expert | owner |
| OQ-5 | where the restricted store for recordings and consent forms is                                                                          | owner |

### 13.4 Proposed owner-document amendments (A rows; none edited here)

| A   | Owner text                                                         | Proposed amendment (PROPOSED)                                                                   | From     | Owner                       |
| --- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- | -------- | --------------------------- |
| A1  | `05`:185 reads as if ambient narration were on by default          | say that the default reads significant updates only, and the 2 s cadence applies under "Always" | C1, AD-1 | owner, with E47-D07 (#1306) |
| A2  | `05`:64 names a flatten-all command the registry does not have     | align the row with the registry, or register the command                                        | C2       | owner, with E47-D09 (#1308) |
| A3  | E47-Q01's and E47-X01's dependency lines cite E47-D01 for contrast | cite E47-D03 and E47-T03                                                                        | C5       | owner (the plan JSON)       |

## 14. Audit tool and its mutations

`docs/design/_tools/e47_d01_research_audit.py` imports `spec_audit_lib` from main and keeps only this memo's rows, in the house shape (inline `--check` and `--self-test`; `--repin` proposes where a pinned cite's words stand now). G-REVIEW loads the merged `catalogue.py` and parses §3 exactly as the register will. Every mutation trips exactly its own gate.

| M    | Gate        | Mutation                                              |
| ---- | ----------- | ----------------------------------------------------- |
| M-1  | G-AC        | a scenario name reworded                              |
| M-2  | G-BQ        | the BQ heading back to pending                        |
| M-3  | G-BQ        | a verdict that differs from the ruling                |
| M-4  | G-TASKS     | a task verdict outside the vocabulary                 |
| M-5  | G-TASKS     | a task without its T04 oracle                         |
| M-6  | G-ROWS      | a finding loses its heuristic label                   |
| M-7  | G-ROWS      | a finding with an unknown severity                    |
| M-8  | G-ROWS      | a finding without its SC                              |
| M-9  | G-ROWS      | a review row re-mints a register id                   |
| M-10 | G-KEYS      | a blocker without its keystrokes                      |
| M-11 | G-REVIEW    | the review table's Sentence column renamed            |
| M-12 | G-D02       | a register id that does not exist                     |
| M-13 | G-D02       | a cited severity differs from the register            |
| M-14 | G-ROUTE     | a review row routed outside the register's vocabulary |
| M-15 | G-COUNTS    | the baseline counts drift                             |
| M-16 | G-FLOOD     | a quoted D07 count edited by hand                     |
| M-17 | G-SCAN      | a scan row without its fetched date                   |
| M-18 | G-AT        | an AT output channel dropped                          |
| M-19 | G-SC        | an AA criterion drops off the screen                  |
| M-20 | G-T2        | the T2 applicability note is missing                  |
| M-21 | G-CITE      | a cite past the end of its document                   |
| M-22 | G-CHECKLIST | an eleventh checklist item                            |
| M-23 | G-NOCLOSE   | a closing keyword                                     |
| M-24 | G-PUBLIC    | a local path                                          |
| M-25 | G-PUBLIC    | a URL outside the public scan                         |
| M-26 | G-UNTOUCHED | the register edited by this PR                        |
| M-27 | G-MUTLIST   | the list drifts                                       |

## 15. References

`05` §1, §3, §6.2, §8 · `10` §2–§6 · `11` US-SET-007 · `14` SCR-012, SCR-013, SCR-030, SCR-045, SCR-050, SCR-060, SCR-063, SCR-074, SCR-081, SCR-082, SCR-100, SCR-102, SCR-116, SCR-117, SCR-121..SCR-123 · `15` CMP-086, CMP-094, CMP-108 · `CAT` §1 · `REG` · `D04`..`D13` · `SRR` and the E47-T04 scripts · issues #73, #1300, #1301, #1302, #1304, #1306, #1308, #1314, #1316, #1317, #1321, #1322, #1326, #1330, #1355
