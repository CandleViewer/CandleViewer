#!/usr/bin/env python3
"""E15-D08 SCR-025 workspace settings and SCR-029 unsaved / conflict dialogs: the spec's gate tool.

Stdlib only, offline; reads the plan texts, the merged upstream specs, the token JSON, `pairs.mjs`
and the spec AS TEXT. The contrast ratio is `contrast_ratio()` of
`docs/design/_tools/contrast_check.py` and the themes resolve through the loader of
`packages/ui/tokens/tests/verify_tokens.py` (prim + dark, + light, + high-contrast, `themes.json`
layering), both imported, never re-implemented; the CVD rows use
`docs/research/_tools/cvd_simulate.py`. Prints: (1) the measured matrix of every fg / bg pair the
two dialogs draw (text 4.5, body text 7.0 in high contrast, non-text 3.0; the 7:1 aims, the
rejected and the decorative rows reported, never gated); (2) every bound token, resolved or
MISSING; (3) the greyscale luma and CVD rows of the danger and boundary colours (reported); (4) the
contract facts the frames quote, parsed from `22` / `14` / `15` / `23` / E15-D02 / E09-D09 / slice 4
text, never typed; (5) the gates, each FAIL led by its code in brackets: the header, the
deviations, the AC trace, the ruled questions, the numbered sections in order, §0's boards and
their reconciliation with the frame rows, the PER-FRAME gates over every `SCR-025/` and `SCR-029/`
row of §2-§4 (each frame's obligations come from the tool's own KIND and FOOTER tables, never from
the row's Class cell, which must agree), the entry-point matrix, the reason and upstream strings,
the copy keys, the cites (a moved line is a WARN; a fragment gone or ambiguous is a FAIL; a cite
missing from CITED_TABLE is a FAIL), the `14` pointer lines, private paths and hosts, closing
keywords, dangling rule and catalogue ids, placeholders, and the written sections: §5's one T2
paragraph and its not-T2 list, §5.1's exits row, §6's exits sentence, §7's tables equal to
sections 1 and 3, §8's deck, §11's G-rows and §12's sign-off items; (6) the counts. `--json` is the
only source of every number in the spec: every `<!-- audit:KEY=VALUE -->` marker is re-derived on
every run, the number printed beside it must equal it, a malformed marker is a FAIL and no marker
the spec carries may disappear; `--check` adds the markers summary line. `--self-test` applies each
named mutation of `mutations()` to an in-memory copy of the spec (and each of
`context_mutations()` to an in-memory copy of the plan texts) and passes only when each adds
exactly one new FAIL carrying its expected text, every gate code of this file is behind at least
one mutation (EXEMPT names the few that no spec or plan-text edit reaches, with the reason), M1-M17
of the brief all run, the per-frame gates are clean on the unmutated spec and the spec on disk is
byte-identical afterwards. Exit 1 on any FAIL, with or without a flag.

Usage: python3 -I -B docs/design/_tools/e15_d08_settings_conflict_audit.py [--json] [--check]
       [--self-test]
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
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
SPEC = DESIGN / "E15" / "E15-D08.md"


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
BASE = "06eeb317e0d4ab636e3b3e8ab9419a5c64ce1d7e"
# The merged inputs the header pins (E15-D01, E15-D02 text and boards, E05-D02 slices 3 and 4,
# E09-D09, E15-D03 text): each full sha must stand in the header.
MERGE_SHAS = (
    "ed8a22246263ace73f39e4434e6d5f57b1a857bd",
    "1044c4f602eff6ae1a2cf42201ab398f6c4234d1",
    "7be6eac6a705cf24ba534ce4f7d31349a1e29932",
    "3a2fc5c299a37e74ca8fb962d4435335b79aead9",
    "04a8caa9513e90debcf7cbc41a9ca585496eba01",
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
    "c4989493461ec6b6d22b9254633452a6362b750e",
)
PENPOT_PAGE = "E15-D08 Workspace settings and conflicts"
STATUS_WORDS = ("text-first", "PROPOSED unless RULED", "boards PENDING", "≤ 10 boards", "≤ 1/3")
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
# A closing keyword in any form GitHub links: `Closes #N`, `Fixes: #N`, `owner/repo#N` or an
# issue URL (text-first PRs say `Refs` and `Partial:` only).
CLOSING = (
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
    r"(?:(?:[\w.-]+/[\w.-]+)?#\d+|https?://\S+/issues/\d+)"
)
POINTER = "[E15-D08.md](../design/E15/E15-D08.md)"
# Each pointer line sits right after its screen's sign-off checklist in `14`.
POINTER_AFTER = (
    "[ ] delete-workspace confirmation path",
    "[ ] Esc maps to Cancel, never to Discard",
)
NOT_DRAWN = "not drawn — the text is binding; drawn on request"
BOARD_CAP = 10
# The two boards that draw tables, not frames (the matrix and the keyboard board).
TABLE_BOARDS = ("07", "08")
# doc key -> path; a cite in the spec is `KEY:line`, or a range with an en dash, in one code span.
DOC_PATHS = {
    "04": PLAN / "04-security-program.md",
    "05": PLAN / "05-accessibility-standard.md",
    "11": PLAN / "11-user-stories.md",
    "14": PLAN / "14-screens-catalogue.md",
    "15": PLAN / "15-component-catalogue.md",
    "16": PLAN / "16-design-system-brief.md",
    "21": PLAN / "21-database-schema.md",
    "22": PLAN / "22-api-openapi.yaml",
    "23": PLAN / "23-ws-protocol.md",
    "BL": PLAN / "backlog" / "E15.json",
    "D01": DESIGN / "research" / "e15-layouts" / "findings.md",
    "D02": DESIGN / "E15" / "E15-D02.md",
    "FL": DESIGN / "specs" / "e15-layout-flows.md",
    "S3": DESIGN / "E05" / "E05-D02-form-controls.md",
    "S4": DESIGN / "E05" / "E05-D02-feedback-overlays.md",
    "D09": DESIGN / "E09" / "E09-D09.md",
    "E16D03": DESIGN / "E16" / "E16-D03.md",
    "D03": DESIGN / "E15" / "E15-D03.md",
    "README": DESIGN / "README.md",
}
EN_DASH = "\u2013"
TIMES = "\u00d7"
MINUS = "\u2212"
CITE_RE = (
    r"`(04|05|11|14|15|16|21|22|23|BL|D01|D02|FL|S3|S4|D09|E16D03|D03|README):(\d+)(?:"
    + EN_DASH
    + r"(\d+))?`"
)
CITE_WARN: list[str] = []
# role -> (bar in dark, bar in light, bar in high contrast); None = reported, never gated.
# `hc-text` is body text: 4.5 in dark and light, 7.0 in high contrast (`05:130`); `aaa-target`
# reports the same 7:1 aim for a UI label that is gated as `text`.
BARS: dict[str, tuple[float, float, float] | None] = {
    "text": (4.5, 4.5, 4.5),
    "hc-text": (4.5, 4.5, 7.0),
    "non-text": (3.0, 3.0, 3.0),
    "aaa-target": None,
    "decorative": None,
    "rejected-text": None,
}
# element | fg | bg | role — every pair the two dialogs draw (spec section 7, rows in order).
PAIRS_TABLE = """
dialog title, body, table values | color.text.primary | color.surface.overlay | hc-text
labels, help, captions, consequence lines | color.text.secondary | color.surface.overlay | hc-text
T2 full label and lock glyph on the T2 fill | color.text.tertiary | color.surface.raised | hc-text
T2 reason, notice words, planned inset words | color.text.secondary | color.surface.raised | hc-text
planned inset stamp on raised | color.text.primary | color.surface.raised | hc-text
field value in the well | color.text.primary | color.surface.app | hc-text
field well boundary | color.text.tertiary | color.surface.app | non-text
invalid boundary against the well | color.status.danger.default | color.surface.app | non-text
invalid boundary against the dialog | color.status.danger.default | color.surface.overlay | non-text
error line glyph, danger-zone glyph | color.status.danger.strong | color.surface.overlay | non-text
error summary and failed banner words | color.text.primary | color.status.danger.subtle | hc-text
error summary links | color.text.link | color.status.danger.subtle | text
error summary links, HC 7:1 aim | color.text.link | color.status.danger.subtle | aaa-target
error summary edge and glyph | color.status.danger.strong | color.status.danger.subtle | non-text
Save / Save layout label on primary | color.text.on-action | color.action.primary.default | text
secondary button label | color.text.primary | color.action.secondary.default | text
delete Confirm label on the danger fill | color.text.on-action | color.status.danger.default | text
delete Confirm label, HC 7:1 aim | color.text.on-action | color.status.danger.default | aaa-target
switch on track | color.action.primary.default | color.surface.overlay | non-text
switch off track | color.text.tertiary | color.surface.overlay | non-text
switch knob on the on track | color.text.on-action | color.action.primary.default | non-text
switch knob on the off track | color.text.on-action | color.text.tertiary | non-text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
focus ring on the well | color.focus.ring | color.surface.app | non-text
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
secondary fill on the dialog | color.action.secondary.default | color.surface.overlay | decorative
the dialog hairline | color.border.default | color.surface.overlay | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.raised",
    "color.surface.overlay",
    "color.border.default",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.disabled",
    "color.text.on-action",
    "color.text.link",
    "color.action.primary.default",
    "color.action.secondary.default",
    "color.status.danger.subtle",
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.warning.strong",
    "color.focus.ring",
    "palette.black",
    "opacity.disabled",
    "opacity.scrim",
    "border.hairline",
    "border.thick",
    "border.focus",
    "radius.dialog",
    "radius.card",
    "radius.control",
    "elevation.dialog",
    "space.dialog.padding",
    "space.stack.xs",
    "space.stack.md",
    "space.stack.lg",
    "space.inset.xs",
    "space.inset.sm",
    "space.inset.md",
    "space.inset.lg",
    "space.field.gap",
    "size.icon",
    "size.control.height",
    "size.control.compact",
    "size.control.comfortable",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.body-strong",
    "type.ui.label",
    "type.ui.caption",
    "type.num.sm",
)
# name | a | b — colour pairs that must not carry a meaning alone (reported: deltaE76 under each
# deficiency; JND 5.0); the words, the glyph and the boundary width carry the meaning.
CVD_TABLE = """
danger-zone glyph against a warning glyph | color.status.danger.strong | color.status.warning.strong
invalid boundary against the field boundary | color.status.danger.default | color.text.tertiary
delete Confirm fill vs the Save fill | color.status.danger.default | color.action.primary.default
"""
GREY_TOKENS = (
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.danger.subtle",
    "color.text.tertiary",
    "color.action.primary.default",
)
JND = 5.0
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# doc | line at the base | text the line must hold. Every `KEY:line` cite in the spec must have a
# row here (a FAIL otherwise); the rows the spec does not cite feed the reconciliation below.
CITED_TABLE = """
04 | 1139 | | `workspaces:write`                                 |
04 | 1180 | Save/load own layouts, templates, drawings, hotkeys
05 | 85 | **Reserved, non-remappable keys**
05 | 96 | **Focus is never silently stolen**
05 | 97 | matching "cancel is always safe"
05 | 130 | **User-adjustable contrast**
05 | 131 | 7. **Text resize (WCAG 1.4.4, AA)**
05 | 148 | reserved for discrete, low-frequency, high-importance events only
05 | 150 | **Region hygiene**
11 | 2758 | #### US-LAY-002 — Saved workspaces
11 | 2865 | containing no secrets and no account bindings
11 | 5101 | #### US-SET-003 — Destructive-action confirm policy
14 | 233 | Escape does **not** dismiss
14 | 514 | `Ctrl+S` save; `Ctrl+Shift+S` save as
14 | 515 | unsaved changes (`*` on the tab, prompt on navigation)
14 | 516 | save conflict → "This workspace changed elsewhere. [Keep mine] [Load theirs]"
14 | 613 | ### SCR-025 — Workspace settings modal
14 | 615 | default account scope, density (compact/cosy/comfortable), theme override
14 | 617 | the last workspace cannot be deleted ("You need at least one workspace.")
14 | 618 | **Stories:** US-WS-020.
14 | 619 | grouped fieldsets for defaults (symbol, interval, environment binding)
14 | 621 | CMP-001 Button, CMP-004 Toggle, CMP-019 Icon (`lock`), CMP-040 FormField
14 | 622 | - **Stories:** US-LAY-002, US-LAY-003.
14 | 624 | [ ] 'this workspace is pinned to LIVE' warning drawn
14 | 662 | ### SCR-029 — Unsaved-changes / layout-conflict dialog
14 | 664 | the conflict variant adds a side-by-side summary of differences
14 | 665 | CMP-027 ErrorState / InlineError, CMP-044 ConfirmDialog, CMP-079 RbacGate.
14 | 667 | the three choices are explicit buttons with verbs
14 | 668 | within 300 ms of the conflicting write being detected
14 | 669 | `layout.conflict_detected`, `layout.conflict_resolved` with `{choice}` (analytics)
14 | 671 | [ ] Esc maps to Cancel, never to Discard
15 | 48 | ### CMP-001 Button
15 | 79 | ### CMP-004 Toggle (Switch)
15 | 83 | only the track dims; the label and the knob stay at full opacity
15 | 85 | `color.action.primary.default` (on track), `color.text.tertiary` (off track)
15 | 225 | ### CMP-019 Icon
15 | 243 | ### CMP-021 Link
15 | 301 | ### CMP-027 ErrorState / InlineError
15 | 304 | an error summary's "Can't submit — 2 problems"
15 | 306 | an error summary keeps `role="alert"` and its host moves focus to its heading
15 | 419 | ### CMP-039 FocusRing
15 | 433 | ### CMP-040 FormField
15 | 436 | `help?` · `error?` · `disabledReason?`
15 | 441 | Default, WithError, WithHelp, Required, Optional, Inline, ReadOnly, DisabledWithReason.
15 | 463 | ### CMP-043 Dialog (Modal)
15 | 466 | at most 420 / 560 / 960 px wide
15 | 468 | an `alertdialog` focuses Cancel
15 | 473 | ### CMP-044 ConfirmDialog
15 | 476 | `confirmDelayMs?` (default 400
15 | 477 | typed (Confirm natively disabled until the summary has loaded
15 | 479 | Confirm a CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`)
15 | 483 | ### CMP-045 Toast / Notification
15 | 671 | ### CMP-065 FormSection
15 | 674 | (`docs/design/E09/E09-D09.md` §2.2: one notice for the section)
15 | 678 | Default, Collapsible, WithErrors, DisabledWithReason.
15 | 811 | ### CMP-079 RbacGate
15 | 2514 | ### CMP-212 ToastHost
16 | 109 | Two supported density modes, selectable globally
16 | 111 | Default surfaces
16 | 114 | **Comfortable** (default for admin/onboarding/settings)
16 | 125 | Density changes spacing-token resolution only
16 | 136 | light is generated by re-pointing the same alias tokens
16 | 137 | Theme selection persists per-user (not per-workspace)
16 | 138 | so a switch is a CSS custom-property swap with no remount
21 | 4849 | **`viewer` holds no write permission.**
22 | 664 | - code: version_conflict
22 | 8525 | `limit_reached` (32 live workspaces)
22 | 8573 | `ETag`: the workspace token versions its metadata only
22 | 8588 | operationId: updateWorkspace
22 | 8605 | `412 version_conflict` (stale or unparseable `If-Match`, nothing
22 | 8634 | operationId: deleteWorkspace
22 | 8639 | workspace is `409 conflict` with `errors[0].rule = last_workspace`
22 | 8725 | `limit_reached` (32 live layouts)
22 | 8839 | operationId: updateLayout
22 | 8848 | `If-Match`, the no-op rule and `412 version_conflict` work as on `updateWorkspace`
22 | 12676 | operationId: exportWorkspace
22 | 19609 | WorkspaceIconToken:
22 | 19618 | WorkspaceInput:
22 | 19628 | `name` is at most 40 characters as sent (rule
22 | 19680 | Concurrency token (also the `ETag`) for the workspace metadata only
22 | 19887 | Panes have no id of their own
22 | 19993 | of the whole layout aggregate, panes included
22 | 20423 | density: { type: string, enum: [compact, comfortable, spacious] }
22 | 20464 | default_environment: { $ref:
23 | 818 | ### 6.2 Private topics
BL | 239 | grouped fieldsets (identity, defaults, appearance, startup, danger zone)
BL | 783 | switches workspaces or closes the app
D01 | 225 | **5.2 Unsaved changes (SCR-029): explicit save, never silent loss
D01 | 231 | SCR-025's "autosave toggle" stays as an opt-in, off by
D01 | 385 | `Ctrl+S` saves the active layout (`updateLayout`); workspace name and tab order
D01 | 398 | `22` `updateLayout`; the E15 epic's Technical notes; E15-S03 save semantics
D01 | 421 | the save model, AM-3 (owner; E15-D08, S03, X01)
D01 | 431 | a layout lock and a version history
D02 | 84 | layout events are analytics, never audit
D02 | 110 | the rail lists all; CMP-073 searches them
D02 | 125 | **The environment is structural:**
D02 | 127 | **Saving:** `Ctrl+S` → `updateLayout`
D02 | 128 | **A preset replaces the working copy and writes nothing:**
D02 | 129 | **SCR-029's verbs and focus:**
D02 | 130 | **A restored copy never looks saved:**
D02 | 147 | **SCR-025 draws only stored fields:**
D02 | 148 | **Import always creates a new workspace,**
D02 | 267 | surplus panes leave `panes[]` (Undo returns them)
D02 | 280 | Undo layout change, Revert to saved…, Workspace settings…, Export…
D02 | 290 | Couldn't save — the workspace store is unavailable.
D02 | 308 | **Reorder** by drag, or by Move up and Move down
D02 | 323 | Undo reverts the last layout change only (one step)
D02 | 408 | **The gallery** (CMP-043 dialog
D02 | 410 | Delete layout Wide chart? It can't be restored.
D02 | 413 | Apply on a clean working copy replaces it at once
D02 | 417 | ### 5.7 SCR-029 Unsaved-changes and conflict dialog
D02 | 433 | Save layout writes Layout 1 (`updateLayout`) and then applies the preset
D02 | 439 | Saved now (14:05:12)
D02 | 443 | Keep mine replaces the version saved at 14:05. Load theirs discards your
D02 | 449 | Keep mine writes with the fresh token
D02 | 498 | ### 5.10 SCR-025 Workspace settings
D02 | 502 | unique per user, case-insensitive; "That name is already in use."
D02 | 503 | - **Saving layouts:**
D02 | 504 | **Share:** [Export…]
D02 | 505 | - **Delete:** [Delete workspace…] opens CMP-044's typed variant
D02 | 507 | Footer: [Save] [Cancel]. `Esc` or Cancel with edits asks
D02 | 511 | **Export preview** (from SCR-025
D02 | 565 | name clash; Delete workspace… T2 on the last one
D02 | 569 | unsaved, revert, conflict variants at both widths; conflict reached from a preset
D02 | 574 | a third racing write refreshes the table with
D02 | 583 | Workspace, always; while Save is T2 it sends nothing
D02 | 632 | - **Zoom and text size** (`05` §5 item 7)
D02 | 635 | ### 8.1 Gated controls: T2, disabled with a visible reason
D02 | 639 | **Legs, in the server's order**
D02 | 640 | - **Client state is T1.**
D02 | 641 | is this surface's rendering
D02 | 642 | **One notice, many pointers** (E09-D09 §2.2): while viewing as
D02 | 643 | **Keys** (E09-D09 §9.3): `Enter` or `Space` on a T2 control
D02 | 645 | **Availability, not T2:**
D02 | 653 | Discard changes, Load theirs and Cancel stay T1
D02 | 658 | SCR-025's fields, autosave switch, [Save] and [Delete workspace…]
D02 | 670 | "This workspace has the most layouts it can hold."
D02 | 675 | E15; the words are `22`'s `last_workspace` copy
D02 | 730 | **SCR-025:** [board 17; spec D-29; open OQ-N]
D02 | 738 | **SCR-029:** [board 13] the unsaved and the cross-session conflict variants
D02 | 765 | two buttons; the unsaved variant needs three verbs and the conflict variant four
D02 | 816 | `14` SCR-020 States; E15-S03 save semantics
D02 | 817 | `14` SCR-020 Validation
D02 | 818 | `14` SCR-020 Sign-off; SCR-025 Type
D02 | 825 | `14` SCR-029 Performance
D02 | 828 | | A-15 |
D02 | 843 | **G-10** SCR-025's unstored fields
D02 | 853 | A preset over a dirty layout goes through SCR-029 (ticket AC3)
D02 | 864 | SCR-025's unstored fields (description, default symbol and interval
D02 | 899 | **T1 — a preset over a dirty layout**
D02 | 949 | §5.7 and §5.10; OQ-C, OQ-D, OQ-E, OQ-N
D09 | 36 | | Step | Question
D09 | 49 | - **T2 Disabled with a visible reason (D4).**
D09 | 85 | Every T2 reason is one of these seven keys
D09 | 114 | `workspaces:write` → "save workspaces"
D09 | 128 | The `permission_change` frame replaces
D09 | 142 | `permission_change`, no focused or armed control affected
D09 | 224 | ### 9.1 `aria-disabled` versus `disabled`, and focusability
D09 | 238 | ### 9.3 Keys on a T2 control
D09 | 263 | "Read-only — {rbac sentence, first letter lower-cased}"
D09 | 264 | | `glyph.name`
E16D03 | 49 | typed confirmation and its value
E16D03 | 364 | | D03-A4 |
D03 | 140 | **The tab strip.** A manual-activation `tablist`
D03 | 580 | | V-1 | `[Save]`
D03 | 602 | | `ws.tab.dirty.name`
D03 | 611 | | `ws.save.clean`
D03 | 626 | | `layout.revert.clean`
FL | 29 | ## F-LAY-2 — Switch workspace with unsaved changes
FL | 54 | This flow replaces `14` SCR-020's "prompt on navigation"
FL | 56 | ## F-LAY-3 — Apply a preset over a dirty layout
FL | 85 | §3.8.1 keeps no history, so Undo is the client's
FL | 171 | `exportWorkspace` is specified but not yet served
README | 46 | - **Penpot reference** to the ticket's page
S3 | 80 | 21. **The field box**
S3 | 103 | 23. **Validation, never T2**
S3 | 113 | On submit the host's error summary
S3 | 120 | 24. **T2 in a form**
S3 | 153 | 25. **What is not T2**
S3 | 182 | 28. **Resize, zoom and reflow**
S4 | 106 | 31. **The scrim and the inert page**
S4 | 119 | 32. **Focus contract for overlays**
S4 | 140 | 33. **Where feedback speaks**
S4 | 173 | 36. **Containers never gate; their nested controls do**
S4 | 194 | 37. **What is not T2 here**
S4 | 202 | 38. **Forced colours**
S4 | 209 | 39. **Resize, zoom and reflow**
S4 | 365 | **CMP-043 and CMP-044 in E15-D02 (kept, E15-D02 following).**
S4 | 734 | **H22 — `Esc`, the NoEscClose story and the scrim.**
S4 | 749 | **H23 — What the scrim makes inert.**
S4 | 756 | **H24 — The confirm: its look, the typed rule
S4 | 848 | **H32 — Where a confirm opens, and its Tab order.**
S4 | 881 | **H34 — A toast raised by a modal's own action.**
S4 | 904 | **H36 — A dialog with unsaved changes.**
S4 | 1642 | block gap `space.stack.md`; at most 420 / 560 / 960 px wide
S4 | 1645 | `Cancel` (`secondary`) first, the primary or danger action last
S4 | 1707 | SCR-072's "partial failure with retry"
S4 | 1720 | what the confirm does, the dialog's description: SCR-072's
S4 | 1722 | CMP-040 + CMP-007; its label names the token
S4 | 1760 | a Confirm gated mid-dialog speaks once, assertively
"""
# The fixture (spec header): the names and the summary cases. The saved time and the conflicting
# re-read's time are parsed from E15-D02 (`D02:433`, `D02:439`); the rest is this spec's own.
FIXTURE: dict[str, Any] = {
    "workspace": "Scalping",
    "other_workspace": "Swing",
    "layout": "Layout 1",
    "preset": "Order-flow",
    "layouts": 2,
    "target": "alex",
    "renamed": "Scalping 2",
    "renamed_elsewhere": "Scalping EU",
    "refreshed_time": "14:07:30",
    "list_cap": 3,
    "ac3": {
        "panels_added": 3,
        "pairs": [("BTCUSDT", "ETHUSDT"), ("SOLUSDT", "BNBUSDT")],
        "groups_added": ["B"],
    },
    "overflow": {
        "panels_added": 1,
        "pairs": [
            ("BTCUSDT", "ETHUSDT"),
            ("SOLUSDT", "BNBUSDT"),
            ("XRPUSDT", "ADAUSDT"),
            ("DOGEUSDT", "LTCUSDT"),
            ("LINKUSDT", "DOTUSDT"),
        ],
    },
}
# The difference-summary templates (BQ-14 RULED): key -> (singular, plural).
DIFF_TEMPLATES = {
    "panels_added": ("{n} panel added.", "{n} panels added."),
    "panels_removed": ("{n} panel removed.", "{n} panels removed."),
    "symbols_changed": ("{n} symbol changed: {items}.", "{n} symbols changed: {items}."),
    "groups_added": ("{n} sync group added: {items}.", "{n} sync groups added: {items}."),
    "groups_removed": ("{n} sync group removed: {items}.", "{n} sync groups removed: {items}."),
    "other": ("{n} other change.", "{n} other changes."),
    "overflow": ("and {n} more difference.", "and {n} more differences."),
}
# The consequence lines (BQ-12 RULED): one per verb, rendered with the frame's time.
LAYOUT_LINES = {
    "Keep mine": "Keep mine replaces the version saved at {hhmm}. That version can't be recovered.",
    "Load theirs": "Load theirs replaces your unsaved changes. They can't be recovered.",
    "Save mine as new layout": (
        "Save mine as new layout keeps both: yours as a new layout, theirs in {layout}."
    ),
    "Cancel": "Cancel keeps your changes unsaved in this window.",
}
SETTINGS_LINES = {
    "Keep mine": "Keep mine replaces the settings saved at {hhmm}. They can't be recovered.",
    "Load theirs": "Load theirs replaces your changes to these settings. They can't be recovered.",
    "Cancel": "Cancel keeps your changes in this dialog.",
}
OVERWRITE_TITLE = "Replace the version saved at {hhmm}?"
QUEUE_RULE = "the dialog never opens while focus is in an order-capable panel"
SAVED_SENTENCE = "Saved workspace settings."
TYPED_LABEL = '"Type {workspace} to confirm"'
# The frame-row sentences the content gates render from FIXTURE and the parsed facts (MJ2 (d): no
# contract or fixture number in a frame row is free).
NAME_HELP = '"Up to {max} characters. Each workspace needs its own name."'
LONG_PRODUCER = "Name typed to {n} characters"
DIRTY_PRODUCER = 'Name edited to "{renamed}"'
ONE_INVALID = ('"Can\'t save — 1 problem"', '"Fix 1 field."')
DELETE_PRODUCER = "on {workspace} ({n} layouts, "
DELETE_BODY = '"It has {n} layouts, and {layout} has unsaved changes. Deleting can\'t be undone."'
RACING_LINE = '"Nothing was deleted — this is now your only workspace."'
CAP_PRODUCER = "holds {n} layouts"
REVERT_AGAINST = "the difference summary against the version saved at {hhmm}"
REVERT_DONE = '"{layout} reverted to the version saved at {hhmm}."'
LOADED_LINE = '"{layout} now shows the version saved at {hhmm}."'
REFRESHED_PRODUCER = "a third window wrote at {time}"
OVERFLOW_PRODUCER = "{panels} panel added and {symbols} symbols changed"
KEEP_ROUTE = "Keep mine opens `SCR-029/keep-mine-confirm`"
TYPED_RULES = (
    "matched exactly after trimming, case-sensitive",
    "`Enter` in the field never confirms",
)
QUEUED_LINES = (
    "autosave stops for {layout} until the conflict is settled",
    '"{layout} changed in another window."',
)
DANGER_WORDS = ("Danger zone", "the `danger` glyph")
BY_REFERENCE = "as `SCR-029/conflict`, its table and its four lines unchanged"
SAVING_ROUTES = (
    "a `412` takes the queued route (`SCR-029/conflict-queued`)",
    "a `412` turns it into `SCR-029/conflict-from-preset`",
)
REFLOW_PRODUCER = "200 % zoom on the {frame} frame"
# frame | kind | parameters — the independent inventory every per-frame gate reads; a row's Class
# cell must agree with it and never decides. `keys` = the T2 reason keys the row names, the first
# one's sentence quoted in its Shows cell; `time` = the fixture time its consequence lines render;
# `diff` = the summary case it renders; `star=producer` = its `*` is the dirty layout of its
# producer; `size` = the CMP-043 / CMP-044 size the row must state; `loaded` = it quotes Load
# theirs' outcome line.
KIND_TABLE = """
SCR-025/default | form | size=md
SCR-025/compact | inset |
SCR-025/planned-description | planned | gap=D08-G1
SCR-025/planned-defaults | planned | gap=D08-G2
SCR-025/planned-density | planned | gap=D08-G3
SCR-025/planned-theme | planned | gap=D08-G4
SCR-025/dirty | form-dirty |
SCR-025/invalid-empty | invalid | rule=empty
SCR-025/invalid-long | invalid | rule=long
SCR-025/invalid-duplicate | invalid | rule=taken
SCR-025/discard-prompt | discard-prompt | size=sm
SCR-025/saving | busy |
SCR-025/saved | outcome |
SCR-025/failed | refusal |
SCR-025/settings-conflict | settings-conflict | time=conflict;size=md
SCR-025/delete-confirm | delete-confirm | star=producer;size=md
SCR-025/delete-racing | delete-racing | keys=workspace.limit.last
SCR-025/delete-last | t2-state | keys=workspace.limit.last
SCR-025/viewer-read-only | t2-viewer | keys=notice.panel_read_only,rbac.permission
SCR-025/view-as | t2-view-as | keys=rbac.view_as
SCR-025/leg-lost | t2-leg | keys=notice.panel_read_only,rbac.permission
SCR-025/reflow-200 | reflow |
SCR-029/unsaved | unsaved | diff=ac3;size=md
SCR-029/unsaved-overflow | unsaved | diff=overflow
SCR-029/unsaved-saving | unsaved-busy |
SCR-029/revert | revert | diff=ac3;size=md
SCR-029/viewer-unsaved | unsaved-t2 | keys=rbac.permission
SCR-029/view-as-unsaved | unsaved-t2 | keys=rbac.view_as
SCR-029/reflow-200 | reflow |
SCR-029/compact | inset |
SCR-029/conflict | conflict | time=conflict;table=yes;loaded=yes;size=md
SCR-029/conflict-from-preset | conflict | time=conflict;table=yes
SCR-029/conflict-refreshed | conflict | time=refreshed
SCR-029/conflict-queued | queued |
SCR-029/keep-mine-confirm | overwrite-confirm | time=conflict;size=sm
SCR-029/save-as-t2 | conflict-t2 | keys=layout.limit.count
SCR-029/leg-lost | conflict-t2 | keys=rbac.permission
"""
# kinds | the footer's labels in order (D08-D16; `S4:1645`: Cancel first, the primary or danger
# action last). A kind not listed draws no footer.
FOOTER_TABLE = """
form, form-dirty, invalid, busy, refusal | Cancel · Save
t2-state, t2-viewer, t2-view-as, t2-leg | Cancel · Save
discard-prompt | Keep editing · Discard changes
settings-conflict | Cancel · Load theirs · Keep mine
delete-confirm, delete-racing | Cancel · Delete workspace
unsaved, unsaved-busy, unsaved-t2 | Cancel · Discard changes · Save layout
revert | Cancel · Revert to saved
conflict, conflict-t2 | Cancel · Save mine as new layout… · Load theirs · Keep mine
overwrite-confirm | Cancel · Replace saved version
"""
DIRTY_KINDS = {
    "form-dirty",
    "invalid",
    "discard-prompt",
    "busy",
    "refusal",
    "settings-conflict",
    "t2-leg",
    "unsaved",
    "unsaved-busy",
    "unsaved-t2",
    "revert",
    "conflict",
    "queued",
    "overwrite-confirm",
    "conflict-t2",
}
# The dirty marker each screen draws: SCR-025's dirty title, SCR-029's dirty tab (`D02:280`).
DIRTY_MARK = {"SCR-025": "`Workspace settings *`", "SCR-029": "`Scalping *`"}
STAR_SPAN = r"`[^`\n]*\*[^`\n]*`"
T2_KINDS = {
    "t2-state",
    "t2-viewer",
    "t2-view-as",
    "t2-leg",
    "unsaved-t2",
    "conflict-t2",
    "delete-racing",
}
ONE_NOTICE_KINDS = {"t2-viewer", "t2-view-as", "t2-leg"}
VALIDITY_KINDS = {"form", "invalid", "delete-confirm"}
SCR029_DIALOG_KINDS = {"unsaved", "unsaved-busy", "unsaved-t2", "revert", "conflict", "conflict-t2"}
DIALOG_KINDS = SCR029_DIALOG_KINDS | {
    "discard-prompt",
    "settings-conflict",
    "delete-confirm",
    "delete-racing",
    "overwrite-confirm",
}
FORM_KINDS = {"form", "form-dirty", "invalid", "busy", "refusal"} | (T2_KINDS - SCR029_DIALOG_KINDS)
EXIT_KINDS = DIALOG_KINDS | FORM_KINDS
CONFLICT_412_KINDS = {"conflict", "conflict-t2", "queued", "settings-conflict", "overwrite-confirm"}
BUSY_KINDS = {"busy", "unsaved-busy"}
SIZE_SM = {"discard-prompt", "overwrite-confirm"}
# kind -> the component the row must name (m5); SCR-029's own kinds are M17's (CMP-043 only).
COMPONENT = {
    "form": 'CMP-043 `role="dialog"`',
    "discard-prompt": 'CMP-044 `standard` `role="alertdialog"`',
    "settings-conflict": 'CMP-043 `role="alertdialog"`',
    "delete-confirm": 'CMP-044 `typed` `role="alertdialog"`',
    "overwrite-confirm": 'CMP-044 `standard` `role="alertdialog"`',
}
SAFE = ("Cancel", "Keep editing")
# MJ-3 (orchestrator text round 1): a dialog row's `initial focus:` clause is a safe label alone,
# or, on these frames only, the safe label with its qualifier as written; and no other clause that
# names focus moves it to a verb that is not safe, unless it is one of the clauses pinned here
# (each the return to the control that opened a layer, read as written).
FOCUS_QUALIFIED = {
    "SCR-029/unsaved-saving": "Cancel, unchanged",
    "SCR-029/conflict-refreshed": "Cancel, where the refresh puts it",
    "SCR-025/delete-racing": (
        "Cancel at open, and after the refusal focus stays on Delete workspace"
    ),
}
FOCUS_ALLOWED = {
    "SCR-029/keep-mine-confirm": (
        "Esc → Cancel (back to the conflict dialog, focus on Keep mine)",
        "(assertive, once), focus on Keep mine",
    ),
    "SCR-029/revert": (
        "focus back on the menu button whose menu holds Revert to saved…, or on the notice's own",
    ),
    "SCR-025/settings-conflict": (
        "and Load theirs puts the saved values in the form, clean, focus on Save",
    ),
}
DESTRUCTIVE = ("Discard changes", "Load theirs", "Keep mine", "Revert to saved")
UNVERBED = ("OK", "Yes", "No", "Confirm", "Discard", "Apply", "Done")
# The exits (A3): never gated anywhere in a row — a T2 clause, a footer note, the exits clause, the
# `Esc` mapping, the close button, or any sentence that pairs an exit with a gating word.
EXIT_RE = (
    r"\b(?:Cancel|Esc|Close|Discard(?: changes)?|Keep editing|Load theirs|Revert to saved)\b"
    r"|close " + TIMES
)
# MJ-2 (orchestrator text round 1): the vocabulary of a gated exit, read case-insensitively —
# a lock or T2, disabled or unavailable, greyed, dimmed, held, hidden, inactive, unusable, "can't
# be pressed" in any spelling, inert, ignored, "does nothing", not operable, suppressed, or an exit
# that waits for anything (the kill switch, a send, a timer).
GATED_RE = (
    r"(?i)\bT2\b|\block(?:ed)?\b|\bpadlock\b|\U0001f512|aria-disabled|\bdisabled\b"
    r"|\bunavailable\b|\bgated\b|\bblocked\b|\bgr[ae]yed(?: out)?\b|\bdimmed\b|\bheld\b"
    r"|\bhidden\b|\binactive\b|\bunusable\b|\bcan(?:not|'t|\u2019t| not) be (?:pressed|used"
    r"|activated|chosen|clicked|focused|operated|reached)\b|\binert\b|\bignor(?:ed|es)\b"
    r"|\bdoe?s? nothing\b|\bnot (?:operable|available|enabled|focusable)\b|\binoperable\b"
    r"|\bsuppress(?:ed|es)\b|\bwait(?:s|ing)?\b|\bdeferred\b|\bno-op\b|\bunresponsive\b"
)
# `Esc` only ever cancels (MJ-2): every `Esc` in a frame row, any case, is `Esc → Cancel`, an item
# of the row's `exits T1:` list, or inside one of these phrases, each pinned to its frame.
ESC_CONTEXTS = {
    "SCR-025/dirty": "with edits, Cancel, Esc, Close and a scrim press open "
    "`SCR-025/discard-prompt`",
}
NEGATED_RE = (
    r"\b(?:never|not|no|nor)\b (?:the |a |by |as )?"
    r"(?:T2|gated|lock(?:ed)?|`?disabled`?|`aria-disabled`|unavailable|dimmed|held|hidden"
    r"|inactive)\b"
)
# A planned inset (BQ-2 RULED) is a fixed sentence with three free parts: its place, its words and
# its caption (MJ4: an allow-list); the free parts are then read for control and dimming words.
PLANNED_HEAD = "the board's annotation layer, "
PLANNED_STAMP = 'the `planned` stamp, the words "'
PLANNED_TAIL = (
    "; full-strength `color.text.secondary` on `color.surface.raised`, `radius.card`; nothing "
    "operable and nothing focusable; the shipped dialog renders none of it (an absence by plan, §5)"
)
CONTROL_RE = (
    r"\bfield\b|\bwell\b|\bCMP-\d{3}\b|\btoggle\b|\bswitch\b|\bselect\b|\bcombobox\b|\blistbox\b"
    r"|\bradio|\bsegmented\b|\bcheckbox\b|\bpicker\b|\binput\b|\bdropdown\b|\bslider\b"
    r"|\bstepper\b|\btext ?(?:area|box)\b|\bbutton\b|\beditable\b|\boperable\b|\bfocusable\b|▾"
    r"|\[ \]"
)
DIM_RE = (
    r"\bT2\b|\block(?:ed)?\b|opacity|aria-disabled|color\.text\.disabled|\bdisabled\b|\bdimmed\b"
    r"|\bgr[ae]yed\b|\bfaded\b|\bmuted\b|\binert\b|\btranslucent\b|\bhalf\b|\bghost(?:ed)?\b"
)
T2_DIM_RE = r"opacity\.disabled|color\.text\.disabled"
# An environment control anywhere (BQ-8 RULED: none at all, not even contract-pending). MJ-1
# (orchestrator text round 1): the whole file is read — every row of every table, SCR-025's and
# SCR-029's frames included, and all prose — for the whole vocabulary, case-insensitive (`demo`,
# `live`, `testnet`, `mainnet`, `paper`, `env`, `environment`, `pin`, `pinned`, `pinning`, a
# `default environment`, CMP-074 / CMP-075). Each word must sit inside one of the phrases below,
# the spec's other senses and its statements of the absence, read as written (case-sensitive),
# and each phrase stands at most as often as pinned, so a copy of one in a new place fails too.
ENV_RE = (
    r"(?i:\b(?:demo|live|testnet|mainnet|paper(?:[- ]trad\w*)?|env|environments?|pins?|pinned"
    r"|pinning)\b)|\bCMP-07[45]\b"
)
ENV_ALLOWED: tuple[tuple[str, int], ...] = (
    ("the boards PR pins it", 1),
    ("account and environment semantics (E27, E28)", 1),
    ("**Inputs pinned.**", 1),
    ("stored fields only are drawn live", 2),
    ("**Deviation — the environment pin.**", 1),
    ('"this workspace is pinned to LIVE" warning, its control and its persistence', 1),
    ("the environment is never stored in a layout", 2),
    ("carries no environment control at all", 1),
    ("the stored fields live and the four planned insets", 1),
    ('environment pinning: the "pinned to LIVE" warning, unmissable', 1),
    ("(BQ-8 RULED): no environment control; D08-C4", 1),
    ("the LIVE-pinning warning drawn", 1),
    ("the pinned state; the account-scope", 1),
    ("stored fields only drawn live", 1),
    ("| BQ-8  | the environment pin ", 1),
    ("no environment control at all: D-7", 1),
    ("the ticket's pin, warning and chrome persistence", 1),
    ("the CMP-075 LIVE pill in a warning that cannot be dismissed", 1),
    ("the environment comes from the account a panel acts on", 2),
    ("the TopBar and its environment badge", 1),
    ("SCR-025 has no environment control", 2),
    ("the four planned insets live", 2),
    ("`sort_order` are stored and live but carry no control", 1),
    (
        (
            "**No environment control (BQ-8 RULED).** The environment comes from the "
            "account a panel acts on and is never stored in a layout (D-7 `D02:125`; "
            "C-2.11), so SCR-025 draws no environment control, no pin and no warning."
        ),
        1,
    ),
    ("The ticket's pin is the fourth deviation", 1),
    ("unique among the user's live workspaces", 1),
    ('aria-live="off"', 5),
    ("the account and environment legs never apply", 2),
    ("`workspace.environment_pinned{env}`", 3),
    ("Discard changes, live after CMP-044's `confirmDelayMs`", 1),
    ("the TopBar with its env band", 1),
    ("the TopBar with its environment badge", 1),
    ("no live region", 3),
    ("## 6. Exits, keyboard, focus and live regions", 1),
    ("the TopBar with its ENV band", 1),
    ("the shell's live regions", 1),
    ("never live: part of the description", 1),
    ("the edits live in the form", 1),
    ("`FLATTEN`, `LIVE`", 2),
    ('"pinned to LIVE" callout', 1),
    ('the "pinned to LIVE" item to the fourth deviation', 1),
    ("Only the stored fields are live", 1),
    ("a workspace stores no environment (E15-D02 D-7)", 1),
    ("(symbol, interval, environment binding)", 1),
    ("the environment pattern, should a per-workspace environment default ever be approved", 1),
    ("the CMP-075 LIVE pill in a CMP-028 warning callout", 1),
    (
        (
            "acts on LIVE; the pick never silent, a confirm naming LIVE before it is "
            "stored; the pinned state visible afterwards"
        ),
        1,
    ),
    ('the ticket\'s "pinned to LIVE" warning, its control and its persistence', 1),
    ("no environment control (the fourth deviation", 2),
    ("the pinned environment only if D08-G5 is approved", 1),
    ("the account and environment binding (D08-G2, D08-G5)", 1),
    ("default symbol/interval, environment binding, autosave toggle", 1),
    ("the environment: none (BQ-8 RULED; D08-C4)", 1),
    ("the environment the fourth deviation", 1),
    ("'this workspace is pinned to LIVE' warning drawn", 1),
    ("why none is an environment (BQ-8 RULED)", 1),
    ("DL-3, DoD-2 environment pinning", 1),
    ("(stored fields only; no environment control)", 1),
)
# MJ-4 (orchestrator text round 1): a "no dialog" route (BQ-11 RULED: D-9 stands) holds no
# prompt of any kind in its Route, outcome or Focus cell — no dialog, toast, confirm, question or
# warning added beside the words "no dialog" — but the import dialog's own trigger, which E5's
# focus returns to (pinned).
PROMPT_RE = (
    r"(?i)\b(?:asks?|asking|asked|prompts?|prompted|prompting|confirms?|confirmation|confirming"
    r"|toasts?|dialogs?|modals?|alerts?|alertdialog|pop-?ups?|questions?|warns?|warning"
    r"|interrupts?|save now)\b|\?|\bSCR-029\b|\bCMP-04[34]\b"
)
PROMPT_ALLOWED = {"E5": "the import dialog's trigger"}
# id | a ticket route (yes / no) | the words its Route cell holds | the frame it opens, or "none"
# (no dialog: the working copy is kept and the tab keeps its `*`).
ENTRY_TABLE = """
E1 | yes | navigating away | none
E2 | yes | switching workspace tab | none
E3 | yes | switching from SCR-011 | none
E4 | yes | applying a preset | SCR-029/unsaved
E5 | yes | importing | none
E6 | yes | closing the app | none
E7 | no | closing a workspace tab | none
E8 | no | Revert to saved | SCR-029/revert
E9 | no | deleting a workspace | SCR-025/delete-confirm
E10 | no | `Ctrl+S` answered `412` | SCR-029/conflict
E11 | no | autosave answered `412` | SCR-029/conflict-queued
E12 | no | closing SCR-025 with edits | SCR-025/discard-prompt
E13 | no | switching layouts in a workspace | none
E14 | no | deleting a layout with unsaved changes | E15-D02 Delete layout confirm
"""
# key | string | the doc that holds it verbatim, in quotes (E09-D09 §3.1, E15-D02 §8.1).
REASONS_TABLE = """
rbac.view_as | Read-only while viewing as {user}. | D09
rbac.permission | Your role can't save workspaces. | D02
notice.panel_read_only | Read-only — your role can't save workspaces. | D02
workspace.limit.last | You need at least one workspace. | D02
layout.limit.count | This workspace has the most layouts it can hold. | D02
"""
# string | doc | frames — upstream copy the frames quote verbatim (each must still exist upstream);
# the T2 reasons are REASONS_TABLE's and the frames' `keys` (no second gate on the same words).
UPSTREAM_TABLE = """
You have unsaved layout changes. | D02 | SCR-029/unsaved
Layout 1 in Scalping has changes that aren't saved. | D02 | SCR-029/unsaved
Applying Order-flow replaces them. | D02 | SCR-029/unsaved
Save layout keeps them in Layout 1 first; Discard changes loses them. | D02 | SCR-029/unsaved
This layout changed in another window. | D02 | SCR-029/conflict
Then Order-flow is applied. | D02 | SCR-029/conflict-from-preset
Changed again in another window. | D02 | SCR-029/conflict-refreshed
That name is already in use. | D02 | SCR-025/invalid-duplicate
Revert Layout 1 to the version saved at 13:40? Your unsaved changes are lost. | D02 | SCR-029/revert
Discard unsaved changes? | S4 | SCR-025/discard-prompt
Keep editing | S4 | SCR-025/discard-prompt
This workspace isn't saved. | D02 | SCR-025/viewer-read-only
""" + (f"min(size, 100vw {MINUS} 2 {TIMES} space.inset.lg) | S4 | SCR-025/reflow-200\n")
# The name rules (AC 6; BQ-4 RULED): rule -> (the error line, the summary link). `{max}` is `22`'s.
INVALID_RULES = {
    "empty": ("Enter a name.", "Name: enter a name."),
    "long": ("Use at most {max} characters.", "Name: use at most {max} characters."),
    "taken": ("That name is already in use.", "Name: that name is already in use."),
}
# The four deviations (the ruling and the ticket): name -> the words its line must carry.
DEVIATIONS = {
    "the deliverable path": "`docs/design/specs/e15-workspace-settings-and-conflicts.md`",
    "the branch": "`design/e15-workspace-settings-conflicts-hifi`",
    "the five fieldsets": "five fieldsets",
    "the environment pin": "pinned to LIVE",
}
AC_IDS = (
    [f"AC-{i}" for i in range(1, 7)]
    + [f"DL-{i}" for i in range(1, 10)]
    + [f"DoD-{i}" for i in range(1, 13)]
)
# The ruled outcomes a BQ row must keep (the orchestrator's ruling, 2026-10-25).
BQ_TERMS = {
    "BQ-2": ("stored fields only drawn live", "planned"),
    "BQ-8": ("no environment control at all",),
    "BQ-9": ("follows BQ-2",),
    "BQ-11": ("D-9 stands",),
    "BQ-12": ("That version can't be recovered.", "Save mine as new layout"),
}
# doc | line | frames — the upstream states the inventory reconciles with (E15-D02 §6, §5.10; `14`
# Validation, Type and the two checklists); each line's needle is its CITED_TABLE row.
RECONCILE_TABLE = """
D02 | 565 | SCR-025/discard-prompt, SCR-025/invalid-duplicate, SCR-025/delete-last
D02 | 565 | SCR-025/viewer-read-only, SCR-025/view-as
D02 | 569 | SCR-029/unsaved, SCR-029/revert, SCR-029/conflict, SCR-029/conflict-from-preset
D02 | 569 | SCR-029/save-as-t2, SCR-029/viewer-unsaved
D02 | 574 | SCR-029/conflict-refreshed
D02 | 505 | SCR-025/delete-confirm, SCR-025/delete-last
14 | 617 | SCR-025/delete-confirm, SCR-025/delete-last
14 | 624 | SCR-025/default, SCR-025/planned-defaults, SCR-025/discard-prompt
14 | 624 | SCR-025/delete-confirm, SCR-025/delete-last
14 | 664 | SCR-029/unsaved, SCR-029/conflict
14 | 671 | SCR-029/unsaved, SCR-029/conflict
"""
COPY_KEY_RE = (
    r"^(?:e15\.[a-z0-9_.]+|rbac\.[a-z_]+|notice\.[a-z_]+|workspace\.limit\.[a-z_]+"
    r"|layout\.limit\.[a-z_]+)$"
)
PLACEHOLDER_RE = r"\*\*Placeholder \(§(\d+)\):\*\* ([^\n]+)"
# §7's table: `| n | `fg` on `bg` | role | dark | light | hc | verdict | registered or PROPOSED |
# where |`, each cell the tool's value as printed (2 decimals, 4 within 0.005 of a bar), the verdict
# and the `pairs.mjs` column the tool's own words.
CONTRAST_ROW_RE = (
    r"^\| (\d+) +\| `([a-z0-9.-]+)` on `([a-z0-9.-]+)` +\| ([a-z-]+) +\| ([\d.]+) +\| ([\d.]+) +\|"
    r" ([\d.]+) +\| ([^|]+?) +\| (registered|PROPOSED) +\|"
)
# §7's greyscale rows (`| `token` | dark | light | hc |`) and colour-vision rows
# (`` `a` vs `b` | the four deltaE76 values | verdict |``): each value is the tool's section 3.
GREY_ROW_RE = r"^\| `([a-z0-9.-]+)` +\| (\d+) +\| (\d+) +\| (\d+) +\|"
CVD_ROW_RE = (
    r"`([a-z0-9.-]+)` vs `([a-z0-9.-]+)` +\| ([\d.]+) · ([\d.]+) · ([\d.]+) · ([\d.]+) +\|"
    r" ([^|\n]+?) +\|"
)
# Jargon and bare acknowledgements the copy deck (§8) never shows a user (its String column).
BANNED_COPY = (
    r"client-side",
    r"server-side",
    r"\bbackend\b",
    r"\bendpoint\b",
    r"\b409\b",
    r"\b412\b",
    r"\b422\b",
    r'"OK"',
    r'"Yes"',
)
FRAME_RE = r"^\| `((?:SCR-025|SCR-029)/[a-z0-9-]+)` +\|.*$"
BOARD_RE = r"^\| (\d\d) +\| `(E15-D08 / (\d\d) [a-z0-9-]+)` +\|(.*)$"
ENTRY_RE = r"^\| (E\d+) +\|(.*)$"
FRAME_NAME_RE = r"`((?:SCR-025|SCR-029)/[a-z0-9-]+)`"
# The written sections' fixed sentences: A3 as the header's standing additions quote the ruling
# and as §6 states it, and its row in §5.1 (MJ1); the planned insets' absence restated outside
# their rows (MJ4); the T2 paragraph's own sentences, each exactly once in the file and inside §5
# (m8: T2 is stated once).
A3_STANDING = (
    "**A3** the exits are never gated — Cancel, Esc, Discard and Close on every frame, never "
    "locked by view-as, the kill switch, a lockout or a state."
)
A3_SENTENCE = (
    "never T2, never held by a busy send, never locked by view-as, the kill switch, a risk "
    "lockout, a lost leg or any state"
)
EXITS_ROW = "Cancel, `Esc`, Close, Keep editing, Discard changes, Load theirs, Revert to saved"
PLANNED_CLAIMS = (
    (2, "never a control, never T2, never dimmed"),
    (5, "an absence is never a lock, never T2 and never dimmed"),
    (7, "full strength, never dimmed"),
)
# §2.3's planned row, whole (MAJOR-2: its place, its look and its focus cell are all binding, so
# any edit of it is a FAIL), and the rows that restate the absence: the ruled BQ-2 outcome, the
# default frame's row and the decision D08-D3.
PLANNED_ROW = (
    "planned-description, planned-defaults, planned-density, planned-theme",
    (
        "the board's annotation layer only, at the place its fieldset would take (Description "
        "under Name; Defaults for new panels between Workspace and Startup and saving; Appearance "
        "after Startup and saving, Density then Theme override): a `color.surface.raised` box, "
        "`radius.card`, padding `space.inset.md`; the `planned` stamp in `type.ui.label` + "
        "`color.text.primary`, the field words in `type.ui.body` + `color.text.secondary`, the "
        "caption in `type.ui.caption` + `color.text.secondary`, all at full strength; no CMP"
    ),
    "nothing in the shipped dialog: no Tab stop, no name, no announcement",
)
PLANNED_ROW_CLAIMS = (
    ("BQ-2", "never a control, never T2, never dimmed"),
    ("`SCR-025/default`", "the four planned insets live in the board's annotation layer only"),
    (
        "D08-D3",
        "live on board 01's annotation layer only, and the shipped dialog renders none of them",
    ),
)
# m3 (orchestrator text round 1): §2's two planned-inset paragraphs (found by their opening
# words) and its planned-inset table are read like an inset row's free words: no control word in
# the paragraphs or in a row's place, fields or reason, and no dimming or T2 word anywhere in them
# (a negated word — "never a control", "no field" — aside).
PLANNED_PARAS = (
    "The ticket's description, its **defaults** fieldset and its **appearance** fieldset",
    "So the ticket's five fieldsets map as:",
)
PLANNED_TABLE_HEAD = "| Planned inset "
NEG_WORD_RE = r"\b(?:never|not|no|nor|without)\b (?:a |an |the |as )?[\w`.-]+"
# m3: a sentence of §3's or §4's prose that has the dialog open, prompt or ask on a route that
# keeps the working copy (D-9; §3.2), unless the sentence negates it.
ROUTE_OPEN_RE = (
    r"(?i)\b(?:opens?|opening|opened|prompts?|asks?|raises?|appears?)\b[^.;|]{0,80}?\b(?:tab "
    r"switch|switch(?:es|ing)? (?:a |the )?(?:workspace )?tabs?|switching workspaces?|tab close"
    r"|clos(?:e|es|ing) (?:a |the )?(?:workspace )?tab|navigat\w+|import\w*|app close"
    r"|clos(?:e|es|ing) the app|layout switch|switching layouts|the rail)\b"
)
ROUTE_NEG_RE = r"(?i)\b(?:never|not|no|nor|nothing|instead)\b"
# m3: the full shas the spec may name — the base, the merged inputs and the two siblings merged as
# text (E15-D04 #4454, E15-D06 #4470); any other is a sibling pinned by mistake.
SIBLING_SHAS = (
    "c73aec08246f06d28c70e8b959c658bc1a0c4d09",
    "6e2c1211fc5f4675457d57011a346642f92710c5",
)
# m2 (orchestrator text round 1): RULED is the orchestrator's ruling, its comment named in the
# status line and in the questions' heading.
RULING = "6392398481"
T2_ONCE = (
    "E09-D09's decision rule decides every control here",
    "A T2 control keeps its native role and its full label",
)
SECTIONS = [str(n) for n in range(16)]
# The brief's A2 list: each of these must stay in `mutations()` (m11).
A2_NAMES = (
    "M1-dirty-star",
    "M2-t2-lock",
    "M3-reason-key",
    "M4-view-as-order",
    "M5-planned-control",
    "M6-planned-dim",
    "M7-cancel-first",
    "M8-focus-safe",
    "M9-esc-cancel",
    "M10-exit-gated",
    "M11-typed-field",
    "M12-consequence",
    "M13-overwrite-time",
    "M14-412",
    "M15-number",
    "M16-env-control",
    "M17-cmp-044",
)
# The gate codes no edit of the spec or of a cited plan text can trip, so no mutation stands
# behind them (m12): each checks the token files or this tool's own tables.
EXEMPT = {
    "token-missing": "a bound token resolves through the token JSON, not the spec",
    "contrast-fail": "a pair's ratio is measured from the token JSON; §7's cells are pinned",
    "reason-form": "checks REASONS_TABLE, this tool's own table, for length and full stop",
    "reconcile": "checks RECONCILE_TABLE against CITED_TABLE and KIND_TABLE, tool tables",
}
# §8's fixture column (MINOR-3 (c)): per key, the variables its templates are rendered with
# beyond the shared ones (`{workspace}`, `{layout}`, `{preset}`, `{user}`, `{max}`, `{name}`);
# a value naming a fixture or a contract fact is read from the tool, never typed. The diff keys
# render from the tool's summaries of the two fixtures.
DECK_VARS = {
    "e15.settings.name.counter": {"n": "name_max+1"},
    "e15.settings.summary.title": {"n": "one_invalid"},
    "e15.settings.fix_fields": {"n": "one_invalid"},
    "e15.settings.summary.link": {"message": "invalid_links"},
    "e15.settings.startup.help": {"workspace": "other_workspace"},
    "e15.delete.body": {"n": "layouts"},
    "e15.revert.title": {"hh:mm": "saved_time"},
    "e15.revert.done": {"hh:mm": "saved_time"},
    "e15.conflict.col_saved": {"hh:mm:ss": "conflict_time"},
    "e15.conflict.loaded": {"hh:mm": "conflict_hhmm"},
    "e15.conflict.confirm.title": {"hh:mm": "conflict_hhmm"},
    "e15.conflict.row_sentence": {"label": "row_label", "mine": "row_mine", "saved": "row_saved"},
}
DECK_FIXTURE_RE = r" · fixtures? (?=\")"
# The fixture strings §2, §3, §4 and §6 restate outside the frame rows (MINOR-3 (c)): section,
# the template (rendered with the tool's name maximum and times) and how many times its non-frame
# lines print it.
RESTATED = (
    (2, '"Up to {max} characters. Each workspace needs its own name."', 1),
    (2, '"{{n}} of {max} characters"', 1),
    (2, '"Use at most {max} characters."', 1),
    (2, '"Name: use at most {max} characters."', 1),
    (3, "Revert {layout} to the version saved at {saved}? Your unsaved changes are lost.", 1),
    (3, "{layout} reverted to the version saved at {saved}.", 1),
    (4, "Replace the version saved at {conflict}?", 1),
    (4, "Saved now ({conflict_full})", 1),
    (4, "Keep mine replaces the version saved at {conflict}.", 1),
    (6, "Saved now ({conflict_full})", 1),
)
# A marker that cannot sit beside its number (it would land inside a copy-ready code span) is
# detached: (the row id, the key) -> how many times the line prints its value (MINOR-3 (b): every
# occurrence on the line is counted, so a bumped one is a FAIL).
DETACHED = {
    ("D08-A10", "contract.name_min"): 1,
    ("D08-A10", "contract.name_max"): 2,
    ("D08-A17", "contract.conflict_ms"): 2,
}
MARKER_RE = r"<!-- audit:([A-Za-z0-9_.-]+)=(\S+) -->"
MARKER_LOOSE_RE = r"<!--\s*audit:[^\n]*?(?:-->|$)"
NUMBER_BEFORE_RE = r"\(?(\d[\d.:]*)"
# key count — every marker key the spec carries and how many times (MJ2 (b): a marker deleted is a
# FAIL); a new marker may be added freely, then pinned here.
MARKER_TABLE = """
boards 2
light_twins 2
mutations 2
fixture.layouts 2
contract.name_max 7
contract.name_min 3
contract.layouts_max 6
contract.dialog_md_px 6
contract.confirm_delay_ms 5
contract.conflict_ms 7
contract.control_comfortable 4
contract.control_compact 4
fixture.saved_time 1
fixture.conflict_time 1
fixture.refreshed_time 1
fixture.ac3.panels_added 2
fixture.ac3.symbols_changed 2
fixture.ac3.groups_added 2
fixture.overflow.panels_added 1
fixture.overflow.symbols_changed 2
fixture.list_cap 5
fixture.overflow.hidden 3
planned_insets 1
contract.reason_max 4
bq_rows 2
frames_total 2
frames_025 3
frames_029 4
frames_drawn 2
frames_not_drawn 2
redline.opacity.scrim 1
redline.space.dialog.padding 1
redline.space.stack.md 1
redline.radius.dialog 1
redline.space.stack.lg 1
redline.space.stack.xs 1
redline.space.inset.sm 1
redline.radius.control 1
redline.space.inset.md 1
redline.border.thick 1
redline.radius.card 1
contract.opacity_disabled 3
redline.border.focus 1
composite.dark 2
composite.light 2
composite.high-contrast 2
fixture.ac3.lines 2
fixture.overflow.lines 2
entry_ticket_routes 1
entry_rows 2
missing_tokens 2
contract.dialog_sm_px 1
contract.dialog_lg_px 1
pairs_rows 2
pairs_fail 2
pairs_registered 1
pairs_proposed 1
aaa_rows 2
aaa_met 2
checklist_items 2
deck_rows 1
rows.G 1
rows.C 1
rows.A 1
rows.Q 1
rows.D 1
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


def footer_table() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kinds, labels in rows(FOOTER_TABLE):
        for kind in kinds.split(", "):
            out[kind] = labels.split(" · ")
    return out


FOOTERS = footer_table()


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


def measure(themes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Section 1: every pair in three themes; section 3: greyscale and CVD (reported)."""
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    matrix: list[dict[str, Any]] = []
    fails = gated = proposed = aaa = aaa_met = 0
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
        if role == "aaa-target":
            aaa += 1
            met = ratios["high-contrast"] >= 7.0
            aaa_met += met
            verdict = "7:1 met" if met else "7:1 not met — shortfall stated (§7)"
        elif bars is None:
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
    composite: dict[str, float] = {}
    for th in THEMES:
        over = resolve(themes[th], "color.surface.overlay")
        label = verify.over(resolve(themes[th], "color.text.on-action"), over, 0.45)
        fill = verify.over(resolve(themes[th], "color.action.primary.default"), over, 0.45)
        composite[th] = round(ratio(label, fill), 2)
    cvd_rows: list[dict[str, Any]] = []
    for name, a, b in rows(CVD_TABLE):
        ha, hb = resolve(themes["dark"], a), resolve(themes["dark"], b)
        d = [cvd.delta_e76(ha, hb)] + [
            cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k)) for k in DEFICIENCIES
        ]
        verdict = "distinct" if min(d) >= JND else "collapses — words and glyph carry it"
        cvd_rows.append({"pair": name, "a": a, "b": b, "dE76": [round(x, 1) for x in d]})
        cvd_rows[-1]["verdict"] = verdict
    grey = {t: {th: luma(resolve(themes[th], t)) for th in THEMES} for t in GREY_TOKENS}
    return {
        "matrix": matrix,
        "composite": composite,
        "cvd": cvd_rows,
        "grey": grey,
        "pairs_rows": gated,
        "pairs_fail": fails,
        "pairs_registered": gated - proposed,
        "pairs_proposed": proposed,
        "aaa_rows": aaa,
        "aaa_met": aaa_met,
    }


def contract_facts(t: dict[str, str], themes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every contract fact a frame quotes, parsed from the plan and spec text; nothing is typed."""
    api = t["22"]
    w_in = api[api.index("    WorkspaceInput:") : api.index("    Workspace:\n")]
    delete = api[api.index("operationId: deleteWorkspace") :]
    delete = delete[: delete.index("operationId:", 30)]
    ws_ops = api[
        api.index("operationId: createWorkspace") : api.index("operationId: deleteWorkspace")
    ]
    icon = api[api.index("    WorkspaceIconToken:") : api.index("    WorkspaceInput:")]
    scr029 = t["14"][t["14"].index("### SCR-029") : t["14"].index("### SCR-030")]
    cmp043 = t["15"][t["15"].index("### CMP-043") : t["15"].index("### CMP-044")]
    cmp044 = t["15"][t["15"].index("### CMP-044") : t["15"].index("### CMP-045")]
    topics_23 = t["23"][t["23"].index("### 6.2 Private topics") :]
    topics_23 = topics_23[: topics_23.index("\n### ", 10)]
    sizes = re.search(r"at most (\d+) / (\d+) / (\d+) px wide", cmp043)
    d02 = t["D02"]
    table = d02[d02.index("Yours (not saved)") :].split("\n")[1:4]
    values = {}
    for line in table:
        parts = [p.strip() for p in re.split(r" {2,}", line.strip("│ ").rstrip()) if p.strip()]
        values[parts[0]] = parts[1:3]
    verb = first(r'`workspaces:write` → "([^"]+)"', t["D09"])
    template = first(r'\| `rbac\.permission` +\| "([^"]+)"', t["D09"])
    facts: dict[str, Any] = {
        "name_min": int(first(r"minLength: (\d+)", w_in)),
        "name_max": int(first(r"maxLength: (\d+)", w_in)),
        "workspace_input_fields": re.findall(r"^        (\w+):", w_in, MULTI),
        "icon_tokens": first(r"enum: \[([^\]]+)\]", icon).split(", "),
        "last_workspace_message": first(r'message: "([^"]+)"', delete),
        "version_conflict_412": bool(re.search(r"- code: version_conflict\n\s+status: 412", api)),
        "refusal_codes": [
            c
            for c in ("name_taken", "concurrent_update", "store_unavailable")
            if re.search(rf"\b{c}\b", ws_ops)
        ],
        "layouts_max": int(first(r"`limit_reached` \((\d+) live layouts\)", api)),
        "workspaces_max": int(first(r"`limit_reached` \((\d+) live workspaces\)", api)),
        "settings_density": first(r"density: \{ type: string, enum: \[([^\]]+)\] \}", api).split(
            ", "
        ),
        "settings_default_environment": "default_environment: { $ref:" in api,
        "conflict_ms": int(first(r"within (\d+) ms of the conflicting write", scr029)),
        "dialog_px": [int(x) for x in sizes.groups()] if sizes else [],
        "confirm_delay_ms": int(first(r"`confirmDelayMs\?` \(default (\d+)", cmp044)),
        "reason_max": int(first(r"One sentence, ≤ (\d+) characters", t["D09"])),
        "permission_sentence": template.replace("{verb}", verb),
        "ws_topics": re.findall(r"^\| `(\w+)` +\|", topics_23, MULTI),
        "saved_time": first(r"the version saved at (\d\d:\d\d)\? Your unsaved changes", d02),
        "conflict_time": first(r"Saved now \((\d\d:\d\d:\d\d)\)", d02),
        "conflict_table": values,
        "reflow_frame": first(rf"200 % zoom on the (\d+ {TIMES} \d+) frame", t["S4"]),
        "control_compact": int(resolve(themes["dark"], "size.control.compact")),
        "control_comfortable": int(resolve(themes["dark"], "size.control.comfortable")),
        "opacity_disabled": float(resolve(themes["dark"], "opacity.disabled")),
    }
    facts["ws_layout_topic"] = any(re.search("workspace|layout", x) for x in facts["ws_topics"])
    facts["unstored_absent"] = not any(
        f in facts["workspace_input_fields"]
        for f in ("description", "density", "theme", "default_symbol", "account", "environment")
    )
    return facts


def render_summary(case: dict[str, Any]) -> list[str]:
    """The difference summary (BQ-14 RULED): one sentence per kind of change, in this order; a list
    names at most `list_cap` items and the last line counts every item left out."""
    cap, hidden, out = int(FIXTURE["list_cap"]), 0, []

    def say(key: str, n: int, items: list[str] | None = None) -> None:
        nonlocal hidden
        one, many = DIFF_TEMPLATES[key]
        text = (one if n == 1 else many).format(n=n, items=", ".join((items or [])[:cap]))
        hidden += max(0, len(items or []) - cap)
        out.append(text)

    if case.get("panels_added"):
        say("panels_added", int(case["panels_added"]))
    if case.get("panels_removed"):
        say("panels_removed", int(case["panels_removed"]))
    pairs = [f"{a} → {b}" for a, b in case.get("pairs", [])]
    if pairs:
        say("symbols_changed", len(pairs), pairs)
    for key in ("groups_added", "groups_removed"):
        if case.get(key):
            say(key, len(case[key]), list(case[key]))
    if case.get("other"):
        say("other", int(case["other"]))
    if hidden:
        one, many = DIFF_TEMPLATES["overflow"]
        out.append((one if hidden == 1 else many).format(n=hidden))
    return out


def frame_time(params: dict[str, str], facts: dict[str, Any]) -> str:
    return str(
        FIXTURE["refreshed_time"] if params.get("time") == "refreshed" else facts["conflict_time"]
    )


def consequence(lines: dict[str, str], full_time: str) -> dict[str, str]:
    return {
        verb: text.format(hhmm=full_time[:5], layout=FIXTURE["layout"])
        for verb, text in lines.items()
    }


def table_text(facts: dict[str, Any]) -> str:
    """The side-by-side summary as the conflict rows spell it, from E15-D02's table (`D02:439`)."""
    parts = []
    for label, (mine, saved) in facts["conflict_table"].items():
        parts.append(f"{label} — yours {mine}, saved now {saved}")
    return " · ".join(parts)


READ: dict[Path, str] = {}


def read_once(path: Path) -> str:
    if path not in READ:
        READ[path] = path.read_text(encoding="utf-8")
    return READ[path]


def fail(code: str, msg: str) -> str:
    """A FAIL line led by its gate code; `--self-test` checks every code has a mutation (m12)."""
    return f"[{code}] {msg}"


def frame_rows(spec: str) -> list[tuple[str, list[str], str]]:
    """(frame, cells, the whole line) for every frame row of §2-§4."""
    out = []
    for m in re.finditer(FRAME_RE, section(spec, 2, 5), MULTI):
        c = cells(m.group(0))
        out.append((c[0].strip("`"), c, m.group(0)))
    return out


def clause(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)} ([^;|]+)", text)
    return m.group(1).strip() if m else ""


def footer_items(shows: str) -> list[tuple[str, str]]:
    out = []
    for item in [i.strip() for i in clause(shows, "footer:").split(" · ") if i.strip()]:
        m = re.match(r"(.+?)\s*(?:\((.*)\))?$", item)
        out.append(((m.group(1) if m else item).strip(), (m.group(2) or "") if m else ""))
    return out


def legs(text: str) -> list[str] | None:
    m = re.search(r"legs ((?:`[a-z_.]+`\s*(?:→\s*)?)+)", text)
    return re.findall(r"`([a-z_.]+)`", m.group(1)) if m else None


def t2_clauses(shows: str) -> list[str]:
    """Every `T2:` clause of a Shows cell (a row may carry more than one)."""
    return [m.group(1) for m in re.finditer(r"T2: ([^;|]+)", shows)]


def t2_controls(text: str) -> list[str]:
    """The controls a `T2:` clause gates: its list up to the first "(", `(also …)` aside."""
    head = re.sub(r" \(also [^()]*\)", "", text).split(" (")[0]
    return [n.strip() for n in re.split(r", | and ", head) if n.strip()]


def plain(text: str) -> str:
    """A clause with its quoted copy and its negated gating words taken out (`never T2`)."""
    return re.sub(NEGATED_RE, "", re.sub(r'"[^"]*"', '""', text))


def exit_gated(shows: str, items: list[tuple[str, str]]) -> bool:
    """A3 / M10: an exit drawn gated anywhere in the row (MJ1)."""
    if any(re.search(EXIT_RE, plain(c)) for c in t2_clauses(shows)):
        return True
    if any(re.fullmatch(EXIT_RE, lab) and re.search(GATED_RE, note) for lab, note in items):
        return True
    if any(re.search(GATED_RE, plain(i)) for i in clause(shows, "exits T1:").split(" · ")):
        return True
    for part in shows.split(";"):
        part = part.strip()
        if part.startswith(("footer:", "exits T1:")):
            continue
        text = plain(part.split("T2:")[0])
        if re.search(EXIT_RE, text) and re.search(GATED_RE, text):
            return True
    return False


def esc_cancels(name: str, shows: str) -> bool:
    """MJ-2: every `Esc` of a row, any case, maps to Cancel (`Esc → Cancel`), is an item of its
    `exits T1:` list, sits in its frame's pinned ESC_CONTEXTS phrase, or sits in a clause that
    gates an exit (exit-gated's FAIL)."""
    text = re.sub(r'"[^"]*"', '""', shows)
    spans: list[tuple[int, int]] = []
    exits = clause(text, "exits T1:")
    if exits:
        at = text.find("exits T1: " + exits)
        spans.append((at, at + len("exits T1: " + exits)))
    context = ESC_CONTEXTS.get(name)
    if context and context in text:
        at = text.find(context)
        spans.append((at, at + len(context)))
    # An `Esc` with no arrow in a clause that gates an exit is exit-gated's (M10): one FAIL.
    gated: list[tuple[int, int]] = []
    at = 0
    for part in text.split(";"):
        if re.search(GATED_RE, plain(part)):
            gated.append((at, at + len(part)))
        at += len(part) + 1
    for m in re.finditer(r"(?i)\besc\b", text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        rest = text[m.end() :]
        if re.match(r"\s*(?:→|->)", rest):
            if m.group(0) != "Esc" or not re.match(r" → Cancel(?![\w-])", rest):
                return False
        elif not any(a <= m.start() < b for a, b in gated):
            return False
    return True


def focus_moved(name: str, shows: str) -> bool:
    """MJ-3: a clause of a dialog row, other than its `initial focus:` one, that names focus and
    then a footer verb that is not safe moves focus off the safe action (FOCUS_ALLOWED aside)."""
    verbs = sorted({v for vs in FOOTERS.values() for v in vs} - set(SAFE), key=len, reverse=True)
    verb_re = r"\b(?:" + "|".join(re.escape(v.rstrip("…")) for v in verbs) + r")"
    for part in re.sub(r'"[^"]*"', '""', shows).split(";"):
        part = part.strip()
        for allowed in FOCUS_ALLOWED.get(name, ()):
            part = part.replace(allowed, "")
        if part.startswith("initial focus:"):
            continue
        m = re.search(r"(?i)(?<!\bno )\bfocus\b", part)
        if m and re.search(verb_re, part[m.end() :]):
            return True
    return False


def star_spans(text: str) -> list[str]:
    return re.findall(STAR_SPAN, text)


def board_cell_ok(board: str) -> bool:
    nums = re.findall(r"\d\d", board)
    return bool(re.fullmatch(r"\d\d(?:, \d\d)*(?: \(inset\))?", board)) and all(
        1 <= int(n) <= BOARD_CAP for n in nums
    )


def class_gates(name: str, kind: str, cls: str) -> list[str]:
    """The Class cell agrees with the tool's KIND (it never decides)."""
    bad: list[str] = []
    if kind in T2_KINDS and not re.search(r"\bT2\b", cls):
        bad.append(fail("class-t2", f"Class cell disagrees with the tool's KIND: {name} is T2"))
    if kind not in T2_KINDS and re.search(r"\bT2\b", cls):
        bad.append(fail("class-not-t2", f"Class cell disagrees with the KIND: {name} is not T2"))
    for want, kinds_ in (
        ("validity look", VALIDITY_KINDS),
        ("busy", BUSY_KINDS),
        ("outcome", {"outcome"}),
        ("T4", {"refusal", "delete-racing"}),
        ("absence (planned)", {"planned"}),
    ):
        if kind in kinds_ and want not in cls:
            bad.append(fail("class-word", f"Class cell disagrees with the KIND: {name} is {want}"))
    return bad


def star_gates(
    name: str, kind: str, params: dict[str, str], producer: str, shows: str
) -> list[str]:
    """M1 and its inverse: the screen's dirty marker on every dirty frame, none on a clean one."""
    mark = DIRTY_MARK[name.split("/")[0]]
    if params.get("star") == "producer":
        if f"{FIXTURE['layout']} `*`" not in producer:
            return [fail("dirty-star", f"dirty frame {name} without its `*` (in its producer)")]
        if star_spans(shows):
            return [fail("clean-star", f"clean frame {name} draws a dirty `*` in its Shows cell")]
        return []
    if kind in DIRTY_KINDS:
        if mark not in shows:
            return [fail("dirty-star", f"dirty frame {name} without its `*` ({mark} in Shows)")]
        return []
    if star_spans(producer + shows):
        return [fail("clean-star", f"clean frame {name} draws a dirty `*`")]
    return []


def planned_gates(name: str, params: dict[str, str], shows: str) -> list[str]:
    """M5, M6 (MJ4): a planned inset is the fixed sentence; its free words are never a control,
    never T2, never dimmed, and carry the caption naming its G-row."""
    if not (
        shows.startswith(PLANNED_HEAD) and shows.endswith(PLANNED_TAIL) and PLANNED_STAMP in shows
    ):
        return [fail("planned-form", f"planned inset {name} is not the fixed inset sentence")]
    bad: list[str] = []
    free = shows.removeprefix(PLANNED_HEAD).removesuffix(PLANNED_TAIL)
    caption = f'"Waits for its contract ({params["gap"]})."'
    if caption not in free:
        bad.append(fail("planned-caption", f"planned inset {name} without its contract caption"))
    words = free.replace(caption, '""')
    if re.search(CONTROL_RE, words):
        bad.append(fail("planned-control", f"planned inset {name} drawn as a control"))
    if re.search(DIM_RE, words):
        bad.append(fail("planned-dim", f"planned inset {name} marked T2 or dimmed"))
    return bad


def t2_gates(name: str, kind: str, params: dict[str, str], c: list[str]) -> list[str]:
    """M2-M4 and the rest of E09-D09's T2 form, per gated row (A1)."""
    bad: list[str] = []
    shows, keys, line = c[2], c[4], " | ".join(c)
    clauses = t2_clauses(shows)
    lock_ok = bool(clauses)
    for cl in clauses:
        gated = [n for n in t2_controls(cl) if not re.fullmatch(EXIT_RE, n)]
        lock_ok = (
            lock_ok and ("the lock leading each" if len(gated) > 1 else "the lock leading") in cl
        )
    if not lock_ok:
        bad.append(fail("t2-lock", f"T2 frame {name} draws no lock leading each gated label"))
    want = params["keys"].split(",")
    for key in want:
        if f"`{key}`" not in shows:
            bad.append(fail("t2-key", f"T2 frame {name} lacks its reason key {key} in Shows"))
        if f"`{key}`" not in keys:
            bad.append(
                fail("t2-key-cell", f"T2 frame {name} lacks its reason key {key} in Copy keys")
            )
    reason = REASONS[want[0]].format(user=FIXTURE["target"])
    if f'"{reason}"' not in shows:
        bad.append(fail("t2-say", f"T2 frame {name} does not quote its reason {reason!r}"))
    order = legs(shows)
    if order is None:
        bad.append(fail("legs", f"T2 frame {name} lacks its legs (view-as first)"))
    elif order[0] != "rbac.view_as":
        bad.append(fail("legs-order", f"view-as leg not first in {name}: {' → '.join(order)}"))
    if re.search(T2_DIM_RE, line):
        bad.append(fail("t2-dim", f"T2 frame {name} conveyed by dimming"))
    if "§5" not in line:
        bad.append(fail("t2-cite", f"T2 frame {name} does not cite §5 (T2 stated once)"))
    if "`disabled`" in re.sub(r"never (?:the )?`disabled`", "", line):
        bad.append(fail("t2-native", f"T2 frame {name} drawn with the native `disabled` attribute"))
    if kind == "t2-state" and ("aria-describedby" not in line or "aria-disabled" not in line):
        bad.append(fail("t2-sr", f"disabled delete lacks its reason for a screen reader in {name}"))
    outside = re.sub(r"T2: [^;|]+", "", shows)
    if re.search(r"\block(?:ed)?\b|\bpadlock\b", plain(outside)):
        bad.append(fail("t2-lock-scope", f"a lock drawn outside the T2 clause of {name}"))
    controls = [n for cl in clauses for n in t2_controls(cl)]
    for label, note in footer_items(shows):
        if not re.fullmatch(EXIT_RE, label) and (label in controls) != bool(
            re.search(r"\bT2\b", note)
        ):
            bad.append(fail("t2-footer", f"footer of {name} and its T2 clause disagree on {label}"))
    return bad


REASONS = {key: string for key, string, _ in rows(REASONS_TABLE)}


def frame_gates(spec: str, facts: dict[str, Any], deck: set[str] | None) -> list[str]:
    """The per-frame gates (A2: M1-M17 and the rest). A frame's obligations come from KIND."""
    bad: list[str] = []
    seen: dict[str, int] = {}
    for name, c, line in frame_rows(spec):
        seen[name] = seen.get(name, 0) + 1
        if name not in KIND:
            continue
        if len(c) != 6:
            bad.append(fail("cells", f"frame {name}: {len(c)} cells, six expected"))
            continue
        kind, params = KIND[name]
        producer, shows, cls, keys, board = c[1], c[2], c[3], c[4], c[5]
        bad += class_gates(name, kind, cls)
        if board != NOT_DRAWN and not board_cell_ok(board):
            bad.append(fail("board-cell", f"frame {name} without a board or the not-drawn cell"))
        for key in re.findall(r"`([^`]+)`", keys):
            if not re.fullmatch(COPY_KEY_RE, key):
                bad.append(
                    fail("key-namespace", f"copy key outside the namespaces in {name}: {key}")
                )
            elif deck is not None and key not in deck:
                bad.append(fail("key-deck", f"copy key not in the deck (§8) in {name}: {key}"))
        bad += star_gates(name, kind, params, producer, shows)
        layout_n = FIXTURE["layout"].split(" ")[-1]
        if any(n != layout_n for n in re.findall(r"\bLayout (\d+)\b", line)):
            bad.append(
                fail("fixture-name", f"frame {name} names a layout other than the fixture's")
            )
        if kind == "planned":
            bad += planned_gates(name, params, shows)
        if kind in T2_KINDS:
            bad += t2_gates(name, kind, params, c)
        if kind in ONE_NOTICE_KINDS and "one notice" not in shows:
            bad.append(fail("one-notice", f"read-only frame {name} without its one notice"))
        if kind in VALIDITY_KINDS:
            if "validity-reason" not in line:
                bad.append(fail("validity-reason", f"validity frame {name} without its reason"))
            if re.search(r"\block(?:ed)?\b|\bpadlock\b|\U0001f512", plain(line)):
                bad.append(fail("validity-lock", f"validity frame {name} with a lock"))
        bad += dialog_gates(name, kind, params, shows)
        bad += content_gates(name, kind, params, producer, shows, facts)
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


def dialog_gates(name: str, kind: str, params: dict[str, str], shows: str) -> list[str]:
    """M7-M10, M17, MJ8 and AC 1: the footer's verbs, order and weights, initial focus, every
    `Esc`, the exits, the component and its size."""
    bad: list[str] = []
    items = footer_items(shows)
    labels = [label for label, _ in items]
    want = FOOTERS.get(kind)
    if want is not None:
        if any(label in UNVERBED for label in labels):
            bad.append(fail("unverbed", f"unverbed button in {name}"))
        elif sorted(labels) != sorted(want):
            bad.append(fail("footer-set", f"footer of {name} is not {' · '.join(want)}"))
        elif labels[0] not in SAFE:
            bad.append(fail("safe-first", f"safe action not first in the footer of {name}"))
        elif labels != want:
            bad.append(fail("footer-order", f"footer of {name} out of D08-D16's order"))
        for i, (label, note) in enumerate(items):
            weighted = re.search(r"`(?:primary|danger)`", note)
            if label in SAFE and "`secondary`" not in note:
                bad.append(fail("safe-weight", f"safe action {label} not `secondary` in {name}"))
            elif label in DESTRUCTIVE and weighted:
                bad.append(
                    fail("x1-weight", f"destructive choice carries primary weight in {name}")
                )
            elif weighted and label not in SAFE + DESTRUCTIVE and i != len(items) - 1:
                bad.append(fail("primary-last", f"primary or danger {label} not last in {name}"))
    if kind in DIALOG_KINDS:
        first_focus = clause(shows, "initial focus:")
        if first_focus not in (*SAFE, FOCUS_QUALIFIED.get(name)):
            bad.append(fail("focus-safe", f"initial focus not on the safe action in {name}"))
        elif focus_moved(name, shows):
            bad.append(fail("focus-moved", f"a clause moves focus off the safe action in {name}"))
    if not esc_cancels(name, shows) or (kind in EXIT_KINDS and "Esc → Cancel" not in shows):
        bad.append(fail("esc", f"Esc not mapped to Cancel in {name}"))
    if kind in EXIT_KINDS:
        exits = [e.strip() for e in clause(shows, "exits T1:").split(" · ")]
        if not (set(exits) & set(SAFE)) or "Esc" not in exits:
            bad.append(fail("exits-t1", f"frame {name} without its T1 exits (Cancel and Esc)"))
    if exit_gated(shows, items):
        bad.append(fail("exit-gated", f"exit drawn gated in {name}"))
    if kind in SCR029_DIALOG_KINDS and (
        'CMP-043 `role="alertdialog"`' not in shows or "CMP-044" in shows
    ):
        bad.append(fail("cmp-043", f"SCR-029 dialog {name} not a CMP-043 alertdialog"))
    comp = COMPONENT.get(kind)
    if comp:
        other = "alertdialog" if kind == "form" else "CMP-04" + ("4" if "CMP-043" in comp else "3")
        if comp not in shows or other in shows:
            bad.append(fail("component", f"frame {name} is not {comp}"))
    sizes = re.findall(r'`size="(\w+)"`', shows)
    expect = params.get("size") or ("sm" if kind in SIZE_SM else "md")
    if ("size" in params and not sizes) or any(s != expect for s in sizes):
        bad.append(fail("size", f'frame {name} does not state `size="{expect}"` (D08-D25)'))
    return bad


def content_gates(
    name: str,
    kind: str,
    params: dict[str, str],
    producer: str,
    shows: str,
    facts: dict[str, Any],
) -> list[str]:
    """The kind's own content, rendered from FIXTURE and the parsed facts (MJ2 (d)): summaries,
    consequence lines, the typed field, the refusals, the routes, every quoted number."""
    bad: list[str] = []
    line = producer + " | " + shows
    delay, name_max, fx = facts["confirm_delay_ms"], facts["name_max"], FIXTURE
    saved, hhmm = str(facts["saved_time"]), str(facts["conflict_time"])[:5]
    if kind in BUSY_KINDS and ("`loading`" not in shows or "`aria-busy`" not in shows):
        bad.append(fail("busy", f"busy frame {name} not in the busy form"))
    if kind == "outcome" and (SAVED_SENTENCE not in shows or "polite" not in shows):
        bad.append(fail("outcome", f"terminal state {name} without its polite announcement"))
    if kind == "form" and NAME_HELP.format(max=name_max) not in shows:
        bad.append(fail("name-help", f"frame {name} lacks the name's help with its maximum"))
    if kind == "form-dirty" and DIRTY_PRODUCER.format(renamed=fx["renamed"]) not in producer:
        bad.append(fail("dirty-fixture", f"dirty frame {name} lacks its fixture edit"))
    if kind == "invalid":
        message, link = (x.format(max=name_max) for x in INVALID_RULES[params["rule"]])
        need = [f'"{message}"', f'"{link}"', "error summary", *ONE_INVALID]
        if params["rule"] == "long":
            need += [f'"{name_max + 1}/{name_max}"', LONG_PRODUCER.format(n=name_max + 1)]
        if params["rule"] == "taken":
            need.append("`409 name_taken`")
        if any(n not in line for n in need):
            bad.append(
                fail("invalid", f"invalid-name frame {name} lacks its rule, summary or fixture")
            )
    if kind == "refusal" and (
        "`503 store_unavailable`" not in producer or "`409 concurrent_update`" not in shows
    ):
        bad.append(fail("refusal", f"failed frame {name} lacks its refusals"))
    if kind == "delete-confirm":
        typed = [TYPED_LABEL.format(workspace=fx["workspace"]), *TYPED_RULES]
        if any(x not in shows for x in typed):
            bad.append(fail("typed-field", f"delete frame {name} lacks the typed field"))
        if DELETE_BODY.format(n=fx["layouts"], layout=fx["layout"]) not in shows:
            bad.append(fail("delete-body", f"delete frame {name} lacks its body with the loss"))
        if DELETE_PRODUCER.format(workspace=fx["workspace"], n=fx["layouts"]) not in producer:
            bad.append(fail("delete-fixture", f"delete frame {name} lacks its fixture"))
    if kind in ("delete-confirm", "overwrite-confirm", "discard-prompt") and (
        f"`confirmDelayMs` {delay}" not in shows
    ):
        bad.append(fail("confirm-delay", f"confirm {name} lacks its confirm delay"))
    if kind == "delete-racing" and (
        "`409 last_workspace`" not in producer or RACING_LINE not in shows
    ):
        bad.append(fail("racing", f"racing delete {name} lacks its refusal"))
    if kind in CONFLICT_412_KINDS and "412" not in producer:
        bad.append(fail("conflict-412", f"conflict frame {name} without its `412` producer"))
    if "diff" in params:
        sentences = render_summary(fx[params["diff"]])
        overflow = sentences[-1] if sentences[-1].startswith("and ") else ""
        if any(f'"{s}"' not in shows for s in sentences if s != overflow):
            bad.append(fail("summary", f"difference summary differs from the fixture in {name}"))
        if overflow and f'"{overflow}"' not in shows:
            bad.append(fail("overflow", f"overflow line missing in {name}"))
    if params.get("diff") == "overflow":
        case = fx["overflow"]
        want = OVERFLOW_PRODUCER.format(panels=case["panels_added"], symbols=len(case["pairs"]))
        if want not in producer:
            bad.append(fail("overflow-producer", f"frame {name} lacks its overflow fixture"))
    if kind == "settings-conflict" and any(
        f'"{fx[k]}"' not in shows for k in ("renamed", "renamed_elsewhere")
    ):
        bad.append(fail("settings-names", f"settings conflict {name} lacks the two names"))
    if kind in ("conflict", "settings-conflict"):
        bad += consequence_gates(name, kind, params, shows, facts)
    if kind == "conflict" and KEEP_ROUTE not in shows:
        bad.append(
            fail("keep-route", f"conflict frame {name}: Keep mine does not open its confirm")
        )
    if params.get("loaded") and LOADED_LINE.format(layout=fx["layout"], hhmm=hhmm) not in shows:
        bad.append(fail("loaded-line", f"conflict frame {name} lacks Load theirs' outcome line"))
    if params.get("time") == "refreshed" and (
        REFRESHED_PRODUCER.format(time=fx["refreshed_time"]) not in producer
    ):
        bad.append(fail("refreshed-time", f"refreshed conflict {name} lacks its third write"))
    if kind == "conflict-t2" and BY_REFERENCE not in shows:
        bad.append(fail("by-reference", f"frame {name} does not keep SCR-029/conflict's content"))
    if kind == "unsaved-busy" and any(r not in shows for r in SAVING_ROUTES):
        bad.append(fail("saving-routes", f"saving frame {name} lacks its `412` routes"))
    if kind == "revert" and (
        REVERT_AGAINST.format(hhmm=saved) not in shows
        or REVERT_DONE.format(layout=fx["layout"], hhmm=saved) not in shows
    ):
        bad.append(fail("revert-done", f"revert frame {name} lacks its saved time"))
    if "layout.limit.count" in params.get("keys", "") and (
        CAP_PRODUCER.format(n=facts["layouts_max"]) not in producer
    ):
        bad.append(fail("save-as-cap", f"frame {name} lacks the layout limit it reached"))
    if kind == "overwrite-confirm":
        title = OVERWRITE_TITLE.format(hhmm=hhmm)
        keep = consequence(LAYOUT_LINES, str(facts["conflict_time"]))["Keep mine"]
        if title not in shows or f'"{keep}"' not in shows:
            bad.append(
                fail(
                    "overwrite", f'overwrite confirm {name} lacks its time or "can\'t be recovered"'
                )
            )
    queue = [QUEUE_RULE, f"within {facts['conflict_ms']} ms"]
    queue += [x.format(layout=fx["layout"]) for x in QUEUED_LINES]
    if kind == "queued" and any(x not in shows for x in queue):
        bad.append(fail("queue-rule", f"queued conflict {name} lacks the queue rule"))
    if kind in ("form", "t2-state") and any(x not in shows for x in DANGER_WORDS):
        bad.append(fail("danger-words", f"frame {name}: the danger zone not named in words"))
    if kind == "reflow" and REFLOW_PRODUCER.format(frame=facts["reflow_frame"]) not in producer:
        bad.append(fail("reflow", f"reflow frame {name} lacks its zoom on its frame"))
    return bad


def consequence_gates(
    name: str, kind: str, params: dict[str, str], shows: str, facts: dict[str, Any]
) -> list[str]:
    """M12, AC 4: the side-by-side summary and one consequence line per verb, in footer order."""
    bad: list[str] = []
    full = frame_time(params, facts)
    heads = ['"Yours (not saved)"', f'"Saved now ({full})"']
    if params.get("table") == "yes":
        heads.append(table_text(facts))
    if any(h not in shows for h in heads):
        bad.append(fail("side-by-side", f"conflict frame {name} lacks the side-by-side summary"))
    lines = consequence(LAYOUT_LINES if kind == "conflict" else SETTINGS_LINES, full)
    what = "conflict verb" if kind == "conflict" else "settings conflict verb"
    for verb, text in lines.items():
        if f'"{text}"' not in shows:
            bad.append(fail("consequence", f"{what} {verb} lacks its consequence line in {name}"))
    at = [shows.find(f'"{lines[label.rstrip("…")]}"') for label in FOOTERS[kind]]
    if all(a >= 0 for a in at) and at != sorted(at):
        bad.append(fail("consequence-order", f"consequence lines of {name} out of footer order"))
    return bad


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
        if export != f"`docs/design/E15/img/E15-D08-{num}-{slug}.png`":
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


def entry_gates(spec: str) -> tuple[list[str], dict[str, int]]:
    """§3.2: every route maps to a frame or to "no dialog", with its Esc (AC 2, BQ-11 RULED)."""
    bad: list[str] = []
    s3 = section(spec, 3, 4)
    found = {m.group(1): cells("|" + m.group(2)) for m in re.finditer(ENTRY_RE, s3, MULTI)}
    present = {name for name, _, _ in frame_rows(spec)}
    for eid, ticket, words, target in rows(ENTRY_TABLE):
        c = found.get(eid)
        if c is None or len(c) < 4:
            bad.append(fail("entry-missing", f"entry-point matrix lacks {eid} ({words})"))
            continue
        route, outcome, esc = c[0], c[1], c[2]
        if words not in route or (ticket == "yes") != ("(ticket)" in route):
            bad.append(fail("entry-route", f"entry point {eid}: its route cell is not {words!r}"))
        if target == "none":
            ok = outcome.startswith("no dialog —") and re.search(STAR_SPAN, outcome)
            if not ok:
                bad.append(fail("entry-unmapped", f"entry point unmapped: {eid} ({words})"))
            if esc != "— (no dialog)":
                bad.append(
                    fail("entry-esc-none", f"entry point {eid}: Esc cell {esc!r}, no dialog")
                )
            words_ = " | ".join((route, outcome.removeprefix("no dialog —"), c[3]))
            if ok and re.search(PROMPT_RE, words_.replace(PROMPT_ALLOWED.get(eid, "\0"), "")):
                bad.append(fail("entry-prompt", f"a prompt on the no-dialog route {eid}"))
        else:
            if (f"`{target}`" not in outcome and target in present) or outcome.startswith("no "):
                bad.append(fail("entry-unmapped", f"entry point unmapped: {eid} ({words})"))
            if esc != "Esc → Cancel":
                bad.append(fail("entry-esc", f"Esc not mapped to Cancel on entry point {eid}"))
    numbers = {
        "entry_rows": len(found),
        "entry_ticket_routes": sum("(ticket)" in c[0] for c in found.values() if c),
        "entry_no_dialog": sum(c[1].startswith("no dialog") for c in found.values() if len(c) > 1),
    }
    return bad, numbers


def head_gates(spec: str) -> tuple[list[str], dict[str, int]]:
    """The header, the deviations, the AC trace and the ruled questions."""
    bad: list[str] = []
    head = spec[: spec.find("\n## ")]
    bad += [
        fail("head-sha", f"header: merge sha missing: {s[:9]}") for s in MERGE_SHAS if s not in head
    ]
    if BASE not in head:
        bad.append(fail("head-base", "header: the base sha is missing"))
    status = first(r"(\*\*Status:\*\*[^\n]*)", head)
    qhead = first(r"^(## The questions[^\n]*)$", spec, MULTI)
    if RULING not in status.split("**Text revision:**")[0] or RULING not in qhead:
        bad.append(fail("head-ruling", f"RULED does not name the ruling comment {RULING}"))
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
    ids = re.findall(r"^\| ((?:AC|DL|DoD|N)-\d+) +\|", trace, MULTI)
    bad += [fail("trace-lacks", f"AC trace lacks {i}") for i in AC_IDS if i not in ids]
    bad += [
        fail("trace-repeats", f"AC trace repeats {i}") for i in sorted(set(ids)) if ids.count(i) > 1
    ]
    bqs = block(spec, "## The questions", "\n## ")
    bq = {m.group(1): m.group(0) for m in re.finditer(r"^\| (BQ-\d+) +\|.*$", bqs, MULTI)}
    for i in range(1, 17):
        row = bq.get(f"BQ-{i}")
        if row is None:
            bad.append(fail("bq-missing", f"BQ-{i} missing from the questions table"))
        elif "RULED" not in cells(row)[-1]:
            bad.append(fail("bq-ruled", f"BQ-{i} not RULED"))
    for qid, terms in BQ_TERMS.items():
        if qid in bq and any(t not in bq[qid] for t in terms):
            bad.append(fail("bq-terms", f"{qid} row lost its ruled outcome ({' / '.join(terms)})"))
    return bad, {"bq_rows": len(bq), "ac_rows": len(ids)}


NEEDLES: dict[
    tuple[int, ...], tuple[list[str], list[str], set[tuple[str, int]], dict[str, int]]
] = {}


def needle_gates(
    t: dict[str, str],
) -> tuple[list[str], list[str], set[tuple[str, int]], dict[str, int]]:
    """The CITED_TABLE needles against the plan texts, computed once per set of texts (the texts'
    own hashes key the cache, so an edited copy of them is checked afresh)."""
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
    """Each CITED_TABLE needle once in its file, at its line (`14`: or as many lines lower as there
    are pointer lines above it); every `KEY:line` cite in the spec has a CITED_TABLE row, and a
    range's end lies after its start and inside its file."""
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


def text_gates(spec: str, t: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """Reasons, upstream copy, the `14` pointer lines, placeholders, the repository-wide rules."""
    bad: list[str] = []
    for key, string, doc in rows(REASONS_TABLE):
        if f'"{string}"' not in t[doc]:
            bad.append(fail("reason-drift", f"reason string drifted from {doc}: {key} {string!r}"))
        if (
            len(string) > facts["reason_max"]
            or not string.endswith(".")
            or (key.startswith("rbac.") and re.search(r"\d", string))
        ):
            bad.append(fail("reason-form", f"reason {key}: too long, no full stop or a number"))
    if facts["permission_sentence"] != REASONS["rbac.permission"]:
        bad.append(
            fail("permission", f"E09-D09's template and verb give {facts['permission_sentence']!r}")
        )
    rows_by_name = {name: line for name, _, line in frame_rows(spec)}
    for string, doc, frames in rows(UPSTREAM_TABLE):
        if string not in t[doc]:
            bad.append(fail("upstream-gone", f"upstream string gone from {doc}: {string!r}"))
        for frame in [f.strip() for f in frames.split(",")]:
            if frame in rows_by_name and string not in rows_by_name[frame]:
                bad.append(fail("upstream-frame", f"frame {frame} lacks the upstream {string!r}"))
    plan14 = t["14"].split("\n")
    at = [i for i, ln in enumerate(plan14) if POINTER in ln]
    want = [i + 1 for i, ln in enumerate(plan14) if any(ln.endswith(a) for a in POINTER_AFTER)]
    if at != want:
        bad.append(fail("pointer-14", f"`14` pointer lines at {[i + 1 for i in at]}, not {want}"))
    for n, text in re.findall(PLACEHOLDER_RE, spec):
        bad.append(fail("placeholder", f"placeholder §{n} still in the spec: {text[:70]}"))
    constitution = read_once(ROOT / "CONSTITUTION.md")
    pointer_lines = "\n".join(plan14[i] for i in at)
    for label, txt in (("spec", spec), ("tool", read_once(TOOL)), ("14", pointer_lines)):
        bad += [
            fail("forbidden", f"{label}: forbidden text {p}")
            for p in FORBIDDEN
            if re.search(p, txt)
        ]
        if label != "tool" and re.search(CLOSING, txt, re.IGNORECASE):
            bad.append(fail("closing", f"{label}: a closing keyword (text-first: Refs + Partial)"))
        if label == "tool":
            continue
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if not re.search(rf"^\*\*{re.escape(r)}\b", constitution, MULTI):
                bad.append(fail("rule-id", f"{label}: dangling rule id {r}"))
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(fail("catalogue-id", f"{label}: no catalogue heading for {c}"))
    return bad


def reconcile_gates() -> list[str]:
    """The inventory against E15-D02 §6 / §5.10 and `14`: each upstream line is a pinned cite (its
    needle checked by `cite_gates`) and every frame it maps to is in KIND."""
    bad: list[str] = []
    pinned = {(doc, int(line)) for doc, line, _ in rows(CITED_TABLE, 2)}
    for doc, line, frames in rows(RECONCILE_TABLE, 2):
        if (doc, int(line)) not in pinned:
            bad.append(fail("reconcile", f"reconciliation row `{doc}:{line}` has no needle"))
        for frame in [f.strip() for f in frames.split(",")]:
            if frame not in KIND:
                bad.append(fail("reconcile", f"reconciliation row `{doc}:{line}` names {frame}"))
    return bad


def checklist_items(t: dict[str, str]) -> list[str]:
    """The SCR-025 and SCR-029 sign-off items, verbatim from `14`."""
    out: list[str] = []
    for line in t["14"].split("\n"):
        if any(line.endswith(a) for a in POINTER_AFTER):
            out += [i.strip() for i in line.split("[ ]")[1:]]
    return out


def table_rows(text: str) -> list[str]:
    return re.findall(r"^\|.*$", text, MULTI)


def section_gates(spec: str, ctx: Ctx) -> list[str]:
    """The numbered sections in order (MJ7), then §5, §5.1, §6, §7, §8, §11 and §12: the one T2
    paragraph and its not-T2 list, T2 stated once, the exits row and sentence, the planned insets'
    absence restated, the measured tables, the deck, the G-rows, the sign-off items; and no
    environment control anywhere SCR-025 is described (all of §0 and §2, §8's rows)."""
    bad: list[str] = []
    heads = re.findall(r"^## (\d+)\. ", spec, MULTI)
    if heads != SECTIONS:
        return [
            fail("sections", f"the numbered sections are {heads}, not ## 0. to ## 15. in order")
        ]
    s5, s6, s7, s8 = (section(spec, n, n + 1) for n in (5, 6, 7, 8))
    if "**T2" not in s5 or "**Not T2" not in s5:
        bad.append(fail("t2-paragraph", "§5 lacks the one T2 paragraph or its not-T2 list"))
    for needle in T2_ONCE:
        if spec.count(needle) != 1 or needle not in s5:
            bad.append(fail("t2-once", f"T2 is stated more than once, or not in §5: {needle!r}"))
    exits = [r for r in table_rows(s5) if r.startswith(f"| {EXITS_ROW}")]
    if len(exits) != 1 or any(x != "T1" for x in cells(exits[0])[2:7]):
        bad.append(fail("exits-matrix", "§5.1's exits row is not T1 for every session"))
    if A3_SENTENCE not in s6:
        bad.append(fail("exits-a3", "§6 lost the sentence that no session or state gates an exit"))
    if A3_STANDING not in spec[: spec.find("\n## 0. ")]:
        bad.append(fail("exits-a3", "the standing additions lost A3: the exits are never gated"))
    for n, claim in PLANNED_CLAIMS:
        if claim not in section(spec, n, n + 1):
            bad.append(fail("planned-claims", f"§{n} lost the planned insets' {claim!r}"))
    planned = [cells(r) for r in table_rows(section(spec, 2, 3)) if r.startswith("| planned-")]
    if [tuple(c) for c in planned] != [PLANNED_ROW]:
        bad.append(fail("planned-row", "§2.3's planned row is not the fixed row (BQ-2 RULED)"))
    for rid, claim in PLANNED_ROW_CLAIMS:
        found = re.findall(rf"^\| {re.escape(rid)} +\|.*$", spec, MULTI)
        if len(found) != 1 or claim not in found[0]:
            bad.append(fail("planned-claims", f"the {rid} row lost the planned insets' {claim!r}"))
    bad += measured_gates(s7, ctx)
    bad += deck_fixture_gates(s8, ctx.facts) + restated_gates(spec, ctx.facts)
    strings = re.findall(r'^\| `[^`]+` +\|[^|\n]*\| ("[^|\n]*")', s8, MULTI)
    for pat in BANNED_COPY:
        bad += [
            fail("jargon", f"§8 jargon in copy: {pat!r} in {x[:40]!r}")
            for x in strings
            if re.search(pat, x)
        ]
    for key, forms in DIFF_TEMPLATES.items():
        if any(form not in s8 for form in forms):
            bad.append(fail("template", f"§8 lacks the template e15.diff.{key} in both forms"))
    for lines in (LAYOUT_LINES, SETTINGS_LINES):
        for verb, text in lines.items():
            if text.format(hhmm="{hh:mm}", layout="{layout}") not in s8:
                bad.append(fail("deck-line", f"§8 lacks the consequence line of {verb}"))
    s11 = section(spec, 11, 12)
    for gap in sorted({p["gap"] for kind, p in KIND.values() if kind == "planned"}):
        if not re.search(rf"^\| {gap} +\|", s11, MULTI):
            bad.append(fail("g-row", f"§11 lacks the G-row {gap} that its planned inset names"))
    s12 = section(spec, 12, 13)
    bad += [
        fail("sign-off", f"§12 lacks the item {i!r}")
        for i in checklist_items(ctx.t)
        if i not in s12
    ]
    return bad + planned_prose_gates(spec) + route_open_gates(spec)


def where(spec: str, pos: int) -> str:
    """The frame, the entry point or the section a position of the spec sits in."""
    line = spec[spec.rfind("\n", 0, pos) + 1 : spec.find("\n", pos)]
    m = re.match(FRAME_RE, line) or re.match(r"^\| (E\d+) +\|", line)
    if m:
        return m.group(1)
    heads = [h for h in re.finditer(r"^## (\d+)\. ", spec, MULTI) if h.start() < pos]
    return f"§{heads[-1].group(1)}" if heads else "the header"


def env_gates(spec: str) -> list[str]:
    """M16 and MJ-1: no environment word anywhere in the file outside its pinned phrases, each
    phrase at most as often as pinned; one FAIL per line."""
    bad: list[str] = []
    covered = bytearray(len(spec))
    for phrase, want in ENV_ALLOWED:
        found = [m.start() for m in re.finditer(re.escape(phrase), spec)]
        if len(found) > want:
            bad.append(
                fail("env", f"environment phrase {phrase[:40]!r} {len(found)} times, {want} pinned")
            )
        for at in found:
            covered[at : at + len(phrase)] = b"\1" * len(phrase)
    lines: set[int] = set()
    for m in re.finditer(ENV_RE, spec):
        line = spec.count("\n", 0, m.start())
        if all(covered[m.start() : m.end()]) or line in lines:
            continue
        lines.add(line)
        bad.append(
            fail(
                "env",
                f"environment word outside the allow-list in {where(spec, m.start())}: "
                f"{m.group(0)!r}",
            )
        )
    return bad


def planned_prose_gates(spec: str) -> list[str]:
    """m3: §2's planned-inset paragraphs and table never draw an inset as a control, T2 or dim."""
    bad: list[str] = []
    s2 = section(spec, 2, 3)
    texts: list[tuple[str, str, str]] = []
    for start in PLANNED_PARAS:
        para = [ln for ln in s2.split("\n") if ln.startswith(start)]
        if len(para) != 1:
            bad.append(fail("planned-prose", f"§2 lost its planned paragraph {start[:40]!r}"))
            continue
        texts.append((f"§2 paragraph {start[:24]!r}", para[0], para[0]))
    at = s2.find("\n" + PLANNED_TABLE_HEAD)
    table = s2[at + 1 : s2.find("\n\n", at + 1)].split("\n")[2:] if at >= 0 else []
    if len(table) != 4:
        bad.append(fail("planned-prose", f"§2's planned-inset table has {len(table)} rows, not 4"))
    for row in table:
        c = cells(row)
        texts.append((f"§2 planned row {c[0][:24]!r}", " | ".join(c[:3]), row))
    for label, control_text, dim_text in texts:
        free = [
            re.sub(NEG_WORD_RE, "", re.sub(r'"[^"]*"', '""', x)) for x in (control_text, dim_text)
        ]
        if re.search(CONTROL_RE, free[0]) or re.search(DIM_RE, free[1]):
            bad.append(fail("planned-prose", f"a planned inset drawn as a control or dim: {label}"))
    return bad


def route_open_gates(spec: str) -> list[str]:
    """m3: no sentence of §3's or §4's prose opens the dialog on a no-dialog route (D-9)."""
    bad: list[str] = []
    for n in (3, 4):
        for ln in section(spec, n, n + 1).split("\n"):
            if ln.startswith(("|", "```", "#", "│", "┌", "└")):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r'"[^"]*"', '""', ln)):
                if re.search(ROUTE_OPEN_RE, sentence) and not re.search(ROUTE_NEG_RE, sentence):
                    bad.append(
                        fail(
                            "route-opens",
                            f"§{n} opens the dialog on a no-dialog route: {sentence[:60]!r}",
                        )
                    )
    return bad


def known_gates(spec: str) -> list[str]:
    """m3: every full sha is one the tool knows, every `KEY:line` cite uses a known key (a
    sibling still PENDING is named, never pinned or cited)."""
    bad: list[str] = []
    known = {BASE, *MERGE_SHAS, *SIBLING_SHAS}
    for sha in sorted(set(re.findall(r"\b[0-9a-f]{40}\b", spec)) - known):
        bad.append(fail("sha-unknown", f"a full sha the tool does not know: {sha[:9]}"))
    for key in sorted(
        set(re.findall(r"`([A-Z][A-Za-z0-9]*|\d\d):\d+(?:[" + EN_DASH + r"-]\d+)?`", spec))
    ):
        if key not in DOC_PATHS:
            bad.append(fail("cite-unknown", f"a cite under a key the tool does not know: {key}"))
    return bad


def deck_values(facts: dict[str, Any]) -> dict[str, list[str]]:
    """The values §8's fixture column is rendered from: FIXTURE and the contract facts."""
    fx, (label, (mine, saved)) = FIXTURE, next(iter(facts["conflict_table"].items()))
    links = [link.format(max=facts["name_max"]) for _, link in INVALID_RULES.values()]
    return {
        "workspace": [fx["workspace"]],
        "other_workspace": [fx["other_workspace"]],
        "layout": [fx["layout"]],
        "preset": [fx["preset"]],
        "user": [fx["target"]],
        "max": [str(facts["name_max"])],
        "name": [f"{fx['layout']} (mine)"],
        "name_max+1": [str(facts["name_max"] + 1)],
        "one_invalid": ["1"],
        "invalid_links": [x.removeprefix("Name: ") for x in links],
        "layouts": [str(fx["layouts"])],
        "saved_time": [facts["saved_time"]],
        "conflict_time": [facts["conflict_time"]],
        "conflict_hhmm": [facts["conflict_time"][:5]],
        "row_label": [label],
        "row_mine": [mine],
        "row_saved": [saved],
    }


def deck_fixture_gates(s8: str, facts: dict[str, Any]) -> list[str]:
    """§8's fixture column, rendered (MINOR-3 (c)): every fixture string is one of its row's
    templates with the tool's values, or (a diff key) one of the tool's summary lines in that
    key's form (DIFF_TEMPLATES; the row's own templates are the `template` gate's)."""
    values, bad = deck_values(facts), []
    lines = render_summary(FIXTURE["ac3"]) + render_summary(FIXTURE["overflow"])
    for row in re.findall(r"^\| `[a-z0-9_.]+` +\|.*$", s8, MULTI):
        c = cells(row)
        if len(c) < 4 or not re.search(DECK_FIXTURE_RE, c[2]):
            continue
        key, (head, tail) = c[0].strip("`"), re.split(DECK_FIXTURE_RE, c[2], maxsplit=1)
        names = {"workspace": "workspace", "layout": "layout", "preset": "preset", "user": "user"}
        names |= {"max": "max", "name": "name"} | DECK_VARS.get(key, {})
        renders: set[str] = set()
        for form in DIFF_TEMPLATES.get(key.removeprefix("e15.diff."), ()):
            pattern = re.escape(form).replace(r"\{n\}", r"\d+").replace(r"\{items\}", ".+")
            renders |= {x for x in lines if re.fullmatch(pattern, x)}
        for template in re.findall(r'"([^"]*)"', head):
            if key.startswith("e15.diff."):
                continue
            slots = re.findall(r"\{([a-z:_]+)\}", template)
            if any(x not in names for x in slots):
                continue
            for combo in itertools.product(*(values[names[x]] for x in slots)):
                out = template
                for slot, value in zip(slots, combo, strict=True):
                    out = out.replace("{" + slot + "}", value)
                renders.add(out)
        for fixture in re.findall(r'"([^"]*)"', tail):
            if fixture not in renders:
                bad.append(
                    fail(
                        "deck-fixture",
                        f"§8 {key}: fixture {fixture!r} is not its rendered template",
                    )
                )
    return bad


def restated_gates(spec: str, facts: dict[str, Any]) -> list[str]:
    """The fixture strings §2, §3, §4 and §6 restate outside the frame rows, rendered (MINOR-3
    (c))."""
    bad: list[str] = []
    times = {
        "max": str(facts["name_max"]),
        "layout": FIXTURE["layout"],
        "saved": facts["saved_time"],
        "conflict": facts["conflict_time"][:5],
        "conflict_full": facts["conflict_time"],
    }
    for n, template, want in RESTATED:
        prose = [ln for ln in section(spec, n, n + 1).split("\n") if not re.match(FRAME_RE, ln)]
        text = template.format(**times)
        have = "\n".join(prose).count(text)
        if have != want:
            bad.append(fail("restated", f"§{n} prints {text!r} {have} times, {want} expected"))
    return bad


def measured_gates(s7: str, ctx: Ctx) -> list[str]:
    """§7: every pair, greyscale and colour-vision value as the tool prints it (no tolerance)."""
    bad: list[str] = []
    found = {(m[2], m[3], m[4]): m for m in re.finditer(CONTRAST_ROW_RE, s7, MULTI)}
    for r in ctx.measured["matrix"]:
        m = found.get((r["fg"], r["bg"], r["role"]))
        if m is None:
            bad.append(fail("contrast-row", f"§7 table lacks {r['fg']} on {r['bg']} ({r['role']})"))
            continue
        if [m[5], m[6], m[7]] != [show(r[th]) for th in THEMES]:
            bad.append(
                fail("contrast-cell", f"§7 cell differs: {r['fg']} on {r['bg']} ({r['role']})")
            )
        if m[8].strip() != r["verdict"] or m[9] != r["pairs"]:
            bad.append(
                fail("contrast-verdict", f"§7 verdict or pairs.mjs differs: {r['fg']} on {r['bg']}")
            )
    greys = {g[1]: g for g in re.finditer(GREY_ROW_RE, s7, MULTI)}
    for tok, vals in ctx.measured["grey"].items():
        g = greys.get(tok)
        if g is None or [int(g[2]), int(g[3]), int(g[4])] != [vals[th] for th in THEMES]:
            bad.append(fail("grey", f"§7 greyscale row differs or is missing: {tok}"))
    cvds = {(c[1], c[2]): c for c in re.finditer(CVD_ROW_RE, s7, MULTI)}
    for r in ctx.measured["cvd"]:
        c = cvds.get((r["a"], r["b"]))
        if c is None or [float(c[i]) for i in range(3, 7)] != r["dE76"] or c[7] != r["verdict"]:
            bad.append(
                fail("cvd", f"§7 colour-vision row differs or is missing: {r['a']} vs {r['b']}")
            )
    return bad


def deck_ids(spec: str) -> set[str] | None:
    """§8's keyed ids, or None while §8 is missing."""
    s8 = section(spec, 8, 9)
    return set(re.findall(r"^\| `([^`]+)` +\|", s8, MULTI)) if s8 else None


def count_frames(spec: str) -> dict[str, Any]:
    found = frame_rows(spec)
    kinds = [KIND[n][0] for n, _, _ in found if n in KIND]
    drawn = [c for _, c, _ in found if len(c) == 6 and c[5] != NOT_DRAWN]
    return {
        "frames_total": len(found),
        "frames_025": sum(n.startswith("SCR-025/") for n, _, _ in found),
        "frames_029": sum(n.startswith("SCR-029/") for n, _, _ in found),
        "frames_drawn": len(drawn),
        "frames_not_drawn": len(found) - len(drawn),
        "planned_insets": kinds.count("planned"),
        "t2_frames": sum(k in T2_KINDS for k in kinds),
        "validity_frames": sum(k in VALIDITY_KINDS for k in kinds),
        "dialog_frames": sum(k in DIALOG_KINDS for k in kinds),
        "dirty_frames": sum(k in DIRTY_KINDS for k in kinds),
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
    numbers: dict[str, Any] = dict(extra)
    numbers.update(count_frames(spec))
    numbers["mutations"] = len(mutations()) + len(context_mutations())
    numbers["contract"] = {
        "name_min": f["name_min"],
        "name_max": f["name_max"],
        "layouts_max": f["layouts_max"],
        "workspaces_max": f["workspaces_max"],
        "dialog_sm_px": f["dialog_px"][0] if f["dialog_px"] else None,
        "dialog_md_px": f["dialog_px"][1] if f["dialog_px"] else None,
        "dialog_lg_px": f["dialog_px"][2] if f["dialog_px"] else None,
        "confirm_delay_ms": f["confirm_delay_ms"],
        "conflict_ms": f["conflict_ms"],
        "reason_max": f["reason_max"],
        "control_compact": f["control_compact"],
        "control_comfortable": f["control_comfortable"],
        "opacity_disabled": f["opacity_disabled"],
    }
    ac3, over = FIXTURE["ac3"], FIXTURE["overflow"]
    numbers["fixture"] = {
        "layouts": FIXTURE["layouts"],
        "saved_time": f["saved_time"],
        "conflict_time": f["conflict_time"],
        "refreshed_time": FIXTURE["refreshed_time"],
        "list_cap": FIXTURE["list_cap"],
        "ac3": {
            "panels_added": ac3["panels_added"],
            "symbols_changed": len(ac3["pairs"]),
            "groups_added": len(ac3["groups_added"]),
            "lines": len(render_summary(ac3)),
        },
        "overflow": {
            "panels_added": over["panels_added"],
            "symbols_changed": len(over["pairs"]),
            "hidden": max(0, len(over["pairs"]) - int(FIXTURE["list_cap"])),
            "lines": len(render_summary(over)),
        },
    }
    for k in ("pairs_rows", "pairs_fail", "pairs_registered", "pairs_proposed", "aaa_rows"):
        numbers[k] = m[k]
    numbers["aaa_met"] = m["aaa_met"]
    numbers["composite"] = m["composite"]
    # The redlines §2.2 quotes in px (or as an opacity): every bound spacing, radius, border and
    # opacity token, resolved in dark (density re-points the control height only, `16:125`).
    numbers["redline"] = {
        tok: resolve(ctx.themes["dark"], tok)
        for tok in BINDINGS
        if tok.split(".")[0] in ("space", "radius", "border", "opacity")
    }
    numbers["missing_tokens"] = len(ctx.missing)
    numbers["reconciled"] = len(rows(RECONCILE_TABLE))
    numbers["checklist_items"] = len(checklist_items(ctx.t))
    numbers["deck_rows"] = len(deck_ids(spec) or ())
    numbers["rows"] = {
        kind: len(set(re.findall(rf"^\| (D08-{kind}\d+) +\|", spec, MULTI))) for kind in "ACDGQ"
    }
    return numbers


def marker_gates(spec: str, numbers: dict[str, Any]) -> list[str]:
    """M15 (MJ2): a marker's value is the tool's, the number printed beside it is the marker's,
    every marker parses, and no marker the spec carries disappears (MARKER_TABLE's counts)."""
    flat = flatten(numbers)
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
        before = spec[spec.rfind("\n", 0, m.start()) + 1 : m.start()]
        token = before.rstrip().split(" ")[-1] if before.strip() else ""
        number = re.fullmatch(NUMBER_BEFORE_RE, token)
        if number and number.group(1) != val:
            bad.append(
                fail("marker-visible", f"printed {number.group(1)} beside audit:{key}={val}")
            )
        elif not number:
            end = spec.find("\n", m.end())
            line = re.sub(MARKER_RE, "", spec[spec.rfind("\n", 0, m.start()) + 1 : end])
            want = DETACHED.get((first(r"^\| (D08-[A-Z]\d+) ", line), key))
            have_n = len(re.findall(rf"(?<![\d.:]){re.escape(val)}(?![\d.:])", line))
            if have_n != want:
                bad.append(
                    fail(
                        "marker-visible",
                        f"audit:{key}={val} detached: its line prints {val} {have_n} times, "
                        f"{want} expected",
                    )
                )
    for key, want in MARKERS.items():
        have_n = len(re.findall(rf"audit:{re.escape(key)}=", spec))
        if have_n < want:
            bad.append(fail("marker-count", f"audit:{key} appears {have_n} times, {want} expected"))
    return bad


def gates(spec: str, ctx: Ctx) -> tuple[list[str], dict[str, Any]]:
    """Every gate over one copy of the spec; returns the FAILs and the numbers it derived."""
    bad: list[str] = []
    b0, n0 = board_gates(spec)
    b3, n3 = entry_gates(spec)
    bh, nh = head_gates(spec)
    bc, nc = cite_gates(spec, ctx.t)
    bad += bh + b0 + frame_gates(spec, ctx.facts, deck_ids(spec)) + b3 + bc
    bad += text_gates(spec, ctx.t, ctx.facts) + reconcile_gates() + section_gates(spec, ctx)
    bad += env_gates(spec) + known_gates(spec)
    bad += [fail("token-missing", f"token MISSING: {tok}") for tok in ctx.missing]
    bad += [
        fail("contrast-fail", f"contrast FAIL: {r['element']}")
        for r in ctx.measured["matrix"]
        if r["verdict"] in ("FAIL", "MISSING")
    ]
    f = ctx.facts
    for fact in ("version_conflict_412", "unstored_absent"):
        if not f[fact]:
            bad.append(fail("contract-fact", f"contract fact changed: {fact}"))
    if len(f["refusal_codes"]) != 3:
        bad.append(fail("contract-fact", f"`22` workspace refusals now {f['refusal_codes']}"))
    if f["last_workspace_message"] != REASONS["workspace.limit.last"]:
        bad.append(fail("contract-fact", "`22` deleteWorkspace's last_workspace sentence changed"))
    if f["ws_layout_topic"]:
        bad.append(fail("ws-topic", "`23` now carries a workspace or layout topic: see D08-G6"))
    numbers = numbers_of(spec, ctx, {**n0, **n3, **nh, **nc})
    bad += marker_gates(spec, numbers)
    return bad, numbers


def row_fn(pattern: str, fn: Callable[[str], str]) -> Callable[[str], str]:
    """Apply `fn` to the one spec line the anchored `pattern` finds (unchanged when none)."""

    def apply(s: str) -> str:
        m = re.search(pattern, s, MULTI)
        return s if not m else s[: m.start()] + fn(m.group(0)) + s[m.end() :]

    return apply


def frame_sub(frame: str, old: str, new: str) -> Callable[[str], str]:
    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", lambda ln: ln.replace(old, new, 1))


def frame_re(frame: str, pattern: str, repl: str) -> Callable[[str], str]:
    return row_fn(rf"^\| `{re.escape(frame)}` +\|.*$", lambda ln: re.sub(pattern, repl, ln))


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


def mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """(name, the in-memory change, the text the one new FAIL must carry): M1-M17 of the brief's A2,
    then at least one per gate code (m12), led by the lenses' pins (MJ1-MJ9, MINOR-4/5, NIT-8)."""
    conflict_footer = (
        "footer: Cancel (`secondary`) · Save mine as new layout… (`secondary`) · "
        "Load theirs (`secondary`) · Keep mine (`secondary`)"
    )
    moved_footer = (
        "footer: Save mine as new layout… (`secondary`) · Load theirs (`secondary`) · "
        "Keep mine (`secondary`) · Cancel (`secondary`)"
    )
    keep_line = (
        ' "Keep mine replaces the version saved at 14:05. That version can\'t be recovered."'
    )
    m: list[tuple[str, Callable[[str], str], str]] = [
        (
            "M1-dirty-star",
            frame_re("SCR-029/unsaved", r"`([^`\n]*?) ?\*([^`\n]*)`", r"`\1\2`"),
            "[dirty-star] dirty frame SCR-029/unsaved",
        ),
        ("M2-t2-lock", frame_re("SCR-025/delete-last", r"\block\b", "glyph"), "[t2-lock]"),
        (
            "M3-reason-key",
            frame_sub("SCR-025/viewer-read-only", "`notice.panel_read_only`", "the notice key"),
            "[t2-key] T2 frame SCR-025/viewer-read-only lacks its reason key notice",
        ),
        (
            "M4-view-as-order",
            frame_sub(
                "SCR-025/delete-last",
                "legs `rbac.view_as` → `rbac.permission`",
                "legs `rbac.permission` → `rbac.view_as`",
            ),
            "[legs-order] view-as leg not first",
        ),
        (
            "M5-planned-control",
            frame_sub(
                "SCR-025/planned-defaults", 'Default account"', 'Default account" in a select'
            ),
            "[planned-control] planned inset SCR-025/planned-defaults",
        ),
        (
            "M6-planned-dim",
            frame_sub(
                "SCR-025/planned-theme",
                'the words "Theme override"',
                'the words "Theme override" at `opacity.disabled`',
            ),
            "[planned-dim] planned inset SCR-025/planned-theme",
        ),
        (
            "M7-cancel-first",
            frame_sub("SCR-029/conflict", conflict_footer, moved_footer),
            "[safe-first] safe action not first in the footer of SCR-029/conflict",
        ),
        (
            "M8-focus-safe",
            frame_sub("SCR-029/unsaved", "initial focus: Cancel", "initial focus: Save layout"),
            "[focus-safe]",
        ),
        (
            "M9-esc-cancel",
            frame_sub("SCR-029/unsaved", "Esc → Cancel", "Esc → Discard changes"),
            "[esc] Esc not mapped to Cancel in SCR-029/unsaved",
        ),
        (
            "M10-exit-gated",
            frame_sub("SCR-029/viewer-unsaved", "T2: Save layout (", "T2: Save layout, Cancel ("),
            "[exit-gated] exit drawn gated in SCR-029/viewer-unsaved",
        ),
        (
            "M11-typed-field",
            frame_sub(
                "SCR-025/delete-confirm",
                'the typed field labelled "Type Scalping to confirm" (',
                "the typed field (",
            ),
            "[typed-field]",
        ),
        ("M12-consequence", frame_sub("SCR-029/conflict", keep_line, ""), "[consequence]"),
        (
            "M13-overwrite-time",
            frame_sub("SCR-029/keep-mine-confirm", " That version can't be recovered.", ""),
            "[overwrite] overwrite confirm SCR-029/keep-mine-confirm lacks its time or",
        ),
        (
            "M14-412",
            frame_sub("SCR-029/conflict", "answered `412 version_conflict`", "answered a refusal"),
            "[conflict-412] conflict frame SCR-029/conflict",
        ),
        (
            "M15-number",
            set_marker("boards", "10", "11"),
            "[marker-value] marker audit:boards=11 vs tool 10",
        ),
        (
            "M16-env-control",
            frame_sub(
                "SCR-025/default",
                "Share (Export…)",
                "Share (Export…, a Default environment for new panels select)",
            ),
            "[env] environment word outside the allow-list in SCR-025/default",
        ),
        (
            "M17-cmp-044",
            frame_sub(
                "SCR-029/conflict", 'CMP-043 `role="alertdialog"`', 'CMP-044 `role="alertdialog"`'
            ),
            "[cmp-043] SCR-029 dialog SCR-029/conflict",
        ),
    ]
    return m + frame_mutations() + more_mutations() + section_mutations() + round1_mutations()


def frame_mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """The per-frame gates beyond M1-M17: one mutation each, the lenses' pins first."""
    v1 = "Cancel (`secondary`, the lock leading its label) · Save mine"
    return [
        (
            "X1-primary-discard",
            frame_sub(
                "SCR-029/unsaved", "Discard changes (`secondary`)", "Discard changes (`primary`)"
            ),
            "[x1-weight] destructive choice carries primary weight in SCR-029/unsaved",
        ),
        (
            "X30-settings-primary",
            frame_sub(
                "SCR-025/settings-conflict", "Keep mine (`secondary`)", "Keep mine (`primary`)"
            ),
            "[x1-weight] destructive choice carries primary weight in SCR-025/settings-conflict",
        ),
        (
            "X31-discard-prompt-danger",
            frame_sub(
                "SCR-025/discard-prompt",
                "Discard changes (`secondary`)",
                "Discard changes (`danger`)",
            ),
            "[x1-weight] destructive choice carries primary weight in SCR-025/discard-prompt",
        ),
        (
            "X2-unverbed",
            frame_sub("SCR-029/unsaved", "Save layout (`primary`)", "OK (`primary`)"),
            "[unverbed] unverbed button in SCR-029/unsaved",
        ),
        (
            "X33-typed-confirm-verb",
            frame_sub(
                "SCR-025/delete-confirm", "Delete workspace (`danger`)", "Confirm (`danger`)"
            ),
            "[unverbed] unverbed button in SCR-025/delete-confirm",
        ),
        (
            "X34-footer-verb-gone",
            frame_sub("SCR-029/unsaved", " · Save layout (`primary`)", ""),
            "[footer-set] footer of SCR-029/unsaved",
        ),
        (
            "X35-form-cancel-first",
            frame_sub(
                "SCR-025/viewer-read-only",
                "footer: Cancel (`secondary`) · Save (T2)",
                "footer: Save (T2) · Cancel (`secondary`)",
            ),
            "[safe-first] safe action not first in the footer of SCR-025/viewer-read-only",
        ),
        (
            "X36-footer-order",
            frame_sub(
                "SCR-029/conflict",
                "Save mine as new layout… (`secondary`) · Load theirs (`secondary`)",
                "Load theirs (`secondary`) · Save mine as new layout… (`secondary`)",
            ),
            "[footer-order] footer of SCR-029/conflict",
        ),
        (
            "X37-cancel-primary",
            frame_sub("SCR-029/revert", "Cancel (`secondary`)", "Cancel (`primary`)"),
            "[safe-weight] safe action Cancel not `secondary` in SCR-029/revert",
        ),
        (
            "X38-primary-not-last",
            frame_sub(
                "SCR-029/conflict",
                "Save mine as new layout… (`secondary`)",
                "Save mine as new layout… (`primary`)",
            ),
            "[primary-last]",
        ),
        (
            "X39-esc-later",
            frame_sub(
                "SCR-025/dirty",
                "exits T1: Cancel · Esc · Close",
                "Esc → Discard changes; exits T1: Cancel · Esc · Close",
            ),
            "[esc] Esc not mapped to Cancel in SCR-025/dirty",
        ),
        (
            "X40-exits-t1",
            frame_sub("SCR-025/dirty", "exits T1: Cancel · Esc · Close", "exits T1: Close"),
            "[exits-t1] frame SCR-025/dirty",
        ),
        (
            "X41-exit-lock",
            frame_sub("SCR-029/conflict", "Cancel (`secondary`) · Save mine", v1),
            "[exit-gated] exit drawn gated in SCR-029/conflict",
        ),
        (
            "X42-exit-second-t2",
            frame_sub(
                "SCR-029/viewer-unsaved",
                "; initial focus: Cancel",
                "; T2: Cancel (the lock leading its full label, §5); initial focus: Cancel",
            ),
            "[exit-gated] exit drawn gated in SCR-029/viewer-unsaved",
        ),
        (
            "X43-exit-close-t2",
            frame_sub(
                "SCR-025/dirty",
                "exits T1: Cancel · Esc · Close",
                "exits T1: Cancel · Esc · Close (T2)",
            ),
            "[exit-gated] exit drawn gated in SCR-025/dirty",
        ),
        (
            "X44-exit-esc-t2",
            frame_sub("SCR-029/revert", "Esc → Cancel (focus", "Esc → Cancel (T2; focus"),
            "[exit-gated] exit drawn gated in SCR-029/revert",
        ),
        (
            "X45-exit-revert-t2",
            frame_sub("SCR-029/revert", "Revert to saved (`secondary`)", "Revert to saved (T2)"),
            "[exit-gated] exit drawn gated in SCR-029/revert",
        ),
        (
            "X46-exit-kill-switch",
            frame_sub(
                "SCR-029/unsaved",
                "; initial focus: Cancel",
                "; while the kill switch is on, Cancel is unavailable; initial focus: Cancel",
            ),
            "[exit-gated] exit drawn gated in SCR-029/unsaved",
        ),
        (
            "X47-exit-close-x",
            frame_sub(
                "SCR-025/default", f"the close {TIMES} named", f"the close {TIMES} (T2) named"
            ),
            "[exit-gated] exit drawn gated in SCR-025/default",
        ),
        (
            "X19-overwrite-plain",
            frame_sub("SCR-029/keep-mine-confirm", "CMP-044 `standard`", "CMP-044 `typed`"),
            "[component] frame SCR-029/keep-mine-confirm",
        ),
        (
            "X48-discard-cmp",
            frame_sub(
                "SCR-025/discard-prompt",
                'CMP-044 `standard` `role="alertdialog"`',
                'CMP-043 `role="alertdialog"`',
            ),
            "[component] frame SCR-025/discard-prompt",
        ),
        (
            "X49-settings-cmp",
            frame_sub(
                "SCR-025/settings-conflict",
                'CMP-043 `role="alertdialog"`',
                'CMP-044 `standard` `role="alertdialog"`',
            ),
            "[component] frame SCR-025/settings-conflict",
        ),
        (
            "X50-form-alertdialog",
            frame_sub("SCR-025/default", 'CMP-043 `role="dialog"`', 'CMP-043 `role="alertdialog"`'),
            "[component] frame SCR-025/default",
        ),
        (
            "X51-size-lg",
            frame_sub("SCR-029/conflict", '`size="md"`', '`size="lg"`'),
            "[size] frame SCR-029/conflict",
        ),
        (
            "X52-size-missing",
            frame_sub("SCR-025/discard-prompt", ', `size="sm"`', ""),
            "[size] frame SCR-025/discard-prompt",
        ),
        (
            "M1b-star-shows-only",
            frame_sub("SCR-029/conflict", "the tab keeps `Scalping *`", "the tab keeps `Scalping`"),
            "[dirty-star] dirty frame SCR-029/conflict",
        ),
        (
            "X53-leg-lost-star",
            frame_sub(
                "SCR-025/leg-lost", "the title keeps `Workspace settings *`", "the title stays"
            ),
            "[dirty-star] dirty frame SCR-025/leg-lost",
        ),
        (
            "X54-delete-star",
            frame_sub("SCR-025/delete-confirm", "Layout 1 `*`", "Layout 1"),
            "[dirty-star] dirty frame SCR-025/delete-confirm",
        ),
        (
            "X55-clean-star",
            frame_sub(
                "SCR-025/default", 'title "Workspace settings"', "title `Workspace settings *`"
            ),
            "[clean-star] clean frame SCR-025/default",
        ),
        (
            "X56-env-dropdown",
            frame_sub(
                "SCR-025/default", "Share (Export…)", "Share (Export…, an Environment dropdown)"
            ),
            "[env] environment word outside the allow-list in SCR-025/default",
        ),
        (
            "X57-env-pill",
            frame_sub(
                "SCR-025/view-as",
                "Export… stays T1",
                "the CMP-075 pill beside the title; Export… stays T1",
            ),
            "[env] environment word outside the allow-list in SCR-025/view-as",
        ),
        (
            "X58-planned-stamp",
            frame_sub("SCR-025/planned-density", "the `planned` stamp, ", ""),
            "[planned-form] planned inset SCR-025/planned-density",
        ),
        (
            "X59-planned-caption",
            frame_sub(
                "SCR-025/planned-theme", ' the caption "Waits for its contract (D08-G4)."', ""
            ),
            "[planned-caption]",
        ),
        (
            "X60-planned-dropdown",
            frame_sub(
                "SCR-025/planned-description",
                'the words "Description"',
                'the words "Description" in a dropdown',
            ),
            "[planned-control] planned inset SCR-025/planned-description",
        ),
        (
            "X61-planned-disabled",
            frame_sub(
                "SCR-025/planned-density", 'the words "Density"', 'the words "Density", disabled'
            ),
            "[planned-dim] planned inset SCR-025/planned-density",
        ),
        (
            "X62-lock-phrase",
            frame_sub("SCR-025/viewer-read-only", "the lock leading each full label, ", ""),
            "[t2-lock] T2 frame SCR-025/viewer-read-only",
        ),
        (
            "M3b-key-from-legs",
            frame_sub("SCR-025/delete-last", " → `workspace.limit.last`", ""),
            "[t2-key] T2 frame SCR-025/delete-last lacks its reason key workspace.limit.last",
        ),
        (
            "X63-key-cell",
            frame_sub("SCR-025/delete-last", "| `workspace.limit.last` · ", "| "),
            "[t2-key-cell] T2 frame SCR-025/delete-last",
        ),
        (
            "X64-reason-long",
            frame_sub(
                "SCR-029/viewer-unsaved",
                '"Your role can\'t save workspaces."',
                '"Your role does not hold the permission a workspace save needs."',
            ),
            "[t2-say] T2 frame SCR-029/viewer-unsaved",
        ),
        (
            "X65-legs-gone",
            frame_sub("SCR-025/view-as", "legs `rbac.view_as` first, ", ""),
            "[legs] T2 frame SCR-025/view-as",
        ),
        (
            "X7-dim-t2",
            frame_sub(
                "SCR-025/delete-last",
                "in `color.text.tertiary`",
                "in `color.text.tertiary` at `opacity.disabled`",
            ),
            "[t2-dim] T2 frame SCR-025/delete-last",
        ),
        (
            "X66-t2-cite",
            frame_re("SCR-029/save-as-t2", "§5", "§6"),
            "[t2-cite] T2 frame SCR-029/save-as-t2",
        ),
        (
            "X67-t2-native",
            frame_sub(
                "SCR-029/viewer-unsaved",
                "`aria-disabled` and never the `disabled` attribute",
                "the `disabled` attribute",
            ),
            "[t2-native] T2 frame SCR-029/viewer-unsaved",
        ),
        (
            "X6-reason-sr",
            frame_sub("SCR-025/delete-last", " through `aria-describedby`", ""),
            "[t2-sr]",
        ),
        (
            "X68-t2-footer",
            frame_sub("SCR-025/viewer-read-only", "Save (T2)", "Save (`primary`)"),
            "[t2-footer] footer of SCR-025/viewer-read-only and its T2 clause disagree on Save",
        ),
        (
            "X147-lock-outside-t2",
            frame_sub(
                "SCR-025/viewer-read-only",
                "(availability, not T2 — no lock, the availability look of §2)",
                "(availability, the lock leading its label)",
            ),
            "[t2-lock-scope] a lock drawn outside the T2 clause of SCR-025/viewer-read-only",
        ),
        (
            "X69-one-notice",
            frame_sub(
                "SCR-025/viewer-read-only",
                "one notice at the top of the body",
                "a notice at the top of the body",
            ),
            "[one-notice] read-only frame SCR-025/viewer-read-only",
        ),
        (
            "X70-validity-reason",
            frame_sub(
                "SCR-025/invalid-empty",
                'the `validity-reason` "Fix 1 field."',
                'the reason "Fix 1 field."',
            ),
            "[validity-reason] validity frame SCR-025/invalid-empty",
        ),
        (
            "X5-validity-lock",
            frame_sub(
                "SCR-025/default",
                "Save in the validity look",
                "Save in the validity look behind a lock",
            ),
            "[validity-lock] validity frame SCR-025/default with a lock",
        ),
        (
            "X17-class-agrees",
            frame_re("SCR-029/save-as-t2", r"\| T2 \(state, §5\)( +)\|", r"| T1 (state)\1|"),
            "[class-t2] Class cell disagrees with the tool's KIND: SCR-029/save-as-t2 is T2",
        ),
        (
            "X71-class-not-t2",
            frame_re("SCR-025/dirty", r"\| T1( +)\|", r"| T2\1|"),
            "[class-not-t2] Class cell disagrees with the KIND: SCR-025/dirty is not T2",
        ),
        (
            "X72-class-word",
            frame_re("SCR-025/saved", r"\| outcome( +)\|", r"| T1\1|"),
            "[class-word] Class cell disagrees with the KIND: SCR-025/saved is outcome",
        ),
        (
            "X73-board-cell",
            frame_re("SCR-025/failed", r"\| 02( +)\|$", r"| 2\1|"),
            "[board-cell] frame SCR-025/failed",
        ),
        (
            "X74-key-namespace",
            frame_sub("SCR-025/saved", "| `e15.settings.saved`", "| `ui.settings.saved`"),
            "[key-namespace] copy key outside the namespaces in SCR-025/saved",
        ),
        (
            "X75-inventory",
            frame_sub("SCR-025/compact", "`SCR-025/compact`", "`SCR-025/compact-x`"),
            "[inventory] frame rows and the tool's inventory differ",
        ),
        (
            "X76-cells",
            frame_re(
                "SCR-025/view-as", r"\| not drawn — the text is binding; drawn on request +\|$", "|"
            ),
            "[cells] frame SCR-025/view-as: 5 cells",
        ),
    ]


def more_mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """The content gates (every quoted number rendered), §0, §3.2, the header, cites and text."""
    key = "**Key.**"
    load = '"Load theirs replaces your unsaved changes. They can\'t be recovered."'
    keep = '"Keep mine replaces the version saved at 14:07. That version can\'t be recovered."'
    return [
        (
            "X3-diff-fixture",
            frame_sub("SCR-029/unsaved", '"3 panels added."', '"Three panels added."'),
            "[summary] difference summary differs from the fixture in SCR-029/unsaved",
        ),
        (
            "X4-overflow",
            frame_sub("SCR-029/unsaved-overflow", ' "and 2 more differences."', ""),
            "[overflow] overflow line missing",
        ),
        (
            "X77-overflow-producer",
            frame_sub(
                "SCR-029/unsaved-overflow",
                "1 panel added and 5 symbols changed",
                "1 panel added and 6 symbols changed",
            ),
            "[overflow-producer]",
        ),
        (
            "X8-invalid-message",
            frame_sub("SCR-025/invalid-long", '"Use at most 40 characters."', '"Too long."'),
            "[invalid] invalid-name frame SCR-025/invalid-long",
        ),
        (
            "X78-invalid-count",
            frame_sub(
                "SCR-025/invalid-long", "Name typed to 41 characters", "Name typed to 42 characters"
            ),
            "[invalid] invalid-name frame SCR-025/invalid-long",
        ),
        (
            "X79-name-help",
            frame_sub("SCR-025/default", '"Up to 40 characters.', '"Up to 41 characters.'),
            "[name-help]",
        ),
        (
            "X80-dirty-fixture",
            frame_sub(
                "SCR-025/dirty", 'Name edited to "Scalping 2"', 'Name edited to "Scalping 3"'
            ),
            "[dirty-fixture]",
        ),
        (
            "X81-refusal",
            frame_sub(
                "SCR-025/failed", "a second `409 concurrent_update`", "a second racing write"
            ),
            "[refusal]",
        ),
        (
            "X82-delete-body",
            frame_sub(
                "SCR-025/delete-confirm", 'body "It has 2 layouts,', 'body "It has 3 layouts,'
            ),
            "[delete-body]",
        ),
        (
            "X83-delete-fixture",
            frame_sub(
                "SCR-025/delete-confirm", "on Scalping (2 layouts,", "on Scalping (3 layouts,"
            ),
            "[delete-fixture]",
        ),
        (
            "X84-confirm-delay",
            frame_sub("SCR-025/discard-prompt", "`confirmDelayMs` 400", "`confirmDelayMs` 300"),
            "[confirm-delay] confirm SCR-025/discard-prompt",
        ),
        (
            "X85-racing",
            frame_sub("SCR-025/delete-racing", "`409 last_workspace`", "a refusal"),
            "[racing]",
        ),
        (
            "X9-announce",
            frame_sub("SCR-025/saved", '"Saved workspace settings."', '"Done."'),
            "[outcome]",
        ),
        (
            "X86-busy",
            frame_sub("SCR-025/saving", "`aria-busy`, ", ""),
            "[busy] busy frame SCR-025/saving",
        ),
        (
            "X21-settings-names",
            frame_sub("SCR-025/settings-conflict", 'saved now "Scalping EU"', "saved now theirs"),
            "[settings-names]",
        ),
        (
            "X87-side-by-side",
            frame_sub("SCR-029/conflict", '"Yours (not saved)"', '"Yours"'),
            "[side-by-side] conflict frame SCR-029/conflict",
        ),
        (
            "X88-line-order",
            frame_sub(
                "SCR-029/conflict-refreshed",
                f"{load} {keep}",
                f"{keep} {load}",
            ),
            "[consequence-order] consequence lines of SCR-029/conflict-refreshed",
        ),
        (
            "X89-keep-route",
            frame_sub(
                "SCR-029/conflict",
                "Keep mine opens `SCR-029/keep-mine-confirm`",
                "Keep mine overwrites the saved version at once",
            ),
            "[keep-route] conflict frame SCR-029/conflict",
        ),
        (
            "X90-loaded-line",
            frame_sub("SCR-029/conflict", 'saved at 14:05." (polite)', 'saved at 14:06." (polite)'),
            "[loaded-line]",
        ),
        (
            "X91-refreshed-time",
            frame_sub("SCR-029/conflict-refreshed", "wrote at 14:07:30", "wrote at 14:07:31"),
            "[refreshed-time]",
        ),
        (
            "X92-by-reference",
            frame_sub("SCR-029/save-as-t2", ", its table and its four lines unchanged", ""),
            "[by-reference] frame SCR-029/save-as-t2",
        ),
        (
            "X93-saving-routes",
            frame_sub(
                "SCR-029/unsaved-saving",
                "a `412` takes the queued route (`SCR-029/conflict-queued`)",
                "a `412` is dropped",
            ),
            "[saving-routes]",
        ),
        (
            "X94-revert-done",
            frame_sub(
                "SCR-029/revert",
                'reverted to the version saved at 13:40."',
                'reverted to the version saved at 13:41."',
            ),
            "[revert-done]",
        ),
        (
            "X95-save-as-cap",
            frame_sub("SCR-029/save-as-t2", "holds 32 layouts", "holds 31 layouts"),
            "[save-as-cap]",
        ),
        (
            "X10-queue-rule",
            frame_sub("SCR-029/conflict-queued", QUEUE_RULE, "the dialog waits"),
            "[queue-rule]",
        ),
        (
            "X148-queue-autosave",
            frame_sub("SCR-029/conflict-queued", "autosave stops for Layout 1", "autosave goes on"),
            "[queue-rule]",
        ),
        (
            "X149-typed-enter",
            frame_sub("SCR-025/delete-confirm", "; `Enter` in the field never confirms", ""),
            "[typed-field]",
        ),
        (
            "X150-danger-words",
            frame_sub(
                "SCR-025/delete-last", "and the `danger` glyph (words", "and a red mark (words"
            ),
            "[danger-words] frame SCR-025/delete-last",
        ),
        (
            "X151-fixture-name",
            frame_sub(
                "SCR-029/unsaved", "Save layout writes Layout 1,", "Save layout writes Layout 2,"
            ),
            "[fixture-name] frame SCR-029/unsaved",
        ),
        (
            "X96-reflow-frame",
            frame_sub("SCR-029/reflow-200", f"1280 {TIMES} 800", f"1280 {TIMES} 720"),
            "[reflow] reflow frame SCR-029/reflow-200",
        ),
        (
            "X16-board-reconcile",
            frame_re("SCR-025/failed", r"\| 02( +)\|$", r"| 03\1|"),
            "[board-reconcile] frame SCR-025/failed: its row says boards",
        ),
        (
            "X20-not-drawn-line",
            sub(", `SCR-029/leg-lost`, `SCR-029/reflow-200`.", ", `SCR-029/reflow-200`."),
            "[not-drawn] frame SCR-029/leg-lost",
        ),
        (
            "X97-not-drawn-unknown",
            sub(", `SCR-029/reflow-200`.", ", `SCR-029/reflow-200`, `SCR-029/ghost`."),
            "[not-drawn-unknown]",
        ),
        (
            "X98-board-name",
            line_sub("| 05 ", "`E15-D08 / 05 ", "`E15-D08 / 06 "),
            "[board-name] §0 board 05",
        ),
        (
            "X99-board-cells",
            row_fn(r"^\| 07 .*$", lambda ln: re.sub(r"\| pending +\|$", "|", ln)),
            "[board-cells] §0 board 07",
        ),
        (
            "X100-board-theme",
            line_sub("| 09 ", "| light |", "| dark  |"),
            "[board-theme] §0 board 09",
        ),
        (
            "X101-board-export",
            line_sub("| 03 ", "E15-D08-03-scr-025-danger-zone.png", "E15-D08-03-danger.png"),
            "[board-export] §0 board 03",
        ),
        (
            "X102-board-status",
            line_sub("| 04 ", "| pending |", "| drawn   |"),
            "[board-status] §0 board 04",
        ),
        (
            "X103-board-unknown",
            line_sub(
                "| 06 ", "`SCR-029/unsaved-overflow`", "`SCR-029/unsaved-overflow`, `SCR-029/ghost`"
            ),
            "[board-unknown] §0 board 06",
        ),
        (
            "X104-board-empty",
            chain(
                line_sub("| 08 ", "| 08 ", "| 11 "),
                line_sub("| 11 ", "/ 08 ", "/ 11 "),
                line_sub("| 11 ", "E15-D08-08-", "E15-D08-11-"),
            ),
            "[board-empty] §0 board 11",
        ),
        (
            "X105-board-cap",
            chain(
                line_sub("| 03 ", "scr-025-danger-zone`", "scr-025-danger-zone-light`"),
                line_sub("| 03 ", "| dark  |", "| light |"),
                line_sub("| 03 ", "scr-025-danger-zone.png", "scr-025-danger-zone-light.png"),
                line_sub("| 04 ", "scr-029-unsaved`", "scr-029-unsaved-light`"),
                line_sub("| 04 ", "| dark  |", "| light |"),
                line_sub("| 04 ", "scr-029-unsaved.png", "scr-029-unsaved-light.png"),
                set_marker("light_twins", "2", "4"),
            ),
            "[board-cap]",
        ),
        (
            "X106-entry-missing",
            row_fn(r"^\| E7 +\|.*$", lambda ln: ln.replace("| E7 ", "| E15", 1)),
            "[entry-missing] entry-point matrix lacks E7",
        ),
        (
            "X107-entry-route",
            row_fn(
                r"^\| E7 +\|.*$",
                lambda ln: ln.replace("closing a workspace tab", "closing a tab", 1),
            ),
            "[entry-route] entry point E7",
        ),
        (
            "X11-entry-unmapped",
            row_fn(
                r"^\| E6 +\|.*$", lambda ln: re.sub(r"\| no dialog — [^|]*\|", "| — |", ln, count=1)
            ),
            "[entry-unmapped] entry point unmapped: E6",
        ),
        (
            "X108-entry-esc-none",
            row_fn(r"^\| E6 +\|.*$", lambda ln: ln.replace("— (no dialog)", "Esc → Cancel", 1)),
            "[entry-esc-none] entry point E6",
        ),
        (
            "X32-entry-esc",
            row_fn(
                r"^\| E4 +\|.*$", lambda ln: ln.replace("Esc → Cancel", "Esc → Discard changes", 1)
            ),
            "[entry-esc] Esc not mapped to Cancel on entry point E4",
        ),
        (
            "X109-head-sha",
            sub("`ed8a22246263ace73f39e4434e6d5f57b1a857bd`", "`ed8a222`"),
            "[head-sha] header: merge sha missing: ed8a22246",
        ),
        (
            "X110-head-base",
            sub("`06eeb317e0d4ab636e3b3e8ab9419a5c64ce1d7e`", "`06eeb317e`"),
            "[head-base]",
        ),
        (
            "X111-head-penpot",
            sub(
                "**Penpot page:** `E15-D08 Workspace settings and conflicts`",
                "**Penpot page:** `E15-D08`",
            ),
            "[head-penpot]",
        ),
        (
            "X112-head-status",
            sub("boards PENDING (§0:", "boards to come (§0:"),
            "[head-status] header: status lost 'boards PENDING'",
        ),
        (
            "X14-deviation",
            row_fn(
                r"^- \*\*Deviation — the five fieldsets\.\*\*.*$",
                lambda ln: ln.replace("five fieldsets", "fieldsets"),
            ),
            "[deviation] deviation missing: the five fieldsets",
        ),
        (
            "X15-ac-trace",
            row_fn(r"^\| AC-5 ", lambda ln: "| AC-50 "),
            "[trace-lacks] AC trace lacks AC-5",
        ),
        (
            "X113-trace-repeats",
            row_fn(r"^\| AC-6 .*$", lambda ln: ln + "\n" + ln),
            "[trace-repeats] AC trace repeats AC-6",
        ),
        (
            "X114-bq-missing",
            row_fn(r"^\| BQ-16 +\|.*$", lambda ln: ln.replace("| BQ-16 |", "| BQ-17 |", 1)),
            "[bq-missing] BQ-16 missing",
        ),
        (
            "X115-bq-ruled",
            row_fn(
                r"^\| BQ-15 +\|.*$", lambda ln: re.sub(r"\| RULED( +)\|$", r"| PROPOSED\1|", ln)
            ),
            "[bq-ruled] BQ-15 not RULED",
        ),
        (
            "X13-bq-outcome",
            row_fn(
                r"^\| BQ-8 +\|.*$",
                lambda ln: ln.replace("no environment control at all", "a control", 1),
            ),
            "[bq-terms] BQ-8 row lost its ruled outcome",
        ),
        (
            "X12-cite-unpinned",
            sub(f"{key} `NN`", f"{key} (`D02:999`) `NN`"),
            "[cite-unpinned] cite not pinned in the tool's CITED_TABLE: `D02:999`",
        ),
        (
            "X116-cite-range",
            sub(f"`D02:635{EN_DASH}675`", f"`D02:635{EN_DASH}630`"),
            "[cite-range]",
        ),
        (
            "X18-upstream",
            frame_sub(
                "SCR-029/unsaved", "Applying Order-flow replaces them.", "Order-flow replaces them."
            ),
            "[upstream-frame] frame SCR-029/unsaved",
        ),
        (
            "X117-placeholder",
            sub("## 15. Summary\n", "## 15. Summary\n\n**Placeholder (§15):** to write.\n"),
            "[placeholder] placeholder §15",
        ),
        (
            "X118-home-path",
            sub(key, f"{key} (`/ho" + "me/alex/x/`)"),
            "[forbidden] spec: forbidden text",
        ),
        (
            "X119-windows-path",
            sub(key, key + " (C:" + "\\" + "Users" + "\\" + "alex" + "\\" + "x)"),
            "[forbidden] spec: forbidden text",
        ),
        ("X120-ip-address", sub(key, f"{key} (10.0.0" + ".7)"), "[forbidden] spec: forbidden text"),
        (
            "X145-unc-path",
            sub(key, key + " (" + "\\\\" + "nas\\share)"),
            "[forbidden] spec: forbidden text",
        ),
        (
            "X146-tailnet",
            sub(key, f"{key} (`box.tail1.ts" + ".net`)"),
            "[forbidden] spec: forbidden text",
        ),
        ("X121-closing", sub(key, f"{key} Closes #362."), "[closing] spec: a closing keyword"),
        (
            "X122-closing-colon",
            sub(key, f"{key} Fixes: #362."),
            "[closing] spec: a closing keyword",
        ),
        (
            "X123-closing-repo",
            sub(key, f"{key} Resolves owner/repo#362."),
            "[closing] spec: a closing keyword",
        ),
        (
            "X124-closing-url",
            sub(key, f"{key} Closes https://example.org/o/r/issues/362."),
            "[closing] spec: a closing keyword",
        ),
        ("X125-rule-id", sub(key, f"{key} (C-99.9)"), "[rule-id] spec: dangling rule id C-99.9"),
        (
            "X126-catalogue-id",
            sub(key, f"{key} (CMP-999)"),
            "[catalogue-id] spec: no catalogue heading for CMP-999",
        ),
    ]


def section_mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """The written sections (§5-§8, §11, §12), the markers and the sections' order."""

    row1 = (
        r"(^\| 1 +\| `color\.text\.primary` on `color\.surface\.overlay`"
        r" +\| hc-text +\| )13\.27"
    )

    def viewer_t2(ln: str) -> str:
        parts = ln.split("|")
        parts[5] = parts[5].replace("T1", "T2")
        return "|".join(parts)

    deck_row = (
        '| `e15.settings.environment` | the Share section | "Default environment for new panels" '
        "| PROPOSED |\n"
    )

    def add_deck_row(s: str) -> str:
        n = str(len(deck_ids(s) or ()))
        s = sec_fn(
            8,
            lambda t: t.replace("| `e15.settings.export`", deck_row + "| `e15.settings.export`", 1),
        )(s)
        return set_marker("deck_rows", n, str(int(n) + 1))(s)

    return [
        (
            "X128-sections",
            chain(sub("\n## 7. ", "\n## x7. "), sub("| 13.27 |", "| 13.37 |")),
            "[sections]",
        ),
        (
            "X23-not-t2-list",
            sec_fn(5, lambda t: t.replace("**Not T2", "**Also not T2", 1)),
            "[t2-paragraph]",
        ),
        (
            "X129-t2-once",
            sec_fn(
                6,
                lambda t: t.replace(
                    "**The exits, stated once",
                    "E09-D09's decision rule decides every control here. **The exits, stated once",
                    1,
                ),
            ),
            "[t2-once]",
        ),
        ("X130-exits-matrix", row_fn(r"^\| Cancel, `Esc`, Close.*$", viewer_t2), "[exits-matrix]"),
        (
            "X131-exits-a3",
            sec_fn(
                6,
                lambda t: t.replace(
                    "never locked by view-as, the kill switch",
                    "locked by view-as, the kill switch",
                    1,
                ),
            ),
            "[exits-a3] §6 lost",
        ),
        (
            "X144-exits-a3-standing",
            sub(
                "Close on every frame, never locked by view-as",
                "Close on every frame, locked by view-as",
            ),
            "[exits-a3] the standing additions lost A3",
        ),
        (
            "X132-planned-claim",
            sec_fn(7, lambda t: t.replace("full strength, never dimmed", "dimmed", 1)),
            "[planned-claims] §7 lost",
        ),
        (
            "X133-contrast-row",
            sec_fn(7, lambda t: re.sub(r"^\| 20 +\|.*\n", "", t, count=1, flags=MULTI)),
            "[contrast-row] §7 table lacks color.text.tertiary on color.surface.overlay",
        ),
        (
            "X26-contrast-cell",
            sec_fn(
                7,
                lambda t: re.sub(
                    row1,
                    r"\g<1>13.37",
                    t,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "[contrast-cell] §7 cell differs: color.text.primary on color.surface.overlay",
        ),
        (
            "X134-contrast-last-digit",
            sec_fn(
                7,
                lambda t: re.sub(
                    row1,
                    r"\g<1>13.28",
                    t,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "[contrast-cell] §7 cell differs: color.text.primary on color.surface.overlay",
        ),
        (
            "X135-contrast-verdict",
            sec_fn(
                7,
                lambda t: re.sub(
                    r"(^\| 9 +\|.*\| )PROPOSED( +\|)", r"\g<1>registered\2", t, count=1, flags=MULTI
                ),
            ),
            "[contrast-verdict]",
        ),
        (
            "X28-grey-cell",
            sec_fn(
                7,
                lambda t: re.sub(
                    r"(^\| `color\.status\.danger\.default` +\| )101",
                    r"\g<1>102",
                    t,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "[grey] §7 greyscale row differs or is missing: color.status.danger.default",
        ),
        (
            "X29-cvd-cell",
            sec_fn(
                7, lambda t: t.replace("14.7 · 12.5 · 14.0 · 5.5", "14.7 · 12.5 · 14.0 · 5.6", 1)
            ),
            "[cvd] §7 colour-vision row differs or is missing: color.status.danger.strong",
        ),
        (
            "X136-jargon",
            sec_fn(8, lambda t: t.replace('"Try again"', '"Try again (412)"', 1)),
            "[jargon]",
        ),
        (
            "X27-template",
            sec_fn(8, lambda t: t.replace('"and {n} more differences."', '"and {n} more."', 1)),
            "[template] §8 lacks the template e15.diff.overflow in both forms",
        ),
        (
            "X137-deck-line",
            sec_fn(
                8,
                lambda t: t.replace(
                    '"Cancel keeps your changes in this dialog."',
                    '"Cancel keeps your edits in this dialog."',
                    1,
                ),
            ),
            "[deck-line] §8 lacks the consequence line of Cancel",
        ),
        (
            "X22-deck-key",
            sec_fn(
                8,
                lambda t: re.sub(
                    r"^\| `e15\.conflict\.queued_status`",
                    "| `e15.conflict.queued_line`",
                    t,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "[key-deck] copy key not in the deck (§8) in SCR-029/conflict-queued",
        ),
        ("X138-env-deck", add_deck_row, "[env] environment word outside the allow-list in §8"),
        (
            "X139-env-anatomy",
            line_sub(
                "| Footer ", "end-aligned,", "end-aligned, a LIVE / DEMO toggle at its start,"
            ),
            "[env] environment word outside the allow-list in §2",
        ),
        (
            "X24-g-row",
            sec_fn(11, lambda t: re.sub(r"^\| D08-G2 ", "| D08-G9 ", t, count=1, flags=MULTI)),
            "[g-row] §11 lacks the G-row D08-G2",
        ),
        (
            "X25-sign-off-item",
            sec_fn(
                12,
                lambda t: t.replace("no default destructive button", "no destructive default", 1),
            ),
            "[sign-off] §12 lacks the item 'no default destructive button'",
        ),
        (
            "X140-marker-visible",
            sub("10 <!-- audit:boards=10 --> boards,", "11 <!-- audit:boards=10 --> boards,"),
            "[marker-visible] printed 11 beside audit:boards=10",
        ),
        (
            "X141-marker-rows-g",
            set_marker("rows.G", "8", "9"),
            "[marker-value] marker audit:rows.G=9 vs tool 8",
        ),
        (
            "X142-marker-parse",
            sub("<!-- audit:boards=10 --> boards,", "<!-- audit:boards=10--> boards,"),
            "[marker-parse]",
        ),
        (
            "X143-marker-count",
            sub(" (2 <!-- audit:light_twins=2 --> light twins)", " (2 light twins)"),
            "[marker-count] audit:light_twins appears 1 times, 2 expected",
        ),
        # Fold r2 (the delta r1): MAJOR-1 — an environment control in §0's or §2's prose (X148 is
        # the lens's M16d:prose-2.3).
        (
            "X148-env-prose-2.3",
            sub(
                "the anatomy of §2.2 holds unless the row says otherwise.",
                "the anatomy of §2.2 holds unless the row says otherwise. Startup also holds a "
                "Default environment for new panels select (DEMO or LIVE).",
            ),
            "[env] environment word outside the allow-list in §2",
        ),
        (
            "X149-env-prose-2.1",
            sub(
                "### 2.1 Frames (binding; the tool gates every row)\n\n",
                "### 2.1 Frames (binding; the tool gates every row)\n\nEvery frame draws the "
                "CMP-075 LIVE pill beside the title.\n\n",
            ),
            "[env] environment word outside the allow-list in §2",
        ),
        (
            "X150-env-prose-0",
            sub(
                "**Reconciliation rule:**",
                "Board 01 draws an Environment dropdown, LIVE or DEMO. **Reconciliation rule:**",
            ),
            "[env] environment word outside the allow-list in §0",
        ),
        # MAJOR-2 — §2.3's planned row (X151 is the lens's M5z:s2.3-row), the BQ-2 row (X154, the
        # lens's M5z:s2-prose regex), D08-D3 and the default frame's row.
        (
            "X151-planned-row",
            row_fn(
                r"^\| planned-description, .*$",
                lambda ln: ln.replace(
                    "the board's annotation layer only", "the dialog, as a field well", 1
                ),
            ),
            "[planned-row] §2.3's planned row is not the fixed row",
        ),
        (
            "X152-planned-row-focus",
            row_fn(
                r"^\| planned-description, .*$",
                lambda ln: ln.replace(
                    "nothing in the shipped dialog: no Tab stop",
                    "a Tab stop each in the shipped dialog",
                    1,
                ),
            ),
            "[planned-row] §2.3's planned row is not the fixed row",
        ),
        (
            "X153-planned-row-dim",
            row_fn(
                r"^\| planned-description, .*$",
                lambda ln: ln.replace(
                    "a `color.surface.raised` box,",
                    "a `color.surface.raised` box at `opacity.disabled`,",
                    1,
                ),
            ),
            "[planned-row] §2.3's planned row is not the fixed row",
        ),
        (
            "X168-default-planned",
            frame_sub(
                "SCR-025/default",
                "live in the board's annotation layer only",
                "live in the dialog, as a field well",
            ),
            "[planned-claims] the `SCR-025/default` row lost",
        ),
        (
            "X169-restated-name-help",
            row_fn(
                r"^\| more than 40 .*$",
                lambda ln: ln.replace(
                    '"Use at most 40 characters."', '"Use at most 41 characters."'
                ),
            ),
            "[restated] §2 prints",
        ),
        (
            "X154-bq2-planned",
            line_sub("| BQ-2 ", "never a control, never T", "a CMP-009 select, never T"),
            "[planned-claims] the BQ-2 row lost",
        ),
        (
            "X155-d3-planned",
            line_sub(
                "| D08-D3 ",
                "live on board 01's annotation layer only, and the shipped dialog renders none "
                "of them",
                "are drawn in the dialog as field wells",
            ),
            "[planned-claims] the D08-D3 row lost",
        ),
        # MINOR-2 — the exits never held or hidden.
        (
            "X156-exit-held",
            frame_sub(
                "SCR-025/delete-confirm",
                "footer: Cancel (`secondary`)",
                "footer: Cancel (`secondary`, held until the save returns)",
            ),
            "[exit-gated] exit drawn gated in SCR-025/delete-confirm",
        ),
        (
            "X157-exit-hidden",
            frame_sub(
                "SCR-025/default",
                f"the close {TIMES} named",
                f"the close {TIMES} hidden under view-as, named",
            ),
            "[exit-gated] exit drawn gated in SCR-025/default",
        ),
        # MINOR-3 — the S4 formula, a detached marker's line, §8's fixtures, the restatements.
        (
            "X158-reflow-formula",
            frame_sub(
                "SCR-025/reflow-200", f"2 {TIMES} space.inset.lg", f"3 {TIMES} space.inset.lg"
            ),
            "[upstream-frame] frame SCR-025/reflow-200",
        ),
        (
            "X159-detached-marker",
            line_sub("| D08-A10 ", "Use at most 40 characters.", "Use at most 41 characters."),
            "[marker-visible] audit:contract.name_max=40 detached",
        ),
        (
            "X160-deck-counter",
            sec_fn(8, lambda t: t.replace('fixture "41/40"', 'fixture "42/40"', 1)),
            "[deck-fixture] §8 e15.settings.name.counter",
        ),
        (
            "X161-deck-time",
            sec_fn(
                8,
                lambda t: t.replace(
                    'fixture "Replace the version saved at 14:05?"',
                    'fixture "Replace the version saved at 14:06?"',
                    1,
                ),
            ),
            "[deck-fixture] §8 e15.conflict.confirm.title",
        ),
        (
            "X162-restated-revert",
            sub(
                '"Layout 1 reverted to the version saved at 13:40.". Focus',
                '"Layout 1 reverted to the version saved at 13:41.". Focus',
            ),
            "[restated] §3 prints",
        ),
        (
            "X163-restated-overwrite",
            sub(
                'titled "Replace the version saved at 14:05?"',
                'titled "Replace the version saved at 14:06?"',
            ),
            "[restated] §4 prints",
        ),
        (
            "X164-restated-col",
            sec_fn(
                6,
                lambda t: t.replace('"Saved now (14:05:12)"', '"Saved now (14:05:13)"', 1),
            ),
            "[restated] §6 prints",
        ),
        # MINOR-4 — a WSL share path.
        (
            "X165-unc-wsl",
            sub("**Key.**", "**Key.** (" + "\\\\" + "wsl$\\Ubuntu\\home\\someone)"),
            "[forbidden] spec: forbidden text",
        ),
        # NIT-2 — the two per-site branches no mutation reached.
        (
            "X166-clean-star-producer",
            frame_sub("SCR-025/delete-confirm", 'title "Delete Scalping?"', "title `Scalping *`"),
            "[clean-star] clean frame SCR-025/delete-confirm draws a dirty `*` in its Shows cell",
        ),
        (
            "X167-entry-dialog-unmapped",
            row_fn(
                r"^\| E12 +\|.*$",
                lambda ln: ln.replace("| `SCR-025/discard-prompt` (H36", "| the prompt (H36", 1),
            ),
            "[entry-unmapped] entry point unmapped: E12",
        ),
    ]


def round1_mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """The orchestrator's text round 1: each hand edit that passed, in the record's words (MJ-1 to
    MJ-4, the carries m2 and m3), plus the brief's vocabulary — one new FAIL each."""
    env = "[env] environment word outside the allow-list in "
    gated = "[exit-gated] exit drawn gated in "
    share = "Share (Export…)"

    def s025(add: str) -> Callable[[str], str]:
        return frame_sub("SCR-025/default", share, f"{share[:-1]}, {add})")

    def before_exits(frame: str, add: str) -> Callable[[str], str]:
        return frame_sub(frame, "; exits T1:", f"; {add}; exits T1:")

    def entry(eid: str, add: str) -> Callable[[str], str]:
        return row_fn(
            rf"^\| {eid} +\|.*$",
            lambda ln: ln.replace("| no dialog — ", f"| no dialog — {add}; ", 1),
        )

    return [
        # MJ-1: the environment vocabulary, any case, in every row and in the prose.
        ("R1-env-demo", s025('a CMP-004 "Open new panels on demo"'), env + "SCR-025/default"),
        ("R1-env-pin", s025('a CMP-004 "Pin this workspace to live"'), env + "SCR-025/default"),
        ("R1-env-select", s025('a select "Env: demo / live"'), env + "SCR-025/default"),
        ("R1-env-paper", s025('a CMP-004 "Paper-trade new panels"'), env + "SCR-025/default"),
        (
            "R1-env-dirty-callout",
            before_exits("SCR-025/dirty", 'a CMP-028 warning callout "pinned to live"'),
            env + "SCR-025/dirty",
        ),
        (
            "R1-env-prose-demo",
            sub(
                "so opening reads nothing.",
                "so opening reads nothing. It opens new panels on the demo account, never live.",
            ),
            env + "§2",
        ),
        (
            "R1-env-prose-pinned",
            sub(
                "Both travel unchanged in every Save",
                "A workspace can be pinned to the demo account. Both travel unchanged in every "
                "Save",
            ),
            env + "§2",
        ),
        (
            "R1-env-holds-row",
            row_fn(
                r"^\| Share +\|.*$",
                lambda ln: "| Defaults | defaults | Open new panels on demo | nothing |\n" + ln,
            ),
            env + "§2",
        ),
        (
            "R1-env-board-01",
            row_fn(
                r"^\| 01 +\|.*$",
                lambda ln: ln.replace(
                    " in the annotation layer;",
                    " in the annotation layer; the demo / live pin;",
                    1,
                ),
            ),
            env + "§0",
        ),
        (
            "R1-env-029-live",
            frame_sub(
                "SCR-029/unsaved",
                "; initial focus: Cancel",
                '; a CMP-004 "Apply Order-flow on LIVE" switch; initial focus: Cancel',
            ),
            env + "SCR-029/unsaved",
        ),
        (
            "R1-env-029-default",
            frame_sub(
                "SCR-029/conflict",
                "; initial focus: Cancel",
                '; a "Default environment for new panels" select; initial focus: Cancel',
            ),
            env + "SCR-029/conflict",
        ),
        (
            "R1-env-5.1-row",
            row_fn(
                r"^\| Save mine as new layout… \(SCR-029 conflict\) .*$",
                lambda ln: (
                    ln
                    + "\n"
                    + ln.replace(
                        "Save mine as new layout… (SCR-029 conflict)",
                        "Default environment for new panels (SCR-025)",
                        1,
                    )
                ),
            ),
            env + "§5",
        ),
        (
            "R1-env-6-tab-stop",
            sub(
                "`Tab` and `Shift+Tab` cycle inside the topmost dialog only;",
                "`Tab` and `Shift+Tab` cycle inside the topmost dialog only, with a Tab stop on "
                "the environment select;",
            ),
            env + "§6",
        ),
        (
            "R1-env-phrase-copy",
            before_exits("SCR-025/dirty", "the TopBar with its env band"),
            "[env] environment phrase 'the TopBar with its env band' 2 times, 1 pinned",
        ),
        # MJ-2: an exit gated in other words, and `Esc` doing anything but cancel.
        (
            "R1-exit-cant",
            before_exits(
                "SCR-029/unsaved-saving",
                "Discard changes can't be pressed while the write is in flight",
            ),
            gated + "SCR-029/unsaved-saving",
        ),
        (
            "R1-exit-inert",
            before_exits("SCR-029/unsaved-saving", "Discard changes is inert until the answer"),
            gated + "SCR-029/unsaved-saving",
        ),
        (
            "R1-exit-ignored",
            before_exits("SCR-025/saving", "Cancel and Esc are ignored until the server answers"),
            gated + "SCR-025/saving",
        ),
        (
            "R1-exit-waits",
            before_exits(
                "SCR-029/conflict",
                "under the kill switch, Load theirs waits for the switch to clear",
            ),
            gated + "SCR-029/conflict",
        ),
        (
            "R1-exit-does-nothing",
            before_exits("SCR-025/failed", "Esc does nothing while the banner shows"),
            gated + "SCR-025/failed",
        ),
        (
            "R1-exit-not-operable",
            before_exits("SCR-029/revert", "Cancel is not operable while viewing as"),
            gated + "SCR-029/revert",
        ),
        (
            "R1-exit-suppressed",
            before_exits(
                "SCR-029/keep-mine-confirm", "Cancel is suppressed for the first 400 ms too"
            ),
            gated + "SCR-029/keep-mine-confirm",
        ),
        (
            "R1-exit-greyed",
            before_exits("SCR-025/saving", "Cancel is greyed out while saving"),
            gated + "SCR-025/saving",
        ),
        (
            "R1-exit-inactive",
            before_exits("SCR-025/dirty", "Close is inactive under the kill switch"),
            gated + "SCR-025/dirty",
        ),
        (
            "R1-exit-unusable",
            before_exits("SCR-029/view-as-unsaved", "Discard changes is unusable while viewing as"),
            gated + "SCR-029/view-as-unsaved",
        ),
        (
            "R1-esc-arrow-discards",
            before_exits("SCR-029/unsaved-saving", "a second Esc → discards the copy"),
            "[esc] Esc not mapped to Cancel in SCR-029/unsaved-saving",
        ),
        (
            "R1-esc-discards",
            before_exits("SCR-029/unsaved", "a second Esc discards the copy"),
            "[esc] Esc not mapped to Cancel in SCR-029/unsaved",
        ),
        # MJ-3: the whole first-focus clause, and any clause that moves focus later.
        (
            "R1-focus-then",
            frame_sub(
                "SCR-029/unsaved",
                "initial focus: Cancel;",
                "initial focus: Cancel, then Discard changes once the summary is read;",
            ),
            "[focus-safe] initial focus not on the safe action in SCR-029/unsaved",
        ),
        (
            "R1-focus-moved-aside",
            frame_sub(
                "SCR-029/conflict-from-preset",
                "initial focus: Cancel;",
                "initial focus: Cancel (moved to Keep mine after 400 ms);",
            ),
            "[focus-safe] initial focus not on the safe action in SCR-029/conflict-from-preset",
        ),
        (
            "R1-focus-moves-later",
            before_exits("SCR-029/conflict", "after 400 ms focus moves to Keep mine"),
            "[focus-moved] a clause moves focus off the safe action in SCR-029/conflict",
        ),
        # MJ-4: a prompt beside the words "no dialog".
        (
            "R1-entry-toast",
            entry("E2", 'a toast asks "Save now?" before the switch'),
            "[entry-prompt] a prompt on the no-dialog route E2",
        ),
        (
            "R1-entry-confirm",
            entry("E7", "a confirm asks before the tab closes"),
            "[entry-prompt] a prompt on the no-dialog route E7",
        ),
        # m3: the same holes outside the frame rows.
        (
            "R1-planned-table-field",
            sub(
                "Description, under Name (`SCR-025/planned-description`)",
                "Description, a text field under Name (`SCR-025/planned-description`)",
            ),
            "[planned-prose] a planned inset drawn as a control or dim: §2 planned row",
        ),
        (
            "R1-planned-prose-switch",
            sub(
                "an absence by plan (§5). A note",
                "an absence by plan (§5). The shipped dialog shows each as a disabled switch. "
                "A note",
            ),
            "[planned-prose] a planned inset drawn as a control or dim: §2 paragraph",
        ),
        (
            "R1-route-opens",
            sub(
                "**What the unsaved variant never does.**",
                "It opens on a tab switch and an app close. **What the unsaved variant never "
                "does.**",
            ),
            "[route-opens] §3 opens the dialog on a no-dialog route",
        ),
        (
            "R1-sibling-sha",
            sub(
                "E15-D04 and E15-D06 merged as text after",
                "E15-D05 merged at `5b0c1d2e3f405162738495a6b7c8d9e0f1a2b3c4`. E15-D04 and "
                "E15-D06 merged as text after",
            ),
            "[sha-unknown] a full sha the tool does not know: 5b0c1d2e3",
        ),
        (
            "R1-sibling-cite",
            sub(
                "E15-D04 and E15-D06 merged as text after",
                "E15-D05 (`D05:120`) is PENDING. E15-D04 and E15-D06 merged as text after",
            ),
            "[cite-unknown] a cite under a key the tool does not know: D05",
        ),
        # m2: RULED names the ruling, not the BQ comment.
        (
            "R1-ruling-heading",
            sub(
                "(2026-10-25, the ruling comment 6392398481 on the BQ comment",
                "(2026-10-25, on the BQ comment",
            ),
            "[head-ruling] RULED does not name the ruling comment 6392398481",
        ),
        (
            "R1-ruling-status",
            sub(
                "RULED is the orchestrator's ruling, #362 comment 6392398481",
                "RULED is the orchestrator's",
            ),
            "[head-ruling] RULED does not name the ruling comment 6392398481",
        ),
    ]


def context_mutations() -> list[tuple[str, Callable[[dict[str, str]], dict[str, str]], str]]:
    """The gates that read the cited plan texts, each tripped through an in-memory copy of them."""

    def swap_pointer(t: dict[str, str]) -> dict[str, str]:
        lines = t["14"].split("\n")
        i = next(n for n, ln in enumerate(lines) if POINTER in ln)
        lines[i - 1], lines[i] = lines[i], lines[i - 1]
        return {**t, "14": "\n".join(lines)}

    topic = "| `layouts`      | `layout_ids` | Current layout tokens | 0 |\n"
    return [
        (
            "C1-cite-gone",
            ctx_sub(
                "D02",
                "layout events are analytics, never audit",
                "layout events are analytics only",
            ),
            "[cite-gone] cited text gone: `D02:84`",
        ),
        (
            "C2-cite-ambiguous",
            lambda t: {**t, "D02": t["D02"] + "\nlayout events are analytics, never audit\n"},
            "[cite-ambiguous] cited text twice: `D02:84`",
        ),
        ("C3-pointer-14", swap_pointer, "[pointer-14]"),
        (
            "C4-reason-drift",
            ctx_sub(
                "D09", "Read-only while viewing as {user}.", "Read-only while you view as {user}."
            ),
            "[reason-drift] reason string drifted from D09: rbac.view_as",
        ),
        (
            "C5-permission",
            ctx_sub("D09", '"Your role can\'t {verb}."', '"Your role cannot {verb}."'),
            "[permission]",
        ),
        (
            "C6-upstream-gone",
            ctx_sub("D02", "Changed again in another window.", "Changed again elsewhere."),
            "[upstream-gone] upstream string gone from D02",
        ),
        (
            "C7-fact-412",
            lambda t: {
                **t,
                "22": re.sub(
                    r"(- code: version_conflict\n\s+status: )412", r"\g<1>409", t["22"], count=1
                ),
            },
            "[contract-fact] contract fact changed: version_conflict_412",
        ),
        (
            "C8-fact-unstored",
            ctx_sub("22", "        icon_token:", "        description:"),
            "[contract-fact] contract fact changed: unstored_absent",
        ),
        (
            "C9-fact-refusals",
            ctx_sub(
                "22",
                "`concurrent_update` (a racing write; retry)",
                "`racing_update` (a racing write; retry)",
            ),
            "[contract-fact] `22` workspace refusals now",
        ),
        (
            "C10-fact-last",
            ctx_sub(
                "22",
                'message: "You need at least one workspace."',
                'message: "Keep one workspace."',
            ),
            "[contract-fact] `22` deleteWorkspace's last_workspace sentence changed",
        ),
        (
            "C11-ws-topic",
            ctx_sub("23", "| `system`       |", topic + "| `system`       |"),
            "[ws-topic]",
        ),
    ]


def frame_family(spec: str, ctx: Ctx) -> list[str]:
    """The per-frame gates alone (frames, boards, the entry-point matrix)."""
    return (
        frame_gates(spec, ctx.facts, deck_ids(spec)) + board_gates(spec)[0] + entry_gates(spec)[0]
    )


def gate_codes() -> set[str]:
    """Every gate code of this file: the `fail("code", …)` calls above `mutations()`."""
    src = TOOL.read_text(encoding="utf-8")
    return set(re.findall(r'\bfail\(\s*"([a-z0-9-]+)"', src[: src.index("\ndef mutations(")]))


def code_of(expect: str) -> str:
    m = re.match(r"\[([a-z0-9-]+)\]", expect)
    return m.group(1) if m else ""


def self_test(spec: str, ctx: Ctx) -> list[str]:
    """Each mutation adds exactly one new FAIL carrying its expected text; every gate code has a
    mutation (EXEMPT aside); the A2 list is complete; the spec on disk is untouched."""
    bad: list[str] = []
    digest = hashlib.sha256(SPEC.read_bytes()).hexdigest()
    base, _ = gates(spec, ctx)
    family = frame_family(spec, ctx)
    if family:
        bad.append(
            f"self-test: the unmutated spec fails {len(family)} per-frame gates: {family[:2]}"
        )
    spec_m, ctx_m = mutations(), context_mutations()
    named = [(n, e) for n, _, e in spec_m] + [(n, e) for n, _, e in ctx_m]
    names = [n for n, _ in named]
    if len(set(names)) != len(names):
        bad.append("self-test: two mutations share a name")
    bad += [f"self-test: the brief's A2 mutation {n} is gone" for n in A2_NAMES if n not in names]
    codes, covered = gate_codes(), {code_of(e) for _, e in named}
    bad += [
        f"self-test: gate code {c} has no mutation" for c in sorted(codes - covered - set(EXEMPT))
    ]
    bad += [f"self-test: EXEMPT names {c}, no gate code" for c in sorted(set(EXEMPT) - codes)]
    bad += [f"self-test: {n} expects no known code" for n, e in named if code_of(e) not in codes]
    runs: list[tuple[str, str, Ctx, str]] = []
    for name, fn, expect in spec_m:
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
        if len(new) != 1 or expect not in new[0]:
            bad.append(f"self-test {name}: expected one new FAIL with {expect!r}, got {new[:3]}")
    again, _ = gates(spec, ctx)
    if sorted(again) != sorted(base):
        bad.append("self-test: the restored spec does not reproduce the base result")
    if hashlib.sha256(SPEC.read_bytes()).hexdigest() != digest:
        bad.append("self-test: the spec on disk changed")
    return bad


def report(ctx: Ctx, numbers: dict[str, Any], bad: list[str]) -> list[str]:
    m = ctx.measured
    out = [
        "## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs.mjs | where)"
    ]
    for r in m["matrix"]:
        if r["verdict"] == "MISSING":
            out.append(f"{r['fg']} on {r['bg']} | {r['role']} | MISSING token | {r['element']}")
            continue
        cells_ = " / ".join(show(r[th]) for th in THEMES)
        out.append(
            f"{r['fg']} on {r['bg']} | {r['role']} | {cells_} | {r['verdict']} | "
            f"{r['pairs']} | {r['element']}"
        )
    out.append(
        f"validity composite (Save at opacity.disabled on the dialog; reported): {m['composite']}"
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
    out.append(
        "summaries: "
        + json.dumps(
            {k: render_summary(FIXTURE[k]) for k in ("ac3", "overflow")}, ensure_ascii=False
        )
    )
    ok = (
        f"OK — {len(gate_codes())} gate codes: the header, the deviations, the AC trace, the ruled "
        "questions and the numbered sections; §0's boards and their reconciliation; every "
        "per-frame gate (the dirty marker and its inverse, T2 anatomy with view-as first, planned "
        "insets as the fixed sentence, Cancel first, `secondary` and focused, every Esc → Cancel, "
        "the exits never gated, the footer's verbs and weights, the component and its size, the "
        "typed field, the consequence lines in footer order, the 412, every quoted number); the "
        "entry-point matrix; reasons and upstream strings; the cites; the `14` pointer lines; §5, "
        "§5.1, §6, §7, §8, §11 and §12; no environment control; every marker printed, parsed, "
        "re-derived and kept; no private path, no closing keyword, no dangling id; no placeholder"
    )
    out.append("\n## 5. Gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    return out


def main(argv: list[str]) -> int:
    ctx = Ctx()
    spec = SPEC.read_text(encoding="utf-8")
    bad, numbers = gates(spec, ctx)
    warns = list(CITE_WARN)
    out = report(ctx, numbers, bad)
    if "--check" in argv:
        mism = [b for b in bad if b.startswith("[marker")]
        out.append("markers: " + ("clean" if not mism else "MISMATCH"))
    st_bad: list[str] = []
    if "--self-test" in argv:
        st_bad = self_test(spec, ctx)
        out.append(
            "self-test: "
            + (
                f"ok — {numbers['mutations']} mutations, each caught once by one new FAIL; every "
                f"gate code but the {len(EXEMPT)} EXEMPT has one; M1-M17 present; the per-frame "
                "gates are clean on the unmutated spec; the spec on disk is unchanged"
                if not st_bad
                else "FAILED"
            )
        )
        out += [f"FAIL {b}" for b in st_bad]
    if "--json" in argv:
        palette = {th: {n: resolve(ctx.themes[th], n) for n in BINDINGS} for th in THEMES}
        inventory = {name: {"kind": kind, **params} for name, (kind, params) in KIND.items()}
        payload = {
            "numbers": numbers,
            "matrix": ctx.measured["matrix"],
            "grey": ctx.measured["grey"],
            "cvd": ctx.measured["cvd"],
            "missing": ctx.missing,
            "facts": ctx.facts,
            "inventory": inventory,
            "summaries": {k: render_summary(FIXTURE[k]) for k in ("ac3", "overflow")},
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
