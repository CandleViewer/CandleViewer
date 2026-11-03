"""Board 06 own-order-and-legend: the own-order column at the three tiers and the legend text (memo AD-5, AD-10;
F-14, F-16; C7; T3). The own orders are synthetic (two resting limits); the anchors are the kit's ramp edges."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 6
FW = 1280
IW = FW - 2 * k.FRAME_PAD


def column_at_tiers(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    lads = []
    for t in k.TIERS:
        lad = rb.ladder("ladder", 0, k.TRAIL[-1], k.MARKS[-1], show_own=True)
        lads.append(k.vbox(f"tier {t}", [k.hbox("tier", [k.text("label", k.ui("depth", "header tier chip label"),
                                                                 k.CAPTION, k.TEXT_2), rb.badge(str(t), strong=True)],
                                                {"gap": k.INSET_XS}, h=20), lad], {"gap": k.STACK_XS}, w=lad["w"]))
    x_own = rb.PRICE_W + rb.SIZE_W
    own = "; ".join(f"{side} {k.size_fmt(q)} {typ} at {k.price(k.px(o))}" for o, side, q, typ in k.OWN)
    k.derive(f"own-order column: x {x_own} px, width {rb.OWN_W} px in every tier's ladder; own orders (synthetic): "
             f"{own}")
    t3, _ln = k.PROBES["T3"]
    return (k.frame(fid, [k.hbox("tiers", lads, {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          rb.marker(f"own-order column: x {x_own} px, width {rb.OWN_W} px at 500, 200 and 50", None),
                          k.hbox("cards", [rb.card("F-14 (heuristic) · Major", [k.FINDINGS["F-14"][0][1]],
                                                   (IW - 24) // 3),
                                           rb.card("C7", [k.CONTRAS["C7"][0][1], k.CONTRAS["C7"][0][2]],
                                                   (IW - 24) // 3),
                                           rb.card(f"T3 · {t3[1]}", [t3[2], t3[3]], (IW - 24) // 3)],
                                 {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "Own orders live in a dedicated, fixed ladder column in text (side, size, type), the glyph a "
                        "second carrier; same place and width at every tier", proposed=True),
            k.frame_block(fid, ["Column heading 'own orders' is a kit label: C7 ('Your orders' vs 'My orders') is "
                                "E21-D04 #504's", "Cell words are kit labels (copy gaps); the arrow glyph is the "
                                "second carrier, never the only one"], ads=["AD-5"], fs=["F-14"]))


def legend(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    sentence = k.ui("Bids sit below the mark and asks above it; a brighter cell holds more resting size.",
                    "the convention sentence (AD-10); the bid/ask hue is user-configurable, so the hi-fi sentence "
                    "names the user's colours (E21-D04 #504)")
    scale = k.ui(f"scale: log, ×{k.anchor(k.RAMP[1] / k.RAMP[0])} a step; BTC per level", "the scale type and unit")
    counts = {i: sum(1 for o in rb.row_offs(0) if k.bucket(k.TRAIL[-1].get(o, k.Decimal(0))) == i) for i in range(5)}
    k.derive(f"anchors {', '.join(k.anchor(e) for e in k.RAMP)} BTC, each ×{k.anchor(k.RAMP[1] / k.RAMP[0])} the "
             f"last; visible rows at the last column per step 0..4: {counts}")
    box_ = k.vbox("CMP-113 legend", [k.text("title", k.ui("Legend", "legend title"), k.LABEL, k.TEXT_2),
                                     k.text("convention", sentence, k.BODY, k.TEXT_1, w=640),
                                     rb.legend_swatches(), k.text("scale", scale, k.NUM_SM, k.TEXT_1)],
                  {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=680,
                  note="CMP-113 legend (lo-fi)")
    return (k.frame(fid, [k.hbox("pair", [box_, k.vbox("cards", [
        rb.card("F-16 (heuristic) · Minor", [k.FINDINGS["F-16"][0][1]], IW - 680 - 24),
        rb.card("Evidence (memo F-16)", [k.FINDINGS["F-16"][0][2]], IW - 680 - 24)], {"gap": k.STACK_SM},
        w=IW - 680 - 24)], {"gap": k.INSET_XL, "align": "start"}, w=IW)],
        FW, "The legend states the bid/ask convention in words and the scale with numeric anchors (AD-10)",
        proposed=True),
        k.frame_block(fid, ["Four numeric anchors and the scale type are drawn (AD-10 asks for at least two)",
                            "Swatches are the lo-fi grey steps; E21-D04 #504 picks the ramp and verifies it"],
                      ads=["AD-10"], fs=["F-16"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((column_at_tiers, legend), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["Ladders: the seeded book at the trail's last column; the visible rows are inside every tier"])
