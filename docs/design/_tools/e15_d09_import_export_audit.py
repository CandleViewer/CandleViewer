#!/usr/bin/env python3
"""E15-D09 SCR-026 workspace import / export, preview and rejection states: the spec's gate tool.

Stdlib only, offline; reads the plan texts, the merged upstream specs, the token JSON, `pairs.mjs`
and the spec AS TEXT. The contrast ratio is `contrast_ratio()` of
`docs/design/_tools/contrast_check.py` and the themes resolve through the loader of
`packages/ui/tokens/tests/verify_tokens.py` (prim + dark, + light, + high-contrast, `themes.json`
layering), both imported, never re-implemented; the CVD rows use
`docs/research/_tools/cvd_simulate.py`. Prints: (1) the measured matrix of every fg / bg pair the
two dialogs draw (text 4.5, body text 7.0 in high contrast, non-text 3.0; the rejected and the
decorative rows reported, never gated); (2) every bound token, resolved or MISSING; (3) the
greyscale luma and CVD rows of the Add / Drop / Remap glyph colours (reported); (4) the contract
facts the frames quote — the limits (size, depth, nodes, layouts, panes, workspaces), the caps,
the frame budget — parsed from `22` / `21` / `14` / `15` / the backlog / CONSTITUTION text, never
typed; (5) the gates, each FAIL led by its code in brackets. Every line of the spec is read by
exactly one ladder, which reports the first FAIL of that line: the FRAME ladder reads every
`SCR-025/export-*` and `SCR-026/*` row of §2-§5 (the obligations come from the tool's KIND table
and are compared clause by clause, whole clauses, never first words; the row's Class cell must
agree), the TABLE ladder reads §4.2 and §4.3 row by row against the fixture, the BOARD gates read
§0, and the LINE ladder reads every other line, prose and tables alike, with case-insensitive
vocabulary lists (the gated-exit words, the environment words, the sharing claim, the markup and
link words for untrusted strings). Then the header, the deviations, the AC trace, the ruled
questions and conditions, the numbered sections in order, the cites (a moved line is a WARN; a
fragment gone or ambiguous is a FAIL; a cite missing from CITED_TABLE is a FAIL), the `14`
pointer lines, private paths and hosts, closing keywords, dangling rule and catalogue ids,
placeholders, and the written sections (each skipped while it is still a placeholder: §6's one T2
paragraph, §7's exits sentence, §8's measured tables, §9's deck, §10-§16); (6) the counts.
`--json` is the only source of every number in the spec: every `<!-- audit:KEY=VALUE -->` marker
is re-derived on every run, the number printed beside it must equal it, a malformed marker is a
FAIL and no marker the spec carries may disappear; `--check` adds the markers summary line.
`--self-test` applies each named mutation of `mutations()` to an in-memory copy of the spec (and
each of `context_mutations()` to an in-memory copy of the plan texts) and passes only when each
adds exactly one new FAIL carrying its expected code, every gate code of this file is behind at
least one mutation (EXEMPT names the few no spec or plan-text edit reaches, with the reason),
S1-S20 of the brief all run (S16 once per gated-exit word), the per-frame gates are clean on the
unmutated spec and the spec on disk is byte-identical afterwards. A mutation whose target section
is still a placeholder is DEFERRED and counted (a spec without placeholders defers none). Exit 1
on any FAIL, with or without a flag.

Usage: python3 -I -B docs/design/_tools/e15_d09_import_export_audit.py [--json] [--check]
       [--self-test]
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOL = Path(__file__).resolve()
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E15" / "E15-D09.md"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(DESIGN / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

MULTI = re.MULTILINE
THEMES = ("dark", "light", "high-contrast")
BASE = "c4989493461ec6b6d22b9254633452a6362b750e"
# The orchestrator's ruling on the BQ list (issue comment on #363): "RULED" cites this id.
RULING = "6396085915"
# The merged inputs the header pins: E15-D01, E15-D02 text and boards, E15-D04, E15-D06 and
# E09-D09 (E15-D03's merge is the base itself, BASE). E15-D08 is PENDING and named only.
MERGE_SHAS = (
    "ed8a22246263ace73f39e4434e6d5f57b1a857bd",
    "1044c4f602eff6ae1a2cf42201ab398f6c4234d1",
    "7be6eac6a705cf24ba534ce4f7d31349a1e29932",
    "c73aec08246f06d28c70e8b959c658bc1a0c4d09",
    "6e2c1211fc5f4675457d57011a346642f92710c5",
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
)
PENPOT_PAGE = "E15-D09 Workspace import and export"
STATUS_WORDS = (
    "text-first",
    "PROPOSED unless RULED",
    "boards PENDING",
    "≤ 10 boards",
    "≤ 1/3",
    RULING,
)
# Generic patterns only (the repo is public): a local home path (POSIX, Windows or UNC), a
# design-tool host, a team or file id query, a home-relative path, a tailnet host, an IPv4
# address. Split literals keep the tool from matching itself.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"\b[A-Za-z]:\\(?:Users|Documents and Settings)\\",
    r"\\\\[\w$.-]+\\[\w$.-]+",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"~/[a-z0-9-]+/",
    r"\.ts\.n[e]t\b",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
)
# A closing keyword in any form GitHub links (text-first PRs say `Refs` and `Partial:` only).
CLOSING = (
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
    r"(?:(?:[\w.-]+/[\w.-]+)?#\d+|https?://\S+/issues/\d+)"
)
POINTER = "[E15-D09.md](../design/E15/E15-D09.md)"
# Each pointer line sits in the run of pointer lines right after its screen's checklist in `14`.
POINTER_AFTER = (
    "[ ] delete-workspace confirmation path",
    "[ ] import never carries credentials or account bindings (verified in copy)",
)
NOT_DRAWN = "not drawn — the text is binding; drawn on request"
BOARD_CAP = 10
# The one board that draws a walk, not frames (the keyboard, focus and announcement walk).
TABLE_BOARDS = ("08",)
EN_DASH = "–"
TIMES = "×"
# doc key -> path; a cite in the spec is `KEY:line`, or a range with an en dash, in one code span.
# `C` (CONSTITUTION) is read for facts and rule ids only; it is cited by rule id, never by line.
DOC_PATHS = {
    "04": PLAN / "04-security-program.md",
    "05": PLAN / "05-accessibility-standard.md",
    "11": PLAN / "11-user-stories.md",
    "14": PLAN / "14-screens-catalogue.md",
    "15": PLAN / "15-component-catalogue.md",
    "16": PLAN / "16-design-system-brief.md",
    "21": PLAN / "21-database-schema.md",
    "22": PLAN / "22-api-openapi.yaml",
    "BL": PLAN / "backlog" / "E15.json",
    "C": ROOT / "CONSTITUTION.md",
    "D01": DESIGN / "research" / "e15-layouts" / "findings.md",
    "D02": DESIGN / "E15" / "E15-D02.md",
    "D03": DESIGN / "E15" / "E15-D03.md",
    "D06": DESIGN / "E15" / "E15-D06.md",
    "FL": DESIGN / "specs" / "e15-layout-flows.md",
    "S4": DESIGN / "E05" / "E05-D02-feedback-overlays.md",
    "E09D09": DESIGN / "E09" / "E09-D09.md",
    "E36D03": DESIGN / "E36" / "E36-D03.md",
    "README": DESIGN / "README.md",
}
CITE_KEYS = "04|05|11|14|15|16|21|22|BL|D01|D02|D03|D06|FL|S4|E09D09|E36D03|README"
CITE_RE = rf"`({CITE_KEYS}):(\d+)(?:{EN_DASH}(\d+))?`"
CITE_WARN: list[str] = []
# role -> (bar in dark, bar in light, bar in high contrast); None = reported, never gated.
# `hc-text` is body text: 4.5 in dark and light, 7.0 in high contrast (`05:131`'s neighbour rule).
BARS: dict[str, tuple[float, float, float] | None] = {
    "text": (4.5, 4.5, 4.5),
    "hc-text": (4.5, 4.5, 7.0),
    "non-text": (3.0, 3.0, 3.0),
    "decorative": None,
    "rejected-text": None,
}
# element | fg | bg | role — every pair the export and import dialogs draw (spec §8, rows in order).
PAIRS_TABLE = """
titles, body, lists, odd rows, mono values | color.text.primary | color.surface.overlay | hc-text
help, captions, T2 and availability reasons | color.text.secondary | color.surface.overlay | hc-text
even table rows (striping, PROPOSED) | color.text.primary | color.surface.raised | hc-text
table header cells | color.text.primary | color.surface.hover | hc-text
T2 label and lock, availability label | color.text.tertiary | color.surface.overlay | hc-text
Add glyph on an odd row | color.status.success.strong | color.surface.overlay | non-text
Drop and rejection glyphs, odd rows | color.status.danger.strong | color.surface.overlay | non-text
Remap glyph on an odd row | color.status.info.strong | color.surface.overlay | non-text
Add glyph on an even row | color.status.success.strong | color.surface.raised | non-text
Drop glyph on an even row | color.status.danger.strong | color.surface.raised | non-text
Remap glyph on an even row | color.status.info.strong | color.surface.raised | non-text
trust note and migration line words | color.text.primary | color.status.info.subtle | hc-text
trust note edge and glyph | color.status.info.strong | color.status.info.subtle | non-text
budget line words | color.text.primary | color.status.warning.subtle | hc-text
budget line edge and glyph | color.status.warning.strong | color.status.warning.subtle | non-text
completion and report line words | color.text.primary | color.status.success.subtle | hc-text
report line edge and glyph | color.status.success.strong | color.status.success.subtle | non-text
primary labels | color.text.on-action | color.action.primary.default | text
secondary labels | color.text.primary | color.action.secondary.default | text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
focus ring on an even row | color.focus.ring | color.surface.raised | non-text
drag-over edge on its fill | color.border.selected | color.surface.hover | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.overlay | rejected-text
drop-zone edge (not the control) | color.border.default | color.surface.overlay | decorative
"""
BINDINGS = (
    "color.surface.overlay",
    "color.surface.raised",
    "color.surface.hover",
    "color.border.default",
    "color.border.subtle",
    "color.border.selected",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.disabled",
    "color.text.on-action",
    "color.action.primary.default",
    "color.action.secondary.default",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.status.danger.strong",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.focus.ring",
    "palette.black",
    "opacity.scrim",
    "border.hairline",
    "border.thick",
    "border.focus",
    "radius.dialog",
    "radius.card",
    "elevation.dialog",
    "space.dialog.padding",
    "space.stack.md",
    "space.inset.sm",
    "space.inset.xl",
    "size.row.height",
    "size.icon",
    "size.control.compact",
    "size.control.comfortable",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.body-strong",
    "type.ui.label",
    "type.ui.caption",
    "type.num.sm",
    "type.num.base",
)
# name | a | b — colour pairs that must never carry a meaning alone (reported: deltaE76 under each
# deficiency; JND 5.0); the Action word and the glyph's shape carry Add, Drop and Remap.
CVD_TABLE = """
Add glyph against the Drop glyph | color.status.success.strong | color.status.danger.strong
Drop glyph against the Remap glyph | color.status.danger.strong | color.status.info.strong
Add glyph against the Remap glyph | color.status.success.strong | color.status.info.strong
Drop glyph against the budget glyph | color.status.danger.strong | color.status.warning.strong
"""
GREY_TOKENS = (
    "color.status.success.strong",
    "color.status.danger.strong",
    "color.status.info.strong",
    "color.status.warning.strong",
)
JND = 5.0
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# doc | line at the base | text the line must hold. Every `KEY:line` cite in the spec must have a
# row here (a FAIL otherwise); a `14` line after the pointer lines sits one or two lower (allowed).
CITED_TABLE = """
04 | 54 | **Assume the browser is hostile**
04 | 853 | | SR-040  | All external input
04 | 922 | | SR-097 | Replay, export and import endpoints MUST NOT accept filesystem paths
04 | 965 | | SR-127 | React code MUST NOT use `dangerouslySetInnerHTML`
04 | 1139 | | `workspaces:write`                                 |                 ✔
04 | 1180 | Save/load own layouts, templates, drawings, hotkeys
05 | 35 | No functionality may depend on hover-only or drag-only interaction
05 | 96 | **Focus is never silently stolen**
05 | 101 | **Dragging alternatives**
05 | 131 | 7. **Text resize (WCAG 1.4.4, AA)**
05 | 144 | ### 6.2 Layer 2 — ARIA live regions for streaming updates
05 | 150 | **Region hygiene**
11 | 2858 | #### US-LAY-007 — Workspace export and import
11 | 2865 | containing no secrets and no account bindings
11 | 2868 | any account-scoped element is dropped with a clear report
11 | 2871 | import is refused with the versions stated rather than applying partially
11 | 2874 | never embed keys, tokens or account ids
14 | 85 | **RBAC denies server-side; the UI presents.**
14 | 613 | ### SCR-025 — Workspace settings modal
14 | 615 | export as template, delete
14 | 624 | [ ] delete-workspace confirmation path
14 | 626 | ### SCR-026 — Workspace import
14 | 628 | (panels added, symbols referenced, accounts remapped)
14 | 629 | inaccessible account references remap to the user's default account
14 | 630 | CMP-044 ConfirmDialog, CMP-067 FileDrop / Import control.
14 | 632 | the import diff is a table, not a canvas
14 | 633 | a 2 MB layout file validates in <=500 ms
14 | 634 | `layout.imported`, `layout.import_rejected` with `{reason}` (analytics)
14 | 635 | §5.11 (Penpot page `E15-D02`, board 18
14 | 636 | [ ] import never carries credentials or account bindings (verified in copy)
14 | 1984 | ### SCR-089 — Rule import / export
15 | 48 | ### CMP-001 Button
15 | 225 | ### CMP-019 Icon
15 | 262 | ### CMP-023 Progress Bar
15 | 301 | ### CMP-027 ErrorState / InlineError
15 | 306 | `live` overrides it: `polite` for an in-panel load failure
15 | 307 | registers the PROPOSED `icon/x-circle`
15 | 311 | ### CMP-028 Callout / Banner
15 | 361 | ### CMP-033 CopyButton
15 | 409 | ### CMP-038 InlineSpinnerText
15 | 463 | ### CMP-043 Dialog (Modal)
15 | 466 | at most 420 / 560 / 960 px wide
15 | 468 | `Esc` always cancels before the confirmed send
15 | 473 | ### CMP-044 ConfirmDialog
15 | 483 | ### CMP-045 Toast / Notification
15 | 524 | ### CMP-049 Table
15 | 529 | one row element per record
15 | 690 | ### CMP-067 FileDrop / Import control
15 | 694 | (drag-and-drop is additive, never the only path)
15 | 695 | **Tokens**: `color.border.dashed`.
15 | 696 | **Storybook**: Default, DragOver, Error.
15 | 699 | ### CMP-068 CopyableCodeBlock
15 | 811 | ### CMP-079 RbacGate
15 | 2738 | ### CMP-234 ValidationPanel
15 | 2742 | a `role="log"` list ordered errors-first
21 | 3300 | -- sanitised, 1..120 code points
21 | 5069 | Pane settings must never carry credentials or account identifiers
22 | 8521 | operationId: createWorkspace
22 | 8525 | `limit_reached` (32 live workspaces)
22 | 8725 | `limit_reached` (32 live layouts)
22 | 12676 | operationId: exportWorkspace
22 | 12679 | The bundle is self-contained and contains no credentials, account identifiers or
22 | 12681 | `POST /workspaces` with `from_bundle`.
22 | 19626 | validation_failed`): JSON nesting depth must be at most 16;
22 | 19638 | At most 40 characters as sent, at least 1 after sanitising (above), SCR-020.
22 | 19778 |     PaneKind:
22 | 19838 | and never holds credentials, account ids or user ids
22 | 19848 | Every key must match `^[a-z][a-z0-9_]{0,31}$`
22 | 19864 | a Bybit USDT linear perpetual symbol of at most 20 characters
22 | 21209 |     WorkspaceBundle:
22 | 21213 | Portable, credential-free export of presentation state only.
22 | 21215 | schema_version: { type: string }
22 | 21226 | Import (E15-S07; no operation takes a bundle yet) never trusts
22 | 21229 | the array is imported whole or not
22 | 21230 | The server refuses it whole beyond 200 items or 1 MiB of preset JSON
BL | 242 | "key": "E15-D09",
BL | 1111 | "key": "E15-S07",
BL | 1136 | a document with 10000 nested nodes
D01 | 39 | (8) Exports carry no credentials or account bindings
D02 | 84 | **E15-D01's locked list:**
D02 | 133 | **Too many panels is two states:**
D02 | 148 | **Import always creates a new workspace,**
D02 | 292 | **Too many panels** (D-15, board 07)
D02 | 507 | density is global, or per panel
D02 | 509 | ### 5.11 SCR-026 Import, and the export preview
D02 | 511 | **Export preview** (from SCR-025
D02 | 513 | **Import** (both widths): [Choose file…]
D02 | 515 | - **Validating:** "Checking scalping.json…"
D02 | 516 | - **Preview:** a table, never a picture
D02 | 517 | - **Refused, newer version:**
D02 | 518 | - **Rejected:** "This file is 3.4 MB; the limit is 2 MB.
D02 | 519 | - **Viewer, view-as and the limit:**
D02 | 520 | - **Done:** the new workspace opens in a tab
D02 | 522 | Import never writes over an existing workspace (D-30)
D02 | 635 | ### 8.1 Gated controls: T2
D02 | 639 | **Legs, in the server's order**
D02 | 645 | - **Not T2**, each owned elsewhere
D02 | 655 | | "+" › Import… (§5.11)
D02 | 674 | | `workspace.limit.count`
D02 | 732 | **SCR-026:** [board 18]
D02 | 823 | | A-10 |
D02 | 843 | **Contract gaps the frames annotate as "storage pending"**
D02 | 865 | | OQ-O |
D02 | 950 | | E15-D09      |
D03 | 118 | ### 1.4 The T2 rule (stated once
D03 | 122 | ### 1.5 Exits are never gated (A3)
D03 | 126 | ### 1.6 Fixtures and security of the frames
D03 | 145 | **Roles degrade honestly (BQ-11, BQ-12).**
D03 | 365 | CMP-002 "+" with a menu: New workspace…, Open workspace… (CMP-073), Import…
D03 | 384 | | `[⋯]` › Export…
D03 | 564 | | R-5 | "+" › Import…
D03 | 583 | | V-4 | `[⋯]` › Revert to saved…, Export…
D03 | 625 | | `ws.export.unstored`
D03 | 629 | | `layout.cost.title`
D03 | 630 | | `layout.cost.body`
D03 | 631 | | `layout.cost.confirm`
D03 | 634 | | `workspace.limit.count`      |
D03 | 635 | | `rbac.view_as`               |
D03 | 636 | | `rbac.permission`            |
D06 | 101 | **The account axis is a deferred capability
FL | 139 | ## F-LAY-6 — Export, then import on another machine
FL | 146 | C6 -->|Cancel| Z6["Nothing exported"]
FL | 154 | Validated in a worker: size, format, schema, version, panels
FL | 162 | L6 -->|Cancel| Y6["Nothing imported"]
FL | 164 | M6 -->|409 limit_reached, another window got there first|
FL | 169 | **Keyboard:** the file input is a labelled button reached by `Tab`
FL | 170 | `layout.import_rejected {reason: size | parse | schema | version | semantic}`
FL | 171 | the import is not atomic
E09D09 | 85 | Every T2 reason is one of these seven keys
E09D09 | 89 | | `rbac.permission`        | "Your role can't {verb}."
E09D09 | 95 | | `rbac.view_as`           | "Read-only while viewing as {user}."
E09D09 | 114 | `workspaces:write` → "save workspaces"
E36D03 | 153 | ## 8. SCR-089 import (board 08)
E36D03 | 155 | **Drop zone** — CMP-067
E36D03 | 272 | **Token names the composed entries use that do not exist**
E36D03 | 339 | | the drop zone (CMP-067)
S4 | 734 | **H22 — `Esc`, the NoEscClose story and the scrim.**
S4 | 904 | **H36 — A dialog with unsaved changes.**
README | 46 | **Penpot reference** to the ticket's page
"""
# The fixture (synthetic; the spec's Fixture paragraph prints it through markers). The export
# fixture is E15-D02's (`D02:511`); the import fixture `scalping.json` is a colleague's export from
# a build that knows two more panel kinds (a kind is additive for readers, `22:19778`), whose
# Positions pane carries an account filter; `wall.json` is the budget fixture. The two account
# labels are the exporter's: no frame, row or line of the spec may print either (S3).
FIXTURE: dict[str, Any] = {
    "workspace": "Scalping",
    "clash": "Scalping (2)",
    "user": "alex",
    "export_layouts": ("Layout 1", "Order-flow"),
    "export_panels": 7,
    "export_symbols": ("BTCUSDT", "ETHUSDT"),
    "export_groups": ("A", "B"),
    "export_drawings": 12,
    "export_templates": 1,
    "export_presets": 3,
    "export_file": "scalping.cv-workspace-v1.json",
    "import_file": "scalping.json",
    "format": {"app": 1, "newer": 2, "older": 0, "floor": 1, "from": 1, "to": 2},
    "oversized_mb": "3.4",
    "malformed_key": "layouts[1].grid_spec.root",
    "parse_line": 212,
    "panes_in_file": 30,
    "layouts_in_file": 40,
    "presets_in_file": 240,
    "wrong_file": "report.csv",
    "server_key": "layouts[0].panes[3].pane_config",
    "step": (3, 5),
    "budget": {"file": "wall.json", "layout": "Wall", "panels": 12, "layouts": 1},
    "measured_ms": 11.8,
    "estimate_ms": 17.9,
    "foreign_accounts": ("Ledger North", "Desk 9"),
    "reflow": {"zoom": 200, "width": 1280, "height": 800, "margin": 16},
}
# Display caps of this spec, PROPOSED (no contract field caps a key path or a local file name).
DESIGN_CAPS = {"key_cap": 64, "file_cap": 40}
# The preview table of `scalping.json` (§4.2; BQ-10 RULED): Item | Type | Action | Reason, drops and
# remaps first. Type is the registry's kind for a known panel, "panel" for a kind this build does
# not know (its stored name is the Item, AC 3), "setting" for a dropped pane setting.
UNKNOWN_REASON = "not available in this version"
ACCOUNT_REASON = "workspaces never carry account bindings"
REMAP_REASON = "shows your own accounts"
PREVIEW_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("`heatmap_v2`", "panel", "Drop", UNKNOWN_REASON),
    ("`tape_speed_v3`", "panel", "Drop", UNKNOWN_REASON),
    ("Account filter on Positions", "setting", "Drop", ACCOUNT_REASON),
    ("Positions", "positions", "Remap", REMAP_REASON),
    ("Layout 1", "layout", "Add", "—"),
    ("Order-flow", "layout", "Add", "—"),
    ("BTCUSDT · 1m · group A", "chart", "Add", "—"),
    ("BTCUSDT · group A", "dom", "Add", "—"),
    ("BTCUSDT · group A", "tape", "Add", "—"),
    ("ETHUSDT · 5m · group B", "chart", "Add", "—"),
    ("ETHUSDT · 5m · group B", "cvd", "Add", "—"),
    ("ETHUSDT · 15m · group B", "chart", "Add", "—"),
    ("2 symbols: BTCUSDT, ETHUSDT", "symbols", "Add", "—"),
    ("12 drawings, with their text labels", "drawings", "Add", "—"),
    ("1 chart template", "chart template", "Add", "—"),
    ("3 indicator presets", "indicator presets", "Add", "—"),
)
ACTIONS = ("Add", "Drop", "Remap")
# The trust copy (BQ-2 RULED, owner approval pending (#2701)): each sentence byte for byte wherever
# it is shown; E15-D02's own Excluded sentence may be quoted (a C-row), never shown on a frame.
EXCLUDED = (
    "Never included: credentials — API keys or tokens; accounts, trade-group and user ids; "
    "environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
)
D02_EXCLUDED = (
    "Never included: API keys or tokens, account or trade-group ids, user ids, P&L figures, "
    "positions or orders."
)
TRUST_NOTE = (
    "A workspace file never carries credentials or account bindings. Importing creates a new "
    "workspace and changes nothing else."
)
INCLUDED = (
    "The file includes: 2 layouts (Layout 1, Order-flow) · 7 panels · symbols BTCUSDT, ETHUSDT · "
    "sync groups A and B · each panel's settings · 12 drawings, with their text labels · 1 chart "
    "template · 3 indicator presets."
)
CAVEAT = "The file does show your symbols, layouts and settings."
CLASH = "Imported as Scalping (2): a workspace named Scalping exists."
MIGRATED = "Migrated from format version {from} to {to}."
NOTHING = "Nothing was imported."
# key -> the template the deck (§9) carries and the frames render from FIXTURE and the facts.
TEMPLATES = {
    "e15.export.preparing": "Preparing the file…",
    "e15.export.failed": (
        "Couldn't prepare the file: the workspace store is unavailable. Nothing was exported."
    ),
    "e15.export.done": "Exported {workspace} as {file}.",
    "e15.import.help": "JSON, up to {size_mb} MB",
    "e15.import.checking": "Checking {file}… step {i} of {n}",
    "e15.import.rejected.version_newer": (
        "This file was exported by format version {file} and can't be imported into format "
        "version {app}. Nothing was imported. Export it again from a version {app} app, or "
        "update this app."
    ),
    "e15.import.rejected.version_older": (
        "This file was exported by format version {file} and this app reads format version "
        "{floor} or later. Nothing was imported. Update the app that exported it, then export it "
        "again."
    ),
    "e15.import.rejected.malformed": (
        "This isn't a workspace file: `{key}` is missing. Nothing was imported."
    ),
    "e15.import.rejected.parse": (
        "This isn't a workspace file: it stops being valid JSON at line {line}. Nothing was "
        "imported."
    ),
    "e15.import.rejected.panes": (
        "This file has a layout with {n} panels; a layout holds at most {max}. Nothing was "
        "imported."
    ),
    "e15.import.rejected.layouts": (
        "This file has {n} layouts; a workspace holds at most {max}. Nothing was imported."
    ),
    "e15.import.rejected.presets": (
        "This file has {n} indicator presets; a file may carry at most {max}. Nothing was imported."
    ),
    "e15.import.rejected.oversized": (
        "This file is {size} MB; the limit is {max} MB. Nothing was imported."
    ),
    "e15.import.rejected.wrong_type": (
        "That isn't a JSON file ({name}). Nothing was imported. Choose a .json workspace file."
    ),
    "e15.import.rejected.depth": (
        "This file is nested too deeply: the limit is {max} levels. Nothing was imported."
    ),
    "e15.import.rejected.nodes": (
        "This file has more than {max} values: the limit is {max}. Nothing was imported."
    ),
    "e15.import.refused.limit": (
        "You have {max} workspaces, the most you can have. Delete one, then import again."
    ),
    "e15.import.refused.server": "The server didn't accept this file: `{key}` isn't allowed.",
    "e15.import.nothing": NOTHING,
    "e15.import.migrated": MIGRATED,
    "e15.import.clash": "Imported as {clash}: a workspace named {workspace} exists.",
    "e15.export.excluded": EXCLUDED,
    "e15.import.trust": TRUST_NOTE,
    "e15.export.caveat": CAVEAT,
    "e15.import.report.done": (
        "Imported {clash}: {panels}, {layouts}, {dropped} items dropped, {remapped} remapped."
    ),
    "e15.import.caption": (
        "Preview — {panels} and {layouts} to add · {dropped} dropped · {remapped} remapped"
    ),
    "e15.import.report.caption": (
        "Report — {panels} and {layouts} added · {dropped} dropped · {remapped} remapped"
    ),
    "e15.import.caption_budget": (
        "Preview — {panels} and {layouts} to add. {layout} opens at about {estimate} ms per "
        "frame (estimated), over the {budget} ms budget."
    ),
    "e15.import.budget": (
        "{layout} opens with {panels}: about {estimate} ms per frame (estimated), over the "
        "{budget} ms budget."
    ),
    "layout.cost.import.title": "Open {layout} with {panels}?",
    "layout.cost.import.body": (
        "Frame time now: {measured} ms per frame (p95, last 10 s, measured), about {fps} fps. "
        "With {layout}'s {panels}: about {estimate} ms (estimated), about {estfps} fps. Budget: "
        "{budget} ms ({budgetfps} fps). That is over the performance budget, so charts may "
        "stutter."
    ),
}
# frame | kind | parameters — the independent inventory every per-frame gate reads; a row's Class
# cell must agree with it and never decides. `key` = the T2 reason key; `reason` = the rejection or
# refusal; `variant` = the preview's fixture; `zone` = the drag-over state; `dialog` = the reflowed
# dialog.
KIND_TABLE = """
SCR-025/export-entry | export-entry |
SCR-025/export-unavailable | availability |
SCR-025/export-preparing | export-busy |
SCR-025/export-preview | export-preview |
SCR-025/export-failed | export-failed |
SCR-025/export-done | export-done |
SCR-025/export-cancelled | export-cancelled |
SCR-025/export-reflow-200 | reflow | dialog=export
SCR-026/entry | entry |
SCR-026/entry-view-as | t2-entry | key=rbac.view_as
SCR-026/entry-permission | t2-entry | key=rbac.permission
SCR-026/entry-limit | t2-entry | key=workspace.limit.count
SCR-026/pick | pick |
SCR-026/drag-over | drag-over | zone=accept
SCR-026/drag-over-rejected | drag-over | zone=reject
SCR-026/validating | validating |
SCR-026/preview | preview | variant=main
SCR-026/preview-migrated | preview | variant=migrated
SCR-026/preview-over-budget | preview | variant=budget
SCR-026/budget-confirm | budget-confirm |
SCR-026/creating | busy |
SCR-026/import-leg-lost | t2-leg | key=rbac.permission
SCR-026/rejected-version-newer | rejection | reason=version-newer
SCR-026/rejected-version-older | rejection | reason=version-older
SCR-026/rejected-malformed | rejection | reason=malformed
SCR-026/rejected-oversized | rejection | reason=oversized
SCR-026/rejected-wrong-type | rejection | reason=wrong-type
SCR-026/rejected-nodes | rejection | reason=nodes
SCR-026/refused-limit | refusal | reason=limit
SCR-026/refused-server | refusal | reason=server
SCR-026/report | report |
SCR-026/cancelled | cancelled |
SCR-026/reflow-200 | reflow | dialog=import
SCR-026/compact | compact |
"""
# kind -> its Class cell, whole (the rejections are outcomes, never T2; the refusals are T4).
CLASS = {
    "export-entry": "T1",
    "availability": "availability",
    "export-busy": "busy",
    "export-preview": "T1",
    "export-failed": "outcome",
    "export-done": "outcome",
    "export-cancelled": "outcome",
    "reflow": "T1 (reflow)",
    "entry": "T1",
    "t2-entry": "T2",
    "pick": "T1",
    "drag-over": "T1",
    "validating": "busy",
    "preview": "T1",
    "budget-confirm": "confirm",
    "busy": "busy",
    "t2-leg": "T2",
    "rejection": "outcome (rejection)",
    "refusal": "T4 (refusal)",
    "report": "outcome",
    "cancelled": "outcome",
    "compact": "T1 (density)",
}
T2_KINDS = {"t2-entry", "t2-leg"}
MENU_KINDS = {"export-entry", "availability", "entry", "t2-entry"}
EXPORT_DIALOG_KINDS = {
    "export-busy",
    "export-preview",
    "export-failed",
    "export-done",
    "export-cancelled",
}
IMPORT_DIALOG_KINDS = {
    "pick",
    "drag-over",
    "validating",
    "preview",
    "busy",
    "t2-leg",
    "rejection",
    "refusal",
    "report",
}
PRE_SEND_KINDS = {"pick", "drag-over", "validating", "preview"}
NOTHING_KINDS = {"rejection", "refusal"}
TRUST_KINDS = {"pick", "drag-over", "validating", "preview", "busy", "t2-leg"} | NOTHING_KINDS
# The frames that render a string taken from the file (Condition 1: caps and text only).
FILE_STRING_FRAMES = {
    "SCR-026/validating",
    "SCR-026/preview",
    "SCR-026/preview-migrated",
    "SCR-026/preview-over-budget",
    "SCR-026/budget-confirm",
    "SCR-026/report",
    "SCR-026/rejected-malformed",
    "SCR-026/rejected-wrong-type",
    "SCR-026/refused-server",
}
VERSION_FRAMES = {
    "SCR-026/rejected-version-newer": "newer",
    "SCR-026/rejected-version-older": "older",
    "SCR-026/preview-migrated": "migrated",
}
# kind (or frame) -> the footer's labels with their weights, in order (`S4`'s footer rule: Cancel
# first, the primary last); the report keeps Copy report first and Close last.
FOOTERS = {
    "export-busy": "Cancel (`secondary`)",
    "export-preview": "Cancel (`secondary`) · Download file (`primary`)",
    "export-cancelled": "Cancel (`secondary`) · Download file (`primary`)",
    "export-failed": "Cancel (`secondary`) · Try again (`primary`)",
    "export-done": "Close (`primary`)",
    "pick": "Cancel (`secondary`)",
    "drag-over": "Cancel (`secondary`)",
    "validating": "Cancel (`secondary`)",
    "preview": "Cancel (`secondary`) · Import as new workspace (`primary`)",
    "budget-confirm": "Cancel (`secondary`) · Import anyway (`primary`)",
    "busy": "Close (`secondary`) · Import as new workspace (`primary`, `aria-busy`)",
    "t2-leg": "Cancel (`secondary`) · Import as new workspace (T2, §6)",
    "rejection": "Cancel (`secondary`) · Choose another file (`primary`)",
    "SCR-026/refused-limit": "Cancel (`secondary`)",
    "SCR-026/refused-server": "Cancel (`secondary`) · Choose another file (`primary`)",
    "report": "Copy report (`secondary`) · Close (`primary`)",
}
FOCUS = {
    "export-busy": "Cancel",
    "export-preview": 'the title (`tabindex="-1"`)',
    "export-failed": "Try again",
    "export-done": "Close",
    "export-cancelled": "Download file",
    "pick": "Choose file…",
    "drag-over": "Choose file…",
    "validating": "Choose file…",
    "preview": "Choose file…",
    "budget-confirm": "Cancel",
    "busy": "Import as new workspace",
    "t2-leg": "Import as new workspace",
    "rejection": "Choose another file",
    "SCR-026/refused-limit": "Cancel",
    "SCR-026/refused-server": "Choose another file",
    "report": 'the heading "Import report" (`tabindex="-1"`)',
}
ESC = {
    "menu": "Close (the menu, focus back on its button)",
    "dialog": "Cancel",
    "export-done": "Close",
    "report": "Close",
    "busy": "Close (the view only: the import is sent and finishes)",
    "budget-confirm": "Cancel (back to the preview)",
}
EXITS = {
    "menu": "Esc",
    "dialog": f"Cancel · Esc · {TIMES}",
    "export-done": f"Close · Esc · {TIMES}",
    "report": f"Close · Esc · {TIMES}",
    "busy": f"Close · Esc · {TIMES}",
    "budget-confirm": "Cancel · Esc",
    "rejection": f"Cancel · Esc · {TIMES} · Choose another file",
    "SCR-026/refused-server": f"Cancel · Esc · {TIMES} · Choose another file",
}
# The rejection and refusal reasons -> the deck keys their message clause renders, in order, and
# the `layout.import_rejected{reason}` value each fires (the ticket's six; depth and nodes are
# `malformed` in the user's words, BQ-5 RULED).
MESSAGES = {
    "version-newer": ("e15.import.rejected.version_newer",),
    "version-older": ("e15.import.rejected.version_older",),
    "malformed": ("e15.import.rejected.malformed",),
    "oversized": ("e15.import.rejected.oversized",),
    "wrong-type": ("e15.import.rejected.wrong_type",),
    "nodes": ("e15.import.rejected.depth",),
    "limit": ("e15.import.nothing", "e15.import.refused.limit"),
    "server": ("e15.import.nothing", "e15.import.refused.server"),
}
VARIANTS = {
    "malformed": (
        "e15.import.rejected.parse",
        "e15.import.rejected.panes",
        "e15.import.rejected.layouts",
        "e15.import.rejected.presets",
    ),
    "nodes": ("e15.import.rejected.nodes",),
}
EVENT_REASON = {
    "version-newer": "version-newer",
    "version-older": "version-older",
    "malformed": "malformed",
    "oversized": "oversized",
    "wrong-type": "wrong-type",
    "nodes": "malformed",
}
# Vocabulary lists, all read case-insensitively (A2 / Condition 3), each against whole clauses.
# An exit: Cancel, Esc, the close × (not the × of a size), Close, Choose another file.
EXIT_RE = (
    r"(?i)\bcancel\b|\besc(?:ape)?\b|(?<!\d)(?<!\d )×(?! ?\d)|\bclose\b|\bchoose another file\b"
)
# The gated-exit words (the brief's list, then E09-D09's T2 vocabulary).
GATE_WORDS = (
    r"\baria-disabled\b|\bdisabled\b|\block(?:ed|s)?\b|\bpadlock\b|\bgr[ae]yed\b|\bdimmed\b"
    r"|\binert\b|\bheld\b|\bhidden\b|\binactive\b|\bsuppressed\b|\bdoes nothing\b"
    r"|\bdo nothing\b|\bcan[’']t be pressed\b|\bcannot be pressed\b|\bcan not be pressed\b"
    r"|\bwaits? for\b|\bunusable\b|\bunavailable\b|\bnot available\b|\bgated\b|\bblocked\b"
    r"|\bt2\b|\bignored\b|\bignores\b|\bcan[’']t be used\b|\bcannot be used\b|\bunreachable\b"
)
GATE_RE = "(?i)" + GATE_WORDS
NEGATORS = {"never", "not", "no", "nor", "without", "isn't", "aren't", "isn’t", "aren’t"}
NEGATION_WINDOW = 4
# The environment words (no environment travels into an import: SCR-026 frames and §3-§5).
ENV_RE = r"(?i:\benvironments?\b|\btestnet\b|\bmainnet\b|\bdemo\b)|\bLIVE\b|\bLive\b(?! region)"
ENV_ALLOWED = ("environment binding is never imported",)
# Untrusted strings rendered as anything but text (S12).
MARKUP_RE = (
    r"(?i)\bmarkup\b|\bmarkdown\b|\bhtml\b|innerhtml|dangerouslysetinnerhtml|\bhref\b"
    r"|\bhyperlinks?\b|\brich text\b|\bclickable\b|\bas a link\b|\ba link to\b|\binterpreted\b"
)
# The sharing claim no design may make (BQ-2 RULED); split so this file never states it.
SHARE_RE = r"(?i)\bsafe[\s-]+to[\s-]+sh" + r"are\b"
# A claim that something exists before the send (S10).
CREATE_RE = (
    r"(?i)\b(?:was|were|has been|have been|is now|are now|already)\s+(?:created|imported|saved"
    r"|added)\b|\b(?:workspace|layout|pane)s?\s+(?:now\s+)?exists?\b"
)
# A lock, a T2 or a leg (export frames, S15; rejection and refusal frames, S6).
LOCK_WORDS = (
    r"\bt2\b|\block(?:ed|s)?\b|\bpadlock\b|\bcmp-079\b|\brbacgate\b|`rbac\.[a-z_]+`"
    r"|\bgated\b|\blegs?:"
)
LOCK_RE = "(?i)" + LOCK_WORDS + "|" + GATE_WORDS
# An import or apply verb outside the footer of a rejection or refusal frame (S5).
IMPORT_VERB_RE = (
    r"(?i)\bimport (?:as new workspace|anyway|partially|selected|valid|what)\b|\[\s*import\b"
    r"|\bapply(?: anyway| partially| the valid parts?)?\b"
)
# A remap of an account binding in prose (S4; BQ-3 RULED: dropped and listed, never remapped).
REMAP_RE = r"(?i)\bremap(?:s|ped|ping)?\b"
ACCOUNT_RE = (
    r"(?i)\baccount (?:filters?|bindings?|references?|ids?)\b|\baccount-scoped\b"
    r"|\bdefault account\b"
)
STEPS = ("size", "parse", "schema", "version", "registry")
# An account named in an import surface (S3, beyond the fixture's two labels): "account" and a
# capitalised name or an id right after it.
FOREIGN_RE = r"\b[Aa]ccounts?\s+(?!IDs?\b)[`\"'(]?[A-Z0-9][\w-]*"
# The drop zone made a Tab stop anywhere in prose or a free clause (S19).
DROP_RE = r"(?i)\bdrop (?:zone|target)\b"
TAB_STOP_RE = (
    r"(?i)\btab stop\b|\bfocusable\b|\btabindex\b|\breceives focus\b|\btakes focus\b"
    r"|\bin the tab order\b|\btab reaches\b"
)
# An app version in a comparison (S8, prose): the clause compares and names an app version.
APP_VERSION_RE = r"(?i)\bapp ?version\b|\bappversion\b|\bapp_version\b"
# A limit stated in prose (S18): the phrase, the number and its unit -> the fact it must equal.
LIMIT_PHRASE_RE = (
    r"(?i)\b(?:at most|up to|limit is|limit of|cap of|capped at|no more than|maximum of)\s+"
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(MB|levels?|values|nodes|layouts|panes|panels"
    r"|workspaces|indicator presets|presets)\b"
)
LIMIT_UNITS = {
    "mb": "size_mb",
    "level": "depth",
    "levels": "depth",
    "values": "nodes",
    "nodes": "nodes",
    "layouts": "layouts_max",
    "panes": "panes_max",
    "panels": "panes_max",
    "workspaces": "workspaces_max",
    "indicator presets": "presets_max",
    "presets": "presets_max",
}
# key | string | the doc that holds it verbatim, in quotes (E09-D09 §3.1, E15-D02 §8.1, E15-D03).
REASONS_TABLE = """
rbac.view_as | Read-only while viewing as {user}. | E09D09
rbac.permission | Your role can't save workspaces. | D02
workspace.limit.count | You have the most workspaces you can have. | D02
ws.export.unstored | This workspace isn't saved. | D03
"""
MALFORMED_D02 = (
    "This isn't a workspace file: `layouts[1].grid_spec.root` is missing. Nothing was imported."
)
# string | doc — the upstream copy the frames quote verbatim; each must still exist upstream.
UPSTREAM_TABLE = (
    ("Preparing the file…", "D02"),
    ("Couldn't prepare the file: the workspace store is unavailable. Nothing was exported.", "D02"),
    (INCLUDED, "D02"),
    (D02_EXCLUDED, "D02"),
    (TRUST_NOTE, "D02"),
    ("or drop a workspace file here", "D02"),
    ("Checking scalping.json…", "D02"),
    (CLASH, "D02"),
    ("This file is 3.4 MB; the limit is 2 MB. Nothing was imported.", "D02"),
    (MALFORMED_D02, "D02"),
    ("You have 32 workspaces, the most you can have. Delete one, then import again.", "D02"),
    (UNKNOWN_REASON, "BL"),
    ("Export again from the older version", "BL"),
)
# The ticket's and E15-D02's states, each reconciled to the frames that draw it (§1.3 carries this
# table row for row; the partial failure has no frame because no import is ever partial).
STATES_TABLE = """
1 | export: Export… unavailable on the viewer's unsaved default | SCR-025/export-unavailable
2 | export: preparing the file | SCR-025/export-preparing
3 | export: the preview with the Included and Excluded lists | SCR-025/export-preview
4 | export: preparing failed | SCR-025/export-failed
5 | export: the completion | SCR-025/export-done
6 | export: cancelled | SCR-025/export-cancelled
7 | import: gated entry | SCR-026/entry-view-as, SCR-026/entry-permission, SCR-026/entry-limit
8 | import: choose a file | SCR-026/pick
9 | import: a file dragged over | SCR-026/drag-over, SCR-026/drag-over-rejected
10 | import: validating | SCR-026/validating
11 | import: the preview | SCR-026/preview
12 | import: unknown panel types in the preview | SCR-026/preview
13 | import: an account reference in the preview | SCR-026/preview
14 | import: valid but over the panel budget | SCR-026/preview-over-budget, SCR-026/budget-confirm
15 | import: a newer format version | SCR-026/rejected-version-newer
16 | import: an older format version | SCR-026/rejected-version-older, SCR-026/preview-migrated
17 | import: a malformed file | SCR-026/rejected-malformed
18 | import: an oversized file | SCR-026/rejected-oversized
19 | import: the wrong file type | SCR-026/rejected-wrong-type
20 | import: the parse limits (depth, nodes) | SCR-026/rejected-nodes
21 | import: the workspace limit reached at the send | SCR-026/refused-limit
22 | import: creating | SCR-026/creating
23 | import: a failure after the send | SCR-026/refused-server
24 | import: presets over their limits | SCR-026/rejected-malformed, SCR-026/refused-server
25 | import: done, the report | SCR-026/report
26 | import: cancelled | SCR-026/cancelled
"""
# doc | line | frames — the upstream lines the inventory reconciles with; each line's needle is its
# CITED_TABLE row and every frame it names is in KIND (EXEMPT `reconcile`: a tool-table check).
RECONCILE_TABLE = """
D02 | 511 | SCR-025/export-preparing, SCR-025/export-preview, SCR-025/export-failed
D02 | 513 | SCR-026/pick
D02 | 515 | SCR-026/validating
D02 | 516 | SCR-026/preview
D02 | 517 | SCR-026/rejected-version-newer
D02 | 518 | SCR-026/rejected-oversized, SCR-026/rejected-malformed, SCR-026/refused-limit
D02 | 519 | SCR-026/entry-view-as, SCR-026/entry-permission, SCR-026/entry-limit
D02 | 520 | SCR-026/report
D03 | 564 | SCR-026/entry-view-as, SCR-026/entry-permission, SCR-026/entry-limit
D03 | 583 | SCR-025/export-unavailable
FL | 146 | SCR-025/export-cancelled
FL | 162 | SCR-026/cancelled
FL | 164 | SCR-026/refused-limit
14 | 628 | SCR-026/preview
14 | 629 | SCR-026/rejected-version-newer, SCR-026/preview
14 | 632 | SCR-026/pick, SCR-026/preview, SCR-026/rejected-malformed
14 | 636 | SCR-026/pick, SCR-026/drag-over, SCR-026/preview, SCR-026/rejected-oversized
"""
# The deviations (the ticket and the ruling): name -> the words its `- **Deviation — ` line carries.
DEVIATIONS = {
    "the deliverable path": "`docs/design/specs/e15-workspace-import-export.md`",
    "the branch": "`design/e15-workspace-import-export-hifi`",
    "the densities": "densities",
    "the symbol cap": "BQ-10",
}
AC_IDS = (
    [f"AC-{i}" for i in range(1, 7)]
    + [f"DL-{i}" for i in range(1, 22)]
    + [f"DoD-{i}" for i in range(1, 12)]
)
TRACE_STATUS = ("done", "heuristic-only", "routed", "text pending")
# The ruled outcomes each BQ row keeps (the orchestrator's ruling, RULING).
BQ_TERMS = {
    "BQ-1": ("`docs/design/E15/E15-D09.md`", "no `15` edit", "two content-only `14` pointer lines"),
    "BQ-2": (EXCLUDED, "is never written anywhere", "owner approval pending (#2701)"),
    "BQ-3": ("dropped and listed, never remapped", "no account the importer cannot see is ever"),
    "BQ-4": ("Migrated from format version 1 to 2.", "`schema_version`, never an app version"),
    "BQ-5": (
        "size → parse depth / node count → schema → version → per-pane registry → preview",
        "nothing is created before Import as new workspace",
    ),
    "BQ-6": ("Import anyway",),
    "BQ-7": ("never gated (a read)",),
    "BQ-8": ("`<slug>.cv-workspace-v<schema_version>.json`",),
    "BQ-9": ("`lg`", "not a Tab stop"),
    "BQ-10": ("Item · Type · Action · Reason", "drops and remaps first", "exactly three Action"),
    "BQ-11": ("no Import verb", "Choose another file focused"),
    "BQ-12": ('`role="region"`', "Copy report"),
    "BQ-13": ("Choose file… is a real `<button>`",),
    "BQ-14": ("view-as first", "Export… is never gated"),
    "BQ-15": ("ten boards", "at most three light twins"),
    "BQ-16": ("D09-G1",),
}
CONDITION_TERMS = {
    "Condition 1": (
        "every string from the file is untrusted",
        "the server re-checks size, depth, nodes, schema and version",
    ),
    "Condition 2": ("view-as first", "Export… is never gated"),
    "Condition 3": ("case-insensitive vocabulary lists", "whole clauses"),
    "Condition 4": ("Cancel, Esc, ×, Close and Choose another file are never gated",),
}
# The standing additions, stated in the header (A3 whole), and the written sections' fixed
# sentences: T2 stated once (§6), the exits sentence (§7).
A3_STANDING = (
    "**A3** the exits are never gated — Cancel, `Esc`, ×, Close and Choose another file, on every "
    "frame and for every session, view-as and the Viewer's included."
)
T2_ONCE = (
    "E09-D09's decision rule decides every control here",
    "A T2 control keeps its native role and its full label",
)
A3_SECTION = (
    "Cancel, `Esc`, ×, Close and Choose another file are never gated: never T2, never locked by "
    "view-as, a role, a limit or any state, on every frame of this spec."
)
FORCED_COLORS = "`forced-colors: active`"
SECTIONS = [str(n) for n in range(17)]
# The brief's A2 list (S1-S20, S16 once per gated-exit word): each stays in `mutations()`.
S16_WORDS = (
    "disabled",
    "locked",
    "greyed",
    "inert",
    "held",
    "hidden",
    "inactive",
    "suppressed",
    "does nothing",
    "can't be pressed",
    "cannot be pressed",
    "waits for",
    "unusable",
)
A2_NAMES = tuple(
    [f"S{i}" for i in range(1, 16)]
    + [f"S16-{w.replace(' ', '-').replace(chr(39), '')}" for w in S16_WORDS]
    + [f"S{i}" for i in range(17, 21)]
)
# The gate codes no edit of the spec or of a cited plan text can trip, so no mutation stands
# behind them: each checks the token files or this tool's own tables.
EXEMPT = {
    "token-missing": "a bound token resolves through the token JSON, not the spec",
    "contrast-fail": "a pair's ratio is measured from the token JSON; §8's cells are pinned",
    "reason-form": "checks REASONS_TABLE, this tool's own table, for length and full stop",
    "reconcile": "checks RECONCILE_TABLE and STATES_TABLE against CITED_TABLE and KIND",
}
FRAME_RE = r"^\| `((?:SCR-025|SCR-026)/[a-z0-9-]+)` +\|.*$"
FRAME_NAME_RE = r"`((?:SCR-025|SCR-026)/[a-z0-9-]+)`"
BOARD_RE = r"^\| (\d\d) +\| `(E15-D09 / (\d\d) [a-z0-9-]+)` +\|(.*)$"
COPY_KEY_RE = (
    r"^(?:e15\.(?:export|import)\.[a-z0-9_.]+|rbac\.[a-z_]+|workspace\.limit\.[a-z_]+"
    r"|ws\.export\.[a-z_]+|layout\.cost\.[a-z_.]+)$"
)
PLACEHOLDER_RE = r"\*\*Placeholder \(§(\d+)\):\*\* ([^\n]+)"
STATE_ROW_RE = r"^\| (\d+) +\| ([^|]+?) +\| ([^|]+?) +\|"
TABLE_HEAD = "| Item | Type | Action | Reason |"
# §8's tables: the contrast row `| n | `fg` on `bg` | role | dark | light | hc | verdict | pairs |`
# (2 decimals, 4 within 0.005 of a bar), the greyscale row and the colour-vision row.
CONTRAST_ROW_RE = (
    r"^\| (\d+) +\| `([a-z0-9.-]+)` on `([a-z0-9.-]+)` +\| ([a-z-]+) +\| ([\d.]+) +\| ([\d.]+) +\|"
    r" ([\d.]+) +\| ([^|]+?) +\| (registered|PROPOSED) +\|"
)
GREY_ROW_RE = r"^\| `([a-z0-9.-]+)` +\| (\d+) +\| (\d+) +\| (\d+) +\|"
CVD_ROW_RE = (
    r"`([a-z0-9.-]+)` vs `([a-z0-9.-]+)` +\| ([\d.]+) · ([\d.]+) · ([\d.]+) · ([\d.]+) +\|"
    r" ([^|\n]+?) +\|"
)
DECK_ROW_RE = r'^\| `([^`]+)` +\|([^|\n]*)\| ("[^|\n]*") +\|'
# Jargon and bare acknowledgements the copy deck (§9) never shows a user (its String column).
BANNED_COPY = (
    r"client-side",
    r"server-side",
    r"\bbackend\b",
    r"\bendpoint\b",
    r"\bschema_version\b",
    r"\b4\d\d\b",
    r'"OK"',
    r'"Yes"',
)
# The G-rows E15-S07 receives by hand-off (BQ-3 RULED) and the walkthrough's keyboard board.
HANDOFF_G = tuple(f"D09-G{i}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 13, 14))
WALK_MAX = 10
SUMMARY_MAX = 10
MARKER_RE = r"<!-- audit:([A-Za-z0-9_.-]+)=(\S+) -->"
MARKER_LOOSE_RE = r"<!--\s*audit:[^\n]*?(?:-->|$)"
NUMBER_BEFORE_RE = r"\(?(\d{1,3}(?:[,\u202f\u00a0]\d{3})+|\d[\d.:]*)\)?"
# key count — every marker key the spec carries and how many times at least (a marker deleted is a
# FAIL); a new marker may be added freely, then pinned here.
MARKER_TABLE = """
boards 1
light_twins 1
mutations 1
bq_rows 1
conditions 1
frames_drawn 1
frames_total 1
frames_not_drawn 1
states 1
fixture.export_layouts 1
fixture.export_panels 1
fixture.panels 1
fixture.layouts 1
fixture.dropped 1
fixture.unknown_kinds 1
fixture.remapped 1
fixture.app_format 1
fixture.newer_format 1
fixture.older_format 1
fixture.budget_panels 1
fixture.measured_ms 1
fixture.estimate_ms 1
contract.budget_ms 1
contract.size_mb 1
contract.parse_ms 1
contract.depth 1
contract.nodes 1
contract.layouts_max 1
contract.panes_max 1
contract.workspaces_max 1
contract.presets_max 1
contract.name_max 1
contract.symbol_max 1
contract.kind_max 1
contract.label_max 1
contract.dialog_lg_px 1
contract.dialog_md_px 1
design.key_cap 1
design.file_cap 1
"""
MARKERS = {k: int(n) for k, n in (ln.split() for ln in MARKER_TABLE.strip().splitlines())}


def rows(table: str, parts: int = -1) -> list[list[str]]:
    """Split a `|` table string; `parts` limits the split so a needle may carry its own pipes."""
    return [[c.strip() for c in ln.split("|", parts)] for ln in table.strip().splitlines()]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "MISSING"


def section(spec: str, a: int, b: int | None) -> str:
    """Section `## a.` up to `## b.` (or the end); empty when `## a.` is gone."""
    start = spec.find(f"\n## {a}.")
    if start < 0:
        return ""
    end = spec.find(f"\n## {b}.", start + 1) if b is not None else -1
    return spec[start : end if end > 0 else len(spec)]


def block(spec: str, head: str, nxt: str) -> str:
    """The text from the heading that starts with `head` to the next heading starting with `nxt`."""
    start = spec.find(head)
    if start < 0:
        return ""
    end = spec.find(nxt, start + len(head))
    return spec[start : end if end > 0 else len(spec)]


def placeholder(spec: str, n: int) -> bool:
    """Section n still carries its placeholder line (its content gates wait for its writer)."""
    return bool(re.search(rf"\*\*Placeholder \(§{n}\):\*\*", section(spec, n, n + 1)))


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def kind_table() -> dict[str, tuple[str, dict[str, str]]]:
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for name, kind, params in rows(KIND_TABLE):
        pairs = [p.split("=", 1) for p in params.split(";") if p]
        out[name] = (kind, {k: v for k, v in pairs})
    return out


KIND = kind_table()


def theme_tokens(name: str) -> dict[str, Any]:
    """prim + the theme's sets, exactly as `verify_tokens.py` layers them (`themes.json`)."""
    tokens: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    tokens.update(verify.merged_set(verify.THEMES[name]))
    return tokens


def resolve(tokens: dict[str, Any], name: str) -> str:
    entry = tokens.get(name)
    if not isinstance(entry, dict) or "$value" not in entry:
        return "MISSING"
    try:
        value = verify.resolve(entry["$value"], tokens)
    except (KeyError, ValueError):
        return "MISSING"
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def show(value: float) -> str:
    near = any(abs(value - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{value:.4f}" if near else f"{value:.2f}"


def luma(hex6: str) -> int:
    """Rec. 601 greyscale, floored (the greyscale strip)."""
    r, g, b = rgb(hex6)
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def split_clauses(text: str, seps: str = ";") -> list[str]:
    """Split on `seps` outside double-quoted copy and backtick code (a quoted sentence keeps its
    semicolons); every clause stripped, empty ones dropped."""
    out: list[str] = []
    buf: list[str] = []
    code = quote = False
    for ch in text:
        if code:
            code = ch != "`"
        elif quote:
            quote = ch != '"'
        elif ch == "`":
            code = True
        elif ch == '"':
            quote = True
        elif ch in seps:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf).strip())
    return [c for c in out if c]


def sentences(text: str) -> list[str]:
    """A line of prose or a table row as clauses: cells, then `;`, `. ` and ` — ` outside quotes
    and code."""
    out: list[str] = []
    for part in split_clauses(text, ";|"):
        for piece in re.split(r"(?<=[.!?]) (?=[A-Z`*(\[])| — ", part):
            if piece.strip():
                out.append(piece.strip())
    return out


def unquote(text: str) -> str:
    """The clause with its quoted copy blanked (a UI string never counts as a description)."""
    return re.sub(r'"[^"\n]*"', '""', text)


def hits(pattern: str, text: str) -> list[str]:
    """Every match of a vocabulary list in `text` that no negator within the window precedes."""
    out: list[str] = []
    for m in re.finditer(pattern, text):
        before = re.findall(r"[\w’']+", text[: m.start()].lower())[-NEGATION_WINDOW:]
        if not NEGATORS & set(before):
            out.append(m.group(0))
    return out


def exit_gated(clause: str) -> list[str]:
    """A3: a clause that names an exit and a non-negated gated-exit word (the exit is read in the
    raw clause, the gating words outside its quoted copy)."""
    if not re.search(EXIT_RE, clause):
        return []
    return hits(GATE_RE, unquote(clause))


def label_of(clause: str) -> str:
    if clause.startswith("Esc →"):
        return "Esc"
    m = re.match(r"(exits T1|T2|[a-z]+(?: [a-z]+)?): ", clause)
    return m.group(1) if m else ""


def labelled(shows: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in split_clauses(shows):
        out.setdefault(label_of(c), []).append(c)
    return out


def numbers(text: str) -> list[str]:
    """The numbers of a text, thousands separators dropped (`10,000` and `10 000` are 10000)."""
    found = re.findall(r"\d{1,3}(?:[,\u202f\u00a0]\d{3})+(?!\d)|\d+(?:\.\d+)?", text)
    return [re.sub(r"[,\u202f\u00a0]", "", n) for n in found]


def measure(themes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Section 1: every pair in three themes; section 3: greyscale and CVD (reported)."""
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    matrix: list[dict[str, Any]] = []
    fails = gated = proposed = 0
    for element, fg, bg, role in rows(PAIRS_TABLE):
        cells_ = {th: (resolve(themes[th], fg), resolve(themes[th], bg)) for th in THEMES}
        if any("MISSING" in pair for pair in cells_.values()):
            matrix.append(
                {"element": element, "fg": fg, "bg": bg, "role": role, "verdict": "MISSING"}
            )
            fails += 1
            continue
        ratios = {th: ratio(*cells_[th]) for th in THEMES}
        bars = BARS[role]
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        if bars is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            gated += 1
            ok = all(ratios[th] >= bar for th, bar in zip(THEMES, bars, strict=True))
            verdict = "PASS" if ok else "FAIL"
            fails += not ok
            proposed += reg == "PROPOSED"
        row: dict[str, Any] = {"element": element, "fg": fg, "bg": bg, "role": role}
        row.update({th: round(v, 4) for th, v in ratios.items()})
        row.update({"verdict": verdict, "pairs": reg})
        matrix.append(row)
    cvd_rows: list[dict[str, Any]] = []
    for name, a, b in rows(CVD_TABLE):
        ha, hb = resolve(themes["dark"], a), resolve(themes["dark"], b)
        d = [cvd.delta_e76(ha, hb)] + [
            cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k)) for k in DEFICIENCIES
        ]
        verdict = "distinct" if min(d) >= JND else "collapses — the word and the glyph carry it"
        cvd_rows.append({"pair": name, "a": a, "b": b, "dE76": [round(x, 1) for x in d]})
        cvd_rows[-1]["verdict"] = verdict
    grey = {t: {th: luma(resolve(themes[th], t)) for th in THEMES} for t in GREY_TOKENS}
    return {
        "matrix": matrix,
        "cvd": cvd_rows,
        "grey": grey,
        "pairs_rows": gated,
        "pairs_fail": fails,
        "pairs_registered": gated - proposed,
        "pairs_proposed": proposed,
    }


def contract_facts(t: dict[str, str], themes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every contract fact a frame quotes, parsed from the plan text; nothing is typed."""
    api, bl = t["22"], t["BL"]
    w_in = api[api.index("    WorkspaceInput:") : api.index("    Workspace:\n")]
    l_in = api[api.index("    LayoutInput:") : api.index("    Layout:\n")]
    bundle = api[api.index("    WorkspaceBundle:") : api.index("    OrderDiagnostics:")]
    kinds = api[api.index("    PaneKind:") :]
    kinds = kinds[: kinds.index("description")]
    export = api[api.index("operationId: exportWorkspace") :]
    export = export[: export.index("operationId:", 30)]
    create = api[api.index("operationId: createWorkspace") :]
    create = create[: create.index("operationId:", 30)]
    scr026 = t["14"][t["14"].index("### SCR-026") : t["14"].index("### SCR-027")]
    cmp043 = t["15"][t["15"].index("### CMP-043") : t["15"].index("### CMP-044")]
    sizes = re.search(r"at most (\d+) / (\d+) / (\d+) px wide", cmp043)

    def num(pattern: str, text: str) -> int:
        value = first(pattern, text)
        return int(value) if value.isdigit() else -1

    facts: dict[str, Any] = {
        "size_mb": num(r"size cap \(default (\d+) MB, rejected above\)", bl),
        "nodes": num(r"a document with (\d+) nested nodes", bl),
        "parse_ms": num(r"validates in <=(\d+) ms", scr026),
        "depth": num(r"JSON nesting depth must be at most (\d+);", w_in),
        "name_max": num(r"maxLength: (\d+)", w_in),
        "workspaces_max": num(r"`limit_reached` \((\d+) live workspaces\)", api),
        "layouts_max": num(r"`limit_reached` \((\d+) live layouts\)", api),
        "panes_max": num(r"panes:\n\s+type: array\n\s+minItems: 0\n\s+maxItems: (\d+)", l_in),
        "symbol_max": num(r"symbol of at most (\d+) characters", api),
        "kind_max": num(r"Every key must match `\^\[a-z\]\[a-z0-9_\]\{0,(\d+)\}\$`", api) + 1,
        "label_max": num(r"-- sanitised, 1\.\.(\d+) code points", t["21"]),
        "presets_max": num(r"refuses it whole beyond (\d+) items", bundle),
        "reason_max": num(r"One sentence, ≤ (\d+) characters", t["E09D09"]),
        "budget_ms": num(r"\| Frame time \| \*\*<(\d+) ms p95\*\*", t["C"]),
        "refresh_fps": num(r"\*\*(\d+) fps sustained\*\*", t["C"]),
        "dialog_px": [int(x) for x in sizes.groups()] if sizes else [],
        "pane_kinds": re.findall(r"^\s+(\w+),$", kinds, MULTI),
        "bundle_fields": re.findall(r"^        (\w+):", bundle, MULTI),
        "export_read": "x-rbac: { permissions: [workspaces:read], scope: self }" in export,
        "create_write": "x-rbac: { permissions: [workspaces:write], scope: self }" in create,
        "bundle_op_absent": "no operation takes a bundle yet" in bundle,
        "schema_version_string": "schema_version: { type: string }" in bundle,
        "verb": first(r'`workspaces:write` → "([^"]+)"', t["E09D09"]),
        "permission_template": first(r'\| `rbac\.permission` +\| "([^"]+)"', t["E09D09"]),
    }
    facts["permission_sentence"] = str(facts["permission_template"]).replace(
        "{verb}", str(facts["verb"])
    )
    facts["density_in_bundle"] = any("densit" in f for f in facts["bundle_fields"])
    facts["redline"] = {
        tok: resolve(themes["dark"], tok)
        for tok in BINDINGS
        if tok.split(".")[0] in ("space", "radius", "border", "opacity", "size")
    }
    return facts


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def fps(ms: float, facts: dict[str, Any]) -> int:
    """fps = min(display refresh, 1000 / ms), as E15-D03's cost confirm states it (D-11)."""
    return round(min(float(facts["refresh_fps"]), 1000 / ms))


def counts(facts: dict[str, Any]) -> dict[str, int]:
    """The preview's counts, derived from the fixture rows and `22`'s pane kinds."""
    kinds = set(facts["pane_kinds"])
    panels = sum(1 for r in PREVIEW_ROWS if r[1] in kinds and r[2] in ("Add", "Remap"))
    return {
        "panels": panels,
        "layouts": sum(1 for r in PREVIEW_ROWS if r[1] == "layout" and r[2] == "Add"),
        "dropped": sum(1 for r in PREVIEW_ROWS if r[2] == "Drop"),
        "remapped": sum(1 for r in PREVIEW_ROWS if r[2] == "Remap"),
        "unknown_kinds": sum(1 for r in PREVIEW_ROWS if r[3] == UNKNOWN_REASON),
        "rows": len(PREVIEW_ROWS),
    }


def variables(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per deck key, the fixture and contract values its template renders with."""
    fx, fm, c, bud = FIXTURE, FIXTURE["format"], counts(facts), FIXTURE["budget"]
    mine = {"panels": plural(c["panels"], "panel"), "layouts": plural(c["layouts"], "layout")}
    tally = {**mine, "dropped": c["dropped"], "remapped": c["remapped"], "clash": fx["clash"]}
    wall = {
        "panels": plural(bud["panels"], "panel"),
        "layouts": plural(bud["layouts"], "layout"),
        "layout": bud["layout"],
        "estimate": fx["estimate_ms"],
        "budget": facts["budget_ms"],
        "measured": fx["measured_ms"],
        "fps": fps(fx["measured_ms"], facts),
        "estfps": fps(fx["estimate_ms"], facts),
        "budgetfps": fps(facts["budget_ms"], facts),
    }
    return {
        "e15.export.done": {"workspace": fx["workspace"], "file": fx["export_file"]},
        "e15.import.help": {"size_mb": facts["size_mb"]},
        "e15.import.checking": {"file": fx["import_file"], "i": fx["step"][0], "n": fx["step"][1]},
        "e15.import.rejected.version_newer": {"file": fm["newer"], "app": fm["app"]},
        "e15.import.rejected.version_older": {"file": fm["older"], "floor": fm["floor"]},
        "e15.import.rejected.malformed": {"key": fx["malformed_key"]},
        "e15.import.rejected.parse": {"line": fx["parse_line"]},
        "e15.import.rejected.panes": {"n": fx["panes_in_file"], "max": facts["panes_max"]},
        "e15.import.rejected.layouts": {"n": fx["layouts_in_file"], "max": facts["layouts_max"]},
        "e15.import.rejected.presets": {"n": fx["presets_in_file"], "max": facts["presets_max"]},
        "e15.import.rejected.oversized": {"size": fx["oversized_mb"], "max": facts["size_mb"]},
        "e15.import.rejected.wrong_type": {"name": fx["wrong_file"]},
        "e15.import.rejected.depth": {"max": facts["depth"]},
        "e15.import.rejected.nodes": {"max": f"{facts['nodes']:,}"},
        "e15.import.refused.limit": {"max": facts["workspaces_max"]},
        "e15.import.refused.server": {"key": fx["server_key"]},
        "e15.import.migrated": {"from": fm["from"], "to": fm["to"]},
        "e15.import.clash": {"clash": fx["clash"], "workspace": fx["workspace"]},
        "e15.import.report.done": tally,
        "e15.import.caption": tally,
        "e15.import.report.caption": tally,
        "e15.import.caption_budget": wall,
        "e15.import.budget": wall,
        "layout.cost.import.title": wall,
        "layout.cost.import.body": wall,
    }


def render(key: str, facts: dict[str, Any]) -> str:
    return TEMPLATES[key].format(**variables(facts).get(key, {}))


def caps_clause(facts: dict[str, Any]) -> str:
    return (
        f"caps: names {facts['name_max']} · symbols {facts['symbol_max']} · panel kinds "
        f"{facts['kind_max']} · keys {DESIGN_CAPS['key_cap']} · file names "
        f"{DESIGN_CAPS['file_cap']} · drawing labels {facts['label_max']} (characters, an "
        "ellipsis past the cap, the whole value in the accessible name)"
    )


RENDERS = (
    "renders: every string from the file as text only — never markup, never a link, never "
    "interpreted"
)
TRUST = f'trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "{TRUST_NOTE}"'
STEPS_CLAUSE = (
    "steps: size → parse depth / node count → schema → version → per-pane registry → preview"
)
SERVER = (
    "server: the server re-checks size, depth, nodes, schema and version when the file is "
    "imported (E15-S07) — this check in the browser is a courtesy and never replaces it"
)
STATE_PRE = (
    "state: nothing created yet — no workspace, layout or pane exists until Import as new workspace"
)
STATE_NONE = (
    "state: nothing imported — no workspace, layout or pane was created and your workspaces are "
    "unchanged"
)
STATE_EXPORT = (
    "state: nothing exported — the save sheet closed unsaved, the preview stays as it was and no "
    "event fires"
)
IMPORT_VERB = "import verb: none — omitted, never T2-locked (AC 2)"
EXPORT_DIALOG = (
    'dialog: CMP-043 `size="md"` `role="dialog"` "Export Scalping", close × "Close Export Scalping"'
)
IMPORT_DIALOG = (
    'dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import '
    'workspace"'
)
ACTIONS_CLAUSE = (
    "actions: exactly three words in their own column, each after a decorative CMP-019 glyph — "
    "Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED) — never colour alone"
)
PICKER = (
    "picker: Choose file… — a real `<button>` (CMP-001 `secondary`) fronting the labelled native "
    '`<input type="file">` (CMP-067, `accept=".json,application/json"`, `multiple` false), whose '
    "`Enter` or `Space` opens the OS picker"
)
DROP_ZONE = (
    'drop zone: around Choose file…, the words "or drop a workspace file here" as the button\'s '
    "`aria-describedby` — not a Tab stop, no role and no name of its own, and a drop only adds to "
    "the input"
)
DRAG = {
    "accept": (
        'drop zone: drag-over — the words "Drop to check the file", the edge '
        "`color.border.selected` and the fill `color.surface.hover`, words and edge, never colour "
        "alone — not a Tab stop"
    ),
    "reject": (
        "drop zone: drag-over that cannot be taken (two files, or a type that is not JSON) — the "
        'words "Drop one .json file", the edge `color.border.default` — not a Tab stop'
    ),
}
LEGS = "legs: `rbac.view_as` → `rbac.permission` → `workspace.limit.count`"
COMPONENT = 'component: CMP-027 `inline`, `live="polite"`, above the still-live Choose file…'
COMPONENT_EXPORT = 'component: CMP-027 `inline`, `live="polite"`, in the dialog body'
DENSITY = (
    "density: compact — the table's rows at the compact `size.row.height` and the controls at "
    "`size.control.compact`, the dialog padding unchanged"
)
REASONS = {key: string for key, string, _ in rows(REASONS_TABLE)}


def reason_clause(key: str) -> str:
    return f'reason: `{key}` "{REASONS[key].format(user=FIXTURE["user"])}"'


def compares_clause(mode: str) -> str:
    fm = FIXTURE["format"]
    if mode == "newer":
        pair, what = (fm["newer"], fm["app"]), "the format version this app reads"
    elif mode == "older":
        pair, what = (fm["older"], fm["floor"]), "the oldest format version this app reads"
    else:
        pair, what = (fm["from"], fm["to"]), "the format version this app reads"
    return (
        f"compares: the file's `schema_version` ({pair[0]}) with {what} ({pair[1]}) — never an "
        "app version"
    )


def reflow_clause(dialog: str) -> str:
    r = FIXTURE["reflow"]
    head = (
        f"reflow: at {r['zoom']} % on {r['width']} {TIMES} {r['height']} the dialog fills the "
        f"viewport less {r['margin']} px a side, keeps its title and footer"
    )
    if dialog == "export":
        return head + " and scrolls its body, both lists in one column"
    return head + ", scrolls its body and reads the table one row element per record (`15:529`)"


def expected(
    name: str, kind: str, params: dict[str, str], facts: dict[str, Any]
) -> list[tuple[str, str, str]]:
    """The clauses a frame row must carry, whole, in the ladder's order: (label, clause, code)."""
    out: list[tuple[str, str, str]] = []

    def add(label: str, clause: str, code: str) -> None:
        out.append((label, clause, code))

    def q(*keys: str) -> str:
        return " · ".join(f'"{render(k, facts)}"' for k in keys)

    if kind in MENU_KINDS:
        if kind == "export-entry":
            add(
                "access",
                "access: Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's "
                "workspace menu — T1 for every session, Owner, Manager, Viewer and view-as alike, "
                "on a stored workspace: a read (`workspaces:read`), never T2 (§6)",
                "access",
            )
        elif kind == "availability":
            add(
                "availability",
                "availability: Export… on the viewer's unsaved default — "
                '`aria-disabled="true"`, its second line "This workspace isn\'t saved." '
                "(`ws.export.unstored`), no lock, no CMP-079, not T2 (§6)",
                "availability",
            )
        elif kind == "entry":
            add(
                "access",
                'access: Import… in "+" and in the rail\'s workspace menu — T1 for Owner and '
                f"Manager under {facts['workspaces_max']} workspaces: a write "
                "(`workspaces:write`) whose legs §6 states",
                "access",
            )
        else:
            key = params["key"]
            how = (
                "one notice — the item points at the SCR-124 banner"
                if key == "rbac.view_as"
                else "2a, the item's second line"
            )
            add(
                "T2",
                'T2: Import… in "+" and in the rail\'s workspace menu — the full label, the '
                'CMP-019 `lock` leading it, `aria-disabled="true"` (never `disabled`), CMP-079 '
                f"RbacGate, rendering {how} (§6)",
                "t2-lock",
            )
            add("reason", reason_clause(key), "t2-key")
            add("legs", LEGS, "legs")
        add("Esc", f"Esc → {ESC['menu']}", "esc")
        add("exits T1", f"exits T1: {EXITS['menu']}", "exits-t1")
        return out
    if kind in EXPORT_DIALOG_KINDS:
        add("dialog", EXPORT_DIALOG, "dialog")
    elif kind in IMPORT_DIALOG_KINDS:
        add("dialog", IMPORT_DIALOG, "dialog")
    elif kind == "budget-confirm":
        title = render("layout.cost.import.title", facts)
        add(
            "dialog",
            f'dialog: CMP-044 `role="alertdialog"` stacked over SCR-026, title "{title}"',
            "dialog",
        )
    if kind in TRUST_KINDS:
        add("trust", TRUST, "trust-note")
    out += content_clauses(name, kind, params, facts, q)
    if name in VERSION_FRAMES:
        add("compares", compares_clause(VERSION_FRAMES[name]), "version-field")
    if name in FILE_STRING_FRAMES:
        add("caps", caps_clause(facts), "caps")
        add("renders", RENDERS, "renders")
    footer = FOOTERS.get(name, FOOTERS.get(kind))
    if footer:
        add("footer", f"footer: {footer}", "footer")
    focus = FOCUS.get(name, FOCUS.get(kind))
    if focus:
        code = "rejection-focus" if kind in NOTHING_KINDS else "focus"
        add("initial focus", f"initial focus: {focus}", code)
    if kind in EXPORT_DIALOG_KINDS | IMPORT_DIALOG_KINDS | {"budget-confirm"}:
        add("Esc", f"Esc → {ESC.get(kind, ESC['dialog'])}", "esc")
        exits = EXITS.get(name, EXITS.get(kind, EXITS["dialog"]))
        add("exits T1", f"exits T1: {exits}", "exits-t1")
    return out


def content_clauses(
    name: str,
    kind: str,
    params: dict[str, str],
    facts: dict[str, Any],
    q: Callable[..., str],
) -> list[tuple[str, str, str]]:
    """The kind's own clauses between the trust note and the caps (see `expected`)."""
    out: list[tuple[str, str, str]] = []

    def add(label: str, clause: str, code: str) -> None:
        out.append((label, clause, code))

    if kind == "export-busy":
        add(
            "busy",
            'busy: "Preparing the file…" — CMP-038 with `aria-busy="true"` on the body, a load, '
            "so Cancel stays",
            "busy",
        )
    elif kind == "export-preview":
        add(
            "included",
            "included: a CMP-036 list built from the fetched bundle, one item per clause — "
            f'"{INCLUDED}"',
            "included",
        )
        add(
            "excluded",
            f'excluded: a CMP-036 list, first-class, one item per clause — "{EXCLUDED}"',
            "excluded",
        )
        add("caveat", f'caveat: "{CAVEAT}"', "caveat")
    elif kind == "export-failed":
        add("component", COMPONENT_EXPORT, "component")
        add("message", f"message: {q('e15.export.failed')}", "message")
        add("live", "live: polite, once", "live")
    elif kind == "export-done":
        add(
            "done",
            f"done: CMP-028 `success` {q('e15.export.done')} — the file name in `type.num.sm`, "
            "selectable",
            "done",
        )
        add(
            "excluded",
            f'excluded: a CMP-036 list, first-class, one item per clause — "{EXCLUDED}"',
            "excluded",
        )
        add(
            "event",
            "event: `workspace.exported{panelCount, schemaVersion}` fires once the file is "
            "saved, never on Download file pressed",
            "event",
        )
        add("live", "live: polite, once — the completion line", "live")
    elif kind == "export-cancelled":
        add("state", STATE_EXPORT, "state")
    elif kind == "pick":
        add("picker", PICKER, "picker")
        add("drop zone", DROP_ZONE, "drop-zone")
        add("help", f"help: {q('e15.import.help')}", "help")
    elif kind == "drag-over":
        add("drop zone", DRAG[params["zone"]], "drop-zone")
    elif kind == "validating":
        add(
            "progress",
            f"progress: CMP-023 determinate, `valueText` {q('e15.import.checking')}",
            "progress",
        )
        add("steps", STEPS_CLAUSE, "steps")
        add("server", SERVER, "server-recheck")
        add("state", STATE_PRE, "created-early")
        add("live", "live: polite, once at the start and once at the end, never per step", "live")
    elif kind == "preview":
        variant = params["variant"]
        if variant == "budget":
            add(
                "table",
                "table: CMP-049 table mode, §4.2's columns and order for `wall.json`, caption "
                f"{q('e15.import.caption_budget')}",
                "table",
            )
            add(
                "budget",
                f"budget: CMP-028 `warning` {q('e15.import.budget')} above the table",
                "budget",
            )
        else:
            add(
                "table",
                f"table: CMP-049 table mode with §4.2's rows, caption {q('e15.import.caption')}",
                "table",
            )
        add("actions", ACTIONS_CLAUSE, "actions")
        if variant == "main":
            add("clash", f"clash: {q('e15.import.clash')}", "clash")
        if variant == "migrated":
            add(
                "migrated",
                f"migrated: CMP-028 `info` {q('e15.import.migrated')} above the table",
                "migrated",
            )
        add("state", STATE_PRE, "created-early")
    elif kind == "budget-confirm":
        add("body", f"body: {q('layout.cost.import.body')}", "budget")
        add(
            "event",
            "event: Cancel fires `layout.import_rejected{reason: budget-exceeded}` and returns to "
            "the preview",
            "event",
        )
    elif kind == "busy":
        add(
            "busy",
            'busy: Import as new workspace keeps its label with `aria-busy="true"` — the file is '
            "sent once, and Close or `Esc` closes the view only",
            "busy",
        )
    elif kind == "t2-leg":
        add(
            "T2",
            "T2: Import as new workspace, in place — the full label, the CMP-019 `lock` leading "
            'it, `aria-disabled="true"` (never `disabled`), CMP-079 RbacGate, rendering 2a, under '
            "the button (§6)",
            "t2-lock",
        )
        add("reason", reason_clause(params["key"]), "t2-key")
        add("legs", LEGS, "legs")
    elif kind in NOTHING_KINDS:
        reason = params["reason"]
        add("component", COMPONENT, "component")
        add("message", f"message: {q(*MESSAGES[reason])}", "message")
        if reason in VARIANTS:
            add("variants", f"variants: {q(*VARIANTS[reason])}", "message")
        add("state", STATE_NONE, "partial")
        add("import verb", IMPORT_VERB, "import-verb")
        if reason in EVENT_REASON:
            add(
                "event",
                f"event: `layout.import_rejected{{reason: {EVENT_REASON[reason]}}}`, once",
                "event",
            )
        add("live", "live: polite, once", "live")
    elif kind == "report":
        add(
            "region",
            'region: the dialog\'s final step, `role="region"` named "Import report", its '
            'heading `tabindex="-1"` focused on arrival, every line selectable',
            "report-region",
        )
        add("success", f"success: CMP-028 `success` {q('e15.import.report.done')}", "report-line")
        add(
            "table",
            f"table: CMP-049 table mode with §4.3's rows, caption {q('e15.import.report.caption')}",
            "table",
        )
        add("actions", ACTIONS_CLAUSE, "actions")
        add(
            "copy",
            "copy: Copy report (CMP-033) puts the report's lines on the clipboard as plain text "
            'and announces "Copied"',
            "report-copy",
        )
        add(
            "persists",
            'persists: until Close — never a toast (CMP-045), never `role="status"`',
            "report-region",
        )
        add(
            "event",
            "event: `layout.imported{panelCount, droppedCount, remappedCount, schemaVersion}`, "
            "once the workspace exists",
            "event",
        )
        add("live", "live: polite, once — the success line", "live")
    elif kind == "cancelled":
        add("state", STATE_NONE, "partial")
    elif kind == "reflow":
        add("reflow", reflow_clause(params["dialog"]), "reflow")
    elif kind == "compact":
        add("density", DENSITY, "density")
    return out


READ: dict[Path, str] = {}


def read_once(path: Path) -> str:
    if path not in READ:
        READ[path] = path.read_text(encoding="utf-8")
    return READ[path]


def fail(code: str, msg: str) -> str:
    """A FAIL line led by its gate code; `--self-test` checks every code has a mutation."""
    return f"[{code}] {msg}"


def frame_rows(spec: str) -> list[tuple[str, list[str], str]]:
    """(frame, cells, the whole line) for every frame row of §2-§5."""
    out = []
    for m in re.finditer(FRAME_RE, section(spec, 2, 6), MULTI):
        c = cells(m.group(0))
        out.append((c[0].strip("`"), c, m.group(0)))
    return out


def footer_items(clause: str) -> list[tuple[str, str]]:
    out = []
    for item in [i.strip() for i in clause.removeprefix("footer:").split(" · ") if i.strip()]:
        m = re.match(r"(.+?)\s*(?:\((.*)\))?$", item)
        out.append(((m.group(1) if m else item).strip(), (m.group(2) or "") if m else ""))
    return out


def board_cell_ok(board: str) -> bool:
    nums = re.findall(r"\d\d", board)
    return bool(re.fullmatch(r"\d\d(?:, \d\d)*", board)) and all(
        1 <= int(n) <= BOARD_CAP for n in nums
    )


def excluded_problem(line: str, frame: bool) -> bool:
    """S1: every "Never included" is the ruled sentence, byte for byte (outside a frame row,
    E15-D02's own sentence may be quoted, a C-row)."""
    for m in re.finditer(r"(?i)never included", line):
        rest = line[m.start() :]
        if not (rest.startswith(EXCLUDED) or (not frame and rest.startswith(D02_EXCLUDED))):
            return True
    return False


def trust_problem(line: str) -> bool:
    """BQ-2: every "A workspace file never carries" is the trust note, byte for byte."""
    return any(
        not line[m.start() :].startswith(TRUST_NOTE)
        for m in re.finditer(r"(?i)a workspace file never carries", line)
    )


def vocabulary_gate(where: str, text: str, frame: bool) -> str | None:
    """The checks every ladder runs first: the sharing claim (S2), a foreign account (S3), the
    Excluded sentence (S1) and the trust note, byte for byte."""
    if re.search(SHARE_RE, text):
        return fail("share-claim", f"{where}: the sharing claim is written (BQ-2 RULED: never)")
    for acct in FIXTURE["foreign_accounts"]:
        if acct.lower() in text.lower():
            return fail("foreign-account", f"{where}: names an account the importer cannot see")
    if excluded_problem(text, frame):
        return fail(
            "excluded", f"{where}: the Excluded sentence is not the ruled one, byte for byte"
        )
    if trust_problem(text):
        return fail("trust-note", f"{where}: the trust note is not E15-D02's, byte for byte")
    return None


def prose_checks(
    clauses: list[str], where: str, import_scope: bool, facts: dict[str, Any]
) -> str | None:
    """The clause checks every ladder shares, on quoted-copy-free clauses: an account binding
    remapped (S4), the check steps or the T2 legs out of order in an arrow chain (S9, S17), an app
    version compared (S8), a limit in prose that is not the tool's (S18) and, on an import
    surface, an account named (S3)."""
    for clause in clauses:
        if hits(REMAP_RE, clause) and re.search(ACCOUNT_RE, clause):
            return fail("account-remap", f"{where}: an account binding remapped (BQ-3: dropped)")
        if "→" in clause:
            at = [m.start() for w in STEPS if (m := re.search(rf"(?i)\b{w}\b", clause))]
            if len(at) == len(STEPS) and at != sorted(at):
                return fail("steps", f"{where}: the check steps out of order: {clause[:60]!r}")
            view_as, perm = clause.find("`rbac.view_as`"), clause.find("`rbac.permission`")
            if view_as >= 0 and perm >= 0 and perm < view_as:
                return fail("legs-order", f"{where}: view-as is not the first leg: {clause[:60]!r}")
        if re.search(DROP_RE, clause) and hits(TAB_STOP_RE, clause):
            return fail("drop-zone", f"{where}: the drop zone made a Tab stop: {clause[:60]!r}")
        if re.search(r"(?i)\bcompar", clause) and hits(APP_VERSION_RE, clause):
            return fail("version-field", f"{where}: an app version compared, not `schema_version`")
        for m in re.finditer(LIMIT_PHRASE_RE, clause):
            fact = facts.get(LIMIT_UNITS[m.group(2).lower()])
            if fact is not None and re.sub(r",", "", m.group(1)) != str(fact):
                return fail("limit-number", f"{where}: {m.group(0)!r} is not the tool's {fact}")
        if import_scope and re.search(FOREIGN_RE, clause):
            return fail("foreign-account", f"{where}: names an account the importer cannot see")
    return None


def frame_gate(name: str, c: list[str], facts: dict[str, Any], deck: set[str] | None) -> str | None:
    """The FRAME ladder: the first FAIL of one frame row, its obligations from KIND."""
    if len(c) != 6:
        return fail("cells", f"frame {name}: {len(c)} cells, six expected")
    kind, params = KIND[name]
    producer, shows, cls, keys, board = c[1], c[2], c[3], c[4], c[5]
    if cls != CLASS[kind]:
        return fail("class", f"frame {name}: Class {cls!r}, the tool's KIND says {CLASS[kind]!r}")
    if board != NOT_DRAWN and not board_cell_ok(board):
        return fail("board-cell", f"frame {name} without a board or the not-drawn cell")
    for key in re.findall(r"`([^`]+)`", keys):
        if not re.fullmatch(COPY_KEY_RE, key):
            return fail("key-namespace", f"copy key outside the namespaces in {name}: {key}")
    found = vocabulary_gate(f"frame {name}", " | ".join(c), frame=True)
    if found:
        return found
    clauses = split_clauses(producer) + split_clauses(shows)
    for clause in clauses:
        if label_of(clause) == "footer":
            for label, note in footer_items(clause):
                if re.fullmatch(EXIT_RE, label) and hits(GATE_RE, note):
                    return fail("exit-gated", f"exit {label} drawn gated in the footer of {name}")
            continue
        gated = exit_gated(clause)
        if gated:
            return fail("exit-gated", f"exit drawn gated in {name} ({gated[0]!r}): {clause[:60]!r}")
    plain = unquote(producer + " ; " + shows)
    if name.startswith("SCR-026/"):
        text = plain
        for allowed in ENV_ALLOWED:
            text = text.replace(allowed, "")
        if hits(ENV_RE, text):
            return fail("env", f"frame {name}: an environment travels into an import")
    rest = split_clauses(shows)
    if name.startswith("SCR-025/"):
        open_ = [
            unquote(x) for x in split_clauses(producer) + rest if label_of(x) != "availability"
        ]
        if any(hits(LOCK_RE, x) for x in open_):
            return fail("export-gated", f"Export… drawn gated in {name} (a read, never T2)")
    found = rejection_gate(name, kind, shows)
    if found:
        return found
    found = prose_checks(
        [unquote(x) for x in rest], f"frame {name}", name.startswith("SCR-026/"), facts
    )
    if found:
        return found
    if name.startswith("SCR-026/") and any(
        hits(MARKUP_RE, unquote(x)) for x in rest if label_of(x) != "renders"
    ):
        return fail("untrusted-markup", f"frame {name}: a file string rendered as markup")
    if kind in PRE_SEND_KINDS and any(
        hits(CREATE_RE, unquote(x)) for x in rest if label_of(x) != "state"
    ):
        return fail("created-early", f"frame {name}: something exists before the send")
    lab = labelled(shows)
    locked = any(hits("(?i)" + LOCK_WORDS, unquote(x)) for x in rest)
    if kind not in T2_KINDS and ({"T2", "legs", "reason"} & set(lab) or locked):
        return fail("t2-over", f"frame {name} is not T2 (over-conversion; validity is no lock)")
    found = clause_gate(name, kind, params, facts, lab)
    if found:
        return found
    if deck is not None:
        for key in re.findall(r"`([^`]+)`", keys):
            if key not in deck:
                return fail("key-deck", f"copy key not in the deck (§9) in {name}: {key}")
    return None


def rejection_gate(name: str, kind: str, shows: str) -> str | None:
    """S6 and S5: a rejection or refusal carries no lock and no Import verb (AC 2)."""
    if kind not in NOTHING_KINDS:
        return None
    rest = [x for x in split_clauses(shows) if label_of(x) != "import verb"]
    if any(hits(LOCK_RE, unquote(x)) for x in rest):
        return fail("rejection-lock", f"rejection {name} drawn locked or T2 (an outcome, never T2)")
    for x in rest:
        if label_of(x) == "footer":
            if any(re.search(r"(?i)\bimport\b|\bapply\b", lab) for lab, _ in footer_items(x)):
                return fail("import-verb", f"rejection {name} offers an Import verb (AC 2)")
        elif hits(IMPORT_VERB_RE, unquote(x)):
            return fail("import-verb", f"rejection {name} offers an Import verb (AC 2)")
    return None


NUMBER_LABELS = ("message", "variants", "help", "budget", "body", "table")


def clause_gate(
    name: str, kind: str, params: dict[str, str], facts: dict[str, Any], lab: dict[str, list[str]]
) -> str | None:
    """Whole clauses: every labelled clause of the kind once, equal to the tool's; a number that
    differs is named as such (S7 versions, S18 limits, the counts)."""
    for label, want, code in expected(name, kind, params, facts):
        have = lab.get(label, [])
        if not have:
            return fail(code, f"frame {name} lacks its {label!r} clause")
        if len(have) > 1:
            return fail(code, f"frame {name} carries its {label!r} clause twice")
        got = have[0]
        if got == want:
            continue
        if label in NUMBER_LABELS and numbers(got) != numbers(want):
            if name in VERSION_FRAMES:
                return fail("versions", f"frame {name}: the versions differ from the fixture's")
            if label == "table":
                return fail("count", f"frame {name}: the caption's counts differ from the tool's")
            return fail(
                "limit-number", f"frame {name}: a number its {label} quotes is not --json's"
            )
        if label == "legs":
            got_k, want_k = re.findall(r"`([a-z_.]+)`", got), re.findall(r"`([a-z_.]+)`", want)
            if sorted(got_k) == sorted(want_k):
                return fail("legs-order", f"view-as leg not first in {name}: {' → '.join(got_k)}")
        return fail(code, f"frame {name}: its {label!r} clause is not the tool's: {want[:90]!r}")
    return None


def frame_gates(spec: str, facts: dict[str, Any], deck: set[str] | None) -> list[str]:
    """Every frame row through the FRAME ladder, then the inventory both ways."""
    bad: list[str] = []
    seen: dict[str, int] = {}
    for name, c, _ in frame_rows(spec):
        seen[name] = seen.get(name, 0) + 1
        if name not in KIND:
            continue
        found = frame_gate(name, c, facts, deck)
        if found:
            bad.append(found)
    extra = sorted(n for n in seen if n not in KIND)
    twice = sorted(n for n, k in seen.items() if k > 1)
    missing = sorted(n for n in KIND if n not in seen)
    if extra or twice or missing:
        bad.append(
            fail(
                "inventory",
                f"frame rows and the tool's inventory differ: unknown {extra}, twice {twice}, "
                f"missing {missing}",
            )
        )
    return bad


def table_lines(spec: str, head: str) -> list[str]:
    return re.findall(r"^\|.*\|$", block(spec, head, "\n### "), MULTI)


def table_gate(spec: str, head: str, report: bool) -> str | None:
    """The TABLE ladder for §4.2 (the preview) or §4.3 (the report): the header, then each row
    against the fixture; the first FAIL of the table."""
    where = "§4.3 (the report)" if report else "§4.2 (the preview)"
    lines = table_lines(spec, head)
    if not lines:
        return fail("preview-columns", f"{where} has no table")
    if re.sub(r" +", " ", lines[0]) != TABLE_HEAD:
        return fail("preview-columns", f"{where}: the columns are not {TABLE_HEAD}")
    body = lines[2:]
    for i, line in enumerate(body):
        found = vocabulary_gate(f"{where} row {i + 1}", line, frame=False)
        if found:
            return found
        got = tuple(cells(line))
        want = PREVIEW_ROWS[i] if i < len(PREVIEW_ROWS) else None
        if got == want:
            continue
        if report:
            return fail("report-repeat", f"{where} row {i + 1} is not §4.2's row (AC 3, AC 4)")
        if want and len(got) == 4 and got[2] == "Remap" and want[3] == ACCOUNT_REASON:
            return fail("account-remap", f"{where}: the account row is remapped (BQ-3: dropped)")
        if want and want[3] == UNKNOWN_REASON and len(got) == 4 and got[3] != UNKNOWN_REASON:
            return fail("unknown-kind", f"{where}: an unknown kind lost {UNKNOWN_REASON!r}")
        if len(got) == 4 and got[2] not in ACTIONS:
            return fail("preview-action", f"{where} row {i + 1}: the Action is not one word")
        if got in PREVIEW_ROWS:
            return fail("preview-order", f"{where}: drops and remaps first, additions after")
        return fail("preview-row", f"{where} row {i + 1} is not the fixture's")
    if len(body) != len(PREVIEW_ROWS):
        code = "report-repeat" if report else "preview-row"
        return fail(code, f"{where}: {len(body)} rows, the fixture has {len(PREVIEW_ROWS)}")
    return None


def board_gates(spec: str) -> tuple[list[str], dict[str, Any]]:
    """§0: the cap, the light twins, the exports and the reconciliation with the frame rows."""
    bad: list[str] = []
    s0 = section(spec, 0, 1)
    boards = re.findall(BOARD_RE, s0, MULTI)
    named: dict[str, set[str]] = {}
    light = 0
    for num, title, num2, rest in boards:
        c = cells("|" + rest)
        slug = title.split(" ", 3)[-1]
        light += slug.endswith("-light")
        if num != num2:
            bad.append(fail("board-name", f"§0 board {num}: its name carries {num2}"))
        if len(c) < 4:
            bad.append(fail("board-cells", f"§0 board {num}: fewer than four cells after its name"))
            continue
        draws, theme, export, status = c[0], c[1], c[2], c[3]
        if slug.endswith("-light") != (theme == "light"):
            bad.append(fail("board-theme", f"§0 board {num}: its slug and its theme disagree"))
        if export != f"`docs/design/E15/img/E15-D09-{num}-{slug}.png`":
            bad.append(fail("board-export", f"§0 board {num}: export path {export} not its name"))
        if status != "pending":
            bad.append(fail("board-status", f"§0 board {num}: status {status!r} (text-first)"))
        frames = set(re.findall(FRAME_NAME_RE, draws))
        for f in sorted(frames - set(KIND)):
            bad.append(fail("board-unknown", f"§0 board {num} names an unknown frame {f}"))
        for f in frames:
            named.setdefault(f, set()).add(num)
        if not frames and num not in TABLE_BOARDS:
            bad.append(fail("board-empty", f"§0 board {num} draws no frame"))
    if len(boards) > BOARD_CAP or light * 3 > len(boards):
        bad.append(fail("board-cap", f"§0 cap broken: {len(boards)} boards, {light} light twins"))
    nd_line = first(r"\*\*Not drawn — the text is binding; drawn on request\*\*([^\n]*)", s0)
    not_drawn = set(re.findall(FRAME_NAME_RE, nd_line))
    for name, c, _ in frame_rows(spec):
        if len(c) != 6 or name not in KIND or (c[5] != NOT_DRAWN and not board_cell_ok(c[5])):
            continue
        mine = set(re.findall(r"\d\d", c[5])) if c[5] != NOT_DRAWN else set()
        if mine != named.get(name, set()):
            bad.append(
                fail(
                    "board-reconcile",
                    f"frame {name}: its row says boards {sorted(mine)}, "
                    f"§0 says {sorted(named.get(name, set()))}",
                )
            )
        if (c[5] == NOT_DRAWN) != (name in not_drawn):
            bad.append(
                fail("not-drawn", f"frame {name}: its cell and §0's not-drawn line disagree")
            )
    for f in sorted(not_drawn - set(KIND)):
        bad.append(fail("not-drawn-unknown", f"§0's not-drawn line names an unknown frame {f}"))
    return bad, {"boards": len(boards), "light_twins": light}


def head_gates(spec: str) -> tuple[list[str], dict[str, int]]:
    """The header, the deviations, the AC trace, the ruled questions and conditions, A3."""
    bad: list[str] = []
    head = spec[: spec.find("\n## ")]
    bad += [
        fail("head-sha", f"header: merge sha missing: {s[:9]}") for s in MERGE_SHAS if s not in head
    ]
    if BASE not in head:
        bad.append(fail("head-base", "header: the base sha is missing"))
    if PENPOT_PAGE not in head:
        bad.append(fail("head-penpot", "header: the Penpot page name is missing"))
    bad += [
        fail("head-status", f"header: status lost {w!r}") for w in STATUS_WORDS if w not in head
    ]
    devs = [ln for ln in head.split("\n") if ln.startswith("- **Deviation — ")]
    for dev, words in DEVIATIONS.items():
        if not any(words in ln for ln in devs):
            bad.append(fail("deviation", f"deviation missing: {dev} ({words})"))
    trace = block(spec, "## Acceptance-criteria trace", "\n## ")
    found = {
        m.group(1): m.group(0) for m in re.finditer(r"^\| ((?:AC|DL|DoD)-\d+) +\|.*$", trace, MULTI)
    }
    ids = re.findall(r"^\| ((?:AC|DL|DoD)-\d+) +\|", trace, MULTI)
    bad += [fail("trace-lacks", f"AC trace lacks {i}") for i in AC_IDS if i not in ids]
    bad += [
        fail("trace-repeats", f"AC trace repeats {i}") for i in sorted(set(ids)) if ids.count(i) > 1
    ]
    for i, row in found.items():
        if cells(row)[-1] not in TRACE_STATUS:
            bad.append(fail("trace-status", f"AC trace {i}: status not one of {TRACE_STATUS}"))
    if not re.search(PLACEHOLDER_RE, spec):
        bad += [
            fail("trace-pending", f"AC trace {i} still says text pending, and no section does")
            for i, row in found.items()
            if cells(row)[-1] == "text pending"
        ]
    bqs = block(spec, "## The questions", "\n## ")
    bq = {m.group(1): m.group(0) for m in re.finditer(r"^\| (BQ-\d+) +\|.*$", bqs, MULTI)}
    for i in range(1, 17):
        bq_row = bq.get(f"BQ-{i}")
        if bq_row is None:
            bad.append(fail("bq-missing", f"BQ-{i} missing from the questions table"))
        elif f"RULED ({RULING})" not in cells(bq_row)[-1]:
            bad.append(fail("bq-ruled", f"BQ-{i} not RULED ({RULING})"))
    for qid, terms in BQ_TERMS.items():
        if qid in bq and any(t not in bq[qid] for t in terms):
            bad.append(fail("bq-terms", f"{qid} row lost its ruled outcome ({' / '.join(terms)})"))
    conds = {m.group(1): m.group(0) for m in re.finditer(r"^\| (Condition \d) +\|.*$", bqs, MULTI)}
    for cid, terms in CONDITION_TERMS.items():
        c_row = conds.get(cid)
        if c_row is None or any(t not in c_row for t in terms) or "RULED" not in cells(c_row)[-1]:
            bad.append(fail("condition", f"{cid} missing or lost its ruled terms"))
    if A3_STANDING not in spec[: spec.find("\n## 0. ")]:
        bad.append(fail("standing", "the standing additions lost A3: the exits are never gated"))
    return bad, {"bq_rows": len(bq), "ac_rows": len(ids), "conditions": len(conds)}


NEEDLES: dict[
    tuple[int, ...], tuple[list[str], list[str], set[tuple[str, int]], dict[str, int]]
] = {}


def needle_gates(
    t: dict[str, str],
) -> tuple[list[str], list[str], set[tuple[str, int]], dict[str, int]]:
    """The CITED_TABLE needles against the plan texts, computed once per set of texts."""
    key = tuple(hash(v) for v in t.values())
    if key not in NEEDLES:
        bad: list[str] = []
        warns: list[str] = []
        lines = {k: v.split("\n") for k, v in t.items()}
        pinned: set[tuple[str, int]] = set()
        for doc, line_s, want in rows(CITED_TABLE, 2):
            line, doc_lines = int(line_s), lines[doc]
            pinned.add((doc, line))
            shift = sum(POINTER in ln for ln in doc_lines[: line - 1]) if doc == "14" else 0
            total = t[doc].count(want)
            at = [i + 1 for i, ln in enumerate(doc_lines) if want in ln]
            if total == 0:
                bad.append(fail("cite-gone", f"cited text gone: `{doc}:{line}` {want[:40]!r}"))
            elif total > 1:
                bad.append(
                    fail("cite-ambiguous", f"cited text twice: `{doc}:{line}` {want[:40]!r}")
                )
            elif at[0] not in (line, line + shift):
                warns.append(f"`{doc}:{line}` now at :{at[0]} ({want[:40]!r})")
        NEEDLES[key] = (bad, warns, pinned, {k: len(v) for k, v in lines.items()})
    bad, warns, pinned, lengths = NEEDLES[key]
    return list(bad), list(warns), set(pinned), lengths


def cite_gates(spec: str, t: dict[str, str]) -> tuple[list[str], dict[str, int]]:
    """Each needle once in its file, at its line (`14`: as many lines lower as there are pointer
    lines above it, a WARN otherwise); every cite in the spec has a needle; a range's end lies
    after its start and inside its file."""
    bad, warns, pinned, lengths = needle_gates(t)
    CITE_WARN[:] = warns
    found = list(re.finditer(CITE_RE, spec))
    used = [(m.group(1), int(m.group(2))) for m in found]
    for doc, line in sorted(set(used) - pinned):
        bad.append(
            fail("cite-unpinned", f"cite not pinned in the tool's CITED_TABLE: `{doc}:{line}`")
        )
    for m in found:
        if m.group(3) and not int(m.group(2)) < int(m.group(3)) <= lengths[m.group(1)]:
            bad.append(fail("cite-range", f"cite range {m.group(0)} ends outside its file"))
    return bad, {"cites_pinned": len(pinned), "cites_used": len(set(used))}


def pointer_runs(lines: list[str]) -> list[list[int]] | None:
    """For each checklist line of POINTER_AFTER, the run of pointer lines right after it."""
    runs: list[list[int]] = []
    for tail in POINTER_AFTER:
        idx = [i for i, ln in enumerate(lines) if ln.endswith(tail)]
        if len(idx) != 1:
            return None
        j, run = idx[0] + 1, []
        while j < len(lines) and lines[j].startswith("- **") and "](../design/" in lines[j]:
            run.append(j)
            j += 1
        runs.append(run)
    return runs


def text_gates(spec: str, t: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """Reasons, upstream copy, the `14` pointer lines, placeholders, the repository-wide rules."""
    bad: list[str] = []
    for key, string, doc in rows(REASONS_TABLE):
        if f'"{string}"' not in t[doc]:
            bad.append(fail("reason-drift", f"reason string drifted from {doc}: {key} {string!r}"))
        if len(string) > facts["reason_max"] or not string.endswith("."):
            bad.append(fail("reason-form", f"reason {key}: too long or no full stop"))
    if facts["permission_sentence"] != REASONS["rbac.permission"]:
        bad.append(fail("reason-drift", "E09-D09's template and verb no longer give the reason"))
    for string, doc in UPSTREAM_TABLE:
        if string not in t[doc]:
            bad.append(fail("upstream-gone", f"upstream string gone from {doc}: {string[:50]!r}"))
    plan14 = t["14"].split("\n")
    at = [i for i, ln in enumerate(plan14) if POINTER in ln]
    runs = pointer_runs(plan14)
    if runs is None or len(at) != 2 or at[0] not in runs[0] or at[1] not in runs[1]:
        bad.append(
            fail(
                "pointer-14",
                f"`14` pointer lines at {[i + 1 for i in at]}, not after the checklists",
            )
        )
    for n, text in re.findall(PLACEHOLDER_RE, spec):
        bad.append(fail("placeholder", f"placeholder §{n} still in the spec: {text[:70]}"))
    constitution = t["C"]
    pointer_lines = "\n".join(plan14[i] for i in at)
    for label, txt in (("spec", spec), ("tool", read_once(TOOL)), ("14", pointer_lines)):
        bad += [
            fail("forbidden", f"{label}: forbidden text {p}")
            for p in FORBIDDEN
            if re.search(p, txt)
        ]
        if label == "tool":
            continue
        if re.search(CLOSING, txt, re.IGNORECASE):
            bad.append(fail("closing", f"{label}: a closing keyword (text-first: Refs + Partial)"))
        if label == "14" and (re.search(SHARE_RE, txt) or excluded_problem(txt, frame=True)):
            bad.append(
                fail("share-claim", "`14` pointer lines: the sharing claim or a changed sentence")
            )
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if not re.search(rf"^\*\*{re.escape(r)}\b", constitution, MULTI):
                bad.append(fail("rule-id", f"{label}: dangling rule id {r}"))
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(fail("catalogue-id", f"{label}: no catalogue heading for {c}"))
    return bad


NUMERIC_FACTS = (
    "size_mb",
    "nodes",
    "parse_ms",
    "depth",
    "name_max",
    "workspaces_max",
    "layouts_max",
    "panes_max",
    "symbol_max",
    "kind_max",
    "label_max",
    "presets_max",
    "reason_max",
    "budget_ms",
    "refresh_fps",
)


def contract_gates(facts: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for fact in ("export_read", "create_write", "bundle_op_absent", "schema_version_string"):
        if not facts[fact]:
            bad.append(fail("contract-fact", f"contract fact changed: {fact}"))
    if facts["density_in_bundle"]:
        bad.append(
            fail("contract-fact", "`22` WorkspaceBundle now carries a density: see the C-row")
        )
    for fact in NUMERIC_FACTS:
        if int(facts[fact]) <= 0:
            bad.append(fail("contract-fact", f"contract fact no longer parses: {fact}"))
    return bad


def line_sections(spec: str) -> list[int]:
    """The `## n.` section of each line (-1 before §0)."""
    out, current = [], -1
    for ln in spec.split("\n"):
        m = re.match(r"## (\d+)\. ", ln)
        if m:
            current = int(m.group(1))
        out.append(current)
    return out


def table_indices(spec: str) -> set[int]:
    """The line numbers (0-based) of §4.2's and §4.3's table rows (the TABLE ladder's)."""
    out: set[int] = set()
    lines = spec.split("\n")
    for head in ("### 4.2 ", "### 4.3 "):
        start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
        if start is None:
            continue
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("#"):
                break
            if lines[i].startswith("|"):
                out.add(i)
    return out


def line_gate(line: str, sec: int, facts: dict[str, Any]) -> str | None:
    """The LINE ladder: one line of prose or a non-frame table row, whole clauses."""
    found = vocabulary_gate(f"§{sec} line {line[:40]!r}", line, frame=False)
    if found:
        return found
    for clause in sentences(line):
        gated = exit_gated(clause)
        if gated:
            return fail("exit-gated", f"exit drawn gated in §{sec} ({gated[0]!r}): {clause[:60]!r}")
    if sec in (3, 4, 5):
        text = unquote(line)
        for allowed in ENV_ALLOWED:
            text = text.replace(allowed, "")
        if hits(ENV_RE, text):
            return fail("env", f"§{sec}: an environment travels into an import: {line[:60]!r}")
        if any(hits(MARKUP_RE, unquote(x)) for x in sentences(line)):
            return fail("untrusted-markup", f"§{sec}: a file string rendered as markup")
    clauses = [unquote(x) for x in sentences(line)]
    return prose_checks(clauses, f"§{sec}", sec in (3, 4, 5), facts)


def line_gates(spec: str, facts: dict[str, Any]) -> list[str]:
    """Every line no other ladder reads: prose, headings and the tables of §1 and §6-§16."""
    bad: list[str] = []
    secs = line_sections(spec)
    tables = table_indices(spec)
    for i, line in enumerate(spec.split("\n")):
        if i in tables or re.match(BOARD_RE, line):
            continue
        if 2 <= secs[i] <= 5 and re.match(FRAME_RE, line):
            continue
        found = line_gate(line, secs[i], facts)
        if found:
            bad.append(found)
    return bad


def states_gate(spec: str) -> list[str]:
    """§1.3: every state of the ticket and E15-D02 reconciled to its frames, row for row."""
    s13 = block(spec, "### 1.3 ", "\n#")
    have = {
        m.group(1): {f.strip().strip("`") for f in m.group(3).split(",")}
        for m in re.finditer(STATE_ROW_RE, s13, MULTI)
    }
    bad: list[str] = []
    for num, _, frames in rows(STATES_TABLE):
        want = {f.strip() for f in frames.split(",")}
        if have.get(num) != want:
            bad.append(fail("states", f"§1.3 state {num}: frames differ from the inventory's"))
    return bad


def reconcile_gates() -> list[str]:
    """RECONCILE_TABLE and STATES_TABLE against CITED_TABLE and KIND (tool tables)."""
    bad: list[str] = []
    pinned = {(doc, int(line)) for doc, line, _ in rows(CITED_TABLE, 2)}
    for doc, line, frames in rows(RECONCILE_TABLE, 2):
        if (doc, int(line)) not in pinned:
            bad.append(fail("reconcile", f"reconciliation row `{doc}:{line}` has no needle"))
        for frame in [f.strip() for f in frames.split(",")]:
            if frame not in KIND:
                bad.append(fail("reconcile", f"reconciliation row `{doc}:{line}` names {frame}"))
    mapped = {f.strip() for _, _, fr in rows(STATES_TABLE) for f in fr.split(",")}
    for frame in sorted(mapped - set(KIND)):
        bad.append(fail("reconcile", f"STATES_TABLE names {frame}, not in KIND"))
    return bad


def measured_gates(s8: str, ctx: Ctx) -> list[str]:
    """§8: every pair, greyscale and colour-vision value as the tool prints it (no tolerance)."""
    bad: list[str] = []
    found = {(m[2], m[3], m[4]): m for m in re.finditer(CONTRAST_ROW_RE, s8, MULTI)}
    for r in ctx.measured["matrix"]:
        m = found.get((r["fg"], r["bg"], r["role"]))
        if m is None:
            bad.append(fail("contrast-row", f"§8 table lacks {r['fg']} on {r['bg']} ({r['role']})"))
            continue
        if [m[5], m[6], m[7]] != [show(r[th]) for th in THEMES]:
            bad.append(
                fail("contrast-cell", f"§8 cell differs: {r['fg']} on {r['bg']} ({r['role']})")
            )
        if m[8].strip() != r["verdict"] or m[9] != r["pairs"]:
            bad.append(
                fail("contrast-verdict", f"§8 verdict or pairs.mjs differs: {r['fg']} on {r['bg']}")
            )
    greys = {g[1]: g for g in re.finditer(GREY_ROW_RE, s8, MULTI)}
    for tok, vals in ctx.measured["grey"].items():
        g = greys.get(tok)
        if g is None or [int(g[2]), int(g[3]), int(g[4])] != [vals[th] for th in THEMES]:
            bad.append(fail("grey", f"§8 greyscale row differs or is missing: {tok}"))
    cvds = {(c[1], c[2]): c for c in re.finditer(CVD_ROW_RE, s8, MULTI)}
    for r in ctx.measured["cvd"]:
        c = cvds.get((r["a"], r["b"]))
        if c is None or [float(c[i]) for i in range(3, 7)] != r["dE76"] or c[7] != r["verdict"]:
            bad.append(
                fail("cvd", f"§8 colour-vision row differs or is missing: {r['a']} vs {r['b']}")
            )
    if FORCED_COLORS not in s8:
        bad.append(fail("forced-colors", "§8 lacks the `forced-colors: active` rendering (R2)"))
    return bad


def deck_rows(spec: str) -> dict[str, str] | None:
    """§9's keyed rows (key -> its String cell), or None while §9 is a placeholder."""
    if placeholder(spec, 9) or not section(spec, 9, 10):
        return None
    return {m.group(1): m.group(3) for m in re.finditer(DECK_ROW_RE, section(spec, 9, 10), MULTI)}


def deck_gates(deck: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """§9: every gated template verbatim, no jargon, every reason key one short sentence."""
    bad: list[str] = []
    for key, template in TEMPLATES.items():
        cell = deck.get(key, "")
        if not cell.startswith(f'"{template}"'):
            bad.append(fail("deck-template", f"§9 {key}: not the tool's template, byte for byte"))
    for key, cell in deck.items():
        string = first(r'^"([^"]*)"', cell)
        for pat in BANNED_COPY:
            if re.search(pat, string):
                bad.append(fail("jargon", f"§9 jargon in copy: {pat!r} in {key}"))
        if re.match(r"(?:rbac|workspace\.limit|ws\.export)\.", key) and (
            len(string) > facts["reason_max"] or not string.endswith(".")
        ):
            bad.append(fail("reason-length", f"§9 {key}: a reason is one sentence of ≤ 60"))
    return bad


def checklist_items(t: dict[str, str]) -> list[str]:
    """SCR-026's sign-off items, verbatim from `14`."""
    for line in t["14"].split("\n"):
        if line.endswith(POINTER_AFTER[1]):
            return [i.strip() for i in line.split("[ ]")[1:]]
    return []


def section_gates(spec: str, ctx: Ctx) -> list[str]:
    """The numbered sections in order, then each written section's own gates; a section that is
    still a placeholder is skipped (its placeholder line is the FAIL)."""
    heads = re.findall(r"^## (\d+)\. ", spec, MULTI)
    if heads != SECTIONS:
        return [fail("sections", f"the numbered sections are {heads}, not ## 0. to ## 16.")]
    bad = states_gate(spec)
    if not placeholder(spec, 6):
        s6 = section(spec, 6, 7)
        if "**T2" not in s6 or "**Not T2" not in s6:
            bad.append(fail("t2-paragraph", "§6 lacks the one T2 paragraph or its not-T2 list"))
        for needle in T2_ONCE:
            if spec.count(needle) != 1 or needle not in s6:
                bad.append(
                    fail("t2-once", f"T2 is stated more than once, or not in §6: {needle!r}")
                )
    if not placeholder(spec, 7) and A3_SECTION not in section(spec, 7, 8):
        bad.append(fail("exits-a3", "§7 lost the sentence that no session or state gates an exit"))
    if not placeholder(spec, 8):
        bad += measured_gates(section(spec, 8, 9), ctx)
    deck = deck_rows(spec)
    if deck is not None:
        bad += deck_gates(deck, ctx.facts)
    if not placeholder(spec, 10) and not re.search(
        r"^\| D09-A\d+ +\|.*CMP-067", section(spec, 10, 11), MULTI
    ):
        bad.append(fail("a-row-15", "§10 lacks the CMP-067 A-row (the Storybook list, BQ-1)"))
    if not placeholder(spec, 11):
        s11 = section(spec, 11, 12)
        for cite in ("`14:628`", "`14:629`", "`14:636`"):
            if not re.search(rf"^\| D09-A\d+ +\|.*{re.escape(cite)}", s11, MULTI):
                bad.append(fail("a-row-14", f"§11 lacks the PROPOSED A-row for {cite} (BQ-3)"))
    if not placeholder(spec, 12):
        s12 = section(spec, 12, 13)
        bad += [
            fail("g-row", f"§12 lacks the G-row {g} that E15-S07 receives")
            for g in HANDOFF_G
            if not re.search(rf"^\| {g} +\|", s12, MULTI)
        ]
    if not placeholder(spec, 13):
        s13 = section(spec, 13, 14)
        bad += [
            fail("sign-off", f"§13 lacks the item {i!r}")
            for i in checklist_items(ctx.t)
            if i not in s13
        ]
    if not placeholder(spec, 14):
        walk = re.findall(r"^- \[ \] .*$", section(spec, 14, 15), MULTI)
        if not walk or len(walk) > WALK_MAX or not any("board 08" in w for w in walk):
            bad.append(fail("walkthrough", "§14's walkthrough: 1-10 items, one on board 08"))
    if not placeholder(spec, 15):
        s15 = section(spec, 15, 16)
        bad += [
            fail("trace-table", f"§15 lacks {i}") for i in AC_IDS if not re.search(rf"\b{i}\b", s15)
        ]
    if not placeholder(spec, 16):
        body = [ln for ln in section(spec, 16, None).split("\n")[2:] if ln.strip()]
        if len(body) > SUMMARY_MAX:
            bad.append(fail("summary", f"§16 has {len(body)} lines, at most {SUMMARY_MAX}"))
    return bad


def count_frames(spec: str) -> dict[str, Any]:
    found = frame_rows(spec)
    kinds = [KIND[n][0] for n, _, _ in found if n in KIND]
    drawn = [c for _, c, _ in found if len(c) == 6 and c[5] != NOT_DRAWN]
    return {
        "frames_total": len(found),
        "frames_export": sum(n.startswith("SCR-025/") for n, _, _ in found),
        "frames_import": sum(n.startswith("SCR-026/") for n, _, _ in found),
        "frames_drawn": len(drawn),
        "frames_not_drawn": len(found) - len(drawn),
        "t2_frames": sum(k in T2_KINDS for k in kinds),
        "rejection_frames": kinds.count("rejection"),
        "refusal_frames": kinds.count("refusal"),
        "placeholders": len(re.findall(PLACEHOLDER_RE, spec)),
    }


class Ctx:
    """Everything the gates read besides the spec: the texts, the themes, the facts, the matrix.
    `with_texts` swaps in an edited copy of the plan texts and re-parses the facts from it."""

    def __init__(self) -> None:
        self.t = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
        self.themes = {th: theme_tokens(th) for th in THEMES}
        self.facts = contract_facts(self.t, self.themes)
        self.measured = measure(self.themes)
        self.missing = [tok for tok in BINDINGS if resolve(self.themes["dark"], tok) == "MISSING"]

    def with_texts(self, t: dict[str, str]) -> Ctx:
        other = object.__new__(Ctx)
        other.__dict__.update(self.__dict__)
        other.t = t
        other.facts = contract_facts(t, self.themes)
        return other


def numbers_of(spec: str, ctx: Ctx, extra: dict[str, Any]) -> dict[str, Any]:
    f, m = ctx.facts, ctx.measured
    numbers_: dict[str, Any] = dict(extra)
    numbers_.update(count_frames(spec))
    numbers_["mutations"] = len(mutations()) + len(context_mutations())
    numbers_["contract"] = {k: f[k] for k in NUMERIC_FACTS}
    numbers_["contract"]["dialog_md_px"] = f["dialog_px"][1] if f["dialog_px"] else None
    numbers_["contract"]["dialog_lg_px"] = f["dialog_px"][2] if f["dialog_px"] else None
    numbers_["design"] = dict(DESIGN_CAPS)
    c = counts(f)
    bud = FIXTURE["budget"]
    numbers_["fixture"] = {
        **c,
        "export_panels": FIXTURE["export_panels"],
        "export_layouts": len(FIXTURE["export_layouts"]),
        "budget_panels": bud["panels"],
        "measured_ms": FIXTURE["measured_ms"],
        "estimate_ms": FIXTURE["estimate_ms"],
        "app_format": FIXTURE["format"]["app"],
        "newer_format": FIXTURE["format"]["newer"],
        "older_format": FIXTURE["format"]["older"],
    }
    for k in ("pairs_rows", "pairs_fail", "pairs_registered", "pairs_proposed"):
        numbers_[k] = m[k]
    numbers_["redline"] = f["redline"]
    numbers_["missing_tokens"] = len(ctx.missing)
    numbers_["states"] = len(rows(STATES_TABLE))
    numbers_["checklist_items"] = len(checklist_items(ctx.t))
    numbers_["deck_rows"] = len(deck_rows(spec) or {})
    numbers_["rows"] = {
        kind: len(set(re.findall(rf"^\| (D09-{kind}\d+) +\|", spec, MULTI))) for kind in "ACDGQ"
    }
    return numbers_


def marker_gates(spec: str, numbers_: dict[str, Any]) -> list[str]:
    """S18 (markers): a marker's value is the tool's, the number printed beside it is the
    marker's, every marker parses, and no marker the spec carries disappears."""
    flat = flatten(numbers_)
    bad: list[str] = []
    for m in re.finditer(MARKER_LOOSE_RE, spec, MULTI):
        if not re.match(MARKER_RE, m.group(0)):
            bad.append(fail("marker-parse", f"malformed marker {m.group(0)[:60]!r}"))
    for m in re.finditer(MARKER_RE, spec):
        key, val = m.group(1), m.group(2)
        have = flat.get(key)
        same = str(have).lower() == val.lower()
        try:
            same = same or float(str(have)) == float(val)
        except ValueError:
            pass
        if have is None or not same:
            bad.append(fail("marker-value", f"marker audit:{key}={val} vs tool {have}"))
            continue
        before = spec[spec.rfind("\n", 0, m.start()) + 1 : m.start()].rstrip()
        token = re.search(NUMBER_BEFORE_RE + r"$", before)
        printed = re.sub(r"[,\u202f\u00a0]", "", token.group(1)) if token else ""
        if printed != val:
            bad.append(fail("marker-visible", f"printed {printed or 'nothing'} beside audit:{key}"))
    for key, want in MARKERS.items():
        have_n = len(re.findall(rf"audit:{re.escape(key)}=", spec))
        if have_n < want:
            bad.append(fail("marker-count", f"audit:{key} appears {have_n} times, {want} expected"))
    return bad


def gates(spec: str, ctx: Ctx) -> tuple[list[str], dict[str, Any]]:
    """Every gate over one copy of the spec; returns the FAILs and the numbers it derived."""
    bad: list[str] = []
    b0, n0 = board_gates(spec)
    bh, nh = head_gates(spec)
    bc, nc = cite_gates(spec, ctx.t)
    deck = deck_rows(spec)
    bad += bh + b0 + frame_gates(spec, ctx.facts, set(deck) if deck is not None else None)
    for head, report in (("### 4.2 ", False), ("### 4.3 ", True)):
        found = table_gate(spec, head, report)
        if found:
            bad.append(found)
    bad += bc + line_gates(spec, ctx.facts) + text_gates(spec, ctx.t, ctx.facts) + reconcile_gates()
    bad += section_gates(spec, ctx) + contract_gates(ctx.facts)
    bad += [fail("token-missing", f"token MISSING: {tok}") for tok in ctx.missing]
    bad += [
        fail("contrast-fail", f"contrast FAIL: {r['element']}")
        for r in ctx.measured["matrix"]
        if r["verdict"] in ("FAIL", "MISSING")
    ]
    numbers_ = numbers_of(spec, ctx, {**n0, **nh, **nc})
    bad += marker_gates(spec, numbers_)
    return bad, numbers_


Mutation = tuple[str, Callable[[str], str], str, int | None]
CtxMutation = tuple[str, Callable[[dict[str, str]], dict[str, str]], str]
ALL = -1  # a mutation that needs every section written


def row_fn(pattern: str, fn: Callable[[str], str]) -> Callable[[str], str]:
    """Apply `fn` to the one spec line the anchored `pattern` finds (unchanged when none)."""

    def apply(s: str) -> str:
        m = re.search(pattern, s, MULTI)
        return s if not m else s[: m.start()] + fn(m.group(0)) + s[m.end() :]

    return apply


def frame_sub(frame: str, old: str, new: str) -> Callable[[str], str]:
    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", lambda ln: ln.replace(old, new, 1))


def frame_add(frame: str, clause: str) -> Callable[[str], str]:
    """Append a clause to the frame's Shows cell (its third cell)."""

    def fn(ln: str) -> str:
        c = ln.split(" | ")
        c[2] = c[2].rstrip() + "; " + clause
        return " | ".join(c)

    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", fn)


def frame_cell(frame: str, index: int, value: str) -> Callable[[str], str]:
    def fn(ln: str) -> str:
        c = cells(ln)
        c[index] = value
        return "| " + " | ".join(c) + " |"

    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", fn)


def line_sub(start: str, old: str, new: str) -> Callable[[str], str]:
    """Replace `old` once in the one line that starts with `start`."""
    return row_fn(rf"^{re.escape(start)}.*$", lambda ln: ln.replace(old, new, 1))


def sec_fn(n: int, fn: Callable[[str], str]) -> Callable[[str], str]:
    """Apply `fn` to section n's text only (unchanged when the section is gone)."""

    def apply(s: str) -> str:
        text = section(s, n, n + 1)
        return s.replace(text, fn(text), 1) if text else s

    return apply


def sub(old: str, new: str) -> Callable[[str], str]:
    return lambda s: s.replace(old, new, 1)


def set_marker(key: str, old: str, new: str) -> Callable[[str], str]:
    """Every `old <!-- audit:key=old -->` becomes `new <!-- audit:key=new -->`: a count the
    mutation itself changes stays printed and marked consistently."""
    a, b = f"{old} <!-- audit:{key}={old} -->", f"{new} <!-- audit:{key}={new} -->"
    return lambda s: s.replace(a, b)


def chain(*fns: Callable[[str], str]) -> Callable[[str], str]:
    def apply(s: str) -> str:
        for fn in fns:
            s = fn(s)
        return s

    return apply


def ctx_sub(doc: str, old: str, new: str) -> Callable[[dict[str, str]], dict[str, str]]:
    """A context mutation: every `old` -> `new` in an in-memory copy of one plan text."""

    def apply(t: dict[str, str]) -> dict[str, str]:
        return {**t, doc: t[doc].replace(old, new)}

    return apply


def mutations() -> list[Mutation]:
    """(name, the in-memory change, the code its one new FAIL carries, the section it needs
    written or None): S1-S20 of the brief's A2 (S16 once per gated-exit word), then at least
    one per gate code, every frame mutation on a whole clause of a real row."""
    share = "Safe To " + "Share"
    home = "/ho" + "me/alex/notes/"
    closing = "Clo" + "ses #" + "363"
    pv, pk, va = "SCR-026/preview", "SCR-026/pick", "SCR-026/validating"
    rn, ro = "SCR-026/rejected-version-newer", "SCR-026/rejected-oversized"
    rm, rep = "SCR-026/rejected-malformed", "SCR-026/report"
    ep, perm = "SCR-025/export-preview", "SCR-026/entry-permission"
    s16 = [
        (va, "CANCEL stays Disabled until the check ends"),
        (pk, "the × is locked while the picker is open"),
        (pv, "Cancel is greyed out under the table"),
        (rep, "Close is inert until the copy is read"),
        ("SCR-026/drag-over", "Cancel is held while a file hovers"),
        ("SCR-026/creating", "Close is Hidden while the file is sent"),
        (ep, "Cancel is inactive while the lists load"),
        ("SCR-026/preview-migrated", "Esc is suppressed during the migration line"),
        (va, "Esc does nothing while the worker runs"),
        (rep, "Close can't be pressed until Copy report ends"),
        (pk, "Cancel cannot be pressed during the picker"),
        ("SCR-026/import-leg-lost", "Cancel waits for the session to settle"),
        ("SCR-026/budget-confirm", "Cancel is unusable for the first moment"),
    ]
    m: list[Mutation] = [
        ("S1", frame_sub(ep, "environment binding (DEMO or LIVE); ", ""), "[excluded]", None),
        ("S2", frame_add(ep, f"the file is {share}"), "[share-claim]", None),
        (
            "S3",
            line_sub("| Positions ", "| Positions ", "| Positions (Ledger North) "),
            "[foreign-account]",
            None,
        ),
        (
            "S4",
            line_sub("| Account filter on Positions ", "| Drop ", "| Remap "),
            "[account-remap]",
            None,
        ),
        (
            "S5",
            frame_sub(
                rn,
                "· Choose another file (`primary`)",
                "· Choose another file (`secondary`) · Import anyway (`primary`)",
            ),
            "[import-verb]",
            None,
        ),
        (
            "S6",
            frame_add(
                rn, "Import as new workspace stays, T2 with the lock leading (`rbac.permission`)"
            ),
            "[rejection-lock]",
            None,
        ),
        (
            "S7",
            frame_sub(rn, "exported by format version 2 and", "exported by a newer format and"),
            "[versions]",
            None,
        ),
        (
            "S8",
            frame_sub(rn, "the file's `schema_version` (2)", "the file's app version (2)"),
            "[version-field]",
            None,
        ),
        ("S9", frame_sub(va, "schema → version →", "version → schema →"), "[steps]", None),
        (
            "S10",
            frame_sub(
                pv,
                STATE_PRE,
                "state: Scalping (2) exists already, its layouts following on Import as new "
                "workspace",
            ),
            "[created-early]",
            None,
        ),
        (
            "S11",
            frame_sub(
                rm,
                STATE_NONE,
                "state: the two valid layouts were kept and the rest is unchanged",
            ),
            "[partial]",
            None,
        ),
        (
            "S12",
            frame_add(pv, "the workspace name from the file is shown as a link to its source"),
            "[untrusted-markup]",
            None,
        ),
        ("S13", frame_sub(rm, "caps: names", "sizes: names"), "[caps]", None),
        (
            "S14",
            frame_sub(va, "server: the server re-checks", "note: the server re-checks"),
            "[server-recheck]",
            None,
        ),
        (
            "S15",
            frame_add(
                "SCR-025/export-entry",
                "T2: Export… for view-as, the lock leading it (`rbac.view_as`)",
            ),
            "[export-gated]",
            None,
        ),
    ]
    for word, (frame, clause) in zip(S16_WORDS, s16, strict=True):
        tag = word.replace(" ", "-").replace("'", "")
        m.append((f"S16-{tag}", frame_add(frame, clause), "[exit-gated]", None))
    m += [
        (
            "S17",
            frame_sub(
                perm, "`rbac.view_as` → `rbac.permission` →", "`rbac.permission` → `rbac.view_as` →"
            ),
            "[legs-order]",
            None,
        ),
        ("S18", frame_sub(ro, "the limit is 2 MB", "the limit is 5 MB"), "[limit-number]", None),
        (
            "S19",
            frame_sub(pk, "— not a Tab stop, no role", "— a Tab stop, no role"),
            "[drop-zone]",
            None,
        ),
        (
            "S20",
            frame_sub(ro, "initial focus: Choose another file", "initial focus: Cancel"),
            "[rejection-focus]",
            None,
        ),
    ]
    return m + more_mutations(share, home, closing)


def more_mutations(share: str, home: str, closing: str) -> list[Mutation]:
    """One or more per gate code beyond S1-S20, each on a whole clause or a whole row."""
    pv, pk, va = "SCR-026/preview", "SCR-026/pick", "SCR-026/validating"
    ro = "SCR-026/rejected-oversized"
    rw, rep = "SCR-026/rejected-wrong-type", "SCR-026/report"
    ep, perm = "SCR-025/export-preview", "SCR-026/entry-permission"
    ed = "SCR-025/export-done"
    base9 = BASE[:9]

    def drop_last_cell(ln: str) -> str:
        return ln[: ln.rstrip().rstrip("|").rstrip().rfind("|") + 1]

    def swap_rows(a: str, b: str) -> Callable[[str], str]:
        def apply(s: str) -> str:
            lines = s.split("\n")
            ia = next(i for i, x in enumerate(lines) if x.startswith(a))
            ib = next(i for i, x in enumerate(lines) if x.startswith(b))
            lines[ia], lines[ib] = lines[ib], lines[ia]
            return "\n".join(lines)

        return apply

    def light(num: str, slug: str) -> Callable[[str], str]:
        return chain(
            sub(f"`E15-D09 / {num} {slug}`", f"`E15-D09 / {num} {slug}-light`"),
            sub(f"E15-D09-{num}-{slug}.png", f"E15-D09-{num}-{slug}-light.png"),
            line_sub(f"| {num} ", "| dark ", "| light "),
        )

    return [
        (
            "S1-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                'conditions RULED. "Never included: credentials and keys."',
            ),
            "[excluded]",
            None,
        ),
        (
            "S2-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                f"conditions RULED. It is {share}.",
            ),
            "[share-claim]",
            None,
        ),
        (
            "S3-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. Desk 9 stays named.",
            ),
            "[foreign-account]",
            None,
        ),
        (
            "S3-report",
            row_fn(
                r"^\| Positions .*$(?![\s\S]*^\| Positions )",
                lambda ln: ln.replace("| Positions ", "| Positions (Desk 9) ", 1),
            ),
            "[foreign-account]",
            None,
        ),
        (
            "S5-clause",
            frame_add(rw, "[Import the valid parts] under the message"),
            "[import-verb]",
            None,
        ),
        (
            "S10-scan",
            frame_add(va, "the workspace was created when the check began"),
            "[created-early]",
            None,
        ),
        (
            "S12-prose",
            line_sub("### 5.1 Frames", "every row)", "every row; the names rendered as Markdown)"),
            "[untrusted-markup]",
            None,
        ),
        (
            "S16-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. Cancel is disabled while the file is checked.",
            ),
            "[exit-gated]",
            None,
        ),
        (
            "S16-rejection",
            frame_add(ro, "Choose another file is disabled until the message is read"),
            "[exit-gated]",
            None,
        ),
        ("env-frame", frame_add(rep, "the new workspace opens in LIVE"), "[env]", None),
        (
            "env-prose",
            line_sub(
                "### 4.1 Frames", "every row)", "every row; the DEMO environment it opens in)"
            ),
            "[env]",
            None,
        ),
        (
            "account-prose",
            line_sub(
                "### 4.1 Frames",
                "every row)",
                "every row; account filters remapped to your default account)",
            ),
            "[account-remap]",
            None,
        ),
        (
            "steps-prose",
            line_sub(
                "### 3.1 Frames",
                "every row)",
                "every row; size → schema → parse depth / node count → version → per-pane "
                "registry)",
            ),
            "[steps]",
            None,
        ),
        ("cells", row_fn(r"^\| `SCR-026/cancelled` +\|.*$", drop_last_cell), "[cells]", None),
        ("class", frame_sub(ro, "| outcome (rejection) |", "| T2 |"), "[class]", None),
        ("board-cell", frame_cell(rep, 5, "11"), "[board-cell]", None),
        (
            "key-namespace",
            frame_cell(pk, 4, "`e15.import.title` · `oops.key`"),
            "[key-namespace]",
            None,
        ),
        (
            "trust-note",
            frame_sub(pk, "changes nothing else", "changes little else"),
            "[trust-note]",
            None,
        ),
        ("t2-over", frame_add(pk, "T2: Choose file… (`rbac.permission`)"), "[t2-over]", None),
        ("t2-over-free", frame_add(pk, "Choose file… is T2 for a Viewer"), "[t2-over]", None),
        ("dialog", frame_sub(ro, '`size="lg"`', '`size="md"`'), "[dialog]", None),
        (
            "included",
            frame_sub(ep, "3 indicator presets.", "3 indicator presets · densities."),
            "[included]",
            None,
        ),
        ("caveat", frame_sub(ep, "caveat: ", "aside: "), "[caveat]", None),
        (
            "access",
            frame_sub("SCR-026/entry", "T1 for Owner and Manager", "T1 for the Owner"),
            "[access]",
            None,
        ),
        (
            "availability",
            frame_sub("SCR-025/export-unavailable", "no lock, no CMP-079", "no CMP-079"),
            "[availability]",
            None,
        ),
        (
            "busy",
            frame_sub("SCR-025/export-preparing", ", a load, so Cancel stays", ""),
            "[busy]",
            None,
        ),
        (
            "done",
            frame_sub(ed, "— the file name in `type.num.sm`", "— the file name in `type.ui.body`"),
            "[done]",
            None,
        ),
        (
            "event",
            frame_sub(ed, "fires once the file is saved, never on", "fires on"),
            "[event]",
            None,
        ),
        ("picker", frame_sub(pk, "a real `<button>`", "a styled `<div>`"), "[picker]", None),
        ("help", frame_sub(pk, '"JSON, up to 2 MB"', '"A JSON file, up to 2 MB"'), "[help]", None),
        ("progress", frame_sub(va, "`valueText`", "`aria-valuetext`"), "[progress]", None),
        (
            "live",
            frame_sub(
                rep,
                "live: polite, once — the success line",
                "live: assertive, once — the success line",
            ),
            "[live]",
            None,
        ),
        (
            "state",
            frame_sub("SCR-025/export-cancelled", "and no event fires", "and the event fires"),
            "[state]",
            None,
        ),
        ("table", frame_sub(pv, 'caption "Preview —', 'caption "Preview:'), "[table]", None),
        ("count", frame_sub(pv, "· 3 dropped ·", "· 2 dropped ·"), "[count]", None),
        ("actions", frame_sub(pv, "— never colour alone", "— colour only"), "[actions]", None),
        (
            "clash",
            frame_sub(pv, '"Imported as Scalping (2): a', '"Imported as Scalping copy (2): a'),
            "[clash]",
            None,
        ),
        (
            "migrated",
            frame_sub(
                "SCR-026/preview-migrated",
                'CMP-028 `info` "Migrated',
                'CMP-028 `warning` "Migrated',
            ),
            "[migrated]",
            None,
        ),
        (
            "budget",
            frame_sub(
                "SCR-026/preview-over-budget", "budget: CMP-028 `warning`", "budget: CMP-028 `info`"
            ),
            "[budget]",
            None,
        ),
        (
            "renders",
            frame_sub(rep, "never markup, never a link, never interpreted", "never markup"),
            "[renders]",
            None,
        ),
        (
            "component",
            frame_sub(
                rw,
                'component: CMP-027 `inline`, `live="polite"`',
                'component: CMP-027 `banner`, `live="polite"`',
            ),
            "[component]",
            None,
        ),
        (
            "message",
            frame_sub(rw, "Choose a .json workspace file.", "Pick a .json workspace file."),
            "[message]",
            None,
        ),
        (
            "footer",
            frame_sub(pk, "footer: Cancel (`secondary`)", "footer: Cancel (`primary`)"),
            "[footer]",
            None,
        ),
        (
            "focus",
            frame_sub(pk, "initial focus: Choose file…", "initial focus: the dialog title"),
            "[focus]",
            None,
        ),
        ("esc", frame_sub(pk, "Esc → Cancel", "Esc → Close"), "[esc]", None),
        (
            "exits-t1",
            frame_sub(pk, "exits T1: Cancel · Esc · ×", "exits T1: Cancel · ×"),
            "[exits-t1]",
            None,
        ),
        ("t2-lock", frame_sub(perm, "the CMP-019 `lock` leading it, ", ""), "[t2-lock]", None),
        (
            "t2-key",
            frame_sub(perm, "reason: `rbac.permission`", "reason: `rbac.view_as`"),
            "[t2-key]",
            None,
        ),
        (
            "legs",
            frame_sub("SCR-026/entry-limit", " → `workspace.limit.count`", ""),
            "[legs]",
            None,
        ),
        (
            "report-region",
            frame_sub(rep, '`role="region"` named', '`role="status"` named'),
            "[report-region]",
            None,
        ),
        (
            "report-line",
            frame_sub(rep, "3 items dropped", "3 things dropped"),
            "[report-line]",
            None,
        ),
        (
            "report-copy",
            frame_sub(rep, 'and announces "Copied"', "and announces nothing"),
            "[report-copy]",
            None,
        ),
        (
            "reflow",
            frame_sub("SCR-026/reflow-200", "keeps its title and footer", "keeps its title"),
            "[reflow]",
            None,
        ),
        (
            "density",
            frame_sub(
                "SCR-026/compact", "the dialog padding unchanged", "the dialog padding halved"
            ),
            "[density]",
            None,
        ),
        (
            "inventory",
            row_fn(
                r"^\| `SCR-026/cancelled` +\|.*$", lambda ln: ln.replace("cancelled", "canceled", 1)
            ),
            "[inventory]",
            None,
        ),
        (
            "key-deck",
            frame_cell(pk, 4, "`e15.import.title` · `e15.import.not_in_the_deck`"),
            "[key-deck]",
            9,
        ),
        (
            "preview-columns",
            row_fn(r"^\| Item +\| Type +\|.*$", lambda ln: ln.replace("Type", "Kind", 1)),
            "[preview-columns]",
            None,
        ),
        ("preview-row", line_sub("| BTCUSDT · 1m · group A ", "1m", "5m"), "[preview-row]", None),
        ("preview-order", swap_rows("| Positions ", "| Layout 1 "), "[preview-order]", None),
        (
            "unknown-kind",
            line_sub("| `tape_speed_v3` ", "not available in this version", "not supported"),
            "[unknown-kind]",
            None,
        ),
        (
            "preview-action",
            line_sub("| BTCUSDT · 1m · group A ", "| Add ", "|  "),
            "[preview-action]",
            None,
        ),
        (
            "report-repeat",
            row_fn(
                r"^\| `heatmap_v2` .*$(?![\s\S]*^\| `heatmap_v2` )",
                lambda ln: ln.replace("not available in this version", "not supported"),
            ),
            "[report-repeat]",
            None,
        ),
        ("board-name", line_sub("| 05 ", "/ 05 budget", "/ 06 budget"), "[board-name]", None),
        ("board-cells", line_sub("| 08 ", "| pending |", "|"), "[board-cells]", None),
        ("board-theme", line_sub("| 09 ", "| light |", "| dark  |"), "[board-theme]", None),
        (
            "board-export",
            sub("E15-D09-01-export-preview.png", "E15-D09-01-preview.png"),
            "[board-export]",
            None,
        ),
        ("board-status", line_sub("| 02 ", "| pending |", "| drawn   |"), "[board-status]", None),
        (
            "board-unknown",
            line_sub("| 06 ", "`SCR-026/report`", "`SCR-026/report`, `SCR-026/teleport`"),
            "[board-unknown]",
            None,
        ),
        (
            "board-empty",
            chain(
                line_sub("| 08 ", "| 08 ", "| 11 "),
                sub("/ 08 keyboard-walk", "/ 11 keyboard-walk"),
                sub("E15-D09-08-keyboard-walk.png", "E15-D09-11-keyboard-walk.png"),
            ),
            "[board-empty]",
            None,
        ),
        (
            "board-cap",
            chain(
                light("07", "entry-t2-matrix"),
                light("08", "keyboard-walk"),
                set_marker("light_twins", "2", "4"),
            ),
            "[board-cap]",
            None,
        ),
        ("board-reconcile", frame_cell(rep, 5, "06"), "[board-reconcile]", None),
        (
            "not-drawn",
            sub("`SCR-026/creating`, `SCR-026/cancelled`", "`SCR-026/cancelled`"),
            "[not-drawn]",
            None,
        ),
        (
            "not-drawn-unknown",
            sub("`SCR-026/refused-server`.", "`SCR-026/refused-server`, `SCR-026/teleport`."),
            "[not-drawn-unknown]",
            None,
        ),
        (
            "S3-generic",
            frame_add(rep, "the exporter's Account North-7 is listed"),
            "[foreign-account]",
            None,
        ),
        (
            "S4-frame",
            frame_add(pv, "the account filter is remapped to your default account"),
            "[account-remap]",
            None,
        ),
        (
            "S6-disabled",
            frame_add(ro, "Import… is disabled until another file is chosen"),
            "[rejection-lock]",
            None,
        ),
        (
            "S8-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. Import compares the app version of the file.",
            ),
            "[version-field]",
            None,
        ),
        (
            "S9-frame",
            frame_add(
                va,
                "in order size → schema → parse depth / node count → version → per-pane registry",
            ),
            "[steps]",
            None,
        ),
        (
            "S15-disabled",
            frame_add("SCR-025/export-entry", "Export… is disabled for a Viewer"),
            "[export-gated]",
            None,
        ),
        (
            "S16-ignored",
            frame_add(pv, "Esc is ignored while the table loads"),
            "[exit-gated]",
            None,
        ),
        (
            "S17-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. Legs: `rbac.permission` → `rbac.view_as`.",
            ),
            "[legs-order]",
            None,
        ),
        (
            "S18-prose",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. A file of at most 5 MB.",
            ),
            "[limit-number]",
            None,
        ),
        ("env-demo", frame_add(rep, "it opens on the demo account"), "[env]", None),
        (
            "S19-prose",
            line_sub("### 3.1 Frames", "every row)", "every row; Tab reaches the drop zone)"),
            "[drop-zone]",
            None,
        ),
        (
            "head-sha",
            sub("c73aec08246f06d28c70e8b959c658bc1a0c4d09", "c73aec08"),
            "[head-sha]",
            None,
        ),
        ("head-base", lambda s: s.replace(BASE, base9, 2), "[head-base]", None),
        (
            "head-penpot",
            sub(
                "**Penpot page:** `E15-D09 Workspace import and export`",
                "**Penpot page:** `E15-D09 Import`",
            ),
            "[head-penpot]",
            None,
        ),
        ("head-status", sub("boards PENDING (§0", "boards (§0"), "[head-status]", None),
        (
            "deviation",
            row_fn(
                r"^- \*\*Deviation — the densities\.\*\*.*$",
                lambda ln: ln.replace("densities", "density modes"),
            ),
            "[deviation]",
            None,
        ),
        (
            "trace-lacks",
            row_fn(r"^\| DL-21 +\|.*$", lambda ln: ln.replace("DL-21", "DL-22", 1)),
            "[trace-lacks]",
            None,
        ),
        (
            "trace-repeats",
            row_fn(r"^\| DL-20 +\|.*$", lambda ln: ln + "\n" + ln),
            "[trace-repeats]",
            None,
        ),
        (
            "trace-status",
            row_fn(
                r"^\| AC-1 +\|.*$", lambda ln: re.sub(r"\| [^|]+\|$", "| pending |", ln.rstrip())
            ),
            "[trace-status]",
            None,
        ),
        (
            "trace-pending",
            row_fn(r"^\| DoD-6 +\|.*$", lambda ln: ln.replace("| routed ", "| text pending ")),
            "[trace-pending]",
            ALL,
        ),
        (
            "bq-missing",
            row_fn(r"^\| BQ-16 +\|.*$", lambda ln: ln.replace("BQ-16", "BQ-17", 1)),
            "[bq-missing]",
            None,
        ),
        (
            "bq-ruled",
            row_fn(r"^\| BQ-15 +\|.*$", lambda ln: ln.replace("RULED (6396085915)", "PROPOSED")),
            "[bq-ruled]",
            None,
        ),
        (
            "bq-terms",
            row_fn(r"^\| BQ-6 +\|.*$", lambda ln: ln.replace("Import anyway", "Proceed")),
            "[bq-terms]",
            None,
        ),
        (
            "condition",
            row_fn(
                r"^\| Condition 3 +\|.*$", lambda ln: ln.replace("whole clauses", "first words")
            ),
            "[condition]",
            None,
        ),
        (
            "standing",
            sub("**A3** the exits are never gated —", "**A3** the exits stay open —"),
            "[standing]",
            None,
        ),
        (
            "states",
            row_fn(
                r"^\| 23 +\|.*$",
                lambda ln: ln.replace("`SCR-026/refused-server`", "`SCR-026/refused-limit`"),
            ),
            "[states]",
            None,
        ),
        ("sections", sub("## 16. Summary", "## 17. Summary"), "[sections]", None),
        (
            "placeholder",
            sub(
                "## 0. Boards (PENDING — the boards PR draws them)\n",
                "## 0. Boards (PENDING — the boards PR draws them)\n\n"
                "**Placeholder (§0):** the intro.\n",
            ),
            "[placeholder]",
            None,
        ),
        (
            "cite-unpinned",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED (`D02:999`).",
            ),
            "[cite-unpinned]",
            None,
        ),
        ("cite-range", sub("`22:21209–21230`", "`22:21209–99999`"), "[cite-range]", None),
        (
            "forbidden",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                f"conditions RULED, from {home}.",
            ),
            "[forbidden]",
            None,
        ),
        (
            "closing",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                f"conditions RULED. {closing}.",
            ),
            "[closing]",
            None,
        ),
        (
            "rule-id",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED (C-99.9).",
            ),
            "[rule-id]",
            None,
        ),
        (
            "catalogue-id",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED (CMP-999).",
            ),
            "[catalogue-id]",
            None,
        ),
        (
            "marker-parse",
            line_sub(
                "**Standing (binding on every section).**",
                "conditions RULED.",
                "conditions RULED. <!-- audit:broken",
            ),
            "[marker-parse]",
            None,
        ),
        (
            "marker-value",
            sub("16 <!-- audit:contract.depth=16 -->", "17 <!-- audit:contract.depth=17 -->"),
            "[marker-value]",
            None,
        ),
        (
            "marker-visible",
            sub("16 <!-- audit:contract.depth=16 -->", "12 <!-- audit:contract.depth=16 -->"),
            "[marker-visible]",
            None,
        ),
        ("marker-count", sub(" <!-- audit:states=26 -->", ""), "[marker-count]", None),
        ("t2-paragraph", sec_fn(6, lambda s: s.replace("**Not T2", "**Also")), "[t2-paragraph]", 6),
        (
            "t2-once",
            sec_fn(6, lambda s: s + "\nE09-D09's decision rule decides every control here.\n"),
            "[t2-once]",
            6,
        ),
        (
            "exits-a3",
            sec_fn(
                7,
                lambda s: s.replace(A3_SECTION, A3_SECTION.replace("are never gated", "stay open")),
            ),
            "[exits-a3]",
            7,
        ),
        (
            "contrast-row",
            sec_fn(8, lambda s: re.sub(CONTRAST_ROW_RE + r".*\n", "", s, count=1, flags=MULTI)),
            "[contrast-row]",
            8,
        ),
        (
            "contrast-cell",
            sec_fn(
                8,
                lambda s: re.sub(
                    r"^(\| \d+ +\| `[a-z0-9.-]+` on `[a-z0-9.-]+` +\| [a-z-]+ +\| )[\d.]+",
                    r"\g<1>0.01",
                    s,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "[contrast-cell]",
            8,
        ),
        (
            "contrast-verdict",
            sec_fn(
                8,
                lambda s: re.sub(
                    r"(?m)^(\| \d+ +\| `[^|]+\|[^|]+\|[^|]+\|[^|]+\|[^|]+\| )PASS",
                    r"\g<1>FAIL",
                    s,
                    count=1,
                ),
            ),
            "[contrast-verdict]",
            8,
        ),
        (
            "grey",
            sec_fn(
                8,
                lambda s: re.sub(
                    r"^(\| `color\.status\.[a-z.-]+` +\| )\d+", r"\g<1>999", s, count=1, flags=MULTI
                ),
            ),
            "[grey]",
            8,
        ),
        (
            "cvd",
            sec_fn(
                8, lambda s: re.sub(r"(` vs `[a-z0-9.-]+` +\| )[\d.]+", r"\g<1>0.1", s, count=1)
            ),
            "[cvd]",
            8,
        ),
        (
            "forced-colors",
            sec_fn(8, lambda s: s.replace(FORCED_COLORS, "`forced colours`")),
            "[forced-colors]",
            8,
        ),
        (
            "deck-template",
            sec_fn(9, lambda s: s.replace("the limit is {max} MB", "the cap is {max} MB", 1)),
            "[deck-template]",
            9,
        ),
        (
            "jargon",
            sec_fn(
                9, lambda s: s + '\n| `e15.import.probe` | — | "The backend refused it." | new |\n'
            ),
            "[jargon]",
            9,
        ),
        (
            "reason-length",
            sec_fn(
                9,
                lambda s: (
                    s
                    + '\n| `rbac.probe` | — | "This reason runs far past the sixty characters '
                    + 'that a reason holds." | new |\n'
                ),
            ),
            "[reason-length]",
            9,
        ),
        ("a-row-15", sec_fn(10, lambda s: s.replace("CMP-067", "CMP-0067")), "[a-row-15]", 10),
        ("a-row-14", sec_fn(11, lambda s: s.replace("`14:628`", "14:628")), "[a-row-14]", 11),
        (
            "g-row",
            sec_fn(12, lambda s: re.sub(r"^\| D09-G13( +)\|", r"| D09-G15\1|", s, flags=MULTI)),
            "[g-row]",
            12,
        ),
        (
            "sign-off",
            sec_fn(13, lambda s: s.replace("file-picker and drag-drop paths", "file-picker paths")),
            "[sign-off]",
            13,
        ),
        (
            "walkthrough",
            sec_fn(14, lambda s: s.replace("board 08", "board eight")),
            "[walkthrough]",
            14,
        ),
        (
            "trace-table",
            sec_fn(15, lambda s: re.sub(r"\bDoD-11\b", "DoD-1x", s)),
            "[trace-table]",
            15,
        ),
        (
            "summary",
            sec_fn(16, lambda s: s + "\n" + "\n".join(f"- line {i}" for i in range(11)) + "\n"),
            "[summary]",
            16,
        ),
    ]


AXIS = "**The account axis is a deferred capability"


def context_mutations() -> list[CtxMutation]:
    """Edits of an in-memory copy of a plan text that a gate must catch (a cite gone or doubled,
    a reason drifted, upstream copy gone, a contract fact changed, a pointer line moved)."""

    def drop_pointer(t: dict[str, str]) -> dict[str, str]:
        lines = [ln for ln in t["14"].split("\n") if not (POINTER in ln and "§3–§5" in ln)]
        return {**t, "14": "\n".join(lines)}

    return [
        (
            "cite-gone",
            ctx_sub("D02", "**Export preview** (from SCR-025", "**Export preview** (from SCR-0025"),
            "[cite-gone]",
        ),
        (
            "cite-ambiguous",
            ctx_sub(
                "D06",
                "**The account axis is a deferred capability",
                "**The account axis is a deferred capability " + AXIS,
            ),
            "[cite-ambiguous]",
        ),
        (
            "reason-drift",
            ctx_sub("D03", '"This workspace isn\'t saved."', '"This workspace is not saved."'),
            "[reason-drift]",
        ),
        (
            "upstream-gone",
            ctx_sub("D02", "or drop a workspace file here", "or drop it here"),
            "[upstream-gone]",
        ),
        (
            "contract-fact",
            ctx_sub(
                "22",
                "x-rbac: { permissions: [workspaces:read], scope: self }",
                "x-rbac: { permissions: [workspaces:write], scope: self }",
            ),
            "[contract-fact]",
        ),
        ("pointer-14", drop_pointer, "[pointer-14]"),
    ]


def frame_family(spec: str, ctx: Ctx) -> list[str]:
    """The per-frame gates alone (the frames, the two tables, the boards)."""
    tables = [table_gate(spec, h, r) for h, r in (("### 4.2 ", False), ("### 4.3 ", True))]
    return frame_gates(spec, ctx.facts, None) + [x for x in tables if x] + board_gates(spec)[0]


def fail_codes() -> set[str]:
    """The literal gate codes of this file: the `fail("code", …)` calls above `mutations()`."""
    src = TOOL.read_text(encoding="utf-8")
    return set(re.findall(r'\bfail\(\s*"([a-z0-9-]+)"', src[: src.index("\ndef mutations(")]))


def all_codes(ctx: Ctx) -> set[str]:
    """Every gate code: the literal ones and those each frame's expected clauses carry."""
    codes = fail_codes() - {"code"}
    for name, (kind, params) in KIND.items():
        codes |= {code for _, _, code in expected(name, kind, params, ctx.facts)}
    return codes


def code_of(expect: str) -> str:
    m = re.match(r"\[([a-z0-9-]+)\]", expect)
    return m.group(1) if m else ""


def deferred(spec: str, needs: int | None) -> bool:
    if needs is None:
        return False
    if needs == ALL:
        return bool(re.search(PLACEHOLDER_RE, spec))
    return placeholder(spec, needs)


def self_test(spec: str, ctx: Ctx) -> tuple[list[str], dict[str, int]]:
    """Each mutation adds exactly one new FAIL carrying its expected code; every gate code has a
    mutation (EXEMPT aside); the A2 list is complete; the spec on disk is untouched. A mutation
    whose section is still a placeholder is deferred (none, once no placeholder is left)."""
    bad: list[str] = []
    digest = hashlib.sha256(SPEC.read_bytes()).hexdigest()
    base, _ = gates(spec, ctx)
    family = frame_family(spec, ctx)
    if family:
        bad.append(
            f"self-test: the unmutated spec fails {len(family)} per-frame gates: {family[:2]}"
        )
    spec_m, ctx_m = mutations(), context_mutations()
    named = [(n, e) for n, _, e, _ in spec_m] + [(n, e) for n, _, e in ctx_m]
    names = [n for n, _ in named]
    if len(set(names)) != len(names):
        bad.append("self-test: two mutations share a name")
    bad += [f"self-test: the brief's A2 mutation {n} is gone" for n in A2_NAMES if n not in names]
    codes, covered = all_codes(ctx), {code_of(e) for _, e in named}
    bad += [
        f"self-test: gate code {c} has no mutation" for c in sorted(codes - covered - set(EXEMPT))
    ]
    bad += [f"self-test: EXEMPT names {c}, no gate code" for c in sorted(set(EXEMPT) - codes)]
    bad += [f"self-test: {n} expects no known code" for n, e in named if code_of(e) not in codes]
    runs: list[tuple[str, str, Ctx, str]] = []
    held = 0
    for name, fn, expect, needs in spec_m:
        if deferred(spec, needs):
            held += 1
            continue
        mutated = fn(spec)
        if mutated == spec:
            bad.append(f"self-test {name}: the mutation did not apply")
            continue
        runs.append((name, mutated, ctx, expect))
    for name, tfn, expect in ctx_m:
        texts = tfn(dict(ctx.t))
        if texts == ctx.t:
            bad.append(f"self-test {name}: the mutation did not apply")
            continue
        runs.append((name, spec, ctx.with_texts(texts), expect))
    for name, mutated, c, expect in runs:
        got, _ = gates(mutated, c)
        new = sorted(set(got) - set(base))
        if len(new) != 1 or not new[0].startswith(expect):
            bad.append(f"self-test {name}: expected one new FAIL {expect!r}, got {new[:3]}")
    again, _ = gates(spec, ctx)
    if sorted(again) != sorted(base):
        bad.append("self-test: the restored spec does not reproduce the base result")
    if hashlib.sha256(SPEC.read_bytes()).hexdigest() != digest:
        bad.append("self-test: the spec on disk changed")
    return bad, {"ran": len(runs), "deferred": held, "codes": len(codes)}


def report(ctx: Ctx, numbers_: dict[str, Any], bad: list[str]) -> list[str]:
    m = ctx.measured
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs.mjs)"]
    for r in m["matrix"]:
        if r["verdict"] == "MISSING":
            out.append(f"{r['fg']} on {r['bg']} | {r['role']} | MISSING token | {r['element']}")
            continue
        cells_ = " / ".join(show(r[th]) for th in THEMES)
        out.append(
            f"{r['fg']} on {r['bg']} | {r['role']} | {cells_} | {r['verdict']} | {r['pairs']}"
        )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    for tok in BINDINGS:
        out.append(f"{tok} | " + " / ".join(resolve(ctx.themes[th], tok)[:40] for th in THEMES))
    out.append(f"MISSING tokens (gated): {ctx.missing}")
    out.append("\n## 3. Greyscale luma (Rec. 601) and CVD deltaE76 (reported, never gated)")
    out += [f"{tok}: {vals}" for tok, vals in m["grey"].items()]
    out += [
        f"{r['pair']}: dE76 normal / P / D / T = {r['dE76']} -> {r['verdict']}" for r in m["cvd"]
    ]
    out.append("\n## 4. Contract facts parsed from text:")
    out.append(json.dumps(ctx.facts, ensure_ascii=False))
    ok = (
        f"OK — {len(all_codes(ctx))} gate codes: the header, the deviations, the AC trace, the "
        "ruled questions and conditions; §0's boards and their reconciliation; the FRAME ladder "
        "over every frame row, whole clauses (the trust copy byte for byte, the sharing claim "
        "never, no foreign account, the exits never gated, no environment, Export… never gated, "
        "no lock and no Import verb on a rejection, the caps and text-only rendering, nothing "
        "created before the send, nothing kept after a refusal, the steps in order, the server "
        "re-check, view-as first, every number the tool's); the TABLE ladder over §4.2 and §4.3; "
        "the LINE ladder over every other line; §1.3's states; the cites; the `14` pointer "
        "lines; the written sections; every marker printed, parsed, re-derived and kept"
    )
    out.append("\n## 5. Gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out.append("\n## 6. Counts: " + json.dumps(numbers_, ensure_ascii=False))
    return out


def main(argv: list[str]) -> int:
    ctx = Ctx()
    spec = SPEC.read_text(encoding="utf-8")
    bad, numbers_ = gates(spec, ctx)
    warns = list(CITE_WARN)
    out = report(ctx, numbers_, bad)
    if "--check" in argv:
        mism = [b for b in bad if b.startswith("[marker")]
        out.append("markers: " + ("clean" if not mism else "MISMATCH"))
        held = sorted({int(n) for n, _ in re.findall(PLACEHOLDER_RE, spec)})
        out.append("placeholder sections: " + (", ".join(f"§{n}" for n in held) or "none"))
    st_bad: list[str] = []
    st_n: dict[str, int] = {}
    if "--self-test" in argv:
        st_bad, st_n = self_test(spec, ctx)
        out.append(
            "self-test: "
            + (
                f"ok — {st_n['ran']} mutations ran, each caught by exactly one new FAIL; "
                f"{st_n['deferred']} deferred to placeholder sections; every one of the "
                f"{st_n['codes']} gate codes but the {len(EXEMPT)} EXEMPT has a mutation; S1-S20 "
                "present; the per-frame gates are clean on the unmutated spec; the spec on disk "
                "is unchanged"
                if not st_bad
                else "FAILED"
            )
        )
        out += [f"FAIL {b}" for b in st_bad]
    if "--json" in argv:
        palette = {th: {n: resolve(ctx.themes[th], n) for n in BINDINGS} for th in THEMES}
        inventory = {
            name: {
                "kind": kind,
                **params,
                "class": CLASS[kind],
                "clauses": [cl for _, cl, _ in expected(name, kind, params, ctx.facts)],
            }
            for name, (kind, params) in KIND.items()
        }
        payload = {
            "numbers": numbers_,
            "matrix": ctx.measured["matrix"],
            "grey": ctx.measured["grey"],
            "cvd": ctx.measured["cvd"],
            "missing": ctx.missing,
            "facts": ctx.facts,
            "inventory": inventory,
            "templates": TEMPLATES,
            "deck": {k: render(k, ctx.facts) for k in TEMPLATES},
            "problems": bad,
            "self_test": st_bad,
            "cite_warnings": warns,
            "palette": palette,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if bad or st_bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
