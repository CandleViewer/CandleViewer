"""Board 08 `E47-D03 / 08 env-badge-themes` (mixed): CMP-074 / CMP-075 LIVE and DEMO in dark, light, high contrast and
the CVD-safe palette (§9; R-7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inkboards as ib  # noqa: E402
from inkboards import k  # noqa: E402

NN = 8
S9 = "## 9. CMP-074 / CMP-075 in every theme"


def frame(fid: str) -> tuple[dict, list[str]]:
    var = fid.rsplit("· ", 1)[1]
    theme = {"dark": "dark", "light": "light", "hc": "hc", "cvd-safe": "dark"}[var]
    t9 = "dark" if var == "cvd-safe" else theme
    rows = [k.cr_line(r, S9, (t9,)) for r in ("word LIVE / DEMO", "LIVE border and glyph", "DEMO border and glyph")]
    banners = k.vbox("CMP-074 EnvBanner", [k.text("label", "CMP-074 EnvBanner", k.LABEL, k.TEXT_2),
                                           k.env_badge("live", banner=True, w_=560),
                                           k.env_badge("demo", banner=True, w_=560)], {"gap": k.STACK_SM})
    badges = k.vbox("CMP-075 EnvBadgeLocal", [k.text("label", "CMP-075 EnvBadgeLocal", k.LABEL, k.TEXT_2),
                                              k.hbox("badges", [k.env_badge("live"), k.env_badge("demo")],
                                                     {"gap": k.INSET_LG}, h=24)], {"gap": k.STACK_SM})
    left = k.vbox("specimens", [banners, badges, k.evidence(f"§9 in {t9}", rows, w_=560)], {"gap": k.STACK_LG}, w=560)
    items = [left]
    if var == "cvd-safe":
        items.append(k.vbox("chart ink", [k.bubbles_panel("cvd-safe")], None, w=k.PANEL_W))
    hdr = k.ink_header(f"Environment badges · {var}" + (" (dark theme, CVD-safe chart palette)" if var == "cvd-safe"
                                                        else ""), "none", "cvd-safe" if var == "cvd-safe" else
                       "default")
    content = k.vbox("workspace", [hdr, k.hbox("row", items, {"gap": k.INSET_XL, "align": "start"})],
                     {"gap": k.STACK_MD, "pad": k.INSET_LG, "fill": k.APP}, w=k.FRAME_W - k.NAV_W)
    status = [k.placeholder("connection chip", 120), k.text("env word", "LIVE", k.BODY_STRONG, k.TEXT_1,
                                                            note="the status bar repeats the environment in words")]
    fr = k.window(k.frame_name(fid), theme, content, badge=k.env_badge("live"), status=status, settings=False,
                  note=f"export under the {theme} set" + (" with the CVD-safe chart palette" if var == "cvd-safe" else ""))
    lines = [f"Export set: {theme}" + ("; data-palette=cvd-safe remaps chart ink only (R-5)" if var == "cvd-safe" else ""),
             *rows,
             f"Accessible name W-3 \"{k.w('W-3')}\" (DEMO: its Demo form); the word, then the glyph's shape (filled dot "
             f"in a ring / outline dot), then the weight; the hue is the fourth channel (§9 L{k.L('**Stated on CMP-074')})"]
    if var == "light":
        lines.append(k.de_line("LIVE / DEMO border", "light", "grey"))
    if var == "hc":
        lines.append("High contrast does not change color.env.* (THC; R-7)")
    return fr, lines


def main() -> None:
    b = k.BOARDS[NN]
    frames, blocks = [], []
    for fid in b.frames:
        fr, lines = frame(fid)
        frames.append(fr)
        blocks.append((fid, lines))
    k.ambiguity("Board 08 is 'mixed' (§0): token binds resolve under one active set, so the md's line 3 says theme "
                "dark and a live check exports each frame under its own set and composites the PNG")
    p, md, pk = k.build(NN, frames, blocks, per_row=2)
    print(p.name, md.name, pk.name, ib.__name__)


if __name__ == "__main__":
    main()
