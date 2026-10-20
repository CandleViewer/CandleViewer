# E16-D02 — handoff checklist for CMP-177 RecorderStatusRow

SCR-140 changes the CMP-177 contract: a `state` enum and explicit actions replace `recording: boolean` and
`onToggleRecording` (`docs/design/E16/E16-D02.md` §4.2). This ticket therefore attaches the §11.4 checklist
(`docs/plan/16-design-system-brief.md` §11.4, §13.3 item 8). The rest of SCR-140 composes published components
unchanged: CMP-023 stays a `progressbar` (the threshold scale is separate text), CMP-028 is used in its own danger and
info tones, CMP-049 keeps its table model (↑/↓ rows), and CMP-055 shows active filter chips plus "Add filter". Their
own checklists apply.

## Handoff checklist — CMP-177 RecorderStatusRow (E16-D02, #323)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — file CandleViewer DS, page `E16-D02 SCR-140 Recorder`, board
      `CMP-177 · RecorderStatusRow — states`: link and PNGs in `E16-D02.md` §"Penpot boards"; PNG per state under
      `docs/design/E16/img/`. Pending: the boards are drawn in the next Penpot slots.
- [ ] **Variants × States matrix** — every state of the shipped spec is a Penpot variant and a Storybook story; table 1.
      Pending with the boards.
- [x] **Keyboard table** — table variant inside CMP-049 (row navigation ↑/↓, Tab into the row's controls); standalone
      variant (SCR-103) as a group of tab stops; no single unmodified key changes recording; `Esc` / `Ctrl+K`
      untouched; table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — the row's values update at 1 Hz from WS `recorder` and are never announced per tick; state
      changes are announced by the page's single polite region (E16-D02 §9.3), not by the row; table 5
- [x] **Motion pair** — the row animates nothing except CMP-014's spinner in Starting (its own reduced-motion pulse);
      table 4
- [x] **Density notes** — comfortable (admin default): row `size.row.comfortable`, controls `size.control.comfortable`;
      compact: `size.row.compact`, `size.control.compact`; smallest hit target 32 × 32 px comfortable (the Why?
      button and the switch at table size), 24 × 24 px compact; density table below
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Tier-2/Tier-3 only, as listed in `E16-D02.md` §11.1; none invented; Penpot token sets =
      `packages/ui/tokens` at the PR base, plus PR #3925's retune for the light danger tone (E16-D02 §10.4 finding 2)
- [ ] **Data contract confirmed** — REST `GET /recording/symbols`, `RecordingStatus`, `StorageUsage`; WS `recorder`
      §15.8; the recording-status amendment (`lingering`, `linger_until`, `refusal`, `level`, `write_gate`,
      `cap_bytes`, `accelerate_retention`, `role_restricted`, `policy`, the `backpressure_drop` gap reason and the
      add-reason rule). Pending: the amendment PR (E16-D02 §2, §15)
- [ ] **Contrast and CVD** — every pair is computed in E16-D02 §10.4 and passes. Pending: registering the pairs this
      row introduces in `tools/contrast/pairs.mjs` (status `.strong` icons and `danger.default` on
      `color.surface.raised`; `text.secondary` on `color.surface.sunken`, which the stale rows use). That is a security-owned `tools/` change,
      which lands with the implementation ticket (E16-S05) or a small tools PR. The CVD simulation is attached with
      the boards
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — on the PR
- [ ] **Sign-off** — owner `approved` comment or merged spec PR

### Table 1 — Variants × States

| State (Storybook)     | Penpot variant                                            | Condition                                          | Notes                                                         |
| --------------------- | --------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------- |
| `Recording`           | CMP-177 · RecorderStatusRow / State=recording             | manual, recording                                  | catalogue name                                                |
| `Stopped`             | State=stopped                                             | stopped, data kept per retention                   | catalogue name; "Record again"                                |
| `Pinned`              | State=recording, Pinned=true                              | keep forever                                       | catalogue name; Retention "Forever"                           |
| `NearDiskBudget`      | State=recording, Disk=near                                | disk level ≥ 1                                     | catalogue name; "· N % of budget" in words                    |
| `AutoChartOpen`       | State=recording, Reason=chart_open                        | auto, chart open                                   | Stop disabled with its reason                                 |
| `AutoPositionOpen`    | State=recording, Reason=position_open                     | auto, open position                                | Stop disabled with its reason (INV-B11-a)                     |
| `ManualWithPosition`  | State=recording, Reason=manual, StopBlocked=position_open | manual symbol with an open position                | Stop disabled (refusal `position_open`), never Gated          |
| `Lingering`           | State=lingering                                           | amendment `lingering`                              | "stops in N min"; "Keep recording"                            |
| `Starting`            | State=starting                                            | initial snapshot                                   | spinner; Stop disabled                                        |
| `Degraded`            | State=degraded                                            | a stream unhealthy                                 | gap count secondary                                           |
| `Gated`               | State=gated                                               | write gate closed, row `refusal` ≠ `position_open` | "Gated · data dropped"                                        |
| `RefusedSymbolCap`    | State=refused, Refusal=symbol_cap                         | 20-symbol limit                                    | no action                                                     |
| `RefusedDiskPressure` | State=refused, Refusal=disk_pressure                      | level 2 refusal                                    | no action                                                     |
| `Silent`              | State=silent                                              | no writes for ≥ 60 s                               | "No writes since …"                                           |
| `Error`               | State=error                                               | error                                              | error text in the row detail                                  |
| `Stopping`            | State=stopping                                            | flushing                                           | no action                                                     |
| `ReadOnly`            | State=recording, CanWrite=false                           | no `recording:write` (SCR-103)                     | controls disabled with the Owner reason                       |
| `Standalone`          | State=recording, Variant=standalone                       | outside a table (SCR-103 drawer)                   | group role, tab stops (tables 2–3)                            |
| `Stale`               | State=recording, Stale=true                               | no `recorder` frame for 2 s                        | sunken background, "stale" tag, words kept; name adds "stale" |

### Table 2 — Keyboard

| Key             | Variant | Action                                                           | Focus after                | Global conflict?                 |
| --------------- | ------- | ---------------------------------------------------------------- | -------------------------- | -------------------------------- |
| ↑ / ↓           | table   | previous / next row (CMP-049 row navigation)                     | the row                    | none (table-local)               |
| Tab / Shift+Tab | both    | the row's controls in order: Why? → Keep forever → action button | the control                | none                             |
| Enter           | table   | on the row: open the row detail; on a button: activate           | drawer heading / dialog    | none                             |
| Space           | both    | on Keep forever: open the confirmation; step-up runs on submit   | the dialog                 | none                             |
| Esc             | both    | close a popover, dialog or the row detail                        | the control that opened it | keeps its global meaning (close) |

### Table 3 — Accessible name / role

| Element       | Variant    | Role     | Accessible name (source)                                                     | States / properties                               |
| ------------- | ---------- | -------- | ---------------------------------------------------------------------------- | ------------------------------------------------- |
| Row           | table      | `row`    | "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on"      | `aria-rowindex`                                   |
| Row           | standalone | `group`  | "BTCUSDT recording" + the same summary as its description                    | —                                                 |
| Reason tag    | both       | text     | "Manual" / "Auto: chart" / "Auto: position" / "Auto: rule" / "Auto: alert"   | —                                                 |
| Why? button   | both       | `button` | "Why is SOLUSDT recorded?"                                                   | `aria-expanded`, `aria-controls`                  |
| State         | both       | text     | the state words ("Recording, stops in 24 minutes")                           | the icon is `aria-hidden`                         |
| Keep forever  | both       | `switch` | "Keep BTCUSDT data forever"                                                  | `aria-checked`                                    |
| Action button | both       | `button` | "Stop recording BTCUSDT" / "Keep recording BTCUSDT" / "Record BTCUSDT again" | `aria-disabled` + `aria-describedby` → the reason |

### Table 4 — Motion pair

| Property                   | motion-safe      | motion-reduce         | Duration / easing tokens |
| -------------------------- | ---------------- | --------------------- | ------------------------ |
| Starting spinner (CMP-014) | CMP-014 rotation | CMP-014 opacity pulse | CMP-014's own            |
| everything else            | none animated    | none animated         | —                        |

### Table 5 — Live data

| Field                    | Politeness                    | Cadence              | Coalescing              | Notes                           |
| ------------------------ | ----------------------------- | -------------------- | ----------------------- | ------------------------------- |
| size, rate, share, since | none (visual only)            | 1 Hz from `recorder` | latest value            | never announced                 |
| state words              | polite, via the page's region | ≤ 1 per 10 s         | latest state per symbol | E16-D02 §9.3                    |
| lingering countdown      | none                          | per minute           | latest                  | "stops in N min", whole minutes |

### Density

| Mode                  | Row / control height                                | Padding tokens         | Smallest target |
| --------------------- | --------------------------------------------------- | ---------------------- | --------------- |
| comfortable (default) | `size.row.comfortable` / `size.control.comfortable` | cells `space.inset.md` | 32 × 32 px      |
| compact               | `size.row.compact` / `size.control.compact`         | cells `space.inset.sm` | 24 × 24 px      |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |
