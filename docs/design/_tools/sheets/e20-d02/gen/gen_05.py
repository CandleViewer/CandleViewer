"""Board 05 forming-partial-empty: SCR-030/strip-forming, -PartialHistory, -Empty(no recording) (§3.7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 5
PARTIAL_FROM = "13:56"  # kit: the first bar with recorded order flow (W-8's <ts>)


def forming() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-forming"
    f = k.window(16)[-1]
    acc = f"Delta % {k.value('Delta %', f)}, {k.side('Delta %', f)} side" + k.W("W-5", 1)
    p = ui.P(crosshair=f.t, readout=f.t, markers=[ui.acc_name(f"forming cell Delta % · {f.t}", acc)])
    k.derive(f"the forming cell's accessible text: §3.6's neutral form + W-5's \"{k.W('W-5', 1)}\"")
    return ui.chart(fid, p), k.frame_block(fid, [
        "The last bar's cells reuse SCR-030's forming-bar treatment (form E12-D06's; 14:759); the column header, the "
        "readout and the data cursor carry the word (W-7); each forming cell's accessible text ends \", forming\"",
        "Values swap in place, no shimmer; no announcement (R-4)",
        f"Delta % {k.value('Delta %', f)} sits near the {k.PCT_BOUND} % bound: a breach-state change (shade, glyph and "
        f"word together) at most twice a second with a hold (FR-6, E47-D08:194), both motion modes; the readout "
        f"shows the true value at once"])


def partial() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-PartialHistory"
    p = ui.P(partial_from=PARTIAL_FROM, markers=[ui.acc_name("each empty cell left of the boundary", k.W("W-28"))])
    return ui.chart(fid, p), k.frame_block(fid, [
        "SCR-030's partial-history boundary, variants and copy (14:762): left of it the cells are visually empty — "
        "no zero, no dash — each with the accessible text W-28, a stated absence (R-2)",
        f"The boundary tag reads W-8 and names the first available bar ({PARTIAL_FROM})"])


def empty() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-Empty(no recording)"
    p = ui.P(empty=True, focus_gear=True, markers=[ui.announce(k.W("W-9"), how='polite, once (role="status")'),
                                                   ui.acc_name("each empty cell", k.W("W-28"))])
    return ui.chart(fid, p), k.frame_block(fid, [
        "No bar in range has recorded order flow: the label column stays, the cells are empty (W-28), one centred "
        "line reads W-9 (PROPOSED), a role=\"status\" node announced once after a range change",
        "The gear stays operable (drawn focused)"])


if __name__ == "__main__":
    ui.run(NN, [forming(), partial(), empty()], 2)
