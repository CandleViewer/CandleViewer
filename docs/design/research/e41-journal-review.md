# E41-D01 — UX research: how the owner reviews a closed trade, and what counts as evidence

- **Ticket:** E41-D01 (issue #1017, P1, Sprint 16; parent E41) · **Status:** In Review — text-first (protocol v0, not piloted): this memo, the session protocol (`e41-d01-session-protocol.md`), the `17` §1.6 journey and the audit tool; this text PR says `Refs #1017` + `Partial:` and does not close the ticket; the SCR-093..096 boards are PENDING (§0) and the research-boards PR, which carries `Closes #1017`, draws them · **BQ list RULED** (comment 6563817618) · **Owner approval pending** (agent-delivery adaptations, owner decision 2026-09-25) · **Method:** heuristic evaluation + persona walkthrough + public-documentation competitive review; **no session was run — no participant, timing or quote exists**; every finding is `(heuristic)` and every decision is **PROPOSED**; the orchestrator's design approval of this PR adopts them as interim rulings under the 2026-10-29 delegation, and the owner can reverse any one by one line on #1017.
- **Scope:** SCR-093 Journal list, SCR-094 Trade detail / post-mortem, SCR-095 Analytics dashboard, SCR-096 Tag manager, read through US-JRN-001..010, the personas P1, P2b and P3, `21` §3.7 and the `22` journal operations. **Out of scope (ticket):** hi-fi, tokens, motion (E41-D02 / D03); replay and alerts boards; quantitative instrumentation studies.
- **Read at:** `origin/main` `46e6acd2ddf3835580a801ac9b143d32f4478090`. **Key:** `NN`:line = `docs/plan/NN-*` at that base (`22` = `docs/plan/22-api-openapi.yaml`); every cite is re-read by `docs/design/_tools/e41_d01_audit.py --check`.
- **Ids:** **RQ** research question · **H** hypothesis · **F** finding · **WD** wireframe decision · **C** contradiction · **G** contract gap · **A** catalogue amendment · **N** new-component note · **OQ** open question · **N1–N10** Nielsen's heuristics.

## Acceptance-criteria trace (issue #1017)

Status key: **done** = delivered as worded · **heuristic-only** = delivered through the adaptation, pending the owner's sessions · **substituted** = a live-session deliverable replaced by the heuristic run, the protocol and the owner walkthrough · **open** = needs the boards or an owner decision.

| AC or deliverable                                                    | Where                                         | Status                                 |
| -------------------------------------------------------------------- | --------------------------------------------- | -------------------------------------- |
| AC1 — 3 moderated sessions, recorded with consent                    | protocol; §10 walkthrough                     | substituted                            |
| AC1 — ≥5 numbered findings, each traced to a wireframe decision      | §5 F-1..F-8, §6 WD-1..WD-13                   | heuristic-only                         |
| AC2 — every declared state exists as a frame; no unlisted component  | §7 frame list, §8 N-rows; boards §0           | open — frames listed, boards PENDING   |
| AC3 — low-sample caveat on every rate; no prescriptive language      | WD-3, WD-4, §7.1 copy deck, the audit lexicon | open — text done; frames PENDING (§0)  |
| DoD — sessions run, notes and consent recorded                       | protocol §2–§4                                | substituted                            |
| DoD — findings memo published and linked from the ticket             | this file                                     | done in PR, pending merge and the link |
| DoD — journey map merged into `17`                                   | `17` §1.6                                     | done in PR, pending merge (heuristic)  |
| DoD — wireframes, all four screens, all states, shareable link       | §0                                            | open — the boards PR (`Closes #1017`)  |
| DoD — CDO review and sign-off comment                                | #1017                                         | open — interim on design approval      |
| DoD — new-component candidates CMP-166..169 flagged to design system | §8 A-rows and N-rows to E41-D04 #1082         | open — recorded in §8; #1082 post open |
| Scope — IA: `/journal`, `/journal/analytics`, SCR-094, SCR-096 shape | WD-12                                         | done (PROPOSED)                        |
| Observability — the six analytics events                             | §9                                            | done                                   |

## Deviations

1. **Sessions.** Moderated sessions, recordings and quotes are substituted by §3–§5, the protocol and the §10 walkthrough (ticket "Agent-delivery adaptations"); AC1's sessions stay **open** for the owner.
2. **Figma → Penpot.** Boards on the Penpot page `E41-D01` (name + id only), exports under `docs/design/E41/img/`.
3. **Paths.** The brief's `apps/web` paths and pnpm commands do not apply: this is a docs-only PR.
4. **Two PRs (BQ-1, RULED).** This memo PR says `Refs #1017` with a `Partial:` note and closes nothing; the research-boards PR carries `Closes #1017` (`docs/design/README.md`'s boards rule holds for research tickets too).
5. **States per screen.** The ticket asks loading, empty, partial, reconciling and insufficient sample on all four screens; BQ-7's default builds `14`'s States lines plus the checklist states, so SCR-094 has no empty or reconciling frame, SCR-096 no loading or partial, and insufficient sample is on SCR-095 only (§7).
6. **No owner-document edit.** Per the ruling, every proposed change to `12`, `13`, `14` or `24` is an A-row in §8, not an edit; this PR leaves those files untouched (the `14` pointer to this memo is A-7).
7. **Competitive sources.** BQ-5 asks a fetched date, a URL and a verbatim quote per row; the pages could not be fetched, so §3 rows carry search-index descriptions only and feed no decision alone.

## BQ list — RULED (comment 6563817618)

The pre-writing BQ list (BQ-0..BQ-16) is posted on #1017 as comment 6563728342; the orchestrator's ruling of record, comment 6563817618, rules every ORCH-default as proposed, BQ-0 through BQ-16. This memo builds exactly on those defaults; each section names the BQ it carries. As ruled: every finding stays `(heuristic)` with no invented participant, quote or timing; every decision stays PROPOSED and becomes an interim ruling on the orchestrator's design approval of this PR (2026-10-29 delegation), which the owner can reverse by one line; every proposed `12` / `13` / `14` / `24` change is an A-row (§8), not an edit; this memo PR is `Refs #1017` + `Partial:` and the research-boards PR closes #1017.

| BQ    | Default built here                                                                                                 | Where             |
| ----- | ------------------------------------------------------------------------------------------------------------------ | ----------------- |
| BQ-1  | `Refs #1017` + `Partial:`; AC1 substituted; `Closes #1017` only on the research-boards PR                          | AC trace          |
| BQ-2  | this memo + `e41-d01-session-protocol.md` + `17` §1.6; the wireframe spec `docs/design/E41/E41-D01.md` with boards | header, §0        |
| BQ-3  | 5–8 findings, each → ≥1 WD naming `SCR-0nn/<state>` with one Given/Then check; all four SCRs covered               | §5, §6            |
| BQ-4  | walkthroughs for P1, P2b, P3; the protocol recruits P1 + P2 only                                                   | §4                |
| BQ-5  | public documentation only, no third-party image; recordings owner-local, 90 days; fetch not met (Deviation 7)      | §3, §11           |
| BQ-6  | one scope at a time, LIVE default, a scope label on every SCR-093..095 frame; replay out of v1 (OQ-2); G-1         | WD-1, WD-2        |
| BQ-7  | `14` states + checklist states + no-match + error; insufficient sample on SCR-095 only (Deviation 5)               | §7                |
| BQ-8  | stats always shown; `14` caveat at n < 20, bucket marker at n < 5, n per rate; formula link (E41-T05); lexicon     | WD-3, WD-4, WD-14 |
| BQ-9  | SCR-094 = the R-181 page; SCR-096 a modal from SCR-093's header; A-5, A-6                                          | WD-12             |
| BQ-10 | free text + optional category, global names, 24 chars; auto tags removable and recorded; OQ-1                      | WD-7, WD-8        |
| BQ-11 | rows per account; aggregate rows never in totals; group siblings on SCR-094 only; G-2                              | WD-9              |
| BQ-12 | context chart = an engine minimal pane with CMP-181 (`15`:2129); histogram, scatter N-rows; A-rows CMP-166 / 168   | WD-6, §8          |
| BQ-13 | granted accounts; manager export = own; Viewer read-only; export confirm names the account data                    | WD-10, WD-13      |
| BQ-14 | `17` §1.6 in §1.5's shape; downstream feeds as named per row, E41-T05 #1083 via WD-14                              | §6, §8            |
| BQ-15 | ten lo-fi boards, no light twins                                                                                   | §0                |
| BQ-16 | `docs/design/_tools/e41_d01_audit.py`, `--check` + `--self-test`                                                   | the tool          |

## 0. Wireframe boards (Penpot) — PENDING

Drawn in the research-boards PR (`Closes #1017`), after this text merges, through the Penpot queue; lo-fi, dark only, ten boards, each frame named `SCR-0nn/<state>` from §7. Nothing below is drawn yet.

| #   | Board                                                                                      | State   |
| --- | ------------------------------------------------------------------------------------------ | ------- |
| 01  | research board — the §1.6 journey and the F → WD map                                       | PENDING |
| 02  | SCR-093 default (LIVE scope, columns, totals, paging) + bulk-tag and export-confirm insets | PENDING |
| 03  | SCR-093 states (loading, empty, partial, reconciling, no-match, error)                     | PENDING |
| 04  | SCR-094 default (fills, excursions, attribution, siblings, notes, tags, replay link)       | PENDING |
| 05  | SCR-094 context states (loading, bar-only, context-not-recorded, pruned, error)            | PENDING |
| 06  | SCR-095 default + table view                                                               | PENDING |
| 07  | SCR-095 insufficient-sample, low-bucket, empty, no-match, loading, error                   | PENDING |
| 08  | environment scope and cohort controls                                                      | PENDING |
| 09  | SCR-096 default, create, rename, merge, delete, empty, error                               | PENDING |
| 10  | keyboard, reading order, 200 % zoom                                                        | PENDING |

Not drawn — the text is binding: SCR-093/viewer-read-only (WD-13) and SCR-093/export-failed (a toast); their copy is in §7.1 and E41-D05 #1205 checks both on the built screen.

## 1. Method (agent-delivery adaptation, owner decision 2026-09-25)

- **Heuristic evaluation** of the four catalogued surfaces against Nielsen's ten heuristics (N1 visibility of status … N10 help) and `05`'s trading reading: POUR for trading (`05`:17), colour-independence with the signed P&L (`05`:105, `05`:114), the data-table alternative for canvas views (`05`:156) and dense focus (`05`:90). The ticket's adaptation names "the trading-specific heuristics in `05`"; `05` has no such list (the gap is the ticket's), so these four sections stand in. N2, N7 and N10 were not exercised by any finding; each finding carries a severity (cosmetic / minor / major), designer judgement.
- **Then** a persona walkthrough (§4) and a competitive review (§3). No participant was recruited; the ticket's "spreadsheet/notes" baseline is described from the ticket, not observed.
- **No contrast or CVD figure** appears here: E41-D02 / D03 compute them with `docs/design/_tools/contrast_check.py` and `docs/design/_tools/cvd_sim.py`.

## 2. Research questions and pre-registered hypotheses (all untested)

| RQ  | Question (ticket)                       | Hypothesis                                                                                                   |
| --- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| RQ1 | (a) what triggers a review session      | H1: a losing session or a rule that acted unexpectedly, then a scheduled weekly or quarterly pass (`10`:168) |
| RQ2 | (b) which fields are looked at first    | H2: R and net P&L, then side and symbol, then whether the stop held — not entry price                        |
| RQ3 | (c) taxonomy or free text for tags      | H3: free text in the moment, a few categories later; rule tags are trusted only if marked as auto            |
| RQ4 | (d) whether demo results are meaningful | H4: yes as a rehearsal of a method, never as a total beside LIVE                                             |
| RQ5 | (e) what is exported and why            | H5: the filtered list as CSV for an external spreadsheet or an accountant; analytics rarely                  |

## 3. Competitive review — public documentation only

Located on 2026-11-01 through a web search; the pages themselves could not be fetched from this host, so **no row carries a quote** and each pattern is a search-index description to confirm on the page before it is relied on. Each pattern cell paraphrases the search snippet. No vendor screenshot or logo is in git or on a board; patterns, not products, illustrate the decisions, and no WD rests on this table alone.

| Product    | Pattern described                                                                | Source (unverified, not fetched)                              | Verified | Illustrates (only) |
| ---------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------- | -------- | ------------------ |
| Tradervue  | tags added at import, per trade or in bulk; a per-tag and tag-combination report | `https://help.tradervue.com/article/3484-how-to-tag`          | no       | WD-7, WD-8         |
| Edgewonk   | user-defined tag groups ("custom statistics") with a trade count per entry       | `https://edgewonk.zendesk.com/hc/en-us/articles/360010061200` | no       | WD-4, WD-7         |
| TraderSync | an account is marked live or simulated, reports run per account                  | `https://tradersync.com/support/how-can-i-sync-my-trades/`    | no       | WD-1               |

## 4. Persona walkthroughs `(heuristic)`

- **P1 Owner, the evening after a losing session.** Follows the post-mortem path of `10`:101: filters SCR-093 to the day and a tag, opens the loser, reads R and the stop path, jumps to replay, notes and re-tags. Predicted friction: a total that silently includes DEMO (F-1); a context chart that spins when nothing was recorded (F-4); an auto tag the owner cannot remove (F-5).
- **P2b swing manager, weekly.** Journal-heavy (`10`:112); scoped to granted accounts (`14`:2154). Predicted friction: a group trade counted twice (F-6); an export that does not say whose data it holds (F-7).
- **P3 Viewer, quarterly review with a screen reader at 200 %.** `10`:164 asks for tables and text summaries; `10`:168 filters, exports, reads the curve and the per-tag table. Predicted friction: a histogram or scatter with no table (F-8); a stat read aloud without its sample size (F-2).

## 5. Findings (each `(heuristic)`; each → at least one WD)

| F   | Finding                                                                                                                | Heuristic | Severity | Evidence                                                                    | → WD              |
| --- | ---------------------------------------------------------------------------------------------------------------------- | --------- | -------- | --------------------------------------------------------------------------- | ----------------- |
| F-1 | Nothing in the read contract tells LIVE from DEMO or paper, so any total can mix them (heuristic)                      | N1, N5    | major    | `14`:2175, `14`:2211, `11`:4697, `21`:3318–3319, `22`:22310                 | WD-1, WD-2        |
| F-2 | Three different low-sample treatments are specified, one of them hides the numbers (heuristic)                         | N4, N1    | major    | `14`:2205, `14`:2211, `13`:398, `11`:4700, `11`:4737                        | WD-3, WD-4, WD-14 |
| F-3 | Review starts from a filtered list and a loser, so R and net P&L must lead the row (heuristic) — rests on H2, untested | N6, N8    | minor    | `10`:101, `14`:2169, `14`:2175                                              | WD-5, WD-12       |
| F-4 | Market context can be absent, bar-only or pruned, and each needs its own words, not a spinner (heuristic)              | N1, N9    | major    | `14`:2197, `11`:4680, `11`:4754, `11`:4664                                  | WD-6              |
| F-5 | Tags are global in the schema, per user in the story, and auto tags are both removable and not (heuristic)             | N4, N3    | minor    | `21`:3379, `11`:4628, `11`:4644, `15`:2147, `14`:2216, `22`:9657, `14`:2195 | WD-7, WD-8        |
| F-6 | A group of N legs stores N + 1 rows; without the flag a total double-counts (heuristic)                                | N5        | major    | `21`:3307, `21`:3315, `22`:22310                                            | WD-9              |
| F-7 | Export scope differs by role and the export must say it carries account data (heuristic)                               | N1, N5    | major    | `11`:4774, `11`:4780, `04`:350, `04`:976, `12`:229                          | WD-10, WD-13      |
| F-8 | Two of the analytics charts have no catalogued component and every chart owes a table (heuristic)                      | POUR, N6  | major    | `14`:2201, `14`:2206, `15`:2127, `05`:156                                   | WD-11             |

## 6. Wireframe decisions (PROPOSED; each testable on a board or by E41-D05)

| WD    | Decision                                                                                                                            | Frame                        | Check (Given … [When …] then …; a frame violates it otherwise)                                                                                                | Owner ticket                               |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| WD-1  | One environment scope at a time (LIVE default, DEMO by choice); never a combined total                                              | SCR-093/default              | Given any SCR-093..095 frame, then one scope label (LIVE or DEMO) is shown and every total sits under it; SCR-096 has none (tags are global, `21`:3379)       | E41-S01 #1209                              |
| WD-2  | SCR-095's DEMO toggle switches the scope; it never adds DEMO to LIVE                                                                | SCR-095/default              | Given the toggle on, then every figure and chart is labelled DEMO and no LIVE figure remains                                                                  | E41-S03 #1211 (OQ-3 may amend)             |
| WD-3  | Statistics stay visible under 20 trades, with the `14` caveat verbatim and n beside each rate                                       | SCR-095/insufficient-sample  | Given n < 20, then the rates show with "Fewer than 20 trades — statistics are noisy" and n                                                                    | E41-D03 #1081                              |
| WD-4  | A breakdown bucket under 5 trades carries a text marker and its count                                                               | SCR-095/low-bucket           | Given a bucket with n < 5, then the row shows "Low sample (n = 3)" as text, not colour alone                                                                  | E41-D03 #1081                              |
| WD-5  | List columns lead with time, symbol, side, R, net P&L; totals are server-side for the filter (lowest confidence: rests on F-3 / H2) | SCR-093/default              | Given the list, then R and net P&L precede entry and exit, and the totals bar names its filter                                                                | E41-D02 #1018                              |
| WD-6  | The context pane (CMP-181 in an engine minimal pane) has four words: loading, bar-only, not recorded, pruned (bar replay)           | SCR-094/context-not-recorded | Given no recording, then the pane says "Context not recorded" with the trade's own fills listed                                                               | E41-D03 #1081                              |
| WD-7  | Tags are free text with an optional category, ≤24 characters, counted in the manager                                                | SCR-096/default              | Given the tag table, then each row shows name, category, usage count and text beside any colour                                                               | E41-D02 #1018 (OQ-1 may amend)             |
| WD-8  | Auto tags read `auto`, are removable, and the removal is recorded                                                                   | SCR-094/default              | Given an auto tag in SCR-094's tag editor, then it carries the word "auto" and a remove control; when it is removed, then the note names the recorded removal | E41-T04 #1132                              |
| WD-9  | Rows are per account; aggregate rows never enter totals; siblings appear on SCR-094 only                                            | SCR-094/default              | Given a group trade, then the list shows one row per account and SCR-094 lists the siblings                                                                   | E41-T01 #1019, E41-D03 #1081               |
| WD-10 | Export confirms scope, range, row count and "includes account data"                                                                 | SCR-093/export               | Given the filtered list, when export is chosen, then the confirm states environment, accounts, range, rows and the account-data line                          | E41-S04 #1212; E41-X01 #1133 security note |
| WD-11 | Every chart has "View as table" and a one-line text summary with n                                                                  | SCR-095/table-view           | Given any chart, then a table view and a summary such as "Expectancy +0.34R over 42 trades" exist                                                             | E41-D04 #1082                              |
| WD-12 | SCR-094 is the R-181 page; SCR-096 is a modal from SCR-093's header; M-019 stays notes-only                                         | SCR-093/default              | Given SCR-093's header, then "Manage tags" opens the modal and a row opens the page, not a drawer                                                             | E41-D02 #1018                              |
| WD-13 | A Viewer reads only: no tag, note or tag-manager entry; ungranted accounts are absent                                               | SCR-093/viewer-read-only     | Given a Viewer, then no write control is shown and the account filter lists granted accounts only                                                             | E41-S01 #1209; E41-D05 #1205 (not drawn)   |
| WD-14 | Each statistic links to its formula in the journal statistics reference                                                             | SCR-095/default              | Given any statistic, then a link to its formula reference sits beside it                                                                                      | E41-T05 #1083                              |

## 7. Frames per screen (AC2)

`14` lists states for SCR-093 (`14`:2169) and SCR-095 (`14`:2205) only; SCR-094 and SCR-096 take their checklist states (`14`:2199, `14`:2222) and A-4 proposes a States line for both.

| Screen  | Frames                                                                                                                      |
| ------- | --------------------------------------------------------------------------------------------------------------------------- |
| SCR-093 | default · loading · empty · partial · reconciling · no-match · error · bulk-tag · export · export-failed · viewer-read-only |
| SCR-094 | default · loading · bar-only · context-not-recorded · pruned · error                                                        |
| SCR-095 | default · table-view · loading · insufficient-sample · low-bucket · empty · no-match · error                                |
| SCR-096 | default · empty · create · rename · merge · delete · error                                                                  |

### 7.1 Copy deck (PROPOSED; descriptive only — the audit refuses imperative and evaluative words)

| Key            | String                                                                 |
| -------------- | ---------------------------------------------------------------------- |
| scope.live     | LIVE only — DEMO trades are not included                               |
| scope.demo     | DEMO only — LIVE trades are not included                               |
| caveat.sample  | Fewer than 20 trades — statistics are noisy                            |
| caveat.bucket  | Low sample (n = {n})                                                   |
| empty.range    | No trades in this range                                                |
| empty.filter   | No trades match these filters                                          |
| context.none   | Context not recorded — fills and prices are listed below               |
| context.bars   | Bars only for part of this trade — excursions are bar-derived          |
| context.pruned | Recorded ticks were pruned — bar replay is available                   |
| export.confirm | Includes account data for {accounts} · {env} · {range} · {rows} trades |
| export.failed  | Export failed — no file was created                                    |
| view.readonly  | Read-only — tags and notes are not editable for this role              |

## 8. Contradictions, gaps and catalogue notes (each with an owner)

| Id  | Item                                                                                                                                                                             | Owner                        |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| C-1 | Caveat copy `14`:2205 vs `14`:2211 vs the empty state of `13`:398; the default is `14`:2205 with stats shown (`11`:4700)                                                         | E41-D03 #1081                |
| C-2 | Tags per user (`11`:4628) vs one global unique name (`21`:3379)                                                                                                                  | owner — OQ-1                 |
| C-3 | Auto tags removable (`11`:4644) vs `readOnlyTags` non-removable (`15`:2147)                                                                                                      | E41-D04 #1082                |
| C-4 | SCR-094 "Page/Drawer" (`14`:2179) vs the R-181 page (`12`:86)                                                                                                                    | E41-D03 #1081                |
| C-5 | M-019 opened from a list row (`12`:223) vs from the trade detail (`13`:388); M-019 lists a Viewer variant vs read-only `10`:16                                                   | E41-D02 #1018                |
| G-1 | `JournalTrade` has no `env` / `is_paper` (`22`:22310; `21`:3318–3319) and neither read takes an environment filter                                                               | E41-T01 #1019, E41-T03 #1021 |
| G-2 | `JournalTrade` has no `is_aggregate` (`21`:3315)                                                                                                                                 | E41-T01 #1019                |
| G-3 | Tag length 40 in `22` (create `22`:9840, filter `22`:9657) vs ≤24 in `14` (`14`:2216); `22` has list and create but no rename, merge or delete                                   | E41-T04 #1132                |
| G-4 | `group_by` (`22`:9877) has `hour_of_day` ("session hour", `22`:9864) but no rule-source key where the checklist asks by-rule and streaks (`14`:2211); `setup` is the nearest key | E41-T03 #1021                |
| A-1 | CMP-169: `readOnlyTags` → auto tags with provenance, removable                                                                                                                   | E41-D04 #1082                |
| A-2 | CMP-166: Decimal strings for prices and P&L, plus environment, account, fees and a bar-derived flag (`15`:2098)                                                                  | E41-D04 #1082                |
| A-3 | CMP-168: a sample-size and caveat prop (`15`:2136)                                                                                                                               | E41-D04 #1082                |
| A-4 | `14`: a States line for SCR-094 and SCR-096 from §7                                                                                                                              | E41-D03 #1081                |
| A-5 | `12`: an M-row for the SCR-096 tag-manager modal                                                                                                                                 | E41-D02 #1018                |
| A-6 | `13`:406: SCR-096 joins M-019 and M-025 as the flow's modal surfaces                                                                                                             | E41-D02 #1018                |
| A-7 | `14`: one pointer line under SCR-093 naming this memo, changing no requirement                                                                                                   | E41-D02 #1018                |
| N-1 | R-distribution histogram (no catalogued component; CMP-024 is a sparkline)                                                                                                       | E41-D04 #1082                |
| N-2 | MAE/MFE scatter, shape by outcome (`14`:2206)                                                                                                                                    | E41-D04 #1082                |

Components named on the boards and already catalogued: CMP-003, CMP-021, CMP-024, CMP-026, CMP-028, CMP-036, CMP-043, CMP-044, CMP-047, CMP-049, CMP-055, CMP-058, CMP-075, CMP-099, CMP-116, CMP-166, CMP-167, CMP-168, CMP-169, CMP-181.

### 8.1 Open questions

| OQ   | Question                                                                           | Owner         |
| ---- | ---------------------------------------------------------------------------------- | ------------- |
| OQ-1 | Are tag names per user or global?                                                  | owner         |
| OQ-2 | Do replay paper fills enter the journal at all (out of v1 by default)?             | owner         |
| OQ-3 | Should DEMO and LIVE ever sit side by side (never summed) for a method comparison? | owner         |
| OQ-4 | What source feeds the "regime at entry" auto-tag rule (`14`:2215)?                 | E41-T04 #1132 |

## 9. Analytics events

The ticket's six — `journal.list_viewed`, `journal.filtered`, `journal.detail_viewed`, `journal.analytics_viewed`, `journal.analytics_filtered`, `journal.cohort_changed` — plus `14`'s export and replay events only — `journal.exported`, `journal.analytics_exported` and `journal.replay_from_trade`; `journal.screenshot_exported` (`14`:2198) is out of scope here; analytics only, no account identifier or P&L in a payload.

## 10. Owner session protocol and walkthrough

The three 45-minute sessions (P1 + P2; P3 a walkthrough only) are in `e41-d01-session-protocol.md`. The owner can confirm or overturn the defaults without a session by walking these items on #1017. Items 3–9 use the boards once drawn; until then they use §7.1 and the §6 Check column as printed cards. Every stimulus holds synthetic rows only (protocol §3); real data stays in the owner's own spreadsheet and no live service is touched.

1. In the spreadsheet or notes used today, open yesterday's losing trade; note the first two fields read (RQ2, WD-5).
2. Say when you last reviewed, and what started it (RQ1).
3. On the board, read a LIVE total and say whether DEMO could be inside it (WD-1, WD-2).
4. On the 12-trade board, say what the caveat tells the reader (WD-3, WD-4, WD-14).
5. On the board, remove an auto tag; say what the record is expected to keep (WD-8).
6. On the SCR-096 board, rename and merge two tags; check the affected-trade count (WD-7).
7. On the board, open a trade with no recording; say what is missing and why (WD-6).
8. On the board, export the filtered list; read the confirm aloud (WD-10).
9. On the board or card, walk "View as table" for each chart in keyboard order (WD-11).
10. Rule OQ-1..OQ-3.

## 11. Security and data handling

Recordings (if the owner runs sessions) stay owner-local, not on a third-party service (C-1.2), are kept 90 days, and only redacted stills — no account id, balance or key identifier (A-12, `04`:81) — may appear in a research artefact. Stimuli (boards, cards, prototypes) carry synthetic rows only and touch no live Bybit or app backend.
