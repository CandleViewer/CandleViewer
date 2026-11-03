"""E21-D04 (#504) board kit: the design-system pack's ten specimen boards (CMP-108, 111, 113, 227, 228, 229, 230) as
cvsheet JSON sheets for the per-set Penpot file "E21-D04 boards", page "E21-D04" (spec §0; BQ-13 RULED, comment
6580397401).

Offline only. Spec (binding; every string comes from it): docs/design/E21/E21-D04.md and E21-D04-handoff.md as the
checkout commits them, read by repo-relative path and md5-pinned in DOCS (the kit refuses drifted bytes: re-read,
re-check, re-pin, rebuild). The recorded instrument fixture gives BTCUSDT's tick size and qty step only; every other
number is the seeded synthetic book (seed 504), derived once below and never typed twice. Token values (for the
computed contrast figures) come from the shared tools/token-sync.json.
Registry: §0's board table (BOARDS) and the hand-off's Table 1 Penpot variants (VARIANTS) are parsed, never typed;
the frame plan per board (FRAME_PLAN) is the kit's reading of §0's "Draws" cells (build-notes "Readings").

Checkout: the kit sits at docs/design/_tools/sheets/e21-d04/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming a checkout. In a checkout: raw sheets + .md in build/ (not committed), packed sheets in v4/, the
.md also beside the kit. Outside: the sibling folders E21-D04-cap/ (raw + .md) and E21-D04-v4/ (packed).

Pipeline (one generator per board, gen/gen_NN.py, calling gen/frames.py):
    frames = [frame(vid), ...]                 # the board's frames in FRAME_PLAN order
    build(nn, frames, blocks)                  # raw sheet (validator exit 0 or raises), md (line 3 = render line),
                                               # packed sheet (mkcall4 count agrees; compactOf = bare name + sha256)
Self-test: python3 -I -B e21d04kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (U+2215 "∕" stands for it); no local path, host
or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side;
colour binds are semantic tokens only (the validator refuses primitives), so themes switch at export, file-wide.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E21-D04", "E21", 504
KIT_DIR = Path(__file__).resolve().parent
_SPEC_REL = "docs/design/E21/E21-D04.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_REL).is_file() and KIT_DIR.is_relative_to(up):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _SPEC_REL).is_file():
        raise SystemExit("e21d04kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + their .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets (compactOf.file bare)
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"

DOCS = {  # key -> (repo-relative path, md5 of the as-built text, the boards PR): every read is md5-checked
    "spec": (_SPEC_REL, "056eae85f78f55346bd851f82c0dd7c7"),
    "handoff": ("docs/design/E21/E21-D04-handoff.md", "67fa3748b75d5bc6ec0018afa8f99e4c"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}

REV = "r2"
PITCH_X, PITCH_Y = 6000, 3600  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3600
MARGIN = 80  # root margin and frame gutters
ANN_W = 400  # the ONE annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215: stands for "/" in every node name (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _doc_bytes(key: str) -> bytes:
    return (REPO / DOCS[key][0]).read_bytes()


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e21d04kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _doc_bytes(k).decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}
SPEC_LINES, HANDOFF_LINES = LINES["spec"], LINES["handoff"]
SPEC_TEXT = "\n".join(SPEC_LINES)
HANDOFF_TEXT = "\n".join(HANDOFF_LINES)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def find_line(needle: str, doc: str = "spec", start: int = 1) -> int:
    """1-based number of the first line of doc at or after start containing needle (raises if absent)."""
    ls = LINES[doc]
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"{doc}: not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites: looked up, never typed as a number."""
    return find_line(needle, "spec", start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, "handoff", start)


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("\\|", "|")).strip()


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _flat(doc: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", (SPEC_TEXT if doc == "spec" else HANDOFF_TEXT).replace("\\|", "|"))


def S(chars: str, doc: str = "spec") -> str:
    """A drawn string that must occur verbatim in the spec (or the hand-off), line breaks read as spaces and
    table-escaped pipes unescaped: returns it unchanged."""
    if chars not in _flat(doc):
        raise LookupError(f"{doc}: string not in the text: {chars!r}")
    return chars


def SL(chars: str, doc: str = "spec") -> int:
    """The line a verbatim string starts on (after S)."""
    S(chars, doc)
    for n in (len(chars), 40, 20, 10):
        for i, ln in enumerate(LINES[doc], 1):
            if chars[:n] in ln.replace("\\|", "|"):
                return i
    raise LookupError(chars)



# --- §0: the ten boards (parsed)
_H0 = L("## 0. Status, version and the boards")
FILE_NAME = re.search(r"the file `([^`]+)`", SPEC_LINES[L("Penpot: the file `", _H0) - 1]).group(1)  # type: ignore
PAGE = re.search(r"page `([^`]+)`", SPEC_LINES[L("Penpot: the file `", _H0) - 1]).group(1)  # type: ignore[union-attr]
_EXPORT = re.search(r"exports go to `(docs/design/E21/img/)E21-D04-NN-<slug>\.png`", SPEC_TEXT)
EXPORT_DIR = _EXPORT.group(1)  # type: ignore[union-attr]
ACCOUNTS = tuple(re.findall(r'"(Acct [A-Z])"', SPEC_LINES[L("Penpot: the file `", _H0) - 1]))  # ("Acct A", "Acct B")


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E21-D04 / 01 cmp-108-variants"
    slug: str
    draws: str  # §0's "Draws" cell
    theme_cell: str  # "dark + light" | "dark"
    line: int

    @property
    def twin(self) -> bool:
        return self.theme_cell == "dark + light"

    @property
    def export(self) -> str:
        return f"{EXPORT_DIR}{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def export_light(self) -> str:
        return f"{EXPORT_DIR}{KEY}-{self.nn:02d}-{self.slug}-light.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def theme(self) -> str:
        """The render line's theme: dark, except board 09 (high contrast; build-notes reading 3)."""
        return "high-contrast" if self.nn == HC_BOARD else "dark"


HC_BOARD = 9


def _parse_boards() -> dict[int, Board]:
    a = L("| #   | Board ", _H0)
    out: dict[int, Board] = {}
    for i in range(a + 2, len(SPEC_LINES) + 1):
        ln = SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = _cells(ln)
        m = re.fullmatch(r"`(E21-D04 / (\d{2}) ([a-z0-9-]+))`", c[1])
        # the Status cell: PENDING before the boards, then the drawn record (board id, PNG, gates)
        if not m or int(c[0]) != int(m.group(2)) or not re.match(r"PENDING$|drawn: board id `", c[4]):
            raise ValueError(f"spec L{i}: board row {c[:2]}")
        out[int(c[0])] = Board(int(c[0]), m.group(1), m.group(3), plain(c[2]), c[3], i)
    return out


BOARDS = _parse_boards()
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**", _H0)
NOT_DRAWN = plain(SPEC_LINES[NOT_DRAWN_LINE - 1].split(":", 1)[1])
# W-21 … W-23 (the cancel results) are spoken once through the panel's status node (R-5), never shown; §0 draws no
# cancel result, so the text is binding for them
NOT_DRAWN_KIT = (f"W-21 … W-23, the cancel results (§4.8 L{L('| W-21 |')}–L{L('| W-23 |')}), spoken once through "
                 f"the panel's status node (R-5 L{L('- **R-5 Announcements.**')}); §0 draws no cancel result.")


# --- the hand-off's Table 1 Penpot variants (parsed): "CMP-108 · DomLadderRow / Variant=BidSide, State=Default"
@dataclass(frozen=True)
class Variant:
    vid: str  # the Penpot variant string, verbatim
    cmp: str  # "CMP-108"
    variant: str
    state: str
    story: str
    notes: str
    line: int  # hand-off line


def _parse_variants() -> dict[str, Variant]:
    out: dict[str, Variant] = {}
    for i, ln in enumerate(HANDOFF_LINES, 1):
        if not ln.startswith("| ") or "·" not in ln:
            continue
        c = _cells(ln)
        if len(c) == 5 and re.match(r"CMP-\d{3} · \w+ / ", c[2]):
            out[c[2]] = Variant(c[2], c[2][:7], plain(c[0]), plain(c[1]), plain(c[3]), plain(c[4]), i)
    return out


VARIANTS = _parse_variants()
# CMP-230's drag row: no Penpot variant (absent while E21 holds, no control; the notice carries W-20; D02:265)
DRAG_ABSENT_LINE = HL("| any                | drag        | none: absent while E21 holds")


def cmp_name(cmp: str) -> str:
    """'CMP-108' -> 'CMP-108 · DomLadderRow' (from the hand-off's checklist heading)."""
    m = re.search(rf"## Handoff checklist — ({cmp}) (\w+) \(", HANDOFF_TEXT)
    if not m:
        raise LookupError(cmp)
    return f"{m.group(1)} · {m.group(2)}"


# --- §4.8 copy (parsed): W-n -> (slot, string, source, status, line); a cell may hold several strings joined by " · "
@dataclass(frozen=True)
class Copy:
    wid: str
    slot: str
    strings: tuple[str, ...]
    source: str
    status: str
    line: int


def _parse_copy() -> dict[str, Copy]:
    a = L("| W    | Slot ")
    out: dict[str, Copy] = {}
    for i in range(a + 2, len(SPEC_LINES) + 1):
        ln = SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = _cells(ln)
        strs = tuple(re.findall(r'"([^"]+)"', c[2]))
        out[c[0]] = Copy(c[0], plain(c[1]), strs, plain(c[3]), plain(c[4]), i)
    return out


COPY = _parse_copy()


def W(wid: str, n: int = 0) -> str:
    """The n-th string of W-n (verbatim); records the copy key."""
    cp = COPY[wid]
    copy_key(f"{wid} ({cp.slot}, {cp.status}): \"{cp.strings[n]}\" (L{cp.line})")
    return cp.strings[n]


def Wt(wid: str, subs: dict[str, str], n: int = 0) -> str:
    """W-n's string with its {slots} (or its example values) re-filled from the world; the derivation is noted."""
    base = W(wid, n)
    out = base
    for a, b in subs.items():
        if a not in out:
            raise ValueError(f"{wid}: {a!r} not in {base!r}")
        out = out.replace(a, b, 1)
    if "{" in out:
        raise ValueError(f"{wid}: unfilled slot in {out!r}")
    if out != base:
        derive(f'"{out}": {wid} "{base}" (L{COPY[wid].line}) filled from the synthetic book')
    return out


def name_form(s: str) -> str:
    """§4.8: where a string with ' · ' becomes an accessible name, each ' · ' is written ', '."""
    return s.replace(" · ", ", ")


# --- §4.1's label template (parsed) and its filler
TEMPLATE = re.search(r"\*\*Template\*\*: `([^`]+)`", SPEC_TEXT).group(1)  # type: ignore[union-attr]
TEMPLATE_LINE = L("**Template**: `")


def label(values: dict[str, str], flags: Iterable[str] = ()) -> str:
    """Fill the template: '{x}' slots from values; each '[; …]' clause kept only when its flag (its slot name, or its
    words: 'best bid', 'at the mark', 'stale', …) is given, in the template's order."""
    fl = set(flags)

    def clause(m: re.Match[str]) -> str:
        body = m.group(1)
        slot = re.search(r"\{(\w+)\}", body)
        key = slot.group(1) if slot else body.lstrip("; ").strip()
        return body if key in fl else ""

    s = re.sub(r"\[([^\]]+)\]", clause, TEMPLATE, flags=re.DOTALL)
    for kk, v in values.items():
        s = s.replace("{" + kk + "}", v)
    if "{" in s:
        raise ValueError(f"label: unfilled slot in {s!r}")
    return s


# --- R-3's T2 tokens and §5.1's palette sets (parsed)
R3_LINE = L("- **R-3 The T2 rule.**")
W20_REASON = "ladder.not_built"
_SETS_A = L("| Set                                   | Bid stops")


def _parse_sets() -> list[tuple[str, str, str, str]]:
    out = []
    for i in range(_SETS_A + 2, _SETS_A + 6):
        c = _cells(SPEC_LINES[i - 1])
        out.append((plain(c[0]), plain(c[1]), plain(c[2]), plain(c[3])))
    return out


PALETTE_SETS = _parse_sets()  # [(set name, "color.heatmap.bid.1..5", "color.heatmap.ask.1..5", floor)]


# --- tokens (exact names in token-sync.json; the self-test checks every one). Semantic colour tokens only.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
OVERLAY = "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION = "color.text.on-action"
BORDER, BORDER_STRONG, RING = "color.border.default", "color.border.strong", "color.focus.ring"
ACTION_PRIMARY = "color.action.primary.default"
INFO_SUBTLE, INFO = "color.status.info.subtle", "color.status.info.default"
BUY, SELL, BUY_SUBTLE, SELL_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle", "color.sell.subtle"
STALE_SURFACE, STALE_TEXT = "color.data-confidence.stale.surface", "color.data-confidence.stale.text"
ENV_DEMO = "color.env.demo"
NEUTRAL = "color.neutral.default"
HEAT_ZERO = "color.heatmap.zero"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM = "type.ui.heading-sm"
NUM_XS, NUM_SM, NUM = "type.num.xs", "type.num.sm", "type.num.base"
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
ROW_COMPACT, ROW_COMFORTABLE = "space.row.height.compact", "space.row.height.comfortable"
ICON_SM, ICON = "size.icon.sm", "size.icon"
R_CONTROL, R_CARD, R_BADGE, R_PILL = "radius.control", "radius.card", "radius.badge", "radius.pill"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12, STACK_LG: 16,
      ICON_SM: 12, ICON: 16}
NEVER = ("color.text.disabled", "opacity.disabled")  # R-3 (G-T2.2): never on a T2 label, glyph or reason


def stops(prefix: str) -> list[str]:
    """'color.heatmap.bid.1..5' -> the five token names."""
    m = re.fullmatch(r"([a-z.]+)\.1\.\.5", prefix)
    if not m:
        raise ValueError(prefix)
    return [f"{m.group(1)}.{i}" for i in range(1, 6)]


# --- token values per theme (themes.json: dark = primitives + semantic-dark; light / high-contrast add their set on
# top), for the computed figures only; the sheets bind names, never values
_ROWS = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
_THEME_SETS = {"dark": ("semantic-dark",), "light": ("semantic-light", "semantic-dark"),
               "high-contrast": ("semantic-hc", "semantic-dark")}


def value(name: str, theme: str = "dark") -> str:
    """The hex a token resolves to in a theme (aliases followed through the theme's sets, then primitives)."""
    seen: set[str] = set()
    cur = name
    while True:
        if cur in seen:
            raise ValueError(f"alias loop at {cur}")
        seen.add(cur)
        hit = None
        for st in (*_THEME_SETS[theme], "primitives"):
            hit = next((r[3] for r in _ROWS if r[0] == st and r[1] == cur), None)
            if hit is not None:
                break
        if hit is None:
            raise LookupError(f"{cur} ({theme})")
        if isinstance(hit, str) and hit.startswith("{") and hit.endswith("}"):
            cur = hit[1:-1]
            continue
        return str(hit)


def _lin(c: int) -> float:
    x = c / 255
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def luminance(hexv: str) -> float:
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg: str, bg: str, theme: str = "dark") -> float:
    """WCAG contrast of two tokens in a theme, to two decimals (the audit tool's rounding)."""
    a, b = luminance(value(fg, theme)), luminance(value(bg, theme))
    hi, lo = max(a, b), min(a, b)
    return float(Decimal(str((hi + 0.05) / (lo + 0.05))).quantize(Decimal("0.01"), ROUND_HALF_UP))


FALLBACKS = {
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it",
    "pill": "radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)",
    "hidden": "kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a "
              "'board marker · name' outline (the words a screen reader hears; not on screen in the product)",
    "marker": "kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as "
              "caption text in a 1 px color.border.strong outline, never product UI",
    "hatch": "kit choice: the pulled mark's pattern.hatch.estimated (D05E11 §7, cited, not re-made) drawn as 2 × 2 px "
             "color.neutral.default steps on a 6 px 45° track inside a 1 px dashed outline; the registry's recipe is "
             "applied live",
    "dash": "kit choice: dashed lines (the CMP-227 marker outline, the ask sparkline, the pulled outline) drawn as 4 px "
            "dashes with 4 px gaps",
    "sparkline": "kit choice: CMP-024's lines drawn as 2 px step segments (horizontal runs joined by vertical risers) "
                 "on the sample times; bid solid, ask dashed, each labelled at its end",
    "own-glyph": "kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after "
                 "the words; the glyph itself is the build's",
    "forced": "kit choice: forced-colours frames bind stand-in tokens that resolve near the system colours under the "
              "high-contrast set: Canvas = color.surface.app, CanvasText = color.text.primary, Highlight = "
              "color.action.primary.default, GrayText = color.text.tertiary, ButtonText = color.text.primary",
    "swatch": "kit choice: legend and ramp swatches drawn as 24 × 16 rects bound to the stop tokens, outlined 1 px "
              "color.border.default only in the forced-colours frames (CanvasText outline, §5.5)",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("not_drawn", "sources", "copy_keys", "copy_gaps", "readings", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations", "derivations")


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
    NOTES.add("live_checks", line)


def copy_gap(line: str) -> None:
    """A drawn string the spec does not word (a kit choice or a neutral placeholder): say where it comes from."""
    NOTES.add("copy_gaps", line)


def reading(line: str) -> None:
    NOTES.add("readings", line)


def derive(line: str) -> None:
    NOTES.add("derivations", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


def copy_key(line: str) -> None:
    NOTES.add("copy_keys", line)


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
    if isinstance(n.get("o"), dict):
        n["o"] = {k: v for k, v in n["o"].items() if v is not None} or None
        if n["o"] is None:
            del n["o"]
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
    # cite marks never reach the canvas: a backtick is markdown, not copy (SHEET-FIX: 02 and 10 drew them)
    return node("text", name, chars=str(chars).replace("`", ""), typo=typo, color=color, **kw)


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
# Inter's mean advance in em. Layout keeps 0.56 (the drawn sheets' widths and wraps were built with it, and a rebuild
# must reproduce them). The root-height estimate uses "root", calibrated on the live check: at 0.56 every root came
# out 2-143 px taller than drawn (the annotation columns wrap fewer lines live); at 0.51 the ten estimates sit
# -17 … +37 px of the drawn ends.
INTER_EM = {"layout": 0.56, "root": 0.51}
_EM = ["layout"]
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), NUM_XS: (10, 1.2, True), NUM_SM: (11, 1.2, True), NUM: (13, 1.2, True)}


def text_w(chars: str, typo: str) -> float:
    size, _lh, mono = _FONT.get(typo, _FONT[BODY])
    return round(len(chars) * (0.6 if mono else INTER_EM[_EM[0]]) * size, 1)


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


def est_root_height(n: Node) -> float:
    """est_height with the root calibration (INTER_EM["root"]): for the board root only, never for a node's own size."""
    _EM[0] = "root"
    try:
        return est_height(n)
    finally:
        _EM[0] = "layout"


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




# --- the synthetic book (seed 504; declared synthetic on every board). Every number below is derived here once.
SEED = ISSUE  # the issue number: seeds every size and print
SYMBOL, COIN = "BTCUSDT", "BTC"


def _fixture_filter(key: str, field_: str) -> Decimal:
    d = json.loads(_doc_bytes("fixture"))
    row = next(r for r in d["result"]["list"] if r["symbol"] == SYMBOL)
    return Decimal(row[key][field_])


TICK = _fixture_filter("priceFilter", "tickSize")  # 0.10
QTY_STEP = _fixture_filter("lotSizeFilter", "qtyStep")  # 0.001
PRICE_DP = max(0, -TICK.normalize().as_tuple().exponent)  # 1
MARK = Decimal(re.search(r'"Price (\d{2},\d{3});', SPEC_TEXT).group(1).replace(",", "")).quantize(TICK)  # W-1's
BEST_BID, BEST_ASK = MARK - TICK, MARK + 2 * TICK  # the mark and one tick above it sit inside the spread
LEVELS = 24  # levels a side in the kit's book (the drawn windows use a few of them)
T0_HMS = (14, 32, 10)  # the illustrative clock (UTC) of every frame: the snapshot time
TRAIL_COLS, TRAIL_STEP_S = 12, 1  # the drawn trail: the last 12 columns, 1 s each (kit illustration)


def price(x: Decimal) -> str:
    return f"{x:,.{PRICE_DP}f}"


def qty(x: Decimal) -> str:
    """A size at its step, trailing zeros dropped (W-2's "0.5", W-3's "1.2")."""
    s = f"{x.quantize(QTY_STEP):f}".rstrip("0")
    return s[:-1] if s.endswith(".") else s


def qty1(x: Decimal) -> str:
    """One decimal (W-8's "12.4", W-16's "18.0")."""
    return f"{x.quantize(Decimal('0.1'), ROUND_HALF_UP):,.1f}"


def hms(sec_back: int = 0) -> str:
    h, m, s = T0_HMS
    t = h * 3600 + m * 60 + s - sec_back
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


def _q(x: float) -> Decimal:
    return max(QTY_STEP * 50, Decimal(str(x)).quantize(QTY_STEP, ROUND_HALF_UP))


def _book() -> tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]:
    rng = random.Random(SEED)
    bids = {BEST_BID - i * TICK: _q(math.exp(rng.gauss(0.2, 0.7))) for i in range(LEVELS)}
    asks = {BEST_ASK + i * TICK: _q(math.exp(rng.gauss(0.2, 0.7))) for i in range(LEVELS)}
    return bids, asks


BIDS, ASKS = _book()
_RNG2 = random.Random(f"{SEED}-trail")
PULL_PRICE = BEST_BID - 5 * TICK  # the pulled bid wall (W-16)
PULL_SIZE = Decimal(_RNG2.randint(120, 240)) / 10  # the wall's size before the pull
PULL_COL = 7  # the trail column where the wall vanishes with no print at its price (the pull)
PRINTS = {MARK: _q(_RNG2.uniform(0.1, 0.9)), BEST_ASK: _q(_RNG2.uniform(0.1, 1.5)),
          BEST_BID: _q(_RNG2.uniform(0.1, 1.5))}  # last traded size per level (the mark row is the last trade)


def side_at(p: Decimal) -> str | None:
    return "bid" if p in BIDS else "ask" if p in ASKS else None


def size_at(p: Decimal) -> Decimal | None:
    return BIDS.get(p, ASKS.get(p))


def cum_depth(p: Decimal) -> Decimal | None:
    """The running total from the touch on that side, through p."""
    if p in BIDS:
        return sum((s for q, s in BIDS.items() if q >= p), Decimal(0))
    if p in ASKS:
        return sum((s for q, s in ASKS.items() if q <= p), Decimal(0))
    return None


def trail(p: Decimal) -> list[Decimal]:
    """Resting size at p over the drawn trail (oldest first; the last column is the book now)."""
    now = size_at(p) or Decimal(0)
    if p == PULL_PRICE:
        return [PULL_SIZE] * PULL_COL + [now] * (TRAIL_COLS - PULL_COL)
    rng = random.Random(f"{SEED}-{p}")
    if now == 0:
        return [Decimal(0)] * TRAIL_COLS
    return [_q(float(now) * rng.uniform(0.6, 1.4)) for _ in range(TRAIL_COLS - 1)] + [now]


@dataclass(frozen=True)
class Own:
    acct: str
    side: str  # "buy" | "sell"
    qty: Decimal
    kind: str  # "limit" | "stop"
    price: Decimal
    status: str = "working"  # "working" | "pending" | "amending"


A, B = ("Acct A", "Acct B")
OWN_SINGLE = BEST_BID - 3 * TICK
OWN_AGG = BEST_BID - 8 * TICK
OWN_MIXED = BEST_ASK + 6 * TICK
OWN_PENDING = BEST_ASK + 3 * TICK
OWN_AMENDING = BEST_BID - 6 * TICK
POSITION_AT = BEST_BID - 10 * TICK  # the long position's entry price
POSITION_QTY = Decimal(re.search(r'"Long (\d+\.\d+) · entry"', SPEC_TEXT).group(1))  # type: ignore[union-attr]
OWN = (Own(A, "buy", Decimal("0.5"), "limit", OWN_SINGLE),
       Own(A, "buy", Decimal("0.5"), "limit", OWN_AGG), Own(A, "buy", Decimal("0.2"), "limit", OWN_AGG),
       Own(B, "buy", Decimal("0.5"), "limit", OWN_AGG),
       Own(A, "buy", Decimal("0.5"), "stop", OWN_MIXED), Own(B, "buy", Decimal("0.5"), "stop", OWN_MIXED),
       Own(A, "sell", Decimal("0.2"), "limit", OWN_MIXED),
       Own(A, "sell", Decimal("0.3"), "limit", OWN_PENDING, "pending"),
       Own(B, "buy", Decimal("0.4"), "limit", OWN_AMENDING, "amending"))


for _o in OWN:  # a resting limit order is part of its level's size; a stop rests off the book
    if _o.kind == "limit":
        _bk = BIDS if _o.side == "buy" else ASKS
        if _o.price not in _bk:
            raise ValueError(f"own {_o} is on the wrong side of the book")
        _bk[_o.price] += _o.qty


def own_at(p: Decimal) -> list[Own]:
    return [o for o in OWN if o.price == p]


def queue_ahead(p: Decimal) -> Decimal:
    """The estimated size ahead of the first own order at p: the level's resting size less every own order there."""
    return (size_at(p) or Decimal(0)) - sum((o.qty for o in own_at(p)), Decimal(0))


def trail_window(prices: Iterable[Decimal]) -> list[Decimal]:
    return [s for p in prices for s in trail(p)]


def bucket(s: Decimal, vmax: Decimal, scale: str = "log") -> int:
    """The stop (1..5) a resting size maps to; 0 = the no-data floor (color.heatmap.zero)."""
    if s <= 0 or vmax <= 0:
        return 0
    f = math.log1p(float(s)) / math.log1p(float(vmax)) if scale == "log" else float(s / vmax)
    return max(1, min(5, math.ceil(5 * f - 1e-9)))


def anchors(vmax: Decimal, scale: str = "log") -> tuple[str, str, str]:
    """Three numeric anchors with their unit: 0, the middle stop's lower edge, the window's largest size."""
    mid = Decimal(str(math.expm1(math.log1p(float(vmax)) * 2 / 5))) if scale == "log" else vmax * 2 / 5
    return "0", qty1(mid), f"{qty1(vmax)} {COIN}"


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, copied), lint
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



# --- the frame plan (the kit's reading of §0's "Draws" cells; build-notes "Readings"): frame ids per board. A Table 1
# id is the hand-off's Penpot variant verbatim; the kit-named ids extend it where §0 draws an axis Table 1 does not
# name (density, high contrast, forced colours) or a non-component board (05, 10).
def _t1(cmp: str, *pick: str) -> list[str]:
    ids = [v.vid for v in VARIANTS.values() if v.cmp == cmp]
    return [i for i in ids if any(p == i.split(" / ", 1)[1] for p in pick)] if pick else ids


C108, C111, C113 = cmp_name("CMP-108"), cmp_name("CMP-111"), cmp_name("CMP-113")
C227, C228, C229, C230 = cmp_name("CMP-227"), cmp_name("CMP-228"), cmp_name("CMP-229"), cmp_name("CMP-230")
FRAME_PLAN: dict[int, list[str]] = {
    1: [v for v in _t1("CMP-108") if re.search(r"State=(Default|Aggregate)$", v)],
    2: [f"{C108} / Variant=BidSide, State=Default, Density=Compact",
        f"{C108} / Variant=BidSide, State=Default, Density=Comfortable",
        *_t1("CMP-108", "Variant=BidSide, State=Focus", "Variant=BidSide, State=MenuT2")],
    3: _t1("CMP-111", "Palette=Standard, State=Open", "State=Empty", "State=Pulled", "State=Stale"),
    4: _t1("CMP-113"),
    5: ["Ramps / The four palette sets on the canvas", "Ramps / Colour vision after simulation"],
    6: [*_t1("CMP-230"), f"{C230} / No drag"],  # Table 1's drag row names no Penpot variant (absent while E21 holds)
    7: [*_t1("CMP-227"), *_t1("CMP-229")],
    8: _t1("CMP-228"),
    9: [f"{c} / {m}" for c in (C108, C113, C230) for m in ("High contrast", "Forced colours")],
    10: ["Token map / The palette sets and the entries' tokens", "Redlines / Rows, bars, ring and badge gaps"],
}


def frame_label(vid: str, nn: int) -> str:
    """The caption id: '<frame id> · <theme>'."""
    b = BOARDS[nn]
    th = "dark + light" if b.twin else "high contrast" if b.nn == HC_BOARD else "dark"
    return f"{vid} · {th}"


def frame_name(vid: str, nn: int) -> str:
    """The node name: the caption id with U+2215 for every '/'."""
    return frame_label(vid, nn).replace("/", SLASH)


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# --- the annotation column (ONE, 400 px, outside the frames) and the board
def data_statement() -> str:
    derive(f"book: {SYMBOL}, mark {price(MARK)} (W-1's example price, L{COPY['W-1'].line}), best bid "
           f"{price(BEST_BID)}, best ask {price(BEST_ASK)}, {LEVELS} levels a side at the fixture's tick {TICK}, sizes "
           f"at its qty step {QTY_STEP}, seeded {SEED}; trail {TRAIL_COLS} columns × {TRAIL_STEP_S} s to {hms()} UTC")
    return (f"Data: synthetic only (§0 L{L('Data is a seeded synthetic BTCUSDT book')}): a seeded {SYMBOL} book (seed "
            f"{SEED}), mark {price(MARK)}, tick {TICK} and qty step {QTY_STEP} from the recorded instrument fixture; "
            f"accounts {' and '.join(ACCOUNTS)} are synthetic, every order and the position are props of a DEMO "
            f"session (R-6, C-2.11); no real account, key or balance")


def frame_block(vid: str, nn: int, lines: Iterable[str]) -> tuple[str, list[str]]:
    v = VARIANTS.get(vid)
    head = ([f"Hand-off L{v.line}: {v.variant} · {v.state} · story {v.story}" + (f" · {v.notes}" if v.notes not in
                                                                                    ("—", "") else "")]
            if v else [])
    return frame_label(vid, nn), head + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    twin = (f"Light twin (§0 'dark + light'; cap ⅓): themes are file-wide and every colour here is a semantic token, "
            f"so the light twin is this board exported again under the light set as {b.export_light}"
            if b.twin else "")
    hc = (f"Theme: high contrast at export (§0's 'dark' column read with the file-wide theme rule: the hc rows are only "
          f"true under the high-contrast set; reading 3)" if b.nn == HC_BOARD else f"Theme: {b.theme_cell}")
    head = [f"§0 L{b.line}: {b.draws}", f"Frames: {len(FRAME_PLAN[nn])} (the kit's frame plan for this Draws cell)",
            hc, twin, f"Export: {b.export}", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    nd = (f"Not drawn — the text is binding (§0 L{NOT_DRAWN_LINE}): {NOT_DRAWN} Also not drawn (the kit): "
          f"{NOT_DRAWN_KIT}")
    kids.append(text("not drawn", nd, CAPTION, TEXT_2, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


ROW_MAX_W = 3400  # frames are packed left to right into rows no wider than this
# the drawn roots' heights, each max(annotation end, footer end) + MARGIN as the live check read them (SHEET-FIX)
MEASURED_H = {1: 1512, 2: 999, 3: 1670, 4: 1400, 5: 958, 6: 1195, 7: 789, 8: 1030, 9: 1033, 10: 597}
MEASURED_SLACK = 48  # px: about three caption lines; past it the text has changed since the measure


def layout(frames: list[Node]) -> list[Node]:
    """Rows of frames, left to right, top-aligned; a new row when the next frame would pass ROW_MAX_W."""
    out, y, x, row_h = [], MARGIN, MARGIN, 0
    for f in frames:
        if x > MARGIN and x + f["w"] > MARGIN + ROW_MAX_W:
            x, y, row_h = MARGIN, y + row_h + MARGIN, 0
        out.append(dict(f, x=x, y=y))
        x += f["w"] + MARGIN
        row_h = max(row_h, f["h"])
    return out


def board(nn: int, frames: list[Node], ann: Node, *, strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The root (§0's name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 28 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f, nn) for f in FRAME_PLAN[nn]]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != the plan {want}")
    if "/" in b.name.split(f"{KEY} / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames)
    labels = {frame_name(f, nn): frame_label(f, nn) for f in FRAME_PLAN[nn]}
    caps = [text(f"caption {i:02d}", f"state: {labels.get(f['name'], f['name'])}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
                 w=right - MARGIN)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_root_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    fh = est_root_height(foot[0])
    est = max(bottom + 24 + fh, MARGIN + ah) + MARGIN
    h = MEASURED_H[nn] if strict else int(math.ceil(est))  # the live check's max(annotation end, footer end) + MARGIN
    if strict and abs(h - est) > MEASURED_SLACK:
        raise ValueError(f"board {nn:02d}: measured root h {h} vs the estimate {est:.0f}: past {MEASURED_SLACK} px, "
                         "so the text changed since the live check; re-measure (SHEET-FIX: MEASURED_H)")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the root h {h} is the live check's max(annotation end, footer end) + {MARGIN} "
         f"(estimated {est:.0f}: the annotation column {ah:.0f} px); re-measure it if the annotations change")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


# --- tables (the E08-D10 kit's, copied): cells padded 8 px a side
ROW_H = int(value(ROW_COMPACT))  # 24: space.row.height.compact (hand-off density table)
ROW_H_COMFORTABLE = int(value(ROW_COMFORTABLE))  # 32


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    numeric: bool = False


def cell(name: str, content: str | Node | list[Node] | None, w_: int, *, numeric: bool = False, h: int = ROW_H,
         typo: str | None = None, color: str = TEXT_1) -> Node:
    inner = w_ - 2 * PX[INSET_SM]
    ty = typo or (NUM_SM if numeric else CAPTION)
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        kids = [text("value", content, ty, color, **({"w": inner} if text_w(content, ty) > inner else {}))]
    elif isinstance(content, list):
        kids = content
    else:
        kids = [content]
    return hbox(name, kids, {"padX": INSET_SM, "justify": "end" if numeric else "start", "gap": INSET_XS}, w=w_, h=h)


def header_row(cols: Iterable[Col]) -> Node:
    cs = list(cols)
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=NUM_SM if c.numeric
                                    else CAPTION, color=TEXT_3) for c in cs], {"fill": RAISED},
                w=sum(c.w for c in cs), h=ROW_H, note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, *,
              h: int | None = None, fill: str = RAISED, colors: dict[str, str] | None = None,
              typo: str | None = None) -> Node:
    """One row; h=None: the tallest cell's content + 4 px a side, at least ROW_H, rounded up to 4 px. Raises when a
    cell's content would not fit (no clipped or overlapping text)."""
    cs = list(cols)
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    if h is None:
        probe = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, typo=typo) for c in cs]
        need = max((est_height(dict(k, h=None)) for k in probe), default=0.0) + 8
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    kids = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, typo=typo,
                 color=(colors or {}).get(c.key, TEXT_1)) for c in cs]
    for k in kids:
        if est_height(dict(k, h=None)) > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs about {est_height(dict(k, h=None)):.0f} px > h {h}")
    return hbox(name, kids, {"fill": fill}, w=sum(c.w for c in cs), h=h)


def rows_block(rows: list[Node], name: str = "rows") -> Node:
    return vbox(name, rows, None, w=rows[0]["w"], h=round(sum(est_height(r) for r in rows)))


def spec_table(name: str, cols: list[Col], rows: list[dict[str, str]], *, cap: str, w_: int) -> Node:
    """A spec table drawn as a CMP-049-style grid on the panel surface (caption, header row, rows); cell strings are
    the spec's own."""
    if sum(c.w for c in cols) != w_:
        raise ValueError(f"{name}: columns {sum(c.w for c in cols)} != {w_}")
    body = [table_row(cols, r, f"row · {j + 1:02d}", fill=RAISED if j % 2 else CANVAS) for j, r in enumerate(rows)]
    return vbox(name, [text("caption", cap, CAPTION, TEXT_2, w=w_ - 16), header_row(cols),
                       rect("header rule", w_, 1, BORDER), rows_block(body)], {"gap": STACK_XS}, w=w_)


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(VALIDATOR), str(path), "--components",
                          str(COMPONENTS), "--tokens", str(TOKENS_FILE)], capture_output=True, text=True,
                         encoding="utf-8", timeout=120, check=False)
    return res.returncode, "\n".join((res.stdout + res.stderr).strip().splitlines())


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                out_dir: Path = CAP_DIR, name: str | None = None, strict: bool = True) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator and raise
    RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, strict=strict)
    if b.twin:
        live(f"light twin: after the dark export, activate the light theme, wait as the drivers do, and export the "
             f"same board again as {b.export_light}; read back one bound fill (color.surface.raised) as the light "
             f"value; switch back to dark")
    if b.theme != "dark":
        live(f"theme: board {nn:02d} renders under dark and exports under the {b.theme} set (line 3)")
    live(f"export {b.export}; record the board id and the PNG size in §0")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("not_drawn", f"§0 L{NOT_DRAWN_LINE}: {NOT_DRAWN}")
    NOTES.add("not_drawn", f"the kit: {NOT_DRAWN_KIT}")
    NOTES.add("sources", f"spec {DOCS['spec'][0].rsplit('/', 1)[1]} md5 {DOCS['spec'][1][:8]} and hand-off md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}; §1-§8; RULED comment 6580397401)")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1][:8]} (tick size and qty step only)")
    NOTES.add("sources", "tokens: tools/token-sync.json (names bound; values only for the computed figures)")
    used = sorted(NOTES.d["tokens"])
    if any(t in NEVER for t in used):
        raise RuntimeError(f"board {nn:02d}: a NEVER token is bound")
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
    """The sheet's .md beside it: line 1 "# <board name>", line 3 md_line3(nn), then the summary, frames, the
    validator line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    twin = f" Light twin: the same board exported under the light set as `{b.export_light}`." if b.twin else ""
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".{twin}", "", "## Frames", ""]
    out += [f"- `{frame_name(f, nn)}`" + (f" (hand-off L{VARIANTS[f].line})" if f in VARIANTS else " (kit-named)")
            for f in FRAME_PLAN[nn]] if sp.parent != SELFTEST_DIR.resolve() else ["- self-test frame"]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "not_drawn", "readings", "derivations", "spec_gaps", "deviations", "copy_keys", "copy_gaps",
               "fallbacks", "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if sp.parent == CAP_DIR.resolve() and IN_REPO:  # the copy beside the kit (committed)
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
                         text=True, encoding="utf-8", timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(MKCALL), str(dst), "count"],
                         capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
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


def build(nn: int, frames: list[Node], blocks: list[tuple[str, list[str]]], *,
          board_lines: Iterable[str] = (), summary: str = "") -> tuple[Path, Path, Path]:
    """write_sheet + write_md + pack_sheet for one board (the generators' last step)."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann)
    return p, write_md(nn, p, summary=summary), pack_sheet(p)


# --- §5.2's contrast table (parsed) against the kit's own computation from token-sync.json
def contrast_table() -> dict[str, tuple[str, str, str, str, int]]:
    a = L("| Theme         | Stops ≥ 3:1 |")
    out = {}
    for i in range(a + 2, a + 5):
        c = _cells(SPEC_LINES[i - 1])
        out[c[0]] = (plain(c[2]), c[3], plain(c[4]), c[5], i)
    return out


def lowest(prefixes: Iterable[str], theme: str) -> tuple[str, float]:
    th = "high-contrast" if theme == "high-contrast" else theme
    names = [n for p in prefixes for n in stops(p)]
    return min(((n, ratio(n, CANVAS, th)) for n in names), key=lambda x: x[1])


STD = ("color.heatmap.bid.1..5", "color.heatmap.ask.1..5")
CVD = ("color.cvd.heatmap.bid.1..5", "color.cvd.heatmap.ask.1..5")


# --- self-test: python3 -I -B e21d04kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources)")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10")
    tw = [n for n, b in BOARDS.items() if b.twin]
    check(tw == [1, 4, 6] and len(tw) * 3 <= len(BOARDS), f"light twins {tw} (cap ⅓)")
    check(FILE_NAME == f"{KEY} boards" and PAGE == KEY and ACCOUNTS == ("Acct A", "Acct B"),
          f"file {FILE_NAME!r}, page {PAGE!r}, accounts {ACCOUNTS}")
    check(len(VARIANTS) == 41, f"hand-off Table 1: {len(VARIANTS)} Penpot variants")
    check(DRAG_ABSENT_LINE > 0 and not any("DragT2" in v for v in VARIANTS) and "DragT2" not in SPEC_TEXT,
          f"CMP-230 drag absent while E21 holds (hand-off L{DRAG_ABSENT_LINE}; no DragT2 in the spec)")
    check(all(f in VARIANTS for n in (1, 3, 4, 7, 8) for f in FRAME_PLAN[n]) and
          all(f in VARIANTS for f in FRAME_PLAN[6][:-1]) and FRAME_PLAN[6][-1] == f"{C230} / No drag" and
          [len(FRAME_PLAN[n]) for n in range(1, 11)] == [9, 4, 4, 8, 2, 8, 3, 5, 6, 2],
          f"frame plan {[len(FRAME_PLAN[n]) for n in range(1, 11)]}")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture tick {TICK}, qty step {QTY_STEP}")
    check(price(MARK) == "65,432.0" and BEST_BID < MARK < BEST_ASK, f"mark {price(MARK)}")
    w1 = label({"price": "65,432", "bid": "1.2", "ask": "0.8", "own": "your buy order 0.5 at this price"}, ["own"])
    check(w1 == COPY["W-1"].strings[0], f"the template reproduces W-1: {w1!r}")
    for th, (std_t, std_r, cvd_t, cvd_r, ln) in contrast_table().items():
        key = {"dark": "dark", "light": "light", "high-contrast": "high-contrast"}[th]
        s, c = lowest(STD, key), lowest(CVD, key)
        check((s[0], f"{s[1]:.2f}", c[0], f"{c[1]:.2f}") == (std_t, std_r, cvd_t, cvd_r),
              f"§5.2 L{ln} {th}: computed {s[0]} {s[1]:.2f}, {c[0]} {c[1]:.2f}")
    check(sum(o.qty for o in own_at(OWN_AGG)) == Decimal("1.2") and len(own_at(OWN_AGG)) == 3,
          "aggregate: 3 orders, buy 1.2 (W-3's words)")
    check(PULL_PRICE in BIDS and trail(PULL_PRICE)[0] == PULL_SIZE and PULL_PRICE not in PRINTS,
          f"pulled wall {qty1(PULL_SIZE)} at {price(PULL_PRICE)}, no print there")
    toks = {r[1] for r in _ROWS}
    used = [v for kk, v in globals().items() if kk.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)]
    check(all(u in toks for u in used if u not in NEVER), "kit tokens exist")
    check(all(r[0] != "primitives" for r in _ROWS if r[1] in used and r[1].startswith("color.")),
          "kit colour tokens are semantic")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: S("a string the spec never says")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/' and an unworded string refused")
    sys.path.insert(0, str(KIT_DIR / "gen"))
    import frames as fr_  # noqa: PLC0415  (the frame builders import this kit)
    NOTES.reset()
    vid = FRAME_PLAN[1][0]
    node_, lines = fr_.BUILDERS[1][0](vid, 1)
    ann = annotations(1, [frame_block(vid, 1, lines)], board_lines=["Self-test sheet: one frame"])
    path = write_sheet(1, [node_], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one frame of board 01); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(1) and l3.endswith("theme dark."), f"md line 3: {l3}")
    check(md_line3(9).endswith("theme high-contrast."), "md line 3: board 09 exports under high contrast")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["file"] == path.name, f"packed: bare source name, sha256 ok, {len(sh['sections'])} "
          "sections, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
