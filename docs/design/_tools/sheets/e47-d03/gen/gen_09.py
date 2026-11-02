"""Board 09 `E47-D03 / 09 data-ink-ramps` (dark): heatmap, profile, candle and delta ink with their ratios and L*
order (§3.2, §3.3, §7.3). build_frame(theme) is reused by board 10 (light twin, after D03-D7 … D03-D14)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inkboards as ib  # noqa: E402
from inkboards import k  # noqa: E402

NN = 9


# §4.2's stale pairs (D03-A11 removes them): a true measurement, but not a §3.2 row, so not drawn
STALE = {("dark", "color.heatmap.ask.2")}
NO_ANCHOR = "no anchored ratio (§3.3 anchors stops 1 and 5)"


def ratio(theme: str, tok: str) -> str | None:
    if (theme, tok) in STALE:
        if "remove (D03-A11)" not in k.SPEC_LINES[k.L(f"{theme}:{tok} on color.surface.canvas") - 1]:
            raise SystemExit(f"board 09: {theme}:{tok} is no longer §4.2's stale pair")
        return None
    try:
        return f"{k.cr(theme, tok, k.CANVAS)}:1"
    except KeyError:
        return None


def hm_group(theme: str, palette: str, side: str) -> tuple[dict, list[str]]:
    lines: list[str] = []
    chips = []
    plus = theme == "light" and palette == "cvd-safe"
    for i in range(1, 6):
        tok = k.ink(palette)[f"hm.{side}.{i}"]
        bound, sub = tok, None
        r = ratio(theme, tok)
        if plus:
            bound = k.light_plus_stop(side, i)
            r = ratio("light+", tok) or ratio("light", bound)
            if bound != tok:
                d = next(n for n, x in k.DIFF.items() if x["token"] == tok and x["set"] == "semantic-light")
                sub = d
                on = (f"{r} on the canvas" + (" (§3.4)" if ratio("light+", tok) else f" (= §3.3 light {bound})")
                      if r else NO_ANCHOR)
                lines.append(f"{side} stop {i}: binds {bound} (today's holder of {k.DIFF[d]['new']}, {d}); {on}")
        chips.append(k.ink_chip(f"{side} {i}", bound, r, sub=sub))
    name = "CVD heatmap " + side if palette == "cvd-safe" else "heatmap " + side
    key = (name + (", retuned" if plus else ""), "light+" if plus else theme)
    verdict = k.ramp_line(*key)
    title = f"Heatmap {side}, {'CVD-safe' if palette == 'cvd-safe' else 'default'} palette: stop 1 → 5 = more size"
    return k.ramp_group(title, chips, verdict, 5 * 88 + 4 * 8 + 24), [verdict, *lines]


def chip_group(theme: str, title: str, items: list[tuple[str, str]]) -> dict:
    chips = [k.ink_chip(lab, tok, ratio(theme, tok)) for lab, tok in items]
    return k.ramp_group(title, chips, "Bar 3:1 on the canvas (§3, R-3: truncated)", len(items) * 96 + 24)


def build_frame(theme: str) -> tuple[dict, list[str]]:
    fid = f"ink/ramps · {theme}"
    lines: list[str] = []
    hm = []
    for pal in ("default", "cvd-safe"):
        for side in ("bid", "ask"):
            g, ls = hm_group(theme, pal, side)
            hm.append(g)
            lines += ls
    d, c = k.ink("default"), k.ink("cvd-safe")
    row3 = [chip_group(theme, "Profile", [("bar (HVN / LVN)", d["bar"]), ("value area", d["va"]), ("POC", d["poc"])]),
            chip_group(theme, "Candles", [("up", d["up"]), ("down", d["down"])]),
            chip_group(theme, "Delta, default", [("buy, delta +", d["buy"]), ("sell, delta −", d["sell"]),
                                                 ("imbalance", d["imbalance"])]),
            chip_group(theme, "Delta, CVD-safe", [("buy, delta +", c["buy"]), ("sell, delta −", c["sell"]),
                                                  ("imbalance", c["imbalance"])])]
    hdr = k.ink_header(f"Data-ink ramps and ink on the canvas · {theme}", "none", "default")
    items = hm + row3
    content = k.vbox("workspace", [hdr, k.hbox("band 1", hm[:2], {"gap": k.INSET_LG, "align": "start"}),
                                   k.hbox("band 2", hm[2:], {"gap": k.INSET_LG, "align": "start"}),
                                   k.hbox("band 3", row3, {"gap": k.INSET_MD, "align": "start"})],
                     {"gap": k.STACK_SM, "pad": k.INSET_LG, "fill": k.APP}, w=k.FRAME_W - k.NAV_W)
    if k.est_height(content) > k.BODY_H:
        raise ValueError(f"{fid}: about {k.est_height(content):.0f} px")
    del items
    lines.append(f"High contrast inherits dark's ramps (§7.3 L{k.L('High contrast inherits dark')}); not drawn (§0)")
    return k.window(k.frame_name(fid), theme, content, settings=False), lines


def main() -> None:
    b = k.BOARDS[NN]
    fr, lines = build_frame("dark")
    p, md, pk = k.build(NN, [fr], [(b.frames[0], lines)])
    print(p.name, md.name, pk.name, ib.__name__)


if __name__ == "__main__":
    main()
