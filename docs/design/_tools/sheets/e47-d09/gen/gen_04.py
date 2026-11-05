"""E47-D09 / 04 node-move: SCR-082 node Move mode — entry, the view following, Enter places, Esc restores, and the
200 % / text-scale inset (§7; DE-17, DE-18)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 4
S7 = k.L("## 7. The rule node graph")
STEP = 24  # FALLBACKS layout-step (D09-G6)
NODE_W, NODE_H = 7 * STEP, 2 * STEP
PAL_W, HEAD_H, FOOT_H = 168, 40, 44
CANVAS_W, CANVAS_H = k.MAIN_W - PAL_W, k.BODY_H - HEAD_H - FOOT_H  # 816 x 644
RULE = "ATR trail 2x"  # `14` SCR-082's wireframe rule and nodes (synthetic)
GRAPH = {  # name -> (kind, word, col, row): the wireframe's nodes on the 24 px grid (kit layout)
    "on bar close": ("trigger", "Trigger", 1, 1), "atr 14": ("condition", "Metric", 1, 5),
    "x 2.0": ("logic", "Logic", 9, 5), "swing_low 5": ("condition", "Metric", 1, 9),
    "max": ("logic", "Logic", 17, 7), "position_side == long": ("condition", "Logic", 1, 13),
    "modify_stop": ("action", "Action", 25, 9)}
EDGES = (("on bar close", "atr 14"), ("atr 14", "x 2.0"), ("x 2.0", "max"), ("swing_low 5", "max"),
         ("max", "modify_stop"), ("position_side == long", "modify_stop"))
MOVER = "swing_low 5"
START = GRAPH[MOVER][2:]
PLACED = (START[0] + 3, START[1] + 1)  # → ×3, ↓ ×1, then Enter
FAR = (START[0] + 30, START[1] + 3)  # Shift+→ ×3 (thirty steps, past the right edge), then ↓ ×3


def view_shift(col: int, view_cols: int = CANVAS_W // STEP) -> int:
    """The view follows at the edge: the cells it scrolls so the node's right edge + one cell stays in view."""
    return max(0, col + NODE_W // STEP + 1 - view_cols)


def node_box(name: str, col: int, row: int, *, focused: bool = False, sx: int = 0) -> c.Node:
    kind, word, _c0, _r0 = GRAPH[name]
    kids = [k.rect("kind stripe", 4, NODE_H, k.NODE[kind], x=0, y=0),
            k.text("name", name, k.BODY_STRONG, k.TEXT_1, x=12, y=6),
            k.text("kind", word, k.CAPTION, k.TEXT_2, x=12, y=28),
            k.ellipse("port in", 8, 8, {"fill": k.TEXT_2}, x=0, y=NODE_H // 2 - 4),
            k.ellipse("port out", 8, 8, {"fill": k.TEXT_2}, x=NODE_W - 8, y=NODE_H // 2 - 4)]
    b = k.box(f"node · {name}", kids, {"fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                       "strokeAlign": "inner", "radius": k.R_CARD}, w=NODE_W, h=NODE_H,
              note=f'CMP-147..150 node; accessible name "{name}"')
    if focused:
        b = k.focus_ring(b, radius=k.R_CARD)
        e = k.extent("normal")
        return dict(b, x=(col - sx) * STEP - e, y=row * STEP - e)
    return dict(b, x=(col - sx) * STEP, y=row * STEP)


def edge(a: tuple[int, int], b: tuple[int, int], name: str, sx: int) -> list[c.Node]:
    """An orthogonal edge from a's out port to b's in port: across, down / up, across (2 px, color.border.strong)."""
    x1, y1 = (a[0] - sx) * STEP + NODE_W, a[1] * STEP + NODE_H // 2
    x2, y2 = (b[0] - sx) * STEP, b[1] * STEP + NODE_H // 2
    xm = (x1 + x2) // 2
    out = [k.rect(f"edge {name} · 1", max(2, xm - x1), 2, k.BORDER_STRONG, x=min(x1, xm), y=y1),
           k.rect(f"edge {name} · 2", 2, max(2, abs(y2 - y1)), k.BORDER_STRONG, x=xm, y=min(y1, y2)),
           k.rect(f"edge {name} · 3", max(2, abs(x2 - xm)), 2, k.BORDER_STRONG, x=min(xm, x2), y=y2)]
    return out


def canvas(pos: dict[str, tuple[int, int]], *, focus: str | None = None, sx: int = 0, ghost: tuple[int, int] | None
           = None, strip: str | None = None, typo: str = k.BODY, w_: int = CANVAS_W, h_: int = CANVAS_H) -> c.Node:
    """CMP-146 canvas: the 24 px grid, the edges, the nodes; Move mode's strip (W-16) pushes the canvas down."""
    k.fallback("layout-step")
    grid = [k.rect(f"v {i}", 1, h_, k.GRID, x=i * STEP, y=0) for i in range(w_ // STEP + 1)]
    grid += [k.rect(f"h {j}", w_, 1, k.GRID, x=0, y=j * STEP) for j in range(h_ // STEP + 1)]
    edges = [e for a, b in EDGES for e in edge(pos[a], pos[b], f"{a} to {b}", sx)]
    nodes = [node_box(n, *pos[n], focused=n == focus, sx=sx) for n in GRAPH]
    kids: list[c.Node] = [k.box("grid", grid, None, w=w_, h=h_, x=0, y=0),
                          k.box("edges", edges, None, w=w_, h=h_, x=0, y=0)]
    if ghost:
        kids.append(k.box("origin (restore point)", [], {"stroke": k.BORDER_SUBTLE, "strokeWidth": k.THICK,
                                                         "strokeAlign": "inner", "radius": k.R_CARD},
                          w=NODE_W, h=NODE_H, x=(ghost[0] - sx) * STEP, y=ghost[1] * STEP,
                          note="the position held at entry (Esc restores it)"))
    kids.append(k.box("nodes", nodes, None, w=w_, h=h_, x=0, y=0))
    plane = k.box("CMP-146 canvas", kids, {"fill": k.CANVAS, "clip": True}, w=w_,
                  h=h_ - (0 if strip is None else strip_h(strip, typo, w_)),
                  note='the canvas; the node list (Alt+L) is its keyboard twin')
    if strip is None:
        return plane
    s = k.hbox("Move mode strip", [k.icon("glyph", "info", k.INFO_STRONG),
                                   k.text("instruction", strip, typo, k.TEXT_1, w=w_ - 2 * 12 - 16 - 8)],
               {"gap": k.INSET_SM, "padX": k.INSET_MD, "padY": k.INSET_SM, "fill": k.RAISED, "align": "start"},
               w=w_, h=strip_h(strip, typo, w_), note="the mode's visible instruction (W-16); role=status")
    return k.vbox("canvas · Move mode", [s, plane], None, w=w_, h=h_)


def strip_h(strip: str, typo: str, w_: int) -> int:
    return int(k.text_h(typo, k.text_lines(strip, typo, w_ - 2 * 12 - 16 - 8))) + 2 * 8


def page(cv: c.Node, *, w_: int = k.MAIN_W) -> c.Node:
    k.copy_gap(f'"{RULE}", the node words, "Form", "Graph", the palette groups (Triggers, Metrics, Logic, Actions) and '
               '"Validate", "Simulate", "Save": `14` SCR-082\'s wireframe (`14`:1931-1946), synthetic')
    head = k.hbox("header", [k.text("h1", f"Rule: {RULE}", k.HEADING_SM, k.TEXT_1),
                             k.hbox("CMP-235 Form | Graph", [k.button("Form", "ghost"), k.button("Graph", "secondary")],
                                    {"gap": k.INSET_XS}, h=k.CONTROL_H)],
                  {"gap": k.INSET_LG, "padX": k.INSET_LG, "fill": k.APP}, w=w_, h=HEAD_H)
    groups = []
    for gname in ("Triggers", "Metrics", "Logic", "Actions"):
        groups += [k.text(f"group {gname}", gname, k.LABEL, k.TEXT_2), k.placeholder(f"{gname} entry 1", 104),
                   k.placeholder(f"{gname} entry 2", 80)]
    pal = k.vbox("CMP-236 node palette", groups, {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.RAISED},
                 w=PAL_W, h=k.BODY_H - HEAD_H - FOOT_H)
    foot = k.hbox("footer", [k.button("Validate"), k.button("Simulate"), k.button("Save")],
                  {"gap": k.INSET_SM, "padX": k.INSET_LG, "fill": k.APP}, w=w_, h=FOOT_H)
    return k.vbox("SCR-082 rule editor · graph", [head, k.hbox("work", [pal, cv], {"align": "start"}, w=w_,
                                                              h=k.BODY_H - HEAD_H - FOOT_H), foot], None, w=w_,
                  h=k.BODY_H)


CV_X, CV_Y = k.NAV_W + PAL_W, k.TOP_H + HEAD_H  # the canvas's origin in frame coordinates
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12


def positions(mover: tuple[int, int]) -> dict[str, tuple[int, int]]:
    p = {n: (v[2], v[3]) for n, v in GRAPH.items()}
    p[MOVER] = mover
    return p


def mark_node(col: int, row: int, sx: int = 0, y_off: int = 0) -> c.Node:
    return k.marker(1, CV_X + (col - sx) * STEP - 26, CV_Y + y_off + row * STEP + 14, name="stop 1 · the node")


def w16() -> str:
    return k.w("W-16", MOVER)


def frame(state: str, mover: tuple[int, int], *, mode: bool, sx: int = 0, ghost: bool = False,
          ov: list[c.Node], note: str) -> c.Node:
    s = w16() if mode else None
    cv = canvas(positions(mover), focus=MOVER, sx=sx, ghost=START if ghost else None, strip=s)
    return k.page_window(k.frame_for(NN, state), page(cv), overlays=ov, note=note)


def y_off(mode: bool) -> int:
    return strip_h(w16(), k.BODY, CANVAS_W) if mode else 0


def frame_move_mode() -> tuple[c.Node, tuple[str, list[str]]]:
    st = "node/move-mode"
    ov = [mark_node(*START, y_off=y_off(True)),
          k.callout("enter", ["M on the focused node (or its menu › Move, Shift+F10):", f"the strip shows W-16; Tab "
                              "is captured by the mode; the position is held as the restore point"], RX, 120, RW)]
    fr = frame(st, START, mode=True, ov=ov, note="M entered Move mode on the focused node")
    blk = [f"§7 L{k.L('- **Move a node (DE-17).**', start=S7)}: M (PROPOSED rules.move_node, scoped to the Rules "
           "canvas, remappable, K-12; D09-Q1) or the node's context menu › Move",
           f"{k.de('DE-17')}; {k.wcite('W-16')}: \"{w16()}\"",
           f"Drawn: {RULE} (`14` SCR-082's nodes); {MOVER} at column {START[0]}, row {START[1]} on the 24 px grid "
           "(D09-G6: no layout step is defined; kit choice)"]
    return fr, k.frame_block(k.frame_for(NN, st), blk, keyboard="M enters; arrows one step, Shift ×10; Enter "
                                                                "places; Esc restores", waits=["D09-G6"])


def frame_view_follows() -> tuple[c.Node, tuple[str, list[str]]]:
    st = "node/view-follows"
    sx = view_shift(FAR[0])
    yo = y_off(True)
    ov = [mark_node(*FAR, sx=sx, y_off=yo),
          k.tag(f"view scrolled {sx} cells right", CV_X + 8, CV_Y + yo + 8, name="tag · view scrolled"),
          c.say("W-15", "W-15", MOVER, FAR[0], FAR[1], x=RX, y=120, wd=RW,
                head="Shift+→ ×3 (30 steps), ↓ ×3 (polite, D5 cadence):",
                extra=[f"The view follows at the edge: {sx} cells ({sx * STEP} px); no separate pan key "
                       "(Space+drag stays the pointer path)"])]
    fr = frame(st, FAR, mode=True, sx=sx, ghost=True, ov=ov,
               note=f"the node moved past the edge; the canvas scrolled {sx} cells to keep it in view")
    blk = [f"§7 L{k.L('- **Pan (DE-18).**', start=S7)}: the view follows a moving node at the edge, as the chart "
           "cursor does; outside Move mode a node-list row scrolls the canvas to the node (O11)",
           f"{k.de('DE-18')}; columns count from the canvas origin, so W-15 reads column {FAR[0]} after the scroll",
           f"The restore point is outlined (color.border.subtle) at column {START[0]}, row {START[1]}; the "
           "announcements coalesce (§6: at most once per 500 ms, the final within 250 ms)"]
    return fr, k.frame_block(k.frame_for(NN, st), blk, keyboard="Shift+→ ten steps, ↓ one; the view follows",
                             waits=["D09-G6"])


def frame_placed() -> tuple[c.Node, tuple[str, list[str]]]:
    st = "node/placed"
    ov = [mark_node(*PLACED),
          c.say("W-15", "W-15", MOVER, *PLACED, x=RX, y=120, wd=RW, head="→ ×3, ↓ ×1, then Enter (polite):",
                extra=["Enter places it: one undo step on the shared stack; the mode ends, focus stays on the node"])]
    fr = frame(st, PLACED, mode=False, ov=ov, note="Enter placed the node; Move mode ended")
    blk = [f"§7 L{k.L('- **Move a node (DE-17).**', start=S7)}: Enter places it as one undo step on the shared "
           "stack; both Enter and Esc leave the mode with focus on the node",
           f"{k.krule('K-4')}: a local, undoable object; {k.wcite('W-15')}"]
    return fr, k.frame_block(k.frame_for(NN, st), blk, keyboard="Enter places; Ctrl+Z undoes the move",
                             waits=["D09-G6"])


def frame_escaped() -> tuple[c.Node, tuple[str, list[str]]]:
    st = "node/escaped"
    ov = [mark_node(*START),
          c.say("W-4", "W-4", MOVER, x=RX, y=120, wd=RW, head="→ ×3, then Esc (polite):",
                extra=[f"The position held at entry is restored: column {START[0]}, row {START[1]}; nothing to undo"])]
    fr = frame(st, START, mode=False, ov=ov, note="Esc restored the node and left Move mode")
    blk = [f"§7 L{k.L('- **Move a node (DE-17).**', start=S7)}: Esc restores the position held at entry",
           f"{k.krule('K-5')}: a local object says W-4; {k.wcite('W-4')}",
           "§13 2.1.2: Move mode leaves by Esc; no keyboard trap"]
    return fr, k.frame_block(k.frame_for(NN, st), blk, keyboard="Esc restores and leaves the mode",
                             waits=["D09-G6"])


T150 = {k.BODY: k.HEADING_LG}  # FALLBACKS type-150: body 13 -> heading-lg 20 (the strip's role)


def strip_200(name: str, typo: str, x: int) -> tuple[c.Node, int]:
    """One 640 CSS px strip: the graph header and the canvas at 640 px, the Move-mode strip at typo."""
    w_, h_ = 640, 800
    s = w16()
    sh = strip_h(s, typo, w_)
    cv = canvas(positions(START), focus=MOVER, strip=s, typo=typo, w_=w_, h_=h_ - HEAD_H)
    head = k.hbox("header", [k.text("h1", f"Rule: {RULE}", k.HEADING_SM if typo == k.BODY else k.DISPLAY,
                                    k.TEXT_1)], {"padX": k.INSET_LG, "fill": k.APP}, w=w_, h=HEAD_H)
    kids = [k.vbox("page at 640 CSS px", [head, cv], None, w=w_, h=h_, x=0, y=0),
            k.rect("viewport 640 x 400 CSS", w_, 2, k.RING, x=0, y=400)]
    return k.box(name, kids, {"fill": k.APP, "clip": True}, w=w_, h=h_, x=x, y=0), sh


def frame_inset() -> tuple[c.Node, tuple[str, list[str]]]:
    st = "node/move-mode-200"
    k.fallback("zoom-200")
    k.fallback("type-150")
    s1, h1 = strip_200("strip 1 · 200 %, text 100 %", k.BODY, 0)
    s2, h2 = strip_200("strip 2 · 200 %, text 150 %", T150[k.BODY], 640)
    n1 = k.text_lines(w16(), k.BODY, 640 - 48)
    n2 = k.text_lines(w16(), T150[k.BODY], 640 - 48)
    fid = k.frame_for(NN, st)
    ov = [k.tag(f"strip: {n1} line, {h1} px", 360, HEAD_H + h1 + 4, name="tag · strip 1"),
          k.tag(f"strip: {n2} lines, {h2} px; the canvas moves down", 1000, HEAD_H + h2 + 4, name="tag · strip 2"),
          # x 440, not 16: at 16 the tag covered the `position_side == long` node text in strip 1 (live check)
          k.tag("400 CSS px: the viewport's fold", 440, 406, name="tag · fold")]
    fr = k.box(k.frame_name(fid), [s1, s2, *ov], {"fill": k.APP, "clip": True}, w=k.FRAME_W, h=k.FRAME_H,
               note="200 % zoom: a 640 x 400 CSS px viewport, the layout at 1:1 in two 640 px strips")
    blk = [f"§13 L{k.L('| 1.4.4, 1.4.10, 1.4.12 Resize, reflow, spacing')}: at 200 % and the in-app text scale the "
           "Move-mode strip (W-16) wraps to two lines and pushes the canvas down, never over the moving node",
           f"Strip 1: 200 %, text 100 % — W-16 on {n1} line; strip 2: 200 % with the 150 % text scale (E47-D03's "
           f"largest step) — {n2} lines, the canvas {h2 - h1} px lower; the node stays below the strip",
           "The shell chrome at 640 CSS px is E10-D03's (its 200 % specimen, D03E10:486), not drawn"]
    return fr, k.frame_block(fid, blk)


def build() -> None:
    fr = [frame_move_mode(), frame_view_follows(), frame_placed(), frame_escaped(), frame_inset()]
    k.reading("one layout step (D09-G6, undefined) is drawn as one 24 px grid cell; W-15's column / row count cells "
              "from the canvas origin, so a scrolled view does not renumber them")
    k.reading("the 200 % inset draws two 640 CSS px strips (E47-D03 board 05's method): text 100 % and the 150 % "
              "text scale; the inset is a full 1280 x 800 frame like the others")
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
