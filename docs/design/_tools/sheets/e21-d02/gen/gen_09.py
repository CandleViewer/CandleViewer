"""Board 09 legend-greyscale-cvd: §7 the legend (CMP-113), the computed contrast and colour-vision tables, the
CVD twin set, the forced-colours carriers, and the greyscale and simulated exports of board 01 (made at export)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 9


def cvd() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/streaming · CVD twin set"
    return ui.panel(fid, ui.P(cvd=True)), k.frame_block(fid, [
        "The panel with the CVD twins color.cvd.heatmap.* (§2.4), the setting for a user who wants colour to carry "
        "the side; the column and the B / A letter carry it in every set (§7.1)"])


def legend() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.LEGEND
    an = k.stops()
    vmax = k.window_max()
    anchors = ["0", k.anchor_fmt(an[2]), f"{k.anchor_fmt(vmax)} {k.COIN}"]
    k.derive(f"legend anchors: 0, the middle stop's lower edge {an[2]} and the window's largest cell {vmax} BTC "
             "(§7.2's form: '0', '25', '120 BTC')")

    def side_row(side: str, words: str) -> k.Node:
        sw = k.hbox("swatches", [k.rect(f"swatch {side} {i}", 24, 16, k.hm(side, i)) for i in range(1, 6)],
                    {"gap": k.INSET_XS}, w=136, h=16, note="aria-hidden; the words and anchors carry it")
        return k.hbox(f"{side} row", [sw, k.text("words", words, k.CAPTION, k.TEXT_1)], {"gap": k.INSET_SM}, h=20)

    leg = k.vbox("CMP-113 HeatmapLegend", [
        side_row("bid", k.S("Bid: resting buy liquidity, left column, below the best price")),
        side_row("ask", k.S("Ask: resting sell liquidity, right column, above the best price")),
        k.text("scale", k.ui(f"scale: {k.S('log')}", "the legend's scale word"), k.CAPTION, k.TEXT_2),
        k.hbox("anchors", [k.text(f"anchor {i}", a, k.NUM_SM, k.TEXT_1) for i, a in enumerate(anchors)],
               {"gap": k.INSET_LG}, h=16)],
        {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=640,
        note='role="group"; static, never announced')
    stops = k.grid_table("§7.3 stops", [k.Col(f"s{i}", k.plain(h), w) for i, (h, w) in enumerate(zip(
        ("Theme", "Lowest stop", "Ratio", "Deuteranopia ΔE", "Protanopia ΔE", "Tritanopia ΔE", "CVD twin lowest stop",
         "Ratio", "Twin smallest ΔE"), (112, 176, 64, 128, 120, 120, 200, 64, 136)))],
        [{f"s{i}": k.plain(v) for i, v in enumerate(c)} for _i, c in k.STOP_ROWS],
        cap=f"§7.3 L{k.STOP_ROWS[0][0]}: computed by the audit tool (heuristic reading in the spec)")
    pairs = k.grid_table("§7.3 pairs", [k.Col("p", "Pair", 560), k.Col("f", "Floor", 64), k.Col("d", "dark", 80),
                                        k.Col("l", "light", 80), k.Col("h", "high-contrast", 120)],
                         [{"p": k.plain(c[0]), "f": c[1], "d": c[2], "l": c[3], "h": c[4]} for _i, c in k.PAIR_ROWS],
                         cap=f"§7.3 L{k.PAIR_ROWS[0][0]}: the other pairs, every theme")
    side = k.text("side", k.ui("Side, three ways (§7.1): the column (Bid left of Ask), the B / A letter, the colour; "
                              "in the pane bids sit below the mark and asks above", "board-marker caption"),
                  k.CAPTION, k.TEXT_2, w=1000)
    return k.marker_frame(fid, [leg, side, stops, pairs], 1184), k.frame_block(fid, [
        "The convention in words (`15`:1349), the scale type from the header, ≥ 2 numeric anchors (M AD-10); an "
        "inverted convention is named when the user inverts it (`11`:2002)",
        "Deuteranopia's closest pair (level 3, 1.9 apart) is below a just-noticeable difference: the column and the "
        "letter carry the side (§7.3)"])


def exports() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.EXPORTS
    b1 = k.BOARDS[1].export
    lines = [k.ui(f"{b1} → {b1[:-4]}-{m}.png", "the export names cvd_sim.py writes") for m in
             ("greyscale", "deuteranopia", "protanopia")]
    k.spec_gap("§0 / §7.3: three simulated exports, but cvd_sim.py writes greyscale, deuteranopia and protanopia only: "
               "tritanopia has no image tool, so §7.3's computed tritanopia ΔE stands for it")
    forced = k.grid_table("§7.4 forced colours", [k.Col("c", "Carrier", 200), k.Col("f", "forced-colors: active", 760)],
                          [{"c": k.plain(c[0]), "f": k.plain(c[1])} for _i, c in k.FORCED],
                          cap=f"§7.4 L{k.FORCED[0][0]}: forced colours, per carrier (R32 R2)")
    head = k.text("how", k.ui("Made at export by docs/design/_tools/cvd_sim.py from board 01's dark export (a "
                              "filter, never a drawn colour):", "board-marker caption"), k.CAPTION, k.TEXT_2, w=900)
    return k.marker_frame(fid, [head, *[k.text(f"export {i}", x, k.NUM_SM, k.TEXT_1) for i, x in enumerate(lines)],
                                forced], 1008), k.frame_block(fid, [
        "§15 item 7: find bid and ask on the greyscale export without the legend (the column and the letter)"])


if __name__ == "__main__":
    ui.run(NN, [cvd(), legend(), exports()], 2)
