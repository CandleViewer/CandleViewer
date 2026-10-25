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
no closing keyword, the PENDING siblings by name only); (6) the frame gates, read table by table, row
by row and clause by clause (spec section 12, rules R-1 to R-22): the three tiers legible with units,
the sample stamp, the two labelled meters, health as text, the degradation sentence on every level >= 1
frame, no lock on any state frame, the purge triple with the typed field empty, the validity look
without a lock, a failing import inside its card, the per-file reporting, busy as status, every
PROPOSED carrier captioned, the view-as T2 anatomy first, the exits enabled, no console or backup
control, every number the tool's, the frame inventory, the confirm pattern per action, one
announcement per terminal state; (7) the counts the spec, the boards and the PR body quote. `--json`
feeds the check-nums script; `--check` re-derives the spec's `<!-- audit:key=N -->` markers and checks
the number printed before each; `--self-test` applies the numbered mutations in memory, one at a time,
and passes only when each makes `--check` fail with ONE FAIL, its own expected message (rc 1), no two
share a message, the unmutated spec passes and the spec file is byte-identical afterwards; `--mutate N`
prints one mutation's gate output and exits rc 1 when the targeted FAIL is the only FAIL (the gate
caught it), rc 2 when the mutation slips through or fails elsewhere (a defect in the gate), never 0.
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
# Generic patterns only: no personal word, no hostname whole or split; the path literal is split.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"\bwt-no[t]es\b",
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
INVERTED = (
    r"trading (?:pauses|stops) before",
    r"trading is affected before",
    r"orders? (?:pause|stop)s? before",
)
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
# Words a clause negates with; a clause carrying one of them reads as a negation (E16-D05's reading).
NEG = r"\b(?:no|never|not|without|none|nothing|absent|nor|neither)\b"
CLAUSE_SEP = r"\s·\s|;\s"
EXIT_RE = r"\b(?:Esc|Close|Back|exits?|Shorten retention|Reduce depth|Unpin|SCR-14[013]|Retry|Open recorder)\b"
DIALOG_FAMILIES = ("JOB/confirm-", "PURGE/dialog", "PURGE/step-up", "PURGE/pinned-refused")
LOCKISH = r"\block\b|\bT2\b|\baria-disabled\b|opacity\.disabled|color\.text\.disabled"
CARRIER_ROW = r"\bvacuum\b|\brow counts?\b|\brows by table\b|slow(?:est)? quer|\bsparkline"
CARRIER_CLAUSE = r"\bD04-G\d+\b"
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


def clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(CLAUSE_SEP, text) if c.strip()]


def positive(clause: str, pattern: str) -> bool:
    """The pattern occurs in the clause and the clause does not negate it."""
    return bool(re.search(pattern, clause, re.IGNORECASE)) and not re.search(
        NEG, clause, re.IGNORECASE
    )


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
    }
    f["e16d03_boundary"] = (
        "tier health, row counts and maintenance actions stay SCR-142" in t["E16D03"]
    )
    f["e25_rule"] = "hatched = estimated or absent, never a side or direction" in t["E25"]
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
        "ingest_rate": f"{round(facts['ingest_rate_k'] * 1000):,} msg/s",
        "line": f"Ingest {round(facts['ingest_rate_k'] * 1000):,} msg/s · backlog {5 * facts['ilp_batch_rows']:,} rows · lag — (PROPOSED D04-G4)",
    }
    mig = facts["migration_latest"]
    fx["migration"] = {
        "schema_version": mig,
        "target_version": f"{int(mig) + 1:04d}",
        "pending": 1,
        "banner": f"1 pending · {mig} → {int(mig) + 1:04d}",
    }
    fx["health"] = {
        "tiers": facts["health_components"][:3],
        "down_tier": "questdb",
        "since": (gen - dt.timedelta(minutes=7)).strftime("%H:%M:%S") + " UTC",
    }
    # the import fixture: January 2026, 31 days; 12 done on the running frame; 30 processed (29 done, 1 skipped)
    # on the skip frame; the last day fails to download in the summary
    frm, to = dt.date(2026, 1, 1), dt.date(2026, 1, 31)
    n = (to - frm).days + 1
    assert n <= facts["import_days_max"]
    tps = facts["trades_rate_k"] * 1000
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
        "overlap_window_s": 600,
        "overlap_rows": f"{round(tps * 600):,} rows",
        "summary": f"Imported 29 days of BTCUSDT trades · 1 file skipped · 1 file failed · {round(tps * 600):,} overlapping rows discarded",
        "overlap_line": f"{round(tps * 600):,} rows inside recorded windows were discarded — recorded data wins.",
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
    fx["purge"] = {
        "symbol": "ETHUSDT",
        "size": gb(ex["symbols"][1]["used_bytes"]),
        "before": (gen - dt.timedelta(days=tiers["parquet"]["retention_days"])).strftime(
            "%Y-%m-%d"
        ),
        "pinned_symbol": ex["symbols"][0]["symbol"],
    }
    return fx


UNIT_NUM = r"\d[\d,]*(?:\.\d+)?\s?(?:GB|TB|MB)\b"
DATE_RE = r"\b\d{4}-\d{2}-\d{2}\b"
STATE_WORD = r"\b(?:healthy|degraded|warning|down|not deployed|not_deployed)\b"
TIER_FRAMES = ("TIER/questdb", "TIER/parquet", "TIER/postgres")


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


def gates(
    files: list[Path], spec: str, facts: dict[str, Any], fx: dict[str, Any], t: dict[str, str]
) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    all_rows = frame_rows(spec)
    seen: dict[str, int] = {}
    need = required_numbers(fx)
    for name, c, sec in all_rows:
        seen[name] = seen.get(name, 0) + 1
        if len(c) < 6:
            bad.append(f"section {sec}: {name} has fewer than six cells")
            continue
        producer, shows, controls, cls = (
            c[COL["producer"]],
            c[COL["shows"]],
            c[COL["controls"]],
            c[COL["cls"]],
        )
        text = shows + " · " + controls
        low = text.lower()
        cl = clauses(shows) + clauses(controls)
        s = short(name)
        own = owner_of(name, cls)
        # R-2 the sample stamp
        if name.startswith("SCR-142/") and name not in NO_STAMP:
            stamp = [x for x in cl if re.search(r"\bSampled \d\d:\d\d:\d\d UTC", x)]
            if not stamp:
                bad.append(f"R-2 {name}: sample timestamp missing")
            elif name == "SCR-142/stale-sample" and not any(
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

            def starting(prefix: str) -> str | None:
                return next((x for x in cl if x.lower().startswith(prefix)), None)

            size = starting("size ")
            if not size or not re.search(UNIT_NUM, size):
                bad.append(f"R-1 {name}: figure without unit")
            proj = starting("projected full")
            if proj is None:
                bad.append(f"R-1 {name}: projected full missing")
            elif not (
                ("—" in proj and "proposed" in proj.lower())
                or ("—" not in proj and re.search(DATE_RE, proj))
            ):
                bad.append(f"R-1 {name}: projected full not produced and not PROPOSED")
            growth = starting("growth/day")
            if growth is None:
                bad.append(f"R-1 {name}: growth cell missing")
            elif not (
                ("—" in growth and "proposed" in growth.lower())
                or ("—" not in growth and re.search(UNIT_NUM, growth))
            ):
                bad.append(f"R-1 {name}: growth cell not produced and not PROPOSED")
            health = starting("health ")
            if health is None or not re.search(STATE_WORD, health, re.IGNORECASE):
                bad.append(f"R-4 {name}: health by colour alone")
        if name == "SCR-142/tier-unreachable-questdb" and "page usable" not in low:
            bad.append(f"R-4 {s}: page-level error")
        # R-5 the degradation order on every level >= 1 frame
        lv = re.search(r"`level` ([0-3])", producer)
        if lv and int(lv.group(1)) >= 1:
            if any(re.search(p, text, re.IGNORECASE) for p in INVERTED):
                bad.append(f"R-5 {s}: degradation order inverted")
            elif DEGRADATION.lower() not in low:
                bad.append(f"R-5 {s}: degradation sentence missing")
        # per clause: exits (R-14), locks by owner (R-6 / R-8 / R-11), PROPOSED carriers (R-12), console / backup (R-15)
        for x in cl:
            is_exit = bool(re.search(EXIT_RE, x)) or (
                name.startswith(DIALOG_FAMILIES) and bool(re.search(r"\bCancel\b", x))
            )
            if is_exit:
                if positive(x, LOCKISH):
                    bad.append(f"R-14 {s}: exit gated")
            elif own == "R6":
                if positive(x, r"\block\b|\bT2\b"):
                    bad.append(f"R-6 {s}: state drawn as a lock")
                elif name == "SCR-142/migration-pending" and positive(x, r"\bapply\b"):
                    bad.append(f"R-6 {s}: deferred capability drawn as a control")
                elif positive(x, r"\baria-disabled\b|opacity\.disabled"):
                    bad.append(f"R-6 {s}: action gated by state")
            elif own == "R8":
                if positive(x, r"\block\b"):
                    bad.append(f"R-8 {name}: lock on a validity control")
                elif positive(x, r"\bCMP-079\b"):
                    bad.append(f"R-8 {name}: RbacGate on validity")
                elif positive(x, r"\bT2\b"):
                    bad.append(f"R-8 {name}: validity drawn as T2")
            if re.search(CARRIER_CLAUSE, x) or (
                not is_exit and re.search(r"\bcancel\b", x, re.IGNORECASE)
            ):
                if "proposed" not in x.lower():
                    what = (
                        "cancel"
                        if re.search(r"\bcancel\b", x, re.IGNORECASE)
                        else "PROPOSED carrier"
                    )
                    bad.append(f"R-12 {s}: {what} without PROPOSED caption")
            if positive(x, r"\bconsole\b"):
                bad.append(f"R-15 {name}: data-store console linked")
            if positive(x, r"\bbackups?\b|\brestore\b"):
                bad.append(f"R-15 {name}: backup control drawn")
        if re.search(CARRIER_ROW, text, re.IGNORECASE) and "proposed" not in low:
            bad.append(f"R-12 {s}: PROPOSED carrier without caption (row)")
        # R-8 the validity rows
        if own == "R8":
            if "validity-reason" not in low:
                bad.append(f"R-8 {name}: validity frame without validity-reason")
            if "opacity.disabled" not in low:
                bad.append(f"R-8 {name}: validity frame without opacity.disabled")
        # R-11 the strip rows
        if own == "R11":
            locked = "T2" in cls or any(positive(x, r"\block\b|\bT2\b") for x in cl)
            if locked:
                bad.append(
                    f"R-11 {s}: busy drawn as T2"
                    if name == "JOB/strip-running"
                    else f"R-11 {s}: refusal drawn as a lock"
                )
            elif name == "JOB/strip-running":
                if "aria-busy" not in low:
                    bad.append(f"R-11 {s}: busy without aria-busy")
                if "busy" not in cls.lower():
                    bad.append(f"R-11 {s}: class is not busy")
            elif "T4" not in cls:
                bad.append(f"R-11 {s}: refusal not classed T4")
        # R-13 the view-as frame
        if own == "R13":
            if "T2" not in cls:
                bad.append(f"R-13 {s}: not T2")
            if "lock glyph" not in low:
                bad.append(f"R-13 {s}: T2 without lock")
            if "rbac.view_as" not in text:
                bad.append(f"R-13 {s}: reason key missing")
            if "full label" not in low:
                bad.append(f"R-13 {s}: T2 without full label")
            notices = [x for x in cl if re.search(r"\bnotice\b", x, re.IGNORECASE)]
            if len(notices) > 1:
                bad.append(f"R-13 {s}: more than one notice")
            elif not notices:
                bad.append(f"R-13 {s}: no notice")
            if any(positive(x, r"opacity\.disabled|color\.text\.disabled") for x in cl):
                bad.append(f"R-13 {s}: T2 dimmed")
        # R-7 the purge triple
        if name == "PURGE/dialog":
            typed = [x for x in cl if re.search(r"type the symbol to confirm", x, re.IGNORECASE)]
            if not typed:
                bad.append(f"R-7 {name}: typed field missing")
            elif positive(typed[0], r"pre-?filled"):
                bad.append(f"R-7 {name}: confirm_symbol pre-filled")
            elif "empty" not in typed[0].lower():
                bad.append(f"R-7 {name}: typed field not shown empty")
            if not any(x.lower().startswith("reason") for x in cl):
                bad.append(f"R-7 {name}: reason missing")
        if name in ("PURGE/dialog", "PURGE/step-up") and STEPUP not in text:
            bad.append(f"R-7 {name}: elevation not shown")
        # R-9 / R-10 the import
        if name == "IMPORT/running-with-skips":
            if any(positive(x, r"\bbanner\b|\balert\b|\bpage error\b") for x in cl):
                bad.append(f"R-9 {s}: page banner on a skipped file")
            if "keeps moving" not in low:
                bad.append(f"R-9 {s}: progress not continuing")
            if not re.search(r"\bReason\b", shows):
                bad.append(f"R-10 {s}: skip without reason")
        if name == "IMPORT/failed" and any(positive(x, r"\bpage\b") for x in cl):
            bad.append(f"R-9 {name}: failure outside the card")
        if name == "IMPORT/summary":
            if "recorded data wins" not in low:
                bad.append(f"R-10 {name}: overlap report missing")
            if "archive-derived" not in low:
                bad.append(f"R-10 {name}: archive-derived label missing")
            if "no book data" not in low:
                bad.append(f"R-10 {name}: book-data caveat missing")
        # R-17 every number the tool's
        for needle in need.get(name, []):
            if needle not in text:
                kind = "count" if name.startswith("IMPORT/") else "number"
                bad.append(
                    f"R-17 {s if kind == 'count' else name}: {kind} not the tool's ({needle})"
                )
        # R-20 the E16-D02 outcome copy
        if name == "JOB/outcomes" and COMPACT_FAILED not in text:
            bad.append(f"R-20 {name}: E16-D02 copy altered")
        if name == "PURGE/outcomes" and PURGE_FAILED_TAIL not in text:
            bad.append(f"R-20 {name}: E16-D02 copy altered")
        # R-21 the confirm pattern per action
        if name in ("JOB/confirm-compact", "JOB/confirm-vacuum"):
            if "cmp-044 standard" not in low or NOTHING_DELETED not in text:
                bad.append(f"R-21 {s}: non-destructive confirm without the standard form")
            if any(positive(x, r"\btyped\b") for x in cl):
                bad.append(f"R-21 {s}: typed confirm on a non-destructive action")
        if name == "PURGE/dialog" and ("cmp-044 standard" in low or "cmp-044 typed" not in low):
            bad.append(f"R-21 {name}: destructive action without typed confirm")
        # R-22 announcements once
        if name == "JOB/strip-running":
            if any(positive(x, r"per tick") for x in cl):
                bad.append(f"R-22 {s}: announcement per tick")
            elif "once" not in low and "one announcement" not in low:
                bad.append(f"R-22 {s}: no announcement policy")
    for name, n in seen.items():
        if n > 1:
            bad.append(f"spec: frame {name} appears in {n} state rows (one row per frame)")
    # R-18 the inventory: every frame section 0 names is a row; the twins are rows
    s0 = section(spec, 0, 1)
    for named in sorted(set(re.findall(r"`((?:SCR-142|TIER|JOB|PURGE|IMPORT)/[a-z0-9-]+)`", s0))):
        if named not in seen:
            bad.append(f"R-18: frame named in §0 missing from its table ({named})")
    for tw in TWINS:
        if tw not in seen:
            bad.append(f"R-18: light twin {tw} is not a frame row")
    # R-13 the view-as leg first in section 1.3 and section 9
    s1 = section(spec, 1, 2)
    gated = re.findall(
        r"^\| ([^|]+?) +\| \*\*(T2|validity look|busy|T4|status|absence|outcome|T1)\*\*", s1, MULTI
    )
    if not gated or "viewing as" not in gated[0][0] or gated[0][1] != "T2":
        bad.append("R-13 §1.3: view-as leg not first")
    roles = re.findall(r"^\| ((?:Owner|Manager)[^|]*?) +\|", section(spec, 9, 10), MULTI)
    if not roles or "viewing as" not in roles[0]:
        bad.append("R-13 §9: view-as leg not first")
    # R-16 the PENDING siblings by name only
    if re.search(r"#(?:4463|4501)\b[^\n]{0,60}?\b[0-9a-f]{7,40}\b", spec):
        bad.append("R-16: unmerged sibling pinned")
    # R-19 the rbac sentences in the deck; the copy gates
    deck = section(spec, 14, 15)
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        for q in re.findall(r'"([^"]+)"', cell):
            if len(q) > LAYOUT["reason_max"]:
                bad.append(f"R-19 §14: rbac sentence over 60 chars ({key})")
            elif not q.endswith("."):
                bad.append(f"R-19 §14: rbac sentence without a full stop ({key})")
            elif re.search(r"\d|[A-Z]{3,}USDT", q):
                bad.append(f"R-19 §14: reason names data ({key})")
    for want, label in ((DEGRADATION, "the AC 2 sentence"), (NOTICE_D16, "the D-16 notice")):
        if want not in deck:
            bad.append(f"spec section 14: {label} is not in the copy deck")
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
        spec = _first(spec, f"{a} <!-- audit:{key}={a} -->", f"{b} <!-- audit:{key}={b} -->")
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


SH, CT, CL = COL["shows"], COL["controls"], COL["cls"]
# (description, mutation, the expected FAIL — the mutation's ONLY FAIL)
Mutation = tuple[str, Callable[[str], str], str]
MUTATIONS: list[Mutation] = [
    (
        "TIER/questdb: the Size cell's unit removed",
        _sub("TIER/questdb", SH, "Size 640.0 GB", "Size 640.0"),
        "R-1 TIER/questdb: figure without unit",
    ),
    (
        "TIER/parquet: the Projected full clause removed",
        _sub(
            "TIER/parquet",
            SH,
            " · Projected full — (PROPOSED D04-G1, shipped fallback: all tiers 2028-03-27)",
            "",
        ),
        "R-1 TIER/parquet: projected full missing",
    ),
    (
        "TIER/postgres: the Growth cell replaced by n/a without PROPOSED",
        _sub(
            "TIER/postgres",
            SH,
            "Growth/day — (PROPOSED D04-G1, shipped fallback: all tiers 1.45 GB/day)",
            "Growth/day n/a",
        ),
        "R-1 TIER/postgres: growth cell not produced and not PROPOSED",
    ),
    (
        "SCR-142/healthy: the stamp clause removed",
        _sub("SCR-142/healthy", SH, "stamp Sampled 10:31:03 UTC (every 60 s) · ", ""),
        "R-2 SCR-142/healthy: sample timestamp missing",
    ),
    (
        "SCR-142/stale-sample: the stale marker removed",
        _sub("SCR-142/stale-sample", SH, ", stale (3 min old)", ""),
        "R-2 SCR-142/stale-sample: staleness not shown",
    ),
    (
        "SCR-142/healthy: the budget meter's denominator removed",
        _sub("SCR-142/healthy", SH, " of 2,000.0 GB cap_bytes", ""),
        "R-3 SCR-142/healthy: meter without denominator",
    ),
    (
        "SCR-142/healthy: a third meter added",
        _append(
            "SCR-142/healthy", SH, "meter Parquet share: 548.0 GB of 2,000.0 GB cap_bytes (27.4 %)"
        ),
        "R-3 SCR-142/healthy: more than two meters",
    ),
    (
        "TIER/questdb: the Health word removed, the tone kept",
        _sub(
            "TIER/questdb",
            SH,
            "Health healthy, the text word with the ✓ glyph (ComponentState)",
            "Health (tone ok, the ✓ glyph)",
        ),
        "R-4 TIER/questdb: health by colour alone",
    ),
    (
        "SCR-142/tier-unreachable-questdb: the page-usable clause removed",
        _sub("SCR-142/tier-unreachable-questdb", SH, "page usable, ", ""),
        "R-4 tier-unreachable-questdb: page-level error",
    ),
    (
        "SCR-142/low-disk-warning: the AC 2 sentence removed",
        _sub(
            "SCR-142/low-disk-warning",
            SH,
            ' with the AC 2 sentence "Recording pauses before trading is affected." and the detail line of §1.4',
            "",
        ),
        "R-5 low-disk-warning: degradation sentence missing",
    ),
    (
        "SCR-142/read-only-disk-full: the sentence inverted",
        _sub(
            "SCR-142/read-only-disk-full",
            SH,
            "Recording pauses before trading is affected.",
            "Trading pauses before recording is affected.",
        ),
        "R-5 read-only-disk-full: degradation order inverted",
    ),
    (
        "SCR-142/read-only-disk-full: Compact drawn T2 with a lock",
        _append("SCR-142/read-only-disk-full", CT, "Compact Parquet… T2 with a lock"),
        "R-6 read-only-disk-full: state drawn as a lock",
    ),
    (
        "SCR-142/migration-pending: an Apply migrations button added",
        _append("SCR-142/migration-pending", CT, "Apply migrations button"),
        "R-6 migration-pending: deferred capability drawn as a control",
    ),
    (
        "SCR-142/tier-unreachable-questdb: Purge aria-disabled",
        _append(
            "SCR-142/tier-unreachable-questdb",
            CT,
            "Purge data… aria-disabled while QuestDB is down",
        ),
        "R-6 tier-unreachable-questdb: action gated by state",
    ),
    (
        "PURGE/dialog: the typed field pre-filled",
        _sub("PURGE/dialog", SH, "empty, never pre-filled", "pre-filled with ETHUSDT"),
        "R-7 PURGE/dialog: confirm_symbol pre-filled",
    ),
    (
        "PURGE/dialog: the Reason field removed",
        _sub("PURGE/dialog", SH, "Reason (CMP-007, required, 3–280 characters) · ", ""),
        "R-7 PURGE/dialog: reason missing",
    ),
    (
        "PURGE/step-up: the step-up sentence removed",
        _sub(
            "PURGE/step-up",
            SH,
            'the step-up sentence "You\'ll confirm with your password and a code." already in the dialog · ',
            "",
        ),
        "R-7 PURGE/step-up: elevation not shown",
    ),
    (
        "PURGE/dialog-validity: a lock added",
        _append("PURGE/dialog-validity", SH, "a lock glyph before the label"),
        "R-8 PURGE/dialog-validity: lock on a validity control",
    ),
    (
        "IMPORT/form-validity: CMP-079 added",
        _append("IMPORT/form-validity", SH, "wrapped in CMP-079"),
        "R-8 IMPORT/form-validity: RbacGate on validity",
    ),
    (
        "IMPORT/running-with-skips: a page banner added",
        _append("IMPORT/running-with-skips", SH, "a page banner"),
        "R-9 running-with-skips: page banner on a skipped file",
    ),
    (
        "IMPORT/running-with-skips: the bar-keeps-moving clause removed",
        _sub("IMPORT/running-with-skips", SH, "the overall bar keeps moving: ", ""),
        "R-9 running-with-skips: progress not continuing",
    ),
    (
        "IMPORT/failed: the failure drawn as a page banner",
        _sub("IMPORT/failed", SH, "never a page banner", "also as a page banner"),
        "R-9 IMPORT/failed: failure outside the card",
    ),
    (
        "IMPORT/running-with-skips: the Reason column removed",
        _sub(
            "IMPORT/running-with-skips", SH, "Day / Status / Reason / Rows", "Day / Status / Rows"
        ),
        "R-10 running-with-skips: skip without reason",
    ),
    (
        "IMPORT/summary: the overlap report removed",
        _sub(
            "IMPORT/summary",
            SH,
            ' · the overlap report "660,000 rows inside recorded windows were discarded — recorded data wins." (`22` :14089; never "duplicates removed")',
            "",
        ),
        "R-10 IMPORT/summary: overlap report missing",
    ),
    (
        "IMPORT/summary: archive-derived removed from the tag",
        _sub(
            "IMPORT/summary",
            SH,
            "Archive-derived · trades only · no book data",
            "Imported · trades only · no book data",
        ),
        "R-10 IMPORT/summary: archive-derived label missing",
    ),
    (
        "IMPORT/summary: no book data removed from the tag",
        _sub("IMPORT/summary", SH, " · no book data", ""),
        "R-10 IMPORT/summary: book-data caveat missing",
    ),
    (
        "JOB/strip-running: the running Compact drawn T2",
        _append("JOB/strip-running", CT, "Compact Parquet… T2"),
        "R-11 strip-running: busy drawn as T2",
    ),
    (
        "JOB/strip-running: aria-busy removed",
        _sub("JOB/strip-running", CT, "`aria-busy`, ", ""),
        "R-11 strip-running: busy without aria-busy",
    ),
    (
        "JOB/strip-refused-409: the class T4 replaced by T2",
        _sub("JOB/strip-refused-409", CL, "T4", "T2"),
        "R-11 strip-refused-409: refusal drawn as a lock",
    ),
    (
        "JOB/strip-running: PROPOSED removed from the Cancel clause",
        _sub(
            "JOB/strip-running",
            CT,
            "Cancel per job line captioned PROPOSED (D04-G10)",
            "Cancel per job line (D04-G10)",
        ),
        "R-12 strip-running: cancel without PROPOSED caption",
    ),
    (
        "SCR-142/view-as: rbac.view_as removed",
        _sub("SCR-142/view-as", CT, "the reason key `rbac.view_as` ", "the reason key "),
        "R-13 view-as: reason key missing",
    ),
    (
        "SCR-142/view-as: a second notice added",
        _append("SCR-142/view-as", SH, "a second notice under the import card"),
        "R-13 view-as: more than one notice",
    ),
    (
        "SCR-142/view-as: the full label dropped",
        _sub(
            "SCR-142/view-as",
            CT,
            "the full label with the lock glyph leading it",
            "the lock glyph leading the label",
        ),
        "R-13 view-as: T2 without full label",
    ),
    (
        "SCR-142/view-as: opacity.disabled added",
        _append("SCR-142/view-as", CT, "label at opacity.disabled"),
        "R-13 view-as: T2 dimmed",
    ),
    (
        "§1.3: the view-as row moved below the validity row",
        lambda s: _swap_rows(
            s, "| every write while viewing as", "| Import archives while the range is empty"
        ),
        "R-13 §1.3: view-as leg not first",
    ),
    (
        "SCR-142/view-as: the SCR-143 link aria-disabled",
        _sub(
            "SCR-142/view-as",
            CT,
            "links to SCR-140, SCR-141 and SCR-143 enabled (T1)",
            "links to SCR-140, SCR-141 and SCR-143 aria-disabled",
        ),
        "R-14 view-as: exit gated",
    ),
    (
        "SCR-142/read-only-disk-full: Shorten retention drawn T2",
        _sub(
            "SCR-142/read-only-disk-full",
            SH,
            "Reduce depth and Unpin as links (T1)",
            "Reduce depth and Unpin as links T2",
        ),
        "R-14 read-only-disk-full: exit gated",
    ),
    (
        "TIER/questdb: a console link added",
        _append("TIER/questdb", CT, "QuestDB console link"),
        "R-15 TIER/questdb: data-store console linked",
    ),
    (
        "TIER/postgres: a Backup button added",
        _append("TIER/postgres", CT, "Backup now button"),
        "R-15 TIER/postgres: backup control drawn",
    ),
    (
        "the whole file: #4463 pinned at a sha",
        lambda s: _first(s, "boards PR #4463 and", "boards PR #4463 (head 0a1b2c3d4e5f) and"),
        "R-16: unmerged sibling pinned",
    ),
    (
        "SCR-142/healthy: the runway days +1",
        _sub("SCR-142/healthy", SH, "about 560 days", "about 561 days"),
        "R-17 SCR-142/healthy: number not the tool's",
    ),
    (
        "IMPORT/running-with-skips: 29 done -> 28 done",
        _sub("IMPORT/running-with-skips", SH, "29 done", "28 done"),
        "R-17 running-with-skips: count not the tool's",
    ),
    (
        "§0: board 07's count 6 -> 5",
        lambda s: _counts(s, **{"board_frames.07": (6, 5)}),
        "R-18: §0 and §8's table disagree",
    ),
    (
        "IMPORT/failed: the row deleted (its counts updated)",
        lambda s: _counts(
            _row_delete(s, "IMPORT/failed"),
            frames_total=(40, 39),
            frames_import=(6, 5),
            **{"board_frames.07": (6, 5)},
        ),
        "R-18: frame named in §0 missing from its table",
    ),
    (
        "§14: rbac.view_as lengthened past 60",
        lambda s: _deck_edit(
            s, "rbac.view_as", "{user}.", "{user} of this organisation's accounts today."
        ),
        "R-19 §14: rbac sentence over 60 chars",
    ),
    (
        "§14: a symbol added to the view-as sentence",
        lambda s: _deck_edit(s, "rbac.view_as", "{user}.", "{user} BTCUSDT."),
        "R-19 §14: reason names data",
    ),
    (
        "JOB/outcomes: the compact-failed line re-worded",
        _sub(
            "JOB/outcomes", SH, COMPACT_FAILED, "Compaction failed (`<code>`). Nothing was deleted."
        ),
        "R-20 JOB/outcomes: E16-D02 copy altered",
    ),
    (
        "JOB/confirm-compact: a typed field added",
        _append("JOB/confirm-compact", SH, "a typed symbol field"),
        "R-21 confirm-compact: typed confirm on a non-destructive action",
    ),
    (
        "PURGE/dialog: the typed pattern replaced by standard",
        _sub("PURGE/dialog", SH, "CMP-044 typed", "CMP-044 standard"),
        "R-21 PURGE/dialog: destructive action without typed confirm",
    ),
    (
        "JOB/strip-running: an announcement per tick",
        _append("JOB/strip-running", SH, "announced per tick"),
        "R-22 strip-running: announcement per tick",
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
    num = lambda s: float(re.sub(r"[^\d.]", "", s))  # noqa: E731
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
    bad = gates([SPEC, *extra], spec, facts, fx, t)
    numbers, matrix, missing, fails = numbers_of(spec, facts, fx, themes, registered)
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
    sigs = list(signatures.values())
    dup = sorted({s for s in sigs if sigs.count(s) > 1})
    if dup:
        ok = False
        out.append("duplicate FAIL messages: " + " | ".join(dup))
    same = hashlib.sha256(SPEC.read_bytes()).hexdigest() == before
    ok = ok and same
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(set(sigs))} distinct FAIL messages, each its mutation's only FAIL; the unmutated spec "
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
        clean = not any(b.startswith("marker") or b.startswith("R-18: §0") for b in bad)
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
