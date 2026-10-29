"""cap10: compose E42-D03's ten confirmed boards (plan: e42d03-plan.md, #886 comment 6498384157, confirmed by
main-orchestrator 2026-10-29 13:57Z) from the old per-board sheets' frames (method of E42-D04's gen10/cap10.py).

Each frame is the old board's frame node tree exactly as its generator (gen/gen_NN.py) wrote and validated it in
E42-D03/NN-<slug>.json: only the frame's root is renamed (old boards call theirs "frame-1280" / "frame-2560", which
would collide on a board) and given its x/y on the new board. harvest.py re-runs the ten source generators in a sandbox
and records that their fresh frames equal the recorded ones (BUILD.md). This module only reads gen/, the kit and the old
sheets; it writes ../E42-D03-cap10/ and ../E42-D03-cap10-v4/.

Board: a plain (non-flex) root, fill color.surface.app, clip; frames 1:1 left to right in one row with 80 px gutters
and an 80 px margin (no 80 px spacing token exists, so the gutters are positions, not a flex gap). The old boards'
non-frame panels (72's insets, 91's SCR-121 parts panel, 92's legend and focus-order table) keep their place under the
frame they sat under on the old board, at the same offset. ONE 400 px annotation column right of the row holds, per
old board (state): a heading, the frames, the provenance, then every annotation block of the old board (source, state
and trigger, decision ids, roles, keyboard path and focus, announcement, copy keys, tokens, analytics and audit events,
budget / insets / notes); the focus-order overlay on boards 04 and 06 (the plan's keyboard rider, quoted from the
boards-branch text); the Board block; the footer "page E42-D03 · board NN · r2". The root hugs the content + 80 px.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
SHEETS = SRC.parent
G10 = SRC / "gen10"
OUT = SRC / "cap10"  # the unpacked sheets (not committed; v4/ expands to them)
PACKED = SRC / "v4"
PIN_SPEC = G10 / "pin" / "branch-4babb1f62.md"  # git show origin/design/e42-d03-boards (= e42kit.SPEC_RULED)
PIN_MD5 = "d91202f9bf42206dd1a5cbc865d5ce02"
PIN_REV = "4babb1f62"
MAIN_SPEC = G10 / "pin" / "main-58660d32f.md"  # git show origin/main (unchanged since 58660d32f)
MAIN_MD5 = "2e87d809cdb23a4cc311f21a272abf33"
VALIDATOR = SHEETS / "tools" / "validate_sheet.py"
COMPONENTS = SHEETS / "tools" / "components.offline.json"
PACKER = SHEETS / "tools" / "compact.py"
PLAN_NAME = "e42d03-plan.md"
CONFIRMED = "2026-10-29 13:57Z"

M = 80  # margin and gutter
COL_W = 400  # the annotation column
OLD_PAD = 16  # the old roots' pad and gap (space.inset.lg)
GRID_X, GRID_Y = 6000, 3200
SECTION_HARD = 24000  # e42kit.SECTION_HARD: the validator warns above it
LEAK = re.compile(r"/h[o]me/|scratch-[a]nvil|new-pro[j]ects|w[t]/\d|hc[l]-|hp[e]-")  # local paths, lane names

Node = dict[str, Any]


@dataclass(frozen=True)
class F:
    """One top-level node of an old sheet carried onto a new board: `old` its name there, `new` its name here;
    frames = how many §0 frames it counts (0 for a panel, which is not a frame)."""
    state: str
    nn: int
    old: str
    new: str
    frames: int = 1


def fr(state: str, nn: int, px: int, old: str = "", tag: str = "") -> F:
    size = {1280: "1280×800", 2560: "2560×1440"}[px]
    return F(state, nn, old or f"frame-{px}", f"{state}{' · ' + tag if tag else ''} · {size} [{nn:02d}]")


# --- the confirmed plan's table (e42d03-plan.md), one row each. old §0 row: the boards-branch §0 line naming the old id
BOARDS: dict[int, dict[str, Any]] = {
    1: {"slug": "tint-proof", "theme": "dark+light", "star": True, "keys": "", "s0": 64,
        "items": [fr("OV-2", 9, 1280, "frame-1280 SCR-120 overview", "SCR-120 overview"),
                  fr("SCR-010", 9, 1280, "frame-1280 SCR-010 workspace", "workspace")],
        "count": 4, "count_note": "4 by §0's count (L75): the two frames drawn here, dark, and the same two exported "
                                  "under the light token theme (old board 09's notes; the plan)"},
    2: {"slug": "scr120-trading-unknown", "theme": "dark", "star": False, "keys": "", "s0": 66,
        "items": [fr("OV-6", 26, 1280), fr("OV-6", 26, 2560)]},
    3: {"slug": "scr120-withdrawal", "theme": "dark", "star": True, "keys": "", "s0": 66,
        "items": [fr("OV-9", 94, 1280), fr("OV-9", 94, 2560)]},
    4: {"slug": "scr122-unbind-unknown", "theme": "dark", "star": False, "keys": "122", "s0": 68,
        "items": [fr("UD-12", 53, 1280), fr("UD-12", 53, 2560)]},
    5: {"slug": "scr122-invited", "theme": "dark", "star": False, "keys": "", "s0": 68,
        "items": [fr("UD-16", 57, 1280), fr("UD-16", 57, 2560)]},
    6: {"slug": "scr124-active", "theme": "dark", "star": True, "keys": "124", "s0": 70,
        "items": [fr("V-4", 72, 1280), fr("V-4", 72, 2560),
                  F("V-4", 72, "insets · under frame-1280 (not frames)", "V-4 insets · under V-4 · 1280×800 (not frames) [72]", 0)]},
    7: {"slug": "role-matrix", "theme": "dark", "star": False, "keys": "", "s0": 71,
        "items": [F("N-6", 88, "role · Owner", "N-6 · Owner (basiltt) · 1280×800 [88]"),
                  F("N-6", 88, "role · Manager", "N-6 · Manager (alex) · 1280×800 [88]"),
                  F("N-6", 88, "role · Viewer", "N-6 · Viewer (erin) · 1280×800 [88]")]},
    8: {"slug": "status-treatments", "theme": "dark", "star": True, "keys": "", "s0": 72,
        "items": [F("status-treatments", 90, "frame-1280 · dark", "status-treatments · dark · 1280×1688 [90]"),
                  F("status-treatments", 90, "frame-1280 · light", "status-treatments · light · 1280×1688 [90]"),
                  F("status-treatments", 90, "frame-1280 · hc", "status-treatments · hc · 1280×1688 [90]")]},
    9: {"slug": "components", "theme": "dark", "star": False, "keys": "", "s0": 72,
        "items": [F("components", 91, "frame-1280", "components · CMP-087 stories · 1280×800 [91]"),
                  F("components", 91, "frame-2560",
                    "components · sheet page 2, the other contracts' stories (DEV panel, not a frame) [91]", 0),
                  F("components", 91, "panel · SCR-121 parts at 1280 (not a frame)",
                    "components · SCR-121 parts at 1280 (DEV panel, not a frame) [91]", 0)]},
    10: {"slug": "redlines", "theme": "dark", "star": False, "keys": "", "s0": 72,
         "items": [fr("OV-2 redlines", 92, 1280), fr("OV-2 redlines", 92, 2560),
                   F("OV-2 redlines", 92, "legend · spacing and tokens by region (annotation)",
                     "legend · spacing and tokens by region (annotation, not a frame) [92]", 0),
                   F("OV-2 redlines", 92, "focus order · stop by stop (annotation)",
                     "focus order · stop by stop (annotation, not a frame) [92]", 0)]},
}
# the plan's frame count per board (§0's count rule): 01 = 4, 02-06 = 2 each, 07 = 3, 08 = 3, 09 = 1, 10 = 2 -> 23
PLAN_COUNT = {1: 4, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 1, 10: 2}
RENDERS = (1, 3, 6, 8)  # the plan: renders on boards 01, 03, 06 and 08 (8 PNGs)

# the keyboard rider (plan; boards-branch 4babb1f62): §12's Keys for the D21 dialog, §13's rows, §10's banner Keys
KEY_LINES = {"122": [(575, 581), (606, 606), (607, 607), (611, 611)],
             "124": [(513, 516), (609, 609), (602, 602), (607, 607), (611, 611)]}
KEY_NOTE = {
    "122": "R-2 (§0 L84-91; §12 L575-581; §13 L607): the confirm waiting on its inputs is natively disabled and skipped "
           "by Tab (CMP-044's merged form). Board [53]'s Keyboard block above predates R-2 (its Tab path ends "
           "\"→ Cancel → Remove access\"); §0 L84-91 keeps that drawing until redrawn on request, and the text binds.",
    "124": "Nothing moves focus on expiry (SH-4; §13 L602); dialogs focus Cancel, Esc cancels and never picks a "
           "choice, focus returns to the opener (§13 L607); D02 D18, no new binding.",
}


# --- the pinned specs
def _read(p: Path, md5: str) -> list[str]:
    raw = p.read_bytes()
    if hashlib.md5(raw).hexdigest() != md5:
        raise RuntimeError(f"{p.name}: md5 is not {md5[:8]}")
    return raw.decode("utf-8").split("\n")


def spec_lines() -> list[str]:
    return _read(PIN_SPEC, PIN_MD5)


def check_s0(nn: int) -> str:
    """The old id's §0 row on the boards branch must name it as drawn; returns the row's first cell."""
    b = BOARDS[nn]
    line = spec_lines()[b["s0"] - 1]
    olds = sorted({it.nn for it in b["items"]})
    for o in olds:
        if not re.search(rf"\b{o:02d}\b", line) or ("Drawn: all three" not in line and not re.search(
                rf"Drawn: [^.]*\b{o:02d}\b", line)):
            raise RuntimeError(f"board {nn:02d}: §0 L{b['s0']} does not say old {o:02d} is drawn")
    return line.split("|")[1].strip()


def quote(a: int, b: int) -> str:
    t = " ".join(ln.strip() for ln in spec_lines()[a - 1:b])
    t = t.replace("`", "").replace("**", "").strip()
    if t.startswith("|"):
        cells = [c.strip() for c in t.strip("|").split("|")]
        t = " — ".join(c for c in cells if c and c != "—")
    t = re.sub(r"^- ", "", re.sub(r"\s+", " ", t))
    return f"L{a}{'-' + str(b) if b != a else ''}: {t}"


# --- reading the old sheets
def old_sheet(nn: int) -> tuple[Path, dict[str, Any]]:
    p = next(q for q in SRC.glob(f"{nn:02d}-*.json") if q.suffix == ".json")
    return p, json.loads(p.read_text(encoding="utf-8"))


def top_sections(sheet: dict[str, Any], top: str) -> list[dict[str, Any]]:
    secs = [s for s in sheet["sections"] if (s["into"] == "" and s["node"]["name"] == top)
            or s["into"] == top or s["into"].startswith(top + "/")]
    if not secs or secs[0]["into"] != "":
        raise ValueError(f"{top!r}: no top-level section")
    return secs


def assemble(secs: list[dict[str, Any]]) -> Node:
    """The full tree of a top-level node (its later sections appended at their `into` paths) for height estimates."""
    root = copy.deepcopy(secs[0]["node"])
    for s in secs[1:]:
        cur = root
        for seg in s["into"].split("/")[1:]:
            cur = next(k for k in cur.get("kids", []) if k.get("name") == seg)
        cur.setdefault("kids", []).append(copy.deepcopy(s["node"]))
    return root


def kit():
    sys.path.insert(0, str(SRC))
    import e42kit  # noqa: E402  (read-only use of the kit's estimator)
    return e42kit


def est_h(n: Node) -> int:
    return int(math.ceil(kit().est_height(n)))


def old_layout(sheet: dict[str, Any]) -> dict[str, tuple[int, int, int, int, bool]]:
    """Old root (flex row, pad/gap 16): every top-level node's (x, y, w, h, abs)."""
    out: dict[str, tuple[int, int, int, int, bool]] = {}
    x = OLD_PAD
    for s in sheet["sections"]:
        if s["into"] != "":
            continue
        n = s["node"]
        full = assemble(top_sections(sheet, n["name"])) if n["name"] != "annotations" else n
        h = int(n.get("h") or est_h(full))
        if n.get("abs"):
            out[n["name"]] = (int(n["x"]), int(n["y"]), int(n["w"]), h, True)
        else:
            out[n["name"]] = (x, OLD_PAD, int(n["w"]), h, False)
            x += int(n["w"]) + OLD_PAD
    return out


def rename(secs: list[dict[str, Any]], top: str, new: str, x: int, y: int) -> list[dict[str, Any]]:
    out = copy.deepcopy(secs)
    head = out[0]["node"]
    head["name"] = new
    for k in ("abs", "alignSelf"):
        head.pop(k, None)
    head["x"], head["y"] = x, y
    for s in out[1:]:
        s["into"] = new + s["into"][len(top):]
    return out


# --- fix pass (2026-10-29): the per-set file "E42-D03 boards" has no CMP-015 / CMP-016 component, so the carried
# inst nodes are replaced by compositions (the kits' fallbacks). Everything else in the carried trees is unchanged.
SUBST_SETS = ("CMP-015 · Skeleton", "CMP-016 · Tooltip")
SKEL_BAR_H = 12  # E27-D03 kit's skeleton bar height (rect 16 x 12); bar + space.stack.xs = one 16 px text line
SUBST_NOTES = {
    "CMP-015 · Skeleton": (
        "fallback: CMP-015's skeleton is a static bar in color.surface.hover (reduced-motion form, §2.5; the E27-D03 "
        "kit's FALLBACKS['SKELETON']): the file has no CMP-015 component, so 'CMP-015 Skeleton · text ×3' is the "
        "board 'CMP-015 Skeleton (composition)', a column (gap space.stack.xs) of Count text-shaped bars, each "
        f"{SKEL_BAR_H} px tall and the instance's slot width, fill color.surface.hover, radius.control"),
    "CMP-016 · Tooltip": (
        "fallback: the file has no CMP-016 component, so 'CMP-016 Tooltip · echo' is the board 'CMP-016 Tooltip "
        "(composition) · echo': fill color.surface.overlay, shadow elevation.popover, radius.control, padX "
        "space.inset.sm, padY space.inset.xs, its content (the inst's own text, rbac.view_as) in type.ui.caption "
        "color.text.primary (the E10-D03 CMP-016 tooltip's tokens; the kit's overlays use color.surface.overlay + "
        "elevation.popover)"),
}


def _subst(n: Node) -> Node:
    """One CMP-015 / CMP-016 inst node -> its composition (the inst's name, slot width and note carried over)."""
    set_, props = n["set"], n.get("props") or {}
    if set_ == "CMP-015 · Skeleton":
        if props.get("Shape") != "text" or "w" not in n or set(n) - {"t", "name", "set", "props", "w"}:
            raise ValueError(f"skeleton inst {n['name']!r}: only text-shaped, fixed-width instances are handled")
        count, w = int(props.get("Count", "1")), n["w"]
        bars = [{"t": "rect", "name": f"bar {i}", "w": w, "h": SKEL_BAR_H,
                 "o": {"radius": "radius.control", "fill": "color.surface.hover"}} for i in range(1, count + 1)]
        return {"t": "board", "name": "CMP-015 Skeleton (composition)",
                "o": {"dir": "column", "align": "start", "gap": "space.stack.xs"}, "kids": bars, "w": w,
                "note": f"replaces the inst {n['name']!r} (Shape text, Count {count}): static bars in "
                        "color.surface.hover, the reduced-motion form (§13 L599)"}
    if set_ == "CMP-016 · Tooltip":
        chars = (n.get("texts") or {}).get("content", "")
        if not chars.strip() or set(n) - {"t", "name", "set", "props", "texts", "note"}:
            raise ValueError(f"tooltip inst {n['name']!r}: no content text, or keys this fix does not carry")
        name = n["name"].replace("CMP-016 Tooltip", "CMP-016 Tooltip (composition)", 1)
        out: Node = {"t": "board", "name": name,
                     "o": {"dir": "row", "fill": "color.surface.overlay", "shadow": "elevation.popover",
                           "radius": "radius.control", "padX": "space.inset.sm", "padY": "space.inset.xs"},
                     "kids": [{"t": "text", "name": "content", "chars": chars, "typo": "type.ui.caption",
                               "color": "color.text.primary"}]}
        if n.get("note"):
            out["note"] = f"role=\"tooltip\"; {n['note']}"
        return out
    raise ValueError(set_)


def substitute(n: Node) -> tuple[Node, int]:
    """n with every CMP-015 / CMP-016 inst (at any depth) replaced by its composition; returns (node, count)."""
    if n.get("t") == "inst" and n.get("set") in SUBST_SETS:
        return _subst(n), 1
    if not n.get("kids"):
        return n, 0
    out, total = dict(n), 0
    kids = []
    for k in n["kids"]:
        k2, c = substitute(k)
        kids.append(k2)
        total += c
    out["kids"] = kids
    return out, total


# --- live-check fold (2026-10-29): the SHEET-FIX lines of p0/E42-D03-cap10/livecheck-report.md, applied to the
# carried trees after substitute() so a regeneration reproduces what was fixed live. Only the named nodes change.
UNDERLINE_W = {  # the sibling word -> (width the estimate gave, width measured live)
    "Change": (46, 48), "BTC scalp": (61, 62), "Default": (43, 45), "Workspace": (68, 70), "Journal": (44, 47),
    "Settings": (49, 51), "Security and backups": (147, 148), "Flags": (36, 37), "Recorder and storage": (148, 146),
    "Record tier": (66, 68),
}
ROOT_H = {1: 2349, 2: 2248, 3: 2276, 4: 3131, 5: 2244, 6: 2944, 7: 2174, 8: 2359, 9: 2470, 10: 2275}  # foot + 80
PILL_DX = {3: 1, 5: -2, 8: 2, 10: 1, 15: 1, 16: 1}  # board 10: pill x, target box right + 4 (measured vs estimate)
PILL_DY = {11: 3, 12: 3, 13: 3, 14: 3}  # board 10, 2560 only: centred on its AuditRow / the button
ECHO_W = 186  # the CMP-016 echo's measured width (live check, 06 1280)
LIVEFIX_CHECKS = {6: [
    "fix pass (live check): after render, pin the svg group of every 'countdown glyph' (banner 1280, banner 2560, "
    "inset 1) at (1, 1) inside its 16 px box: the kit places it 43 px low"]}


def _word_of(parent: Node) -> str:
    kids = parent.get("kids") or []
    t = next((k for k in kids if k.get("t") == "text"), None) or next(
        (g for k in kids for g in (k.get("kids") or []) if g.get("t") == "text"), None)
    return str((t or {}).get("chars", ""))


hits_ctx: dict[str, str] = {}


def _livefix(n: Node, nn: int, sec: int, parent: Node | None, hits: list[str]) -> None:
    name = n.get("name")
    if n.get("t") == "rect" and name == "underline" and parent is not None:
        word = _word_of(parent)
        if word in UNDERLINE_W and n.get("w") == UNDERLINE_W[word][0] and UNDERLINE_W[word][0] != UNDERLINE_W[word][1]:
            n["w"] = UNDERLINE_W[word][1]
            hits.append(f"{nn:02d} underline {word!r}")
    if nn == 6 and name == "T2 2b · cancel with its echo" and sec == 1:  # the 1280 frame only, as fixed live
        n["w"], n["h"] = 32, 58
        n["o"] = {**n["o"], "clip": False}
        echo = next(k for k in n["kids"] if k["name"].startswith("CMP-016 Tooltip"))
        echo["abs"], echo["x"], echo["y"] = True, 32 - ECHO_W, 32 + 4
        hits.append("06 T2 2b + echo")
    if nn == 9 and name == "unknown line (radiogroup label)":
        tail = next(k for k in n["kids"] if k["name"] == "tail")
        tail.pop("w", None)
        hits.append("09 tail auto-width")
    if nn == 9 and name == "text" and n.get("t") == "text" and n.get("w") == 890 and parent is not None \
            and parent.get("name") == "line":
        n["w"] = 944 - 8 - 48
        hits.append("09 capacity text w 888")
    if nn == 4 and name == "CMP-044 ConfirmDialog (composition) · rung 2" and n.get("y") in (171, 491):
        n["y"] -= 4  # the estimate is 640 x 466, not 458: centred
        hits.append("04 rung-2 y")
    if nn == 10 and parent is not None and parent.get("name") == "pills":
        m = re.match(r"focus (\d+) ", str(name))
        num = int(m.group(1)) if m else 0
        wide = "2560" in str(hits_ctx.get("frame", ""))
        if num in PILL_DX and (num in (3, 5, 8) or wide):
            n["x"] += PILL_DX[num]
            hits.append(f"10 pill {num} x")
        if wide and num in PILL_DY:
            n["y"] += PILL_DY[num]
            hits.append(f"10 pill {num} y")
    for k in n.get("kids") or []:
        _livefix(k, nn, sec, n, hits)


def livefix(nn: int, sections: list[dict[str, Any]]) -> list[str]:
    hits: list[str] = []
    for i, s in enumerate(sections):
        hits_ctx["frame"] = s["into"]
        _livefix(s["node"], nn, i, None, hits)
    return hits


def label_of(block_: Node) -> str:
    for k in block_.get("kids", []):
        if k["t"] == "text" and k["name"] == "label":
            return str(k["chars"])
    return ""


# --- the annotation column
def text(name: str, chars: str, typo: str = "type.ui.body", color: str = "color.text.primary") -> Node:
    return {"t": "text", "name": name, "chars": chars, "typo": typo, "color": color, "w": 368}


def block(name: str, label: str, values: list[str]) -> Node:
    return {"t": "board", "name": name, "o": {"dir": "column", "align": "start", "gap": "space.stack.xs"}, "w": 368,
            "kids": [text("label", label, "type.ui.label", "color.text.secondary")]
            + [text(f"value-{i}", v) for i, v in enumerate(values, 1)]}


def focus_block(screen: str) -> Node:
    vals = [quote(a, b) for a, b in KEY_LINES[screen]] + [KEY_NOTE[screen]]
    return block("focus order overlay", f"Focus order overlay · SCR-{screen} (the plan's keyboard rider; boards-branch "
                 f"text {PIN_REV}: §12 / §10 Keys, §13; §17 AC-4 / AC-5 / DoD-5)", vals)


def provenance(nn: int) -> str:
    h = json.loads((G10 / "harvest.json").read_text(encoding="utf-8")).get(f"{nn:02d}")
    if not h or h["exit"] != 0:
        raise RuntimeError(f"gen_{nn:02d}.py: no clean sandbox re-run in harvest.json")
    if h.get("frames_equal"):
        return f"gen_{nn:02d}.py re-run in the sandbox: frames byte-equal to the recorded sheet"
    if h.get("frames_equal_pre_skel"):
        return (f"gen_{nn:02d}.py re-run in the sandbox: frames byte-equal to its own output (.pre-skel); the recorded "
                "sheet drops the CMP-015 Skeleton inst's State prop (live read-back), so the recorded frames are used")
    raise RuntimeError(f"gen_{nn:02d}.py: fresh frames differ from the recorded sheet")


def scrub(s: str) -> str:
    """Notes carried from the old sheets: local paths and worktree names reduced to neutral words."""
    s = re.sub(r"/h[o]me/[^/]+/new-pro[j]ects/scratch-[a]nvil/", "", s)
    s = re.sub(r"scratch-[a]nvil/", "", s)
    s = re.sub(r"\bw[t]/886-b\b", "the boards-branch checkout", s)
    s = re.sub(r"\bw[t]/886\b", "the spec checkout", s)
    return s


# --- the board
def board_name(nn: int) -> tuple[str, str]:
    b = BOARDS[nn]
    sizes: list[str] = []
    for it in b["items"]:
        if not it.frames:
            continue
        m = re.search(r"(\d+×\d+)", it.new)
        assert m
        if m.group(1) not in sizes:
            sizes.append(m.group(1))
    sz = "+".join(sorted(sizes, key=lambda s: int(s.split("×")[0])))
    return f"E42-D03 / {nn:02d} {b['slug']} · {sz} · {b['theme']}", sz


@dataclass
class Built:
    board: dict[str, Any]
    sections: list[dict[str, Any]]
    export: str
    stem: str
    items: list[dict[str, Any]] = field(default_factory=list)
    col_h: int = 0
    content_bottom: int = 0
    sheets: dict[int, str] = field(default_factory=dict)
    notes_src: dict[int, dict[str, Any]] = field(default_factory=dict)
    n_drawn: int = 0
    n_count: int = 0
    n_subst: dict[str, int] = field(default_factory=dict)  # fix pass: set -> inst nodes replaced


def build(nn: int) -> Built:
    b = BOARDS[nn]
    name, sizes = board_name(nn)
    stem = f"{nn:02d}-{b['slug']}"
    export = f"docs/design/E42/img/E42-D03-{stem}.png"
    s0_cell = check_s0(nn)
    sheets: dict[int, tuple[Path, dict[str, Any]]] = {}
    layouts: dict[int, dict[str, tuple[int, int, int, int, bool]]] = {}
    sections: list[dict[str, Any]] = []
    items_meta: list[dict[str, Any]] = []
    placed: dict[tuple[int, str], tuple[int, int]] = {}  # old (nn, name) -> new (x, y) of in-row items
    x = M
    bottom = M
    n_subst = 0
    subst_by_set: dict[str, int] = {}
    # in-row items first (left to right), then the panels anchored under the in-row item they sat under
    order = list(b["items"])
    for pass_abs in (False, True):
        for it in order:
            if it.nn not in sheets:
                sheets[it.nn] = old_sheet(it.nn)
                layouts[it.nn] = old_layout(sheets[it.nn][1])
            ox, oy, w, h, is_abs = layouts[it.nn][it.old]
            if is_abs != pass_abs:
                continue
            secs = top_sections(sheets[it.nn][1], it.old)
            if not is_abs:
                nx, ny = x, M
                placed[(it.nn, it.old)] = (nx, ny)
                x += w + M
            else:
                anchor = next((k for k, v in layouts[it.nn].items() if not v[4] and k != "annotations"
                               and v[0] <= ox < v[0] + v[2]), None)
                if anchor is None:
                    raise RuntimeError(f"{it.old}: no in-row node above it on old board {it.nn:02d}")
                ax_, ay_ = placed[(it.nn, anchor)]
                a = layouts[it.nn][anchor]
                nx, ny = ax_ + (ox - a[0]), ay_ + (oy - a[1])
            for s in rename(secs, it.old, it.new, nx, ny):
                before = [x_.get("set") for x_ in walk(s["node"]) if x_.get("t") == "inst"]
                s["node"], c = substitute(s["node"])
                n_subst += c
                for st in SUBST_SETS:
                    subst_by_set[st] = subst_by_set.get(st, 0) + sum(1 for b_ in before if b_ == st)
                sections.append(s)
            items_meta.append({"name": it.new, "state": it.state, "old_board": it.nn, "old_node": it.old,
                               "sheet": sheets[it.nn][0].name, "x": nx, "y": ny, "w": w, "h": h, "frames": it.frames,
                               "sections": len(secs), "panel": not it.frames})
            bottom = max(bottom, ny + h)
    row_right = x - M
    ax = row_right + M
    n_drawn = sum(m["frames"] for m in items_meta)
    n_count = b.get("count", n_drawn)
    if n_count != PLAN_COUNT[nn]:
        raise RuntimeError(f"board {nn:02d}: {n_count} frames, the plan counts {PLAN_COUNT[nn]}")
    # annotation column
    title = text("title", f"{nn:02d} {b['slug']} · {sizes} · {b['theme']}", "type.ui.heading-sm")
    sub = text("subtitle", "E42-D03 board %02d of the ten in the confirmed cap plan (main-orchestrator %s): the frames "
               "1:1 in one row, 80 px gutters, each named by its state id with the old §0 board id in brackets; per "
               "state below, that id's annotation (source, state and trigger, decision ids, roles, keyboard path and "
               "focus, announcement, copy keys, tokens, analytics and audit events)." % (nn, CONFIRMED),
               "type.ui.caption", "color.text.tertiary")
    col = {"t": "board", "name": "annotations", "o": {"dir": "column", "align": "start", "gap": "space.stack.sm",
                                                       "pad": "space.inset.lg"}, "w": COL_W, "x": ax, "y": M,
           "kids": [title, sub]}
    ann_secs: list[dict[str, Any]] = [{"into": "", "node": col}]
    groups: dict[int, list[str]] = {}  # one annotation group per old board (its blocks cover all its frames)
    states: dict[int, list[str]] = {}
    for m in items_meta:
        groups.setdefault(m["old_board"], []).append(m["name"])
        if m["state"] not in states.setdefault(m["old_board"], []):
            states[m["old_board"]].append(m["state"])
    for onn, names in groups.items():
        state = " beside ".join(states[onn])
        olda = next(s["node"] for s in sheets[onn][1]["sections"] if s["into"] == "" and s["node"]["name"] == "annotations")
        kids: list[Node] = [text("heading", f"{state} [{onn:02d}] ({sheets[onn][0].stem})", "type.ui.heading-sm"),
                            text("frames", "Frames and panels: " + " · ".join(names), "type.ui.caption",
                                 "color.text.secondary"),
                            text("provenance", provenance(onn), "type.ui.caption", "color.text.tertiary")]
        for k in olda.get("kids", []):
            if k["t"] == "board":
                kids.append(copy.deepcopy(k))
        if onn == 91:
            kids.append(block("cap10 note", "Board 09 under the cap (plan; §0 L75: 90-92 = 6 = 3 + 1 + 2)", [
                "One frame: the CMP-087 stories at 1280×800. The old 91 sheet's frame-2560 (its sheet page 2, the "
                "other contracts' stories) is no longer a frame: it is carried unchanged as a DEV panel beside the "
                "frame, so CMP-044's TwoChoice, CMP-138, CMP-093, CMP-178, CMP-088 and CMP-173 stay drawn once; the "
                "blocks above that say \"frame-2560\" mean that panel."]))
        if onn == 9:
            kids.append(block("cap10 note", "Board 01 under the cap (plan; §0 L75)", [
                "Two frames drawn (dark); §0 counts four: the light pair is this board exported under the light token "
                "theme, as the Light frames and renders block above says."]))
        grp = {"t": "board", "name": f"{state} [{onn:02d}]", "o": {"dir": "column", "align": "start",
                                                                   "gap": "space.stack.sm"}, "w": 368, "kids": kids}
        ann_secs.append({"into": "annotations", "node": grp})
    if b["keys"]:
        ann_secs.append({"into": "annotations", "node": focus_block(b["keys"])})
    bline = [f"{name} → {export}",
             f"Old §0 board(s) {', '.join('%02d' % o for o in sorted(sheets))}; boards-branch §0 L{b['s0']} "
             f"({s0_cell}) names them drawn ({PIN_REV}); {n_count} frames by §0's count rule"
             + (f" ({n_drawn} drawn)" if n_drawn != n_count else "") + "; page E42-D03; file `E42-D03 boards`"]
    if nn in RENDERS:
        bline.append(f"★ greyscale and deuteranopia renders: E42-D03-{stem}-greyscale.png, "
                     f"E42-D03-{stem}-deuteranopia.png (the plan: renders on boards 01, 03, 06 and 08, 8 PNGs)")
    else:
        bline.append("No renders (the plan renders boards 01, 03, 06 and 08 only)")
    if b["keys"]:
        bline.append("Keyboard rider (the plan; §17 AC-4 / AC-5 / DoD-5): the focus-order overlay above")
    if nn == 10:
        bline.append("The keyboard board (the plan's rider): the focus order at both sizes, the panel under the 2560 "
                     "frame")
    ann_secs.append({"into": "annotations", "node": block("board", "Board", bline)})
    ann_secs.append({"into": "annotations", "node": text("footer", f"page E42-D03 · board {nn:02d} · r2",
                                                         "type.ui.caption", "color.text.tertiary")})
    col_h = est_h({"t": "board", "name": "annotations", "o": col["o"], "w": COL_W,
                   "kids": col["kids"] + [s["node"] for s in ann_secs[1:]]})
    sections += ann_secs
    livefix(nn, sections)
    w = ax + COL_W + M
    h = max(bottom, M + col_h) + M
    board_ = {"name": name, "w": w, "h": h, "x": 0, "y": 0, "o": {"fill": "color.surface.app", "clip": True}}
    return Built(board_, sections, export, stem, items_meta, col_h, bottom, {k: v[0].name for k, v in sheets.items()},
                 {k: v[1]["notes"] for k, v in sheets.items()}, n_drawn, n_count,
                 {k: v for k, v in subst_by_set.items() if v})


def merged_notes(r: Built, nn: int, grid: tuple[int, int]) -> dict[str, list[str]]:
    keys = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations")
    out: dict[str, list[str]] = {k: [] for k in keys}
    out["sources"].append(f"cap10: gen10/{r.stem}.py + gen10/cap10.py compose old id(s) "
                          f"{', '.join('%02d' % k for k in sorted(r.sheets))} ({', '.join(r.sheets.values())}) per the "
                          f"confirmed plan {PLAN_NAME} ({CONFIRMED}); boards-branch text {PIN_REV} (md5 {PIN_MD5[:8]}, "
                          f"§0 L{BOARDS[nn]['s0']}); main {MAIN_MD5[:8]} at 58660d32f unchanged")
    out["deviations"] += [
        "frames renamed from the old ids' 'frame-1280' / 'frame-2560' to '<state> · <size> [<old id>]'; node trees "
        "otherwise byte-identical to the recorded sheet",
        "root is not a flex board: the 80 px gutters have no spacing token, so frames, panels and the annotation "
        "column are placed by x/y with an 80 px margin; panels keep their offset under the frame they sat under",
    ]
    out["live_checks"] += [
        f"root '{r.board['name']}' at ({grid[0]}, {grid[1]}): {r.board['w']} x {r.board['h']} px; nothing overlaps "
        f"(80 px gutters); after relayout the annotation column (estimated {r.col_h} px) must end at least 80 px "
        "inside the root: raise the root's h if it does not",
    ]
    for onn in sorted(r.notes_src):
        for k in keys:
            for line in r.notes_src[onn].get(k) or []:
                if k == "live_checks" and r.n_subst and re.match(r"inst 'CMP-01[56] ", line):
                    continue  # fix pass: that inst is a composition now (fallbacks below), nothing to verify live
                out[k].append(scrub(f"[{onn:02d}] {line}"))
    out["live_checks"] += LIVEFIX_CHECKS.get(nn, [])
    for st, c in r.n_subst.items():
        out["fallbacks"].append(f"fix pass: {c} × {SUBST_NOTES[st]}")
        out["tokens"].append("fix pass: " + ("color.surface.hover, radius.control, space.stack.xs (CMP-015 composition)"
                                             if st.startswith("CMP-015") else
                                             "color.surface.overlay, elevation.popover, radius.control, space.inset.sm, "
                                             "space.inset.xs, type.ui.caption, color.text.primary (CMP-016 composition)"))
        out["live_checks"].append(f"fix pass: {c} × {st.split(' · ')[0]} composition replaces the inst: after "
                                  "relayout nothing in its parent may be clipped")
    return out


def walk(n: Node):
    yield n
    for k in n.get("kids", []):
        yield from walk(k)


def leaks(sheet: dict[str, Any]) -> list[str]:
    hits = [str(n.get(k))[:80] for s in sheet["sections"] for n in walk(s["node"]) for k in ("chars", "name")
            if isinstance(n.get(k), str) and LEAK.search(n[k])]
    hits += [ln[:80] for v in sheet["notes"].values() for ln in (v or []) if LEAK.search(ln)]
    hits += [sheet["board"]["name"]] if LEAK.search(sheet["board"]["name"]) else []
    return hits


def penpot_rules(sheet: dict[str, Any]) -> list[str]:
    bad = []
    for s in sheet["sections"]:
        for n in walk(s["node"]):
            if isinstance((n.get("o") or {}).get("wrap"), bool):
                bad.append(f"boolean wrap on {n.get('name')}")
            if n.get("t") == "inst" and "CMP-014" in str(n.get("set", "")) + str(n.get("name", "")):
                bad.append(f"CMP-014 Spinner inst {n.get('name')}")
    return bad


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=180, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, (lines[-1] if lines else "")


def grid_xy(nn: int, step_y: int = GRID_Y) -> tuple[int, int]:
    return ((nn - 1) % 5) * GRID_X, ((nn - 1) // 5) * step_y


def count_nodes(n: Node) -> int:
    return 1 + sum(count_nodes(k) for k in n.get("kids", []))


def write(nn: int, step_y: int) -> dict[str, Any]:
    r = build(nn)
    gx, gy = grid_xy(nn, step_y)
    r.board["x"], r.board["y"] = gx, gy
    r.board["h"] = ROOT_H[nn]  # live-check fold: the annotation foot + 80 (step_y keeps the estimate's pitch)
    if r.board["w"] > GRID_X - M:
        raise RuntimeError(f"board {nn:02d} is {r.board['w']} px wide: over the {GRID_X} px pitch")
    big = [(s["node"]["name"], len(json.dumps(s))) for s in r.sections if len(json.dumps(s)) > SECTION_HARD]
    sheet = {"board": r.board, "sections": r.sections, "export": r.export, "notes": merged_notes(r, nn, (gx, gy))}
    lk, pr = leaks(sheet), penpot_rules(sheet)
    if lk or pr or big:
        raise RuntimeError(f"board {nn:02d}: leaks {lk[:5]}; penpot rules {pr[:5]}; sections over {SECTION_HARD} {big}")
    OUT.mkdir(exist_ok=True)
    jp = OUT / f"{r.stem}.json"
    jp.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    code, vline = validate(jp)
    res = {"r": r, "json": jp, "valid": (code, vline), "grid": (gx, gy),
           "shapes": sum(count_nodes(s["node"]) for s in r.sections),
           "insts": sum(1 for s in r.sections for n in walk(s["node"]) if n["t"] == "inst"),
           "bytes": len(json.dumps(sheet, ensure_ascii=False, separators=(",", ":")))}
    md_text = md(res, nn)
    if LEAK.search(md_text):
        raise RuntimeError(f"board {nn:02d}: the .md carries a local path or agent name")
    (OUT / f"{r.stem}.md").write_text(md_text, encoding="utf-8")
    if code != 0:
        raise RuntimeError(f"{jp.name}: validator exit {code} ({vline})")
    return res


def md(res: dict[str, Any], nn: int) -> str:
    r: Built = res["r"]
    b = BOARDS[nn]
    L = [f"# {r.board['name']}", "",
         f"File `E42-D03 boards`, page `E42-D03`; export `{r.export}`; sheet `{r.stem}.json` (validated); "
         + (f"theme {b['theme']}." if b["theme"] != "dark+light" else  # the review pass's wording (board 01)
            "theme dark. (Its light pair is the same board exported under the light token theme and composited "
            "beside it.)"), "",
         f"Board {nn:02d} of the confirmed ten (plan {PLAN_NAME}, main-orchestrator {CONFIRMED}; old §0 board(s) "
         f"{', '.join('%02d' % o for o in sorted(r.sheets))}, boards-branch §0 L{b['s0']} at {PIN_REV}). Grid "
         f"({res['grid'][0]}, {res['grid'][1]}); {r.board['w']} x {r.board['h']} px; {r.n_count} frames by §0's count"
         + (f" ({r.n_drawn} drawn)" if r.n_drawn != r.n_count else "")
         + f"; footer \"page E42-D03 · board {nn:02d} · r2\".", "", "## Frames and panels", ""]
    for m in r.items:
        kind = "frame" if m["frames"] else "panel (not a frame)"
        L.append(f"- `{m['name']}` — {kind}; {m['state']}, old id [{m['old_board']:02d}] node `{m['old_node']}` of "
                 f"`{m['sheet']}` (gen/gen_{m['old_board']:02d}.py), {m['w']} x {m['h']} at ({m['x']}, {m['y']}); "
                 f"{provenance(m['old_board'])}")
    if b.get("count_note"):
        L.append(f"- count: {b['count_note']}")
    L += ["", "## Annotation column", "",
          f"- 400 px at x {r.board['w'] - COL_W - M}, estimated {r.col_h} px tall (frames and panels end at y "
          f"{r.content_bottom}).",
          "- per state: the old board's annotation blocks, unchanged (source, state and trigger, decision ids, roles, "
          "keyboard path and focus, announcement, copy keys, tokens, analytics and audit events, budget / insets / "
          "notes)." + (f" Focus-order overlay for SCR-{b['keys']} (the plan's keyboard rider)." if b["keys"] else ""),
          "", "## Renders", "",
          (f"- ★ `E42-D03-{r.stem}-greyscale.png` and `E42-D03-{r.stem}-deuteranopia.png`" if nn in RENDERS
           else "- none (the plan renders boards 01, 03, 06 and 08 only)"), "",
          "## Validator and size", "",
          f"- `{res['valid'][1]}` (exit {res['valid'][0]})",
          f"- {len(r.sections)} sections, {res['shapes']} nodes (shapes estimate; {res['insts']} instances), "
          f"{res['bytes']} bytes compact JSON", "",
          "## Live checks for the drawer (new; the old boards' carried lines are in the sheet's notes, prefixed [NN])",
          "", f"- {merged_notes(r, nn, res['grid'])['live_checks'][0]}",
          "- every inst node carried from the old boards keeps its old live check (notes.live_checks, [NN] lines)", ""]
    return "\n".join(L) + "\n"


def pack(jp: Path) -> tuple[int, str]:
    PACKED.mkdir(exist_ok=True)
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(jp), str(PACKED / jp.name)],
                         capture_output=True, text=True, timeout=300, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode == 0:  # compactOf.file -> the bare file name (committed form), sha256 re-verified
        pp = PACKED / jp.name
        raw = pp.read_text(encoding="utf-8")
        meta = json.loads(raw)["compactOf"]
        if meta["sha256"] != hashlib.sha256(jp.read_bytes()).hexdigest():
            raise RuntimeError(f"{pp.name}: compactOf.sha256 does not match {jp.name}")
        old = json.dumps(meta["file"], ensure_ascii=False)
        if raw.count(old) != 1:
            raise RuntimeError(f"{pp.name}: compactOf.file not found exactly once")
        pp.write_text(raw.replace(old, json.dumps(jp.name, ensure_ascii=False)), encoding="utf-8")
    return res.returncode, (lines[-1] if lines else "")


def step_y() -> int:
    """The grid's row pitch: 3200 unless a first-row board (01-05) is taller."""
    tallest = max(build(n).board["h"] for n in range(1, 6))
    return max(GRID_Y, math.ceil((tallest + M) / 100) * 100)


def main_one(nn: int) -> int:
    _read(MAIN_SPEC, MAIN_MD5)
    res = write(nn, step_y())
    r: Built = res["r"]
    code, line = pack(res["json"])
    print(f"{r.stem}: {res['valid'][1]} (exit {res['valid'][0]}); frames {r.n_count} (drawn {r.n_drawn}); "
          f"{r.board['w']} x {r.board['h']} at {res['grid']}; nodes {res['shapes']}; pack exit {code}: {line}")
    return 0 if code == 0 and res["valid"][0] == 0 else 1
