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
logged, cached; SEC_BEARING_RE, any case) must equal its entry of SEC_PIN_TXT. The status pin is
default-deny on the unit (fold 4): every unit that carries a decision or a row status in any word
and any case (PROPOSED, RULED, pending, owner approval, applied, merged, settled, done, closed,
landed, final, agreed, approved, accepted, adopted, shipped, "in `main`" and their forms;
STATUS_BEARING_RE), and every unit of §10, §11, §12 and the BQ table, whole (STATUS_WHOLE_RE), must
equal its entry of STATUS_PIN_TXT, each entry its section, its place (heading, prose, or row and
column) and its exact text, in document order. A unit that is new, changed, moved or duplicated,
and a pinned unit that is gone (its status word deleted or swapped for a word the list lacks), FAIL
`sec-pin` or `status-pin` with its own place: the word list only widens what is pinned, the table
decides what a unit may say. A pin is the backstop, reported when every other gate passes, so one
fault reads as one FAIL. `--repin-security` and `--repin-status` rewrite their table in this file
from the current text and print the diff for a reviewer to read and commit; `--check` never
re-pins.

The whole text is pinned too, block by block, default-deny (the lens round 1 ruling): every
heading, every paragraph, list and table run and every fenced block, keyed by its heading path and
occurrence and its place under the heading, whitespace-normalised line by line (a fenced line
verbatim), with the blank lines before it, must equal its entry of RULED_PIN_TXT. A block changed,
soft-wrapped, grown by a line, moved, duplicated, deleted or new, a new heading and a blank-line
change FAIL `text-pin` by location; `--repin-ruled` is the table's only writer. The vocabulary
gates stay the first line: the pin FAILs only when every other gate passes, and beside another
FAIL it names the same fault on a NOTE line. `--repin-cites` moves every CITED_TABLE needle found
at another line, in the table and in every cite of the spec and of this file, and prints the moves.

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
       [--self-test] [--repin-security] [--repin-status] [--repin-ruled] [--repin-cites]
"""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import re
import sys
import textwrap
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

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
BASE = "908667f27b63c5722cb084819902bcbd7943bf28"
# The orchestrator's ruling on the BQ list (issue comment on #363): "RULED" cites this id.
RULING = "6396085915"
# The BQ comment the ruling answers (the questions table's heading names both).
BQ_COMMENT = "6396029607"
# The merged inputs the header pins: E15-D01, E15-D02 text and boards, E15-D03, E15-D04,
# E15-D06, E09-D09, and E15-D08 and E15-D05, each named only and never cited by line.
MERGE_SHAS = (
    "ed8a22246263ace73f39e4434e6d5f57b1a857bd",
    "1044c4f602eff6ae1a2cf42201ab398f6c4234d1",
    "7be6eac6a705cf24ba534ce4f7d31349a1e29932",
    "c73aec08246f06d28c70e8b959c658bc1a0c4d09",
    "6e2c1211fc5f4675457d57011a346642f92710c5",
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
    "c4989493461ec6b6d22b9254633452a6362b750e",
    "fb1b48041ae0a12638beacae6a61854833c5cc4d",
    "013562636a339ab32c80d257b9d1f8cef8e64422",
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
04 | 855 | | SR-040  | All external input
04 | 924 | | SR-097 | Replay, export and import endpoints MUST NOT accept filesystem paths
04 | 967 | | SR-127 | React code MUST NOT use `dangerouslySetInnerHTML`
04 | 1141 | | `workspaces:write`                                 |                 ✔
04 | 1182 | Save/load own layouts, templates, drawings, hotkeys
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
14 | 616 | ### SCR-025 — Workspace settings modal
14 | 618 | export as template, delete
14 | 621 | `workspace.updated`, `workspace.deleted`, `workspace.exported`
14 | 627 | [ ] delete-workspace confirmation path
14 | 630 | ### SCR-026 — Workspace import
14 | 632 | (panels added, symbols referenced, accounts remapped)
14 | 633 | inaccessible account references remap to the user's default account
14 | 634 | CMP-044 ConfirmDialog, CMP-067 FileDrop / Import control.
14 | 636 | the import diff is a table, not a canvas
14 | 637 | a 2 MB layout file validates in <=500 ms
14 | 638 | `layout.imported`, `layout.import_rejected` with `{reason}` (analytics)
14 | 639 | §5.11 (Penpot page `E15-D02`, board 18
14 | 640 | [ ] import never carries credentials or account bindings (verified in copy)
14 | 1990 | ### SCR-089 — Rule import / export
14 | 1999 | [ ] export selection (single / selected / all) with a scope-stripping note
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
21 | 3302 | -- sanitised, 1..120 code points
21 | 5079 | Pane settings must never carry credentials or account identifiers
22 | 8682 | operationId: createWorkspace
22 | 8686 | `limit_reached` (32 live workspaces)
22 | 8691 | Bodies over 4 KiB are refused with `413` (`payload_too_large`)
22 | 8692 | `Idempotency-Key` is accepted, never required
22 | 8886 | `limit_reached` (32 live layouts)
22 | 12843 | operationId: exportWorkspace
22 | 12846 | The bundle is self-contained and contains no credentials, account identifiers or
22 | 12848 | `POST /workspaces` with `from_bundle`.
22 | 19819 | validation_failed`): JSON nesting depth must be at most 16;
22 | 19831 | At most 40 characters as sent, at least 1 after sanitising (above), SCR-020.
22 | 19971 |     PaneKind:
22 | 20031 | and never holds credentials, account ids or user ids
22 | 20041 | Every key must match `^[a-z][a-z0-9_]{0,31}$`
22 | 20057 | a Bybit USDT linear perpetual symbol of at most 20 characters
22 | 20066 | Every non-null value is refused (`422` rule `chart_template_not_found`)
22 | 20072 | A non-empty list is refused (`422` rule `indicator_preset_not_found`)
22 | 20390 | else 422 rule `layout_not_found`
22 | 21402 |     WorkspaceBundle:
22 | 21406 | Portable, credential-free export of presentation state only.
22 | 21408 | schema_version: { type: string }
22 | 21417 | Export holds only the caller's live presets
22 | 21419 | Import (E15-S07; no operation takes a bundle yet) never trusts
22 | 21422 | the array is imported whole or not
22 | 21423 | The server refuses it whole beyond 200 items or 1 MiB of preset JSON
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
# a build that knows two more panel kinds (a kind is additive for readers, `22:19971`), whose
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
# The focus pairs S20 allows beside a frame's own focus (fold 4), §7's one line rendered from them:
# Cancel is a drawn footer control and a real focus target on these five frames (refused-limit's
# own focus, the preparing line's, where Try again returns it). Any other focus claim fails there.
FOCUS_PAIRS = {
    "SCR-026/refused-limit": ("Cancel",),
    "SCR-025/export-preparing": ("Cancel", "the title"),
    "SCR-025/export-preview": ("the title", "Cancel"),
    "SCR-025/export-failed": ("Try again", "Cancel"),
    "SCR-025/export-cancelled": ("Download file", "Cancel"),
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
    # The exit forms of the lens round 1: an exit removed, not drawn or swallowed.
    r"|\bremov(?:e|es|ed|ing)\b|\b(?:is|are|stays?|remains?) not drawn\b|\bnot drawn until\b"
    r"|\bswallow(?:s|ed|ing)?\b"
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
# The active voice (lens round 1): "the worker creates the new workspace as soon as the file passes
# the size step". An active create is early when its clause names a client-side maker or a moment
# before the send (a check step, the pick, the drop, the preview); the server's create at the send
# ("an import always creates a new workspace") states the contract and stands.
CREATE_ACTIVE_RE = (
    r"(?i)\b(?:creates?|creating|saves?|saving|stores?|storing|writes?|writing|adds?|adding"
    r"|persists?|persisting|makes?|making|builds?|building|sets? up)\s+"
    r"(?:(?:the|a|an|its|your|their)\s+)?(?:(?:new|draft|imported|temporary)\s+)?"
    r"(?:workspaces?|layouts?|panes?|panels?|tabs?|drafts?|cop(?:y|ies))\b"
)
CREATE_EARLY_CUE_RE = (
    r"(?i)\b(?:worker|browser|client|picker|drop zone)\b"
    r"|\b(?:as soon as|once|while|before|during|when)\b[^;]*\b(?:pass\w*|check\w*|pick\w*"
    r"|chos\w*|drop\w*|validat\w*|pars\w*|steps?|opens?)\b"
)
# Keep forms a refused file is the only subject of, gated in every section with or without a refusal
# word near them (fold 4): the layouts that passed, what passed, staying or left in your workspaces.
KEEP_ALWAYS_RE = (
    r"(?i)\bthe (?:layouts?|panels?|panes?|parts?) that passed\b|\bwhat passed\b"
    r"|\bbefore the check failed\b"
    r"|\b(?:stays?|remains?|(?:is|are|was|were) left)\s+(?:\w+\s+){0,2}?in your workspaces?\b"
)
KEEP_RE = (
    r"(?i)\b(?:is|are|was|were|has been|have been|stays?|remains?|gets?|got|being)\s+"
    + NOT_NEG
    + r"(?:kept|saved|stored|retained|imported|added|cached|created|persisted|applied)\b"
    + POST_NEG
    + r"|\bkeeps?\s+(?:the\s+|its\s+|a\s+)?(?:valid\s+|parsed\s+|checked\s+|passed\s+)?(?:layouts?"
    r"|panels?|panes?|parts?|document|rest|draft)\b|\bretain\w*|\bpartial(?:ly)?\b"
    r"|\bthe valid (?:parts?|layouts?"
    r"|panels?|panes?)\b|\bbrought in\b|\bcontinues?\s+with\b"
    r"|\bkept in (?:the browser's storage|local storage|a cache|the cache)\b"
    # The keep forms with no keep verb (fold 4): what stays, remains or is left.
    r"|\b(?:layouts?|panels?|panes?|parts?|tabs?|workspaces?|rest)\s+(?:that\s+\w+\s+)?"
    r"(?:stay|stays|remain|remains|(?:is|are|was|were) left)\b(?!\s+(?:unchanged|as|empty)\b)"
    + "|"
    + KEEP_ALWAYS_RE.removeprefix("(?i)")
)
# The budget confirm's footer in prose (lens round 1): a sentence naming the confirm and its footer,
# primary, verb or button names only the confirm's own controls (FOOTERS["budget-confirm"]).
CONFIRM_RE = (
    r"(?i)budget-confirm\b|\b(?:stacked|cost|budget|measured-cost) confirm\b|\bconfirm['’]s\b"
)
CONFIRM_SLOT_RE = (
    r"(?i)\bfooter\b|\bprimary\b|\bre-?verb\w*|\bverb\b|\bbuttons?\b|\breads\b|\blabel\w*"
)
CONFIRM_NAMES_OK = frozenset(
    {
        *("Cancel", "Import", "Esc", "US-LAY-001", "CMP-044", "CMP-001", "E15-D03", "SCR-026"),
        *("BQ-6", "RULED", "DL-16", "Add", "Open", "Wall", "Over", "The", "A", "It", "Its"),
        *("PROPOSED", "D09-A20"),
    }
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
# A focus claim's known controls (S20): the names a focus statement may land on.
FOCUS_CONTROLS = (
    r"Cancel|Choose another file|Choose file…|Close|Import as new workspace|Import anyway|Try again"
    r"|Download file|Copy report|the title|the heading|the message|×"
)
# Any focus claim, its target read whatever it names (fold 5, default-deny): a target that is not
# one of FOCUS_CONTROLS ("focus moves to Import", "Retry takes focus") is its own unknown name.
FOCUS_ANY_RE = (
    r"(?i)\bfocus(?:es|ed)?\s+(?:\w+\s+){0,3}?(?:on|to|onto)\s+(?P<a>[^\s.,;:()]+)"
    r"|(?P<b>[^\s,;:()]+)\s*,?\s+(?:the\s+\w+,\s+)?(?:is\s+)?"
    r"(?:focused|takes focus|gets focus|has focus|holds focus)\b"
    r"|\btab\s+(?:starts|begins)\s+(?:on|at)\s+(?P<c>[^\s.,;:()]+)"
)
# A chained focus target: a connective ("and", "or", "then", "next", "later", "afterwards"), a
# comma before it allowed, then the target, "to" / "on" / "onto" optional.
FOCUS_CHAIN_RE = (
    r"(?i)[\s\"”\]]*,?\s*(?:(?:and|or|then|next|later|afterwards)\b[\s,]*)+(?:(?:on|to|onto)\s+)?"
)
REJECTION_CTX_RE = (
    r"(?i)\breject(?:ion|ions|ed)\b|\brefusals?\b|\brefused-\w+|\brejected-\w+"
    r"|\bnothing was imported\b"
)
# The keep scope (S11) reads every form of the verbs too: "the server refuses the file", "a refused
# file", "it rejects" are refusals whose keep claims count, wherever the sentence stands.
REFUSED_RE = (
    REJECTION_CTX_RE
    + r"|\brefus(?:e|es|ed|ing)\b|\breject(?:s|ing)?\b"
    # Its synonyms (fold 4): a file that fails, is turned down, declined or not accepted.
    + r"|\bfail(?:s|ed|ing)?\b|\bturn(?:s|ed)? down\b|\bturned\s+\w+\s+down\b"
    + r"|\bdeclin(?:e|es|ed|ing)\b|\bnot accepted\b|\b(?:isn|aren|wasn|weren)['’]t accepted\b"
)
# "Not accepted" names a refusal: its "not" governs "accepted" only, never the keep claim after it.
NOT_ACCEPTED_RE = r"(?i)\b(?:not|isn['’]t|aren['’]t|wasn['’]t|weren['’]t)(?=\s+accepted\b)"
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
    "2 panels": "`14:640`'s checklist item, quoted (D09-C7)",
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
14 | 632 | SCR-026/preview
14 | 633 | SCR-026/rejected-version-newer, SCR-026/preview
14 | 636 | SCR-026/pick, SCR-026/preview, SCR-026/rejected-malformed
14 | 640 | SCR-026/pick, SCR-026/drag-over, SCR-026/preview, SCR-026/rejected-oversized
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
MARKER_LOOSE_RE = r"<!--\s*audit:[^\n]*?(?:--!?>|$)"
NUMBER_BEFORE_RE = r"\(?(\d{1,3}(?:[,\u202f\u00a0]\d{3})+|\d[\d.:]*)\)?"
# key count — every marker key the spec carries and exactly how many times (M8: a marker
# deleted or added unpinned is a FAIL).
# --- held whole: generated from the spec, then reviewed; a change here is a change there ---
PRODUCERS = {
    "SCR-025/export-entry": (
        "Export… opened from SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's "
        "`[⋯]` (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored workspace"
    ),
    "SCR-025/export-unavailable": (
        "the viewer's unsaved default (`D03:583`, `D03:625`), or a workspace with no stored "
        "copy (`D03:384`)"
    ),
    "SCR-025/export-preparing": (
        "Export… chosen on the stored workspace Scalping; `exportWorkspace` called "
        "(`22:12843`), its bundle not back yet"
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
        'a Viewer session opens "+" or the rail\'s workspace menu (`04:1141`, `D03:564`; the '
        "rail's item, D09-A22)"
    ),
    "SCR-026/entry-limit": (
        'an Owner session at the workspace limit opens "+" or the rail\'s workspace menu '
        "(`22:8686`, `D03:564`; the rail's item, D09-A22)"
    ),
    "SCR-026/pick": ("Import… chosen: the dialog opens empty (`D02:513`)"),
    "SCR-026/drag-over": ("one .json file dragged over the zone"),
    "SCR-026/drag-over-rejected": (
        "two files, or a file whose type is not JSON, dragged over the zone"
    ),
    "SCR-026/validating": ("`scalping.json` chosen: the worker checks it (`D02:515`, `14:637`)"),
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
        "a file nested deeper than the depth limit (`22:19819`); over the node count is its "
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
            "worker (`14:637`) | `SCR-026/rejected-oversized` | "
            "`e15.import.rejected.oversized` |",
            "| 2 parse | nesting at most 16 <!-- audit:contract.depth=16 --> levels | the "
            "server's own rule for a workspace body (`22:19819`), reused (BQ-5 RULED) | "
            "`SCR-026/rejected-nodes` | `e15.import.rejected.depth` |",
            "| 2 parse | at most 10,000 <!-- audit:contract.nodes=10000 --> values, PROPOSED | "
            'E15-S07 names a node-count limit and fuzzes "a document with 10000 nested nodes" '
            "(`BL:1136`); no contract carries a number (D09-G5) | `SCR-026/rejected-nodes`, "
            "its variant | `e15.import.rejected.nodes` |",
            "| 3 schema | the envelope's `schema_version` first, then the shape of a version "
            "this app reads: every required key and every known key's type (`22:21402–21423`) "
            "| `22:21402–21423`; an unknown key ignored by the client and refused by the "
            "server on its write path (C-6.3; `04:855`); the bundle and `ChartTemplateInput` "
            "are not closed yet (D09-G4) | `SCR-026/rejected-malformed` | "
            "`e15.import.rejected.malformed` |",
            "| 3 schema | at most 16 <!-- audit:contract.panes_max=16 --> panels a layout | "
            "the contract's 16 (`D02:133`) | `SCR-026/rejected-malformed`, its variant | "
            "`e15.import.rejected.panes` |",
            "| 3 schema | at most 32 <!-- audit:contract.layouts_max=32 --> layouts a "
            "workspace | the store's limit (`22:8886`); the bundle carries none (D09-G5) | "
            "`SCR-026/rejected-malformed`, its variant | `e15.import.rejected.layouts` |",
            "| 3 schema | at most 200 <!-- audit:contract.presets_max=200 --> indicator "
            "presets, the array whole or not at all | `22:21422–21423`, where the server also "
            "refuses the array beyond 1 MiB of preset JSON | `SCR-026/rejected-malformed`, its "
            "variant; the server's refusal is `SCR-026/refused-server` | "
            "`e15.import.rejected.presets` |",
            "| 4 version | the format versions this app reads (§5.3) | `22:21408`; D09-G2 | "
            "the two version refusals; the migrated preview | §5.3 |",
            "| 5 registry | each pane's kind and each setting against the registry | the "
            "open-ended kinds (`22:19971`); settings that never hold account ids (`22:20031`) "
            "| never a rejection: an unknown kind or an account-scoped setting is a Drop row "
            "(§4.2) | `e15.import.reason.unknown_kind` |",
            "| the send | at most 32 <!-- audit:contract.workspaces_max=32 --> workspaces a "
            "user | `22:8686` | `SCR-026/refused-limit` | `e15.import.refused.limit` |",
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
            "rule for a request body (`22:19819`); 10,000 <!-- audit:contract.nodes=10000 --> "
            "values (`BL:1136`), PROPOSED (D09-G5) | `SCR-026/rejected-nodes` (the depth, with "
            "the node count its variant); invalid JSON: `SCR-026/rejected-malformed`'s parse "
            "variant, which names the line | `malformed` |",
            "| 3 | schema | first the envelope, `schema_version` present and a whole number "
            "(D09-D25), else the malformed outcome that names it; then the shape of that "
            "format version, only when this app reads it (one shape per readable version, "
            "D09-G2), against `WorkspaceBundle` (`22:21402–21423`): every required key present "
            "and every known key's value of its kind, a pane's kind an open string for a "
            "reader (`22:19971`), no layout over its panes, no workspace over its layouts, the "
            "indicator presets whole or not at all; an unknown key is ignored and never read "
            "into the app (C-6.3); a version above the newest or below the floor skips the "
            "shape and goes to step 4, so the shape never shadows the version outcome (D09-Q5) "
            "| 16 <!-- audit:contract.panes_max=16 --> panes a layout (`D02:133`); 32 <!-- "
            "audit:contract.layouts_max=32 --> layouts a workspace (`22:8886`); 200 <!-- "
            "audit:contract.presets_max=200 --> presets a file (`22:21422–21423`) | "
            "`SCR-026/rejected-malformed`: the missing key, or the known key whose value is "
            "the wrong kind, named in mono, or its panes, layouts and presets variants | "
            "`malformed` |",
            "| 4 | version | the file's `schema_version` (`22:21408`) against the format "
            "version this app reads (BQ-4 RULED): newer is refused; older and still readable "
            "is migrated forward in the worker; older than the oldest this app reads is "
            "refused | this app reads format version 1 <!-- audit:fixture.app_format=1 -->; "
            "the order of versions and the oldest one read are D09-G2's | "
            "`SCR-026/rejected-version-newer`; `SCR-026/rejected-version-older`; a migration "
            "is no failure: `SCR-026/preview-migrated` | `version-newer`; `version-older` |",
            "| 5 | per-pane registry | each pane's kind against this build's registry "
            "(`22:19971`) and each pane setting against the registry's list for its kind "
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
            "caption, its counts first, so the summary comes before the rows (`14:636`); after "
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
            "cell's text | `15:530`; `14:636` |",
            '| a rejection, focus on Choose another file | button · "Choose another file", '
            "focused once the message's polite region has read it, e.g. \"This file was "
            "exported by format version 2 and can't be imported into format version 1. Nothing "
            'was imported. Export it again from a version 1 app, or update this app."; the '
            "message is not the button's description, so it is read once | `15:306`; `05:150` |",
            "| the malformed file's key | inside the message, plain text read in order, its "
            "punctuation as the reader's settings speak it; at most 64 <!-- "
            'audit:design.key_cap=64 --> characters, then "(shortened)" (§5.5) | `14:636` |',
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
        "| Included item | Built from the bundle (`22:21402–21423`) | For Scalping | Left out "
        "when |"
    ): (
        "pinned-row",
        (
            "| the layouts, with their names | `layouts[]`, each `name` (at most 40 <!-- "
            "audit:contract.name_max=40 --> characters, `22:19831`), in the bundle's order | 2 "
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
            "`21:3302`) | 12 drawings, with their text labels | there is no drawing |",
            "| the chart templates | `chart_templates[]` | 1 chart template | there is none |",
            "| the indicator presets | `indicator_presets[]`: every live preset of the caller, "
            "never truncated (`22:21419–21423`) | 3 indicator presets | there is none |",
        ),
    ),
    ("| # | Question | Built here (the ruled outcome) | Status |"): (
        "bq-terms",
        (
            "| BQ-1 | the deliverable path, the branch, the Penpot page, the `14` / `15` edit "
            "set, the PR | this file, `docs/design/E15/E15-D09.md`, and its tool "
            "`e15_d09_import_export_audit.py`; the ticket's spec path and branch are the first "
            "two deviations; the Penpot page `E15-D09 Workspace import and export`; two "
            "content-only `14` pointer lines, after SCR-025's checklist (`14:627`) and "
            "SCR-026's (`14:640`), and PROPOSED A-rows for `14:632–633` and `14:640` (§11); no "
            "`15` edit — A-rows only (§10); the PR says `Refs #363` and `Partial:`, never a "
            "closing keyword | RULED (6396085915) |",
            "| BQ-2 | the trust claims, word for word | the Excluded list, first-class and "
            "drawn as a list, in AC 1's words: \"Never included: credentials — API keys or "
            "tokens; accounts, trade-group and user ids; environment binding (DEMO or LIVE); "
            'alert and rule bindings; P&L, positions or orders." — a C-row to `D02:511`, an '
            "extension and not a contradiction; the Included list names only what "
            "`WorkspaceBundle` holds (`22:21402–21423`); the import's trust note is `D02:513` "
            'verbatim: "A workspace file never carries credentials or account bindings. '
            'Importing creates a new workspace and changes nothing else."; the sharing claim '
            "in `22:12846`'s description is never written anywhere (its G-row names it without "
            "repeating it); the tool gates both sentences byte for byte on every frame that "
            "shows them; owner approval pending (#2701) | RULED (6396085915) — owner approval "
            "pending (#2701) |",
            "| BQ-3 | account-scoped elements on import | dropped and listed, never remapped, "
            "and no account the importer cannot see is ever named in the preview, the report "
            'or a reason: its row reads "workspaces never carry account bindings" (§4.2 row '
            '3); the word "Remap" is kept for the one true remap, the Positions pane that '
            "shows your own accounts (§4.2 row 4); `14:632–633` and the checklist item of "
            "`14:640` get PROPOSED A-rows (§11); E15-S07 receives D09-G1…G8, G13 and G14 by "
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
            "— SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's `[⋯]` "
            "(`D03:384`) and the rail's workspace menu (`D02:511`) — and one CMP-043 `md` "
            "dialog with the Included and Excluded lists built from the fetched bundle; "
            "Export… is a read (`22:12843`), never gated (a read): T1 for every session, "
            "view-as included; on "
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
            "| BQ-14 | T2 per role, view-as first | Import… is a write (`22:8682`): its legs "
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
    "c4989493461ec6b6d22b9254633452a6362b750e": 2,
    "fb1b48041ae0a12638beacae6a61854833c5cc4d": 12,
    "013562636a339ab32c80d257b9d1f8cef8e64422": 4,
    "908667f27b63c5722cb084819902bcbd7943bf28": 1,
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


def focus_claims(body: str) -> list[tuple[str, int]]:
    """Every focus claim of `body`, default-deny: (the control it names, lower case, or the
    unknown name it lands on instead, its offset). A known control is read whole ("Choose another
    file", "the title"); any other Title-case or quoted name ("Import", "the Retry button") is an
    unknown control and returned as its word. Lower-case targets name no control (the opener,
    "the menu's button", a pronoun) and frame names in backticks are not targets."""
    known_head = re.compile(rf"(?i)(?:{FOCUS_CONTROLS})(?![\w…])")
    known_tail = re.compile(rf"(?i)(?<![\w…])(?:{FOCUS_CONTROLS})$")
    found: list[tuple[str, int]] = []
    for m in re.finditer(FOCUS_ANY_RE, body):
        if m.group("b") is not None:
            k = known_tail.search(body[: m.end("b")])
            if k:
                found.append((k.group(0).lower(), m.start()))
            else:
                # "the Retry button is focused": a control noun reads the name before it.
                before = (
                    body[: m.start("b")].split()[-1:]
                    if m.group("b").lower() in ("button", "control")
                    else []
                )
                name = focus_named(m.group("b")) or "".join(focus_named(w) for w in before)
                if name:
                    found.append((name, m.start()))
            continue
        at: int | None = m.start("a") if m.group("a") is not None else m.start("c")
        while at is not None:
            hit = focus_target(body, at, known_head)
            if hit is None:
                break
            found.append((hit[0], m.start()))
            # A chained target (round 1): "focus moves to Cancel, and then to Choose another
            # file" lands on both, so every target of the chain is read, not the first alone.
            chain = re.match(FOCUS_CHAIN_RE, body[hit[1] :])
            at = hit[1] + chain.end() if chain else None
    return found


def focus_target(body: str, at: int, known_head: re.Pattern[str]) -> tuple[str, int] | None:
    """The focus target at `at`: a known control read whole, or an unknown Title-case name read
    as its word (an article skipped), with the offset its name ends at; None for no target."""
    words = list(re.finditer(r"\S+", body[at:]))[:3]
    if words and words[0].group(0).lower() in ("the", "a", "an", "its", "their"):
        words = words[1:]
    else:
        words = words[:1]
    for w in [None, *words]:
        pos = at if w is None else at + w.start()
        pos += 1 if body[pos : pos + 1] in '"“[' else 0
        k = known_head.match(body, pos)
        if k:
            return k.group(0).lower(), k.end()
        if w is not None and focus_named(w.group(0)):
            return focus_named(w.group(0)), at + w.end()
    return None


def focus_text(text: str) -> str:
    """A clause as the focus claims read it: plain() but with quoted copy kept, so a quoted
    control name ('focus moves to "Retry"') is still a target."""
    text = re.sub(MARKER_RE, " ", text)
    for pattern in EXIT_BLANK:
        text = re.sub(pattern, lambda m: " " * len(m.group(0)), text)
    return text.replace("`", "")


def focus_named(word: str) -> str:
    """A focus target's word as an unknown control's name ("Import", "[Retry]", '"Import"'), or
    "" for a word that names none (lower case, a pronoun, a frame name)."""
    w = word.strip("`\"“”'[]()*.,;:")
    if not w or not w[0].isupper() or re.match(r"SCR-\d", w):
        return ""
    return w.lower()


def focus_problem(
    text: str, line: str, forced: bool, own_focus: str | None = None, frame: str | None = None
) -> str | None:
    """S20: on a rejection or a refusal, a focus claim names Choose another file, unless its
    clause names the frame whose focus the control is (a frame's own focus is its row's clause,
    or a pair §7 allows it: FOCUS_PAIRS). Any other target, a name the tool never knew, fails."""
    ctx = (
        forced
        or re.search(REJECTION_CTX_RE, plain(text))
        or re.search(REJECTION_CTX_RE, plain(line))
    )
    if not ctx:
        return None
    frames = set(re.findall(FRAME_NAME_RE, line))
    own = own_focus
    if own is None and len(frames) == 1:
        frame = frames.pop()
        if frame in KIND:
            own = FOCUS.get(frame, FOCUS.get(KIND[frame][0], ""))
    allowed = {c.lower() for c in FOCUS_PAIRS.get(frame or "", ())}
    ftext = focus_text(text)
    for control, at in focus_claims(ftext):
        if own is not None:
            if control != own.lower() and control not in allowed:
                return control
            continue
        if control == "choose another file":
            continue
        rule = FOCUS_EXCEPT.get(control)
        if rule and re.search(rule, clause_of(ftext, at)):
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
# Everywhere else in the prose (fold 4): an Import verb said to stay, remain, sit or be offered in a
# footer, whatever stands before it (a negator's reach or a ` · ` separator), is the same claim.
STAY_RE = (
    r"(?i)\b(?:stay(?:s|ed)?|remain(?:s|ed)?|sits?|(?:is|are|be|being) (?:still )?offered)\b"
    r"(?:\s+\w+){0,3}?\s+(?:in|on) (?:the|its|a) (?:dialog's )?footer\b"
)


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
        allowed = FOCUS_PAIRS.get(ctx.get("name", ""))
        for control, _ in focus_claims(focus_text(text)):
            if allowed is not None and control.lower() not in {c.lower() for c in allowed}:
                return fail("export-focus", f"{where}: focus on {control!r}, not a pair §7 allows")
            if not re.search(r"(?<!\w)" + re.escape(control.lower()) + r"(?!\w)", rest):
                return fail(
                    "export-focus", f"{where}: focus on {control!r}, a control it never draws"
                )
    if prose:
        presence = PRESENCE_RE if sub in ("6", "6.1") else STAY_RE
        for m in re.finditer(IMPORT_VERB_RE, body):
            if not negated(body, m.start()) and re.search(presence, own_clause(body, m.start())):
                return fail("import-verb", f"{where}: an Import verb drawn in place: {text[:60]!r}")
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
    if early and (claims(CREATE_RE, work, post=True) or active_create(work)):
        return fail("created-early", f"{where}: something exists before the send: {text[:60]!r}")
    kept = (
        (kind in NOTHING_KINDS | {"cancelled", "unconfirmed"})
        if not prose
        else refusal or sub in REFUSAL_SUBS or bool(re.search(REFUSED_RE, body))
    )
    if (kept and claims(KEEP_RE, work)) or claims(KEEP_ALWAYS_RE, work):
        return fail("partial", f"{where}: something of a refused file is kept: {text[:60]!r}")
    if prose:
        found = confirm_footer_problem(body)
        if found:
            return fail("confirm-footer", f"{where}: the budget confirm's control {found!r}")
    return unit_gate_2(text, body, ctx, facts, prose)


def active_create(text: str) -> bool:
    """An active create (CREATE_ACTIVE_RE), no negator governing it, its clause naming a
    client-side maker or a moment before the send (CREATE_EARLY_CUE_RE) and not the send."""
    for m in re.finditer(CREATE_ACTIVE_RE, text):
        if negated(text, m.start()):
            continue
        a, b = clause_bounds(text, m.start(), NEG_SPLIT_RE)
        own = text[own_start(text, a, m.start()) : b]
        if re.search(CREATE_EARLY_CUE_RE, own) and not re.search(POST_SEND_RE, own):
            return True
    return False


def confirm_footer_problem(body: str) -> str | None:
    """A sentence naming the budget confirm and a footer slot: every capitalised word after the
    slot word in its clause is one of the confirm's own names (CONFIRM_NAMES_OK), so a footer
    verb the confirm never draws ("Continue", "Proceed") fails."""
    if not re.search(CONFIRM_RE, body):
        return None
    for m in re.finditer(CONFIRM_SLOT_RE, body):
        _a, b = clause_bounds(body, m.start())
        for w in re.finditer(r"(?<![\w-])[A-Z][\w-]*", body[m.end() : b]):
            if w.group(0) not in CONFIRM_NAMES_OK:
                return w.group(0)
    return None


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
    unneg = re.sub(NOT_ACCEPTED_RE, lambda m: "_" * len(m.group(0)), text)
    for m in re.finditer(pattern, text):
        if negated(unneg, m.start()):
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
    control = focus_problem(text, line, forced, ctx.get("focus"), ctx.get("name"))
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
        "name": name,
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
    # A comment runs to its first `-->` or `--!>` across lines (re.DOTALL), or to the end of the
    # text when it never closes, so a multi-line or unclosed comment is read whole and fails.
    for m in re.finditer(r"<!--.*?(?:--!?>|\Z)", spec, re.DOTALL):
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
    """A4: a line cite to a document the tool does not pin (E15-D08 and E15-D05 are named only)."""
    for m in re.finditer(r"`([A-Za-z][A-Za-z0-9]*):(\d+)(?:–\d+)?`", spec):
        if m.group(1) not in KNOWN_KEYS:
            return m.group(0)
    pending = re.search(r"\bD0[58]:\d+", spec)
    return pending.group(0) if pending else None


def sha_problems(spec: str) -> list[str]:
    """A4: every commit id is a pinned merge's, each printed as often as the tool
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


def focus_pairs_line() -> str:
    """§7's line of the allowed focus pairs, rendered from FOCUS_PAIRS."""
    pairs = "; ".join(f"`{name}` on {' or '.join(c)}" for name, c in FOCUS_PAIRS.items())
    return (
        "**The focus pairs, stated once (S20).** On these five frames focus lands only on the "
        f"controls named here, the frame's own first: {pairs}. A focus claim on any other control "
        "of these frames fails."
    )


def focus_pairs_gates(spec: str) -> list[str]:
    """§7 carries the focus pairs' line byte for byte, once (S20's allowed pairs)."""
    line = focus_pairs_line()
    n = section(spec, 7, 8).split("\n").count(line)
    if n != 1:
        return [fail("focus-pairs", f"§7 carries the focus pairs' line {n} times, once pinned")]
    return []


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
        for cite in ("`14:632`", "`14:633`", "`14:640`"):
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
# Default-deny (fold 4): a unit that carries a decision or a row status in any word, any case, is
# pinned whole; the word list only widens the pin, the pin decides what a unit may say. A unit whose
# status word is deleted or swapped for a word the list lacks drops out, so its pin reads "gone".
STATUS_BEARING_RE = (
    r"(?i)\bpropos\w*|\brul(?:ed|ing|ings)\b|\bpending\b|\bowner approval\b|\bappl(?:ied|ies)\b"
    r"|\bmerg(?:e|ed|es)\b|\bsettled\b|\bdone\b|\bclosed\b|\blanded\b|\bfinal\w*|\bagreed\b"
    r"|\bapprov\w*|\baccept\w*|\badopt\w*|\bconfirmed\b|\bdecided\b|\bin force\b|\bsigned off\b"
    # Lens round 1: "shipped" and "in `main`" restate a PROPOSED item as merged.
    r"|\bship\w*|\bin\s+`?(?:origin/)?main`?(?!\w)"
)
# Sections pinned whole for the status pin, every unit of them (§10's and §11's A-rows, §12's rows
# and hand-offs, the BQ table and its lines), whatever words they use.
STATUS_WHOLE_RE = r"§1[012](?:\.\d+)?|The questions \(BQ-"
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


def pin_selected(spec: str, select: str, headings: bool, whole: str = "") -> list[Unit]:
    return [
        u
        for u in pin_units(spec)
        if re.search(select, u[2])
        or (headings and u[1] == "heading")
        or (whole and re.match(whole, u[0]))
    ]


def render_pins(spec: str, select: str, headings: bool = False, whole: str = "") -> str:
    """The pinned table as `--repin-security` / `--repin-status` print it: a `§ section` line per
    section, an `@ place` line per unit, its text wrapped at spaces on lines indented two spaces
    (joined with one space, the lines are the unit again)."""
    lines: list[str] = []
    last = ""
    for section, where, text in pin_selected(spec, select, headings, whole):
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


def pin_gate(spec: str, select: str, table: str, headings: bool, whole: str = "") -> str | None:
    """Every selected unit equals its pinned entry, in order: the first unit that is new,
    changed, moved or duplicated, or a pinned unit gone, named with its own place."""
    have, want = pin_selected(spec, select, headings, whole), pin_rows(table)
    for op, i1, _i2, j1, j2 in difflib.SequenceMatcher(
        None, want, have, autojunk=False
    ).get_opcodes():
        if op == "equal":
            continue
        places = {u[:2] for u in have[j1:j2]}
        if op == "delete" or (op == "replace" and want[i1][:2] not in places):
            pin = want[i1]
            return f"{pin[0]}{PIN_SEP}{pin[1]}: a pinned unit is gone: {pin[2][:60]!r}"
        got = have[j1]
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
    found = pin_gate(spec, STATUS_BEARING_RE, STATUS_PIN_TXT, False, STATUS_WHOLE_RE)
    if found:
        return [fail("status-pin", f"a ruling or a settled state (STATUS_PIN_TXT): {found}")]
    return []


# ---- the whole text, pinned block by block, default-deny (the lens round 1 ruling) -------------
# The vocabulary gates above are the first line; this is the backstop. EVERY Markdown block of the
# spec is pinned in RULED_PIN_TXT: a heading line; a run of non-blank lines (a paragraph, a list,
# a table, each whole); a fenced block, fence to fence, verbatim (its columns are content). A block
# is keyed by its heading path (each heading of the path, its occurrence `#n`) and ¶k, its place
# under that heading (the heading is ¶0); it carries its kind, the blank lines before it and its
# lines, each whitespace-normalised (a table's rule line its dashes as three; a fenced line
# verbatim, trailing blanks aside), so a re-padded table holds and a re-broken line does not.
# `--repin-ruled` is the ONLY writer (it rewrites RULED_PIN_TXT at the end of this file and prints
# the diff for review); `--check` never re-pins.
# A block that is changed, soft-wrapped, grown by a line (added), moved, duplicated, deleted or
# new (unpinned), a new heading and a blank-line change (a squeeze or an added blank) FAIL
# `text-pin` by location (the spec's line, the heading path and ¶k). Precedence: the pin FAILs
# only when no other gate FAILs; beside another gate's FAIL it is printed on a NOTE line, so one
# wrong form reads as one FAIL and the pin still names where it is.
TEXT_PATH_SEP = " › "
TEXT_PIN_WIDTH = 96
TEXT_KINDS = ("heading", "paragraph", "list", "table", "fence", "end")
QUOTES3 = '"' * 3  # spelled so, the table's own delimiters appear in this file once each
TEXT_PIN_BEGIN = "RULED_PIN_TXT = r" + QUOTES3
TEXT_PIN_END = QUOTES3 + "  # end of RULED_PIN_TXT"
TEXT_PIN_NOTES: list[str] = []


class DocBlock(NamedTuple):
    path: str  # the heading path, `#n` its occurrence
    para: int  # ¶k under that heading (the heading is ¶0)
    kind: str  # heading, paragraph, list, table, fence, end
    gap: int  # the blank lines before it
    text: str  # its lines, normalised, joined by "\n"
    line: int  # its first line in the spec (0 for a pinned entry)

    @property
    def where(self) -> str:
        """The block's place as a FAIL names it: its heading's number (or its first 40
        characters), that heading's occurrence and ¶k; the full path is the pin's key."""
        name, _, occ = self.path.rpartition("#")
        last = name.split(TEXT_PATH_SEP)[-1]
        num = re.match(r"(\d+(?:\.\d+)*)\.? ", last)
        return f"{'§' + num.group(1) if num else last[:40]}#{occ} ¶{self.para}"


def rule_line(line: str) -> str:
    """A table's rule line with each cell's dashes as three, its colons kept: a re-padded table
    (Prettier's widths) holds; an alignment change does not."""
    if not re.fullmatch(r"\|[ :|-]+\|", line):
        return line
    cells_ = [c.strip() for c in line.strip("|").split("|")]
    return "| " + " | ".join(re.sub(r"-+", "---", c) for c in cells_) + " |"


def doc_blocks(spec: str) -> list[DocBlock]:
    """Every block of the spec in order, then an `end` block holding the trailing blank lines."""
    lines = spec.split("\n")
    out: list[DocBlock] = []
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    path, para, gap, i = "(top)#1", 0, 0, 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            gap, i = gap + 1, i + 1
            continue
        start = i
        head = re.match(r"^(#{1,6}) (.*)$", raw)
        if raw.lstrip().startswith(("```", "~~~")):
            fence = raw.lstrip()[:3]
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(fence):
                i += 1
            i = min(i + 1, len(lines))
            kind, text = "fence", "\n".join(ln.rstrip() for ln in lines[start:i])
        elif head:
            i += 1
            level, name = len(head.group(1)), one_space(head.group(2))
            stack = [(lv, x) for lv, x in stack if lv < level] + [(level, name)]
            joined = TEXT_PATH_SEP.join(x for _lv, x in stack)
            seen[joined] = seen.get(joined, 0) + 1
            path, para = f"{joined}#{seen[joined]}", -1
            kind, text = "heading", one_space(raw)
        else:
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"^#{1,6} ", lines[i])
                and not lines[i].lstrip().startswith(("```", "~~~"))
            ):
                i += 1
            run = [rule_line(one_space(ln)) for ln in lines[start:i]]
            if all(x.startswith("|") for x in run):
                kind = "table"
            elif re.match(r"^(?:[-*+] |\d+\. )", run[0]):
                kind = "list"
            else:
                kind = "paragraph"
            text = "\n".join(run)
        para += 1
        out.append(DocBlock(path, para, kind, gap, text, start + 1))
        gap = 0
    out.append(DocBlock("(end)#1", 0, "end", gap, "", len(lines)))
    return out


def pin_wrap(lead: str, line: str, where: str) -> list[str]:
    """One normalised line wrapped at spaces: the first part after `lead`, a continuation
    indented three spaces; joined with one space, the parts are the line again."""
    parts = textwrap.wrap(line, TEXT_PIN_WIDTH, break_long_words=False, break_on_hyphens=False)
    if " ".join(parts) != line:
        raise SystemExit(f"--repin-ruled: a line does not survive the wrap ({where})")
    return [lead + parts[0], *("   " + p for p in parts[1:])]


def render_text_pins(spec: str) -> str:
    """RULED_PIN_TXT as `--repin-ruled` writes it: a `§ path` line (wrapped) where the heading
    path changes, an `@ ¶k ‖ kind ‖ gap` line per block, then each of its lines wrapped at
    spaces, indented two spaces and a continuation three; a fenced line is JSON, verbatim."""
    out: list[str] = []
    last = ""
    for b in doc_blocks(spec):
        if b.path != last:
            out += pin_wrap("§ ", b.path, b.where)
            last = b.path
        out.append(f"@ ¶{b.para}{PIN_SEP}{b.kind}{PIN_SEP}{b.gap}")
        for ln in b.text.split("\n") if b.text else []:
            if b.kind == "fence":
                out.append("  " + json.dumps(ln, ensure_ascii=False))
            else:
                out += pin_wrap("  ", ln, b.where)
    return "\n".join(out) + "\n"


def text_pin_rows(table: str) -> list[DocBlock] | None:
    """RULED_PIN_TXT parsed, in order; None when it does not parse."""
    rows: list[DocBlock] = []
    path: list[str] = []
    head: list[str] = []
    body: list[str] = []

    def flush() -> bool:
        if not head:
            return True
        if len(head) != 3 or not head[0].startswith("¶") or head[1] not in TEXT_KINDS:
            return False
        try:
            para, gap = int(head[0][1:]), int(head[2])
        except ValueError:
            return False
        rows.append(DocBlock(" ".join(path), para, head[1], gap, "\n".join(body), 0))
        return True

    for line in table.split("\n"):
        if not line:
            continue
        if line.startswith("§ "):
            if not flush():
                return None
            path, head, body = [line[2:]], [], []
        elif line.startswith("   ") and path and not head:
            path.append(line[3:])
        elif line.startswith("@ ") and path:
            if not flush():
                return None
            head, body = line[2:].split(PIN_SEP), []
        elif line.startswith("   ") and body and head[1] != "fence":
            body[-1] += " " + line[3:]
        elif line.startswith("  ") and head:
            try:
                body.append(json.loads(line[2:]) if head[1] == "fence" else line[2:])
            except json.JSONDecodeError:
                return None
        else:
            return None
    return rows if flush() and rows else None


def text_changed(was: str, now: str) -> str:
    """How a pinned block changed: soft-wrapped, a line added, a line removed, lines reordered or
    a line edited (its changed span shown)."""
    a, b = was.split("\n"), now.split("\n")
    if a != b and " ".join(a) == " ".join(b):
        return "soft-wrapped (its words unchanged, its lines re-broken)"
    ops = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()]
    edits = [o for o in ops if o[0] != "equal"]
    tag, i1, _i2, j1, _j2 = edits[0]
    if sorted(a) == sorted(b):
        return f"lines reordered at {b[j1][:50]!r}"
    if len(edits) == 1 and tag == "insert":
        return f"a line added {b[j1][:50]!r}"
    if len(edits) == 1 and tag == "delete":
        return f"a line removed {a[i1][:50]!r}"
    old, new = (a[i1] if i1 < len(a) else ""), (b[j1] if j1 < len(b) else "")
    k = 0
    while k < min(len(old), len(new)) and old[k] == new[k]:
        k += 1
    lead = max(0, k - 16)
    return f"changed from {old[lead : lead + 60]!r} to {new[lead : lead + 60]!r}"


def text_pin_problems(want: list[DocBlock], have: list[DocBlock]) -> list[str]:
    """The spec's blocks against their pins, each FAIL named by its location (the spec's line,
    the heading path and ¶k): changed, soft-wrapped, a line added, moved, duplicated, deleted,
    unpinned (a new block), a new heading, a blank-line change."""
    count_w = Counter(b.text for b in want)
    count_h = Counter(b.text for b in have)
    paths_w = {b.path for b in want}
    bad: list[tuple[int, str]] = []
    gone: list[int] = []
    added: list[int] = []
    paired: dict[int, int] = {}
    key = [(b.kind, b.text) for b in want], [(b.kind, b.text) for b in have]
    match = difflib.SequenceMatcher(None, key[0], key[1], autojunk=False)
    for op, i1, i2, j1, j2 in match.get_opcodes():
        if op == "equal":
            for w, h in zip(want[i1:i2], have[j1:j2], strict=True):
                if w.gap != h.gap:
                    what = "squeezed" if h.gap < w.gap else "added"
                    msg = f"blank lines before it {w.gap} → {h.gap} ({what}): {h.text[:50]!r}"
                    bad.append((h.line, f"E15-D09.md:{h.line} {h.where}: {msg}"))
                elif w.path != h.path and w.kind != "end":
                    msg = f"moved from {w.where}: {h.text[:50]!r}"
                    bad.append((h.line, f"E15-D09.md:{h.line} {h.where}: {msg}"))
            continue
        gone += range(i1, i2)
        added += range(j1, j2)
        if op == "replace":
            paired.update(zip(range(j1, j2), range(i1, i2), strict=False))
    left = {i: want[i].text for i in gone}
    for j in added:
        h = have[j]
        shown = h.text.replace("\n", " ")[:50]
        moved = next((i for i in gone if i in left and left[i] == h.text), None)
        squeezed = next(
            (
                i
                for i in gone
                if i + 1 < len(want)
                and i in left
                and (i + 1) in left
                and h.text == want[i].text + "\n" + want[i + 1].text
            ),
            None,
        )
        if h.kind == "heading" and h.path not in paths_w:
            if moved is not None:
                del left[moved]
            msg = f"a new heading {shown!r}"
        elif squeezed is not None:
            del left[squeezed], left[squeezed + 1]
            msg = f"a blank line squeezed: {want[squeezed].where} runs into the block after it"
        elif moved is not None and count_h[h.text] <= count_w[h.text]:
            del left[moved]
            msg = f"moved from {want[moved].where} {shown!r}"
        elif count_w[h.text] and count_h[h.text] > count_w[h.text]:
            once = next(w.where for w in want if w.text == h.text)
            msg = f"duplicated (pinned at {once}) {shown!r}"
        elif j in paired and paired[j] in left and want[paired[j]].kind == h.kind:
            msg = text_changed(left.pop(paired[j]), h.text)
        else:
            msg = f"not pinned (a new block) {shown!r}"
        bad.append((h.line, f"E15-D09.md:{h.line} {h.where}: {msg}"))
    for i in gone:
        if i in left:
            w = want[i]
            msg = f"E15-D09.md {w.where}: a pinned block is deleted {w.text[:50]!r}"
            bad.append((10**9 + i, msg))
    return [m for _n, m in sorted(bad, key=lambda x: x[0])]


# The spec holds no fenced block, so the self-test probes the fence path on a small document of
# its own: pinned and parsed back it holds, and each verbatim change inside the fence FAILs once.
FENCE_PROBE = (
    "# 1. Probe\n\nA sketch follows.\n\n```text\n  [ Import… ]   [ Cancel ]\n"
    "| not | a table |\n```\n\nAfter it.\n"
)
FENCE_PROBE_CUTS = (
    ("a run of spaces inside a line", "]   [ Cancel", "] [ Cancel", "changed from"),
    ("a line's indent", "\n  [ Import", "\n[ Import", "changed from"),
    (
        "a doubled space in a `|` line",
        "| not | a table |\n",
        "| not |  a table |\n",
        "changed from",
    ),
    ("a line removed", "| not | a table |\n", "", "a line removed"),
    ("a line added", "| not | a table |\n", "| not | a table |\n  Esc\n", "a line added"),
)


def fence_pin_probe() -> list[str]:
    """The fence path of the whole-text pin on FENCE_PROBE: one `fence` block, verbatim (its
    indent and inner spaces kept, a `|` line never a table), round-trips through the pin with no
    FAIL, and each FENCE_PROBE_CUTS change FAILs once, by location, with its kind."""
    pins = text_pin_rows(render_text_pins(FENCE_PROBE))
    if not pins:
        return ["self-test fence probe: its pin does not parse"]
    have = doc_blocks(FENCE_PROBE)
    fences = [b for b in have if b.kind == "fence"]
    if len(fences) != 1 or "\n  [ Import… ]   [ Cancel ]\n" not in fences[0].text:
        return [f"self-test fence probe: not one verbatim fence block: {fences[:1]}"]
    bad = [
        f"self-test fence probe: unchanged FAILs {p[:60]!r}" for p in text_pin_problems(pins, have)
    ]
    for name, old, new, says in FENCE_PROBE_CUTS:
        cut = FENCE_PROBE.replace(old, new, 1)
        got = text_pin_problems(pins, doc_blocks(cut))
        if cut == FENCE_PROBE or len(got) != 1 or says not in got[0] or "§1#1 ¶2" not in got[0]:
            bad.append(f"self-test fence probe {name}: expected one {says!r} at §1#1 ¶2, got {got}")
    return bad


def text_pin_gate(spec: str, table: str) -> list[str]:
    """Every block of the spec equals its pin, in order (default-deny): the FAILs by location."""
    pinned = text_pin_rows(table)
    if not pinned:
        return ["RULED_PIN_TXT is empty or does not parse; run --repin-ruled"]
    return text_pin_problems(pinned, doc_blocks(spec))


def repin_table(name: str, table: str) -> int:
    """`--repin-security` / `--repin-status`, their table's only writer: `name` rewritten in this
    file from the current text, the diff printed for review."""
    src = TOOL.read_text(encoding="utf-8")
    begin = f"\n{name} = r{QUOTES3}\n"
    start = src.find(begin)
    end = src.find(f"\n{QUOTES3}", start + len(begin))
    if start < 0 or end < 0 or src.count(begin) != 1:
        print(f"--repin: no {name} block in this file")
        return 1
    if QUOTES3 in table:
        print(f"--repin: a unit cannot sit in {name}'s raw string; nothing written")
        return 1
    old = src[start + len(begin) : end]
    if old == table:
        print(f"--repin: {name} already holds the text; nothing written")
        return 0
    TOOL.write_text(src[: start + len(begin)] + table + src[end:], encoding="utf-8")
    diff = difflib.unified_diff(
        old.split("\n"), table.split("\n"), f"{name} (was)", f"{name} (now)", lineterm=""
    )
    print("\n".join(diff))
    print(f"--repin: {name} rewritten; review the diff, then commit")
    return 0


def repin_ruled(spec: str) -> int:
    """`--repin-ruled`, the table's only writer: RULED_PIN_TXT rewritten from the current spec in
    this file, the diff printed for review (exit 0; nothing written when the table holds)."""
    src = TOOL.read_text(encoding="utf-8")
    start = src.rfind(TEXT_PIN_BEGIN)
    end = src.find(TEXT_PIN_END, start)
    if start < 0 or end < 0 or src.count(TEXT_PIN_BEGIN) != 1:
        print("--repin-ruled: no RULED_PIN_TXT block in this file")
        return 1
    new_table = "\n" + render_text_pins(spec)
    if QUOTES3 in new_table or "\\\n" in new_table:
        print("--repin-ruled: a block cannot sit in the raw string; nothing written")
        return 1
    old_table = src[start + len(TEXT_PIN_BEGIN) : end]
    if old_table == new_table:
        print("--repin-ruled: RULED_PIN_TXT already holds the text; nothing written")
        return 0
    TOOL.write_text(src[: start + len(TEXT_PIN_BEGIN)] + new_table + src[end:], encoding="utf-8")
    diff = difflib.unified_diff(
        old_table.split("\n"),
        new_table.split("\n"),
        "RULED_PIN_TXT (was)",
        "RULED_PIN_TXT (now)",
        lineterm="",
    )
    print("\n".join(diff))
    rows_ = text_pin_rows(new_table) or []
    print(f"--repin-ruled: {len(rows_)} blocks pinned; review the diff, then commit")
    return 0


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
    bad += reconcile_gates() + pinned_gates(spec) + keyboard_gates(spec) + focus_pairs_gates(spec)
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
    held = text_pin_gate(spec, RULED_PIN_TXT)
    TEXT_PIN_NOTES[:] = held if bad else []
    if held and not bad:
        more = f" (+{len(held) - 1} more)" if len(held) > 1 else ""
        bad.append(fail("text-pin", f"the whole text (RULED_PIN_TXT): {held[0]}{more}"))
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
        + fold4_mutations()
        + fold5_mutations()
        + fold_r1_mutations()
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
        ("cite-range", sub("`22:21402–21423`", "`22:21402–100192`"), "[cite-range]", None),
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
        ("a-row-14", sec_fn(11, lambda s: s.replace("`14:632`", "14:628")), "[a-row-14]", 11),
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


def prose_add(head: str, words: str) -> Callable[[str], str]:
    """Append `words` to the first prose line under the heading that starts with `head`."""

    def apply(s: str) -> str:
        lines = s.split("\n")
        at = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
        if at is None:
            return s
        for i in range(at + 1, len(lines)):
            if lines[i] and not lines[i].startswith(("#", "|", "-", "<")):
                lines[i] = lines[i].rstrip() + " " + words
                return "\n".join(lines)
        return s

    return apply


def fold4_mutations() -> list[Mutation]:
    """The delta check of fold r3, one mutation per finding form: the lens's words, then two
    variants each. P: a status word deleted or swapped for a word the list lacks (the default-deny
    status pin); K: a refusal synonym or a keep form with no keep verb (S11); F: an Import verb said
    to stay in a footer in §3.5, §4.4 and §4.5 (S5); C: a focus claim beside §7's pairs (S20)."""
    copy_ready = "Copy-ready for the catalogue's owner, PROPOSED"
    hand_off = "Each row is a PROPOSED hand-off"
    s35, s44, s45 = "### 3.5 ", "### 4.4 ", "### 4.5 "
    rl, eg, ev, ef, ec = (
        "SCR-026/refused-limit",
        "SCR-025/export-preparing",
        "SCR-025/export-preview",
        "SCR-025/export-failed",
        "SCR-025/export-cancelled",
    )
    pairs = "`SCR-025/export-preparing` on Cancel or the title"
    pin, part, verb = "[status-pin]", "[partial]", "[import-verb]"
    status = [
        ("P1-delete-11", sub(copy_ready, copy_ready[:-10]), pin),
        ("P1-merged-11", sub(copy_ready, copy_ready[:-8] + "merged"), pin),
        ("P1-delete-12", sub(hand_off, "Each row is a hand-off"), pin),
        ("P1-merged-12", sub(hand_off, "Each row is a merged hand-off"), pin),
        ("P1-done-12", sub(hand_off, "Each row is a done hand-off"), pin),
        ("P1-closed-12", sub(hand_off, "Each row is a closed hand-off"), pin),
        ("P1-pending-12", sub(hand_off, "Each row is a pending hand-off"), pin),
        ("P1-landed-12", sub(hand_off, "Each row is a landed hand-off"), pin),
        (
            "P1-delete-prose",
            sub(
                "**The check before the preview (PROPOSED).**",
                "**The check before the preview.**",
            ),
            pin,
        ),
        ("P1-swap-case", sub("(PROPOSED; no event fires", "(Official; no event fires"), pin),
    ]
    keep = [
        (
            "K1-fails",
            prose_add(s35, "Whenever it fails, the layouts that passed stay in your workspaces."),
            part,
        ),
        ("K1-bare", prose_add(s44, "The layouts that passed stay in your workspaces."), part),
        (
            "K1-turned-down",
            prose_add(s45, "When the file is turned down, the valid layouts are kept."),
            part,
        ),
        (
            "K1-declined",
            prose_add(
                "## 7. ", "When the file is declined, the layouts remain in your workspaces."
            ),
            part,
        ),
        (
            "K1-left-case",
            prose_add("### 1.2 ", "IF THE CHECK FAILED, THE PANES ARE LEFT IN YOUR WORKSPACES."),
            part,
        ),
        (
            "K1-not-accepted",
            prose_add("### 3.3 ", "Once the file is not accepted, the valid layouts remain."),
            part,
        ),
    ]
    footer = [
        ("F1-35", prose_add(s35, "Import anyway stays in the footer."), verb),
        ("F1-44", prose_add(s44, "Import anyway stays in the footer."), verb),
        ("F1-45", prose_add(s45, "Import anyway stays in the footer."), verb),
        (
            "F1-separator",
            prose_add(s44, "Nothing is announced · and Import anyway stays in the footer."),
            verb,
        ),
        (
            "F1-remains",
            prose_add(s35, "Nothing moves, and Import as new workspace remains in the footer."),
            verb,
        ),
        ("F1-offered-case", prose_add(s45, "IMPORT ANYWAY IS STILL OFFERED IN THE FOOTER."), verb),
    ]
    focus = [
        ("C1-limit", cell_add(rl, 2, "and focus lands on Try again"), "[rejection-focus]"),
        ("C1-preparing", cell_add(eg, 2, "and focus lands on Download file"), "[export-focus]"),
        ("C1-failed", cell_add(ef, 2, "and focus lands on the title"), "[export-focus]"),
        ("C1-cancelled", cell_add(ec, 2, "and focus lands on Try again"), "[export-focus]"),
        ("C1-preview-case", cell_add(ev, 2, "AND FOCUS MOVES TO CLOSE"), "[export-focus]"),
        ("C1-producer", cell_add(ef, 1, "and Download file takes focus"), "[export-focus]"),
        ("C2-pair-changed", sub(pairs, pairs.replace("the title", "Close")), "[focus-pairs]"),
        ("C2-pair-gone", sub(focus_pairs_line() + "\n", ""), "[focus-pairs]"),
    ]
    return [(n, fn, e, None) for n, fn, e in status + keep + footer + focus]


def fold5_mutations() -> list[Mutation]:
    """The fold 5 check, default-deny focus (S20): a focus claim on a control the tool never
    knew ("Import", "Retry") fails on refused-limit's row, on D09-D28, on the other refusals and
    on an export frame. The lens's three words, then two variants each (case, quoted, a control
    noun, the "takes focus" form)."""
    rl, rs, rv, ru, ef = (
        "SCR-026/refused-limit",
        "SCR-026/refused-server",
        "SCR-026/rejected-version-newer",
        "SCR-026/refused-unconfirmed",
        "SCR-025/export-failed",
    )
    d28 = "and focus lands on Cancel, because another file"
    rf, xf = "[rejection-focus]", "[export-focus]"

    def d28_add(words: str) -> Callable[[str], str]:
        return sub(d28, d28.replace("Cancel,", f"Cancel {words},"))

    focus = [
        ("F5-limit-moves", cell_add(rl, 2, "and focus moves to Import"), rf),
        ("F5-limit-lands", cell_add(rl, 2, "and focus lands on Import"), rf),
        ("F5-limit-retry", cell_add(rl, 2, "and focus lands on Retry"), rf),
        ("F5-limit-case", cell_add(rl, 2, "AND FOCUS MOVES TO IMPORT"), rf),
        ("F5-limit-quoted", cell_add(rl, 1, 'and focus moves to "Retry"'), rf),
        ("F5-d28-moves", d28_add("and focus moves to Import"), rf),
        ("F5-d28-lands", d28_add("and focus lands on Import"), rf),
        ("F5-d28-retry", d28_add("and focus lands on Retry"), rf),
        ("F5-d28-noun", d28_add("and the Retry button is focused"), rf),
        ("F5-server", cell_add(rs, 2, "and Import takes focus"), rf),
        ("F5-rejection", cell_add(rv, 2, "and focus lands on the Retry button"), rf),
        ("F5-unconfirmed", cell_add(ru, 2, "and focus moves to [Retry]"), rf),
        ("F5-export", cell_add(ef, 2, "and focus moves to Retry"), xf),
        ("F5-export-case", cell_add(ef, 2, "AND RETRY TAKES FOCUS"), xf),
    ]
    return [(n, fn, e, None) for n, fn, e in focus]


def block_move(line: str, before: str, keep: bool = False) -> Callable[[str], str]:
    """The prose block whose line starts with `line` moved (or, with `keep`, copied) to sit right
    before the line that starts with `before`, a blank line after it."""

    def fn(s: str) -> str:
        lines = s.split("\n")
        at = next((i for i, ln in enumerate(lines) if ln.startswith(line)), None)
        if at is None:
            return s
        text = lines[at]
        if not keep:
            del lines[at : at + 2]
        to = next((i for i, ln in enumerate(lines) if ln.startswith(before)), None)
        if to is None:
            return s
        lines[to:to] = [text, ""]
        return "\n".join(lines)

    return fn


def block_drop(line: str) -> Callable[[str], str]:
    """The prose block whose line starts with `line` deleted, with the blank line after it."""
    return lambda s: re.sub(rf"(?m)^{re.escape(line)}.*\n\n", "", s, count=1)


def block_before(line: str, text: str) -> Callable[[str], str]:
    """`text` and a blank line inserted right before the line that starts with `line`."""
    return lambda s: re.sub(
        rf"(?m)^(?={re.escape(line)})", text.replace("\\", r"\\") + "\n\n", s, count=1
    )


def fold_r1_mutations() -> list[Mutation]:
    """The lens round 1 fold. TP: the whole-text pin, one mutation per FAIL kind on a block no
    other gate reads whole (the expected kind after `||`; `||NOTE ` when a first-line gate reports
    and the pin names the kind on its NOTE line). R1: the lens's escapes (M1's "shipped" and "in
    `main`" forms, M2's exit forms and the active create). R2: twelve paraphrases of ruled
    properties, each caught by its own gate (a vocabulary gate first)."""
    p348 = "Each row is a frame of §2.1, in the order the flow reaches it;"
    p835 = "Token audit: the boards PR reads every shape's fills"
    p811 = "**Motion** is E15-D14's (out of scope)."
    p1130 = "**Heuristic evaluation `(heuristic)`**"
    kept = "**Nothing is kept.** Cancel during the check"
    order = "**The order (BQ-5 RULED; Condition 1).**"
    rl = "SCR-026/refused-limit"
    pin, ex, ce = "[text-pin]", "[exit-gated]", "[created-early]"
    stp = "[status-pin]"
    active = "The worker creates the new workspace as soon as the file passes the size step."
    out: list[tuple[str, Callable[[str], str], str]] = [
        # TP — each FAIL kind of the whole-text pin, by location
        (
            "TP-changed",
            sub("in the order the flow reaches it", "in the order the flow meets it"),
            pin + "||changed from",
        ),
        ("TP-soft-wrapped", sub(p348, p348 + "\n"), "[wrap]||NOTE soft-wrapped"),
        (
            "TP-added",
            row_fn(rf"^{re.escape(p835)}.*$", lambda ln: ln + "\n- A note."),
            pin + "||a line added",
        ),
        ("TP-moved", block_move(p835, p811), pin + "||moved from"),
        ("TP-duplicated", block_move(p835, p811, keep=True), pin + "||duplicated"),
        ("TP-deleted", block_drop(p835), pin + "||is deleted"),
        ("TP-unpinned", block_before(p811, "This paragraph is new."), pin + "||not pinned"),
        ("TP-new-heading", block_before(p835, "#### 8 Notes"), pin + "||a new heading"),
        ("TP-squeeze-table", sub("\n\n" + p835, "\n" + p835), pin + "||a blank line squeezed"),
        ("TP-squeeze-heading", sub("\n\n" + p348, "\n" + p348), pin + "||(squeezed)"),
        ("TP-blank-added", sub("\n\n" + p348, "\n\n\n" + p348), pin + "||(added)"),
        # R1 — the lens's escapes: M1's five "shipped" / "in `main`" forms, M2's exit forms and the
        # active create in the BQ-5 RULED paragraph and in "Nothing is kept"
        ("R1-main-paren", line_add(p1130, "(D09-G1; already in `main`, C-6.1)"), stp),
        ("R1-shipped", line_add(p811, "The atomic send has shipped."), stp + "||NOTE changed from"),
        ("R1-in-main", line_add(p1130, "D09-G1 is in `main`."), stp),
        ("R1-ships", line_add(p811, "D09-G13 ships with E15-S07."), stp),
        ("R1-in-main-bare", line_add(p1130, "The atomic import is already in main."), stp),
        ("R1-exit-removed", line_add(p811, "Cancel is removed until the message ends."), ex),
        ("R1-exit-not-drawn", line_add(p811, "During the check the × is not drawn."), ex),
        (
            "R1-exit-swallowed",
            line_add(p811, "Esc is swallowed by the worker."),
            ex + "||NOTE changed",
        ),
        ("R1-create-order", line_add(order, active), ce),
        ("R1-create-kept", line_add(kept, active), ce),
        # R2 — twelve paraphrases of ruled properties, of this fold's own
        (
            "R2-limit-chain",
            cell_add(rl, 2, "and focus moves to Cancel, and then to Choose another file"),
            "[rejection-focus]",
        ),
        (
            "R2-confirm-continue",
            line_add(p811, "The budget confirm's footer reads Cancel · Continue."),
            "[confirm-footer]",
        ),
        (
            "R2-confirm-proceed",
            line_add(p811, "The stacked confirm's primary button is Proceed."),
            "[confirm-footer]",
        ),
        (
            "R2-browser-stores",
            line_add(p811, "The browser stores a draft layout once the file is picked."),
            ce,
        ),
        (
            "R2-exit-removing",
            line_add(p811, "While the file uploads the dialog keeps removing Close."),
            ex,
        ),
        (
            "R2-exit-not-drawn-until",
            line_add(p811, "Choose another file is not drawn until the server answers."),
            ex,
        ),
        (
            "R2-partial",
            line_add(p811, "A refused file keeps the layouts that passed."),
            "[partial]",
        ),
        (
            "R2-recheck",
            line_add(p811, "The server skips its re-check for a file the preview passed."),
            "[server-recheck]",
        ),
        ("R2-share", line_add(p811, "The file is safe to share with anyone."), "[share-claim]"),
        ("R2-export-locked", line_add(p811, "Export… is locked for a Viewer."), "[export-gated]"),
        (
            "R2-version-compare",
            line_add(p811, "The app version is compared against the file's version."),
            "[version-field]",
        ),
        (
            "R2-markup",
            line_add(p811, "Markdown in a workspace name renders as a link."),
            "[untrusted-markup]",
        ),
    ]
    return [(n, fn, e, None) for n, fn, e in out]


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
        # `code||words`: the one FAIL also says `words`; `code||NOTE words`: a first-line gate
        # reports and the whole-text pin names the same fault on its NOTE line.
        code, _, says = expect.partition("||")
        note = says.removeprefix("NOTE ") if says.startswith("NOTE ") else ""
        if len(new) != 1 or not new[0].startswith(code):
            bad.append(f"self-test {name}: expected one new FAIL {code!r}, got {new[:3]}")
        elif note and not any(note in n for n in TEXT_PIN_NOTES):
            bad.append(f"self-test {name}: the whole-text pin's NOTE lacks {note!r}")
        elif says and not note and says not in new[0]:
            bad.append(f"self-test {name}: the FAIL does not say {says!r}: {new[0][:80]!r}")
    bad += fence_pin_probe()
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
        "sections; every marker printed, parsed, re-derived and counted; the whole text, block "
        "by block (RULED_PIN_TXT)"
    )
    out.append("\n## 5. Gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out += [f"NOTE the whole-text pin also holds: {w}" for w in TEXT_PIN_NOTES[:3]]
    out.append("\n## 6. Counts: " + json.dumps(numbers_, ensure_ascii=False))
    return out


def repin_cites(spec: str) -> int:
    """`--repin-cites`, the cite table's only writer: each CITED_TABLE needle found once at another
    line moves there, in the table and in every cite of the spec and of this file that starts on it
    (a range's end moves by the same count); the moves are printed for review (exit 1 when a
    needle is gone or twice)."""
    t = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
    moves: dict[tuple[str, int], int] = {}
    for doc, line_s, want in rows(CITED_TABLE, 2):
        line = int(line_s)
        at = [i + 1 for i, ln in enumerate(t[doc].split("\n")) if want in ln]
        if t[doc].count(want) != 1:
            print(f"--repin-cites: `{doc}:{line}` {want[:40]!r} is gone or twice; nothing written")
            return 1
        shift = sum(POINTER in ln for ln in t[doc].split("\n")[: line - 1]) if doc == "14" else 0
        if at[0] not in (line, line + shift):
            moves[(doc, line)] = at[0]
    if not moves:
        print("--repin-cites: every cite is at its line; nothing written")
        return 0
    src = TOOL.read_text(encoding="utf-8")
    head, rest = src.split('\nCITED_TABLE = """\n', 1)
    table, tail = rest.split('\n"""\n', 1)
    for (doc, line), new in sorted(moves.items()):
        print(f"`{doc}:{line}` -> `{doc}:{new}`")
    table = re.sub(  # one pass, so a row moved onto another row's old line is never moved twice
        r"(?m)^(\w+) \| (\d+) \| ",
        lambda m: f"{m[1]} | {moves.get((m[1], int(m[2])), int(m[2]))} | ",
        table,
    )

    def move(m: re.Match[str]) -> str:
        doc, a, b = m.group(1), int(m.group(2)), m.group(3)
        new = moves.get((doc, a), a)
        end = f"{EN_DASH}{int(b) + new - a}" if b else ""
        return f"`{doc}:{new}{end}`"

    new_spec = re.sub(CITE_RE, move, spec)
    head, tail = re.sub(CITE_RE, move, head), re.sub(CITE_RE, move, tail)  # the tool's own cites
    TOOL.write_text(head + '\nCITED_TABLE = """\n' + table + '\n"""\n' + tail, encoding="utf-8")
    SPEC.write_text(new_spec, encoding="utf-8")
    n = sum(1 for m in re.finditer(CITE_RE, spec) if (m.group(1), int(m.group(2))) in moves)
    print(f"--repin-cites: {len(moves)} needles moved, {n} cites in the spec; review the diff")
    return 0


def main(argv: list[str]) -> int:
    spec = SPEC.read_text(encoding="utf-8")
    if "--repin-ruled" in argv:
        return repin_ruled(spec)
    if "--repin-cites" in argv:
        return repin_cites(spec)
    if "--repin-security" in argv:
        return repin_table("SEC_PIN_TXT", render_pins(spec, SEC_BEARING_RE))
    if "--repin-status" in argv:
        return repin_table(
            "STATUS_PIN_TXT", render_pins(spec, STATUS_BEARING_RE, False, STATUS_WHOLE_RE)
        )
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
            "pins": {
                "sec_units": len(pin_rows(SEC_PIN_TXT)),
                "status_units": len(pin_rows(STATUS_PIN_TXT)),
                "text_blocks": len(text_pin_rows(RULED_PIN_TXT) or []),
                "text_kinds": dict(Counter(b.kind for b in text_pin_rows(RULED_PIN_TXT) or [])),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if bad or st_bad else 0


# --- the default-deny pins: `--repin-security` / `--repin-status` write them; a reviewer reads ---
# --- them here, and `--check` never re-pins ------------------------------------------------------
SEC_PIN_TXT = r"""
§ E15-D09 — SCR-026 workspace import / exp
@ prose
  Export… from SCR-025 and the workspace menus, the pre-export preview with what is included
  and, first-class, what is excluded, the file name with its format version, the completion
@ prose
  sharing beyond the file
@ prose
  E15-D08 (#4503, Export… in SCR-025's Share section) merged at
  `fb1b48041ae0a12638beacae6a61854833c5cc4d`: named only, never cited by line
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
  the Included list names only what `WorkspaceBundle` holds (`22:21402–21423`)
@ row BQ-2 · col 3
  the import's trust note is `D02:513` verbatim: "A workspace file never carries credentials
  or account bindings. Importing creates a new workspace and changes nothing else."
@ row BQ-2 · col 3
  the sharing claim in `22:12846`'s description is never written anywhere (its G-row names
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
  SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's `[⋯]` (`D03:384`) and
  the rail's workspace menu (`D02:511`)
@ row BQ-7 · col 3
  and one CMP-043 `md` dialog with the Included and Excluded lists built from the fetched
  bundle
@ row BQ-7 · col 3
  Export… is a read (`22:12843`), never gated (a read): T1 for every session, view-as
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
  environment, an alert or rule binding, P&L, a position or an order (`22:21402–21423`
@ row Exfiltration: the file leaves the machin · col 2
  the preview names what travels and, first-class, the Excluded list, so a mistake in the
  build is visible rather than hidden
@ row Injection through content: every string  · col 1
  Injection through content: every string from the file is untrusted
@ row Injection through content: every string  · col 2
  text only: never markup, never a link, never interpreted (SR-127, `04:967`
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
  the sharing claim of `22:12846`'s description is written nowhere in this spec (D09-G11).
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
  Export… opened from SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's
  `[⋯]` (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored workspace
@ row `SCR-025/export-entry` · col 3
  access: Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace menu
@ row `SCR-025/export-entry` · col 3
  Components: a CMP-041 item of `kind` action in the tab's `[⋯]` and in the rail's workspace
  menu, with no glyph and no shortcut · in SCR-025's Share section a CMP-001 `secondary`
  button, which E15-D08 draws (merged, `fb1b4804`)
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
  SCR-025's Share section is E15-D02 §5.10's, its hi-fi E15-D08's (merged, `fb1b4804`)
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
  so it names only what `WorkspaceBundle` holds (`22:21402–21423`): no density, which no
  workspace stores (the third deviation).
@ prose
  The Excluded list is BQ-2's sentence, byte for byte, drawn as a list of its five clauses
  and first-class: the same type, weight and column width as the Included list, never a
  footnote, a hint or a tooltip.
@ prose
  a pane's settings never hold credentials, account ids or user ids, `22:20031`, `21:5079`
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
  Every name in the lists is rendered as text, never as markup (SR-127, `04:967`).
@ prose
  and because the file is the bytes as fetched (§2.4), the client declines to save a bundle
  that carries one, or a pane setting the import would drop as account-scoped (§4.2's third
  row): `SCR-025/export-failed` with "Couldn't prepare the file: it holds something this
  preview can't show. Nothing was exported." `WorkspaceBundle` and `ChartTemplateInput` are
  not closed today (D09-G4)
@ prose
  - A limit an import would refuse (the file's size, its nesting or its count of values, or
  its presets: an export carries every live preset, while an import takes at most 200 <!--
  audit:contract.presets_max=200 --> of them, `22:21419–21423`) keeps Download file and adds
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
  within the 500 <!-- audit:contract.parse_ms=500 --> ms of `14:637` from flashing the bar
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
  and layout content is never logged (`21:5079`), and E15-S07 logs its export requests
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
  `14:632–633`'s "remap to the user's default account" gets a PROPOSED A-row (§11).
@ prose
  DL-17).** Every string the table takes from the file (kind names, layout names, symbols,
  intervals, drawing labels) is a text node and nothing else: never markup, never a link,
  never interpreted (SR-127, `04:967`
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
  settings that never hold account ids (`22:20031`)
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
  workspace and layout content is never logged (`21:5079`), and E15-S07 logs its export
  requests without file contents (`BL:1136`).
@ prose
  **Nothing kept.** When a refusal shows, the worker's text and document and the file's
  handle are dropped: nothing reaches the workspace store, the browser's storage, a cache or
  a log, and Choose another file starts from nothing (BQ-5 RULED).
@ prose
  `422 validation_failed` when the server's own re-check refuses what the browser passed
  (`22:19819`): "Nothing was imported." then "The server didn't accept this file: `{key}`
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
  view-as included, its preview, its Download file and its completion alike (`22:12843`
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
  Two do not: SCR-089 accepts or skips each rule on its own (`14:1999`) where a workspace is
  whole or nothing, and a rule bundle's version and account references follow E36's
  contract, not `WorkspaceBundle`'s.
§ §12
@ row D09-G1 · col 2
  and an import built in the client from `createWorkspace` and then `createLayout` for each
  layout is not atomic (`FL:171`), the partial import the ticket forbids (`11:2871`)
@ row D09-G3 · col 2
  Account-scoped elements: no bundle schema has an account field and `PaneConfig` forbids
  account ids (`22:20031`), so a strict server refuses a file that carries one whole (C-6.3
@ row D09-G3 · col 2
  `14:633`'s "the user's default account" names nothing a workspace has
@ row D09-G3 · col 3
  the contract's rule: the server drops an account-scoped setting at export and again at
  import and names it in its answer (E15-S07, `BL:1136`), or it refuses the whole file, in
  which case the preview's Drop row is a prediction and the outcome is
  `SCR-026/refused-server`
@ row D09-G3 · col 3
  no default account for a workspace
@ row D09-G10 · col 2
  `workspace.exported` sits on SCR-025's Audit line (`14:621`), while E15-D01's locked list
  keeps layout events analytics, never audit (`D02:84`), and E15-X01 asks that the export be
  audited (`BL:721`)
@ row D09-G11 · col 2
  The data class and the sharing claim: `exportWorkspace`'s description makes the sharing
  claim (`22:12846`), while `21:5079` classes the pane columns P0 and E15-X01 classes the
  file user-confidential (`BL:721`)
@ row D09-G11 · col 3
  `22`'s description drops the sharing claim and names the class
@ row D09-G15 · col 2
  An export carries the caller's whole live preset library, at most 500 and never truncated
  (`22:21417–21419`), not only the presets this workspace's panes use, while the Included
  list's "3 indicator presets" reads as the workspace's own
@ row D09-G15 · col 3
  the owner (#2701) chooses: the Included list says "all 3 of your indicator presets", or
  the bundle carries only the presets the panes reference (`22`'s owner)
@ row D09-C3 · col 2
  the ticket's Included list names densities, which `WorkspaceBundle` does not hold
  (`22:21402–21423`
@ row D09-C5 · col 2
  E15-D02's sentence "Never included: API keys or tokens, account or trade-group ids, user
  ids, P&L figures, positions or orders." (`D02:511`) is extended by BQ-2's to name
  credentials, accounts, the environment binding and the alert and rule bindings (AC 1): an
  extension, not a contradiction, and E15-D02's sentence is never shown on a frame
@ row D09-C8 · col 2
  `14:632`'s "accounts remapped", `14:633`'s "inaccessible account references remap to the
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
  importer's own libraries (`22:21422–21425`, counted against the 500-preset cap): is the
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
  **SCR-025 (`14:627`)** is E15-D08's surface (merged, `fb1b4804`, named only): of its four
  items this spec draws only Export… in the Share section, part of the first item's sharing
  (§2), and the export dialog it opens
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
@ prose
  every decision PROPOSED unless RULED (6396085915)
@ prose
  boards PENDING (§0: 10 <!-- audit:boards=10 --> boards, 2 <!-- audit:light_twins=2 --> of
  them light twins, inside the cap of ≤ 10 boards with light twins ≤ 1/3
@ prose
  **Owner approval pending (#2701)** (agent-delivery adaptations, owner decision
  2026-09-25): the owner's `approved` comment or the merge stands in for the ticket's CDO
  and Security-engineer sign-offs (§13).
@ prose
  **Method:** a desk spec over the merged E15-D01, E15-D02, E15-D03 and E15-D06 text and
  boards, E05-D02 slice 4 and E09-D09
@ prose
  **Penpot page:** `E15-D09 Workspace import and export` · id pending (the boards PR pins it
@ prose
  **Start.** `blocked_by` E15-D02 (#248): Done
@ prose
  text merged in #4192 at `1044c4f602eff6ae1a2cf42201ab398f6c4234d1`, boards in #4408 at
  `7be6eac6a705cf24ba534ce4f7d31349a1e29932`
@ prose
  its input E15-D01 merged in #4079 at `ed8a22246263ace73f39e4434e6d5f57b1a857bd`.
@ prose
  Merged siblings, cited as merged text: E15-D03 (#4478 at
  `c4989493461ec6b6d22b9254633452a6362b750e`) and E15-D06 (#4470 at
  `6e2c1211fc5f4675457d57011a346642f92710c5`)
@ prose
  E15-D04 (#4454 at `c73aec08246f06d28c70e8b959c658bc1a0c4d09`), the dock system, is pinned
  because the ruling names it, and nothing of it is reused or cited here
@ prose
  E15-D08 (#4503, Export… in SCR-025's Share section) merged at
  `fb1b48041ae0a12638beacae6a61854833c5cc4d`: named only, never cited by line
@ prose
  E15-D05 (#4507, the SCR-011 rail) merged at `013562636a339ab32c80d257b9d1f8cef8e64422`:
  named only, never cited by line
@ prose
  Merged upstream: E15-D01 (`D01:39`)
@ prose
  PROPOSED, D09-G5)
@ prose
  The caps on a string from the file: names 40 <!-- audit:contract.name_max=40 -->
  (`22:19831`), symbols 20 <!-- audit:contract.symbol_max=20 --> (`22:20057`), panel kinds
  32 <!-- audit:contract.kind_max=32 --> (PROPOSED: `PaneKind` has no length bound,
  `22:19971`, so the setting keys' cap of `22:20041` stands in
@ prose
  D09-G5), drawing labels 120 <!-- audit:contract.label_max=120 --> (`21:3302`), keys 64
  <!-- audit:design.key_cap=64 --> and file names 40 <!-- audit:design.file_cap=40 -->
  (PROPOSED).
@ prose
  the spec is this file, beside its E15 siblings (`14:639`), with its gate tool (BQ-1
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
@ prose
  Status: **done** = specified here · **heuristic-only** = by the adaptation · **routed** =
  its owner named (a drawing's owner is the boards PR, §0) · **text pending** = its section
  is still a placeholder (the tool fails this word once no placeholder is left).
@ row AC-1 · col 3
  `SCR-025/export-preview`, `SCR-025/export-done` (§2.1)
@ row AC-1 · col 3
  the Excluded sentence byte for byte (BQ-2 RULED)
@ row AC-1 · col 4
  done
@ row AC-2 · col 2
  "A newer-version file is refused, not partially applied": both versions named, no option
  that applies part of the file
@ row AC-2 · col 3
  BQ-4 and BQ-11 RULED
@ row AC-2 · col 4
  done
@ row AC-3 · col 4
  done
@ row AC-4 · col 3
  §4.2 rows 3–4 (BQ-3 RULED: dropped and listed)
@ row AC-4 · col 4
  done
@ row AC-5 · col 4
  done
@ row AC-6 · col 4
  done
@ row DL-1 · col 3
  BQ-7 RULED)
@ row DL-1 · col 4
  done
@ row DL-2 · col 4
  done
@ row DL-3 · col 3
  `SCR-025/export-preview`, `SCR-025/export-done`
@ row DL-3 · col 4
  done
@ row DL-4 · col 3
  `SCR-025/export-done`
@ row DL-4 · col 3
  BQ-8 RULED
@ row DL-4 · col 4
  done
@ row DL-5 · col 3
  `SCR-025/export-done`
@ row DL-5 · col 4
  done
@ row DL-6 · col 4
  done
@ row DL-7 · col 4
  done
@ row DL-8 · col 4
  done
@ row DL-9 · col 4
  done
@ row DL-10 · col 4
  done
@ row DL-11 · col 4
  done
@ row DL-12 · col 3
  BQ-2 RULED, owner approval pending (#2701)
@ row DL-12 · col 4
  done
@ row DL-13 · col 4
  done
@ row DL-14 · col 4
  done
@ row DL-15 · col 4
  done
@ row DL-16 · col 4
  done
@ row DL-17 · col 4
  done
@ row DL-18 · col 4
  done
@ row DL-19 · col 4
  done
@ row DL-20 · col 4
  done
@ row DL-21 · col 4
  done
@ row DoD-3 · col 4
  done
@ row DoD-4 · col 4
  done
@ row DoD-6 · col 2
  The copy signed off on the trust claims
@ row DoD-6 · col 3
  the owner's `approved` (#2701)
@ row DoD-7 · col 4
  done
@ row DoD-8 · col 4
  done
@ row DoD-9 · col 2
  The spec merged
@ row DoD-9 · col 2
  CMP-067's Storybook list agreed
@ row DoD-10 · col 4
  done
§ The questions (BQ-1…BQ-16) — RULED by th
@ heading
  The questions (BQ-1…BQ-16) — RULED by the orchestrator: 6396085915, on the BQ comment
  6396029607
@ row # · col 1
  #
@ row # · col 2
  Question
@ row # · col 3
  Built here (the ruled outcome)
@ row # · col 4
  Status
@ row BQ-1 · col 1
  BQ-1
@ row BQ-1 · col 2
  the deliverable path, the branch, the Penpot page, the `14` / `15` edit set, the PR
@ row BQ-1 · col 3
  this file, `docs/design/E15/E15-D09.md`, and its tool `e15_d09_import_export_audit.py`
@ row BQ-1 · col 3
  the ticket's spec path and branch are the first two deviations
@ row BQ-1 · col 3
  the Penpot page `E15-D09 Workspace import and export`
@ row BQ-1 · col 3
  two content-only `14` pointer lines, after SCR-025's checklist (`14:627`) and SCR-026's
  (`14:640`), and PROPOSED A-rows for `14:632–633` and `14:640` (§11)
@ row BQ-1 · col 3
  no `15` edit
@ row BQ-1 · col 3
  A-rows only (§10)
@ row BQ-1 · col 3
  the PR says `Refs #363` and `Partial:`, never a closing keyword
@ row BQ-1 · col 4
  RULED (6396085915)
@ row BQ-2 · col 1
  BQ-2
@ row BQ-2 · col 2
  the trust claims, word for word
@ row BQ-2 · col 3
  the Excluded list, first-class and drawn as a list, in AC 1's words: "Never included:
  credentials — API keys or tokens; accounts, trade-group and user ids; environment binding
  (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."
@ row BQ-2 · col 3
  a C-row to `D02:511`, an extension and not a contradiction
@ row BQ-2 · col 3
  the Included list names only what `WorkspaceBundle` holds (`22:21402–21423`)
@ row BQ-2 · col 3
  the import's trust note is `D02:513` verbatim: "A workspace file never carries credentials
  or account bindings. Importing creates a new workspace and changes nothing else."
@ row BQ-2 · col 3
  the sharing claim in `22:12846`'s description is never written anywhere (its G-row names
  it without repeating it)
@ row BQ-2 · col 3
  the tool gates both sentences byte for byte on every frame that shows them
@ row BQ-2 · col 3
  owner approval pending (#2701)
@ row BQ-2 · col 4
  RULED (6396085915)
@ row BQ-2 · col 4
  owner approval pending (#2701)
@ row BQ-3 · col 1
  BQ-3
@ row BQ-3 · col 2
  account-scoped elements on import
@ row BQ-3 · col 3
  dropped and listed, never remapped, and no account the importer cannot see is ever named
  in the preview, the report or a reason: its row reads "workspaces never carry account
  bindings" (§4.2 row 3)
@ row BQ-3 · col 3
  the word "Remap" is kept for the one true remap, the Positions pane that shows your own
  accounts (§4.2 row 4)
@ row BQ-3 · col 3
  `14:632–633` and the checklist item of `14:640` get PROPOSED A-rows (§11)
@ row BQ-3 · col 3
  E15-S07 receives D09-G1…G8, G13 and G14 by hand-off row (§12)
@ row BQ-3 · col 4
  RULED (6396085915)
@ row BQ-3 · col 4
  owner approval pending (#2701)
@ row BQ-4 · col 1
  BQ-4
@ row BQ-4 · col 2
  the version rule
@ row BQ-4 · col 3
  a newer file refused with both versions and the constructive second sentence, no Import
  verb (`SCR-026/rejected-version-newer`)
@ row BQ-4 · col 3
  an older compatible file migrated forward with "Migrated from format version 1 to 2."
  (E15-S07's rule, `SCR-026/preview-migrated`)
@ row BQ-4 · col 3
  an older unsupported file refused with both versions (`SCR-026/rejected-version-older`,
  the ticket's `version-older`)
@ row BQ-4 · col 3
  the comparison on `schema_version`, never an app version
@ row BQ-4 · col 4
  RULED (6396085915)
@ row BQ-4 · col 4
  owner approval pending (#2701)
@ row BQ-5 · col 1
  BQ-5
@ row BQ-5 · col 2
  size, shape and the refused parse
@ row BQ-5 · col 3
  the five check steps in order, size → parse depth / node count → schema → version →
  per-pane registry → preview
@ row BQ-5 · col 3
  nothing is created before Import as new workspace and nothing kept after a refusal
@ row BQ-5 · col 3
  the limits in copy rendered from the tool's facts (the Fixture paragraph), the node count
  PROPOSED with D09-G5
@ row BQ-5 · col 3
  every refusal says "Nothing was imported."
@ row BQ-5 · col 4
  RULED (6396085915)
@ row BQ-6 · col 1
  BQ-6
@ row BQ-6 · col 2
  the panel budget on a valid file
@ row BQ-6 · col 3
  per layout, for the layout that opens: caught in the preview as the caption's last
  sentence and a warning line (`SCR-026/preview-over-budget`), then applied through
  US-LAY-001's CMP-044 confirm re-verbed "Import anyway", its Cancel focused
  (`SCR-026/budget-confirm`)
@ row BQ-6 · col 3
  a confirm, not a refusal, whose cancel fires `budget-exceeded`
@ row BQ-6 · col 4
  RULED (6396085915)
@ row BQ-7 · col 1
  BQ-7
@ row BQ-7 · col 2
  the export surface and Export…'s availability
@ row BQ-7 · col 3
  Export… in three places
@ row BQ-7 · col 3
  SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's `[⋯]` (`D03:384`) and
  the rail's workspace menu (`D02:511`)
@ row BQ-7 · col 3
  and one CMP-043 `md` dialog with the Included and Excluded lists built from the fetched
  bundle
@ row BQ-7 · col 3
  Export… is a read (`22:12843`), never gated (a read): T1 for every session, view-as
  included
@ row BQ-7 · col 3
  on the viewer's unsaved default it is an availability state (`D03:583`)
@ row BQ-7 · col 4
  RULED (6396085915)
@ row BQ-8 · col 1
  BQ-8
@ row BQ-8 · col 2
  the file name and the completion
@ row BQ-8 · col 3
  `<slug>.cv-workspace-v<schema_version>.json`, the slug the workspace name lower-cased,
  ASCII-folded, every other character a `-`, capped like a name (D09-G14)
@ row BQ-8 · col 3
  the fixture `scalping.cv-workspace-v1.json`
@ row BQ-8 · col 3
  a drawn completion step naming the saved file (`SCR-025/export-done`)
@ row BQ-8 · col 3
  a dismissed save sheet keeps the preview (`SCR-025/export-cancelled`)
@ row BQ-8 · col 4
  RULED (6396085915)
@ row BQ-9 · col 1
  BQ-9
@ row BQ-9 · col 2
  the import dialog
@ row BQ-9 · col 3
  CMP-043 `lg` with its steps in one chrome
@ row BQ-9 · col 3
  choose, validating, preview, the send, the report
@ row BQ-9 · col 3
  Choose file… a real button fronting the labelled native input
@ row BQ-9 · col 3
  the drop zone not a Tab stop
@ row BQ-9 · col 3
  a name clash disambiguated by the server (`D02:516`)
@ row BQ-9 · col 3
  Cancel, `Esc` and × before the send close the dialog with nothing imported
@ row BQ-9 · col 4
  RULED (6396085915)
@ row BQ-10 · col 1
  BQ-10
@ row BQ-10 · col 2
  the preview table
@ row BQ-10 · col 3
  CMP-049 table mode, the caption first with the counts
@ row BQ-10 · col 3
  the columns Item · Type · Action · Reason
@ row BQ-10 · col 3
  drops and remaps first, additions after
@ row BQ-10 · col 3
  exactly three Action words, each a word with a decorative glyph
@ row BQ-10 · col 3
  the unknown kinds by stored name with the ticket's reason
@ row BQ-10 · col 3
  strings from the file as text, capped (the Fixture paragraph
@ row BQ-10 · col 3
  the symbol cap is the fourth deviation)
@ row BQ-10 · col 4
  RULED (6396085915)
@ row BQ-11 · col 1
  BQ-11
@ row BQ-11 · col 2
  the rejection frames
@ row BQ-11 · col 3
  six CMP-027 `inline` frames, `live="polite"`, the dialog kept open with Choose another
  file focused beside its Cancel
@ row BQ-11 · col 3
  no Import verb on any of them (AC 2: omitted, never T2-locked)
@ row BQ-11 · col 3
  each names its problem and its limit and says "Nothing was imported."
@ row BQ-11 · col 3
  each fires one `layout.import_rejected{reason}`
@ row BQ-11 · col 4
  RULED (6396085915)
@ row BQ-12 · col 1
  BQ-12
@ row BQ-12 · col 2
  the post-import report
@ row BQ-12 · col 3
  the dialog's final step, a `role="region"` named "Import report" with the table
  re-rendered (§4.3) and Copy report (CMP-033)
@ row BQ-12 · col 3
  it stays until Close and is never a toast
@ row BQ-12 · col 4
  RULED (6396085915)
@ row BQ-13 · col 1
  BQ-13
@ row BQ-13 · col 2
  the keyboard path and the tree
@ row BQ-13 · col 3
  Choose file… is a real `<button>` whose `Enter` or `Space` opens the OS picker
@ row BQ-13 · col 3
  the drop zone only adds to the input
@ row BQ-13 · col 3
  the table is one Tab stop read with its headers
@ row BQ-13 · col 3
  each announcement polite and once (§7)
@ row BQ-13 · col 4
  RULED (6396085915)
@ row BQ-14 · col 1
  BQ-14
@ row BQ-14 · col 2
  T2 per role, view-as first
@ row BQ-14 · col 3
  Import… is a write (`22:8682`): its legs in the server's order, view-as first
  (`rbac.view_as`), then the permission (`rbac.permission`), then the state
  (`workspace.limit.count`), keys as merged E15-D02 (`D02:655`) and E15-D03 (`D03:564`)
  carry them
@ row BQ-14 · col 3
  Export… is never gated
@ row BQ-14 · col 3
  a rejected file never T2-locks Import because the verb is absent
@ row BQ-14 · col 3
  an absence is never a lock and validity is never a lock
@ row BQ-14 · col 3
  T2 is stated once (§6)
@ row BQ-14 · col 4
  RULED (6396085915)
@ row BQ-15 · col 1
  BQ-15
@ row BQ-15 · col 2
  the boards under the cap
@ row BQ-15 · col 3
  ten boards with at most three light twins
@ row BQ-15 · col 3
  two here (§0)
@ row BQ-15 · col 3
  every other frame not drawn, the text binding, drawn on request
@ row BQ-15 · col 4
  RULED (6396085915)
@ row BQ-16 · col 1
  BQ-16
@ row BQ-16 · col 2
  the gate tool, the mutation list and the G-rows
@ row BQ-16 · col 3
  the tool in E15-D08's form with D09's own row ids: per-frame gates over every row of every
  table and the prose, case-insensitive vocabulary lists, whole clauses
@ row BQ-16 · col 3
  S1–S20 each a `--self-test` mutation
@ row BQ-16 · col 3
  the G-rows D09-G1…G14 to `22`'s owner (`22` first, C-6.1)
@ row BQ-16 · col 4
  RULED (6396085915)
@ row Condition 1 · col 1
  Condition 1
@ row Condition 1 · col 2
  security
@ row Condition 1 · col 2
  every string from the file is untrusted
@ row Condition 1 · col 3
  every string from the file is untrusted: text only, never markup and never a link, capped
  with the cap stated, the malformed reason naming the key in mono, truncated
@ row Condition 1 · col 3
  the report echoes no raw file content beyond those capped names
@ row Condition 1 · col 3
  the client's parse is a courtesy
@ row Condition 1 · col 3
  the server re-checks size, depth, nodes, schema and version (E15-S07) and
  `SCR-026/validating` says so
@ row Condition 1 · col 3
  a refused parse is never a partial import
@ row Condition 1 · col 3
  nothing is created before Import as new workspace and nothing kept after a refusal
@ row Condition 1 · col 4
  RULED (6396085915)
@ row Condition 1 · col 4
  binding on every frame
@ row Condition 2 · col 1
  Condition 2
@ row Condition 2 · col 2
  A1
@ row Condition 2 · col 2
  the T2 rule
@ row Condition 2 · col 3
  Import… is a write, its legs in the server's order, view-as first (`rbac.view_as`), then
  `rbac.permission`, then `workspace.limit.count`
@ row Condition 2 · col 3
  Export… is never gated
@ row Condition 2 · col 3
  a rejected file never T2-locks Import
@ row Condition 2 · col 3
  an absence is never a lock
@ row Condition 2 · col 3
  validity is never a lock
@ row Condition 2 · col 4
  RULED (6396085915)
@ row Condition 2 · col 4
  binding on every frame
@ row Condition 3 · col 1
  Condition 3
@ row Condition 3 · col 2
  A2
@ row Condition 3 · col 2
  the gates
@ row Condition 3 · col 3
  the tool reads every frame table row by row, every other table and the prose, with
  case-insensitive vocabulary lists (the gated-exit words, the environment words, the
  sharing claim, the markup and link words) against whole clauses, never first words
@ row Condition 3 · col 3
  one `--self-test` mutation per ruled sentence and per frame element, S1–S20 the minimum
@ row Condition 3 · col 4
  RULED (6396085915)
@ row Condition 3 · col 4
  binding from the first commit
@ row Condition 4 · col 1
  Condition 4
@ row Condition 4 · col 2
  A3 / A4
@ row Condition 4 · col 2
  the exits and honesty
@ row Condition 4 · col 3
  Cancel, Esc, ×, Close and Choose another file are never gated on any frame, view-as and
  the Viewer's included
@ row Condition 4 · col 3
  merged texts at their merge shas
@ row Condition 4 · col 3
  every departure a PROPOSED A, C or G-row
@ row Condition 4 · col 3
  "RULED" cites 6396085915
@ row Condition 4 · col 3
  no lane is an authority
@ row Condition 4 · col 4
  RULED (6396085915)
@ row Condition 4 · col 4
  binding on every frame
@ prose
  **Standing (binding on every section).** **A1** T2 is E09-D09's, stated once in §6:
  Import… is a write and its legs run view-as first
@ prose
  Export… is a read and never gated
@ prose
  a rejection, a refusal, an absence and form validity are never a lock.
@ prose
  **A2** every gate reads whole clauses with case-insensitive vocabulary lists, and every
  ruled sentence and frame element has its mutation.
@ prose
  **A3** the exits are never gated
@ prose
  Cancel, `Esc`, ×, Close and Choose another file, on every frame and for every session,
  view-as and the Viewer's included.
@ prose
  **A4** honesty: merged texts at their merge shas, E15-D08 by name only, every departure a
  PROPOSED A, C or G-row, and nothing measured, signed or drawn is claimed before it is.
@ prose
  16 <!-- audit:bq_rows=16 --> questions and 4 <!-- audit:conditions=4 --> conditions RULED.
§ §0
@ heading
  0. Boards (PENDING — the boards PR draws them)
@ prose
  The boards are drawn from this text in a second PR on the Penpot page `E15-D09 Workspace
  import and export` (id pending), named `E15-D09 / NN slug`, their frames named as in
  §2–§5, exported at 1:1 through `docs/design/_tools/penpot_export.py` to
  `docs/design/E15/img/`, with greyscale and deuteranopia renders through
  `docs/design/_tools/cvd_sim.py` for boards 03, 04 and 06 (the Add, Drop and Remap glyphs
  and the rejection colour).
@ prose
  Dark and comfortable unless the row says otherwise: ten boards, two of them light twins
  (BQ-15 RULED).
@ row 01 · col 3
  `SCR-025/export-preview`, `SCR-025/export-done`
@ row 01 · col 6
  pending
@ row 02 · col 6
  pending
@ row 03 · col 6
  pending
@ row 04 · col 6
  pending
@ row 05 · col 6
  pending
@ row 06 · col 6
  pending
@ row 07 · col 6
  pending
@ row 08 · col 6
  pending
@ row 09 · col 6
  pending
@ row 10 · col 6
  pending
@ prose
  drawn on request** (BQ-15 RULED): `SCR-025/export-preparing`, `SCR-025/export-failed`,
  `SCR-025/export-cancelled`, `SCR-025/export-reflow-200`, `SCR-026/drag-over`,
  `SCR-026/drag-over-rejected`, `SCR-026/creating`, `SCR-026/cancelled`, `SCR-026/compact`,
  `SCR-026/reflow-200`, `SCR-026/preview-migrated`, `SCR-026/rejected-nodes`,
  `SCR-026/refused-server`, `SCR-026/refused-unconfirmed`.
§ §1
@ prose
  Cited and never re-decided: each input below fixes something in this spec, and §2–§16 cite
  it rather than restate it. §1.2 states the trust boundary once and every frame of §2–§5
  applies it
@ prose
  §1.4 lists the decisions this spec takes on top of its inputs, each PROPOSED unless a
  ruling is named
@ prose
  the ruled answers are the questions table's (6396085915).
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
@ row E15-D03, merged in #4478: the T2 rule st · col 1
  E15-D03, merged in #4478: the T2 rule stated once
@ row D-15 and US-LAY-001's cost confirm: belo · col 3
  the budget line and the stacked confirm re-verbed Import anyway (BQ-6 RULED, §4.4)
@ row `22`: `exportWorkspace` is a read (`work · col 3
  Export… never gated (BQ-7 RULED)
@ row E05-D02 slice 4: H22, `Esc`, the scrim a · col 1
  E05-D02 slice 4: H22, `Esc`, the scrim and the outcome surface after a view is closed
@ row E05-D02 slice 4: H22, `Esc`, the scrim a · col 3
  the exits and the toasts after a closed view (§3.5, §7)
@ row E15-S07: the check order (size, the pars · col 3
  the limits, PROPOSED for `22` (D09-G5)
@ row E15-D06 D-9: a layout never stores an ac · col 3
  the account setting's Drop row (BQ-3 RULED, §4.4)
@ row The ticket: the six acceptance criteria, · col 1
  The ticket: the six acceptance criteria, the six rejection reasons, the 2 MB file checked
  within 500 ms in a worker, the security and accessibility notes
§ §1.2
@ prose
  Each of the ticket's four hazards has one rule here, and every frame of §2–§5 applies it.
@ row Exfiltration: the file leaves the machin · col 3
  `SCR-025/export-preview`, `SCR-025/export-done` (BQ-2 RULED
@ row Exfiltration: the file leaves the machin · col 3
  owner approval pending (#2701))
@ row Injection through content: every string  · col 2
  the same rule holds in the applied workspace, whose names the server sanitises again
  (`22:19819`)
@ prose
  **The server re-checks (Condition 1).** No guard in the browser replaces the server's own
  validation: the server re-checks size, depth, nodes, schema and version when the file is
  imported (E15-S07), refuses unknown fields on its write paths, fail closed, while the
  client ignores them (C-6.3
@ prose
  BQ-5 RULED).** No workspace, layout or pane exists before Import as new workspace is
  pressed on a preview
@ prose
  **What the user is told (BQ-2 RULED
@ prose
  owner approval pending (#2701)).** Two sentences carry the trust claims, each gated byte
  for byte wherever it shows: the Excluded list on the export and the trust note on the
  import (§9 holds both).
§ §1.3
@ prose
  a failure after the send has no partial frame, because the import is never partial
  (D09-G1), and its frame is the server's refusal, or, when no answer came, the frame that
  says the import could not be confirmed.
@ row 5 · col 3
  `SCR-025/export-done`
@ row 25 · col 2
  import: done, the report
§ §1.4
@ heading
  1.4 Decisions of this spec (PROPOSED unless RULED)
@ prose
  Each row is stated in full where it applies
@ prose
  a ruled question is the questions table's and is never repeated here.
@ row D09-D2 · col 2
  before the preview the client reads the fetched bundle with the import's own check: data
  the lists cannot show, or a setting the import would drop as account-scoped, fails the
  export closed
@ row D09-D18 · col 2
  when the view was closed during the send, a persistent `success` toast with View report,
  or a persistent `danger` toast with Review, carries the outcome, and an unanswered send a
  persistent `warning` toast with Review (D09-D33)
@ row D09-D33 · col 2
  after the view closed, a `warning` toast writes its words, never `e15.import.nothing`
§ §2
@ prose
  It sits in three places and opens one dialog (BQ-7 RULED, §2.2): a CMP-043
  `role="dialog"`, `size="md"`, at most 560 <!-- audit:contract.dialog_md_px=560 --> px wide
  (`15:466`), which calls `exportWorkspace` once, counts the Included list from the bundle
  it gets and saves that same bundle, so what the owner checks is what the file holds
  (`D02:511`
@ prose
  The trust copy is BQ-2's ruled text, owner approval pending (#2701), and the sharing claim
  in `exportWorkspace`'s description is written nowhere in this spec (D09-G11).
@ prose
  A decision that names no ruling is PROPOSED.
§ §2.1
@ row `SCR-025/export-entry` · col 2
  Export… opened from SCR-025's Share section (E15-D08, merged at `fb1b4804`), the tab's
  `[⋯]` (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored workspace
@ row `SCR-025/export-entry` · col 3
  Components: a CMP-041 item of `kind` action in the tab's `[⋯]` and in the rail's workspace
  menu, with no glyph and no shortcut · in SCR-025's Share section a CMP-001 `secondary`
  button, which E15-D08 draws (merged, `fb1b4804`)
@ row `SCR-025/export-unavailable` · col 3
  Components: the same CMP-041 item with its second line, which its `aria-describedby` names
  · no glyph · in SCR-025, the same CMP-001 `secondary` button with the line under it
  (E15-D08, merged)
@ row `SCR-025/export-preparing` · col 3
  Timing: the line shows only after the 150 ms show-delay BQ-9 rules for the import (§3.4),
  PROPOSED here for the export (D09-D9), so a quick answer goes straight to the preview ·
  Cancel ends the read and nothing is exported
@ row `SCR-025/export-preview` · col 3
  Components: CMP-043 `md` · two CMP-036 KeyValueRows in one `dl`, each with its lead-in as
  the term and its list as the value, a `ul` with one `li` per clause that keeps the
  clause's own punctuation · the caveat a plain line · CMP-001 `secondary` and `primary` ·
  CMP-028 `info` for unsaved changes and `warning` for an import limit, each only when it
  applies, `live="off"` (§2.3)
@ row `SCR-025/export-failed` · col 3
  Variants, PROPOSED, the same frame with its own sentence: a `403` or `404` from the read,
  "Couldn't prepare the file: this workspace can no longer be read. Nothing was exported." ·
  a bundle holding what the preview can't show (§2.3), "Couldn't prepare the file: it holds
  something this preview can't show. Nothing was exported." · a write that failed (§2.4),
  "Couldn't save the file. Nothing was exported."
@ row `SCR-025/export-done` · col 1
  `SCR-025/export-done`
@ row `SCR-025/export-done` · col 3
  done: CMP-028 `success` "Exported Scalping as scalping.cv-workspace-v1.json."
@ row `SCR-025/export-done` · col 5
  `e15.export.title` · `e15.export.close` · `e15.export.done` · `e15.export.excluded` ·
  `e15.export.close_button`
@ row `SCR-025/export-cancelled` · col 2
  the OS save sheet closed without saving (`FL:146`)
@ row `SCR-025/export-cancelled` · col 3
  the save sheet closed unsaved, the preview stays as it was and no event fires
§ §2.2
@ prose
  **Three places, one dialog (BQ-7 RULED).** Export… sits wherever a workspace is managed,
  and each place opens the same dialog on the workspace it belongs to:
@ row SCR-025's Share section · col 5
  E15-D08, merged at `fb1b4804`
@ prose
  SCR-025's Share section is E15-D02 §5.10's, its hi-fi E15-D08's (merged, `fb1b4804`)
@ prose
  this spec adds no shortcut and no palette command, and the three places are the ones BQ-7
  RULED names.
@ row Footer · col 3
  the done step's footer is Close alone
§ §2.3
@ prose
  **What the two lists say (BQ-2 RULED
@ prose
  owner approval pending (#2701)).** The Included list is counted from the fetched bundle,
  so it names only what `WorkspaceBundle` holds (`22:21402–21423`): no density, which no
  workspace stores (the third deviation).
@ prose
  **The check before the preview (PROPOSED).** The preview can vouch only for what it lists,
  so before it draws the lists the client reads the fetched bundle with the import's own
  check (§3's five steps, in the same worker as the import's, `14:637`), and the export
  never saves what the preview cannot show:
@ prose
  and because the file is the bytes as fetched (§2.4), the client declines to save a bundle
  that carries one, or a pane setting the import would drop as account-scoped (§4.2's third
  row): `SCR-025/export-failed` with "Couldn't prepare the file: it holds something this
  preview can't show. Nothing was exported." `WorkspaceBundle` and `ChartTemplateInput` are
  not closed today (D09-G4)
@ prose
  **Unsaved changes (PROPOSED).** `exportWorkspace` reads the store, so a layout's unsaved
  working copy and SCR-025's unsaved edits are not in the file.
@ prose
  **Anatomy and redlines (comfortable / compact).** The body of the preview, the done step
  and the failed step
@ row Completion line (the done step) · col 1
  Completion line (the done step)
§ §2.4
@ prose
  **The name (BQ-8 RULED
@ prose
  The slug, PROPOSED in full:
@ prose
  They are written whole or not at all (to a temporary file, then renamed), so a failed
  write leaves no partial file and turns the dialog to `SCR-025/export-failed` with
  "Couldn't save the file. Nothing was exported." (PROPOSED), whose Try again opens the
  sheet again.
@ prose
  A sheet closed unsaved returns to the preview as it was, `SCR-025/export-cancelled`:
  nothing saved and no event (`FL:146`).
@ prose
  the hand-off is the only answer the page gets there, so it counts as the save (PROPOSED
@ prose
  **The completion step (BQ-8 RULED).** When the write ends, the body changes in place
  (`SCR-025/export-done`): a CMP-028 `success` line, "Exported Scalping as
  scalping.cv-workspace-v1.json.", the file name in `type.num.sm` and selectable, then the
  Excluded list, unchanged, so the owner sees what the file leaves out as they send it on.
@ prose
  The press of Download file alone never fires it, nor does a sheet closed unsaved or a
  failure.
§ §2.5
@ row cancelled (`SCR-025/export-cancelled`) · col 2
  the save sheet closed unsaved
@ row done (`SCR-025/export-done`) · col 1
  done (`SCR-025/export-done`)
§ §3
@ prose
  SCR-026 is one CMP-043 `role="dialog"`, `size="lg"`, at most 960 <!--
  audit:contract.dialog_lg_px=960 --> px wide (`15:466`), because the preview's four columns
  need the width (BQ-9 RULED).
@ prose
  The trust note, `D02:513` verbatim, sits under the title from the first step to the send
  (BQ-2 RULED).
@ prose
  BQ-5 RULED).
@ prose
  §3.2 to §3.5 give each one its anatomy, redlines, tokens and focus, and a decision that
  names no ruling is PROPOSED.
§ §3.1
@ row `SCR-026/pick` · col 3
  a real `<button>` (CMP-001 `secondary`) fronting the labelled native `<input type="file">`
  (CMP-067, `accept=".json,application/json"`, `multiple` false), whose `Enter` or `Space`
  opens the OS picker
§ §3.2
@ prose
  **Entries (BQ-9 RULED).** Import… is an item of the tab strip's "+" menu, after New
  workspace… and Open workspace… (`D03:365`), and of the rail's workspace menu, where no
  merged text places it yet (BQ-9 RULED
@ prose
  no operation takes a bundle yet, `22:21419`), so §6's legs gate it, view-as first, with
  the keys merged E15-D02 and E15-D03 carry (`D02:655`
@ prose
  **One chrome, five steps (BQ-9 RULED).** The body changes with the step
@ row preview · col 2
  the migration or the budget line when one applies
@ row preview · col 2
  the clash line when one applies
@ row Card · col 3
  its top edge stays where it opened while the body grows, so the title and the zone never
  move under the pointer (PROPOSED)
@ row Trust note · col 3
  the dialog's `aria-describedby`, so a screen reader hears it as focus enters the dialog
  (PROPOSED)
@ prose
  **Focus and keys in the dialog (BQ-13 RULED
§ §3.3
@ prose
  **Choose file… (BQ-13 RULED
@ prose
  It fronts CMP-067's native `<input type="file">` (`15:690–696`), which carries
  `accept=".json,application/json"` and `multiple` false: the input is `hidden`, so it is
  out of the Tab order and out of the accessibility tree, the button's click opens it, and
  it stays labelled by the button (`aria-labelledby`), so the one control a keyboard or
  screen-reader user meets is the button and browse mode finds no second Choose file…
  (PROPOSED anatomy
@ prose
  The OS picker filters by `accept`
@ prose
  **The drop zone (BQ-9 RULED
@ prose
  Dropping two or more files reads none of them and changes nothing: the zone returns to
  rest and its drag-over words, "Drop one .json file", are announced once, politely
  (PROPOSED
@ row The zone · col 2
  CMP-067's drop target, a box with no role (PROPOSED: the label, the hint and the states
  are A-rows to CMP-067, §10)
@ row The zone · col 3
  a `border.hairline` 1 <!-- audit:redline.border.hairline=1 --> px solid edge, never
  dashed: `color.border.dashed` is not a shipped token (`15:695`) and E36-D03 re-bound it
  the same way (`E36D03:272`)
@ row File line · col 2
  the chosen file's name, once a file is picked or dropped (PROPOSED)
@ row Drag-over · col 4
  accept: edge `color.border.selected` on `color.surface.hover`
§ §3.4
@ prose
  **The order (BQ-5 RULED
@ row 1 · col 3
  a picked file's type is checked too, because `accept` only filters what the OS picker
  offers
@ row 1 · col 4
  2 <!-- audit:contract.size_mb=2 --> MB, E15-S07's default (`BL:1136`), PROPOSED for `22`
  (D09-G5)
@ row 2 · col 4
  10,000 <!-- audit:contract.nodes=10000 --> values (`BL:1136`), PROPOSED (D09-G5)
@ row 4 · col 3
  the file's `schema_version` (`22:21408`) against the format version this app reads (BQ-4
  RULED): newer is refused
@ prose
  BQ-9 RULED).** `SCR-026/validating` is CMP-023, determinate (`15:262–268`): its value
  moves a fifth at each step, and its value text, always shown, reads "Checking
  scalping.json… step 3 of 5" (`e15.import.checking`: `D02:515`'s words with the step
  added), the file's name capped at 40 <!-- audit:design.file_cap=40 --> characters as text.
@ prose
  A show-delay of 150 ms (BQ-9's default, ruled as proposed) keeps a file that validates
  within the 500 <!-- audit:contract.parse_ms=500 --> ms of `14:637` from flashing the bar
@ prose
  That departs from `D02:515`, which names them, and is a PROPOSED C-row (D09-C13).
@ prose
  **What is spoken (BQ-13 RULED
@ prose
  The worker reads the file as plain data and builds the preview only from the fields
  `WorkspaceBundle` names, so an unknown key, `__proto__` and `constructor` included, is
  never read into the app: the client ignores it, as C-6.3 asks of every client, and the
  server refuses it on its write path, fail closed (C-6.3
§ §3.5
@ prose
  **The send (BQ-9 RULED
@ prose
  done in the client as `createWorkspace` and then `createLayout` per layout, the import
  would not be atomic, `FL:171`, which is why no frame here shows a partial state).
@ prose
  CMP-001's buy and sell keep their label the same way, PROPOSED for this primary so the
  effect stays named while it runs).
@ prose
  After CMP-001's slow-path delay, "Still importing…" shows under the footer, end-aligned in
  `type.ui.caption` + `color.text.secondary`, and is spoken once, politely (PROPOSED copy,
  `e15.import.slow`).
@ prose
  **When the view was closed during the send (PROPOSED
@ prose
  H22's outcome surface, `S4:734`).** The new workspace still opens in a tab, and a
  persistent CMP-045 `success` toast writes the report's success line
  (`e15.import.report.done`) once into CMP-212's polite region, with the action View report
  (`e15.import.report.view`), which reopens SCR-026 at its report (§4.5)
@ prose
  A refusal that arrives after the view closed raises a persistent CMP-045 `danger` toast,
  "Nothing was imported." (`e15.import.nothing`), with the action Review
  (`e15.import.review`), which reopens SCR-026 at the refusal's frame (§5.1).
@ prose
  A send left unanswered after the view closed raises a persistent CMP-045 `warning` toast
  with `SCR-026/refused-unconfirmed`'s words, "We couldn't confirm the import. Check your
  workspaces before importing again." (`e15.import.refused.unconfirmed`), and the action
  Review, which reopens SCR-026 at that frame
@ prose
  No toast is the report: the report is the dialog's region (BQ-12 RULED).
@ row drag-over · col 2
  the zone's accept state (§3.3)
§ §4.1
@ row `SCR-026/preview` · col 3
  Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED)
@ row `SCR-026/preview-migrated` · col 3
  Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED)
@ row `SCR-026/preview-over-budget` · col 3
  Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED)
@ row `SCR-026/report` · col 3
  region: the dialog's final step, `role="region"` named "Import report", its heading
  `tabindex="-1"` focused on arrival, every line selectable
@ row `SCR-026/report` · col 3
  Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED)
@ row `SCR-026/report` · col 5
  `e15.import.report.heading` · `e15.import.report.done` · `e15.import.report.caption` ·
  `e15.import.report.copy` · `e15.import.report.copied` · `e15.import.report.close`
§ §4.4
@ prose
  **The table (BQ-10 RULED
@ prose
  a file holds at most 32 <!-- audit:contract.layouts_max=32 --> layouts of 16 <!--
  audit:contract.panes_max=16 --> panes each (PROPOSED: CMP-049's `virtualized` off here).
@ prose
  **The Action column (BQ-10 RULED
@ prose
  DoD-4).** Exactly three words, each after a decorative CMP-019 glyph in its own cell
  (`aria-hidden`, `15:225`): Add (`check`), Drop (`x-circle`, the PROPOSED glyph `15:307`
  registers) and Remap (`merge`, PROPOSED).
@ prose
  **Account-scoped elements (BQ-3 RULED
@ prose
  `14:632–633`'s "remap to the user's default account" gets a PROPOSED A-row (§11).
@ prose
  Each value is direction-isolated (`<bdi>`), and each control or bidirectional-formatting
  character in it (the set `22:19819–19824` makes the server strip from a name), and each
  character of the `Default_Ignorable_Code_Point` property, which would be invisible (§5.5),
  shows as a visible "�" instead of acting or hiding, so no file string can reorder the row
  around it or hide part of itself (PROPOSED).
@ prose
  **Striping, the header and the rows (PROPOSED A-row to CMP-049, §10).** Inside a dialog
  the table sits on `color.surface.overlay`, where CMP-049's panel stripes (odd
  `color.surface.canvas`, `15:524–531`) would read as holes, so the odd rows take
  `color.surface.overlay` and the even rows `color.surface.raised`.
@ prose
  **The panel budget (BQ-6 RULED
@ prose
  BQ-6 RULED
@ prose
  The three `layout.cost.import.*` strings are PROPOSED, an A-row to E15-D03's deck
  (D09-A20).
@ prose
  Import anyway is a CMP-001 `primary` and not `danger`, because nothing is destroyed and
  the stutter it accepts ends when panels close
@ prose
  Cancel and `Esc` return to the preview with focus on Import as new workspace and fire
  `layout.import_rejected{reason: budget-exceeded}` once: the ticket's sixth reason counts a
  user who declined the stutter, not a refused file (BQ-6 RULED).
@ prose
  **The migration line (BQ-4 RULED
@ prose
  The table then lists what the migrated file creates, and the report of a migrated import
  carries the same line above its table (PROPOSED
§ §4.5
@ prose
  **The report (BQ-12 RULED
@ prose
  Inside the region, in order: the CMP-028 `success` line "Imported Scalping (2): 7 panels,
  2 layouts, 3 items dropped, 1 remapped." (`e15.import.report.done`, `D02:520`'s line with
  this fixture's counts and the remap count added), spoken once, politely, and naming the
  name the server gave
@ prose
  then the same CMP-049 table re-rendered with what was applied, dropped and remapped, row
  for row as §4.3, its caption "Report — 7 panels and 2 layouts added · 3 dropped · 1
  remapped" (`e15.import.report.caption`).
@ prose
  **It persists (BQ-12 RULED).** The report stays until Close: no timer, never a toast
  (CMP-045) and never `role="status"`
@ prose
  Once closed, the report is gone from the app, and after a closed view it goes when its
  toast is dismissed (§3.5)
@ prose
  BQ-12 RULED
@ prose
  its labelled form is a PROPOSED A-row, §10).
@ prose
  No copied line starts with a value from the file, so a spreadsheet the text is pasted into
  never reads one as a formula, and a control character from the file arrives as the "�" the
  table shows, never as a tab or a line break (PROPOSED).
@ prose
  If the browser refuses the clipboard, "Couldn't copy the report." is spoken once,
  politely, and the region stays selectable for a copy by hand (PROPOSED copy,
  `e15.import.report.copy_failed`).
@ prose
  **Copy this section adds (PROPOSED).** Four strings that no frame row keys, each one
  sentence or one verb, are rows of the deck (§9): `e15.import.slow`,
  `e15.import.report.view`, `e15.import.review` and `e15.import.report.copy_failed`.
§ §5
@ prose
  never a lock, never a partial import** (BQ-4, BQ-5, BQ-11 RULED
@ prose
  the unanswered send says instead that the import could not be confirmed, because it may
  have happened.
§ §5.1
@ row `SCR-026/rejected-wrong-type` · col 3
  type: a picked file is filtered by `accept`
@ row `SCR-026/refused-server` · col 3
  message: "Nothing was imported." · "The server didn't accept this file:
  `layouts[0].panes[3].pane_config` isn't valid."
@ row `SCR-026/refused-server` · col 3
  variants: "The workspace store didn't answer. Choose the file again in a moment." · "The
  server didn't accept this file: it is larger than the server takes."
§ §5.2
@ prose
  the event fires once per rejection, its reason the ticket's word (BQ-11 RULED
@ row nested too deeply · col 6
  `malformed` (BQ-5 RULED)
@ row too many values · col 4
  the limit, at most 10,000 <!-- audit:contract.nodes=10000 --> values, PROPOSED (D09-G5)
@ row the send's answer never came · col 4
  that the import could not be confirmed
§ §5.3
@ heading
  5.3 The version rule (BQ-4 RULED, owner approval pending (#2701))
@ prose
  The contract types it as a string with no order (`22:21408`), so this spec reads it as a
  whole number written in decimal and compares it as a number, PROPOSED
@ prose
  "format version" names what is compared, and the ticket's "This layout was exported by v2
  and can't be imported into v1." (`14:633`) is replaced by the ruled words (BQ-4 RULED
§ §5.4
@ prose
  The checks run cheapest first, and the first that fails ends the run, so a 50 MB file is
  refused before it is read (BQ-5 RULED
@ row 2 parse · col 3
  the server's own rule for a workspace body (`22:19819`), reused (BQ-5 RULED)
@ row 2 parse · col 2
  at most 10,000 <!-- audit:contract.nodes=10000 --> values, PROPOSED
@ row 3 schema · col 3
  the bundle and `ChartTemplateInput` are not closed yet (D09-G4)
@ prose
  a known key whose value is the wrong kind takes the same frame with the PROPOSED
  `e15.import.rejected.invalid`, "This isn't a workspace file: `{key}` isn't valid. Nothing
  was imported.", the frame's variant (§9).
@ prose
  **The budget is a confirm, not a refusal** (BQ-6 RULED).
§ §5.5
@ prose
  **Condition 1, applied to a refusal** (RULED, binding on every frame).
@ prose
  PROPOSED for a key and a file name, which no contract cleans, and a file's extension is
  read after this cleaning (§3.4).
@ prose
  **Capped.** A key is shown at most 64 <!-- audit:design.key_cap=64 --> characters, a file
  name at most 40 <!-- audit:design.file_cap=40 -->, counted after cleaning, an ellipsis (…)
  past the cap (the Fixture's display caps, PROPOSED).
@ prose
  No contract bounds either string, so the cap also holds in the accessible name, which
  carries the same shortened text with the word "(shortened)" after it, PROPOSED: nothing
  past a cap is ever rendered, announced, copied or logged.
@ prose
  **Nothing kept.** When a refusal shows, the worker's text and document and the file's
  handle are dropped: nothing reaches the workspace store, the browser's storage, a cache or
  a log, and Choose another file starts from nothing (BQ-5 RULED).
@ prose
  A refusal that arrives after the view closed holds only its capped message, and only while
  its toast stands (§3.5).
@ prose
  `422 validation_failed` when the server's own re-check refuses what the browser passed
  (`22:19819`): "Nothing was imported." then "The server didn't accept this file: `{key}`
  isn't valid.", the key the first field path of the problem's `errors[]`, cleaned and
  capped as above
@ prose
  takes the same frame with the PROPOSED `e15.import.refused.store`, "The workspace store
  didn't answer. Choose the file again in a moment.", in place of the key's sentence:
  nothing of the file was kept, so the way on is to choose it again (§9
@ prose
  A `413`, a file larger than the server takes (`22:8691`), takes the same frame with the
  PROPOSED `e15.import.refused.size`, "The server didn't accept this file: it is larger than
  the server takes.", the oversized refusal's words at the send, the number the server's
  (D09-G5).
@ prose
  it says "We couldn't confirm the import. Check your workspaces before importing again."
  (PROPOSED, `e15.import.refused.unconfirmed`).
§ §6
@ prose
  BQ-14 RULED
@ prose
  These are the keys merged E15-D02 gives "+" › Import… (`D02:639`
@ prose
  `D02:655`) and merged E15-D03 renders as its R-5 (`D03:564`
§ §6.1
@ prose
  BQ-11 RULED).
@ prose
  the budget's Import anyway is a confirm, not a gate (BQ-6 RULED).
§ §7
@ row `SCR-025/export-preview`, `SCR-025/expor · col 2
  Download file once the save sheet has closed unsaved
@ row `SCR-025/export-done` · col 1
  `SCR-025/export-done`
@ row `SCR-026/report` · col 6
  PROPOSED, since the opener's menu belongs to the old tab)
@ row `SCR-026/cancelled` · col 2
  —: the dialog has closed
@ prose
  a screen reader's table commands read each cell with its column header, and each Item cell
  is its row's header (`scope="row"`, PROPOSED: CMP-049 leaves row headers to the host), so
  a row reads as its item, its type, its action and its reason.
@ row the export file is saved · col 2
  `SCR-025/export-done`
@ row the export file is saved · col 4
  `e15.export.done`
@ row the import succeeds · col 4
  `e15.import.report.done`
@ row the import succeeds after the view was c · col 1
  the import succeeds after the view was closed
@ row the import succeeds after the view was c · col 3
  polite, once, through CMP-212's region: a persistent CMP-045 `success` toast with the
  success line and the action View report, which reopens the report as the dialog's final
  step (PROPOSED
@ row the import succeeds after the view was c · col 4
  `e15.import.report.done` · `e15.import.report.view`
@ row a refusal arrives after the view was clo · col 1
  a refusal arrives after the view was closed
@ row a refusal arrives after the view was clo · col 3
  polite, once, through CMP-212's region (`politeness="polite"`, as a refusal at the send
  speaks here, D09-C12): a persistent CMP-045 `danger` toast, "Nothing was imported.", with
  the action Review, which reopens SCR-026 at the refusal's frame (PROPOSED
@ row a send left unanswered after the view wa · col 1
  a send left unanswered after the view was closed
@ row a send left unanswered after the view wa · col 3
  PROPOSED
@ row a refusal at the send · col 3
  PROPOSED departure from slice 4's conventions 33, which speaks a refusal at its point of
  action assertively (`S4:140`): the refused verb leaves the footer and focus moves with it,
  so an interruption would only cut that reading short (D09-C12)
@ row the check runs, `SCR-026/validating` · col 2
  `progressbar` · named by "Checking scalping.json…" · its value the share of the five steps
  done, its text "Checking scalping.json… step 3 of 5"
§ §8
@ row Choose file… and the drop zone (CMP-067) · col 2
  the zone's resting edge `color.border.default` at `border.hairline`, solid (CMP-067's
  `color.border.dashed` is not a shipped token, D09-A3), `radius.card`, padding
  `space.inset.xl` (24 <!-- audit:redline.space.inset.xl=24 --> px)
@ row Action column · col 2
  its decorative CMP-019 glyph at `size.icon` (16 <!-- audit:redline.size.icon=16 --> px):
  Add `check` in `color.status.success.strong`, Drop `x-circle` (`danger` until registered,
  `15:307`) in `color.status.danger.strong`, Remap `merge` (PROPOSED by E11-D02's icon batch
@ prose
  26 <!-- audit:pairs_rows=26 --> gated pairs, 0 <!-- audit:pairs_fail=0 --> FAIL: 14 <!--
  audit:pairs_registered=14 --> registered in `tools/contrast/pairs.mjs` and 12 <!--
  audit:pairs_proposed=12 --> PROPOSED (D09-A10).
@ row 4 · col 8
  PROPOSED
@ row 6 · col 8
  PROPOSED
@ row 9 · col 8
  PROPOSED
@ row 10 · col 8
  PROPOSED
@ row 11 · col 8
  PROPOSED
@ row 13 · col 8
  PROPOSED
@ row 16 · col 8
  PROPOSED
@ row 17 · col 8
  PROPOSED
@ row 19 · col 8
  PROPOSED
@ row 22 · col 8
  PROPOSED
@ row 23 · col 8
  PROPOSED
@ row 24 · col 8
  PROPOSED
@ row 27 · col 8
  PROPOSED
@ row 28 · col 8
  PROPOSED
@ row 29 · col 8
  PROPOSED
@ prose
  **Why twelve are PROPOSED.** Rows 4, 6, 9, 10, 11, 13, 16, 17, 19, 22, 27 and 28 are pairs
  `tools/contrast/pairs.mjs` does not hold: the header fill, the Add glyph on both rows, the
  Drop and Remap glyphs on even rows, the trust note's edge, the success line's words and
  edge, the `secondary` label, the drag-over edge and the progress bar's fill on its track
  and on the card.
@ prose
  a check, a circled cross, a merge
@ prose
  and never a row's colour (BQ-10 RULED
§ §9
@ prose
  on the export the base name the save sheet returned, suggested as
  `<slug>.cv-workspace-v<schema_version>.json` (BQ-8 RULED
@ prose
  **Status:** upstream = verbatim from merged text, cited · adapted = upstream words
  changed, cited, with why · ruled = the copy a BQ ruled (6396085915) · registered = a key
  or a component's own word, already registered · new · PROPOSED = this spec's, the owner's
  to approve (#2701).
@ row `e15.export.unsaved` · col 4
  new · PROPOSED (§2.3
@ row `e15.export.included` · col 4
  only what `WorkspaceBundle` holds (BQ-2 RULED
@ row `e15.export.excluded` · col 2
  the Excluded list, first-class, one item per clause (`SCR-025/export-preview`,
  `SCR-025/export-done`)
@ row `e15.export.excluded` · col 4
  ruled · BQ-2 (6396085915), owner approval pending (#2701)
@ row `e15.export.caveat` · col 4
  ruled · BQ-2 (6396085915)
@ row `e15.export.over_limit` · col 4
  new · PROPOSED (§2.3
@ row `e15.export.failed_gone` · col 4
  new · PROPOSED (§2.1
@ row `e15.export.failed_unlisted` · col 4
  new · PROPOSED (§2.3
@ row `e15.export.save_failed` · col 4
  new · PROPOSED (§2.4
@ row `e15.export.done` · col 1
  `e15.export.done`
@ row `e15.export.done` · col 2
  the completion line, CMP-028 `success`, the file name in mono (`SCR-025/export-done`)
@ row `e15.export.done` · col 4
  new · PROPOSED (BQ-8 RULED: the drawn completion)
@ row `e15.import.title` · col 4
  new · PROPOSED (BQ-9 RULED)
@ row `e15.import.trust` · col 4
  upstream · `D02:513`, verbatim (BQ-2 RULED
@ row `e15.import.trust` · col 4
  owner approval pending (#2701))
@ row `e15.import.help` · col 4
  new · PROPOSED
@ row `e15.import.drop_active` · col 4
  new · PROPOSED
@ row `e15.import.drop_rejected` · col 4
  new · PROPOSED
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
@ row `e15.import.action.remap` · col 2
  the Action word after the `merge` glyph, kept for the one true remap (§4.2 row 4)
@ row `e15.import.action.remap` · col 4
  the ticket's three words (BQ-3, BQ-10 RULED)
@ row `e15.import.reason.account` · col 4
  upstream · `D02:516` (BQ-3 RULED)
@ row `e15.import.reason.remap` · col 4
  new · PROPOSED (BQ-3 RULED)
@ row `e15.import.slow` · col 4
  new · PROPOSED (CMP-001's slow path, `15:48`
@ row `e15.import.migrated` · col 4
  ruled · BQ-4 (6396085915), E15-S07's rule (`BL:1136`)
@ row `e15.import.caption_budget` · col 4
  new · PROPOSED (BQ-6 RULED)
@ row `e15.import.budget` · col 4
  new · PROPOSED (BQ-6 RULED)
@ row `layout.cost.import.confirm` · col 4
  ruled · BQ-6 (6396085915), re-verbed from `D03:631`
@ row `e15.import.report.heading` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.report.done` · col 1
  `e15.import.report.done`
@ row `e15.import.report.done` · col 2
  the toast's line after a closed view (§7)
@ row `e15.import.report.caption` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.report.copy` · col 4
  new · PROPOSED (BQ-12 RULED)
@ row `e15.import.report.copy_failed` · col 4
  new · PROPOSED (§4.5
@ row `e15.import.report.view` · col 2
  the action of the persistent CMP-045 `success` toast after the view was closed mid-send
@ row `e15.import.report.view` · col 4
  new · PROPOSED (H22's outcome surface, `S4:734`
@ row `e15.import.review` · col 2
  the action of the persistent CMP-045 `danger` toast when a refusal arrives after the view
  was closed mid-send
@ row `e15.import.review` · col 4
  new · PROPOSED (H22's outcome surface, `S4:734`
@ row `e15.import.rejected.version_newer` · col 4
  adapted · `D02:517` and `14:633`: "format version" names what is compared, the
  constructive sentence added (BQ-4 RULED
@ row `e15.import.rejected.version_newer` · col 4
  owner approval pending (#2701))
@ row `e15.import.rejected.version_older` · col 4
  new · PROPOSED (BQ-4 RULED
@ row `e15.import.rejected.version_older` · col 4
  owner approval pending (#2701))
@ row `e15.import.rejected.parse` · col 4
  new · PROPOSED
@ row `e15.import.rejected.panes` · col 4
  new · PROPOSED
@ row `e15.import.rejected.layouts` · col 4
  new · PROPOSED
@ row `e15.import.rejected.presets` · col 4
  new · PROPOSED
@ row `e15.import.rejected.invalid` · col 4
  new · PROPOSED (D09-D31)
@ row `e15.import.rejected.wrong_type` · col 4
  new · PROPOSED
@ row `e15.import.rejected.depth` · col 4
  new · PROPOSED
@ row `e15.import.rejected.nodes` · col 4
  new · PROPOSED
@ row `e15.import.rejected.nodes` · col 4
  the limit PROPOSED (D09-G5)
@ row `e15.import.refused.server` · col 3
  "The server didn't accept this file: `{key}` isn't valid." · fixture "The server didn't
  accept this file: `layouts[0].panes[3].pane_config` isn't valid."
@ row `e15.import.refused.server` · col 4
  new · PROPOSED
@ row `e15.import.refused.store` · col 4
  new · PROPOSED (D09-D31)
@ row `e15.import.refused.size` · col 3
  "The server didn't accept this file: it is larger than the server takes."
@ row `e15.import.refused.size` · col 4
  new · PROPOSED (D09-D31
@ row `e15.import.refused.unconfirmed` · col 4
  new · PROPOSED (D09-D33
@ row `e15.import.shortened` · col 4
  new · PROPOSED (D09-D27)
@ row `workspace.limit.count` · col 4
  E15's PROPOSED state key · `D02:674`
§ §10
@ heading
  10. Design-system A-rows (`15`, PROPOSED)
@ prose
  This PR edits no `15` entry (BQ-1 RULED).
@ prose
  Each row is copy-ready for the catalogue's owner: the old text is verbatim at the base, a
  fragment of the line named and unique in it, and the new text replaces exactly that
  fragment, the rest of the line unchanged.
@ prose
  Text inside a double-backtick span is the catalogue's own source, its single backticks
  included
@ prose
  in the tables `\|` stands for `|`.
@ prose
  The ids run D09-A1 to D09-A11 here and go on in §11
@ prose
  §12's hand-offs name each row's owner.
@ row Id · col 1
  Id
@ row Id · col 2
  `15` entry · field (line)
@ row Id · col 3
  Old (verbatim)
@ row Id · col 4
  New (PROPOSED)
@ row Id · col 5
  Basis
@ row D09-A1 · col 1
  D09-A1
@ row D09-A1 · col 2
  CMP-067 · Purpose (`15:692`)
@ row D09-A1 · col 2
  Props (`15:693`)
@ row D09-A1 · col 3
  `**Purpose**: CSV/JSON import (journal import, rule import/export).` · ``- **Props**:
  `accept` · `onFiles` · `multiple?`.``
@ row D09-A1 · col 4
  `**Purpose**: CSV/JSON import (journal import, rule import/export, workspace import).` ·
  ``- **Props**: `accept` · `onFiles` · `multiple?` · `label` (the visible text of the real
  `<button>` that fronts the native input, kept `hidden` and opened by the button's click,
  e.g.
@ row D09-A1 · col 4
  "Choose file…"
@ row D09-A1 · col 4
  the input is labelled by it) · `dropHint?` (the drop zone's words, the button's
  `aria-describedby`, e.g.
@ row D09-A1 · col 4
  "or drop a workspace file here") · `help?` (the line under it, in the same
  `aria-describedby` after the drop words) · `maxBytes?` (a picked or dropped file over it
  is refused from its size before a byte of it is read
@ row D09-A1 · col 4
  the host shows its error) · `error?` (the host's message node, first in the button's
  `aria-describedby`
@ row D09-A1 · col 4
  the input stays live).``
@ row D09-A1 · col 5
  SCR-026's picker and drop zone (`SCR-026/pick`
@ row D09-A1 · col 5
  BQ-9, BQ-13 RULED
@ row D09-A1 · col 5
  `D02:513`)
@ row D09-A1 · col 5
  the drop target described the same way on SCR-089 (`E36D03:339`)
@ row D09-A1 · col 5
  `14:636`
@ row D09-A2 · col 1
  D09-A2
@ row D09-A2 · col 2
  CMP-067 · A11y (`15:694`)
@ row D09-A2 · col 3
  ``- **A11y**: native `<input type=file>` under the hood (drag-and-drop is additive, never
  the only path), fully keyboard-operable via the native file picker.``
@ row D09-A2 · col 4
  ``- **A11y**: native `<input type=file>` under the hood (drag-and-drop is additive, never
  the only path), fully keyboard-operable via the native file picker: a real `<button>`
  showing its `label` opens it on `Enter` or `Space`, and a chosen file returns focus to
  that button
@ row D09-A2 · col 4
  the drop zone has no role, no name and no Tab stop of its own, and a drop only adds to the
  input
@ row D09-A2 · col 4
  a drop of more files than `multiple` allows, or of a type outside `accept`, is refused in
  words ("Drop one .json file"), never by colour alone
@ row D09-A2 · col 4
  a drop that carries no file, or lands outside the zone, is ignored: nothing is read or
  fetched and no address is followed
@ row D09-A2 · col 4
  the host's error is first in the button's `aria-describedby` and announced once,
  politely.``
@ row D09-A2 · col 5
  `05:35`
@ row D09-A2 · col 5
  `05:101`
@ row D09-A2 · col 5
  `14:636`
@ row D09-A2 · col 5
  `SCR-026/drag-over-rejected`
@ row D09-A2 · col 5
  BQ-13 RULED
@ row D09-A3 · col 1
  D09-A3
@ row D09-A3 · col 2
  CMP-067 · Tokens (`15:695`)
@ row D09-A3 · col 3
  ``- **Tokens**: `color.border.dashed`.``
@ row D09-A3 · col 4
  ``- **Tokens**: the zone's edge `color.border.default` at `border.hairline`, solid,
  `radius.card`, padding `space.inset.xl`, its words `type.ui.body` + `color.text.secondary`
@ row D09-A3 · col 4
  drag-over: the edge `color.border.selected` and the fill `color.surface.hover`, the words
  changed
@ row D09-A3 · col 4
  the button a CMP-001 `secondary`.
@ row D09-A3 · col 4
  (Replaces `color.border.dashed`, which is not a shipped token
@ row D09-A3 · col 4
  a dashed edge is kept for estimated and absent data.)``
@ row D09-A3 · col 5
  the re-bind E36-D03 reported for the same entry (`E36D03:272`)
@ row D09-A3 · col 5
  §8 rows 22 and 24
@ row D09-A4 · col 1
  D09-A4
@ row D09-A4 · col 2
  CMP-067 · Storybook (`15:696`)
@ row D09-A4 · col 2
  Tests (`15:697`)
@ row D09-A4 · col 3
  `- **Storybook**: Default, DragOver, Error.` · `- **Tests**: unit, visual, axe,
  keyboard-only file selection test.`
@ row D09-A4 · col 4
  `- **Storybook**: Default, Focused, WithHelp, DragOver, DragOverRejected, Validating,
  Error, DisabledWithReason, Reflow200.` · ``- **Tests**: unit, visual, axe, keyboard-only
  file selection test, the drop zone never in the Tab order, a drop refused by type or by
  count in words, a file over `maxBytes` refused before it is read.``
@ row D09-A4 · col 5
  the ticket's DoD, CMP-067's Storybook list agreed with FE (`BL:266`
@ row D09-A4 · col 5
  the owner's agreement stands in, #2701)
@ row D09-A4 · col 5
  DL-14
@ row D09-A4 · col 5
  DisabledWithReason is a host's T2 on the button, which SCR-026 never needs (§6)
@ row D09-A5 · col 1
  D09-A5
@ row D09-A5 · col 2
  CMP-049 · Tokens (`15:531`)
@ row D09-A5 · col 3
  `` odd `color.surface.canvas`, even `color.surface.raised` ``
@ row D09-A5 · col 4
  `` odd `color.surface.canvas` (inside a dialog, the dialog's own `color.surface.overlay`),
  even `color.surface.raised` ``
@ row D09-A5 · col 5
  the preview and the report sit on the dialog's surface (§4
@ row D09-A5 · col 5
  §8 rows 1, 3 and 21)
@ row D09-A6 · col 1
  D09-A6
@ row D09-A6 · col 2
  CMP-027 · A11y (`15:306`)
@ row D09-A6 · col 3
  `` `live` overrides it: `polite` for an in-panel load failure, ``
@ row D09-A6 · col 4
  `` `live` overrides it: `polite` for an in-panel load failure or for a file refused inside
  a dialog, its input above it still live and the refused verb absent (SCR-026's
  rejections), ``
@ row D09-A6 · col 5
  §5.2
@ row D09-A6 · col 5
  slice 4's H37 (`S4:919`)
@ row D09-A6 · col 5
  BQ-11 RULED
@ row D09-A7 · col 1
  D09-A7
@ row D09-A7 · col 2
  CMP-028 · A11y (`15:317`)
@ row D09-A7 · col 3
  `` `live` overrides the default (`off` renders no live role, for a banner whose
  announcement another region makes)
@ row D09-A7 · col 3
  ``
@ row D09-A7 · col 4
  `` `live` overrides the default (`off` renders no live role, for a banner whose
  announcement another region makes
@ row D09-A7 · col 4
  a standing statement read in place and never announced, such as an import's trust note, is
  `live="off"` with `role="note"`, its one line `type.ui.body` + `color.text.primary`)
@ row D09-A7 · col 4
  ``
@ row D09-A7 · col 5
  SCR-026's trust note (`D02:513`
@ row D09-A7 · col 5
  BQ-2 RULED)
@ row D09-A7 · col 5
  E36-D03's privacy note in the same form (`E36D03:153–155`)
@ row D09-A7 · col 5
  §8 row 12
@ row D09-A8 · col 1
  D09-A8
@ row D09-A8 · col 2
  CMP-033 · Props (`15:364`)
@ row D09-A8 · col 2
  Storybook (`15:368`)
@ row D09-A8 · col 3
  ``- **Props**: `value: string` · `label` (a11y name) · `onCopied?`.`` · `- **Storybook**:
  Default, CopiedState.`
@ row D09-A8 · col 4
  ``- **Props**: `value: string` · `label` (a11y name) · `onCopied?` · `display?: "icon"\
@ row D09-A8 · col 5
  "button"` (default `icon`; `button` shows the label as a CMP-001 `secondary`, for a
  dialog's footer such as SCR-026's Copy report; the copy and its "Copied" announcement are
  unchanged).`` · `- **Storybook**: Default, CopiedState, AsButton.`
@ row D09-A8 · col 6
  `SCR-026/report`'s footer (BQ-12 RULED)
@ row D09-A8 · col 6
  CMP-033's announcement (`15:366`)
@ row D09-A9 · col 1
  D09-A9
@ row D09-A9 · col 2
  CMP-044 · Tokens (`15:479`)
@ row D09-A9 · col 3
  ``Confirm a CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`),``
@ row D09-A9 · col 4
  ``Confirm a CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`), or a
  CMP-001 `primary` for a measured-cost confirm, which destroys nothing (US-LAY-001's Add
  panel anyway, SCR-026's Import anyway),``
@ row D09-A9 · col 5
  `SCR-026/budget-confirm` (BQ-6 RULED)
@ row D09-A9 · col 5
  E15-D03's cost confirm (`D03:629–631`)
@ row D09-A9 · col 5
  E15-D08's merged row on the same clause composes with it
@ row D09-A10 · col 1
  D09-A10
@ row D09-A10 · col 2
  `tools/contrast/pairs.mjs` and `tools/contrast/encodings.json` (their owner
@ row D09-A10 · col 2
  not `15`)
@ row D09-A10 · col 3
  —
@ row D09-A10 · col 4
  register the twelve PROPOSED gated pairs of §8
@ row D09-A10 · col 4
  rows 4, 6, 9, 10, 11, 13, 16, 17, 19, 22, 27 and 28
@ row D09-A10 · col 4
  and add the preview's and the report's Add / Drop / Remap encoding, its non-colour channel
  the word and the glyph's shape
@ row D09-A10 · col 5
  `16:456`
@ row D09-A10 · col 5
  §8
@ row D09-A10 · col 5
  a design PR never edits `tools/`
@ row D09-A11 · col 1
  D09-A11
@ row D09-A11 · col 2
  CMP-036 · Tokens (`15:395`)
@ row D09-A11 · col 3
  ``- **Tokens**: `space.row.*`, `font.size.body/label`.``
@ row D09-A11 · col 4
  ``- **Tokens**: `space.row.height.comfortable` or `space.row.height.compact` by density
@ row D09-A11 · col 4
  the label `type.ui.label` + `color.text.secondary`, the value `type.ui.body` +
  `color.text.primary`.
@ row D09-A11 · col 4
  (Replaces the wildcard `space.row.*` and `font.size.body/label`, which name no shipped
  token.)``
@ row D09-A11 · col 5
  the export's Included and Excluded lists (`SCR-025/export-preview`)
@ row D09-A11 · col 5
  the semantic sets in `packages/ui/tokens`
@ prose
  **No A-row, and why.** CMP-001 Button: its `loading` keeps the label with `aria-busy`, and
  its T2 is E09-D09's (`15:48–57`).
@ prose
  CMP-019 Icon: `x-circle` is already PROPOSED for E05-T06 (`15:307`) and `merge` by E11's
  icon batch, and this spec adds no glyph.
@ prose
  CMP-023 Progress Bar: determinate, `valueText`, never a live region, as catalogued
  (`15:262–270`).
@ prose
  CMP-043 Dialog: `lg` and `md` fit (`15:466`), and its focus, `Esc` and scrim rules hold as
  catalogued (`15:468`).
@ prose
  CMP-045 Toast: the report is never a toast
@ prose
  the one toast here, after a closed view, is persistent because it carries an action, as
  catalogued (`15:483–490`).
@ prose
  CMP-068 CopyableCodeBlock: unused, because no frame shows the file's text and Condition 1
  forbids echoing it.
@ prose
  CMP-079 RbacGate: T2 as catalogued (`15:811–819`).
@ prose
  CMP-234 ValidationPanel: unused, because its entries anchor to rule rows and nodes
  (`15:2738–2742`) while a refusal here names one key in one message and the report is a
  table
@ prose
  E15-S07 names it for the report (`BL:1136`), a C-row (D09-C10).
§ §11
@ heading
  11. `14` A-rows and the pointer lines
@ prose
  **Applied by this PR, content only (BQ-1 RULED).** Two pointer lines, each right after its
  screen's sign-off checklist
@ prose
  after SCR-025's (`14:627`) and after SCR-026's (`14:640`)
@ prose
  each starting `- **Design (hi-fi):** [E15-D09.md](../design/E15/E15-D09.md)`: SCR-025's
  points at §2, the export
@ prose
  SCR-026's at §3 to §5, the import.
@ prose
  The tool checks on every run that each sits in the run of pointer lines right after its
  checklist, so a later E15-D08 pointer may sit beside ours.
@ prose
  Nothing else in `14` is edited: both checklists stay verbatim, and §13 maps every item,
  the version-mismatch item to its refusal frame.
@ prose
  **Copy-ready for the catalogue's owner, PROPOSED** (old text verbatim at the base, a whole
  line or a fragment of it as named
@ prose
  a fragment in double quotes is the catalogue's own words
@ prose
  in the tables `\|` stands for `|`).
@ prose
  Where E15-D02 already proposed the same line's change
@ prose
  its A-10 on SCR-026's Type, Validation and checklist (`D02:823`), pending
@ prose
  the row below is the one text that does both, so the owner applies one, not two.
@ row Id · col 1
  Id
@ row Id · col 2
  `14` entry · field (line)
@ row Id · col 3
  Old (verbatim)
@ row Id · col 4
  New (PROPOSED)
@ row Id · col 5
  Basis
@ row D09-A12 · col 1
  D09-A12
@ row D09-A12 · col 2
  SCR-026 · Type (`14:632`), a fragment
@ row D09-A12 · col 3
  "(panels added, symbols referenced, accounts remapped)"
@ row D09-A12 · col 4
  "(Choose file… or a drop; five checks in a worker; then a table of what is added, dropped
  and remapped — unknown panel kinds and account-scoped settings dropped and listed, never
  remapped — before Import as new workspace creates a new workspace)"
@ row D09-A12 · col 5
  BQ-3, BQ-5 and BQ-9 RULED
@ row D09-A12 · col 5
  it does E15-D02's A-10 for this line (`D02:823`)
@ row D09-A12 · col 5
  `11:2868`
@ row D09-A13 · col 1
  D09-A13
@ row D09-A13 · col 2
  SCR-026 · Validation (`14:633`), two fragments
@ row D09-A13 · col 3
  "This layout was exported by v2 and can't be imported into v1." · "inaccessible account
  references remap to the user's default account"
@ row D09-A13 · col 4
  "This file was exported by format version 2 and can't be imported into format version 1.
  Nothing was imported. Export it again from a version 1 app, or update this app." ·
  "account-scoped settings are dropped and listed, never remapped, and no account the
  importer cannot see is named; an older format version this app still reads is migrated
  forward and said so"
@ row D09-A13 · col 5
  BQ-3 and BQ-4 RULED, owner approval pending (#2701)
@ row D09-A13 · col 5
  `11:2868`
@ row D09-A13 · col 5
  `11:2871`
@ row D09-A13 · col 5
  it does E15-D02's A-10 for this line (`D02:823`)
@ row D09-A14 · col 1
  D09-A14
@ row D09-A14 · col 2
  SCR-026 · Components (`14:634`), the whole line
@ row D09-A14 · col 3
  `- **Components:** CMP-001 Button, CMP-027 ErrorState / InlineError, CMP-043 Dialog,
  CMP-044 ConfirmDialog, CMP-067 FileDrop / Import control.`
@ row D09-A14 · col 4
  ``- **Components:** CMP-001 Button, CMP-019 Icon (`lock`, `check`, `x-circle`, `merge`),
  CMP-023 Progress Bar, CMP-027 ErrorState / InlineError, CMP-028 Callout / Banner, CMP-033
  CopyButton, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-049 Table, CMP-067 FileDrop /
  Import control, CMP-079 RbacGate.``
@ row D09-A14 · col 5
  the frames of §3 to §5
@ row D09-A14 · col 5
  an entry that shows a T2 control lists CMP-019's `lock` and CMP-079 (E15-D02 §8.1,
  `D02:635–674`
@ row D09-A14 · col 5
  §6)
@ row D09-A15 · col 1
  D09-A15
@ row D09-A15 · col 2
  SCR-026 · A11y (`14:636`), the whole line
@ row D09-A15 · col 3
  `- **A11y:** File input has a visible label and an accessible drop zone with a keyboard
  alternative; the import diff is a table, not a canvas; validation errors are listed as
  text with the offending key named.`
@ row D09-A15 · col 4
  `- **A11y:** File input has a visible label (Choose file…, a real button) and a drop zone
  with a keyboard alternative, the drop zone never a Tab stop; the import diff is a table,
  not a canvas, its caption stating the counts first and its Action a word with a decorative
  glyph; validation errors are listed as text with the offending key named, announced
  politely, the input staying live; the report is a persistent region with Copy report;
  every string from the file is shown as text, capped.`
@ row D09-A15 · col 5
  the ticket's Accessibility notes (`BL:266`)
@ row D09-A15 · col 5
  BQ-9, BQ-10, BQ-12 and BQ-13 RULED
@ row D09-A15 · col 5
  §5, §7
@ row D09-A16 · col 1
  D09-A16
@ row D09-A16 · col 2
  SCR-026 · Analytics/audit (`14:638`), the whole line
@ row D09-A16 · col 3
  ``- **Analytics/audit:** `layout.imported`, `layout.import_rejected` with `{reason}`
  (analytics).``
@ row D09-A16 · col 4
  ``- **Analytics:** `layout.imported` `{panelCount, droppedCount, remappedCount,
  schemaVersion}`, `layout.import_rejected` `{reason: version-newer \
@ row D09-A16 · col 5
  version-older \
@ row D09-A16 · col 6
  malformed \
@ row D09-A16 · col 7
  oversized \
@ row D09-A16 · col 8
  wrong-type \
@ row D09-A16 · col 9
  budget-exceeded}` (analytics, never audit; no property carries anything from the file).``
@ row D09-A16 · col 10
  the ticket's Observability (`BL:266`)
@ row D09-A16 · col 10
  D09-G13 maps E15-S07's `size \
@ row D09-A16 · col 11
  parse \
@ row D09-A16 · col 12
  schema \
@ row D09-A16 · col 13
  version \
@ row D09-A16 · col 14
  semantic` (`BL:1136`); §5.5
@ row D09-A17 · col 1
  D09-A17
@ row D09-A17 · col 2
  SCR-026 · checklist (`14:640`), a fragment
@ row D09-A17 · col 3
  "version-mismatch state ('exported from a newer version - 2 panels will be dropped')"
@ row D09-A17 · col 4
  "version-mismatch state (a newer format version refused with both versions and a way on,
  nothing imported, no partial apply; an older one this app still reads migrated and said
  so) [ ] account-scoped elements dropped and listed in the preview and the report, naming
  no account the importer cannot see"
@ row D09-A17 · col 5
  BQ-3 and BQ-4 RULED, owner approval pending (#2701)
@ row D09-A17 · col 5
  `11:2871`
@ row D09-A17 · col 5
  E15-D02 drew the refusal, not the checklist's words (`D02:732`), and its A-10 asked for
  this item (`D02:823`)
@ row D09-A18 · col 1
  D09-A18
@ row D09-A18 · col 2
  SCR-025 · Type (`14:618`), a fragment
@ row D09-A18 · col 3
  "export as template"
@ row D09-A18 · col 4
  "Export… (a workspace file, E15-D09 §2)"
@ row D09-A18 · col 5
  `exportWorkspace` exports a workspace file, never a template (`22:12843`)
@ row D09-A18 · col 5
  BQ-7 RULED
@ row D09-A18 · col 5
  E15-D08's merged row rewrites the whole line and composes with this one
@ row D09-A19 · col 1
  D09-A19
@ row D09-A19 · col 2
  SCR-089 · a new line after its checklist (`14:1999`)
@ row D09-A19 · col 3
  —
@ row D09-A19 · col 4
  `- **Reuse (E15-D09):** [E15-D09.md](../design/E15/E15-D09.md) §3 to §7: a file that
  crosses the trust boundary is chosen through a real button fronting the labelled native
  input, the drop zone never a Tab stop; it is checked in a fixed order and the server
  checks it again, as the dialog says; a preview table shows drops and remaps first; a
  refusal names its key in mono, capped, and offers no import verb; the report is a
  persistent region with Copy report; every string from the file is shown as text, capped.`
@ row D09-A19 · col 5
  the ticket's reuse note (DL-21
@ row D09-A19 · col 5
  DoD-10)
@ row D09-A19 · col 5
  E36-D03 already draws SCR-089's drop zone and pre-check table (`E36D03:153–155`), so this
  line points and never redraws
@ prose
  **The reuse note for SCR-089** (DL-21
@ prose
  DoD-10
@ prose
  the ticket's Out of scope).
@ prose
  SCR-089, rule import and export (`14:1990`), is a sibling surface that E36-D03 already
  draws, with CMP-067's native input first and its drop target described by its words
  (`E36D03:153–155`
@ prose
  `E36D03:339`), so D09-A19 points at this spec and changes nothing drawn there.
@ prose
  Five things carry over as they stand: the real button with its visible label in front of
  the native input
@ prose
  the drop zone that only adds to it and is never a Tab stop
@ prose
  the checks in a fixed, cheapest-first order, with the server's own check stated on the
  checking step
@ prose
  the refusal that names its key in mono, capped, and never offers to bring in part of a
  file
@ prose
  every string from the file shown as text only, cleaned and capped (§5.5).
@ prose
  Two do not: SCR-089 accepts or skips each rule on its own (`14:1999`) where a workspace is
  whole or nothing, and a rule bundle's version and account references follow E36's
  contract, not `WorkspaceBundle`'s.
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
@ prose
  **G
@ prose
  gaps their owners close.**
@ row Id · col 1
  Id
@ row Id · col 2
  Gap
@ row Id · col 3
  What closes it
@ row Id · col 4
  Owner
@ row D09-G1 · col 1
  D09-G1
@ row D09-G1 · col 2
  **The atomic import.** No operation takes a bundle: `exportWorkspace`'s description names
  `POST /workspaces` with `from_bundle` (`22:12848`), a field no input schema has, and `22`
  says so (`22:21419`)
@ row D09-G1 · col 2
  `createWorkspace` refuses a body over 4 KiB (`22:8691`) while a file may be 2 MB
@ row D09-G1 · col 2
  and an import built in the client from `createWorkspace` and then `createLayout` for each
  layout is not atomic (`FL:171`), the partial import the ticket forbids (`11:2871`)
@ row D09-G1 · col 3
  one operation, contract first, that takes the checked bundle and creates the workspace
  with all its layouts, chart templates, drawings and indicator presets in one transaction,
  or creates nothing
@ row D09-G1 · col 3
  it re-runs every check of §3.4 on the server, admits a 2 MB body, returns the name it gave
  and the items it dropped, and refuses with the problem types of D09-G7
@ row D09-G1 · col 3
  it takes an `Idempotency-Key`, as `createWorkspace` does (`22:8692`), so a send repeated
  after a lost answer never imports twice (`SCR-026/refused-unconfirmed`)
@ row D09-G1 · col 3
  the import is built on it and never before it (§3.5, §5.5)
@ row D09-G1 · col 4
  `22`'s owner, contract first (C-6.1)
@ row D09-G1 · col 4
  E15-S07 builds on it
@ row D09-G2 · col 1
  D09-G2
@ row D09-G2 · col 2
  `schema_version` is a free string (`22:21408`): no current value, no order, no oldest
  version still read, no outcome for a value that is absent or malformed
@ row D09-G2 · col 2
  E15-S07 names `schemaVersion` and `appVersion` in another shape (`BL:1136`)
@ row D09-G2 · col 3
  the format (PROPOSED: a whole number written in decimal, §5.3), the current value 1, the
  order, the oldest version still read, the outcome for an absent or malformed value (a
  schema failure that names the key) and one casing
@ row D09-G2 · col 3
  the characters a file name may carry for it (§2.4)
@ row D09-G2 · col 3
  and one shape per readable version, so the schema step reads a file against its own
  version's shape and never shadows the version outcome (§3.4)
@ row D09-G2 · col 4
  `22`'s owner
@ row D09-G2 · col 4
  E15-S07
@ row D09-G3 · col 1
  D09-G3
@ row D09-G3 · col 2
  Account-scoped elements: no bundle schema has an account field and `PaneConfig` forbids
  account ids (`22:20031`), so a strict server refuses a file that carries one whole (C-6.3
@ row D09-G3 · col 2
  SR-040, `04:855`), while the story wants it dropped with a clear report (`11:2868`)
@ row D09-G3 · col 2
  `14:633`'s "the user's default account" names nothing a workspace has
@ row D09-G3 · col 3
  the contract's rule: the server drops an account-scoped setting at export and again at
  import and names it in its answer (E15-S07, `BL:1136`), or it refuses the whole file, in
  which case the preview's Drop row is a prediction and the outcome is
  `SCR-026/refused-server`
@ row D09-G3 · col 3
  no default account for a workspace
@ row D09-G3 · col 4
  `22`'s owner
@ row D09-G3 · col 4
  E15-S07
@ row D09-G4 · col 1
  D09-G4
@ row D09-G4 · col 2
  `WorkspaceBundle` and `ChartTemplateInput` are not closed, and a template's `config` is
  open (`22:21402–21423`), against C-6.3 and SR-040 (`04:855`)
@ row D09-G4 · col 3
  `additionalProperties: false` on both and a closed `config`
@ row D09-G4 · col 3
  the export's check (§2.3) and the import's schema step then read closed schemas
@ row D09-G4 · col 4
  `22`'s owner
@ row D09-G5 · col 1
  D09-G5
@ row D09-G5 · col 2
  The limits the contract does not carry: the file's size (2 MB, E15-S07's default,
  `BL:1136`), the count of values (10,000, PROPOSED), the `layouts` array (32 a workspace in
  the store, `22:8886`, none in the bundle), the `drawings` and `chart_templates` arrays,
  and a pane kind's length (32 here, PROPOSED from the setting keys' pattern of `22:20041`,
  since `PaneKind` has none, `22:19971`)
@ row D09-G5 · col 2
  and the two directions disagree: an export carries every live preset, 500 a user and never
  truncated, while an import takes 200 (`22:21422–21423`), and an export's size has no cap
  while an import's is 2 MB
@ row D09-G5 · col 3
  the caps in `22`, the same numbers in both directions, or an export that warns when its
  file would be refused (§2.3's warning line meanwhile)
@ row D09-G5 · col 4
  `22`'s owner
@ row D09-G5 · col 4
  E15-S07
@ row D09-G6 · col 1
  D09-G6
@ row D09-G6 · col 2
  References inside the bundle point at the exporter's ids: a drawing's `layout_id`
  (`22:20390`), a pane's `chart_template_id` (`22:20066`) and its `indicator_preset_ids`
  (`22:20072`), each refused today on a create
@ row D09-G6 · col 3
  a rule that the server makes new ids for everything it imports and re-points each
  reference, never honouring the exporter's (E15-X01, `BL:721`), and drops a reference it
  cannot resolve, with its report
@ row D09-G6 · col 4
  `22`'s owner
@ row D09-G6 · col 4
  E15-S07
@ row D09-G7 · col 1
  D09-G7
@ row D09-G7 · col 2
  No problem type names a newer or an older format version, a wrong file type, or a store
  that does not answer at the import: today the workspace routes refuse with
  `validation_failed` and `limit_reached` (`22:19819`
@ row D09-G7 · col 2
  `22:8686`), so these refusals are the client's
@ row D09-G7 · col 2
  the budget is a confirm and needs none
@ row D09-G7 · col 3
  a problem type, or an `errors[]` rule, for each, so the server's refusal at the send maps
  to §9's keys and never shows its own words (`15:306`)
@ row D09-G7 · col 4
  `22`'s owner
@ row D09-G7 · col 4
  E15-S07
@ row D09-G8 · col 1
  D09-G8
@ row D09-G8 · col 2
  E15-S07 wants the file to carry its own report of what the export dropped (`BL:1136`)
@ row D09-G8 · col 2
  `WorkspaceBundle` has no field for it (`22:21402–21423`)
@ row D09-G8 · col 3
  a report field in the bundle that the preview's Drop rows read, or the import's answer
  naming what the server dropped
@ row D09-G8 · col 4
  `22`'s owner
@ row D09-G8 · col 4
  E15-S07
@ row D09-G9 · col 1
  D09-G9
@ row D09-G9 · col 2
  The ticket cites a workspace document in `24-internal-schemas.md` (`BL:266`), and `24` has
  none
@ row D09-G9 · col 3
  the document in `24`, or the ticket's reference corrected to `22`'s `WorkspaceBundle`
@ row D09-G9 · col 4
  `24`'s owner
@ row D09-G9 · col 4
  the owner
@ row D09-G10 · col 1
  D09-G10
@ row D09-G10 · col 2
  `workspace.exported` sits on SCR-025's Audit line (`14:621`), while E15-D01's locked list
  keeps layout events analytics, never audit (`D02:84`), and E15-X01 asks that the export be
  audited (`BL:721`)
@ row D09-G10 · col 2
  an export performed while viewing as another user, T1 by BQ-7, is the case the audit
  question is about
@ row D09-G10 · col 3
  one class for the event
@ row D09-G10 · col 3
  this spec draws it as analytics with counts only (§2.4)
@ row D09-G10 · col 4
  the owner
@ row D09-G10 · col 4
  E15-X01
@ row D09-G10 · col 4
  `14`'s owner
@ row D09-G11 · col 1
  D09-G11
@ row D09-G11 · col 2
  The data class and the sharing claim: `exportWorkspace`'s description makes the sharing
  claim (`22:12846`), while `21:5079` classes the pane columns P0 and E15-X01 classes the
  file user-confidential (`BL:721`)
@ row D09-G11 · col 3
  `22`'s description drops the sharing claim and names the class
@ row D09-G11 · col 3
  this spec writes the caveat instead (BQ-2 RULED)
@ row D09-G11 · col 4
  `22`'s owner
@ row D09-G11 · col 4
  the owner (#2701) for the class
@ row D09-G12 · col 1
  D09-G12
@ row D09-G12 · col 2
  No E15 STRIDE model exists (C-12.1), so no `SR-E15-nn` can be cited
@ row D09-G12 · col 2
  E15-X01 is its ticket (`BL:700`)
@ row D09-G12 · col 3
  E15-X01's model
@ row D09-G12 · col 3
  until it lands, the review of the trust copy cites `04`'s SR-040, SR-097 and SR-127
@ row D09-G12 · col 4
  E15-X01
@ row D09-G12 · col 4
  the security program's owner
@ row D09-G13 · col 1
  D09-G13
@ row D09-G13 · col 2
  Two lists of reasons: the ticket's six (`version-newer`, `version-older`, `malformed`,
  `oversized`, `wrong-type`, `budget-exceeded`) against E15-D02's and E15-S07's five
  (`size`, `parse`, `schema`, `version`, `semantic`
@ row D09-G13 · col 2
  `FL:170`
@ row D09-G13 · col 2
  `D02:522`)
@ row D09-G13 · col 2
  and two sets of event fields, `panelCount` and the rest against `{panes, dropped,
  migratedFrom}` (`BL:1136`)
@ row D09-G13 · col 3
  BQ-11's alias table in E15-S07's Observability: `version-newer` and `version-older` are
  `version`
@ row D09-G13 · col 3
  `malformed` is `parse` or `schema`, the depth and the count of values `parse`
@ row D09-G13 · col 3
  `oversized` is `size`
@ row D09-G13 · col 3
  `wrong-type` is `parse`
@ row D09-G13 · col 3
  `budget-exceeded` is `semantic`
@ row D09-G13 · col 3
  one name per field
@ row D09-G13 · col 4
  E15-S07
@ row D09-G14 · col 1
  D09-G14
@ row D09-G14 · col 2
  The file-name slug rule: whoever names the file applies it (BQ-8 RULED the pattern)
@ row D09-G14 · col 3
  §2.4's rule, in the client or in E15-S07's export
@ row D09-G14 · col 4
  E15-S07
@ row D09-G15 · col 1
  D09-G15
@ row D09-G15 · col 2
  An export carries the caller's whole live preset library, at most 500 and never truncated
  (`22:21417–21419`), not only the presets this workspace's panes use, while the Included
  list's "3 indicator presets" reads as the workspace's own
@ row D09-G15 · col 3
  the owner (#2701) chooses: the Included list says "all 3 of your indicator presets", or
  the bundle carries only the presets the panes reference (`22`'s owner)
@ row D09-G15 · col 4
  the owner (#2701)
@ row D09-G15 · col 4
  `22`'s owner
@ prose
  **C
@ prose
  contradictions, each with its owner.**
@ row Id · col 1
  Id
@ row Id · col 2
  Contradiction
@ row Id · col 3
  Owner
@ row D09-C1 · col 1
  D09-C1
@ row D09-C1 · col 2
  the ticket's deliverable path `docs/design/specs/e15-workspace-import-export.md`
  (`BL:266`) against this file beside its E15 siblings (`14:639`
@ row D09-C1 · col 2
  the first deviation
@ row D09-C1 · col 2
  BQ-1 RULED)
@ row D09-C1 · col 3
  the owner
@ row D09-C2 · col 1
  D09-C2
@ row D09-C2 · col 2
  the ticket's branch `design/e15-workspace-import-export-hifi` against
  `design/e15-d09-hifi` (C-4.4
@ row D09-C2 · col 2
  the second deviation
@ row D09-C2 · col 2
  BQ-1 RULED)
@ row D09-C2 · col 3
  the owner
@ row D09-C3 · col 1
  D09-C3
@ row D09-C3 · col 2
  the ticket's Included list names densities, which `WorkspaceBundle` does not hold
  (`22:21402–21423`
@ row D09-C3 · col 2
  `D02:507`) (the third deviation
@ row D09-C3 · col 2
  BQ-2 RULED)
@ row D09-C3 · col 3
  the owner
@ row D09-C4 · col 1
  D09-C4
@ row D09-C4 · col 2
  BQ-10 RULED a symbol cap of 16 from the pattern's `{2,16}`
@ row D09-C4 · col 2
  a symbol is at most 20 characters with its `USDT` (`22:20057`), so the cap here is 20 (the
  fourth deviation
@ row D09-C4 · col 2
  D09-Q1)
@ row D09-C4 · col 3
  the orchestrator
@ row D09-C5 · col 1
  D09-C5
@ row D09-C5 · col 2
  E15-D02's sentence "Never included: API keys or tokens, account or trade-group ids, user
  ids, P&L figures, positions or orders." (`D02:511`) is extended by BQ-2's to name
  credentials, accounts, the environment binding and the alert and rule bindings (AC 1): an
  extension, not a contradiction, and E15-D02's sentence is never shown on a frame
@ row D09-C5 · col 3
  E15-D02, at its next revision
@ row D09-C6 · col 1
  D09-C6
@ row D09-C6 · col 2
  `D02:516`'s reason "not known to this version" against AC 3's "not available in this
  version" (`BL:266`)
@ row D09-C6 · col 3
  E15-D02, at its next revision
@ row D09-C7 · col 1
  D09-C7
@ row D09-C7 · col 2
  `14:640`'s item "version-mismatch state ('exported from a newer version - 2 panels will be
  dropped')" against US-LAY-007's refusal (`11:2871`) and AC 2: drawn as the refusal (§13),
  and D09-A17 rewrites the item
@ row D09-C7 · col 3
  `14`'s owner
@ row D09-C8 · col 1
  D09-C8
@ row D09-C8 · col 2
  `14:632`'s "accounts remapped", `14:633`'s "inaccessible account references remap to the
  user's default account" and AC 4's "remapped to the importer's default" against
  US-LAY-007's drop (`11:2868`) and BQ-3 RULED
@ row D09-C8 · col 2
  D09-A12 and D09-A13 rewrite both lines
@ row D09-C8 · col 3
  `14`'s owner
@ row D09-C8 · col 3
  the owner (#2701)
@ row D09-C9 · col 1
  D09-C9
@ row D09-C9 · col 2
  the ticket's risk "R13 Sharing abuse" (its `risk` field, `BL:242–259`), which E15-X01
  carries too (`BL:700`), against the register's R13, "Team & knowledge" (`32:47`)
@ row D09-C9 · col 3
  the plan's owner
@ row D09-C10 · col 1
  D09-C10
@ row D09-C10 · col 2
  CMP-234 ValidationPanel, which the ticket and E15-S07 name for the report (`BL:1136`),
  anchors its entries to rule rows and nodes (`15:2738–2742`)
@ row D09-C10 · col 2
  the report here is a region with a table (BQ-12 RULED)
@ row D09-C10 · col 3
  E15-S07's owner
@ row D09-C10 · col 3
  the design system's owner
@ row D09-C11 · col 1
  D09-C11
@ row D09-C11 · col 2
  `04:1182` marks a Viewer ✔(own) on saving layouts against `04:1141`, where a Viewer holds
  no `workspaces:write`, and E15-D01's locked list (`D02:84`)
@ row D09-C11 · col 2
  this spec draws the Viewer's Import… in T2, and the server enforces either way (C-12.4)
@ row D09-C11 · col 3
  `04`'s owner
@ row D09-C12 · col 1
  D09-C12
@ row D09-C12 · col 2
  a refusal at the send speaks politely here (§7), against slice 4's conventions 33, which
  speaks a refusal at its point of action assertively (`S4:140`)
@ row D09-C12 · col 3
  E05-D02's owner
@ row D09-C13 · col 1
  D09-C13
@ row D09-C13 · col 2
  `D02:515` names the check's steps in its line (size, format, schema, version, panels)
@ row D09-C13 · col 2
  the value text here counts them instead, because "schema" and "registry" are not a
  trader's words (§3.4)
@ row D09-C13 · col 3
  E15-D02, at its next revision
@ row D09-C14 · col 1
  D09-C14
@ row D09-C14 · col 2
  the ticket's `version-older` as a rejection reason (`BL:266`) against E15-S07's older file
  migrated forward (`BL:1136`): reconciled by BQ-4 RULED, where `version-older` names only a
  file older than the oldest version this app still reads
@ row D09-C14 · col 3
  E15-S07, whose Observability gains `version-older`
@ row D09-C15 · col 1
  D09-C15
@ row D09-C15 · col 2
  the ruled BQ drafts' copy, refined here and PROPOSED: BQ-11's older refusal ended "Open it
  in a version 1 app and export it again.", which a file older than every format version 1
  app reads cannot follow, so it reads "Update the app that exported it, then export it
  again."
@ row D09-C15 · col 2
  BQ-5's panes sentence named the layout, a string from the file, so it names the count
  alone
@ row D09-C15 · col 2
  BQ-6's budget sentence said 16.7 ms where C-14.2's budget is 16 ms
@ row D09-C15 · col 2
  BQ-10's caption and BQ-12's success line counted 2 dropped where the tool's fixture drops
  3
@ row D09-C15 · col 3
  the orchestrator (6396085915)
@ row D09-C16 · col 1
  D09-C16
@ row D09-C16 · col 2
  SCR-025's "export as template" (`14:618`) against `exportWorkspace`, which exports a
  workspace file (`22:12843`)
@ row D09-C16 · col 2
  D09-A18
@ row D09-C16 · col 3
  `14`'s owner
@ row D09-C17 · col 1
  D09-C17
@ row D09-C17 · col 2
  the ticket's 30-panel file (`BL:266`), meant for the budget's confirm, holds more panes
  than the 16 a layout holds (`D02:133`), so it is the panes variant of
  `SCR-026/rejected-malformed`, never the budget (BQ-5 and BQ-6 RULED)
@ row D09-C17 · col 3
  the owner
@ row D09-C18 · col 1
  D09-C18
@ row D09-C18 · col 2
  the ticket's Scope lists intervals among what the export preview enumerates (`BL:266`),
  against E15-D02's Included sentence (`D02:511`), in which a panel's interval is one of
  "each panel's settings": the sentence is kept as E15-D02 wrote it (the fifth deviation
@ row D09-C18 · col 2
  BQ-2 RULED: the Included list names only what the bundle holds)
@ row D09-C18 · col 3
  the owner
@ row D09-C19 · col 1
  D09-C19
@ row D09-C19 · col 2
  BQ-13's draft, ruled as proposed, named a target of at least 44 px comfortable and 24
  compact
@ row D09-C19 · col 2
  the design system's controls are `size.control.height`, 32 px comfortable and 24 px
  compact, and `05:100`'s floor is 24 px (`size.target.min`), which every target here meets
  (§3.2)
@ row D09-C19 · col 3
  the orchestrator (6396085915)
@ prose
  **A
@ prose
  amendments to other specs.** D09-A1 to D09-A11 are §10's (`15` and `tools/contrast/`) and
  D09-A12 to D09-A19 are §11's (`14`)
@ prose
  the three below go to E15 specs: D09-A20 to merged E15-D03, D09-A21 to merged E15-D08
  (`fb1b4804`) and D09-A22 to merged E15-D03 and to merged E15-D05 (`01356263`), named only
  and never cited by line.
@ row Id · col 1
  Id
@ row Id · col 2
  Amendment
@ row Id · col 3
  Owner
@ row D09-A20 · col 1
  D09-A20
@ row D09-A20 · col 2
  E15-D03's deck gains the import's three cost strings, adapted from `layout.cost.title`,
  `.body` and `.confirm` (`D03:629–631`): `layout.cost.import.title` "Open {layout} with
  {panels}?", `layout.cost.import.body`, its measured and estimated sentence with the
  import's clause (§9), and `layout.cost.import.confirm` "Import anyway" (BQ-6 RULED)
@ row D09-A20 · col 3
  E15-D03, at its next revision
@ row D09-A21 · col 1
  D09-A21
@ row D09-A21 · col 2
  SCR-025's Share section: its Export… opens this spec's export dialog (§2.2), and its help
  line names what the file leaves out in BQ-2's classes, or points at the Excluded list, and
  never makes the sharing claim
@ row D09-A21 · col 3
  E15-D08 (merged, `fb1b4804`)
@ row D09-A22 · col 1
  D09-A22
@ row D09-A22 · col 2
  Import… as an item of the rail's workspace menu (SCR-011), beside Export…, opening the
  same empty dialog (§3.2
@ row D09-A22 · col 2
  BQ-9 RULED): E15-D03's R-5 (`D03:564`) gains the rail's row, and the rail's menu gains the
  item
@ row D09-A22 · col 3
  E15-D03, at its next revision
@ row D09-A22 · col 3
  E15-D05, the rail's owner (merged, `01356263`)
@ prose
  **Q
@ prose
  open questions
@ prose
  the default built is named.**
@ row Id · col 1
  Id
@ row Id · col 2
  Question
@ row Id · col 3
  Built now
@ row Id · col 4
  Owner
@ row D09-Q1 · col 1
  D09-Q1
@ row D09-Q1 · col 2
  the symbol cap: BQ-10's 16, or the contract's 20 (`22:20057`)?
@ row D09-Q1 · col 3
  20, the contract's (the fourth deviation)
@ row D09-Q1 · col 4
  the orchestrator
@ row D09-Q2 · col 1
  D09-Q2
@ row D09-Q2 · col 2
  where a browser has no save picker, does the download hand-off count as the save, for the
  completion step and for `workspace.exported`?
@ row D09-Q2 · col 3
  yes: the hand-off is the only answer the page gets (§2.4)
@ row D09-Q2 · col 4
  the owner
@ row D09-Q2 · col 4
  E15-S07
@ row D09-Q3 · col 1
  D09-Q3
@ row D09-Q3 · col 2
  CMP-036 for the export's lists: an A-row for a list value and a stacked layout, or another
  list atom?
@ row D09-Q3 · col 3
  two CMP-036 rows in one `dl`, each value a `ul` (§2.3)
@ row D09-Q3 · col 3
  D09-A11 re-binds its tokens (`15:395`)
@ row D09-Q3 · col 4
  the design system's owner
@ row D09-Q4 · col 1
  D09-Q4
@ row D09-Q4 · col 2
  the desktop shell's save: does its renderer reach a save picker, or does it need a save
  bridge that returns the base name only?
@ row D09-Q4 · col 3
  the platform's save sheet, the page learning the base name only (§2.4)
@ row D09-Q4 · col 4
  the desktop shell's owner
@ row D09-Q5 · col 1
  D09-Q5
@ row D09-Q5 · col 2
  the schema step reads `schema_version` from the envelope ahead of its shape rules, so a
  newer or an older file meets its version refusal and never a shape failure: confirmed?
@ row D09-Q5 · col 3
  yes (§3.4, step 3
@ row D09-Q5 · col 3
  §5.3)
@ row D09-Q5 · col 4
  the orchestrator
@ row D09-Q6 · col 1
  D09-Q6
@ row D09-Q6 · col 2
  the trust note's "Importing creates a new workspace and changes nothing else." stands
  beside Add rows for indicator presets, chart templates and drawings, which join the
  importer's own libraries (`22:21422–21425`, counted against the 500-preset cap): is the
  sentence kept word for word?
@ row D09-Q6 · col 3
  the ruled sentence, verbatim (BQ-2 RULED)
@ row D09-Q6 · col 4
  the owner (#2701)
@ row D09-Q7 · col 1
  D09-Q7
@ row D09-Q7 · col 2
  the newer refusal's ruled way on, "Export it again from a version 1 app, or update this
  app.", prints the format number as an app's version
@ row D09-Q7 · col 2
  the alternative "Export it again from an app that writes format version 1, or update this
  app." names what is compared
@ row D09-Q7 · col 3
  the ruled sentence (BQ-4 RULED)
@ row D09-Q7 · col 4
  the owner (#2701)
@ prose
  **Hand-offs.** E15-D03 and E15-D06 are merged (`c4989493`, `6e2c1211`), and E15-D04
  (`c73aec08`) is pinned with nothing taken from it
@ prose
  E15-D08 (#4503) is merged (`fb1b4804`) and named only.
@ prose
  Each row is a PROPOSED hand-off for its owner to take or refuse.
@ row To · col 1
  To
@ row To · col 2
  Takes from this spec
@ row To · col 3
  State
@ row E15-S07 (the import and export story) · col 1
  E15-S07 (the import and export story)
@ row E15-S07 (the import and export story) · col 2
  D09-G1 to D09-G8, D09-G13 and D09-G14 (BQ-3 RULED)
@ row E15-S07 (the import and export story) · col 2
  D09-C10, D09-C14
@ row E15-S07 (the import and export story) · col 2
  the five steps and their limits (§3.4, §5.4)
@ row E15-S07 (the import and export story) · col 2
  the alias table (D09-G13)
@ row E15-S07 (the import and export story) · col 3
  —
@ row `22`'s owner · col 1
  `22`'s owner
@ row `22`'s owner · col 2
  D09-G1, the atomic import with its `Idempotency-Key`, contract first (C-6.1), with D09-G2
  to D09-G8, D09-G11 and D09-G15
@ row `22`'s owner · col 3
  —
@ row E15-D08 (SCR-025 settings) · col 1
  E15-D08 (SCR-025 settings)
@ row E15-D08 (SCR-025 settings) · col 2
  Export… in its Share section opening §2's dialog (BQ-7 RULED)
@ row E15-D08 (SCR-025 settings) · col 2
  D09-A21
@ row E15-D08 (SCR-025 settings) · col 2
  if E15-D08 changes the entry, §2.2 follows it
@ row E15-D08 (SCR-025 settings) · col 3
  merged (`fb1b4804`)
@ row E15-D03 (SCR-020 chrome) · col 1
  E15-D03 (SCR-020 chrome)
@ row E15-D03 (SCR-020 chrome) · col 2
  D09-A20, D09-A22
@ row E15-D03 (SCR-020 chrome) · col 2
  Import… in "+" and Export… in `[⋯]` keep their keys (§6)
@ row E15-D03 (SCR-020 chrome) · col 3
  merged
@ row E15-D05 (SCR-011 rail) · col 1
  E15-D05 (SCR-011 rail)
@ row E15-D05 (SCR-011 rail) · col 2
  D09-A22: Import… in the rail's workspace menu
@ row E15-D05 (SCR-011 rail) · col 3
  merged (`01356263`)
@ row E15-X01 (STRIDE) · col 1
  E15-X01 (STRIDE)
@ row E15-X01 (STRIDE) · col 2
  D09-G10 with the export under view-as, D09-G11, D09-G12
@ row E15-X01 (STRIDE) · col 2
  the four hazards of §1.2 as its starting list
@ row E15-X01 (STRIDE) · col 3
  —
@ row E15-D14, E15-D15, E15-D16 · col 1
  E15-D14, E15-D15, E15-D16
@ row E15-D14, E15-D15, E15-D16 · col 2
  the motion of both dialogs (out of scope here)
@ row E15-D14, E15-D15, E15-D16 · col 2
  §7's keyboard model and desk pass for the screen-reader script
@ row E15-D14, E15-D15, E15-D16 · col 2
  the frames, the deck and the G-rows for the hand-off pack
@ row E15-D14, E15-D15, E15-D16 · col 3
  after this spec
@ row SCR-089's owner (E35, E36) · col 1
  SCR-089's owner (E35, E36)
@ row SCR-089's owner (E35, E36) · col 2
  the reuse note (D09-A19, §11)
@ row SCR-089's owner (E35, E36) · col 3
  —
@ row the design system; `14`'s owner; `24`'s  · col 1
  the design system
@ row the design system; `14`'s owner; `24`'s  · col 1
  `14`'s owner
@ row the design system; `14`'s owner; `24`'s  · col 1
  `24`'s owner
@ row the design system; `14`'s owner; `24`'s  · col 1
  `04`'s owner
@ row the design system; `14`'s owner; `24`'s  · col 2
  D09-A1 to D09-A11, D09-Q3
@ row the design system; `14`'s owner; `24`'s  · col 2
  D09-A12 to D09-A19
@ row the design system; `14`'s owner; `24`'s  · col 2
  D09-G9
@ row the design system; `14`'s owner; `24`'s  · col 2
  D09-C11
@ row the design system; `14`'s owner; `24`'s  · col 3
  —
@ row the desktop shell's owner · col 1
  the desktop shell's owner
@ row the desktop shell's owner · col 2
  D09-Q4
@ row the desktop shell's owner · col 3
  —
@ row the orchestrator; the owner (#2701) · col 1
  the orchestrator
@ row the orchestrator; the owner (#2701) · col 1
  the owner (#2701)
@ row the orchestrator; the owner (#2701) · col 2
  D09-Q1, D09-Q5, D09-C4, D09-C15, D09-C19
@ row the orchestrator; the owner (#2701) · col 2
  the owner-level questions BQ-2, BQ-3 and BQ-4, with D09-Q6, D09-Q7 and D09-G15 for the
  owner
@ row the orchestrator; the owner (#2701) · col 2
  the walkthrough (§14)
@ row the orchestrator; the owner (#2701) · col 3
  owner approval pending
§ §13
@ row file-picker and drag-drop paths · col 3
  boards PENDING
@ row version-mismatch state ('exported from a · col 2
  `SCR-026/rejected-version-newer` (boards 04 and 09): both versions and a way on, nothing
  imported and nothing applied in part
@ row version-mismatch state ('exported from a · col 3
  the item's words amended (D09-A17, PROPOSED)
@ row preview of what will be imported before  · col 3
  boards PENDING
@ row rejection state for malformed or oversiz · col 3
  boards PENDING
@ row import never carries credentials or acco · col 2
  the Excluded list on `SCR-025/export-preview` and `SCR-025/export-done` (boards 01 and 10)
@ row import never carries credentials or acco · col 3
  the copy's owner approval pending (#2701)
@ prose
  **SCR-025 (`14:627`)** is E15-D08's surface (merged, `fb1b4804`, named only): of its four
  items this spec draws only Export… in the Share section, part of the first item's sharing
  (§2), and the export dialog it opens
§ §14
@ row user control and freedom · col 3
  the toasts after a closed view carry the outcome (D09-D18)
@ row recognise, diagnose and recover from err · col 3
  a refusal that arrives after the view closed needs the toast's Review to recover (D09-D18)
@ prose
  posted on #363 at merge, the boards PR drawing what each names):
§ §15
@ prose
  Every ticket item, from the trace at the top, to the section that answers it, the frames
  that show it and the boards that will draw them (PENDING, §0).
@ row AC-1 the included and the excluded lists · col 3
  `SCR-025/export-preview`, `SCR-025/export-done`
@ row AC-2 a newer file refused, never applied · col 1
  AC-2 a newer file refused, never applied in part
@ row DL-4, DL-5 the file name with its format · col 3
  `SCR-025/export-done`, `SCR-025/export-cancelled`
@ row DL-20 the annotated events · col 3
  `SCR-025/export-done`, `SCR-026/report`, the six rejections, `SCR-026/budget-confirm`
@ row DoD-6 the copy signed off on the trust c · col 1
  DoD-6 the copy signed off on the trust claims
@ row DoD-6 the copy signed off on the trust c · col 3
  — (owner approval pending (#2701))
@ row DoD-9 the spec merged; CMP-067's Storybo · col 1
  DoD-9 the spec merged
@ row DoD-9 the spec merged; CMP-067's Storybo · col 1
  CMP-067's Storybook list agreed
§ §16
@ prose
  - **Ruled:** 16 <!-- audit:bq_rows=16 --> questions and 4 <!-- audit:conditions=4 -->
  conditions (6396085915)
@ prose
  the trust copy, the account rule and the version rule are the owner's, approval pending
  (#2701).
@ prose
  - **Rows:** 15 <!-- audit:rows.G=15 --> G, 19 <!-- audit:rows.C=19 --> C, 22 <!--
  audit:rows.A=22 --> A, 7 <!-- audit:rows.Q=7 --> Q and 35 <!-- audit:rows.D=35 -->
  decisions, every one PROPOSED to a named owner.
@ prose
  E15-D08 is merged (`fb1b4804`) and named only
@ prose
  the walkthrough of §14 is posted on #363 at merge.
"""


# The whole text, block by block (see the block comment above `doc_blocks`): `--repin-ruled`
# alone writes it; `--check` never re-pins.
RULED_PIN_TXT = r"""
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi#1
@ ¶0 ‖ heading ‖ 0
  # E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi
@ ¶1 ‖ paragraph ‖ 1
  **Ticket:** E15-D09 (#363) · **Epic:** E15 · **Status:** Draft — text-first; every decision
   PROPOSED unless RULED (6396085915); boards PENDING (§0: 10 <!-- audit:boards=10 --> boards, 2
   <!-- audit:light_twins=2 --> of them light twins, inside the cap of ≤ 10 boards with light twins
   ≤ 1/3; every other frame is "not drawn — the text is binding; drawn on request"). **Revision:**
   the whole text, §0 to §16, gated by the tool from its first line to its last; the boards follow
   in a second PR (§0). **Owner approval pending (#2701)** (agent-delivery adaptations, owner
   decision 2026-09-25): the owner's `approved` comment or the merge stands in for the ticket's CDO
   and Security-engineer sign-offs (§13). **Method:** a desk spec over the merged E15-D01, E15-D02,
   E15-D03 and E15-D06 text and boards, E05-D02 slice 4 and E09-D09 — a heuristic evaluation
   `(heuristic)`; no session, participant, measured time or sign-off exists and none is invented.
   **Tool:** `docs/design/_tools/e15_d09_import_export_audit.py` (stdlib, offline, `python3 -I
   -B`): its `--json` is the only source of every number here, each carrying an `audit:` marker
   that `--check` re-derives, and its `--self-test` runs 391 <!-- audit:mutations=391 --> in-memory
   mutations, each caught by exactly one new FAIL.
@ ¶2 ‖ paragraph ‖ 1
  **Penpot page:** `E15-D09 Workspace import and export` · id pending (the boards PR pins it; page
   by name + id only, `README:46`).
@ ¶3 ‖ paragraph ‖ 1
  **Scope** (the ticket): SCR-026, the workspace import — the drop zone (CMP-067) with its visible
   label and a keyboard path, the file picker, the parse and validation progress, the diff-style
   preview as a table, every rejection state, the post-import report; the export surface — Export…
   from SCR-025 and the workspace menus, the pre-export preview with what is included and,
   first-class, what is excluded, the file name with its format version, the completion; the copy
   for the trust claims; keyboard, focus and announcements; tokens, the measured contrast,
   greyscale and CVD; the A, C and G rows. **Out of scope** (the ticket): the file schema itself
   (`22` `WorkspaceBundle`, E15-S07); rule import / export (SCR-089, E35 / E36: a reuse note only);
   server-side validation; sharing beyond the file; motion (E15-D14).
@ ¶4 ‖ paragraph ‖ 1
  **Start.** `blocked_by` E15-D02 (#248): Done — text merged in #4192 at
   `1044c4f602eff6ae1a2cf42201ab398f6c4234d1`, boards in #4408 at
   `7be6eac6a705cf24ba534ce4f7d31349a1e29932`; its input E15-D01 merged in #4079 at
   `ed8a22246263ace73f39e4434e6d5f57b1a857bd`. Merged siblings, cited as merged text: E15-D03
   (#4478 at `c4989493461ec6b6d22b9254633452a6362b750e`) and E15-D06 (#4470 at
   `6e2c1211fc5f4675457d57011a346642f92710c5`); E15-D04 (#4454 at
   `c73aec08246f06d28c70e8b959c658bc1a0c4d09`), the dock system, is pinned because the ruling names
   it, and nothing of it is reused or cited here; E09-D09 (#3953 at
   `baccf724a1fa3ad66f9333e440a7f5e8668b6eff`); E05-D02 slice 4
   (`04a8caa9513e90debcf7cbc41a9ca585496eba01`). E15-D08 (#4503, Export… in SCR-025's Share
   section) merged at `fb1b48041ae0a12638beacae6a61854833c5cc4d`: named only, never cited by line;
   if it changes, this spec's export entry follows it. E15-D05 (#4507, the SCR-011 rail) merged at
   `013562636a339ab32c80d257b9d1f8cef8e64422`: named only, never cited by line; D09-A22 hands it
   the rail's Import….
@ ¶5 ‖ paragraph ‖ 1
  **Inputs pinned.** Base `origin/main` `908667f27b63c5722cb084819902bcbd7943bf28`; every
   `file:line` cite in this file is at it and the tool re-checks each (a moved line is a WARN; a
   fragment gone or ambiguous is a FAIL; a `14` line after this PR's pointer lines sits one or two
   lower). Plan: `14` SCR-025 `14:616–627`, SCR-026 `14:630–640`, SCR-089 `14:1990`; `15` CMP-001
   `15:48`, CMP-019 `15:225`, CMP-023 `15:262`, CMP-027 `15:301–307`, CMP-028 `15:311`, CMP-033
   `15:361`, CMP-038 `15:409`, CMP-043 `15:463–468`, CMP-044 `15:473`, CMP-045 `15:483`, CMP-049
   `15:524–529`, CMP-067 `15:690–696`, CMP-068 `15:699`, CMP-079 `15:811`, CMP-234 `15:2738–2742`;
   US-LAY-007 `11:2858–2874`; `22` `createWorkspace` `22:8682–8686`, the layout limit `22:8886`,
   `exportWorkspace` `22:12843–12848`, `WorkspaceInput` `22:19819`, `22:19831`, `PaneKind`
   `22:19971`, `PaneConfig` `22:20031`, the setting keys `22:20041`, the symbol `22:20057`,
   `WorkspaceBundle` `22:21402–21423`; `21:3302`, `21:5079`; `04:54`, `04:855`, `04:924`, `04:967`,
   `04:1141`, `04:1182`; `05:35`, `05:96`, `05:101`, `05:131`, `05:144`, `05:150`; the ticket
   `BL:242` and E15-S07 `BL:1111`, `BL:1136`. Merged upstream: E15-D01 (`D01:39`); E15-D02
   (`D02:84`, D-15 `D02:133`, D-30 `D02:148`, `D02:292`, `D02:507`, §5.11 `D02:509–522`, §8.1
   `D02:635–674`, `D02:732`, A-10 `D02:823`, G-12 `D02:843`, OQ-O `D02:865`, the hand-off
   `D02:950`); E15-D03 (§1.4 `D03:118`, §1.5 `D03:122`, §1.6 `D03:126`, D-12 `D03:145`, `D03:365`,
   `D03:384`, R-5 `D03:564`, V-4 `D03:583`, the deck `D03:625–636`); E15-D06 (D-9 `D06:101`); the
   flow F-LAY-6 (`FL:139–171`); E05-D02 slice 4 (H22 `S4:734`, H36 `S4:904`); E09-D09
   (`E09D09:85–95`, `E09D09:114`); the SCR-089 sibling E36-D03 (`E36D03:153–155`, `E36D03:272`,
   `E36D03:339`). Cited below and pinned the same way: E15-X01 (`BL:700`, `BL:721`) and the risk
   register (`32:47`).
@ ¶6 ‖ paragraph ‖ 1
  **Key.** `NN` = `docs/plan/NN-*.md` (`22` = `22-api-openapi.yaml`); `BL` =
   `docs/plan/backlog/E15.json`; `D01` = `docs/design/research/e15-layouts/findings.md` (E15-D01);
   `D02`, `D03`, `D06` = `docs/design/E15/E15-D02.md`, `E15-D03.md`, `E15-D06.md`; `FL` =
   `docs/design/specs/e15-layout-flows.md`; `S4` = `docs/design/E05/E05-D02-feedback-overlays.md`;
   `E09D09` = `docs/design/E09/E09-D09.md`; `E36D03` = `docs/design/E36/E36-D03.md`; `README` =
   `docs/design/README.md`; `C-x.y` = `CONSTITUTION.md`. A cite is a key, a colon and the line at
   the base, a range with an en dash. **D09-Gn** = a gap its owner closes (a contract field, a
   limit, a requirement on E15-S07), **D09-Cn** = a contradiction with its owner, **D09-An** = a
   copy-ready amendment (§10–§12), **D09-Qn** = an open question (§12), **D09-Dn** = a decision of
   this spec (§1).
@ ¶7 ‖ paragraph ‖ 1
  **Fixture** (the tool's `FIXTURE` and the contract facts it parses from text; nothing here is
   typed by hand). Export: the stored workspace Scalping with 2 <!-- audit:fixture.export_layouts=2
   --> layouts and 7 <!-- audit:fixture.export_panels=7 --> panels (`D02:511`), saved as
   `scalping.cv-workspace-v1.json`. Import: `scalping.json`, a colleague's export from a build that
   knows two more panel kinds, whose Positions pane carries an account filter that points at an
   account of the colleague's (its label stays in the tool; no frame, row or line prints it); its
   preview adds 7 <!-- audit:fixture.panels=7 --> panels and 2 <!-- audit:fixture.layouts=2 -->
   layouts, drops 3 <!-- audit:fixture.dropped=3 --> items, 2 <!-- audit:fixture.unknown_kinds=2
   --> of them unknown kinds, and remaps 1 <!-- audit:fixture.remapped=1 -->. The app reads format
   version 1 <!-- audit:fixture.app_format=1 -->; the newer file is format version 2 <!--
   audit:fixture.newer_format=2 -->, the older one format version 0 <!--
   audit:fixture.older_format=0 -->. The budget fixture `wall.json` opens Wall with 12 <!--
   audit:fixture.budget_panels=12 --> panels: 11.8 <!-- audit:fixture.measured_ms=11.8 --> ms per
   frame measured now, about 17.9 <!-- audit:fixture.estimate_ms=17.9 --> ms estimated, against the
   budget of 16 <!-- audit:contract.budget_ms=16 --> ms p95 (C-14.2). The limits: a file of at most
   2 <!-- audit:contract.size_mb=2 --> MB (E15-S07's default, `BL:1136`), checked within 500 <!--
   audit:contract.parse_ms=500 --> ms (`14:637`); nesting depth at most 16 <!--
   audit:contract.depth=16 --> (`22:19819`); at most 10,000 <!-- audit:contract.nodes=10000 -->
   values (`BL:1136`; PROPOSED, D09-G5); at most 32 <!-- audit:contract.layouts_max=32 --> layouts
   a workspace (`22:8886`) and 16 <!-- audit:contract.panes_max=16 --> panes a layout (`D02:133`);
   at most 32 <!-- audit:contract.workspaces_max=32 --> workspaces a user (`22:8686`); at most 200
   <!-- audit:contract.presets_max=200 --> indicator presets a file, whole or not at all
   (`22:21422–21423`). The caps on a string from the file: names 40 <!-- audit:contract.name_max=40
   --> (`22:19831`), symbols 20 <!-- audit:contract.symbol_max=20 --> (`22:20057`), panel kinds 32
   <!-- audit:contract.kind_max=32 --> (PROPOSED: `PaneKind` has no length bound, `22:19971`, so
   the setting keys' cap of `22:20041` stands in; D09-G5), drawing labels 120 <!--
   audit:contract.label_max=120 --> (`21:3302`), keys 64 <!-- audit:design.key_cap=64 --> and file
   names 40 <!-- audit:design.file_cap=40 --> (PROPOSED). The import dialog is CMP-043 `size="lg"`,
   at most 960 <!-- audit:contract.dialog_lg_px=960 --> px wide; the export dialog is `size="md"`,
   at most 560 <!-- audit:contract.dialog_md_px=560 --> px (`15:463–468`).
@ ¶8 ‖ paragraph ‖ 1
  **Deviations (recorded, not hidden; each is also a C-row in §12).**
@ ¶9 ‖ list ‖ 1
  - **Deviation — the deliverable path.** The ticket asks for
   `docs/design/specs/e15-workspace-import-export.md` (`BL:266`); the spec is this file, beside its
   E15 siblings (`14:639`), with its gate tool (BQ-1 RULED).
  - **Deviation — the branch.** The ticket names `design/e15-workspace-import-export-hifi`; the
   work is on `design/e15-d09-hifi` (C-4.4; BQ-1 RULED).
  - **Deviation — the densities.** The ticket's Included list names densities; `WorkspaceBundle`
   holds none (`22:21402–21423`; density is global or per panel, `D02:507`), so a C-row records the
   densities, and the Included list names only what the bundle holds (BQ-2 RULED).
  - **Deviation — the symbol cap.** BQ-10 RULED reads 16 for symbols from the pattern's `{2,16}`;
   a symbol is at most 20 characters with its `USDT` (`22:20057`), so the cap here is the
   contract's 20 and D09-Q1 asks the orchestrator to confirm it; every other number of BQ-10
   stands.
  - **Deviation — the intervals.** The ticket's Scope lists intervals among what the export
   preview enumerates (`BL:266`); the Included sentence is E15-D02's (`D02:511`), in which each
   panel's interval is one of "each panel's settings", so the intervals take no clause of their
   own, and the import's table names each panel's interval in its Item cell (§4.2; D09-C18).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi ›
   Acceptance-criteria trace (#363)#1
@ ¶0 ‖ heading ‖ 1
  ## Acceptance-criteria trace (#363)
@ ¶1 ‖ paragraph ‖ 1
  Status: **done** = specified here · **heuristic-only** = by the adaptation · **routed** = its
   owner named (a drawing's owner is the boards PR, §0) · **text pending** = its section is still a
   placeholder (the tool fails this word once no placeholder is left).
@ ¶2 ‖ table ‖ 1
  | Id | Ticket item | Where | Status |
  | --- | --- | --- | --- |
  | AC-1 | "The user learns what travels before exporting": the included and the excluded lists,
   the excluded one naming accounts, environment binding and credentials |
   `SCR-025/export-preview`, `SCR-025/export-done` (§2.1); the Excluded sentence byte for byte
   (BQ-2 RULED) | done |
  | AC-2 | "A newer-version file is refused, not partially applied": both versions named, no
   option that applies part of the file | `SCR-026/rejected-version-newer` (§5.1); BQ-4 and BQ-11
   RULED | done |
  | AC-3 | "Unknown panel types are reported, not silently dropped": both listed by stored type
   name with the ticket's reason, and the report repeats them | §4.2 rows 1–2 and §4.3 rows 1–2;
   `SCR-026/preview`, `SCR-026/report` | done |
  | AC-4 | "Account references are remapped and disclosed": shown dropped, the report in plain
   language, naming no account the importer cannot see | §4.2 rows 3–4 (BQ-3 RULED: dropped and
   listed); `SCR-026/report` | done |
  | AC-5 | "The file is malformed or oversized": the problem and the limit named, the dialog open
   for another file | `SCR-026/rejected-malformed`, `SCR-026/rejected-oversized` (§5.1) | done |
  | AC-6 | "Import is performed without a pointer": a keyboard path for every step, the table read
   as a table with headers | `SCR-026/pick` (Choose file…, the drop zone off the Tab order), §7,
   board 08 | done |
  | DL-1 | Export surface: the entry from SCR-025 and from the workspace menu |
   `SCR-025/export-entry` (§2.1; BQ-7 RULED) | done |
  | DL-2 | The pre-export preview's included list | `SCR-025/export-preview` | done |
  | DL-3 | The excluded list, first-class | `SCR-025/export-preview`, `SCR-025/export-done` | done
   |
  | DL-4 | The file name with the schema version | `SCR-025/export-done`; BQ-8 RULED | done |
  | DL-5 | The export completion state | `SCR-025/export-done` | done |
  | DL-6 | SCR-026 import hi-fi in both themes: the drop zone with a visible label, the keyboard
   alternative, the picker | `SCR-026/pick`; boards 02 and 09 | done |
  | DL-7 | The diff-style preview as a table, never a canvas | §4.2; `SCR-026/preview` | done |
  | DL-8 | Item, type, action, reason; drops and remaps first | §4.2 | done |
  | DL-9 | The validation states | §5.1; `SCR-026/preview-over-budget` | done |
  | DL-10 | The post-import report, persistent and copyable | `SCR-026/report`; §4.3 | done |
  | DL-11 | Parse and validation progress for large files | `SCR-026/validating` | done |
  | DL-12 | The copy set for the trust claims, word by word | §9; BQ-2 RULED, owner approval
   pending (#2701) | done |
  | DL-13 | Redlines and the spec page | this file (the first deviation) | done |
  | DL-14 | The Storybook list for CMP-067 | §10 (an A-row) | done |
  | DL-15 | The constructive route on a refusal | `SCR-026/rejected-version-newer`,
   `SCR-026/rejected-version-older` | done |
  | DL-16 | The budget overflow through US-LAY-001's confirm | `SCR-026/budget-confirm` | done |
  | DL-17 | The untrusted-string rule | §1.2 (Condition 1); the caps and renders clauses of §3–§5
   | done |
  | DL-18 | The limits stated; no environment travels; the server re-checks | the Fixture
   paragraph; §1.2; `SCR-026/validating`; §5.4 | done |
  | DL-19 | The accessibility notes: caption with counts, action as text, errors announced, report
   region, polite progress | §4, §7 | done |
  | DL-20 | The annotated events | the event clauses of §2–§5; §12 | done |
  | DL-21 | The reuse note for SCR-089 | §11 | done |
  | DoD-1 | Export preview drawn with both lists | `SCR-025/export-preview` (§2.1); board 01 is
   the boards PR's (§0) | routed |
  | DoD-2 | SCR-026 drawn in both themes: drop zone, picker, preview table, the six validation
   states, the report | §3–§5 and §8; boards 02–06, 09 and 10 are the boards PR's (§0) | routed |
  | DoD-3 | The version mismatch names both versions and a constructive step; no partial-apply
   path | `SCR-026/rejected-version-newer` | done |
  | DoD-4 | Diff indicators text plus icon; contrast and colour vision checked | §8 (the tool's
   numbers) | done |
  | DoD-5 | Keyboard-only walkthrough incl. file selection; the table navigable with headers | §7;
   the owner's walk on board 08 (§14) | heuristic-only |
  | DoD-6 | The copy signed off on the trust claims | the owner's `approved` (#2701) | routed |
  | DoD-7 | The untrusted-string rule and the limits stated | §1.2; §5.4; §5.5; the Fixture
   paragraph | done |
  | DoD-8 | SCR-026's sign-off items satisfied | §13 | done |
  | DoD-9 | The spec merged; CMP-067's Storybook list agreed | this PR; §10 | routed |
  | DoD-10 | The reuse note for SCR-089 filed | §11 | done |
  | DoD-11 | The CDO sign-off recorded | the owner | routed |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › The questions
   (BQ-1…BQ-16) — RULED by the orchestrator: 6396085915, on the BQ comment 6396029607#1
@ ¶0 ‖ heading ‖ 1
  ## The questions (BQ-1…BQ-16) — RULED by the orchestrator: 6396085915, on the BQ comment
   6396029607
@ ¶1 ‖ table ‖ 1
  | # | Question | Built here (the ruled outcome) | Status |
  | --- | --- | --- | --- |
  | BQ-1 | the deliverable path, the branch, the Penpot page, the `14` / `15` edit set, the PR |
   this file, `docs/design/E15/E15-D09.md`, and its tool `e15_d09_import_export_audit.py`; the
   ticket's spec path and branch are the first two deviations; the Penpot page `E15-D09 Workspace
   import and export`; two content-only `14` pointer lines, after SCR-025's checklist (`14:627`)
   and SCR-026's (`14:640`), and PROPOSED A-rows for `14:632–633` and `14:640` (§11); no `15` edit
   — A-rows only (§10); the PR says `Refs #363` and `Partial:`, never a closing keyword | RULED
   (6396085915) |
  | BQ-2 | the trust claims, word for word | the Excluded list, first-class and drawn as a list,
   in AC 1's words: "Never included: credentials — API keys or tokens; accounts, trade-group and
   user ids; environment binding (DEMO or LIVE); alert and rule bindings; P&L, positions or
   orders." — a C-row to `D02:511`, an extension and not a contradiction; the Included list names
   only what `WorkspaceBundle` holds (`22:21402–21423`); the import's trust note is `D02:513`
   verbatim: "A workspace file never carries credentials or account bindings. Importing creates a
   new workspace and changes nothing else."; the sharing claim in `22:12846`'s description is never
   written anywhere (its G-row names it without repeating it); the tool gates both sentences byte
   for byte on every frame that shows them; owner approval pending (#2701) | RULED (6396085915) —
   owner approval pending (#2701) |
  | BQ-3 | account-scoped elements on import | dropped and listed, never remapped, and no account
   the importer cannot see is ever named in the preview, the report or a reason: its row reads
   "workspaces never carry account bindings" (§4.2 row 3); the word "Remap" is kept for the one
   true remap, the Positions pane that shows your own accounts (§4.2 row 4); `14:632–633` and the
   checklist item of `14:640` get PROPOSED A-rows (§11); E15-S07 receives D09-G1…G8, G13 and G14 by
   hand-off row (§12) | RULED (6396085915) — owner approval pending (#2701) |
  | BQ-4 | the version rule | a newer file refused with both versions and the constructive second
   sentence, no Import verb (`SCR-026/rejected-version-newer`); an older compatible file migrated
   forward with "Migrated from format version 1 to 2." (E15-S07's rule,
   `SCR-026/preview-migrated`); an older unsupported file refused with both versions
   (`SCR-026/rejected-version-older`, the ticket's `version-older`); the comparison on
   `schema_version`, never an app version | RULED (6396085915) — owner approval pending (#2701) |
  | BQ-5 | size, shape and the refused parse | the five check steps in order, size → parse depth /
   node count → schema → version → per-pane registry → preview; nothing is created before Import as
   new workspace and nothing kept after a refusal; the limits in copy rendered from the tool's
   facts (the Fixture paragraph), the node count PROPOSED with D09-G5; every refusal says "Nothing
   was imported." | RULED (6396085915) |
  | BQ-6 | the panel budget on a valid file | per layout, for the layout that opens: caught in the
   preview as the caption's last sentence and a warning line (`SCR-026/preview-over-budget`), then
   applied through US-LAY-001's CMP-044 confirm re-verbed "Import anyway", its Cancel focused
   (`SCR-026/budget-confirm`); a confirm, not a refusal, whose cancel fires `budget-exceeded` |
   RULED (6396085915) |
  | BQ-7 | the export surface and Export…'s availability | Export… in three places — SCR-025's
   Share section (E15-D08, merged at `fb1b4804`), the tab's `[⋯]` (`D03:384`) and the rail's
   workspace menu (`D02:511`) — and one CMP-043 `md` dialog with the Included and Excluded lists
   built from the fetched bundle; Export… is a read (`22:12843`), never gated (a read): T1 for
   every session, view-as included; on the viewer's unsaved default it is an availability state
   (`D03:583`) | RULED (6396085915) |
  | BQ-8 | the file name and the completion | `<slug>.cv-workspace-v<schema_version>.json`, the
   slug the workspace name lower-cased, ASCII-folded, every other character a `-`, capped like a
   name (D09-G14); the fixture `scalping.cv-workspace-v1.json`; a drawn completion step naming the
   saved file (`SCR-025/export-done`); a dismissed save sheet keeps the preview
   (`SCR-025/export-cancelled`) | RULED (6396085915) |
  | BQ-9 | the import dialog | CMP-043 `lg` with its steps in one chrome — choose, validating,
   preview, the send, the report; Choose file… a real button fronting the labelled native input;
   the drop zone not a Tab stop; a name clash disambiguated by the server (`D02:516`); Cancel,
   `Esc` and × before the send close the dialog with nothing imported | RULED (6396085915) |
  | BQ-10 | the preview table | CMP-049 table mode, the caption first with the counts; the columns
   Item · Type · Action · Reason; drops and remaps first, additions after; exactly three Action
   words, each a word with a decorative glyph; the unknown kinds by stored name with the ticket's
   reason; strings from the file as text, capped (the Fixture paragraph; the symbol cap is the
   fourth deviation) | RULED (6396085915) |
  | BQ-11 | the rejection frames | six CMP-027 `inline` frames, `live="polite"`, the dialog kept
   open with Choose another file focused beside its Cancel; no Import verb on any of them (AC 2:
   omitted, never T2-locked); each names its problem and its limit and says "Nothing was
   imported."; each fires one `layout.import_rejected{reason}` | RULED (6396085915) |
  | BQ-12 | the post-import report | the dialog's final step, a `role="region"` named "Import
   report" with the table re-rendered (§4.3) and Copy report (CMP-033); it stays until Close and is
   never a toast | RULED (6396085915) |
  | BQ-13 | the keyboard path and the tree | Choose file… is a real `<button>` whose `Enter` or
   `Space` opens the OS picker; the drop zone only adds to the input; the table is one Tab stop
   read with its headers; each announcement polite and once (§7) | RULED (6396085915) |
  | BQ-14 | T2 per role, view-as first | Import… is a write (`22:8682`): its legs in the server's
   order, view-as first (`rbac.view_as`), then the permission (`rbac.permission`), then the state
   (`workspace.limit.count`), keys as merged E15-D02 (`D02:655`) and E15-D03 (`D03:564`) carry
   them; Export… is never gated; a rejected file never T2-locks Import because the verb is absent;
   an absence is never a lock and validity is never a lock; T2 is stated once (§6) | RULED
   (6396085915) |
  | BQ-15 | the boards under the cap | ten boards with at most three light twins — two here (§0);
   every other frame not drawn, the text binding, drawn on request | RULED (6396085915) |
  | BQ-16 | the gate tool, the mutation list and the G-rows | the tool in E15-D08's form with
   D09's own row ids: per-frame gates over every row of every table and the prose, case-insensitive
   vocabulary lists, whole clauses; S1–S20 each a `--self-test` mutation; the G-rows D09-G1…G14 to
   `22`'s owner (`22` first, C-6.1) | RULED (6396085915) |
  | Condition 1 | security — every string from the file is untrusted | every string from the file
   is untrusted: text only, never markup and never a link, capped with the cap stated, the
   malformed reason naming the key in mono, truncated; the report echoes no raw file content beyond
   those capped names; the client's parse is a courtesy — the server re-checks size, depth, nodes,
   schema and version (E15-S07) and `SCR-026/validating` says so; a refused parse is never a
   partial import; nothing is created before Import as new workspace and nothing kept after a
   refusal | RULED (6396085915) — binding on every frame |
  | Condition 2 | A1 — the T2 rule | Import… is a write, its legs in the server's order, view-as
   first (`rbac.view_as`), then `rbac.permission`, then `workspace.limit.count`; Export… is never
   gated; a rejected file never T2-locks Import; an absence is never a lock; validity is never a
   lock | RULED (6396085915) — binding on every frame |
  | Condition 3 | A2 — the gates | the tool reads every frame table row by row, every other table
   and the prose, with case-insensitive vocabulary lists (the gated-exit words, the environment
   words, the sharing claim, the markup and link words) against whole clauses, never first words;
   one `--self-test` mutation per ruled sentence and per frame element, S1–S20 the minimum | RULED
   (6396085915) — binding from the first commit |
  | Condition 4 | A3 / A4 — the exits and honesty | Cancel, Esc, ×, Close and Choose another file
   are never gated on any frame, view-as and the Viewer's included; merged texts at their merge
   shas; every departure a PROPOSED A, C or G-row; "RULED" cites 6396085915; no lane is an
   authority | RULED (6396085915) — binding on every frame |
@ ¶2 ‖ paragraph ‖ 1
  **Standing (binding on every section).** **A1** T2 is E09-D09's, stated once in §6: Import… is a
   write and its legs run view-as first; Export… is a read and never gated; a rejection, a refusal,
   an absence and form validity are never a lock. **A2** every gate reads whole clauses with
   case-insensitive vocabulary lists, and every ruled sentence and frame element has its mutation.
   **A3** the exits are never gated — Cancel, `Esc`, ×, Close and Choose another file, on every
   frame and for every session, view-as and the Viewer's included. **A4** honesty: merged texts at
   their merge shas, E15-D08 by name only, every departure a PROPOSED A, C or G-row, and nothing
   measured, signed or drawn is claimed before it is. 16 <!-- audit:bq_rows=16 --> questions and 4
   <!-- audit:conditions=4 --> conditions RULED.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 0. Boards
   (PENDING — the boards PR draws them)#1
@ ¶0 ‖ heading ‖ 1
  ## 0. Boards (PENDING — the boards PR draws them)
@ ¶1 ‖ paragraph ‖ 1
  The boards are drawn from this text in a second PR on the Penpot page `E15-D09 Workspace import
   and export` (id pending), named `E15-D09 / NN slug`, their frames named as in §2–§5, exported at
   1:1 through `docs/design/_tools/penpot_export.py` to `docs/design/E15/img/`, with greyscale and
   deuteranopia renders through `docs/design/_tools/cvd_sim.py` for boards 03, 04 and 06 (the Add,
   Drop and Remap glyphs and the rejection colour). Dark and comfortable unless the row says
   otherwise: ten boards, two of them light twins (BQ-15 RULED).
@ ¶2 ‖ table ‖ 1
  | # | Board | Draws | Theme | Export | Status |
  | --- | --- | --- | --- | --- | --- |
  | 01 | `E15-D09 / 01 export-preview` | `SCR-025/export-preview`, `SCR-025/export-done` | dark |
   `docs/design/E15/img/E15-D09-01-export-preview.png` | pending |
  | 02 | `E15-D09 / 02 import-anatomy` | `SCR-026/pick`, with the redlines of §3 | dark |
   `docs/design/E15/img/E15-D09-02-import-anatomy.png` | pending |
  | 03 | `E15-D09 / 03 validating-preview` | `SCR-026/validating`, `SCR-026/preview` | dark |
   `docs/design/E15/img/E15-D09-03-validating-preview.png` | pending |
  | 04 | `E15-D09 / 04 rejections` | `SCR-026/rejected-version-newer`,
   `SCR-026/rejected-version-older`, `SCR-026/rejected-malformed`, `SCR-026/rejected-oversized`,
   `SCR-026/rejected-wrong-type`, with the CVD strip | dark |
   `docs/design/E15/img/E15-D09-04-rejections.png` | pending |
  | 05 | `E15-D09 / 05 budget-and-limit` | `SCR-026/preview-over-budget`,
   `SCR-026/budget-confirm`, `SCR-026/refused-limit` | dark |
   `docs/design/E15/img/E15-D09-05-budget-and-limit.png` | pending |
  | 06 | `E15-D09 / 06 report` | `SCR-026/report` | dark |
   `docs/design/E15/img/E15-D09-06-report.png` | pending |
  | 07 | `E15-D09 / 07 entry-t2-matrix` | `SCR-026/entry`, `SCR-026/entry-view-as`,
   `SCR-026/entry-permission`, `SCR-026/entry-limit`, `SCR-026/import-leg-lost`,
   `SCR-025/export-entry`, `SCR-025/export-unavailable` | dark |
   `docs/design/E15/img/E15-D09-07-entry-t2-matrix.png` | pending |
  | 08 | `E15-D09 / 08 keyboard-walk` | the keyboard, focus and announcement walk of §7, from the
   entry through choosing a file and the table to the report | dark |
   `docs/design/E15/img/E15-D09-08-keyboard-walk.png` | pending |
  | 09 | `E15-D09 / 09 import-light` | `SCR-026/pick`, `SCR-026/preview`,
   `SCR-026/rejected-version-newer` | light | `docs/design/E15/img/E15-D09-09-import-light.png` |
   pending |
  | 10 | `E15-D09 / 10 export-report-light` | `SCR-025/export-preview`, `SCR-026/report` | light |
   `docs/design/E15/img/E15-D09-10-export-report-light.png` | pending |
@ ¶3 ‖ paragraph ‖ 1
  **Not drawn — the text is binding; drawn on request** (BQ-15 RULED): `SCR-025/export-preparing`,
   `SCR-025/export-failed`, `SCR-025/export-cancelled`, `SCR-025/export-reflow-200`,
   `SCR-026/drag-over`, `SCR-026/drag-over-rejected`, `SCR-026/creating`, `SCR-026/cancelled`,
   `SCR-026/compact`, `SCR-026/reflow-200`, `SCR-026/preview-migrated`, `SCR-026/rejected-nodes`,
   `SCR-026/refused-server`, `SCR-026/refused-unconfirmed`.
@ ¶4 ‖ paragraph ‖ 1
  The ten boards draw 21 <!-- audit:frames_drawn=21 --> of the 35 <!-- audit:frames_total=35 -->
   frames; the other 14 <!-- audit:frames_not_drawn=14 --> are on the line above.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 1. Locked
   inputs, the trust boundary and decisions#1
@ ¶0 ‖ heading ‖ 1
  ## 1. Locked inputs, the trust boundary and decisions
@ ¶1 ‖ paragraph ‖ 1
  Cited and never re-decided: each input below fixes something in this spec, and §2–§16 cite it
   rather than restate it. §1.2 states the trust boundary once and every frame of §2–§5 applies it;
   §1.3 reconciles every state the ticket and E15-D02 name with its frames; §1.4 lists the
   decisions this spec takes on top of its inputs, each PROPOSED unless a ruling is named — the
   ruled answers are the questions table's (6396085915).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 1. Locked
   inputs, the trust boundary and decisions › 1.1 Locked inputs (cited, never re-decided)#1
@ ¶0 ‖ heading ‖ 1
  ### 1.1 Locked inputs (cited, never re-decided)
@ ¶1 ‖ table ‖ 1
  | Input | Source | What it fixes here |
  | --- | --- | --- |
  | US-LAY-007: the export carries no secrets and no account bindings; any account-scoped element
   is dropped with a clear report; a newer file is refused with the versions stated rather than
   applied in part; a file is schema-validated on import and never embeds keys, tokens or account
   ids | `11:2858–2874` (`11:2865`, `11:2868`, `11:2871`, `11:2874`) | the Excluded list and the
   trust note (BQ-2 RULED); the Drop rows (BQ-3 RULED); the version refusals (BQ-4 RULED); the five
   check steps (§3.4) |
  | E15-D01's locked list, item (8): exports carry no credentials or account bindings; layout
   events are analytics, never audit; a Viewer cannot save workspaces | `D01:39`; `D02:84` | the
   Excluded list (§2.3); the three events as analytics (§2.4, §4.5); Import… in T2 for a Viewer
   (§6) |
  | D-30: an import always creates a new workspace, after a preview that lists what is included
   and dropped and says the file carries no credentials and no account bindings; a newer file is
   refused with both versions | `D02:148`; `D02:522`; OQ-O `D02:865` | Import as new workspace,
   never over a workspace, so no SCR-029 and no discard prompt (§3); the preview before the send
   (§4) |
  | E15-D02 §5.11: the export preview and the import's states and words, drawn as wireframes and
   handed to this ticket | `D02:509–522`; the hand-off `D02:950` | every frame of §2–§5 quotes its
   upstream words byte for byte, and the tool checks each still stands upstream; E15-D02's own
   Excluded sentence is extended and never shown (D09-C5) |
  | E15-D02 §8.1: T2 on this surface — the legs in the server's order, view-as first; one notice,
   many pointers; Export… a read; busy, form validity and a refusal at the point of action are not
   T2 | `D02:635–674`; `D02:645` | §6, restated per session |
  | E15-D03, merged in #4478: the T2 rule stated once; the exits; the synthetic fixtures; Import…
   in "+" (R-5); Export… in `[⋯]` and its availability on the viewer's unsaved default (V-4); the
   reason deck | `D03:118`; `D03:122`; `D03:126`; `D03:365`; `D03:384`; `D03:564`; `D03:583`;
   `D03:625–636` | the entry frames (§3.1), the export's places (§2.2), the reason keys (§6, §9)
   and the exits (§7) |
  | D-15 and US-LAY-001's cost confirm: below 16 panes an add whose estimate crosses the frame
   budget asks with the measured and the estimated cost, its Cancel focused; a stored layout never
   holds more than 16 | `D02:133`; `D02:292`; `D03:629–631` | the budget line and the stacked
   confirm re-verbed Import anyway (BQ-6 RULED, §4.4); the 30-panel file as the panes variant of a
   rejection (§5.4) |
  | `22`: `exportWorkspace` is a read (`workspaces:read`, scope `self`) that returns one
   `WorkspaceBundle`; `createWorkspace` is a write (`workspaces:write`), refused past 32
   workspaces; no operation takes a bundle yet | `22:12843–12848`; `22:21402–21423`;
   `22:8682–8686`; `22:21419` | Export… never gated (BQ-7 RULED); the Included list counted from
   the bundle (§2.3); Import… a write with its legs (§6); D09-G1 |
  | `22`'s limits: the nesting depth of a body; a name's 40 characters; a symbol's 20; a setting
   key's pattern; 32 layouts a workspace; 16 panes a layout; indicator presets whole or not at all,
   refused beyond 200 | `22:19819`; `22:19831`; `22:20057`; `22:20041`; `22:8886`; `D02:133`;
   `22:21422–21423` | the check steps and their limits (§3.4, §5.4); the caps clause of every frame
   that shows a string from the file |
  | `PaneConfig` never holds credentials, account ids or user ids; the pane columns are class P0 |
   `22:20031`; `21:5079` | the Excluded list holds for every file the dialog saves (§2.3); the
   account setting's Drop row (§4.2) |
  | `04`: the browser is hostile; the server refuses unknown fields and never coerces them
   (SR-040), while a client ignores them (C-6.3); no import path takes a filesystem path (SR-097);
   no `dangerouslySetInnerHTML` (SR-127); `workspaces:write` per role | `04:54`; `04:855`;
   `04:924`; `04:967`; `04:1141` | §1.2; every `renders:` and `server:` clause; §6 |
  | `05`: no function by hover or drag alone; focus never silently stolen; dragging alternatives;
   text resize; live regions and their hygiene | `05:35`; `05:96`; `05:101`; `05:131`; `05:144`;
   `05:150` | Choose file… as the keyboard path, the drop zone never a Tab stop (§3.3); focus and
   announcements (§7); the 200 % frames |
  | E05-D02 slice 4: H22, `Esc`, the scrim and the outcome surface after a view is closed; H36,
   the discard prompt of a dialog with unsaved changes | `S4:734`; `S4:904` | the exits and the
   toasts after a closed view (§3.5, §7); no discard prompt, because a chosen file is no unsaved
   change (§7) |
  | E09-D09: the decision rule; T2's anatomy; the seven reason keys; the verb "save workspaces" |
   `E09D09:32`; `E09D09:49`; `E09D09:85–95`; `E09D09:114` | §6 and every T2 frame |
  | E15-S07: the check order (size, the parse limits, the schema, the version, the registry); an
   older compatible file migrated forward and said so; a newer file refused with both versions; the
   2 MB default; a node-count limit; the server's own checks; export requests logged without file
   contents | `BL:1111`; `BL:1136` | the five steps and the `server:` clause (§3.4); the migration
   line (§4.4); the limits, PROPOSED for `22` (D09-G5); the hand-offs (§12) |
  | F-LAY-6: export, then import on another machine — its cancel paths, the `409` race, its
   keyboard line and its note that an import built from many calls is not atomic | `FL:139–171` |
   `SCR-025/export-cancelled`, `SCR-026/cancelled`, `SCR-026/refused-limit`; D09-G1 |
  | E15-D06 D-9: a layout never stores an account | `D06:101` | the account setting's Drop row
   (BQ-3 RULED, §4.4) |
  | E36-D03, the SCR-089 sibling: CMP-067's native input first, its drop target described by its
   words, `color.border.dashed` re-bound | `E36D03:153–155`; `E36D03:272`; `E36D03:339` | the drop
   zone's edge (D09-A3); the reuse note (D09-A19) |
  | The ticket: the six acceptance criteria, the six rejection reasons, the 2 MB file checked
   within 500 ms in a worker, the security and accessibility notes | `BL:242`; `BL:266`; `14:637` |
   the AC trace; the event clauses; the validating state (DL-11); §1.2 |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 1. Locked
   inputs, the trust boundary and decisions › 1.2 The trust boundary, stated once#1
@ ¶0 ‖ heading ‖ 1
  ### 1.2 The trust boundary, stated once
@ ¶1 ‖ paragraph ‖ 1
  This is the one E15 surface where a file crosses the trust boundary: out of the app on export,
   into it on import (the ticket's Security notes, `BL:266`; E15-S07, `BL:1136`). Each of the
   ticket's four hazards has one rule here, and every frame of §2–§5 applies it.
@ ¶2 ‖ table ‖ 1
  | Hazard | The rule | Where it binds |
  | --- | --- | --- |
  | Exfiltration: the file leaves the machine and may end up in a chat | the server builds the
   bundle by an allow-list projection (E15-S07, `BL:1136`); no field of `WorkspaceBundle` holds a
   credential, an account, a trade-group or user id, an environment, an alert or rule binding, P&L,
   a position or an order (`22:21402–21423`; `22:20031`; C-2.7); the preview names what travels
   and, first-class, the Excluded list, so a mistake in the build is visible rather than hidden;
   the client saves only what its lists can show (D09-D2) | `SCR-025/export-preview`,
   `SCR-025/export-done` (BQ-2 RULED; owner approval pending (#2701)) |
  | Injection through content: every string from the file is untrusted | text only: never markup,
   never a link, never interpreted (SR-127, `04:967`; C-12.10); capped, an ellipsis past the cap,
   and nothing past a cap rendered, announced, copied or logged; direction-isolated, each control,
   bidi or invisible character shown as a visible "�" so it never acts or hides (D09-D20); a key
   named in mono; the report repeats nothing of the file beyond those capped strings; the same rule
   holds in the applied workspace, whose names the server sanitises again (`22:19819`) | every
   `caps:` and `renders:` clause; §4.4; §5.5 |
  | Resource abuse: a file sized or shaped to stall the app | checked in a worker, cheapest first:
   the size before a byte is parsed, then the depth and the count of values while it parses, then
   the schema, the version and the registry, the first failure ending the check; a 2 MB file is
   checked within 500 ms; a hostile file stalls the worker, never the page or the trading panes
   behind it | `SCR-026/validating`; §3.4; §5.4 |
  | Privilege confusion: a file that would grant or imply access | an import creates one new
   workspace, owned by the importer, and changes nothing else; account-scoped elements are dropped
   and listed, never remapped, and no account the importer cannot see is named; the environment
   binding is never imported; the new workspace starts unpinned; Import… is a write whose legs run
   view-as first (§6) | §4.2 rows 3 and 4; `SCR-026/report`; §6 |
@ ¶3 ‖ paragraph ‖ 1
  **The server re-checks (Condition 1).** No guard in the browser replaces the server's own
   validation: the server re-checks size, depth, nodes, schema and version when the file is
   imported (E15-S07), refuses unknown fields on its write paths, fail closed, while the client
   ignores them (C-6.3; SR-040, `04:855`), and treats the browser as hostile (`04:54`; C-2.12), and
   the same holds for every later write of the workspace, `PUT /workspaces/{workspaceId}` included
   (the ticket's Security notes, `BL:266`). `SCR-026/validating` says so in its `server:` clause,
   which the tool gates.
@ ¶4 ‖ paragraph ‖ 1
  **Nothing before the send, nothing after a refusal (Condition 1; BQ-5 RULED).** No workspace,
   layout or pane exists before Import as new workspace is pressed on a preview; a refusal at any
   step keeps nothing of the file; and the import is one request that creates everything or nothing
   (D09-G1), so no frame of this spec shows a partial import.
@ ¶5 ‖ paragraph ‖ 1
  **What the user is told (BQ-2 RULED; owner approval pending (#2701)).** Two sentences carry the
   trust claims, each gated byte for byte wherever it shows: the Excluded list on the export and
   the trust note on the import (§9 holds both). The caveat says what the file does show; the
   sharing claim of `22:12846`'s description is written nowhere in this spec (D09-G11).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 1. Locked
   inputs, the trust boundary and decisions › 1.3 The state inventory, reconciled (binding; the
   tool gates every row)#1
@ ¶0 ‖ heading ‖ 1
  ### 1.3 The state inventory, reconciled (binding; the tool gates every row)
@ ¶1 ‖ paragraph ‖ 1
  Every state the ticket and E15-D02 name has a frame; a failure after the send has no partial
   frame, because the import is never partial (D09-G1), and its frame is the server's refusal, or,
   when no answer came, the frame that says the import could not be confirmed. 27 <!--
   audit:states=27 --> states.
@ ¶2 ‖ table ‖ 1
  | # | State (the ticket and E15-D02) | Frames |
  | --- | --- | --- |
  | 1 | export: Export… unavailable on the viewer's unsaved default | `SCR-025/export-unavailable`
   |
  | 2 | export: preparing the file | `SCR-025/export-preparing` |
  | 3 | export: the preview with the Included and Excluded lists | `SCR-025/export-preview` |
  | 4 | export: preparing failed | `SCR-025/export-failed` |
  | 5 | export: the completion | `SCR-025/export-done` |
  | 6 | export: cancelled | `SCR-025/export-cancelled` |
  | 7 | import: the entry gated per role | `SCR-026/entry-view-as`, `SCR-026/entry-permission`,
   `SCR-026/entry-limit` |
  | 8 | import: choose a file | `SCR-026/pick` |
  | 9 | import: a file dragged over | `SCR-026/drag-over`, `SCR-026/drag-over-rejected` |
  | 10 | import: validating | `SCR-026/validating` |
  | 11 | import: the preview | `SCR-026/preview` |
  | 12 | import: unknown panel types in the preview | `SCR-026/preview` |
  | 13 | import: an account reference in the preview | `SCR-026/preview` |
  | 14 | import: valid but over the panel budget | `SCR-026/preview-over-budget`,
   `SCR-026/budget-confirm` |
  | 15 | import: a newer format version | `SCR-026/rejected-version-newer` |
  | 16 | import: an older format version | `SCR-026/rejected-version-older`,
   `SCR-026/preview-migrated` |
  | 17 | import: a malformed file | `SCR-026/rejected-malformed` |
  | 18 | import: an oversized file | `SCR-026/rejected-oversized` |
  | 19 | import: the wrong file type | `SCR-026/rejected-wrong-type` |
  | 20 | import: the parse limits (depth, nodes) | `SCR-026/rejected-nodes` |
  | 21 | import: the workspace limit reached at the send | `SCR-026/refused-limit` |
  | 22 | import: creating | `SCR-026/creating` |
  | 23 | import: a failure after the send | `SCR-026/refused-server` |
  | 24 | import: indicator presets over their limits | `SCR-026/rejected-malformed`,
   `SCR-026/refused-server` |
  | 25 | import: done, the report | `SCR-026/report` |
  | 26 | import: cancelled | `SCR-026/cancelled` |
  | 27 | import: the send's answer never came | `SCR-026/refused-unconfirmed` |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 1. Locked
   inputs, the trust boundary and decisions › 1.4 Decisions of this spec (PROPOSED unless RULED)#1
@ ¶0 ‖ heading ‖ 1
  ### 1.4 Decisions of this spec (PROPOSED unless RULED)
@ ¶1 ‖ paragraph ‖ 1
  Each row is stated in full where it applies; a ruled question is the questions table's and is
   never repeated here.
@ ¶2 ‖ table ‖ 1
  | Id | Decision | Where |
  | --- | --- | --- |
  | D09-D1 | the Included and Excluded lists stand side by side in equal columns, so the Excluded
   list never sits below a long Included list; at 200 % they stack, the Included list first | §2.3
   |
  | D09-D2 | before the preview the client reads the fetched bundle with the import's own check:
   data the lists cannot show, or a setting the import would drop as account-scoped, fails the
   export closed; a limit an import would refuse keeps Download file and adds a warning line | §2.3
   |
  | D09-D3 | while the workspace has unsaved changes, a line says the file holds it as last saved
   | §2.3 |
  | D09-D4 | the bytes saved are the response body as fetched, written whole or not at all; the
   page learns only the file's base name and the server never a path; where a browser has no save
   picker, the hand-off counts as the save (D09-Q2) | §2.4 |
  | D09-D5 | the slug rule in full, the empty name and the Windows device names included (D09-G14)
   | §2.4 |
  | D09-D6 | `workspace.exported` fires when the write ends and carries counts only | §2.4 |
  | D09-D7 | when the bundle arrives, focus moves to the title only while it is still on the
   Cancel the dialog opened on | §2.1 |
  | D09-D8 | `SCR-025/export-failed` takes three more sentences: a `403` or `404` from the read, a
   bundle the check declines and a write that failed | §2.1 |
  | D09-D9 | the export's preparing line waits for the show-delay BQ-9 rules for the import, 150
   ms | §2.1, §3.4 |
  | D09-D10 | the native input is `hidden`, out of the Tab order and the accessibility tree,
   opened by Choose file…'s click and labelled by it | §3.3 |
  | D09-D11 | the trust note is the import dialog's description, heard as focus enters | §3.2 |
  | D09-D12 | the import dialog's top edge stays where it opened while its body grows | §3.2 |
  | D09-D13 | the file line names the chosen file, capped at 40 <!-- audit:design.file_cap=40 -->
   characters, as text | §3.3 |
  | D09-D14 | a drop of two or more files reads none of them and speaks "Drop one .json file" once
   | §3.3 |
  | D09-D15 | the value text counts the steps and never names them (D09-C13) | §3.4 |
  | D09-D16 | the import is one request that creates everything or nothing, never
   `createWorkspace` followed by `createLayout` for each layout (D09-G1) | §3.5, §5.5 |
  | D09-D17 | Import as new workspace keeps its label while it is busy, and "Still importing…"
   shows after CMP-001's slow-path delay | §3.5 |
  | D09-D18 | when the view was closed during the send, a persistent `success` toast with View
   report, or a persistent `danger` toast with Review, carries the outcome, and an unanswered send
   a persistent `warning` toast with Review (D09-D33) | §3.5, §7 |
  | D09-D19 | each Item cell is its row's header, and every row stays in the page, never windowed
   | §4.4, §7 |
  | D09-D20 | every string from the file is direction-isolated, and each control, bidi or
   default-ignorable (`Default_Ignorable_Code_Point`, §5.5) character in it shows as a visible "�"
   instead of acting or hiding | §4.4, §5.5 |
  | D09-D21 | Copy report's plain text: one numbered line per row, its cells joined by " · ", no
   line starting with a value from the file; "Couldn't copy the report." when the clipboard is
   refused | §4.5 |
  | D09-D22 | `layout.imported` carries the file's own `schemaVersion`, as read before any
   migration | §4.5 |
  | D09-D23 | the report of a migrated import carries the migration line above its table | §4.4 |
  | D09-D24 | Import anyway is a CMP-001 `primary`, not `danger`, because nothing is destroyed
   (D09-A9) | §4.4 |
  | D09-D25 | `schema_version` is read as a whole number written in decimal; absent, empty or
   anything else is a schema failure that names the key (D09-G2) | §5.3 |
  | D09-D26 | the worker counts the nesting and the values as it reads and stops at the first
   limit crossed, before any document is built | §5.4 |
  | D09-D27 | a key or a file name is capped at 64 <!-- audit:design.key_cap=64 --> or 40
   characters, and its accessible name carries the same capped text, followed by "(shortened)" when
   it was cut | §5.5 |
  | D09-D28 | `SCR-026/refused-limit`'s footer is Cancel alone and its body leaves out the zone
   and Choose file…, an absence, and focus lands on Cancel, because another file would meet the
   same limit | §5.5 |
  | D09-D29 | a `403` at the send turns the dialog's verb T2 where it stands
   (`SCR-026/import-leg-lost`); no event fires on a refusal at the send | §5.5 |
  | D09-D30 | a refusal at the send speaks politely, focus on the frame's named button (D09-C12) |
   §7 |
  | D09-D31 | three more refusals in words: a known key whose value is the wrong kind, the
   malformed file's variant; a store that does not answer at the send and a file larger than the
   server takes, the server refusal's variants | §5.4, §5.5 |
  | D09-D32 | the bytes sent are the bytes the preview was built from, held in the worker and
   never read again from the file's handle | §3.5 |
  | D09-D33 | a send whose answer never comes, a timeout or a dropped connection, ends on
   `SCR-026/refused-unconfirmed`, which never claims that nothing was imported and offers no second
   send (D09-G1); after the view closed, a `warning` toast writes its words, never
   `e15.import.nothing` | §5.5 |
  | D09-D34 | a drop that carries no file, or a drop outside the zone, is ignored: nothing is read
   or fetched, no address is followed and the page keeps its state | §3.3 |
  | D09-D35 | a pane setting the registry does not list for its kind, and that is not
   account-scoped, is a Drop row of its own, Type "setting", Reason "not available in this version"
   | §3.4, §4.4 |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion#1
@ ¶0 ‖ heading ‖ 1
  ## 2. Export: entry points, the preview dialog, the file and its completion
@ ¶1 ‖ paragraph ‖ 1
  Export is a read. `exportWorkspace` returns the stored workspace as one `WorkspaceBundle`,
   `workspaces:read`, scope `self` (`22:12843–12849`), so Export… is never gated (a read): T1 for
   every session on a stored workspace, Owner, Manager, Viewer and view-as alike (`D02:645`; T2 is
   stated once, in §6). It sits in three places and opens one dialog (BQ-7 RULED, §2.2): a CMP-043
   `role="dialog"`, `size="md"`, at most 560 <!-- audit:contract.dialog_md_px=560 --> px wide
   (`15:466`), which calls `exportWorkspace` once, counts the Included list from the bundle it gets
   and saves that same bundle, so what the owner checks is what the file holds (`D02:511`; F-LAY-6,
   `FL:139–171`). Beside the Included list stands the Excluded list, first-class (§2.3). The file
   is written on this machine through the platform's save sheet and its name carries the format
   version (§2.4); no path ever goes to the server (SR-097, `04:924`), and nothing leaves the
   machine until the owner sends the file on. The trust copy is BQ-2's ruled text, owner approval
   pending (#2701), and the sharing claim in `exportWorkspace`'s description is written nowhere in
   this spec (D09-G11). A decision that names no ruling is PROPOSED.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion › 2.1 Frames (binding; the tool
   gates every row)#1
@ ¶0 ‖ heading ‖ 1
  ### 2.1 Frames (binding; the tool gates every row)
@ ¶1 ‖ table ‖ 1
  | Frame | Producer | Shows | Class | Copy keys | Board |
  | --- | --- | --- | --- | --- | --- |
  | `SCR-025/export-entry` | Export… opened from SCR-025's Share section (E15-D08, merged at
   `fb1b4804`), the tab's `[⋯]` (`D03:384`) or the rail's workspace menu (`D02:511`), on a stored
   workspace | access: Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace
   menu — T1 for every session, Owner, Manager, Viewer and view-as alike, on a stored workspace: a
   read (`workspaces:read`), never T2 (§6); Esc → Close (the menu, focus back on its button); exits
   T1: Esc; Components: a CMP-041 item of `kind` action in the tab's `[⋯]` and in the rail's
   workspace menu, with no glyph and no shortcut · in SCR-025's Share section a CMP-001 `secondary`
   button, which E15-D08 draws (merged, `fb1b4804`); Layout (comfortable / compact): the item
   `size.row.height` tall, 32 <!-- audit:redline.size.control.comfortable=32 --> px or 24 <!--
   audit:redline.size.row.height=24 --> px, its label inset `space.inset.sm` 8 <!--
   audit:redline.space.inset.sm=8 --> px · the menu `radius.card` 6 <!--
   audit:redline.radius.card=6 --> px with a `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px `color.border.default` edge; Tokens (dark and light, the
   same names): the menu `color.surface.overlay` at `elevation.popover`, the label `type.ui.body` +
   `color.text.primary`, hover `color.surface.hover`, the focus ring `color.focus.ring` at
   `border.focus` 2 <!-- audit:redline.border.focus=2 --> px inside the item; Focus: the arrows
   land on Export… and `Enter` opens the export dialog as the menu folds away · when the dialog
   ends, focus returns to the menu's button (`[⋯]` or the rail row's) or to SCR-025's Export… | T1
   | `e15.export.menu_item` | 07 |
  | `SCR-025/export-unavailable` | the viewer's unsaved default (`D03:583`, `D03:625`), or a
   workspace with no stored copy (`D03:384`) | availability: Export… on the viewer's unsaved
   default — `aria-disabled="true"`, its second line "This workspace isn't saved."
   (`ws.export.unstored`), no lock, no CMP-079, not T2 (§6); Esc → Close (the menu, focus back on
   its button); exits T1: Esc; Components: the same CMP-041 item with its second line, which its
   `aria-describedby` names · no glyph · in SCR-025, the same CMP-001 `secondary` button with the
   line under it (E15-D08, merged); Layout (comfortable / compact): the item grows to two lines and
   stays at least `size.row.height` tall, 32 <!-- audit:redline.size.control.comfortable=32 --> px
   or 24 <!-- audit:redline.size.row.height=24 --> px, the second line under the label at the same
   8 <!-- audit:redline.space.inset.sm=8 --> px inset; Tokens (dark and light, the same names): the
   label `type.ui.body` + `color.text.tertiary`, the second line `type.ui.caption` +
   `color.text.secondary` (`D02:645`), both at full strength; Focus: the arrows still land on it
   and a screen reader reads its second line with its name · `Enter` and `Space` change nothing and
   open nothing | availability | `e15.export.menu_item` · `ws.export.unstored` | 07 |
  | `SCR-025/export-preparing` | Export… chosen on the stored workspace Scalping;
   `exportWorkspace` called (`22:12843`), its bundle not back yet | dialog: CMP-043 `size="md"`
   `role="dialog"` "Export Scalping", close × "Close Export Scalping"; busy: "Preparing the file…"
   — CMP-038 with `aria-busy="true"` on the body, a load, so Cancel stays; footer: Cancel
   (`secondary`); initial focus: Cancel; Esc → Cancel; exits T1: Cancel · Esc · ×; Components:
   CMP-043 `md`, stacked over SCR-025 when opened there and on its own from a menu · CMP-038 with
   its CMP-014 `sm` arc, `role="status"`, in the body · CMP-002 `ghost` close · CMP-001
   `secondary`; Layout (comfortable / compact): the card at most 560 <!--
   audit:contract.dialog_md_px=560 --> px wide, padding `space.dialog.padding` 24 <!--
   audit:redline.space.dialog.padding=24 --> px, header, body and footer `space.stack.md` 12 <!--
   audit:redline.space.stack.md=12 --> px apart · the header one row `size.control.height` tall, 32
   <!-- audit:redline.size.control.comfortable=32 --> px or 24 <!--
   audit:redline.size.control.compact=24 --> px, the × a square of that size beside the title,
   `space.inset.sm` from it · the footer end-aligned, its buttons `size.control.height` tall and
   `space.inset.sm` apart · the body one CMP-038 line and no stand-in for the lists; Tokens (dark
   and light, the same names): the card `color.surface.overlay` at `elevation.dialog`,
   `radius.dialog` 10 <!-- audit:redline.radius.dialog=10 --> px, a `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px `color.border.default` edge, over `palette.black` at
   `opacity.scrim` 0.6 <!-- audit:redline.opacity.scrim=0.6 --> · the title `type.ui.heading-sm` +
   `color.text.primary` · the focus ring `color.focus.ring` at `border.focus` 2 <!--
   audit:redline.border.focus=2 --> px · the CMP-038 words `type.ui.body` + `color.text.secondary`,
   its arc `color.action.primary.default`; Timing: the line shows only after the 150 ms show-delay
   BQ-9 rules for the import (§3.4), PROPOSED here for the export (D09-D9), so a quick answer goes
   straight to the preview · Cancel ends the read and nothing is exported; Focus: Tab cycles × →
   Cancel → × · when the bundle arrives, focus moves to the title only while it is still on Cancel,
   where the dialog put it (`05:96`) · CMP-038 speaks its line once | busy | `e15.export.title` ·
   `e15.export.close` · `e15.export.preparing` · `e15.export.cancel` | not drawn — the text is
   binding; drawn on request |
  | `SCR-025/export-preview` | the bundle arrived and passed the check of §2.3: the preview is
   built from it and Download file saves that same bundle (`D02:511`) | dialog: CMP-043 `size="md"`
   `role="dialog"` "Export Scalping", close × "Close Export Scalping"; included: a CMP-036 list
   built from the fetched bundle, one item per clause — "The file includes: 2 layouts (Layout 1,
   Order-flow) · 7 panels · symbols BTCUSDT, ETHUSDT · sync groups A and B · each panel's settings
   · 12 drawings, with their text labels · 1 chart template · 3 indicator presets."; excluded: a
   CMP-036 list, first-class, one item per clause — "Never included: credentials — API keys or
   tokens; accounts, trade-group and user ids; environment binding (DEMO or LIVE); alert and rule
   bindings; P&L, positions or orders."; caveat: "The file does show your symbols, layouts and
   settings."; footer: Cancel (`secondary`) · Download file (`primary`); initial focus: the title
   (`tabindex="-1"`); Esc → Cancel; exits T1: Cancel · Esc · ×; Components: CMP-043 `md` · two
   CMP-036 KeyValueRows in one `dl`, each with its lead-in as the term and its list as the value, a
   `ul` with one `li` per clause that keeps the clause's own punctuation · the caveat a plain line
   · CMP-001 `secondary` and `primary` · CMP-028 `info` for unsaved changes and `warning` for an
   import limit, each only when it applies, `live="off"` (§2.3); Layout (comfortable / compact):
   the two lists side by side in equal columns `space.inset.xl` 24 <!--
   audit:redline.space.inset.xl=24 --> px apart, both from the top of the body, so the Excluded
   list stands beside the Included list however long that one runs · each item at least
   `size.row.height` tall, 32 <!-- audit:redline.size.control.comfortable=32 --> px or 24 <!--
   audit:redline.size.row.height=24 --> px · the caveat full width, 12 <!--
   audit:redline.space.stack.md=12 --> px under the columns · past 80 % of the viewport the body
   scrolls between the header and the footer (`15:466–468`) · the card's chrome as on
   `SCR-025/export-preparing`; Tokens (dark and light, the same names): each lead-in
   `type.ui.body-strong` + `color.text.primary`, each item `type.ui.body` + `color.text.primary`,
   the caveat `type.ui.body` + `color.text.secondary`, Download file `color.text.on-action` on
   `color.action.primary.default`, Cancel `color.text.primary` on `color.action.secondary.default`;
   Description: the dialog's `aria-describedby` names the two lists, so the title is read with them
   · Download file's `aria-describedby` names the unsaved-changes line and the import-limit line
   when they show; Focus: Tab cycles × → the body (a Tab stop only while it scrolls) → Cancel →
   Download file → × · `Enter` on Download file opens the save sheet with the suggested name (§2.4)
   | T1 | `e15.export.title` · `e15.export.close` · `e15.export.unsaved` · `e15.export.included` ·
   `e15.export.excluded` · `e15.export.caveat` · `e15.export.over_limit` · `e15.export.cancel` ·
   `e15.export.download` | 01, 10 |
  | `SCR-025/export-failed` | `exportWorkspace` answered `store_unavailable` or nothing
   (`D02:511`, `FL:139`); the same frame for a `403` or `404`, for a bundle the check of §2.3
   declines and for a failed write (§2.4) | dialog: CMP-043 `size="md"` `role="dialog"` "Export
   Scalping", close × "Close Export Scalping"; component: CMP-027 `inline`, `live="polite"`, in the
   dialog body; message: "Couldn't prepare the file: the workspace store is unavailable. Nothing
   was exported."; live: polite, once; footer: Cancel (`secondary`) · Try again (`primary`);
   initial focus: Try again; Esc → Cancel; exits T1: Cancel · Esc · ×; Variants, PROPOSED, the same
   frame with its own sentence: a `403` or `404` from the read, "Couldn't prepare the file: this
   workspace can no longer be read. Nothing was exported." · a bundle holding what the preview
   can't show (§2.3), "Couldn't prepare the file: it holds something this preview can't show.
   Nothing was exported." · a write that failed (§2.4), "Couldn't save the file. Nothing was
   exported."; Components: CMP-027 `inline`, `severity` error, its CMP-019 `danger` glyph before
   the words (`15:301–309`) · the lists leave the body and the message stands alone; Layout
   (comfortable / compact): the message full width, its glyph `size.icon` 16 <!--
   audit:redline.size.icon=16 --> px, the card as tall as the message, the chrome and the footer as
   on `SCR-025/export-preparing`; Tokens (dark and light, the same names): the glyph
   `color.status.danger.strong` and the words `type.ui.body` + `color.text.primary`, both on
   `color.surface.overlay`; Focus: Tab cycles × → Cancel → Try again → × · Try again sends the read
   again and shows the preparing line with focus on Cancel, or, after a failed write, opens the
   save sheet again | outcome | `e15.export.title` · `e15.export.close` · `e15.export.failed` ·
   `e15.export.failed_gone` · `e15.export.failed_unlisted` · `e15.export.save_failed` ·
   `e15.export.cancel` · `e15.export.retry` | not drawn — the text is binding; drawn on request |
  | `SCR-025/export-done` | the save sheet returned a file and its write ended, whole (§2.4) |
   dialog: CMP-043 `size="md"` `role="dialog"` "Export Scalping", close × "Close Export Scalping";
   done: CMP-028 `success` "Exported Scalping as scalping.cv-workspace-v1.json." — the file name in
   `type.num.sm`, selectable; excluded: a CMP-036 list, first-class, one item per clause — "Never
   included: credentials — API keys or tokens; accounts, trade-group and user ids; environment
   binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."; event:
   `workspace.exported{panelCount, schemaVersion}` fires once the file is saved, never on Download
   file pressed; live: polite, once — the completion line; footer: Close (`primary`); initial
   focus: Close; Esc → Close; exits T1: Close · Esc · ×; Components: CMP-028 `success`, its title
   line alone, at the top of the body · the Excluded CMP-036 row, full width, beneath it · the
   Included list, the caveat and the conditional lines leave · CMP-001 `primary` Close; Layout
   (comfortable / compact): the success line full width with its `border.thick` 2 <!--
   audit:redline.border.thick=2 --> px start edge and `radius.card` 6 <!--
   audit:redline.radius.card=6 --> px, the Excluded row 12 <!-- audit:redline.space.stack.md=12 -->
   px under it, the footer one button `size.control.height` tall, the chrome as on
   `SCR-025/export-preparing`; Tokens (dark and light, the same names): the success words
   `type.ui.body-strong` + `color.text.primary` on `color.status.success.subtle`, its edge and
   glyph `color.status.success.strong`, the file name `type.num.sm` + `color.text.primary`; File
   name: the base name the save sheet returned, never its folder, at most 40 <!--
   audit:design.file_cap=40 --> characters with an ellipsis past them, as text, the whole capped
   value in the accessible name; Focus: Tab cycles × → Close → × · Close, `Esc` or × returns focus
   to the opener | outcome | `e15.export.title` · `e15.export.close` · `e15.export.done` ·
   `e15.export.excluded` · `e15.export.close_button` | 01 |
  | `SCR-025/export-cancelled` | the OS save sheet closed without saving (`FL:146`) | dialog:
   CMP-043 `size="md"` `role="dialog"` "Export Scalping", close × "Close Export Scalping"; state:
   nothing exported — the save sheet closed unsaved, the preview stays as it was and no event
   fires; included: a CMP-036 list built from the fetched bundle, one item per clause — "The file
   includes: 2 layouts (Layout 1, Order-flow) · 7 panels · symbols BTCUSDT, ETHUSDT · sync groups A
   and B · each panel's settings · 12 drawings, with their text labels · 1 chart template · 3
   indicator presets."; excluded: a CMP-036 list, first-class, one item per clause — "Never
   included: credentials — API keys or tokens; accounts, trade-group and user ids; environment
   binding (DEMO or LIVE); alert and rule bindings; P&L, positions or orders."; caveat: "The file
   does show your symbols, layouts and settings."; footer: Cancel (`secondary`) · Download file
   (`primary`); initial focus: Download file; Esc → Cancel; exits T1: Cancel · Esc · ×; Components,
   layout and tokens: as on `SCR-025/export-preview`, its conditional lines with them; Focus: on
   Download file, where the save sheet returned it · Tab as on the preview · nothing is announced |
   outcome | `e15.export.title` · `e15.export.close` · `e15.export.unsaved` · `e15.export.included`
   · `e15.export.excluded` · `e15.export.caveat` · `e15.export.over_limit` · `e15.export.cancel` ·
   `e15.export.download` | not drawn — the text is binding; drawn on request |
  | `SCR-025/export-reflow-200` | the export dialog at 200 % zoom (`05:131`) | reflow: at 200 % on
   1280 × 800 the dialog fills the viewport less 16 px a side, keeps its title and footer and
   scrolls its body, both lists in one column; Layout: CMP-043's reflow state (`15:466–468`) · the
   two lists stack, the Included list first, each full width, and the caveat and the conditional
   lines follow in order · the footer may wrap to two lines, Cancel first · nothing is clipped
   (`05:131`) | T1 (reflow) | — | not drawn — the text is binding; drawn on request |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion › 2.2 Entry points and the
   dialog#1
@ ¶0 ‖ heading ‖ 1
  ### 2.2 Entry points and the dialog
@ ¶1 ‖ paragraph ‖ 1
  **Three places, one dialog (BQ-7 RULED).** Export… sits wherever a workspace is managed, and
   each place opens the same dialog on the workspace it belongs to:
@ ¶2 ‖ table ‖ 1
  | Place | Control | The dialog opens | Focus when the dialog ends | Source |
  | --- | --- | --- | --- | --- |
  | SCR-025's Share section | CMP-001 `secondary`, "Export…" | stacked over SCR-025, one more
   layer (E05-D02 slice 4, conventions 32) | SCR-025's Export… | E15-D08, merged at `fb1b4804`; if
   it changes, this row follows it |
  | the tab's `[⋯]` | a CMP-041 item, "Export…" | over the workspace | `[⋯]`, the menu's own
   button (the item went with the menu) | `D03:384` |
  | the rail's workspace menu | a CMP-041 item, "Export…" | over the workspace | the rail row's
   menu button | `D02:511` |
@ ¶3 ‖ paragraph ‖ 1
  Each place acts on the stored workspace it belongs to and on nothing else: the file holds that
   workspace as last saved (§2.3). SCR-025's Share section is E15-D02 §5.10's, its hi-fi E15-D08's
   (merged, `fb1b4804`); this spec adds no shortcut and no palette command, and the three places
   are the ones BQ-7 RULED names.
@ ¶4 ‖ paragraph ‖ 1
  **Availability, not T2.** Where the workspace has no stored copy, the viewer's unsaved default
   (V-4, `D03:583`) and a workspace never stored (`D03:384`), there is nothing to read, so the item
   keeps its place and its label, the label in `color.text.tertiary` and the item
   `aria-disabled="true"`, with "This workspace isn't saved." as its second line
   (`ws.export.unstored`, `D03:625`): no lock glyph, no CMP-079 and no registered reason key, the
   availability form of E15-D03 §1.4 (`D03:118–120`; `SCR-025/export-unavailable`). The arrows
   still reach it, and its second line is read with its name.
@ ¶5 ‖ paragraph ‖ 1
  **The dialog (`15:463–469`).** A CMP-043 `role="dialog"` with `aria-modal="true"` and
   `size="md"`, titled "Export Scalping" with the stored name, so an unsaved rename is not in the
   title and a long name wraps rather than being cut, and with its close × named "Close Export
   Scalping". Opening it calls `exportWorkspace` once and shows "Preparing the file…" until the
   bundle arrives (`D02:511`); preparing is a load, so its Cancel stays (`15:409–417`). The scrim
   covers the workspace below the TopBar; the TopBar with its environment badge, the StatusBar and
   the shell's live regions stay above it (E05-D02 slice 4, conventions 31; `D02:84`). Opened from
   SCR-025, the dialog is one more layer, and `Esc` ends it alone and returns focus to SCR-025's
   Export… (H22, `S4:734`). The dialog holds no edits, so Cancel, `Esc`, × and a press on the scrim
   end it at once, with no prompt (H36, `S4:904`) and nothing exported (`FL:146`).
@ ¶6 ‖ paragraph ‖ 1
  **Anatomy and redlines (comfortable; compact changes the control heights only).** Density
   re-points `size.control.height` and `size.row.height` and nothing else
   (`packages/ui/src/theme/theme.css`), so every other value below holds in both densities. Every
   binding is a semantic name; light and high contrast re-point the same aliases, so the light twin
   (board 10) changes no binding, and §8 measures each pair in the three themes.
@ ¶7 ‖ table ‖ 1
  | Part | Component and variant | Layout and redlines | Tokens (dark and light, the same names) |
  | --- | --- | --- | --- |
  | Scrim | CMP-043's (conventions 31) | over the workspace below the TopBar | `palette.black` at
   `opacity.scrim` 0.6 <!-- audit:redline.opacity.scrim=0.6 --> |
  | Card | CMP-043 `role="dialog"`, `size="md"` | at most 560 <!-- audit:contract.dialog_md_px=560
   --> px wide, as tall as its content up to 80 % of the viewport, past which the body scrolls
   between the fixed header and footer (`15:466–468`); padding `space.dialog.padding` 24 <!--
   audit:redline.space.dialog.padding=24 --> px; header, body and footer `space.stack.md` 12 <!--
   audit:redline.space.stack.md=12 --> px apart | `color.surface.overlay`, `elevation.dialog`,
   `radius.dialog` 10 <!-- audit:redline.radius.dialog=10 --> px, a `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px `color.border.default` edge |
  | Header | CMP-043's header; CMP-002 `ghost` `close` | one row: the title at its start, the × at
   its end, a square of `size.control.height`, 32 <!-- audit:redline.size.control.comfortable=32
   --> px comfortable and 24 <!-- audit:redline.size.control.compact=24 --> px compact,
   `space.inset.sm` 8 <!-- audit:redline.space.inset.sm=8 --> px from the title; a long title wraps
   to a second line | the title `type.ui.heading-sm` + `color.text.primary` (`h2`); the × glyph in
   `color.text.primary` |
  | Body | the frame's content (§2.3) | the card's content box, full width; while it scrolls it is
   one Tab stop (`tabindex="0"`, named by the title), so a keyboard can scroll it | as §2.3 |
  | Footer | a CMP-001 row | end-aligned, Cancel (`secondary`) first and the primary last,
   `space.inset.sm` apart, `size.control.height` tall; the done step's footer is Close alone | the
   primary `color.text.on-action` on `color.action.primary.default`; Cancel `color.text.primary` on
   `color.action.secondary.default`; both labels in CMP-001's own type |
  | Focus | CMP-039 | a `border.focus` 2 <!-- audit:redline.border.focus=2 --> px ring on every
   stop | `color.focus.ring` |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion › 2.3 The Included and Excluded
   lists: anatomy and redlines#1
@ ¶0 ‖ heading ‖ 1
  ### 2.3 The Included and Excluded lists: anatomy and redlines
@ ¶1 ‖ paragraph ‖ 1
  **What the two lists say (BQ-2 RULED; owner approval pending (#2701)).** The Included list is
   counted from the fetched bundle, so it names only what `WorkspaceBundle` holds
   (`22:21402–21423`): no density, which no workspace stores (the third deviation). The Excluded
   list is BQ-2's sentence, byte for byte, drawn as a list of its five clauses and first-class: the
   same type, weight and column width as the Included list, never a footnote, a hint or a tooltip.
   It holds for every file this dialog saves: the bundle has no field for any of the five classes
   (`22:21406`; a pane's settings never hold credentials, account ids or user ids, `22:20031`,
   `21:5079`; credentials never leave the secrets module, C-2.7), the server builds the bundle by
   copying fields in by name, never by spreading a row (E15-S07, `BL:1136`), and the client saves
   only a bundle that passes the check below. The caveat says what the file does show, a trader's
   symbols, layouts and settings, which makes the file user-confidential (E15-X01); the sharing
   claim of `exportWorkspace`'s description is never written (D09-G11).
@ ¶2 ‖ table ‖ 1
  | Included item | Built from the bundle (`22:21402–21423`) | For Scalping | Left out when |
  | --- | --- | --- | --- |
  | the layouts, with their names | `layouts[]`, each `name` (at most 40 <!--
   audit:contract.name_max=40 --> characters, `22:19831`), in the bundle's order | 2 <!--
   audit:fixture.export_layouts=2 --> layouts (Layout 1, Order-flow) | the workspace has no layout
   yet |
  | the panels | every pane of every layout, `layouts[].panes[]` | 7 <!--
   audit:fixture.export_panels=7 --> panels | no layout holds a panel |
  | the symbols | each distinct `symbol` of a pane or of a drawing, in the order first met |
   symbols BTCUSDT, ETHUSDT | no pane or drawing names a symbol |
  | the sync groups | each distinct `pane_config.sync_group` | sync groups A and B | no pane is in
   a group |
  | the panel settings | each pane's `pane_config.settings` | each panel's settings | no layout
   holds a panel |
  | the drawings | `drawings[]`, with ", with their text labels" while one carries a `label` (at
   most 120 <!-- audit:contract.label_max=120 --> code points, `21:3302`) | 12 drawings, with their
   text labels | there is no drawing |
  | the chart templates | `chart_templates[]` | 1 chart template | there is none |
  | the indicator presets | `indicator_presets[]`: every live preset of the caller, never
   truncated (`22:21419–21423`) | 3 indicator presets | there is none |
@ ¶3 ‖ paragraph ‖ 1
  A count of one takes the singular ("1 layout (Layout 1)", "1 panel"); the items keep the
   sentence's order and the last one takes its full stop. The workspace record itself (its name,
   whether it opens at startup, its icon and its place in the rail) travels as the file's
   `workspace` (`22:21406–21410`) and is named by the title; the format version and the time of
   export travel too (`22:21408–21409`), the version also in the file's name (§2.4); the Included
   list leaves both out because they are facts about the file, not about the workspace. Every name
   in the lists is rendered as text, never as markup (SR-127, `04:967`).
@ ¶4 ‖ paragraph ‖ 1
  **The check before the preview (PROPOSED).** The preview can vouch only for what it lists, so
   before it draws the lists the client reads the fetched bundle with the import's own check (§3's
   five steps, in the same worker as the import's, `14:637`), and the export never saves what the
   preview cannot show:
@ ¶5 ‖ list ‖ 1
  - A field outside `WorkspaceBundle`'s schemas is never read into the lists, because a client
   ignores what it does not know (C-6.3); and because the file is the bytes as fetched (§2.4), the
   client declines to save a bundle that carries one, or a pane setting the import would drop as
   account-scoped (§4.2's third row): `SCR-025/export-failed` with "Couldn't prepare the file: it
   holds something this preview can't show. Nothing was exported." `WorkspaceBundle` and
   `ChartTemplateInput` are not closed today (D09-G4); the server's allow-list projection stays the
   authority (E15-S07, `BL:1136`) and this check never replaces it (`04:54`): it only declines to
   save what it cannot list. One rule holds in both directions: what the lists cannot show is never
   written to a file, and on import an unknown key is never read into the app (§3.4).
  - A limit an import would refuse (the file's size, its nesting or its count of values, or its
   presets: an export carries every live preset, while an import takes at most 200 <!--
   audit:contract.presets_max=200 --> of them, `22:21419–21423`) keeps Download file and adds a
   CMP-028 `warning` line under the caveat: the import's own first sentence, then "You can save it,
   but this app won't import it." For a file with 240 presets: "This file has 240 indicator
   presets; a file may carry at most 200. You can save it, but this app won't import it." The
   limits are E15-S07's until the contract carries them (D09-G5).
@ ¶6 ‖ paragraph ‖ 1
  **Unsaved changes (PROPOSED).** `exportWorkspace` reads the store, so a layout's unsaved working
   copy and SCR-025's unsaved edits are not in the file. While the workspace has unsaved changes, a
   CMP-028 `info` line opens the body: "Unsaved changes aren't in the file: it holds Scalping as
   last saved." Saving first sends them; a session that cannot save exports what is stored.
@ ¶7 ‖ paragraph ‖ 1
  **Anatomy and redlines (comfortable / compact).** The body of the preview, the done step and the
   failed step; §2.2 holds the chrome.
@ ¶8 ‖ table ‖ 1
  | Part | Component and variant | Layout and redlines (comfortable / compact) | Tokens (dark and
   light, the same names) |
  | --- | --- | --- | --- |
  | Unsaved-changes line | CMP-028 `info`, its title line alone, `live="off"`, only while the
   workspace has unsaved changes | full width at the top of the body, `space.stack.md` 12 <!--
   audit:redline.space.stack.md=12 --> px above the lists; a `border.thick` 2 <!--
   audit:redline.border.thick=2 --> px start edge; `radius.card` 6 <!-- audit:redline.radius.card=6
   --> px; CMP-028's own padding | words `type.ui.body-strong` + `color.text.primary` on
   `color.status.info.subtle`; edge and glyph `color.status.info.strong` |
  | The two lists | one `dl` holding two CMP-036 KeyValueRows | two equal columns `space.inset.xl`
   24 <!-- audit:redline.space.inset.xl=24 --> px apart, both from the top of the body; in the
   reflow state one column, the Included list first | as their parts |
  | Lead-in | each CMP-036's `label`: "The file includes:", and the Excluded sentence's opening
   words up to its colon | one line, `space.inset.sm` 8 <!-- audit:redline.space.inset.sm=8 --> px
   above its first item | `type.ui.body-strong` + `color.text.primary` |
  | Items | each CMP-036's `value`: a `ul` named by its lead-in (`aria-labelledby`), one `li` per
   clause, each keeping the clause's own punctuation, so the list read in order is the sentence |
   each item at least `size.row.height` tall, 32 <!-- audit:redline.size.control.comfortable=32 -->
   px comfortable and 24 <!-- audit:redline.size.row.height=24 --> px compact, its words centred in
   it; a long item wraps inside its column | `type.ui.body` + `color.text.primary` on
   `color.surface.overlay` |
  | Caveat | a `p` | full width, `space.stack.md` under the columns | `type.ui.body` +
   `color.text.secondary` |
  | Import-limit line | CMP-028 `warning`, its title line alone, `live="off"`, only while an
   import would refuse the file | full width, `space.stack.md` under the caveat; the edge, the
   radius and the padding of the unsaved-changes line | words `type.ui.body-strong` +
   `color.text.primary` on `color.status.warning.subtle`; edge and glyph
   `color.status.warning.strong` |
  | Completion line (the done step) | CMP-028 `success`, its title line alone, `role="status"` |
   full width at the top of the body, the Excluded row `space.stack.md` under it; the edge, the
   radius and the padding of the unsaved-changes line | words `type.ui.body-strong` +
   `color.text.primary` on `color.status.success.subtle`; edge and glyph
   `color.status.success.strong`; the file name `type.num.sm` |
  | Failure (the failed step) | CMP-027 `inline`, `severity` error, `live="polite"` | the message
   full width, its glyph `size.icon` 16 <!-- audit:redline.size.icon=16 --> px before the words |
   glyph `color.status.danger.strong`; words `type.ui.body` + `color.text.primary` |
@ ¶9 ‖ paragraph ‖ 1
  **Dark, light and high contrast.** The three themes re-point the same names
   (`packages/ui/tokens/themes.json`), and §8 measures every pair from the token files. The lists'
   words are the dialog's first pair, `color.text.primary` on `color.surface.overlay`, body text in
   every theme, and the availability label's `color.text.tertiary` passes as text in every theme
   too. In light, the completion line's edge and glyph on their fill are the faintest pair this
   section draws that still passes as non-text, so the line's words carry it; and, in light, the
   failure glyph's `color.status.danger.strong` and the import-limit glyph's
   `color.status.warning.strong` share one greyscale value (§8's greyscale rows), so colour never
   tells them apart: the two never show together, and each is read by its words. Under
   `forced-colors: active` the card keeps its `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px edge and every callout keeps its glyph and its words
   (E05-D02 slice 4, conventions 38).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion › 2.4 The file name and the
   completion#1
@ ¶0 ‖ heading ‖ 1
  ### 2.4 The file name and the completion
@ ¶1 ‖ paragraph ‖ 1
  **The name (BQ-8 RULED; the slug rule is D09-G14).**
   `<slug>.cv-workspace-v<schema_version>.json`, for the fixture `scalping.cv-workspace-v1.json`.
   The format token follows SCR-089's `cv-rule-bundle/1` family (`E36D03:153–155`); the version is
   the bundle's own `schema_version` (`22:21408`), never an app version; and there is no date,
   because `exported_at` is inside the file (`22:21408–21409`) and a date in the name invites stale
   copies. The import reads the version inside the file and never the name (§5), so a renamed file
   imports as well as any other. The slug, PROPOSED in full:
@ ¶2 ‖ list ‖ 1
  1. the stored name, Unicode NFKD with its combining marks removed, lower-cased;
  2. every character outside `a`–`z` and `0`–`9` becomes `-`, a run of them one `-`, and the ends
   are trimmed;
  3. cut at 40 <!-- audit:contract.name_max=40 --> characters, the name's own cap (`22:19831`),
   and trimmed again;
  4. an empty result is `workspace`, and a Windows device name (`con`, `prn`, `aux`, `nul`, `com1`
   to `com9`, `lpt1` to `lpt9`) takes `workspace-` in front;
  5. the version keeps `0`–`9`, `a`–`z` and `.` only, by the same rule (D09-G2: the contract does
   not yet say what the string holds).
@ ¶3 ‖ table ‖ 1
  | Stored name | File name |
  | --- | --- |
  | Scalping | `scalping.cv-workspace-v1.json` |
  | Fanout review — EU session: BTCUSDT, ETH (E15-D03's 40-character name, `D03:126–128`) |
   `fanout-review-eu-session-btcusdt-eth.cv-workspace-v1.json` |
  | Café — Asia open | `cafe-asia-open.cv-workspace-v1.json` |
  | ★★★ | `workspace.cv-workspace-v1.json` |
  | CON | `workspace-con.cv-workspace-v1.json` |
@ ¶4 ‖ paragraph ‖ 1
  **The save sheet and the write.** Download file hands the file to the platform's save sheet, the
   operating system's file dialog reached through the browser's save picker or the desktop shell,
   with the suggested name and the JSON type (`application/json`, `.json`). The sheet is the
   operating system's layer, not this dialog's: the owner picks the folder and may change the name,
   and the page learns only the chosen file's base name, never its folder. The bytes are the
   response body as fetched, the very bytes the lists were counted from, never re-serialised and
   never added to: plain JSON, which E15-S07 keeps so a person can read the file before sending it
   (`BL:1136`). They are written whole or not at all (to a temporary file, then renamed), so a
   failed write leaves no partial file and turns the dialog to `SCR-025/export-failed` with
   "Couldn't save the file. Nothing was exported." (PROPOSED), whose Try again opens the sheet
   again. A sheet closed unsaved returns to the preview as it was, `SCR-025/export-cancelled`:
   nothing saved and no event (`FL:146`). Where a browser has no save picker, the file goes to its
   downloads under the suggested name; the hand-off is the only answer the page gets there, so it
   counts as the save (PROPOSED; D09-Q2). No path, folder or file name ever goes to the server
   (SR-097, `04:924`).
@ ¶5 ‖ paragraph ‖ 1
  **The completion step (BQ-8 RULED).** When the write ends, the body changes in place
   (`SCR-025/export-done`): a CMP-028 `success` line, "Exported Scalping as
   scalping.cv-workspace-v1.json.", the file name in `type.num.sm` and selectable, then the
   Excluded list, unchanged, so the owner sees what the file leaves out as they send it on. The
   Included list, the caveat and the conditional lines leave; the footer is Close alone, and focus
   lands on it. The line is spoken once, politely (CMP-028 `success`, `role="status"`,
   `15:311–320`). The name is the base name the sheet returned, so a file the owner renamed reads
   "Exported Scalping as desk-copy.json."; the name comes from outside the app, so it is shown as
   text, at most 40 <!-- audit:design.file_cap=40 --> characters with an ellipsis past them, the
   whole capped value in the accessible name, and never with its folder. Close, `Esc` or × ends the
   dialog, and focus returns to the opener (§2.2).
@ ¶6 ‖ paragraph ‖ 1
  **The event.** `workspace.exported{panelCount, schemaVersion}` fires once the file is saved:
   when the write ends, or, under the browser fallback, at the hand-off that stands for the save.
   The press of Download file alone never fires it, nor does a sheet closed unsaved or a failure.
   It carries the counts the lists showed: `panelCount` 7 <!-- audit:fixture.export_panels=7 -->
   and `schemaVersion` "1" for the fixture. It is analytics, never audit (`D02:84`), and it carries
   no workspace name, file name or symbol (`21:5079`); SCR-025's catalogue entry lists it on its
   Audit line (`14:616–627`), which D09-G10 settles.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 2. Export:
   entry points, the preview dialog, the file and its completion › 2.5 Per frame: what changes, the
   components and the focus#1
@ ¶0 ‖ heading ‖ 1
  ### 2.5 Per frame: what changes, the components and the focus
@ ¶1 ‖ paragraph ‖ 1
  Each row is a frame of §2.1, in the order the flow reaches it; §2.2's chrome and §2.3's anatomy
   hold unless the row says otherwise.
@ ¶2 ‖ table ‖ 1
  | State | Reached when | What changes (components and variants) | Focus, keys and announcements
   |
  | --- | --- | --- | --- |
  | entry (`SCR-025/export-entry`) | a menu opens on a stored workspace, or SCR-025 shows its
   Share section | a CMP-041 item, or SCR-025's CMP-001 `secondary` button | the arrows reach the
   item; `Enter` opens the dialog and the menu folds away; nothing is announced beyond the item's
   name |
  | unavailable (`SCR-025/export-unavailable`) | the workspace has no stored copy | the label in
   `color.text.tertiary` and its second line; no glyph | the arrows reach it; its name and its
   second line are read together; `Enter` and `Space` change nothing |
  | preparing (`SCR-025/export-preparing`) | Export… chosen | the dialog, CMP-038 in its body
   after the show-delay | focus on Cancel; CMP-038 speaks "Preparing the file…" once; Cancel, `Esc`
   and × end the read with nothing exported and focus back on the opener |
  | preview (`SCR-025/export-preview`) | the bundle passed the check (§2.3) | CMP-038 leaves; the
   two lists, the caveat and any conditional line arrive; Download file joins the footer | focus
   moves to the title if it was still on Cancel, and the title is read with the two lists, its
   `aria-describedby`; `Enter` on Download file opens the save sheet; Cancel, `Esc` and × end the
   dialog with nothing exported (`FL:146`) |
  | failed (`SCR-025/export-failed`) | the read answered `503` or nothing, or `403` or `404`; the
   check declined the bundle; or the write failed | CMP-027 `inline` takes the body; Try again
   joins the footer | focus on Try again; the message is spoken once, politely; Try again reads
   again (the preparing line, focus on Cancel) or, after a failed write, opens the sheet again |
  | cancelled (`SCR-025/export-cancelled`) | the save sheet closed unsaved | nothing: the preview
   as it was | focus on Download file; nothing is announced and no event fires |
  | done (`SCR-025/export-done`) | the write ended | the completion line over the Excluded list;
   the footer Close alone | focus on Close; the completion line is spoken once, politely;
   `workspace.exported` fires |
  | reflow (`SCR-025/export-reflow-200`) | 200 % zoom on 1280 × 800 (`05:131`) | CMP-043's reflow
   state; the two lists stack | as at 100 %, with nothing clipped |
@ ¶3 ‖ paragraph ‖ 1
  **Announcements.** Each spoken line comes from a region mounted empty with the dialog, its text
   inserted when its state begins, and each is spoken once, politely (`05:144`, `05:150`); opening
   the dialog adds nothing to what the focused control and the preparing line say, and a dismissed
   save sheet says nothing at all.
@ ¶4 ‖ paragraph ‖ 1
  **Exits.** Cancel, `Esc`, × and Close end the export dialog on each of its frames and for every
   session, view-as included, and `Esc` closes the menu that holds Export… (§7 states the rule
   once). Before the write they end it with nothing exported; a write already started still
   completes whole or not at all (§2.4). Focus returns to the opener, or, when the opener has gone,
   to the host's named fallback and never to the page's `body` (`15:466–468`).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying#1
@ ¶0 ‖ heading ‖ 1
  ## 3. The import flow: entry, the dialog, choosing a file, validating, applying
@ ¶1 ‖ paragraph ‖ 1
  SCR-026 is one CMP-043 `role="dialog"`, `size="lg"`, at most 960 <!--
   audit:contract.dialog_lg_px=960 --> px wide (`15:466`), because the preview's four columns need
   the width (BQ-9 RULED). Its steps share one chrome — choose, validating, preview, the send, the
   report — so the title "Import workspace", the close × and the footer's place never move while
   the body changes; no wizard header and no step counter is drawn. The import only ever creates a
   new workspace and never writes over one (D-30, `D02:148`; `D02:522`), so it needs no SCR-029 and
   no discard prompt. The trust note, `D02:513` verbatim, sits under the title from the first step
   to the send (BQ-2 RULED). Nothing is created before Import as new workspace, and nothing of the
   file is kept after a Cancel or a refusal (Condition 1; BQ-5 RULED). The frames below are binding
   and the tool gates them row by row; §3.2 to §3.5 give each one its anatomy, redlines, tokens and
   focus, and a decision that names no ruling is PROPOSED. The preview and the report are §4, the
   rejections and refusals §5, the T2 rule §6, and the full keyboard and announcement walk §7.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying › 3.1 Frames (binding; the tool
   gates every row)#1
@ ¶0 ‖ heading ‖ 1
  ### 3.1 Frames (binding; the tool gates every row)
@ ¶1 ‖ table ‖ 1
  | Frame | Producer | Shows | Class | Copy keys | Board |
  | --- | --- | --- | --- | --- | --- |
  | `SCR-026/entry` | an Owner or Manager session under the workspace limit opens "+" or the
   rail's workspace menu (`D03:365`; the rail's item is D09-A22's) | access: Import… in "+" and in
   the rail's workspace menu — T1 for Owner and Manager under 32 workspaces: a write
   (`workspaces:write`) whose legs §6 states; Esc → Close (the menu, focus back on its button);
   exits T1: Esc | T1 | `e15.import.menu_item` | 07 |
  | `SCR-026/entry-view-as` | a session viewing as alex opens "+" or the rail's workspace menu
   (`D02:519`, `D03:564`; the rail's item, D09-A22) | T2: Import… in "+" and in the rail's
   workspace menu — the full label, the CMP-019 `lock` leading it, `aria-disabled="true"` (never
   `disabled`), CMP-079 RbacGate, rendering one notice — the item points at the SCR-124 banner
   (§6); reason: `rbac.view_as` "Read-only while viewing as alex."; legs: `rbac.view_as` →
   `rbac.permission` → `workspace.limit.count`; Esc → Close (the menu, focus back on its button);
   exits T1: Esc | T2 | `e15.import.menu_item` · `rbac.view_as` | 07 |
  | `SCR-026/entry-permission` | a Viewer session opens "+" or the rail's workspace menu
   (`04:1141`, `D03:564`; the rail's item, D09-A22) | T2: Import… in "+" and in the rail's
   workspace menu — the full label, the CMP-019 `lock` leading it, `aria-disabled="true"` (never
   `disabled`), CMP-079 RbacGate, rendering 2a, the item's second line (§6); reason:
   `rbac.permission` "Your role can't save workspaces."; legs: `rbac.view_as` → `rbac.permission` →
   `workspace.limit.count`; Esc → Close (the menu, focus back on its button); exits T1: Esc | T2 |
   `e15.import.menu_item` · `rbac.permission` | 07 |
  | `SCR-026/entry-limit` | an Owner session at the workspace limit opens "+" or the rail's
   workspace menu (`22:8686`, `D03:564`; the rail's item, D09-A22) | T2: Import… in "+" and in the
   rail's workspace menu — the full label, the CMP-019 `lock` leading it, `aria-disabled="true"`
   (never `disabled`), CMP-079 RbacGate, rendering 2a, the item's second line (§6); reason:
   `workspace.limit.count` "You have the most workspaces you can have."; legs: `rbac.view_as` →
   `rbac.permission` → `workspace.limit.count`; Esc → Close (the menu, focus back on its button);
   exits T1: Esc | T2 | `e15.import.menu_item` · `workspace.limit.count` | 07 |
  | `SCR-026/pick` | Import… chosen: the dialog opens empty (`D02:513`) | dialog: CMP-043
   `size="lg"` `role="dialog"` "Import workspace", close × "Close Import workspace"; trust: CMP-028
   `info` `role="note"` under the title, not a Tab stop — "A workspace file never carries
   credentials or account bindings. Importing creates a new workspace and changes nothing else.";
   picker: Choose file… — a real `<button>` (CMP-001 `secondary`) fronting the labelled native
   `<input type="file">` (CMP-067, `accept=".json,application/json"`, `multiple` false), whose
   `Enter` or `Space` opens the OS picker; drop zone: around Choose file…, the words "or drop a
   workspace file here" as the button's `aria-describedby` — not a Tab stop, no role and no name of
   its own, and a drop only adds to the input; help: "JSON, up to 2 MB"; footer: Cancel
   (`secondary`); initial focus: Choose file…; Esc → Cancel; exits T1: Cancel · Esc · × | T1 |
   `e15.import.title` · `e15.import.close` · `e15.import.trust` · `e15.import.choose` ·
   `e15.import.drop_hint` · `e15.import.help` · `e15.import.cancel` | 02, 09 |
  | `SCR-026/drag-over` | one .json file dragged over the zone | dialog: CMP-043 `size="lg"`
   `role="dialog"` "Import workspace", close × "Close Import workspace"; trust: CMP-028 `info`
   `role="note"` under the title, not a Tab stop — "A workspace file never carries credentials or
   account bindings. Importing creates a new workspace and changes nothing else."; drop zone:
   drag-over — the words "Drop to check the file", the edge `color.border.selected` and the fill
   `color.surface.hover`, words and edge, never colour alone — not a Tab stop; footer: Cancel
   (`secondary`); initial focus: Choose file…; Esc → Cancel; exits T1: Cancel · Esc · × | T1 |
   `e15.import.drop_active` | not drawn — the text is binding; drawn on request |
  | `SCR-026/drag-over-rejected` | two files, or a file whose type is not JSON, dragged over the
   zone | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; drop zone: drag-over that cannot be taken (two files, or a type that is
   not JSON) — the words "Drop one .json file", the edge `color.border.default` — not a Tab stop;
   footer: Cancel (`secondary`); initial focus: Choose file…; Esc → Cancel; exits T1: Cancel · Esc
   · × | T1 | `e15.import.drop_rejected` | not drawn — the text is binding; drawn on request |
  | `SCR-026/validating` | `scalping.json` chosen: the worker checks it (`D02:515`, `14:637`) |
   dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; progress: CMP-023 determinate, `valueText` "Checking scalping.json… step
   3 of 5"; steps: size → parse depth / node count → schema → version → per-pane registry →
   preview; server: the server re-checks size, depth, nodes, schema and version when the file is
   imported (E15-S07) — this check in the browser is a courtesy and never replaces it; state:
   nothing created yet — no workspace, layout or pane exists until Import as new workspace; live:
   polite, once at the start and once at the end, never per step; caps: names 40 · symbols 20 ·
   panel kinds 32 · keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past the
   cap, the whole capped value in the accessible name); renders: every string from the file as text
   only — never markup, never a link, never interpreted; footer: Cancel (`secondary`); initial
   focus: Choose file…; Esc → Cancel; exits T1: Cancel · Esc · × | busy | `e15.import.checking` ·
   `e15.import.cancel` | 03 |
  | `SCR-026/creating` | Import as new workspace pressed on a valid preview: the file is sent once
   | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; busy: Import as new workspace keeps its label with `aria-busy="true"` —
   the file is sent once, and Close or `Esc` closes the view only; caps: names 40 · symbols 20 ·
   panel kinds 32 · keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past the
   cap, the whole capped value in the accessible name); renders: every string from the file as text
   only — never markup, never a link, never interpreted; footer: Close (`secondary`) · Import as
   new workspace (`primary`, `aria-busy`); initial focus: Import as new workspace; Esc → Close (the
   view only: the import is sent and finishes); exits T1: Close · Esc · × | busy |
   `e15.import.confirm` · `e15.import.close_view` | not drawn — the text is binding; drawn on
   request |
  | `SCR-026/import-leg-lost` | the session lost its permission while the dialog was open
   (`D02:645`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close
   Import workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A
   workspace file never carries credentials or account bindings. Importing creates a new workspace
   and changes nothing else."; T2: Import as new workspace, in place — the full label, the CMP-019
   `lock` leading it, `aria-disabled="true"` (never `disabled`), CMP-079 RbacGate, rendering 2a,
   under the button (§6); reason: `rbac.permission` "Your role can't save workspaces."; legs:
   `rbac.view_as` → `rbac.permission` → `workspace.limit.count`; caps: names 40 · symbols 20 ·
   panel kinds 32 · keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past the
   cap, the whole capped value in the accessible name); renders: every string from the file as text
   only — never markup, never a link, never interpreted; footer: Cancel (`secondary`) · Import as
   new workspace (T2, §6); initial focus: Import as new workspace; Esc → Cancel; exits T1: Cancel ·
   Esc · × | T2 | `e15.import.confirm` · `rbac.permission` | 07 |
  | `SCR-026/cancelled` | Cancel, `Esc` or × before the send (`FL:162`) | state: nothing imported
   — no workspace, layout or pane was created and your workspaces are unchanged | outcome | — | not
   drawn — the text is binding; drawn on request |
  | `SCR-026/compact` | the import dialog at the compact density | density: compact — the table's
   rows at the compact `size.row.height` and the controls at `size.control.compact`, the dialog
   padding unchanged | T1 (density) | — | not drawn — the text is binding; drawn on request |
  | `SCR-026/reflow-200` | the import dialog at 200 % zoom (`05:131`) | reflow: at 200 % on 1280 ×
   800 the dialog fills the viewport less 16 px a side, keeps its title and footer, scrolls its
   body and reads the table one row element per record (`15:529`) | T1 (reflow) | — | not drawn —
   the text is binding; drawn on request |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying › 3.2 The entries and the
   dialog's one chrome#1
@ ¶0 ‖ heading ‖ 1
  ### 3.2 The entries and the dialog's one chrome
@ ¶1 ‖ paragraph ‖ 1
  **Entries (BQ-9 RULED).** Import… is an item of the tab strip's "+" menu, after New workspace…
   and Open workspace… (`D03:365`), and of the rail's workspace menu, where no merged text places
   it yet (BQ-9 RULED; D09-A22 to E15-D03 and E15-D05); either opens the dialog empty (`D02:513`),
   routed as `?modal=import` (BQ-9's route). The route is a way in of its own: a link, a restore or
   Back opens the dialog for any session, and where §6's legs gate Import…, the dialog's Import as
   new workspace takes §6's form in place from the start, as on `SCR-026/import-leg-lost`, while
   Choose file…, the checks and the preview work as for every session. Import… is a write, because
   it creates a workspace (`createWorkspace`, `22:8682`; no operation takes a bundle yet,
   `22:21419`), so §6's legs gate it, view-as first, with the keys merged E15-D02 and E15-D03 carry
   (`D02:655`; `D03:564`). An Owner or a Manager under 32 <!-- audit:contract.workspaces_max=32 -->
   workspaces (`22:8686`) meets `SCR-026/entry` (`04:1141`); the three other entry frames,
   `SCR-026/entry-view-as`, `SCR-026/entry-permission` and `SCR-026/entry-limit`, are drawn as §6
   states the rule. Each menu's own `Esc` closes it and returns focus to its button, on every entry
   frame (§7).
@ ¶2 ‖ paragraph ‖ 1
  **One chrome, five steps (BQ-9 RULED).** The body changes with the step; the header, the trust
   note and the footer's place do not. A rejection or a refusal takes the preview's place in the
   body (§5).
@ ¶3 ‖ table ‖ 1
  | Step | The body, top to bottom | The footer, Cancel first and the primary last | Frames |
  | --- | --- | --- | --- |
  | choose | the trust note; the drop zone around Choose file…; the help line (§3.3) | Cancel |
   `SCR-026/pick`, `SCR-026/drag-over`, `SCR-026/drag-over-rejected` |
  | validating | the trust note; the zone; the file line; CMP-023 (§3.4) | Cancel |
   `SCR-026/validating` |
  | preview | the trust note; the zone; the file line; the migration or the budget line when one
   applies; the clash line when one applies; CMP-049 (§4.4) | Cancel · Import as new workspace |
   `SCR-026/preview`, `SCR-026/preview-migrated`, `SCR-026/preview-over-budget` |
  | the send | the trust note; the preview's lines and table, read-only (§3.5) | Close · Import as
   new workspace, busy | `SCR-026/budget-confirm` (stacked first, over the budget only),
   `SCR-026/creating` |
  | the report | the report region (§4.5) | Copy report · Close | `SCR-026/report` |
  | a rejection | the trust note; CMP-027 `inline`; the zone with Choose file…, its words and its
   help line, which leave the body at the limit and after an unanswered send (§5.2) | Cancel ·
   Choose another file; Cancel alone at the limit; Close alone after an unanswered send | §5.1's
   six rejections and three outcomes at the send |
@ ¶4 ‖ paragraph ‖ 1
  **Anatomy and redlines (comfortable; compact changes the control and row heights only).** One
   semantic name per binding: the light twin (board 09) re-points the same names (`16` §4) and
   changes none, and §8 measures every pair in dark, light and high contrast. Every px value below
   is the tool's, from the token files. Every target is at least `05:100`'s floor,
   `size.target.min` 24 <!-- audit:redline.size.target.min=24 --> px: the controls are
   `size.control.height` tall, 32 <!-- audit:redline.size.control.comfortable=32 --> px comfortable
   and 24 <!-- audit:redline.size.control.compact=24 --> px compact, and the × is a square of that
   height (D09-C19).
@ ¶5 ‖ table ‖ 1
  | Part | Component and variant | Layout and redlines | Tokens |
  | --- | --- | --- | --- |
  | Scrim | CMP-043's | over the page between the TopBar and the StatusBar, which stay above it
   with the shell's live regions (`15:463–468`) | `palette.black` at `opacity.scrim` 0.6 <!--
   audit:redline.opacity.scrim=0.6 --> |
  | Card | CMP-043 `role="dialog"`, `aria-modal="true"`, `size="lg"` | at most 960 <!--
   audit:contract.dialog_lg_px=960 --> px wide (`15:466`); as tall as its content, then CMP-043's
   scrolls state with a fixed header and footer; its top edge stays where it opened while the body
   grows, so the title and the zone never move under the pointer (PROPOSED); padding
   `space.dialog.padding` 24 <!-- audit:redline.space.dialog.padding=24 --> px; header, body and
   footer `space.stack.md` 12 <!-- audit:redline.space.stack.md=12 --> px apart |
   `color.surface.overlay`; `elevation.dialog`; `radius.dialog` 10 <!--
   audit:redline.radius.dialog=10 --> px; a `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px `color.border.default` edge, decorative |
  | Header | the title, an `h2` and the dialog's `aria-labelledby`; CMP-002 `ghost` for the × |
   one row: the title at its start, the × at its end in a square of the control height, 32 <!--
   audit:redline.size.control.comfortable=32 --> px comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px compact; the × named "Close Import workspace" |
   title `type.ui.heading-sm` + `color.text.primary`; the × glyph in its context's text token
   (`15:225`) |
  | Trust note | CMP-028 `info`, `role="note"`, `live="off"` (E36-D03's privacy-note form) | under
   the header, full width; the dialog's `aria-describedby`, so a screen reader hears it as focus
   enters the dialog (PROPOSED); never a Tab stop; padding `space.inset.sm` 8 <!--
   audit:redline.space.inset.sm=8 --> px; a `border.thick` 2 <!-- audit:redline.border.thick=2 -->
   px start edge; the glyph at `size.icon` 16 <!-- audit:redline.size.icon=16 --> px | fill
   `color.status.info.subtle`; edge and glyph `color.status.info.strong`; words `type.ui.body` +
   `color.text.primary`; `radius.card` 6 <!-- audit:redline.radius.card=6 --> px |
  | Body | the step's content (§3.3 to §4.5) | `space.stack.md` 12 <!--
   audit:redline.space.stack.md=12 --> px between its blocks; it scrolls only at 200 % zoom, where
   the table stacks (`SCR-026/reflow-200`) | — |
  | Footer | a CMP-001 row | end-aligned, `space.inset.sm` 8 <!-- audit:redline.space.inset.sm=8
   --> px apart, Cancel (or Close) first and the primary last, each the control height | primary
   `color.action.primary.default` + `color.text.on-action`; secondary
   `color.action.secondary.default` + `color.text.primary` |
  | Focus | CMP-039 | a `border.focus` 2 <!-- audit:redline.border.focus=2 --> px ring at
   CMP-039's offset on every Tab stop | `color.focus.ring` |
@ ¶6 ‖ paragraph ‖ 1
  **Focus and keys in the dialog (BQ-13 RULED; the walk itself is §7 and board 08).** Opening
   moves focus to Choose file… (CMP-043's `initialFocusRef`, `15:463–468`); nothing is announced
   beyond what focus entering reads, the title and then the trust note as the dialog's description.
   `Tab` runs the trap in DOM order: the ×, Choose file…, the table's scroll region once a preview
   stands, then the footer from its first button to the primary. The drop zone is never a Tab stop,
   and neither are the trust note, the help line and the file line, which are text. `Esc` closes
   the topmost layer only: the OS file picker first (the browser's own layer, which returns focus
   to Choose file…), then the stacked confirm, then the dialog (`S4:734`). Before the send, `Esc`,
   Cancel, the × and a press on the scrim close the dialog with nothing imported
   (`SCR-026/cancelled`); once the file is sent they close the view and cancel nothing (`15:468`).
   On close, focus returns to the button of the menu Import… came from, "+" or the rail's workspace
   menu, because the item went with its menu (CMP-043's named fallback, `15:463–468`); after a
   successful import, Close lands on the new workspace's tab (§4.5).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying › 3.3 Choose file… and the drop
   zone (CMP-067)#1
@ ¶0 ‖ heading ‖ 1
  ### 3.3 Choose file… and the drop zone (CMP-067)
@ ¶1 ‖ paragraph ‖ 1
  **Choose file… (BQ-13 RULED; AC 6).** A real `<button>`, CMP-001 `secondary`, whose label
   "Choose file…" is the visible label `14:636` asks for and whose `Enter` or `Space` opens the OS
   file picker. It fronts CMP-067's native `<input type="file">` (`15:690–696`), which carries
   `accept=".json,application/json"` and `multiple` false: the input is `hidden`, so it is out of
   the Tab order and out of the accessibility tree, the button's click opens it, and it stays
   labelled by the button (`aria-labelledby`), so the one control a keyboard or screen-reader user
   meets is the button and browse mode finds no second Choose file… (PROPOSED anatomy; E36-D03's
   SCR-089 puts the native input first, `E36D03:153–155`). The button's `aria-describedby` names
   the drop hint, then the help line, so a screen reader hears "Choose file…, button, or drop a
   workspace file here, JSON, up to 2 MB". The OS picker filters by `accept`; leaving it with `Esc`
   returns focus to the button with nothing chosen and nothing announced. Choose file… stays live
   through the validating, the preview and every rejection: a new pick discards the file in hand
   and starts the check again from its first step.
@ ¶2 ‖ paragraph ‖ 1
  **The drop zone (BQ-9 RULED; `05:35`, `05:101`).** A box around Choose file… that adds a second
   way in and is never the only one (`15:694`; WCAG 2.5.7). The drop zone has no role and no name
   of its own and is never a Tab stop; its words, "or drop a workspace file here" (`D02:513`), are
   the button's description. A drop only adds to the input: a dropped file goes through the same
   five steps as a picked one (§3.4), and the zone takes one file. While files are dragged over it,
   the zone shows one of two states, each in words and an edge, never colour alone:
@ ¶3 ‖ list ‖ 1
  - `SCR-026/drag-over`, one file that may be JSON: the words "Drop to check the file" in place of
   the hint, the edge `color.border.selected` at `border.thick` 2 <!-- audit:redline.border.thick=2
   --> px inside the box (no layout shift) on the fill `color.surface.hover`.
  - `SCR-026/drag-over-rejected`, two or more files, or one whose type the drag already shows is
   not JSON: the words "Drop one .json file", the edge `color.border.default`. A drag carries no
   file name, so neither state prints one.
@ ¶4 ‖ paragraph ‖ 1
  Dropping two or more files reads none of them and changes nothing: the zone returns to rest and
   its drag-over words, "Drop one .json file", are announced once, politely (PROPOSED; no event
   fires, because nothing was read). A drop that carries no file — text, an address, an HTML
   fragment, an image dragged from a page — is ignored: nothing is read, nothing is fetched and no
   address is ever followed (SR-097, `04:924`); only the drop's files are read, and only through
   the input. While the dialog is open, a drop outside the zone is ignored too, the page's default
   prevented, so a file let go over the header, the footer or the scrim never makes the page open
   it (D09-D34). Dropping one file that is not JSON leads to `SCR-026/rejected-wrong-type` (§5.1):
   the picker filters by type, a drop does not. A drag is a pointer gesture and its states announce
   nothing; Choose file… is the keyboard path to the same input (`05:101`).
@ ¶5 ‖ table ‖ 1
  | Part | Component and variant | Layout and redlines | Tokens |
  | --- | --- | --- | --- |
  | The zone | CMP-067's drop target, a box with no role (PROPOSED: the label, the hint and the
   states are A-rows to CMP-067, §10) | full body width; padding `space.inset.xl` 24 <!--
   audit:redline.space.inset.xl=24 --> px; Choose file… centred, its words `space.stack.md` 12 <!--
   audit:redline.space.stack.md=12 --> px under it; `radius.card` 6 <!--
   audit:redline.radius.card=6 --> px; a `border.hairline` 1 <!-- audit:redline.border.hairline=1
   --> px solid edge, never dashed: `color.border.dashed` is not a shipped token (`15:695`) and
   E36-D03 re-bound it the same way (`E36D03:272`) | edge `color.border.default`, decorative
   because the zone is not the control (§8); the words `type.ui.body` + `color.text.secondary` |
  | Choose file… | CMP-001 `secondary`, `md` | the control height, 32 <!--
   audit:redline.size.control.comfortable=32 --> px comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px compact; the dialog's focus ring | fill
   `color.action.secondary.default`; label `color.text.primary` |
  | Native input | `<input type="file">` (CMP-067), `hidden` | out of the Tab order and the
   accessibility tree; opened by the button's click; `aria-labelledby` the button | none drawn |
  | Help line | text under the zone | `space.stack.md` 12 <!-- audit:redline.space.stack.md=12 -->
   px under it; "JSON, up to 2 MB" (`e15.import.help`) | `type.ui.caption` + `color.text.secondary`
   |
  | File line | the chosen file's name, once a file is picked or dropped (PROPOSED) | under the
   help line, `space.stack.md` 12 <!-- audit:redline.space.stack.md=12 --> px; at most 40 <!--
   audit:design.file_cap=40 --> characters, an ellipsis past them, text only (Condition 1): the
   local name of a file someone else may have named | `type.num.sm` + `color.text.primary` |
  | Drag-over | the zone's two states | the edge only thickens, inside the box; the words replace
   the hint in the hint's place | accept: edge `color.border.selected` on `color.surface.hover`;
   reject: edge `color.border.default` on `color.surface.overlay`; words `type.ui.body-strong` +
   `color.text.primary` |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying › 3.4 The five check steps, the
   validating state and the server's re-check#1
@ ¶0 ‖ heading ‖ 1
  ### 3.4 The five check steps, the validating state and the server's re-check
@ ¶1 ‖ paragraph ‖ 1
  **The order (BQ-5 RULED; Condition 1).** A picked or dropped file is checked in a worker,
   cheapest step first, and only a file that passes every step reaches the preview (E15-S07's
   order, `BL:1136`; `14:637`): size → parse depth / node count → schema → version → per-pane
   registry → preview. The first step that fails ends the check: its rejection takes the progress's
   place, the later steps never run, and nothing of the file is kept (§5).
@ ¶2 ‖ table ‖ 1
  | # | Step | What the worker checks | The limit (the Fixture paragraph) | When it fails, or what
   it finds | `layout.import_rejected{reason}` |
  | --- | --- | --- | --- | --- | --- |
  | 1 | size | the file's type and size, from its metadata, before a byte of it reaches the
   parser: a file over the cap is never parsed (`BL:1136`); the type check refuses a file only when
   its name, read after §5.5's cleaning, does not end in `.json` and its media type is not
   `application/json`, so a blank type never refuses a `.json` name; a picked file's type is
   checked too, because `accept` only filters what the OS picker offers | 2 <!--
   audit:contract.size_mb=2 --> MB, E15-S07's default (`BL:1136`), PROPOSED for `22` (D09-G5) |
   `SCR-026/rejected-oversized`; a dropped file that is not JSON: `SCR-026/rejected-wrong-type` |
   `oversized`; `wrong-type` |
  | 2 | parse depth / node count | the JSON, parsed in the worker with both limits counted while
   it parses, so a hostile file stalls a worker and never the page (`BL:1136`) | depth 16 <!--
   audit:contract.depth=16 --> levels, the server's own rule for a request body (`22:19819`);
   10,000 <!-- audit:contract.nodes=10000 --> values (`BL:1136`), PROPOSED (D09-G5) |
   `SCR-026/rejected-nodes` (the depth, with the node count its variant); invalid JSON:
   `SCR-026/rejected-malformed`'s parse variant, which names the line | `malformed` |
  | 3 | schema | first the envelope, `schema_version` present and a whole number (D09-D25), else
   the malformed outcome that names it; then the shape of that format version, only when this app
   reads it (one shape per readable version, D09-G2), against `WorkspaceBundle` (`22:21402–21423`):
   every required key present and every known key's value of its kind, a pane's kind an open string
   for a reader (`22:19971`), no layout over its panes, no workspace over its layouts, the
   indicator presets whole or not at all; an unknown key is ignored and never read into the app
   (C-6.3); a version above the newest or below the floor skips the shape and goes to step 4, so
   the shape never shadows the version outcome (D09-Q5) | 16 <!-- audit:contract.panes_max=16 -->
   panes a layout (`D02:133`); 32 <!-- audit:contract.layouts_max=32 --> layouts a workspace
   (`22:8886`); 200 <!-- audit:contract.presets_max=200 --> presets a file (`22:21422–21423`) |
   `SCR-026/rejected-malformed`: the missing key, or the known key whose value is the wrong kind,
   named in mono, or its panes, layouts and presets variants | `malformed` |
  | 4 | version | the file's `schema_version` (`22:21408`) against the format version this app
   reads (BQ-4 RULED): newer is refused; older and still readable is migrated forward in the
   worker; older than the oldest this app reads is refused | this app reads format version 1 <!--
   audit:fixture.app_format=1 -->; the order of versions and the oldest one read are D09-G2's |
   `SCR-026/rejected-version-newer`; `SCR-026/rejected-version-older`; a migration is no failure:
   `SCR-026/preview-migrated` | `version-newer`; `version-older` |
  | 5 | per-pane registry | each pane's kind against this build's registry (`22:19971`) and each
   pane setting against the registry's list for its kind (`BL:1136`) | — | nothing fails here: an
   unknown kind is a Drop row, never a refusal (AC 3); a setting the registry marks account-scoped
   is a Drop row, and so is a setting it does not list for its kind, a newer build's option
   (D09-D35); the Positions pane is the one Remap (§4.2) | — |
  | — | preview | the table of §4.2, built from the document already parsed, with no second parse
   (`BL:1136`) | the panel budget of the layout that opens (§4.4) | over the budget: the budget
   line and the stacked confirm (§4.4) | `budget-exceeded`, only when that confirm is cancelled |
@ ¶3 ‖ paragraph ‖ 1
  **The validating state (DL-11; BQ-9 RULED).** `SCR-026/validating` is CMP-023, determinate
   (`15:262–268`): its value moves a fifth at each step, and its value text, always shown, reads
   "Checking scalping.json… step 3 of 5" (`e15.import.checking`: `D02:515`'s words with the step
   added), the file's name capped at 40 <!-- audit:design.file_cap=40 --> characters as text. The
   bar sits under the file line, full body width; its track `color.surface.hover`, its fill
   `color.action.primary.default`, its value text `type.num.sm` + `color.text.secondary` (CMP-023's
   own tokens; §8 rows 27 to 29: the fill carries the value against the track, the track is
   decorative and the value text carries the state). A show-delay of 150 ms (BQ-9's default, ruled
   as proposed) keeps a file that validates within the 500 <!-- audit:contract.parse_ms=500 --> ms
   of `14:637` from flashing the bar; a check that ends inside the delay shows its outcome at once,
   with no start announcement. The step names stay in this spec and in the analytics mapping and
   are not printed: "schema" and "registry" are not a trader's words, so the value text counts the
   steps instead. That departs from `D02:515`, which names them, and is a PROPOSED C-row (D09-C13).
@ ¶4 ‖ paragraph ‖ 1
  **What is spoken (BQ-13 RULED; `05:144`, `05:150`).** The dialog mounts one polite region,
   empty, with its body (`05:150`); CMP-023 is never a live region itself (`15:262–268`). The check
   speaks at most twice: once when the bar first shows, its value text at step 1, and once at its
   end, the preview's caption on a pass (the migration line first on a migrated file; over the
   budget the caption carries the budget sentence itself), or, on a fail, the rejection's own
   CMP-027, which speaks for itself (§5). Never per step, never per percent. On a pass focus stays
   on Choose file…, so the next `Tab` reaches the table (`05:96`); on a fail it moves to Choose
   another file once the message has been announced (§5).
@ ¶5 ‖ paragraph ‖ 1
  **What the check in the browser is, and is not (Condition 1).** It is a courtesy: it tells the
   user early and keeps a hostile file away from the page, and it never replaces the server's own
   check. The server re-checks size, depth, nodes, schema and version when the file is imported
   (E15-S07, `BL:1136`); it refuses unknown fields on its write paths (SR-040, `04:855`) and treats
   the browser as hostile (`04:54`), and the ticket's Security notes say the same of every client
   guard (`BL:266`). `SCR-026/validating` says so in its `server:` clause, which the tool gates
   (S14). A file the server refuses at the send is `SCR-026/refused-server` (§5.1) and never a
   partial import, because the import is one request that creates everything or nothing (D09-G1,
   §12). Until it has passed, the file is never used to build a component, open a window or send a
   request (`BL:1136`), and no import path takes a filesystem path (SR-097, `04:924`). The worker
   reads the file as plain data and builds the preview only from the fields `WorkspaceBundle`
   names, so an unknown key, `__proto__` and `constructor` included, is never read into the app:
   the client ignores it, as C-6.3 asks of every client, and the server refuses it on its write
   path, fail closed (C-6.3; SR-040, `04:855`), which is `SCR-026/refused-server`; D09-G4 asks `22`
   to close the schemas so the bundle says so too, and E15-S07's fuzz corpus covers the
   prototype-shaped keys (`BL:1136`).
@ ¶6 ‖ paragraph ‖ 1
  **Nothing is kept.** Cancel during the check stops the worker and releases the file and
   everything parsed from it; a refusal at any step does the same, and so does a new pick, which
   starts again from the first step. Nothing from the file is stored, sent or logged before Import
   as new workspace: workspace and layout content is never logged (`21:5079`), and E15-S07 logs its
   export requests without file contents (`BL:1136`).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 3. The import
   flow: entry, the dialog, choosing a file, validating, applying › 3.5 The send, the creating
   state and every frame of §3.1#1
@ ¶0 ‖ heading ‖ 1
  ### 3.5 The send, the creating state and every frame of §3.1
@ ¶1 ‖ paragraph ‖ 1
  **The send (BQ-9 RULED; D-30, `D02:148`).** Import as new workspace sends the checked file once,
   and the server creates the new workspace with all of it in one request, or nothing (D09-G1, §12:
   no operation of `22` takes a bundle, `22:21419`, and E15-S07 lands one first, C-6.1; done in the
   client as `createWorkspace` and then `createLayout` per layout, the import would not be atomic,
   `FL:171`, which is why no frame here shows a partial state). The bytes sent are the bytes the
   preview was built from, held in the worker and never read again from the file's handle, so a
   file changed on disk after its preview never reaches the server unseen (D09-D32). Over the panel
   budget, the stacked confirm comes first (§4.4). A name already in use is the server's to settle,
   never a rename field: the preview's clash line names the result, "Imported as Scalping (2): a
   workspace named Scalping exists." (`D02:516`), and the report names the name the server gave
   (§4.5). The new workspace starts unpinned, and environment binding is never imported (the
   ticket's Security notes, `BL:266`).
@ ¶2 ‖ paragraph ‖ 1
  **Creating (`SCR-026/creating`).** Import as new workspace keeps its label, with
   `aria-busy="true"` and CMP-001's spinner after the label, its width fixed (`15:48`; CMP-001's
   buy and sell keep their label the same way, PROPOSED for this primary so the effect stays named
   while it runs). Cancel becomes Close, because a sent file can no longer be called back. The zone
   and Choose file… leave the body, so nothing can be chosen mid-send, an absence of the step and
   not a lock; the table stays, read-only and still scrollable. Close, `Esc`, the × and a press on
   the scrim close the view only: the import goes on and finishes (`15:468`; H22, `S4:734`). After
   CMP-001's slow-path delay, "Still importing…" shows under the footer, end-aligned in
   `type.ui.caption` + `color.text.secondary`, and is spoken once, politely (PROPOSED copy,
   `e15.import.slow`). Focus stays on Import as new workspace.
@ ¶3 ‖ paragraph ‖ 1
  **When the view was closed during the send (PROPOSED; H22's outcome surface, `S4:734`).** The
   new workspace still opens in a tab, and a persistent CMP-045 `success` toast writes the report's
   success line (`e15.import.report.done`) once into CMP-212's polite region, with the action View
   report (`e15.import.report.view`), which reopens SCR-026 at its report (§4.5); a toast with an
   action stays until it is dismissed (`15:483`). A refusal that arrives after the view closed
   raises a persistent CMP-045 `danger` toast, "Nothing was imported." (`e15.import.nothing`), with
   the action Review (`e15.import.review`), which reopens SCR-026 at the refusal's frame (§5.1). A
   send left unanswered after the view closed raises a persistent CMP-045 `warning` toast with
   `SCR-026/refused-unconfirmed`'s words, "We couldn't confirm the import. Check your workspaces
   before importing again." (`e15.import.refused.unconfirmed`), and the action Review, which
   reopens SCR-026 at that frame; it never writes "Nothing was imported." (`e15.import.nothing`),
   since the import may have happened (D09-D33). No toast is the report: the report is the dialog's
   region (BQ-12 RULED). What a toast reopens lasts only as long as the toast: the report's rows or
   a refusal's capped message, never the file, its text or its document; dismissing the toast drops
   it.
@ ¶4 ‖ paragraph ‖ 1
  **When the session changes while the dialog is open (`SCR-026/import-leg-lost`; §6).** If the
   session loses `workspaces:write` (`D02:645`), or a view-as context starts meanwhile, Import as
   new workspace takes §6's form where it stands. Choose file…, the zone, the check and the table
   are client work and stay T1 for every session. A workspace limit the client has not learned is
   the send's refusal, `SCR-026/refused-limit` (§5.1). The rule, its anatomy and the order of the
   legs are §6's alone.
@ ¶5 ‖ paragraph ‖ 1
  **Cancelled (`SCR-026/cancelled`; `FL:162`).** Cancel, `Esc`, the × or a press on the scrim
   before the send closes the dialog at once, with no discard prompt, because a chosen file is not
   unsaved work (H36, `S4:904`): the worker stops, the file and everything parsed from it are
   released, no event fires and nothing is announced, and focus returns to the menu's button.
@ ¶6 ‖ paragraph ‖ 1
  **Density and zoom.** `SCR-026/compact` changes two values: the controls take
   `size.control.compact`, 24 <!-- audit:redline.size.control.compact=24 --> px, and the table's
   rows take the compact `size.row.height`, 24 <!-- audit:redline.size.row.height=24 --> px;
   padding, gaps and type are unchanged (`16` §3). `SCR-026/reflow-200` is CMP-043's reflow
   (`15:463–468`; `05:131`): the dialog fills the viewport, the header and the footer stay in view
   and the footer wraps in its order, the body scrolls, and the table stacks one row element per
   record (`15:529`), each record its Item, Type, Action and Reason as labelled lines with the
   Action's glyph beside its word.
@ ¶7 ‖ paragraph ‖ 1
  **Per frame: what changes, the components and the focus.** Each row names a frame of §3.1 by its
   state; the anatomy of §3.2 and §3.3 holds unless the row says otherwise.
@ ¶8 ‖ table ‖ 1
  | State | What changes (layout, components and variants, tokens) | Focus order, keys and
   announcements |
  | --- | --- | --- |
  | entry | Import…, a CMP-041 item in the "+" menu (CMP-002 "+", `D03:365`) and in the rail's
   workspace menu, its label `type.ui.body` + `color.text.primary` | the arrow keys reach it;
   `Enter` or `Space` opens the dialog on Choose file…; `Esc` closes the menu and returns focus to
   its button |
  | entry-view-as | the item in §6's form, pointing at the SCR-124 banner, the one notice, with no
   reason line of its own (`D02:635–674`) | the arrow keys reach it; `Enter` or `Space` opens
   nothing and re-shows the reason once, politely (§6); `Esc` closes the menu and returns focus to
   its button |
  | entry-permission | the item in §6's form with its reason as its second line, "Your role can't
   save workspaces." (`rbac.permission`; the verb is E09-D09's, `E09D09:114`) | as entry-view-as |
  | entry-limit | the item in §6's form with its reason as its second line, "You have the most
   workspaces you can have." (`workspace.limit.count`, `D03:634`) | as entry-view-as |
  | pick | §3.2's chrome: the trust note, the zone with Choose file… and its words, the help line;
   the footer Cancel; CMP-043, CMP-002, CMP-028, CMP-067, CMP-001 ×2 | opens on Choose file…;
   `Tab`: Choose file… → Cancel → × → Choose file…; `Enter` or `Space` on Choose file… opens the OS
   picker; on open only the title and the trust note are read |
  | drag-over | the zone's accept state (§3.3); nothing else moves | focus stays where it was;
   nothing is announced |
  | drag-over-rejected | the zone's reject state (§3.3) | focus stays where it was; a drop of two
   files speaks its words once, politely (§3.3) |
  | validating | the file line and CMP-023 under the zone (§3.4); Choose file… stays live | focus
   stays on Choose file…; one polite announcement at the start and one at the end (§3.4); Cancel
   stops the worker and closes the dialog |
  | creating | Import as new workspace busy, its label kept; Cancel becomes Close; the zone
   leaves; the table read-only; the slow-path line under the footer after CMP-001's delay | focus
   stays on Import as new workspace; `Tab`: the table's scroll region → Close → Import as new
   workspace → × → the scroll region; Close, `Esc`, the × and the scrim close the view only; the
   slow-path line once, politely |
  | import-leg-lost | Import as new workspace in §6's form where it stands, its reason "Your role
   can't save workspaces." under it (2a); nothing else changes | focus stays where it was; one
   announcement (§6) |
  | cancelled | no dialog | focus on the menu's button; nothing is announced |
  | compact | the controls at `size.control.compact` and the rows at the compact
   `size.row.height`; nothing else | as pick |
  | reflow-200 | the dialog fills the viewport; the header and the footer stay in view; the body
   scrolls; the table stacks (`15:529`) | as at 100 %; nothing is clipped (`05:131`) |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report#1
@ ¶0 ‖ heading ‖ 1
  ## 4. The preview table and the report
@ ¶1 ‖ paragraph ‖ 1
  The preview is the whole design (the ticket's Technical notes, `BL:242`): an import that only
   asks whether to go ahead asks the user to trust an opaque file, while a table that lists every
   drop and remap first, and every addition after, makes the import an informed decision. One table
   serves both moments, the preview before the send (§4.2) and the report after it (§4.3), row for
   row (AC 3, AC 4). The frames below are binding and the tool gates them row by row, and §4.2 and
   §4.3 are the fixture's rows, gated cell by cell; §4.4 gives the preview's anatomy, the budget
   line, the stacked confirm and the migration line, and §4.5 the report with Copy report.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report › 4.1 Frames (binding; the tool gates every row)#1
@ ¶0 ‖ heading ‖ 1
  ### 4.1 Frames (binding; the tool gates every row)
@ ¶1 ‖ table ‖ 1
  | Frame | Producer | Shows | Class | Copy keys | Board |
  | --- | --- | --- | --- | --- | --- |
  | `SCR-026/preview` | `scalping.json` passed every step: §4.2 is its table (`D02:516`) | dialog:
   CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import workspace"; trust:
   CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace file never carries
   credentials or account bindings. Importing creates a new workspace and changes nothing else.";
   table: CMP-049 table mode with §4.2's rows, caption "Preview — 7 panels and 2 layouts to add · 3
   dropped · 1 remapped"; actions: exactly three words in their own column, each after a decorative
   CMP-019 glyph — Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED) — never
   colour alone; clash: "Imported as Scalping (2): a workspace named Scalping exists."; state:
   nothing created yet — no workspace, layout or pane exists until Import as new workspace; caps:
   names 40 · symbols 20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120
   (characters, an ellipsis past the cap, the whole capped value in the accessible name); renders:
   every string from the file as text only — never markup, never a link, never interpreted; footer:
   Cancel (`secondary`) · Import as new workspace (`primary`); initial focus: Choose file…; Esc →
   Cancel; exits T1: Cancel · Esc · × | T1 | `e15.import.caption` · `e15.import.col.item` ·
   `e15.import.col.type` · `e15.import.col.action` · `e15.import.col.reason` ·
   `e15.import.action.add` · `e15.import.action.drop` · `e15.import.action.remap` ·
   `e15.import.reason.unknown_kind` · `e15.import.reason.account` · `e15.import.reason.remap` ·
   `e15.import.clash` · `e15.import.cancel` · `e15.import.confirm` | 03, 09 |
  | `SCR-026/preview-migrated` | a format version 1 file opened by a later app that reads format
   version 2 (E15-S07 migrates it forward, `BL:1111`) | dialog: CMP-043 `size="lg"` `role="dialog"`
   "Import workspace", close × "Close Import workspace"; trust: CMP-028 `info` `role="note"` under
   the title, not a Tab stop — "A workspace file never carries credentials or account bindings.
   Importing creates a new workspace and changes nothing else."; table: CMP-049 table mode with
   §4.2's rows, caption "Preview — 7 panels and 2 layouts to add · 3 dropped · 1 remapped";
   actions: exactly three words in their own column, each after a decorative CMP-019 glyph — Add
   (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED) — never colour alone;
   migrated: CMP-028 `info` "Migrated from format version 1 to 2." above the table; state: nothing
   created yet — no workspace, layout or pane exists until Import as new workspace; compares: the
   file's `schema_version` (1) with the format version this app reads (2) — never an app version;
   caps: names 40 · symbols 20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120
   (characters, an ellipsis past the cap, the whole capped value in the accessible name); renders:
   every string from the file as text only — never markup, never a link, never interpreted; footer:
   Cancel (`secondary`) · Import as new workspace (`primary`); initial focus: Choose file…; Esc →
   Cancel; exits T1: Cancel · Esc · × | T1 | `e15.import.caption` · `e15.import.migrated` | not
   drawn — the text is binding; drawn on request |
  | `SCR-026/preview-over-budget` | `wall.json` passed every step and the layout that opens, Wall,
   estimates over the frame budget (`D02:133`) | dialog: CMP-043 `size="lg"` `role="dialog"`
   "Import workspace", close × "Close Import workspace"; trust: CMP-028 `info` `role="note"` under
   the title, not a Tab stop — "A workspace file never carries credentials or account bindings.
   Importing creates a new workspace and changes nothing else."; table: CMP-049 table mode, §4.2's
   columns and order for `wall.json`, caption "Preview — 12 panels and 1 layout to add. Wall opens
   at about 17.9 ms per frame (estimated), over the 16 ms budget."; budget: CMP-028 `warning` "Wall
   opens with 12 panels: about 17.9 ms per frame (estimated), over the 16 ms budget." above the
   table; actions: exactly three words in their own column, each after a decorative CMP-019 glyph —
   Add (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED) — never colour alone;
   state: nothing created yet — no workspace, layout or pane exists until Import as new workspace;
   caps: names 40 · symbols 20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120
   (characters, an ellipsis past the cap, the whole capped value in the accessible name); renders:
   every string from the file as text only — never markup, never a link, never interpreted; footer:
   Cancel (`secondary`) · Import as new workspace (`primary`); initial focus: Choose file…; Esc →
   Cancel; exits T1: Cancel · Esc · × | T1 | `e15.import.caption_budget` · `e15.import.budget` | 05
   |
  | `SCR-026/budget-confirm` | Import as new workspace pressed on `SCR-026/preview-over-budget`
   (`D02:292`, `D03:629`) | dialog: CMP-044 `role="alertdialog"` stacked over SCR-026, title "Open
   Wall with 12 panels?"; body: "Frame time now: 11.8 ms per frame (p95, last 10 s, measured),
   about 60 fps. With Wall's 12 panels: about 17.9 ms (estimated), about 56 fps. Budget: 16 ms (60
   fps). That is over the performance budget, so charts may stutter."; event: Cancel fires
   `layout.import_rejected{reason: budget-exceeded}` and returns to the preview; state: nothing
   created yet — no workspace, layout or pane exists until Import anyway sends the file; caps:
   names 40 · symbols 20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120
   (characters, an ellipsis past the cap, the whole capped value in the accessible name); renders:
   every string from the file as text only — never markup, never a link, never interpreted; footer:
   Cancel (`secondary`) · Import anyway (`primary`); initial focus: Cancel; Esc → Cancel (back to
   the preview); exits T1: Cancel · Esc | confirm | `layout.cost.import.title` ·
   `layout.cost.import.body` · `layout.cost.import.confirm` · `e15.import.cancel` | 05 |
  | `SCR-026/report` | the import succeeded: the new workspace opened in a tab behind the dialog
   (`D02:520`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close
   Import workspace"; region: the dialog's final step, `role="region"` named "Import report", its
   heading `tabindex="-1"` focused on arrival, every line selectable; success: CMP-028 `success`
   "Imported Scalping (2): 7 panels, 2 layouts, 3 items dropped, 1 remapped."; table: CMP-049 table
   mode with §4.3's rows, caption "Report — 7 panels and 2 layouts added · 3 dropped · 1 remapped";
   actions: exactly three words in their own column, each after a decorative CMP-019 glyph — Add
   (`check`), Drop (`x-circle`, PROPOSED), Remap (`merge`, PROPOSED) — never colour alone; copy:
   Copy report (CMP-033) puts the report's lines on the clipboard as plain text and announces
   "Copied"; persists: until Close — never a toast (CMP-045), never `role="status"`; event:
   `layout.imported{panelCount, droppedCount, remappedCount, schemaVersion}`, once the workspace
   exists; live: polite, once — the success line; caps: names 40 · symbols 20 · panel kinds 32 ·
   keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past the cap, the whole
   capped value in the accessible name); renders: every string from the file as text only — never
   markup, never a link, never interpreted; footer: Copy report (`secondary`) · Close (`primary`);
   initial focus: the heading "Import report" (`tabindex="-1"`); Esc → Close; exits T1: Close · Esc
   · × | outcome | `e15.import.report.heading` · `e15.import.report.done` ·
   `e15.import.report.caption` · `e15.import.report.copy` · `e15.import.report.copied` ·
   `e15.import.report.close` | 06, 10 |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report › 4.2 The preview table (fixture `scalping.json`; binding)#1
@ ¶0 ‖ heading ‖ 1
  ### 4.2 The preview table (fixture `scalping.json`; binding)
@ ¶1 ‖ paragraph ‖ 1
  The rows of `SCR-026/preview` in order, as the tool's fixture holds them (CMP-049 table mode;
   every string from the file as text, capped):
@ ¶2 ‖ table ‖ 1
  | Item | Type | Action | Reason |
  | --- | --- | --- | --- |
  | `heatmap_v2` | panel | Drop | not available in this version |
  | `tape_speed_v3` | panel | Drop | not available in this version |
  | Account filter on Positions | setting | Drop | workspaces never carry account bindings |
  | Positions | positions | Remap | shows your own accounts |
  | Layout 1 | layout | Add | — |
  | Order-flow | layout | Add | — |
  | BTCUSDT · 1m · group A | chart | Add | — |
  | BTCUSDT · group A | dom | Add | — |
  | BTCUSDT · group A | tape | Add | — |
  | ETHUSDT · 5m · group B | chart | Add | — |
  | ETHUSDT · 5m · group B | cvd | Add | — |
  | ETHUSDT · 15m · group B | chart | Add | — |
  | 2 symbols: BTCUSDT, ETHUSDT | symbols | Add | — |
  | 12 drawings, with their text labels | drawings | Add | — |
  | 1 chart template | chart template | Add | — |
  | 3 indicator presets | indicator presets | Add | — |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report › 4.3 The report table (binding; §4.2's rows re-rendered)#1
@ ¶0 ‖ heading ‖ 1
  ### 4.3 The report table (binding; §4.2's rows re-rendered)
@ ¶1 ‖ paragraph ‖ 1
  The report repeats §4.2 row for row, the unknown kinds by stored name (AC 3) and the account row
   as dropped (AC 4):
@ ¶2 ‖ table ‖ 1
  | Item | Type | Action | Reason |
  | --- | --- | --- | --- |
  | `heatmap_v2` | panel | Drop | not available in this version |
  | `tape_speed_v3` | panel | Drop | not available in this version |
  | Account filter on Positions | setting | Drop | workspaces never carry account bindings |
  | Positions | positions | Remap | shows your own accounts |
  | Layout 1 | layout | Add | — |
  | Order-flow | layout | Add | — |
  | BTCUSDT · 1m · group A | chart | Add | — |
  | BTCUSDT · group A | dom | Add | — |
  | BTCUSDT · group A | tape | Add | — |
  | ETHUSDT · 5m · group B | chart | Add | — |
  | ETHUSDT · 5m · group B | cvd | Add | — |
  | ETHUSDT · 15m · group B | chart | Add | — |
  | 2 symbols: BTCUSDT, ETHUSDT | symbols | Add | — |
  | 12 drawings, with their text labels | drawings | Add | — |
  | 1 chart template | chart template | Add | — |
  | 3 indicator presets | indicator presets | Add | — |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report › 4.4 The preview: the table, the budget line, the stacked confirm
   and the migration line#1
@ ¶0 ‖ heading ‖ 1
  ### 4.4 The preview: the table, the budget line, the stacked confirm and the migration line
@ ¶1 ‖ paragraph ‖ 1
  **The table (BQ-10 RULED; DL-7, DL-8; `14:636`).** CMP-049 in table mode (`15:524–530`): a
   semantic `<table>` whose `<caption>` comes first, so a screen reader hears the counts before any
   row (the ticket's Accessibility notes), then a header row of four `<th scope="col">`, Item ·
   Type · Action · Reason, then one row per element with its Item as the row header (`<th
   scope="row">`), so every cell is read with its column and its item. It is static: no control in
   a body row, no sort, no select column and no per-row skip (SCR-089's per-row choice,
   `E36D03:153–155`, is not this surface's), so it stays a table and never becomes a grid
   (`15:524–530`). Its one Tab stop is the scroll region around it, named by the caption
   (`15:524–530`): the arrow keys scroll it, and a screen reader's table commands move cell by cell
   with the headers read (AC 6). Every row stays in the page, never windowed, so table navigation
   and the browser's find reach all of them; a file holds at most 32 <!--
   audit:contract.layouts_max=32 --> layouts of 16 <!-- audit:contract.panes_max=16 --> panes each
   (PROPOSED: CMP-049's `virtualized` off here). It is never a canvas and never a picture
   (`14:636`; `D02:516`).
@ ¶2 ‖ paragraph ‖ 1
  **The order (DL-8; the ticket's Technical notes).** Drops and remaps first and additions after,
   so the surprising rows lead: the Drop rows (the unknown kinds, then the dropped settings, each
   in the file's order), then the Remap rows, then the Add rows (the layouts, then the panels in
   their layouts' order, then one summary row each for symbols, drawings, chart templates and
   indicator presets). §4.2 is the fixture's 16 <!-- audit:fixture.rows=16 --> rows in that order,
   which the tool checks row by row.
@ ¶3 ‖ paragraph ‖ 1
  **The caption (DL-19).** It leads with the counts the user is deciding on, "Preview — 7 panels
   and 2 layouts to add · 3 dropped · 1 remapped" (`e15.import.caption`), each count derived by the
   tool from the rows: 7 <!-- audit:fixture.panels=7 --> panels, 2 <!-- audit:fixture.layouts=2 -->
   layouts, 3 <!-- audit:fixture.dropped=3 --> dropped (2 <!-- audit:fixture.unknown_kinds=2 --> of
   them unknown kinds) and 1 <!-- audit:fixture.remapped=1 --> remapped. A remapped panel counts
   among the panels it adds, and a dropped item is never counted as added. The caption is
   `type.ui.label` + `color.text.secondary`, above the header row (`15:524–531`); over the budget
   its last sentence names the layout that opens and its estimate (below).
@ ¶4 ‖ paragraph ‖ 1
  **The Action column (BQ-10 RULED; DoD-4).** Exactly three words, each after a decorative CMP-019
   glyph in its own cell (`aria-hidden`, `15:225`): Add (`check`), Drop (`x-circle`, the PROPOSED
   glyph `15:307` registers) and Remap (`merge`, PROPOSED). The word carries the meaning, the
   glyph's shape repeats it, and colour is a third cue, never the only one. The word is
   `type.ui.body-strong` in `color.text.primary` on every row; only the glyph, at `size.icon` 16
   <!-- audit:redline.size.icon=16 --> px, takes a status colour: Add
   `color.status.success.strong`, Drop `color.status.danger.strong`, Remap
   `color.status.info.strong`, each measured as non-text on both stripes in §8. Remap takes the
   info hue rather than the warning one because in light `color.status.danger.strong` and
   `color.status.warning.strong` resolve to the same amber, so Drop and Remap would share a colour;
   under tritanopia the Add and Remap colours are the nearest of §8's colour-vision pairs, though
   none collapses, and the two words and the two shapes carry them regardless.
@ ¶5 ‖ paragraph ‖ 1
  **The Item, Type and Reason columns.** Item is the element as the file names it, a stored kind
   name such as `heatmap_v2`, a layout's name, a panel's symbol, interval and sync group, or a
   summary such as "2 symbols: BTCUSDT, ETHUSDT", set in `type.num.sm` + `color.text.primary` down
   the whole column, so a value from the file never changes typeface mid-column and always reads as
   data. Type is the app's word for the element (the registry's kind for a known panel; "panel" for
   a kind this build does not know, AC 3; "setting" for a dropped pane setting), in `type.ui.body`
   + `color.text.primary`. Reason is the app's own sentence in `type.ui.body` +
   `color.text.secondary`, and an em dash on an Add row. The unknown kinds keep their stored names
   and the ticket's reason, "not available in this version" (AC 3); `D02:516`'s "not known to this
   version" is a C-row (D09-C6). A pane setting the registry does not list for its kind, a newer
   build's option that is not account-scoped, is a Drop row too, its Item the setting and its pane,
   Type "setting", Reason "not available in this version" (D09-D35). Item takes the width the other
   three columns leave; Type and Action fit their longest word; Reason wraps, and its row grows
   with it.
@ ¶6 ‖ paragraph ‖ 1
  **Account-scoped elements (BQ-3 RULED; AC 4).** An account filter on a pane is dropped and
   listed, never remapped: its row reads Account filter on Positions · setting · Drop · "workspaces
   never carry account bindings" (`D02:516`; `11:2868`), and nothing in the preview, the report,
   the copied text, an announcement or an event names the account it pointed at, or any account the
   importer cannot see. The value of a dropped setting is never shown, only where it was. The one
   Remap is the Positions pane itself, which shows your own accounts once it is imported; its
   Reason names no account at all, because what changes is the pane's scope and not a stored
   binding. The drop is the client's reading of the file; the server drops such a setting again at
   import (`BL:1136`), and until `22` says how (D09-G3), a strict server may refuse the whole file
   instead, which is `SCR-026/refused-server` (§5.1) and never a partial import. `14:632–633`'s
   "remap to the user's default account" gets a PROPOSED A-row (§11).
@ ¶7 ‖ paragraph ‖ 1
  **Strings from the file (Condition 1; DL-17).** Every string the table takes from the file (kind
   names, layout names, symbols, intervals, drawing labels) is a text node and nothing else: never
   markup, never a link, never interpreted (SR-127, `04:967`; C-12.10). Each is capped before it
   reaches the page, at names 40 <!-- audit:contract.name_max=40 -->, symbols 20 <!--
   audit:contract.symbol_max=20 -->, panel kinds 32 <!-- audit:contract.kind_max=32 -->, keys 64
   <!-- audit:design.key_cap=64 -->, file names 40 <!-- audit:design.file_cap=40 --> and drawing
   labels 120 <!-- audit:contract.label_max=120 --> characters (the Fixture paragraph): a longer
   value is cut at its cap and ends in "…", so nothing past a cap is rendered, announced or copied.
   Within its cap, a value wider than its column ends in an ellipsis on screen and keeps the whole
   capped value in the cell's text, for a screen reader and for Copy report. Each value is
   direction-isolated (`<bdi>`), and each control or bidirectional-formatting character in it (the
   set `22:19819–19824` makes the server strip from a name), and each character of the
   `Default_Ignorable_Code_Point` property, which would be invisible (§5.5), shows as a visible "�"
   instead of acting or hiding, so no file string can reorder the row around it or hide part of
   itself (PROPOSED).
@ ¶8 ‖ paragraph ‖ 1
  **Striping, the header and the rows (PROPOSED A-row to CMP-049, §10).** Inside a dialog the
   table sits on `color.surface.overlay`, where CMP-049's panel stripes (odd
   `color.surface.canvas`, `15:524–531`) would read as holes, so the odd rows take
   `color.surface.overlay` and the even rows `color.surface.raised`. The header row is
   `color.surface.hover` with `type.ui.label` + `color.text.primary` and a `border.hairline` 1 <!--
   audit:redline.border.hairline=1 --> px `color.border.subtle` rule under it, sticky at the top of
   the scroll region (`15:524–530`). The rows are the density's `size.row.height` (24 <!--
   audit:redline.size.row.height=24 --> px compact) and grow when a Reason wraps; each cell is
   padded `space.inset.sm` 8 <!-- audit:redline.space.inset.sm=8 --> px. The table's region takes
   the height the blocks above it leave inside CMP-043's cap (`15:466`), so the footer never
   scrolls away, and the focused region carries the dialog's ring inside its edge.
@ ¶9 ‖ paragraph ‖ 1
  **The lines above the table.** In the order a reader meets them: the trust note (§3.2); the zone
   and the file line (§3.3); at most one CMP-028 line, the migration line or the budget line,
   `live="off"` because the end of the check speaks it (§3.4); then the clash line when a workspace
   already has the file's name, "Imported as Scalping (2): a workspace named Scalping exists."
   (`D02:516`; `e15.import.clash`), in `type.ui.body` + `color.text.secondary`, the server's
   disambiguated name as the client predicts it (`BL:1136`); then the table. Each CMP-028 line is
   full width with a `border.thick` 2 <!-- audit:redline.border.thick=2 --> px start edge, padding
   `space.inset.sm` 8 <!-- audit:redline.space.inset.sm=8 --> px and `radius.card` 6 <!--
   audit:redline.radius.card=6 --> px; the migration line's words are `color.text.primary` on
   `color.status.info.subtle`, the budget line's on `color.status.warning.subtle`, and each edge
   and glyph takes its tone's `.strong` (§8).
@ ¶10 ‖ paragraph ‖ 1
  **The panel budget (BQ-6 RULED; DL-9, DL-16; the ticket's Technical notes and Performance
   notes).** The check is per layout, for the layout that opens, which is the file's default layout
   or else its first: one layout is mounted at a time, so a sum over the whole file would warn
   about panels that are never on screen together. Its estimate is E15-K01's per-kind cost model
   over that layout's panels against the frame time measured now (D-15, `D02:133`; `D02:292`), held
   to the 16 <!-- audit:contract.budget_ms=16 --> ms p95 budget (C-14.2). Under the budget nothing
   is shown and Import as new workspace sends at once. Over it, the preview says so twice before
   anything is sent: the caption's last sentence (`e15.import.caption_budget`) and the CMP-028
   `warning` line above the table (`e15.import.budget`). The fixture `wall.json` opens Wall with 12
   <!-- audit:fixture.budget_panels=12 --> panels: 11.8 <!-- audit:fixture.measured_ms=11.8 --> ms
   per frame measured now and about 17.9 <!-- audit:fixture.estimate_ms=17.9 --> ms estimated. A
   file with more panes in one layout than the 16 <!-- audit:contract.panes_max=16 --> a layout
   holds never reaches the budget: it is a schema rejection that names the limit, the panes variant
   of `SCR-026/rejected-malformed` (the ticket's 30-panel fixture; more than 16 cannot occur for a
   stored layout, `D02:292`).
@ ¶11 ‖ paragraph ‖ 1
  **The stacked confirm (`SCR-026/budget-confirm`; BQ-6 RULED; DL-16).** Over the budget, Import
   as new workspace opens US-LAY-001's confirm, the CMP-044 E15-D03 drew for Add panel
   (`D03:629–631`), with the import's verb and never a second warning: a `role="alertdialog"`
   stacked over SCR-026 with its own scrim, at most 560 <!-- audit:contract.dialog_md_px=560 --> px
   wide (`15:466`), titled "Open Wall with 12 panels?" (`layout.cost.import.title`), its body the
   cost sentence with the measured and the estimated frame time and their fps
   (`layout.cost.import.body`, `D03:630`'s sentence with the import's clause), and its footer
   Cancel (`secondary`, focused) · Import anyway (`primary`). The three `layout.cost.import.*`
   strings are PROPOSED, an A-row to E15-D03's deck (D09-A20). Import anyway is a CMP-001 `primary`
   and not `danger`, because nothing is destroyed and the stutter it accepts ends when panels
   close; it takes no activation in CMP-044's first `confirmDelayMs` and no key repeat
   (`15:473–481`). Cancel and `Esc` return to the preview with focus on Import as new workspace and
   fire `layout.import_rejected{reason: budget-exceeded}` once: the ticket's sixth reason counts a
   user who declined the stutter, not a refused file (BQ-6 RULED). A press on the confirm's scrim
   leaves it open, as for any `alertdialog` (`15:463–468`). Import anyway sends the file (§3.5).
@ ¶12 ‖ paragraph ‖ 1
  **The migration line (BQ-4 RULED; `BL:1136`).** A file whose `schema_version` is older than the
   format version this app reads, and which E15-S07's migration can carry forward, is migrated in
   the worker before the preview, and the preview says so above the table: "Migrated from format
   version 1 to 2." (`e15.import.migrated`; CMP-028 `info`). The table then lists what the migrated
   file creates, and the report of a migrated import carries the same line above its table
   (PROPOSED; not drawn). The comparison reads `schema_version` alone, never an app version
   (`22:21408`); the order of versions and the oldest one still read are D09-G2's to fix in `22`. A
   newer file, or an older one past that oldest, is refused (§5).
@ ¶13 ‖ paragraph ‖ 1
  **Per frame: what changes, the components and the focus.**
@ ¶14 ‖ table ‖ 1
  | State | What changes (layout, components and variants, tokens) | Focus order, keys and
   announcements |
  | --- | --- | --- |
  | preview | the zone and the file line stay; the clash line; CMP-049 with §4.2's rows in its
   scroll region; the footer Cancel · Import as new workspace; CMP-043, CMP-002, CMP-028, CMP-067,
   CMP-049, CMP-019 ×3, CMP-001 ×3 | focus stays on Choose file…; `Tab`: Choose file… → the table's
   scroll region → Cancel → Import as new workspace → × → Choose file…; the end of the check speaks
   the caption once, politely |
  | preview-migrated | as the preview, with the migration line above the table and no clash line |
   as the preview; the end of the check speaks the migration line, then the caption |
  | preview-over-budget | as the preview, with the budget line above the table and the budget
   sentence closing the caption; the table is `wall.json`'s | as the preview; the caption, budget
   sentence included, is spoken once; Import as new workspace opens the stacked confirm |
  | budget-confirm | a CMP-044 `standard`, `md`, stacked over SCR-026 with its own scrim; its
   title `type.ui.heading-sm` + `color.text.primary`, its body `type.ui.body` +
   `color.text.secondary`, the numbers in the body's type; the footer as above | opens on Cancel;
   `Tab`: Cancel → Import anyway → Cancel; `Esc` is Cancel; a press on its scrim leaves it open;
   the title and the body are read as it opens (an `alertdialog`, `05:96`); after Cancel, focus is
   back on Import as new workspace |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 4. The
   preview table and the report › 4.5 The report and Copy report#1
@ ¶0 ‖ heading ‖ 1
  ### 4.5 The report and Copy report
@ ¶1 ‖ paragraph ‖ 1
  **The report (BQ-12 RULED; DL-10; AC 3, AC 4).** When the import succeeds, the new workspace
   opens in a tab behind the dialog (`D02:520`) and the dialog's body becomes its last step: a
   `role="region"` named "Import report" by its heading, an `h3` with `tabindex="-1"` that takes
   focus on arrival, a move the user's own Import as new workspace made, announced as focus lands
   (`05:96`). Inside the region, in order: the CMP-028 `success` line "Imported Scalping (2): 7
   panels, 2 layouts, 3 items dropped, 1 remapped." (`e15.import.report.done`, `D02:520`'s line
   with this fixture's counts and the remap count added), spoken once, politely, and naming the
   name the server gave; then the same CMP-049 table re-rendered with what was applied, dropped and
   remapped, row for row as §4.3, its caption "Report — 7 panels and 2 layouts added · 3 dropped ·
   1 remapped" (`e15.import.report.caption`). The rows are the server's answer, the items it says
   it created, dropped and remapped (D09-G1), never the client's preview, whose Drop rows are a
   prediction (§4.4; D09-G3); for the fixture they match §4.2 row for row. The unknown kinds are
   repeated by their stored names (AC 3's second leg); the account filter is listed as dropped; the
   Positions pane is the one Remap; and each says so in plain words that name no account
   ("workspaces never carry account bindings", "shows your own accounts"; AC 4). The trust note and
   the zone are gone from this step, because the file has been used.
@ ¶2 ‖ paragraph ‖ 1
  **It persists (BQ-12 RULED).** The report stays until Close: no timer, never a toast (CMP-045)
   and never `role="status"`; every line, the caption and every cell are selectable text. Close,
   `Esc`, the × and a press on the scrim end it, and focus lands on the new workspace's tab, the
   host's named fallback, since Import… and its menu are gone (`15:463–468`). Once closed, the
   report is gone from the app, and after a closed view it goes when its toast is dismissed (§3.5);
   `layout.imported` is the record that remains, analytics and never audit (`14:638`; `D02:84`).
@ ¶3 ‖ paragraph ‖ 1
  **Copy report (CMP-033; BQ-12 RULED; DL-10).** Copy report is CMP-033's behaviour in a labelled
   footer button, a CMP-001 `secondary` (CMP-033 is an icon button today, `15:361`; its labelled
   form is a PROPOSED A-row, §10). It puts the report on the clipboard as plain text, in the
   region's order: the success line, the caption, then one line per row, the row's number first and
   its four cells after it, joined by " · " ("1 · heatmap_v2 · panel · Drop · not available in this
   version"). No copied line starts with a value from the file, so a spreadsheet the text is pasted
   into never reads one as a formula, and a control character from the file arrives as the "�" the
   table shows, never as a tab or a line break (PROPOSED). The values are the capped ones
   (Condition 1), and nothing else of the file travels. It announces "Copied" once through
   CMP-033's own polite region and never speaks the copied text (`15:361–367`); its `check` glyph
   shows CMP-033's copied state, and focus stays on it. If the browser refuses the clipboard,
   "Couldn't copy the report." is spoken once, politely, and the region stays selectable for a copy
   by hand (PROPOSED copy, `e15.import.report.copy_failed`).
@ ¶4 ‖ paragraph ‖ 1
  **The event (DL-20).** `layout.imported{panelCount, droppedCount, remappedCount, schemaVersion}`
   fires once, when the server has created the workspace, and never on the press (`14:638`): 7 <!--
   audit:fixture.panels=7 -->, 3 <!-- audit:fixture.dropped=3 --> and 1 <!--
   audit:fixture.remapped=1 --> for the fixture, with `schemaVersion` the file's own
   `schema_version`, as read before any migration, so a migrated import stays visible. E15-S07's
   `{panes, dropped, migratedFrom}` names the same facts; the alias table is D09-G13 (§12).
@ ¶5 ‖ table ‖ 1
  | Part | Component and variant | Layout and redlines | Tokens |
  | --- | --- | --- | --- |
  | Region | `<section role="region">`, `aria-labelledby` its heading | the whole body: the
   heading, the success line `space.stack.md` 12 <!-- audit:redline.space.stack.md=12 --> px under
   it, the table under that | — |
  | Heading | an `h3`, "Import report", `tabindex="-1"` | one line; the dialog's focus ring when
   it holds focus | `type.ui.body-strong` + `color.text.primary` |
  | Success line | CMP-028 `success`, `live="polite"` | full width; a `border.thick` 2 <!--
   audit:redline.border.thick=2 --> px start edge; padding `space.inset.sm` 8 <!--
   audit:redline.space.inset.sm=8 --> px; `radius.card` 6 <!-- audit:redline.radius.card=6 --> px |
   fill `color.status.success.subtle`; edge and glyph `color.status.success.strong`; words
   `type.ui.body` + `color.text.primary` |
  | Table | CMP-049 table mode, as the preview's (§4.4) | the height the heading and the line
   leave; its own scroll region, named by its caption | as §4.4 |
  | Footer | Copy report (CMP-001 `secondary`, CMP-033's behaviour) · Close (CMP-001 `primary`) |
   as §3.2's footer | as §3.2's footer |
@ ¶6 ‖ paragraph ‖ 1
  **Per frame (`SCR-026/report`).** What changes: the body is the region above, the trust note and
   the zone gone; CMP-043, CMP-002, CMP-028, CMP-049, CMP-019 ×3, CMP-001 ×2 with CMP-033's
   behaviour on Copy report. Focus, keys and announcements: focus on the heading; `Tab`: the
   table's scroll region → Copy report → Close → × → the scroll region; `Enter` or `Space` on Copy
   report copies; Close, `Esc`, the × and the scrim close the dialog and focus lands on the new
   workspace's tab; the success line is spoken once, politely, and "Copied" once per copy.
@ ¶7 ‖ paragraph ‖ 1
  **Copy this section adds (PROPOSED).** Four strings that no frame row keys, each one sentence or
   one verb, are rows of the deck (§9): `e15.import.slow`, `e15.import.report.view`,
   `e15.import.review` and `e15.import.report.copy_failed`.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals#1
@ ¶0 ‖ heading ‖ 1
  ## 5. Rejections and refusals
@ ¶1 ‖ paragraph ‖ 1
  **Every rejection and every refusal here is an outcome — never a lock, never a partial import**
   (BQ-4, BQ-5, BQ-11 RULED; Conditions 1 and 2; A1). Six frames refuse a file before anything is
   sent: the newer and the older format version, the malformed file, the oversized file, the wrong
   type and the parse limits. Three end at the send: the workspace limit, the server's own
   re-check, and a send whose answer never came (§1.3, states 15–21, 23, 24 and 27). Each is one
   CMP-027 `inline` message with `live="polite"` in the import dialog's body, above the still-live
   Choose file…, so the dialog stays open and another file is chosen without starting over (AC 5;
   `D02:517`; `D02:518`); at the limit and after an unanswered send the zone and Choose file… leave
   the body, because another file would meet the same limit or the same file could import twice.
   The footer carries Cancel and Choose another file, the primary, focused on arrival; the limit's
   frame carries Cancel alone and the unanswered send's Close alone. No Import verb is drawn on any
   of them; it is omitted, never T2-locked (AC 2; `11:2871`; §6). Each but the unanswered send says
   "Nothing was imported." and it is true: no workspace, layout or pane exists, and nothing of the
   file is kept (§5.5); the unanswered send says instead that the import could not be confirmed,
   because it may have happened.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals › 5.1 Frames (binding; the tool gates every row)#1
@ ¶0 ‖ heading ‖ 1
  ### 5.1 Frames (binding; the tool gates every row)
@ ¶1 ‖ table ‖ 1
  | Frame | Producer | Shows | Class | Copy keys | Board |
  | --- | --- | --- | --- | --- | --- |
  | `SCR-026/rejected-version-newer` | a file whose `schema_version` is newer than this app reads
   (`D02:517`, `11:2871`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close ×
   "Close Import workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop —
   "A workspace file never carries credentials or account bindings. Importing creates a new
   workspace and changes nothing else."; component: CMP-027 `inline`, `live="polite"`, above the
   still-live Choose file…; message: "This file was exported by format version 2 and can't be
   imported into format version 1. Nothing was imported. Export it again from a version 1 app, or
   update this app."; state: nothing imported — no workspace, layout or pane was created and your
   workspaces are unchanged; import verb: none — omitted, never T2-locked (AC 2); event:
   `layout.import_rejected{reason: version-newer}`, once; live: polite, once; compares: the file's
   `schema_version` (2) with the format version this app reads (1) — never an app version; shape:
   not checked — a format version this app does not read skips the shape rules, so the outcome is
   the version refusal and never a shape failure (§3.4, step 3); footer: Cancel (`secondary`) ·
   Choose another file (`primary`); initial focus: Choose another file; Esc → Cancel; exits T1:
   Cancel · Esc · × · Choose another file; anatomy: top to bottom the title row, the trust note,
   the CMP-027 message, Choose file… with its drop words and its help line, then the footer (§5.2);
   tokens: the CMP-019 `danger` glyph at `size.icon` in `color.status.danger.strong` (`x-circle`
   once registered, `15:307`) and the words in `type.ui.body` + `color.text.primary`, on the card's
   `color.surface.overlay` with no fill; one set of names for dark, light and high contrast (§8
   rows 1 and 7); redlines: `space.stack.md` (12 <!-- audit:redline.space.stack.md=12 --> px) above
   and below the message, the glyph 16 <!-- audit:redline.size.icon=16 --> px with `space.inset.xs`
   to the words; the footer's buttons `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 -->
   px) apart, 32 <!-- audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24
   <!-- audit:redline.size.control.compact=24 --> px at compact; versions: the two numbers are
   whole numbers parsed from the file and read from the app, in `type.num.sm`, never the file's raw
   text (§5.3); keys: `Enter` on Choose another file opens the OS picker, and a new file starts the
   checks again from size; the message is spoken once by its polite region and is not the button's
   description, so it is never read twice | outcome (rejection) |
   `e15.import.rejected.version_newer` · `e15.import.choose_another` · `e15.import.cancel` | 04, 09
   |
  | `SCR-026/rejected-version-older` | a file below the oldest format version this app reads
   (BQ-4) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; component: CMP-027 `inline`, `live="polite"`, above the still-live
   Choose file…; message: "This file was exported by format version 0 and this app reads format
   version 1 or later. Nothing was imported. Update the app that exported it, then export it
   again."; state: nothing imported — no workspace, layout or pane was created and your workspaces
   are unchanged; import verb: none — omitted, never T2-locked (AC 2); event:
   `layout.import_rejected{reason: version-older}`, once; live: polite, once; compares: the file's
   `schema_version` (0) with the oldest format version this app reads (1) — never an app version;
   shape: not checked — a format version this app does not read skips the shape rules, so the
   outcome is the version refusal and never a shape failure (§3.4, step 3); footer: Cancel
   (`secondary`) · Choose another file (`primary`); initial focus: Choose another file; Esc →
   Cancel; exits T1: Cancel · Esc · × · Choose another file; anatomy: top to bottom the title row,
   the trust note, the CMP-027 message, Choose file… with its drop words and its help line, then
   the footer (§5.2); tokens: the CMP-019 `danger` glyph at `size.icon` in
   `color.status.danger.strong` (`x-circle` once registered, `15:307`) and the words in
   `type.ui.body` + `color.text.primary`, on the card's `color.surface.overlay` with no fill; one
   set of names for dark, light and high contrast (§8 rows 1 and 7); redlines: `space.stack.md` (12
   <!-- audit:redline.space.stack.md=12 --> px) above and below the message, the glyph 16 <!--
   audit:redline.size.icon=16 --> px with `space.inset.xs` to the words; the footer's buttons
   `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 --> px) apart, 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; versions: as the newer refusal's, its
   way on pointing at the app that exported the file (§5.3); keys: `Enter` on Choose another file
   opens the OS picker, and a new file starts the checks again from size; the message is spoken
   once by its polite region and is not the button's description, so it is never read twice |
   outcome (rejection) | `e15.import.rejected.version_older` · `e15.import.choose_another` ·
   `e15.import.cancel` | 04 |
  | `SCR-026/rejected-malformed` | a file missing a required key (`D02:518`); its variants: a
   parse error, a layout over the pane limit, too many layouts, too many indicator presets |
   dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; component: CMP-027 `inline`, `live="polite"`, above the still-live
   Choose file…; message: "This isn't a workspace file: `layouts[1].grid_spec.root` is missing.
   Nothing was imported."; variants: "This isn't a workspace file: it stops being valid JSON at
   line 212. Nothing was imported." · "This file has a layout with 30 panels; a layout holds at
   most 16. Nothing was imported." · "This file has 40 layouts; a workspace holds at most 32.
   Nothing was imported." · "This file has 240 indicator presets; a file may carry at most 200.
   Nothing was imported." · "This isn't a workspace file: `layouts[0].crosshair_sync` isn't valid.
   Nothing was imported."; state: nothing imported — no workspace, layout or pane was created and
   your workspaces are unchanged; import verb: none — omitted, never T2-locked (AC 2); event:
   `layout.import_rejected{reason: malformed}`, once; live: polite, once; caps: names 40 · symbols
   20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past
   the cap, the whole capped value in the accessible name); renders: every string from the file as
   text only — never markup, never a link, never interpreted; footer: Cancel (`secondary`) · Choose
   another file (`primary`); initial focus: Choose another file; Esc → Cancel; exits T1: Cancel ·
   Esc · × · Choose another file; anatomy: top to bottom the title row, the trust note, the CMP-027
   message, Choose file… with its drop words and its help line, then the footer (§5.2); tokens: the
   CMP-019 `danger` glyph at `size.icon` in `color.status.danger.strong` (`x-circle` once
   registered, `15:307`) and the words in `type.ui.body` + `color.text.primary`, on the card's
   `color.surface.overlay` with no fill; one set of names for dark, light and high contrast (§8
   rows 1 and 7); redlines: `space.stack.md` (12 <!-- audit:redline.space.stack.md=12 --> px) above
   and below the message, the glyph 16 <!-- audit:redline.size.icon=16 --> px with `space.inset.xs`
   to the words; the footer's buttons `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 -->
   px) apart, 32 <!-- audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24
   <!-- audit:redline.size.control.compact=24 --> px at compact; key: the offending key in
   `type.num.sm` (mono), a text node of its own, at most 64 <!-- audit:design.key_cap=64 -->
   characters with an ellipsis past them; one key, the first the check names (`14:636`); counts:
   the line, the panel, layout and preset counts are the parser's and the counter's numbers, never
   text copied from the file (§5.4); keys: `Enter` on Choose another file opens the OS picker, and
   a new file starts the checks again from size; the message is spoken once by its polite region
   and is not the button's description, so it is never read twice | outcome (rejection) |
   `e15.import.rejected.malformed` · `e15.import.rejected.parse` · `e15.import.rejected.panes` ·
   `e15.import.rejected.layouts` · `e15.import.rejected.presets` · `e15.import.rejected.invalid` ·
   `e15.import.choose_another` · `e15.import.cancel` | 04 |
  | `SCR-026/rejected-oversized` | a file over the size cap (`D02:518`, `BL:1136`) | dialog:
   CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import workspace"; trust:
   CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace file never carries
   credentials or account bindings. Importing creates a new workspace and changes nothing else.";
   component: CMP-027 `inline`, `live="polite"`, above the still-live Choose file…; message: "This
   file is 3.4 MB; the limit is 2 MB. Nothing was imported."; state: nothing imported — no
   workspace, layout or pane was created and your workspaces are unchanged; import verb: none —
   omitted, never T2-locked (AC 2); event: `layout.import_rejected{reason: oversized}`, once; live:
   polite, once; footer: Cancel (`secondary`) · Choose another file (`primary`); initial focus:
   Choose another file; Esc → Cancel; exits T1: Cancel · Esc · × · Choose another file; anatomy:
   top to bottom the title row, the trust note, the CMP-027 message, Choose file… with its drop
   words and its help line, then the footer (§5.2); tokens: the CMP-019 `danger` glyph at
   `size.icon` in `color.status.danger.strong` (`x-circle` once registered, `15:307`) and the words
   in `type.ui.body` + `color.text.primary`, on the card's `color.surface.overlay` with no fill;
   one set of names for dark, light and high contrast (§8 rows 1 and 7); redlines: `space.stack.md`
   (12 <!-- audit:redline.space.stack.md=12 --> px) above and below the message, the glyph 16 <!--
   audit:redline.size.icon=16 --> px with `space.inset.xs` to the words; the footer's buttons
   `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 --> px) apart, 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; size: read from the chosen file's size
   before a byte of it is read, in MB to one decimal rounded up, so a file just over the limit
   never reads as the limit; the file is never opened or parsed (§5.4); keys: `Enter` on Choose
   another file opens the OS picker, and a new file starts the checks again from size; the message
   is spoken once by its polite region and is not the button's description, so it is never read
   twice | outcome (rejection) | `e15.import.rejected.oversized` · `e15.import.choose_another` ·
   `e15.import.cancel` | 04 |
  | `SCR-026/rejected-wrong-type` | `report.csv` dropped: the picker filters by type, a drop does
   not | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close × "Close Import
   workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop — "A workspace
   file never carries credentials or account bindings. Importing creates a new workspace and
   changes nothing else."; component: CMP-027 `inline`, `live="polite"`, above the still-live
   Choose file…; message: "That isn't a JSON file (report.csv). Nothing was imported. Choose a
   .json workspace file."; state: nothing imported — no workspace, layout or pane was created and
   your workspaces are unchanged; import verb: none — omitted, never T2-locked (AC 2); event:
   `layout.import_rejected{reason: wrong-type}`, once; live: polite, once; caps: names 40 · symbols
   20 · panel kinds 32 · keys 64 · file names 40 · drawing labels 120 (characters, an ellipsis past
   the cap, the whole capped value in the accessible name); renders: every string from the file as
   text only — never markup, never a link, never interpreted; footer: Cancel (`secondary`) · Choose
   another file (`primary`); initial focus: Choose another file; Esc → Cancel; exits T1: Cancel ·
   Esc · × · Choose another file; anatomy: top to bottom the title row, the trust note, the CMP-027
   message, Choose file… with its drop words and its help line, then the footer (§5.2); tokens: the
   CMP-019 `danger` glyph at `size.icon` in `color.status.danger.strong` (`x-circle` once
   registered, `15:307`) and the words in `type.ui.body` + `color.text.primary`, on the card's
   `color.surface.overlay` with no fill; one set of names for dark, light and high contrast (§8
   rows 1 and 7); redlines: `space.stack.md` (12 <!-- audit:redline.space.stack.md=12 --> px) above
   and below the message, the glyph 16 <!-- audit:redline.size.icon=16 --> px with `space.inset.xs`
   to the words; the footer's buttons `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 -->
   px) apart, 32 <!-- audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24
   <!-- audit:redline.size.control.compact=24 --> px at compact; type: a picked file is filtered by
   `accept`; a dropped one is refused only when its name, read after §5.5's cleaning, does not end
   in `.json` and its media type is not `application/json`, before a byte is read, so a blank type
   never refuses a `.json` name; the name in `type.num.sm`, at most 40 <!--
   audit:design.file_cap=40 --> characters with an ellipsis past them; keys: `Enter` on Choose
   another file opens the OS picker, and a new file starts the checks again from size; the message
   is spoken once by its polite region and is not the button's description, so it is never read
   twice | outcome (rejection) | `e15.import.rejected.wrong_type` · `e15.import.choose_another` ·
   `e15.import.cancel` | 04 |
  | `SCR-026/rejected-nodes` | a file nested deeper than the depth limit (`22:19819`); over the
   node count is its variant (`BL:1136`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import
   workspace", close × "Close Import workspace"; trust: CMP-028 `info` `role="note"` under the
   title, not a Tab stop — "A workspace file never carries credentials or account bindings.
   Importing creates a new workspace and changes nothing else."; component: CMP-027 `inline`,
   `live="polite"`, above the still-live Choose file…; message: "This file is nested too deeply:
   the limit is 16 levels. Nothing was imported."; variants: "This file has more than 10,000
   values: the limit is 10,000. Nothing was imported."; state: nothing imported — no workspace,
   layout or pane was created and your workspaces are unchanged; import verb: none — omitted, never
   T2-locked (AC 2); event: `layout.import_rejected{reason: malformed}`, once; live: polite, once;
   footer: Cancel (`secondary`) · Choose another file (`primary`); initial focus: Choose another
   file; Esc → Cancel; exits T1: Cancel · Esc · × · Choose another file; anatomy: top to bottom the
   title row, the trust note, the CMP-027 message, Choose file… with its drop words and its help
   line, then the footer (§5.2); tokens: the CMP-019 `danger` glyph at `size.icon` in
   `color.status.danger.strong` (`x-circle` once registered, `15:307`) and the words in
   `type.ui.body` + `color.text.primary`, on the card's `color.surface.overlay` with no fill; one
   set of names for dark, light and high contrast (§8 rows 1 and 7); redlines: `space.stack.md` (12
   <!-- audit:redline.space.stack.md=12 --> px) above and below the message, the glyph 16 <!--
   audit:redline.size.icon=16 --> px with `space.inset.xs` to the words; the footer's buttons
   `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 --> px) apart, 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; scan: the worker counts the nesting and
   the values as it reads and stops at the first limit crossed, before any document is built, so a
   hostile file costs the worker, never the dialog (§5.4); keys: `Enter` on Choose another file
   opens the OS picker, and a new file starts the checks again from size; the message is spoken
   once by its polite region and is not the button's description, so it is never read twice |
   outcome (rejection) | `e15.import.rejected.depth` · `e15.import.rejected.nodes` ·
   `e15.import.choose_another` · `e15.import.cancel` | not drawn — the text is binding; drawn on
   request |
  | `SCR-026/refused-limit` | another window reached the workspace limit first: the send answered
   `409 limit_reached` (`FL:164`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace",
   close × "Close Import workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab
   stop — "A workspace file never carries credentials or account bindings. Importing creates a new
   workspace and changes nothing else."; component: CMP-027 `inline`, `live="polite"`, in the
   dialog body, the zone and Choose file… gone (§5.5); message: "Nothing was imported." · "You have
   32 workspaces, the most you can have. Delete one, then import again."; state: nothing imported —
   no workspace, layout or pane was created and your workspaces are unchanged; import verb: none —
   omitted, never T2-locked (AC 2); live: polite, once; footer: Cancel (`secondary`); initial
   focus: Cancel; Esc → Cancel; exits T1: Cancel · Esc · ×; anatomy: the title row, the trust note,
   the message in two sentences and a footer of Cancel alone; the zone, Choose file… and its help
   line leave the body, an absence and never a lock (§5.5); tokens: the CMP-019 `danger` glyph at
   `size.icon` in `color.status.danger.strong` (`x-circle` once registered, `15:307`) and the words
   in `type.ui.body` + `color.text.primary`, on the card's `color.surface.overlay` with no fill;
   one set of names for dark, light and high contrast (§8 rows 1 and 7); redlines: `space.stack.md`
   (12 <!-- audit:redline.space.stack.md=12 --> px) above and below the message, the glyph 16 <!--
   audit:redline.size.icon=16 --> px with `space.inset.xs` to the words; Cancel 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; race: another window created a
   workspace between the preview and the send; the import verb leaves the footer and focus moves to
   Cancel, the named fallback (`15:468`) | T4 (refusal) | `e15.import.nothing` ·
   `e15.import.refused.limit` · `e15.import.cancel` | 05 |
  | `SCR-026/refused-server` | the server's own re-check refused the file at the send (`422
   validation_failed`) | dialog: CMP-043 `size="lg"` `role="dialog"` "Import workspace", close ×
   "Close Import workspace"; trust: CMP-028 `info` `role="note"` under the title, not a Tab stop —
   "A workspace file never carries credentials or account bindings. Importing creates a new
   workspace and changes nothing else."; component: CMP-027 `inline`, `live="polite"`, above the
   still-live Choose file…; message: "Nothing was imported." · "The server didn't accept this file:
   `layouts[0].panes[3].pane_config` isn't valid."; variants: "The workspace store didn't answer.
   Choose the file again in a moment." · "The server didn't accept this file: it is larger than the
   server takes."; state: nothing imported — no workspace, layout or pane was created and your
   workspaces are unchanged; import verb: none — omitted, never T2-locked (AC 2); live: polite,
   once; caps: names 40 · symbols 20 · panel kinds 32 · keys 64 · file names 40 · drawing labels
   120 (characters, an ellipsis past the cap, the whole capped value in the accessible name);
   renders: every string from the file as text only — never markup, never a link, never
   interpreted; footer: Cancel (`secondary`) · Choose another file (`primary`); initial focus:
   Choose another file; Esc → Cancel; exits T1: Cancel · Esc · × · Choose another file; anatomy:
   top to bottom the title row, the trust note, the CMP-027 message, Choose file… with its drop
   words and its help line, then the footer (§5.2); tokens: the CMP-019 `danger` glyph at
   `size.icon` in `color.status.danger.strong` (`x-circle` once registered, `15:307`) and the words
   in `type.ui.body` + `color.text.primary`, on the card's `color.surface.overlay` with no fill;
   one set of names for dark, light and high contrast (§8 rows 1 and 7); redlines: `space.stack.md`
   (12 <!-- audit:redline.space.stack.md=12 --> px) above and below the message, the glyph 16 <!--
   audit:redline.size.icon=16 --> px with `space.inset.xs` to the words; the footer's buttons
   `space.inset.sm` (8 <!-- audit:redline.space.inset.sm=8 --> px) apart, 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall at comfortable and 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; key: the first field path of the
   server's `errors[]`, in `type.num.sm` (mono), at most 64 <!-- audit:design.key_cap=64 -->
   characters with an ellipsis past them; the server's own words are never shown (`15:306`); keys:
   `Enter` on Choose another file opens the OS picker, and a new file starts the checks again from
   size; the message is spoken once by its polite region and is not the button's description, so it
   is never read twice | T4 (refusal) | `e15.import.nothing` · `e15.import.refused.server` ·
   `e15.import.refused.store` · `e15.import.refused.size` · `e15.import.choose_another` ·
   `e15.import.cancel` | not drawn — the text is binding; drawn on request |
  | `SCR-026/refused-unconfirmed` | the send's answer never came: a timeout or a dropped
   connection after the file was sent (D09-G1) | dialog: CMP-043 `size="lg"` `role="dialog"`
   "Import workspace", close × "Close Import workspace"; trust: CMP-028 `info` `role="note"` under
   the title, not a Tab stop — "A workspace file never carries credentials or account bindings.
   Importing creates a new workspace and changes nothing else."; component: CMP-027 `inline`,
   `live="polite"`, in the dialog body, the zone and Choose file… gone (§5.5); message: "We
   couldn't confirm the import. Check your workspaces before importing again."; state: unknown —
   the answer never came, so the new workspace may or may not exist, and nothing is sent again by
   itself; import verb: none — omitted, so the file is never sent twice (D09-G1); live: polite,
   once; footer: Close (`primary`); initial focus: Close; Esc → Close; exits T1: Close · Esc · ×;
   anatomy: the title row, the trust note, the message and a footer of Close alone; the zone,
   Choose file… and its help line leave the body, an absence and never a lock (§5.5); tokens: the
   CMP-019 `danger` glyph at `size.icon` in `color.status.danger.strong` (`x-circle` once
   registered, `15:307`) and the words in `type.ui.body` + `color.text.primary`, on the card's
   `color.surface.overlay` with no fill; one set of names for dark, light and high contrast (§8
   rows 1 and 7); redlines: `space.stack.md` (12 <!-- audit:redline.space.stack.md=12 --> px) above
   and below the message, the glyph 16 <!-- audit:redline.size.icon=16 --> px with `space.inset.xs`
   to the words; Close 32 <!-- audit:redline.size.control.comfortable=32 --> px tall at comfortable
   and 24 <!-- audit:redline.size.control.compact=24 --> px at compact; way on: Close ends the
   dialog and focus lands on the button of the menu Import… came from, so the rail shows whether
   the workspace was made | outcome | `e15.import.refused.unconfirmed` · `e15.import.close_view` |
   not drawn — the text is binding; drawn on request |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals › 5.2 The rejection frames' anatomy#1
@ ¶0 ‖ heading ‖ 1
  ### 5.2 The rejection frames' anatomy
@ ¶1 ‖ paragraph ‖ 1
  One anatomy serves the six rejections and the three outcomes at the send; only the message, its
   variants, the footer and, at the limit and after an unanswered send, the zone change (§5.1). Top
   to bottom inside the CMP-043 `size="lg"` card, at most 960 <!-- audit:contract.dialog_lg_px=960
   --> px wide (`15:466`): the title row, "Import workspace" (`h2`) with the close × "Close Import
   workspace"; the trust note, CMP-028 `info` `role="note"`, unchanged from `SCR-026/pick`; the
   message; Choose file… with its words "or drop a workspace file here" and its help "JSON, up to 2
   MB", still live, so a pick or a drop starts the five checks again from size (§5.4), except at
   the limit and after an unanswered send, where the zone and Choose file… leave the body (§5.5);
   the footer. Nothing else is drawn: no table, no progress, no list of what would have been added.
   Choose another file and Choose file… front the same native input: the footer's button is the
   constructive primary that focus lands on, so `Enter` reopens the picker at once, and the body's
   button keeps its drop words for a pointer. The message is CandleViewer's own words with at most
   one string from outside the app in it (§5.5), never a parser's or a server's text (`15:306`).
@ ¶2 ‖ table ‖ 1
  | Part | Component and variant | Tokens (one set of names; dark, light and high contrast resolve
   them, §8) | Redlines (comfortable; compact changes only the control heights) |
  | --- | --- | --- | --- |
  | The message | CMP-027 `inline`, severity `error`, `live="polite"` overriding the
   `role="alert"` default (`15:306`; slice 4's H37, `S4:919`) | the glyph CMP-019 `danger` at
   `size.icon` in `color.status.danger.strong`, `x-circle` once E05-T06 registers it (`15:307`);
   the words `type.ui.body` + `color.text.primary` on the card's `color.surface.overlay`, no fill
   (§8 rows 1 and 7) | the glyph 16 <!-- audit:redline.size.icon=16 --> px, `space.inset.xs` to the
   words; `space.stack.md`, 12 <!-- audit:redline.space.stack.md=12 --> px, above and below the
   message; the words wrap, never truncate |
  | A key or a file name inside the message | a text node of its own, never a link (§5.5) |
   `type.num.sm` (mono) + `color.text.primary` | inline in the sentence; a key at most 64 <!--
   audit:design.key_cap=64 --> characters, a file name at most 40 <!-- audit:design.file_cap=40 -->
   characters, an ellipsis past either |
  | The version numbers | whole numbers, parsed and read (§5.3) | `type.num.sm` +
   `color.text.primary` | inline in the sentence |
  | Choose file… and its words | CMP-067 behind a CMP-001 `secondary` button (§3) | as
   `SCR-026/pick` | as `SCR-026/pick` |
  | The footer | CMP-001 `secondary` Cancel, then CMP-001 `primary` Choose another file; on
   `SCR-026/refused-limit` Cancel alone; on `SCR-026/refused-unconfirmed` Close alone, a CMP-001
   `primary` | `color.action.secondary.default` + `color.text.primary`;
   `color.action.primary.default` + `color.text.on-action` (§8 rows 18 and 19) | 32 <!--
   audit:redline.size.control.comfortable=32 --> px tall, 24 <!--
   audit:redline.size.control.compact=24 --> px at compact; `space.inset.sm`, 8 <!--
   audit:redline.space.inset.sm=8 --> px, apart; `space.dialog.padding`, 24 <!--
   audit:redline.space.dialog.padding=24 --> px, inside the card |
  | Focus on arrival | CMP-039's ring on Choose another file, on Cancel at the limit, or on Close
   after an unanswered send | `color.focus.ring` at `border.focus`, 2 <!--
   audit:redline.border.focus=2 --> px (§8 row 20) | outside the control, never clipped by the
   footer |
@ ¶3 ‖ paragraph ‖ 1
  **What changes per frame.** The words are §9's; the event fires once per rejection, its reason
   the ticket's word (BQ-11 RULED; the alias table to E15-S07's `size | parse | schema | version |
   semantic` is D09-G13).
@ ¶4 ‖ table ‖ 1
  | Case | Frame | Check (§5.4) | The problem and the limit it names | The way on |
   `layout.import_rejected{reason}` |
  | --- | --- | --- | --- | --- | --- |
  | a newer format version | `SCR-026/rejected-version-newer` | 4 version | both format versions,
   the file's 2 <!-- audit:fixture.newer_format=2 --> and this app's 1 <!--
   audit:fixture.app_format=1 --> | "Export it again from a version 1 app, or update this app.";
   Choose another file | `version-newer` |
  | an older format version, unsupported | `SCR-026/rejected-version-older` | 4 version | both,
   the file's 0 <!-- audit:fixture.older_format=0 --> and the oldest this app reads | "Update the
   app that exported it, then export it again."; Choose another file | `version-older` |
  | a required key missing | `SCR-026/rejected-malformed` | 3 schema | the key, in mono | Choose
   another file | `malformed` |
  | not JSON at all | its variant | 2 parse | the line where the text stops being JSON | Choose
   another file | `malformed` |
  | a layout over the panel limit | its variant | 3 schema | the count and the limit, at most 16
   <!-- audit:contract.panes_max=16 --> panels a layout | Choose another file | `malformed` |
  | too many layouts | its variant | 3 schema | the count and the limit, at most 32 <!--
   audit:contract.layouts_max=32 --> layouts a workspace | Choose another file | `malformed` |
  | too many indicator presets | its variant | 3 schema | the count and the limit, at most 200
   <!-- audit:contract.presets_max=200 --> indicator presets a file | Choose another file |
   `malformed` |
  | a file over the size limit | `SCR-026/rejected-oversized` | 1 size | the file's size and the
   limit, at most 2 <!-- audit:contract.size_mb=2 --> MB | Choose another file | `oversized` |
  | not a JSON file | `SCR-026/rejected-wrong-type` | 1 size, its type first | the file's name |
   "Choose a .json workspace file."; Choose another file | `wrong-type` |
  | nested too deeply | `SCR-026/rejected-nodes` | 2 parse | the limit, at most 16 <!--
   audit:contract.depth=16 --> levels | Choose another file | `malformed` (BQ-5 RULED) |
  | too many values | its variant | 2 parse | the limit, at most 10,000 <!--
   audit:contract.nodes=10000 --> values, PROPOSED (D09-G5) | Choose another file | `malformed` |
  | the workspace limit, met at the send | `SCR-026/refused-limit` | the send | the limit, 32 <!--
   audit:contract.workspaces_max=32 --> workspaces | "Delete one, then import again."; Cancel |
   none (§5.5) |
  | the server's re-check, at the send | `SCR-026/refused-server` | the send | the first key the
   server named, in mono | Choose another file | none (§5.5) |
  | a file larger than the server takes, `413` | its variant | the send | that the server takes no
   file this large; the number is the server's (D09-G5) | Choose another file | none (§5.5) |
  | the send's answer never came | `SCR-026/refused-unconfirmed` | the send | that the import
   could not be confirmed | "Check your workspaces before importing again."; Close | none (§5.5) |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals › 5.3 The version rule (BQ-4 RULED, owner approval pending (#2701))#1
@ ¶0 ‖ heading ‖ 1
  ### 5.3 The version rule (BQ-4 RULED, owner approval pending (#2701))
@ ¶1 ‖ paragraph ‖ 1
  The file's `schema_version` is compared with the format versions this app reads, and nothing
   else is: never an app version, never the build or the date that exported the file (`22:21408`;
   E15-S07, `BL:1136`). The contract types it as a string with no order (`22:21408`), so this spec
   reads it as a whole number written in decimal and compares it as a number, PROPOSED — D09-G2
   asks `22`'s owner for the format, the order and the oldest version still read (the floor). Today
   the app reads format version 1 <!-- audit:fixture.app_format=1 -->, which is both its newest and
   its floor; the newer fixture is format version 2 <!-- audit:fixture.newer_format=2 --> and the
   older one format version 0 <!-- audit:fixture.older_format=0 -->. The migrated row below is a
   later build's, one that reads format version 2 and still reads 1.
@ ¶2 ‖ table ‖ 1
  | The file's `schema_version` | Outcome | Frame | Words (§9) | Event |
  | --- | --- | --- | --- | --- |
  | above the newest this app reads (the fixture: 2 <!-- audit:fixture.newer_format=2 --> against
   1 <!-- audit:fixture.app_format=1 -->) | refused whole, both versions named, then the way on:
   export it again from an app that writes the older format, or update this app (AC 2; `11:2871`;
   `D02:517`) | `SCR-026/rejected-version-newer` | `e15.import.rejected.version_newer` |
   `version-newer` |
  | the newest this app reads | the checks go on to the registry, then the preview |
   `SCR-026/preview` | — | — |
  | older, still read (a later build, the file one format behind it) | migrated forward before the
   preview, which shows the migrated document, and said so above the table: "Migrated from format
   version 1 to 2." (E15-S07's rule, `BL:1136`) | `SCR-026/preview-migrated` |
   `e15.import.migrated` | none at the preview; on success `layout.imported` carries the file's own
   `schemaVersion` |
  | below the floor (the fixture: 0 <!-- audit:fixture.older_format=0 --> against 1 <!--
   audit:fixture.app_format=1 -->) | refused whole, both versions named, then the way on: update
   the app that exported it, then export it again (the ticket's `version-older`) |
   `SCR-026/rejected-version-older` | `e15.import.rejected.version_older` | `version-older` |
  | absent, empty, or not a whole number | a schema failure, the key `schema_version` named in
   mono: "is missing" when it is absent, "isn't valid" otherwise (§5.4) |
   `SCR-026/rejected-malformed` | `e15.import.rejected.malformed` · `e15.import.rejected.invalid` |
   `malformed` |
@ ¶3 ‖ paragraph ‖ 1
  The version is read from the file's envelope before any shape rule, so a newer or an older file
   meets its version refusal and never a shape failure: a reader of one format cannot read
   another's shape, and the shape rules wait for a version this app reads (§3.4, step 3; D09-Q5).
   Both refusals name both numbers in the words the user reads — "format version 2", "format
   version 1" — never "v2", a build number or an app's name; the newer refusal's last sentence is
   the constructive route the ticket asks for, export again from the older version or update this
   app (`BL:266`), and the older refusal's points the other way, at the app that wrote the file. No
   variant offers to bring in part of the file, to skip what this build cannot read or to go on
   regardless: the verb is absent (AC 2). The numbers printed are the parsed whole numbers and the
   app's own constant, so the file's raw `schema_version` text never reaches the screen (§5.5).
   E15-D02's refusal said "version 2" and "version 1" (`D02:517`); "format version" names what is
   compared, and the ticket's "This layout was exported by v2 and can't be imported into v1."
   (`14:633`) is replaced by the ruled words (BQ-4 RULED; `14:633`'s A-row, §11).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals › 5.4 The limits, rendered from the tool#1
@ ¶0 ‖ heading ‖ 1
  ### 5.4 The limits, rendered from the tool
@ ¶1 ‖ paragraph ‖ 1
  Every number below is the tool's (`--json`, `numbers.contract`), printed with its marker; each
   frame prints the same number in its message and the tool compares it clause by clause. The
   checks run cheapest first, and the first that fails ends the run, so a 50 MB file is refused
   before it is read (BQ-5 RULED; E15-S07, `BL:1136`): size → parse depth / node count → schema →
   version → per-pane registry → preview. Nothing is created by any of them; only Import as new
   workspace sends, and only after the preview (Condition 1).
@ ¶2 ‖ table ‖ 1
  | Step | Limit | Source | Past it | Words (§9) |
  | --- | --- | --- | --- | --- |
  | 1 size | a file of at most 2 <!-- audit:contract.size_mb=2 --> MB, read from the chosen file's
   size before a byte of it is read | E15-S07's default (`BL:1136`) until `22` sets the cap
   (D09-G5); a 2 <!-- audit:contract.size_mb=2 --> MB file is checked within 500 <!--
   audit:contract.parse_ms=500 --> ms in a worker (`14:637`) | `SCR-026/rejected-oversized` |
   `e15.import.rejected.oversized` |
  | 2 parse | nesting at most 16 <!-- audit:contract.depth=16 --> levels | the server's own rule
   for a workspace body (`22:19819`), reused (BQ-5 RULED) | `SCR-026/rejected-nodes` |
   `e15.import.rejected.depth` |
  | 2 parse | at most 10,000 <!-- audit:contract.nodes=10000 --> values, PROPOSED | E15-S07 names
   a node-count limit and fuzzes "a document with 10000 nested nodes" (`BL:1136`); no contract
   carries a number (D09-G5) | `SCR-026/rejected-nodes`, its variant | `e15.import.rejected.nodes`
   |
  | 3 schema | the envelope's `schema_version` first, then the shape of a version this app reads:
   every required key and every known key's type (`22:21402–21423`) | `22:21402–21423`; an unknown
   key ignored by the client and refused by the server on its write path (C-6.3; `04:855`); the
   bundle and `ChartTemplateInput` are not closed yet (D09-G4) | `SCR-026/rejected-malformed` |
   `e15.import.rejected.malformed` |
  | 3 schema | at most 16 <!-- audit:contract.panes_max=16 --> panels a layout | the contract's 16
   (`D02:133`) | `SCR-026/rejected-malformed`, its variant | `e15.import.rejected.panes` |
  | 3 schema | at most 32 <!-- audit:contract.layouts_max=32 --> layouts a workspace | the store's
   limit (`22:8886`); the bundle carries none (D09-G5) | `SCR-026/rejected-malformed`, its variant
   | `e15.import.rejected.layouts` |
  | 3 schema | at most 200 <!-- audit:contract.presets_max=200 --> indicator presets, the array
   whole or not at all | `22:21422–21423`, where the server also refuses the array beyond 1 MiB of
   preset JSON | `SCR-026/rejected-malformed`, its variant; the server's refusal is
   `SCR-026/refused-server` | `e15.import.rejected.presets` |
  | 4 version | the format versions this app reads (§5.3) | `22:21408`; D09-G2 | the two version
   refusals; the migrated preview | §5.3 |
  | 5 registry | each pane's kind and each setting against the registry | the open-ended kinds
   (`22:19971`); settings that never hold account ids (`22:20031`) | never a rejection: an unknown
   kind or an account-scoped setting is a Drop row (§4.2) | `e15.import.reason.unknown_kind` |
  | the send | at most 32 <!-- audit:contract.workspaces_max=32 --> workspaces a user | `22:8686`
   | `SCR-026/refused-limit` | `e15.import.refused.limit` |
  | the send | everything above, checked again by the server | E15-S07 (`BL:1136`); `04:54`;
   C-2.12 | `SCR-026/refused-server` | `e15.import.refused.server` |
@ ¶3 ‖ paragraph ‖ 1
  **How the parse step stays bounded.** The worker reads the text once, counting the nesting and
   the values as it goes, and stops at the first limit it crosses, before any document is built; at
   2 <!-- audit:contract.size_mb=2 --> MB that stays inside the parse budget of `14:637`, and a
   hostile file stalls the worker, never the dialog or the trading panes behind it (E15-S07's
   containment note, `BL:1136`). **How the schema step names a key.** It reads the envelope's
   `schema_version` first and names it when it is absent or not a whole number; it then names the
   first failure in document order, one key per message (`14:636`): a required key that is missing
   takes `e15.import.rejected.malformed`'s words; a known key whose value is the wrong kind takes
   the same frame with the PROPOSED `e15.import.rejected.invalid`, "This isn't a workspace file:
   `{key}` isn't valid. Nothing was imported.", the frame's variant (§9). An unknown key, the
   prototype-shaped keys of E15-S07's fuzz corpus included (`BL:1136`), is ignored and never
   reaches an object; the server refuses it on its write path (C-6.3), which is
   `SCR-026/refused-server`. A key written twice makes the text ambiguous, so it is refused with
   the same variant, the key named.
@ ¶4 ‖ paragraph ‖ 1
  **The budget is a confirm, not a refusal** (BQ-6 RULED). A file whose layout that opens would
   cost more than the frame budget is a valid file: the preview says so
   (`SCR-026/preview-over-budget`), and Import as new workspace asks through US-LAY-001's
   measured-cost confirm, re-verbed Import anyway (`SCR-026/budget-confirm`, §4; `D02:292`); its
   Cancel fires `layout.import_rejected{reason: budget-exceeded}` and returns to the preview, so
   `budget-exceeded`, the last of the ticket's six reasons, belongs to that confirm and never to a
   rejection frame. Past the hard cap it is a refusal: the ticket's "30-panel file" (its test plan,
   `BL:266`) is a layout over the 16 <!-- audit:contract.panes_max=16 --> panels a layout holds
   (`D02:133`), refused whole with `e15.import.rejected.panes`.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 5. Rejections
   and refusals › 5.5 Untrusted strings, nothing kept, and the refusals at the send#1
@ ¶0 ‖ heading ‖ 1
  ### 5.5 Untrusted strings, nothing kept, and the refusals at the send
@ ¶1 ‖ paragraph ‖ 1
  **Condition 1, applied to a refusal** (RULED, binding on every frame). A refusal shows at most
   one string that came from outside the app: the offending key (`SCR-026/rejected-malformed`,
   `SCR-026/refused-server`) or the chosen file's name (`SCR-026/rejected-wrong-type`). Every other
   part of a message is the app's own: the size comes from the file's size before it is read, the
   line from the parser, the counts from counting, the versions from parsing a whole number (§5.3).
   The two strings follow five rules:
@ ¶2 ‖ list ‖ 1
  1. **Text only.** Each is one text node of its own, never set through `dangerouslySetInnerHTML`
   (`04:967`; C-12.10), never a link and never a format string, so a `{` in a key stays a `{`. No
   Markdown, HTML or link is ever rendered from it, and nothing in it that looks like an address is
   made live (the ticket's Security notes, hazard 2; `BL:266`).
  2. **Cleaned.** Before display the characters that `22`'s name rule removes — the C0 and C1
   controls, U+2028, U+2029, the bidi marks and overrides U+061C, U+200E, U+200F, U+202A–U+202E and
   U+2066–U+2069 — and every code point of Unicode's `Default_Ignorable_Code_Point` property
   (DerivedCoreProperties.txt), the whole set, which would otherwise be invisible (for example
   U+00AD, U+034F, the Hangul fillers U+115F, U+1160, U+3164 and U+FFA0, U+17B4–U+17B5,
   U+180B–U+180F, U+200B–U+200D, U+2060–U+206F, U+FEFF, U+FE00–U+FE0F, U+FFF0–U+FFF8,
   U+1BCA0–U+1BCA3, U+1D173–U+1D17A and U+E0000–U+E0FFF), each shows as a visible "�" instead of
   acting or hiding, as in the preview's table (§4.4), so neither string can reorder the sentence
   around it, pad a key past its cap with what cannot be seen or spoof an extension
   (`22:19819–19824`); PROPOSED for a key and a file name, which no contract cleans, and a file's
   extension is read after this cleaning (§3.4).
  3. **Capped.** A key is shown at most 64 <!-- audit:design.key_cap=64 --> characters, a file
   name at most 40 <!-- audit:design.file_cap=40 -->, counted after cleaning, an ellipsis (…) past
   the cap (the Fixture's display caps, PROPOSED). No contract bounds either string, so the cap
   also holds in the accessible name, which carries the same shortened text with the word
   "(shortened)" after it, PROPOSED: nothing past a cap is ever rendered, announced, copied or
   logged. The bounded strings — names, symbols, panel kinds, drawing labels — never reach a
   refusal, and one over its contract's length fails the schema step before any preview (§5.4). The
   frames' caps clause reads "the whole capped value in the accessible name": nothing past a cap
   reaches it.
  4. **Never logged.** `layout.import_rejected{reason}` carries the reason word only, never a key,
   a name, a size or a line; workspace and layout content is never logged (`21:5079`), and E15-S07
   logs its export requests without file contents (`BL:1136`).
  5. **Nothing kept.** When a refusal shows, the worker's text and document and the file's handle
   are dropped: nothing reaches the workspace store, the browser's storage, a cache or a log, and
   Choose another file starts from nothing (BQ-5 RULED). The `state:` clause of every frame in §5.1
   says it in the user's terms: no workspace, layout or pane was created and the user's workspaces
   are unchanged. A refusal that arrives after the view closed holds only its capped message, and
   only while its toast stands (§3.5).
@ ¶3 ‖ paragraph ‖ 1
  **The browser's checks are a courtesy** (Condition 1; `04:54`; C-2.12). The server checks size,
   depth, nodes, schema and version again when the file is sent (E15-S07), and `SCR-026/validating`
   says so in its `server:` clause; a file the browser passed can still be refused at the send, and
   a client that skips the checks gains nothing.
@ ¶4 ‖ paragraph ‖ 1
  **The refusals at the send** are refusals at the point of action, T4 in E09-D09's rule, step 2
   (`E09D09:32`), never a lock:
@ ¶5 ‖ list ‖ 1
  - **`SCR-026/refused-limit`** — `409 limit_reached` when another window created a workspace
   between the preview and the send, so the user now has 32 <!-- audit:contract.workspaces_max=32
   --> workspaces (`22:8686`; `FL:164`). The message is "Nothing was imported." then E15-D02's "You
   have 32 workspaces, the most you can have. Delete one, then import again." (`D02:518`). The
   footer is Cancel alone, and it takes focus; the zone and Choose file… leave the body, an absence
   (§6), because another file would meet the same limit; the way on is in the words. Once the
   dialog closes, the session's legs and states are read again and Import… reads
   `workspace.limit.count` in its menus (`SCR-026/entry-limit`, §6).
  - **`SCR-026/refused-server`** — `422 validation_failed` when the server's own re-check refuses
   what the browser passed (`22:19819`): "Nothing was imported." then "The server didn't accept
   this file: `{key}` isn't valid.", the key the first field path of the problem's `errors[]`,
   cleaned and capped as above; the server's own sentence is never shown (`15:306`). Choose another
   file takes focus. A refusal that names no field — the store unavailable, `503` — takes the same
   frame with the PROPOSED `e15.import.refused.store`, "The workspace store didn't answer. Choose
   the file again in a moment.", in place of the key's sentence: nothing of the file was kept, so
   the way on is to choose it again (§9; the problem types are D09-G7's). A `413`, a file larger
   than the server takes (`22:8691`), takes the same frame with the PROPOSED
   `e15.import.refused.size`, "The server didn't accept this file: it is larger than the server
   takes.", the oversized refusal's words at the send, the number the server's (D09-G5).
  - **`SCR-026/refused-unconfirmed`** — not a refusal but an outcome nobody knows: a send whose
   answer never came, a timeout or a dropped connection. The import may have happened, so the frame
   never claims that nothing was imported; it says "We couldn't confirm the import. Check your
   workspaces before importing again." (PROPOSED, `e15.import.refused.unconfirmed`). The zone and
   Choose file… leave the body, no verb sends the file again, and Close takes focus; the one-call
   operation takes an `Idempotency-Key`, as `createWorkspace` does (`22:8692`), so a send the
   platform repeats never imports twice (D09-G1; D09-D33).
  - **A `403` at the send is the session's, not the file's**: view-as began or the permission went
   while the dialog was open. Nothing is imported, and the dialog shows `SCR-026/import-leg-lost`
   (§3), its verb in place with its reason (§6).
  - **No event fires at the send.** The ticket's six reasons name none of these refusals;
   E15-S07's `semantic` would hold the server's (`BL:1136`), and D09-G13 maps the two lists.
@ ¶6 ‖ paragraph ‖ 1
  **Never a partial import.** The send is one call that creates the workspace with all its layouts
   or creates nothing (D09-G1; E15-S07 lands it in `22` first, C-6.1). The browser-side sequence of
   `createWorkspace` then `createLayout` for each layout (`FL:171`) is not built: a failure between
   two calls would leave a workspace the user never chose, the partial import the ticket forbids
   (`11:2871`; `BL:266`). The import is built on the one-call operation, never before it, and every
   refusal in this section therefore leaves the user's workspaces exactly as they were; a send
   whose answer never came says only what is known (D09-D33).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 6. T2 —
   stated once#1
@ ¶0 ‖ heading ‖ 1
  ## 6. T2 — stated once
@ ¶1 ‖ paragraph ‖ 1
  **T2 — disabled with a visible reason, one rule for this spec (A1; BQ-14 RULED; Condition 2;
   every T2 row of §3 cites "§6").** E09-D09's decision rule decides every control here, the first
   "yes" winning (`E09D09:32`; `14:85`): a server refusal is T4 at the point of action; then the
   session's legs, in the server's own order, then a state the client knows. **Import… is a write**
   — `createWorkspace` · `workspaces:write`, scope `self` (`22:8682`; `04:1141`) — so its legs run
   `rbac.view_as` → `rbac.permission` → `workspace.limit.count`: first, while `GET
   /auth/session/view-as` reports a context, it is T2 with `rbac.view_as`, "Read-only while viewing
   as {user}." (`E09D09:95`), because the server refuses a view-as write before it authorises;
   otherwise, without `workspaces:write`, it is T2 with `rbac.permission` and the verb of
   `E09D09:114`, "Your role can't save workspaces." (`E09D09:89`); otherwise, at 32 <!--
   audit:contract.workspaces_max=32 --> workspaces (`22:8686`), it is T2 with the state key
   `workspace.limit.count`, "You have the most workspaces you can have." (`D02:674`). These are the
   keys merged E15-D02 gives "+" › Import… (`D02:639`; `D02:655`) and merged E15-D03 renders as its
   R-5 (`D03:564`; its deck `D03:634–636`); this spec adds none. A workspace write is scope `self`,
   so the account and environment legs never apply. Each reason is one sentence of at most 60 <!--
   audit:contract.reason_max=60 --> characters with a full stop that names a capability, never data
   (`E09D09:85–95`); the first missing leg is the one named. **The anatomy** (`E09D09:49`;
   `D02:641`): A T2 control keeps its native role and its full label; it is `aria-disabled="true"`,
   never `disabled`, so it stays in the Tab order and a menu item stays arrow-reachable; the
   CMP-019 `lock` glyph (`decorative=false`, named "Not available") leads the label; CMP-079
   RbacGate wraps it and its reason node is in the DOM at mount, linked by `aria-describedby`. The
   label and the lock are `color.text.tertiary`, the reason `color.text.secondary`, a filled
   button's fill `color.surface.raised` with the `color.border.default` hairline — never
   `color.text.disabled`, never `opacity.disabled` (§8 rows 2, 5, 23 and 25). **The rendering** is
   2a: in the menus, the reason as Import…'s second line; in the dialog, under Import as new
   workspace when a leg goes while the dialog is open (`SCR-026/import-leg-lost`). While viewing
   as, the SCR-124 banner is the one notice and the menu item points at it, repeating no reason
   (`D02:642`). **The keys** (`D02:643`): `Enter` or `Space` on a T2 control changes nothing and
   sends nothing; the reason is re-shown in place and announced once, politely; an arrow lands on a
   T2 menu item without activating it. A T2 control emits no analytics. A leg that goes while the
   dialog is open turns the dialog's write T2 where it stands — no reload, no focus move, the
   checked file and its preview kept.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 6. T2 —
   stated once › 6.1 The gated set, per session#1
@ ¶0 ‖ heading ‖ 1
  ### 6.1 The gated set, per session
@ ¶1 ‖ paragraph ‖ 1
  The session's legs decide, never a role's name (`E09D09:32`): an Owner holds `workspaces:write`,
   a Manager holds it for their own workspaces and a Viewer does not (`04:1141`). `04:1182` marks a
   Viewer ✔(own) on that permission, a contradiction listed in §12 that gates nothing here, because
   the server enforces (C-12.4) and E15-D01's locked list says a Viewer cannot save a workspace
   (`D02:84`). The view-as column holds for any target.
@ ¶2 ‖ table ‖ 1
  | Control (frames) | Operation · permission | Owner | Manager | Viewer | View-as (any target) |
   At 32 <!-- audit:contract.workspaces_max=32 --> workspaces (a state) | Rendering |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | Import… in "+" and the rail's workspace menu (`SCR-026/entry`, `SCR-026/entry-view-as`,
   `SCR-026/entry-permission`, `SCR-026/entry-limit`) | `createWorkspace` · `workspaces:write`,
   scope `self` (`22:8682`) | T1 | T1 (own workspaces) | T2 `rbac.permission`
   (`SCR-026/entry-permission`) | T2 `rbac.view_as`, the banner the one notice
   (`SCR-026/entry-view-as`) | T2 `workspace.limit.count` (`SCR-026/entry-limit`) | 2a, the item's
   second line; view-as: the one notice |
  | Import as new workspace, the dialog's primary (`SCR-026/preview`, `SCR-026/import-leg-lost`) |
   the one-call import, `workspaces:write` (D09-G1) | T1; T2 in place when a leg goes while the
   dialog is open | as the Owner | reached by a link only (§3.2): T2 `rbac.permission` in place |
   reached by a link only: T2 `rbac.view_as` in place | a race at the send is T4
   (`SCR-026/refused-limit`), then the entry reads the key | 2a under the button |
  | Export… in SCR-025's Share section, the tab's `[⋯]` and the rail's workspace menu; Download
   file (`SCR-025/*`) | `exportWorkspace` · `workspaces:read` (`22:12843`) | T1 | T1 | T1 on a
   stored workspace; on the unsaved default an availability state (`SCR-025/export-unavailable`) |
   T1: a read | none | — : never gated |
  | Choose file…, a drop, the five checks, the preview, Copy report | none: the browser and its
   worker | T1 | T1 | T1, reached by a link only | T1, reached by a link only | none | — : never
   gated |
  | Cancel, `Esc`, ×, Close, Choose another file (every frame) | none | T1 | T1 | T1 | T1 | T1 |
   never gated (§7) |
@ ¶3 ‖ paragraph ‖ 1
  **Not T2 — each owned elsewhere, never drawn with a lock** (`D02:645`; `S4:194`):
@ ¶4 ‖ list ‖ 1
  - **Export…, a read.** No leg gates it: T1 for every session on a stored workspace, view-as
   included, its preview, its Download file and its completion alike (`22:12843`; `D03:384`). On
   the viewer's unsaved default it is an availability state — `aria-disabled`, the line "This
   workspace isn't saved." (`ws.export.unstored`) under it, no lock, no CMP-079, no key
   (`D03:583`).
  - **A rejected file.** The six rejections, the two refusals at the send and the unanswered send
   are outcomes (§5): Import… stays T1, since it opened the dialog, and the dialog's import verb is
   absent, omitted rather than T2-locked (AC 2; BQ-11 RULED).
  - **An absence.** A control that is not drawn is no lock: the verb on a refusal; Choose another
   file, the zone and Choose file… on `SCR-026/refused-limit` and `SCR-026/refused-unconfirmed`.
   The drop zone likewise, which is never a Tab stop and never needed one (§7). None of them is
   dimmed or carries a reason.
  - **Validity.** A file that fails a check is an outcome, not a validity look, and no field here
   is typed, so no control is natively disabled for validity; the budget's Import anyway is a
   confirm, not a gate (BQ-6 RULED). Validity is never a lock.
  - **Busy.** "Preparing the file…", "Checking scalping.json… step 3 of 5" and Import as new
   workspace in flight are `aria-busy` with their labels kept, focusable, no lock and no reason
   (`SCR-025/export-preparing`, `SCR-026/validating`, `SCR-026/creating`).
  - **Outcomes.** The completion line, the report and "Nothing was imported." are lines after the
   act, never a control's state.
  - **A refusal at the point of action, T4.** `409 limit_reached` and `422 validation_failed` at
   the send (§5.5), after which the session's legs and states are read again; a `403` there turns
   the dialog's verb T2 in place (`SCR-026/import-leg-lost`); a send whose answer never came is an
   outcome, `SCR-026/refused-unconfirmed`, never a lock.
  - **The exits.** Cancel, `Esc`, ×, Close and Choose another file are T1 for every session,
   view-as and the Viewer's included (§7).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 7. Exits,
   keyboard, focus and live regions#1
@ ¶0 ‖ heading ‖ 1
  ## 7. Exits, keyboard, focus and live regions
@ ¶1 ‖ paragraph ‖ 1
  **The exits, stated once (A3; Condition 4).** Cancel, `Esc`, ×, Close and Choose another file
   are never gated: never T2, never locked by view-as, a role, a limit or any state, on every frame
   of this spec. Before the send, Cancel, `Esc`, × and a press on the scrim close the dialog with
   nothing imported (`SCR-026/cancelled`; `FL:162`) or nothing exported (`FL:146`); once the import
   is sent, Close and `Esc` close the view and cancel nothing, the import finishing on its own
   (`15:468`; `SCR-026/creating`). `Esc` is reserved and never remapped (`05:85`), and it closes
   the topmost layer only — the OS file picker, then a menu, then the stacked confirm, then the
   dialog (`S4:119`; `S4:734`). A press on the scrim is Cancel on the export and the import dialog,
   each a `dialog`, and changes nothing on the stacked confirm, an `alertdialog` (`15:468`). No
   dialog here asks before it closes: a chosen file is no unsaved change, so the prompt of slice
   4's H36 never appears (`S4:904`). The tool reads every frame row for it (A2): each `exits T1:`
   clause names its exits; no gated word sits in a clause beside an exit; and every rejection lists
   Choose another file among its exits.
@ ¶2 ‖ paragraph ‖ 1
  **Each dialog's keyboard model** (`05:96`; `S4:119`; `15:463–471`). The trap cycles in DOM order
   and wraps; text — the trust note, a list, a message, a caption — is read, never a stop. The
   close × sits first in the DOM, in the title row.
@ ¶3 ‖ table ‖ 1
  | Frames | Initial focus | Tab order | `Enter` | `Esc` | Focus on close |
  | --- | --- | --- | --- | --- | --- |
  | the menus: `SCR-025/export-entry`, `SCR-025/export-unavailable`, `SCR-026/entry`,
   `SCR-026/entry-view-as`, `SCR-026/entry-permission`, `SCR-026/entry-limit` | the menu's first
   item (CMP-041) | arrows, not `Tab`: `↑` and `↓` reach every item, the T2 item and the
   unavailable one included | opens the dialog; on a T2 or an unavailable item nothing is sent and
   its line is re-shown and said once (§6) | closes the menu, focus back on its button | the menu's
   button: the tab's `[⋯]`, "+" or the rail's workspace menu; in SCR-025's Share section Export… is
   a button and keeps focus |
  | `SCR-025/export-preparing` | Cancel | × → Cancel | Cancel's action | Cancel: the call is
   dropped, nothing exported | the menu button or SCR-025's Export… that opened it |
  | `SCR-025/export-preview`, `SCR-025/export-cancelled` | the title (`tabindex="-1"`) on the
   preview; Download file once the save sheet has closed unsaved | × → the body, a stop only while
   it scrolls → Cancel → Download file | the focused button; on the title nothing | Cancel: nothing
   exported | as above |
  | `SCR-025/export-failed` | Try again | × → Cancel → Try again | the focused button | Cancel |
   as above |
  | `SCR-025/export-done` | Close | × → Close | Close's action | Close | as above |
  | `SCR-026/pick`, `SCR-026/drag-over`, `SCR-026/drag-over-rejected`, `SCR-026/validating` |
   Choose file… | × → Choose file… → Cancel | on Choose file… the OS picker opens, as on `Space` |
   Cancel: nothing imported, a check in progress stopped (`SCR-026/cancelled`) | "+" or the rail's
   workspace menu button, whose Import… opened it |
  | `SCR-026/preview`, `SCR-026/preview-migrated`, `SCR-026/preview-over-budget` | Choose file…,
   where it already was: the preview's arrival never moves focus (`05:96`) | × → Choose file… → the
   table's scroll region → Cancel → Import as new workspace | the focused button; on the region
   nothing | Cancel: nothing imported | as above |
  | `SCR-026/budget-confirm`, a CMP-044 `alertdialog` stacked over the preview | Cancel | Cancel →
   Import anyway; it has no close × | the focused button; Import anyway takes no activation in its
   first moment, as CMP-044's delay sets (`15:476`) | Cancel: back to the preview, nothing sent |
   after Cancel, Import as new workspace on the preview; after Import anyway, the same button, now
   busy (`SCR-026/creating`) |
  | `SCR-026/creating` | Import as new workspace, busy, where it was | × → the table's scroll
   region → Close → Import as new workspace (Choose file… and the zone have left the body, §3.5) |
   nothing more is sent: the button is busy | Close: the view only; the import is sent and finishes
   | as above; the outcome still speaks, below |
  | `SCR-026/import-leg-lost` | Import as new workspace, where it was: focus never moves (§6) | ×
   → Choose file… → the table's scroll region → Cancel → Import as new workspace, still a stop (§6)
   | on the verb nothing is sent; its reason is said once | Cancel: nothing imported | as above |
  | the six rejections and `SCR-026/refused-server` | Choose another file | × → Choose file… →
   Cancel → Choose another file | on Choose another file the OS picker opens, and a chosen file
   starts the checks again from size | Cancel: nothing imported | as above |
  | `SCR-026/refused-limit` | Cancel, the named fallback once the verb has left the footer
   (`15:468`) | × → Cancel | the focused button | Cancel: nothing imported | as above; the menus'
   Import… then reads `workspace.limit.count` (§6) |
  | `SCR-026/refused-unconfirmed` | Close | × → Close | the focused button | Close: nothing more
   is sent | "+" or the rail's workspace menu button, so the rail shows whether the workspace was
   made |
  | `SCR-026/report` | the heading "Import report" (`tabindex="-1"`), on arrival only | × → the
   table's scroll region → Copy report → Close | the focused button | Close | the new workspace's
   tab, the import's result, which opened behind the dialog (`D02:520`; PROPOSED, since the
   opener's menu belongs to the old tab) |
  | `SCR-026/cancelled` | —: the dialog has closed | — | — | — | "+" or the rail's workspace menu
   button |
  | `SCR-025/export-reflow-200`, `SCR-026/reflow-200`, `SCR-026/compact` | as the frame it reflows
   | as that frame | as that frame | as that frame | as that frame |
@ ¶4 ‖ paragraph ‖ 1
  **The focus pairs, stated once (S20).** On these five frames focus lands only on the controls
   named here, the frame's own first: `SCR-026/refused-limit` on Cancel; `SCR-025/export-preparing`
   on Cancel or the title; `SCR-025/export-preview` on the title or Cancel; `SCR-025/export-failed`
   on Try again or Cancel; `SCR-025/export-cancelled` on Download file or Cancel. A focus claim on
   any other control of these frames fails.
@ ¶5 ‖ paragraph ‖ 1
  **Keys.** `Tab` and `Shift+Tab` cycle inside the topmost layer only, and the page under the
   scrim takes no input, while the TopBar, the StatusBar and the shell's live regions stay outside
   it (`15:468`). `Enter` and `Space` on Choose file… or Choose another file open the OS file
   picker, which is the platform's own layer: a chosen file returns focus to the button that opened
   the picker and starts the checks, and the picker's own `Esc` or Cancel returns focus there with
   nothing changed (`05:101`; `FL:169`). The drop zone only adds to the input: it is never a Tab
   stop, has no role and no name, and every drop has the button as its keyboard equal (`05:35`;
   `15:694`). The preview's and the report's tables are CMP-049's table mode: one stop, the scroll
   region named by the caption, no control in a body row (`15:530`); a screen reader's table
   commands read each cell with its column header, and each Item cell is its row's header
   (`scope="row"`, PROPOSED: CMP-049 leaves row headers to the host), so a row reads as its item,
   its type, its action and its reason. On a T2 control, `Enter` and `Space` change nothing (§6).
@ ¶6 ‖ paragraph ‖ 1
  **Announcements** (`05:144`; `05:150`; `S4:140`). Polite, and once. A dialog speaks when focus
   enters it; every other message goes through a region mounted empty with its host, its text
   inserted when the state begins, so it is never destroyed and re-created (`05:150`). No step of
   the checks, no tick of the progress and no drag is announced.
@ ¶7 ‖ table ‖ 1
  | Event | Frames | How it speaks | String (§9) |
  | --- | --- | --- | --- |
  | a dialog opens | every dialog frame | no live region: read as focus enters it, the title and
   then what focus lands on (`15:468`) | `e15.export.title` · `e15.import.title` |
  | the export file is being prepared | `SCR-025/export-preparing` | CMP-038's one `role="status"`
   region, once (`15:409–417`) | `e15.export.preparing` |
  | preparing the file fails | `SCR-025/export-failed` | the CMP-027 message, polite, once |
   `e15.export.failed` |
  | the export file is saved | `SCR-025/export-done` | polite, once: the completion line |
   `e15.export.done` |
  | the save sheet closes unsaved | `SCR-025/export-cancelled` | never: the preview is as it was
   and focus is on Download file | — |
  | the check starts | `SCR-026/validating` | polite, once, through the import dialog's status
   region; CMP-023 is never a live region itself (`15:262–270`) | `e15.import.checking` |
  | the check passes | `SCR-026/preview`, `SCR-026/preview-migrated`,
   `SCR-026/preview-over-budget` | polite, once, through the same region: the caption, its counts
   first, so the summary comes before the rows (`14:636`); after the migration line on a migrated
   file, with the budget sentence on a file over the budget | `e15.import.migrated` ·
   `e15.import.caption` · `e15.import.caption_budget` |
  | the check fails | the six rejections | the CMP-027 message, polite, once; the status region
   adds nothing (`S4:919`); focus moves to Choose another file once the message has been read, and
   the message is not that button's description, so it is read once | the six messages and their
   variants |
  | a file is dragged over the zone | `SCR-026/drag-over`, `SCR-026/drag-over-rejected` | never:
   the words change for the pointer's user, and the keyboard path never drags |
   `e15.import.drop_active` · `e15.import.drop_rejected` |
  | the budget confirm opens | `SCR-026/budget-confirm` | no live region: an `alertdialog` read as
   focus enters it, its title and its body | `layout.cost.import.title` · `layout.cost.import.body`
   |
  | Import as new workspace or Import anyway pressed | `SCR-026/creating` | nothing at the press:
   the button keeps its name with `aria-busy` (`15:48–57`) | — |
  | the import succeeds | `SCR-026/report` | polite, once: the success line; focus moves to the
   report's heading | `e15.import.report.done` |
  | the import succeeds after the view was closed | after `SCR-026/creating` | polite, once,
   through CMP-212's region: a persistent CMP-045 `success` toast with the success line and the
   action View report, which reopens the report as the dialog's final step (PROPOSED; a toast with
   an action never times out, `15:483–490`) | `e15.import.report.done` · `e15.import.report.view` |
  | a refusal arrives after the view was closed | after `SCR-026/creating` | polite, once, through
   CMP-212's region (`politeness="polite"`, as a refusal at the send speaks here, D09-C12): a
   persistent CMP-045 `danger` toast, "Nothing was imported.", with the action Review, which
   reopens SCR-026 at the refusal's frame (PROPOSED; a toast with an action never times out,
   `15:483–490`) | `e15.import.nothing` · `e15.import.review` |
  | a send left unanswered after the view was closed | after `SCR-026/creating` | polite, once,
   through CMP-212's region: a persistent CMP-045 `warning` toast with the frame's words, "We
   couldn't confirm the import. Check your workspaces before importing again.", and the action
   Review, which reopens SCR-026 at `SCR-026/refused-unconfirmed`; never "Nothing was imported.",
   since the import may have happened (D09-D33; PROPOSED; a toast with an action never times out,
   `15:483–490`) | `e15.import.refused.unconfirmed` · `e15.import.review` |
  | a refusal at the send | `SCR-026/refused-limit`, `SCR-026/refused-server`,
   `SCR-026/refused-unconfirmed` | polite, once; focus moves to the frame's named button once the
   message has been read, and the message is not that button's description, so it is read once.
   PROPOSED departure from slice 4's conventions 33, which speaks a refusal at its point of action
   assertively (`S4:140`): the refused verb leaves the footer and focus moves with it, so an
   interruption would only cut that reading short (D09-C12) | `e15.import.nothing` ·
   `e15.import.refused.limit` · `e15.import.refused.server` · `e15.import.refused.unconfirmed` |
  | Copy report pressed | `SCR-026/report` | CMP-033's "Copied", polite, once; never the copied
   text (`15:366`) | `e15.import.report.copied` |
  | a press on a T2 control | `SCR-026/entry-view-as`, `SCR-026/entry-permission`,
   `SCR-026/entry-limit`, `SCR-026/import-leg-lost` | polite, once per press: its reason (§6) |
   `rbac.view_as` · `rbac.permission` · `workspace.limit.count` |
  | a leg goes while the dialog is open | `SCR-026/import-leg-lost` | the shell's one
   access-changed announcement; the dialog adds none and focus stays (§6) | — |
@ ¶8 ‖ paragraph ‖ 1
  **The screen-reader desk pass `(heuristic)`** (DoD-5; the owner's pass with a screen reader is
   §14's). What the accessibility tree exposes, read from the frames' roles and names; no session
   was run and none is reported.
@ ¶9 ‖ table ‖ 1
  | Moment | What the tree exposes (role · name · state · description) | Source |
  | --- | --- | --- |
  | the import dialog opens on `SCR-026/pick` | `dialog` · "Import workspace"; focus on the button
   "Choose file…", described by "or drop a workspace file here" and "JSON, up to 2 MB"; the native
   input is labelled by that button and stays out of the Tab order; the trust note is a `note` read
   in browse mode; the zone around the button has no role and no name | `15:694`; `D02:513` |
  | the check runs, `SCR-026/validating` | `progressbar` · named by "Checking scalping.json…" ·
   its value the share of the five steps done, its text "Checking scalping.json… step 3 of 5";
   Cancel is reached as before | `15:262–270`; `D02:515` |
  | `Tab` reaches the preview's table | the scroll region · named by its caption "Preview — 7
   panels and 2 layouts to add · 3 dropped · 1 remapped"; inside, a `table` with that caption, four
   `columnheader`s — Item, Type, Action, Reason — and each Item cell a `rowheader`; each Action
   glyph has no name, its word is the cell's text | `15:530`; `14:636` |
  | a rejection, focus on Choose another file | button · "Choose another file", focused once the
   message's polite region has read it, e.g. "This file was exported by format version 2 and can't
   be imported into format version 1. Nothing was imported. Export it again from a version 1 app,
   or update this app."; the message is not the button's description, so it is read once |
   `15:306`; `05:150` |
  | the malformed file's key | inside the message, plain text read in order, its punctuation as
   the reader's settings speak it; at most 64 <!-- audit:design.key_cap=64 --> characters, then
   "(shortened)" (§5.5) | `14:636` |
  | the budget confirm opens | `alertdialog` · "Open Wall with 12 panels?" · described by its
   body; focus on "Cancel" | `15:468`; `D02:292` |
  | the report arrives | heading · "Import report" (focused) inside a `region` named "Import
   report"; the success line; the table as above, its caption "Report — 7 panels and 2 layouts
   added · 3 dropped · 1 remapped"; the buttons "Copy report" and "Close" | `D02:520` |
  | the menu's Import… for a Viewer | menu item · "Import…" · `aria-disabled` · described by "Your
   role can't save workspaces."; the lock glyph named "Not available" leads the label |
   `E09D09:49`; `E09D09:89` |
  | the export dialog opens on `SCR-025/export-preview` | `dialog` · "Export Scalping"; focus on
   the title; the Included and the Excluded list are lists read in browse mode, one item per clause
   | `D02:511` |
@ ¶10 ‖ paragraph ‖ 1
  **200 % zoom and text size** (`05:131`; `S4:209`; `14:639`). At 200 % zoom on the 1280 × 800
   frame each dialog fills the viewport less its margins, keeps its title row and its footer and
   scrolls its body (`SCR-025/export-reflow-200`, `SCR-026/reflow-200`); the two export lists stack
   in one column, and the import's tables read one row element per record (`15:529`). A footer
   whose labels do not fit one row wraps to two in its order, Cancel first, and never truncates a
   label; the stacked confirm caps the same way. The in-app text scale reflows the same. Nothing is
   clipped: a message wraps, and a key or a file name keeps its cap and its ellipsis (§5.5).
@ ¶11 ‖ paragraph ‖ 1
  **Motion** is E15-D14's (out of scope). These dialogs use CMP-043's own — the scrim fades in
   while the card appears at once (`15:463–471`) — and reduced motion is E15-D14's to state.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 8. Tokens,
   contrast, greyscale and CVD#1
@ ¶0 ‖ heading ‖ 1
  ## 8. Tokens, contrast, greyscale and CVD
@ ¶1 ‖ paragraph ‖ 1
  **The token map and the redlines** (tokens by name, never a raw value; the boards bind exactly
   these, §0). Every token below resolves in dark, light and high contrast through `themes.json`'s
   layering: 0 <!-- audit:missing_tokens=0 --> MISSING in the tool's section 2. The redline values
   are the tool's (`--json`, `numbers.redline`), comfortable density; compact changes only the
   control and row heights (`SCR-026/compact`).
@ ¶2 ‖ table ‖ 1
  | Element | Tokens |
  | --- | --- |
  | Dialog card (every dialog frame) | CMP-043: `color.surface.overlay`, `elevation.dialog`,
   `radius.dialog` (10 <!-- audit:redline.radius.dialog=10 --> px), the `color.border.default` edge
   at `border.hairline` (1 <!-- audit:redline.border.hairline=1 --> px), `space.dialog.padding` (24
   <!-- audit:redline.space.dialog.padding=24 --> px), `space.stack.md` (12 <!--
   audit:redline.space.stack.md=12 --> px) between blocks; the scrim `palette.black` at
   `opacity.scrim` (0.6 <!-- audit:redline.opacity.scrim=0.6 -->) (`15:463–471`) |
  | Widths | the import dialog `size="lg"`, at most 960 <!-- audit:contract.dialog_lg_px=960 -->
   px wide; the export dialog `size="md"`, at most 560 <!-- audit:contract.dialog_md_px=560 --> px
   (`15:466`); the stacked budget confirm CMP-044 over the import dialog |
  | Title, body, lists | title `type.ui.heading-sm` + `color.text.primary` (`h2`); body, list
   items and messages `type.ui.body` + `color.text.primary`; help, captions and reasons
   `type.ui.caption` or `type.ui.label` + `color.text.secondary`; counts, sizes and versions
   `type.num.sm` |
  | Strings from the file and the file's name | `type.num.sm` (mono) + `color.text.primary`,
   capped with an ellipsis (§5.5) |
  | Trust note and migration line (CMP-028 `info`) | fill `color.status.info.subtle`; a
   `border.thick` (2 <!-- audit:redline.border.thick=2 --> px) start edge and the glyph in
   `color.status.info.strong`; the words `type.ui.body` + `color.text.primary` (D09-A7);
   `radius.card` (6 <!-- audit:redline.radius.card=6 --> px), `space.inset.sm` (8 <!--
   audit:redline.space.inset.sm=8 --> px) |
  | Budget line (CMP-028 `warning`) | fill `color.status.warning.subtle`; edge and glyph
   `color.status.warning.strong`; the words `type.ui.body` + `color.text.primary` |
  | Completion and report lines (CMP-028 `success`) | fill `color.status.success.subtle`; edge and
   glyph `color.status.success.strong`; the words `type.ui.body` + `color.text.primary`; a file
   name in `type.num.sm` |
  | Rejection message (CMP-027 `inline`) | the glyph CMP-019 `danger` in
   `color.status.danger.strong`, `x-circle` once registered (`15:307`); the words `type.ui.body` +
   `color.text.primary` on the card, no fill (§5.2) |
  | Choose file… and the drop zone (CMP-067) | the button CMP-001 `secondary`; the zone's resting
   edge `color.border.default` at `border.hairline`, solid (CMP-067's `color.border.dashed` is not
   a shipped token, D09-A3), `radius.card`, padding `space.inset.xl` (24 <!--
   audit:redline.space.inset.xl=24 --> px); drag-over: the edge `color.border.selected`, the fill
   `color.surface.hover`, the words changed; the words `type.ui.body` + `color.text.secondary` |
  | Progress (CMP-023) | track `color.surface.hover`, fill `color.action.primary.default`, value
   text `type.num.sm` + `color.text.secondary` (`15:262–270`) |
  | Preview and report tables (CMP-049 table mode) | header `color.surface.hover` +
   `type.ui.label` + `color.text.primary`, a `color.border.subtle` rule at `border.hairline`; rows
   `size.row.height` (24 <!-- audit:redline.size.row.height=24 --> px at comfortable), odd rows on
   the dialog's `color.surface.overlay` and even rows `color.surface.raised` (D09-A5), cells
   `space.inset.sm`; caption `type.ui.label` + `color.text.secondary` |
  | Action column | the word `type.ui.body-strong` + `color.text.primary`; its decorative CMP-019
   glyph at `size.icon` (16 <!-- audit:redline.size.icon=16 --> px): Add `check` in
   `color.status.success.strong`, Drop `x-circle` (`danger` until registered, `15:307`) in
   `color.status.danger.strong`, Remap `merge` (PROPOSED by E11-D02's icon batch; until registered
   the word alone) in `color.status.info.strong` |
  | Buttons (CMP-001) | `primary`: `color.action.primary.default` + `color.text.on-action`;
   `secondary`: `color.action.secondary.default` + `color.text.primary`; `size.control.comfortable`
   (32 <!-- audit:redline.size.control.comfortable=32 --> px), `size.control.compact` (24 <!--
   audit:redline.size.control.compact=24 --> px); footer gap `space.inset.sm`, Cancel first |
  | T2 (§6) | label and lock `color.text.tertiary`; reason `color.text.secondary`; a filled
   button's fill `color.surface.raised` with the `color.border.default` hairline; never
   `color.text.disabled`, never `opacity.disabled` |
  | Focus | CMP-039: `color.focus.ring` at `border.focus` (2 <!-- audit:redline.border.focus=2 -->
   px), outside the control, on `:focus-visible` |
@ ¶3 ‖ paragraph ‖ 1
  Token audit: the boards PR reads every shape's fills, strokes and text styles back as token
   bindings and records its counts; until then no count is claimed.
@ ¶4 ‖ paragraph ‖ 1
  **The measured matrix** (the tool's section 1, `--json` `matrix`; dark, light and high contrast
   through `themes.json`; text 4.5, body text 7.0 in high contrast (`05:130`), non-text 3.0; the
   rejected grey and the decorative edge reported, never gated). 26 <!-- audit:pairs_rows=26 -->
   gated pairs, 0 <!-- audit:pairs_fail=0 --> FAIL: 14 <!-- audit:pairs_registered=14 -->
   registered in `tools/contrast/pairs.mjs` and 12 <!-- audit:pairs_proposed=12 --> PROPOSED
   (D09-A10).
@ ¶5 ‖ table ‖ 1
  | # | Pair | Role | dark | light | hc | Verdict | `pairs.mjs` | Where |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | `color.text.primary` on `color.surface.overlay` | hc-text | 13.27 | 14.37 | 15.02 | PASS |
   registered | dialog titles and bodies, both export lists, the messages with their keys, the
   preview's and the report's odd rows — every dialog frame |
  | 2 | `color.text.secondary` on `color.surface.overlay` | hc-text | 8.14 | 8.26 | 13.27 | PASS |
   registered | the help line, the captions, the T2 reasons and the unsaved default's "This
   workspace isn't saved." |
  | 3 | `color.text.primary` on `color.surface.raised` | hc-text | 14.35 | 15.62 | 16.25 | PASS |
   registered | the preview's and the report's even rows (striping inside a dialog, D09-A5) |
  | 4 | `color.text.primary` on `color.surface.hover` | hc-text | 12.22 | 14.37 | 13.83 | PASS |
   PROPOSED | the header row: Item, Type, Action, Reason |
  | 5 | `color.text.tertiary` on `color.surface.overlay` | hc-text | 5.20 | 5.44 | 10.36 | PASS |
   registered | Import…'s label and lock in its menus (§6); Export…'s label on the unsaved default
   |
  | 6 | `color.status.success.strong` on `color.surface.overlay` | non-text | 8.69 | 3.11 | 8.69 |
   PASS | PROPOSED | the Add glyph, odd rows |
  | 7 | `color.status.danger.strong` on `color.surface.overlay` | non-text | 8.61 | 3.78 | 8.61 |
   PASS | registered | the Drop glyph, odd rows; the rejection's glyph on the card (§5.2) |
  | 8 | `color.status.info.strong` on `color.surface.overlay` | non-text | 9.03 | 4.03 | 9.03 |
   PASS | registered | the Remap glyph, odd rows |
  | 9 | `color.status.success.strong` on `color.surface.raised` | non-text | 9.40 | 3.39 | 9.40 |
   PASS | PROPOSED | the Add glyph, even rows |
  | 10 | `color.status.danger.strong` on `color.surface.raised` | non-text | 9.32 | 4.11 | 9.32 |
   PASS | PROPOSED | the Drop glyph, even rows |
  | 11 | `color.status.info.strong` on `color.surface.raised` | non-text | 9.76 | 4.38 | 9.76 |
   PASS | PROPOSED | the Remap glyph, even rows |
  | 12 | `color.text.primary` on `color.status.info.subtle` | hc-text | 10.74 | 15.44 | 12.16 |
   PASS | registered | the trust note's words on every import frame; the migration line |
  | 13 | `color.status.info.strong` on `color.status.info.subtle` | non-text | 7.30 | 4.34 | 7.30
   | PASS | PROPOSED | the trust note's and the migration line's edge and glyph |
  | 14 | `color.text.primary` on `color.status.warning.subtle` | hc-text | 9.86 | 15.62 | 11.16 |
   PASS | registered | the budget line's words (`SCR-026/preview-over-budget`) |
  | 15 | `color.status.warning.strong` on `color.status.warning.subtle` | non-text | 7.56 | 4.11 |
   7.56 | PASS | registered | the budget line's edge and glyph |
  | 16 | `color.text.primary` on `color.status.success.subtle` | hc-text | 10.21 | 15.41 | 11.56 |
   PASS | PROPOSED | the export's completion line; the report's success line |
  | 17 | `color.status.success.strong` on `color.status.success.subtle` | non-text | 6.69 | 3.34 |
   6.69 | PASS | PROPOSED | the completion and report lines' edge and glyph |
  | 18 | `color.text.on-action` on `color.action.primary.default` | text | 4.76 | 4.76 | 7.45 |
   PASS | registered | the `primary` labels: Download file, Try again, Import as new workspace,
   Import anyway, Choose another file, Close |
  | 19 | `color.text.primary` on `color.action.secondary.default` | text | 10.17 | 12.82 | 11.51 |
   PASS | PROPOSED | the `secondary` labels: Cancel, Choose file…, Copy report |
  | 20 | `color.focus.ring` on `color.surface.overlay` | non-text | 6.15 | 5.39 | 15.99 | PASS |
   registered | the focus ring on the dialog's surface |
  | 21 | `color.focus.ring` on `color.surface.raised` | non-text | 6.66 | 5.86 | 17.30 | PASS |
   registered | the focus ring where it crosses an even row |
  | 22 | `color.border.selected` on `color.surface.hover` | non-text | 4.16 | 3.80 | 5.66 | PASS |
   PROPOSED | the drop zone's edge while a file is dragged over (`SCR-026/drag-over`) |
  | 23 | `color.text.disabled` on `color.surface.overlay` | rejected-text | 2.64 | 3.44 | 2.64 |
   rejected, never drawn | PROPOSED | REJECTED: a T2 label in `color.text.disabled`, never drawn
   (§6) |
  | 24 | `color.border.default` on `color.surface.overlay` | decorative | 1.30 | 1.12 | 2.64 |
   reported, not gated | PROPOSED | the drop zone's resting edge — not the control; Choose file… is
   (§3) |
  | 25 | `color.text.tertiary` on `color.surface.raised` | hc-text | 5.62 | 5.92 | 11.21 | PASS |
   registered | the dialog's T2 verb on its raised fill (`SCR-026/import-leg-lost`, §6) |
  | 26 | `color.text.secondary` on `color.surface.raised` | hc-text | 8.81 | 8.98 | 14.35 | PASS |
   registered | the Reason column's words on the preview's and the report's even rows (D09-A5) |
  | 27 | `color.action.primary.default` on `color.surface.hover` | non-text | 3.09 | 3.80 | 5.66 |
   PASS | PROPOSED | the progress bar's fill on its track (`SCR-026/validating`) |
  | 28 | `color.action.primary.default` on `color.surface.overlay` | non-text | 3.36 | 3.80 | 6.15
   | PASS | PROPOSED | the progress bar's fill against the card around it |
  | 29 | `color.surface.hover` on `color.surface.overlay` | decorative | 1.09 | 1.00 | 1.09 |
   reported, not gated | PROPOSED | the progress bar's track on the card — decorative: the value
   text, always shown, carries the state |
@ ¶6 ‖ paragraph ‖ 1
  **The thin margins, stated.** Every gated pair clears its bar in every theme. In light the
   glyphs sit nearest their non-text bar — the Add glyph on both rows (rows 6 and 9) and the
   success line's edge and glyph (row 17) — and none carries a meaning alone: each sits beside its
   word in `color.text.primary` (rows 1 and 16). Row 23 is the grey a T2 label must never take,
   measured to show why (`E09D09:49`); row 24 is the drop zone's resting edge, decorative, because
   the zone is not the control: Choose file… is, and its label and its focus ring are rows 19 and
   20. Row 25 is the dialog's T2 verb on its raised fill (`SCR-026/import-leg-lost`): the menus' T2
   label of row 5 on the fill E09-D09 gives a T2 button. Row 26 is the Reason column's words on the
   even rows; rows 27 and 28 are the progress bar's fill against its track and against the card,
   and row 29 is its track, decorative: in light the track and the card are one grey, so the bar's
   value text, always shown, carries the state.
@ ¶7 ‖ paragraph ‖ 1
  **Why twelve are PROPOSED.** Rows 4, 6, 9, 10, 11, 13, 16, 17, 19, 22, 27 and 28 are pairs
   `tools/contrast/pairs.mjs` does not hold: the header fill, the Add glyph on both rows, the Drop
   and Remap glyphs on even rows, the trust note's edge, the success line's words and edge, the
   `secondary` label, the drag-over edge and the progress bar's fill on its track and on the card.
   D09-A10 asks the registry's owner to register them, and to add the Add / Drop / Remap encoding
   to `tools/contrast/encodings.json` with its non-colour channel, as `16:456` requires of a new
   status encoding; this spec edits nothing under `tools/`.
@ ¶8 ‖ paragraph ‖ 1
  **Greyscale and colour vision** (the tool's section 3, `--json` `grey` and `cvd`; reported,
   never a gate on the design, while the tool checks every value below against its own; boards 03,
   04 and 06 carry the greyscale and deuteranopia strips, §0). Rec. 601 luma, 0–255:
@ ¶9 ‖ table ‖ 1
  | Token | dark | light | hc | What it marks |
  | --- | --- | --- | --- | --- |
  | `color.status.success.strong` | 172 | 104 | 172 | the Add glyph; the completion and report
   lines' edge |
  | `color.status.danger.strong` | 184 | 108 | 184 | the Drop glyph; the rejection's glyph |
  | `color.status.info.strong` | 181 | 92 | 181 | the Remap glyph; the trust note's and the
   migration line's edge |
  | `color.status.warning.strong` | 202 | 108 | 202 | the budget line's edge and glyph |
@ ¶10 ‖ table ‖ 1
  | Pair (ΔE76 for normal vision, protanopia, deuteranopia and tritanopia; the verdict is the
   tool's) | ΔE76 | Verdict |
  | --- | --- | --- |
  | the Add glyph against the Drop glyph: `color.status.success.strong` vs
   `color.status.danger.strong` | 68.4 · 27.1 · 43.1 · 74.4 | distinct |
  | the Drop glyph against the Remap glyph: `color.status.danger.strong` vs
   `color.status.info.strong` | 91.2 · 78.4 · 93.6 · 81.6 | distinct |
  | the Add glyph against the Remap glyph: `color.status.success.strong` vs
   `color.status.info.strong` | 54.0 · 52.0 · 50.8 · 10.3 | distinct |
  | the Drop glyph against the budget line's glyph: `color.status.danger.strong` vs
   `color.status.warning.strong` | 14.7 · 12.5 · 14.0 · 11.2 | distinct |
@ ¶11 ‖ paragraph ‖ 1
  **What carries each meaning, so nothing rests on a hue** (the ticket's test plan item 5; DoD-4;
   `05:130`). Add, Drop and Remap are their words in their own column, each after a glyph of its
   own shape — a check, a circled cross, a merge — and never a row's colour (BQ-10 RULED;
   `14:636`). The tool's colour-vision rows show why the words must carry it: no pair collapses,
   yet under tritanopia the Add and Remap glyphs come nearest of any pair, and in light
   `color.status.danger.strong` and `color.status.warning.strong` are one amber, so the Drop glyph
   and the budget line's glyph differ by shape and words only. A rejection is its words, its glyph
   and the absent import verb; the budget line is its words and its numbers; T2 is the lock and the
   reason (§6); the drag-over state is its changed words and its edge, never the fill alone.
@ ¶12 ‖ paragraph ‖ 1
  **Forced colours** (`S4:202`). Under `forced-colors: active` each dialog keeps its edge as a
   real border, which forced colours paint CanvasText; the scrim keeps its black at its opacity
   (`forced-color-adjust: none`); text takes CanvasText and every glyph `currentColor`, so Add,
   Drop and Remap stay words with their shapes; the callouts' fills fall away and their edges
   become CanvasText, the glyph and the words carrying the tone; the drop zone's edge stays a
   border and its drag-over words change as before; the focus ring becomes a Highlight outline. No
   meaning here is lost with the colours.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 9. Copy
   deck#1
@ ¶0 ‖ heading ‖ 1
  ## 9. Copy deck
@ ¶1 ‖ paragraph ‖ 1
  Every string the export and import surfaces show, keyed in `e15.export.*` and `e15.import.*`,
   with the registered reasons (`rbac.*`, `workspace.limit.count`, `ws.export.unstored`) and the
   import's cost confirm (`layout.cost.import.*`) beside them. Every frame row's copy key is a row
   here, and each of the tool's templates opens its String cell byte for byte, its fixture
   rendering after it (the tool checks both). A reason is one sentence of at most 60 <!--
   audit:contract.reason_max=60 --> characters with a full stop (`E09D09:85–95`). No string names a
   contract field, a status code or a part of the system, except the one key a refusal names and
   the words "server" and "workspace store" where upstream uses them: the file's version is its
   "format version" to the user, never the field's name.
@ ¶2 ‖ paragraph ‖ 1
  **Variables.** `{workspace}` a workspace's name (fixture Scalping); `{clash}` the name the
   server makes unique, Scalping (2) (`D02:516`); `{file}` a file's name — on the export the base
   name the save sheet returned, suggested as `<slug>.cv-workspace-v<schema_version>.json` (BQ-8
   RULED; D09-G14), on the import the chosen one, scalping.json — except in the two version
   refusals, where it is the file's format version, a parsed whole number (§5.3); `{app}` the
   format version this app reads, 1 <!-- audit:fixture.app_format=1 -->, and `{floor}` the oldest
   it still reads, today the same (§5.3); `{from}` and `{to}` a migration's two versions; `{i}` and
   `{n}` the step under way and the five steps; `{size}` the chosen file's size in MB to one
   decimal, rounded up; `{size_mb}` and `{max}` a limit from the tool (§5.4), and `{n}` in a
   variant the count found in the file; `{line}` the line where the text stops being JSON; `{key}`
   a key path in mono, at most 64 <!-- audit:design.key_cap=64 --> characters (§5.5); `{name}` the
   chosen file's name, at most 40 <!-- audit:design.file_cap=40 --> characters; `{panels}` and
   `{layouts}` a count with its noun, singular for 1; `{dropped}` and `{remapped}` counts, and
   `{dropped_items}` the dropped count with its noun, "1 item" or "3 items"; `{layout_names}` the
   layouts' names and `{symbols}` the distinct symbols, each list joined by commas; `{groups}` the
   sync groups, joined by "and"; `{drawings}`, `{templates}` and `{presets}` a count with its noun,
   singular for 1; `{reason}` the import's own first sentence for the limit the file would cross
   (§5.2); `{layout}` the layout that opens (Wall); `{measured}` and `{estimate}` the frame time
   measured now and estimated, in ms; `{budget}` the budget, 16 <!-- audit:contract.budget_ms=16
   --> ms p95 (C-14.2); `{fps}`, `{estfps}` and `{budgetfps}` each the lesser of 60 <!--
   audit:contract.refresh_fps=60 --> and 1000 divided by its ms, rounded (`D03:630`); `{user}` the
   view-as target (alex); `{verb}` the permission's verb. Strings from the file, or from outside
   the app, enter through `{key}` and `{name}` (§5.5), through `{file}` (the chosen or the saved
   file's name, at most 40 <!-- audit:design.file_cap=40 --> characters), through `{workspace}` and
   `{clash}` on the import (the file's workspace name before the send, the server's answer after
   it, at most 40 <!-- audit:contract.name_max=40 --> characters) and through `{layout}` (the
   file's layout name, at most 40 <!-- audit:contract.name_max=40 --> characters); each is text
   only, cleaned (§5.5) and capped (the Fixture paragraph), never rendered as markup or a link and
   never read as a format string (Condition 1).
@ ¶3 ‖ paragraph ‖ 1
  **Status:** upstream = verbatim from merged text, cited · adapted = upstream words changed,
   cited, with why · ruled = the copy a BQ ruled (6396085915) · registered = a key or a component's
   own word, already registered · new · PROPOSED = this spec's, the owner's to approve (#2701).
@ ¶4 ‖ table ‖ 1
  | Id | Where | String | Status · source |
  | --- | --- | --- | --- |
  | `e15.export.menu_item` | the item in SCR-025's Share section, the tab's `[⋯]` and the rail's
   workspace menu (`SCR-025/export-entry`, `SCR-025/export-unavailable`) | "Export…" | upstream ·
   `D03:384`; `D02:511` |
  | `e15.export.title` | the export dialog's title (`h2`) on every export dialog frame | "Export
   {workspace}" · fixture "Export Scalping" | upstream · `D02:511` |
  | `e15.export.close` | the export dialog's close ×, its name | "Close Export {workspace}" ·
   fixture "Close Export Scalping" | registered pattern · CMP-043's close button named for its
   title (`15:468`) |
  | `e15.export.preparing` | the busy line, CMP-038 (`SCR-025/export-preparing`) | "Preparing the
   file…" | upstream · `D02:511` |
  | `e15.export.unsaved` | CMP-028 `info` at the top of the export body while the workspace has
   unsaved changes (`SCR-025/export-preview`, `SCR-025/export-cancelled`) | "Unsaved changes aren't
   in the file: it holds {workspace} as last saved." · fixture "Unsaved changes aren't in the file:
   it holds Scalping as last saved." | new · PROPOSED (§2.3; D09-D3) |
  | `e15.export.included` | the Included list, one item per clause, built from the fetched bundle;
   a clause whose count is 0 is left out (`SCR-025/export-preview`) | "The file includes: {layouts}
   ({layout_names}) · {panels} · symbols {symbols} · sync groups {groups} · each panel's settings ·
   {drawings}, with their text labels · {templates} · {presets}." · fixture "The file includes: 2
   layouts (Layout 1, Order-flow) · 7 panels · symbols BTCUSDT, ETHUSDT · sync groups A and B ·
   each panel's settings · 12 drawings, with their text labels · 1 chart template · 3 indicator
   presets." | upstream · `D02:511`; only what `WorkspaceBundle` holds (BQ-2 RULED;
   `22:21402–21423`) |
  | `e15.export.excluded` | the Excluded list, first-class, one item per clause
   (`SCR-025/export-preview`, `SCR-025/export-done`) | "Never included: credentials — API keys or
   tokens; accounts, trade-group and user ids; environment binding (DEMO or LIVE); alert and rule
   bindings; P&L, positions or orders." | ruled · BQ-2 (6396085915), owner approval pending
   (#2701); it extends E15-D02's sentence (`D02:511`), a C-row (D09-C5) |
  | `e15.export.caveat` | under the two lists (`SCR-025/export-preview`) | "The file does show
   your symbols, layouts and settings." | ruled · BQ-2 (6396085915); the data class is D09-G11's |
  | `e15.export.over_limit` | CMP-028 `warning` under the caveat while an import would refuse the
   file (`SCR-025/export-preview`, `SCR-025/export-cancelled`) | "{reason} You can save it, but
   this app won't import it." · {reason} is the import's own first sentence (§5.2); fixture "This
   file has 240 indicator presets; a file may carry at most 200. You can save it, but this app
   won't import it." | new · PROPOSED (§2.3; D09-D2) |
  | `e15.export.cancel` | the export footer's first button, `secondary`; `Esc` and the scrim are
   this Cancel | "Cancel" | registered · CMP-043 |
  | `e15.export.download` | the export footer's primary (`SCR-025/export-preview`,
   `SCR-025/export-cancelled`) | "Download file" | upstream · `D02:511` |
  | `e15.export.failed` | the CMP-027 message (`SCR-025/export-failed`) | "Couldn't prepare the
   file: the workspace store is unavailable. Nothing was exported." | upstream · `D02:511` |
  | `e15.export.failed_gone` | the CMP-027 message when the read answers that the workspace can no
   longer be read (`SCR-025/export-failed`) | "Couldn't prepare the file: this workspace can no
   longer be read. Nothing was exported." | new · PROPOSED (§2.1; D09-D8) |
  | `e15.export.failed_unlisted` | the CMP-027 message when the check of §2.3 declines the bundle
   (`SCR-025/export-failed`) | "Couldn't prepare the file: it holds something this preview can't
   show. Nothing was exported." | new · PROPOSED (§2.3; D09-D2) |
  | `e15.export.save_failed` | the CMP-027 message when the write fails (`SCR-025/export-failed`)
   | "Couldn't save the file. Nothing was exported." | new · PROPOSED (§2.4; D09-D4) |
  | `e15.export.retry` | the failed frame's primary | "Try again" | upstream · `D02:511` |
  | `e15.export.done` | the completion line, CMP-028 `success`, the file name in mono
   (`SCR-025/export-done`) | "Exported {workspace} as {file}." · fixture "Exported Scalping as
   scalping.cv-workspace-v1.json." | new · PROPOSED (BQ-8 RULED: the drawn completion) |
  | `e15.export.close_button` | the completion's one button, `primary` | "Close" | registered ·
   CMP-043 |
  | `e15.import.menu_item` | the item in "+" and the rail's workspace menu (`SCR-026/entry` and
   its three T2 frames) | "Import…" | upstream · `D03:365` |
  | `e15.import.title` | the import dialog's title (`h2`) on every import dialog frame | "Import
   workspace" | new · PROPOSED (BQ-9 RULED) |
  | `e15.import.close` | the import dialog's close ×, its name | "Close Import workspace" |
   registered pattern · CMP-043's close button named for its title (`15:468`) |
  | `e15.import.trust` | the trust note, CMP-028 `info` `role="note"`, on every import dialog
   frame | "A workspace file never carries credentials or account bindings. Importing creates a new
   workspace and changes nothing else." | upstream · `D02:513`, verbatim (BQ-2 RULED; owner
   approval pending (#2701)) |
  | `e15.import.choose` | the picker's button, CMP-001 `secondary`, fronting the native input
   (`SCR-026/pick`) | "Choose file…" | upstream · `D02:513` |
  | `e15.import.drop_hint` | the drop zone's words, the button's `aria-describedby` | "or drop a
   workspace file here" | upstream · `D02:513` |
  | `e15.import.help` | the help line under the picker, in the button's `aria-describedby` after
   the drop words | "JSON, up to {size_mb} MB" · fixture "JSON, up to 2 MB" | new · PROPOSED; the
   limit is the tool's (§5.4) |
  | `e15.import.drop_active` | the drop zone's words while one file is dragged over
   (`SCR-026/drag-over`) | "Drop to check the file" | new · PROPOSED |
  | `e15.import.drop_rejected` | the drop zone's words while two files, or a file whose type is
   not JSON, are dragged over (`SCR-026/drag-over-rejected`) | "Drop one .json file" | new ·
   PROPOSED |
  | `e15.import.cancel` | the footer's first button on every import frame and the budget confirm's
   first; `Esc` and a press on the dialog's scrim are this Cancel | "Cancel" | registered ·
   CMP-043, CMP-044 |
  | `e15.import.checking` | the progress bar's `valueText` and the status line
   (`SCR-026/validating`) | "Checking {file}… step {i} of {n}" · fixture "Checking scalping.json…
   step 3 of 5" | adapted · `D02:515`, the step count added (DL-11) |
  | `e15.import.caption` | the preview table's caption, its counts first (`SCR-026/preview`,
   `SCR-026/preview-migrated`) | "Preview — {panels} and {layouts} to add · {dropped} dropped ·
   {remapped} remapped" · fixture "Preview — 7 panels and 2 layouts to add · 3 dropped · 1
   remapped" | new · PROPOSED (BQ-10 RULED) |
  | `e15.import.col.item` | the first column's header | "Item" | the ticket's columns (`BL:266`;
   BQ-10 RULED) |
  | `e15.import.col.type` | the second column's header | "Type" | the ticket's columns (`BL:266`;
   BQ-10 RULED) |
  | `e15.import.col.action` | the third column's header | "Action" | the ticket's columns
   (`BL:266`; BQ-10 RULED) |
  | `e15.import.col.reason` | the fourth column's header | "Reason" | the ticket's columns
   (`BL:266`; BQ-10 RULED) |
  | `e15.import.action.add` | the Action word after the `check` glyph | "Add" | the ticket's three
   words (BQ-10 RULED) |
  | `e15.import.action.drop` | the Action word after the `x-circle` glyph | "Drop" | the ticket's
   three words (BQ-10 RULED) |
  | `e15.import.action.remap` | the Action word after the `merge` glyph, kept for the one true
   remap (§4.2 row 4) | "Remap" | the ticket's three words (BQ-3, BQ-10 RULED) |
  | `e15.import.reason.unknown_kind` | the Reason of an unknown kind's Drop row, the kind by its
   stored name in the Item cell | "not available in this version" | the ticket's AC 3, verbatim
   (`BL:266`) |
  | `e15.import.reason.account` | the Reason of an account-scoped setting's Drop row | "workspaces
   never carry account bindings" | upstream · `D02:516` (BQ-3 RULED) |
  | `e15.import.reason.remap` | the Reason of the Positions pane's Remap row | "shows your own
   accounts" | new · PROPOSED (BQ-3 RULED) |
  | `e15.import.clash` | the line above the table when the name is taken (`SCR-026/preview`) |
   "Imported as {clash}: a workspace named {workspace} exists." · fixture "Imported as Scalping
   (2): a workspace named Scalping exists." | upstream · `D02:516` |
  | `e15.import.confirm` | the preview's primary; busy on `SCR-026/creating`; in place on
   `SCR-026/import-leg-lost` (§6) | "Import as new workspace" | upstream · `D02:516` |
  | `e15.import.close_view` | the creating frame's first button, which closes the view only
   (`15:468`), and the one button of `SCR-026/refused-unconfirmed` | "Close" | registered · CMP-043
   |
  | `e15.import.slow` | under the footer of `SCR-026/creating` after CMP-001's slow-path delay |
   "Still importing…" | new · PROPOSED (CMP-001's slow path, `15:48`; D09-D17) |
  | `e15.import.migrated` | CMP-028 `info` above the table (`SCR-026/preview-migrated`) |
   "Migrated from format version {from} to {to}." · fixture "Migrated from format version 1 to 2."
   | ruled · BQ-4 (6396085915), E15-S07's rule (`BL:1136`) |
  | `e15.import.caption_budget` | the over-budget preview's caption
   (`SCR-026/preview-over-budget`) | "Preview — {panels} and {layouts} to add. {layout} opens at
   about {estimate} ms per frame (estimated), over the {budget} ms budget." · fixture "Preview — 12
   panels and 1 layout to add. Wall opens at about 17.9 ms per frame (estimated), over the 16 ms
   budget." | new · PROPOSED (BQ-6 RULED) |
  | `e15.import.budget` | CMP-028 `warning` above the over-budget table | "{layout} opens with
   {panels}: about {estimate} ms per frame (estimated), over the {budget} ms budget." · fixture
   "Wall opens with 12 panels: about 17.9 ms per frame (estimated), over the 16 ms budget." | new ·
   PROPOSED (BQ-6 RULED) |
  | `layout.cost.import.title` | the stacked confirm's title (`SCR-026/budget-confirm`) | "Open
   {layout} with {panels}?" · fixture "Open Wall with 12 panels?" | adapted · `D03:629`, re-worded
   for an import; an A-row to E15-D03's deck (D09-A20) |
  | `layout.cost.import.body` | the stacked confirm's body | "Frame time now: {measured} ms per
   frame (p95, last 10 s, measured), about {fps} fps. With {layout}'s {panels}: about {estimate} ms
   (estimated), about {estfps} fps. Budget: {budget} ms ({budgetfps} fps). That is over the
   performance budget, so charts may stutter." · fixture "Frame time now: 11.8 ms per frame (p95,
   last 10 s, measured), about 60 fps. With Wall's 12 panels: about 17.9 ms (estimated), about 56
   fps. Budget: 16 ms (60 fps). That is over the performance budget, so charts may stutter." |
   adapted · `D03:630`, its consequence sentence verbatim; an A-row to E15-D03's deck (D09-A20) |
  | `layout.cost.import.confirm` | the stacked confirm's primary | "Import anyway" | ruled · BQ-6
   (6396085915), re-verbed from `D03:631` |
  | `e15.import.report.heading` | the report's heading (`tabindex="-1"`) and its region's name
   (`SCR-026/report`) | "Import report" | new · PROPOSED (BQ-12 RULED) |
  | `e15.import.report.done` | the success line, CMP-028 `success`, atop the report; the toast's
   line after a closed view (§7) | "Imported {clash}: {panels}, {layouts}, {dropped_items} dropped,
   {remapped} remapped." · fixture "Imported Scalping (2): 7 panels, 2 layouts, 3 items dropped, 1
   remapped." | adapted · `D02:520`, the remap count added (AC 4) |
  | `e15.import.report.caption` | the report table's caption | "Report — {panels} and {layouts}
   added · {dropped} dropped · {remapped} remapped" · fixture "Report — 7 panels and 2 layouts
   added · 3 dropped · 1 remapped" | new · PROPOSED (BQ-12 RULED) |
  | `e15.import.report.copy` | the report footer's first button, CMP-033 as a labelled button
   (D09-A8) | "Copy report" | new · PROPOSED (BQ-12 RULED) |
  | `e15.import.report.copied` | CMP-033's polite announcement after a copy | "Copied" |
   registered · CMP-033 (`15:366`) |
  | `e15.import.report.copy_failed` | `SCR-026/report`, spoken once when the browser refuses the
   clipboard | "Couldn't copy the report." | new · PROPOSED (§4.5; D09-D21) |
  | `e15.import.report.close` | the report's primary | "Close" | registered · CMP-043 |
  | `e15.import.report.view` | the action of the persistent CMP-045 `success` toast after the view
   was closed mid-send; it reopens the report (§3.5, §7) | "View report" | new · PROPOSED (H22's
   outcome surface, `S4:734`; D09-D18) |
  | `e15.import.review` | the action of the persistent CMP-045 `danger` toast when a refusal
   arrives after the view was closed mid-send; it reopens the refusal's frame (§3.5, §7) | "Review"
   | new · PROPOSED (H22's outcome surface, `S4:734`; D09-D18) |
  | `e15.import.choose_another` | the primary of every rejection and of `SCR-026/refused-server`,
   focused on arrival | "Choose another file" | upstream · `D02:517` |
  | `e15.import.rejected.version_newer` | the CMP-027 message (`SCR-026/rejected-version-newer`) |
   "This file was exported by format version {file} and can't be imported into format version
   {app}. Nothing was imported. Export it again from a version {app} app, or update this app." ·
   fixture "This file was exported by format version 2 and can't be imported into format version 1.
   Nothing was imported. Export it again from a version 1 app, or update this app." | adapted ·
   `D02:517` and `14:633`: "format version" names what is compared, the constructive sentence added
   (BQ-4 RULED; owner approval pending (#2701)) |
  | `e15.import.rejected.version_older` | the CMP-027 message (`SCR-026/rejected-version-older`) |
   "This file was exported by format version {file} and this app reads format version {floor} or
   later. Nothing was imported. Update the app that exported it, then export it again." · fixture
   "This file was exported by format version 0 and this app reads format version 1 or later.
   Nothing was imported. Update the app that exported it, then export it again." | new · PROPOSED
   (BQ-4 RULED; owner approval pending (#2701)) |
  | `e15.import.rejected.malformed` | the CMP-027 message, the key in mono
   (`SCR-026/rejected-malformed`) | "This isn't a workspace file: `{key}` is missing. Nothing was
   imported." · fixture "This isn't a workspace file: `layouts[1].grid_spec.root` is missing.
   Nothing was imported." | upstream · `D02:518` |
  | `e15.import.rejected.parse` | its variant: the text is not JSON | "This isn't a workspace
   file: it stops being valid JSON at line {line}. Nothing was imported." · fixture "This isn't a
   workspace file: it stops being valid JSON at line 212. Nothing was imported." | new · PROPOSED |
  | `e15.import.rejected.panes` | its variant: a layout over the panel limit | "This file has a
   layout with {n} panels; a layout holds at most {max}. Nothing was imported." · fixture "This
   file has a layout with 30 panels; a layout holds at most 16. Nothing was imported." | new ·
   PROPOSED; the limit `D02:133` |
  | `e15.import.rejected.layouts` | its variant: too many layouts | "This file has {n} layouts; a
   workspace holds at most {max}. Nothing was imported." · fixture "This file has 40 layouts; a
   workspace holds at most 32. Nothing was imported." | new · PROPOSED; the limit `22:8886` |
  | `e15.import.rejected.presets` | its variant: too many indicator presets | "This file has {n}
   indicator presets; a file may carry at most {max}. Nothing was imported." · fixture "This file
   has 240 indicator presets; a file may carry at most 200. Nothing was imported." | new ·
   PROPOSED; the limit `22:21422–21423` |
  | `e15.import.rejected.invalid` | a variant of `SCR-026/rejected-malformed`: a known key whose
   value is the wrong kind, or a key written twice (§5.4) | "This isn't a workspace file: `{key}`
   isn't valid. Nothing was imported." · fixture "This isn't a workspace file:
   `layouts[0].crosshair_sync` isn't valid. Nothing was imported." | new · PROPOSED (D09-D31) |
  | `e15.import.rejected.oversized` | the CMP-027 message (`SCR-026/rejected-oversized`) | "This
   file is {size} MB; the limit is {max} MB. Nothing was imported." · fixture "This file is 3.4 MB;
   the limit is 2 MB. Nothing was imported." | upstream · `D02:518` |
  | `e15.import.rejected.wrong_type` | the CMP-027 message, the file's name in mono
   (`SCR-026/rejected-wrong-type`) | "That isn't a JSON file ({name}). Nothing was imported. Choose
   a .json workspace file." · fixture "That isn't a JSON file (report.csv). Nothing was imported.
   Choose a .json workspace file." | new · PROPOSED |
  | `e15.import.rejected.depth` | the CMP-027 message (`SCR-026/rejected-nodes`) | "This file is
   nested too deeply: the limit is {max} levels. Nothing was imported." · fixture "This file is
   nested too deeply: the limit is 16 levels. Nothing was imported." | new · PROPOSED; the limit
   `22:19819` |
  | `e15.import.rejected.nodes` | its variant: too many values | "This file has more than {max}
   values: the limit is {max}. Nothing was imported." · fixture "This file has more than 10,000
   values: the limit is 10,000. Nothing was imported." | new · PROPOSED; the limit PROPOSED
   (D09-G5) |
  | `e15.import.nothing` | the first sentence of each refusal at the send
   (`SCR-026/refused-limit`, `SCR-026/refused-server`) | "Nothing was imported." | upstream ·
   `D02:517`; `D02:518` |
  | `e15.import.refused.limit` | its second sentence at the workspace limit
   (`SCR-026/refused-limit`) | "You have {max} workspaces, the most you can have. Delete one, then
   import again." · fixture "You have 32 workspaces, the most you can have. Delete one, then import
   again." | upstream · `D02:518` |
  | `e15.import.refused.server` | its second sentence when the server's re-check refuses the file
   (`SCR-026/refused-server`) | "The server didn't accept this file: `{key}` isn't valid." ·
   fixture "The server didn't accept this file: `layouts[0].panes[3].pane_config` isn't valid." |
   new · PROPOSED |
  | `e15.import.refused.store` | a variant of `SCR-026/refused-server`: its second sentence when
   the send fails without naming a field (§5.5) | "The workspace store didn't answer. Choose the
   file again in a moment." | new · PROPOSED (D09-D31) |
  | `e15.import.refused.size` | a variant of `SCR-026/refused-server`: its second sentence when
   the server answers `413`, the file larger than it takes (§5.5) | "The server didn't accept this
   file: it is larger than the server takes." | new · PROPOSED (D09-D31; the number is the
   server's, D09-G5) |
  | `e15.import.refused.unconfirmed` | the CMP-027 message when the send's answer never came
   (`SCR-026/refused-unconfirmed`) | "We couldn't confirm the import. Check your workspaces before
   importing again." | new · PROPOSED (D09-D33; D09-G1) |
  | `e15.import.shortened` | after a capped key or file name, in its accessible name only, never
   on screen (§5.5) | "(shortened)" | new · PROPOSED (D09-D27) |
  | `rbac.view_as` | Import…'s T2 reason while viewing as: the SCR-124 banner's node
   (`SCR-026/entry-view-as`) | "Read-only while viewing as {user}." · fixture "Read-only while
   viewing as alex." | registered · `E09D09:95` |
  | `rbac.permission` | Import…'s T2 reason without `workspaces:write`; the dialog's verb when
   that leg goes (`SCR-026/entry-permission`, `SCR-026/import-leg-lost`) | "Your role can't save
   workspaces." · template "Your role can't {verb}." | registered · `E09D09:89`, its verb "save
   workspaces" from `E09D09:114` |
  | `workspace.limit.count` | Import…'s T2 reason at the workspace limit (`SCR-026/entry-limit`) |
   "You have the most workspaces you can have." | E15's PROPOSED state key · `D02:674`; rendered by
   `D03:634` |
  | `ws.export.unstored` | Export…'s line on the viewer's unsaved default
   (`SCR-025/export-unavailable`) | "This workspace isn't saved." | upstream · `D03:625` |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 10.
   Design-system A-rows (`15`, PROPOSED)#1
@ ¶0 ‖ heading ‖ 1
  ## 10. Design-system A-rows (`15`, PROPOSED)
@ ¶1 ‖ paragraph ‖ 1
  This PR edits no `15` entry (BQ-1 RULED). Each row is copy-ready for the catalogue's owner: the
   old text is verbatim at the base, a fragment of the line named and unique in it, and the new
   text replaces exactly that fragment, the rest of the line unchanged. Text inside a
   double-backtick span is the catalogue's own source, its single backticks included; in the tables
   `\|` stands for `|`. The ids run D09-A1 to D09-A11 here and go on in §11; §12's hand-offs name
   each row's owner.
@ ¶2 ‖ table ‖ 1
  | Id | `15` entry · field (line) | Old (verbatim) | New (PROPOSED) | Basis |
  | --- | --- | --- | --- | --- |
  | D09-A1 | CMP-067 · Purpose (`15:692`); Props (`15:693`) | `**Purpose**: CSV/JSON import
   (journal import, rule import/export).` · ``- **Props**: `accept` · `onFiles` · `multiple?`.`` |
   `**Purpose**: CSV/JSON import (journal import, rule import/export, workspace import).` · ``-
   **Props**: `accept` · `onFiles` · `multiple?` · `label` (the visible text of the real `<button>`
   that fronts the native input, kept `hidden` and opened by the button's click, e.g. "Choose
   file…"; the input is labelled by it) · `dropHint?` (the drop zone's words, the button's
   `aria-describedby`, e.g. "or drop a workspace file here") · `help?` (the line under it, in the
   same `aria-describedby` after the drop words) · `maxBytes?` (a picked or dropped file over it is
   refused from its size before a byte of it is read; the host shows its error) · `error?` (the
   host's message node, first in the button's `aria-describedby`; the input stays live).`` |
   SCR-026's picker and drop zone (`SCR-026/pick`; BQ-9, BQ-13 RULED; `D02:513`); the drop target
   described the same way on SCR-089 (`E36D03:339`); `14:636` |
  | D09-A2 | CMP-067 · A11y (`15:694`) | ``- **A11y**: native `<input type=file>` under the hood
   (drag-and-drop is additive, never the only path), fully keyboard-operable via the native file
   picker.`` | ``- **A11y**: native `<input type=file>` under the hood (drag-and-drop is additive,
   never the only path), fully keyboard-operable via the native file picker: a real `<button>`
   showing its `label` opens it on `Enter` or `Space`, and a chosen file returns focus to that
   button; the drop zone has no role, no name and no Tab stop of its own, and a drop only adds to
   the input; a drop of more files than `multiple` allows, or of a type outside `accept`, is
   refused in words ("Drop one .json file"), never by colour alone; a drop that carries no file, or
   lands outside the zone, is ignored: nothing is read or fetched and no address is followed; the
   host's error is first in the button's `aria-describedby` and announced once, politely.`` |
   `05:35`; `05:101`; `14:636`; `SCR-026/drag-over-rejected`; BQ-13 RULED |
  | D09-A3 | CMP-067 · Tokens (`15:695`) | ``- **Tokens**: `color.border.dashed`.`` | ``-
   **Tokens**: the zone's edge `color.border.default` at `border.hairline`, solid, `radius.card`,
   padding `space.inset.xl`, its words `type.ui.body` + `color.text.secondary`; drag-over: the edge
   `color.border.selected` and the fill `color.surface.hover`, the words changed; the button a
   CMP-001 `secondary`. (Replaces `color.border.dashed`, which is not a shipped token; a dashed
   edge is kept for estimated and absent data.)`` | the re-bind E36-D03 reported for the same entry
   (`E36D03:272`); §8 rows 22 and 24 |
  | D09-A4 | CMP-067 · Storybook (`15:696`); Tests (`15:697`) | `- **Storybook**: Default,
   DragOver, Error.` · `- **Tests**: unit, visual, axe, keyboard-only file selection test.` | `-
   **Storybook**: Default, Focused, WithHelp, DragOver, DragOverRejected, Validating, Error,
   DisabledWithReason, Reflow200.` · ``- **Tests**: unit, visual, axe, keyboard-only file selection
   test, the drop zone never in the Tab order, a drop refused by type or by count in words, a file
   over `maxBytes` refused before it is read.`` | the ticket's DoD, CMP-067's Storybook list agreed
   with FE (`BL:266`; the owner's agreement stands in, #2701); DL-14; DisabledWithReason is a
   host's T2 on the button, which SCR-026 never needs (§6) |
  | D09-A5 | CMP-049 · Tokens (`15:531`) | `` odd `color.surface.canvas`, even
   `color.surface.raised` `` | `` odd `color.surface.canvas` (inside a dialog, the dialog's own
   `color.surface.overlay`), even `color.surface.raised` `` | the preview and the report sit on the
   dialog's surface (§4; §8 rows 1, 3 and 21) |
  | D09-A6 | CMP-027 · A11y (`15:306`) | `` `live` overrides it: `polite` for an in-panel load
   failure, `` | `` `live` overrides it: `polite` for an in-panel load failure or for a file
   refused inside a dialog, its input above it still live and the refused verb absent (SCR-026's
   rejections), `` | §5.2; slice 4's H37 (`S4:919`); BQ-11 RULED |
  | D09-A7 | CMP-028 · A11y (`15:317`) | `` `live` overrides the default (`off` renders no live
   role, for a banner whose announcement another region makes); `` | `` `live` overrides the
   default (`off` renders no live role, for a banner whose announcement another region makes; a
   standing statement read in place and never announced, such as an import's trust note, is
   `live="off"` with `role="note"`, its one line `type.ui.body` + `color.text.primary`); `` |
   SCR-026's trust note (`D02:513`; BQ-2 RULED); E36-D03's privacy note in the same form
   (`E36D03:153–155`); §8 row 12 |
  | D09-A8 | CMP-033 · Props (`15:364`); Storybook (`15:368`) | ``- **Props**: `value: string` ·
   `label` (a11y name) · `onCopied?`.`` · `- **Storybook**: Default, CopiedState.` | ``- **Props**:
   `value: string` · `label` (a11y name) · `onCopied?` · `display?: "icon"\|"button"` (default
   `icon`; `button` shows the label as a CMP-001 `secondary`, for a dialog's footer such as
   SCR-026's Copy report; the copy and its "Copied" announcement are unchanged).`` · `-
   **Storybook**: Default, CopiedState, AsButton.` | `SCR-026/report`'s footer (BQ-12 RULED);
   CMP-033's announcement (`15:366`) |
  | D09-A9 | CMP-044 · Tokens (`15:479`) | ``Confirm a CMP-001 `danger`
   (`color.status.danger.default`, `color.text.on-action`),`` | ``Confirm a CMP-001 `danger`
   (`color.status.danger.default`, `color.text.on-action`), or a CMP-001 `primary` for a
   measured-cost confirm, which destroys nothing (US-LAY-001's Add panel anyway, SCR-026's Import
   anyway),`` | `SCR-026/budget-confirm` (BQ-6 RULED); E15-D03's cost confirm (`D03:629–631`);
   E15-D08's merged row on the same clause composes with it |
  | D09-A10 | `tools/contrast/pairs.mjs` and `tools/contrast/encodings.json` (their owner; not
   `15`) | — | register the twelve PROPOSED gated pairs of §8 — rows 4, 6, 9, 10, 11, 13, 16, 17,
   19, 22, 27 and 28 — and add the preview's and the report's Add / Drop / Remap encoding, its
   non-colour channel the word and the glyph's shape | `16:456`; §8; a design PR never edits
   `tools/` |
  | D09-A11 | CMP-036 · Tokens (`15:395`) | ``- **Tokens**: `space.row.*`,
   `font.size.body/label`.`` | ``- **Tokens**: `space.row.height.comfortable` or
   `space.row.height.compact` by density; the label `type.ui.label` + `color.text.secondary`, the
   value `type.ui.body` + `color.text.primary`. (Replaces the wildcard `space.row.*` and
   `font.size.body/label`, which name no shipped token.)`` | the export's Included and Excluded
   lists (`SCR-025/export-preview`); the semantic sets in `packages/ui/tokens` |
@ ¶3 ‖ paragraph ‖ 1
  **No A-row, and why.** CMP-001 Button: its `loading` keeps the label with `aria-busy`, and its
   T2 is E09-D09's (`15:48–57`). CMP-019 Icon: `x-circle` is already PROPOSED for E05-T06
   (`15:307`) and `merge` by E11's icon batch, and this spec adds no glyph. CMP-023 Progress Bar:
   determinate, `valueText`, never a live region, as catalogued (`15:262–270`). CMP-043 Dialog:
   `lg` and `md` fit (`15:466`), and its focus, `Esc` and scrim rules hold as catalogued
   (`15:468`). CMP-045 Toast: the report is never a toast; the one toast here, after a closed view,
   is persistent because it carries an action, as catalogued (`15:483–490`). CMP-068
   CopyableCodeBlock: unused, because no frame shows the file's text and Condition 1 forbids
   echoing it. CMP-079 RbacGate: T2 as catalogued (`15:811–819`). CMP-234 ValidationPanel: unused,
   because its entries anchor to rule rows and nodes (`15:2738–2742`) while a refusal here names
   one key in one message and the report is a table; E15-S07 names it for the report (`BL:1136`), a
   C-row (D09-C10).
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 11. `14`
   A-rows and the pointer lines#1
@ ¶0 ‖ heading ‖ 1
  ## 11. `14` A-rows and the pointer lines
@ ¶1 ‖ paragraph ‖ 1
  **Applied by this PR, content only (BQ-1 RULED).** Two pointer lines, each right after its
   screen's sign-off checklist — after SCR-025's (`14:627`) and after SCR-026's (`14:640`) — each
   starting `- **Design (hi-fi):** [E15-D09.md](../design/E15/E15-D09.md)`: SCR-025's points at §2,
   the export; SCR-026's at §3 to §5, the import. The tool checks on every run that each sits in
   the run of pointer lines right after its checklist, so a later E15-D08 pointer may sit beside
   ours. Nothing else in `14` is edited: both checklists stay verbatim, and §13 maps every item,
   the version-mismatch item to its refusal frame.
@ ¶2 ‖ paragraph ‖ 1
  **Copy-ready for the catalogue's owner, PROPOSED** (old text verbatim at the base, a whole line
   or a fragment of it as named; a fragment in double quotes is the catalogue's own words; in the
   tables `\|` stands for `|`). Where E15-D02 already proposed the same line's change — its A-10 on
   SCR-026's Type, Validation and checklist (`D02:823`), pending — the row below is the one text
   that does both, so the owner applies one, not two.
@ ¶3 ‖ table ‖ 1
  | Id | `14` entry · field (line) | Old (verbatim) | New (PROPOSED) | Basis |
  | --- | --- | --- | --- | --- |
  | D09-A12 | SCR-026 · Type (`14:632`), a fragment | "(panels added, symbols referenced, accounts
   remapped)" | "(Choose file… or a drop; five checks in a worker; then a table of what is added,
   dropped and remapped — unknown panel kinds and account-scoped settings dropped and listed, never
   remapped — before Import as new workspace creates a new workspace)" | BQ-3, BQ-5 and BQ-9 RULED;
   it does E15-D02's A-10 for this line (`D02:823`); `11:2868` |
  | D09-A13 | SCR-026 · Validation (`14:633`), two fragments | "This layout was exported by v2 and
   can't be imported into v1." · "inaccessible account references remap to the user's default
   account" | "This file was exported by format version 2 and can't be imported into format version
   1. Nothing was imported. Export it again from a version 1 app, or update this app." ·
   "account-scoped settings are dropped and listed, never remapped, and no account the importer
   cannot see is named; an older format version this app still reads is migrated forward and said
   so" | BQ-3 and BQ-4 RULED, owner approval pending (#2701); `11:2868`; `11:2871`; it does
   E15-D02's A-10 for this line (`D02:823`) |
  | D09-A14 | SCR-026 · Components (`14:634`), the whole line | `- **Components:** CMP-001 Button,
   CMP-027 ErrorState / InlineError, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-067 FileDrop /
   Import control.` | ``- **Components:** CMP-001 Button, CMP-019 Icon (`lock`, `check`,
   `x-circle`, `merge`), CMP-023 Progress Bar, CMP-027 ErrorState / InlineError, CMP-028 Callout /
   Banner, CMP-033 CopyButton, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-049 Table, CMP-067
   FileDrop / Import control, CMP-079 RbacGate.`` | the frames of §3 to §5; an entry that shows a
   T2 control lists CMP-019's `lock` and CMP-079 (E15-D02 §8.1, `D02:635–674`; §6) |
  | D09-A15 | SCR-026 · A11y (`14:636`), the whole line | `- **A11y:** File input has a visible
   label and an accessible drop zone with a keyboard alternative; the import diff is a table, not a
   canvas; validation errors are listed as text with the offending key named.` | `- **A11y:** File
   input has a visible label (Choose file…, a real button) and a drop zone with a keyboard
   alternative, the drop zone never a Tab stop; the import diff is a table, not a canvas, its
   caption stating the counts first and its Action a word with a decorative glyph; validation
   errors are listed as text with the offending key named, announced politely, the input staying
   live; the report is a persistent region with Copy report; every string from the file is shown as
   text, capped.` | the ticket's Accessibility notes (`BL:266`); BQ-9, BQ-10, BQ-12 and BQ-13
   RULED; §5, §7 |
  | D09-A16 | SCR-026 · Analytics/audit (`14:638`), the whole line | ``- **Analytics/audit:**
   `layout.imported`, `layout.import_rejected` with `{reason}` (analytics).`` | ``- **Analytics:**
   `layout.imported` `{panelCount, droppedCount, remappedCount, schemaVersion}`,
   `layout.import_rejected` `{reason: version-newer \| version-older \| malformed \| oversized \|
   wrong-type \| budget-exceeded}` (analytics, never audit; no property carries anything from the
   file).`` | the ticket's Observability (`BL:266`); D09-G13 maps E15-S07's `size \| parse \|
   schema \| version \| semantic` (`BL:1136`); §5.5 |
  | D09-A17 | SCR-026 · checklist (`14:640`), a fragment | "version-mismatch state ('exported from
   a newer version - 2 panels will be dropped')" | "version-mismatch state (a newer format version
   refused with both versions and a way on, nothing imported, no partial apply; an older one this
   app still reads migrated and said so) [ ] account-scoped elements dropped and listed in the
   preview and the report, naming no account the importer cannot see" | BQ-3 and BQ-4 RULED, owner
   approval pending (#2701); `11:2871`; E15-D02 drew the refusal, not the checklist's words
   (`D02:732`), and its A-10 asked for this item (`D02:823`) |
  | D09-A18 | SCR-025 · Type (`14:618`), a fragment | "export as template" | "Export… (a workspace
   file, E15-D09 §2)" | `exportWorkspace` exports a workspace file, never a template (`22:12843`);
   BQ-7 RULED; E15-D08's merged row rewrites the whole line and composes with this one |
  | D09-A19 | SCR-089 · a new line after its checklist (`14:1999`) | — | `- **Reuse (E15-D09):**
   [E15-D09.md](../design/E15/E15-D09.md) §3 to §7: a file that crosses the trust boundary is
   chosen through a real button fronting the labelled native input, the drop zone never a Tab stop;
   it is checked in a fixed order and the server checks it again, as the dialog says; a preview
   table shows drops and remaps first; a refusal names its key in mono, capped, and offers no
   import verb; the report is a persistent region with Copy report; every string from the file is
   shown as text, capped.` | the ticket's reuse note (DL-21; DoD-10); E36-D03 already draws
   SCR-089's drop zone and pre-check table (`E36D03:153–155`), so this line points and never
   redraws |
@ ¶4 ‖ paragraph ‖ 1
  **The reuse note for SCR-089** (DL-21; DoD-10; the ticket's Out of scope). SCR-089, rule import
   and export (`14:1990`), is a sibling surface that E36-D03 already draws, with CMP-067's native
   input first and its drop target described by its words (`E36D03:153–155`; `E36D03:339`), so
   D09-A19 points at this spec and changes nothing drawn there. Five things carry over as they
   stand: the real button with its visible label in front of the native input; the drop zone that
   only adds to it and is never a Tab stop; the checks in a fixed, cheapest-first order, with the
   server's own check stated on the checking step; the refusal that names its key in mono, capped,
   and never offers to bring in part of a file; every string from the file shown as text only,
   cleaned and capped (§5.5). Two do not: SCR-089 accepts or skips each rule on its own (`14:1999`)
   where a workspace is whole or nothing, and a rule bundle's version and account references follow
   E36's contract, not `WorkspaceBundle`'s.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 12. A, C and
   G rows, and the hand-offs#1
@ ¶0 ‖ heading ‖ 1
  ## 12. A, C and G rows, and the hand-offs
@ ¶1 ‖ paragraph ‖ 1
  Every row is PROPOSED to its owner, and none is applied by this PR: a contract changes
   contract-first in its owner's PR (C-6.1), `14` and `15` through the A-rows of §10 and §11, and a
   ruling stays the orchestrator's (6396085915) or the owner's (#2701). E15-S07 receives D09-G1 to
   D09-G8, D09-G13 and D09-G14 by the hand-off row below (BQ-3 RULED).
@ ¶2 ‖ paragraph ‖ 1
  **G — gaps their owners close.**
@ ¶3 ‖ table ‖ 1
  | Id | Gap | What closes it | Owner |
  | --- | --- | --- | --- |
  | D09-G1 | **The atomic import.** No operation takes a bundle: `exportWorkspace`'s description
   names `POST /workspaces` with `from_bundle` (`22:12848`), a field no input schema has, and `22`
   says so (`22:21419`); `createWorkspace` refuses a body over 4 KiB (`22:8691`) while a file may
   be 2 MB; and an import built in the client from `createWorkspace` and then `createLayout` for
   each layout is not atomic (`FL:171`), the partial import the ticket forbids (`11:2871`) | one
   operation, contract first, that takes the checked bundle and creates the workspace with all its
   layouts, chart templates, drawings and indicator presets in one transaction, or creates nothing;
   it re-runs every check of §3.4 on the server, admits a 2 MB body, returns the name it gave and
   the items it dropped, and refuses with the problem types of D09-G7; it takes an
   `Idempotency-Key`, as `createWorkspace` does (`22:8692`), so a send repeated after a lost answer
   never imports twice (`SCR-026/refused-unconfirmed`); the import is built on it and never before
   it (§3.5, §5.5) | `22`'s owner, contract first (C-6.1); E15-S07 builds on it |
  | D09-G2 | `schema_version` is a free string (`22:21408`): no current value, no order, no oldest
   version still read, no outcome for a value that is absent or malformed; E15-S07 names
   `schemaVersion` and `appVersion` in another shape (`BL:1136`) | the format (PROPOSED: a whole
   number written in decimal, §5.3), the current value 1, the order, the oldest version still read,
   the outcome for an absent or malformed value (a schema failure that names the key) and one
   casing; the characters a file name may carry for it (§2.4); and one shape per readable version,
   so the schema step reads a file against its own version's shape and never shadows the version
   outcome (§3.4) | `22`'s owner; E15-S07 |
  | D09-G3 | Account-scoped elements: no bundle schema has an account field and `PaneConfig`
   forbids account ids (`22:20031`), so a strict server refuses a file that carries one whole
   (C-6.3; SR-040, `04:855`), while the story wants it dropped with a clear report (`11:2868`);
   `14:633`'s "the user's default account" names nothing a workspace has | the contract's rule: the
   server drops an account-scoped setting at export and again at import and names it in its answer
   (E15-S07, `BL:1136`), or it refuses the whole file, in which case the preview's Drop row is a
   prediction and the outcome is `SCR-026/refused-server`; no default account for a workspace |
   `22`'s owner; E15-S07 |
  | D09-G4 | `WorkspaceBundle` and `ChartTemplateInput` are not closed, and a template's `config`
   is open (`22:21402–21423`), against C-6.3 and SR-040 (`04:855`) | `additionalProperties: false`
   on both and a closed `config`; the export's check (§2.3) and the import's schema step then read
   closed schemas | `22`'s owner |
  | D09-G5 | The limits the contract does not carry: the file's size (2 MB, E15-S07's default,
   `BL:1136`), the count of values (10,000, PROPOSED), the `layouts` array (32 a workspace in the
   store, `22:8886`, none in the bundle), the `drawings` and `chart_templates` arrays, and a pane
   kind's length (32 here, PROPOSED from the setting keys' pattern of `22:20041`, since `PaneKind`
   has none, `22:19971`); and the two directions disagree: an export carries every live preset, 500
   a user and never truncated, while an import takes 200 (`22:21422–21423`), and an export's size
   has no cap while an import's is 2 MB | the caps in `22`, the same numbers in both directions, or
   an export that warns when its file would be refused (§2.3's warning line meanwhile) | `22`'s
   owner; E15-S07 |
  | D09-G6 | References inside the bundle point at the exporter's ids: a drawing's `layout_id`
   (`22:20390`), a pane's `chart_template_id` (`22:20066`) and its `indicator_preset_ids`
   (`22:20072`), each refused today on a create | a rule that the server makes new ids for
   everything it imports and re-points each reference, never honouring the exporter's (E15-X01,
   `BL:721`), and drops a reference it cannot resolve, with its report | `22`'s owner; E15-S07 |
  | D09-G7 | No problem type names a newer or an older format version, a wrong file type, or a
   store that does not answer at the import: today the workspace routes refuse with
   `validation_failed` and `limit_reached` (`22:19819`; `22:8686`), so these refusals are the
   client's; the budget is a confirm and needs none | a problem type, or an `errors[]` rule, for
   each, so the server's refusal at the send maps to §9's keys and never shows its own words
   (`15:306`) | `22`'s owner; E15-S07 |
  | D09-G8 | E15-S07 wants the file to carry its own report of what the export dropped
   (`BL:1136`); `WorkspaceBundle` has no field for it (`22:21402–21423`) | a report field in the
   bundle that the preview's Drop rows read, or the import's answer naming what the server dropped
   | `22`'s owner; E15-S07 |
  | D09-G9 | The ticket cites a workspace document in `24-internal-schemas.md` (`BL:266`), and
   `24` has none | the document in `24`, or the ticket's reference corrected to `22`'s
   `WorkspaceBundle` | `24`'s owner; the owner |
  | D09-G10 | `workspace.exported` sits on SCR-025's Audit line (`14:621`), while E15-D01's locked
   list keeps layout events analytics, never audit (`D02:84`), and E15-X01 asks that the export be
   audited (`BL:721`); an export performed while viewing as another user, T1 by BQ-7, is the case
   the audit question is about | one class for the event; this spec draws it as analytics with
   counts only (§2.4) | the owner; E15-X01; `14`'s owner |
  | D09-G11 | The data class and the sharing claim: `exportWorkspace`'s description makes the
   sharing claim (`22:12846`), while `21:5079` classes the pane columns P0 and E15-X01 classes the
   file user-confidential (`BL:721`) | `22`'s description drops the sharing claim and names the
   class; this spec writes the caveat instead (BQ-2 RULED) | `22`'s owner; the owner (#2701) for
   the class |
  | D09-G12 | No E15 STRIDE model exists (C-12.1), so no `SR-E15-nn` can be cited; E15-X01 is its
   ticket (`BL:700`) | E15-X01's model; until it lands, the review of the trust copy cites `04`'s
   SR-040, SR-097 and SR-127 | E15-X01; the security program's owner |
  | D09-G13 | Two lists of reasons: the ticket's six (`version-newer`, `version-older`,
   `malformed`, `oversized`, `wrong-type`, `budget-exceeded`) against E15-D02's and E15-S07's five
   (`size`, `parse`, `schema`, `version`, `semantic`; `FL:170`; `D02:522`); and two sets of event
   fields, `panelCount` and the rest against `{panes, dropped, migratedFrom}` (`BL:1136`) | BQ-11's
   alias table in E15-S07's Observability: `version-newer` and `version-older` are `version`;
   `malformed` is `parse` or `schema`, the depth and the count of values `parse`; `oversized` is
   `size`; `wrong-type` is `parse`; `budget-exceeded` is `semantic`; one name per field | E15-S07 |
  | D09-G14 | The file-name slug rule: whoever names the file applies it (BQ-8 RULED the pattern)
   | §2.4's rule, in the client or in E15-S07's export | E15-S07 |
  | D09-G15 | An export carries the caller's whole live preset library, at most 500 and never
   truncated (`22:21417–21419`), not only the presets this workspace's panes use, while the
   Included list's "3 indicator presets" reads as the workspace's own | the owner (#2701) chooses:
   the Included list says "all 3 of your indicator presets", or the bundle carries only the presets
   the panes reference (`22`'s owner) | the owner (#2701); `22`'s owner |
@ ¶4 ‖ paragraph ‖ 1
  **C — contradictions, each with its owner.**
@ ¶5 ‖ table ‖ 1
  | Id | Contradiction | Owner |
  | --- | --- | --- |
  | D09-C1 | the ticket's deliverable path `docs/design/specs/e15-workspace-import-export.md`
   (`BL:266`) against this file beside its E15 siblings (`14:639`; the first deviation; BQ-1 RULED)
   | the owner |
  | D09-C2 | the ticket's branch `design/e15-workspace-import-export-hifi` against
   `design/e15-d09-hifi` (C-4.4; the second deviation; BQ-1 RULED) | the owner |
  | D09-C3 | the ticket's Included list names densities, which `WorkspaceBundle` does not hold
   (`22:21402–21423`; `D02:507`) (the third deviation; BQ-2 RULED) | the owner |
  | D09-C4 | BQ-10 RULED a symbol cap of 16 from the pattern's `{2,16}`; a symbol is at most 20
   characters with its `USDT` (`22:20057`), so the cap here is 20 (the fourth deviation; D09-Q1) |
   the orchestrator |
  | D09-C5 | E15-D02's sentence "Never included: API keys or tokens, account or trade-group ids,
   user ids, P&L figures, positions or orders." (`D02:511`) is extended by BQ-2's to name
   credentials, accounts, the environment binding and the alert and rule bindings (AC 1): an
   extension, not a contradiction, and E15-D02's sentence is never shown on a frame | E15-D02, at
   its next revision |
  | D09-C6 | `D02:516`'s reason "not known to this version" against AC 3's "not available in this
   version" (`BL:266`) | E15-D02, at its next revision |
  | D09-C7 | `14:640`'s item "version-mismatch state ('exported from a newer version - 2 panels
   will be dropped')" against US-LAY-007's refusal (`11:2871`) and AC 2: drawn as the refusal
   (§13), and D09-A17 rewrites the item | `14`'s owner |
  | D09-C8 | `14:632`'s "accounts remapped", `14:633`'s "inaccessible account references remap to
   the user's default account" and AC 4's "remapped to the importer's default" against US-LAY-007's
   drop (`11:2868`) and BQ-3 RULED; D09-A12 and D09-A13 rewrite both lines | `14`'s owner; the
   owner (#2701) |
  | D09-C9 | the ticket's risk "R13 Sharing abuse" (its `risk` field, `BL:242–259`), which E15-X01
   carries too (`BL:700`), against the register's R13, "Team & knowledge" (`32:47`) | the plan's
   owner |
  | D09-C10 | CMP-234 ValidationPanel, which the ticket and E15-S07 name for the report
   (`BL:1136`), anchors its entries to rule rows and nodes (`15:2738–2742`); the report here is a
   region with a table (BQ-12 RULED) | E15-S07's owner; the design system's owner |
  | D09-C11 | `04:1182` marks a Viewer ✔(own) on saving layouts against `04:1141`, where a Viewer
   holds no `workspaces:write`, and E15-D01's locked list (`D02:84`); this spec draws the Viewer's
   Import… in T2, and the server enforces either way (C-12.4) | `04`'s owner |
  | D09-C12 | a refusal at the send speaks politely here (§7), against slice 4's conventions 33,
   which speaks a refusal at its point of action assertively (`S4:140`) | E05-D02's owner |
  | D09-C13 | `D02:515` names the check's steps in its line (size, format, schema, version,
   panels); the value text here counts them instead, because "schema" and "registry" are not a
   trader's words (§3.4) | E15-D02, at its next revision |
  | D09-C14 | the ticket's `version-older` as a rejection reason (`BL:266`) against E15-S07's
   older file migrated forward (`BL:1136`): reconciled by BQ-4 RULED, where `version-older` names
   only a file older than the oldest version this app still reads | E15-S07, whose Observability
   gains `version-older` |
  | D09-C15 | the ruled BQ drafts' copy, refined here and PROPOSED: BQ-11's older refusal ended
   "Open it in a version 1 app and export it again.", which a file older than every format version
   1 app reads cannot follow, so it reads "Update the app that exported it, then export it again.";
   BQ-5's panes sentence named the layout, a string from the file, so it names the count alone;
   BQ-6's budget sentence said 16.7 ms where C-14.2's budget is 16 ms; BQ-10's caption and BQ-12's
   success line counted 2 dropped where the tool's fixture drops 3 | the orchestrator (6396085915)
   |
  | D09-C16 | SCR-025's "export as template" (`14:618`) against `exportWorkspace`, which exports a
   workspace file (`22:12843`); D09-A18 | `14`'s owner |
  | D09-C17 | the ticket's 30-panel file (`BL:266`), meant for the budget's confirm, holds more
   panes than the 16 a layout holds (`D02:133`), so it is the panes variant of
   `SCR-026/rejected-malformed`, never the budget (BQ-5 and BQ-6 RULED) | the owner |
  | D09-C18 | the ticket's Scope lists intervals among what the export preview enumerates
   (`BL:266`), against E15-D02's Included sentence (`D02:511`), in which a panel's interval is one
   of "each panel's settings": the sentence is kept as E15-D02 wrote it (the fifth deviation; BQ-2
   RULED: the Included list names only what the bundle holds) | the owner |
  | D09-C19 | BQ-13's draft, ruled as proposed, named a target of at least 44 px comfortable and
   24 compact; the design system's controls are `size.control.height`, 32 px comfortable and 24 px
   compact, and `05:100`'s floor is 24 px (`size.target.min`), which every target here meets (§3.2)
   | the orchestrator (6396085915) |
@ ¶6 ‖ paragraph ‖ 1
  **A — amendments to other specs.** D09-A1 to D09-A11 are §10's (`15` and `tools/contrast/`) and
   D09-A12 to D09-A19 are §11's (`14`); the three below go to E15 specs: D09-A20 to merged E15-D03,
   D09-A21 to merged E15-D08 (`fb1b4804`) and D09-A22 to merged E15-D03 and to merged E15-D05
   (`01356263`), named only and never cited by line.
@ ¶7 ‖ table ‖ 1
  | Id | Amendment | Owner |
  | --- | --- | --- |
  | D09-A20 | E15-D03's deck gains the import's three cost strings, adapted from
   `layout.cost.title`, `.body` and `.confirm` (`D03:629–631`): `layout.cost.import.title` "Open
   {layout} with {panels}?", `layout.cost.import.body`, its measured and estimated sentence with
   the import's clause (§9), and `layout.cost.import.confirm` "Import anyway" (BQ-6 RULED) |
   E15-D03, at its next revision |
  | D09-A21 | SCR-025's Share section: its Export… opens this spec's export dialog (§2.2), and its
   help line names what the file leaves out in BQ-2's classes, or points at the Excluded list, and
   never makes the sharing claim | E15-D08 (merged, `fb1b4804`) |
  | D09-A22 | Import… as an item of the rail's workspace menu (SCR-011), beside Export…, opening
   the same empty dialog (§3.2; BQ-9 RULED): E15-D03's R-5 (`D03:564`) gains the rail's row, and
   the rail's menu gains the item | E15-D03, at its next revision; E15-D05, the rail's owner
   (merged, `01356263`) |
@ ¶8 ‖ paragraph ‖ 1
  **Q — open questions; the default built is named.**
@ ¶9 ‖ table ‖ 1
  | Id | Question | Built now | Owner |
  | --- | --- | --- | --- |
  | D09-Q1 | the symbol cap: BQ-10's 16, or the contract's 20 (`22:20057`)? | 20, the contract's
   (the fourth deviation) | the orchestrator |
  | D09-Q2 | where a browser has no save picker, does the download hand-off count as the save, for
   the completion step and for `workspace.exported`? | yes: the hand-off is the only answer the
   page gets (§2.4) | the owner; E15-S07 |
  | D09-Q3 | CMP-036 for the export's lists: an A-row for a list value and a stacked layout, or
   another list atom? | two CMP-036 rows in one `dl`, each value a `ul` (§2.3); D09-A11 re-binds
   its tokens (`15:395`) | the design system's owner |
  | D09-Q4 | the desktop shell's save: does its renderer reach a save picker, or does it need a
   save bridge that returns the base name only? | the platform's save sheet, the page learning the
   base name only (§2.4) | the desktop shell's owner |
  | D09-Q5 | the schema step reads `schema_version` from the envelope ahead of its shape rules, so
   a newer or an older file meets its version refusal and never a shape failure: confirmed? | yes
   (§3.4, step 3; §5.3) | the orchestrator |
  | D09-Q6 | the trust note's "Importing creates a new workspace and changes nothing else." stands
   beside Add rows for indicator presets, chart templates and drawings, which join the importer's
   own libraries (`22:21422–21425`, counted against the 500-preset cap): is the sentence kept word
   for word? | the ruled sentence, verbatim (BQ-2 RULED) | the owner (#2701) |
  | D09-Q7 | the newer refusal's ruled way on, "Export it again from a version 1 app, or update
   this app.", prints the format number as an app's version; the alternative "Export it again from
   an app that writes format version 1, or update this app." names what is compared | the ruled
   sentence (BQ-4 RULED) | the owner (#2701) |
@ ¶10 ‖ paragraph ‖ 1
  **Hand-offs.** E15-D03 and E15-D06 are merged (`c4989493`, `6e2c1211`), and E15-D04 (`c73aec08`)
   is pinned with nothing taken from it; E15-D08 (#4503) is merged (`fb1b4804`) and named only.
   Each row is a PROPOSED hand-off for its owner to take or refuse.
@ ¶11 ‖ table ‖ 1
  | To | Takes from this spec | State |
  | --- | --- | --- |
  | E15-S07 (the import and export story) | D09-G1 to D09-G8, D09-G13 and D09-G14 (BQ-3 RULED);
   D09-C10, D09-C14; the five steps and their limits (§3.4, §5.4); the alias table (D09-G13) | — |
  | `22`'s owner | D09-G1, the atomic import with its `Idempotency-Key`, contract first (C-6.1),
   with D09-G2 to D09-G8, D09-G11 and D09-G15 | — |
  | E15-D08 (SCR-025 settings) | Export… in its Share section opening §2's dialog (BQ-7 RULED);
   D09-A21; if E15-D08 changes the entry, §2.2 follows it | merged (`fb1b4804`) |
  | E15-D03 (SCR-020 chrome) | D09-A20, D09-A22; Import… in "+" and Export… in `[⋯]` keep their
   keys (§6) | merged |
  | E15-D05 (SCR-011 rail) | D09-A22: Import… in the rail's workspace menu | merged (`01356263`) |
  | E15-X01 (STRIDE) | D09-G10 with the export under view-as, D09-G11, D09-G12; the four hazards
   of §1.2 as its starting list | — |
  | E15-D14, E15-D15, E15-D16 | the motion of both dialogs (out of scope here); §7's keyboard
   model and desk pass for the screen-reader script; the frames, the deck and the G-rows for the
   hand-off pack | after this spec |
  | SCR-089's owner (E35, E36) | the reuse note (D09-A19, §11) | — |
  | the design system; `14`'s owner; `24`'s owner; `04`'s owner | D09-A1 to D09-A11, D09-Q3;
   D09-A12 to D09-A19; D09-G9; D09-C11 | — |
  | the desktop shell's owner | D09-Q4 | — |
  | the orchestrator; the owner (#2701) | D09-Q1, D09-Q5, D09-C4, D09-C15, D09-C19; the
   owner-level questions BQ-2, BQ-3 and BQ-4, with D09-Q6, D09-Q7 and D09-G15 for the owner; the
   walkthrough (§14) | owner approval pending |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 13. Sign-off
   checklists, item by item#1
@ ¶0 ‖ heading ‖ 1
  ## 13. Sign-off checklists, item by item
@ ¶1 ‖ paragraph ‖ 1
  SCR-026's five items are `14`'s, each quoted verbatim below (the tool checks every one); `14`
   keeps its boxes, which the owner ticks on #363 and never this PR, and gains only the pointer
   lines (§11).
@ ¶2 ‖ paragraph ‖ 1
  **SCR-026 (`14:640`).**
@ ¶3 ‖ table ‖ 1
  | Item (verbatim) | Frames and boards | Status |
  | --- | --- | --- |
  | file-picker and drag-drop paths | `SCR-026/pick` (boards 02 and 09): Choose file…, a real
   button fronting the labelled native input, and the drop zone around it, never a Tab stop;
   `SCR-026/drag-over` and `SCR-026/drag-over-rejected` (not drawn — the text is binding);
   `SCR-026/rejected-wrong-type` for a dropped file the picker would have filtered (board 04) |
   gated; boards PENDING |
  | version-mismatch state ('exported from a newer version - 2 panels will be dropped') |
   `SCR-026/rejected-version-newer` (boards 04 and 09): both versions and a way on, nothing
   imported and nothing applied in part — drawn as US-LAY-007's refusal (`11:2871`), never as the
   item's words (D09-C7; D09-A17 rewrites the item); `SCR-026/rejected-version-older` (board 04);
   `SCR-026/preview-migrated` (not drawn — the text is binding) | gated; the item's words amended
   (D09-A17, PROPOSED) |
  | preview of what will be imported before applying | `SCR-026/preview` (boards 03 and 09),
   §4.2's table with its drops and remaps first; `SCR-026/preview-over-budget` and
   `SCR-026/budget-confirm` (board 05); nothing exists before Import as new workspace (Condition 1)
   | gated; boards PENDING |
  | rejection state for malformed or oversized files | `SCR-026/rejected-malformed` and
   `SCR-026/rejected-oversized` (board 04), each naming its problem and its limit, the dialog open
   for another file; `SCR-026/rejected-nodes` (not drawn — the text is binding) | gated; boards
   PENDING |
  | import never carries credentials or account bindings (verified in copy) | the trust note on
   every import frame, `D02:513` byte for byte; the Excluded list on `SCR-025/export-preview` and
   `SCR-025/export-done` (boards 01 and 10); the account setting's Drop row and its words (§4.2) |
   gated; the copy's owner approval pending (#2701) |
@ ¶4 ‖ paragraph ‖ 1
  **SCR-025 (`14:627`)** is E15-D08's surface (merged, `fb1b4804`, named only): of its four items
   this spec draws only Export… in the Share section, part of the first item's sharing (§2), and
   the export dialog it opens; the other items are E15-D08's.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 14. Heuristic
   evaluation and the owner walkthrough#1
@ ¶0 ‖ heading ‖ 1
  ## 14. Heuristic evaluation and the owner walkthrough
@ ¶1 ‖ paragraph ‖ 1
  **Heuristic evaluation `(heuristic)`** — Nielsen's ten and `05`'s rules, a desk review of this
   text and E15-D02's boards: no participant, timing or quote exists, and none is invented.
@ ¶2 ‖ table ‖ 1
  | Heuristic | What the design does | Risk left `(heuristic)` |
  | --- | --- | --- |
  | visibility of system status | the determinate progress with its step count; Import as new
   workspace busy, then "Still importing…"; every outcome spoken once; the report persists until
   the user leaves it | a check that ends inside the 150 ms show-delay shows no bar at all, by
   intent; a slower one speaks once at its start and once at its end, never per step |
  | match with the real world | "format version" and never the field's name; Add, Drop and Remap;
   panels, layouts and symbols, never the file's keys, except the one key a refusal names | a key
   such as `layouts[1].grid_spec.root` is the file's own language, so the sentence around it says
   what to do next |
  | user control and freedom | Cancel, `Esc`, × and Close are never gated (§7); a refusal keeps
   the dialog open with Choose another file focused; the budget's Cancel returns to the preview |
   once the file is sent, Close ends the view and the import still finishes; the toasts after a
   closed view carry the outcome (D09-D18) |
  | consistency and standards | the trust note on every import frame; CMP-043's footer with Cancel
   first; one table for the preview and the report; E15-D03's T2 anatomy | E15-D02's own words
   differ in three places until its next revision (D09-C5, D09-C6, D09-C13) |
  | error prevention | the preview before the send; nothing created before Import as new
   workspace; the budget's confirm with its Cancel focused; the export's check declines what its
   lists cannot show | the account setting's Drop row predicts what the server does until `22` says
   it (D09-G3) |
  | recognition rather than recall | the Excluded list stays on the completion step; the report
   repeats the preview row for row; the file line names the chosen file | once the dialog is gone,
   so is the report; Copy report is the way to keep it |
  | flexibility and efficiency | a drop or Choose file…; `Enter` on Choose another file reopens
   the picker at once | no chord opens Import… directly; the two menus reach it |
  | aesthetic and minimalist design | one chrome for five steps; at most one CMP-028 line above
   the table | a file with many layouts makes a long table, so its caption's counts come first |
  | recognise, diagnose and recover from errors | each rejection and refusal names its problem and
   its limit, gives a way on and says "Nothing was imported."; the unanswered send, an outcome too,
   says the import is unconfirmed; the dialog stays open | a refusal that arrives after the view
   closed needs the toast's Review to recover (D09-D18) |
  | help and documentation | the help line "JSON, up to 2 MB"; the trust note; the caveat | — |
  | `05`: focus is never silently stolen (`05:96`) | the preview arrives with focus left on Choose
   file…; the report's heading takes focus only after the user's own Import as new workspace | a
   screen-reader user meets the caption through the polite region before the table itself |
  | `05`: colour is never the only signal | Add, Drop and Remap are words with their own shapes; a
   rejection is its words, its glyph and the absent verb | under tritanopia the Add and Remap
   glyphs are §8's nearest pair, so the words carry them |
  | `05`: no function by drag alone (`05:35`) | Choose file… is the keyboard path, and the drop
   zone only adds to it | — |
@ ¶3 ‖ paragraph ‖ 1
  **The protocols** (`(heuristic)` until run). **Status: not run** — no participant, count, timing
   or quote exists. Ready once boards 01 to 08 exist; results are appended as a dated addendum, the
   ticket's test plan item by item (`BL:266`).
@ ¶4 ‖ list ‖ 1
  - **T-1 — the fixture walk** (item 1): walk every state with the fixture set — the valid file,
   the newer and the older format version, the malformed, the oversized, the unknown kinds, the
   account filter and the 30-panel file — and record the frame each reaches and its words.
  - **T-2 — the keyboard walk** (item 2; board 08): from "+" › Import… to the report without a
   pointer, file selection included; record every stop and every announcement against §7.
  - **T-3 — the screen-reader pass** (item 3): the drop zone's words, the table read with its
   headers, the report's region; record what is heard against §7's desk pass.
  - **T-4 — the copy review of the trust claims** (item 4; boards 01 and 02): the owner reads the
   Excluded list and the trust note cold and says what leaves the machine and what is ignored on
   import. **Pre-registered rule:** a reader who believes the file may go anywhere without a
   thought, or that an account travels in it, makes the copy a redesign item before sign-off.
  - **T-5 — contrast and colour vision** (item 5): §8's rows from the tool, and the boards'
   greyscale and deuteranopia renders.
  - **T-6 — the token audit** (item 6): the boards PR reads every shape back as token bindings and
   records its counts.
  - **T-7 — the checklist sweep** (item 7): §13, item by item.
  - **T-8 — the hand-off dry run** (item 8; boards 02 and 04): a developer who has not read the
   thread rebuilds the drop zone and one rejection, `SCR-026/pick` and
   `SCR-026/rejected-oversized`, from this spec and those boards alone; each question the spec does
   not answer becomes a fix before E15-D15's hand-off pack.
@ ¶5 ‖ paragraph ‖ 1
  **Owner walkthrough** (at most ten items; posted on #363 at merge, the boards PR drawing what
   each names):
@ ¶6 ‖ list ‖ 1
  - [ ] Board 01: open Export… from the tab's `[⋯]`; read the Included and the Excluded lists
   aloud, say what leaves the machine and what does not, and confirm that the sharing claim appears
   nowhere.
  - [ ] Board 01: download the file; read the completion line and the file name, and say why the
   Excluded list is still shown.
  - [ ] Board 02: open Import… and find both ways in, Choose file… and the drop zone, and say
   which one the keyboard reaches.
  - [ ] Board 03: watch the check, read the preview's caption first and then its Drop and Remap
   rows, and say what will be added, what will not, and why.
  - [ ] Board 04: for each rejection, say what was wrong, what the limit is and that nothing was
   imported, and confirm that no Import verb is offered.
  - [ ] Board 05: open `wall.json`; read the budget line, press Import as new workspace and read
   the confirm's numbers, then press Cancel and say where focus is.
  - [ ] Board 06: read the report, press Copy report and paste the text; check that no account is
   named and that nothing of the file appears beyond its capped names.
  - [ ] Board 07: as a Viewer, and then viewing as alex, open "+" and read Import…'s lock and its
   reason; then say why Export… is offered to every session.
  - [ ] The keyboard walk on board 08: with the keyboard alone, go from "+" › Import… through
   Choose file…, the OS picker, the table's headers, Import as new workspace and the report to
   Close, and confirm that `Esc` closes only the topmost layer and that no step needs a pointer.
  - [ ] Boards 09 and 10, the light twins: tell Add, Drop and Remap apart without colour, and read
   the trust note and the Excluded list.
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 15.
   Traceability#1
@ ¶0 ‖ heading ‖ 1
  ## 15. Traceability
@ ¶1 ‖ paragraph ‖ 1
  Every ticket item, from the trace at the top, to the section that answers it, the frames that
   show it and the boards that will draw them (PENDING, §0).
@ ¶2 ‖ table ‖ 1
  | Ticket item | Section | Frames | Boards |
  | --- | --- | --- | --- |
  | AC-1 the included and the excluded lists | §2.3 | `SCR-025/export-preview`,
   `SCR-025/export-done` | 01, 10 |
  | AC-2 a newer file refused, never applied in part | §5.1, §5.3 |
   `SCR-026/rejected-version-newer` | 04, 09 |
  | AC-3 the unknown kinds by their stored names, in the preview and the report | §4.2, §4.3 |
   `SCR-026/preview`, `SCR-026/report` | 03, 06, 09, 10 |
  | AC-4 an account reference dropped and disclosed, naming no account | §4.2, §4.4, §4.5 |
   `SCR-026/preview`, `SCR-026/report` | 03, 06 |
  | AC-5 malformed or oversized: the problem and the limit, the dialog open | §5.1, §5.4 |
   `SCR-026/rejected-malformed`, `SCR-026/rejected-oversized` | 04 |
  | AC-6 a keyboard path for every step; the table read with its headers | §3.3, §4.4, §7 |
   `SCR-026/pick`, `SCR-026/preview` | 02, 03, 08 |
  | DL-1 the export's entries | §2.2 | `SCR-025/export-entry`, `SCR-025/export-unavailable` | 07 |
  | DL-2, DL-3 the Included list and the Excluded list, first-class | §2.3 |
   `SCR-025/export-preview` | 01, 10 |
  | DL-4, DL-5 the file name with its format version; the completion | §2.4 |
   `SCR-025/export-done`, `SCR-025/export-cancelled` | 01 |
  | DL-6 SCR-026 in both themes: the drop zone, its label, the keyboard path, the picker | §3.3,
   §8 | `SCR-026/pick`, `SCR-026/drag-over`, `SCR-026/drag-over-rejected` | 02, 09 |
  | DL-7, DL-8 the preview as a table: its columns and its order | §4.2, §4.4 | `SCR-026/preview`
   | 03, 09 |
  | DL-9 the validation states | §4.4, §5 | the six rejections; `SCR-026/preview-over-budget` |
   04, 05 |
  | DL-10 the report, persistent and copyable | §4.5 | `SCR-026/report` | 06, 10 |
  | DL-11 the progress of the check | §3.4 | `SCR-026/validating` | 03 |
  | DL-12 the trust copy, word by word | §1.2, §9 | the trust note of every import frame;
   `SCR-025/export-preview` | 01, 02 |
  | DL-13 the redlines and the spec page | §2.2, §2.3, §3.2, §3.3, §4.4, §5.2, §8 | every frame |
   01 to 10 |
  | DL-14 CMP-067's Storybook list | §10 (D09-A4) | — | — |
  | DL-15 the constructive route | §5.3 | `SCR-026/rejected-version-newer`,
   `SCR-026/rejected-version-older` | 04 |
  | DL-16 the budget through US-LAY-001's confirm | §4.4 | `SCR-026/preview-over-budget`,
   `SCR-026/budget-confirm` | 05 |
  | DL-17 the strings from the file | §1.2, §4.4, §5.5 | every frame with a `caps:` and a
   `renders:` clause | 03, 04, 06 |
  | DL-18 the limits; no environment travels; the server re-checks | §1.2, §3.4, §5.4 |
   `SCR-026/validating`; §5.1's frames | 03, 04 |
  | DL-19 the accessibility notes | §4.4, §7 | `SCR-026/validating`, `SCR-026/preview`,
   `SCR-026/report` | 03, 06, 08 |
  | DL-20 the annotated events | §2.4, §4.5, §5.2; D09-G13 | `SCR-025/export-done`,
   `SCR-026/report`, the six rejections, `SCR-026/budget-confirm` | — |
  | DL-21 the reuse note for SCR-089 | §11 (D09-A19) | — | — |
  | DoD-1 the export preview with both lists | §2.3 | `SCR-025/export-preview` | 01, 10 |
  | DoD-2 SCR-026 in both themes | §3, §4, §5, §8 | the 27 <!-- audit:frames_import=27 --> SCR-026
   frames | 02 to 06, 09, 10 |
  | DoD-3 both versions, a way on, no partial apply | §5.3 | `SCR-026/rejected-version-newer` |
   04, 09 |
  | DoD-4 text plus glyph; contrast and colour vision | §4.4, §8 | the Action column; §8's matrix
   | 03, 04, 06 |
  | DoD-5 the keyboard walk with file selection; the table with its headers | §7, §14 | §7's
   keyboard model; the walkthrough's item on board 08 | 08 |
  | DoD-6 the copy signed off on the trust claims | §9, §14 | — (owner approval pending (#2701)) |
   — |
  | DoD-7 the untrusted-string rule and the limits stated | §1.2, §5.4, §5.5 | — | — |
  | DoD-8 SCR-026's sign-off items | §13 | the 5 <!-- audit:checklist_items=5 --> items of
   `14:640` | — |
  | DoD-9 the spec merged; CMP-067's Storybook list agreed | the deviations; §10 | — | — |
  | DoD-10 the reuse note filed | §11 | — | — |
  | DoD-11 the CDO sign-off recorded | §12, the owner (#2701) | — | — |
§ E15-D09 — SCR-026 workspace import / export, preview and rejection states: hi-fi › 16. Summary#1
@ ¶0 ‖ heading ‖ 1
  ## 16. Summary
@ ¶1 ‖ list ‖ 1
  - **What it is:** the text-first hi-fi of SCR-026's workspace import — one `lg` dialog, Choose
   file… with its drop zone, five checks in a worker with the server's re-check stated, a preview
   table with its drops and remaps first, six rejections, two refusals and an unanswered send, none
   with an Import verb, and a report with Copy report — and of the export from SCR-025 and the
   menus: the Included and Excluded lists, the file name with its format version, the completion.
  - **Ruled:** 16 <!-- audit:bq_rows=16 --> questions and 4 <!-- audit:conditions=4 --> conditions
   (6396085915); the trust copy, the account rule and the version rule are the owner's, approval
   pending (#2701).
  - **Frames:** 35 <!-- audit:frames_total=35 --> — 8 <!-- audit:frames_export=8 --> on the
   export, 27 <!-- audit:frames_import=27 --> on the import — with 21 <!-- audit:frames_drawn=21
   --> on 10 <!-- audit:boards=10 --> boards (2 <!-- audit:light_twins=2 --> light twins) and 14
   <!-- audit:frames_not_drawn=14 --> bound by the text.
  - **Measured:** 26 <!-- audit:pairs_rows=26 --> gated pairs, 0 <!-- audit:pairs_fail=0 --> FAIL,
   0 <!-- audit:missing_tokens=0 --> tokens missing; Add, Drop and Remap are words with their own
   shapes, never colour alone (§8).
  - **Gated:** `--check` clean; `--self-test` runs 391 <!-- audit:mutations=391 --> mutations,
   each caught by exactly one new FAIL; every frame's copy key is a row of the deck (§9).
  - **Rows:** 15 <!-- audit:rows.G=15 --> G, 19 <!-- audit:rows.C=19 --> C, 22 <!--
   audit:rows.A=22 --> A, 7 <!-- audit:rows.Q=7 --> Q and 35 <!-- audit:rows.D=35 --> decisions,
   every one PROPOSED to a named owner.
  - **Next:** the boards PR draws the ten boards; E15-S07 takes D09-G1 to D09-G8, D09-G13 and
   D09-G14, with the atomic import in `22` first (C-6.1); E15-D08 is merged (`fb1b4804`) and named
   only; the walkthrough of §14 is posted on #363 at merge.
§ (end)#1
@ ¶0 ‖ end ‖ 1
"""  # end of RULED_PIN_TXT


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
