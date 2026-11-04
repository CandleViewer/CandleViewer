"""Board 02 compact-and-collapse: SCR-030/strip-CompactMode and SCR-030/strip-NarrowBars (§3.4, §4.1, §4.3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 2
NARROW = 32  # kit: 32 visible bars, a 32 px pitch under the seeded 40 px floor (E18-D02:124)


def perf_lines() -> list[str]:
    return [f"Performance (§4.3, D02-C2): the {k.CEILING}-row ceiling; both budgets recorded — "
            f"\"{k.S('<=1.5 ms per frame')}\" (14:874) and \"{k.S('strip adds ≤2 ms per frame')}\" (11:1885)",
            "Recomputed on bar close and on the visible-range change (14:874); the forming bar coalesced to 4 Hz "
            "(15:2936; MEMO C6, E20-T02)"]


def compact() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-CompactMode"
    rows = tuple(r["label"] for r in k.COMPACT_ROWS)
    names = "; ".join(f"{r['x']} → {r['label']}" for r in k.COMPACT_ROWS)
    p = ui.P(rows=rows, short=True, markers=[ui.acc_name("row headers' accessible names", names)])
    return ui.chart(fid, p), k.frame_block(fid, [
        "The user's row-set choice in SCR-033 (14:865), never the automatic collapse (§4): the default's first three "
        "in order, each with its PROPOSED short label and its §7 label as its accessible name (MEMO A6)",
        "Compact mode does not change how a cell renders; on narrow bars a compact strip still collapses (§4.1)",
        *[k.source_line(x) for x in rows]])


def narrow() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-NarrowBars"
    bars = k.window(NARROW)
    b = next(x for x in bars if x.t == "14:01")
    f = bars[-1]
    acc = k.W("W-5", label="Delta", value=k.value("Delta", b), unit=k.unit_word("Delta"), side=k.side("Delta", b))
    accf = k.W("W-5", label="Delta", value=k.value("Delta", f), unit=k.unit_word("Delta"),
               side=k.side("Delta", f)) + k.W("W-5", 1)
    p = ui.P(n=NARROW, markers=[ui.acc_name(f"cell Delta · {b.t}", acc), ui.acc_name(f"cell Delta · {f.t}", accf)])
    k.derive(f"pitch {ui.PLOT_W} / {NARROW} = {ui.PLOT_W / NARROW:.0f} px < the {k.FLOOR_PX} px seed floor: every "
             f"cell collapses (§4.1)")
    return ui.chart(fid, p), k.frame_block(fid, [
        f"Below the minimum legible bar width ({k.FLOOR_PX} px here: E20-K01's number, seeded from E18-D02:"
        f"{k.FLOOR_LINE}, MEMO G5) each cell drops its digits and keeps its row class's glyph: ▲ / ▼ signed, · "
        f"(PROPOSED) unsigned, the breach-glyph slot added on a breached cell; row labels stay; nothing clipped",
        "Each cell's accessible text keeps the full value, its unit and the sign word (W-5)",
        *perf_lines()])


if __name__ == "__main__":
    ui.run(NN, [compact(), narrow()], 2)
