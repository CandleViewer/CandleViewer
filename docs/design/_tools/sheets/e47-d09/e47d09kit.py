"""E47-D09 (#1308) board kit: keyboard operability (the order line's select / adjust / commit / cancel, a drawing's
anchor nudge and "Edit values…", a profile's anchor range, node Move mode on the rule canvas, the SCR-012 palette
deltas, the SCR-013 cheatsheet deltas, the SCR-113 redlines and the inert-binding message), ten boards as cvsheet JSON
sheets for the per-set Penpot file "E47-D09 boards", page "E47-D09" (spec §0).

Offline only. Spec (binding; every string, frame and figure comes from it): docs/design/E47/E47-D09.md and
E47-D09-handoff.md, read by repo-relative path from a checkout and md5-pinned in DOCS (the kit refuses drifted bytes:
after a spec edit re-check every L<n> cite, re-pin and rebuild). The registry the palette and the cheatsheet list is
apps/web/src/keymap/keymap.json (KMAP, md5-pinned; unchanged since the spec's base) and its reserved-keys.json (RES);
the one recorded input, the instrument's tick size, comes from the recorded fixture (hand-off §H: "only the
instrument's tick size comes from a recorded fixture"). Every other value is the seeded synthetic world (seed 1308),
declared synthetic on every board's face, and every price, time, count and step is derived from it.

Registry parsed from the spec: §0's board table (BOARDS, twins), §H's frame table (FRAME_PLAN; a twin row "the frames
of NN · light" is expanded from board NN), §1.4's K-rules, §3's census (DE), §10's redlines (RL), §16's copy deck
(COPY, `w()` fills slots), §19.1 C-rows and §19.2 G-rows, the tool-filled counts (COUNT).

Checkout: the kit sits at docs/design/_tools/sheets/e47-d09/ in a checkout (REPO = four levels up; outputs build/ and
v4/), or anywhere with CV_CHECKOUT naming a checkout (outputs in the sibling E47-D09-cap/ and E47-D09-v4/ folders).
Pipeline (one generator per board, gen/gen_NN.py):
    frames = [...]                                    # one 1280 x 800 frame per FRAME_PLAN entry, in order
    ann = annotations(nn, [frame_block(...), ...])    # the ONE 400 px column
    build_all(nn, frames, ann)                        # raw sheet (validator exit 0), .md (line 3), packed sheet
Twins: 02 calls 01's build("light"), 06 and 10 call 05's build("light" / "hc"); every fill is a token, the theme is
set at export. Self-test: python3 -I -B e47d09kit.py selftest. Every board: python3 -I -B check_all.py.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (§H's "<surface>/<state>" frame names are drawn
with U+2215); no local path, host or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells
carry 8 px inner padding a side.
"""
from __future__ import annotations

import hashlib
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

KEY, EPIC, ISSUE = "E47-D09", "E47", 1308
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E47/E47-D09.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file():
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _SPEC_PATH).is_file():
        raise SystemExit("e47d09kit: run inside a checkout or set CV_CHECKOUT to one")
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
_PATHS = {  # alias -> repo-relative path; AT_BASE aliases are read at SPEC_BASE
    "spec": _SPEC_PATH,
    "handoff": "docs/design/E47/E47-D09-handoff.md",
    "keymap": "apps/web/src/keymap/keymap.json",
    "reserved": "apps/web/src/keymap/reserved-keys.json",
    "fixture": FIXTURE_REL,
}
_MD5 = (  # md5 as read, one per _PATHS entry in its order
    "d5d4465e36cae491c78d5f3ea027cb7a",
    "bbb18e25855d41c746e2b0bd60a9b9a6",
    "eb409e85f54a119baff80f94a513e3ad",
    "5683c37f66248472e7b7b494063b7b3e",
    "edd9dd2a060c51bd4bd1450307728ddf",
)
# alias -> (path, md5): every read is md5-checked
DOCS = {a: (rel, m) for (a, rel), m in zip(_PATHS.items(), _MD5, strict=True)}
FILE_NAME = "E47-D09 boards"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80  # root margin and frame gutters (positions, not a flex gap)
ANN_W = 400  # the one annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000  # raw section JSON; the packed section is smaller
PACKED_MAX = 9216  # "each packed section <= ~9 KB"
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b",
    re.I | re.DOTALL)


# the registry as the spec cites it: at the base its "Inputs pinned" line names (git show); main has moved on
AT_BASE = frozenset(("keymap", "reserved"))


def _git_show(sha: str, rel: str) -> bytes:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d09kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout


def _spec_base() -> str:
    m = re.search(rb"\*\*Inputs pinned\.\*\* Base `origin/main` `([0-9a-f]{7,40})`",
                  (REPO / DOCS["spec"][0]).read_bytes())
    if not m:
        raise SystemExit("e47d09kit: the spec's Inputs pinned line names no base")
    return m.group(1).decode()


SPEC_BASE = _spec_base()
_BYTES: dict[str, bytes] = {}


def doc_bytes(key: str) -> bytes:
    if key not in _BYTES:
        rel = DOCS[key][0]
        _BYTES[key] = _git_show(SPEC_BASE, rel) if key in AT_BASE else (REPO / rel).read_bytes()
    return _BYTES[key]


def doc_text(key: str) -> str:
    return doc_bytes(key).decode("utf-8")


def spec_md5_ok() -> dict[str, bool]:
    return {k_: hashlib.md5(doc_bytes(k_)).hexdigest() == m for k_, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e47d09kit: source drifted from DOCS ({', '.join(_DRIFT)}): re-read, re-check, re-pin")


def _read(key: str) -> list[str]:
    return doc_text(key).split("\n")


SPEC_LINES = _read("spec")
HANDOFF_LINES = _read("handoff")
SPEC_TEXT = "\n".join(SPEC_LINES)
_COMMENT = re.compile(r"<!--[^>]*-->", re.DOTALL)


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


def plain(s: str) -> str:
    """A table cell as words: placeholder comments dropped, backticks and bold removed, spaces collapsed."""
    return re.sub(r"\s+", " ", _COMMENT.sub("", s).replace("`", "").replace("**", "")).strip()


def _rows(head: str, end: str, pat: str) -> dict[str, tuple[list[str], int]]:
    """Table rows between the heading `head` and the next `end` heading whose first cell matches pat."""
    a = L(head)
    b = L(end, start=a + 1)
    return {c[0]: (c, i) for i in range(a, b) if SPEC_LINES[i - 1].startswith("|")
            and re.fullmatch(pat, (c := _cells(SPEC_LINES[i - 1]))[0])}


COUNT: dict[str, str] = {k_: v for v, k_ in re.findall(r"([0-9]+)<!--=COUNT:([\w.-]+)-->", SPEC_TEXT, re.DOTALL)}


# --- §0: the ten boards (registry parsed from the spec); §H: their frames
_P0 = L("Penpot: the file `E47-D09 boards`")
PAGE = re.search(r"page `([^`]+)`", SPEC_LINES[_P0 - 1]).group(1)  # type: ignore[union-attr]
_EXPORT = re.search(r"Exports go to `([^`]+)`", SPEC_LINES[_P0 - 1]).group(1)  # type: ignore[union-attr]


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E47-D09 / 01 order-line"
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int  # §0 line
    twin: int | None = None  # light / high-contrast twin of board N

    @property
    def export(self) -> str:
        return _EXPORT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def base(self) -> int:
        return self.twin or self.nn


_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(E47-D09 / (\d{2}) ([a-z0-9-]+))`\s*\|([^|]*)\|\s*(dark|light|hc)\s*\|"
                    r"(?:[^|]*\|)?\s*$")
_TWIN = re.compile(r"^(light|high-contrast) twin of (\d{2})\b")


def _parse_boards() -> dict[int, Board]:
    s0 = L("## 0. Status, artefacts and the boards")
    s1 = L("## 1. Purpose", start=s0)
    out: dict[int, Board] = {}
    for i in range(s0, s1):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        nn = int(m.group(1))
        if int(m.group(3)) != nn:
            raise ValueError(f"§0 L{i}: row {nn} names board {m.group(3)}")
        draws = plain(m.group(5))
        tw = _TWIN.match(draws)
        if tw and {"light": "light", "high-contrast": "hc"}[tw.group(1)] != m.group(6):
            raise ValueError(f"§0 L{i}: twin kind {tw.group(1)} vs theme {m.group(6)}")
        out[nn] = Board(nn, m.group(2), m.group(4), draws, m.group(6), i, int(tw.group(2)) if tw else None)
    return out


BOARDS = _parse_boards()
TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {2: 1, 6: 5, 10: 5}
NOT_DRAWN_LINE = L("**Not drawn (the text is binding)**")
H_LINE = HL("## §H The board plan")
_TWIN_FRAMES = re.compile(r"^the frames of (\d{2}) · (light|hc)$")


def _parse_frames() -> dict[int, tuple[str, ...]]:
    """§H: board -> its frame names as written ("order-line/selected · dark", ...); a twin row is expanded."""
    out: dict[int, tuple[str, ...]] = {}
    twins: dict[int, tuple[int, str]] = {}
    for i in range(H_LINE, len(HANDOFF_LINES)):
        ln = HANDOFF_LINES[i]
        if ln.startswith("## "):
            break
        c = _cells(ln) if ln.startswith("|") else []
        if c and re.fullmatch(r"\d{2}", c[0]):
            m = _TWIN_FRAMES.match(plain(c[1]))
            if m:
                twins[int(c[0])] = (int(m.group(1)), m.group(2))
            else:
                out[int(c[0])] = tuple(re.findall(r"`([^`]+)`", c[1]))
    for nn, (base, th) in twins.items():
        out[nn] = tuple(f.rsplit(" · ", 1)[0] + f" · {th}" for f in out[base])
    return dict(sorted(out.items()))


FRAME_PLAN = _parse_frames()


def frames_of(nn: int) -> tuple[str, ...]:
    return FRAME_PLAN[nn]


def frame_name(fid: str) -> str:
    """The Penpot frame name: §H's "<surface>/<state> · <theme>" with U+2215 for the slash."""
    return fid.replace("/", SLASH)


def frame_id(fid: str) -> str:
    """"order-line/selected · dark" -> "order-line∕selected" (the caption's state id)."""
    return frame_name(fid).split(" · ")[0]


def frame_for(nn: int, state: str, theme: str | None = None) -> str:
    """The §H frame of board nn whose state is `state` ("order-line/pending"), under theme (default the board's)."""
    th = theme or BOARDS[nn].theme
    hit = [f for f in frames_of(nn) if f.rsplit(" · ", 1)[0] == state]
    if len(hit) != 1:
        raise KeyError(f"board {nn:02d}: no single §H frame {state!r}")
    return hit[0].rsplit(" · ", 1)[0] + f" · {th}"


# --- §1.4 K-rules, §3 DE rows, §10 RL rows, §16 copy deck, §19.1 C-rows, §19.2 G-rows
KRULES = {m.group(1): (m.group(2), i + 1) for i, ln in enumerate(SPEC_LINES)
          if (m := re.match(r"- \*\*(K-\d+) ([^*]+?)\*\*", ln))}


def krule(kid: str) -> str:
    """'K-5 Cancel restores (§1.4 L<n>)'."""
    name, ln = KRULES[kid]
    return f"{kid} {name} (§1.4 L{ln})"


DE = {k_: ([plain(x) for x in c], ln) for k_, (c, ln) in _rows("## 3. The census", "## 4.", r"DE-\d+").items()}
RL = {k_: ([plain(x) for x in c], ln) for k_, (c, ln) in _rows("## 10. SCR-113", "## 11.", r"RL-\d+").items()}
CROWS = {k_: ([plain(x) for x in c], ln) for k_, (c, ln) in _rows("### 19.1", "### 19.2", r"D09-C\d+").items()}
GROWS = {k_: ([plain(x) for x in c], ln) for k_, (c, ln) in _rows("### 19.2", "### 19.3", r"D09-G\d+").items()}


def de(did: str) -> str:
    c, ln = DE[did]
    return f"{did} (§3 L{ln}): {c[1]}"


def rl(rid: str) -> str:
    c, ln = RL[rid]
    return f"{rid} (§10 L{ln})"


@dataclass(frozen=True)
class Copy:
    key: str
    text: str  # the string, quotes removed ("{object}, {price}, pending. ...")
    cite: str
    status: str
    line: int


COPY = {k_: Copy(k_, plain(c[1]).strip('"'), plain(c[2]), plain(c[3]), ln)
        for k_, (c, ln) in _rows("## 16. Copy deck", "## 17.", r"W-\d+").items()}
_SLOT = re.compile(r"\{[^{}]*\}")


def w(key: str, *vals: Any) -> str:
    """W-n with its {slots} filled in order (every slot must be filled; a verbatim string takes none)."""
    s = COPY[key].text
    slots = _SLOT.findall(s)
    if len(vals) != len(slots):
        raise ValueError(f"{key}: {len(slots)} slots {slots}, {len(vals)} values")
    for v in vals:
        s = _SLOT.sub(str(v).replace("\\", "\\\\"), s, count=1)
    NOTES.add("copy_keys", f"{key} (§16 L{COPY[key].line}, {COPY[key].status})")
    return s


def wcite(key: str) -> str:
    return f"{key} (§16 L{COPY[key].line}, {COPY[key].status})"


def g(gid: str) -> str:
    if gid not in GROWS:
        raise KeyError(gid)
    c, ln = GROWS[gid]
    NOTES.add("g_rows", f"{gid} (§19.2 L{ln}): {c[1]} (owner {c[3]})")
    return gid


def crow(cid: str) -> str:
    c, ln = CROWS[cid]
    NOTES.add("c_rows", f"{cid} (§19.1 L{ln}): {c[2]}")
    return f"{cid} (§19.1 L{ln})"


# --- the registry (KMAP) and the synthetic keymap profile the boards draw (declared synthetic on every board)
KMAP = json.loads(doc_text("keymap"))
KMAP_LINES = _read("keymap")
RESERVED: dict[str, str] = json.loads(doc_text("reserved"))
CONTEXTS = tuple(KMAP["cheatsheetContexts"])  # the nine, in cheatsheetContexts order (§9 Grouping)


@dataclass(frozen=True)
class Cmd:
    id: str
    label: str
    context: str
    default: str
    destructive: bool
    valid_when: str
    arm: bool  # requiresArm
    confirm: bool

    @property
    def is_range(self) -> bool:
        return ".." in self.default

    @property
    def is_pointer(self) -> bool:  # a pointer chord (§3: "every pointer chord of the registry is named by its id")
        return bool(re.search(r"(drag|click|wheel)$", self.default))

    @property
    def safety(self) -> bool:  # RL-5's safety group: destructive and arm commands
        return self.destructive or self.id.endswith(".arm")


COMMANDS = tuple(Cmd(c["id"], c["label"], c["context"], c["defaultBinding"], bool(c.get("destructive")),
                     c["validWhen"], bool(c.get("requiresArm")), bool(c.get("confirm"))) for c in KMAP["commands"])
CMD = {c.id: c for c in COMMANDS}


def kmap_line(cid: str) -> int:
    return find_line(f'"id": "{cid}"', KMAP_LINES)


# The synthetic profile (hand-off §G QA-3: "remap positions.close_all to Ctrl+Shift+F and two others"; spec §9's AC4
# trace; one command unbound so SCR-012 and SCR-013 have an "unbound" row: no default binding is empty in KMAP).
# "" = unbound. The self-test checks each new key is neither reserved (RES) nor bound elsewhere in a co-active context.
PROFILE = {"positions.close_all": "Ctrl+Shift+F", "ticket.reduce_only": "Alt+R", "replay.bookmark": "Ctrl+B",
           "dom.centre_mark": ""}
UNBOUND_WORD = "unbound"  # W-7, set by w("W-7") where drawn


def binding(cid: str) -> str:
    return PROFILE.get(cid, CMD[cid].default)


def remapped(cid: str) -> bool:
    return bool(PROFILE.get(cid))


def changed_count() -> int:
    """The bindings Reset all puts back (W-17's {n}): every profile entry that differs from the default."""
    return sum(1 for cid, b in PROFILE.items() if b != CMD[cid].default)


# The view the workspace boards are drawn in (kit reading, recorded): SCR-020's trading workspace, the chart, DOM,
# ticket and positions panels docked; a command is valid here when its context is active and its validWhen holds.
VIEW_CONTEXTS = {"workspace": {"Global", "Workspace", "Chart", "DOM", "Ticket", "Positions"}, "journal": {"Global"}}
VIEW_STATE = {"always", "workspace open", "panel focused", "chart panel focused", "working orders exist"}


def valid_here(cid: str, view: str = "workspace") -> bool:
    c = CMD[cid]
    return c.context in VIEW_CONTEXTS[view] and c.valid_when in VIEW_STATE


def kbd_words(b: str) -> str:
    """A binding as the boards write it ("Ctrl+Shift+F"; a pointer chord as its words, "Alt+drag")."""
    return b


def keys_query(q: str) -> str | None:
    """§9 Search: a query that parses as keys ("ctrl shift f", "Ctrl+Shift+F") -> the binding form, else None."""
    parts = [p for p in re.split(r"[\s+]+", q.strip()) if p]
    mods = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
    if len(parts) < 2 or not all(p.lower() in mods for p in parts[:-1]) or len(parts[-1]) != 1:
        return None
    return "+".join([mods[p.lower()] for p in parts[:-1]] + [parts[-1].upper()])


def search(q: str) -> list[Cmd]:
    """§9: a key query matches the binding, any other text the label (case-insensitive substring)."""
    kq = keys_query(q)
    if kq:
        return [c for c in COMMANDS if binding(c.id) == kq]
    return [c for c in COMMANDS if q.lower() in c.label.lower()]


# --- the recorded tick size (§H) and the synthetic world declared on every board's face
def _tick(symbol: str = "BTCUSDT") -> Decimal:
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

    t = find(json.loads(doc_text("fixture")))
    if not t:
        raise LookupError(f"{symbol}: no tickSize in {FIXTURE_REL}")
    return Decimal(t)


SYMBOL = "BTCUSDT"
TICK = _tick(SYMBOL)  # Decimal("0.10") in the pinned fixture
SEED = 1308
SYNTHETIC = (f"Synthetic data (seed {SEED}): a seeded {SYMBOL} 1-minute series, order, profile, rule graph and keymap "
             f"profile; only the {SYMBOL} tick size ({TICK}) is recorded ({FIXTURE_REL})")


def lcg(seed: int) -> Iterable[int]:
    x = seed
    while True:
        x = (1103515245 * x + 12345) % (1 << 31)
        yield x


def px_fmt(p: Decimal, tick: Decimal = TICK) -> str:
    return f"{p.quantize(tick):,}"


def region_name(kind: str, symbol: str, interval: str | None = None, env: str | None = None) -> str:
    """E15-D15's naming rule (D15:262): "{Kind}, {symbol} {interval spelled}" plus ", {Environment}"."""
    s = f"{kind}, {symbol}" + (f" {interval}" if interval else "")
    return s + (f", {env}" if env else "")


PANELS = (  # the four-panel layout in reading order (E47-D04's), D15:262's examples
    ("chart", region_name("Chart", SYMBOL, "1 minute", "Live")),
    ("dom", region_name("DOM", SYMBOL, env="Live")),
    ("positions", region_name("Positions", "all symbols", env="Live")),
    ("tape", region_name("Tape", SYMBOL)),
)


# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_INVERSE, TEXT_LINK = "color.text.on-action", "color.text.inverse", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
DANGER_STRONG, DANGER_SUBTLE, INFO_STRONG = ("color.status.danger.strong", "color.status.danger.subtle",
                                             "color.status.info.strong")
WARN_STRONG, WARN_DEFAULT = "color.status.warning.strong", "color.status.warning.default"
BUY, SELL, BUY_SUBTLE, SELL_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle", "color.sell.subtle"
ENV_LIVE = "color.env.live"
POS_SL, POS_TP, POS_ENTRY, ORDER_LINE = ("color.position.sl", "color.position.tp", "color.position.entry",
                                         "color.order.line")
CANDLE_UP, CANDLE_DOWN, WICK = "color.candle.up", "color.candle.down", "color.candle.wick"
GRID, AXIS_TEXT, CROSSHAIR = "color.grid.line", "color.axis.text", "color.crosshair"
DRAWING, DRAWING_SEL = "color.drawing.default", "color.drawing.selected"
PROF_BAR, PROF_POC, PROF_VA = "color.profile.bar", "color.profile.poc", "color.profile.valuearea"
NODE = {"trigger": "color.node.trigger", "condition": "color.node.condition", "logic": "color.node.logic",
        "action": "color.node.action"}
MARK_FILL = "color.status.info.default"  # the annotation markers (numbered stops, tags, callouts): not product UI
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG, DISPLAY = ("type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg",
                                               "type.ui.display")
NUM, NUM_XS = "type.num.base", "type.num.xs"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
DIALOG_PAD, BUTTON_PADX, PANEL_PAD = "space.dialog.padding", "space.button.paddingX", "space.panel.padding"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
OPACITY_SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, DIALOG_PAD: 24, BUTTON_PADX: 12, PANEL_PAD: 12, ICON: 16, ICON_SM: 12, HAIR: 1, THICK: 2,
      FOCUS_W: 2}
FALLBACKS = {
    "scrim": "fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim",
    "chrome": "kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab "
              "labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only "
              "what this spec names is drawn with words",
    "markers": "kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in "
               "color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes "
               "what is spoken (polite) or what a key does",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "density": "kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, "
               "size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); "
               "the shell bars keep E10's 48 px TopBar",
    "dashed": "fallback: the renderer draws no dashed stroke: the pending line is 8 px segments with 4 px gaps of "
              "the line's own token (each segment a rect), always with its \"pending\" label (§13: never colour or "
              "a line style alone)",
    "chart": "kit choice: the chart is drawn at 4 px per tick and 12 px per 1-minute bar; candles, axis labels and "
             "the profile are derived from the seeded series (every label = a price on the tick grid)",
    "layout-step": "kit choice for D09-G6 (no layout step is defined for the rule canvas): the canvas grid is 24 px "
                   "and one layout step = one grid cell; column / row in W-15 count cells from the canvas origin",
    "type-150": "fallback (E47-D03's FALLBACKS type-150): no type token at a 150 % text scale: each role is drawn "
                "with the token nearest 1.5 x its size (caption 11 -> heading-md 16, label 12 / body 13 -> "
                "heading-lg 20, heading-sm 14 / heading-md 16 -> display 24, num.xs 11 -> heading-md 16)",
    "zoom-200": "kit choice (E47-D03 board 05's): at 200 % the 1280 x 800 window is a 640 x 400 CSS px viewport; "
                "the inset draws the 640 CSS px layout at 1:1 in a 640 px strip with the 400 px viewport outlined; "
                "the device shows it at 2 x",
    "panel-focus": "fallback (E47-D04's): border.panel.focus (= {border.focus}, `16`:88) is not in the token file: "
                   "the focused panel's inset frame is a border.focus inner stroke in color.focus.ring and its header "
                   "bar a 3 px color.focus.ring rect",
    "kbd": "kit choice: CMP-022 Kbd drawn as a pill (color.surface.raised, color.border.default hairline, "
           "radius.control, type.num.xs in color.text.primary); a pointer chord reads as its words",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}
# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "g_rows", "c_rows", "readings", "spec_gaps", "fallbacks", "tokens",
              "live_checks", "deviations")


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


def reading(line: str) -> None:
    """An ambiguity settled by the kit, with the reading chosen (also listed in build-notes.md)."""
    NOTES.add("readings", line)


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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), HEADING_LG: (20, 1.2, False),
         NUM: (13, 1.2, True)}


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



# --- CMP-039 the ring (E47-D04 §7.1 geometry and §7.2 tones, reused from the E47-D04 kit; D04 board 06 draws the
# palette and cheatsheet focus, never redrawn here: the rings on these boards only mark where focus is), drawn from
# nested stroke-only boards so every band is token-bound: outer halo, ring, inner halo, then the offset gap.
CONTROL_H, ROW_H = 24, 24  # compact density (§0)
GEOM_PX = {"normal": (2, 1, 2), "inset": (2, 1, 0)}  # ring px, halo px, offset px (E47-D04 §7.1)
HALO_TOKENS = {"normal": (HAIR,), "inset": (HAIR,)}
RING_TOKENS = {"normal": (FOCUS_W,), "inset": (FOCUS_W,)}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    """Outside-in (colour, width token) bands of the ring; the sum of widths + the offset is the outer extent."""
    return ([(CANVAS, t) for t in HALO_TOKENS[variant]] + [(RING, t) for t in RING_TOKENS[variant]]
            + [(CANVAS, t) for t in HALO_TOKENS[variant]])


def extent(variant: str) -> int:
    """offset + halo + ring + halo, in px (E47-D04 §7.5: 6 px normal; the self-test checks it)."""
    return GEOM_PX[variant][2] + sum(PX[t] for _c, t in ring_bands(variant))


def _layers(name: str, wd: int, ht: int, variant: str, inner: Node | None, radius: str | None) -> Node:
    bands = ring_bands(variant)
    node_: Node | None = None
    sizes, s = [], 0
    for _c, t in bands:
        sizes.append(s)
        s += PX[t]
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
    """CMP-039 around a control with explicit w and h: a w + 2e x h + 2e board (e = extent(variant)); the control
    sits at the offset inside the inner halo."""
    if variant != "normal":
        raise ValueError(variant)
    e = extent(variant)
    cw, ch = int(control["w"]), int(control["h"])
    band_sum = e - GEOM_PX[variant][2]
    last = PX[ring_bands(variant)[-1][1]]
    inner = dict(control, x=last + GEOM_PX[variant][2], y=last + GEOM_PX[variant][2])
    inner.pop("abs", None)
    del band_sum
    return dict(_layers(name or f"CMP-039 ring · {variant}", cw + 2 * e, ch + 2 * e, variant, inner, radius),
                note=f"focus-visible; {variant}: outer extent {e} px (E47-D04 §7.1, §7.5)")


def inset_ring(wd: int, ht: int, *, name: str = "CMP-039 ring · inset", radius: str | None = None) -> Node:
    """CMP-039 inset (rows, cells): the bands drawn inside the element's box, no offset; place it as the row's last
    kid (abs at 0, 0)."""
    return dict(_layers(name, wd, ht, "inset", None, radius), x=0, y=0, abs=True,
                note="CMP-039 inset: drawn inside the element (E47-D04 §7.1)")


# --- annotation overlays inside a frame: numbered stops, region tags, outlines, move arrows, callouts
def marker(n: int | str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    wd = 20 if str(n).isdigit() else 28  # an alphabetic label ("Esc") is a 28 x 20 pill (boards lens D-5)
    return hbox(name or f"stop {n}", [text("n", str(n), LABEL, TEXT_INVERSE)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=wd, h=20, x=x, y=y, abs=True,
                note="annotation marker (not product UI)")


def tag(label_: str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox((name or f"tag · {label_[:40]}").replace("/", SLASH), [text("label", label_, CAPTION, TEXT_INVERSE)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def tag_stack(name: str, lines: Iterable[str], x: int, y: int, wd: int) -> Node:
    """A tag on several lines, for a narrow region (the 56 px NavRail; boards lens m-5)."""
    fallback("markers")
    kids = [text(f"line-{i}", s, CAPTION, TEXT_INVERSE, w=wd - 2 * PX[INSET_XS]) for i, s in enumerate(lines, 1)]
    return vbox(f"tag · {name}".replace("/", SLASH), kids, {"padX": INSET_XS, "padY": INSET_XS, "radius": R_CONTROL,
                                                            "fill": MARK_FILL}, w=wd, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def outline(name: str, x: int, y: int, wd: int, ht: int) -> Node:
    fallback("markers")
    return box(f"outline · {name}", [], {"stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
               w=wd, h=ht, x=x, y=y, abs=True, note="annotation outline (not product UI)")


def hline(name: str, x: int, y: int, wd: int) -> Node:
    return rect(f"arrow · {name}", wd, 2, MARK_FILL, x=x, y=y, abs=True)


def vline(name: str, x: int, y: int, ht: int) -> Node:
    return rect(f"arrow · {name}", 2, ht, MARK_FILL, x=x, y=y, abs=True)


def arrow_head(name: str, glyph_: str, x: int, y: int) -> Node:
    return icon(f"arrow-head · {name}", glyph_, MARK_FILL, x=x, y=y, abs=True)


def callout(name: str, lines: Iterable[str], x: int, y: int, wd: int = 320) -> Node:
    """A spoken string or a move, boxed on the frame (an annotation overlay; the words are §16's)."""
    fallback("markers")
    ls = [ln for ln in lines if ln]
    kids = [text(f"line-{i}", s, CAPTION if i > 1 else LABEL, TEXT_1, w=wd - 2 * PX[INSET_SM])
            for i, s in enumerate(ls, 1)]
    return vbox(f"callout · {name}", kids, {"gap": STACK_XS, "pad": INSET_SM, "fill": OVERLAY, "radius": R_CONTROL,
                                            "stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
                w=wd, x=x, y=y, abs=True, note="annotation callout (not product UI)")


# --- controls at compact density (24 px)
BUTTON_LOOK = {"primary": (ACTION_PRIMARY, TEXT_ON_ACTION, None), "secondary": (ACTION_SECONDARY, TEXT_1, None),
               "ghost": (None, TEXT_2, None), "destructive": (DANGER_SUBTLE, TEXT_1, DANGER_STRONG)}


def placeholder(name: str, w_: int, h: int = 12, fill: str = HOVER) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, fill, {"radius": R_CONTROL})


def button(chars: str, variant: str = "secondary", *, name: str | None = None, lead: Node | None = None,
           focused: str | None = None) -> Node:
    """A CMP-001 button, 24 px; focused="normal" | "thick" wraps it in CMP-039."""
    fill_, col, stroke = BUTTON_LOOK[variant]
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIR, strokeAlign="inner")
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, o, w=wd, h=CONTROL_H)
    return focus_ring(b, focused) if focused else b


def icon_button(glyph_: str, *, name: str | None = None, focused: str | None = None) -> Node:
    b = hbox(name or f"icon button · {glyph_}", [icon("glyph", glyph_, TEXT_2)], {"justify": "center",
                                                                                 "radius": R_CONTROL},
             w=CONTROL_H, h=CONTROL_H)
    return focus_ring(b, focused) if focused else b


def t2_button(chars: str, reason: str, *, focused: str | None = None, name: str | None = None,
              w_: int = 240) -> Node:
    """The T2 paragraph (§12; E09-D09 §2.1 rendering 2a): the CMP-019 lock (accessible name "Not available") leads the
    full label in color.text.tertiary; the primary fill gives way to color.surface.raised + a color.border.default
    hairline; the reason under it in color.text.secondary (aria-describedby, present at mount); aria-disabled="true",
    never the disabled attribute and never opacity.disabled; it stays in the Tab order."""
    kids = [icon("lock", "locked", TEXT_3), text("label", chars, BODY_STRONG, TEXT_3)]
    b = hbox(f"T2 · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "fill": RAISED,
                                     "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"},
             w=round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2), h=CONTROL_H,
             note='aria-disabled="true" (never disabled, never opacity.disabled); the reason is its aria-describedby; CMP-079 RbacGate')
    return vbox(name or f"T2 · {chars} + reason", [focus_ring(b, focused) if focused else b,
                                                   text("reason", reason, CAPTION, TEXT_2, w=w_)], {"gap": INSET_XS})


def switch(on: bool = False) -> Node:
    knob = ellipse("knob", 12, 12, {"fill": TEXT_ON_ACTION if on else TEXT_2}, x=22 if on else 4, y=4)
    return box("switch", [knob], {"fill": ACTION_PRIMARY if on else HOVER, "radius": R_BADGE, "stroke": BORDER,
                                  "strokeWidth": HAIR, "strokeAlign": "inner"}, w=38, h=20)


def toggle_row(label_: str, help_: str | None = None, *, on: bool = False, focused: str | None = None,
               w_: int = 560) -> Node:
    """CMP-004 Toggle with its visible label and description (SCR-117: "never a bare toggle")."""
    sw = switch(on)
    lines = [text("label", label_, BODY_STRONG, TEXT_1, w=w_ - 72)]
    if help_:
        lines.append(text("help", help_, CAPTION, TEXT_2, w=w_ - 72))
    return hbox(f"toggle · {label_[:40]}", [focus_ring(sw, focused, radius=R_BADGE) if focused else sw,
                                            vbox("text", lines, {"gap": STACK_XS})],
                {"gap": INSET_MD, "align": "start"}, w=w_, note='role="switch"')


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
              colors: dict[str, str] | None = None, fill: str | None = None) -> Node:
    """One body row: zebra (odd color.surface.canvas, even color.surface.raised, §16); focused adds CMP-039 inset.
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
    o: dict[str, Any] = {"fill": fill or (CANVAS if i % 2 else RAISED)}
    wd = sum(c.w for c in cs)
    if focused:  # CMP-039 inset on the focused row (E47-D04 §7.1 inset)
        kids.append(inset_ring(wd, h))
    return hbox(name, kids, o, w=wd, h=h)


def table(name: str, caption_: str | None, header: Node, rows: list[Node], *, note: str | None = None) -> Node:
    """A CMP-049 table: the visible caption (type.ui.caption, secondary), the header row, a 1 px rule, the rows."""
    wd = header["w"]
    kids = [text("caption", caption_, CAPTION, TEXT_2, w=wd) if caption_ else None, header,
            rect("header rule", wd, 1, BORDER),
            vbox("rows", rows, None, w=wd, h=round(sum(est_height(r) for r in rows))) if rows else None]
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, note=note)


# §3.2's columns at 944 px (W-08 gives the six headings; Meter and State carry no visible heading in §3.2's list, so


# --- the shell (SCR-010) at 1280 x 800, compact: TopBar 48 (E10) | NavRail 56 · main 984 · RightRail 240 | StatusBar
# 24; on the workspace (SCR-020) main = the tab strip (RG-02) 32, the four panels 2 x 2 (490 x 332, 4 px splitters),
# the minimised tray (RG-04) 28. Frame coordinates of every region are in GEO for the overlays.
TOP_H, STATUS_H, NAV_W, RIGHT_W = 48, 24, 56, 240
MAIN_W, BODY_H = FRAME_W - NAV_W - RIGHT_W, FRAME_H - TOP_H - STATUS_H  # 984, 728
TAB_H, TRAY_H, SPLIT = 32, 28, 4
PANEL_W, PANEL_H = (MAIN_W - SPLIT) // 2, (BODY_H - TAB_H - TRAY_H - SPLIT) // 2  # 490, 332
HEADER_H = 28
GEO: dict[str, tuple[int, int, int, int]] = {
    "topbar": (0, 0, FRAME_W, TOP_H), "navrail": (0, TOP_H, NAV_W, BODY_H), "main": (NAV_W, TOP_H, MAIN_W, BODY_H),
    "tabstrip": (NAV_W, TOP_H, MAIN_W, TAB_H),
    "chart": (NAV_W, TOP_H + TAB_H, PANEL_W, PANEL_H),
    "dom": (NAV_W + PANEL_W + SPLIT, TOP_H + TAB_H, PANEL_W, PANEL_H),
    "positions": (NAV_W, TOP_H + TAB_H + PANEL_H + SPLIT, PANEL_W, PANEL_H),
    "tape": (NAV_W + PANEL_W + SPLIT, TOP_H + TAB_H + PANEL_H + SPLIT, PANEL_W, PANEL_H),
    "tray": (NAV_W, TOP_H + BODY_H - TRAY_H, MAIN_W, TRAY_H),
    "rightrail": (FRAME_W - RIGHT_W, TOP_H, RIGHT_W, BODY_H), "statusbar": (0, FRAME_H - STATUS_H, FRAME_W, STATUS_H),
}
FLATTEN = "FLATTEN ALL"  # the TopBar control §9.2 names (`14`:302); FREEZE beside it in `14` SCR-010's wireframe
FREEZE = "FREEZE"


def topbar(*, flatten: Node | None = None) -> Node:
    """TopBar (banner): placeholders, then FLATTEN ALL and FREEZE (or `flatten`, a focused / T2 variant)."""
    left = hbox("left", [placeholder("wordmark", 72), placeholder("env badge", 40, 16, ENV_LIVE),
                         placeholder("account picker", 120), placeholder("symbol picker", 88),
                         placeholder("interval picker", 48)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chips", 160), flatten or button(FLATTEN, "destructive"),
                           button(FREEZE, "destructive"), placeholder("user menu", 64)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar · banner", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                       abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note='role="banner"')


def navrail(*, admin: bool = True, current: int = 1) -> Node:
    """NavRail (navigation): six entries + Admin (Owner only; T3-absent otherwise, §10)."""
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center", "radius": R_CONTROL,
                                                                **({"fill": SELECTED} if i == current else {})},
                 w=40, h=CONTROL_H + 8) for i in range(1, 7)]
    if admin:
        rows.append(hbox("entry-admin", [placeholder("admin glyph", 16, 16)], {"justify": "center"}, w=40,
                         h=CONTROL_H + 8, note="Admin entry: Owner only"))
    return vbox("NavRail · navigation", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0,
                                                       abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H,
                note='<nav> with aria-current')


def rightrail() -> Node:
    rows = [placeholder(f"row-{i}", RIGHT_W - 24) for i in range(1, 5)]
    return vbox("RightRail · complementary", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"gap": INSET_MD, "pad": INSET_MD, "fill": APP}, w=RIGHT_W, h=BODY_H, note='role="complementary"')


def statusbar() -> Node:
    return hbox("StatusBar · contentinfo", [placeholder("connection chip", 120), placeholder("clock", 96),
                                            placeholder("version", 48),
                                            rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=FRAME_W, h=STATUS_H,
                note='role="contentinfo"')


def tabstrip() -> Node:
    tabs = [hbox(f"tab-{i}", [placeholder("tab label", 72)], {"padX": INSET_MD, "radius": R_CONTROL,
                                                              **({"fill": SELECTED} if i == 1 else {})},
                 h=CONTROL_H) for i in range(1, 4)]
    return hbox("tab strip · RG-02 Workspaces", tabs, {"gap": INSET_XS, "padX": INSET_SM, "fill": APP}, w=MAIN_W,
                h=TAB_H, note='role="tablist" aria-label="Workspaces"; the active tab is the visually hidden h1')


def tray() -> Node:
    chips = [placeholder(f"minimised-{i}", 96, 16) for i in (1, 2)]
    return hbox("tray · RG-04 Minimised panels", chips, {"gap": INSET_SM, "padX": INSET_SM, "fill": APP}, w=MAIN_W,
                h=TRAY_H, note='role="toolbar" aria-label="Minimised panels"')


def flatten_x(flatten: Node | None = None) -> int:
    """The frame x of the TopBar's FLATTEN ALL control (its right group is end-justified; estimate)."""
    fl = flatten or button(FLATTEN, "destructive")
    rest = 64 + est_width(button(FREEZE, "destructive")) + est_width(fl) + 3 * PX[INSET_MD]
    return round(FRAME_W - PX[INSET_LG] - rest)


TOOLBAR_GLYPHS = ("more-horizontal", "close")  # RG-08: the header actions (kit choice of glyphs)


def panel(kind: str, name: str, body: Node | None, *, focused: bool = False, toolbar_focus: int | None = None,
          w_: int = PANEL_W, h_: int = PANEL_H, extra: Iterable[Node] = ()) -> Node:
    """A docked panel (region named by D15's rule): the header (h2 + the RG-08 toolbar), the body; focused draws
    CMP-080's inset frame and the header bar in color.focus.ring (§7.4; `16`:88), never CMP-039 around the panel."""
    tools = [icon_button(gl, focused="normal" if toolbar_focus == i else None, name=f"tool {i} · {gl}")
             for i, gl in enumerate(TOOLBAR_GLYPHS, 1)]
    header = hbox("header", [text("h2", name, BODY_STRONG, TEXT_1), hbox("RG-08 toolbar", tools, {"gap": INSET_XS},
                                                                         h=HEADER_H)],
                  {"padX": INSET_SM, "justify": "space-between", "fill": RAISED}, w=w_, h=HEADER_H,
                  note=f'h2 "{name}"; RG-08 toolbar named by the panel')
    bh = h_ - HEADER_H
    kids: list[Node] = [header, box("body", [body] if body else [], {"fill": CANVAS, "clip": True}, w=w_, h=bh),
                        *extra]
    if focused:
        fallback("panel-focus")
        kids += [box("panel focus frame", [], {"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"},
                     w=w_, h=h_, x=0, y=0, abs=True, note="CMP-080 inset frame (border.panel.focus)"),
                 rect("panel focus header bar", w_, 3, RING, x=0, y=0, abs=True)]
    return vbox(f"panel · {kind}", kids, {"clip": True}, w=w_, h=h_, note=f'role="region" aria-label="{name}"')


def _frame(fid: str, kids: list[Node], overlays: Iterable[Node], note: str | None) -> Node:
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    return vbox(frame_name(fid), [*kids, *overlays], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H, note=note)


def workspace_window(fid: str, bodies: dict[str, Node | None], *, focus_panel: str | None = None,
                     toolbar_focus: tuple[str, int] | None = None, panel_extra: dict[str, list[Node]] | None = None,
                     overlays: Iterable[Node] = (), flatten: Node | None = None, note: str | None = None) -> Node:
    """SCR-020 in the shell (§2, §3): bodies[kind] fills each of the four panels (None: an empty canvas)."""
    fallback("density")
    ps = []
    for kind, name in PANELS:
        x, y, _w, _h = GEO[kind]
        p = panel(kind, name, bodies.get(kind), focused=focus_panel == kind,
                  toolbar_focus=toolbar_focus[1] if toolbar_focus and toolbar_focus[0] == kind else None,
                  extra=(panel_extra or {}).get(kind, ()))
        ps.append(dict(p, x=x - NAV_W, y=y - TOP_H))
    main = box("main · workspace", [dict(tabstrip(), x=0, y=0), *ps,
                                    dict(tray(), x=0, y=BODY_H - TRAY_H)], {"fill": BORDER_SUBTLE, "clip": True},
               w=MAIN_W, h=BODY_H, note='<main>; each panel a region; splitters 4 px (color.border.subtle)')
    body = hbox("body", [navrail(), main, rightrail()], {"align": "start"}, w=FRAME_W, h=BODY_H)
    return _frame(fid, [topbar(flatten=flatten), body, statusbar()], overlays, note)


def page_window(fid: str, content: Node, *, admin: bool = True, flatten: Node | None = None,
                overlays: Iterable[Node] = (), note: str | None = None) -> Node:
    """A full page (§4 full-page form) in the shell: content fills main (984 x 728)."""
    fallback("density")
    main = box("main · page", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=MAIN_W, h=BODY_H,
               note="<main>")
    body = hbox("body", [navrail(admin=admin, current=6), main, rightrail()], {"align": "start"}, w=FRAME_W,
                h=BODY_H)
    return _frame(fid, [topbar(flatten=flatten), body, statusbar()], overlays, note)


def specimen_frame(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    """A 1280 x 800 specimen frame (boards 08-10): color.surface.app, 40 px inset, a column of kids."""
    inner = vbox("specimen", kids, {"gap": STACK_LG}, w=FRAME_W - 80, x=40, y=40)
    return box(frame_name(fid), [inner], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H,
                note=note or "specimen: every fill a token; the theme is set at export")


# --- dialogs (CMP-044 alertdialog over the flat scrim)
DIALOG_W = 480  # kit choice: no source gives CMP-044's width at 1280 (recorded)


def dialog(title: str, kids: Iterable[Node | None], actions: Iterable[Node], *, name: str | None = None,
           w_: int = DIALOG_W) -> Node:
    deviate(f"dialog width {w_} px: a kit choice (no source gives CMP-044's width)")
    iw = w_ - 2 * PX[DIALOG_PAD]
    body = [text("title", title, HEADING_MD, TEXT_1, w=iw, note="h2: the dialog's name"), *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "justify": "end"}, w=iw, h=CONTROL_H + 20)]
    return vbox(name or "CMP-044 dialog", body, {"fill": OVERLAY, "radius": R_DIALOG, "pad": DIALOG_PAD,
                                                 "gap": STACK_MD, "stroke": BORDER, "strokeWidth": HAIR,
                                                 "strokeAlign": "inner"}, w=w_,
                note='role="alertdialog" aria-modal; the page behind is inert')


# a centred dialog's live-measured height and its y after the re-centre, keyed by node name (board 01 / 02)
MEASURED_MODAL: dict[str, tuple[int, int]] = {"CMP-044 confirm · amend": (183, 309)}


def modal(dialog_node: Node, *, x: int | None = None, y: int | None = None) -> tuple[Node, tuple[int, int, int, int]]:
    """The overlay for a window's overlays: the flat scrim over the frame and the dialog centred; returns the overlay
    and the dialog's frame rect (x, y, w, h estimated)."""
    fallback("scrim")
    name = dialog_node["name"]
    dw, dh = est_width(dialog_node), est_height(dialog_node)
    m = MEASURED_MODAL.get(name) if x is None and y is None else None
    if m:
        dh = m[0]
    dx = round((FRAME_W - dw) / 2) if x is None else x
    dy = (m[1] if m else round(max((FRAME_H - dh) / 2, 0))) if y is None else y
    if x is None and y is None:
        live(f"modal: re-centre '{name}' after relayout, both axes ({'measured' if m else 'estimated'} "
             f"{dw:.0f} x {dh:.0f} px{f', y {dy}' if m else ''})")
    elif x is None:
        live(f"modal: re-centre '{name}' horizontally only after relayout (estimated {dw:.0f} px wide); keep y {dy}: "
             "it is top-anchored, never re-centred vertically")
    else:
        live(f"modal: keep '{name}' at ({dx}, {dy}) after relayout: placed by the sheet, never re-centred")
    scrim = rect("scrim", FRAME_W, FRAME_H, SUNKEN, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    dlg = dict(dialog_node, x=dx, y=dy)
    return box("overlay", [scrim, dlg], None, w=FRAME_W, h=FRAME_H, x=0, y=0, abs=True), (dx, dy, round(dw), round(dh))


def lines_block(name: str, lines: Iterable[str], *, w_: int, typo: str = BODY, color: str = TEXT_1) -> Node:
    ls = [x for x in lines if x]
    return vbox(name, [text(f"line-{i}", s, typo, color, w=w_) for i, s in enumerate(ls, 1)], {"gap": STACK_XS},
                w=w_)




# --- the synthetic world (seed 1308; every number derived, never typed)
MARK = Decimal("67420.00").quantize(TICK)  # the synthetic mark (= the last close); every price is MARK +/- k * TICK
PX_PER_TICK, BAR_W = 4, 12  # FALLBACKS["chart"]
SESSION_DATE = "2026-10-05"  # the fixture's date; the 1-minute bars start at BAR0 UTC
BAR0 = 13 * 60  # 13:00 UTC in minutes


@dataclass(frozen=True)
class Bar:
    i: int
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741
    c: Decimal

    @property
    def hhmm(self) -> str:
        m = BAR0 + self.i
        return f"{m // 60:02d}:{m % 60:02d}"


def series(n: int = 60, seed: int = SEED) -> list[Bar]:
    """n seeded 1-minute bars ending with close == MARK: closes walk back from MARK in -6..+6 ticks; open = the
    previous close; high / low 0..3 ticks beyond the body."""
    r = lcg(seed)
    closes = [MARK]
    for _ in range(n - 1):
        closes.append(closes[-1] - (next(r) % 13 - 6) * TICK)
    closes.reverse()
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - (next(r) % 5 - 2) * TICK
        h = max(o, c) + (next(r) % 4) * TICK
        lo = min(o, c) - (next(r) % 4) * TICK
        out.append(Bar(i, o, h, lo, c))
    return out


SERIES = series()


def tick_ladder(p: Decimal, k: int) -> Decimal:
    return (p + k * TICK).quantize(TICK)


# the long position and its working orders (SCR-063 rows; DE-01's line): all on the tick grid around MARK
QTY = "0.250"
ENTRY = tick_ladder(MARK, -15)
SL = tick_ladder(MARK, -40)  # the working stop the boards select (a long's stop: tighten = up, toward the price)
TP = tick_ladder(MARK, 45)
NUDGE = 5  # board 01: `↑` five times (hand-off §E: "press ↑ five times")
WRONG_SIDE_PRESSES = 5  # board 01: `Shift+↑` five times = 50 ticks, past the mark
PENDING = tick_ladder(SL, NUDGE)
WRONG = tick_ladder(SL, 10 * WRONG_SIDE_PRESSES)


def wrong_side(p: Decimal, side: str = "Long") -> bool:
    """`11`:3056-3057: a long's stop at or above the mark is on the wrong side (it would close at once)."""
    return p >= MARK if side == "Long" else p <= MARK


# --- the annotation column (ONE, 400 px, outside the frames) and the board
def frame_block(fid: str, lines: Iterable[str], *, keyboard: str | None = None,
                waits: Iterable[str] = ()) -> tuple[str, list[str]]:
    """The annotation block of one frame: what it draws (the author's lines, each citing its §/L line), the keyboard
    path, the G-rows it waits on."""
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    out = [x for x in lines if x]
    if keyboard:
        out.append(f"Keyboard: {keyboard}")
    gs = [g(x) for x in waits]
    if gs:
        out.append("Waits on " + "; ".join(f"{k} (§19.2 L{GROWS[k][1]}: {GROWS[k][0][1]})" for k in gs))
    return frame_name(fid), out


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title (the board name), a "Board" block (§0's Draws, theme, twin, export, §H frames,
    the synthetic declaration), one block per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}",
            f"Theme: {b.theme}" + (f" (twin of board {b.twin:02d}: same frames, theme set at export)" if b.twin
                                   else ""),
            f"Frames (hand-off §H L{H_LINE}): " + ", ".join(frames_of(nn)), f"Export: {b.export}",
            "Every frame 1280 x 800 at compact density (§0); markers, tags, outlines and callouts in "
            "color.status.info.default are annotation, not product UI", SYNTHETIC, *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    """Frames placed 1:1 in rows of <= MAX_PER_ROW (2 or 4 frames: 2 per row); MARGIN margin, gutters MARGIN + the
    28 px state caption above each row."""
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


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# root heights measured live (max(annotation end, footer end) + MARGIN), the drawing lane's checked `want`: the
# footer's one-line data statement ends 2 px above the estimate (14 px, not 16); on 03 the annotation column is longer
MEASURED_H: dict[int, int] = {1: 1878, 2: 1878, 3: 1008, 4: 1878, 5: 1878, 6: 1878, 7: 1878, 8: 1878, 9: 998, 10: 1878}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int | None = None,
          strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, fill color.surface.app, clip) hugging its frames + the ONE annotation
    column + MARGIN; a "state: <id>" caption 28 px above each frame; the synthetic-data footer under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in frames_of(nn)]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §H {want}")
    if any(f["w"] != FRAME_W or f["h"] != FRAME_H for f in frames):
        raise ValueError(f"board {nn:02d}: every frame is a {FRAME_W} x {FRAME_H} window (§0)")
    placed = layout(frames, per_row)
    caps = [text(f"caption {i:02d}", f"state: {f['name'].split(' · ')[0]}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · synthetic", SYNTHETIC, CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + 24 + 14 + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end {bottom + 24 + 14} + {MARGIN}")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    if strict and nn in MEASURED_H:
        live(f"after touchTexts + relayout: the root's h {h} is the measured max(column end, footer end) + {MARGIN} "
             f"(annotation column estimated {ah:.0f} px); read it back")
    else:
        live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root "
             f"(h {h}); set the root's h to max(column end, footer end) + {MARGIN}")
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
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1][:8]} (§0 L{b.line}); hand-off "
                         f"{DOCS['handoff'][0]} md5 {DOCS['handoff'][1][:8]} (§H L{H_LINE}); registry at {SPEC_BASE} "
                         f"{DOCS['keymap'][0]} md5 {DOCS['keymap'][1][:8]} and {DOCS['reserved'][0]} md5 "
                         f"{DOCS['reserved'][1][:8]}; tick size: {FIXTURE_REL} md5 {DOCS['fixture'][1][:8]}")
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




def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>. The packer records the raw sheet's absolute path and sha256 in
    its pack-source field; inside a checkout the path is rewritten to the bare file name (committable), outside one it
    stays absolute (the render drivers read the raw sheet through it). Checks: the sha256 is the raw sheet's, every
    packed section <= PACKED_MAX bytes, and mkcall4.py's `count` equals the sections."""
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
    field = [k_ for k_ in json.loads(raw) if k_.startswith("compact")]
    if len(field) != 1:
        raise RuntimeError(f"{dst.name}: no single pack-source field ({field})")
    src_f = json.loads(raw)[field[0]]
    pf = src_f.get("file")
    if not pf or Path(pf) != src or src_f.get("sha256") != hashlib.sha256(src.read_bytes()).hexdigest():
        raise RuntimeError(f"{dst.name}: pack source {pf!r} / sha256 is not the raw sheet's")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(n_sec):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} "
                           f"!= {n_sec}: {cnt.stderr.strip()[-300:]}")
    if IN_REPO:
        abs_field = json.dumps(pf, ensure_ascii=False)
        if raw.count(abs_field) != 1:
            raise RuntimeError(f"{dst.name}: the pack source path occurs {raw.count(abs_field)} times")
        dst.write_text(raw.replace(abs_field, json.dumps(src.name, ensure_ascii=False)), encoding="utf-8")
    sh = json.loads(dst.read_text(encoding="utf-8"))
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    return dst


def md_line3(nn: int) -> str:
    """The render drivers' line (they parse "page `...`" and "theme dark." / "theme light." / "theme hc.")."""
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
                      f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}`" for f in frames_of(nn)]
    out += [f"- {ln}" for ln in frames_info]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "readings", "g_rows", "c_rows", "spec_gaps", "deviations", "copy_keys", "copy_gaps",
               "fallbacks", "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if IN_REPO and sp.parent == CAP_DIR.resolve():  # the committed copy beside the kit
        (KIT_DIR / p.name).write_text(s, encoding="utf-8")
    return p


def build_all(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
              summary: str = "", frames_info: Iterable[str] = ()) -> tuple[Path, Path, Path]:
    """write_sheet + write_md + pack_sheet for board nn; prints one line per board."""
    p = write_sheet(nn, frames, ann, notes=notes)
    md = write_md(nn, p, summary=summary, frames_info=frames_info)
    pk = pack_sheet(p)
    sh = json.loads(p.read_text(encoding="utf-8"))
    print(f"board {nn:02d}: {p.name} {sh['board']['w']} x {sh['board']['h']}, {len(sh['sections'])} sections; "
          f"packed {len(json.loads(pk.read_text(encoding='utf-8'))['sections'])}")
    return p, md, pk




# --- self-test: python3 -I -B e47d09kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s {spec_md5_ok()}")
    check(sorted(BOARDS) == list(range(1, 11)) and str(len(BOARDS)) == COUNT["boards"], "§0: ten boards 01-10")
    th = [b.theme for b in BOARDS.values()]
    check((th.count("dark"), th.count("light"), th.count("hc")) == (7, 2, 1), "§0 themes 7 dark / 2 light / 1 hc")
    check(TWINS == {2: 1, 6: 5, 10: 5} and str(len(TWINS)) == COUNT["boards.twins"] and 3 * len(TWINS) <= len(BOARDS),
          f"§0 twins {TWINS} (<= one third)")
    nf = sum(map(len, FRAME_PLAN.values()))
    check(sorted(FRAME_PLAN) == sorted(BOARDS) and nf == 41, f"§H: {nf} frames over ten boards")
    check(all(f.endswith(f" · {BOARDS[nn].theme}") for nn, fs in FRAME_PLAN.items() for f in fs),
          "§H frame themes agree with §0")
    check(all(len(set(fs)) == len(fs) for fs in FRAME_PLAN.values()), "§H frame names unique per board")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards", f"§0 page {PAGE!r}")
    check(BOARDS[1].export == "docs/design/E47/img/E47-D09-01-order-line.png", f"export {BOARDS[1].export}")
    check(len(COPY) == 25 and COPY["W-7"].text == "unbound" and COPY["W-2"].text == "Amend cancelled",
          f"§16 copy deck ({len(COPY)} rows)")
    check(sorted(KRULES, key=lambda x: int(x[2:])) == [f"K-{i}" for i in range(1, 13)], "§1.4 K-1 ... K-12")
    check(str(len(DE)) == COUNT["census"] and len(RL) == 5, f"§3 {len(DE)} DE rows = COUNT census; §10 5 RL rows")
    check(len(GROWS) == 6 and len(CROWS) == 18, f"§19 {len(GROWS)} G-rows, {len(CROWS)} C-rows")
    check(str(len(COMMANDS)) == COUNT["registry"] and str(len(COMMANDS) - 1) == COUNT["palette"],
          f"registry {len(COMMANDS)} = COUNT registry; palette rows {len(COMMANDS) - 1} = COUNT palette")
    check(str(sum(c.is_pointer for c in COMMANDS)) == COUNT["chords"], "pointer chords = COUNT chords")
    check(len(CONTEXTS) == 9 and all(c.context in CONTEXTS for c in COMMANDS), "nine cheatsheet contexts")
    check(TICK == Decimal("0.10"), f"fixture tick {TICK}")
    for cid, b in PROFILE.items():
        clash = [c.id for c in COMMANDS if c.id != cid and b and binding(c.id) == b
                 and ({c.context, CMD[cid].context} & {"Global"} or c.context == CMD[cid].context)]
        check(cid in CMD and b not in RESERVED and not clash, f"profile {cid} -> {b or 'unbound'}: not reserved, "
                                                             f"no clash {clash}")
    check([c.id for c in search("ctrl shift f")] == ["positions.close_all"]
          and "positions.close_all" in [c.id for c in search("close all")]
          and [c.id for c in search("Ctrl+Shift+F")] == ["positions.close_all"], "§9 AC4: found by name and by key")
    check(changed_count() == 4, f"W-17 count {changed_count()}")
    check(SERIES[-1].c == MARK and all(b.l <= min(b.o, b.c) and b.h >= max(b.o, b.c) for b in SERIES)
          and all(((x - MARK) / TICK) == int((x - MARK) / TICK) for b in SERIES for x in (b.o, b.h, b.l, b.c)),
          "series ends at the mark; every OHLC on the tick grid")
    check(not wrong_side(PENDING) and wrong_side(WRONG) and SL < ENTRY < MARK < TP, "order-line prices consistent")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)] + list(NODE.values())
    check(all(u in toks for u in used), f"kit tokens exist ({len(set(used))}; missing "
                                        f"{sorted(set(u for u in used if u not in toks))})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: w("W-1")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', unfilled slot refused")
    NOTES.reset()
    fid = FRAME_PLAN[9][0]
    fr = page_window(fid, box("content", [], {"fill": CANVAS}, w=MAIN_W, h=BODY_H),
                     overlays=[callout("W-2", [w("W-2")], 700, 420)])
    blk = frame_block(fid, ["self-test frame"])
    ann = annotations(9, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    path = write_sheet(9, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(9, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark."), f"md line 3 parses: {l3}")  # type: ignore
    check(md_line3(10).endswith("theme hc.") and md_line3(2).endswith("theme light."), "md line 3: light and hc")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(len(sh["sections"]) > 0, f"packed {packed.name}: source sha256 = raw, {len(sh['sections'])} sections, "
                                   "mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
