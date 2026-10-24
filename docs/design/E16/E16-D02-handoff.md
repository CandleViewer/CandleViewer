# E16-D02 — handoff checklist for CMP-177 RecorderStatusRow

SCR-140 changes the CMP-177 contract: a `state` enum and explicit actions replace `recording: boolean` and
`onToggleRecording` (`docs/design/E16/E16-D02.md` §4.2). This ticket therefore attaches the §11.4 checklist
(`docs/plan/16-design-system-brief.md` §11.4, §13.3 item 8). The rest of SCR-140 composes published components
unchanged: CMP-023 stays a `progressbar` (the threshold scale is separate text), CMP-028 is used in its own danger and
info tones, CMP-049 is used as E42-D02's admin grid (D18: one tab stop, roving tabindex, ↑ ↓ rows, ← → cells), and
CMP-055 shows active filter chips plus "Add filter". Their own checklists apply.

## Handoff checklist — CMP-177 RecorderStatusRow (E16-D02, #323)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [x] **Final Penpot link** — page `E16-D02` · id `2f3d2667-6b0f-80a6-8008-d51b2dd0486e`, board `20 CMP-177/states`
      (id `00cd4910-e909-80cf-8008-d68719921682`); PNG `docs/design/E16/img/E16-D02-20-cmp-177-states.png`; every
      board id and PNG in `E16-D02.md` §"Penpot boards".
- [ ] **Variants × States matrix** — every state of the shipped spec is a Penpot variant and a Storybook story; table 1.
      Pending: board 20 draws every story as a composition labelled with its table-1 variant, not as a library variant.
- [x] **Keyboard table** — table variant inside the CMP-049 grid (↑ ↓ rows, ← → into the row's controls); standalone
      variant (SCR-103) as a group of tab stops; a T2 control re-shows its reason on Enter / Space (E16-D02 §10.5); no
      single unmodified key changes recording; `Esc` / `Ctrl+K` untouched; table 2
- [x] **Accessible name / role table** — table 3
- [x] **Live data** — the row's values update at 1 Hz from WS `recorder` and are never announced per tick; state
      changes are announced by the page's single polite region (E16-D02 §9.3), not by the row; table 5
- [x] **Motion pair** — the row animates nothing except CMP-014's spinner in Starting (its own reduced-motion pulse);
      table 4
- [x] **Density notes** — comfortable (admin default): row `size.row.comfortable`, controls `size.control.comfortable`;
      compact: `size.row.compact`, `size.control.compact`; smallest hit target 32 × 32 px comfortable (the Why?
      button and the switch at table size; CMP-002 asks 44: E16-D02 D-17), 24 × 24 px compact; density table below
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — Tier-2/Tier-3 only, as listed in `E16-D02.md` §11.1; none invented; Penpot token sets =
      `packages/ui/tokens` at the PR base, which includes #3925's retune of the light danger tone (E16-D02 §10.4
      finding 2); a T2 action (E16-D02 §10.5): fill `color.surface.raised` + `color.border.default`, label and CMP-019
      `lock` `color.text.tertiary`, reason `color.text.secondary`, never `color.text.disabled` or `opacity.disabled`
- [x] **Data contract confirmed** — REST `GET /recording/symbols`, `RecordingStatus`, `StorageUsage`; WS `recorder`
      §15.8; the recording-status amendment (`lingering`, `linger_until`, `refusal`, `level`, `write_gate`,
      `cap_bytes`, `accelerate_retention`, `role_restricted`, `policy`, the `backpressure_drop` gap reason and the
      add-reason rule). Merged: #3951 and #3955 (both 2026-10-20), 24 §19.18 (E16-D02 §2, §15)
- [ ] **Contrast and CVD** — every pair is computed in E16-D02 §10.4 and passes. Pending: registering the pairs this
      row introduces in `tools/contrast/pairs.mjs` (status `.strong` icons and `danger.default` on
      `color.surface.raised`; `text.secondary` and the four state icons, `success.default`, `warning.strong`,
      `danger.default` and `info.strong`, on `color.surface.sunken`, which the stale rows use; the T2 label,
      `text.tertiary` on `color.surface.hover`). That is a security-owned `tools/` change,
      which lands with the CMP-177 build (E16-S01) or a small tools PR. The CVD simulation is attached with
      the boards
- [ ] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — on the boards PR
- [ ] **Sign-off** — owner `approved` comment or merged spec PR

### Table 1 — Variants × States

| State (Storybook)     | Penpot variant                                            | Condition                                          | Notes                                                                                                              |
| --------------------- | --------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `Recording`           | CMP-177 · RecorderStatusRow / State=recording             | manual, recording                                  | catalogue name; while its chart is open, Stop T2 `recorder.stop_blocked.chart_manual`                              |
| `Stopped`             | State=stopped                                             | stopped, data kept per retention                   | catalogue name; "Record again" (T2 `recorder.symbol_cap` while `recordAgainBlockedReason` is set)                  |
| `Pinned`              | State=recording, Pinned=true                              | keep forever                                       | catalogue name; Retention "Forever"                                                                                |
| `NearDiskBudget`      | State=recording, Disk=near                                | disk level ≥ 1                                     | catalogue name; "· N % of budget" in words                                                                         |
| `AutoChartOpen`       | State=recording, Reason=chart_open                        | auto, chart open                                   | Stop T2 (E16-D02 §10.5) `recorder.stop_blocked.chart_auto`                                                         |
| `AutoPositionOpen`    | State=recording, Reason=position_open                     | auto, open position                                | Stop T2 (E16-D02 §10.5) `recorder.stop_blocked.position_auto` (INV-B11-a)                                          |
| `ManualWithPosition`  | State=recording, Reason=manual, StopBlocked=position_open | manual symbol with an open position                | Stop T2 (E16-D02 §10.5) `recorder.stop_blocked.position_manual` (refusal `position_open`), never Gated             |
| `Lingering`           | State=lingering                                           | amendment `lingering`                              | "stops in N min"; "Keep recording"                                                                                 |
| `Starting`            | State=starting                                            | initial snapshot                                   | spinner; Stop (T2 with its `recorder.stop_blocked.*` key while a chart or a position is open)                      |
| `Degraded`            | State=degraded                                            | a stream unhealthy                                 | gap count secondary                                                                                                |
| `Gated`               | State=gated                                               | write gate closed, row `refusal` ≠ `position_open` | "Gated · data dropped"                                                                                             |
| `RefusedSymbolCap`    | State=refused, Refusal=symbol_cap                         | 20-symbol limit                                    | no action; Keep forever and Retention "—" (an `idle` entry)                                                        |
| `RefusedDiskPressure` | State=refused, Refusal=disk_pressure                      | level 2 refusal                                    | no action; Keep forever and Retention "—"                                                                          |
| `Silent`              | State=silent                                              | no writes for ≥ 60 s                               | "No writes since …"                                                                                                |
| `Error`               | State=error                                               | error                                              | error text in the row detail; Stop (B11 defers it to the retry)                                                    |
| `Stopping`            | State=stopping                                            | flushing                                           | no action                                                                                                          |
| `ReadOnly`            | State=recording, WriteReason=owner_only                   | `writeReason` non-null (SCR-103)                   | controls T2 `rbac.owner_only` (`rbac.view_as` while viewing as another user: an inset) through CMP-079, one notice |
| `Standalone`          | State=recording, Variant=standalone                       | outside a table (SCR-103 drawer)                   | group role, tab stops (tables 2–3)                                                                                 |
| `Stale`               | State=recording, Stale=true                               | no `recorder` frame for 2 s                        | sunken background, "stale" tag, words kept; name adds "stale"                                                      |

### Table 2 — Keyboard

| Key                           | Variant    | Action                                                                                                                                                                                                 | Focus after                               | Global conflict?                 |
| ----------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- | -------------------------------- |
| ↑ ↓ · ← → · Home / End        | table      | the CMP-049 grid (one tab stop, roving tabindex): ↑ ↓ rows; ← → the row's controls (Why? → Keep forever → the action); Home / End: the first / last row (on a control, the row's first / last control) | the row or the control                    | none (grid-local)                |
| Tab / Shift+Tab               | table      | enters or leaves the grid                                                                                                                                                                              | the grid's current row / the next control | none                             |
| Tab / Shift+Tab               | standalone | the row's controls in order: Why? → Keep forever → the action                                                                                                                                          | the control                               | none                             |
| Enter                         | table      | on the row: open the row detail; on a button: activate                                                                                                                                                 | drawer heading / dialog                   | none                             |
| Space                         | both       | on Keep forever: open the confirmation; step-up runs on submit                                                                                                                                         | the dialog                                | none                             |
| Enter / Space on a T2 control | both       | nothing opens or is sent; the reason is re-shown (in the table, the echo) and announced once, politely                                                                                                 | the control                               | none                             |
| Esc                           | both       | close a popover, the T2 echo, a dialog or the row detail                                                                                                                                               | the control that opened it                | keeps its global meaning (close) |

### Table 3 — Accessible name / role

| Element          | Variant    | Role                                           | Accessible name (source)                                                      | States / properties                                                                                                                      |
| ---------------- | ---------- | ---------------------------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Row              | table      | `row` in the CMP-049 `grid` (cells `gridcell`) | "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on"       | `aria-rowindex`                                                                                                                          |
| Row              | standalone | `group`                                        | "BTCUSDT recording" + the same summary as its description                     | —                                                                                                                                        |
| Reason tag       | both       | text                                           | "Manual" / "Auto: chart" / "Auto: position" / "Auto: rule" / "Auto: alert"    | —                                                                                                                                        |
| Why? button      | both       | `button`                                       | "Why is SOLUSDT recorded?"                                                    | `aria-expanded`, `aria-controls`                                                                                                         |
| State            | both       | text                                           | the state words ("Recording, stops in 24 minutes")                            | the icon is `aria-hidden`                                                                                                                |
| Keep forever     | both       | `switch`                                       | "Keep BTCUSDT data forever"                                                   | `aria-checked`                                                                                                                           |
| Action button    | both       | `button`                                       | "Stop recording BTCUSDT" / "Keep recording BTCUSDT" / "Record BTCUSDT again"  | T2 (E16-D02 §10.5): `aria-disabled`, never `disabled`; `aria-describedby` → the reason node (at mount); a CMP-019 `lock` leads the label |
| Read-only notice | standalone | text                                           | "Read-only — only the owner can change recording." (`notice.panel_read_only`) | the `aria-describedby` target of every gated control in `ReadOnly`                                                                       |

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
