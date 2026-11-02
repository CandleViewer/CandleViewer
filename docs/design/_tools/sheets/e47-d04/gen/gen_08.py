"""E47-D04 / 08 ring-spec (and its twins 09 light, 10 high contrast with the thick geometry): the ring geometry
(normal, inset, thick) and the ring over the 12 backgrounds of §7.6. Every fill is a token; the theme is set at
export; every ratio is the spec's tool output (k.CONTRAST)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

L71, L72, L73 = k.L("### 7.1 Geometry"), k.L("### 7.2 The two-tone technique"), k.L("### 7.3 The high-visibility")
L76 = k.L("### 7.6 The ring over the 12 worst-case backgrounds")
L74 = k.L("### 7.4 The CMP-039 contract")
ZOOM = 8  # the cross-section scale: 1 px drawn as 8 px
CARD_W = 280


def cross_section(variant: str) -> k.Node:
    """The bands from the control's edge outward, each px drawn ZOOM px wide: control, offset, halo, ring, halo."""
    off = k.GEOM_PX[variant][2]
    bands = [("control", k.ACTION_SECONDARY, 2)] + ([("offset", k.RAISED, off)] if off else [])
    bands += [(("ring" if c == k.RING else "halo"), c, k.PX[t]) for c, t in reversed(k.ring_bands(variant))]
    kids = [k.rect(f"{i} {nm} {px} px", px * ZOOM, 40, c) for i, (nm, c, px) in enumerate(bands, 1)]
    parts = [f"{nm} {px}" for nm, _c, px in bands[1:]]
    if variant == "inset":
        kids = [k.rect(f"{i} {nm} {px} px", px * ZOOM, 40, c) for i, (nm, c, px) in
                enumerate(reversed(bands[1:]), 1)] + [k.rect("control interior", 2 * ZOOM, 40, k.ACTION_SECONDARY)]
        parts = list(reversed(parts))
    total = sum(px for _n, _c, px in bands[1:])
    return k.vbox(f"cross-section ×{ZOOM} · {variant}", [
        k.hbox("bands", kids, None, h=40),
        k.text("legend", ("edge → in: " if variant == "inset" else "edge → out: ") + " · ".join(p + " px" for p in parts)
               + f" = {total} px", k.CAPTION, k.TEXT_2, w=CARD_W - 24)], {"gap": k.STACK_XS}, w=CARD_W - 24)


def spec_card(variant: str, *, prominent: bool = False) -> k.Node:
    g = k.GEOMETRY[variant]
    if variant == "inset":
        cols = (k.Col("price", "Price", 120, True), k.Col("size", "Size", 120, True))
        sample = k.table_row(cols, {"price": k.px_fmt(k.BEST_BID), "size": "1.250"}, "row (focused)", 1, h=k.ROW_H,
                             focused=True, fill=k.CANVAS)
    else:
        sample = k.button("Cancel", "secondary", focused=variant)
    stage = k.hbox("stage", [sample], {"justify": "center", "fill": k.RAISED, "radius": k.R_CARD},
                   w=CARD_W - 24, h=96 if prominent else 72)
    lines = [f"Ring: {g.ring}", f"Halo: {g.halo}", f"Offset: {g.offset}", f"Trigger: {g.trigger}"]
    if variant != "inset":
        lines.append(f"Outer extent: {k.extent(variant)} px (§7.5)")
    return k.vbox(f"card · {variant}", [k.text("title", g.variant, k.HEADING_SM, k.TEXT_1), stage,
                                         cross_section(variant),
                                         k.lines_block("rows", lines, w_=CARD_W - 24, typo=k.CAPTION, color=k.TEXT_2)],
                  {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.CANVAS, "radius": k.R_CARD, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=CARD_W)


def panel_card() -> k.Node:
    """§7.4: the panel frame is CMP-080's, not CMP-039 (R-9)."""
    k.fallback("panel-focus")
    hdr = k.hbox("header", [k.text("h2", dict(k.PANELS)["dom"], k.BODY_STRONG, k.TEXT_1)],
                 {"padX": k.INSET_SM, "fill": k.RAISED}, w=CARD_W - 24, h=k.HEADER_H)
    mini = k.vbox("panel (focused)", [hdr, k.box("body", [], {"fill": k.CANVAS}, w=CARD_W - 24, h=60),
                                       k.box("frame", [], {"stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                                           "strokeAlign": "inner"}, w=CARD_W - 24, h=88, x=0, y=0,
                                             abs=True),
                                       k.rect("header bar", CARD_W - 24, 3, k.RING, x=0, y=0, abs=True)],
                  {"clip": True}, w=CARD_W - 24, h=88)
    return k.vbox("card · panel focus", [k.text("title", "panel focus (CMP-080, not CMP-039)", k.HEADING_SM, k.TEXT_1),
                                         mini, k.lines_block("rows", [
                                             "2 px inset frame + the header bar in color.focus.ring, inside the box; "
                                             "never a ring around the panel (§7.4; `16`:88)"], w_=CARD_W - 24,
                                             typo=k.CAPTION, color=k.TEXT_2)],
                  {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.CANVAS, "radius": k.R_CARD, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=CARD_W)


def pair_line(theme: str) -> k.Node:
    return k.text("pair", f"Two tones: the ring–halo pair is {k.ratio('pair.' + theme)}:1 ({k.THEME_WORD[theme]}); "
                          "the rule is pair ≥ 3:1 and edge ≥ 3:1 on every measured background (§7.2)",
                  k.BODY, k.TEXT_1, w=k.FRAME_W - 80)


def frame_geometry(fid: str, theme: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cards = k.hbox("cards", [spec_card("normal"), spec_card("inset"), spec_card("thick"), panel_card()],
                   {"gap": k.INSET_LG, "align": "start"})
    fr = k.specimen_frame(fid, [k.text("h", "CMP-039 focus ring · geometry (§7.1)", k.HEADING_MD, k.TEXT_1),
                                cards, pair_line(theme)])
    lines = [f"§7.1 L{L71}: the three variants as their rows read (parsed): " + "; ".join(
        f"{g.variant}: ring {g.ring}, halo {g.halo}, offset {g.offset}" for g in k.GEOMETRY.values()),
             f"§7.5 L{k.EXTENT_LINE}: outer extent offset + halo + ring + halo = {k.extent('normal')} px normal, "
             f"{k.extent('thick')} px thick (computed from the bands, checked against the line)",
             f"§7.2 L{L72}: pair {k.ratio('pair.' + theme)}:1 in {k.THEME_WORD[theme]} (tool output)",
             f"Each cross-section draws 1 px as {ZOOM} px, from the control's edge out (inset: from the edge in)",
             f"§7.4 L{L74}: the panel frame is a separate responsibility (R-9)"]
    return fr, k.frame_block(fid, lines, waits=("D04-G5", "D04-G6"))


def tile(bg: k.Background, theme: str, variant: str) -> k.Node:
    tw = (k.FRAME_W - 80 - 3 * 16) // 4
    stage = k.hbox("background", [k.button("Cancel", "secondary", focused=variant)],
                   {"justify": "center", "fill": bg.token}, w=tw, h=96, note=f"fill {bg.token}")
    ring_r, edge_r = bg.r(theme, "ring"), bg.r(theme, "edge")
    ok = float(edge_r) >= 3
    cap = k.vbox("caption", [k.text("token", f"{bg.n}  {bg.token}", k.LABEL, k.TEXT_1, w=tw - 16),
                             k.text("why", bg.why, k.CAPTION, k.TEXT_2, w=tw - 16),
                             k.hbox("ratios", [k.icon("verdict", "check" if ok else "danger", k.TEXT_1),
                                               k.text("r", f"ring {ring_r} · edge {edge_r}", k.NUM, k.TEXT_1)],
                                    {"gap": k.INSET_XS})], {"gap": k.STACK_XS, "pad": k.INSET_SM}, w=tw)
    return k.vbox(f"tile {bg.n:02d}", [stage, cap], {"fill": k.CANVAS, "radius": k.R_CARD, "clip": True,
                                                    "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                    "strokeAlign": "inner"}, w=tw)


def frame_backgrounds(fid: str, theme: str, variant: str) -> tuple[k.Node, tuple[str, list[str]]]:
    tiles = [tile(bg, theme, variant) for bg in k.BACKGROUNDS]
    grid = k.vbox("grid", [k.hbox(f"tiles {r + 1}", tiles[r * 4:r * 4 + 4], {"gap": k.INSET_LG, "align": "start"})
                           for r in range(3)], {"gap": k.STACK_LG})
    th = k.THEME_WORD[theme]
    fr = k.specimen_frame(fid, [k.text("h", f"The ring over the 12 backgrounds of §7.6 · {th} · {variant}",
                                       k.HEADING_MD, k.TEXT_1), grid,
                                k.text("min", f"Lowest edge over all three themes {k.ratio('min.edge')}:1; lowest "
                                              f"single-colour ring {k.ratio('min.ring')}:1 (§7.6)", k.CAPTION,
                                       k.TEXT_2, w=k.FRAME_W - 80)])
    fails = [bg.n for bg in k.BACKGROUNDS if float(bg.r(theme, "edge")) < 3]
    lines = [f"§7.6 L{L76}: ratios by the WCAG 2.x formula over the resolved tokens, truncated to two decimals; "
             f"ring = color.focus.ring alone, edge = the better of ring and halo (the spec's tool output, rows "
             f"L{k.BACKGROUNDS[0].line}-L{k.BACKGROUNDS[-1].line})",
             f"{th}: edge ≥ 3:1 on {12 - len(fails)} of 12 (check glyph per tile); the ring alone is under 3:1 on "
             + ", ".join(str(bg.n) for bg in k.BACKGROUNDS if float(bg.r(theme, "ring")) < 3),
             "Each tile: the background token as the fill, a Cancel button with the ring; the caption strip sits on "
             "color.surface.canvas so its words do not depend on the background",
             f"Rows 3-4 are the CVD tokens measured in every theme; the CVD-theme rings wait on E47-D03 (§0 L"
             f"{k.NOT_DRAWN_LINE})"]
    return fr, k.frame_block(fid, lines, waits=("D04-G1",))


def build(theme: str = "dark") -> None:
    nn = {"dark": 8, "light": 9, "hc": 10}[theme]
    fids = k.frames_of(nn)
    if theme == "hc":
        from gen_10 import frame_thick  # the high-contrast twin's first frame: the thick geometry (§7.3)
        f1 = frame_thick(fids[0])
        f2 = frame_backgrounds(fids[1], theme, "thick")
    else:
        f1 = frame_geometry(fids[0], theme)
        f2 = frame_backgrounds(fids[1], theme, "normal")
    k.build_all(nn, [f1[0], f2[0]], k.annotations(nn, [f1[1], f2[1]]))


if __name__ == "__main__":
    build("dark")
