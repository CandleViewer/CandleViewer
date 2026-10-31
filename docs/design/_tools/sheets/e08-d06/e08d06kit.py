"""E08-D06 (#174) board kit: SCR-103 symbol info drawer (CMP-046) with CMP-125, CMP-126 and CMP-177, as cvsheet JSON
sheets for the per-set Penpot file "E08-D06 boards", page "E08-D06 SCR-103 Symbol info".

Offline only. Spec (binding): docs/design/E08/E08-D06.md and E08-D06-handoff.md as at BASE (read with `git show` in
this checkout; md5-pinned in SPEC_MD5: the kit refuses drifted bytes; re-read, re-check, re-pin).
Registry: spec §15's 25 boards are parsed (sizes, twin flags, contents); boards 1-17 get a light twin, so BOARDS holds
42 keys: "1D" ... "25D" and "1L" ... "17L". Export names keep §15's form: scr-103-<state>-<role>-<theme>.png and
cmp-<nnn>-<name>-<theme>.png under docs/design/E08/img/.
Seed data: the DATA block of the r2 board script (r2/e08-d06-board.js, sha256-pinned in R2_SHA256): its fixtures,
strings and per-board markers. Only its data is used, never its drawing code; every number the kit draws is derived
again from the fixture values by the §5 formatters (F3-F7, F10) and the self-test proves it equals r2's strings.

Pipeline (one generator per board, gen/gen_<key>.py, written by the board authors after the cap ruling):
    frames = [drawer_frame(...) | free_frame(...), ...]   # FRAME_PLAN order, §15 sizes
    ann = annotations(key, [frame_block(...), marker_block(...), ...])
    p = write_sheet(key, frames, ann)        # build/NN-<slug>-<theme>.json, validator exit 0 or RuntimeError
    write_md(key, p)                         # build/ and ./NN-<slug>-<theme>.md (line 3 = the render script's line)
    pack_sheet(p)                            # v4/<same name>, compactOf.file = the bare name + the source's sha256
Twins ("NL"): call the base board's builder with theme="light"; the sheet is the same token-bound construction and the
theme switch happens at export (md line 3 "theme light."). Never paint a light value.
Self-test: python3 -I -B e08d06kit.py selftest   (board 1 dark into build/selftest/, validated, packed)
Rebuild all eleven drawn boards: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every flex
child without text carries an explicit h; no "/" in a node name; no local path, host or agent name in a sheet (BANNED);
packed sections <= 9 KB; table and row cells carry 8 px inner padding a side; a "state: <fid>" caption per frame; the
root hugs its frames + ONE 400 px annotation column + 80.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
PENPOT_SLASH = "\u2215"  # kit reading: after the "E08-D06 / NN " prefix a "/" is written U+2215 in Penpot names
CAP_DIR = KIT_DIR / "build"  # raw sheets + their .md (the render drivers' set; untracked: .gitignore)
V4_DIR = KIT_DIR / "v4"  # packed sheets (the renderer's input, committed; compactOf.file = the bare raw name)
SELFTEST_DIR = CAP_DIR / "selftest"
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
PACKER = SHEETS_DIR / "tools" / "compact.py"
MKCALL = SHEETS_DIR / "tools" / "mkcall4.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = SHEETS_DIR / "tools" / "token-sync.json"
REPO = KIT_DIR.parents[4]  # the checkout's root
BASE = "33bb920225ec"  # the commit that merged the E08-D06 text (#4072): the boards cite the spec as at this commit


class _Doc:
    """A repo-relative doc read as at BASE (`git show BASE:<rel>` in this checkout; SPEC_MD5 refuses drifted bytes)."""

    def __init__(self, rel: str) -> None:
        self.rel, self.name = rel, rel.rsplit("/", 1)[-1]
        self._b: bytes | None = None

    def read_bytes(self) -> bytes:
        if self._b is None:
            res = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{self.rel}"], capture_output=True,
                                 timeout=60, check=False)
            if res.returncode != 0:
                raise SystemExit(f"e08d06kit: git show {BASE}:{self.rel} failed (a full clone of the repository "
                                 f"is needed): {res.stderr.decode(errors='replace').strip()[:200]}")
            self._b = res.stdout
        return self._b

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.read_bytes().decode(encoding)


SPEC = _Doc("docs/design/E08/E08-D06.md")
HANDOFF = _Doc("docs/design/E08/E08-D06-handoff.md")
SPEC_MD5 = {SPEC.name: "af8763f005d32c785db59e2212266b0e", HANDOFF.name: "50667e8f4cd0a4d1504a97c61ac15646"}
R2 = KIT_DIR / "r2" / "e08-d06-board.js.txt"  # the posted r2 script (4 parts joined), data block only
R2_SHA256 = "298c156fb3bcb1fc8cba78635082ebfc6472b35af07c39b368beb5e6c09be1a7"

FILE_NAME = "E08-D06 boards"
PAGE = "E08-D06 SCR-103 Symbol info"
REV = "r3"  # r1/r2 were the script's text rounds; the sheets are the first draw
# Live-check fold (2026-10-31): each drawn root's height = max(frame / caption bottom, annotation end) + MARGIN, as
# measured after touchTexts + relayout (the estimate runs long on the annotation column); the exports are these sizes.
MEASURED_H = {"1D": 1756, "1L": 1786, "3D": 1520, "6D": 1260, "10D": 994, "15D": 1098, "18D": 1298, "21D": 1560,
              "23D": 1259, "25D": 1549, "25H": 1694}
PITCH_X, PITCH_Y = 3000, 2400  # grid slot per board, computed for all 42 up front (a subset lands in place)
MARGIN = 80  # root margin and frame gutters (positions, not a flex gap)
CAP_DY = 28  # the "state: <fid>" caption sits 28 px above its frame
ANN_W = 400  # the ONE annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").split("\n")


def spec_md5_ok() -> dict[str, bool]:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() == SPEC_MD5[p.name] for p in (SPEC, HANDOFF)}


def r2_sha_ok() -> bool:
    return hashlib.sha256(R2.read_bytes()).hexdigest() == R2_SHA256


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok] + ([] if r2_sha_ok() else [R2.name])
if _DRIFT:  # every L<n> cite, every parsed string and every r2 datum assumes the pinned bytes
    raise SystemExit(f"e08d06kit: pinned input drifted ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _read(SPEC)
HANDOFF_LINES = _read(HANDOFF)


def _r2_data() -> dict[str, Any]:
    s = R2.read_text(encoding="utf-8")
    a = s.index("/*DATA-BEGIN*/") + len("/*DATA-BEGIN*/")
    return json.loads(s[a:s.index("/*DATA-END*/")])


D = _r2_data()  # r2's DATA block: struct, _fixture, _subst, copy, labels, bands, drawers, boards
R2_BOARDS = {b["n"]: b for b in D["boards"]}


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def find_line(needle: str, lines: list[str] | None = None, start: int = 1) -> int:
    """1-based number of the first line at or after start containing needle (raises if absent)."""
    ls = SPEC_LINES if lines is None else lines
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites: looked up, never typed as a number."""
    return find_line(needle, start=start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, HANDOFF_LINES, start)


def cite(s: str) -> str | None:
    """'L<n>' (spec) or 'H<n>' (hand-off) of the first line holding s verbatim (markdown backticks ignored), or None."""
    probe = s.strip().strip('"').strip()
    if len(probe) < 6:
        return None
    for tag, lines in (("L", SPEC_LINES), ("H", HANDOFF_LINES)):
        for i, ln in enumerate(lines, 1):
            if probe in ln or probe in ln.replace("`", ""):
                return f"{tag}{i}"
    return None


def in_spec(s: str) -> bool:
    """s appears verbatim (backticks ignored) in the spec or the hand-off. Long prose lines wrap at ~120 columns, so
    the check also accepts s when it spans two adjacent lines."""
    if cite(s):
        return True
    for lines in (SPEC_LINES, HANDOFF_LINES):
        for a, b in zip(lines, lines[1:]):
            if s in (a.replace("`", "").rstrip() + " " + b.replace("`", "").strip()):
                return True
    return False


# --- §15: the 25 boards and their 17 light twins (registry parsed from the spec)
@dataclass(frozen=True)
class Board:
    n: int  # §15's number
    sid: str  # §15's id, e.g. "SCR-103/populated-recorded-owner"
    w: int  # §15's size (the main frame)
    h: int
    twinned: bool  # §15 Twin "Y"
    content: str  # §15 Content cell
    line: int  # §15 line
    theme: str = "dark"  # dark | light (the light twin of 1-17)

    @property
    def key(self) -> str:
        return f"{self.n}{'D' if self.theme == 'dark' else 'L'}"

    @property
    def name(self) -> str:
        """The root's name: "E08-D06 / NN <§15 id>" (+ " · light" for a twin), r2's naming."""
        return f"E08-D06 / {self.n:02d} {self.sid.replace('/', PENPOT_SLASH)}" + (
            "" if self.theme == "dark" else f" · {self.theme}")

    @property
    def slug(self) -> str:
        return self.sid.split("/", 1)[1]

    @property
    def png(self) -> str:
        """§15's PNG name: the id lowercased, "/" -> "-", then the theme."""
        return f"{self.sid.lower().replace('/', '-')}-{self.theme}.png"

    @property
    def export(self) -> str:
        return f"docs/design/E08/img/{self.png}"

    @property
    def sheet(self) -> str:
        return f"{self.n:02d}-{self.slug}-{self.theme}.json"

    @property
    def twin_of(self) -> int | None:
        return self.n if self.theme != "dark" else None


_B_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([A-Z]+-\d{3}/[a-z0-9-]+)`\s*\|\s*(\d+) × (\d+)\s*\|\s*(Y|N)\s*\|(.*)\|"
                    r"\s*(PENDING \(BLOCKED-PENPOT\))\s*\|\s*$")


def _parse_boards() -> dict[str, Board]:
    s15 = find_line("## 15. Boards")
    s16 = find_line("## 16. Contract gaps", start=s15)
    out: dict[str, Board] = {}
    for i in range(s15, s16):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        b = Board(int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5) == "Y",
                  m.group(6).strip(), i)
        out[b.key] = b
        if b.twinned:
            t = Board(b.n, b.sid, b.w, b.h, True, b.content, b.line, "light")
            out[t.key] = t
    return out


BOARDS = _parse_boards()  # 42: "1D".."25D", "1L".."17L"
DARK = [k for k in BOARDS if k.endswith("D")]
LIGHT = [k for k in BOARDS if k.endswith("L")]


def key_of(nn: int | str) -> str:
    """1 -> "1D"; "1L" stays; "01L" -> "1L"."""
    if isinstance(nn, int):
        return f"{nn}D"
    m = re.fullmatch(r"0*(\d+)([DL]?)", nn)
    if not m:
        raise KeyError(nn)
    return f"{int(m.group(1))}{m.group(2) or 'D'}"


def grid_xy(key: str) -> tuple[int, int]:
    """Dark boards in rows of 5 (1-5, 6-10, ... 21-25), the light twins in rows of 5 below them (rows 5-8)."""
    b = BOARDS[key_of(key)]
    row = (b.n - 1) // 5 + (0 if b.theme == "dark" else 5)
    return ((b.n - 1) % 5) * PITCH_X, row * PITCH_Y


# --- the cap (ruling 10-30: <= 10 boards, twins <= 1/3) and the author groups (plan §4)
PROPOSED_TEN = ("1D", "1L", "3D", "6D", "10D", "18D", "21D", "23D", "25D", "15D")  # PROPOSED, waits on Q1
ALTERNATES = ("19D", "16D")  # 19 anatomy could replace 10D (23 carries AC 4's rows); 16 CMP-125
AUTHOR_GROUPS_CAP = {"A": ("1D", "1L", "3D", "6D", "10D"), "B": ("18D", "21D", "23D", "25D", "15D")}
AUTHOR_GROUPS_42 = {
    "A": ("1D", "2D", "3D", "4D", "5D", "6D"), "B": ("7D", "8D", "9D", "10D", "11D"),
    "C": ("12D", "13D", "14D", "24D", "25D"), "D": ("15D", "16D", "17D", "19D"),
    "E": ("18D", "20D", "21D", "22D", "23D"), "F": tuple(f"{n}L" for n in range(1, 10)),
    "G": tuple(f"{n}L" for n in range(10, 18)),
}


def undrawn(drawn: Iterable[str] = PROPOSED_TEN) -> list[str]:
    """The ids the §15 deviation names as "not drawn — the text is binding" under a cap set."""
    s = {key_of(k) for k in drawn}
    return [k for k in BOARDS if k not in s]


# --- §6: the states (first column, bold) and the frames each board draws (FRAME_PLAN, §15 sizes)
def _parse_states() -> dict[str, int]:
    a = find_line("| State (trigger)")
    b = find_line("Retry keeps focus on the button", start=a)
    out: dict[str, int] = {}
    for i in range(a + 2, b):
        m = re.match(r"^\|\s*\*\*(.+?)\*\*", SPEC_LINES[i - 1])
        if m:
            out[m.group(1)] = i
    return out


STATES = _parse_states()  # 23 §6 states -> line


@dataclass(frozen=True)
class Frame:
    fid: str  # the frame's id: its §6 state(s) and role, or §15's words
    w: int
    h: int
    density: str = "compact"
    states: tuple[str, ...] = ()  # §6 states the frame draws

    @property
    def caption(self) -> str:
        return f"state: {self.fid}"


_C = "compact"
FRAME_PLAN: dict[int, tuple[Frame, ...]] = {
    1: (Frame("Populated, recorded · Owner", 480, 1360, _C, ("Populated, recorded",)),),
    2: (Frame("Not recorded · Owner · SOLUSDT", 480, 1220, _C, ("Not recorded",)),),
    3: (Frame("Stale, T1 and Stale, T2 · Owner", 1000, 1360, _C, ("Stale, T1", "Stale, T2")),),
    4: (Frame("Reconnecting, disconnected · Owner", 480, 1360, _C, ("Reconnecting, disconnected",)),),
    5: (Frame("Awaiting the first tick and Live unavailable · Owner", 1000, 1360, _C,
              ("Awaiting the first tick", "Live unavailable")),),
    6: (Frame("Not trading · Closed · Owner · LUNAUSDT", 480, 1100, _C, ("Not trading",)),),
    7: (Frame("Not trading · Pre-launch, Delivering, Closed", 1480, 560, _C, ("Not trading",)),),
    8: (Frame("Catalogue loading · Owner", 480, 1060, _C, ("Catalogue loading",)),),
    9: (Frame("Rules changed while open · Owner · SOLUSDT", 480, 1360, _C, ("Rules changed while open",)),),
    10: (Frame("Contract load failed, Not in the instrument list, Forbidden · Owner", 480, 760, _C,
               ("Contract load failed", "Not in the instrument list", "Forbidden")),),
    11: (Frame("Coverage failed · Owner", 480, 1360, _C, ("Coverage failed",)),),
    12: (Frame("Populated, recorded · Manager", 480, 1260, _C, ("Populated, recorded",)),),
    13: (Frame("Populated, recorded · Viewer, column B", 480, 1220, _C, ("Populated, recorded",)),
         Frame("Viewer: A (ticket literal)", 480, 260, _C, ())),
    14: (Frame("Risk-limit tiers · collapsed, expanded, unavailable", 1040, 900, _C, ("Tiers unavailable",)),),
    15: (Frame("CMP-126 funding countdown · every condition", 960, 900, _C, ("Clock alarm",)),),
    16: (Frame("CMP-125 popover · default, stale, not trading, unavailable", 1100, 700, _C, ()),),
    17: (Frame("CMP-177 recorder status row · summary states", 960, 900, _C,
               ("Recording restricted", "Not recorded, Manager or Viewer", "Not recorded, Owner viewing as")),),
    18: (Frame("Precision rules · F1-F10 examples", 1200, 1100, _C, ()),),
    19: (Frame("Anatomy · bands, columns, tokens", 1000, 1400, _C, ("Populated, recorded",)),),
    20: (Frame("Over the workspace · 1280 × 800", 1280, 800, _C, ("Populated, recorded",)),
         Frame("200 % reflow · 640 × 400 CSS px", 640, 400, _C, ())),
    21: (Frame("Keyboard focus order · §10.1", 1000, 1400, _C, ()),),
    22: (Frame("Lifecycle wireflow · open, live, grace, revision, retry, close", 1600, 900, _C, ()),),
    23: (Frame("States matrix · §6", 1280, 980, _C, tuple(STATES)),),
    24: (Frame("Populated, recorded · Owner · comfortable", 480, 1720, "comfortable", ("Populated, recorded",)),),
    25: (Frame("Not recorded, Manager or Viewer · SOLUSDT", 480, 1220, _C, ("Not recorded, Manager or Viewer",)),
         Frame("Not recorded, Owner viewing as · SOLUSDT", 480, 1220, _C, ("Not recorded, Owner viewing as",))),
}
ILLUSTRATIVE = {9, 14, 15, 18}  # boards whose values are partly illustrative (spec L1-20 "marked so on the board")


def frames_of(key: str | int) -> tuple[Frame, ...]:
    return FRAME_PLAN[BOARDS[key_of(key)].n]


def frame_name(fr: Frame, theme: str) -> str:
    """The Penpot frame name: "SCR-103 · <fid> · <theme> · <density>" ("/" never appears: section paths split on it)."""
    name = f"SCR-103 · {fr.fid} · {theme} · {fr.density}"
    if "/" in name:
        raise ValueError(name)
    return name


# --- tokens (exact names in token-sync.json; the self-test checks every one). §3 "Tokens" is the binding slot list.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, OVERLAY = "color.surface.hover", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_LINK = "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, RING = "color.border.default", "color.border.subtle", "color.focus.ring"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
STATUS = "color.status"  # f"{STATUS}.{tone}.{strong|subtle|default}", tone in info / warning / danger / success
DC = "color.data-confidence"  # f"{DC}.stale.surface", f"{DC}.stale.text", f"{DC}.delisted.indicator" ...
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM = "type.num.base"  # §3: values, right-aligned, tabular figures
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
DIALOG_PAD, BUTTON_PADX = "space.dialog.padding", "space.button.paddingX"
ICON = "size.icon"
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, FOCUS_W = "border.hairline", "border.focus"
OPACITY_SCRIM, SHADOW_DIALOG, SHADOW_POPOVER = "opacity.scrim", "elevation.dialog", "elevation.popover"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12, STACK_LG: 16,
      DIALOG_PAD: 24, BUTTON_PADX: 12, ICON: 16}
ROW_H = {"compact": 24, "comfortable": 32}  # §3 "Rows size.row.height (24 / 32)"
CONTROL_H = {"compact": 24, "comfortable": 32}  # §10.3 "Targets 24 / 32 px"
ROLE_COLOR = {"text": TEXT_1, "text2": TEXT_2, "text3": TEXT_3}  # r2's _role
TONE_ICON = {"info": "info", "warning": "warning", "danger": "danger", "plain": "info"}
FALLBACKS = {
    "drawer-w": "kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)",
    "skeleton": "fallback: CMP-015 Skeleton drawn as static color.surface.hover bars (no motion.shimmer token, §10.3)",
    "glyphs": "the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons",
    "markers": "kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block "
               "naming its part ('at: ...') so no marker shifts the drawer's layout",
    "placeholder": "kit choice: SOLUSDT has no recorded ticker, so its live rows are drawn as labelled placeholder bars "
                   "(r2's 'placeholder'), never invented values",
    "popover-w": "kit choice: CMP-125 is drawn 400 px wide (no width in §9 or the hand-off)",
    "strip-tone": "kit choice: the CMP-078 escalated strip binds color.status.danger.subtle with the danger icon "
                  "(the words carry the state, §10.3)",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}

# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "spec_cites", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations",
              "derivations")


class _Notes:
    def __init__(self) -> None:
        self.d: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}

    def add(self, kind: str, line: str) -> None:
        if kind not in self.d:
            raise KeyError(kind)
        if line not in self.d[kind]:
            self.d[kind].append(line)

    def reset(self) -> None:
        self.d = {k: [] for k in NOTE_KINDS}


NOTES = _Notes()


def live(line: str) -> None:
    """A live_checks line: a measurable ACTION for the live drawer (read back X, expect Y)."""
    NOTES.add("live_checks", line)


def spec_gap(line: str) -> None:
    NOTES.add("spec_gaps", line)


def copy_gap(line: str) -> None:
    """A drawn string that is not verbatim in the spec (derived, substituted or a kit word): say where it comes from."""
    NOTES.add("copy_gaps", line)


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def derived(line: str) -> None:
    NOTES.add("derivations", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


# --- node primitives (cvsheet v4.2 schema; no inst nodes)
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a non-string
    o.wrap, and a banned string in the name, note or chars. Records bound tokens."""
    if t not in _KEYS:
        raise ValueError(f"node type {t!r} not allowed (no inst nodes in the per-set file)")
    if not name or "/" in name:
        raise ValueError(f"{t} name {name!r}: empty or contains '/'")
    n: Node = {"t": t, "name": name}
    n.update({k: v for k, v in kw.items() if v is not None})
    extra = set(n) - _KEYS[t]
    if extra:
        raise KeyError(f"{t} {name!r}: keys cvsheet rejects: {sorted(extra)}")
    o = n.get("o") or {}
    if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
        raise ValueError(f"{name!r}: o.wrap must be 'wrap' or 'nowrap', not {o['wrap']!r}")
    for s in (name, n.get("note") or "", n.get("chars") or ""):
        if BANNED.search(s):
            raise ValueError(f"{name!r}: banned string in {s[:60]!r}")
    for tk in [n.get(k) for k in ("typo", "color", "size")] + [v for k, v in o.items() if k in _TOKEN_OPTS]:
        if isinstance(tk, str):
            NOTES.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1, **kw: Any) -> Node:
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=str(chars), typo=typo, color=color, **kw)


def icon(name: str, glyph_: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph_ not in ICONS_OK:
        raise ValueError(f"icon {glyph_!r} not in the local set {sorted(ICONS_OK)}")
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


def rect(name: str, w_: float, h: float, fill: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w_, h=h, o=opts or None, **kw)


def unique_names(kids: Iterable[Node | None]) -> list[Node]:
    seen: dict[str, int] = {}
    out = []
    for k in kids:
        if not k:
            continue
        seen[k["name"]] = seen.get(k["name"], 0) + 1
        out.append(k if seen[k["name"]] == 1 else dict(k, name=f"{k['name']} · {seen[k['name']]}"))
    return out


def box(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return node("board", name, o=dict(o) if o else None, kids=unique_names(kids) or None, **kw)


def hbox(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return box(name, kids, {"dir": "row", "align": "center", **(o or {})}, **kw)


def vbox(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return box(name, kids, {"dir": "column", "align": "start", **(o or {})}, **kw)


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


# --- text metrics (estimates; Inter / JetBrains Mono)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM: (13, 1.2, True)}


def text_w(chars: str, typo: str) -> float:
    size, _lh, mono = _FONT.get(typo, _FONT[BODY])
    return round(len(chars) * (0.6 if mono else 0.56) * size, 1)


def text_lines(chars: str, typo: str, width: float) -> int:
    lines, cur = 1, ""
    for word in str(chars).split():
        trial = f"{cur} {word}" if cur else word
        if cur and text_w(trial, typo) > width:
            lines, cur = lines + 1, word
        else:
            cur = trial
    return lines


def text_h(typo: str, lines: int = 1) -> float:
    size, lh, _m = _FONT.get(typo, _FONT[BODY])
    return round(size * lh * lines, 1)


def _px(v: Any) -> int:
    return PX.get(v, 0) if isinstance(v, str) else 0


def est_width(n: Node) -> float:
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
        return pad + sum(est_width(k) for k in kids) + _px(o.get("gap")) * max(len(kids) - 1, 0)
    if o.get("dir") == "column":
        return pad + max((est_width(k) for k in kids), default=0.0)
    return max((float(k.get("x", 0)) + est_width(k) for k in n.get("kids") or []), default=0.0)


def est_height(n: Node) -> float:
    if n.get("h"):
        return float(n["h"])
    if n["t"] == "text":
        return text_h(n["typo"], text_lines(n["chars"], n["typo"], n["w"]) if n.get("w") else 1)
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padY")) + _px(o.get("padT")) + _px(o.get("padB"))
    if o.get("dir") == "column":
        return pad + sum(est_height(k) for k in kids) + _px(o.get("gap")) * max(len(kids) - 1, 0)
    if o.get("dir") == "row":
        return pad + max((est_height(k) for k in kids), default=0.0)
    return max((float(k.get("y", 0)) + est_height(k) for k in n.get("kids") or []), default=0.0)


def fit_text(name: str, chars: str, typo: str, color: str, room: float, **kw: Any) -> Node:
    """A text that wraps inside `room` px when it is wider (w set), else hugs."""
    return text(name, chars, typo, color, **({"w": room} if text_w(chars, typo) > room else {}), **kw)


# --- §5 formatters (F3-F7, F10): decimal strings in, display strings out; never float
MINUS = "−"  # r2's minus sign for negative rates ("−0.00771 %")


def _plain(d: Decimal) -> str:
    s = format(d, "f")
    return s if s not in ("-0",) else "0"


def minimal(s: str) -> str:
    """F3: drop trailing fractional zeros, never a significant digit, positional only ("0.10" -> "0.1", "100.000"
    -> "100", F2 expands "1E-7" -> "0.0000001")."""
    d = Decimal(s)
    t = _plain(d.normalize()) if d != d.to_integral() else _plain(d.quantize(Decimal(1)))
    return t


def decimals(s: str) -> int:
    t = minimal(s)
    return len(t.split(".")[1]) if "." in t else 0


def group(s: str) -> str:
    """F8: a comma groups the integer part only; the decimal point is '.'."""
    neg = s.startswith("-")
    ip, _, fp = s.lstrip("-").partition(".")
    ip = f"{int(ip):,}"
    return ("-" if neg else "") + ip + (f".{fp}" if fp else "")


def rule_value(s: str) -> str:
    """F3 + F8: a rule value in minimal exact form, grouped."""
    return group(minimal(s))


def at_precision(v: str, unit: str) -> str:
    """F4 / F5: the larger of the tick's (step's) decimals and the value's own significant decimals; never rounded."""
    n = max(decimals(unit), decimals(v))
    return group(_plain(Decimal(v).quantize(Decimal(1).scaleb(-n))))


def change_pct(frac: str) -> str:
    """F6: the 24 h change, x100 exact, half-even to 2 decimals, ▲ / ▼ with a sign; zero takes neither."""
    p = (Decimal(frac) * 100).quantize(Decimal("0.01"), ROUND_HALF_EVEN)
    if p == 0:
        return "0.00 %"
    return f"▲ +{_plain(p)} %" if p > 0 else f"▼ {MINUS}{_plain(-p)} %"


def funding_pct(frac: str) -> str:
    """F6: funding x100 by an exact shift, at least 4 decimals, with a sign; zero "0.0000 %"."""
    p = Decimal(frac) * 100
    n = max(4, decimals(_plain(p)))
    q = _plain(abs(p).quantize(Decimal(1).scaleb(-n)))
    return f"0.{'0' * 4} %" if p == 0 else (f"+{q} %" if p > 0 else f"{MINUS}{q} %")


_UNITS = (("", 0), ("K", 3), ("M", 6), ("B", 9))
_DISK = (("B", 0), ("kB", 3), ("MB", 6), ("GB", 9), ("TB", 12))


def magnitude(v: str, units: tuple[tuple[str, int], ...] = _UNITS) -> str:
    """F7: 3 significant figures, half-even, K / M / B (or decimal disk units); 999.6 M -> 1.00 B."""
    d = abs(Decimal(v))
    i = 0
    while i + 1 < len(units) and d >= Decimal(10) ** units[i + 1][1]:
        i += 1
    x = d.scaleb(-units[i][1])
    while True:
        q = x.quantize(Decimal(1).scaleb(x.adjusted() - 2), ROUND_HALF_EVEN) if x else Decimal("0.00")
        if q >= 1000 and i + 1 < len(units):  # the rounded value reached 1,000: the next unit, re-rounded
            x, i = q.scaleb(-3), i + 1
            continue
        return f"{_plain(q)} {units[i][0]}".strip()


def disk(nbytes: int) -> str:
    return magnitude(str(nbytes), _DISK)


def utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def hms(ms: int) -> str:
    return utc(ms).strftime("%H:%M:%S")


def clock(seconds: int) -> str:
    """CMP-126's fixed-width hh:mm:ss (seconds floored by the caller)."""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def gap_span(start_iso: str, end_iso: str) -> str:
    """F10: a gap in minutes, the start rounded down and the end rounded up ("02:11:00-02:14:20" -> "02:11–02:15")."""
    a, b = (datetime.fromisoformat(x) for x in (start_iso, end_iso))
    s = int((Decimal(a.minute * 60 + a.second) / 60).to_integral_value(ROUND_FLOOR))
    e = int((Decimal(b.minute * 60 + b.second) / 60).to_integral_value(ROUND_CEILING))
    return f"{a.hour:02d}:{s:02d}–{b.hour + e // 60:02d}:{e % 60:02d}"


def day_mon(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


# --- the frame data (spec L1-20 "Frame data"): fixture values through the formatters; r2's strings are the check
FX = D["_fixture"]
INSTR: dict[str, dict[str, Any]] = FX["instruments"]  # instruments_after.json values as delivered
TICKER: dict[str, Any] = FX["ticker"]  # the recorded BTCUSDT snapshot line (2026-10-19)
CONTRACT_WORDS = {"LinearPerpetual": "USDT perpetual"}  # §4.1 identity line's wording
STATUS_WORDS = {"Trading": "Trading", "PreLaunch": "Pre-launch", "Delivering": "Delivering", "Closed": "Closed"}
REC = {  # `22`'s RecordedSymbol / DataCoverage examples (spec §4.3, §5 F7, F10)
    "disk_bytes": 812340221100, "as_of": "10:31:02",
    "streams": (("trades", "2026-09-01T00:00:00+00:00"), ("order book", "2026-09-07T00:00:00+00:00")),
    "gap": ("2026-09-04T02:11:00+00:00", "2026-09-04T02:14:20+00:00", "connection lost"),
    "started_at": "2026-09-01 00:00 UTC",  # `22`'s recording_started_at example, board 18's after-CR-8 column only
}
CLOCK_SKEW_MS = 612  # §7's example
COUNTDOWN_S = {"lt1h": 3599, "lt5m": 252}  # §7's "< 1 h" and "< 5 min" rows (spec values, not the fixture's)


def rules(sym: str) -> dict[str, str]:
    """§4.1 rows for an instrument, F3 minimal exact form (+ "×" for leverage, hours for the interval)."""
    i = INSTR[sym]
    mins = int(i["funding"])
    return {"status": STATUS_WORDS.get(i["status"], i["status"]), "tick": rule_value(i["tick"]),
            "step": rule_value(i["step"]), "minQty": rule_value(i["minQty"]), "maxQty": rule_value(i["maxQty"]),
            "minNotional": rule_value(i["minNotional"]), "maxLev": rule_value(i["maxLev"]) + "×",
            "levStep": rule_value(i["levStep"]), "funding": f"{mins // 60} h" if mins % 60 == 0 else f"{mins} min",
            "identity": f"{i['base']} / {i['quote']} · {CONTRACT_WORDS[i['contract']]} · settled in {i['settle']} · "
                        f"listed {utc(int(i['launch'])).strftime('%Y-%m-%d')}"}


def to_go_s(t: dict[str, Any] = TICKER) -> int:
    return (int(t["nextFundingTime"]) - int(t["ts"])) // 1000


def live_values(t: dict[str, Any] = TICKER, sym: str = "BTCUSDT") -> dict[str, str]:
    """§4.2 rows from one ticker item (F4-F7), with the §7 countdown at the item's own time."""
    tick, step = INSTR[sym]["tick"], INSTR[sym]["step"]
    nxt = utc(int(t["nextFundingTime"])).strftime("%H:%M")
    return {"last": at_precision(t["lastPrice"], tick), "mark": at_precision(t["markPrice"], tick),
            "index": at_precision(t["indexPrice"], tick), "chg": change_pct(t["price24hPcnt"]),
            "high": at_precision(t["highPrice24h"], tick), "low": at_precision(t["lowPrice24h"], tick),
            "vol": at_precision(t["volume24h"], step), "turn": magnitude(t["turnover24h"]),
            "oi": at_precision(t["openInterest"], step), "oiv": magnitude(t["openInterestValue"]),
            "rate": funding_pct(t["fundingRate"]), "updated": f"Updated {hms(int(t['ts']))} UTC",
            "lastUpdate": f"Last update {hms(int(t['ts']))} UTC",
            "cd": f"next in {clock(to_go_s(t))} · {nxt} UTC"}


def countdown_text(cond: str, t: dict[str, Any] = TICKER, sym: str = "BTCUSDT") -> tuple[str, str | None]:
    """§7's shown text for a condition: ge1h, lt1h, lt5m, elapsed, clock, unknown, suppressed -> (line, second)."""
    nxt = utc(int(t["nextFundingTime"]))
    hm = nxt.strftime("%H:%M")
    s = to_go_s(t)
    out = {"ge1h": (f"next in {clock(s)} · {hm} UTC", None),
           "lt1h": (f"next in {clock(COUNTDOWN_S['lt1h'])} · {hm} UTC", None),
           "lt5m": (f"settles in {clock(COUNTDOWN_S['lt5m'])} · {hm} UTC", None),
           "elapsed": ("Settlement time passed — waiting for an update", None),
           "clock": (f"at {nxt.strftime('%H:%M:%S')} UTC (in about {s // 3600} h {s % 3600 // 60} min)",
                     f"Clock skew {CLOCK_SKEW_MS} ms — the countdown may be off"),
           "unknown": ("Next funding time not available", None),
           "suppressed": (f"No funding — {sym} is not trading.", None)}
    return out[cond]


def rec_values() -> dict[str, str]:
    st = " · ".join(f"{name} from {day_mon(iso)}" for name, iso in REC["streams"])
    a, b, why = REC["gap"]
    return {"asOf": f"Coverage as of {REC['as_of']} UTC · trades can include imported days", "streams": st,
            "gaps": f"1 · {day_mon(a)} {gap_span(a, b)} UTC, {why}", "disk": disk(REC["disk_bytes"])}


def tier_rows(n: int = 12) -> list[tuple[str, str, str]]:
    """Board 14's illustrative tiers (§4.4, marked illustrative): the axis steps 600,000 USDT from 2,000,000 and the
    initial margin 0.2 points from 1 %, so Max leverage = 1 / margin, truncated to 0.01 (never rounded up past the
    exchange's cap) in F3 minimal form. Consistent with r2's eight drawn rows (the self-test checks it)."""
    out = []
    for i in range(n):
        value = 2_000_000 + 600_000 * i
        lev = (Decimal(100) / (1 + Decimal("0.2") * i)).quantize(Decimal("0.01"), ROUND_FLOOR)
        out.append((str(i + 1), group(str(value)), rule_value(str(lev)) + "×"))
    return out


def r2_consistency() -> list[str]:
    """Every r2 value the kit re-derives, compared; [] means r2's DATA agrees with the formatters."""
    bad = []
    for sym, shown in FX["shown"].items():
        for k_, v in rules(sym).items():
            if k_ in shown and shown[k_] != v:
                bad.append(f"{sym}.{k_}: r2 {shown[k_]!r} != {v!r}")
    for k_, v in live_values().items():
        if FX["live"].get(k_) != v:
            bad.append(f"live.{k_}: r2 {FX['live'].get(k_)!r} != {v!r}")
    c = D["copy"]
    for k_, v in rec_values().items():
        if c.get(k_) != v:
            bad.append(f"rec.{k_}: r2 {c.get(k_)!r} != {v!r}")
    r2t = R2_BOARDS[14]["tiers"]["rows"]
    if [tuple(r) for r in r2t] != tier_rows()[:len(r2t)]:
        bad.append(f"tiers: r2 {r2t} != {tier_rows()[:len(r2t)]}")
    cds = {r.get("cond"): r.get("v") for r in R2_BOARDS[15]["cmp126"]["rows"] if r.get("v")}
    for cond, key in (("≥ 1 h", "ge1h"), ("< 1 h", "lt1h"), ("< 5 min", "lt5m"), ("elapsed, no fresh ticker", "elapsed"),
                      ("clock alarm on, or offset unknown", "clock"), ("next funding time unknown", "unknown"),
                      ("not trading", "suppressed")):
        if cds.get(cond) != countdown_text(key)[0]:
            bad.append(f"cmp126 {cond}: r2 {cds.get(cond)!r} != {countdown_text(key)[0]!r}")
    return bad


# --- drawer geometry (§2 D-14, §3): 480 px, space.dialog.padding 24, value column for 11 characters (E30-D02 §5.4)
DRAWER_W = 480
INNER = DRAWER_W - 2 * PX[DIALOG_PAD]  # 432
VALUE_W = 104  # 11 mono characters (85.8 px) + 8 px a side
UNIT_W = 80  # the fixed unit column; also holds the "can change" tag (61.6 px + 8 px a side)
LABEL_W = INNER - VALUE_W - UNIT_W  # 248: the longest §4.1 label, "Maximum quantity, market orders", needs 242
REC_LABEL_W = 176  # the CandleViewer band: label | one start-aligned value cell (wraps)
CD_LABEL_W = 136  # the Next funding row: CMP-126 spans the value and unit columns (§3) and the free label room


def cell(key: str, content: str | Node | list[Node] | None, w_: int, *, h: int, end: bool = False,
         typo: str = BODY, color: str = TEXT_1, note: str | None = None) -> Node:
    """One cell, padded space.inset.sm (8 px) a side, so adjacent texts sit >= 16 px apart; text wraps inside it."""
    room = w_ - 2 * PX[INSET_SM]
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        kids = [fit_text("text", content, typo, color, room)]
    else:
        kids = content if isinstance(content, list) else [content]
    return hbox(f"cell · {key}", kids, {"padX": INSET_SM, "justify": "end" if end else "start", "gap": INSET_XS},
                w=w_, h=h, note=note)


def _row_h(cells: list[Node], density: str) -> int:
    need = max((est_height(dict(c, h=None)) for c in cells), default=0.0) + 4  # 2 px above and below the text
    return max(ROW_H[density], int(math.ceil(need / 4) * 4))


def dl_row(label: str, value: str | Node, *, kind: str = "num", unit: str | None = None, tag: str | None = None,
           density: str = "compact", stale: bool = False, w_: int = INNER, note: str | None = None,
           col: str = "rules") -> Node:
    """One dt / dd pair (§10.2 'facts': one value per row, F8). kind (r2's _vk): num (value end-aligned in the
    11-character column + unit column), na ("not available yet", color.text.tertiary, spans value + unit), word
    (Status), cd (CMP-126 node or text spanning the value side), cdword (a countdown sentence), rec / recnum (the
    CandleViewer band: one start-aligned cell; col="rec" puts a na row there too). stale: values in color.data-confidence.stale.text (§6 Stale, T1).
    A tag beside a unit ("Changed · was 0.01") goes on a line under the value (the value column never moves)."""
    vcol = f"{DC}.stale.text" if stale else TEXT_1
    if isinstance(value, str) and set(value) & set("●○◐▲▼✕"):
        fallback("glyphs")
    if kind in ("rec", "recnum") or col == "rec":
        lw, vw = REC_LABEL_W, w_ - REC_LABEL_W
        val = [cell("dd", value, vw, h=1, typo=NUM if kind == "recnum" else BODY,
                    color=TEXT_3 if kind == "na" else (TEXT_2 if label == "Recording" else vcol))]
    elif kind in ("cd", "cdword"):
        lw, vw = CD_LABEL_W, w_ - CD_LABEL_W
        val = [cell("dd", value, vw, h=1, end=kind == "cd", typo=NUM if kind == "cd" else BODY, color=vcol)]
    elif kind in ("na", "word"):
        lw, vw = w_ - VALUE_W - UNIT_W, VALUE_W + UNIT_W
        val = [cell("dd", value, vw, h=1, color=TEXT_3 if kind == "na" else vcol)]
    elif kind == "num":
        lw = w_ - VALUE_W - UNIT_W
        side = tag if (tag and not unit) else unit
        val = [cell("dd", value, VALUE_W, h=1, end=True, typo=NUM, color=vcol),
               cell("unit" if side == unit else "tag", side, UNIT_W, h=1, typo=CAPTION,
                    color=TEXT_3 if side == unit else TEXT_2)]
    else:
        raise ValueError(f"dl_row kind {kind!r}")
    lab = cell("dt", label, lw, h=1, color=TEXT_2)
    if text_w(label, BODY) > lw - 2 * PX[INSET_SM]:
        raise ValueError(f"label {label!r} wider than its {lw} px cell")
    h = _row_h([lab, *val], density)
    kids = [dict(c, h=h) for c in [lab, *val]]
    row = hbox(f"row · {label}", kids, None, w=w_, h=h, note=note or "dt / dd pair (§10.2)")
    if tag and unit and kind == "num":
        sub = hbox(f"tag · {label}", [text("text", tag, CAPTION, TEXT_1)], {"padX": INSET_SM, "justify": "end"},
                   w=w_, h=16, note='"Changed" tag with the old value (§2 D-13); static, never flashes (§10.3)')
        return vbox(f"row · {label} · changed", [row, sub], None, w=w_, h=h + 16)
    return row


def line(key: str, chars: str, *, typo: str = CAPTION, color: str = TEXT_2, align: str = "left",
         w_: int = INNER, indent: int = 0) -> Node:
    """A band line (as-of, provenance, note, sentence), padded 8 px a side (+ indent), wrapping."""
    o: dict[str, Any] = {"padL": INSET_LG if indent else INSET_SM, "padR": INSET_SM,
                         "justify": "end" if align == "right" else "start"}
    room = w_ - PX[o["padL"]] - PX[INSET_SM]
    t = fit_text("text", chars, typo, color, room)
    return hbox(f"line · {key}", [t], o, w=w_, h=int(math.ceil(est_height(t) / 2) * 2))


def example(chars: str, w_: int = INNER) -> Node:
    """§3: an example line under its rule row, type.ui.caption in color.text.tertiary, indented."""
    return line("example", chars, typo=CAPTION, color=TEXT_3, w_=w_, indent=1)


def band_rule(w_: int = INNER) -> Node:
    return rect("band rule", w_, 1, BORDER, note="border.hairline in color.border.default; decorative (1.30:1, §13)")


def chip(kind: str, chars: str) -> Node:
    """CMP-239 marker (stale, delisted, ...): words in color.data-confidence.<kind>.text on a hairline in .indicator."""
    t = text("text", chars, CAPTION, f"{DC}.{kind}.text")
    return hbox(f"CMP-239 {kind}", [t], {"padX": INSET_XS, "radius": R_BADGE, "stroke": f"{DC}.{kind}.indicator",
                                         "strokeWidth": HAIR, "strokeAlign": "inner"},
                w=round(text_w(chars, CAPTION) + 2 * PX[INSET_XS] + 2), h=20, note="CMP-239; never stacked")


def band(title: str, tag: str, kids: Iterable[Node | None], *, stale: bool = False, marker: Node | None = None,
         w_: int = INNER, density: str = "compact") -> Node:
    """A band (§2 D-1): section with its h3 and source tag on one header row, the decorative rule above, its rows.
    stale: the band surface color.data-confidence.stale.surface (§6 Stale)."""
    left = hbox("heading", [text("h3", title, HEADING_SM, TEXT_1), marker], {"gap": INSET_SM})
    head = hbox("band header", [left, text("source tag", tag, CAPTION, TEXT_2)],
                {"padX": INSET_SM, "justify": "space-between"}, w=w_, h=ROW_H[density])
    o: dict[str, Any] = {"gap": STACK_XS}
    if stale:
        o["fill"] = f"{DC}.stale.surface"
    return vbox(f"band · {title}", [band_rule(w_), head, *kids], o, w=w_,
                note=f'section aria-labelledby its h3 "{title}"')


# --- controls (CMP-001 / CMP-002 / CMP-021 / CMP-039 compositions; 24 / 32 px targets, §10.3)
BUTTON_LOOK = {"primary": (ACTION_PRIMARY, TEXT_ON_ACTION), "secondary": (ACTION_SECONDARY, TEXT_1),
               "ghost": (None, TEXT_2)}


def ring(control: Node, radius: str = R_CONTROL) -> Node:
    """CMP-039 focus-visible: a wrapper with 4 px padding and a color.focus.ring stroke at border.focus (§10.1)."""
    return hbox("focus-ring", [control], {"pad": INSET_XS, "radius": radius, "stroke": RING, "strokeWidth": FOCUS_W,
                                          "strokeAlign": "inner"}, note="focus-visible (CMP-039; a real outline)")


def button(chars: str, variant: str = "secondary", *, density: str = "compact", focused: bool = False,
           name: str | None = None, lead: Node | None = None, note: str | None = None) -> Node:
    fill_, col = BUTTON_LOOK[variant]
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center"}
    if fill_:
        o["fill"] = fill_
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, o, w=wd, h=CONTROL_H[density], note=note or "CMP-001 button")
    return ring(b) if focused else b


def close_button(*, density: str = "compact", focused: bool = False) -> Node:
    s = CONTROL_H[density]
    b = hbox("CMP-002 close", [icon("glyph", "close", TEXT_2)], {"justify": "center", "radius": R_CONTROL}, w=s, h=s,
             note='CMP-002 button, name "Close symbol info" (§10.2); Esc closes (§10.1)')
    return ring(b) if focused else b


def link(chars: str, *, focused: bool = False, w_: int = INNER, density: str = "compact") -> Node:
    t = hbox("CMP-021 link", [text("text", chars, BODY, TEXT_LINK)], None, h=ROW_H[density],
             note=f'CMP-021 a "{chars}" (§10.2)')
    return hbox(f"link · {chars}", [ring(t) if focused else t], {"padX": INSET_SM}, w=w_,
                h=ROW_H[density] + (2 * PX[INSET_XS] if focused else 0))


def buttons_row(specs: Iterable[tuple[str, str]], *, density: str = "compact", w_: int = INNER,
                focused: str | None = None, name: str = "buttons") -> Node:
    bs = [button(c, v, density=density, focused=c == focused) for c, v in specs]
    return hbox(name, bs, {"padX": INSET_SM, "gap": INSET_SM}, w=w_,
                h=round(max(est_height(b) for b in bs)) if bs else CONTROL_H[density])


# --- notices and errors (CMP-028 notice, CMP-027 inline error / warning, CMP-078 strip, CMP-015 skeleton)
def _tone_box(name: str, tone: str, lines: list[str], *, btns: Iterable[tuple[str, str]] = (), ref: str | None = None,
              w_: int = INNER, density: str = "compact", note: str | None = None) -> Node:
    """A toned box: the glyph + first line (body-strong), the other lines (body), buttons, the Ref line. tone info /
    warning / danger binds color.status.<tone>.subtle + .strong; plain binds color.surface.raised + border.default."""
    room = w_ - 2 * PX[INSET_MD]
    fill_, stroke = ((RAISED, BORDER) if tone == "plain" else (f"{STATUS}.{tone}.subtle", f"{STATUS}.{tone}.strong"))
    gcol = TEXT_2 if tone == "plain" else f"{STATUS}.{tone}.strong"
    first = hbox("lead", [icon("glyph", TONE_ICON[tone], gcol),
                          fit_text("text", lines[0], BODY_STRONG, TEXT_1, room - 20)], {"gap": INSET_XS, "align": "start"})
    rest = [fit_text(f"line-{i}", ln, BODY, TEXT_1, room) for i, ln in enumerate(lines[1:], 2)]
    bl = list(btns)
    kids: list[Node | None] = [first, *rest,
                               buttons_row(bl, density=density, w_=room, name="actions") if bl else None,
                               text("ref", ref, CAPTION, TEXT_3) if ref else None]
    return vbox(name, kids, {"pad": INSET_MD, "gap": STACK_SM, "radius": R_CARD, "fill": fill_, "stroke": stroke,
                             "strokeWidth": HAIR, "strokeAlign": "inner"}, w=w_, note=note)


def notice(tone: str, lines: list[str], *, w_: int = INNER) -> Node:
    """CMP-028 notice under the title (not trading: danger with the delisted chip; pre-launch: info, §2 D-5)."""
    return _tone_box(f"CMP-028 notice · {tone}", tone, lines, w_=w_,
                     note="status notice; tabindex=-1 takes focus when a focused action disappears (§10.1)")


def inline_error(tone: str, lines: list[str], *, btns: Iterable[tuple[str, str]] = (), ref: str | None = None,
                 w_: int = INNER, density: str = "compact") -> Node:
    """CMP-027 (§6): contract failure role="alert" once; coverage and live role="status"."""
    role = 'role="alert" (contract load failed, once)' if tone == "danger" else 'role="status" (polite once)'
    return _tone_box(f"CMP-027 {tone}", tone, lines, btns=btns, ref=ref, w_=w_, density=density,
                     note=f"CMP-027 {tone}; {role}; Retry keeps focus, aria-busy on its band (§6)")


def strip(chars: str, *, w_: int = INNER) -> Node:
    """CMP-078 escalated strip (§6 Stale, T2)."""
    fallback("strip-tone")
    return hbox("CMP-078 escalated", [icon("glyph", "danger", f"{STATUS}.danger.strong"),
                                      fit_text("text", chars, BODY_STRONG, TEXT_1, w_ - 44)],
                {"padX": INSET_SM, "gap": INSET_XS, "radius": R_CARD, "fill": f"{STATUS}.danger.subtle"}, w=w_, h=32,
                note="CMP-078 escalated; the shell's assertive T2 sentence is never repeated here (§6)")


def skeleton(n: int, labels: Iterable[str] | None = None, *, w_: int = INNER, density: str = "compact",
             placeholder: bool = False) -> Node:
    """CMP-015 static skeleton rows (aria-busy, §6 Awaiting / Catalogue loading) or, placeholder=True, labelled
    placeholder bars where no recorded value exists (SOLUSDT's live band)."""
    fallback("placeholder" if placeholder else "skeleton")
    labs = list(labels or [])
    rows = []
    for i in range(n):
        lab = (cell("dt", labs[i], LABEL_W, h=ROW_H[density], color=TEXT_2) if i < len(labs) else
               cell("dt", [rect("bar", 120, 12, HOVER)], LABEL_W, h=ROW_H[density]))
        val = cell("dd", [rect("bar", VALUE_W - 24, 12, HOVER)], VALUE_W, h=ROW_H[density], end=True)
        rows.append(hbox(f"row · {labs[i] if i < len(labs) else f'skeleton {i + 1}'}", [lab, val], None,
                         w=w_, h=ROW_H[density]))
    nm = "placeholder rows" if placeholder else "CMP-015 skeleton"
    return vbox(nm, rows, None, w=w_, h=n * ROW_H[density],
                note="placeholder: no recorded value for this symbol" if placeholder else 'aria-busy="true"; static')


def scrim(w_: int, h: int, *, x: int = 0, y: int = 0) -> Node:
    """§3: color.surface.sunken at opacity.scrim, below the TopBar and the SCR-152 slot (E08-D05 D-11)."""
    return rect("scrim", w_, h, SUNKEN, {"opacity": OPACITY_SCRIM}, x=x, y=y, abs=True, note="inert subtree")


def scr152_banner(*, w_: int = DRAWER_W) -> Node:
    """The SCR-152 banner, live above the scrim (§6 Reconnecting): r2's copy.banner words."""
    b = D["copy"]["banner"]
    room = w_ - 2 * PX[INSET_MD]
    kids = [hbox("lead", [icon("glyph", "warning", f"{STATUS}.warning.strong"),
                          fit_text("title", b["title"], BODY_STRONG, TEXT_1, room - 20)], {"gap": INSET_XS}),
            *[fit_text(f"body-{i}", t, BODY, TEXT_1, room) for i, t in enumerate(b["body"], 1)],
            buttons_row([(a, "secondary") for a in b["actions"]], w_=room, name="actions")]
    return vbox("SCR-152 banner", kids, {"pad": INSET_MD, "gap": STACK_SM, "fill": f"{STATUS}.warning.subtle"},
                w=w_, note="SCR-152 slot: live above the scrim; the shell's alert (E17-D01 §7)")


# --- CMP-126 funding countdown (§7; E24-D01's ladder)
def countdown(cond: str, *, stale: bool = False, t: dict[str, Any] = TICKER, sym: str = "BTCUSDT") -> Node:
    """§7: digits in type.num.base (aria-live="off"); words in type.ui.body; < 5 min leads with the ⚠ glyph in
    color.status.warning.strong; clock adds the skew line. Never negative, never a frozen 00:00:00."""
    first, second = countdown_text(cond, t, sym)
    col = f"{DC}.stale.text" if stale else TEXT_1
    digits = cond in ("ge1h", "lt1h", "lt5m")
    lead = [icon("glyph", "warning", f"{STATUS}.warning.strong")] if cond == "lt5m" else []
    row = hbox("line", [*lead, text("text", first, NUM if digits else BODY, col)], {"gap": INSET_XS})
    kids: list[Node] = [row] + ([text("skew", second, CAPTION, TEXT_2)] if second else [])
    s = to_go_s(t)
    name_ = f"Next funding in {s // 3600} hour {s % 3600 // 60} minutes, at {utc(int(t['nextFundingTime'])):%H:%M} UTC"
    return vbox(f"CMP-126 countdown · {cond}", kids, {"gap": STACK_XS, "align": "end"},
                note=f'aria-live="off"; updates at most once a second; name "{name_}" (§7)' if digits else
                "words, no countdown (§7)")


# --- CMP-177 recorder status row, summary variant (§4.3, §8; hand-off A-6: the state word in color.text.secondary)
def _parse_rec_words() -> list[str]:
    a = find_line("| Store value")
    b = find_line("Gate causes", start=a)
    out: list[str] = []
    for i in range(a + 2, b):
        c = _cells(SPEC_LINES[i - 1])
        if len(c) < 2:
            continue
        qs = re.findall(r'"([^"]+)"', c[1])
        if qs and qs[0].startswith("● Recording · ") and not qs[0].endswith("min"):
            head = qs[0].rsplit(" · ", 1)[0]
            qs = [qs[0]] + [f"{head} · {q}" for q in qs[1:]]
        out += qs
    return [q for q in dict.fromkeys(out) if q != "Not recorded"]  # the bare one is §4.3's "never" wording


REC_WORDS = _parse_rec_words()  # every §4.3 "Shown" string, the five reasons expanded


def recorder_row(word: str, *, says: Iterable[str] = (), record: bool = False, settings: bool = False,
                 owner_rows: Iterable[tuple[str, str]] = (), density: str = "compact", w_: int = INNER,
                 focused: str | None = None) -> Node:
    """The CandleViewer band's state row and what follows it in the band (§4.3, §8): the state word (glyph + words,
    color.text.secondary), the T2 / T3 sentences (text, no control), the Owner's rows (disk, retention), Record this
    symbol… (Owner, not recorded) and the Recorder settings link (Owner)."""
    if word not in REC_WORDS:
        raise ValueError(f"{word!r} is not a §4.3 state string")
    kids: list[Node | None] = [dl_row("Recording", word, kind="rec", density=density, w_=w_,
                                      note="CMP-177 summary: glyph + words; colour never alone (§10.3)")]
    kids += [dl_row(lab, v, kind="recnum" if lab.startswith("Size") else "rec", density=density, w_=w_)
             for lab, v in owner_rows]
    kids += [sentence(s, w_=w_) for s in says]
    if record:
        kids.append(buttons_row([(D["copy"]["record"], "secondary")], density=density, w_=w_, name="record",
                                focused=D["copy"]["record"] if focused == "record" else None))
    if settings:
        kids.append(link(D["copy"]["settings"], w_=w_, density=density, focused=focused == "settings"))
    return vbox("CMP-177 recorder status", kids, {"gap": STACK_XS}, w=w_)


T2_OWNER_ONLY = "Only the owner can start recording."  # rbac.owner_only (§8, E09-D09 §2.4 row (ii))
T2_VIEW_AS = "Read-only while viewing as alex."  # rbac.view_as, drawn with SCR-124's user (§8)
T3_SENTENCE = "Recording is set up by the owner."  # the hidden SCR-140 link's sentence form (§8)
SENTENCE_NOTES = {
    T2_OWNER_ONLY: "T2 sentence form: CMP-079 RbacGate renders CMP-026 with cta omitted; no lock glyph, no button, "
                   "no aria-disabled (§8); read in browse order (§10.2)",
    T2_VIEW_AS: "T2 view-as leg first (E09-D09 step 3a): CMP-026 description, no control (§8)",
    T3_SENTENCE: "T3: the SCR-140 link hidden, this sentence in its place (§8); never borrowed by a T2 reason",
}


def sentence(chars: str, *, w_: int = INNER, role: str = "text2") -> Node:
    """A band sentence (r2's "say"): body text in its role colour; the T2 / T3 sentences carry their §8 note."""
    n = line("sentence", chars, typo=BODY, color=ROLE_COLOR[role], w_=w_)
    return dict(n, note=SENTENCE_NOTES.get(chars, "sentence (§6)"))


# --- §4.4 risk-limit tiers (D-8): a captioned table; collapsed 3 rows + "Show all N tiers"; expanded <= 8 + region
TIER_COLS = (("tier", "Tier", 64, True), ("value", "Position value up to, USDT", 224, True),
             ("lev", "Max leverage", 144, True))  # the margin columns stay hidden until CR-4 (§4.4)


def tiers(state: str, *, density: str = "compact", w_: int = INNER, sym: str = "BTCUSDT",
          focused: str | None = None) -> Node:
    """state: collapsed | expanded | unavailable. Rows are board 14's illustrative tiers (tier_rows())."""
    if state == "unavailable":
        return line("tiers", "Risk-limit tiers: not available yet", typo=BODY, color=TEXT_3, w_=w_)
    rows_ = tier_rows()
    shown = rows_[:3] if state == "collapsed" else rows_[:8]
    rh = ROW_H[density]
    head = hbox("header row", [cell(k_, lab, wd, h=rh, end=num, typo=CAPTION, color=TEXT_2)
                               for k_, lab, wd, num in TIER_COLS], {"fill": CANVAS}, w=w_, h=rh,
                note='column headers, scope="col"')
    body = [hbox(f"row {i:02d}", [cell(k_, v, wd, h=rh, end=num, typo=NUM)
                                  for (k_, _l, wd, num), v in zip(TIER_COLS, r)],
                 {"fill": CANVAS if i % 2 else RAISED}, w=w_, h=rh) for i, r in enumerate(shown, 1)]
    region = vbox("rows", body, None, w=w_, h=len(body) * rh,
                  note=('role="region" "Risk-limit tiers, scrollable", tabindex=0; arrows, PageUp/PageDown, '
                        'Home/End scroll (§10.1)') if state == "expanded" else None)
    btn = button(f"Show all {len(rows_)} tiers", "ghost", density=density, focused=focused == "show",
                 lead=icon("chevron", "chevron-down" if state == "expanded" else "chevron-right", TEXT_2),
                 note=f'button aria-expanded="{str(state == "expanded").lower()}" aria-controls the table (§4.4)')
    kids = [text("caption", f"Risk-limit tiers for {sym}", CAPTION, TEXT_2), head,
            rect("header rule", w_, 1, BORDER), region, hbox("disclosure", [btn], {"padX": INSET_SM}, w=w_,
                                                              h=round(est_height(btn)))]
    return vbox(f"tiers · {state}", kids, {"gap": STACK_XS}, w=w_, note="table + caption (§10.2)")


# --- CMP-125 SymbolInfoPopover (§9): the same three band labels, compact rows, "Open full details"
POPOVER_W = 400


def popover(state: str = "default", *, focused: str | None = None) -> Node:
    """state: default | stale | not trading | unavailable (§9), from r2's cmp125 data."""
    fallback("popover-w")
    p = R2_BOARDS[16]["cmp125"]
    w_ = POPOVER_W - 2 * PX[INSET_MD]
    kids: list[Node | None] = [text("title", p["host"], HEADING_SM, TEXT_1)]
    if state == "unavailable":
        kids.append(line("unavailable", "Contract rules not loaded", typo=BODY, color=TEXT_1, w_=w_))
    else:
        kids.append(band(p["bands"][0], D["copy"]["tagContract"],
                         [dl_row(lab, v, unit=u, w_=w_) for lab, v, u in p["contract"]], w_=w_))
        if state == "not trading":
            kids.append(notice("danger", [f"{p['host']} is not trading on Bybit."], w_=w_))
        else:
            mk = chip("stale", "Stale 7s") if state == "stale" else None
            kids.append(band(p["bands"][1], D["copy"]["tagLive"],
                             [dl_row(lab, v, unit=u, w_=w_, stale=state == "stale") for lab, v, u in p["live"]],
                             w_=w_, stale=state == "stale", marker=mk))
        kids.append(band(p["bands"][2], D["copy"]["tagRec"], [dl_row("Recording", p["rec"], kind="rec", w_=w_)],
                         w_=w_))
    kids.append(link(p["link"], w_=w_, focused=focused == "link"))
    return vbox(f"CMP-125 popover · {state}", kids, {"pad": INSET_MD, "gap": STACK_SM, "fill": OVERLAY,
                                                      "radius": R_CARD, "shadow": SHADOW_POPOVER}, w=POPOVER_W,
                note='non-modal; opens from a CMP-002 info button (aria-haspopup="dialog"), never on hover; Esc '
                     'closes and returns focus (§9)')


# --- the drawer (CMP-046 modal, right side, 480 px; sticky header and footer, §2 D-14, §3), from r2's DATA
def item(it: dict[str, Any], *, density: str = "compact", stale: bool = False, w_: int = INNER,
         focused: str | None = None) -> Node:
    """One r2 band item (_k: row, line, ex, say, link, block, skel, ph, strip, btns) as kit nodes."""
    k_ = it["_k"]
    if k_ == "row":
        vk = it.get("_vk") or "num"
        if vk == "cd" and it["v"] == countdown_text("ge1h")[0]:
            v: str | Node = countdown("ge1h", stale=stale)
        else:
            v = it["v"]
        return dl_row(it["l"], v, kind=vk, unit=it.get("u"), tag=it.get("tag"), density=density, stale=stale,
                      w_=w_, col=it.get("_col", "rules"))
    if k_ == "line":
        return line(it.get("_key", "line"), it["t"], typo=BODY if it.get("_ty") == "body" else CAPTION,
                    color=ROLE_COLOR[it.get("_role", "text2")], align=it.get("_align", "left"), w_=w_)
    if k_ == "ex":
        return example(it["t"], w_)
    if k_ == "say":
        return sentence(it["t"], w_=w_, role=it.get("_role", "text2"))
    if k_ == "link":
        return link(it["t"], w_=w_, density=density, focused=focused == "settings")
    if k_ == "block":
        return inline_error(it["_tone"], it["lines"], btns=[tuple(b) for b in it.get("btns", [])], ref=it.get("ref"),
                            w_=w_, density=density)
    if k_ in ("skel", "ph"):
        return skeleton(it.get("n") or len(it.get("labels", [])), it.get("labels"), w_=w_, density=density,
                        placeholder=k_ == "ph")
    if k_ == "strip":
        return strip(it["t"], w_=w_)
    if k_ == "btns":
        return buttons_row([tuple(b) for b in it["b"]], density=density, w_=w_, name=it.get("_key", "buttons"),
                           focused=it["b"][0][0] if focused == it.get("_key") else None)
    raise ValueError(f"r2 item kind {k_!r}")


def band_r2(key: str, *, density: str = "compact", w_: int = INNER, focused: str | None = None) -> Node:
    """An r2 band (D["bands"][key]) drawn by the kit; its marker (CMP-239 chip or the disconnected text) in the
    header; _state "stale" puts the band on the stale surface with stale values."""
    b = D["bands"][key]
    st = b.get("_state") == "stale"
    mk = b.get("marker")
    marker = None
    if mk:
        marker = (chip("stale", mk["t"]) if mk["_kind"] == "stale" else
                  text("marker", mk["t"], CAPTION, f"{DC}.disconnected.text",
                       note="no CMP-239: the SCR-152 banner outranks it (§6 Reconnecting)"))
    kids = [item(it, density=density, stale=st, w_=w_, focused=focused) for it in b["items"]]
    return band(b["h"], b["tag"], kids, stale=st, marker=marker, w_=w_, density=density)


def drawer_header(title: str, identity: str | None, *, chip_: Node | None = None, notice_: Node | None = None,
                  density: str = "compact", focused: str | None = None, w_: int = DRAWER_W) -> Node:
    inner = w_ - 2 * PX[DIALOG_PAD]
    top = hbox("title row", [hbox("title", [text("h2", title, HEADING_MD, TEXT_1,
                                                 note='the title, tabindex="-1"; focus lands here on open (§10.1)'),
                                            chip_], {"gap": INSET_SM}),
                             close_button(density=density, focused=focused == "close")],
               {"justify": "space-between"}, w=inner, h=32)
    kids: list[Node | None] = [top]
    if identity:
        kids.append(fit_text("identity", identity, CAPTION, TEXT_2, inner,
                             note="aria-describedby of the dialog (§10.2)"))
    kids.append(notice_)
    head = vbox("header", kids, {"pad": DIALOG_PAD, "gap": STACK_SM}, w=w_)
    return vbox("sticky header", [head, rect("header rule", w_, 1, BORDER)], None, w=w_,
                h=round(est_height(head)) + 1, note="sticky (§2 D-14)")


# Live-check fold (2026-10-31): the header the renderer measured on each drawn drawer (its own hug height); the sticky
# header is that + 1 so the 1 px "header rule" under it shows, and the fixed body gives the px back (the drawer's bottom
# stays put). The estimate was 1 px short on every drawer (2 px on board 6's), which hid the rule. Board 10's hugging
# strips (d10a-d10c) measured 80 + 1 already and are not listed.
HEADER_LIVE_H = {"d01": 102, "d03a": 102, "d03b": 102, "d06": 180, "d25": 102, "d25B": 102}


ACTION_NAMES = {"Open in new chart": "Open {sym} in a new chart", "Open DOM ladder": "Open {sym} DOM ladder"}  # §10.2


def drawer_footer(actions: Iterable[tuple[str, str]], *, density: str = "compact", focused: str | None = None,
                  w_: int = DRAWER_W, sym: str = "BTCUSDT") -> Node:
    row = hbox("actions", [button(c, v, density=density, focused=c == focused,
                                  note=f'CMP-001 button, name "{ACTION_NAMES.get(c, c).format(sym=sym)}" (§10.2)')
                           for c, v in actions], {"padX": DIALOG_PAD, "padY": INSET_LG, "gap": INSET_SM}, w=w_,
               h=CONTROL_H[density] + 2 * PX[INSET_LG] + (2 * PX[INSET_XS] if focused else 0))
    return vbox("sticky footer", [rect("footer rule", w_, 1, BORDER), row], None, w=w_, h=row["h"] + 1,
                note="sticky; both actions open a new panel, never the focused one (§2 D-15)")


def drawer(dkey: str, *, density: str = "compact", h: int | None = None, w_: int = DRAWER_W,
           name: str = "CMP-046 drawer", focused: str | None = None, bands: Iterable[Node] | None = None,
           above: Iterable[Node] = ()) -> Node:
    """r2's drawer dkey (title, identity, chip, notice, bands, actions) as one CMP-046 panel: sticky header, the
    bands (D-1's fixed order) in a clipped body, sticky footer; h=None hugs (the strips of board 10 and 13).
    bands= replaces r2's bands (author-built); above= nodes over the header (board 4's SCR-152 banner)."""
    d = D["drawers"][dkey]
    fallback("drawer-w")
    chip_ = chip(d["chip"]["_kind"], d["chip"]["t"]) if d.get("chip") else None
    note_ = notice(d["notice"]["_tone"], d["notice"]["lines"], w_=w_ - 2 * PX[DIALOG_PAD]) if d.get("notice") else None
    head = drawer_header(d["title"], d.get("identity"), chip_=chip_, notice_=note_, density=density,
                         focused=focused, w_=w_)
    if dkey in HEADER_LIVE_H and density == "compact":
        head["h"] = HEADER_LIVE_H[dkey] + 1
        derived(f"{name}: sticky header {head['h']} = the measured header {HEADER_LIVE_H[dkey]} + the 1 px header rule "
                f"(live-check fold)")
    inner = w_ - 2 * PX[DIALOG_PAD]
    bs = list(bands) if bands is not None else [band_r2(b, density=density, w_=inner, focused=focused)
                                                for b in d["_bands"]]
    acts = [tuple(a) for a in d.get("actions", [[D["copy"]["openChart"], "secondary"],
                                                 [D["copy"]["openDom"], "secondary"]])]
    foot = drawer_footer(acts, density=density, focused=focused, w_=w_, sym=d["title"]) if acts else None
    ab = list(above)
    fixed = sum(est_height(x) for x in [*ab, head] + ([foot] if foot else []))
    body_kw: dict[str, Any] = {}
    content = sum(est_height(b) for b in bs) + PX[STACK_LG] * max(len(bs) - 1, 0) + 2 * PX[INSET_LG]
    if h is not None:
        body_kw["h"] = int(h - fixed)
        if content > body_kw["h"]:
            live(f"{name}: the bands need about {content:.0f} px for a {body_kw['h']} px body: the body clips (the "
                 f"drawer scrolls); read back that the last band is cut at the footer, never under it")
    body = vbox("body", bs, {"padX": DIALOG_PAD, "padY": INSET_LG, "gap": STACK_LG, "clip": True}, w=w_, **body_kw)
    return vbox(name, [*ab, head, body, foot], {"fill": OVERLAY, "shadow": SHADOW_DIALOG, "clip": True}, w=w_, h=h,
                note='dialog, aria-modal="true", aria-labelledby the title, aria-describedby the identity line; '
                     '"Symbol info: <symbol>" ("Symbol info:" visually hidden) (§10.2)')


# --- frames (§15 sizes): a drawer frame IS the drawer at the frame's size; other frames are canvases for authors
def drawer_frame(fr: Frame, theme: str, dkey: str, **kw: Any) -> Node:
    """One 480-wide frame holding r2's drawer dkey at the frame's own height (board 1, 2, 4, 6, 8, 9, 11, 12, 24 ...)."""
    if fr.w != DRAWER_W:
        raise ValueError(f"{fr.fid}: a drawer frame is {DRAWER_W} wide; use free_frame for {fr.w}")
    return drawer(dkey, density=fr.density, h=fr.h, name=frame_name(fr, theme), **kw)


def free_frame(fr: Frame, theme: str, kids: Iterable[Node | None], o: dict[str, Any] | None = None,
               note: str | None = None) -> Node:
    """A §15-sized frame (fill color.surface.app, clip) for side-by-side drawers, component states, tables and flows;
    flex by default (o={"dir": "row", "gap": ...}); pass o={} and abs kids for free placement."""
    opts = {"fill": APP, "clip": True, **({"dir": "row", "align": "start", "gap": STACK_LG, "pad": INSET_LG}
                                          if o is None else o)}
    return box(frame_name(fr, theme), kids, opts, w=fr.w, h=fr.h, note=note)


# --- the annotation column (ONE, 400 px, outside the frames)
def _cited(s: str) -> str:
    c = cite(s)
    if c:
        NOTES.add("spec_cites", f"{c}: {s[:70]}")
    return f"{s} ({c})" if c else s


def frame_block(fr: Frame, *, lines: Iterable[str] = ()) -> tuple[str, list[str]]:
    """A frame's block: its §6 states with their lines, its size and density, then the author's lines."""
    out = [f"§6 L{STATES[s]}: {s}" for s in fr.states]
    out.append(f"Frame {fr.w} × {fr.h} (§15), {fr.density}: rows {ROW_H[fr.density]} px (§3 size.row.height)")
    return f"Frame · {fr.fid}", out + [x for x in lines if x]


FACETS = ("Role", "Keyboard", "Focus", "Budget", "Event")


def marker_block(m: dict[str, Any]) -> tuple[str, list[str]]:
    """An r2 marker (part, note and the five facets; "—" facets dropped) as a block; each line cites the spec or
    hand-off line that holds it verbatim."""
    fallback("markers")
    out = [_cited(m["part"])] + ([_cited(m["note"])] if m.get("note") else [])
    out += [f"{f}: {_cited(m[f])}" for f in FACETS if m.get(f) and m[f] != "—"]
    return f"at {m['_at']}", out


def annotations(key: str, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title (the board name), a "Board" block (§15 row, size, theme, twin, export), the blocks,
    footer "page <PAGE> · board NN · <REV>"."""
    b = BOARDS[key_of(key)]
    head = [f"§15 L{b.line}: {b.content}", f"Size {b.w} × {b.h}; theme {b.theme}"
            + (f" (light twin of board {b.n}: same frames, same values, re-bound by the theme switch)"
               if b.theme != "dark" else ""), f"Export: {b.export}", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines_) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines_, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {b.n:02d}{'' if b.theme == 'dark' else ' light'} · {REV}",
                     CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    """Frames 1:1 in one row (or rows of per_row), MARGIN margin and gutters, CAP_DY room for each caption."""
    k = per_row or max(len(frames), 1)
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        row = frames[i:i + k]
        x = MARGIN
        for f in row:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in row) + MARGIN + CAP_DY
        i += k
    return out


def board(key: str, frames: list[Node], ann: Node, *, per_row: int | None = None, illustrative: str | None = None,
          strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, fill color.surface.app, clip) hugging its frames + the annotation
    column + MARGIN; a "state: <fid>" caption 28 px above each frame; an "illustrative" footer under the frames on
    the boards that need one (ILLUSTRATIVE). Checks names and sizes against FRAME_PLAN and the pitch."""
    b = BOARDS[key_of(key)]
    plan = frames_of(b.key)
    want = [(frame_name(f, b.theme), f.w, f.h) for f in plan]
    got = [(f["name"], f["w"], f["h"]) for f in frames]
    if strict and got != want:
        raise ValueError(f"board {b.key}: frames {got} != FRAME_PLAN {want}")
    if b.n in ILLUSTRATIVE and not illustrative:
        raise ValueError(f"board {b.key}: illustrative values need the footer (pass illustrative=...)")
    placed = layout(frames, per_row)
    fid_of = {frame_name(f, b.theme): f.caption for f in plan}
    caps = [text(f"caption {i:02d}", fid_of.get(f["name"], f"state: {f['name']}"), CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - CAP_DY) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = []
    if illustrative:
        foot = [text("footer · illustrative", f"illustrative: {illustrative}", CAPTION, TEXT_2, x=MARGIN,
                     y=bottom + 24, w=right - MARGIN)]
        bottom += 24 + 16
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom, MARGIN + ah) + MARGIN) / 8) * 8)
    if b.key in MEASURED_H:
        fb = max(f["y"] + f["h"] for f in placed) + MARGIN  # the footer's 16 px reserve is not ink
        if MEASURED_H[b.key] < fb:
            raise ValueError(f"board {b.key}: measured root h {MEASURED_H[b.key]} is under the frames' {fb}")
        h = MEASURED_H[b.key]
    if wd > PITCH_X - 160 or h > PITCH_Y - 160:
        raise ValueError(f"board {b.key}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(b.key)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h to its end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills; "
             f"its caption sits {CAP_DY} px above it")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, copied), lint, write, pack
def _size(section_: dict[str, Any]) -> int:
    return len(json.dumps(section_))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
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
    if j == len(kids):
        return dict(bare, kids=kept), []
    shallow = [(me, k) for k in kids[j:]]
    used = len(json.dumps(dict(bare, kids=[*kept, {}]))) - 2
    part, rest = _pack(kids[j], me, room - used, budget)
    if part is not None:
        deep = rest + [(me, k) for k in kids[j + 1:]]
        if sum(len(_emit(k, p, budget)) for p, k in deep) < sum(len(_emit(k, p, budget)) for p, k in shallow):
            return dict(bare, kids=[*kept, part]), deep
    return (dict(bare, kids=kept) if kept else bare), shallow


def _emit(n: Node, into: str, budget: int) -> list[dict[str, Any]]:
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


def sections_for(nodes: Iterable[Node], budget: int = SECTION_RAW_BUDGET) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        for n in nodes:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    return out


_COLOR_KEYS = ("fill", "stroke")


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children without
    text carry h; no '/' in names; every cell padded 8 px a side; no painted colour (light twins stay bound)."""
    bad = []

    def has_text(n: Node) -> bool:
        return any(x["t"] == "text" for _p, x in walk(n))

    def rec(n: Node, parent_flex: bool, path: str) -> None:
        p = f"{path}/{n.get('name')}"
        if n["t"] not in _KEYS:
            bad.append(f"{p}: type {n['t']}")
        if "/" in n.get("name", ""):
            bad.append(f"{p}: '/' in name")
        if n["t"] == "icon" and n.get("icon") not in ICONS_OK:
            bad.append(f"{p}: icon {n.get('icon')}")
        o = n.get("o") or {}
        if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
            bad.append(f"{p}: wrap {o['wrap']!r}")
        if parent_flex and n["t"] in ("board", "rect", "ellipse") and not n.get("h") and not has_text(n):
            bad.append(f"{p}: flex child without text and without h")
        if n["t"] == "board" and n.get("name", "").startswith("cell · ") and o.get("padX") != INSET_SM:
            bad.append(f"{p}: cell padX {o.get('padX')} (8 px a side required)")
        for ck in _COLOR_KEYS:
            if ck in o and not str(o[ck]).startswith("color."):
                bad.append(f"{p}: {ck} {o[ck]!r} is not a colour token (painted value)")
        if n.get("color") and not str(n["color"]).startswith("color."):
            bad.append(f"{p}: color {n['color']!r} is not a colour token")
        for k in n.get("kids") or []:
            rec(k, bool(o.get("dir")), p)

    for n in nodes:
        rec(n, False, "")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, "\n".join(lines)


def write_sheet(key: str, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int | None = None, illustrative: str | None = None, out_dir: Path = CAP_DIR,
                name: str | None = None, strict: bool = True) -> Path:
    """Assemble board key (board()), split into sections, merge notes, write out_dir/NN-<slug>-<theme>.json, run the
    validator (tokens + components) and raise RuntimeError unless it exits 0 and the kit lint and the banned scan
    are clean. Requires at least one live_checks line. Clears NOTES."""
    b = BOARDS[key_of(key)]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(b.key, frames, ann, per_row=per_row, illustrative=illustrative, strict=strict)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {b.key} (twin of {b.n}D); read back "
             f"one bound fill (color.surface.overlay) as the {b.theme} value; nothing on the board is painted")
    live(f"export {b.export}: record the board id and the PNG size ({root['w']} x {root['h']} at 1x)")
    bad = lint(nodes)
    for kind, lines_ in (notes or {}).items():
        for ln in [lines_] if isinstance(lines_, str) else lines_:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]} (§15 L{b.line}); hand-off {HANDOFF.name} "
                         f"md5 {SPEC_MD5[HANDOFF.name][:8]}; r2 data block sha256 {R2_SHA256[:8]}")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {b.key}: lint {bad[:8]} banned {banned}")
    if not sheet["notes"]["live_checks"]:
        raise RuntimeError(f"board {b.key}: notes.live_checks is empty")
    out = out_dir / (name or b.sheet)
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rc, msg = validate(out)
    if rc != 0:
        errs = [ln for ln in msg.splitlines() if "ERROR" in ln.upper()]
        raise RuntimeError(f"{out.name}: validator exit {rc}\n" + "\n".join(errs[:20] or msg.splitlines()[-20:]))
    return out


def md_line3(key: str, sheet_name: str | None = None) -> str:
    """The render script's line (it parses "page `...`" and "theme dark." / "theme light.")."""
    b = BOARDS[key_of(key)]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{sheet_name or b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(key: str, sheet_path: Path, *, summary: str = "", frames_info: Iterable[str] = ()) -> Path:
    """The sheet's .md beside it: line 1 "# <board name>", line 3 md_line3(), then the summary, frames, the validator
    line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[key_of(key)]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(b.key)
    out = [f"# {b.name}", "", md_line3(b.key, sp.name), "",
           summary or f"Board {b.key} (§15 L{b.line}: {b.content}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; footer \"page {PAGE} · board {b.n:02d} · {REV}\".", "", "## Frames", ""]
    out += [f"- `{frame_name(f, b.theme)}` ({f.w} x {f.h}; {', '.join(f.states) or 'no §6 state'})"
            for f in frames_of(b.key)]
    out += [f"- {ln}" for ln in frames_info]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "derivations", "spec_gaps", "deviations", "copy_gaps", "fallbacks", "spec_cites",
               "sources", "tokens"):
        lines_ = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines_)})", ""] + [f"- {ln}" for ln in lines_] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(ln.rstrip() for ln in out))  # Prettier-stable (no trailing blanks)
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {b.key}: banned string {m.group(0)!r}")
    (sp.parent / (sp.stem + ".md")).write_text(s, encoding="utf-8")  # beside the sheet (the render drivers' set)
    p = (KIT_DIR if sp.parent == CAP_DIR.resolve() else sp.parent) / (sp.stem + ".md")  # the committed copy
    p.write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>; check compactOf.file is the ABSOLUTE source path, its sha256 the
    source's, every packed section <= PACKED_MAX bytes (compact JSON) and mkcall4.py's `count` agrees; then rewrite
    compactOf.file to the bare file name (the sha256 beside it stays the source's), so the committed v4/ carries no
    local path."""
    src = Path(sheet_path).resolve()
    out_dir = out_dir.resolve()
    if out_dir not in (V4_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"packed sheets go to {V4_DIR}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.name if out_dir == V4_DIR.resolve() else src.stem + ".packed.json")
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    sh = json.loads(dst.read_text(encoding="utf-8"))
    cf = sh.get("compactOf") or {}
    if not cf.get("file") or not Path(cf["file"]).is_absolute() or Path(cf["file"]) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {cf.get('file')!r} is not the absolute source path")
    if cf.get("sha256") != hashlib.sha256(src.read_bytes()).hexdigest():
        raise RuntimeError(f"{dst.name}: compactOf.sha256 is not the source's")
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(len(sh["sections"])):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} "
                           f"!= {len(sh['sections'])}: {cnt.stderr.strip()[-300:]}")
    raw = dst.read_text(encoding="utf-8")
    abs_field = json.dumps(cf["file"], ensure_ascii=False)
    if raw.count(abs_field) != 1:
        raise RuntimeError(f"{dst.name}: the pack source path occurs {raw.count(abs_field)} times")
    dst.write_text(raw.replace(abs_field, json.dumps(src.name, ensure_ascii=False)), encoding="utf-8")
    if json.loads(dst.read_text(encoding="utf-8"))["compactOf"] != {"file": src.name, "sha256": cf["sha256"]}:
        raise RuntimeError(f"{dst.name}: compactOf is not the bare name and sha256 of {src.name}")
    return dst


# --- board 1 (the self-test's board; a board author may import it as the reference generator)
def board1(theme: str = "dark", density: str | None = None) -> tuple[list[Node], Node]:
    """Board 1 (§3: BTCUSDT, Owner, recorded, compact): r2's drawer d01 at 480 x 1360; annotations from r2's nine
    markers (each line cited) and the frame block with the derivations. theme="light" is board 1L (same nodes)."""
    key = f"1{'D' if theme == 'dark' else 'L'}"
    fr = frames_of(key)[0]
    fr = Frame(fr.fid, fr.w, fr.h, density or fr.density, fr.states)
    frame = drawer_frame(fr, theme, "d01")
    lv, rv, ru = live_values(), rec_values(), rules("BTCUSDT")
    derived(f"rules from instruments_after.json as delivered (tick {INSTR['BTCUSDT']['tick']}, max qty "
            f"{INSTR['BTCUSDT']['maxQty']}, leverage {INSTR['BTCUSDT']['maxLev']}) -> F3 {ru['tick']}, {ru['maxQty']}, "
            f"{ru['maxLev']} (§5 L{L('- **F3 Rule values')})")
    derived(f"live from the recorded snapshot: last {lv['last']}, index {lv['index']} (F4), volume {lv['vol']} (F5), "
            f"turnover {lv['turn']} (F7), change {lv['chg']}, funding {lv['rate']} (F6), {lv['updated']}")
    derived(f"countdown {lv['cd']}: next_funding_time_ms - ts_ms = {to_go_s() * 1000 + int(TICKER['ts']) % 1000} ms "
            f"to go, floored to seconds (§7 L{L('the recorded frame had 5,053,771 ms to go')})")
    derived(f"recording: {rv['gaps']} (F10: 02:11:00-02:14:20 rounded out), disk {rv['disk']} (F7 of "
            f"{REC['disk_bytes']:,} bytes)")
    blk = frame_block(fr, lines=["24 h high / low: 'not available yet' (CR-11; §4.2), not the snapshot's values "
                                 "(board 18 draws them after CR-11)"])
    ann = annotations(key, [blk, *[marker_block(m) for m in R2_BOARDS[1]["markers"]]])
    return [frame], ann


# --- self-test: python3 -I -B e08d06kit.py selftest
_PNG = re.compile(r"\b((?:scr-103|cmp-\d{3})-[a-z0-9-]+-(?:dark|light)\.png)")


def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()) and r2_sha_ok(), f"pinned md5s {spec_md5_ok()}, r2 sha256 {R2_SHA256[:8]}")
    check(len(DARK) == 25 and len(LIGHT) == 17 and len(BOARDS) == 42
          and LIGHT == [f"{n}L" for n in range(1, 18)], "§15: 25 dark + 17 light twins (1-17) = 42")
    check(all((BOARDS[f"{n}D"].w, BOARDS[f"{n}D"].h) == (fs[0].w, fs[0].h) for n, fs in FRAME_PLAN.items())
          and sorted(FRAME_PLAN) == list(range(1, 26)), "FRAME_PLAN: one entry per board, main frame = §15 size")
    check(all([(f["_w"], f["_h"]) for f in R2_BOARDS[n]["_frames"]] == [(f.w, f.h) for f in FRAME_PLAN[n]]
              and R2_BOARDS[n]["id"] == BOARDS[f"{n}D"].sid and R2_BOARDS[n]["_twin"] == BOARDS[f"{n}D"].twinned
              for n in FRAME_PLAN), "r2 boards agree: ids, twin flags, frame sizes")
    check(len(STATES) == 23 and all(s in STATES for fs in FRAME_PLAN.values() for f in fs for s in f.states),
          f"§6: {len(STATES)} states; every frame state is one of them")
    drawn = {s for n, fs in FRAME_PLAN.items() if n != 23 for f in fs for s in f.states}
    check(True, f"§6 states drawn on a drawer or component board (board 23 holds all): {len(drawn)}; matrix only: "
                f"{sorted(set(STATES) - drawn)}")
    pngs = [b.png for b in BOARDS.values()]
    named = set(_PNG.findall("\n".join(HANDOFF_LINES + SPEC_LINES)))
    check(len(set(pngs)) == 42 and named <= set(pngs), f"42 unique §15 PNG names; the {len(named)} the hand-off / "
                                                       f"spec name are in the registry")
    slots = {grid_xy(k) for k in BOARDS}
    check(len(slots) == 42, "42 distinct grid slots (positions do not depend on the drawn set)")
    for k in BOARDS:
        fs = frames_of(k)
        wd = MARGIN + sum(f.w + MARGIN for f in fs) + ANN_W + MARGIN
        hh = MARGIN + max(f.h for f in fs) + MARGIN + 64
        if wd > PITCH_X - 160 or hh > PITCH_Y - 160:
            check(False, f"board {k}: {wd} x {hh} over the {PITCH_X} x {PITCH_Y} pitch")
    check(True, "every board's frames fit its pitch slot (one row)")
    ten = [key_of(k) for k in PROPOSED_TEN]
    check(len(set(ten)) == 10 and sum(k.endswith("L") for k in ten) <= 10 // 3
          and {"3D", "6D", "10D", "18D", "25D"} <= set(ten) and len(undrawn()) == 32,
          f"cap set: 10 boards, {sum(k.endswith('L') for k in ten)} twin(s) <= 1/3, AC 2-5 + T2 drawn, 32 undrawn")
    check(sorted(k for g in AUTHOR_GROUPS_CAP.values() for k in g) == sorted(ten)
          and sorted(k for g in AUTHOR_GROUPS_42.values() for k in g) == sorted(BOARDS),
          "author groups: the cap pair covers the ten; the seven groups cover all 42 once")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k, v in globals().items() if k.isupper() and k not in ("DC", "STATUS") and isinstance(v, str)
            and re.match(
        r"^(color|type|space|size|radius|border|opacity|elevation)\.", v)]
    used += [f"{DC}.{k}.{p}" for k in ("stale", "delisted", "disconnected") for p in ("text", "indicator")]
    used += [f"{DC}.stale.surface"] + [f"{STATUS}.{t}.{p}" for t in ("info", "warning", "danger")
                                       for p in ("subtle", "strong")]
    miss = sorted({u for u in used if u not in toks})
    check(not miss, f"kit tokens exist ({len(set(used))}; missing {miss})")
    bad = r2_consistency()
    check(not bad, f"r2 DATA = the §5 formatters on the fixtures (rules x3, live x14, recording x4, tiers, CMP-126 "
                   f"x7){'' if not bad else ': ' + '; '.join(bad[:4])}")
    check(change_pct("0") == "0.00 %" and funding_pct("0.0001") == "+0.0100 %" and magnitude("999600000") == "1.00 B"
          and minimal("1E-7") == "0.0000001" and gap_span("2026-09-04T02:11:00+00:00", "2026-09-04T02:14:20+00:00")
          == "02:11–02:15", "F2/F6/F7/F10 edge cases (§5's own examples)")
    sents = [T2_OWNER_ONLY, T2_VIEW_AS, T3_SENTENCE, *REC_WORDS]
    expand = [s_ for s_ in sents if not in_spec(s_)]  # "● Recording · " + a reason the row lists bare
    check(all(s_.startswith("● Recording · ") and in_spec(f'"{s_.split(" · ", 1)[1]}"') for s_ in expand),
          f"T2 / T3 sentences and the {len(REC_WORDS)} §4.3 words verbatim ({len(expand)} expand a listed reason)")
    copy_strs = [v for v in D["copy"].values() if isinstance(v, str) and len(v) > 5]
    nonverb = [v for v in copy_strs if not in_spec(v)]
    check(True, f"r2 copy: {len(copy_strs) - len(nonverb)}/{len(copy_strs)} strings verbatim in spec/hand-off; "
                f"the rest are r2 substitutions or derived: {nonverb[:6]}")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: recorder_row("Recording on")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/' in a name and a non-§4.3 state word refused")
    check(lint([rect("x", 4, 4, "#ffffff")]) != [], "lint refuses a painted colour")
    NOTES.reset()
    frames, ann = board1("dark")
    path = write_sheet("1D", frames, ann, out_dir=SELFTEST_DIR, name="00-selftest.json",
                       notes={"live_checks": ["self-test sheet: board 1 dark, not for rendering from this folder"]})
    rc, msg = validate(path)
    check(rc == 0, f"board 1 dark: validator exit {rc}: {msg.splitlines()[-1]}")
    sh = json.loads(path.read_text(encoding="utf-8"))
    chars = [n.get("chars", "") for s_ in sh["sections"] for _p, n in walk(s_["node"])]
    want = [*live_values().values(), *rec_values().values(), *(v for k_, v in rules("BTCUSDT").items()
                                                                if k_ not in ("levStep",))]
    want = [v for v in want if v not in ("82,850.0", "80,611.7", "Last update 06:35:46 UTC")]
    miss_v = [v for v in want if not any(v == c or (v in c and len(v) > 6) for c in chars)]
    check(not miss_v, f"board 1 draws every derived value (missing {miss_v[:4]}) and no 24 h high / low")
    caps = [c for c in chars if c.startswith("state: ")]
    check(caps == [f"state: {frames_of('1D')[0].fid}"], f"one state caption per frame: {caps}")
    d = drawer("d01", h=1360)
    body = next(x for x in d["kids"] if x["name"] == "body")
    need = sum(est_height(b) for b in body["kids"]) + PX[STACK_LG] * 2 + 2 * PX[INSET_LG]
    check(need <= body["h"], f"board 1's three bands fit the 1360 px drawer (about {need:.0f} of {body['h']} px)")
    check(sh["board"]["w"] == MARGIN + 480 + MARGIN + ANN_W + MARGIN, f"root hugs frame + 400 + 80: "
                                                                     f"{sh['board']['w']} x {sh['board']['h']}")
    md = write_md("1D", path, summary="Self-test sheet (board 1 dark); not a board of the set until the cap ruling.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark.")  # type: ignore[union-attr]
          and "export `docs/design/E08/img/scr-103-populated-recorded-owner-dark.png`" in l3, f"md line 3: {l3}")
    check(md_line3("1L").endswith("theme light.") and "scr-103-populated-recorded-owner-light.png" in md_line3("1L")
          and "sheet `01-populated-recorded-owner-light.json`" in md_line3("1L"), "md line 3: the light twin")
    packed = pack_sheet(path, SELFTEST_DIR)
    ps = json.loads(packed.read_text(encoding="utf-8"))
    check(ps["compactOf"]["file"] == path.name, f"packed {packed.name}: bare pack source name, sha256 ok, "
          f"{len(ps['sections'])} sections, max "
          f"{max(len(json.dumps(s_, ensure_ascii=False, separators=(',', ':')).encode()) for s_ in ps['sections'])} B, "
          f"mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
