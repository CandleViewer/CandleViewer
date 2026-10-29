"""e42kit: the shared sheet kit for the E42-D03 (#886, PR #4138) Penpot boards. Python 3.12+, standard library only.

Every builder returns cvsheet v1 node dicts (schema: ../cvsheet-v1.js header), so each board generator draws the CMP-087
admin shell (TopBar, NavRail, band, rule, strip, PageHeader, route content, footer marker, RightRail, StatusBar) at
1280 x 800 and 2560 x 1440, its content parts, the annotation column and the board frame the same way. Sources: the spec
SPEC (§0 boards, §1 worked example and clocks, §2 D1-D5 layout and tint, §4 CMP-087, §12 ladder, §13 keys and the T2
rule, §14 copy deck, §15 tokens; line numbers read at SPEC_MD5) and the binding build-notes.md beside this file.
T2 (§13 L602, "(T2, §13)"): t2_button (2a, or shared=True under a notice), t2_reason, t2_notice (one notice, many
pointers), t2_select, t2_check, t2_field, t2_icon_button (2b, the CMP-016 echo), t2_sentence (the sentence form),
t2_cluster (CMP-211), menu() (a (label, reason) item: the reason its second line; focus=), radio(t2_reason=) and
row_menu_items(kind) (§7's row menu by status); never T2 (§13 L602): validity_button (a rung confirm waiting on its
inputs, §12 L542-543), busy_button / busy_icon_button (CMP-001 loading, U-7's trigger) and table_header(sort_pending=)
(CMP-049 sortPending: a pressed SCR-121 sort header busy while the remaining pages load, an availability state, §7
L304-305; sort_cleared= after a failed read). table_header(t2_reason=) stays for old calls only, flagged: the merged
spec has no T2 header.

Use from a generator (python3 -I keeps the kit's folder off sys.path):
    import sys; sys.path.insert(0, "<this folder>")
    import e42kit as k
    frames = [k.shell(px, route=k.label("users"), right=k.badge(760), h1=k.label("users"),
                      primary=k.button(k.label("invite_user"), "primary"), content=[...]) for px in k.SIZES]
    ann = k.annotations(1, "01 CMP-087 · SH-1 unlocked (a)", {"source": "spec §4 L182 · SH-1", "state": "..."})
    secs = k.sections_for_board(frames, ann)
    b = k.board(1, "CMP-087", "unlocked", "both", "dark", frames=frames, ann=ann)
    k.write_sheet(k.KIT_DIR / "01-shell-unlocked.json", b, secs, k.export_path(1))
Copy: copy(key, **fills) returns a §14 string verbatim and records the key; label(key) returns an anatomy string the
spec gives outside §14 (with its line) and records it under copy_gaps; SAMPLE / USERS are §1's worked example. Kit
functions record copy keys, tokens, fallbacks, live checks, copy gaps, deviations and sources in LOG: annotations()
prints the copy keys and tokens it has seen (so build every frame first) and write_sheet() merges LOG into the sheet's
notes, then clears it. CLI: python3 -I e42kit.py selftest   (writes 00-selftest.json: SH-1 at both sizes, validated)
"""
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = SHEETS_DIR / "tools" / "token-sync.json"  # the token sync (the boards read the E42-D02-era copy)
SPEC = KIT_DIR / "spec" / "E42-D03@7884a33bd.md"  # frozen copy; absent, pin_bytes() reads it with git show (R-1/R-2: lines stay at 7884a33bd)
SPEC_MD5 = "3f909f5f71e333b6c112f595fefaae8c"  # HEAD 7884a33bd, the board cap (was 2e87d809, 58660d32f); no line moved
SPEC_MD5_PRE_GATE = "92d95c06fcef71501ca0f9e68a72185d"  # 782eb0e4d + #960 Q11: re-pinned by repin/linemap.json
D01 = KIT_DIR.parents[2] / "research" / "e42-admin.md"  # dlg.disable = D01:668-672
D09 = KIT_DIR.parents[2] / "E09" / "E09-D09.md"  # rbac.view_as = D09:262 (§14 L624)
SECTION_BUDGET = 20000  # bytes per section, measured as the validator does (json.dumps defaults)
SECTION_HARD = 24000  # the validator warns above this; write_sheet() refuses it
REV = "r1"  # the script revision in every board footer (§0 L50)

# --- Tokens: exact Penpot names from token-sync.json; colour and typography from the semantic sets only (§15).
APP, CANVAS, RAISED = "color.surface.app", "color.surface.canvas", "color.surface.raised"
OVERLAY, SUNKEN = "color.surface.overlay", "color.surface.sunken"
HOVER, SELECTED = "color.surface.hover", "color.surface.selected"
BORDER_SUBTLE, BORDER_DEFAULT = "color.border.subtle", "color.border.default"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_LINK, TEXT_ON_ACTION = "color.text.link", "color.text.on-action"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
OK_SUBTLE, OK_STRONG = "color.status.success.subtle", "color.status.success.strong"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
DANGER_SUBTLE, DANGER_STRONG = "color.status.danger.subtle", "color.status.danger.strong"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
NEUTRAL_SUBTLE = "color.neutral.subtle"
ENV_COLOR = {"LIVE": "color.env.live", "DEMO": "color.env.demo"}
FOCUS_RING = "color.focus.ring"
STALE_IND = "color.data-confidence.stale.indicator"  # the stale clock (Appendix A CMP-178 Tokens, L895)
ADMIN_TINT = RAISED  # DS-1: color.surface.admin-tint -> {color.surface.raised} (§2 D2 L116, §15 L635-636)
ADMIN_RULE = TEXT_3  # DS-2: color.border.admin -> {color.text.tertiary} (§2 D2 L116, §15 L636-637)
FIELD_EDGE = TEXT_3  # DS-3: color.border.input -> {color.text.tertiary} (§15 L637, F1 L666)
SCRIM = SUNKEN  # no scrim colour token: #000000 in dark (see FALLBACKS["SCRIM"])
CHROME = APP  # TopBar, NavRail, RightRail, StatusBar: no source names a chrome surface (DEVIATIONS["chrome"])
CAPTION, BODY, BODY_STRONG = "type.ui.caption", "type.ui.body", "type.ui.body-strong"
LABEL, HEADING_SM, HEADING_MD = "type.ui.label", "type.ui.heading-sm", "type.ui.heading-md"
NUM_SM, NUM_BASE = "type.num.sm", "type.num.base"  # type.num.base for every count and clock (D02:120, App. A L881)
INSET_XS, INSET_SM, INSET_MD = "space.inset.xs", "space.inset.sm", "space.inset.md"
INSET_LG, INSET_XL = "space.inset.lg", "space.inset.xl"
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
STEP = STACK_MD  # §2 D1's "space.3 gaps" / D02:120's "space.3 stack step", bound as the semantic alias (12 px)
PANEL_PAD, DIALOG_PAD = "space.panel.padding", "space.dialog.padding"
BUTTON_PADX, FIELD_GAP = "space.button.paddingX", "space.field.gap"
CONTROL_COMF = "size.control.comfortable"  # 32 px, a Tier-1 primitive the spec names (§4 L177; validator WARN)
ROW_COMF = "space.row.height.comfortable"  # 32 px rows, semantic alias of size.row.comfortable
ICON = "size.icon"  # 16 px
ICON_SM = "size.icon.sm"  # 12 px, a Tier-1 primitive (validator WARN): the 2b lock badge only (FALLBACKS["T2-BADGE"])
R_CONTROL, R_CARD, R_DIALOG, R_BADGE = "radius.control", "radius.card", "radius.dialog", "radius.badge"
E_CARD, E_POPOVER, E_DIALOG = "elevation.card", "elevation.popover", "elevation.dialog"
OPACITY_SCRIM = "opacity.scrim"  # 0.6, Tier-1 primitive (validator WARN): the flat 60 % scrim (§1 L97)
HAIRLINE, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, PANEL_PAD: 12, DIALOG_PAD: 24, BUTTON_PADX: 12, FIELD_GAP: 8, ICON: 16, CONTROL_COMF: 32,
      ROW_COMF: 32, ICON_SM: 12}
TONES = {  # tone -> (fill, glyph kind, glyph colour); text on every fill is color.text.primary (§15 L648, L657, L660)
    "neutral": (NEUTRAL_SUBTLE, "slashed-circle", TEXT_2), "success": (OK_SUBTLE, "check", OK_STRONG),
    "info": (INFO_SUBTLE, "info", INFO_STRONG), "warning": (WARN_SUBTLE, "triangle", WARN_STRONG),
    "danger": (DANGER_SUBTLE, "octagon", DANGER_STRONG),
}


# --- Geometry (§2 D1 L115; §1 L98; §4 L174-175). Raw px only in w, h, x, y.
class Geo(NamedTuple):
    """One frame size: frame w x h, NavRail, main column and RightRail widths, the 944/2048 inner width, chrome
    heights and the three SCR-120 tile widths (space.3 gaps)."""

    w: int
    h: int
    nav: int
    main: int
    right: int
    inner: int
    top: int
    status: int
    tiles: tuple[int, int, int]


SIZES: dict[int, Geo] = {
    1280: Geo(1280, 800, 64, 976, 240, 944, 48, 48, (307, 306, 307)),  # NavRail collapsed; "about 307 px" (§6 L256)
    2560: Geo(2560, 1440, 240, 2080, 240, 2048, 48, 48, (675, 674, 675)),  # NavRail expanded; "675 px" (§6 L256)
}
for _g in SIZES.values():
    assert _g.nav + _g.main + _g.right == _g.w and _g.inner == _g.main - 2 * 16
    assert sum(_g.tiles) + 2 * PX[STEP] == _g.inner
BAND_H, RULE_H, PILL_H, CONTROL_H, ROW_H = 56, 4, 24, 32, 32  # band = inset.lg + 24 px pill + inset.lg
ITEM_H, ENV_H, CHIP_H = 32, 16, 24  # strip items are links at the comfortable 32 px target (§13 L599)
ANN_W, ANN_TEXT_W = 400, 368  # the annotation column (build notes); values wrap at 368 px
PITCH_X, PITCH_Y = 4600, 1800  # page grid (build notes)
ROOT_PAD = 16  # space.inset.lg (root padding and gaps)
DIALOG_W = {"default": 480, "large": 640}  # kit choice: no source gives CMP-043 widths (DEVIATIONS["dialog-w"])
DRAWER_W = 400  # kit choice: no source gives the CMP-046 width

# --- The notes collector (write_sheet() merges it into the sheet's notes, then clears it).
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "live_checks", "deviations", "fallbacks", "tokens")


class _Log:
    """Notes recorded while nodes are built, deduplicated in first-seen order."""

    def __init__(self) -> None:
        """Start with no notes."""
        self.notes: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}

    def add(self, kind: str, line: str) -> str:
        """Record one line under kind and return it."""
        if line not in self.notes[kind]:
            self.notes[kind].append(line)
        return line

    def reset(self) -> None:
        """Forget everything recorded so far."""
        self.notes = {k: [] for k in NOTE_KINDS}


LOG = _Log()


def collected() -> dict[str, list[str]]:
    """A copy of everything recorded since the last write_sheet() or reset_notes()."""
    return {k: list(v) for k, v in LOG.notes.items()}


def reset_notes() -> None:
    """Clear the collector (write_sheet() does this after writing)."""
    LOG.reset()


FALLBACKS = {  # "fallback: <token> pending <CR>" lines, printed under Tokens by annotations()
    "DS-1": "fallback: color.surface.admin-tint pending DS-1: the band binds color.surface.raised (§2 D2, §15 L635)",
    "DS-2": "fallback: color.border.admin pending DS-2: the 4 px rule binds color.text.tertiary (§2 D2, §15 L636)",
    "DS-3": "fallback: color.border.input pending DS-3: field boundaries bind color.text.tertiary (§15 L637, F1 L666)",
    "SCRIM": ("fallback: no scrim colour token: the flat 60 % scrim (§1 L97, D06:24-25) binds color.surface.sunken at "
              "opacity.scrim (#000000 at 60 % in dark; light resolves sunken to a light grey, so a light export of a "
              "dialog board needs the coordinator's [THEME-WINDOW] check)"),
    "STEP": "token: §2 D1's space.3 gaps bind the semantic alias space.stack.md (12 px)",
    "CONTROL": ("token: size.control.comfortable (32 px, §4 L177) is the Tier-1 primitive the spec names (validator "
                "WARN)"),
    "T2-BADGE": ("token: the 2b lock badge (T2, §13 L602 (4): 'in 2b it is the badge on the icon') is the registry "
                 "glyph 'locked' at size.icon.sm (12 px, a Tier-1 primitive; validator WARN) on a color.surface.raised "
                 "disc at the icon's lower right (kit choice: no source sizes the badge)"),
    "SPINNER": ("fallback: CMP-014 Spinner inside a busy control (CMP-001 loading, 15:53; U-7's CMP-002 trigger, §7 "
                "L340) is drawn as the registry glyph 'refresh' in the label's colour (cvsheet v1 cannot recolour an "
                "instance; board 45's stand-in)"),
}
DS5 = {  # DS-5 icon names (§15 L637-639) -> registry glyph today; None = drawn as a composition
    "eye": "show", "lock": "locked", "check": "check", "triangle": "warning", "octagon": "danger", "clock": "pending",
    "slashed-circle": "cancelled", "ring": None, "admin": None, "info": "info",
}
SRC = {
    "boards": "spec §0 L43-83 (boards, names, footer, build order)",
    "example": "spec §1 L100-109 (worked example, clocks)",
    "layout": "spec §2 D1 L115 (layout at both sizes)",
    "tint": "spec §2 D2-D5 L116-119 (neutral tint, countdown text, one tone at expiry, time limits)",
    "shell": "spec §4 L163-205 (CMP-087 anatomy, SH-1..SH-8, focus, audit)",
    "overview": "spec §6 L245-291 (SCR-120 tiles)",
    "users": "spec §7 L293-354 (SCR-121 columns, chips, capacity line)",
    "sort": ("spec §7 L304-305 (a sort reads every page first: the pressed header busy, users.sorting polite once; a "
             "failed read keeps the rows with users.error [Retry]; an availability state, never T2, §13 L602)"),
    "viewas": "spec §10 L458-507 (SCR-124 banner)",
    "ladder": "spec §12 L531-583 (dialog anatomy and rungs)",
    "keys": "spec §13 L585-602 (keyboard, focus, live regions, text resize; the T2 rule closes it at L602)",
    "t2": "spec §13 L602 (T2 — disabled with a visible reason: never-T2 list, renderings (3), carriers (4), hi-fi (5))",
    "validity": "spec §12 L542-543, L566-568 (a rung confirm waiting on its inputs: the validity form, never T2)",
    "copy": "spec §14 L604-624 (copy deck)",
    "tokens": "spec §15 L626-680 (tokens, contrast, colour vision)",
    "components": "spec §16 L682-692, Appendix A L872-910 (component contracts)",
}
DEVIATIONS = {
    "names": ("Board names carry Penpot's normalised ' / ' form (E42-D03 / 31 SCR-121 / populated · …) so cvsheet's "
              "find-or-create root matches on every section call; §0 L47-48 writes 'SCR-121/populated'."),
    "compose": ("Buttons, chips, badges, banners, fields, tiles, tables, menus and dialogs are compositions from "
                "tokens: admin controls are 32 px (size.control.comfortable, §4 L177) while the library CMP-001 binds "
                "size.control.height (24 px in the file's compact density), and cvsheet v1 cannot set an "
                "instance's glyph, fill or border."),
    "chrome": ("TopBar, NavRail, RightRail and StatusBar content other than the Admin entry, the env badges and the "
               "owner's name is drawn as neutral placeholders (E10-D02 owns it; §1 L98 gives only the sizes); the "
               "chrome binds color.surface.app with color.border.subtle dividers (no source names a chrome surface)."),
    "clock": ("A live countdown (band badge, grace line, view-as banner) sets its clock in type.num.base as its own "
              "text node (D02:120; Appendix A L881 CMP-087 Tokens); the node's note carries the full §14 string."),
    "link": "Links are colour + position only on the boards: cvsheet v1 texts have no underline.",
    "dialog-w": ("CMP-043 'size' Default and Large are drawn 480 and 640 px wide (kit choice): §5 L212, §9 L420 and "
                 "§12 L537 name the sizes, and no source gives their widths."),
    "focus": ("A focus ring is a 2 px color.focus.ring inner stroke on a wrapper with space.inset.xs (4 px) padding, "
              "so it sits 2 px off the control (CMP-039) inside the wrapper's bounds; its radius is the next step "
              "(radius.card around radius.control); the wrapper adds 4 px on each side to the layout."),
    "t2": ("T2 controls are compositions (T2, §13 L602): the lock (CMP-019 'lock', DS-5 pending: the registry glyph "
           "'locked') leads the full label, both color.text.tertiary; a filled control's fill goes to "
           "color.surface.raised with a 1 px color.border.default hairline (a ghost control has no fill to lose); the "
           "2a reason is type.ui.caption color.text.secondary; never color.text.disabled or opacity.disabled. A select "
           "(CMP-009) or text field (CMP-007) takes the same look on its trigger or well (kit reading of (5), as "
           "boards 04, 49 and 57 drew it); the lock leads its visible label, or its value when it has none."),
    "t2-notice": ("The shared T2 notice (§10 L475 panel notices; UD-16 / UD-20's PageHeader notice, §8 L402, L406) is "
                  "a CMP-028 Callout composition in the info tone: §10 L475 names a CMP-028 with no live role and no "
                  "tone (kit choice: info, as D24's view-as banner and D22's tightening notice)."),
    "validity": ("A rung confirm waiting on its inputs takes the validity form (§12 L542-543, L566-568; never T2, §13 "
                 "L602): aria-disabled, focusable, no lock, no CMP-079, the danger fill dropped to "
                 "color.surface.raised with a color.border.default hairline and the label color.text.tertiary (the "
                 "spec's DJ); its visible hint (dlg.choose_first / dlg.ack_first / dlg.token) sits under the button in "
                 "type.ui.caption color.text.tertiary, the dialogs' hint class (§15 L661; placement: kit choice)."),
}


def _src(key: str) -> None:
    """Record the spec section SRC[key] as a source of the sheet being built."""
    LOG.add("sources", SRC[key])


def _fallback(key: str) -> None:
    """Record the fallback or token line FALLBACKS[key] (printed under Tokens)."""
    LOG.add("fallbacks", FALLBACKS[key])
    _src("tokens")


def _deviate(key: str, line: str | None = None) -> None:
    """Record the kit deviation DEVIATIONS[key] (or a one-off line) in the sheet's notes."""
    LOG.add("deviations", line or DEVIATIONS[key])


# --- Node builders (mirror cvsheet-v1.js KEYS: keys cvsheet v1 rejects raise here, as cvsheet would throw).
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
    "inst": {"t", "name", "set", "props", "texts", "hide", "show", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf",
             "note"},
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


def node(t: str, name: str, **kw: Any) -> Node:
    """A cvsheet node of type t (None values dropped); raises on keys cvsheet v1 rejects or a "/" in the name, and
    records every token it binds under LOG "tokens"."""
    if not name or "/" in name:
        raise ValueError(f"{t} node name {name!r}: empty or contains '/' (section paths split on '/')")
    n: Node = {"t": t, "name": name}
    n.update({k: v for k, v in kw.items() if v is not None})
    extra = set(n) - _KEYS[t]
    if extra:
        raise KeyError(f"{t} {name!r}: keys cvsheet v1 rejects: {sorted(extra)}")
    toks = [n.get(k) for k in ("typo", "color", "size")]
    toks += [v for k, v in (n.get("o") or {}).items() if k in _TOKEN_OPTS]
    for tk in toks:
        if isinstance(tk, str):
            LOG.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str, color: str, **kw: Any) -> Node:
    """A text node bound to a typography and a colour token; w= sets a fixed wrap width (auto height)."""
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=str(chars), typo=typo, color=color, **kw)


def icon(name: str, glyph: str, color: str, size: str = ICON, **kw: Any) -> Node:
    """A registry icon (icon/<glyph>, components.offline.json "icons") with its stroke bound to color."""
    if glyph not in ICONS:
        raise ValueError(f"icon {glyph!r} is not a registry glyph")
    return node("icon", name, icon=glyph, color=color, size=size, **kw)


def rect(name: str, w: float, h: float, fill: str | None = None, o: dict[str, str] | None = None, **kw: Any) -> Node:
    """A w x h rectangle, optionally filled with a colour token; o= adds other shape options (stroke, radius…)."""
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w, h=h, o=opts or None, **kw)


def ellipse(name: str, w: float, h: float, o: dict[str, str], **kw: Any) -> Node:
    """A w x h ellipse with shape options o (fill / stroke / strokeWidth)."""
    return node("ellipse", name, w=w, h=h, o=o, **kw)


def unique_names(kids: Iterable[Node]) -> list[Node]:
    """kids with repeated sibling names suffixed " · 2", " · 3" (cvsheet replaces a sibling by name, the validator
    rejects duplicates); the first keeps its name."""
    seen: dict[str, int] = {}
    out = []
    for k in kids:
        if not k:
            continue
        seen[k["name"]] = seen.get(k["name"], 0) + 1
        out.append(k if seen[k["name"]] == 1 else dict(k, name=f"{k['name']} · {seen[k['name']]}"))
    return out


def box(name: str, kids: Iterable[Node] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    """A board with cv.board options o and child nodes (w/h raw px; x/y/abs/hs/vs/alignSelf/note placement); repeated
    child names are made unique (unique_names)."""
    return node("board", name, o=dict(o) if o else None, kids=unique_names(kids) or None, **kw)


def hbox(name: str, kids: Iterable[Node] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    """A flex-row board, items centred unless o says otherwise (cv.board's default)."""
    return box(name, kids, {"dir": "row", **(o or {})}, **kw)


def vbox(name: str, kids: Iterable[Node] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    """A flex-column board, items at the start unless o says otherwise."""
    return box(name, kids, {"dir": "column", "align": "start", **(o or {})}, **kw)


def _inst_check(n: Node) -> str:
    """The live-check line for one inst node (set, variant props, text layers)."""
    props = json.dumps(n.get("props") or {}, ensure_ascii=False)
    return (f"inst {n['name']!r}: set {n['set']!r}, props {props}, text layers {sorted(n.get('texts') or {})}: verify "
            f"the set, the variant and the layer names live before rendering")


def inst(name: str, set_: str, props: dict[str, str] | None = None, texts: dict[str, str] | None = None,
         **kw: Any) -> Node:
    """A library instance; recorded as a live check (set, variant props and text layer names are verified live)."""
    n = node("inst", name, set=set_, props=props or None, texts=texts or None, **kw)
    LOG.add("live_checks", _inst_check(n))
    return n


ICONS = frozenset(  # the 47 registry glyphs (components.offline.json "icons")
    "arrow-down arrow-up arrow-up-down calendar cancelled check chevron-down chevron-left chevron-right chevron-up "
    "chevrons-up-down close copy crosshair danger delete disconnected download drag-handle edit error external-link "
    "filter help hide info locked maximize minimize minus more-horizontal more-vertical notifications pending pin plus "
    "redo refresh search settings show success undo upload warning zoom-in zoom-out".split())


def glyph(kind: str, color: str, name: str | None = None, size: str = ICON) -> Node:
    """A DS-5 glyph by its spec name (eye, lock, check, triangle, octagon, clock, slashed-circle, ring, admin, info):
    the registry glyph standing in for it, the ring as a 13 px ellipse outline, the admin mark as the text ◆; every
    stand-in is recorded as a fallback line."""
    if kind not in DS5:
        raise ValueError(f"glyph {kind!r}: one of {sorted(DS5)}")
    nm = name or kind
    if kind == "ring":
        LOG.add("fallbacks", "fallback: icon/ring (○) pending DS-5: drawn as a 13 px ellipse outline, border.thick")
        ring = ellipse("ring", 13, 13, {"stroke": color, "strokeWidth": THICK})
        return hbox(nm, [ring], {"justify": "center"}, w=PX[size], h=PX[size])
    if kind == "admin":
        LOG.add("fallbacks", "fallback: icon/admin (◆) pending DS-5: drawn as the text glyph ◆ of band.label (L608)")
        LOG.add("live_checks", "glyph ◆ (U+25C6): confirm Inter draws it; else Penpot substitutes a fallback font")
        return text(nm, "◆", BODY_STRONG, color)
    reg = DS5[kind]
    assert reg is not None
    if kind not in ("check", "info"):
        LOG.add("fallbacks", f"fallback: icon/{kind} pending DS-5: drawn with the registry glyph '{reg}'")
    return icon(nm, reg, color, size)


# --- Text metrics (estimates for widths, fit checks and board heights; Inter / JetBrains Mono).
_FONT = {CAPTION: (11, 1.2, 1.0, False), BODY: (13, 1.4, 1.0, False), BODY_STRONG: (13, 1.4, 1.04, False),
         LABEL: (12, 1.2, 1.03, False), HEADING_SM: (14, 1.2, 1.06, False), HEADING_MD: (16, 1.2, 1.06, False),
         "type.ui.heading-lg": (20, 1.2, 1.06, False), "type.ui.display": (24, 1.2, 1.09, False),
         NUM_SM: (11, 1.2, 1.0, True), NUM_BASE: (13, 1.2, 1.0, True), "type.num.xs": (10, 1.2, 1.0, True),
         "type.num.md": (14, 1.2, 1.0, True), "type.num.lg": (16, 1.2, 1.0, True), "type.num.xl": (20, 1.2, 1.0, True)}
_EM = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (.70, .66, .69, .72, .58, .56, .72, .74, .27, .51, .66, .54, .87, .74, .76,
                                              .63, .76, .64, .63, .62, .73, .70, .98, .67, .67, .63), strict=True))
_EM.update(zip("abcdefghijklmnopqrstuvwxyz", (.55, .59, .54, .59, .56, .34, .59, .57, .24, .25, .52, .24, .87, .57,
                                              .58, .59, .59, .37, .51, .35, .57, .52, .78, .52, .52, .51), strict=True))
_EM.update({" ": .26, ".": .27, ",": .27, ":": .27, ";": .27, "%": .83, "(": .33, ")": .33, "+": .60, "−": .60,
            "-": .41, "—": 1.0, "–": .60, "·": .27, "/": .38, "…": .80, "?": .50, "'": .23, '"': .40, "#": .65,
            "1": .40, "×": .60, "◆": .78, "→": .80, "@": .95, "≤": .60, "•": .45, "[": .30, "]": .30, "_": .50,
            "&": .70, "!": .27, "|": .24, "<": .60, ">": .60, "=": .60, "*": .45, "○": .78, "⋯": .80})


def text_w(chars: str, typo: str) -> float:
    """Estimated advance width in px of chars set in typo (approximate metrics; mono is 0.6 em per character)."""
    size, _lh, weight, mono = _FONT.get(typo, _FONT[BODY])
    if mono:
        return round(len(chars) * 0.6 * size, 1)
    return round(sum(_EM.get(ch, .58 if ch.isdigit() else .60) for ch in chars) * size * weight, 1)


def text_lines(chars: str, typo: str, width: float) -> int:
    """Lines chars wraps to at width (greedy word wrap on the estimated metrics)."""
    lines, cur = 1, ""
    for word in str(chars).split():
        trial = f"{cur} {word}" if cur else word
        if cur and text_w(trial, typo) > width:
            lines, cur = lines + 1, word
        else:
            cur = trial
    return lines


def text_h(typo: str, lines: int = 1) -> float:
    """Height in px of lines lines of typo (size x line height)."""
    size, lh, _w, _m = _FONT.get(typo, _FONT[BODY])
    return round(size * lh * lines, 1)


CLOCK_RE = re.compile(r"(\(?\d{1,2}:\d{2}(?::\d{2})?[.,;)]?)")  # m:ss, hh:mm, hh:mm:ss (+ attached punctuation)


def clock_text(name: str, chars: str, typo: str, color: str, num: str = NUM_BASE, **kw: Any) -> Node:
    """A copy string whose live clock (m:ss, hh:mm:ss) is set in type.num.base as its own text node in a flex row
    (gap space.inset.xs stands for the word space); the row's note carries the full string. No clock: one text."""
    parts = [p for p in CLOCK_RE.split(chars) if p.strip()]
    if len(parts) == 1:
        return text(name, chars, typo, color, **kw)
    _deviate("clock")
    kids = [text(f"seg-{i}", p.strip(), num if CLOCK_RE.fullmatch(p.strip()) else typo, color)
            for i, p in enumerate(parts, 1)]
    extra = kw.pop("note", None)
    kw.pop("w", None)  # a split string cannot wrap: the row hugs its segments
    return hbox(name, kids, {"gap": INSET_XS}, note=f'copy: "{chars}"' + (f"; {extra}" if extra else ""), **kw)


def mss(seconds: int) -> str:
    """A duration as m:ss ("12:40", "4:59", "0:59"; §2 D3 L117)."""
    s = max(int(seconds), 0)
    return f"{s // 60}:{s % 60:02d}"


def _px(v: Any) -> int:
    """The px of a spacing token name in PX (0 for None or an unknown name)."""
    return PX.get(v, 0) if isinstance(v, str) else 0


def est_width(n: Node) -> float:
    """Estimated rendered width of a node (fixed w wins; rows add children and gaps, columns take the widest)."""
    if n.get("w"):
        return float(n["w"])
    if n["t"] == "text":
        return text_w(n["chars"], n["typo"])
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padX")) + _px(o.get("padL")) + _px(o.get("padR"))
    if o.get("dir") == "row":
        gap = _px(o.get("colGap") or o.get("gap"))
        return pad + sum(est_width(k) for k in kids) + gap * max(len(kids) - 1, 0)
    return pad + max((est_width(k) for k in kids), default=0.0)


def est_height(n: Node) -> float:
    """Estimated rendered height of a node (fixed h wins; columns stack, rows take the tallest child or, with wrap,
    pack children into lines of the row's width)."""
    if n.get("h"):
        return float(n["h"])
    if n["t"] == "text":
        lines = text_lines(n["chars"], n["typo"], n["w"]) if n.get("w") else 1
        return text_h(n["typo"], lines)
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padY")) + _px(o.get("padT")) + _px(o.get("padB"))
    if o.get("dir") == "column":
        gap = _px(o.get("rowGap") or o.get("gap"))
        return pad + sum(est_height(k) for k in kids) + gap * max(len(kids) - 1, 0)
    if o.get("wrap") == "wrap" and n.get("w"):
        inner = n["w"] - 2 * _px(o.get("pad")) - 2 * _px(o.get("padX"))
        cgap, rgap = _px(o.get("colGap") or o.get("gap")), _px(o.get("rowGap") or o.get("gap"))
        rows: list[float] = []
        used = 0.0
        for k in kids:
            kw_, kh = est_width(k), est_height(k)
            if not rows or used + cgap + kw_ > inner:
                rows.append(kh)
                used = kw_
            else:
                rows[-1] = max(rows[-1], kh)
                used += cgap + kw_
        return pad + sum(rows) + rgap * max(len(rows) - 1, 0)
    return pad + max((est_height(k) for k in kids), default=0.0)


# --- The copy deck (§14 L608-624, verbatim; "{…}" = a fill). Tuples hold the parts §14 joins with "+" or "/".
# Kit-named sub-keys (the spec gives the string, not a key): *.one (singular forms), band.grace.class.*, tile.c26,
# dlg.step_up.*, dlg.enable_purge.cg28; rbac.view_as is D09's key, which §14 L624 adopts verbatim. COPY_SOURCE names
# the line of every string that is not in §14 L608-624; COPY_RENAMED keeps the gate-renamed keys as aliases.
COPY: dict[str, str | tuple[str, ...]] = {
    "band.label": "◆ Admin area · {route}",
    "band.unlocked": "Admin unlocked · {m:ss} left",
    "band.left": "{m:ss} left",
    "band.left_final": "{m:ss} left — unlock to keep editing",
    "band.locked": "Admin locked — unlock to save",
    "band.grace": "Still trusted for {class} · {m:ss}",
    "band.grace.class.users": "user changes",
    "band.grace.class.risk_caps": "risk limits",
    "strip.title": "Needs your action ({n})",
    "strip.none": "Nothing needs your action",
    "strip.locked": "Attention: Admin locked — Unlock now",
    "strip.unlock_again": "Attention: admin unlock ends in {m:ss} → Unlock again",
    "strip.key_expiry": "Key for {account} expires in {n} d → Rotate",
    "strip.key_expiry_n": "{n} keys expire within 30 days → Accounts and keys",
    "strip.key_expiry_n.one": "1 key expires within 30 days → Accounts and keys",
    "strip.tamper": "Tamper check FAILED → Open audit log",
    "strip.no_mfa": "{n} active users without two-factor → Users",
    "strip.no_mfa.one": "1 active user without two-factor → Users",
    "strip.tier": "Tier not recorded → Record tier",
    "strip.drift": "Attention: clock drift {s} s — order entry halted → Health",
    "strip.withdrawal": ("Attention: key …{last4} on {account} has withdrawal permission — remove it on Bybit → "
                         "Accounts and keys"),
    "strip.keys_invalid": "{n} keys rejected by Bybit → Accounts and keys",
    "strip.keys_invalid.one": "1 key rejected by Bybit → Accounts and keys",
    "strip.backup_old": "Last backup {n} days ago → Backups",
    "strip.break_glass": "Attention: break-glass recovery was used — review it → Incidents",
    "meta.asof": "All times UTC · as of {hh:mm:ss}",
    "footer.area_entered": "Entering this area was recorded — Area entered (admin.area_entered)",
    "announce.route": "Admin · {route} · {ENV}",
    "announce.admin_5min": "Admin unlock expires in 5 minutes.",
    "announce.admin_1min": "Admin unlock expires in 1 minute.",
    "announce.admin_locked": "Admin locked. Unlock to save.",
    "announce.tamper": "Tamper check failed at entry {n}. Treat this as a security incident.",
    "announce.withdrawal": "Withdrawal permission found on a key. Remove it on Bybit.",
    "gate.title": "Unlock admin",
    "gate.body": "Admin screens need a fresh confirmation. It stays unlocked until {hh:mm} UTC.",
    "gate.body_held": "Your change is kept. Unlock admin to save it.",
    "gate.code_label": "Authenticator code",
    "gate.code_hint": "6 digits",
    "gate.code_incomplete": "Enter the 6-digit code.",
    "gate.verifying": "Verifying code…",
    "gate.wrong": "Wrong password or code.",
    "gate.wrong_count": "Wrong password or code. {n} attempts left.",
    "gate.cancel_note": "Cancel discards nothing; you return to your workspace.",
    "gate.unavailable": "Can't check codes right now. Try again in {n} s.",
    "gate.not_checked": "Couldn't confirm right now — nothing was checked. Try again in {n} s.",
    "gate.password_required": "Enter your password.",
    "save.saved": "Saved.",
    "save.not_saved_locked": "Not saved — unlock admin to save.",
    "save.not_saved": "Not saved.",
    "save.checking": "Checking whether {user}'s change was saved…",
    "save.not_saved_expired": "Not saved — the confirmation expired. Save again to confirm.",
    "save.locked_hint": "Unlock admin to save.",  # Save's T1 description under SH-4 (§4 L185), never a T2 reason
    "tile.asof": "as of {hh:mm:ss}",
    "tile.stale": "stale since {hh:mm:ss}",
    "tile.unavailable": "Unavailable — {detail}",
    "tile.degraded": "Degraded — {detail}",
    "tile.not_built": "Unavailable — not built yet",
    "tile.error": "Error — timed out after 300 ms [Retry]",
    "tile.last_good": "last good {hh:mm:ss}",
    "tile.trading_unknown": ("Kill switch: unknown", "Live trading: —"),
    "tile.not_measured": "not measured",
    "tile.tamper_failed": "Tamper check FAILED at entry {n} — treat this as a security incident",
    "tile.maintenance_off": "Maintenance: off (flags read)",
    "tile.maintenance_on": "Maintenance: ON since {hh:mm} UTC → Maintenance",
    "tile.not_deployed": "{n} components not deployed — showing live frames only",
    "tile.withdrawal_ok": "Withdrawal permission: off on every key · checked {hh:mm} UTC",
    "tile.withdrawal_found": ("Withdrawal permission ON — key …{last4} on {account}; the system is read-only and "
                              "{account} can't trade"),
    "tile.c26": "Native stops on the exchange are unaffected",  # L614: never on an oms/trading/SL fault (#960 Q11)
    "banner.maintenance": ("Maintenance mode — new orders are blocked. Running algos were cancelled. Native stops on "
                           "the exchange are unaffected. Since {hh:mm} UTC."),
    "chip.active": "Active",
    "chip.invited": "Invited · expires {yyyy-mm-dd hh:mm} UTC",
    "chip.invite_expired": "Invite expired · {yyyy-mm-dd hh:mm} UTC",
    "chip.disabled": "Disabled",
    "chip.locked_out": "Locked out (sign-in) · until {hh:mm} UTC",
    "chip.trading_locked": "Trading locked (risk) · until {hh:mm} UTC",
    "chip.deletion_scheduled": "Disabled · deletion on {yyyy-mm-dd}",
    "cap.recorded": "{used} of {cap} sub-accounts used · {Tier} tier, recorded {date} [Change]",
    "cap.unrecorded": "{used} sub-accounts in use · Tier not recorded — record it to see your cap [Record tier]",
    "cap.tier_unavailable": "{used} sub-accounts in use · cap unavailable right now",
    "cap.used_unavailable": "{Tier} tier allows {cap} · sub-accounts in use: unavailable right now",
    "cap.down": "Sub-account capacity unavailable right now [Retry]",
    "cap.at_capacity": ("Bybit allows {cap} sub-accounts on your tier — you've used {used}.",
                        "To add another, complete Business KYC verification with Bybit (cap 20), then record the new "
                        "tier here — or share an existing sub-account and accept that its users are not isolated from "
                        "each other."),
    "cap.over": ("6 sub-accounts in use · Regular tier allows 5. Bybit lets accounts keep sub-accounts made before 14 "
                 "August 2026 — or the recorded tier may be wrong. [Change]"),
    "cap.valuetext": "{used} of {cap} sub-accounts used",
    "users.empty": "You're the only user. Invite a manager or viewer to delegate.",
    "users.no_match": "No users match these filters. [Clear filters]",
    "users.error": "Couldn't load users — {detail}. [Retry]",
    "users.sorting": "Loading all users to sort…",  # a pressed sort header's announcement, polite once (§7 L305)
    "users.disabling": "Disabling {user}…",
    "users.disabled": "{user} disabled. Signed out of {n} sessions.",
    "users.disabled.one": "{user} disabled. Signed out of 1 session.",
    "users.never": "Never signed in",
    "users.mfa_pending": "Set up when the invite is accepted",
    "users.deleted": "{user} disabled; deletion is scheduled 90 days after the first Delete.",
    "users.delete_none": "Not deleted — deletion isn't available right now; nothing changed.",
    "users.delete_partial": "{user} is disabled, but the deletion isn't scheduled yet. [Retry]",
    "users.delete_reenabled": "Not deleted — {user} was enabled while this ran; no deletion is scheduled.",
    "users.enable_refused": "Can't enable {user}: their account was anonymised.",
    "users.anonymised": "Anonymised on {yyyy-mm-dd}",  # the outcome line once CG-28 lands (U-9 L342; #960 Q13)
    "ud.demotion": ("{user} becomes a viewer: trading and rule arming stop on their next request; grants stay for a "
                    "later re-promote."),
    "ud.live_48h": "Live on {account} unlocks {date time} UTC (Bybit's 48 h key rule). Demo trading works meanwhile.",
    "ud.cap_max": "Can't exceed the account's {n} % daily cap.",
    "ud.summary": "{n} changes pending",
    "ud.summary.one": "1 change pending",
    "ud.conflict_412": "This user changed while you were editing. [Reload]",
    "ud.conflict_409": "Not saved: {user}'s grants changed meanwhile and nothing was written. Reload and try again.",
    "ud.conflict_inactive": "Not saved: {user} is {status} now, so their grants can't change.",
    "ud.load_error": "Couldn't load {user} — {detail}. [Retry]",
    "ud.last_owner": "You can't remove the last active owner.",
    "ud.saving": "Saving {n} changes…",
    "ud.no_sessions": "No active sessions",
    "ud.partial": "Partly saved: {n} of {m} changes.",
    "ud.req_saved": "Saved",
    "ud.req_refused": "Not saved — {reason}",
    "ud.req_unsent": "Not sent",
    "ud.req_not_flat": ("Not flat — {account} still has open positions or orders, so {user} keeps access; what closed "
                        "stays closed."),
    "ud.retry_rest": "Retry the rest",
    "ud.no_cap": "No cap",
    "ud.eff_symbols": "Symbols: {allowed} · blocked: {blocked}",
    "ud.eff_symbols.all": "every listed USDT perpetual",
    "ud.eff_symbols.none": "none",
    "ud.eff_symbols_none": "Symbols: none — the allow-list is empty and 'all symbols' is off",
    "ud.eff_disabled": "Profile disabled — it sizes no order",
    "ud.eff_not_trading": "Profile not trading-enabled — it sizes no order",
    "ud.eff_not_built": "Permissions, profile and live enablement unavailable — not built yet",
    "admin.locked": "Unlock admin to save.",  # renamed save.locked_hint by the gate (COPY_RENAMED): an alias
    "admin.self.role": "You can't remove your own owner role.",
    "admin.self.account": "You can't disable or delete your own account.",
    "admin.self.view_as": "You can't view as yourself.",
    "admin.owner_target": "You can't view as another owner.",
    "admin.invite_pending": "Available once the invite is accepted.",
    "admin.needs_count": "Needs the open-position count.",
    "admin.self.mfa": "You can't reset your own two-factor here.",
    "admin.user_disabled": "Enable this user first.",
    "admin.choose_first": "Choose an option first.",  # renamed dlg.choose_first (COPY_RENAMED): an alias
    "admin.ack_first": "Tick the acknowledgement first.",  # renamed dlg.ack_first (COPY_RENAMED): an alias
    "admin.shared_account": "Other users trade this account.",
    "dlg.disable": ("Disable alex", "Signs alex out everywhere within 5 seconds. · Removes alex's access to sub_001 "
                    "and sub_002. · Disarms alex's rules. · Keeps everything: journal, rules, settings and audit "
                    "history stay. · You can enable alex again at any time."),
    "dlg.delete": ("{user} can't sign in from now on. · Their journal, rules and audit history are kept; audit records "
                   "keep the name they were written with. · 90 days after the first Delete their e-mail and login name "
                   "are anonymised; from then this can't be undone. · Until then, Enable cancels the deletion.",
                   "Type the username to confirm."),  # "+ `token`" (L620): its second part is dlg.token
    "dlg.mfa_reset": ("Signs {user} out everywhere · next sign-in must enrol a new authenticator · nothing is "
                      "cancelled or flattened"),
    "dlg.enable": "{user} can sign in again. Their access stays removed: grant accounts again on their page.",
    "dlg.enable_purge": "If a deletion is scheduled, enabling cancels it.",
    "dlg.enable_purge.cg28": "Enabling cancels the deletion scheduled for {date}.",
    "dlg.promote": "erin becomes a manager: trading and rule arming start on the accounts you grant at trade level.",
    "dlg.signout": "Ends 1 session (device · IP · since) · the others stay",
    "dlg.signout_current": "This is the session you're using: signing it out signs you out.",
    "dlg.revoke": "The link stops working now.",
    "dlg.reissue": "{user} gets a new link valid for 72 hours; any open link stops working.",
    "dlg.tier": ("Record the sub-account tier", "This sets your cap: Regular allows 5 sub-accounts, Business KYC "
                 "allows 20. You can record it again later; it can't be cleared."),
    "dlg.choose_first": "Choose an option first.",  # a validity hint (§12 L542), never a T2 reason (L620)
    "dlg.ack_first": "Tick the acknowledgement first.",  # a validity hint (§12 L542), never a T2 reason (L620)
    "dlg.token": "Type the username to confirm.",  # D02:708, full stop added; rung 3's hint and token prompt (L543)
    "dlg.step_up.grace": "Still trusted for {class} · {m:ss}",
    "dlg.step_up.code": "You'll confirm with your password and a code.",
    "unbind.lead": ("{account} [{ENV}] has {n} open positions and {m} working orders. Choose what happens when you "
                    "remove {user}'s access:"),
    "unbind.a": ("The positions and orders stay as they are on Bybit. Their exchange stop-losses stay active. You "
                 "manage them from now on."),
    "unbind.b": ("Closes the {n} open positions at market and cancels the {m} working orders on {account}, then "
                 "removes {user}'s access."),
    "unbind.b_option_a": "If a position can't be closed, {user} keeps access; positions already closed stay closed.",
    "unbind.b_shared": "This closes every position and order on {account}; {other} also trades it.",
    "unbind.unknown": "We can't count the open positions and orders on {account} [{ENV}] right now.",
    "unbind.ack": "I accept that any open positions and orders stay open on Bybit under their exchange stop-losses.",
    "notice.tightening": "No positions will be closed. New entries are blocked; reduce-only actions remain available.",
    "inv.title": "Invite a user",
    "inv.role": "Invited as a viewer. You grant manager access and accounts after they sign in and enrol two-factor.",
    "inv.expiry": "Link expires 72 hours after it is created.",
    "inv.tailscale": "Reminder: the invitee also needs a Tailscale ACL grant.",
    "inv.none": "No pending invites",
    "inv.created": "Invite created for {user}",
    "inv.once": "Shown only once — treat it as a secret. Expires {date time} UTC.",
    "inv.close_warning": "When you close this, the link is gone. Copy it first.",
    "inv.copied": "Copied",
    "inv.creating": "Creating…",
    "inv.error": "Couldn't create the invite — {detail}. [Retry]",
    "inv.err_taken": "That username or e-mail is already in use.",
    "inv.err_pattern": "Use 3–32 letters, digits, dots, underscores or hyphens.",
    "inv.err_email": "Enter an address with an @ and a domain.",
    "inv.checking": "Checking whether the invite was created…",
    "inv.link_lost": "The invite was created but its link wasn't received. Re-issue to get a new link. [Re-issue]",
    "va.entry.title": "View as {user} (read-only)",
    "va.entry.body": ("For 30 minutes you see what {user} sees. Only protective actions work — stop-losses and an "
                      "account freeze — and they run as you."),
    "va.entry.body_ro": "For 30 minutes you see what {user} sees, read-only.",
    "va.entry.notice": "{user} is told now who is viewing and until when — not why.",
    "va.entry.reason": "Why are you viewing as {user}?",
    "va.err_reason": "Enter a reason (1–500 characters).",
    "va.starting": "Switching to {user}'s view…",
    "va.banner": "Viewing as {user} (read-only) — only protective actions work. Ends in {m:ss}.",
    "va.banner_ro": "Viewing as {user} (read-only). Ends in {m:ss}.",
    "va.notified": "{user} has been notified.",
    "va.announce": "Viewing as {user}, read-only. Only protective actions work. Exit view-as.",
    "va.announce_ro": "Viewing as {user}, read-only. Exit view-as.",
    "va.announce_5min": "View-as ends in 5 minutes.",
    "va.announce_1min": "View-as ends in 1 minute.",
    "va.announce_ended": "Viewing as {user} ended. Exit to return to your own view.",
    "va.ended": "Viewing as {user} ended. Exit to return to your own view.",
    "va.back": "Back to your own view",
    "va.err_active": "You're already viewing as {user}. Exit first.",
    "va.err_inactive": "{user} isn't active, so you can't view as them.",
    "va.notice": "System · {viewer} is viewing your account read-only from {hh:mm} to {hh:mm} UTC.",
    "va.exit_failed": "Couldn't end view-as — try again.",
    "inflight.view_as": "Not sent — read-only while viewing as {user}.",
    "rbac.view_as": "Read-only while viewing as {user}.",  # D09's key verbatim (§14 L624; D09:262): the panel notice
}
COPY_SOURCE = {  # strings §14 L608-624 references but does not spell out: (file, first line, last line)
    "strip.key_expiry_n.one": ("spec", 277, 277), "strip.no_mfa.one": ("spec", 277, 277),
    "strip.keys_invalid.one": ("spec", 277, 277), "cap.over": ("spec", 126, 126), "dlg.promote": ("spec", 396, 396),
    "dlg.disable": ("D01", 668, 670), "rbac.view_as": ("D09", 262, 262),
}
# Keys the gate fold (PR #4138 9644f23f0) renamed: the old key stays a COPY alias so old generators still run; copy()
# records it as called with a deviation naming the new key, and t2_reason() flags a renamed key used as a T2 reason.
COPY_RENAMED = {"admin.locked": "save.locked_hint", "admin.choose_first": "dlg.choose_first",
                "admin.ack_first": "dlg.ack_first"}
COPY_REMOVED = {  # keys §14 dropped at the merge (PR #4138, 58660d32f): copy() and the T2 helpers refuse them
    "admin.sort_needs_all": ("a sort is an availability state since the merge, never T2 (§7 L304-305; §13 L602): draw "
                             "table_header(sort_pending=) and announce users.sorting (§14 L617)"),
}
NEVER_T2 = {  # §14 keys that are never a T2 reason (§13 L602's Never-T2 list), with the spec's reason
    "save.locked_hint": "the expiry adds no T2 (§4 L185): save.locked_hint is Save's T1 description, never a T2 reason",
    "users.sorting": ("a pressed sort header waiting on the remaining pages is busy, an availability state (§7 L305): "
                      "users.sorting is its polite announcement, never a T2 reason"),
    "users.mfa_pending": ("an availability state (§7 L322, §8 L402): Reset two-factor is left out on an invited row and "
                          "users.mfa_pending states the fact in the Two-factor cell, never a T2 reason"),
    "dlg.choose_first": "a rung confirm waiting on its inputs takes the validity form (§12 L542): a hint, not T2",
    "dlg.ack_first": "a rung confirm waiting on its inputs takes the validity form (§12 L542): a hint, not T2",
    "dlg.token": "rung 3's confirm waits on the token in the validity form (§12 L543): a hint, not T2",
}
COPY_PIECES = {"users.disabled.one": ("{user} disabled. Signed out of ", "1 session.")}  # §14's "(one: '… 1 session.')"
_FILL_RE = re.compile(r"\{([^{}]+)\}")
_ALIAS = {"cls": "class"}  # "class" is a Python keyword


def _norm(name: str) -> str:
    """A fill name normalised for keyword use: "m:ss" -> "mss", "date time" -> "datetime", "ENV" -> "env"."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def fill(template: str, **fills: Any) -> str:
    """template with every {…} replaced: keywords are the normalised fill names (mss, hhmmss, hhmm, yyyymmddhhmm,
    yyyymmdd, datetime, env, tier, cls for {class}); a list value fills repeated slots in order ({hh:mm} … {hh:mm})."""
    vals = {_ALIAS.get(k, _norm(k)): (list(v) if isinstance(v, (list, tuple)) else v) for k, v in fills.items()}

    def one(m: re.Match[str]) -> str:
        """The value for one {…} slot."""
        key = _norm(m.group(1))
        if key not in vals:
            raise KeyError(f"fill {{{m.group(1)}}} missing (pass {key}=…) in {template!r}")
        v = vals[key]
        return str(v.pop(0) if isinstance(v, list) else v)

    return _FILL_RE.sub(one, template)


def copy(key: str, **fills: Any) -> str:
    """The §14 string for key with its fills (see fill()); a multi-part entry returns its parts joined by a space
    unless part= is given (0-based). Records the key under LOG "copy_keys"; a gate-renamed key (COPY_RENAMED) is
    recorded as called, so an old generator's own key checks still hold, with a deviation naming its new key."""
    part = fills.pop("part", None)
    if key in COPY_REMOVED:
        raise KeyError(f"copy key {key!r} left §14 at the merge: {COPY_REMOVED[key]}")
    if key not in COPY:
        raise KeyError(f"copy key {key!r} is not in §14 (COPY)")
    if key in COPY_RENAMED:
        _deviate("renamed", f"kit: copy key {key} is {COPY_RENAMED[key]} since the gate fold (§14 L613, L620; PR "
                            f"#4138 9644f23f0): the string is unchanged; re-key this sheet's call")
    LOG.add("copy_keys", key)
    _src("copy")
    raw = COPY[key]
    if isinstance(raw, tuple):
        raw = raw[part] if part is not None else " ".join(raw)
    return fill(raw, **fills)


def copy_parts(key: str, **fills: Any) -> tuple[str, ...]:
    """Every part of a multi-part §14 entry (tile.trading_unknown, cap.at_capacity, dlg.*), filled."""
    raw = COPY[key]
    n = len(raw) if isinstance(raw, tuple) else 1
    return tuple(copy(key, part=i, **fills) if n > 1 else copy(key, **fills) for i in range(n))


def list_items(s: str) -> list[str]:
    """A §14 list string split on its " · " separators outside parentheses ("Ends 1 session (device · IP · since) ·
    the others stay" -> 2 items)."""
    items, depth, cur = [], 0, ""
    i = 0
    while i < len(s):
        ch = s[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and s.startswith(" · ", i):
            items.append(cur)
            cur, i = "", i + 3
            continue
        cur += ch
        i += 1
    return items + [cur]


def split_actions(s: str) -> tuple[str, list[str], list[str]]:
    """A filled copy string split into (text, actions, env badges): "[Retry]" is a control, "[LIVE]" / "[DEMO]" an env
    badge (CMP-012), everything else the text with single spaces."""
    acts: list[str] = []
    envs: list[str] = []

    def take(m: re.Match[str]) -> str:
        """Collect one bracketed part and drop it from the text."""
        (envs if m.group(1) in ENV_COLOR else acts).append(m.group(1))
        return ""

    txt = re.sub(r"\s*\[([^\]]+)\]", take, s)
    return re.sub(r"\s+", " ", txt).strip(), acts, envs


# --- Anatomy strings the spec gives outside §14 (control labels, titles, headers): key -> (string, spec line).
# label() returns one and records it under copy_gaps, so every board lists the non-§14 strings it shows.
LABELS: dict[str, tuple[str, int]] = {
    "users": ("Users", 295), "overview": ("Overview", 251), "invite_user": ("+ Invite user", 295),
    "cancel": ("Cancel", 214), "unlock_admin": ("Unlock admin", 214), "create_invite": ("Create invite", 422),
    "start_viewing": ("Start viewing", 486), "remove_access": ("Remove access", 555),
    "exit_view_as": ("Exit view-as", 468), "load_more": ("Load more", 298),
    "run_tamper_check": ("Run tamper check", 276),
    "save": ("Save", 364), "copy": ("Copy", 423), "close": ("Close", 424), "revoke": ("Revoke", 424),
    "reissue": ("Re-issue", 424), "edit": ("Edit", 330), "reset_2fa": ("Reset two-factor", 330),
    "view_as": ("View as", 330), "disable": ("Disable", 330), "enable": ("Enable", 330), "delete": ("Delete", 330),
    "nav_admin": ("Admin", 189), "cmd_admin_area": ("Admin area", 189),
    "user_menu": ("Profile · Settings · Admin · Sign out", 189),
    "choice_a": ("Leave positions open — you take over", 135), "choice_b": ("Flatten first, then remove access", 553),
    "keeps_access": ("alex keeps access to sub_002.", 554), "unbind_title": ("Remove alex's access to sub_001", 551),
    "all_owner": ("all (owner)", 127), "n_accounts": ("2 accounts", 127), "this_device": ("This device", 401),
    "signout_session": ("Sign out this session", 401), "attention": ("Attention:", 287),
    "notice.key_selfcheck": ("Trading disabled: a stored API key failed its check.", 283),
    "notice.break_glass": ("Break-glass recovery was used on this server; the Owner must review it.", 284),
    "mfa.yes": ("yes", 301), "mfa.no": ("no", 301), "col.user": ("User", 300), "col.role": ("Role", 300),
    "col.accounts": ("Accounts", 301), "col.two_factor": ("Two-factor", 301), "col.last_sign_in": ("Last sign-in", 302),
    "col.status": ("Status", 303), "filter.role": ("Role", 296), "filter.status": ("Status", 296),
    "band.right_now": ("RIGHT NOW", 251), "band.people": ("PEOPLE AND ACCESS", 252),
    "band.evidence": ("EVIDENCE AND", 252),  # "EVIDENCE AND CONTROLS" wraps onto L253
    "tile.trading": ("Trading safety", 251), "tile.health": ("Health", 252),
    "tile.recorder": ("Recorder and storage", 252), "tile.users": ("Users", 252),
    "tile.accounts": ("Accounts and keys", 252), "tile.profiles": ("Profiles and limits", 252),
    "tile.audit": ("Audit", 253), "tile.security": ("Security and backups", 253), "tile.flags": ("Flags", 253),
    "role.owner": ("owner", 376), "role.manager": ("manager", 376), "role.viewer": ("viewer", 376),
    "env.live": ("LIVE", 103), "env.demo": ("DEMO", 301), "invite_link": ("https://…/invite/…", 436),
    "none_dash": ("—", 127), "retry_count": ("Retry count", 569),
    "cmp211.freeze": ("FREEZE…", 475), "cmp211.release": ("Release…", 475),  # CMP-211 under view-as (§10 L475)
    "cmp211.flatten_all": ("FLATTEN ALL…", 475), "cmp211.cancel_all": ("CANCEL ALL…", 475),
    "display_name": ("Display name", 452),  # SCR-123's field (§9 L452, §13 L595)
}
LABEL_FULL = {"band.evidence": "EVIDENCE AND CONTROLS"}  # strings the spec wraps across two lines
MARKER = "Recorded in the audit log · {label} ({code})"  # §1 L92 (D02 D5): "<label> (<code>)"


def label(key: str) -> str:
    """An anatomy string the spec gives outside §14 (LABELS), recorded under copy_gaps with its spec line."""
    if key not in LABELS:
        raise KeyError(f"label {key!r} is not in LABELS (add it with its spec line, never invent it)")
    s, ln = LABELS[key]
    s = LABEL_FULL.get(key, s)
    LOG.add("copy_gaps", f"'{s}': an anatomy string, not a §14 key (spec L{ln})")
    return s


# --- §1's worked example (L100-105): every frame's data.
SAMPLE: dict[str, Any] = {
    "owner": "basiltt", "env": "LIVE", "date": "2026-10-22", "asof": "14:02:11", "tier": "Regular",
    "tier_recorded": "2026-09-12", "subaccounts_used": 3, "users_total": 8, "users_active": 4, "users_without_mfa": 0,
}


class User(NamedTuple):
    """One §1 user: name, role, (account, level) grants, the §7 L335 status chip, its fills, §1's other facts."""

    username: str
    role: str
    grants: tuple[tuple[str, str | None], ...]
    chip: str
    fills: dict[str, str]
    facts: str


USERS: tuple[User, ...] = (
    User("basiltt", "owner", (), "active", {}, "the Owner"),
    User("alex", "manager", (("sub_001", "trade"), ("sub_002", "trade")), "active", {},
         "2 open positions and 3 working orders on sub_001"),
    User("bea", "manager", (("sub_003", None),), "trading_locked", {"hhmm": "00:00"},
         "trading locked by risk until 00:00 UTC"),
    User("carol", "viewer", (), "invited", {"yyyymmddhhmm": "2026-10-23 10:00"},
         "invited 2026-10-20 10:00 UTC, link expires 2026-10-23 10:00 UTC"),
    User("dave", "viewer", (), "invite_expired", {"yyyymmddhhmm": "2026-10-19 08:00"}, "invite expired"),
    User("dan", "viewer", (), "disabled", {}, "disabled"),
    User("erin", "viewer", (("sub_001", "read"),), "active", {}, "sub_001 read"),
    User("frank", "viewer", (), "locked_out", {"hhmm": "14:30"}, "locked out of sign-in until 14:30 UTC"),
)
USER = {u.username: u for u in USERS}
POSITIONS = {"sub_001": (2, 3)}  # (open positions, working orders), §1 L101


# --- The board registry (§0 L59-69 and the state tables of §4-§11): NN -> screen, state id, name state, slug,
# size, theme, dark twin. The name state is the slug without its screen prefix (§0's example "31 SCR-121/populated").
class Bd(NamedTuple):
    """One planned board."""

    screen: str
    state_id: str
    state: str
    slug: str
    size: str
    theme: str
    twin: int | None


SIZE_BOTH, SIZE_1280 = "1280×800+2560×1440", "1280×800"
_PLAN = """
01 CMP-087 SH-1 shell-unlocked|02 CMP-087 SH-2 shell-5min|03 CMP-087 SH-3 shell-1min|04 CMP-087 SH-4 shell-expired
05 CMP-087 SH-5 shell-grace|06 CMP-087 SH-6 shell-per-action|07 CMP-087 SH-7 shell-after-idle
08 CMP-087 SH-8 shell-entry|09 CMP-087 - tint-proof|10 CMP-087 SH-1 =01
11 SCR-149 RA-1 scr149-entry|12 SCR-149 RA-2 scr149-verifying|13 SCR-149 RA-3 scr149-wrong
14 SCR-149 RA-4 scr149-read-only|15 SCR-149 RA-5 scr149-expiry-mid-edit|16 SCR-149 RA-6 scr149-not-saved
17 SCR-149 RA-7 scr149-saved|18 SCR-149 RA-8 scr149-outcome-pending|19 SCR-149 RA-9 scr149-idle-lock|20 SCR-149 RA-1 =11
93 SCR-149 RA-10 scr149-unavailable|101 SCR-149 RA-11 scr149-not-checked|102 SCR-149 RA-12 scr149-challenge-ended
21 SCR-120 OV-1 scr120-loading|22 SCR-120 OV-2 scr120-healthy|23 SCR-120 OV-3 scr120-attention
24 SCR-120 OV-4 scr120-mixed|25 SCR-120 OV-5 scr120-tamper-failed|26 SCR-120 OV-6 scr120-trading-unknown
27 SCR-120 OV-7 scr120-maintenance|28 SCR-120 OV-8 scr120-record-tier|29 SCR-120 OV-2 =22
94 SCR-120 OV-9 scr120-withdrawal|103 SCR-120 OV-10 scr120-break-glass
30 SCR-121 U-1 scr121-loading|31 SCR-121 U-2 scr121-populated|32 SCR-121 U-3 scr121-empty
33 SCR-121 U-4 scr121-filtered-empty|34 SCR-121 U-5 scr121-at-capacity|35 SCR-121 U-6 scr121-error
36 SCR-121 U-7 scr121-in-flight|37 SCR-121 U-8 scr121-disable|38 SCR-121 U-9 scr121-enable
39 SCR-121 U-10 scr121-delete|40 SCR-121 U-11 scr121-reset-2fa|41 SCR-121 U-2 =31|95 SCR-121 U-12 scr121-delete-result
42 SCR-122 UD-1 scr122-loading|43 SCR-122 UD-2 scr122-default|44 SCR-122 UD-3 scr122-dirty
45 SCR-122 UD-4 scr122-saving|46 SCR-122 UD-5 scr122-saved|47 SCR-122 UD-6 scr122-conflict
48 SCR-122 UD-7 scr122-load-error|49 SCR-122 UD-8 scr122-self-guard|50 SCR-122 UD-9 scr122-last-owner
51 SCR-122 UD-10 scr122-promotion|52 SCR-122 UD-11 scr122-unbind-known|53 SCR-122 UD-12 scr122-unbind-unknown
54 SCR-122 UD-13 scr122-unbind-result|55 SCR-122 UD-14 scr122-tightening|56 SCR-122 UD-15 scr122-sessions
57 SCR-122 UD-16 scr122-invited|58 SCR-122 UD-2 =43|96 SCR-122 UD-17 scr122-partly-saved
97 SCR-122 UD-18 scr122-effective-today|100 SCR-122 UD-19 scr122-effective-profile|104 SCR-122 UD-20 scr122-disabled
59 SCR-123 I-1 scr123-form|60 SCR-123 I-2 scr123-validation|61 SCR-123 I-3 scr123-creating
62 SCR-123 I-4 scr123-link-once|63 SCR-123 I-5 scr123-copied|64 SCR-123 I-6 scr123-pending-expired
65 SCR-123 I-7 scr123-reissue|66 SCR-123 I-8 scr123-error|67 SCR-123 I-9 scr123-step-up|68 SCR-123 I-4 =62
98 SCR-123 I-10 scr123-outcome-unknown
69 SCR-124 V-1 scr124-entry|70 SCR-124 V-2 scr124-validation|71 SCR-124 V-3 scr124-starting
72 SCR-124 V-4 scr124-active|73 SCR-124 V-5 scr124-5min|74 SCR-124 V-6 scr124-1min|75 SCR-124 V-7 scr124-refused
76 SCR-124 V-8 scr124-expired-held|77 SCR-124 V-9 scr124-exited|78 SCR-124 V-10 scr124-owner-target
79 SCR-124 V-11 scr124-start-refusals|80 SCR-124 V-12 scr124-floating|81 SCR-124 V-13 scr124-target-notice
82 SCR-124 V-4 =72|99 SCR-124 V-14 scr124-exit-failed
83 SCR-154 N-1 scr154-never-had|84 SCR-154 N-2 scr154-withdrawn|85 SCR-154 N-3 scr154-account
86 SCR-155 N-4 scr155-admin-route|87 SCR-155 N-5 scr155-unknown-route|88 SCR-155 N-6 role-matrix|89 SCR-155 N-4 =86
90 proofs - status-treatments|91 proofs - components|92 proofs - redlines
"""
SIZE_OF = {8: SIZE_1280, 88: SIZE_1280, 9: SIZE_1280}  # §0 L49 (08, 88) and L72-73 (09 at 1280: see spec gaps)
THEME_OF = {9: "dark+light", 90: "dark+light+hc"}  # §0 L61, L69
FRAMES_OF = {8: 2, 88: 3, 9: 4, 90: 2, 91: 2, 92: 2}  # §0 L61, L68, L72-73: frames other than a state board's two
RENDERS = (1, 4, 9, 10, 22, 24, 25, 26, 31, 34, 72, 76, 80, 90, 94)  # §0 L73-74: greyscale + deuteranopia, 2 PNGs each
_PREFIX = re.compile(r"^(shell|scr\d{3})-")


def _plan() -> dict[int, Bd]:
    """Parse _PLAN into the registry; a light twin ("=NN") takes its dark twin's state and the slug + "-light"."""
    out: dict[int, Bd] = {}
    rows = [r.split() for line in _PLAN.strip().splitlines() for r in line.split("|")]
    for nn_s, screen, sid, slug in rows:
        nn = int(nn_s)
        twin = int(slug[1:]) if slug.startswith("=") else None
        if twin is not None:
            d = out[twin]
            out[nn] = Bd(screen, sid, d.state, d.slug + "-light", d.size, "light", twin)
            continue
        out[nn] = Bd(screen, sid, _PREFIX.sub("", slug), slug, SIZE_OF.get(nn, SIZE_BOTH), THEME_OF.get(nn, "dark"),
                     None)
    return out


BOARDS = _plan()
assert len(BOARDS) == 104 and sorted(BOARDS) == list(range(1, 105))  # §0 L71: 104 boards (104 = UD-20, §8 L406)
LIGHT_TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {10: 1, 20: 11, 29: 22, …}


def plan_counts() -> dict[str, int]:
    """§0 L71-74's counts from the registry: boards, dark state boards (both sizes), light boards, frames and PNGs (one
    export per board plus the greyscale and deuteranopia renders of RENDERS)."""
    light = [nn for nn, b in BOARDS.items() if b.twin]
    dark_state = [nn for nn, b in BOARDS.items() if not b.twin and nn not in FRAMES_OF]
    frames = 2 * len(dark_state) + 2 * len(light) + sum(FRAMES_OF.values())
    return {"boards": len(BOARDS), "dark_state": len(dark_state), "light": len(light), "frames": frames,
            "pngs": len(BOARDS) + 2 * len(RENDERS)}


def penpot_name(name: str) -> str:
    """A board name in Penpot's normalised form ("a/b" -> "a / b")."""
    return re.sub(r"\s*/\s*", " / ", name)


def board_name(nn: int) -> str:
    """The §0 L47 board name of board nn, normalised for Penpot: "E42-D03 / 31 SCR-121 / populated · 1280×800+2560×1440
    · dark"."""
    b = BOARDS[nn]
    return penpot_name(f"E42-D03 / {nn:02d} {b.screen}/{b.state} · {b.size} · {b.theme}")


def grid_xy(nn: int) -> tuple[int, int]:
    """Board nn's page position: x = ((NN − 1) mod 5) × 4600, y = floor((NN − 1) / 5) × 1800 (build notes)."""
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def export_path(nn: int) -> str:
    """The export docs/design/E42/img/E42-D03-NN-<slug>.png (§0 L51-52); light twins and boards 09, 90-92 use the
    kit's slug (§0 gives none)."""
    return f"docs/design/E42/img/E42-D03-{nn:02d}-{BOARDS[nn].slug}.png"


ROOT_O = {"dir": "row", "align": "start", "fill": APP, "pad": INSET_LG, "gap": INSET_LG, "clip": True}


def root_size(frames: Iterable[Node], ann: Node | None = None) -> tuple[int, int]:
    """Root width and height for frames side by side plus the 400 px annotation column, inset.lg padding and gaps
    (the height rounded up to 8)."""
    fr = list(frames)
    w = ROOT_PAD + sum(round(est_width(f)) + ROOT_PAD for f in fr) + (ANN_W + ROOT_PAD if ann else 0)
    tallest = max([est_height(f) for f in fr] + [est_height(ann) if ann else 0.0])
    return w, int(math.ceil((tallest + 2 * ROOT_PAD) / 8) * 8)


def board(nn: int, screen: str | None = None, state: str | None = None, size: str | None = None,
          theme: str | None = None, *, frames: Iterable[Node] | None = None, ann: Node | None = None,
          w: int | None = None, h: int | None = None) -> dict[str, Any]:
    """The sheet's board dict for board nn: the §0 name (normalised), the build-notes grid x/y, ROOT_O, and w/h (given,
    or from frames and the annotation column). screen/state/size/theme default to the registry and must match it;
    size accepts "both" / "1280" for the two §0 size strings."""
    if nn not in BOARDS:
        raise ValueError(f"board {nn} is not in §0's plan (01-104)")
    b = BOARDS[nn]
    size = {"both": SIZE_BOTH, "1280": SIZE_1280}.get(size or "", size)
    for what, got, want in (("screen", screen, b.screen), ("state", state, b.state), ("size", size, b.size),
                            ("theme", theme, b.theme)):
        if got is not None and got != want:
            raise ValueError(f"board {nn:02d}: {what} {got!r} differs from the registry's {want!r} (§0 / §4-§11)")
    if w is None or h is None:
        if frames is None:
            raise ValueError("board(): pass frames= (and ann=) or w= and h=")
        w, h = root_size(frames, ann)
    if w > PITCH_X - 40 or h > PITCH_Y - 40:
        raise ValueError(f"board {w} x {h} would touch its neighbours (pitch {PITCH_X} x {PITCH_Y}): use a 2 x 2 "
                         f"layout")
    _deviate("names")
    _src("boards")
    LOG.add("live_checks", "root name: after the first section call the root must read back exactly as the sheet's "
                           "board.name, or later calls create a duplicate root")
    x, y = grid_xy(nn)
    return {"name": board_name(nn), "w": w, "h": h, "x": x, "y": y, "o": dict(ROOT_O)}


# --- Chrome (CMP-072 TopBar, CMP-071 NavRail, RightRail, CMP-208 StatusBar; §1 L98, §4 L165-172, E10:61-71).
def env_badge(env: str = "LIVE", fill: str | None = None, name: str | None = None) -> Node:
    """The env badge (CMP-012 composition): the word LIVE or DEMO (type.ui.caption, color.text.primary) in a pill with
    a 1 px color.env.live / .demo border, no fill unless fill= (a strip item gives it color.surface.raised so the
    border and the word keep their measured pairs, §15 L649, D02:836); never colour-only (14:81)."""
    if env not in ENV_COLOR:
        raise ValueError("env: LIVE | DEMO")
    o = {"padX": INSET_XS, "radius": R_BADGE, "stroke": ENV_COLOR[env], "strokeWidth": HAIRLINE}
    if fill:
        o["fill"] = fill
    return hbox(name or f"CMP-012 Badge (composition) · {env}", [text("word", env, CAPTION, TEXT_1)], o, h=ENV_H)


def placeholder(name: str, w: int, h: int = 12) -> Node:
    """A neutral placeholder bar for chrome content no E42-D03 source specifies (DEVIATIONS["chrome"])."""
    _deviate("chrome")
    return rect(f"placeholder · {name}", w, h, HOVER, {"radius": R_CONTROL})


def _divider(name: str, w: float, h: float, x: float, y: float) -> Node:
    """A 1 px color.border.subtle divider placed absolutely (Penpot draws no one-sided strokes)."""
    return rect(name, w, h, BORDER_SUBTLE, x=x, y=y, abs=True)


def icon_button(role: str, glyph_name: str, color: str = TEXT_2) -> Node:
    """A 32 x 32 CMP-002 IconButton composition (ghost) holding one registry glyph; named by its role."""
    _deviate("compose")
    return hbox(f"CMP-002 IconButton (composition) · {role}", [icon("icon", glyph_name, color)],
                {"justify": "center", "radius": R_CONTROL}, w=CONTROL_H, h=CONTROL_H)


def topbar(px: int, env: str = "LIVE") -> Node:
    """The 48 px TopBar (CMP-072): wordmark and workspace-switcher placeholders, the env badge, CMP-210's placeholder,
    the search trigger and the owner's CMP-061 user menu (§1's basiltt)."""
    g = SIZES[px]
    _src("shell")
    left = hbox("left", [placeholder("wordmark", 88), env_badge(env), placeholder("workspace switcher", 136)],
                {"gap": INSET_MD})
    menu = hbox("CMP-061 UserMenu (composition)", [text("name", SAMPLE["owner"], BODY, TEXT_1),
                                                    icon("chevron", "chevron-down", TEXT_2)],
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL}, h=CONTROL_H,
                note="opens CMP-061: Profile · Settings · Admin · Sign out (§4 L189)")
    right = hbox("right", [placeholder("CMP-210 HealthChips", 160), icon_button("search", "search"), menu],
                 {"gap": INSET_MD})
    return hbox("CMP-072 TopBar (composition)", [left, right, _divider("divider", g.w, 1, 0, g.top - 1)],
                {"padX": INSET_LG, "justify": "space-between", "fill": CHROME}, w=g.w, h=g.top,
                note="48 px (§1 L98); the env badge is never hideable (E10-D02)")


def _admin_entry(px: int, selected: bool) -> Node:
    """The NavRail Admin entry (Owner only): the ◆ mark, and at 2560 its label; selected = the current area."""
    o: dict[str, Any] = {"radius": R_CONTROL, **({"fill": SELECTED} if selected else {})}
    note = "Owner only; structurally absent for Manager and Viewer (E10-D02)"
    note += "; aria-current=page" if selected else ""
    mark = glyph("admin", TEXT_1, "mark")
    if px == 1280:
        return hbox("Admin entry", [mark], {**o, "justify": "center"}, w=48, h=CONTROL_H, note=note + "; named 'Admin'")
    kids = [mark, text("label", label("nav_admin"), BODY, TEXT_1 if selected else TEXT_2)]
    return hbox("Admin entry", kids, {**o, "gap": INSET_SM, "padX": INSET_MD}, w=SIZES[px].nav - 16, h=CONTROL_H,
                note=note)


def navrail(px: int, admin_entry: bool = True, selected: bool = True, entries: int = 5, h: int | None = None) -> Node:
    """The NavRail (CMP-071): collapsed 64 px at 1280, expanded 240 px at 2560 (§2 D1); E10's workspace entries as
    placeholders, the Admin entry at the foot (Owner only; admin_entry=False draws a Manager's or Viewer's rail)."""
    g = SIZES[px]
    body_h = h or g.h - g.top - g.status
    rows = []
    for i in range(1, entries + 1):
        if px == 1280:
            rows.append(hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=CONTROL_H))
        else:
            rows.append(hbox(f"entry-{i}", [placeholder("glyph", 16, 16), placeholder("label", 104, 8)],
                             {"gap": INSET_SM, "padX": INSET_MD}, w=g.nav - 16, h=CONTROL_H))
    kids = [vbox("entries", rows, {"gap": INSET_XS, "align": "center"})]
    if admin_entry:
        kids.append(_admin_entry(px, selected))
    kids.append(_divider("divider", 1, body_h, g.nav - 1, 0))
    return vbox("CMP-071 NavRail (composition)", kids,
                {"justify": "space-between", "align": "center", "padY": INSET_SM, "fill": CHROME},
                w=g.nav, h=body_h, vs="fill", note=f"{g.nav} px ({'collapsed' if px == 1280 else 'expanded'}, §2 D1)")


def rightrail(px: int, h: int | None = None) -> Node:
    """The 240 px RightRail with CMP-211 at its top (§1 L98; E39-D01's control, consumed, drawn as a placeholder) and
    E10's quick-view rows as placeholders."""
    g = SIZES[px]
    body_h = h or g.h - g.top - g.status
    panic = box("CMP-211 PanicButtons (placeholder)", [], {"radius": R_CONTROL, "fill": HOVER}, w=g.right - 24, h=40,
                note="E39-D01's Flatten all / Kill switch cluster at the rail's top; copy and look are E39's "
                     "(§12 L544)")
    _deviate("chrome")
    rows = [placeholder(f"row-{i}", g.right - 24) for i in range(1, 4)]
    return vbox("RightRail (composition)", [panic, *rows, _divider("divider", 1, body_h, 0, 0)],
                {"gap": INSET_MD, "pad": INSET_MD, "fill": CHROME}, w=g.right, h=body_h, vs="fill",
                note="240 px at both sizes (§2 D1)")


def statusbar(px: int, env: str = "LIVE") -> Node:
    """The 48 px StatusBar (CMP-208): E10's connection chip as a placeholder, the env badge repeated at the end."""
    g = SIZES[px]
    return hbox("CMP-208 StatusBar (composition)", [placeholder("connection chip", 120), env_badge(env),
                                                     _divider("divider", g.w, 1, 0, 0)],
                {"padX": INSET_LG, "justify": "space-between", "fill": CHROME}, w=g.w, h=g.status,
                note="48 px (§1 L98); the env badge repeats the TopBar's (E10-D02)")


# --- CMP-087 AdminLayout parts (§4 L165-178, §2 D2-D5, §14 band.* / strip.* / meta / footer, §15 L646-649).
BADGE_STATES = ("unlocked", "5min", "1min", "locked")


def badge_state(seconds: int) -> str:
    """The (a) badge state for the window's remaining seconds: more than 5:00 unlocked (SH-1), 5:00 to 1:01 warning
    (SH-2), 1:00 to 0:01 danger (SH-3), 0:00 locked (SH-4; §2 D3 L117, §4 L182-185)."""
    return "unlocked" if seconds > 300 else "5min" if seconds > 60 else "1min" if seconds > 0 else "locked"


def badge(seconds: int | None = None, state: str | None = None) -> Node:
    """The (a) re-auth badge, a non-interactive pill at the band's right end: SH-1 "Admin unlocked · 12:40 left" on
    color.surface.hover in color.text.secondary; SH-2 the warning pill + triangle "4:59 left"; SH-3 the danger pill +
    octagon "0:59 left — unlock to keep editing"; SH-4 / SH-7 "Admin locked — unlock to save" (danger, D4). The
    clock is type.num.base; the badge is outside any live region (D02:114)."""
    st = state or badge_state(int(seconds or 0))
    if st not in BADGE_STATES:
        raise ValueError(f"badge state {st!r}: one of {BADGE_STATES}")
    if st != "locked" and seconds is None:
        raise ValueError("badge(): a countdown state needs seconds= (the server's expires_at minus its now, §1 L108)")
    _src("shell")
    _src("tint")
    clock = mss(seconds or 0)
    if st == "unlocked":
        kids = [clock_text("text", copy("band.unlocked", mss=clock), BODY, TEXT_2)]
        fill_ = HOVER
    else:
        tone = "warning" if st == "5min" else "danger"
        key = {"5min": "band.left", "1min": "band.left_final", "locked": "band.locked"}[st]
        fill_, kind, gcol = TONES[tone]
        kids = [glyph(kind, gcol), clock_text("text", copy(key, mss=clock), BODY, TEXT_1)]
    notes = {"unlocked": "SH-1: no announcement", "5min": "SH-2: polite once announce.admin_5min",
             "1min": "SH-3: assertive once announce.admin_1min", "locked": "SH-4: assertive once announce.admin_locked"}
    return hbox("re-auth badge (CMP-035 text pattern)", kids,
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_BADGE, "fill": fill_}, h=PILL_H,
                note=f"non-interactive, never focusable, not live; {notes[st]}")


def grace_line(cls: str = "users", seconds: int = 134) -> Node:
    """The (b) grace line at the band's right end (SH-5): "Still trusted for user changes · 2:14" in
    color.text.secondary, the clock type.num.base; no pill, no badge, no countdown elsewhere (§4 L186)."""
    if cls not in ("users", "risk_caps"):
        raise ValueError("grace class: users | risk_caps")
    _src("shell")
    line = copy("band.grace", cls=copy(f"band.grace.class.{cls}"), mss=mss(seconds))
    return clock_text("grace line", line, BODY, TEXT_2, note="SH-5: polite at 60 s and 10 s (D06:58)")


def band(route: str, right: Node | None = None, px: int = 1280) -> Node:
    """The admin band: region "Admin area", color.surface.admin-tint (DS-1 -> color.surface.raised), space.inset.lg,
    "◆ Admin area · <route>" with the (a) badge or (b) grace line at its right end; it holds no focusable control
    and spans 944 / 2048 px (§4 L166-167, L174-175)."""
    _fallback("DS-1")
    _src("shell")
    kids = [text("label", copy("band.label", route=route), BODY_STRONG, TEXT_1)] + ([right] if right else [])
    return hbox("CMP-087 band (composition)", kids, {"pad": INSET_LG, "justify": "space-between", "fill": ADMIN_TINT},
                w=SIZES[px].inner, h=BAND_H,
                note='role="region" aria-label="Admin area"; never focusable; the fill is not a carrier (§2 D2)')


def rule(px: int = 1280) -> Node:
    """The 4 px rule under the band, color.border.admin (DS-2 -> color.text.tertiary): a carrier (AC-4, §4 L176)."""
    _fallback("DS-2")
    return rect("CMP-087 rule (4 px)", SIZES[px].inner, RULE_H, ADMIN_RULE,
                note="6.29 / 6.81 / 12.54 against the page (§15 L647)")


STRIP_DANGER = ("strip.locked", "strip.tamper", "strip.withdrawal", "strip.break_glass")  # critical items (§4 L170, D4)


def strip_item(key: str, env: str | None = None, tone: str | None = None, focused: bool = False, **fills: Any) -> Node:
    """One strip item: a CMP-021 link (color.text.primary) with its tone glyph on its tone fill, plus the slice's env
    badge; critical keys take the danger tone (octagon), the rest the warning tone (triangle). "Attention:" leads every
    warning's accessible name (§6 L287); the env badge is part of the name (§6 L288)."""
    t = tone or ("danger" if key in STRIP_DANGER else "warning")
    if key == "strip.unlock_again" and tone is None:
        _deviate("strip-tone", "strip.unlock_again is drawn in the warning tone: no source names its tone (§2 D4 makes "
                               "only the expiry items danger).")
    fill_, kind, gcol = TONES[t]
    words = text("link", copy(key, **fills), BODY, TEXT_1)
    kids = [glyph(kind, gcol), words] + ([env_badge(env, fill=RAISED)] if env else [])
    item = hbox("CMP-021 Link (composition)", kids, {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL,
                                                     "fill": fill_}, h=ITEM_H, note=f"{key}; a link to the control")
    _deviate("link")
    return ring(item) if focused else item


def strip(items: Iterable[Node] = (), px: int = 1280) -> Node:
    """The "Needs your action" region (role="region", not live): "Needs your action (n)" and the items wrapping, never
    truncated; empty, the one line "Nothing needs your action" (§4 L168-170, SH-6)."""
    its = list(items)
    _src("shell")
    if not its:
        kids = [text("none", copy("strip.none"), LABEL, TEXT_2)]
    else:
        kids = [text("title", copy("strip.title", n=len(its)), LABEL, TEXT_2)]
        kids += [dict(it, name=f"item-{i:02d}") for i, it in enumerate(its, 1)]
    return hbox("CMP-087 strip (composition)", kids, {"wrap": "wrap", "gap": INSET_SM, "padY": INSET_SM},
                w=SIZES[px].inner,
                note='role="region" "Needs your action"; a list; not live (the shell announces once)')


def page_header(h1: str, meta: str | None = None, primary: Node | None = None, marker_line: str | None = None,
                px: int = 1280) -> Node:
    """CMP-088 PageHeader: the h1 (type.ui.heading-md, color.text.primary), the meta line (default meta.asof with §1's
    14:02:11; type.ui.caption, color.text.tertiary), an optional audited-read marker and the primary action at the
    end; space.inset.lg above and below, space.stack.sm between lines (Appendix A L883-885)."""
    lines = [text("h1", h1, HEADING_MD, TEXT_1, note="the h1: the skip-link target (CMP-085)"),
             text("meta", meta or copy("meta.asof", hhmmss=SAMPLE["asof"]), CAPTION, TEXT_3)]
    if marker_line:
        lines.append(text("marker", marker_line, CAPTION, TEXT_3))
    kids = [vbox("titles", lines, {"gap": STACK_SM})] + ([dict(primary, name="primary action")] if primary else [])
    return hbox("CMP-088 PageHeader (composition)", kids, {"padY": INSET_LG, "justify": "space-between",
                                                          "align": "end"}, w=SIZES[px].inner)


def footer_marker(px: int = 1280) -> Node:
    """The area-entered footer (footer.area_entered, D02 D5's fourth placement, D27; type.ui.caption, tertiary)."""
    return hbox("footer marker (CMP-093)", [text("text", copy("footer.area_entered"), CAPTION, TEXT_3)],
                {"padT": INSET_LG}, w=SIZES[px].inner,
                note="admin.area_entered comes from the strip's /admin/* reads on SCR-121-123 (§4 L202-205)")


# --- Banners: CMP-028 compositions (the shell-band slot, inline notices) and the SCR-124 view-as banner (§10, D24).
def banner(tone: str, chars: str, title: str | None = None, actions: Iterable[Node] = (), shell: bool = False,
           w: int | None = None, name: str | None = None, note: str | None = None) -> Node:
    """A CMP-028 Callout composition: the tone's .subtle fill, its .strong glyph (info, check, triangle, octagon), the
    text in color.text.primary (body; title body-strong) and optional controls; shell=True spans the frame under the
    TopBar (the shell-band slot: maintenance, D09's three-strike banner, critical system notices, §4 L172-174)."""
    if tone not in TONES or tone == "neutral":
        raise ValueError("banner tone: info | success | warning | danger")
    fill_, kind, gcol = TONES[tone]
    words = [text("title", title, BODY_STRONG, TEXT_1)] if title else []
    width = w or 0
    tw = max(width - 2 * PX[INSET_LG] - 24 - sum(est_width(a) + 8 for a in actions), 120) if width else None
    words.append(text("body", chars, BODY, TEXT_1, w=tw))
    kids = [glyph(kind, gcol), vbox("words", words, {"gap": STACK_XS})] + [dict(a) for a in actions]
    o = {"gap": INSET_SM, "padX": INSET_LG, "padY": INSET_SM, "fill": fill_, "align": "start"}
    if not shell:
        o["radius"] = R_CARD
    _deviate("compose")
    return hbox(name or f"CMP-028 Callout (composition) · {tone}", kids, o, w=w, hs="fill" if shell else None,
                note=note or ("the shell-band slot under the TopBar" if shell else None))


def notice(chars: str, tone: str = "info", w: int | None = None, name: str | None = None) -> Node:
    """An inline, static CMP-028 notice (the tightening notice of §12 D22 is info tone, polite once)."""
    return banner(tone, chars, w=w, name=name or "CMP-028 notice (composition)")


def viewas_banner(user: str = "alex", seconds: int = 1660, phase: str | None = None, protective: bool = True,
                  notified: bool = False, w: int = 1280, exit_focused: bool = False) -> Node:
    """The SCR-124 view-as banner, every window's first row above the TopBar (D24): color.status.info.subtle with a
    2 px color.status.info.strong rule under it, the eye glyph, va.banner (va.banner_ro until the protective handlers
    mount, V-4), the countdown glyph (the clock, then at 5:00 the triangle, at 1:00 the octagon; text stays primary),
    optionally va.notified (a target, CG-26) and Exit view-as (primary + a 1 px color.text.primary border, F2);
    phase="ended" draws va.ended (V-8)."""
    _src("viewas")
    st = phase or ("ended" if seconds <= 0 else "1min" if seconds <= 60 else "5min" if seconds <= 300 else "active")
    if st == "ended":
        words = [text("text", copy("va.ended", user=user), BODY, TEXT_1)]
    else:
        line = copy("va.banner" if protective else "va.banner_ro", user=user, mss=mss(seconds))
        head, tail = line.split(" Ends in ")
        kind, gcol = {"active": ("clock", INFO_STRONG), "5min": ("triangle", WARN_STRONG),
                      "1min": ("octagon", DANGER_STRONG)}[st]
        if st == "active":
            _deviate("viewas-clock", "The view-as countdown carries the clock glyph before 5:00 (§10 L471 says "
                                     "only that the countdown's glyph changes at 5:00 and 1:00; the first glyph is "
                                     "unnamed).")
        words = [text("text", head, BODY, TEXT_1), glyph(kind, gcol, "countdown glyph"),
                 clock_text("countdown", "Ends in " + tail, BODY, TEXT_1, note="never live (§10 L502)")]
        if notified:
            words.append(text("notified", copy("va.notified", user=user), BODY, TEXT_1,
                              note="a target: shown once alex can read the notice (CG-26)"))
    lead = hbox("lead", [glyph("eye", INFO_STRONG, "eye"), hbox("words", words, {"gap": INSET_SM, "wrap": "wrap"})],
                {"gap": INSET_SM})
    row = hbox("row", [lead, button(label("exit_view_as"), "exit", focused=exit_focused)],
               {"gap": INSET_SM, "padX": INSET_LG, "padY": INSET_SM, "justify": "space-between", "fill": INFO_SUBTLE},
               w=w)
    return vbox("CMP-028 view-as banner (composition)", [row, rect("rule (2 px)", w, 2, INFO_STRONG)], None, w=w,
                note='labelled region aria-label="View-as", not live; first in the DOM; Exit is the first tab stop; '
                     "never scrolled out of view, wraps, never truncated (D24)")


# --- The frame and the assembled CMP-087 shell.
def frame(px: int, kids: Iterable[Node] = (), name: str | None = None) -> Node:
    """A fixed 1:1 frame (1280 x 800 or 2560 x 1440): flex column, color.surface.app, clip on (build notes)."""
    g = SIZES[px]
    _src("layout")
    return vbox(name or f"frame-{px}", kids, {"fill": APP, "clip": True}, w=g.w, h=g.h)


def main_column(px: int, kids: Iterable[Node], h: int) -> Node:
    """The 976 / 2080 px <main> column: space.inset.lg padding (944 / 2048 inside), color.surface.app, clip on."""
    g = SIZES[px]
    return vbox("main", kids, {"pad": INSET_LG, "fill": APP, "clip": True}, w=g.main, h=h, vs="fill",
                note="<main>: band → rule → strip → PageHeader → route content → footer marker (§4 L166-172)")


def shell(px: int, *, route: str, h1: str, right: Node | None = None, items: Iterable[Node] = (),
          meta: str | None = None, primary: Node | None = None, marker_line: str | None = None,
          content: Iterable[Node] = (), banners: Iterable[Node] = (), viewas: Node | None = None,
          admin_entry: bool = True, env: str = "LIVE", overlays: Iterable[Node] = (), name: str | None = None,
          footer: bool = True) -> Node:
    """The CMP-087 frame at px: [view-as banner] → TopBar → [shell-band banners] → NavRail | main (band with the
    badge or grace line, rule, strip, PageHeader, content, footer marker) | RightRail → StatusBar, then overlays
    (scrim and dialog from modal()) on top. Content nodes should be at most SIZES[px].inner wide."""
    g = SIZES[px]
    _src("shell")
    above = ([viewas] if viewas else []) + [topbar(px, env)] + list(banners)
    body_h = int(g.h - g.status - sum(est_height(n) for n in above))
    route_kids = [band(route, right, px), rule(px), strip(items, px), page_header(h1, meta, primary, marker_line, px)]
    route_kids += [c for c in content]
    if footer:
        route_kids.append(footer_marker(px))
    used = sum(est_height(k) for k in route_kids) + 2 * PX[INSET_LG]
    if used > body_h:
        LOG.add("live_checks", f"fit: frame-{px} main column content is about {used:.0f} px for {body_h} px: it is "
                               f"clipped at the bottom (a page scroll), check the export")
    rail = dict(rightrail(px, h=body_h), x=g.nav + g.main, y=0, abs=True)  # absolute, so main is the last child
    body = hbox("body", [navrail(px, admin_entry, h=body_h), rail, main_column(px, route_kids, body_h)],
                {"align": "start"}, w=g.w, h=body_h, vs="fill",
                note="NavRail | main | RightRail (the rail is absolute at x = NavRail + main)")
    kids = above + [body, statusbar(px, env)] + list(overlays)
    return frame(px, kids, name)


def app_shell(px: int, content: Iterable[Node] = (), *, viewas: Node | None = None, banners: Iterable[Node] = (),
              admin_entry: bool = True, env: str = "LIVE", overlays: Iterable[Node] = (), center: bool = False,
              name: str | None = None) -> Node:
    """The SCR-010 shell without CMP-087 (the non-admin route a gate overlays, alex's workspace under view-as,
    SCR-154/155, board 09's workspace, board 88's roles): [view-as banner] → TopBar → [banners] → NavRail | main |
    RightRail → StatusBar → overlays. With no content the main column holds E10's WorkspaceCanvas as one neutral
    color.surface.canvas placeholder; center=True centres the content (SCR-154/155's single column, §11 L514)."""
    g = SIZES[px]
    above = ([viewas] if viewas else []) + [topbar(px, env)] + list(banners)
    body_h = int(g.h - g.status - sum(est_height(n) for n in above))
    kids = list(content)
    if not kids:
        _deviate("chrome")
        kids = [rect("placeholder · WorkspaceCanvas (E10)", g.inner, body_h - 2 * PX[INSET_LG], CANVAS,
                     {"radius": R_CARD}, note="E10-D02's workspace canvas; its panels are other epics' (not drawn)")]
    o: dict[str, Any] = {"pad": INSET_LG, "fill": APP, "clip": True, "gap": STEP}
    if center:
        o.update(align="center", justify="center")
    main = vbox("main", kids, o, w=g.main, h=body_h, vs="fill", note="<main> of SCR-010 (E10-D02)")
    rail = dict(rightrail(px, h=body_h), x=g.nav + g.main, y=0, abs=True)
    body = hbox("body", [navrail(px, admin_entry, selected=False, h=body_h), rail, main], {"align": "start"},
                w=g.w, h=body_h, vs="fill")
    return frame(px, above + [body, statusbar(px, env)] + list(overlays), name)


def modal(px: int, dialog_node: Node) -> list[Node]:
    """One absolute "overlay" board over the whole frame holding the flat 60 % scrim and the dialog centred on it
    (D06:24-25): pass the result as shell(overlays=…). The dialog's height is estimated; a live check asks to
    re-centre it after relayout."""
    g = SIZES[px]
    _fallback("SCRIM")
    scrim = rect("scrim", g.w, g.h, SCRIM, {"opacity": OPACITY_SCRIM}, x=0, y=0,
                 note="flat 60 % scrim, no blur; the content under it is not masked")
    dw, dh = est_width(dialog_node), est_height(dialog_node)
    LOG.add("live_checks", f"modal: centre '{dialog_node['name']}' in frame-{px} after relayout (estimated {dw:.0f} x "
                           f"{dh:.0f} px)")
    dlg = dict(dialog_node, x=round((g.w - dw) / 2), y=round(max((g.h - dh) / 2, 0)))
    return [box("overlay", [scrim, dlg], None, w=g.w, h=g.h, x=0, y=0, abs=True, note="the modal layer (no layout)")]


# --- Controls (CMP-001 / CMP-021 compositions at the comfortable 32 px; §12 L537, §15 L651, L661-662, D24).
BUTTON_LOOK = {  # variant -> (fill, label colour, stroke); every label type.ui.body-strong (CMP-001 md)
    "primary": (ACTION_PRIMARY, TEXT_ON_ACTION, None),  # 4.76 (§15 L651)
    "secondary": (ACTION_SECONDARY, TEXT_1, None),  # Cancel, Retry: 10.17 (§15 L653, L661)
    "ghost": (None, TEXT_2, None),
    "destructive": (DANGER_SUBTLE, TEXT_1, DANGER_STRONG),  # the confirm and danger-zone look (§12 L536-537, D02:129)
    "exit": (ACTION_PRIMARY, TEXT_ON_ACTION, TEXT_1),  # Exit view-as: primary + 1 px text.primary border (D24, F2)
}


def ring(control: Node, radius: str = R_CARD) -> Node:
    """control inside the CMP-039 focus ring: a wrapper hugging it with space.inset.xs (4 px) padding and a 2 px
    color.focus.ring inner stroke, so the ring sits 2 px off the control inside the wrapper (no parent clip cuts it)."""
    _deviate("focus")
    return hbox("focus-ring", [control], {"pad": INSET_XS, "radius": radius, "stroke": FOCUS_RING,
                                          "strokeWidth": FOCUS_W, "strokeAlign": "inner"},
                note="focus-visible (CMP-039): 2 px ring at a 2 px offset")


def button(chars: str, variant: str = "secondary", focused: bool = False, described: str | None = None,
           glyph_kind: str | None = None, name: str | None = None) -> Node:
    """A CMP-001 Button composition, 32 px (size.control.comfortable), radius.control, space.button.paddingX; focused
    adds the CMP-039 ring; described= adds a caption under it (a §14 key or text: e.g. SH-4's Save described
    save.locked_hint, its T1 description; the expiry adds no T2 and board 04 draws the writes enabled, §4 L185)."""
    if variant not in BUTTON_LOOK:
        raise ValueError(f"button variant {variant!r}: one of {sorted(BUTTON_LOOK)}")
    _deviate("compose")
    _fallback("CONTROL")
    fill_, col, stroke = BUTTON_LOOK[variant]
    kids = ([glyph(glyph_kind, col)] if glyph_kind else []) + [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "height": CONTROL_COMF,
                         "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIRLINE, strokeAlign="inner")
    w = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    btn = hbox(name or f"CMP-001 Button (composition) · {chars}", kids, o, w=w, h=CONTROL_H)
    if focused:
        btn = ring(btn)
    if described:
        cap = copy(described) if described in COPY else described
        return vbox(f"{btn['name']} + description", [btn, text("description", cap, CAPTION, TEXT_2)],
                    {"gap": INSET_XS}, note="the description is the control's aria-describedby")
    return btn


# --- T2: disabled with a visible reason (§13 L602; E09-D09 §2.2, §9.1-§9.3). The look §13 L602 (5) and §15 L656, L661
# name; never color.text.disabled, never opacity.disabled (NEVER_TOKENS; the self-test scans its sheet for them).
T2_LABEL = TEXT_3  # the full label and the lock: color.text.tertiary (5.62 on raised, 5.20 on overlay, 4.79 on hover)
T2_REASON = TEXT_2  # the reason: color.text.secondary (§15 L661 "secondary and T2 reason")
T2_FILL, T2_EDGE = RAISED, BORDER_DEFAULT  # a filled control's fill goes to raised with a border.default hairline
T2_FOCUS_FILL = HOVER  # a focused CMP-041 item, T2 included, sits on color.surface.hover (§15 L656, DJ; F4: never on
#                        color.surface.selected)
NEVER_TOKENS = ("color.text.disabled", "opacity.disabled")  # §13 L602 (5): never on the label, the glyph or the reason
T2_CARRIER = {  # §13 L602 (4): an admin.* control's own carrier until D26's keys are registered (then CMP-079)
    "CMP-001": "CMP-001's disabledReason (15:51)", "CMP-041": "the CMP-041 item's disabledReason? (D09:208)",
    "CMP-005": "CMP-005's disabledReason (D09:205)", "CMP-044": "CMP-044's choices[].disabledReason (Appendix A L902)",
    "CMP-009": "a CMP-009 disabledReason? (15:127 lacks it; routed to the E05 owner, §20)",
    "CMP-007": "the shared node (CMP-007 readOnly?, 15:108; CMP-079 form: \"notice\" proposed, §20)",
    "CMP-002": "CMP-002's disabledReason (15:62), echoed by CMP-016",
}


def _t2_key(reason: str) -> str:
    """reason's current key (a gate-renamed alias resolved); a key §13 L602 puts outside T2 is recorded as a deviation
    (the drawing goes on, so old generators still run)."""
    if reason in COPY_REMOVED:
        raise KeyError(f"T2 reason {reason!r} left §14 at the merge: {COPY_REMOVED[reason]}")
    key = COPY_RENAMED.get(reason, reason)
    if key in NEVER_T2:
        _deviate("never-t2", f"kit: {reason} drawn as a T2 reason, but {NEVER_T2[key]} (T2, §13 L602): redraw it")
    return key


def _t2_text(reason: str, **fills: Any) -> str:
    """The reason's string: a §14 / D09 key through copy() (recorded; admin.* at most 60 characters, §14 L619) or
    a string from D09's vocabulary as given."""
    key = _t2_key(reason)
    if reason not in COPY:
        return reason
    why = copy(reason, **fills)
    if key.startswith("admin.") and len(why) > 60:
        raise ValueError(f"{key}: T2 reasons are at most 60 characters (§14 L619)")
    return why


def _carrier(reason: str | None, cmp: str) -> str:
    """The note naming who carries the reason (§13 L602 (4)): CMP-079 RbacGate for a view-as write (rbac.view_as),
    an admin.* control's own carrier until D26's keys are registered in E09-D09 §3.1."""
    key = COPY_RENAMED.get(reason or "", reason or "")
    if key == "rbac.view_as":
        return "wrapped in CMP-079 RbacGate, reason rbac.view_as"
    if key.startswith("admin."):
        return f"{key}: CMP-079 once D26's keys are registered in E09-D09 §3.1, until then {T2_CARRIER[cmp]}"
    return f"reason {reason!r}" if reason else "the reason its shared node carries"


def _reason_node(reason: str, w: int | None = None, name: str = "reason", **fills: Any) -> Node:
    """The T2 reason node (see t2_reason)."""
    _src("t2")
    return text(name, _t2_text(reason, **fills), CAPTION, T2_REASON, w=w,
                note="the reason: in the DOM at mount, the control's aria-describedby; a T2 keystroke re-shows it with "
                     "one polite announcement (T2, §13 L602 (3), (6))")


def t2_reason(reason: str, w: int | None = None, name: str = "reason", **fills: Any) -> Node:
    """A 2a reason node (T2, §13 L602 (3)): the reason in type.ui.caption color.text.secondary, in the DOM at mount and
    the control's aria-describedby: under a button or field, a menu item's or a T2 option's second line, or the one
    line under CMP-211's cluster. reason: a §14 key (admin.*, at most 60 characters, §14 L619),
    D09's rbac.view_as (fill user=) or a string from D09's vocabulary; fills as copy()."""
    return _reason_node(reason, w, name, **fills)


def lock_glyph(name: str = "locked") -> Node:
    """The T2 glyph (§13 L602 (4)): CMP-019 Icon lock (DS-5 icon/lock pending: the registry glyph 'locked') in
    color.text.tertiary, decorative=false, accessible name "Not available"; it leads the full label in 2a and under a
    shared notice (in 2b it is the badge on the icon; the sentence form has none)."""
    _src("t2")
    return dict(glyph("lock", T2_LABEL, name),
                note='CMP-019 Icon lock: decorative=false, accessible name "Not available"; it leads the full label, '
                     "both color.text.tertiary (T2, §13 L602 (4), (5))")


def t2_button(chars: str, reason: str, variant: str = "secondary", name: str | None = None, *,
              focused: bool = False, shared: bool = False, **fills: Any) -> Node:
    """A T2 CMP-001 Button (T2, §13 L602): the lock leads the full label, both color.text.tertiary; a filled variant
    (primary, secondary, destructive, exit) loses its fill to color.surface.raised with a 1 px color.border.default
    hairline, a ghost has none to lose; aria-disabled, never disabled, focusable (focused adds the CMP-039 ring), no
    hover; Enter or Space changes nothing and re-shows the reason. 2a (the default): a column named name or
    "T2 · <chars>" holding "CMP-001 Button (composition) · <chars> (T2)" and its "reason" under it. shared=True: the
    control alone, with no reason of its own: its aria-describedby points at a shared node (t2_notice for a §10 panel
    or UD-16 / UD-20, t2_cluster's line). reason: a §14 key, D09's rbac.view_as (fills: user=) or D09 text."""
    if variant not in BUTTON_LOOK:
        raise ValueError(f"button variant {variant!r}: one of {sorted(BUTTON_LOOK)}")
    _fallback("CONTROL")
    _deviate("compose")
    _deviate("t2")
    _src("t2")
    kids = [lock_glyph(), text("label", chars, BODY_STRONG, T2_LABEL)]
    w = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "height": CONTROL_COMF,
                         "justify": "center"}
    if BUTTON_LOOK[variant][0]:
        o.update(fill=T2_FILL, stroke=T2_EDGE, strokeWidth=HAIRLINE, strokeAlign="inner")
    where = "the shared node's id (no reason of its own)" if shared else "its reason under it"
    ctl = hbox(f"CMP-001 Button (composition) · {chars} (T2)", kids, o, w=w, h=CONTROL_H,
               note=f"T2, {_carrier(reason, 'CMP-001')}: aria-disabled (never disabled), focusable, no hover; "
                    f"variant {variant} when enabled; aria-describedby {where}; Enter or Space changes nothing and "
                    "re-shows the reason, polite once; emits nothing (T2, §13 L602 (2), (6), (7))")
    if focused:
        ctl = ring(ctl)
    if shared:
        _t2_key(reason)
        return dict(ctl, name=name) if name else ctl
    return vbox(name or f"T2 · {chars}", [ctl, _reason_node(reason, **fills)], {"gap": INSET_XS},
                note="T2 2a: the reason under the control is its aria-describedby (T2, §13 L602 (3))")


def t2_notice(reason: str, w: int | None = None, *, tone: str = "info", name: str | None = None,
              **fills: Any) -> Node:
    """One shared T2 reason node (T2, §13 L602 (3)-(4), "one notice, many pointers"): a CMP-028 notice holding the
    reason, no live role (§10 L475); every T2 control under it points aria-describedby at it and draws no reason of its
    own (t2_button / t2_select / t2_check / t2_field with shared=True; t2_icon_button, whose echo repeats it). Under a
    §10 panel's header (rbac.view_as, user=) or under UD-16 / UD-20's PageHeader (admin.invite_pending,
    admin.user_disabled; §8 L402, L406). The tone is a kit choice (DEVIATIONS["t2-notice"])."""
    _src("t2")
    _deviate("t2-notice")
    n = notice(_t2_text(reason, **fills), tone, w=w, name=name or "CMP-028 notice (composition) · T2")
    return dict(n, note="the shared T2 reason node: no live role (§10 L475), in the DOM at mount; every T2 control "
                        "under it has aria-describedby = its id and no reason line of its own (T2, §13 L602 (3)-(4))")


def t2_select(value: str, reason: str | None = None, *, label_: str | None = None, w: int = 200,
              focused: bool = False, shared: bool = False, name: str | None = None, **fills: Any) -> Node:
    """A T2 CMP-009 Select (the role select, a grant's level select; it stays the combobox, §13 L602 (1)): the trigger
    on color.surface.raised with a 1 px color.border.default hairline, its value and chevron in color.text.tertiary;
    the lock leads label_ (type.ui.label, tertiary, above the trigger) or, with no label_, the value. 2a: the reason
    under the field (UD-8, UD-16's role select); shared=True: none (UD-20's level selects). Alt+↓ and the arrows
    change nothing and re-show the reason (§13 L602 (6))."""
    if not shared and not reason:
        raise ValueError("t2_select: 2a needs reason= (or shared=True under a t2_notice)")
    _fallback("CONTROL")
    _deviate("compose")
    _deviate("t2")
    _src("t2")
    lead = ([] if label_ else [lock_glyph()]) + [text("value", value, BODY, T2_LABEL)]
    o = {"padX": INSET_SM, "radius": R_CONTROL, "fill": T2_FILL, "height": CONTROL_COMF, "stroke": T2_EDGE,
         "strokeWidth": HAIRLINE, "strokeAlign": "inner", "justify": "space-between"}
    trig: Node = hbox("CMP-009 Select (composition) · trigger (T2)",
                      [hbox("lead", lead, {"gap": INSET_XS}), icon("chevron", "chevron-down", T2_LABEL)], o, w=w,
                      h=CONTROL_H, note=f"T2, {_carrier(reason, 'CMP-009')}: aria-disabled, focusable, no listbox "
                                        "opens; Alt+↓ and the arrows change nothing and re-show the reason (T2, §13 "
                                        "L602 (1), (6))")
    if focused:
        trig = ring(trig)
    kids: list[Node] = []
    if label_:
        kids.append(hbox("label", [lock_glyph(), text("text", label_, LABEL, T2_LABEL)], {"gap": INSET_XS}))
    kids.append(trig)
    if shared:
        if reason:
            _t2_key(reason)
    else:
        kids.append(_reason_node(str(reason), w=w, **fills))
    return vbox(name or f"CMP-009 Select (composition) · {label_ or value} (T2)", kids, {"gap": STACK_XS},
                w=w + (8 if focused else 0))


def t2_check(label_: str, reason: str | None = None, *, checked: bool = False, extra: Iterable[Node] = (),
             focused: bool = False, shared: bool = False, w: int | None = None, name: str | None = None,
             **fills: Any) -> Node:
    """A T2 CMP-005 checkbox (a grant's tick: UD-16, UD-20; it keeps its aria-checked, §13 L602 (1)): the 16 px box on
    color.surface.raised with a 1 px color.border.default hairline (checked: the check in color.text.tertiary), the lock
    leading the full label in color.text.tertiary, then extra nodes (the env badge, a t2_select level). shared=True:
    no reason of its own (aria-describedby -> the PageHeader notice); 2a: the reason under it. Space changes nothing."""
    if not shared and not reason:
        raise ValueError("t2_check: 2a needs reason= (or shared=True under a t2_notice)")
    _deviate("compose")
    _deviate("t2")
    _src("t2")
    box_o = {"justify": "center", "radius": R_CONTROL, "fill": T2_FILL, "stroke": T2_EDGE, "strokeWidth": HAIRLINE,
             "strokeAlign": "inner"}
    bx = hbox("box", [icon("check", "check", T2_LABEL, ICON)] if checked else [], box_o, w=16, h=16,
              note="checked (aria-checked kept)" if checked else "unchecked (aria-checked kept)")
    lead = hbox("lead", [lock_glyph(), text("label", label_, BODY, T2_LABEL)], {"gap": INSET_XS})
    row: Node = hbox(f"CMP-005 Checkbox (composition) · {label_} (T2)", [bx, lead, *[dict(x) for x in extra]],
                     {"gap": INSET_SM, "height": ROW_COMF}, w=w, h=ROW_H,
                     note=f"T2, {_carrier(reason, 'CMP-005')}: aria-disabled, focusable; Space changes nothing and "
                          "re-shows the reason (T2, §13 L602 (1), (6))")
    if focused:
        row = ring(row)
    if shared:
        if reason:
            _t2_key(reason)
        return dict(row, name=name) if name else row
    return vbox(name or f"T2 · {label_}", [row, _reason_node(str(reason), w=w, **fills)], {"gap": INSET_XS})


def t2_field(label_: str, value: str | None = None, reason: str | None = None, *, w: int = 320, mono: bool = False,
             focused: bool = False, shared: bool = False, name: str | None = None, **fills: Any) -> Node:
    """A T2 CMP-007 TextInput (UD-16's cap fields are CMP-007s, DJ, §13 L602 (4)): readonly as well as aria-disabled
    (2); the lock leads the label (type.ui.label) in color.text.tertiary; the well on color.surface.raised with a 1 px
    color.border.default hairline, the value (type.num.base when mono) in color.text.tertiary. shared=True: no reason of
    its own (UD-16: it points at the PageHeader notice); 2a: the reason under the field."""
    if not shared and not reason:
        raise ValueError("t2_field: 2a needs reason= (or shared=True under a t2_notice)")
    _deviate("compose")
    _deviate("t2")
    _src("t2")
    val = [text("value", value, NUM_BASE if mono else BODY, T2_LABEL)] if value else []
    o = {"padX": INSET_SM, "radius": R_CONTROL, "fill": T2_FILL, "height": CONTROL_COMF, "stroke": T2_EDGE,
         "strokeWidth": HAIRLINE, "strokeAlign": "inner"}
    well: Node = hbox("input", val, o, w=w, h=CONTROL_H,
                      note=f"T2, {_carrier(reason, 'CMP-007')}: readonly and aria-disabled, focusable (T2, §13 L602 "
                           "(2))")
    kids = [hbox("label", [lock_glyph(), text("text", label_, LABEL, T2_LABEL)], {"gap": INSET_XS}),
            ring(well) if focused else well]
    if shared:
        if reason:
            _t2_key(reason)
    else:
        kids.append(_reason_node(str(reason), w=w, **fills))
    return vbox(name or f"field · {label_} (T2)", kids, {"gap": STACK_XS}, w=w + (8 if focused else 0))


def t2_icon_button(role: str, glyph_name: str, reason: str | None = None, *, echo: bool = False,
                   focused: bool = False, name: str | None = None, **fills: Any) -> Node:
    """A 2b T2 control (T2, §13 L602 (3)-(4)): a 32 x 32 CMP-002 IconButton composition, its registry glyph in
    color.text.tertiary with the lock badge on the icon (FALLBACKS["T2-BADGE"]); its description (the reason, or the
    §10 panel notice it points at) is visually hidden and CMP-016 echoes it on hover and focus; echo=True draws the
    echo, a CMP-016 Tooltip instance under the button holding the reason (Esc closes the echo only, §13 L602 (6))."""
    if echo and not reason:
        raise ValueError("t2_icon_button: echo=True needs reason= (the text the echo repeats)")
    _deviate("compose")
    _deviate("t2")
    _fallback("T2-BADGE")
    _src("t2")
    badge_ = box("lock badge", [icon("locked", "locked", T2_LABEL, ICON_SM, x=1, y=1, abs=True)],
                 {"radius": R_BADGE, "fill": T2_FILL}, w=14, h=14, x=17, y=17, abs=True,
                 note='the 2b badge: CMP-019 lock, decorative=false, name "Not available" (T2, §13 L602 (4))')
    btn: Node = hbox(f"CMP-002 IconButton (composition) · {role} (T2)", [icon("icon", glyph_name, T2_LABEL), badge_],
                     {"justify": "center", "radius": R_CONTROL}, w=CONTROL_H, h=CONTROL_H,
                     note=f"T2 2b, {_carrier(reason, 'CMP-002')}: aria-label {role!r}, aria-disabled, focusable; the "
                          "description is visually hidden and CMP-016 echoes it on hover and focus (T2, §13 L602 (3))")
    if focused:
        btn = ring(btn)
    if not echo:
        if reason:
            _t2_key(reason)
        return dict(btn, name=name) if name else btn
    tip = inst("CMP-016 Tooltip · echo", "CMP-016 · Tooltip", {"State": "default"},
               {"content": _t2_text(str(reason), **fills)},
               note="the 2b echo on hover and focus: a duplicate of the description, never the only copy (Esc closes "
                    "it only)")
    return vbox(name or f"T2 2b · {role}", [btn, tip], {"gap": STACK_XS})


def t2_sentence(reason: str, w: int | None = None, *, name: str | None = None, **fills: Any) -> Node:
    """The T2 sentence form (§13 L602 (3), (8)): an empty state whose sole CTA is a write (alex's empty rules or alerts
    list under view-as) is CMP-026 with its cta omitted and its description the reason (rbac.view_as, user=), alone:
    no glyph, no button; it stands in for that panel's §10 notice, so the sentence appears once."""
    _deviate("compose")
    _src("t2")
    desc = text("description", _t2_text(reason, **fills), BODY, T2_REASON, w=w,
                note="CMP-026's description, the reason alone: no glyph, no button (T2, §13 L602 (3), (8))")
    return vbox(name or "CMP-026 EmptyState (composition) · T2 sentence form", [desc],
                {"align": "center", "padY": INSET_XL}, w=w,
                note="the T2 sentence form: CMP-026 with cta omitted; it stands in for the panel's §10 notice")


def t2_cluster(items: Iterable[str | Node], reason: str, *, variant: str = "secondary", w: int | None = None,
               name: str | None = None, **fills: Any) -> Node:
    """CMP-211's cluster under view-as (§13 L602 (3): 2a, one reason line under the cluster, DJ; §10 L475): a str item
    is a T2 button in the shared form (the lock leading its label, no reason of its own), a node is drawn as given (a
    T1 control: FREEZE… on the account set once E39-S03 admits it); then the one reason line every T2 button's
    aria-describedby points at. The labels are LABELS cmp211.* (§10 L475); the look is E39's (§12 L544)."""
    _src("t2")
    ctl = [t2_button(it, reason, variant, shared=True) if isinstance(it, str) else dict(it) for it in items]
    row = hbox("buttons", ctl, {"gap": INSET_SM, "wrap": "wrap"}, w=w)
    return vbox(name or "CMP-211 PanicButtons (composition) · T2", [row, _reason_node(reason, w=w, **fills)],
                {"gap": INSET_XS}, w=w, note="2a with one reason line under the cluster (T2, §13 L602 (3), DJ)")


def validity_button(chars: str, hint: str, variant: str = "destructive", *, focused: bool = False,
                    name: str | None = None, **fills: Any) -> Node:
    """A control waiting on its own inputs: the validity form, never T2 (§13 L602; §12 L542-543): aria-disabled,
    focusable, no lock glyph, no CMP-079; the fill dropped to color.surface.raised with a 1 px color.border.default
    hairline and the label color.text.tertiary (the spec's DJ); its visible hint (dlg.choose_first, dlg.ack_first or
    dlg.token) under it in type.ui.caption color.text.tertiary is its aria-describedby; Enter or Space moves focus to
    the first unmet input (§13 L594). A column "validity · <chars>" holding "CMP-001 Button (composition) · <chars>
    (validity)" and "hint" (DEVIATIONS["validity"])."""
    if variant not in BUTTON_LOOK:
        raise ValueError(f"button variant {variant!r}: one of {sorted(BUTTON_LOOK)}")
    _fallback("CONTROL")
    _deviate("compose")
    _deviate("validity")
    _src("validity")
    why = copy(hint, **fills) if hint in COPY else hint
    kids = [text("label", chars, BODY_STRONG, T2_LABEL)]
    w = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    o = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "height": CONTROL_COMF, "justify": "center",
         "fill": T2_FILL, "stroke": T2_EDGE, "strokeWidth": HAIRLINE, "strokeAlign": "inner"}
    btn: Node = hbox(f"CMP-001 Button (composition) · {chars} (validity)", kids, o, w=w, h=CONTROL_H,
                     note=f"the validity form (§12 L542-543), not T2: aria-disabled, focusable, no lock, no CMP-079; "
                          f"variant {variant} once its inputs are met; Enter or Space moves focus to the first unmet "
                          "input; forced colours: the label GrayText (§15 L642)")
    if focused:
        btn = ring(btn)
    hint_n = text("hint", why, CAPTION, TEXT_3,
                  note="the visible hint for the first unmet condition, the confirm's aria-describedby (§12 L542; 5.20 "
                       "on overlay, §15 L661)")
    return vbox(name or f"validity · {chars}", [btn, hint_n], {"gap": INSET_XS, "align": "end"})


def busy_button(chars: str, variant: str = "primary", *, focused: bool = False, name: str | None = None) -> Node:
    """A busy CMP-001 (loading, 15:53; never T2, §13 L602): the spinner replaces the label at the label's width (no
    reflow; FALLBACKS["SPINNER"]), the variant's look kept, aria-busy="true", focusable and keeping focus, its name
    still chars (UD-4's Save §8 L390, I-3's Create invite, a rung confirm while its counts load §12 L542)."""
    if variant not in BUTTON_LOOK:
        raise ValueError(f"button variant {variant!r}: one of {sorted(BUTTON_LOOK)}")
    _fallback("CONTROL")
    _fallback("SPINNER")
    _deviate("compose")
    fill_, col, stroke = BUTTON_LOOK[variant]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "height": CONTROL_COMF,
                         "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIRLINE, strokeAlign="inner")
    w = round(text_w(chars, BODY_STRONG) + 2 * PX[BUTTON_PADX] + 2)
    btn = hbox(name or f"CMP-001 Button (composition) · {chars} (loading)", [icon("spinner", "refresh", col)], o, w=w,
               h=CONTROL_H, note=f'CMP-001 loading (15:53): aria-busy="true", focusable, named "{chars}"; never T2, '
                                 "never disabled (§13 L602)")
    return ring(btn) if focused else btn


def busy_icon_button(role: str, label_: str, *, focused: bool = False) -> Node:
    """U-7's busy CMP-002 trigger (§7 L340; never T2, §13 L602): it stays mounted with aria-busy="true" and a spinner
    in place of its glyph (FALLBACKS["SPINNER"]), focusable, named label_ (e.g. copy("users.disabling", user="alex"));
    focus returns to it when the dialog closes (05:97)."""
    _deviate("compose")
    _fallback("SPINNER")
    btn = hbox(f"CMP-002 IconButton (composition) · {role} (busy)", [icon("spinner", "refresh", TEXT_2)],
               {"justify": "center", "radius": R_CONTROL}, w=CONTROL_H, h=CONTROL_H,
               note=f'aria-busy="true", focusable, named "{label_}"; never T2 (§7 L340; §13 L602)')
    return ring(btn) if focused else btn


ROW_MENU = {  # §7 L322's row menu by status, in L330's order: (LABELS key, None = T1 | its T2 reason)
    "own": (("edit", None), ("reset_2fa", "admin.self.mfa"), ("view_as", "admin.self.view_as"),
            ("disable", "admin.self.account"), ("delete", "admin.self.account")),
    "owner": (("edit", None), ("reset_2fa", None), ("view_as", "admin.owner_target"), ("disable", None),
              ("delete", None)),
    "active": (("edit", None), ("reset_2fa", None), ("view_as", None), ("disable", None), ("delete", None)),
    "invited": (("edit", None), ("view_as", "admin.invite_pending"), ("disable", "admin.invite_pending"),
                ("delete", None)),  # no Reset two-factor: left out, not T2; users.mfa_pending states the fact (L322)
    "disabled": (("edit", None), ("reset_2fa", None), ("view_as", "admin.user_disabled"), ("enable", None),
                 ("delete", None)),
    "anonymised": (("edit", None), ("reset_2fa", None), ("view_as", "admin.user_disabled"), ("delete", None)),
}
ROW_MENU_KIND = {"locked_out": "active", "trading_locked": "active", "invite_expired": "invited",
                 "deletion_scheduled": "disabled"}  # a §1 user's chip kind -> its §7 L322 row


def row_menu_items(kind: str) -> list[str | tuple[str, str]]:
    """The SCR-121 row menu by status (§7 L322; items in L330's order) as menu() items: a T1 item is its label, a T2
    item (label, reason), whose reason menu() draws as its second line. kind: own (U-5), owner (V-10), active (also
    locked_out, trading_locked), invited (also invite_expired; Reset two-factor is left out, not T2, while the
    Two-factor cell's users.mfa_pending states the fact, §7 L322), disabled (Enable in place of Disable, U-9) or
    anonymised (a target: Enable dropped, U-9, CG-28), or a §1 user's chip kind."""
    row = ROW_MENU_KIND.get(kind, kind)
    if row not in ROW_MENU:
        raise ValueError(f"row menu kind {kind!r}: one of {sorted(ROW_MENU)} or a chip kind {sorted(ROW_MENU_KIND)}")
    _src("users")
    return [label(lk) if why is None else (label(lk), why) for lk, why in ROW_MENU[row]]


def link(chars: str, typo: str = BODY, color: str = TEXT_LINK, name: str | None = None) -> Node:
    """A CMP-021 Link composition: color.text.link (7.45 on the page, 6.66 on raised, §15 L650, L653)."""
    _deviate("link")
    return text(name or "CMP-021 Link (composition)", chars, typo, color)


def marker(label_: str, code: str | None = None) -> Node:
    """The CMP-093 audit marker "Recorded in the audit log · <label> (<code>)" (§1 L92; type.ui.caption, tertiary);
    code=None draws the label alone (a cap write has no registered code, CG-15)."""
    s = fill(MARKER, label=label_, code=code) if code else f"Recorded in the audit log · {label_}"
    if not code:
        LOG.add("copy_gaps", f"marker without a code: '{s}' (CG-15, §8 L416)")
    return text("CMP-093 marker", s, CAPTION, TEXT_3)


CHIP_LOOK = {  # §7 L307-311 glyphs, §15 L657-658 fills and glyph colours; anonymised: U-9 L342 (the Disabled tone)
    "active": ("success", "check"), "invited": ("info", "ring"), "invite_expired": ("warning", "triangle"),
    "disabled": ("neutral", "slashed-circle"), "locked_out": ("warning", "triangle"),
    "trading_locked": ("danger", "octagon"), "deletion_scheduled": ("neutral", "slashed-circle"),
    "anonymised": ("neutral", "slashed-circle"),
}


def chip(kind: str, until: bool = True, **fills: Any) -> Node:
    """A user status chip (CMP-011 composition, text + glyph + tone; §7 L307-311): Active (check), Invited (ring),
    Invite expired (triangle), Disabled (slashed circle), Locked out (triangle; until=False drops the time no read
    serves, CG-12), Trading locked (octagon; a target, CG-13), deletion scheduled (a target, CG-28), anonymised
    (users.anonymised "Anonymised on {yyyy-mm-dd}": the slashed circle in the Disabled chip's tone, a target once
    anonymised_at is served, U-9 L342, CG-28)."""
    if kind not in CHIP_LOOK:
        raise ValueError(f"chip kind {kind!r}: one of {sorted(CHIP_LOOK)}")
    _src("users")
    tone, kind_g = CHIP_LOOK[kind]
    fill_ = TONES[tone][0]
    gcol = TONES[tone][2] if kind_g != "ring" else INFO_STRONG
    if kind == "anonymised":
        words = copy("users.anonymised", **fills)
    elif until or kind != "locked_out":
        words = copy(f"chip.{kind}", **fills)
    else:  # §7 L309-310: "Locked out (sign-in)" alone until the until-time is served (CG-12)
        LOG.add("copy_keys", "chip.locked_out")
        words = str(COPY["chip.locked_out"]).split(" · ")[0]
    note = {"locked_out": None if until else "CG-12: no until-time is served yet (§7 L309-310)",
            "trading_locked": "a target state (CG-13)", "deletion_scheduled": "a target (CG-28)",
            "anonymised": "a target once User serves anonymised_at (U-9 L342, CG-28; #960 Q13): never T2"}.get(kind)
    return hbox(f"CMP-011 Tag (composition) · {kind}", [glyph(kind_g, gcol), text("label", words, LABEL, TEXT_1)],
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_BADGE, "fill": fill_}, h=CHIP_H, note=note)


def tag(chars: str, tone: str = "neutral", glyph_kind: str | None = None, name: str | None = None) -> Node:
    """A generic CMP-011 Tag composition: the tone's .subtle fill (§15 L657), the text in color.text.primary
    (type.ui.label) and, by default, the tone's glyph (never colour alone; glyph_kind="" drops it)."""
    if tone not in TONES:
        raise ValueError(f"tag tone: one of {sorted(TONES)}")
    fill_, kind, gcol = TONES[tone]
    g = glyph_kind if glyph_kind is not None else kind
    kids = ([glyph(g, gcol)] if g else []) + [text("label", chars, LABEL, TEXT_1)]
    return hbox(name or f"CMP-011 Tag (composition) · {tone}", kids,
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_BADGE, "fill": fill_}, h=CHIP_H)


def user_chip(username: str, until: bool = True) -> Node:
    """The §7 L335 status chip of a §1 user (fills from USERS)."""
    u = USER[username]
    return chip(u.chip, until, **u.fills)


def empty_state(chars: str, action: Node | None = None, w: int | None = None) -> Node:
    """A CMP-026 EmptyState composition: the sentence (type.ui.body, color.text.primary) and its action, centred."""
    _deviate("compose")
    return vbox("CMP-026 EmptyState (composition)", [text("text", chars, BODY, TEXT_1)] + ([action] if action else []),
                {"align": "center", "gap": STACK_MD, "padY": INSET_XL}, w=w)


def error_state(chars: str, w: int | None = None, name: str | None = None) -> Node:
    """A CMP-027 panel error: the octagon, the sentence and its [Retry] / [Reload] as a secondary button."""
    words, acts, _env = split_actions(chars)
    kids = [glyph("octagon", DANGER_STRONG), text("text", words, BODY, TEXT_1)] + [button(a) for a in acts]
    return hbox(name or "CMP-027 ErrorState (composition)", kids, {"gap": INSET_SM}, w=w)


def inline_error(chars: str, w: int | None = None) -> Node:
    """A CMP-027 field error: color.text.primary on color.status.danger.subtle with the octagon (D02:724: danger.strong
    fails as error text in light)."""
    return hbox("CMP-027 inline error (composition)", [glyph("octagon", DANGER_STRONG),
                                                       text("text", chars, CAPTION, TEXT_1)],
                {"gap": INSET_XS, "padX": INSET_SM, "padY": INSET_XS, "radius": R_CONTROL, "fill": DANGER_SUBTLE}, w=w)


# --- SCR-120 / SCR-121 content parts (§6, §7, §15 L653-659, Appendix A L892-901).
TILE_TONE = {"ok": ("check", OK_STRONG), "warning": ("triangle", WARN_STRONG), "danger": ("octagon", DANGER_STRONG),
             "stale": ("clock", STALE_IND)}  # one glyph shape per tone (Appendix A L894)
BUTTON_ACTIONS = ("Retry", "Reload", "Re-issue", "Retry the rest")  # bracketed actions drawn as secondary buttons


def action(chars: str) -> Node:
    """A control named inside a copy string ("[Retry]", "[Change]"): Retry / Reload / Re-issue as a secondary
    CMP-001, the rest (Change, Record tier, Clear filters) as a CMP-021 link (kit choice: §14 gives only the words)."""
    return button(chars) if chars in BUTTON_ACTIONS else link(chars, name=f"CMP-021 Link (composition) · {chars}")


def pair(name: str, label_: str, value: str, numeric: bool = False) -> Node:
    """A tile line as label + value: the label color.text.secondary, the value color.text.primary (type.num.base for a
    count or clock, §6 L288); e.g. pair("live", "Live trading:", "on")."""
    val = text("value", value, NUM_BASE if numeric else BODY, TEXT_1)
    return hbox(name, [text("label", label_, BODY, TEXT_2), val], {"gap": INSET_XS})


def tile(heading: str, lines: Iterable[str | Node] = (), *, px: int = 1280, col: int = 0, state: str = "ready",
         tone: str | None = None, status: str | None = None, env: str | None = None, asof: str | None = None,
         last_good: str | None = None, controls: Iterable[Node] = (), h: int | None = None) -> Node:
    """A CMP-178 tile on CMP-050 (role="region" labelled by its heading, the CMP-021 link, §6 L254-257): raised,
    radius.card, space.inset.lg; the heading (+ env badge); loading = a CMP-015 skeleton; otherwise the status line
    (tone glyph + status text, e.g. copy("tile.unavailable", detail=…)), the lines (strings or pair() nodes), "as of"
    and "last good" in tertiary caption, the controls (Retry, Run tamper check). Width: SIZES[px].tiles[col]."""
    _src("overview")
    w = SIZES[px].tiles[col]
    inner = w - 2 * PX[INSET_LG]
    head = [link(heading, HEADING_SM, name="heading")] + ([env_badge(env)] if env else [])
    kids: list[Node] = [hbox("header", head, {"gap": INSET_SM})]
    if state == "loading":
        kids.append(skeleton("text", 3, inner))
    else:
        if status:
            g_kind, g_col = TILE_TONE[tone or "ok"]
            words, acts, _e = split_actions(status)
            kids.append(hbox("status", [glyph(g_kind, g_col), text("text", words, BODY_STRONG, TEXT_1, w=inner - 24)],
                             {"gap": INSET_XS, "align": "start"}))
            controls = [action(a) for a in acts] + list(controls)
        for i, ln in enumerate(lines, 1):
            kids.append(text(f"line-{i}", ln, BODY, TEXT_1, w=inner) if isinstance(ln, str)
                        else dict(ln, name=f"line-{i}"))
        stamps = [s for s in (asof, last_good) if s]
        if stamps:
            kids.append(text("as of", " · ".join(stamps), CAPTION, TEXT_3))
        ctl = list(controls)
        if ctl:
            kids.append(hbox("controls", ctl, {"gap": INSET_SM}))
    return vbox(f"CMP-178 tile (composition) · {heading}", kids,
                {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG, "gap": STACK_SM}, w=w, h=h,
                note='role="region" aria-labelledby its heading (the link); no number for a field not received')


def tile_band(h2: str, tiles: Iterable[Node], px: int = 1280, h: int | None = None) -> Node:
    """One SCR-120 band: its h2 and three tiles in a row with space.3 gaps; its tiles share one height (§6 L257)."""
    _fallback("STEP")
    ts = [dict(t, h=h) if h else t for t in tiles]
    row = hbox("tiles", ts, {"gap": STEP, "align": "start"})
    return vbox(f"band · {h2}", [text("h2", h2, HEADING_SM, TEXT_2), row], {"gap": STACK_SM}, w=SIZES[px].inner)


METER_FILL = {"normal": ACTION_PRIMARY, "near": WARN_STRONG, "breached": DANGER_STRONG, "tightened": DANGER_STRONG}


def meter(used: float, cap: float, w: int = 120, state: str = "normal", valuetext: str | None = None) -> Node:
    """A CMP-023 meter composition, 8 px: the color.surface.hover track and the fill (action.primary.default; near
    warning.strong; breached / tightened danger.strong; §15 L659, Appendix A L899); the aria-valuetext in its note."""
    fw = round(w * max(0.0, min(used / cap, 1.0))) if cap else 0
    kids = [rect("track", w, 8, HOVER, {"radius": R_BADGE}, x=0, y=0)]
    if fw:
        kids.append(rect("fill", fw, 8, METER_FILL[state], {"radius": R_BADGE}, x=0, y=0))
    return box("CMP-023 meter (composition)", kids, None, w=w, h=8,
               note=f"role=meter; aria-valuetext \"{valuetext}\"" if valuetext else "role=meter")


CAP_STATES = ("recorded", "unrecorded", "tier_unavailable", "used_unavailable", "down", "at_capacity", "over")


def capacity_line(state: str = "recorded", used: int = 3, cap: int = 5, tier: str = "Regular",
                  date: str = "2026-09-12", px: int = 1280) -> Node:
    """SCR-121's capacity line (§7 L312-317, D10-D12): a CMP-023 meter only when used and cap were both read and the
    tier is recorded, its §14 cap.* text and its action; at_capacity adds the triangle and cap.at_capacity's two
    sentences; over draws D12 (no meter: a bar cannot show 6 of 5). Defaults: §1's 3 used, Regular, recorded
    2026-09-12."""
    if state not in CAP_STATES:
        raise ValueError(f"capacity state {state!r}: one of {CAP_STATES}")
    _src("users")
    key = {"at_capacity": "cap.recorded"}.get(state, f"cap.{state}")
    s = copy(key, used=used, cap=cap, tier=tier, date=date) if "{" in str(COPY[key]) else copy(key)
    words, acts, _e = split_actions(s)
    kids: list[Node] = []
    if state in ("recorded", "at_capacity"):
        vt = copy("cap.valuetext", used=used, cap=cap)
        kids.append(meter(used, cap, 120, "near" if state == "at_capacity" else "normal", vt))
    if state == "at_capacity":
        kids.append(glyph("triangle", WARN_STRONG))
    if state == "over":
        _deviate("over", "The over-cap line (D12) draws no meter: a bar cannot show more than its cap (kit choice).")
    kids += [text("text", words, BODY, TEXT_1)] + [action(a) for a in acts]
    line = hbox("line", kids, {"gap": INSET_SM})
    rows = [line]
    if state == "at_capacity":
        rows.append(text("at capacity", copy("cap.at_capacity", cap=cap, used=used), BODY, TEXT_2,
                         w=SIZES[px].inner - 32))
    return vbox(f"capacity line · {state}", rows, {"gap": STACK_XS}, w=SIZES[px].inner,
                note="CMP-023 + its text + its action, above the grid so it stays in view (§7 L297-298)")


def audit_row(time: str, actor: str, action_label: str, code: str, subject: str, outcome: str, severity: str) -> Node:
    """A CMP-173 compact row (Appendix A L888-890): time UTC (type.num.sm), actor, action label and code, subject,
    outcome and severity as words. The spec gives no entry data: pass strings with their source (a copy gap)."""
    kids = [text("time", time, NUM_SM, TEXT_2), text("actor", actor, BODY, TEXT_1),
            text("action", f"{action_label} ({code})", BODY, TEXT_1), text("subject", subject, BODY, TEXT_2),
            text("outcome", f"{outcome} · {severity}", CAPTION, TEXT_2)]
    return hbox("CMP-173 AuditRow compact (composition)", kids, {"gap": INSET_SM, "height": ROW_COMF}, h=ROW_H,
                note="links to SCR-136")


SKELETONS = {("text", "1"), ("row", "1"), ("card", "1"), ("chart", "1"), ("text", "3")}  # inventory variants


def skeleton(shape: str = "text", count: int = 1, w: int | None = None, h: int | None = None) -> Node:
    """A CMP-015 Skeleton instance (static two-tone under reduced motion, §13 L599); verified live."""
    if (shape, str(count)) not in SKELETONS:
        raise ValueError(f"CMP-015 has no variant Shape={shape} Count={count}")
    return inst(f"CMP-015 Skeleton · {shape} ×{count}", "CMP-015 · Skeleton",
                {"State": "default", "Shape": shape, "Count": str(count)}, w=w, h=h)


def tooltip(chars: str, **place: Any) -> Node:
    """A CMP-016 Tooltip instance with its content (e.g. D13's account list behind "2 accounts"); verified live."""
    return inst("CMP-016 Tooltip", "CMP-016 · Tooltip", {"State": "default"}, {"content": chars}, **place)


# --- Tables, menus and form parts (CMP-049, CMP-041, CMP-040/201/204/007 compositions; §7, §12, §15 L655, L661-663).
class Col(NamedTuple):
    """One grid column: id, header copy, width in px, alignment ("start" | "end"), sortable."""

    id: str
    header: str
    width: int
    align: str = "start"
    sortable: bool = False


def scr121_cols(px: int = 1280) -> tuple[Col, ...]:
    """SCR-121's named columns (§7 L300-304): User, Role, Accounts, Two-factor, Last sign-in, Status and the row menu,
    with kit widths (no source sets them) summing to the 944 / 2048 px grid; the four sortable ones flagged."""
    _deviate("cols", "SCR-121 column widths are the kit's proportions (no source sets them); Accounts shortens "
                     "first at 1280 (D13).")
    share = (("user", "col.user", .19, True), ("role", "col.role", .11, True), ("accounts", "col.accounts", .19, False),
             ("two_factor", "col.two_factor", .11, False), ("last", "col.last_sign_in", .15, True),
             ("status", "col.status", .21, True))
    inner = SIZES[px].inner - 48  # the row menu column is 48 px (a 32 px target + padding)
    cols = [Col(i, label(k), int(inner * f), "start", s) for i, k, f, s in share]
    cols[-1] = cols[-1]._replace(width=inner - sum(c.width for c in cols[:-1]))
    return (*cols, Col("menu", "", 48, "end"))


SORT_ARIA = {"asc": "ascending", "desc": "descending"}


def table_header(cols: Iterable[Col], sort: tuple[str, str] | None = None, name: str = "header", *,
                 sort_pending: str | None = None, sort_cleared: str | None = None, focus: str | None = None,
                 t2_reason: str | None = None, **fills: Any) -> Node:
    """The CMP-049 header row (comfortable 32 px): color.surface.hover, headers type.ui.label in color.text.secondary
    (7.50), the sort glyph in color.text.tertiary (4.79) on the sorted column; aria-sort noted (§15 L655, §7 L304).
    sort_pending= a sortable column id (CMP-049 sortPending, §16 L692, Appendix A L908-909): its header was pressed
    while has_more and reads the remaining pages first (§7 L305): its label and aria-sort kept (sort= gives the kept
    direction, else none), a spinner in place of its sort glyph (FALLBACKS["SPINNER"], color.text.tertiary like the
    glyph, 4.79 on hover, §15 L655), aria-busy="true", focusable and keeping focus, arrow-reachable; pressing it again
    changes nothing; users.sorting is announced polite once (recorded); never T2: an availability state (§13 L602).
    sort_cleared= the column whose sort read failed: no glyph, aria-sort none until a Retry completes the read, while
    users.error [Retry] sits under the rows read so far, in the server's order (§7 L305). focus= a column id gets the
    inner 2 px ring (as table_row's focus=). t2_reason= is the gate fold's T2 sort-header form, kept for old calls only
    and flagged as a deviation: the merged spec has no T2 header (a removed key such as admin.sort_needs_all raises)."""
    cl = list(cols)
    gated = t2_reason is not None
    ids = {c.id for c in cl if c.sortable}
    for arg, val in (("sort_pending", sort_pending), ("sort_cleared", sort_cleared)):
        if val is not None and val not in ids:
            raise ValueError(f"table_header {arg}={val!r}: one of the sortable columns {sorted(ids)}")
    if sort_pending and sort_cleared:
        raise ValueError("table_header: sort_pending and sort_cleared are two moments of one read, not one header")
    if sort_cleared and sort and sort[0] == sort_cleared:
        raise ValueError("table_header: a cleared sort has no direction (aria-sort none, §7 L305); drop sort=")
    if gated:
        _deviate("t2-sort", "kit: table_header(t2_reason=) draws the gate fold's T2 sort headers, which the merge "
                            "removed (§7 L304-305: an availability state, never T2, §13 L602): redraw with "
                            "sort_pending=")
    if sort_pending or sort_cleared:
        _src("sort")
    if sort_pending:
        _fallback("SPINNER")
    kids = []
    for c in cl:
        ck: list[Node] = []
        if c.header:
            ck = ([lock_glyph(), text("label", c.header, LABEL, T2_LABEL)] if gated and c.sortable else
                  [text("label", c.header, LABEL, TEXT_2)])
        note = None
        if c.id == sort_pending:
            kept = SORT_ARIA[sort[1]] if sort and sort[0] == c.id else "none"
            ck.append(icon("spinner", "refresh", TEXT_3))
            note = (f'CMP-049 sortPending="{c.id}" (§16 L692; Appendix A L908-909): pressed while has_more, it reads the '
                    f"remaining pages first (§7 L305): its label and aria-sort kept (aria-sort {kept}), a spinner in "
                    'place of its sort glyph (color.text.tertiary, 4.79 on hover, §15 L655), aria-busy="true", '
                    "focusable, focus kept, arrow-reachable (D09:231); pressing it again changes nothing; "
                    f'users.sorting "{copy("users.sorting")}" polite once (§13 L592); then it sorts and Load more goes; '
                    "never T2: an availability state (§13 L602)")
        elif c.id == sort_cleared:
            note = ("aria-sort none: the failed read cleared this header's glyph and aria-sort until a Retry completes "
                    "the read; the rows read so far stay, in the server's order, with users.error [Retry] under them "
                    "(§7 L305); not busy, never T2 (§13 L602)")
        elif sort and sort[0] == c.id:
            ck.append(icon("sort", "arrow-down" if sort[1] == "desc" else "arrow-up", TEXT_3))
            note = f"aria-sort {SORT_ARIA[sort[1]]}"
        if gated and c.sortable:
            note = ((note + "; ") if note else "") + (
                "T2 header button: aria-disabled, arrow-reachable, aria-describedby the one reason line above the "
                f"header row; {_carrier(t2_reason, 'CMP-001')} (T2, §13 L602 (3); Appendix A L909)")
        o = {"gap": INSET_XS, "padX": INSET_SM, **({"justify": "end"} if c.align == "end" else {})}
        if focus == c.id:
            o.update(stroke=FOCUS_RING, strokeWidth=FOCUS_W, strokeAlign="inner")
            note = ((note + "; ") if note else "") + "focused (the inner 2 px ring)"
        kids.append(hbox(c.id, ck, o, w=c.width, h=ROW_H, note=note))
    row = hbox(name, kids, {"fill": HOVER, "height": ROW_COMF}, h=ROW_H)
    if not gated:
        return row
    _deviate("t2")
    reason = _reason_node(str(t2_reason), w=sum(c.width for c in cl), **fills)
    return vbox(f"{name} (T2)", [dict(reason, note="one node for the four sort headers (E09-D09 §9.2), above the "
                                                   "header row; each header's aria-describedby (T2, §13 L602 (3))"),
                                 row], {"gap": STACK_XS})


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node]], name: str, selected: bool = False,
              focus: str | None = None, fill: str | None = RAISED) -> Node:
    """One CMP-049 grid row at 32 px (space.row.height.comfortable) on color.surface.raised with a 1 px
    color.border.subtle divider; a cell is a string (type.ui.body, primary), a node or a list of nodes; selected = the
    color.surface.selected row with primary text (10.17); focus= a column id gets the inner 2 px ring."""
    cl = list(cols)
    kids, x = [], 0
    for c in cl:
        v = cells.get(c.id)
        ck = [] if v is None else [text("value", v, BODY, TEXT_1)] if isinstance(v, str) else (
            [dict(n) for n in v] if isinstance(v, list) else [dict(v)])
        o: dict[str, Any] = {"gap": INSET_XS, "padX": INSET_SM, **({"justify": "end"} if c.align == "end" else {})}
        if focus == c.id:
            o.update(stroke=FOCUS_RING, strokeWidth=FOCUS_W, strokeAlign="inner")
        kids.append(hbox(c.id, ck, o, w=c.width, h=ROW_H))
        x += c.width
    kids.append(_divider("divider", x, 1, 0, ROW_H - 1))
    f = SELECTED if selected else fill
    return hbox(name, kids, {"height": ROW_COMF, **({"fill": f} if f else {})}, w=x, h=ROW_H,
                note="the selected / focused row" if selected else None)


def menu(items: Iterable[str | tuple[str, str]], w: int = 240, name: str = "CMP-041 Menu (composition)", *,
         focus: int | None = None, **place: Any) -> Node:
    """A CMP-041 menu (overlay, elevation.popover, radius.card, 1 px color.border.default): an item is a label, "-" (a
    divider) or (label, reason) for a T2 item (T2, §13 L602; §7 L322): it stays a menu item, aria-disabled and
    arrow-reachable, the lock leading its full label in color.text.tertiary, the reason its second line
    (type.ui.caption, color.text.secondary) and its aria-describedby. focus= the 1-based position of the focused item
    (a divider counts), drawn on color.surface.hover, T2 or not (§15 L656, DJ; never on selected, F4)."""
    _deviate("compose")
    kids: list[Node] = []
    inner = w - 2 * PX[INSET_XS]
    for i, it in enumerate(items, 1):
        hi = {"fill": T2_FOCUS_FILL} if focus == i else {}
        if it == "-":
            kids.append(rect(f"divider-{i:02d}", inner, 1, BORDER_SUBTLE))
        elif isinstance(it, str):
            kids.append(hbox(f"item-{i:02d}", [text("label", it, BODY, TEXT_1)], {"padX": INSET_SM,
                                                                                  "height": CONTROL_COMF, **hi},
                             w=inner, h=CONTROL_H, note="focused (color.surface.hover)" if hi else None))
        else:
            lab, why = it
            _deviate("t2")
            words = vbox("words", [text("label", lab, BODY, T2_LABEL),
                                   _reason_node(why, w=inner - 36)])
            kids.append(hbox(f"item-{i:02d}", [lock_glyph(), words],
                             {"align": "start", "gap": INSET_XS, "padX": INSET_SM, "padY": INSET_XS, **hi}, w=inner,
                             note=f"T2 menu item, {_carrier(why, 'CMP-041')}: aria-disabled, arrow-reachable; the "
                                  "reason its second line and aria-describedby; Enter changes nothing and re-shows it "
                                  "(T2, §13 L602 (3), (6))" + ("; focused (color.surface.hover)" if hi else "")))
    o = {"fill": OVERLAY, "shadow": E_POPOVER, "radius": R_CARD, "stroke": BORDER_DEFAULT, "strokeWidth": HAIRLINE,
         "pad": INSET_XS}
    return vbox(name, kids, o, w=w, **place)


def fieldset(legend: str, kids: Iterable[Node], w: int, name: str | None = None) -> Node:
    """A <fieldset> card (SCR-122's sections): raised, radius.card, space.inset.lg, the legend type.ui.heading-sm."""
    return vbox(name or f"fieldset · {legend}", [text("legend", legend, HEADING_SM, TEXT_1), *kids],
                {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG, "gap": STACK_SM}, w=w)


PASSWORD_MASK = "••••••••"  # a typed password as the field draws it (not copy)


def field(label_: str, value: str | None = None, *, w: int = 320, hint: str | None = None, error: str | None = None,
          focused: bool = False, locked: bool = False, mono: bool = False, name: str | None = None) -> Node:
    """A labelled text field (CMP-040 label + CMP-007 / CMP-201 / CMP-204 composition): label type.ui.label secondary,
    the well color.surface.sunken (17.42) with the DS-3 boundary color.text.tertiary (1 px; 2 px focus ring when
    focused), the value primary (type.num.base when mono), the hint tertiary caption and the CMP-027 inline error."""
    _fallback("DS-3")
    _deviate("compose")
    val = [text("value", value, NUM_BASE if mono else BODY, TEXT_3 if locked else TEXT_1)] if value else []
    o = {"padX": INSET_SM, "radius": R_CONTROL, "fill": SUNKEN, "height": CONTROL_COMF, "stroke": FIELD_EDGE,
         "strokeWidth": HAIRLINE, "strokeAlign": "inner"}
    well = hbox("input", val, o, w=w, h=CONTROL_H, note="locked: aria-busy" if locked else None)
    kids = [text("label", label_, LABEL, TEXT_2), ring(well) if focused else well]
    if hint:
        kids.append(text("hint", hint, CAPTION, TEXT_3, note="aria-describedby"))
    if error:
        kids.append(inline_error(error))
    return vbox(name or f"field · {label_}", kids, {"gap": STACK_XS}, w=w + (8 if focused else 0))


def radio(label_: str, body: str | None = None, *, checked: bool = False, t2_reason: str | None = None,
          focused: bool = False, w: int = 560, name: str | None = None) -> Node:
    """A radio option of the §12 two-choice block (CMP-006 composition): an unchecked ring in color.text.tertiary
    (checked: action.primary.default with a color.text.on-action dot), the bold label and its body (secondary). A T2
    option (t2_reason, e.g. choice B under D21, "admin.needs_count", §12 L570) keeps role="radio" and is focused, never
    checked: the lock leads its full label (both color.text.tertiary), its reason is its second line
    (type.ui.caption, color.text.secondary, aria-describedby), then the body (T2, §13 L602; §16 L691; App. A L903)."""
    _deviate("compose")
    if checked:
        dot = box("dot", [ellipse("fill", 16, 16, {"fill": ACTION_PRIMARY}, x=0, y=0),
                          ellipse("dot", 6, 6, {"fill": TEXT_ON_ACTION}, x=5, y=5)], None, w=16, h=16)
    else:
        dot = box("ring", [ellipse("ring", 16, 16, {"stroke": TEXT_3, "strokeWidth": HAIRLINE}, x=0, y=0)], None,
                  w=16, h=16)
    gated = t2_reason is not None
    if gated:
        _deviate("t2")
        lead = hbox("label row", [lock_glyph(), text("label", label_, BODY_STRONG, T2_LABEL, w=w - 48 - 20)],
                    {"gap": INSET_XS, "align": "start"})
        words: list[Node] = [lead, _reason_node(str(t2_reason), w=w - 48)]
    else:
        words = [text("label", label_, BODY_STRONG, TEXT_1, w=w - 48)]
    if body:
        words.append(text("body", body, BODY, TEXT_2, w=w - 48))
    opt = hbox(name or "option", [dot, vbox("words", words, {"gap": STACK_XS})],
               {"gap": INSET_SM, "align": "start", "padY": INSET_XS}, w=w,
               note=(f"T2 option, {_carrier(t2_reason, 'CMP-044')}: role=radio, aria-disabled; an arrow focuses it "
                     "without checking it, Space never checks it and re-shows its reason (§12 L564-566; T2, §13 "
                     "L602 (6))" if gated else
                     "checked" if checked else "unchecked: none pre-selected (§12 L556)"))
    return ring(opt) if focused else opt


def tick(label_: str, *, checked: bool = False, w: int = 560, focused: bool = False, name: str | None = None) -> Node:
    """The acknowledgement tick (CMP-005 composition, D21): a 16 px box (tertiary 1 px outline; checked:
    action.primary.default with the on-action check) and its wrapping label in color.text.primary."""
    _deviate("compose")
    if checked:
        bx = hbox("box", [icon("check", "check", TEXT_ON_ACTION, ICON)], {"justify": "center", "radius": R_CONTROL,
                                                                          "fill": ACTION_PRIMARY}, w=16, h=16)
    else:
        bx = box("box", [], {"radius": R_CONTROL, "stroke": TEXT_3, "strokeWidth": HAIRLINE, "strokeAlign": "inner"},
                 w=16, h=16)
    t = hbox(name or "CMP-005 tick (composition)", [bx, text("label", label_, BODY, TEXT_1, w=w - 28)],
             {"gap": INSET_SM, "align": "start"}, w=w, note="checked" if checked else "unchecked")
    return ring(t) if focused else t


def env_text(name: str, chars: str, typo: str, color: str, w: int) -> Node:
    """A copy string carrying "[LIVE]" / "[DEMO]" (unbind.lead, unbind.unknown): the text with the CMP-012 badge where
    the token stands; the rest wraps at w. No token: one wrapping text."""
    m = re.search(r"\s*\[(LIVE|DEMO)\]\s*", chars)
    if not m:
        return text(name, chars, typo, color, w=w)
    head, tail = chars[:m.start()], chars[m.end():]
    bdg = env_badge(m.group(1))
    first = text("head", head, typo, color) if head.strip() else None
    rest_w = max(round(w - (text_w(head, typo) if first else 0) - est_width(bdg) - 2 * PX[INSET_XS]), 120)
    kids = [k for k in (first, bdg, text("tail", tail, typo, color, w=rest_w)) if k]
    return hbox(name, kids, {"gap": INSET_XS, "align": "start"}, w=w, note=f'copy: "{chars}"')


def dialog(title: str, kids: Iterable[Node], actions: Iterable[Node] = (), size: str = "large",
           name: str | None = None, role: str = "alertdialog") -> Node:
    """A CMP-043 dialog composition: color.surface.overlay, radius.dialog, elevation.dialog, space.dialog.padding,
    space.stack.md between parts; the title an h2 (type.ui.heading-md, primary 13.27); actions right-aligned (Cancel
    first). size "default" 480 / "large" 640 px (DEVIATIONS["dialog-w"])."""
    _deviate("dialog-w")
    _deviate("compose")
    w = DIALOG_W[size]
    body = [text("title", title, HEADING_MD, TEXT_1, w=w - 2 * PX[DIALOG_PAD], note="h2; the dialog's name"), *kids]
    acts = list(actions)
    if acts:
        body.append(hbox("actions", acts, {"gap": INSET_SM, "justify": "end", "align": "start"},
                         w=w - 2 * PX[DIALOG_PAD]))
    return vbox(name or f"CMP-043 Dialog (composition) · {size}", body,
                {"fill": OVERLAY, "radius": R_DIALOG, "shadow": E_DIALOG, "pad": DIALOG_PAD, "gap": STACK_MD}, w=w,
                note=f'role="{role}"; focus trapped; Esc cancels; the first sentence is the description')


CONFIRM_STATES = ("enabled", "choose_first", "ack_first", "token", "loading")
CONFIRM_HINT = {"choose_first": "dlg.choose_first", "ack_first": "dlg.ack_first", "token": "dlg.token"}  # §12 L542-543


def rung_dialog(rung: int, title: str, *, consequences: Iterable[str] = (), blast: Iterable[Node] = (),
                choices: Node | None = None, ack: Node | None = None, token: Node | None = None,
                why: Node | None = None, step_up: str | None = "code", step_cls: str = "users", grace_s: int = 134,
                marker_: tuple[str, str | None] | None = None, confirm: str = "", confirm_state: str = "enabled",
                cancel_focused: bool = True, extra: Iterable[Node] = (), size: str = "large") -> Node:
    """A CMP-044 ladder dialog in §12's locked order (L533-537): title · consequences · blast radius · [two-choice
    block] · [tick] · [typed token] · [Why] · the step-up line (dlg.step_up.code / .grace, or None) · the marker ·
    [Cancel] (focused) [confirm]. The confirm (§12 L536-537, L541-543): "enabled" color.text.primary on danger.subtle
    with a danger.strong border; "choose_first" / "ack_first" / "token" (a choice, the tick or the typed username still
    missing) the validity form with its hint dlg.choose_first / dlg.ack_first / dlg.token (validity_button: never T2,
    no lock); "loading" (the counts not yet answered) CMP-001 loading (busy_button)."""
    if rung not in (1, 2, 3):
        raise ValueError("rung_dialog: rungs 1-3 (0 and 4 are not drawn here, §12 L544)")
    if confirm_state not in CONFIRM_STATES:
        raise ValueError(f"confirm_state: one of {CONFIRM_STATES}")
    if not confirm:
        raise ValueError("rung_dialog: confirm= is the '<Verb> <object>' label (§12 L535)")
    _src("ladder")
    iw = DIALOG_W[size] - 2 * PX[DIALOG_PAD]
    kids: list[Node] = [text(f"consequence-{i}", c, BODY, TEXT_1, w=iw) for i, c in enumerate(consequences, 1)]
    kids += list(blast) + [k for k in (choices, ack, token, why) if k] + list(extra)
    if step_up == "code":
        kids.append(text("step-up line", copy("dlg.step_up.code"), CAPTION, TEXT_2))
    elif step_up == "grace":
        kids.append(clock_text("step-up line", copy("dlg.step_up.grace", cls=copy(f"band.grace.class.{step_cls}"),
                                                    mss=mss(grace_s)), CAPTION, TEXT_2, num=NUM_SM))
    if marker_:
        kids.append(marker(*marker_))
    cancel = button(label("cancel"), "secondary", focused=cancel_focused)
    if confirm_state == "enabled":
        conf = button(confirm, "destructive")
    elif confirm_state == "loading":
        conf = dict(busy_button(confirm, "destructive"),
                    note='the counts not yet answered: CMP-001 loading, aria-busy="true", focusable, never T2 (§12 '
                         "L542)")
    else:
        conf = validity_button(confirm, CONFIRM_HINT[confirm_state], "destructive")
    return dialog(title, kids, [cancel, conf], size, name=f"CMP-044 rung-{rung} dialog (composition)")


def drawer(title: str, kids: Iterable[Node], px: int = 1280, w: int = DRAWER_W) -> Node:
    """A CMP-046 drawer composition at the frame's right edge under the TopBar (absolute): overlay, elevation.popover,
    space.inset.lg, the title (type.ui.heading-md) and a close button (DRAWER_W is a kit width)."""
    g = SIZES[px]
    _deviate("drawer", "The CMP-046 drawer is 400 px wide (kit choice: no source gives its width).")
    head = hbox("header", [text("title", title, HEADING_MD, TEXT_1), icon_button("close", "close")],
                {"justify": "space-between"}, w=w - 2 * PX[INSET_LG])
    return vbox("CMP-046 Drawer (composition)", [head, *kids], {"fill": OVERLAY, "shadow": E_POPOVER, "pad": INSET_LG,
                                                                "gap": STACK_MD, "clip": True},
                w=w, h=g.h - g.top - g.status, x=g.w - w, y=g.top, abs=True, note="focus on its heading; Esc closes")


# --- The annotation column (build notes: title, source line, state id and trigger, decision ids, roles, keyboard path
# and focus, announcement, copy keys used, tokens, analytics/audit event, footer).
ANN_ORDER = (("source", "Source"), ("state", "State and trigger"), ("decisions", "Decision ids"), ("roles", "Roles"),
             ("keyboard", "Keyboard path and focus"), ("announcement", "Announcement (text, region, when)"),
             ("copy", "Copy keys used"), ("tokens", "Tokens"), ("events", "Analytics and audit events"))


def tokens_line(tokens: Iterable[str] | None = None) -> str:
    """The tokens recorded so far (or given), grouped: "colour: surface.app, …; type: …; space: …; size: …; …"."""
    groups: dict[str, list[str]] = {}
    for t in sorted(set(LOG.notes["tokens"] if tokens is None else tokens)):
        head, _dot, rest = t.partition(".")
        key = {"color": "colour", "type": "type", "space": "space", "size": "size", "radius": "radius"}.get(
            head, "other")
        groups.setdefault(key, []).append(rest if key != "other" else t)
    order = ("colour", "type", "space", "size", "radius", "other")
    return "; ".join(f"{g}: {', '.join(groups[g])}" for g in order if g in groups)


def annotations(nn: int, title: str, blocks: dict[str, Any] | Iterable[tuple[str, Any]], rev: str = REV) -> Node:
    """The 400 px annotation column: the title (type.ui.heading-sm), labelled blocks in build-notes order (keys of
    ANN_ORDER; other labels follow "events"), "copy" defaulting to the copy keys recorded and "tokens" to the tokens
    recorded plus every fallback line, then the footer "page E42-D03 · board NN · rN" (§0 L50). Build it last."""
    _src("boards")
    labels = dict(ANN_ORDER)
    by_key: dict[str, list[str]] = {}
    extras: list[tuple[str, list[str]]] = []
    for k, v in (blocks.items() if isinstance(blocks, dict) else blocks):
        lines = [v] if isinstance(v, str) else [str(x) for x in v]
        (by_key.setdefault(k, []).extend(lines) if k in labels else extras.append((str(k), lines)))
    if "copy" not in by_key and LOG.notes["copy_keys"]:
        by_key["copy"] = [", ".join(LOG.notes["copy_keys"])]
    if "tokens" not in by_key:
        by_key["tokens"] = [tokens_line()]
    by_key["tokens"] += [ln for ln in LOG.notes["fallbacks"] if ln not in by_key["tokens"]]
    ordered = [(labels[k], by_key[k]) for k, _l in ANN_ORDER if k in by_key] + extras
    kids = [text("title", title, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate(ordered, 1):
        bk = [text("label", lab, LABEL, TEXT_2)]
        bk += [text(f"value-{j}", ln, BODY, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1)]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page E42-D03 · board {nn:02d} · {rev}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG}, w=ANN_W)


# --- Sections and writing.
def _size(section: dict[str, Any]) -> int:
    """A section's size in bytes as the validator measures it (json.dumps defaults)."""
    return len(json.dumps(section))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    """n pruned to at most room bytes of JSON: the bare board, its longest prefix of whole kids and, when that needs
    fewer sections in total, the next kid packed the same way; plus the parts cut off as (parent path, node) in render
    order. None when not even the bare node fits."""
    if len(json.dumps(n)) <= room:
        return n, []
    bare = {k: v for k, v in n.items() if k != "kids"}
    if n["t"] != "board" or len(json.dumps(bare)) > room:
        return None, []
    me = f"{path}/{n['name']}" if path else n["name"]
    kids = list(n.get("kids") or [])
    kept: list[Node] = []
    while len(kept) < len(kids) and len(json.dumps(dict(bare, kids=[*kept, kids[len(kept)]]))) <= room:
        kept.append(kids[len(kept)])
    j = len(kept)
    if j == len(kids):  # unreachable while key order does not change the JSON size; kept for safety
        return dict(bare, kids=kept), []
    shallow = [(me, k) for k in kids[j:]]
    used = len(json.dumps(dict(bare, kids=[*kept, {}]))) - 2  # the bytes around the next kid's own JSON
    part, rest = _pack(kids[j], me, room - used, budget)
    if part is not None:
        deep = rest + [(me, k) for k in kids[j + 1:]]
        if _cost(deep, budget) < _cost(shallow, budget):
            return dict(bare, kids=[*kept, part]), deep
    return (dict(bare, kids=kept) if kept else bare), shallow


def _cost(cut: list[tuple[str, Node]], budget: int) -> int:
    """How many sections the cut parts need."""
    return sum(len(_emit(k, parent, budget)) for parent, k in cut)


def _emit(n: Node, into: str, budget: int) -> list[dict[str, Any]]:
    """The sections that render n under into (append-only: every into path exists before it is used and each
    parent's children arrive in the tree's order), packed by _pack; memoised per node, path and budget."""
    key = (id(n), into, budget)
    if key not in _MEMO:
        part, cut = _pack(n, into, budget - (_size({"into": into, "node": {}}) - 2), budget)
        if part is None:
            raise ValueError(f"node {n['name']!r}: not even its bare board fits {budget} bytes")
        out = [{"into": into, "node": part}]
        for parent, kid in cut:
            out += _emit(kid, parent, budget)
        _MEMO[key] = out
    return _MEMO[key]


def sections_for_board(frames: Iterable[Node], ann: Node | None = None, extra: Iterable[Node] = (),
                       budget: int = SECTION_BUDGET) -> list[dict[str, Any]]:
    """Split a board into sections under budget bytes with correct into paths: each frame whole if it fits, else packed
    in pre-order (the frame with as much of its subtree as fits, then the cut parts under "frame-1280",
    "frame-1280/body", "frame-1280/body/main"…, each packed the same way); then extra root nodes, then annotations."""
    out: list[dict[str, Any]] = []
    nodes = [*frames, *extra, *([ann] if ann else [])]
    try:
        for n in nodes:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    for s in out:
        if _size(s) > SECTION_HARD:
            raise ValueError(f"section {s['node']['name']!r} is {_size(s)} bytes (> {SECTION_HARD})")
    return out


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    """Yield (path, node) for n and every descendant."""
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


def write_sheet(path: str | Path, board_: dict[str, Any], sections: list[dict[str, Any]], export: str,
                notes: dict[str, Any] | None = None) -> str:
    """Write the sheet JSON (notes merged with LOG, every inst node a live check), validate it with the component
    inventory, clear LOG; raise RuntimeError on a validator error or a section over SECTION_HARD; return the
    validator's summary line."""
    out = Path(path).resolve()
    if out.parent != KIT_DIR:
        raise ValueError(f"sheets are written only into {KIT_DIR}")
    unknown = set(notes or {}) - set(NOTE_KINDS)
    if unknown:
        raise KeyError(f"notes keys {sorted(unknown)}; allowed {NOTE_KINDS}")
    merged: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}
    for src in (notes or {}, LOG.notes):
        for k, lines in src.items():
            for ln in [lines] if isinstance(lines, str) else lines:
                if ln not in merged[k]:
                    merged[k].append(ln)
    for sec in sections:
        for _p, n in walk(sec["node"]):
            if n["t"] == "inst" and _inst_check(n) not in merged["live_checks"]:
                merged["live_checks"].append(_inst_check(n))
    sheet = {"board": board_, "sections": sections, "export": export, "notes": merged}
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reset_notes()
    sizes = [(sec["node"]["name"], _size(sec)) for sec in sections]
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(out), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    big = [(nm, z) for nm, z in sizes if z > SECTION_HARD]
    if res.returncode != 0 or big:
        raise RuntimeError(f"{out.name}: validator exit {res.returncode}, oversize sections {big}\n" + "\n".join(lines))
    return lines[-1] if lines else ""


# --- Self-test.
def _token_table() -> dict[str, set[tuple[str, str]]]:
    """token-sync.json as {name: {(set, type)}}."""
    table: dict[str, set[tuple[str, str]]] = {}
    for s, n, ty, _v in json.loads(TOKENS_FILE.read_text()):
        table.setdefault(n, set()).add((s, ty))
    return table


def _ws(s: str) -> str:
    """s with every whitespace run collapsed to one space (markdown wraps long lines)."""
    return re.sub(r"\s+", " ", s)


def _spec_checks(check: Any) -> None:
    """Every COPY, LABELS, MARKER and SAMPLE string against the spec (and D01, D09) at the lines this kit cites, the
    gate fold's T2 anchors and §0's counts against the registry."""
    spec = pin_bytes(SPEC).decode("utf-8").split("\n")
    sec14 = "\n".join(spec[607:624])  # §14's rows, L608-624
    docs = {"spec": spec, "D01": D01.read_text(encoding="utf-8").split("\n"),
            "D09": D09.read_text(encoding="utf-8").split("\n")}
    bad = []
    for key, val in COPY.items():
        for part in (val if isinstance(val, tuple) else (val,)):
            if key in COPY_SOURCE:
                src, a, b = COPY_SOURCE[key]
                hay = _ws(" ".join(docs[src][a - 1:b]))
                ok = _ws(part) in hay
            elif key in COPY_PIECES:
                ok = all(pc in sec14 for pc in COPY_PIECES[key])
            else:
                ok = part in sec14
            if not ok:
                bad.append(key)
    current = [k for k in COPY if k not in COPY_RENAMED]
    check(not bad, f"{len(current)} copy keys verbatim in §14 L608-624 (or their cited line), plus "
                   f"{len(COPY_RENAMED)} renamed aliases {bad or ''}")
    named = [k for k in ("save.locked_hint", "dlg.choose_first", "dlg.ack_first", "dlg.token", "users.anonymised",
                         "users.sorting", "users.mfa_pending") if f"`{k.split('.', 1)[1]}`" not in sec14]
    named += [old for old, new in COPY_RENAMED.items() if f"`{old.split('.', 1)[1]}`" in spec[618]]
    named += [old for old in COPY_REMOVED if old in COPY or old.split(".", 1)[1] in "\n".join(spec)]
    check(not named, f"the gate's §14 keys: save.locked_hint (L613), dlg.choose_first / ack_first / token (L620), "
                     f"users.anonymised (L617); no admin.locked / choose_first / ack_first left in admin.* (L619); "
                     f"the merge's: users.sorting and users.mfa_pending (L617), admin.sort_needs_all gone from the "
                     f"spec and COPY {named or ''}")
    bad = [k for k, (s, ln) in LABELS.items() if s not in spec[ln - 1]]
    bad += [k for k, full in LABEL_FULL.items() if full not in _ws(" ".join(spec[LABELS[k][1] - 1:LABELS[k][1] + 1]))]
    check(not bad, f"{len(LABELS)} anatomy labels at their spec lines {bad or ''}")
    check("Recorded in the audit log · <label> (<code>)" in spec[91], "the marker template is §1 L92's")
    ex = _ws(" ".join(spec[99:105]))
    facts = [SAMPLE["owner"], "LIVE", SAMPLE["date"], f'"as of {SAMPLE["asof"]}"',
             f'"{SAMPLE["tier"]}, recorded {SAMPLE["tier_recorded"]}"', "3 sub-accounts in use", "`users.total` 8",
             "`.active` 4", "`.without_mfa` 0", "2 open positions and 3 working orders on `sub_001`"]
    facts += [u.username for u in USERS] + [f"until {USER['bea'].fills['hhmm']} UTC",
                                            f"until {USER['frank'].fills['hhmm']} UTC", "2026-10-23 10:00 UTC",
                                            "2026-10-19 08:00 UTC"]
    bad = [f for f in facts if f not in ex]
    check(not bad, f"§1 worked example facts at L100-105 {bad or ''}")
    lit = {  # filled copy == the state tables' literals
        182: copy("band.unlocked", mss=mss(760)), 183: copy("band.left", mss=mss(299)),
        184: copy("band.left_final", mss=mss(59)), 185: copy("band.locked"),
        186: copy("band.grace", cls=copy("band.grace.class.users"), mss=mss(134)), 187: copy("strip.none"),
        167: copy("band.label", route="Users"), 171: copy("meta.asof", hhmmss=SAMPLE["asof"]),
        498: copy("va.notice", viewer="basiltt", hhmm=["14:02", "14:32"]),
    }
    off = [ln for ln, s in lit.items() if s not in spec[ln - 1]]
    banner_l = copy("va.banner", user="alex", mss=mss(1660))
    if banner_l not in _ws(" ".join(spec[466:468])):
        off.append(467)
    check(not off, f"filled strings match the state tables (L167-187, L467-468, L498) {off or ''}")
    t2 = {  # the gate fold's anchors this kit's T2 helpers cite (T2, §13)
        602: ("**T2 — disabled with a visible reason**", "2a, the reason its second line",
              "one notice under the PageHeader",
              "takes the badge and CMP-016 echoes that notice (2b)", "takes the sentence form",
              "a pressed SCR-121 sort header with `aria-busy`", "an availability state",
              "never `color.text.disabled`, never `opacity.disabled`",
              "a focused T2 menu item sits on `color.surface.hover`"),
        542: ("form-validity form, not T2", "`dlg.choose_first` or `dlg.ack_first`"), 543: ("hint `dlg.token`",),
        185: ("the expiry adds no T2", "`save.locked_hint`", "board 04 draws the writes enabled"),
        322: ("**Row menu by status", "no Reset two-factor", "the item is left out, not T2 (§13)",
              "`users.mfa_pending` states the fact"),
        305: ("a header pressed while `has_more` first reads the remaining pages", "a spinner in place of its sort glyph",
              "`users.sorting` polite once", "with `users.error` [Retry]", "an availability state, never T2 (§13)"),
        655: ("sort glyph (and the busy spinner, §7)", "7.50 · 4.79 · 10.17"),
        692: ("`sortPending?: string`", "a spinner replaces its sort glyph"),
        909: ("the header button of the `sortPending` column keeps its label and its `aria-sort`",
              "pressing it again changes nothing"),
        406: ("UD-20", "`scr122-disabled`", "one notice under the PageHeader"), 475: ("**Panel notices (T2, §13).**",),
        656: ("T2 label and lock (tertiary) on `surface.hover`",), 691: ("the CMP-019 `lock` glyph leads its label",),
    }
    off = [ln for ln, needles in t2.items() if not all(nd in spec[ln - 1] for nd in needles)]
    check(not off, f"T2 anchors: §13 L602, §12 L542-543, §4 L185, §7 L322, §8 L406, §10 L475, §15 L656, §16 L691; "
                   f"the merge's sort: §7 L305, §15 L655, §16 L692, Appendix A L909 {off or ''}")
    slugs = [b.slug for nn, b in BOARDS.items() if b.twin is None and nn not in (9, 90, 91, 92)]
    text_all = "\n".join(spec)
    bad = [s for s in slugs if f"`{s}`" not in text_all]
    check(not bad, f"{len(slugs)} state-board slugs appear in §4-§11 {bad or ''}")
    pc = plan_counts()
    count = _ws(" ".join(spec[70:74]))  # §0 "Count." L71-74
    want = [f"{pc['boards']} boards", f"Frames: {pc['dark_state']} dark state boards × 2 sizes",
            f"{pc['light']} light boards × 2", f"{pc['frames']} frames in all", f"so {pc['pngs']} PNGs"]
    bad = [w for w in want if w not in count]
    check(not bad and pc == {"boards": 104, "dark_state": 90, "light": 8, "frames": 211, "pngs": 134},
          f"registry counts = §0 L71-74: {pc} {bad or ''}")


def selftest() -> int:
    """Check tokens, the copy deck, labels, the worked example, geometry, thresholds and the registry against the
    spec; build SH-1 at both sizes (frame content and a kit-exercise column use every helper), write 00-selftest.json
    and validate it; returns 0 when everything passes."""
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        """Print PASS or FAIL for one check and remember failures."""
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    reset_notes()
    table = _token_table()
    pat = r"(color|type|space|size|radius|elevation|opacity|border)\.[a-z0-9.\-]+"
    names = {v for k, v in globals().items() if k.isupper() and isinstance(v, str) and re.fullmatch(pat, v)}
    names |= set(ENV_COLOR.values()) | {t[0] for t in TONES.values()} | {t[2] for t in TONES.values()}
    names |= {v for look in BUTTON_LOOK.values() for v in look if v} | set(METER_FILL.values())
    missing = sorted(n for n in names if n not in table)
    check(not missing, f"all {len(names)} kit tokens exist in token-sync.json {missing or ''}")
    check(not names & set(NEVER_TOKENS), f"no kit token is {' or '.join(NEVER_TOKENS)} (T2, §13 L602 (5))")
    prims = sorted(n for n in names if n.startswith(("color.", "type.")) and {s for s, _ in table.get(n, set())} ==
                   {"primitives"})
    check(not prims, f"colour and typography tokens are semantic {prims or ''}")
    md5 = hashlib.md5(pin_bytes(SPEC)).hexdigest()
    print(("PASS " if md5 == SPEC_MD5 else "WARN ") + f"spec revision {md5[:8]} (line numbers read at {SPEC_MD5[:8]})")
    _spec_checks(check)
    reset_notes()
    th = {301: "unlocked", 300: "5min", 61: "5min", 60: "1min", 1: "1min", 0: "locked"}
    check(all(badge_state(s) == st for s, st in th.items()), "badge thresholds: >5:00, 5:00-1:01, 1:00-0:01, 0:00 (D3)")
    check(all(g.nav + g.main + g.right == g.w and g.inner == g.main - 32 for g in SIZES.values()),
          "D1: NavRail + main + RightRail = frame; 944 / 2048 inside space.inset.lg")
    check(LIGHT_TWINS == {10: 1, 20: 11, 29: 22, 41: 31, 58: 43, 68: 62, 82: 72, 89: 86}, "light twins per §0 L76-77")
    check(board_name(31) == "E42-D03 / 31 SCR-121 / populated · 1280×800+2560×1440 · dark", "board 31 name (§0 L48)")
    check(grid_xy(31) == (0, 6 * PITCH_Y) and grid_xy(5) == (4 * PITCH_X, 0), "grid x/y per the build notes")
    check(BOARDS[104] == Bd("SCR-122", "UD-20", "disabled", "scr122-disabled", SIZE_BOTH, "dark", None)
          and board_name(104) == "E42-D03 / 104 SCR-122 / disabled · 1280×800+2560×1440 · dark"
          and grid_xy(104) == (3 * PITCH_X, 20 * PITCH_Y)
          and export_path(104) == "docs/design/E42/img/E42-D03-104-scr122-disabled.png",
          "board 104: SCR-122 UD-20 scr122-disabled, both sizes, dark, at grid slot NN = 104 (§0 L65, §8 L406)")
    check(list_items(copy("dlg.signout")) == ["Ends 1 session (device · IP · since)", "the others stay"],
          "list_items keeps the parenthesised dots")
    reset_notes()
    _t2_checks(check)
    reset_notes()
    return _selftest_sheet(check, fails)


def _t2_checks(check: Any) -> None:
    """The T2 helpers against §13 L602 and the validity / busy forms against §12 L542-543 (built, checked, dropped)."""
    def names(n: Node) -> list[str]:
        """Every node name under n, n included (pre-order)."""
        return [x["name"] for _p, x in walk(n)]

    def find_(n: Node, nm: str) -> Node:
        """The first node named nm under n."""
        return next(x for _p, x in walk(n) if x["name"] == nm)

    b = t2_button("Save", "admin.self.account", "primary")
    ctl = b["kids"][0]
    check(b["name"] == "T2 · Save" and [k["name"] for k in ctl["kids"]] == ["locked", "label"]
          and ctl["o"].get("fill") == T2_FILL and ctl["o"].get("stroke") == T2_EDGE
          and find_(ctl, "label")["color"] == T2_LABEL and find_(ctl, "locked")["color"] == T2_LABEL
          and b["kids"][1]["name"] == "reason" and b["kids"][1]["color"] == T2_REASON,
          "t2_button 2a: the lock leads the full label (tertiary), raised + border.default hairline, the reason under "
          "it (secondary)")
    sh = t2_button("Save", "rbac.view_as", shared=True)
    gh = t2_button("Edit", "admin.self.account", "ghost")
    check("reason" not in names(sh) and sh["kids"][0]["name"] == "locked" and "fill" not in gh["kids"][0]["o"],
          "t2_button shared: no reason of its own; a ghost has no fill to lose")
    ib = t2_icon_button("edit", "edit", "rbac.view_as", echo=True, user="alex")
    check("lock badge" in names(ib) and any(x["t"] == "inst" and x["set"] == "CMP-016 · Tooltip" for _p, x in walk(ib)),
          "t2_icon_button: the lock badge on the icon and the CMP-016 echo (2b)")
    s = t2_sentence("rbac.view_as", user="alex")
    check([x["t"] for _p, x in walk(s)] == ["board", "text"] and find_(s, "description")["chars"] ==
          "Read-only while viewing as alex.", "t2_sentence: the reason alone, no glyph, no button")
    m = menu(row_menu_items("own"), focus=2)
    it2 = m["kids"][1]
    check(it2["kids"][0]["name"] == "locked" and [k["name"] for k in it2["kids"][1]["kids"]] == ["label", "reason"]
          and it2["o"].get("fill") == T2_FOCUS_FILL and len(m["kids"]) == 5,
          "menu: a T2 item's reason is its second line; the focused item on color.surface.hover; U-5's five items")
    r = radio("B", "body", t2_reason="admin.needs_count")
    words = find_(r, "words")["kids"]
    check([k["name"] for k in words] == ["label row", "reason", "body"] and words[0]["kids"][0]["name"] == "locked",
          "radio T2: the lock leads the label, the reason its second line, then the body")
    reset_notes()
    th = table_header(scr121_cols(), focus="user", sort_pending="user")
    hu = next(x for x in th["kids"] if x["name"] == "user")
    sortable = [c.id for c in scr121_cols() if c.sortable]
    check(th["name"] == "header" and "locked" not in names(th) and "reason" not in names(th)
          and [k["name"] for k in hu["kids"]] == ["label", "spinner"] and hu["kids"][0]["color"] == TEXT_2
          and hu["kids"][1]["icon"] == "refresh" and hu["kids"][1]["color"] == TEXT_3
          and hu["o"].get("stroke") == FOCUS_RING and 'aria-busy="true"' in hu["note"]
          and "aria-sort none" in hu["note"] and "users.sorting" in LOG.notes["copy_keys"]
          and DEVIATIONS["t2"] not in LOG.notes["deviations"]
          and not any("t2_reason=" in d for d in LOG.notes["deviations"]) and len(sortable) == 4,
          "sortPending header (§7 L305, §16 L692): label and aria-sort kept, the spinner in place of the sort glyph "
          "(tertiary), aria-busy, focused; no lock, no reason (never T2); users.sorting recorded")
    tc = table_header(scr121_cols(), sort_cleared="user")
    hc = next(x for x in tc["kids"] if x["name"] == "user")
    check([k["name"] for k in hc["kids"]] == ["label"] and "aria-sort none" in hc["note"] and "locked" not in names(tc),
          "sort_cleared: no glyph, aria-sort none after a failed read (users.error [Retry] under the rows, §7 L305)")
    refused = []
    for probe in (lambda: copy("admin.sort_needs_all"), lambda: t2_reason("admin.sort_needs_all")):
        try:
            probe()
        except KeyError:
            refused.append(True)
    check(len(refused) == 2 and "admin.sort_needs_all" not in COPY,
          "a key §14 dropped at the merge (admin.sort_needs_all) is refused by copy() and the T2 helpers")
    inv = [row_menu_items(kind) for kind in ("invited", "invite_expired")]
    check(all(label("reset_2fa") not in [it if isinstance(it, str) else it[0] for it in r] and len(r) == 4 for r in inv)
          and inv[0] == [label("edit"), (label("view_as"), "admin.invite_pending"),
                         (label("disable"), "admin.invite_pending"), label("delete")],
          "§7 L322: an invited / expired-invite row menu is Edit, View as T2, Disable T2, Delete (no Reset two-factor)")
    conf = {st: rung_dialog(2, "t", confirm="Remove access", confirm_state=st)["kids"][-1]["kids"][-1]
            for st in CONFIRM_STATES}
    check(conf["enabled"]["name"] == "CMP-001 Button (composition) · Remove access"
          and all(conf[st]["name"] == "validity · Remove access" and "locked" not in names(conf[st])
                  and find_(conf[st], "hint")["chars"] == COPY[CONFIRM_HINT[st]] for st in CONFIRM_HINT)
          and conf["loading"]["name"].endswith("(loading)"),
          "rung confirm: validity form (no lock; hint dlg.choose_first / ack_first / token) and loading, never T2")
    reset_notes()
    s1 = copy("admin.locked")
    check(s1 == COPY["save.locked_hint"] and LOG.notes["copy_keys"] == ["admin.locked"]
          and any("save.locked_hint" in d for d in LOG.notes["deviations"]),
          "a renamed key (admin.locked) still resolves, recorded as called and flagged with its new key")
    reset_notes()
    t2_button("Save", "admin.locked")
    check(any("never a T2 reason" in d for d in LOG.notes["deviations"]),
          "a never-T2 key drawn as a T2 reason is flagged (save.locked_hint, §4 L185)")
    reset_notes()
    every = [b, sh, gh, ib, s, m, r, th, tc, *conf.values(), t2_notice("admin.user_disabled", w=480),
             t2_select("trade", shared=True), t2_check("sub_001", "admin.user_disabled", checked=True),
             t2_field("x", "1", shared=True), t2_cluster(["A", "B"], "rbac.view_as", user="alex"),
             busy_icon_button("row menu", "Disabling alex…")]
    dump = json.dumps(every)
    check(not any(t in dump for t in NEVER_TOKENS), f"no T2 / validity / busy node binds {' or '.join(NEVER_TOKENS)}")


def _selftest_content(px: int) -> list[Node]:
    """Frame content for the self-test (spec strings only): at 1280 the capacity line, an SCR-121 header and rows
    and a T2 / described control pair; at 2560 a band of three tiles, the tightening notice and the empty state."""
    if px == 1280:
        cols = scr121_cols(px)
        menu_btn = icon_button("row menu", "more-horizontal")
        rows = [table_header(cols, sort=("user", "asc")),
                table_row(cols, {"user": "basiltt", "role": label("role.owner"), "accounts": label("all_owner"),
                                 "two_factor": label("mfa.yes"), "status": user_chip("basiltt"), "menu": menu_btn},
                          "row-basiltt", selected=True),
                table_row(cols, {"user": "alex", "role": label("role.manager"), "accounts": label("n_accounts"),
                                 "two_factor": label("mfa.yes"), "status": user_chip("alex"), "menu": menu_btn},
                          "row-alex", focus="user"),
                table_row(cols, {"user": "carol", "role": label("role.viewer"), "accounts": label("none_dash"),
                                 "two_factor": label("none_dash"), "status": user_chip("carol"), "menu": menu_btn},
                          "row-carol")]
        ctl = hbox("controls", [t2_button(label("disable"), "admin.self.account"),
                                button(label("save"), "primary", described="save.locked_hint")],
                   {"gap": INSET_LG, "align": "start"})
        return [capacity_line("recorded", px=px), vbox("CMP-049 grid (composition)", rows, None), ctl]
    LOG.add("copy_gaps", "'Live trading:' / 'on', 'Kill switch:' / 'off', 'Open positions:' / '2': OV-2's tile lines "
                         "(spec L276), not §14 keys (self-test only)")
    t1 = tile(label("tile.trading"), [pair("live", "Live trading:", "on"), pair("kill", "Kill switch:", "off"),
                                      pair("open", "Open positions:", "2", numeric=True)], px=px, col=0, env="LIVE",
              asof=copy("tile.asof", hhmmss="14:02:11"))
    t2 = tile(label("tile.users"), px=px, col=1, tone="danger", status=copy("tile.error"),
              last_good=copy("tile.last_good", hhmmss="14:01:40"))
    t3 = tile(label("tile.recorder"), px=px, col=2, state="loading")
    return [tile_band(label("band.right_now"), [t1, t2, t3], px, h=200),
            notice(copy("notice.tightening"), w=SIZES[px].inner),
            empty_state(copy("users.empty"), button(label("invite_user"), "primary"), w=SIZES[px].inner)]


def _selftest_exercise() -> Node:
    """A 1280 px kit-exercise column (spec strings only): the four badges and the grace line, every capacity state,
    every user chip, the U-5 own-row menu (focused T2 item), carol's and dan's row menus (§7 L322), a focused code
    field with its error, the OV-9 notice, the view-as banner, a rung-2 unbind dialog with its two choices and the
    acknowledgement tick, then the T2 and never-T2 forms (_selftest_t2)."""
    badges = hbox("badges", [badge(760), badge(299), badge(59), badge(state="locked"), grace_line()], {"gap": INSET_MD})
    caps = vbox("capacity states", [capacity_line(s, used=5 if s == "at_capacity" else 3) for s in CAP_STATES],
                {"gap": STACK_SM})
    chips = hbox("chips", [user_chip(u.username) for u in USERS] + [chip("locked_out", until=False),
                                                                     chip("anonymised", yyyymmdd=SAMPLE["date"]),
                                                                     tag(label("this_device"), "neutral", "")],
                 {"gap": INSET_XS, "wrap": "wrap"}, w=1280)
    own_menu = menu(row_menu_items("own"), w=280, focus=2, name="CMP-041 Menu (composition) · own row")
    carol_menu = menu(row_menu_items(USER["carol"].chip), w=280, name="CMP-041 Menu (composition) · carol")
    dan_menu = menu(row_menu_items(USER["dan"].chip), w=280, name="CMP-041 Menu (composition) · dan")
    code = field(copy("gate.code_label"), "1234", hint=copy("gate.code_hint"), error=copy("gate.code_incomplete"),
                 focused=True, mono=True)
    iw = DIALOG_W["large"] - 2 * PX[DIALOG_PAD]
    lead = env_text("lead", copy("unbind.lead", account="sub_001", env="LIVE", n=2, m=3, user="alex"), BODY, TEXT_1,
                    iw)
    b_body = copy("unbind.b", n=2, m=3, account="sub_001", user="alex") + " " + copy("unbind.b_option_a", user="alex")
    choices = vbox("radiogroup", [lead, radio(label("choice_a"), copy("unbind.a"), w=iw, name="option-a"),
                                  radio(label("choice_b"), b_body, w=iw, name="option-b")], {"gap": STACK_SM},
                   note='role="radiogroup" labelled by the lead, aria-required, none checked (§12 L562-563)')
    dlg = rung_dialog(2, label("unbind_title"), choices=choices, extra=[text("keeps", label("keeps_access"), BODY,
                                                                             TEXT_1)],
                      marker_=("Account access changed", "users.access_change"), confirm=label("remove_access"),
                      confirm_state="choose_first")
    ack = tick(copy("unbind.ack"), w=iw)
    menus = hbox("row menus", [own_menu, carol_menu, dan_menu], {"gap": INSET_LG, "align": "start"})
    side = hbox("field, tick", [code, ack], {"gap": INSET_LG, "align": "start"})
    return vbox("kit exercise", [badges, caps, chips, menus, side, banner("danger", label("notice.key_selfcheck"),
                                                                          w=1280),
                                 viewas_banner(notified=True), dlg, _selftest_t2()], {"gap": STACK_LG}, w=1280)


def _selftest_t2() -> Node:
    """The T2 and never-T2 forms (T2, §13 L602; spec strings and §1 data only): UD-20's PageHeader notice with a
    shared tick, level select and field; UD-8's 2a role select and danger button; a view-as panel notice with a shared
    button, a 2b icon control and its echo, the sentence form and CMP-211's cluster; the busy sortPending header (never
    T2, §7 L305); a T2 option; the validity, busy confirm and U-7 trigger."""
    w = 600
    ud20 = vbox("UD-20: one notice, many pointers", [
        t2_notice("admin.user_disabled", w=w),
        t2_check("sub_001", shared=True, extra=[env_badge("LIVE"), t2_select("trade", shared=True, w=120)]),
        t2_field(label("display_name"), shared=True, w=240)], {"gap": STACK_SM}, w=w)
    ud8 = hbox("UD-8: 2a", [t2_select(label("role.owner"), "admin.self.role", w=200),
                            t2_button(label("disable"), "admin.self.account", "destructive", focused=True)],
               {"gap": INSET_LG, "align": "start"})
    panel = vbox("view-as panel", [
        t2_notice("rbac.view_as", w=w, user="alex"),
        hbox("controls", [t2_button(label("edit"), "rbac.view_as", "primary", shared=True),
                          t2_icon_button("edit", "edit", "rbac.view_as", echo=True, user="alex")],
             {"gap": INSET_LG, "align": "start"}),
        t2_cluster([label("cmp211.freeze"), label("cmp211.release"), label("cmp211.flatten_all"),
                    label("cmp211.cancel_all")], "rbac.view_as", w=w, user="alex"),
        t2_sentence("rbac.view_as", w=w, user="alex")], {"gap": STACK_SM}, w=w)
    iw = DIALOG_W["large"] - 2 * PX[DIALOG_PAD]
    option_b = radio(label("choice_b"), copy("unbind.b", n=2, m=3, account="sub_001", user="alex"),
                     t2_reason="admin.needs_count", focused=True, w=iw, name="option-b (T2)")
    never = hbox("never T2", [validity_button(label("remove_access"), "dlg.ack_first"),
                              validity_button(label("delete"), "dlg.token"),
                              busy_button(label("save"), "primary", focused=True),
                              busy_icon_button("row menu", copy("users.disabling", user="alex"))],
                 {"gap": INSET_LG, "align": "start"})
    return vbox("T2 forms", [hbox("UD-20, UD-8", [ud20, ud8], {"gap": INSET_LG, "align": "start"}), panel,
                             table_header(scr121_cols(), name="header (sort pending)", focus="user",
                                          sort_pending="user"), option_b, never],
                {"gap": STACK_LG}, w=1280)


def _selftest_sheet(check: Any, fails: list[str]) -> int:
    """Build SH-1 at both sizes plus the exercise column, write 00-selftest.json, validate it and check the output."""
    probe = modal(1280, dialog(copy("gate.title"), [text("body", copy("gate.body", hhmm="14:17"), BODY, TEXT_1)],
                               size="default"))
    check(len(probe) == 1 and probe[0].get("abs") and len(probe[0]["kids"]) == 2,
          "modal(): one absolute overlay holding the scrim and the dialog")
    check(drawer(label("users"), []).get("abs") is True, "drawer(): absolute at the frame's right edge")
    reset_notes()  # the probes are not part of the sheet
    frames = []
    for px in SIZES:
        items = [strip_item("strip.locked"), strip_item("strip.key_expiry_n.one", env="LIVE", focused=True),
                 strip_item("strip.unlock_again", mss="0:59")] if px == 2560 else []
        frames.append(shell(px, route=label("users"), h1="alex", right=badge(760), items=items,
                            content=_selftest_content(px)))
    exercise = _selftest_exercise()
    ann = annotations(0, "00 kit self-test: SH-1 unlocked (a) at both sizes, plus a kit-exercise column", {
        "source": "spec §4 L182 · SH-1; frame-2560's strip items and all frame content exercise the kit",
        "state": "SH-1 unlocked (a): the window is live with more than 5:00 left (12:40); band.unlocked",
        "decisions": "§2 D1 (layout), D2 (neutral tint), D3 (countdown text), D5 (time limits)",
        "roles": "Owner only: without admin:read CMP-087 never mounts (§4 L202)",
        "keyboard": "skip link → TopBar → NavRail → strip items → the h1's primary action → page → RightRail → "
                    "StatusBar; the band holds no focusable control (§4 L199-201)",
        "announcement": "none for SH-1; the route announcer says "
                        f"'{copy('announce.route', route='Users', env='LIVE')}' once, polite (§4 L200)",
        "events": "admin.area_entered, written by the strip's /admin/* reads on SCR-121-123 (§4 L202-205)",
    })
    for ln in (FALLBACKS["DS-1"], FALLBACKS["DS-2"], FALLBACKS["DS-3"], FALLBACKS["STEP"]):
        check(any(n.get("chars") == ln for _p, n in walk(ann)), f"annotation prints: {ln[:60]}…")
    secs = sections_for_board(frames, ann, extra=[exercise])
    big = max(_size(s) for s in secs)
    check(big <= SECTION_BUDGET, f"{len(secs)} sections, largest {big} bytes (budget {SECTION_BUDGET})")
    check([s["into"] for s in secs].count("") >= 4, "root sections: frame-1280, frame-2560, kit exercise, annotations")
    w, h = root_size([*frames, exercise], ann)
    b = {"name": penpot_name(f"E42-D03 / 00 kit/selftest · {SIZE_BOTH} · dark"), "w": w, "h": h, "x": 0,
         "y": -2 * PITCH_Y, "o": dict(ROOT_O)}  # above the grid's first row, clear of boards 01-05
    out = KIT_DIR / "00-selftest.json"
    try:
        check(True, "validator: " + write_sheet(out, b, secs, "docs/design/E42/img/E42-D03-00-selftest.png",
                                                {"sources": ["e42kit.py self-test (not a spec board)"]}))
    except RuntimeError as exc:
        print(exc)
        check(False, "validator exit 0")
        return 1
    sheet = json.loads(out.read_text())
    secs_dump = json.dumps(sheet["sections"])
    check(not any(t in secs_dump for t in NEVER_TOKENS), f"no node of the sheet binds {' or '.join(NEVER_TOKENS)}")
    insts = [n for sec in sheet["sections"] for _p, n in walk(sec["node"]) if n["t"] == "inst"]
    check(bool(insts) and all(_inst_check(n) in sheet["notes"]["live_checks"] for n in insts),
          f"{len(insts)} inst nodes in live_checks")
    fr = [s["node"] for s in sheet["sections"] if s["into"] == "" and s["node"]["name"].startswith("frame-")]
    check([(f["w"], f["h"]) for f in fr] == [(1280, 800), (2560, 1440)], "frames 1280 x 800 and 2560 x 1440 at 1:1")
    print(f"{out}: {'OK' if not fails else str(len(fails)) + ' failed'} ({len(sheet['sections'])} sections, "
          f"{len(json.dumps(sheet))} bytes)")
    return 1 if fails else 0


# --- R-1 / R-2 (orchestrator ruling 2026-10-25 01:30Z; build notes "RULINGS R-1 / R-2"): appended after the self-test
# so no earlier kit line moves (board 94 computes a kit line number). CMP-138 and CMP-044 are read from the spec at
# the boards branch's 4babb1f62 and `15` there (frozen in spec/, else pin_bytes()); every other line pin stays at SPEC
# (7884a33bd). Nothing above this block changed except SPEC's path (the same bytes, frozen).
SPEC_RULED = KIT_DIR / "spec" / "E42-D03@4babb1f62.md"
SPEC_RULED_MD5 = "d91202f9bf42206dd1a5cbc865d5ce02"  # 969 lines; §0 L84-91, §12 L555-556, §16 L711-712, §20 L822-842
CAT_RULED = KIT_DIR / "spec" / "15@4babb1f62.md"
CAT_RULED_MD5 = "310980c4dbe1e4a65ae03cc528ce3183"  # CMP-044 `15:473-480` (#4414), CMP-138 `15:1576-1586` (#4134)


def ruled_lines(doc: str) -> list[str]:
    """The lines of the ruled spec ("spec", 4babb1f62) or catalogue ("15"), after checking their md5 (R-1, R-2)."""
    path, md5 = {"spec": (SPEC_RULED, SPEC_RULED_MD5), "15": (CAT_RULED, CAT_RULED_MD5)}[doc]
    data = pin_bytes(path)
    if hashlib.md5(data).hexdigest() != md5:
        raise SystemExit(f"{path.name}: md5 is not {md5[:8]}: re-read every ruled line")
    return data.decode("utf-8").splitlines()


def check_ruled(facts: Iterable[tuple[str, int, str]]) -> list[str]:
    """The (doc, line, text) facts not found on their ruled line (or across it and the next, where markdown wraps)."""
    docs = {d: ruled_lines(d) for d in ("spec", "15")}
    return [f"{d}@4babb1f62:{ln} {t[:48]!r}" for d, ln, t in facts
            if _ws(t) not in _ws(" ".join(docs[d][ln - 1:ln + 1]))]


# Facts the block below states, proven at build time by check_ruled(RULED_KIT_FACTS) from each generator that uses it.
RULED_KIT_FACTS = [
    ("spec", 555, "natively disabled as `15` CMP-044's merged entry has it (#4414; R-2): out of the Tab order, no lock "
                  "glyph, no CMP-079, the danger fill dropped to `color.surface.raised` with a `color.border.default` "
                  "hairline and the label `color.text.tertiary` (DJ), the visible hint for the first unmet condition"),
    ("spec", 556, "the same natively disabled validity form, CMP-044's typed state, hint `dlg.token`"),
    ("spec", 607, "while an input is unmet, is natively disabled and skipped by Tab, its visible hint naming that input"),
    ("spec", 711, "consumed by name (R-1, orchestrator ruling 2026-10-25 01:30Z)"),
    ("spec", 679, "CMP-138 (E39-D02 §6) 80 % tick · overflow marker · unknown hatch on `surface.sunken` · state glyph on "
                  "raised"),
    ("15", 477, "typed (Confirm natively disabled until the summary has loaded and the field matches exactly: form "
                "validity, not a gate)"),
    ("15", 478, "Confirm stays natively disabled (form validity, as the typed state, not a gate) until a choice is "
                "made, then until `acknowledge` is ticked"),
    ("15", 478, "the visible hint names the first unmet input"),
    ("15", 1578, "the fill is reinforcement, the glyph + word carry the state"),
    ("15", 1580, "near-cap (≥ 80 %: WARN diamond + word)"),
    ("15", 1580, "LOCK square + word; the bar clipped at 100 %, the number not; a refusal cap at 100 % reads bar + "
                 "\"CAP\""),
    ("15", 1580, "unknown: no fill, a hatched track, \"—\""),
    ("15", 1580, "over-cap-after-tightening (the clipped fill plus an overflow marker; \"112 % of the new cap · cap "
                 "tightened at 14:10 UTC\""),
    ("15", 1582, "PROPOSED `role=\"meter\"` with `aria-valuenow/min/max` and `aria-valuetext`"),
    ("15", 1582, "the 80 % tick on every variant; never announced per tick"),
    ("15", 1583, "`color.surface.sunken` (the track"),
    ("15", 1583, "`radius.pill`"),
]

SRC["validity-native"] = ("spec 4babb1f62 §12 L555-556, §13 L607 and `15:477-478` (CMP-044's merged validity form, "
                          "natively disabled: R-2, #4414)")
SRC["cmp138"] = ("spec 4babb1f62 §16 L711, §20 C-row (3) L822-826, UD-14 L412 and `15:1576-1586` (E39-D02's merged "
                 "CMP-138, read by name: R-1, #4134; E39-D02 §6)")
DEVIATIONS["validity-native"] = (
    "A rung confirm waiting on its inputs takes the validity form, natively disabled as CMP-044's merged entry has it "
    "(R-2, #4414; `15:477-478`; spec 4babb1f62 §12 L555-556, §13 L607; never T2): the `disabled` attribute, out of the "
    "Tab order, no lock, no CMP-079, the danger fill dropped to color.surface.raised with a color.border.default "
    "hairline and the label color.text.tertiary (the spec's DJ); its visible hint (dlg.choose_first / dlg.ack_first / "
    "dlg.token) names the first unmet input and sits under the button in type.ui.caption color.text.tertiary (§15 "
    "L661; placement: kit choice).")
FALLBACKS["CMP138"] = (
    "fallback: CMP-138's state glyphs (E39-D02 §6: circle ok, diamond WARN, filled square LOCK, bar CAP) are not in "
    "DS-5 or the registry: the circle a 10 px ellipse outline, the diamond the text glyph ◆ (as the admin mark), the "
    "square a 10 px rect, the bar a 12 x 4 rect, all color.text.primary; the unknown hatch's diagonals are 2 px steps "
    "in color.text.tertiary (cvsheet v1 has no rotation or path); the track's radius.pill is the merged entry's token "
    "(`15:1583`), a Tier-1 primitive (validator WARN)")


def validity_native(chars: str, hint: str, variant: str = "destructive", *, name: str | None = None,
                    **fills: Any) -> Node:
    """validity_button()'s geometry and tokens with CMP-044's merged semantics (R-2, #4414; `15:477-478`; spec
    4babb1f62 §12 L555-556, §13 L607): natively disabled, out of the Tab order (never focused), its hint naming the
    first unmet input; never T2. Same node names as validity_button() (DEVIATIONS["validity-native"])."""
    if variant not in BUTTON_LOOK:
        raise ValueError(f"button variant {variant!r}: one of {sorted(BUTTON_LOOK)}")
    _fallback("CONTROL")
    _deviate("compose")
    _deviate("validity-native")
    _src("validity-native")
    why = copy(hint, **fills) if hint in COPY else hint
    kids = [text("label", chars, BODY_STRONG, T2_LABEL)]
    w = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    o = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "height": CONTROL_COMF, "justify": "center",
         "fill": T2_FILL, "stroke": T2_EDGE, "strokeWidth": HAIRLINE, "strokeAlign": "inner"}
    btn: Node = hbox(f"CMP-001 Button (composition) · {chars} (validity)", kids, o, w=w, h=CONTROL_H,
                     note=f"the validity form, not T2 (spec 4babb1f62 §12 L555-556): natively disabled as CMP-044's "
                          f"merged entry has it (`15:477-478`, #4414; R-2): the disabled attribute, out of the Tab "
                          f"order, no lock, no CMP-079; variant {variant} once its inputs are met; forced colours: the "
                          "label GrayText (§15 L642)")
    hint_n = text("hint", why, CAPTION, TEXT_3,
                  note="the visible hint naming the first unmet input (CMP-044 A11y, `15:478`; spec 4babb1f62 §12 "
                       "L555; 5.20 on overlay, §15 L661)")
    return vbox(name or f"validity · {chars}", [btn, hint_n], {"gap": INSET_XS, "align": "end"})


# CMP-138 RiskCapMeter as E39-D02 merged it, read by name (R-1, #4134; `15:1576-1586`; E39-D02 §6 :98-108; spec
# 4babb1f62 §16 L711, §20 C-row (3) L822-826): the color.surface.sunken track (radius.pill), the fill as reinforcement
# (ok color.text.secondary, warn color.status.warning.default, lock and cap color.status.danger.default, clipped at
# 100 %), the 1 px color.text.secondary 80 % tick on every variant, a color.status.danger.strong overflow marker past the
# track end (over-cap-after-tightening), unknown a hatched track with no fill; the glyph + word beside the number carry
# the state (circle ok, diamond WARN, filled square LOCK, bar CAP; color.text.primary, §15 L679 at 4babb1f62).
WARN_DEFAULT, DANGER_DEFAULT = "color.status.warning.default", "color.status.danger.default"
R_PILL = "radius.pill"
CAP138_FILL = {"ok": TEXT_2, "warn": WARN_DEFAULT, "lock": DANGER_DEFAULT, "cap": DANGER_DEFAULT,
               "over": DANGER_DEFAULT, "unknown": None}
CAP138_WORD = {"ok": ("circle", "ok"), "warn": ("diamond", "WARN"), "lock": ("square", "LOCK"), "cap": ("bar", "CAP"),
               "over": ("bar", "CAP")}


def cap138_glyph(kind: str) -> Node:
    """A CMP-138 state glyph (E39-D02 §6), a composition (FALLBACKS["CMP138"]): circle, diamond, square or bar."""
    LOG.add("fallbacks", FALLBACKS["CMP138"])
    if kind == "circle":
        g = ellipse("circle", 10, 10, {"stroke": TEXT_1, "strokeWidth": HAIRLINE})
    elif kind == "diamond":
        LOG.add("live_checks", "glyph ◆ (U+25C6), CMP-138's WARN diamond: confirm Inter draws it; else Penpot "
                               "substitutes a fallback font")
        return text("diamond", "◆", CAPTION, TEXT_1)
    elif kind == "square":
        g = rect("square", 10, 10, TEXT_1)
    elif kind == "bar":
        g = rect("bar", 12, 4, TEXT_1)
    else:
        raise ValueError(f"CMP-138 glyph {kind!r}: circle, diamond, square or bar")
    return hbox(kind, [g], {"justify": "center"}, w=12, h=12)


def cap138_state(state: str) -> Node:
    """The glyph + word beside the number (E39-D02 §6; `15:1580`): type.ui.caption color.text.primary."""
    kind, word = CAP138_WORD[state]
    return hbox(f"state · {word}", [cap138_glyph(kind), text("word", word, CAPTION, TEXT_1)], {"gap": INSET_XS},
                note="the glyph and the word carry the state; the fill is reinforcement (`15:1578`; E39-D02 §6)")


def cap138_meter(state: str, frac: float, w: int = 160, h: int = 8, note: str = "") -> Node:
    """The merged CMP-138 bar (no text): sunken pill track, the state's fill clipped at 100 %, the 80 % tick, the
    overflow marker ("over") or the hatch ("unknown"); role="meter" in its note."""
    if state not in CAP138_FILL:
        raise ValueError(f"CMP-138 state {state!r}: one of {sorted(CAP138_FILL)}")
    _src("cmp138")
    LOG.add("fallbacks", FALLBACKS["CMP138"])
    tick_h = h + 4
    y0 = (tick_h - h) // 2
    kids = [rect("track", w, h, SUNKEN, {"radius": R_PILL}, x=0, y=y0)]
    fill = CAP138_FILL[state]
    if fill and frac > 0:
        kids.append(rect("fill", round(w * min(frac, 1.0)), h, fill, {"radius": R_PILL}, x=0, y=y0))
    if state == "unknown":
        for i, x0 in enumerate(range(12, w - 8, 30), 1):  # 5 diagonals of 2 px steps (FALLBACKS["CMP138"])
            for j in range(h // 2):
                kids.append(rect(f"hatch {i}.{j + 1}", 2, 2, TEXT_3, x=x0 + 2 * j, y=y0 + h - 2 - 2 * j))
    kids.append(rect("80 % tick", 1, tick_h, TEXT_2, x=round(w * 0.8), y=0))
    extra = 0
    if state == "over":
        kids.append(rect("overflow marker", 3, tick_h, DANGER_STRONG, x=w + 2, y=0))
        extra = 5
    return box(f"CMP-138 RiskCapMeter (composition) · {state} bar", kids, None, w=w + extra, h=tick_h,
               note='role="meter", aria-valuenow/min/max and aria-valuetext, the state word in the accessible name; '
                    "never live (`15:1582`; E39-D02 §6)" + (f"; {note}" if note else ""))


# --- Pins. The frozen copies under spec/ are not committed; when one is absent, pin_bytes() reads the same bytes with
# `git show` (repo-relative, read-only, no network): the pin's revision, then the boards PR's own commit that holds the
# same bytes (the pin itself was rebased away), then the blob id. Each reader still checks the md5.
PIN_GIT: dict[str, tuple[str, tuple[str, ...]]] = {
    "E42-D03@7884a33bd.md": ("docs/design/E42/E42-D03.md",
                             ("7884a33bd", "357a0b097", "f5756899dd059eca01dfbd155a7df95e017e6f0d")),
    "E42-D03@4babb1f62.md": ("docs/design/E42/E42-D03.md",
                             ("4babb1f62", "3dafe78a7", "378a49898b8afc6af67c1ebd91b2d96076c0ed1a")),
    "15@4babb1f62.md": ("docs/plan/15-component-catalogue.md",
                        ("4babb1f62", "a7caf791b024083b08792dcd4b10930cb3961d48")),
}


def pin_bytes(path: Path) -> bytes:
    """A frozen pin's bytes: the file under spec/ if present, else `git show <rev>:<path>` / `git show <blob>`."""
    if path.exists():
        return path.read_bytes()
    rel, revs = PIN_GIT[path.name]
    for rev in revs:
        obj = rev if len(rev) == 40 else f"{rev}:{rel}"
        res = subprocess.run(["git", "-C", str(KIT_DIR), "show", obj], capture_output=True, timeout=60, check=False)
        if res.returncode == 0:
            return res.stdout
    raise SystemExit(f"{path.name}: not under spec/, and git show finds none of {', '.join(revs)} ({rel}); "
                     "fetch the boards PR's head ref (gen10/BUILD.md, Rebuild)")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)
