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
contract facts the frames quote, parsed from `22` / `14` / `15` / `23` / E15-D02 / E09-D09 text,
never typed; (5) the gates: the header, the deviations, the AC trace, the ruled questions, §0's
boards and their reconciliation with the frame rows, the PER-FRAME gates over every `SCR-025/` and
`SCR-029/` row of §2-§4 (each frame's obligations come from the tool's own KIND table, never from
the row's Class cell, which must agree), the entry-point matrix, the reason and upstream strings,
the copy keys, the cites (a moved line is a WARN; a fragment gone or ambiguous is a FAIL; a cite
missing from CITED_TABLE is a FAIL), the `14` pointer lines, private paths and hosts, closing
keywords, dangling rule and catalogue ids, every `**Placeholder (§n):**` paragraph still in the
spec (a FAIL, so a skeleton never passes), and the written sections: §5's one T2 paragraph and its
not-T2 list, §7's tables equal to sections 1 and 3, §8's templates and consequence lines, §11's
G-rows and §12's sign-off items; (6) the counts. `--json` is the only source of every
number in the spec; `--check` re-derives every `<!-- audit:KEY=VALUE -->` marker (markers are
checked on every run); `--self-test` applies each named mutation of `mutations()` to an in-memory
copy of the spec and passes only when each adds exactly one new FAIL naming its gate, the per-frame
gates are clean on the unmutated spec and the spec on disk is byte-identical afterwards. Exit 1 on
a gated FAIL.

Usage: python3 -I -B docs/design/_tools/e15_d08_settings_conflict_audit.py [--json] [--check]
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
BASE = "0bf4b87c556a7ae8cba11a584b2f81708c0c9bd9"
# The merged inputs the header pins (E15-D01, E15-D02 text and boards, E05-D02 slices 3 and 4,
# E09-D09): each full sha must stand in the header.
MERGE_SHAS = (
    "ed8a22246263ace73f39e4434e6d5f57b1a857bd",
    "1044c4f602eff6ae1a2cf42201ab398f6c4234d1",
    "7be6eac6a705cf24ba534ce4f7d31349a1e29932",
    "3a2fc5c299a37e74ca8fb962d4435335b79aead9",
    "04a8caa9513e90debcf7cbc41a9ca585496eba01",
    "baccf724a1fa3ad66f9333e440a7f5e8668b6eff",
)
PENPOT_PAGE = "E15-D08 Workspace settings and conflicts"
STATUS_WORDS = ("text-first", "PROPOSED unless RULED", "boards PENDING", "≤ 10 boards", "≤ 1/3")
# Generic patterns only (the repo is public): a local home path, a design-tool host, a team or file
# id query, a home-relative path. Split literals keep the tool from matching itself.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"~/[a-z0-9-]+/",
)
CLOSING = r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s+#\d+"
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
    "README": DESIGN / "README.md",
}
EN_DASH = "\u2013"
CITE_RE = (
    r"`(04|05|11|14|15|16|21|22|23|BL|D01|D02|FL|S3|S4|D09|E16D03|README):(\d+)(?:"
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
14 | 610 | ### SCR-025 — Workspace settings modal
14 | 612 | default account scope, density (compact/cosy/comfortable), theme override
14 | 614 | the last workspace cannot be deleted ("You need at least one workspace.")
14 | 615 | **Stories:** US-WS-020.
14 | 616 | grouped fieldsets for defaults (symbol, interval, environment binding)
14 | 618 | CMP-001 Button, CMP-004 Toggle, CMP-019 Icon (`lock`), CMP-040 FormField
14 | 619 | - **Stories:** US-LAY-002, US-LAY-003.
14 | 621 | [ ] 'this workspace is pinned to LIVE' warning drawn
14 | 659 | ### SCR-029 — Unsaved-changes / layout-conflict dialog
14 | 661 | the conflict variant adds a side-by-side summary of differences
14 | 662 | CMP-027 ErrorState / InlineError, CMP-044 ConfirmDialog, CMP-079 RbacGate.
14 | 664 | the three choices are explicit buttons with verbs
14 | 665 | within 300 ms of the conflicting write being detected
14 | 666 | `layout.conflict_detected`, `layout.conflict_resolved` with `{choice}` (analytics)
14 | 668 | [ ] Esc maps to Cancel, never to Discard
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
22 | 658 | - code: version_conflict
22 | 8507 | `limit_reached` (32 live workspaces)
22 | 8555 | `ETag`: the workspace token versions its metadata only
22 | 8570 | operationId: updateWorkspace
22 | 8587 | `412 version_conflict` (stale or unparseable `If-Match`, nothing
22 | 8616 | operationId: deleteWorkspace
22 | 8621 | workspace is `409 conflict` with `errors[0].rule = last_workspace`
22 | 8707 | `limit_reached` (32 live layouts)
22 | 8821 | operationId: updateLayout
22 | 8830 | `If-Match`, the no-op rule and `412 version_conflict` work as on `updateWorkspace`
22 | 12658 | operationId: exportWorkspace
22 | 19576 | WorkspaceIconToken:
22 | 19585 | WorkspaceInput:
22 | 19595 | `name` is at most 40 characters as sent (rule
22 | 19647 | Concurrency token (also the `ETag`) for the workspace metadata only
22 | 19854 | Panes have no id of their own
22 | 19960 | of the whole layout aggregate, panes included
22 | 20390 | density: { type: string, enum: [compact, comfortable, spacious] }
22 | 20431 | default_environment: { $ref:
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
IRREVERSIBLE = "can't be undone"
# frame | kind | parameters — the independent inventory every per-frame gate reads; a row's Class
# cell must agree with it and never decides. `keys` = the T2 reason keys the row must name; `time`
# = the fixture time its consequence lines render; `diff` = the summary case it renders.
KIND_TABLE = """
SCR-025/default | form |
SCR-025/compact | inset |
SCR-025/planned-description | planned | gap=D08-G1
SCR-025/planned-defaults | planned | gap=D08-G2
SCR-025/planned-density | planned | gap=D08-G3
SCR-025/planned-theme | planned | gap=D08-G4
SCR-025/dirty | form-dirty |
SCR-025/invalid-empty | invalid | rule=empty
SCR-025/invalid-long | invalid | rule=long
SCR-025/invalid-duplicate | invalid | rule=taken
SCR-025/discard-prompt | discard-prompt |
SCR-025/saving | busy |
SCR-025/saved | outcome |
SCR-025/failed | refusal |
SCR-025/settings-conflict | settings-conflict | time=conflict
SCR-025/delete-confirm | delete-confirm |
SCR-025/delete-racing | delete-racing | keys=workspace.limit.last
SCR-025/delete-last | t2-state | keys=workspace.limit.last
SCR-025/viewer-read-only | t2-viewer | keys=notice.panel_read_only,rbac.permission
SCR-025/view-as | t2-view-as | keys=rbac.view_as
SCR-025/leg-lost | t2-leg | keys=rbac.permission
SCR-025/reflow-200 | reflow |
SCR-029/unsaved | unsaved | diff=ac3
SCR-029/unsaved-overflow | unsaved | diff=overflow
SCR-029/unsaved-saving | unsaved-busy |
SCR-029/revert | revert |
SCR-029/viewer-unsaved | unsaved-t2 | keys=rbac.permission
SCR-029/view-as-unsaved | unsaved-t2 | keys=rbac.view_as
SCR-029/reflow-200 | reflow |
SCR-029/compact | inset |
SCR-029/conflict | conflict | time=conflict;table=yes
SCR-029/conflict-from-preset | conflict | time=conflict;table=yes
SCR-029/conflict-refreshed | conflict | time=refreshed
SCR-029/conflict-queued | queued |
SCR-029/keep-mine-confirm | overwrite-confirm | time=conflict
SCR-029/save-as-t2 | conflict-t2 | keys=layout.limit.count
SCR-029/leg-lost | conflict-t2 | keys=rbac.permission
"""
DIRTY_KINDS = {
    "form-dirty",
    "invalid",
    "discard-prompt",
    "busy",
    "refusal",
    "settings-conflict",
    "unsaved",
    "unsaved-busy",
    "unsaved-t2",
    "revert",
    "conflict",
    "queued",
    "overwrite-confirm",
    "conflict-t2",
}
T2_KINDS = {
    "t2-state",
    "t2-viewer",
    "t2-view-as",
    "t2-leg",
    "unsaved-t2",
    "conflict-t2",
    "delete-racing",
}
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
CONFLICT_412_KINDS = {"conflict", "conflict-t2", "queued", "settings-conflict"}
BUSY_KINDS = {"busy", "unsaved-busy"}
UNVERBED_KINDS = SCR029_DIALOG_KINDS | {"overwrite-confirm", "discard-prompt", "settings-conflict"}
SAFE = ("Cancel", "Keep editing")
EXIT_RE = r"\b(?:Cancel|Esc|Close|Discard(?: changes)?|Keep editing|Load theirs)\b"
DESTRUCTIVE = ("Discard changes", "Load theirs", "Keep mine", "Revert to saved")
UNVERBED = ("OK", "Yes", "No", "Confirm", "Discard", "Apply", "Done")
# Words that make a planned inset read as a control (M5) or as a lock or a dimmed control (M6).
CONTROL_RE = (
    r"\bfield well\b|\bCMP-(?:003|004|007|009|048|062|063|105|106|219|220)\b|\btoggle\b"
    r"|\bswitch\b|\bselect\b|\bcombobox\b|\blistbox\b|\bradio|\bsegmented\b|\bcheckbox\b"
    r"|\bpicker\b|\binput\b|▾|\[ \]"
)
DIM_RE = (
    r"\bT2\b|\block\b|opacity\.disabled|aria-disabled|color\.text\.disabled|\bdimmed\b|\bgreyed\b"
)
T2_DIM_RE = r"opacity\.disabled|color\.text\.disabled"
# An environment control on SCR-025 (BQ-8 RULED: none at all, not even contract-pending).
ENV_RE = (
    r"(?i)default environment|environment for new panels|pin(?:ned)? to LIVE|environment binding"
    r"|\bDEMO\s*/\s*LIVE\b|environment (?:select|picker|toggle|switch|control)"
)
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
# string | doc | frames — upstream copy the frames quote verbatim (each must still exist upstream).
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
You need at least one workspace. | 22 | SCR-025/delete-last, SCR-025/delete-racing
Read-only — your role can't save workspaces. | D02 | SCR-025/viewer-read-only
This workspace isn't saved. | D02 | SCR-025/viewer-read-only
"""
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
14 | 614 | SCR-025/delete-confirm, SCR-025/delete-last
14 | 621 | SCR-025/default, SCR-025/planned-defaults, SCR-025/discard-prompt
14 | 621 | SCR-025/delete-confirm, SCR-025/delete-last
14 | 661 | SCR-029/unsaved, SCR-029/conflict
14 | 668 | SCR-029/unsaved, SCR-029/conflict
"""
COPY_KEY_RE = (
    r"^(?:e15\.[a-z0-9_.]+|rbac\.[a-z_]+|notice\.[a-z_]+|workspace\.limit\.[a-z_]+"
    r"|layout\.limit\.[a-z_]+)$"
)
PLACEHOLDER_RE = r"\*\*Placeholder \(§(\d+)\):\*\* ([^\n]+)"
# Section gates that wake up once a placeholder is replaced. §7's table: `| n | `fg` on `bg` | role
# | dark | light | hc | verdict | registered or PROPOSED | where |`, each cell within CELL_TOLERANCE
# of the tool's value and the verdict and the `pairs.mjs` column the tool's own words.
CELL_TOLERANCE = 0.0051
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


def legs(line: str) -> list[str] | None:
    m = re.search(r"legs ((?:`[a-z_.]+`\s*(?:→\s*)?)+)", line)
    return re.findall(r"`([a-z_.]+)`", m.group(1)) if m else None


def frame_gates(spec: str, facts: dict[str, Any], deck: set[str] | None) -> list[str]:
    """The per-frame gates (A2: M1-M17 and the rest). A frame's obligations come from KIND."""
    bad: list[str] = []
    found = frame_rows(spec)
    seen: dict[str, int] = {}
    for name, c, line in found:
        seen[name] = seen.get(name, 0) + 1
        if name not in KIND:
            bad.append(f"frame {name} is not in the tool's inventory (KIND_TABLE)")
            continue
        if len(c) != 6:
            bad.append(f"frame {name}: {len(c)} cells, six expected")
            continue
        kind, params = KIND[name]
        producer, shows, cls, keys, board = c[1], c[2], c[3], c[4], c[5]
        if kind in T2_KINDS and not re.search(r"\bT2\b", cls):
            bad.append(f"Class cell disagrees with the tool's KIND: {name} is T2")
        if kind not in T2_KINDS and kind != "planned" and re.search(r"\bT2\b", cls):
            bad.append(f"Class cell disagrees with the tool's KIND: {name} is not T2")
        for want, kinds_ in (
            ("validity look", VALIDITY_KINDS),
            ("busy", BUSY_KINDS),
            ("outcome", {"outcome"}),
            ("T4", {"refusal", "delete-racing"}),
            ("absence (planned)", {"planned"}),
        ):
            if kind in kinds_ and want not in cls:
                bad.append(f"Class cell disagrees with the tool's KIND: {name} is {want}")
        nums = re.findall(r"\d\d", board)
        if board != NOT_DRAWN and (
            not re.fullmatch(r"\d\d(?:, \d\d)*(?: \(inset\))?", board)
            or any(not 1 <= int(n) <= BOARD_CAP for n in nums)
        ):
            bad.append(f"frame {name} without a board or the not-drawn cell ({board!r})")
        for key in re.findall(r"`([^`]+)`", keys):
            if not re.fullmatch(COPY_KEY_RE, key):
                bad.append(f"copy key outside the registered namespaces in {name}: {key}")
            elif deck is not None and key not in deck:
                bad.append(f"copy key not in the deck (§8) in {name}: {key}")
        if kind in DIRTY_KINDS and not re.search(r"`[^`\n]*\*[^`\n]*`", line):
            bad.append(f"dirty frame {name} without its `*`")
        if name.startswith("SCR-025/") and re.search(ENV_RE, line):
            bad.append(f"environment control on SCR-025 in {name} (BQ-8 RULED: none)")
        if kind == "planned":
            if re.search(CONTROL_RE, line):
                bad.append(f"planned inset {name} drawn as a control")
            if re.search(DIM_RE, line):
                bad.append(f"planned inset {name} marked T2 or dimmed")
            if f"Waits for its contract ({params['gap']})." not in line:
                bad.append(f"planned inset {name} without its contract caption")
        if kind in T2_KINDS:
            if not re.search(r"\block\b", line):
                bad.append(f"T2 frame {name} draws no lock")
            for key in params.get("keys", "").split(","):
                if key and f"`{key}`" not in line:
                    bad.append(f"T2 frame {name} lacks its reason key {key}")
            order = legs(line)
            if order is None:
                bad.append(f"T2 frame {name} lacks its legs (view-as first)")
            elif order[0] != "rbac.view_as":
                bad.append(f"view-as leg not first in {name}: {' → '.join(order)}")
            if re.search(T2_DIM_RE, line):
                bad.append(f"T2 frame {name} conveyed by dimming")
            if "§5" not in line:
                bad.append(f"T2 frame {name} does not cite §5 (T2 stated once)")
        if kind == "t2-state" and (
            facts["last_workspace_message"] not in line or "aria-describedby" not in line
        ):
            bad.append(f"disabled delete lacks its reason for a screen reader in {name}")
        if kind in ("t2-viewer", "t2-view-as") and "one notice" not in line:
            bad.append(f"read-only frame {name} without its one notice")
        if kind in VALIDITY_KINDS:
            if "validity-reason" not in line:
                bad.append(f"validity frame {name} without its validity-reason")
            if re.search(r"\block\b", line):
                bad.append(f"validity frame {name} with a lock")
        bad += dialog_gates(name, kind, shows, line)
        bad += content_gates(name, kind, params, producer, line, facts)
    for name, n in seen.items():
        if n > 1:
            bad.append(f"frame {name} appears in {n} rows (one row per frame)")
    for name in KIND:
        if name not in seen:
            bad.append(f"frame {name} missing from the state tables of §2-§4")
    return bad


def dialog_gates(name: str, kind: str, shows: str, line: str) -> list[str]:
    """M7-M10, M17 and AC 1: footer order, initial focus, Esc, the exits, the weights, the role."""
    bad: list[str] = []
    items = footer_items(shows)
    if kind in DIALOG_KINDS:
        if not items or items[0][0] not in SAFE:
            bad.append(f"safe action not first in the footer of {name}")
        if not clause(shows, "initial focus:").startswith(SAFE):
            bad.append(f"initial focus not on the safe action in {name}")
    if kind in EXIT_KINDS:
        esc = re.search(r"Esc → ([A-Z][a-z]+(?: [a-z]+)?)", shows)
        if not esc or esc.group(1) != "Cancel":
            bad.append(f"Esc not mapped to Cancel in {name}")
        exits = [e.strip().split(" ")[0] for e in clause(shows, "exits T1:").split(" · ")]
        exits_full = [e.strip() for e in clause(shows, "exits T1:").split(" · ")]
        if not (set(exits_full) & set(SAFE)) or "Esc" not in exits:
            bad.append(f"frame {name} without its T1 exits (Cancel and Esc)")
    gated = re.search(EXIT_RE, clause(shows, "T2:")) is not None
    gated = gated or any(
        re.fullmatch(EXIT_RE, label) and re.search(r"\bT2\b|disabled", note)
        for label, note in items
    )
    if gated:
        bad.append(f"exit drawn gated in {name}")
    if kind in SCR029_DIALOG_KINDS:
        if "CMP-043" not in line or 'role="alertdialog"' not in line or "CMP-044" in line:
            bad.append(f"SCR-029 dialog {name} not a CMP-043 alertdialog")
        if any(
            label in DESTRUCTIVE and re.search(r"`(?:primary|danger)`", note)
            for label, note in items
        ):
            bad.append(f"destructive or overwriting choice carries primary weight in {name}")
    if kind in UNVERBED_KINDS and any(label in UNVERBED for label, _ in items):
        bad.append(f"unverbed button in {name}")
    return bad


def content_gates(
    name: str, kind: str, params: dict[str, str], producer: str, line: str, facts: dict[str, Any]
) -> list[str]:
    """The kind's own content: summaries, consequence lines, the typed field, the refusals."""
    bad: list[str] = []
    delay, name_max = facts["confirm_delay_ms"], facts["name_max"]
    if kind in BUSY_KINDS and ("`loading`" not in line or "`aria-busy`" not in line):
        bad.append(f"busy frame {name} not in the busy form")
    if kind == "outcome" and (SAVED_SENTENCE not in line or "polite" not in line):
        bad.append(f"terminal state {name} without its polite announcement")
    if kind == "invalid":
        message, link = (x.format(max=name_max) for x in INVALID_RULES[params["rule"]])
        need = [f'"{message}"', f'"{link}"', "error summary"]
        if params["rule"] == "long":
            need.append(f'"{name_max + 1}/{name_max}"')
        if any(n not in line for n in need):
            bad.append(f"invalid-name frame {name} lacks its rule message or summary link")
    if kind == "delete-confirm":
        if TYPED_LABEL.format(workspace=FIXTURE["workspace"]) not in line:
            bad.append(f"delete frame {name} lacks the typed field")
        if IRREVERSIBLE not in line:
            bad.append(f"delete frame {name} lacks its irreversibility line")
        if "CMP-044 `typed`" not in line:
            bad.append(f"delete frame {name} is not a CMP-044 typed confirm")
    if kind in ("delete-confirm", "overwrite-confirm") and f"`confirmDelayMs` {delay}" not in line:
        bad.append(f"confirm {name} lacks its confirm delay")
    if kind == "delete-racing" and (
        "`409 last_workspace`" not in producer or facts["last_workspace_message"] not in line
    ):
        bad.append(f"racing delete {name} lacks its refusal")
    if kind in CONFLICT_412_KINDS and "412" not in producer:
        bad.append(f"conflict frame {name} without its `412` producer")
    if "diff" in params:
        sentences = render_summary(FIXTURE[params["diff"]])
        overflow = sentences[-1] if sentences[-1].startswith("and ") else ""
        if any(f'"{s}"' not in line for s in sentences if s != overflow):
            bad.append(f"difference summary differs from the rendered fixture in {name}")
        if overflow and f'"{overflow}"' not in line:
            bad.append(f"overflow line missing in {name}")
    if kind == "settings-conflict" and any(
        f'"{FIXTURE[k]}"' not in line for k in ("renamed", "renamed_elsewhere")
    ):
        bad.append(f"settings conflict {name} lacks its two values of the name")
    if kind in ("conflict", "settings-conflict"):
        full = frame_time(params, facts)
        heads = ['"Yours (not saved)"', f'"Saved now ({full})"']
        if params.get("table") == "yes":
            heads.append(table_text(facts))
        if any(h not in line for h in heads):
            bad.append(f"conflict frame {name} lacks the side-by-side summary")
        lines = LAYOUT_LINES if kind == "conflict" else SETTINGS_LINES
        what = "conflict verb" if kind == "conflict" else "settings conflict verb"
        for verb, text in consequence(lines, full).items():
            if f'"{text}"' not in line:
                bad.append(f"{what} {verb} lacks its consequence line in {name}")
    if kind == "overwrite-confirm":
        hhmm = str(facts["conflict_time"])[:5]
        if OVERWRITE_TITLE.format(hhmm=hhmm) not in line or "can't be recovered" not in line:
            bad.append(f'overwrite confirm {name} lacks its time or "can\'t be recovered"')
        if "CMP-044 `standard`" not in line or "CMP-044 `typed`" in line:
            bad.append(f"overwrite confirm {name} is not a plain CMP-044 standard")
    if kind == "queued" and (
        QUEUE_RULE not in line or f"within {facts['conflict_ms']} ms" not in line
    ):
        bad.append(f"queued conflict {name} lacks the queue rule")
    if kind == "reflow" and "200 %" not in line:
        bad.append(f"reflow frame {name} lacks its zoom")
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
        if num != num2:
            bad.append(f"§0 board {num}: its name carries {num2}")
        slug = title.split(" ", 3)[-1]
        if len(c) < 4:
            bad.append(f"§0 board {num}: fewer than four cells after its name")
            continue
        draws, theme, export, status = c[0], c[1], c[2], c[3]
        light += slug.endswith("-light")
        if slug.endswith("-light") != (theme == "light"):
            bad.append(f"§0 board {num}: its slug and its theme disagree")
        if export != f"`docs/design/E15/img/E15-D08-{num}-{slug}.png`":
            bad.append(f"§0 board {num}: export path {export} does not match its name")
        if status != "pending":
            bad.append(f"§0 board {num}: status {status!r} (text-first: pending)")
        frames = set(re.findall(FRAME_NAME_RE, draws))
        for f in frames:
            if f not in KIND:
                bad.append(f"§0 board {num} names an unknown frame {f}")
            named.setdefault(f, set()).add(num)
        if not frames and num not in TABLE_BOARDS:
            bad.append(f"§0 board {num} draws no frame")
    if len(boards) > BOARD_CAP or light * 3 > len(boards):
        bad.append(f"§0 board cap broken: {len(boards)} boards, {light} light twins")
    nd_line = first(r"\*\*Not drawn — the text is binding; drawn on request\*\*([^\n]*)", s0)
    not_drawn = set(re.findall(FRAME_NAME_RE, nd_line))
    for name, c, _ in frame_rows(spec):
        if len(c) != 6 or name not in KIND:
            continue
        mine = set(re.findall(r"\d\d", c[5])) if c[5] != NOT_DRAWN else set()
        if mine != named.get(name, set()):
            bad.append(
                f"frame {name}: its row says boards {sorted(mine)}, "
                f"§0 says {sorted(named.get(name, set()))}"
            )
        if (c[5] == NOT_DRAWN) != (name in not_drawn):
            bad.append(f"frame {name}: its not-drawn cell and §0's not-drawn line disagree")
    for f in not_drawn - set(KIND):
        bad.append(f"§0's not-drawn line names an unknown frame {f}")
    numbers = {"boards": len(boards), "light_twins": light}
    return bad, numbers


def entry_gates(spec: str) -> tuple[list[str], dict[str, int]]:
    """§3.2: every route maps to a frame or to "no dialog", with its Esc (AC 2, BQ-11 RULED)."""
    bad: list[str] = []
    s3 = section(spec, 3, 4)
    found = {m.group(1): cells("|" + m.group(2)) for m in re.finditer(ENTRY_RE, s3, MULTI)}
    present = {name for name, _, _ in frame_rows(spec)}
    for eid, ticket, words, target in rows(ENTRY_TABLE):
        c = found.get(eid)
        if c is None or len(c) < 4:
            bad.append(f"entry-point matrix lacks {eid} ({words})")
            continue
        route, outcome, esc = c[0], c[1], c[2]
        if words not in route or (ticket == "yes") != ("(ticket)" in route):
            bad.append(f"entry point {eid}: its route cell is not {words!r}")
        if target == "none":
            ok = outcome.startswith("no dialog —") and re.search(r"`[^`\n]*\*[^`\n]*`", outcome)
            if not ok:
                bad.append(f"entry point unmapped: {eid} ({words})")
            if esc != "— (no dialog)":
                bad.append(f"entry point {eid}: Esc cell {esc!r} on a route with no dialog")
        else:
            if f"`{target}`" not in outcome and target in present:
                bad.append(f"entry point unmapped: {eid} ({words})")
            if esc != "Esc → Cancel":
                bad.append(f"Esc not mapped to Cancel on entry point {eid}")
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
    bad += [f"header: merge sha missing: {s[:9]}" for s in MERGE_SHAS if s not in head]
    if BASE not in head:
        bad.append("header: the base sha is missing")
    if PENPOT_PAGE not in head:
        bad.append("header: the Penpot page name is missing")
    bad += [f"header: the status line lost {w!r}" for w in STATUS_WORDS if w not in head]
    devs = [ln for ln in head.split("\n") if ln.startswith("- **Deviation — ")]
    for dev, words in DEVIATIONS.items():
        if not any(words in ln for ln in devs):
            bad.append(f"deviation missing: {dev} ({words})")
    trace = block(spec, "## Acceptance-criteria trace", "\n## ")
    ids = re.findall(r"^\| ((?:AC|DL|DoD|N)-\d+) +\|", trace, MULTI)
    bad += [f"AC trace lacks {i}" for i in AC_IDS if i not in ids]
    bad += [f"AC trace repeats {i}" for i in set(ids) if ids.count(i) > 1]
    bqs = block(spec, "## The questions", "\n## ")
    bq = {m.group(1): m.group(0) for m in re.finditer(r"^\| (BQ-\d+) +\|.*$", bqs, MULTI)}
    for i in range(1, 17):
        row = bq.get(f"BQ-{i}")
        if row is None:
            bad.append(f"BQ-{i} missing from the questions table")
        elif "RULED" not in cells(row)[-1]:
            bad.append(f"BQ-{i} not RULED")
    for qid, terms in BQ_TERMS.items():
        if qid in bq and any(t not in bq[qid] for t in terms):
            bad.append(f"{qid} row lost its ruled outcome ({' / '.join(terms)})")
    numbers = {"bq_rows": len(bq), "ac_rows": len(ids)}
    return bad, numbers


def cite_gates(spec: str, t: dict[str, str]) -> tuple[list[str], dict[str, int]]:
    """Each CITED_TABLE needle once in its file, at its line (`14`: or as many lines lower as there
    are pointer lines above it); every `KEY:line` cite in the spec has a CITED_TABLE row."""
    bad: list[str] = []
    lines = {k: v.split("\n") for k, v in t.items()}
    pinned: set[tuple[str, int]] = set()
    CITE_WARN.clear()
    for doc, line_s, want in rows(CITED_TABLE, 2):
        line, doc_lines = int(line_s), lines[doc]
        pinned.add((doc, line))
        shift = sum(POINTER in ln for ln in doc_lines[: line - 1]) if doc == "14" else 0
        total = t[doc].count(want)
        at = [i + 1 for i, ln in enumerate(doc_lines) if want in ln]
        if total == 0:
            bad.append(f"cited text gone: `{doc}:{line}` {want[:40]!r}")
        elif total > 1:
            bad.append(f"cited text ambiguous: `{doc}:{line}` {want[:40]!r} ({total} matches)")
        elif at[0] not in (line, line + shift):
            CITE_WARN.append(f"`{doc}:{line}` now at :{at[0]} ({want[:40]!r})")
    used = [(m.group(1), int(m.group(2))) for m in re.finditer(CITE_RE, spec)]
    for doc, line in sorted(set(used) - pinned):
        bad.append(f"cite not pinned in the tool's CITED_TABLE: `{doc}:{line}`")
    return bad, {"cites_pinned": len(pinned), "cites_used": len(set(used))}


def text_gates(spec: str, t: dict[str, str], facts: dict[str, Any]) -> list[str]:
    """Reasons, upstream copy, the `14` pointer lines, placeholders, the repository-wide rules."""
    bad: list[str] = []
    for key, string, doc in rows(REASONS_TABLE):
        if f'"{string}"' not in t[doc]:
            bad.append(f"reason string drifted from {doc}: {key} {string!r}")
        if len(string) > facts["reason_max"] or not string.endswith("."):
            bad.append(f"reason {key}: {len(string)} characters or no full stop")
        if key.startswith("rbac.") and re.search(r"\d", string):
            bad.append(f"reason {key} names a number")
    if facts["permission_sentence"] != "Your role can't save workspaces.":
        bad.append(f"E09-D09's template and verb give {facts['permission_sentence']!r}")
    rows_by_name = {name: line for name, _, line in frame_rows(spec)}
    for string, doc, frames in rows(UPSTREAM_TABLE):
        if string not in t[doc]:
            bad.append(f"upstream string gone from {doc}: {string!r}")
        for frame in [f.strip() for f in frames.split(",")]:
            if frame in rows_by_name and string not in rows_by_name[frame]:
                bad.append(f"frame {frame} lacks the upstream string {string!r}")
    plan14 = t["14"].split("\n")
    at = [i for i, ln in enumerate(plan14) if POINTER in ln]
    want = [i + 1 for i, ln in enumerate(plan14) if any(ln.endswith(a) for a in POINTER_AFTER)]
    if at != want:
        bad.append(f"`14` pointer lines at {[i + 1 for i in at]}, expected right after {want}")
    for n, text in re.findall(PLACEHOLDER_RE, spec):
        bad.append(f"placeholder §{n} still in the spec: {text[:70]}")
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    pointer_lines = "\n".join(plan14[i] for i in at)
    for label, txt in (
        ("spec", spec),
        ("tool", TOOL.read_text(encoding="utf-8")),
        ("14", pointer_lines),
    ):
        bad += [f"{label}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        if label != "tool" and re.search(CLOSING, txt, re.IGNORECASE):
            bad.append(f"{label}: a closing keyword (text-first: Refs + Partial only)")
        if label == "tool":
            continue
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if not re.search(rf"^\*\*{re.escape(r)}\b", constitution, MULTI):
                bad.append(f"{label}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{label}: no catalogue heading for {c}")
    return bad


def reconcile_gates() -> list[str]:
    """The inventory against E15-D02 §6 / §5.10 and `14`: each upstream line is a pinned cite (its
    needle checked by `cite_gates`) and every frame it maps to is in KIND."""
    bad: list[str] = []
    pinned = {(doc, int(line)) for doc, line, _ in rows(CITED_TABLE, 2)}
    for doc, line, frames in rows(RECONCILE_TABLE, 2):
        if (doc, int(line)) not in pinned:
            bad.append(f"reconciliation row `{doc}:{line}` has no CITED_TABLE needle")
        for frame in [f.strip() for f in frames.split(",")]:
            if frame not in KIND:
                bad.append(f"reconciliation row `{doc}:{line}` names an unknown frame {frame}")
    return bad


def live(spec: str, n: int) -> str:
    """Section n's text once it is written; empty while it is missing or still a placeholder."""
    text = section(spec, n, n + 1)
    return "" if not text or f"**Placeholder (§{n}):**" in text else text


def checklist_items(t: dict[str, str]) -> list[str]:
    """The SCR-025 and SCR-029 sign-off items, verbatim from `14`."""
    out: list[str] = []
    for line in t["14"].split("\n"):
        if any(line.endswith(a) for a in POINTER_AFTER):
            out += [i.strip() for i in line.split("[ ]")[1:]]
    return out


def section_gates(spec: str, ctx: Ctx) -> list[str]:
    """§5, §7, §8, §11 and §12 once written: the one T2 paragraph and its not-T2 list; the measured
    table equal to the tool's matrix; the deck's templates and consequence lines, no jargon; a
    G-row for every planned inset; every sign-off item."""
    bad: list[str] = []
    s5 = live(spec, 5)
    if s5 and ("**T2" not in s5 or "**Not T2" not in s5):
        bad.append("§5 lacks the one T2 paragraph or its not-T2 list")
    s7 = live(spec, 7)
    if s7:
        found = {(m[2], m[3], m[4]): m for m in re.finditer(CONTRAST_ROW_RE, s7, MULTI)}
        for r in ctx.measured["matrix"]:
            m = found.get((r["fg"], r["bg"], r["role"]))
            if m is None:
                bad.append(f"§7 table lacks {r['fg']} on {r['bg']} ({r['role']})")
                continue
            cells_ = dict(zip(THEMES, (m[5], m[6], m[7]), strict=True))
            if any(abs(float(cells_[th]) - float(r[th])) > CELL_TOLERANCE for th in THEMES):
                bad.append(f"§7 measured cell differs: {r['fg']} on {r['bg']} ({r['role']})")
            if m[8].strip() != r["verdict"] or m[9] != r["pairs"]:
                bad.append(f"§7 verdict or pairs.mjs column differs: {r['fg']} on {r['bg']}")
        greys = {g[1]: g for g in re.finditer(GREY_ROW_RE, s7, MULTI)}
        for tok, vals in ctx.measured["grey"].items():
            g = greys.get(tok)
            if g is None or [int(g[2]), int(g[3]), int(g[4])] != [vals[th] for th in THEMES]:
                bad.append(f"§7 greyscale row differs or is missing: {tok}")
        cvds = {(c[1], c[2]): c for c in re.finditer(CVD_ROW_RE, s7, MULTI)}
        for r in ctx.measured["cvd"]:
            c = cvds.get((r["a"], r["b"]))
            if c is None or [float(c[i]) for i in range(3, 7)] != r["dE76"] or c[7] != r["verdict"]:
                bad.append(f"§7 colour-vision row differs or is missing: {r['a']} vs {r['b']}")
    s8 = live(spec, 8)
    if s8:
        strings = re.findall(r'^\| `[^`]+` +\|[^|\n]*\| ("[^|\n]*")', s8, MULTI)
        for pat in BANNED_COPY:
            bad += [
                f"§8 jargon in user copy: {pat!r} in {x[:40]!r}"
                for x in strings
                if re.search(pat, x)
            ]
        for key, forms in DIFF_TEMPLATES.items():
            if any(form not in s8 for form in forms):
                bad.append(f"§8 lacks the template e15.diff.{key} in both forms")
        for lines in (LAYOUT_LINES, SETTINGS_LINES):
            for verb, text in lines.items():
                if text.format(hhmm="{hh:mm}", layout="{layout}") not in s8:
                    bad.append(f"§8 lacks the consequence line of {verb}")
    s11 = live(spec, 11)
    if s11:
        for gap in sorted({p["gap"] for kind, p in KIND.values() if kind == "planned"}):
            if not re.search(rf"^\| {gap} +\|", s11, MULTI):
                bad.append(f"§11 lacks the G-row {gap} that its planned inset names")
    s12 = live(spec, 12)
    if s12:
        bad += [
            f"§12 lacks the sign-off item {i!r}" for i in checklist_items(ctx.t) if i not in s12
        ]
    return bad


def deck_ids(spec: str) -> set[str] | None:
    """§8's keyed ids, or None while §8 is a placeholder."""
    s8 = section(spec, 8, 9)
    if not s8 or "**Placeholder (§8):**" in s8:
        return None
    return set(re.findall(r"^\| `([^`]+)` +\|", s8, MULTI))


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
    """Everything the gates read besides the spec: the texts, the themes, the facts, the matrix."""

    def __init__(self) -> None:
        self.t = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
        self.themes = {th: theme_tokens(th) for th in THEMES}
        self.facts = contract_facts(self.t, self.themes)
        self.measured = measure(self.themes)
        self.missing = [tok for tok in BINDINGS if resolve(self.themes["dark"], tok) == "MISSING"]


def numbers_of(spec: str, ctx: Ctx, extra: dict[str, Any]) -> dict[str, Any]:
    f, m = ctx.facts, ctx.measured
    numbers: dict[str, Any] = dict(extra)
    numbers.update(count_frames(spec))
    numbers["mutations"] = len(mutations())
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
    for k in (
        "pairs_rows",
        "pairs_fail",
        "pairs_registered",
        "pairs_proposed",
        "aaa_rows",
        "aaa_met",
    ):
        numbers[k] = m[k]
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
    flat = flatten(numbers)
    bad = []
    for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
        have = flat.get(key)
        same = str(have).lower() == val.lower()
        try:
            same = same or float(str(have)) == float(val)
        except ValueError:
            pass
        if have is None or not same:
            bad.append(f"marker audit:{key}={val} vs tool {have}")
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
    bad += [f"token MISSING: {tok}" for tok in ctx.missing]
    bad += [
        f"contrast FAIL: {r['element']}"
        for r in ctx.measured["matrix"]
        if r["verdict"] in ("FAIL", "MISSING")
    ]
    for fact in ("version_conflict_412", "settings_default_environment", "unstored_absent"):
        if not ctx.facts[fact]:
            bad.append(f"contract fact changed: {fact}")
    if ctx.facts["ws_layout_topic"]:
        bad.append("`23` now carries a workspace or layout topic: revisit the WS G-row (BQ-13)")
    if ctx.facts["last_workspace_message"] != "You need at least one workspace.":
        bad.append("`22` deleteWorkspace's last_workspace sentence changed")
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


def sec_fn(n: int, fn: Callable[[str], str]) -> Callable[[str], str]:
    """Apply `fn` to section n's text only (unchanged when the section is gone)."""

    def apply(s: str) -> str:
        text = section(s, n, n + 1)
        return s.replace(text, fn(text), 1) if text else s

    return apply


def mutations() -> list[tuple[str, Callable[[str], str], str]]:
    """(name, the in-memory change, the text the one new FAIL must carry): M1-M17 of the brief's A2,
    then the gates the spec adds. Each must apply, and each must add exactly one new FAIL."""
    keep_mine = (
        '"Keep mine replaces the version saved at 14:05. That version can\'t be recovered." '
    )
    conflict_footer = (
        "footer: Cancel (`secondary`) · Save mine as new layout… (`secondary`) · "
        "Load theirs (`secondary`) · Keep mine (`secondary`)"
    )
    moved_footer = (
        "footer: Save mine as new layout… (`secondary`) · Load theirs (`secondary`) · "
        "Keep mine (`secondary`) · Cancel (`secondary`)"
    )
    return [
        (
            "M1-dirty-star",
            frame_re("SCR-029/unsaved", r"`([^`\n]*?) ?\*([^`\n]*)`", r"`\1\2`"),
            "without its `*`",
        ),
        ("M2-t2-lock", frame_re("SCR-025/delete-last", r"\block\b", "glyph"), "draws no lock"),
        (
            "M3-reason-key",
            frame_re("SCR-025/viewer-read-only", r"`notice\.panel_read_only`", "the notice key"),
            "lacks its reason key notice.panel_read_only",
        ),
        (
            "M4-view-as-order",
            frame_sub(
                "SCR-025/delete-last",
                "legs `rbac.view_as` → `rbac.permission`",
                "legs `rbac.permission` → `rbac.view_as`",
            ),
            "view-as leg not first",
        ),
        (
            "M5-planned-control",
            frame_sub("SCR-025/planned-defaults", "nothing operable", "a CMP-009 select"),
            "drawn as a control",
        ),
        (
            "M6-planned-dim",
            frame_sub(
                "SCR-025/planned-theme",
                "full-strength `color.text.secondary`",
                "`color.text.secondary` at `opacity.disabled`",
            ),
            "marked T2 or dimmed",
        ),
        (
            "M7-cancel-first",
            frame_sub("SCR-029/conflict", conflict_footer, moved_footer),
            "safe action not first",
        ),
        (
            "M8-focus-safe",
            frame_sub("SCR-029/unsaved", "initial focus: Cancel", "initial focus: Save layout"),
            "initial focus not on the safe action",
        ),
        (
            "M9-esc-cancel",
            frame_sub("SCR-029/unsaved", "Esc → Cancel", "Esc → Discard changes"),
            "Esc not mapped to Cancel",
        ),
        (
            "M10-exit-gated",
            frame_sub("SCR-029/viewer-unsaved", "T2: Save layout (", "T2: Save layout, Cancel ("),
            "exit drawn gated",
        ),
        (
            "M11-typed-field",
            frame_sub(
                "SCR-025/delete-confirm",
                'the typed field labelled "Type Scalping to confirm" (',
                "the typed field (",
            ),
            "lacks the typed field",
        ),
        (
            "M12-consequence",
            frame_sub("SCR-029/conflict", keep_mine, ""),
            "Keep mine lacks its consequence line",
        ),
        (
            "M13-overwrite-time",
            frame_sub("SCR-029/keep-mine-confirm", " That version can't be recovered.", ""),
            "lacks its time or",
        ),
        (
            "M14-412",
            frame_sub("SCR-029/conflict", "answered `412 version_conflict`", "answered a refusal"),
            "without its `412` producer",
        ),
        (
            "M15-number",
            lambda s: s.replace("<!-- audit:boards=10 -->", "<!-- audit:boards=11 -->", 1),
            "marker audit:boards=11",
        ),
        (
            "M16-env-control",
            frame_sub(
                "SCR-025/default",
                "Share (Export…)",
                "Share (Export…, a Default environment for new panels select)",
            ),
            "environment control on SCR-025",
        ),
        (
            "M17-cmp-044",
            frame_sub(
                "SCR-029/conflict", 'CMP-043 `role="alertdialog"`', 'CMP-044 `role="alertdialog"`'
            ),
            "not a CMP-043 alertdialog",
        ),
        (
            "X1-primary-discard",
            frame_sub(
                "SCR-029/unsaved", "Discard changes (`secondary`)", "Discard changes (`primary`)"
            ),
            "carries primary weight",
        ),
        (
            "X2-unverbed",
            frame_sub("SCR-029/unsaved", "Save layout (`primary`)", "OK (`primary`)"),
            "unverbed button",
        ),
        (
            "X3-diff-fixture",
            frame_sub("SCR-029/unsaved", '"3 panels added."', '"Three panels added."'),
            "differs from the rendered fixture",
        ),
        (
            "X4-overflow",
            frame_sub("SCR-029/unsaved-overflow", ' "and 2 more differences."', ""),
            "overflow line missing",
        ),
        (
            "X5-validity-lock",
            frame_sub(
                "SCR-025/default",
                "Save in the validity look",
                "Save in the validity look behind a lock",
            ),
            "validity frame SCR-025/default with a lock",
        ),
        (
            "X6-reason-sr",
            frame_sub("SCR-025/delete-last", " through `aria-describedby`", ""),
            "lacks its reason for a screen reader",
        ),
        (
            "X7-dim-t2",
            frame_sub(
                "SCR-025/delete-last",
                "in `color.text.tertiary`",
                "in `color.text.tertiary` at `opacity.disabled`",
            ),
            "conveyed by dimming",
        ),
        (
            "X8-invalid-message",
            frame_sub("SCR-025/invalid-long", '"Use at most 40 characters."', '"Too long."'),
            "lacks its rule message or summary link",
        ),
        (
            "X9-announce",
            frame_sub("SCR-025/saved", '"Saved workspace settings."', '"Done."'),
            "without its polite announcement",
        ),
        (
            "X10-queue-rule",
            frame_sub("SCR-029/conflict-queued", QUEUE_RULE, "the dialog waits"),
            "lacks the queue rule",
        ),
        (
            "X11-entry-unmapped",
            row_fn(
                r"^\| E6 +\|.*$",
                lambda ln: re.sub(r"\| no dialog — [^|]*\|", "| — |", ln, count=1),
            ),
            "entry point unmapped: E6",
        ),
        (
            "X12-cite-unpinned",
            lambda s: s.replace("**Key.** `NN`", "**Key.** (`D02:999`) `NN`", 1),
            "cite not pinned in the tool's CITED_TABLE: `D02:999`",
        ),
        (
            "X13-bq-outcome",
            row_fn(
                r"^\| BQ-8 +\|.*$",
                lambda ln: ln.replace("no environment control at all", "an environment control", 1),
            ),
            "BQ-8 row lost its ruled outcome",
        ),
        (
            "X14-deviation",
            row_fn(
                r"^- \*\*Deviation — the five fieldsets\.\*\*.*$",
                lambda ln: ln.replace("five fieldsets", "fieldsets"),
            ),
            "deviation missing: the five fieldsets",
        ),
        ("X15-ac-trace", row_fn(r"^\| AC-5 ", lambda ln: "| AC-50 "), "AC trace lacks AC-5"),
        (
            "X16-board-reconcile",
            frame_re("SCR-025/failed", r"\| 02( +)\|$", r"| 03\1|"),
            "SCR-025/failed: its row says boards",
        ),
        (
            "X17-class-agrees",
            frame_re("SCR-029/save-as-t2", r"\| T2 \(state, §5\)( +)\|", r"| T1 (state)\1|"),
            "Class cell disagrees with the tool's KIND: SCR-029/save-as-t2 is T2",
        ),
        (
            "X18-upstream",
            frame_sub(
                "SCR-029/unsaved", "Applying Order-flow replaces them.", "Order-flow replaces them."
            ),
            "lacks the upstream string",
        ),
        (
            "X19-overwrite-plain",
            frame_sub("SCR-029/keep-mine-confirm", "CMP-044 `standard`", "CMP-044 `typed`"),
            "is not a plain CMP-044 standard",
        ),
        (
            "X20-not-drawn-line",
            lambda s: s.replace(
                ", `SCR-029/leg-lost`, `SCR-029/reflow-200`.", ", `SCR-029/reflow-200`.", 1
            ),
            "SCR-029/leg-lost: its not-drawn cell and §0's not-drawn line disagree",
        ),
        (
            "X21-settings-names",
            frame_sub("SCR-025/settings-conflict", 'saved now "Scalping EU"', "saved now theirs"),
            "lacks its two values of the name",
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
            "copy key not in the deck (§8) in SCR-029/conflict-queued: e15.conflict.queued_status",
        ),
        (
            "X23-not-t2-list",
            sec_fn(5, lambda t: t.replace("**Not T2", "**Also not T2", 1)),
            "§5 lacks the one T2 paragraph or its not-T2 list",
        ),
        (
            "X24-g-row",
            sec_fn(11, lambda t: re.sub(r"^\| D08-G2 ", "| D08-G9 ", t, count=1, flags=MULTI)),
            "§11 lacks the G-row D08-G2",
        ),
        (
            "X25-sign-off-item",
            sec_fn(
                12,
                lambda t: t.replace("no default destructive button", "no destructive default", 1),
            ),
            "§12 lacks the sign-off item 'no default destructive button'",
        ),
        (
            "X26-contrast-cell",
            sec_fn(
                7,
                lambda t: re.sub(
                    r"(^\| 1 +\| `color\.text\.primary` on `color\.surface\.overlay`"
                    r" +\| hc-text +\| )13\.27",
                    r"\g<1>13.37",
                    t,
                    count=1,
                    flags=MULTI,
                ),
            ),
            "§7 measured cell differs: color.text.primary on color.surface.overlay (hc-text)",
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
            "§7 greyscale row differs or is missing: color.status.danger.default",
        ),
        (
            "X29-cvd-cell",
            sec_fn(
                7, lambda t: t.replace("14.7 · 12.5 · 14.0 · 5.5", "14.7 · 12.5 · 14.0 · 5.6", 1)
            ),
            "§7 colour-vision row differs or is missing: color.status.danger.strong vs",
        ),
        (
            "X27-template",
            sec_fn(8, lambda t: t.replace('"and {n} more differences."', '"and {n} more."', 1)),
            "§8 lacks the template e15.diff.overflow in both forms",
        ),
    ]


def frame_family(spec: str, ctx: Ctx) -> list[str]:
    """The per-frame gates alone (frames, boards, the entry-point matrix)."""
    return (
        frame_gates(spec, ctx.facts, deck_ids(spec)) + board_gates(spec)[0] + entry_gates(spec)[0]
    )


def self_test(spec: str, ctx: Ctx) -> list[str]:
    bad: list[str] = []
    digest = hashlib.sha256(SPEC.read_bytes()).hexdigest()
    base, _ = gates(spec, ctx)
    family = frame_family(spec, ctx)
    if family:
        bad.append(
            f"self-test: the unmutated spec fails {len(family)} per-frame gates: {family[:2]}"
        )
    names = [name for name, _, _ in mutations()]
    if len(set(names)) != len(names):
        bad.append("self-test: two mutations share a name")
    for name, fn, expect in mutations():
        mutated = fn(spec)
        if mutated == spec:
            bad.append(f"self-test {name}: the mutation did not apply")
            continue
        got, _ = gates(mutated, ctx)
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
        "OK — the header, the deviations, the AC trace and the ruled questions; §0's boards "
        "and their reconciliation; every per-frame gate (dirty marker, T2 anatomy with view-as "
        "first, planned insets never controls, never T2, never dimmed, Cancel first and "
        "focused, Esc → Cancel, the exits never gated, CMP-043 alertdialog, the weights, the "
        "typed field, the consequence lines, the 412, the summaries); the entry-point matrix; "
        "reasons and upstream strings; the cites; the `14` pointer lines; §5's T2 paragraph, §7's "
        "matrix, greyscale and CVD rows, §8's deck, §11's G-rows and §12's items; no private path, "
        "no closing keyword, no dangling id; no placeholder"
    )
    out.append("\n## 5. Gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    return out


def main(argv: list[str]) -> int:
    ctx = Ctx()
    spec = SPEC.read_text(encoding="utf-8")
    bad, numbers = gates(spec, ctx)
    out = report(ctx, numbers, bad)
    if "--check" in argv:
        mism = [b for b in bad if b.startswith("marker")]
        out.append("markers: " + ("clean" if not mism else "MISMATCH"))
    st_bad: list[str] = []
    if "--self-test" in argv:
        st_bad = self_test(spec, ctx)
        out.append(
            "self-test: "
            + (
                f"ok — {len(mutations())} mutations, each caught once by one new FAIL; "
                "the per-frame gates are clean on the unmutated spec; the spec on disk is unchanged"
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
            "cite_warnings": CITE_WARN,
            "palette": palette,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    if argv == ["--self-test"]:
        return 1 if st_bad else 0
    return 1 if bad or st_bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
