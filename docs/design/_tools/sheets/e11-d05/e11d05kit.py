"""E11-D05 (#310) ref-frame kit: boards 09 / 10, the 55 per-state ref frames of the chart primitives, as cvsheet JSON.

Offline only (no Penpot, no network). Spec (binding; read with `git show e87194bb0:<path>` in this checkout, the
text the boards cite, md5s pinned in SPEC_MD5):
docs/design/E11/E11-D05.md (§0, §4.1 / §4.1b slots, §6 density, §8 states), E11-D05-handoff.md Table 1 (the frame
names `CMP-nnn · Name — ref frame (<state>)`, one per state, 55 total), E11-D02.md D7-D16 (the state looks),
E11-D04.md §11 / §12.2 (empty and context-loss copy), docs/plan/15-component-catalogue.md (the entries' Tier /
Purpose = the ownership split restated per `16` §10 item 3).

Ruling of record (Q2 / Q3): board 09 `ref-frames-a` (CMP-180 / 188 / 189 / 190, 33 frames) and board 10
`ref-frames-b` (CMP-197 / 198 / 199 / 226, 22 frames), dark only, in the per-set file `E11-D05 ref frames`, page
`E11-D05 ref frames`; the Variants x States products are not drawn (the text is binding).

Pipeline: gen/gen_09.py and gen/gen_10.py build the frames with this kit, then
    p = write_sheet(nn, groups, ann)   # build/NN-<slug>.json, validated (exit 0) or RuntimeError
    write_md(nn, p, ...)                # NN-<slug>.md here and in build/, line 3 = the render drivers' line
    write_post_live(nn, p)              # build/NN-<slug>.post-live.js, the live fold's post-render step
    pack_sheet(p)                       # v4/NN-<slug>.json, compactOf.file = the bare name, sections <= 9 KB

Tokens: every colour binds an existing token. The 18 slot / alias names of §4.1 / §4.1b are not in packages/ui/tokens
yet (they land with #390, E11-T04): a shape that the spec binds to a slot binds the alias target the spec names
(slot() below) and the sheet notes list it as "slot pending #390". Hard checks kept from the E12-D07 kit: no "inst"
node, icons only from ICONS_OK, o.wrap only "wrap" / "nowrap", every flex child without text carries h, no "/" in a
node name, no local path / host / agent name anywhere (BANNED), packed sections <= 9 KB.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
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
CAP_DIR = KIT_DIR / "build"  # the raw sheets (untracked: .gitignore); their .md go to KIT_DIR as well
V4_DIR = KIT_DIR / "v4"  # packed sheets (the renderer's input, committed; compactOf.file = the bare raw name)
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
PACKER = SHEETS_DIR / "tools" / "compact.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
REPO = KIT_DIR.parents[4]  # the checkout's root
BASE = "e87194bb0"  # origin/main when the kit was cut: the boards cite the docs as at this commit (md5-pinned below)


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
                raise SystemExit(f"e11d05kit: git show {BASE}:{self.rel} failed (a full clone of the repository "
                                 f"is needed): {res.stderr.decode(errors='replace').strip()[:200]}")
            self._b = res.stdout
        return self._b

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.read_bytes().decode(encoding)


SPEC = _Doc("docs/design/E11/E11-D05.md")
HANDOFF = _Doc("docs/design/E11/E11-D05-handoff.md")
D02 = _Doc("docs/design/E11/E11-D02.md")
D04 = _Doc("docs/design/E11/E11-D04.md")
CAT = _Doc("docs/plan/15-component-catalogue.md")
SPEC_MD5 = {SPEC.name: "6575db497fdaa3e7aa46a5a7f894eefe", HANDOFF.name: "1f2def41cf0694387cfa28b9f9e3f315",
            D02.name: "c42ae3853ca684c2cc3fabfe3dd9e89a", D04.name: "02f3ff690f4c840aebb734889d0a17c6",
            CAT.name: "d88c34b27b91a64eb2aeed4ad34fc250"}

FILE_NAME = "E11-D05 ref frames"
PAGE = "E11-D05 ref frames"
REV = "r1"
BOARDS = {9: ("E11-D05 / 09 ref-frames-a", "ref-frames-a"), 10: ("E11-D05 / 10 ref-frames-b", "ref-frames-b")}
BOARD_XY = {9: (0, 0), 10: (4000, 0)}  # the new page holds only these two roots, side by side
MARGIN = 80  # root margin, group gutters (positions, not a flex gap)
FRAME_GAP = 40  # between frames in a group row
LABEL_H = 40  # a group's label line + its gap above the frames
ANN_W = 400
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def spec_md5_ok() -> dict[str, bool]:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() == SPEC_MD5[p.name] for p in (SPEC, HANDOFF, D02, D04, CAT)}


_LINES = {p.name: _read(p) for p in (SPEC, HANDOFF, D02, D04, CAT)}


def L(needle: str, doc: str = "spec", start: int = 1) -> int:
    """The 1-based line of the first line (from start) containing needle in doc (spec / handoff / d02 / d04 / cat)."""
    name = {"spec": SPEC, "handoff": HANDOFF, "d02": D02, "d04": D04, "cat": CAT}[doc].name
    for i, ln in enumerate(_LINES[name][start - 1:], start):
        if needle in ln:
            return i
    raise KeyError(f"{needle!r} not in {name}")


def table1() -> dict[str, list[str]]:
    """Handoff Table 1: {"CMP-180": [states...]} for the eight drawn components (CMP-196 is non-visual)."""
    out: dict[str, list[str]] = {}
    i0 = L("### Table 1", "handoff")
    for ln in _LINES[HANDOFF.name][i0:i0 + 16]:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) > 3 and cells[0].startswith("CMP-") and "ref frame" in cells[3]:
            out[cells[0]] = [s.strip().replace("`", "") for s in cells[2].split(" · ")]
    return out


def frame_name(cmp: str, title: str, state: str) -> str:
    """Table 1's pattern: `CMP-nnn · Name — ref frame (<state>)`."""
    return f"{cmp} · {title} — ref frame ({state})"


# --- the 18 slot / alias names (§4.1 / §4.1b): slot -> the existing token the spec aliases it to (dark)
SLOTS = {
    "color.chart.axis": "color.text.tertiary",
    "color.chart.grid.major": "color.border.default",
    "color.chart.grid.minor": "color.grid.line",
    "color.chart.crosshair": "color.crosshair",
    "color.chart.watermark": "color.border.default",
    "color.chart.pane.bg.default": "color.surface.canvas",
    "color.chart.pane.bg.focused": "color.surface.canvas",
    "color.chart.replay.border": "color.node.logic",  # spec alias palette.purple.400 is a primitive (see note)
    "color.chart.boundary": "color.text.tertiary",
    "color.chart.rule": "color.border.default",
    "color.chart.hatch.texture": "color.border.strong",
    "color.chart.pill.bg": "color.surface.raised",
    "color.chart.pill.border": "color.border.strong",
    "color.chart.pill.text.default": "color.text.primary",
    "color.chart.pill.text.inverse": "color.text.inverse",
    "color.chart.pill.text.on-marker": "color.text.on-action",
    "color.chart.marker.goto": "color.action.primary.default",
    "color.chart.focus.ring": "color.focus.ring",
}
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
BORDER, BORDER_STRONG, RING = "color.border.default", "color.border.strong", "color.focus.ring"
BUY_TEXT, SELL_TEXT = "color.buy.default", "color.sell.default"  # FALLBACKS["buy-sell"]
UP, DOWN, WICK, AXIS = "color.candle.up", "color.candle.down", "color.candle.wick", "color.axis.text"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
ENV_DEMO, ENV_LIVE = "color.env.demo", "color.env.live"
NUM, CAPTION, LABEL, BODY = "type.num.sm", "type.ui.caption", "type.ui.label", "type.ui.body"
BODY_STRONG, HEADING_SM = "type.ui.body-strong", "type.ui.heading-sm"
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM = "space.stack.xs", "space.stack.sm"
ICON_SM, ICON = "size.icon.sm", "size.icon"  # 12 px (Tier-1, validator WARN) / 16 px
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, FOCUS_W = "border.hairline", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, ICON_SM: 12, ICON: 16}
FALLBACKS = {
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): small glyphs in pills and chips",
    "replay": ("slot pending #390: color.chart.replay.border -> color.node.logic. The spec aliases it to "
               "palette.purple.400 (dark), a primitive the validator refuses as a colour bind; no semantic token "
               "resolves to purple.400, so the nearest semantic purple (color.node.logic = palette.purple.500) "
               "stands in; the live drawer reads the hue as the replay purple, not its exact value"),
    "indicator": ("fallback: color.indicator.palette.1 (E13-D04's slot, not in packages/ui/tokens) for the EMA 20 "
                  "swatch / line is drawn as color.status.info.strong; the swatch's shape carries the kind"),
    "watermark-type": ("fallback: the watermark's 48 px (40 px dense) semibold has no type token (E11-D05 §6.1: "
                       "a fixed px, not a class); drawn with type.ui.display (24 px bold) - live check sets the size"),
    "watermark-dense": ("fallback: the dense 40 px watermark (E11-D05 §6 L291 'watermark 48 / 48 / 40 px') is drawn "
                        "with type.ui.heading-lg (20 px semibold), the same 40 : 48 ratio as the 24 px default - "
                        "live check sets 40 px"),
    "num-medium": ("fallback: the boundary date label's medium weight has no mono type token; drawn type.num.sm "
                   "(the weight is reinforcement, priority 0 is its position)"),
}
OPACITY_SCRIM, OPACITY_MUTED = "opacity.scrim", "opacity.muted"
DISPLAY, NUM_XS, NUM_BASE = "type.ui.display", "type.num.xs", "type.num.base"
CROSSHAIR, GRID_MINOR, ACTION = "color.crosshair", "color.grid.line", "color.action.primary.default"
INVERSE, ON_ACTION, INFO_STRONG = "color.text.inverse", "color.text.on-action", "color.status.info.strong"
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations")


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
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a boolean or other
    o.wrap, and a banned string (local path, host, agent name) in the name or note. Records bound tokens."""
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


def icon(name: str, glyph: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph not in ICONS_OK:
        raise ValueError(f"icon {glyph!r} not in the local set {sorted(ICONS_OK)}")
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph, color=color, size=size, **kw)


def rect(name: str, w: float, h: float, fill: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w, h=h, o=opts or None, **kw)


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


# --- text metrics (estimates; Inter / JetBrains Mono at 0.6 em)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), NUM: (11, 1.2, True), "type.num.base": (13, 1.2, True),
         "type.num.xs": (10, 1.2, True), "type.ui.display": (24, 1.2, False),
         "type.ui.heading-lg": (20, 1.2, False)}


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


# --- data: one seeded trade stream (random.Random(SEED)) and honest bar builders. The world: generation 1 records
# 2026-10-19 16:40-17:02 UTC; a recording gap 17:02-09:14 (W-2's placeholder times); generation 2 restarts 09:15 (W-1)
# and runs to the last good time 13:42:05 (§6.2's "values as of 13:42:05"), its last bar forming; a buy sweep of
# SWEEP_N prints at 2026-10-20 10:22:11.412 (§2.2's example time) makes several non-time bars share one open time.
# Time-axis kline rows (no delta, no trades): 16:00-16:39 before order flow starts (W-5) and 17:02-09:14 (W-3 / W-4).

def _size(section: dict[str, Any]) -> int:
    return len(json.dumps(section))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    """n pruned to at most room bytes: the bare board, its longest prefix of whole kids and, when cheaper, the next
    kid packed the same way; plus the cut parts as (parent path, node) in render order (e42kit's packer, copied)."""
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
    """Sections under budget raw bytes each, into paths valid when used (frames first, then the annotation column)."""
    out: list[dict[str, Any]] = []
    try:
        for n in nodes:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    return out


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children
    without text carry h; no '/' in names; no banned string anywhere."""
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
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})



# --- slots: bind the alias target, record the pending slot (per frame and per sheet)
FRAME_SLOTS: list[str] = []


def slot(name: str) -> str:
    """The token to bind for a §4.1 / §4.1b slot (its alias target today); records "slot pending #390"."""
    fb = SLOTS[name]
    if name == "color.chart.replay.border":
        fallback("replay")
    else:
        NOTES.add("fallbacks", f"slot pending #390: {name} -> {fb} (the alias target §4.1 / §4.1b names)")
    if name not in FRAME_SLOTS:
        FRAME_SLOTS.append(name)
    return fb


# --- seeded bars (deterministic; seed 310); prices on the 0.5 tick of BTCUSDT 1m
SEED = 310


@dataclass
class Bar:
    o: float
    h: float
    l: float
    c: float


def bars(n: int, seed: int = SEED, start: float = 64000.0, vol: float = 14.0) -> list[Bar]:
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        o = p
        c = round((o + rng.gauss(0, vol)) * 2) / 2
        h = round((max(o, c) + abs(rng.gauss(0, vol * 0.6))) * 2) / 2
        lo = round((min(o, c) - abs(rng.gauss(0, vol * 0.6))) * 2) / 2
        out.append(Bar(o, h, lo, c))
        p = c
    return out


def f_price(x: float) -> str:
    return f"{x:,.1f}"


# --- drawing primitives for a non-flex chart crop (children positioned by x / y; no abs needed)
def dashes(name: str, x: float, y: float, length: float, color: str, *, vertical: bool, dash: int = 4, gap: int = 4,
           thick: int = 1, phase: int = 0, o: dict[str, Any] | None = None, note: str | None = None) -> Node:
    """A dashed hairline as a board of dash rects (Penpot has no per-line dash token)."""
    kids, pos, i = [], -phase, 0
    while pos < length:
        a, b = max(pos, 0), min(pos + dash, length)
        if b > a:
            kids.append(rect(f"dash {i:02d}", thick if vertical else b - a, b - a if vertical else thick, color,
                             x=0 if vertical else a, y=a if vertical else 0))
            i += 1
        pos += dash + gap
    w, h = (thick, length) if vertical else (length, thick)
    return box(name, kids, o, w=w, h=h, x=x, y=y, note=note)


def pill(name: str, chars: str, fill: str, color: str, *, h: int = 17, typo: str = NUM, stroke: str | None = None,
         sw: str = HAIR, glyph: str | None = None, gcolor: str | None = None, x: float | None = None,
         y: float | None = None, radius: str = "radius.xs", pad: str = INSET_XS, note: str | None = None,
         magnet: bool = False) -> Node:
    """A GL axis pill (E11-D02 D7 / D9: 4 px horizontal padding, radius.xs, height per density: 17 compact)."""
    kids = [magnet_glyph(color) if magnet else None,
            icon("glyph", glyph, gcolor or color, ICON_SM) if glyph else None, text("label", chars, typo, color)]
    o = {"fill": fill, "radius": radius, "padX": pad, "gap": INSET_XS}
    if stroke:
        o.update(stroke=stroke, strokeWidth=sw, strokeAlign="inner")
    return hbox(name, kids, o, h=h, x=x, y=y, note=note)


def magnet_glyph(color: str) -> Node:
    """E11-D02 L302's 12 px magnet glyph from primitives (icon/magnet is CR-7, not in the local icon set): a 12 x 12
    horseshoe of three rects - two 3 px legs and a 3 px bridge, open end up."""
    return box("magnet glyph", [rect("leg left", 3, 9, color, x=0, y=0), rect("leg right", 3, 9, color, x=9, y=0),
                                rect("bridge", 12, 3, color, x=0, y=9)], w=12, h=12,
               note="12 px magnet glyph drawn from primitives (icon/magnet, E11-D02 CR-7, is not in the local set)")


def chip(name: str, chars: str, *, fill: str = RAISED, color: str = TEXT_1, stroke: str | None = BORDER,
         sw: str = HAIR, glyph: str | None = None, gcolor: str | None = None, dot: str | None = None,
         typo: str = CAPTION, h: int = 20, x: float | None = None, y: float | None = None,
         note: str | None = None) -> Node:
    """A status-row chip (E11-D02 D16: 20 px compact, radius.badge, type.ui.caption, 8 px horizontal padding)."""
    kids = [node("ellipse", "dot", w=8, h=8, o={"fill": dot}) if dot else None,
            icon("glyph", glyph, gcolor or color, ICON_SM) if glyph else None, text("label", chars, typo, color)]
    o: dict[str, Any] = {"fill": fill, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}
    if stroke:
        o.update(stroke=stroke, strokeWidth=sw, strokeAlign="inner")
    return hbox(name, kids, o, h=h, x=x, y=y, note=note)


def ring(name: str, w: float, h: float, x: float = 0, y: float = 0) -> Node:
    """The CMP-039 ring: 2 px color.focus.ring drawn inside the rectangle (E11-D02 D7 / D8)."""
    return rect(name, w, h, None, {"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"}, x=x, y=y)


def frame_rect(name: str, w: float, h: float, color: str, t: int, x: float = 0, y: float = 0) -> Node:
    """A t px solid frame as four rects (no border token is 4 px)."""
    return box(name, [rect("top", w, t, color, x=0, y=0), rect("bottom", w, t, color, x=0, y=h - t),
                      rect("left", t, h - 2 * t, color, x=0, y=t), rect("right", t, h - 2 * t, color, x=w - t, y=t)],
               w=w, h=h, x=x, y=y)


class Crop:
    """A compact-density chart-panel crop: optional status row (24), the pane (plot + price gutter) and the time strip
    (24). Geometry from E11-D02 §2 (compact): status row 24, gutter = widest label + 8 (min 48), strip 24, axis type
    type.num.sm 11 px, pills 17. Overlays go to .top (frame), .pane, .gutter or .strip lists (x / y local to each)."""

    def __init__(self, w: int, h: int, *, status: bool = False, strip: bool = True, gutter: int = 56, n: int = 14,
                 seed: int = SEED, data: bool = True, grid: bool = True, minor: bool = True,
                 labels: bool = True, times: Iterable[str] = ("13:30", "13:35", "13:40"),
                 zone: str | None = "UTC 13:47:05") -> None:
        self.w, self.h, self.gw = w, h, gutter
        self.st = 24 if status else 0
        self.sh = 24 if strip else 0
        self.pw, self.ph = w - gutter, h - self.st - self.sh
        self.data, self.grid, self.minor, self.labels, self.times = data, grid, minor, labels, list(times)
        self.zone = zone
        self.first = 0  # bars before this index are not drawn (not loaded)
        self.drop_times: set[int] = set()  # live fold: time labels removed, the rest keep their positions
        self.lp_box: tuple[int, int] | None = None  # the last-price pill's (top, bottom) in the gutter (D5 suppression)
        self.ink_group: str | None = None  # wrap the candles in one named group (the stale x0.85 dim target)
        self.axes = True  # False: no gutter rule / labels (no GL context)
        self.axis_typo = NUM
        self.bars = bars(n, seed)
        lo, hi = min(b.l for b in self.bars), max(b.h for b in self.bars)
        m = (hi - lo) * 0.15 or 10.0
        self.lo, self.hi = lo - m, hi + m
        self.top: list[Node] = []
        self.pane: list[Node] = []
        self.gutter: list[Node] = []
        self.strip: list[Node] = []
        self.status_left: list[Node] = []
        self.status_right: list[Node] = []
        self.slot_w = self.pw / (n + 2)  # two empty slots: the right offset

    def y(self, p: float) -> int:
        return round((self.hi - p) / (self.hi - self.lo) * (self.ph - 1))

    def x(self, i: int) -> int:
        return round(i * self.slot_w + self.slot_w / 2)

    def levels(self) -> tuple[list[float], list[float]]:
        span = self.hi - self.lo
        step = next(s for s in (5, 10, 20, 25, 50, 100, 200) if span / s <= 5)
        first = math.ceil(self.lo / step) * step
        major = [first + i * step for i in range(int(span // step) + 1) if first + i * step < self.hi]
        minor = [p + step / 2 for p in major if p + step / 2 < self.hi]
        return major, minor

    def strip_area(self) -> tuple[float, float]:
        """The strip's label area: 8 px right of the zone tag (E11-D02 L172) to 8 px left of the cluster (L171)."""
        a = 4 + text_w(self.zone, NUM) + 8 if self.zone else 4.0
        ends = [float(k["x"]) for k in self.strip if k.get("name") == "cluster"]
        return a, min([float(self.pw), *[e - 8 for e in ends]])

    def time_x(self, i: int) -> float:
        """The centre of time label i (labels evenly spaced in the strip's label area, dropped ones included)."""
        a, b = self.strip_area()
        return a + (b - a) * (i + 0.5) / len(self.times)

    def minutes_at(self, x: float) -> float:
        """The axis time at x (minutes after midnight), linear through the frame's own time labels (m3: every pill
        value is read off the axis it sits on, so it falls between the ticks it sits between)."""
        t = [int(s[:2]) * 60 + int(s[3:5]) for s in self.times]
        step = t[1] - t[0] if len(t) > 1 else 5
        a, b = self.strip_area()
        return t[0] + (x - self.time_x(0)) / ((b - a) / len(t)) * step

    def clock_at(self, x: float, *, secs: bool = False) -> str:
        m = self.minutes_at(x)
        if secs:
            s = math.floor(m * 60)
            return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"
        return f"{math.floor(m) // 60:02d}:{math.floor(m) % 60:02d}"

    def strip_pill(self, n: Node, xc: float) -> Node:
        """Place a strip pill on its anchor xc: centred; flipped left of the anchor when it would cross the cluster's
        8 px zone (E11-D02 L206); at the zone tag's mirror zone (L172) flipped right of the anchor, and held at the
        zone's edge when the flip does not clear it, so a pill never covers the tag's clock (L206: pills cover tick
        labels only)."""
        a, b = self.strip_area()
        w = est_width(n)
        x = xc - w / 2
        if x + w > b:
            x = xc - w
        if x < a:
            x = max(xc, a)
        return dict(n, x=round(x))

    def candle_nodes(self, upto: int | None = None) -> list[Node]:
        kids: list[Node] = []
        bw = max(1, round(0.7 * self.slot_w))
        bw -= 1 if bw >= 4 and bw % 2 == 0 else 0
        for i, b in enumerate(self.bars[:upto]):
            if i < self.first:
                continue
            cx = self.x(i)
            kids.append(rect(f"wick {i:02d}", 1, max(1, self.y(b.l) - self.y(b.h)), WICK, x=cx, y=self.y(b.h)))
            top, bot = min(self.y(b.o), self.y(b.c)), max(self.y(b.o), self.y(b.c))
            kids.append(rect(f"body {i:02d}", bw, max(1, bot - top), UP if b.c >= b.o else DOWN,
                             x=cx - bw // 2, y=top))
        return kids

    def last(self) -> Bar:
        return self.bars[-1]

    def build(self, name: str, *, note: str | None = None) -> Node:
        major, minor = self.levels()
        pane: list[Node] = []
        if self.grid:
            gmaj, gmin = slot("color.chart.grid.major"), slot("color.chart.grid.minor")
            if self.minor:
                pane += [rect(f"grid minor {i}", self.pw, 1, gmin, x=0, y=self.y(p)) for i, p in enumerate(minor)]
            pane += [rect(f"grid major {i}", self.pw, 1, gmaj, x=0, y=self.y(p)) for i, p in enumerate(major)]
        if self.data and self.ink_group:
            pane.append(box(self.ink_group, self.candle_nodes(), w=self.pw, h=self.ph, x=0, y=0,
                            note="data ink (wicks + bodies) in one group: the stale state's uniform x 0.85"))
        elif self.data:
            pane += self.candle_nodes()
        pane += self.pane
        # live fold (SHEET-FIX): the watermark is the pane's first child, under the grid and the candles
        pane.sort(key=lambda n: n.get("name") != "CMP-198 watermark")
        pbg = slot("color.chart.pane.bg.default")
        kids: list[Node] = [box("pane", pane, {"fill": pbg, "clip": True}, w=self.pw, h=self.ph, x=0, y=self.st)]
        gut: list[Node] = [rect("axis rule", 1, self.ph, slot("color.chart.rule"), x=0, y=0)] if self.axes else []
        if self.labels:
            ax = slot("color.chart.axis")
            lh = text_h(self.axis_typo)
            lp = self.lp_box
            # E11-D02 L205 (D5): the last-price pill suppresses any tick label whose box comes within one label
            # height of it
            gut += [text(f"tick {i}", f_price(p), self.axis_typo, ax, x=4, y=max(0, self.y(p) - 7))
                    for i, p in enumerate(major)
                    if 4 < self.y(p) < self.ph - 10 and not (
                        lp and max(0, self.y(p) - 7) < lp[1] + lh and max(0, self.y(p) - 7) + lh > lp[0] - lh)]
        gut += self.gutter
        kids.append(box("price gutter", gut, {"fill": pbg, "clip": True}, w=self.gw, h=self.ph, x=self.pw, y=self.st))
        if self.sh:
            st: list[Node] = [rect("strip rule", self.w, 1, slot("color.chart.rule"), x=0, y=0)]
            if self.labels:
                ax = slot("color.chart.axis")
                if self.zone:
                    st.append(text("zone tag", self.zone, NUM, ax, x=4, y=6, note="1 Hz, the WS-corrected server "
                                   "time; aria-live off; 8 px exclusion zone to its right (E11-D02 D8)"))
                for i, t in enumerate(self.times):
                    if i in self.drop_times:
                        continue
                    cx = self.time_x(i)
                    st.append(text(f"time {i}", t, NUM, ax, x=round(cx - text_w(t, NUM) / 2), y=6))
            st += self.strip
            kids.append(box("time strip", st, {"fill": pbg, "clip": True}, w=self.w, h=self.sh, x=0,
                            y=self.st + self.ph))
        if self.st:
            left = hbox("chips", self.status_left, {"gap": INSET_SM}, h=24, x=8, y=0) if self.status_left else None
            rw = sum(est_width(k) for k in self.status_right) + 8 * max(len(self.status_right) - 1, 0)
            right = (hbox("right", self.status_right, {"gap": INSET_SM}, h=24, x=round(self.w - 8 - rw), y=0)
                     if self.status_right else None)
            kids.insert(0, box("status row", [k for k in (left, right) if k], {"fill": RAISED}, w=self.w, h=24, x=0,
                               y=0))
        kids += self.top
        return box(name, kids, {"fill": slot("color.chart.pane.bg.default"), "clip": True}, w=self.w, h=self.h,
                   note=note)


# --- frames, groups, the annotation column, the board, the sheet, the md and the pack
def ref_frame(cmp: str, title: str, state: str, make: Any, cite: str) -> Node:
    """make() -> the frame's node (any name); renamed per Table 1; its note records the state, the cite and the
    slots it binds (pending #390) - the shape's plugin data carries it."""
    FRAME_SLOTS.clear()
    n = make()
    n = dict(n, name=frame_name(cmp, title, state))
    bits = [f"{cmp} state '{state}' ({cite}); dark, compact"]
    if FRAME_SLOTS:
        bits.append("slots (pending #390, alias bound): " + ", ".join(FRAME_SLOTS))
    n["note"] = "; ".join(bits)
    if BANNED.search(n["note"]):
        raise ValueError(n["note"])
    return n


@dataclass
class Group:
    cmp: str
    title: str
    frames: list[Node]
    per_row: int
    states: list[str]

    @property
    def name(self) -> str:
        return f"{self.cmp} {self.title} · {len(self.frames)} ref frames"

    def node(self) -> Node:
        kids: list[Node] = [text("label", f"{self.cmp} · {self.title} — {len(self.frames)} ref frames (one per state, "
                                          f"Table 1)", HEADING_SM, TEXT_1, x=0, y=0)]
        y, i = LABEL_H, 0
        while i < len(self.frames):
            row, x = self.frames[i:i + self.per_row], 0
            for j, f in enumerate(row):
                # m4: each frame carries a visible caption naming its Table 1 state, in the gap above it
                kids.append(text(f"state caption · {self.states[i + j]}", f"state: {self.states[i + j]}", CAPTION,
                                 TEXT_2, w=f["w"], x=x, y=y - 18))
                kids.append(dict(f, x=x, y=y))
                x += f["w"] + FRAME_GAP
            y += max(f["h"] for f in row) + FRAME_GAP
            i += self.per_row
        w = max(k["x"] + k["w"] for k in kids[1:] if k["t"] == "board")
        return box(self.name, kids, None, w=w, h=y - FRAME_GAP)


def annotations(nn: int, board_lines: list[str], blocks: list[tuple[str, list[str]]]) -> Node:
    """The ONE 400 px column: title, a Board block, one block per component, the footer."""
    cw = ANN_W - 32
    kids = [text("title", BOARDS[nn][0], HEADING_SM, TEXT_1, w=cw)]
    for i, (lab, lines) in enumerate([("Board", board_lines), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=cw)] + [text(f"value-{j}", ln, BODY, TEXT_1, w=cw)
                                                         for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=cw))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=cw))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def board(nn: int, groups: list[Group], ann: Node) -> tuple[dict[str, Any], list[Node]]:
    placed, y = [], MARGIN
    for g in groups:
        gn = dict(g.node(), x=MARGIN, y=y)
        placed.append(gn)
        y += gn["h"] + MARGIN
    right = max(g["x"] + g["w"] for g in placed)
    ah = est_height(ann)
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    w = right + MARGIN + ANN_W + MARGIN
    h = MEASURED_H.get(nn) or int(math.ceil(max(y, MARGIN + ah + MARGIN) / 8) * 8)
    x0, y0 = BOARD_XY[nn]
    name = BOARDS[nn][0]
    live(f"root {name!r} at ({x0}, {y0}) on page {PAGE!r}: read back the name exactly after the first section call "
         f"(a mismatch makes a duplicate root); size {w} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends at least {MARGIN} px above "
         f"the root's bottom (h {h}); if not, raise the root's h to the column's end + {MARGIN} and record it")
    live("each frame has its state caption 'state: <Table 1 state>' (type.ui.caption, color.text.secondary) 18 px "
         "above it, inside the row gap, clear of the frame (round 2, m4)")
    for g in placed:
        live(f"group {g['name']!r}: read back {g['w']} x {g['h']} at ({g['x']}, {g['y']}); its frames keep their "
             f"sheet sizes after relayout (clip on, no child outside its frame)")
    return {"name": name, "w": w, "h": h, "x": x0, "y": y0, "o": {"fill": APP, "clip": True}}, [*placed, a]


def export_path(nn: int) -> str:
    return f"docs/design/E11/img/E11-D05-{nn:02d}-{BOARDS[nn][1]}.png"


def sheet_name(nn: int) -> str:
    return f"{nn:02d}-{BOARDS[nn][1]}.json"


def write_sheet(nn: int, groups: list[Group], ann: Node, *, notes: dict[str, Iterable[str]] | None = None) -> Path:
    if not all(spec_md5_ok().values()):
        raise RuntimeError(f"spec drift: {spec_md5_ok()} - re-check the cites, re-pin SPEC_MD5")
    board_, nodes = board(nn, groups, ann)
    live(f"export {export_path(nn)}: export the root at scale 1 (dark set active) and record the board id, the PNG "
         f"size ({board_['w']} x {board_['h']}) and the frame count read back")
    live(f"after the render, run {Path(sheet_name(nn)).stem}.post-live.js (the kit writes it beside this sheet) twice: "
         f"frame notes to shared plugin data cvd02/note, watermarks 48 / 40 px weight 600 centred under the candles, "
         f"the stale x0.85 ink fills, the mark pill's 3 px padding (the live fold, 2026-10-30)")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"origin/main {BASE}: {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]}, {HANDOFF.name} md5 "
                         f"{SPEC_MD5[HANDOFF.name][:8]} (Table 1 L{L('### Table 1', 'handoff')}), {D02.name} md5 "
                         f"{SPEC_MD5[D02.name][:8]}, {D04.name} md5 {SPEC_MD5[D04.name][:8]}, 15 md5 "
                         f"{SPEC_MD5[CAT.name][:8]}; ruling of record Q2 / Q3 (2026-10-30)")
    sheet = {"board": board_, "sections": sections_for(nodes), "export": export_path(nn),
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    out = (CAP_DIR / sheet_name(nn)).resolve()
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(out), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode != 0:
        raise RuntimeError(f"{out.name}: validator exit {res.returncode}\n" + "\n".join(
            [ln for ln in lines if "ERROR" in ln.upper()][:20] or lines[-20:]))
    return out


def md_line3(nn: int) -> str:
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{export_path(nn)}`; sheet `{sheet_name(nn)}` (validated); "
            f"theme dark.")


def write_md(nn: int, sheet_path: Path, *, summary: str, frames: list[str]) -> Path:
    sh = json.loads(Path(sheet_path).read_text(encoding="utf-8"))
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(sheet_path), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    vline = (res.stdout + res.stderr).strip().splitlines()[-1]
    shapes = sum(1 for s in sh["sections"] for _p, _n in walk(s["node"]))
    out = [f"# {BOARDS[nn][0]}", "", md_line3(nn), "", summary, "",
           f"Root {sh['board']['w']} x {sh['board']['h']} px at ({sh['board']['x']}, {sh['board']['y']}); footer "
           f"\"page {PAGE} · board {nn:02d} · {REV}\".", "", f"## Frames ({len(frames)})", ""]
    out += [f"- `{f}`" for f in frames]
    out += ["", "## Validator and size", "", f"- `{vline}` (exit {res.returncode})",
            f"- {len(sh['sections'])} sections, {shapes} shapes, {len(json.dumps(sh))} bytes", ""]
    notes = sh["notes"]
    for kd in ("live_checks", "spec_gaps", "deviations", "fallbacks", "copy_keys", "copy_gaps", "sources", "tokens"):
        lines = notes.get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))  # an empty notes section leaves one blank line (prettier)
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    sp = Path(sheet_path).resolve()
    (sp.parent / (sp.stem + ".md")).write_text(s, encoding="utf-8")  # beside the sheet (the render drivers' set)
    p = KIT_DIR / (sp.stem + ".md")  # the committed copy
    p.write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path) -> Path:
    """Pack with ../tools/compact.py into v4/<same name>; the packer writes the source's absolute path into
    compactOf.file, which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged);
    check that and every packed section is <= PACKED_MAX bytes (compact JSON). Raises RuntimeError otherwise."""
    src = Path(sheet_path).resolve()
    V4_DIR.mkdir(parents=True, exist_ok=True)
    dst = V4_DIR / src.name
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
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


# --- shared chrome pieces (E11-D02 D8 cluster, D11 countdown, D13 watermark, D7 pills)
def segment(name: str, chars: str, *, pressed: bool = False, glyph: str | None = None) -> Node:
    kids = [icon("glyph", glyph, TEXT_1, ICON_SM) if glyph else None,
            text("label", chars, CAPTION, TEXT_1) if chars else None]
    o = {"fill": SELECTED if pressed else RAISED, "stroke": BORDER_STRONG if pressed else BORDER,
         "strokeWidth": HAIR, "strokeAlign": "inner", "padX": INSET_XS, "gap": INSET_XS, "justify": "center"}
    return hbox(name, kids, o, h=24, w=None if chars and len(chars) > 1 else 24)


def cluster(state: str = "following", *, x: float = 0, y: float = 0) -> Node:
    """[ auto | fit | › ] (E11-D01 Q2-c / E11-D02 D8): auto on = "Live" pressed (selected + border.strong + check);
    off = the "Paused at 13:47" warning pill replacing auto's label and widening the cluster leftwards."""
    if state == "paused":
        auto = hbox("auto · paused", [icon("glyph", "pending", WARN_STRONG, ICON_SM),
                                      text("label", "Paused at 13:47", CAPTION, TEXT_1)],
                    {"fill": WARN_SUBTLE, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner",
                     "padX": INSET_XS, "gap": INSET_XS}, h=24)
    else:
        auto = segment("auto · following", "Live", pressed=True, glyph="check")
    return hbox("cluster", [auto, segment("fit", "fit"), segment("latest", "›")], None, h=24, x=x, y=y)


def cluster_w(state: str = "following") -> float:
    return est_width(cluster(state))


def countdown(state: str = "normal") -> Node:
    """CMP-226 (E11-D02 D11): normal `bar close 0:41` text.secondary; warn `0:08 closing` on a warning.subtle pill,
    text.primary at medium weight, a clock glyph in warning.strong; closed `closed` and n/a `—` in text.tertiary."""
    if state == "warn":
        return hbox("CMP-226 countdown · warn", [icon("glyph", "pending", WARN_STRONG, ICON_SM),
                                                 text("label", "0:08 closing", BODY_STRONG, TEXT_1)],
                    {"fill": WARN_SUBTLE, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20)
    if state == "closed":
        return text("CMP-226 countdown · closed", "closed", NUM, TEXT_3)
    if state == "na":
        return text("CMP-226 countdown · n∕a", "—", NUM, TEXT_3, note="title: No countdown for tick bars")
    return hbox("CMP-226 countdown · normal", [text("label", "bar close", CAPTION, TEXT_2),
                                               text("digits", "0:41", NUM, TEXT_2)], {"gap": INSET_XS}, h=20)


def env_badge() -> Node:
    return chip("CMP-075 env badge", "DEMO", stroke=ENV_DEMO, sw=FOCUS_W, typo=LABEL)


# live fold: the watermarks whose 48 / 40 px text (live measured) is wider than the pane - 16: (pane w, text)
WATERMARK_WRAP = {(408, "BTCUSDT · 1m · replay"): True, (248, "BTCUSDT · 1m"): True,
                  (248, "BTCUSDT · 1m · replay"): True}
MEASURED_H = {9: 2913, 10: 2566}  # live fold: root h = the measured annotation end + MARGIN (2833 + 80, 2486 + 80)


def watermark(c: Crop, chars: str = "BTCUSDT · 1m", *, dense: bool = False) -> Node:
    fallback("watermark-type")
    typo = "type.ui.heading-lg" if dense else DISPLAY
    if dense:
        fallback("watermark-dense")
    tw = text_w(chars, typo)
    if WATERMARK_WRAP.get((c.pw, chars)):  # live fold: the 48 / 40 px text is wider than the pane - 16: wrap, centred
        return text("CMP-198 watermark", chars, typo, slot("color.chart.watermark"), w=c.pw - 16, align="center",
                    x=8, y=round(c.ph / 2 - (12 if dense else 14)), note=f"48 px semibold in the spec"
                    f"{' (40 px dense)' if dense else ''}; aria-hidden; opacity fixed at 1; wraps in pane - 16")
    return text("CMP-198 watermark", chars, typo, slot("color.chart.watermark"), x=round((c.pw - tw) / 2),
                y=round(c.ph / 2 - (12 if dense else 14)), note=f"48 px semibold in the spec{' (40 px dense)' if dense else ''}; "
                                              "aria-hidden; opacity fixed at 1")


def last_pill(c: Crop, *, up: bool | None = None, line: bool = True) -> None:
    """The last-price pill (E11-D02 D7) in the gutter at the last close + its 1 px dashed line across the plot."""
    b = c.last()
    up = (b.c >= b.o) if up is None else up
    fill = UP if up else DOWN
    yy = c.y(b.c)
    c.lp_box = (yy - 8, yy - 8 + 17)
    if line:
        c.pane.append(dashes("last-price line", 0, yy, c.pw, fill, vertical=False))
    c.gutter.append(rect("last-price nub", 4, 6, fill, x=1, y=yy - 3))
    # live fold (SHEET-FIX): the pill (live width > gutter - 4) sits flush with the gutter's left edge (x 4 -> 0)
    c.gutter.append(pill("last-price pill", f"{'▲' if up else '▼'}{f_price(b.c)}", fill,
                         slot("color.chart.pill.text.inverse"), x=0, y=yy - 8,
                         note="fill keyed to the current bar's direction, held >= 500 ms; ▲ / ▼ carries it"))


def force_dir(c: Crop, up: bool) -> None:
    b = c.bars[-1]
    if (b.c >= b.o) != up:
        b.o, b.c = b.c, b.o


def build_group(cmp: str, title: str, states: list[str], make: Any, cites: dict[str, str],
                per_row: int) -> tuple[Group, list[str]]:
    """One Group of Table 1 frames for cmp (states in Table 1 order); returns it and the union of slots bound."""
    if list(cites) != states:
        raise ValueError(f"{cmp}: cites {list(cites)} != Table 1 {states}")
    frames, used = [], []
    for st in states:
        frames.append(ref_frame(cmp, title, st, lambda st=st: make(st), cites[st]))
        used += [x for x in FRAME_SLOTS if x not in used]
    return Group(cmp, title, frames, per_row, states), used


def density_line(extra: str = "") -> str:
    return (f"Density (§6 L{L('| **compact**')}; E11-D02 §2): compact drawn (the trading default) — axis "
            f"type.num.sm 11 px, pills 17, chips 20, strip / rows 24, gutter = widest label + 8 (min 48), inset 8; "
            f"comfortable 13 px / 20 / 24 / 32 / inset 12; dense 10 px / 16 / 20 / 24 / inset 4." + extra)


PRODUCTS = "Variants × States products: not drawn — the text is binding (ruling Q2; Table 1's Variant column)."


# --- the live fold's post-render step (what a sheet cannot carry): run after the render, before the post-export
POST_LIVE_JS = """// E11-D05 board __NN__ post-render live step (kit-written; run it twice: the second run re-centres the watermarks on
// their settled heights). cvsheet drops `note`, no type token is 48 / 40 px and no colour token is the stale x0.85 ink.
const ROOT = __ROOT__;
const NOTES = __NOTES__;
const STALE = { "color.candle.up": "#27A14C", "color.candle.down": "#C33D41", "color.candle.wick": "#767E86" };
const r = penpot.currentPage.root.children.find(c => c.name === ROOT);
if (!r) return { abort: "root", ROOT };
const log = { notes: 0, missing: [], wm: [], stale: 0, mark: 0 };
for (const f of penpotUtils.findShapes(s => s.type === "board" && / ref frame \\(/.test(s.name), r)) {
  if (NOTES[f.name]) { f.setSharedPluginData("cvd02", "note", NOTES[f.name]); log.notes++; } else log.missing.push(f.name);
  for (const t of penpotUtils.findShapes(s => s.type === "text" && s.name === "CMP-198 watermark", f)) {
    const p = t.parent;
    t.fontSize = /\\(dense 40 px\\)$/.test(f.name) ? "40" : "48";
    t.fontWeight = "600";
    if (p.children[0] && p.children[0].id !== t.id) { const x = t.x, y = t.y; p.insertChild(0, t); t.x = x; t.y = y; }
    if (t.growType === "fixed" || t.growType === "auto-height") { t.x = p.x + 8; }
    else { t.x = p.x + Math.round((p.width - t.width) / 2); }
    t.y = p.y + Math.round((p.height - t.height) / 2);
    log.wm.push([f.name.replace(/.*\\(/, "("), t.fontSize, Math.round(t.x - p.x), Math.round(t.y - p.y)]);
  }
  for (const g of penpotUtils.findShapes(s => s.name === "data ink · x0.85", f)) {
    for (const k of penpotUtils.findShapes(() => true, g)) {
      let tk = {}; try { tk = k.tokens || {}; } catch (e) {}
      if (STALE[tk.fill]) { k.fills = [{ fillColor: STALE[tk.fill], fillOpacity: 1 }]; log.stale++; }
    }
  }
  for (const m of penpotUtils.findShapes(s => s.name === "mark pill", f)) {
    if (m.flex) { m.flex.leftPadding = 3; m.flex.rightPadding = 3; log.mark++; }
  }
}
return log;
"""


def write_post_live(nn: int, sheet_path: Path) -> Path:
    """build/NN-<slug>.post-live.js: the frames' notes as shared plugin data cvd02/note, the watermarks at 48 / 40 px
    weight 600 (under the candles, centred), the stale frame's x0.85 ink fills and the mark pill's 3 px padding."""
    sh = json.loads(Path(sheet_path).read_text(encoding="utf-8"))
    notes: dict[str, str] = {}
    for s in sh["sections"]:
        for _p, n in walk(s["node"]):
            if n.get("t") == "board" and " ref frame (" in str(n.get("name")) and n.get("note"):
                notes[n["name"]] = n["note"]
    js = (POST_LIVE_JS.replace("__NN__", f"{nn:02d}").replace("__ROOT__", json.dumps(BOARDS[nn][0], ensure_ascii=False))
          .replace("__NOTES__", json.dumps(notes, ensure_ascii=False)))
    if BANNED.search(js):
        raise RuntimeError(f"post-live js for board {nn:02d}: banned string")
    out = CAP_DIR / (Path(sheet_path).stem + ".post-live.js")
    out.write_text(js, encoding="utf-8")
    return out
