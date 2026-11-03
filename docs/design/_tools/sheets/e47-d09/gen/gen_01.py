"""E47-D09 / 01 order-line (dark) and, through build("light"), 02 order-line-light: the grammar on a working stop —
selected, pending (W-1), refused (W-19, W-20), Enter through the confirm (W-21), Esc (W-2) (§4; DE-01)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 1
OBJ = "Stop-loss"  # {object}: the line's name (the SCR-063 row word); kit reading, recorded
S4 = k.L("## 4. The order line on the chart")
RX = k.FRAME_W - k.RIGHT_W + 6  # callouts sit over the RightRail placeholders (annotation, not product UI)
RW = k.RIGHT_W - 12


def row4(needle: str) -> int:
    return k.L(needle, start=S4)


def axis_tag(p: Decimal, token: str, name: str) -> c.Node:
    """The line's readout on the price axis (it follows the pending value; §2 Adjust: "the readout follows")."""
    return k.hbox(f"readout · {name}", [k.text("price", k.px_fmt(p), k.NUM_XS, k.TEXT_1)],
                  {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": token, "strokeWidth": k.THICK,
                   "strokeAlign": "inner"}, w=c.AXIS_W - 4, h=16, x=c.PLOT_W + 2, y=c.y_of(p) - 8)


def at_chart(x: int, y: int) -> tuple[int, int]:
    return c.CB_X + x, c.CB_Y + y


def sl_row_y() -> int:
    """The Stop-loss row's frame y in SCR-063 (header + caption-less table: header row, rule, rows)."""
    return c.OP_Y + k.HEADER_H + k.ROW_H + 1 + 4 + 4 + k.ROW_H


def frame_selected(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "order-line/selected", theme)
    lines = c.position_lines(sl_focus=True)
    chart = c.chart_body(lines, [axis_tag(k.SL, k.POS_SL, "stop-loss")])
    sel = f"{OBJ}, {k.px_fmt(k.SL)}, arrows adjust"
    k.copy_gap(f'the select announcement "{sel}": §4 L{row4("| `Tab` / arrows in the trading-object stop")} gives '
               'its parts ("the line, its price, arrows adjust"), not a W-string (E47-D07 owns the words)')
    tx, ty = at_chart(c.LABEL_X, c.y_of(k.SL))
    ov = [k.marker(1, tx - 30, ty - 10, name="stop 1 · the line's surrogate"),
          k.marker(2, c.CB_X - 24, sl_row_y() + 2, name="stop 2 · the SCR-063 row twin"),
          k.callout("select", ["Selected (polite, once):", f"“{sel}”", f"Restore point held: {k.px_fmt(k.SL)} "
                               "(K-2); nothing sent"], RX, 120, RW)]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov,
                          note="Tab reached the trading-object stop after the plot stop; the SL line is selected")
    blk = [f"§4 L{row4('| `Tab` / arrows in the trading-object stop')}: Tab / arrows in the trading-object stop, or "
           "Enter on the SCR-063 row (stop 2), select the line and hold its price as the restore point",
           f"{k.krule('K-2')}; {k.de('DE-01')}",
           f"Drawn: the long {k.QTY} {k.SYMBOL} at {k.px_fmt(k.ENTRY)}, SL {k.px_fmt(k.SL)}, TP {k.px_fmt(k.TP)}, "
           f"mark {k.px_fmt(k.MARK)}; the ring on the SL label (the surrogate), its readout on the axis",
           "Focus placement and the ring are E47-D04's (D04 board 06); the ring here only marks where focus is"]
    return fr, k.frame_block(fid, blk, keyboard="Tab into the stop, arrows to the SL line; or Enter on its row",
                             waits=["D09-G4"])


def frame_pending(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "order-line/pending", theme)
    lines = [*c.position_lines(), *c.price_line("pending", k.PENDING, k.POS_SL, c.tag_text("SL", k.PENDING),
                                                focused=True, pending=True)]
    chart = c.chart_body(lines, [axis_tag(k.PENDING, k.POS_SL, "pending")])
    tx, ty = at_chart(c.LABEL_X, c.y_of(k.PENDING))
    ov = [k.marker(1, tx - 30, ty - 10, name="stop 1 · the pending line"),
          k.tag(f"unchanged: {k.px_fmt(k.SL)}, nothing sent (K-7)", c.CB_X + 824, sl_row_y() + 4,
                name="tag · the row is unchanged"),
          c.say("W-1", "W-1", OBJ, k.px_fmt(k.PENDING), x=RX, y=120, wd=RW,
                head=f"First press (leadDelay 0, polite), after {k.NUDGE} presses:",
                extra=[f"Held: at most once per 500 ms, the short form W-5 “{k.w('W-5', k.px_fmt(k.PENDING))}”; "
                       "the final value within 250 ms (§6)"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov, note=f"↑ pressed {k.NUDGE} times: one tick each")
    blk = [f"§4 L{row4('| `↑` / `↓`, `Shift` ×10')}: the pending price moves {k.NUDGE} ticks "
           f"({k.px_fmt(k.SL)} → {k.px_fmt(k.PENDING)}, tick {k.TICK}); the line draws dashed with the word "
           "\"pending\"; the stop moves only toward the price",
           f"{k.krule('K-3')}; {k.krule('K-6')}; {k.krule('K-7')}",
           f"Sends nothing: the SCR-063 Stop-loss row still reads {k.px_fmt(k.SL)} (hand-off §G QA-2)",
           f"{k.wcite('W-1')}; {k.wcite('W-5')}"]
    return fr, k.frame_block(fid, blk, keyboard="↑ / ↓ one tick, Shift ×10, PageUp / PageDown ×100",
                             waits=["D09-G4"])


def frame_refused(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "order-line/refused", theme)
    lines = [*c.position_lines(), *c.price_line("pending", k.WRONG, k.POS_SL, c.tag_text("SL", k.WRONG),
                                                focused=True, pending=True)]
    chart = c.chart_body(lines, [axis_tag(k.WRONG, k.POS_SL, "pending")])
    tx, ty = at_chart(c.LABEL_X, c.y_of(k.WRONG))
    ov = [k.marker(1, tx - 30, ty - 10, name="stop 1 · the pending line"),
          c.say("W-20", "W-20", k.px_fmt(k.WRONG), x=RX, y=120, wd=RW,
                head=f"Shift+↑ ×{k.WRONG_SIDE_PRESSES}: past the mark {k.px_fmt(k.MARK)} (polite, once):",
                extra=["Refused as the drop is; the pending value stays for correction"]),
          c.say("W-19", "W-19", x=RX, y=330, wd=RW,
                head=f"↓ at the restore point {k.px_fmt(k.SL)} (polite, once):",
                extra=["The value stays at the current stop; Loosen stop… in SCR-064 widens it (D05E32:264)"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov,
                          note="a pending value on the wrong side of the mark; the loosening key refused")
    blk = [f"§4 L{row4('| a pending value on the wrong side of the price')}: refused as the drop is "
           f"(`11`:3056-3057; {k.crow('D09-C8')}); {k.px_fmt(k.WRONG)} >= the mark {k.px_fmt(k.MARK)}",
           f"§4 L{row4('| the loosening key on a stop')}: the loosening key leaves the stop where it is; "
           f"{k.krule('K-7')}",
           f"{k.wcite('W-19')}; {k.wcite('W-20')}; both polite status messages, never role=alert (§13 4.1.3)"]
    return fr, k.frame_block(fid, blk, keyboard="Shift+↑ ×10 per press; ↓ on a long's stop loosens (refused)",
                             waits=["D09-G4"])


def frame_confirm(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "order-line/confirm", theme)
    lines = [*c.position_lines(), *c.price_line("pending", k.PENDING, k.POS_SL, c.tag_text("SL", k.PENDING),
                                                pending=True)]
    chart = c.chart_body(lines, [axis_tag(k.PENDING, k.POS_SL, "pending")])
    title = "Amend stop-loss"
    k.copy_gap(f'the confirm dialog\'s words "{title}", "Cancel", "Confirm" and its two data lines: the drop\'s own '
               "confirm (SCR-040's confirm choice, `14`:1030-1033; E31-D01 owns it, PROPOSED); no W-string")
    body = [k.text("change", f"SL {k.px_fmt(k.SL)} → {k.px_fmt(k.PENDING)}", k.NUM, k.TEXT_1),
            k.text("order", f"{k.SYMBOL} · Long {k.QTY} · Live", k.BODY, k.TEXT_2)]
    dlg = k.dialog(title, body, [k.button("Cancel", "secondary"), k.button("Confirm", "primary")],
                   name="CMP-044 confirm · amend")
    ovl, (dx, dy, dw, _dh) = k.modal(dlg)
    ov = [ovl, c.say("W-21", "W-21", k.px_fmt(k.PENDING), x=RX, y=120, wd=RW, head="After Confirm (polite):",
                     extra=["Then the order's acknowledged or rejected state, once; Esc after Enter closes the "
                            "selection and the request stands (D05E32:272)"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov,
                          note="Enter commits through the drop's own path: the confirm opens as the drag's would")
    blk = [f"§4 L{row4('| `Enter`')}: Enter commits through the drop's own path — SCR-040's confirm choice, "
           "US-SET-003's policy with Live never weaker than Demo (`11`:5106-5112), the wrong-side refusal; one amend",
           f"{k.krule('K-4')}; BQ-5 RULED (§4 L{row4('Arrow-nudging a stop is a real amendment')})",
           "Drawn: the Live session's policy = dialog; the dialog is E47-D04's contract (initial focus and the "
           "return to the line's surrogate on every close path, D04's R-7), not redrawn here",
           f"{k.wcite('W-21')}"]
    return fr, k.frame_block(fid, blk, keyboard="Enter opens the confirm; Confirm sends one amend; Esc / Cancel "
                                                "returns to the pending line", waits=["D09-G4"])


def frame_cancelled(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "order-line/cancelled", theme)
    chart = c.chart_body(c.position_lines(sl_focus=True), [axis_tag(k.SL, k.POS_SL, "stop-loss")])
    tx, ty = at_chart(c.LABEL_X, c.y_of(k.SL))
    ov = [k.marker(1, tx - 30, ty - 10, name="stop 1 · the line, restored"),
          c.say("W-2", "W-2", x=RX, y=120, wd=RW, head="Esc before Enter (polite):",
                extra=[f"The price at selection is restored: {k.px_fmt(k.SL)}; nothing was sent",
                       "A focus move away says W-2 after the new focus's announcement, never in its place (K-5)"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov, note="Esc before Enter: the line is back at its "
                                                                         "restore point; focus stays on it")
    blk = [f"§4 L{row4('| `Esc`, or focus moved away, before `Enter`')}: Esc, or focus moved away, before Enter "
           "restores the price at selection",
           f"{k.krule('K-5')}; focus stays on the line's surrogate (§4, D04's R-7)",
           f"{k.wcite('W-2')}; hand-off §E: \"the stop is where it was, nothing was sent, and W-2 was spoken\""]
    return fr, k.frame_block(fid, blk, keyboard="Esc restores; the line stays selected", waits=["D09-G4"])


def build(theme: str = "dark") -> None:
    nn = {"dark": 1, "light": 2}[theme]
    fr = [f(theme) for f in (frame_selected, frame_pending, frame_refused, frame_confirm, frame_cancelled)]
    k.reading(f"{{object}} in W-1 / W-2 is \"{OBJ}\", the SCR-063 row word for the working stop; the select "
              "announcement is built from §4's cell (the line, its price, \"arrows adjust\")")
    k.reading("the readout that follows the pending value (§2 Adjust) is drawn as the line's price tag on the axis; "
              "the label on the line carries the word \"pending\"")
    k.reading("W-19 and W-20 share the one refused frame (§H names both on it): W-20's case is drawn, W-19's key "
              "and string are a second callout")
    k.build_all(nn, [f for f, _b in fr], k.annotations(nn, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
