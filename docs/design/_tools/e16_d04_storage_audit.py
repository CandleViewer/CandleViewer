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
body's required triple, the 366-day cap, the section 5.4 compaction thresholds, the `CV_DISK_*` steps,
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
the facts, the layout, the counts and the typed context); (7) the counts the spec, the boards and the PR body quote.
`--json` feeds the check-nums script; `--check` re-derives the spec's `<!-- audit:key=N -->` markers and checks
the number printed before each; `--self-test` applies the numbered mutations in memory, one at a time,
and passes only when each makes `--check` fail with ONE FAIL, its own expected message (rc 1), no two
share a message, the valid twins raise nothing, the unmutated spec passes and the spec file is byte-identical
afterwards; `--mutate N` prints one mutation's gate output and exits rc 1 when the targeted FAIL is the only
FAIL (the gate caught it), rc 2 when the mutation slips through or fails elsewhere (a defect in the gate), never 0.
Every other mode exits 1 on a gated FAIL.

Usage: python3 -I docs/design/_tools/e16_d04_storage_audit.py [--json] [--check] [--self-test]
  [--mutate N] [--extra F]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
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
22 | 378 | `compactRecorder`, `importTradeArchive` and `purgeRecordedData` keep theirs: at most 256 jobs
22 | 715 | The typed confirm_symbol does not equal the symbol to purge
22 | 721 | code: import_range_invalid
22 | 4993 | operationId: getStorageUsage
22 | 5004 | the `questdb` plus `parquet` `tiers[]` bytes by `cap_bytes`
22 | 5015 | disk_total_bytes: 4000000000000
22 | 5026 | { tier: questdb, used_bytes: 640000000000, retention_days: 7 }
22 | 10458 | operationId: getHealth
22 | 10486 | detail: "ingest 18.4k msg/s"
22 | 10570 | Dependencies reachable and migrations applied
22 | 11276 | (`checksum_mismatch` when the stored digest does
22 | 11572 | operationId: getJob
22 | 11584 | Every `404` here carries rule `job_unknown`
22 | 13501 | CHECK (migration 0008, `21-database-schema.md` §3.10.2)
22 | 14043 | operationId: compactRecorder
22 | 14048 | One compaction at a time (`409 job_running`)
22 | 14084 | operationId: importTradeArchive
22 | 14088 | `[from, to]` (inclusive UTC dates, at most 366 days)
22 | 14089 | Recorded data wins: rows inside a
22 | 14091 | archive-derived and cover `trades` only
22 | 14094 | Audited as `recorder.import`
22 | 14138 | operationId: purgeRecordedData
22 | 14141 | Requires an elevated session, a mandatory reason, and
22 | 14145 | Elevation is the `recorder` step-up class
22 | 14150 | The audit record (`retention.purge`, exact window, partition count, rows, bytes)
22 | 14164 | required: [symbol, confirm_symbol, reason]
22 | 16368 | enum: [healthy, degraded, warning, down, not_deployed]
22 | 18101 | tier: { type: string, enum: [questdb, parquet, postgres] }
22 | 18115 | level: { type: integer, enum: [0, 1, 2, 3] }
22 | 20691 | last_good_at: { type: ["string", "null"], format: date-time }
22 | 20843 |                 archive_import,
22 | 20847 | status: { type: string, enum: [queued, running, succeeded, failed, cancelled] }
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
15 | 811 | ### CMP-079 RbacGate
15 | 884 | ### CMP-087 AdminLayout
15 | 2068 | ### CMP-178 SystemHealthTile
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
    f["purge_required"] = first(r"required: \[(symbol, confirm_symbol, reason)\]", a22).split(", ")
    f["purge_sentences"] = {
        "elevated": "Requires an elevated session, a mandatory reason, and" in a22,
        "stepup_class": "Elevation is the `recorder` step-up class" in a22,
        "audit_first": "written BEFORE the job exists; if it cannot be written the answer is 503"
        in a22,
        "pinned_refused": "`retention_pinned_refused` (pinned without `include_pinned`)" in a22,
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
NEGATOR = r"(?:no|never|not|without|none|nothing|nor|neither|absent|isn't|aren't)"
CLAUSE_STOP = r"[,;:()·—]|\.\s"
LOCK_TERM = r"\b(?:locked|locks?|padlock|T2|CMP-079|RbacGate)\b"
DIM_TERM = (
    r"\baria-disabled\b|\bopacity\.disabled\b|\bcolor\.text\.disabled\b|\b\d+ ?% opacity\b"
    r"|\b(?:disabled|gr[ae]yed(?: out)?|dimmed|dims|faded|inert|unavailable|blocked|gated)\b"
    r"|\b(?:not|no longer) (?:available|usable|pressable|clickable)\b(?! on the server)"
    r"|\b(?:can't|cannot|can not) be (?:pressed|used|clicked|activated)\b"
)
# the T2 anatomy's own words on the view-as frame; every other dim word there is a FAIL
T2_DIM = (
    r"\bopacity\.disabled\b|\bcolor\.text\.disabled\b|\b\d+ ?% opacity\b"
    r"|(?<!aria-)\bdisabled\b|\b(?:gr[ae]yed(?: out)?|dimmed|dims|faded)\b"
)
# R-7: a typed confirm field shown filled. The strong words fail anywhere; the context words fail when the typed
# field is the subject (named before them in the unit, or carried by an item or a sentence that opens on a pronoun).
SYM = r"(?:the |its |a |that )?\{?(?:symbol|ETHUSDT|BTCUSDT)"
FILL = (
    r"\b(?:pre-?filled|prefill(?:ed|s|ing)?|auto-?fill(?:ed|s|ing)?|pre-?populated|filled in"
    rf"|typed into|copied into|pasted into|defaults? to {SYM}|(?:entered|inserted|supplied|filled"
    r"|typed|put in|placed) (?:for (?:you|the Owner)|automatically|by the (?:dialog|client|app|page)))\b"
)
FILL_CONTEXT = (
    r"\b(?:set to|already (?:holding|holds|contains|containing|carrying|carries|shows|showing|has|having"
    r"|reads|reading|in (?:it|place|there))|defaulted|seeded|populated|holding the symbol"
    r"|with the symbol in it|empty (?:at first|initially|until)|then (?:set|filled|holds|shows|reads)"
    r"|(?:comes?|arrives?|opens?|starts?|loads?|appears?|renders?)(?: already)? (?:with|holding|showing"
    rf"|containing|carrying|reading) {SYM}|suggests? {SYM})\b"
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
# the exit Cancel in its own forms: never captioned, never locked; any other "Cancel" on a frame is a job action
EXIT_CANCEL = (
    r"\bCancel, Esc and the close ✕|\bCancel (?:and|/) (?:Esc|Confirm|Compact|Vacuum|the verb)\b"
    r"|\bexits? Cancel\b|\bEsc = Cancel\b|\bfocus starts on Cancel\b"
)
# PROPOSED carriers: a vocabulary per gap id (the n the caption must carry); the first match in an item wins.
CARRIERS: tuple[tuple[str, str, frozenset[int]], ...] = (
    ("last vacuum or compaction", r"\blast (?:vacuum|compaction)\b", frozenset({6})),
    ("vacuum", r"\bvacuum", frozenset({8})),
    (
        "stop job",
        r"\b(?:stop(?: job)?|cancel|abort|end(?: the)? job|kill|terminate)\b",
        frozenset({10}),
    ),
    (
        "per-file rows",
        r"\bper-file\b|files\[\]|\b\d+ skipped\b|skipped ⚠|\bDay / Status(?: / [A-Z]\w*)*",
        frozenset({11}),
    ),
    (
        "row counts",
        r"\brows? by table\b|\brow counts?\b|\bRows [\d,]{3,}|(?-i:\bRows\b)",
        frozenset({3}),
    ),
    (
        "slow queries",
        r"\bslow(?:est)? quer|\bp95\b|\bquery[- ]performance\b|\bstatement kind\b",
        frozenset({5}),
    ),
    ("per-tier growth", r"\bGrowth/day —|\bProjected full —", frozenset({1})),
    ("lag", r"\blag\b", frozenset({4})),
    (
        "sparkline",
        r"\bspark ?lines?\b|\bhistory_bytes|\bOldest\b|\bCMP-024\b|\btrend ?lines?\b|\bmini[- ]?charts?\b",
        frozenset({2, 3}),
    ),
    (
        "migration",
        r"\bMigration (?:pending|\d{4})|\b\d{4} → \d{4}|\bschema[_ ]version|(?<!§)\b\d+ pending\b",
        frozenset({7}),
    ),
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
    "vacuum": (
        r"\bVacuum Postgres…|\bVacuum (?:button|control|action|inset)\b|\[ ?Vacuum",
        frozenset({8}),
    ),
    "stop job": (
        (
            r"\bStop job\b|\bEnd(?: the)? job\b|\bCancel (?:button|control)\b"
            r"|\bCancel (?:per|on (?:the|each|every)) job|\bCancel on the jobs strip\b"
        ),
        frozenset({10}),
    ),
    "row counts": (
        r"(?-i:\bRows\b)(?! by)|\brows by table\b|\brow counts? (?:by|per) table\b",
        frozenset({3, 11}),
    ),
    "slow queries": (r"\bp95\b|\bslowest queries\b|\bquery performance\b", frozenset({5})),
    "sparkline": (
        r"\bsparklines?\b|\bCMP-024\b(?! :)|\btrend ?lines?\b|\bhistory_bytes\b|\bOldest / Newest\b",
        frozenset({2, 3}),
    ),
    "last vacuum or compaction": (r"(?-i:\bLast (?:vacuum|compaction)\b)", frozenset({6})),
    "migration": (
        r"\bschema[_ ]version\b|(?-i:\bMigration \d{4}\b)|\b\d{4} → \d{4}\b|\bpending_migrations\b",
        frozenset({7}),
    ),
    "per-file rows": (
        r"\bper-file (?:table|rows?|CMP-049)\b|Day / Status / Reason / Rows|\bskip counter\b|files\[\]",
        frozenset({11}),
    ),
    "lag": (r"\blag (?:cell|field)\b|\bingest_lag_ms\b", frozenset({4})),
    "per-tier growth": (r"\bper-tier growth\b|\btiers\[\]\.daily_growth_bytes\b", frozenset({1})),
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
    return {"exit": exit_, "write": WRITE_TERM}


ACTION_KINDS = {"purge": PURGE_SUBJ, "other": OTHER_ACTION}


def gated_term(
    x: str,
    carried: str,
    kinds: dict[str, str],
    want_exit: bool,
    only: tuple[str, ...] = ("lock", "dim"),
) -> tuple[str, str] | None:
    """The first un-negated lock or dim word whose subject is (want_exit) or is not an exit: (word, kind)."""
    hits = sorted(
        (m.start(), m.group(0), which)
        for which, pat in (("lock", LOCK_TERM), ("dim", DIM_TERM))
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
    return None


def ruled_order(x: str) -> bool:
    """The ruled order stated in any wording (recording pauses before trading is affected)."""
    return order_issue(x) is None and any(re.search(p, x, re.IGNORECASE) for p in RULED_ORDER)


def shipped_mention(
    text: str, dialog: bool = False, whole: bool = False, strong: bool = True
) -> tuple[str, str, int] | None:
    """The first PROPOSED item `text` presents as shipped, as (name, the words, its gap n), or None. `text` is
    scrubbed (captions read CAPTIONn); a clause ends at `;` ` · ` a sentence break or a cell bar. A name (DOC_STRONG)
    in a table row is answered by the caption or the absence anywhere in the row (`whole`: read across its cells);
    a presenting form (SHIPPED) must be answered in its own clause."""
    gap_ids = {what: ids for what, _, ids in CARRIERS} | {k: v[1] for k, v in DOC_STRONG.items()}

    def answered(scope: str, ids: frozenset[int]) -> bool:
        caps = {int(n) for n in re.findall(r"CAPTION(\d+)", scope)}
        named = {int(n) for n in re.findall(r"\b(?:D04-)?G(\d+)\b", scope)}
        return bool(caps & ids) or (re.search(GAP_ABSENT, scope) is not None and bool(named & ids))

    exit_ = EXIT_CANCEL + (r"|\bCancel\b" if dialog else "")
    for clause in re.split(r";|\s·\s|\.\s|\|", text):
        bare = re.sub(exit_, " ", clause)
        names = [(k, v[0]) for k, v in DOC_STRONG.items()] if strong else []
        for what, pat in names + list(SHIPPED.items()):
            ids = gap_ids[what]
            term = positive_term(bare, pat)
            if term is None:
                continue
            scope = text if (whole and what in DOC_STRONG and (what, pat) in names) else clause
            if not answered(scope, ids):
                return what, term, min(ids)
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


def anchor_table(fx: dict[str, Any], facts: dict[str, Any]) -> list[Anchor]:
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
    return out


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
    term = unregistered(item, reg)
    if term is not None:
        return f"R-17 {name}: number not the tool's ({term})"
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
        bad += row_presence(
            name, cls, producer, shows, controls, text, low, s, own, fx, need, reasons
        )
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
    anchors = anchor_table(fx, facts)
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
    "`importTradeArchive` (`22` :14081–14134) imports",
)
P14, PEND = "The ladder is the server's", "E16-D06 and E16-D07 are PENDING by name;"
PDV, EXITS_T1 = "PURGE/dialog-validity", "exits Cancel, Esc and the close ✕ (T1)"
LINKS_T1 = "links to SCR-140, SCR-141 and SCR-143 enabled (T1)"
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
            ', the overlap report "660,000 rows inside recorded windows were discarded — recorded data wins." (`22` :14089, never "duplicates removed")',
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
        "R-12 questdb: Rows 1,204,553,120 without its caption (D04-G3)",
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
        "R-17 SCR-142/low-disk-warning: number not the tool's (1611.0 GB)",
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
        "R-12 §1.1 prose: stop job presented as shipped ('Stop button')",
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
        "R-12 §4 prose: per-tier growth presented as shipped ('Growth/day 1')",
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
        "R-12 §5 prose: lag presented as shipped ('lag 4')",
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
    n["valid_twins"] = len(VALID)
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
) -> tuple[list[str], dict[str, Any], list[dict[str, object]], list[str], int]:
    facts = contract_facts(t)
    fx = fixture(facts, t["22"])
    numbers, matrix, missing, fails = numbers_of(spec, facts, fx, themes, registered)
    bad = gates([SPEC, *extra], spec, facts, fx, t, numbers)
    bad += matrix_gate(spec, matrix)
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
                if key.startswith("board_frames."):
                    nn = key.split(".")[1]
                    bad.append(
                        f"R-18: §0 and §{BOARD_SECTION.get(nn, '?')}'s table disagree (board {nn}: §0 says {val}, the table {have})"
                    )
                else:
                    bad.append(f"marker audit:{key}={val} vs tool {have}")
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
            out.append(f"mutation {i:3d} FAIL as expected, its only FAIL: {bad[0]}")
        else:
            ok = False
            out.append(
                f"mutation {i:3d} DEFECT ({len(bad)} FAIL): {desc} — " + " | ".join(bad)[:300]
            )
    for desc, fn in VALID:
        bad, _, _, _, _ = run(fn(spec), t, themes, registered, [], True)
        ok = ok and not bad
        out.append(
            f"valid twin {desc[:3]} "
            + ("PASS, no FAIL" if not bad else "DEFECT: " + " | ".join(bad)[:300])
        )
    sigs = list(signatures.values())
    dup = sorted({s for s in sigs if sigs.count(s) > 1})
    if dup:
        ok = False
        out.append("duplicate FAIL messages: " + " | ".join(dup))
    same = hashlib.sha256(SPEC.read_bytes()).hexdigest() == before
    ok = ok and same
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(set(sigs))} distinct FAIL messages, each its mutation's only FAIL; {len(VALID)} valid twins clean; the unmutated spec "
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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
