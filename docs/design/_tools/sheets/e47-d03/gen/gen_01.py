"""Board 01 `E47-D03 / 01 scr116-default` (dark): V-1, every control of §8.1, the accent presets with names and the
check glyph, the PreviewTile. build_frames(theme) is reused by board 04 (light twin; its first frame only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scr116 as h  # noqa: E402
from scr116 import k  # noqa: E402

NN = 1


def specimen_frame(fid: str, theme: str) -> dict:
    """The PreviewTile at size and the four presets, each in its chosen state (check glyph + ring), with §8.2's and
    §3.6's figures for the theme."""
    presets = []
    for p in k.PRESETS:
        sw = k.swatch(p, theme, chosen=True)
        c36 = next(c for ln, c in k.table_after("### 3.6 The accent swatch") if k.plain(c[0]) == f"check glyph on {p}")
        figs = k.vbox("figures", [
            k.text("acc", f"text use {k.acc(theme, p)}:1 (bar {k.acc_bar(theme):g})", k.NUM_SM, k.TEXT_1),
            k.text("check", f"check glyph {k.plain(c36[{'dark': 4, 'light': 5, 'hc': 6}[theme]])}:1 (bar 3)",
                   k.NUM_SM, k.TEXT_1),
            k.text("warn", "W-1 shown" if k.acc_warns(theme, p) else "no warning", k.CAPTION, k.TEXT_2)],
            {"gap": k.STACK_XS})
        presets.append(k.vbox(f"preset card · {p}", [sw, figs], {"gap": k.STACK_SM, "pad": k.INSET_MD,
                                                                  "fill": k.RAISED, "radius": k.R_CARD}, w=200))
    picker = k.vbox("accent presets", [k.text("heading", k.w_label("W-9"), k.HEADING_SM, k.TEXT_1),
                                       k.hbox("cards", presets, {"gap": k.INSET_LG, "align": "start"})],
                    {"gap": k.STACK_SM})
    tile = k.vbox("tile specimen", [k.text("heading", "PreviewTile (CMP-228)", k.HEADING_SM, k.TEXT_1),
                                    k.preview_tile(theme, "Blue")], {"gap": k.STACK_SM})
    content = k.vbox("specimen", [k.text("h1", "Appearance", k.HEADING_MD, k.TEXT_1), tile, picker],
                     {"gap": k.STACK_LG, "pad": k.INSET_XL, "fill": k.APP}, w=k.CONTENT_W)
    return k.window(k.frame_name(fid), theme, content, note="specimen: the tile and the four presets, chosen state")


def build_frames(theme: str) -> list[dict]:
    b = k.BOARDS[NN]
    f1 = h.default_frame(b.frames[0].replace("dark", theme), theme)
    f2 = specimen_frame(b.frames[1].replace("dark", theme), theme)
    return [f1, f2]


def blocks(theme: str, fids: list[str]) -> list[tuple[str, list[str]]]:
    out = [(fids[0], [*k.variant_lines("V-1"), *h.common_lines(theme)])]
    if len(fids) > 1:
        out.append((fids[1], [
            f"The four presets (W-9 \"{k.w('W-9')}\"), each drawn chosen: swatch 24 x 24 (2.5.8), check glyph in "
            f"color.text.inverse (§3.6 L{k.L('### 3.6')}), 2 px color.border.selected ring; never a ring alone",
            *[f"{p}: {k.acc_primitive(theme, p)} via {k.swatch_token(theme, p)[0]}"
              + ("" if k.swatch_token(theme, p)[1] else " (stand-in, live rebind)") for p in k.PRESETS],
            f"The tile (§8.1 L{k.L('The PreviewTile (CMP-228')}): a footprint cell, a ladder row and a positions row; "
            f"role=img, never the only disclosure of a setting; synthetic sample data (§8.4)",
        ]))
    return out


def main() -> None:
    b = k.BOARDS[NN]
    frames = build_frames("dark")
    k.ambiguity("Board 01 frame 2 (SCR-116/preview-tile): §G names the frame, §0 asks for the presets with names "
                "and the check glyph and the PreviewTile: drawn as a specimen window (the tile at size, each preset "
                "in its chosen state with §8.2 / §3.6 figures), not a second screen state")
    p, md, pk = k.build(NN, frames, blocks("dark", list(b.frames)), per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
