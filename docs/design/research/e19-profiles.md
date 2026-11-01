# E19-D01 — UX research: how traders read value, POC and profile period modes

- **Ticket:** E19-D01 (issue #382, P1, Sprint 05; parent E19; area order-flow) · **Status:** Draft, design approval pending — this memo PR carries `Refs #382` + `Partial:` (its protocol §10 and its audit tool included); the nine research boards of §0 are PENDING and are drawn in the research-boards PR, which carries `Closes #382` (ruling of record, #382 comment 6563817073) · **Design approval pending** (the ticket's agent-delivery adaptations, owner decision 2026-09-25) · **Method:** heuristic evaluation (Nielsen N1–N10 and `05` §4 colour independence and §6 table alternatives) + a persona walkthrough (P1 Owner, P2 Account Manager, P3 Viewer) + a public-documentation competitive review + worked numbers from the audit tool; **no session was run — no participant, timing, score or quote exists**; every finding is `(heuristic)` and every decision is **PROPOSED**; the orchestrator's design approval of this PR adopts them as interim rulings under the owner's 2026-10-29 delegation, each reversible by the owner in one line, and the owner's sessions (§10) can overturn them.
- **Scope:** SCR-038 (profile panel and chart overlay) and SCR-039 (settings dialog): the default period mode and the mode switcher, the labelled-vs-implied ranking of the derived levels, developing vs final value area, the "approximated from bars" and partial-history honesty states, greyscale and row density, and the session protocol the owner runs later. **Out of scope (ticket):** visual design, colour and tokens (E19-D02 / D03), footprint cells (E18), the CVD pane (E23), recorder administration and retention (E16), recruiting anyone beyond the Owner and the account managers.
- **Inputs pinned:** `main` `ca49e693ae45`; every `file :line` below is read at that commit. **Key:** `NN` = `docs/plan/NN-*.md` (`22` = `docs/plan/22-api-openapi.yaml`); `README` = `docs/design/README.md`; `E16-D05` = `docs/design/E16/E16-D05.md`; `E18-D02` = `docs/design/E18/E18-D02.md`; `digest-01` / `digest-04` = `docs/research/digests/01-tradingview-charting.digest.md` / `04-deepcharts-deepchart.digest.md`; "tool" = `docs/design/_tools/e19_d01_profiles_audit.py`. Text in curly quotes is verbatim from a source its line cites (the tool checks it); text in straight quotes is this memo's PROPOSED copy or a vendor's page.
- **Ids:** **F** finding (Blocker / Major / Minor / Nit) · **PD** proposed decision, testable by E19-D02 · **C** contradiction between sources · **G** contract or definition gap, routed to its owning ticket (never a field invented here) · **A** amendment proposal against a plan document · **OQ** open question with an owner · **T** protocol task.

## Acceptance-criteria trace (issue #382)

Status key: **done** = delivered as worded · **heuristic-only** = delivered by the adaptation, pending the owner's sessions · **open** = needs sessions or an owner decision.

| Ticket AC or deliverable                                                                                                                     | Where                                                                               | Status                                                                                                         |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| AC 1 — POC, VAH, VAL, value-area shading, HVN, LVN, naked POC and single prints each carry a label, a prominence and a traceable observation | §5 (ten rows: the eight + developing state + initial balance), each tied to an F-id | heuristic-only (the observations are heuristic; sessions open)                                                 |
| AC 2 — developing vs final distinguished unaided, and the treatment that made it reliable recommended                                        | §6.3, PD-1; protocol T2, T4, T8                                                     | **open** (needs sessions); the treatment PROPOSED                                                              |
| AC 3 — an approximated profile's misread recorded verbatim and driving a raised `EstimatedBadge` prominence                                  | §6.4, PD-4; protocol T9                                                             | **open** (no misread exists to record); PD-4 raises the prominence ahead of it                                 |
| AC 4 — a finding that contradicts SCR-038 / SCR-039 or `24` §5 raised as a written amendment proposal                                        | §9.1 C-rows, §9.3 A-rows                                                            | done (A-rows PROPOSED; no plan text edited)                                                                    |
| AC 5 — the greyscale condition: which levels became unreadable, binding on E19-D03                                                           | §4.4 (computed), F-13, PD-3                                                         | heuristic-only (computed, not observed); the binding is stated                                                 |
| DoD — report merged with at least 6 adopted, testable decisions                                                                              | §7 PD-1..PD-8                                                                       | design approval pending (the orchestrator's design approval = adoption as interim rulings; owner reversible)   |
| DoD — default period mode and the labelled-vs-implied ranking agreed with the Architect                                                      | §6.2, §5                                                                            | design approval pending (Architect → the orchestrator's interim ruling; owner reversible)                      |
| DoD — findings presented at Design Review; decisions carried into E19-D02                                                                    | §10.6 walkthrough; §11 traceability                                                 | heuristic-only (the walkthrough replaces Design Review)                                                        |
| DoD — every contradiction raised as a documented amendment proposal                                                                          | §9                                                                                  | done                                                                                                           |
| DoD — CDO sign-off recorded; Status Done                                                                                                     | the owner's `approved` comment or merge                                             | design approval pending; the research-boards PR (`Closes #382`) completes #382                                 |
| Scope — 3 moderated sessions, two-coder reconciliation, the "most useful rows" number                                                        | §10                                                                                 | **open** (owner's sessions)                                                                                    |
| Scope — competitive scan (TradingView, Sierra Chart / DeepCharts, the Owner's own tool)                                                      | §8                                                                                  | heuristic-only (Sierra Chart sourced; TradingView and DeepCharts not established; the Owner's tool OQ-1, open) |
| Accessibility notes — a screen-reader session on the table alternative; the compact-density legibility probe                                 | §10.4 sessions 2 and 3                                                              | **open** (owner's sessions)                                                                                    |
| Observability — whether the observed switching justifies all three events                                                                    | §6.7, F-22                                                                          | **open** (the session tally)                                                                                   |

## 0. Research boards (Penpot) — PENDING

Mandatory on every design ticket, research included (`README` :44–:57). PENDING: drawn in the research-boards PR, which carries `Closes #382`, in the Penpot file `E19-D01 boards` on the page `E19-D01` (cited by page name + page id only, never a host or file URL), greyscale, no light twins, exported to `docs/design/research/img/E19-D01-NN-<slug>.png`. Nine boards <!-- audit:boards=9 -->, under the cap of ten:

| #   | Board                                     | Content                                                                                               | State   |
| --- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------- |
| 01  | `E19-D01 / 01 questions-hypotheses`       | §2 research questions and hypotheses, all untested                                                    | PENDING |
| 02  | `E19-D01 / 02 competitive-teardown`       | §8 as greyscale schematics redrawn from public text; no vendor screenshot                             | PENDING |
| 03  | `E19-D01 / 03 period-mode-map`            | §6.1: the four source vocabularies onto the five user-facing modes and the `24` kinds                 | PENDING |
| 04  | `E19-D01 / 04 derived-level-ladder`       | §5: labelled vs implied, each level's non-colour cue, in greyscale                                    | PENDING |
| 05  | `E19-D01 / 05 developing-vs-final`        | §6.3, PD-1: the header words and the open-ended bracket beside the final state                        | PENDING |
| 06  | `E19-D01 / 06 approximated-partial-strip` | §6.4–§6.5, PD-4, PD-5: the header status slot with CMP-011 and CMP-227, the hatched approximated rows | PENDING |
| 07  | `E19-D01 / 07 density-row-legibility`     | §4.3, PD-8: the row ladder at compact and dense, labels on named levels only                          | PENDING |
| 08  | `E19-D01 / 08 decisions`                  | §7 PD-1..PD-8 with each check                                                                         | PENDING |
| 09  | `E19-D01 / 09 protocol-table-alternative` | §10 the session plan and the table-alternative columns of A-6                                         | PENDING |

## 1. Brief questions (BQ list, issue #382 comment 6563727875)

Status: **RULED (comment 6563817073)**. The orchestrator's ruling of record (#382 comment 6563817073, on the BQ list comment 6563727875) rules every ORCH-default as proposed, BQ-0 through BQ-15: every finding stays `(heuristic)`, every decision stays PROPOSED and the orchestrator's design approval of this PR adopts them as interim rulings under the owner's 2026-10-29 delegation, each reversible by the owner in one line; every proposed `12` / `13` / `14` / `24` amendment is an A-row in this memo, never an edit to the owner document. The tool pins the ruling (G-BQ), the untouched plan documents (G-UNTOUCHED) and the base as a 12-character short sha with no 40-hex string in the memo (G-PIN).

- **BQ-0 — standing rules.** Ruled as proposed: this path; branch `design/e19-profiles-research`; heuristic evaluation + persona walkthrough + competitive review; nothing invented; every finding `(heuristic)`, every decision PROPOSED; the brief's `apps/web` paths and pnpm commands do not apply (one Deviation line, §2); the ticket's "line 77" is `14` :83 at the pinned base.
- **BQ-1 — done and the closing keyword.** Ruled as proposed: the ticket is not text-only (`README` :54–:57); this memo PR carries `Refs #382` and "Partial: research boards pending (≤ 10)", no closing keyword in any commit; the research-boards PR carries `Closes #382` (the `README` boards rule holds for research tickets too); AC 2, AC 3, the sessions, the two-coder reconciliation and the useful-rows number stay open.
- **BQ-2 — protocol and harness.** Ruled as proposed: §10 in full (probes verbatim, a pass criterion per task, rotation, recording sheet, "two coders agree → adopted"); the harness specified, not built; the two rehearsal fixtures named as protocol inputs, never invented; recordings as the ticket cites ADR-0015, with the retention owner to confirm (§10.1).
- **BQ-3 — the 6–10 decisions.** Ruled as proposed: PD-1..PD-8 (§7), each with a PASS / FAIL check E19-D02 runs, its evidence and its target; PROPOSED; the orchestrator's design approval of this PR adopts them as interim rulings under the owner's 2026-10-29 delegation, each reversible by the owner in one line; the walkthrough (§10.6) replaces Design Review.
- **BQ-4 — the period vocabulary.** Ruled as proposed: the ticket's five modes, each mapped to a `24` kind (§6.1); `bar` and `rolling` not user-facing; `anchored` an amendment on `24` §5.1 owned by E19-C01 (A-1); A-rows for `14` :1010 and CMP-183 (A-2, A-3).
- **BQ-5 — default mode and switcher.** Ruled as proposed: Session (UTC day) for the docked panel, Visible range for the chart overlay, both PROPOSED; a menu in the header; the radio group in SCR-039; `14`'s ASCII default an A-row (A-4).
- **BQ-6 — the level set and ranking.** Ruled as proposed: §5, ten rows; "labelled in text": POC, VAH, VAL and the developing state; naked POC labelled at its ray end; implied by glyph + legend: HVN, LVN, single prints, value-area shading; the POC / VA cue reuses E18-D02 D6.
- **BQ-7 — developing vs final.** Ruled as proposed: the words "Developing · as of HH:MM UTC" / "Final" + an open-ended value-area bracket, never dashed or hatched (§6.3, PD-1); G-1, G-2 to E19-T02 / T03; AC 2 open.
- **BQ-8 — approximated from bars.** Ruled as proposed: one treatment, CMP-227 with a PROPOSED detector `bar_approximation`, visible word "(estimated)", methodology "approximated from bars", raised to `section` grade in the header; `pattern.hatch.estimated` on the approximated rows; delta and TPO absent over that portion; G-3; A-5 (§6.4, PD-4).
- **BQ-9 — partial history.** Ruled as proposed: E16-D05's ruled chip verbatim; this memo decides prominence only (header status slot, left of CMP-227, ≥ 4 px apart); a composite states its covered range in the legend; the stale `14` wording stays E16-D05's A-row (§6.5, PD-5).
- **BQ-10 — contradictions.** Ruled as proposed: §9.1 C-1..C-3 and §9.3 A-rows, each with its owning document and ticket; the tie-break tooltip cites `24`'s chain pending the owner; no plan document edited; the `14` SCR-038 pointer to this memo is A-8, not an edit.
- **BQ-11 — greyscale and density.** Ruled as proposed: computed with `cvd_sim.py`'s maths and `contrast_check.py`'s formula over the profile tokens (§4.4), binding on E19-D03 (PD-3); densities compact and dense evaluated, comfortable noted (§6.6); the useful-rows number open; the 5 000-row budget untouched.
- **BQ-12 — competitive scan.** Ruled as proposed: public documentation only, URL + fetched date per row, else "unsourced observation"; TradingView, Sierra Chart and DeepCharts; POC / VAH / VAL labelling and the developing treatment only; no screenshot; the Owner's own tool is a protocol question (§8).
- **BQ-13 — traceability and analytics.** Ruled as proposed: §11 maps each PD to its ticket; the three `14` events kept PROPOSED with a protocol tally; no new event.
- **BQ-14 — the audit tool.** Ruled as proposed: the tool named above, stdlib, `python3 -I`, `--json` / `--check` / `--self-test`; ruled pins: G-BQ requires the ruling comment 6563817073 and no pending line, G-UNTOUCHED no plan-document edit.
- **BQ-15 — the board plan.** Ruled as proposed: §0, nine greyscale boards, no light twins.

## 2. Method note (agent-delivery adaptation, owner decision 2026-09-25)

The ticket's three moderated sessions are replaced by (1) a **heuristic evaluation** of the plan texts and contracts (Nielsen N1–N10; `05` §4's colour-independence rule and §6's table alternatives), (2) a **persona walkthrough** — P1 the Owner scaling out at a naked POC (`10` :99), P2 the Account Manager (`10` :106), P3 the Viewer who most likely uses a screen reader (`10` :164) — (3) a **competitive review** of public documentation (§8), (4) **worked numbers** from the audit tool over the recorded fixtures and the token JSON (§4), and (5) a **written protocol** the owner can run (§10). Honest limits: the fixtures are documented-shape files, not market evidence; the contrast and CVD numbers are computed, not observed; every reading prediction is a heuristic.

**Research questions and hypotheses (all untested).** RQ1 which period mode a trader reaches for first (H1: the session for a docked panel, the visible range for an overlay); RQ2 segmented control or menu (H2: a menu, since five words do not fit a compact header); RQ3 which levels must carry words (H3: POC, VAH, VAL and the developing state); RQ4 whether a developing value area is read as settled without words (H4: yes, it is misread); RQ5 how loudly "approximated" must speak (H5: a header badge plus a row pattern; a chip alone is missed); RQ6 which levels vanish in greyscale (H6: every fill-only distinction).

**Deviations (recorded, not hidden).** (1) The sessions, the two-coder reconciliation and the useful-rows number are replaced as above; AC 2, AC 3 stay open. (2) The brief's `apps/web` repo paths and pnpm commands do not apply to a research text; the gates run are the design-PR gates. (3) The prototype harness is specified in §10.2, not built (the E22-D01 precedent).

## 3. Heuristic evaluation

Severity: Blocker (would cause a wrong trade) · Major · Minor · Nit. Findings <!-- audit:findings=22 -->:

| F    | Label       | Heuristic | Finding                                                                                                                                                                                                                            | Evidence                                               | Severity |
| ---- | ----------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------- |
| F-1  | (heuristic) | N1        | The model knows whether a profile is still developing, but neither contract carries it: a client cannot say "Developing" from REST or WS data, so a developing value area is drawn exactly like a final one                        | `24` :1002; `22` :20296–20312; `23` :3140–3174         | Blocker  |
| F-2  | (heuristic) | N1        | The developing value-area "ribbon" is promised but only the POC path is stored, so the client has no developing VAH / VAL history to draw from (and E19-D05 may not require client-kept history)                                   | `24` :1000, :1017                                      | Major    |
| F-3  | (heuristic) | N4        | Dashed, hollow and hatched marks are reserved for estimated or absent data; a dashed "developing" value area would be read as estimated — E18-D02 forbids the same for the forming bar                                             | `15` :2927; `E18-D02` :157                             | Major    |
| F-4  | (heuristic) | N4, N10   | "approximated from bars" has no `EstimatedBadge` detector and is missing from `14`'s "(estimated)" rule list, though a bar-approximation member already has a precedent (`vwap_bar_approx`)                                        | `14` :82, :1009; `15` :2924–2925                       | Major    |
| F-5  | (heuristic) | N1        | No contract field says which period or which rows were bar-approximated: `DataMeta.sources` names tiers for the whole response, so the client cannot hatch the approximated rows                                                   | `22` :18562–18569, :20287–20295                        | Blocker  |
| F-6  | (heuristic) | N1, N2    | An approximated POC depends on an allocation rule the trader cannot see: on the same 450 bars two rules move the POC by two rows (§4.1); delta cannot be derived from bars at all (tool `bars`: a kline carries no aggressor side) | tool `bars`; `11` :1705–1707 (bar-approximated volume) | Major    |
| F-7  | (heuristic) | N4, N2    | Four sources name the period modes four ways (ticket five modes; `14` five other words; CMP-183 four; `24` six kinds; `22` three splits), so wireframes would invent a sixth vocabulary                                            | `14` :1010; `15` :2370; `24` :968; `22` :4855–4857     | Major    |
| F-8  | (heuristic) | N2        | US-VP-002 asks for a profile anchored at a bar that "can be extended indefinitely", but `24` has no anchored kind                                                                                                                  | `11` :1725–1727; `24` :968                             | Major    |
| F-9  | (heuristic) | N4        | Three different defaults: the SCR-038 sketch opens on Visible range, the Must story is the UTC-day session, `22` defaults to a composite split with a UTC-day anchor                                                               | `14` :996; `11` :1694, :1700; `22` :4857, :4861        | Major    |
| F-10 | (heuristic) | N8        | Five mode words do not fit a segmented control in a 24 px compact header beside input, VA % and row size; the dialog already specifies a radio group                                                                               | `16` :129; `14` :996–997, :1025                        | Minor    |
| F-11 | (heuristic) | N4        | CMP-110 can flag only POC and value area, so HVN, LVN, naked POC, single prints and the initial balance have no carrier and would be invented per screen                                                                           | `15` :1287–1288; `24` :997–999                         | Major    |
| F-12 | (heuristic) | N2        | Single prints have no stored field; derivable as rows whose `tpo_count` is 1, and a rule signal already derives them within `n` ticks, while vendors define singles more narrowly (§8), so the span is ambiguous                   | `24` :982, :1255; `11` :1839                           | Minor    |
| F-13 | (heuristic) | `05` §4   | In greyscale no pair of the three profile fills reaches 3:1 in any theme (§4.4): fill alone cannot tell the POC row, a value-area row and a row outside it apart — AC 5's answer, binding on E19-D03                               | tool `colour`; `16` :191, :197                         | Blocker  |
| F-14 | (heuristic) | N1        | Levels are sparse: a missing row means no trade, a row with delta 0 means balance; in the trade fixture 40 of 55 rows in the span are untraded (§4.2), so the two cases are common and must look different                         | `24` :990; `11` :1820–1821; tool `ticks`               | Minor    |
| F-15 | (heuristic) | N4        | The partial-history wording in SCR-038 is stale against E16-D05's ruled chip                                                                                                                                                       | `14` :1011; `E16-D05` :246                             | Minor    |
| F-16 | (heuristic) | N2        | The POC tie-break the tooltip must state differs between the story and the model, so either tooltip text would contradict a source                                                                                                 | `11` :1764–1766; `24` :1007                            | Major    |
| F-17 | (heuristic) | N5        | The value-area percentage range differs across sources (1–100, 50–95, presets 68 / 80)                                                                                                                                             | `14` :1022; `22` :4874; `24` :1009                     | Minor    |
| F-18 | (heuristic) | `05` §6   | The profile table alternative lacks TPO count, HVN / LVN, naked POC, single print, developing and estimated columns, so P3 cannot read what the canvas shows                                                                       | `05` :171–179; `10` :164; `14` :1012                   | Major    |
| F-19 | (heuristic) | N8        | At one-tick rows a 7.5 h BTCUSDT range is 2 251 rows, under 0.3 px each in a 640 px pane; rows merge (×8 to ×15) and per-row text is impossible, so only named levels can carry words (§4.3)                                       | tool `density`; `26` :238; `05` :208                   | Minor    |
| F-20 | (heuristic) | N1        | A composite short of coverage must state its covered range, but the only coverage carrier (`coverage_holes`) is described for the kline cache                                                                                      | `11` :1745–1747; `22` :18572–18578                     | Minor    |
| F-21 | (heuristic) | N7        | Naked POCs carry forward with a clutter limit and a hidden count; an unlabelled ray is indistinguishable from a drawing or the current POC                                                                                         | `11` :1797, :1803; `24` :1013; `22` :20305–20309       | Minor    |
| F-22 | (heuristic) | —         | The three analytics events cannot show whether switching justifies all three without sessions                                                                                                                                      | `14` :1016                                             | Nit      |

## 4. Worked numbers

Tool output (`python3 -I docs/design/_tools/e19_d01_profiles_audit.py --json`) at the pinned base. The fixtures are documented-shape files (`packages/fixtures/bybit/2026-10-05`), not live captures; the kline pages and the trade frames cover different windows, so **no tick-vs-bar accuracy comparison is possible** (G-5).

### 4.1 A bar-approximated profile (kline fixture, 450 one-minute bars, 62 784.0–63 009.0, rows of 10 ticks)

| Allocation rule (both plausible; neither specified)             | Rows | POC      | VAL      | VAH      |
| --------------------------------------------------------------- | ---- | -------- | -------- | -------- |
| uniform: each bar's volume spread evenly over [low, high]       | 226  | 62 974.0 | 62 859.0 | 63 009.0 |
| OHLC4: a quarter of each bar's volume at open, high, low, close | 216  | 62 972.0 | 62 859.0 | 63 008.0 |

The POC moves 2.00 USDT (two rows) with the rule alone; delta is not derivable (a kline carries no aggressor side). Both use `24`'s POC chain and `22`'s single-step value area (`24` :1007; `22` :4841–4843). Feeds F-6 and PD-4.

### 4.2 A tick profile (trade fixture, 46 prints, one-tick rows)

15 traded rows across a 55-row span: 40 rows inside the span have no trade, and no traded row has a delta of exactly 0. Feeds F-14 and PD-8.

### 4.3 Row density (the kline range, 2 251 one-tick rows; pane heights 320 / 480 / 640 px are examples, not sourced)

| Row size (ticks) | Rows  | px per row (320 / 480 / 640) | Merge factor to reach 2 px | Every row labelled at the 10 px floor? |
| ---------------- | ----- | ---------------------------- | -------------------------- | -------------------------------------- |
| 1                | 2 251 | 0.14 / 0.21 / 0.28           | 15 / 10 / 8                | no                                     |
| 10               | 226   | 1.42 / 2.12 / 2.83           | 2 / 1 / 1                  | no                                     |
| 25               | 91    | 3.52 / 5.27 / 7.03           | 1                          | no                                     |
| 50               | 46    | 6.96 / 10.43 / 13.91         | 1                          | 480 and 640 only                       |

At the 10 px floor a pane holds at most 32 / 48 / 64 labelled rows; the table alternative shows 13 / 20 / 26 rows at compact (24 px) and 10 / 15 / 20 at comfortable (32 px). The merge rule is `26` :238; the 10 px floor is the only frozen canvas-text floor (`05` :208, footprint), borrowed here. Feeds F-19 and PD-8.

### 4.4 The profile tokens under greyscale and deuteranopia (WCAG ratio; bar 3:1, WCAG 1.4.11)

`color.profile.poc`, `color.profile.valuearea` and `color.profile.bar` (CMP-110, `15` :1289) against each other, rendered with `cvd_sim.py`'s Rec. 601 luma and Machado 2009 matrix, measured with `contrast_check.py`'s formula. High-contrast resolves to the dark values (no override).

| Pair                                     | Dark: normal / greyscale / deuteranopia | Light: normal / greyscale / deuteranopia |
| ---------------------------------------- | --------------------------------------- | ---------------------------------------- |
| POC vs value area                        | 1.63 / 1.66 / 1.90                      | 1.95 / 2.09 / 2.27                       |
| value area vs outside it                 | 1.71 / 1.54 / 1.58                      | 1.57 / 1.82 / 1.69                       |
| POC vs outside the value area            | 2.79 / 2.57 / 3.01                      | 1.25 / 1.15 / 1.34                       |
| outside-VA bar vs `color.surface.raised` | 2.86 / 2.85 / 2.82                      | 3.74 / 3.79 / 3.82                       |

**AC 5's answer (computed, binding on E19-D03):** in greyscale each of the three fill-vs-fill pairs is below 3:1 in both themes, so a POC row, a value-area row and a row outside the value area cannot be told apart by fill; in light greyscale the POC row nearly vanishes against the outside-VA rows (1.15). The outside-VA bar also misses 3:1 on the raised surface in dark. WCAG 1.4.11 is applied here to adjacent fills because the fill is today the only carrier of the level; the Blocker is the missing non-colour carrier, not a breach by the tokens alone. Feeds F-13 and PD-3.

## 5. Derived levels — label, cue and rank (AC 1)

Rank: **1 labelled** = word and price at rest, every density · **2 labelled** = word at its anchor, on screen · **3 implied** = glyph + legend entry, the word on hover, focus, the DOM mirror and the table. No cue uses fill colour alone, and none uses dashed, hollow or hatched marks (reserved, F-3). The POC and VA cues reuse E18-D02 D6 (`E18-D02` :156) and its mirror words “point of control”, “value area high”, “value area low” (`E18-D02` :307–308) so per-bar and session profiles read alike. Levels <!-- audit:levels=10 -->:

| Level              | Label (text)                                                  | Non-colour cue                                                                                                 | Rank       | Prominence                           | Finding          |
| ------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------ | ---------------- |
| POC                | "POC 62,974.0" at the row's end; mirror "point of control"    | a full-width solid rail on the row's top and bottom edges + bold price (E18-D02 D6)                            | 1 labelled | always, every density                | F-11, F-13, F-16 |
| VAH                | "VAH" + price                                                 | a solid tick at the value-area edge + the bracket's end                                                        | 1 labelled | always                               | F-11, F-13       |
| VAL                | "VAL" + price                                                 | a solid tick at the value-area edge + the bracket's end                                                        | 1 labelled | always                               | F-11, F-13       |
| Value-area shading | legend "Value area 70 %"                                      | a solid bracket from VAL to VAH beside the histogram; the tint only reinforces                                 | 3 implied  | the bracket always; the legend entry | F-13, F-17       |
| HVN                | legend "HVN"; mirror "high-volume node"                       | a solid right-pointing notch glyph at the row's end                                                            | 3 implied  | when node marking is on              | F-11             |
| LVN                | legend "LVN"; mirror "low-volume node"                        | a solid left-pointing notch glyph, distinct in shape from HVN's                                                | 3 implied  | when node marking is on              | F-11             |
| Naked POC          | "nPOC" + the session date at the ray's end                    | a solid thin horizontal ray from its session; tested ones demoted to the history toggle with the word "tested" | 2 labelled | the nearest N + "N hidden"           | F-21             |
| Single prints      | legend "Single prints"                                        | a solid bar glyph in the TPO letter margin (US-VP-008's glyph)                                                 | 3 implied  | TPO mode, toggleable                 | F-12             |
| Developing state   | "Developing · as of 14:30 UTC" / "Final" in header and legend | an open-ended value-area bracket (no end cap) while developing                                                 | 1 labelled | always while `complete` is false     | F-1, F-2, F-3    |
| Initial balance    | "IB" + its range                                              | a solid vertical bar left of the TPO letters (CMP-184's shading reinforces only)                               | 2 labelled | TPO mode                             | F-11             |

The non-colour cue column states a constraint class (solid, shape-distinct, never fill-only, never dashed, hollow or hatched); the glyph shapes named are examples, and E19-D03 chooses the glyphs (PD-3 tests the class, not the shape).

**The labelled-vs-implied ranking (the ticket's deliverable):** must be labelled in text — POC, VAH, VAL, the developing state; labelled at their anchor — naked POC, initial balance; may be implied by glyph + legend — value-area shading, HVN, LVN, single prints.

## 6. Period modes and the honesty states

### 6.1 The user-facing vocabulary (BQ-4)

| User-facing mode (PROPOSED word) | `24` `ProfilePeriod.kind` (`24` :968) | `22` request (`22` :4855–4868)           | `14` :1010 word    | CMP-183 `periodType` (`15` :2370) |
| -------------------------------- | ------------------------------------- | ---------------------------------------- | ------------------ | --------------------------------- |
| Session                          | `session`                             | `split=session` + `session_anchor`       | Session multiples  | `multiples`                       |
| Fixed range                      | `fixed_range`                         | `split=fixed` + `fixed_duration_minutes` | Personalised range | `personalized`                    |
| Visible range                    | `visible_range`                       | `from` / `to` of the viewport            | Visible range      | `visible`                         |
| Anchored                         | none — A-1 (E19-C01)                  | none                                     | Swing-anchored     | none                              |
| Composite                        | `composite`                           | `split=composite`                        | Composite          | `composite`                       |

`bar` belongs to E18's per-bar profile and `rolling` to the VWAP family; neither is user-facing here (a recorded decision for E19-D02's one-to-one rule). "Multiples" is a Session option ("one per session, side by side", US-VP-003), not a sixth mode.

### 6.2 Default mode and switcher (BQ-5; RQ1, RQ2)

PROPOSED both ways, for the owner: the docked panel opens on **Session** (the UTC day; US-VP-001 is the Must mode and the day is `22`'s default anchor, `11` :1694, :1700; `22` :4861), the chart overlay on **Visible range** (it follows the viewport the trader is already reading). The header switcher is a **menu button** showing the current mode word (F-10); SCR-039 keeps its radio group (`14` :1025). The sketch's "Visible range" default (`14` :996) becomes A-4.

### 6.3 Developing vs final (BQ-7; AC 2)

While `complete` is false (`24` :1002) the header and legend read "Developing · as of HH:MM UTC" and the value-area bracket is drawn open at its developing edge; at close the words become "Final" and the bracket closes. Never dashed, hollow or hatched (F-3), never opacity or motion alone (E19-D05 owns the transition). The contracts must carry `complete` and the developing bounds first (G-1, G-2). AC 2 stays open: only sessions can show whether the words are noticed unaided (protocol T2, T4 and T8).

### 6.4 "Approximated from bars" (BQ-8; AC 3)

One treatment for the state `14` :1009 names: CMP-227 with a PROPOSED detector `bar_approximation` (a sibling of the `vwap_bar_approx` precedent, `15` :2925), visible word "(estimated)", methodology section "approximated from bars", raised from a chip to the `section` grade after the panel title — the histogram cannot be read without it in view (E19-D03's own rule). At series level the approximated rows carry `pattern.hatch.estimated` (`16` :194–195); delta and TPO over that portion are drawn as absent with the words "Delta not available before 09:00 UTC" (PROPOSED copy), never estimated (§4.1: bars carry no side). The data contract needs a per-period, per-portion flag (G-3); the rule lists in `14` §0.5 and CMP-227 need the member (A-5). AC 3 stays open: no misread exists to quote; the protocol records one verbatim (T9).

### 6.5 Partial history and short composites (BQ-9)

E16-D05's ruling is reused verbatim — CMP-011 `info`, “Partial: {n} of {m} requested days recorded” (`E16-D05` :246) — with no hatch on profile rows (`E16-D05` :285) and the approximated chip kept a separate state (`E16-D05` :286). This memo decides prominence only: the chip sits in the header status slot, left of CMP-227, at least 4 px apart, each with its own accessible name. A composite built from fewer sessions than requested states its covered range in the legend, as US-VP-003 requires (`11` :1745–1747), from G-4's carrier. `14` :1011's stale words stay E16-D05's A-row.

### 6.6 Greyscale and density (BQ-11; AC 5)

Computed in §4.4 and stated binding on E19-D03 (PD-3). Densities evaluated: `compact` (the chart default, `16` :129) and the chart-only `dense` (`16` :146); `comfortable` noted for the table alternative only. The 5 000-row budget (`14` :1013) is untouched; the number of rows traders find useful stays open (protocol T10).

### 6.7 Analytics (BQ-13)

The three events of `14` :1016 stay PROPOSED; the protocol's recording sheet tallies mode switches per session so the owner can judge whether `profile.period_changed` and `profile.mode_changed` both earn their place. No new event.

## 7. Proposed decisions PD-1..PD-8 (testable by E19-D02 wireframes)

Each is one sentence a greyscale wireframe satisfies or violates; the orchestrator's design approval of this PR adopts them as interim rulings under the owner's 2026-10-29 delegation, each reversible by the owner in one line. Decisions <!-- audit:decisions=8 -->:

| PD   | Decision                                                                               | Check E19-D02 runs                                                                                                                                                                                                                                                                                                                                                                                                       | Evidence         | Target                    | Status   |
| ---- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------- | ------------------------- | -------- |
| PD-1 | A developing profile says so in words, a final one says "Final"                        | PASS if the header and the legend show "Developing · as of HH:MM UTC" in every frame where `complete` is false, and "Final" otherwise; FAIL if the distinction rests on line style, opacity, colour or motion alone, or uses a dashed, hollow or hatched mark                                                                                                                                                            | F-1, F-2, F-3    | E19-D02, E19-D05, E19-S04 | PROPOSED |
| PD-2 | POC, VAH and VAL carry their word and price at rest                                    | PASS if every frame showing a profile labels POC, VAH and VAL with word and price without hover, at compact and dense; FAIL if any of the three is conveyed by fill or line colour alone or only on hover                                                                                                                                                                                                                | F-11, F-13, F-16 | E19-D02, E19-D03          | PROPOSED |
| PD-3 | Every level survives greyscale without fill                                            | PASS if, in the greyscale export, the POC row, the value-area rows and the rows outside the value area are each told apart by a rail, bracket, tick or glyph; FAIL if any pair relies on fill lightness (all measured below 3:1 in §4.4)                                                                                                                                                                                 | F-13             | E19-D03, E19-D06          | PROPOSED |
| PD-4 | An approximated profile cannot be read without its badge                               | PASS if, whenever any part is bar-approximated, the header carries CMP-227 at `section` grade reading "(estimated)" with the methodology "approximated from bars", the approximated rows carry `pattern.hatch.estimated`, and delta and TPO over that portion are shown as absent with words; FAIL if the badge can scroll or collapse out of view while the histogram shows, or delta or TPO is drawn over that portion | F-4, F-5, F-6    | E19-D03, E19-S01, E19-C01 | PROPOSED |
| PD-5 | Partial history uses E16-D05's chip, placed beside the badge                           | PASS if the partial chip is CMP-011 `info` with E16-D05's ruled words in the header status slot, left of CMP-227 with at least 4 px between them, and a short composite states its covered range in the legend; FAIL if the wording differs, the two merge into one chip, or the covered range is missing                                                                                                                | F-15, F-20       | E19-D02, E19-S03          | PROPOSED |
| PD-6 | Five user-facing modes, each mapped to one kind                                        | PASS if the switcher offers exactly Session, Fixed range, Visible range, Anchored and Composite, each annotated with its `ProfilePeriod.kind` (Anchored with A-1), and `bar` and `rolling` are not offered; FAIL if a sixth mode or another name (Personalised, Swing-anchored, Multiples) appears without a recorded decision                                                                                           | F-7, F-8         | E19-D02, E19-D04          | PROPOSED |
| PD-7 | Session is the docked default, Visible range the overlay default, switched from a menu | PASS if the docked panel opens on Session (UTC day), the chart overlay on Visible range, the header switcher is a menu button showing the current mode's word, and SCR-039 uses a radio group; FAIL if a default differs without an owner ruling, or the switcher is a segmented control that truncates a word at compact                                                                                                | F-9, F-10        | E19-D02                   | PROPOSED |
| PD-8 | Words go on named levels, never on every row; untraded and balanced rows differ        | PASS if at every density only named levels carry price text, rows merge per `26`'s rule when under 2 px, the row size is in the legend, and a zero-delta row differs from an untraded row by a mark; FAIL if row text appears below the 10 px floor (a PROPOSED floor borrowed from the footprint, `05` :208; E19-D02 may tighten it) or an untraded row and a zero-delta row look the same                              | F-14, F-19       | E19-D02, E19-D06          | PROPOSED |

## 8. Competitive review

Public documentation only; patterns described in words, no vendor screenshot or asset committed (board 02 redraws them as schematics). Vendor words are in straight quotes. Rows <!-- audit:competitive_rows=6 -->:

| Vendor / surface                                   | POC / VAH / VAL labelling                                                                                                                                                                   | Developing value area                                                                                                                                                                             | Source (vendor words as read on the fetched date)                                                                    |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Sierra Chart — TPO Profile Chart                   | "The TPO Point of Control (POC) is displayed as highlighted letters or blocks"; the value area likewise; both extendable as lines, one option "Until Future Intersection" (a naked-POC ray) | not a visual state of the chart itself                                                                                                                                                            | https://www.sierrachart.com/index.php?page=doc/StudiesReference/TimePriceOpportunityCharts.html — fetched 2026-11-01 |
| Sierra Chart — TPO Value Area Lines study          | lines for VAH, VAL and POC per period                                                                                                                                                       | an input, "Draw Developing Value Area Lines": with Yes, the lines at each bar show the value area "from the beginning of the time period up until that bar"; no word on the chart says developing | https://www.sierrachart.com/index.php?page=doc/StudiesReference.php&ID=158 — fetched 2026-11-01                      |
| Sierra Chart — initial balance                     | "displayed as a vertical line to the left of the TPO Letters/Blocks"                                                                                                                        | —                                                                                                                                                                                                 | https://www.sierrachart.com/index.php?page=doc/StudiesReference/TimePriceOpportunityCharts.html — fetched 2026-11-01 |
| TradingView — Fixed Range / Session Volume Profile | Fixed Range: “manual range, POC/VAH/VAL” (`digest-01` :46); Session Volume Profile: “per-session auto”, levels not itemised (`digest-01` :47)                                               | not documented in the digest                                                                                                                                                                      | unsourced observation (the public help page was not fetched; the digest is secondary)                                |
| TradingView — TPO                                  | entitlement tiers only (`digest-01` :8)                                                                                                                                                     | not documented in the digest                                                                                                                                                                      | unsourced observation                                                                                                |
| DeepCharts — Deep Profile                          | "Volume POC, Value Area (~70%)" plotted; periods "Composite, Multiples, Visible, Personalized" (`digest-04` :33, :36)                                                                       | not itemised; naked POC an open question (`digest-04` :38)                                                                                                                                        | unsourced observation (not fetched)                                                                                  |

**Reading (heuristic):** in the one documented tool (Sierra Chart) the developing value area is a study input, not a labelled state on the chart, and the POC and value area are marked by highlighted letters or blocks rather than words. Whether TradingView or DeepCharts distinguish a developing value area at all is **not established** (their rows are unsourced). PD-1 and PD-2 rest on F-1..F-3 and F-11, not on this review. CMP-183's four period words match DeepCharts' list (`15` :2370), possibly the origin of F-7's fourth vocabulary (heuristic). The tool the Owner already uses is asked in the protocol (T0), not guessed.

## 9. Amendments, contract gaps and open questions

No plan document is edited by this PR: per the ruling of record (comment 6563817073) every proposed `12` / `13` / `14` / `24` change, the SCR-038 pointer line included, is an A-row below.

### 9.1 Contradictions (none resolved silently)

| C   | Contradiction                                                                                                   | Sources                            | This memo's resolution (PROPOSED)                                                                                   | Owner            |
| --- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------- |
| C-1 | POC tie-break: the story's “closest to the range midpoint” vs the model's VWAP → last price → lower ticks chain | `11` :1766; `24` :1007             | the tooltip copy cites `24`'s chain (shared with E18 per `24` §4.5) pending the owner; E19-C01 records the decision | owner, E19-C01   |
| C-2 | Value-area percentage: 1–100 in SCR-039, 50–95 in `22`, default 70 with presets 68 / 80 in `24`                 | `14` :1022; `22` :4874; `24` :1009 | SCR-039 validates 50–95 (the contract wins), presets 68 / 70 / 80                                                   | E19-C01, E19-T02 |
| C-3 | Default period: Visible range in the SCR-038 sketch, session in the Must story, composite split in `22`         | `14` :996; `11` :1694; `22` :4857  | §6.2                                                                                                                | owner, E19-D02   |

### 9.2 Contract and definition gaps (contract first; no field invented)

| G   | Gap                                                                                                                                                                                             | Evidence                                 | Route                     |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ------------------------- |
| G-1 | `24`'s `complete` is not carried by `ProfilePeriod` in `22` nor by `ProfileUpdate` in `23`                                                                                                      | `24` :1002; `22` :20296; `23` :3140      | E19-T02, E19-T03          |
| G-2 | No developing VAH / VAL path; only `developing_poc` is stored and not carried                                                                                                                   | `24` :1000, :1017                        | E19-T02, E19-T03, E19-S04 |
| G-3 | No per-period or per-row flag for bar-approximated volume; `DataMeta.sources` is per response                                                                                                   | `22` :18562–18569                        | E19-T02, E19-S01, E19-C01 |
| G-4 | No carrier for "covered N of M sessions" on a composite profile                                                                                                                                 | `11` :1745–1747; `22` :18572–18578       | E19-T02, E19-S03          |
| G-5 | No matched tick + kline fixture pair over one window, and no POC-tie, short-composite, developing / closed, bar-approximated or TPO-levels (HVN, LVN, naked POC, single prints) profile fixture | `packages/fixtures/bybit/2026-10-05`; §4 | E19-Q02                   |
| G-6 | No single-print or initial-balance field; single prints derivable from `tpo_count`, and the rule signal `profile_single_print_present` exists, but no TPO-count rule fixes the span             | `24` :982, :1255; `11` :1837–1839        | E19-C01, E19-S08          |

### 9.3 Amendment proposals (AC 4; text proposals only)

| A   | Against                                          | Proposal                                                                                                                                                                                                          | Owner            |
| --- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| A-1 | `24` §5.1 `ProfilePeriod.kind`                   | add an anchored, open-ended period (a new kind, or `fixed_range` with an open end) for US-VP-002's anchored profile                                                                                               | E19-C01          |
| A-2 | `14` SCR-038 Settings (:1010)                    | the five mode words of §6.1; "Session multiples" becomes a Session option                                                                                                                                         | E19-D02          |
| A-3 | CMP-183 `periodType` (`15` :2370)                | one value per user-facing mode, mapped to `24`'s kinds; a developing / final prop driven by `complete`                                                                                                            | E19-D03          |
| A-4 | `14` SCR-038 sketch (:996)                       | the docked default "Session" (§6.2)                                                                                                                                                                               | E19-D02          |
| A-5 | `14` §0.5 (:82) and CMP-227 (`15` :2924)         | add bar approximation to the "(estimated)" rule list and a `bar_approximation` detector with its methodology entry                                                                                                | E25-D05, E19-D03 |
| A-6 | `05` profile table (:171–179)                    | add TPO count, node (HVN / LVN), naked POC, single print, developing / final and estimated columns, following `24` `ProfileLevel`                                                                                 | E19-D06          |
| A-7 | CMP-110 props (`15` :1287); CMP-184 (`15` :2377) | level flags beyond `isPoc` / `isValueArea` (HVN, LVN, naked POC, single print, initial balance), each with a non-colour cue; on CMP-184 a solid initial-balance bar beside its shading and the single-print glyph | E19-D03          |
| A-8 | `14` SCR-038 (:1017)                             | add one pointer line under SCR-038 naming this memo as its UX research, changing no requirement                                                                                                                   | E19-D02          |

### 9.4 Open questions

| OQ   | Question                                                                                                | Owner            |
| ---- | ------------------------------------------------------------------------------------------------------- | ---------------- |
| OQ-1 | Which profile or market-profile tool does the Owner already use, and how does it show developing value? | owner            |
| OQ-2 | Is TPO over a bar-approximated portion absent (BQ-8 default) or derivable from one-minute bar ranges?   | E19-C01          |
| OQ-3 | The tie-break the tooltip states (C-1)                                                                  | owner            |
| OQ-4 | The useful-rows number, the input to SCR-038's 5 000-row budget                                         | owner (sessions) |
| OQ-5 | Does "Developing · as of HH:MM UTC" update per developing interval (60 s default) or per recompute?     | E19-D05          |
| OQ-6 | Who builds the session harness of §10.2 (no ticket owns it)?                                            | owner            |

## 10. Owner session protocol

Ready to run once the entry criteria of §10.2 hold; nothing below has been run.

### 10.1 Participants, consent and data

The Owner plus up to two account managers (ticket scope), 45 minutes each. The moderator is never the participant: for the Owner's session a second person moderates, or an agent reads the script while a person takes notes. Before any recording starts the moderator reads, verbatim: "We record the screen and audio of this session for internal design use only. Nothing is published. You can stop at any time, or ask us to delete the recording, without giving a reason. The prototype shows market data only, never your accounts. Is that all right?" For the screen-reader participant the same text is given beforehand as plain text they can read with their own screen reader, and consent is spoken on the recording. Notes carry initials only; any account identifier that appears on a recording is redacted before storage. Recordings are stored in the design drive, never in the repo, with the design drive's standard retention (ticket Security notes); the ticket cites ADR-0015, which governs market-data recording, not recordings of people, so the retention named here is this memo's PROPOSED rule — delete when E19 closes — **owner to confirm**. Market fixtures only — no account identifier, balance, position or key in the harness.

### 10.2 The prototype harness and the entry criteria (specified, not built)

A dev-only greyscale page rendering `VolumeProfile` fixtures (`24` §5.1) as a docked SCR-038 and an overlay, at compact and dense, with a table alternative; never promoted to production. The stimuli are **documented-shape, synthetic profiles**, not live market data: the moderator says so to each participant, and the recording sheet records it; the developing / final, approximated and covered-range states are carried by the fixtures as harness flags, not contract fields (G-1, G-3, G-4 stay open).

Entry criteria — the sessions do not start until all hold:

1. The harness is built; no ticket owns it today, so who builds it is an owner decision (OQ-6).
2. The named fixtures exist (G-5, E19-Q02; none exists today): a BTCUSDT session with a POC tie (US-VP-004); a composite whose coverage is shorter than requested (US-VP-003); a session with a bar-approximated portion; one developing and one closed session side by side; a TPO session showing HVN, LVN, a naked POC and single prints.
3. Both switcher variants (menu button and segmented control) are wired, for T3.
4. A screen reader is available for session 2 and the table alternative is reachable by keyboard.

### 10.3 Tasks (a pass criterion per task; order rotated per §10.4)

Budgets and thresholds are `(heuristic)` planning values, not a benchmark or a measurement. Setup and consent take 3 minutes and the debrief 2; the tasks below total 38; a session totals 43 minutes. A task that overruns its budget is cut, never extended. A session running late drops T7, then T6, then T10 (marked "not run" on the sheet); T1, T8, T9 and T11 are never dropped (RQ1, AC 2, AC 3, AC 5).

| T   | Task                                                                                                                                                                             | Budget | Pass criterion                                                                                                            |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------- |
| T0  | Warm-up: which profile tool do you use today, and for what?                                                                                                                      | 2 min  | answer recorded (OQ-1)                                                                                                    |
| T1  | Before any profile is shown: "You open a docked profile for today, and then one for a swing you are studying: which period would you start with, and why?"                       | 3 min  | the period named and the reason recorded verbatim (RQ1, H1)                                                               |
| T2  | Find the session POC (a developing session; think aloud, no prompt about its state)                                                                                              | 2 min  | names the POC price within 10 s, no hover; any unprompted remark on the developing state recorded (AC 2 "volunteered")    |
| T3  | Switch to visible-range mode and pan, once with the menu button and once with a segmented control (order alternated)                                                             | 3 min  | finds each switcher without help; time to find each; says the profile follows the view (RQ2, H2)                          |
| T4  | Compare two sessions via a composite (one developing, one closed; the composite short of coverage)                                                                               | 4 min  | states both value areas and the covered range; any unprompted remark on developing vs closed or the partial chip recorded |
| T5  | On the TPO-levels fixture, legend hidden: "Point to and name the levels you would trade around"; then the probe "which of these price levels would you put an order at and why?" | 4 min  | which levels are named without the legend, and their words, recorded (RQ3, H3; §5 ranking)                                |
| T6  | Identify where sellers dominated using the delta profile                                                                                                                         | 3 min  | names a price band and its sign without colour                                                                            |
| T7  | Read the TPO initial balance                                                                                                                                                     | 2 min  | states the IB range                                                                                                       |
| T8  | The probe "is this value area finished?", for both side-by-side profiles (always after T2 and T4)                                                                                | 3 min  | correct for both; scored "volunteered" if already said in T2 or T4, else "answered when asked" (AC 2, RQ4)                |
| T9  | The approximated session: any unprompted remark first, then "How was this profile produced?" and the probe "what does this badge mean?"                                          | 4 min  | says it is estimated or built from bars; any misread written verbatim (AC 3, RQ5)                                         |
| T10 | The probe "what is the smallest row size that still tells you something?" on the row-size control                                                                                | 3 min  | a row size and a row count recorded (OQ-4)                                                                                |
| T11 | Greyscale condition (always last): repeat T2, T6 and T8                                                                                                                          | 5 min  | every level still named; failures listed by level (AC 5, RQ6)                                                             |

The four probes are verbatim from the ticket, each bound to its task above (T5, T8, T9, T10).

| RQ / decision                | Task       | Outcome that rewrites the decision                                                                                                    |
| ---------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| RQ1, PD-7 defaults           | T1         | 2 of 3 participants name another period first → PD-7's default is rewritten                                                           |
| RQ2, PD-7 switcher           | T3         | 2 of 3 find the segmented control faster with no word truncated → the switcher is rewritten                                           |
| RQ3, PD-2 and the §5 ranking | T5         | a rank-3 level misnamed by 2 of 3 even with the legend → promoted to labelled; a rank-1 level missed by 2 of 3 → its cue is rewritten |
| RQ4, PD-1                    | T2, T4, T8 | 2 of 3 wrong at T8 → PD-1's treatment is rewritten; AC 2 stays open until a treatment passes                                          |
| RQ5, PD-4                    | T9         | any participant reads the approximated profile as tick data → PD-4's prominence is raised again; the misread is quoted (AC 3)         |
| PD-5                         | T4         | the covered range missed by 2 of 3 → PD-5's placement is rewritten                                                                    |
| PD-6                         | T1, T3     | a mode word misread by 2 of 3 → that word is rewritten                                                                                |
| RQ6, PD-3                    | T11        | any level not named in greyscale → its cue is rewritten (binding on E19-D03)                                                          |
| PD-8, OQ-4                   | T10        | the recorded row size and count feed PD-8's floor and SCR-038's 5 000-row budget                                                      |
| §6.7 analytics               | every task | the mode-switch tally                                                                                                                 |

### 10.4 Rotation, density and assistive technology

T0 and T1 open every session (T1 must precede any profile); T11 always closes it. T2–T10 rotate:

| Session | Order of T2–T10                     | Density | Condition                                                                                   |
| ------- | ----------------------------------- | ------- | ------------------------------------------------------------------------------------------- |
| 1       | T2, T3, T4, T5, T6, T7, T8, T9, T10 | compact | then T11                                                                                    |
| 2       | T4, T2, T6, T3, T5, T9, T8, T10     | dense   | then T11; a screen reader on the table alternative for T2 and T8 (+3 min), so T7 is not run |
| 3       | T6, T4, T2, T9, T3, T10, T5, T8, T7 | compact | then T11; asked at T10 whether row labels stay legible at the smallest row                  |

The composite task (T4) never directly follows the session task (T2); T8 always follows T2 and T4; greyscale is always last. **Validity limits:** three sessions cannot counterbalance nine tasks — this is a rotation, not a Latin square, and the T2 / T4 order rule is the only ordering constraint met; density is confounded with participant (sessions 1 and 3 compact, session 2 dense), so no density effect can be separated from a person.

### 10.5 Recording sheet and decision rule

Per session: date, initials, persona, density, input (mouse / screen reader), "stimuli: synthetic documented-shape fixtures". Per task: success / partial / fail, time to answer, help given, the verbatim words of any misread, "volunteered" or "answered when asked" (T8), any task cut or not run, and the count of mode switches (for §6.7). Two coders code the transcripts independently and reconcile; an interim ruling becomes final only when both coders agree and the owner approves. A PD whose check the sessions contradict is rewritten by the rule in §10.3's table, not dropped silently.

### 10.6 Owner walkthrough checklist (posted on #382)

1. Approve or amend the default modes of §6.2 (PD-7).
2. Approve the labelled-vs-implied ranking of §5.
3. Rule the POC tie-break the tooltip states (C-1, OQ-3).
4. Confirm the developing / final words of PD-1.
5. Confirm PD-4's prominence for approximated profiles and the detector name.
6. Confirm the five user-facing modes and the anchored amendment (PD-6, A-1).
7. Answer OQ-1 (the tool you already use).
8. Accept G-1..G-6 as routed.
9. Decide who builds the harness (OQ-6) and whether to run the sessions of §10 before E19-D02 starts or after.
10. Review the nine boards in the research-boards PR (`Closes #382`).

## 11. Traceability

| Decision or item | Feeds                                                                               |
| ---------------- | ----------------------------------------------------------------------------------- |
| PD-1             | E19-D02 (states), E19-D05 (developing → final: no meaning by motion alone), E19-S04 |
| PD-2, PD-3       | E19-D02 (checks), E19-D03 (the greyscale finding is binding; level cues), E19-D06   |
| PD-4             | E19-D03, E19-S01 (badge), E19-C01 (what bars can and cannot give)                   |
| PD-5             | E19-D02, E19-S03 (covered range)                                                    |
| PD-6, PD-7       | E19-D02 (vocabulary, defaults), E19-D04 (the anchored flow)                         |
| PD-8             | E19-D02 (density cases), E19-D06 (table columns, A-6)                               |
| G-1..G-4, G-6    | E19-T02, E19-T03, E19-C01, E19-S03, E19-S08                                         |
| A-1..A-8         | E19-C01, E19-D02, E19-D03, E19-D06, E25-D05                                         |
| §6.7 analytics   | E19-S01, E19-S04 (event lists), the owner's session tally                           |

## 12. References

`11` §9 VP (US-VP-001..009); `14` SCR-038, SCR-039, §0.5; `15` CMP-110, CMP-183, CMP-184, CMP-227; `24` §5; `22` `/market/profile`, `ProfilePeriod`, `DataMeta`; `23` §14.6; `16` §3, §6; `05` §4, §6; `26` LOD; `10` P1–P3; `E16-D05` §6; `E18-D02` D6–D7; `README`; the research digests 01 and 04; ADR-0015; `docs/design/_tools/cvd_sim.py`, `contrast_check.py`; the exemplars `e22-tape-reading.md`, `e37-node-graph-vs-list.md`, `e40-alert-attention.md`.
