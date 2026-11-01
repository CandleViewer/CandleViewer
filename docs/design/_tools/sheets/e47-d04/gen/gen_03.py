"""E47-D04 / 03 grid-escape: the DOM ladder as one stop: entry with its extent label (W-2), Tab out, the Esc layers
to the panel header (§6)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies, mark, at_header, at_body  # noqa: E402

NN = 3
F_ENTRY, F_OUT, F_ESC = k.frames_of(NN)
DOM_X, DOM_Y, DOM_W, DOM_H = k.GEO["dom"]
L61, L62, L63 = k.L("### 6.1 One stop"), k.L("### 6.2 Entry and identity"), k.L("### 6.3 `Esc`, in layers")


def frame_entry() -> tuple[k.Node, tuple[str, list[str]]]:
    ov = [mark(1, at_header("dom"), name="from · DOM header"), mark(2, at_body("dom", 0.97, 0.2), name="to · ladder"),
          k.callout("W-2", ["Grid entry (once per entry, polite; R-8):", f'"{k.w("W-2")}"'],
                    DOM_X - 300, DOM_Y + 150, 290)]
    fr = k.workspace_window(F_ENTRY, bodies(dom=k.ladder_table(k.ladder(), focus=k.BEST_BID)), focus_panel="dom",
                            overlays=ov, note=f"Tab from the DOM header enters the ladder on best bid "
                                              f"{k.px_fmt(k.BEST_BID)}")
    lines = [f"§6.1 L{L61}: CMP-049 role=grid, one Tab stop, roving tabindex; ↑/↓ by row, ←/→ by cell (R-2)",
             f"§6.2 L{L62}: on entry focus lands on the item last focused (R-3), else the default: the ladder's best "
             f"bid. Drawn: no prior item, so best bid {k.px_fmt(k.BEST_BID)} (CMP-039 inset on the row)",
             f"W-2 (§15 L{k.COPY['W-2'].line}, verbatim): \"{k.w('W-2')}\"",
             "Stop 1 = the DOM header toolbar (its first stop), stop 2 = the ladder (the panel's last stop)",
             k.arch("Tokens", "dense grid")]
    return fr, k.frame_block(F_ENTRY, lines, keyboard="Tab from the header lands on best bid; ↑/↓ move by price")


def frame_out() -> tuple[k.Node, tuple[str, list[str]]]:
    ov = [mark(1, at_body("dom", 0.97, 0.2), name="from · ladder"), mark(2, at_header("positions", 40),
                                                                        name="to · Positions header"),
          k.callout("Tab out", ["Tab: one press leaves the ladder", "to the next panel's header (§6.1)"],
                    DOM_X + 20, DOM_Y + DOM_H - 60, 300)]
    fr = k.workspace_window(F_OUT, bodies(), focus_panel="positions", toolbar_focus=("positions", 1), overlays=ov,
                            note="after one Tab from the ladder: focus on the Positions header's first tool")
    lines = [f"§6.1 L{L61}: Tab from anywhere inside leaves the grid in one press to the next stop of its panel; "
             "the next panel's header when the grid is the panel's last stop; never one row",
             "Drawn: the ladder is the DOM panel's last stop, so Tab lands on the Positions header (reading order: "
             "Chart, DOM, Positions, Tape); the Positions panel now shows panel focus",
             "Shift+Tab from the ladder leaves to the previous stop, the DOM header (§6.1)",
             "QA-1 (hand-off §G): after one Tab, activeElement is outside the grid and is the panel's next stop"]
    return fr, k.frame_block(F_OUT, lines, keyboard="Tab (one press) out; Shift+Tab back to the DOM header")


def frame_esc() -> tuple[k.Node, tuple[str, list[str]]]:
    layers = ["Esc, innermost first (§6.3):", "1  an open menu", "2  an in-cell edit", "3  the selection",
              "4  an expansion", "then, with nothing open: the panel header"]
    ov = [k.callout("Esc layers", layers, DOM_X - 300, DOM_Y + 120, 280),
          mark("Esc", at_header("dom"), name="lands · DOM header"),
          k.callout("no cancel", ["A bare Esc never cancels an order;", "a focused order cancels with Ctrl+Delete"],
                    DOM_X + 60, DOM_Y + DOM_H + 60, 320)]
    fr = k.workspace_window(F_ESC, bodies(), focus_panel="dom", toolbar_focus=("dom", 1), overlays=ov,
                            note="Esc with nothing open: focus on the DOM panel header (its first tool)")
    lines = [f"§6.3 L{L63}: Esc closes the innermost transient first: an open menu, then an in-cell edit, then the "
             "selection (D04E11:296), then an expansion; only with nothing open does it leave the grid",
             "A panel-hosted grid (the ladder) exits to its panel header: the RG-08 toolbar's last-focused item, "
             "else its first (D15:269). Drawn: the first tool",
             "SCR-045 keeps its merged destination, the plot stop (D04-C2); not drawn here",
             "A bare Esc never cancels an order in any grid; Ctrl+Delete cancels a focused order (D04-C3)",
             "QA-1 (hand-off §G): after Esc with nothing open, focus is in the panel header's toolbar"]
    return fr, k.frame_block(F_ESC, lines, keyboard="Esc peels menu → edit → selection → expansion → header")


def build(theme: str = "dark") -> None:
    del theme
    fr = [frame_entry(), frame_out(), frame_esc()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
