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
facts the frames quote, parsed from `22` / `21` / `14` / `15` / the backlog / CONSTITUTION text,
never typed; (5) the gates, each FAIL led by its code in brackets; (6) the counts.

Every line of the spec is read by exactly one ladder, which reports the first FAIL of that line.
The FRAME ladder reads every cell of every `SCR-025/export-*` and `SCR-026/*` row of §2-§5: the
expected clauses (the obligations of the tool's KIND table) whole, never first words; the Producer
and every free clause through the vocabulary ladder; the free clauses' labels, the Producer and the
copy keys against the tool's own text; the Class and Board cells against the inventory and §0. The
TABLE ladder reads §4.2 and §4.3 row by row against the fixture. The BOARD gates read every cell of
§0. The LINE ladder reads every other line, each sentence (a paragraph is one line, so no sentence
is ever split) and each table cell through the same vocabulary ladder. The vocabulary ladder holds
stem lists read case-insensitively against whole clauses, a match counting unless a negator
governs it in its clause (one before it with no "but", "only", "while" or new subject between):
the gated-exit words with a role placed before an exit; the environment words; the sharing claim
and its paraphrases; markup and link words beside a string from the file; a remap beside an
account; an Import verb, a lock, a create or a keep word where a refusal or the time before the send
is in scope; the drop zone made a stop; an app version compared; the server's re-check denied; a
string shown past its cap; file content echoed or sent; the exporter granted anything; a claim no
text-first spec can make; T2 restated; a refusal's focus moved; the check steps and the legs in any
chain or list, in order; every number with its unit the tool's; every quoted UI string the deck's.
The tables that restate frame facts or record a ruling (the BQ table, the AC trace, §3.4's steps,
§5.2's anatomy and cases, §5.3, §5.4, §7's keyboard model, announcements and desk pass, §2.3's
Included items), the deck's strings, §0's boards and the `14` pointer lines are compared whole with
the tool's text. Then the header, the deviations, the cites (a moved line is a WARN; a fragment gone
or ambiguous is a FAIL; a cite missing from CITED_TABLE or to an unpinned document is a FAIL), every
commit id a pinned merge's and printed as often as pinned, "RULED" only where a ruling stands,
private paths and hosts, closing keywords, invisible or impersonating characters, comments and
raw HTML, dangling rule and catalogue ids, placeholders, and the written sections.

Two default-deny pins back the lists (the delta check of the lens round 1): every heading, every
prose sentence and every sentence of every table cell is a unit, and a unit that names the trust
copy or security-bearing text (included, excluded, sharing, credentials, API keys, an account,
untrusted, markup, Markdown, HTML, a link, raw, echo, re-check, partial, kept, keeps, uploaded,
logged, cached; SEC_BEARING_RE, any case) must equal its entry of SEC_PIN_TXT, and a heading or a
unit that names a ruling or a settled state (RULED, applied, agreed, settled, final, confirmed,
accepted, adopted, decided, in force, approved, signed off; STATUS_BEARING_RE) its entry of
STATUS_PIN_TXT, each entry its section, its place (heading, prose, or row and column) and its exact
text, in document order. A unit that is new, changed, moved or duplicated, and a pinned unit that
is gone, FAIL `sec-pin` or `status-pin` with its place: the word list decides which units are
pinned, the table what they may say. A pin is the backstop, reported when every other gate passes,
so one fault reads as one FAIL. `--repin-security` and `--repin-status` print a table from the
current text for a reviewer to read and commit; `--check` never re-pins.

`--json` is the only source of every number in the spec: every `<!-- audit:KEY=VALUE -->` marker
is re-derived on every run, the number printed beside it must equal it, a malformed marker is a
FAIL, each key appears exactly as often as MARKER_TABLE pins it, and a number printed without a
marker must be one the tool derives for its unit. `--check` adds the markers summary line.
`--self-test` applies each named mutation of `mutations()` to an in-memory copy of the spec (and
each of `context_mutations()` to an in-memory copy of the plan texts) and passes only when each
adds exactly one new FAIL carrying its expected code, every gate code of this file is behind at
least one mutation (EXEMPT names the few no spec or plan-text edit reaches, with the reason),
S1-S20 of the brief all run (S16 once per gated-exit word), the per-frame gates are clean on the
unmutated spec and the spec on disk is byte-identical afterwards. A mutation whose target section
is still a placeholder is DEFERRED and counted (a spec without placeholders defers none). Exit 1
on any FAIL, with or without a flag.

Usage: python3 -I -B docs/design/_tools/e15_d09_import_export_audit.py [--json] [--check]
       [--self-test] [--repin-security] [--repin-status]
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import re
import sys
import textwrap
import unicodedata
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
# The BQ comment the ruling answers (the questions table's heading names both).
BQ_COMMENT = "6396029607"
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
# E05-D02 slice 4's commit, which the header names beside the merges.
SLICE4 = "04a8caa9513e90debcf7cbc41a9ca585496eba01"
KNOWN_SHAS = (*MERGE_SHAS, BASE, SLICE4)
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
    r"(?:(?:[\w.-]+/[\w.-]+)?#\d+|https?://\S+/issues/\d+|issue\s+\d+)"
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
    "32": PLAN / "32-risk-register.md",
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
CITE_KEYS = "04|05|11|14|15|16|21|22|32|BL|D01|D02|D03|D06|FL|S4|E09D09|E36D03|README"
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
the dialog's T2 verb on its raised fill | color.text.tertiary | color.surface.raised | hc-text
the Reason column on even rows | color.text.secondary | color.surface.raised | hc-text
the progress fill on its track | color.action.primary.default | color.surface.hover | non-text
the progress fill on the card | color.action.primary.default | color.surface.overlay | non-text
the progress track on the card | color.surface.hover | color.surface.overlay | decorative
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
    "size.target.min",
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
05 | 85 | **Reserved, non-remappable keys**
05 | 96 | **Focus is never silently stolen**
05 | 100 | 7. **Target size**
05 | 101 | **Dragging alternatives**
05 | 130 | **User-adjustable contrast**
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
14 | 618 | `workspace.updated`, `workspace.deleted`, `workspace.exported`
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
14 | 1993 | [ ] export selection (single / selected / all) with a scope-stripping note
15 | 48 | ### CMP-001 Button
15 | 225 | ### CMP-019 Icon
15 | 262 | ### CMP-023 Progress Bar
15 | 301 | ### CMP-027 ErrorState / InlineError
15 | 306 | `live` overrides it: `polite` for an in-panel load failure
15 | 307 | registers the PROPOSED `icon/x-circle`
15 | 311 | ### CMP-028 Callout / Banner
15 | 317 | `live` overrides the default (`off` renders no live role
15 | 361 | ### CMP-033 CopyButton
15 | 364 | - **Props**: `value: string` · `label` (a11y name) · `onCopied?`.
15 | 366 | announces "Copied" via a transient polite live region
15 | 368 | - **Storybook**: Default, CopiedState.
15 | 395 | - **Tokens**: `space.row.*`, `font.size.body/label`.
15 | 409 | ### CMP-038 InlineSpinnerText
15 | 463 | ### CMP-043 Dialog (Modal)
15 | 466 | at most 420 / 560 / 960 px wide
15 | 468 | `Esc` always cancels before the confirmed send
15 | 473 | ### CMP-044 ConfirmDialog
15 | 476 | `confirmDelayMs?` (default 400; Confirm ignores any activation before it)
15 | 479 | Confirm a CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`)
15 | 483 | ### CMP-045 Toast / Notification
15 | 524 | ### CMP-049 Table
15 | 529 | one row element per record
15 | 530 | table mode's Tab stops are the scroll region
15 | 531 | odd `color.surface.canvas`, even `color.surface.raised`
15 | 690 | ### CMP-067 FileDrop / Import control
15 | 692 | **Purpose**: CSV/JSON import (journal import, rule import/export).
15 | 693 | - **Props**: `accept` · `onFiles` · `multiple?`.
15 | 694 | (drag-and-drop is additive, never the only path)
15 | 695 | **Tokens**: `color.border.dashed`.
15 | 696 | **Storybook**: Default, DragOver, Error.
15 | 697 | - **Tests**: unit, visual, axe, keyboard-only file selection test.
15 | 699 | ### CMP-068 CopyableCodeBlock
15 | 811 | ### CMP-079 RbacGate
15 | 2738 | ### CMP-234 ValidationPanel
15 | 2742 | a `role="log"` list ordered errors-first
16 | 456 | a new directional or status **encoding** needs every surface
21 | 3300 | -- sanitised, 1..120 code points
21 | 5069 | Pane settings must never carry credentials or account identifiers
22 | 8521 | operationId: createWorkspace
22 | 8525 | `limit_reached` (32 live workspaces)
22 | 8530 | Bodies over 4 KiB are refused with `413` (`payload_too_large`)
22 | 8531 | `Idempotency-Key` is accepted, never required
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
22 | 19873 | Every non-null value is refused (`422` rule `chart_template_not_found`)
22 | 19879 | A non-empty list is refused (`422` rule `indicator_preset_not_found`)
22 | 20197 | else 422 rule `layout_not_found`
22 | 21209 |     WorkspaceBundle:
22 | 21213 | Portable, credential-free export of presentation state only.
22 | 21215 | schema_version: { type: string }
22 | 21224 | Export holds only the caller's live presets
22 | 21226 | Import (E15-S07; no operation takes a bundle yet) never trusts
22 | 21229 | the array is imported whole or not
22 | 21230 | The server refuses it whole beyond 200 items or 1 MiB of preset JSON
32 | 47 | **R13** | Team & knowledge
BL | 242 | "key": "E15-D09",
BL | 266 | Export again from the older version
BL | 700 | "key": "E15-X01",
BL | 721 | Classify a workspace export as *user-confidential*
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
D02 | 641 | - **Anatomy** (E09-D09 §2.2, §9.1, §9.2)
D02 | 642 | - **One notice, many pointers** (E09-D09 §2.2)
D02 | 643 | - **Keys** (E09-D09 §9.3)
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
E09D09 | 32 | ### 2.1 The decision rule (D1, D2)
E09D09 | 49 | **T2 Disabled with a visible reason (D4).**
E09D09 | 85 | Every T2 reason is one of these seven keys
E09D09 | 89 | | `rbac.permission`        | "Your role can't {verb}."
E09D09 | 95 | | `rbac.view_as`           | "Read-only while viewing as {user}."
E09D09 | 114 | `workspaces:write` → "save workspaces"
E36D03 | 153 | ## 8. SCR-089 import (board 08)
E36D03 | 155 | **Drop zone** — CMP-067
E36D03 | 272 | **Token names the composed entries use that do not exist**
E36D03 | 339 | | the drop zone (CMP-067)
S4 | 119 | 32. **Focus contract for overlays**
S4 | 140 | 33. **Where feedback speaks**
S4 | 194 | 37. **What is not T2 here**
S4 | 202 | 38. **Forced colours**
S4 | 209 | 39. **Resize, zoom and reflow**
S4 | 734 | **H22 — `Esc`, the NoEscClose story and the scrim.**
S4 | 904 | **H36 — A dialog with unsaved changes.**
S4 | 919 | **H37 — Where a warning and a load failure speak.**
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
    "invalid_key": "layouts[0].crosshair_sync",
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
    "e15.export.title": "Export {workspace}",
    "e15.export.close": "Close Export {workspace}",
    "e15.export.unsaved": (
        "Unsaved changes aren't in the file: it holds {workspace} as last saved."
    ),
    "e15.export.included": (
        "The file includes: {layouts} ({layout_names}) · {panels} · symbols {symbols} · sync "
        "groups {groups} · each panel's settings · {drawings}, with their text labels · "
        "{templates} · {presets}."
    ),
    "rbac.view_as": "Read-only while viewing as {user}.",
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
    "e15.import.rejected.invalid": (
        "This isn't a workspace file: `{key}` isn't valid. Nothing was imported."
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
    "e15.import.refused.server": "The server didn't accept this file: `{key}` isn't valid.",
    "e15.import.refused.store": (
        "The workspace store didn't answer. Choose the file again in a moment."
    ),
    "e15.import.refused.size": (
        "The server didn't accept this file: it is larger than the server takes."
    ),
    "e15.import.refused.unconfirmed": (
        "We couldn't confirm the import. Check your workspaces before importing again."
    ),
    "e15.import.nothing": NOTHING,
    "e15.import.migrated": MIGRATED,
    "e15.import.clash": "Imported as {clash}: a workspace named {workspace} exists.",
    "e15.export.excluded": EXCLUDED,
    "e15.import.trust": TRUST_NOTE,
    "e15.export.caveat": CAVEAT,
    "e15.import.report.done": (
        "Imported {clash}: {panels}, {layouts}, {dropped_items} dropped, {remapped} remapped."
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
SCR-026/refused-unconfirmed | unconfirmed |
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
    "unconfirmed": "outcome",
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
    "unconfirmed",
    "report",
}
PRE_SEND_KINDS = {"pick", "drag-over", "validating", "preview", "budget-confirm", "t2-leg"}
NOTHING_KINDS = {"rejection", "refusal"}
TRUST_KINDS = {
    "pick",
    "drag-over",
    "validating",
    "preview",
    "busy",
    "t2-leg",
    "unconfirmed",
} | NOTHING_KINDS
# The export's frames, where every free clause is read for a lock (S15), the unsaved
# default's availability aside.
EXPORT_KINDS = EXPORT_DIALOG_KINDS | {"export-entry"}
# The frames that render a string taken from the file (Condition 1: caps and text only).
FILE_STRING_FRAMES = {
    "SCR-026/validating",
    "SCR-026/preview",
    "SCR-026/preview-migrated",
    "SCR-026/preview-over-budget",
    "SCR-026/budget-confirm",
    "SCR-026/creating",
    "SCR-026/import-leg-lost",
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
    "unconfirmed": "Close (`primary`)",
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
    "unconfirmed": "Close",
    "report": 'the heading "Import report" (`tabindex="-1"`)',
}
ESC = {
    "menu": "Close (the menu, focus back on its button)",
    "dialog": "Cancel",
    "export-done": "Close",
    "report": "Close",
    "busy": "Close (the view only: the import is sent and finishes)",
    "budget-confirm": "Cancel (back to the preview)",
    "unconfirmed": "Close",
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
    "unconfirmed": f"Close · Esc · {TIMES}",
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
    "unconfirmed": ("e15.import.refused.unconfirmed",),
}
VARIANTS = {
    "malformed": (
        "e15.import.rejected.parse",
        "e15.import.rejected.panes",
        "e15.import.rejected.layouts",
        "e15.import.rejected.presets",
        "e15.import.rejected.invalid",
    ),
    "nodes": ("e15.import.rejected.nodes",),
    "server": ("e15.import.refused.store", "e15.import.refused.size"),
}
EVENT_REASON = {
    "version-newer": "version-newer",
    "version-older": "version-older",
    "malformed": "malformed",
    "oversized": "oversized",
    "wrong-type": "wrong-type",
    "nodes": "malformed",
}
# Vocabulary lists, all read case-insensitively (A2 / Condition 3) as stems, never closed word
# lists: each list is read against whole clauses (a frame row's clauses, a table's cells, a prose
# sentence), quoted copy blanked (`unquote`), code spans read as text, and a match counts unless a
# negator governs it (`negated`): one earlier in its clause with no contrast boundary between.
# An exit: Cancel, Esc, the close × (not the × of a size), Close, Choose another file, Dismiss.
EXIT_RE = (
    r"(?i)\bcancel(?:s|led|ling)?\b|\besc(?:ape)?\b|(?<!\d)(?<!\d )×(?! ?\d)|\bclose[sd]?\b"
    r"|\bchoose another file\b|\bdismiss\w*|\bthe back button\b"
)
# "fail closed" names a server's posture, never the exit Close.
EXIT_BLANK = (r"(?i)\bfail(?:s|ed)? closed\b",)
# The gated-exit stems (the brief's words and their inflections, E09-D09's T2 vocabulary, the
# synonyms a lens found, and a role or a permission placed before an exit).
GATE_WORDS = (
    r"\baria-disabled\b|\bdisabl\w*|\block(?:s|ed|ing)?\b|\bpadlock\w*|\bgr[ae]y(?:s|ed|ing)?\b"
    r"|\bdim(?:s|med|ming)?\b|\binert\b|\bheld\b|\bhid(?:den|es|e|ing)\b|\binactiv\w*|\bsuppress\w*"
    r"|\bdo(?:es)? nothing\b|\bno effect\b|\bnot (?:be )?(?:enabled|clickable|pressable|shown"
    r"|focusable|operable|reachable|active|usable|responsive|offered|allowed|available)\b"
    r"|\bcan(?:not|['’]t| not) be (?:pressed|used|clicked|activated|reached|focused|operated"
    r"|chosen|selected|closed|dismissed)\b|\bwait(?:s|ing)? for\b|\bunusab\w*|\bunavailab\w*"
    r"|\bno longer (?:available|works?|shown|offered|active)\b|\bgated\b|\bblock(?:s|ed|ing)\b"
    r"|\bt2\b|\bignor(?:es|ed|ing)\b|\bunreachab\w*|\bturn(?:s|ed)? off\b|\bswitch(?:es|ed)? off\b"
    r"|\bfrozen\b|\bfreez\w*|\bfad(?:es|ed|ing)\b|\bread-only\b|\bnon-interactive\b"
    r"|\bunresponsive\b|\bdeactivat\w*|\bonly (?:for|to) (?:an? |the )?(?:owner|manager|viewer"
    r"|admin)s?\b|\b(?:owner|manager|viewer)s? only\b|\b(?:needs?|requires?) (?:the |a |an )?"
    r"(?:\w+ )?(?:role|permission)\b|\bcan(?:not|['’]t| not) (?:cancel|close|escape|dismiss)\b"
    r"|\brbac\.\w+|\bunder a lock\b|\bcmp-079\b|\brbacgate\b"
    r"|\b(?:doesn['’]t|does not|won['’]t|will not|cannot|can['’]t) (?:respond|react|work|act)\b"
    r"|\bstops? (?:responding|working)\b"
)
GATE_RE = "(?i)" + GATE_WORDS
# The negators, and what ends a negator's reach inside its clause.
NEGATOR_RE = (
    r"(?i)\b(?:never|not|no|nor|none|nothing|nowhere|neither|without|isn['’]t|aren['’]t|doesn['’]t"
    r"|don['’]t|won['’]t|wasn['’]t|weren['’]t|hasn['’]t|haven['’]t|rather than|instead of)\b"
)
# A negator reaches this many words; a gated or claimed word further on stands on its own.
NEGATION_REACH = 40
CLAUSE_SPLIT_RE = r"[;|]|:(?=\s)| — | – |(?<=[.!?)])\s+(?=[A-Z0-9`*\"(\[])|(?<=[.!?])\s+(?=[a-z])"
# Words a capital never starts a new clause after: an article, a preposition, a conjunction, a verb.
NO_BREAK_BEFORE = (
    "a",
    "an",
    "the",
    "no",
    "its",
    "their",
    "on",
    "to",
    "of",
    "in",
    "at",
    "by",
    "for",
    "with",
    "and",
    "or",
    "nor",
    "than",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "never",
    "not",
    "from",
    "into",
    "onto",
)
# A negator's reach ends too where a new subject and verb start mid-clause without punctuation
# ("... beyond the item's name Cancel is disabled"); a gated word still pairs with its exit
# across it.
NEG_SPLIT_RE = (
    CLAUSE_SPLIT_RE
    + r"|(?<=[a-z0-9’')`/] )"
    + "".join(rf"(?<!\b{w} )" for w in NO_BREAK_BEFORE)
    + r"(?=[A-Z][a-z]*(?: \S+){0,5}? (?:is|are|stays?|has|have|can|cannot|was|were"
    r"|keeps?|takes?|gets?)\b)"
)
CONTRAST_RE = (
    r"(?i)\b(?:but|yet|although|though|except|unless|whereas|while|however|only|when|whenever|if"
    r"|once|because|since)\b"
    r"|\b(?:and|or)\s+(?:\w+\s+){0,3}?(?:is|are|was|were|stays?|becomes?|turns?|gets?|has|have"
    r"|can|cannot|can['’]t|will|keeps?|shows?|takes?|goes|lands?|opens?|moves?)\b"
    r"|,\s+(?:then\s+)?(?:the|a|an|its|their|this|that|each|every|it|they)\s+(?:\w+\s+){0,2}?"
    r"(?:is|are|was|were|stays?|becomes?|turns?|takes?|has|gets?|keeps?|shows?|opens?|lands?)\b"
)
# A negator governs its own predicate only (MAJOR 1 of the delta check): its reach ends at " · "
# (the separator of a descriptive clause's items) and at a comma, "and" or "or" that starts a new
# subject (an article, a pronoun, a capitalised word or a non-word token such as ×) whose verb
# follows, however long the subject and whatever the verb, the match itself included. A negated
# list ("never disabled, hidden or locked", "never markup or a link") has no new subject and
# verb, so it stays one predicate.
NEG_ITEM_SEP_RE = r" · "
NEG_JOIN_RE = r",\s+(?:(?:and|or|then|so)\s+)?|\s(?:and|or)\s+"
NEW_SUBJECT_RE = (
    r"(?:(?i:the|an?|its|their|this|that|these|those|each|every|any|some|your|our|his|her|it"
    r"|they|he|she|we|you|both|all|one)\b|[A-Z]|[^\w\s,.;:])"
)
SUBJECT_VERB_RE = (
    r"(?i)\b(?:is|are|was|were|be|been|being|stays?|remains?|becomes?|turns?|gets?|got|has|have"
    r"|had|does|do|did|can|cannot|can['’]t|could|will|would|should|may|might|must|keeps?|kept"
    r"|shows?|takes?|goes|lands?|opens?|moves?|sits?|reads?|says?|names?|runs?|holds?|carries"
    r"|needs?|requires?|leaves?|appears?|disables?|hides?|locks?|blocks?|ignores?|travels?"
    r"|survives?|lists?|renders?|sends?|creates?|saves?|stores?|checks?|quotes?|echoes"
    r"|repeats?|prints?|displays?|links?|wins?|points?|pointed|starts?|ends?|waits?|greys?"
    r"|grays?|dims?|freezes?|stops?|brings?|imports?|applies|adds?|offers?)\b"
)
# The verbs that mark a match as the subject of what follows (`verb_follows`): finite forms only,
# never a word that is a noun as often ("the partial import the ticket forbids").
FINITE_VERB_RE = (
    r"(?i)(?:is|are|was|were|stays|remains|becomes|turns|gets|got|has|have|had|does|did|can"
    r"|cannot|can['’]t|could|will|would|should|may|might|must|keeps|kept|sits|appears|opens"
    r"|lands|waits|sends|offers|brings|applies|carries|takes|goes|moves|survives|travels)"
)
# The environment words (no environment travels into an import), and the spec's own uses of them
# that name no environment: an accessibility live region, a live (undeleted) record, a statement
# that the binding is never imported. Each allowance is a whole phrase, blanked before the read.
ENV_RE = (
    r"(?i)\b(?:demo|live|testnet|mainnet|environments?|sandbox|paper[- ](?:trading|account|mode)"
    r"|production (?:mode|account|environment)|real[- ](?:money|account))\b"
)
ENV_OK_RE = (r"`live(?:=\"[^\"`]*\")?`", r"`?aria-live`?", r"`politeness=\"polite\"`")
ENV_OK = (
    "environment binding is never imported",
    "staying live",
    "with its environment badge",
    "the account and environment legs never apply",
    "the environment binding and the alert and rule bindings",
    "live regions",
    "live region",
    "still-live",
    "still live",
    "stays live",
    "every live preset",
    "whole live preset library",
)
# Untrusted strings rendered as anything but text (S12): a markup or link stem in a clause that
# names a string from the file.
MARKUP_RE = (
    r"(?i)\b(?:mark-?up|markdown|html|innerhtml|dangerouslysetinnerhtml|href|hyper-?links?|links?"
    r"|linked|linking|linkif\w*|autolink\w*|anchors?|clickable|tappable|rich[- ]text"
    r"|formatt(?:ed|ing)|bold|italics?|emphas\w*|interpret(?:s|ed|ing)?|navigat\w*|made live)\b"
    r"|\bopens? on (?:click|tap)\b|\bfollows? the (?:link|url|address)\b"
)
MARKUP_OK = ("bidirectional-formatting", "anchor to rule rows", "anchors its entries")
FILE_SUBJECT_RE = (
    r"(?i)\b(?:names?|keys?|labels?|strings?|values?|kinds?|symbols?|items?|cells?|captions?)\b"
    r"|\bfrom the file\b|\bfile's name\b"
)
# The sharing claim no design may make (BQ-2 RULED) and its paraphrases; split so this file never
# states it.
SHARE_RE = (
    r"(?i)\bsafe\w*\W{1,3}(?:to|for)\W{1,3}(?:be\W{1,3})?sh" + r"ar\w*"
    r"|\bsh" + r"ar\w*\W{1,3}(?:it\W{1,3})?(?:safe(?:ly)?|freely|with anyone|without (?:a |any )?"
    r"(?:risk|worry|thought|care))\b|\bsh" + r"areable\b|\bsh" + r"are-?safe\b"
    r"|\b(?:ok|okay|fine|free)\W{1,3}to\W{1,3}(?:sh" + r"are|pass (?:it )?on|send (?:it )?"
    r"(?:on|anywhere))\b|\bsafe(?:ly)?\W{1,3}(?:to|for)\W{1,3}(?:send|pass on|hand on"
    r"|distribute|post)\b"
)
# A claim that something exists before the send (S10), and that something of a refused file is
# kept (S11). The control names are blanked first, so "Import as new workspace opens" is no claim.
CONTROL_NAMES = (
    "Import as new workspace",
    "Import anyway",
    "Import…",
    "Export…",
    "Choose file…",
    "Choose another file",
    "Download file",
    "Copy report",
    "Try again",
    "New workspace…",
    "Open workspace…",
)
NOT_NEG = r"(?:(?!(?:never|not|no|nor|nowhere|no longer)\b)\w+\s+)?"
POST_NEG = r"(?!\s+(?:nowhere|never|not|no longer)\b)"
CREATE_RE = (
    r"(?i)\b(?:is|are|was|were|has been|have been|gets?|got|being|already|now|first|still)\s+"
    + NOT_NEG
    + r"(?:created|saved|stored|persisted|written|added|imported|cached|uploaded|made)\b"
    + POST_NEG
    + r"|\b(?:workspaces?|layouts?|panes?|tabs?|drafts?|cop(?:y|ies))\s+(?:now\s+|already\s+)?"
    r"(?:exists?|appears?|opens?)\b|\bdraft workspace\b|\btemporary workspace\b"
    r"|\bin the background\b"
)
KEEP_RE = (
    r"(?i)\b(?:is|are|was|were|has been|have been|stays?|remains?|gets?|got|being)\s+"
    + NOT_NEG
    + r"(?:kept|saved|stored|retained|imported|added|cached|created|persisted|applied)\b"
    + POST_NEG
    + r"|\bkeeps?\s+(?:the\s+|its\s+|a\s+)?(?:valid\s+|parsed\s+|checked\s+|passed\s+)?(?:layouts?"
    r"|panels?|panes?|parts?|document|rest|draft)\b|\bretain\w*|\bpartial(?:ly)?\b"
    r"|\bthe valid (?:parts?|layouts?"
    r"|panels?|panes?)\b|\bbrought in\b|\bstays? in your workspaces\b|\bcontinues?\s+with\b"
    r"|\bbefore the check failed\b|\bthe layouts that passed\b|\bwhat passed\b"
    r"|\bkept in (?:the browser's storage|local storage|a cache|the cache)\b"
)
# A temporal clause around a create or keep word states when, never that it happened early.
TEMPORAL_RE = r"(?i)\b(?:when|whenever|once|after|until|as soon as)\b"
# An import or apply verb offered on a rejection or a refusal (S5).
IMPORT_VERB_RE = (
    r"(?i)\bimport(?:s|ing)?\s+(?:it\s+|them\s+|this file\s+|the file\s+)?(?:as new workspace"
    r"|anyway|partially|selected|valid|what|the valid|the rest|the readable|all|its|the (?:layouts?"
    r"|panels?|parts?)|this|that|regardless|now)\b|\[\s*import\b|\bimport button\b"
    r"|\bbutton:\s*import\b|\bapply\w*|\bcontinue[sd]?\s+(?:anyway|with|regardless)\b|\bproceed\w*"
    r"|\bgo(?:es)? on\s+(?:regardless|anyway|with)\b|\bbring(?:s|ing)?\s+in\b|\bbrought in\b"
    r"|\bskip(?:s|ping)?\s+(?:the rest|what)\b|\btry (?:it )?anyway\b"
    r"|\b(?:be|is|are)\s+(?:still\s+)?imported\s+(?:anyway|regardless|partially|still)\b"
    r"|\bcan (?:still )?be imported\b"
)
# The import's verbs where they live: on the preview and its budget confirm.
VERB_HOME_RE = r"(?i)\bpreview\b|\bbudget\b|\bconfirm\b"
# A lock, a T2 or a leg, or a gated look (S6 on a rejection, S15 on the export, A1's validity).
LOCK_WORDS = (
    r"\bt2\b|\block(?:s|ed|ing)?\b|\bpadlock\w*|\bcmp-079\b|\brbacgate\b|\brbac\.\w+|\bgated\b"
    r"|\blegs?:"
)
LOCK_RE = "(?i)" + LOCK_WORDS + "|" + GATE_WORDS
# A remap of an account binding (S4; BQ-3 RULED: dropped and listed, never remapped); the one true
# remap, the Positions pane, is the only clause where a remap word may meet an account word.
REMAP_RE = (
    r"(?i)\bre-?map(?:s|ped|ping)?\b|\bre-?bind(?:s|ing)?\b|\bre-?bound\b"
    r"|\b(?:map|maps|mapped|mapping)\s+(?:on)?to\b|\bswap(?:s|ped|ping)?\s+(?:for|to|with)\b"
    r"|\btranslat(?:e|es|ed|ing)\s+(?:in)?to\b"
)
ACCOUNT_RE = (
    r"(?i)\baccounts?\b|\baccount-scoped\b|\bbindings?\b|\bfilters?\b|\byours\b|\byour own\b"
)
TRUE_REMAP_RE = r"\bthe Positions pane\b"
STEPS = ("size", "parse", "schema", "version", "registry")
# A step named in a chain or a list (S9): its word, read outside code spans.
STEP_WORDS = (
    ("size", r"(?i)\bsize\b(?![.=\-])"),
    ("parse", r"(?i)\bparse\b(?! error)|\bparse depth\b|\bnesting\b|\bnode count\b|\bdepth\b"),
    ("schema", r"(?i)\bschema\b(?![_.])"),
    ("version", r"(?i)\bversion\b(?! \d|s\b| refusal)"),
    ("registry", r"(?i)\bregistry\b"),
)
ORDER_CUE_RE = (
    r"→|->|(?<![<>=-])>(?![=>])|(?i:\bthen\b|\bfirst\b|\bbefore\b|\bafter\b|\border\b"
    r"|\blegs?\b|\botherwise\b)"
)
# The legs (S17), read in a chain or a sentence that orders them.
LEG_WORDS = (
    ("view_as", r"(?i)\brbac\.view_as\b|(?<!entry-)\bview-as\b|\bviewing as\b"),
    ("permission", r"(?i)\brbac\.permission\b|\bthe permission\b|\bpermission\b(?! reason)"),
    ("limit", r"(?i)\bworkspace\.limit\.count\b|\bthe limit\b(?! leg)|\bthe state\b"),
)
# A leg named first or view-as named late, in a sentence about the legs; the permission's reason
# shown while viewing as.
LEG_FIRST_RE = (
    r"(?i)\b(?:permission|limit|state)(?: leg)?(?: is read| runs| comes)? first\b"
    r"|\bview-as(?: leg)? (?:is |comes |runs )?(?:the )?(?:second|last|third)\b"
)
LEG_CTX_RE = r"(?i)\blegs?\b|\bread\b|\bT2\b|\border\b"
LEG_WRONG_RE = (
    r"(?i)\bpermission reason\b[^.;]{0,40}\bwhile viewing as\b"
    r"|\bwhile viewing as\b[^.;]{0,40}\bpermission reason\b"
)
# The drop zone made a Tab stop (S19).
DROP_RE = (
    r"(?i)\bdrop[- ]?(?:zone|area|target|box|region)\b|\bdropzone\b|\bthe zone\b|\bdashed (?:box"
    r"|area|edge)\b"
)
TAB_STOP_RE = (
    r"(?i)\btab[- ]?stops?\b|\bfocusable\b|\btabindex\b|\b(?:receives?|takes?|gets?|holds?)\s+"
    r"(?:keyboard\s+)?focus\b|\bin the tab order\b|\btab (?:reaches|lands on|stops on|moves to"
    r"|goes to)\b|\btabbed to\b|\btabbable\b|\bfocus order\b|\bkeyboard focus\b"
    r"|\brole (?:of )?\"?button\b|\benter on the zone\b|\boperable\b"
)
# An app version in a comparison (S8).
APP_VERSION_RE = (
    r"(?i)\bapp(?:lication)?[ _-]?version\b|\bappversion\b|\bbuild (?:number|version)\b"
    r"|\brelease (?:number|version)\b|\bexporting build\b|\bthe app's version\b|\brelease\b"
    r"|\bthe file['’]s version\b|\b(?:with|against) the app['’]s\b"
)
COMPARE_RE = r"(?i)\bcompar\w*|\bagainst\b|\bversus\b|\bvs\.?\b|\bnewer\b|\bolder\b"
# The server's re-check denied or replaced (S14).
RECHECK_RE = (
    r"(?i)\b(?:the server|it)\s+(?:does not|doesn['’]t|never|won['’]t|will not|no longer|need not"
    r"|needn['’]t)\s+(?:re-?check|check|validate|verify)\w*|\b(?:never|not|no longer)\s+"
    r"re-?checked\b|\bchecks?\s+(?:in the browser\s+)?(?:are|is)\s+(?:final|enough|sufficient"
    r"|authoritative)\b|\btrusts?\s+(?:the|this)\s+(?:browser|client|check)\w*"
    r"|\bthe server\s+skips\b|\binstead of the server\b|\b(?:guard|check)s?\b[^.;:]{0,40}?"
    r"\breplaces?\s+the server|\bthe server\s+(?:accepts?|takes?)\s+(?:what|whatever)\s+the"
    r"\s+(?:browser|client)\b|\brel(?:y|ies)\s+on\s+the\s+(?:browser|client)"
)
# A string from the file shown past its cap (S13).
UNCAPPED_RE = (
    r"(?i)\b(?:shown|printed|rendered|displayed|spoken|copied|named)\s+(?:in full|whole(?! or not)"
    r"|uncapped|untruncated|unshortened|at any length|without (?:a |any )?(?:cap|limit|ellipsis))\b"
)
UNCAPPED_BARE_RE = (
    r"(?i)\b(?:is|are) never (?:shortened|truncated|capped)\b|\bno cap\b|\buncapped\b"
)
# Raw file content echoed, logged, cached or sent before the import (Condition 1).
RAW_RE = (
    r"(?i)\b(?:quotes?|echo(?:es|ed)?|repeats?|reproduces?)\s+(?:the\s+)?(?:file['’]s\s+|its\s+)?"
    r"(?:own\s+)?(?:offending\s+|raw\s+|original\s+)?(?:line|lines|text|content|contents|source"
    r"|json)\b"
    r"|\b(?:prints?|shows?|displays?|renders?|copies)\s+(?:the\s+)?(?:file['’]s\s+|its\s+)?"
    r"(?:offending|raw|original)\s+(?:line|lines|text|content|contents|source|json)\b"
    r"|\b(?:offending|raw|original)\s+(?:line|lines|text|content|contents|source|json)"
    r"(?:\s+of\s+(?:the|this)\s+file)?\s+(?:is|are|gets?)\s+(?:quoted|echoed|repeated|shown"
    r"|displayed|printed|reproduced|rendered|copied)\b"
    r"|\b(?:server|parser)['’]s\s+(?:own\s+)?(?:error|message|words|sentence|text|reply)"
    r"(?:\s+(?:text|message|words|sentence))?\s+(?:(?:is|are)\s+(?:shown|displayed|printed"
    r"|quoted|rendered|repeated)|appears?|shows)\b"
    r"|\b(?:is|are|gets?)\s+(?:uploaded|logged|cached|echoed)\b"
    r"|\buploaded to the server\b|\b(?:is|are)\s+sent to (?:the server|analytics|support)\b"
)
# A file that grants the exporter anything (Condition 1's privilege hazard).
PRIVILEGE_RE = (
    r"(?i)\b(?:owned by|shared with|belongs? to|access to|grants?|keeps?)\s+(?:the\s+)?"
    r"exporter(?:['’]s)?\b|\bthe exporter['’]s (?:pin|accounts?|access|role|permissions?)\b"
    r"|\bcarr(?:y|ies)\s+(?:an?\s+|the\s+|your\s+|their\s+)?(?:accounts?\b(?![\s-](?:filter|scoped))"
    r"|credentials|api keys?"
    r"|tokens?|(?:account\s+)?bindings?|account ids?)\b"
)
# A claim this text-first spec cannot make (A4): a sign-off, a session, a lane as authority.
HONESTY_RE = (
    r"(?i)\bapproved\b|\bsigned off\b|\bsign-off (?:is |was )?(?:given|recorded|done)\b"
    r"|\bparticipants?\b|\bsession with\b|\bwe (?:measured|tested|observed|found)\b"
    r"|\busers? (?:said|found|reported|preferred)\b|\blanes?\b|\b(?:hcl|hpe)-worker\b"
)
HONESTY_OK = (
    "the copy signed off on the trust claims",
    "the CDO sign-off recorded",
    "owner's approved comment",
)
# T2 restated outside §6 (A1: stated once).
T2_RESTATE_RE = (
    r"(?i)\block(?: glyph)? leads?\b|\bleading the label\b|\bsecond line\b|\bnative role\b"
    r"|\bin the tab order\b|\baria-disabled\b|\bdisabled with a visible reason\b"
)
# A focus claim (S20): the control a focus statement names.
FOCUS_CONTROLS = (
    r"Cancel|Choose another file|Choose file…|Close|Import as new workspace|Import anyway|Try again"
    r"|Download file|Copy report|the title|the heading|the message|×"
)
FOCUS_CLAIM_RE = (
    rf"(?i)\bfocus(?:es|ed)?\s+(?:\w+\s+){{0,3}}?(?:on|to|onto)\s+(?P<a>{FOCUS_CONTROLS})"
    rf"|(?P<b>{FOCUS_CONTROLS})\s*,?\s+(?:the\s+\w+,\s+)?(?:is\s+)?"
    rf"(?:focused|takes focus|gets focus"
    rf"|has focus|holds focus)\b|\btab\s+(?:starts|begins)\s+(?:on|at)\s+(?P<c>{FOCUS_CONTROLS})"
)
REJECTION_CTX_RE = (
    r"(?i)\breject(?:ion|ions|ed)\b|\brefusals?\b|\brefused-\w+|\brejected-\w+"
    r"|\bnothing was imported\b"
)
# The keep scope (S11) reads every form of the verbs too: "the server refuses the file", "a refused
# file", "it rejects" are refusals whose keep claims count, wherever the sentence stands.
REFUSED_RE = REJECTION_CTX_RE + r"|\brefus(?:e|es|ed|ing)\b|\breject(?:s|ing)?\b"
# Where another control may take focus on a refusal: the clause names its frame.
FOCUS_EXCEPT = {
    "cancel": r"(?i)\blimit\b|\bbudget\b|\bconfirm\b|\bexport",
    "close": r"(?i)\bunanswered\b|\bunconfirmed\b|\bnever came\b|\bcreating\b|\breport\b|\bexport",
    "choose file…": r"(?i)\bpass\b|\bpreview\b|\bvalidating\b|\bpick",
    "import as new workspace": r"(?i)\bcreating\b|\bleg\b|\bbudget\b|\bconfirm\b|\bpreview\b",
}
# Renderings the text quotes beside the fixture's: a file the owner renamed (§2.4) and the
# alternative way on offered to the owner for the newer refusal (D09-Q7).
QUOTE_EXAMPLES = (
    "Exported Scalping as desk-copy.json.",
    "Export it again from an app that writes format version 1, or update this app.",
)
# A dialog control named beside a lock or a gated look (A1 in prose: a sentence about the
# control, read near it) and the T2 statements that name their leg, role or section.
CONTROL_WORDS = (
    "|".join(re.escape(c) for c in CONTROL_NAMES if c != "Export…")
    + r"|\bthe (?:dialog's )?(?:primary|verb|import verb)\b"
    + r"|\bimport(?= (?:is|stays|remains|can|cannot|can['’]t|becomes|turns|waits)\b)"
)
T2_CONTEXT_RE = (
    r"(?i)(?=.*(?:\bT2\b|\block(?:ed)?\b|CMP-079|RbacGate))(?=.*(?:rbac\.|Viewer|view-as|viewing as"
    r"|§6|\blegs?\b|\brole\b|workspaces:write|permission|workspace\.limit\.count|\blimit\b"
    r"|SCR-026/entry-|import-leg-lost))"
)
# A role or a permission placed on Export… (S15): read on the availability frame too, whose own
# words (unavailable, hidden) are an absence, never a gate (Condition 2: Export… is a read).
ROLE_GATE_RE = (
    r"(?i)\bonly (?:for|to) (?:an? |the )?(?:owner|manager|viewer|admin)s?\b"
    r"|\b(?:owner|manager|viewer|admin)s? only\b|\b(?:needs?|requires?) (?:the |a |an )?"
    r"(?:\w+ )?(?:role|permission)\b|\brbac\.\w+|\bworkspaces:write\b|\bt2\b|\bcmp-079\b"
    r"|\brbacgate\b"
)
EXPORT_STEMS = GATE_WORDS + r"|\bt2\b|\block(?:s|ed|ing)?\b|\bworkspaces:write\b|\blegs?\b"
# Numbers quoted from a draft or a checklist, each a C-row's evidence (S18 allows them by name).
QUOTED_NUMBERS = {
    "16.7 ms": "BQ-6's draft (D09-C15)",
    "44 px": "BQ-13's draft (D09-C19)",
    "2 panels": "`14:636`'s checklist item, quoted (D09-C7)",
}
# The base zoom a 200 % frame is measured against.
BASE_ZOOM = 100
# The Included list names only what the bundle holds (BQ-2 RULED): nothing the Excluded list
# names, and no density, is ever said to be in it.
INCLUDED_CTX_RE = r"(?i)\bincluded list\b|\bthe file includes\b|\bincluded item\b"
TICKET_RE = r"(?i)\bticket\b"
INCLUDED_VERB_RE = r"\bnames?\b|\blists?\b|\bincludes?\b|\bholds?\b|\bcarries\b|\bshows?\b"
INCLUDED_EXTRA_RE = (
    r"(?i)\bdensit\w*|\bapi keys?\b|\bcredentials\b|\btokens?\b|\benvironment\b|\balert\b"
    r"|\bp&l\b|\bpositions or orders\b|\baccount ids?\b|\baccount bindings?\b"
)
# The sentences a frame's facts are restated in, held word for word where they stand (M13).
REQUIRED = (
    ("5", "Both refusals name both numbers in the words the user reads", "versions"),
    ("7", "every rejection lists Choose another file among its exits", "exits-a3"),
)
# A sentence that speaks after the send, where a workspace may exist; a create claim anywhere else
# is a claim that something exists before Import as new workspace (S10).
POST_SEND_RE = (
    r"(?i)\bafter the send\b|\bonce the file is sent\b|\bwhen the import succeeds\b|\bsucceeded\b"
    r"|\bthe server (?:creates|has created|gave|makes)\b|\bon success\b"
    r"|\bonce the workspace exists\b"
    r"|\bsends the (?:checked )?file\b|\bin one request\b|\beverything or nothing\b"
    r"|\bone transaction\b|\bsuccessful import\b|\bthe new workspace opens\b|\bthe report\b"
    r"|\bafter (?:it|the import) (?:is|was) sent\b|\bthe import (?:goes on|finishes)\b"
    r"|\bmay have happened\b"
    r"|\b(?:when|once|after|as soon as)\s+(?:the file|it|the import|the workspace|they)\s+"
    r"(?:is|was|are|were|has been)\s+imported\b"
    r"|\bonce the (?:exported )?file is saved\b"
    r"|\bwhether\b"
)
# The account names the importer cannot see (S3): the fixture's labels however spaced, an id
# shape, an account named after "account", or a proper name a filter or a binding is said to carry.
FOREIGN_RES = (
    r"(?i)\b(?:acct|a/c)\b",
    r"(?i)\buid\b\W{0,3}\d",
    r"(?i)\baccount\s*(?:id|no\.?|number|#)\s*[:#]?\s*\d",
    r"(?i)\b(?:sub-?)?accounts?\b\s+(?:called|named|labell?ed|titled)\s+\S",
    r"\b(?:[Ss]ub-?)?[Aa]ccounts?\s*[:(]?\s*[\"'`]?(?!IDs?\b)[A-Z0-9][\w-]*",
)
FOREIGN_NAMED_RE = (
    r"\b(?:named|called|naming|labell?ed|titled)\s+[\"'`]?(?P<n>[A-Z][\w-]*(?:[ -][A-Z0-9][\w-]*)*)"
)
FOREIGN_CTX_RE = r"(?i)\bfilters?\b|\baccounts?\b|\bbindings?\b|\bdesks?\b|\bportfolios?\b"
PROPER_OK = {"Scalping", "Wall", "Positions", "Import", "Export", "Layout", "Order-flow"}
# An account word followed by a name-like token in any case (MAJOR 3 of the delta check: "the
# source account alpha-desk", "account alpha", "the colleague's sub-account hedge-2"): the token
# is a name unless it is one of the spec's own nouns or a function word after "account".
ACCOUNT_TOKEN_RE = r"(?i)\b(?:sub-?)?accounts?\b(?:['’]s)?\s*[:(#]?\s*[\"'`]?(?P<tok>[^\W_][\w.-]*)"
ACCOUNT_WORDS = """
    a an the and or nor of for at to in on from with by as than that which whose who it its they
    them their this these those is are was were be been being has have had can cannot could will
    would may might must should does do did never not no once ever only also still now each every
    any all both either neither one bindings binding bound scope scoped scopes filter filters id
    ids reference references setting setting's settings field fields rule rules row rows legs leg
    level levels axis remapped remap travels travel names name named label labels workspaces
    workspace pane panes picker selector menu column columns data context leg's type types
    """
ACCOUNT_NEXT_OK = frozenset(ACCOUNT_WORDS.split())


NUM_UNIT_RE = (
    r"(?<![\w.#/-])(\d{1,3}(?:[,   ]\d{3})+|\d+(?:\.\d+)?)\s*(MB|MiB|KiB|ms|px|%|fps|s"
    r"|levels?|values|nodes|layouts?|panes?|panels?|workspaces?|indicator presets?|presets?"
    r"|characters?|code points)(?![\w])"
)
LIMIT_LEAD_RE = (
    r"(?i)(?:at most|up to|limit(?: is| of|:)|cap(?:ped)?(?: is| at| of|:)|no more than"
    r"|maximum(?: of)?|max|holds?|over|more than|deeper than|within|beyond|exceeds?)\s*"
    r"(?:a |an |the )?$"
)
LIMIT_TAIL_RE = r"(?i)^\s*(?:limit|cap|maximum|max)\b"
UNIT_FAMILY = {
    "mb": "mb",
    "mib": "mib",
    "kib": "kib",
    "ms": "ms",
    "px": "px",
    "%": "pct",
    "fps": "fps",
    "s": "s",
    "level": "depth",
    "levels": "depth",
    "values": "nodes",
    "nodes": "nodes",
    "layout": "layouts",
    "layouts": "layouts",
    "pane": "panes",
    "panes": "panes",
    "panel": "panes",
    "panels": "panes",
    "workspace": "workspaces",
    "workspaces": "workspaces",
    "indicator preset": "presets",
    "indicator presets": "presets",
    "preset": "presets",
    "presets": "presets",
    "character": "chars",
    "characters": "chars",
    "code points": "chars",
}
# The show-delay BQ-9 rules for the import (its default, ruled as proposed; PROPOSED for the
# export).
SHOW_DELAY_MS = 150


NUMBER_SETS: dict[int, tuple[dict[str, set[float]], dict[str, set[float]]]] = {}


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
27 | import: the send's answer never came | SCR-026/refused-unconfirmed
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
    "the intervals": "intervals",
}
AC_IDS = (
    [f"AC-{i}" for i in range(1, 7)]
    + [f"DL-{i}" for i in range(1, 22)]
    + [f"DoD-{i}" for i in range(1, 12)]
)
TRACE_STATUS = ("done", "heuristic-only", "routed", "text pending")
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
# key count — every marker key the spec carries and exactly how many times (M8: a marker
# deleted or added unpinned is a FAIL).
# --- held whole: generated from the spec, then reviewed; a change here is a change there ---
PRODUCERS = {
    "SCR-025/export-entry": (
        "Export… opened from SCR-025's Share section (E15-D08, PENDING by name), the tab's "
        "`[⋯]` (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored workspace"
    ),
    "SCR-025/export-unavailable": (
        "the viewer's unsaved default (`D03:583`, `D03:625`), or a workspace with no stored "
        "copy (`D03:384`)"
    ),
    "SCR-025/export-preparing": (
        "Export… chosen on the stored workspace Scalping; `exportWorkspace` called "
        "(`22:12676`), its bundle not back yet"
    ),
    "SCR-025/export-preview": (
        "the bundle arrived and passed the check of §2.3: the preview is built from it and "
        "Download file saves that same bundle (`D02:511`)"
    ),
    "SCR-025/export-failed": (
        "`exportWorkspace` answered `store_unavailable` or nothing (`D02:511`, `FL:139`); the "
        "same frame for a `403` or `404`, for a bundle the check of §2.3 declines and for a "
        "failed write (§2.4)"
    ),
    "SCR-025/export-done": ("the save sheet returned a file and its write ended, whole (§2.4)"),
    "SCR-025/export-cancelled": ("the OS save sheet closed without saving (`FL:146`)"),
    "SCR-025/export-reflow-200": ("the export dialog at 200 % zoom (`05:131`)"),
    "SCR-026/entry": (
        'an Owner or Manager session under the workspace limit opens "+" or the rail\'s '
        "workspace menu (`D03:365`; the rail's item is D09-A22's)"
    ),
    "SCR-026/entry-view-as": (
        'a session viewing as alex opens "+" or the rail\'s workspace menu (`D02:519`, '
        "`D03:564`; the rail's item, D09-A22)"
    ),
    "SCR-026/entry-permission": (
        'a Viewer session opens "+" or the rail\'s workspace menu (`04:1139`, `D03:564`; the '
        "rail's item, D09-A22)"
    ),
    "SCR-026/entry-limit": (
        'an Owner session at the workspace limit opens "+" or the rail\'s workspace menu '
        "(`22:8525`, `D03:564`; the rail's item, D09-A22)"
    ),
    "SCR-026/pick": ("Import… chosen: the dialog opens empty (`D02:513`)"),
    "SCR-026/drag-over": ("one .json file dragged over the zone"),
    "SCR-026/drag-over-rejected": (
        "two files, or a file whose type is not JSON, dragged over the zone"
    ),
    "SCR-026/validating": ("`scalping.json` chosen: the worker checks it (`D02:515`, `14:633`)"),
    "SCR-026/creating": (
        "Import as new workspace pressed on a valid preview: the file is sent once"
    ),
    "SCR-026/import-leg-lost": (
        "the session lost its permission while the dialog was open (`D02:645`)"
    ),
    "SCR-026/cancelled": ("Cancel, `Esc` or × before the send (`FL:162`)"),
    "SCR-026/compact": ("the import dialog at the compact density"),
    "SCR-026/reflow-200": ("the import dialog at 200 % zoom (`05:131`)"),
    "SCR-026/preview": ("`scalping.json` passed every step: §4.2 is its table (`D02:516`)"),
    "SCR-026/preview-migrated": (
        "a format version 1 file opened by a later app that reads format version 2 (E15-S07 "
        "migrates it forward, `BL:1111`)"
    ),
    "SCR-026/preview-over-budget": (
        "`wall.json` passed every step and the layout that opens, Wall, estimates over the "
        "frame budget (`D02:133`)"
    ),
    "SCR-026/budget-confirm": (
        "Import as new workspace pressed on `SCR-026/preview-over-budget` (`D02:292`, `D03:629`)"
    ),
    "SCR-026/report": (
        "the import succeeded: the new workspace opened in a tab behind the dialog (`D02:520`)"
    ),
    "SCR-026/rejected-version-newer": (
        "a file whose `schema_version` is newer than this app reads (`D02:517`, `11:2871`)"
    ),
    "SCR-026/rejected-version-older": (
        "a file below the oldest format version this app reads (BQ-4)"
    ),
    "SCR-026/rejected-malformed": (
        "a file missing a required key (`D02:518`); its variants: a parse error, a layout over "
        "the pane limit, too many layouts, too many indicator presets"
    ),
    "SCR-026/rejected-oversized": ("a file over the size cap (`D02:518`, `BL:1136`)"),
    "SCR-026/rejected-wrong-type": (
        "`report.csv` dropped: the picker filters by type, a drop does not"
    ),
    "SCR-026/rejected-nodes": (
        "a file nested deeper than the depth limit (`22:19626`); over the node count is its "
        "variant (`BL:1136`)"
    ),
    "SCR-026/refused-limit": (
        "another window reached the workspace limit first: the send answered `409 "
        "limit_reached` (`FL:164`)"
    ),
    "SCR-026/refused-server": (
        "the server's own re-check refused the file at the send (`422 validation_failed`)"
    ),
    "SCR-026/refused-unconfirmed": (
        "the send's answer never came: a timeout or a dropped connection after the file was "
        "sent (D09-G1)"
    ),
}
COPY_KEYS = {
    "SCR-025/export-entry": ("`e15.export.menu_item`"),
    "SCR-025/export-unavailable": ("`e15.export.menu_item` · `ws.export.unstored`"),
    "SCR-025/export-preparing": (
        "`e15.export.title` · `e15.export.close` · `e15.export.preparing` · `e15.export.cancel`"
    ),
    "SCR-025/export-preview": (
        "`e15.export.title` · `e15.export.close` · `e15.export.unsaved` · "
        "`e15.export.included` · `e15.export.excluded` · `e15.export.caveat` · "
        "`e15.export.over_limit` · `e15.export.cancel` · `e15.export.download`"
    ),
    "SCR-025/export-failed": (
        "`e15.export.title` · `e15.export.close` · `e15.export.failed` · "
        "`e15.export.failed_gone` · `e15.export.failed_unlisted` · `e15.export.save_failed` · "
        "`e15.export.cancel` · `e15.export.retry`"
    ),
    "SCR-025/export-done": (
        "`e15.export.title` · `e15.export.close` · `e15.export.done` · `e15.export.excluded` · "
        "`e15.export.close_button`"
    ),
    "SCR-025/export-cancelled": (
        "`e15.export.title` · `e15.export.close` · `e15.export.unsaved` · "
        "`e15.export.included` · `e15.export.excluded` · `e15.export.caveat` · "
        "`e15.export.over_limit` · `e15.export.cancel` · `e15.export.download`"
    ),
    "SCR-025/export-reflow-200": ("—"),
    "SCR-026/entry": ("`e15.import.menu_item`"),
    "SCR-026/entry-view-as": ("`e15.import.menu_item` · `rbac.view_as`"),
    "SCR-026/entry-permission": ("`e15.import.menu_item` · `rbac.permission`"),
    "SCR-026/entry-limit": ("`e15.import.menu_item` · `workspace.limit.count`"),
    "SCR-026/pick": (
        "`e15.import.title` · `e15.import.close` · `e15.import.trust` · `e15.import.choose` · "
        "`e15.import.drop_hint` · `e15.import.help` · `e15.import.cancel`"
    ),
    "SCR-026/drag-over": ("`e15.import.drop_active`"),
    "SCR-026/drag-over-rejected": ("`e15.import.drop_rejected`"),
    "SCR-026/validating": ("`e15.import.checking` · `e15.import.cancel`"),
    "SCR-026/creating": ("`e15.import.confirm` · `e15.import.close_view`"),
    "SCR-026/import-leg-lost": ("`e15.import.confirm` · `rbac.permission`"),
    "SCR-026/cancelled": ("—"),
    "SCR-026/compact": ("—"),
    "SCR-026/reflow-200": ("—"),
    "SCR-026/preview": (
        "`e15.import.caption` · `e15.import.col.item` · `e15.import.col.type` · "
        "`e15.import.col.action` · `e15.import.col.reason` · `e15.import.action.add` · "
        "`e15.import.action.drop` · `e15.import.action.remap` · "
        "`e15.import.reason.unknown_kind` · `e15.import.reason.account` · "
        "`e15.import.reason.remap` · `e15.import.clash` · `e15.import.cancel` · "
        "`e15.import.confirm`"
    ),
    "SCR-026/preview-migrated": ("`e15.import.caption` · `e15.import.migrated`"),
    "SCR-026/preview-over-budget": ("`e15.import.caption_budget` · `e15.import.budget`"),
    "SCR-026/budget-confirm": (
        "`layout.cost.import.title` · `layout.cost.import.body` · `layout.cost.import.confirm` "
        "· `e15.import.cancel`"
    ),
    "SCR-026/report": (
        "`e15.import.report.heading` · `e15.import.report.done` · `e15.import.report.caption` "
        "· `e15.import.report.copy` · `e15.import.report.copied` · `e15.import.report.close`"
    ),
    "SCR-026/rejected-version-newer": (
        "`e15.import.rejected.version_newer` · `e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/rejected-version-older": (
        "`e15.import.rejected.version_older` · `e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/rejected-malformed": (
        "`e15.import.rejected.malformed` · `e15.import.rejected.parse` · "
        "`e15.import.rejected.panes` · `e15.import.rejected.layouts` · "
        "`e15.import.rejected.presets` · `e15.import.rejected.invalid` · "
        "`e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/rejected-oversized": (
        "`e15.import.rejected.oversized` · `e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/rejected-wrong-type": (
        "`e15.import.rejected.wrong_type` · `e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/rejected-nodes": (
        "`e15.import.rejected.depth` · `e15.import.rejected.nodes` · "
        "`e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/refused-limit": (
        "`e15.import.nothing` · `e15.import.refused.limit` · `e15.import.cancel`"
    ),
    "SCR-026/refused-server": (
        "`e15.import.nothing` · `e15.import.refused.server` · `e15.import.refused.store` · "
        "`e15.import.refused.size` · `e15.import.choose_another` · `e15.import.cancel`"
    ),
    "SCR-026/refused-unconfirmed": ("`e15.import.refused.unconfirmed` · `e15.import.close_view`"),
}
DESCRIPTIVE: dict[str, tuple[str, ...]] = {
    "SCR-025/export-entry": (
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "Focus",
    ),
    "SCR-025/export-unavailable": (
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "Focus",
    ),
    "SCR-025/export-preparing": (
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "Timing",
        "Focus",
    ),
    "SCR-025/export-preview": (
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "Description",
        "Focus",
    ),
    "SCR-025/export-failed": (
        "Variants, PROPOSED, the same frame with its own sentence",
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "Focus",
    ),
    "SCR-025/export-done": (
        "Components",
        "Layout (comfortable / compact)",
        "Tokens (dark and light, the same names)",
        "File name",
        "Focus",
    ),
    "SCR-025/export-cancelled": ("Components, layout and tokens", "Focus"),
    "SCR-025/export-reflow-200": ("Layout",),
    "SCR-026/entry": (),
    "SCR-026/entry-view-as": (),
    "SCR-026/entry-permission": (),
    "SCR-026/entry-limit": (),
    "SCR-026/pick": (),
    "SCR-026/drag-over": (),
    "SCR-026/drag-over-rejected": (),
    "SCR-026/validating": (),
    "SCR-026/creating": (),
    "SCR-026/import-leg-lost": (),
    "SCR-026/cancelled": (),
    "SCR-026/compact": (),
    "SCR-026/reflow-200": (),
    "SCR-026/preview": (),
    "SCR-026/preview-migrated": (),
    "SCR-026/preview-over-budget": (),
    "SCR-026/budget-confirm": (),
    "SCR-026/report": (),
    "SCR-026/rejected-version-newer": (
        "anatomy",
        "tokens",
        "",
        "redlines",
        "",
        "versions",
        "keys",
        "",
    ),
    "SCR-026/rejected-version-older": (
        "anatomy",
        "tokens",
        "",
        "redlines",
        "",
        "versions",
        "keys",
        "",
    ),
    "SCR-026/rejected-malformed": (
        "anatomy",
        "tokens",
        "",
        "redlines",
        "",
        "key",
        "",
        "counts",
        "keys",
        "",
    ),
    "SCR-026/rejected-oversized": ("anatomy", "tokens", "", "redlines", "", "size", "", "keys", ""),
    "SCR-026/rejected-wrong-type": (
        "anatomy",
        "tokens",
        "",
        "redlines",
        "",
        "type",
        "",
        "",
        "keys",
        "",
    ),
    "SCR-026/rejected-nodes": ("anatomy", "tokens", "", "redlines", "", "scan", "keys", ""),
    "SCR-026/refused-limit": ("anatomy", "", "tokens", "", "redlines", "", "race", ""),
    "SCR-026/refused-server": ("anatomy", "tokens", "", "redlines", "", "key", "", "keys", ""),
    "SCR-026/refused-unconfirmed": ("anatomy", "", "tokens", "", "redlines", "", "way on"),
}
BOARDS = {
    "01": (
        "`SCR-025/export-preview`, `SCR-025/export-done`",
        "dark",
    ),
    "02": (
        "`SCR-026/pick`, with the redlines of §3",
        "dark",
    ),
    "03": (
        "`SCR-026/validating`, `SCR-026/preview`",
        "dark",
    ),
    "04": (
        "`SCR-026/rejected-version-newer`, `SCR-026/rejected-version-older`, "
        "`SCR-026/rejected-malformed`, `SCR-026/rejected-oversized`, "
        "`SCR-026/rejected-wrong-type`, with the CVD strip",
        "dark",
    ),
    "05": (
        "`SCR-026/preview-over-budget`, `SCR-026/budget-confirm`, `SCR-026/refused-limit`",
        "dark",
    ),
    "06": (
        "`SCR-026/report`",
        "dark",
    ),
    "07": (
        "`SCR-026/entry`, `SCR-026/entry-view-as`, `SCR-026/entry-permission`, "
        "`SCR-026/entry-limit`, `SCR-026/import-leg-lost`, `SCR-025/export-entry`, "
        "`SCR-025/export-unavailable`",
        "dark",
    ),
    "08": (
        "the keyboard, focus and announcement walk of §7, from the entry through choosing a "
        "file and the table to the report",
        "dark",
    ),
    "09": (
        "`SCR-026/pick`, `SCR-026/preview`, `SCR-026/rejected-version-newer`",
        "light",
    ),
    "10": (
        "`SCR-025/export-preview`, `SCR-026/report`",
        "light",
    ),
}
KEYBOARD_HEAD = "| Frames | Initial focus | Tab order | `Enter` | `Esc` | Focus on close |"
KEYBOARD = {
    (
        "the menus: `SCR-025/export-entry`, `SCR-025/export-unavailable`, `SCR-026/entry`, "
        "`SCR-026/entry-view-as`, `SCR-026/entry-permission`, `SCR-026/entry-limit`"
    ): (
        "the menu's first item (CMP-041)",
        "arrows, not `Tab`: `↑` and `↓` reach every item, the T2 item and the unavailable one "
        "included",
    ),
    ("`SCR-025/export-preparing`"): (
        "Cancel",
        "× → Cancel",
    ),
    ("`SCR-025/export-preview`, `SCR-025/export-cancelled`"): (
        'the title (`tabindex="-1"`) on the preview; Download file once the save sheet has '
        "closed unsaved",
        "× → the body, a stop only while it scrolls → Cancel → Download file",
    ),
    ("`SCR-025/export-failed`"): (
        "Try again",
        "× → Cancel → Try again",
    ),
    ("`SCR-025/export-done`"): (
        "Close",
        "× → Close",
    ),
    ("`SCR-026/pick`, `SCR-026/drag-over`, `SCR-026/drag-over-rejected`, `SCR-026/validating`"): (
        "Choose file…",
        "× → Choose file… → Cancel",
    ),
    ("`SCR-026/preview`, `SCR-026/preview-migrated`, `SCR-026/preview-over-budget`"): (
        "Choose file…, where it already was: the preview's arrival never moves focus (`05:96`)",
        "× → Choose file… → the table's scroll region → Cancel → Import as new workspace",
    ),
    ("`SCR-026/budget-confirm`, a CMP-044 `alertdialog` stacked over the preview"): (
        "Cancel",
        "Cancel → Import anyway; it has no close ×",
    ),
    ("`SCR-026/creating`"): (
        "Import as new workspace, busy, where it was",
        "× → the table's scroll region → Close → Import as new workspace (Choose file… and the "
        "zone have left the body, §3.5)",
    ),
    ("`SCR-026/import-leg-lost`"): (
        "Import as new workspace, where it was: focus never moves (§6)",
        "× → Choose file… → the table's scroll region → Cancel → Import as new workspace, "
        "still a stop (§6)",
    ),
    ("the six rejections and `SCR-026/refused-server`"): (
        "Choose another file",
        "× → Choose file… → Cancel → Choose another file",
    ),
    ("`SCR-026/refused-limit`"): (
        "Cancel, the named fallback once the verb has left the footer (`15:468`)",
        "× → Cancel",
    ),
    ("`SCR-026/refused-unconfirmed`"): (
        "Close",
        "× → Close",
    ),
    ("`SCR-026/report`"): (
        'the heading "Import report" (`tabindex="-1"`), on arrival only',
        "× → the table's scroll region → Copy report → Close",
    ),
    ("`SCR-026/cancelled`"): (
        "—: the dialog has closed",
        "—",
    ),
    ("`SCR-025/export-reflow-200`, `SCR-026/reflow-200`, `SCR-026/compact`"): (
        "as the frame it reflows",
        "as that frame",
    ),
}
PINNED: dict[str, tuple[str, tuple[str, ...]]] = {
    (
        "| Part | Component and variant | Tokens (one set of names; dark, light and high "
        "contrast resolve them, §8) | Redlines (comfortable; compact changes only the control "
        "heights) |"
    ): (
        "pinned-row",
        (
            '| The message | CMP-027 `inline`, severity `error`, `live="polite"` overriding '
            'the `role="alert"` default (`15:306`; slice 4\'s H37, `S4:919`) | the glyph '
            "CMP-019 `danger` at `size.icon` in `color.status.danger.strong`, `x-circle` once "
            "E05-T06 registers it (`15:307`); the words `type.ui.body` + `color.text.primary` "
            "on the card's `color.surface.overlay`, no fill (§8 rows 1 and 7) | the glyph 16 "
            "<!-- audit:redline.size.icon=16 --> px, `space.inset.xs` to the words; "
            "`space.stack.md`, 12 <!-- audit:redline.space.stack.md=12 --> px, above and below "
            "the message; the words wrap, never truncate |",
            "| A key or a file name inside the message | a text node of its own, never a link "
            "(§5.5) | `type.num.sm` (mono) + `color.text.primary` | inline in the sentence; a "
            "key at most 64 <!-- audit:design.key_cap=64 --> characters, a file name at most "
            "40 <!-- audit:design.file_cap=40 --> characters, an ellipsis past either |",
            "| The version numbers | whole numbers, parsed and read (§5.3) | `type.num.sm` + "
            "`color.text.primary` | inline in the sentence |",
            "| Choose file… and its words | CMP-067 behind a CMP-001 `secondary` button (§3) | "
            "as `SCR-026/pick` | as `SCR-026/pick` |",
            "| The footer | CMP-001 `secondary` Cancel, then CMP-001 `primary` Choose another "
            "file; on `SCR-026/refused-limit` Cancel alone; on `SCR-026/refused-unconfirmed` "
            "Close alone, a CMP-001 `primary` | `color.action.secondary.default` + "
            "`color.text.primary`; `color.action.primary.default` + `color.text.on-action` (§8 "
            "rows 18 and 19) | 32 <!-- audit:redline.size.control.comfortable=32 --> px tall, "
            "24 <!-- audit:redline.size.control.compact=24 --> px at compact; "
            "`space.inset.sm`, 8 <!-- audit:redline.space.inset.sm=8 --> px, apart; "
            "`space.dialog.padding`, 24 <!-- audit:redline.space.dialog.padding=24 --> px, "
            "inside the card |",
            "| Focus on arrival | CMP-039's ring on Choose another file, on Cancel at the "
            "limit, or on Close after an unanswered send | `color.focus.ring` at "
            "`border.focus`, 2 <!-- audit:redline.border.focus=2 --> px (§8 row 20) | outside "
            "the control, never clipped by the footer |",
        ),
    ),
    (
        "| Case | Frame | Check (§5.4) | The problem and the limit it names | The way on | "
        "`layout.import_rejected{reason}` |"
    ): (
        "pinned-row",
        (
            "| a newer format version | `SCR-026/rejected-version-newer` | 4 version | both "
            "format versions, the file's 2 <!-- audit:fixture.newer_format=2 --> and this "
            "app's 1 <!-- audit:fixture.app_format=1 --> | \"Export it again from a version 1 "
            'app, or update this app."; Choose another file | `version-newer` |',
            "| an older format version, unsupported | `SCR-026/rejected-version-older` | 4 "
            "version | both, the file's 0 <!-- audit:fixture.older_format=0 --> and the oldest "
            'this app reads | "Update the app that exported it, then export it again."; Choose '
            "another file | `version-older` |",
            "| a required key missing | `SCR-026/rejected-malformed` | 3 schema | the key, in "
            "mono | Choose another file | `malformed` |",
            "| not JSON at all | its variant | 2 parse | the line where the text stops being "
            "JSON | Choose another file | `malformed` |",
            "| a layout over the panel limit | its variant | 3 schema | the count and the "
            "limit, at most 16 <!-- audit:contract.panes_max=16 --> panels a layout | Choose "
            "another file | `malformed` |",
            "| too many layouts | its variant | 3 schema | the count and the limit, at most 32 "
            "<!-- audit:contract.layouts_max=32 --> layouts a workspace | Choose another file "
            "| `malformed` |",
            "| too many indicator presets | its variant | 3 schema | the count and the limit, "
            "at most 200 <!-- audit:contract.presets_max=200 --> indicator presets a file | "
            "Choose another file | `malformed` |",
            "| a file over the size limit | `SCR-026/rejected-oversized` | 1 size | the file's "
            "size and the limit, at most 2 <!-- audit:contract.size_mb=2 --> MB | Choose "
            "another file | `oversized` |",
            "| not a JSON file | `SCR-026/rejected-wrong-type` | 1 size, its type first | the "
            'file\'s name | "Choose a .json workspace file."; Choose another file | '
            "`wrong-type` |",
            "| nested too deeply | `SCR-026/rejected-nodes` | 2 parse | the limit, at most 16 "
            "<!-- audit:contract.depth=16 --> levels | Choose another file | `malformed` (BQ-5 "
            "RULED) |",
            "| too many values | its variant | 2 parse | the limit, at most 10,000 <!-- "
            "audit:contract.nodes=10000 --> values, PROPOSED (D09-G5) | Choose another file | "
            "`malformed` |",
            "| the workspace limit, met at the send | `SCR-026/refused-limit` | the send | the "
            'limit, 32 <!-- audit:contract.workspaces_max=32 --> workspaces | "Delete one, '
            'then import again."; Cancel | none (§5.5) |',
            "| the server's re-check, at the send | `SCR-026/refused-server` | the send | the "
            "first key the server named, in mono | Choose another file | none (§5.5) |",
            "| a file larger than the server takes, `413` | its variant | the send | that the "
            "server takes no file this large; the number is the server's (D09-G5) | Choose "
            "another file | none (§5.5) |",
            "| the send's answer never came | `SCR-026/refused-unconfirmed` | the send | that "
            'the import could not be confirmed | "Check your workspaces before importing '
            'again."; Close | none (§5.5) |',
        ),
    ),
    ("| The file's `schema_version` | Outcome | Frame | Words (§9) | Event |"): (
        "pinned-row",
        (
            "| above the newest this app reads (the fixture: 2 <!-- "
            "audit:fixture.newer_format=2 --> against 1 <!-- audit:fixture.app_format=1 -->) | "
            "refused whole, both versions named, then the way on: export it again from an app "
            "that writes the older format, or update this app (AC 2; `11:2871`; `D02:517`) | "
            "`SCR-026/rejected-version-newer` | `e15.import.rejected.version_newer` | "
            "`version-newer` |",
            "| the newest this app reads | the checks go on to the registry, then the preview "
            "| `SCR-026/preview` | — | — |",
            "| older, still read (a later build, the file one format behind it) | migrated "
            "forward before the preview, which shows the migrated document, and said so above "
            'the table: "Migrated from format version 1 to 2." (E15-S07\'s rule, `BL:1136`) | '
            "`SCR-026/preview-migrated` | `e15.import.migrated` | none at the preview; on "
            "success `layout.imported` carries the file's own `schemaVersion` |",
            "| below the floor (the fixture: 0 <!-- audit:fixture.older_format=0 --> against 1 "
            "<!-- audit:fixture.app_format=1 -->) | refused whole, both versions named, then "
            "the way on: update the app that exported it, then export it again (the ticket's "
            "`version-older`) | `SCR-026/rejected-version-older` | "
            "`e15.import.rejected.version_older` | `version-older` |",
            "| absent, empty, or not a whole number | a schema failure, the key "
            '`schema_version` named in mono: "is missing" when it is absent, "isn\'t valid" '
            "otherwise (§5.4) | `SCR-026/rejected-malformed` | `e15.import.rejected.malformed` "
            "· `e15.import.rejected.invalid` | `malformed` |",
        ),
    ),
    ("| Step | Limit | Source | Past it | Words (§9) |"): (
        "pinned-row",
        (
            "| 1 size | a file of at most 2 <!-- audit:contract.size_mb=2 --> MB, read from "
            "the chosen file's size before a byte of it is read | E15-S07's default "
            "(`BL:1136`) until `22` sets the cap (D09-G5); a 2 <!-- audit:contract.size_mb=2 "
            "--> MB file is checked within 500 <!-- audit:contract.parse_ms=500 --> ms in a "
            "worker (`14:633`) | `SCR-026/rejected-oversized` | "
            "`e15.import.rejected.oversized` |",
            "| 2 parse | nesting at most 16 <!-- audit:contract.depth=16 --> levels | the "
            "server's own rule for a workspace body (`22:19626`), reused (BQ-5 RULED) | "
            "`SCR-026/rejected-nodes` | `e15.import.rejected.depth` |",
            "| 2 parse | at most 10,000 <!-- audit:contract.nodes=10000 --> values, PROPOSED | "
            'E15-S07 names a node-count limit and fuzzes "a document with 10000 nested nodes" '
            "(`BL:1136`); no contract carries a number (D09-G5) | `SCR-026/rejected-nodes`, "
            "its variant | `e15.import.rejected.nodes` |",
            "| 3 schema | the envelope's `schema_version` first, then the shape of a version "
            "this app reads: every required key and every known key's type (`22:21209–21230`) "
            "| `22:21209–21230`; an unknown key ignored by the client and refused by the "
            "server on its write path (C-6.3; `04:853`); the bundle and `ChartTemplateInput` "
            "are not closed yet (D09-G4) | `SCR-026/rejected-malformed` | "
            "`e15.import.rejected.malformed` |",
            "| 3 schema | at most 16 <!-- audit:contract.panes_max=16 --> panels a layout | "
            "the contract's 16 (`D02:133`) | `SCR-026/rejected-malformed`, its variant | "
            "`e15.import.rejected.panes` |",
            "| 3 schema | at most 32 <!-- audit:contract.layouts_max=32 --> layouts a "
            "workspace | the store's limit (`22:8725`); the bundle carries none (D09-G5) | "
            "`SCR-026/rejected-malformed`, its variant | `e15.import.rejected.layouts` |",
            "| 3 schema | at most 200 <!-- audit:contract.presets_max=200 --> indicator "
            "presets, the array whole or not at all | `22:21229–21230`, where the server also "
            "refuses the array beyond 1 MiB of preset JSON | `SCR-026/rejected-malformed`, its "
            "variant; the server's refusal is `SCR-026/refused-server` | "
            "`e15.import.rejected.presets` |",
            "| 4 version | the format versions this app reads (§5.3) | `22:21215`; D09-G2 | "
            "the two version refusals; the migrated preview | §5.3 |",
            "| 5 registry | each pane's kind and each setting against the registry | the "
            "open-ended kinds (`22:19778`); settings that never hold account ids (`22:19838`) "
            "| never a rejection: an unknown kind or an account-scoped setting is a Drop row "
            "(§4.2) | `e15.import.reason.unknown_kind` |",
            "| the send | at most 32 <!-- audit:contract.workspaces_max=32 --> workspaces a "
            "user | `22:8525` | `SCR-026/refused-limit` | `e15.import.refused.limit` |",
            "| the send | everything above, checked again by the server | E15-S07 (`BL:1136`); "
            "`04:54`; C-2.12 | `SCR-026/refused-server` | `e15.import.refused.server` |",
        ),
    ),
    (
        "| # | Step | What the worker checks | The limit (the Fixture paragraph) | When it "
        "fails, or what it finds | `layout.import_rejected{reason}` |"
    ): (
        "pinned-row",
        (
            "| 1 | size | the file's type and size, from its metadata, before a byte of it "
            "reaches the parser: a file over the cap is never parsed (`BL:1136`); the type "
            "check refuses a file only when its name, read after §5.5's cleaning, does not end "
            "in `.json` and its media type is not `application/json`, so a blank type never "
            "refuses a `.json` name; a picked file's type is checked too, because `accept` "
            "only filters what the OS picker offers | 2 <!-- audit:contract.size_mb=2 --> MB, "
            "E15-S07's default (`BL:1136`), PROPOSED for `22` (D09-G5) | "
            "`SCR-026/rejected-oversized`; a dropped file that is not JSON: "
            "`SCR-026/rejected-wrong-type` | `oversized`; `wrong-type` |",
            "| 2 | parse depth / node count | the JSON, parsed in the worker with both limits "
            "counted while it parses, so a hostile file stalls a worker and never the page "
            "(`BL:1136`) | depth 16 <!-- audit:contract.depth=16 --> levels, the server's own "
            "rule for a request body (`22:19626`); 10,000 <!-- audit:contract.nodes=10000 --> "
            "values (`BL:1136`), PROPOSED (D09-G5) | `SCR-026/rejected-nodes` (the depth, with "
            "the node count its variant); invalid JSON: `SCR-026/rejected-malformed`'s parse "
            "variant, which names the line | `malformed` |",
            "| 3 | schema | first the envelope, `schema_version` present and a whole number "
            "(D09-D25), else the malformed outcome that names it; then the shape of that "
            "format version, only when this app reads it (one shape per readable version, "
            "D09-G2), against `WorkspaceBundle` (`22:21209–21230`): every required key present "
            "and every known key's value of its kind, a pane's kind an open string for a "
            "reader (`22:19778`), no layout over its panes, no workspace over its layouts, the "
            "indicator presets whole or not at all; an unknown key is ignored and never read "
            "into the app (C-6.3); a version above the newest or below the floor skips the "
            "shape and goes to step 4, so the shape never shadows the version outcome (D09-Q5) "
            "| 16 <!-- audit:contract.panes_max=16 --> panes a layout (`D02:133`); 32 <!-- "
            "audit:contract.layouts_max=32 --> layouts a workspace (`22:8725`); 200 <!-- "
            "audit:contract.presets_max=200 --> presets a file (`22:21229–21230`) | "
            "`SCR-026/rejected-malformed`: the missing key, or the known key whose value is "
            "the wrong kind, named in mono, or its panes, layouts and presets variants | "
            "`malformed` |",
            "| 4 | version | the file's `schema_version` (`22:21215`) against the format "
            "version this app reads (BQ-4 RULED): newer is refused; older and still readable "
            "is migrated forward in the worker; older than the oldest this app reads is "
            "refused | this app reads format version 1 <!-- audit:fixture.app_format=1 -->; "
            "the order of versions and the oldest one read are D09-G2's | "
            "`SCR-026/rejected-version-newer`; `SCR-026/rejected-version-older`; a migration "
            "is no failure: `SCR-026/preview-migrated` | `version-newer`; `version-older` |",
            "| 5 | per-pane registry | each pane's kind against this build's registry "
            "(`22:19778`) and each pane setting against the registry's list for its kind "
            "(`BL:1136`) | — | nothing fails here: an unknown kind is a Drop row, never a "
            "refusal (AC 3); a setting the registry marks account-scoped is a Drop row, and so "
            "is a setting it does not list for its kind, a newer build's option (D09-D35); the "
            "Positions pane is the one Remap (§4.2) | — |",
            "| — | preview | the table of §4.2, built from the document already parsed, with "
            "no second parse (`BL:1136`) | the panel budget of the layout that opens (§4.4) | "
            "over the budget: the budget line and the stacked confirm (§4.4) | "
            "`budget-exceeded`, only when that confirm is cancelled |",
        ),
    ),
    ("| Event | Frames | How it speaks | String (§9) |"): (
        "pinned-row",
        (
            "| a dialog opens | every dialog frame | no live region: read as focus enters it, "
            "the title and then what focus lands on (`15:468`) | `e15.export.title` · "
            "`e15.import.title` |",
            "| the export file is being prepared | `SCR-025/export-preparing` | CMP-038's one "
            '`role="status"` region, once (`15:409–417`) | `e15.export.preparing` |',
            "| preparing the file fails | `SCR-025/export-failed` | the CMP-027 message, "
            "polite, once | `e15.export.failed` |",
            "| the export file is saved | `SCR-025/export-done` | polite, once: the completion "
            "line | `e15.export.done` |",
            "| the save sheet closes unsaved | `SCR-025/export-cancelled` | never: the preview "
            "is as it was and focus is on Download file | — |",
            "| the check starts | `SCR-026/validating` | polite, once, through the import "
            "dialog's status region; CMP-023 is never a live region itself (`15:262–270`) | "
            "`e15.import.checking` |",
            "| the check passes | `SCR-026/preview`, `SCR-026/preview-migrated`, "
            "`SCR-026/preview-over-budget` | polite, once, through the same region: the "
            "caption, its counts first, so the summary comes before the rows (`14:632`); after "
            "the migration line on a migrated file, with the budget sentence on a file over "
            "the budget | `e15.import.migrated` · `e15.import.caption` · "
            "`e15.import.caption_budget` |",
            "| the check fails | the six rejections | the CMP-027 message, polite, once; the "
            "status region adds nothing (`S4:919`); focus moves to Choose another file once "
            "the message has been read, and the message is not that button's description, so "
            "it is read once | the six messages and their variants |",
            "| a file is dragged over the zone | `SCR-026/drag-over`, "
            "`SCR-026/drag-over-rejected` | never: the words change for the pointer's user, "
            "and the keyboard path never drags | `e15.import.drop_active` · "
            "`e15.import.drop_rejected` |",
            "| the budget confirm opens | `SCR-026/budget-confirm` | no live region: an "
            "`alertdialog` read as focus enters it, its title and its body | "
            "`layout.cost.import.title` · `layout.cost.import.body` |",
            "| Import as new workspace or Import anyway pressed | `SCR-026/creating` | nothing "
            "at the press: the button keeps its name with `aria-busy` (`15:48–57`) | — |",
            "| the import succeeds | `SCR-026/report` | polite, once: the success line; focus "
            "moves to the report's heading | `e15.import.report.done` |",
            "| the import succeeds after the view was closed | after `SCR-026/creating` | "
            "polite, once, through CMP-212's region: a persistent CMP-045 `success` toast with "
            "the success line and the action View report, which reopens the report as the "
            "dialog's final step (PROPOSED; a toast with an action never times out, "
            "`15:483–490`) | `e15.import.report.done` · `e15.import.report.view` |",
            "| a refusal arrives after the view was closed | after `SCR-026/creating` | "
            'polite, once, through CMP-212\'s region (`politeness="polite"`, as a refusal at '
            'the send speaks here, D09-C12): a persistent CMP-045 `danger` toast, "Nothing was '
            "imported.\", with the action Review, which reopens SCR-026 at the refusal's frame "
            "(PROPOSED; a toast with an action never times out, `15:483–490`) | "
            "`e15.import.nothing` · `e15.import.review` |",
            "| a send left unanswered after the view was closed | after `SCR-026/creating` | "
            "polite, once, through CMP-212's region: a persistent CMP-045 `warning` toast with "
            "the frame's words, \"We couldn't confirm the import. Check your workspaces before "
            'importing again.", and the action Review, which reopens SCR-026 at '
            '`SCR-026/refused-unconfirmed`; never "Nothing was imported.", since the import '
            "may have happened (D09-D33; PROPOSED; a toast with an action never times out, "
            "`15:483–490`) | `e15.import.refused.unconfirmed` · `e15.import.review` |",
            "| a refusal at the send | `SCR-026/refused-limit`, `SCR-026/refused-server`, "
            "`SCR-026/refused-unconfirmed` | polite, once; focus moves to the frame's named "
            "button once the message has been read, and the message is not that button's "
            "description, so it is read once. PROPOSED departure from slice 4's conventions "
            "33, which speaks a refusal at its point of action assertively (`S4:140`): the "
            "refused verb leaves the footer and focus moves with it, so an interruption would "
            "only cut that reading short (D09-C12) | `e15.import.nothing` · "
            "`e15.import.refused.limit` · `e15.import.refused.server` · "
            "`e15.import.refused.unconfirmed` |",
            '| Copy report pressed | `SCR-026/report` | CMP-033\'s "Copied", polite, once; '
            "never the copied text (`15:366`) | `e15.import.report.copied` |",
            "| a press on a T2 control | `SCR-026/entry-view-as`, `SCR-026/entry-permission`, "
            "`SCR-026/entry-limit`, `SCR-026/import-leg-lost` | polite, once per press: its "
            "reason (§6) | `rbac.view_as` · `rbac.permission` · `workspace.limit.count` |",
            "| a leg goes while the dialog is open | `SCR-026/import-leg-lost` | the shell's "
            "one access-changed announcement; the dialog adds none and focus stays (§6) | — |",
        ),
    ),
    ("| Moment | What the tree exposes (role · name · state · description) | Source |"): (
        "pinned-row",
        (
            '| the import dialog opens on `SCR-026/pick` | `dialog` · "Import workspace"; '
            'focus on the button "Choose file…", described by "or drop a workspace file here" '
            'and "JSON, up to 2 MB"; the native input is labelled by that button and stays out '
            "of the Tab order; the trust note is a `note` read in browse mode; the zone around "
            "the button has no role and no name | `15:694`; `D02:513` |",
            '| the check runs, `SCR-026/validating` | `progressbar` · named by "Checking '
            'scalping.json…" · its value the share of the five steps done, its text "Checking '
            'scalping.json… step 3 of 5"; Cancel is reached as before | `15:262–270`; '
            "`D02:515` |",
            "| `Tab` reaches the preview's table | the scroll region · named by its caption "
            '"Preview — 7 panels and 2 layouts to add · 3 dropped · 1 remapped"; inside, a '
            "`table` with that caption, four `columnheader`s — Item, Type, Action, Reason — "
            "and each Item cell a `rowheader`; each Action glyph has no name, its word is the "
            "cell's text | `15:530`; `14:632` |",
            '| a rejection, focus on Choose another file | button · "Choose another file", '
            "focused once the message's polite region has read it, e.g. \"This file was "
            "exported by format version 2 and can't be imported into format version 1. Nothing "
            'was imported. Export it again from a version 1 app, or update this app."; the '
            "message is not the button's description, so it is read once | `15:306`; `05:150` |",
            "| the malformed file's key | inside the message, plain text read in order, its "
            "punctuation as the reader's settings speak it; at most 64 <!-- "
            'audit:design.key_cap=64 --> characters, then "(shortened)" (§5.5) | `14:632` |',
            '| the budget confirm opens | `alertdialog` · "Open Wall with 12 panels?" · '
            'described by its body; focus on "Cancel" | `15:468`; `D02:292` |',
            '| the report arrives | heading · "Import report" (focused) inside a `region` '
            'named "Import report"; the success line; the table as above, its caption "Report '
            '— 7 panels and 2 layouts added · 3 dropped · 1 remapped"; the buttons "Copy '
            'report" and "Close" | `D02:520` |',
            '| the menu\'s Import… for a Viewer | menu item · "Import…" · `aria-disabled` · '
            'described by "Your role can\'t save workspaces."; the lock glyph named "Not '
            'available" leads the label | `E09D09:49`; `E09D09:89` |',
            '| the export dialog opens on `SCR-025/export-preview` | `dialog` · "Export '
            'Scalping"; focus on the title; the Included and the Excluded list are lists read '
            "in browse mode, one item per clause | `D02:511` |",
        ),
    ),
    (
        "| Included item | Built from the bundle (`22:21209–21230`) | For Scalping | Left out "
        "when |"
    ): (
        "pinned-row",
        (
            "| the layouts, with their names | `layouts[]`, each `name` (at most 40 <!-- "
            "audit:contract.name_max=40 --> characters, `22:19638`), in the bundle's order | 2 "
            "<!-- audit:fixture.export_layouts=2 --> layouts (Layout 1, Order-flow) | the "
            "workspace has no layout yet |",
            "| the panels | every pane of every layout, `layouts[].panes[]` | 7 <!-- "
            "audit:fixture.export_panels=7 --> panels | no layout holds a panel |",
            "| the symbols | each distinct `symbol` of a pane or of a drawing, in the order "
            "first met | symbols BTCUSDT, ETHUSDT | no pane or drawing names a symbol |",
            "| the sync groups | each distinct `pane_config.sync_group` | sync groups A and B "
            "| no pane is in a group |",
            "| the panel settings | each pane's `pane_config.settings` | each panel's settings "
            "| no layout holds a panel |",
            '| the drawings | `drawings[]`, with ", with their text labels" while one carries '
            "a `label` (at most 120 <!-- audit:contract.label_max=120 --> code points, "
            "`21:3300`) | 12 drawings, with their text labels | there is no drawing |",
            "| the chart templates | `chart_templates[]` | 1 chart template | there is none |",
            "| the indicator presets | `indicator_presets[]`: every live preset of the caller, "
            "never truncated (`22:21226–21230`) | 3 indicator presets | there is none |",
        ),
    ),
    ("| # | Question | Built here (the ruled outcome) | Status |"): (
        "bq-terms",
        (
            "| BQ-1 | the deliverable path, the branch, the Penpot page, the `14` / `15` edit "
            "set, the PR | this file, `docs/design/E15/E15-D09.md`, and its tool "
            "`e15_d09_import_export_audit.py`; the ticket's spec path and branch are the first "
            "two deviations; the Penpot page `E15-D09 Workspace import and export`; two "
            "content-only `14` pointer lines, after SCR-025's checklist (`14:624`) and "
            "SCR-026's (`14:636`), and PROPOSED A-rows for `14:628–629` and `14:636` (§11); no "
            "`15` edit — A-rows only (§10); the PR says `Refs #363` and `Partial:`, never a "
            "closing keyword | RULED (6396085915) |",
            "| BQ-2 | the trust claims, word for word | the Excluded list, first-class and "
            "drawn as a list, in AC 1's words: \"Never included: credentials — API keys or "
            "tokens; accounts, trade-group and user ids; environment binding (DEMO or LIVE); "
            'alert and rule bindings; P&L, positions or orders." — a C-row to `D02:511`, an '
            "extension and not a contradiction; the Included list names only what "
            "`WorkspaceBundle` holds (`22:21209–21230`); the import's trust note is `D02:513` "
            'verbatim: "A workspace file never carries credentials or account bindings. '
            'Importing creates a new workspace and changes nothing else."; the sharing claim '
            "in `22:12679`'s description is never written anywhere (its G-row names it without "
            "repeating it); the tool gates both sentences byte for byte on every frame that "
            "shows them; owner approval pending (#2701) | RULED (6396085915) — owner approval "
            "pending (#2701) |",
            "| BQ-3 | account-scoped elements on import | dropped and listed, never remapped, "
            "and no account the importer cannot see is ever named in the preview, the report "
            'or a reason: its row reads "workspaces never carry account bindings" (§4.2 row '
            '3); the word "Remap" is kept for the one true remap, the Positions pane that '
            "shows your own accounts (§4.2 row 4); `14:628–629` and the checklist item of "
            "`14:636` get PROPOSED A-rows (§11); E15-S07 receives D09-G1…G8, G13 and G14 by "
            "hand-off row (§12) | RULED (6396085915) — owner approval pending (#2701) |",
            "| BQ-4 | the version rule | a newer file refused with both versions and the "
            "constructive second sentence, no Import verb (`SCR-026/rejected-version-newer`); "
            'an older compatible file migrated forward with "Migrated from format version 1 to '
            "2.\" (E15-S07's rule, `SCR-026/preview-migrated`); an older unsupported file "
            "refused with both versions (`SCR-026/rejected-version-older`, the ticket's "
            "`version-older`); the comparison on `schema_version`, never an app version | "
            "RULED (6396085915) — owner approval pending (#2701) |",
            "| BQ-5 | size, shape and the refused parse | the five check steps in order, size "
            "→ parse depth / node count → schema → version → per-pane registry → preview; "
            "nothing is created before Import as new workspace and nothing kept after a "
            "refusal; the limits in copy rendered from the tool's facts (the Fixture "
            'paragraph), the node count PROPOSED with D09-G5; every refusal says "Nothing was '
            'imported." | RULED (6396085915) |',
            "| BQ-6 | the panel budget on a valid file | per layout, for the layout that "
            "opens: caught in the preview as the caption's last sentence and a warning line "
            "(`SCR-026/preview-over-budget`), then applied through US-LAY-001's CMP-044 "
            'confirm re-verbed "Import anyway", its Cancel focused (`SCR-026/budget-confirm`); '
            "a confirm, not a refusal, whose cancel fires `budget-exceeded` | RULED "
            "(6396085915) |",
            "| BQ-7 | the export surface and Export…'s availability | Export… in three places "
            "— SCR-025's Share section (E15-D08, PENDING by name), the tab's `[⋯]` (`D03:384`) "
            "and the rail's workspace menu (`D02:511`) — and one CMP-043 `md` dialog with the "
            "Included and Excluded lists built from the fetched bundle; Export… is a read "
            "(`22:12676`), never gated (a read): T1 for every session, view-as included; on "
            "the viewer's unsaved default it is an availability state (`D03:583`) | RULED "
            "(6396085915) |",
            "| BQ-8 | the file name and the completion | "
            "`<slug>.cv-workspace-v<schema_version>.json`, the slug the workspace name "
            "lower-cased, ASCII-folded, every other character a `-`, capped like a name "
            "(D09-G14); the fixture `scalping.cv-workspace-v1.json`; a drawn completion step "
            "naming the saved file (`SCR-025/export-done`); a dismissed save sheet keeps the "
            "preview (`SCR-025/export-cancelled`) | RULED (6396085915) |",
            "| BQ-9 | the import dialog | CMP-043 `lg` with its steps in one chrome — choose, "
            "validating, preview, the send, the report; Choose file… a real button fronting "
            "the labelled native input; the drop zone not a Tab stop; a name clash "
            "disambiguated by the server (`D02:516`); Cancel, `Esc` and × before the send "
            "close the dialog with nothing imported | RULED (6396085915) |",
            "| BQ-10 | the preview table | CMP-049 table mode, the caption first with the "
            "counts; the columns Item · Type · Action · Reason; drops and remaps first, "
            "additions after; exactly three Action words, each a word with a decorative glyph; "
            "the unknown kinds by stored name with the ticket's reason; strings from the file "
            "as text, capped (the Fixture paragraph; the symbol cap is the fourth deviation) | "
            "RULED (6396085915) |",
            '| BQ-11 | the rejection frames | six CMP-027 `inline` frames, `live="polite"`, '
            "the dialog kept open with Choose another file focused beside its Cancel; no "
            "Import verb on any of them (AC 2: omitted, never T2-locked); each names its "
            'problem and its limit and says "Nothing was imported."; each fires one '
            "`layout.import_rejected{reason}` | RULED (6396085915) |",
            '| BQ-12 | the post-import report | the dialog\'s final step, a `role="region"` '
            'named "Import report" with the table re-rendered (§4.3) and Copy report '
            "(CMP-033); it stays until Close and is never a toast | RULED (6396085915) |",
            "| BQ-13 | the keyboard path and the tree | Choose file… is a real `<button>` "
            "whose `Enter` or `Space` opens the OS picker; the drop zone only adds to the "
            "input; the table is one Tab stop read with its headers; each announcement polite "
            "and once (§7) | RULED (6396085915) |",
            "| BQ-14 | T2 per role, view-as first | Import… is a write (`22:8521`): its legs "
            "in the server's order, view-as first (`rbac.view_as`), then the permission "
            "(`rbac.permission`), then the state (`workspace.limit.count`), keys as merged "
            "E15-D02 (`D02:655`) and E15-D03 (`D03:564`) carry them; Export… is never gated; a "
            "rejected file never T2-locks Import because the verb is absent; an absence is "
            "never a lock and validity is never a lock; T2 is stated once (§6) | RULED "
            "(6396085915) |",
            "| BQ-15 | the boards under the cap | ten boards with at most three light twins — "
            "two here (§0); every other frame not drawn, the text binding, drawn on request | "
            "RULED (6396085915) |",
            "| BQ-16 | the gate tool, the mutation list and the G-rows | the tool in E15-D08's "
            "form with D09's own row ids: per-frame gates over every row of every table and "
            "the prose, case-insensitive vocabulary lists, whole clauses; S1–S20 each a "
            "`--self-test` mutation; the G-rows D09-G1…G14 to `22`'s owner (`22` first, C-6.1) "
            "| RULED (6396085915) |",
            "| Condition 1 | security — every string from the file is untrusted | every string "
            "from the file is untrusted: text only, never markup and never a link, capped with "
            "the cap stated, the malformed reason naming the key in mono, truncated; the "
            "report echoes no raw file content beyond those capped names; the client's parse "
            "is a courtesy — the server re-checks size, depth, nodes, schema and version "
            "(E15-S07) and `SCR-026/validating` says so; a refused parse is never a partial "
            "import; nothing is created before Import as new workspace and nothing kept after "
            "a refusal | RULED (6396085915) — binding on every frame |",
            "| Condition 2 | A1 — the T2 rule | Import… is a write, its legs in the server's "
            "order, view-as first (`rbac.view_as`), then `rbac.permission`, then "
            "`workspace.limit.count`; Export… is never gated; a rejected file never T2-locks "
            "Import; an absence is never a lock; validity is never a lock | RULED (6396085915) "
            "— binding on every frame |",
            "| Condition 3 | A2 — the gates | the tool reads every frame table row by row, "
            "every other table and the prose, with case-insensitive vocabulary lists (the "
            "gated-exit words, the environment words, the sharing claim, the markup and link "
            "words) against whole clauses, never first words; one `--self-test` mutation per "
            "ruled sentence and per frame element, S1–S20 the minimum | RULED (6396085915) — "
            "binding from the first commit |",
            "| Condition 4 | A3 / A4 — the exits and honesty | Cancel, Esc, ×, Close and "
            "Choose another file are never gated on any frame, view-as and the Viewer's "
            "included; merged texts at their merge shas; every departure a PROPOSED A, C or "
            'G-row; "RULED" cites 6396085915; no lane is an authority | RULED (6396085915) — '
            "binding on every frame |",
        ),
    ),
    ("| Id | Ticket item | Where | Status |"): (
        "trace-row",
        (
            '| AC-1 | "The user learns what travels before exporting": the included and the '
            "excluded lists, the excluded one naming accounts, environment binding and "
            "credentials | `SCR-025/export-preview`, `SCR-025/export-done` (§2.1); the "
            "Excluded sentence byte for byte (BQ-2 RULED) | done |",
            '| AC-2 | "A newer-version file is refused, not partially applied": both versions '
            "named, no option that applies part of the file | `SCR-026/rejected-version-newer` "
            "(§5.1); BQ-4 and BQ-11 RULED | done |",
            '| AC-3 | "Unknown panel types are reported, not silently dropped": both listed by '
            "stored type name with the ticket's reason, and the report repeats them | §4.2 "
            "rows 1–2 and §4.3 rows 1–2; `SCR-026/preview`, `SCR-026/report` | done |",
            '| AC-4 | "Account references are remapped and disclosed": shown dropped, the '
            "report in plain language, naming no account the importer cannot see | §4.2 rows "
            "3–4 (BQ-3 RULED: dropped and listed); `SCR-026/report` | done |",
            '| AC-5 | "The file is malformed or oversized": the problem and the limit named, '
            "the dialog open for another file | `SCR-026/rejected-malformed`, "
            "`SCR-026/rejected-oversized` (§5.1) | done |",
            '| AC-6 | "Import is performed without a pointer": a keyboard path for every step, '
            "the table read as a table with headers | `SCR-026/pick` (Choose file…, the drop "
            "zone off the Tab order), §7, board 08 | done |",
            "| DL-1 | Export surface: the entry from SCR-025 and from the workspace menu | "
            "`SCR-025/export-entry` (§2.1; BQ-7 RULED) | done |",
            "| DL-2 | The pre-export preview's included list | `SCR-025/export-preview` | done |",
            "| DL-3 | The excluded list, first-class | `SCR-025/export-preview`, "
            "`SCR-025/export-done` | done |",
            "| DL-4 | The file name with the schema version | `SCR-025/export-done`; BQ-8 "
            "RULED | done |",
            "| DL-5 | The export completion state | `SCR-025/export-done` | done |",
            "| DL-6 | SCR-026 import hi-fi in both themes: the drop zone with a visible label, "
            "the keyboard alternative, the picker | `SCR-026/pick`; boards 02 and 09 | done |",
            "| DL-7 | The diff-style preview as a table, never a canvas | §4.2; "
            "`SCR-026/preview` | done |",
            "| DL-8 | Item, type, action, reason; drops and remaps first | §4.2 | done |",
            "| DL-9 | The validation states | §5.1; `SCR-026/preview-over-budget` | done |",
            "| DL-10 | The post-import report, persistent and copyable | `SCR-026/report`; "
            "§4.3 | done |",
            "| DL-11 | Parse and validation progress for large files | `SCR-026/validating` | "
            "done |",
            "| DL-12 | The copy set for the trust claims, word by word | §9; BQ-2 RULED, owner "
            "approval pending (#2701) | done |",
            "| DL-13 | Redlines and the spec page | this file (the first deviation) | done |",
            "| DL-14 | The Storybook list for CMP-067 | §10 (an A-row) | done |",
            "| DL-15 | The constructive route on a refusal | `SCR-026/rejected-version-newer`, "
            "`SCR-026/rejected-version-older` | done |",
            "| DL-16 | The budget overflow through US-LAY-001's confirm | "
            "`SCR-026/budget-confirm` | done |",
            "| DL-17 | The untrusted-string rule | §1.2 (Condition 1); the caps and renders "
            "clauses of §3–§5 | done |",
            "| DL-18 | The limits stated; no environment travels; the server re-checks | the "
            "Fixture paragraph; §1.2; `SCR-026/validating`; §5.4 | done |",
            "| DL-19 | The accessibility notes: caption with counts, action as text, errors "
            "announced, report region, polite progress | §4, §7 | done |",
            "| DL-20 | The annotated events | the event clauses of §2–§5; §12 | done |",
            "| DL-21 | The reuse note for SCR-089 | §11 | done |",
            "| DoD-1 | Export preview drawn with both lists | `SCR-025/export-preview` (§2.1); "
            "board 01 is the boards PR's (§0) | routed |",
            "| DoD-2 | SCR-026 drawn in both themes: drop zone, picker, preview table, the six "
            "validation states, the report | §3–§5 and §8; boards 02–06, 09 and 10 are the "
            "boards PR's (§0) | routed |",
            "| DoD-3 | The version mismatch names both versions and a constructive step; no "
            "partial-apply path | `SCR-026/rejected-version-newer` | done |",
            "| DoD-4 | Diff indicators text plus icon; contrast and colour vision checked | §8 "
            "(the tool's numbers) | done |",
            "| DoD-5 | Keyboard-only walkthrough incl. file selection; the table navigable "
            "with headers | §7; the owner's walk on board 08 (§14) | heuristic-only |",
            "| DoD-6 | The copy signed off on the trust claims | the owner's `approved` "
            "(#2701) | routed |",
            "| DoD-7 | The untrusted-string rule and the limits stated | §1.2; §5.4; §5.5; the "
            "Fixture paragraph | done |",
            "| DoD-8 | SCR-026's sign-off items satisfied | §13 | done |",
            "| DoD-9 | The spec merged; CMP-067's Storybook list agreed | this PR; §10 | routed |",
            "| DoD-10 | The reuse note for SCR-089 filed | §11 | done |",
            "| DoD-11 | The CDO sign-off recorded | the owner | routed |",
        ),
    ),
}
POINTER_LINES = (
    (
        "- **Design (hi-fi):** [E15-D09.md](../design/E15/E15-D09.md) §2 (E15-D09; owner "
        "approval pending; text-first, the boards follow in a second PR: Export… in its three "
        "places, never gated; the export preview's Included and Excluded lists; the file name "
        "with its format version; the completion)."
    ),
    (
        "- **Design (hi-fi):** [E15-D09.md](../design/E15/E15-D09.md) §3–§5 (E15-D09; owner "
        "approval pending; text-first, the boards follow in a second PR: the import dialog, "
        "the five check steps, the preview table with drops and remaps first, the six "
        "rejections with no Import verb, the report, T2 view-as first and the keyboard path)."
    ),
)
DECK_CELLS = {
    "e15.export.menu_item": ('"Export…"'),
    "e15.export.title": ('"Export {workspace}" · fixture "Export Scalping"'),
    "e15.export.close": ('"Close Export {workspace}" · fixture "Close Export Scalping"'),
    "e15.export.preparing": ('"Preparing the file…"'),
    "e15.export.unsaved": (
        '"Unsaved changes aren\'t in the file: it holds {workspace} as last saved." · fixture '
        '"Unsaved changes aren\'t in the file: it holds Scalping as last saved."'
    ),
    "e15.export.included": (
        '"The file includes: {layouts} ({layout_names}) · {panels} · symbols {symbols} · sync '
        "groups {groups} · each panel's settings · {drawings}, with their text labels · "
        '{templates} · {presets}." · fixture "The file includes: 2 layouts (Layout 1, '
        "Order-flow) · 7 panels · symbols BTCUSDT, ETHUSDT · sync groups A and B · each "
        "panel's settings · 12 drawings, with their text labels · 1 chart template · 3 "
        'indicator presets."'
    ),
    "e15.export.excluded": (
        '"Never included: credentials — API keys or tokens; accounts, trade-group and user '
        "ids; environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or "
        'orders."'
    ),
    "e15.export.caveat": ('"The file does show your symbols, layouts and settings."'),
    "e15.export.over_limit": (
        '"{reason} You can save it, but this app won\'t import it." · {reason} is the '
        "import's own first sentence (§5.2); fixture \"This file has 240 indicator presets; a "
        "file may carry at most 200. You can save it, but this app won't import it.\""
    ),
    "e15.export.cancel": ('"Cancel"'),
    "e15.export.download": ('"Download file"'),
    "e15.export.failed": (
        '"Couldn\'t prepare the file: the workspace store is unavailable. Nothing was exported."'
    ),
    "e15.export.failed_gone": (
        '"Couldn\'t prepare the file: this workspace can no longer be read. Nothing was exported."'
    ),
    "e15.export.failed_unlisted": (
        "\"Couldn't prepare the file: it holds something this preview can't show. Nothing was "
        'exported."'
    ),
    "e15.export.save_failed": ('"Couldn\'t save the file. Nothing was exported."'),
    "e15.export.retry": ('"Try again"'),
    "e15.export.done": (
        '"Exported {workspace} as {file}." · fixture "Exported Scalping as '
        'scalping.cv-workspace-v1.json."'
    ),
    "e15.export.close_button": ('"Close"'),
    "e15.import.menu_item": ('"Import…"'),
    "e15.import.title": ('"Import workspace"'),
    "e15.import.close": ('"Close Import workspace"'),
    "e15.import.trust": (
        '"A workspace file never carries credentials or account bindings. Importing creates a '
        'new workspace and changes nothing else."'
    ),
    "e15.import.choose": ('"Choose file…"'),
    "e15.import.drop_hint": ('"or drop a workspace file here"'),
    "e15.import.help": ('"JSON, up to {size_mb} MB" · fixture "JSON, up to 2 MB"'),
    "e15.import.drop_active": ('"Drop to check the file"'),
    "e15.import.drop_rejected": ('"Drop one .json file"'),
    "e15.import.cancel": ('"Cancel"'),
    "e15.import.checking": (
        '"Checking {file}… step {i} of {n}" · fixture "Checking scalping.json… step 3 of 5"'
    ),
    "e15.import.caption": (
        '"Preview — {panels} and {layouts} to add · {dropped} dropped · {remapped} remapped" · '
        'fixture "Preview — 7 panels and 2 layouts to add · 3 dropped · 1 remapped"'
    ),
    "e15.import.col.item": ('"Item"'),
    "e15.import.col.type": ('"Type"'),
    "e15.import.col.action": ('"Action"'),
    "e15.import.col.reason": ('"Reason"'),
    "e15.import.action.add": ('"Add"'),
    "e15.import.action.drop": ('"Drop"'),
    "e15.import.action.remap": ('"Remap"'),
    "e15.import.reason.unknown_kind": ('"not available in this version"'),
    "e15.import.reason.account": ('"workspaces never carry account bindings"'),
    "e15.import.reason.remap": ('"shows your own accounts"'),
    "e15.import.clash": (
        '"Imported as {clash}: a workspace named {workspace} exists." · fixture "Imported as '
        'Scalping (2): a workspace named Scalping exists."'
    ),
    "e15.import.confirm": ('"Import as new workspace"'),
    "e15.import.close_view": ('"Close"'),
    "e15.import.slow": ('"Still importing…"'),
    "e15.import.migrated": (
        '"Migrated from format version {from} to {to}." · fixture "Migrated from format '
        'version 1 to 2."'
    ),
    "e15.import.caption_budget": (
        '"Preview — {panels} and {layouts} to add. {layout} opens at about {estimate} ms per '
        'frame (estimated), over the {budget} ms budget." · fixture "Preview — 12 panels and 1 '
        "layout to add. Wall opens at about 17.9 ms per frame (estimated), over the 16 ms "
        'budget."'
    ),
    "e15.import.budget": (
        '"{layout} opens with {panels}: about {estimate} ms per frame (estimated), over the '
        '{budget} ms budget." · fixture "Wall opens with 12 panels: about 17.9 ms per frame '
        '(estimated), over the 16 ms budget."'
    ),
    "layout.cost.import.title": (
        '"Open {layout} with {panels}?" · fixture "Open Wall with 12 panels?"'
    ),
    "layout.cost.import.body": (
        '"Frame time now: {measured} ms per frame (p95, last 10 s, measured), about {fps} fps. '
        "With {layout}'s {panels}: about {estimate} ms (estimated), about {estfps} fps. "
        "Budget: {budget} ms ({budgetfps} fps). That is over the performance budget, so charts "
        'may stutter." · fixture "Frame time now: 11.8 ms per frame (p95, last 10 s, '
        "measured), about 60 fps. With Wall's 12 panels: about 17.9 ms (estimated), about 56 "
        "fps. Budget: 16 ms (60 fps). That is over the performance budget, so charts may "
        'stutter."'
    ),
    "layout.cost.import.confirm": ('"Import anyway"'),
    "e15.import.report.heading": ('"Import report"'),
    "e15.import.report.done": (
        '"Imported {clash}: {panels}, {layouts}, {dropped_items} dropped, {remapped} '
        'remapped." · fixture "Imported Scalping (2): 7 panels, 2 layouts, 3 items dropped, 1 '
        'remapped."'
    ),
    "e15.import.report.caption": (
        '"Report — {panels} and {layouts} added · {dropped} dropped · {remapped} remapped" · '
        'fixture "Report — 7 panels and 2 layouts added · 3 dropped · 1 remapped"'
    ),
    "e15.import.report.copy": ('"Copy report"'),
    "e15.import.report.copied": ('"Copied"'),
    "e15.import.report.copy_failed": ('"Couldn\'t copy the report."'),
    "e15.import.report.close": ('"Close"'),
    "e15.import.report.view": ('"View report"'),
    "e15.import.review": ('"Review"'),
    "e15.import.choose_another": ('"Choose another file"'),
    "e15.import.rejected.version_newer": (
        "\"This file was exported by format version {file} and can't be imported into format "
        "version {app}. Nothing was imported. Export it again from a version {app} app, or "
        'update this app." · fixture "This file was exported by format version 2 and can\'t be '
        "imported into format version 1. Nothing was imported. Export it again from a version "
        '1 app, or update this app."'
    ),
    "e15.import.rejected.version_older": (
        '"This file was exported by format version {file} and this app reads format version '
        "{floor} or later. Nothing was imported. Update the app that exported it, then export "
        'it again." · fixture "This file was exported by format version 0 and this app reads '
        "format version 1 or later. Nothing was imported. Update the app that exported it, "
        'then export it again."'
    ),
    "e15.import.rejected.malformed": (
        '"This isn\'t a workspace file: `{key}` is missing. Nothing was imported." · fixture '
        "\"This isn't a workspace file: `layouts[1].grid_spec.root` is missing. Nothing was "
        'imported."'
    ),
    "e15.import.rejected.parse": (
        "\"This isn't a workspace file: it stops being valid JSON at line {line}. Nothing was "
        'imported." · fixture "This isn\'t a workspace file: it stops being valid JSON at line '
        '212. Nothing was imported."'
    ),
    "e15.import.rejected.panes": (
        '"This file has a layout with {n} panels; a layout holds at most {max}. Nothing was '
        'imported." · fixture "This file has a layout with 30 panels; a layout holds at most '
        '16. Nothing was imported."'
    ),
    "e15.import.rejected.layouts": (
        '"This file has {n} layouts; a workspace holds at most {max}. Nothing was imported." · '
        'fixture "This file has 40 layouts; a workspace holds at most 32. Nothing was '
        'imported."'
    ),
    "e15.import.rejected.presets": (
        '"This file has {n} indicator presets; a file may carry at most {max}. Nothing was '
        'imported." · fixture "This file has 240 indicator presets; a file may carry at most '
        '200. Nothing was imported."'
    ),
    "e15.import.rejected.invalid": (
        "\"This isn't a workspace file: `{key}` isn't valid. Nothing was imported.\" · fixture "
        "\"This isn't a workspace file: `layouts[0].crosshair_sync` isn't valid. Nothing was "
        'imported."'
    ),
    "e15.import.rejected.oversized": (
        '"This file is {size} MB; the limit is {max} MB. Nothing was imported." · fixture '
        '"This file is 3.4 MB; the limit is 2 MB. Nothing was imported."'
    ),
    "e15.import.rejected.wrong_type": (
        "\"That isn't a JSON file ({name}). Nothing was imported. Choose a .json workspace "
        'file." · fixture "That isn\'t a JSON file (report.csv). Nothing was imported. Choose '
        'a .json workspace file."'
    ),
    "e15.import.rejected.depth": (
        '"This file is nested too deeply: the limit is {max} levels. Nothing was imported." · '
        'fixture "This file is nested too deeply: the limit is 16 levels. Nothing was '
        'imported."'
    ),
    "e15.import.rejected.nodes": (
        '"This file has more than {max} values: the limit is {max}. Nothing was imported." · '
        'fixture "This file has more than 10,000 values: the limit is 10,000. Nothing was '
        'imported."'
    ),
    "e15.import.nothing": ('"Nothing was imported."'),
    "e15.import.refused.limit": (
        '"You have {max} workspaces, the most you can have. Delete one, then import again." · '
        'fixture "You have 32 workspaces, the most you can have. Delete one, then import '
        'again."'
    ),
    "e15.import.refused.server": (
        '"The server didn\'t accept this file: `{key}` isn\'t valid." · fixture "The server '
        "didn't accept this file: `layouts[0].panes[3].pane_config` isn't valid.\""
    ),
    "e15.import.refused.store": (
        '"The workspace store didn\'t answer. Choose the file again in a moment."'
    ),
    "e15.import.refused.size": (
        '"The server didn\'t accept this file: it is larger than the server takes."'
    ),
    "e15.import.refused.unconfirmed": (
        '"We couldn\'t confirm the import. Check your workspaces before importing again."'
    ),
    "e15.import.shortened": ('"(shortened)"'),
    "rbac.view_as": (
        '"Read-only while viewing as {user}." · fixture "Read-only while viewing as alex."'
    ),
    "rbac.permission": (
        '"Your role can\'t save workspaces." · template "Your role can\'t {verb}."'
    ),
    "workspace.limit.count": ('"You have the most workspaces you can have."'),
    "ws.export.unstored": ('"This workspace isn\'t saved."'),
}
MARKER_TABLE = """
boards 2
light_twins 2
mutations 2
fixture.export_layouts 2
fixture.export_panels 3
fixture.panels 3
fixture.layouts 2
fixture.dropped 3
fixture.unknown_kinds 2
fixture.remapped 3
fixture.app_format 7
fixture.newer_format 4
fixture.older_format 4
fixture.budget_panels 2
fixture.measured_ms 2
fixture.estimate_ms 2
contract.budget_ms 3
contract.size_mb 6
contract.parse_ms 3
contract.depth 4
contract.nodes 4
contract.layouts_max 5
contract.panes_max 7
contract.workspaces_max 7
contract.presets_max 5
contract.name_max 6
contract.symbol_max 2
contract.kind_max 2
contract.label_max 3
design.key_cap 9
design.file_cap 12
contract.dialog_lg_px 5
contract.dialog_md_px 6
bq_rows 2
conditions 2
frames_drawn 2
frames_total 2
frames_not_drawn 2
states 1
redline.size.control.comfortable 20
redline.size.row.height 7
redline.space.inset.sm 18
redline.radius.card 8
redline.border.hairline 8
redline.border.focus 6
redline.space.dialog.padding 5
redline.space.stack.md 22
redline.size.control.compact 17
redline.radius.dialog 4
redline.opacity.scrim 4
redline.space.inset.xl 4
redline.size.icon 15
redline.border.thick 7
redline.size.target.min 1
fixture.rows 1
contract.reason_max 2
missing_tokens 2
pairs_rows 2
pairs_fail 2
pairs_registered 1
pairs_proposed 1
contract.refresh_fps 1
frames_import 2
checklist_items 1
frames_export 1
rows.G 1
rows.C 1
rows.A 1
rows.Q 1
rows.D 1
"""
SHA_COUNTS = {
    "ed8a22246263ace73f39e4434e6d5f57b1a857bd": 1,
    "1044c4f602eff6ae1a2cf42201ab398f6c4234d1": 1,
    "7be6eac6a705cf24ba534ce4f7d31349a1e29932": 1,
    "c73aec08246f06d28c70e8b959c658bc1a0c4d09": 2,
    "6e2c1211fc5f4675457d57011a346642f92710c5": 2,
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff": 1,
    "c4989493461ec6b6d22b9254633452a6362b750e": 3,
    "04a8caa9513e90debcf7cbc41a9ca585496eba01": 1,
}

TRACE_HEAD = "| Id | Ticket item | Where | Status |"
BQ_HEAD = "| # | Question | Built here (the ruled outcome) | Status |"
DECK_STATIC = {k: v for k, v in DECK_CELLS.items() if k not in TEMPLATES}
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


def unquote(text: str) -> str:
    """The clause with its quoted copy blanked (a UI string never counts as a description)."""
    return re.sub(r'"[^"\n]*"', '""', text)


def compact(text: str) -> str:
    """Lower-cased letters and digits only: a label however it is spaced or hyphenated."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def blank(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in phrases:
        text = text.replace(phrase, " " * len(phrase))
    return text


def plain(text: str) -> str:
    """A clause as the vocabulary lists read it: the audit markers and "fail closed" blanked,
    quoted copy blanked, code spans read as their text."""
    text = re.sub(MARKER_RE, " ", text)
    for pattern in EXIT_BLANK:
        text = re.sub(pattern, lambda m: " " * len(m.group(0)), text)
    return unquote(text).replace("`", "")


def clause_bounds(text: str, pos: int, split: str = CLAUSE_SPLIT_RE) -> tuple[int, int]:
    start, end = 0, len(text)
    for m in re.finditer(split, text):
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def own_start(text: str, a: int, start: int) -> int:
    """Where the match's own predicate starts inside its clause `text[a:]`: after the last comma,
    "and" or "or" that opens a new subject whose verb follows, the match itself included (MAJOR 1
    of the delta check); `a` when none does. A negated list has no new subject and verb."""
    verb_first = bool(re.match(SUBJECT_VERB_RE, text[start:]))
    _, end = clause_bounds(text, start, NEG_SPLIT_RE)
    follows = verb_follows(text[start:end])
    own = a
    for m in re.finditer(NEG_JOIN_RE, text[a:start]):
        rest = text[a + m.end() : start]
        if not re.match(NEW_SUBJECT_RE, rest if rest.strip() else text[start:]):
            continue
        # A match right after an article is a noun ("never markup or a link"), never a verb.
        noun = re.search(r"(?i)\b(?:the|an?|its|their|your|this|that|each|every|any)\s*$", rest)
        # The match may be the new subject's head ("…, and Import anyway sits beside …"): its
        # verb follows, and what stands between the last negator and the join is not a list of
        # names ("no Cancel, Close or Import anyway is offered").
        before = text[a : a + m.start()]
        negs = list(re.finditer(NEGATOR_RE, before))
        seg = before[negs[-1].end() :] if negs else before
        names = bool(seg.strip()) and bool(
            re.fullmatch(r"(?:\s*(?:[A-Z×`][^\s,]*|and|or|,))*\s*", seg)
        )
        head = follows and not names
        if re.search(SUBJECT_VERB_RE, rest) or (verb_first and not noun) or head:
            own = a + m.end()
    return own


def own_clause(text: str, start: int) -> str:
    """The match's own predicate: from `own_start` to its clause's end."""
    a, b = clause_bounds(text, start, NEG_SPLIT_RE)
    return text[own_start(text, a, start) : b]


def negated(text: str, start: int) -> bool:
    """A negator earlier in the match's own predicate governs it (`own_start`), unless a
    contrast boundary (but, only, while, a new subject and verb ...) or " · " lies between."""
    text = text.replace("e.g.", "e·g·").replace("i.e.", "i·e·")
    a, _ = clause_bounds(text, start, NEG_SPLIT_RE)
    head = text[own_start(text, a, start) : start]
    negs = list(re.finditer(NEGATOR_RE, head))
    if not negs or len(re.findall(r"\S+", head[negs[-1].end() :])) > NEGATION_REACH:
        return False
    tail = head[negs[-1].end() :]
    return not (re.search(CONTRAST_RE, tail) or re.search(NEG_ITEM_SEP_RE, tail))


def verb_follows(text: str) -> bool:
    """A verb within the first words after a match's first word, before any "and", "or" or
    comma: the match is the subject of that verb."""
    for word in re.findall(r"\S+", text)[1:6]:
        if word.endswith(",") or word.lower() in ("and", "or"):
            return False
        if re.fullmatch(FINITE_VERB_RE, word.strip(".;:()\"'")):
            return True
    return False


def hits(pattern: str, text: str) -> list[str]:
    """Every match of a vocabulary list in `text` that no negator governs."""
    return [m.group(0) for m in re.finditer(pattern, text) if not negated(text, m.start())]


def clause_of(text: str, pos: int) -> str:
    a, b = clause_bounds(text, pos)
    return text[a:b]


def exit_gated(clause: str) -> list[str]:
    """A3: a clause that names an exit and a gated-exit stem in the same clause, no negator
    governing the stem."""
    text = plain(clause)
    out = []
    for m in re.finditer(GATE_RE, text):
        if negated(text, m.start()):
            continue
        if re.search(EXIT_RE, clause_of(text, m.start())):
            out.append(m.group(0))
    return out


def foreign(text: str) -> bool:
    """S3: an account the importer cannot see is named."""
    flat = compact(text)
    if any(compact(a) in flat for a in FIXTURE["foreign_accounts"]):
        return True
    body = plain(text)
    if any(re.search(p, body) for p in FOREIGN_RES):
        return True
    for m in re.finditer(ACCOUNT_TOKEN_RE, body):
        if m.group("tok").rstrip(".-").lower() not in ACCOUNT_NEXT_OK:
            return True
    if re.search(FOREIGN_CTX_RE, body):
        for m in re.finditer(FOREIGN_NAMED_RE, body):
            if m.group("n").split()[0] not in PROPER_OK:
                return True
    return False


def order_problem(
    text: str, words: tuple[tuple[str, str], ...], want: tuple[str, ...], least: int, cue: bool
) -> bool:
    """A chain or a list naming `least` or more of `words` (two in an arrow chain) in another order
    than `want`; `cue`: only where the sentence orders them (an arrow, "then", "first", "legs")."""
    body = re.sub(
        r"`[^`\n]*`", lambda m: m.group(0).strip("`"), unquote(re.sub(MARKER_RE, " ", text))
    )
    found: list[tuple[int, str]] = []
    parts = re.split(r"→|->|(?<![<>=-])>(?![=>])", body)
    if len(parts) > 1:
        for k, part in enumerate(parts):
            hits_ = [(m.start(), name) for name, p in words for m in re.finditer(p, part)]
            if hits_:
                found.append((k, (max(hits_) if k == 0 else min(hits_))[1]))
    else:
        for name, pattern in words:
            m = re.search(pattern, body)
            if m:
                found.append((m.start(), name))
    if len(found) < (2 if re.search(r"→|->|(?<![<>=-])>(?![=>])", body) else least):
        return False
    if cue and not re.search(ORDER_CUE_RE, body):
        return False
    seq = list(dict.fromkeys(name for _, name in sorted(found)))
    if len(seq) == 2 and re.search(r"(?i)\bafter\b", body):
        seq.reverse()
    return seq != [w for w in want if w in seq]


def steps_problem(text: str) -> str | None:
    """S9: an arrow chain is the whole ruled chain; any other list keeps the ruled order."""
    body = re.sub(r"`[^`\n]*`", "``", unquote(re.sub(MARKER_RE, " ", text)))
    if re.search(r"→|->", body) and len([1 for _, p in STEP_WORDS if re.search(p, body)]) >= 2:
        chain = STEPS_CLAUSE.removeprefix("steps: ")
        if chain not in text:
            return "a chain of the check steps that is not the ruled one"
    if order_problem(body, STEP_WORDS, STEPS, 3, False):
        return "the check steps out of order"
    return None


def legs_problem(text: str) -> bool:
    """S17: the legs out of the server's order, in a chain, a list or a sentence ordering them."""
    body = plain(text)
    if re.search(LEG_WRONG_RE, body):
        return True
    if re.search(LEG_CTX_RE, body) and hits(LEG_FIRST_RE, body):
        return True
    return order_problem(text, LEG_WORDS, ("view_as", "permission", "limit"), 2, True)


def focus_problem(text: str, line: str, forced: bool, own_focus: str | None = None) -> str | None:
    """S20: on a rejection or a refusal, a focus claim names Choose another file, unless its
    clause names the frame whose focus the control is (a frame's own focus is its row's clause)."""
    ctx = (
        forced
        or re.search(REJECTION_CTX_RE, plain(text))
        or re.search(REJECTION_CTX_RE, plain(line))
    )
    if not ctx:
        return None
    body = plain(text)
    frames = set(re.findall(FRAME_NAME_RE, line))
    own = own_focus
    if own is None and len(frames) == 1:
        name = frames.pop()
        if name in KIND:
            own = FOCUS.get(name, FOCUS.get(KIND[name][0], ""))
    for m in re.finditer(FOCUS_CLAIM_RE, body):
        control = (m.group("a") or m.group("b") or m.group("c")).lower()
        if own is not None:
            if control != own.lower():
                return control
            continue
        if control == "choose another file":
            continue
        rule = FOCUS_EXCEPT.get(control)
        if rule and re.search(rule, clause_of(body, m.start())):
            continue
        return control
    return None


def near(control: str, stems: str, text: str, after: int = 6, before: int = 3) -> str | None:
    """A stem no negator governs, within `after` words after a control or `before` words before
    it: a sentence about the control, never one that only shares a sentence with it."""
    fwd = rf"(?i)\W+(?:\S+\s+){{0,{after}}}?(?P<s>{stems})"
    back = rf"(?i)\W+(?:\S+\s+){{0,{before}}}?(?:{control})"
    for c in re.finditer(rf"(?i){control}", text):
        m = re.match(fwd, text[c.end() :])
        if m:
            s, e = c.end() + m.start("s"), c.end() + m.end()
            a, b = clause_bounds(text, s)
            if not negated(text, s) and a <= c.start() and e <= b:
                return m.group("s")
    for st in re.finditer(rf"(?i){stems}", text):
        m = re.match(back, text[st.end() :])
        if m:
            a, b = clause_bounds(text, st.start())
            if not negated(text, st.start()) and st.end() + m.end() <= b:
                return st.group(0)
    return None


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
        "presets_user": num(r"most (\d+), the per-user cap", bundle),
        "presets_mib": num(r"or (\d+) MiB of preset JSON", bundle),
        "create_kib": num(r"Bodies over (\d+) KiB are refused with `413`", create),
        "example_mb": num(r"When a (\d+) MB file", bl),
        "body_pct": num(r"the card at most (\d+) % of the viewport", cmp043),
        "p95_window_s": num(r"p95, last (\d+) s", t["D03"]),
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
    tally = {
        **mine,
        "dropped": c["dropped"],
        "dropped_items": plural(c["dropped"], "item"),
        "remapped": c["remapped"],
        "clash": fx["clash"],
    }
    included = {
        "layouts": plural(len(fx["export_layouts"]), "layout"),
        "layout_names": ", ".join(fx["export_layouts"]),
        "panels": plural(fx["export_panels"], "panel"),
        "symbols": ", ".join(fx["export_symbols"]),
        "groups": " and ".join(fx["export_groups"]),
        "drawings": plural(fx["export_drawings"], "drawing"),
        "templates": plural(fx["export_templates"], "chart template"),
        "presets": plural(fx["export_presets"], "indicator preset"),
    }
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
        "e15.export.title": {"workspace": fx["workspace"]},
        "e15.export.close": {"workspace": fx["workspace"]},
        "e15.export.unsaved": {"workspace": fx["workspace"]},
        "e15.export.included": included,
        "rbac.view_as": {"user": fx["user"]},
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
        "e15.import.rejected.invalid": {"key": fx["invalid_key"]},
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
        "ellipsis past the cap, the whole capped value in the accessible name)"
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
COMPONENT_GONE = (
    'component: CMP-027 `inline`, `live="polite"`, in the dialog body, the zone and Choose '
    "file… gone (§5.5)"
)
STATE_CONFIRM = (
    "state: nothing created yet — no workspace, layout or pane exists until Import anyway sends "
    "the file"
)
STATE_UNKNOWN = (
    "state: unknown — the answer never came, so the new workspace may or may not exist, and "
    "nothing is sent again by itself"
)
IMPORT_VERB_ONCE = "import verb: none — omitted, so the file is never sent twice (D09-G1)"
SHAPE = (
    "shape: not checked — a format version this app does not read skips the shape rules, so "
    "the outcome is the version refusal and never a shape failure (§3.4, step 3)"
)
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
        if VERSION_FRAMES[name] != "migrated":
            add("shape", SHAPE, "version-shape")
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
        add("state", STATE_CONFIRM, "created-early")
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
    elif kind == "unconfirmed":
        add("component", COMPONENT_GONE, "component")
        add("message", f"message: {q('e15.import.refused.unconfirmed')}", "message")
        add("state", STATE_UNKNOWN, "unconfirmed")
        add("import verb", IMPORT_VERB_ONCE, "import-verb")
        add("live", "live: polite, once", "live")
    elif kind in NOTHING_KINDS:
        reason = params["reason"]
        add("component", COMPONENT_GONE if reason == "limit" else COMPONENT, "component")
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
    """S1: every "Never included" opens the ruled sentence, byte for byte, as a whole quoted string
    (outside a frame row E15-D02's own sentence may be quoted, a C-row)."""
    for m in re.finditer(r"(?i)never\s*included", line):
        rest = line[m.start() :]
        whole = [EXCLUDED] if frame else [EXCLUDED, D02_EXCLUDED]
        quoted = line[m.start() - 1 : m.start()] == '"'
        if not (quoted and any(rest.startswith(w + '"') for w in whole)):
            return True
    return False


def trust_problem(line: str) -> bool:
    """BQ-2: every "A workspace file never carries" is the trust note, byte for byte, as a whole
    quoted string."""
    return any(
        line[m.start() - 1 : m.start()] != '"' or not line[m.start() :].startswith(TRUST_NOTE + '"')
        for m in re.finditer(r"(?i)a\s*workspace\s*file\s*never\s*carries", line)
    )


def vocabulary_gate(where: str, text: str, frame: bool) -> str | None:
    """The checks every ladder runs first: the sharing claim and its paraphrases (S2, markdown
    emphasis and spacing read through), an account the importer cannot see (S3), the Excluded
    sentence (S1) and the trust note, each byte for byte."""
    if re.search(SHARE_RE, re.sub(r"[*_`]+", "", text)):
        return fail("share-claim", f"{where}: the sharing claim is written (BQ-2 RULED: never)")
    if foreign(text):
        return fail("foreign-account", f"{where}: names an account the importer cannot see")
    if excluded_problem(text, frame):
        return fail(
            "excluded", f"{where}: the Excluded sentence is not the ruled one, byte for byte"
        )
    if trust_problem(text):
        return fail("trust-note", f"{where}: the trust note is not E15-D02's, byte for byte")
    return None


def number_sets(facts: dict[str, Any]) -> tuple[dict[str, set[float]], dict[str, set[float]]]:
    """Per unit, every value the tool derives (the allowed set) and the limits a "at most N" or
    "N MB limit" phrase may state (S18): a number printed without its marker must be one of them."""
    if id(facts) not in NUMBER_SETS:
        known_copy(facts)
        NUMBER_SETS[id(facts)] = derive_numbers(facts)
    return NUMBER_SETS[id(facts)]


def derive_numbers(facts: dict[str, Any]) -> tuple[dict[str, set[float]], dict[str, set[float]]]:
    fx, bud, c = FIXTURE, FIXTURE["budget"], counts(facts)
    caps = {
        facts["name_max"],
        facts["symbol_max"],
        facts["kind_max"],
        DESIGN_CAPS["key_cap"],
        DESIGN_CAPS["file_cap"],
        facts["label_max"],
        facts["reason_max"],
    }
    redline = {float(v) for k, v in facts["redline"].items() if not k.startswith("opacity.")}
    limits = {
        "mb": {facts["size_mb"]},
        "depth": {facts["depth"]},
        "nodes": {facts["nodes"]},
        "layouts": {facts["layouts_max"]},
        "panes": {facts["panes_max"]},
        "workspaces": {facts["workspaces_max"]},
        "presets": {facts["presets_max"], facts["presets_user"]},
        "chars": caps,
        "ms": {facts["parse_ms"], facts["budget_ms"]},
        "kib": {facts["create_kib"]},
        "mib": {facts["presets_mib"]},
    }
    allowed = {k: set(v) for k, v in limits.items()}
    allowed["mb"] |= {float(fx["oversized_mb"]), facts["example_mb"]}
    allowed["ms"] |= {SHOW_DELAY_MS, fx["measured_ms"], fx["estimate_ms"]}
    allowed["px"] = redline | set(facts["dialog_px"]) | {fx["reflow"]["margin"]}
    allowed["pct"] = {fx["reflow"]["zoom"], facts["body_pct"], BASE_ZOOM}
    allowed["fps"] = {
        facts["refresh_fps"],
        fps(fx["measured_ms"], facts),
        fps(fx["estimate_ms"], facts),
    }
    allowed["s"] = {facts["p95_window_s"]}
    allowed["layouts"] |= {
        len(fx["export_layouts"]),
        fx["layouts_in_file"],
        bud["layouts"],
        c["layouts"],
    }
    allowed["panes"] |= {fx["export_panels"], c["panels"], bud["panels"], fx["panes_in_file"]}
    allowed["presets"] |= {fx["presets_in_file"], fx["export_presets"]}
    return (
        {k: {float(x) for x in v} for k, v in allowed.items()},
        {k: {float(x) for x in v} for k, v in limits.items()},
    )


def number_problem(text: str, facts: dict[str, Any]) -> str | None:
    """S18: every number with its unit, printed without its marker, outside quoted copy and code,
    is the tool's: a limit phrase states the limit, any other number is one the tool derives."""
    body = re.sub(r"`[^`\n]*`", "``", unquote(text))
    allowed, limits = number_sets(facts)
    for m in re.finditer(NUM_UNIT_RE, body):
        if m.group(0) in QUOTED_NUMBERS:
            continue
        family = UNIT_FAMILY.get(m.group(2).lower())
        if family is None:
            continue
        value = float(re.sub(r"[,   ]", "", m.group(1)))
        is_limit = re.search(LIMIT_LEAD_RE, body[: m.start()]) or re.match(
            LIMIT_TAIL_RE, body[m.end() :]
        )
        pool = limits.get(family, allowed.get(family, set())) if is_limit else allowed.get(family)
        if pool is None or value not in pool:
            return m.group(0)
    return None


# Per facts object, its UI strings; the facts are held here too, so no id is ever reused while a
# cache below is keyed by it.
KNOWN: dict[int, tuple[dict[str, Any], list[str]]] = {}


def known_copy(facts: dict[str, Any]) -> list[str]:
    """Every UI string the tool holds: the deck rendered and as templates, the reasons, the
    upstream words, and the alternative renderings the text offers by name."""
    if id(facts) in KNOWN:
        return KNOWN[id(facts)][1]
    out = [render(k, facts) for k in TEMPLATES] + list(TEMPLATES.values())
    out += [s.strip('"') for s in DECK_STATIC.values() if s.startswith('"')]
    out += [s for s, _ in UPSTREAM_TABLE] + [D02_EXCLUDED, MALFORMED_D02] + list(QUOTE_EXAMPLES)
    out += [REASONS[k].format(user=FIXTURE["user"]) for k in REASONS]
    KNOWN[id(facts)] = (facts, out)
    return out


def head_words(text: str, n: int = 3) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))[:n])


HEADS: dict[int, set[tuple[str, ...]]] = {}


def quoted_problem(text: str, known: list[str]) -> str | None:
    """M11/M13: a quoted string that opens like a UI string of the tool is that string, or a part
    of it, byte for byte (a version, a limit or a word changed in a quote is a FAIL)."""
    if id(known) not in HEADS:
        heads = {head_words(s) for k in known for s in re.split(r"(?<=[.!?…]) ", k) if s}
        HEADS[id(known)] = {h for h in heads if len(h) == 3}
    heads = HEADS[id(known)]
    for found in re.finditer(r'"([^"\n]+)"', text):
        q = found.group(1)
        if any(q in k for k in known):
            continue
        if head_words(q) in heads:
            return q
    return None


PRE_SEND_SUBS = ("1.2", "3.3", "3.4", "4.2", "4.4")
REFUSAL_SUBS = ("1.2", "3.4", "5", "5.1", "5.2", "5.3", "5.4", "5.5")
EXPORT_NAME_RE = r"Export…|Download file|\bthe export dialog\b|\bexport dialog\b"
AVAILABILITY_RE = r"(?i)unsaved default|no stored copy|never stored|availability"
T2_POINTER_RE = (
    r"SCR-026/entry-view-as|SCR-026/entry-permission|SCR-026/entry-limit|SCR-026/import-leg-lost"
    r"|§6's (?:form|legs|rule|alone)|as §6 states|takes §6's"
)
CONTROL_RE = "|".join(re.escape(c) for c in CONTROL_NAMES if c != "Export…")
# The import's matter on an export frame (fold r3): any form of "import" or an import verb, unless
# it is one of the export's own mentions of the import (the delay it borrows, the limit line).
EXPORT_IMPORT_RE = IMPORT_VERB_RE + r"|\bimport\w*"
EXPORT_IMPORT_OK = ("rules for the import (§3.4)", "an import limit", "the import-limit line")
# §6's rows and bullets read what is drawn where: an import verb said to stand in a footer, to stay,
# remain or sit is a presence claim §6 never makes (the verb is drawn on its frames, §3 to §5).
PRESENCE_RE = r"(?i)\bfooters?\b|\bstay(?:s|ed)?\b|\bremain(?:s|ed)?\b|\bsits?\b|\bis offered\b"


def unit_gate(text: str, ctx: dict[str, Any], facts: dict[str, Any]) -> str | None:
    """The vocabulary ladder every free clause, cell and sentence runs: the first FAIL of `text`.
    `ctx` names where it is (`where`), its frame's kind (`kind`, None in prose), its subsection
    (`sub`) and the whole line around it (`line`), which decide the scoped lists."""
    where, kind, sub = ctx["where"], ctx.get("kind"), ctx.get("sub", "")
    body = plain(text)
    prose = kind is None
    gated = exit_gated(text)
    if gated:
        return fail("exit-gated", f"exit drawn gated in {where} ({gated[0]!r}): {text[:60]!r}")
    env_text = text
    for pattern in ENV_OK_RE:
        env_text = re.sub(pattern, lambda m: " " * len(m.group(0)), env_text)
    if hits(ENV_RE, blank(plain(env_text), ENV_OK)):
        return fail("env", f"{where}: an environment travels into an import: {text[:60]!r}")
    locked: bool
    if prose:
        locked = (
            not re.search(AVAILABILITY_RE, body) and bool(near(EXPORT_NAME_RE, EXPORT_STEMS, body))
        ) or bool(near(EXPORT_NAME_RE, ROLE_GATE_RE.removeprefix("(?i)"), body))
    else:
        locked = (
            bool(ctx.get("export"))
            and bool(hits(LOCK_RE, body))
            or (kind == "availability" and bool(hits(ROLE_GATE_RE, body)))
        )
    if locked:
        return fail(
            "export-gated", f"Export… drawn gated in {where} (a read, never T2): {text[:60]!r}"
        )
    if ctx.get("export_frame"):
        found = export_import_problem(body)
        if found:
            return fail("export-import", f"{where}: {found} on an export frame: {text[:60]!r}")
        rest = plain(ctx.get("line", "").replace(text, " ")).lower()
        for m in re.finditer(FOCUS_CLAIM_RE, body):
            control = m.group("a") or m.group("b") or m.group("c")
            if not re.search(r"(?<!\w)" + re.escape(control.lower()) + r"(?!\w)", rest):
                return fail(
                    "export-focus", f"{where}: focus on {control!r}, a control it never draws"
                )
    if prose and sub in ("6", "6.1"):
        for m in re.finditer(IMPORT_VERB_RE, body):
            if not negated(body, m.start()) and re.search(PRESENCE_RE, own_clause(body, m.start())):
                return fail(
                    "import-verb", f"{where}: §6 draws an Import verb in place: {text[:60]!r}"
                )
    refusal = (
        (kind in NOTHING_KINDS | {"unconfirmed"} or bool(re.search(REJECTION_CTX_RE, body)))
        if not prose
        else (sub in REFUSAL_SUBS[2:] or bool(re.search(REJECTION_CTX_RE, body)))
    )
    if refusal:
        lock = (
            near(CONTROL_WORDS, LOCK_WORDS + "|" + GATE_WORDS, body)
            if prose
            else hits(LOCK_RE, body)
        )
        verbs = []
        for m in re.finditer(IMPORT_VERB_RE, body):
            if negated(body, m.start()):
                continue
            # The preview's own verbs, in a sentence about the preview or its confirm, unless
            # the verb's own predicate puts them on a rejection.
            if (
                prose
                and re.search(VERB_HOME_RE, body)
                and re.match(r"(?i)import (?:as new workspace|anyway)$", m.group(0))
                and not re.search(REJECTION_CTX_RE, own_clause(body, m.start()))
            ):
                continue
            verbs.append(m.group(0))
        if verbs and not lock:
            return fail(
                "import-verb", f"{where} offers an Import verb on a refusal (AC 2): {verbs[0]!r}"
            )
        if lock:
            return fail("rejection-lock", f"{where}: a refusal drawn locked or T2: {text[:60]!r}")
    lock_hit: bool
    if prose:
        validity = sub not in ("6", "6.1") and not re.search(T2_CONTEXT_RE, body)
        lock_hit = validity and bool(near(CONTROL_WORDS, LOCK_WORDS + "|" + GATE_WORDS, body))
    else:
        validity = kind not in T2_KINDS | NOTHING_KINDS | {"availability", "unconfirmed"}
        lock_hit = validity and not ctx.get("export") and bool(hits(LOCK_RE, body))
    if lock_hit:
        return fail("t2-over", f"{where} is not T2 (validity is no lock): {text[:60]!r}")
    work = body
    for name in CONTROL_NAMES:
        work = work.replace(name, "control")
    early = (
        kind in PRE_SEND_KINDS | {"rejection"}
        or bool(re.search(r"(?i)\bbefore the (?:send|import)\b", body))
        if not prose
        else sub[:1] != "2"
        or bool(re.search(r"(?i)\b(?:workspaces?|layouts?|panes?|tabs?)\b", body))
    )
    if early and claims(CREATE_RE, work, post=True):
        return fail("created-early", f"{where}: something exists before the send: {text[:60]!r}")
    kept = (
        (kind in NOTHING_KINDS | {"cancelled", "unconfirmed"})
        if not prose
        else refusal or sub in REFUSAL_SUBS or bool(re.search(REFUSED_RE, body))
    )
    if kept and claims(KEEP_RE, work):
        return fail("partial", f"{where}: something of a refused file is kept: {text[:60]!r}")
    return unit_gate_2(text, body, ctx, facts, prose)


def export_import_problem(body: str) -> str | None:
    """An export frame's clause that speaks of the import: an Import verb or any import word
    beyond the export's own mentions (S5, S6), or a workspace created or kept (S10, S11)."""
    text = blank(body, EXPORT_IMPORT_OK)
    for m in re.finditer(EXPORT_IMPORT_RE, text):
        if not negated(text, m.start()):
            return f"an import word ({m.group(0)!r})"
    work = text
    for name in CONTROL_NAMES:
        work = work.replace(name, "control")
    if claims(CREATE_RE, work, post=True) or claims(KEEP_RE, work):
        return "a workspace created or kept"
    return None


def claims(pattern: str, text: str, post: bool = False) -> bool:
    """A create claim (`post`) or a keep claim: matched, no negator governing it. A create claim
    stands unless its clause speaks of the send or after it (POST_SEND_RE): "when the check
    passes" or "once the file is chosen" names a moment before the send, so it exempts nothing.
    A keep claim stands unless a temporal word leads it and no refusal leads it: "when it is
    imported" says when, "when the server refuses the file, the layouts are kept" keeps them."""
    for m in re.finditer(pattern, text):
        if negated(text, m.start()):
            continue
        a, b = clause_bounds(text, m.start(), NEG_SPLIT_RE)
        if post:
            if re.search(POST_SEND_RE, text[own_start(text, a, m.start()) : b]):
                continue
        else:
            lead = text[own_start(text, a, m.start()) : m.start()]
            if re.search(TEMPORAL_RE, lead) and not re.search(REFUSED_RE, lead):
                continue
        return True
    return False


def unit_gate_2(
    text: str, body: str, ctx: dict[str, Any], facts: dict[str, Any], prose: bool
) -> str | None:
    """The ladder's second half: the lists every clause reads wherever it stands."""
    where, sub, line = ctx["where"], ctx.get("sub", ""), ctx.get("line", text)
    marked = blank(body, MARKUP_OK)
    for m in re.finditer(MARKUP_RE, marked):
        if not negated(marked, m.start()) and re.search(
            FILE_SUBJECT_RE, clause_of(marked, m.start())
        ):
            return fail(
                "untrusted-markup", f"{where}: a file string rendered as markup: {text[:60]!r}"
            )
    for m in re.finditer(REMAP_RE, body):
        if negated(body, m.start()) or re.search(TRUE_REMAP_RE, body):
            continue
        if re.search(ACCOUNT_RE, clause_of(body, m.start())):
            return fail("account-remap", f"{where}: an account binding remapped: {text[:60]!r}")
    if near(DROP_RE.removeprefix("(?i)"), TAB_STOP_RE.removeprefix("(?i)"), body) or re.search(
        r"(?i)\benter (?:on|in) the (?:drop )?zone\b", body
    ):
        return fail("drop-zone", f"{where}: the drop zone made a Tab stop: {text[:60]!r}")
    if re.search(COMPARE_RE, body) and hits(APP_VERSION_RE, body):
        return fail("version-field", f"{where}: an app version compared: {text[:60]!r}")
    problem = steps_problem(text)
    if problem:
        return fail("steps", f"{where}: {problem}: {text[:60]!r}")
    if legs_problem(text):
        return fail("legs-order", f"{where}: view-as is not the first leg: {text[:60]!r}")
    if hits(RECHECK_RE, body):
        return fail("server-recheck", f"{where}: the server's re-check denied: {text[:60]!r}")
    shown = (re.search(FILE_SUBJECT_RE, body) or re.search(FILE_SUBJECT_RE, plain(line))) and hits(
        UNCAPPED_RE, body
    )
    if shown or (re.search(FILE_SUBJECT_RE, body) and hits(UNCAPPED_BARE_RE, body)):
        return fail("caps", f"{where}: a string from the file past its cap: {text[:60]!r}")
    if hits(RAW_RE, body):
        return fail("raw-echo", f"{where}: file content echoed, logged or sent: {text[:60]!r}")
    if (
        re.search(INCLUDED_CTX_RE, body)
        and not re.search(TICKET_RE, body)
        and near(INCLUDED_VERB_RE, INCLUDED_EXTRA_RE.removeprefix("(?i)"), body, 3, 0)
    ):
        return fail("included", f"{where}: the Included list names what the bundle never holds")
    if hits(PRIVILEGE_RE, body):
        return fail(
            "privilege", f"{where}: a file that grants the exporter something: {text[:60]!r}"
        )
    if hits(HONESTY_RE, blank(body, HONESTY_OK)):
        return fail("honesty", f"{where}: a claim no text-first spec can make (A4): {text[:60]!r}")
    if prose and sub not in ("6", "6.1") and hits(r"\bT2\b", body):
        if hits(T2_RESTATE_RE, body):
            return fail("t2-once", f"{where}: T2 restated outside §6 (A1): {text[:60]!r}")
    forced = ctx.get("kind") in NOTHING_KINDS | {"unconfirmed"}
    control = focus_problem(text, line, forced, ctx.get("focus"))
    if control:
        return fail("rejection-focus", f"{where}: focus on {control!r} on a refusal: {text[:60]!r}")
    number = number_problem(text, facts)
    if number:
        return fail("limit-number", f"{where}: {number!r} is not a number the tool derives")
    quoted = quoted_problem(text, ctx["known"])
    if quoted:
        return fail("quoted-copy", f"{where}: a UI string differs from the deck's: {quoted[:50]!r}")
    return None


def sentences(text: str) -> list[str]:
    """A line of prose or a table cell as clauses: split on `;` and `|`, on a sentence's end and on
    ` — `, never inside double-quoted copy or a code span."""
    out: list[str] = []
    for part in split_clauses(text, ";|"):
        buf: list[str] = []
        code = quote = False
        i = 0
        while i < len(part):
            ch = part[i]
            if code:
                code = ch != "`"
            elif quote:
                quote = ch != '"'
            elif ch == "`":
                code = True
            elif ch == '"':
                quote = True
            elif part.startswith(" — ", i):
                out.append("".join(buf).strip())
                buf, i = [], i + 3
                continue
            elif ch in ".!?" and re.match(r" [A-Z0-9`*(\[\"]", part[i + 1 : i + 3] or ""):
                buf.append(ch)
                out.append("".join(buf).strip())
                buf, i = [], i + 2
                continue
            buf.append(ch)
            i += 1
        out.append("".join(buf).strip())
    return [s for s in out if s]


def clause_label(clause: str) -> str:
    """A free clause's label: its words before the first ": " (none when the clause opens on copy,
    code or a sentence)."""
    if clause.startswith("Esc →"):
        return "Esc"
    m = re.match(r"([^:`\"]{1,72}?): ", clause)
    return m.group(1) if m else ""


def frame_gate(
    name: str, c: list[str], facts: dict[str, Any], deck: set[str] | None, known: list[str]
) -> str | None:
    """The FRAME ladder: the first FAIL of one frame row, its obligations from the tool's tables.
    Every cell is read: the Producer and every free clause by the vocabulary ladder, the expected
    clauses whole, the free clauses' labels, the Producer and the copy keys against the tool's own
    text, the Class and the Board cells against the inventory and §0."""
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
    clauses = split_clauses(shows)
    for clause in clauses:
        if label_of(clause) == "footer":
            for label, note in footer_items(clause):
                if re.fullmatch(EXIT_RE, label) and hits(GATE_RE, note):
                    return fail("exit-gated", f"exit {label} drawn gated in the footer of {name}")
    want = {label for label, _, _ in expected(name, kind, params, facts)}
    free = [x for x in clauses if label_of(x) not in want]
    for clause in [producer] + free:
        gated = exit_gated(clause)
        if gated:
            return fail("exit-gated", f"exit drawn gated in {name} ({gated[0]!r}): {clause[:60]!r}")
    found = rejection_gate(name, kind, shows)
    if found:
        return found
    ctx: dict[str, Any] = {
        "where": f"frame {name}",
        "kind": kind,
        "line": producer + " ; " + shows,
        "known": known,
        "export": name.startswith("SCR-025/") and kind != "availability",
        "export_frame": name.startswith("SCR-025/"),
        "focus": FOCUS.get(name, FOCUS.get(kind)),
    }
    for clause in [producer] + free:
        found = unit_gate(clause, ctx, facts)
        if found:
            return found
    if kind not in T2_KINDS and {"T2", "legs", "reason"} & set(labelled(shows)):
        return fail("t2-over", f"frame {name} is not T2 (over-conversion; validity is no lock)")
    found = clause_gate(name, kind, params, facts, labelled(shows))
    if found:
        return found
    labels = tuple(clause_label(x) for x in free)
    if labels != DESCRIPTIVE[name]:
        return fail("clause-label", f"frame {name}: free clauses {labels}, the tool's are fixed")
    if producer != PRODUCERS[name]:
        return fail("producer", f"frame {name}: the Producer cell is not the tool's, whole")
    if deck is not None:
        for key in re.findall(r"`([^`]+)`", keys):
            if key not in deck:
                return fail("key-deck", f"copy key not in the deck (§9) in {name}: {key}")
    if keys != COPY_KEYS[name]:
        return fail("copy-keys", f"frame {name}: the copy keys are not the tool's, whole")
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


FRAME_CACHE: dict[tuple[object, ...], str | None] = {}


def frame_gates(
    spec: str, facts: dict[str, Any], deck: set[str] | None, known: list[str]
) -> list[str]:
    """Every frame row through the FRAME ladder, then the inventory both ways."""
    bad: list[str] = []
    seen: dict[str, int] = {}
    for name, c, _ in frame_rows(spec):
        seen[name] = seen.get(name, 0) + 1
        if name not in KIND:
            continue
        key = (
            id(facts),
            id(known),
            name,
            " | ".join(c),
            None if deck is None else tuple(sorted(deck)),
        )
        if key not in FRAME_CACHE:
            FRAME_CACHE[key] = frame_gate(name, c, facts, deck, known)
        found = FRAME_CACHE[key]
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
    if len(lines) < 2 or not re.fullmatch(r"\|[ :|-]+\|", lines[1].strip()):
        return fail("preview-columns", f"{where}: its separator row carries text")
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
    """§0: the cap, the light twins, the exports, every cell of every row against the tool's
    (BOARDS: the Draws and the Theme whole) and the reconciliation with the frame rows."""
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
        frames = set(re.findall(FRAME_NAME_RE, draws))
        if slug.endswith("-light") != (theme == "light"):
            bad.append(fail("board-theme", f"§0 board {num}: its slug and its theme disagree"))
        elif theme not in ("dark", "light"):
            bad.append(fail("board-theme", f"§0 board {num}: its Theme cell is not dark or light"))
        if export != f"`docs/design/E15/img/E15-D09-{num}-{slug}.png`":
            bad.append(fail("board-export", f"§0 board {num}: export path {export} not its name"))
        if status != "pending":
            bad.append(fail("board-status", f"§0 board {num}: status {status!r} (text-first)"))
        unknown = sorted(frames - set(KIND))
        for f in unknown:
            bad.append(fail("board-unknown", f"§0 board {num} names an unknown frame {f}"))
        if not unknown and num in BOARDS and draws != BOARDS[num][0]:
            bad.append(fail("board-draws", f"§0 board {num}: its Draws cell is not the tool's"))
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
    """The header, the deviations, the AC trace and the ruled questions and conditions, each row
    whole against the tool's (M15: a qualifier added or the pending mark dropped is a FAIL), A3."""
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
    trace_rows = {cells(r)[0]: squeeze(r) for r in PINNED[TRACE_HEAD][1]}
    pending = not re.search(PLACEHOLDER_RE, spec)
    for i, row in found.items():
        status = cells(row)[-1]
        if status not in TRACE_STATUS:
            bad.append(fail("trace-status", f"AC trace {i}: status not one of {TRACE_STATUS}"))
        elif status == "text pending" and pending:
            bad.append(fail("trace-pending", f"AC trace {i} still says text pending"))
        elif ids.count(i) == 1 and i in trace_rows and squeeze(row) != trace_rows[i]:
            bad.append(fail("trace-row", f"AC trace {i} is not the tool's row, whole"))
    bqs = block(spec, "## The questions", "\n## ")
    if f"{RULING}, on the BQ comment {BQ_COMMENT}" not in bqs.split("\n")[0]:
        bad.append(fail("bq-ruled", "the questions' heading lost the ruling or the BQ comment"))
    want = {cells(r)[0]: squeeze(r) for r in PINNED[BQ_HEAD][1]}
    have = {
        m.group(1): squeeze(m.group(0))
        for m in re.finditer(r"^\| (BQ-\d+|Condition \d) +\|.*$", bqs, MULTI)
    }
    for qid, row in want.items():
        got = have.get(qid)
        if got is None and qid.startswith("Condition"):
            bad.append(fail("condition", f"{qid} missing from the questions table"))
        elif got is None:
            bad.append(fail("bq-missing", f"{qid} missing from the questions table"))
        elif qid.startswith("Condition"):
            if got != row:
                bad.append(fail("condition", f"{qid} is not the ruled row, whole"))
        elif f"RULED ({RULING})" not in cells(got)[-1]:
            bad.append(fail("bq-ruled", f"{qid} not RULED ({RULING})"))
        elif got != row:
            bad.append(fail("bq-terms", f"{qid} row is not the ruled one, whole (M15)"))
    if A3_STANDING not in spec[: spec.find("\n## 0. ")]:
        bad.append(fail("standing", "the standing additions lost A3: the exits are never gated"))
    bq_n = len([q for q in have if q.startswith("BQ-")])
    conds = len([q for q in have if q.startswith("Condition")])
    return bad, {"bq_rows": bq_n, "ac_rows": len(ids), "conditions": conds}


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


INVISIBLE_OK = {"\n", "\t"}
CONFUSABLE_SCRIPTS = ("CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC")
CONFUSABLE_OK = {"Δ"}


def invisible_problem(text: str) -> str | None:
    """A character that hides or impersonates (Trojan-Source hygiene for a public repository): a
    format or control character, a letter of a script that mimics Latin, an HTML entity."""
    for ch in set(text):
        if ch in INVISIBLE_OK:
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cc", "Co", "Cs", "Zl", "Zp"):
            return f"U+{ord(ch):04X}"
        name = unicodedata.name(ch, "")
        if ch not in CONFUSABLE_OK and name.split(" ")[0] in CONFUSABLE_SCRIPTS:
            return f"U+{ord(ch):04X} {name}"
    m = re.search(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);", text)
    return m.group(0) if m else None


def container_problem(spec: str) -> str | None:
    """Text a reader of the rendered page never sees, or HTML that renders: a comment other than
    an audit marker, a fenced block, a raw HTML tag outside code."""
    for m in re.finditer(r"<!--.*?(?:-->|$)", spec, MULTI):
        if not re.fullmatch(MARKER_RE, m.group(0)) and not re.match(r"<!--\s*audit:", m.group(0)):
            return m.group(0)[:40]
    if "```" in spec or "~~~" in spec:
        return "a fenced block"
    body = re.sub(r"`[^`\n]*`", "", re.sub(MARKER_RE, "", spec))
    tag = re.search(r"</?[A-Za-z][\w-]*(?:\s[^<>\n]*)?>", body)
    return tag.group(0)[:40] if tag else None


def wrap_problem(spec: str) -> int | None:
    """M14: a paragraph or a list item is one line, so no sentence is ever split across two (a
    wrapped sentence would evade every sentence gate)."""
    lines = spec.split("\n")
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if not a.strip() or not b.strip() or a.startswith(("|", "#")) or b.startswith("|"):
            continue
        if re.match(r"(?:- |\d+\. |#)", b):
            continue
        return i + 2
    return None


RULED_FORM_RE = (
    r"BQ-\d+(?:,? (?:and )?BQ-\d+)* RULED|RULED \(" + RULING + r"\)|PROPOSED unless RULED"
    r"|RULED by the orchestrator|\(RULED, binding on every frame\)|\"RULED\" cites "
    + RULING
    + r"|conditions RULED"
)


def ruled_problems(spec: str) -> list[str]:
    """A4: "RULED" only where a ruling stands — a BQ by number, or the ruling's id — and never on a
    decision of this spec (§1.4's rows are PROPOSED; a ruled question is the BQ table's)."""
    bad: list[str] = []
    body = re.sub(RULED_FORM_RE, "", spec)
    for m in re.finditer(r"^\| (D09-D\d+) +\|.*$", section(spec, 1, 2), MULTI):
        if re.search(r"(?i)\bruled\b", m.group(0)):
            return [fail("ruled", f"{m.group(1)} claims a ruling; a decision is PROPOSED")]
    for m in re.finditer(r"\bRULED\b", body):
        ln = body[body.rfind("\n", 0, m.start()) + 1 : body.find("\n", m.start())]
        return [fail("ruled", f"RULED without its ruling: {ln[:60]!r}")]
    for n in re.findall(r"BQ-(\d+)(?:,? (?:and )?BQ-\d+)* RULED", spec):
        if not 1 <= int(n) <= 16:
            return [fail("ruled", f"BQ-{n} RULED names no ruled question")]
    return bad


KNOWN_KEYS = set(CITE_KEYS.split("|"))


def cite_key_problem(spec: str) -> str | None:
    """A4: a line cite to a document the tool does not pin (E15-D08 is PENDING: named only)."""
    for m in re.finditer(r"`([A-Za-z][A-Za-z0-9]*):(\d+)(?:–\d+)?`", spec):
        if m.group(1) not in KNOWN_KEYS:
            return m.group(0)
    pending = re.search(r"\bD08:\d+", spec)
    return pending.group(0) if pending else None


def sha_problems(spec: str) -> list[str]:
    """A4: every commit id is a pinned merge's (E15-D08 has none), each printed as often as the tool
    pins it, so none is swapped for a ref or edited in one of its copies."""
    bad: list[str] = []
    for tok in sorted(set(re.findall(r"\b[0-9a-f]{7,40}\b", spec))):
        if not re.search(r"[a-f]", tok) or tok.isdigit():
            continue
        if not any(s.startswith(tok) for s in KNOWN_SHAS):
            bad.append(fail("sha", f"a commit id no pinned merge has: {tok}"))
    for sha, want in SHA_COUNTS.items():
        have = len(re.findall(rf"\b{sha[:8]}[0-9a-f]*\b", spec))
        if have != want:
            bad.append(fail("sha", f"{sha[:8]} printed {have} times, the tool pins {want}"))
    return bad


def text_gates(spec: str, t: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """Reasons, upstream copy, the `14` pointer lines whole, placeholders, the repository-wide
    rules: private paths, closing keywords, invisible or impersonating characters, comments and
    raw HTML, wrapped paragraphs, "RULED", unpinned cites, commit ids, dangling ids."""
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
    if (
        runs is None
        or len(at) != 2
        or at[0] not in runs[0]
        or at[1] not in runs[1]
        or tuple(plan14[i] for i in at) != POINTER_LINES
    ):
        bad.append(
            fail(
                "pointer-14",
                f"`14` pointer lines at {[i + 1 for i in at]}: not after the checklists or not the "
                "tool's text, byte for byte",
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
        odd = invisible_problem(txt)
        if odd:
            bad.append(fail("invisible", f"{label}: an invisible or impersonating character {odd}"))
        if label == "tool":
            continue
        if re.search(CLOSING, txt, re.IGNORECASE):
            bad.append(fail("closing", f"{label}: a closing keyword (text-first: Refs + Partial)"))
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if not re.search(rf"^\*\*{re.escape(r)}\b", constitution, MULTI):
                bad.append(fail("rule-id", f"{label}: dangling rule id {r}"))
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(fail("catalogue-id", f"{label}: no catalogue heading for {c}"))
    hidden = container_problem(spec)
    if hidden:
        bad.append(fail("comment", f"spec: text a reader never sees, or raw HTML: {hidden!r}"))
    wrapped = wrap_problem(spec)
    if wrapped:
        bad.append(fail("wrap", f"spec line {wrapped}: a paragraph runs on to a second line"))
    bad += ruled_problems(spec) + sha_problems(spec)
    cite = cite_key_problem(spec)
    if cite:
        bad.append(
            fail("cite-unpinned", f"a line cite to a document the tool does not pin: {cite}")
        )
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
    "presets_user",
    "presets_mib",
    "create_kib",
    "example_mb",
    "body_pct",
    "p95_window_s",
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


def line_subsections(spec: str) -> list[str]:
    """The `### n.m` subsection of each line ("n" before its first subsection, "-1" before §0)."""
    out, current = [], "-1"
    for ln in spec.split("\n"):
        m = re.match(r"## (\d+)\. ", ln)
        if m:
            current = m.group(1)
        m = re.match(r"### (\d+\.\d+) ", ln)
        if m:
            current = m.group(1)
        out.append(current)
    return out


def table_spans(spec: str) -> dict[int, str]:
    """For each table row (0-based line), the squeezed header row of the table it belongs to."""
    out: dict[int, str] = {}
    head = ""
    for i, ln in enumerate(spec.split("\n")):
        if not ln.startswith("|"):
            head = ""
            continue
        if not head:
            head = squeeze(ln)
        out[i] = head
    return out


def squeeze(line: str) -> str:
    return re.sub(r" {2,}", " ", line.strip())


def line_gate(line: str, sec: int, sub: str, facts: dict[str, Any], known: list[str]) -> str | None:
    """The LINE ladder: one line of prose or one row of a table no other ladder reads, every
    sentence or cell through the vocabulary ladder."""
    where = f"§{sec} line {line[:40]!r}"
    found = vocabulary_gate(where, line, frame=False)
    if found:
        return found
    if line.startswith("|"):
        units = cells(line)
        if re.match(DECK_ROW_RE, line):
            units = [units[1], units[3]] if len(units) > 3 else units
        units = [s for u in units for s in sentences(u)]
    else:
        units = sentences(line)
    ctx: dict[str, Any] = {"where": f"§{sec}", "sub": sub, "line": line, "known": known}
    for unit in units:
        found = unit_gate(unit, ctx, facts)
        if found:
            return found
    return None


def line_gates(spec: str, facts: dict[str, Any], known: list[str]) -> list[str]:
    """Every line no other ladder reads: prose, headings, list items and the tables that are
    neither frames, §4.2 and §4.3, §0's boards nor a table the tool holds whole."""
    bad: list[str] = []
    secs, subs = line_sections(spec), line_subsections(spec)
    tables, spans = table_indices(spec), table_spans(spec)
    for i, line in enumerate(spec.split("\n")):
        if i in tables or re.match(BOARD_RE, line) or not line.strip():
            continue
        if 2 <= secs[i] <= 5 and re.match(FRAME_RE, line):
            continue
        head = spans.get(i)
        if head in PINNED or head == KEYBOARD_HEAD and squeeze(line) != head:
            if head == KEYBOARD_HEAD:
                cell = cells(line)
                rest = " | ".join(cell[3:])
                found = line_gate("| " + rest + " |", secs[i], subs[i], facts, known)
                if found:
                    bad.append(found)
            continue
        key = (id(facts), id(known), line, secs[i], subs[i])
        if key not in LINE_CACHE:
            LINE_CACHE[key] = line_gate(line, secs[i], subs[i], facts, known)
        if LINE_CACHE[key]:
            bad.append(str(LINE_CACHE[key]))
    return bad


# One line's verdict, kept for the run: a mutation changes a line or two, the rest are re-read
# from here (`--self-test` runs every gate once per mutation).
LINE_CACHE: dict[tuple[int, int, str, int, str], str | None] = {}


def pinned_gates(spec: str) -> list[str]:
    """The tables the tool holds whole (they restate frame facts or record a ruling): each row
    squeezed, compared with the tool's, in order (M13, M15)."""
    bad: list[str] = []
    found: dict[str, list[str]] = {}
    lines = spec.split("\n")
    for i, head in table_spans(spec).items():
        line = squeeze(lines[i])
        if head in PINNED and line != head and not re.fullmatch(r"\|[ :|-]+\|", line):
            found.setdefault(head, []).append(line)
    spans = table_spans(spec)
    for i, head in spans.items():
        if spans.get(i - 1) is None or squeeze(lines[i - 1]) != head:
            continue
        if not re.fullmatch(r"\|[ :|-]+\|", squeeze(lines[i])):
            bad.append(fail("separator", f"a table's separator row carries text: {head[:40]!r}"))
    for head, (code, want) in PINNED.items():
        have = found.get(head, [])
        if code != "pinned-row":
            continue
        for n, (a, b) in enumerate(zip(have, want, strict=False), 1):
            if a != b:
                bad.append(fail("pinned-row", f"{head[:40]!r} row {n} is not the tool's, whole"))
                break
        else:
            if len(have) != len(want):
                bad.append(
                    fail("pinned-row", f"{head[:40]!r}: {len(have)} rows, the tool's {len(want)}")
                )
    return bad


def keyboard_gates(spec: str) -> list[str]:
    """§7's keyboard model: every row's frames, initial focus and Tab order are the tool's (the
    focus a rejection lands on, the drop zone never a stop: S19, S20)."""
    bad: list[str] = []
    spans = table_spans(spec)
    rows = [
        cells(ln)
        for i, ln in enumerate(spec.split("\n"))
        if spans.get(i) == KEYBOARD_HEAD
        and squeeze(ln) != KEYBOARD_HEAD
        and not re.fullmatch(r"\|[ :|-]+\|", squeeze(ln))
    ]
    have = {r[0]: (r[1], r[2]) for r in rows if len(r) >= 3}
    for frames, (focus, tab) in KEYBOARD.items():
        got = have.get(frames)
        if got is None:
            bad.append(fail("keyboard", f"§7's keyboard model lacks the row {frames[:50]!r}"))
        elif got != (focus, tab):
            bad.append(fail("keyboard", f"§7's keyboard row {frames[:40]!r}: focus or Tab order"))
    for frames in sorted(set(have) - set(KEYBOARD)):
        bad.append(
            fail("keyboard", f"§7's keyboard model has a row the tool lacks {frames[:40]!r}")
        )
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
    pairs = {(r["fg"], r["bg"], r["role"]) for r in ctx.measured["matrix"]}
    for key in sorted(set(found) - pairs):
        bad.append(
            fail("contrast-row", f"§8 has a row the tool does not measure: {key[0]} on {key[1]}")
        )
    if FORCED_COLORS not in s8:
        bad.append(fail("forced-colors", "§8 lacks the `forced-colors: active` rendering (R2)"))
    return bad


def deck_rows(spec: str) -> dict[str, str] | None:
    """§9's keyed rows (key -> its String cell), or None while §9 is a placeholder."""
    if placeholder(spec, 9) or not section(spec, 9, 10):
        return None
    return {m.group(1): m.group(3) for m in re.finditer(DECK_ROW_RE, section(spec, 9, 10), MULTI)}


def deck_cell(key: str, facts: dict[str, Any]) -> str:
    """A deck row's String cell as the tool holds it: a template with its fixture rendering, or the
    static string whole."""
    if key in TEMPLATES:
        template, rendering = TEMPLATES[key], render(key, facts)
        return f'"{template}"' if rendering == template else f'"{template}" · fixture "{rendering}"'
    return DECK_STATIC[key]


def deck_gates(deck: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """§9: every String cell the tool's whole (M11: a reason, a label or a list changed is a FAIL),
    the deck's keys the tool's, no jargon, every reason key one short sentence."""
    bad: list[str] = []
    for key, cell in deck.items():
        string = first(r'^"([^"]*)"', cell)
        jargon = [pat for pat in BANNED_COPY if re.search(pat, string)]
        if jargon:
            bad.append(fail("jargon", f"§9 jargon in copy: {jargon[0]!r} in {key}"))
        elif re.match(r"(?:rbac|workspace\.limit|ws\.export)\.", key) and (
            len(string) > facts["reason_max"] or not string.endswith(".")
        ):
            bad.append(fail("reason-length", f"§9 {key}: a reason is one sentence of ≤ 60"))
        elif key not in TEMPLATES and key not in DECK_STATIC:
            bad.append(fail("deck-template", f"§9 has a key the tool does not hold: {key}"))
        elif cell != deck_cell(key, facts):
            bad.append(fail("deck-template", f"§9 {key}: not the tool's string, whole"))
    for key in sorted((set(TEMPLATES) | set(DECK_STATIC)) - set(deck)):
        bad.append(fail("deck-template", f"§9 lacks the tool's key {key}"))
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
    for n, phrase, code in REQUIRED:
        if phrase not in section(spec, int(n), int(n) + 1):
            bad.append(fail(code, f"§{n} lost the restated fact {phrase[:50]!r} (M13)"))
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
        if have_n != want:
            bad.append(fail("marker-count", f"audit:{key} appears {have_n} times, {want} pinned"))
    for key in sorted(set(re.findall(r"audit:([A-Za-z0-9_.-]+)=", spec)) - set(MARKERS)):
        bad.append(fail("marker-count", f"audit:{key} is not pinned in MARKER_TABLE"))
    return bad


SEC_BEARING_RE = (
    r"(?i)\bnever included\b|\bincluded\b|\bexcluded\b|\bsh" + r"ar(?:e|es|ed|ing|eable)\b"
    r"|\bcredentials?\b|\bapi keys?\b|\b(?:sub-?)?accounts?\b|\buntrusted\b|\bmark-?up\b"
    r"|\bmarkdown\b|\blink(?:s|ed|ing)?\b|\bhtml\b|\braw\b|\becho\w*|\bre-?check\w*|\bpartial\w*"
    r"|\bkept\b|\bkeeps?\b|\buploaded\b|\blogged\b|\bcached\b"
)
STATUS_BEARING_RE = (
    r"\bRULED\b|(?i:\b(?:applied|agreed|settled|final|finali[sz]ed|confirmed|accepted|adopted"
    r"|decided|in force|approved|signed off)\b)"
)
PIN_SEP = " ‖ "
PIN_WIDTH = 90
Unit = tuple[str, str, str]


def one_space(text: str) -> str:
    return " ".join(text.split())


def pin_units(spec: str) -> list[Unit]:
    """Every heading, prose sentence and sentence of a table cell: (section, place, text)."""
    out: list[Unit] = []
    section = "title"
    for line in spec.split("\n"):
        head = re.match(r"^#{1,6} (.*)$", line)
        if head:
            num = re.match(r"(\d+(?:\.\d+)?)\.? ", head.group(1))
            section = f"§{num.group(1)}" if num else one_space(head.group(1))[:40]
            out.append((section, "heading", one_space(head.group(1))))
        elif line.startswith("|"):
            if re.fullmatch(r"\|[ :|-]+\|", squeeze(line)):
                continue
            row = cells(line)
            rid = one_space(row[0])[:40]
            for col, cell in enumerate(row, 1):
                out += [(section, f"row {rid} · col {col}", one_space(s)) for s in sentences(cell)]
        elif line.strip():
            out += [(section, "prose", one_space(s)) for s in sentences(line)]
    return out


def pin_selected(spec: str, select: str, headings: bool) -> list[Unit]:
    return [
        u for u in pin_units(spec) if re.search(select, u[2]) or (headings and u[1] == "heading")
    ]


def render_pins(spec: str, select: str, headings: bool = False) -> str:
    """The pinned table as `--repin-security` / `--repin-status` print it: a `§ section` line per
    section, an `@ place` line per unit, its text wrapped at spaces on lines indented two spaces
    (joined with one space, the lines are the unit again)."""
    lines: list[str] = []
    last = ""
    for section, where, text in pin_selected(spec, select, headings):
        if section != last:
            lines.append(f"§ {section}")
            last = section
        lines.append(f"@ {where}")
        lines += [
            "  " + part
            for part in textwrap.wrap(
                text, PIN_WIDTH, break_long_words=False, break_on_hyphens=False
            )
        ]
    return "\n".join(lines)


def pin_rows(table: str) -> list[Unit]:
    """A pinned table parsed: (section, place, text) in document order."""
    rows: list[Unit] = []
    section, where = "", ""
    parts: list[str] = []
    for line in [*table.strip("\n").split("\n"), "@ end"]:
        if line.startswith(("§ ", "@ ")) and parts:
            rows.append((section, where, " ".join(parts)))
            parts = []
        if line.startswith("§ "):
            section = line[2:]
        elif line.startswith("@ "):
            where = line[2:]
        elif line.startswith("  "):
            parts.append(line[2:])
    return rows


def pin_gate(spec: str, select: str, table: str, headings: bool) -> str | None:
    """Every selected unit equals its pinned entry, in order: the first unit that is new,
    changed, moved or duplicated, or a pinned unit gone, named with its place."""
    have, want = pin_selected(spec, select, headings), pin_rows(table)
    for got, pin in itertools.zip_longest(have, want):
        if got == pin:
            continue
        if got is None and pin is not None:
            return f"{pin[0]}{PIN_SEP}{pin[1]}: a pinned unit is gone: {pin[2][:60]!r}"
        if got is not None:
            return (
                f"{got[0]}{PIN_SEP}{got[1]}: new, changed, moved or duplicated, not the pinned "
                f"text: {got[2][:60]!r}"
            )
    return None


def pins_gates(spec: str) -> list[str]:
    """The two default-deny pins, the security text first: the first pin with a FAIL."""
    found = pin_gate(spec, SEC_BEARING_RE, SEC_PIN_TXT, False)
    if found:
        return [fail("sec-pin", f"security text (SEC_PIN_TXT): {found}")]
    found = pin_gate(spec, STATUS_BEARING_RE, STATUS_PIN_TXT, True)
    if found:
        return [fail("status-pin", f"a ruling or a settled state (STATUS_PIN_TXT): {found}")]
    return []


def gates(spec: str, ctx: Ctx) -> tuple[list[str], dict[str, Any]]:
    """Every gate over one copy of the spec; returns the FAILs and the numbers it derived."""
    bad: list[str] = []
    b0, n0 = board_gates(spec)
    bh, nh = head_gates(spec)
    bc, nc = cite_gates(spec, ctx.t)
    deck = deck_rows(spec)
    known = known_copy(ctx.facts)
    bad += bh + b0 + frame_gates(spec, ctx.facts, set(deck) if deck is not None else None, known)
    for head, report in (("### 4.2 ", False), ("### 4.3 ", True)):
        found = table_gate(spec, head, report)
        if found:
            bad.append(found)
    bad += bc + line_gates(spec, ctx.facts, known) + text_gates(spec, ctx.t, ctx.facts)
    bad += reconcile_gates() + pinned_gates(spec) + keyboard_gates(spec)
    bad += section_gates(spec, ctx) + contract_gates(ctx.facts)
    bad += [fail("token-missing", f"token MISSING: {tok}") for tok in ctx.missing]
    bad += [
        fail("contrast-fail", f"contrast FAIL: {r['element']}")
        for r in ctx.measured["matrix"]
        if r["verdict"] in ("FAIL", "MISSING")
    ]
    numbers_ = numbers_of(spec, ctx, {**n0, **nh, **nc})
    bad += marker_gates(spec, numbers_)
    if not bad:
        bad += pins_gates(spec)
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


def cell_add(frame: str, index: int, words: str, sep: str = ", ") -> Callable[[str], str]:
    """Append `sep` and `words` to one cell of a frame row (1 the Producer, 2 the Shows)."""

    def fn(ln: str) -> str:
        c = ln.split(" | ")
        c[index] = c[index].rstrip() + sep + words
        return " | ".join(c)

    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", fn)


def line_add(start: str, sentence: str) -> Callable[[str], str]:
    """Append a sentence to the one prose line that starts with `start`."""
    return row_fn(rf"^{re.escape(start)}.*$", lambda ln: ln.rstrip() + " " + sentence)


def separator_text(s: str) -> str:
    """Text written into the AC trace's separator row."""
    lines = s.split("\n")
    i = next(n for n, x in enumerate(lines) if squeeze(x) == TRACE_HEAD)
    lines[i + 1] = lines[i + 1].rstrip().rstrip("|") + " plain |"
    return "\n".join(lines)


def fold_mutations(share: str) -> list[Mutation]:
    """The lens round's findings, each a frame-level gate now (M1-M17, the security lens's tool
    items, the design lens's clauses): one mutation per finding, its natural wording, its place."""
    rn, rm, ro = (
        "SCR-026/rejected-version-newer",
        "SCR-026/rejected-malformed",
        "SCR-026/rejected-oversized",
    )
    pv, pk, va = "SCR-026/preview", "SCR-026/pick", "SCR-026/validating"
    rep, perm, ee = "SCR-026/report", "SCR-026/entry-permission", "SCR-025/export-entry"
    ec, cr, ll = "SCR-025/export-cancelled", "SCR-026/creating", "SCR-026/import-leg-lost"
    bc, un = "SCR-026/budget-confirm", "SCR-026/refused-unconfirmed"
    table, strings = "**The table (BQ-10 RULED;", "**Strings from the file (Condition 1; DL-17).**"
    outcome, anatomy = (
        "**Every rejection and every refusal here is an outcome",
        "One anatomy serves the six",
    )
    t2, order, envelope = (
        "**T2 — disabled with a visible reason",
        "**The order (BQ-5 RULED;",
        "The version is read",
    )
    lists, entries, handoffs = (
        "**What the two lists say (BQ-2 RULED;",
        "**Entries (BQ-9 RULED).**",
        "**Hand-offs.**",
    )
    limits = "Every number below is the tool's"
    sharing = "safe for " + "sha" + "ring"
    return [
        ("M1-producer-verb", cell_add(rn, 1, "Import anyway stays offered"), "[import-verb]", None),
        (
            "M1-producer-remap",
            cell_add(pv, 1, "the account filter is remapped to your default account"),
            "[account-remap]",
            None,
        ),
        ("M1-producer-zone", cell_add(pk, 1, "the drop zone is a Tab stop"), "[drop-zone]", None),
        (
            "M1-producer-early",
            cell_add(va, 1, "a workspace has been created for this file"),
            "[created-early]",
            None,
        ),
        (
            "M1-producer-markup",
            cell_add(pv, 1, "each name from the file is shown as a link to its source"),
            "[untrusted-markup]",
            None,
        ),
        ("M1-producer-focus", cell_add(rm, 1, "focus lands on Cancel"), "[rejection-focus]", None),
        ("M1-producer-number", cell_add(pk, 1, "the limit is 5 MB"), "[limit-number]", None),
        (
            "M1-producer-legs",
            cell_add(
                perm, 1, "its legs run `rbac.permission` → `rbac.view_as` → `workspace.limit.count`"
            ),
            "[legs-order]",
            None,
        ),
        (
            "M1-producer",
            frame_sub(pk, "the dialog opens empty", "the dialog opens"),
            "[producer]",
            None,
        ),
        ("M1-copy-keys", frame_sub(pk, " · `e15.import.cancel`", ""), "[copy-keys]", None),
        (
            "M1-board-draws",
            line_sub("| 03 ", "`SCR-026/preview`", f"`SCR-026/preview` · it is {share}"),
            "[board-draws]",
            None,
        ),
        (
            "M1-board-theme",
            line_sub("| 03 ", "| dark ", "| dark · Cancel is disabled "),
            "[board-theme]",
            None,
        ),
        ("M2-label", frame_add(pk, "note: a quiet word on the frame"), "[clause-label]", None),
        ("M2-partial", frame_add(rm, "note: the two valid layouts were kept"), "[partial]", None),
        (
            "M2-early",
            frame_add(pv, "note: a draft workspace is saved while you review"),
            "[created-early]",
            None,
        ),
        ("M2-verb", frame_add(rn, "button: Import"), "[import-verb]", None),
        (
            "M2-export-role",
            frame_add(ee, "note: Export… is for Owners only"),
            "[export-gated]",
            None,
        ),
        (
            "M2-focus",
            frame_add(ro, "focus: on arrival the focus ring is on Cancel"),
            "[rejection-focus]",
            None,
        ),
        (
            "M3-partial",
            line_add(outcome, "The layouts that passed stay in your workspaces."),
            "[partial]",
            None,
        ),
        (
            "M3-early",
            line_add(table, "A workspace has been created for this file."),
            "[created-early]",
            None,
        ),
        (
            "M3-verb",
            line_add(
                anatomy,
                "On a rejection the footer keeps Import as new workspace beside Choose another "
                "file.",
            ),
            "[import-verb]",
            None,
        ),
        (
            "M3-lock",
            line_add(anatomy, "The verb is greyed out on a rejection."),
            "[rejection-lock]",
            None,
        ),
        (
            "M3-export",
            line_add("- **Export…, a read.**", "Export… is disabled for a Viewer."),
            "[export-gated]",
            None,
        ),
        (
            "M3-recheck",
            line_add(
                "**What the check in the browser is", "The server does not check the file again."
            ),
            "[server-recheck]",
            None,
        ),
        ("M3-comment", sub(f"\n{handoffs}", f"\n<!-- a note -->\n\n{handoffs}"), "[comment]", None),
        (
            "M4-frame",
            frame_add(
                pv,
                "note: Import as new workspace is disabled until the preview has no dropped items",
            ),
            "[t2-over]",
            None,
        ),
        (
            "M4-prose",
            line_add(table, "Import as new workspace stays inactive until the table is read."),
            "[t2-over]",
            None,
        ),
        ("M4-import", line_add(table, "Import is disabled."), "[t2-over]", None),
        (
            "M5-verb",
            frame_add(pk, "note: the dialog disables Cancel until the file is read"),
            "[exit-gated]",
            None,
        ),
        (
            "M5-role",
            frame_add(perm, "note: a Viewer cannot cancel the dialog"),
            "[exit-gated]",
            None,
        ),
        (
            "M5-negator",
            frame_add(
                pk, "note: Cancel is never disabled, but is greyed out while the file is read"
            ),
            "[exit-gated]",
            None,
        ),
        (
            "M5-respond",
            line_add(order, "Cancel doesn't respond until the check ends."),
            "[exit-gated]",
            None,
        ),
        (
            "M5-deck",
            line_sub("| `e15.import.cancel` ", '"Cancel"', '"Cancel (disabled while checking)"'),
            "[deck-template]",
            9,
        ),
        ("M6-frame", frame_add(pv, "note: the file's name is a link"), "[untrusted-markup]", None),
        (
            "M6-prose",
            line_add(strings, "The label supports bold and italics."),
            "[untrusted-markup]",
            None,
        ),
        ("M7-frame", frame_add(pk, "note: the drop-zone is a Tab stop"), "[drop-zone]", None),
        (
            "M7-prose",
            line_add("**The drop zone (BQ-9 RULED;", "The drop area takes focus."),
            "[drop-zone]",
            None,
        ),
        (
            "M7-keyboard",
            line_sub(
                "| `SCR-026/pick`, `SCR-026/drag-over`",
                "× → Choose file… → Cancel",
                "× → the drop zone → Choose file… → Cancel",
            ),
            "[keyboard]",
            7,
        ),
        ("M8-prose", line_add(limits, "A 5 MB limit applies."), "[limit-number]", None),
        (
            "M8-marker",
            sub(
                "a file of at most 2 <!-- audit:contract.size_mb=2 --> MB (E15-S07's default",
                "a file of at most 2 MB (E15-S07's default",
            ),
            "[marker-count]",
            None,
        ),
        (
            "M9-legs-words",
            line_add(t2, "The legs run permission first, then view-as, then the limit."),
            "[legs-order]",
            6,
        ),
        (
            "M9-legs-ascii",
            line_add(
                t2, "The legs run `rbac.permission` -> `rbac.view_as` -> `workspace.limit.count`."
            ),
            "[legs-order]",
            6,
        ),
        (
            "M9-steps-chain",
            line_sub(
                limits,
                "parse depth / node count → schema → version",
                "parse depth / node count → version",
            ),
            "[steps]",
            None,
        ),
        (
            "M9-steps-list",
            line_add(order, "The checks run the version, then the schema, then the registry."),
            "[steps]",
            None,
        ),
        (
            "M9-app-version",
            line_add(envelope, "The file's app version is compared with the app's."),
            "[version-field]",
            None,
        ),
        ("M10-pronoun", frame_add(pv, "note: it is remapped to yours"), "[account-remap]", None),
        (
            "M10-name",
            frame_add(rep, "note: the dropped filter named Hedge Desk"),
            "[foreign-account]",
            None,
        ),
        (
            "M10-id",
            line_add(strings, "The filter named acct-7731 is dropped."),
            "[foreign-account]",
            None,
        ),
        (
            "M11-included",
            line_sub(
                "| `e15.export.included` ",
                "{templates} · {presets}.",
                "{templates} · {presets} · densities.",
            ),
            "[deck-template]",
            9,
        ),
        (
            "M11-reason",
            line_sub(
                "| `rbac.permission` ",
                '"Your role can\'t save workspaces."',
                '"Your role is read-only here."',
            ),
            "[deck-template]",
            9,
        ),
        (
            "M12-excluded",
            frame_sub(
                ec,
                f'; excluded: a CMP-036 list, first-class, one item per clause — "{EXCLUDED}"',
                "",
            ),
            "[excluded]",
            None,
        ),
        (
            "M12-suffix",
            line_add(lists, f'Its words are "{EXCLUDED} Everything else is included."'),
            "[excluded]",
            None,
        ),
        (
            "M12-trust",
            line_add(entries, f"{TRUST_NOTE} It may carry accounts in rare cases."),
            "[trust-note]",
            None,
        ),
        (
            "M13-keyboard-focus",
            line_sub(
                "| the six rejections and `SCR-026/refused-server` ",
                "Choose another file",
                "Cancel",
            ),
            "[keyboard]",
            7,
        ),
        (
            "M13-anatomy",
            line_sub("| Focus on arrival ", "on Choose another file, on Cancel", "on Cancel"),
            "[pinned-row]",
            None,
        ),
        (
            "M13-intro-focus",
            line_sub(
                outcome, "Choose another file, the primary, focused", "Cancel, the primary, focused"
            ),
            "[rejection-focus]",
            None,
        ),
        (
            "M13-caps",
            line_add(strings, "Names are shown in full, never shortened."),
            "[caps]",
            None,
        ),
        (
            "M13-quote",
            line_add(
                envelope,
                "The refusal reads \"This file was exported by format version 2 and can't be "
                'imported into this version."',
            ),
            "[quoted-copy]",
            None,
        ),
        (
            "M13-required",
            line_sub(envelope, "Both refusals name both numbers", "Both refusals name one number"),
            "[versions]",
            5,
        ),
        (
            "M13-trace",
            row_fn(
                r"^\| AC-2 +\|.*$",
                lambda ln: ln.replace("both versions named", "the version named", 1),
            ),
            "[trace-row]",
            None,
        ),
        ("M14-wrap", line_add(table, "It is plain.\nA second line runs on."), "[wrap]", None),
        (
            "M15-decision",
            row_fn(r"^\| D09-D9 +\|.*$", lambda ln: ln.replace("150 ms", "150 ms (RULED)", 1)),
            "[ruled]",
            None,
        ),
        (
            "M15-pending",
            row_fn(
                r"^\| BQ-3 +\|.*$",
                lambda ln: ln.replace("owner approval pending (#2701)", "owner approved", 1),
            ),
            "[bq-terms]",
            None,
        ),
        (
            "M15-cite",
            line_add(entries, "E15-D08's Share section is drawn at `D08:123`."),
            "[cite-unpinned]",
            None,
        ),
        (
            "M15-sha",
            line_add("Export is a read.", "E15-D08 (#4503) is merged at `abcdef0`."),
            "[sha]",
            None,
        ),
        (
            "M15-signoff",
            line_add(handoffs, "**Sign-off:** CDO approved the copy."),
            "[honesty]",
            None,
        ),
        ("M15-lane", line_add(handoffs, "E15-D03's lane decided this."), "[honesty]", None),
        (
            "M15-qualifier",
            row_fn(
                r"^\| BQ-11 +\|.*$",
                lambda ln: ln.replace(
                    "no Import verb on any of them",
                    "no Import verb on any of them, except Import anyway on the version refusals",
                    1,
                ),
            ),
            "[bq-terms]",
            None,
        ),
        ("M17-frame", frame_add(pv, "note: the workspace keeps its live binding"), "[env]", None),
        ("M17-prose", line_add(t2, "The new workspace opens in live mode."), "[env]", 6),
        ("SEC-invisible", line_add(table, "It is plain\u200b text."), "[invisible]", None),
        ("SEC-paraphrase", line_add(lists, f"The file is {sharing}."), "[share-claim]", None),
        (
            "SEC-negator",
            frame_add(pk, "note: Cancel is not shown and is disabled"),
            "[exit-gated]",
            None,
        ),
        (
            "shape",
            frame_sub(rn, "; shape: not checked", "; shape: checked"),
            "[version-shape]",
            None,
        ),
        ("caps-creating", frame_sub(cr, "caps: names", "sizes: names"), "[caps]", None),
        (
            "renders-leg",
            frame_sub(ll, "renders: every string", "shows: every string"),
            "[renders]",
            None,
        ),
        (
            "state-confirm",
            frame_sub(bc, "until Import anyway sends the file", "until the confirm closes"),
            "[created-early]",
            None,
        ),
        (
            "unconfirmed-state",
            frame_sub(un, "state: unknown", "state: nothing imported"),
            "[unconfirmed]",
            None,
        ),
        (
            "C-01",
            line_add(
                entries,
                "A T2 control stays in the Tab order, is `aria-disabled`, and its lock glyph leads "
                "the label.",
            ),
            "[t2-once]",
            None,
        ),
        (
            "C1-raw",
            line_add("4. **Never logged.**", "The offending key is logged for support."),
            "[raw-echo]",
            None,
        ),
        (
            "C1-privilege",
            line_add(
                "**Nothing before the send, nothing after a refusal",
                "The new workspace is shared with the exporter.",
            ),
            "[privilege]",
            None,
        ),
        (
            "INC-07",
            line_add(lists, "The Included list also names your densities."),
            "[included]",
            None,
        ),
        ("close-issue", line_add(handoffs, "This PR closes issue 363."), "[closing]", None),
        ("separator", separator_text, "[separator]", None),
    ]


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
    return (
        m
        + more_mutations(share, home, closing)
        + fold_mutations(share)
        + fold2_mutations()
        + fold3_mutations()
    )


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
            "variants-invalid",
            frame_sub(
                "SCR-026/rejected-malformed",
                "`layouts[0].crosshair_sync` isn't valid",
                "`layouts[0].crosshair_sync` is odd",
            ),
            "[message]",
            None,
        ),
        (
            "variants-store",
            frame_sub(
                "SCR-026/refused-server",
                "Choose the file again in a moment.",
                "Try again in a moment.",
            ),
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
            sub(
                "`SCR-026/refused-unconfirmed`.\n",
                "`SCR-026/refused-unconfirmed`, `SCR-026/teleport`.\n",
            ),
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
        ("marker-count", sub(" <!-- audit:states=27 -->", ""), "[marker-count]", None),
        ("t2-paragraph", sec_fn(6, lambda s: s.replace("**Not T2", "**Also")), "[t2-paragraph]", 6),
        (
            "t2-once",
            sec_fn(6, lambda s: s + "\n\nE09-D09's decision rule decides every control here.\n"),
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
            sec_fn(12, lambda s: re.sub(r"^\| D09-G13( +)\|", r"| D09-G16\1|", s, flags=MULTI)),
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


def fold2_mutations() -> list[Mutation]:
    """The delta check of the lens round 1, one mutation per finding form: the delta's words, then
    another place and another case. N: a negator's reach past its own predicate (MAJOR 1); T: a
    temporal lead word, and "refused" as a refusal (MAJOR 2); F: a foreign account in any case
    (MAJOR 3); P: a PROPOSED row presented as settled, and BQ-1's sentence (MAJOR 4); R: the
    Condition 1 echo in either word order (MINOR 1); X: the security text's default-deny pin."""
    rn, ro, rm = (
        "SCR-026/rejected-version-newer",
        "SCR-026/rejected-oversized",
        "SCR-026/rejected-malformed",
    )
    rv, rw, rx = (
        "SCR-026/rejected-version-older",
        "SCR-026/rejected-wrong-type",
        "SCR-026/rejected-nodes",
    )
    rs, un = "SCR-026/refused-server", "SCR-026/refused-unconfirmed"
    ee, eu = "SCR-025/export-entry", "SCR-025/export-unavailable"
    check, caption = "**What the check in the browser is, and is not", "**The caption (DL-19).**"
    send, intro = (
        "**The send (BQ-9 RULED;",
        "**Every rejection and every refusal here is an outcome",
    )
    report, cond1 = "**The report (BQ-12 RULED;", "**Condition 1, applied to a refusal**"
    zone, absence = "**The drop zone (BQ-9 RULED;", "- **An absence.**"
    nothing_drawn = "None of them is dimmed or carries a reason."
    exits = r"^\| Cancel, `Esc`, ×, Close, Choose another file \(every frame\) .*$"
    return [
        ("N1-exit", cell_add(rm, 2, "and Esc does nothing here"), "[exit-gated]", None),
        (
            "N1-exit-prose",
            line_sub(absence, nothing_drawn, nothing_drawn[:-1] + ", and Esc DOES NOTHING here."),
            "[exit-gated]",
            None,
        ),
        (
            "N1-exit-row",
            row_fn(
                exits,
                lambda ln: ln.replace(
                    "never gated (§7)", "never gated (§7), and Esc does nothing here"
                ),
            ),
            "[exit-gated]",
            None,
        ),
        ("N1-times", cell_add(rs, 2, "and the × is HIDDEN"), "[exit-gated]", None),
        (
            "N1-verb",
            cell_add(rx, 2, "and the dialog disables Cancel until the check ends"),
            "[exit-gated]",
            None,
        ),
        (
            "N1-dot",
            frame_sub(
                eu,
                "change nothing and open nothing",
                "change nothing and open nothing · Esc does nothing here",
            ),
            "[exit-gated]",
            None,
        ),
        (
            "N1-export",
            frame_sub(
                ee,
                "with no glyph and no shortcut",
                "with no glyph and no shortcut, and Export… is for OWNERS only",
            ),
            "[export-gated]",
            None,
        ),
        (
            "N1-export-avail",
            cell_add(eu, 2, "and Export… requires the Owner role"),
            "[export-gated]",
            None,
        ),
        (
            "N1-verb-import",
            cell_add(rw, 2, "and Import anyway sits beside Choose another file"),
            "[import-verb]",
            None,
        ),
        (
            "N1-button",
            cell_add(ro, 2, "and an IMPORT BUTTON stays in the footer"),
            "[import-verb]",
            None,
        ),
        (
            "N1-markup",
            cell_add(rs, 2, "and the file's name is rendered as Markdown"),
            "[untrusted-markup]",
            None,
        ),
        (
            "N1-recheck",
            cell_add(rv, 2, "and the server does not check the file again"),
            "[server-recheck]",
            None,
        ),
        ("N1-zone", cell_add(rm, 2, "and Tab lands on the drop zone first"), "[drop-zone]", None),
        (
            "N1-zone-prose",
            line_sub(
                zone,
                "A box around",
                "Nothing is dimmed, and TAB lands on the drop zone first. A box around",
            ),
            "[drop-zone]",
            None,
        ),
        ("N1-kept", cell_add(rn, 2, "and a partial workspace is kept"), "[partial]", None),
        (
            "T1-passes",
            line_add(check, "When the check passes, the new workspace is created."),
            "[created-early]",
            None,
        ),
        (
            "T1-preview",
            line_add(
                caption, "As soon as the preview shows, the layouts are added to your workspaces."
            ),
            "[created-early]",
            None,
        ),
        (
            "T1-chosen",
            line_add(zone, "ONCE the file is chosen, the workspace is saved."),
            "[created-early]",
            None,
        ),
        (
            "T2-refuses",
            line_add(intro, "When the server refuses the file, the layouts that passed are kept."),
            "[partial]",
            None,
        ),
        (
            "T2-after",
            line_add(send, "After the rejection, the layouts that passed are kept."),
            "[partial]",
            None,
        ),
        (
            "T2-refused",
            line_add(caption, "The layouts of a REFUSED file are kept for the next attempt."),
            "[partial]",
            None,
        ),
        (
            "T2-unconfirmed",
            cell_add(un, 2, "and the two valid layouts were kept"),
            "[partial]",
            None,
        ),
        (
            "T2-once",
            cell_add(rn, 2, "and once refused, the valid layouts are kept"),
            "[partial]",
            None,
        ),
        (
            "F1-source",
            line_add(caption, "The dropped filter pointed at the source account alpha-desk."),
            "[foreign-account]",
            None,
        ),
        (
            "F1-report",
            line_add(report, "Its binding was to the ACCOUNT alpha."),
            "[foreign-account]",
            None,
        ),
        (
            "F1-frame",
            cell_add(rm, 2, "naming the colleague's sub-account hedge-2"),
            "[foreign-account]",
            None,
        ),
        (
            "P1-heading",
            sub(
                "## 10. Design-system A-rows (`15`, PROPOSED)",
                "## 10. Design-system A-rows (`15`, agreed)",
            ),
            "[status-pin]",
            None,
        ),
        (
            "P1-heading-14",
            sub(
                "### 1.4 Decisions of this spec (PROPOSED unless RULED)",
                "### 1.4 Decisions of this spec (final)",
            ),
            "[status-pin]",
            None,
        ),
        ("P1-header", sub("| New (PROPOSED) ", "| New (settled)  "), "[status-pin]", None),
        (
            "P1-row",
            row_fn(
                r"^\| D09-A1 +\|.*$",
                lambda ln: ln.replace(
                    "CMP-067 · Purpose", "CMP-067 (applied by this PR) · Purpose", 1
                ),
            ),
            "[status-pin]",
            None,
        ),
        (
            "P1-s12",
            sub(
                "Every row is PROPOSED to its owner, and none is applied by this PR",
                "Every row is agreed with its owner, and each is applied by this PR",
            ),
            "[status-pin]",
            None,
        ),
        (
            "P1-s11",
            sub(
                "**Copy-ready for the catalogue's owner, PROPOSED**",
                "**Copy-ready for the catalogue's owner, APPLIED**",
            ),
            "[status-pin]",
            None,
        ),
        (
            "P1-handoff",
            sub("Each row is a PROPOSED hand-off", "Each row is an agreed hand-off"),
            "[status-pin]",
            None,
        ),
        (
            "P1-q5",
            sub("never a shape failure: confirmed?", "never a shape failure: confirmed."),
            "[status-pin]",
            None,
        ),
        (
            "P1-bq1",
            sub(
                "This PR edits no `15` entry (BQ-1 RULED).",
                "This PR edits the `15` entries (BQ-1 RULED).",
            ),
            "[status-pin]",
            None,
        ),
        (
            "R1-server",
            line_add(cond1, "The server's own error text is shown under the message."),
            "[raw-echo]",
            None,
        ),
        (
            "R1-report",
            line_add(report, "The report repeats the file's raw JSON for each dropped item."),
            "[raw-echo]",
            None,
        ),
        (
            "R1-frame",
            cell_add(rm, 2, "and the OFFENDING LINE of the file is quoted"),
            "[raw-echo]",
            None,
        ),
        (
            "R1-appears",
            line_add(cond1, "The server's error message appears under the key."),
            "[raw-echo]",
            None,
        ),
        (
            "X1-changed",
            row_fn(
                r"^\| DoD-7 the untrusted-string rule .*$",
                lambda ln: ln.replace(
                    "the untrusted-string rule", "the untrusted-string rule, relaxed,", 1
                ),
            ),
            "[sec-pin]",
            None,
        ),
        (
            "X1-new",
            line_add(caption, "The Excluded list stays where it is."),
            "[sec-pin]",
            None,
        ),
        (
            "X1-moved",
            line_add(report, "Copy report copies the capped values, as the account row does."),
            "[sec-pin]",
            None,
        ),
    ]


def fold3_mutations() -> list[Mutation]:
    """The delta check of fold r2, one mutation per finding form: the delta's words, then another
    place and another case. E: the import's matter on an export frame, an Import verb or lock (S5,
    S6), a workspace created or kept (S10, S11) and focus on a control the frame never draws
    (S20); G: an Import verb said to stand in a footer in §6's prose (MINOR 2)."""
    ee, eu, eg = (
        "SCR-025/export-entry",
        "SCR-025/export-unavailable",
        "SCR-025/export-preparing",
    )
    ev, ef, ed, ec = (
        "SCR-025/export-preview",
        "SCR-025/export-failed",
        "SCR-025/export-done",
        "SCR-025/export-cancelled",
    )
    footer = ", and an Import button stays in the footer."
    read, rejected = "- **Export…, a read.**", "- **A rejected file.**"
    exits, legs = "- **The exits.**", "The session's legs decide, never a role's name"
    return [
        (
            "E1-verb",
            cell_add(ee, 2, "and an Import button stays in the footer"),
            "[export-import]",
            None,
        ),
        (
            "E1-verb-case",
            cell_add(ed, 2, "and IMPORT ANYWAY sits beside Close"),
            "[export-import]",
            None,
        ),
        (
            "E1-verb-producer",
            cell_add(ef, 1, "and Continue anyway brings in the readable layouts"),
            "[export-import]",
            None,
        ),
        (
            "E1-lock",
            cell_add(eu, 2, "and the import verb is locked with a padlock"),
            "[export-import]",
            None,
        ),
        (
            "E1-lock-case",
            cell_add(ev, 2, "and IMPORT AS NEW WORKSPACE sits in the footer"),
            "[export-import]",
            None,
        ),
        (
            "E2-create",
            cell_add(eg, 2, "and a draft workspace is saved meanwhile"),
            "[export-import]",
            None,
        ),
        (
            "E2-create-case",
            cell_add(ec, 2, "and A TEMPORARY WORKSPACE is made"),
            "[export-import]",
            None,
        ),
        (
            "E2-create-producer",
            cell_add(ev, 1, "and a workspace already exists for it"),
            "[export-import]",
            None,
        ),
        (
            "E2-keep",
            cell_add(ef, 2, "and the layouts that passed stay in your workspaces"),
            "[export-import]",
            None,
        ),
        (
            "E2-keep-case",
            cell_add(ed, 2, "and THE VALID LAYOUTS are kept"),
            "[export-import]",
            None,
        ),
        ("E3-focus", cell_add(ed, 2, "and focus lands on Cancel"), "[export-focus]", None),
        ("E3-focus-menu", cell_add(ee, 2, "and focus lands on Try again"), "[export-focus]", None),
        ("E3-focus-case", cell_add(eu, 2, "AND FOCUS LANDS ON CANCEL"), "[export-focus]", None),
        (
            "G1-read",
            line_sub(read, "no key (`D03:583`).", "no key (`D03:583`)" + footer),
            "[import-verb]",
            None,
        ),
        (
            "G1-rejected",
            line_sub(rejected, "BQ-11 RULED).", "BQ-11 RULED)" + footer),
            "[import-verb]",
            None,
        ),
        (
            "G1-exits",
            line_sub(exits, "included (§7).", "included (§7)" + footer),
            "[import-verb]",
            None,
        ),
        (
            "G1-section-case",
            line_sub(
                legs, "holds for any target.", "holds for any target, and IMPORT ANYWAY REMAINS."
            ),
            "[import-verb]",
            None,
        ),
    ]


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
        (
            "M16-pointer",
            ctx_sub(
                "14",
                "Export… in its three places, never gated;",
                "Export… in its three places, gated per role;",
            ),
            "[pointer-14]",
        ),
    ]


def frame_family(spec: str, ctx: Ctx) -> list[str]:
    """The per-frame gates alone (the frames, the two tables, the boards)."""
    tables = [table_gate(spec, h, r) for h, r in (("### 4.2 ", False), ("### 4.3 ", True))]
    known = known_copy(ctx.facts)
    frames = frame_gates(spec, ctx.facts, None, known)
    return frames + [x for x in tables if x] + board_gates(spec)[0]


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
        "ruled questions and conditions, each row whole; §0's boards, every cell; the FRAME "
        "ladder over every cell of every frame row (the expected clauses whole, the Producer and "
        "the free clauses through the vocabulary ladder, their labels, the Producer and the copy "
        "keys the tool's); the TABLE ladder over §4.2 and §4.3; the LINE ladder over every other "
        "sentence and cell; the tables held whole; §7's keyboard model; §1.3's states; the deck "
        "whole; the cites; the commit ids; the `14` pointer lines byte for byte; the written "
        "sections; every marker printed, parsed, re-derived and counted"
    )
    out.append("\n## 5. Gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out.append("\n## 6. Counts: " + json.dumps(numbers_, ensure_ascii=False))
    return out


def main(argv: list[str]) -> int:
    spec = SPEC.read_text(encoding="utf-8")
    if "--repin-security" in argv:
        print(render_pins(spec, SEC_BEARING_RE))
        return 0
    if "--repin-status" in argv:
        print(render_pins(spec, STATUS_BEARING_RE, True))
        return 0
    ctx = Ctx()
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


# --- the default-deny pins: `--repin-security` / `--repin-status` print them; a reviewer reads ---
# --- them here, and `--check` never re-pins ------------------------------------------------------
SEC_PIN_TXT = r"""
§ E15-D09 — SCR-026 workspace import / exp
@ prose
  Export… from SCR-025 and the workspace menus, the pre-export preview with what is included
  and, first-class, what is excluded, the file name with its format version, the completion
@ prose
  sharing beyond the file
@ prose
  E15-D08 (#4503, Export… in SCR-025's Share section) is PENDING: named only, never pinned
  and never cited by line
@ prose
  every `file:line` cite in this file is at it and the tool re-checks each (a moved line is
  a WARN
@ prose
  Import: `scalping.json`, a colleague's export from a build that knows two more panel
  kinds, whose Positions pane carries an account filter that points at an account of the
  colleague's (its label stays in the tool
@ prose
  the densities.** The ticket's Included list names densities
@ prose
  density is global or per panel, `D02:507`), so a C-row records the densities, and the
  Included list names only what the bundle holds (BQ-2 RULED).
@ prose
  the Included sentence is E15-D02's (`D02:511`), in which each panel's interval is one of
  "each panel's settings", so the intervals take no clause of their own, and the import's
  table names each panel's interval in its Item cell (§4.2
§ Acceptance-criteria trace (#363)
@ row AC-1 · col 2
  "The user learns what travels before exporting": the included and the excluded lists, the
  excluded one naming accounts, environment binding and credentials
@ row AC-1 · col 3
  the Excluded sentence byte for byte (BQ-2 RULED)
@ row AC-2 · col 2
  "A newer-version file is refused, not partially applied": both versions named, no option
  that applies part of the file
@ row AC-4 · col 2
  "Account references are remapped and disclosed": shown dropped, the report in plain
  language, naming no account the importer cannot see
@ row DL-2 · col 2
  The pre-export preview's included list
@ row DL-3 · col 2
  The excluded list, first-class
@ row DL-17 · col 2
  The untrusted-string rule
@ row DL-18 · col 2
  the server re-checks
@ row DoD-3 · col 2
  no partial-apply path
@ row DoD-7 · col 2
  The untrusted-string rule and the limits stated
§ The questions (BQ-1…BQ-16) — RULED by th
@ row BQ-1 · col 3
  the PR says `Refs #363` and `Partial:`, never a closing keyword
@ row BQ-2 · col 3
  the Excluded list, first-class and drawn as a list, in AC 1's words: "Never included:
  credentials — API keys or tokens; accounts, trade-group and user ids; environment binding
  (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row BQ-2 · col 3
  the Included list names only what `WorkspaceBundle` holds (`22:21209–21230`)
@ row BQ-2 · col 3
  the import's trust note is `D02:513` verbatim: "A workspace file never carries credentials
  or account bindings. Importing creates a new workspace and changes nothing else."
@ row BQ-2 · col 3
  the sharing claim in `22:12679`'s description is never written anywhere (its G-row names
  it without repeating it)
@ row BQ-3 · col 2
  account-scoped elements on import
@ row BQ-3 · col 3
  dropped and listed, never remapped, and no account the importer cannot see is ever named
  in the preview, the report or a reason: its row reads "workspaces never carry account
  bindings" (§4.2 row 3)
@ row BQ-3 · col 3
  the word "Remap" is kept for the one true remap, the Positions pane that shows your own
  accounts (§4.2 row 4)
@ row BQ-5 · col 3
  nothing is created before Import as new workspace and nothing kept after a refusal
@ row BQ-7 · col 3
  SCR-025's Share section (E15-D08, PENDING by name), the tab's `[⋯]` (`D03:384`) and the
  rail's workspace menu (`D02:511`)
@ row BQ-7 · col 3
  and one CMP-043 `md` dialog with the Included and Excluded lists built from the fetched
  bundle
@ row BQ-7 · col 3
  Export… is a read (`22:12676`), never gated (a read): T1 for every session, view-as
  included
@ row BQ-8 · col 3
  a dismissed save sheet keeps the preview (`SCR-025/export-cancelled`)
@ row BQ-11 · col 3
  six CMP-027 `inline` frames, `live="polite"`, the dialog kept open with Choose another
  file focused beside its Cancel
@ row Condition 1 · col 2
  every string from the file is untrusted
@ row Condition 1 · col 3
  every string from the file is untrusted: text only, never markup and never a link, capped
  with the cap stated, the malformed reason naming the key in mono, truncated
@ row Condition 1 · col 3
  the report echoes no raw file content beyond those capped names
@ row Condition 1 · col 3
  the server re-checks size, depth, nodes, schema and version (E15-S07) and
  `SCR-026/validating` says so
@ row Condition 1 · col 3
  a refused parse is never a partial import
@ row Condition 1 · col 3
  nothing is created before Import as new workspace and nothing kept after a refusal
@ row Condition 3 · col 3
  the tool reads every frame table row by row, every other table and the prose, with
  case-insensitive vocabulary lists (the gated-exit words, the environment words, the
  sharing claim, the markup and link words) against whole clauses, never first words
@ row Condition 4 · col 3
  Cancel, Esc, ×, Close and Choose another file are never gated on any frame, view-as and
  the Viewer's included
@ prose
  Cancel, `Esc`, ×, Close and Choose another file, on every frame and for every session,
  view-as and the Viewer's included.
§ §1.1
@ row US-LAY-007: the export carries no secret · col 1
  US-LAY-007: the export carries no secrets and no account bindings
@ row US-LAY-007: the export carries no secret · col 1
  any account-scoped element is dropped with a clear report
@ row US-LAY-007: the export carries no secret · col 1
  a file is schema-validated on import and never embeds keys, tokens or account ids
@ row US-LAY-007: the export carries no secret · col 3
  the Excluded list and the trust note (BQ-2 RULED)
@ row E15-D01's locked list, item (8): exports · col 1
  E15-D01's locked list, item (8): exports carry no credentials or account bindings
@ row E15-D01's locked list, item (8): exports · col 3
  the Excluded list (§2.3)
@ row D-30: an import always creates a new wor · col 1
  D-30: an import always creates a new workspace, after a preview that lists what is
  included and dropped and says the file carries no credentials and no account bindings
@ row E15-D02 §5.11: the export preview and th · col 3
  E15-D02's own Excluded sentence is extended and never shown (D09-C5)
@ row `22`: `exportWorkspace` is a read (`work · col 3
  the Included list counted from the bundle (§2.3)
@ row `PaneConfig` never holds credentials, ac · col 1
  `PaneConfig` never holds credentials, account ids or user ids
@ row `PaneConfig` never holds credentials, ac · col 3
  the Excluded list holds for every file the dialog saves (§2.3)
@ row `PaneConfig` never holds credentials, ac · col 3
  the account setting's Drop row (§4.2)
@ row E15-S07: the check order (size, the pars · col 1
  export requests logged without file contents
@ row E15-D06 D-9: a layout never stores an ac · col 1
  E15-D06 D-9: a layout never stores an account
@ row E15-D06 D-9: a layout never stores an ac · col 3
  the account setting's Drop row (BQ-3 RULED, §4.4)
§ §1.2
@ row Exfiltration: the file leaves the machin · col 2
  no field of `WorkspaceBundle` holds a credential, an account, a trade-group or user id, an
  environment, an alert or rule binding, P&L, a position or an order (`22:21209–21230`
@ row Exfiltration: the file leaves the machin · col 2
  the preview names what travels and, first-class, the Excluded list, so a mistake in the
  build is visible rather than hidden
@ row Injection through content: every string  · col 1
  Injection through content: every string from the file is untrusted
@ row Injection through content: every string  · col 2
  text only: never markup, never a link, never interpreted (SR-127, `04:965`
@ row Injection through content: every string  · col 2
  capped, an ellipsis past the cap, and nothing past a cap rendered, announced, copied or
  logged
@ row Privilege confusion: a file that would g · col 2
  account-scoped elements are dropped and listed, never remapped, and no account the
  importer cannot see is named
@ prose
  **The server re-checks (Condition 1).** No guard in the browser replaces the server's own
  validation: the server re-checks size, depth, nodes, schema and version when the file is
  imported (E15-S07), refuses unknown fields on its write paths, fail closed, while the
  client ignores them (C-6.3
@ prose
  C-2.12), and the same holds for every later write of the workspace, `PUT
  /workspaces/{workspaceId}` included (the ticket's Security notes, `BL:266`).
@ prose
  a refusal at any step keeps nothing of the file
@ prose
  and the import is one request that creates everything or nothing (D09-G1), so no frame of
  this spec shows a partial import.
@ prose
  owner approval pending (#2701)).** Two sentences carry the trust claims, each gated byte
  for byte wherever it shows: the Excluded list on the export and the trust note on the
  import (§9 holds both).
@ prose
  the sharing claim of `22:12679`'s description is written nowhere in this spec (D09-G11).
§ §1.3
@ prose
  a failure after the send has no partial frame, because the import is never partial
  (D09-G1), and its frame is the server's refusal, or, when no answer came, the frame that
  says the import could not be confirmed.
@ row 3 · col 2
  export: the preview with the Included and Excluded lists
@ row 13 · col 2
  import: an account reference in the preview
§ §1.4
@ row D09-D1 · col 2
  the Included and Excluded lists stand side by side in equal columns, so the Excluded list
  never sits below a long Included list
@ row D09-D1 · col 2
  at 200 % they stack, the Included list first
@ row D09-D2 · col 2
  before the preview the client reads the fetched bundle with the import's own check: data
  the lists cannot show, or a setting the import would drop as account-scoped, fails the
  export closed
@ row D09-D2 · col 2
  a limit an import would refuse keeps Download file and adds a warning line
@ row D09-D5 · col 2
  the slug rule in full, the empty name and the Windows device names included (D09-G14)
@ row D09-D17 · col 2
  Import as new workspace keeps its label while it is busy, and "Still importing…" shows
  after CMP-001's slow-path delay
@ row D09-D34 · col 2
  a drop that carries no file, or a drop outside the zone, is ignored: nothing is read or
  fetched, no address is followed and the page keeps its state
@ row D09-D35 · col 2
  a pane setting the registry does not list for its kind, and that is not account-scoped, is
  a Drop row of its own, Type "setting", Reason "not available in this version"
§ §2
@ prose
  It sits in three places and opens one dialog (BQ-7 RULED, §2.2): a CMP-043
  `role="dialog"`, `size="md"`, at most 560 <!-- audit:contract.dialog_md_px=560 --> px wide
  (`15:466`), which calls `exportWorkspace` once, counts the Included list from the bundle
  it gets and saves that same bundle, so what the owner checks is what the file holds
  (`D02:511`
@ prose
  Beside the Included list stands the Excluded list, first-class (§2.3).
@ prose
  The trust copy is BQ-2's ruled text, owner approval pending (#2701), and the sharing claim
  in `exportWorkspace`'s description is written nowhere in this spec (D09-G11).
§ §2.1
@ row `SCR-025/export-entry` · col 2
  Export… opened from SCR-025's Share section (E15-D08, PENDING by name), the tab's `[⋯]`
  (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored workspace
@ row `SCR-025/export-entry` · col 3
  access: Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace menu
@ row `SCR-025/export-entry` · col 3
  Components: a CMP-041 item of `kind` action in the tab's `[⋯]` and in the rail's workspace
  menu, with no glyph and no shortcut · in SCR-025's Share section a CMP-001 `secondary`
  button, which E15-D08 draws (PENDING, by name)
@ row `SCR-025/export-preview` · col 3
  included: a CMP-036 list built from the fetched bundle, one item per clause
@ row `SCR-025/export-preview` · col 3
  excluded: a CMP-036 list, first-class, one item per clause
@ row `SCR-025/export-preview` · col 3
  "Never included: credentials — API keys or tokens; accounts, trade-group and user ids;
  environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row `SCR-025/export-preview` · col 3
  Components: CMP-043 `md` · two CMP-036 KeyValueRows in one `dl`, each with its lead-in as
  the term and its list as the value, a `ul` with one `li` per clause that keeps the
  clause's own punctuation · the caveat a plain line · CMP-001 `secondary` and `primary` ·
  CMP-028 `info` for unsaved changes and `warning` for an import limit, each only when it
  applies, `live="off"` (§2.3)
@ row `SCR-025/export-preview` · col 3
  Layout (comfortable / compact): the two lists side by side in equal columns
  `space.inset.xl` 24 <!-- audit:redline.space.inset.xl=24 --> px apart, both from the top
  of the body, so the Excluded list stands beside the Included list however long that one
  runs · each item at least `size.row.height` tall, 32 <!--
  audit:redline.size.control.comfortable=32 --> px or 24 <!--
  audit:redline.size.row.height=24 --> px · the caveat full width, 12 <!--
  audit:redline.space.stack.md=12 --> px under the columns · past 80 % of the viewport the
  body scrolls between the header and the footer (`15:466–468`) · the card's chrome as on
  `SCR-025/export-preparing`
@ row `SCR-025/export-preview` · col 5
  `e15.export.title` · `e15.export.close` · `e15.export.unsaved` · `e15.export.included` ·
  `e15.export.excluded` · `e15.export.caveat` · `e15.export.over_limit` ·
  `e15.export.cancel` · `e15.export.download`
@ row `SCR-025/export-done` · col 3
  excluded: a CMP-036 list, first-class, one item per clause
@ row `SCR-025/export-done` · col 3
  "Never included: credentials — API keys or tokens; accounts, trade-group and user ids;
  environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row `SCR-025/export-done` · col 3
  Components: CMP-028 `success`, its title line alone, at the top of the body · the Excluded
  CMP-036 row, full width, beneath it · the Included list, the caveat and the conditional
  lines leave · CMP-001 `primary` Close
@ row `SCR-025/export-done` · col 3
  Layout (comfortable / compact): the success line full width with its `border.thick` 2 <!--
  audit:redline.border.thick=2 --> px start edge and `radius.card` 6 <!--
  audit:redline.radius.card=6 --> px, the Excluded row 12 <!--
  audit:redline.space.stack.md=12 --> px under it, the footer one button
  `size.control.height` tall, the chrome as on `SCR-025/export-preparing`
@ row `SCR-025/export-done` · col 5
  `e15.export.title` · `e15.export.close` · `e15.export.done` · `e15.export.excluded` ·
  `e15.export.close_button`
@ row `SCR-025/export-cancelled` · col 3
  included: a CMP-036 list built from the fetched bundle, one item per clause
@ row `SCR-025/export-cancelled` · col 3
  excluded: a CMP-036 list, first-class, one item per clause
@ row `SCR-025/export-cancelled` · col 3
  "Never included: credentials — API keys or tokens; accounts, trade-group and user ids;
  environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row `SCR-025/export-cancelled` · col 5
  `e15.export.title` · `e15.export.close` · `e15.export.unsaved` · `e15.export.included` ·
  `e15.export.excluded` · `e15.export.caveat` · `e15.export.over_limit` ·
  `e15.export.cancel` · `e15.export.download`
@ row `SCR-025/export-reflow-200` · col 3
  reflow: at 200 % on 1280 × 800 the dialog fills the viewport less 16 px a side, keeps its
  title and footer and scrolls its body, both lists in one column
@ row `SCR-025/export-reflow-200` · col 3
  Layout: CMP-043's reflow state (`15:466–468`) · the two lists stack, the Included list
  first, each full width, and the caveat and the conditional lines follow in order · the
  footer may wrap to two lines, Cancel first · nothing is clipped (`05:131`)
§ §2.2
@ row SCR-025's Share section · col 1
  SCR-025's Share section
@ prose
  SCR-025's Share section is E15-D02 §5.10's, its hi-fi E15-D08's (PENDING)
@ prose
  **Availability, not T2.** Where the workspace has no stored copy, the viewer's unsaved
  default (V-4, `D03:583`) and a workspace never stored (`D03:384`), there is nothing to
  read, so the item keeps its place and its label, the label in `color.text.tertiary` and
  the item `aria-disabled="true"`, with "This workspace isn't saved." as its second line
  (`ws.export.unstored`, `D03:625`): no lock glyph, no CMP-079 and no registered reason key,
  the availability form of E15-D03 §1.4 (`D03:118–120`
§ §2.3
@ heading
  2.3 The Included and Excluded lists: anatomy and redlines
@ prose
  owner approval pending (#2701)).** The Included list is counted from the fetched bundle,
  so it names only what `WorkspaceBundle` holds (`22:21209–21230`): no density, which no
  workspace stores (the third deviation).
@ prose
  The Excluded list is BQ-2's sentence, byte for byte, drawn as a list of its five clauses
  and first-class: the same type, weight and column width as the Included list, never a
  footnote, a hint or a tooltip.
@ prose
  a pane's settings never hold credentials, account ids or user ids, `22:19838`, `21:5069`
@ prose
  credentials never leave the secrets module, C-2.7), the server builds the bundle by
  copying fields in by name, never by spreading a row (E15-S07, `BL:1136`), and the client
  saves only a bundle that passes the check below.
@ prose
  the sharing claim of `exportWorkspace`'s description is never written (D09-G11).
@ row Included item · col 1
  Included item
@ prose
  the items keep the sentence's order and the last one takes its full stop.
@ prose
  the Included list leaves both out because they are facts about the file, not about the
  workspace.
@ prose
  Every name in the lists is rendered as text, never as markup (SR-127, `04:965`).
@ prose
  and because the file is the bytes as fetched (§2.4), the client declines to save a bundle
  that carries one, or a pane setting the import would drop as account-scoped (§4.2's third
  row): `SCR-025/export-failed` with "Couldn't prepare the file: it holds something this
  preview can't show. Nothing was exported." `WorkspaceBundle` and `ChartTemplateInput` are
  not closed today (D09-G4)
@ prose
  - A limit an import would refuse (the file's size, its nesting or its count of values, or
  its presets: an export carries every live preset, while an import takes at most 200 <!--
  audit:contract.presets_max=200 --> of them, `22:21226–21230`) keeps Download file and adds
  a CMP-028 `warning` line under the caveat: the import's own first sentence, then "You can
  save it, but this app won't import it." For a file with 240 presets: "This file has 240
  indicator presets; a file may carry at most 200. You can save it, but this app won't
  import it." The limits are E15-S07's until the contract carries them (D09-G5).
@ row The two lists · col 3
  in the reflow state one column, the Included list first
@ row Lead-in · col 2
  each CMP-036's `label`: "The file includes:", and the Excluded sentence's opening words up
  to its colon
@ row Completion line (the done step) · col 3
  full width at the top of the body, the Excluded row `space.stack.md` under it
@ prose
  and, in light, the failure glyph's `color.status.danger.strong` and the import-limit
  glyph's `color.status.warning.strong` share one greyscale value (§8's greyscale rows), so
  colour never tells them apart: the two never show together, and each is read by its words.
@ prose
  Under `forced-colors: active` the card keeps its `border.hairline` 1 <!--
  audit:redline.border.hairline=1 --> px edge and every callout keeps its glyph and its
  words (E05-D02 slice 4, conventions 38).
§ §2.4
@ prose
  5. the version keeps `0`–`9`, `a`–`z` and `.` only, by the same rule (D09-G2: the contract
  does not yet say what the string holds).
@ prose
  The bytes are the response body as fetched, the very bytes the lists were counted from,
  never re-serialised and never added to: plain JSON, which E15-S07 keeps so a person can
  read the file before sending it (`BL:1136`).
@ prose
  They are written whole or not at all (to a temporary file, then renamed), so a failed
  write leaves no partial file and turns the dialog to `SCR-025/export-failed` with
  "Couldn't save the file. Nothing was exported." (PROPOSED), whose Try again opens the
  sheet again.
@ prose
  **The completion step (BQ-8 RULED).** When the write ends, the body changes in place
  (`SCR-025/export-done`): a CMP-028 `success` line, "Exported Scalping as
  scalping.cv-workspace-v1.json.", the file name in `type.num.sm` and selectable, then the
  Excluded list, unchanged, so the owner sees what the file leaves out as they send it on.
@ prose
  The Included list, the caveat and the conditional lines leave
§ §2.5
@ row entry (`SCR-025/export-entry`) · col 2
  a menu opens on a stored workspace, or SCR-025 shows its Share section
@ row done (`SCR-025/export-done`) · col 3
  the completion line over the Excluded list
@ prose
  **Exits.** Cancel, `Esc`, × and Close end the export dialog on each of its frames and for
  every session, view-as included, and `Esc` closes the menu that holds Export… (§7 states
  the rule once).
§ §3
@ prose
  Its steps share one chrome
@ prose
  Nothing is created before Import as new workspace, and nothing of the file is kept after a
  Cancel or a refusal (Condition 1
§ §3.1
@ row `SCR-026/pick` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/drag-over` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/drag-over-rejected` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/validating` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/validating` · col 3
  server: the server re-checks size, depth, nodes, schema and version when the file is
  imported (E15-S07)
@ row `SCR-026/validating` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/creating` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/creating` · col 3
  busy: Import as new workspace keeps its label with `aria-busy="true"`
@ row `SCR-026/creating` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/import-leg-lost` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/import-leg-lost` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/reflow-200` · col 3
  reflow: at 200 % on 1280 × 800 the dialog fills the viewport less 16 px a side, keeps its
  title and footer, scrolls its body and reads the table one row element per record
  (`15:529`)
§ §3.2
@ prose
  The route is a way in of its own: a link, a restore or Back opens the dialog for any
  session, and where §6's legs gate Import…, the dialog's Import as new workspace takes §6's
  form in place from the start, as on `SCR-026/import-leg-lost`, while Choose file…, the
  checks and the preview work as for every session.
§ §3.3
@ prose
  text, an address, an HTML fragment, an image dragged from a page
§ §3.4
@ heading
  3.4 The five check steps, the validating state and the server's re-check
@ prose
  The first step that fails ends the check: its rejection takes the progress's place, the
  later steps never run, and nothing of the file is kept (§5).
@ row 5 · col 5
  a setting the registry marks account-scoped is a Drop row, and so is a setting it does not
  list for its kind, a newer build's option (D09-D35)
@ prose
  A show-delay of 150 ms (BQ-9's default, ruled as proposed) keeps a file that validates
  within the 500 <!-- audit:contract.parse_ms=500 --> ms of `14:633` from flashing the bar
@ prose
  **What the check in the browser is, and is not (Condition 1).** It is a courtesy: it tells
  the user early and keeps a hostile file away from the page, and it never replaces the
  server's own check.
@ prose
  The server re-checks size, depth, nodes, schema and version when the file is imported
  (E15-S07, `BL:1136`)
@ prose
  A file the server refuses at the send is `SCR-026/refused-server` (§5.1) and never a
  partial import, because the import is one request that creates everything or nothing
  (D09-G1, §12).
@ prose
  The worker reads the file as plain data and builds the preview only from the fields
  `WorkspaceBundle` names, so an unknown key, `__proto__` and `constructor` included, is
  never read into the app: the client ignores it, as C-6.3 asks of every client, and the
  server refuses it on its write path, fail closed (C-6.3
@ prose
  **Nothing is kept.** Cancel during the check stops the worker and releases the file and
  everything parsed from it
@ prose
  Nothing from the file is stored, sent or logged before Import as new workspace: workspace
  and layout content is never logged (`21:5069`), and E15-S07 logs its export requests
  without file contents (`BL:1136`).
§ §3.5
@ prose
  done in the client as `createWorkspace` and then `createLayout` per layout, the import
  would not be atomic, `FL:171`, which is why no frame here shows a partial state).
@ prose
  **Creating (`SCR-026/creating`).** Import as new workspace keeps its label, with
  `aria-busy="true"` and CMP-001's spinner after the label, its width fixed (`15:48`
@ prose
  CMP-001's buy and sell keep their label the same way, PROPOSED for this primary so the
  effect stays named while it runs).
@ row creating · col 2
  Import as new workspace busy, its label kept
§ §4.1
@ row `SCR-026/preview` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/preview` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/preview` · col 5
  `e15.import.caption` · `e15.import.col.item` · `e15.import.col.type` ·
  `e15.import.col.action` · `e15.import.col.reason` · `e15.import.action.add` ·
  `e15.import.action.drop` · `e15.import.action.remap` · `e15.import.reason.unknown_kind` ·
  `e15.import.reason.account` · `e15.import.reason.remap` · `e15.import.clash` ·
  `e15.import.cancel` · `e15.import.confirm`
@ row `SCR-026/preview-migrated` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/preview-migrated` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/preview-over-budget` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/preview-over-budget` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/budget-confirm` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/report` · col 3
  never markup, never a link, never interpreted
§ §4.2
@ row Account filter on Positions · col 1
  Account filter on Positions
@ row Account filter on Positions · col 4
  workspaces never carry account bindings
@ row Positions · col 4
  shows your own accounts
§ §4.3
@ prose
  The report repeats §4.2 row for row, the unknown kinds by stored name (AC 3) and the
  account row as dropped (AC 4):
@ row Account filter on Positions · col 1
  Account filter on Positions
@ row Account filter on Positions · col 4
  workspaces never carry account bindings
@ row Positions · col 4
  shows your own accounts
§ §4.4
@ prose
  Remap takes the info hue rather than the warning one because in light
  `color.status.danger.strong` and `color.status.warning.strong` resolve to the same amber,
  so Drop and Remap would share a colour
@ prose
  The unknown kinds keep their stored names and the ticket's reason, "not available in this
  version" (AC 3)
@ prose
  A pane setting the registry does not list for its kind, a newer build's option that is not
  account-scoped, is a Drop row too, its Item the setting and its pane, Type "setting",
  Reason "not available in this version" (D09-D35).
@ prose
  **Account-scoped elements (BQ-3 RULED
@ prose
  AC 4).** An account filter on a pane is dropped and listed, never remapped: its row reads
  Account filter on Positions · setting · Drop · "workspaces never carry account bindings"
  (`D02:516`
@ prose
  `11:2868`), and nothing in the preview, the report, the copied text, an announcement or an
  event names the account it pointed at, or any account the importer cannot see.
@ prose
  The one Remap is the Positions pane itself, which shows your own accounts once it is
  imported
@ prose
  its Reason names no account at all, because what changes is the pane's scope and not a
  stored binding.
@ prose
  the server drops such a setting again at import (`BL:1136`), and until `22` says how
  (D09-G3), a strict server may refuse the whole file instead, which is
  `SCR-026/refused-server` (§5.1) and never a partial import.
@ prose
  `14:628–629`'s "remap to the user's default account" gets a PROPOSED A-row (§11).
@ prose
  DL-17).** Every string the table takes from the file (kind names, layout names, symbols,
  intervals, drawing labels) is a text node and nothing else: never markup, never a link,
  never interpreted (SR-127, `04:965`
@ prose
  Within its cap, a value wider than its column ends in an ellipsis on screen and keeps the
  whole capped value in the cell's text, for a screen reader and for Copy report.
@ row preview-over-budget · col 3
  the caption, budget sentence included, is spoken once
§ §4.5
@ prose
  the account filter is listed as dropped
@ prose
  and each says so in plain words that name no account ("workspaces never carry account
  bindings", "shows your own accounts"
§ §5
@ prose
  never a lock, never a partial import** (BQ-4, BQ-5, BQ-11 RULED
@ prose
  Three end at the send: the workspace limit, the server's own re-check, and a send whose
  answer never came (§1.3, states 15–21, 23, 24 and 27).
@ prose
  Each but the unanswered send says "Nothing was imported." and it is true: no workspace,
  layout or pane exists, and nothing of the file is kept (§5.5)
§ §5.1
@ row `SCR-026/rejected-version-newer` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/rejected-version-newer` · col 3
  versions: the two numbers are whole numbers parsed from the file and read from the app, in
  `type.num.sm`, never the file's raw text (§5.3)
@ row `SCR-026/rejected-version-older` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/rejected-malformed` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/rejected-malformed` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/rejected-oversized` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/rejected-wrong-type` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/rejected-wrong-type` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/rejected-nodes` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/refused-limit` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/refused-server` · col 2
  the server's own re-check refused the file at the send (`422 validation_failed`)
@ row `SCR-026/refused-server` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `SCR-026/refused-server` · col 3
  never markup, never a link, never interpreted
@ row `SCR-026/refused-unconfirmed` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
§ §5.2
@ prose
  Choose another file and Choose file… front the same native input: the footer's button is
  the constructive primary that focus lands on, so `Enter` reopens the picker at once, and
  the body's button keeps its drop words for a pointer.
@ row A key or a file name inside the message · col 2
  a text node of its own, never a link (§5.5)
@ row the server's re-check, at the send · col 1
  the server's re-check, at the send
§ §5.3
@ prose
  The numbers printed are the parsed whole numbers and the app's own constant, so the file's
  raw `schema_version` text never reaches the screen (§5.5).
§ §5.4
@ row 5 registry · col 3
  settings that never hold account ids (`22:19838`)
@ row 5 registry · col 4
  never a rejection: an unknown kind or an account-scoped setting is a Drop row (§4.2)
@ prose
  An unknown key, the prototype-shaped keys of E15-S07's fuzz corpus included (`BL:1136`),
  is ignored and never reaches an object
§ §5.5
@ heading
  5.5 Untrusted strings, nothing kept, and the refusals at the send
@ prose
  C-12.10), never a link and never a format string, so a `{` in a key stays a `{`.
@ prose
  No Markdown, HTML or link is ever rendered from it, and nothing in it that looks like an
  address is made live (the ticket's Security notes, hazard 2
@ prose
  No contract bounds either string, so the cap also holds in the accessible name, which
  carries the same shortened text with the word "(shortened)" after it, PROPOSED: nothing
  past a cap is ever rendered, announced, copied or logged.
@ prose
  **Never logged.** `layout.import_rejected{reason}` carries the reason word only, never a
  key, a name, a size or a line
@ prose
  workspace and layout content is never logged (`21:5069`), and E15-S07 logs its export
  requests without file contents (`BL:1136`).
@ prose
  **Nothing kept.** When a refusal shows, the worker's text and document and the file's
  handle are dropped: nothing reaches the workspace store, the browser's storage, a cache or
  a log, and Choose another file starts from nothing (BQ-5 RULED).
@ prose
  `422 validation_failed` when the server's own re-check refuses what the browser passed
  (`22:19626`): "Nothing was imported." then "The server didn't accept this file: `{key}`
  isn't valid.", the key the first field path of the problem's `errors[]`, cleaned and
  capped as above
@ prose
  takes the same frame with the PROPOSED `e15.import.refused.store`, "The workspace store
  didn't answer. Choose the file again in a moment.", in place of the key's sentence:
  nothing of the file was kept, so the way on is to choose it again (§9
@ prose
  **Never a partial import.** The send is one call that creates the workspace with all its
  layouts or creates nothing (D09-G1
@ prose
  The browser-side sequence of `createWorkspace` then `createLayout` for each layout
  (`FL:171`) is not built: a failure between two calls would leave a workspace the user
  never chose, the partial import the ticket forbids (`11:2871`
§ §6
@ prose
  A workspace write is scope `self`, so the account and environment legs never apply.
@ prose
  `D02:641`): A T2 control keeps its native role and its full label
@ prose
  CMP-079 RbacGate wraps it and its reason node is in the DOM at mount, linked by
  `aria-describedby`.
@ prose
  no reload, no focus move, the checked file and its preview kept.
§ §6.1
@ row Import as new workspace, the dialog's pr · col 5
  reached by a link only (§3.2): T2 `rbac.permission` in place
@ row Import as new workspace, the dialog's pr · col 6
  reached by a link only: T2 `rbac.view_as` in place
@ row Export… in SCR-025's Share section, the  · col 1
  Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace menu
@ row Choose file…, a drop, the five checks, t · col 5
  T1, reached by a link only
@ row Choose file…, a drop, the five checks, t · col 6
  T1, reached by a link only
@ prose
  - **Export…, a read.** No leg gates it: T1 for every session on a stored workspace,
  view-as included, its preview, its Download file and its completion alike (`22:12676`
@ prose
  - **Busy.** "Preparing the file…", "Checking scalping.json… step 3 of 5" and Import as new
  workspace in flight are `aria-busy` with their labels kept, focusable, no lock and no
  reason (`SCR-025/export-preparing`, `SCR-026/validating`, `SCR-026/creating`).
@ prose
  - **The exits.** Cancel, `Esc`, ×, Close and Choose another file are T1 for every session,
  view-as and the Viewer's included (§7).
§ §7
@ row the menus: `SCR-025/export-entry`, `SCR- · col 3
  arrows, not `Tab`: `↑` and `↓` reach every item, the T2 item and the unavailable one
  included
@ row the menus: `SCR-025/export-entry`, `SCR- · col 6
  in SCR-025's Share section Export… is a button and keeps focus
@ row Import as new workspace or Import anyway · col 3
  nothing at the press: the button keeps its name with `aria-busy` (`15:48–57`)
@ row the check runs, `SCR-026/validating` · col 2
  `progressbar` · named by "Checking scalping.json…" · its value the share of the five steps
  done, its text "Checking scalping.json… step 3 of 5"
@ row the export dialog opens on `SCR-025/expo · col 2
  the Included and the Excluded list are lists read in browse mode, one item per clause
@ prose
  At 200 % zoom on the 1280 × 800 frame each dialog fills the viewport less its margins,
  keeps its title row and its footer and scrolls its body (`SCR-025/export-reflow-200`,
  `SCR-026/reflow-200`)
@ prose
  Nothing is clipped: a message wraps, and a key or a file name keeps its cap and its
  ellipsis (§5.5).
§ §8
@ prose
  **The token map and the redlines** (tokens by name, never a raw value
@ prose
  Under `forced-colors: active` each dialog keeps its edge as a real border, which forced
  colours paint CanvasText
@ prose
  the scrim keeps its black at its opacity (`forced-color-adjust: none`)
§ §9
@ prose
  each is text only, cleaned (§5.5) and capped (the Fixture paragraph), never rendered as
  markup or a link and never read as a format string (Condition 1).
@ row `e15.export.menu_item` · col 2
  the item in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace menu
  (`SCR-025/export-entry`, `SCR-025/export-unavailable`)
@ row `e15.export.included` · col 1
  `e15.export.included`
@ row `e15.export.included` · col 2
  the Included list, one item per clause, built from the fetched bundle
@ row `e15.export.excluded` · col 1
  `e15.export.excluded`
@ row `e15.export.excluded` · col 2
  the Excluded list, first-class, one item per clause (`SCR-025/export-preview`,
  `SCR-025/export-done`)
@ row `e15.export.excluded` · col 3
  "Never included: credentials — API keys or tokens; accounts, trade-group and user ids;
  environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row `e15.import.trust` · col 3
  "A workspace file never carries credentials or account bindings. Importing creates a new
  workspace and changes nothing else."
@ row `e15.import.action.remap` · col 2
  the Action word after the `merge` glyph, kept for the one true remap (§4.2 row 4)
@ row `e15.import.reason.account` · col 1
  `e15.import.reason.account`
@ row `e15.import.reason.account` · col 2
  the Reason of an account-scoped setting's Drop row
@ row `e15.import.reason.account` · col 3
  "workspaces never carry account bindings"
@ row `e15.import.reason.remap` · col 3
  "shows your own accounts"
@ row `e15.import.refused.server` · col 2
  its second sentence when the server's re-check refuses the file (`SCR-026/refused-server`)
§ §10
@ prose
  Text inside a double-backtick span is the catalogue's own source, its single backticks
  included
@ row D09-A1 · col 4
  `**Purpose**: CSV/JSON import (journal import, rule import/export, workspace import).` ·
  ``- **Props**: `accept` · `onFiles` · `multiple?` · `label` (the visible text of the real
  `<button>` that fronts the native input, kept `hidden` and opened by the button's click,
  e.g.
@ row D09-A3 · col 4
  a dashed edge is kept for estimated and absent data.)``
@ row D09-A11 · col 5
  the export's Included and Excluded lists (`SCR-025/export-preview`)
@ prose
  **No A-row, and why.** CMP-001 Button: its `loading` keeps the label with `aria-busy`, and
  its T2 is E09-D09's (`15:48–57`).
@ prose
  CMP-068 CopyableCodeBlock: unused, because no frame shows the file's text and Condition 1
  forbids echoing it.
§ §11
@ row D09-A12 · col 3
  "(panels added, symbols referenced, accounts remapped)"
@ row D09-A12 · col 4
  "(Choose file… or a drop; five checks in a worker; then a table of what is added, dropped
  and remapped — unknown panel kinds and account-scoped settings dropped and listed, never
  remapped — before Import as new workspace creates a new workspace)"
@ row D09-A13 · col 3
  "This layout was exported by v2 and can't be imported into v1." · "inaccessible account
  references remap to the user's default account"
@ row D09-A13 · col 4
  "This file was exported by format version 2 and can't be imported into format version 1.
  Nothing was imported. Export it again from a version 1 app, or update this app." ·
  "account-scoped settings are dropped and listed, never remapped, and no account the
  importer cannot see is named; an older format version this app still reads is migrated
  forward and said so"
@ row D09-A17 · col 4
  "version-mismatch state (a newer format version refused with both versions and a way on,
  nothing imported, no partial apply; an older one this app still reads migrated and said
  so) [ ] account-scoped elements dropped and listed in the preview and the report, naming
  no account the importer cannot see"
@ prose
  Two do not: SCR-089 accepts or skips each rule on its own (`14:1993`) where a workspace is
  whole or nothing, and a rule bundle's version and account references follow E36's
  contract, not `WorkspaceBundle`'s.
§ §12
@ row D09-G1 · col 2
  and an import built in the client from `createWorkspace` and then `createLayout` for each
  layout is not atomic (`FL:171`), the partial import the ticket forbids (`11:2871`)
@ row D09-G3 · col 2
  Account-scoped elements: no bundle schema has an account field and `PaneConfig` forbids
  account ids (`22:19838`), so a strict server refuses a file that carries one whole (C-6.3
@ row D09-G3 · col 2
  `14:629`'s "the user's default account" names nothing a workspace has
@ row D09-G3 · col 3
  the contract's rule: the server drops an account-scoped setting at export and again at
  import and names it in its answer (E15-S07, `BL:1136`), or it refuses the whole file, in
  which case the preview's Drop row is a prediction and the outcome is
  `SCR-026/refused-server`
@ row D09-G3 · col 3
  no default account for a workspace
@ row D09-G10 · col 2
  `workspace.exported` sits on SCR-025's Audit line (`14:618`), while E15-D01's locked list
  keeps layout events analytics, never audit (`D02:84`), and E15-X01 asks that the export be
  audited (`BL:721`)
@ row D09-G11 · col 2
  The data class and the sharing claim: `exportWorkspace`'s description makes the sharing
  claim (`22:12679`), while `21:5069` classes the pane columns P0 and E15-X01 classes the
  file user-confidential (`BL:721`)
@ row D09-G11 · col 3
  `22`'s description drops the sharing claim and names the class
@ row D09-G15 · col 2
  An export carries the caller's whole live preset library, at most 500 and never truncated
  (`22:21224–21226`), not only the presets this workspace's panes use, while the Included
  list's "3 indicator presets" reads as the workspace's own
@ row D09-G15 · col 3
  the owner (#2701) chooses: the Included list says "all 3 of your indicator presets", or
  the bundle carries only the presets the panes reference (`22`'s owner)
@ row D09-C3 · col 2
  the ticket's Included list names densities, which `WorkspaceBundle` does not hold
  (`22:21209–21230`
@ row D09-C5 · col 2
  E15-D02's sentence "Never included: API keys or tokens, account or trade-group ids, user
  ids, P&L figures, positions or orders." (`D02:511`) is extended by BQ-2's to name
  credentials, accounts, the environment binding and the alert and rule bindings (AC 1): an
  extension, not a contradiction, and E15-D02's sentence is never shown on a frame
@ row D09-C8 · col 2
  `14:628`'s "accounts remapped", `14:629`'s "inaccessible account references remap to the
  user's default account" and AC 4's "remapped to the importer's default" against
  US-LAY-007's drop (`11:2868`) and BQ-3 RULED
@ row D09-C9 · col 2
  the ticket's risk "R13 Sharing abuse" (its `risk` field, `BL:242–259`), which E15-X01
  carries too (`BL:700`), against the register's R13, "Team & knowledge" (`32:47`)
@ row D09-C18 · col 2
  the ticket's Scope lists intervals among what the export preview enumerates (`BL:266`),
  against E15-D02's Included sentence (`D02:511`), in which a panel's interval is one of
  "each panel's settings": the sentence is kept as E15-D02 wrote it (the fifth deviation
@ row D09-C18 · col 2
  BQ-2 RULED: the Included list names only what the bundle holds)
@ row D09-A21 · col 2
  SCR-025's Share section: its Export… opens this spec's export dialog (§2.2), and its help
  line names what the file leaves out in BQ-2's classes, or points at the Excluded list, and
  never makes the sharing claim
@ row D09-Q6 · col 2
  the trust note's "Importing creates a new workspace and changes nothing else." stands
  beside Add rows for indicator presets, chart templates and drawings, which join the
  importer's own libraries (`22:21229–21232`, counted against the 500-preset cap): is the
  sentence kept word for word?
@ row E15-D08 (SCR-025 settings) · col 2
  Export… in its Share section opening §2's dialog (BQ-7 RULED)
@ row E15-D03 (SCR-020 chrome) · col 2
  Import… in "+" and Export… in `[⋯]` keep their keys (§6)
§ §13
@ prose
  `14` keeps its boxes, which the owner ticks on #363 and never this PR, and gains only the
  pointer lines (§11).
@ row import never carries credentials or acco · col 1
  import never carries credentials or account bindings (verified in copy)
@ row import never carries credentials or acco · col 2
  the Excluded list on `SCR-025/export-preview` and `SCR-025/export-done` (boards 01 and 10)
@ row import never carries credentials or acco · col 2
  the account setting's Drop row and its words (§4.2)
@ prose
  **SCR-025 (`14:624`)** is E15-D08's surface (PENDING, by name): of its four items this
  spec draws only Export… in the Share section, part of the first item's sharing (§2), and
  the export dialog it opens
§ §14
@ row user control and freedom · col 2
  a refusal keeps the dialog open with Choose another file focused
@ row error prevention · col 3
  the account setting's Drop row predicts what the server does until `22` says it (D09-G3)
@ row recognition rather than recall · col 2
  the Excluded list stays on the completion step
@ row recognition rather than recall · col 3
  Copy report is the way to keep it
@ prose
  the valid file, the newer and the older format version, the malformed, the oversized, the
  unknown kinds, the account filter and the 30-panel file
@ prose
  board 08): from "+" › Import… to the report without a pointer, file selection included
@ prose
  boards 01 and 02): the owner reads the Excluded list and the trust note cold and says what
  leaves the machine and what is ignored on import.
@ prose
  **Pre-registered rule:** a reader who believes the file may go anywhere without a thought,
  or that an account travels in it, makes the copy a redesign item before sign-off.
@ prose
  read the Included and the Excluded lists aloud, say what leaves the machine and what does
  not, and confirm that the sharing claim appears nowhere.
@ prose
  read the completion line and the file name, and say why the Excluded list is still shown.
@ prose
  check that no account is named and that nothing of the file appears beyond its capped
  names.
@ prose
  - [ ] Boards 09 and 10, the light twins: tell Add, Drop and Remap apart without colour,
  and read the trust note and the Excluded list.
§ §15
@ row AC-1 the included and the excluded lists · col 1
  AC-1 the included and the excluded lists
@ row AC-4 an account reference dropped and di · col 1
  AC-4 an account reference dropped and disclosed, naming no account
@ row DL-2, DL-3 the Included list and the Exc · col 1
  DL-2, DL-3 the Included list and the Excluded list, first-class
@ row DL-18 the limits; no environment travels · col 1
  the server re-checks
@ row DoD-3 both versions, a way on, no partia · col 1
  DoD-3 both versions, a way on, no partial apply
@ row DoD-7 the untrusted-string rule and the  · col 1
  DoD-7 the untrusted-string rule and the limits stated
§ §16
@ prose
  one `lg` dialog, Choose file… with its drop zone, five checks in a worker with the
  server's re-check stated, a preview table with its drops and remaps first, six rejections,
  two refusals and an unanswered send, none with an Import verb, and a report with Copy
  report
@ prose
  and of the export from SCR-025 and the menus: the Included and Excluded lists, the file
  name with its format version, the completion.
@ prose
  the trust copy, the account rule and the version rule are the owner's, approval pending
  (#2701).
"""
STATUS_PIN_TXT = r"""
§ E15-D09 — SCR-026 workspace import / exp
@ heading
  E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi
@ prose
  every decision PROPOSED unless RULED (6396085915)
@ prose
  **Owner approval pending (#2701)** (agent-delivery adaptations, owner decision
  2026-09-25): the owner's `approved` comment or the merge stands in for the ticket's CDO
  and Security-engineer sign-offs (§13).
@ prose
  the spec is this file, beside its E15 siblings (`14:635`), with its gate tool (BQ-1
  RULED).
@ prose
  BQ-1 RULED).
@ prose
  density is global or per panel, `D02:507`), so a C-row records the densities, and the
  Included list names only what the bundle holds (BQ-2 RULED).
@ prose
  the symbol cap.** BQ-10 RULED reads 16 for symbols from the pattern's `{2,16}`
§ Acceptance-criteria trace (#363)
@ heading
  Acceptance-criteria trace (#363)
@ row AC-1 · col 3
  the Excluded sentence byte for byte (BQ-2 RULED)
@ row AC-2 · col 2
  "A newer-version file is refused, not partially applied": both versions named, no option
  that applies part of the file
@ row AC-2 · col 3
  BQ-4 and BQ-11 RULED
@ row AC-4 · col 3
  §4.2 rows 3–4 (BQ-3 RULED: dropped and listed)
@ row DL-1 · col 3
  BQ-7 RULED)
@ row DL-4 · col 3
  BQ-8 RULED
@ row DL-12 · col 3
  BQ-2 RULED, owner approval pending (#2701)
@ row DoD-6 · col 2
  The copy signed off on the trust claims
@ row DoD-6 · col 3
  the owner's `approved` (#2701)
@ row DoD-9 · col 2
  CMP-067's Storybook list agreed
§ The questions (BQ-1…BQ-16) — RULED by th
@ heading
  The questions (BQ-1…BQ-16) — RULED by the orchestrator (2026-10-25, 6396085915, on the BQ
  comment 6396029607)
@ row BQ-1 · col 4
  RULED (6396085915)
@ row BQ-2 · col 4
  RULED (6396085915)
@ row BQ-3 · col 4
  RULED (6396085915)
@ row BQ-4 · col 4
  RULED (6396085915)
@ row BQ-5 · col 4
  RULED (6396085915)
@ row BQ-6 · col 3
  per layout, for the layout that opens: caught in the preview as the caption's last
  sentence and a warning line (`SCR-026/preview-over-budget`), then applied through
  US-LAY-001's CMP-044 confirm re-verbed "Import anyway", its Cancel focused
  (`SCR-026/budget-confirm`)
@ row BQ-6 · col 4
  RULED (6396085915)
@ row BQ-7 · col 4
  RULED (6396085915)
@ row BQ-8 · col 4
  RULED (6396085915)
@ row BQ-9 · col 4
  RULED (6396085915)
@ row BQ-10 · col 4
  RULED (6396085915)
@ row BQ-11 · col 4
  RULED (6396085915)
@ row BQ-12 · col 3
  the dialog's final step, a `role="region"` named "Import report" with the table
  re-rendered (§4.3) and Copy report (CMP-033)
@ row BQ-12 · col 4
  RULED (6396085915)
@ row BQ-13 · col 4
  RULED (6396085915)
@ row BQ-14 · col 4
  RULED (6396085915)
@ row BQ-15 · col 4
  RULED (6396085915)
@ row BQ-16 · col 4
  RULED (6396085915)
@ row Condition 1 · col 4
  RULED (6396085915)
@ row Condition 2 · col 4
  RULED (6396085915)
@ row Condition 3 · col 4
  RULED (6396085915)
@ row Condition 4 · col 3
  "RULED" cites 6396085915
@ row Condition 4 · col 4
  RULED (6396085915)
@ prose
  16 <!-- audit:bq_rows=16 --> questions and 4 <!-- audit:conditions=4 --> conditions RULED.
§ §0
@ heading
  0. Boards (PENDING — the boards PR draws them)
@ prose
  Dark and comfortable unless the row says otherwise: ten boards, two of them light twins
  (BQ-15 RULED).
@ prose
  drawn on request** (BQ-15 RULED): `SCR-025/export-preparing`, `SCR-025/export-failed`,
  `SCR-025/export-cancelled`, `SCR-025/export-reflow-200`, `SCR-026/drag-over`,
  `SCR-026/drag-over-rejected`, `SCR-026/creating`, `SCR-026/cancelled`, `SCR-026/compact`,
  `SCR-026/reflow-200`, `SCR-026/preview-migrated`, `SCR-026/rejected-nodes`,
  `SCR-026/refused-server`, `SCR-026/refused-unconfirmed`.
§ §1
@ heading
  1. Locked inputs, the trust boundary and decisions
@ prose
  Cited and never re-decided: each input below fixes something in this spec, and §2–§16 cite
  it rather than restate it. §1.2 states the trust boundary once and every frame of §2–§5
  applies it
§ §1.1
@ heading
  1.1 Locked inputs (cited, never re-decided)
@ row US-LAY-007: the export carries no secret · col 1
  a newer file is refused with the versions stated rather than applied in part
@ row US-LAY-007: the export carries no secret · col 3
  the Excluded list and the trust note (BQ-2 RULED)
@ row US-LAY-007: the export carries no secret · col 3
  the Drop rows (BQ-3 RULED)
@ row US-LAY-007: the export carries no secret · col 3
  the version refusals (BQ-4 RULED)
@ row D-15 and US-LAY-001's cost confirm: belo · col 3
  the budget line and the stacked confirm re-verbed Import anyway (BQ-6 RULED, §4.4)
@ row `22`: `exportWorkspace` is a read (`work · col 3
  Export… never gated (BQ-7 RULED)
@ row E15-D06 D-9: a layout never stores an ac · col 3
  the account setting's Drop row (BQ-3 RULED, §4.4)
§ §1.2
@ heading
  1.2 The trust boundary, stated once
@ row Exfiltration: the file leaves the machin · col 3
  `SCR-025/export-preview`, `SCR-025/export-done` (BQ-2 RULED
@ row Injection through content: every string  · col 2
  the same rule holds in the applied workspace, whose names the server sanitises again
  (`22:19626`)
@ prose
  BQ-5 RULED).** No workspace, layout or pane exists before Import as new workspace is
  pressed on a preview
@ prose
  **What the user is told (BQ-2 RULED
§ §1.3
@ heading
  1.3 The state inventory, reconciled (binding; the tool gates every row)
@ prose
  a failure after the send has no partial frame, because the import is never partial
  (D09-G1), and its frame is the server's refusal, or, when no answer came, the frame that
  says the import could not be confirmed.
§ §1.4
@ heading
  1.4 Decisions of this spec (PROPOSED unless RULED)
§ §2
@ heading
  2. Export: entry points, the preview dialog, the file and its completion
@ prose
  It sits in three places and opens one dialog (BQ-7 RULED, §2.2): a CMP-043
  `role="dialog"`, `size="md"`, at most 560 <!-- audit:contract.dialog_md_px=560 --> px wide
  (`15:466`), which calls `exportWorkspace` once, counts the Included list from the bundle
  it gets and saves that same bundle, so what the owner checks is what the file holds
  (`D02:511`
§ §2.1
@ heading
  2.1 Frames (binding; the tool gates every row)
§ §2.2
@ heading
  2.2 Entry points and the dialog
@ prose
  **Three places, one dialog (BQ-7 RULED).** Export… sits wherever a workspace is managed,
  and each place opens the same dialog on the workspace it belongs to:
@ prose
  this spec adds no shortcut and no palette command, and the three places are the ones BQ-7
  RULED names.
§ §2.3
@ heading
  2.3 The Included and Excluded lists: anatomy and redlines
@ prose
  **What the two lists say (BQ-2 RULED
§ §2.4
@ heading
  2.4 The file name and the completion
@ prose
  **The name (BQ-8 RULED
@ prose
  **The completion step (BQ-8 RULED).** When the write ends, the body changes in place
  (`SCR-025/export-done`): a CMP-028 `success` line, "Exported Scalping as
  scalping.cv-workspace-v1.json.", the file name in `type.num.sm` and selectable, then the
  Excluded list, unchanged, so the owner sees what the file leaves out as they send it on.
§ §2.5
@ heading
  2.5 Per frame: what changes, the components and the focus
§ §3
@ heading
  3. The import flow: entry, the dialog, choosing a file, validating, applying
@ prose
  SCR-026 is one CMP-043 `role="dialog"`, `size="lg"`, at most 960 <!--
  audit:contract.dialog_lg_px=960 --> px wide (`15:466`), because the preview's four columns
  need the width (BQ-9 RULED).
@ prose
  The trust note, `D02:513` verbatim, sits under the title from the first step to the send
  (BQ-2 RULED).
@ prose
  BQ-5 RULED).
§ §3.1
@ heading
  3.1 Frames (binding; the tool gates every row)
§ §3.2
@ heading
  3.2 The entries and the dialog's one chrome
@ prose
  **Entries (BQ-9 RULED).** Import… is an item of the tab strip's "+" menu, after New
  workspace… and Open workspace… (`D03:365`), and of the rail's workspace menu, where no
  merged text places it yet (BQ-9 RULED
@ prose
  **One chrome, five steps (BQ-9 RULED).** The body changes with the step
@ prose
  **Focus and keys in the dialog (BQ-13 RULED
§ §3.3
@ heading
  3.3 Choose file… and the drop zone (CMP-067)
@ prose
  **Choose file… (BQ-13 RULED
@ prose
  **The drop zone (BQ-9 RULED
§ §3.4
@ heading
  3.4 The five check steps, the validating state and the server's re-check
@ prose
  **The order (BQ-5 RULED
@ row 4 · col 3
  the file's `schema_version` (`22:21215`) against the format version this app reads (BQ-4
  RULED): newer is refused
@ prose
  BQ-9 RULED).** `SCR-026/validating` is CMP-023, determinate (`15:262–268`): its value
  moves a fifth at each step, and its value text, always shown, reads "Checking
  scalping.json… step 3 of 5" (`e15.import.checking`: `D02:515`'s words with the step
  added), the file's name capped at 40 <!-- audit:design.file_cap=40 --> characters as text.
@ prose
  **What is spoken (BQ-13 RULED
§ §3.5
@ heading
  3.5 The send, the creating state and every frame of §3.1
@ prose
  **The send (BQ-9 RULED
@ prose
  No toast is the report: the report is the dialog's region (BQ-12 RULED).
§ §4
@ heading
  4. The preview table and the report
§ §4.1
@ heading
  4.1 Frames (binding; the tool gates every row)
@ row `SCR-026/report` · col 3
  region: the dialog's final step, `role="region"` named "Import report", its heading
  `tabindex="-1"` focused on arrival, every line selectable
§ §4.2
@ heading
  4.2 The preview table (fixture `scalping.json`; binding)
§ §4.3
@ heading
  4.3 The report table (binding; §4.2's rows re-rendered)
§ §4.4
@ heading
  4.4 The preview: the table, the budget line, the stacked confirm and the migration line
@ prose
  **The table (BQ-10 RULED
@ prose
  **The Action column (BQ-10 RULED
@ prose
  **Account-scoped elements (BQ-3 RULED
@ prose
  **The panel budget (BQ-6 RULED
@ prose
  BQ-6 RULED
@ prose
  Cancel and `Esc` return to the preview with focus on Import as new workspace and fire
  `layout.import_rejected{reason: budget-exceeded}` once: the ticket's sixth reason counts a
  user who declined the stutter, not a refused file (BQ-6 RULED).
@ prose
  **The migration line (BQ-4 RULED
§ §4.5
@ heading
  4.5 The report and Copy report
@ prose
  **The report (BQ-12 RULED
@ prose
  then the same CMP-049 table re-rendered with what was applied, dropped and remapped, row
  for row as §4.3, its caption "Report — 7 panels and 2 layouts added · 3 dropped · 1
  remapped" (`e15.import.report.caption`).
@ prose
  **It persists (BQ-12 RULED).** The report stays until Close: no timer, never a toast
  (CMP-045) and never `role="status"`
@ prose
  BQ-12 RULED
§ §5
@ heading
  5. Rejections and refusals
@ prose
  never a lock, never a partial import** (BQ-4, BQ-5, BQ-11 RULED
@ prose
  the unanswered send says instead that the import could not be confirmed, because it may
  have happened.
§ §5.1
@ heading
  5.1 Frames (binding; the tool gates every row)
§ §5.2
@ heading
  5.2 The rejection frames' anatomy
@ prose
  the event fires once per rejection, its reason the ticket's word (BQ-11 RULED
@ row nested too deeply · col 6
  `malformed` (BQ-5 RULED)
@ row the send's answer never came · col 4
  that the import could not be confirmed
§ §5.3
@ heading
  5.3 The version rule (BQ-4 RULED, owner approval pending (#2701))
@ prose
  "format version" names what is compared, and the ticket's "This layout was exported by v2
  and can't be imported into v1." (`14:629`) is replaced by the ruled words (BQ-4 RULED
§ §5.4
@ heading
  5.4 The limits, rendered from the tool
@ prose
  The checks run cheapest first, and the first that fails ends the run, so a 50 MB file is
  refused before it is read (BQ-5 RULED
@ row 2 parse · col 3
  the server's own rule for a workspace body (`22:19626`), reused (BQ-5 RULED)
@ prose
  **The budget is a confirm, not a refusal** (BQ-6 RULED).
§ §5.5
@ heading
  5.5 Untrusted strings, nothing kept, and the refusals at the send
@ prose
  **Condition 1, applied to a refusal** (RULED, binding on every frame).
@ prose
  **Nothing kept.** When a refusal shows, the worker's text and document and the file's
  handle are dropped: nothing reaches the workspace store, the browser's storage, a cache or
  a log, and Choose another file starts from nothing (BQ-5 RULED).
§ §6
@ heading
  6. T2 — stated once
@ prose
  BQ-14 RULED
§ §6.1
@ heading
  6.1 The gated set, per session
@ prose
  BQ-11 RULED).
@ prose
  the budget's Import anyway is a confirm, not a gate (BQ-6 RULED).
§ §7
@ heading
  7. Exits, keyboard, focus and live regions
@ row the import succeeds after the view was c · col 3
  polite, once, through CMP-212's region: a persistent CMP-045 `success` toast with the
  success line and the action View report, which reopens the report as the dialog's final
  step (PROPOSED
§ §8
@ heading
  8. Tokens, contrast, greyscale and CVD
@ prose
  and never a row's colour (BQ-10 RULED
§ §9
@ heading
  9. Copy deck
@ prose
  on the export the base name the save sheet returned, suggested as
  `<slug>.cv-workspace-v<schema_version>.json` (BQ-8 RULED
@ row `e15.export.included` · col 4
  only what `WorkspaceBundle` holds (BQ-2 RULED
@ row `e15.export.done` · col 4
  new · PROPOSED (BQ-8 RULED: the drawn completion)
@ row `e15.import.title` · col 4
  new · PROPOSED (BQ-9 RULED)
@ row `e15.import.trust` · col 4
  upstream · `D02:513`, verbatim (BQ-2 RULED
@ row `e15.import.caption` · col 4
  new · PROPOSED (BQ-10 RULED)
@ row `e15.import.col.item` · col 4
  BQ-10 RULED)
@ row `e15.import.col.type` · col 4
  BQ-10 RULED)
@ row `e15.import.col.action` · col 4
  BQ-10 RULED)
@ row `e15.import.col.reason` · col 4
  BQ-10 RULED)
@ row `e15.import.action.add` · col 4
  the ticket's three words (BQ-10 RULED)
@ row `e15.import.action.drop` · col 4
  the ticket's three words (BQ-10 RULED)
@ row `e15.import.action.remap` · col 4
  the ticket's three words (BQ-3, BQ-10 RULED)
@ row `e15.import.reason.account` · col 4
  upstream · `D02:516` (BQ-3 RULED)
@ row `e15.import.reason.remap` · col 4
  new · PROPOSED (BQ-3 RULED)
@ row `e15.import.caption_budget` · col 4
  new · PROPOSED (BQ-6 RULED)
@ row `e15.import.budget` · col 4
  new · PROPOSED (BQ-6 RULED)
@ row `e15.import.report.heading` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.report.caption` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.report.copy` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.rejected.version_newer` · col 4
  adapted · `D02:517` and `14:629`: "format version" names what is compared, the
  constructive sentence added (BQ-4 RULED
@ row `e15.import.rejected.version_older` · col 4
  new · PROPOSED (BQ-4 RULED
§ §10
@ heading
  10. Design-system A-rows (`15`, PROPOSED)
@ prose
  This PR edits no `15` entry (BQ-1 RULED).
@ row D09-A1 · col 5
  BQ-9, BQ-13 RULED
@ row D09-A2 · col 5
  BQ-13 RULED
@ row D09-A4 · col 5
  the ticket's DoD, CMP-067's Storybook list agreed with FE (`BL:266`
@ row D09-A6 · col 5
  BQ-11 RULED
@ row D09-A7 · col 5
  BQ-2 RULED)
@ row D09-A8 · col 6
  `SCR-026/report`'s footer (BQ-12 RULED)
@ row D09-A9 · col 5
  `SCR-026/budget-confirm` (BQ-6 RULED)
§ §11
@ heading
  11. `14` A-rows and the pointer lines
@ prose
  **Applied by this PR, content only (BQ-1 RULED).** Two pointer lines, each right after its
  screen's sign-off checklist
@ row D09-A12 · col 5
  BQ-3, BQ-5 and BQ-9 RULED
@ row D09-A13 · col 5
  BQ-3 and BQ-4 RULED, owner approval pending (#2701)
@ row D09-A15 · col 5
  BQ-9, BQ-10, BQ-12 and BQ-13 RULED
@ row D09-A17 · col 5
  BQ-3 and BQ-4 RULED, owner approval pending (#2701)
@ row D09-A18 · col 5
  BQ-7 RULED
§ §12
@ heading
  12. A, C and G rows, and the hand-offs
@ prose
  Every row is PROPOSED to its owner, and none is applied by this PR: a contract changes
  contract-first in its owner's PR (C-6.1), `14` and `15` through the A-rows of §10 and §11,
  and a ruling stays the orchestrator's (6396085915) or the owner's (#2701).
@ prose
  E15-S07 receives D09-G1 to D09-G8, D09-G13 and D09-G14 by the hand-off row below (BQ-3
  RULED).
@ row D09-G11 · col 3
  this spec writes the caveat instead (BQ-2 RULED)
@ row D09-G14 · col 2
  The file-name slug rule: whoever names the file applies it (BQ-8 RULED the pattern)
@ row D09-C1 · col 2
  BQ-1 RULED)
@ row D09-C2 · col 2
  BQ-1 RULED)
@ row D09-C3 · col 2
  BQ-2 RULED)
@ row D09-C4 · col 2
  BQ-10 RULED a symbol cap of 16 from the pattern's `{2,16}`
@ row D09-C8 · col 2
  `14:628`'s "accounts remapped", `14:629`'s "inaccessible account references remap to the
  user's default account" and AC 4's "remapped to the importer's default" against
  US-LAY-007's drop (`11:2868`) and BQ-3 RULED
@ row D09-C10 · col 2
  the report here is a region with a table (BQ-12 RULED)
@ row D09-C14 · col 2
  the ticket's `version-older` as a rejection reason (`BL:266`) against E15-S07's older file
  migrated forward (`BL:1136`): reconciled by BQ-4 RULED, where `version-older` names only a
  file older than the oldest version this app still reads
@ row D09-C17 · col 2
  the ticket's 30-panel file (`BL:266`), meant for the budget's confirm, holds more panes
  than the 16 a layout holds (`D02:133`), so it is the panes variant of
  `SCR-026/rejected-malformed`, never the budget (BQ-5 and BQ-6 RULED)
@ row D09-C18 · col 2
  BQ-2 RULED: the Included list names only what the bundle holds)
@ row D09-A20 · col 2
  E15-D03's deck gains the import's three cost strings, adapted from `layout.cost.title`,
  `.body` and `.confirm` (`D03:629–631`): `layout.cost.import.title` "Open {layout} with
  {panels}?", `layout.cost.import.body`, its measured and estimated sentence with the
  import's clause (§9), and `layout.cost.import.confirm` "Import anyway" (BQ-6 RULED)
@ row D09-A22 · col 2
  BQ-9 RULED): E15-D03's R-5 (`D03:564`) gains the rail's row, and the rail's menu gains the
  item
@ row D09-Q5 · col 2
  the schema step reads `schema_version` from the envelope ahead of its shape rules, so a
  newer or an older file meets its version refusal and never a shape failure: confirmed?
@ row D09-Q6 · col 3
  the ruled sentence, verbatim (BQ-2 RULED)
@ row D09-Q7 · col 3
  the ruled sentence (BQ-4 RULED)
@ row E15-S07 (the import and export story) · col 2
  D09-G1 to D09-G8, D09-G13 and D09-G14 (BQ-3 RULED)
@ row E15-D08 (SCR-025 settings) · col 2
  Export… in its Share section opening §2's dialog (BQ-7 RULED)
§ §13
@ heading
  13. Sign-off checklists, item by item
@ row version-mismatch state ('exported from a · col 2
  `SCR-026/rejected-version-newer` (boards 04 and 09): both versions and a way on, nothing
  imported and nothing applied in part
§ §14
@ heading
  14. Heuristic evaluation and the owner walkthrough
§ §15
@ heading
  15. Traceability
@ row AC-2 a newer file refused, never applied · col 1
  AC-2 a newer file refused, never applied in part
@ row DoD-6 the copy signed off on the trust c · col 1
  DoD-6 the copy signed off on the trust claims
@ row DoD-9 the spec merged; CMP-067's Storybo · col 1
  CMP-067's Storybook list agreed
§ §16
@ heading
  16. Summary
"""


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
