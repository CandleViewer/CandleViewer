"""E47-D08 (#1307) board kit: the motion layer (reduced-motion variants and flash-rate safety), ten boards (22 frames;
boards 03 and 09 carry a light / high-contrast twin frame) as cvsheet JSON sheets for the per-set Penpot file
"E47-D08 boards", page "E47-D08 — Motion" (spec §0, hand-off §H).

Offline only. Spec (binding; every string, number, token and frame comes from it): docs/design/E47/E47-D08.md and
E47-D08-handoff.md as the checkout commits them, read by repo-relative path and md5-pinned in DOCS (the kit refuses
drifted bytes: re-read, re-check the cites, re-pin). The synthetic stream is TICKS (the spec's Key line:
packages/fixtures/src/synthetic-ticks.mjs), read the same way: its `burst` preset and its defaults drive every figure
(mulberry32 ported below; the self-test checks the port against the generator's own arithmetic). E47-D04's ring
geometry and E47-D05's SCR-117 strings are read with `git show <pin>:<path>` at the pins the spec's "Inputs pinned"
line names.
Registry (parsed, never typed): §0's board table (BOARDS), the hand-off's §H frame plan (FRAMES), §3's inventory
(INV), §4.1's constants (FR), §4.4's simulation figures (SIM anchors, re-derived by simulate()), §8's pause table
(PAUSE), §10's matrix (MATRIX), §11's safety table (SAFETY), §15's copy deck (COPY), the COUNT anchors.

Checkout: the kit sits at docs/design/_tools/sheets/e47-d08/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md, Build).
Pipeline (one generator per board, gen/gen_NN.py):
    frames = [...]; blocks = [(frame id, lines), ...]
    build(nn, frames, blocks) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e47d08kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host or
agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E47-D08", "E47", 1307
KIT_DIR = Path(__file__).resolve().parent


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / "docs" / "design" / EPIC).is_dir() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / "docs" / "design" / EPIC).is_dir():
        raise SystemExit("e47d08kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
TICKS_REL = "packages/fixtures/src/synthetic-ticks.mjs"
_PATHS = {  # alias -> repo-relative path
    "spec": "docs/design/E47/E47-D08.md",
    "handoff": "docs/design/E47/E47-D08-handoff.md",
    "ticks": TICKS_REL,
}
_MD5 = (  # md5 as read, one per _PATHS entry in its order
    "a935d0983d53103c8fbea271e35ce875",
    "e4e1def0d82c59b1ebf569f80c8e8785",
    "64c3ede90417111e7bac5f2091e3fee5",
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
    raise SystemExit(f"e47d08kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _doc_bytes("spec").decode("utf-8").split("\n")
HANDOFF_LINES = _doc_bytes("handoff").decode("utf-8").split("\n")
TICKS_SRC = _doc_bytes("ticks").decode("utf-8")
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
                raise SystemExit(f"e47d08kit: anchor {k} carries two values ({vals[k]} / {v})")
            vals[k] = v
    return vals


VAL = _parse_values()


def val(kind: str, key: str) -> str:
    """A figure from the spec's tool output (KeyError when the spec has none: never invent one)."""
    return VAL[f"{kind}:{key}"]


# --- §0: the boards; the hand-off's §H: their frames
_S0 = L("Penpot: the file `E47-D08 boards`")
_PAGE_M = re.search(r"Penpot: the file `([^`]+)`, page `([^`]+)`", SPEC_LINES[_S0 - 1])
if not _PAGE_M:
    raise SystemExit("e47d08kit: §0 names no Penpot file and page")
FILE_NAME, PAGE = _PAGE_M.group(1), _PAGE_M.group(2)
_EXPORT_PAT = re.search(r"Exports go to `([^`]+)`", SPEC_LINES[_S0 - 1]).group(1)  # .../E47-D08-NN-<slug>.png
_WINDOW_M = re.search(r"Every frame is a (\d+) × (\d+) window at (\w+) density", SPEC_LINES[_S0 - 1])
if not _WINDOW_M or (int(_WINDOW_M.group(1)), int(_WINDOW_M.group(2))) != (FRAME_W, FRAME_H):
    raise SystemExit("e47d08kit: §0's window size is not 1280 x 800")
DENSITY = _WINDOW_M.group(3)
NOT_DRAWN_LINE = L("**Not drawn (the text is binding)**")
TWIN_LINE = L("Board 03 carries its light twin as a second frame")
THEMES = ("dark", "light", "hc")
THEME_WORD = {"dark": "dark", "light": "light", "hc": "high contrast"}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str
    slug: str
    draws: str
    themes: tuple[str, ...]  # ("dark",) or ("dark", "light") / ("dark", "hc"): §0's Theme cell
    line: int
    frames: tuple[str, ...]  # the §H frame ids, "/" as written

    @property
    def theme(self) -> str:
        return self.themes[0]

    @property
    def twin(self) -> str | None:
        return self.themes[1] if len(self.themes) > 1 else None

    @property
    def export(self) -> str:
        return _EXPORT_PAT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def twin_export(self) -> str | None:
        """The twin frame's evidence: the same board exported again under the twin's token set (ambiguity A-1)."""
        return self.export.replace(".png", f"-{THEME_WORD[self.twin].replace(' ', '-')}.png") if self.twin else None

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


H_LINE = HL("## §H The board plan")


def _parse_frames() -> dict[int, tuple[str, ...]]:
    return {int(c[0]): tuple(re.findall(r"`([^`]+)`", c[1])) for _ln, c in table_after("## §H The board plan",
                                                                                       HANDOFF_LINES)}


FRAMES = _parse_frames()


def frame_theme(fid: str) -> str:
    m = re.search(r" · (dark|light|hc)$", fid)
    if not m:
        raise SystemExit(f"e47d08kit: §H frame {fid!r} names no theme")
    return m.group(1)


def _parse_boards() -> dict[int, Board]:
    out = {}
    for ln, c in table_after("## 0. Status, artefacts and the boards"):
        m = re.fullmatch(rf"`({KEY} / (\d{{2}}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise SystemExit(f"e47d08kit: §0 row L{ln} unreadable")
        nn = int(m.group(2))
        themes = tuple(t.strip() for t in c[3].split("+"))
        if themes[0] != "dark" or any(t not in THEMES for t in themes):
            raise SystemExit(f"e47d08kit: §0 board {nn:02d} theme cell {c[3]!r}")
        if {frame_theme(f) for f in FRAMES[nn]} != set(themes):
            raise SystemExit(f"e47d08kit: §0 board {nn:02d} themes {themes} != §H frame themes")
        out[nn] = Board(nn, m.group(1), m.group(3), plain(c[2]), themes, ln, FRAMES[nn])
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The §H frame id as a node name: the spec's "/" drawn as U+2215 (cvsheet's path separator is "/")."""
    return fid.replace("/", SLASH)


# --- the pins the spec's "Inputs pinned" line names: E47-D04 (ring geometry), E47-D05 (SCR-117's strings)
_PINS_LINE = SPEC_LINES[L("**Inputs pinned.**") - 1]
D04_SHA = re.search(r"D04 at `([0-9a-f]{7,40})`", _PINS_LINE).group(1)
D05_SHA = re.search(r"D05 at `([0-9a-f]{7,40})`", _PINS_LINE).group(1)


def _git_show(sha: str, rel: str) -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, text=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d08kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout.split("\n")


BASE_SHA = re.search(r"Base `origin/main` `([0-9a-f]{7,40})`", _PINS_LINE).group(1)
D04_LINES = _git_show(D04_SHA, "docs/design/E47/E47-D04.md")
D05_LINES = _git_show(D05_SHA, "docs/design/E47/E47-D05.md")


def D5L(needle: str) -> int:
    return find_line(needle, D05_LINES)


def _ring_geometry() -> dict[str, tuple[int, int, int, int]]:
    """variant -> (ring px, halo px, offset px, D04 line) from D04 §7.1's table."""
    out = {}
    for ln, c in table_after("### 7.1 Geometry", D04_LINES):
        v = c[0].split(" ")[0]
        px = [int(m) for m in re.findall(r"(\d+) px", " ".join(c[1:4]))]
        if v == "inset":
            continue
        if len(px) != 3:
            raise SystemExit(f"e47d08kit: D04 §7.1 {v} row unreadable")
        out[v] = (px[0], px[1], px[2], ln)
    return out


RING_GEOM = _ring_geometry()  # {"normal": (2, 1, 2, 235), "thick": (3, 2, 2, 237)}


def _d05_copy() -> dict[str, tuple[str, int]]:
    return {c[0]: (re.findall(r'"([^"]+)"', plain(c[1]))[0], ln) for ln, c in table_after("## 15. Copy deck", D05_LINES)
            if re.findall(r'"([^"]+)"', plain(c[1]))}


D05_COPY = _d05_copy()  # "W-3" -> ("Reduced motion", line)
_D05_TPL_LN = D5L("**Effective line** under it")
D05_EFFECTIVE_TEMPLATE = re.search(r'the template "([^"]+)"', D05_LINES[_D05_TPL_LN - 1]).group(1)
D05_TRI = re.findall(r'"([^"]+)"', re.search(r'RadioGroup ("[^)]+?") \(', D05_LINES[_D05_TPL_LN - 1]).group(1))
D05_ROWS = {plain(c[0]): (plain(c[1]), plain(c[2]), ln) for ln, c in table_after("## 4. Option rows", D05_LINES)
            if c and c[0].startswith("`")}


# --- §15 copy deck
@dataclass(frozen=True)
class Copy:
    key: str
    s: str
    source: str
    status: str
    line: int


COPY = {c[0]: Copy(c[0], plain(c[1]), plain(c[2]), plain(c[3]), ln) for ln, c in table_after("## 15. Copy deck")}


def w(key: str) -> str:
    """The quoted string of a W-n row exactly as §15 gives it (NOTES records the key)."""
    c = COPY[key]
    s = re.findall(r'"([^"]+)"', c.s)[0]
    NOTES.add("copy_keys", f"{key} (§15 L{c.line}, {c.status}): {s}")
    return s


def fill_slot(s: str, slot: str, value: str) -> str:
    if slot not in s:
        raise ValueError(f"{slot!r} not in {s!r}")
    return s.replace(slot, value, 1)


def d05_effective(on: bool, source: str) -> str:
    """A fill of D05 §5.1's template (D05 at its pin), each value one of its slot's alternatives."""
    alts = re.findall(r"\{([^{}]+)\}", D05_EFFECTIVE_TEMPLATE)
    if "On" not in alts[0].split("|") or source not in alts[1].split("|"):
        raise ValueError(f"{source!r} is not a source of {D05_EFFECTIVE_TEMPLATE!r}")
    out = D05_EFFECTIVE_TEMPLATE.replace("{" + alts[0] + "}", "On" if on else "Off", 1)
    return out.replace("{" + alts[1] + "}", source, 1)


# --- §3 the inventory, §4.1 the constants, §8 pauses, §10 the matrix, §11 safety
@dataclass(frozen=True)
class Inv:
    i: str
    surface: str
    trigger: str
    layer: str
    klass: str
    full: str
    calm: str
    reduced: str
    owner: str
    line: int

    @property
    def n(self) -> int:
        return int(self.i.split("-")[1])

    def tier(self, t: str) -> str:
        return {"full": self.full, "canvas-calm": self.calm, "reduced": self.reduced}[t]


INV = sorted((Inv(*[plain(x) for x in c[:9]], ln) for ln, c in table_after("## 3. The motion inventory")),
             key=lambda r: r.n)
INV_LINE = L("## 3. The motion inventory")
TIERS = ("full", "canvas-calm", "reduced")  # §H's frame words; §2's tiers "full", "canvas calm", "reduced"
TIER_TABLE = {plain(c[0]): dict(set_by=plain(c[1]), motion=plain(c[2]), flags=plain(c[3]), dom=plain(c[4]),
                                flash=plain(c[5]), line=ln) for ln, c in table_after("## 2. The three effective tiers")}
FR = {c[0]: dict(name=plain(c[1]), value=plain(c[2]), source=plain(c[3]), status=plain(c[4]), line=ln)
      for ln, c in table_after("### 4.1 The constants")}
PER_SURFACE = {plain(c[0]): dict(carrier=plain(c[1]), budget=plain(c[2]), rule=plain(c[3]), reduce=plain(c[4]),
                                 qa=plain(c[5]), line=ln) for ln, c in table_after("### 4.2 Per surface")}
SIM_ROWS = [(plain(c[0]), plain(c[1]), plain(c[2]), ln) for ln, c in table_after("### 4.4 The 40 Hz simulation")]
PAUSE = [dict(mover=plain(c[0]), control=plain(c[1]), announced=plain(c[2]), feed=plain(c[3]), line=ln)
         for ln, c in table_after("## 8. Pause, stop, hide")]
MATRIX_HEAD = _cells(SPEC_LINES[L("| Class                          | safe") - 1])
MATRIX = {plain(c[0]): ([plain(x) for x in c[1:5]], ln) for ln, c in table_after("## 10. Forced colours")}
SAFETY = [dict(signal=plain(c[0]), component=plain(c[1]), carrier=plain(c[2]), reduce=plain(c[3]),
               flashes=plain(c[4]), line=ln) for ln, c in table_after("## 11. Safety signals stay static")]
T2_LINE = L("**The T2 paragraph (G-T2;")
T2_VERB = re.search(r'so the leg reads "([^"]+)"', SPEC_LINES[T2_LINE - 1]).group(1)


def fr_ms(fr: str) -> int:
    """FR-1 '500 ms' -> 500; FR-5 '1 per 1 000 ms' -> 1000; FR-6 '2 per 1 000 ms' -> 500 (the interval it implies)."""
    v = FR[fr]["value"]
    m = re.fullmatch(r"(\d+) per ([\d ]+) ms", v)
    if m:
        return int(m.group(2).replace(" ", "")) // int(m.group(1))
    m = re.fullmatch(r"([\d ]+) ms", v)
    if not m:
        raise ValueError(f"{fr} {v!r} is not a duration")
    return int(m.group(1).replace(" ", ""))


def fr_int(fr: str) -> int:
    return int(re.match(r"\d+", FR[fr]["value"]).group(0))


REGION_W, REGION_H = (int(x) for x in re.fullmatch(r"(\d+) × (\d+)", FR["FR-2"]["value"]).groups())
WINDOW_MS = int(re.search(r"half-open ([\d ]+) ms window", FR["FR-3"]["name"]).group(1).replace(" ", ""))
HEAT_MS = int(re.search(r"each (\d+) ms column", next(r for r in INV if r.i == "I-20").trigger).group(1))


# --- TICKS: the synthetic stream (seeded; declared synthetic on every board)
def _ticks_obj(name: str) -> dict[str, float]:
    m = re.search(name + r" = Object\.freeze\(\{(.*?)\}\);", TICKS_SRC, re.DOTALL)
    if not m:
        raise SystemExit(f"e47d08kit: TICKS has no {name}")
    return {k_: float(v.replace("_", "")) for k_, v in re.findall(r"(\w+): ([\d_.]+)", m.group(1))}


TICK_DEFAULTS = _ticks_obj("SYNTHETIC_TICK_DEFAULTS")
_BURST_M = re.search(r"burst: Object\.freeze\(\{ rateHz: (\d+), durationMs: (\d+) \}\)", TICKS_SRC)
BURST_HZ, BURST_MS = int(_BURST_M.group(1)), int(_BURST_M.group(2))


def mulberry32(seed: int):
    """The generator's mulberry32 (TICKS), in unsigned 32-bit arithmetic (JS's int32 ops keep the same low bits)."""
    a = seed & 0xFFFFFFFF

    def nxt() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return nxt


@dataclass(frozen=True)
class Tick:
    i: int
    t_ms: int
    price_ticks: int
    move: str

    @property
    def price(self) -> str:
        d = int(TICK_DEFAULTS["tickDecimals"])
        return f"{self.price_ticks // 10 ** d}.{self.price_ticks % 10 ** d:0{d}d}"


def generate_ticks(rate_hz: int = BURST_HZ, duration_ms: int = BURST_MS, seed: int | None = None) -> list[Tick]:
    """TICKS generateTicks with the `burst` preset (the defaults' seed and start price)."""
    rand = mulberry32(int(TICK_DEFAULTS["seed"] if seed is None else seed))
    count = (duration_ms * rate_hz) // 1000
    p = int(TICK_DEFAULTS["startPriceTicks"])
    out = []
    for i in range(count):
        r = rand()
        move = "up" if r < 0.4 else "down" if r < 0.8 else "flat"
        p += 1 if move == "up" else -1 if move == "down" else 0
        out.append(Tick(i, int(TICK_DEFAULTS["startMs"]) + math.floor(i * 1000 / rate_hz + 0.5), p, move))
    return out


BURST = generate_ticks()
SEED = int(TICK_DEFAULTS["seed"])
DATA_LINE = (f"Data: synthetic, never a venue payload: the TICKS `burst` preset (seed {SEED}, {BURST_HZ} Hz, "
             f"{len(BURST)} ticks from a start of {Tick(0, 0, int(TICK_DEFAULTS['startPriceTicks']), 'flat').price}); sample "
             "data only")


# --- §4.4 re-derived: the burst through §4's rules (the spec tool's simulate(), on the same inputs)
def max_window(starts: Iterable[int], window: int = WINDOW_MS) -> int:
    """The most starts in any half-open window [s, s + window)."""
    xs = sorted(starts)
    return max((sum(1 for x in xs[i:] if x < s + window) for i, s in enumerate(xs)), default=0)


SOURCES = ("liq", "price", "heat")  # FR-9's rank: liquidation, then the focused symbol, then the rest
SOURCE_I = {"liq": "I-24", "price": "I-5", "heat": "I-21", "bubble": "I-22"}


@dataclass
class Sim:
    requests: dict[str, list[int]]
    solo: dict[str, list[int]]
    admitted: dict[str, list[int]]
    refused: dict[str, list[int]] = field(default_factory=dict)

    def figures(self) -> dict[str, int]:
        allsolo = [t for s in SOURCES for t in self.solo[s]]
        return {"ticks": len(BURST), "price": max_window(self.solo["price"]), "liq": max_window(self.solo["liq"]),
                "heat": max_window(self.solo["heat"]), "bubble": 0, "naive": max_window(allsolo),
                "combined": max_window([t for s in SOURCES for t in self.admitted[s]]),
                "frames": fr_ms("FR-1") * 60 // 1000}


def simulate(requests: dict[str, list[int]] | None = None, interval: dict[str, int] | None = None,
             rank: tuple[str, ...] = SOURCES) -> Sim:
    """Each source alone (its own interval: FR-5, FR-1, FR-6), then the region arbiter (FR-3 starts per half-open
    window, ranked by FR-9; a refused request is dropped, never queued)."""
    ticks = [t.t_ms for t in BURST]
    req = requests or {"liq": ticks, "price": ticks, "heat": list(range(0, BURST_MS, HEAT_MS))}
    iv = interval or {"liq": fr_ms("FR-5"), "price": fr_ms("FR-1"), "heat": fr_ms("FR-6")}
    cap = fr_int("FR-3")

    def alone(src: str) -> list[int]:
        out: list[int] = []
        for t in req[src]:
            if not out or t - out[-1] >= iv[src]:
                out.append(t)
        return out

    solo = {s: alone(s) for s in rank}
    last: dict[str, int | None] = {s: None for s in rank}
    adm: dict[str, list[int]] = {s: [] for s in rank}
    ref: dict[str, list[int]] = {s: [] for s in rank}
    for t in sorted(set().union(*[set(req[s]) for s in rank])):
        for s in rank:
            if t not in req[s]:
                continue
            prev = last[s]
            if prev is not None and t - prev < iv[s]:
                continue  # held by the source's own interval (not a region refusal)
            if sum(1 for x in [y for z in adm.values() for y in z] if x > t - WINDOW_MS) >= cap:
                ref[s].append(t)
                continue
            adm[s].append(t)
            last[s] = t
    return Sim(req, solo, adm, ref)


SIM = simulate()


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
C_UP, C_DOWN, C_WICK, AXIS, GRID = ("color.candle.up", "color.candle.down", "color.candle.wick", "color.axis.text",
                                    "color.grid.line")
HM = {i: f"color.heatmap.bid.{i}" for i in range(1, 6)}
HM_ZERO = "color.heatmap.zero"
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


ENV_LIVE, ENV_DEMO = "color.env.live", "color.env.demo"
WARN_SUBTLE, DANGER_SUBTLE, DANGER_DEF, WARN_DEF = ("color.status.warning.subtle", "color.status.danger.subtle",
                                                    "color.status.danger.default", "color.status.warning.default")
INFO_SUBTLE, SUCCESS_STRONG = "color.status.info.subtle", "color.status.success.strong"
SELL_SUBTLE, BUY_HC, SELL_HC = "color.sell.subtle", "color.buy.hc", "color.sell.hc"
HM_ASK = {i: f"color.heatmap.ask.{i}" for i in range(1, 6)}
CROSSHAIR, DRAWING_SEL = "color.crosshair", "color.drawing.selected"
OPACITY_MUTED = "opacity.muted"
R_PILL = "radius.pill"  # a primitive (validator WARN), as CMP-229's tokens name it (`15`)
NUM_XS, NUM_MD = "type.num.xs", "type.num.md"
PX[R_PILL] = 0

FALLBACKS = {
    "chrome": "kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are "
              "neutral placeholders; only the surfaces a board draws are drawn",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "markers": "kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in "
               "color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI",
    "flash-peak": "fallback: the value-flash overlay's peak (opacity 0.25 of color.buy.default / color.sell.default, "
                  "§3 I-5) has no opacity token: drawn as color.buy.subtle / color.sell.subtle over the cell, its "
                  "mid-decay as the same tint at opacity.muted, labelled with the spec's values",
    "liq-overlay": "fallback: the liquidation overlay (§6; PROPOSED color.liquidation.flash, D08-A9, not a token) drawn "
                   "as color.status.warning.subtle under a color.status.warning.strong 2 px outline, labelled PROPOSED",
    "forced": "fallback: system colours (CanvasText, Canvas, Highlight, ButtonBorder) are not tokens: under forced "
              "colours they are drawn token-bound as color.text.primary / color.surface.app / color.focus.ring / "
              "color.border.strong with the system colour's name written beside them",
    "glyph": "fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the "
             "liquidation glyph as the local warning icon",
    "env-glyph": "fallback: the environment glyph (CMP-074 / CMP-075) drawn as a filled ellipse in color.env.live "
                 "inside a ring (no env icon in the local set)",
    "thick": "fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent "
             "strokes in color.focus.ring, border.focus (2) + border.hairline (1); its 2 px halos as border.thick",
    "pill": "radius.pill is a Tier-1 primitive (validator WARN), the radius CMP-229's token list names (`15`)",
    "trail": "fallback: the heatmap trail's age-based fade (no hi-fi spec, D08-G1) drawn as stepped ramp tokens "
             "color.heatmap.bid.1-5, one step dimmer per older column; the instant mode maps true size to the step",
    "time-axis": "kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI",
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
    """A text box's live height: Penpot measures ceil(size x line-height x lines) (13 px x 1.4 is 19 px, not 18.2;
    11 px x 1.2 is 14, not 13.2), so every stack that hugs its texts is sized to that line box."""
    size, lh, _m = _FONT.get(typo, _FONT[BODY])
    return float(math.ceil(round(size * lh * lines, 1)))


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



# --- CMP-039 the ring (E47-D04 §7.1), nested stroke-only boards so every band is token-bound (the E47-D04 kit's way):
# outer halo, ring, inner halo, the offset gap, then the control. normal: 1 + 2 + 1 (+ 2 offset); thick: 2 + 3 + 2.
_BANDS = {"normal": ([HAIR], [FOCUS_W]), "thick": ([THICK], [FOCUS_W, HAIR])}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    halo, ring_ = _BANDS[variant]
    if variant == "thick":
        fallback("thick")
    bands = [(CANVAS, t) for t in halo] + [(RING, t) for t in ring_] + [(CANVAS, t) for t in halo]
    r_px, h_px, _o, _ln = RING_GEOM[variant]
    if sum(PX[t] for c, t in bands if c == RING) != r_px or sum(PX[t] for t in halo) != h_px:
        raise SystemExit(f"e47d05kit: the {variant} bands disagree with D04 §7.1 ({r_px} / {h_px} px)")
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




# --- tables (the E47-D04 kit's CMP-049 cells: 8 px a side, so adjacent cell texts sit >= 16 px apart)
ROW_H = 24  # compact density (§0): size.row.compact


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    numeric: bool = False


def cell(name: str, content: str | Node | list[Node] | None, w_: int, *, numeric: bool = False, h: int = ROW_H,
         typo: str | None = None, color: str = TEXT_1, fill_: str | None = None) -> Node:
    inner = w_ - 2 * PX[INSET_SM]
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        ty = typo or (NUM if numeric else BODY)
        kids = [text("value", content, ty, color, **({"w": inner} if text_w(content, ty) > inner else {}))]
    elif isinstance(content, list):
        kids = content
    else:
        kids = [content]
    o: dict[str, Any] = {"padX": INSET_SM, "justify": "end" if numeric else "start", "gap": INSET_XS}
    if fill_:
        o["fill"] = fill_
    return hbox(name, kids, o, w=w_, h=h)


def header_row(cols: Iterable[Col], *, fill_: str = CANVAS) -> Node:
    cs = list(cols)
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=CAPTION, color=TEXT_2)
                               for c in cs], {"fill": fill_}, w=sum(c.w for c in cs), h=ROW_H,
                note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, i: int, *,
              h: int | None = None, colors: dict[str, str] | None = None, fills: dict[str, str] | None = None,
              fill_: str | None = None, note: str | None = None) -> Node:
    """One body row: zebra (odd color.surface.canvas, even color.surface.raised); h=None: the tallest cell + 4 px a
    side, at least ROW_H."""
    cs = list(cols)
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    mk = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, color=(colors or {}).get(c.key, TEXT_1),
               fill_=(fills or {}).get(c.key)) for c in cs]
    if h is None:
        need = max((est_height(dict(k, h=None)) for k in mk), default=0.0) + 2 * PX[INSET_XS]
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    kids = [dict(k, h=h) for k in mk]
    for k in kids:
        if est_height(dict(k, h=None)) > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs more than row h {h}")
    return hbox(name, kids, {"fill": fill_ or (CANVAS if i % 2 else RAISED)}, w=sum(c.w for c in cs), h=h, note=note)


def table(name: str, caption_: str | None, header: Node, rows: list[Node], *, note: str | None = None) -> Node:
    wd = header["w"]
    kids = [text("caption", caption_, CAPTION, TEXT_2, w=wd) if caption_ else None, header,
            rect("header rule", wd, 1, BORDER),
            vbox("rows", rows, None, w=wd, h=round(sum(est_height(r) for r in rows))) if rows else None]
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, note=note)


# --- the window at 1280 x 800, compact: TopBar 48 | NavRail 56 · main 1224 | StatusBar 24 (the E47-D04 kit's shell)
TOP_H, STATUS_H, NAV_W = 48, 24, 56
MAIN_W, BODY_H = FRAME_W - NAV_W, FRAME_H - TOP_H - STATUS_H  # 1224, 728
HEADER_H = 28
CONTROL_H = 24


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def env_glyph(env: str = "live") -> Node:
    fallback("env-glyph")
    col = ENV_LIVE if env == "live" else ENV_DEMO
    return box("env glyph", [ellipse("ring", 12, 12, {"stroke": col, "strokeWidth": THICK, "strokeAlign": "inner"},
                                     x=0, y=0),
                             ellipse("dot", 6, 6, {"fill": col}, x=3, y=3)], w=12, h=12)


def env_badge(env: str = "live", theme: str = "dark") -> Node:
    """CMP-075 as built (`15`:842 ff.): word + glyph + weight + a 2 px env border; role="img"."""
    col = ENV_LIVE if env == "live" else ENV_DEMO
    word = env.upper()
    return hbox(f"CMP-075 EnvBadgeLocal · {word}", [env_glyph(env), text("word", word, LABEL, TEXT_1)],
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_BADGE, "stroke": col, "strokeWidth": THICK,
                 "strokeAlign": "inner"}, h=22,
                note=f'role="img" named "Trading environment: {env.capitalize()}"; static in every tier (I-25, §11)')


def topbar(*, badge: Node | None = None, right: Iterable[Node] = ()) -> Node:
    left = hbox("left", [placeholder("wordmark", 88), badge or placeholder("env badge", 56, 20),
                         placeholder("account picker", 136)], {"gap": INSET_MD}, h=TOP_H)
    rgt = hbox("right", [*right, placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar", [left, rgt, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1, abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note="the shell's TopBar (E10): placeholders except the parts this board draws")


def navrail() -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=40, h=32) for i in range(1, 7)]
    return vbox("NavRail", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H)


def statusbar(kids: Iterable[Node] = ()) -> Node:
    ks = list(kids) or [placeholder("connection chip", 120), placeholder("env word", 56)]
    return hbox("StatusBar", [*ks, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=FRAME_W, h=STATUS_H)


def window(fid: str, content: Node, *, top: Node | None = None, status: Node | None = None,
           overlays: Iterable[Node] = (), note: str | None = None) -> Node:
    """One 1280 x 800 window: TopBar | NavRail · main (1224 x 728, content at its origin) | StatusBar."""
    main = box("main", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=MAIN_W, h=BODY_H)
    body = hbox("body", [navrail(), main], {"align": "start"}, w=FRAME_W, h=BODY_H)
    kids: list[Node] = [top or topbar(), body, status or statusbar(), *overlays]
    return vbox(frame_name(fid), kids, {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H, note=note)


def specimen(fid: str, kids: list[Node], *, note: str | None = None, gap: str = STACK_MD) -> Node:
    """A 1280 x 800 specimen frame (a map or a matrix, not a screen): canvas fill, 24 px padding, column flow."""
    return vbox(frame_name(fid), kids, {"fill": CANVAS, "clip": True, "pad": INSET_XL, "gap": gap},
                w=FRAME_W, h=FRAME_H, note=note)


def panel(name: str, title: str, body: Node, w_: int, h: int, *, tools: Iterable[Node] = (),
          note: str | None = None) -> Node:
    """A dock panel (CMP-080): a 28 px header (the h2 title, then its tools) over the body; hairline border."""
    head = hbox("header", [text("h2", title, BODY_STRONG, TEXT_1), hbox("tools", list(tools) or
                                                                         [placeholder("tool", 16, 16)],
                                                                         {"gap": INSET_SM}, h=HEADER_H)],
                {"padX": INSET_SM, "justify": "space-between", "fill": RAISED}, w=w_, h=HEADER_H)
    return vbox(name, [head, dict(body, w=w_, h=h - HEADER_H)], {"fill": CANVAS, "stroke": BORDER_SUBTLE,
                                                                 "strokeWidth": HAIR, "strokeAlign": "inner",
                                                                 "clip": True}, w=w_, h=h, note=note)


def button(chars: str, *, name: str | None = None, lead: Node | None = None, pressed: bool | None = None,
           focused: str | None = None, primary: bool = False, note: str | None = None) -> Node:
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, TEXT_ON_ACTION if primary else TEXT_1)]
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    fill_ = ACTION_PRIMARY if primary else (SELECTED if pressed else ACTION_SECONDARY)
    b = hbox(name or f"button · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL,
                                                 "justify": "center", "fill": fill_, "stroke": BORDER_STRONG,
                                                 "strokeWidth": HAIR, "strokeAlign": "inner"},
             w=wd, h=CONTROL_H, note=note or ("CMP-001 Button" + (f'; aria-pressed="{str(pressed).lower()}"'
                                                                   if pressed is not None else "")))
    return focus_ring(b, focused) if focused else b


def chip(chars: str, *, fill_: str = RAISED, color: str = TEXT_1, lead: Node | None = None, name: str | None = None,
         stroke: str | None = None, note: str | None = None) -> Node:
    o: dict[str, Any] = {"gap": INSET_XS, "padX": INSET_SM, "radius": R_BADGE, "fill": fill_}
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIR, strokeAlign="inner")
    return hbox(name or f"chip · {chars[:32]}", ([lead] if lead else []) + [text("label", chars, LABEL, color)], o,
                h=20, note=note)


def glyph(up: bool, color: str | None = None, typo: str = NUM) -> Node:
    fallback("glyph")
    return text("glyph " + ("up" if up else "down"), "▲" if up else "▼", typo, color or (BUY if up else SELL))


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
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(VALIDATOR), str(path), "--components",
                          str(COMPONENTS), "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120,
                         check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, "\n".join(lines)



# --- the annotation column, the board, the sheet
def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title, a "Board" block (§0's Draws, theme, frames, export, the data line), one block
    per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    tw = (f"; its {THEME_WORD[b.twin]} twin is a second frame (§0 L{TWIN_LINE}), token-bound: the board is exported "
          f"again under the {THEME_WORD[b.twin]} set to {b.twin_export}" if b.twin else "")
    head = [f"§0 L{b.line}: {b.draws}", f"Theme: {b.theme}{tw}",
            f"Frames (hand-off §H L{H_LINE}): " + "; ".join(b.frames),
            f"Export: {b.export}", f"Every frame a {FRAME_W} × {FRAME_H} window, {DENSITY} density (§0 L{_S0})",
            DATA_LINE, "Markers, tags, shading, outlines and callouts in color.status.info.default are annotation, "
                       "not product UI", *board_lines]
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
            raise ValueError(f"board {nn:02d}: frame {f['name']!r} is {f['w']} x {f['h']} (§0: 1280 x 800 windows)")
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
    # the root hugs max(footer end, annotation end) + MARGIN: the live check read back footer end 918 + 80 = 998 on
    # all ten boards (the first sheets rounded an estimate up to 1000)
    h = int(max(bottom + 24 + text_h(CAPTION), MARGIN + math.ceil(ah)) + MARGIN)
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the root's h {h} is max(footer end, annotation column end) + {MARGIN} "
         f"(annotation column estimated {ah:.0f} px); read it back and raise it to the measured end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int = 3, out_dir: Path = CAP_DIR, name: str | None = None) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator (tokens +
    components); RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row)
    live(f"export {b.export} under the dark set; record the board id and the PNG size in §0")
    if b.twin:
        tf = frame_name(b.frames[-1])
        live(f"twin: activate the {THEME_WORD[b.twin]} token set, read back one bound fill (color.surface.canvas) as "
             f"its {THEME_WORD[b.twin]} value, export the board again to {b.twin_export} (frame '{tf}' is the "
             f"evidence there, the dark frame in the first export), then restore the dark set")
        ambiguity(f"A-1: §0 L{b.line} plans a dark and a {THEME_WORD[b.twin]} frame on one board while the token set "
                  f"is file-wide: read as one token-bound board exported twice (dark, then {THEME_WORD[b.twin]} to "
                  f"{b.twin_export}); the export name adds the theme word to §0 L{_S0}'s NN-<slug> pattern")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1][:8]}, hand-off {DOCS['handoff'][0]} md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}; hand-off §H L{H_LINE}); TICKS {TICKS_REL} md5 "
                         f"{DOCS['ticks'][1][:8]}; ring geometry E47-D04 at {D04_SHA} (§7.1); SCR-117 strings E47-D05 "
                         f"at {D05_SHA}")
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


def write_md(nn: int, sheet_path: Path) -> Path:
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    twin = (f" Twin export: theme {b.twin}; export `{b.twin_export}` (the same sheet; frame "
            f"`{frame_name(b.frames[-1])}` is the evidence)." if b.twin else "")
    out = [f"# {b.name}", "", md_line3(nn), "",
           f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
           f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".{twin}",
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
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(PACKER), str(src), str(dst)], capture_output=True,
                         text=True, timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(MKCALL), str(dst), "count"],
                         capture_output=True, text=True, timeout=120, check=False)
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



# --- self-test: python3 -I -B e47d08kit.py selftest
TICKS_GOLDEN = (200, 1300001150, "65000.22")  # the generator's own output for `burst` (count, sum of priceTicks, last)


def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), "source md5 pins")
    check(len(BOARDS) == int(val("COUNT", "boards")) == 10, "§0 board count = COUNT:boards")
    twins = [b for b in BOARDS.values() if b.twin]
    check(len(twins) == int(val("COUNT", "boards.twins")) and len(twins) * 3 <= len(BOARDS), "twins = COUNT, <= ⅓")
    check(all(BOARDS[n].frames for n in BOARDS), "§H frames for every board")
    check(all("/" not in b.name[len(f"{KEY} / {n:02d} "):] for n, b in BOARDS.items()), "no '/' after the prefix")
    check(len(INV) == int(val("COUNT", "inv.rows")), "§3 rows = COUNT:inv.rows")
    check(sum(r.klass.endswith("animated") for r in INV) == int(val("COUNT", "inv.animated")), "animated count")
    check(sum(r.layer == "canvas" for r in INV) == int(val("COUNT", "inv.canvas")), "canvas count")
    check(all(r.tier(t) for r in INV for t in TIERS), "no blank tier cell")
    check(all(r.calm == r.reduced for r in INV if r.layer == "canvas"), "§3: a canvas row's calm cell = its reduced")
    check(all(r.calm == "as full" for r in INV if r.layer == "DOM"), "§3: a DOM row's calm cell is 'as full'")
    g = (len(BURST), sum(t.price_ticks for t in BURST), BURST[-1].price)
    check(g == TICKS_GOLDEN, f"mulberry32 port = the generator's burst {g}")
    figs = SIM.figures()
    for k_ in ("ticks", "price", "liq", "heat", "bubble", "naive", "combined", "frames"):
        check(str(figs[k_]) == val("SIM", k_), f"SIM:{k_} {figs[k_]} = §4.4's {val('SIM', k_)}")
    check(fr_ms("FR-1") == 500 and fr_ms("FR-5") == 1000 and fr_ms("FR-6") == 500 and fr_int("FR-3") == 2,
          "FR-1/3/5/6 parsed")
    check((REGION_W, REGION_H, WINDOW_MS, HEAT_MS) == (341, 256, 1000, 100), "FR-2 region, window, heat cadence")
    check(RING_GEOM["normal"][:3] == (2, 1, 2), "D04 §7.1 geometry read")
    check(d05_effective(False, "your choice") == "Effective: Off, your choice", "D05 §5.1 template fill")
    check(d05_effective(True, "your choice") == w("W-3"), "W-3 is the On fill of D05's template")
    check(len(MATRIX) == 5 and len(MATRIX_HEAD) == 5 and len(SAFETY) == 7 and len(PAUSE) == 5, "§8 / §10 / §11")
    toks = set(_TS.get("semantic-dark", {})) | set(_TS.get("primitives", {}))
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str)
            and re.match(r"(color|type|space|size|radius|border|opacity)\.", v)] + list(HM.values())
    check(all(t in toks for t in used), f"kit tokens exist: {[t for t in used if t not in toks]}")
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    fr = specimen(BOARDS[10].frames[0], [text("probe", "self-test", BODY, TEXT_1)])
    ann = annotations(10, [(BOARDS[10].frames[0], ["self-test"])])
    try:
        p = write_sheet(10, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json")
        pk = pack_sheet(p, SELFTEST_DIR)
        check(json.loads(pk.read_text())["compactOf"]["file"] == p.name, "packed source is the bare name")
        check('"t": "inst"' not in p.read_text(), "no inst")
    except Exception as e:  # noqa: BLE001 - reported as a failure
        fails.append(f"sample sheet: {e}")
    NOTES.reset()
    for f in fails:
        print("FAIL", f)
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
