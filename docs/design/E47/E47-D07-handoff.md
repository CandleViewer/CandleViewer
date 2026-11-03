# E47-D07 — Hand-off (`16` §11.4; live-region announcements)

Components: **ShellAnnouncer** (the shell pair, ANN:80–106), **CMP-212 ToastHost** and **CMP-045 Toast** (writers into the pair), **CMP-060 NotificationCenter** (the log), **CMP-077 ReconnectOverlay** and **CMP-117 RiskLockoutBanner** (writers), **CMP-065 FormSection**, **CMP-006 RadioGroup** and **CMP-004 Toggle** (the SCR-117 Announcements panel), **CMP-079 RbacGate** with the **CMP-019 Icon** `lock` glyph (the T2 safety row and view-as)

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                                                     | Evidence                                                             |
| -------------------------------------------------------- | -------------------------------------------------------------------- |
| Taxonomy: every user-surfaced event classified           | [x] spec §4; the CI check is D07-G5                                  |
| Copy: one exact template per announced event             | [x] spec §7.2, §7.3                                                  |
| Throttle model: cadence, latest value, bursts, verbosity | [x] spec §5, §6; the cadence default is D07-Q2                       |
| Region hygiene                                           | [x] spec §2; the CMP-212 build is D07-G4                             |
| Focus and persistence                                    | [x] spec §9; board 05 drawn (spec §0, §17)                           |
| Transcripts                                              | [x] the JSON and spec §10; [ ] QA acceptance pending (E47-Q01 #1314) |
| Variants × states (the panel)                            | [x] spec §8.3                                                        |
| Keyboard table (the panel)                               | [x] spec §8.3                                                        |
| Data contract                                            | [ ] NO: D07-G1, D07-G2, D07-G3, D07-G7, D07-G8, D07-G11              |
| Boards                                                   | [x] drawn: spec §0 (ids, PNGs, theme gates) and §17 (as built)       |
| NVDA and JAWS evidence                                   | [ ] the session protocol (§I), not run                               |
| Sign-off                                                 | [ ] owner approval pending (#2701)                                   |

## §B Who applies what

| A                       | Target                         | Applied by                                                |
| ----------------------- | ------------------------------ | --------------------------------------------------------- |
| D07-A1 … D07-A4         | `05` §6.2                      | E47-D11 (#1310), the hand-off pack (the DoD's `05` lines) |
| D07-A5, D07-A6, D07-A7  | `15` CMP-212, CMP-045, CMP-060 | E47-D10 (#1309), the CMP contribution                     |
| D07-A8, D07-A9, D07-A13 | `14` SCR-014, SCR-117          | the `14` owner, at the owner's sign-off PR                |
| D07-A10                 | `24` §2.9                      | E47-D11 (#1310), the hand-off pack (the DoD's `24` line)  |
| D07-A11                 | E09-D09 §3.1 (the keys)        | E09-D09's owner, as a registered state key                |
| D07-A12                 | `11` US-CHART                  | the `11` owner, at the owner's sign-off PR                |
| D07-A14                 | E40 LR-0 (LR)                  | E40's a11y review, with E40-S02 (#1130)                   |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `85b6b6c1c` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A       | Target        | Field (`file`:line)    | Old                                                                                                                                                       | New                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------- | ------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D07-A1  | `05` §6.2     | Assertive (`05`:152)   | order filled, order rejected, position auto-flattened by risk engine, rule triggered, WS disconnected/reconnected, Demo/Live environment switch confirmed | insert after: . The safety set is a separate fixed group, always assertive and never silenced by the user: kill switch engaged, risk lockout or cap hit, native stop-loss placement failure, trade-group unwind incomplete. Also assertive (PROPOSED): order partially filled, order status unknown, rule stopped after errors, trade group with failed legs, an order refused at its ticket (in the ticket's own `role="alert"`) and E17-D02's assertive connection rows (E47-D07 §3.2) |
| D07-A2  | `05` §6.2     | Polite (`05`:151)      | always presenting the _latest_ value rather than queuing every intermediate tick.                                                                         | insert after: The fields of the active symbol are written as one composite per cadence in a fixed order; discrete polite statuses keep at most one per 5 s per region (E47-D07 §6).                                                                                                                                                                                                                                                                                                      |
| D07-A3  | `05` §6.2     | Hygiene (`05`:154)     | so screen readers reliably pick up updates.                                                                                                               | insert after: The app shell owns the one pair; a per-message child inside the stable container is allowed; a local `role="alert"` region is kept only for the reply to the user's own action (E47-D07 §2).                                                                                                                                                                                                                                                                               |
| D07-A4  | `05` §6.2     | Panel (`05`:153)       | a master "reduce announcements" toggle                                                                                                                    | insert after: (placed in SCR-117, one fieldset per class, the safety class fixed assertive; its two keys land in E47-S07's own contract PR first; E47-D07 §8)                                                                                                                                                                                                                                                                                                                            |
| D07-A5  | `15` CMP-060  | A11y (`15`:692)        | list uses `role="log"`                                                                                                                                    | insert after: ; every assertive announcement also writes an entry (E47-D07 §9)                                                                                                                                                                                                                                                                                                                                                                                                           |
| D07-A6  | `15` CMP-212  | A11y (`15`:2762)       | one `aria-live="polite"` region for informational toasts and a **separate** `role="alert"` region for errors/rejections                                   | writes each toast's sentence into the app shell's one live-region pair (polite, or assertive for errors and rejections) and owns no region of its own (E47-D07 §2)                                                                                                                                                                                                                                                                                                                       |
| D07-A7  | `15` CMP-045  | A11y (`15`:533)        | its sentence is written once into CMP-212's polite region, or its assertive region for `tone="danger"`                                                    | its sentence is written once, through CMP-212, into the shell pair's polite region, or its assertive region for `tone="danger"` (E47-D07 §2)                                                                                                                                                                                                                                                                                                                                             |
| D07-A8  | `14` SCR-014  | A11y (`14`:406)        | announcements come from CMP-212's two regions                                                                                                             | announcements come from the shell's one pair, written by CMP-212 (E47-D07 §2)                                                                                                                                                                                                                                                                                                                                                                                                            |
| D07-A9  | `14` SCR-117  | Components (`14`:2478) | CMP-228 PreviewTile.                                                                                                                                      | insert after: The Announcements panel: CMP-065 FormSection per class with CMP-006 RadioGroup, CMP-004 Toggle (Reduce announcements), CMP-079 RbacGate with CMP-019 Icon `lock` (the T2 safety row; E47-D07 §8).                                                                                                                                                                                                                                                                          |
| D07-A10 | `24` §2.9     | Heading (`24`:436)     | Event catalogue summary                                                                                                                                   | insert after the table: every user-surfaced event and state of this document has exactly one announcement class in E47-D07 §4 (event → class); a new one is classified there before it ships                                                                                                                                                                                                                                                                                             |
| D07-A11 | E09-D09 §3.1  | Keys (D09E09:95)       | `rbac.view_as`                                                                                                                                            | insert a row after: `a11y.safety_fixed` · "Safety announcements are always read at once." · the SCR-117 safety class, a PROPOSED §3.1 key under G-T2.4 (E47-D07 §8.2)                                                                                                                                                                                                                                                                                                                    |
| D07-A12 | `11` US-CHART | NFR (`11`:1035)        | live-region announcements throttled to ≤2/s                                                                                                               | insert after: (the cursor echo: E06-D03 D5, E47-D07 §6.3)                                                                                                                                                                                                                                                                                                                                                                                                                                |
| D07-A13 | `14` SCR-014  | A11y (`14`:406)        | polite for user alerts, rule fires (E40-D01 RF-B) and system and recorder information                                                                     | polite for user alerts and system and recorder information; every rule fire assertive, as `05`:152 owns it (OQ-13 answered by the standard; E47-D07 §3.2)                                                                                                                                                                                                                                                                                                                                |
| D07-A14 | E40 LR-0      | Architecture (LR:27)   | and lives in CMP-212 ToastHost                                                                                                                            | and writes, through CMP-212 ToastHost, into the app shell's one live-region pair; CMP-212 owns no region of its own, as D07-A6 rewrites it (E47-D07 §2)                                                                                                                                                                                                                                                                                                                                  |

## §D Storybook story lists (each story per theme, `15`:41)

| Component                   | Stories                                                                                            |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| ShellAnnouncer              | Empty · PoliteComposite · AssertiveQueue (three ranks) · AssertiveDropsPendingAmbient · UnderModal |
| CMP-212 ToastHost           | the merged list + WritesIntoShellPair                                                              |
| CMP-060 NotificationCenter  | the merged list + AssertiveEntries                                                                 |
| SCR-117 Announcements panel | Default · Modified · ReduceOn · SafetyFixedT2 · ViewAsT2 · ForcedColours                           |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window unless named)

- [ ] Board 01: every event you know from trading is on the map, in one class; nothing silent that you would want spoken.
- [ ] Board 03: at 10 Hz the polite line speaks at most half the time and always shows the newest price; the speech share, not the 2 s cadence, sets its pace (D07-Q3).
- [ ] Board 04: the auto-flatten is spoken first, then the reject, then the disconnect; each has its log row, the auto-flatten its persistent toast.
- [ ] Board 05: the typed price stays in the ticket after a reject; the auto-flatten dialog returns focus where it was.
- [ ] Board 06: each class has Assertive / Polite / Off; the safety row shows the lock glyph and its reason and stays in the Tab order.
- [ ] Board 08: Off, significant and Low read no prices; Normal and High read the same; the tape is never read; whale prints only when switched on.
- [ ] Board 10: read W-1, W-3 and W-5 aloud; each is clear by ear on first hearing.
- [ ] §I: listen to the fast transcript for one minute at 100 % and at 60 % of your screen reader's default rate; note any line you could not follow.
- [ ] §I: listen to the incident transcript; note whether any line arrived too late to act on.
- [ ] Record `approved` on #1306, or the findings `(heuristic)` with board and frame names.

## §F Consumers and what each builds from

| Consumer        | Builds from                                                                                                    | Waits on                        |
| --------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| E47-D05 (#1304) | spec §8.1 class names, §10 transcripts (preview)                                                               | —                               |
| E47-D06 (#1305) | spec §4 (each surface's class), §6.1 (the joiner); hands over its range words (§7.4)                           | —                               |
| E10-S01 (#304)  | spec §2, §5, §7.3, §12                                                                                         | D07-G1, D07-G2, D07-G7, D07-G11 |
| E47-S01 (#1316) | spec §6                                                                                                        | D07-G8                          |
| E47-S07 (#1321) | spec §8: the two keys, in its own contract PR before any consumer                                              | D07-G3                          |
| E47-D08 (#1307) | spec §8.2 (`Ctrl+Shift+M` on a T2 control); hands over its reduced-motion words and its W-4, W-8 … W-10 (§7.4) | —                               |
| E47-D10 (#1309) | §C D07-A5, D07-A6, D07-A7; §D                                                                                  | D07-G4                          |
| E47-Q01 (#1314) | the transcripts, §G                                                                                            | D07-G6                          |
| E47-Q02 (#1355) | §I                                                                                                             | the boards                      |

## §G QA draft assertions (deterministic)

| QA   | Given / when                                                                 | Then (assert)                                                                                                                                                                                                                                                                                                                                                                       |
| ---- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| QA-1 | replay the fast script under Always · Normal with a fake clock               | the polite region's writes equal the transcript's polite lines, in time and text                                                                                                                                                                                                                                                                                                    |
| QA-2 | replay the fast script under Always · Low                                    | no polite write; the assertive writes equal the transcript's assertive lines                                                                                                                                                                                                                                                                                                        |
| QA-3 | replay the incident script                                                   | the dialog takes focus first and its focus speech carries W-40, W-5 and W-41; then the assertive region's writes are W-3, W-13 in that order, each once and in full; three CMP-060 entries; the auto-flatten's toast persistent                                                                                                                                                     |
| QA-4 | focus the ticket's price field, type "6400", inject a reject                 | `document.activeElement` and the field's value are unchanged; the ticket is open                                                                                                                                                                                                                                                                                                    |
| QA-5 | inject three partial fills of one order and its fill inside 1.6 s            | one partial line and one "Filled" line, as the quiet transcript                                                                                                                                                                                                                                                                                                                     |
| QA-6 | inject a reject with an unmapped code                                        | the line ends "Reason not recognised. See Notifications."; the upstream text is in no region                                                                                                                                                                                                                                                                                        |
| QA-7 | open SCR-117; Tab to the Risk and safety group; press `Space`, then `↓`      | every radio has `aria-disabled="true"`, the reason W-39 is its description, the value is unchanged, one polite announcement                                                                                                                                                                                                                                                         |
| QA-8 | mount and unmount ten panels; read the shell pair's containers               | the two containers are the same nodes before and after; no other `aria-live` container carries a taxonomy event                                                                                                                                                                                                                                                                     |
| QA-9 | replay the fast script (60 s at 10 Hz) under each of the seven §6.4 settings | the field reads inside the stream's minute equal §6.4's column (the steady state, 11<!--=SIM:fast.composites--> composites under Always · Normal); the one flush composite after the stream ends, at 61.271<!--=SIM:fast.flush-at--> s, is asserted apart; the assertive writes are identical in every setting; no composite starts inside twice the previous one's speech estimate |

## §H The board plan (drawn; spec §0 and §17)

The boards of spec §0, on page `E47-D07 announcements` of the Penpot file `E47-D07 boards`. Data: the seeded synthetic stream (seed 1306), declared synthetic on every board's face.

| Board | Frames                                                                                                         |
| ----- | -------------------------------------------------------------------------------------------------------------- |
| 01    | `taxonomy/map · dark`                                                                                          |
| 02    | `regions/shell-pair · dark`, `regions/local-reply · dark`                                                      |
| 03    | `timeline/polite-10hz · dark`                                                                                  |
| 04    | `timeline/incident · dark`                                                                                     |
| 05    | `focus/reject-kept · dark`, `focus/alertdialog · dark`                                                         |
| 06    | `SCR-117/announcements-default · dark`, `SCR-117/announcements-view-as · dark`                                 |
| 07    | `SCR-117/announcements-default · light`                                                                        |
| 08    | `matrix/verbosity · dark`                                                                                      |
| 09    | `preview/quiet · dark`, `preview/fast · dark`, `preview/incident · dark` (content for E47-D05's board-07 tile) |
| 10    | `copy/anatomy · dark`                                                                                          |

## §I Owner session protocol (NVDA and JAWS; not run)

Setup: Windows, NVDA and JAWS at their default rates and verbosity, the browser at 100 %, a seeded build replaying the transcripts with a fake clock (E47-Q01 #1314). Never a live account, never a recorded account capture.

1. Quiet script under Always · Normal: confirm the polite lines arrive as the transcript says and the partial fills read as one.
2. Fast script for one minute under Always · Normal, then Low: count the lines heard; compare with §10.2 and §6.4.
3. Incident script at 100 % and at 60 % of the default rate: note the order heard, whether any line was cut and how late the disconnect is heard; open the bell and confirm three entries.
4. Focus in the ticket's price field while the incident plays: confirm the typed value stays and the dialog returns focus.
5. SCR-117 panel: walk it by keyboard; confirm the safety row's reason is read and `Space` changes nothing.
6. Record per screen reader: lines heard, lines missed, lines late, and a usable / not usable verdict in the owner's words (T Test); label every finding `(heuristic)` unless measured.

## §J Summary for #1306

1. Text-first spec of the live-region layer over the shipped announcer and ambient writer; every difference a G-row; 10<!--=COUNT:boards--> boards drawn (spec §0, §17); default-deny audit tool.
2. A taxonomy of 55<!--=COUNT:taxonomy--> events in five classes, each with its source, topic, surface, panel class and words; silent rows say where to read the value.
3. An assertive queue by rank, never throttled, merged or cut; bursts of one entity collapse, distinct events never merge.
4. Ambient fields as one composite per cadence, latest value, never appended; the tape never narrated, whale prints opt-in, Normal = High until the owner splits them.
5. Closed words: grammar, slots and a reason map from `24`; no secret is ever spoken; account-scoped.
6. Three transcripts replayed by the tool as the QA oracle and E47-D05's preview content.
7. BQ-0 … BQ-16 RULED (comment 6570054100): BQ-2, BQ-7, BQ-8, BQ-9 overridden, the rest accepted; E47-D05 and its upstream, E47-D06 (PR #5443) and E47-D08's handed words re-pinned from their PR heads to their merge commits; `Refs #1306` + `Partial:` while both blockers (#1304, #1305) are open, then `Closes`, the closing keyword for this ticket.
