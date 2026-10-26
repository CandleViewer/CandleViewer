#!/usr/bin/env python3
"""E16-D03 SCR-141 retention policy editor audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the merged upstream specs and the spec AS TEXT and
prints: (1) the WCAG 2.x ratio of every fg / bg pair SCR-141 renders in dark / light / high-contrast
(`themes.json` layering) and the validity composite; (2) every token the spec binds, resolved or
MISSING; (3) the contract facts the boards quote, parsed from `22` / `21` / `24` text (the eight stream
kinds, the four actions, the five job states, the 1..3650 bounds, the seed numbers, the 03:00 UTC
sentence, the storage example the fixture derives from); (4) the copy gates (the `14` validation
sentence byte-for-byte, every T2 reason within 60 characters naming no data, no jargon in user copy,
no private path or host, every cited id and line still valid); (5) the per-frame gates (every
reduction frame carries its consequence sentence, every destructive frame its typed instruction, a timing
clause and the undo line, every reduction kind its title / body / typed value, every T2 frame its lock,
every validity-look frame its reason and no lock, the view-as row first, the absences named); (6) the
counts the spec, the boards and the PR body quote. The fixture is derived from the `22` storage example
by the contract's own semantics: a reduction is a shorter TOTAL horizon (`21` `read_policy_row`), the
fallback size is per symbol across its streams and its range is clamped to the recorded history.
Whether a frame or a kind is a reduction is derived from its before / after horizons (DIFF_TABLE:
total = the days for `drop`, max(the days, the `21` section 7 total) for `archive_parquet`), never
from the frame's own Class cell, which must agree. `--json` feeds the check-nums script; `--check`
re-derives the spec's `audit:` markers. The mutation modes change the spec in memory and pass only
when exactly the FAIL they target results: `--mutate-consequence` removes the consequence sentence
from one reduction frame, `--mutate-kinds` the undo line from one reduction-kind row,
`--mutate-typed` the quoted typed-field label from the first destructive confirm, `--mutate-plain`
turns the `drop` -> `archive_parquet` kind into a plain confirm, `--mutate-title` gives K7 K6's title,
`--mutate-nothing` adds "Nothing is deleted." to K6's body, `--mutate-producer` writes the plain mark
into the kinds frame's Producer cell, `--mutate-applynow` removes the Apply-now qualifier from the
lengthening confirm's copy row. Exit 1 on a gated FAIL.

Usage: python3 -I docs/design/_tools/e16_d03_retention_audit.py [--json] [--check]
  [--mutate-consequence | --mutate-kinds | --mutate-typed | --mutate-plain | --mutate-title
   | --mutate-nothing | --mutate-producer | --mutate-applynow] [--extra F]
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E16" / "E16-D03.md"
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
)
# Jargon the copy deck (section 14) never shows a user; checked on the deck's String column only.
BANNED_COPY = (
    r"client-side",
    r"server-side",
    r"\bbackend\b",
    r"\bendpoint\b",
    r"\b422\b",
    r"\b409\b",
)
# `14` :2769, byte-for-byte (the derived-stream rule in product terms).
SENTENCE_14 = "Bars can't be deleted before the ticks they came from are kept — adjust the tiers."
# `24` :3866, the daily job; `22` :5239, the exemption; both quoted in the spec.
SENTENCE_24 = "Daily retention job (03:00 UTC)"
SENTENCE_22_EXEMPT = "pinned symbols are exempt"
VIEW_AS = "Read-only while viewing as {user}."
# The undo line every destructive confirm ends with (spec section 5; E16-D02 :506).
UNDO = "It cannot be undone. Replay, footprint history and the journal lose the deleted days."
# The two timing clauses (BQ-8 / BQ-10 RULED): one of them in every destructive frame.
TIMING = ("at the next retention run (daily, 03:00 UTC)", "a retention sweep starts now")
# The typed field's label as the spec quotes it: the closing quote right after "confirm" tells it
# apart from the Apply control's validity reason "Type trades to confirm." (same words, a full stop).
TYPED_LABEL = '"Type trades to confirm"'
# A confirm that names the plain variant is never a reduction's confirm.
PLAIN_MARKS = ("CMP-044 standard", "plain confirm")
# The worked example's typed constants beside the contract-derived ones (spec header): the lowered drop
# window of kind K2, the per-symbol override days of F3 / K3 / K4, the running job's progress, the
# long-window days of K6 / K7 and the hot window above the section 7 total that `{total}` must print.
EXAMPLE = {
    "reduce_to": 7,
    "lengthen_to": 90,
    "drop_lower_to": 3,
    "override_days": 14,
    "progress_pct": 42,
    "long_days": 1000,
    "long_hot_days": 800,
}
# The absences (deferred capabilities drawn as absent, never as a lock): `22` :5242–5243.
ABSENCES = ("downsample", "pin", "applies_to_pinned")
ABSENT_FIELDS = ("downsample_to", "max_disk_gb", "archive_path", "enabled")
# element | fg | bg | role — every pair SCR-141 draws (spec section 15, rows in order).
PAIRS_TABLE = """
dialog body, grid cell words on the dialog | color.text.primary | color.surface.overlay | text
labels, help, validity reasons, job line on the dialog | color.text.secondary | color.surface.overlay | text
T2 label and lock on the T2 fill | color.text.tertiary | color.surface.raised | text
T2 reason, baseline chip, exempt caption on raised | color.text.secondary | color.surface.raised | text
grid cell words on the zebra row | color.text.primary | color.surface.raised | text
grid cell words on canvas rows | color.text.primary | color.surface.canvas | text
grid header words | color.text.secondary | color.surface.sunken | text
field value in the well | color.text.primary | color.surface.app | text
field well boundary | color.text.tertiary | color.surface.app | non-text
invalid well boundary on the dialog | color.status.danger.default | color.surface.overlay | non-text
error line words | color.text.primary | color.surface.overlay | text
error line glyph | color.status.danger.strong | color.surface.overlay | non-text
Apply label on the primary fill | color.text.on-action | color.action.primary.default | text
destructive Apply label on the danger fill | color.text.on-action | color.status.danger.default | text
rule banner words | color.text.primary | color.status.info.subtle | text
rule banner glyph | color.status.info.strong | color.status.info.subtle | non-text
no-other-source warning words | color.text.primary | color.status.warning.subtle | text
no-other-source warning glyph | color.status.warning.strong | color.status.warning.subtle | non-text
job succeeded words | color.text.primary | color.status.success.subtle | text
job succeeded glyph | color.status.success.strong | color.status.success.subtle | non-text
job failed words | color.text.primary | color.status.danger.subtle | text
job failed glyph | color.status.danger.strong | color.status.danger.subtle | non-text
exempt pin glyph on raised | color.text.secondary | color.surface.raised | non-text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
progress bar fill on its track | color.action.primary.default | color.surface.sunken | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.hover",
    "color.surface.admin-tint",
    "color.border.default",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.danger.subtle",
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.action.primary.default",
    "color.focus.ring",
    "opacity.disabled",
    "radius.card",
    "radius.dialog",
    "radius.control",
    "radius.badge",
    "elevation.card",
    "elevation.dialog",
    "space.inset.lg",
    "space.inset.sm",
    "space.inset.xs",
    "space.dialog.padding",
    "space.stack.xs",
    "space.stack.md",
    "space.stack.lg",
    "type.ui.heading-lg",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.body-strong",
    "type.ui.label",
    "type.ui.caption",
    "type.num.sm",
    "type.num.base",
    "size.row.comfortable",
    "size.control.height",
    "size.icon.sm",
    "motion.duration.normal",
    "motion.easing.decelerate",
)
# doc | line at the base | text the line must hold. A `14` line may sit lower by the pointer line.
CITED_TABLE = """
14 | 85 | **RBAC denies server-side; the UI presents.**
14 | 2766 | ### SCR-141 — Admin: retention policy editor
14 | 2768 | cold-tier migration age (QuestDB → Parquet), pin overrides
14 | 2769 | retention ≥1 day; raw-tick retention ≤ bar retention
14 | 2770 | CMP-008 NumericStepperInput, CMP-040 FormField, CMP-044 ConfirmDialog, CMP-065 FormSection, CMP-087 AdminLayout, CMP-093 AuditActionTrigger.
14 | 2772 | every duration field states its unit
14 | 2773 | the screen shows the job's queued/running/complete state
14 | 2774 | `retention.default_changed` `{before, after}`
14 | 2775 | the 'this will delete N GB covering dates X-Y' warning before applying a reduction
22 | 710 | - code: retention_invalid_policy
22 | 1069 | - recording:write
22 | 4944 | operationId: updateRecordedSymbol
22 | 5019 | operationId: pinRecordedSymbol
22 | 5131 | operationId: getStorageUsage
22 | 5189 | operationId: listRetentionPolicies
22 | 5235 | operationId: setRetentionPolicies
22 | 5239 | (per-symbol beats global); pinned symbols are exempt.
22 | 5242 | `downsample`, `pin` and `applies_to_pinned: true` are `422 retention_invalid_policy` until
22 | 5243 | the store holds their fields, as is a set where a stream derived from `trades` outlives it;
22 | 5246 | starts one `retention_sweep` job: `409 job_running` while one is queued or running, and
22 | 5247 | `409 conflict` while the retention scheduler is off (`CV_RETENTION_ENABLED`). A refused
22 | 5249 | Audited as `retention.change` (the set before and after), written before the new set is
22 | 5256 | - name: apply_now
22 | 282 | answers `403 view_as_read_only` and changes nothing.
22 | 11767 | (ADR-0004), so a restart loses every
22 | 14333 | operationId: purgeRecordedData
22 | 16587 | StreamKind:
22 | 16603 | RetentionAction:
22 | 18382 | RetentionPolicyInput:
22 | 18387 | retain_days: { type: integer, minimum: 1, maximum: 3650 }
22 | 18395 | RetentionPolicy:
22 | 21105 | status: { type: string, enum: [queued, running, succeeded, failed, cancelled] }
21 | 2899 | market data is mainnet even for demo trading
21 | 2905 | retention_days    integer,                              -- NULL → use retention_policies default
21 | 2974 | #### 3.6.3 `retention_policies`
21 | 3003 | Resolution order for a (symbol, stream): pinned symbol → infinite retention
21 | 3005 | `retain_days` reads by `action`, through one mapping (`read_policy_row`)
21 | 3005 | the total horizon stays the stream's §7 total, never shorter than the hot window
21 | 4506 | a `retention_purge` audit entry records symbol, stream, range and row count
21 | 4520 | | `trades`                              | 30 d
21 | 4521 | | `orderbook_deltas`                    | 7 d
21 | 4525 | Irreplaceable (no REST history)
21 | 4529 | Rebuildable from `trades` while trades exist
21 | 4535 | | **Pinned symbol (any stream)**
24 | 3854 | class RetentionRule(BaseModel):
24 | 3866 | Daily retention job (03:00 UTC): move hot→cold past `hot_days`
04 | 368 | A Manager (not the Owner) changes global retention policy
04 | 926 | | SR-099 | Retention jobs MUST honour pins, run dry-run-first with a report
04 | 1139 | | `recording:write`                                  |  ✔(step-up for purge/retention)
04 | 1185 | Pin a recording / change retention (add, update: with `pinned` or `retention_days`)
11 | 4146 | Then it reports exactly what would be deleted, by symbol, range and size, before anything is removed
11 | 4895 | Then a preview of the impact is shown and typed confirmation is required
12 | 111 | | R-340 | `/admin/recorder` | Recorder & retention config
13 | 440 | **Screens:** SCR-140, SCR-141, SCR-142, SCR-100, SCR-103, SCR-047
20 | 896 | | `CV_RECORDER_RETENTION_DAYS`     | int    | `30`
15 | 119 | ### CMP-008 NumericStepperInput
15 | 433 | ### CMP-040 FormField
15 | 473 | ### CMP-044 ConfirmDialog
15 | 671 | ### CMP-065 FormSection
15 | 811 | ### CMP-079 RbacGate (disabled-with-reason wrapper)
15 | 884 | ### CMP-087 AdminLayout (RBAC-gated shell)
15 | 940 | ### CMP-093 AuditActionTrigger
05 | 90 | ### 3.4 Focus management in dense layouts
05 | 144 | ### 6.2 Layer 2 — ARIA live regions for streaming updates
E09 | 39 | Has the **server** just refused this control's action or route
E09 | 49 | **T2 Disabled with a visible reason (D4).**
E09 | 72 | Recorder setting (i): retention policy on SCR-140
E09 | 85 | Every T2 reason is one of these seven keys, or a key of a registered **state** vocabulary
E09 | 95 | | `rbac.view_as`           | "Read-only while viewing as {user}."
E09 | 108 | `recording:write` → "change recording"
E09 | 224 | ### 9.1 `aria-disabled` versus `disabled`, and focusability
E09 | 230 | a control disabled by **form validity**
E09 | 238 | ### 9.3 Keys on a T2 control
E30D02 | 128 | disabled = `opacity.disabled` on the control with the reason as full-opacity text under it, never inside it
E30D03 | 102 | every destructive-class button names its object
E30D04 | 1048 | ## 30. Gaps (G-rows). Shared sentence for every `22` / `23` gap
E25 | 334 | **"Hollow, dashed or hatched = estimated or absent, never a side or direction."**
E16D02 | 29 | Managers do not get `recording:write` in the design
E16D02 | 74 | [ Retention policy ] [ Storage details ] [ Compact now ] [ Purge data… ]
E16D02 | 380 | ### 6.4 Retention and Keep forever
E16D02 | 395 | so about 13.5 GB recorded before 2026-09-20 becomes eligible for deletion at the next retention run
E16D02 | 397 | "Custom…" opens SCR-141, E16-D03
E16D02 | 404 | ### 6.5 Purge data (per symbol; Owner + step-up + typed symbol + reason)
E16D02 | 444 | ## 7. Roles
E16D02 | 486 | ### 8.3 Disk card (keyed on `level`)
E16D02 | 506 | Destructive confirmations always state what is deleted, how much, and that it cannot be undone.
E16D02 | 508 | ### 8.5 T2 reasons (PROPOSED state keys `recorder.*`; owner: this spec)
E16D02 | 639 | ### 10.5 Disabled with a visible reason (T2; E09-D09 §2.2, §3.1, §9.1–§9.3; CMP-079, CMP-019)
E16D02 | 742 | **C-5:** no purge preview (US-REC-003 "prune preview") exists
E16D02 | 750 | **D-3 (audit vocabulary):**
E16D02 | 760 | **D-8 (owner decision):**
E16D02 | 769 | **D-12 (shell):**
E16D02 | 771 | **D-13 (SCR-141/142):**
E16D02 | 777 | **D-15 (2b in the grid):**
E16D02 | 778 | **D-16 (the view-as notice):**
E16D01 | 222 | "Older data was removed by the retention policy (<N> days)."
"""
POINTER = "E16-D03.md](../design/E16/E16-D03.md)"
DOC_NAMES = (
    "04-security-program.md",
    "05-accessibility-standard.md",
    "11-user-stories.md",
    "12-sitemap.md",
    "13-user-flows.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "20-architecture.md",
    "21-database-schema.md",
    "22-api-openapi.yaml",
    "24-internal-schemas.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
DOCS.update(
    {
        "E09": DESIGN / "E09" / "E09-D09.md",
        "E30D02": DESIGN / "E30" / "E30-D02.md",
        "E30D03": DESIGN / "E30" / "E30-D03.md",
        "E30D04": DESIGN / "E30" / "E30-D04.md",
        "E25": DESIGN / "E25" / "E25-D01.md",
        "E16D02": DESIGN / "E16" / "E16-D02.md",
        "E16D01": DESIGN / "research" / "e16-recorder-mental-model.md",
    }
)
# The eight `22` stream kinds in order, with the `21` section 7 table name each reads its seed from.
STREAM_TABLE = (
    ("trades", "trades"),
    ("orderbook_delta", "orderbook_deltas"),
    ("orderbook_snapshot", "orderbook_snapshots"),
    ("tickers", "tickers"),
    ("klines", "klines"),
    ("liquidations", "liquidations"),
    ("open_interest", "open_interest"),
    ("funding", "funding_rates"),
)
# frame or kind | stage | before | after — each side "stream days action", pairs joined by ";". The
# numbers are fixture keys ({seed_*} the `21` section 7 seed, {example_days} `22`'s override row, the
# rest EXAMPLE). A side's total horizon is its days for `drop` and max(its days, the section 7 total)
# for `archive_parquet` (`21` :3005); a change is a reduction when any pair's total shrinks.
# `SCR-141/confirm-kinds` stands for every K row.
DIFF_TABLE = """
SCR-141/editing-dirty-lengthen | edit | trades {seed_trades} archive_parquet | trades {lengthen_to} archive_parquet
SCR-141/editing-dirty-tiering | edit | trades {seed_trades} archive_parquet | trades {reduce_to} archive_parquet
SCR-141/editing-dirty-reduce | edit | trades {seed_trades} archive_parquet | trades {reduce_to} drop
SCR-141/preview | preview | trades {seed_trades} archive_parquet | trades {reduce_to} drop
SCR-141/confirm-reduce | confirm | trades {seed_trades} archive_parquet | trades {reduce_to} drop
SCR-141/confirm-reduce-now | confirm | trades {seed_trades} archive_parquet | trades {reduce_to} drop
SCR-141/confirm-kinds | confirm | kinds | kinds
SCR-141/confirm-lengthen | confirm | trades {seed_trades} archive_parquet | trades {lengthen_to} archive_parquet
SCR-141/row-removed | edit | orderbook_delta {example_days} drop | orderbook_delta {seed_orderbook_delta} archive_parquet
K1 | confirm | trades {seed_trades} archive_parquet | trades {reduce_to} drop
K2 | confirm | trades {reduce_to} drop | trades {drop_lower_to} drop
K3 | confirm | trades {seed_trades} archive_parquet | trades {override_days} drop
K4 | confirm | trades {override_days} archive_parquet | trades {reduce_to} drop
K5 | confirm | trades {seed_trades} archive_parquet; orderbook_snapshot {seed_orderbook_snapshot} archive_parquet | trades {reduce_to} drop; orderbook_snapshot {reduce_to} drop
K6 | confirm | trades {long_days} drop | trades {seed_trades} archive_parquet
K7 | confirm | trades {long_days} archive_parquet | trades {seed_trades} archive_parquet
"""
# The one layout fixture of the spec (section 2): the dialog and the reflow viewport, in px.
LAYOUT = {"dialog_w": 960, "dialog_max_h_vh": 85, "vp_w": 1280, "vp_h": 800, "zoom_pct": 200}
LAYOUT.update({"row_px": 32, "nav_px": 240, "poll_s": 2, "reason_max": 60, "regions": 5})
# mutation mode | the FAIL text it must produce, exactly once
MUTATIONS = {
    "consequence": "lacks its consequence sentence",
    "kinds": "lacks the undo line",
    "typed": "lacks the typed field",
    "plain": "takes no typed confirm",
    "title": "share a title",
    "nothing": "says Nothing is deleted",
    "producer": "names the plain confirm",
    "applynow": "lacks the Apply-now qualifier",
}
# "Nothing is deleted." on the lengthening confirm holds only while Apply now is unticked (`22`
# :5246: a run started now still deletes what the current rules make eligible).
APPLY_NOW_QUALIFIER = "true only while Apply now is unticked — with it ticked the body is"
# frame | the derived strings its Shows cell must carry (the drawn sizes, gated where they are drawn)
FRAME_SENTENCES = {
    "SCR-141/preview": ("preview_row", "preview_total"),
    "SCR-141/estimate": ("estimate",),
    "SCR-141/confirm-lengthen": ("lengthen_body",),
    "SCR-141/pinned-list": ("pinned_row",),
}
# section | pattern — the counted frame rows per spec section (start, end, regex).
COUNTS = (
    ("frames_states", 4, 5, r"^\| `SCR-141/"),
    ("frames_confirm", 5, 6, r"^\| `SCR-141/"),
    ("row_kinds", 6, 7, r"^\| `SCR-141/row-"),
    ("validation_frames", 7, 8, r"^\| `SCR-141/"),
    ("footer_frames", 8, 9, r"^\| `SCR-141/footer-"),
    ("estimate_frames", 9, 10, r"^\| `SCR-141/"),
    ("redline_frames", 11, 12, r"^\| `SCR-141/"),
    ("boards", 0, 1, r"^\| \d\d +\| `"),
    ("light_twins", 0, 1, r"^\| \d\d +\| `[^`]+-light`"),
    ("flows", 17, 18, r"^\| F\d "),
)
ROW_IDS = (("c_rows", "C"), ("g_rows", "G"), ("a_rows", "A"), ("q_rows", "Q"))
REASON_RE = r"^\| `((?:rbac|recorder)\.[a-z_.]+)` +\| ([^|]+?) +\|"
FRAME_RE = r"^\| `(SCR-141/[a-z0-9-]+)` +\|.*$"
# Cite rule: the needle must occur exactly once in its file. Once, at the cited line (or the cited
# line plus the PR's pointer shift for `14`): OK. Once, elsewhere: WARN naming the current line
# (drift at any distance; re-pin at the next text touch). Not at all: FAIL "cited text gone".
# More than once: FAIL "cited text ambiguous" (lengthen the needle; do not re-pin).
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


def gb(n: float) -> float:
    return round(n / 1e9, 1)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def contract_facts(t: dict[str, str]) -> dict[str, Any]:
    """Every fact a board quotes, parsed from the plan text; nothing is executed."""
    api, db, d24 = t["22"], t["21"], t["24"]
    kinds = api[api.index("    StreamKind:") : api.index("    RetentionAction:")]
    actions = api[api.index("    RetentionAction:") :]
    actions = actions[: actions.index("\n", actions.index("enum:"))]
    rp_in = api[api.index("    RetentionPolicyInput:") : api.index("    RetentionPolicy:")]
    put = api[api.index("operationId: setRetentionPolicies") : api.index("  /recording/sessions:")]
    put = " ".join(put.split())  # the description wraps; sentences are checked on one line
    lst = api[
        api.index("operationId: listRetentionPolicies") : api.index(
            "operationId: setRetentionPolicies"
        )
    ]
    usage = api[
        api.index("operationId: getStorageUsage") : api.index("  /recording/retention-policies:")
    ]
    job = api[api.index("    Job:\n") :]
    job = job[: job.index("        progress_pct:")]
    matrix = db[db.index("## 7. Retention policy matrix") :]
    seed: dict[str, int] = {}
    total: dict[str, str] = {}
    for kind, table in STREAM_TABLE:
        row = first(rf"^\| `{table}` +\|([^\n]*)$", matrix, MULTI)
        parts = [c.strip() for c in row.split("|")]
        seed[kind] = int(first(r"^(\d+) d$", parts[0]))
        total[kind] = parts[2]
    example_rows = re.findall(
        r"stream: (\w+),\s+retain_days: (\d+),\s+action: (\w+),\s+symbol: (\w+),", lst
    )
    sym_rows = re.findall(
        r"symbol: (\w+),\s+used_bytes: (\d+),\s+daily_growth_bytes: (\d+),\s+pinned: (\w+),", usage
    )
    tiers = re.findall(r"\{ tier: (\w+), used_bytes: (\d+), retention_days: (\w+) \}", usage)
    out: dict[str, Any] = {
        "stream_kinds": re.findall(r"^\s+(\w+),$", kinds, MULTI),
        "retention_actions": re.findall(r"\b(drop|archive_parquet|downsample|pin)\b", actions),
        "job_status": first(r"status: \{ type: string, enum: \[([^\]]+)\] \}", job).split(", "),
        "retain_min": int(first(r"minimum: (\d+)", rp_in)),
        "retain_max": int(first(r"maximum: (\d+)", rp_in)),
        "symbol_null_is_global": "Null = global default." in rp_in,
        "applies_to_pinned_default": first(
            r"applies_to_pinned: \{ type: boolean, default: (\w+) \}", rp_in
        ),
        "input_fields": re.findall(r"^        (\w+):", rp_in, MULTI),
        "put_sentences": {
            "whole_set": "Replaces the whole set in one transaction." in put,
            "most_specific_first": "most-specific-first" in put,
            "exempt": SENTENCE_22_EXEMPT in put,
            "retain_days_by_action": "for `drop` the total horizon" in put,
            "deferred_422": "`downsample`, `pin` and `applies_to_pinned: true` are `422 retention_invalid_policy`"
            in put,
            "derived_422": "a stream derived from `trades` outlives it" in put,
            "unknown_field_422": "an unknown field is `422 validation_failed`" in put,
            "step_up": "Always needs the `recorder` step-up (`403 step_up_required`)" in put,
            "nightly": "Changes apply at the next nightly sweep" in put,
            "apply_now": "`apply_now=true` also" in put and "name: apply_now" in put,
            "job_running": "`409 job_running` while one is queued or running" in put,
            "scheduler_off": "`409 conflict` while the retention scheduler is off (`CV_RETENTION_ENABLED`)"
            in put,
            "refused_stores_nothing": "A refused request stores nothing." in put,
            "audit": "Audited as `retention.change` (the set before and after), written before the new set is"
            in put,
            "audit_unavailable": "`503 audit_unavailable` and nothing changes" in put,
            "rbac": "x-rbac: { permissions: [recording:write], scope: none }" in put,
        },
        "example_rows": [[s, int(d), a, sym] for s, d, a, sym in example_rows],
        "storage_example": {
            "generated_at": first(r'generated_at: "([^"]+)"', usage),
            "cap_bytes": int(first(r"cap_bytes: (\d+)", usage)),
            "daily_growth_bytes": int(first(r"^\s+daily_growth_bytes: (\d+)$", usage, MULTI)),
            "tiers": {tier: int(b) for tier, b, _ in tiers},
            "symbols": {
                s: {"used_bytes": int(u), "daily_growth_bytes": int(g), "pinned": p == "true"}
                for s, u, g, p in sym_rows
            },
        },
        "seed": seed,
        "total_horizon": total,
        "resolution_order": "pinned symbol → infinite retention; else symbol-scoped policy; else default policy; else the §7 per-stream default"
        in db,
        "read_policy_row": "`read_policy_row`" in db,
        "archive_total_floor": "the total horizon stays the stream's §7 total, never shorter than the hot window"
        in db,
        "mainnet_comment": "market data is mainnet even for demo trading" in db,
        "purge_audit_21": "a `retention_purge` audit entry records symbol, stream, range and row count"
        in db,
        "pinned_overrides_all": "Overrides everything above" in matrix,
        "daily_job_24": SENTENCE_24 in d24,
        "never_delete_referenced": "never delete a period referenced by an unexported journal trade, a saved replay session or an open investigation"
        in d24,
        "deletion_audit_24": "Every deletion writes an audit entry with symbol, stream, range and freed bytes"
        in d24,
        "manager_recording_write_22": bool(
            re.search(r"  manager:\n(?:    - [\w:*]+\n)*?    - recording:write\n", api)
        ),
        "manager_recording_write_04": "✔(step-up for purge/retention)           |        ✖"
        in t["04"],
        "s19_owner_only": "Retention-policy mutation is Owner-only" in t["04"],
        "sr_099": "Retention jobs MUST honour pins, run dry-run-first with a report, and audit every deletion (symbol, range, byte count)."
        in t["04"],
        "sentence_14_present": SENTENCE_14 in t["14"],
        "checklist_boxes_14": len(
            re.findall(
                r"\[ \]",
                first(
                    r"^(- \*\*Design sign-off acceptance checklist:\*\*[^\n]*)$",
                    t["14"][t["14"].index("### SCR-141") : t["14"].index("### SCR-142")],
                    MULTI,
                ),
            )
        ),
        "us_rec_003_dry_run": "reports exactly what would be deleted, by symbol, range and size, before anything is removed"
        in t["11"],
        "us_admin_006_typed": "a preview of the impact is shown and typed confirmation is required"
        in t["11"],
        "zero_counts": {
            "22:retention-policies/preview": api.count("retention-policies/preview"),
            "22:dry_run": api.count("dry_run"),
            "22:next_sweep_at": api.count("next_sweep_at"),
            "22:last_sweep_at": api.count("last_sweep_at"),
            "22:retention_enabled_field": api.count("retention_enabled"),
            "20:CV_RETENTION_ENABLED": t["20"].count("CV_RETENTION_ENABLED"),
            "22:RetentionSweepResult": api.count("RetentionSweepResult"),
        },
    }
    return out


def months_before(day: dt.datetime, months: int) -> dt.datetime:
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    return day.replace(year=y, month=m + 1)


def fixture(facts: dict[str, Any]) -> dict[str, Any]:
    """The spec's worked examples, derived from the `22` storage example and the `21` section 7 seed.

    The reduction is the ticket's trades 30 -> 7 days WITH the action set to `drop`: under `22`
    :5239-5241 a lowered `retain_days` on an `archive_parquet` row only moves days to Parquet sooner
    (a tiering change) while its hot window stays at or under the section 7 total. The fallback size is `used_bytes` per
    symbol across all its streams; its range is clamped to the recorded history (start =
    generated_at - used_bytes / daily_growth_bytes), and when nothing predates the cut-off the
    sentence says so. The long-window example (EXAMPLE long_days) is the total that falls to the
    section 7 total when its row becomes Move to Parquet after the seed days; with a hot window above
    the section 7 total (EXAMPLE long_hot_days) the total is that hot window.
    """
    ex = facts["storage_example"]
    seed = facts["seed"]
    total = facts["total_horizon"]
    syms = ex["symbols"]
    gen_dt = dt.datetime.fromisoformat(str(ex["generated_at"]).replace("Z", "+00:00"))
    gen = gen_dt.date()
    reduce_from, reduce_to = int(seed["trades"]), EXAMPLE["reduce_to"]
    days_removed = reduce_from - reduce_to
    nonpinned = {s: v for s, v in syms.items() if not v["pinned"]}
    pinned = {s: v for s, v in syms.items() if v["pinned"]}
    cutoff = gen_dt - dt.timedelta(days=reduce_to)
    total_months = int(first(r"^(\d+) mo$", str(total["trades"])))
    total_cutoff = months_before(gen_dt, total_months)
    held = {s: v["used_bytes"] / v["daily_growth_bytes"] for s, v in nonpinned.items()}
    since = {s: gen_dt - dt.timedelta(days=d) for s, d in held.items()}

    def eligible(cut: dt.datetime) -> float:
        return float(
            sum(
                max(0.0, (cut - since[s]).total_seconds() / 86400) * v["daily_growth_bytes"]
                for s, v in nonpinned.items()
            )
        )

    growth_np = sum(v["daily_growth_bytes"] for v in nonpinned.values())
    longest = max(int(d) for d in seed.values())
    steady = growth_np * longest
    cap = int(ex["cap_bytes"])
    tiers = ex["tiers"]
    used = int(tiers["questdb"]) + int(tiers["parquet"])
    pinned_growth = sum(v["daily_growth_bytes"] for v in pinned.values())
    out: dict[str, Any] = {
        "generated_at": gen.isoformat(),
        "reduce_from": reduce_from,
        "reduce_to": reduce_to,
        "reduce_action": "archive_parquet -> drop",
        "days_removed": days_removed,
        "cutoff": cutoff.date().isoformat(),
        "recorded_since": min(since.values()).date().isoformat(),
        "days_held": round(max(held.values()), 1),
        "predates_cutoff": any(since[s] <= cutoff for s in nonpinned),
        "eligible_now_gb": gb(eligible(cutoff)),
        "total_months": total_months,
        "total_cutoff": total_cutoff.date().isoformat(),
        "predates_total_cutoff": any(since[s] <= total_cutoff for s in nonpinned),
        "eligible_total_gb": gb(eligible(total_cutoff)),
        "affected_symbols": len(nonpinned),
        "affected_symbol": ",".join(sorted(nonpinned)),
        "pinned_symbol": ",".join(sorted(pinned)),
        "pinned_gb": gb(sum(v["used_bytes"] for v in pinned.values())),
        "pinned_growth_mb": round(pinned_growth / 1e6),
        "nonpinned_gb": gb(sum(v["used_bytes"] for v in nonpinned.values())),
        "nonpinned_growth_mb": round(growth_np / 1e6),
        "longest_days": longest,
        "steady_gb": gb(steady),
        "steady_pct": round(steady / cap * 100),
        "cap_gb": round(cap / 1e9),
        "used_gb": round(used / 1e9),
        "used_pct": round(used / cap * 100),
        "override": next(r for r in facts["example_rows"] if r[3] != "null"),
        "example_rows": len(facts["example_rows"]),
    }
    out.update({k: v for k, v in EXAMPLE.items() if k != "reduce_to"})
    return out


def size_clause(fx: dict[str, Any], cut: str, predates: bool, size_gb: str) -> str:
    sym, since = fx["affected_symbol"], fx["recorded_since"]
    if predates:
        return (
            f"About {size_gb} GB across {sym}'s recorded streams, recorded from {since} to {cut}, "
            "goes at the first run."
        )
    return (
        f"Nothing recorded before {cut} exists yet (about {size_gb} GB now; recording started "
        f"about {since}), so the first run deletes nothing."
    )


def sentences(fx: dict[str, Any]) -> dict[str, str]:
    """The consequence sentences every reduction frame carries (BQ-10 RULED), from the fixture."""
    n, sym, m = fx["reduce_to"], fx["affected_symbol"], fx["total_months"]
    size_gb = f"{float(str(fx['eligible_now_gb'])):g}"
    total_gb = f"{float(str(fx['eligible_total_gb'])):g}"
    size = size_clause(fx, fx["cutoff"], fx["predates_cutoff"], size_gb)
    size_total = size_clause(fx, fx["total_cutoff"], fx["predates_total_cutoff"], total_gb)
    if fx["predates_cutoff"]:
        size_now = size.replace("goes at the first run", "goes in this sweep")
        row = f"{sym} · Trades · {fx['recorded_since']} · {fx['cutoff']} · about {size_gb} GB"
        total = f"About {size_gb} GB across {fx['affected_symbols']} symbol"
    else:
        size_now = size.replace("the first run deletes nothing", "this sweep deletes nothing")
        since = fx["recorded_since"]
        row = f"{sym} · Trades · — · — · about {size_gb} GB now (recorded since about {since})"
        total = f"About {size_gb} GB now across {fx['affected_symbols']} symbol"
    lead = f"Trades for {sym} older than {n} days"
    every = "and at every run after it, Parquet included."
    title_total = f"Shorten trades retention to {m} months?"
    move = "Move trades to Parquet and shorten retention to"
    hot = int(fx["long_hot_days"])
    # `{total}` = max(the hot window, the section 7 total): days when the hot window is the larger
    long_words = f"{hot} days" if hot > m * 365 / 12 else f"{m} months"
    cap = f"{int(fx['cap_gb']):,}"
    return {
        "consequence": f"{lead} become eligible for deletion {TIMING[0]} {every} {size}",
        "consequence_now": (
            f"{lead} are deleted when you apply: {TIMING[1]}, and every daily run repeats it, "
            f"Parquet included. {size_now}"
        ),
        "consequence_total": (
            f"Trades for {sym} older than {m} months become eligible for deletion {TIMING[0]} "
            f"{every} {size_total}"
        ),
        "undo": UNDO,
        "typed": "Type trades to confirm",
        "pinned_note": f"{fx['pinned_symbol']} is pinned and is not affected.",
        "tiering": (
            f"Moves trades older than {n} days to Parquet sooner; it is still kept for {m} months. "
            "Nothing is deleted."
        ),
        "help_archive": (
            "Days in the fast store before the nightly move to Parquet. "
            f"Parquet keeps it for {m} months in total."
        ),
        "title": f"Delete trades after {n} days?",
        "title_total": title_total,
        "title_total_move": f"{move} {m} months?",
        "title_total_long": f"{move} {long_words}?",
        "estimate": (
            f"Under this policy the fast store settles at most about {fx['steady_gb']} GB "
            f"({fx['steady_pct']} % of {cap} GB), plus pinned data."
        ),
        "lengthen_body": (
            f"Nothing is deleted. The fast store settles at most about {fx['steady_gb']} GB, "
            "plus pinned data."
        ),
        "pinned_row": f"⚲ {fx['pinned_symbol']} · {fx['pinned_gb']} GB · Exempt (pinned)",
        "preview_row": row,
        "preview_total": total,
        "kind_titles": " · ".join(
            [
                f"Delete trades after {n} days?",
                f"Delete trades after {fx['drop_lower_to']} days?",
                f"Delete {sym} trades after {fx['override_days']} days?",
                f"Remove the {sym} trades rule?",
                "Shorten retention for 2 streams?",
                f"{move} {m} months?",
                title_total,
            ]
        ),
    }


def horizon(text: str) -> float:
    """A `21` section 7 Total horizon cell in days: "24 mo", "90 d" or "∞"."""
    if text.strip() == "∞":
        return float("inf")
    m = re.fullmatch(r"(\d+) (mo|d)", text.strip())
    if not m:
        raise ValueError(f"`21` section 7: unreadable total horizon {text!r}")
    return int(m.group(1)) * (365 / 12 if m.group(2) == "mo" else 1)


def side_totals(side: str, totals: dict[str, str]) -> dict[str, float]:
    """`21` :3005: the total is the days for `drop`, never shorter than the hot window otherwise."""
    out: dict[str, float] = {}
    for pair in side.split(";"):
        stream, days, action = pair.split()
        hot = float(days)
        out[stream] = hot if action == "drop" else max(hot, horizon(totals[stream]))
    return out


def diffs(facts: dict[str, Any], fx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every DIFF_TABLE row with its stage, its totals before and after and whether it reduces."""
    keys: dict[str, Any] = {f"seed_{k}": v for k, v in facts["seed"].items()}
    keys.update({k: v for k, v in fx.items() if isinstance(v, int | float | str)})
    keys["example_days"] = fx["override"][1]
    out: dict[str, dict[str, Any]] = {}
    for name, stage, before, after in rows(DIFF_TABLE):
        if before == "kinds":
            out[name] = {"stage": stage, "kinds": True, "before": before, "after": after}
            continue
        b_side, a_side = before.format(**keys), after.format(**keys)
        tb = side_totals(b_side, facts["total_horizon"])
        ta = side_totals(a_side, facts["total_horizon"])
        out[name] = {
            "stage": stage,
            "kinds": False,
            "before": b_side,
            "after": a_side,
            "totals": {k: [tb[k], ta[k]] for k in tb},
            "reduction": any(ta[k] < tb[k] for k in tb),
        }
    kinds = [v["reduction"] for k, v in out.items() if re.fullmatch(r"K\d+", k)]
    for v in out.values():
        if v["kinds"]:
            v["reduction"] = bool(kinds) and all(kinds)
    return out


def frame_rows(spec: str, a: int, b: int) -> list[tuple[str, list[str]]]:
    out = []
    for m in re.finditer(FRAME_RE, section(spec, a, b), MULTI):
        c = cells(m.group(0))
        out.append((c[0].strip("`"), c))
    return out


def gates(
    files: list[Path],
    spec: str,
    facts: dict[str, Any],
    t: dict[str, str],
    sent: dict[str, str],
    diff: dict[str, dict[str, Any]],
    mode: str = "",
) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = section(spec, 14, 15)
    if SENTENCE_14 not in deck:
        bad.append(
            "spec section 14: the `14` :2769 validation sentence is not in the copy deck byte-for-byte"
        )
    if not facts["sentence_14_present"]:
        bad.append("`14`: the validation sentence is gone from the catalogue")
    for k in (
        "consequence",
        "consequence_now",
        "consequence_total",
        "undo",
        "typed",
        "pinned_note",
        "tiering",
        "help_archive",
        "title",
        "title_total",
        "title_total_move",
        "title_total_long",
        "estimate",
        "lengthen_body",
        "preview_row",
        "preview_total",
    ):
        if sent[k] not in deck:
            bad.append(
                f"spec section 14: the {k} sentence is not in the copy deck: {sent[k][:48]!r}"
            )
    # the Apply-now truth: the lengthening body's row carries the qualifier, the run-now body
    # names it, and the lengthening frame's Trigger leaves Apply now unticked
    lengthen = first(r"^(\| `retention\.confirm\.lengthen\.body` +\|.*)$", deck, MULTI)
    if mode == "applynow":
        lengthen = lengthen.replace(APPLY_NOW_QUALIFIER, "", 1)
    if APPLY_NOW_QUALIFIER not in lengthen:
        bad.append("spec section 14: retention.confirm.lengthen.body lacks the Apply-now qualifier")
    now = first(r"^(\| `retention\.confirm\.plain\.body_now` +\|.*)$", deck, MULTI)
    if "`retention.confirm.lengthen.body`" not in now:
        bad.append(
            "spec section 14: retention.confirm.plain.body_now does not cover the lengthening confirm"
        )
    trig = first(r"^\| `SCR-141/confirm-lengthen` +\| ([^|]*)\|", spec, MULTI)
    if "Apply now unticked" not in trig:
        bad.append(
            "spec section 5: SCR-141/confirm-lengthen's Trigger does not leave Apply now unticked"
        )
    for title in sent["kind_titles"].split(" · "):
        if title not in deck:
            bad.append(f"spec section 14: the kind title is not in the copy deck: {title!r}")
    strings = re.findall(r"^\| `[^`]+` +\| ([^|]+?) +\|", deck, MULTI)
    for p in BANNED_COPY:
        for s in strings:
            if re.search(p, s):
                bad.append(f"spec section 14: jargon in user copy: {p!r} in {s[:40]!r}")
                break
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        for s in re.findall(r'"([^"]+)"', cell):
            if len(s) > LAYOUT["reason_max"] or not s.endswith(".") or re.search(r"\d", s):
                bad.append(
                    f"T2 reason {key}: {len(s)} chars; stop {s.endswith('.')}; digit {bool(re.search(r'[0-9]', s))}"
                )
    # (5) the per-frame gates over every state table (sections 4-9, 11). Whether a frame is a
    # reduction comes from DIFF_TABLE's horizons; its Class cell must agree, and never decides.
    tables = [(a, b) for _, a, b, p in COUNTS if p.startswith(r"^\| `SCR-141/")]
    seen: dict[str, int] = {}
    reductions = t2 = validity = 0
    mutated = {"consequence": False, "typed": False, "producer": False}
    kinds = re.findall(r"^\| (K\d) +\|(.*)$", section(spec, 5, 6), MULTI)
    # the typed instruction each kind's inset draws, in the kinds table's order (its typed value)
    want_typed = [first(r"`([^`]+)`", cells("|" + rest)[-1]) for _, rest in kinds]
    kinds_shows = ""
    for a, b in sorted(set(tables)):
        for name, c in frame_rows(spec, a, b):
            seen[name] = seen.get(name, 0) + 1
            if len(c) < 5:
                bad.append(f"spec section {a}: {name} has fewer than five columns")
                continue
            shows, cls = c[2], c[3]
            for k in FRAME_SENTENCES.get(name, ()):
                if sent[k] not in shows:
                    bad.append(f"spec section {a}: frame {name} lacks the derived {k}: {sent[k]!r}")
            d = diff.get(name, {"stage": "", "kinds": False, "reduction": False})
            said = "destructive" in cls or "reduction" in cls
            if said != d["reduction"]:
                bad.append(
                    f"spec section {a}: {name}: the Class cell says reduction={said}, "
                    f"the before / after horizons say reduction={d['reduction']}"
                )
            if d["reduction"]:  # a reduction frame: the consequence sentence always
                reductions += 1
                row_text = shows
                if mode == "consequence" and not mutated["consequence"]:
                    mutated["consequence"] = True
                    for k in ("consequence", "consequence_now"):
                        row_text = row_text.replace(sent[k], "")
                confirm = d["stage"] == "confirm"
                if mode == "typed" and confirm and not d["kinds"] and not mutated["typed"]:
                    mutated["typed"] = True
                    row_text = row_text.replace(TYPED_LABEL, "")
                producer = c[1]
                if mode == "producer" and d["kinds"] and not mutated["producer"]:
                    mutated["producer"] = True
                    producer = PLAIN_MARKS[0] + ": " + producer
                # the plain marks, read from the Producer, Shows and Class cells alike
                if any(pm in cell for pm in PLAIN_MARKS for cell in (producer, row_text, cls)):
                    bad.append(f"spec section {a}: reduction frame {name} names the plain confirm")
                if d["kinds"]:
                    kinds_shows = row_text
                titles = sent["kind_titles"].split(" · ")
                if d[
                    "kinds"
                ]:  # the kinds frame: every reduction kind's title stands for its sentence
                    if any(tt not in row_text for tt in titles):
                        bad.append(
                            f"spec section {a}: reduction frame {name} lacks its consequence "
                            "sentence (a kind title is missing)"
                        )
                elif (
                    sent["consequence"] not in row_text and sent["consequence_now"] not in row_text
                ):
                    bad.append(
                        f"spec section {a}: reduction frame {name} lacks its consequence sentence"
                    )
                if "Nothing is deleted." in row_text:
                    bad.append(f"spec section {a}: reduction frame {name} says Nothing is deleted.")
                if confirm:  # a destructive confirm: the typed field, never the plain variant
                    if TYPED_LABEL not in row_text:
                        bad.append(
                            f"spec section {a}: destructive frame {name} lacks the typed field "
                            f"(its quoted label {TYPED_LABEL})"
                        )
                    if "typed" not in cls:
                        bad.append(
                            f"spec section {a}: destructive frame {name}'s Class cell lacks typed"
                        )
                    if UNDO not in row_text:
                        bad.append(
                            f"spec section {a}: destructive frame {name} lacks the undo line"
                        )
                    if not any(tc in row_text for tc in TIMING):
                        bad.append(
                            f"spec section {a}: destructive frame {name} lacks a timing clause"
                        )
            if "T2" in cls:
                t2 += 1
                if "lock" not in shows:
                    bad.append(f"spec section {a}: T2 frame {name} draws no lock")
                if "rbac.view_as" not in c[4]:
                    bad.append(
                        f"spec section {a}: T2 frame {name} is not the view-as leg "
                        "(the only T2 on SCR-141)"
                    )
            if "validity" in cls:
                validity += 1
                if "validity-reason" not in shows or "lock" in shows:
                    bad.append(
                        f"spec section {a}: validity frame {name} must carry validity-reason "
                        "and no lock"
                    )
    for name, n in seen.items():
        if n > 1:
            bad.append(f"spec: frame {name} appears in {n} state rows (one row per frame)")
    for name in diff:
        if name.startswith("SCR-141/") and name not in seen:
            bad.append(f"DIFF_TABLE: frame {name} is not in the spec's state tables")
    for name in FRAME_SENTENCES:
        if name not in seen:
            bad.append(f"spec: frame {name} is not in the spec's state tables")
    for k in ("consequence", "typed", "producer"):
        if mode == k and not mutated[k]:
            bad.append(f"mutation: no frame to mutate for {k}")
    got_typed = re.findall(r'"Type ([^"]+) to confirm"', kinds_shows)
    if kinds_shows and got_typed != want_typed:
        bad.append(
            f"spec section 5: the kinds frame's typed instructions {got_typed} differ from the "
            f"kinds table's typed values {want_typed}"
        )
    # the reduction-kinds table (section 5): every kind is a reduction by its horizons and takes the
    # typed confirm: a title ending "?" no other kind shares, a body with the undo line (or the
    # `retention.confirm.body` reference, whose deck row carries it) and never "Nothing is deleted.",
    # and a typed value in code style, never the plain confirm
    plain_target = next(
        (
            k
            for k, v in diff.items()
            if re.fullmatch(r"K\d+", k)
            and str(v["before"]).endswith(" drop")
            and str(v["after"]).endswith(" archive_parquet")
        ),
        "",
    )
    mutated_k = mutated_p = mutated_t = mutated_n = False
    title_of: dict[str, str] = {}
    k6_title = next((cells("|" + r)[2] for k, r in kinds if k == plain_target), "")
    for kid, rest in kinds:
        c = cells("|" + rest)
        if len(c) < 5:
            bad.append(f"spec section 5: kind {kid} has fewer than five columns")
            continue
        body, typed = c[3], c[4]
        if mode == "title" and kid == "K7" and k6_title:
            mutated_t = True
            c[2] = k6_title
        if mode == "nothing" and kid == plain_target:
            mutated_n = True
            body += " Nothing is deleted."
        fixture_title = (re.findall(r'"([^"]+\?)"', c[2]) or [""])[-1]
        twin = next((k for k, tt in title_of.items() if tt == fixture_title), "")
        if twin:
            bad.append(f"spec section 5: kinds {twin} and {kid} share a title {fixture_title!r}")
        title_of[kid] = fixture_title
        if any("Nothing is deleted." in cell for cell in (*c[:3], body)):
            bad.append(f"spec section 5: kind {kid} says Nothing is deleted.")
        if mode == "kinds" and not mutated_k:
            mutated_k = True
            body = body.replace("It cannot be undone.", "").replace("`retention.confirm.body`", "")
        if mode == "plain" and kid == plain_target:
            mutated_p = True
            typed = "none: the plain confirm (Nothing is deleted.)"
        if not re.search(r'"[^"]+\?"', c[2]):
            bad.append(
                f"spec section 5: kind {kid} has no quoted title ending with a question mark"
            )
        if "It cannot be undone." not in body and "`retention.confirm.body`" not in body:
            bad.append(f"spec section 5: kind {kid} lacks the undo line")
        if kid not in diff:
            bad.append(f"spec section 5: kind {kid} has no DIFF_TABLE row")
            continue
        d = diff[kid]
        if not d["reduction"]:
            bad.append(
                f"spec section 5: kind {kid} is not a reduction by its horizons {d['totals']}"
            )
        elif not re.search(r"`[^`]+`", typed) or any(
            pm in typed for pm in (*PLAIN_MARKS, "plain", "Nothing is deleted.")
        ):
            bad.append(
                f"spec section 5: kind {kid} shrinks the total {d['totals']} but takes no typed "
                "confirm"
            )
    for k in diff:
        if re.fullmatch(r"K\d+", k) and k not in {kid for kid, _ in kinds}:
            bad.append(f"DIFF_TABLE: kind {k} is not in the spec's kinds table")
    if mode == "kinds" and kinds and not mutated_k:
        bad.append("mutation: no reduction kind to mutate")
    if mode == "plain" and not mutated_p:
        bad.append("mutation: no drop -> archive_parquet kind to mutate")
    if mode == "title" and not mutated_t:
        bad.append("mutation: no K7 / K6 pair to mutate")
    if mode == "nothing" and not mutated_n:
        bad.append("mutation: no drop -> archive_parquet kind to mutate")
    # the classification table: the view-as row first among the gated rows; the absences row present
    s1 = section(spec, 1, 2)
    gated = re.findall(
        r"^\| ([^|]+?) +\| \*\*(T2|validity look|busy|T4|absence|outcome|exempt)\*\*", s1, MULTI
    )
    if not gated or "viewing as" not in gated[0][0] or gated[0][1] != "T2":
        bad.append("spec section 1: the view-as T2 row is not the first classified row")
    if sum(cls == "T2" for _, cls in gated) != 1:
        bad.append(
            "spec section 1: SCR-141 has exactly one T2 row (view-as); over-conversion is a defect"
        )
    for absent in ABSENCES:
        if f"`{absent}`" not in s1:
            bad.append(f"spec section 1: absence `{absent}` is not named")
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
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {c}")
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
    expect = {"stream_kinds": 8, "retention_actions": 4, "job_status": 5}
    for k, n in expect.items():
        if len(facts[k]) != n:
            bad.append(f"`22`: {k} has {len(facts[k])} values, the spec assumes {n}")
    if [k for k, _ in STREAM_TABLE] != list(facts["stream_kinds"]):
        bad.append("`22` StreamKind order differs from the spec's eight rows")
    for k, ok in facts["put_sentences"].items():
        if not ok:
            bad.append(f"`22` setRetentionPolicies: the {k} sentence is gone")
    for k in (
        "resolution_order",
        "read_policy_row",
        "archive_total_floor",
        "mainnet_comment",
        "daily_job_24",
        "never_delete_referenced",
        "sr_099",
        "s19_owner_only",
        "us_rec_003_dry_run",
        "us_admin_006_typed",
    ):
        if not facts[k]:
            bad.append(f"contract fact gone: {k}")
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    modes = [m for m in MUTATIONS if f"--mutate-{m}" in argv]
    if len(modes) > 1:
        print("one mutation mode at a time: " + ", ".join(modes))
        return 2
    mode = modes[0] if modes else ""
    themes = {k: load_theme(k) for k in THEMES}
    t = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
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
        row: dict[str, object] = {"element": element, "fg": fg, "bg": bg, "role": role}
        row.update(
            {"verdict": verdict, "pairs": reg, **{k: round(v, 4) for k, v in ratios.items()}}
        )
        matrix.append(row)
        out.append(
            f"{fg} on {bg} | {role} | {' / '.join(show(r) for r in ratios.values())} | {verdict} | {reg} | {element}"
        )
    composite: dict[str, float] = {}
    for th, tk in themes.items():
        over = resolve(tk, "color.surface.overlay")
        label = blend(resolve(tk, "color.text.on-action"), over, 0.45)
        fill = blend(resolve(tk, "color.action.primary.default"), over, 0.45)
        composite[th] = round(contrast(label, fill), 2)
    out.append(
        f"validity composite (Apply at opacity.disabled over the dialog; not gated): {composite}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    out.append(f"MISSING tokens: {missing}")
    facts = contract_facts(t)
    fx = fixture(facts)
    sent = sentences(fx)
    diff = diffs(facts, fx)
    out.append("\n## 3. Contract facts parsed from text (and the derived fixture):")
    derived = {"facts": facts, "fixture": fx, "sentences": sent, "diffs": diff}
    out.append(json.dumps(derived, ensure_ascii=False))
    spec = SPEC.read_text(encoding="utf-8")
    bad = gates([SPEC, *extra], spec, facts, t, sent, diff, mode)
    ok = (
        "OK — the `14` sentence verbatim; the consequence sentences in the deck and on every reduction frame, "
        "the destructive ones with the typed instruction, a timing clause and the undo line; every reduction kind with its title, "
        "body and typed value; one T2 (view-as) with its lock, first; validity frames with their reason and no lock; "
        "the absences named; no jargon; no private path; every C / CMP / SCR id exists; every cited text exists; no closing keyword"
    )
    out.append(
        "\n## 4-5. String and frame gates: "
        + (ok if not bad else "\n".join("FAIL " + b for b in bad))
    )
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    deck = section(spec, 14, 15)
    deck_rows = re.findall(r"^\| `[^`]+` +\| [^|]*\| ([^|]+?) +\|", deck, MULTI)
    by_source: dict[str, int] = {}
    for src in deck_rows:
        key = src.split(" ")[0].strip("`*")
        by_source[key] = by_source.get(key, 0) + 1
    reasons = [k for k, _ in re.findall(REASON_RE, deck, MULTI)]
    numbers: dict[str, object] = {k: count(p, section(spec, a, b)) for k, a, b, p in COUNTS}
    numbers.update({k: count(rf"^\| D03-{p}\d+ ", spec) for k, p in ROW_IDS})
    tables = sorted({(a, b) for _, a, b, p in COUNTS if p.startswith(r"^\| `SCR-141/")})
    all_rows = [c for a, b in tables for _, c in frame_rows(spec, a, b)]
    numbers["frames_total"] = len(all_rows)
    numbers["reduction_frames"] = sum(
        bool(diff.get(c[0].strip("`"), {}).get("reduction")) for c in all_rows
    )
    numbers["t2_frames"] = sum("T2" in c[3] for c in all_rows if len(c) > 3)
    numbers["validity_frames"] = sum("validity" in c[3] for c in all_rows if len(c) > 3)
    numbers["bq_rows"] = count(r"^\| BQ-\d+ ", spec)
    numbers["kinds"] = count(r"^\| K\d +\|", section(spec, 5, 6))
    numbers["checklist_items"] = count(r"^\| 14:2775 ", spec)
    numbers["checklist_boxes_14"] = facts["checklist_boxes_14"]
    numbers["typed_kinds"] = sum(
        bool(v["reduction"]) for k, v in diff.items() if re.fullmatch(r"K\d+", k)
    )
    numbers.update(
        {
            "pairs_rows": gated,
            "pairs_registered": gated - proposed,
            "pairs_proposed": proposed,
            "pairs_fail": fails,
        }
    )
    numbers.update(
        {"composite": composite, "deck_rows": len(deck_rows), "deck_by_source": by_source}
    )
    numbers["opacity_disabled"] = float(resolve(themes["dark"], "opacity.disabled"))
    numbers.update({"deck_new": by_source.get("new", 0), "reason_keys": len(reasons)})
    numbers["reason_keys_proposed"] = sum(r.startswith("recorder.") for r in reasons)
    numbers["validation_messages"] = count(r"^\| `retention\.err\.", deck)
    numbers["refusal_sentences"] = count(r"^\| `retention\.refused\.", deck)
    numbers["job_keys"] = count(r"^\| `retention\.job\.", deck)
    numbers.update({"missing_tokens": len(missing), "banned_copy_words": len(BANNED_COPY)})
    numbers.update({"streams": len(facts["stream_kinds"])})
    numbers.update({"actions": len(facts["retention_actions"])})
    numbers.update(
        {"actions_offered": 2, "absences": len(ABSENCES), "absent_fields": len(ABSENT_FIELDS)}
    )
    numbers.update({"job_states": len(facts["job_status"])})
    numbers.update({"retain_min": facts["retain_min"], "retain_max": facts["retain_max"]})
    numbers.update({"seed": facts["seed"], "fixture": fx, "layout": LAYOUT})
    numbers["example_rows_22"] = fx["example_rows"]
    flat = flatten(numbers)
    if "--check" in argv:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except ValueError:
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
        clean = not any(b.startswith("marker") for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
        out += [f"FAIL {b}" for b in bad if b.startswith("marker")]
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    if mode:
        needle = MUTATIONS[mode]
        hits = [b for b in bad if needle in b]
        passed = len(hits) == 1 and len(bad) == 1
        out.append(
            f"\n## mutation --mutate-{mode} ({needle}): {len(hits)} FAIL — "
            + ("as expected" if passed else "UNEXPECTED")
        )
        out += [f"FAIL {b}" for b in bad]
        print("\n".join(out))
        return 0 if passed else 1
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        payload = {
            "numbers": numbers,
            "matrix": matrix,
            "missing": missing,
            "facts": facts,
            "sentences": sent,
            "diffs": diff,
        }
        payload.update({"problems": bad, "cite_warnings": CITE_WARN, "palette": palette})
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
