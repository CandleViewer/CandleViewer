# E17-D02 — Per-component handoff checklist (`16` §11.4; CMP-076, CMP-077, CMP-078, CMP-092)

Four blocks (one per component; every line of the `16` §11.4 block kept), then Tables 1–5, the Density table and the Essential-exceptions table **once each with a leading `Component` column** so every component's rows are present without four copies (deviation recorded in `E17-D02.md` §19 item 7; the fallback is per-component tables). The Penpot line follows the page-ref rule (page name + page id; never a hostname, team or file id, or a workspace URL) and reads BLOCKED-PENPOT until hpe-worker-1 draws the boards. Spec: `docs/design/E17/E17-D02.md`; tokens: `packages/ui/tokens` at `2f01564958868412c7236378d13113db91957788`; matrix: `docs/design/_tools/e17_d02_token_audit.py` (44 rows, 37 gated, 0 FAIL).

## Handoff checklist — CMP-076 ConnectionStatus (E17-D02, #325)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E17-D02 Connection-state components` (page id pinned after the first build), specimens `CMP-076 · ConnectionStatus` on this ticket's own page (never the DS library file); PNG per state planned at `docs/design/E17/img/E17-D02-05-cmp-076-chip.png` and `docs/design/E17/img/E17-D02-09-themes-greyscale.png`
- [ ] **Variants × States matrix** — PENDING (a Penpot variant exists only once the boards are drawn, BLOCKED-PENPOT): 2 densities × 5 states (+ strong, connecting, upstream-down, stale-server, resync-storm details) × 7 render states (spec §5); Table 1 below
- [x] **Keyboard table** — `Tab`, `Enter` / `Space` (popover), `Esc` (innermost-cancel); no view-local override, no single unmodified key, `Esc` / `Ctrl+K` untouched (spec §13); Table 2
- [x] **Accessible name / role table** — native `<button>`, "Connection: Stale 7 seconds, last data 13:42:05 UTC", `aria-describedby`, `aria-haspopup="dialog"`; the chip owns no live region (spec §5); Table 3
- [x] **Live data** — age and latency `aria-live="off"`, ≤1 Hz, latest value only; the state announcements are the SCR-152 region's (spec §5, §11); Table 5
- [x] **Motion pair** — none animated: every state change is a class flip in both modes (spec §12 row 14); Table 4
- [x] **Density notes** — compact: a 20 px pill in the 24 px row (`size.control.compact`) padded to a 24 × ≥72 px target; comfortable: a 24 px pill in the 32 px row (spec §5); Density table
- [x] **Essential-exceptions log** — none (the target is reached by padding)
- [x] **Tokens used** — `color.text.primary`, `color.surface.raised` / `.hover`, `color.status.{danger,warning,info}.{subtle,strong}`, `color.status.info.default`, `color.data-confidence.{live,stale}.indicator`, `color.border.default`, `color.focus.ring`, `radius.badge`, `border.hairline` / `.focus`, `size.control.{compact,comfortable}`, `size.target.min`, `size.icon.sm`, `space.inset.{xs,sm}`, `type.ui.{caption,label}`, `font.family.{ui,mono}`, `elevation.popover` = the `15` CMP-076 Tokens field; none invented; Penpot token sets = `packages/ui/tokens` at `2f01564958868412c7236378d13113db91957788`
- [x] **Data contract confirmed** — the shipped `TransportState`, `Link`, `TopicStatus` (`apps/web/src/lib/ws/state/types.ts`), `connection_quality` and `exchange_state` (`23` §8.3, §15.9 `NEUTRAL_FIELDS`), `snap` `meta.stale` (`23` §7.2); the §3 selector is PROPOSED (Q4 of `types.ts`)
- [ ] **Contrast and CVD** — PENDING (the PROPOSED `pairs.mjs` rows are registered by E17-T04, CR-6; CVD planned on the exports): spec §14.1: word 14.35 / 15.62 / 16.25 on the bar, stale glyph 11.00 / 4.11 / 11.00, danger glyph on the danger fill 7.83 / 3.85 / 7.83, Delayed glyph 4.64 / 3.44 / 4.64, focus ring 6.66 / 5.86 / 17.30, all PASS; the `connection-reconnecting` indicator on the bar rejected at 2.9992 (light); PROPOSED rows: `color.data-confidence.stale.indicator` on `color.surface.raised`, `color.status.danger.strong` on `color.status.danger.subtle`, `color.status.warning.strong` on `color.status.warning.subtle`, `color.status.info.default` on `color.status.info.subtle`, `color.text.primary` on `color.surface.hover`; CVD planned (`cvd_sim.py`), non-colour encodings in spec §14.3
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B below
- [ ] **Sign-off** — owner approval pending (owner `approved` comment or merged spec PR)

## Handoff checklist — CMP-077 ReconnectOverlay (E17-D02, #325)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E17-D02 Connection-state components` (page id pinned after the first build), specimens `CMP-077 · ReconnectOverlay`; PNG planned at `docs/design/E17/img/E17-D02-06-cmp-077-region.png` and `docs/design/E17/img/E17-D02-02-scr-152-workspace.png`
- [ ] **Variants × States matrix** — PENDING (Penpot variants once the boards are drawn, BLOCKED-PENPOT): 2 Details instances × 9 states (spec §6); Table 1
- [x] **Keyboard table** — `Retry now`, `Sign in` (`session-ended`) and `Details` in the Tab order, `Enter` / `Space`, `Esc` closes Details or dismisses `recovered`; the `Ctrl+\` cycle stop is PROPOSED (Q9); **no trap**; the state change never moves focus, and the inline variant moves focus only on a submitted sign-in failure (spec §4.3, §6, §13); Table 2
- [x] **Accessible name / role table** — `role="region"` "Connection"; the CMP-028 `connection-disconnected` callout `role="alert"` once; two buttons; the countdown `aria-live="off"` (spec §6); Table 3
- [x] **Live data** — the countdown and age 1 Hz text swaps, `aria-live="off"`; the connection announcements per spec §11 rows 1, 12, 13, 14 (assertive once per `transitionSeq`); the Read-only instance's row 2 for the region's reasons only (the §6 routing table); Table 5
- [x] **Motion pair** — content and fill flip at 0 ms; the `recovered` dismissal `fast` / `accelerate` → cut; no spinner (spec §12 rows 1–7, 16; PROPOSED against E08-D11); Table 4
- [x] **Density notes** — the region is 96 px in both densities (E08-D03 §2 reused); the pill 24 px tall, the link's hit box 24 px (spec §4.1, §13); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.{danger,warning,success}.{subtle,strong}`, `color.text.{primary,secondary,inverse,link,on-action}`, `color.action.primary.default`, `color.focus.ring`, `radius.control`, `border.thick` / `.focus`, `size.icon.md`, `space.inset.sm`, `type.ui.{body,body-strong}`, `elevation.chrome`, `motion.duration.{instant,fast}`, `motion.easing.accelerate` = the `15` CMP-077 Tokens field; `elevation.5` / `elevation.scrim` and the `color.surface.scrim` alias are not this component's (CR-2, CR-3); Penpot token sets = `packages/ui/tokens` at `2f01564958868412c7236378d13113db91957788`
- [x] **Data contract confirmed** — `Link.reconnecting.attempt` / `nextAttemptAtMs`, `Link.offline.cause`, `bye.reconnect` (`23` §4.4: `false` → the `session-ended` state, `Sign in`, no retry), `shutdown_notice` (`message`, `closing_in_ms`, `expected_downtime_ms` → `countdownMs`, `23` §9.4), `bye.reason` and the close code (`23` §4.4), the client's `diagnostics` behind Copy details; the Details split uses only `NEUTRAL_FIELDS` for Manager / Viewer
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows registered by E17-T04, CR-6; CVD planned): spec §14.1: title 12.06 / 14.64 / 13.66 (registered), body 7.40 / 8.42 / 12.06, glyph and border 7.83 / 3.85 / 7.83, Retry now fill 3.06 / 3.87 / 5.59 (E08-D03 §6 reproduced), Retry label 4.76 / 4.76 / 7.45, Details 5.59 / 5.50 / 5.59, long-outage text 10.42 / 4.73 / 10.42, all PASS; rejected: the filled pill (2.56 / 1.01 / 1.40) and the link (1.40 / 1.43 / 1.40) on the strong fill — outlined pill and underlined link in `color.text.inverse` instead; the CMP-028 accents on the fill (2.88 dark / 2.81 light); PROPOSED rows: `color.text.secondary`, `color.text.link`, `color.focus.ring`, `color.action.primary.default`, `color.status.danger.strong` on `color.status.danger.subtle`; the warning and success counterparts; `color.text.inverse` on `color.status.danger.strong`; CVD planned
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-078 StaleDataShade (E17-D02, #325)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E17-D02 Connection-state components` (page id pinned after the first build), specimens `CMP-078 · StaleDataShade`; PNG planned at `docs/design/E17/img/E17-D02-07-cmp-078-shade.png` and `docs/design/E17/img/E17-D02-03-scr-152-in-panel.png`
- [ ] **Variants × States matrix** — PENDING (Penpot variants once the boards are drawn, BLOCKED-PENPOT): 2 variants (panel, grid row) × 5 states (spec §7); Table 1
- [ ] N/A — **Keyboard table**: the shade has no interactive element; its text is the panel's accessible description and focus is never moved by it (`05` §3.4 item 3; spec §13)
- [x] **Accessible name / role table** — `aria-hidden` shade; text exposed via `aria-describedby` on the panel region ("Stale, last update 7 seconds ago"); `role="img"` canvases keep their summary; the `Alt+T` table alternative carries the same state word and age (E11-D04 D15; spec §7); Table 3
- [x] **Live data** — the age text ≤1 Hz, `aria-live="off"`; stale enter / exit polite once at panel level; Stale ≥ T2 one assertive sentence per episode (spec §11 rows 4, 5); Table 5
- [x] **Motion pair** — the settle plays once (`opacity` 0 → 0.15 over `normal` / `standard`, instant under reduce); T2 and the scrims are flips; the scrim lifts in the `snap` frame; **the shade never pulses** (spec §12 rows 8–12, 17); Table 4
- [x] **Density notes** — the strip row 24 px (compact) / 32 px (comfortable); the chip as CMP-076's pill sizes; no target of its own (spec §7); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.data-confidence.stale.{text,indicator,surface}`, `color.data-confidence.resyncing.indicator`, `color.surface.overlay`, `opacity.scrim`, `elevation.scrim`, `color.status.warning.{subtle,strong}`, `color.text.{primary,secondary}`, `border.thick`, `type.ui.{caption,body-strong}`, `font.family.mono`, `motion.duration.{normal,fast,instant}`, `motion.easing.{standard,accelerate}` = the `15` CMP-078 Tokens field; `color.overlay.stale` and `color.surface.scrim` are requested aliases (CR-1, CR-2), never bound; Penpot token sets = `packages/ui/tokens` at `2f01564958868412c7236378d13113db91957788`
- [x] **Data contract confirmed** — `TopicStatus` (`stale`, `resyncing`), the per-topic age against T1 / T2, `snap` `meta.stale` + `ts`, the `snap` `reason` classes (`23` §7.2, §7.4), `exchange_state.affected_symbols`; pure chrome otherwise
- [ ] **Contrast and CVD** — PENDING (CVD planned on the exports; the composites cannot be `pairs.mjs` rows): spec §14.1: the word over the 15 % dim 15.60 / 16.17 / 17.66, the indicator over the dim 11.96 / 4.25 / 11.96, "Mark 8s old" over the dimmed grid 9.15 / 8.74 / 14.92, the scrim label 14.05 / 15.34 / 15.91, the resyncing indicator on the scrim 9.56 / 4.31 / 9.56, the strip 9.86 / 15.62 / 11.16 (registered) and its glyph 7.56 / 4.11 / 7.56, all PASS; PROPOSED rows: `color.status.warning.strong` on `color.status.warning.subtle`; CVD planned
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

## Handoff checklist — CMP-092 DegradedModeBanner (E17-D02, #325)

Rule: every line is `[x]` with its evidence, or `[ ] N/A — <reason>`. No blank line at Done
(docs/plan/16-design-system-brief.md §11.4, §13.3).

- [ ] **Final Penpot link** — BLOCKED-PENPOT: page `E17-D02 Connection-state components` (page id pinned after the first build), specimens `CMP-092 · DegradedModeBanner`; PNG planned at `docs/design/E17/img/E17-D02-08-cmp-092-banner.png`
- [ ] **Variants × States matrix** — PENDING (Penpot variants once the boards are drawn, BLOCKED-PENPOT): single / multiple × 3 severities × dismissed-reappears (spec §8); Table 1
- [x] **Keyboard table** — each row's CMP-210 chip then its dismiss control, `Enter` / `Space`; no new key (spec §13); Table 2
- [x] **Accessible name / role table** — `role="status"` rows (info, warning), `role="alert"` once for a blocking row; the dismiss control named "Dismiss <message>" (spec §8); Table 3
- [x] **Live data** — one polite announcement per row on entry within the ≤1 per 5 s budget; a blocking row assertive once; a dismissed row returns only on a new `system` frame (spec §8, §11 rows 5, 16; the §6 routing table — one reason → one surface); Table 5
- [x] **Motion pair** — rows enter as flips and dismiss over `fast` / `accelerate` → cut (spec §12 row 15, PROPOSED); Table 4
- [x] **Density notes** — row height 24 px (compact) / 32 px (comfortable); the chip and the dismiss control 24 × 24 in both (spec §8, §13); Density table
- [x] **Essential-exceptions log** — none
- [x] **Tokens used** — `color.status.{info,warning,danger}.{subtle,strong}`, `color.status.info.default`, `color.text.{primary,secondary}`, `color.surface.raised`, `color.focus.ring`, `space.stack.sm`, `space.inset.sm`, `size.target.min`, `type.ui.{body,caption}`, `motion.duration.{instant,fast}` = the `15` CMP-092 Tokens field; the bare `color.status.warning` resolved to the triad (CR-5); Penpot token sets = `packages/ui/tokens` at `2f01564958868412c7236378d13113db91957788`
- [x] **Data contract confirmed** — `system` `exchange_state` (`public_ws`, `affected_symbols`), `health` (`components[]` without `detail`, `health`), `notice` (`reason`), `maintenance.enabled` — the `NEUTRAL_FIELDS` subset of the `system` kinds (`23` §15.9); the per-account D17 condition from the private `wallet` topic's `WalletUpdate.health[]` per `exchange_account_id` (`23` §15.4, account-scoped — not a `system` kind); the E04 ingestion-lag issue's producer is E04's
- [ ] **Contrast and CVD** — PENDING (PROPOSED `pairs.mjs` rows registered by E17-T04, CR-6; CVD planned): spec §14.1: warning row 9.86 / 15.62 / 11.16 (registered) and 6.05 / 8.98 / 9.86, info row 10.74 / 15.44 / 12.16 (registered) and 6.59 / 8.88 / 10.74, blocking row 12.06 / 14.64 / 13.66 (registered) and 7.40 / 8.42 / 12.06, the glyphs 7.56 / 4.11 / 7.56, 4.64 / 3.44 / 4.64, 7.83 / 3.85 / 7.83, the CMP-210 chip glyphs 11.00 / 4.11 / 11.00 and 9.32 / 4.11 / 9.32, all PASS; PROPOSED rows: `color.text.secondary` on the three `.subtle` fills, the three `.strong` glyphs on their fills, `color.status.warning.strong` and `color.status.danger.strong` on `color.surface.raised`; CVD planned
- [x] **Design QA checklist (16 §12)** and the **a11y acceptance-criteria template (05 §10)** attached — sections A and B
- [ ] **Sign-off** — owner approval pending

### Table 1 — Variants × States

| Component | Variant                                         | State (every one is a Penpot variant and a story)                                                                                                                                  | Penpot variant (name pattern)                                         | Story name(s)                                                                                                                                                                   | Notes                                                                                         |
| --------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| CMP-076   | compact · comfortable (Density)                 | live, delayed, stale, stale-strong (T2), reconnecting, offline, connecting, upstream-down, stale-server, resync-storm × default, hover, focus-visible, tooltip-open, hc, greyscale | `CMP-076 · ConnectionStatus / State=Delayed, Density=Compact` …       | Live, Delayed, Stale, StaleEscalated, StaleServer, UpstreamDown, Reconnecting, Offline, Compact, Comfortable, TooltipOpen, HighContrast, Greyscale                              | the glyph set ✓ ◐ ⚠ ↻ ✕; `lagging` is a tooltip, not a state; Read-only is never a chip state |
| CMP-077   | Owner Details · Manager / Viewer Details (Role) | reconnecting, retrying-now, unstable, offline (a fatal close / a shell cause), session-ended, 30-s-step, long-outage, recovered, read-only × default, focus-visible, hc, greyscale | `CMP-077 · ReconnectOverlay / State=Reconnecting, Role=Owner` …       | Reconnecting, OfflineFatal, OfflineUnreachable, SessionEnded, Recovered, LongOutage, ReadOnlyShutdown, ReadOnlyKillSwitch, DetailsOwner, DetailsViewer, Keyboard, ReducedMotion | non-modal region; no `alertdialog`; `session-ended` offers Sign in, never a retry             |
| CMP-078   | panel · grid row (Variant)                      | fresh, stale, escalated, stale-server, disconnected (+ resyncing label)                                                                                                            | `CMP-078 · StaleDataShade / State=Escalated, Variant=Panel` …         | Fresh, Stale, Escalated, StaleServer, Disconnected, ReducedMotion                                                                                                               | `fresh` renders nothing                                                                       |
| CMP-092   | single · multiple (Issues)                      | info, warning, blocking, dismissed-reappears × default, focus-visible, hc                                                                                                          | `CMP-092 · DegradedModeBanner / Severity=Blocking, Issues=Multiple` … | SingleIssue, MultipleIssues, Blocking, DismissedReappears, HighContrast                                                                                                         | Delayed, Disconnected and Resyncing are never issues here                                     |

### Table 2 — Keyboard

| Component        | Key                 | Action                                                                | Focus after                                             | Global conflict?                                                | Notes                                   |
| ---------------- | ------------------- | --------------------------------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------- |
| CMP-076          | `Tab` / `Shift+Tab` | reach the chip                                                        | the chip; tooltip on focus                              | none                                                            | one stop in the TopBar order            |
| CMP-076          | `Enter` / `Space`   | open the details popover                                              | the popover; back to the chip on close                  | none (not in the `05` §3.2 map; not trading-critical)           | APG button + disclosure                 |
| CMP-076          | `Esc`               | close the popover (innermost-cancel)                                  | stays on the chip                                       | `Esc` reserved, never swallowed                                 | —                                       |
| CMP-077          | `Tab` / `Shift+Tab` | `Retry now`, then `Details`                                           | the control                                             | none                                                            | no trap; SCR-063 stays reachable        |
| CMP-077          | `Enter` / `Space`   | retry now (one manual handshake) / sign in / open Details             | the pill / the sign-in form / the panel's first control | none                                                            | the title swaps on retry                |
| CMP-077          | `Esc`               | close Details; dismiss `recovered` (≥10 s)                            | `Details` / the dismissing control or the next stop     | `Esc` innermost-cancel                                          | —                                       |
| CMP-077          | `Ctrl+\`            | region cycling reaches "Connection" — PROPOSED (Q9)                   | the region's first control                              | none — an extension of the `05` §3.4 item 1 list, not a new key | the landmark list reaches it either way |
| CMP-077 (inline) | —                   | SCR-001: focus moves to the alert only when a submitted sign-in fails | the alert; unchanged on a reachability flip             | none                                                            | `05` §3.4 item 3                        |
| CMP-078          | —                   | N/A — no interactive element                                          | never moved by the shade                                | none                                                            | `05` §3.4 item 3                        |
| CMP-092          | `Tab` / `Shift+Tab` | each row's CMP-210 chip, then its dismiss control                     | the control                                             | none                                                            | —                                       |
| CMP-092          | `Enter` / `Space`   | open the admin screen / dismiss the row                               | the screen / the next row's chip or the next stop       | none                                                            | the chip is absent without `admin:read` |

### Table 3 — Accessible name / role

| Component | Element                                    | Role                                             | Accessible name (source)                                                                                      | States / properties                                                                                                   |
| --------- | ------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| CMP-076   | the chip                                   | button (native `<button>`)                       | "Connection: Stale 7 seconds, last data 13:42:05 UTC" (visible text first, SC 2.5.3)                          | `aria-describedby` → tooltip; `aria-haspopup="dialog"`; no live region; age / latency `aria-live="off"`               |
| CMP-076   | the popover                                | dialog (non-modal)                               | "Connection details"                                                                                          | the numbers as text; `Esc` closes                                                                                     |
| CMP-077   | the region                                 | `region`                                         | "Connection" (`aria-label`)                                                                                   | reachable with `Ctrl+\`; never traps                                                                                  |
| CMP-077   | the callout inside it                      | CMP-028 `connection-disconnected` → `alert`      | the §11 row 1 / 12 / 13 / 14 sentence                                                                         | fires once per `transitionSeq` change; static afterwards                                                              |
| CMP-077   | `Retry now`; `Sign in`; `Details`; Dismiss | button; button; button (`aria-expanded`); button | visible labels; "Dismiss"                                                                                     | the countdown beside them `aria-live="off"` (CMP-035); `Sign in` only in `session-ended`, where `Retry now` is absent |
| CMP-078   | the shade                                  | none (`aria-hidden`)                             | — (the panel's `aria-describedby` reads "Stale, last update 7 seconds ago" / "Disconnected, last data 00:12") | the strip sentence is read once with the per-episode announcement                                                     |
| CMP-092   | an issue row                               | `status` (info, warning) / `alert` (blocking)    | the message + stillWorks sentence                                                                             | one announcement per row on entry; dismissed-for-the-episode                                                          |
| CMP-092   | the CMP-210 chip; the dismiss control      | button; button                                   | the chip's `label` + `tooltip`; "Dismiss <message>"                                                           | `aria-disabled` + reason where role-gated                                                                             |

### Table 4 — Motion pair

| Component | Property                        | motion-safe                                                                                   | motion-reduce | Duration / easing tokens                           |
| --------- | ------------------------------- | --------------------------------------------------------------------------------------------- | ------------- | -------------------------------------------------- |
| CMP-076   | none animated                   | every state change is a class flip; age text swaps ≤1 Hz                                      | identical     | `motion.duration.instant`                          |
| CMP-077   | content, fill, title            | flips at 0 ms; title swaps ≤1 / s, latched under T5                                           | identical     | `motion.duration.instant`                          |
| CMP-077   | `recovered` dismissal           | `opacity` 1 → 0 over `fast` / `accelerate`, then one slot flip                                | a cut         | `motion.duration.fast`, `motion.easing.accelerate` |
| CMP-078   | the stale settle                | overlay `opacity` 0 → 0.15 over `normal` / `standard`; exit 0.15 → 0                          | both instant  | `motion.duration.normal`, `motion.easing.standard` |
| CMP-078   | the resync / disconnected scrim | enter: flip to `opacity.scrim`; lift: 0.6 → 0 over `fast` in the `snap` frame; the block cuts | lift as a cut | `motion.duration.fast`, `motion.easing.accelerate` |
| CMP-078   | the shade while stale           | **never animates** (D16 / M20)                                                                | identical     | —                                                  |
| CMP-092   | issue row enter / dismiss       | enter: flip; dismiss: `opacity` 1 → 0 over `fast` / `accelerate`                              | a cut         | `motion.duration.fast`, `motion.easing.accelerate` |

### Table 5 — Live data

| Component | Field                                                 | Politeness                                            | Cadence                                                                                       | Coalescing                                  | Notes                                        |
| --------- | ----------------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------- |
| CMP-076   | age; latency                                          | none (`aria-live="off"`)                              | ≤1 Hz                                                                                         | latest value only                           | D18; never announced                         |
| CMP-076   | state change                                          | none on the chip                                      | on `transitionSeq`                                                                            | —                                           | the region announces (§11)                   |
| CMP-077   | Disconnected entry; retry stopped; recovery; unstable | assertive / assertive (PROPOSED) / assertive / polite | once per `transitionSeq` change; recovery once when the private snapshots and `system` are in | —                                           | §11 rows 1, 14, 12, 13                       |
| CMP-077   | Read-only reason                                      | assertive                                             | once per reason change                                                                        | the latest reason                           | §11 row 2 (the region's reasons; §6 routing) |
| CMP-077   | countdown; age                                        | none (`aria-live="off"`)                              | 1 Hz text swap                                                                                | —                                           | CMP-035                                      |
| CMP-078   | stale enter / exit (< T2); stale-server; resync       | polite, panel level                                   | once on entry, once on exit                                                                   | flaps collapsed in 5 s                      | §11 row 5                                    |
| CMP-078   | Stale ≥ T2                                            | assertive                                             | once per episode, ≤1 per 5 s                                                                  | every symbol crossing in 5 s → one sentence | §11 row 4                                    |
| CMP-078   | age text                                              | none                                                  | ≤1 Hz                                                                                         | latest                                      | —                                            |
| CMP-092   | info / warning row                                    | polite (`role="status"`)                              | once on entry; ≤1 per 5 s shared                                                              | per row                                     | §11 row 5                                    |
| CMP-092   | blocking row                                          | assertive (`role="alert"`)                            | once per issue entry (again after a dismissal)                                                | —                                           | §11 row 16 (never also row 2)                |

### Density

| Component | Mode        | Row / control height                                   | Padding tokens                                                             | Smallest target             |
| --------- | ----------- | ------------------------------------------------------ | -------------------------------------------------------------------------- | --------------------------- |
| CMP-076   | compact     | 20 px pill in a 24 px row (`size.control.compact`)     | `space.inset.sm` x; `space.inset.xs` glyph gap; 2 px transparent y padding | 24 × ≥72 px (by padding)    |
| CMP-076   | comfortable | 24 px pill in a 32 px row (`size.control.comfortable`) | `space.inset.sm` x; `space.inset.xs` glyph gap                             | 32 × ≥80 px                 |
| CMP-077   | compact     | region 96 px; pill 24 px; link hit box 24 px           | `space.inset.sm` (the E08-D03 §2 offsets)                                  | 24 × 24 px                  |
| CMP-077   | comfortable | the same (the slot does not change with density)       | the same                                                                   | 24 × 24 px                  |
| CMP-078   | compact     | strip row 24 px                                        | `space.inset.sm`                                                           | — (no target)               |
| CMP-078   | comfortable | strip row 32 px                                        | `space.inset.sm`                                                           | — (no target)               |
| CMP-092   | compact     | issue row 24 px                                        | `space.inset.sm`; `space.stack.sm` between rows                            | chip and dismiss 24 × 24 px |
| CMP-092   | comfortable | issue row 32 px                                        | `space.inset.sm`; `space.stack.sm`                                         | 24 × 24 px                  |

### Essential exceptions

| Component | Exception | Compensating control | Reviewer | Date |
| --------- | --------- | -------------------- | -------- | ---- |
| all four  | none      | —                    | —        | —    |

## A. Design QA checklist (`16` §12) — the four components

- [x] Only published Tier-2 tokens; zero hard-coded hex / px in the spec (the px are anatomy derived from tokens or E08-D03 §2 offsets; the two aliases are PROPOSED requests, CR-1 / CR-2).
- [ ] Verified in all three themes at both densities — the matrix is computed for the three themes (spec §14.1); the visual parity check runs on the boards (BLOCKED-PENPOT).
- [x] Passes the contrast matrix for every pair introduced or touched (37 gated rows, 0 FAIL with the unrounded compare; 6 rejected rows designed around; 21 PROPOSED `pairs.mjs` rows named).
- [ ] CVD simulation reviewed — planned on the exports (`cvd_sim.py`); the non-colour encodings are stated (spec §14.3).
- [ ] Every documented state has a Penpot variant and a story — PENDING the boards (BLOCKED-PENPOT): the variants are planned in Table 1; the 36 stories of spec §15 cover every state.
- [x] Disabled states use disabled-with-reason (CMP-079) — the order ticket while Disconnected / Read-only; the role-gated CMP-210 chip.
- [x] Loading / empty / error states designed explicitly — `connecting`, `fresh` (nothing rendered), the SCR-001 error region (spec §2 rows 1, 7; §7).
- [x] Keyboard-interaction table completed (Table 2); matches the tested path once the stories exist (E17-T04).
- [x] Accessible-name / role table completed (Table 3).
- [x] Canvas-adjacent: the shade over `role="img"` canvases keeps their summary and exposes its text via `aria-describedby` (spec §7); the canvas dim itself is E11-D06 D13's.
- [x] Motion-safe / motion-reduce pair specified (Table 4; spec §12).
- [x] Hit targets ≥24 px in compact (by padding) and comfortable; no essential exception.
- [ ] Accessibility role sign-off — owner approval pending (adaptations).
- [x] Confirm-gate variant: no component here places an order; the gated confirm while Disconnected is CMP-044 `standard` on the grid's controls (E17-D01 §6), cited not redrawn.
- [x] Every heuristic / estimated value is chip-tagged — the hatched heatmap columns during a resync carry `(estimated)` (CMP-227; `25` §3).
- [x] Demo / Live context: the chrome never triggers a trading action; the `[ARMED] LIVE` badge stays visible under the in-panel variant (spec §4.2).
- [x] Reuses existing CMP ids; no new id (the count stays 239).
- [x] Storybook stories match the full Variants × States matrix (spec §15 vs Table 1).
- [ ] Composes only published-library components — the atoms (CMP-001, 012, 016, 019, 028, 035) are E05-D02's batches, pending; the specimens are drawn on the ticket's page.

## B. Accessibility acceptance criteria (`05` §10) — the four components

```gherkin
Feature: E17-D02 connection-state chrome — accessibility acceptance criteria

  Scenario: Keyboard-only operation
    Given the user has not used a pointing device
    When the connection drops, the user reads the chip, retries now, opens Details, dismisses the
      recovered banner and dismisses a degraded-mode issue using only the keyboard
    Then every control involved is reachable via Tab or arrow-key navigation (Table 2)
    And every action has a documented non-drag keyboard equivalent (no drag exists here)
    And focus is never silently moved by a background data update, a reconnect or a system frame
      (the SCR-001 inline variant moves focus only when a submitted sign-in fails)
    And a visible focus indicator meeting >=3:1 contrast is present at every step
      (6.66 / 5.86 / 17.30 on the bar; 5.59 / 5.50 / 14.54 on the danger fill)
    And the positions grid, its cancel and close controls and the kill switch stay reachable while Disconnected

  Scenario: Screen-reader operation
    Given the user is using NVDA with the keyboard
    When the transport drops, recovers, a feed goes stale and a backend issue appears
    Then all labels, roles and current values are announced correctly (Table 3)
    And live data is announced per 05 §6.2: Disconnected and recovery assertive once, Stale >= T2 once
      per episode, Delayed and Stale < T2 polite once on entry and exit, counters, ages and latency never
    And the shade's text is exposed as the panel's description without a per-cell announcement
    And any canvas-rendered data involved has a working DOM-mirror and/or
      "View as table" equivalent with full data parity, carrying the same state word and age (E11-D04 D15)

  Scenario: Colour-independence
    Given the chrome displays the five connection states and the issue severities
    When a state is rendered
    Then the state is also conveyed via glyph, word and position, not colour alone
      (the glyph set and words of spec §14.3; the region's 96 px slot and 4 px border; the scrims and the dim)
    And the components pass deuteranopia / protanopia / tritanopia simulation review (planned on the exports)

  Scenario: Contrast
    Given the chrome is rendered in the dark theme and the high-contrast theme
    Then all text meets >=4.5:1 and all meaningful non-text elements meet >=3:1 per the token
      contrast matrix (E17-D02 §14.1: 37 gated rows, 0 FAIL)

  Scenario: Reduced motion
    Given the user has prefers-reduced-motion enabled
    When the connection changes state
    Then the region and the chip flip instantly, the stale settle and the scrim lift become cuts,
      the stale shade never animates, no spinner runs and no flash exceeds 3 per second

  Scenario: Automated gates
    Given the implementation PR is opened
    Then axe-core reports zero new serious or critical violations
    And the affected screen's Lighthouse Accessibility score remains >= 95
    And the keyboard-only E2E smoke test covering drop → Retry now → Details → recovery passes
    And the no-trap test asserts the Tab order leaves the region
    And the announcement-throttling test asserts one alert per transitionSeq change
```

Spot-testing: deferred to the release-level pass of `05` §8 and E17-D04; no owner-approved exception exists.
