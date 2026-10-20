# E16-D02 — handoff checklist for CMP-177 RecorderStatusRow

SCR-140 changes the CMP-177 contract (a `state` enum and explicit actions replace `recording: boolean` and
`onToggleRecording`; `docs/design/E16/E16-D02.md` §4.2), so this ticket attaches the §11.4 checklist
(`docs/plan/16-design-system-brief.md` §11.4, §13.3 item 8). The rest of SCR-140 composes published components and
links their own checklists.

## Handoff checklist — CMP-177 RecorderStatusRow (E16-D02, #323)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — file CandleViewer DS, page `E16-D02 SCR-140 Recorder`, board `CMP-177 · RecorderStatusRow — states`:
      link and PNGs in `E16-D02.md` §"Penpot boards"; PNG per state under `docs/design/E16/img/CMP-177-<state>.png`
- [ ] **Variants × States matrix** — every state of the shipped spec is a Penpot variant and a Storybook story; table 1
- [x] **Keyboard table** — row inside the CMP-049 grid pattern (WAI-ARIA APG grid); no single unmodified key changes
      recording; `Esc` / `Ctrl+K` untouched; table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — the row's values update at 1 Hz from WS `recorder`, never announced per tick; state changes are
      announced by the page's single polite region (E16-D02 §9.3), not by the row; table 5
- [x] **Motion pair** — the row animates nothing; the share bar jumps (only the page's disk meter tweens); table 4
- [x] **Density notes** — compact: row `size.row.compact`, controls `size.control.compact`; comfortable: `size.row.comfortable`,
      `size.control.comfortable`; smallest hit target 24 × 24 px in both (the Keep forever switch and the "Why?" button)
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Tier-2/Tier-3 only, as listed in `E16-D02.md` §11.1; none invented; Penpot token sets =
      `packages/ui/tokens` at the PR base
- [ ] **Data contract confirmed** — REST `GET /recording/symbols`, WS `recorder` §15.8, plus the recording-status
      amendment fields (`lingering`, `linger_until`, `level`, `write_gate`, `cap_bytes`, `refusal`, `role_restricted`)
      and the proposed `policy` object (E16-D02 §15 D-1): pending the amendment PR
- [x] **Contrast and CVD** — computed for every pair the row uses (E16-D02 §10.4); state words in `color.text.primary`,
      tone on the icon; no meaning depends on hue alone
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — on the PR
- [ ] **Sign-off** — owner `approved` comment or merged spec PR

### Table 1 — Variants × States

| State (Storybook)      | Penpot variant                                    | Condition                                  | Notes                                             |
| ---------------------- | ------------------------------------------------- | ------------------------------------------ | ------------------------------------------------- |
| `Recording`            | CMP-177 · RecorderStatusRow / State=recording      | manual, recording                          | catalogue name                                    |
| `Stopped`              | State=stopped                                      | stopped, data kept until a date            | catalogue name; "Record again"                    |
| `Pinned`               | State=recording, Pinned=true                       | keep forever                               | catalogue name; Retention "Forever"               |
| `NearDiskBudget`       | State=recording, Disk=near                         | disk level ≥ 1                             | catalogue name; share bar warning + "% of budget" |
| `AutoChartOpen`        | State=recording, Reason=chart_open                 | auto, chart open                           | Stop disabled with reason                         |
| `AutoPositionOpen`     | State=recording, Reason=position_open              | auto, open position                        | Stop disabled with reason (INV-B11-a)             |
| `Lingering`            | State=lingering                                    | amendment `lingering`                      | "stops in N min"; "Keep recording"                |
| `Starting`             | State=starting                                     | initial snapshot                           | spinner; Stop disabled                            |
| `Degraded`             | State=degraded                                     | gaps                                       | "Restart feed" in the row menu                    |
| `Gated`                | State=gated                                        | level 3, no position                       | "Gated · data dropped"                            |
| `RefusedSymbolCap`     | State=refused, Refusal=symbol_cap                  | 20-symbol limit                            | no action                                         |
| `RefusedDiskPressure`  | State=refused, Refusal=disk_pressure               | level 2 refusal                            | no action                                         |
| `Silent`               | State=silent                                       | no writes ≥ 60 s                           | "Restart feed"                                    |
| `Error`                | State=error                                        | error                                      | "Restart feed"                                    |
| `ReadOnly`             | State=recording, CanWrite=false                    | Manager                                    | no controls                                       |

### Table 2 — Keyboard

| Key                | Action                                                              | Focus after                     | Global conflict?                       | Notes                                   |
| ------------------ | ------------------------------------------------------------------- | ------------------------------- | -------------------------------------- | --------------------------------------- |
| Arrow Up / Down    | previous / next row (grid)                                          | the row                         | none (grid-local, APG)                 | rows are focusable                      |
| Arrow Left / Right | previous / next interactive cell in the row                         | the cell's control              | none                                   | depth, retention, keep forever, actions |
| Enter              | on the row: open the row detail; on a button: activate              | detail's first item / dialog    | none                                   | —                                       |
| Space              | on Keep forever: toggle (pin on → step-up; off → confirmation)      | the switch, or the dialog       | none                                   | never toggles from the row itself       |
| Esc                | close a popover or the row detail                                   | the control that opened it      | `Esc` keeps its global meaning (close) | —                                       |

### Table 3 — Accessible name / role

| Element        | Role                       | Accessible name (source)                                                          | States / properties                                                    |
| -------------- | -------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Row            | `row`                      | "BTCUSDT, manual, recording since 1 Sep 2026, 9.9 GB, keep forever on" (computed) | `aria-rowindex`                                                        |
| Reason badge   | text in a `gridcell`       | "Manual" / "Auto, chart open" / "Auto, position open"                             | —                                                                      |
| Why? button    | `button`                   | "Why is SOLUSDT recorded?"                                                        | `aria-expanded`, `aria-controls`                                       |
| State          | text in a `gridcell`       | the state words ("Recording, stops in 24 minutes")                                | the icon is `aria-hidden`                                              |
| Keep forever   | `switch`                   | "Keep BTCUSDT data forever"                                                       | `aria-checked`                                                         |
| Depth          | `combobox`                 | "Order-book depth for BTCUSDT"                                                    | options 1, 50, 200, 500                                                |
| Retention      | `combobox`                 | "Retention for BTCUSDT"                                                           | —                                                                      |
| Stop           | `button`                   | "Stop recording BTCUSDT"                                                          | `aria-disabled` + `aria-describedby` → the reason                      |
| Share bar      | `meter`                    | "BTCUSDT share of the disk budget"                                                | `aria-valuetext` "9.9 GB, 5 % of the 200 GB budget"                   |

### Table 4 — Motion pair

| Property   | motion-safe   | motion-reduce | Duration / easing tokens |
| ---------- | ------------- | ------------- | ------------------------ |
| none       | none animated | none animated | —                        |

### Table 5 — Live data

| Field                         | Politeness                      | Cadence             | Coalescing                    | Notes                                   |
| ----------------------------- | ------------------------------- | ------------------- | ----------------------------- | --------------------------------------- |
| rate, size, share, since      | none (visual only)              | 1 Hz from `recorder` | latest value                  | never announced                         |
| state word                    | polite, via the page's region   | ≤ 1 per 10 s        | latest state per symbol       | E16-D02 §9.3                            |
| lingering countdown           | none                            | per minute          | latest                        | "stops in N min", minute resolution     |

### Density

| Mode        | Row / control height                                  | Padding tokens                       | Smallest target |
| ----------- | ----------------------------------------------------- | ------------------------------------ | --------------- |
| compact     | `size.row.compact` / `size.control.compact`           | cells `space.inset.sm`               | 24 × 24 px      |
| comfortable | `size.row.comfortable` / `size.control.comfortable`   | cells `space.inset.md`               | 24 × 24 px      |

### Essential exceptions

| Exception | Compensating control | Reviewer | Date |
| --------- | -------------------- | -------- | ---- |
| none      | —                    | —        | —    |
