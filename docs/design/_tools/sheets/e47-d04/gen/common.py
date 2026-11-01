"""Shared pieces of the E47-D04 board generators: the kit import, the panel bodies of the four-panel workspace and
the marker positions per region (frame coordinates from k.GEO)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import e47d04kit as k  # noqa: E402

Node = k.Node
BODY_W, BODY_H = k.PANEL_W, k.PANEL_H - k.HEADER_H  # 490 x 304


def chart_body() -> Node:
    """The chart's plot stop (one stop, the chart root; §4 workspace Roving zones): neutral placeholder bars."""
    k.fallback("chrome")
    bars = []
    for i in range(24):
        h = 40 + (i * 37) % 120
        bars.append(k.rect(f"placeholder · candle {i + 1:02d}", 8, h, k.HOVER, x=24 + i * 18, y=230 - h))
    return k.box("plot stop", bars, None, w=BODY_W, h=BODY_H, note="the chart root: one stop (D03E06:103, :245)")


def tape_body() -> Node:
    k.fallback("chrome")
    rows = [k.placeholder(f"tape row {i}", BODY_W - 24, 12) for i in range(1, 11)]
    return k.vbox("tape list", rows, {"gap": k.STACK_SM, "pad": k.INSET_MD}, w=BODY_W, h=BODY_H)


def bodies(**over: Node | None) -> dict[str, Node | None]:
    """The four panels' bodies: chart placeholder, the DOM ladder, the positions grid, the tape placeholder."""
    out: dict[str, Node | None] = {"chart": chart_body(), "dom": k.ladder_table(k.ladder()),
                                   "positions": k.positions_table(k.positions()), "tape": tape_body()}
    out.update(over)
    return out


def at_header(kind: str, dx: int = 0) -> tuple[int, int]:
    """A marker spot in a panel header, between the h2 and the toolbar."""
    x, y, w, _h = k.GEO[kind]
    return x + w // 2 + dx, y + 4


def at_body(kind: str, fx: float = 0.5, fy: float = 0.5) -> tuple[int, int]:
    x, y, w, h = k.GEO[kind]
    return x + round((w - 20) * fx), y + k.HEADER_H + round((h - k.HEADER_H - 20) * fy)


SPOT = {  # one marker spot per ring member (§3 workspace order)
    "topbar": (620, 14), "navrail": (18, 400), "tabstrip": (k.NAV_W + k.MAIN_W - 32, k.TOP_H + 6),
    "tray": (k.NAV_W + k.MAIN_W - 32, k.GEO["tray"][1] + 4), "rightrail": (k.GEO["rightrail"][0] + 110, 400),
    "statusbar": (620, k.FRAME_H - 22),
}


def mark(n: int | str, where: str | tuple[int, int], name: str | None = None) -> Node:
    x, y = SPOT[where] if isinstance(where, str) else where
    return k.marker(n, x, y, name=name)
