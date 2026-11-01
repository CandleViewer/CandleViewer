"""Board 02 `E47-D03 / 02 accent-warning` (light): V-2, Amber in light below 4.5:1 on a selected row, W-1 with its
warning glyph, the live-region note, the accent kept off text."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scr116 as h  # noqa: E402
from scr116 import k  # noqa: E402

NN, THEME, PRESET = 2, "light", "Amber"


def main() -> None:
    b = k.BOARDS[NN]
    if not k.acc_warns(THEME, PRESET):
        raise SystemExit("board 02: §8.2 no longer warns for Amber in light")
    fid = b.frames[0]
    fr = h.default_frame(fid, THEME, preset=PRESET, warning=True, focus="Accent", selected_row=True)
    lines = [*k.variant_lines("V-2"),
             f"{PRESET} in light: {k.acc(THEME, PRESET)}:1, below the bar {k.acc_bar(THEME):g} (§8.2 "
             f"L{k.PRESET_ROWS[PRESET][1]}); the nearest light case to AC4's 3.9:1 (D03-C5, §8.2 L{k.L('AC4')})",
             f"W-1 \"{k.w('W-1')}\" (§13 L{k.COPY['W-1'].line}) after a warning glyph in color.status.warning.strong; "
             f"W-21 with the preset's name: \"{k.w21_for(PRESET)}\"",
             "Live region: role=status, aria-live=polite; W-1 announced once on selection, coalesced to at most one "
             f"per second (R-8, §1.4 L{k.L('- **R-8')}); focus stays on the Amber swatch",
             f"Accent kept off text: the {PRESET} accent draws the selected row's 2 px border only; the current "
             "settings entry and every link keep color.text.link; env, buy / sell and status tokens untouched (R-5, R-7)",
             k.cr_line("link on a selected row", h.S34, ("light+",)),
             k.cr_line("focus colour on a selected row", h.S31, (THEME,)),
             *h.common_lines(THEME)[1:4]]
    k.ambiguity("Board 02: Amber's light primitive (palette.light.amber.700) and Cyan's (palette.cyan.700) have no "
                "semantic alias in the light set; the swatches and the selected-row border bind same-hue stand-ins "
                "and carry live rebind steps")
    p, md, pk = k.build(NN, [fr], [(fid, lines)])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
