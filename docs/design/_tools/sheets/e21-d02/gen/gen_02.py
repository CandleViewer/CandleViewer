"""Board 02 tiers-500-unavailable: the tier strip 50 / 200 / 500 at compact (§3), SCR-050/500-unavailable (the option
T2, M OQ-4) and the tier notice (§11.1)."""
from __future__ import annotations

import math
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 2


def tier(t: int) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = f"SCR-050/streaming · tier {t}"
    p = ui.P(tier=t, w2=t == 500, tier_notice=k.S("Depth 200 → 500 · rebuilding") if t == 500 else None)
    ends = (k.extent_end("bid", t), k.extent_end("ask", t))
    k.derive(f"tier {t}: the extent ends at {k.price0(ends[0])} (bids) and {k.price0(ends[1])} (asks): the {t}th "
             f"level a side of the seeded book; rows beyond it hold no level and are not drawn; stops "
             f"{[str(x) for x in k.stops(t)]} BTC (adaptive per tier)")
    m = [ui.announce(k.S("Depth 200 → 500 · rebuilding"))] if t == 500 else []
    lines = [f"Row matrix (§3.1 L{k.MATRIX[0][0]}): {k.plain(next(c for _i, c in k.MATRIX if c[0] == str(t))[1])}",
             "A tier is a scroll extent, never an aggregation: + / - zoom aggregates ticks in both regions at every "
             "tier alike (R-2; H-6)"]
    if t == 500:
        w2 = re.findall(r'"([^"]+)"', k.COPY["W-2"][0][2])[0]
        lo, hi = (Decimal(x.replace(",", "")) for x in re.search(r"showing ([\d,]+)–([\d,]+)", w2).groups())
        n_rows = ui.body_h(p) // p.row_h
        rows = k.rows_window(math.ceil(ui.body_h(p) / p.row_h))[:n_rows]
        fits = [z for z in range(1, 1001) if (hi - lo) * 10 % z == 0 and (hi - lo) * 10 // z + 1 == n_rows]
        k.spec_gap(f"W-2's example \"{w2}\" spans {int((hi - lo) / k.STEP) + 1} rows at the {k.STEP:.0f} USDT zoom "
                   f"(§3.1's comfortable \"about 18 rows\"), but §0 draws the tier strip at compact, where this frame "
                   f"shows {n_rows} rows under the tier notice; no zoom on the {k.TICK} tick puts {n_rows} rows on "
                   f"{k.price0(lo)}–{k.price0(hi)} ({len(fits)} fit) and 500 × comfortable is a not-drawn cell (§0): "
                   f"the header keeps W-2's form with the drawn rows ({k.price0(rows[-1])}–{k.price0(rows[0])}), "
                   f"the only figure consistent with the ladder; the spec owner to re-figure W-2")
        lines += ["The header reads W-2, its range the drawn window's first and last rows; the count the subscribed "
                  "tier's (`23`:747); the tier notice carries dom.depth_changed {from, to, cause: user} (§11.1), "
                  "polite once; focus stays on its price row",
                  "500 is flag and spike gated (heatmap_depth_500 off by default; PENDING E21-K01 #603): drawn here "
                  "as the flag-on view; the unavailable variant is the next frame"]
    return ui.panel(fid, p, markers=m), k.frame_block(fid, lines)


def unavailable() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/500-unavailable"
    p = ui.P(menu="depth")
    return ui.panel(fid, p, markers=[ui.announce(k.W("W-3"), how="polite, each press (R-7)")]), k.frame_block(fid, [
        "The 500 option stays in the open listbox, arrow-reachable, rendering 2a under the option: aria-disabled, "
        "never disabled; CMP-079 + the CMP-019 lock; W-3 on the PROPOSED key book.tier_unavailable (owner E09-D09 "
        "#192, A-4)",
        "Enter on 500 changes nothing and re-shows W-3; a server refusal of a tier change is T4 at the point of "
        "action, not this frame (§3.2)"])


if __name__ == "__main__":
    ui.run(NN, [tier(50), tier(200), tier(500), unavailable()], 2)
