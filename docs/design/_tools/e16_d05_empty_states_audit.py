#!/usr/bin/env python3
"""E16-D05 recorder-dependent empty and partial-history states audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged upstream specs and the spec AS TEXT and
prints: (1) the WCAG 2.x ratio of every fg / bg pair the empty states, the chip, the band and the
tooltip render in dark / light / high-contrast (`themes.json` layering); (2) every token the spec binds,
resolved or MISSING, with E11-D05's two chart aliases resolved through their targets and the two hatch
registry ids listed apart; (3) the contract facts the boards quote, parsed from `22` / `23` / `21` /
`24` / `14` / `15` text (the seven gap reasons and the open-ended note, the data-coverage `x-rbac`, the
`no_data_recorded` 422 on REST and WS, the `gone` 410, the nullable `recording_started_at`, the
`coverage_holes`, `history_bars` >= 0, the auto-record sentence, the `21` partial-history mandate and its
five-value cause CHECK, the `24` "a backfilled gap stays a gap" rule, the `14` stem and chip illustration,
the two sign-off checklists, the five CMP-026 variants, the two registry rows, E11-D04's ruled stem, the
`26` hatched-band rule); (4) the fixture, derived from the `22` data-coverage example (the gap's
duration, the chip's n / m, the 12-minute AC 2 gap, the band's px width at three zoom levels) and the
retention fixture (the same report one retention period later: its trim date lies after the recording
start, so the days before it are a `retention_purge` gap); (5) the copy gates (the stem byte for byte
on every history-start heading and on no gap frame, every `rbac.*` sentence within 60 characters naming
no data, every cause within 80 characters, the banned words, the retention cause distinct from the
never-recorded cause, every gap frame's cause the deck's sentence for its reason, the unknown-reason
fallback, no private path or host, every cited id and line still valid, no closing keyword); (6) the
per-frame gates over every state table (section 12 of the spec lists them); (7) the counts the spec,
the boards and the PR body quote. `--json` feeds the check-nums script; `--check` re-derives the spec's
`<!-- audit:key=N -->` markers; `--self-test` applies the 39 numbered mutations of spec section 12 in
memory, one at a time, and passes only when each makes `--check` fail with its own message (rc 1), no
two share a message, and the unmutated spec passes; `--mutate N` prints one mutation's gate output and
exits as `--check` would on the mutated spec: 1 when the targeted FAIL fires (the gate caught it), 2 when
the mutation slips through or fails for another reason (a defect in the gate) — never 0. Every other
mode exits 1 on a gated FAIL.

Usage: python3 -I docs/design/_tools/e16_d05_empty_states_audit.py [--json] [--check] [--self-test]
  [--mutate N] [--extra F]
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E16" / "E16-D05.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES = {"dark": (PRIM, DARK), "light": (PRIM, DARK, LIGHT), "high-contrast": (PRIM, DARK, HC)}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
MULTI = re.MULTILINE
# Generic patterns only: no personal word, no hostname whole or split; the path literal is split.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b",
)
# Words the deck's String column never shows a user (spec section 2: no apology, no "error").
BANNED_COPY = (r"\berror\b", r"\bsorry\b", r"\bunfortunately\b", r"\boops\b")
# E11-D05's chart aliases (:92, :94): the registry name -> the semantic token it aliases.
CHART_ALIASES = {
    "color.chart.boundary": "color.text.tertiary",
    "color.chart.hatch.texture": "color.border.strong",
}
REGISTRY_IDS = ("pattern.hatch.gap", "pattern.hatch.absent")
# The shared history-start cause (BQ-16 RULED): on the stem family only, never on a gap frame.
RECORDED_ONLY = "Nothing is missing or broken: CandleViewer keeps only what it records."
STEM_TAILS = ("— recording began then.", "— recording has not begun yet.")
VIEW_AS = "Read-only while viewing as"
OWNER_ONLY = "Only the owner can change recording."
# E11-D04 :798's Manager / Viewer draft: names data (the symbol) and runs past 60 characters (D05-C7).
DRAFT_798 = "You can't start recording with your role — ask the owner to record BTCUSDT."
LIVE_NOW = "Live data is streaming now."
# The REC chip words (E16-D02 section 5.4 :331-340): one of them on the in-situ frame.
REC_CHIP = (
    "REC · manual",
    "Not recording · limit reached",
    "Not recording · disk nearly full",
    "REC gated · data dropped",
    "REC degraded",
    "Recording status restricted",
)
# The actions that leave an empty state (spec section 1.3): every SCR-047 row names one.
EXITS = (
    "`Go to latest`",
    "`Go to recorded history`",
    "`Switch symbol`",
    "`Open symbol info`",
    "`Switch to time bars`",
    "`Go to the nearest recorded data`",
    "the first bar ends the state",
)
# The gap family (spec section 2, BQ-16 RULED): every prefix. A gap frame never carries the shared cause;
# the 1b stem ("recording began then") never sits on one; the 1a stem ("has not begun yet") sits only on
# the never-recorded frames, which include the auto-record refusals (recording has not begun there).
GAP_FAMILY = re.compile(r"gap-|no-trades|refused|role-restricted|in-situ|^GAP/|scr-038-partial")
STEM_1A_NEVER = re.compile(r"gap-|no-trades|role-restricted|^GAP/|scr-038-partial")
STEM_1B_TAIL = "recording began then"
STEM_1A_TAIL = "recording has not begun yet"
# Every gap-family frame's cause cell carries the deck's sentence for its reason (BQ-10; E16-D02 :340).
GAP_CAUSE_KEY = {
    "SCR-047/gap-ws-disconnect": "empty.gap.ws_disconnect",
    "SCR-047/gap-retention-purge": "empty.gap.retention_purge",
    "SCR-047/no-trades-in-window": "empty.gap.no_trades",
    "SCR-047/autorecord-refused-cap": "empty.refused.symbol_cap",
    "SCR-047/autorecord-refused-disk": "empty.refused.disk_pressure",
    "SCR-047/in-situ": "empty.refused.symbol_cap",
    "SCR-047/role-restricted": "empty.status.restricted",
    "SCR-151/role-restricted": "empty.status.restricted",
}
# A band frame's label cell names a VISIBLE text carrier (AC 2: "identifiable and labelled" at every zoom):
# the in-band label, the time-axis tag or the seam's tag — never the tooltip or the cursor alone.
VISIBLE_CARRIERS = ("`gap.band.label`", "`gap.axis.tag`", "`gap.seam.label`")
IN_BAND_LABEL = re.compile(r'in-band (?:"|label\b)')  # a drawn in-band label, never "no in-band room"
NINETY_DAY = "unknown — never shown as a gap and never as covered"
KEY_CHORD = re.compile(r"\b(?:Ctrl|Alt|Cmd)\+[A-Za-z0-9]+")
DIMMING = ("opacity.disabled", "color.text.disabled")
# The three-zoom thresholds and scales (spec section 3; D05-D6). px per minute; the AC 2 gap in minutes.
ZOOM = {"wide_px_per_min": 0.5, "medium_px_per_min": 2, "tight_px_per_min": 8, "seam_px": 8, "label_px": 48}
LAYOUT = {"block_w": 480, "tooltip_w": 320, "coverage_days": 90, "reason_max": 60, "cause_max": 80}
# element | fg | bg | role — every pair the states draw (spec section 15, rows in order).
PAIRS_TABLE = """
heading, mono timestamp and the live sentence words on the pane | color.text.primary | color.surface.canvas | text
cause and the rbac sentence on the pane | color.text.secondary | color.surface.canvas | text
heading on a panel | color.text.primary | color.surface.raised | text
cause, rbac sentence and the table band row words on a panel | color.text.secondary | color.surface.raised | text
CTA label on the primary fill | color.text.on-action | color.action.primary.default | text
link words on the pane | color.text.link | color.surface.canvas | text
link words on a panel | color.text.link | color.surface.raised | text
chip words on the info fill | color.text.primary | color.status.info.subtle | text
chip glyph on the info fill | color.status.info.strong | color.status.info.subtle | non-text
band edges and the seam on the canvas (color.chart.boundary) | color.text.tertiary | color.surface.canvas | non-text
in-band label and the axis tag on the canvas | color.text.tertiary | color.surface.canvas | text
tooltip title on the overlay | color.text.primary | color.surface.overlay | text
tooltip lines on the overlay | color.text.secondary | color.surface.overlay | text
live glyph on the pane | color.data-confidence.live.indicator | color.surface.canvas | non-text
gapped chip words on a panel | color.data-confidence.gapped.text | color.surface.raised | text
backfilling words on a panel | color.data-confidence.backfilling.text | color.surface.raised | text
delisted chip words on a panel | color.data-confidence.delisted.text | color.surface.raised | text
progress bar fill on its track | color.action.primary.default | color.surface.sunken | non-text
focus ring on the pane | color.focus.ring | color.surface.canvas | non-text
focus ring on a panel | color.focus.ring | color.surface.raised | non-text
band texture on the canvas (color.chart.hatch.texture) | color.border.strong | color.surface.canvas | decorative
the CMP-026 glyph on the pane | color.text.tertiary | color.surface.canvas | decorative
REJECTED dimmed cause in text.disabled on the pane | color.text.disabled | color.surface.canvas | rejected-text
"""
BINDINGS = (
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.border.default",
    "color.border.strong",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.link",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.action.primary.default",
    "color.focus.ring",
    "color.data-confidence.live.indicator",
    "color.data-confidence.gapped.text",
    "color.data-confidence.backfilling.text",
    "color.data-confidence.delisted.text",
    "opacity.disabled",
    "radius.badge",
    "radius.card",
    "elevation.card",
    "space.inset.xl",
    "space.inset.sm",
    "space.stack.sm",
    "space.stack.md",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.caption",
    "type.num.sm",
    "font.family.mono",
    "size.icon.lg",
)
# doc | line at the base | text the line must hold. A `14` line may sit lower by this PR's pointer lines.
CITED_TABLE = """
14 | 83 | **Recorder-dependent emptiness is a designed state**, never a blank canvas
14 | 85 | **RBAC denies server-side; the UI presents.**
14 | 674 | ### SCR-030 — Chart panel (price + footprint)
14 | 724 | | partial-history      | Dashed full-height boundary with a text tag
14 | 725 | | coverage-gap         | Time axis: a hatched, labelled band over the time slots
14 | 727 | | empty                | SCR-047 replaces the pane stack, with no GL context
14 | 740 | The first live bar ends SCR-047, which yields to the built-from boundary
14 | 942 | ### SCR-038 — Profile panel (volume / delta profile + TPO)
14 | 961 | falling back to kline-derived approximation with an explicit "approximated from bars" chip
14 | 963 | partial history (chip "Partial: only 12 of 30 requested days recorded")
14 | 964 | a table alternative lists each price row with volume, delta, and VA membership
14 | 966 | CMP-026 EmptyState, CMP-110 ProfileBar, CMP-135 VwapBandLegend
14 | 1070 | ### SCR-047 — Chart empty / no-data state
14 | 1072 | symbol never recorded (offers live-only view with a "history starts when you record" explanation)
14 | 1083 | CMP-001 Button, CMP-021 Link, CMP-026 EmptyState, CMP-029 Skeleton-Chart placeholder.
14 | 1085 | the CTA is a real button (owner) or an explanatory sentence (manager/viewer)
14 | 1086 | The empty state renders without initialising the GL context for the data layer
14 | 1087 | `chart.empty_state_shown` with `{reason: 'not_recorded'|'no_data_in_range'|'symbol_delisted'}`
14 | 1088 | proposes scoping the live-data sentence and naming the cause; copy owned by E16-D05
14 | 1089 | three distinct reasons drawn (never recorded / no data in this range / instrument not trading)
14 | 2229 | ### SCR-103 — Symbol info / instrument detail
14 | 2233 | "Open symbol info" and "Show coverage" (SCR-047)
14 | 2721 | ### SCR-140 — Admin: recorder & storage
14 | 2914 | ### SCR-151 — Empty state pattern
14 | 2916 | a short heading stating the fact, one sentence of cause, one primary action, one secondary learn-more link
14 | 2919 | either an action button or an explicit statement that no action is available to this role
14 | 2920 | Empty states render without initialising heavy resources (no GL context, no subscriptions)
14 | 2921 | `empty_state_shown` `{surface, reason}`
14 | 2923 | the backfill variant's determinate CMP-023 bar, no indeterminate loop
14 | 2924 | the three empty-state classes drawn (nothing created yet / nothing matches the filter / data not recorded yet)
14 | 2926 | ### SCR-152 — Disconnected / reconnecting state
14 | 2949 | ### SCR-153 — Degraded-mode state
15 | 149 | ### CMP-011 Tag / Chip
15 | 156 | neutral: `color.neutral.subtle` fill + `color.border.default` 1 px stroke
15 | 188 | ### CMP-015 Skeleton
15 | 198 | ### CMP-016 Tooltip
15 | 225 | ### CMP-019 Icon
15 | 243 | ### CMP-021 Link
15 | 262 | ### CMP-023 Progress Bar
15 | 290 | ### CMP-026 EmptyState
15 | 293 | `variant: "no-data"|"recording-not-started"|"backfill-in-progress"|"filtered-empty"|"error"`
15 | 294 | `variant="backfill-in-progress"` (data-confidence `backfilling` state) pairs a determinate/indeterminate progress affordance
15 | 295 | when the sole CTA is gated, `cta` is omitted and `description` carries the host's reason, with no button
15 | 297 | glyph CMP-019 `size="lg"` in `color.text.tertiary`; heading `type.ui.heading-sm`
15 | 298 | AllVariants, SentenceForm.
15 | 311 | ### CMP-028 Callout / Banner (inline, non-global)
15 | 323 | ### CMP-029 Skeleton-Chart placeholder
15 | 811 | ### CMP-079 RbacGate (disabled-with-reason wrapper)
15 | 2000 | ### CMP-172 ReplayRangePicker
15 | 2005 | Default, PartialAvailability, NoRecordedHistory(EmptyState).
15 | 2237 | ### CMP-189 TimeAxis
15 | 2653 | ### CMP-227 EstimatedBadge
15 | 2784 | ### CMP-239 FreshnessMarker (E08-D04, data-confidence vocabulary)
22 | 670 | - code: gone
22 | 672 | Resource existed but was purged by retention, or a one-time link that expired or was used
22 | 686 | - code: no_data_recorded
22 | 688 | title: Requested window predates the start of recording for this symbol
22 | 3825 | `recording_started_at` returns `no_data_recorded` (422) rather than silently
22 | 4572 | /market/data-coverage:
22 | 4578 | The UI calls this before rendering a historical window so it can grey out ranges that
22 | 4622 | reason: "ws_disconnect",
22 | 4636 | generated_at: "2026-09-14T10:31:02.800Z"
22 | 5235 | A window lacking recorded coverage is rejected with `no_data_recorded` (422) —
22 | 16029 | DataMeta:
22 | 16044 | coverage_holes:
22 | 16227 | RecordingState:
22 | 16230 | enum: [idle, starting, recording, degraded, stopping, stopped, error],
22 | 17565 | recorded: { type: boolean }
22 | 17845 | DataCoverage:
22 | 17876 | ws_disconnect,
22 | 17882 | seq_jump,
22 | 17888 | RecordedSymbol:
23 | 857 | #### 6.2.2 `recorder` topic
23 | 1597 | | `no_data_recorded`         | any        | no          | =                      | Topic needs recorded history that does not exist. Start recording first.
23 | 1820 | ### 12.6 Subscribing to a symbol with no recorded history
23 | 1824 | "warning":{"code":"no_data_recorded","message":"SOLUSDT recording started 00:04:12 ago; only 1 complete bar of
23 | 1825 | "meta":{"reason":"initial","recording_started_at_ms":1789132848000,"history_bars":1}
23 | 1828 | triggers auto-record (owner decision #4
23 | 2000 | "recording_started_at_ms": { "$ref": "#/$defs/epochMs" },
23 | 2001 | "history_bars": { "type": "integer", "minimum": 0 },
21 | 2923 | #### 3.6.2 `recording_sessions`
21 | 2925 | a reconnect that loses data closes the current session with a gap record and opens a new one
21 | 2954 | CREATE TABLE recording_gaps (
21 | 2962 | backfilled           boolean NOT NULL DEFAULT false,
21 | 2963 | backfill_source      text,
21 | 2965 | CONSTRAINT rg_cause  CHECK (cause IN ('ws_disconnect','backpressure_drop','process_restart','seq_jump','exchange_outage'))
21 | 2970 | must render the documented "partial history" state
21 | 4512 | | `trades`                              | 30 d
21 | 4498 | a `retention_purge` audit entry records symbol, stream, range and row count
21 | 4618 | Market data gaps become `recording_gaps` rows with `cause='process_restart'`
24 | 3745 | #### 13.3.1 `CoverageService` (E16-T04)
24 | 3753 | async def recording_started_at_us(symbol: str) -> int | None
24 | 3757 | GapInterval(lo: int, hi: int, cause: str, backfilled: bool, backfill_source: str | None)
24 | 3762 | A `backfilled` (kline) gap stays a gap: tick coverage is
24 | 3764 | `process_restart`→`backend_restart`; `seq_jump`, `backpressure_drop` 1:1 (#2216)
11 | 1058 | #### US-CHART-010 — Days-to-load control
11 | 1064 | When I set 30 days on a 1m chart
11 | 4191 | #### US-REC-006 — Recording gaps and integrity
11 | 4193 | so that I never mistake a gap for calm
11 | 4197 | Given the recorder was down for 12 minutes
11 | 4203 | Then bars are backfilled and marked as bar-derived, while tick-level views still show the gap
11 | 4206 | NFR: gap metadata is a first-class table consulted by charts, replay, profiles and backtests
05 | 118 | imbalance-flagged cells get a distinct border/pattern
05 | 126 | **Non-text/UI component contrast (WCAG 1.4.11, AA)**
05 | 131 | **Text resize (WCAG 1.4.4, AA)**
05 | 140 | a `tabindex`-able, ARIA-labelled DOM element per logical unit
05 | 146 | **Price/position/order updates** are announced via `aria-live` regions
05 | 150 | live regions are pre-rendered empty containers on page load
05 | 195 | The `<canvas>` element itself carries `role="img"` with a dynamic `aria-label`
05 | 204 | The app respects OS-level `prefers-reduced-motion: reduce` by default
05 | 285 | Then the state is also conveyed via shape/icon and text, not colour alone
16 | 54 | **Status/tone ramp**: `color.status.{success,warning,danger,info}`
16 | 56 | **Chart chrome slots (E11-D05)**
16 | 75 | merged into one chip — see CMP-227/CMP-239
16 | 160 | **Colour is never the sole encoding.**
16 | 164 | **Estimated/heuristic series are visually distinguished at the series level**
16 | 174 | **Every animated property ships a `motion-safe`/`motion-reduce` pair**
06 | 25 | | 1 | Chart engine frame time | ≤16.6ms/frame (60fps) sustained
26 | 620 | **Coverage gaps**: ranges with no recorded data are rendered as a hatched band with a label, never interpolated
26 | 709 | | **M8** | Replay + accessibility + polish | Virtual-now marker, coverage-gap rendering
12 | 227 | | M-023 | Modal | Recording toggle / retention explainer for a symbol
E11D04 | 336 | SCR-151's anatomy, which SCR-047 is an instance of
E11D04 | 342 | | **1a never recorded** (`not_recorded`)
E11D04 | 343 | | **1b recorded, window before the start** (`not_recorded`)
E11D04 | 344 | | **2 no data in this range** (`no_data_in_range`)
E11D04 | 345 | | **3 not trading / delisted** (`symbol_delisted`)
E11D04 | 347 | **Owner-only** is the orchestrator's ruling of 2026-10-20 18:30Z
E11D04 | 351 | - **"Live data is streaming now."** is shown only when the symbol's live topics are **Live**
E11D04 | 352 | - **Exits.** 1a and 1b leave the empty state when the first bar exists
E11D04 | 353 | - **No spinner path.**
E11D04 | 457 | | SCR-047 pane                         | reasons 1a / 1b / 2 / 3 × CTA / explanatory (08, 09)
E11D04 | 481 | the chart's loading transition only — **not** the empty state (§11.1)
E11D04 | 482 | **CR-D04-4** (co-owner E16-D05): `variant: "not-trading"` and an `explanation?: string` prop
E11D04 | 778 | Final empty-state wording is E16-D05's
E11D04 | 798 | **SCR-047.** 1a heading "History starts when you record BTCUSDT — recording has not begun yet."
E11D04 | 919 | 1a without a timestamp
E11D04 | 963 | **Closed — ruled 2026-10-20 18:30Z:** the stem is `14` §0.5 rule 3's
E11D04 | 987 | - **A-2 `14` SCR-047:** Components: CMP-029 is the loading transition only; add CMP-239
E11D04 | 1014 | the SCR-047 deck (§19) to finalise against E16-D01 §4 on the ruled stem
E12D02 | 272 | | `SCR-030/partial-history-time`     | Boundary at recording start
E12D02 | 273 | | `SCR-030/partial-history-non-time` | Bars start at the boundary
E12D02 | 275 | | `SCR-030/lookback-boundary`        | On a 1h chart
E12D02 | 276 | | `SCR-030/coverage-gaps`            | Time: a hatched band over a gap's time slots
E12D02 | 289 | a separator row per boundary and gap
E12D02 | 291 | bar with recorded prints" at recording start
E12D02 | 313 | | `SCR-047/not-recorded-autorecord-on`      | `not_recorded`
E12D02 | 314 | | `SCR-047/not-recorded-autorecord-refused` | `not_recorded`
E12D02 | 316 | | `SCR-047/not-recorded-manager-viewer`     | `not_recorded`
E12D02 | 317 | | `SCR-047/no-data-in-range-non-time`       |
E12D02 | 335 | E12-D08 (#243) with E16-D05 (#373) reconciles the E12 wording
E12D02 | 386 | | `chart.empty_state_shown`                        | `reason` (`not_recorded`, `no_data_in_range`, `symbol_delisted`)
E12D02 | 488 | | OQ-10 | SCR-047's owner CTA: M-023 in context (sitemap) or SCR-140
E16D02 | 27 | | 2   | Disclosure A′: silent auto-record after the 60 s dwell
E16D02 | 29 | | 4   | Managers do not get `recording:write` in the design
E16D02 | 134 | (an unknown reason reads as "gap")
E16D02 | 150 | gaps from `DataCoverage.streams[].gaps[]` (reasons incl. **amendment** `backpressure_drop`, `seq_jump`; open-ended)
E16D02 | 175 | | **paused** (disk level 2)
E16D02 | 240 | the tooltip and the row detail say "data erodes daily under the 30-day retention"
E16D02 | 319 | ### 5.4 REC chip state sheet (cross-screen)
E16D02 | 326 | then a session without `recording:write` (`rbac.owner_only` "Only the owner can
E16D02 | 336 | | "Not recording · limit reached"    | refusal symbol_cap
E16D02 | 337 | | "Not recording · disk nearly full" | refusal disk_pressure
E16D02 | 340 | | "Recording status restricted"      | **amendment** `role_restricted`, the symbol not in the set
E16D02 | 449 | | Manager                  | not reachable: `/admin/*` is hidden from navigation and returns a hard 404
E16D02 | 450 | | Viewer / role-restricted | not reachable
E16D02 | 809 | CVD renders (§10.4: the running and disk-critical boards
E11D05 | 92 | | `color.chart.boundary`            | `{color.text.tertiary}`
E11D05 | 94 | | `color.chart.hatch.texture`       | `{color.border.strong}`
E11D05 | 315 | | `pattern.hatch.gap`         | 45°, 1 px lines, 6 px pitch; dashed 4 / 4 edges
E11D05 | 316 | | `pattern.hatch.absent`      | pattern.hatch.gap's geometry
E11D05 | 328 | | E12-D06 §6 D8       | 45°, 1 px lines, **10 px period**
E11D02 | 115 | maintenance window = hatched band (`color.border.strong` texture) with dashed `color.text.tertiary` edges and a text label
E11D02 | 140 | | **Maintenance band**                     | an exchange maintenance window (a coverage gap)
E11D02 | 272 | `01:55 – 02:25 maintenance` label when ≥48 px wide
E11D02 | 273 | - **Loading band** (E11-D01 Q1-i)
E11D02 | 646 | | CR-6 | `pattern.hatch.gap` (registry id)
E11D02 | 692 | | maintenance hatch                            | pattern via the registered hatch
E11D03 | 348 | | — gap older than the coverage window
E11D03 | 352 | **One stem across surfaces (cross-ticket decision
E11D03 | 876 | | O-10 | The before-history stem across SCR-044 (here), SCR-047
E05D02 | 1271 | | block       | centred in its region on the host surface; a column at most 480 px
E05D02 | 1272 | | glyph       | CMP-019 `size="lg"` (`size.icon.lg`, slice 1 §5.2) in `color.text.tertiary`, decorative
E05D02 | 1275 | | actions     | the CTA a CMP-001 `primary`
E05D02 | 1284 | a gated CTA is never drawn: the sentence form instead
E05D02 | 1426 | the box, the edge, hatched or solid, turns CanvasText
E09 | 38 | | 1    | Is the control a **navigation affordance whose only function is to reach an `/admin/**` destination**
E09 | 40 | | 3    | In the **session** (`GET /auth/session` and `GET /me` at bootstrap
E09 | 49 | - **T2 Disabled with a visible reason (D4).**
E09 | 73 | | Recorder setting (ii): "Record this symbol" on SCR-047 (`recording:write`)
E09 | 85 | Every T2 reason is one of these seven keys, or a key of a registered **state** vocabulary
E09 | 95 | | `rbac.view_as`           | "Read-only while viewing as {user}."
E09 | 108 | `recording:write` → "change recording"
E09 | 224 | ### 9.1 `aria-disabled` versus `disabled`, and focusability
E09 | 230 | a control disabled by **form validity**
E09 | 238 | ### 9.3 Keys on a T2 control
E30D02 | 128 | disabled = `opacity.disabled` on the control with the reason as full-opacity text under it, never inside it
E16D01 | 203 | **Blocking copy issue (heuristic).** "History starts <ts> — recording began then" reads like a pending job
E16D01 | 209 | **Revised string (proposed, not adopted).**
E16D01 | 214 | 1. **"Live data is working" is scoped to "where true"**
E16D01 | 222 | "Older data was removed by the retention policy (<N> days)."
E16D01 | 223 | Gaps are shown as gaps, never interpolated (ADR-0015 decision 7)
E17D01 | 93 | | F13 | Existing precedence (E08): `delisted > disconnected > reconnecting > resyncing > gapped > backfilling > stale > live`
E17D01 | 209 | ## 7. Announcement policy
E25 | 334 | **"Hollow, dashed or hatched = estimated or absent, never a side or direction."**
E08D02 | 133 | - The two ingestion-relevant variants of the shared empty-state pattern: "No recorded history before
E08D04 | 46 | | `gapped` | `.gapped.text` | `.gapped.indicator` | ambient | "Reconstructed after gap"
E08D04 | 47 | | `backfilling` | `.backfilling.text` | `.backfilling.indicator` | ambient / CMP-026 | "Loading history…"
E08D06 | 168 | | Recorded data from    | `InstrumentDetail.recording_started_at` once CR-8 wires it
E08D06 | 169 | the route answers the last 90 days only and clips every interval to them
E08D06 | 175 | Shown (placeholder words: the final copy is E16-D05's)
E08D06 | 687 | E16-D05 replaces the §4.3 placeholder words
E08D07 | 105 | | D23 | Empty list: heading "No symbols on this watchlist"
E10D03 | 270 | - **Empty**: SCR-151's pattern — "No workspaces yet"
"""
POINTER = "E16-D05.md"
DOC_NAMES = (
    "05-accessibility-standard.md",
    "06-performance-and-load-standard.md",
    "11-user-stories.md",
    "12-sitemap.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "16-design-system-brief.md",
    "21-database-schema.md",
    "22-api-openapi.yaml",
    "23-ws-protocol.md",
    "24-internal-schemas.md",
    "26-chart-engine-design.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
DOCS.update(
    {
        "E11D04": DESIGN / "E11" / "E11-D04.md",
        "E11D05": DESIGN / "E11" / "E11-D05.md",
        "E11D02": DESIGN / "E11" / "E11-D02.md",
        "E11D03": DESIGN / "E11" / "E11-D03.md",
        "E12D02": DESIGN / "E12" / "E12-D02.md",
        "E16D02": DESIGN / "E16" / "E16-D02.md",
        "E16D01": DESIGN / "research" / "e16-recorder-mental-model.md",
        "E05D02": DESIGN / "E05" / "E05-D02-feedback-overlays.md",
        "E09": DESIGN / "E09" / "E09-D09.md",
        "E30D02": DESIGN / "E30" / "E30-D02.md",
        "E17D01": DESIGN / "E17" / "E17-D01.md",
        "E25": DESIGN / "E25" / "E25-D01.md",
        "E08D02": DESIGN / "E08" / "E08-D02.md",
        "E08D04": DESIGN / "E08" / "E08-D04.md",
        "E08D06": DESIGN / "E08" / "E08-D06.md",
        "E08D07": DESIGN / "E08" / "E08-D07.md",
        "E10D03": DESIGN / "E10" / "E10-D03.md",
    }
)
# The state tables: (spec section start, section end). Frame rows are `| \`PREFIX/slug\` | ...`.
TABLES = ((4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10), (11, 12))
FRAME_RE = r"^\| `((?:SCR-047|SCR-151|CHIP|GAP|SURF)/[a-z0-9-]+)` +\|.*$"
ROW_IDS = (("a_rows", "A"), ("c_rows", "C"), ("g_rows", "G"), ("cg_rows", "CG"), ("q_rows", "Q"))
# Cite rule: the needle must occur exactly once in its file. Once, at the cited line (or the cited
# line plus the PR's pointer shift for `14`): OK. Once, elsewhere: WARN naming the current line.
# Not at all: FAIL "cited text gone". More than once: FAIL "cited text ambiguous".
CITE_WARN: list[str] = []


def rows(table: str, parts: int = -1) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|", parts)] for ln in table.strip().splitlines()]


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads((TOKENS / f).read_text(encoding="utf-8"))
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    name = CHART_ALIASES.get(name, name)
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return str(value)


def rgb(hex6: str) -> list[int]:
    return [int(hex6.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]


def luminance(hex6: str) -> float:
    lin = [
        (c / 12.92) if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in rgb(hex6))
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def section(spec: str, a: int, b: int) -> str:
    return spec[spec.index(f"\n## {a}.") : spec.index(f"\n## {b}.")]


def first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "MISSING"


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def humanise(seconds: int) -> str:
    """D05-D7: seconds under a minute, "{m} min {s} s" under an hour, "{h} h {m} min" after."""
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m} min {s} s" if s else f"{m} min"
    h, rest = divmod(seconds, 3600)
    m = rest // 60
    return f"{h} h {m} min" if m else f"{h} h"


def frame_rows(spec: str) -> list[tuple[str, list[str], int]]:
    """Every frame row of every state table: (frame, cells, section)."""
    out = []
    for a, b in TABLES:
        for m in re.finditer(FRAME_RE, section(spec, a, b), MULTI):
            c = cells(m.group(0))
            out.append((c[0].strip("`"), c, a))
    return out


def iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def contract_facts(t: dict[str, str]) -> dict[str, Any]:
    """Every fact a board quotes, parsed from the plan and spec texts; nothing is executed."""
    api, ws, db, d24, cat, cmp = t["22"], t["23"], t["21"], t["24"], t["14"], t["15"]
    cov = api[api.index("    DataCoverage:") : api.index("    RecordedSymbol:")]
    gaps = cov[cov.index("gaps:") :]
    enum = gaps[gaps.index("enum:") : gaps.index("]", gaps.index("enum:"))]
    reasons = re.findall(r"\b([a-z_]+),", enum)
    route = api[api.index("  /market/data-coverage:") : api.index('        "400"', api.index("  /market/data-coverage:"))]
    example = route[route.index("examples:") :]
    intervals = [
        (iso(f), iso(to), tier, int(n))
        for f, to, tier, n in re.findall(
            r'from: "([^"]+)",\s*to: "([^"]+)",\s*tier: (\w+),\s*rows: (\d+)', example
        )
    ]
    gap_rows = re.findall(r'from: "([^"]+)",\s*to: "([^"]+)",\s*reason: "(\w+)"', example)
    state = api[api.index("    RecordingState:") : api.index("    RecordReason:")]
    states = re.findall(r"\b([a-z]+)", first(r"enum: \[([^\]]+)\]", state))
    err = api[api.index("  - code: no_data_recorded") :]
    err = err[: err.index("  - code:", 10)]
    gone = api[api.index("  - code: gone") :]
    gone = gone[: gone.index("  - code:", 10)]
    check = first(r"CONSTRAINT rg_cause\s+CHECK \(cause IN \(([^)]+)\)\)", db)
    causes_21 = re.findall(r"'([a-z_]+)'", check)
    seed = first(r"^\| `trades` +\| (\d+) d", db[db.index("## 7. Retention policy matrix") :], MULTI)
    stem = first(r'show "(History starts <ts> — recording began then)"', cat)
    chip_14 = first(r'chip "(Partial: only 12 of 30 requested days recorded)"', cat)
    scr047 = cat[cat.index("### SCR-047 ") : cat.index("### SCR-048 ")]
    scr151 = cat[cat.index("### SCR-151 ") : cat.index("### SCR-152 ")]
    boxes = lambda s: first(r"(- \*\*Design sign-off acceptance checklist:\*\*.*)$", s, MULTI).count("[ ]")  # noqa: E731
    cmp026 = cmp[cmp.index("### CMP-026 ") : cmp.index("### CMP-027 ")]
    variants = re.findall(r'"([a-z-]+)"', first(r"`variant: ([^`]+)`", cmp026))
    d05 = t["E11D05"]
    return {
        "gap_reasons_22": reasons,
        "open_ended": "**Open-ended for readers:**" in cov,
        "coverage_rbac": "x-rbac: { permissions: [marketdata:read], scope: none }" in route,
        "no_data_recorded_422": "status: 422" in err and "surface: [rest, ws]" in err,
        "gone_410": "status: 410" in gone and "purged by retention" in gone,
        "recording_started_nullable": 'recording_started_at: { type: ["string", "null"]' in api,
        "coverage_holes": "coverage_holes:" in api,
        "instrument_recorded": "recorded: { type: boolean }" in api,
        "recording_states": states,
        "history_bars_min_0": '"history_bars": { "type": "integer", "minimum": 0 }' in ws,
        "recording_started_at_ms": '"recording_started_at_ms": { "$ref": "#/$defs/epochMs" }' in ws,
        "auto_record_sentence": "triggers auto-record" in ws,
        "empty_bars_signal": "an empty `bars` array is its signal" in ws,
        "server_message_1824": "SOLUSDT recording started 00:04:12 ago" in ws,
        "mandate_2970": 'must render the documented "partial history" state' in db,
        "causes_21": causes_21,
        "seed_trades_days": int(seed) if seed != "MISSING" else 0,
        "backfilled_stays_gap": "A `backfilled` (kline) gap stays a gap" in d24,
        "restart_mapping": "`process_restart`→`backend_restart`" in d24,
        "stem_14": stem,
        "under_review_14": "Wording under review, not yet adopted:" in cat,
        "chip_14": chip_14,
        "checklist_boxes_047": boxes(scr047),
        "checklist_boxes_151": boxes(scr151),
        "cmp026_variants": variants,
        "registry_gap_row": "| `pattern.hatch.gap`" in d05 and "6 px pitch" in d05,
        "registry_absent_row": "| `pattern.hatch.absent`" in d05,
        "o7_closed": "**Closed — ruled 2026-10-20 18:30Z:**" in t["E11D04"],
        "hatched_band_26": "rendered as a hatched band with a label, never interpolated" in t["26"],
        "intervals": [(a.isoformat(), b.isoformat(), tier, n) for a, b, tier, n in intervals],
        "gaps": gap_rows,
        "generated_at": first(r'generated_at: "([^"]+)"', example),
    }


def fixture(facts: dict[str, Any]) -> dict[str, Any]:
    """The fixture, derived from the `22` data-coverage example by its own semantics (never typed)."""
    ivs = [(iso(a), iso(b), tier, n) for a, b, tier, n in facts["intervals"] if tier in ("parquet", "questdb")]
    trades = ivs[:2]  # the trades stream's two intervals (Parquet, then QuestDB); order-book follows
    gen = iso(facts["generated_at"])
    gap_from, gap_to, reason = (iso(facts["gaps"][0][0]), iso(facts["gaps"][0][1]), facts["gaps"][0][2])
    start = min(a for a, _, _, _ in trades)
    gap_seconds = int((gap_to - gap_from).total_seconds())
    window_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    chip_m = (gen.date() - window_start.date()).days + 1
    covered = sum(int((min(b, gen) - max(a, window_start)).total_seconds()) for a, b, _, _ in trades)
    gap_in_window = gap_seconds if window_start <= gap_from <= gen else 0
    chip_n = (covered - gap_in_window) // 86400
    retention_days = facts["seed_trades_days"]
    # The retention fixture: the same report viewed one retention period later. Its trim date (report minus
    # retention) lies after the recording start, so the whole days from the start to the trim date are a
    # `retention_purge` gap; the report's own trim date (gen minus retention) lies before the recording start,
    # where nothing was ever recorded, so it cannot host a retention frame (the lens's F-4).
    ret_report = gen.date() + dt.timedelta(days=retention_days)
    trim_d = ret_report - dt.timedelta(days=retention_days)
    trim = trim_d.isoformat()
    purged_days = (trim_d - start.date()).days
    ac2_min = 12  # US-REC-006 :4197 "the recorder was down for 12 minutes" (the tool checks the line)
    ac2_to = gap_from + dt.timedelta(minutes=ac2_min)
    zoom = {k: v for k, v in ZOOM.items()}
    for lvl in ("wide", "medium", "tight"):
        zoom[f"{lvl}_px"] = round(ac2_min * ZOOM[f"{lvl}_px_per_min"], 2)
        if float(zoom[f"{lvl}_px"]).is_integer():
            zoom[f"{lvl}_px"] = int(zoom[f"{lvl}_px"])
    hm = lambda d: d.strftime("%H:%M")  # noqa: E731
    return {
        "recording_started_date": start.date().isoformat(),
        "recording_started_time": hm(start),
        "recording_started": f"{start.date().isoformat()} {hm(start)} UTC",
        "generated_at": gen.date().isoformat(),
        "generated_time": hm(gen),
        "gap_date": gap_from.date().isoformat(),
        "gap_from": hm(gap_from),
        "gap_to": hm(gap_to),
        "gap_reason": reason,
        "gap_seconds": gap_seconds,
        "gap_human": humanise(gap_seconds),
        "gap_ranges": len([g for g in facts["gaps"]]),
        "rows_parquet": trades[0][3],
        "rows_questdb": trades[1][3],
        "covered_seconds": covered,
        "chip_n": chip_n,
        "chip_m": chip_m,
        "gap_ac2_min": ac2_min,
        "ac2_to": hm(ac2_to),
        "ac2_human": humanise(ac2_min * 60),
        "retention_days": retention_days,
        "retention_report_date": ret_report.isoformat(),
        "trim_date": trim,
        "purge_from_date": start.date().isoformat(),
        "retention_purged_days": purged_days,
        "zoom": zoom,
    }


def deck_rows(spec: str) -> list[tuple[str, str, str]]:
    """(key, string cell, source cell) for every row of the copy deck (section 14)."""
    out = []
    for ln in section(spec, 14, 15).splitlines():
        m = re.match(r"^\| `([^`]+)` +\| (.*?) +\| (.*?) +\|", ln)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def gates(files: list[Path], spec: str, facts: dict[str, Any], fx: dict[str, Any], t: dict[str, str]) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = deck_rows(spec)
    strings = {k: s for k, s, _ in deck}
    # (5) the copy gates on the deck
    for k, s, _ in deck:
        quoted = re.findall(r'"([^"]+)"', s)
        if k.startswith("rbac."):
            for q in quoted:
                if len(q) > LAYOUT["reason_max"] or not q.endswith(".") or re.search(r"\d|USDT|\{symbol\}", q):
                    bad.append(f"T2 reason names data or exceeds 60 chars [{k}: {q[:48]}]")
        if k.startswith(("empty.cause.", "empty.gap.")):
            for q in quoted:
                if len(q) > LAYOUT["cause_max"]:
                    bad.append(f"cause longer than 80 chars [{k}]")
        for p in BANNED_COPY:
            if re.search(p, " ".join(quoted), re.IGNORECASE):
                bad.append(f"banned word in user copy [{k}: {p}]")
        if k == "chip.partial" and re.search(r"\bonly\b", s):
            bad.append("the chip string carries 'only' (D05-C9)")
    for k in ("empty.gap.unknown", "empty.cause.recorded_only", "rbac.owner_only", "rbac.view_as", "chip.partial"):
        if k not in strings:
            bad.append(f"deck key missing: {k}")
    if "empty.gap.unknown" in strings and '"Recording gap."' not in strings["empty.gap.unknown"]:
        bad.append("unknown gap reason has no fallback [deck]")
    if "empty.gap.retention_purge" in strings and RECORDED_ONLY in strings["empty.gap.retention_purge"]:
        bad.append("retention cause identical to never-recorded cause [deck]")
    for reason in facts["gap_reasons_22"]:
        if reason == "never_recorded":
            continue
        if f"empty.gap.{reason}" not in strings:
            bad.append(f"no cause sentence for the `22` reason {reason}")
    # the stem byte for byte: every heading that claims the stem carries one of its two tails
    stem_tail = facts["stem_14"].split(" — ")[-1] if facts["stem_14"] != "MISSING" else "recording began then"
    # (6) the per-frame gates
    frames = frame_rows(spec)
    names = [n for n, _, _ in frames]
    for n in sorted({n for n in names if names.count(n) > 1}):
        bad.append(f"frame row repeated: {n}")
    scr047 = [(n, c) for n, c, s in frames if n.startswith("SCR-047/")]
    for n, c in scr047:
        if len(c) < 8:
            bad.append(f"frame {n}: the SCR-047 row has {len(c)} cells, 8 expected")
            continue
        heading, cause, ctrl, exit_, live, cls = c[2], c[3], c[4], c[5], c[6], c[7]
        if not heading:
            bad.append(f"frame {n}: heading missing")
        elif "BTCUSDT" not in heading and "{symbol}" not in heading and not re.search(r"History starts \d{4}-", heading):
            bad.append(f"frame {n}: heading names no symbol (E11-D04 :347)")  # the 1b stem is `14` :83's text
        if "History starts" in heading and not any(tail in heading for tail in STEM_TAILS):
            bad.append(f"stem text differs from 14 §0.5 rule 3 [{n}]")
        if "History starts" in heading and "recording began then" in heading and f"— {stem_tail}." not in heading:
            bad.append(f"stem text differs from 14 §0.5 rule 3 [{n}]")
        if n == "SCR-047/gap-retention-purge":
            if "retention policy (" not in cause:
                bad.append("retention frame: cause sentence missing")
            if RECORDED_ONLY in cause:
                bad.append("retention cause identical to never-recorded cause")
            if "`minus`" not in ctrl:
                bad.append("retention frame: distinct glyph missing")
            if "`Retention policy`" not in ctrl or "Owner" not in ctrl:
                bad.append("retention frame: Owner-only Retention policy link missing")
        elif not cause:
            bad.append(f"frame {n}: cause missing")
        if re.search(r"\block\b", ctrl, re.IGNORECASE) or re.search(r"\block\b", cls, re.IGNORECASE):
            bad.append(f"lock drawn on an absence frame [{n}]")
        if "sentence form" in cls:
            if "`Record this symbol`" in ctrl or re.search(r"\bbutton\b|CMP-001", ctrl):
                bad.append(f"sentence form carries a button [{n}]")
            if cls.startswith("T2") and not re.search(r"`rbac\.[a-z_]+`", cause):
                bad.append(f"sentence form names no rbac key [{n}]")
        if not any(e in exit_ for e in EXITS):
            bad.append(f"exit missing on {n}")
        if "not-trading" in n and LIVE_NOW in live:
            bad.append(f"live sentence on a frame where it is not true [{n}]")
        if LIVE_NOW in live and "where true" not in live:
            bad.append(f"live sentence without its condition [{n}]")
        if n == "SCR-047/in-situ" and not any(w in " ".join(c) for w in REC_CHIP):
            bad.append("recorder-status chip missing from the in-situ frame")
        if n in ("SCR-047/never-recorded-owner", "SCR-047/before-start") and RECORDED_ONLY not in cause:
            bad.append(f"history-start frame without the shared cause [{n}]")
    b02 = {n: c for n, c in scr047 if n in ("SCR-047/never-recorded-owner", "SCR-047/gap-ws-disconnect", "SCR-047/not-trading")}
    if len(b02) == 3:
        hs = [c[2] for c in b02.values()]
        cs = [c[3] for c in b02.values()]
        if len(set(hs)) != 3 or len(set(cs)) != 3:
            bad.append("the three reasons are not distinct in heading and cause (AC 1)")
    scr151 = [(n, c) for n, c, s in frames if n.startswith("SCR-151/")]
    for n, c in scr151:
        if len(c) < 7:
            bad.append(f"frame {n}: the SCR-151 row has {len(c)} cells, 7 expected")
            continue
        heading, cause, ctrl, ts, cls = c[2], c[3], c[4], c[5], c[6]
        if re.search(r"\block\b", ctrl, re.IGNORECASE):
            bad.append(f"lock drawn on an absence frame [{n}]")
        if "sentence form" in cls and ("`Record this symbol`" in ctrl or re.search(r"\bbutton\b|CMP-001", ctrl)):
            bad.append(f"sentence form carries a button [{n}]")
        if n == "SCR-151/recording-not-started" and not re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", ts):
            bad.append("recording-start timestamp missing")
        if n == "SCR-151/classes":
            for phrase in ("nothing created yet", "nothing matches the filter", "data not recorded yet"):
                if phrase not in c[1]:
                    bad.append(f"fewer than three SCR-151 classes [{phrase} missing]")
        if "History starts" in heading and not any(tail in heading for tail in STEM_TAILS):
            bad.append(f"stem text differs from 14 §0.5 rule 3 [{n}]")
    for n, c, _ in frames:
        joined = " ".join(c)
        if any(d in joined for d in DIMMING):
            bad.append(f"dimming on a sentence form [{n}]" if "sentence form" in c[-1] else f"dimming on a state frame [{n}]")
        if KEY_CHORD.search(joined) and "PROPOSED" not in joined:
            bad.append(f"key binding drawn as shipped without PROPOSED [{n}]")
        # the two families apart on EVERY frame table (BQ-16 RULED; the lens's F-1): the shared cause and the
        # 1b stem never on a gap-family frame; the 1a stem never on a gap, no-trades, restricted or band frame
        if GAP_FAMILY.search(n):
            if "Nothing is missing" in joined:
                bad.append(f"stem family cause on a gap frame [{n}]")
            if STEM_1B_TAIL in joined or (STEM_1A_NEVER.search(n) and STEM_1A_TAIL in joined):
                bad.append(f"stem heading on a gap frame [{n}]")
        if not n.startswith(("SCR-047/", "SCR-151/")) and re.search(r"\block\b", joined, re.IGNORECASE):
            bad.append(f"lock drawn on a state frame [{n}]")
        if "older than" in joined and "gap" in joined and "unknown" not in joined and "never" not in joined:
            bad.append(f"coverage older than the route's window drawn as a gap [{n}]")
    # every gap-family frame's cause is the deck's sentence for its reason (BQ-10; the lens's F-1)
    by_name = {n: c for n, c, _ in frames}
    for n, key in GAP_CAUSE_KEY.items():
        if n not in by_name or key not in strings:
            continue
        cause = by_name[n][3]
        wanted = re.findall(r'"([^"]+)"', strings[key])
        if "restricted" in n and "Not recording" in cause:
            bad.append(f"role-restricted frame reads 'Not recording' (E16-D02 :340) [{n}]")
        elif not any(w in cause for w in wanted):
            bad.append(f"gap frame cause is not the deck's sentence [{n}: {key}]")
    if NINETY_DAY not in section(spec, 3, 4):
        bad.append("the 90-day sentence is missing from section 3 (BQ-14 RULED)")
    chips = [(n, c) for n, c, s in frames if n.startswith("CHIP/")]
    for n, c in chips:
        if "Partial:" not in " ".join(c):
            bad.append(f"partial chip text missing [{n}]")
    gapz = [(n, c) for n, c, s in frames if n.startswith("GAP/") and s == 7]
    bands = [n for n, _ in gapz if n.startswith("GAP/band-")]
    if len(bands) < 3:
        bad.append("fewer than three zoom-level frames")
    for n, c in gapz:
        geometry, label = c[2], c[3]
        if not any(r in geometry for r in REGISTRY_IDS):
            bad.append(f"gap band not bound to a registry pattern [{n}]")
        if "dashed edges" not in geometry:
            bad.append(f"gap band without edges [{n}]")
        if not label:
            bad.append(f"gap band without a text label [{n}]")
        elif not any(v in label for v in VISIBLE_CARRIERS) and not IN_BAND_LABEL.search(label):
            bad.append(f"gap band without a visible text carrier [{n}]")
        if n == "GAP/backfilled-kline" and "band stays" not in geometry:
            bad.append("backfilled gap drawn as covered")
    gapt = {n: c for n, c, s in frames if n.startswith("GAP/") and s == 8}
    if "GAP/tooltip" in gapt:
        content = gapt["GAP/tooltip"][2].lower()
        for field in ("start", "end", "duration", "cause"):
            if not re.search(rf"\b{field}\b", content):
                bad.append(f"gap tooltip missing field: {field}")
    else:
        bad.append("GAP/tooltip row missing")
    if "GAP/causes" in gapt:
        if '"Recording gap."' not in gapt["GAP/causes"][2]:
            bad.append("unknown gap reason has no fallback")
    else:
        bad.append("GAP/causes row missing")
    # section 1.3: the view-as row first, the loading row a status
    s1 = section(spec, 1, 2)
    cls_rows = [cells(ln) for ln in s1.splitlines() if ln.startswith("| `Record this symbol`") or ln.startswith("| the pane while")]
    t2_rows = [c for c in cls_rows if "T2" in c[1]]
    if not t2_rows or "viewing as" not in t2_rows[0][0]:
        bad.append("view-as leg not first")
    if len(t2_rows) != 2 or not all("sentence form" in c[1] for c in t2_rows):
        bad.append("section 1.3: the two T2 rows are not both the sentence form")
    loading = [c for c in cls_rows if "CMP-029" in c[0]]
    if not loading or "status" not in loading[0][1] or "empty" in loading[0][1]:
        bad.append("spinner or skeleton classed as an empty state")
    if "No spinner path" not in s1 and "no spinner path" not in s1:
        bad.append("section 1.3: the no-spinner rule is not stated")
    # the view-as leg first in EVERY table that holds both legs (E09-D09 §2.1 step 3; the lens's F-2)
    pos = {n: i for i, (n, _, _) in enumerate(frames)}
    for sec, va, oo in (
        (4, "SCR-047/never-recorded-view-as", "SCR-047/never-recorded-sentence"),
        (5, "SCR-151/view-as", "SCR-151/sentence-form"),
    ):
        if va in pos and oo in pos and pos[va] > pos[oo]:
            bad.append(f"view-as leg not first in section {sec}")
    roles = [cells(ln) for ln in s1.splitlines() if re.match(r"^\| (?:Owner|Manager|Viewer|any role)", ln)]
    if not roles or "viewing as" not in roles[0][0]:
        bad.append("section 1.4: the viewing-as row is not first")
    # section 0 reconciles with the state tables
    s0 = section(spec, 0, 1)
    listed: dict[str, list[str]] = {}
    for ln in s0.splitlines():
        m = re.match(r"^\| (\d\d) +\| `E16-D05 / ", ln)
        if m:
            listed[m.group(1)] = re.findall(r"`((?:SCR-047|SCR-151|CHIP|GAP|SURF)/[a-z0-9-]+)`", cells(ln)[2])
    for board, names_ in listed.items():
        for va, oo in (("SCR-047/never-recorded-view-as", "SCR-047/never-recorded-sentence"), ("SCR-151/view-as", "SCR-151/sentence-form")):
            if va in names_ and oo in names_ and names_.index(va) > names_.index(oo):
                bad.append(f"view-as leg not first in section 0 [board {board}]")
    drawn = {n for k, v in listed.items() if k != "10" for n in v}
    for n in sorted(drawn - set(names)):
        bad.append(f"section 0 draws a frame the state tables lack: {n}")
    for n in sorted(set(names) - drawn):
        bad.append(f"state frame on no board of section 0: {n}")
    for n in sorted(set(listed.get("10", [])) - set(names)):
        bad.append(f"the light twin names an unknown frame: {n}")
    # cites, forbidden text, ids, closing keywords
    lines = {k: v.split("\n") for k, v in t.items()}
    CITE_WARN.clear()
    for doc, line_s, want in rows(CITED_TABLE, 2):
        line = int(line_s)
        shift = sum(POINTER in ln for ln in lines[doc][: line - 1 + 2]) if doc == "14" else 0
        found = [i + 1 for i, ln in enumerate(lines[doc]) if want in ln]
        total = sum(ln.count(want) for ln in lines[doc])
        if total == 0:
            bad.append(f"cited text gone: `{doc}` :{line} {want[:40]!r} (nowhere in the file)")
        elif total > 1:
            bad.append(f"cited text ambiguous: `{doc}` :{line} {want[:40]!r} ({total} matches: use a longer needle)")
        elif found[0] not in (line, line + shift):
            CITE_WARN.append(f"`{doc}` :{line} now at :{found[0]} ({want[:40]!r})")
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {c}")
        for word in ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"):
            if re.search(rf"\b{word}\b\s+#\d+", txt, re.IGNORECASE):
                bad.append(f"{f.name}: closing keyword before an issue number (text-first PR)")
    # contract facts the spec leans on
    if len(facts["gap_reasons_22"]) != 7:
        bad.append(f"`22`: {len(facts['gap_reasons_22'])} gap reasons, the spec assumes 7")
    if "paused" in facts["recording_states"]:
        bad.append("`22`: RecordingState gained `paused` — D05-C4 is stale")
    if len(facts["cmp026_variants"]) != 5:
        bad.append(f"`15`: CMP-026 has {len(facts['cmp026_variants'])} variants, the spec assumes 5")
    for k in (
        "open_ended", "coverage_rbac", "no_data_recorded_422", "gone_410", "recording_started_nullable",
        "coverage_holes", "instrument_recorded", "history_bars_min_0", "recording_started_at_ms",
        "auto_record_sentence", "empty_bars_signal", "server_message_1824", "mandate_2970",
        "backfilled_stays_gap", "restart_mapping", "under_review_14", "registry_gap_row",
        "registry_absent_row", "o7_closed", "hatched_band_26",
    ):
        if not facts[k]:
            bad.append(f"contract fact gone: {k}")
    if facts["stem_14"] == "MISSING" or facts["chip_14"] == "MISSING":
        bad.append("`14`: the stem or the chip illustration is gone")
    if fx["chip_n"] >= fx["chip_m"]:
        bad.append("fixture: the chip is not partial (n >= m)")
    if fx["retention_purged_days"] <= 0:
        bad.append("fixture: the retention trim date is not after the recording start (no retention_purge gap)")
    return bad


# ---- the 39 mutations of spec section 12 (in memory; each must produce its own FAIL) -------------
def _row_edit(spec: str, frame: str, col: int, fn: Callable[[str], str]) -> str:
    out = []
    done = False
    for ln in spec.split("\n"):
        if not done and re.match(rf"^\| `{re.escape(frame)}` +\|", ln):
            c = cells(ln)
            c[col] = fn(c[col])
            ln = "| " + " | ".join(c) + " |"
            done = True
        out.append(ln)
    if not done:
        raise SystemExit(f"mutation target not found: {frame}")
    return "\n".join(out)


def _row_delete(spec: str, frame: str) -> str:
    return "\n".join(ln for ln in spec.split("\n") if not re.match(rf"^\| `{re.escape(frame)}` +\|", ln))


def _swap_rows(spec: str, a_start: str, b_start: str) -> str:
    lines = spec.split("\n")
    ia = next(i for i, ln in enumerate(lines) if ln.startswith(a_start))
    ib = next(i for i, ln in enumerate(lines) if ln.startswith(b_start))
    lines[ia], lines[ib] = lines[ib], lines[ia]
    return "\n".join(lines)


def _deck_edit(spec: str, key: str, old: str, new: str) -> str:
    out, done = [], False
    for ln in spec.split("\n"):
        if not done and ln.startswith(f"| `{key}`"):
            ln, done = ln.replace(old, new), True
        out.append(ln)
    return "\n".join(out)


def _class_edit(spec: str, row_start: str, old: str, new: str) -> str:
    out, done = [], False
    for ln in spec.split("\n"):
        if not done and ln.startswith(row_start):
            ln, done = ln.replace(old, new), True
        out.append(ln)
    return "\n".join(out)


MUTATIONS: list[tuple[str, Callable[[str], str], str]] = [
    ("SCR-047/never-recorded-owner: the heading cell emptied", lambda s: _row_edit(s, "SCR-047/never-recorded-owner", 2, lambda c: ""), "frame SCR-047/never-recorded-owner: heading missing"),
    ("SCR-047/gap-retention-purge: the cause cell emptied", lambda s: _row_edit(s, "SCR-047/gap-retention-purge", 3, lambda c: ""), "retention frame: cause sentence missing"),
    ("SCR-047/gap-retention-purge: the cause replaced by empty.cause.recorded_only", lambda s: _row_edit(s, "SCR-047/gap-retention-purge", 3, lambda c: f'"{RECORDED_ONLY}"'), "retention cause identical to never-recorded cause"),
    ("SCR-047/never-recorded-sentence: ' lock' appended to the control cell", lambda s: _row_edit(s, "SCR-047/never-recorded-sentence", 4, lambda c: c + " lock"), "lock drawn on an absence frame"),
    ("SCR-047/never-recorded-sentence: a Record this symbol button added", lambda s: _row_edit(s, "SCR-047/never-recorded-sentence", 4, lambda c: c + " · `Record this symbol` button (CMP-001)"), "sentence form carries a button"),
    ("section 1.3: the view-as row moved below the owner-only row", lambda s: _swap_rows(s, "| `Record this symbol` while viewing as", "| `Record this symbol` for a session without"), "view-as leg not first"),
    ("SCR-047/not-trading: 'Live data is streaming now.' added", lambda s: _row_edit(s, "SCR-047/not-trading", 6, lambda c: f'"{LIVE_NOW}" where true'), "live sentence on a frame where it is not true"),
    ("SCR-047/before-start: the exit Go to recorded history removed", lambda s: _row_edit(s, "SCR-047/before-start", 5, lambda c: c.replace("`Go to recorded history`", "")), "exit missing on SCR-047/before-start"),
    ("SCR-151/recording-not-started: the timestamp removed", lambda s: _row_edit(s, "SCR-151/recording-not-started", 5, lambda c: "—"), "recording-start timestamp missing"),
    ("CHIP/partial-days: 'Partial:' removed", lambda s: _row_edit(s, "CHIP/partial-days", 2, lambda c: c.replace("Partial:", "")), "partial chip text missing"),
    ("<!-- audit:chip_n=13 --> changed to 12", lambda s: s.replace("<!-- audit:chip_n=13 -->", "<!-- audit:chip_n=12 -->"), "marker audit:chip_n=12 vs tool 13"),
    ("GAP/band-tight: the label cell emptied", lambda s: _row_edit(s, "GAP/band-tight", 3, lambda c: ""), "gap band without a text label"),
    ("GAP/band-medium: 'dashed edges' removed", lambda s: _row_edit(s, "GAP/band-medium", 2, lambda c: c.replace("dashed edges", "edges")), "gap band without edges"),
    ("GAP/tooltip: 'duration' removed", lambda s: _row_edit(s, "GAP/tooltip", 2, lambda c: re.sub(r"(?i)duration", "", c)), "gap tooltip missing field: duration"),
    ("GAP/tooltip: 'cause' removed", lambda s: _row_edit(s, "GAP/tooltip", 2, lambda c: re.sub(r"(?i)cause", "", c)), "gap tooltip missing field: cause"),
    ("GAP/backfilled-kline: 'band stays' -> 'band removed'", lambda s: _row_edit(s, "GAP/backfilled-kline", 2, lambda c: c.replace("band stays", "band removed")), "backfilled gap drawn as covered"),
    ("GAP/band-wide: the row deleted", lambda s: _row_delete(s, "GAP/band-wide"), "fewer than three zoom-level frames"),
    ("a Ctrl+R chord added to the CTA cell without PROPOSED", lambda s: _row_edit(s, "SCR-047/never-recorded-owner", 4, lambda c: c + " · `Ctrl+R`"), "key binding drawn as shipped without PROPOSED"),
    ("SCR-047/in-situ: the REC chip text removed", lambda s: _row_edit(s, "SCR-047/in-situ", 1, lambda c: c.replace("Not recording · limit reached", "")), "recorder-status chip missing from the in-situ frame"),
    ("<!-- audit:frames_scr047=13 --> decremented", lambda s: s.replace("<!-- audit:frames_scr047=13 -->", "<!-- audit:frames_scr047=12 -->"), "marker audit:frames_scr047=12 vs tool 13"),
    ("the rbac.owner_only string replaced by E11-D04 :798's draft", lambda s: _deck_edit(s, "rbac.owner_only", OWNER_ONLY, DRAFT_798), "T2 reason names data or exceeds 60 chars"),
    ("GAP/causes: the fallback 'Recording gap.' removed", lambda s: _row_edit(s, "GAP/causes", 2, lambda c: c.replace('"Recording gap."', '""')), "unknown gap reason has no fallback"),
    ("SCR-151/sentence-form: opacity.disabled added to its controls cell", lambda s: _row_edit(s, "SCR-151/sentence-form", 4, lambda c: c + " `opacity.disabled`"), "dimming on a sentence form"),
    ("section 1.3: the loading row's class 'status' -> 'empty'", lambda s: _class_edit(s, "| the pane while", "**status (loading)**", "**empty (loading)**"), "spinner or skeleton classed as an empty state"),
    ("GAP/band-tight: pattern.hatch.gap removed", lambda s: _row_edit(s, "GAP/band-tight", 2, lambda c: c.replace("`pattern.hatch.gap`", "the hatch")), "gap band not bound to a registry pattern"),
    ("SCR-151/classes: 'nothing matches the filter' removed", lambda s: _row_edit(s, "SCR-151/classes", 1, lambda c: c.replace("nothing matches the filter", "a filtered list")), "fewer than three SCR-151 classes"),
    ("SCR-047/before-start: the stem altered to 'recording started then'", lambda s: _row_edit(s, "SCR-047/before-start", 2, lambda c: c.replace("recording began then", "recording started then")), "stem text differs from 14 §0.5 rule 3"),
    ("SCR-047/gap-ws-disconnect: the stem family's sentence added to its cause", lambda s: _row_edit(s, "SCR-047/gap-ws-disconnect", 3, lambda c: c + f' "{RECORDED_ONLY}"'), "stem family cause on a gap frame"),
    # 29-39: the pre-PR design-review lens round 1 (F-1, F-2, F-3)
    ("SCR-047/gap-ws-disconnect: the 1b stem put in its heading", lambda s: _row_edit(s, "SCR-047/gap-ws-disconnect", 2, lambda c: '"History starts 2026-09-01 00:00 UTC — recording began then."'), "stem heading on a gap frame [SCR-047/gap-ws-disconnect]"),
    ("GAP/band-tight: the stem family's sentence added to its label cell", lambda s: _row_edit(s, "GAP/band-tight", 3, lambda c: c + f' "{RECORDED_ONLY}"'), "stem family cause on a gap frame [GAP/band-tight]"),
    ("SCR-047/gap-ws-disconnect: the cause replaced by 'Something happened.'", lambda s: _row_edit(s, "SCR-047/gap-ws-disconnect", 3, lambda c: '"Something happened."'), "gap frame cause is not the deck's sentence"),
    ("section 3: the 90-day sentence reworded to 'shown as a gap'", lambda s: s.replace(NINETY_DAY, "shown as a gap"), "the 90-day sentence is missing from section 3"),
    ("CHIP/partial-days: ' lock' appended to the look cell", lambda s: _row_edit(s, "CHIP/partial-days", 3, lambda c: c + " lock"), "lock drawn on a state frame"),
    ("SCR-047/role-restricted: the cause replaced by 'Not recording'", lambda s: _row_edit(s, "SCR-047/role-restricted", 3, lambda c: '"Not recording"'), "role-restricted frame reads 'Not recording'"),
    ("section 4: the view-as row moved below the owner-only row", lambda s: _swap_rows(s, "| `SCR-047/never-recorded-view-as`", "| `SCR-047/never-recorded-sentence`"), "view-as leg not first in section 4"),
    ("section 5: the view-as row moved below the owner-only row", lambda s: _swap_rows(s, "| `SCR-151/view-as`", "| `SCR-151/sentence-form`"), "view-as leg not first in section 5"),
    ("section 1.4: the viewing-as row moved below the Owner row", lambda s: _swap_rows(s, "| any role, viewing as", "| Owner "), "section 1.4: the viewing-as row is not first"),
    ("section 0 board 03: the view-as frame listed after the owner-only frame", lambda s: _class_edit(s, "| 03  ", "`SCR-047/never-recorded-view-as`, `SCR-047/never-recorded-sentence`", "`SCR-047/never-recorded-sentence`, `SCR-047/never-recorded-view-as`"), "view-as leg not first in section 0 [board 03]"),
    ("GAP/band-wide: the axis tag removed from its label cell", lambda s: _row_edit(s, "GAP/band-wide", 3, lambda c: c.replace("`gap.axis.tag`", "the tag")), "gap band without a visible text carrier"),
]


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def numbers_of(spec: str, facts: dict[str, Any], fx: dict[str, Any], themes: dict[str, dict[str, object]], registered: set[tuple[str, str]]) -> tuple[dict[str, Any], list[dict[str, object]], list[str], int]:
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(tk, fg), resolve(tk, bg)) for th, tk in themes.items()}
        bar = BAR.get(role)
        if bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            gated += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            fails += verdict == "FAIL"
            proposed += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        row: dict[str, object] = {"element": element, "fg": fg, "bg": bg, "role": role, "verdict": verdict, "pairs": reg}
        row.update({k: round(v, 4) for k, v in ratios.items()})
        matrix.append(row)
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    frames = frame_rows(spec)
    names = [n for n, _, _ in frames]
    deck = deck_rows(spec)
    by_source: dict[str, int] = {}
    for _, _, src in deck:
        key = "new" if src.startswith("new") else src.split(" ")[0].strip("`*")
        by_source[key] = by_source.get(key, 0) + 1
    s0 = section(spec, 0, 1)
    board_frames = {}
    for ln in s0.splitlines():
        m = re.match(r"^\| (\d\d) +\| `E16-D05 / ", ln)
        if m:
            board_frames[m.group(1)] = len(set(re.findall(r"`((?:SCR-047|SCR-151|CHIP|GAP|SURF)/[a-z0-9-]+)`", cells(ln)[2])))
    s2 = section(spec, 2, 3)
    gap_causes = sum(f"`{r}`" in s2 for r in facts["gap_reasons_22"]) + ("an unknown reason" in s2)
    n: dict[str, Any] = {
        "boards": count(r"^\| \d\d +\| `E16-D05 / ", s0),
        "light_twins": count(r"^\| \d\d +\| `E16-D05 / [^`]*light", s0),
        "frames_total": len(names),
        "frames_scr047": sum(x.startswith("SCR-047/") for x in names),
        "frames_scr151": sum(x.startswith("SCR-151/") for x in names),
        "frames_chip": sum(x.startswith("CHIP/") for x in names),
        "frames_gap": sum(x.startswith("GAP/") for x in names),
        "frames_surf": sum(x.startswith("SURF/") for x in names),
        "zoom_frames": sum(x.startswith("GAP/band-") for x in names),
        "board_frames": board_frames,
        "gap_causes": gap_causes,
        "reasons_22": len(facts["gap_reasons_22"]),
        "causes_21": len(facts["causes_21"]),
        "recording_states": len(facts["recording_states"]),
        "cmp026_variants": len(facts["cmp026_variants"]),
        "bq_rows": count(r"^\| BQ-\d+ ", spec),
        "d_rows": len(set(re.findall(r"\*\*D05-D(\d+)\*\*", section(spec, 13, 14)))),
        "checklist_047": facts["checklist_boxes_047"],
        "checklist_151": facts["checklist_boxes_151"],
        "checklist_items": count(r"^\| 14:(?:1089|2924) ", spec),
        "flows": count(r"^\| F\d ", spec),
        "mutations": len(MUTATIONS),
        "deck_rows": len(deck),
        "deck_new": by_source.get("new", 0),
        "deck_by_source": by_source,
        "rbac_keys": sum(k.startswith("rbac.") for k, _, _ in deck),
        "pairs_rows": gated,
        "pairs_registered": gated - proposed,
        "pairs_proposed": proposed,
        "pairs_fail": fails,
        "missing_tokens": len(missing),
        "registry_ids": len(REGISTRY_IDS),
        "reason_max": LAYOUT["reason_max"],
        "cause_max": LAYOUT["cause_max"],
        "opacity_disabled": float(resolve(themes["dark"], "opacity.disabled")),
        "layout": LAYOUT,
        "zoom": fx["zoom"],
        "fixture": {k: v for k, v in fx.items() if k != "zoom"},
        "chip_n": fx["chip_n"],
        "chip_m": fx["chip_m"],
    }
    n.update({k: count(rf"^\| D05-{p}\d+ ", spec) for k, p in ROW_IDS})
    return n, matrix, missing, fails


def run(spec: str, t: dict[str, str], themes: dict[str, dict[str, object]], registered: set[tuple[str, str]], extra: list[Path], check: bool) -> tuple[list[str], dict[str, Any], list[dict[str, object]], list[str], int]:
    facts = contract_facts(t)
    fx = fixture(facts)
    bad = gates([SPEC, *extra], spec, facts, fx, t)
    numbers, matrix, missing, fails = numbers_of(spec, facts, fx, themes, registered)
    numbers["facts"] = {k: v for k, v in facts.items() if k not in ("intervals", "gaps")}
    if check:
        flat = flatten(numbers)
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except (TypeError, ValueError):
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
    return bad, numbers, matrix, missing, fails


def self_test(spec: str, t: dict[str, str], themes: dict[str, dict[str, object]], registered: set[tuple[str, str]]) -> int:
    base_bad, _, _, _, base_fails = run(spec, t, themes, registered, [], True)
    out = []
    ok = not base_bad and not base_fails
    out.append("unmutated spec: " + ("PASS" if ok else "FAIL — " + "; ".join(base_bad[:5])))
    signatures: dict[int, str] = {}
    for i, (desc, fn, needle) in enumerate(MUTATIONS, 1):
        bad, _, _, _, _ = run(fn(spec), t, themes, registered, [], True)
        hits = [b for b in bad if b.startswith(needle)]
        if not bad:
            ok = False
            out.append(f"mutation {i:2d} PASSED THE GATES (defect): {desc}")
        elif not hits:
            ok = False
            out.append(f"mutation {i:2d} failed for another reason (defect): {desc} — {bad[0][:80]}")
        else:
            signatures[i] = hits[0]
            out.append(f"mutation {i:2d} FAIL as expected: {hits[0]}")
    sigs = list(signatures.values())
    dup = sorted({s for s in sigs if sigs.count(s) > 1})
    if dup:
        ok = False
        out.append("duplicate FAIL messages: " + " | ".join(dup))
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(set(sigs))} distinct FAIL messages, the unmutated spec "
        + ("passes" if not base_bad else "FAILS")
        + " — "
        + ("OK" if ok else "DEFECT")
    )
    print("\n".join(out))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    t = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    spec = SPEC.read_text(encoding="utf-8")
    if "--self-test" in argv:
        return self_test(spec, t, themes, registered)
    mode = None
    if "--mutate" in argv:
        mode = int(argv[argv.index("--mutate") + 1])
        desc, fn, needle = MUTATIONS[mode - 1]
        spec = fn(spec)
    bad, numbers, matrix, missing, fails = run(spec, t, themes, registered, extra, "--check" in argv or mode is not None)
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        palette_aliases = {th: {n: resolve(tk, n) for n in CHART_ALIASES} for th, tk in themes.items()}
        payload = {"numbers": numbers, "matrix": matrix, "missing": missing, "problems": bad, "cite_warnings": CITE_WARN}
        payload.update({"palette": palette, "chart_aliases": palette_aliases, "registry_ids": list(REGISTRY_IDS)})
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 1 if fails or bad else 0
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    for r in matrix:
        out.append(f"{r['fg']} on {r['bg']} | {r['role']} | {show(float(r['dark']))} / {show(float(r['light']))} / {show(float(r['high-contrast']))} | {r['verdict']} | {r['pairs']} | {r['element']}")
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    out += [f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS]
    out += [f"{alias} → {target} | {' / '.join(resolve(tk, alias)[:40] for tk in themes.values())}" for alias, target in CHART_ALIASES.items()]
    out.append(f"registry ids (not tokens): {', '.join(REGISTRY_IDS)}; MISSING tokens: {missing}")
    out.append("\n## 3-4. Contract facts and the derived fixture:")
    out.append(json.dumps({"facts": numbers["facts"], "fixture": numbers["fixture"], "zoom": numbers["zoom"]}, ensure_ascii=False))
    ok = (
        "OK — every SCR-047 row names the symbol, a cause and an exit; the retention cause, glyph and link distinct; "
        "no lock, no button, no dimming on any absence frame; the view-as row first in every table; the rbac reasons within 60 chars naming no data; "
        "the stem families apart on every table; every gap frame's cause the deck's; every band frame bound to the registry with dashed edges and a visible label; the backfilled band stays; "
        "three zoom frames; the tooltip's four fields; the fallback present; every chip row Partial:; the in-situ chip; no shipped chord; "
        "the loading row a status; the 90-day sentence kept; the retention fixture after the start; no closing keyword; no private path; every cited text exists"
    )
    out.append("\n## 5-6. Copy and frame gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    if "--check" in argv or mode is not None:
        clean = not any(b.startswith("marker") for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
    out.append("\n## 7. Counts: " + json.dumps({k: v for k, v in numbers.items() if k != "facts"}, ensure_ascii=False))
    if mode is not None:
        desc, fn, needle = MUTATIONS[mode - 1]
        hits = [b for b in bad if b.startswith(needle)]
        out.append(f"\n## mutation {mode} ({desc}): {len(hits)} targeted FAIL of {len(bad)} — " + ("as expected (rc 1: the gate caught it)" if hits else "UNEXPECTED (rc 2: the mutation slipped through)"))
        print("\n".join(out))
        return 1 if hits else 2
    print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
