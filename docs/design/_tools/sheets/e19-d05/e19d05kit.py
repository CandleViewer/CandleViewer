"""E19-D05 (#500) board kit: the ten boards of the profile motion spec (case table, POC jump, developing -> final,
live growth, developing value area, re-bucket, visible range, nPOC / overlay / dock, suppression matrix, flash audit
and announcements) as cvsheet JSON sheets for the Penpot file "E19-D05 boards", page "E19-D05" (spec §0; BQ-13
RULED: ACCEPT). The boards are drawn: spec §0 and §16 record them, BUILD.md rebuilds the sheets.

Offline only. Sources (binding; every drawn string comes from them, k.S checks it verbatim): the spec
docs/design/E19/E19-D05.md, the E19-D03 spec (D03, read at 35032f521) and the E19-D02 spec (D02, read at 3619e95c5),
the motion primitives (PRIM, packages/ui/tokens/primitives.tokens.json: durations and easings) and the recorded
instrument fixture (tick size, qty step), all read by repo-relative path from a checkout and md5-pinned in DOCS (the
kit refuses drifted bytes: re-read, re-check, re-pin). A source absent from the checkout, or whose bytes differ, is read
from its pinned commit with `git show`. E19-D05 has no hand-off file (BQ-1: the motion table is the Motion pair of
CMP-110 / CMP-183 / CMP-184), so there is no hand-off pin. Every price, size, count and time on a board is the seeded
synthetic world below (seed 500, the issue number, as §9's prototype), derived once and never typed twice.

Checkout: the repository root is $CV_REPO when set, else this file's parents[4] (the committed layout
docs/design/_tools/sheets/e19-d05/). Outputs: raw sheets + their .md in CAP_DIR, packed sheets in V4_DIR.

Pipeline (one generator per board, gen/gen_NN.py, calling gen/frames.py through gen/registry.py):
    frames = [builder(theme) for each §0 frame]  # nested frames in §0's order
    build(nn, frames, blocks)                    # raw sheet (validator exit 0 or raises), md (line 3 = render line),
                                                 # packed sheet (mkcall4 count agrees; compactOf = bare name + sha256)
Self-test: python3 -I -B e19d05kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (U+2215 stands for it); no local path, host
or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side;
every frame has a "state: <id>" caption.
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E19-D05", "E19", 500
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E19/E19-D05.md"


def _repo() -> Path:
    env = os.environ.get("CV_REPO")
    if env:
        if not (Path(env) / _SPEC_PATH).is_file():
            raise SystemExit(f"e19d05kit: CV_REPO has no {_SPEC_PATH}")
        return Path(env).resolve()
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file():
        return up
    raise SystemExit("e19d05kit: run inside a checkout or set CV_REPO to one")


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
# key -> (repo-relative path, md5, commit to read from when the checkout's bytes differ or the file is absent; "" =
# this checkout only: the spec is read where the kit is committed, its §0 and §16 recording the boards as drawn).
# The md5 pins sit apart from the paths (a hex value beside a path is the shape a secret scanner flags).
_PATHS = {
    "spec": _SPEC_PATH,
    "d03": "docs/design/E19/E19-D03.md",
    "d02": "docs/design/E19/E19-D02.md",
    "prim": "packages/ui/tokens/primitives.tokens.json",
    "fixture": "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json",
}
_MD5 = {
    "spec": "6cf5556d912d774a869a38494078f881",
    "d03": "928db4e4b68dafe97694c6ec9a718c7b",
    "d02": "1299df3b853121295e018bed3b819262",
    "prim": "b5e4756938646d98fa8c4ba2d5322b4a",
    "fixture": "edd9dd2a060c51bd4bd1450307728ddf",
}
_AT = {"spec": "", "d03": "35032f521", "d02": "3619e95c5", "prim": "d23ec8bd7", "fixture": "d23ec8bd7"}
DOCS = {k: (_PATHS[k], _MD5[k], _AT[k]) for k in _PATHS}
REV = "r1"
PITCH_X, PITCH_Y = 7600, 5600  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts, URLs and agent part names never belong in a sheet; the words are hex here so this file carries
# none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "636c61756465", "68747470", "7777772e", "2d6f7263686573747261746f72")) + r"|wt/\d|\b"
    + bytes.fromhex("616e76696c").decode() + r"\b", re.I | re.DOTALL)
_SOURCE_NOTE: dict[str, str] = {}


def _doc_bytes(k: str) -> bytes:
    path, md5, commit = DOCS[k]
    f = REPO / path
    if f.is_file() and hashlib.md5(f.read_bytes()).hexdigest() == md5:
        _SOURCE_NOTE[k] = "checkout"
        return f.read_bytes()
    if not commit:
        raise SystemExit(f"e19d05kit: {path} drifted from its md5 {md5[:8]}: re-read, re-check, re-pin")
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e19d05kit: {path} is neither in the checkout at its pin nor readable at {commit}")
    _SOURCE_NOTE[k] = f"git show {commit}"
    return res.stdout


_BYTES = {k: _doc_bytes(k) for k in DOCS}


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_BYTES[k]).hexdigest() == DOCS[k][1] for k in DOCS}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e19d05kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TEXT_DOCS = ("spec", "d03", "d02")
LINES = {k: _COMMENT.sub("", _BYTES[k].decode("utf-8")).split("\n") for k in TEXT_DOCS}
TEXTS = {k: "\n".join(v) for k, v in LINES.items()}
DOC_LABEL = {"spec": "spec", "d03": "D03", "d02": "D02"}
PRIM = json.loads(_BYTES["prim"].decode("utf-8"))


def _cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


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


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("**", "").replace("\\|", "|")).strip()


def _flat(doc: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", TEXTS[doc].replace("\\|", "|"))


_FLAT = {k: _flat(k) for k in TEXTS}
_FLAT_PLAIN = {k: plain(v) for k, v in _FLAT.items()}


def S(chars: str, doc: str | None = None) -> str:
    """A drawn string that must occur verbatim (or verbatim once markdown code / bold marks are dropped) in the spec,
    D03 or D02 (doc names one): returns it."""
    docs = [doc] if doc else list(TEXT_DOCS)
    if not any(chars in _FLAT[d] or chars in _FLAT_PLAIN[d] for d in docs):
        raise LookupError(f"{'/'.join(docs)}: string not in the text: {chars!r}")
    return chars


def SL(chars: str, doc: str | None = None) -> str:
    """'<doc> L<n>': where a verbatim string first stands (after S)."""
    S(chars, doc)
    for d in [doc] if doc else list(TEXT_DOCS):
        if chars in _FLAT[d] or chars in _FLAT_PLAIN[d]:
            for n in (len(chars), 40, 20, 10):
                for i, ln in enumerate(LINES[d], 1):
                    if chars[:n] in ln.replace("\\|", "|") or chars[:n] in plain(ln):
                        return f"{DOC_LABEL[d]} L{i}"
    raise LookupError(chars)


# --- §0: the ten boards (parsed) -------------------------------------------------------------------------------------
_H0 = L("## 0. Status and the boards")
_S0 = " ".join(LINES["spec"][_H0:_H0 + 4])
FILE_NAME = re.search(r"Penpot file `([^`]+)`", _S0).group(1)  # type: ignore[union-attr]
PAGE = re.search(r"page `([^`]+)`", _S0).group(1)  # type: ignore[union-attr]
# kit reading R-K1: §0 names no export path; the kit takes the merged motion specs' form (E08-D11 §0:
# docs/design/<EPIC>/img/<KEY>-NN-<slug>.png)
EXPORT_PATTERN = f"docs/design/{EPIC}/img/{KEY}-NN-<slug>.png"
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**", _H0)
NOT_DRAWN = tuple(re.findall(r"`(SCR-03[89]/[a-z0-9-]+)`", " ".join(LINES["spec"][NOT_DRAWN_LINE - 1:NOT_DRAWN_LINE + 2])))
NOT_DRAWN_HC = plain(re.search(r"(and every high-contrast strip \([^)]*\))",
                               _FLAT["spec"]).group(1))  # type: ignore[union-attr]


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E19-D05 / 01 case-table" (§0 verbatim)
    slug: str
    cell: str  # §0's Frames cell, plain
    theme: str  # "dark" | "light" (a "dark + light twin" board renders under the light set, kit reading R-K2)
    twin: bool
    line: int
    frames: tuple[str, ...]

    @property
    def export(self) -> str:
        return EXPORT_PATTERN.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def mixed(self) -> bool:
        """A light twin that also nests a '-dark' frame: exported once per theme (kit reading R-K2)."""
        return self.twin and any(f.endswith("-dark") for f in self.frames)

    @property
    def export_dark(self) -> str:
        return self.export.replace(".png", "-dark.png")


def _boards() -> dict[int, Board]:
    out: dict[int, Board] = {}
    for i in range(_H0 + 2, NOT_DRAWN_LINE):
        ln = LINES["spec"][i - 1]
        if not re.match(r"^\| \d{2} ", ln):
            continue
        c = _cells(ln)
        nn = int(c[0])
        m = re.fullmatch(rf"`({re.escape(KEY)} / {nn:02d} ([a-z0-9-]+))`", c[1])
        if not m or not (plain(c[4]) == "PENDING" or c[4].startswith("drawn: board id ")):
            raise ValueError(f"§0 L{i}: board cell {c[1]!r} / state {c[4]!r}")
        shots = tuple(re.findall(r"`(SCR-03[89]/[a-z0-9-]+)`", c[2]))
        th = plain(c[3])
        if th not in ("dark", "dark + light twin"):
            raise ValueError(f"§0 L{i}: theme {th!r}")
        twin = th == "dark + light twin"
        out[nn] = Board(nn, m.group(1), m.group(2), plain(c[2]), "light" if twin else "dark", twin, i, shots)
    return out


BOARDS = _boards()


def frame_theme(fid: str, board_theme: str) -> str:
    """A frame's own theme: its id's '-dark' / '-light' suffix, else the board's."""
    m = re.search(r"-(dark|light)$", fid)
    return m.group(1) if m else board_theme


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# --- tokens (exact names in token-sync.json; the self-test checks every one) -----------------------------------------
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
OVERLAY_SURF = "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
P_BAR, P_POC, P_VA = "color.profile.bar", "color.profile.poc", "color.profile.valuearea"
STALE_SURFACE = "color.data-confidence.stale.surface"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM_XS, NUM_SM = "type.num.xs", "type.num.sm"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
ICON_SM, ICON = "size.icon.sm", "size.icon"
R_CONTROL, R_CARD = "radius.control", "radius.card"
HAIR, THICK = "border.hairline", "border.thick"
SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, ICON_SM: 12, ICON: 16}
NEVER = ("color.text.disabled", "opacity.disabled")  # §1.4 G-T2.2 / E09-D09 §2.1: never bound by this kit
FALLBACKS = {
    "alpha": "kit stand-in: the renderer binds opacity only to a token and no token carries a key frame's computed "
             "opacity (R-3 adds none), so a shape between 0 and 1 is drawn as its outline (1 px border.hairline in "
             "its ink, no fill) and its opacity, computed from PRIM's easing at that time, is written in the key "
             "frame's caption; 1 is drawn solid and 0 is not drawn",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs",
    "scrim": "opacity.scrim is a Tier-1 primitive (validator WARN); only the CMP-078 stale shade of the contrast case "
             "uses it",
    "hidden": "kit choice: a string a screen reader hears (a polite announcement) is drawn for the board as caption "
              "text in a bordered 'visually hidden' box (not on screen in the product)",
    "marker": "kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a "
              "specimen, a timeline or a measurement, never product UI",
    "crop": "kit choice: a key frame is a crop of the docked CMP-183 panel (280 px wide, D03's width): a header strip "
            "(D02 W-1 and the state word), the plot and the CMP-199 legend's words; D03's controls rows are "
            "unchanged by this spec and not repeated",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}

HEADING_LG = "type.ui.heading-lg"
NUM, NUM_MD, NUM_LG, NUM_XL = "type.num.base", "type.num.md", "type.num.lg", "type.num.xl"

# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "readings", "spec_gaps", "fallbacks", "tokens", "live_checks",
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
    """A drawn string no source words (a kit choice or a neutral placeholder): say where it comes from."""
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
    o.wrap, a NEVER token and a banned string in the name, note or chars. Records bound tokens."""
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
            if tk in NEVER:
                raise ValueError(f"{name!r}: {tk} is never bound (§1.4 G-T2.2; E09-D09 §2.1)")
            NOTES.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1, **kw: Any) -> Node:
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
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


# --- text metrics (estimates; Inter / JetBrains Mono at the type tokens' sizes)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM_XS: (10, 1.2, True), NUM_SM: (11, 1.2, True),
         NUM: (13, 1.2, True), NUM_MD: (14, 1.2, True), HEADING_LG: (20, 1.2, False), NUM_LG: (16, 1.2, True),
         NUM_XL: (20, 1.2, True)}
MONO_ADVANCE = Decimal("0.6")  # em (D04E11:196, §6.1)


def text_w(chars: str, typo: str, scale: float = 1.0) -> float:
    size, _lh, mono = _FONT.get(typo, _FONT[BODY])
    return round(len(chars) * (0.6 if mono else 0.56) * size * scale, 1)


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




# --- the copy decks (parsed): spec §8.3 (W-1, W-1b, W-2 and the cited D03 / D02 rows), D03 §13, D02 §12 ------
def _deck(doc: str, head: str, key_re: str = r"W-\d+") -> dict[str, tuple[list[str], int]]:
    a = find_line(head, doc)
    out: dict[str, tuple[list[str], int]] = {}
    for i in range(a + 1, len(LINES[doc]) + 1):
        ln = LINES[doc][i - 1]
        if ln.startswith("#") and i > a + 1:
            break
        m = re.match(rf"^\| ({key_re}) +\| (.*?) +\| ", ln)
        if m:
            out[m.group(1).removeprefix("D05 ")] = (re.findall(r'"([^"]+)"', m.group(2)), i)
    return out


DECK = {"spec": _deck("spec", "### 8.3 Copy deck", r"(?:D0[235] )?W-\d+[ab]?"),
        "d03": _deck("d03", "## 13. Copy deck (W-n)"), "d02": _deck("d02", "## 12. Copy deck (W-n)")}


def W(key: str, alt: int = 0, *, doc: str = "spec", **subs: str) -> str:
    """The copy-deck string `key` (spec keys: "W-1", "W-1b", "W-2", "D03 W-10", …; doc="d03"/"d02": that deck's
    "W-n"), alternative alt, its {placeholders} filled from the world; every placeholder must be filled."""
    strings, ln = DECK[doc][key]
    s = strings[alt]
    for a, b in subs.items():
        if "{" + a + "}" not in s:
            raise ValueError(f"{doc} {key} {s!r}: no placeholder {{{a}}}")
        s = s.replace("{" + a + "}", b)
    if re.search(r"\{[^}]+\}", s):
        raise ValueError(f"{doc} {key}: unfilled placeholder in {s!r}")
    who = {"spec": "", "d03": "D03 ", "d02": "D02 "}[doc]
    copy_key(f"{who}{key}: \"{strings[alt]}\" ({DOC_LABEL[doc]} L{ln})" + (" filled from the world" if subs else ""))
    return s


def tpl(example: str, subs: dict[str, str], doc: str | None = None) -> str:
    """A source example re-filled with this frame's derived values: the example must occur verbatim."""
    S(example, doc)
    out = example
    for a, b in subs.items():
        if a not in out:
            raise ValueError(f"{a!r} not in {example!r}")
        out = out.replace(a, b)
    if out != example:
        derive(f'"{out}": the example "{example}" ({SL(example, doc)}) with this frame\'s values')
    return out


# --- spec tables (parsed, never typed) -------------------------------------------------------------------------------
def table_after(head: str, doc: str = "spec") -> tuple[list[str], list[list[str]], int]:
    """The first markdown table after the heading line `head`: (header cells, body rows, first body line)."""
    a = find_line(head, doc)
    ls = LINES[doc]
    i = a
    while not ls[i].startswith("|"):
        i += 1
    hdr = _cells(ls[i])
    rows, j = [], i + 2
    while j < len(ls) and ls[j].startswith("|"):
        rows.append(_cells(ls[j]))
        j += 1
    return hdr, rows, i + 3


CASE_HDR, CASE_ROWS, CASE_LINE = table_after("## 2. The motion table (AC 1)")
MATRIX_HDR, MATRIX_ROWS, MATRIX_LINE = table_after("## 3. The suppression matrix (AC 3, AC 6)")
CADENCE_HDR, CADENCE_ROWS, CADENCE_LINE = table_after("### 4.1 Cadence")
THRESH_HDR, THRESH_ROWS, THRESH_LINE = table_after("### 4.2 The threshold T_rows (AC 3)")
FLASH_HDR, FLASH_ROWS, FLASH_LINE = table_after("### 8.1 Flash audit")
CASES = {r[0]: dict(zip(CASE_HDR, r)) for r in CASE_ROWS}
MATRIX = {r[0]: dict(zip(MATRIX_HDR, r)) for r in MATRIX_ROWS}


def _num(cell: str) -> Decimal:
    return Decimal(re.match(r"[\d  ]*[\d.]+", plain(cell)).group(0).replace(" ", "").replace(" ", ""))  # type: ignore


THRESH = {plain(r[0]): r for r in THRESH_ROWS}
BUDGET_MS = _num(THRESH["Input and animations per frame"][1])
SHARE_MS = _num(THRESH["Profile motion share of it"][1])
COST_US = _num(THRESH["Planning cost per eased row"][1])
T_ROWS = int((SHARE_MS * 1000) // COST_US)  # ⌊share ÷ cost⌋ (§4.2): derived, then checked against the spec's cell
WORST_ROWS = int(_num(THRESH["Worst case rows before the merge"][1]))
BYTES_PER_INSTANCE = 4  # "(4 B per instance)", §4.2's row label
THROTTLES = [int(_num(r[0])) for r in CADENCE_ROWS]  # 1 000 (default), 250 (a request), 50 (the floor)
DEFAULT_THROTTLE_MS = THROTTLES[0]
HS1_GAP_MS = 500  # R-5 / E05-D03:105 (checked against the spec text by the self-test)
HS1_QUIET_S = 10  # R-5: "changing at ≥ 1 Hz for 10 s"
BUSY_DELAY_MS = 300  # §6.1 (PROPOSED; checked against the spec text)
DEBOUNCE_MS = 100  # C-4: `14`:1013 "debounce 100 ms" (checked against the spec text)
PAN_HZ = 10  # §6.2: "≤ 10 Hz"
LANE_TRACE, LANE_BRACKET = 4, 8  # §5.1 "4 px wide", §5.2 "8 px lane" (PROPOSED)
PEAK = Decimal("0.25")  # §5.1 / §5.2 "0.25 → 0"
REGION_W, REGION_H, AREA_CAP, MR1 = 341, 256, 21824, 3  # §8.1 (HS-1b, MR-1), checked against the spec text
COMBINED_CAP = 3  # R-5's combined cap


# --- motion primitives (PRIM, pinned) --------------------------------------------------------------------------------
DUR = {n.rsplit(".", 1)[1]: int(str(v["$value"]).removesuffix("ms")) for n, v in PRIM.items()
       if n.startswith("motion.duration.")}
EASE = {n.rsplit(".", 1)[1]: tuple(float(x) for x in v["$value"]) for n, v in PRIM.items()
        if n.startswith("motion.easing.")}
FPS = 60


def frames_at_60(ms: float) -> int:
    return round(ms * FPS / 1000)


def ease(name: str, p: float) -> float:
    """The cubic-bezier easing `motion.easing.<name>` at progress p in [0, 1] (bisection on x, then y)."""
    x1, y1, x2, y2 = EASE[name]

    def bz(s: float, a: float, b: float) -> float:
        return 3 * (1 - s) ** 2 * s * a + 3 * (1 - s) * s ** 2 * b + s ** 3

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if bz(mid, x1, x2) < p:
            lo = mid
        else:
            hi = mid
    return bz((lo + hi) / 2, y1, y2)


@dataclass(frozen=True)
class Key:
    """One key frame of a token entry: §0's 'frame 0, the middle of the token duration and the end'."""
    word: str  # "frame 0" | "middle" | "end"
    t_ms: int
    progress: float  # eased progress 0 -> 1


def keyframes(duration: str, easing: str) -> list[Key]:
    d = DUR[duration]
    return [Key("frame 0", 0, 0.0), Key("middle", d // 2, ease(easing, 0.5)), Key("end", d, 1.0)]


def lerp(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def fmt_alpha(a: float) -> str:
    return f"{a:.2f}".rstrip("0").rstrip(".") if a not in (0, 1) else str(int(a))


# --- the synthetic world (seed 500, the issue number and §9's prototype seed; declared synthetic on every board) ----
UTC = timezone.utc
SEED = ISSUE
SYMBOL = "BTCUSDT"


def _fixture() -> tuple[Decimal, Decimal]:
    for it in json.loads(_BYTES["fixture"].decode("utf-8"))["result"]["list"]:
        if it["symbol"] == SYMBOL:
            return Decimal(it["priceFilter"]["tickSize"]), Decimal(it["lotSizeFilter"]["qtyStep"])
    raise SystemExit(f"e19d05kit: {SYMBOL} not in the instrument fixture")


TICK, QTY_STEP = _fixture()
PRICE_DP = max(0, -TICK.normalize().as_tuple().exponent)  # type: ignore[operator]
QTY_DP = max(0, -QTY_STEP.normalize().as_tuple().exponent)  # type: ignore[operator]
FINE = 10  # ticks per fine bucket (1.0 USDT): the world's volume grain; 1-tick rows split it (FINE_SPLIT)
P30 = timedelta(minutes=30)
DAY_LIVE = datetime(2026, 10, 31, tzinfo=UTC)  # the live session
DAY0 = DAY_LIVE - timedelta(days=20)  # D03's naked-POC lookback, 20 sessions (`24`)
LIVE_BAR = DAY_LIVE + timedelta(hours=14, minutes=30)  # the bar in progress
U0 = LIVE_BAR + timedelta(minutes=11)  # 14:41:00 UTC: the update the live frames start from
ROW_TICKS = 100  # the panel's row size (10.0 USDT), D03's kit world
ROW_TICKS_NEW = 50  # board 06: the row size the re-bucket changes to (kit choice)
VA_PCT = 70  # `22` default, the legend's "VA 70 %"
NPOC_N = 5  # D03 §5: the cap's default N (PROPOSED there)
START_PX = 60000.0
DRIFT = 140.0  # USDT a day (up): earlier sessions' POCs lie below the price, mostly naked


def qt(v: float | Decimal) -> int:
    """A price in USDT to integer ticks (round half even)."""
    return int((Decimal(str(v)) / TICK).to_integral_value(rounding=ROUND_HALF_EVEN))


@dataclass
class Bar:
    start: datetime
    o: int  # ticks
    h: int
    l: int  # noqa: E741
    c: int
    fine: dict[int, int] = field(default_factory=dict)  # fine bucket index -> qty steps


def _fill(b: Bar, rng: random.Random, vol: int) -> None:
    """Spread vol qty steps over the bar's fine buckets: a triangle peaking between open and close, seeded noise."""
    lo, hi = b.l // FINE, b.h // FINE
    peak = (b.o + b.c) / 2 / FINE
    span = max(hi - lo, 1)
    w = {i: max(0.05, 1 - abs(i - peak) / span) * (0.4 + rng.random()) for i in range(lo, hi + 1)}
    tot = sum(w.values())
    for i, x in w.items():
        q = int(vol * x / tot)
        if q:
            b.fine[i] = b.fine.get(i, 0) + q


def _bars() -> list[Bar]:
    rng = random.Random(SEED)
    out: list[Bar] = []
    px, d = START_PX, DAY0
    while d <= DAY_LIVE:
        for p in range(48):
            s = d + p * P30
            if s > LIVE_BAR:
                break
            o = px
            c = o + DRIFT / 48 + rng.gauss(0, 34)
            hi, lo = max(o, c) + abs(rng.gauss(0, 22)), min(o, c) - abs(rng.gauss(0, 22))
            b = Bar(s, qt(o), qt(hi), qt(lo), qt(c))
            _fill(b, rng, rng.randint(20000, 80000) + (30000 if 13 <= s.hour < 17 else 0))
            out.append(b)
            px = c
        d += timedelta(days=1)
    return out


BARS = _bars()
LIVE = BARS[-1]  # the bar in progress at U0 (its prints so far)


def bars_between(a: datetime, b: datetime) -> list[Bar]:
    return [x for x in BARS if a <= x.start < b]


def merge_fine(bars: Iterable[Bar], extra: dict[int, int] | None = None) -> dict[int, int]:
    out: dict[int, int] = {}
    for b in bars:
        for i, q in b.fine.items():
            out[i] = out.get(i, 0) + q
    for i, q in (extra or {}).items():
        out[i] = out.get(i, 0) + q
    return out


def _split(i: int, q: int) -> dict[int, int]:
    """FINE_SPLIT: a fine bucket's qty over its 10 ticks, seeded by the bucket index (1-tick rows only)."""
    r = random.Random(SEED * 100003 + i)
    w = [0.3 + r.random() for _ in range(FINE)]
    tot = sum(w)
    parts = [int(q * x / tot) for x in w]
    parts[0] += q - sum(parts)
    return {i * FINE + j: v for j, v in enumerate(parts) if v}


@dataclass
class Profile:
    label: str
    row_ticks: int
    levels: dict[int, int]  # row -> qty steps
    vwap_ticks: Decimal
    last_ticks: int
    complete: bool = False
    poc: int = 0
    va: tuple[int, int] = (0, 0)

    def price(self, r: int) -> Decimal:
        """A row's price: its lower boundary (`24`:987)."""
        return r * self.row_ticks * TICK

    def vol(self, r: int) -> int:
        return self.levels.get(r, 0)

    @property
    def total(self) -> int:
        return sum(self.levels.values())

    @property
    def max_vol(self) -> int:
        return max(self.levels.values())


def build_profile(label: str, fine: dict[int, int], *, row_ticks: int = ROW_TICKS, last_ticks: int,
                  complete: bool = False) -> Profile:
    """`24` §4.5: rows of row_ticks; POC = max volume, ties by closeness to the period VWAP, then to the last price, then
    the lower price (`24`:1009); the value area by the single-step expansion to VA_PCT (ties absorb both sides)."""
    levels: dict[int, int] = {}
    num = Decimal(0)
    for i, q in fine.items():
        num += Decimal(i * FINE + FINE // 2) * q
        if row_ticks % FINE == 0:
            r = i * FINE // row_ticks
            levels[r] = levels.get(r, 0) + q
        else:
            for t, v in _split(i, q).items():
                levels[t // row_ticks] = levels.get(t // row_ticks, 0) + v
    pr = Profile(label, row_ticks, levels, num / sum(fine.values()), last_ticks, complete)
    top = pr.max_vol
    mid = Decimal(row_ticks - 1) / 2
    pr.poc = min((r for r, v in levels.items() if v == top),
                 key=lambda r: (abs(r * row_ticks + mid - pr.vwap_ticks), abs(r * row_ticks + mid - last_ticks), r))
    lo = hi = pr.poc
    got, need = levels[pr.poc], Decimal(pr.total) * VA_PCT / 100
    rmin, rmax = min(levels), max(levels)
    while got < need:
        up = pr.vol(hi + 1) if hi < rmax else None
        dn = pr.vol(lo - 1) if lo > rmin else None
        if up is not None and (dn is None or up >= dn):
            hi += 1
            got += up
        if dn is not None and (up is None or dn >= up):
            lo -= 1
            got += dn
    pr.va = (lo, hi)
    return pr


def session_profile(day: datetime, until: datetime, extra: dict[int, int] | None = None, *, row_ticks: int = ROW_TICKS,
                    last: int | None = None, complete: bool = False, label: str = "Session") -> Profile:
    bs = bars_between(day, until)
    return build_profile(label, merge_fine(bs, extra), row_ticks=row_ticks, last_ticks=last if last is not None
                         else bs[-1].c, complete=complete)


# --- the scenarios (each derived from the world; the frames draw them) -----------------------------------------------
def _burst(row: int, row_ticks: int, qty: int, rng: random.Random) -> dict[int, int]:
    """qty qty-steps printed over the fine buckets of one row (seeded split)."""
    lo = row * row_ticks // FINE
    n = max(1, row_ticks // FINE)
    w = [0.5 + rng.random() for _ in range(n)]
    parts = [int(qty * x / sum(w)) for x in w]
    parts[0] += qty - sum(parts)
    return {lo + j: v for j, v in enumerate(parts) if v}


def _add(a: dict[int, int], b: dict[int, int]) -> dict[int, int]:
    out = dict(a)
    for i, q in b.items():
        out[i] = out.get(i, 0) + q
    return out


JUMP_ROWS = 3  # board 02: the multi-level jump, kit choice (§5.1 asks ≥ 2 rows)
BASE = merge_fine(bars_between(DAY_LIVE, DAY_LIVE + timedelta(days=1)))  # the live session at U0


@dataclass
class PocJump:
    p0: Profile
    p1: Profile  # U1: the jump (JUMP_ROWS)
    p2: Profile  # U2: the 1-row move (a cut)
    burst1: int
    burst2: int


def _poc_jump() -> PocJump:
    rng = random.Random(SEED + 2)
    p0 = build_profile("Session", BASE, last_ticks=LIVE.c)
    t1 = p0.poc + JUMP_ROWS
    q1 = p0.max_vol - p0.vol(t1) + rng.randint(800, 1600)
    f1 = _add(BASE, _burst(t1, ROW_TICKS, q1, rng))
    p1 = build_profile("Session", f1, last_ticks=t1 * ROW_TICKS + ROW_TICKS // 2)
    t2 = t1 + 1
    q2 = p1.max_vol - p1.vol(t2) + rng.randint(800, 1600)
    p2 = build_profile("Session", _add(f1, _burst(t2, ROW_TICKS, q2, rng)), last_ticks=t2 * ROW_TICKS + 20)
    return PocJump(p0, p1, p2, q1, q2)


JUMP = _poc_jump()
U1, U2 = U0 + timedelta(milliseconds=DEFAULT_THROTTLE_MS), U0 + timedelta(milliseconds=2 * DEFAULT_THROTTLE_MS)

# board 03: the 30 Oct session closes at 31 Oct 00:00 UTC; its last developing recompute is as of 23:59 (one per 60 s
# by default, `24`:1019); the final minute's prints are a seeded 1/30 of the last bar's, removed from the developing one
CLOSE_DAY = DAY_LIVE - timedelta(days=1)
_LAST30 = bars_between(CLOSE_DAY, DAY_LIVE)
_FINAL_MIN = {i: q // 30 for i, q in _LAST30[-1].fine.items() if q // 30}
DEV_AT = DAY_LIVE - timedelta(minutes=1)
FINAL = build_profile("Session", merge_fine(_LAST30), last_ticks=_LAST30[-1].c, complete=True)
DEV_LAST = build_profile("Session", {i: q - _FINAL_MIN.get(i, 0) for i, q in merge_fine(_LAST30).items()},
                         last_ticks=_LAST30[-1].c)


@dataclass
class Growth:
    row_ticks: int
    rows: int  # visible rows
    window: tuple[int, int]  # [lo, hi) rows
    p0: Profile
    p1: Profile
    changed: list[int]  # rows whose value changed


def _growth_prints() -> dict[int, int]:
    """The prints between U0 and U1 (1 000 ms): seeded sizes in the live bar's range near the last price."""
    rng = random.Random(SEED + 4)
    c = LIVE.c // FINE
    return {c + d: rng.randint(40, 260) for d in sorted(rng.sample(range(-6, 7), 6))}


GROWTH_PRINTS = _growth_prints()


def _growth(row_ticks: int, rows: int) -> Growth:
    p0 = build_profile("Session", BASE, row_ticks=row_ticks, last_ticks=LIVE.c)
    p1 = build_profile("Session", _add(BASE, GROWTH_PRINTS), row_ticks=row_ticks, last_ticks=LIVE.c)
    lo = LIVE.c // row_ticks - rows // 2  # the window is centred on the last price (the prints land there)
    changed = sorted(r for r in set(p0.levels) | set(p1.levels) if p0.vol(r) != p1.vol(r))
    return Growth(row_ticks, rows, (lo, lo + rows), p0, p1, changed)


G120 = _growth(FINE, T_ROWS)  # 120 rows of 10 ticks (1.0 USDT)
G5000 = _growth(1, WORST_ROWS)  # 5 000 rows of 1 tick

# board 05: two developing recomputes of the live session 60 s apart (as of 14:41 and 14:42); the minute's prints are
# a seeded run just under the value area (price dips one row below VAL), the smallest that moves the area (derived)
VA_AT0, VA_AT1 = U0, U0 + timedelta(minutes=1)


def _va_minute() -> tuple[Profile, Profile]:
    rng = random.Random(SEED + 5)
    p0 = build_profile("Session", BASE, last_ticks=LIVE.c)
    step, row = rng.randint(1500, 2500), p0.va[0] - 1
    for n in range(1, 200):  # the smallest multiple of a seeded step that moves the area
        f = _add(BASE, _burst(row, ROW_TICKS, n * step, random.Random(SEED + 50)))
        p1 = build_profile("Session", f, last_ticks=row * ROW_TICKS + 40)
        if p1.va != p0.va and p1.poc == p0.poc:
            return p0, p1
    raise RuntimeError(f"board 05: no minute of prints moves the value area {p0.va}")


VA0, VA1 = _va_minute()

# board 05: HS-1 on a tied POC. A requested 250 ms throttle (§4.1's second row); two levels JUMP_ROWS - 1 = 2 rows
# apart tie and alternate as the POC on every update for TIE_SECONDS, then the tape goes quiet
TIE_THROTTLE_MS = THROTTLES[1]
TIE_SECONDS = 12
TIE_ROWS = (JUMP.p0.poc, JUMP.p0.poc + 2)


@dataclass(frozen=True)
class TieEvent:
    t_ms: int
    row: int
    band: bool
    why: str


def tie_timeline() -> list[TieEvent]:
    """R-5 / HS-1 per update: a band starts only if ≥ HS1_GAP_MS since the last start and the POC has not been
    changing at ≥ 1 Hz for HS1_QUIET_S; the latest update wins and nothing queues; W-1 updates on every move."""
    out, last_start, since = [], -10 ** 9, 0
    for i, t in enumerate(range(0, TIE_SECONDS * 1000, TIE_THROTTLE_MS)):
        row = TIE_ROWS[(i + 1) % 2]
        if t - since >= HS1_QUIET_S * 1000:
            out.append(TieEvent(t, row, False, "quiet rule"))
        elif t - last_start >= HS1_GAP_MS:
            out.append(TieEvent(t, row, True, "start"))
            last_start = t
        else:
            out.append(TieEvent(t, row, False, "gap"))
    return out


TIE = tie_timeline()


def starts_in_any_second(ts: list[int]) -> int:
    """The most starts in any half-open 1 000 ms window."""
    return max((sum(1 for u in ts if t <= u < t + 1000) for t in ts), default=0)


# board 06: re-bucket 100 -> 50 ticks and a period change Session -> Fixed range (the last 240 minutes, D03's kit
# choice); each recompute lands RESULT_MS after the action (synthetic; > BUSY_DELAY_MS so the busy bar shows)
RESULT_MS = 600
FIXED_MIN = 240
P100 = JUMP.p0
P50 = build_profile("Session", BASE, row_ticks=ROW_TICKS_NEW, last_ticks=LIVE.c)
FIXED = build_profile("Fixed range", merge_fine(bars_between(U0 - timedelta(minutes=FIXED_MIN + 11), U0)),
                      last_ticks=LIVE.c)

# board 07: a drag pan of the chart's visible range: VIS_N bars visible, one bar further back per pointer step; the
# throttled recompute (≤ PAN_HZ) at 0, 100, 200, 300 ms, the pointer released at PAN_END_MS, the debounce's recompute
# DEBOUNCE_MS later (the price scale is unchanged by a time pan, so the panel's rows stay put)
VIS_N = 24
PAN_STEPS = (0, 100, 200, 300)
PAN_END_MS = 350
_LIVE_BARS = bars_between(DAY_LIVE, DAY_LIVE + timedelta(days=1))


def visible_profile(shift: int) -> Profile:
    bs = _LIVE_BARS[len(_LIVE_BARS) - VIS_N - shift:len(_LIVE_BARS) - shift]
    return build_profile("Visible range", merge_fine(bs), last_ticks=bs[-1].c)


PAN = {t: visible_profile(i) for i, t in enumerate(PAN_STEPS)}
SETTLED = visible_profile(len(PAN_STEPS))


# board 08: naked POCs of the 20 earlier sessions (untested by any later bar up to U0); the nearest NPOC_N drawn, the
# rest counted by D03 W-2; at the live bar's close (15:00 UTC) its run down reaches the nearest naked POC below
# the price (a seeded print run, kit construction) and retests it
@dataclass(frozen=True)
class NakedPoc:
    day: datetime
    row: int


def _naked() -> list[NakedPoc]:
    out = []
    for i in range(20):
        d = DAY0 + timedelta(days=i)
        p = build_profile("Session", merge_fine(bars_between(d, d + timedelta(days=1))), complete=True,
                          last_ticks=bars_between(d, d + timedelta(days=1))[-1].c)
        lo, hi = p.poc * ROW_TICKS, p.poc * ROW_TICKS + ROW_TICKS - 1
        if not any(b.l <= hi and b.h >= lo for b in BARS if b.start >= d + timedelta(days=1)):
            out.append(NakedPoc(d, p.poc))
    return sorted(out, key=lambda n: (abs(n.row * ROW_TICKS - LIVE.c), n.day))


NAKED = _naked()
RETEST = next(n for n in NAKED[:NPOC_N] if n.row * ROW_TICKS < LIVE.c)
NEAREST_BEFORE = NAKED[:NPOC_N]
NEAREST_AFTER = [n for n in NAKED if n != RETEST][:NPOC_N]
HIDDEN_BEFORE, HIDDEN_AFTER = len(NAKED) - NPOC_N, len(NAKED) - 1 - NPOC_N
BAR_CLOSE = LIVE_BAR + P30


def _run_down() -> dict[int, int]:
    rng = random.Random(SEED + 8)
    top = LIVE.l // FINE
    return {i: rng.randint(60, 400) for i in range(RETEST.row * ROW_TICKS // FINE, top)}


AT_CLOSE = build_profile("Session", _add(BASE, _run_down()), last_ticks=RETEST.row * ROW_TICKS + 30)


# board 10: the flash steps re-derived from token-sync.json with the checkout's contrast_check.relative_luminance()
# (the spec's figures are the audit tool's; the self-test checks the kit's agree to 3 places)
def _contrast_module() -> Any:
    import importlib.util  # noqa: PLC0415
    spec_ = importlib.util.spec_from_file_location("contrast_check", REPO / "docs/design/_tools/contrast_check.py")
    mod = importlib.util.module_from_spec(spec_)  # type: ignore[arg-type]
    spec_.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_TS = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
THEME_SETS = {"dark": ("semantic-dark",), "light": ("semantic-dark", "semantic-light"),
              "high-contrast": ("semantic-dark", "semantic-hc")}


def resolve(theme: str, name: str) -> str:
    table = {r[1]: r[3] for r in _TS if r[0] == "primitives"}
    for part in THEME_SETS[theme]:
        table.update({r[1]: r[3] for r in _TS if r[0] == part})
    v, seen = table[name], set()
    while v.startswith("{"):
        if v in seen:
            raise ValueError(f"alias loop at {name}")
        seen.add(v)
        v = table[v[1:-1]]
    return v


def flash_step(theme: str, token: str, alpha: float) -> float:
    rgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))  # noqa: E731
    fg, bg = rgb(resolve(theme, token)), rgb(resolve(theme, CANVAS))
    peak = tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg))
    lum = _contrast_module().relative_luminance
    return abs(float(lum(peak)) - float(lum(bg)))


# board 10: the one polite region (R-7, D02 R-4): ≤ 1 per 2 s, the latest wins, nothing queues behind it
REGION_GAP_MS = 2000
@dataclass(frozen=True)
class Say:
    t_ms: int
    words: str
    src: str


def region(events: list[Say]) -> list[tuple[Say, int | None]]:
    """Each event with the time it is spoken, or None when a later event replaced it while it waited."""
    out: list[tuple[Say, int | None]] = []
    last_spoken: int | None = None
    pending: Say | None = None
    evs = sorted(events, key=lambda e: e.t_ms)
    i = 0
    while i < len(evs) or pending:
        due = (last_spoken + REGION_GAP_MS) if last_spoken is not None else -1
        nxt = evs[i].t_ms if i < len(evs) else None
        if pending and (nxt is None or due <= nxt):
            out.append((pending, max(due, pending.t_ms)))
            last_spoken, pending = max(due, pending.t_ms), None
            continue
        e = evs[i]
        i += 1
        if pending:
            out.append((pending, None))
        if last_spoken is None or e.t_ms >= last_spoken + REGION_GAP_MS:
            out.append((e, e.t_ms))
            last_spoken, pending = e.t_ms, None
        else:
            pending = e
    return out


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


def chunk(n: Node, budget: int = SECTION_RAW_BUDGET - 1200) -> Node:
    """Wrap the kids of a large non-flex board into full-size 'group NN' boards (x 0, y 0, the parent's w and h, no
    fill) of at most `budget` raw bytes each, so the packer emits one section per group instead of one per shape;
    positions are unchanged (the groups sit at the parent's origin). Flex boards are never regrouped."""
    if n["t"] != "board" or not n.get("kids"):
        return n
    kids = [chunk(c, budget) for c in n["kids"]]
    m = dict(n, kids=kids)
    if (n.get("o") or {}).get("dir") or len(json.dumps(m)) <= budget or len(kids) < 8:
        return m
    groups: list[list[Node]] = [[]]
    for c in kids:
        if groups[-1] and len(json.dumps(groups[-1] + [c])) > budget:
            groups.append([])
        groups[-1].append(c)
    if len(groups) == 1:
        return m
    m["kids"] = [{"t": "board", "name": f"group {i:02d}", "w": n["w"], "h": n["h"], "x": 0, "y": 0,
                  "kids": g} for i, g in enumerate(groups, 1)]
    return m


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
            if (x["t"] == "board" and re.search(r"/(header row|row ·[^/]*)/[^/]+$", p) and "padX" in (x.get("o") or {})
                    and (x["o"]["padX"] != INSET_SM)):
                bad.append(f"{p}: cell padX {x['o']['padX']} (8 px a side required)")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})


# --- the annotation column (ONE, 400 px, outside the frames) and the board -------------------------------------------
def data_statement() -> str:
    derive(f"world: {SYMBOL} 30-minute bars {DAY0:%d %b} 00:00 – {LIVE_BAR:%d %b %H:%M} UTC (the bar in progress), one "
           f"upward walk seeded {SEED} (the issue number, §9's prototype seed), prices at the fixture's tick {TICK}, "
           f"sizes at its qty step {QTY_STEP}, volume on a {FINE}-tick grain; live updates from {U0:%H:%M:%S} UTC at "
           f"the {DEFAULT_THROTTLE_MS} ms default throttle; row size {ROW_TICKS} ticks unless a frame says otherwise")
    return (f"Data: synthetic only: {SYMBOL} 30-minute bars seeded {SEED}, {DAY0:%d %b} – {LIVE_BAR:%d %b %Y} UTC, live "
            f"updates from {U0:%H:%M:%S} UTC; tick size {TICK} from the recorded instrument fixture; no account, key, "
            f"balance or environment on any frame (§1.5: no DEMO ∕ LIVE surface)")


def frame_block(fid: str, theme: str, size: tuple[int, int], lines: Iterable[str]) -> tuple[str, list[str]]:
    return f"{fid} · {theme}", [f"{size[0]} × {size[1]}"] + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.cell}",
            f"Theme: {'dark + light twin (token-bound; the light set is activated at export, kit reading R-K2)' if b.twin else b.theme}",
            f"Export: {b.export}" + (f"; the '-dark' frame also as {b.export_dark} (R-K2)" if b.mixed else ""),
            f"Strip form (§0 L{L('A motion board is a strip')}): frame 0, the middle of the token duration and the "
            f"end, the reduce strip beneath (reduce is never a twin)",
            f"T2 (§1.4 L{L('### 1.4 T2')}): {S('No control is newly gated here.')} {S('No board of §0 draws it.')}",
            f"C-2.11 (§1.5 L{L('### 1.5 C-2.11')}): {S('No DEMO / LIVE surface is specified here.')}",
            f"Not drawn — the text is binding (§0 L{NOT_DRAWN_LINE}): {', '.join(NOT_DRAWN)}, {NOT_DRAWN_HC}",
            *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


ROW_MAX = 3000  # frames flow left to right in rows no wider than this
# root heights as drawn: max(annotation end, footer end) + 80, read back on the live boards (live-check fold)
LIVE_ROOT_H = {1: 934, 2: 1958, 3: 1502, 4: 1534, 5: 1038, 6: 1886, 7: 1054, 8: 2998, 9: 1302, 10: 918}


def layout(frames: list[Node]) -> list[Node]:
    """Frames left to right, wrapping at ROW_MAX; frames top-aligned in a row; 80 px gutters (the caption sits in the
    gutter above its frame)."""
    out, y, x, row_h = [], MARGIN, MARGIN, 0
    for f in frames:
        if x > MARGIN and x - MARGIN + f["w"] > ROW_MAX:
            x, y, row_h = MARGIN, y + row_h + MARGIN, 0
        out.append(dict(f, x=x, y=y))
        x += f["w"] + MARGIN
        row_h = max(row_h, f["h"])
    return out


def board(nn: int, frames: list[Node], ann: Node, *, strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The root (§0's name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 28 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §0 {want}")
    if "/" in b.name.split(f"{KEY} / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames)
    caps = [text(f"caption {i:02d}", f"state: {f['name'].replace(SLASH, '/')} · "
                 f"{frame_theme(f['name'].replace(SLASH, '/'), b.theme)}", CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28)
            for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
                 w=right - MARGIN)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    est = int(math.ceil((max(bottom + 24 + 28, MARGIN + ah) + MARGIN) / 8) * 8)
    # live-check fold: the drawing lane measured max(annotation end, footer end) + 80 on every root (the estimate ran
    # 18 px over on all ten); the measured height is used, never below the footer end + 80
    h = LIVE_ROOT_H.get(nn, est) if strict else est
    foot_end = bottom + 24 + text_h(CAPTION)  # the data statement's one caption line
    if h < foot_end + MARGIN:
        raise ValueError(f"board {nn:02d}: root h {h} leaves less than {MARGIN} px under the footer (ends {foot_end})")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}, "
         f"the drawn max(annotation end, footer end) + {MARGIN}); raise the root's h to that rule if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, encoding="utf-8",
                         timeout=180, check=False)
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
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.raised) as the {b.theme} value")
    live(f"export {b.export}; record the board id and the PNG size")
    reading("R-K1 (export path): §0 names none; the kit takes the merged motion specs' form "
            f"docs/design/{EPIC}/img/{KEY}-NN-<slug>.png (E08-D11 §0)")
    if b.mixed:
        live(f"kit reading R-K2: export board {nn:02d} a second time under the dark set as {b.export_dark}; its "
             f"'-dark' frame is read from that export, its '-light' frame from {b.export}")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0].rsplit('/', 1)[1]} md5 {DOCS['spec'][1][:8]} in this checkout "
                         f"(§0 L{b.line}; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)")
    for kk in ("d03", "d02"):
        NOTES.add("sources", f"{DOC_LABEL[kk]} {DOCS[kk][0].rsplit('/', 1)[1]} md5 {DOCS[kk][1][:8]} at {DOCS[kk][2]} "
                             f"(read via {_SOURCE_NOTE[kk]}; re-pinned when its PR merges)")
    NOTES.add("sources", f"PRIM {DOCS['prim'][0]} md5 {DOCS['prim'][1][:8]} (motion durations and easings only)")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1][:8]} (tick size and qty step only)")
    sheet = {"board": root, "sections": sections_for([chunk(n) for n in nodes]), "export": b.export,
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
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.cell}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".", "", "## Frames", ""]
    names = {frame_name(f) for f in b.frames}
    tops = {s_["node"]["name"]: (s_["node"]["w"], s_["node"]["h"]) for s_ in sh["sections"]
            if s_["into"] == "" and s_["node"]["name"] in names}
    out += [f"- `{frame_name(f)}` ({frame_theme(f, b.theme)}, {tops[frame_name(f)][0]} x {tops[frame_name(f)][1]})"
            for f in b.frames if frame_name(f) in tops]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "readings", "derivations", "spec_gaps", "deviations", "copy_keys", "copy_gaps",
               "fallbacks", "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if IN_REPO and sp.parent == CAP_DIR.resolve():  # the committed sidecar beside the kit, the same bytes
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
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         encoding="utf-8", timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         encoding="utf-8", timeout=120, check=False)
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
# --- tables (the E08-D10 kit's, copied): cells padded 8 px a side
ROW_H = 24  # compact rows (§12.1)


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
    """The header row, sized from its tallest wrapped th (live-check fold: board 09's 2-line th in a 24 px row): the
    text + 4 px a side, at least ROW_H, rounded up to 8 px; every th takes the row's height."""
    cs = list(cols)

    def th(c: Col, h: int) -> Node:
        return cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=NUM_SM if c.numeric else CAPTION,
                    color=TEXT_3, h=h)

    need = max((est_height(dict(th(c, 1), h=None)) for c in cs), default=0.0) + 8
    h = max(ROW_H, int(math.ceil(need / 8) * 8))
    return hbox("header row", [th(c, h) for c in cs], {"fill": RAISED}, w=sum(c.w for c in cs), h=h,
                note='column headers, scope="col"')


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





# --- self-test: python3 -I -B e19d05kit.py selftest ------------------------------------------------------------------
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources; D03 via {_SOURCE_NOTE['d03']}, D02 via "
          f"{_SOURCE_NOTE['d02']})")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10")
    twins = [b.nn for b in BOARDS.values() if b.twin]
    check(twins == [2, 3, 9] and len(twins) * 3 <= len(BOARDS), f"light twins {twins} <= one third (BQ-13)")
    check([len(BOARDS[n].frames) for n in range(1, 11)] == [1, 2, 2, 2, 2, 3, 2, 3, 2, 2], "frames per board as §0")
    check(not any(f in NOT_DRAWN for b in BOARDS.values() for f in b.frames) and len(NOT_DRAWN) == 7,
          f"no drawn frame is on §0's not-drawn line ({len(NOT_DRAWN)} named + every high-contrast strip)")
    check((FILE_NAME, PAGE) == ("E19-D05 boards", "E19-D05"), f"file {FILE_NAME!r}, page {PAGE!r}")
    check(all("/" not in b.name.split(f"{KEY} / {b.nn:02d} ", 1)[1] for b in BOARDS.values()), "no '/' after the prefix")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture tick {TICK}, qty step {QTY_STEP}")
    check((DUR["fast"], DUR["normal"], DUR["instant"]) == (100, 200, 0), f"PRIM durations {DUR}")
    check(abs(ease("accelerate", 0.0)) < 1e-9 and abs(ease("decelerate", 1.0) - 1) < 1e-9, "easing end points")
    check(T_ROWS == 120 and plain(THRESH["T_rows = ⌊share ÷ cost⌋"][1]) == str(T_ROWS), f"T_rows {T_ROWS} = §4.2's")
    check(plain(THRESH[f"Bytes per frame at T_rows ({BYTES_PER_INSTANCE} B per instance)"][1]) ==
          f"{T_ROWS * BYTES_PER_INSTANCE} B", "§4.2 bytes per frame")
    check(THROTTLES == [1000, 250, 50], f"§4.1 throttles {THROTTLES}")
    for frag in ("≥ 500 ms between starts per element", "still pending after 300 ms", "debounce 100 ms",
                 "≤ 21 824 px²", "341 × 256 px", "4 px wide, PROPOSED", "8 px lane", "0.25 → 0", "≤ 10 Hz"):
        check(frag in _FLAT["spec"] or frag in _FLAT_PLAIN["spec"], f"kit constant's spec text: {frag!r}")
    check(len(CASES) == 10 and len(MATRIX) == 10, "§2 and §3: ten rows each")
    j = JUMP
    check(j.p1.poc - j.p0.poc == JUMP_ROWS >= 2 and j.p2.poc - j.p1.poc == 1, "POC jump: 3 rows, then 1 row")
    check(not DEV_LAST.complete and FINAL.complete, "developing -> final")
    check(G120.rows == T_ROWS and G5000.rows == WORST_ROWS and G120.p0.max_vol == G120.p1.max_vol
          and all(G120.window[0] <= r < G120.window[1] for r in G120.changed), "growth arms: rows, scale max, window")
    check(VA0.va != VA1.va and VA0.poc == VA1.poc, f"developing VA moves {VA0.va} -> {VA1.va}")
    starts = [e.t_ms for e in TIE if e.band]
    check(starts_in_any_second(starts) == int(_num(CADENCE_ROWS[1][3])) and not any(
        e.band for e in TIE if e.t_ms >= HS1_QUIET_S * 1000), "tie: §4.1's starts per second; none after 10 s")
    check(len(NAKED) > NPOC_N and RETEST in NEAREST_BEFORE and HIDDEN_AFTER == HIDDEN_BEFORE - 1,
          f"naked POCs {len(NAKED)}, retest {RETEST.day:%d %b}, hidden {HIDDEN_BEFORE} -> {HIDDEN_AFTER}")
    for r in FLASH_ROWS:
        tok, al = {"M-2 trace": (P_POC, 0.25), "M-4 bracket": (P_VA, 0.25)}.get(plain(r[0]), (P_POC, 1.0))
        got = [f"{flash_step(t, tok, al):.3f}" for t in ("dark", "light", "high-contrast")]
        check(got == [plain(x) for x in r[2:5]], f"§8.1 {plain(r[0])}: ΔL {got}")
    toks = {r[1] for r in _TS}
    used = [v for kk, v in globals().items() if kk.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)]
    check(all(u in toks for u in used if u not in NEVER), "kit tokens exist in token-sync.json")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: S("a string no source says"),
                 lambda: text("x", "y", CAPTION, "color.text.disabled"), lambda: rect("x", 1, 1, P_POC,
                                                                                       {"opacity": "opacity.disabled"})):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', an unworded string and a NEVER token refused")
    sys.path.insert(0, str(KIT_DIR / "gen"))
    import registry  # noqa: PLC0415  (the frame builders import this kit)
    check(set(registry.BUILDERS) == {f for b in BOARDS.values() for f in b.frames}, "a builder for every frame")
    NOTES.reset()
    fid = "SCR-038/developing-va-dark"
    node_, lines = registry.BUILDERS[fid]("dark")
    ann = annotations(5, [frame_block(fid, "dark", (node_["w"], node_["h"]), lines)],
                      board_lines=["Self-test sheet: one frame"])
    path = write_sheet(5, [node_], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(5, path, summary="Self-test sheet (one frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(5) and l3.endswith("theme dark."), f"md line 3: {l3}")
    check(all(md_line3(n).endswith("theme light.") for n in (2, 3, 9)), "md line 3: the light twins")
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
