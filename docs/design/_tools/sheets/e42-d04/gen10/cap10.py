"""cap10b: compose E42-D04's ten confirmed boards (plan: e42d04-plan.md, confirmed by main-orchestrator
2026-10-28 17:49Z) from the old per-board sheets' frames.

Each frame is the old board's frame node tree exactly as its generator (gen/gen_NN.py, the frame builders) wrote and
validated it in E42-D04/NN-<slug>.json: only the frame's root is renamed (old boards all call theirs "frame-1280" /
"frame-2560", which would collide on one board) and given its x/y on the new board. harvest.py re-runs every source
generator in a sandbox and records which still run and match (BUILD.md). This module only reads gen/, the kit and the
old sheets. Drift fix pass (2026-10-28, BUILD.md "Fix pass 2"): the kit and gen_18, gen_30, gen_55, gen_59, gen_63 and
gen_64 were re-pinned to the boards branch f4418e83b (the carries, the cap and the CMP-044 ruling R-2) and re-run, so
their sheets (18, 30, 55, 59, 63, 64) carry today's frames; no "Known drift" remains. Fix pass 3 (2026-10-28, BUILD.md):
the same seven files and this module re-pinned to cbec19a92, the branch text with §0 / §17 / §21 restated for these ten
boards (the spec of record); each board's Board block and footer are checked against its restated §0 row.

Board: a plain (non-flex) root, fill color.surface.app, clip; frames 1:1 at x/y in the plan's rows with 80 px gutters
and an 80 px margin (no 80 px spacing token exists, so the gutters are positions, not a flex gap); ONE 400 px
annotation column to the right of the widest row, holding per state: the old board's annotation blocks (source, state
and trigger, decision ids, roles, keyboard path and focus, announcement, copy keys, tokens, analytics and audit
events, plus its security / sign-off / theme blocks; its "Board" and inset blocks dropped: the insets are not frames
and are not on these boards), the focus-order overlay on boards 01, 04, 05 and 06 (the plan's keyboard rider, quoted
from the spec), the Board block (the restated §0 row: name, export, frames, ★ renders, Status) and the footer
"page E42-D04 · board NN · r2".
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1]  # the kit folder
SHEETS = SRC.parent
G10 = SRC / "gen10"
OUT = SRC / "cap10b"  # the unpacked sheets (not committed; v4/ expands to them)
PACKED = SRC / "v4"
PIN_SPEC = G10 / "pin" / "branch-cbec19a92.md"  # git show cbec19a92 (the kit's SPEC_MD5 04dda6e1; was f4418e83b)
PIN_MD5 = "04dda6e1247e38d231de80861fccddea"
PIN_REV = "cbec19a92"
VALIDATOR = SHEETS / "tools" / "validate_sheet.py"
COMPONENTS = SHEETS / "tools" / "components.offline.json"
PACKER = SHEETS / "tools" / "compact.py"
PLAN = SRC / "spec" / "e42d04-plan.md"  # the confirmed plan (not committed)

M = 80  # margin and gutter (the brief: 80 px gutters)
COL_W = 400  # the annotation column
GRID_X, GRID_Y = 6000, 3200  # the brief's grid pitch; place() widens GRID_Y if a board is taller (BUILD.md)
SECTION_BUDGET = 14000  # the kit's per-section budget (e42d04kit.SECTION_BUDGET)

Node = dict[str, Any]


@dataclass(frozen=True)
class F:
    """One frame: the state id, the old board, the old sheet's top-level node name, the new frame name."""
    state: str
    nn: int
    old: str
    new: str


def fr(state: str, nn: int, px: int, label: str = "") -> F:
    size = {1280: "1280×800", 2560: "2560×1440"}[px]
    return F(state, nn, f"frame-{px}" if not label else label, f"{state} · {size} [{nn:02d}]")


# --- the confirmed plan (e42d04-plan.md's table), row by row
BOARDS: dict[int, dict[str, Any]] = {
    1: {"slug": "scr135-populated", "theme": "dark", "star": True, "keys": "135",
        "rows": [[fr("AL-2", 2, 1280), fr("AL-2", 2, 2560), fr("AL-3", 3, 1280)],
                 [fr("AL-18", 18, 1280), fr("AL-20", 20, 1280), fr("AL-21", 21, 1280)]]},
    2: {"slug": "scr135-tamper-failed", "theme": "dark", "star": True, "keys": "",
        "rows": [[fr("AL-13", 13, 1280), fr("AL-13", 13, 2560), fr("AD-5", 34, 1280)],
                 [F("AL-14", 14, "frame-1280 · 1 strip (SCR-148)", "AL-14 · 1 strip (SCR-148) · 1280×800 [14]"),
                  F("AL-14", 14, "frame-1280 · 2 tile (SCR-120)", "AL-14 · 2 tile (SCR-120) · 1280×800 [14]"),
                  F("AL-14", 14, "frame-1280 · 3 row (SCR-144)", "AL-14 · 3 row (SCR-144) · 1280×800 [14]")]]},
    3: {"slug": "audit-secret", "theme": "dark", "star": False, "keys": "",
        "rows": [[fr("AL-4", 4, 1280), fr("AL-4", 4, 2560)], [fr("AD-3", 32, 1280), fr("AD-3", 32, 2560)]]},
    4: {"slug": "scr136-detail", "theme": "dark", "star": False, "keys": "136",
        "rows": [[fr("AD-1", 30, 1280), fr("AD-1", 30, 2560), fr("AD-7", 36, 1280)]]},
    5: {"slug": "scr145-live-blocked", "theme": "dark", "star": False, "keys": "145",
        "rows": [[fr("FF-2", 39, 1280), fr("FF-2", 39, 2560)], [fr("FF-4", 41, 1280), fr("FF-4", 41, 2560)]]},
    6: {"slug": "scr148-on-and-dialogs", "theme": "dark", "star": False, "keys": "148",
        "rows": [[fr("MM-4", 57, 1280), fr("MM-4", 57, 2560), fr("MM-5", 58, 1280)],
                 [fr("MM-2", 55, 1280), fr("MM-6", 59, 1280)]]},
    7: {"slug": "motion-storyboard", "theme": "dark", "star": False, "keys": "",
        "rows": [[F("motion-safe", 63, "frame-1280", "motion-safe storyboard · 1280×800 [63]"),
                  F("motion-reduce", 64, "frame-1280", "motion-reduce twins · 1280×800 [64]")]]},
    8: {"slug": "status-sheet", "theme": "dark", "star": True, "keys": "",
        "rows": [[F("status-sheet", 66, "theme columns", "theme columns · 4 × 1000×1728 [66]")]]},
    9: {"slug": "diff-sheet", "theme": "dark", "star": True, "keys": "",
        "rows": [[F("diff-sheet", 67, "frame-1280", "diff-sheet · 1280×800 [67]")]]},
    10: {"slug": "light-representatives", "theme": "light", "star": False, "keys": "",
         "rows": [[fr("AL-29", 29, 1280), fr("FF-16", 53, 1280), fr("MM-9", 62, 1280)]]},
}
# frames a top-level node holds (board 08's container holds the four theme frames, §0 counts four)
FRAMES_IN = {"theme columns": 4}
# the keyboard rider (§0 L105-108): spec lines quoted per screen (pinned spec cbec19a92; §4, §5, §9, §10 Keys; L131,
# D02 D16-D18; L629, R-2's "skipped while natively disabled"), moved from f4418e83b by linemap.restated_line() (+29)
KEY_LINES = {"135": [(295, 304), (131, 131), (629, 629)], "136": [(351, 354), (131, 131)],
             "145": [(546, 548), (131, 131)], "148": [(590, 590), (131, 131), (629, 629)]}
RIDER = (105, 108)  # §0's Keyboard rider bullet (restated): boards 01, 04, 05 and 06 carry the overlays
DROP_BLOCKS = ("Board", "Inset")

# --- known drift: none. The fix pass's DRIFT table (gen10/cap10.py.pre-drift) recorded
# six states drawn before R-2, G-31 and G-41; the drift fix pass re-pinned their generators and redrew them (BUILD.md).
BRANCH = "design/e42-d04-boards cbec19a92 (md5 04dda6e1)"
# finding 4 is closed: cbec19a92 restates §0 (the ten boards' table L78-89, Count L91-97, the Not-drawn list L98-104,
# the keyboard rider L105-108), §17's AC-4 / DoD-5 trace and §21's board pointers for this set (Fix pass 3)
S0_HEAD = "| NN  | Board (slug)"  # the restated §0 table's header row


def s0_row(nn: int) -> tuple[int, list[str]]:
    """Board nn's row of the restated §0 table: (line, cells NN, slug, theme, frames, ★, Status, Evidence)."""
    lines = spec_lines()
    head = next(i for i, x in enumerate(lines, 1) if x.startswith(S0_HEAD))
    for i in range(head + 2, head + 14):
        cells = [c.strip() for c in lines[i - 1].strip().strip("|").split("|")]
        if cells[0] == f"{nn:02d}":
            return i, cells
    raise RuntimeError(f"board {nn:02d}: no row in §0's table (L{head})")


def s0_line(prefix: str) -> tuple[int, int]:
    """A restated §0 bullet's first and last line ("- **Count.**" …)."""
    lines = spec_lines()
    a = next(i for i, x in enumerate(lines, 1) if x.startswith(prefix))
    b = next(i for i in range(a + 1, len(lines) + 1) if lines[i - 1].startswith("- **") or not lines[i - 1].strip())
    return a, b - 1


# --- reading the old sheets
def old_sheet(nn: int) -> tuple[Path, dict[str, Any]]:
    p = next(SRC.glob(f"{nn:02d}-*.json"))
    return p, json.loads(p.read_text(encoding="utf-8"))


def frame_sections(sheet: dict[str, Any], top: str) -> list[dict[str, Any]]:
    """The old sheet's sections that build the top-level node `top`: its own section and every later one under it."""
    secs = [s for s in sheet["sections"] if (s["into"] == "" and s["node"]["name"] == top)
            or s["into"] == top or s["into"].startswith(top + "/")]
    if not secs or secs[0]["into"] != "":
        raise ValueError(f"{top!r}: no top-level section")
    return secs


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


def size_of(secs: list[dict[str, Any]]) -> tuple[int, int]:
    """A frame's w x h (the theme-columns container: its kids, row, gap space.inset.lg = 16 px)."""
    head = secs[0]["node"]
    if head.get("w") and head.get("h"):
        return int(head["w"]), int(head["h"])
    kids = [s["node"] for s in secs[1:] if s["into"] == head["name"]] + head.get("kids", [])
    ws = [int(k["w"]) for k in kids]
    return sum(ws) + 16 * (len(ws) - 1), max(int(k["h"]) for k in kids)


def old_annotations(sheet: dict[str, Any]) -> Node:
    secs = [s for s in sheet["sections"] if s["into"] == "" and s["node"]["name"] == "annotations"]
    if len(secs) != 1 or any(s["into"].startswith("annotations") for s in sheet["sections"]):
        raise ValueError("expected one annotation section")
    return secs[0]["node"]


def label_of(block: Node) -> str:
    for k in block.get("kids", []):
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


def spec_lines() -> list[str]:
    raw = PIN_SPEC.read_bytes()
    if hashlib.md5(raw).hexdigest() != PIN_MD5:
        raise RuntimeError("pinned spec md5")
    return raw.decode("utf-8").split("\n")


def quote(a: int, b: int) -> str:
    """Spec L a-b as one line: markdown ticks, bold marks and table pipes dropped, whitespace collapsed; a Keys item is
    cut before its next bold item (Roles., Events.)."""
    t = " ".join(ln.strip() for ln in spec_lines()[a - 1:b])
    t = re.split(r" \*\*(?!Keys)[A-Z][a-z]+\.\*\*", t)[0]
    t = t.replace("`", "").replace("**", "").strip()
    if t.startswith("|"):
        t = " — ".join(c.strip() for c in t.strip("|").split("|"))
    t = re.sub(r"^- ", "", re.sub(r"\s+", " ", t))
    return f"L{a}{'-' + str(b) if b != a else ''}: {t}"


def focus_block(screen: str) -> Node:
    vals = [quote(a, b) for a, b in KEY_LINES[screen]]
    return block("focus order overlay", f"Focus order overlay · SCR-{screen} (keyboard rider, §0 L{RIDER[0]}-{RIDER[1]}: "
                 "§4, §5, §9, §10 Keys; D02 D18, no new binding; Enter in a reason field never confirms; §17 AC-4 / "
                 "DoD-5)", vals)


def est_height(n: Node) -> int:
    """The shell kit's estimate (E42-D03 e42kit.est_height: per-typo font metrics, word wrap at the text's w, column
    gaps and pads); the live relayout measures the real height."""
    sys.path.insert(0, str(SHEETS / "e42-d03"))
    import e42kit  # noqa: E402  (read-only use of the shell kit's estimator)
    return int(math.ceil(e42kit.est_height(n)))


# --- provenance: the six redrawn boards from harvest.json (re-run on the restated branch text cbec19a92, Fix pass 3); every
# other board from harvest.json.pre-drift (re-run on the capped 1ef40f20b with the pre-drift kit, when its frames were
# proven): their frames are the recorded ones, untouched by the drift fix pass
REDRAWN = (18, 30, 55, 59, 63, 64)


def provenance(nn: int) -> str:
    redrawn = nn in REDRAWN
    h = json.loads((G10 / ("harvest.json" if redrawn else "harvest.json.pre-drift")).read_text(encoding="utf-8")).get(
        f"{nn:02d}")
    if not h:
        return "not harvested"
    if redrawn:
        if h["exit"] == 0 and h.get("frames_equal"):
            return ("gen_%02d.py re-pinned and re-run on the restated branch text %s (drift fix pass and Fix pass 3, "
                    "2026-10-28; sandbox re-run: frames byte-equal to the sheet); its L-numbers are %s's"
                    % (nn, PIN_REV, PIN_REV))
        raise RuntimeError(f"gen_{nn:02d}.py: the redrawn board's sandbox re-run failed or differs: {h['last'][:120]}")
    if h["exit"] == 0:
        return ("gen_%02d.py re-run in the sandbox on the pinned capped spec: frames byte-equal to the recorded sheet; "
                "its L-numbers the capped 1ef40f20b's" % nn) if h.get("frames_equal") else (
            "gen_%02d.py re-run: FRAMES DIFFER (see BUILD.md)" % nn)
    return ("recorded output of gen_%02d.py, its L-numbers the capped 1ef40f20b's (the generator refuses on today's "
            "tree: %s)" % (nn, h["last"][:140]))


# --- the board
def board_name(nn: int) -> tuple[str, str]:
    b = BOARDS[nn]
    tops = [f for row in b["rows"] for f in row]
    sizes = []
    for f in tops:
        s = "1000×1728" if f.old == "theme columns" else ("2560×1440" if "2560" in f.new else "1280×800")
        if s not in sizes:
            sizes.append(s)
    sz = "+".join(sorted(sizes, key=lambda s: int(s.split("×")[0])))
    return f"E42-D04 / {nn:02d} {b['slug']} · {sz} · {b['theme']}", sz


def build(nn: int) -> dict[str, Any]:
    b = BOARDS[nn]
    name, sizes = board_name(nn)
    stem = f"{nn:02d}-{b['slug']}"
    export = f"docs/design/E42/img/E42-D04-{stem}.png"
    sections: list[dict[str, Any]] = []
    frames_meta: list[dict[str, Any]] = []
    y = M
    row_w = 0
    rows_meta = []
    sheets: dict[int, tuple[Path, dict[str, Any]]] = {}
    for r, row in enumerate(b["rows"], 1):
        x, h_row = M, 0
        for f in row:
            sheets.setdefault(f.nn, old_sheet(f.nn))
            secs = frame_sections(sheets[f.nn][1], f.old)
            w, h = size_of(secs)
            sections += rename(secs, f.old, f.new, x, y)
            frames_meta.append({"name": f.new, "state": f.state, "old_board": f.nn, "old_node": f.old,
                                "sheet": sheets[f.nn][0].name, "x": x, "y": y, "w": w, "h": h, "row": r,
                                "frames": FRAMES_IN.get(f.old, 1), "sections": len(secs)})
            x += w + M
            h_row = max(h_row, h)
        rows_meta.append({"row": r, "width": x - 2 * M, "height": h_row,
                          "frames": [f.new for f in row]})
        row_w = max(row_w, x - M)
        y += h_row + M
    frames_bottom = y
    ax = row_w + M
    # annotation column
    title = text("title", f"{nn:02d} {b['slug']} · {sizes} · {b['theme']}", "type.ui.heading-sm")
    sub = text("subtitle", "E42-D04 board %02d of the ten in §0's table (L%d, %s; plan confirmed 2026-10-28 17:49Z): the "
               "frames 1:1 in its rows, 80 px gutters, each named by its state and earlier id; per state below, that "
               "id's annotation (its frames' source, state and trigger, decision ids, roles, keyboard path and focus, "
               "announcement, copy keys, tokens, analytics and audit events)." % (nn, s0_row(nn)[0], PIN_REV),
               "type.ui.caption", "color.text.tertiary")
    col = {"t": "board", "name": "annotations", "o": {"dir": "column", "align": "start", "gap": "space.stack.sm",
                                                       "pad": "space.inset.lg"}, "w": COL_W, "x": ax, "y": M,
           "kids": [title, sub]}
    ann_secs = [{"into": "", "node": col}]
    groups: dict[tuple[str, int], list[str]] = {}
    for fm in frames_meta:
        groups.setdefault((fm["state"], fm["old_board"]), []).append(fm["name"])
    dropped: list[str] = []
    for (state, onn), names in groups.items():
        old = old_annotations(sheets[onn][1])
        kids: list[Node] = [text("heading", f"{state} [{onn:02d}] ({sheets[onn][0].stem})",
                                 "type.ui.heading-sm"),
                            text("frames", "Frames: " + " · ".join(names), "type.ui.caption", "color.text.secondary"),
                            text("provenance", provenance(onn), "type.ui.caption", "color.text.tertiary")]
        for k in old.get("kids", []):
            if k["t"] != "board":
                continue  # the old title and footer: replaced by the heading above and this board's footer
            lab = label_of(k)
            if lab.startswith(DROP_BLOCKS):
                dropped.append(f"[{onn:02d}] {lab[:60]}")
                continue
            kids.append(copy.deepcopy(k))
        grp = {"t": "board", "name": f"{state} [{onn:02d}]",
               "o": {"dir": "column", "align": "start", "gap": "space.stack.sm"}, "w": 368, "kids": kids}
        ann_secs.append({"into": "annotations", "node": grp})
    if b["keys"]:
        ann_secs.append({"into": "annotations", "node": focus_block(b["keys"])})
    n_frames = sum(fm["frames"] for fm in frames_meta)
    row_ln, cells = s0_row(nn)
    if (cells[1].strip("`"), cells[2], cells[4] == "★") != (b["slug"], b["theme"], b["star"]):
        raise RuntimeError(f"board {nn:02d}: the plan ({b['slug']}, {b['theme']}, ★ {b['star']}) is not §0 L{row_ln}'s "
                           f"{cells[1:5]}")
    ca, cb = s0_line("- **Count.**")
    bline = [f"{name} → {export} (§0 L61-62, L67-69)",
             f"§0 L{row_ln}: {cells[3].replace('`', '')}; {n_frames} frames in {len(b['rows'])} row(s); Status "
             f"{cells[5]}; page E42-D04"]
    if b["star"]:
        bline.append(f"★ greyscale and deuteranopia renders: E42-D04-{stem}-greyscale.png, "
                     f"E42-D04-{stem}-deuteranopia.png (§0 L68-69; Count L{ca}-{cb}: renders on boards 01, 02, 08 "
                     "and 09, 18 PNGs)")
    if b["keys"]:
        bline.append(f"Keyboard rider (§0 L{RIDER[0]}-{RIDER[1]}; §17 AC-4 / DoD-5): the focus-order overlay above")
    ann_secs.append({"into": "annotations", "node": block("board", "Board", bline)})
    ann_secs.append({"into": "annotations", "node": text("footer", f"page E42-D04 · board {nn:02d} · r2",
                                                         "type.ui.caption", "color.text.tertiary")})
    col_h = est_height({"t": "board", "name": "annotations", "o": col["o"],
                        "kids": col["kids"] + [s["node"] for s in ann_secs[1:]]})
    sections += ann_secs
    w = ax + COL_W + M
    h = max(frames_bottom, M + col_h + M)
    board_ = {"name": name, "w": w, "h": h, "x": 0, "y": 0,
              "o": {"fill": "color.surface.app", "clip": True}}
    return {"board": board_, "sections": sections, "export": export, "stem": stem, "frames": frames_meta,
            "rows": rows_meta, "col_h": col_h, "frames_bottom": frames_bottom, "dropped": dropped,
            "sheets": {k: v[0].name for k, v in sheets.items()}, "n_frames": n_frames,
            "notes_src": {k: v[1]["notes"] for k, v in sheets.items()}}


def merged_notes(r: dict[str, Any], nn: int, grid: tuple[int, int]) -> dict[str, list[str]]:
    keys = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations")
    out: dict[str, list[str]] = {k: [] for k in keys}
    out["sources"].append(f"cap10b: gen10/{r['stem']}.py + gen10/cap10.py compose the earlier ids "
                          f"{', '.join('%02d' % k for k in sorted(r['sheets']))} ({', '.join(r['sheets'].values())}) "
                          f"per the confirmed plan {PLAN} (2026-10-28 17:49Z), as §0's table states it (L{s0_row(nn)[0]}); "
                          f"spec pinned at {BRANCH} (gen10/pin/branch-cbec19a92.md)")
    out["deviations"] += [
        "frames renamed from the earlier ids' 'frame-1280' / 'frame-2560' to '<state> · <size> [<old id>]' (§0 L62-63's "
        "form; two ids' frames share a row and sibling names must be unique); node trees otherwise byte-identical",
        "root is not a flex board: the plan's 80 px gutters have no spacing token (space.* tops at 96 / 64), so frames "
        "and the annotation column are placed by x/y with an 80 px margin",
        "old annotation blocks not carried: " + ("; ".join(r["dropped"]) if r["dropped"] else "none")
        + " (the insets are not frames and are not drawn on these boards)",
    ]
    out["live_checks"] += [
        f"root '{r['board']['name']}' at ({grid[0]}, {grid[1]}): {r['board']['w']} x {r['board']['h']} px; frames at "
        "their x/y never overlap (80 px gutters); after relayout the annotation column (estimated "
        f"{r['col_h']} px tall) must end inside the root: raise the root's h if it does not",
    ]
    for onn in sorted(r["notes_src"]):
        for k in keys:
            for line in r["notes_src"][onn].get(k) or []:
                out[k].append(f"[{onn:02d}] {line}")
    return out


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, (lines[-1] if lines else "")


def grid_xy(nn: int, step_y: int = GRID_Y) -> tuple[int, int]:
    return ((nn - 1) % 5) * GRID_X, ((nn - 1) // 5) * step_y


def count_nodes(n: Node) -> int:
    return 1 + sum(count_nodes(k) for k in n.get("kids", []))


def write(nn: int, step_y: int) -> dict[str, Any]:
    r = build(nn)
    gx, gy = grid_xy(nn, step_y)
    r["board"]["x"], r["board"]["y"] = gx, gy
    if r["board"]["w"] > GRID_X - M:
        raise RuntimeError(f"board {nn:02d} is {r['board']['w']} px wide: over the {GRID_X} px pitch")
    big = [(s["node"]["name"], len(json.dumps(s, ensure_ascii=False))) for s in r["sections"]
           if len(json.dumps(s, ensure_ascii=False)) > SECTION_BUDGET]
    sheet = {"board": r["board"], "sections": r["sections"], "export": r["export"],
             "notes": merged_notes(r, nn, (gx, gy))}
    OUT.mkdir(exist_ok=True)
    jp = OUT / f"{r['stem']}.json"
    jp.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    code, vline = validate(jp)
    r.update({"json": jp, "valid": (code, vline), "big": big, "grid": (gx, gy),
              "shapes": sum(count_nodes(s["node"]) for s in r["sections"]),
              "insts": sum(1 for s in r["sections"] for n in walk(s["node"]) if n["t"] == "inst"),
              "bytes": len(json.dumps(sheet, ensure_ascii=False, separators=(",", ":")))})
    (OUT / f"{r['stem']}.md").write_text(md(r, nn), encoding="utf-8")
    if code != 0 or big:
        raise RuntimeError(f"{jp.name}: validator exit {code} ({vline}); sections over budget {big}")
    return r


def walk(n: Node):
    yield n
    for k in n.get("kids", []):
        yield from walk(k)


def md(r: dict[str, Any], nn: int) -> str:
    b = BOARDS[nn]
    L = [f"# {r['board']['name']}", "",
         f"File `E42-D04 boards`, page `E42-D04`; export `{r['export']}`; sheet `{r['stem']}.json` (validated); "
         f"theme {b['theme']}.", "",
         f"Board {nn:02d} of the confirmed ten (plan {PLAN.name}, main-orchestrator 2026-10-28 17:49Z; §0 L{s0_row(nn)[0]} "
         f"of {BRANCH}). Grid "
         f"({r['grid'][0]}, {r['grid'][1]}); {r['board']['w']} x {r['board']['h']} px; {r['n_frames']} frames; "
         f"footer \"page E42-D04 · board {nn:02d} · r2\".", "", "## Frames", ""]
    for fm in r["frames"]:
        extra = f" (holds {fm['frames']} frames)" if fm["frames"] > 1 else ""
        L.append(f"- `{fm['name']}`{extra} — {fm['state']}, id [{fm['old_board']:02d}] node `{fm['old_node']}` "
                 f"of `{fm['sheet']}` (gen/gen_{fm['old_board']:02d}.py), {fm['w']} x {fm['h']} at "
                 f"({fm['x']}, {fm['y']}), row {fm['row']}; {provenance(fm['old_board'])}")
    L += ["", "## Rows", ""]
    for rw in r["rows"]:
        L.append(f"- row {rw['row']}: {rw['width']} px wide (frames and gutters), {rw['height']} px tall: "
                 + " · ".join(rw["frames"]))
    L += ["", "## Annotation column", "",
          f"- 400 px at x {r['board']['w'] - COL_W - M}, estimated {r['col_h']} px tall "
          f"(frames end at y {r['frames_bottom'] - M}).",
          "- per state: the old board's blocks (source, state and trigger, decision ids, roles, keyboard path and "
          "focus, announcement, copy keys, tokens, analytics and audit events, and any security / sign-off / theme "
          "block)." + (" Focus-order overlay for SCR-" + b["keys"] + " (the plan's keyboard rider)." if b["keys"]
                        else ""),
          "- dropped: " + ("; ".join(r["dropped"]) or "none")]
    row_ln, cells = s0_row(nn)
    L += ["", "## Spec of record (restated §0)", "",
          f"- §0 L{row_ln} ({BRANCH}): `{cells[1].strip('`')}` · {cells[2]} · {cells[3].replace('`', '')} · "
          f"{cells[4]} · {cells[5]} · {cells[6].replace('`', '')}"]
    L += ["",
          "## Renders", "",
          (f"- ★ `E42-D04-{r['stem']}-greyscale.png` and `E42-D04-{r['stem']}-deuteranopia.png`" if b["star"]
           else "- none (the plan renders boards 01, 02, 08 and 09 only)"), "",
          "## Validator and size", "",
          f"- `{r['valid'][1]}` (exit {r['valid'][0]})",
          f"- {len(r['sections'])} sections, {r['shapes']} nodes (shapes estimate, instances counted once: "
          f"{r['insts']}), {r['bytes']} bytes compact JSON", "",
          "## Live checks for the drawer (new; the old boards' carried lines are in the sheet's notes, prefixed "
          "[NN])", ""]
    L += [f"- {x}" for x in merged_notes(r, nn, r["grid"])["live_checks"][:1]]
    L += ["- every inst node carried from the old boards keeps its old live check (notes.live_checks, [NN] lines)", ""]
    return "\n".join(L) + "\n"


def pack(jp: Path) -> tuple[int, str]:
    PACKED.mkdir(exist_ok=True)
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(jp), str(PACKED / jp.name)],
                         capture_output=True, text=True, timeout=300, check=False)
    return res.returncode, (res.stdout + res.stderr).strip().splitlines()[-1] if (res.stdout + res.stderr).strip() else ""


def step_y() -> int:
    """The grid's row pitch: the brief's 3200 px unless a board (the first grid row: 01-05) is taller."""
    tallest = max(build(n)["board"]["h"] for n in range(1, 6))
    return max(GRID_Y, math.ceil((tallest + M) / 100) * 100)


def main_one(nn: int) -> int:
    r = write(nn, step_y())
    code, line = pack(r["json"])
    print(f"{r['stem']}: {r['valid'][1]} (exit {r['valid'][0]}); {r['n_frames']} frames; "
          f"{r['board']['w']} x {r['board']['h']} at {r['grid']}; nodes {r['shapes']}; pack exit {code}: {line}")
    return 0 if code == 0 else 1
