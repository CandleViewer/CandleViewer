"""E47-D04 / 10 ring-hc-thick: the high-contrast twin of 08 with the thick geometry (§7.3): frame 1 the thick ring
beside the normal one and the shipped preference (W-7, W-8); frame 2 the 12 backgrounds with the thick ring."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402
import gen_08 as g8  # noqa: E402


def frame_thick(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    # live check fold: the title wraps at the card's 256 px content width (one line overflowed it by 51 px)
    pref = k.vbox("card · preference", [k.text("title", "The preference (SCR-117; drawn by E47-D05)", k.HEADING_SM,
                                               k.TEXT_1, w=g8.CARD_W - 24),
                                        k.toggle_row(k.w("W-7"), k.w("W-8"), on=True, w_=g8.CARD_W - 24),
                                        k.lines_block("rows", ['writes data-focus-ring="thick" on the root (PCX:148)',
                                                               "the default in the high-contrast theme (§7.3)"],
                                                      w_=g8.CARD_W - 24, typo=k.CAPTION, color=k.TEXT_2)],
                  {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.CANVAS, "radius": k.R_CARD, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=g8.CARD_W)
    cards = k.hbox("cards", [g8.spec_card("thick", prominent=True), g8.spec_card("normal"), pref],
                   {"gap": k.INSET_LG, "align": "start"})
    fr = k.specimen_frame(fid, [k.text("h", "CMP-039 thick ring (high visibility) · high contrast (§7.1, §7.3)",
                                       k.HEADING_MD, k.TEXT_1), cards, g8.pair_line("hc")])
    lines = [f"§7.3 L{g8.L73}: US-SET-007 asks that focus indicators become more prominent; the shipped preference "
             f"thick_focus_ring (MODEL:13) labelled W-7 with W-8 as help (ASS:113, :114), written as "
             "data-focus-ring on the root (PCX:148); thick is the default in the high-contrast theme",
             f"W-7 (§15 L{k.COPY['W-7'].line}, verbatim): \"{k.w('W-7')}\"; W-8: \"{k.w('W-8')}\"",
             f"§7.1 L{g8.L71} thick: ring {k.GEOMETRY['thick'].ring}; halo {k.GEOMETRY['thick'].halo}; offset "
             f"{k.GEOMETRY['thick'].offset}; outer extent {k.extent('thick')} px vs {k.extent('normal')} px normal",
             "The thick card is drawn first and larger; the normal card beside it for comparison",
             f"§7.2 pair in high contrast {k.ratio('pair.hc')}:1",
             "\"Always-show focus ring\" (`14`:2471) has no preference in the shipped model (D04-G2)"]
    return fr, k.frame_block(fid, lines, waits=("D04-G2", "D04-G5"))


if __name__ == "__main__":
    g8.build("hc")
