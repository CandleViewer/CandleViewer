"""E47-D04 / 02 workspace-order: the workspace archetype's Tab sequence and its roving zones over the four-panel
layout, the panel header bar and frame (§4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies, mark, at_header, at_body  # noqa: E402

NN = 2
F_TAB, F_ROVE = k.frames_of(NN)


def frame_tab() -> tuple[k.Node, tuple[str, list[str]]]:
    seq = [("skip links", (440, 4)), ("TopBar", "topbar"), ("NavRail", "navrail"), ("tab strip", "tabstrip")]
    for kind, _n in k.PANELS:
        seq.append((f"{kind} header toolbar", at_header(kind)))
        seq.append((f"{kind} body", at_body(kind, 0.9, 0.85)))
    seq += [("tray", "tray"), ("RightRail", "rightrail"), ("StatusBar", "statusbar")]
    ov = [mark(i, where, name=f"tab {i:02d} · {lab}") for i, (lab, where) in enumerate(seq, 1)]
    ov.append(k.tag("skip links: visible on focus", 466, 6))
    ov.append(k.callout("Tab sequence", ["Tab sequence (§4 workspace):", k.ARCH["Tab sequence"]["workspace"][0]],
                        k.GEO["positions"][0] + 150, k.GEO["positions"][1] + 120, 330))
    fr = k.workspace_window(F_TAB, bodies(), focus_panel="chart", toolbar_focus=("chart", 1), overlays=ov,
                            note="Tab order over the four panels; the Chart panel's header toolbar holds focus")
    lines = [k.arch("Tab sequence", "workspace"),
             "Stops drawn: " + ", ".join(f"{i} {lab}" for i, (lab, _w) in enumerate(seq, 1)),
             "Each panel is one run of stops, its header first (header toolbar, then its body stops); a dense grid "
             f"body is one stop ({k.rule('R-2')})",
             k.arch("Initial target", "workspace"),
             "Focus is on the Chart header's first toolbar item: CMP-039 normal on the control; the panel shows "
             "CMP-080's inset frame + header bar in color.focus.ring (§4 Tokens; `16`:88)",
             f"{k.rule('R-1')}: the DOM is rebuilt to the visual order, so Tab follows the picture"]
    return fr, k.frame_block(F_TAB, lines, keyboard="Tab / Shift+Tab walk 1-15; the ring keys jump region to region")


def frame_rove() -> tuple[k.Node, tuple[str, list[str]]]:
    G = k.GEO
    ov = [k.outline("RG-02", *G["tabstrip"]), k.tag("roving · RG-02 tab strip (←/→)", G["tabstrip"][0] + 300, 54),
          k.outline("RG-07", 0, k.TOP_H, k.NAV_W, 7 * 36 + 8), # boards lens m-5: the tag sits in the rail, under the tree's outline
          k.tag_stack("roving · RG-07 rail tree (↑/↓)", ["roving", "RG-07", "tree", "(↑/↓)"], 1,
                      k.TOP_H + 7 * 36 + 16, 54),
          k.outline("RG-04", *G["tray"]), k.tag("roving · RG-04 tray (←/→)", G["tray"][0] + 300, G["tray"][1] + 6)]
    for kind, _n in k.PANELS:
        x, y, w, _h = G[kind]
        ov.append(k.outline(f"RG-08 {kind}", x + w - 64, y, 64, k.HEADER_H))
    ov.append(k.tag("roving · RG-08 header toolbars (←/→)", G["dom"][0] + 196, G["dom"][1] + 6))
    cx, cy, cw, ch = G["chart"]
    ov += [k.outline("plot stop", cx, cy + k.HEADER_H, cw, ch - k.HEADER_H),
           k.tag("one stop · the chart's plot stop", cx + 12, cy + k.HEADER_H + 8)]
    ov.append(k.callout("R-2", ["One item tabindex=\"0\", the rest \"-1\":",
                                "the DOM header's first tool holds the zone's one stop (R-2)"],
                        G["tape"][0] + 120, G["tape"][1] + 150, 344))
    fr = k.workspace_window(F_ROVE, bodies(), focus_panel="dom", toolbar_focus=("dom", 1), overlays=ov,
                            note="the roving zones: each is one Tab stop, arrows inside")
    lines = [k.arch("Roving zones", "workspace"),
             f"{k.rule('R-2')}: a grid, tree, listbox, toolbar or tablist is one Tab stop with a roving tabindex",
             k.arch("Entry and exit keys", "workspace"),
             "Panel header bar and frame: the DOM panel is the focused panel (frame + bar in color.focus.ring, "
             f"inside the box; §7.4 L{k.L('### 7.4 The CMP-039 contract')}); its first header tool carries CMP-039",
             "The arrow glyphs in the tags name the keys inside each zone (APG; §4)"]
    return fr, k.frame_block(F_ROVE, lines, keyboard="Tab enters a zone on its one stop; ←/→ (↑/↓ in the tree) move "
                                                     "inside; Tab leaves")


def build(theme: str = "dark") -> None:
    del theme
    f1, b1 = frame_tab()
    f2, b2 = frame_rove()
    k.build_all(NN, [f1, f2], k.annotations(NN, [b1, b2]))


if __name__ == "__main__":
    build()
