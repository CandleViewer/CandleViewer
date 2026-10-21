# E39-D01 accessibility audit (WCAG 2.2 AA) — Penpot page, all 41 boards

Page **"E39-D01 Risk caps, lockout and kill-switch research"** (page-id `c1ff2298-b5c7-80ce-8008-c98715176704`), audited
read-only on 2026-10-21 after Penpot pass C with the `penpot-audit-accessibility` method, run through the plugin API
(companion to [E39-D01.md](E39-D01.md) §9). **Result: 0 High · 0 Medium · 6 Low.** 2,598 of 2,604 visible texts reach
4.5:1; the other 6 are labels of disabled controls (WCAG 1.4.3 exempts inactive components), each with its reason stated
beside it. 151 targets, 0 under 24 × 24 px; 28 heading-styled texts, 0 order issues; 49 state glyphs, all with a word.

## Method

- **Contrast (1.4.3):** background = the top-most filled shape under the text's centre in paint order, composited (fill
  opacity × layer opacity) down to the board fill; the foreground likewise; colours are the resolved token values. No
  text is large (≥ 24 px, or ≥ 18.66 px bold), so every text needs 4.5:1.
- **Exempt:** disabled-control labels (`color.text.disabled`, or a disabled `CMP-001 · Button` variant at layer opacity
  0.45). Excluded: the 104 texts behind the opaque scrim of `SCR-134 / step-up-required` (inert, not visible in the
  export). The accepted exception O-K, the frozen chart under the disconnected scrim, is non-text.
- **Targets (2.5.8):** every `CMP-001 · Button` and `CMP-005 · Checkbox` instance, measured at its own bounds.
- **Headings (1.3.1, heuristic):** `type.ui.heading-*` texts in reading order, ranked by size per board: the first is
  the largest, no step skips a level; board titles and the top-bar brand "CandleViewer" (a logo) are left out.
- **Non-text (1.1.1, 1.4.11):** every `glyph-*` state shape has its word beside it (D8) and ≥ 3:1 against its background.

## Per board

| Board                                 | Texts ≥ 4.5:1       | Exempt | Targets ≥ 24 px | Headings         | Result   |
| ------------------------------------- | ------------------- | ------ | --------------- | ---------------- | -------- |
| `SCR-071 / normal`                    | 111 / 111           | 0      | 6 / 6           | 1, in order      | pass     |
| `SCR-071 / warning`                   | 111 / 111           | 0      | 6 / 6           | 1, in order      | pass     |
| `SCR-071 / locked`                    | 115 / 115           | 0      | 7 / 7           | 1, in order      | pass     |
| `SCR-071 / frozen`                    | 114 / 115           | 1      | 7 / 7           | 1, in order      | pass     |
| `SCR-071 / stale`                     | 113 / 113           | 0      | 6 / 6           | 1, in order      | pass     |
| `SCR-071 / reconciling`               | 113 / 113           | 0      | 6 / 6           | 1, in order      | pass     |
| `SCR-071 / manager`                   | 82 / 82             | 0      | 3 / 3           | 1, in order      | pass     |
| `SCR-072 / confirm-account`           | 38 / 38             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / confirm-flatten-ticked`    | 41 / 41             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / confirm-global`            | 47 / 47             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / confirm-manager`           | 41 / 43             | 2      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / confirm-demo`              | 39 / 39             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / confirm-disconnected`      | 42 / 42             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-072 / executing`                 | 25 / 25             | 0      | 1 / 1           | 1, in order      | pass     |
| `SCR-072 / completed`                 | 36 / 36             | 0      | 2 / 2           | 1, in order      | pass     |
| `SCR-072 / engaged-not-durable`       | 38 / 38             | 0      | 3 / 3           | 1, in order      | pass     |
| `SCR-072 / engaged-by-system`         | 38 / 38             | 0      | 3 / 3           | 1, in order      | pass     |
| `SCR-072 / partial-failure`           | 29 / 29             | 0      | 2 / 2           | 1, in order      | pass     |
| `SCR-072 / release`                   | 24 / 24             | 0      | 2 / 2           | 1, in order      | pass     |
| `SCR-072 / release-incomplete`        | 27 / 27             | 0      | 4 / 4           | 1, in order      | pass     |
| `SCR-073 / active-daily-loss`         | 60 / 60             | 0      | 6 / 6           | —                | pass     |
| `SCR-073 / consecutive-losses`        | 63 / 63             | 0      | 5 / 5           | —                | pass     |
| `SCR-073 / max-positions`             | 68 / 68             | 0      | 4 / 4           | —                | pass     |
| `SCR-073 / manual`                    | 63 / 63             | 0      | 5 / 5           | —                | pass     |
| `SCR-073 / override-requested`        | 56 / 57             | 1      | 5 / 5           | —                | pass     |
| `SCR-073 / expired`                   | 60 / 60             | 0      | 5 / 5           | —                | pass     |
| `SCR-073 / frozen-by-owner`           | 60 / 61             | 1      | 4 / 4           | —                | pass     |
| `SCR-073 / owner-override`            | 44 / 44             | 0      | 2 / 2           | 1, in order      | pass     |
| `SCR-073 / override-result`           | 15 / 15             | 0      | 2 / 2           | 2, in order      | pass     |
| `SCR-134 / clean`                     | 122 / 123           | 1      | 5 / 5           | 1, in order      | pass     |
| `SCR-134 / validation-warning`        | 128 / 128           | 0      | 6 / 6           | 1, in order      | pass     |
| `SCR-134 / step-up-required`          | 31 / 31 (104 inert) | 0      | 8 / 8           | 1, in order      | pass     |
| `SCR-134 / save-conflict`             | 127 / 127           | 0      | 7 / 7           | 1, in order      | pass     |
| `SCR-134 / save-refused-policy-floor` | 126 / 126           | 0      | 5 / 5           | 1, in order      | pass     |
| `flow / F20-kill-switch`              | 48 / 48             | 0      | —               | —                | pass     |
| `flow / breach-lockout-override`      | 33 / 33             | 0      | —               | —                | pass     |
| `research / personas-and-journeys`    | 59 / 59             | 0      | —               | —                | pass     |
| `research / findings-to-decisions`    | 59 / 59             | 0      | —               | —                | pass     |
| `research / comparison-matrix`        | 62 / 62             | 0      | —               | —                | pass     |
| `research / state-encoding-legend`    | 14 / 14             | 0      | —               | —                | pass     |
| `a11y / keyboard-and-live-regions`    | 76 / 76             | 0      | —               | —                | pass     |
| **41 boards**                         | **2,598 / 2,604**   | **6**  | **151 / 151**   | **28, 0 issues** | **pass** |

## Below 4.5:1 — exempt inactive components (Low), each with its reason stated

| Board                          | Shape › text                                                                 | Contrast | Reason beside it                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------- |
| `SCR-071 / frozen`             | `CMP-001 Button: Frozen [disabled-with-reason]` › "Frozen"                   | 3.72:1   | the row's FROZEN state; the board note gives the reason                          |
| `SCR-072 / confirm-manager`    | scope radio label "All 3 accounts in LIVE and DEMO" (`color.text.disabled`)  | 2.64:1   | "Global freeze is owner-only"                                                    |
| `SCR-072 / confirm-manager`    | `CMP-005 Checkbox: Also flatten open positions (2)` › label                  | 1.51:1   | "Only the owner can flatten."                                                    |
| `SCR-073 / override-requested` | `CMP-001 Button: Override requested 13:52 — waiting [disabled-with-reason]`  | 3.72:1   | "disabled: already requested"                                                    |
| `SCR-073 / frozen-by-owner`    | `CMP-001 Button: Freeze my account… [disabled-with-reason]` (Safety cluster) | 3.48:1   | the FROZEN banner: "Trading frozen at 14:02 UTC — only the owner can release it" |
| `SCR-134 / clean`              | `CMP-001 Button: Discard changes` › label                                    | 3.78:1   | "disabled: no changes"                                                           |

No AA fix is needed; to keep disabled labels readable, E39-D02/D03 would change the library variant's opacity (0.45).
