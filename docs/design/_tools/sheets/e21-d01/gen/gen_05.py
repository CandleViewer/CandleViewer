"""Board 05 tiers-and-shed: 500 → 200 → 50 — what each step loses, the shed order and the notice (memo §6 depth-tier
row, AD-7; F-10, F-11, F-12; C6; K1; T5). Every count, price and depth is derived from the seeded 500-level book."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 5
FW = 1440
IW = FW - 2 * k.FRAME_PAD


def walls_words(ws: list[tuple[int, k.Decimal]]) -> str:
    return ", ".join(f"{k.price(k.px(o))} ({k.size_fmt(s)})" for o, s in ws) or "none"


def depth_scale() -> k.Node:
    """The book from the far bid to the far ask of tier 500, one rect per tier (nested) and a tick per wall."""
    s5 = k.tier_stats(500)
    lo, hi = s5["bid"]["far"], s5["ask"]["far"]
    span = hi - lo + 1
    sc = IW / span

    def x(o: int) -> int:
        return int((o - lo) * sc)

    kids: list[k.Node] = []
    for i, t in enumerate(k.TIERS):
        st = k.tier_stats(t)
        a, b = x(st["bid"]["far"]), x(st["ask"]["far"]) + 1
        kids.append(k.rect(f"tier {t}", b - a, 20, (k.RAISED, k.HOVER, k.SELECTED)[i],
                           {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR}, x=a, y=4 + i * 4))
        kids.append(k.text(f"tier {t} · label", f"{t}: {k.price(k.px(st['bid']['far']))} – "
                                                f"{k.price(k.px(st['ask']['far']))}", k.NUM_SM, k.TEXT_1, x=a + 4,
                           y=32 + i * 18))
    for o, s in s5["bid"]["walls"] + s5["ask"]["walls"]:
        kids.append(k.rect(f"wall · {k.price(k.px(o))}", 3, 28, k.TEXT_1, x=x(o) - 1, y=0))
    kids.append(k.rect("mark", 2, 36, k.TEXT_1, x=x(0), y=0))
    k.derive(f"depth scale: {span} ticks from {k.price(k.px(lo))} to {k.price(k.px(hi))} drawn over {IW} px; wall ticks "
             f"(≥ {k.anchor(k.WALL)} BTC) at {walls_words(s5['bid']['walls'] + s5['ask']['walls'])}")
    return k.box("depth scale", kids, {}, w=IW, h=32 + 3 * 18 + 8)


def tiers(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("tier", "tier (levels a side)", 136), k.Col("reach", "reaches (bid – ask)", 216),
            k.Col("ticks", "ticks a side (bid ∕ ask)", 176), k.Col("depth", "cumulative depth, BTC (bid ∕ ask)", 248),
            k.Col("walls", "walls inside (price, BTC)", 616)]
    rows = []
    for t in k.TIERS:
        st = k.tier_stats(t)
        rows.append({"tier": f"{t}" + (" (default, PROPOSED)" if t == 200 else ""),
                     "reach": f"{k.price(k.px(st['bid']['far']))} – {k.price(k.px(st['ask']['far']))}",
                     "ticks": f"{st['bid']['ticks']} ∕ {st['ask']['ticks']}",
                     "depth": f"{k.size_fmt(st['bid']['depth'])} ∕ {k.size_fmt(st['ask']['depth'])}",
                     "walls": walls_words(st["bid"]["walls"] + st["ask"]["walls"])})
    lcols = [k.Col("step", "step", 136), k.Col("walls", "far walls beyond the tier", 392),
             k.Col("depth", "cumulative depth beyond it, BTC (bid ∕ ask)", 312),
             k.Col("rows", "heatmap rows outside it (below ∕ above)", 280), k.Col("f", "named in", 272)]
    lrows = []
    for hi, lo in ((500, 200), (200, 50)):
        ls = k.tier_loss(hi, lo)
        lrows.append({"step": f"{hi} → {lo}", "walls": walls_words(ls["bid"]["walls"] + ls["ask"]["walls"]),
                      "depth": f"{k.size_fmt(ls['bid']['depth'])} ∕ {k.size_fmt(ls['ask']['depth'])}",
                      "rows": f"{ls['bid']['rows']} ∕ {ls['ask']['rows']}", "f": "F-11"})
    k.derive("tiers: the first N levels a side of the seeded book; ticks a side = |far − best| + 1; losses = tier hi "
             "minus tier lo, a side")
    return (k.frame(fid, [depth_scale(),
                          k.grid_table("tiers", cols, rows, row_h=24, cap="What each tier holds (seeded book)"),
                          k.grid_table("losses", lcols, lrows, row_h=24,
                                       cap="What each step loses: " + k.memo("the far walls beyond the tier, the "
                                                                             "cumulative depth beyond it and the "
                                                                             "heatmap rows outside it")),
                          k.hbox("cards", [rb.card("F-10 (heuristic) · Major", [k.FINDINGS["F-10"][0][1]],
                                                   (IW - 12) // 2),
                                           rb.card("F-11 (heuristic) · Major", [k.FINDINGS["F-11"][0][1]],
                                                   (IW - 12) // 2)], {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "500 → 200 → 50: each step down loses the far walls, the cumulative depth and the heatmap rows "
                        "beyond the smaller tier (200 the default)", proposed=True),
            k.frame_block(fid, ["The ADR's measured gap is quoted in F-11 (a mid-cap symbol); the BTCUSDT numbers on "
                                "this frame are the seeded book's, not a measurement"], ads=["AD-7"],
                          fs=["F-10", "F-11"]))


def shed_order(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    d, _ln = k.DEFAULTS["Depth tier"]
    c6, _l = k.CONTRAS["C6"]
    k1, _k = k.KILLS["K1"]
    steps = [rb.card(f"step {i}", [k.memo(w)], 200, name=f"shed step {i}") for i, w in
             enumerate(("cadence", "trail", "depth"), 1)]
    arrow = [k.text(f"arrow {i}", "→", k.HEADING_MD, k.TEXT_2) for i in (1, 2)]
    return (k.frame(fid, [k.hbox("order", [steps[0], arrow[0], steps[1], arrow[1], steps[2],
                                           rb.marker("every tier change told, with the pin", None)],
                                 {"gap": k.INSET_MD}, h=64),
                          rb.card("Default (PROPOSED)", [d[1]], IW),
                          k.hbox("cards", [rb.card("C6 · four texts disagree", [c6[1], c6[2]], (IW - 24) // 3),
                                           rb.card("F-12 (heuristic) · Major", [k.FINDINGS["F-12"][0][1]],
                                                   (IW - 24) // 3),
                                           rb.card(f"K1 · {k1[1]}", [k1[2], k1[3]], (IW - 24) // 3)],
                                 {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "The shed order: cadence first, then the trail, then depth; never silent", proposed=True),
            k.frame_block(fid, ["C6 goes to E21-T07 #711 (memo §12.1); the order is PROPOSED, not ruled"],
                          ads=["AD-7"], fs=["F-12"]))


def notice(hi: int, lo: int, w: int) -> k.Node:
    ls = k.tier_loss(hi, lo)
    lines = [k.ui(f"Depth {hi} → {lo}", "notice title: both tiers (AD-7)"),
             k.ui(f"Far walls lost: {walls_words(ls['bid']['walls'] + ls['ask']['walls'])}", "lost item 1 (F-11)"),
             k.ui(f"Depth lost: {k.size_fmt(ls['bid']['depth'])} BTC bids, {k.size_fmt(ls['ask']['depth'])} BTC "
                  "asks", "lost item 2 (F-11)"),
             k.ui(f"Heatmap rows lost: {ls['bid']['rows']} below, {ls['ask']['rows']} above", "lost item 3 (F-11)")]
    pin = k.hbox(f"button · pin {hi}", [k.text("label", k.ui(f"Pin {hi}", "the pin control (AD-7)"), k.BODY_STRONG,
                                               k.TEXT_1)],
                 {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                  "strokeAlign": "inner"}, h=28, note="CMP-003 Button (lo-fi)")
    body = k.vbox("words", [k.text("title", lines[0], k.BODY_STRONG, k.TEXT_1, w=w - 56),
                            *[k.text(f"lost {i}", ln, k.BODY, k.TEXT_1, w=w - 56) for i, ln in enumerate(lines[1:], 1)],
                            pin], {"gap": k.STACK_XS}, w=w - 56)
    return k.hbox(f"notice · {hi} to {lo}", [k.icon("glyph", "info", k.TEXT_1), body],
                  {"pad": k.INSET_MD, "gap": k.INSET_SM, "align": "start", "fill": k.RAISED, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w,
                  note="the depth-shed notice (SCR-153 variant, E21-D03 #503)")


def shed_notice(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t5, _ln = k.PROBES["T5"]
    tier_sel = k.hbox("tier", [k.text("label", k.ui("depth", "header tier chip label"), k.CAPTION, k.TEXT_2),
                               *[rb.badge(str(t), strong=t == 200) for t in k.TIERS],
                               k.text("default", f"{k.memo('200 is the default tier')} (AD-7, PROPOSED) · "
                                                 f"{k.memo('500 only with heatmap_depth_500 on')}",
                                      k.CAPTION, k.TEXT_2)], {"gap": k.INSET_XS}, h=20)
    return (k.frame(fid, [tier_sel, k.hbox("notices", [notice(500, 200, 640), notice(200, 50, 640)],
                                           {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          rb.card(f"T5 · {t5[1]}", [t5[2], t5[3]], IW)],
                    FW, "The notice names both tiers, what was lost (the three items of F-11, as numbers) and the pin",
                    proposed=True),
            k.frame_block(fid, ["Notice words are kit labels (copy gaps): E21-D03 #503 writes SCR-153's variant",
                                "The numbers are the seeded book's losses (tiers frame)",
                                "Flag state (memo §9): " + k.memo("heatmap_depth_500 defaults to off")],
                          ads=["AD-7"], fs=["F-11", "F-12"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((tiers, shed_order, shed_notice), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=[f"Tiers drawn: {', '.join(str(t) for t in k.TIERS)} levels a side of one seeded "
                        f"{k.LEVELS}-level book; a wall = a level of at least {k.anchor(k.WALL)} BTC (kit illustration)"])
