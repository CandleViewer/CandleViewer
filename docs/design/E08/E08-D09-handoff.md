# E08-D09 — Hand-off (`16` §11.4; SCR-147, exchange connectivity and limits)

Components: **CMP-178 SystemHealthTile** (the summary strip), **CMP-023 Progress Bar** (`meter`), **CMP-049 Table** (the per-class grid, the inspector, the simulator's result and the history table), **CMP-044 ConfirmDialog** with **CMP-093 AuditActionTrigger** (Force reconnect, Change budget), **CMP-024 Sparkline** (history), **CMP-036 KeyValueRow** (clock, reserve band), **CMP-079 RbacGate** with the CMP-019 `lock` (every T2 control), plus the SCR-147 rows of `14` and CMP-178's row in `15`. The spec is [E08-D09.md](E08-D09.md); every "§" below without a prefix is the spec's. No component contract changes: the page composes existing variants (RULED BQ-19), so the `15` row only names SCR-147 as a host.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | CMP-178 tiles                                              | CMP-023 meter                       | CMP-049 grids and tables                     | CMP-044 + CMP-093 dialogs                                     | CMP-024 history              |
| ------------------------ | ---------------------------------------------------------- | ----------------------------------- | -------------------------------------------- | ------------------------------------------------------------- | ---------------------------- |
| Final Penpot link        | [ ] PR 3: page `E08-D09 SCR-147 Connectivity`, board 01    | [ ] PR 3: boards 01, 02             | [ ] PR 3: boards 01, 06, 07                  | [ ] PR 3: boards 04, 06                                       | [ ] PR 3: board 07           |
| Variants × states        | [x] §2.2, §5.2 (S-01 … S-20 on a tile)                     | [x] §3.2 (steps, never animates)    | [x] §3, §8, §9, §14                          | [x] §11, §12 (rung 2, rung 1)                                 | [x] §14                      |
| Keyboard table           | [x] §17.3 (the heading link)                               | [x] none: not focusable             | [x] §17.3 SCR-147-KB-2, KB-6                 | [x] §17.3 SCR-147-KB-1, KB-3                                  | [x] §17.3 SCR-147-KB-5       |
| Accessible name and role | [x] §17.2 (`region`, units in words)                       | [x] §17.2 (`role="meter"`, W-09)    | [x] §17.1 (caption W-07, row headers)        | [x] §11 (`alertdialog`, the first consequence as description) | [x] §14 (`role="img"`, W-72) |
| Live data                | [x] §17.4: the tile never announces; the shell's pair does | [x] never live (SR-1)               | [x] the 1 Hz update announces nothing (SR-1) | [x] SR-12 once per press                                      | [x] none: a disclosure       |
| Motion pair              | [x] one flip on entry and exit (§19)                       | [x] steps per sample (§19; D09-C10) | [x] none                                     | [x] CMP-044's own                                             | [x] none                     |
| Density notes            | [x] comfortable (CMP-087)                                  | [x] comfortable                     | [x] comfortable; reflow §17.6                | [x] comfortable                                               | [x] comfortable              |
| Essential exceptions     | [x] none                                                   | [x] none                            | [x] none                                     | [x] none                                                      | [x] none                     |
| Tokens used              | [x] §16                                                    | [x] §16                             | [x] §16                                      | [x] §16                                                       | [x] §16                      |
| Data contract            | [ ] NO: D09-G1, D09-G5                                     | [ ] NO: D09-G1, D09-G14             | [ ] NO: D09-G1, D09-G3, D09-G9, D09-G10      | [ ] NO: D09-G7, D09-G8, D09-G12, D09-G17                      | [ ] NO: D09-G9               |
| Contrast                 | [ ] measured at PR 3 (§16)                                 | [ ] measured at PR 3                | [ ] measured at PR 3                         | [ ] measured at PR 3                                          | [ ] measured at PR 3         |
| Storybook                | [x] §D                                                     | [x] §D                              | [x] §D                                       | [x] §D                                                        | [x] §D                       |
| Sign-off                 | [ ] pending (RULED BQ-24)                                  | [ ] pending                         | [ ] pending                                  | [ ] pending                                                   | [ ] pending                  |

## §B Who applies what

| A         | Target       | Applied by                              |
| --------- | ------------ | --------------------------------------- |
| A-1 … A-6 | `14` SCR-147 | PR 2, from the tool's `--a-rows` export |
| A-7       | `15` CMP-178 | PR 2, in the `15` queue                 |

PR 2 changes `14`, `15` and, at most, a byte-exact rewrite of the pins; the tool's G-UNTOUCHED checks it in its PR 2 mode.

## §C Copy-ready A-rows (PR 2 applies them byte for byte; never in PR 1)

**Rules.** Each row names its target file and line at the base `03ee085982`, its op and its source, then its Old (or anchor) and its New, each a fenced block. PR 2 applies them byte for byte from the tool's `--a-rows` export, queued behind any open PR on the same lines and re-pinned by content at its open (RULED BQ-02). No `16` row: no token is added (spec §16).

#### A-1 · SCR-147 · Type

`14`:2983 · replace · from BQ-09, BQ-08 (D09-C6, D09-C7)

```old
- **Type:** Page. Per-account REST and WS rate-limit budgets, current consumption, recent 10018 events, the fan-out budgeting model, and per-endpoint weights; includes a simulator ("a 5-account fan-out with brackets costs ≈ 15 requests — 9 % of your minute budget").
```

```new
- **Type:** Page. Per-account REST and WS rate-limit budgets, current consumption, recent 10018 events and the IP hold, the fan-out budgeting model, and per-endpoint weights; includes a simulator whose figures come from the server's planner, never the browser ("a 5-account fan-out with brackets costs about 15 requests — 9 % of each account's spendable budget per minute", the figures illustrative; E08-D09 D09-C7). Three rate states, each with its own word: throttled (per account), on hold (all accounts, our hold's time left) and banned (the IP lockout, contract-first; E08-D09 D09-C6).
```

#### A-2 · SCR-147 · Components

`14`:2984 · replace · from BQ-19

Scope: the `Components` line under the heading `### SCR-147 — Admin: exchange connectivity & rate limits` (`14`:2981). The same text also stands at `14`:2878 under SCR-142, which PR 2 never touches; the tool re-points this row by its scope heading.

```old
- **Components:** CMP-023 Progress Bar, CMP-024 Sparkline, CMP-036 KeyValueRow, CMP-049 Table, CMP-087 AdminLayout, CMP-178 SystemHealthTile.
```

```new
- **Components:** CMP-023 Progress Bar (`meter`), CMP-024 Sparkline, CMP-036 KeyValueRow, CMP-049 Table, CMP-087 AdminLayout, CMP-088 PageHeader, CMP-178 SystemHealthTile, CMP-044 ConfirmDialog, CMP-093 AuditActionTrigger, CMP-027 ErrorState / InlineError, CMP-015 Skeleton, CMP-239 FreshnessMarker, CMP-079 RbacGate with the CMP-019 Icon `lock` (every T2 control).
```

#### A-3 · SCR-147 · A11y

`14`:2986 · replace · from BQ-20, BQ-05

```old
- **A11y:** Per-endpoint-class table (REST order, REST query, public WS, private WS) with limit, current usage, window and headroom as numbers with units; per-account rows are labelled with the account.
```

```new
- **A11y:** Per-endpoint-class table (REST order, REST query, public WS, private WS; REST rows named by the contract's `RateBudget.endpoint_class` values, with the adapter's class as a second line) with limit, current usage, window and headroom as numbers with units, headroom excluding the reserve for stops and cancels; per-account rows are labelled with the account alias. Meters carry `aria-valuetext` with the real numbers. Every announcement is written into the shell's live-region pair (E17-D02 §11): entering Disconnected is the one assertive line; throttled, on-hold, banned, order-entry-halted, degraded and recovery lines are polite, once per episode and at most one per 5 s per region; usage, ages and countdowns are never announced. The sparkline has a "View as table" alternative. No key is bound by the page (E08-D09 §17).
```

#### A-4 · SCR-147 · Performance

`14`:2987 · replace · from BQ-22 (D09-C10)

```old
- **Performance:** Usage figures come from the backend's own rate-limit accounting (server-side counters and exchange response headers), sampled at 1 Hz; the browser never queries the exchange directly.
```

```new
- **Performance:** Usage figures come from the backend's own rate-limit accounting (server-side counters and exchange response headers), sampled at 1 Hz; the browser never queries the exchange directly. Meters step with each sample and never animate; rows update in place by key; the subscription inspector virtualises past 60 rows; the history and the simulator fetch on demand (E08-D09 §19).
```

#### A-5 · SCR-147 · Analytics/audit

`14`:2988 · replace · from BQ-23 (D09-C12)

```old
- **Analytics/audit:** `connectivity.panel_viewed` (analytics); `connectivity.budget_changed` (per-account request budget) and `connectivity.reconnect_forced` are **audited**.
```

```new
- **Analytics/audit:** `connectivity.panel_viewed` (analytics); `connectivity.budget_changed` (per-account request budget) and `connectivity.reconnect_forced` are **audited**. Both audit codes are PROPOSED until the audit registry lists them; until then each action's marker shows its label only (E42-D02 D5; E08-D09 D09-G7, D09-G8).
```

#### A-6 · SCR-147 · the hi-fi pointer

`14`:2990 · insert after · from BQ-01

```anchor
- **A11y review (E08-D12):** [E08-D12.md](../design/E08/E08-D12.md) (E08-D12; structure only; hi-fi review owed by E08-D09; owner approval pending).
```

```new
- **Hi-fi (E08-D09):** [E08-D09.md](../design/E08/E08-D09.md) (the page, the twenty-state register, the gap ledger of what the backend does not serve yet; the boards at E08-D09's PR 3; owner approval pending).
```

#### A-7 · CMP-178 · Purpose

`15`:2228 · replace · from BQ-04

```old
- **Tier**: Molecule (owner/admin) · **Purpose**: one metric tile on the admin Health screen or the SCR-120 overview — ingestion lag, WS state, DB status, engine FPS, a slice's counts — each with threshold-based tone and its own loading, error, unavailable and stale state.
```

```new
- **Tier**: Molecule (owner/admin) · **Purpose**: one metric tile on the admin Health screen, the SCR-120 overview or the SCR-147 summary strip — ingestion lag, WS state, DB status, engine FPS, a slice's counts — each with threshold-based tone and its own loading, error, unavailable and stale state.
```

## §D Storybook story lists (each story in dark, light and high contrast)

| Component                  | Stories                                                                                                               |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| CMP-178 SystemHealthTile   | the merged list (`15`:2232) + RateHeld · RateBanned · ClockHalted · NotMeasured                                       |
| CMP-023 Progress Bar       | the merged list (`15`:283) + MeterStepped · MeterNotConnected                                                         |
| CMP-049 Table              | the merged list (`15`:583) + BudgetGrid · BudgetGridPerMinute · InspectorVirtualised · SimulatorResult · HistoryTable |
| CMP-044 ConfirmDialog      | the merged list (`15`:520) + ReconnectMarketData · ChangeBudget · ChangeBudgetRefused                                 |
| CMP-079 RbacGate           | the merged list (`15`:888) + HoldReason · ConnectionBudgetWait · ViewAs                                               |
| CMP-024 Sparkline          | the merged list (`15`:293) + UsageHistory · UsageHistoryEmpty                                                         |
| CMP-093 AuditActionTrigger | the merged list (`15`:1029) + MarkerPendingRegistration                                                               |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window, comfortable density)

- [ ] Board 01: every figure has its unit; a figure not served reads "Not connected yet", never 0.
- [ ] Board 02: approaching limit and throttled name the account, the class, the limit and the retry time.
- [ ] Board 03: held by IP and banned read differently from throttled; each prints only its own condition sentence.
- [ ] Board 04: disconnected, reconnecting and "Connection unstable" use E08-D04's words; the reconnect dialog says what it interrupts.
- [ ] Board 05: the clock shows its size and direction in words, its age, and the halt; "Not measured yet" is never "In sync".
- [ ] Board 06: the simulator counts the stop-loss always; the budget dialog states its four invariants.
- [ ] Board 07: the inspector names the limit that binds; the history has its table.
- [ ] Boards 08–10: light and high contrast keep every state as a word and a glyph.
- [ ] The engineering walkthrough (T:78): each row of spec §20.2 confirmed against an exported metric, or its G-row.

## §F Consumer pointers

| Consumer                                                                   | Builds from                        | Waits on                             |
| -------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------ |
| the SCR-147 page story (filed by the orchestrator at PR 1's merge; D09-C3) | spec §2–§20, §C, §D                | D09-G1 … D09-G17                     |
| E08-T02, E08-S07                                                           | spec §5.2, §6, §10, §20.2          | — (they own D09-G1, G5, G6, G8, G13) |
| E42-T01                                                                    | spec §3, §14, §21.2                | — (it owns D09-G2, G9)               |
| E08-D13 (#181)                                                             | spec §15, §17, §20.1               | —                                    |
| E08-D14 (#277)                                                             | spec §5.2 as the forced-state list | D09-G3, D09-G4                       |

## §G Summary for #177

1. Text-first SCR-147 spec + hand-off + audit tool; 10 boards follow in PR 3 (7 dark, 3 twins).
2. An Owner-only page in CMP-087; Manager and Viewer see no entry (T3 hidden).
3. Per-class budgets in the contract's `endpoint_class` words, each figure a number with its unit; the reserve is never spendable.
4. Throttled, held by IP and banned: three states, each with its own word, glyph and condition sentence.
5. The clock follows the guard: 500 ms warns, 2 000 ms halts order entry; never 0 while unmeasured.
6. Force reconnect is rung 2 with the marker "pending registration"; the budget change is drawn contract-first.
7. Almost every figure waits on a G-row with its owner; no shape is proposed.
