"""E47-D04 / 01 landmarks-ring: SCR-020 in the shell, the landmarks (§2) and the region ring in order with the wrap
and SR-04's label at one arrival (§3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies, mark, at_header, SPOT

NN = 1
F_LAND, F_RING = k.frames_of(NN)
DOM_NAME = dict(k.PANELS)["dom"]


def frame_landmarks() -> tuple[k.Node, tuple[str, list[str]]]:
    G = k.GEO
    ov = [k.outline("banner", *G["topbar"]), k.tag("banner · TopBar", 440, 30),
          k.outline("navigation", *G["navrail"]), k.tag("navigation · NavRail", 4, 760 - 20),
          k.outline("main", *G["main"]), k.tag("main · workspace (SCR-020)", G["main"][0] + 8, G["tray"][1] - 20),
          k.outline("complementary", *G["rightrail"]),
          k.tag("complementary · RightRail (SCR-014)", G["rightrail"][0] + 8, 740),
          k.outline("contentinfo", *G["statusbar"]), k.tag("contentinfo · StatusBar", 900, k.FRAME_H - 20),
          k.tag("RG-02 tablist · Workspaces", G["tabstrip"][0] + 420, G["tabstrip"][1] + 8),
          k.tag("RG-04 toolbar · Minimised panels", G["tray"][0] + 260, G["tray"][1] + 6)]
    for kind, name in k.PANELS:
        x, y = at_header(kind, -40)
        ov.append(k.tag(f"region · h2", x + 60, y + 30, name=f"tag · region {kind}"))
    fr = k.workspace_window(F_LAND, bodies(), overlays=ov,
                            note="landmarks: one banner, navigation, main, complementary, contentinfo (§2)")
    lines = [f"§2 L{k.L('**Landmarks.** The shell (SCR-010)')}: one of each top-level landmark: banner = TopBar, "
             "navigation = NavRail, main = the workspace, complementary = RightRail, contentinfo = StatusBar",
             "Each docked panel is a region named by E15-D15's rule (D15:262, :281): " +
             "; ".join(f'"{n}"' for _k, n in k.PANELS),
             "Each panel name is its header's h2 (in the dock); the one h1 is the workspace name, visually hidden "
             f"(the active tab) (§2 L{k.L('**Headings.** One `h1` per screen')})",
             "The tab strip, toolbar and tray are RG-02 ... RG-04; a dialog is not a landmark (§2)",
             "The skip-link set targets main and each region by name (`05`:98)"]
    return fr, k.frame_block(F_LAND, lines)


RING = ("topbar", "navrail", "tabstrip", "chart", "dom", "positions", "tape", "tray", "rightrail", "statusbar")


def frame_ring() -> tuple[k.Node, tuple[str, list[str]]]:
    ov: list[k.Node] = []
    for i, r in enumerate(RING, 1):
        ov.append(mark(i, at_header(r) if r in dict(k.PANELS) else r, name=f"ring {i:02d} · {r}"))
    # the wrap: StatusBar -> TopBar along the right edge, and back
    # live check fold: the line and its heads sit 2 px further in, inside the frame's right edge (they spilled 1 px)
    ov += [k.vline("wrap", k.FRAME_W - 10, 22, k.FRAME_H - 44),
           k.arrow_head("wrap up", "arrow-up", k.FRAME_W - 17, 12),
           k.arrow_head("wrap down", "arrow-down", k.FRAME_W - 17, k.FRAME_H - 28),
           k.tag("wrap: 10 → 1 forward, 1 → 10 reverse", k.FRAME_W - 236, 52)]
    say = k.w("W-1", DOM_NAME)
    ov.append(k.callout("SR-04 arrival", ["Arrival on the DOM panel by Ctrl+\\ (once, polite):", f'"{say}"'],
                        k.GEO["dom"][0] + 60, k.GEO["dom"][1] + 120, 340))
    fr = k.workspace_window(F_RING, bodies(), focus_panel="dom", overlays=ov,
                            note="the ring in visual order; focus has just arrived on the DOM panel")
    t = k.L("| workspace         | TopBar → NavRail")
    lines = [f"§3 L{t} ring order (forward): TopBar → NavRail → the tab strip → the panels in reading order → the "
             "minimised tray → RightRail → StatusBar; reverse = the same list backwards; wrap StatusBar → TopBar",
             "Stops 1-10 drawn: " + ", ".join(f"{i} {r}" for i, r in enumerate(RING, 1)),
             f"Keys (§3 L{k.L('- **Keys.** Forward')}): forward Ctrl+\\ and F6 (desktop); reverse Shift+F6 "
             "(desktop); Ctrl+Shift+\\ PROPOSED (D04-C1); hidden and minimised panels skipped; the tray is one stop",
             f"Announcement (§3 L{k.L('- **Announcement.** On every arrival')}): W-1 once, politely: \"{say}\"; a "
             "second move within one second replaces it (R-8)",
             f"Landing: the element last focused in the region, else its first stop (a panel: its header) "
             f"(§3 L{t})",
             "The DOM panel shows panel focus: CMP-080's inset frame + the header bar in color.focus.ring, never "
             f"CMP-039 around the panel (§7.4 L{k.L('### 7.4 The CMP-039 contract')})",
             f"Order source: the layout system's ordered region list ({k.rule('R-1')})"]
    return fr, k.frame_block(F_RING, lines, keyboard="Ctrl+\\ x10 walks 1-10 and wraps to 1; Shift+F6 reverses",
                             waits=("D04-G4",))


def build(theme: str = "dark") -> None:
    del theme
    f1, b1 = frame_landmarks()
    f2, b2 = frame_ring()
    ann = k.annotations(NN, [b1, b2])
    k.build_all(NN, [f1, f2], ann)


if __name__ == "__main__":
    build()
