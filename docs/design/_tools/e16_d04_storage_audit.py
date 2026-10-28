#!/usr/bin/env python3
"""E16-D04 SCR-142 storage and database panel audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged upstream specs and the spec AS TEXT and
prints: (1) the WCAG 2.x ratio of every fg / bg pair SCR-142 renders in dark / light / high-contrast
(`themes.json` layering): the words on the admin canvas and the cards, the two meters' fills on their
track, the tier tone glyphs, the T2 pair, the validity composite, the status subtle fills, the
sparkline stroke; (2) every token the spec binds, resolved or MISSING; (3) the contract facts the
boards quote, parsed from `22` / `23` / `21` / `20` / `24` / `14` / `15` text (the `StorageUsage` field
list, the `level` enum, the gate reasons, the five `Job.status` words, the `Job.kind` list and the
ABSENCE of a vacuum or compaction kind and of a cancel route, the three routes' `x-rbac`, the purge
body's four required fields (`before` among them), the 366-day cap, the section 5.4 compaction thresholds, the `CV_DISK_*` steps,
the SCR-142 checklist's six boxes, the six CMP headings, the `ComponentState` words, the health
example's component names); (4) the fixture, derived from the `22` `getStorageUsage` example and its
level, health, lag, migration and import variants, every size with a unit, every date ISO, and the
example's own inconsistency recorded (the symbols sum against the budget), never corrected; (5) the
copy gates (every `rbac.*` sentence within 60 characters naming no data, the degradation-order
sentence in the deck, the banned words, no private path or host, every cited id and line still valid,
no closing keyword, the PENDING siblings by name only); (6) the gates (spec section 12, rules R-1 to R-22),
read over the WHOLE spec: every frame row cell by cell and item by item (a quoted string never split), every other
table row (section 1.3's classes, section 6's action table, the copy deck's closed key set), every prose sentence and
the sketch; each ruled sentence has a case-insensitive vocabulary with synonyms (a lock: lock, padlock, T2, CMP-079,
RbacGate; a disabled control: disabled, greyed / grayed, dimmed, faded, inert, unavailable, blocked, gated, can't /
cannot be pressed or used, aria-disabled, opacity.disabled; a page banner: banner, callout, toast, alert, page error,
top of the page / screen; a stalled bar; a pre-filled field: pre-filled, auto-filled, pre-populated, defaulted); a
negator exempts a match only within four words before it in the same clause; an item without a subject reads the
write named earlier in its unit; every PROPOSED carrier carries its own caption "PROPOSED — D04-Gn, owner approval
pending (#2701)" with its n, and no unit presents a PROPOSED item as shipped; every exit a frame lists is
present and T1; every number any unit types is a `--json` value with its unit (R-17's register: the fixture,
the facts, the layout, the counts and the typed context); (7) the counts the spec, the boards and the PR body quote;
(8) R-23, the backstop behind the vocabularies (the orchestrator's gate re-checks 2 and 3: whole-document
default-deny): EVERY unit of the spec (a Markdown block: a heading, a run of consecutive non-blank lines, i.e. each
paragraph, list block and table block, the deck included, and the fenced sketch whole; a soft-wrapped line belongs to
its block) is pinned by region (the heading path plus occurrence), place and exact text in RULED_PIN_TXT at the end of
this file; a changed, moved, duplicated or missing unit, a unit or region the pins do not hold and a duplicate location
FAIL naming the location. Only PIN_EXEMPT is left unpinned (the `audit:` markers and the number before each, which
`--check` gates exactly). `--repin-ruled` rewrites the table from the spec (deliberate; `--check` never re-pins). An
R-23 FAIL is reported only when no other gate FAILs, else counted beside it on a NOTE line, so one wrong form yields one FAIL.
`--json` feeds the check-nums script; `--check` re-derives the spec's `<!-- audit:key=N -->` markers and checks
the number printed before each; `--self-test` applies the numbered mutations in memory, one at a time,
and passes only when each makes `--check` fail with ONE FAIL, its own expected message (rc 1), no two
share a message, the valid twins raise nothing once re-pinned (R-23 alone refuses them until then), the unmutated
spec passes and the spec file is byte-identical
afterwards; `--mutate N` prints one mutation's gate output and exits rc 1 when the targeted FAIL is the only
FAIL (the gate caught it), rc 2 when the mutation slips through or fails elsewhere (a defect in the gate), never 0.
Every other mode exits 1 on a gated FAIL.

Usage: python3 -I docs/design/_tools/e16_d04_storage_audit.py [--json] [--check] [--self-test]
  [--mutate N] [--extra F] [--repin-ruled]
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E16" / "E16-D04.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES = {"dark": (PRIM, DARK), "light": (PRIM, DARK, LIGHT), "high-contrast": (PRIM, DARK, HC)}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
MULTI = re.MULTILINE
# Generic patterns only (a home path with a user name in it, a Penpot host, a team or file id): no personal word,
# no folder name, no hostname whole or split.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
)
# Jargon the copy deck (section 14) never shows a user; checked on the deck's String column only.
BANNED_COPY = (
    r"client-side",
    r"server-side",
    r"\bbackend\b",
    r"\bendpoint\b",
    r"\b(?:409|422|503)\s+[a-z]+_[a-z_]+\b",
    r"\bHTTP\b",
    r"\bsorry\b",
    r"\boops\b",
)
VIEW_AS = "Read-only while viewing as {user}."
NOTICE_D16 = "Read-only — read-only while viewing as {user}."
# AC 2 (the ticket): the degradation order, stated in text on every level >= 1 frame (R-5).
DEGRADATION = "Recording pauses before trading is affected."
# The purge step-up sentence (E16-D02 section 6.4 / 6.5) and the audit line.
STEPUP = "You'll confirm with your password and a code."
AUDITED = "This action is audited."
NOTHING_DELETED = "Nothing is deleted."
# E16-D02 section 3.2 (:203 / :200): the job outcome copy SCR-142 reuses by key (R-20).
COMPACT_FAILED = "Compaction failed (`<code>`); nothing was deleted."
PURGE_FAILED_TAIL = "failed (`<code>`). Some data may already be deleted: check"
# element | fg | bg | role — every pair SCR-142 draws (spec section 15, rows in order).
PAIRS_TABLE = """
page words on the admin canvas | color.text.primary | color.surface.canvas | text
secondary words on the canvas (the projection line, the stamp) | color.text.secondary | color.surface.canvas | text
card words (tier rows, table cells on even rows) | color.text.primary | color.surface.raised | text
captions, units, reasons, the T2 reason on raised | color.text.secondary | color.surface.raised | text
T2 label and lock; tertiary words (the stamp's cadence) on raised | color.text.tertiary | color.surface.raised | text
table header words | color.text.primary | color.surface.hover | text
field value in the well (import form, purge dialog) | color.text.primary | color.surface.app | text
field well boundary | color.text.tertiary | color.surface.app | non-text
meter fill level 0 on its track | color.action.primary.default | color.surface.sunken | non-text
meter fill level 1 and 2 on its track | color.status.warning.strong | color.surface.sunken | non-text
meter fill level 3 on its track | color.status.danger.default | color.surface.sunken | non-text
health glyph ok on the card | color.status.success.strong | color.surface.raised | non-text
health glyph warning on the card | color.status.warning.strong | color.surface.raised | non-text
health glyph down on the card | color.status.danger.strong | color.surface.raised | non-text
warning banner and skipped-row words | color.text.primary | color.status.warning.subtle | text
warning banner glyph | color.status.warning.strong | color.status.warning.subtle | non-text
import failed words (inside the card) | color.text.primary | color.status.danger.subtle | text
import failed glyph | color.status.danger.strong | color.status.danger.subtle | non-text
job succeeded words | color.text.primary | color.status.success.subtle | text
job succeeded glyph | color.status.success.strong | color.status.success.subtle | non-text
info line words (overlap report) | color.text.primary | color.status.info.subtle | text
info line glyph | color.status.info.strong | color.status.info.subtle | non-text
primary button label (Import archives, Compact) | color.text.on-action | color.action.primary.default | text
destructive Confirm label on the danger fill (Purge) | color.text.on-action | color.status.danger.default | text
sparkline stroke on the card (PROPOSED inset) | color.text.tertiary | color.surface.raised | non-text
stale clock glyph on raised | color.data-confidence.stale.indicator | color.surface.raised | non-text
invalid well boundary | color.status.danger.default | color.surface.raised | non-text
focus ring on the canvas | color.focus.ring | color.surface.canvas | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.admin-tint",
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.hover",
    "color.surface.sunken",
    "color.surface.overlay",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.disabled",
    "color.text.on-action",
    "color.border.default",
    "color.border.subtle",
    "color.focus.ring",
    "color.action.primary.default",
    "color.status.success.strong",
    "color.status.success.subtle",
    "color.status.warning.strong",
    "color.status.warning.subtle",
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.danger.subtle",
    "color.status.info.strong",
    "color.status.info.subtle",
    "color.data-confidence.stale.indicator",
    "color.neutral.default",
    "opacity.disabled",
    "size.row.comfortable",
    "size.control.height",
    "size.icon.sm",
    "radius.card",
    "radius.control",
    "radius.badge",
    "space.inset.md",
    "space.inset.sm",
    "space.inset.xs",
    "space.stack.xs",
    "space.stack.sm",
    "elevation.card",
    "type.ui.heading-lg",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.label",
    "type.ui.caption",
    "type.num.base",
    "type.num.sm",
    "font.family.mono",
    "motion.duration.normal",
)
# doc | line | needle — every `:N` the spec cites, checked against the file (once at the line: OK;
# once elsewhere: WARN naming the current line; gone: FAIL; ambiguous: FAIL). `14` lines after the
# pointer line shift by the pointer line (POINTER), as E16-D03's tool allows.
CITED_TABLE = """
14 | 43 | require role `owner` **and** an admin re-auth token ≤15 min old (see SCR-149)
14 | 84 | last-good timestamp always shown
14 | 85 | **RBAC denies server-side; the UI presents.**
14 | 86 | no information by colour alone
14 | 2768 | E16-D03.md](../design/E16/E16-D03.md)
14 | 2770 | ### SCR-142 — Admin: storage & database panel
14 | 2772 | QuestDB, Postgres and Parquet/DuckDB status: size, row counts by table
14 | 2774 | healthy · migration pending (banner with the version delta) · lag warning · read-only mode (disk full)
14 | 2777 | with size, row counts, oldest/newest timestamps and health; all figures have units; health is text
14 | 2778 | sampled server-side every 60 s, not computed on request
14 | 2779 | `storage.compaction_triggered`, `storage.vacuum_triggered`, `storage.tier_migration_triggered`
14 | 2780 | recording pauses before trading is affected - stated
14 | 2795 | questdb 41GB - postgres 1.2GB - parquet 88GB
22 | 380 | `compactRecorder`, `importTradeArchive` and `purgeRecordedData` keep theirs: at most 256 jobs
22 | 722 | The typed confirm_symbol does not equal the symbol to purge
22 | 728 | code: import_range_invalid
22 | 5413 | operationId: getStorageUsage
22 | 5424 | the `questdb` plus `parquet` `tiers[]` bytes by `cap_bytes`
22 | 5435 | disk_total_bytes: 4000000000000
22 | 5446 | { tier: questdb, used_bytes: 640000000000, retention_days: 7 }
22 | 10991 | operationId: getHealth
22 | 11019 | detail: "ingest 18.4k msg/s"
22 | 11103 | Dependencies reachable and migrations applied
22 | 11809 | (`checksum_mismatch` when the stored digest does
22 | 12105 | operationId: getJob
22 | 12117 | Every `404` here carries rule `job_unknown`
22 | 12495 | `recorder_purge` are no-grace: the response is `single_use: true` and no window is opened
22 | 14395 | CHECK (migration 0008, `21-database-schema.md` §3.10.2)
22 | 14937 | operationId: compactRecorder
22 | 14942 | One compaction at a time (`409 job_running`)
22 | 14978 | operationId: importTradeArchive
22 | 14982 | `[from, to]` (inclusive UTC dates, at most 366 days)
22 | 14983 | Recorded data wins: rows inside a
22 | 14985 | archive-derived and cover `trades` only
22 | 14988 | Audited as `recorder.import`
22 | 15032 | operationId: purgeRecordedData
22 | 15035 | Requires a fresh step-up, a mandatory reason, an explicit
22 | 15040 | `recorder_purge` is a no-grace step-up class
22 | 15043 | `action_class` set to `recorder_purge`
22 | 15045 | `422 retention_pinned_refused`
22 | 15051 | **Window.** `before` is required
22 | 15054 | by this request or by any retry of it. A `before` later than the server's clock is
22 | 15055 | validation_failed` with `errors: [{field: before, rule: before_in_future}]`
22 | 15073 | The audit record (`retention.purge`, exact window, partition count, rows, bytes)
22 | 15086 | required: [symbol, confirm_symbol, reason, before]
22 | 17419 | enum: [healthy, degraded, warning, down, not_deployed]
22 | 19221 | tier: { type: string, enum: [questdb, parquet, postgres] }
22 | 19235 | level: { type: integer, enum: [0, 1, 2, 3] }
22 | 21860 | last_good_at: { type: ["string", "null"], format: date-time }
22 | 22012 |                 archive_import,
22 | 22016 | status: { type: string, enum: [queued, running, succeeded, failed, cancelled] }
23 | 4060 | "ingest_rate_msgs_per_sec": { "type": "integer" }
23 | 4061 | "write_backlog_rows": { "type": "integer" }
23 | 4071 | Recorded bytes (QuestDB plus Parquet), the meter's numerator over cap_bytes
23 | 4080 | "projected_full_at_ms"
21 | 3956 | ## 4. QuestDB — hot time-series tier
21 | 4323 | batched 5 000 rows or 100 ms
21 | 4331 | `SNAPSHOT PREPARE` → filesystem snapshot/rsync
21 | 4332 | the API never issues DDL against QuestDB at runtime except the retention job
21 | 4408 | ### 5.4 Compaction
21 | 4410 | The compactor runs weekly (Sundays 03:00 UTC)
21 | 4414 | One file per partition directory, ≤ 512 MiB
21 | 4415 | > 4 files in a partition, or any file < 16 MiB with siblings
21 | 4417 | Row count and SHA-256 of the merged output recorded before deletion
21 | 4418 | Skips any partition referenced by an active `replay_sessions` row
21 | 4567 | ## 8. Backup & restore
20 | 904 | `CV_DISK_CAP_GB`
20 | 905 | `CV_DISK_WARN_PCT`
20 | 906 | `CV_DISK_AUTOSTOP_PCT`
20 | 907 | write gate: symbols without an open position dropped (gaps)
20 | 908 | | `CV_DISK_SAMPLE_INTERVAL_S`
24 | 494 | `ingest_lag_seconds{stream}`
24 | 3814 | #### 13.4.1 `DiskBudget` (E16-T07)
24 | 3830 | `projected_full_at` = now + min(cap − used, volume free) / growth
24 | 3854 | outranks ADR-0015's "recording halts"
04 | 873 | | SR-048 |
05 | 90 | ### 3.4 Focus management in dense layouts
05 | 144 | ### 6.2 Layer 2 — ARIA live regions for streaming updates
11 | 4210 | #### US-REC-007 — Historical bulk backfill
11 | 4223 | Then it is skipped, reported, and the rest of the import continues
11 | 4226 | imported ranges are labelled as archive-derived (no book data)
15 | 225 | ### CMP-019 Icon
15 | 262 | ### CMP-023 Progress Bar
15 | 265 | `meter` for a gauge such as disk usage or a budget share
15 | 267 | never a live region: the host announces the start, the completion or a failure once
15 | 272 | ### CMP-024 Sparkline
15 | 276 | reachable via the parent row's DOM-mirror table
15 | 390 | ### CMP-036 KeyValueRow
15 | 473 | ### CMP-044 ConfirmDialog
15 | 477 | form validity, not a gate
15 | 524 | ### CMP-049 Table
15 | 528 | **Variants**: table (static cells, the APG Table pattern
15 | 811 | ### CMP-079 RbacGate
15 | 884 | ### CMP-087 AdminLayout
15 | 2068 | ### CMP-178 SystemHealthTile
15 | 2071 | **Props**: `label` · `value` · `unit` · `tone
E09 | 49 | **T2 Disabled with a visible reason (D4).**
E09 | 85 | Every T2 reason is one of these seven keys
E09 | 108 | `recording:write` → "change recording"
E09 | 230 | a control disabled by **form validity**
E09 | 238 | ### 9.3 Keys on a T2 control
E30D02 | 128 | | D3  | **Side and submit:**
E30D04 | 1048 | ## 30. Gaps (G-rows). Shared sentence
E16D02 | 153 | `projected_full_at` (to the nearer wall: the cap or the volume)
E16D02 | 157 | progress in %; bytes and partitions only from `result`
E16D02 | 200 | **Purge failed:** CMP-028 danger, `role="alert"` once
E16D02 | 203 | **Compact failed / cancelled / unknown:**
E16D02 | 404 | ### 6.5 Purge data (per symbol; Owner + step-up + typed symbol + reason)
E16D02 | 422 | ### 6.6 Compact now
E16D02 | 449 | not reachable: `/admin/*` is hidden from navigation and returns a hard 404
E16D02 | 486 | ### 8.3 Disk card (keyed on `level`)
E16D02 | 496 | Open positions keep recording; other symbols' data is dropped and recorded as gaps.
E16D02 | 508 | ### 8.5 T2 reasons (PROPOSED state keys `recorder.*`; owner: this spec)
E16D02 | 760 | **D-8 (owner decision):**
E16D02 | 778 | **D-16 (the view-as notice):**
E16D03 | 45 | tier health, row counts and maintenance actions stay SCR-142
E16D03 | 210 | Apply pressed on the trades 30 → 90 diff
E16D03 | 255 | ## 8. The job footer (board 06; 7 frames)
E16D05 | 319 | ## 12. Producibility, the contract gaps and the frame gates (the Test plan)
E25 | 334 | hatched = estimated or absent, never a side or direction
"""
POINTER = "E16-D04.md](../design/E16/E16-D04.md)"
DOC_NAMES = (
    "04-security-program.md",
    "05-accessibility-standard.md",
    "11-user-stories.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "20-architecture.md",
    "21-database-schema.md",
    "22-api-openapi.yaml",
    "23-ws-protocol.md",
    "24-internal-schemas.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
DOCS.update(
    {
        "E09": DESIGN / "E09" / "E09-D09.md",
        "E30D02": DESIGN / "E30" / "E30-D02.md",
        "E30D04": DESIGN / "E30" / "E30-D04.md",
        "E25": DESIGN / "E25" / "E25-D01.md",
        "E16D02": DESIGN / "E16" / "E16-D02.md",
        "E16D03": DESIGN / "E16" / "E16-D03.md",
        "E16D05": DESIGN / "E16" / "E16-D05.md",
    }
)
# The layout fixture (section 2): the reference viewport, the admin nav, densities, the poll cadence.
LAYOUT = {"vp_w": 1280, "vp_h": 800, "zoom_pct": 200, "row_px": 32, "nav_px": 240, "poll_s": 2}
LAYOUT.update({"reason_max": 60, "regions": 8, "card_w": 384, "meter_h": 8, "stale_factor": 2})
# the remaining layout figures the prose types: the base zoom, the card-stack breakpoint, the empty notice slot, the
# focus ring, the slow-query window, the projection horizon (each a `--json` context, R-17)
LAYOUT.update({"base_zoom_pct": 100, "stack_px": 1024, "notice_slot_px": 0, "focus_px": 2})
LAYOUT.update({"query_window_h": 1, "horizon_days": 30})
# The sections whose tables hold frame rows (start, end): section 2 (anatomy), 4 (tiers), 5 (states),
# 6 (maintenance), 7 (purge), 8 (import), 11 (redlines). Every frame row has six cells.
TABLES = ((2, 3), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (11, 12))
FRAME_RE = r"^\| `((?:SCR-142|TIER|JOB|PURGE|IMPORT)/[a-z0-9-]+)` +\|.*$"
COL = {"frame": 0, "producer": 1, "shows": 2, "controls": 3, "cls": 4, "board": 5}
# board NN -> the spec section whose table holds its frames (R-18's message names it)
BOARD_SECTION = {
    "01": 2,
    "02": 4,
    "03": 5,
    "04": 5,
    "05": 6,
    "06": 7,
    "07": 8,
    "08": 10,
    "09": 11,
    "10": 15,
}
# The three frames board 10 twins in semantic-light (BQ-21 RULED); each must be a frame row.
TWINS = ("SCR-142/low-disk-warning", "IMPORT/running-with-skips", "SCR-142/view-as")
# Frames the stamp gate (R-2) exempts: the reflow twin, the redlines sheet and the loading skeleton.
NO_STAMP = ("SCR-142/healthy-200-zoom", "SCR-142/redlines", "SCR-142/loading")
DIALOG_FAMILIES = ("JOB/confirm-", "PURGE/dialog", "PURGE/step-up", "PURGE/pinned-refused")
ROW_IDS = (
    ("a_rows", "A"),
    ("c_rows", "C"),
    ("cg_rows", "CG"),
    ("g_rows", "G"),
    ("q_rows", "Q"),
    ("d_rows", "D"),
)
REASON_RE = r"^\| `((?:rbac|storage\.state)\.[a-z_.]+)` +\| ([^|]+?) +\|"
CITE_WARN: list[str] = []


def rows(table: str, parts: int = -1) -> list[list[str]]:
    # `parts` limits the split, so a cited table-row needle may carry its own pipes
    return [[c.strip() for c in ln.split("|", parts)] for ln in table.strip().splitlines()]


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads((TOKENS / f).read_text(encoding="utf-8"))
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
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


def blend(fg: str, bg: str, alpha: float) -> str:
    mixed = (round(a * alpha + b * (1 - alpha)) for a, b in zip(rgb(fg), rgb(bg), strict=True))
    return "#" + "".join(f"{v:02X}" for v in mixed)


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


def short(frame: str) -> str:
    return frame.split("/", 1)[1] if "/" in frame else frame


def gb(n: float) -> str:
    return f"{n / 1e9:,.1f} GB"


def tb(n: float) -> str:
    return f"{n / 1e12:,.1f} TB"


def rate(n: float) -> str:
    return f"{n / 1e9:.2f} GB/day" if n >= 1e9 else f"{round(n / 1e6):,} MB/day"


def pct(num: float, den: float) -> str:
    return f"{100 * num / den:.1f} %"


def iso_dt(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def frame_rows(spec: str) -> list[tuple[str, list[str], int]]:
    """Every frame row of every state table: (frame, cells, section)."""
    out = []
    for a, b in TABLES:
        for m in re.finditer(FRAME_RE, section(spec, a, b), MULTI):
            c = cells(m.group(0))
            out.append((c[0].strip("`"), c, a))
    return out


def deck_rows(spec: str) -> list[tuple[str, str, str]]:
    """(key, string cell, source cell) for every row of the copy deck (section 14)."""
    out = []
    for ln in section(spec, 14, 15).splitlines():
        m = re.match(r"^\| `([^`]+)` +\| (.*?) +\| (.*?) +\|", ln)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def strip_md(s: str) -> str:
    return re.sub(r"[`*]", "", s).strip("| ").strip()


def block(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def contract_facts(t: dict[str, str]) -> dict[str, Any]:
    """Every contract fact the spec and the boards quote, parsed from the plan texts (never typed)."""
    a22, a23, a21, a20, a24, a14, a15 = (t[k] for k in ("22", "23", "21", "20", "24", "14", "15"))
    f: dict[str, Any] = {}
    # StorageUsage: the field list, the enums
    su = block(a22, "\n    StorageUsage:\n", "\n    RetentionPolicyInput:\n")
    f["storage_fields"] = re.findall(r"^        ([a-z_]+):", su, MULTI)
    f["tier_fields"] = re.findall(
        r"^              ([a-z_]+):", block(su, "        tiers:", "        symbols:"), MULTI
    )
    f["symbol_fields"] = re.findall(
        r"^              ([a-z_]+):", block(su, "        symbols:", "        generated_at:"), MULTI
    )
    f["tier_enum"] = (
        first(r"tier: \{ type: string, enum: \[([^\]]+)\] \}", su).replace(" ", "").split(",")
    )
    f["level_enum"] = (
        first(r"level: \{ type: integer, enum: \[([^\]]+)\] \}", su).replace(" ", "").split(",")
    )
    f["gate_enum"] = (
        first(r"write_gate: \{ type: string, enum: \[([^\]]+)\] \}", su).replace(" ", "").split(",")
    )
    f["gate_reason_enum"] = first(r"enum: \[(disk_halt[^\]]+)\]", su).replace(" ", "").split(",")
    f["component_state"] = (
        first(r"ComponentState:\n      type: string\n      enum: \[([^\]]+)\]", a22)
        .replace(" ", "")
        .split(",")
    )
    job = block(a22, "\n    Job:\n", "\n        status:")
    f["job_kinds"] = re.findall(r"^                ([a-z_]+),", job, MULTI)
    f["job_status"] = (
        first(r"status: \{ type: string, enum: \[(queued[^\]]+)\] \}", a22)
        .replace(" ", "")
        .split(",")
    )
    f["no_vacuum_kind"] = not any("vacuum" in k or "compact" in k for k in f["job_kinds"])
    f["no_cancel_route"] = "/admin/jobs/{jobId}/cancel" not in a22
    f["no_vacuum_route"] = not re.search(r"^  /[^\n]*vacuum[^\n]*:\s*$", a22, MULTI)
    f["no_import_result_schema"] = "ArchiveImportResult" not in a22

    # the three routes and the job poll: x-rbac, the shapes, the words
    def rbac_of(op: str) -> str:
        return first(
            r"operationId: " + op + r"\n(?:.*\n){0,24}?\s+x-rbac: \{ permissions: \[([a-z:_]+)\]",
            a22,
        )

    f["rbac"] = {
        op: rbac_of(op)
        for op in (
            "getStorageUsage",
            "compactRecorder",
            "importTradeArchive",
            "purgeRecordedData",
            "getJob",
            "getHealth",
        )
    }
    f["import_days_max"] = int(first(r"inclusive UTC dates, at most (\d+) days", a22) or 0)
    f["import_sentences"] = {
        "recorded_wins": "Recorded data wins: rows inside a" in a22,
        "archive_derived": "archive-derived and cover `trades` only" in a22,
        "resumable": "Resumable and idempotent per day" in a22,
        "one_at_a_time": "One import at a" in a22,
        "audited": "Audited as `recorder.import`" in a22,
        "result_summary": "`result` carries the import summary" in a22,
    }
    f["purge_required"] = first(
        r"required: \[(symbol, confirm_symbol, reason, before)\]", a22
    ).split(", ")
    f["purge_sentences"] = {
        "elevated": "Requires a fresh step-up, a mandatory reason, an explicit" in a22,
        "stepup_class": "`recorder_purge` is a no-grace step-up class" in a22,
        "stepup_problem": "`action_class` set to `recorder_purge`" in a22,
        "no_grace": "`recorder_purge` are no-grace: the response is `single_use: true`" in a22,
        "before_required": "**Window.** `before` is required: the exclusive upper bound of the purge window"
        in a22,
        "before_kept": "Data recorded at or after `before` is never deleted" in a22,
        "before_future": "rule: before_in_future" in a22,
        "before_schema": re.search(
            r"before:\n\s+type: string\n\s+format: date-time\n",
            block(a22, "operationId: purgeRecordedData", '"202"'),
        )
        is not None,
        "audit_first": "written BEFORE the job exists; if it cannot be written the answer is 503"
        in a22,
        "pinned_refused": "(pinned without `include_pinned`) and `409 job_running`" in a22,
        "audit_name": "`retention.purge`, exact window" in a22,
    }
    f["reason_bounds"] = [
        int(x)
        for x in re.findall(r"reason: \{ type: string, minLength: (\d+), maxLength: (\d+) \}", a22)[
            0
        ]
    ]
    f["compact_sentences"] = {
        "one_at_a_time": "One compaction at a time (`409 job_running`)" in a22,
        "section_54": "21-database-schema.md section 5.4" in a22,
    }
    f["job_unknown"] = "Every `404` here carries rule `job_unknown`" in a22
    f["jobs_cap"] = int(first(r"keep theirs: at most (\d+) jobs", a22) or 0)
    f["health_components"] = re.findall(
        r"name: ([a-z_]+),?\s", block(a22, "operationId: getHealth", '"401"')
    )
    f["ingest_rate_k"] = float(first(r'detail: "ingest ([0-9.]+)k msg/s"', a22) or 0)
    f["readiness_migrations"] = "Dependencies reachable and migrations applied" in a22
    f["migration_latest"] = first(r"migration (\d{4}), `21-database-schema.md`", a22)
    f["checksum_code"] = "`checksum_mismatch`" in a22
    f["problem_action_class"] = (
        "`action_class`, `action_summary` and `target` (see `Problem`)" in a22
    )
    # 23: the recorder topic's storage object and the two ingestion-pressure numbers
    ws = block(a23, '"storage": {', '"additionalProperties": false\n    }')
    f["ws_storage_fields"] = re.findall(r'^        "([a-z_]+)":', ws, MULTI)
    f["ws_pressure_fields"] = [
        k
        for k in ("ingest_rate_msgs_per_sec", "write_backlog_rows")
        if f'"{k}": {{ "type": "integer" }}' in a23
    ]
    f["ws_no_lag_field"] = '"ingest_lag_ms"' not in a23 and '"ingest_lag_seconds"' not in a23
    # 21: the QuestDB tables, the ILP batch, the no-DDL rule, the compaction thresholds, backup out of scope
    q = block(a21, "## 4. QuestDB", "## 5. Parquet")
    f["questdb_tables"] = [
        re.sub(r"[`*]", "", x) for x in re.findall(r"^### 4\.\d+ (`[a-z_<>]+`)", q, MULTI)
    ]
    f["questdb_sections"] = count(r"^### 4\.\d+ ", q)
    f["ilp_batch_rows"] = (
        int(
            first(r"batched (\d) (\d{3}) rows", a21).replace(" ", "")
            + first(r"batched \d (\d{3}) rows", a21)
        )
        if re.search(r"batched \d \d{3} rows", a21)
        else 0
    )
    f["no_ddl"] = (
        "the API never issues DDL against QuestDB at runtime except the retention job" in a21
    )
    f["backup_snapshot"] = "`SNAPSHOT PREPARE`" in a21
    comp = block(a21, "### 5.4 Compaction", "### 5.5")
    f["compaction"] = {
        "schedule": first(r"runs weekly \((Sundays \d\d:\d\d UTC)\)", comp),
        "merge_mib": int(first(r"≤ (\d+) MiB", comp) or 0),
        "trigger_files": int(first(r"> (\d+) files in a partition", comp) or 0),
        "trigger_mib": int(first(r"any file < (\d+) MiB", comp) or 0),
        "safety": "Row count and SHA-256 of the merged output recorded before deletion" in comp,
        "idle_guard": "active `replay_sessions` row" in comp,
    }
    f["parquet_families"] = sorted(
        set(
            re.findall(
                r"^  ([a-z_]+)/ +symbol=", block(a21, "### 5.1 Directory layout", "### 5.2"), MULTI
            )
        )
    )
    f["backup_section"] = "## 8. Backup & restore" in a21
    # 20 and 24: the ladder, the cadence, the precedence
    f["disk"] = {
        k: int(first(rf"\| `{k}` +\| [a-z]+ +\| `(\d+)`", a20) or 0)
        for k in (
            "CV_DISK_CAP_GB",
            "CV_DISK_WARN_PCT",
            "CV_DISK_AUTOSTOP_PCT",
            "CV_DISK_HALT_PCT",
            "CV_DISK_SAMPLE_INTERVAL_S",
        )
    }
    f["precedence"] = 'outranks ADR-0015\'s "recording halts"' in a24
    f["lag_metric"] = "`ingest_lag_seconds{stream}`" in a24
    f["projection_rule"] = (
        "`projected_full_at` = now + min(cap − used, volume free) / growth" in a24
    )
    f["release_points"] = int(first(r"re-arms only past its release \((\d) points", a24) or 0)
    # 14: the SCR-142 block and its neighbours
    s142 = block(a14, "### SCR-142", "### SCR-143")
    f["scr142"] = {
        "type_section": "**Type:** Page section." in s142,
        "no_route": "**Route:**" not in s142,
        "states": [x.strip() for x in first(r"\*\*States:\*\* (.+)", s142).split(" · ")],
        "components": re.findall(r"CMP-\d{3}", first(r"\*\*Components:\*\* (.+)", s142)),
        "checklist_boxes": first(r"\*\*Design sign-off acceptance checklist:\*\* (.+)", s142).count(
            "[ ]"
        ),
        "audit_names": re.findall(
            r"`(storage\.[a-z_]+)`", first(r"\*\*Analytics/audit:\*\* (.+)", s142)
        ),
        "degradation_box": "recording pauses before trading is affected - stated" in s142,
        "a11y": "all figures have units; health is text" in s142,
        "performance": "sampled server-side every 60 s, not computed on request" in s142,
        "cancel": "can be cancelled" in s142,
        "stories": re.findall(r"US-REC-\d{3}", first(r"\*\*Stories:\*\* (.+)", s142)),
    }
    f["scr143_db_row"] = "questdb 41GB - postgres 1.2GB - parquet 88GB" in a14
    f["admin_rule"] = "require role `owner` **and** an admin re-auth token ≤15 min old" in a14
    f["rule4"] = "last-good timestamp always shown" in a14
    f["rule5"] = "**RBAC denies server-side; the UI presents.**" in a14
    f["rule6"] = "no information by colour alone" in a14
    f["scr140_states_line"] = first(
        r"\(\"Near limit · auto-record pauses in about (\d+) days\"; \"Recording budget ([0-9.]+) % used",
        a14,
    )
    f["scr140_warn_pct"] = float(
        first(r"\"Recording budget ([0-9.]+) % used \(161\.0 GB of 200 GB\)", a14) or 0
    )
    f["trades_rate_k"] = float(first(r"trades ([0-9.]+)k/s", a14) or 0)
    # 15: the headings the spec uses and the sentences it leans on
    f["cmp_headings"] = {
        c: f"### {c} " in a15
        for c in (
            "CMP-001",
            "CMP-005",
            "CMP-007",
            "CMP-009",
            "CMP-011",
            "CMP-015",
            "CMP-016",
            "CMP-019",
            "CMP-021",
            "CMP-023",
            "CMP-024",
            "CMP-027",
            "CMP-028",
            "CMP-035",
            "CMP-036",
            "CMP-038",
            "CMP-040",
            "CMP-043",
            "CMP-044",
            "CMP-047",
            "CMP-049",
            "CMP-050",
            "CMP-051",
            "CMP-079",
            "CMP-087",
            "CMP-093",
            "CMP-178",
            "CMP-239",
        )
    }
    f["cmp"] = {
        "meter": "`meter` for a gauge such as disk usage or a budget share" in a15,
        "never_live": "never a live region: the host announces the start, the completion or a failure once"
        in a15,
        "mirror": "reachable via the parent row's DOM-mirror table" in a15,
        "typed_validity": "form validity, not a gate" in a15,
        "tile_props": '`label` · `value` · `unit` · `tone: "ok"|"warning"|"danger"` · `sparkline?: number[]`'
        in a15,
        "admin_tint": "`color.surface.admin-tint`" in a15,
        "table_variants": "table (static cells, the APG Table pattern: no control in a body row; default), grid"
        in a15,
    }
    # 04, 05, 11
    f["sr_048"] = "| SR-048 |" in t["04"] and "QuestDB HTTP console" in t["04"]
    f["a11y_sections"] = (
        "### 3.4 Focus management in dense layouts" in t["05"]
        and "### 6.2 Layer 2 — ARIA live regions" in t["05"]
    )
    f["us_rec_007"] = {
        "corrupt": "Then it is skipped, reported, and the rest of the import continues" in t["11"],
        "overlap": "Then recorded data wins, the overlap is reported, and no duplicates are created"
        in t["11"],
        "nfr": "imported ranges are labelled as archive-derived (no book data)" in t["11"],
    }
    # the merged specs
    f["e09"] = {
        "view_as": first(r"`rbac\.view_as` +\| \"([^\"]+)\"", t["E09"]),
        "t2": "**T2 Disabled with a visible reason (D4).**" in t["E09"],
        "verb": '`recording:write` → "change recording"' in t["E09"],
        "validity": "a control disabled by **form validity**" in t["E09"],
    }
    f["e30"] = {
        "d3": "| D3  | **Side and submit:**" in t["E30D02"],
        "shared": first(r"Shared sentence for every `22` / `23` gap: \"([^\"]+)\"", t["E30D04"]),
    }
    d02 = t["E16D02"]
    card = block(d02, "### 8.3 Disk card", "### 8.4")
    f["e16d02"] = {
        "compact_failed": COMPACT_FAILED in d02,
        "purge_failed": PURGE_FAILED_TAIL in d02,
        "level3_line": "Open positions keep recording; other symbols' data is dropped and recorded as gaps."
        in d02,
        "compacting_pct": int(first(r"\"Compacting · (\d+) %\"", d02) or 0),
        "compacted_at": first(r"\"(Compacted at \d\d:\d\d UTC)\"", d02),
        "d16": NOTICE_D16 in d02,
        "manager": "not reachable: `/admin/*` is hidden from navigation and returns a hard 404"
        in d02,
        "headlines": {
            lv: first(rf"^\| {pat} +\| \"([^\"]+)\"", card, MULTI)
            for lv, pat in (("0", "0, growing"), ("1", "1"), ("2", "2"), ("3", "3"))
        },
        "scale": re.sub(r"\s+", " ", first(r"Threshold scale under the bar: \"([^\"]+)\"", card)),
        "actions": (
            ["Shorten retention", "Reduce depth", "Unpin"]
            if all(x in d02 for x in ('"Shorten retention"', '"Reduce depth"', '"Unpin"'))
            else []
        ),
        "purge_cancelled": "Data deleted before the cancel is gone." in d02,
        "purge_unknown": "The purge's status is no longer available on the server." in d02,
        "compact_unknown": "Compaction status is no longer available on the server." in d02,
        "projection": "(to the nearer wall: the cap or the volume)" in d02,
        # section 6.5's body (:410-412), whole: the window and the roll-off sentence included
        "purge_body": re.sub(
            r"\s*\n>\s*",
            " ",
            first(r"(> This deletes .*?nightly roll-off\.)", d02, re.DOTALL).lstrip("> "),
        ).replace("**", ""),
    }
    f["e16d03_boundary"] = (
        "tier health, row counts and maintenance actions stay SCR-142" in t["E16D03"]
    )
    f["e25_rule"] = "hatched = estimated or absent, never a side or direction" in t["E25"]
    # the constants the prose quotes beside the ladder, the admin rule and the compact body
    f["free_steps"] = [int(x) for x in re.findall(r"free < (\d+) %", a24)]
    f["rearm_points"] = int(first(r"re-arms (\d+) points lower", a20) or 0)
    f["warn_runway_days"] = int(first(r"or runway ≤ (\d+) d ", a24) or 0)
    f["reauth_min"] = int(first(r"re-auth token ≤(\d+) min", a14) or 0)
    f["older_than_days_max"] = int(
        first(r"older_than_days: \{ type: integer, minimum: 1, maximum: (\d+) \}", a22) or 0
    )
    return f


def example(a22: str) -> dict[str, Any]:
    """The `22` getStorageUsage example, parsed (never typed)."""
    ex = block(a22, "operationId: getStorageUsage", '"401"')
    out: dict[str, Any] = {}
    for k in (
        "disk_total_bytes",
        "disk_used_bytes",
        "disk_free_bytes",
        "daily_growth_bytes",
        "cap_bytes",
        "level",
    ):
        out[k] = int(first(rf"^\s+{k}: (\d+)$", ex, MULTI))
    out["projected_full_at"] = first(r'projected_full_at: "([^"]+)"', ex)
    out["generated_at"] = first(r'generated_at: "([^"]+)"', ex)
    out["write_gate"] = first(r"write_gate: ([a-z]+)", ex)
    out["tiers"] = [
        {
            "tier": m.group(1),
            "used_bytes": int(m.group(2)),
            "retention_days": None if m.group(3) == "null" else int(m.group(3)),
        }
        for m in re.finditer(
            r"\{ tier: ([a-z]+), used_bytes: (\d+), retention_days: (\d+|null) \}", ex
        )
    ]
    out["symbols"] = [
        {
            "symbol": m.group(1),
            "used_bytes": int(m.group(2)),
            "daily_growth_bytes": int(m.group(3)),
            "pinned": m.group(4) == "true",
        }
        for m in re.finditer(
            r"symbol: ([A-Z]+),\s+used_bytes: (\d+),\s+daily_growth_bytes: (\d+),\s+pinned: (true|false)",
            ex,
        )
    ]
    return out


def days_word(d: float) -> str:
    return f"about {round(d):,} days"


def fixture(facts: dict[str, Any], a22: str) -> dict[str, Any]:
    """The fixture and its derived states: every number and string the frames show."""
    ex = example(a22)
    disk = facts["disk"]
    warn, autostop, halt, every = (
        disk[k]
        for k in (
            "CV_DISK_WARN_PCT",
            "CV_DISK_AUTOSTOP_PCT",
            "CV_DISK_HALT_PCT",
            "CV_DISK_SAMPLE_INTERVAL_S",
        )
    )
    cap, growth = ex["cap_bytes"], ex["daily_growth_bytes"]
    tiers = {x["tier"]: x for x in ex["tiers"]}
    used = tiers["questdb"]["used_bytes"] + tiers["parquet"]["used_bytes"]
    gen = iso_dt(ex["generated_at"])
    full = iso_dt(ex["projected_full_at"])
    runway = (full - gen).total_seconds() / 86400
    cap_wall = (cap - used) / growth
    vol_wall = ex["disk_free_bytes"] / growth
    autostop_days = (autostop / 100 * cap - used) / growth
    used30 = used + 30 * growth
    sym_sum = sum(s["used_bytes"] for s in ex["symbols"])
    fx: dict[str, Any] = {
        "example": ex,
        "generated_at": ex["generated_at"],
        "sample_date": gen.strftime("%Y-%m-%d"),
        "sample_time": gen.strftime("%H:%M:%S"),
        "stamp": f"Sampled {gen.strftime('%H:%M:%S')} UTC (every {every} s)",
        "stale_after_s": LAYOUT["stale_factor"] * every,
        "stale_age_s": 3 * every,
        "stale_age": f"{3 * every // 60} min",
        "stamp_stale": f"Sampled {gen.strftime('%H:%M:%S')} UTC, stale ({3 * every // 60} min old)",
        "last_good": (gen - dt.timedelta(minutes=7)).strftime("%H:%M:%S") + " UTC",
        "disk_total": tb(ex["disk_total_bytes"]),
        "disk_used": tb(ex["disk_used_bytes"]),
        "disk_free": tb(ex["disk_free_bytes"]),
        "volume_pct": pct(ex["disk_used_bytes"], ex["disk_total_bytes"]),
        "cap": gb(cap),
        "budget_used": gb(used),
        "budget_pct": pct(used, cap),
        "growth": rate(growth),
        "runway_days": round(runway, 1),
        "runway": days_word(runway),
        "full_date": full.strftime("%Y-%m-%d"),
        "wall": (
            "cap"
            if abs(cap_wall - runway) < 0.5
            else ("volume" if abs(vol_wall - runway) < 0.5 else "neither")
        ),
        "cap_wall_days": round(cap_wall, 1),
        "volume_wall_days": round(vol_wall, 1),
        "volume_wall": days_word(vol_wall),
        "autostop_days": round(autostop_days, 1),
        "autostop_runway": days_word(autostop_days),
        "used30": gb(used30),
        "formula": f"({autostop} % × {gb(cap)} − {gb(used)}) ÷ {rate(growth)} ≈ {round(autostop_days):,} days",
        "projection_line": f"Full in {days_word(runway)} ({full.strftime('%Y-%m-%d')}) at {rate(growth)}: the budget is the nearer wall (the volume {days_word(vol_wall)})",
        "scale": f"{warn} % warning · {autostop} % auto-record pauses · {halt} % recording stops (open positions keep writing)",
        "tiers": {
            k: {
                "size": gb(v["used_bytes"]),
                "retention": "—" if v["retention_days"] is None else f"{v['retention_days']} d",
                "share": pct(v["used_bytes"], cap) if k != "postgres" else "not counted",
            }
            for k, v in tiers.items()
        },
        "symbols": [
            {
                "symbol": s["symbol"],
                "size": gb(s["used_bytes"]),
                "growth": rate(s["daily_growth_bytes"]),
                "share": pct(s["used_bytes"], cap),
                "pinned": "pinned" if s["pinned"] else "—",
                "runway_share": days_word(s["used_bytes"] / s["daily_growth_bytes"]),
            }
            for s in ex["symbols"]
        ],
        "symbols_sum": gb(sym_sum),
        "attributed_pct": pct(sym_sum, used),
        "attributed_line": f"{gb(sym_sum)} of {gb(used)} attributed to symbols ({pct(sym_sum, used)}): the example's `symbols[]` does not sum to its tiers (D04-CG3)",
    }
    # the level fixtures: the same report with the recorded bytes scaled to the `14` :2748 figure and the ladder steps
    levels: dict[str, Any] = {}
    for lv, p in (("1", facts["scr140_warn_pct"]), ("2", float(autostop)), ("3", float(halt))):
        u = p / 100 * cap
        nxt = {"1": autostop, "2": halt, "3": None}[lv]
        d = (nxt / 100 * cap - u) / growth if nxt else None
        h = facts["e16d02"]["headlines"][lv]
        fills = {
            "{d}": f"{round(d):,}" if d else "",
            "{warn − 5}": str(warn - 5),
            "{autostop − 5}": str(autostop - 5),
            "{halt − 5}": str(halt - 5),
        }
        for k, v in fills.items():
            h = h.replace(k, v)
        levels[lv] = {
            "pct": f"{p:.1f} %",
            "used": gb(u),
            "runway_next": days_word(d) if d else "—",
            "headline": h,
        }
    levels["0"] = {
        "pct": pct(used, cap),
        "used": gb(used),
        "runway_next": days_word(autostop_days),
        "headline": facts["e16d02"]["headlines"]["0"].replace("{d}", f"{round(autostop_days):,}"),
    }
    fx["levels"] = levels
    fx["degradation"] = DEGRADATION
    fx["degradation_detail"] = (
        f"At {autostop} % of the recording budget auto-record pauses; at {halt} % recording stops for symbols without an open position; orders and positions are never gated by the disk."
    )
    # lag, migration, health
    fx["lag"] = {
        "backlog_rows": 5 * facts["ilp_batch_rows"],
        "backlog": f"{5 * facts['ilp_batch_rows']:,} rows",
        "threshold_batches": 5,
        "threshold": "5 batches",
        "healthy_backlog_rows": 0,
        "healthy_backlog": "0 rows",
        "ingest_rate": f"{round(facts['ingest_rate_k'] * 1000):,} msg/s",
        "line": f"Ingest {round(facts['ingest_rate_k'] * 1000):,} msg/s · backlog {5 * facts['ilp_batch_rows']:,} rows · lag — (PROPOSED D04-G4)",
    }
    mig = facts["migration_latest"]
    fx["migration"] = {
        "schema_version": mig,
        "target_version": f"{int(mig) + 1:04d}",
        "pending": 1,
        "banner": f"1 pending · {mig} → {int(mig) + 1:04d}",
        "healthy_pending": 0,
        "healthy_line": f"Migration {mig}, 0 pending",
    }
    fx["health"] = {
        "tiers": facts["health_components"][:3],
        "down_tier": "questdb",
        "since": (gen - dt.timedelta(minutes=7)).strftime("%H:%M:%S") + " UTC",
        "offset_min": 7,
    }
    # the import fixture: January 2026, 31 days; 12 done on the running frame; 30 processed (29 done, 1 skipped)
    # on the skip frame; the last day fails to download in the summary
    frm, to = dt.date(2026, 1, 1), dt.date(2026, 1, 31)
    n = (to - frm).days + 1
    if n > facts["import_days_max"]:
        raise ValueError(f"import fixture: {n} days exceeds the {facts['import_days_max']}-day cap")
    tps = facts["trades_rate_k"] * 1000
    overlap_s = 600  # the overlap window the fixture assumes: ten minutes of recorded trades
    fx["imp"] = {
        "symbol": "BTCUSDT",
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "days": n,
        "running_done": 12,
        "running_pct": int(100 * 12 // n),
        "running_line": f"12 of {n} days · {int(100 * 12 // n)} %",
        "skip_done": 29,
        "skip_processed": 30,
        "skip_pct": int(100 * 30 // n),
        "skip_line": f"30 of {n} days · {int(100 * 30 // n)} % · 1 skipped",
        "skip_counts": "29 done · 1 skipped · 1 downloading",
        "skipped_day": (frm + dt.timedelta(days=13)).isoformat(),
        "error_day": to.isoformat(),
        "rows_per_day": f"{round(tps * 86400):,} rows",
        "overlap_window_s": overlap_s,
        "overlap_window": f"{overlap_s // 60} min",
        "overlap_rows": f"{round(tps * overlap_s):,} rows",
        "finished": f"Import finished: BTCUSDT, {frm.isoformat()} → {to.isoformat()}",
        "summary": f"Imported 29 days of BTCUSDT trades · 1 file skipped · 1 file failed · {round(tps * overlap_s):,} overlapping rows discarded",
        "overlap_line": f"{round(tps * overlap_s):,} rows inside recorded windows were discarded — recorded data wins.",
    }
    fx["jobs"] = {
        "compact_pct": facts["e16d02"]["compacting_pct"],
        "compact_line": f"Compaction running · {facts['e16d02']['compacting_pct']} %",
        "import_line": f"Import running · {int(100 * 12 // n)} %",
        "compacted_at": facts["e16d02"]["compacted_at"],
    }
    comp = facts["compaction"]
    fx["compaction"] = {
        "schedule": comp["schedule"],
        "merge": f"{comp['merge_mib']} MiB",
        "trigger": f"more than {comp['trigger_files']} files, or any file under {comp['trigger_mib']} MiB",
    }
    eth = ex["symbols"][1]
    before = gen - dt.timedelta(days=tiers["parquet"]["retention_days"])
    # the preview window: the symbol's bytes over its growth, ending at the cut-off (the live dialog reads coverage)
    since = before - dt.timedelta(days=round(eth["used_bytes"] / eth["daily_growth_bytes"]))
    window = f"about {gb(eth['used_bytes'])} recorded from {since:%Y-%m-%d} to {before:%Y-%m-%d}"
    fx["purge"] = {
        "symbol": "ETHUSDT",
        "size": gb(eth["used_bytes"]),
        "before": before.strftime("%Y-%m-%d"),
        "from": since.strftime("%Y-%m-%d"),
        "body": re.sub(
            r"about [\d.]+ GB recorded from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}",
            window,
            facts["e16d02"]["purge_body"],
        ),
        "pinned_symbol": ex["symbols"][0]["symbol"],
    }
    return fx


UNIT_NUM = r"\d[\d,]*(?:\.\d+)?\s?(?:GB|TB|MB)\b"
DATE_RE = r"\b\d{4}-\d{2}-\d{2}\b"
STATE_WORD = r"\b(?:healthy|degraded|warning|down|not deployed|not_deployed)\b"
TIER_FRAMES = ("TIER/questdb", "TIER/parquet", "TIER/postgres")
# The ruled caption every PROPOSED carrier repeats (the deck's `storage.proposed.caption`; BQ-11 / 13 / 18 / 22).
CAPTION = "PROPOSED — D04-G{n}, owner approval pending (#2701)"
CAP_RE = r"PROPOSED — D04-G(\d+), owner approval pending \(#2701\)"
# BQ-14 RULED: the sentence the disk-full frame carries.
BQ14 = "a server refusal shows in the CMP-044 result as T4, never as a disabled control"
# Vocabularies, case-insensitive, per ruled sentence. A negator governs a match only when it stands within four
# words before it, inside the same clause (no `,` `;` `:` `(` `)` `·` `—` or sentence break between them).
NEGATOR = (
    r"(?:no|never|not|without|none|nothing|nor|neither|absent|isn't|aren't|cannot|can't|won't|doesn't"
    r"|don't|didn't)"
)
CLAUSE_STOP = r"[,;:()·—]|\.\s"
LOCK_TERM = r"\b(?:locked|locks?|padlock|T2|CMP-079|RbacGate)\b"
DIM_TERM = (
    r"\baria-disabled\b|\bopacity\.disabled\b|\bcolor\.text\.disabled\b|\b\d+ ?% opacity\b"
    r"|\b(?:disabled|gr[ae]yed(?: out)?|dimmed|dims|faded|inert|unavailable|blocked|gated)\b"
    r"|\b(?:not|no longer) (?:available|usable|pressable|clickable)\b(?! on the server)"
    r"|\b(?:can't|cannot|can not) be (?:pressed|used|clicked|activated)\b"
)
# A2 / A3: an exit accepts only T1. Any predicate that takes an exit's effect away is a FAIL, by class and in any
# inflection: no effect (does nothing, has no effect, a no-op, ignored, swallowed, suppressed), not there (hidden,
# removed, invisible), off (inactive, switched / turned off, deactivated, muted), refused (blocked, unavailable,
# greyed, disabled) and the negated working verbs (doesn't close, won't respond, can't be used). Read only where
# the subject is an exit; DIM_TERM and LOCK_TERM keep their own reading of the writes.
DEAD_TERM = (
    r"\b(?:does|do|did|doing|done) nothing\b|\b(?:has|have|had|having|with|of|to) no effect\b"
    r"|\bwithout (?:any )?effect\b"
    r"|\bno-?ops?\b|\b(?:ineffective|inert|inactive|dead|unresponsive|invisible|unusable|unreachable)\b"
    r"|\b(?:hid(?:e|es|den|ing)|conceal(?:s|ed|ing)?|ignor(?:e|es|ed|ing)|suppress(?:es|ed|ing)?"
    r"|swallow(?:s|ed|ing)?|block(?:s|ed|ing)?|disabl(?:e|es|ed|ing)|deactivat(?:e|es|ed|ing)|mut(?:e|es|ed|ing)"
    r"|gr[ae]y(?:s|ed|ing)?(?: out)?|remov(?:e|es|ed|ing)|unavailable)\b"
    r"|\b(?:switch(?:es|ed|ing)?|turn(?:s|ed|ing)?|shut(?:s|ting)?|toggl(?:e|es|ed|ing)) off\b"
    r"|\b(?:not|no longer|never) (?:available|usable|pressable|clickable|shown|visible|active|enabled|reachable"
    r"|focusable|operable|working|responsive|there)\b"
    r"|\b(?:can't|cannot|can not|won't|will not|doesn't|does not|don't|do not|didn't|did not) (?:be )?(?:pressed"
    r"|used|clicked|activated|work|respond|close|dismiss|act|fire|function|leave|exit|cancel)\b"
)
# the T2 anatomy's own words on the view-as frame; every other dim word there is a FAIL
T2_DIM = (
    r"\bopacity\.disabled\b|\bcolor\.text\.disabled\b|\b\d+ ?% opacity\b"
    r"|(?<!aria-)\bdisabled\b|\b(?:gr[ae]yed(?: out)?|dimmed|dims|faded)\b"
)
# R-7: a typed confirm field shown filled. The strong words fail anywhere; the context words fail when the typed
# field is the subject (named before them in the unit, or carried by an item or a sentence that opens on a pronoun).
SYM = r"(?:the |its |a |that )?\{?(?:symbol|ETHUSDT|BTCUSDT)"
# arriving, in any inflection: comes / came / coming, arrives, opens, starts, loads, appears, renders, begins, launches
ARRIVE = (
    r"(?:com(?:e|es|ing)|came|arriv(?:e|es|ed|ing)|open(?:s|ed|ing)?|start(?:s|ed|ing)?|load(?:s|ed|ing)?"
    r"|appear(?:s|ed|ing)?|render(?:s|ed|ing)?|begin(?:s|ning)?|began|launch(?:es|ed|ing)?|pops? up"
    r"|popp(?:ed|ing) up|show(?:s|n|ed|ing)? up)"
)
FILL = (
    r"\b(?:pre-?filled|prefill(?:ed|s|ing)?|auto-?fill(?:ed|s|ing)?|pre-?populated|filled in"
    rf"|typed into|copied into|pasted into|defaults? to {SYM}|(?:entered|inserted|supplied|filled"
    r"|typed|put in|placed) (?:for (?:you|the Owner)|automatically|by the (?:dialog|client|app|page)))\b"
)
FILL_CONTEXT = (
    r"\b(?:set to|already (?:holding|holds|contains|containing|carrying|carries|shows|showing|has|having"
    r"|reads|reading|in (?:it|place|there))|defaulted|seeded|populated|holding the symbol"
    r"|with the symbol in it|empty (?:at first|initially|until)|then (?:set|filled|holds|shows|reads)"
    rf"|(?:{ARRIVE})(?: already)? (?:with|holding|showing|containing|carrying|reading|on) {SYM}"
    rf"|suggest(?:s|ed|ing)? {SYM})\b"
)
# R-7 by class: the typed field (or any confirm / symbol / text field, input or box) holding a value. The subject,
# then within three words a verb of showing, holding, containing, displaying, carrying, bearing, reading or
# arriving in any inflection, then a symbol: "The typed field shows ETHUSDT.", "the field comes with BTCUSDT".
# A negator inside the match ("the typed field never shows the symbol") or before it exempts it.
FIELD_NOUN = (
    r"(?:(?:typed|confirm(?:ation)?|symbol|text|purge) )?(?:field|input|box)\b|\btyped (?:symbol|confirm)\b"
    r"|Type the symbol to confirm\b[^·;|\"]*?"
)
HOLD_VERB = (
    r"(?:show(?:s|n|ed|ing)?|hold(?:s|ing)?|held|contain(?:s|ed|ing)?|display(?:s|ed|ing)?"
    r"|carr(?:y|ies|ied|ying)|bear(?:s|ing)?|bore|borne|read(?:s|ing)?|ha(?:s|ve|d|ving)|keep(?:s|ing)?|kept"
    r"|includ(?:e|es|ed|ing)|set to|equal(?:s|led|ling)?|(?:is|are|was|were|be|being|been) "
    rf"(?:already )?(?:set to|filled with)|{ARRIVE})"
)
FIELD_HOLDS = (
    rf"\b(?:{FIELD_NOUN})\W+(?:[\w'’-]+\W+){{0,3}}?{HOLD_VERB}\b\W+(?:(?:with|on|in)\W+)?{SYM}\b"
)
TYPED_SUBJ = (
    r"\btyped (?:field|input|symbol|confirm)|\bconfirm(?:_symbol| field)\b|Type the symbol to confirm"
    r"|\b(?:symbol|confirm(?:ation)?) (?:field|input|box)\b"
)
# R-5: the degradation order in any wording. REC = the recording side, TRADE = the trading side, HALT = a stop.
REC = r"(?:recording|auto-record|the recorder|capture)"
TRADE = r"(?:trading|orders?|order (?:placement|entry)|positions?|execution)"
HALT = (
    r"(?:pause[sd]?|stop(?:s|ped)?|halt(?:s|ed)?|freez(?:e|es)|suspend(?:s|ed)?"
    r"|(?:is|are|gets?) (?:affected|refused|rejected|blocked|gated|stopped|paused|halted|suspended|cut|throttled))"
)
INVERTED = (
    (
        rf"\b{TRADE}\W+(?:\w+\W+){{0,3}}?{HALT}\W+(?:\w+\W+){{0,2}}?"
        rf"(?:first|before|earlier|sooner|ahead of)\b"
    ),
    rf"\b{TRADE}\W+(?:\w+\W+){{0,2}}?(?:is|are) (?:the )?first to\b",
    (
        rf"\b{REC}\W+(?:\w+\W+){{0,3}}?{HALT}\W+(?:\w+\W+){{0,2}}?(?:after|only after|once|later than|behind)"
        rf"\W+(?:\w+\W+){{0,2}}?{TRADE}"
    ),
    (
        rf"\b{REC}\W+(?:\w+\W+){{0,3}}?(?:continues?|keeps? (?:going|running|writing|recording)|goes on"
        rf"|carries on|stays? up)\W+(?:\w+\W+){{0,3}}?(?:while|when|after|even as|as|until)\W+(?:\w+\W+){{0,2}}?"
        rf"{TRADE}"
    ),
    rf"\bbefore {REC}\W+(?:\w+\W+){{0,2}}?{HALT}\W+(?:\w+\W+){{0,2}}?{TRADE}",
    rf"\bfirst\W+(?:\w+\W+){{0,2}}?{TRADE}\b.*\bthen\b.*\b{REC}",
)
WEAKENED = (
    (
        rf"\b{REC}\W+(?:\w+\W+){{0,1}}?(?:may|might|could|can|usually|often|sometimes|generally|typically"
        rf"|normally|mostly|ideally|should|tries to)\W+(?:\w+\W+){{0,2}}?(?:pause|stop|halt)"
    ),
    (
        rf"\b{TRADE}\W+(?:\w+\W+){{0,3}}?(?:may|might|could|can|will) (?:also |then |still |eventually )?"
        rf"(?:be )?(?:affected|stop|pause|halt|gated|refused|blocked|slowed)\b"
    ),
    rf"\b(?:{REC} and {TRADE}|{TRADE} and {REC})\W+(?:\w+\W+){{0,2}}?(?:pause|stop|halt)",
    rf"\b(?:at the same time as|together with|simultaneously with|alongside) {TRADE}",
)
RULED_ORDER = (
    (
        rf"\b{REC}\W+(?:\w+\W+){{0,3}}?{HALT}\W+(?:\w+\W+){{0,2}}?(?:before|ahead of)"
        rf"\W+(?:\w+\W+){{0,2}}?{TRADE}"
    ),
    rf"\b{TRADE}\W+(?:\w+\W+){{0,3}}?(?:only )?after\W+(?:\w+\W+){{0,2}}?{REC}",
    rf"\b{REC}\W+(?:\w+\W+){{0,2}}?{HALT}\W+first\b",
)
# R-5 by sequence (A2: the order of events, not a phrase list). The two subjects: the trading side (trading,
# order entry, positions, orders, the OMS) and the recording side (recording, the recorder, capture, ingestion
# writes). A trading EVENT is a trading subject with an un-negated stopping predicate in its clause; the order is
# read from the sequence words (first, then, later, follows, before, after, once, until, only after, next,
# subsequently …), else from the order the two are told in. A statement where the trading event comes first or at
# the same time as the recording side fails; the ruled order in any wording passes.
SEQ_TRADE = (
    r"\b(?:trading|order (?:entry|placement)|orders?|(?:open )?positions?|the OMS|OMS|execution)\b"
)
SEQ_REC = (
    r"\b(?:recording|auto-record(?:ing)?|(?:the )?recorder|captur(?:e|es|ed|ing)|ingestion writes?"
    r"|ingest writes?)\b(?! (?:budget|volume|data|policy|scale|status|card|panel)\b)"
)
SEQ_HALT = (
    r"(?:halt(?:s|ed|ing)?|stop(?:s|ped|ping)?|paus(?:e|es|ed|ing)|freez(?:e|es|ing)|froze(?:n)?"
    r"|suspend(?:s|ed|ing)?|(?:is|are|gets?|got|was|were|be|being) (?:hit|affected|impacted|cut(?: off)?"
    r"|refused|rejected|blocked|gated|stopped|paused|halted|suspended|throttled|closed|frozen|interrupted"
    r"|degraded|disrupted|lost|flattened|liquidated|wound down|touched|reached|slowed)|hit|clos(?:e|es|ed|ing)(?: out| down)?"
    r"|wind(?:s|ing)? down|wound down|flatten(?:s|ed|ing)?|liquidat(?:e|es|ed|ing)|end(?:s|ed)?|fail(?:s|ed)?"
    r"|go(?:es)? (?:down|dark|offline)|went (?:down|dark|offline)|(?:is|are) the first to \w+|suffer(?:s|ed)?"
    r"|tak(?:e|es) the hit|stall(?:s|ed)?|ceas(?:e|es|ed))\b"
)
SEQ_FIRST = r"\b(?:first|firstly|earliest|immediately|at once|right away|straight away|initially)\b"
SEQ_LATER = (
    r"\b(?:then|later|follows?|followed|following|next|subsequently|afterwards?|thereafter|eventually|in turn"
    r"|after that|after this|only then|second|last|lastly|finally)\b"
)
SEQ_SAME = (
    r"\b(?:at the same time(?: as)?|simultaneously(?: with)?|together(?: with)?|alongside|along with|in step with"
    r"|in lockstep(?: with)?|as soon as|the moment|while|whilst|as|when|with)\b"
)
# connector between the two clauses: (A conn B) means A happens before B ("before"), or after B ("after")
SEQ_BEFORE = (
    r"\b(?:before|ahead of|earlier than|sooner than|prior to|in advance of|preceding|precedes?)\b"
)
SEQ_AFTER = r"\b(?:only after|only once|only when|not until|after|once|later than|behind|following|until|till)\b"
PAGE_LEVEL = (
    r"\b(?:banners?|callouts?|toasts?|alerts?|page[- ]level|page error)\b|role=\"?alert"
    r"|\b(?:top of the (?:page|screen)|across the (?:page|screen))\b"
)
STALL = r"\b(?:paused|pauses|stops|stopped|halts|halted|frozen|freezes|waits|stalls|stalled)\b"
OUTSIDE_CARD = r"\b(?:page|screen|top of)\b"
DEFERRED = (
    r"(?i:\b(?:apply|run|start|execute)\s+(?:the\s+)?migrations?\b|\bmigrate now\b)|\bApply\b"
)
# R-21: a second purge shape, read when purge is the subject (or the words name it)
SECOND_PURGE = (
    r"\b(?:one-click|single-click|one-step)\b|\b(?:quick|lighter|simpler|simple|plain|standard) (?:purge|confirm|dialog)\b"
    r"|\bCMP-044 standard\b|\b(?:without|no|skips?|skipping|drops?|dropping) (?:its |the )?typed "
    r"(?:field|confirm|symbol|input)\b|\b(?:its|their|a|an) (?:own|separate|second|new|different|other) purge "
    r"(?:dialog|confirm|shape|flow)\b|\bsecond (?:purge )?shape\b"
    # by class: no typing (no typing, nothing to type, without typing, no symbol to type, skips the typed field,
    # untyped) and a lighter dialog (slim, light, short, quick, straight / directly to the step-up)
    r"|\b(?:no|without|skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?|avoid(?:s|ed|ing)?|omit(?:s|ted|ting)?|drop(?:s|ped"
    r"|ping)?|los(?:e|es|ing)|lack(?:s|ed|ing)?|minus) (?:any |the |its |a |all )?(?:re-?)?typing\b"
    r"|\bnothing (?:to|for (?:you|the Owner) to) (?:re-?)?(?:type|enter|key in)\b"
    r"|\bno (?:symbol|text|name|word|ticker|value)s? (?:to|for (?:you|the Owner) to) (?:re-?)?(?:type|enter|key in)\b"
    r"|\b(?:skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?|omit(?:s|ted|ting)?|los(?:e|es|ing)|lack(?:s|ed|ing)?"
    r"|avoid(?:s|ed|ing)?) (?:the |its |a |any )?(?:typed|typing|confirm(?:ation)?|symbol) (?:field|step|confirm"
    r"|input|box|check)\b|\b(?:untyped|type-?free|typeless|typing-free)\b"
    r"|\b(?:slim|slimmer|light|lighter|lightweight|short|shorter|quick|quicker|express|fast|minimal|bare)"
    r"(?:-weight)? (?:confirm(?:ation)?|dialog|modal|prompt|form|path|flow|version)\b"
    r"|\b(?:straight|directly|direct|right) (?:on )?to (?:the )?step-up\b"
)
PURGE_SUBJ = r"Purge data…|\bPurge…|\b[Pp]urge(?:RecordedData)?\b"
OTHER_ACTION = r"\b[Cc]ompact(?:ion|s|ed)?\b|\b[Vv]acuum\b|\b[Ii]mport(?:s|ed)?\b"
NOTICE = r"\b(?:notices?|banners?|callouts?|toasts?)\b"
# Subjects (A1 / A3): every exit and every write by its full and its short name. A lock or dim word speaks of the
# nearest subject named before it in the item, else of the subject carried from the items before (a ";" item, a
# "·" item, an item that opens on It / This / They / Then / Each speaks of the last subject named).
EXIT_TERM = (
    r"\bCancel, Esc and the close ✕|\bCancel (?:and|/) Esc\b|\bEsc\b|\bclose ✕|✕|\bClose\b|\bBack\b"
    r"|\blinks? to SCR-14[013]|\blinks?\b|\bShorten retention\b|\bReduce depth\b|\bUnpin\b|\bRetry\b"
    r"|\bManage pin\b|→ SCR-14[013]|\bexits?\b"
)
WRITE_TERM = (
    r"Compact Parquet…|\bCompact\b|Purge data…|\bPurge…|\bPurge\b|Import archives|Vacuum Postgres…|\bVacuum\b"
    r"|\bStop job\b|\bevery write\b|\bthe other writes\b|\bwrites?\b|\bactions?\b|\bConfirm\b|\bbuttons?\b"
)
# the keys a keyboard model names (Esc is an exit): "Enter in the typed field does nothing" speaks of Enter
KEY_TERM = r"\bEnter\b|\bSpace\b|\bShift\+Tab\b|\bTab\b|\barrows?\b|\bhotkeys?\b"
# the exit Cancel in its own forms: never captioned, never locked; any other "Cancel" on a frame is a job action
EXIT_CANCEL = (
    r"\bCancel, Esc and the close ✕|\bCancel (?:and|/) (?:Esc|Confirm|Compact|Vacuum|the verb)\b"
    r"|\bexits? Cancel\b|\bEsc = Cancel\b|\bfocus starts on Cancel\b"
)
# PROPOSED carriers by stem or noun class (A2: a word list is a Major). Each class reads any inflection and any
# order of its nouns, document-wide: the frame rows (CARRIERS), the names outside them (DOC_STRONG).
ROW_WORD = r"rows?"
COUNT_WORD = r"(?:counts?|count(?:ed|ing)|totals?|totall?(?:ed|ing)|tall(?:y|ies|ied|ying)|sums?)"
ROW_COUNT = (
    rf"\b{ROW_WORD}\W+(?:[\w'’-]+\W+){{0,2}}?{COUNT_WORD}\b"
    rf"|\b(?:{COUNT_WORD}|numbers?)\W+(?:of\W+)?(?:[\w'’-]+\W+){{0,1}}?{ROW_WORD}\b"
    r"|\brows by table\b|(?-i:\bRows\b)"
)
VACUUM = r"\bvacuum(?:s|ed|ing)?\b"
LAST_RUN = (
    r"\b(?:last|latest|most recent|previous) (?:vacuum|compaction)(?:\s*(?:/|or|and)\s*(?:(?:last|latest) )?"
    r"(?:vacuum|compaction))?\b"
)
JOB_NOUN = r"(?:jobs?|compactions?|imports?|vacuums?|purges?|runs?)"
STOP_VERB = (
    r"(?:stop(?:s|ping)?|cancel(?:s|ling|ing)?|abort(?:s|ing)?|kill(?:s|ing)?|terminat(?:e|es|ing)|end(?:s|ing)?"
    r"|halt(?:s|ing)?|interrupt(?:s|ing)?)"
)
STOP_BARE = r"\b(?:stop(?: job)?|cancel|abort|end(?: the)? job|kill|terminate)\b"
STOP_JOB_CLASS = (
    rf"\b{STOP_VERB}\W+(?:(?:the|a|an|this|that|each|every|any|its|their|running|started|current)\W+){{0,2}}"
    rf"{JOB_NOUN}\b"
    rf"|\b{JOB_NOUN}\W+(?:[\w'’-]+\W+){{0,2}}?(?:stopp|cancell?|abort|kill|terminat)(?:ed|able)\s+"
    r"(?:by|from|with|via|using|on|early|mid-run)\b"
)
STOP_JOB = STOP_BARE + "|" + STOP_JOB_CLASS
SLOW_QUERY = (
    r"\bslow(?:er|est|-running)?\W+(?:[\w'’-]+\W+){0,1}?quer(?:y|ies)\b"
    r"|\bquer(?:y|ies)\W+(?:[\w'’-]+\W+){0,1}?(?:latenc(?:y|ies)|durations?|timings?|times)\b"
    r"|\blatenc(?:y|ies)\b|\bp9[59]\b|\bquery[- ]performance\b|\bstatement kinds?\b"
)
TIER_WORD = (
    r"(?:QuestDB|Parquet|Postgres|per-tier|each tier(?:'s)?|every tier(?:'s)?|the tier's|a tier's)"
)
GROW_WORD = r"(?:grow(?:s|n|ing|th)?|grew|daily (?:growth|bytes)|trend(?:s|ing)?)"
TIER_GROWTH = (
    rf"\b{TIER_WORD}\W+(?:[\w'’-]+\W+){{0,2}}?{GROW_WORD}\b"
    rf"|\b{GROW_WORD}\W+(?:[\w'’-]+\W+){{0,1}}?(?:of|for|per|by) (?:each |every |the )?(?:tier|QuestDB|Parquet"
    r"|Postgres)\b|\btiers\[\]\.daily_growth_bytes\b"
)
# the lag value (D04-G4); the lag-warning state is shipped (keyed on the backlog, BQ-17), so its name is not a carrier
LAG = (
    r"\blag(?:s|ged|ging)?\b(?![- ](?:warning|banner|state|notice)s?\b)|\bingest(?:ion)?[_ ]lag\w*"
)
SPARK = (
    r"\bspark[- ]?lines?\b|\btrend[- ]?(?:lines?|charts?|graphs?)\b|\bmini[- ]?(?:charts?|graphs?|plots?)\b"
    r"|\bhistory (?:charts?|graphs?|lines?|bars?)\b|\bhistory_bytes\b|\bCMP-024\b"
)
MIGRATION = (
    r"\b(?:pending|outstanding|unapplied|queued|waiting) migrations?\b"
    r"|\bmigrations?\W+(?:[\w'’-]+\W+){0,2}?(?:pending|outstanding|unapplied|waiting|behind|versions?|states?"
    r"|banners?|rows?|counts?)\b|\bschema[_ ]versions?\b|\b\d{4} → \d{4}\b|\bpending_migrations\b"
    r"|(?<!§)\b\d+ pending\b"
)
# PROPOSED carriers: a vocabulary per gap id (the n the caption must carry); the first match in an item wins.
CARRIERS: tuple[tuple[str, str, frozenset[int]], ...] = (
    ("last vacuum or compaction", LAST_RUN, frozenset({6})),
    ("vacuum", VACUUM, frozenset({8})),
    ("stop job", STOP_JOB, frozenset({10})),
    (
        "per-file rows",
        r"\bper-file\b|files\[\]|\b\d+ skipped\b|skipped ⚠|\bDay / Status(?: / [A-Z]\w*)*",
        frozenset({11}),
    ),
    ("row counts", ROW_COUNT, frozenset({3})),
    ("slow queries", SLOW_QUERY, frozenset({5})),
    ("per-tier growth", r"\bGrowth/day —|\bProjected full —|" + TIER_GROWTH, frozenset({1})),
    ("lag", LAG, frozenset({4})),
    ("sparkline", SPARK + r"|\bOldest\b", frozenset({2, 3})),
    ("migration", MIGRATION, frozenset({7})),
    (
        "archive-derived ranges",
        r"\bimported ranges?\b|\bcoverage (?:chart|band|chip|intervals?)\b",
        frozenset({12}),
    ),
)
# A PROPOSED item presented as shipped outside the frame rows. DOC_STRONG: the item's names (a control label, a
# column, a component) — a mention needs, in its clause (a table row is read whole, across its cells), the caption
# with its n, or the gap named absent (GAP_ABSENT and the gap id), or a governing negator. SHIPPED: the generic nouns,
# failing only in a presenting form (a verb or a control word). The rows that define a gap (GAP_ROW) are exempt.
DOC_STRONG: dict[str, tuple[str, frozenset[int]]] = {
    "last vacuum or compaction": (LAST_RUN, frozenset({6})),
    "vacuum": (
        r"\bVacuum Postgres…|\bVacuum (?:button|control|action|inset)\b|\[ ?Vacuum|" + VACUUM,
        frozenset({8}),
    ),
    "stop job": (
        (
            r"\bStop job\b|\bEnd(?: the)? job\b|\bCancel (?:button|control)\b"
            r"|\bCancel (?:per|on (?:the|each|every)) job|\bCancel on the jobs strip\b|"
            + STOP_JOB_CLASS
        ),
        frozenset({10}),
    ),
    "row counts": (ROW_COUNT, frozenset({3, 11})),
    "slow queries": (SLOW_QUERY, frozenset({5})),
    "sparkline": (
        SPARK.replace(r"\bCMP-024\b", r"\bCMP-024\b(?! :)") + r"|\bOldest / Newest\b",
        frozenset({2, 3}),
    ),
    "migration": (MIGRATION + r"|(?-i:\bMigration \d{4}\b)", frozenset({7})),
    "per-file rows": (
        r"\bper-file (?:table|rows?|CMP-049)\b|Day / Status / Reason / Rows|\bskip counter\b|files\[\]",
        frozenset({11}),
    ),
    "lag": (LAG, frozenset({4})),
    "per-tier growth": (TIER_GROWTH, frozenset({1})),
}
SHIPPED: dict[str, str] = {
    "vacuum": (
        r"\bvacuum(?: postgres)?…? (?:button|control|link)\b|\[ ?vacuum"
        r"|\bvacuum(?: postgres)?…? (?:sits|stands|appears|shows|beside|next to|alongside)\b"
        r"|\b(?:offers|has|includes|adds|gains|provides|carries|shows) (?:a |the |its )?vacuum\b"
    ),
    "stop job": (
        r"\b(?:stop|cancel|abort) (?:button|control|link)\b"
        r"|\b(?:stops|cancels|aborts|ends) (?:the|a) (?:running|job|compaction|import|vacuum|purge)\b"
    ),
    "row counts": (
        r"\b(?:shows?|lists?|displays?|carries|reads|with|offers|has|includes) (?:its |the |their )?"
        r"(?:row counts?|rows by table)\b"
    ),
    "slow queries": (
        r"\b(?:shows?|lists?|displays?|carries|reads|with|offers|has|includes) (?:its |the |their )?slow(?:est)? quer"
    ),
    "per-tier growth": (
        r"\b(?:Growth/day|Projected full):? \d|\bdaily_growth_bytes`? ?[=:]? ?\d"
        r"|\bper-tier growth (?:of|is|reads|at|shows)\b"
    ),
    "lag": r"\blag (?:of |is |= ?|: ?)?\d|\bingest_lag_ms`? ?[=:]? ?\d",
    "sparkline": (
        r"\b(?:growth|history|7-day) sparkline\b"
        r"|\bsparkline (?:shows|draws|plots|sits|beside|next to|appears)\b"
        r"|\b(?:shows?|draws?|with|carries|plots?) (?:a|the|its) sparkline\b"
    ),
    "migration": r"(?-i:\bMigration \d{4}\b)|\bschema version \d{4}\b",
    "per-file rows": (
        r"\bper-file (?:table|rows?)\b[^.;·]{0,60}\b(?:during|while) (?:the )?(?:import |job )?"
        r"(?:run|runs|running|is running)\b"
        r"|\b(?:during|while) (?:the )?(?:import |job )?(?:run|runs|running)\b[^.;·]{0,60}\bper-file\b"
    ),
}
GAP_ABSENT = r"(?i:\bneeds?\b|\buntil\b|\bnot yet\b|\bnot produced\b|\babsen(?:t|ce)\b|\bnone\b|\bno such\b)|\bPROPOSED\b"
GAP_ROW = r"^\| (?:\*\*)?(?:D04-(?:CG|[ACDGQ])\d+|BQ-\d+)\b"
# a table's gap column: a cell holding only gap ids (§12's producibility table)
GAP_CELL = r"(?:—\s*)?\(?(?:PROPOSED\s*)?(?:D04-(?:CG|G|Q)\d+(?:\s*[,/]\s*|\s+)?)+\)?"
# Exits each frame lists (R-14): present, and T1. The dialog family carries Cancel and Esc; the page frames their links.
CLOSE_EXITS = "Cancel, Esc and the close ✕"
EXITS: dict[str, tuple[str, ...]] = {
    "SCR-142/healthy": ("links to SCR-140, SCR-141 and SCR-143",),
    "SCR-142/view-as": ("links to SCR-140, SCR-141 and SCR-143",),
    "SCR-142/low-disk-warning": ("Shorten retention",),
    "SCR-142/autostop": ("suggested actions as links",),
    "SCR-142/read-only-disk-full": ("Shorten retention",),
    "SCR-142/tier-unreachable-questdb": ("Retry",),
    "SCR-142/unavailable": ("Retry",),
    "JOB/confirm-compact": (CLOSE_EXITS,),
    "JOB/confirm-vacuum": (CLOSE_EXITS,),
    "PURGE/dialog": (CLOSE_EXITS,),
    "PURGE/dialog-validity": (CLOSE_EXITS,),
    "PURGE/pinned-refused": (CLOSE_EXITS,),
    "PURGE/step-up": (CLOSE_EXITS,),
    "TIER/per-symbol": ("Manage pin",),
}
# The view-as leg's writes (section 1.3's T2 row), each named on the frame (R-13), and its anatomy tokens.
VIEW_AS_WRITES = (
    "Compact Parquet…",
    "Purge data…",
    "Import archives",
    "Purge… in the row's detail popover",
    "Stop job on the jobs strip",
    "Vacuum Postgres… inset",
)
T2_TOKENS = (
    "color.surface.raised",
    "color.border.default",
    "color.text.tertiary",
    "color.text.secondary",
)
# The closed set of skip reasons (D04-G11) with their deck sentences (R-10).
SKIP_KEYS = {
    "checksum_mismatch": "storage.import.reason.checksum",
    "parse_error": "storage.import.reason.parse",
    "download_failed": "storage.import.reason.download",
    "already_imported": "storage.import.reason.already",
}
# Section 1.3's classification: each row's class is fixed by its lead (R-6; the view-as row first, R-13).
CLASS_MAP = (
    ("every write while viewing as", "T2"),
    ("a Manager or a Viewer", "not a state of this page"),
    ("Import archives while the range", "validity look"),
    ("Compact Parquet… / Import archives / Purge…", "busy"),
    ("`409 job_running`", "T4"),
    ("disk full", "status"),
    ("Stop job (cancel a running job)", "absence"),
    ("a job's succeeded", "outcome"),
    ("exits and links", "T1"),
)
# The copy deck's closed key set (section 14): a new key (a lock string, a state key) is a FAIL.
DECK_KEYS = frozenset(
    (
        "storage.title",
        "storage.stamp",
        "storage.stamp.stale",
        "storage.stamp.sampling",
        "storage.meter.budget",
        "storage.meter.volume",
        "storage.projection",
        "storage.headline.0",
        "storage.headline.1",
        "storage.headline.2",
        "storage.headline.3",
        "storage.level3.fact",
        "storage.formula",
        "storage.scale",
        "storage.degradation",
        "storage.degradation.detail",
        "storage.autostop.next",
        "storage.accelerated",
        "storage.volume_refused",
        "storage.actions.shorten",
        "storage.actions.depth",
        "storage.actions.unpin",
        "storage.tier.questdb",
        "storage.tier.parquet",
        "storage.tier.postgres",
        "storage.tier.rows",
        "storage.tier.not_counted",
        "storage.tier.all_tiers",
        "storage.tier.health",
        "storage.tier.unreachable",
        "storage.tier.retry",
        "storage.ingestion",
        "storage.lag.banner",
        "storage.proposed.caption",
        "storage.proposed.rows",
        "storage.proposed.queries",
        "storage.compaction.schedule",
        "storage.symbols.attributed",
        "storage.migration.banner",
        "storage.unavailable",
        "storage.stale.announce",
        "notice.panel_read_only",
        "rbac.view_as",
        "storage.compact.button",
        "storage.compact.title",
        "storage.compact.body",
        "storage.vacuum.button",
        "storage.vacuum.title",
        "storage.vacuum.body",
        "storage.audited",
        "storage.confirm.cancel",
        "storage.job.running",
        "storage.job.started",
        "storage.job.stop",
        "storage.job.refused.running",
        "storage.compact.succeeded",
        "storage.compact.failed",
        "storage.compact.cancelled",
        "storage.compact.unknown",
        "storage.vacuum.succeeded",
        "storage.vacuum.failed",
        "storage.vacuum.cancelled",
        "storage.vacuum.unknown",
        "storage.purge.button",
        "storage.purge.title",
        "storage.purge.body",
        "storage.purge.before",
        "storage.purge.before.help",
        "storage.purge.before.reason",
        "storage.purge.refused.before",
        "storage.purge.typed",
        "storage.purge.typed.reason",
        "storage.purge.stepup",
        "storage.purge.stepup.trusted",
        "storage.purge.audited",
        "storage.purge.confirm",
        "storage.purge.refused.pinned",
        "storage.purge.refused.audit",
        "storage.purge.failed",
        "storage.purge.cancelled",
        "storage.purge.unknown",
        "storage.purge.succeeded",
        "storage.import.button",
        "storage.import.consequence",
        "storage.import.tag",
        "storage.import.range.reason",
        "storage.import.progress",
        "storage.import.skipped_count",
        "storage.import.finished",
        "storage.import.columns",
        "storage.import.status",
        "storage.import.reason.checksum",
        "storage.import.reason.parse",
        "storage.import.reason.download",
        "storage.import.reason.already",
        "storage.import.overlap",
        "storage.import.summary",
        "storage.import.failed",
        "storage.import.cancelled",
        "storage.import.unknown",
        "storage.import.resume",
        "storage.links.storage_details",
        "storage.links.health",
    )
)
# Numbers (R-17): every number a unit shows must be a `--json` value. Stripped first: markers (checked on their own),
# code spans, line cites, section refs, rule / ticket / component ids, issue numbers, commit shas, ordinals.
NUM_EXEMPT: tuple[str | re.Pattern[str], ...] = (
    re.compile(r"[\d,.:-]+\s*<!-- audit:.*?--!?>", re.DOTALL),
    re.compile(r"<!--.*?--!?>", re.DOTALL),
    r"`[^`]*`",
    r"\b\d\d:\d{3,5}(?:–\d+)?\b",
    r"\bBQ-\d+(?:\s*/\s*\d+)*",
    r"\bAC [1-3]\b",
    r"\blevels?\s*(?:≥|>=|=)?\s*\d(?:[–-]\d)?\b",
    r"\b0\d\d\b",
    r"\b\d{9,}\b",
    r"(?<![\d:]):\d+(?:–\d+)?",
    r"§\s?\d+(?:\.\d+)*(?:–\d+(?:\.\d+)*)?",
    r"\b(?:[A-Z]{1,4}\d*-)+[A-Z]{0,3}\d+(?:\.\d+)?(?:-[a-z])?\b",
    r"\b[AEFWQ]\d+\b",
    r"#\d+",
    r"\b(?:PR|pulls?|pull request)\s*/?\s*\d+",
    r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b",
    r"\b(?:boards?|Sprint|step|steps|rules?|item|condition|WCAG|round|Board)\s\d[\d,.–]*(?:(?:, | and | / )\d\d)*",
    r"\b(?:SCR|CMP|BQ)-\d+",
)
NUM_UNIT = (
    r"GB/day|MB/day|msg/s|GB|TB|MB|MiB|%|days?|d|ms|min|s|px|rows?|files?|batches|pending|done|skipped"
    r"|downloading|h|characters|fields|values|headings|items|frames|boards|mutations|samples|points"
    r"|jobs|symbols|pairs|flows|regions"
)
NUM_CORE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
NUM_TOKEN = (
    rf"(?P<date>\b\d{{4}}-\d{{2}}-\d{{2}}\b)|(?P<time>\b\d{{2}}:\d{{2}}(?::\d{{2}})?\b)"
    rf"|(?P<num>(?<![\w.-])(?:{NUM_CORE}))(?:\s?(?P<unit>(?:{NUM_UNIT}))(?![\w/]))?"
)


def negated(text: str, start: int) -> bool:
    """A negator governs the match at `start` when it stands within four words before it in the same clause."""
    before = re.split(CLAUSE_STOP, text[:start])[-1].replace("`", "")
    words = re.findall(r"[\w'’-]+", before)[-4:]
    return any(re.fullmatch(NEGATOR, w, re.IGNORECASE) for w in words)


def positive_term(text: str, pattern: str, flags: int = re.IGNORECASE) -> str | None:
    """The first match of `pattern` in `text` that no nearby negator governs, or None."""
    for m in re.finditer(pattern, text, flags):
        if not negated(text, m.start()):
            return m.group(0)
    return None


PRONOUN_LEAD = (
    r"(?i:^\W*(?:it|its|this|that|these|those|they|them|their|then|both|each|either|neither|all)\b)"
)


def subject_at(text: str, i: int, carried: str, kinds: dict[str, str]) -> str:
    """The kind of the nearest subject named before offset i in `text` (across any punctuation), else `carried`."""
    best, kind = -1, ""
    for name, pat in kinds.items():
        for m in re.finditer(pat, text[:i]):
            if m.end() > best:
                best, kind = m.end(), name
    return kind or carried


def last_subject(text: str, carried: str, kinds: dict[str, str]) -> str:
    """The kind of the last subject `text` names, else `carried` (what the next item or sentence speaks of)."""
    return subject_at(text, len(text), carried, kinds)


def ctrl_kinds(dialog: bool) -> dict[str, str]:
    """Exits and writes by full and short name; in a dialog frame a bare Cancel is the dialog's exit."""
    exit_ = EXIT_TERM + (r"|\bCancel\b" if dialog else "")
    return {"exit": exit_, "write": WRITE_TERM, "key": KEY_TERM}


ACTION_KINDS = {"purge": PURGE_SUBJ, "other": OTHER_ACTION}


def gated_term(
    x: str,
    carried: str,
    kinds: dict[str, str],
    want_exit: bool,
    only: tuple[str, ...] = ("lock", "dim", "dead"),
) -> tuple[str, str] | None:
    """The first un-negated lock, dim or (on an exit) dead word whose subject is (want_exit) or is not an exit:
    (word, kind). The dead class is read only for exits (A3: an exit accepts only T1)."""
    pats = (("lock", LOCK_TERM), ("dim", DIM_TERM)) + ((("dead", DEAD_TERM),) if want_exit else ())
    hits = sorted(
        (m.start(), m.group(0), which)
        for which, pat in pats
        if which in only
        for m in re.finditer(pat, x, re.IGNORECASE)
        if not negated(x, m.start())
    )
    for i, word, which in hits:
        is_exit = subject_at(x, i, carried, kinds) == "exit"
        if is_exit == want_exit:
            return word, which
    return None


def fill_term(x: str, carried_typed: bool) -> str | None:
    """R-7: a strong fill word anywhere, or a context fill word whose subject is the typed field."""
    if (term := positive_term(x, FILL)) is not None:
        return term
    for m in re.finditer(FILL_CONTEXT, x, re.IGNORECASE):
        if negated(x, m.start()):
            continue
        if re.search(TYPED_SUBJ, x[: m.start()], re.IGNORECASE) or carried_typed:
            return m.group(0)
    for m in re.finditer(FIELD_HOLDS, x, re.IGNORECASE):
        if not negated(x, m.start()) and not re.search(
            rf"\b{NEGATOR}\b", m.group(0), re.IGNORECASE
        ):
            return m.group(0)
    return None


def second_purge(x: str, carried: str) -> str | None:
    """R-21: a second purge shape, read when purge is the subject (named before, carried, or in the words)."""
    for m in re.finditer(SECOND_PURGE, x, re.IGNORECASE):
        if negated(x, m.start()):
            continue
        near = x[m.start() : m.end() + 16].lower()  # the words name it: "a one-click purge"
        if "purge" in near or subject_at(x, m.start(), carried, ACTION_KINDS) == "purge":
            return m.group(0)
    return None


def order_issue(x: str) -> str | None:
    """R-5 in any wording: 'inverted (…)' when trading is said to stop first, 'weakened (…)' when the order is
    hedged; a governing negator exempts the trading clause."""
    for kind, pats in (("inverted", INVERTED), ("weakened", WEAKENED)):
        for p in pats:
            # overlapping matches: a negated trading word must not swallow the clause after it
            for m in re.finditer(rf"(?=({p}))", x, re.IGNORECASE):
                if negated(x, m.start()) or (
                    kind == "weakened" and re.search(r"\bnever\b", m.group(1), re.IGNORECASE)
                ):
                    continue
                return f"{kind} ({m.group(1)[:48]!r})"
    return sequence_issue(x)


def statements(x: str) -> list[str]:
    """The statements R-5 orders: sentences and ` · ` items (a `;` or a `,` does not end one)."""
    return [p for p in re.split(r"\s·\s|(?<=[.!?])\s+", x) if p.strip()]


def trade_event(st: str) -> re.Match[str] | None:
    """The first trading subject with an un-negated stopping predicate within four words in its clause."""
    for m in re.finditer(SEQ_TRADE, st, re.IGNORECASE):
        tail = re.split(r"[;:()—]|,\s(?=and\b|but\b|then\b)", st[m.end() :])[0]
        h = re.match(rf"\W+(?:[\w'’-]+\W+){{0,4}}?{SEQ_HALT}", tail, re.IGNORECASE)
        if h and not negated(st, m.end() + h.end() - 1) and not negated(st, m.start()):
            words = re.findall(r"[\w'’-]+", tail[: h.end()])
            if not any(re.fullmatch(NEGATOR, w, re.IGNORECASE) for w in words):
                return m
    return None


def sequence(st: str) -> str | None:
    """'trade-first', 'same' or 'rec-first' for a statement that names a trading event and the recording side;
    None when it does not name both."""
    t = trade_event(st)
    r = re.search(SEQ_REC, st, re.IGNORECASE)
    if t is None or r is None:
        return None
    a, b = (t, r) if t.start() < r.start() else (r, t)
    first_is_trade = a is t
    between = st[a.end() : b.start()]
    lead = st[: a.start()]
    # a leading connector: "Before X, Y" (Y first), "After / Once / Only after X, Y" (X first)
    if re.search(rf"^\W*{SEQ_BEFORE}", lead, re.IGNORECASE):
        return "rec-first" if first_is_trade else "trade-first"
    if re.search(rf"^\W*{SEQ_AFTER}", lead, re.IGNORECASE):
        return "trade-first" if first_is_trade else "rec-first"
    # a connector between: "A before B" (A first), "A after / once / until B" (B first), "A as / while B" (same)
    for conn, a_first in ((SEQ_AFTER, False), (SEQ_BEFORE, True)):
        c = re.search(conn, between, re.IGNORECASE)
        if c and not negated(between, c.start()):
            trade_first = first_is_trade == a_first
            return "trade-first" if trade_first else "rec-first"
    # sequence adverbs in each side's clause
    t_cl = clause_around(st, t.start())
    r_cl = clause_around(st, r.start())
    if re.search(SEQ_FIRST, t_cl, re.IGNORECASE) or re.search(SEQ_LATER, r_cl, re.IGNORECASE):
        return "trade-first"
    if re.search(SEQ_FIRST, r_cl, re.IGNORECASE) or re.search(SEQ_LATER, t_cl, re.IGNORECASE):
        return "rec-first"
    if re.search(SEQ_SAME, between, re.IGNORECASE) or re.fullmatch(r"\W*and\W*", between):
        return "same"
    return "trade-first" if first_is_trade else "rec-first"


def clause_around(st: str, i: int) -> str:
    """The clause of `st` holding offset i (bounded by `,` `;` `:` `(` `)` `—`)."""
    starts = [m.end() for m in re.finditer(r"[,;:()—]", st[:i])]
    end = re.search(r"[,;:()—]", st[i:])
    return st[(starts[-1] if starts else 0) : i + (end.start() if end else len(st) - i)]


def sequence_issue(x: str) -> str | None:
    """R-5 by sequence: the first statement whose trading event comes first or at the same time."""
    for st in statements(x):
        seq = sequence(st)
        if seq in ("trade-first", "same"):
            kind = "trading first" if seq == "trade-first" else "at the same time"
            return f"{kind} ({st.strip()[:48]!r})"
    return None


def ruled_order(x: str) -> bool:
    """The ruled order stated in any wording (recording pauses before trading is affected)."""
    if order_issue(x) is not None:
        return False
    return any(re.search(p, x, re.IGNORECASE) for p in RULED_ORDER) or any(
        sequence(st) == "rec-first" for st in statements(x)
    )


def shipped_mention(
    text: str, dialog: bool = False, whole: bool = False, strong: bool = True
) -> tuple[str, str, int] | None:
    """The first PROPOSED item `text` presents as shipped, as (name, the words, its gap n), or None. `text` is
    scrubbed (captions read CAPTIONn); a clause ends at `;` ` · ` a sentence break or a cell bar. A name (DOC_STRONG)
    is answered by the caption or the absence with its gap id in its own clause, or, in a table row (`whole`), in
    another cell of the row (the deck's Source, a gap or class column). A presenting form (SHIPPED) must be
    answered in its own clause."""
    gap_ids = {what: ids for what, _, ids in CARRIERS} | {k: v[1] for k, v in DOC_STRONG.items()}

    def answered(scope: str, ids: frozenset[int]) -> bool:
        caps = {int(n) for n in re.findall(r"CAPTION(\d+)", scope)}
        named = {int(n) for n in re.findall(r"\b(?:D04-)?G(\d+)\b", scope)}
        return bool(caps & ids) or (re.search(GAP_ABSENT, scope) is not None and bool(named & ids))

    # in a table row (`whole`) the row's OTHER cells answer for a name (a gap, source or class column: the deck's
    # `new` (PROPOSED D04-Gn)); within one cell, each clause answers only for itself
    exit_ = EXIT_CANCEL + (r"|\bCancel\b" if dialog else "")
    cells_ = text.split("|") if whole else [text]
    for ci, cell in enumerate(cells_):
        others = " ".join(c for j, c in enumerate(cells_) if j != ci)
        gap_col = " ".join(
            f"PROPOSED {c}"
            for j, c in enumerate(cells_)
            if j != ci and c.strip() and re.fullmatch(GAP_CELL, c.strip())
        )
        for clause in re.split(r";|\s·\s|\.\s", cell):
            bare = unmasked = re.sub(exit_, " ", clause)
            names = [(k, v[0]) for k, v in DOC_STRONG.items()] if strong else []
            for what, pat in names + list(SHIPPED.items()):
                ids = gap_ids[what]
                term = positive_term(bare if (what, pat) in names else unmasked, pat)
                if term is None:
                    continue
                named_ = (what, pat) in names
                row_scope = f"{clause} {others} {gap_col}"
                if not answered(clause, ids) and not (named_ and answered(row_scope, ids)):
                    return what, term, min(ids)
                if named_:  # an answered name is masked: a shorter name inside it is not read twice
                    bare = re.sub(pat, " ", bare, flags=re.IGNORECASE)
    return None


def items(cell: str) -> list[str]:
    """A cell's items: split on ' · ' and '; ' outside double quotes (a quoted string stays whole)."""
    out: list[str] = []
    buf: list[str] = []
    quoted, i = False, 0
    while i < len(cell):
        ch = cell[i]
        if ch == '"':
            quoted = not quoted
        if not quoted and cell.startswith((" · ", "; "), i):
            out.append("".join(buf))
            buf = []
            i += 3 if cell.startswith(" · ", i) else 2
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def scrub(text: str) -> str:
    """Frame refs and ruled captions out of a scan (a frame named `…/unavailable` is not an unavailable control)."""
    text = re.sub(r"<!--.*?--!?>", "", text, flags=re.DOTALL)
    text = re.sub(r"(?:SCR-142|TIER|JOB|PURGE|IMPORT)/[a-z0-9-]+|(?<=`)/[a-z0-9-]+", "FRAME", text)
    text = re.sub(r"`(?:storage|notice|rbac)\.[a-z_.0-9]+`", "KEY", text)
    return re.sub(CAP_RE, lambda m: f"CAPTION{m.group(1)}", text)


def num_tokens(text: str) -> list[tuple[str, str]]:
    """(value, unit) for every number a unit types, after the exempt forms are stripped; dates and times keyed."""
    for p in NUM_EXEMPT:
        text = re.sub(p, " ", text)
    out = []
    for m in re.finditer(NUM_TOKEN, text):
        if m.group("date"):
            out.append((m.group("date"), "date"))
        elif m.group("time"):
            out.append((m.group("time"), "time"))
        else:
            out.append((m.group("num").replace(",", ""), m.group("unit") or ""))
    return out


def registry(numbers: dict[str, Any]) -> tuple[set[tuple[str, str]], set[float]]:
    """Every (value, unit) pair and every bare value the tool's `--json` carries (R-17's register)."""
    pairs: set[tuple[str, str]] = set()
    vals: set[float] = set()

    def walk(v: object) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            return
        elif isinstance(v, int | float):
            vals.add(float(v))
        elif isinstance(v, str):
            for val, unit in num_tokens(v):
                pairs.add((val, unit))
                if unit not in ("date", "time"):
                    vals.add(float(val))

    walk(numbers)
    return pairs, vals


def unregistered(text: str, reg: tuple[set[tuple[str, str]], set[float]]) -> str | None:
    pairs, vals = reg
    for val, unit in num_tokens(text):
        if unit and (val, unit) not in pairs:
            return f"{val} {unit}" if unit not in ("date", "time") else val
        if not unit and float(val) not in vals:
            return val
    return None


def owner_of(frame: str, cls: str) -> str:
    """Which rule owns a row's lock reading: R-13 the view-as frame, R-8 a validity row, R-11 the strip rows,
    none the redlines sheet, R-6 every other row."""
    if frame == "SCR-142/view-as":
        return "R13"
    if "validity" in cls.lower():
        return "R8"
    if frame.startswith("JOB/strip-"):
        return "R11"
    if frame == "SCR-142/redlines":
        return "none"
    return "R6"


def required_numbers(fx: dict[str, Any]) -> dict[str, list[str]]:
    """R-17: the tool's fixture strings each frame row must repeat (the rows R-1 reads keep their unit gate)."""
    t, sy, lv, imp, lag = fx["tiers"], fx["symbols"], fx["levels"], fx["imp"], fx["lag"]
    return {
        "SCR-142/healthy": [fx["runway"], fx["full_date"], fx["budget_pct"], fx["volume_pct"]],
        "SCR-142/low-disk-warning": [lv["1"]["pct"], lv["1"]["runway_next"]],
        "SCR-142/autostop": [lv["2"]["pct"], lv["2"]["runway_next"]],
        "SCR-142/read-only-disk-full": [lv["3"]["pct"]],
        "TIER/questdb": [t["questdb"]["share"]],
        "TIER/parquet": [t["parquet"]["share"]],
        "TIER/postgres": [t["postgres"]["size"]],
        "TIER/per-symbol": [
            sy[0]["size"],
            sy[0]["growth"],
            sy[0]["share"],
            sy[1]["size"],
            sy[1]["growth"],
            fx["symbols_sum"],
        ],
        "SCR-142/lag-warning": [lag["backlog"], lag["ingest_rate"]],
        "SCR-142/migration-pending": [
            f"{fx['migration']['pending']} pending",
            f"{fx['migration']['schema_version']} → {fx['migration']['target_version']}",
        ],
        "SCR-142/tier-unreachable-questdb": [fx["last_good"]],
        "IMPORT/running": [
            f"{imp['running_done']} of {imp['days']} days",
            f"{imp['running_pct']} %",
        ],
        "IMPORT/running-with-skips": [
            f"{imp['skip_processed']} of {imp['days']} days",
            f"{imp['skip_done']} done",
            f"{imp['skip_pct']} %",
        ],
        "IMPORT/summary": [imp["overlap_rows"].split(" ")[0], f"{imp['skip_done']} days"],
        "JOB/strip-running": [f"{fx['jobs']['compact_pct']} %", f"{imp['running_pct']} %"],
    }


Anchor = tuple[str, dict[str, set[tuple[str, ...]]], str]


def anchor_table(
    fx: dict[str, Any], facts: dict[str, Any], ctx: dict[str, Any] | None = None
) -> list[Anchor]:
    """R-17 anchors: each typed number bound to its own `--json` value through its context words, per frame where
    the value differs by frame ("*" = every other frame row and every unit of the document). A swap of one
    registered value for another fails here, not only a value outside the register."""
    d = facts["disk"]
    warn, auto, halt = d["CV_DISK_WARN_PCT"], d["CV_DISK_AUTOSTOP_PCT"], d["CV_DISK_HALT_PCT"]
    t, sy, lv, imp, lag, mig = (
        fx["tiers"],
        fx["symbols"],
        fx["levels"],
        fx["imp"],
        fx["lag"],
        fx["migration"],
    )
    comp = facts["compaction"]

    def one(*v: object) -> set[tuple[str, ...]]:
        return {tuple(norm(str(x)) for x in v)}

    out: list[tuple[str, dict[str, set[tuple[str, ...]]], str]] = [
        ("the warning step", {"*": one(warn)}, r"\b(\d+) % warning\b"),
        ("the autostop step", {"*": one(auto)}, r"\b(\d+) % auto-record pauses"),
        ("the halt step", {"*": one(halt)}, r"\b(\d+) % recording stops\b"),
        ("the warning step", {"*": one(warn)}, r"\bat (\d+) % of the recording budget \(or"),
        (
            "the autostop step",
            {"*": one(auto)},
            r"\b[Aa]t (\d+) % (?:of the recording budget auto-record pauses|new auto-record starts)",
        ),
        ("the halt step", {"*": one(halt)}, r"\b[Aa]t (\d+) % (?:\(or less than|recording stops)"),
        ("the halt step", {"*": one(halt)}, r"\bRecording stops at (\d+) %"),
        ("the warning clear", {"*": one(warn - 5)}, r"\bclears below (\d+) %"),
        ("the autostop clear", {"*": one(auto - 5)}, r"\bresumes below (\d+) % of the budget"),
        ("the halt clear", {"*": one(halt - 5)}, r"\bresumes below (\d+) % with"),
        ("the merge size", {"*": one(comp["merge_mib"])}, r"\bat most ([\d,]+) MiB"),
        ("the lag threshold", {"*": one(lag["threshold_batches"])}, r"\b(\d+) (?:ILP )?batches\b"),
        ("the ILP batch", {"*": one(facts["ilp_batch_rows"])}, r"\bbatches of ([\d,]+) rows"),
        (
            "the tier size",
            {f"TIER/{k}": one(t[k]["size"]) for k in t} | {"*": set()},
            r"\bSize ([\d,.]+ GB)",
        ),
        (
            "the tier share",
            {f"TIER/{k}": one(t[k]["share"]) for k in ("questdb", "parquet")} | {"*": set()},
            r"\bShare of budget ([\d.]+ %)",
        ),
        (
            "the tier retention",
            {f"TIER/{k}": one(t[k]["retention"]) for k in t} | {"*": set()},
            r"\bRetention (\d+ d|—)",
        ),
        (
            "the tier sizes",
            {"*": one(t["questdb"]["size"], t["parquet"]["size"], t["postgres"]["size"])},
            r"\bSize ([\d,.]+ GB)\s+Size ([\d,.]+ GB)\s+Size ([\d,.]+ GB)",
        ),
        (
            "the tier retentions",
            {
                "*": one(
                    t["questdb"]["retention"], t["parquet"]["retention"], t["postgres"]["retention"]
                )
            },
            r"\bRetention (\d+ d|—)\s+Retention (\d+ d|—)\s+Retention (\d+ d|—)",
        ),
        (
            "the budget meter",
            {"*": one(fx["budget_used"], fx["cap"])},
            r"\bRecording budget:? +(?:\[[^\]]*\] +)?([\d,.]+ GB) of ([\d,.]+ GB)",
        ),
        (
            "the volume meter",
            {"*": one(fx["disk_used"], fx["disk_total"])},
            r"\bDisk volume:? +(?:\[[^\]]*\] +)?([\d.]+ TB) of ([\d.]+ TB)",
        ),
        (
            "the free volume",
            {"*": one(fx["disk_free"])},
            r"\bfree ([\d.]+ TB)|\b([\d.]+ TB) free\b",
        ),
        (
            "the budget share",
            {"*": one(fx["budget_pct"])},
            r"\bRecording budget:? +(?:\[[^\]]*\] +)?[\d,.]+ GB of [\d,.]+ GB(?: cap_bytes)? \(([\d.]+ %)\)",
        ),
        (
            "the volume share",
            {"*": one(fx["volume_pct"])},
            r"\bDisk volume:? +(?:\[[^\]]*\] +)?[\d.]+ TB of [\d.]+ TB(?: disk_total_bytes)? \(([\d.]+ %)\)",
        ),
        (
            "the projection",
            {"*": one(fx["runway"].split()[1], fx["full_date"], fx["growth"])},
            r"\bFull in about ([\d,]+) days \((\d{4}-\d\d-\d\d)\) at ([\d.]+ GB/day)",
        ),
        (
            "the volume wall",
            {"*": one(fx["volume_wall"].split()[1])},
            r"\bthe volume about ([\d,]+) days",
        ),
        (
            "the headline runway",
            {
                "SCR-142/low-disk-warning": one(lv["1"]["runway_next"].split()[1]),
                "*": one(lv["0"]["runway_next"].split()[1]),
            },
            r"\bauto-record pauses in about ([\d,]+) days",
        ),
        (
            "the halt runway",
            {"*": one(lv["2"]["runway_next"].split()[1])},
            r"\bRecording stops at \d+ % in about ([\d,]+) days",
        ),
        (
            "the formula",
            {
                "*": one(
                    auto,
                    fx["cap"],
                    fx["budget_used"],
                    fx["growth"],
                    lv["0"]["runway_next"].split()[1],
                )
            },
            r"\((\d+) % × ([\d,.]+ GB) − ([\d,.]+ GB)\) ÷ ([\d.]+ GB/day) ≈ ([\d,]+) days",
        ),
        ("the all-tiers growth", {"*": one(fx["growth"])}, r"\ball tiers ([\d.]+ GB/day)"),
        ("the all-tiers date", {"*": one(fx["full_date"])}, r"\ball tiers (\d{4}-\d\d-\d\d)"),
        (
            "the level meter",
            {
                "SCR-142/low-disk-warning": one(lv["1"]["pct"]),
                "SCR-142/autostop": one(lv["2"]["pct"]),
                "SCR-142/read-only-disk-full": one(lv["3"]["pct"]),
                "*": {(norm(lv[k]["pct"]),) for k in ("1", "2", "3")},
            },
            r"\bthe budget meter at ([\d.]+ %)",
        ),
        (
            "the level budget",
            {
                "SCR-142/healthy": one(lv["0"]["pct"]),
                "SCR-142/low-disk-warning": one(lv["1"]["pct"]),
                "SCR-142/autostop": one(lv["2"]["pct"]),
                "SCR-142/read-only-disk-full": one(lv["3"]["pct"]),
                "*": {(norm(lv[k]["pct"]),) for k in ("0", "1", "2", "3")},
            },
            r"\(budget ([\d.]+ %)",
        ),
        ("the ingest rate", {"*": one(lag["ingest_rate"].split()[0])}, r"\bIngest ([\d,]+) msg/s"),
        (
            "the backlog",
            {
                "TIER/questdb": one(lag["healthy_backlog_rows"]),
                "SCR-142/lag-warning": one(lag["backlog_rows"]),
                "*": one(lag["healthy_backlog_rows"]) | one(lag["backlog_rows"]),
            },
            r"\bbacklog ([\d,]+) rows",
        ),
        (
            "the import progress",
            {
                "*": one(imp["running_done"], imp["days"], imp["running_pct"])
                | one(imp["skip_processed"], imp["days"], imp["skip_pct"])
            },
            r"\b([\d,]+) of ([\d,]+) days · (\d+) %",
        ),
        (
            "the import strip",
            {
                "JOB/strip-running": one(imp["running_pct"]),
                "IMPORT/running-with-skips": one(imp["skip_pct"]),
                "*": one(imp["running_pct"]) | one(imp["skip_pct"]),
            },
            r"\bImport running · (\d+) %",
        ),
        (
            "the compaction strip",
            {"*": one(fx["jobs"]["compact_pct"])},
            r"\bCompaction running · (\d+) %",
        ),
        (
            "the overlap",
            {"*": one(imp["overlap_rows"].split()[0])},
            r"\b([\d,]+) (?:overlapping rows|rows inside recorded windows)",
        ),
        ("the imported days", {"*": one(imp["skip_done"])}, r"\bImported (\d+) days"),
        (
            "the done count",
            {"IMPORT/running-with-skips": one(imp["skip_done"]), "*": set()},
            r"\b(\d+) done\b",
        ),
        (
            "the attribution",
            {"*": one(fx["symbols_sum"], fx["budget_used"], fx["attributed_pct"])},
            r"\b([\d,.]+ GB) of ([\d,.]+ GB) attributed to symbols \(([\d.]+ %)\)",
        ),
        (
            "the BTCUSDT row",
            {"*": one(sy[0]["size"], sy[0]["growth"], sy[0]["share"])},
            r"\bBTCUSDT ([\d,.]+ GB) ([\d,]+ MB/day) ([\d.]+ %)",
        ),
        (
            "the ETHUSDT row",
            {"*": one(sy[1]["size"], sy[1]["growth"], sy[1]["share"])},
            r"\bETHUSDT ([\d,.]+ GB) ([\d,]+ MB/day) ([\d.]+ %)",
        ),
        ("the sample time", {"*": one(fx["sample_time"])}, r"\bSampled (\d\d:\d\d:\d\d) UTC"),
        ("the stale age", {"*": one(fx["stale_age"].split()[0])}, r"\bstale \((\d+) min old\)"),
        (
            "the last good time",
            {"*": one(fx["last_good"].split()[0])},
            r"\bsince (\d\d:\d\d:\d\d) UTC",
        ),
        (
            "the migration",
            {"*": one(mig["pending"], mig["schema_version"], mig["target_version"])},
            r"\b(\d+) pending · (\d{4}) → (\d{4})",
        ),
        (
            "the purge window",
            {"*": one(fx["purge"]["size"], fx["purge"]["from"], fx["purge"]["before"])},
            r"\babout ([\d.]+ GB) recorded from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)",
        ),
        (
            "the purge cut-off",
            {"*": one(fx["purge"]["before"])},
            r"\(CMP-047 single\) (\d{4}-\d\d-\d\d)",
        ),
        (
            "the compacted time",
            {"*": one(first(r"(\d\d:\d\d)", fx["jobs"]["compacted_at"]))},
            r"\bCompacted at (\d\d:\d\d) UTC",
        ),
        ("the rows per day", {"*": one(imp["rows_per_day"].split()[0])}, r"done ✓ / ([\d,]+) rows"),
        ("the purged size", {"*": one(fx["purge"]["size"])}, r"\bPurged ([\d.]+ GB) of ETHUSDT"),
    ]
    out += frame_anchors(fx, facts, ctx or {})
    return out


LEVEL_OF = {
    "SCR-142/low-disk-warning": "1",
    "SCR-142/autostop": "2",
    "SCR-142/read-only-disk-full": "3",
    "SCR-142/volume-refused": "3",
}


def frame_anchors(fx: dict[str, Any], facts: dict[str, Any], ctx: dict[str, Any]) -> list[Anchor]:
    """M5: the keys binding every other number a frame row types (an unbound one is a FAIL, never
    a pass on register membership); each value is the tool's own, per frame where it differs."""
    lv, imp, lag, mig, comp = (
        fx["levels"],
        fx["imp"],
        fx["lag"],
        fx["migration"],
        facts["compaction"],
    )
    lay = LAYOUT

    def one(*v: object) -> set[tuple[str, ...]]:
        return {tuple(norm(str(x)) for x in v)}

    def grab(pat: str, text: str) -> tuple[str, ...]:
        m = re.search(pat, text)
        return tuple(norm(g) for g in m.groups()) if m else ("MISSING",)

    free = {k: grab(r"with (\d+) % of the volume free", lv[k]["headline"]) for k in ("2", "3")}
    counts = grab(r"(\d+) done · (\d+) skipped · (\d+) downloading", imp["skip_counts"])
    files = grab(r"· (\d+) file skipped · (\d+) file failed", imp["summary"])
    skipped = grab(r"· (\d+) skipped$", imp["skip_line"])
    lo, hi = facts["reason_bounds"]
    levels = {f: one(k) for f, k in LEVEL_OF.items()}
    return [
        ("the level", levels | {"*": {(k,) for k in ("0", "1", "2", "3")}}, r"`level` ([0-3])\b"),
        (
            "the level bytes",
            {
                "SCR-142/low-disk-warning": one(lv["1"]["used"], fx["cap"]),
                "SCR-142/autostop": one(lv["2"]["used"]),
                "SCR-142/read-only-disk-full": one(lv["3"]["used"]),
                "*": set(),
            },
            r"\(budget [\d.]+ %[^)]*?([\d,]+\.\d GB)(?: of ([\d,]+\.\d GB))?\)",
        ),
        (
            "the unchanged bytes",
            {"*": one(fx["budget_used"])},
            r"\bthe bytes unchanged: ([\d,.]+ GB)",
        ),
        (
            "the sample interval",
            {"*": one(facts["disk"]["CV_DISK_SAMPLE_INTERVAL_S"])},
            r"\bevery (\d+) s\b",
        ),
        ("the strip poll", {"*": one(lay["poll_s"])}, r"\b(\d+) s polling\b"),
        (
            "the stale rule",
            {"*": one(lay["stale_factor"], facts["disk"]["CV_DISK_SAMPLE_INTERVAL_S"])},
            r"\bmore than (\d+) × (\d+) s\b",
        ),
        ("the viewport", {"*": one(lay["vp_w"], lay["vp_h"])}, r"\((\d+) × (\d+)\)"),
        (
            "the compaction schedule",
            {"*": grab_set(comp["schedule"])},
            r"\bSundays (\d\d:\d\d) UTC",
        ),
        (
            "the healthy migration",
            {"*": one(mig["schema_version"], mig["healthy_pending"])},
            r"\bMigration (\d{4}), (\d+) pending",
        ),
        (
            "the pending migration",
            {"*": one(mig["schema_version"], mig["pending"])},
            r"\"(\d{4}), (\d+) pending\"",
        ),
        (
            "the migration fields",
            {"*": one(mig["pending"], mig["schema_version"], mig["target_version"])},
            r"`pending_migrations` (\d+), `schema_version` (\d{4}), `target_version` (\d{4})",
        ),
        ("the query window", {"*": one(lay["query_window_h"])}, r"\bCount \((\d+) h\)"),
        (
            "the free volume share",
            {
                "SCR-142/autostop": {free["2"]},
                "SCR-142/read-only-disk-full": {free["3"]},
                "SCR-142/volume-refused": {free["3"]},
                "*": {free["2"], free["3"]},
            },
            r"\bwith (\d+) % of the volume free",
        ),
        (
            "the backlog field",
            {"*": one(lag["backlog_rows"], lag["threshold_batches"], facts["ilp_batch_rows"])},
            r"`write_backlog_rows` ([\d,]+) \((\d+) ILP batches of ([\d,]+) rows",
        ),
        (
            "the ingest field",
            {"*": one(lag["ingest_rate"].split()[0])},
            r"`ingest_rate_msgs_per_sec` ([\d,]+)",
        ),
        (
            "the last report",
            {"*": one(fx["sample_time"])},
            r"\bthe last report (\d\d:\d\d:\d\d) UTC",
        ),
        (
            "the last good field",
            {"*": one(fx["last_good"].split()[0])},
            r"`last_good_at` (\d\d:\d\d:\d\d) UTC",
        ),
        (
            "the HTTP code",
            {"*": {(str(c),) for c in ctx.get("http_codes", [])}},
            r"\banswers (\d{3})\b",
        ),
        (
            "the job progress",
            {
                "JOB/strip-running": one(fx["jobs"]["compact_pct"]),
                "IMPORT/running": one(imp["running_pct"]),
                "*": one(fx["jobs"]["compact_pct"]) | one(imp["running_pct"]),
            },
            r"`progress_pct` (\d+)",
        ),
        ("the import progress field", {"*": one(imp["running_pct"])}, r"\ban import \((\d+)\)"),
        ("the reason bounds", {"*": one(lo, hi)}, r"\b(\d+)–(\d+) characters\b"),
        ("the reason minimum", {"*": one(lo)}, r"\bshorter than (\d+) characters\b"),
        (
            "the validity opacity",
            {"*": one(ctx.get("opacity", ""))},
            r"`opacity\.disabled` ([\d.]+)",
        ),
        (
            "the import range",
            {"*": one(imp["from"], imp["to"])},
            r"\b(\d{4}-\d\d-\d\d) → (\d{4}-\d\d-\d\d)",
        ),
        (
            "the import cap",
            {"*": one(facts["import_days_max"])},
            r"\b(?:at most|longer than) (\d+) days\b",
        ),
        (
            "the skipped day",
            {"*": one(int(imp["skipped_day"][-2:]), imp["skipped_day"])},
            r"\bday (\d+) \((\d{4}-\d\d-\d\d)\)",
        ),
        (
            "the per-file counts",
            {"*": {counts}},
            r"\b(\d+) done, (\d+) skipped, (\d+) downloading\b",
        ),
        ("the skip counter", {"*": {skipped}}, r"\bthe counter \"(\d+) skipped\""),
        (
            "the per-file row",
            {
                "IMPORT/running-with-skips": one(imp["skipped_day"]),
                "IMPORT/summary": one(imp["error_day"]),
                "*": one(imp["skipped_day"]) | one(imp["error_day"]),
            },
            r"\bthe (\d{4}-\d\d-\d\d) row\b",
        ),
        ("the file counts", {"*": {files}}, r"· (\d+) file skipped · (\d+) file failed\b"),
    ]


def grab_set(text: str) -> set[tuple[str, ...]]:
    """The HH:MM a schedule string carries, as an anchor value set."""
    m = re.search(r"(\d\d:\d\d)", text)
    return {(m.group(1),)} if m else set()


def unbound(text: str, scope: str, anchors: list[Anchor]) -> str | None:
    """M5: the first number a frame item types that no anchor binds for its frame (no register-only pass)."""
    plain = re.sub(r"[\d,.:-]+\s*<!-- audit:.*?--!?>", " ", text, flags=re.DOTALL)
    chars = list(plain)
    for _, want, pat in anchors:
        if not want.get(scope, want["*"]):
            continue
        for m in re.finditer(pat, plain):
            chars[m.start() : m.end()] = " " * (m.end() - m.start())
    for val, unit in num_tokens("".join(chars)):
        return f"{val} {unit}".strip() if unit not in ("date", "time") else val
    return None


def norm(v: str) -> str:
    return v.replace(",", "").strip()


def anchor_miss(text: str, scope: str, anchors: list[Anchor]) -> str | None:
    """The first anchored number in `text` that is not its own `--json` value: 'label reads X, not Y'."""
    plain = re.sub(r"[\d,.:-]+\s*<!-- audit:.*?--!?>", " ", text, flags=re.DOTALL)
    for label, want, pat in anchors:
        ok = want.get(scope, want["*"])
        if not ok:
            continue
        for m in re.finditer(pat, plain):
            got = tuple(norm(g) for g in m.groups() if g is not None)
            if got not in ok:
                exp = " / ".join(sorted(" · ".join(o) for o in ok)) or "none here"
                return f"{label} reads {' · '.join(got)}, not the tool's {exp}"
    return None


def item_gate(
    name: str,
    own: str,
    item: str,
    cell: str,
    carry: dict[str, str],
    reg: tuple[set[tuple[str, str]], set[float]],
    anchors: list[Anchor],
) -> str | None:
    """The first violation one item of a frame row carries (priority order), or None. `carry` holds the subjects
    the items before it named (the control, the action, the typed field), read when this item names none first.
    """
    s = short(name)
    x = scrub(item)
    dialog = name.startswith(DIALOG_FAMILIES)
    kinds = ctrl_kinds(dialog)
    if cell != "producer":
        hit = gated_term(x, carry["ctrl"], kinds, True)
        if hit:
            return f"R-14 {s}: exit gated ({hit[0]!r} in {x.strip()[:28]!r})"
        if re.search(EXIT_CANCEL, x) and re.search(r"CAPTION\d+", x):
            return f"R-14 {s}: the exit Cancel captioned PROPOSED"
        if name == "SCR-142/tier-unreachable-questdb":
            term = positive_term(x, PAGE_LEVEL)
            if term:
                return f"R-4 {s}: page-level banner ({term!r})"
        if name == "IMPORT/running-with-skips":
            term = positive_term(x, PAGE_LEVEL)
            if term:
                return f"R-9 {s}: page banner on a skipped file ({term!r})"
            term = positive_term(x, STALL)
            if term:
                return f"R-9 {s}: progress stalled ({term!r})"
        if name == "IMPORT/failed":
            term = positive_term(x, OUTSIDE_CARD)
            if term:
                return f"R-9 {name}: failure outside the card ({term!r})"
        if name == "SCR-142/migration-pending":
            term = positive_term(x, DEFERRED, 0)
            if term:
                return f"R-6 {s}: deferred capability drawn as a control ({term!r})"
        lock_hit = gated_term(x, carry["ctrl"], kinds, False, ("lock",))
        dim_hit = gated_term(x, carry["ctrl"], kinds, False, ("dim",))
        lock = lock_hit[0] if lock_hit else None
        dim = dim_hit[0] if dim_hit else None
        on = ""
        if lock or dim:
            w = list(re.finditer(WRITE_TERM, x))
            on = f" on {w[0].group(0)}" if w else ""
        if own == "R6" and lock:
            return f"R-6 {s}: state drawn as a lock ({lock!r}{on})"
        if own == "R6" and dim:
            return f"R-6 {s}: action gated by state ({dim!r}{on})"
        if own == "R8" and lock in ("CMP-079", "RbacGate"):
            return f"R-8 {name}: RbacGate on validity ({lock!r})"
        if own == "R8" and lock:
            return f"R-8 {name}: lock on a validity control ({lock!r})"
        if own == "R8" and (term := positive_term(x, r"\binside\b")):
            return f"R-8 {name}: the reason {term} the control"
        if own == "R11" and lock:
            return (
                f"R-11 {s}: busy drawn as T2 ({lock!r}{on})"
                if name == "JOB/strip-running"
                else f"R-11 {s}: refusal drawn as a lock ({lock!r}{on})"
            )
        if own == "R11" and dim:
            return (
                f"R-11 {s}: a write gated while a job runs ({dim!r}{on})"
                if name == "JOB/strip-running"
                else f"R-11 {s}: refusal drawn as a disabled control ({dim!r}{on})"
            )
        if own == "R13" and (term := positive_term(x, T2_DIM)):
            return f"R-13 {s}: T2 dimmed ({term!r}{on})"
        if (term := second_purge(x, carry["action"])) is not None:
            return f"R-21 {s}: a second purge shape ({term!r})"
        if (term := fill_term(x, carry["typed"] == "typed")) is not None:
            return f"R-7 {name}: confirm_symbol pre-filled ({term!r})"
        if (issue := order_issue(x)) is not None:
            return f"R-5 {s}: degradation order {issue}"
        if (term := positive_term(x, r"\bconsoles?\b")) is not None:
            return f"R-15 {name}: data-store console linked ({term!r})"
        if (term := positive_term(x, r"\bbackups?\b|\brestore\b")) is not None:
            return f"R-15 {name}: backup control drawn ({term!r})"
        if name == "JOB/strip-running" and positive_term(x, r"\bper tick\b"):
            return f"R-22 {s}: announcement per tick"
        caps = {int(n) for n in re.findall(r"CAPTION(\d+)", x)}
        rest = re.sub(r'"(?:Row counts|Slowest queries)[^"]*"', "", x)
        rest = re.sub(EXIT_CANCEL + (r"|\bCancel\b" if dialog else ""), " ", rest)
        if (m := re.search(r"\bCancel\b", rest)) is not None and not negated(rest, m.start()):
            ctx = rest[m.end() : m.end() + 24].strip()
            return f"R-12 {s}: the job action drawn as 'Cancel {ctx}…' (it is Stop job, D04-G10; Cancel is the exit)"
        for what, pat, ids in CARRIERS:
            for m in re.finditer(pat, rest, re.IGNORECASE):
                if negated(rest, m.start()):
                    continue
                if not caps & ids:
                    return f"R-12 {s}: {m.group(0)} without its caption (D04-G{min(ids)})"
            # a carrier answered by its caption is masked, so a shorter carrier inside it is not read twice
            rest = re.sub(pat, " ", rest, flags=re.IGNORECASE)
        for g in re.findall(r"\bD04-G(\d+)\b", x):
            if int(g) not in caps:
                return f"R-12 {s}: D04-G{g} named without its caption"
    miss = anchor_miss(item, name, anchors)
    if miss is not None:
        return f"R-17 {name}: {miss}"
    return None


def frame_gates(
    spec: str,
    fx: dict[str, Any],
    reg: tuple[set[tuple[str, str]], set[float]],
    anchors: list[Anchor],
) -> tuple[list[str], dict[str, int]]:
    """Every frame row read whole: item by item (the priority order of `item_gate`), each item's subject carried
    across `;` and `·` from Shows into Controls; then the row's presence rules."""
    bad: list[str] = []
    seen: dict[str, int] = {}
    need = required_numbers(fx)
    reasons = {k: v for k, v, _ in deck_rows(spec)}
    for name, c, sec in frame_rows(spec):
        seen[name] = seen.get(name, 0) + 1
        if len(c) < 6:
            bad.append(f"section {sec}: {name} has fewer than six cells")
            continue
        producer, shows, controls, cls = (
            c[COL[k]] for k in ("producer", "shows", "controls", "cls")
        )
        text = shows + " · " + controls
        low = text.lower()
        s = short(name)
        own = owner_of(name, cls)
        dialog = name.startswith(DIALOG_FAMILIES)
        start = (
            "purge"
            if name.startswith("PURGE/")
            else ("other" if name.startswith("JOB/confirm-") else "")
        )
        carry = {"ctrl": "", "action": start, "typed": ""}
        flagged = False
        for kind, cell_text in (("producer", producer), ("shows", shows), ("controls", controls)):
            if kind == "producer":
                carry = {"ctrl": "", "action": start, "typed": ""}
            for it in items(cell_text):
                x = scrub(it)
                msg = item_gate(name, own, it, kind, carry, reg, anchors)
                if msg is None and (hit := shipped_mention(x, dialog, strong=False)):
                    what, term, n = hit
                    msg = f"R-12 {s}: {what} drawn as shipped ({term!r}) without its caption (D04-G{n})"
                if msg:
                    bad.append(msg)
                    flagged = True
                # the next item reads the subject this item named last; an item that names none passes the
                # carried subject on only when it opens on a pronoun (It / They / Each …)
                keep = re.match(PRONOUN_LEAD, x) is not None
                carry = {
                    "ctrl": last_subject(x, carry["ctrl"] if keep else "", ctrl_kinds(dialog)),
                    "action": last_subject(x, carry["action"], ACTION_KINDS),
                    "typed": last_subject(
                        x,
                        carry["typed"] if keep else "",
                        {"typed": TYPED_SUBJ, "other": WRITE_TERM + "|" + EXIT_TERM},
                    ),
                }
        if flagged:
            continue
        # R-5 by sequence across the items of one statement ("Trading halts; recording pauses later.")
        if (issue := sequence_issue(scrub(text))) is not None:
            bad.append(f"R-5 {s}: degradation order {issue}")
            continue
        found = row_presence(
            name, cls, producer, shows, controls, text, low, s, own, fx, need, reasons
        )
        # M5: every number the row types is bound to its own key (read after the presence checks, so a figure
        # stripped of its unit stays R-1's and a meter stripped of its denominator stays R-3's)
        if not found:
            for cell_text in (producer, shows, controls):
                for it in items(cell_text):
                    if (loose := unbound(it, name, anchors)) is not None:
                        found.append(f"R-17 {name}: number not bound to its key ({loose})")
                        break
                if found:
                    break
        bad += found
    for name, n in seen.items():
        if n > 1:
            bad.append(f"spec: frame {name} appears in {n} state rows (one row per frame)")
    return bad, seen


def row_presence(
    name: str,
    cls: str,
    producer: str,
    shows: str,
    controls: str,
    text: str,
    low: str,
    s: str,
    own: str,
    fx: dict[str, Any],
    need: dict[str, list[str]],
    reasons: dict[str, str],
) -> list[str]:
    """What a frame row must carry (each a FAIL when absent); a row with an item violation skips these."""
    bad: list[str] = []
    cl = items(shows) + items(controls)
    # R-2 the sample stamp; the stale form on the stale and the unavailable frames
    if name.startswith("SCR-142/") and name not in NO_STAMP:
        stamp = [x for x in cl if re.search(r"\bSampled \d\d:\d\d:\d\d UTC", x)]
        if not stamp:
            bad.append(f"R-2 {name}: sample timestamp missing")
        elif name in ("SCR-142/stale-sample", "SCR-142/unavailable") and not any(
            re.search(r"\bstale \(\d+ min old\)", x) for x in stamp
        ):
            bad.append(f"R-2 {name}: staleness not shown")
    # R-3 two meters, each naming its denominator
    meters = [x for x in cl if x.lower().startswith("meter ")]
    if name == "SCR-142/healthy" and len(meters) < 2:
        bad.append(f"R-3 {name}: fewer than two meters")
    if len(meters) > 2:
        bad.append(f"R-3 {name}: more than two meters")
    for x in meters:
        if not re.search(r" of [\d,.]+ (?:GB|TB) (?:cap_bytes|disk_total_bytes)\b", x):
            bad.append(f"R-3 {name}: meter without denominator")
    # R-1 / R-4 the tier cards
    if name in TIER_FRAMES:
        starts = {
            p: next((x for x in cl if x.lower().startswith(p)), None)
            for p in ("size ", "projected full", "growth/day", "health ")
        }
        size, proj, growth, health = starts.values()
        if not size or not re.search(UNIT_NUM, size):
            bad.append(f"R-1 {name}: figure without unit")
        if proj is None:
            bad.append(f"R-1 {name}: projected full missing")
        elif not (("—" in proj and "CAPTION1" in scrub(proj)) or re.search(DATE_RE, proj)):
            bad.append(f"R-1 {name}: projected full not produced and not PROPOSED")
        if growth is None:
            bad.append(f"R-1 {name}: growth cell missing")
        elif not (("—" in growth and "CAPTION1" in scrub(growth)) or re.search(UNIT_NUM, growth)):
            bad.append(f"R-1 {name}: growth cell not produced and not PROPOSED")
        if health is None or not re.search(STATE_WORD, health, re.IGNORECASE):
            bad.append(f"R-4 {name}: health by colour alone")
    if name == "SCR-142/tier-unreachable-questdb" and "page usable" not in low:
        bad.append(f"R-4 {s}: page-level error")
    # R-5 the degradation sentence on every level >= 1 frame
    lv = re.search(r"`level` ([0-3])", producer)
    if lv and int(lv.group(1)) >= 1 and not ruled_order(scrub(text)):
        bad.append(f"R-5 {s}: degradation sentence missing")
    # R-6 the BQ-14 sentence on the disk-full frame
    if name == "SCR-142/read-only-disk-full" and BQ14.lower() not in low:
        bad.append(f"R-6 {s}: the BQ-14 sentence missing")
    # R-7 the purge triple
    if name == "PURGE/dialog":
        typed = [x for x in cl if re.search(r"type the symbol to confirm", x, re.IGNORECASE)]
        reason = [x for x in cl if x.lower().startswith("reason")]
        if not typed:
            bad.append(f"R-7 {name}: typed field missing")
        elif "empty" not in typed[0].lower():
            bad.append(f"R-7 {name}: typed field not shown empty")
        if not reason:
            bad.append(f"R-7 {name}: reason missing")
        elif not re.search(r"\brequired\b", reason[0]) or "3–280" not in reason[0]:
            bad.append(f"R-7 {name}: reason not required 3–280")
        before = [x for x in cl if x.startswith("Delete data recorded before")]
        if not before:
            bad.append(f"R-7 {name}: before field missing")
        elif not re.search(r"`before`, required\b", before[0]):
            bad.append(f"R-7 {name}: before field not required")
    if name in ("PURGE/dialog", "PURGE/step-up") and STEPUP not in text:
        bad.append(f"R-7 {name}: elevation not shown")
    if name == "PURGE/dialog" and fx["purge"]["body"] not in text:
        bad.append(f"R-21 {name}: E16-D02 §6.5's body not reused whole")
    # R-8 the validity rows
    if own == "R8":
        if "validity-reason" not in low:
            bad.append(f"R-8 {name}: validity frame without validity-reason")
        if "opacity.disabled" not in low:
            bad.append(f"R-8 {name}: validity frame without opacity.disabled")
        if "under it" not in low:
            bad.append(f"R-8 {name}: the reason not under the control")
    # R-9 / R-10 the import
    if name == "IMPORT/running-with-skips":
        if "keeps moving" not in low:
            bad.append(f"R-9 {s}: progress not continuing")
        if not re.search(r"\bReason\b", shows):
            bad.append(f"R-10 {s}: skip without reason")
        else:
            row_ = re.search(r'"skipped ⚠ / ([a-z_]+) / ([^/"]+?) / ', shows)
            if (
                not row_
                or row_.group(1) not in SKIP_KEYS
                or f'"{row_.group(2)}"' != reasons.get(SKIP_KEYS[row_.group(1)])
            ):
                bad.append(f"R-10 {s}: the skipped row without its code and sentence")
    if name == "IMPORT/failed" and "inside the import card" not in low:
        bad.append(f"R-9 {name}: failure not placed inside the card")
    if name == "IMPORT/summary":
        if "recorded data wins" not in low:
            bad.append(f"R-10 {name}: overlap report missing")
        if "archive-derived" not in low:
            bad.append(f"R-10 {name}: archive-derived label missing")
        if "no book data" not in low:
            bad.append(f"R-10 {name}: book-data caveat missing")
    # R-11 the strip rows
    if own == "R11":
        if "T2" in cls:
            bad.append(
                f"R-11 {s}: busy drawn as T2 (class)"
                if name == "JOB/strip-running"
                else f"R-11 {s}: refusal drawn as a lock (class T2)"
            )
        elif name == "JOB/strip-running":
            if "aria-busy" not in low:
                bad.append(f"R-11 {s}: busy without aria-busy")
            if "busy" not in cls.lower():
                bad.append(f"R-11 {s}: class is not busy")
        elif "T4" not in cls:
            bad.append(f"R-11 {s}: refusal not classed T4")
    # R-13 the view-as frame: T2, the key, one notice, every write by name, the anatomy tokens, the leg first
    if own == "R13":
        notices = [x for x in cl if positive_term(scrub(x), NOTICE)]
        if "T2" not in cls:
            bad.append(f"R-13 {s}: not T2")
        if "lock glyph" not in low:
            bad.append(f"R-13 {s}: T2 without lock")
        if "rbac.view_as" not in text:
            bad.append(f"R-13 {s}: reason key missing")
        if "full label" not in low:
            bad.append(f"R-13 {s}: T2 without full label")
        if len(notices) > 1:
            extra = positive_term(scrub(notices[1]), NOTICE)
            bad.append(f"R-13 {s}: more than one notice ({extra!r})")
        elif not notices:
            bad.append(f"R-13 {s}: no notice")
        for w in VIEW_AS_WRITES:
            if w not in controls:
                bad.append(f"R-13 {s}: a write missing from the T2 list ({w})")
        fill = f"fill `{T2_TOKENS[0]}` + `{T2_TOKENS[1]}` hairline"
        if fill not in controls or any(f"`{t_}`" not in controls for t_ in T2_TOKENS):
            bad.append(f"R-13 {s}: the T2 anatomy tokens changed")
        if "the view-as leg first" not in controls:
            bad.append(f"R-13 {s}: view-as leg not first (frame row)")
    # R-14 the exits each frame lists: present and T1
    for ex in EXITS.get(name, ()):
        hit = [x for x in cl if ex in x]
        if not hit:
            bad.append(f"R-14 {s}: exit missing ({ex})")
        elif not re.search(r"\bT1\b", hit[0]):
            bad.append(f"R-14 {s}: exit not T1 ({ex})")
    # R-21 every purge entry point opens E16-D02 section 6.5 (one shape)
    if name in ("TIER/questdb", "TIER/parquet", "TIER/per-symbol", "PURGE/entry-points"):
        for x in items(controls):
            if (
                re.search(r"Purge data…|\bPurge…", x)
                and not negated(x, x.find("Purge"))
                and "opens E16-D02 §6.5" not in x
            ):
                bad.append(f"R-21 {s}: purge entry point not E16-D02 §6.5's")
    # R-17 the tool's strings each frame repeats
    for needle in need.get(name, []):
        if needle not in text:
            kind = "count" if name.startswith("IMPORT/") else "number"
            bad.append(f"R-17 {s if kind == 'count' else name}: {kind} not the tool's ({needle})")
    # R-20 the E16-D02 outcome copy
    if name == "JOB/outcomes" and COMPACT_FAILED not in text:
        bad.append(f"R-20 {name}: E16-D02 copy altered")
    if name == "PURGE/outcomes" and PURGE_FAILED_TAIL not in text:
        bad.append(f"R-20 {name}: E16-D02 copy altered")
    # R-21 the confirm pattern per action
    if name in ("JOB/confirm-compact", "JOB/confirm-vacuum"):
        if "cmp-044 standard" not in low or NOTHING_DELETED not in text:
            bad.append(f"R-21 {s}: non-destructive confirm without the standard form")
        if any(positive_term(x, r"\btyped\b") for x in cl):
            bad.append(f"R-21 {s}: typed confirm on a non-destructive action")
    if name == "PURGE/dialog" and ("cmp-044 standard" in low or "cmp-044 typed" not in low):
        bad.append(f"R-21 {name}: destructive action without typed confirm")
    # R-22 announcements once
    if name == "JOB/strip-running" and "once" not in low and "one announcement" not in low:
        bad.append(f"R-22 {s}: no announcement policy")
    return bad


def doc_units(spec: str) -> list[tuple[str, str, str]]:
    """Every unit outside the frame tables: (where, kind, text) — a table row, a prose sentence or a sketch line."""
    out: list[tuple[str, str, str]] = []
    sec, sub, fence = "header", "", False
    for ln in spec.split("\n"):
        h = re.match(r"^(#{2,3}) (?:(\d+(?:\.\d+)?)\.? )?(.*)", ln)
        if h:
            if h.group(1) == "##":
                sec = (
                    f"§{h.group(2)}" if h.group(2) else ("AC trace" if "Acceptance" in ln else "BQ")
                )
                sub = ""
            else:
                sub = f"§{h.group(2)}" if h.group(2) else sub
            continue
        where = sub or sec
        if ln.startswith("```"):
            fence = not fence
            continue
        if fence:
            out.append((f"{where} sketch", "sketch", ln))
        elif ln.startswith("| ") and not re.match(r"^\| -", ln):
            if re.match(FRAME_RE, ln):
                continue
            c = cells(ln)
            key = c[0].strip("`*")
            out.append((f"{where} table ({key[:40]})", "row", ln))
        elif ln.strip():
            for sent in re.split(r'(?<=[.!?])\s+(?=[A-Z*(`"])(?=(?:[^"]*"[^"]*")*[^"]*$)', ln):
                if sent.strip():
                    out.append((f"{where} prose", "prose", sent))
    return out


def t2_context(text: str) -> bool:
    """A unit that speaks of the view-as leg, the T2 rule itself or the validity look may name a lock."""
    return bool(
        re.search(
            r"view-as|viewing as|rbac\.|\bvalidity\b|T2 — disabled|E09-D09 §(?:2\.2|3\.1|9\.1|9\.3)|CMP-079"
            r"|\bT2 (?:control|pair|press|grammar|leg|frame|keys)\b|\bon T2\b",
            text,
        )
    )


def sketch_lines(spec: str) -> dict[str, str]:
    """The sketch's footnote markers mapped to the ruled caption each footnote line carries (¹ → CAPTION1)."""
    marks: dict[str, str] = {}
    for m in re.finditer(r"^([¹²³⁴⁵⁶⁷⁸⁹]) (" + CAP_RE + r")", spec, MULTI):
        marks[m.group(1)] = f"CAPTION{m.group(3)}"
    return marks


def doc_gates(
    spec: str,
    fx: dict[str, Any],
    reg: tuple[set[tuple[str, str]], set[float]],
    prior: list[str],
    anchors: list[Anchor],
) -> list[str]:
    """The whole document beyond the frame rows: prose, the non-frame tables, the deck and the sketch. A table row
    is read whole, across its cells; a prose sentence that opens on a pronoun is read with the sentence before it.
    """
    bad: list[str] = []
    r5_in_1 = False
    marks = sketch_lines(spec)
    prev = ("", "", "")
    for where, kind, raw0 in doc_units(spec):
        last, prev = prev, (where, kind, raw0)
        raw = raw0
        if kind == "prose" and last[:2] == (where, kind) and re.match(PRONOUN_LEAD, raw0):
            raw = last[2] + " " + raw0
        if kind == "sketch":
            for k, v in marks.items():
                raw = raw.replace(k, f" {v} ")
        x = scrub(raw)
        key_m = re.match(r"^\| `([^`]+)` +\|", raw) if where.startswith("§14") else None
        if key_m and key_m.group(1) not in DECK_KEYS:
            bad.append(f"R-19 §14: a key outside the closed deck set ({key_m.group(1)})")
            continue
        lead = next((ld for ld, _ in CLASS_MAP if raw.startswith(f"| {ld}")), None)
        if where.startswith("§1.3 table") and lead is not None:
            got = re.search(r"\| \*\*([^*]+)\*\*[^|]*\||\| (not a state of this page) +\|", raw)
            want = dict(CLASS_MAP)[lead]
            have = (got.group(1) or got.group(2)) if got else "none"
            if have != want:
                bad.append(f"R-6 §1.3: {lead[:30]!r} classed {have}, not {want}")
                continue
        msg = unit_gate(where, kind, raw, x, fx, reg, anchors)
        if msg:
            r5_in_1 = r5_in_1 or (msg.startswith("R-5") and where.startswith("§1"))
            bad.append(msg)
    # section 1.4 states the AC 2 sentence in any ruled wording (unless an inversion there was already reported)
    s14 = spec[spec.index("### 1.4") : spec.index("\n## 2.")]
    if not ruled_order(scrub(s14)) and not r5_in_1:
        bad.append("R-5 §1.4: the AC 2 sentence missing")
    # section 1.3's classification: each row's class fixed by its lead; the view-as row first
    s1 = section(spec, 1, 2)
    rows_ = [
        ln[2:]
        for ln in s1.splitlines()
        if ln.startswith("| ") and any(ln.startswith(f"| {ld}") for ld, _ in CLASS_MAP)
    ]
    for lead, _ in CLASS_MAP:
        if not any(r.startswith(lead) for r in rows_):
            bad.append(f"R-6 §1.3: the classification row {lead[:30]!r} missing")
    if not rows_ or not rows_[0].startswith(CLASS_MAP[0][0]):
        bad.append("R-13 §1.3: view-as leg not first")
    roles = re.findall(r"^\| ((?:Owner|Manager)[^|]*?) +\|", section(spec, 9, 10), MULTI)
    if not roles or "viewing as" not in roles[0]:
        bad.append("R-13 §9: view-as leg not first")
    # section 6's action table: compact and vacuum non-destructive and standard, purge typed
    for ln in section(spec, 6, 7).splitlines():
        c = cells(ln) if ln.startswith("| ") else []
        if len(c) < 4 or c[0] not in (
            "Compact Parquet",
            "Vacuum Postgres",
            "Purge data",
            "Import archives",
        ):
            continue
        if c[0] in ("Compact Parquet", "Vacuum Postgres"):
            if NOTHING_DELETED not in c[3] or "CMP-044 standard" not in c[3]:
                bad.append(f"R-21 §6 table: {c[0]} confirm without 'Nothing is deleted.'")
            if not c[2].startswith("no"):
                bad.append(f"R-21 §6 table: {c[0]} drawn destructive")
        elif c[0] == "Purge data" and ("typed dialog" not in c[3] or "yes" not in c[2]):
            bad.append("R-21 §6 table: purge without E16-D02's typed dialog")
    # the deck's ruled strings, byte for byte
    deck = {k: v for k, v, _ in deck_rows(spec)}
    src = {k: v for k, _, v in deck_rows(spec)}
    for key, want in (
        ("storage.degradation", f'"{DEGRADATION}"'),
        ("storage.degradation.detail", f'"{fx["degradation_detail"]}"'),
        ("rbac.view_as", f'"{VIEW_AS}"'),
    ):
        if key not in deck:
            bad.append(f"spec section 14: {key} is not in the copy deck")
        elif deck[key] != want and not any(key in b for b in prior + bad):
            rule = "R-19" if key.startswith("rbac") else "R-5"
            bad.append(f"{rule} §14: {key} is not the ruled string")
    for key in ("storage.compact.body", "storage.vacuum.body"):
        if NOTHING_DELETED not in deck.get(key, ""):
            bad.append(f"R-21 §14: {key} without 'Nothing is deleted.'")
    # the job action and the exit never share a label: Stop job carries PROPOSED, Cancel never does
    if deck.get("storage.job.stop") != '"Stop job"' and not any("storage.job" in b for b in bad):
        bad.append("R-12 §14: the PROPOSED job action is not labelled Stop job")
    if "PROPOSED" in src.get("storage.confirm.cancel", "") and not any(
        "confirm.cancel" in b for b in bad
    ):
        bad.append("R-14 §14: the exit Cancel captioned PROPOSED (storage.confirm.cancel)")
    return bad


def unit_gate(
    where: str,
    kind: str,
    raw: str,
    x: str,
    fx: dict[str, Any],
    reg: tuple[set[tuple[str, str]], set[float]],
    anchors: list[Anchor],
) -> str | None:
    """The first violation one document unit carries (priority order), or None."""
    gap_row = re.match(GAP_ROW, raw) is not None
    if kind == "sketch":
        if re.search(r"\bPROPOSED\b", x):
            return f"R-12 {where}: a short PROPOSED form (the full caption, or its footnote)"
        for what, pat, ids in CARRIERS:
            for m in re.finditer(pat, x, re.IGNORECASE):
                if (
                    not negated(x, m.start())
                    and not {int(n) for n in re.findall(r"CAPTION(\d+)", x)} & ids
                ):
                    return f"R-12 {where}: {what} without its caption ({m.group(0)!r}, D04-G{min(ids)})"
            x = re.sub(pat, " ", x, flags=re.IGNORECASE)
        if re.search(r"\(g\) Maintenance", raw) and positive_term(raw, PURGE_SUBJ, 0):
            return f"R-21 {where}: Purge data… on the maintenance card (the entry points are the tier cards)"
    deck_str = (cells(x) + ["", ""])[1].replace(CAPTION, "")
    if where.startswith("§14 table") and re.search(r"\bPROPOSED\b", deck_str):
        return f"R-12 {where}: a short PROPOSED form in a deck string (the full caption)"
    if where.startswith("§2 table ((g))") and positive_term(raw, PURGE_SUBJ, 0):
        return "R-21 §2 table ((g)): Purge data… on the maintenance card (the entry points are the tier cards)"
    rule_row = where.startswith(
        "§12 table (R-"
    )  # the rule table names the forbidden forms by design
    hit = None if gap_row or rule_row else shipped_mention(x, whole=kind == "row")
    if hit is not None:
        what, shown, n = hit
        return (
            f"R-12 {where}: {what} presented as shipped ({shown!r}) without its caption (D04-G{n})"
        )
    if where.startswith(("§12", "§15")):
        return None  # the rule table and the measured matrix name the forbidden forms by design
    if (issue := order_issue(x)) is not None:
        return f"R-5 {where}: degradation order {issue}"
    if (term := second_purge(x, "")) is not None:
        return f"R-21 {where}: a second purge shape ({term!r})"
    if (term := fill_term(x, False)) is not None:
        return f"R-7 {where}: typed field pre-filled ({term!r})"
    if not t2_context(raw):
        ctrl = ctrl_kinds(False)
        hit2 = gated_term(x, "", ctrl, True) or gated_term(x, "", ctrl, False)
        if hit2:
            return f"R-6 {where}: a state or write drawn as a lock ({hit2[0]!r})"
    else:
        hit2 = gated_term(x, "", ctrl_kinds(False), True)
        if hit2:
            return f"R-14 {where}: an exit drawn locked ({hit2[0]!r})"
    if where.startswith("§8 prose") and (term := positive_term(x, PAGE_LEVEL)):
        return f"R-9 {where}: page banner on a skipped file ({term!r})"
    if (miss := anchor_miss(raw, "*", anchors)) is not None:
        return f"R-17 {where}: {miss}"
    if (term := unregistered(raw, reg)) is not None:
        return f"R-17 {where}: number not the tool's ({term})"
    return None


# R-16: the PENDING siblings in any spelling (the PR number, the boards by name), then a sha in any form (hex with a
# letter, a code span of 7-40 hex digits, "at" and 7+ digits) or a line cite
SIBLING = (
    r"(?:#|\bPR\s*|\bpulls?/|\bpull request\s*|\b)(?:4463|4501)\b"
    r"|\bE16-D0[35](?:'s)? boards(?: PR)?\b"
)
SHA_OR_LINE = (
    r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b|`[0-9a-f]{7,40}`|\bat\s+\d{7,40}\b|(?<![\d:]):\d{2,}"
)


def gates(
    files: list[Path],
    spec: str,
    facts: dict[str, Any],
    fx: dict[str, Any],
    t: dict[str, str],
    numbers: dict[str, Any],
) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    reg = registry(numbers)
    anchors = anchor_table(
        fx,
        facts,
        {"opacity": numbers["opacity_disabled"], "http_codes": numbers["context"]["http_codes"]},
    )
    fb, seen = frame_gates(spec, fx, reg, anchors)
    bad += fb
    # R-18 the inventory: every frame section 0 names is a row; the twins are rows
    s0 = section(spec, 0, 1)
    for named in sorted(set(re.findall(r"`((?:SCR-142|TIER|JOB|PURGE|IMPORT)/[a-z0-9-]+)`", s0))):
        if named not in seen:
            bad.append(f"R-18: frame named in §0 missing from its table ({named})")
    for tw in TWINS:
        if tw not in seen:
            bad.append(f"R-18: light twin {tw} is not a frame row")
    # R-16 the PENDING siblings by name only: any spelling of the number, then a sha or a line cite
    for m in re.finditer(SIBLING, spec):
        after = spec[m.end() : m.end() + 80].split("\n")[0]
        if re.search(SHA_OR_LINE, after):
            pin = re.search(SHA_OR_LINE, after)
            bad.append(
                f"R-16: unmerged sibling pinned ({m.group(0).strip()} at {pin.group(0) if pin else '?'})"
            )
            break
    # R-19 the rbac sentences in the deck
    deck = section(spec, 14, 15)
    r19: list[str] = []
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        for q in re.findall(r'"([^"]+)"', cell):
            if len(q) > LAYOUT["reason_max"]:
                r19.append(f"R-19 §14: rbac sentence over 60 chars ({key})")
            elif not q.endswith("."):
                r19.append(f"R-19 §14: rbac sentence without a full stop ({key})")
            elif re.search(r"\d|[A-Z]{3,}USDT", q):
                r19.append(f"R-19 §14: reason names data ({key})")
    bad += r19
    bad += doc_gates(spec, fx, reg, r19, anchors)
    if NOTICE_D16 not in deck:
        bad.append("spec section 14: the D-16 notice is not in the copy deck")
    strings = [s for _, s, _ in deck_rows(spec)]
    for p in BANNED_COPY:
        for s_ in strings:
            if re.search(p, s_):
                bad.append(f"spec section 14: jargon in user copy: {p!r} in {s_[:40]!r}")
                break
    # the bindings table: every row names a unit
    for ln in section(spec, 3, 4).splitlines():
        if ln.startswith("| ") and not ln.startswith("| UI element") and not re.match(r"^\| -", ln):
            c = cells(ln)
            if len(c) >= 3 and not c[2].strip():
                bad.append(f"spec section 3: binding row without a unit ({strip_md(c[0])[:32]})")
    # the cited lines
    lines = {k: v.split("\n") for k, v in t.items()}
    CITE_WARN.clear()
    for doc, line_s, want in rows(CITED_TABLE, 2):
        line = int(line_s)
        shift = sum(POINTER in ln for ln in lines[doc][: line - 1]) if doc == "14" else 0
        found = [i + 1 for i, ln in enumerate(lines[doc]) if want in ln]
        total = sum(ln.count(want) for ln in lines[doc])
        if total == 0:
            bad.append(f"cited text gone: `{doc}` :{line} {want[:40]!r} (nowhere in the file)")
        elif total > 1:
            bad.append(
                f"cited text ambiguous: `{doc}` :{line} {want[:40]!r} ({total} matches: use a longer needle)"
            )
        elif found[0] not in (line, line + shift):
            CITE_WARN.append(f"`{doc}` :{line} now at :{found[0]} ({want[:40]!r})")
    # hygiene, ids, closing keywords
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for cid in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {cid} " not in t["15" if cid.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {cid}")
        for word in (
            "close",
            "closes",
            "closed",
            "fix",
            "fixes",
            "fixed",
            "resolve",
            "resolves",
            "resolved",
        ):
            if re.search(rf"\b{word}\b\s+#\d+", txt, re.IGNORECASE):
                bad.append(f"{f.name}: closing keyword before an issue number (text-first PR)")
    # the contract facts the spec assumes
    expect = {
        "storage_fields": 13,
        "job_status": 5,
        "level_enum": 4,
        "tier_enum": 3,
        "component_state": 5,
    }
    for k, n in expect.items():
        if len(facts[k]) != n:
            bad.append(f"`22`: {k} has {len(facts[k])} values, the spec assumes {n}")
    for k in (
        "no_vacuum_kind",
        "no_cancel_route",
        "no_vacuum_route",
        "no_import_result_schema",
        "no_ddl",
        "precedence",
        "projection_rule",
        "sr_048",
        "e16d03_boundary",
        "e25_rule",
        "readiness_migrations",
        "checksum_code",
        "scr143_db_row",
        "admin_rule",
        "rule4",
        "rule5",
        "rule6",
        "ws_no_lag_field",
    ):
        if not facts[k]:
            bad.append(f"contract fact gone: {k}")
    for group in (
        "import_sentences",
        "purge_sentences",
        "compact_sentences",
        "us_rec_007",
        "cmp",
        "e09",
        "e16d02",
        "scr142",
    ):
        for k, v in facts[group].items():
            if v is False or v == "MISSING" or v == 0 or v == []:
                bad.append(f"contract fact gone: {group}.{k}")
    if facts["health_components"][:3] != ["postgres", "questdb", "parquet_store"]:
        bad.append(
            "`22` health example: the three tier components are not postgres / questdb / parquet_store"
        )
    if facts["e09"]["view_as"] != VIEW_AS:
        bad.append("E09-D09: the rbac.view_as string changed")
    shared = facts["e30"]["shared"].split(". ", 1)[1]
    if shared not in section(spec, 13, 14):
        bad.append("spec section 13: the shared gap sentence is not E30-D04 §30's")
    if (
        facts["scr142"]["checklist_boxes"] != 6
        or len(facts["scr142"]["components"]) != 6
        or len(facts["scr142"]["states"]) != 4
    ):
        bad.append("`14` SCR-142: the checklist, components or states changed")
    if not all(facts["cmp_headings"].values()):
        bad.append("`15`: a component heading the spec uses is gone")
    return bad


# --- R-23 the whole document, pinned default-deny (the orchestrator's gate re-check 3) ------------
# The vocabulary gates above are the first line; this is the backstop. A unit is a Markdown block of
# the spec: a heading line, or a run of consecutive non-blank lines (each paragraph, list block and
# table block, the deck's table included), and the fenced sketch whole; a soft-wrapped line belongs
# to its block, so a new line under a pinned paragraph changes that block. A unit is keyed by its
# region (the heading path, each heading by its section id, plus its occurrence `#n`) and its index
# in the region; every line is whitespace-normalised, except the fenced sketch's, pinned verbatim
# (its columns are content; trailing spaces aside). EVERY unit is pinned in RULED_PIN_TXT (key,
# kind, exact text): a changed, moved, duplicated or missing unit, a unit the pins do not hold and a
# region the pins do not hold (a new or repeated heading) FAIL R-23 naming the location, so a new or
# edited unit anywhere fails until `--repin-ruled` (a deliberate act, read in the diff); `--check`
# never re-pins. Exempt by name (PIN_EXEMPT) are only the spans with their own exact gate. Precedence:
# a pin FAIL is reported only when no other gate FAILs; beside another gate's FAIL it is counted on a
# NOTE line, so one wrong form yields one FAIL.
PIN_SEP = " ‖ "
PIN_WIDTH = 96
PIN_KINDS = ("heading", "paragraph", "list", "table", "sketch")
# the exemptions, by name, each with the exact gate that holds it instead of the pin
PIN_EXEMPT = (
    (
        "audit markers",
        (
            "every `N <!-- audit:key=N -->` span (a number bound to a `--json` key, §12's markers"
            " among them) is read as ⟦audit:key⟧: `--check` re-derives the key's value and reads"
            " the number printed before the marker"
        ),
    ),
)
# held by the pin, not exempt: no exact gate of their own reads them whole
PIN_NOT_EXEMPT = (
    "§12's R-rows (no gate reads the rule table)",
    "§15's matrix (the matrix gate reads the three ratios, not the row)",
    "the caption carriers (R-12 reads the caption, not the rest of the unit)",
)
MARKER_RE = r"(\S+) <!-- audit:([a-z0-9_.-]+)=([^ ]+) --!?>"
NUM_WORDS = {
    w: i
    for i, w in enumerate(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        )
    )
}
PinUnit = tuple[str, str, str]  # (key "region#n ¶k", kind, text: normalised lines joined by "\n")
PIN_BESIDE: list[str] = []


def printed_before(spec: str) -> list[str]:
    """The number printed before each `audit:` marker equals the marker's value (the exemption's gate)."""
    bad: list[str] = []
    for m in re.finditer(MARKER_RE, spec, re.DOTALL):
        shown, key, val = m.group(1).lstrip("(~"), m.group(2), m.group(3)
        num: float | None = NUM_WORDS.get(shown.lower())
        if num is None:
            try:
                num = float(shown.replace(",", ""))
            except ValueError:
                num = None
        try:
            same = num == float(val) if num is not None else shown == val
        except ValueError:
            same = shown == val
        if not same:
            bad.append(f"marker audit:{key}={val}: the number printed before it reads {shown!r}")
    return bad


def heading_id(ln: str) -> tuple[int, str]:
    """A heading's level and section id (`§1.3`; the unnumbered ones by name)."""
    h = re.match(r"^(#{1,6}) (?:(\d+(?:\.\d+)*)\.? )?(.*)", ln)
    if h is None:
        return 0, ""
    level = len(h.group(1))
    if level == 1:
        return level, "header"
    if h.group(2):
        return level, f"§{h.group(2)}"
    return level, "AC trace" if "Acceptance" in ln else ("BQ" if "BQ-1" in ln else h.group(3)[:24])


def mask(text: str) -> str:
    """The exempt spans (PIN_EXEMPT) read as their names."""

    def read(m: re.Match[str]) -> str:
        shown = m.group(1)  # only the number is masked: a leading `(` / `~` stays pinned
        return f"{shown[: len(shown) - len(shown.lstrip('(~'))]}⟦audit:{m.group(2)}⟧"

    return re.sub(MARKER_RE, read, text, flags=re.DOTALL)


def ruled_units(spec: str) -> list[PinUnit]:
    """Every unit of the spec (see the block comment) as (key, kind, text), in document order."""
    out: list[PinUnit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k = "header#1", 0
    block: list[str] = []
    fence = False

    def flush(kind: str = "") -> None:
        nonlocal k
        if not block:
            return
        first = block[0]
        if not kind:
            if all(x.startswith("|") for x in block):
                kind = "table"
            elif re.match(r"^(?:[-*+] |\d+\. )", first):
                kind = "list"
            else:
                kind = "paragraph"
        k += 1
        out.append((f"{region} ¶{k}", kind, mask("\n".join(block))))
        block.clear()

    for raw in spec.split("\n"):
        ln = " ".join(raw.split())
        if fence:
            block.append(raw.rstrip())  # the sketch's columns are content: verbatim, trailing aside
            if raw.startswith("```"):
                fence = False
                flush("sketch")
            continue
        if raw.startswith("```"):
            flush()
            fence = True
            block.append(ln)
            continue
        level, sid = heading_id(raw)
        if level:
            flush()
            path = [p for p in path if 1 < p[0] < level] + [(level, sid)]
            name = " › ".join(p[1] for p in path)
            seen[name] = seen.get(name, 0) + 1
            region, k = f"{name}#{seen[name]}", 0
            block.append(ln)
            flush("heading")
            continue
        if not ln:
            flush()
            continue
        block.append(ln)
    flush("sketch" if fence else "")
    return out


def render_pins(spec: str) -> str:
    """RULED_PIN_TXT as `--repin-ruled` writes it: an `@ key ‖ kind` line per unit, then each of its
    lines wrapped at spaces only, the first part indented two spaces and a continuation three."""
    lines: list[str] = []
    for key, kind, text in ruled_units(spec):
        lines.append(f"@ {key}{PIN_SEP}{kind}")
        for ln in text.split("\n"):
            if kind == "sketch":  # verbatim: no wrap, no collapse; a line never opens on a space
                if ln.startswith(" "):
                    raise SystemExit(f"repin: a sketch line opens on a space ({key})")
                lines.append("  " + ln if ln else "  ⏎")
                continue
            parts = textwrap.wrap(ln, PIN_WIDTH, break_long_words=False, break_on_hyphens=False)
            if " ".join(parts) != ln:
                raise SystemExit(f"repin: a line does not survive the wrap ({key})")
            lines += ["  " + parts[0], *("   " + p for p in parts[1:])] if parts else ["  ⏎"]
    return "\n".join(lines)


def pin_rows(table: str) -> list[PinUnit]:
    """RULED_PIN_TXT parsed: (key, kind, text) in document order."""
    rows: list[PinUnit] = []
    key, kind = "", ""
    body: list[str] = []
    for line in [*table.split("\n"), "@ end"]:
        if line.startswith("@ "):
            if key:
                rows.append((key, kind, "\n".join(body)))
            body = []
            key, _, kind = line[2:].partition(PIN_SEP)
        elif line.startswith("   ") and body:
            body[-1] += " " + line[3:]
        elif line.startswith("  "):
            body.append("" if line == "  ⏎" else line[2:])
    return rows


def clip(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def delta(was: str, now: str) -> str:
    """The changed span of a pinned line: its common head and tail cut, 16 characters of context."""
    i = 0
    while i < min(len(was), len(now)) and was[i] == now[i]:
        i += 1
    j = 0
    while j < min(len(was), len(now)) - i and was[-1 - j] == now[-1 - j]:
        j += 1
    lead = max(0, i - 16)

    def span(x: str) -> str:
        core = x[lead : len(x) - j]
        tail = "…" if j and len(core) <= 60 else ""
        return ("…" if lead else "") + clip(core, 60) + tail

    return f"{span(was)!r} is now {span(now)!r}"


def where_of(key: str) -> str:
    """A unit key's section id (the deepest heading of its region)."""
    return key.split(" ¶")[0].rsplit("#", 1)[0].split(" › ")[-1]


def show_at(key: str, kind: str, line: str) -> str:
    """The location a FAIL names: the section id and the unit's kind, a table by its row."""
    where = where_of(key)
    if kind == "table":
        frame = re.match(FRAME_RE, line)
        if frame:
            return f"{where} frame {frame.group(1)}"
        return f"{where} row {' '.join(cells(line)[0].strip('`* ').split())[:40]}"
    return f"{where} {'prose' if kind in ('paragraph', 'list') else kind}"


def changed(key: str, kind: str, was: str, now: str) -> str:
    """One FAIL for a changed unit, naming its first changed line and how the lines changed."""
    a, b = was.split("\n"), now.split("\n")
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    tag, i1, _i2, j1, _j2 = next(o for o in ops if o[0] != "equal")
    edits = [o for o in ops if o[0] != "equal"]
    if sorted(a) == sorted(b):
        how, at, what = "lines reordered", b[j1], repr(clip(b[j1]))
    elif len(edits) == 1 and tag == "insert":
        dup = b[j1] in a
        how, at, what = ("a line duplicated" if dup else "a line added"), b[j1], repr(clip(b[j1]))
    elif len(edits) == 1 and tag == "delete":
        how, at, what = "a line removed", a[i1], repr(clip(a[i1]))
    else:
        new = b[j1] if j1 < len(b) else a[i1]
        how, at, what = "a line edited", new, delta(a[i1] if i1 < len(a) else "", new)
    return f"R-23 {show_at(key, kind, at)}: a pinned unit changed ({kind}, {how}): {what}"


def pin_gate(spec: str, table: str) -> list[str]:
    """R-23: every unit of the spec equals its pin, by region, place and exact text (block comment)."""
    pins, now = pin_rows(table), ruled_units(spec)
    bad: list[str] = []

    def regions(units: list[PinUnit]) -> dict[str, list[PinUnit]]:
        out: dict[str, list[PinUnit]] = {}
        for u in units:
            out.setdefault(u[0].split(" ¶")[0], []).append(u)
        return out

    keys = [u[0] for u in now]
    for key in sorted({x for x in keys if keys.count(x) > 1}):
        bad.append(f"R-23 {key}: a duplicate location")
    rp, rn = regions(pins), regions(now)
    adds: list[PinUnit] = []
    drops: list[PinUnit] = []
    for name, units in rn.items():
        if name not in rp:
            continue
        a, b = rp[name], units
        sm = difflib.SequenceMatcher(None, [u[2] for u in a], [u[2] for u in b], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace":
                ptext, (nk, nkind, ntext) = a[i1][2], b[j1]
                msg = changed(nk, nkind, ptext, ntext)
                if (i2 - i1, j2 - j1) != (1, 1):
                    msg = msg.replace(
                        ": a pinned unit changed (",
                        f": units split or merged ({i2 - i1} → {j2 - j1}; ",
                        1,
                    )
                bad.append(msg)
            elif tag == "insert":
                adds += b[j1:j2]
            elif tag == "delete":
                drops += a[i1:i2]
    pinned_texts = {u[2] for u in pins}
    for key, kind, text in adds:
        at = show_at(key, kind, text.split("\n")[0])
        away = next((d for d in drops if d[2] == text), None)
        if away is not None:
            drops.remove(away)
            if away[0].split(" ¶")[0] == key.split(" ¶")[0]:
                bad.append(
                    f"R-23 {at}: a pinned unit moved out of its pinned order: {clip(text)!r}"
                )
            else:
                was = show_at(away[0], away[1], text.split("\n")[0])
                bad.append(f"R-23 {at}: a pinned unit moved here from {was}: {clip(text)!r}")
        elif text in pinned_texts:
            bad.append(f"R-23 {at}: a pinned unit duplicated ({kind}): {clip(text)!r}")
        else:
            bad.append(f"R-23 {at}: a unit the pins do not hold ({kind}): {clip(text)!r}")
    for key, kind, text in drops:
        at = show_at(key, kind, text.split("\n")[0])
        bad.append(f"R-23 {at}: a pinned unit is missing ({kind}): {clip(text)!r}")
    gone = [r for r in rp if r not in rn]
    for name in [r for r in rn if r not in rp]:
        body = [u[2] for u in rn[name][1:]]
        twin = next((g for g in gone if [u[2] for u in rp[g][1:]] == body), None)
        head = rn[name][0][2]
        if twin is not None:
            gone.remove(twin)
            bad.append(f"R-23 {name}: a heading changed: {delta(rp[twin][0][2], head)}")
        elif not name.endswith("#1"):
            bad.append(
                f"R-23 {name}: a heading repeated, a region the pins do not hold: {clip(head)!r}"
            )
        else:
            bad.append(f"R-23 {name}: a region the pins do not hold: {clip(head)!r}")
    for name in gone:
        bad.append(f"R-23 {name}: a pinned region is missing: {clip(rp[name][0][2])!r}")
    if not bad and [u[0] for u in now] != [u[0] for u in pins]:
        first = next(r for r, p in zip(rn, rp, strict=False) if r != p)
        bad.append(f"R-23 {first}: a region moved out of its pinned order")
    return bad


def pin_counts(table: str) -> dict[str, int]:
    """The pinned units per kind and in all, and the exemptions."""
    rows = pin_rows(table)
    out = {c: sum(r[1] == c for r in rows) for c in PIN_KINDS}
    out["total"] = len(rows)
    out["masked"] = sum(r[2].count("⟦audit:") for r in rows)
    out["exempt"] = len(PIN_EXEMPT)
    return out


def repin(spec: str) -> int:
    """`--repin-ruled`: write RULED_PIN_TXT into this file from the current spec."""
    me = Path(__file__)
    src = me.read_text(encoding="utf-8")
    block = re.search(r'^RULED_PIN_TXT = r"""\n.*?^"""\n', src, re.DOTALL | MULTI)
    if block is None:
        raise SystemExit("repin: the RULED_PIN_TXT block is not found")
    table = render_pins(spec)
    if '"""' in table or table.endswith("\\"):
        raise SystemExit("repin: a unit cannot sit in the raw string")
    text = f'RULED_PIN_TXT = r"""\n{table}\n"""\n'
    me.write_text(src[: block.start()] + text + src[block.end() :], encoding="utf-8", newline="\n")
    counts = pin_counts(table)
    print(f"RULED_PIN_TXT rewritten: {counts['total']} units; " + json.dumps(counts))
    return 0


def _row_edit(spec: str, frame: str, col: int, fn: Callable[[str], str]) -> str:
    out, done = [], False
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
    return "\n".join(
        ln for ln in spec.split("\n") if not re.match(rf"^\| `{re.escape(frame)}` +\|", ln)
    )


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
            if old not in ln:
                raise SystemExit(f"mutation target not found: {key} / {old}")
            ln, done = ln.replace(old, new), True
        out.append(ln)
    return "\n".join(out)


def _first(spec: str, old: str, new: str) -> str:
    if old not in spec:
        raise SystemExit(f"mutation target not found: {old[:60]}")
    return spec.replace(old, new, 1)


def _sketch_shift(spec: str, col: int) -> str:
    """The sketch's second `[ Purge data… ]` line, its box moved to column `col` by spaces alone."""
    old = "|" + " " * 28 + "[ Purge data… ]"
    line = next(x for x in spec.split("\n") if x.startswith(old))
    inner = line[1:-1]
    return _first(spec, line, "|" + (" " * col + inner.strip()).ljust(len(inner)) + "|")


def _counts(spec: str, **marks: tuple[int, int]) -> str:
    """Rewrite count markers (the visible number and the marker together): key=(old, new)."""
    for key, (a, b) in marks.items():
        old = f"{a} <!-- audit:{key}={a} -->"
        if old not in spec:
            raise SystemExit(f"mutation target not found: {old}")
        spec = spec.replace(old, f"{b} <!-- audit:{key}={b} -->")
    return spec


def _sub(frame: str, col: int, old: str, new: str) -> Callable[[str], str]:
    """Replace `old` by `new` once in one cell of a frame row (the cell must contain it)."""

    def fn(c: str) -> str:
        if old not in c:
            raise SystemExit(f"mutation target not found: {frame} col {col} / {old[:50]}")
        return c.replace(old, new, 1)

    return lambda s: _row_edit(s, frame, col, fn)


def _append(frame: str, col: int, text: str) -> Callable[[str], str]:
    """Append `text` to one cell of a frame row as its own clause."""
    return lambda s: _row_edit(s, frame, col, lambda c: f"{c}; {text}")


def _line_sub(spec: str, start: str, old: str, new: str) -> str:
    """Replace `old` by `new` once in the first line that starts with `start` (a non-frame table row)."""
    lines = spec.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(start):
            if old not in ln:
                raise SystemExit(f"mutation target not found: {start[:40]} / {old[:40]}")
            lines[i] = ln.replace(old, new, 1)
            return "\n".join(lines)
    raise SystemExit(f"mutation target not found: {start[:60]}")


def _deck_add(spec: str, after: str, row: str) -> str:
    """Insert a deck row after the row of key `after`."""
    lines = spec.split("\n")
    i = next((i for i, ln in enumerate(lines) if ln.startswith(f"| `{after}`")), None)
    if i is None:
        raise SystemExit(f"mutation target not found: {after}")
    lines.insert(i + 1, row)
    return "\n".join(lines)


def _dot(frame: str, col: int, text: str) -> Callable[[str], str]:
    """Append `text` to one cell of a frame row as its own ` · ` item."""
    return lambda s: _row_edit(s, frame, col, lambda c: f"{c} · {text}")


def cap(n: int) -> str:
    return CAPTION.format(n=n)


STOP_ITEM = f"Stop job per job line, {cap(10)}: today a started job runs to its end"


def _para_add(start: str, text: str) -> Callable[[str], str]:
    """Append `text` as one more sentence to the prose line that starts with `start`."""

    def fn(spec: str) -> str:
        lines = spec.split("\n")
        i = next((i for i, ln in enumerate(lines) if ln.startswith(start)), None)
        if i is None:
            raise SystemExit(f"mutation target not found: {start[:60]}")
        lines[i] = f"{lines[i]} {text}"
        return "\n".join(lines)

    return fn


def _line_at(spec: str, start: str) -> tuple[list[str], int]:
    """The spec's lines and the index of the first line that starts with `start`."""
    lines = spec.split("\n")
    i = next((i for i, ln in enumerate(lines) if ln.startswith(start)), None)
    if i is None:
        raise SystemExit(f"mutation target not found: {start[:60]}")
    return lines, i


def _move_line(start: str, before: str) -> Callable[[str], str]:
    """Move the line that starts with `start` to stand before the line that starts with `before`."""

    def fn(spec: str) -> str:
        lines, i = _line_at(spec, start)
        line = lines.pop(i)
        j = _line_at("\n".join(lines), before)[1]
        lines.insert(j, line)
        return "\n".join(lines)

    return fn


def _dup_line(start: str) -> Callable[[str], str]:
    """A second copy of the line that starts with `start`, right below it."""

    def fn(spec: str) -> str:
        lines, i = _line_at(spec, start)
        lines.insert(i + 1, lines[i])
        return "\n".join(lines)

    return fn


def _del_line(start: str) -> Callable[[str], str]:
    """The line that starts with `start` deleted."""

    def fn(spec: str) -> str:
        lines, i = _line_at(spec, start)
        lines.pop(i)
        return "\n".join(lines)

    return fn


def _new_para(before: str, text: str) -> Callable[[str], str]:
    """`text` as a paragraph of its own, before the line that starts with `before`."""

    def fn(spec: str) -> str:
        lines, i = _line_at(spec, before)
        lines[i:i] = [text, ""]
        return "\n".join(lines)

    return fn


def _soft_wrap(start: str, text: str) -> Callable[[str], str]:
    """`text` as a soft-wrapped line right under the line that starts with `start` (the same block)."""

    def fn(spec: str) -> str:
        lines, i = _line_at(spec, start)
        lines.insert(i + 1, text)
        return "\n".join(lines)

    return fn


SH, CT, CL = COL["shows"], COL["controls"], COL["cls"]
# (description, mutation, the expected FAIL's prefix — the mutation's ONLY FAIL; every message distinct).
# M01-M50: the first-commit forms; A01-A60: the pre-PR design-review lens round 1's probes; O01-O22: this fold's
# own variants (spellings, carriers, tables and prose the lens did not try); P01-P12: a PROPOSED item presented as
# shipped outside a frame's Shows / Controls (prose, the non-frame tables, the deck, the sketch, a Producer cell).
Mutation = tuple[str, Callable[[str], str], str]
ROD, TUQ, VAS = "SCR-142/read-only-disk-full", "SCR-142/tier-unreachable-questdb", "SCR-142/view-as"
SKP, SRN, PDL = "IMPORT/running-with-skips", "JOB/strip-running", "PURGE/dialog"
P11 = "SCR-142 is where the Owner sees"
P04, P05, P06 = (
    "The three cards are the AC 1 surface",
    "The ticket's five states",
    "**Who may run them:**",
)
P07, P08 = (
    "Purge is the one destructive action here",
    "`importTradeArchive` (`22` :14975–15028) imports",
)
P14, PEND = "The ladder is the server's", "E16-D06 and E16-D07 are PENDING by name;"
PDV, EXITS_T1 = "PURGE/dialog-validity", "exits Cancel, Esc and the close ✕ (T1)"
LINKS_T1 = "links to SCR-140, SCR-141 and SCR-143 enabled (T1)"
CCF, CVF, PEP, LDW = (
    "JOB/confirm-compact",
    "JOB/confirm-vacuum",
    "PURGE/entry-points",
    "SCR-142/low-disk-warning",
)
G_REGION = 'CMP-001 secondary "Compact Parquet…"; "Vacuum Postgres…" only as the captioned PROPOSED inset (D04-G8)'
MUTATIONS: list[Mutation] = [
    (
        "M01 TIER/questdb: the Size cell's unit removed",
        _sub("TIER/questdb", SH, "Size 640.0 GB", "Size 640.0"),
        "R-1 TIER/questdb: figure without unit",
    ),
    (
        "M02 TIER/parquet: the Projected full clause removed",
        _sub(
            "TIER/parquet",
            SH,
            f" · Projected full — ({cap(1)}, shipped fallback beside it: all tiers 2028-03-27)",
            "",
        ),
        "R-1 TIER/parquet: projected full missing",
    ),
    (
        "M03 TIER/postgres: the Growth cell replaced by n/a without PROPOSED",
        _sub(
            "TIER/postgres",
            SH,
            f"Growth/day — ({cap(1)}, shipped fallback beside it: all tiers 1.45 GB/day)",
            "Growth/day n/a",
        ),
        "R-1 TIER/postgres: growth cell not produced and not PROPOSED",
    ),
    (
        "M04 SCR-142/healthy: the stamp clause removed",
        _sub("SCR-142/healthy", SH, "stamp Sampled 10:31:03 UTC (every 60 s) · ", ""),
        "R-2 SCR-142/healthy: sample timestamp missing",
    ),
    (
        "M05 SCR-142/stale-sample: the stale marker removed",
        _sub("SCR-142/stale-sample", SH, ", stale (3 min old)", ""),
        "R-2 SCR-142/stale-sample: staleness not shown",
    ),
    (
        "M06 SCR-142/healthy: the budget meter's denominator removed",
        _sub("SCR-142/healthy", SH, " of 2,000.0 GB cap_bytes", ""),
        "R-3 SCR-142/healthy: meter without denominator",
    ),
    (
        "M07 SCR-142/healthy: a third meter added",
        _append(
            "SCR-142/healthy", SH, "meter Parquet share: 548.0 GB of 2,000.0 GB cap_bytes (27.4 %)"
        ),
        "R-3 SCR-142/healthy: more than two meters",
    ),
    (
        "M08 TIER/questdb: the Health word removed, the tone kept",
        _sub(
            "TIER/questdb",
            SH,
            "Health healthy, the text word with the ✓ glyph (ComponentState)",
            "Health (tone ok, the ✓ glyph)",
        ),
        "R-4 TIER/questdb: health by colour alone",
    ),
    (
        "M09 SCR-142/tier-unreachable-questdb: the page-usable clause removed",
        _sub(TUQ, SH, "page usable, ", ""),
        "R-4 tier-unreachable-questdb: page-level error",
    ),
    (
        "M10 SCR-142/low-disk-warning: the AC 2 sentence removed",
        _sub(
            "SCR-142/low-disk-warning",
            SH,
            ' with the AC 2 sentence "Recording pauses before trading is affected." and the detail line of §1.4',
            "",
        ),
        "R-5 low-disk-warning: degradation sentence missing",
    ),
    (
        "M11 SCR-142/read-only-disk-full: the sentence inverted",
        _sub(
            ROD,
            SH,
            "Recording pauses before trading is affected.",
            "Trading pauses before recording is affected.",
        ),
        "R-5 read-only-disk-full: degradation order inverted",
    ),
    (
        "M12 SCR-142/read-only-disk-full: Compact drawn T2 with a lock",
        _append(ROD, CT, "Compact Parquet… T2 with a lock"),
        "R-6 read-only-disk-full: state drawn as a lock",
    ),
    (
        "M13 SCR-142/migration-pending: an Apply migrations button added",
        _append("SCR-142/migration-pending", CT, "Apply migrations button"),
        "R-6 migration-pending: deferred capability drawn as a control",
    ),
    (
        "M14 SCR-142/tier-unreachable-questdb: Purge aria-disabled",
        _append(TUQ, CT, "Purge data… aria-disabled while QuestDB is down"),
        "R-6 tier-unreachable-questdb: action gated by state",
    ),
    (
        "M15 PURGE/dialog: the typed field pre-filled",
        _sub(PDL, SH, "empty, never pre-filled", "pre-filled with ETHUSDT"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled",
    ),
    (
        "M16 PURGE/dialog: the Reason field removed",
        _sub(PDL, SH, "Reason (CMP-007, required, 3–280 characters) · ", ""),
        "R-7 PURGE/dialog: reason missing",
    ),
    (
        "M17 PURGE/step-up: the step-up sentence removed",
        _sub(
            "PURGE/step-up",
            SH,
            'the step-up sentence "You\'ll confirm with your password and a code." already in the dialog · ',
            "",
        ),
        "R-7 PURGE/step-up: elevation not shown",
    ),
    (
        "V01 PURGE/dialog: the before field removed (the purge-contract re-pin, #4597)",
        _sub(
            PDL,
            SH,
            "Delete data recorded before (CMP-047 single) 2026-08-15, the retention cut-off: the contract's `before`, required (`22` :15086), "
            "the exclusive upper bound of the window `[earliest, before)` sent as a `date-time` instant with an offset and not later than the "
            'server\'s clock (:15051–15054, :15092–15097), with the help line "Data recorded at or after this time is kept." under it · ',
            "",
        ),
        "R-7 PURGE/dialog: before field missing",
    ),
    (
        "M18 PURGE/dialog-validity: a lock added",
        _append("PURGE/dialog-validity", SH, "a lock glyph before the label"),
        "R-8 PURGE/dialog-validity: lock on a validity control",
    ),
    (
        "M19 IMPORT/form-validity: CMP-079 added",
        _append("IMPORT/form-validity", SH, "wrapped in CMP-079"),
        "R-8 IMPORT/form-validity: RbacGate on validity",
    ),
    (
        "M20 IMPORT/running-with-skips: a page banner added",
        _append(SKP, SH, "a page banner"),
        "R-9 running-with-skips: page banner on a skipped file",
    ),
    (
        "M21 IMPORT/running-with-skips: the bar-keeps-moving clause removed",
        _sub(SKP, SH, "the overall bar keeps moving: ", ""),
        "R-9 running-with-skips: progress not continuing",
    ),
    (
        "M22 IMPORT/failed: the failure drawn as a page banner",
        _sub("IMPORT/failed", SH, "never a page banner", "also as a page banner"),
        "R-9 IMPORT/failed: failure outside the card",
    ),
    (
        "M23 IMPORT/running-with-skips: the Reason column removed",
        _sub(SKP, SH, "Day / Status / Reason / Rows", "Day / Status / Rows"),
        "R-10 running-with-skips: skip without reason",
    ),
    (
        "M24 IMPORT/summary: the overlap report removed",
        _sub(
            "IMPORT/summary",
            SH,
            ', the overlap report "660,000 rows inside recorded windows were discarded — recorded data wins." (`22` :14983, never "duplicates removed")',
            "",
        ),
        "R-10 IMPORT/summary: overlap report missing",
    ),
    (
        "M25 IMPORT/summary: archive-derived removed from the tag",
        _sub(
            "IMPORT/summary",
            SH,
            "Archive-derived · trades only · no book data",
            "Imported · trades only · no book data",
        ),
        "R-10 IMPORT/summary: archive-derived label missing",
    ),
    (
        "M26 IMPORT/summary: no book data removed from the tag",
        _sub("IMPORT/summary", SH, " · no book data", ""),
        "R-10 IMPORT/summary: book-data caveat missing",
    ),
    (
        "M27 JOB/strip-running: the running Compact drawn T2",
        _append(SRN, CT, "Compact Parquet… T2"),
        "R-11 strip-running: busy drawn as T2",
    ),
    (
        "M28 JOB/strip-running: aria-busy removed",
        _sub(SRN, CT, "`aria-busy`, ", ""),
        "R-11 strip-running: busy without aria-busy",
    ),
    (
        "M29 JOB/strip-refused-409: the class T4 replaced by T2",
        _sub("JOB/strip-refused-409", CL, "T4", "T2"),
        "R-11 strip-refused-409: refusal drawn as a lock",
    ),
    (
        "M30 JOB/strip-running: the caption removed from the Stop job item",
        _sub(SRN, CT, f"Stop job per job line, {cap(10)}:", "Stop job per job line (D04-G10):"),
        "R-12 strip-running: Stop job without its caption",
    ),
    (
        "M31 SCR-142/view-as: rbac.view_as removed",
        _sub(VAS, CT, "the reason key `rbac.view_as` ", "the reason key "),
        "R-13 view-as: reason key missing",
    ),
    (
        "M32 SCR-142/view-as: a second notice added",
        _append(VAS, SH, "a second notice under the import card"),
        "R-13 view-as: more than one notice",
    ),
    (
        "M33 SCR-142/view-as: the full label dropped",
        _sub(
            VAS,
            CT,
            "the full label with the lock glyph leading it",
            "the lock glyph leading the label",
        ),
        "R-13 view-as: T2 without full label",
    ),
    (
        "M34 SCR-142/view-as: opacity.disabled added",
        _append(VAS, CT, "Compact Parquet… label at opacity.disabled"),
        "R-13 view-as: T2 dimmed",
    ),
    (
        "M35 §1.3: the view-as row moved below the validity row",
        lambda s: _swap_rows(
            s, "| every write while viewing as", "| Import archives while the range is empty"
        ),
        "R-13 §1.3: view-as leg not first",
    ),
    (
        "M36 SCR-142/view-as: the SCR-143 link aria-disabled",
        _sub(
            VAS,
            CT,
            "links to SCR-140, SCR-141 and SCR-143 enabled (T1)",
            "links to SCR-140, SCR-141 and SCR-143 aria-disabled",
        ),
        "R-14 view-as: exit gated",
    ),
    (
        "M37 SCR-142/read-only-disk-full: Shorten retention drawn T2",
        _sub(ROD, SH, "Reduce depth and Unpin as links (T1)", "Reduce depth and Unpin as links T2"),
        "R-14 read-only-disk-full: exit gated",
    ),
    (
        "M38 TIER/questdb: a console link added",
        _append("TIER/questdb", CT, "QuestDB console link"),
        "R-15 TIER/questdb: data-store console linked",
    ),
    (
        "M39 TIER/postgres: a Backup button added",
        _append("TIER/postgres", CT, "Backup now button"),
        "R-15 TIER/postgres: backup control drawn",
    ),
    (
        "M40 the whole file: #4463 pinned at a sha",
        lambda s: _first(s, "boards PR #4463 and", "boards PR #4463 (head 0a1b2c3d4e5f) and"),
        "R-16: unmerged sibling pinned (E16-D03 boards PR at 0a1b2c3d4e5f)",
    ),
    (
        "M41 SCR-142/healthy: the runway days +1",
        _sub("SCR-142/healthy", SH, "about 560 days", "about 561 days"),
        "R-17 SCR-142/healthy: the projection reads 561",
    ),
    (
        "M42 IMPORT/running-with-skips: 29 done -> 28 done",
        _sub(SKP, SH, "29 done", "28 done"),
        "R-17 IMPORT/running-with-skips: the done count reads 28",
    ),
    (
        "M43 §0: board 07's count 6 -> 5",
        lambda s: _counts(s, **{"board_frames.07": (6, 5)}),
        "R-18: §0 and §8's table disagree",
    ),
    (
        "M44 IMPORT/failed: the row deleted (its counts updated)",
        lambda s: _counts(
            _row_delete(s, "IMPORT/failed"),
            frames_total=(40, 39),
            frames_import=(6, 5),
            **{"board_frames.07": (6, 5)},
        ),
        "R-18: frame named in §0 missing from its table",
    ),
    (
        "M45 §14: rbac.view_as lengthened past 60",
        lambda s: _deck_edit(
            s, "rbac.view_as", "{user}.", "{user} of this organisation's accounts today."
        ),
        "R-19 §14: rbac sentence over 60 chars",
    ),
    (
        "M46 §14: a symbol added to the view-as sentence",
        lambda s: _deck_edit(s, "rbac.view_as", "{user}.", "{user} BTCUSDT."),
        "R-19 §14: reason names data",
    ),
    (
        "M47 JOB/outcomes: the compact-failed line re-worded",
        _sub(
            "JOB/outcomes", SH, COMPACT_FAILED, "Compaction failed (`<code>`). Nothing was deleted."
        ),
        "R-20 JOB/outcomes: E16-D02 copy altered",
    ),
    (
        "M48 JOB/confirm-compact: a typed field added",
        _append("JOB/confirm-compact", SH, "a typed symbol field"),
        "R-21 confirm-compact: typed confirm on a non-destructive action",
    ),
    (
        "M49 PURGE/dialog: the typed pattern replaced by standard",
        _sub(PDL, SH, "CMP-044 typed", "CMP-044 standard"),
        "R-21 dialog: a second purge shape ('CMP-044 standard')",
    ),
    (
        "M50 JOB/strip-running: an announcement per tick",
        _append(SRN, SH, "announced per tick"),
        "R-22 strip-running: announcement per tick",
    ),
    # ---- the lens's probes (A01-A60), each a form the first commit's keyword gates missed or caught
    (
        "A01 read-only-disk-full: Import archives greyed out",
        _append(ROD, CT, "Import archives greyed out while the gate is closed"),
        "R-6 read-only-disk-full: action gated by state ('greyed out'",
    ),
    (
        "A02 read-only-disk-full: Import archives disabled",
        _append(ROD, CT, "Import archives disabled until space is freed"),
        "R-6 read-only-disk-full: action gated by state ('disabled'",
    ),
    (
        "A03 read-only-disk-full: Compact Parquet… is inert",
        _append(ROD, CT, "Compact Parquet… is inert"),
        "R-6 read-only-disk-full: action gated by state ('inert'",
    ),
    (
        "A04 tier-unreachable: Purge data… can't be pressed",
        _append(TUQ, CT, "Purge data… can't be pressed while QuestDB is down"),
        'R-6 tier-unreachable-questdb: action gated by state ("can\'t be pressed"',
    ),
    (
        "A05 tier-unreachable: a LOCK glyph on Purge data…",
        _append(TUQ, CT, "Purge data… behind a LOCK glyph"),
        "R-6 tier-unreachable-questdb: state drawn as a lock ('LOCK'",
    ),
    (
        "A06 lag-warning: T2 with a 'not' later in the clause",
        _append(
            "SCR-142/lag-warning",
            CT,
            "Compact Parquet… T2 with the lock glyph, the reason not repeated",
        ),
        "R-6 lag-warning: state drawn as a lock ('T2'",
    ),
    (
        "A07 migration-pending: a Run migrations button",
        _append("SCR-142/migration-pending", CT, "Run migrations button"),
        "R-6 migration-pending: deferred capability drawn as a control ('Run migrations'",
    ),
    (
        "A08 stale-sample: every write dimmed",
        _append("SCR-142/stale-sample", CT, "every write dimmed until a fresh sample arrives"),
        "R-6 stale-sample: action gated by state ('dimmed'",
    ),
    (
        "A09 read-only-disk-full: the BQ-14 ruled sentence removed",
        _sub(ROD, CT, f"; {BQ14}", ""),
        "R-6 read-only-disk-full: the BQ-14 sentence missing",
    ),
    (
        "A10 §1.3 table: the status row reclassed T2",
        lambda s: _line_sub(s, "| disk full (`level` 3", "| **status**", "| **T2**"),
        "R-6 §1.3: 'disk full' classed T2, not status",
    ),
    (
        "A11 §5 prose: every write locked at level 3",
        lambda s: _first(
            s,
            "The view-as frame is the one T2 frame",
            "On level 3 every write is locked (T2) with the lock glyph. The view-as frame is the one T2 frame",
        ),
        "R-6 §5 prose: a state or write drawn as a lock ('locked')",
    ),
    (
        "A12 §14: a new storage.state.disk_full lock key",
        lambda s: _deck_add(
            s,
            "storage.volume_refused",
            '| `storage.state.disk_full` | "Locked while the disk is full." | `new` | `SCR-142/read-only-disk-full` |',
        ),
        "R-19 §14: a key outside the closed deck set (storage.state.disk_full)",
    ),
    (
        "A13 view-as: the lock glyph removed",
        _sub(VAS, CT, "with the lock glyph leading it", "with the label leading"),
        "R-13 view-as: T2 without lock",
    ),
    (
        "A14 view-as: one write greyed out",
        _append(VAS, CT, "Import archives greyed out"),
        "R-13 view-as: T2 dimmed ('greyed out'",
    ),
    (
        "A15 view-as: the fill at 45 % opacity",
        _sub(
            VAS,
            CT,
            "fill `color.surface.raised` + `color.border.default` hairline",
            "fill at 45 % opacity",
        ),
        "R-13 view-as: T2 dimmed ('45 % opacity'",
    ),
    (
        "A16 view-as: a second banner",
        _append(VAS, SH, "a second banner under the meters: Read-only while viewing as alex."),
        "R-13 view-as: more than one notice ('banner')",
    ),
    (
        "A17 view-as: Compact dropped from the T2 list",
        _sub(VAS, CT, "Compact Parquet…, ", ""),
        "R-13 view-as: a write missing from the T2 list (Compact Parquet…)",
    ),
    (
        "A18 view-as: the permission leg first",
        _sub(
            VAS,
            CT,
            "the view-as leg first, E09-D09 §2.1 step 3",
            "the permission leg first, then view-as",
        ),
        "R-13 view-as: view-as leg not first (frame row)",
    ),
    (
        "A19 §14: rbac.view_as reworded",
        lambda s: _deck_edit(
            s, "rbac.view_as", "Read-only while viewing as {user}.", "Choose the account first."
        ),
        "R-19 §14: rbac.view_as is not the ruled string",
    ),
    (
        "A20 PURGE/dialog: the exits removed",
        _sub(PDL, CT, "exits Cancel, Esc and the close ✕ (T1) · Confirm", "Confirm"),
        "R-14 dialog: exit missing (Cancel, Esc and the close ✕)",
    ),
    (
        "A21 confirm-compact: the exits disabled",
        _sub(
            "JOB/confirm-compact",
            CT,
            "exits Cancel, Esc and the close ✕ (T1)",
            "exits Cancel, Esc and the close ✕ disabled while confirming",
        ),
        "R-14 confirm-compact: exit gated ('disabled'",
    ),
    (
        "A22 healthy: the links greyed out",
        _sub(
            "SCR-142/healthy",
            CT,
            "links to SCR-140, SCR-141 and SCR-143 enabled (T1)",
            "links to SCR-140, SCR-141 and SCR-143 greyed out",
        ),
        "R-14 healthy: exit gated ('greyed out'",
    ),
    (
        "A23 view-as: the links inert",
        _sub(
            VAS,
            CT,
            "links to SCR-140, SCR-141 and SCR-143 enabled (T1)",
            "links to SCR-140, SCR-141 and SCR-143 inert",
        ),
        "R-14 view-as: exit gated ('inert'",
    ),
    (
        "A24 PURGE/dialog: the typed field auto-filled",
        _sub(PDL, SH, "empty, never pre-filled", "empty on open, then auto-filled with ETHUSDT"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('auto-filled')",
    ),
    (
        "A25 PURGE/dialog: the typed field Pre-Filled",
        _sub(PDL, SH, "empty, never pre-filled", "Pre-Filled with ETHUSDT"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('Pre-Filled')",
    ),
    (
        "A26 PURGE/dialog: the reason optional",
        _sub(PDL, SH, "Reason (CMP-007, required, 3–280 characters)", "Reason (CMP-007, optional)"),
        "R-7 PURGE/dialog: reason not required 3–280",
    ),
    (
        "A27 §7 prose: the typed field pre-filled",
        lambda s: _first(
            s,
            "the typed field empty — never pre-filled",
            "the typed field pre-filled with the row's symbol",
        ),
        "R-7 §7 prose: typed field pre-filled ('pre-filled')",
    ),
    (
        "A28 TIER/questdb: a second purge shape",
        _sub(
            "TIER/questdb",
            CT,
            "Purge data… (T1, opens E16-D02 §6.5)",
            "Purge data… (T1, a one-click CMP-044 standard purge)",
        ),
        "R-21 questdb: a second purge shape ('one-click')",
    ),
    (
        "A29 dialog-validity: the reason inside the button",
        _sub(
            "PURGE/dialog-validity",
            SH,
            "the reason full-opacity under it in",
            "the reason inside the button in",
        ),
        "R-8 PURGE/dialog-validity: the reason inside the control",
    ),
    (
        "A30 form-validity: RbacGate by name",
        _append("IMPORT/form-validity", SH, "wrapped in RbacGate"),
        "R-8 IMPORT/form-validity: RbacGate on validity ('RbacGate')",
    ),
    (
        "A31 §6 table: compact without 'Nothing is deleted.'",
        lambda s: _line_sub(s, "| Compact Parquet |", " Nothing is deleted.", ""),
        "R-21 §6 table: Compact Parquet confirm without 'Nothing is deleted.'",
    ),
    (
        "A32 §14: the compact body without 'Nothing is deleted.'",
        lambda s: _deck_edit(s, "storage.compact.body", " Nothing is deleted.", ""),
        "R-21 §14: storage.compact.body without 'Nothing is deleted.'",
    ),
    (
        "A33 §14: the vacuum body without 'Nothing is deleted.'",
        lambda s: _deck_edit(s, "storage.vacuum.body", " Nothing is deleted.", ""),
        "R-21 §14: storage.vacuum.body without 'Nothing is deleted.'",
    ),
    (
        "A34 TIER/postgres: Vacuum as a shipped T1 control",
        _sub(
            "TIER/postgres",
            CT,
            f"Vacuum Postgres… only as the inset {cap(8)}",
            "Vacuum Postgres… (T1)",
        ),
        "R-12 postgres: Vacuum without its caption (D04-G8)",
    ),
    (
        "A35 TIER/questdb: a shipped row count",
        _append("TIER/questdb", SH, "Rows 1,204,553,120 in trades"),
        "R-12 questdb: Rows without its caption (D04-G3)",
    ),
    (
        "A36 TIER/questdb: lag 240 ms as shipped",
        _sub("TIER/questdb", SH, f"lag — ({cap(4)})", "lag 240 ms"),
        "R-12 questdb: lag without its caption (D04-G4)",
    ),
    (
        "A37 TIER/per-symbol: a sparkline in every row",
        _append("TIER/per-symbol", SH, "a sparkline in every row"),
        "R-12 per-symbol: sparkline without its caption (D04-G2)",
    ),
    (
        "A38 strip-running: Stop per job, no caption",
        _sub(
            SRN,
            CT,
            f"Stop job per job line, {cap(10)}: today a started job runs to its end",
            "Stop per job line (T1)",
        ),
        "R-12 strip-running: Stop without its caption (D04-G10)",
    ),
    (
        "A39 view-as: the Stop job carrier without its caption",
        _sub(VAS, CT, f"Stop job on the jobs strip ({cap(10)})", "Stop job on the jobs strip"),
        "R-12 view-as: Stop job without its caption (D04-G10)",
    ),
    (
        "A40 migration-pending: the banner's caption removed",
        _sub(
            "SCR-142/migration-pending",
            SH,
            f"CMP-028 warning banner captioned {cap(7)}: ",
            "CMP-028 warning banner ",
        ),
        "R-12 migration-pending: Migration pending without its caption (D04-G7)",
    ),
    (
        "A41 §1.4 prose: the AC 2 sentence inverted",
        lambda s: _first(
            s,
            '**"Recording pauses before trading is affected."**',
            '**"Trading pauses before recording is affected."**',
        ),
        "R-5 §1.4 prose: degradation order inverted",
    ),
    (
        "A42 autostop: an inverted clause added",
        _append("SCR-142/autostop", SH, "trading stops before recording"),
        "R-5 autostop: degradation order inverted",
    ),
    (
        "A43 §14: the degradation detail inverted",
        lambda s: _deck_edit(
            s,
            "storage.degradation.detail",
            "orders and positions are never gated by the disk.",
            "orders stop first, then recording.",
        ),
        "R-5 §14 table (storage.degradation.detail): degradation order inverted",
    ),
    (
        "A44 running-with-skips: a danger callout across the page",
        _append(SKP, SH, "a CMP-028 danger callout across the top of the page: 1 file failed"),
        "R-9 running-with-skips: page banner on a skipped file ('callout')",
    ),
    (
        "A45 running-with-skips: a toast",
        _append(SKP, SH, "a toast: Import error"),
        "R-9 running-with-skips: page banner on a skipped file ('toast')",
    ),
    (
        "A46 running-with-skips: the bar paused",
        _append(SKP, SH, "the overall bar paused until the skipped file is retried"),
        "R-9 running-with-skips: progress stalled ('paused')",
    ),
    (
        "A47 running-with-skips: the skip reason and code removed",
        _sub(
            SKP,
            SH,
            '"skipped ⚠ / checksum_mismatch / Checksum did not match; the file was skipped. / —"',
            '"skipped ⚠ / — / — / —"',
        ),
        "R-10 running-with-skips: the skipped row without its code and sentence",
    ),
    (
        "A48 IMPORT/failed: across the top of the screen",
        _sub("IMPORT/failed", SH, "inside the import card only", "across the top of the screen"),
        "R-9 IMPORT/failed: failure outside the card ('top of')",
    ),
    (
        "A49 §8 prose: a page banner on a skipped file",
        lambda s: _first(
            s,
            'Either way the page keeps its healthy chrome with no banner and no `role="alert"`.',
            "Either way the page shows a danger banner and role=alert.",
        ),
        "R-9 §8 prose: page banner on a skipped file ('banner')",
    ),
    (
        "A50 TIER/questdb: Size 641.0 GB",
        _sub("TIER/questdb", SH, "Size 640.0 GB", "Size 641.0 GB"),
        "R-17 TIER/questdb: the tier size reads 641.0 GB",
    ),
    (
        "A51 TIER/parquet: Retention 31 d",
        _sub("TIER/parquet", SH, "Retention 30 d", "Retention 31 d"),
        "R-17 TIER/parquet: the tier retention reads 31 d",
    ),
    (
        "A52 healthy: 1,189.0 GB",
        _sub("SCR-142/healthy", SH, "1,188.0 GB of", "1,189.0 GB of"),
        "R-17 SCR-142/healthy: the budget meter reads 1189.0 GB",
    ),
    (
        "A53 low-disk-warning: 1,611.0 GB",
        _sub("SCR-142/low-disk-warning", COL["producer"], "1,610.0 GB", "1,611.0 GB"),
        "R-17 SCR-142/low-disk-warning: the level bytes reads 1611.0 GB · 2000.0 GB, not the tool's",
    ),
    (
        "A54 lag-warning: 6 batches",
        _sub("SCR-142/lag-warning", SH, "5 batches", "6 batches"),
        "R-17 SCR-142/lag-warning: the lag threshold reads 6",
    ),
    (
        "A55 confirm-compact: 640 MiB",
        _sub("JOB/confirm-compact", SH, "512 MiB", "640 MiB"),
        "R-17 JOB/confirm-compact: the merge size reads 640",
    ),
    (
        "A56 healthy: free 2.9 TB",
        _sub("SCR-142/healthy", SH, "free 2.8 TB", "free 2.9 TB"),
        "R-17 SCR-142/healthy: the free volume reads 2.9 TB",
    ),
    (
        "A57 R-16: 'PR 4463 at <sha>'",
        lambda s: _first(
            s,
            "**the E16-D03 boards PR #4463",
            "the E16-D03 boards (PR 4463 at 1a2b3c4d) **the E16-D03 boards PR #4463",
        ),
        "R-16: unmerged sibling pinned (E16-D03 boards at 1a2b3c4d)",
    ),
    (
        "A58 tier-unreachable: a page-level danger banner",
        _append(TUQ, SH, "a CMP-028 danger banner: Storage unavailable"),
        "R-4 tier-unreachable-questdb: page-level banner ('banner')",
    ),
    (
        "A59 strip-refused-409: Compact greyed out",
        _append("JOB/strip-refused-409", CT, "Compact Parquet… greyed out until the job ends"),
        "R-11 strip-refused-409: refusal drawn as a disabled control ('greyed out'",
    ),
    (
        "A60 strip-running: Import archives disabled",
        _append(SRN, CT, "Import archives disabled while a job runs"),
        "R-11 strip-running: a write gated while a job runs ('disabled'",
    ),
    # ---- this fold's own variants (O01-O22)
    (
        "O01 read-only-disk-full: Purge data… grayed out (US spelling)",
        _append(ROD, CT, "Purge data… grayed out"),
        "R-6 read-only-disk-full: action gated by state ('grayed out'",
    ),
    (
        "O02 low-disk-warning: every write blocked",
        _append("SCR-142/low-disk-warning", CT, "every write blocked until space is freed"),
        "R-6 low-disk-warning: action gated by state ('blocked'",
    ),
    (
        "O03 autostop: Import archives faded",
        _append("SCR-142/autostop", CT, "Import archives faded"),
        "R-6 autostop: action gated by state ('faded'",
    ),
    (
        "O04 volume-refused: Compact cannot be used",
        _append("SCR-142/volume-refused", CT, "Compact Parquet… cannot be used"),
        "R-6 volume-refused: action gated by state ('cannot be used'",
    ),
    (
        "O05 tier-unreachable: Compact behind a padlock",
        _append(TUQ, CT, "Compact Parquet… behind a padlock"),
        "R-6 tier-unreachable-questdb: state drawn as a lock ('padlock'",
    ),
    (
        "O06 healthy: Import archives wrapped in CMP-079",
        _append("SCR-142/healthy", CT, "Import archives wrapped in CMP-079"),
        "R-6 healthy: state drawn as a lock ('CMP-079'",
    ),
    (
        "O07 §14: a lock sentence inside an existing deck string",
        lambda s: _deck_edit(
            s, "storage.lag.banner", 'writes are behind the feed" ·', 'writes are locked" ·'
        ),
        "R-6 §14 table (storage.lag.banner): a state or write drawn as a lock ('locked')",
    ),
    (
        "O08 §1.3 table: the busy row reclassed T2",
        lambda s: _line_sub(
            s, "| Compact Parquet… / Import archives / Purge…", "| **busy**", "| **T2**"
        ),
        "R-6 §1.3: 'Compact Parquet… / Import arch' classed T2, not busy",
    ),
    (
        "O09 §6 table: vacuum without 'Nothing is deleted.'",
        lambda s: _line_sub(s, "| Vacuum Postgres |", " Nothing is deleted.", ""),
        "R-21 §6 table: Vacuum Postgres confirm without 'Nothing is deleted.'",
    ),
    (
        "O10 PURGE/dialog: the roll-off sentence dropped from the reuse",
        _sub(PDL, SH, " Shared QuestDB day partitions are freed by the nightly roll-off.", ""),
        "R-21 PURGE/dialog: E16-D02 §6.5's body not reused whole",
    ),
    (
        "O11 TIER/parquet: Last compaction without its caption",
        _sub("TIER/parquet", SH, f"Last compaction — ({cap(6)}, ", "Last compaction — ("),
        "R-12 parquet: Last compaction without its caption (D04-G6)",
    ),
    (
        "O12 IMPORT/running: the per-file inset uncaptioned",
        _sub("IMPORT/running", SH, f"only as an inset {cap(11)}:", "only as an inset:"),
        "R-12 running: per-file without its caption (D04-G11)",
    ),
    (
        "O13 IMPORT/summary: the result inset captioned with the wrong gap",
        _sub("IMPORT/summary", SH, f"an inset {cap(11)} from", f"an inset {cap(12)} from"),
        "R-12 summary: per-file without its caption (D04-G11)",
    ),
    (
        "O14 R-16: 'pull/4501' with a line cite",
        lambda s: _first(
            s,
            "**Hand-offs:**",
            "**Hand-offs:** the E16-D05 boards (pull/4501 at :88) stay PENDING;",
        ),
        "R-16: unmerged sibling pinned (E16-D05 boards at :88)",
    ),
    (
        "O15 TIER/questdb: the healthy backlog 1 row",
        _sub("TIER/questdb", SH, "backlog 0 rows", "backlog 1 rows"),
        "R-17 TIER/questdb: the backlog reads 1",
    ),
    (
        "O16 PURGE/dialog: the window's first date moved",
        _sub(PDL, SH, "from 2026-08-13 to", "from 2026-08-12 to"),
        "R-17 PURGE/dialog: the purge window reads 1.2 GB · 2026-08-12",
    ),
    (
        "O17 §14: the AC 2 sentence weakened",
        lambda s: _deck_edit(
            s, "storage.degradation", "Recording pauses before", "Recording may pause before"
        ),
        "R-5 §14 table (storage.degradation): degradation order weakened",
    ),
    (
        "O18 view-as: the label in color.text.disabled",
        _sub(VAS, CT, "label `color.text.tertiary`", "label `color.text.disabled`"),
        "R-13 view-as: T2 dimmed ('color.text.disabled'",
    ),
    (
        "O19 PURGE/step-up: the exits removed",
        _sub("PURGE/step-up", CT, "exits Cancel, Esc and the close ✕ on the modal (T1); ", ""),
        "R-14 step-up: exit missing (Cancel, Esc and the close ✕)",
    ),
    (
        "O20 JOB/confirm-vacuum: the Vacuum button uncaptioned",
        _sub(
            "JOB/confirm-vacuum",
            CT,
            f"Vacuum (CMP-001 primary, T1), {cap(8)}",
            "Vacuum (CMP-001 primary, T1)",
        ),
        "R-12 confirm-vacuum: Vacuum without its caption (D04-G8)",
    ),
    (
        "O21 §8 prose: a toast for a skipped file",
        lambda s: _first(
            s,
            "Only a `failed` job uses `color.status.danger.subtle`",
            "A skipped file also raises a toast. Only a `failed` job uses `color.status.danger.subtle`",
        ),
        "R-9 §8 prose: page banner on a skipped file ('toast')",
    ),
    (
        "O22 §5 prose: every write greyed out on the state frames",
        lambda s: _first(
            s,
            "every write stays enabled on every state frame",
            "every write stays greyed out on every state frame",
        ),
        "R-6 §5 prose: a state or write drawn as a lock ('greyed out')",
    ),
    (
        "P01 §1.1 prose: the Vacuum button beside Compact now",
        _para_add(P11, "The Vacuum button sits beside Compact now on the Postgres card."),
        "R-12 §1.1 prose: vacuum presented as shipped ('Vacuum button')",
    ),
    (
        "P02 §1.1 prose: each tier card lists its slowest queries",
        _para_add(P11, "Each tier card lists its slowest queries."),
        "R-12 §1.1 prose: slow queries presented as shipped ('slowest queries')",
    ),
    (
        "P03 §1.1 prose: a Stop button cancels the running compaction",
        _para_add(P11, "A Stop button cancels the running compaction."),
        "R-12 §1.1 prose: stop job presented as shipped ('cancels the running compaction') without ",
    ),
    (
        "P04 healthy: the Vacuum button in the Producer cell",
        lambda s: _row_edit(
            s,
            "SCR-142/healthy",
            COL["producer"],
            lambda c: f"the Vacuum button beside Compact now; {c}",
        ),
        "R-12 healthy: vacuum drawn as shipped ('Vacuum button')",
    ),
    (
        "P05 §6 action table: a Cancel button in the Stop job column",
        lambda s: _line_sub(
            s, "| Compact Parquet ", "| PROPOSED (D04-G10) ", "| a Cancel button    "
        ),
        "R-12 §6 table (Compact Parquet): stop job presented as shipped ('Cancel button')",
    ),
    (
        "P06 §14: the vacuum key's Where reads the Vacuum button beside Compact",
        lambda s: _deck_edit(
            s, "storage.vacuum.button", "the vacuum inset", "the Vacuum button beside Compact"
        ),
        "R-12 §14 table (storage.vacuum.button): vacuum presented as shipped ('Vacuum button')",
    ),
    (
        "P07 §2 sketch: Vacuum Postgres… drawn as a button",
        lambda s: _first(s, "┆ Vacuum Postgres… ⁴ ┆", "[ Vacuum Postgres… ]"),
        "R-12 §2 sketch: vacuum without its caption ('Vacuum'",
    ),
    (
        "P08 §4 prose: a per-tier Growth/day value",
        _para_add(
            "The three cards are the AC 1 surface", "The QuestDB card reads Growth/day 1.45 GB/day."
        ),
        "R-12 §4 prose: per-tier growth presented as shipped ('QuestDB card reads Growth') without ",
    ),
    (
        "P09 §2 table (e): the growth sparkline beside the Growth column",
        lambda s: _line_sub(
            s,
            "| (e)",
            "the sparkline only as captioned PROPOSED carriers",
            "the growth sparkline beside the Growth column",
        ),
        "R-12 §2 table ((e)): sparkline presented as shipped ('Oldest / Newest')",
    ),
    (
        "P10 §5 prose: a lag value on the QuestDB card",
        _para_add("The ticket's five states", "The QuestDB card shows ingestion lag 4 s."),
        "R-12 §5 prose: lag presented as shipped ('ingestion lag') without its caption (D04-G4)",
    ),
    (
        "P11 §8 prose: the per-file table filled while the import runs",
        lambda s: _first(
            s,
            "The per-file rows and the",
            "The per-file table fills row by row while the import runs. The per-file rows and the",
        ),
        "R-12 §8 prose: per-file rows presented as shipped",
    ),
    (
        "P12 §10 prose: the jobs strip's lowercase stop button",
        lambda s: _first(
            s,
            "the jobs strip's Stop job carriers (PROPOSED D04-G10)",
            "the jobs strip's stop button",
        ),
        "R-12 §10 prose: stop job presented as shipped ('stop button')",
    ),
    # ---- the orchestrator's text round 1 probes (R01-R31), rebuilt verbatim: each slipped at the pushed head
    (
        "R01 dialog-validity: an exit greyed out after ';'",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + "; greyed out until the form is valid"),
        "R-14 dialog-validity: exit gated ('greyed out' in 'greyed out until the form is')",
    ),
    (
        "R02 dialog-validity: an exit greyed out in an 'It …' follow-on",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + " · It is greyed out until the form is valid."),
        "R-14 dialog-validity: exit gated ('greyed out' in 'It is greyed out until the f')",
    ),
    (
        "R03 view-as: the links '; locked'",
        _sub(VAS, CT, LINKS_T1, LINKS_T1 + "; locked"),
        "R-14 view-as: exit gated ('locked' in 'locked')",
    ),
    (
        "R04 view-as: the links '; each with the lock glyph'",
        _sub(VAS, CT, LINKS_T1, LINKS_T1 + "; each with the lock glyph"),
        "R-14 view-as: exit gated ('lock' in 'each with the lock glyph')",
    ),
    (
        "R05 view-as: the links in a 'They …' follow-on",
        _sub(VAS, CT, LINKS_T1, LINKS_T1 + " · They are unavailable while viewing as."),
        "R-14 view-as: exit gated ('unavailable' in 'They are unavailable while v')",
    ),
    (
        "R06 strip-running: a Cancel per job line beside an exit",
        _sub(SRN, CT, STOP_ITEM, "Cancel per job line and a link to SCR-140 (T1)"),
        "R-12 strip-running: the job action drawn as 'Cancel per job line and a link…' (it is Stop ",
    ),
    (
        "R07 healthy: a Cancel button on each job line beside the links",
        _sub("SCR-142/healthy", CT, LINKS_T1, LINKS_T1 + " and a Cancel button on each job line"),
        "R-12 healthy: the job action drawn as 'Cancel button on each job line…' (it is Stop job, D",
    ),
    (
        "R08 per-symbol: a bare Rows column",
        _sub("TIER/per-symbol", SH, "Share of budget / Pinned", "Share of budget / Pinned / Rows"),
        "R-12 per-symbol: Rows without its caption (D04-G3)",
    ),
    (
        "R09 per-symbol: a CMP-024 per row",
        _append("TIER/per-symbol", SH, "a CMP-024 per row"),
        "R-12 per-symbol: CMP-024 without its caption (D04-G2)",
    ),
    (
        "R10 per-symbol: a growth trend line per row",
        _append("TIER/per-symbol", SH, "a growth trend line per row"),
        "R-12 per-symbol: trend line without its caption (D04-G2)",
    ),
    (
        "R11 strip-running: an End job button",
        _append(SRN, CT, "an End job button per job line"),
        "R-12 strip-running: End job without its caption (D04-G10)",
    ),
    (
        "R12 PURGE/dialog: the typed field set to the symbol later",
        _sub(
            PDL,
            SH,
            "empty, never pre-filled",
            "empty at first, then set to ETHUSDT when the dialog opens",
        ),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('empty at first')",
    ),
    (
        "R13 PURGE/entry-points: the typed field already holding it",
        _sub(
            "PURGE/entry-points", SH, "the typed field empty", "the typed field already holding it"
        ),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('already holding')",
    ),
    (
        "R14 per-symbol: the symbol typed into the confirm field",
        _sub(
            "TIER/per-symbol",
            CT,
            "the typed field empty",
            "the symbol typed into the confirm field",
        ),
        "R-7 TIER/per-symbol: confirm_symbol pre-filled ('typed into')",
    ),
    (
        "R15 §7 prose: the typed field filled in",
        lambda s: _first(
            s,
            "**the typed field empty — never pre-filled**",
            "the typed field filled in with the symbol",
        ),
        "R-7 §7 prose: typed field pre-filled ('filled in')",
    ),
    (
        "R16 healthy: Purge data… opens a lighter confirm",
        _sub(
            "SCR-142/healthy",
            CT,
            "Purge data…",
            "Purge data… (opens a lighter confirm with no typed field)",
        ),
        "R-21 healthy: a second purge shape ('lighter confirm')",
    ),
    (
        "R17 TIER/questdb: §6.5 without its typed field",
        _sub(
            "TIER/questdb", CT, "opens E16-D02 §6.5)", "opens E16-D02 §6.5 without its typed field)"
        ),
        "R-21 questdb: a second purge shape ('without its typed field')",
    ),
    (
        "R18 §7 prose: its own purge dialog, a standard confirm",
        lambda s: _first(
            s,
            "SCR-142 adds **entry points**, not a dialog:",
            "SCR-142 adds its own purge dialog, a CMP-044 standard confirm:",
        ),
        "R-21 §7 prose: a second purge shape ('its own purge dialog')",
    ),
    (
        "R19 §7 prose: a one-click purge",
        _para_add(P07, "The per-symbol row offers a one-click purge."),
        "R-21 §7 prose: a second purge shape ('one-click')",
    ),
    (
        "R20 TIER/questdb: Size 548.0 GB",
        _sub("TIER/questdb", SH, "Size 640.0 GB", "Size 548.0 GB"),
        "R-17 TIER/questdb: the tier size reads 548.0 GB, not the tool's 640.0 GB",
    ),
    (
        "R21 TIER/parquet: Retention 7 d",
        _sub("TIER/parquet", SH, "Retention 30 d", "Retention 7 d"),
        "R-17 TIER/parquet: the tier retention reads 7 d, not the tool's 30 d",
    ),
    (
        "R22 healthy: 85 % warning",
        _sub("SCR-142/healthy", SH, "80 % warning", "85 % warning"),
        "R-17 SCR-142/healthy: the warning step reads 85, not the tool's 80",
    ),
    (
        "R23 low-disk-warning: clears below 80 %",
        _sub("SCR-142/low-disk-warning", SH, "clears below 75 %", "clears below 80 %"),
        "R-17 SCR-142/low-disk-warning: the warning clear reads 80, not the tool's 75",
    ),
    (
        "R24 confirm-compact: at most 16 MiB",
        _sub("JOB/confirm-compact", SH, "at most 512 MiB", "at most 16 MiB"),
        "R-17 JOB/confirm-compact: the merge size reads 16, not the tool's 512",
    ),
    (
        "R25 §1.4: at 85 %",
        lambda s: _first(
            s,
            "at 80 % of the recording budget (or a runway",
            "at 85 % of the recording budget (or a runway",
        ),
        "R-17 §1.4 prose: the warning step reads 85, not the tool's 80",
    ),
    (
        "R26 autostop: orders refused before recording pauses",
        _append("SCR-142/autostop", SH, "orders are refused before recording pauses"),
        "R-5 autostop: degradation order inverted ('orders are refused before')",
    ),
    (
        "R27 §1.4: orders refused before recording pauses",
        _para_add(P14, "Orders are refused before recording pauses."),
        "R-5 §1.4 prose: degradation order inverted ('Orders are refused before')",
    ),
    (
        "R28 §2 (g): Purge data… and Vacuum Postgres… as CMP-001 secondary",
        lambda s: _first(
            s,
            G_REGION,
            'CMP-001 secondary "Compact Parquet…", "Purge data…" and "Vacuum Postgres…"',
        ),
        "R-21 §2 table ((g)): Purge data… on the maintenance card (the entry points are the tier ca",
    ),
    (
        "R29 §6 prose: the maintenance card also offers Vacuum Postgres…",
        _para_add(
            P06, "The maintenance card also offers Vacuum Postgres… for the relational tier."
        ),
        "R-12 §6 prose: vacuum presented as shipped ('Vacuum Postgres…') without its caption (D04-G",
    ),
    (
        "R30 R-16: the E16-D03 boards read at a sha, no number",
        lambda s: _first(s, PEND, "The E16-D03 boards are read at `9f8e7d6c5b`. " + PEND),
        "R-16: unmerged sibling pinned (E16-D03 boards at `9f8e7d6c5b`)",
    ),
    (
        "R31 R-16: an all-digit sha",
        lambda s: _first(s, PEND, "The E16-D05 boards PR #4501 is read at `12345678`. " + PEND),
        "R-16: unmerged sibling pinned (E16-D05 boards PR at `12345678`)",
    ),
    # ---- this fold's own variants (N01-N25): the same gates in wordings and carriers the probes did not try
    (
        "N01 dialog-validity: 'Each is not available' after the exits",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + " · Each is not available until the form is valid."),
        "R-14 dialog-validity: exit gated ('not available' in 'Each is not available until ')",
    ),
    (
        "N02 confirm-vacuum: the exits can't be used",
        _sub(
            "JOB/confirm-vacuum", CT, EXITS_T1, EXITS_T1 + "; they can't be used while confirming"
        ),
        'R-14 confirm-vacuum: exit gated ("can\'t be used" in "they can\'t be used while con")',
    ),
    (
        "N03 pinned-refused: the close ✕ no longer available",
        _append("PURGE/pinned-refused", CT, "the close ✕ no longer available after the refusal"),
        "R-14 pinned-refused: exit gated ('no longer available' in 'the close ✕ no longer availa')",
    ),
    (
        "N04 strip-running: Abort per job line",
        _sub(SRN, CT, STOP_ITEM, "Abort per job line (T1)"),
        "R-12 strip-running: Abort without its caption (D04-G10)",
    ),
    (
        "N05 confirm-compact: the exit Cancel captioned PROPOSED",
        _sub("JOB/confirm-compact", CT, EXITS_T1, f"{EXITS_T1}, {cap(10)}"),
        "R-14 confirm-compact: the exit Cancel captioned PROPOSED",
    ),
    (
        "N06 §14: the job action labelled Cancel",
        lambda s: _deck_edit(s, "storage.job.stop", '"Stop job"', '"Cancel"'),
        "R-12 §14: the PROPOSED job action is not labelled Stop job",
    ),
    (
        "N07 §14: the exit Cancel's source PROPOSED",
        lambda s: _deck_edit(
            s, "storage.confirm.cancel", "CMP-044 `15` :473", "CMP-044 `15` :473 (PROPOSED D04-G10)"
        ),
        "R-14 §14: the exit Cancel captioned PROPOSED (storage.confirm.cancel)",
    ),
    (
        "N08 PURGE/dialog: the symbol copied into the typed field",
        _sub(PDL, SH, "empty, never pre-filled", "empty until the symbol is copied into it"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('copied into')",
    ),
    (
        "N09 §4 prose: the popover's Purge… skips the typed field",
        _para_add(P04, "Purge… in the per-symbol popover skips the typed field."),
        "R-21 §4 prose: a second purge shape ('skips the typed field')",
    ),
    (
        "N10 §1.4: the halt step at 90 %",
        lambda s: _first(
            s,
            "at 95 % (or less than 5 % of the volume free)",
            "at 90 % (or less than 5 % of the volume free)",
        ),
        "R-17 §1.4 prose: the halt step reads 90, not the tool's 95",
    ),
    (
        "N11 autostop: resumes below 80 % of the budget",
        _sub(
            "SCR-142/autostop",
            SH,
            "resumes below 85 % of the budget",
            "resumes below 80 % of the budget",
        ),
        "R-17 SCR-142/autostop: the autostop clear reads 80, not the tool's 85",
    ),
    (
        "N12 §14: the formula's runway swapped for the full date's",
        lambda s: _deck_edit(s, "storage.formula", "≈ 422 days", "≈ 560 days"),
        "R-17 §14 table (storage.formula): the formula reads 90 · 2000.0 GB · 1188.0 GB · 1.45 GB/d",
    ),
    (
        "N13 §2 sketch: the QuestDB and Parquet sizes swapped",
        lambda s: _first(
            s, "Size 640.0 GB          Size 548.0 GB", "Size 548.0 GB          Size 640.0 GB"
        ),
        "R-17 §2 sketch: the tier sizes reads 548.0 GB · 640.0 GB · 16.0 GB, not the tool's 640.0 G",
    ),
    (
        "N14 per-symbol: BTCUSDT's growth swapped for ETHUSDT's",
        _sub("TIER/per-symbol", SH, "BTCUSDT 812.3 GB 780 MB/day", "BTCUSDT 812.3 GB 520 MB/day"),
        "R-17 TIER/per-symbol: the BTCUSDT row reads 812.3 GB · 520 MB/day · 40.6 %, not the tool's",
    ),
    (
        "N15 low-disk-warning: trading may also be affected",
        _append("SCR-142/low-disk-warning", SH, "trading may also be affected"),
        "R-5 low-disk-warning: degradation order weakened ('trading may also be affected')",
    ),
    (
        "N16 §1.4: recording continues while trading halts",
        _para_add(P14, "Recording continues while trading halts."),
        "R-5 §1.4 prose: degradation order inverted ('Recording continues while trading')",
    ),
    (
        "N17 §5 prose: trading is the first to stop",
        _para_add(P05, "Trading is the first to stop when the disk fills."),
        "R-5 §5 prose: degradation order inverted ('Trading is the first to')",
    ),
    (
        "N18 §2 (g): Vacuum Postgres… as a shipped secondary button",
        lambda s: _first(
            s, G_REGION, 'CMP-001 secondary "Compact Parquet…" and "Vacuum Postgres…"'
        ),
        "R-12 §2 table ((g)): vacuum presented as shipped ('Vacuum Postgres…') without its caption ",
    ),
    (
        "N19 §2 sketch: a short PROPOSED form on the (g) line",
        lambda s: _first(s, "┆ Vacuum Postgres… ⁴ ┆", "┆ Vacuum Postgres… PROPOSED D04-G8 ┆"),
        "R-12 §2 sketch: a short PROPOSED form (the full caption, or its footnote)",
    ),
    (
        "N20 §14: the ingestion example with a short caption",
        lambda s: _deck_edit(
            s, "storage.ingestion", f"lag — ({cap(4)})", "lag — (PROPOSED D04-G4)"
        ),
        "R-12 §14 table (storage.ingestion): a short PROPOSED form in a deck string (the full capti",
    ),
    (
        "N21 §2 sketch: Purge data… back on the maintenance line",
        lambda s: _first(s, "[ Compact Parquet… ]   ┆", "[ Compact Parquet… ] [ Purge data… ] ┆"),
        "R-21 §2 sketch: Purge data… on the maintenance card (the entry points are the tier cards)",
    ),
    (
        "N22 §1.3 prose: 'They are locked' after the exits sentence",
        lambda s: _first(
            s,
            "enabled for every role on every frame.",
            "enabled for every role on every frame. They are locked while viewing as.",
        ),
        "R-14 §1.3 prose: an exit drawn locked ('locked')",
    ),
    (
        "N23 strip-running: Cancel per job line, captioned",
        _sub(
            SRN,
            CT,
            STOP_ITEM,
            f"Cancel per job line, {cap(10)}: today a started job runs to its end",
        ),
        "R-12 strip-running: the job action drawn as 'Cancel per job line, CAPTION10…' (it is Stop ",
    ),
    (
        "N24 IMPORT/running: the Stop job carrier uncaptioned",
        _sub("IMPORT/running", CT, f"Stop job, {cap(10)}", "Stop job (T1)"),
        "R-12 running: Stop job without its caption (D04-G10)",
    ),
    (
        "N25 R-16: the E16-D05 boards at a line cite",
        lambda s: _first(s, PEND, "The E16-D05 boards are read at :142. " + PEND),
        "R-16: unmerged sibling pinned (E16-D05 boards at :142)",
    ),
    (
        "N26 §1.1 prose: the typed field arrives with the symbol already in it",
        _para_add(P11, "The typed field arrives with the symbol already in it."),
        "R-7 §1.1 prose: typed field pre-filled ('arrives with the symbol')",
    ),
    (
        "N27 PURGE/dialog: the typed field already holds the symbol",
        _append(PDL, SH, "the typed field already holds the symbol"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('already holds')",
    ),
    (
        "N28 PURGE/entry-points: the symbol entered for you",
        _append("PURGE/entry-points", SH, "the symbol is entered for you"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('entered for you')",
    ),
    (
        "N29 §14: the typed field opens with the symbol",
        lambda s: _deck_edit(
            s,
            "storage.purge.typed",
            "E16-D02 §6.5 :415",
            "E16-D02 §6.5 :415; it opens with the symbol",
        ),
        "R-7 §14 table (storage.purge.typed): typed field pre-filled ('opens with the symbol')",
    ),
    (
        "N30 §6 table: the purge symbol field defaults to the symbol",
        lambda s: _line_sub(
            s,
            "| Purge data ",
            "reused whole (§7)",
            "reused whole (§7), its symbol field defaults to the symbol",
        ),
        "R-7 §6 table (Purge data): typed field pre-filled ('defaults to the symbol')",
    ),
    (
        "N31 §7 prose: the confirm field starts with ETHUSDT",
        _para_add(P07, "The confirm field starts with ETHUSDT."),
        "R-7 §7 prose: typed field pre-filled ('starts with ETHUSDT')",
    ),
    (
        "N32 PURGE/dialog-validity: the typed field suggests the symbol",
        _append(PDV, SH, "the typed field suggests the symbol"),
        "R-7 PURGE/dialog-validity: confirm_symbol pre-filled ('suggests the symbol')",
    ),
    (
        "N33 §1.1 prose: the symbol field uses autofill",
        _para_add(P11, "The symbol field uses autofill."),
        "R-7 §1.1 prose: typed field pre-filled ('autofill')",
    ),
    # ---- the orchestrator's text round 2 probes (T01-T22), rebuilt verbatim: each slipped at the pushed head
    (
        "T01 confirm-compact: Esc does nothing while the confirm is open",
        _sub(CCF, CT, EXITS_T1, EXITS_T1 + " · Esc does nothing while the confirm is open"),
        "R-14 confirm-compact: exit gated ('does nothing' in 'Esc does nothing while the c')",
    ),
    (
        "T02 TIER/parquet: Esc does nothing while a compaction runs",
        _dot("TIER/parquet", CT, "Esc does nothing while a compaction runs"),
        "R-14 parquet: exit gated ('does nothing' in 'Esc does nothing while a com')",
    ),
    (
        "T03 dialog-validity: the close ✕ is hidden until the form is valid",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + "; the close ✕ is hidden until the form is valid"),
        "R-14 dialog-validity: exit gated ('hidden' in 'the close ✕ is hidden until ')",
    ),
    (
        "T04 dialog-validity: Both are switched off until the form is valid",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + " · Both are switched off until the form is valid"),
        "R-14 dialog-validity: exit gated ('switched off' in 'Both are switched off until ')",
    ),
    (
        "T05 dialog-validity: Esc has no effect until the form is valid",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + "; Esc has no effect until the form is valid"),
        "R-14 dialog-validity: exit gated ('has no effect' in 'Esc has no effect until the ')",
    ),
    (
        "T06 confirm-vacuum: all three inactive until the confirm closes",
        _sub(CVF, CT, EXITS_T1, EXITS_T1 + ", all three inactive until the confirm closes"),
        "R-14 confirm-vacuum: exit gated ('inactive' in 'exits Cancel, Esc and the cl')",
    ),
    (
        "T07 per-symbol: a Row total column",
        _sub(
            "TIER/per-symbol",
            SH,
            "Share of budget / Pinned",
            "Share of budget / Pinned / Row total",
        ),
        "R-12 per-symbol: Row total without its caption (D04-G3)",
    ),
    (
        "T08 per-symbol: a Total rows column",
        _sub(
            "TIER/per-symbol",
            SH,
            "Share of budget / Pinned",
            "Share of budget / Pinned / Total rows",
        ),
        "R-12 per-symbol: Total rows without its caption (D04-G3)",
    ),
    (
        "T09 §9 Owner row: Postgres can be vacuumed from the maintenance card",
        lambda s: _line_sub(
            s,
            "| Owner  ",
            "without a typed field",
            "without a typed field; Postgres can be vacuumed from the maintenance card",
        ),
        "R-12 §9 table (Owner): vacuum presented as shipped ('vacuumed') without its caption (D04-G",
    ),
    (
        "T10 §14 compact.button: a Vacuum Postgres string without the ellipsis",
        lambda s: _deck_edit(
            s,
            "storage.compact.button",
            '"Compact Parquet…"',
            '"Compact Parquet…" · "Vacuum Postgres"',
        ),
        "R-12 §14 table (storage.compact.button): vacuum presented as shipped ('Vacuum') without it",
    ),
    (
        "T11 PURGE/entry-points: the typed field starting with BTCUSDT",
        _sub(PEP, SH, "the typed field empty", "the typed field starting with BTCUSDT"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('starting with BTCUSDT')",
    ),
    (
        "T12 PURGE/entry-points: the typed field opening with BTCUSDT",
        _sub(PEP, SH, "the typed field empty", "the typed field opening with BTCUSDT"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('opening with BTCUSDT')",
    ),
    (
        "T13 PURGE/entry-points: the confirm box arriving with BTCUSDT",
        _sub(PEP, SH, "the typed field empty", "the confirm box arriving with BTCUSDT"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('arriving with BTCUSDT')",
    ),
    (
        "T14 PURGE/entry-points: the field comes with BTCUSDT",
        _sub(PEP, SH, "the typed field empty", "the field comes with BTCUSDT"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('field comes with BTCUSDT')",
    ),
    (
        "T15 §7 prose: The typed field shows ETHUSDT.",
        _para_add(P07, "The typed field shows ETHUSDT."),
        "R-7 §7 prose: typed field pre-filled ('typed field shows ETHUSDT')",
    ),
    (
        "T16 TIER/parquet: Purge data… opens §6.5 as a slim confirm, no typing",
        _sub(
            "TIER/parquet",
            CT,
            "Purge data… (T1, opens E16-D02 §6.5)",
            "Purge data… (T1, opens E16-D02 §6.5 as a slim confirm, no typing)",
        ),
        "R-21 parquet: a second purge shape ('slim confirm')",
    ),
    (
        "T17 §7 prose: purge goes straight to the step-up with no symbol to type",
        _para_add(
            P07,
            "From the per-symbol popover, purge goes straight to the step-up with no symbol to type.",
        ),
        "R-21 §7 prose: a second purge shape ('straight to the step-up')",
    ),
    (
        "T18 strip-running: 60 s polling",
        _sub(SRN, SH, "2 s polling", "60 s polling"),
        "R-17 JOB/strip-running: the strip poll reads 60, not the tool's 2",
    ),
    (
        "T19 low-disk-warning: the Producer's 1,800.0 GB (level 2's)",
        _sub(LDW, COL["producer"], "1,610.0 GB of 2,000.0 GB", "1,800.0 GB of 2,000.0 GB"),
        "R-17 SCR-142/low-disk-warning: the level bytes reads 1800.0 GB · 2000.0 GB, not the tool's",
    ),
    (
        "T20 autostop: Trading halts; recording pauses later.",
        _dot("SCR-142/autostop", SH, "Trading halts; recording pauses later."),
        "R-5 autostop: degradation order trading first ('Trading halts; recording pauses later.')",
    ),
    (
        "T21 §1.4: Trading is hit first; recording follows.",
        _para_add(P14, "Trading is hit first; recording follows."),
        "R-5 §1.4 prose: degradation order trading first ('Trading is hit first; recording follows.",
    ),
    (
        "T22 low-disk-warning: positions close out, and then recording pauses",
        _dot(LDW, SH, "positions close out, and then recording pauses"),
        "R-5 low-disk-warning: degradation order trading first ('positions close out, and then reco",
    ),
    # ---- this fold's own variants (U01-U30): the same five classes in words the probes did not try
    (
        "U01 confirm-compact: the close ✕ is ignored while the confirm is open",
        _sub(CCF, CT, EXITS_T1, EXITS_T1 + "; the close ✕ is ignored while the confirm is open"),
        "R-14 confirm-compact: exit gated ('ignored' in 'the close ✕ is ignored while')",
    ),
    (
        "U02 dialog-validity: Esc is swallowed until the form is valid",
        _sub(PDV, CT, EXITS_T1, EXITS_T1 + " · Esc is swallowed until the form is valid"),
        "R-14 dialog-validity: exit gated ('swallowed' in 'Esc is swallowed until the f')",
    ),
    (
        "U03 pinned-refused: Cancel suppressed after the refusal",
        _dot("PURGE/pinned-refused", CT, "Cancel is suppressed after the refusal"),
        "R-14 pinned-refused: exit gated ('suppressed' in 'Cancel is suppressed after t')",
    ),
    (
        "U04 step-up: the close ✕ removed while the code is checked",
        _sub(
            "PURGE/step-up",
            CT,
            "the dialog keeps its inputs",
            "the dialog keeps its inputs; the close ✕ removed while the code is checked",
        ),
        "R-14 step-up: exit gated ('removed' in 'the close ✕ removed while th')",
    ),
    (
        "U05 view-as: the links turned off while viewing as",
        _sub(VAS, CT, LINKS_T1, LINKS_T1 + " · They are turned off while viewing as."),
        "R-14 view-as: exit gated ('turned off' in 'They are turned off while vi')",
    ),
    (
        "U06 per-symbol: a Tallied rows column",
        _sub(
            "TIER/per-symbol",
            SH,
            "Share of budget / Pinned",
            "Share of budget / Pinned / Tallied rows",
        ),
        "R-12 per-symbol: Tallied rows without its caption (D04-G3)",
    ),
    (
        "U07 per-symbol: a row tally per symbol",
        _dot("TIER/per-symbol", SH, "a row tally per symbol"),
        "R-12 per-symbol: row tally without its caption (D04-G3)",
    ),
    (
        "U08 §6 prose: Postgres is vacuumed weekly",
        _para_add(P06, "Postgres is vacuumed weekly."),
        "R-12 §6 prose: vacuum presented as shipped ('vacuumed') without its caption (D04-G8)",
    ),
    (
        "U09 §4 prose: the number of rows per table",
        _para_add(P04, "Each card lists the number of rows per table."),
        "R-12 §4 prose: row counts presented as shipped ('number of rows') without its caption (D04",
    ),
    (
        "U10 strip-running: stopping the compaction",
        _dot(SRN, CT, "stopping the compaction is one press away"),
        "R-12 strip-running: stopping the compaction without its caption (D04-G10)",
    ),
    (
        "U11 §4 prose: query latency on each card",
        _para_add(P04, "Each card shows its query latency."),
        "R-12 §4 prose: slow queries presented as shipped ('query latency') without its caption (D0",
    ),
    (
        "U12 TIER/questdb: QuestDB's growth trend",
        _dot("TIER/questdb", SH, "QuestDB's growth trend beside the size"),
        "R-12 questdb: QuestDB's growth without its caption (D04-G1)",
    ),
    (
        "U13 §5 prose: the ingestion lagging behind",
        _para_add(P05, "The banner says ingestion is lagging behind."),
        "R-12 §5 prose: lag presented as shipped ('lagging') without its caption (D04-G4)",
    ),
    (
        "U14 §5 prose: migrations pending on the Postgres card",
        _para_add(P05, "The Postgres card lists migrations pending."),
        "R-12 §5 prose: migration presented as shipped ('migrations pending') without its caption (",
    ),
    (
        "U15 per-symbol: a history chart per row",
        _dot("TIER/per-symbol", SH, "a history chart per row"),
        "R-12 per-symbol: history chart without its caption (D04-G2)",
    ),
    (
        "U16 PURGE/dialog: the typed field displaying ETHUSDT",
        _sub(PDL, SH, "empty, never pre-filled", "displaying ETHUSDT"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled ('Type the symbol to confirm (CMP-007): displa",
    ),
    (
        "U17 §7 prose: the confirm field bears {symbol}",
        _para_add(P07, "The confirm field bears {symbol} when it opens."),
        "R-7 §7 prose: typed field pre-filled ('confirm field bears {symbol')",
    ),
    (
        "U18 PURGE/entry-points: the typed field loaded with BTCUSDT",
        _sub(PEP, SH, "the typed field empty", "the typed field loaded with BTCUSDT"),
        "R-7 PURGE/entry-points: confirm_symbol pre-filled ('loaded with BTCUSDT')",
    ),
    (
        "U19 §7 prose: from a symbol row, purge runs without typing",
        _para_add(P07, "From a symbol row, purge runs without typing."),
        "R-21 §7 prose: a second purge shape ('without typing')",
    ),
    (
        "U20 TIER/questdb: Purge data… with nothing to type",
        _sub(
            "TIER/questdb",
            CT,
            "Purge data… (T1, opens E16-D02 §6.5)",
            "Purge data… (T1, opens E16-D02 §6.5, nothing to type)",
        ),
        "R-21 questdb: a second purge shape ('nothing to type')",
    ),
    (
        "U21 §4 prose: the popover's Purge… bypasses the typed confirm",
        _para_add(P04, "The popover's Purge… bypasses the typed confirm."),
        "R-21 §4 prose: a second purge shape ('bypasses the typed confirm')",
    ),
    (
        "U22 healthy: the stamp every 30 s",
        _sub("SCR-142/healthy", SH, "(every 60 s)", "(every 30 s)"),
        "R-17 SCR-142/healthy: the sample interval reads 30, not the tool's 60",
    ),
    (
        "U23 autostop: the Producer's 1,900.0 GB (level 3's)",
        _sub("SCR-142/autostop", COL["producer"], "1,800.0 GB", "1,900.0 GB"),
        "R-17 SCR-142/autostop: the level bytes reads 1900.0 GB, not the tool's 1800.0 GB",
    ),
    (
        "U24 IMPORT/form: at most 365 days",
        _sub("IMPORT/form", SH, "at most 366 days", "at most 365 days"),
        "R-17 IMPORT/form: the import cap reads 365, not the tool's 366",
    ),
    (
        "U25 dialog-validity: opacity 0.38",
        _sub(PDV, SH, "`opacity.disabled` 0.45", "`opacity.disabled` 0.38"),
        "R-17 PURGE/dialog-validity: the validity opacity reads 0.38, not the tool's 0.45",
    ),
    (
        "U26 stale-sample: more than 3 × 60 s",
        _sub("SCR-142/stale-sample", COL["producer"], "more than 2 × 60 s", "more than 3 × 60 s"),
        "R-17 SCR-142/stale-sample: the stale rule reads 3 · 60, not the tool's 2 · 60",
    ),
    (
        "U27 read-only-disk-full: order entry stops, and only later the recorder",
        _dot(ROD, SH, "Order entry stops, and only later does the recorder pause."),
        "R-5 read-only-disk-full: degradation order trading first ('Order entry stops, and only lat",
    ),
    (
        "U28 §1.4: the OMS suspended before capture stops",
        _para_add(P14, "The OMS is suspended before capture stops."),
        "R-5 §1.4 prose: degradation order trading first ('The OMS is suspended before capture stop",
    ),
    (
        "U29 autostop: orders rejected as recording pauses",
        _dot("SCR-142/autostop", SH, "Orders are rejected as recording pauses."),
        "R-5 autostop: degradation order at the same time ('Orders are rejected as recording pauses",
    ),
    (
        "U30 §5 prose: positions flattened, then the recorder stops",
        _para_add(P05, "Positions are flattened; then the recorder stops."),
        "R-5 §5 prose: degradation order trading first ('Positions are flattened; then the recorder",
    ),
    # X01-X16: the orchestrator's gate re-check 2's slipped forms, verbatim, each in the ruled unit the record
    # names; the default-deny pin (R-23) refuses each as a changed pinned unit
    (
        "X01 JOB/strip-running: Back is dormant until the job ends",
        _dot(SRN, CT, "Back is dormant until the job ends"),
        "R-23 §6 frame JOB/strip-running: a pinned unit changed",
    ),
    (
        "X02 TIER/parquet: Esc falls on deaf ears",
        _dot("TIER/parquet", CT, "Esc falls on deaf ears"),
        "R-23 §4 frame TIER/parquet: a pinned unit changed",
    ),
    (
        "X03 §4 prose: the per-symbol table adds a per-symbol tally",
        _para_add(P04, "The per-symbol table adds a per-symbol tally."),
        "R-23 §4 prose: a pinned unit changed",
    ),
    (
        "X04 §4 prose: each tier card shows its record count",
        _para_add(P04, "Each tier card shows its record count."),
        "R-23 §4 prose: a pinned unit changed",
    ),
    (
        "X05 sketch: an End button per job",
        lambda s: _first(
            s,
            "jobs strip: (empty at rest)    ",
            "jobs strip: (empty at rest); an End button per job",
        ),
        "R-23 §2 sketch: a pinned unit changed",
    ),
    (
        "X06 PURGE/entry-points: the symbol is already waiting in the box (replacing the empty field)",
        _sub(PEP, SH, "the typed field empty", "the symbol is already waiting in the box"),
        "R-23 §7 frame PURGE/entry-points: a pinned unit changed",
    ),
    (
        "X07 §7 prose: ETHUSDT sits in the field when it opens",
        _para_add(P07, "ETHUSDT sits in the field when it opens."),
        "R-23 §7 prose: a pinned unit changed",
    ),
    (
        "X08 §1.4 prose: first the orders, afterwards the recorder",
        _para_add(P14, "Under pressure it is first the orders, afterwards the recorder."),
        "R-23 §1.4 prose: a pinned unit changed",
    ),
    (
        "X09 TIER/parquet: Esc is dormant",
        _dot("TIER/parquet", CT, "Esc is dormant until the job ends"),
        "R-23 §4 frame TIER/parquet: a pinned unit changed",
    ),
    (
        "X10 confirm-compact: Esc goes unheeded",
        _dot(CCF, CT, "Esc goes unheeded"),
        "R-23 §6 frame JOB/confirm-compact: a pinned unit changed",
    ),
    (
        "X11 confirm-compact: ; Cancel stays asleep",
        _append(CCF, CT, "Cancel stays asleep until the job ends"),
        "R-23 §6 frame JOB/confirm-compact: a pinned unit changed",
    ),
    (
        "X12 PURGE/entry-points: the symbol is already waiting in the box (after the empty field)",
        _sub(
            PEP,
            SH,
            "the typed field empty",
            "the typed field empty, the symbol is already waiting in the box",
        ),
        "R-23 §7 frame PURGE/entry-points: a pinned unit changed",
    ),
    (
        "X13 PURGE/dialog: ETHUSDT sits in the typed field",
        _dot(PDL, SH, "ETHUSDT sits in the typed field when it opens"),
        "R-23 §7 frame PURGE/dialog: a pinned unit changed",
    ),
    (
        "X14 PURGE/entry-points: BTCUSDT already waiting in the typed field",
        _dot(PEP, SH, "BTCUSDT already waiting in the typed field"),
        "R-23 §7 frame PURGE/entry-points: a pinned unit changed",
    ),
    (
        "X15 §1.4 prose: It stops first the orders, afterwards the recorder",
        _para_add(P14, "It stops first the orders, afterwards the recorder."),
        "R-23 §1.4 prose: a pinned unit changed",
    ),
    (
        "X16 §3 prose: level 1's bytes swapped for the registered 1,800.0 GB",
        lambda s: _first(s, "level 1 at 80.5 % (1,610.0 GB;", "level 1 at 80.5 % (1,800.0 GB;"),
        "R-23 §3 prose: a pinned unit changed",
    ),
    # Y01-Y10: own paraphrases across the pinned classes (Y03-Y05 a vocabulary gate reads first; R-23 beside)
    (
        "Y01 unavailable: Retry naps while the sample loads",
        _dot("SCR-142/unavailable", CT, "Retry naps while the sample loads"),
        "R-23 §5 frame SCR-142/unavailable: a pinned unit changed",
    ),
    (
        "Y02 view-as: the links sit idle while viewing as",
        _dot(VAS, SH, "the links sit idle while viewing as"),
        "R-23 §5 frame SCR-142/view-as: a pinned unit changed",
    ),
    (
        "Y03 §4 prose: each card keeps a running tally of rows",
        _para_add(P04, "Each card keeps a running tally of rows."),
        "R-12 §4 prose: row counts presented as shipped ('tally of rows')",
    ),
    (
        "Y04 §6 table: the symbol arrives typed for you",
        lambda s: _line_sub(
            s,
            "| Purge data ",
            "reused whole (§7)",
            "reused whole (§7), the symbol arrives typed for you",
        ),
        "R-7 §6 table (Purge data): typed field pre-filled ('typed for you')",
    ),
    (
        "Y05 autostop: the order book closes ahead of the recorder",
        _dot("SCR-142/autostop", SH, "the order book closes ahead of the recorder"),
        "R-5 autostop: degradation order trading first ('the order book closes ahead",
    ),
    (
        "Y06 §9 view-as row: Esc rests",
        lambda s: _line_sub(
            s,
            "| Owner viewing as another user",
            "exits and links enabled",
            "exits and links enabled, Esc rests",
        ),
        "R-23 §9 row Owner viewing as another user: a pinned unit changed",
    ),
    (
        "Y07 §6 prose: each job line offers a halt control",
        _para_add(P06, "Each job line offers a halt control."),
        "R-23 §6 prose: a pinned unit changed",
    ),
    (
        "Y08 sketch: [ Halt ] beside the jobs strip",
        lambda s: _first(
            s, "jobs strip: (empty at rest)    ", "jobs strip: (empty at rest) [ Halt ]"
        ),
        "R-23 §2 sketch: a pinned unit changed",
    ),
    (
        "Y09 §13 D04-CG3: 813.6 GB swapped for the registered 812.3 GB",
        lambda s: _line_sub(s, "| D04-CG3", "813.6 GB", "812.3 GB"),
        "R-23 §13 row D04-CG3: a pinned unit changed",
    ),
    (
        "Y10 PURGE/step-up: the code box comes filled",
        _dot("PURGE/step-up", SH, "the code box comes filled"),
        "R-23 §7 frame PURGE/step-up: a pinned unit changed",
    ),
    # Z01-Z27: R-23 by its own kinds (changed, moved, duplicated, missing, a unit or a region the pins do not hold)
    # over the unit classes, each R-23's only FAIL; a frame row's copy or deletion is the inventory's (R-18)
    (
        "Z01 frame changed: SCR-142/loading reworded",
        _sub("SCR-142/loading", SH, "skeleton meters and cards", "skeleton meters and the cards"),
        "R-23 §5 frame SCR-142/loading: a pinned unit changed",
    ),
    (
        "Z02 frame moved: SCR-142/loading above SCR-142/stale-sample",
        _move_line("| `SCR-142/loading`", "| `SCR-142/stale-sample`"),
        "R-23 §5 frame SCR-142/loading: a pinned unit changed (table, lines reordered)",
    ),
    (
        "Z03 ruled changed: §7 prose Owner-only reworded",
        lambda s: _line_sub(s, P07, "Owner-only", "Owner only"),
        "R-23 §7 prose: a pinned unit changed",
    ),
    (
        "Z04 ruled moved: §6's Who may run them paragraph moved to §17",
        _move_line(P06, "## 18."),
        "R-23 §17 prose: a pinned unit moved here from §6 prose",
    ),
    (
        "Z05 ruled duplicated: §9's Manager / Viewer row twice",
        _dup_line("| Manager / Viewer"),
        "R-23 §9 row Manager / Viewer: a pinned unit changed (table, a line duplicated)",
    ),
    (
        "Z06 ruled missing: §9's Owner row deleted",
        _del_line("| Owner  "),
        "R-23 §9 row Owner: a pinned unit changed (table, a line removed)",
    ),
    (
        "Z07 caption changed: the deck's storage.title source reworded",
        lambda s: _deck_edit(s, "storage.title", "(the heading,", "(the page heading,"),
        "R-23 §14 row storage.title: a pinned unit changed",
    ),
    (
        "Z08 caption moved: the sketch's footnote ⁴ above ³",
        _move_line("⁴ PROPOSED", "³ PROPOSED"),
        "R-23 §2 sketch: a pinned unit changed (sketch, lines reordered)",
    ),
    (
        "Z09 caption duplicated: the sketch's tier header line twice",
        _dup_line("| (c) [QuestDB"),
        "R-23 §2 sketch: a pinned unit changed (sketch, a line duplicated)",
    ),
    (
        "Z10 caption missing: the sketch's archive-derived line deleted",
        _del_line("|     Archive-derived"),
        "R-23 §2 sketch: a pinned unit changed (sketch, a line removed)",
    ),
    (
        "Z11 degradation changed: §16's low-disk row reworded",
        lambda s: _line_sub(s, "| 14:2780 low-disk", "drawn with", "drawn, with"),
        "R-23 §16 row 14:2780 low-disk warning and critical st: a pinned unit changed",
    ),
    (
        "Z12 view-as moved: BQ-8 below BQ-9",
        _move_line("| BQ-8 ", "| BQ-10 "),
        "R-23 BQ row BQ-9: a pinned unit changed (table, lines reordered)",
    ),
    (
        "Z13 purge duplicated: §2's per-symbol row (e) twice",
        _dup_line("| (e) "),
        "R-23 §2 row (e): a pinned unit changed (table, a line duplicated)",
    ),
    (
        "Z14 PROPOSED missing: §1.1's purpose paragraph deleted",
        _del_line(P11),
        "R-23 §1.1 prose: a pinned unit is missing",
    ),
    (
        "Z15 number missing: the header's Key paragraph deleted",
        _del_line("**Key.**"),
        "R-23 header prose: a pinned unit is missing",
    ),
    (
        "Z16 view-as duplicated: the BQ conditions paragraph twice",
        _dup_line("**Conditions (RULED"),
        "R-23 BQ prose: a pinned unit changed (paragraph, a line duplicated)",
    ),
    (
        "Z17 view-as missing: §15's theme paragraph deleted",
        _del_line("Dark / light / high-contrast = "),
        "R-23 §15 prose: a pinned unit is missing",
    ),
    (
        "Z18 unpinned: a new paragraph in the ruled §7",
        _new_para(P07, "The dialog is the same on every entry point."),
        "R-23 §7 prose: a unit the pins do not hold (paragraph)",
    ),
    (
        "Z19 unpinned: a new PROPOSED paragraph in §17",
        _new_para("## 18.", f"The history line waits, {cap(2)}."),
        "R-23 §17 prose: a unit the pins do not hold (paragraph): 'The history",
    ),
    (
        "Z20 unpinned: a neutral clause on §1.3's classification line (a fresh twin before the fold)",
        _para_add(
            "**The classification (every state row", "Each class reads the same on every board."
        ),
        "R-23 §1.3 prose: a pinned unit changed (paragraph, a line edited)",
    ),
    (
        "Z21 unpinned: a fresh note in its own §17 paragraph (a fresh twin before the fold)",
        _new_para("## 18.", "The walkthrough reads the frames in board order."),
        "R-23 §17 prose: a unit the pins do not hold (paragraph)",
    ),
    (
        "Z22 unpinned: the header's Penpot page line gains a sentence (a fresh twin before the fold)",
        _para_add("**Penpot page:**", "The page name stays as written."),
        "R-23 header prose: a pinned unit changed (paragraph, a line edited)",
    ),
    (
        "Z23 region: §1.3's heading repeated with a new paragraph under it",
        _new_para("### 1.4 ", "### 1.3 The rules, stated once\n\nThe rules again, in brief."),
        "R-23 §1 › §1.3#2: a heading repeated, a region the pins do not hold",
    ),
    (
        "Z24 region: §11's heading reworded",
        lambda s: _first(s, "## 11. Tokens and redlines", "## 11. Tokens and the redlines"),
        "R-23 §11 heading: a pinned unit changed (heading, a line edited)",
    ),
    (
        "Z25 unit duplicated: §17's flows paragraph copied as its own block before §18",
        lambda s: _new_para(
            "## 18.", "**Flows (every step a frame).** 5 <!-- audit:flows=5 --> flows."
        )(s),
        "R-23 §17 prose: a pinned unit duplicated (paragraph)",
    ),
    (
        "Z26 unit order: §10's Initial focus and Announcements paragraphs swapped",
        lambda s: _swap_rows(s, "**Initial focus**", "**Announcements**"),
        "R-23 §10 prose: a pinned unit moved out of its pinned order",
    ),
    (
        "Z27 region renamed: §1.1's heading id changed",
        lambda s: _first(s, "### 1.1 Purpose", "### 1.9 Purpose"),
        "R-23 §1 › §1.9#1: a heading changed",
    ),
    # S01-S15: the orchestrator's gate re-check 3's passing forms, verbatim, in the record's places
    (
        "S01 §10 Esc row: while a job runs Esc goes unheeded",
        lambda s: _line_sub(
            s,
            "| `Esc`  ",
            "Cancel; focus returns to the opener",
            "Cancel; focus returns to the opener; while a job runs Esc goes unheeded",
        ),
        "R-23 §10 row Esc: a pinned unit changed (table, a line edited)",
    ),
    (
        "S02 §1.3 exits row: Retry lies dormant while the tier is down",
        lambda s: _line_sub(
            s,
            "| exits and links:",
            "never gated for any role (A3)",
            "never gated for any role (A3); Retry lies dormant while the tier is down",
        ),
        "R-23 §1.3 row exits and links: Cancel, Esc and the clo: a pinned unit changed",
    ),
    (
        "S03 §16 per-symbol row: Record count from symbols[]",
        lambda s: _line_sub(
            s,
            "| 14:2780 per-symbol",
            "/ Pinned from `symbols[]`",
            "/ Pinned / Record count from `symbols[]`",
        ),
        "R-23 §16 row 14:2780 per-symbol breakdown for the hot: a pinned unit changed",
    ),
    (
        "S04 §2 (c): a per-tier tally of records",
        lambda s: _line_sub(
            s, "| (c)    |", "the rows of §4;", "the rows of §4 and a per-tier tally of records;"
        ),
        "R-23 §2 row (c): a pinned unit changed (table, a line edited)",
    ),
    (
        "S05 §17 F3: an End button on the strip ends it early",
        lambda s: _line_sub(
            s,
            "| F3 ",
            "→ `JOB/strip-running` →",
            "→ `JOB/strip-running` (an End button on the strip ends it early) →",
        ),
        "R-23 §17 row F3: a pinned unit changed (table, a line edited)",
    ),
    (
        "S06 §1.2 destructive-change row: the symbol already waiting in the box",
        lambda s: _line_sub(
            s,
            "| the destructive-change pattern",
            "typed confirm carrying the consequence",
            "typed confirm, the symbol already waiting in the box, carrying the consequence",
        ),
        "R-23 §1.2 row the destructive-change pattern: a pinned unit changed",
    ),
    (
        "S07 §3 per-symbol row: a row's symbol sits in the typed field once its confirm opens",
        lambda s: _line_sub(
            s,
            "| the per-symbol table ",
            "(`22` :19224–19232)",
            "(`22` :19224–19232); a row's symbol sits in the typed field once its confirm opens",
        ),
        "R-23 §3 row the per-symbol table: a pinned unit changed (table, a line edited)",
    ),
    (
        "S08 §1.3 A3 paragraph: a soft-wrapped line under it",
        _soft_wrap("**Status · outcome · absence", "Retry lies dormant while the tier is down."),
        "R-23 §1.3 prose: a pinned unit changed (paragraph, a line added)",
    ),
    (
        "S09 §2 BQ-6 paragraph: a soft-wrapped line under it",
        _soft_wrap(
            "A section of `/admin/recorder` (BQ-6", "Each tier card shows its record count."
        ),
        "R-23 §2 prose: a pinned unit changed (paragraph, a line added)",
    ),
    (
        "S10 §10: a new paragraph with the M2 forms",
        _new_para(
            "**Announcements**", "While a job runs, Esc goes unheeded and Retry lies dormant."
        ),
        "R-23 §10 prose: a unit the pins do not hold (paragraph)",
    ),
    (
        "S11 §16: a new paragraph with the M3 forms",
        _new_para(
            "AC 3 is traced the same way",
            "Each tier card shows its record count; an End button on the strip ends it early.",
        ),
        "R-23 §16 prose: a unit the pins do not hold (paragraph)",
    ),
    (
        "S12 §13 D04-D7: first the trades, afterwards the capture",
        lambda s: _line_sub(
            s,
            "| D04-D7 ",
            "(alternative rejected: a tooltip)",
            "(alternative rejected: a tooltip); first the trades, afterwards the capture",
        ),
        "R-23 §13 row D04-D7: a pinned unit changed (table, a line edited)",
    ),
    (
        "S13 §10 paragraph: first the trades, afterwards the capture",
        _new_para("| Key  ", "Under pressure it is first the trades, afterwards the capture."),
        "R-23 §10 prose: a unit the pins do not hold (paragraph): 'Under",
    ),
    (
        "S14 BQ-12 rewritten: a CMP-044 standard dialog confirms the import",
        lambda s: _line_sub(
            s,
            "| BQ-12 ",
            "no dialog: the card form + one consequence line is the confirm (additive, resumable);"
            " the CMP-044 standard alternative is D04-Q3",
            "a CMP-044 standard dialog confirms the import",
        ),
        "R-23 BQ row BQ-12: a pinned unit changed (table, a line edited)",
    ),
    (
        "S15 BQ-15 rewritten: a page-level CMP-028 strip above the cards",
        lambda s: _line_sub(
            s,
            "| BQ-15 ",
            "per-card CMP-027 inline with Retry (re-poll)",
            "a page-level CMP-028 strip above the cards",
        ),
        "R-23 BQ row BQ-15: a pinned unit changed (table, a line edited)",
    ),
    # W01-W12: own paraphrases of M2 / M3 / M4 / M6, each in a unit no pin held before this fold
    (
        "W01 M2 §1.3 Manager / Viewer row: Cancel slumbers",
        lambda s: _line_sub(
            s,
            "| a Manager or a Viewer",
            "the server is the control (C-12.4)",
            "the server is the control (C-12.4); Cancel slumbers for them",
        ),
        "R-23 §1.3 row a Manager or a Viewer: a pinned unit changed",
    ),
    (
        "W02 M2 §10 From / To row: Esc sits idle here",
        lambda s: _line_sub(
            s,
            "| `Enter`    ",
            "on Import archives: submit",
            "on Import archives: submit; Esc sits idle here",
        ),
        "R-23 §10 row Enter: a pinned unit changed (table, a line edited)",
    ),
    (
        "W03 M2 BQ-15: Retry naps until the tier answers",
        lambda s: _line_sub(
            s,
            "| BQ-15 ",
            "the page stays usable",
            "the page stays usable; its Retry naps until the tier answers",
        ),
        "R-23 BQ row BQ-15: a pinned unit changed (table, a line edited): '…age stays usable",
    ),
    (
        "W04 M3 §13 D04-D1: each meter shows its record total",
        lambda s: _line_sub(
            s,
            "| D04-D1 ",
            "(alternative rejected: one meter with a second scale)",
            "(alternative rejected: one meter with a second scale); each meter shows its record total",
        ),
        "R-23 §13 row D04-D1: a pinned unit changed (table, a line edited)",
    ),
    (
        "W05 M3 §11 jobs strip row: a Halt button on each job line",
        lambda s: _line_sub(
            s,
            "| the jobs strip ",
            "`space.stack.xs`",
            "`space.stack.xs`; a Halt button on each job line",
        ),
        "R-23 §11 row the jobs strip: a pinned unit changed (table, a line edited)",
    ),
    (
        "W06 M3 BQ-20: the import card counts every record it wrote",
        lambda s: _line_sub(
            s,
            "| BQ-20 ",
            "a C-row (D04-C1, owner `14`)",
            "a C-row (D04-C1, owner `14`); the import card counts every record it wrote",
        ),
        "R-23 BQ row BQ-20: a pinned unit changed (table, a line edited)",
    ),
    (
        "W07 M4 §3 headline row: the row's symbol lies ready in the box",
        lambda s: _line_sub(
            s,
            "| the headline, the gate,",
            "E16-D02 §8.3's grammar",
            "E16-D02 §8.3's grammar; the row's symbol lies ready in the box when its confirm opens",
        ),
        "R-23 §3 row the headline, the gate, the suggested ac: a pinned unit changed",
    ),
    (
        "W08 M4 BQ-5: the confirm box comes stocked with the row's symbol",
        lambda s: _line_sub(
            s,
            "| BQ-5 ",
            "never a workspace URL",
            "never a workspace URL; the confirm box comes stocked with the row's symbol",
        ),
        "R-23 BQ row BQ-5: a pinned unit changed (table, a line edited)",
    ),
    (
        "W09 M4 §17 F2: ETHUSDT already rests in the box",
        lambda s: _line_sub(
            s,
            "| F2 ",
            "with every action still enabled",
            "with every action still enabled; ETHUSDT already rests in the box when the confirm opens",
        ),
        "R-23 §17 row F2: a pinned unit changed (table, a line edited)",
    ),
    (
        "W10 M6 §13 D04-D8: the dealing stops first, the taping later",
        lambda s: _line_sub(
            s,
            "| D04-D8 ",
            "(BQ-17 RULED)",
            "(BQ-17 RULED); under strain the dealing stops first, the taping later",
        ),
        "R-23 §13 row D04-D8: a pinned unit changed (table, a line edited)",
    ),
    (
        "W11 M6 §2 (c): the dealing yields before the taping does",
        lambda s: _line_sub(
            s,
            "| (c)    |",
            "with a CMP-027 inline error and Retry",
            "with a CMP-027 inline error and Retry; past the warn step the dealing yields before"
            " the taping does",
        ),
        "R-23 §2 row (c): a pinned unit changed (table, a line edited): '… error and Retry",
    ),
    (
        "W12 M6 §16 tier-unreachable row: the desk shuts ahead of the tape",
        lambda s: _line_sub(
            s,
            "| 14:2780 error state when a tier",
            "the page usable (R-4)",
            "the page usable (R-4); when space runs out the desk shuts ahead of the tape",
        ),
        "R-23 §16 row 14:2780 error state when a tier is unrea: a pinned unit changed",
    ),
    # Q01-Q02: the orchestrator's gate re-check 4's Major: the sketch's columns are content
    (
        "Q01 sketch: [ Purge data… ] shifted by spaces onto the Postgres card's column",
        lambda s: _sketch_shift(s, 55),
        "R-23 §2 sketch: a pinned unit changed (sketch, a line edited)",
    ),
    (
        "Q02 sketch: [ Purge data… ] shifted by spaces off the Parquet card's column",
        lambda s: _sketch_shift(s, 20),
        "R-23 §2 sketch: a pinned unit changed (sketch, a line edited)",
    ),
    (
        "Q03 header prose: a `~` written before a marked number (it was masked with the number)",
        lambda s: _first(
            s,
            "about 560 <!-- audit:fixture.runway_days",
            "about ~560 <!-- audit:fixture.runway_days",
        ),
        "R-23 header prose: a pinned unit changed (paragraph, a line edited)",
    ),
]
# Valid twins: each must raise nothing (a captioned inset line, the gap's own G-row, a negated mention).
VALID: list[tuple[str, Callable[[str], str]]] = [
    (
        "V01 §1.1 prose: the Vacuum button in a captioned inset",
        _para_add(P11, f"The Vacuum button sits in an inset beside Compact now, {cap(8)}."),
    ),
    (
        "V02 D04-G8: the G-row itself names the Vacuum button beside Compact",
        lambda s: _line_sub(
            s,
            "| D04-G8 ",
            "`POST /admin/db/vacuum`",
            "`POST /admin/db/vacuum` (the Vacuum button beside Compact)",
        ),
    ),
    (
        "V03 §1.1 prose: no Vacuum control on the shipped card",
        _para_add(P11, "There is no Vacuum control on the shipped card."),
    ),
    (
        "V04 confirm-compact: the exit Cancel named again, never locked",
        _append("JOB/confirm-compact", CT, "Cancel / Esc close the dialog, never locked"),
    ),
    (
        "V05 PURGE/dialog: the typed field is never set to the symbol",
        _append(PDL, SH, "the typed field is never set to the symbol"),
    ),
    (
        "V06 §6 prose: Stop job captioned",
        _para_add(P06, f"Stop job sits on each job line, {cap(10)}."),
    ),
    (
        "V07 low-disk-warning: the ruled order reworded",
        _sub(
            "SCR-142/low-disk-warning",
            SH,
            '"Recording pauses before trading is affected."',
            '"Trading is affected only after recording pauses."',
        ),
    ),
    (
        "V08 D04-G10: the G-row names the Stop job button",
        lambda s: _line_sub(
            s,
            "| D04-G10 ",
            "`POST /admin/jobs/{jobId}/cancel`",
            "`POST /admin/jobs/{jobId}/cancel` (the Stop job button on each job line)",
        ),
    ),
    (
        "V09 §0 prose: the E16-D05 boards PR PENDING by name",
        lambda s: _first(
            s, PEND, "The E16-D05 boards PR #4501 stays PENDING by name only. " + PEND
        ),
    ),
    (
        "V10 §8 prose: the per-file table captioned",
        _para_add(P08, f"The per-file table is an inset, {cap(11)}."),
    ),
    (
        "V11 §7 prose: the typed field starts empty and the Owner types the symbol",
        _para_add(P07, "The typed field starts empty; the Owner types the symbol."),
    ),
    (
        "V12 low-disk-warning: the ruled order as 'First … then'",
        _sub(
            LDW,
            SH,
            '"Recording pauses before trading is affected."',
            '"First recording pauses; then trading is affected."',
        ),
    ),
    (
        "V13 autostop: the ruled order as 'first, and only then'",
        _sub(
            "SCR-142/autostop",
            SH,
            '"Recording pauses before trading is affected."',
            '"Recording pauses first, and only then is trading affected."',
        ),
    ),
    (
        "V14 §1.4 prose: the ruled order led by 'Only after'",
        _para_add(P14, "Only after the recorder stops is order entry touched."),
    ),
    (
        "V15 confirm-compact: Esc closes the dialog",
        _dot(CCF, CT, "Esc closes the dialog"),
    ),
    (
        "V16 §4 prose: row totals in a captioned PROPOSED inset",
        _para_add(P04, f"Row totals sit in an inset, {cap(3)}."),
    ),
    (
        "V17 PURGE/dialog: the typed field starts empty",
        _dot(PDL, SH, "the typed field starts empty"),
    ),
    (
        "V18 dialog-validity: the exit Cancel closes the dialog",
        _dot(PDV, CT, "Cancel closes the dialog (T1)"),
    ),
    (
        "V19 §6 prose: the vacuum inset captioned",
        _para_add(P06, f"The vacuum inset is captioned {cap(8)}."),
    ),
    (
        "V20 dialog-validity: Esc is never hidden",
        _dot(PDV, CT, "Esc is never hidden or ignored"),
    ),
    (
        "V21 trailing spaces on a sketch line and a prose line (no pinned text changes)",
        lambda s: _first(
            _first(
                s, "(every 60 s)   [view-as notice]  |\n", "(every 60 s)   [view-as notice]  |  \n"
            ),
            "\n**Penpot page:** ",
            "\n**Penpot page:**  ",
        ),
    ),
]


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def fixture_numbers(fx: dict[str, Any], facts: dict[str, Any]) -> dict[str, object]:
    """The fixture as plain marker values (no spaces): the spec's `audit:fixture.*` keys."""
    ex, t, sy, lv, imp = fx["example"], fx["tiers"], fx["symbols"], fx["levels"], fx["imp"]

    def num(s: str) -> float:
        return float(re.sub(r"[^\d.]", "", s))

    return {
        "sample_date": fx["sample_date"],
        "sample_time": fx["sample_time"],
        "generated_at": fx["sample_date"],
        "disk_total_tb": num(fx["disk_total"]),
        "disk_used_tb": num(fx["disk_used"]),
        "disk_free_tb": num(fx["disk_free"]),
        "volume_pct": num(fx["volume_pct"]),
        "cap_gb": num(fx["cap"]),
        "budget_used_gb": num(fx["budget_used"]),
        "budget_pct": num(fx["budget_pct"]),
        "questdb_gb": num(t["questdb"]["size"]),
        "parquet_gb": num(t["parquet"]["size"]),
        "postgres_gb": num(t["postgres"]["size"]),
        "questdb_share": num(t["questdb"]["share"]),
        "parquet_share": num(t["parquet"]["share"]),
        "retention_questdb": ex["tiers"][0]["retention_days"],
        "retention_parquet": ex["tiers"][1]["retention_days"],
        "growth_gb_day": num(fx["growth"]),
        "runway_days": round(fx["runway_days"]),
        "full_date": fx["full_date"],
        "volume_wall_days": round(fx["volume_wall_days"]),
        "autostop_days": round(fx["autostop_days"]),
        "used30_gb": num(fx["used30"]),
        "btc_gb": num(sy[0]["size"]),
        "btc_mb_day": num(sy[0]["growth"]),
        "btc_share": num(sy[0]["share"]),
        "eth_gb": num(sy[1]["size"]),
        "eth_mb_day": num(sy[1]["growth"]),
        "symbols_sum_gb": num(fx["symbols_sum"]),
        "attributed_pct": num(fx["attributed_pct"]),
        "level1_pct": num(lv["1"]["pct"]),
        "level1_runway": int(re.sub(r"\D", "", lv["1"]["runway_next"])),
        "level2_runway": int(re.sub(r"\D", "", lv["2"]["runway_next"])),
        "warn": facts["disk"]["CV_DISK_WARN_PCT"],
        "autostop": facts["disk"]["CV_DISK_AUTOSTOP_PCT"],
        "halt": facts["disk"]["CV_DISK_HALT_PCT"],
        "every_s": facts["disk"]["CV_DISK_SAMPLE_INTERVAL_S"],
        "stale_after_s": fx["stale_after_s"],
        "stale_age_min": fx["stale_age_s"] // 60,
        "last_good": fx["last_good"].split(" ")[0],
        "backlog_rows": fx["lag"]["backlog_rows"],
        "ingest_rate": int(re.sub(r"\D", "", fx["lag"]["ingest_rate"])),
        "schema_version": fx["migration"]["schema_version"],
        "target_version": fx["migration"]["target_version"],
        "pending": fx["migration"]["pending"],
        "import_days": imp["days"],
        "running_done": imp["running_done"],
        "running_pct": imp["running_pct"],
        "skip_processed": imp["skip_processed"],
        "skip_done": imp["skip_done"],
        "skip_pct": imp["skip_pct"],
        "overlap_rows": int(re.sub(r"\D", "", imp["overlap_rows"])),
        "rows_per_day": int(re.sub(r"\D", "", imp["rows_per_day"])),
        "compact_pct": fx["jobs"]["compact_pct"],
        "merge_mib": facts["compaction"]["merge_mib"],
        "trigger_files": facts["compaction"]["trigger_files"],
        "trigger_mib": facts["compaction"]["trigger_mib"],
        "purge_before": fx["purge"]["before"],
        "purge_from": fx["purge"]["from"],
        "healthy_backlog_rows": fx["lag"]["healthy_backlog_rows"],
        "healthy_pending": fx["migration"]["healthy_pending"],
    }


def numbers_of(
    spec: str,
    facts: dict[str, Any],
    fx: dict[str, Any],
    themes: dict[str, dict[str, object]],
    registered: set[tuple[str, str]],
) -> tuple[dict[str, Any], list[dict[str, object]], list[str], int]:
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
        row: dict[str, object] = {
            "element": element,
            "fg": fg,
            "bg": bg,
            "role": role,
            "verdict": verdict,
        }
        row.update(
            {
                "pairs": "registered" if (fg, bg) in registered else "PROPOSED",
                **{k: round(v, 4) for k, v in ratios.items()},
            }
        )
        matrix.append(row)
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    dark = themes["dark"]
    composite = {}
    for th, tk in themes.items():
        over = resolve(tk, "color.surface.raised")
        composite[th] = round(
            contrast(
                blend(resolve(tk, "color.text.on-action"), over, 0.45),
                blend(resolve(tk, "color.action.primary.default"), over, 0.45),
            ),
            2,
        )
    all_rows = frame_rows(spec)
    n: dict[str, Any] = {}
    n["frames_total"] = len(all_rows) + len(TWINS)
    for fam, key in (
        ("SCR-142/", "frames_scr"),
        ("TIER/", "frames_tier"),
        ("JOB/", "frames_job"),
        ("PURGE/", "frames_purge"),
        ("IMPORT/", "frames_import"),
    ):
        n[key] = sum(name.startswith(fam) for name, _, _ in all_rows)
    n["board_frames"] = {}
    for nn in BOARD_SECTION:
        n["board_frames"][nn] = sum(
            nn in re.findall(r"\d\d", c[COL["board"]])
            for _, c, _ in all_rows
            if len(c) > COL["board"]
        )
    s0 = section(spec, 0, 1)
    n["boards"] = count(r"^\| \d\d +\| `E16-D04 / ", s0)
    n["light_twins"] = count(r"^\| \d\d +\| `[^`]+` +\| [^|]* \| light +\|", s0)
    n["twin_frames"] = len(TWINS)
    n["mutations"] = len(MUTATIONS)
    n["mutations_by_rule"] = {}
    for _, _, needle in MUTATIONS:
        rule = "r" + needle.split(" ", 1)[0].split(":", 1)[0][2:]
        n["mutations_by_rule"][rule] = n["mutations_by_rule"].get(rule, 0) + 1
    n["mutations_first"] = sum(d.startswith("M") for d, _, _ in MUTATIONS)
    n["mutations_lens"] = sum(d.startswith("A") for d, _, _ in MUTATIONS)
    n["mutations_own"] = sum(d.startswith("O") for d, _, _ in MUTATIONS)
    n["mutations_shipped"] = sum(d.startswith("P") for d, _, _ in MUTATIONS)
    n["mutations_text1"] = sum(d.startswith("R") for d, _, _ in MUTATIONS)
    n["mutations_text1_own"] = sum(d.startswith("N") for d, _, _ in MUTATIONS)
    n["mutations_text2"] = sum(d.startswith("T") for d, _, _ in MUTATIONS)
    n["mutations_text2_own"] = sum(d.startswith("U") for d, _, _ in MUTATIONS)
    n["mutations_text3"] = sum(d.startswith("X") for d, _, _ in MUTATIONS)
    n["mutations_text3_own"] = sum(d.startswith("Y") for d, _, _ in MUTATIONS)
    n["mutations_pin"] = sum(d.startswith("Z") for d, _, _ in MUTATIONS)
    n["mutations_text4"] = sum(d.startswith("S") for d, _, _ in MUTATIONS)
    n["mutations_text4_own"] = sum(d.startswith("W") for d, _, _ in MUTATIONS)
    n["mutations_text5"] = sum(d.startswith("Q") for d, _, _ in MUTATIONS)
    n["mutations_contract"] = sum(d.startswith("V") for d, _, _ in MUTATIONS)
    n["valid_twins"] = len(VALID)
    n["pins"] = pin_counts(RULED_PIN_TXT)
    n["bq_rows"] = count(r"^\| BQ-\d+ ", spec)
    n["checklist_boxes_14"] = facts["scr142"]["checklist_boxes"]
    n["checklist_items"] = count(r"^\| 14:2780 ", spec)
    dk = deck_rows(spec)
    n["deck_rows"] = len(dk)
    n["deck_new"] = sum(src.startswith("`new`") for _, _, src in dk)
    n["reason_keys"] = len(re.findall(REASON_RE, section(spec, 14, 15), MULTI))
    n.update({k: count(rf"^\| D04-{p}\d+ ", spec) for k, p in ROW_IDS})
    n["flows"] = count(r"^\| F\d ", section(spec, 17, 18))
    n.update(
        {
            "pairs_rows": gated,
            "pairs_fail": fails,
            "pairs_registered": gated - proposed,
            "pairs_proposed": proposed,
        }
    )
    n["composite"] = composite
    n["ratios"] = {
        "disabled": {
            "dark": round(
                contrast(
                    resolve(dark, "color.text.disabled"), resolve(dark, "color.surface.raised")
                ),
                2,
            )
        },
        "danger_on_hover": {
            "dark": round(
                contrast(
                    resolve(dark, "color.status.danger.default"),
                    resolve(dark, "color.surface.hover"),
                ),
                2,
            )
        },
        "danger_on_sunken": {
            "dark": round(
                contrast(
                    resolve(dark, "color.status.danger.default"),
                    resolve(dark, "color.surface.sunken"),
                ),
                2,
            )
        },
    }
    n["opacity_disabled"] = float(resolve(dark, "opacity.disabled"))
    lo, hi = facts["reason_bounds"]
    lay = LAYOUT
    # R-17's register beyond the fixture: the figures the prose types with their units, the HTTP codes, the dates
    # the provenance cites (the owner's decision, the shared-sentence ruling, this ticket's ruling)
    n["context"] = {
        "http_codes": [202, 403, 404, 409, 422, 503],
        "provenance_dates": ["2026-09-25", "2026-10-21", "2026-10-25"],
        "typed": [
            f"{facts['import_days_max']} days",
            f"{lo} characters",
            f"{hi} characters",
            f"{lay['reason_max']} characters",
            f"{lay['poll_s']} s",
            f"{lay['zoom_pct']} %",
            f"{lay['base_zoom_pct']} %",
            f"{lay['stack_px']} px",
            f"{lay['notice_slot_px']} px",
            f"{lay['focus_px']} px",
            f"{lay['query_window_h']} h",
            f"{lay['horizon_days']} days",
            f"{facts['reauth_min']} min",
            f"{facts['rearm_points']} points",
            f"{facts['warn_runway_days']} days",
            f"{facts['ilp_batch_rows']:,} rows",
            *(f"{p} %" for p in facts["free_steps"]),
            f"{fx['health']['offset_min']} min",
            gb(0),
            f"{len(frame_rows(spec)) + len(TWINS)} frames",
        ],
        "older_than_days": [1, facts["older_than_days_max"]],
    }
    n["missing_tokens"] = len(missing)
    n["layout"] = LAYOUT
    n["fixture"] = fixture_numbers(fx, facts)
    n["strings"] = {
        k: v
        for k, v in fx.items()
        if k
        not in (
            "example",
            "levels",
            "tiers",
            "symbols",
            "lag",
            "migration",
            "health",
            "imp",
            "jobs",
            "compaction",
            "purge",
        )
    }
    n["strings"].update(
        {
            "levels": fx["levels"],
            "tiers": fx["tiers"],
            "symbols": fx["symbols"],
            "lag": fx["lag"],
            "migration": fx["migration"],
            "health": fx["health"],
            "imp": fx["imp"],
            "jobs": fx["jobs"],
            "compaction": fx["compaction"],
            "purge": fx["purge"],
        }
    )
    n["facts"] = {
        "jobs_cap": facts["jobs_cap"],
        "disk": facts["disk"],
        "import_days_max": facts["import_days_max"],
        "reason_min": facts["reason_bounds"][0],
        "reason_max_chars": facts["reason_bounds"][1],
        "questdb_tables": len(facts["questdb_tables"]),
        "storage_fields": len(facts["storage_fields"]),
        "job_kinds": len(facts["job_kinds"]),
        "job_status": len(facts["job_status"]),
        "health_tiers": facts["health_components"][:3],
        "ilp_batch_rows": facts["ilp_batch_rows"],
        "migration_latest": facts["migration_latest"],
        "ingest_rate_k": facts["ingest_rate_k"],
        "trades_rate_k": facts["trades_rate_k"],
    }
    return n, matrix, missing, fails


def matrix_gate(spec: str, matrix: list[dict[str, object]]) -> list[str]:
    """Section 15, row by row: the three printed ratios equal the tool's for that fg / bg / role."""
    bad: list[str] = []
    by = {(str(r["fg"]), str(r["bg"]), str(r["role"])): r for r in matrix}
    for ln in section(spec, 15, 16).splitlines():
        m = re.match(
            r"^\| ([^|]+?) +\| `([^`]+)` +\| `([^`]+)` +\| ([a-z-]+) +\| ([^|]+?) +\| ([^|]+?) +\| ([^|]+?) +\|",
            ln,
        )
        if not m:
            continue
        r = by.get((m.group(2), m.group(3), m.group(4)))
        if r is None:
            bad.append(f"section 15: {m.group(1)[:40]} is not a pair the tool measures")
            continue
        want = [show(cast(float, r[k])) for k in ("dark", "light", "high-contrast")]
        if [m.group(5), m.group(6), m.group(7)] != want:
            bad.append(f"section 15: {m.group(1)[:40]} ratios differ from the tool ({want})")
    return bad


def run(
    spec: str,
    t: dict[str, str],
    themes: dict[str, dict[str, object]],
    registered: set[tuple[str, str]],
    extra: list[Path],
    check: bool,
    pins: str | None = None,
) -> tuple[list[str], dict[str, Any], list[dict[str, object]], list[str], int]:
    facts = contract_facts(t)
    fx = fixture(facts, t["22"])
    numbers, matrix, missing, fails = numbers_of(spec, facts, fx, themes, registered)
    bad = gates([SPEC, *extra], spec, facts, fx, t, numbers)
    bad += matrix_gate(spec, matrix)
    if check:
        flat = flatten(numbers)
        seen: set[str] = set()
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) --!?>", spec, re.DOTALL):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except (TypeError, ValueError):
                pass
            if have is None or not same:
                if f"{key}={val}" in seen:
                    continue  # one FAIL per marker however often the spec repeats it
                seen.add(f"{key}={val}")
                if key.startswith("board_frames."):
                    nn = key.split(".")[1]
                    bad.append(
                        f"R-18: §0 and §{BOARD_SECTION.get(nn, '?')}'s table disagree (board {nn}: §0 says {val}, the table {have})"
                    )
                else:
                    bad.append(f"marker audit:{key}={val} vs tool {have}")
        bad += printed_before(spec)
    # R-23, the backstop: reported when no other gate FAILs, else counted beside them (PIN_BESIDE)
    pin_bad = pin_gate(spec, RULED_PIN_TXT if pins is None else pins)
    PIN_BESIDE.clear()
    if bad:
        PIN_BESIDE.extend(pin_bad)
    else:
        bad = pin_bad
    return bad, numbers, matrix, missing, fails


def self_test(
    spec: str,
    t: dict[str, str],
    themes: dict[str, dict[str, object]],
    registered: set[tuple[str, str]],
) -> int:
    """Each mutation must make `--check` fail with ONE FAIL — its own, the expected message — and no two mutations
    may share a message; the unmutated spec passes and the spec file is byte-identical afterwards.
    """
    before = hashlib.sha256(SPEC.read_bytes()).hexdigest()
    base_bad, _, _, _, base_fails = run(spec, t, themes, registered, [], True)
    out = []
    ok = not base_bad and not base_fails
    out.append("unmutated spec: " + ("PASS" if ok else "FAIL — " + "; ".join(base_bad[:5])))
    signatures: dict[int, str] = {}
    for i, (desc, fn, needle) in enumerate(MUTATIONS, 1):
        bad, _, _, _, _ = run(fn(spec), t, themes, registered, [], True)
        if len(bad) == 1 and bad[0].startswith(needle):
            signatures[i] = bad[0]
            beside = f" (R-23 beside it: {len(PIN_BESIDE)})" if PIN_BESIDE else ""
            out.append(f"mutation {i:3d} FAIL as expected, its only FAIL: {bad[0]}{beside}")
        else:
            ok = False
            out.append(
                f"mutation {i:3d} DEFECT ({len(bad)} FAIL): {desc} — " + " | ".join(bad)[:300]
            )
    # a twin that edits a ruled unit is clean once re-pinned, and until then only R-23 refuses it
    for desc, fn in VALID:
        twin = fn(spec)
        bad, _, _, _, _ = run(twin, t, themes, registered, [], True, render_pins(twin))
        held, _, _, _, _ = run(twin, t, themes, registered, [], True)
        good = not bad and all(b.startswith("R-23 ") for b in held)
        ok = ok and good
        out.append(
            f"valid twin {desc[:3]} "
            + (
                f"PASS, no FAIL once re-pinned ({len(held)} R-23 until then)"
                if good
                else "DEFECT: " + " | ".join(bad or held)[:300]
            )
        )
    sigs = list(signatures.values())
    dup = sorted({s for s in sigs if sigs.count(s) > 1})
    if dup:
        ok = False
        out.append("duplicate FAIL messages: " + " | ".join(dup))
    same = hashlib.sha256(SPEC.read_bytes()).hexdigest() == before
    ok = ok and same
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(set(sigs))} distinct FAIL messages, each its mutation's only FAIL; {len(VALID)} valid twins clean once re-pinned; the unmutated spec "
        + ("passes" if not base_bad else "FAILS")
        + "; the spec file "
        + ("byte-identical" if same else "CHANGED")
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
    if "--repin-ruled" in argv:
        return repin(spec)
    if "--self-test" in argv:
        return self_test(spec, t, themes, registered)
    mode = None
    if "--mutate" in argv:
        mode = int(argv[argv.index("--mutate") + 1])
        desc, fn, needle = MUTATIONS[mode - 1]
        spec = fn(spec)
    bad, numbers, matrix, missing, fails = run(
        spec, t, themes, registered, extra, "--check" in argv or mode is not None
    )
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        payload = {
            "numbers": numbers,
            "matrix": matrix,
            "missing": missing,
            "problems": bad,
            "cite_warnings": CITE_WARN,
            "pins_beside": PIN_BESIDE,
            "palette": palette,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 1 if fails or bad else 0
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    for r in matrix:
        out.append(
            f"{r['fg']} on {r['bg']} | {r['role']} | {show(cast(float, r['dark']))} / {show(cast(float, r['light']))} / {show(cast(float, r['high-contrast']))} | {r['verdict']} | {r['pairs']} | {r['element']}"
        )
    out.append(
        f"validity composite (the primary label at opacity.disabled over the card; not gated): {numbers['composite']}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    out.append(f"MISSING tokens: {missing}")
    out.append("\n## 3-4. Contract facts and the derived fixture:")
    out.append(
        json.dumps(
            {
                "facts": numbers["facts"],
                "fixture": numbers["fixture"],
                "strings": numbers["strings"],
            },
            ensure_ascii=False,
        )
    )
    ok = (
        "OK — every tier row with a unit and the PROPOSED fallback; the stamp on every page frame; two labelled meters; health as text and the page usable; "
        "the degradation sentence on every level >= 1 frame; no lock on any state frame; the purge triple with the typed field empty; the validity look without a lock; "
        "a failing import inside its card with its reason, the overlap report and the archive-derived tag; busy as status and the 409 as T4; every PROPOSED carrier captioned; "
        "the view-as T2 anatomy first; exits never gated; no console or backup control; the siblings PENDING by name; every number the tool's; the inventory reconciled; "
        "the rbac sentences within 60 chars naming no data; the E16-D02 outcome copy byte for byte; standard confirms for compact and vacuum, typed for purge; one announcement per state; "
        "no jargon; no private path; every id exists; every cited text exists; no closing keyword"
    )
    out.append(
        "\n## 5-6. Copy and frame gates: "
        + (ok if not bad else "\n".join("FAIL " + b for b in bad))
    )
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out += [f"NOTE R-23 beside the FAILs above (reported once they clear): {m}" for m in PIN_BESIDE]
    if "--check" in argv or mode is not None:
        clean = not any(b.startswith(("marker", "R-18: §0")) for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
    out.append(
        "\n## 7. Counts: "
        + json.dumps(
            {k: v for k, v in numbers.items() if k not in ("facts", "strings")}, ensure_ascii=False
        )
    )
    if mode is not None:
        desc, fn, needle = MUTATIONS[mode - 1]
        hit = len(bad) == 1 and bad[0].startswith(needle)
        out.append(
            f"\n## mutation {mode} ({desc}): {len(bad)} FAIL — "
            + (
                "as expected, the targeted FAIL only (rc 1: the gate caught it)"
                if hit
                else "UNEXPECTED (rc 2: the mutation slipped through or failed elsewhere)"
            )
        )
        print("\n".join(out))
        return 1 if hit else 2
    print("\n".join(out))
    return 1 if fails or bad else 0


# --- R-23 the pinned ruled units: `--repin-ruled` writes this table; a reviewer reads it here --------
RULED_PIN_TXT = r"""
@ header#1 ¶1 ‖ heading
  # E16-D04 — SCR-142 Storage and database panel with tier health and projections: hi-fi
@ header#1 ¶2 ‖ paragraph
  **Ticket:** E16-D04 (#372) · **Epic:** E16 · **Status:** Draft, **text-first** — this file is
   the hi-fi spec; the ten Penpot boards (nine dark, one light twin board) are **PENDING** and land
   in a second PR with their exports and the page id (§0); nothing here is cited as drawn. **Owner
   approval pending** (agent-delivery adaptations, owner decision 2026-09-25): the owner's
   `approved` comment or the merge stands in for the ticket's design sign-off (§18). **Every
   decision not already binding is PROPOSED**; RULED items name their source (the BQ table; the
   orchestrator's ruling on #372, issue comment 6397016433, 2026-10-25); every finding is
   `(heuristic)`; no participant, timing or quote is invented (§17). **Method:** a desk spec over
   the merged E16-D02 (SCR-140, the host page) and E16-D03 (the destructive-change pattern and the
   SCR-141 / SCR-142 boundary), and the merged E09-D09 / E30-D02 / E30-D04 patterns; every number
   here carries an `audit:` marker that `docs/design/_tools/e16_d04_storage_audit.py --check`
   re-derives from the `22` `getStorageUsage` example, and `--self-test` proves §12's gates with
   ⟦audit:mutations⟧ mutations.
@ header#1 ¶3 ‖ paragraph
  **Penpot page:** `E16-D04 Storage and database` · id pending (the boards PR pins it; page by
   name + id only, `docs/design/README.md` :46–48).
@ header#1 ¶4 ‖ paragraph
  **Scope** (the ticket): SCR-142 as the one picture of the three storage tiers (QuestDB hot,
   Parquet/DuckDB cold, Postgres): per-tier size, growth rate and projected full date with units
   (the per-tier growth and projection PROPOSED, D04-G1); row counts by table, ingestion pressure,
   slowest queries, last vacuum / compaction and the migration version as PROPOSED fields drawn
   beside their shipped fallback (D04-G3, G4, G5, G6, G7); the hot-tier per-symbol table; the
   maintenance actions (compact, purge and the PROPOSED vacuum, D04-G8) with progress; the bulk
   archive import (US-REC-007) with a date range per symbol, progress, per-file skip / error
   reporting, the overlap report and the archive-derived label; the five states (healthy ·
   migration pending (PROPOSED, D04-G7) · lag warning · read-only mode (disk full) · a tier
   unreachable); keyboard and announcements; redlines; the copy deck; the measured contrast. **Out
   of scope:** SCR-143 (E42 / OBS) beyond the one recorder / DB tile link; backup and restore (`21`
   §8 :4567; `22` `/admin/backups`) — named as absences, never drawn; SCR-140's disk card, purge
   dialog and Compact now (E16-D02 — reused by cite, never redrawn); SCR-141's retention editor and
   its `retention_sweep` footer (E16-D03 BQ-6 RULED :45); implementation.
@ header#1 ¶5 ‖ paragraph
  **Start.** `blocked_by` E16-D02 (#323): Done — text merged in #4124 at
   `736f995e02ce14c726599f5860f5733b8cfc836b`, boards merged in #4401 at
   `505fdafe9a30530159efdc9252242c0bcffa24f1`; both cited at those commits. The sibling E16-D03
   (#324) text is merged (#4438, `3ff63ea0e8326793824dd130468a591eadf43f14`) and E16-D05 (#373)
   text is merged (`cba937ef0f94815de1c85622645579ccb724c2a0`); **the E16-D03 boards PR #4463 and
   the E16-D05 boards PR #4501 are PENDING by name only** — nothing from either is pinned, quoted
   or cited as a frame. E16-D06 and E16-D07 are PENDING by name; the implementation ticket that
   consumes SCR-142 opens the contract-first PRs for D04-G1…G12 (§13; E16-T10 is the import's, `22`
   :14979).
@ header#1 ¶6 ‖ paragraph
  **Inputs pinned.** Base `origin/main` `965cf14090e590781d3e19c51a719ff54fb4c30e`: `14` §0.3 :43,
   §0.5 rules 4–6 :84–86, SCR-140 :2725–2757 (states :2748), SCR-141 :2758–2769 (the pointer form
   :2768), SCR-142 :2770–2781 (type :2772, data :2773, states :2774, components :2775, a11y :2777,
   performance :2778, audit :2779, checklist :2780), SCR-143 :2782–2795; `22` (re-pinned to
   `origin/main` `299562bdb829588edeae26065dc79b1c704395c4`, after #4597 reworded the purge route:
   step-up class `recorder_purge`, `before` required) `getStorageUsage` :5410–5465 (the description
   :5415–5424, the example :5435–5462), `StorageUsage` :19208–19243, `RecorderPolicySettings`
   :19180–19207, `compactRecorder` :14934–14974, `importTradeArchive` :14975–15028,
   `purgeRecordedData` :15029–15142 (the step-up :15040–15049, the window :15051–15057, the body
   :15086–15100), `getJob` :12097–12133, `Job` :21992–22044, `getHealth` :10988–11027,
   `HealthReport` :21836–21861, `ComponentState` :17417–17420, the job caps :380, the 422 titles
   :722, :728, `checksum_mismatch` :11809, the readiness probe :11103, the step-up problem
   :12413–12417, migration 0008 :14395; `23` the recorder topic's `storage` object :4062–4085 and
   the two pressure fields :4060–4061, the gate prose :4096–4105; `21` §4 :3956–4334 (the thirteen
   table headings :3968–4318, the operational notes :4319–4334), §5.1 :4339, §5.4 :4408–4420, §8
   :4567; `20` :904–908; `24` §13.4.1 :3814–3860 (the projection :3830, the precedence :3854),
   :494, :3718–3719; `27` ADR-0003 :1, :23, :34–36, :45; `04` SR-048 :873; `05` §3.4 :90, §6.2
   :144–150; `11` US-REC-004 :4153, US-REC-005 :4172, US-REC-007 :4210–4226; `15` CMP-001 :48,
   CMP-009 :129, CMP-011 :149, CMP-016 :198, CMP-019 :225–231, CMP-023 :262–270, CMP-024 :272–278,
   CMP-026 :290, CMP-027 :301, CMP-028 :311, CMP-035 :381, CMP-036 :390–396, CMP-038 :409, CMP-040
   :433, CMP-043 :463, CMP-044 :473–481, CMP-047 :503, CMP-049 :524–533, CMP-050 :535, CMP-051
   :544, CMP-079 :811–817, CMP-087 :884–890, CMP-093 :940, CMP-178 :2068–2074, CMP-239 :2784.
   Merged upstream specs at their merge commits: E16-D02 `736f995e…` (§2 :150–158, §3.1 :186–194,
   §3.2 :196–209, §6.4 :380–384, §6.5 :404–420, §6.6 :422–426, §7 :444–455, §8.3 :486–504, §8.5
   :508–519, D-8 :760, D-16 :778); E16-D03 `3ff63ea0…` (BQ-6 :45, §1.3 :102–120, §5 :198–224 incl.
   `SCR-141/confirm-lengthen` :210, §8 :255–268, §18 :546); E16-D05 `cba937ef…` (the header, §0
   :52–68, §12 :319–357, §13 :359, §18 :537: the spec shape and the table-keyed audit tool);
   E09-D09 `baccf724a1fa3ad66f9333e440a7f5e8668b6eff` (§2.1 :32–44, §2.2 :49, §3.1 :85–95, §3.2
   :108, §9.1 :224–232, §9.3 :238, §10 :252); E30-D02 `f798a64e65d15d13f2f816c9b5564e0d148ba2ae`
   (D3 :128); E30-D04 `ca7d61fa1a767f6698d5243379546ad9f95090ab` (§30 :1048, the shared G-row
   sentence); E25-D01 `c0674eb95a59903b09388468f8bf2e382bab1161` (§9.5 :334, the pattern rule
   cited, never re-proposed); the token JSON `packages/ui/tokens/*.tokens.json` + `themes.json`;
   `tools/contrast/pairs.mjs`.
@ header#1 ¶7 ‖ paragraph
  **Key.** `NN` = `docs/plan/NN-*.md` (`22` = `22-api-openapi.yaml`). **D04-Gn** = a contract gap
   (the shared sentence of §13), **D04-CGn** = a shipped limit recorded, not designed around,
   **D04-Cn** = a contradiction with its owner, **D04-An** = a copy-ready amendment, **D04-Qn** =
   an open question, **D04-Dn** = a decision of this spec. **Fixture** (derived by the tool from
   the `22` `getStorageUsage` example :5435–5462, never typed): report sampled
   ⟦audit:fixture.sample_date⟧ ⟦audit:fixture.sample_time⟧ UTC; disk ⟦audit:fixture.disk_total_tb⟧
   TB, ⟦audit:fixture.disk_used_tb⟧ TB used (⟦audit:fixture.volume_pct⟧ %),
   ⟦audit:fixture.disk_free_tb⟧ TB free; recording budget ⟦audit:fixture.cap_gb⟧ GB with
   ⟦audit:fixture.budget_used_gb⟧ GB recorded (⟦audit:fixture.budget_pct⟧ %: QuestDB
   ⟦audit:fixture.questdb_gb⟧ GB over ⟦audit:fixture.retention_questdb⟧ days, Parquet
   ⟦audit:fixture.parquet_gb⟧ GB over ⟦audit:fixture.retention_parquet⟧ days; Postgres
   ⟦audit:fixture.postgres_gb⟧ GB outside the budget); growth ⟦audit:fixture.growth_gb_day⟧ GB/day;
   `projected_full_at` ⟦audit:fixture.full_date⟧ = about ⟦audit:fixture.runway_days⟧ days, which
   the tool confirms is the budget wall ((cap − used) ÷ growth; the volume's wall is about
   ⟦audit:fixture.volume_wall_days⟧ days away); BTCUSDT pinned, ⟦audit:fixture.btc_gb⟧ GB,
   ⟦audit:fixture.btc_mb_day⟧ MB/day; ETHUSDT ⟦audit:fixture.eth_gb⟧ GB, ⟦audit:fixture.eth_mb_day⟧
   MB/day. **D04-CG3:** the example's `symbols[]` sum to ⟦audit:fixture.symbols_sum_gb⟧ GB while
   its QuestDB + Parquet tiers hold 1,188.0 GB (⟦audit:fixture.attributed_pct⟧ % attributed): the
   example is internally inconsistent; the tool prints both figures, the per-symbol table says so
   (§4), and nothing here "fixes" the example. The level fixtures scale the recorded bytes to the
   ladder steps (`20` :905–907; the `14` :2748 figure for level 1): ⟦audit:fixture.level1_pct⟧ %,
   ⟦audit:fixture.autostop⟧ % and ⟦audit:fixture.halt⟧ %. Every frame-row number is re-derived by
   the tool's R-17 gate (§12); every prose number carries a marker.
@ AC trace#1 ¶1 ‖ heading
  ## Acceptance-criteria trace (#372)
@ AC trace#1 ¶2 ‖ table
  | Scenario (ticket) | Where in this spec | Evidence the tool gates |
  |
   --------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | **All three tiers are legible at a glance** — QuestDB hot, Parquet/DuckDB cold and Postgres
   each show size, growth rate and projected full date with units | §4 (board 02: `TIER/questdb`,
   `TIER/parquet`, `TIER/postgres`); §3 (which of the three numbers is produced today: only the
   disk-level growth and projection); §13 D04-G1 | every tier row's Size cell carries a number and
   a unit, its Growth/day and Projected full cells carry either a figure with a unit or the shipped
   "—" captioned PROPOSED with the disk-level fallback beside it; a tier row missing one is a FAIL
   (§12 R-1; mutations M01–M03) |
  | **Degradation order is stated** — in the low-disk warning state the design states in text that
   recording pauses before trading is affected | §5 (board 03: `SCR-142/low-disk-warning`,
   `/autostop`, `/read-only-disk-full`, `/volume-refused`); §1.4 (the ladder, `20` :904–908; the
   precedence, `24` :3854); §14 `storage.degradation` | the sentence "Recording pauses before
   trading is affected." read on every frame whose producer is `level` ≥ 1, never inverted (§12
   R-5; mutations M10–M11, T20–T22, U27–U30) |
  | **A failing import does not look like a failing page** — one archive file fails checksum: the
   file is shown skipped with a reason while the import continues with progress | §8 (board 07:
   `IMPORT/running-with-skips`, `/summary`, `/failed`); §14 the per-file reason sentences | the
   shipped running state (the overall bar and its days still moving), the skipped file's row with
   its reason in the captioned PROPOSED inset (D04-G11: `files[]` streamed before `succeeded`), no
   page banner and no `role="alert"` in any wording on the skip frame; a failed import stays inside
   its card (§12 R-9, R-10). AC 3's per-file skip while running is met as PROPOSED (§16) |
@ AC trace#1 ¶3 ‖ paragraph
  The catalogue's six sign-off boxes (`14` :2780, ⟦audit:checklist_boxes_14⟧ items) are traced
   item by item in §16. The ticket's Security note (Owner-only, step-up, the reason and the typed
   `confirm_symbol` echo, never pre-filled; no QuestDB / DuckDB console link, SR-048 `04` :873) →
   §7 and §12 R-7, R-15. The A11y note (per-tier tables with units, health as text, sparklines with
   a table alternative (the sparkline PROPOSED, D04-G2), one announcement per terminal state) → §4,
   §10. The Performance note (figures sampled every 60 s; heavy operations explicit, with progress)
   → the sample stamp (§2, R-2) and §6. Observability → §13 D04-C1, D04-D10.
@ BQ#1 ¶1 ‖ heading
  ## The twenty-two questions (BQ-1…BQ-22) — RULED by the orchestrator (issue comment 6397016433,
   2026-10-25): all ⟦audit:bq_rows⟧ defaults stand, with four conditions and three adjustments
@ BQ#1 ¶2 ‖ table
  | # | Question | Built here | Status |
  | ----- | ------------------------------------------------------------------- |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ------ |
  | BQ-1 | the deliverable path and companions | `docs/design/E16/E16-D04.md` +
   `docs/design/_tools/e16_d04_storage_audit.py` + one `14` pointer line; the ticket's web template
   paths, `pnpm` commands and closing-keyword body line are one Deviation line (§18) | RULED |
  | BQ-2 | the branch | `design/e16-d04-storage-panel-hifi` (the ticket's `design/e16-scr142`
   recorded as a Deviation, §18) | RULED |
  | BQ-3 | a hand-off file | none: not labelled `handoff`; no component contract changes (CMP-178
   by A-row only) | RULED |
  | BQ-4 | the `14` / `15` edit set | `14`: one content-only pointer line after SCR-142's
   checklist :2780 in the :2768 form; the fifth state and the audit-name mismatch are C-rows
   (D04-C1, D04-C2). `15`: untouched; A-rows for CMP-178, CMP-023, CMP-049 (§13) | RULED |
  | BQ-5 | the Penpot page name | `E16-D04 Storage and database`, by name + page id once drawn;
   never the host, team or file id, never a workspace URL | RULED |
  | BQ-6 | where SCR-142 lives | a **section of `/admin/recorder`** (`14` :2772 "Page section"),
   reached from SCR-140's disk card ("Storage details →") and from SCR-143's recorder / DB tile; no
   route of its own is drawn (D04-Q2 names the alternative) | RULED |
  | BQ-7 | the boundary with SCR-140 | the per-symbol **table** cut of `symbols[]` and the three
   tier cards are this page's; the disk-card headline grammar, the purge dialog (§6.5) and Compact
   now (§6.6) are E16-D02's, reused by cite; "Shorten retention / Reduce depth / Unpin" link to
   SCR-141 / SCR-140 | RULED |
  | BQ-8 | which T2 frames | only `SCR-142/view-as` (`rbac.view_as`, one notice); **no**
   `rbac.owner_only` frame: a non-owner never reaches `/admin/*` (`14` :43, :85) — the sentence
   lives in §9's role table only | RULED |
  | BQ-9 | purge on SCR-142 | the one E16-D02 §6.5 dialog from its entry points (Purge data… on
   the QuestDB and Parquet cards, Purge… in the symbol row's detail popover; none on Postgres),
   drawn as a cited re-use with the typed field empty; no second shape | RULED |
  | BQ-10 | the confirm pattern for compact / vacuum | CMP-044 **standard** — compaction and
   vacuum are non-destructive ("Nothing is deleted."): no typed field, no step-up unless the server
   answers 403; purge keeps E16-D02 §6.5's typed dialog with the `recorder_purge` step-up | RULED |
  | BQ-11 | vacuum's existence and class | wholly PROPOSED (D04-G8); **never a frame's default**:
   it appears only as a captioned inset "PROPOSED — D04-G8, owner approval pending (#2701)" on
   boards 01, 02 and 05; `recording:write` and no step-up proposed; the owner may require the
   `recorder_purge` class (D04-Q1) | RULED |
  | BQ-12 | the import confirm | no dialog: the card form + one consequence line is the confirm
   (additive, resumable); the CMP-044 standard alternative is D04-Q3 | RULED |
  | BQ-13 | cancel | drawn only as a captioned PROPOSED carrier on the jobs strip (D04-G10 `POST
   /admin/jobs/{jobId}/cancel`), never as a shipped control; the shipped reality stated on every
   carrier: a started job runs to its end; the `cancelled` outcomes kept (`Job.status` :22016) |
   RULED |
  | BQ-14 | actions at level 3 / write gate closed | Compact, Purge and Import **enabled**
   (availability, never a pre-emptive disable — E30-D02 D3); a server refusal is shown in the
   CMP-044 result as T4, never as a disabled control | RULED |
  | BQ-15 | a tier down | per-card CMP-027 inline with Retry (re-poll); the actions that need that
   tier are T4 on refusal; the page stays usable | RULED |
  | BQ-16 | migration pending | CMP-028 warning banner on PROPOSED fields (D04-G7), captioned;
   **no Apply control** (an absence: migrations run with the release, `22` :11103) | RULED |
  | BQ-17 | "ingestion lag" with no lag field | the two produced numbers (WS
   `ingest_rate_msgs_per_sec`, `write_backlog_rows`, `23` :4060–4061) with units; the lag cell "—"
   + D04-G4; the lag-warning state keyed on the backlog | RULED |
  | BQ-18 | row counts, slow queries, last vacuum / compaction, per-tier growth | all PROPOSED
   (D04-G1, G3, G5, G6); every frame's default shows the shipped surface, the PROPOSED column or
   row appears only as a captioned second row or inset with the shipped fallback beside it; the
   checklist boxes are satisfied "as PROPOSED" and say so in §16 | RULED |
  | BQ-19 | import per-file reporting with no result schema | D04-G11 `ArchiveImportResult`
   PROPOSED; `checksum_mismatch` reuses `22` :11809's code word; the running frame shows the pct
   bar and "{done} of {n} days"; the per-file rows and the skip counter while running are D04-G11's
   `files[]` stream, a captioned inset | RULED |
  | BQ-20 | the audit-name mismatch | a C-row (D04-C1, owner `14`); the confirm line stays "This
   action is audited." | RULED |
  | BQ-21 | the light twin set | board 10 = three twins: `SCR-142/low-disk-warning`,
   `IMPORT/running-with-skips`, `SCR-142/view-as` (⟦audit:twin_frames⟧ of ⟦audit:frames_total⟧,
   under one third of the boards) | RULED |
  | BQ-22 | the sparkline source | the shipped frame draws the Growth column alone; the sparkline
   is one PROPOSED inset on board 02 (D04-G2 `symbols[].history_bytes[]`) with its DOM-mirror
   table, never a frame default | RULED |
@ BQ#1 ¶3 ‖ paragraph
  **Conditions (RULED with the list; the same four as the sibling specs).** (A1) a lock only for a
   key in E09-D09's register — here `rbac.view_as` on `SCR-142/view-as` only; absences, validity
   and server refusals are never locks; every exit (Close, Esc, Cancel, Back) T1 on every frame.
   (A2) the tool's gates read every frame table row by row and the prose, case-insensitive
   vocabulary per ruled sentence, whole clauses, one `--self-test` mutation per form (§12). (A3)
   exits never gated. (A4) merged texts cited at their merge shas; the E16-D03 / E16-D05 boards PRs
   PENDING by name only; every departure a PROPOSED A / C / G-row; `15` untouched, `14` the one
   pointer line; no lane as authority.
@ §0#1 ¶1 ‖ heading
  ## 0. Boards (PENDING — the boards PR draws them)
@ §0#1 ¶2 ‖ paragraph
  Boards go on the self-hosted Penpot page `E16-D04 Storage and database` · id pending
   (`docs/design/README.md` :46–48; never the host, team or file id, never a workspace URL). Boards
   are `E16-D04 / NN slug`; frames inside them are `SCR-142/<state>`, `TIER/<state>`,
   `JOB/<state>`, `PURGE/<state>` and `IMPORT/<state>`; exports go to
   `docs/design/E16/img/E16-D04-NN-<slug>.png` at 1:1 via `docs/design/_tools/penpot_export.py`.
   Every board with a PROPOSED decision carries the stamp, every RULED item its source; every
   PROPOSED control, column or action is a captioned inset or a captioned second row ("PROPOSED —
   D04-Gn, owner approval pending (#2701)"), never a frame's default (BQ-11 / BQ-13 / BQ-18 / BQ-22
   RULED). Nothing from E16-D02's boards
   (`docs/design/E16/img/E16-D02-05-scr-140-disk-warning.png`,
   `E16-D02-19-scr-140-purge-confirm.png`) is redrawn: they are cited by name and path.
   ⟦audit:boards⟧ boards, ⟦audit:light_twins⟧ light board, ⟦audit:frames_total⟧ frames
   (⟦audit:frames_scr⟧ SCR-142 · ⟦audit:frames_tier⟧ TIER · ⟦audit:frames_job⟧ JOB ·
   ⟦audit:frames_purge⟧ PURGE · ⟦audit:frames_import⟧ IMPORT, plus the 3 twins of board 10); the
   state tables, this table and the board script's frame inventory reconcile (§12 R-18).
@ §0#1 ¶3 ‖ table
  | # | Board | Draws | Theme | Export | Status |
  | --- | --------------------------------- |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ----- | ------------------------------------------------------- | ------- |
  | 01 | `E16-D04 / 01 anatomy-healthy` | ⟦audit:board_frames.01⟧ frames of §2: `SCR-142/healthy`
   (the full page, regions (a)…(h) lettered, the two meters, the three tier cards, the sample
   stamp; the vacuum inset captioned PROPOSED, D04-G8) · `SCR-142/healthy-200-zoom` (the reflow:
   cards stack, tables one row element per record) | dark |
   `docs/design/E16/img/E16-D04-01-anatomy-healthy.png` | pending |
  | 02 | `E16-D04 / 02 tiers-and-tables` | ⟦audit:board_frames.02⟧ frames of §4: `TIER/questdb`,
   `TIER/parquet`, `TIER/postgres` (the cards, every row, PROPOSED rows captioned with the shipped
   fallback) · `TIER/tables-questdb` (the per-table CMP-049 as a captioned second row) ·
   `TIER/per-symbol` (the hot-tier symbol table; the sparkline as the one PROPOSED D04-G2 inset
   with its mirror table) · `TIER/query-performance` (a captioned second row) | dark |
   `docs/design/E16/img/E16-D04-02-tiers-and-tables.png` | pending |
  | 03 | `E16-D04 / 03 states-disk` | ⟦audit:board_frames.03⟧ frames of §5:
   `SCR-142/low-disk-warning` (level 1 + the AC 2 sentence) · `SCR-142/autostop` ·
   `SCR-142/read-only-disk-full` (level 3, gate closed; every action still enabled) ·
   `SCR-142/volume-refused` · `SCR-142/view-as` (every write T2, one notice) | dark |
   `docs/design/E16/img/E16-D04-03-states-disk.png` | pending |
  | 04 | `E16-D04 / 04 states-health` | ⟦audit:board_frames.04⟧ frames of §5:
   `SCR-142/tier-unreachable-questdb` (the card error, the page usable) · `SCR-142/lag-warning` ·
   `SCR-142/migration-pending` (the captioned banner with the version delta; no Apply) ·
   `SCR-142/stale-sample` · `SCR-142/loading` · `SCR-142/unavailable` | dark |
   `docs/design/E16/img/E16-D04-04-states-health.png` | pending |
  | 05 | `E16-D04 / 05 maintenance-jobs` | ⟦audit:board_frames.05⟧ frames of §6:
   `JOB/confirm-compact` (CMP-044 standard) · `JOB/confirm-vacuum` (captioned PROPOSED) ·
   `JOB/strip-running` (two jobs with their pct; Stop job (PROPOSED D04-G10)) ·
   `JOB/strip-refused-409` (T4) · `JOB/outcomes` (succeeded / failed / cancelled / unknown insets
   for compact and, captioned PROPOSED (D04-G8), vacuum) | dark |
   `docs/design/E16/img/E16-D04-05-maintenance-jobs.png` | pending |
  | 06 | `E16-D04 / 06 purge` | ⟦audit:board_frames.06⟧ frames of §7: `PURGE/entry-points` ·
   `PURGE/dialog` (E16-D02 §6.5 reused; the typed field empty) · `PURGE/dialog-validity` (the typed
   mismatch: validity look, `validity-reason` layer, no lock) · `PURGE/pinned-refused` (T4) ·
   `PURGE/step-up` (the sentence; SCR-006 cited, not drawn) · `PURGE/outcomes` | dark |
   `docs/design/E16/img/E16-D04-06-purge.png` | pending |
  | 07 | `E16-D04 / 07 import` | ⟦audit:board_frames.07⟧ frames of §8: `IMPORT/form` ·
   `IMPORT/form-validity` (over 366 days) · `IMPORT/running` (the bar and the days; the per-file
   table a captioned PROPOSED D04-G11 inset) · `IMPORT/running-with-skips` (AC 3: the shipped bar
   moving, the skipped row with its reason in the captioned D04-G11 inset, no banner) ·
   `IMPORT/summary` (the overlap report, the archive-derived tag) · `IMPORT/failed` (inside the
   card) | dark | `docs/design/E16/img/E16-D04-07-import.png` | pending |
  | 08 | `E16-D04 / 08 keyboard-a11y-copy` | ⟦audit:board_frames.08⟧ state frames: the focus-order
   map (header → meters → cards → tables → maintenance → import), the keys table, the announcement
   policy, the copy-deck counts, the measured-matrix line, the RULED stamps (§10, §13–§15) | dark |
   `docs/design/E16/img/E16-D04-08-keyboard-a11y-copy.png` | pending |
  | 09 | `E16-D04 / 09 redlines` | ⟦audit:board_frames.09⟧ frame of §11: `SCR-142/redlines` —
   tokens annotated on a tier card, a meter, the jobs strip, the per-file table (the PROPOSED
   D04-G11 inset), the T2 control and the validity control; the token audit counts | dark |
   `docs/design/E16/img/E16-D04-09-redlines.png` | pending |
  | 10 | `E16-D04 / 10 light-twins` | ⟦audit:board_frames.10⟧ twins in `semantic-light` through
   `themes.json` (BQ-21 RULED): `SCR-142/low-disk-warning` (the warning tone on the admin canvas),
   `IMPORT/running-with-skips` (the warning subtle rows), `SCR-142/view-as` (the T2 pair); the
   measured ratios in the title | light | `docs/design/E16/img/E16-D04-10-light-twins.png` |
   pending |
@ §1#1 ¶1 ‖ heading
  ## 1. Purpose, locked inputs, the rules stated once, the classification
@ §1 › §1.1#1 ¶1 ‖ heading
  ### 1.1 Purpose
@ §1 › §1.1#1 ¶2 ‖ paragraph
  SCR-142 is where the Owner sees the three storage tiers as one picture (`14` :2772; ADR-0003
   :23, :34–36: QuestDB hot, Parquet/DuckDB cold, Postgres relational) and where the bulk archive
   import and the maintenance actions live (the ticket). It answers four questions with figures
   that carry units and a sample time: how full is the recording budget and the volume, and when is
   either full; how large is each tier, each table and each symbol, and how healthy is each tier;
   what is running or has run (compaction, purge, import) and what it did; what the shipped
   contract does not yet produce (row counts D04-G3, slow queries D04-G5, last vacuum / compaction
   D04-G6, the schema version D04-G7, per-tier growth D04-G1, a cancel D04-G10) — each drawn as a
   captioned PROPOSED carrier beside its shipped fallback, never as a shipped control (BQ-18
   RULED). It re-decides nothing E16-D02 owns (the disk-card headline grammar, the purge dialog,
   Compact now, the job terminal copy) and nothing E16-D03 owns (the retention editor and its
   footer; BQ-6 :45 RULED: "tier health, row counts and maintenance actions stay SCR-142", the row
   counts PROPOSED, D04-G3).
@ §1 › §1.2#1 ¶1 ‖ heading
  ### 1.2 Locked inputs (cited, never re-decided)
@ §1 › §1.2#1 ¶2 ‖ table
  | Item | Source | What it fixes here |
  | --------------------------------------- |
   ----------------------------------------------------------------------------------- |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | the admin area | `14` §0.3 :43, :2390; CMP-087 `15` :884–890 | `/admin/*` needs role `owner`
   and a re-auth token ≤ 15 min old; any other session gets the router's 404; the AdminLayout shell
   with its re-auth badge (CMP-035) and `aria-label="Admin area"`; `color.surface.admin-tint` is
   named by CMP-087 and MISSING from the token package (D04-C4) — the page draws on
   `color.surface.canvas` |
  | the host page and its disk card | E16-D02 §8.3 :486–504, §2 :150–158 | the headline keyed on
   `level` ("Growing · auto-record pauses in about {d} days" … "Recording stopped · resumes below
   {halt − 5} % with 10 % of the volume free"), the formula "({autostop} % × {cap} − {used}) ÷
   {growth}/day ≈ {d} days", the threshold scale, the three suggested actions; growth = the 7-day
   trend, projection to the nearer wall (:153) |
  | the purge dialog and Compact now | E16-D02 §6.5 :404–420, §6.6 :422–426, §6.4 :380–384 | one
   CMP-043 form with CMP-044's typed pattern wrapped by CMP-093: Symbol, date, size estimate,
   Reason 3–280, Include pinned (pinned only), the typed symbol never pre-filled, the step-up
   sentence, "This action is audited (high severity)."; Compact now busy with `aria-busy`, no lock,
   no confirmation on SCR-140 |
  | the job terminal copy | E16-D02 §3.2 :196–209 | the failed / cancelled / unknown / succeeded
   lines for purge and compact (reused by cite in §6, §7); a lost job is `404 job_unknown` (`22`
   :12117) |
  | the job footer grammar | E16-D03 §8 :255–268 | one `role="status"` region,
   ⟦audit:layout.poll_s⟧ s polling while queued or running, progress as text first with a CMP-023
   whose `aria-valuetext` equals the text, one announcement per terminal state; the Class words
   `T1` · `busy` · `outcome` · `T2` · `validity look` · `T4` |
  | the destructive-change pattern | E16-D03 §5 :198–224; CMP-044 `15` :473–481 | preview → typed
   confirm carrying the consequence → step-up on submit for a destructive change;
   `SCR-141/confirm-lengthen` (:210) is the non-destructive form: CMP-044 standard, "Nothing is
   deleted.", the audited line, Cancel / Confirm |
  | the three routes and the job poll | `22` :14934–15142, :12097–12133, :21992–22044 |
   `compactRecorder`, `importTradeArchive`, `purgeRecordedData` (all `recording:write`), `getJob`
   (`admin:read`); one job of a kind at a time (`409 job_running`); jobs live in one process's
   memory, at most ⟦audit:facts.jobs_cap⟧, lost at a restart (:380, :12114–12117; D04-CG4) |
  | the ladder, the cadence, the precedence | `20` :904–908; `24` §13.4.1 :3814–3860; `22`
   :5415–5424; `23` :4096–4105 | warn 80 <!-- audit:facts.disk.CV_DISK_WARN_PCT=80 --> / autostop
   90 / halt 95 % of `cap_bytes`, re-armed 5 points lower; a sample every 60 <!--
   audit:facts.disk.CV_DISK_SAMPLE_INTERVAL_S=60 --> s; `level` read, never derived; the gate
   closed = symbols without an open position dropped as gaps; INV-B11-a outranks ADR-0015's halt |
  | T2, its keys, the validity look | E09-D09 §2.2 :49, §3.1 :85–95, §3.2 :108, §9.1 :224–232,
   §9.3 :238; E30-D02 D3 :128 | §1.3 restates them once |
  | the shared gap sentence | E30-D04 §30 :1048 | every D04-Gn carries it (§13) |
  | the pattern-vocabulary rule | E25-D01 §9.5 :334 (merged `c0674eb9…`) | "hollow, dashed or
   hatched = estimated or absent, never a side or direction" is PROPOSED there; this spec follows
   it (the PROPOSED carriers' dashed outline means absent from the contract) and does not
   re-propose it (D04-C5) |
  | what stays out | `21` §8 :4567; `04` SR-048 :873; E16-D03 BQ-6 :45; `14` SCR-143 :2782–2795 |
   backups and restore are SCR-143 / E42's (one sentence here, no control); no data-store console
   link or port; no retention footer; of SCR-143 only its recorder / DB tile is linked (:2794–2795)
   |
@ §1 › §1.3#1 ¶1 ‖ heading
  ### 1.3 The rules, stated once (every later section with a gated or disabled control cites
   "§1.3")
@ §1 › §1.3#1 ¶2 ‖ paragraph
  **T2 — disabled with a visible reason** (E09-D09 §2.2 :49, §3.1 :85–95, §9.1 :224–228, §9.3
   :238; CMP-079 RbacGate `15` :811; CMP-019 Icon `lock` :225). A control gated by a role, grant,
   environment, session or **registered state** keeps its native role and its full label;
   `aria-disabled="true"`, never the `disabled` attribute, so it stays a Tab stop; a CMP-019 `lock`
   glyph (`decorative=false`, name "Not available") leads the label in the same colour; the reason
   sits under it (2a inline; 2b tooltip echo only for icon-only controls), in the DOM at mount and
   linked by `aria-describedby`; on SCR-142 every gated control points at the one panel notice and
   carries no reason line of its own; `Enter`, `Space` or a bound hotkey changes nothing and
   re-shows the reason once, politely; a T2 control emits no audit and no analytics; role legs are
   wrapped in CMP-079. Hi-fi: the label `color.text.tertiary`, the reason `color.text.secondary`,
   the fill `color.surface.raised` with a `color.border.default` hairline; never
   `color.text.disabled`, never `opacity.disabled`. Reasons are `rbac.*` keys with the §3.2 verb
   (`recording:write` → "change recording", :108) or a registered state key; a screen never writes
   its own string, and a reason never names data — no symbol, count, size or user name (except the
   view-as target) — one sentence, at most ⟦audit:layout.reason_max⟧ characters, a full stop. **On
   this page the only T2 is the view-as leg** (BQ-8 RULED, A1): the Owner viewing as another user;
   `rbac.owner_only` is named in §9 for completeness and no frame draws it, because a non-owner
   never reaches `/admin/*`. This page needs no new state key (E16-D02 §8.5's form would govern
   one; D04-Q4 names the one candidate and keeps it a status).
@ §1 › §1.3#1 ¶3 ‖ paragraph
  **The validity look is not T2** (E09-D09 §9.1 :230; E30-D02 D3 :128): a control disabled by form
   validity keeps its own fill and label at `opacity.disabled` (⟦audit:opacity_disabled⟧), the
   reason at full opacity under or beside it in `color.text.secondary` (never inside),
   `aria-disabled`, focusable; a press shows the error summary; no lock glyph, no CMP-079, no key;
   board layer `validity-reason`. On SCR-142 two controls take it: Import archives while the range
   is empty, inverted or longer than ⟦audit:facts.import_days_max⟧ days (`22` :14982), and the
   purge dialog's Confirm while the typed symbol differs or the reason is shorter than
   ⟦audit:facts.reason_min⟧ characters (E16-D02 :419; CMP-044 :477 "form validity, not a gate").
   Never over-converted.
@ §1 › §1.3#1 ¶4 ‖ paragraph
  **Status · outcome · absence · refusal** (E09-D09 §9.1 :231; the orchestrator's conditions A1
   and A3). **Busy** — a job this client started while it is queued or running: the button is
   CMP-001 `loading` with `aria-busy`, focusable, a press opens nothing, no lock (E16-D02 §6.6
   :422–426). **Status** — the five states of the ticket: disk full (`level` 3, the gate closed), a
   tier unreachable, the ingestion backlog, a pending migration (PROPOSED, D04-G7) and a stale
   sample are states of the system with notices and tones; no control is gated by them, and the
   actions that would be refused are refused by the server at the point of action (BQ-14, BQ-15
   RULED). **Outcome** — a job's terminal state and the import summary: one polite announcement
   each, never a gate. **Absence** — a capability the contract defers (cancel, vacuum, row counts,
   slow queries, per-tier growth and projection, the sparkline history, Apply migrations: D04-G10,
   G8, G3, G5, G1, G2, G7) is drawn absent from every frame's default and appears only as a
   captioned PROPOSED inset or second row, never as a lock (BQ-11 / 13 / 16 / 18 / 22 RULED).
   **Refusal (T4)** — `409 job_running`, `422 import_range_invalid`, `422
   purge_confirmation_mismatch`, `422 retention_pinned_refused`, the `503` when the purge's audit
   record cannot be written (`22` :15073–15075), and `403 step_up_required` (not a refusal: it runs
   the SCR-006 step-up, E16-D02 §6.4): CMP-027 inline under the control with the server's code in
   parentheses, polite once; the page state never changes and nothing else dims. **Exits and links
   are never gated** (A3): Cancel, Esc and the close ✕ in every dialog, Retry, the links to SCR-140
   / SCR-141 / SCR-143, the per-tier table alternatives — enabled for every role on every frame.
@ §1 › §1.3#1 ¶5 ‖ paragraph
  **The classification (every state row of §2 and §4–§8 names one class):**
@ §1 › §1.3#1 ¶6 ‖ table
  | Control × condition | Class | Reason / look (source) |
  |
   --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ------------------------ |
   ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | every write while viewing as — Compact Parquet…, Purge data… and the per-symbol Purge… (the
   row's detail popover), Import archives, Stop job on the jobs strip (PROPOSED D04-G10) and the
   Vacuum Postgres… inset (PROPOSED D04-G8) | **T2** (first leg) | `rbac.view_as` "Read-only while
   viewing as {user}.", one panel notice under the header (the D-16 text, E16-D02 :778); every
   gated control's `aria-describedby` → it (one notice, many pointers); reads, the meters, the
   tables and a running job's progress keep updating — E09-D09 §2.1 step 3, §3.1 :95; CMP-079
   `form="notice"` |
  | a Manager or a Viewer | not a state of this page | the route is hidden and hard-404s (`14`
   :43, :85; E16-D02 §7 :449); SCR-142 draws neither; the server is the control (C-12.4) |
  | Import archives while the range is empty, inverted or over 366 days; the purge Confirm while
   the typed symbol differs, the reason is short or the `before` bound is later than now |
   **validity look** | own fill + label at `opacity.disabled`, the reason full-opacity under it:
   "Choose a range of at most 366 days." · "Type ETHUSDT exactly to confirm." · "Choose a time no
   later than now."; never T2 (E09-D09 §9.1 :230; E30-D02 D3 :128) |
  | Compact Parquet… / Import archives / Purge… while this client's job of that kind is queued or
   running | **busy** | CMP-001 `loading`, `aria-busy`, focusable, a press opens nothing; the strip
   shows the progress; no lock (E09-D09 §9.1; E16-D02 §6.6) |
  | `409 job_running` (a second press, or after a reload with no job id) · `422
   import_range_invalid` · `422 purge_confirmation_mismatch` · `422 retention_pinned_refused` ·
   `422 validation_failed` (`before_in_future`: a `before` later than the server's clock, its time
   in `message`) · the purge's `503` when its audit record cannot be written | **T4** | the refusal
   sentence under the control at the point of action with the code in parentheses (§6, §7, §8);
   `403 step_up_required` runs the step-up flow instead (§7) |
  | disk full (`level` 3, `write_gate` closed) · a tier `down` · the ingestion backlog · a pending
   migration (PROPOSED, D04-G7) · a stale sample | **status** | notices and tones (§5); every write
   stays enabled; a refusal, if any, is T4 at the point of action; Shorten retention / Reduce depth
   / Unpin stay links (BQ-14, BQ-15 RULED) |
  | Stop job (cancel a running job) · Vacuum Postgres · row counts by table · slowest queries ·
   per-tier growth and projection · the sparkline history · Apply migrations | **absence** |
   shipped absent (`22` has no cancel route, no vacuum route or kind, no such fields: §12; D04-G10,
   G8, G3, G5, G1, G2, G7); drawn only as a captioned PROPOSED inset or second row with the shipped
   fallback beside it; never a lock (A1; BQ-11 / 13 / 16 / 18 / 22 RULED) |
  | a job's succeeded · failed · cancelled · unknown line; the import summary | **outcome** |
   polite live region, one announcement per terminal state (`05` §6.2 :146–150; CMP-023 `15` :267);
   a failed purge (E16-D02 :200) and a failed import, inside its card, are `role="alert"` once |
  | exits and links: Cancel, Esc and the close ✕ in a dialog, Retry, the per-tier table
   alternative, SCR-140 / SCR-141 / SCR-143 | **T1** | never gated for any role (A3) |
@ §1 › §1.4#1 ¶1 ‖ heading
  ### 1.4 The degradation ladder and the AC 2 sentence
@ §1 › §1.4#1 ¶2 ‖ paragraph
  The ladder is the server's (`20` :904–908; `24` §13.4.1 :3833–3840): at 80 % of the recording
   budget (or a runway ≤ 7 days) a warning; at 90 % new auto-record starts are refused and
   retention accelerates; at 95 % (or less than 5 % of the volume free) the write gate closes and
   symbols without an open position are dropped as gaps — open positions keep writing (`24` :3854:
   INV-B11-a outranks ADR-0015's "recording halts"; E16-D02 :496). Nothing on the ladder touches
   order placement (`24` :3845 "Order placement never reads the budget"). The design states the
   order in text on every level ≥ 1 frame (AC 2): **"Recording pauses before trading is
   affected."** (`storage.degradation`, a `new` key, §14), followed by the detail line "At 90 % of
   the recording budget auto-record pauses; at 95 % recording stops for symbols without an open
   position; orders and positions are never gated by the disk." The tool reads the sentence on
   every frame whose producer is `level` ≥ 1 and fails an inverted order (§12 R-5).
@ §2#1 ¶1 ‖ heading
  ## 2. SCR-142 — anatomy (board 01; `SCR-142/healthy` is the anatomy frame)
@ §2#1 ¶2 ‖ paragraph
  A section of `/admin/recorder` (BQ-6 RULED; `14` :2772 "Page section"), reached from SCR-140's
   disk card ("Storage details →", a link E16-D02's card gains as D04-A4's companion line) and from
   SCR-143's recorder / DB tile (`14` :2794–2795), inside the CMP-087 AdminLayout shell with its
   re-auth badge (`14` :43). Reference viewport ⟦audit:layout.vp_w⟧ × ⟦audit:layout.vp_h⟧ at 100 %,
   comfortable density (`16` §3: ⟦audit:layout.row_px⟧ px rows and controls, the admin default),
   the admin nav ⟦audit:layout.nav_px⟧ px as E16-D02 D-12 assumes it; dark is the default, the
   light twins are board 10. ⟦audit:layout.regions⟧ regions, top to bottom; cards are CMP-050 on
   `color.surface.raised` with a `color.border.default` hairline, ⟦audit:layout.card_w⟧ px wide in
   a three-up row, stacking below 1024 px and at 200 % zoom.
@ §2#1 ¶3 ‖ sketch
  ```
  +-- Admin area · Recorder › Storage and database -------------------------- re-auth mm:ss --+
  | (a) Storage and database            Sampled 10:31:03 UTC (every 60 s)   [view-as notice]  |
  | (b) Recording budget  [########------------]  1,188.0 GB of 2,000.0 GB cap_bytes (59.4 %)  |
  |     Growing · auto-record pauses in about 422 days   80 % · 90 % · 95 % scale              |
  |     Disk volume       [######--------------]  1.2 TB of 4.0 TB disk_total_bytes (30.1 %)   |
  |     Full in about 560 days (2028-03-27) at 1.45 GB/day: the budget is the nearer wall        |
  | (c) [QuestDB · hot]        [Parquet/DuckDB · cold]      [Postgres · relational]             |
  |     Size 640.0 GB          Size 548.0 GB                Size 16.0 GB                        |
  |     Retention 7 d          Retention 30 d               Retention —                         |
  |     Growth/day — ¹         Growth/day — ¹               Growth/day — ¹                      |
  |     Projected full — ¹     Projected full — ¹           Projected full — ¹                  |
  |     Health ✓ healthy       Health ✓ healthy             Health ✓ healthy · Migration —      |
  |     [ Purge data… ]        [ Compact Parquet… ]         (no purge entry)                    |
  |                            [ Purge data… ]                                                  |
  | (d) ▸ Tables ²     (e) Per-symbol (hot); Purge… in the row popover     (f) Queries ³        |
  | (g) Maintenance  [ Compact Parquet… ]   ┆ Vacuum Postgres… ⁴ ┆                               |
  |     jobs strip: (empty at rest)                                                             |
  | (h) Import archives  Symbol [BTCUSDT ▾]  From [2026-01-01] To [2026-01-31]  [Import archives]|
  |     Archive-derived · trades only · no book data                                            |
  +---------------------------------------------------------------------------------------------+
  ¹ PROPOSED — D04-G1, owner approval pending (#2701); the shipped fallback beside it: all tiers 1.45 GB/day, all tiers 2028-03-27
  ² PROPOSED — D04-G3, owner approval pending (#2701): a captioned second row per tier
  ³ PROPOSED — D04-G5, owner approval pending (#2701): a captioned second row
  ⁴ PROPOSED — D04-G8, owner approval pending (#2701): a captioned inset
  ```
@ §2#1 ¶4 ‖ table
  | Region | Content |
  | ------ |
   -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | (a) | H2 "Storage and database" (`type.ui.heading-lg`); the sample stamp "Sampled {HH:MM:SS}
   UTC (every 60 s)" from `generated_at` (`22` :19233) and `CV_DISK_SAMPLE_INTERVAL_S` (`20` :908),
   `type.ui.caption` `color.text.secondary`, with CMP-239 `stale` and its clock glyph once the
   report is older than ⟦audit:layout.stale_factor⟧ samples (`14` §0.5 rule 4 :84: the last-good
   time always shown); the one view-as notice slot (0 px unless viewing as) |
  | (b) | two CMP-023 `kind="meter"` (`15` :265), each labelled with what it divides (D04-D1,
   D04-A2): **Recording budget** = (questdb + parquet `used_bytes`) ÷ `cap_bytes` (`22` :5423–5424;
   `23` :4071) with E16-D02 §8.3's headline keyed on `level`; **Disk volume** = `disk_used_bytes` ÷
   `disk_total_bytes` with `disk_free_bytes`; under them the projection line and E16-D02's formula
   and threshold scale; the AC 2 sentence on every level ≥ 1 frame (§1.4); the fill tone by `level`
   (0 primary, 1–2 warning, 3 danger) |
  | (c) | three tier cards (CMP-050 + CMP-036 rows; the CMP-178 tone from `components[].state`):
   the rows of §4; a card in `down` keeps its shell with a CMP-027 inline error and Retry |
  | (d) | per-tier tables (CMP-049 table variant inside a CMP-051 Accordion per card): Table /
   Rows / Size / Oldest / Newest — PROPOSED `tiers[].tables[]` (D04-G3), drawn only as a captioned
   second row |
  | (e) | the hot-tier per-symbol table (CMP-049 table variant): Symbol / Size / Growth/day /
   Share of budget / Pinned from `symbols[]`; Oldest / Newest and the sparkline only as captioned
   PROPOSED carriers (D04-G2; BQ-22 RULED); Purge… in each row's detail popover (D04-D3) |
  | (f) | query performance (CMP-049): Tier / Statement kind / p95 / Count (1 h) — PROPOSED
   `slow_queries[]` (D04-G5), a captioned second row; never SQL text, never a console (SR-048) |
  | (g) | maintenance (CMP-050): CMP-001 secondary "Compact Parquet…"; "Vacuum Postgres…" only as
   the captioned PROPOSED inset (D04-G8); the jobs strip (E16-D03 §8's grammar): one line per
   running job this client started, "{Verb} running · {pct} %" + CMP-023, and Stop job as a
   captioned PROPOSED carrier (D04-G10) |
  | (h) | import (CMP-050): Symbol (CMP-009), From / To (CMP-047 range, ≤ 366 days), the
   consequence line, "Import archives" (CMP-001 primary); while running the overall CMP-023 with
   "{done} of {n} days" (`progress_pct` with the requested range); the per-file CMP-049 table (Day
   / Status / Reason / Rows), the skip counter and the overlap report only as captioned PROPOSED
   insets (D04-G11); the CMP-011 tag "Archive-derived · trades only · no book data" (`22`
   :14984–14985) |
@ §2#1 ¶5 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | -------------------------- |
   -------------------------------------------------------------------------------------------------------
   |
   ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ----- | ----- |
  | `SCR-142/healthy` | `level` 0 (budget 59.4 %), every `components[].state` healthy, no pending
   migration (D04-G7 absent) | stamp Sampled 10:31:03 UTC (every 60 s) · meter Recording budget:
   1,188.0 GB of 2,000.0 GB cap_bytes (59.4 %), headline "Growing · auto-record pauses in about 422
   days" (E16-D02 :490) · meter Disk volume: 1.2 TB of 4.0 TB disk_total_bytes (30.1 %), free 2.8
   TB · the projection line "Full in about 560 days (2028-03-27) at 1.45 GB/day: the budget is the
   nearer wall (the volume about 1,928 days)" · the formula line "(90 % × 2,000.0 GB − 1,188.0 GB)
   ÷ 1.45 GB/day ≈ 422 days" · the scale "80 % warning · 90 % auto-record pauses · 95 % recording
   stops (open positions keep writing)" · three tier cards (§4) · the per-symbol table, the
   maintenance card and the import card at rest | Compact Parquet…, Purge data…, Import archives
   enabled (T1) · Vacuum Postgres… only as the inset PROPOSED — D04-G8, owner approval pending
   (#2701) · links to SCR-140, SCR-141 and SCR-143 enabled (T1) | T1 | 01 |
  | `SCR-142/healthy-200-zoom` | the same report at ⟦audit:layout.zoom_pct⟧ % zoom and the in-app
   text scale (1280 × 800) | the two meters stacked, full width · the three tier cards stacked one
   per row · every table one row element per record (CMP-049 reflow, `15` :528) · the import card's
   form fields stacked one per row · nothing hidden, no horizontal scroll · forced-colors: the
   meter fills take the system accent with their value text beside them, the tone glyphs keep their
   words (`14` :86) | as `SCR-142/healthy` (T1) | T1 | 01 |
@ §3#1 ¶1 ‖ heading
  ## 3. Data bindings and the fixture
@ §3#1 ¶2 ‖ paragraph
  Every element binds to a shipped field or is a PROPOSED gap (D04-Gn, §13) drawn with its shipped
   fallback beside it. The page reads `GET /recording/storage` once on entry and every 60 s while
   open, `GET /admin/health` with it (the tier health), and the WS `recorder` topic for the two
   ingestion-pressure numbers and the live `storage` object (`23` :4062–4085) — the level, the gate
   and the headline never lag the gate (E16-D02 :152).
@ §3#1 ¶3 ‖ table
  | UI element | Field (source) | Unit shown | Gap |
  | ----------------------------------------------------- |
   --------------------------------------------------------------------------------------------------------------------------------------------
   | ----------------------- | ------------------------------- |
  | the sample stamp | `StorageUsage.generated_at` (`22` :19233); the cadence
   `CV_DISK_SAMPLE_INTERVAL_S` 60 s (`20` :908) | HH:MM:SS UTC, s | — |
  | the budget meter | `tiers[]` questdb + parquet `used_bytes` ÷ `cap_bytes` (`22` :5423–5424,
   :19216–19223, :19234); live `storage.used_bytes` (`23` :4068–4071) | GB, % | — |
  | the volume meter | `disk_used_bytes` ÷ `disk_total_bytes`, `disk_free_bytes` (`22`
   :19211–19213) | TB, % | — |
  | the headline, the gate, the suggested actions | `level`, `write_gate`, `write_gate_reason`,
   `accelerate_retention` (`22` :19235–19243; `23` :4073–4079); E16-D02 §8.3's grammar | words | —
   |
  | the projection line and the formula | `projected_full_at`, `daily_growth_bytes` (`22`
   :19214–19215; `24` :3830: to the nearer wall); the ladder percentages (`20` :905–907) | days,
   date, GB/day | — |
  | per-tier size and retention | `tiers[] {tier, used_bytes, retention_days}` (`22` :19216–19223)
   | GB, d ("—" when null) | — |
  | per-tier growth rate and projected full date (AC 1) | none: only the disk-level numbers exist;
   the card shows them labelled "all tiers" and "—" per tier | GB/day, date | D04-G1 |
  | per-tier health, the "unreachable" state | `HealthReport.components[] {name, state,
   last_good_at}` (`22` :21850–21860; names from the example :11014–11026) | the ComponentState
   word | — (D04-CG1) |
  | the per-symbol table | `symbols[] {symbol, used_bytes, daily_growth_bytes, pinned}` (`22`
   :19224–19232) | GB, MB/day, % | — |
  | per-symbol oldest / newest, the sparkline history | none | UTC date, GB | D04-G2 |
  | rows by table, oldest / newest per table | none; the table names are `21` §4.1–4.13's
   (⟦audit:facts.questdb_tables⟧ headings) and §5.1's partition families | count, GB, UTC date |
   D04-G3 |
  | ingestion pressure; "ingestion lag" | WS `ingest_rate_msgs_per_sec`, `write_backlog_rows`
   (`23` :4060–4061); `24` :494's `ingest_lag_seconds{stream}` is a metric, not a field | msg/s,
   rows; ms | D04-G4 (the lag cell, PROPOSED) |
  | slowest queries | none | ms, count | D04-G5 |
  | last compaction / last vacuum | none; the schedule is a fact (`21` :4410 weekly, Sundays 03:00
   UTC) | UTC time | D04-G6 |
  | the schema version and pending migrations | none; `HealthReport.version` / `git_sha` (`22`
   :21840–21841) are release facts; readiness = "migrations applied" (`22` :11103) | version, count
   | D04-G7 |
  | compaction, purge, import progress | `202 {job_id}` → `getJob`: `Job.status`, `progress_pct`,
   `result` (`22` :22016–22020; E16-D02 :157: bytes and partitions only from `result`) | %, GB | —
   (D04-G9 the kind word) |
  | a vacuum | none: no route, no `Job.kind` (`22` :22002–22014); `21` :4332 "the API never issues
   DDL against QuestDB at runtime except the retention job" | — | D04-G8 |
  | cancel a running job | none: `getJob` only (`22` :12097–12133) | — | D04-G10 |
  | the import summary: per-file status, reasons, overlap | `Job.result` "carries the import
   summary" (`22` :14987) with no schema | days, rows | D04-G11 |
  | the archive-derived label on coverage | prose only (`22` :14984–14985) | a tag | D04-G12 |
@ §3#1 ¶4 ‖ paragraph
  **The fixture** is the header's: the `22` example (:5435–5462) and its derived states, every
   number the tool's: budget 59.4 %, volume 30.1 %, runway about 560 days to 2028-03-27 (the budget
   wall; the volume's wall about 1,928 days), autostop runway about ⟦audit:fixture.autostop_days⟧
   days, "In 30 days: about ⟦audit:fixture.used30_gb⟧ GB"; level 1 at 80.5 % (1,610.0 GB; about
   ⟦audit:fixture.level1_runway⟧ days to autostop), level 2 at 90.0 % (about
   ⟦audit:fixture.level2_runway⟧ days to the halt), level 3 at 95.0 %; a tier down since
   ⟦audit:fixture.last_good⟧ UTC (7 min before the sample); the backlog
   ⟦audit:fixture.backlog_rows⟧ rows (5 ILP batches of 5,000 rows, `21` :4323; the healthy frames'
   backlog ⟦audit:fixture.healthy_backlog_rows⟧ rows) at ⟦audit:fixture.ingest_rate⟧ msg/s (the
   health example's "ingest 18.4k msg/s", `22` :11019); migration ⟦audit:fixture.schema_version⟧ →
   ⟦audit:fixture.target_version⟧, ⟦audit:fixture.pending⟧ pending (the latest migration `22`
   :14395 names; ⟦audit:fixture.healthy_pending⟧ pending on the healthy card); the import BTCUSDT
   2026-01-01 → 2026-01-31, ⟦audit:fixture.import_days⟧ days (≤ 366), ⟦audit:fixture.running_done⟧
   done at ⟦audit:fixture.running_pct⟧ % on the running frame, ⟦audit:fixture.skip_processed⟧
   processed (⟦audit:fixture.skip_done⟧ done, 1 skipped) at ⟦audit:fixture.skip_pct⟧ % on the skip
   frame, ⟦audit:fixture.overlap_rows⟧ overlapping rows (10 min of `14` :2792's 1.1k trades/s) and
   ⟦audit:fixture.rows_per_day⟧ rows per imported day; a compaction at ⟦audit:fixture.compact_pct⟧
   % (E16-D02 :425's figure); the compaction thresholds ⟦audit:fixture.merge_mib⟧ MiB,
   ⟦audit:fixture.trigger_files⟧ files, ⟦audit:fixture.trigger_mib⟧ MiB (`21` :4414–4415); the
   purge example ETHUSDT, about 1.2 GB, before ⟦audit:fixture.purge_before⟧ (the Parquet cut-off),
   its window from ⟦audit:fixture.purge_from⟧ (the symbol's bytes over its growth, ending at the
   cut-off; the live dialog reads the window from the coverage intervals, E16-D02 :420).
@ §4#1 ¶1 ‖ heading
  ## 4. Tier cards and the tables (board 02; 6 frames)
@ §4#1 ¶2 ‖ paragraph
  The three cards are the AC 1 surface: Size · Share of budget · Retention · Growth/day ·
   Projected full · Health, then the tier's own rows. Of the three AC 1 numbers only the disk-level
   growth and projection are produced today (`22` :19214–19215): every card's Growth/day and
   Projected full cells read "—" with the caption PROPOSED (D04-G1) and the shipped fallback beside
   them ("all tiers 1.45 GB/day", "all tiers 2028-03-27"), so the board is honest about today and
   the tool fails a tier row whose cell is neither a figure with a unit nor the captioned fallback
   (§12 R-1). Health is the `ComponentState` word (`22` :17419) with its glyph (✓ healthy · ⚠
   degraded / warning · ✗ down · "not deployed" plain), never colour alone (`14` :86, :2777). Every
   figure carries a unit. The CMP-178 tile for SCR-143's link carries `label · value · unit · tone`
   (D04-A1 adds the `unit` requirement and the tone ↔ `ComponentState` map). Row counts (D04-G3),
   the slowest queries (D04-G5), last compaction / vacuum (D04-G6) and the schema version (D04-G7)
   appear only as captioned PROPOSED second rows with their shipped fallback (BQ-18 RULED); no card
   links a console (SR-048) and no card carries a backup control (`21` §8). Purge data… sits on the
   QuestDB and Parquet cards only: `purgeRecordedData` deletes recorded data from QuestDB and
   Parquet (`22` :15035–15057; E16-D02 :410), and the Postgres tier holds none of it, so its card
   has no purge entry.
@ §4#1 ¶3 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | ------------------------ |
   -------------------------------------------------------------------------------- |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ----- | ----- |
  | `TIER/questdb` | `tiers[].tier` questdb; `components[]` questdb healthy | Size 640.0 GB ·
   Share of budget 32.0 % · Retention 7 d · Growth/day — (PROPOSED — D04-G1, owner approval pending
   (#2701), shipped fallback beside it: all tiers 1.45 GB/day) · Projected full — (PROPOSED —
   D04-G1, owner approval pending (#2701), shipped fallback beside it: all tiers 2028-03-27) ·
   Health healthy, the text word with the ✓ glyph (ComponentState) · Ingestion "Ingest 18,400
   msg/s, backlog 0 rows" from the WS topic, lag — (PROPOSED — D04-G4, owner approval pending
   (#2701)) · Rows by table — (PROPOSED — D04-G3, owner approval pending (#2701)), the per-table
   CMP-049 as a captioned second row · no Last compaction row on the hot tier (compaction is a
   Parquet operation) | Purge data… (T1, opens E16-D02 §6.5) · no console link (SR-048) · no backup
   control (`21` §8 is SCR-143 / E42's) | T1 | 02 |
  | `TIER/parquet` | `tiers[].tier` parquet; `components[]` parquet_store healthy | Size 548.0 GB
   · Share of budget 27.4 % · Retention 30 d · Growth/day — (PROPOSED — D04-G1, owner approval
   pending (#2701), shipped fallback beside it: all tiers 1.45 GB/day) · Projected full — (PROPOSED
   — D04-G1, owner approval pending (#2701), shipped fallback beside it: all tiers 2028-03-27) ·
   Health healthy, the text word with the ✓ glyph · Last compaction — (PROPOSED — D04-G6, owner
   approval pending (#2701), shipped fallback beside it: the schedule "weekly, Sundays 03:00 UTC",
   `21` :4410) · Rows by table — (PROPOSED — D04-G3, owner approval pending (#2701)) | Compact
   Parquet… (T1) · Purge data… (T1, opens E16-D02 §6.5) · no console link · no backup control | T1
   | 02 |
  | `TIER/postgres` | `tiers[].tier` postgres (`retention_days` null); `components[]` postgres
   healthy | Size 16.0 GB · Share of budget not counted (the meter divides questdb + parquet only,
   `22` :5424) · Retention — · Growth/day — (PROPOSED — D04-G1, owner approval pending (#2701),
   shipped fallback beside it: all tiers 1.45 GB/day) · Projected full — (PROPOSED — D04-G1, owner
   approval pending (#2701), shipped fallback beside it: all tiers 2028-03-27) · Health healthy,
   the text word with the ✓ glyph · Last vacuum — (PROPOSED — D04-G6, owner approval pending
   (#2701)) · Migration — (the shipped fallback: the release version from `HealthReport.version`,
   not a schema version) · a captioned second row PROPOSED — D04-G7, owner approval pending
   (#2701): Migration 0008, 0 pending · Rows by table — (PROPOSED — D04-G3, owner approval pending
   (#2701)) | Vacuum Postgres… only as the inset PROPOSED — D04-G8, owner approval pending (#2701)
   · no purge entry on this card: purge deletes QuestDB and Parquet data only (`22` :15035–15057) ·
   no console link · no backup control | T1 | 02 |
  | `TIER/tables-questdb` | PROPOSED `tiers[].tables[]` (D04-G3); the shipped frame carries no
   table | a captioned second row "PROPOSED — D04-G3, owner approval pending (#2701)": CMP-049
   table variant, columns Table / Rows / Size / Oldest / Newest, one row per `21` §4.1–4.13 table
   name (trades, orderbook_deltas, orderbook_snapshots, tickers, klines, liquidations,
   open_interest, funding_rates, bars_<type>, footprint_cells, profiles, orderflow_metrics,
   heatmap_cells, engine_metrics), every Size cell with a unit, Rows as a count, Oldest / Newest as
   UTC timestamps as text · the shipped fallback beside it: "Row counts by table are not produced
   yet" | none (a read) | T1 | 02 |
  | `TIER/per-symbol` | `symbols[]` (shipped) | CMP-049 table variant: Symbol / Size / Growth/day
   / Share of budget / Pinned, rows BTCUSDT 812.3 GB 780 MB/day 40.6 % pinned and ETHUSDT 1.2 GB
   520 MB/day 0.1 % — · the attribution line "813.6 GB of 1,188.0 GB attributed to symbols (68.5
   %)" (D04-CG3) · Oldest / Newest — (PROPOSED — D04-G2, owner approval pending (#2701)), as a
   captioned second row · the sparkline only as one inset PROPOSED — D04-G2, owner approval pending
   (#2701) on this board (`history_bytes[]`, BQ-22 RULED), with its DOM-mirror table (CMP-024, `15`
   :276) | Purge… in the row's detail popover (T1, opens E16-D02 §6.5 with the symbol preselected,
   the typed field empty; D04-D3) · Manage pin → SCR-140 (T1) | T1 | 02 |
  | `TIER/query-performance` | PROPOSED `slow_queries[]` (D04-G5); nothing shipped | a captioned
   second row "PROPOSED — D04-G5, owner approval pending (#2701)": CMP-049 table variant, columns
   Tier / Statement kind / p95 / Count (1 h), p95 in ms, the statement kind a closed word (replay
   scan, footprint build, coverage read), never SQL text · the shipped fallback beside it: "Slowest
   queries are not produced yet" · no console link (SR-048 `04` :873) | none (a read) | T1 | 02 |
@ §5#1 ¶1 ‖ heading
  ## 5. Page states (boards 03 and 04; 11 frames; class per §1.3)
@ §5#1 ¶2 ‖ paragraph
  The ticket's five states and E16-D02 §3.1's page states (`SCR-142/loading`,
   `SCR-142/unavailable` and `SCR-142/stale-sample` here, :186–194), each a status with a notice
   and a tone — never a lock (A1; BQ-14 / BQ-15 / BQ-16 RULED). The sample stamp stays on every
   page frame (R-2); every write stays enabled on every state frame and a refusal, if any, is T4 at
   the point of action (§1.3). The AC 2 sentence sits in the level banner on every level ≥ 1 frame
   (§1.4; R-5). The view-as frame is the one T2 frame of this spec and is listed first among the
   gated legs wherever they appear (§1.3, §9; R-13).
@ §5#1 ¶3 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | ---------------------------------- |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ------ | ------ |
  | `SCR-142/low-disk-warning` | `level` 1 (budget 80.5 %: the `14` :2748 figure scaled to this
   cap, 1,610.0 GB of 2,000.0 GB) | stamp Sampled 10:31:03 UTC (every 60 s) · the budget meter at
   80.5 % · headline "Near limit · auto-record pauses in about 131 days · clears below 75 %"
   (E16-D02 §8.3 :490) · CMP-028 warning banner with the AC 2 sentence "Recording pauses before
   trading is affected." and the detail line of §1.4 · the budget meter fill
   `color.status.warning.strong` with the ⚠ glyph before the value text · the suggested actions
   Shorten retention (→ SCR-141), Reduce depth and Unpin (→ SCR-140) as links (T1) | every write
   enabled (T1); nothing is gated by the level | status | 03, 10 |
  | `SCR-142/autostop` | `level` 2 (budget 90.0 %, 1,800.0 GB) | stamp Sampled 10:31:03 UTC (every
   60 s) · the budget meter at 90.0 % · headline "Auto-record paused · resumes below 85 % of the
   budget with 20 % of the volume free" (E16-D02 :494) · the warning banner with the AC 2 sentence
   "Recording pauses before trading is affected." and "Recording stops at 95 % in about 69 days" ·
   `accelerate_retention` true reads "Retention accelerated" as a status word beside the headline ·
   the suggested actions as links (T1) | every write enabled (T1) | status | 03 |
  | `SCR-142/read-only-disk-full` | `level` 3, `write_gate` closed, `write_gate_reason` disk_halt
   (budget 95.0 %, 1,900.0 GB) | stamp Sampled 10:31:03 UTC (every 60 s) · the budget meter at 95.0
   % · headline "Recording stopped · resumes below 90 % with 10 % of the volume free" (E16-D02
   :496) · the level-3 fact "Open positions keep recording; other symbols' data is dropped and
   recorded as gaps." · the AC 2 sentence "Recording pauses before trading is affected." · the
   budget meter fill `color.status.danger.default` with the ✗ glyph · the suggested actions Shorten
   retention (→ SCR-141), Reduce depth and Unpin as links (T1) | Compact Parquet…, Purge data… and
   Import archives stay enabled (they free space or add to the cold tier; BQ-14 RULED): no lock, no
   validity look, no pre-emptive disable; a server refusal shows in the CMP-044 result as T4, never
   as a disabled control | status | 03 |
  | `SCR-142/volume-refused` | `level` 3, `write_gate` closed, `write_gate_reason` volume_refused
   (the bytes unchanged: 1,188.0 GB) | stamp Sampled 10:31:03 UTC (every 60 s) · headline
   "Recording stopped · resumes below 90 % with 10 % of the volume free" with the cause line "The
   recording volume was refused at start-up; the gate opens once it is fixed" · the AC 2 sentence
   "Recording pauses before trading is affected." · the meters at their last values, the budget
   fill danger · `level` 3 shown as the gate's level, never derived from the bytes (`22`
   :5416–5418) | every write enabled (T1); the same T4 rule on a refusal | status | 03 |
  | `SCR-142/view-as` | `GET /auth/session/view-as` reports an active context (the Owner viewing
   as alex); `level` 0 | stamp Sampled 10:31:03 UTC (every 60 s) · one notice under the header: ⚿
   "Read-only — read-only while viewing as alex." (`notice.panel_read_only`, E16-D02 D-16 :778
   text, an A-row to E09-D09 §10 pending there) · the meters, the tier cards, the tables and the
   jobs strip read as for the target (unchanged reads) · a running job still shows its progress
   (status) | every write T2 (the view-as leg first, E09-D09 §2.1 step 3): Compact Parquet…, Purge
   data…, Import archives, the per-symbol Purge… in the row's detail popover, Stop job on the jobs
   strip (PROPOSED — D04-G10, owner approval pending (#2701)) and the Vacuum Postgres… inset
   (PROPOSED — D04-G8, owner approval pending (#2701)) each keep the full label with the lock glyph
   leading it, `aria-disabled`, `aria-describedby` → that node, the reason key `rbac.view_as`
   "Read-only while viewing as {user}.", fill `color.surface.raised` + `color.border.default`
   hairline, label `color.text.tertiary`, reason `color.text.secondary`, never
   `color.text.disabled` nor `opacity.disabled` · Enter / Space re-show the reason once, politely ·
   links to SCR-140, SCR-141 and SCR-143 enabled (T1) | T2 | 03, 10 |
  | `SCR-142/tier-unreachable-questdb` | `HealthReport.components[]` questdb `state` down,
   `last_good_at` 10:24:03 UTC; the other two healthy; `level` 0 | stamp Sampled 10:31:03 UTC
   (every 60 s) · the QuestDB card keeps its shell with CMP-027 inline "QuestDB unreachable since
   10:24:03 UTC" + Retry (re-poll, T1) and its last sizes tagged stale · the other two cards, the
   meters and the tables unchanged: page usable, no page-level error, no `role="alert"` · the
   CMP-178 tile tone danger with the word "down" (text, not colour alone) | Compact Parquet…, Purge
   data…, Import archives enabled (T1); an action that needs QuestDB is refused by the server at
   the point of action (T4 with the code), never pre-emptively disabled | status | 04 |
  | `SCR-142/lag-warning` | WS `recorder` `write_backlog_rows` 25,000 (5 ILP batches of 5,000
   rows, `21` :4323) for two samples; `ingest_rate_msgs_per_sec` 18,400 (`22` :11019); `level` 0 |
   stamp Sampled 10:31:03 UTC (every 60 s) · CMP-028 warning "Ingestion backlog 25,000 rows —
   writes are behind the feed" · the QuestDB card's Ingestion row "Ingest 18,400 msg/s, backlog
   25,000 rows, lag —" with the lag cell captioned PROPOSED — D04-G4, owner approval pending
   (#2701), the card tone warning and the word "warning" · the threshold stated beside the banner,
   5 batches (PROPOSED — D04-G4, owner approval pending (#2701), D04-Q4) | every write enabled (T1)
   | status | 04 |
  | `SCR-142/migration-pending` | PROPOSED `pending_migrations` 1, `schema_version` 0008,
   `target_version` 0009 (D04-G7; the shipped frame has no banner); `level` 0 | stamp Sampled
   10:31:03 UTC (every 60 s) · CMP-028 warning banner captioned PROPOSED — D04-G7, owner approval
   pending (#2701): "Migration pending · 1 pending · 0008 → 0009 — applied with the next release" ·
   the Postgres card's Migration row as a captioned second row PROPOSED — D04-G7, owner approval
   pending (#2701): "0008, 1 pending" · the shipped fallback beside it: `HealthReport.version` and
   `git_sha` as the release words | no Apply control: migrations run with the release (`22`
   :11103), a deferred capability drawn absent (A1) · every write enabled (T1) | status | 04 |
  | `SCR-142/stale-sample` | no new report for more than 2 × 60 s (the socket up or down); the
   last report 10:31:03 UTC; `level` 0 | stamp Sampled 10:31:03 UTC, stale (3 min old) with the
   clock glyph (CMP-239 `stale`, `color.data-confidence.stale.indicator`) · every figure keeps
   full-opacity text with a "stale" tag on the meters and the cards (E16-D02 §3.1 :192) · the
   SCR-152 overlay covers a full disconnect | every write enabled (T1); a press is decided by the
   server | status | 04 |
  | `SCR-142/loading` | the first `GET /recording/storage` and `GET /admin/health` in flight |
   skeleton meters and cards (CMP-015), `aria-busy` on the region · the header and the stamp slot
   "Sampling…" · nothing is claimed before the first answer | nothing yet | status | 04 |
  | `SCR-142/unavailable` | `/recording/storage` answers 503 or fails; `/admin/health` answered;
   `level` unknown | stamp Sampled 10:31:03 UTC, stale (3 min old): the last good report's stamp in
   its stale form, never the fresh one (`14` :84; `storage.stamp.stale`) · CMP-028 danger banner
   naming the part: "Disk figures could not be loaded." (E16-D02 §3.1 :191) + Retry (T1) · the tier
   health cards from `/admin/health` stay visible | every write enabled (T1) | status | 04 |
@ §6#1 ¶1 ‖ heading
  ## 6. Maintenance actions and the jobs strip (board 05; 5 frames)
@ §6#1 ¶2 ‖ paragraph
  **Who may run them:** the Owner, on the admin surface, with a fresh re-auth badge (`14` :43);
   the view-as leg first on every one (§1.3). Nothing else gates them. In progress is **busy**,
   never a lock (E16-D02 §6.6 :422–426); a second start while one runs is refused by the server
   with `409 job_running` and shown as T4 at the point of action ("A compaction is already
   running."). Compaction and the PROPOSED vacuum (D04-G8) are **non-destructive** — "Nothing is
   deleted." (`21` §5.4 :4416–4417: the originals are deleted only after the merged output's row
   count and SHA-256 are recorded, a server check this page never shows (the row counts are
   PROPOSED, D04-G3); a vacuum (PROPOSED, D04-G8) reclaims space and deletes no rows) — so both
   take CMP-044 **standard** (E16-D03's `SCR-141/confirm-lengthen` form :210; BQ-10 RULED): a
   title, the body, "This action is audited.", Cancel and the verb; no typed field, no step-up
   unless the server answers 403 (D04-CG2). On SCR-140, E16-D02 §6.6 runs the same
   `compactRecorder` as Compact now with no confirmation (:424); this page confirms it (BQ-10
   RULED), and D04-C6 records the divergence for its owner. Purge keeps E16-D02 §6.5's typed dialog
   with the `recorder` step-up (§7). The vacuum is wholly PROPOSED (D04-G8: no route, no
   `Job.kind`, `22` :22002–22014; `21` :4332) and appears only as a captioned inset (BQ-11 RULED).
   Stop job (cancel a running job) is PROPOSED (D04-G10: `getJob` is the only job route, `22`
   :12097–12133) and appears only as a captioned carrier on the strip, named Stop job so it never
   shares a label with the dialogs' Cancel exit; today a started compaction, purge or import runs
   to its end, and the `cancelled` outcome copy stands because `Job.status` has the word (`22`
   :22016). The jobs strip is one `role="status"` region (E16-D03 §8 :255–268): 2 s polling while
   queued or running, the text swapped in place, progress text first with a CMP-023 whose
   `aria-valuetext` equals the text, one polite announcement at start and one per terminal state —
   never per tick (CMP-023 `15` :267).
@ §6#1 ¶3 ‖ table
  | Action | Route / job | Destructive? | Confirm (§1.3) | Step-up | Progress line | Stop job
   (PROPOSED D04-G10) | Outcomes |
  | --------------- |
   ----------------------------------------------------------------------------------------------------------------------------------
   | ------------------------ |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   -------------------------------------------------------------------------------------------------------------------------------
   | ------------------------------------ | --------------------------- |
   -----------------------------------------------------------------------------------------------
   |
  | Compact Parquet | `compactRecorder` (`22` :14937); `Job.kind` PROPOSED `parquet_compaction`
   (D04-G9); optional `symbols[]`, `older_than_days` 1–3650 | no (`21` :4416–4417) | CMP-044
   standard: "Compact Parquet partitions?" · "Merges small files into partitions of at most 512
   MiB. Nothing is deleted. Replay is paused on partitions it touches." · the audited line · Cancel
   / Compact | none in `22` (D04-CG2) | "Compaction running · 42 %" | PROPOSED (D04-G10) | E16-D02
   §3.2 :203–204 reused: succeeded "Compacted at 10:42 UTC", failed, cancelled, unknown |
  | Vacuum Postgres | PROPOSED `POST /admin/db/vacuum` + `Job.kind` `db_vacuum` (D04-G8): the
   whole action is PROPOSED, captioned on every carrier | no | CMP-044 standard: "Vacuum Postgres?"
   · "Reclaims space from deleted rows. Nothing is deleted. Queries may be slower while it runs." ·
   the audited line · Cancel / Vacuum | none proposed; the owner may require `recorder_purge`
   (D04-Q1) | "Vacuum running · {pct} %" | PROPOSED (D04-G10) | `new` keys
   `storage.vacuum.{succeeded, failed, cancelled, unknown}` mirroring the compact lines |
  | Purge data | `purgeRecordedData` (`22` :15032); `Job.kind` `retention_purge` (:22013) | **yes,
   irreversible** | E16-D02 §6.5's typed dialog, reused whole (§7) | `recorder_purge` class,
   no-grace: a fresh code per purge (`22` :15040, :12495; E16-D02 §6.4), on submit after the typed
   confirm | "Purge of ETHUSDT running · {pct} %" | PROPOSED (D04-G10) | E16-D02 §3.2 :200–202,
   :204 reused |
  | Import archives | `importTradeArchive` (`22` :14978); `Job.kind` `archive_import` (:22012) |
   no (adds; recorded wins) | no dialog: the card form + one consequence line (BQ-12 RULED; §8) |
   none | "Import running · 38 %" | PROPOSED (D04-G10) | §8: the summary, failed, cancelled,
   unknown (`new` keys) |
@ §6#1 ¶4 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | ----------------------- |
   ----------------------------------------------------------------------------------------------------------------
   |
   ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ------- | ----- |
  | `JOB/confirm-compact` | Compact Parquet… pressed | CMP-044 standard (BQ-10 RULED): title
   "Compact Parquet partitions?" · body "Merges small files into partitions of at most 512 MiB.
   Nothing is deleted. Replay is paused on partitions it touches." (`21` :4414, :4417, :4418) ·
   "This action is audited." · no typed field, no step-up sentence (D04-CG2) | exits Cancel, Esc
   and the close ✕ (T1) · Compact (CMP-001 primary, T1) | T1 | 05 |
  | `JOB/confirm-vacuum` | the Vacuum Postgres… inset pressed (the whole action is PROPOSED
   D04-G8; nothing is shipped) | captioned PROPOSED — D04-G8, owner approval pending (#2701):
   CMP-044 standard, title "Vacuum Postgres?" · body "Reclaims space from deleted rows. Nothing is
   deleted. Queries may be slower while it runs." · "This action is audited." · no typed field, no
   step-up sentence unless the owner assigns the `recorder` class (D04-Q1) | exits Cancel, Esc and
   the close ✕ (T1) · Vacuum (CMP-001 primary, T1), PROPOSED — D04-G8, owner approval pending
   (#2701) | T1 | 05 |
  | `JOB/strip-running` | this client's `202` → `Job.status` running for a compaction
   (`progress_pct` 42) and an import (38) | one `role="status"` region (polite), 2 s polling, the
   text swapped in place · "Compaction running · 42 %" + CMP-023 (`aria-valuetext` equal to the
   text) · "Import running · 38 %" + CMP-023 · one announcement at start and one per terminal
   state, never per tick (CMP-023 A11y `15` :267) | Compact Parquet… busy: CMP-001 `loading`,
   `aria-busy`, focusable, a press opens nothing (E16-D02 §6.6 :422; no lock) · Stop job per job
   line, PROPOSED — D04-G10, owner approval pending (#2701): today a started job runs to its end ·
   the other writes enabled (T1) | busy | 05 |
  | `JOB/strip-refused-409` | a second Compact Parquet… press while one runs, or after a reload
   with no job id: the server's `409 job_running` | CMP-027 inline under the control: "A compaction
   is already running." with the code job_running in parentheses, polite once · the page state
   unchanged, nothing dimmed | Compact Parquet… stays enabled (T1): the refusal is T4 at the point
   of action, never a pre-emptive lock | T4 | 05 |
  | `JOB/outcomes` | `Job.status` succeeded / failed / cancelled, or `404 job_unknown` (`22`
   :12117) | insets, one per terminal state, reused from E16-D02 §3.2 (:203–204): compact succeeded
   "Compacted at 10:42 UTC" · compact failed "Compaction failed (`<code>`); nothing was deleted." ·
   compact cancelled "Compaction cancelled; nothing was deleted." (E16-D02's elided "…cancelled."
   completed here: D04-A8) · compact unknown "Compaction status is no longer available on the
   server." · vacuum (PROPOSED — D04-G8, owner approval pending (#2701)) succeeded "Vacuumed at
   {HH:MM} UTC", failed "Vacuum failed (`<code>`); nothing was deleted.", cancelled and unknown as
   `new` keys mirroring the compact lines · each polite, once, with no banner: the words on
   `color.status.success.subtle` / `color.status.danger.subtle` inside the card | none (outcomes) |
   outcome | 05 |
@ §7#1 ¶1 ‖ heading
  ## 7. Purge (board 06; 6 frames) — E16-D02 §6.5 reused whole
@ §7#1 ¶2 ‖ paragraph
  Purge is the one destructive action here: Owner-only, step-up authenticated (a fresh code per
   purge), with a mandatory reason, the typed `confirm_symbol` echo and the window's upper bound
   `before` (`22` :15035–15049, :15086; the ticket's security note). SCR-142 adds **entry points**,
   not a dialog: the QuestDB and Parquet tier cards' "Purge data…" and the "Purge…" in the
   per-symbol row's detail popover (D04-D3) open E16-D02 §6.5's dialog (:404–420) with the symbol
   preselected and **the typed field empty — never pre-filled** (BQ-9 RULED: no second shape). The
   Postgres card has no purge entry: purge deletes QuestDB and Parquet data only (`22`
   :15035–15057; E16-D02 :410). The dialog is reused whole, its window and its roll-off sentence
   included (E16-D02 :410–412). Its date field carries the contract's `before`, **required** (`22`
   :15086): the exclusive upper bound of the purge window `[earliest, before)`, sent as a
   `date-time` instant with an offset and never later than the server's clock (:15051–15054,
   :15092–15097); data recorded at or after it is never deleted by the request or by any retry of
   it (:15053–15054); a bound in the future is `422 validation_failed` with `errors: [{field:
   before, rule: before_in_future}]` and the server's current time in `message` (:15054–15057) — T4
   at the point of action, after the dialog's own validity look on the bound
   (`PURGE/dialog-validity`); the help line under the field, "Data recorded at or after this time
   is kept.", and its two reasons are `new` (§14). The Confirm is enabled only when the reason is
   valid and the typed symbol matches: a validity look, never T2 (CMP-044 :477; E30-D02 D3). The
   `recorder_purge` step-up runs on submit after the typed confirm (`22` :15040; a no-grace class:
   each purge spends a fresh code and no trusted window opens, :12495; E16-D02 §6.4 :380–384: the
   request held and re-sent once with the same Idempotency-Key; SCR-006 cited, not drawn). A pinned
   symbol is refused without Include pinned (`422 retention_pinned_refused`, `22` :15045): T4 at
   the point of action. The audit record (`retention.purge`) is written before the job exists; when
   it cannot be, the server answers 503 and nothing starts (`22` :15073–15075): "Not started: the
   audit record could not be written." (T4). The dialog's confirm line stays "This action is
   audited (high severity)." (E16-D02's words; the name mismatch with `14` :2779 is D04-C1). No
   frame links a QuestDB or DuckDB console (SR-048, `04` :873).
@ §7#1 ¶3 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | ----------------------- |
   -------------------------------------------------------------------------------------------------------------------------------------
   |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | ------------- | ----- |
  | `PURGE/entry-points` | the QuestDB and Parquet tier cards' Purge data… and the Purge… in the
   per-symbol row's detail popover | the entry points drawn on their carriers (the QuestDB card,
   the Parquet card, the row's detail popover), each opening the one E16-D02 §6.5 dialog (:404–420;
   BQ-9 RULED: no second shape) with the symbol preselected from the row, the typed field empty ·
   the Postgres card carries none: purge deletes QuestDB and Parquet data only · the level-3
   banner's Purge data… is SCR-140's (cited) | Purge data… / Purge… (T1, opens E16-D02 §6.5) | T1 |
   06 |
  | `PURGE/dialog` | Purge… pressed on the ETHUSDT row | E16-D02 §6.5's dialog reused whole
   (CMP-043 form, CMP-044 typed, wrapped by CMP-093): title "Purge ETHUSDT data?" · Symbol
   (CMP-009) ETHUSDT · Delete data recorded before (CMP-047 single) 2026-08-15, the retention
   cut-off: the contract's `before`, required (`22` :15086), the exclusive upper bound of the
   window `[earliest, before)` sent as a `date-time` instant with an offset and not later than the
   server's clock (:15051–15054, :15092–15097), with the help line "Data recorded at or after this
   time is kept." under it · "This deletes about 1.2 GB recorded from 2026-08-13 to 2026-08-15 from
   QuestDB and Parquet. It cannot be undone, and replay, footprint history and the journal lose
   this range. Shared QuestDB day partitions are freed by the nightly roll-off." (E16-D02 :410–412,
   whole) · Reason (CMP-007, required, 3–280 characters) · Include pinned (CMP-005) shown only for
   a pinned symbol · Type the symbol to confirm (CMP-007): empty, never pre-filled (the ticket's
   security note) · the step-up sentence "You'll confirm with your password and a code." · "This
   action is audited (high severity)." | exits Cancel, Esc and the close ✕ (T1) · Confirm "Purge
   ETHUSDT data" (CMP-001 danger) enabled only when the reason is valid and the typed symbol
   matches: a validity look while it is not, never T2 (`PURGE/dialog-validity`) | T1 | 06 |
  | `PURGE/dialog-validity` | the typed symbol differs from ETHUSDT, the reason is shorter than 3
   characters, or the `before` bound is later than now (`22` :15054) | the same dialog · Confirm
   "Purge ETHUSDT data" with its own danger fill and label at `opacity.disabled` 0.45, the reason
   full-opacity under it in `color.text.secondary`: "Type ETHUSDT exactly to confirm." (for the
   bound, "Choose a time no later than now.", in the same place) · board layer `validity-reason` ·
   `aria-disabled`, focusable, a press shows the error summary · no lock, no CMP-079, no key
   (E09-D09 §9.1 :230; E30-D02 D3 :128) | exits Cancel, Esc and the close ✕ (T1) | validity look |
   06 |
  | `PURGE/pinned-refused` | Confirm pressed for BTCUSDT (pinned) without Include pinned: the
   server's `422 retention_pinned_refused` | CMP-027 inline under Confirm: "Pinned data is
   excluded. Tick Include pinned to delete it too." with the code retention_pinned_refused in
   parentheses, polite once · the dialog stays open with its inputs | exits Cancel, Esc and the
   close ✕ (T1) · Confirm stays enabled (T1): a refusal is T4 at the point of action | T4 | 06 |
  | `PURGE/step-up` | Confirm pressed with a valid form: the server answers `403 step_up_required`
   with `action_class` `recorder_purge` (`22` :15043) | the step-up sentence "You'll confirm with
   your password and a code." already in the dialog · the SCR-006 step-up modal opens over it
   (cited, E16-D02 §6.4 :380–384; not drawn here), the request held and re-sent once with the same
   Idempotency-Key · `recorder_purge` is a no-grace class (`22` :12495, :15040): each purge spends
   a fresh code and no trusted window opens, so E16-D02 §6.4 :389's "Still trusted for recorder
   changes · {mm:ss}" is never shown here | exits Cancel, Esc and the close ✕ on the modal (T1);
   the dialog keeps its inputs | T1 | 06 |
  | `PURGE/outcomes` | `Job.status` terminal, or `404 job_unknown` | insets reused from E16-D02
   §3.2 (:200–202, :204): failed, `role="alert"` once, "Purge of ETHUSDT failed (`<code>`). Some
   data may already be deleted: check ETHUSDT's size and gaps." · cancelled (the cancel itself
   PROPOSED — D04-G10, owner approval pending (#2701)) "Purge of ETHUSDT was cancelled. Data
   deleted before the cancel is gone." · unknown "The purge's status is no longer available on the
   server. Check ETHUSDT's size and gaps." · succeeded "Purged 1.2 GB of ETHUSDT data" from
   `Job.result` | none (outcomes) | outcome | 06 |
@ §8#1 ¶1 ‖ heading
  ## 8. Import (board 07; 6 frames; US-REC-007 :4210–4226)
@ §8#1 ¶2 ‖ paragraph
  `importTradeArchive` (`22` :14975–15028) imports the exchange's public daily trade archives for
   one symbol over an inclusive UTC date range of at most 366 days, verifies each file, writes
   trades to the Parquet cold tier, discards and reports rows inside a recorded window (recorded
   data wins), labels the windows archive-derived and `trades` only, is resumable and idempotent
   per day, runs one at a time and is audited as `recorder.import`. The card's form is the confirm
   (BQ-12 RULED: an additive, resumable action; the CMP-044 alternative is D04-Q3): Symbol, From /
   To, one consequence line, "Import archives". **A failing file never looks like a failing page**
   (AC 3). While the import runs, the shipped surface is `Job.progress_pct` with the requested
   range (`22` :22017; `Job.result` is null until `succeeded`, :22020–22021): the overall bar and
   "{done} of {n} days · {pct} %" keep moving and the strip reads "Import running · {pct} %". The
   per-file rows and the "{k} skipped" counter during the run need `files[]` streamed before
   `succeeded` (D04-G11), so they are drawn as a captioned PROPOSED inset beside the bar: a skipped
   or errored file is one row with its reason sentence, on `color.status.warning.subtle`. Either
   way the page keeps its healthy chrome with no banner and no `role="alert"`. Only a `failed` job
   uses `color.status.danger.subtle`, and even then inside the import card. The server paces the
   downloads (rate-limited, US-REC-007 NFR); the UI shows no rate control. The import summary (the
   counts, the overlap report, the per-file table) comes from `result`, whose shape is PROPOSED too
   (D04-G11), and is drawn as a captioned inset; the shipped summary is the finished line and the
   tag. The per-file reason codes are PROPOSED with `ArchiveImportResult` (D04-G11):
   `checksum_mismatch` (the code word of `22` :11809) · `parse_error` · `download_failed` ·
   `already_imported`, each with one sentence (§14).
@ §8#1 ¶3 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | --------------------------- |
   ----------------------------------------------------------------------------------------------------------------------------------------
   |
   ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   ----------------------------------------------------------------------------------------------------------
   | ------------- | ------ |
  | `IMPORT/form` | the import card at rest (`importTradeArchive`, `22` :14978) | Symbol (CMP-009)
   BTCUSDT · From / To (CMP-047 range) 2026-01-01 → 2026-01-31, inclusive UTC dates, at most 366
   days (`22` :14982) · the consequence line "Imports Bybit's public daily trade archives (trades
   only, no book data). Recorded data wins where they overlap. Re-running skips finished days." ·
   the CMP-011 tag "Archive-derived · trades only · no book data" | Import archives (CMP-001
   primary, T1); no dialog: the form is the confirm (BQ-12 RULED) | T1 | 07 |
  | `IMPORT/form-validity` | the range empty, inverted or longer than 366 days | Import archives
   with its own fill and label at `opacity.disabled` 0.45, the reason full-opacity under it:
   "Choose a range of at most 366 days." · board layer `validity-reason` · `aria-disabled`,
   focusable, a press shows the error summary · no lock, no CMP-079, no key | Import archives
   (validity look) | validity look | 07 |
  | `IMPORT/running` | `202` → `Job.status` running, `kind` archive_import, `progress_pct` 38 |
   the overall CMP-023 "12 of 31 days · 38 %" (`aria-valuetext` equal to the text;
   `Job.progress_pct` with the requested range, the shipped running state) · the per-file CMP-049
   table (table variant, no row control, columns Day / Status / Reason / Rows) only as an inset
   PROPOSED — D04-G11, owner approval pending (#2701): `files[]` streamed while the job runs ·
   "Import started" announced once | Import archives busy (`aria-busy`, no lock) · Stop job,
   PROPOSED — D04-G10, owner approval pending (#2701) | busy | 07 |
  | `IMPORT/running-with-skips` | day 14 (2026-01-14) fails its checksum: the file is skipped
   (`checksum_mismatch`, the code word of `22` :11809) and the import continues | the overall bar
   keeps moving: "30 of 31 days · 96 %" (`aria-valuetext` equal; `Job.progress_pct` with the
   requested range, the shipped running state) · the strip reads "Import running · 96 %" · the page
   keeps its healthy chrome: no page banner, no `role="alert"` (AC 3) · an inset PROPOSED —
   D04-G11, owner approval pending (#2701) beside the bar: the per-file table streamed from
   `files[]` while the job runs, columns Day / Status / Reason / Rows, 29 done, 1 skipped, 1
   downloading, the 2026-01-14 row "skipped ⚠ / checksum_mismatch / Checksum did not match; the
   file was skipped. / —" on `color.status.warning.subtle`, done rows "done ✓ / 95,040,000 rows",
   and the counter "1 skipped" after the bar's text | Import archives busy (`aria-busy`) · Stop
   job, PROPOSED — D04-G10, owner approval pending (#2701) | busy | 07, 10 |
  | `IMPORT/summary` | `Job.status` succeeded; `result` (PROPOSED `ArchiveImportResult`, D04-G11)
   | the shipped outcome line "Import finished: BTCUSDT, 2026-01-01 → 2026-01-31" (polite, once) ·
   the CMP-011 tag "Archive-derived · trades only · no book data" on the summary and, PROPOSED —
   D04-G12, owner approval pending (#2701), on every imported range the coverage chart draws
   (E16-D05's chip is the consumer) · an inset PROPOSED — D04-G11, owner approval pending (#2701)
   from `result`: the counts "Imported 29 days of BTCUSDT trades · 1 file skipped · 1 file failed ·
   660,000 overlapping rows discarded", the overlap report "660,000 rows inside recorded windows
   were discarded — recorded data wins." (`22` :14983, never "duplicates removed"), the per-file
   table complete with the 2026-01-31 row "error ✗ / download_failed / The file could not be
   downloaded; run the import again to retry it. / —" | Import archives enabled again (T1); "Run it
   again to resume: finished days are skipped." | outcome | 07 |
  | `IMPORT/failed` | `Job.status` failed, `error` a stable code (download_failed after the retry
   budget), or `404 job_unknown` | inside the import card only: "Import failed (download_failed).
   Finished days are kept; run it again to resume." on `color.status.danger.subtle`, `role="alert"`
   once · never a page banner · the per-file table, an inset PROPOSED — D04-G11, owner approval
   pending (#2701), keeps its rows · unknown: "The import's status is no longer available on the
   server. Run it again: finished days are skipped." | Import archives enabled again (T1) | outcome
   | 07 |
@ §9#1 ¶1 ‖ heading
  ## 9. Roles and the view-as leg (E16-D02 §7 :444–455 adapted)
@ §9#1 ¶2 ‖ table
  | Role | SCR-142 |
  | ----------------------------- |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | Owner viewing as another user | the **first leg** on every write (E09-D09 §2.1 step 3): every
   write T2 with `rbac.view_as`, one panel notice (`SCR-142/view-as`); reads, meters, tables and a
   running job's progress unchanged; exits and links enabled |
  | Owner | everything in §2–§8; the `recorder_purge` step-up on purge; compaction, import and the
   PROPOSED vacuum (D04-G8) without a typed field |
  | Manager / Viewer | not reachable: `/admin/*` is hidden from navigation and returns a hard 404
   (`14` :43, :85; E16-D02 §7 :449); `rbac.owner_only` "Only the owner can change recording."
   (E09-D09 :90, :108) would be the reason if a write of this page ever reached them — no frame
   draws it (BQ-8 RULED); the server decides (C-12.4) |
@ §10#1 ¶1 ‖ heading
  ## 10. Keyboard, focus and announcements (board 08; `05` §3.4 :90, §6.2 :144–150)
@ §10#1 ¶2 ‖ paragraph
  **Initial focus** on entry: the H2 (a route-section change, not a dialog). **Tab order** follows
   the regions: the stamp's Retry (when shown) → the two meters (each a `role="meter"`, focusable
   only when it carries a tooltip; the value text is always visible, so by default they are not Tab
   stops) → the three tier cards' controls (Purge data… / Compact Parquet…; the Accordion header of
   each per-tier table) → the per-symbol table → the maintenance buttons → the jobs strip's Stop
   job carriers (PROPOSED D04-G10) → the import form (Symbol, From, To, Import archives) → the
   per-file table (the PROPOSED D04-G11 inset). **Tables**: every CMP-049 here is the table variant
   (no control in a body row; `15` :528): Tab lands on the table as one scroll region, arrows
   scroll; a sortable header is a button with `aria-sort`; no APG grid is implied because no body
   cell is interactive (the per-symbol row's Purge… sits in a trailing actions column, which would
   make it a grid — D04-D3 keeps the action in the row's detail popover instead, so the table stays
   a table). **Dialogs** (E16-D03 §5's model): CMP-044 standard — focus starts on Cancel; Tab:
   Cancel → the verb → the close ✕; Esc = Cancel; on close focus returns to the button that opened
   it. The purge dialog — first focus on the Symbol select, Tab through the fields to the typed
   input, Cancel, Confirm, ✕; Enter in the typed field does nothing (no implicit submit on a
   destructive path); Esc = Cancel. **The import form** — Enter in From / To moves to the next
   field, Enter on Import archives submits; a validity-look press shows the error summary and moves
   focus to it. **T2 keys** (§1.3; E09-D09 §9.3 :238): Enter, Space or a bound hotkey on a T2
   control changes nothing and re-shows the reason once, politely. **No global hotkeys** are added
   (the admin area has none; `05` §3.2's list is untouched).
@ §10#1 ¶3 ‖ paragraph
  **Announcements** (`05` §6.2 :146–150; CMP-023 `15` :267): the jobs strip is one `role="status"`
   region, polite; one announcement at a job's start ("Compaction started", "Import started") and
   one per terminal state; never per tick, never per 2 s poll; a failed purge (E16-D02 :200) and a
   failed import (inside its card, §8) are each `role="alert"` once, the only two assertive
   announcements; a skipped import file is not announced (the PROPOSED inset's row and counter
   carry it); the summary once. The sample stamp changes silently; staleness is announced once when
   it begins ("Storage figures are stale"). **Zoom and reflow** (`05` §5 item 7): at 200 % and the
   in-app text scale at 1280 × 800 the cards stack, every table renders one row element per record,
   the dialogs fill the viewport with a sticky footer and a scrolling body; `forced-colors`: the
   meter fills take the system accent beside their always-visible value text, the tone glyphs keep
   their words, the dashed PROPOSED outline stays a dashed border.
@ §10#1 ¶4 ‖ table
  | Key | Where | Effect |
  | -------------------------------- | ------------------------------------ |
   ----------------------------------------------------------------------------------------------------------------------------------
   |
  | `Tab` / `Shift+Tab` | the page | the region order above; every control a stop; a T2 control
   stays a stop |
  | `Enter` / `Space` | a button | opens the confirm (compact; the vacuum inset, PROPOSED D04-G8),
   the purge dialog, or submits the import; on T2 re-shows the reason |
  | `Enter` | From / To | next field; on Import archives: submit |
  | `Esc` | a dialog | Cancel; focus returns to the opener |
  | `↑` / `↓`, `PageUp` / `PageDown` | a table (scroll region) | scrolls; no roving cell focus
   (the table variant) |
  | `Enter` / `Space` | an Accordion header (per-tier table) | toggles; `aria-expanded` |
@ §11#1 ¶1 ‖ heading
  ## 11. Tokens and redlines (board 09; 1 frame)
@ §11#1 ¶2 ‖ table
  | Element | Tokens |
  | -------------------------------------------------------- |
   ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | the page | `color.surface.canvas` (CMP-087's `color.surface.admin-tint` is MISSING in the
   token package, D04-C4); the H2 `type.ui.heading-lg` `color.text.primary`; the stamp
   `type.ui.caption` `color.text.secondary` |
  | a meter (CMP-023 `kind="meter"`) | track `color.surface.sunken` (CMP-023's
   `color.surface.hover` track fails 3:1 under the danger fill in dark, §15; D04-A7), height
   ⟦audit:layout.meter_h⟧ px, `radius.badge`; fill `color.action.primary.default` (level 0),
   `color.status.warning.strong` (1–2), `color.status.danger.default` (3); label `type.ui.label`,
   value `type.num.sm`, both `color.text.secondary`; the tone glyph before the value on 1–3 |
  | a tier card (CMP-050 + CMP-036) | `color.surface.raised`, `color.border.default` hairline,
   `radius.card`, `elevation.card`, `space.inset.md`; rows `size.row.comfortable`; `dt`
   `type.ui.label` `color.text.secondary`, `dd` `type.num.base` `color.text.primary`; the health
   glyph `size.icon.sm` in `color.status.success.strong` / `warning.strong` / `danger.strong` |
  | a PROPOSED carrier | the same card or row with a dashed `color.border.default` outline (absent
   from the contract, never a side — E25-D01 §9.5) and the caption `type.ui.caption`
   `color.text.secondary` "PROPOSED — D04-Gn, owner approval pending (#2701)" |
  | the jobs strip | one line `type.ui.body` `color.text.primary`; CMP-023 `progress` under it;
   `space.stack.xs` |
  | the per-file table (CMP-049, the PROPOSED D04-G11 inset) | header `color.surface.hover`
   `type.ui.label`; odd rows `color.surface.canvas`, even `color.surface.raised`; a skipped row
   `color.status.warning.subtle` with the ⚠ glyph `color.status.warning.strong`; an error row the
   same warning subtle (the job is not failed); the words `color.text.primary` |
  | a T2 control (view-as) | `color.surface.raised` + `color.border.default` hairline; the lock
   and the full label `color.text.tertiary`; the notice `color.text.secondary`; never
   `color.text.disabled`, never `opacity.disabled` |
  | a validity control | its own fill and label at `opacity.disabled` 0.45; the reason
   `color.text.secondary` at full opacity; layer `validity-reason` |
  | banners (CMP-028) | warning `color.status.warning.subtle` / glyph `.strong`; danger
   (`SCR-142/unavailable`; the failed import inside its card) `color.status.danger.subtle` / glyph
   `.strong`; info (the overlap report) `color.status.info.subtle` / glyph `.strong`; the words
   `color.text.primary` |
  | focus | `color.focus.ring`, 2 px outside; `motion.duration.normal` for a meter's value change
   (motion-reduce: none) |
@ §11#1 ¶3 ‖ table
  | Frame | Producer | Shows | Controls (class per §1.3) | Class | Board |
  | ------------------ | ------------------ |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | -------------------------------------------------------------------------------------- | -----
   | ----- |
  | `SCR-142/redlines` | the healthy report | the tokens above annotated on a tier card, a meter,
   the jobs strip, the per-file table (an inset, PROPOSED — D04-G11, owner approval pending
   (#2701)), the T2 control (the lock + the full label + the notice on `color.surface.raised`) and
   the validity control (`opacity.disabled` + `validity-reason`) · the token audit counts | as
   annotated (the T2 and validity specimens are the §5 and §7 frames' controls, cited) | T1 | 09 |
@ §12#1 ¶1 ‖ heading
  ## 12. Producibility, the contract gaps and the frame gates (the Test plan)
@ §12#1 ¶2 ‖ paragraph
  **Shipped state at the base (the zero counts).** `StorageUsage` has ⟦audit:facts.storage_fields⟧
   fields (`22` :19211–19243) and nothing SCR-142's catalogue entry asks for beyond them: no row
   counts, no lag, no slow queries, no vacuum or compaction timestamps, no schema version, no
   per-tier growth or projection; `Job.kind` has ⟦audit:facts.job_kinds⟧ values with no compaction
   or vacuum kind (:22002–22014); `getJob` is the only job route (no cancel, :12097–12133); no
   vacuum route exists; `Job.result` for `archive_import` has no schema (:14987);
   `HealthReport.components[]` names its tiers only in the example (:11014–11026). The tool prints
   the counts.
@ §12#1 ¶3 ‖ table
  | Field or behaviour | Producer today | Gap |
  | --------------------------------------------------------------------- |
   ------------------------------------------------------------------------------------- |
   ----------- |
  | disk and budget figures, projection, growth, level, gate, sample time | `StorageUsage` (`22`
   :19211–19243); WS `storage` (`23` :4062–4085) | — |
  | per-tier size, retention; per-symbol size, growth, pinned | `tiers[]`, `symbols[]` (`22`
   :19216–19232) | — |
  | per-tier growth and projected full date (AC 1) | none | D04-G1 |
  | per-symbol oldest / newest, the sparkline history | none | D04-G2 |
  | rows by table, oldest / newest per table | none | D04-G3 |
  | ingestion lag | WS pressure numbers only (`23` :4060–4061); `24` :494 is a metric | D04-G4 |
  | slowest queries | none | D04-G5 |
  | last compaction / last vacuum | none (the schedule is `21` :4410) | D04-G6 |
  | schema version, pending migrations | none (`version` / `git_sha` are release facts,
   :21840–21841; readiness :11103) | D04-G7 |
  | a vacuum action | none (no route, no kind; `21` :4332) | D04-G8 |
  | the compaction job's kind word | none in `Job.kind` | D04-G9 |
  | cancel a running job | none | D04-G10 |
  | the import summary's shape and the per-file reason codes | `result` "carries the import
   summary", no schema (:14987) | D04-G11 |
  | the archive-derived label on coverage intervals | prose (:14984–14985) | D04-G12 |
  | a tier unreachable | `components[] {name, state, last_good_at}` (:21850–21860); the names from
   the example | — (D04-CG1) |
  | the step-up on compact / PROPOSED vacuum (D04-G8) / import | none in `22` (purge only, :15040)
   | — (D04-CG2) |
  | the example's symbols against its tiers | the `22` example (:5445–5461) | — (D04-CG3) |
  | jobs after an API restart | lost; `404 job_unknown` (:12114–12117; the 256 cap :380) | —
   (D04-CG4) |
@ §12#1 ¶4 ‖ paragraph
  **The gates (A2 RULED; `docs/design/_tools/e16_d04_storage_audit.py`).** `--check` reads this
   whole file as text and re-derives every `audit:` marker. Its gates read **every frame row whole,
   cell by cell and item by item** (an item is a cell's part between " · " or "; ", a quoted string
   never split), **every other table row across all its cells, every prose sentence, the deck and
   the sketch** (its footnote markers read as the captions they carry). **Subjects carry** (the
   merged E15-D05 design): a lock, dim or fill word speaks of the nearest control, action or field
   named before it in its item, else of the one the item before named last, so a word after ";" or
   in an item that opens on It / This / They / Then / Each lands on that subject; a prose sentence
   that opens on a pronoun is read with the sentence before it. Controls are named by their full
   and short names (Cancel, Esc and the close ✕; the links; Compact Parquet… / Compact; Purge data…
   / Purge… / Purge; Import archives; Confirm; and the PROPOSED D04-G8 and D04-G10 carriers, Vacuum
   Postgres… / Vacuum and Stop job). Each ruled sentence has a case-insensitive vocabulary with its
   synonyms; a negator (no, never, not, without, nor) exempts a match only when it governs it,
   within four words before it in the same clause, so a "not" elsewhere in the item does not.
   **Numbers are anchored:** each typed number is read through its context words (a tier's Size,
   Share and Retention, the ladder's steps and clears, the merge size, the batches, the meters, the
   runways, the formula, the import progress, the symbol rows, the purge window, the times) and
   must equal its own `--json` value, so a swap of one registered value for another fails; every
   other number is pinned with its unit's exact text (R-23). Each item reports its first violation
   only, and a row with one skips its presence checks. A frame table row has six cells (Frame ·
   Producer · Shows · Controls · Class · Board). `--self-test` applies ⟦audit:mutations⟧ mutations
   in memory, one at a time — the first commit's ⟦audit:mutations_first⟧ forms, the pre-PR
   design-review lens round 1's ⟦audit:mutations_lens⟧ probes, ⟦audit:mutations_own⟧ variants of
   that fold, ⟦audit:mutations_shipped⟧ forms of a PROPOSED item presented as shipped outside a
   frame's Shows / Controls, the orchestrator's text round 1's ⟦audit:mutations_text1⟧ probes
   rebuilt verbatim and ⟦audit:mutations_text1_own⟧ variants of that fold, the orchestrator's gate
   re-check's ⟦audit:mutations_text2⟧ probes rebuilt verbatim and ⟦audit:mutations_text2_own⟧
   variants of that fold, the orchestrator's gate re-check 2's ⟦audit:mutations_text3⟧ slipped
   forms rebuilt verbatim, ⟦audit:mutations_text3_own⟧ paraphrases of that fold,
   ⟦audit:mutations_pin⟧ mutations of R-23's own kinds, the orchestrator's gate re-check 3's
   ⟦audit:mutations_text4⟧ passing forms rebuilt verbatim in its places (two of them soft-wrapped
   lines, two new paragraphs, the M6 synonym twice, the BQ-12 and BQ-15 rewrites) and
   ⟦audit:mutations_text4_own⟧ paraphrases of this fold (M2, M3, M4 and M6, three each, in units no
   pin held before it) and the gate re-check 4's ⟦audit:mutations_text5⟧ forms (the sketch's Purge
   box shifted by spaces alone, onto the Postgres card and off the Parquet card, and a `~` written
   before a marked number) and the purge-contract re-pin's ⟦audit:mutations_contract⟧ form (the
   dialog's `before` field removed) — and each must make `--check` fail with **one** FAIL, its own
   message; no two share a message, ⟦audit:valid_twins⟧ valid twins (a captioned inset, the gap's
   own G-row, a negated mention, the exit Cancel, "Esc closes the dialog", the ruled order reworded
   four ways, a sibling PENDING by name, the typed field starting empty, trailing spaces) raise no
   gate FAIL and nothing once re-pinned (until then R-23 alone refuses each, as it edits a unit),
   the unmutated file passes and the file is byte-identical afterwards; `--mutate N` exits 1 when
   the gate caught the mutation, 2 when it slipped. **Two layers (the gate re-check 3:
   whole-document default-deny).** The vocabulary gates above are the first line: each reads its
   ruled sentence through its words, their synonyms and the negators that govern them. R-23 is the
   backstop and pins **every unit** of this file in the tool's committed `RULED_PIN_TXT`: a unit is
   a Markdown block — a heading, or a run of consecutive non-blank lines (each paragraph, list
   block and table block, the deck's table among them) — and the fenced sketch whole, its lines
   verbatim (its columns are content; every other unit's whitespace is normalised); a soft-wrapped
   line belongs to its block. A unit is keyed by its region (the heading path, plus the heading's
   occurrence) and its place in the region, and read with its exact text: ⟦audit:pins.total⟧ units
   (headings ⟦audit:pins.heading⟧, paragraphs ⟦audit:pins.paragraph⟧, tables ⟦audit:pins.table⟧,
   the sketch ⟦audit:pins.sketch⟧). A changed, moved, duplicated or missing unit, a unit the pins
   do not hold, a new or repeated heading and a duplicate location FAIL naming the location, so a
   new or edited unit anywhere fails until `--repin-ruled` rewrites the table, a deliberate act
   read in the diff; `--check` never re-pins. **Left unpinned, by name (the exemption list, the
   tool's `PIN_EXEMPT`):** ⟦audit:pins.exempt⟧ class — the `audit:` markers and the number printed
   before each, §12's among them (⟦audit:pins.masked⟧ spans, each read as its key): `--check`
   re-derives each key's value and reads the number before the marker. Nothing else is exempt:
   §12's R-rows, §15's matrix and the caption carriers have no exact gate that reads them whole, so
   they stay pinned. An R-23 FAIL is reported only when no other gate FAILs, else counted beside it
   on a NOTE line, so one wrong form yields one FAIL.
@ §12#1 ¶5 ‖ table
  | Rule | The ruled sentence the gate reads (source) | Tables read | Mutations |
  | ---- |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   | --------------------------------------------------------- |
   ------------------------------------------ |
  | R-1 | every tier card's Size cell carries a number with a unit; its Growth/day and Projected
   full cells carry a figure with a unit or the shipped "—" with the D04-G1 caption (AC 1; `14`
   :2777 "all figures have units") | §4 `TIER/questdb`, `/parquet`, `/postgres` |
   ⟦audit:mutations_by_rule.r1⟧ |
  | R-2 | every page frame carries the sample stamp "Sampled HH:MM:SS UTC"; the stale and the
   unavailable frames show its stale form "stale (N min old)" (`14` :84; `20` :908) | §2, §5 |
   ⟦audit:mutations_by_rule.r2⟧ |
  | R-3 | exactly two meters, each naming its denominator field (`cap_bytes`, `disk_total_bytes`;
   `22` :5424; D04-D1) | §2 `SCR-142/healthy` | ⟦audit:mutations_by_rule.r3⟧ |
  | R-4 | health is a `ComponentState` word in every tier card; a tier down keeps the page usable
   and draws no page-level banner, callout, toast or alert in any wording (`14` :2777, :86; BQ-15
   RULED) | §4, §5 `SCR-142/tier-unreachable-questdb` | ⟦audit:mutations_by_rule.r4⟧ |
  | R-5 | "Recording pauses before trading is affected." on every frame whose producer is `level`
   ≥ 1 in any wording that keeps the ruled order, in §1.4 and in the deck byte for byte, with the
   deck's detail line; an inverted or weakened order in any wording anywhere in the file fails
   ("trading stops before recording", "orders are refused before recording pauses", "recording
   continues while trading halts", "trading may also be affected") (AC 2; `14` :2780) | every frame
   table, every prose sentence, §14 | ⟦audit:mutations_by_rule.r5⟧ |
  | R-6 | no state, T1, T4, outcome or dialog frame and no unit outside the T2 and validity rules
   draws a lock or a disabled control in any wording (lock, padlock, T2, CMP-079, RbacGate,
   disabled, greyed / grayed, dimmed, faded, inert, unavailable, not available, no longer
   available, blocked, gated, can't / cannot be pressed or used, `aria-disabled`,
   `opacity.disabled`); §1.3's classes are fixed per row; the disk-full frame carries the BQ-14
   sentence; the migration frame draws no Apply or run control (A1; BQ-14 / 15 / 16 RULED) | every
   frame table, §1.3, every prose sentence, §14 | ⟦audit:mutations_by_rule.r6⟧ |
  | R-7 | the purge dialog carries the Reason field (required, 3–280), the `before` bound (Delete
   data recorded before, required), the typed symbol empty and the step-up sentence; the typed
   field is never pre-filled, auto-filled, pre-populated, filled in, typed or copied into, nor —
   with the typed field as its subject — set to the symbol, already holding it or already in it,
   arriving, opening or starting with it, defaulting to or suggesting it, seeded or "empty at
   first"; nor is the symbol entered for the Owner — in any wording anywhere in the file (the
   ticket's security note; `22` :15035, :15051, :15086) | §7 `PURGE/dialog`, `PURGE/step-up`, every
   prose sentence | ⟦audit:mutations_by_rule.r7⟧ |
  | R-8 | a validity-look frame carries `validity-reason`, `opacity.disabled` and the reason under
   the control, never inside it, and no lock, no CMP-079 or RbacGate (E09-D09 §9.1 :230; E30-D02 D3
   :128) | every row whose Class is validity look | ⟦audit:mutations_by_rule.r8⟧ |
  | R-9 | the skip frame keeps its bar moving and draws no banner, callout, toast, alert or page
   error in any wording, and no stalled bar; §8's prose names none; a failed import stays inside
   its card (AC 3; US-REC-007 :4223) | §8 `IMPORT/running-with-skips`, `IMPORT/failed`, §8 prose |
   ⟦audit:mutations_by_rule.r9⟧ |
  | R-10 | the per-file table has a Reason column and the skipped row a code of the closed set
   with its deck sentence; the summary carries the overlap report ("recorded data wins"), the
   archive-derived label and "no book data" (`22` :14983–14985; US-REC-007 :4220, :4226) | §8, §14
   | ⟦audit:mutations_by_rule.r10⟧ |
  | R-11 | a running job is busy with `aria-busy`, never `T2`, a lock or a disabled write; a `409`
   refusal is T4, never a lock or a disabled control (E16-D02 §6.6 :422; E09-D09 §9.1) | §6
   `JOB/strip-running`, `JOB/strip-refused-409` | ⟦audit:mutations_by_rule.r11⟧ |
  | R-12 | every PROPOSED carrier — vacuum (G8), Stop job (G10: the job cancel, never labelled
   Cancel, the dialogs' exit; also stop, abort, End job), row counts and a Rows column (G3), slow
   queries and p95 (G5), per-tier growth (G1), lag (G4), the sparkline, CMP-024, a trend line and
   the ranges (G2), the migration values (G7), last vacuum or compaction (G6), the per-file rows
   and the skip counter (G11), the archive ranges (G12), and any D04-Gn named — carries its own
   caption "PROPOSED — D04-Gn, owner approval pending (#2701)" with its n in the same item; no unit
   anywhere (a prose sentence, a non-frame table row read across its cells, the deck, the sketch, a
   Producer cell) presents a PROPOSED item as shipped by any of its names (Vacuum Postgres…, Stop
   job, End job, a Rows column, p95, the sparkline, CMP-024, Last vacuum, Migration 0008, the
   per-file table) unless its row or clause carries that caption or names the gap absent, or a
   negator governs it (the gap's own A / C / CG / D / G / Q rows and the BQ table exempt); the
   deck's strings and the sketch carry the full caption, never a short "PROPOSED Dn" (BQ-11 / 13 /
   18 / 22 RULED; A2) | every frame table, every unit | ⟦audit:mutations_by_rule.r12⟧ |
  | R-13 | the view-as frame is T2 with `rbac.view_as`, one notice in any wording, the lock and
   the full label, every write of §1.3's T2 row by name, the four anatomy tokens, the view-as leg
   first, and nothing dimmed; the view-as row is first in §1.3 and §9 (E09-D09 §2.1 step 3, §2.2
   :49, §3.1 :95) | §5 `SCR-142/view-as`, §1.3, §9 | ⟦audit:mutations_by_rule.r13⟧ |
  | R-14 | every exit a frame lists (Cancel, Esc and the close ✕ on every dialog, the SCR-140 /
   141 / 143 links, Shorten retention, Retry, Manage pin) is present and T1, and never locked or
   disabled in any wording, whether the word sits in the exit's own item, after a ";" or in an "It
   / They / Each …" follow-on; the exit Cancel is never captioned PROPOSED and never the job action
   (A3) | every frame table | ⟦audit:mutations_by_rule.r14⟧ |
  | R-15 | no frame links a data-store console or draws a backup or restore control (SR-048 `04`
   :873; `21` §8 :4567) | every frame table | ⟦audit:mutations_by_rule.r15⟧ |
  | R-16 | #4463 and #4501 are named PENDING, never pinned at a sha or a line in any spelling
   (`#N`, `PR N`, `pull/N`, "the E16-D03 / E16-D05 boards"; a sha with or without a hex letter)
   (A4) | the whole file | ⟦audit:mutations_by_rule.r16⟧ |
  | R-17 | every number a frame row or a prose or table unit types (sizes, percentages, days,
   dates, times, counts, px, ms) is a `--json` value with its unit, and every anchored number is
   its own value (the anchors above); markers, line cites and ids aside | every frame table, every
   unit | ⟦audit:mutations_by_rule.r17⟧ |
  | R-18 | §0's per-board counts equal the frame tables' rows per board, their sum the frame
   total, and every frame §0 names is a row (the frame inventory) | §0, every frame table |
   ⟦audit:mutations_by_rule.r18⟧ |
  | R-19 | every `rbac.*` deck string is one sentence of at most 60 characters with a full stop,
   naming no data, and `rbac.view_as` is E09-D09's byte for byte; the deck's key set is closed
   (E09-D09 §3.1 :85) | §14 | ⟦audit:mutations_by_rule.r19⟧ |
  | R-20 | the compact and purge outcome lines are E16-D02 §3.2's, byte for byte (:200, :203) | §6
   `JOB/outcomes`, §7 `PURGE/outcomes` | ⟦audit:mutations_by_rule.r20⟧ |
  | R-21 | compact and vacuum confirm with CMP-044 standard and "Nothing is deleted." in the
   frames, §6's action table and the deck; the purge dialog is CMP-044 typed and E16-D02 §6.5's
   body whole; every purge entry opens §6.5, never a second shape in any wording in any unit
   (one-click, a lighter, simpler or standard confirm, without the typed field, its own purge
   dialog); Purge data… sits on the QuestDB and Parquet cards and Purge… in the row popover, never
   on the maintenance card (§2 (g), the sketch) (BQ-9 / BQ-10 RULED; `21` :4416–4417) | §6, §7,
   §14, §4 | ⟦audit:mutations_by_rule.r21⟧ |
  | R-22 | the strip announces once at start and once per terminal state, never per tick (`05`
   §6.2 :146; CMP-023 `15` :267) | §6 `JOB/strip-running` | ⟦audit:mutations_by_rule.r22⟧ |
  | R-23 | every unit of the file (a heading, a paragraph, a list or table block, the sketch)
   equals its pin, by region, place and exact text, in the tool's `RULED_PIN_TXT` (written by
   `--repin-ruled`, never by `--check`); a changed, moved, duplicated or missing unit, a unit or
   region the pins do not hold and a duplicate location fail naming the location; only `PIN_EXEMPT`
   is left unpinned (the orchestrator's gate re-checks 2 and 3) | the whole file |
   ⟦audit:mutations_by_rule.r23⟧ |
@ §12#1 ¶6 ‖ paragraph
  **Copy gates beside them** (no mutation of their own): the AC 2 sentence and the view-as notice
   in the deck; the banned words off the deck's String column; no local path, user, notes folder or
   Penpot host anywhere (generic patterns); every `C-x.y`, `CMP-nnn` and `SCR-nnn` id exists in its
   owner; every cited `:N` still holds its text (a drift is a WARN naming the current line; a
   vanished or ambiguous needle a FAIL); no closing keyword before an issue number; §15's ratios
   equal the matrix; every bindings-table row with a numeric field names a unit.
@ §13#1 ¶1 ‖ heading
  ## 13. Component map and the rows (A · C · G · CG · Q), and the decisions
@ §13#1 ¶2 ‖ paragraph
  **Components used** (each has a `15` heading; the tool checks): CMP-001 (secondary / primary /
   danger), 005 (Include pinned), 007 (Reason, the typed symbol), 009 (Symbol), 011 (the
   archive-derived tag), 015 (skeletons), 016 (the stamp's echo), 019 (`lock` on the view-as leg
   only; ✓ ⚠ ✗ as the health and status glyphs; the clock), 021 (links), 023 (`meter` × 2;
   `progress` on the strip and the import), 024 (only inside the PROPOSED inset, with its mirror
   table), 027 (inline errors: a tier down, a refusal), 028 (the level banner, the lag-warning
   banner (keyed on the backlog, BQ-17) and the migration banner (PROPOSED, D04-G7), and the
   `SCR-142/unavailable` one), 035 (the re-auth badge, via CMP-087), 036 (the card rows), 040 (the
   import fields), 043 + 044 (standard for compact and the PROPOSED vacuum, D04-G8; typed for
   purge, E16-D02's), 047 (From / To; the purge date), 049 (table variant everywhere), 050 (cards),
   051 (the per-tier table's disclosure), 079 (`form="notice"` on the view-as leg), 087 (the
   shell), 093 (wraps the purge, E16-D02's), CMP-178 (the SCR-143 link tile), CMP-239 (`stale` on
   the stamp). **Not used:** CMP-038 (progress is always determinate here), CMP-177 (E16-D02's
   row), CMP-026 (no empty state: a tier with nothing recorded reads "0.0 GB"). **Shared sentence
   for every `22` / `23` / `24` gap (E30-D04 §30 :1048, in the design-PR form):** "Design PRs never
   edit `22`. Contract-first, the schema change lands in its own small PR, opened by the first
   implementation ticket that needs the field; the names here are PROPOSED (orchestrator ruling,
   2026-10-21)." For this spec that first implementation ticket is the E16 implementation ticket
   that consumes SCR-142 (the ticket's Context names E16-S05 / E16-S08; the backlog names E16-T10
   for the import and E16-T07 for `DiskBudget`).
@ §13#1 ¶3 ‖ table
  | Id | What |
  | ------- |
   -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | D04-A1 | `15` CMP-178 :2071 Props — Old: "`label` · `value` · `unit` · `tone:
   "ok"\|"warning"\|"danger"` · `sparkline?: number[]`" → New: "`label` · `value` · `unit`
   (required whenever `value` is a number: never a bare figure) · `tone: …` (from `ComponentState`:
   healthy and not_deployed → ok, degraded and warning → warning, down → danger; the word always
   rendered beside the tone) · `href?` (the tile's destination; SCR-143 from here) · `sparkline?:
   number[]`" — `unit` is already a prop; the amendment makes it required for a number and adds the
   tone map and `href?` |
  | D04-A2 | `15` CMP-023 :264 Purpose — Old: "determinate progress (recorder disk usage, replay
   load, TWAP slice progress)." → New: "determinate progress (recorder disk usage, replay load,
   TWAP slice progress); a `meter` divides by one denominator, so two denominators are two meters,
   each naming what it divides in its label (the recording budget over `cap_bytes`; the volume over
   `disk_total_bytes`)." |
  | D04-A3 | `15` CMP-049 :528 Variants — Old: "table (static cells, the APG Table pattern: no
   control in a body row; default)" → New: "table (static cells, the APG Table pattern: no control
   in a body row; default; an import's per-file table stays this variant: status and reason as text
   cells, no per-row Retry or Skip control, a re-run resumes)" |
  | D04-A4 | `14` SCR-142: the pointer line this PR adds after :2780 (content-only); and SCR-140
   :2742's card gains "Storage details →" as the link to this section (E16-D02's card, by its
   owner) |
  | D04-A5 | `14` SCR-142 :2774 States (copy-ready for the owner): "healthy · migration pending
   (banner with the version delta) · lag warning · read-only mode (disk full) · a tier unreachable
   (error per tier, page usable)" — not edited here (D04-C2) |
  | D04-A6 | `14` SCR-142 :2778 Performance (copy-ready): "… are explicit actions with progress;
   cancel is PROPOSED until `22` has a cancel route" — not edited here (D04-C3) |
  | D04-A7 | `15` CMP-023 :268 Tokens — Old: "track `color.surface.hover`" → New: "track
   `color.surface.sunken`" — the danger fill measures ⟦audit:ratios.danger_on_hover.dark⟧ on the
   hover track in dark (below 3:1) and ⟦audit:ratios.danger_on_sunken.dark⟧ on sunken (§15), as
   E16-D03 §15 already measured for the primary fill |
  | D04-A8 | E16-D02 §3.2 :203 (merged `736f995e`), the compact line — Old: "Compaction failed
   (`<code>`); nothing was deleted." / "…cancelled." / "Compaction status is no longer available on
   the server." → New: the middle form written out whole, "Compaction cancelled; nothing was
   deleted." (the line `JOB/outcomes` draws); owner E16-D02 |
  | D04-C1 | `14` :2779 audits `storage.compaction_triggered`, `storage.vacuum_triggered`,
   `storage.tier_migration_triggered`; `22` audits the import as `recorder.import` (:14988) and the
   purge as `retention.purge` (:15073) and names no compaction audit; owner `14` / `22`; the
   confirm line here stays "This action is audited." |
  | D04-C2 | `14` :2774 lists four states; the ticket adds "a tier unreachable"; this spec draws
   five (§5); owner `14` (D04-A5) |
  | D04-C3 | `14` :2778 says heavy operations "can be cancelled" and names "reindex"; `22` has no
   cancel route and no reindex; owner `14` (D04-A6) and `22` (D04-G10) |
  | D04-C4 | `15` CMP-087 binds `color.surface.admin-tint`, which the token package does not
   define (the tool prints it MISSING); the page draws on `color.surface.canvas` until the
   design-system owner adds it |
  | D04-C5 | E25-D01 §9.5 :334's pattern rule is followed (a dashed outline = absent from the
   contract) and not re-proposed here |
  | D04-C6 | E16-D02 §6.6 :424 (merged `736f995e`) runs `compactRecorder` as Compact now with no
   confirmation on SCR-140, while this spec confirms the same call with CMP-044 standard (BQ-10
   RULED); owner E16-D02 and the owner; recorded, not reconciled here (alternative: no confirmation
   on SCR-142, matching SCR-140) |
  | D04-G1 | `StorageUsage.tiers[].daily_growth_bytes` and `tiers[].projected_full_at` (nullable)
   — per-tier growth and projection (AC 1); until then the card shows the disk-level figure
   labelled "all tiers" and "—" per tier. Shared sentence. |
  | D04-G2 | `symbols[].oldest_at`, `symbols[].newest_at`, `symbols[].history_bytes[]` (7 daily
   samples) — the per-symbol range and the sparkline's series. Shared sentence. |
  | D04-G3 | `tiers[].tables[] {name, rows, bytes, oldest_at, newest_at}` — rows by table; the
   QuestDB names are `21` §4.1–4.13's, the Parquet "tables" its §5.1 partition families. Shared
   sentence. |
  | D04-G4 | `ingest_lag_ms` on the recorder topic (or `StorageUsage`); until then the two
   produced numbers (`23` :4060–4061) and a "—" lag cell; the lag-warning threshold (5 ILP batches)
   is PROPOSED with it (D04-Q4). Shared sentence. |
  | D04-G5 | `slow_queries[] {tier, kind, p95_ms, count_1h}` on a PROPOSED `GET
   /admin/storage/queries` or on `StorageUsage` — the checklist's query-performance indicators.
   Shared sentence. |
  | D04-G6 | `tiers[].last_compaction_at` (parquet), `tiers[].last_vacuum_at` (postgres). Shared
   sentence. |
  | D04-G7 | `schema_version`, `target_version`, `pending_migrations: int` on `HealthReport` or
   `StorageUsage`; the banner "{n} pending · {schema_version} → {target_version}". Shared sentence.
   |
  | D04-G8 | `POST /admin/db/vacuum` (Postgres only; `recording:write` proposed, `admin:write` the
   alternative; no step-up proposed — D04-Q1) + `Job.kind` `db_vacuum`. Shared sentence. |
  | D04-G9 | `Job.kind` `parquet_compaction` for `compactRecorder`'s job (today the kind is
   unnamed). Shared sentence. |
  | D04-G10 | `POST /admin/jobs/{jobId}/cancel` → `202`; `409 job_not_cancellable`; until then
   Stop job is a captioned PROPOSED carrier, never labelled Cancel (the dialogs' exit), and a
   started job runs to its end. Shared sentence. |
  | D04-G11 | `ArchiveImportResult {days_total, days_done, files[] {date, status ∈ done \| skipped
   \| error, reason, rows}, overlap_rows_discarded, archive_derived: true}` as `Job.result` for
   `archive_import`; reason codes `checksum_mismatch` (`22` :11809's word) · `parse_error` ·
   `download_failed` · `already_imported`; and `files[]` (with the skip count) streamed in `result`
   while the job runs, before `succeeded` — today `result` is null until then (`22` :22020–22021),
   so the running frames' per-file rows and skip counter are this gap's captioned inset. Shared
   sentence. |
  | D04-G12 | a per-interval `source: recorded \| archive` on `GET /market/data-coverage`, so the
   chart's coverage chip and band (E16-D05) can label archive-derived ranges. Shared sentence. |
  | D04-CG1 | `HealthReport.components[].name` is a free string; `postgres`, `questdb`,
   `parquet_store` are the example's names (`22` :11014–11026), not an enum — the three tier cards
   bind to them by name and show "not reported" for a missing one |
  | D04-CG2 | `22` puts a step-up class on purge only (:15040); compact, import and the PROPOSED
   vacuum carry none, so no step-up sentence is drawn on their confirms |
  | D04-CG3 | the `22` example's `symbols[]` sum to 813.6 GB against 1,188.0 GB of QuestDB +
   Parquet: the per-symbol table states "{sum} of {budget used} attributed to symbols"; the example
   is not corrected |
  | D04-CG4 | jobs live in the API process (at most 256, lost at a restart, `22` :380,
   :12114–12117): the strip's "unknown" outcome and the reload case (`409 job_running` with no job
   id) are designed for |
  | D04-Q1 | does the owner want the `recorder_purge` step-up class on the PROPOSED vacuum (a `22`
   change)? Default proposed: none (non-destructive) |
  | D04-Q2 | a section of `/admin/recorder` (built) or its own `/admin/storage` route? One line
   changes if the owner prefers the route |
  | D04-Q3 | should the import get a CMP-044 standard confirm instead of the card form? Default:
   no (additive, resumable) |
  | D04-Q4 | the lag-warning threshold: 5 ILP batches of `write_backlog_rows` for two samples is
   PROPOSED; a registered state key is not needed while it stays a status |
  | D04-D1 | two meters, each labelled with its denominator (alternative rejected: one meter with
   a second scale) |
  | D04-D2 | SCR-142 is a section of `/admin/recorder` reached from SCR-140 and SCR-143
   (alternative: an own route, D04-Q2) |
  | D04-D3 | the per-symbol table stays the table variant: Purge… lives in the row's detail
   popover, not an actions column (alternative: a grid) |
  | D04-D4 | compact and vacuum confirm with CMP-044 standard (BQ-10 RULED); purge reuses E16-D02
   §6.5 (never a second purge shape: the alternative is rejected) |
  | D04-D5 | the import has no dialog; its consequence line is the confirm (BQ-12 RULED;
   alternative D04-Q3) |
  | D04-D6 | every PROPOSED capability is a captioned inset or second row with the shipped
   fallback beside it, never a frame's default (BQ-11 / 13 / 18 / 22 RULED; alternative rejected:
   drawing the target state) |
  | D04-D7 | the AC 2 sentence sits in the level banner on every level ≥ 1 frame and in the deck
   (alternative rejected: a tooltip) |
  | D04-D8 | the lag-warning state is keyed on the backlog (the produced number), not on a lag
   field that does not exist (BQ-17 RULED) |
  | D04-D9 | the light twin set: the warning tone on the canvas, the warning subtle rows, the T2
   pair (BQ-21 RULED) |
  | D04-D10 | analytics `storage.panel_viewed` once per entry (`14` :2779); the audited names are
   the server's (`recorder.import`, `retention.purge`; D04-C1); a T2 press emits nothing |
@ §14#1 ¶1 ‖ heading
  ## 14. Copy deck (every string SCR-142 shows; Source: `14` verbatim · an upstream spec and line
   · `new` = PROPOSED here, owner E16-D04)
@ §14#1 ¶2 ‖ paragraph
  Variables: `{HH:MM:SS}` 10:31:03; `{every}` 60 s; `{used}` / `{cap}` 1,188.0 GB / 2,000.0 GB;
   `{pct}` 59.4 %; `{d}` 422 (the autostop runway) or 560 (the full date); `{date}` 2028-03-27;
   `{growth}` 1.45 GB/day; `{symbol}` ETHUSDT; `{user}` alex; `{n}` / `{done}` 31 / 12; `{k}` 1;
   `{rows}` 660,000; `{code}` the server's stable code; `{verb}` Compaction · Import · Purge of
   {symbol} · Vacuum (PROPOSED, D04-G8). The fixture strings beside a template are the boards'
   words. Every `rbac.*` string ≤ 60 characters, names no data; no jargon in a user-facing string
   (the tool gates).
@ §14#1 ¶3 ‖ table
  | Key | String | Source | Frames |
  | -------------------------------- |
   ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
   ----------------------------------------------------------------------------------------------------------------------------------------
   | --------------------------------------------------------- |
  | `storage.title` | "Storage and database" | `14` :2770 (the heading, cased) | every page frame
   |
  | `storage.stamp` | "Sampled {HH:MM:SS} UTC (every {every})" · "Sampled 10:31:03 UTC (every 60
   s)" | `new` | every page frame |
  | `storage.stamp.stale` | "Sampled {HH:MM:SS} UTC, stale ({age} old)" · "Sampled 10:31:03 UTC,
   stale (3 min old)" | `new` | `SCR-142/stale-sample` |
  | `storage.stamp.sampling` | "Sampling…" | `new` | `SCR-142/loading` |
  | `storage.meter.budget` | "Recording budget: {used} of {cap} ({pct})" · "Recording budget:
   1,188.0 GB of 2,000.0 GB (59.4 %)" | `new` (the numerator rule `22` :5424) | every page frame |
  | `storage.meter.volume` | "Disk volume: {used} of {total} ({pct}), {free} free" · "Disk volume:
   1.2 TB of 4.0 TB (30.1 %), 2.8 TB free" | `new` | every page frame |
  | `storage.projection` | "Full in about {d} days ({date}) at {growth}: the {wall} is the nearer
   wall" · "Full in about 560 days (2028-03-27) at 1.45 GB/day: the budget is the nearer wall (the
   volume about 1,928 days)" | `new` (E16-D02 :153's rule) | `SCR-142/healthy` |
  | `storage.headline.0` | "Growing · auto-record pauses in about {d} days" · "Growing ·
   auto-record pauses in about 422 days" | E16-D02 §8.3 :490 | `SCR-142/healthy` |
  | `storage.headline.1` | "Near limit · auto-record pauses in about {d} days · clears below {warn
   − 5} %" · "… about 131 days · clears below 75 %" | E16-D02 §8.3 :493 |
   `SCR-142/low-disk-warning` |
  | `storage.headline.2` | "Auto-record paused · resumes below {autostop − 5} % of the budget with
   20 % of the volume free" | E16-D02 §8.3 :494 | `SCR-142/autostop` |
  | `storage.headline.3` | "Recording stopped · resumes below {halt − 5} % with 10 % of the volume
   free" · "… below 90 % …" | E16-D02 §8.3 :496 | `SCR-142/read-only-disk-full`, `/volume-refused`
   |
  | `storage.level3.fact` | "Open positions keep recording; other symbols' data is dropped and
   recorded as gaps." | E16-D02 §8.3 :496 | `SCR-142/read-only-disk-full` |
  | `storage.formula` | "({autostop} % × {cap} − {used}) ÷ {growth} ≈ {d} days" · "(90 % × 2,000.0
   GB − 1,188.0 GB) ÷ 1.45 GB/day ≈ 422 days" | E16-D02 §8.3 :490 | `SCR-142/healthy` |
  | `storage.scale` | "80 % warning · 90 % auto-record pauses · 95 % recording stops (open
   positions keep writing)" | E16-D02 §8.3 :499 | every page frame |
  | `storage.degradation` | "Recording pauses before trading is affected." | `new` (AC 2; `14`
   :2780) | every level ≥ 1 frame |
  | `storage.degradation.detail` | "At 90 % of the recording budget auto-record pauses; at 95 %
   recording stops for symbols without an open position; orders and positions are never gated by
   the disk." | `new` (`20` :905–907; `24` :3845, :3854) | every level ≥ 1 frame |
  | `storage.autostop.next` | "Recording stops at {halt} % in about {d} days" · "Recording stops
   at 95 % in about 69 days" | E16-D02 §8.3 :494 | `SCR-142/autostop` |
  | `storage.accelerated` | "Retention accelerated" | `new` (`22` :19243) | `SCR-142/autostop` |
  | `storage.volume_refused` | "The recording volume was refused at start-up; the gate opens once
   it is fixed" | `new` (`23` :4103–4104; SR-096) | `SCR-142/volume-refused` |
  | `storage.actions.shorten` | "Shorten retention" | E16-D02 §8.3 :503 | level ≥ 1 frames |
  | `storage.actions.depth` | "Reduce depth" | E16-D02 §8.3 :503 | level ≥ 1 frames |
  | `storage.actions.unpin` | "Unpin" | E16-D02 §8.3 :504 | level ≥ 1 frames |
  | `storage.tier.questdb` | "QuestDB · hot" | `new` (ADR-0003 :34) | `TIER/questdb` |
  | `storage.tier.parquet` | "Parquet/DuckDB · cold" | `new` (ADR-0003 :35) | `TIER/parquet` |
  | `storage.tier.postgres` | "Postgres · relational" | `new` (ADR-0003 :36) | `TIER/postgres` |
  | `storage.tier.rows` | "Size" · "Share of budget" · "Retention" · "Growth/day" · "Projected
   full" · "Health" · "Ingestion" · "Last compaction" · "Last vacuum" · "Migration" · "Rows by
   table" | `new` (`14` :2772, :2777; "Last compaction", "Last vacuum", "Migration" and "Rows by
   table" label PROPOSED rows: D04-G6, D04-G7, D04-G3) | `TIER/*` |
  | `storage.tier.not_counted` | "not counted" | `new` (`22` :5424) | `TIER/postgres` |
  | `storage.tier.all_tiers` | "all tiers {growth}" · "all tiers 1.45 GB/day" · "all tiers
   2028-03-27" | `new` (D04-G1's fallback) | `TIER/*` |
  | `storage.tier.health` | "healthy" · "degraded" · "warning" · "down" · "not deployed" · "not
   reported" | `22` :17419 (`ComponentState`); `new` the last | `TIER/*`,
   `SCR-142/tier-unreachable-questdb` |
  | `storage.tier.unreachable` | "{Tier} unreachable since {HH:MM:SS} UTC" · "QuestDB unreachable
   since 10:24:03 UTC" | `new` | `SCR-142/tier-unreachable-questdb` |
  | `storage.tier.retry` | "Retry" | E16-D02 §3.1 :191 | `SCR-142/tier-unreachable-questdb`,
   `SCR-142/unavailable` |
  | `storage.ingestion` | "Ingest {rate} msg/s, backlog {rows} rows, lag —" · "Ingest 18,400
   msg/s, backlog 25,000 rows, lag — (PROPOSED — D04-G4, owner approval pending (#2701))" | `new`
   (`23` :4060–4061; the lag PROPOSED, D04-G4) | `TIER/questdb`, `SCR-142/lag-warning` |
  | `storage.lag.banner` | "Ingestion backlog {rows} rows — writes are behind the feed" ·
   "Ingestion backlog 25,000 rows — writes are behind the feed" | `new` | `SCR-142/lag-warning` |
  | `storage.proposed.caption` | "PROPOSED — D04-G{n}, owner approval pending (#2701)" | `new`
   (the orchestrator's ruling) | every PROPOSED carrier |
  | `storage.proposed.rows` | "Row counts by table are not produced yet" | `new` (D04-G3's
   fallback) | `TIER/tables-questdb` |
  | `storage.proposed.queries` | "Slowest queries are not produced yet" | `new` (D04-G5's
   fallback) | `TIER/query-performance` |
  | `storage.compaction.schedule` | "weekly, Sundays 03:00 UTC" | `21` :4410 | `TIER/parquet` |
  | `storage.symbols.attributed` | "{sum} of {used} attributed to symbols ({pct})" · "813.6 GB of
   1,188.0 GB attributed to symbols (68.5 %)" | `new` (D04-CG3) | `TIER/per-symbol` |
  | `storage.migration.banner` | "Migration pending · {n} pending · {from} → {to} — applied with
   the next release" · "Migration pending · 1 pending · 0008 → 0009 — applied with the next
   release" | `new` (PROPOSED D04-G7; `22` :11103) | `SCR-142/migration-pending` |
  | `storage.unavailable` | "Disk figures could not be loaded." | E16-D02 §3.1 :191 |
   `SCR-142/unavailable` |
  | `storage.stale.announce` | "Storage figures are stale" | `new` | `SCR-142/stale-sample` |
  | `notice.panel_read_only` | "Read-only — read-only while viewing as {user}." · "Read-only —
   read-only while viewing as alex." | E16-D02 D-16 :778 (E09-D09 §10's template) |
   `SCR-142/view-as` |
  | `rbac.view_as` | "Read-only while viewing as {user}." | E09-D09 §3.1 :95 | `SCR-142/view-as` |
  | `storage.compact.button` | "Compact Parquet…" | `new` (E16-D02 §6.6's "Compact now" on
   SCR-140) | maintenance frames |
  | `storage.compact.title` | "Compact Parquet partitions?" | `new` | `JOB/confirm-compact` |
  | `storage.compact.body` | "Merges small files into partitions of at most 512 MiB. Nothing is
   deleted. Replay is paused on partitions it touches." | `new` (`21` :4414, :4417, :4418) |
   `JOB/confirm-compact` |
  | `storage.vacuum.button` | "Vacuum Postgres…" | `new` (PROPOSED D04-G8) | the vacuum inset |
  | `storage.vacuum.title` | "Vacuum Postgres?" | `new` (PROPOSED D04-G8) | `JOB/confirm-vacuum` |
  | `storage.vacuum.body` | "Reclaims space from deleted rows. Nothing is deleted. Queries may be
   slower while it runs." | `new` (PROPOSED D04-G8) | `JOB/confirm-vacuum` |
  | `storage.audited` | "This action is audited." | E16-D03 §5 :210 | `JOB/confirm-*` |
  | `storage.confirm.cancel` | "Cancel" | CMP-044 `15` :473 | every dialog |
  | `storage.job.running` | "{verb} running · {pct} %" · "Compaction running · 42 %" · "Import
   running · 38 %" | E16-D03 §8 :262 (the grammar) | `JOB/strip-running`, `IMPORT/running` |
  | `storage.job.started` | "{verb} started" · "Compaction started" · "Import started" | `new` |
   the strip (announced once) |
  | `storage.job.stop` | "Stop job" | `new` (PROPOSED D04-G10) | the strip's PROPOSED carrier |
  | `storage.job.refused.running` | "A {verb} is already running." · "A compaction is already
   running." | `new` (`22` :14942 `409 job_running`) | `JOB/strip-refused-409` |
  | `storage.compact.succeeded` | "Compacted at {HH:MM} UTC" · "Compacted at 10:42 UTC" | E16-D02
   §3.2 :204 | `JOB/outcomes` |
  | `storage.compact.failed` | "Compaction failed (`<code>`); nothing was deleted." | E16-D02 §3.2
   :203 | `JOB/outcomes` |
  | `storage.compact.cancelled` | "Compaction cancelled; nothing was deleted." | E16-D02 §3.2 :203
   (elided there; completed by D04-A8) | `JOB/outcomes` |
  | `storage.compact.unknown` | "Compaction status is no longer available on the server." |
   E16-D02 §3.2 :203 | `JOB/outcomes` |
  | `storage.vacuum.succeeded` | "Vacuumed at {HH:MM} UTC" | `new` (PROPOSED D04-G8) |
   `JOB/outcomes` |
  | `storage.vacuum.failed` | "Vacuum failed (`<code>`); nothing was deleted." | `new` (PROPOSED
   D04-G8) | `JOB/outcomes` |
  | `storage.vacuum.cancelled` | "Vacuum cancelled; nothing was deleted." | `new` (PROPOSED
   D04-G8) | `JOB/outcomes` |
  | `storage.vacuum.unknown` | "Vacuum status is no longer available on the server." | `new`
   (PROPOSED D04-G8) | `JOB/outcomes` |
  | `storage.purge.button` | "Purge data…" · "Purge…" | E16-D02 §6.5 :404 | `PURGE/entry-points` |
  | `storage.purge.title` | "Purge {symbol} data?" · "Purge ETHUSDT data?" | E16-D02 §6.5 :408 |
   `PURGE/dialog` |
  | `storage.purge.body` | "This deletes about {size} recorded from {from} to {to} from QuestDB
   and Parquet. It cannot be undone, and replay, footprint history and the journal lose this range.
   Shared QuestDB day partitions are freed by the nightly roll-off." | E16-D02 §6.5 :410–412 |
   `PURGE/dialog` |
  | `storage.purge.before` | "Delete data recorded before" | E16-D02 §6.5 :409 (`22` :15086:
   `before`, required) | `PURGE/dialog` |
  | `storage.purge.before.help` | "Data recorded at or after this time is kept." | `new` (`22`
   :15053–15054) | `PURGE/dialog` |
  | `storage.purge.before.reason` | "Choose a time no later than now." | `new` (`22` :15054–15057
   `before_in_future`) | `PURGE/dialog-validity` |
  | `storage.purge.refused.before` | "Not started: the time is later than the server's
   ({server_time}). Choose a time at or before it." | `new` (`22` :15054–15057: `422
   validation_failed`, the server's time in `message`) | — (T4 under Confirm, §1.3; no frame) |
  | `storage.purge.typed` | "Type the symbol to confirm" | E16-D02 §6.5 :415 | `PURGE/dialog` |
  | `storage.purge.typed.reason` | "Type {symbol} exactly to confirm." · "Type ETHUSDT exactly to
   confirm." | `new` (the validity reason) | `PURGE/dialog-validity` |
  | `storage.purge.stepup` | "You'll confirm with your password and a code." | E16-D02 §6.4 :388 |
   `PURGE/dialog`, `PURGE/step-up` |
  | `storage.purge.stepup.trusted` | "Still trusted for recorder changes · {mm:ss}" | E16-D02 §6.4
   :389 (never on purge: `recorder_purge` is no-grace, `22` :12495) | none (`PURGE/step-up` states
   why) |
  | `storage.purge.audited` | "This action is audited (high severity)." | E16-D02 §6.5 :417 |
   `PURGE/dialog` |
  | `storage.purge.confirm` | "Purge {symbol} data" · "Purge ETHUSDT data" | E16-D02 §6.5 :418 |
   `PURGE/dialog` |
  | `storage.purge.refused.pinned` | "Pinned data is excluded. Tick Include pinned to delete it
   too." | `new` (`22` :15045) | `PURGE/pinned-refused` |
  | `storage.purge.refused.audit` | "Not started: the audit record could not be written." | `new`
   (`22` :15073–15075) | §7 (T4) |
  | `storage.purge.failed` | "Purge of {symbol} failed (`<code>`). Some data may already be
   deleted: check {symbol}'s size and gaps." | E16-D02 §3.2 :200 | `PURGE/outcomes` |
  | `storage.purge.cancelled` | "Purge of {symbol} was cancelled. Data deleted before the cancel
   is gone." | E16-D02 §3.2 :201 | `PURGE/outcomes` |
  | `storage.purge.unknown` | "The purge's status is no longer available on the server. Check
   {symbol}'s size and gaps." | E16-D02 §3.2 :202 | `PURGE/outcomes` |
  | `storage.purge.succeeded` | "Purged {size} of {symbol} data" · "Purged 1.2 GB of ETHUSDT data"
   | E16-D02 §3.2 :204 | `PURGE/outcomes` |
  | `storage.import.button` | "Import archives" | `new` | `IMPORT/*` |
  | `storage.import.consequence` | "Imports Bybit's public daily trade archives (trades only, no
   book data). Recorded data wins where they overlap. Re-running skips finished days." | `new`
   (`22` :14981–14986) | `IMPORT/form` |
  | `storage.import.tag` | "Archive-derived · trades only · no book data" | `new` (`22`
   :14984–14985; US-REC-007 :4226) | `IMPORT/form`, `IMPORT/summary` |
  | `storage.import.range.reason` | "Choose a range of at most 366 days." | `new` (`22` :14982) |
   `IMPORT/form-validity` |
  | `storage.import.progress` | "{done} of {n} days · {pct} %" · "12 of 31 days · 38 %" · "30 of
   31 days · 96 %" | `new` | `IMPORT/running`, `/running-with-skips` |
  | `storage.import.skipped_count` | "{k} skipped" · "1 skipped" | `new` (PROPOSED D04-G11) | the
   running inset |
  | `storage.import.finished` | "Import finished: {symbol}, {from} → {to}" · "Import finished:
   BTCUSDT, 2026-01-01 → 2026-01-31" | `new` | `IMPORT/summary` |
  | `storage.import.columns` | "Day" · "Status" · "Reason" · "Rows" | `new` (PROPOSED D04-G11) |
   the per-file table |
  | `storage.import.status` | "done" · "skipped" · "error" · "downloading" | `new` (PROPOSED
   D04-G11) | the per-file table |
  | `storage.import.reason.checksum` | "Checksum did not match; the file was skipped." | `new`
   (`checksum_mismatch`, `22` :11809) | `IMPORT/running-with-skips` |
  | `storage.import.reason.parse` | "The file could not be read; it was skipped." | `new`
   (`parse_error`; PROPOSED D04-G11) | the per-file table |
  | `storage.import.reason.download` | "The file could not be downloaded; run the import again to
   retry it." | `new` (`download_failed`) | `IMPORT/summary` |
  | `storage.import.reason.already` | "Already imported on an earlier run." | `new`
   (`already_imported`; PROPOSED D04-G11; `22` :14985–14986) | the per-file table |
  | `storage.import.overlap` | "{rows} rows inside recorded windows were discarded — recorded data
   wins." · "660,000 rows inside recorded windows were discarded — recorded data wins." | `new`
   (PROPOSED D04-G11; `22` :14983–14984; US-REC-007 :4220) | `IMPORT/summary` |
  | `storage.import.summary` | "Imported {days} days of {symbol} trades · {k} file skipped · {e}
   file failed · {rows} overlapping rows discarded" · "Imported 29 days of BTCUSDT trades · 1 file
   skipped · 1 file failed · 660,000 overlapping rows discarded" | `new` (PROPOSED D04-G11) |
   `IMPORT/summary` |
  | `storage.import.failed` | "Import failed ({code}). Finished days are kept; run it again to
   resume." · "Import failed (download_failed). Finished days are kept; run it again to resume." |
   `new` (`22` :14985–14986) | `IMPORT/failed` |
  | `storage.import.cancelled` | "Import cancelled. Finished days are kept." | `new` (PROPOSED
   D04-G10) | §8 |
  | `storage.import.unknown` | "The import's status is no longer available on the server. Run it
   again: finished days are skipped." | `new` | `IMPORT/failed` |
  | `storage.import.resume` | "Run it again to resume: finished days are skipped." | `new` (`22`
   :14985–14986) | `IMPORT/summary`, `IMPORT/failed` |
  | `storage.links.storage_details` | "Storage details →" | `new` (D04-A4; on SCR-140's card) |
   SCR-140 (E16-D02's card) |
  | `storage.links.health` | "System health →" | `new` (the CMP-178 tile to SCR-143) | every page
   frame |
@ §15#1 ¶1 ‖ heading
  ## 15. Measured contrast (the tool, section 1; dark / light / high-contrast through
   `themes.json`)
@ §15#1 ¶2 ‖ paragraph
  Dark / light / high-contrast = `semantic-dark`; `semantic-light` over it; `semantic-hc` over it.
   Bars 4.5 text · 3.0 non-text; the `decorative` and `rejected-text` rows are reported, never
   gated. ⟦audit:pairs_rows⟧ gated pairs, ⟦audit:pairs_fail⟧ FAIL, ⟦audit:pairs_registered⟧
   registered / ⟦audit:pairs_proposed⟧ PROPOSED `pairs.mjs` rows (the boards PR registers the
   PROPOSED ones). The meter track is `color.surface.sunken` because the danger fill measures 2.92
   on CMP-023's `color.surface.hover` track in dark (D04-A7). `color.text.disabled` is never drawn
   (the one REJECTED row says why: ⟦audit:ratios.disabled.dark⟧ on the card). The validity
   composite (the primary label at `opacity.disabled` over the card) is ⟦audit:composite.dark⟧ /
   ⟦audit:composite.light⟧ / ⟦audit:composite.high-contrast⟧, reported and not gated: the reason
   beside it carries the meaning at full opacity (E30-D02 D3).
@ §15#1 ¶3 ‖ table
  | Element | fg | bg | role | dark | light | hc | verdict | pairs.mjs |
  | ----------------------------------------------------------------- |
   --------------------------------------- | ------------------------------ | ------------- | -----
   | ----- | ----- | --------------------- | ---------- |
  | page words on the admin canvas | `color.text.primary` | `color.surface.canvas` | text | 15.20
   | 16.78 | 17.21 | PASS | registered |
  | secondary words on the canvas (the projection line, the stamp) | `color.text.secondary` |
   `color.surface.canvas` | text | 9.33 | 9.65 | 15.20 | PASS | registered |
  | card words (tier rows, table cells on even rows) | `color.text.primary` |
   `color.surface.raised` | text | 14.35 | 15.62 | 16.25 | PASS | registered |
  | captions, units, reasons, the T2 reason on raised | `color.text.secondary` |
   `color.surface.raised` | text | 8.81 | 8.98 | 14.35 | PASS | registered |
  | T2 label and lock; tertiary words (the stamp's cadence) on raised | `color.text.tertiary` |
   `color.surface.raised` | text | 5.62 | 5.92 | 11.21 | PASS | registered |
  | table header words | `color.text.primary` | `color.surface.hover` | text | 12.22 | 14.37 |
   13.83 | PASS | PROPOSED |
  | field value in the well (import form, purge dialog) | `color.text.primary` |
   `color.surface.app` | text | 16.06 | 17.99 | 18.18 | PASS | registered |
  | field well boundary | `color.text.tertiary` | `color.surface.app` | non-text | 6.29 | 6.81 |
   12.54 | PASS | registered |
  | meter fill level 0 on its track | `color.action.primary.default` | `color.surface.sunken` |
   non-text | 4.41 | 3.39 | 8.08 | PASS | PROPOSED |
  | meter fill level 1 and 2 on its track | `color.status.warning.strong` | `color.surface.sunken`
   | non-text | 13.36 | 3.37 | 13.36 | PASS | registered |
  | meter fill level 3 on its track | `color.status.danger.default` | `color.surface.sunken` |
   non-text | 4.16 | 7.35 | 4.92 | PASS | PROPOSED |
  | health glyph ok on the card | `color.status.success.strong` | `color.surface.raised` |
   non-text | 9.40 | 3.39 | 9.40 | PASS | PROPOSED |
  | health glyph warning on the card | `color.status.warning.strong` | `color.surface.raised` |
   non-text | 11.00 | 4.11 | 11.00 | PASS | PROPOSED |
  | health glyph down on the card | `color.status.danger.strong` | `color.surface.raised` |
   non-text | 9.32 | 4.11 | 9.32 | PASS | PROPOSED |
  | warning banner and skipped-row words | `color.text.primary` | `color.status.warning.subtle` |
   text | 9.86 | 15.62 | 11.16 | PASS | registered |
  | warning banner glyph | `color.status.warning.strong` | `color.status.warning.subtle` |
   non-text | 7.56 | 4.11 | 7.56 | PASS | registered |
  | import failed words (inside the card) | `color.text.primary` | `color.status.danger.subtle` |
   text | 12.06 | 14.64 | 13.66 | PASS | registered |
  | import failed glyph | `color.status.danger.strong` | `color.status.danger.subtle` | non-text |
   7.83 | 3.85 | 7.83 | PASS | PROPOSED |
  | job succeeded words | `color.text.primary` | `color.status.success.subtle` | text | 10.21 |
   15.41 | 11.56 | PASS | PROPOSED |
  | job succeeded glyph | `color.status.success.strong` | `color.status.success.subtle` | non-text
   | 6.69 | 3.34 | 6.69 | PASS | PROPOSED |
  | info line words (overlap report) | `color.text.primary` | `color.status.info.subtle` | text |
   10.74 | 15.44 | 12.16 | PASS | registered |
  | info line glyph | `color.status.info.strong` | `color.status.info.subtle` | non-text | 7.30 |
   4.34 | 7.30 | PASS | PROPOSED |
  | primary button label (Import archives, Compact) | `color.text.on-action` |
   `color.action.primary.default` | text | 4.76 | 4.76 | 7.45 | PASS | registered |
  | destructive Confirm label on the danger fill (Purge) | `color.text.on-action` |
   `color.status.danger.default` | text | 5.05 | 10.31 | 4.54 | PASS | PROPOSED |
  | sparkline stroke (the PROPOSED D04-G2 inset) | `color.text.tertiary` | `color.surface.raised`
   | non-text | 5.62 | 5.92 | 11.21 | PASS | registered |
  | stale clock glyph on raised | `color.data-confidence.stale.indicator` | `color.surface.raised`
   | non-text | 11.00 | 4.11 | 11.00 | PASS | PROPOSED |
  | invalid well boundary | `color.status.danger.default` | `color.surface.raised` | non-text |
   3.43 | 8.95 | 4.05 | PASS | PROPOSED |
  | focus ring on the canvas | `color.focus.ring` | `color.surface.canvas` | non-text | 7.05 |
   6.30 | 18.32 | PASS | registered |
  | focus ring on raised | `color.focus.ring` | `color.surface.raised` | non-text | 6.66 | 5.86 |
   17.30 | PASS | registered |
  | REJECTED T2 label in text.disabled | `color.text.disabled` | `color.surface.raised` |
   rejected-text | 2.86 | 3.74 | 2.86 | rejected, never drawn | PROPOSED |
  | the card hairline | `color.border.default` | `color.surface.raised` | decorative | 1.41 | 1.22
   | 2.86 | reported, not gated | PROPOSED |
@ §16#1 ¶1 ‖ heading
  ## 16. The catalogue checklist, item by item (`14` :2780)
@ §16#1 ¶2 ‖ table
  | Item | Frame |
  |
   ---------------------------------------------------------------------------------------------------------------------------------------
   |
   -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | 14:2780 all three tiers drawn with size, growth rate and projected full date | `TIER/questdb`,
   `TIER/parquet`, `TIER/postgres` (board 02): size and retention shipped; growth and projected
   full "—" captioned PROPOSED (D04-G1) with the disk-level fallback beside them — satisfied as
   PROPOSED (BQ-18 RULED) |
  | 14:2780 per-symbol breakdown for the hot tier | `TIER/per-symbol` (board 02): Symbol / Size /
   Growth/day / Share of budget / Pinned from `symbols[]`; the attribution line (D04-CG3) |
  | 14:2780 maintenance actions with progress and cancel | `JOB/confirm-compact`,
   `JOB/strip-running`, `JOB/outcomes` (board 05), `PURGE/*` (board 06), `IMPORT/running` (board
   07): progress shipped (`Job.progress_pct`); Stop job (the cancel) a captioned PROPOSED carrier
   (D04-G10) — satisfied as PROPOSED (BQ-13 RULED) |
  | 14:2780 low-disk warning and critical states drawn with what stops working first (recording
   pauses before trading is affected - stated) | `SCR-142/low-disk-warning`, `/autostop`,
   `/read-only-disk-full`, `/volume-refused` (board 03): the sentence "Recording pauses before
   trading is affected." and the detail line on each (§1.4; R-5) |
  | 14:2780 query-performance indicators | `TIER/query-performance` (board 02): a captioned
   PROPOSED second row (D04-G5) with the shipped fallback — satisfied as PROPOSED |
  | 14:2780 error state when a tier is unreachable | `SCR-142/tier-unreachable-questdb` (board
   04): the card's CMP-027 inline error with Retry; the page usable (R-4) |
@ §16#1 ¶3 ‖ paragraph
  AC 3 is traced the same way: `IMPORT/running-with-skips` draws the shipped running state (the
   bar, its days, the strip), and its per-file skip row and the "1 skipped" counter while the
   import runs are met **as PROPOSED** (D04-G11's `files[]` stream, a captioned inset), with no
   page banner in either.
@ §17#1 ¶1 ‖ heading
  ## 17. Flows, heuristic evaluation and the owner walkthrough
@ §17#1 ¶2 ‖ paragraph
  **Flows (every step a frame).** ⟦audit:flows⟧ flows.
@ §17#1 ¶3 ‖ table
  | # | Flow |
  | --- |
   --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   |
  | F1 | Read the picture: `SCR-142/healthy` → the tier cards → `TIER/per-symbol` → the SCR-143
   tile link; at 200 % `SCR-142/healthy-200-zoom` |
  | F2 | A warning day: `SCR-142/low-disk-warning` → Shorten retention (SCR-141) or Unpin
   (SCR-140) → back; `SCR-142/autostop` → `SCR-142/read-only-disk-full` with every action still
   enabled |
  | F3 | Compact: `SCR-142/healthy` → `JOB/confirm-compact` → `JOB/strip-running` →
   `JOB/outcomes`; a second press → `JOB/strip-refused-409` |
  | F4 | Purge one symbol: `PURGE/entry-points` → `PURGE/dialog` (`PURGE/dialog-validity` while
   typing) → `PURGE/step-up` → `PURGE/outcomes`; a pinned symbol → `PURGE/pinned-refused` |
  | F5 | Import a month: `IMPORT/form` (`IMPORT/form-validity` on a bad range) → `IMPORT/running`
   → `IMPORT/running-with-skips` → `IMPORT/summary`; a failed download after the retry budget →
   `IMPORT/failed` → run it again |
@ §17#1 ¶4 ‖ paragraph
  **Heuristic evaluation `(heuristic)`** (Nielsen; `05`'s trading heuristics). Visibility of
   system status: the stamp and the staleness marker on every page frame; the strip's text-first
   progress. Match with the real world: sizes in GB / TB with one decimal, days of runway, dates as
   ISO; the headline words are E16-D02's. User control: every action is explicit and confirmed
   (compact / the PROPOSED vacuum (D04-G8) standard, purge typed); nothing heavy runs on page load.
   Consistency: one purge dialog (E16-D02's), one job grammar (E16-D03's), one T2 grammar
   (E09-D09's). Error prevention: the typed symbol and the reason on purge; the 366-day range
   reason before a press. Recognition: the PROPOSED carriers are captioned so a reader never takes
   a gap for a shipped control. Flexibility: none added — no hotkeys in the admin area. Aesthetic
   and minimalist: the shipped frame is the default; PROPOSED carriers are insets. Error recovery:
   a skipped file is a row with its reason and the import continues; a failed import says how to
   resume. Help: the consequence lines on compact, the PROPOSED vacuum (D04-G8) and import. Risks
   found `(heuristic)`: the two meters could be read as one if their labels were dropped (D04-D1
   keeps both labels); a dashed PROPOSED outline might be misread (the caption carries the meaning:
   absent from the contract, never a disabled control; E25-D01 §9.5's rule holds); the attribution
   line could be read as a bug report (it is: D04-CG3, stated in words).
@ §17#1 ¶5 ‖ paragraph
  **Owner walkthrough** (posted on #372 at merge, not in `14`): W1 read the healthy page and say
   which wall is nearer; W2 find the Postgres size and say what it is not counted in; W3 at level
   1, say what stops first; W4 start a compaction and find its progress and its outcome; W5 purge
   ETHUSDT and stop at the typed field (it is empty); W6 import January and find the skipped day
   and its reason; W7 point at every PROPOSED carrier and name the gap it stands for; W8 view as
   alex and find the one notice; W9 at 200 % find the per-symbol table's rows.
@ §18#1 ¶1 ‖ heading
  ## 18. AC → evidence, deviations, hand-offs, summary
@ §18#1 ¶2 ‖ paragraph
  **DoD:** the six checklist items → §16 (the `14` boxes are posted on #372 at merge, not edited
   here); the three ACs → the AC trace (R-1, R-5, R-9 / R-10); design sign-off → the owner's
   `approved` (pending); the import flow reviewed by the backend lead against the importer's real
   capabilities (resumable, rate-limited, recorded data wins on overlap) → under the agent-delivery
   adaptations the owner's approval stands in for that review, and the importer check itself is
   handed to E16-T10 (the import's implementation ticket), with §8 citing `22` :14979–14988 for
   each capability; Sprint 05 → the owner. **Deviations (recorded, not hidden):** (1) branch
   `design/e16-d04-storage-panel-hifi`, not the ticket's `design/e16-scr142` (C-4.4); (2) the
   ticket's `apps/web/src/features/<feature>/` paths, `pnpm` commands and closing-keyword body line
   are the web template on a design ticket — the deliverable is this spec, the tool and one `14`
   pointer line; the text-first PR carries `Refs #372` and a `Partial:` line, the boards PR carries
   the issue's closing keyword; (3) `15` is not edited (A-rows only, D04-A1…A3, A7); (4) the
   ticket's "vacuum", "cancel", "row counts", "slowest queries", "last vacuum / compaction" and
   "migration version" are drawn as captioned PROPOSED carriers (D04-G8, G10, G3, G5, G6, G7),
   never as shipped controls (BQ-11 / 13 / 18 RULED); (5) the ticket's audit names are `14`'s and
   differ from `22`'s (D04-C1); (6) no hand-off file (BQ-3 RULED); (7) Figma → Penpot; the boards
   are PENDING (text-first). **Hand-offs:** the E16 implementation ticket that consumes SCR-142
   (E16-S05 / E16-S08 per the ticket; E16-T10 for the import, E16-T07 for `DiskBudget`) — the
   build, every `storage.*` key, the frames, and the contract-first PRs for D04-G1…G12; E16-D06 —
   the a11y review of §10 and the hand-off of the set; E16-D07 — design QA of F1–F5; the `14` owner
   — D04-A4…A6, D04-C1…C3; the E16-D02 owner — D04-A8, D04-C6; the `15` owner — D04-A1…A3, D04-A7,
   D04-C4; the `22` owner — D04-G1…G12, D04-CG1, D04-CG2; the owner — D04-Q1…Q4. **Summary:** one
   admin section with eight regions: two labelled meters and the sample stamp, three tier cards
   with health as text, the per-tier tables and the per-symbol table, the maintenance card with its
   jobs strip, the import card with per-file reporting; ⟦audit:frames_total⟧ frames across 9 dark
   boards and 1 light board (PENDING); the only T2 is the view-as leg; purge is E16-D02's typed
   dialog, compact and the PROPOSED vacuum (D04-G8) are standard confirms that delete nothing; the
   degradation order is stated in text on every warning state; every missing field is a captioned
   PROPOSED carrier beside its shipped fallback; every number is the tool's and every frame gate is
   mutation-tested (⟦audit:mutations⟧ mutations, each its mutation's only FAIL with a distinct
   message); the boards land in the second PR with the page id.
"""


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
