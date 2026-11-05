"""Board 03 narrow-bar-readout: SCR-030/strip-NarrowBars-readout and SCR-030/strip-readout-overflow (§4.2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 3
NARROW = 32
ROWS13 = (*ui.ALL12, k.OTHER_8[0])  # a 13th row enabled in SCR-033 renders (D02-OQ1): the first of the other 8


def keyboard() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-NarrowBars-readout"
    b = next(x for x in k.window(NARROW) if x.t == "14:01")
    acc = k.W("W-5", label="Delta", value=k.value("Delta", b), unit=k.unit_word("Delta"), side=k.side("Delta", b))
    p = ui.P(n=NARROW, focus_cell=("Delta", b.t), readout=b.t, markers=[ui.acc_name(f"focused cell Delta · {b.t}",
                                                                                     acc)])
    return ui.chart(fid, p), k.frame_block(fid, [
        "Keyboard: the focused strip cell exposes its full value as its accessible text (W-5) and shows the readout "
        "for its bar while it has focus; Esc dismisses it; the chart cursor's ← / → step one bar (E47-D09:96)",
        "CMP-197 lists every enabled row's §7 label, value and unit in strip order (§4.2)",
        "The read shortcut's key and text stay E20-D04's (MEMO G7)"])


def overflow() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-readout-overflow"
    t = "13:58"
    p = ui.P(n=NARROW, rows=ROWS13, crosshair=t, readout=t)
    return ui.chart(fid, p), k.frame_block(fid, [
        f"{len(ROWS13)} rows enabled ({ROWS13[-1]} the 13th, D02-OQ1): the readout lists 12 and shows W-6, its path "
        f"to SCR-045 (§7); \"Alt+T\" is the catalogue's table alternative (15:2598, MEMO AD-4), not a new key",
        "On pointer the readout stays while hovered (1.4.13)", k.source_line(ROWS13[-1])])


if __name__ == "__main__":
    ui.run(NN, [keyboard(), overflow()], 2)
