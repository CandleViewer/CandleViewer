"""E08-D09 (#177, PR 3) board kit: SCR-147 exchange connectivity, rate limits and clock skew, ten boards as cvsheet
JSON sheets for the per-set Penpot file "E08-D09 boards", page "E08-D09 SCR-147 Connectivity".

Offline only. Spec (binding; every string comes from it): docs/design/E08/E08-D09.md and E08-D09-handoff.md as this
checkout commits them (read by repo-relative path; md5-pinned in SPEC_MD5: the kit refuses drifted bytes; re-read,
re-pin).
Registry: §0's board table is parsed (BOARDS); the frames each board draws are this kit's FRAME_PLAN, keyed by the
spec's state ids (S-01 ... S-20, §5.2) and, where §0 names a view with no S-id, by §0's own words.

Pipeline (a generator per board, written by the board authors, gen/gen_NN.py):
    frames = [window(...), ...]                       # one 1280 x 800 window per FRAME_PLAN entry, in order
    ann = annotations(nn, [frame_block(...), ...])    # the ONE 400 px column
    p = write_sheet(nn, frames, ann)                  # build/NN-<slug>.json (untracked), validator exit 0 or RuntimeError
    write_md(nn, p)                                   # NN-<slug>.md here and in build/, line 3 = the render script's line
    pack_sheet(p)                                     # v4/NN-<slug>.json, compactOf.file = the bare name + its sha256
Twins: boards 08, 09 (light) and 10 (hc) call their base board's builder with theme= their own theme (build(theme)).
Self-test: python3 -I -B e08d09kit.py selftest   (one sample frame into build/selftest/, validated, packed)
Rebuild all ten: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name; no local path, host or agent name anywhere in a
sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
CAP_DIR = KIT_DIR / "build"  # the raw sheets + a copy of each .md (untracked: .gitignore); the .md also go to KIT_DIR
SELFTEST_DIR = CAP_DIR / "selftest"  # the self-test's sheet, md and packed sheet
V4_DIR = KIT_DIR / "v4"  # packed sheets (the renderer's input, committed; compactOf.file = the bare name)
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
PACKER = SHEETS_DIR / "tools" / "compact.py"
MKCALL = SHEETS_DIR / "tools" / "mkcall4.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = SHEETS_DIR / "tools" / "token-sync.json"
REPO = KIT_DIR.parents[4]  # the checkout's root: every spec read is REPO / <repo-relative path>, md5-pinned below
SPEC = REPO / "docs/design/E08/E08-D09.md"
HANDOFF = REPO / "docs/design/E08/E08-D09-handoff.md"
SPEC_MD5 = {SPEC.name: "bb6e2dd100900608848f7d7ef5fabc30", HANDOFF.name: "3dc8240e5e2f88fb640cfb7ce06b8d7d"}

FILE_NAME = "E08-D09 boards"
PAGE = "E08-D09 SCR-147 Connectivity"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3200
MARGIN = 80  # root margin and frame gutters (positions, not a flex gap)
ANN_W = 400  # the one annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000  # raw section JSON; the packed section is smaller
PACKED_MAX = 9216  # "each packed section <= ~9 KB"
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


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e08d09kit: spec text drifted from SPEC_MD5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _read(SPEC)
HANDOFF_LINES = _read(HANDOFF)


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


def _table_rows(head: str, stop: str, first: str) -> list[tuple[int, list[str]]]:
    """(line, cells) of the table rows between the heading line `head` and the next line containing `stop`, keeping
    rows whose first cell matches the regex `first`."""
    a = find_line(head)
    b = find_line(stop, start=a + 1)
    return [(i, c) for i in range(a + 1, b) if (c := _cells(SPEC_LINES[i - 1])) and re.fullmatch(first, c[0])]


# --- §0: the ten boards (registry parsed from the spec)
@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E08-D09 / 01 healthy"
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int  # §0 line
    twin: int | None = None  # light / high-contrast twin of board N
    states: tuple[str, ...] = ()  # the S-ids §0's Draws cell names

    @property
    def export(self) -> str:
        return f"docs/design/E08/img/E08-D09-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def base(self) -> int:
        return self.twin or self.nn


# §0's board row: number, name, Draws, Theme, then (since PR 3) the As built cell, which the kit does not read
_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(E08-D09 / (\d{2}) ([a-z0-9-]+))`\s*\|([^|]*)\|\s*(dark|light|hc)\s*\|"
                    r"(?:[^|]*\|)?\s*$")
_TWIN = re.compile(r"^(light|high-contrast) twin of (\d{2})$")


def _parse_boards() -> dict[int, Board]:
    s0 = find_line("## 0. Status, artefacts and the boards")
    s1 = find_line("## 1. Purpose", start=s0)
    out: dict[int, Board] = {}
    for i in range(s0, s1):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        nn = int(m.group(1))
        if int(m.group(3)) != nn:
            raise ValueError(f"§0 L{i}: row {nn} names board {m.group(3)}")
        draws = m.group(5).strip()
        tw = _TWIN.match(draws)
        if tw and {"light": "light", "high-contrast": "hc"}[tw.group(1)] != m.group(6):
            raise ValueError(f"§0 L{i}: twin kind {tw.group(1)} vs theme {m.group(6)}")
        out[nn] = Board(nn, m.group(2), m.group(4), draws, m.group(6), i, int(tw.group(2)) if tw else None,
                        tuple(dict.fromkeys(re.findall(r"S-\d{2}", draws))))
    return out


BOARDS = _parse_boards()
TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {8: 1, 9: 5, 10: 2}
# five parallel authors; each twin with its base board, then the remaining four boards in two pairs
PAIRS = ((1, 8), (5, 9), (2, 10), (3, 7), (4, 6))


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# --- §5.2 the state register (S-01 ... S-20), §15 the copy deck (W-n), §17.4 the SR rows, §21.2 the G-ledger
@dataclass(frozen=True)
class State:
    sid: str
    state: str  # the register's State cell, parentheses and backticks removed ("held by IP")
    origin: str  # Exchange | Network | Our backend | —
    word: str  # the first quoted word ("Throttled")
    wkey: str | None  # its W-id
    glyph: str  # check | triangle | octagon | clock | ring | —
    token: str  # the tone token cell, backticks removed
    trigger: str
    exit: str
    announce: str
    max_rate: str
    boards: tuple[int, ...]
    line: int


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "")).strip()


def _parse_register() -> dict[str, State]:
    out: dict[str, State] = {}
    for i, c in _table_rows("### 5.2 The register", "- **Precedence on one row:**", r"S-\d{2}"):
        if len(c) != 11:
            raise ValueError(f"§5.2 L{i}: {len(c)} cells")
        st = _plain(re.sub(r"\s*\([^)]*\)", "", c[1])) or _plain(c[1])
        word = re.search(r'"([^"]+)"', c[3])
        wk = re.search(r"W-\d+[ab]?", c[3])
        out[c[0]] = State(c[0], st, c[2], word.group(1) if word else _plain(c[3]), wk.group(0) if wk else None,
                          c[4], _plain(c[5]), _plain(c[6]), _plain(c[7]), _plain(c[8]), _plain(c[9]),
                          tuple(int(x) for x in re.findall(r"\d{2}", c[10])), i)
    return out


REGISTER = _parse_register()  # 20 states
PRECEDENCE = tuple(re.findall(r"S-\d{2}", SPEC_LINES[L("- **Precedence on one row:**") - 1]))


@dataclass(frozen=True)
class Copy:
    key: str
    where: str
    text: str
    source: str
    line: int


def _parse_copy() -> dict[str, Copy]:
    return {c[0]: Copy(c[0], c[1], c[2], c[3], i)
            for i, c in _table_rows("## 15. Copy deck", "## 16. Tokens", r"W-\d+[ab]?")}


COPY = _parse_copy()
_SLOT = re.compile(r"\{[^{}]*\}")


def _parse_sr() -> dict[str, tuple[str, str, str, int]]:
    """§17.4: SR id -> (event, string, politeness, line)."""
    return {c[0]: (c[1], c[2], c[3], i) for i, c in
            _table_rows("### 17.4 Announcements", "- **One assertive case.**", r"SCR-147-SR-\d+")}


SR = _parse_sr()
SR_FOR: dict[str, list[str]] = {}
for _sr, (_ev, _s, _p, _i) in SR.items():
    if "…" in _ev:  # SR-9: recovery from any S-02…S-20 (an exit line, listed per frame by frame_block(recovery=True))
        continue
    for _sid in re.findall(r"S-\d{2}", _ev):
        SR_FOR.setdefault(_sid, []).append(_sr)


def _parse_t2() -> dict[str, list[str]]:
    return {c[0]: c for _i, c in _table_rows("### 17.5 T2 rows", "### 17.6 Reflow", r"SCR-147-T2-\d+")}


T2_ROWS = _parse_t2()


def _parse_g() -> dict[str, tuple[str, int]]:
    return {c[0]: (_plain(c[1]), i) for i, c in _table_rows("### 21.2 The G-ledger", "### 21.3 Open questions",
                                                           r"D09-G\d+")}


GROWS = _parse_g()  # D09-G1 ... D09-G18


def g(gid: str) -> str:
    """A G-row id, checked against §21.2 ("D09-G1" or "G1"); records it."""
    k = gid if gid.startswith("D09-") else f"D09-{gid}"
    if k not in GROWS:
        raise KeyError(f"{k}: not in §21.2")
    NOTES.add("g_rows", f"{k} (§21.2 L{GROWS[k][1]}): {GROWS[k][0][:90]}")
    return k


def w(key: str, piece: int | None = None, *vals: Any, sample: bool = False) -> str:
    """A §15 string (piece i of its " · "-separated pieces, or the whole). Each {…} slot is filled in order from vals;
    the frame's own data must give them (derive, never type a number that contradicts another on the frame).
    sample=True keeps the spec's illustrative slot values and records that in the notes."""
    c = COPY[key]
    s = c.text if piece is None else c.text.split(" · ")[piece]
    slots = _SLOT.findall(s)
    if vals:
        if len(vals) != len(slots):
            raise ValueError(f"{key}[{piece}]: {len(slots)} slots {slots}, {len(vals)} values")
        it = iter(vals)
        s = _SLOT.sub(lambda _m: str(next(it)), s)
    elif slots:
        if not sample:
            raise ValueError(f"{key}[{piece}]: slots {slots} need values (or sample=True)")
        s = _SLOT.sub(lambda m: m.group(0)[1:-1], s)
        NOTES.add("deviations", f"{key}: the spec's illustrative slot values kept ({', '.join(slots)})")
    NOTES.add("copy_keys", f"{key} (§15 L{c.line}; {c.where})")
    return s


def state_word(sid: str) -> str:
    """The S-id's word as the register gives it (W-n verbatim); records the key."""
    st = REGISTER[sid]
    if st.wkey:
        c = COPY[st.wkey]
        NOTES.add("copy_keys", f"{c.key} (§15 L{c.line}; {c.where})")
    return st.word


def origin_label(sid: str) -> str | None:
    """W-11's piece for the state's origin (Exchange · Network · Our backend), or None for an origin-less state."""
    o = REGISTER[sid].origin
    pieces = COPY["W-11"].text.split(" · ")
    if o not in pieces:
        return None
    NOTES.add("copy_keys", f"W-11 (§15 L{COPY['W-11'].line}; origin label)")
    return o


def origin_action(sid: str) -> str | None:
    """W-12's operator action line for the state's origin (§5.1), or None."""
    o = REGISTER[sid].origin
    order = COPY["W-11"].text.split(" · ")
    if o not in order:
        return None
    acts = re.split(r"(?<=\.) · ", COPY["W-12"].text)
    NOTES.add("copy_keys", f"W-12 (§15 L{COPY['W-12'].line}; origin action line)")
    return acts[order.index(o)]


# --- the frame plan: per base board, the windows it draws (twins draw their base board's plan in their theme)
def _short(sid: str) -> str:
    return f"{sid} {REGISTER[sid].state}"


FRAME_PLAN: dict[int, tuple[tuple[str, tuple[str, ...]], ...]] = {
    1: ((_short("S-01") + " · top", ("S-01",)), (_short("S-01") + " · middle", ("S-01",)),
        (_short("S-01") + " · bottom", ("S-01",)), *((_short(s), (s,)) for s in
                                                     ("S-13", "S-15", "S-16", "S-17", "S-18", "S-19"))),
    2: tuple((_short(s), (s,)) for s in ("S-02", "S-03")),
    3: tuple((_short(s), (s,)) for s in ("S-04", "S-05")),
    4: (*((_short(s), (s,)) for s in ("S-06", "S-07", "S-08", "S-20")), ("Force reconnect dialog", ())),
    5: (*((_short(s), (s,)) for s in ("S-09", "S-10", "S-11", "S-12")), ("re-measure busy", ()),
        ("re-measure cooldown", ())),
    6: ((_short("S-19") + " · simulator", ("S-19",)), ("simulator result", ()), ("Change budget dialog", ()),
        ("Change budget refusal", ()), ("T2 view-as forms", ())),
    7: (("inspector · 36 topic rows", ()), ("inspector · 120 topic rows", ()), ("inspector · 480 topic rows", ()),
        (_short("S-14"), ("S-14",)), ("history sparkline and table", ()), ("history empty", ()),
        (_short("S-19") + " · inspector and history", ("S-19",))),
}


def frames_of(nn: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return FRAME_PLAN[BOARDS[nn].base]


def frame_name(fid: str, theme: str) -> str:
    """The Penpot frame name: "SCR-147 · <fid> · <theme>" ("/" never appears: section paths split on it)."""
    name = f"SCR-147 · {fid} · {theme}"
    if "/" in name:
        raise ValueError(name)
    return name


# --- tokens (exact names in token-sync.json; the self-test checks every one). §16 is the binding slot table.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_LINK = "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
OK_STRONG, WARN_STRONG, DANGER_STRONG = ("color.status.success.strong", "color.status.warning.strong",
                                         "color.status.danger.strong")
DANGER_DEFAULT, DANGER_SUBTLE, WARN_SUBTLE = ("color.status.danger.default", "color.status.danger.subtle",
                                              "color.status.warning.subtle")
NEUTRAL = "color.neutral.default"
DC = "color.data-confidence"  # f"{DC}.disconnected.text" etc. (§16: connection rows and old values)
ADMIN_TINT, ADMIN_RULE = RAISED, TEXT_3  # §16 L"admin band, rule": CMP-087's band names resolve to these
TRACK = HOVER  # §16 meter track
SCRIM = SUNKEN  # no scrim colour token (FALLBACKS["scrim"])
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM = "type.num.base"  # §16: numbers, end-aligned
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
DIALOG_PAD, BUTTON_PADX = "space.dialog.padding", "space.button.paddingX"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
OPACITY_SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12, STACK_LG: 16,
      DIALOG_PAD: 24, BUTTON_PADX: 12, ICON: 16, ICON_SM: 12}
TONE = {  # §5.2 token tone -> (glyph colour, word colour); words stay color.text.primary on the page surfaces
    "success": OK_STRONG, "warning": WARN_STRONG, "danger": DANGER_STRONG, "neutral": NEUTRAL,
}
GLYPH_ICON = {"check": "check", "triangle": "warning", "octagon": "danger", "clock": "pending"}  # "ring": an ellipse
FALLBACKS = {
    "ring": "fallback: CMP-178's ring glyph (§5.2) drawn as a 12 px ellipse outline, border.thick (no ring icon)",
    "clock": "fallback: CMP-178's clock glyph (§5.2) drawn with the local icon 'pending'",
    "triangle": "fallback: CMP-178's triangle glyph drawn with the local icon 'warning'",
    "octagon": "fallback: CMP-178's octagon glyph drawn with the local icon 'danger'",
    "scrim": "fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim",
    "chrome": "kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders; "
              "only CMP-087's band and rule and the SCR-147 page are drawn (§2.1, §2.2)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "sparkline": "fallback: CMP-024's line drawn as stepped 2 px column marks (no path primitive in cvsheet)",
    "skeleton": "fallback: CMP-015 Skeleton drawn as color.surface.hover bars (no library component in the file)",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "g_rows", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations")


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
    """A string the copy deck lacks, drawn from the spec's prose (cite the line)."""
    NOTES.add("copy_gaps", line)


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


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
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


def rect(name: str, w_: float, h: float, fill: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w_, h=h, o=opts or None, **kw)


def ellipse(name: str, w_: float, h: float, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return node("ellipse", name, w=w_, h=h, o=dict(o) if o else None, **kw)


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
    if o.get("dir") == "row" and o.get("wrap") == "wrap" and n.get("w"):
        room = float(n["w"]) - 2 * _px(o.get("pad")) - 2 * _px(o.get("padX")) - _px(o.get("padL")) - _px(o.get("padR"))
        gap, total, line_w, line_h = _px(o.get("gap")), 0.0, 0.0, 0.0
        for k in kids:
            kw, kh = est_width(k), est_height(k)
            if line_w and line_w + gap + kw > room:
                total, line_w, line_h = total + line_h + gap, 0.0, 0.0
            line_w, line_h = line_w + (gap if line_w else 0) + kw, max(line_h, kh)
        return pad + total + line_h
    if o.get("dir") == "row":
        return pad + max((est_height(k) for k in kids), default=0.0)
    return max((float(k.get("y", 0)) + est_height(k) for k in n.get("kids") or []), default=0.0)


# --- the illustrative world (W-01: "illustrative values, not a market capture"). One clock for every frame: AS_OF
# is W-03's own example time; every other time on a frame is derived from it with at(), every duration with dur().
AS_OF = "14:02:11"
ACCOUNTS = ("Main", "Swing", "Scalp", "Hedge", "Desk")  # "Main" is the spec's slot; the other four are kit choices
LIM = {  # documented defaults the boards follow (§3.2 "Illustrative figures ... follow the documented defaults")
    "order_per_s": 10, "read_per_s": 50, "ip_per_5s": 600,  # §3.2 (`24`:2314)
    "ws_new_per_5min": 500, "ws_concurrent": 1000,  # §3.1 Public WS row
    "topics_per_request": 10, "chars_per_request": 21000, "topics_per_socket": 500,  # §9 planner constants
    "clock_warn_ms": 500, "clock_halt_ms": 2000, "clock_every_s": 300, "clock_stale_s": 900,  # §10
    "s02_pct": 80, "stale_s": 5, "virtualize_rows": 60,  # §5.2 S-02, S-15; §9
}
ORDER_CLASSES = ("order.create", "order.amend", "order.cancel", "order.cancel_all", "batch")  # §3.1 REST order
QUERY_CLASSES = (("position.read", "position"), ("account.read", "account"), ("market.read", "market_data"))


def _sec(hms_: str) -> int:
    h, m, s = (int(x) for x in hms_.split(":"))
    return h * 3600 + m * 60 + s


def at(delta_s: int, base: str = AS_OF) -> str:
    """base + delta_s seconds as HH:MM:SS (UTC); negative deltas give earlier times."""
    t = (_sec(base) + delta_s) % 86400
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def dur(s: int) -> str:
    """A duration in the deck's forms: "42 s" under a minute, "8m 20s" above (W-15, W-16)."""
    return f"{s} s" if s < 60 else f"{s // 60}m {s % 60:02d}s".replace("m 0", "m ").replace("m 0s", "m")


def ago(s: int) -> str:
    """An age in W-39's form: "2m" ("{2m} ago"), "4s" (W-04's "Stale {4s}")."""
    return f"{s}s" if s < 60 else f"{s // 60}m"


def pct(used: float, limit: float) -> int:
    return int(round(100 * used / limit)) if limit else 0


HEADROOM_CITE = "§3.2 Headroom row and R-4; W-14's base"  # where headroom() comes from (annotations quote L-lines)


def headroom(limit: int, used: int, reserve: int = 0) -> tuple[int, int, int]:
    """The one headroom arithmetic every board calls. §3.2's Headroom row: "what is left after the reserve is taken
    out (R-4), as a count and a share"; the share is of the spendable budget (limit - reserve), the base W-14 names
    ("% of the spendable budget used"), so on one row Used share + Headroom share = 100 % and the REST tile agrees.
    The headroom share rounds down (it never overstates what is left); the used share is its complement.
    Returns (headroom count = max(0, limit - used - reserve), headroom share %, used share %)."""
    spendable = limit - reserve
    head = max(0, spendable - used)
    share = math.floor(100 * head / spendable) if spendable > 0 else 0
    return head, share, 100 - share


def offset_s(ms: int) -> str:
    """W-38's size slot ("{0.62}" s): the clock offset in seconds, two decimals (12 ms -> "0.01"), on every board."""
    return f"{ms / 1000:.2f}"


CLOCK_LABELS = ("State", "Offset", "Last measured", "Next due")  # §10 Fields' words (W-39 "Last measured"), every board


def headroom_cell(limit: int, used: int, reserve: int = 0) -> str:
    """The Headroom cell, "count · share %" (W-08's column; §3.2 unit "requests · %"), from headroom()."""
    head, share, _used = headroom(limit, used, reserve)
    return f"{head} · {share} %"


# --- the window: SCR-147 anatomy (§2.2) inside CMP-087 AdminLayout at 1280 x 800, comfortable density (§0, §2.1).
# Chrome geometry follows the committed E42 admin kits: TopBar 48, NavRail 64 (collapsed), main 976 (944 inside
# space.inset.lg), RightRail 240, StatusBar 48; the band 56 + the 4 px rule.
TOP_H, STATUS_H, NAV_W, RIGHT_W = 48, 48, 64, 240
MAIN_W = FRAME_W - NAV_W - RIGHT_W  # 976
INNER_W = MAIN_W - 2 * 16  # 944
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
VIEW_H = BODY_H - 2 * 16  # 672: the page's visible height at scroll 0 (below the main column's top inset)
BAND_H, RULE_H, CONTROL_H, ROW_H, ROW2_H = 56, 4, 32, 32, 44  # ROW2_H: a row whose Class cell has its second line


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar() -> Node:
    left = hbox("left", [placeholder("wordmark", 88), placeholder("env badge", 40, 16),
                         placeholder("workspace switcher", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chips", 160), placeholder("search", 16, 16),
                           placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                          abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note="E10's TopBar, not this spec's: placeholders only")


def navrail() -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=CONTROL_H)
            for i in range(1, 6)]
    admin = hbox("Admin entry (current)", [placeholder("admin glyph", 16, 16)],
                 {"justify": "center", "radius": R_CONTROL, "fill": SELECTED}, w=48, h=CONTROL_H,
                 note="Owner only; aria-current=page (§13.1: Manager and Viewer have no entry)")
    return vbox("NavRail (placeholder)", [vbox("entries", rows, {"gap": INSET_XS, "align": "center"}, w=48,
                                               h=5 * CONTROL_H + 4 * 4), admin,
                                          rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"justify": "space-between", "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H)


def rightrail() -> Node:
    rows = [placeholder(f"row-{i}", RIGHT_W - 24) for i in range(1, 4)]
    return vbox("RightRail (placeholder)", [placeholder("panic buttons", RIGHT_W - 24, 40), *rows,
                                            rect("divider", 1, BODY_H, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"gap": INSET_MD, "pad": INSET_MD, "fill": APP}, w=RIGHT_W, h=BODY_H)


def statusbar() -> Node:
    return hbox("StatusBar (placeholder)", [placeholder("connection chip", 120), placeholder("env badge", 40, 16),
                                            rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=STATUS_H)


def band() -> Node:
    """CMP-087's band: region "Admin area", never focusable (§2.1, §17.1); fill color.surface.raised (§16)."""
    ln = L('the "Admin area" band')
    copy_gap(f'"Admin area": the band region name, from §2.1 L{ln} (CMP-087 own string; not in §15)')
    return hbox("CMP-087 band", [text("label", "Admin area", BODY_STRONG, TEXT_1)],
                {"pad": INSET_LG, "fill": ADMIN_TINT}, w=INNER_W, h=BAND_H,
                note='role="region" aria-label="Admin area"; never focusable')


def rule() -> Node:
    return rect("CMP-087 rule (4 px)", INNER_W, RULE_H, ADMIN_RULE, note="§16: color.text.tertiary, 4 px")


def page_header(as_of: str = AS_OF) -> Node:
    """CMP-088 PageHeader: the h1 W-02, the meta W-03 "All times UTC · as of <as_of>", no actions (§2.2 item 1)."""
    lines = [text("h1", w("W-02"), HEADING_MD, TEXT_1, note="the one h1; the document title (§17.2)"),
             text("meta", w("W-03", None, as_of), CAPTION, TEXT_3)]
    return vbox("CMP-088 PageHeader", lines, {"gap": STACK_SM, "padY": INSET_LG}, w=INNER_W)


def window(fid: str, theme: str, sections: Iterable[Node], *, scroll: int = 0, as_of: str = AS_OF,
           overlays: Iterable[Node] = (), note: str | None = None) -> Node:
    """One 1280 x 800 window (§0): TopBar | NavRail · main · RightRail | StatusBar, the main column (976, clip) holding
    the page (band, rule, PageHeader, then `sections` in §2.2's order) at y = 16 - scroll: scroll > 0 shows a lower
    part of the page (the band and header scroll away with it). overlays (modal()) sit on top of the whole frame."""
    if theme not in ("dark", "light", "hc"):
        raise ValueError(theme)
    page = vbox("page", [band(), rule(), page_header(as_of), *sections], {"gap": STACK_LG}, w=INNER_W, x=16,
                y=16 - scroll, note="<main>: band → rule → PageHeader → the sections of §2.2, in Tab order (§17.3)")
    main = box("main", [page], {"fill": APP, "clip": True}, w=MAIN_W, h=BODY_H, note=f"scroll {scroll} px")
    body = hbox("body", [navrail(), main, rightrail()], {"align": "start"}, w=FRAME_W, h=BODY_H)
    need = est_height(page)
    if scroll == 0 and need > VIEW_H:
        live(f"{fid}: the page is about {need:.0f} px for a {VIEW_H} px view: the export shows its top only "
             f"(as drawn); read back that the main column clips it")
    return vbox(frame_name(fid, theme), [topbar(), body, statusbar(), *overlays], {"fill": APP, "clip": True},
                w=FRAME_W, h=FRAME_H, note=note)


# --- sections and the state vocabulary (§2.2, §5)
def section(h2: str, kids: Iterable[Node | None], *, waits: Iterable[str] = (), note: str | None = None) -> Node:
    """A region named by its h2 (§2.2: "each section is a region named by its h2"), its kids, and, when it waits on
    G-rows, the marker line "Waits on D09-Gn" in caption tertiary (§0: "each frame marked with the G-row")."""
    head: list[Node] = [text("h2", h2, HEADING_SM, TEXT_1)]
    gs = [g(x) for x in waits]
    if gs:
        head.append(text("g-rows", "Waits on " + ", ".join(gs), CAPTION, TEXT_3))
        deviate("G-row marker line 'Waits on D09-Gn' on each waiting section: §0 asks for the mark, gives no string")
    return vbox(f"section · {h2}", [hbox("heading", head, {"gap": INSET_SM, "align": "end"}), *kids],
                {"gap": STACK_SM}, w=INNER_W, note=note or f'role="region" aria-labelledby its h2 "{h2}"')


def glyph(kind: str, color: str, name: str = "glyph") -> Node | None:
    """CMP-178's glyph by its §5.2 name (check, triangle, octagon, clock, ring); "—" draws none."""
    if kind in ("—", "", None):
        return None
    if kind == "ring":
        fallback("ring")
        return hbox(name, [ellipse("ring", 12, 12, {"stroke": color, "strokeWidth": THICK})], {"justify": "center"},
                    w=16, h=16)
    if kind not in GLYPH_ICON:
        raise ValueError(f"glyph {kind!r}")
    if kind != "check":
        fallback(kind)
    return icon(name, GLYPH_ICON[kind], color)


def tone_color(sid: str) -> str:
    """The register's tone token for a state's glyph (data-confidence ones resolve to their .indicator)."""
    t = REGISTER[sid].token
    if t.startswith(f"{DC}."):
        return t.replace(".*", ".indicator")
    if t.startswith("color."):
        return t
    return NEUTRAL  # S-13 (CMP-015): no glyph


def state_line(sid: str, figures: Iterable[str] = (), *, origin: bool = True, w_: int | None = None,
               name: str | None = None, word_w: int | None = None) -> Node:
    """A state cell/line (§5.1, §17.2): origin label, glyph, the state word, then the figures, all as text (R-5)."""
    st = REGISTER[sid]
    kids: list[Node | None] = []
    o = origin_label(sid) if origin else None
    if o:
        kids.append(text("origin", o, CAPTION, TEXT_2))
    kids.append(glyph(st.glyph, tone_color(sid)))
    kids.append(text("word", state_word(sid), BODY_STRONG, TEXT_1, **({"w": word_w} if word_w else {})))
    for i, f in enumerate(figures, 1):
        kids.append(text(f"figure-{i}", f, BODY, TEXT_1, **({"w": w_} if w_ and text_w(f, BODY) > w_ else {})))
    return hbox(name or f"state · {sid}", kids, {"gap": INSET_XS, **({"wrap": "wrap"} if w_ else {})}, w=w_,
                note=f"{sid} {st.state}: the glyph is aria-hidden beside its word")


def g_tag(gid: str) -> Node:
    k = g(gid)
    return text(f"tag · {k}", k, CAPTION, TEXT_3, note=f"§21.2: {GROWS[k][0][:80]}")


def not_connected(name: str, gid: str | Iterable[str], *, w_: int | None = None, both: bool = True) -> Node:
    """S-19 in a slot (W-05): the ring glyph, "Not connected yet" (and, with both=True, its second sentence), and the
    G-row it waits on; never 0 (R-2)."""
    gids = [gid] if isinstance(gid, str) else list(gid)
    kids: list[Node | None] = [glyph("ring", NEUTRAL), text("word", w("W-05", 0), BODY_STRONG, TEXT_1)]
    if both:
        kids.append(text("sentence", w("W-05", 1), BODY, TEXT_2))
    kids += [g_tag(x) for x in gids]
    return hbox(name, kids, {"gap": INSET_XS, **({"wrap": "wrap"} if w_ else {})}, w=w_, note="S-19; never 0 (R-2)")


def tile(heading: str, sid: str | None, number: str | None, *, w_: int, as_of: str | None = AS_OF,
         extra: Iterable[Node] = (), gid: str | None = None, status: Node | None = None,
         wrap_word: bool | None = None) -> Node:
    """A CMP-178 tile (§2.2 item 2): heading (a link), the state word with its glyph, one number with its unit (or
    S-19 when number is None and gid is given), "as of"; raised, radius.card, space.inset.lg."""
    inner = w_ - 2 * PX[INSET_LG]
    kids: list[Node | None] = [text("heading", heading, HEADING_SM, TEXT_LINK)]
    if number is None and gid:
        kids.append(not_connected("value", gid, w_=inner, both=False))
    else:
        if status is None and sid is None:
            raise ValueError(f"tile {heading!r}: sid= or status= (the clock's ok state has no S-id, §10)")
        if status:
            # §2.2 item 2 (the word, then one number with its unit): a status's figures leave its line for the
            # number's, so every tile reads word over number (the clock's "In sync" / "12 ms behind" on every board)
            figs = [c for c in status["kids"] if c["name"].startswith("figure")]
            kids.append(dict(status, name="state", kids=[c for c in status["kids"] if c not in figs]))
            kids += [dict(f, name="number" if i == 0 else f"number-{i + 1}", w=inner) for i, f in enumerate(figs)]
        else:
            # a word wider than the room beside its glyph wraps there (wrap_word None = when the estimate says so),
            # so the glyph never sits alone on a line (§5.2: the glyph beside its word)
            beside = inner - PX[ICON] - PX[INSET_XS]
            if wrap_word is None:
                wrap_word = text_w(state_word(sid), BODY_STRONG) > beside
            kids.append(state_line(sid, origin=False, w_=inner, name="state", word_w=beside if wrap_word else None))
        if number:
            kids.append(text("number", number, NUM, TEXT_1, w=inner))
    kids += list(extra)
    if as_of:
        kids.append(text("as of", f"as of {as_of}", CAPTION, TEXT_3))
    return vbox(f"CMP-178 tile · {heading}", kids, {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG,
                                                   "gap": STACK_SM}, w=w_,
                note='role="region" labelled by its heading; numbers carry units in words in the name (§17.2)')


TILE_HEADINGS = ("REST budget", "Public market data", "Private streams", "Clock", "IP hold")  # §2.2 item 2


def tile_widths(n: int = 5, total: int = INNER_W, gap: int = 12) -> list[int]:
    base = (total - gap * (n - 1)) // n
    ws = [base] * n
    ws[n // 2] += total - gap * (n - 1) - base * n
    return ws


def summary_strip(tiles: list[Node]) -> Node:
    """The five tiles in one row, space.stack.md gaps, one shared height (no h2: each tile is its own region)."""
    return hbox("summary strip", tiles, {"gap": STACK_MD, "align": "start"}, w=INNER_W)


METER_FILL = {"normal": ACTION_PRIMARY, "warning": WARN_STRONG, "danger": DANGER_DEFAULT}  # §16 meter fills


def meter(used: float, limit: float, *, w_: int = 72, tone: str = "normal", valuetext: str = "") -> Node:
    """CMP-023 kind="meter", 8 px: the color.surface.hover track and a stepped fill (never animates, §3.2)."""
    fw = round(w_ * max(0.0, min(used / limit, 1.0))) if limit else 0
    kids = [rect("track", w_, 8, TRACK, {"radius": R_BADGE}, x=0, y=0)]
    if fw:
        kids.append(rect("fill", fw, 8, METER_FILL[tone], {"radius": R_BADGE}, x=0, y=0))
    return box("CMP-023 meter", kids, None, w=w_, h=8,
               note=f'role="meter"; aria-valuetext "{valuetext}"' if valuetext else 'role="meter"')


# --- CMP-049 tables: every cell is a box padded space.inset.sm (8 px) a side, so adjacent texts sit >= 16 px apart
@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    numeric: bool = False


def cell(name: str, content: str | Node | list[Node] | None, w_: int, *, numeric: bool = False, h: int = ROW_H,
         typo: str | None = None, color: str = TEXT_1, second: str | None = None) -> Node:
    """One cell: padX 8 px, end-justified for numbers (type.num.base), start otherwise; `second` adds a secondary
    line under the text (the Class cell's adapter class, §3.1)."""
    inner = w_ - 2 * PX[INSET_SM]
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        t = text("value", content, typo or (NUM if numeric else BODY), color,
                 **({"w": inner} if text_w(content, typo or (NUM if numeric else BODY)) > inner else {}))
        kids = [t]
        if second:
            kids = [vbox("lines", [t, text("second", second, CAPTION, TEXT_2)], {"gap": STACK_XS})]
    elif isinstance(content, list):
        kids = content
    else:
        kids = [content]
    return hbox(name, kids, {"padX": INSET_SM, "justify": "end" if numeric else "start", "gap": INSET_XS}, w=w_, h=h)


def header_row(cols: Iterable[Col], *, fill: str = CANVAS) -> Node:
    cs = list(cols)
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=CAPTION, color=TEXT_2)
                               for c in cs], {"fill": fill}, w=sum(c.w for c in cs), h=ROW_H,
                note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, i: int, *,
              h: int | None = None, focused: bool = False, second: dict[str, str] | None = None,
              colors: dict[str, str] | None = None) -> Node:
    """One body row: zebra (odd color.surface.canvas, even color.surface.raised, §16); focused adds the 2 px ring.
    h=None: the tallest cell's content + 8 px a side, at least ROW_H (32), rounded up to 4 px."""
    cs = list(cols)
    if h is None:
        probe = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, second=(second or {}).get(c.key))
                 for c in cs]
        need = max((est_height(dict(k, h=None)) for k in probe), default=0.0) + 2 * PX[INSET_SM]
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    kids = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, second=(second or {}).get(c.key),
                 color=(colors or {}).get(c.key, TEXT_1)) for c in cs]
    for k in kids:  # a cell's content must fit the row (no clipped or overlapping text): pass a taller h
        need = est_height(dict(k, h=None))
        if need > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs about {need:.0f} px > row h {h}")
    o: dict[str, Any] = {"fill": CANVAS if i % 2 else RAISED}
    if focused:
        o.update({"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"})
    return hbox(name, kids, o, w=sum(c.w for c in cs), h=h)


def table(name: str, caption_: str | None, header: Node, rows: list[Node], *, note: str | None = None) -> Node:
    """A CMP-049 table: the visible caption (type.ui.caption, secondary), the header row, a 1 px rule, the rows."""
    wd = header["w"]
    kids = [text("caption", caption_, CAPTION, TEXT_2, w=wd) if caption_ else None, header,
            rect("header rule", wd, 1, BORDER),
            vbox("rows", rows, None, w=wd, h=round(sum(est_height(r) for r in rows))) if rows else None]
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, note=note)


# §3.2's columns at 944 px (W-08 gives the six headings; Meter and State carry no visible heading in §3.2's list, so
# the kit draws them from §3.2's Column cells; the action column holds the row action "Change budget…", W-60)
BUDGET_COLS = (Col("class", "Class", 168), Col("account", "Account", 96), Col("limit", "Limit", 104, True),
               Col("used", "Used now", 80, True), Col("window", "Window", 64, True),
               Col("headroom", "Headroom", 120, True), Col("meter", "Meter", 88), Col("state", "State", 176),
               Col("action", "", 48))
assert sum(c.w for c in BUDGET_COLS) == INNER_W


def budget_header() -> Node:
    heads = w("W-08").split(" · ")
    cols = [Col(c.key, heads[i] if i < len(heads) else c.label, c.w, c.numeric) for i, c in enumerate(BUDGET_COLS)]
    copy_gap(f'budget table headings "Meter" and "State": §3.2 L{L("| Meter    |")} and L{L("| State    |")} '
             f"(W-08 lists six)")
    return header_row(cols)


def row_action(focused: bool = False) -> Node:
    """The account row's action cell: a 24 px more-horizontal button opening the row menu ("Change budget…")."""
    btn = hbox("row action", [icon("glyph", "more-horizontal", TEXT_2)], {"justify": "center", "radius": R_CONTROL},
               w=24, h=24, note=f'opens the row menu: "{w("W-60")}" (Shift+F10, SCR-147-KB-2)')
    return ring(btn) if focused else btn


# --- CMP-036 key-value rows (the reserve band, the clock dl)
def kv_row(name: str, label_: str, value: str | Node, *, w_: int = INNER_W, label_w: int = 280,
           glyph_kind: str | None = None, glyph_color: str = NEUTRAL, numeric: bool = False) -> Node:
    lead = [glyph(glyph_kind, glyph_color)] if glyph_kind else []
    lab = hbox("label", [*lead, text("text", label_, BODY, TEXT_2)], {"gap": INSET_XS, "padX": INSET_SM},
               w=label_w, h=ROW_H)
    val = value if isinstance(value, dict) else text("text", value, NUM if numeric else BODY, TEXT_1)
    return hbox(name, [lab, hbox("value", [val], {"padX": INSET_SM, "gap": INSET_XS}, w=w_ - label_w, h=ROW_H)],
                None, w=w_, h=ROW_H)


def reserve_band(rows: Iterable[tuple[str, int | None]], gid: str = "D09-G14", *, label_w: int = 280) -> Node:
    """§7 item 1: one CMP-036 row per account, "Reserved for stops and cancels" with W-06a (not served) or W-06b's
    count, never both; the ring glyph in color.neutral.default; outside the meter, never added to Headroom."""
    out = []
    for i, (alias, n) in enumerate(rows, 1):
        lab = f"{w('W-06a', 0)} · {alias}"
        val = (not_connected("value", gid, both=False) if n is None else text("text", w("W-06b", 1, n), NUM, TEXT_1))
        out.append(kv_row(f"reserve · {alias}", lab, val, glyph_kind="ring", label_w=label_w))
    return vbox("reserve band", out, {"stroke": NEUTRAL, "strokeWidth": HAIR, "strokeAlign": "inner",
                                      "radius": R_CARD}, w=INNER_W,
                note="separate labelled band (§7 item 1); never focusable (§17.3)")


# --- controls (CMP-001 / CMP-079 / CMP-039 compositions at the comfortable 32 px)
BUTTON_LOOK = {"primary": (ACTION_PRIMARY, TEXT_ON_ACTION, None), "secondary": (ACTION_SECONDARY, TEXT_1, None),
               "ghost": (None, TEXT_2, None), "destructive": (DANGER_SUBTLE, TEXT_1, DANGER_STRONG)}


def ring(control: Node, radius: str = R_CONTROL) -> Node:
    """CMP-039 focus-visible: a wrapper with 4 px padding and a 2 px color.focus.ring inner stroke."""
    return hbox("focus-ring", [control], {"pad": INSET_XS, "radius": radius, "stroke": RING, "strokeWidth": FOCUS_W,
                                          "strokeAlign": "inner"}, note="focus-visible")


def button(chars: str, variant: str = "secondary", *, focused: bool = False, name: str | None = None,
           lead: Node | None = None) -> Node:
    fill_, col, stroke = BUTTON_LOOK[variant]
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIR, strokeAlign="inner")
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, o, w=wd, h=CONTROL_H)
    return ring(b) if focused else b


def busy_button(chars: str, variant: str = "secondary", *, name: str | None = None) -> Node:
    """aria-busy (W-35's "Measuring…"): the label replaced by the busy word with a pending glyph leading."""
    return button(chars, variant, name=name or f"button · {chars} (busy)", lead=icon("busy", "pending", TEXT_2))


def t2_button(chars: str, reason: str, *, focused: bool = False, name: str | None = None, w_: int = 320) -> Node:
    """R-9 / §17.5 rendering 2a: the lock leads the full label (color.text.tertiary) on raised + border.default; the
    reason under it in color.text.secondary (aria-describedby); aria-disabled, never disabled."""
    kids = [icon("lock", "locked", TEXT_3), text("label", chars, BODY_STRONG, TEXT_3)]
    b = hbox(f"T2 · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "fill": RAISED,
                                     "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"},
             w=round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2), h=CONTROL_H,
             note='aria-disabled="true"; the reason is its aria-describedby')
    return vbox(name or f"T2 · {chars} + reason", [ring(b) if focused else b,
                                                   text("reason", reason, CAPTION, TEXT_2, w=w_)], {"gap": INSET_XS})


def inline_error(chars: str, *, w_: int = 480, name: str = "CMP-027 InlineError") -> Node:
    return hbox(name, [icon("glyph", "danger", DANGER_STRONG), text("text", chars, BODY, TEXT_1, w=w_ - 24)],
                {"gap": INSET_XS, "align": "start"}, w=w_)


def skeleton(name: str, w_: int, lines: int = 3) -> Node:
    """CMP-015 Skeleton (S-13): static bars (reduced motion), aria-busy on the section."""
    fallback("skeleton")
    bars = [rect(f"bar-{i}", w_ if i < lines else w_ * 2 // 3, 12, HOVER, {"radius": R_BADGE})
            for i in range(1, lines + 1)]
    return vbox(name, bars, {"gap": STACK_SM}, w=w_, h=lines * 12 + (lines - 1) * 8, note='aria-busy="true"')


# --- dialogs (CMP-044 alertdialog over the flat scrim), disclosures, form controls, the sparkline
DIALOG_W = 560  # kit choice: no source gives CMP-044's width at 1280 (deviation recorded when used)


def dialog(title: str, kids: Iterable[Node | None], actions: Iterable[Node], *, name: str | None = None,
           w_: int = DIALOG_W) -> Node:
    """CMP-044 variant="standard", role="alertdialog" (§11): color.surface.overlay, radius.dialog, space.dialog.padding;
    the title an h2; actions end-aligned, [Cancel] (focus) first."""
    deviate(f"dialog width {w_} px: a kit choice (no source gives CMP-044's width)")
    iw = w_ - 2 * PX[DIALOG_PAD]
    body = [text("title", title, HEADING_MD, TEXT_1, w=iw, note="the dialog's name"), *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "justify": "end"}, w=iw, h=CONTROL_H + 8)]
    return vbox(name or f"CMP-044 dialog · {title}", body, {"fill": OVERLAY, "radius": R_DIALOG, "pad": DIALOG_PAD,
                                                           "gap": STACK_MD, "stroke": BORDER, "strokeWidth": HAIR,
                                                           "strokeAlign": "inner"}, w=w_,
                note='role="alertdialog"; focus on Cancel; the first consequence is the description (§17.1)')


def lines_block(name: str, lines: Iterable[str], *, w_: int, typo: str = BODY, color: str = TEXT_1) -> Node:
    ls = [x for x in lines if x]
    return vbox(name, [text(f"line-{i}", s, typo, color, w=w_) for i, s in enumerate(ls, 1)], {"gap": STACK_XS},
                w=w_)


def modal(dialog_node: Node, measured_h: int | None = None) -> list[Node]:
    """The overlay for window(overlays=...): the flat scrim over the whole frame and the dialog centred on it.
    measured_h: the dialog's height as drawn (the live check's SHEET-FIX), used for the centring in place of the
    estimate."""
    fallback("scrim")
    dw, dh = est_width(dialog_node), (measured_h if measured_h is not None else est_height(dialog_node))
    live(f"modal: re-centre '{dialog_node['name']}' after relayout (estimated {dw:.0f} x {dh:.0f} px)")
    scrim = rect("scrim", FRAME_W, FRAME_H, SCRIM, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    dlg = dict(dialog_node, x=round((FRAME_W - dw) / 2), y=round(max((FRAME_H - dh) / 2, 0)))
    return [box("overlay", [scrim, dlg], None, w=FRAME_W, h=FRAME_H, x=0, y=0, abs=True)]


def disclosure(label_: str, *, open_: bool = False, focused: bool = False, name: str | None = None) -> Node:
    """A native disclosure trigger: chevron-right closed / chevron-down open, the label (W-44, W-70, W-71's "View as
    table"); aria-expanded in its note."""
    kids = [icon("chevron", "chevron-down" if open_ else "chevron-right", TEXT_2), text("label", label_, BODY_STRONG,
                                                                                       TEXT_1)]
    b = hbox(name or f"disclosure · {label_}", kids, {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL},
             h=CONTROL_H, note=f'aria-expanded="{str(open_).lower()}"')
    return ring(b) if focused else b


def checkbox(label_: str, *, checked: bool = False, focused: bool = False) -> Node:
    boxk = hbox("box", [icon("check", "check", TEXT_ON_ACTION, ICON_SM)] if checked else [],
                {"justify": "center", "radius": R_BADGE, "fill": ACTION_PRIMARY if checked else CANVAS,
                 "stroke": TEXT_3, "strokeWidth": HAIR, "strokeAlign": "inner"}, w=16, h=16)
    c = hbox(f"checkbox · {label_}", [boxk, text("label", label_, BODY, TEXT_1)], {"gap": INSET_SM}, h=24,
             note=f'aria-checked="{str(checked).lower()}"')
    return ring(c) if focused else c


def number_field(label_: str, value: str, *, unit: str | None = None, w_: int = 96, focused: bool = False,
                 error: str | None = None) -> Node:
    fld = hbox("field", [text("value", value, NUM, TEXT_1)] + ([text("unit", unit, CAPTION, TEXT_2)] if unit else []),
               {"padX": INSET_SM, "gap": INSET_XS, "radius": R_CONTROL, "fill": CANVAS,
                "stroke": DANGER_STRONG if error else TEXT_3, "strokeWidth": HAIR, "strokeAlign": "inner"},
               w=w_, h=CONTROL_H)
    kids: list[Node | None] = [text("label", label_, LABEL, TEXT_2), ring(fld) if focused else fld]
    if error:
        kids.append(inline_error(error, w_=max(w_, 360)))
    return vbox(f"number field · {label_}", kids, {"gap": INSET_XS})


def segmented(options: Iterable[str], selected: str, *, focused: bool = False) -> Node:
    segs = [hbox(f"segment · {o}", [text("label", o, BODY_STRONG, TEXT_1 if o == selected else TEXT_2)],
                 {"padX": INSET_MD, "radius": R_CONTROL, **({"fill": SELECTED} if o == selected else {})},
                 h=CONTROL_H - 4) for o in options]
    s = hbox("segmented control", segs, {"pad": INSET_XS, "gap": INSET_XS, "radius": R_CONTROL, "fill": SUNKEN},
             h=CONTROL_H + 4, note='radiogroup; arrows move (SCR-147-KB-4)')
    return ring(s) if focused else s


def sparkline(values: list[float], *, w_: int = 360, h: int = 48, vmax: float | None = None,
              name: str = "CMP-024 sparkline") -> Node:
    """CMP-024 (role="img", the trend label W-72 as its name): one 2 px column mark per sample, scaled to vmax."""
    fallback("sparkline")
    top = vmax or max(values) or 1
    step = w_ / max(len(values), 1)
    marks = [rect(f"m-{i:02d}", 2, max(2, round(h * v / top)), ACTION_PRIMARY, x=round(i * step),
                  y=h - max(2, round(h * v / top))) for i, v in enumerate(values)]
    return box(name, [rect("baseline", w_, 1, BORDER_SUBTLE, x=0, y=h - 1), *marks], None, w=w_, h=h,
               note='role="img"; named by the trend label (W-72); the table is its alternative (§14)')


# --- the annotation column (ONE, 400 px, outside the frames) and the board
def frame_block(fid: str, *, lines: Iterable[str] = (), keyboard: str | None = None, waits: Iterable[str] = (),
                suppressed: Iterable[str] = (), recovery: bool = False) -> tuple[str, list[str]]:
    """The annotation block of one frame: for every S-id the frame plan gives it, the register's facts (word, origin,
    glyph, tone, trigger, exit, announcement and rate, the SR rows and strings, the origin's action line); then the
    G-rows it waits on, suppressed states (§5.2 precedence), the keyboard path and the author's lines."""
    plan = dict((f, s) for b in FRAME_PLAN.values() for f, s in b)
    if fid not in plan:
        raise KeyError(f"{fid!r} is not in FRAME_PLAN")
    out: list[str] = []
    for sid in plan[fid]:
        st = REGISTER[sid]
        out.append(f'{sid} {st.state} (§5.2 L{st.line}): "{st.word}"{f" ({st.wkey})" if st.wkey else ""}; origin '
                   f"{st.origin}; glyph {st.glyph}; tone {st.token}")
        out.append(f"Trigger: {st.trigger}. Exit: {st.exit}.")
        out.append(f"Announce: {st.announce}; max rate {st.max_rate}.")
        for sr in SR_FOR.get(sid, []):
            ev, s, pol, ln = SR[sr]
            out.append(f"{sr} (§17.4 L{ln}, {pol}): {s}")
        act = origin_action(sid)
        if act:
            out.append(f"Operator action (W-12): {act}")
    if recovery:
        ev, s, pol, ln = SR["SCR-147-SR-9"]
        out.append(f"SCR-147-SR-9 (§17.4 L{ln}, {pol}, on exit): {s}")
    for sid in suppressed:
        out.append(f"Suppressed on this row by precedence (§5.2 L{L('- **Precedence on one row:**')}): {sid} "
                   f"{REGISTER[sid].state}")
    gs = [g(x) for x in waits]
    if gs:
        out.append("Waits on " + ", ".join(f"{k} ({GROWS[k][0][:60]})" for k in gs))
    if keyboard:
        out.append(f"Keyboard: {keyboard}")
    out += [x for x in lines if x]
    return fid, out


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title (the board name), a "Board" block (§0's Draws, theme, twin, export, W-01), one
    block per frame (frame_block()), footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}",
            f"Theme: {b.theme}" + (f" (twin of board {b.twin:02d}: same frames, same values)" if b.twin else ""),
            f"Export: {b.export}", f"Board footer (W-01): {w('W-01')}", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    """Frames placed 1:1 in rows of <= MAX_PER_ROW (4 frames: 2 x 2), MARGIN margin and gutters."""
    k = per_row or (2 if len(frames) in (2, 4) else MAX_PER_ROW)
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        row = frames[i:i + k]
        x = MARGIN
        for f in row:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in row) + MARGIN
        i += k
    return out


# Root h per board as drawn: the live-measured max(annotation end, footer end) + MARGIN after touchTexts + relayout
# (the live checks' SHEET-FIX; text_h over-estimates the column). board() uses it for strict boards. 02, 03, 06
# and 10 are the round-2 live check's measures after the boards lens's kit fix; 01, 07 and 08 end on their footers.
MEASURED_H = {1: 2758, 2: 1874, 3: 1481, 4: 2506, 5: 2270, 6: 1878, 7: 2758, 8: 2758, 9: 2244, 10: 1905}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int | None = None, strict: bool = True,
          footer: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, fill color.surface.app, clip) hugging its frames + the annotation
    column + MARGIN; a "state: <fid>" caption 28 px above each frame; the W-01 footer under the frames. Checks the
    frame names against FRAME_PLAN in the board's theme and the pitch."""
    b = BOARDS[nn]
    plan = frames_of(nn)
    want = [frame_name(f, b.theme) for f, _s in plan]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != FRAME_PLAN {want}")
    if any(f["w"] != FRAME_W or f["h"] != FRAME_H for f in frames):
        raise ValueError(f"board {nn:02d}: every frame is a {FRAME_W} x {FRAME_H} window (§0)")
    placed = layout(frames, per_row)
    fid_of = {frame_name(f, b.theme): f for f, _s in plan}
    caps = [text(f"caption {i:02d}", f"state: {fid_of.get(f['name'], f['name'])}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · W-01", w("W-01"), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)] if footer else []
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < frames bottom {bottom} + {MARGIN}")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h to its end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; e42kit's packer, copied), lint, write, pack
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


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children without
    text carry h; no '/' in names; table cells padded 8 px a side (cells are named by their column key)."""
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
        for k in n.get("kids") or []:
            rec(k, bool(o.get("dir")), p)

    for n in nodes:
        rec(n, False, "")
    for n in nodes:
        for p, x in walk(n):
            if (x["t"] == "board" and re.search(r"/(header row|row[^/]*)/[^/]+$", p) and "padX" in (x.get("o") or {})
                    and (x["o"]["padX"] != INSET_SM)):
                bad.append(f"{p}: cell padX {x['o']['padX']} (8 px a side required)")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, "\n".join(lines)


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int | None = None, out_dir: Path = CAP_DIR, name: str | None = None,
                strict: bool = True) -> Path:
    """Assemble board nn (board()), split into sections, merge notes (the kit's + notes=), write
    out_dir/NN-<slug>.json, run the validator (tokens + components) and raise RuntimeError unless it exits 0 and the
    kit lint and the banned scan are clean. Requires at least one live_checks line. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row, strict=strict)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d} (twin of {b.twin:02d}); read "
             f"back one bound fill (color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}: every frame is {FRAME_W} x {FRAME_H}; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]} (§0 L{b.line}, §2, §3, §5.2, §15, §16, "
                         f"§17); hand-off {HANDOFF.name} md5 {SPEC_MD5[HANDOFF.name][:8]}")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    if not sheet["notes"]["live_checks"]:
        raise RuntimeError(f"board {nn:02d}: notes.live_checks is empty")
    out = out_dir / (name or b.sheet)
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rc, msg = validate(out)
    if rc != 0:
        errs = [ln for ln in msg.splitlines() if "ERROR" in ln.upper()]
        raise RuntimeError(f"{out.name}: validator exit {rc}\n" + "\n".join(errs[:20] or msg.splitlines()[-20:]))
    return out


def md_line3(nn: int) -> str:
    """The render script's line (it parses "page `...`" and "theme dark." / "theme light." / "theme hc.")."""
    b = BOARDS[nn]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "", frames_info: Iterable[str] = ()) -> Path:
    """The sheet's .md beside it: line 1 "# <board name>", line 3 md_line3(nn), then the summary, frames, the
    validator line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; footer W-01; \"page {PAGE} · board {nn:02d} · "
                      f"{REV}\".", "", "## Frames", ""]
    out += [f"- `{frame_name(f, b.theme)}` ({', '.join(s) or 'no S-id'})" for f, s in frames_of(nn)]
    out += [f"- {ln}" for ln in frames_info]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "g_rows", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "fallbacks", "sources",
               "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    (sp.parent / (sp.stem + ".md")).write_text(s, encoding="utf-8")  # beside the sheet (the render drivers' set)
    p = (KIT_DIR if sp.parent == CAP_DIR.resolve() else sp.parent) / (sp.stem + ".md")  # the committed copy
    p.write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>; the packer writes the source's absolute path into compactOf.file,
    which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged); check that, every
    packed section <= PACKED_MAX bytes (compact JSON), and that mkcall4.py's `count` agrees."""
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
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(n_sec):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} "
                           f"!= {n_sec}: {cnt.stderr.strip()[-300:]}")
    abs_field = json.dumps(pf, ensure_ascii=False)
    if raw.count(abs_field) != 1:
        raise RuntimeError(f"{dst.name}: the pack source path occurs {raw.count(abs_field)} times")
    dst.write_text(raw.replace(abs_field, json.dumps(src.name, ensure_ascii=False)), encoding="utf-8")
    sh = json.loads(dst.read_text(encoding="utf-8"))
    if sh["compactOf"] != {"file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}:
        raise RuntimeError(f"{dst.name}: compactOf {sh['compactOf']!r} is not the bare name and sha256 of {src.name}")
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    return dst


# --- self-test: python3 -I -B e08d09kit.py selftest
def clock_ok_status(offset_ms: int, direction: str = "behind") -> Node:
    """The clock's ok status (§10: "In sync", W-29; S-01 is not used for the clock): check glyph + "In sync"."""
    return hbox("state · clock ok", [glyph("check", OK_STRONG), text("word", w("W-29", 0), BODY_STRONG, TEXT_1),
                                     text("figure-1", w("W-29", 1, offset_ms, direction), NUM, TEXT_1)],
                {"gap": INSET_XS})


def sample_frame() -> tuple[Node, tuple[str, list[str]]]:
    """Board 02's S-03 frame as the sample: Main's order.create throttled at its limit, retry 42 s after AS_OF; the
    other figures served and within budget; the reserve not served (S-19)."""
    fid = frames_of(2)[1][0]
    lim, retry_s = LIM["order_per_s"], 42
    tw = tile_widths()
    tiles = [tile(TILE_HEADINGS[0], "S-03", w("W-15", 2, lim), w_=tw[0]),
             tile(TILE_HEADINGS[1], "S-01", w("W-52", 1, 120), w_=tw[1]),
             tile(TILE_HEADINGS[2], None, None, w_=tw[2], gid="D09-G1"),
             tile(TILE_HEADINGS[3], None, None, w_=tw[3], status=clock_ok_status(12)),
             tile(TILE_HEADINGS[4], "S-01", None, w_=tw[4])]
    cols = BUDGET_COLS
    rows = [table_row(cols, {"class": "order.create", "account": ACCOUNTS[0], "limit": f"{lim} / s", "used": str(lim),
                             "window": "1 s", "headroom": headroom_cell(lim, lim),
                             "meter": meter(lim, lim, tone="danger", valuetext=w("W-09", None, lim, lim, 0)),
                             "state": state_line("S-03", [w("W-15", 3, at(retry_s), retry_s)], w_=160),
                             "action": row_action()}, "row 01 · order.create · Main", 1,
                      second={"class": "order"}),
            table_row(cols, {"class": "order.amend", "account": ACCOUNTS[0], "limit": f"{lim} / s", "used": "2",
                             "window": "1 s", "headroom": headroom_cell(lim, 2),
                             "meter": meter(2, lim, valuetext=w("W-09", None, 2, lim, 8)),
                             "state": state_line("S-01", origin=False, w_=160), "action": row_action()},
                      "row 02 · order.amend · Main", 2, second={"class": "order"})]
    deviate("sample: Headroom shown as served (the reserve figure D09-G14 is not served; a board draws its S-19)")
    budgets = section("Rate budgets", [table("CMP-049 budgets", w("W-07"), budget_header(), rows),
                                       reserve_band([(ACCOUNTS[0], None)])], waits=["D09-G1"])
    fr = window(fid, BOARDS[2].theme, [summary_strip(tiles), budgets])
    blk = frame_block(fid, waits=["D09-G1"], keyboard="Tab reaches the budgets grid as one stop; arrows move "
                                                      "(SCR-147-KB-2)",
                      lines=[f"Retry at {at(retry_s)} = as of {AS_OF} + {retry_s} s (derived)"])
    return fr, blk


def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s {spec_md5_ok()}")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10")
    th = [b.theme for b in BOARDS.values()]
    check((th.count("dark"), th.count("light"), th.count("hc")) == (7, 2, 1), f"§0 themes 7 dark / 2 light / 1 hc")
    check(TWINS == {8: 1, 9: 5, 10: 2}, f"§0 twins {TWINS}")
    check(sorted(n for p in PAIRS for n in p) == list(range(1, 11))
          and all(any(set(p) == {t, base} for p in PAIRS) for t, base in TWINS.items()), "five pairs, twins paired")
    check(sorted(REGISTER) == [f"S-{i:02d}" for i in range(1, 21)], "§5.2: twenty states")
    check(set(PRECEDENCE) <= set(REGISTER) and len(PRECEDENCE) == 18, f"§5.2 precedence ({len(PRECEDENCE)})")
    drawn = {s for b in FRAME_PLAN.values() for _f, ss in b for s in ss}
    check(drawn == set(REGISTER), f"every S-id on a frame (missing {sorted(set(REGISTER) - drawn)})")
    ok0 = all(set(b.states) <= {s for _f, ss in frames_of(nn) for s in ss} for nn, b in BOARDS.items())
    check(ok0, "§0's S-ids per board are frames of that board")
    regb = all(nn in REGISTER[s].boards for nn, plan in FRAME_PLAN.items() for _f, ss in plan for s in ss)
    check(regb, "§5.2 Board column agrees with FRAME_PLAN")
    want = {f"W-{i:02d}" for i in range(1, 75)} - {"W-06", "W-49", *(f"W-{i}" for i in range(65, 70))}
    want |= {"W-06a", "W-06b", "W-36b"}
    check(set(COPY) == want and COPY["W-01"].text == "illustrative values, not a market capture",
          f"§15: {len(COPY)} strings, W-01 verbatim")
    check(len(SR) == 13 and len(T2_ROWS) == 4 and len(GROWS) == 18, f"§17.4 SR {len(SR)}, §17.5 T2 {len(T2_ROWS)}, "
                                                                     f"§21.2 G {len(GROWS)}")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k, v in globals().items() if k.isupper() and k != "DC" and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)]
    used += [tone_color(s) for s in REGISTER] + [f"{DC}.{k}.{p}" for k in ("disconnected", "reconnecting", "stale")
                                                 for p in ("text", "indicator")] + [f"{DC}.stale.surface"]
    check(all(u in toks for u in used), f"kit tokens exist ({len(set(used))}; missing "
                                        f"{sorted(set(u for u in used if u not in toks))})")
    check(w("W-15", 2, 10) == "Limit 10 requests per second" and w("W-29", 1, 12, "behind") == "12 ms behind",
          "w(): slots filled in order")
    try:
        w("W-15", 3)
        check(False, "w(): unfilled slots refused")
    except ValueError:
        check(True, "w(): unfilled slots refused")
    check(at(42) == "14:02:53" and at(-13) == "14:01:58" and dur(500) == "8m 20s" and dur(42) == "42 s",
          "clock helpers")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap and '/' refused")
    for nn in BOARDS:
        n = len(frames_of(nn))
        k = 2 if n in (2, 4) else MAX_PER_ROW
        wd = MARGIN + min(n, k) * (FRAME_W + MARGIN) + ANN_W + MARGIN
        hh = MARGIN + math.ceil(n / k) * (FRAME_H + MARGIN)
        if wd > PITCH_X - 200 or hh > PITCH_Y - 200:
            check(False, f"board {nn:02d}: {n} frames give {wd} x {hh}, over the pitch")
    check(True, "every board's frames fit the 6000 x 3200 pitch")
    NOTES.reset()
    fr, blk = sample_frame()
    ann = annotations(2, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    path = write_sheet(2, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(2, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark."), f"md line 3 parses: {l3}")  # type: ignore
    check(md_line3(10).endswith("theme hc.") and md_line3(8).endswith("theme light."), "md line 3: light and hc")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["file"] == path.name, f"packed {packed.name}: bare pack source name, sha256 ok, "
          f"{len(sh['sections'])} sections, max "
          f"{max(len(json.dumps(s, separators=(',', ':'))) for s in sh['sections'])} B, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
