"""E47-D09 / 09 inert: the inert-binding message from the journal — non-modal, the polite region marked — and the
200 % / text-scale inset (§11; AC5; K-10)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 9
S11 = k.L("## 11. Inert-binding feedback")
CMD = k.CMD["ticket.submit"]  # AC5's case: Ctrl+Enter (Submit order) pressed in the journal
TOAST_W = 360  # E10-D03 §7 (D03E10:289): 360 px, PROPOSED there (size.toast.width is not a token)
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12
TONE_WORD = "Info"
T150 = {k.BODY: k.HEADING_LG, k.BODY_STRONG: k.HEADING_LG, k.CAPTION: k.HEADING_MD, k.HEADING_LG: k.DISPLAY,
        k.HEADING_SM: k.DISPLAY}


def w6() -> str:
    return k.w("W-6", CMD.label, CMD.context)


def toast(scale: dict[str, str] | None = None) -> c.Node:
    sc = scale or {}
    iw = TOAST_W - 2 * 12
    head = k.hbox("head", [k.hbox("tone", [k.icon("glyph", "info", k.INFO_STRONG),
                                           k.text("word", TONE_WORD, sc.get(k.BODY_STRONG, k.BODY_STRONG),
                                                  k.INFO_STRONG)], {"gap": k.INSET_XS}, h=24),
                           k.icon_button("close", name="dismiss · Dismiss notification")],
                  {"justify": "space-between"}, w=iw, h=24)
    return k.vbox("CMP-020 toast · info", [head, k.text("title", w6(), sc.get(k.BODY, k.BODY), k.TEXT_1, w=iw)],
                  {"gap": k.STACK_XS, "pad": k.INSET_MD, "fill": k.OVERLAY, "radius": k.R_CARD, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=TOAST_W,
                  note="non-modal; never takes focus (D04's R-5); spoken through the host's one polite region; "
                       "copied into SCR-014's log")


def journal(w_: int, scale: dict[str, str] | None = None) -> c.Node:
    sc = scale or {}
    k.copy_gap('"Journal": SCR-093\'s title (`14`:2152); the list and its filters are placeholders')
    rows = []
    for i in range(1, 9):
        r = k.hbox(f"trade row {i}", [k.placeholder("time", 64), k.placeholder("symbol", 72),
                                      k.placeholder("result", 96)], {"gap": k.INSET_LG, "padX": k.INSET_SM,
                                                                     "fill": k.CANVAS if i % 2 else k.RAISED},
                   w=w_ - 48, h=32)
        if i == 2:
            r = dict(r, kids=[*r["kids"], k.inset_ring(w_ - 48, 32)], note="focus stays here (unchanged)")
        rows.append(r)
    return k.vbox("SCR-093 journal", [k.text("h1", "Journal", sc.get(k.HEADING_LG, k.HEADING_LG), k.TEXT_1),
                                      k.hbox("filters", [k.placeholder("filter 1", 120, 24),
                                                         k.placeholder("filter 2", 96, 24)], {"gap": k.INSET_SM},
                                             h=24),
                                      k.vbox("trade list", rows, None, w=w_ - 48, h=32 * len(rows))],
                  {"gap": k.STACK_MD, "pad": k.INSET_XL}, w=w_)


def frame_journal() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "inert/journal")
    t = toast()
    th = round(k.est_height(t))
    tx, ty = k.FRAME_W - 16 - TOAST_W, k.FRAME_H - k.STATUS_H - 16 - th
    ov = [dict(t, x=tx, y=ty, abs=True),
          k.outline("polite region", tx - 6, ty - 6, TOAST_W + 12, th + 12),
          k.tag("the toast host's one polite region (aria-live=polite)", tx - 6, ty - 26, name="tag · polite region"),
          k.callout("press", [f"{CMD.default} ({CMD.label}) pressed in the journal:",
                              "one non-modal message, said once (polite); focus unchanged; nothing ran",
                              "A second press within 5 s adds no toast while the first is shown; after 5 s it "
                              "speaks again (DISP:19)"], RX, 120, RW)]
    fr = k.page_window(fid, journal(k.MAIN_W), overlays=ov, note=f"{CMD.default} in the journal: the inert message")
    shipped = f"{CMD.label} is not available here ({CMD.context} view): it needs {CMD.valid_when}."
    blk = [f"§11 L{S11 + 2}: the shipped mechanism stands (E49-S07): a CMP-020 info toast (HOST:124-126), 5 s, "
           "spoken through the host's one polite region, at most once per command per 5 s, counted as "
           "hotkey.inert_pressed; every toast is copied into SCR-014's log",
           f"Copy change (D09-A10): W-6 \"{w6()}\" replaces the shipped \"{shipped}\" (DISP:87-91, H-6)",
           f"{k.wcite('W-6')}: {{contexts}} = the command's registry context ({CMD.context}; KMAP:"
           f"{k.kmap_line(CMD.id)}); the journal has no keymap context, so the view reads \"this view\"",
           f"{k.krule('K-10')}; {k.crow('D09-C12')}: bare navigation keys, Esc, ranges and repeats stay silent",
           f"Toast: bottom-right above the StatusBar, 16 px in, {TOAST_W} px (D03E10:289); glyph + the tone word "
           f"\"{TONE_WORD}\" + the text + Dismiss"]
    return fr, k.frame_block(fid, blk, keyboard=f"{CMD.default} in the journal; focus stays on the trade row",
                             waits=["D09-G2"])


# the live check's measured toasts, (height px, lines): 71 px, one line of 13 px text, at text 100 %; 100 px, two lines,
# at 150 % (the kit estimated 88 px and two lines for strip 1)
MEASURED_TOAST = {"strip 1": (71, 1), "strip 2": (100, 2)}


def lines(n: int) -> str:
    return "line" if n == 1 else "lines"


def strip(name: str, x: int, scale: dict[str, str] | None) -> tuple[c.Node, int]:
    w_, h_ = 640, 800
    t = toast(scale)
    th = round(k.est_height(t))
    kids = [k.box("page at 640 CSS px", [journal(w_, scale)], {"fill": k.APP}, w=w_, h=h_, x=0, y=0),
            dict(t, x=w_ - 16 - TOAST_W, y=400 - 16 - th),
            k.rect("viewport 640 x 400 CSS", w_, 2, k.RING, x=0, y=400)]
    return k.box(name, kids, {"fill": k.APP, "clip": True}, w=w_, h=h_, x=x, y=0), th


def frame_inset() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "inert/journal-200")
    k.fallback("zoom-200")
    k.fallback("type-150")
    s1, _e1 = strip("strip 1 · 200 %, text 100 %", 0, None)
    s2, _e2 = strip("strip 2 · 200 %, text 150 %", 640, T150)
    # the words state the live-measured toasts (the strips keep the drawn, estimated placement)
    (h1, n1), (h2, n2) = MEASURED_TOAST["strip 1"], MEASURED_TOAST["strip 2"]
    ov = [k.tag(f"toast {h1} px: text on {n1} {lines(n1)}", 16, 420, name="tag · strip 1"),
          k.tag(f"toast {h2} px: text on {n2} lines, width kept", 656, 420, name="tag · strip 2"),
          k.tag("400 CSS px: the viewport's fold", 16, 406 + 36, name="tag · fold")]
    fr = k.box(k.frame_name(fid), [s1, s2, *ov], {"fill": k.APP, "clip": True}, w=k.FRAME_W, h=k.FRAME_H,
               note="200 % zoom: a 640 x 400 CSS px viewport, the layout at 1:1 in two 640 px strips")
    blk = [f"§13 L{k.L('| 1.4.4, 1.4.10, 1.4.12 Resize, reflow, spacing')}: the inert toast wraps inside CMP-020's "
           "width and grows in height; its copy stays in SCR-014's log",
           f"Strip 1: 200 %, text 100 % — W-6 on {n1} {lines(n1)}; strip 2: the 150 % text scale — {n2} lines, the toast "
           f"{h2 - h1} px taller, still {TOAST_W} px wide and inside the viewport",
           "The shell chrome at 640 CSS px is E10-D03's (D03E10:486), not drawn"]
    return fr, k.frame_block(fid, blk)


def build() -> None:
    fr = [frame_journal(), frame_inset()]
    k.reading(f"AC5's case is ticket.submit ({CMD.default}) pressed in the journal (§11: \"the journal case of AC5\"); "
              f"W-6's {{contexts}} is its registry context \"{CMD.context}\"")
    k.reading(f"the toast's tone word \"{TONE_WORD}\" is E10-D03 §7's \"glyph + severity word + text\" for the info "
              "tone (copy gap: no W-row)")
    k.copy_gap(f'"{TONE_WORD}" and "Dismiss notification": E10-D03 §7 (D03E10:84, :289), not this spec\'s')
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
