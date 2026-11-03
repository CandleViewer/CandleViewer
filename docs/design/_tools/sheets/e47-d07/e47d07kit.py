"""E47-D07 (#1306) board kit: live-region announcements (the taxonomy map, the shell pair and its writers, the polite
and incident timelines, focus kept, the SCR-117 Announcements panel, the verbosity matrix, the transcript preview and
the copy anatomy), ten boards (9 dark, 1 light twin) as cvsheet JSON sheets for the per-set Penpot file
"E47-D07 boards", page "E47-D07 announcements" (spec §0, hand-off §H).

Offline only. Spec (binding; every string, number, token and frame comes from it): docs/design/E47/E47-D07.md,
E47-D07-handoff.md and E47-D07-transcripts.json as the checkout commits them, read by repo-relative path and
md5-pinned in DOCS (the kit refuses drifted bytes: re-read, re-check the cites, re-pin). The spec's own audit tool
(docs/design/_tools/e47_d07_announcement_audit.py, md5-pinned too) is loaded as a library, never run as a check: its
expand / replay / estimate re-derive every timeline figure from the seeded scripts, and the kit asserts that the
replay equals the transcripts' expected lines. E47-D04's ring geometry (§7.1 there) and E47-D05's SettingsNav label
are read with `git show <pin>`, the pins parsed from the spec's Start line. E09-D09's `rbac.view_as` reason words and
the recorded instrument fixture (BTCUSDT's tick size only) are read the same md5-pinned way.
Registry (parsed, never typed): §0's board table (BOARDS), the hand-off's §H frame plan (FRAMES), §3.1's classes,
§4's taxonomy (TAX), §7.2's copy deck (COPY), §7.3's reason map, §8.1's panel classes (PANEL), §6.4's matrix (MATRIX).

Checkout: the kit sits at docs/design/_tools/sheets/e47-d07/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md, Build).
Pipeline (one generator per board, gen/gen_NN.py; the twin's generator calls its base board's frame builder):
    frames = [...]; blocks = [(frame id, lines), ...]
    build(nn, frames, blocks) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e47d07kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host or
agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E47-D07", "E47", 1306
KIT_DIR = Path(__file__).resolve().parent


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / "docs" / "design" / EPIC).is_dir() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / "docs" / "design" / EPIC).is_dir():
        raise SystemExit("e47d07kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
FIXTURE_REL = "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json"
_PATHS = {  # alias -> repo-relative path
    "spec": "docs/design/E47/E47-D07.md",
    "handoff": "docs/design/E47/E47-D07-handoff.md",
    "transcripts": "docs/design/E47/E47-D07-transcripts.json",
    "tool": "docs/design/_tools/e47_d07_announcement_audit.py",
    "e09d09": "docs/design/E09/E09-D09.md",  # the rbac.view_as reason words
    "fixture": FIXTURE_REL,
}
_MD5 = (  # md5 as read, one per _PATHS entry in its order
    "ab7bad64846bb20d5d6355d77684ab74",
    "5b74ef6e101a54f3747d1565223c489b",
    "6bf5c553c93f66f80cebc011f9db2e4d",
    "8ab6f248f4dc14941375a22d028f52e7",
    "20c5d5f43537b6a919553704c06f7c18",
    "edd9dd2a060c51bd4bd1450307728ddf",
)
# alias -> (path, md5): every read is md5-checked
DOCS = {a: (rel, m) for (a, rel), m in zip(_PATHS.items(), _MD5, strict=True)}
REV = "r1"
PITCH_X, PITCH_Y = 7000, 4200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465", "2f746d70")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode()
                    + r"\b", re.I)


def _doc_bytes(k: str) -> bytes:
    return (REPO / DOCS[k][0]).read_bytes()


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e47d07kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_TEXT = _doc_bytes("spec").decode("utf-8")
SPEC_LINES = SPEC_TEXT.split("\n")
HANDOFF_LINES = _doc_bytes("handoff").decode("utf-8").split("\n")
E09_LINES = _doc_bytes("e09d09").decode("utf-8").split("\n")
TRANSCRIPTS = json.loads(_doc_bytes("transcripts").decode("utf-8"))
_ANCHOR = re.compile(r"([^\s|`(]+?)<!--=([A-Z]+):([^>]+?)-->", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def plain(s: str) -> str:
    """A spec cell without anchors, backticks, bold marks or table escapes."""
    s = _COMMENT.sub("", s)
    return re.sub(r"\*\*|`", "", s).replace("\\|", "|").strip()


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def find_line(needle: str, lines: list[str] | None = None, start: int = 1) -> int:
    ls = SPEC_LINES if lines is None else lines
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites: looked up, never typed."""
    return find_line(needle, start=start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, HANDOFF_LINES, start)


def table_after(head: str, lines: list[str] | None = None) -> list[tuple[int, list[str]]]:
    """(line, cells) of the first markdown table after the heading line `head` (header and rule rows dropped)."""
    ls = SPEC_LINES if lines is None else lines
    i = find_line(head, ls)
    while not ls[i].startswith("|"):
        i += 1
    out = []
    j = i + 2
    while j < len(ls) and ls[j].startswith("|"):
        out.append((j + 1, _cells(ls[j])))
        j += 1
    return out


def _parse_values() -> dict[str, str]:
    vals: dict[str, str] = {}
    for ln in SPEC_LINES + HANDOFF_LINES:
        for v, kind, key in _ANCHOR.findall(ln):
            k = f"{kind}:{key}"
            if vals.get(k, v) != v:
                raise SystemExit(f"e47d07kit: anchor {k} carries two values ({vals[k]} / {v})")
            vals[k] = v
    return vals


VAL = _parse_values()


def val(kind: str, key: str) -> str:
    """A figure from the spec's tool output (KeyError when the spec has none: never invent one)."""
    return VAL[f"{kind}:{key}"]


# --- §0: the boards; the hand-off's §H: their frames
_P0 = L("## 0. Status, artefacts and the boards")
_S0 = L("Penpot file `", _P0)
_S0_TEXT = plain(SPEC_LINES[_S0 - 1])
_PAGE_M = re.search(r"Penpot file `([^`]+)` \(README:14\), one page `([^`]+)`", SPEC_LINES[_S0 - 1])
if not _PAGE_M:
    raise SystemExit("e47d07kit: §0 names no Penpot file and page")
FILE_NAME, PAGE = _PAGE_M.group(1), _PAGE_M.group(2)
_EXPORT_PAT = re.search(r"exports go to `([^`]+)`", SPEC_LINES[_S0 - 1]).group(1)  # .../E47-D07-NN-<slug>.png
_DATA_M = re.search(r"data is the seeded synthetic stream of §10 \(seed (\d+), (\w+), tick ([\d.]+)\)",
                    SPEC_LINES[_S0 - 1])
_TWINS_M = re.search(r"of them a twin in another theme \((\d{2}) (light)\)", _S0_TEXT)
_FRAMES_RULE = re.search(r"Frames are (\d+) × (\d+) windows unless a board names a timeline strip", _S0_TEXT)
if not (_DATA_M and _TWINS_M and _FRAMES_RULE):
    raise SystemExit("e47d07kit: §0's data line, twins sentence or frame rule unreadable")
if (int(_FRAMES_RULE.group(1)), int(_FRAMES_RULE.group(2))) != (FRAME_W, FRAME_H):
    raise SystemExit("e47d07kit: §0's frame size changed")
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**")
NOT_DRAWN = plain(SPEC_LINES[NOT_DRAWN_LINE - 1]).split(":", 1)[1].strip()
THEME_OF = {"light": "light"}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str
    slug: str
    draws: str
    theme: str  # dark | light
    line: int
    twin: int | None
    frames: tuple[str, ...]  # the §H frame ids, "/" as written

    @property
    def export(self) -> str:
        return _EXPORT_PAT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


H_LINE = HL("## §H The board plan")
FRAME_THEME: dict[str, str] = {}  # "<id> · <theme>" -> theme


def _parse_frames() -> dict[int, tuple[str, ...]]:
    out = {}
    for _ln, c in table_after("## §H The board plan", HANDOFF_LINES):
        ids = re.findall(r"`([^`]+)`", c[1])
        out[int(c[0])] = tuple(ids)
    return out


FRAMES = _parse_frames()


def _parse_boards() -> dict[int, Board]:
    out = {}
    twin_nn, twin_theme = int(_TWINS_M.group(1)), THEME_OF[_TWINS_M.group(2)]
    for ln, c in table_after("## 0. Status, artefacts and the boards"):
        m = re.fullmatch(rf"`({KEY} / (\d{{2}}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise SystemExit(f"e47d07kit: §0 row L{ln} unreadable")
        nn = int(m.group(2))
        theme = c[3]
        tw = re.match(r"light twin of (\d{2})$", plain(c[2]))
        if (nn == twin_nn) != bool(tw) or (tw and theme != twin_theme):
            raise SystemExit(f"e47d07kit: §0 board {nn:02d} twin / theme disagree with the twins sentence")
        for f in FRAMES[nn]:
            if not f.endswith(f" · {theme}"):
                raise SystemExit(f"e47d07kit: §H frame {f!r} is not in board {nn:02d}'s theme {theme}")
        out[nn] = Board(nn, m.group(1), m.group(3), plain(c[2]), theme, ln, int(tw.group(1)) if tw else None,
                        FRAMES[nn])
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The §H frame id as a node name: the spec's "/" drawn as U+2215 (cvsheet's path separator is "/")."""
    return fid.replace("/", SLASH)


def frame_state(fid: str) -> str:
    """The state id without its theme suffix ("taxonomy/map · dark" -> "taxonomy/map")."""
    return fid.rsplit(" · ", 1)[0]


# --- §3.1 the five classes, §4 the taxonomy, §3.2 the assertive set
CLASSES = {plain(c[0]): dict(region=plain(c[1]), schedule=plain(c[2]), line=ln)
           for ln, c in table_after("### 3.1 The five classes")}
CLASSES_LINE = L("### 3.1 The five classes")


@dataclass(frozen=True)
class Tax:
    tid: str
    event: str
    topic: str
    cls: str
    rank: str
    surface: str
    panel: str
    words: str
    read_at: str
    line: int

    @property
    def short(self) -> str:
        """The event cell without its trailing source parenthesis."""
        return re.sub(r"\s*\([^()]*(\([^()]*\)[^()]*)*\)$", "", self.event).strip()


TAX = {plain(c[0]): Tax(plain(c[0]), plain(c[1]), plain(c[2]), plain(c[3]), plain(c[4]), plain(c[5]), plain(c[6]),
                        plain(c[7]), plain(c[8]), ln) for ln, c in table_after("## 4. The taxonomy")}
TAX_LINE = L("## 4. The taxonomy")
ASSERTIVE_SET = [dict(entry=plain(c[0]), source=plain(c[1]), rows=plain(c[2]), status=plain(c[3]), line=ln)
                 for ln, c in table_after("### 3.2 The assertive set")]
RANK_LINE = L("### 5.1 The queue") + 2
RANKS = {int(n): words.strip() for n, words in
         re.findall(r"\*\*(\d)\*\* ([^;.]+)", SPEC_LINES[RANK_LINE - 1].split("The queue is drained")[0])}


# --- §7.2 the copy deck, §7.3 the reason map, §7.1 the slots
@dataclass(frozen=True)
class Copy:
    key: str
    s: str
    source: str
    status: str
    line: int


COPY = {c[0]: Copy(c[0], plain(c[1]), plain(c[2]), plain(c[3]), ln) for ln, c in table_after("### 7.2 Copy deck")}
REASONS = {plain(c[0]): plain(c[1]) for _ln, c in table_after("### 7.3 Reason words")}
REASONS_LINE = L("### 7.3 Reason words")
GRAMMAR_LINE = L("### 7.1 Grammar and slots") + 2
SLOTS = re.findall(r"`([a-z_]+)`", SPEC_LINES[GRAMMAR_LINE - 1].split("listed in the tool")[1].split(". `minutes`")[0])


def _quoted(s: str) -> list[str]:
    return re.findall(r'"([^"]+)"', s)


def w(key: str, i: int = 0) -> str:
    """The i-th quoted string of a W-n row exactly as §7.2 gives it (NOTES records the key)."""
    c = COPY[key]
    s = _quoted(c.s)[i]
    NOTES.add("copy_keys", f"{key} (§7.2 L{c.line}, {c.source if c.source != '—' else 'no source'}; "
                           f"{c.status.split(',')[0]}): {s}")
    return s


# --- §8.1 the panel classes, §8.2 T2, §6.4 the matrix
PANEL = [dict(cls=plain(c[0]), rows=plain(c[1]), default=plain(c[2]), choice=plain(c[3]), line=ln)
         for ln, c in table_after("### 8.1 Structure")]
PANEL_LINE = L("### 8.1 Structure")
_S81 = SPEC_LINES[PANEL_LINE + 1]
REDUCE_LABEL, REDUCE_HELP = re.search(r'CMP-004 Toggle "([^"]+)" \(help: "([^"]+)"\)', _S81).groups()
SECTION_NAME = re.search(r'A FormSection "([^"]+)" in SCR-117', _S81).group(1)
T2_LINE = L("### 8.2 The fixed safety row and view-as")
MATRIX = [dict(setting=plain(c[0]), assertive=plain(c[1]), status=plain(c[2]), fields=plain(c[3]), whale=plain(c[4]),
               reads=plain(c[5]), cell=re.search(r"SIM:cell\.([a-z]+(?:-[a-z]+)*)-->", c[5]).group(1), line=ln)
          for ln, c in table_after("### 6.4 What each setting reads")]
MATRIX_HEAD = [plain(c) for c in _cells(SPEC_LINES[MATRIX[0]["line"] - 3])]
MATRIX_LINE = L("### 6.4 What each setting reads")


def _e09_reason(key: str) -> tuple[str, int]:
    for i, ln in enumerate(E09_LINES, 1):
        c = _cells(ln) if ln.startswith("|") else []
        if c and plain(c[0]) == key:
            return _quoted(c[1])[0], i
    raise LookupError(key)


VIEW_AS_REASON, VIEW_AS_LINE = _e09_reason("rbac.view_as")  # "Read-only while viewing as {user}." (D09E09:95)
VIEW_AS_USER = "user_02"  # synthetic: the viewed user in the view-as frame (declared on the board)


# --- sibling pins (the spec's Start line), read with git show
_START = plain(SPEC_LINES[L("**Start.**") - 1])
PIN = {k_: re.search(rf"{k_} (?:is read )?at (?:its (?:PR head|merge commit) )?([0-9a-f]{{7,40}})", _START).group(1)
       for k_ in ("E47-D04", "E47-D05")}


def git_show(sha: str, rel: str) -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, text=True,
                         timeout=60, check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d07kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout.split("\n")


D04_LINES = git_show(PIN["E47-D04"], "docs/design/E47/E47-D04.md")
D05_LINES = git_show(PIN["E47-D05"], "docs/design/E47/E47-D05.md")
_NAV_L = find_line('SettingsNav entry "', D05_LINES)
NAV_LABEL = re.search(r'SettingsNav entry "([^"]+)"', D05_LINES[_NAV_L - 1]).group(1)  # "Accessibility" (D05)
_TILE_L = find_line("### 6.3 Announcements", D05_LINES)
PLAY_LABEL = re.search(r'behind a "([^"]+)" button', D05_LINES[_TILE_L + 1]).group(1)  # "Play sample" (D05 §6.3)


def _ring_geometry() -> dict[str, tuple[int, int, int, int]]:
    """variant -> (ring px, halo px, offset px, D04 line) from D04 §7.1's table."""
    out = {}
    for ln, c in table_after("### 7.1 Geometry", D04_LINES):
        v = c[0].split(" ")[0]
        px = [int(m) for m in re.findall(r"(\d+) px", " ".join(c[1:4]))]
        if v == "inset":
            continue
        if len(px) != 3:
            raise SystemExit(f"e47d07kit: D04 §7.1 {v} row unreadable")
        out[v] = (px[0], px[1], px[2], ln)
    return out


RING_GEOM = _ring_geometry()


# --- the spec's audit tool as a library: the seeded scripts re-derived (expand, replay, estimate)
def _load_tool() -> Any:
    sp = importlib.util.spec_from_file_location("e47_d07_announcement_audit", REPO / DOCS["tool"][0])
    mod = importlib.util.module_from_spec(sp)  # type: ignore[arg-type]
    sys.modules[sp.name] = mod  # type: ignore[union-attr]
    sp.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


AUD = _load_tool()
SCRIPTS = {s["id"]: s for s in TRANSCRIPTS["scripts"]}
CPS, FLOOR_MS = int(TRANSCRIPTS["speech_chars_per_s"]), int(TRANSCRIPTS["speech_floor_ms"])


def replay(sid: str, **over: Any) -> Any:
    s = SCRIPTS[sid]
    return AUD.replay(SPEC_TEXT, TRANSCRIPTS, s, dict(s["settings"], **over))


for _sid, _s in SCRIPTS.items():
    if [AUD.line_dict(x) for x in replay(_sid).lines] != _s["expected"]:
        raise SystemExit(f"e47d07kit: the replay of {_sid!r} differs from its expected lines")


def est_ms(text_: str) -> int:
    """§5.1's speech estimate, max(1.5 s, characters / 15 per second), through the tool."""
    return int(AUD.estimate(text_, CPS, FLOOR_MS))


def secs(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def field_reads(sid: str, cell: str) -> int:
    """§6.4's replay column: field reads inside the stream's minute under one setting cell."""
    s = SCRIPTS[sid]
    r = replay(sid, **AUD.CELLS[cell])
    return sum(len(x.rows.split()) for x in r.lines if x.channel == "polite" and x.t <= int(s["duration_ms"]))


def items(sid: str) -> list[Any]:
    return AUD.expand(SPEC_TEXT, SCRIPTS[sid], int(TRANSCRIPTS["seed"]))




# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_INV, TEXT_ON_ACTION, TEXT_LINK = "color.text.inverse", "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, BORDER_SEL = ("color.border.default", "color.border.subtle",
                                                   "color.border.strong", "color.border.selected")
RING = "color.focus.ring"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_STRONG, DANGER_STRONG, WARN_STRONG = ("color.status.info.strong", "color.status.danger.strong",
                                           "color.status.warning.strong")
MARK_FILL = "color.status.info.default"  # annotation markers (numbered stops, tags, callouts): not product UI
BUY, SELL, BUY_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle"
AXIS, GRID = "color.axis.text", "color.grid.line"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG, DISPLAY = ("type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg",
                                               "type.ui.display")
NUM, NUM_SM = "type.num.base", "type.num.sm"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
OPACITY_SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON: 16, ICON_SM: 12, HAIR: 1, THICK: 2, FOCUS_W: 2}

_TS: dict[str, dict[str, str]] = {}
for _s, _n, _t, _v in json.loads(TOKENS_FILE.read_text(encoding="utf-8")):
    _TS.setdefault(_s, {})[_n] = str(_v)
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations",
              "ambiguities")


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
    """A string the copy deck lacks, drawn from the spec's prose or a kit label (cite the line)."""
    NOTES.add("copy_gaps", line)


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def ambiguity(line: str) -> None:
    NOTES.add("ambiguities", line)


FALLBACKS = {
    "chrome": "kit choice: the shell chrome (TopBar, NavRail, StatusBar), the other CMP-086 entries and the other "
              "SCR-117 sections drawn as neutral placeholders; only this spec's parts are drawn",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "markers": "kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in "
               "color.status.info.default with color.text.inverse words, never product UI",
    "scrim": "fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim",
    "diagram": "kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on "
               "color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI",
    "border-control": "fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control "
                      "boundaries bind border.hairline in dark and light",
    "timeline-scale": "kit choice: a timeline's x scale is linear in milliseconds, its px per second stated on the axis "
                      "label; bars span [write, write + the §5.1 speech estimate]",
}


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


# --- node primitives (cvsheet v4.3 schema; no inst nodes)
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, a non-string o.wrap and a banned
    string; a "/" in the name becomes U+2215. Records bound tokens."""
    if t not in _KEYS:
        raise ValueError(f"node type {t!r} not allowed (no inst nodes in the per-set file)")
    name = name.replace("/", SLASH)
    if not name:
        raise ValueError(f"{t} name is empty")
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
    # cite marks are drawn plain: a backtick is markdown, never board text (the first render kept them)
    return node("text", name, chars=str(chars).replace("`", ""), typo=typo, color=color, **kw)


def icon(name: str, glyph_: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph_ not in ICONS_OK:
        raise ValueError(f"icon {glyph_!r} not in the local set {sorted(ICONS_OK)}")
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


def rect(name: str, w_: float, h: float, fill_: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill_:
        opts["fill"] = fill_
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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), HEADING_LG: (20, 1.2, False),
         DISPLAY: (24, 1.2, False), NUM: (13, 1.2, True), NUM_SM: (11, 1.2, True)}


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



# --- the illustrative world: §0's seeded synthetic stream (seed 1306, BTCUSDT), declared on every board; every
# figure on a frame comes from the transcripts' scripts through the tool's replay, never typed
SEED = int(_DATA_M.group(1))
SYMBOL = _DATA_M.group(2)
if (SEED, SYMBOL) != (int(TRANSCRIPTS["seed"]), TRANSCRIPTS["symbol"]) or _DATA_M.group(3) != TRANSCRIPTS["tick"]:
    raise SystemExit("e47d07kit: §0's data line != the transcripts' seed / symbol / tick")


def _tick(symbol: str) -> Decimal:
    def find(o: Any) -> str | None:
        if isinstance(o, dict):
            if o.get("symbol") == symbol and "priceFilter" in o:
                return str(o["priceFilter"]["tickSize"])
            vals = o.values()
        elif isinstance(o, list):
            vals = o
        else:
            return None
        for v in vals:
            r = find(v)
            if r:
                return r
        return None

    t = find(json.loads(_doc_bytes("fixture").decode("utf-8")))
    if not t:
        raise LookupError(f"{symbol}: no tickSize in {FIXTURE_REL}")
    return Decimal(t)


TICK = _tick(SYMBOL)
if TICK != Decimal(_DATA_M.group(3)):
    raise SystemExit(f"e47d07kit: §0's tick {_DATA_M.group(3)} != the fixture's {TICK}")
DATA_LINE = (f"Data: seeded synthetic stream (seed {SEED}, {SYMBOL}, tick {TICK.normalize()}), the §10 scripts; "
             f"sample data, never a market capture (§0 L{_S0}); only the tick size is the recorded fixture's")


# --- CMP-039 the ring (E47-D04 §7.1), nested stroke-only boards so every band is token-bound (the E47-D04 kit's way):
# outer halo, ring, inner halo, the offset gap, then the control. normal: 1 + 2 + 1 (+ 2 offset).
_BANDS = {"normal": ([HAIR], [FOCUS_W])}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    halo, ring_ = _BANDS[variant]
    bands = [(CANVAS, t) for t in halo] + [(RING, t) for t in ring_] + [(CANVAS, t) for t in halo]
    r_px, h_px, _o, _ln = RING_GEOM[variant]
    if sum(PX[t] for c, t in bands if c == RING) != r_px or sum(PX[t] for t in halo) != h_px:
        raise SystemExit(f"e47d07kit: the {variant} bands disagree with D04 §7.1 ({r_px} / {h_px} px)")
    return bands


def extent(variant: str, inset: bool = False) -> int:
    return (0 if inset else RING_GEOM[variant][2]) + sum(PX[t] for _c, t in ring_bands(variant))


def _layers(name: str, wd: int, ht: int, variant: str, inner: Node | None, radius: str | None) -> Node:
    bands = ring_bands(variant)
    sizes, s = [], 0
    for _c, t in bands:
        sizes.append(s)
        s += PX[t]
    node_: Node | None = None
    for i in range(len(bands) - 1, -1, -1):
        c, t = bands[i]
        kids = [node_] if node_ else ([inner] if inner else [])
        node_ = box(f"band-{i + 1} · {'ring' if c == RING else 'halo'}", kids,
                    {"stroke": c, "strokeWidth": t, "strokeAlign": "inner", **({"radius": radius} if radius else {})},
                    w=wd - 2 * sizes[i], h=ht - 2 * sizes[i],
                    x=(PX[bands[i - 1][1]] if i else 0), y=(PX[bands[i - 1][1]] if i else 0))
    assert node_ is not None
    node_ = dict(node_, name=name)
    node_.pop("x", None)
    node_.pop("y", None)
    return node_


def focus_ring(control: Node, variant: str = "normal", *, radius: str = R_CONTROL, name: str | None = None) -> Node:
    """CMP-039 around a control with explicit w and h: a (w + 2e) x (h + 2e) board, e = offset + the bands."""
    e = extent(variant)
    last = PX[ring_bands(variant)[-1][1]]
    off = RING_GEOM[variant][2]
    inner = dict(control, x=last + off, y=last + off)
    inner.pop("abs", None)
    return dict(_layers(name or f"CMP-039 ring · {variant}", int(control["w"]) + 2 * e, int(control["h"]) + 2 * e,
                        variant, inner, radius),
                note=f"focus-visible; {variant}: ring {RING_GEOM[variant][0]} px, halo {RING_GEOM[variant][1]} px each "
                     f"side, offset {off} px (D04 §7.1 L{RING_GEOM[variant][3]})")


def inset_ring(wd: int, ht: int, variant: str = "normal") -> Node:
    """CMP-039 inset (rows): the bands inside the row's box, no offset; the row's last kid at (0, 0)."""
    return dict(_layers(f"CMP-039 ring · inset {variant}", wd, ht, variant, None, None), x=0, y=0, abs=True,
                note="CMP-039 inset: drawn inside the row (E47-D04 §7.1)")


# --- annotation overlays (FALLBACKS markers)
def marker(n: int | str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    wd = 20 if len(str(n)) == 1 else 28
    return hbox(name or f"stop {n}", [text("n", str(n), LABEL, TEXT_INV)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=wd, h=20, x=x, y=y, abs=True,
                note="annotation marker (not product UI)")


def tag(label_: str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox(name or f"tag · {label_[:40]}", [text("label", label_, CAPTION, TEXT_INV)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def callout(name: str, lines: Iterable[str], x: int, y: int, wd: int = 320) -> Node:
    fallback("markers")
    ls = [ln for ln in lines if ln]
    kids = [text(f"line-{i}", s, CAPTION if i > 1 else LABEL, TEXT_1, w=wd - 2 * PX[INSET_SM])
            for i, s in enumerate(ls, 1)]
    return vbox(f"callout · {name}", kids, {"gap": STACK_XS, "pad": INSET_SM, "fill": OVERLAY, "radius": R_CONTROL,
                                            "stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
                w=wd, x=x, y=y, abs=True, note="annotation callout (not product UI)")


# --- the window: SCR-117 inside the shell at 1280 x 800 (the E47-D03 kit's SCR-116 chrome): TopBar 48 | NavRail 64 ·
# CMP-086 settings list 208 · content 1008 | StatusBar 48. Compact density: controls 24 px.
TOP_H, STATUS_H, NAV_W, SET_NAV_W = 48, 48, 64, 208
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
CONTENT_W = FRAME_W - NAV_W - SET_NAV_W  # 1008
CONTENT_PAD = 24
COL_W = CONTENT_W - 2 * CONTENT_PAD  # 960 = the 60 rem max-width (§2)
ROWS_W, TILE_W, COL_GAP = 560, 360, 24  # E47-D05's two columns (its kit): rows | tile
CONTROL_H = 24


def border_w(theme: str) -> str:
    fallback("border-control")
    return THICK if theme == "hc" else HAIR


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar(wd: int = FRAME_W) -> Node:
    left = hbox("left", [placeholder("wordmark", 88), placeholder("env badge", 56, 20),
                         placeholder("account picker", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chip", 120), placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", wd, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1, abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=wd, h=TOP_H,
                note="the shell's TopBar, not this spec's: placeholders only")


def navrail(h: int) -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32) for i in range(1, 7)]
    return vbox("NavRail (placeholder)", [*rows, rect("divider", 1, h, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=h)


def statusbar(wd: int = FRAME_W) -> Node:
    ks = [placeholder("connection chip", 120), placeholder("env word", 56)]
    return hbox("StatusBar (placeholder)", [*ks, rect("divider", wd, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=wd, h=STATUS_H)


def settings_nav(h: int, *, focused: bool = False) -> Node:
    """CMP-086 (`nav aria-label="Settings"`): placeholder entries and the PROPOSED own entry "Accessibility" (BQ-8,
    D05-A6), its selected label in color.text.link with the selected underline in color.border.selected."""
    lab = text("label", NAV_LABEL, BODY_STRONG, TEXT_LINK)
    cur = vbox(f"entry · {NAV_LABEL} (current)", [lab, rect("selected underline", 96, 2, BORDER_SEL)],
               {"gap": STACK_XS, "padX": INSET_MD, "padY": INSET_XS}, w=SET_NAV_W - 16, h=36,
               note='aria-current="page"; E47-D05\'s PROPOSED SettingsNav entry (D05-A6)')
    if focused:
        cur = focus_ring(cur)
    ents = [hbox(f"entry-{i}", [placeholder("label", 96 + 8 * (i % 3))], {"padX": INSET_MD}, w=SET_NAV_W - 16, h=28)
            for i in range(1, 5)]
    return vbox("CMP-086 SettingsNav", [*ents[:2], cur, *ents[2:],
                                       rect("divider", 1, h, BORDER_SUBTLE, x=SET_NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "pad": INSET_SM, "fill": RAISED}, w=SET_NAV_W, h=h)


def window(name: str, content: Node, *, settings: bool = True, body_h: int = BODY_H, overlays: Iterable[Node] = (),
           note: str | None = None, nav_focused: bool = False) -> Node:
    """One window: TopBar | NavRail · (SettingsNav) · main | StatusBar. body_h > BODY_H draws the full scroll length
    (FALLBACKS full-length); the main column clips at the viewport otherwise (a scrolled view)."""
    main_w = CONTENT_W if settings else FRAME_W - NAV_W
    main = box("main", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=main_w, h=body_h)
    body = hbox("body", [navrail(body_h), settings_nav(body_h, focused=nav_focused) if settings else None, main],
                {"align": "start"}, w=FRAME_W, h=body_h)
    fh = TOP_H + body_h + STATUS_H
    kids: list[Node] = [topbar(), body, statusbar()]
    kids += list(overlays)
    return vbox(name, kids, {"fill": APP, "clip": True}, w=FRAME_W, h=fh, note=note)



# --- controls (compact, 24 px; the E47-D05 kit's, without its page state)
def button(chars: str, *, theme: str = "dark", name: str | None = None, focused: bool = False,
           variant: str = "secondary", lead: Node | None = None) -> Node:
    fill_, ink = (ACTION_PRIMARY, TEXT_ON_ACTION) if variant == "primary" else (ACTION_SECONDARY, TEXT_1)
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, ink)]
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL,
                                                 "justify": "center", "fill": fill_, "stroke": BORDER_STRONG,
                                                 "strokeWidth": border_w(theme), "strokeAlign": "inner"},
             w=wd, h=CONTROL_H + 4, note=f"CMP-001 Button ({variant})")
    return focus_ring(b) if focused else b


def radio(label_: str, checked: bool, *, theme: str = "dark", t2: bool = False, focused: bool = False) -> Node:
    """CMP-006 radio: T2 = the label in color.text.tertiary, the dot in the same colour, aria-disabled."""
    edge = BORDER if t2 else BORDER_STRONG
    dot = [ellipse("dot", 8, 8, {"fill": TEXT_3 if t2 else ACTION_PRIMARY}, x=4, y=4, abs=True)] if checked else []
    circle = box("circle", [ellipse("outline", 16, 16, {"fill": CANVAS, "stroke": edge, "strokeWidth": border_w(theme),
                                                       "strokeAlign": "inner"}, x=0, y=0, abs=True), *dot], w=16, h=16)
    r = hbox(f"radio · {label_}", [circle, text("label", label_, BODY, TEXT_3 if t2 else TEXT_1)],
             {"gap": INSET_SM}, h=CONTROL_H,
             note=f'role="radio" aria-checked="{str(checked).lower()}"' + (' aria-disabled="true"' if t2 else ""))
    if focused:
        r = focus_ring(dict(r, w=round(est_width(r))))
    return r


def switch(on: bool, *, theme: str = "dark", t2: bool = False) -> Node:
    knob = ellipse("knob", 12, 12, {"fill": TEXT_ON_ACTION if on and not t2 else TEXT_3 if t2 else TEXT_2},
                   x=22 if on else 4, y=4, abs=True)
    return box("switch", [knob], {"fill": RAISED if t2 else ACTION_PRIMARY if on else HOVER, "radius": R_BADGE,
                                  "stroke": BORDER if t2 else BORDER_STRONG, "strokeWidth": border_w(theme),
                                  "strokeAlign": "inner"}, w=38, h=20,
               note=f'role="switch" aria-checked="{str(on).lower()}"' + (' aria-disabled="true"' if t2 else ""))


def lock_label(chars: str, typo: str = BODY_STRONG, *, name: str = "label") -> Node:
    """T2 (§8.2's T2 paragraph): the CMP-019 lock glyph leads the full label, both color.text.tertiary."""
    return hbox(name, [icon("lock", "locked", TEXT_3, note='CMP-019 Icon lock, decorative=false, accessible name '
                                                           '"Not available" (D09E09:207)'),
                       text("words", chars, typo, TEXT_3)], {"gap": INSET_XS},
                note="T2: lock + the full label in color.text.tertiary; never color.text.disabled, never opacity")


def field(label_: str, value: str, *, theme: str = "dark", wd: int = 120, focused: bool = False,
          caret: bool = False) -> Node:
    kids: list[Node] = [text("value", value, NUM, TEXT_1)]
    if caret:
        kids.append(rect("caret", 1, 16, TEXT_1, note="the caret, in place after the typed value"))
    inp = hbox("input", kids, {"padX": INSET_SM, "gap": STACK_XS, "justify": "end", "fill": CANVAS, "radius": R_CONTROL,
                               "stroke": BORDER_STRONG, "strokeWidth": border_w(theme), "strokeAlign": "inner"},
               w=wd, h=CONTROL_H + 4)
    if focused:
        inp = focus_ring(inp)
    return vbox(f"field · {label_}", [text("label", label_, LABEL, TEXT_1), inp], {"gap": STACK_XS})


# --- CMP-043 / CMP-044 dialog and the modal overlay (the E47-D04 kit's)
DIALOG_W = 440


def dialog(title: str, kids: Iterable[Node | None], actions: Iterable[Node], *, name: str = "CMP-043 Dialog",
           note: str = 'role="dialog" aria-modal="true"; the page behind is inert') -> Node:
    deviate(f"dialog width {DIALOG_W} px: a kit choice (no source gives the dialog's width; the E47-D05 kit's)")
    iw = DIALOG_W - 2 * PX[DIALOG_PAD]
    body = [text("title", title, HEADING_MD, TEXT_1, w=iw, note="h2: the dialog's name (aria-labelledby)"), *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "justify": "end"}, w=iw, h=CONTROL_H + 20)]
    return vbox(name, body, {"fill": OVERLAY, "radius": R_DIALOG, "pad": DIALOG_PAD, "gap": STACK_MD, "stroke": BORDER,
                             "strokeWidth": HAIR, "strokeAlign": "inner"}, w=DIALOG_W, note=note)


# a dialog's live-measured height (the drawing lane re-centred it: 173 px against the 172 estimate, so y 313, 0.5 px
# above centre, not the estimate's 314)
MEASURED_DIALOG_H: dict[str, int] = {"CMP-044 alertdialog · auto-flatten": 173}


def modal(dialog_node: Node) -> Node:
    """The overlay over a 1280 x 800 window: the flat scrim and the dialog centred."""
    fallback("scrim")
    dw, dh = est_width(dialog_node), est_height(dialog_node)
    dx, dy = round((FRAME_W - dw) / 2), round(max((FRAME_H - dh) / 2, 0))
    if dialog_node["name"] in MEASURED_DIALOG_H:
        dy = (FRAME_H - MEASURED_DIALOG_H[dialog_node["name"]]) // 2
    live(f"modal: re-centre '{dialog_node['name']}' after relayout (estimated {dw:.0f} x {dh:.0f} px)")
    scrim = rect("scrim", FRAME_W, FRAME_H, SUNKEN, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    return box("overlay", [scrim, dict(dialog_node, x=dx, y=dy)], None, w=FRAME_W, h=FRAME_H, x=0, y=0, abs=True)


def specimen(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    """A diagram frame (FALLBACKS diagram): 1280 x 800 on the canvas, children placed absolutely."""
    fallback("diagram")
    return box(frame_name(fid), kids, {"fill": CANVAS, "clip": True}, w=FRAME_W, h=FRAME_H,
               note=note or frame_state(fid))


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, as the E47-D03 kit copies it)
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


CELL_ROW = re.compile(r"/(header row|row \d+|row · [^/]*)/[^/]+$", re.DOTALL)


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children without
    text carry h; no '/' in names; table cells padded 8 px a side."""
    bad: list[str] = []
    nodes = list(nodes)

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
        if parent_flex and not n.get("abs") and n["t"] in ("board", "rect", "ellipse") and not n.get("h") \
                and not has_text(n):
            bad.append(f"{p}: flex child without text and without h")
        for k in n.get("kids") or []:
            rec(k, bool(o.get("dir")), p)

    for n in nodes:
        rec(n, False, "")
    for n in nodes:
        for p, x in walk(n):
            if x["t"] == "board" and CELL_ROW.search(p) and "padX" in (x.get("o") or {}) and x["o"]["padX"] != INSET_SM:
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




# --- the annotation column, the board, the sheet
def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title, a "Board" block (§0's Draws, theme, twin, frames, export, the data line), one
    block per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    tw = (f" (twin of board {b.twin:02d}: same frames and words; the {b.theme} token set is switched at export)"
          if b.twin else "")
    head = [f"§0 L{b.line}: {b.draws}", f"Theme: {b.theme}{tw}",
            f"Frames (hand-off §H L{H_LINE}): " + "; ".join(b.frames),
            f"Export: {b.export}", DATA_LINE,
            "Markers, tags, arrows and callouts in color.status.info.default are annotation, not product UI",
            *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int) -> list[Node]:
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        row = frames[i:i + per_row]
        x = MARGIN
        for f in row:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in row) + MARGIN
        i += per_row
    return out


# root heights measured live, the drawing lane's checked `want` (footer end 918 + MARGIN): the data line ends 2 px
# above the estimate on every board
MEASURED_H: dict[int, int] = {n: 998 for n in range(1, 11)}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int = 3) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, color.surface.app, clip) hugging its frames + the ONE annotation column
    + MARGIN; a "state: <frame id>" caption 28 px above each frame; the data line under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §H {want}")
    for f in frames:
        if (f["w"], f["h"]) != (FRAME_W, FRAME_H):
            raise ValueError(f"board {nn:02d}: frame {f['name']!r} is {f['w']} x {f['h']} (§0: {FRAME_W} x {FRAME_H})")
    if "/" in b.name[len(f"{KEY} / {nn:02d} "):]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames, per_row)
    fid = dict(zip(want, b.frames))
    caps = [text(f"caption {i:02d}", f"state: {fid[f['name']]}", CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28)
            for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data", DATA_LINE, CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    est = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    h = MEASURED_H.get(nn, est)
    if h < est - 8:
        raise ValueError(f"board {nn:02d}: measured h {h} is under the estimate {est}: re-measure")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    if nn in MEASURED_H:
        live(f"after touchTexts + relayout: the root's h {h} is the measured max(column end, footer end) + {MARGIN} "
             f"(annotation column estimated {ah:.0f} px); read it back")
    else:
        live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root "
             f"(h {h}); raise the root's h to its end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int = 3, out_dir: Path = CAP_DIR,
                name: str | None = None) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator (tokens +
    components); RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}; record the board id and the PNG size in §0")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1][:8]}, hand-off {DOCS['handoff'][0]} md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}; hand-off §H L{H_LINE}); scripts "
                         f"{DOCS['transcripts'][0]} md5 {DOCS['transcripts'][1][:8]} replayed through "
                         f"{DOCS['tool'][0]} md5 {DOCS['tool'][1][:8]}; tick size {FIXTURE_REL} md5 "
                         f"{DOCS['fixture'][1][:8]}; ring geometry E47-D04 at {PIN['E47-D04']} (§7.1 there)")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    out = out_dir / (name or b.sheet)
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rc, msg = validate(out)
    if rc != 0:
        errs = [ln for ln in msg.splitlines() if "ERROR" in ln.upper()]
        raise RuntimeError(f"{out.name}: validator exit {rc}\n" + "\n".join(errs[:20] or msg.splitlines()[-20:]))
    return out


def md_line3(nn: int) -> str:
    b = BOARDS[nn]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "") -> Path:
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}` (§H: `{f}`)" for f in b.frames]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "ambiguities", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "fallbacks",
               "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if sp.parent == CAP_DIR.resolve():  # the copy beside the kit (the committed sidecar once the kit is in a checkout)
        (KIT_DIR / p.name).write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>; the packer writes the source's absolute path into compactOf.file,
    which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged); check that, every
    packed section <= PACKED_MAX bytes, and that mkcall4.py's `count` agrees."""
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


def build(nn: int, frames: list[Node], blocks: list[tuple[str, list[str]]], *, board_lines: Iterable[str] = (),
          per_row: int = 3, notes: dict[str, Iterable[str]] | None = None) -> tuple[Path, Path, Path]:
    """The generators' one call: annotations, sheet, md, packed sheet."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann, per_row=per_row, notes=notes)
    return p, write_md(nn, p), pack_sheet(p)



# --- the diagram vocabulary shared by the boards: class tones, T-row lines, toasts, log rows, lanes
CLASS_TONE = {  # kit choice (recorded): stripe + subtle fill per class; the class word is always written beside it
    "significant-assertive": (DANGER_STRONG, "color.status.danger.subtle"),
    "status-polite": (INFO_STRONG, "color.status.info.subtle"),
    "ambient-polite": ("color.neutral.default", "color.neutral.subtle"),
    "echo-polite": (BORDER_SEL, SELECTED),
    "silent": (BORDER_SUBTLE, SUNKEN),
}


def tone_note() -> None:
    NOTES.add("fallbacks", "kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, "
                           "silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour "
                           "is never the only signal (1.4.1)")


def badge(chars: str, cls: str, *, name: str | None = None) -> Node:
    tone_note()
    stripe, _f = CLASS_TONE[cls]
    return hbox(name or f"badge · {chars}", [text("words", chars, CAPTION, TEXT_1)],
                {"padX": INSET_XS, "radius": R_BADGE, "stroke": stripe, "strokeWidth": HAIR, "strokeAlign": "inner"},
                h=16)


def measured_stack_h(stack: Node) -> int:
    """A text column's live height: each text box measures ceil(size x line-height x lines) (13 px x 1.4 draws 19 px,
    not 18.2), plus the padding and gaps. The drawing lane grew the class cards' and part chips' 'content' stacks to it
    (1-2 px) where the last line sat in the bottom padding; the card and its stripe keep the estimate (positions)."""
    o, kids = stack.get("o") or {}, [k for k in stack.get("kids") or [] if not k.get("abs")]
    boxes = []
    for kid in kids:
        if kid["t"] != "text":
            return round(est_height(stack))
        size, lh, _m = _FONT.get(kid["typo"], _FONT[BODY])
        lines = text_lines(kid["chars"], kid["typo"], kid["w"]) if kid.get("w") else 1
        boxes.append(math.ceil(round(size * lh * lines, 1)))
    return 2 * _px(o.get("padY")) + sum(boxes) + _px(o.get("gap")) * max(len(kids) - 1, 0)


def tagged_card(name: str, cls: str, kids: list[Node], wd: int, *, note: str | None = None,
                grow: bool = True) -> Node:
    """A diagram card: a 4 px class stripe on the left, then the content on the class's subtle fill. grow: the
    content stack takes measured_stack_h when that is taller (the live fold); a board whose live wraps ran shorter
    than the estimate names the stacks it grew (board 01)."""
    tone_note()
    stripe, fill_ = CLASS_TONE[cls]
    inner = vbox("content", kids, {"gap": STACK_XS, "padX": INSET_SM, "padY": INSET_XS}, w=wd - 4)
    h = round(est_height(inner))
    return hbox(name, [rect("stripe", 4, h, stripe), dict(inner, h=max(h, measured_stack_h(inner)) if grow else h)],
                {"align": "start", "fill": fill_,
                                                                       "radius": R_CONTROL, "clip": True},
                w=wd, h=h, note=note)


def trow_line(t: Tax, wd: int, *, rank: bool = True) -> Node:
    r = f" · rank {t.rank}" if rank and t.rank not in ("—", "") else ""
    return text(f"row · {t.tid}", f"{t.tid}{r} · {t.short}", CAPTION, TEXT_1, w=wd,
                note=f"§4 L{t.line}: {t.cls}; surface {t.surface}; words {t.words}")


def toast(chars: str, *, persistent: bool, glyph: str = "danger", wd: int = 360, name: str | None = None) -> Node:
    """CMP-045 Toast (`15`:531): glyph, the sentence, and, when persistent, its close button (no auto-dismiss)."""
    kids: list[Node] = [icon("glyph", glyph, DANGER_STRONG if glyph == "danger" else TEXT_2),
                        text("sentence", chars, BODY, TEXT_1, w=wd - 16 - 24 - 3 * PX[INSET_SM])]
    if persistent:
        kids.append(hbox("close", [icon("glyph", "close", TEXT_2)], {"justify": "center", "radius": R_CONTROL},
                         w=24, h=24, note='CMP-001 icon button, accessible name "Close"'))
    return hbox(name or ("CMP-045 Toast · persistent" if persistent else "CMP-045 Toast"), kids,
                {"gap": INSET_SM, "pad": INSET_SM, "align": "start", "fill": OVERLAY, "radius": R_CARD,
                 "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"}, w=wd,
                note=("persistent: stays until closed (R-8, `15`:531); " if persistent else "")
                + "appears without focus; its sentence is written into the shell pair, spoken once (R-6)")


def log_row(t_s: str, chars: str, wd: int, i: int) -> Node:
    """A CMP-060 NotificationCenter entry (`role="log"`, `15`:692)."""
    return hbox(f"row {i}", [hbox("time", [text("t", t_s, NUM_SM, TEXT_2)], {"padX": INSET_SM}, w=72, h=20),
                             hbox("entry", [text("words", chars, CAPTION, TEXT_1, w=wd - 72 - 16)], {"padX": INSET_SM},
                                  w=wd - 72)],
                {"align": "start"}, w=wd, note="CMP-060 entry: a listitem in the role=log list")


def lane_bar(name: str, x0: float, x1: float, y: int, h: int, cls: str, label_: str | None = None) -> Node:
    tone_note()
    stripe, fill_ = CLASS_TONE[cls]
    wd = max(4, round(x1 - x0))
    kids = [text("words", label_, CAPTION, TEXT_1)] if label_ and wd > 40 else []
    return hbox(name, kids, {"fill": fill_, "stroke": stripe, "strokeWidth": HAIR, "strokeAlign": "inner",
                             "radius": R_CONTROL, "padX": INSET_XS, "clip": True}, w=wd, h=h, x=round(x0), y=y)


def arrow(name: str, x: int, y: int, wd: int, *, label_: str | None = None) -> Node:
    """A horizontal annotation arrow: a 2 px line and a chevron-right head (FALLBACKS markers)."""
    fallback("markers")
    kids: list[Node] = [rect("shaft", wd - 12, 2, MARK_FILL, x=0, y=7),
                        icon("head", "chevron-right", MARK_FILL, x=wd - 16, y=0)]
    if label_:
        kids.append(text("label", label_, CAPTION, TEXT_2, x=0, y=-16))
    return box(f"arrow · {name}", kids, None, w=wd, h=16, x=x, y=y, note="annotation arrow (not product UI)")


def heading(name: str, chars: str, x: int, y: int, wd: int, *, sub: str | None = None) -> Node:
    kids = [text("title", chars, HEADING_SM, TEXT_1, w=wd)]
    if sub:
        kids.append(text("sub", sub, CAPTION, TEXT_2, w=wd))
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, x=x, y=y)


# the synthetic-data tag's x in a shell window (05, 06, 07, 09): right of the StatusBar placeholders (x 16-136 and
# 152-208), which the first render's x 16 covered (the drawing lane moved it to 224 at the same y)
SHELL_TAG_X = 224


def synthetic_tag(x: int, y: int) -> Node:
    """§0: the data is declared synthetic on each board's face; inside every frame too, as a small tag."""
    return tag(f"Synthetic data · seed {SEED} · {SYMBOL}", x, y, name="tag · synthetic data")


# --- self-test: python3 -I -B e47d07kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), "source md5 pins")
    check(len(BOARDS) == int(val("COUNT", "boards")) == 10, "§0 board count = COUNT:boards")
    check(sum(b.twin is not None for b in BOARDS.values()) == int(val("COUNT", "boards.twins")), "twin count")
    check(sum(b.twin is not None for b in BOARDS.values()) * 3 <= len(BOARDS), "twins <= a third")
    check(all(BOARDS[n].frames for n in BOARDS), "§H frames for every board")
    check(all("/" not in b.name[len(f"{KEY} / {n:02d} "):] for n, b in BOARDS.items()), "no '/' after the prefix")
    check(len(TAX) == int(val("COUNT", "taxonomy")), "§4 rows = COUNT:taxonomy")
    check(sum(t.cls == "significant-assertive" for t in TAX.values()) == int(val("COUNT", "taxonomy.assertive")),
          "assertive rows = COUNT:taxonomy.assertive")
    check(sum(t.cls == "silent" for t in TAX.values()) == int(val("COUNT", "taxonomy.silent")), "silent rows")
    check(all(t.cls in CLASSES for t in TAX.values()), "every T-row in a §3.1 class")
    check(len(ASSERTIVE_SET) == int(val("COUNT", "assertive-set")), "§3.2 entries = COUNT:assertive-set")
    check(len(COPY) == int(val("COUNT", "copy")), "§7.2 strings = COUNT:copy")
    check(len(REASONS) == int(val("COUNT", "reasons")), "§7.3 codes = COUNT:reasons")
    check(len(SLOTS) == int(val("COUNT", "slots")), "§7.1 slots = COUNT:slots")
    check(len(PANEL) == int(val("COUNT", "panel")), "§8.1 classes = COUNT:panel")
    pan_rows = sorted(r.strip() for p in PANEL for r in p["rows"].split(","))
    check(pan_rows == sorted(t for t, x in TAX.items() if x.panel not in ("—", "— (local reply)")),
          "every panelled T-row in exactly one §8.1 class")
    check(all(str(field_reads("fast", m["cell"])) == m["reads"] for m in MATRIX), "§6.4 replay column re-derived")
    check(sorted(RANKS) == [1, 2, 3, 4], "§5.1's four ranks")
    check(RING_GEOM["normal"][:3] == (2, 1, 2) and extent("normal") == 6, "D04 §7.1 normal ring read")
    toks = set(_TS.get("semantic-dark", {})) | set(_TS.get("primitives", {}))
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str)
            and re.match(r"(color|type|space|size|radius|border|opacity)\.", v)]
    used += [t for pair in CLASS_TONE.values() for t in pair]
    check(all(t in toks for t in used), f"kit tokens exist: {[t for t in used if t not in toks]}")
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    fr = specimen(BOARDS[1].frames[0], [heading("h", "self-test", 24, 24, 400), synthetic_tag(24, 760)])
    ann = annotations(1, [(BOARDS[1].frames[0], ["self-test"])])
    try:
        p = write_sheet(1, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json")
        pk = pack_sheet(p, SELFTEST_DIR)
        check(json.loads(pk.read_text())["compactOf"]["file"] == p.name, "packed source is the bare name")
        check('"t": "inst"' not in p.read_text(), "no inst")
    except Exception as e:  # noqa: BLE001 - reported as a failure
        fails.append(f"sample sheet: {e}")
    for f in fails:
        print("FAIL", f)
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
