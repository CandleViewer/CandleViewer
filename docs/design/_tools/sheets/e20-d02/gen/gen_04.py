"""Board 04 thresholds-breached-greyscale: SCR-030/strip-ThresholdsBreached, its greyscale twin frame and the
per-symbol set named (§3.6; AC 3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 4


def table_texts() -> list[str]:
    """§3.6's accessible texts, verbatim (each matches the world's drawn value: the kit self-test checks it)."""
    return [k.unquote(c[6]) for _i, c in k.BREACH_ROWS]


def breached(fid: str, shade: bool) -> tuple[k.Node, tuple[str, list[str]]]:
    p = ui.P(shade=shade, markers=[ui.acc_name("accessible text, §3.6 (PROPOSED)", "; ".join(table_texts()), w=520)])
    lines = ["A breached cell carries three marks: a shade (hi-fi E20-D03), the breach-glyph slot (a shape distinct "
             "from both sign glyphs, its form E20-D03's) and the word (W-3) above the value (§3.6)",
             "Signed rows compare the magnitude (abs >, MEMO AD-6): one bound marks a buy bar and a sell bar alike; "
             "the sign glyph gives the side",
             f"The {k.PCT_BOUND} % bound is the story's seed (11:1914); the {k.DELTA_BOUND} BTC bound is a board "
             f"placeholder, \"{k.ui('example', 'the placeholder bound label (MEMO OQ-3)')}\", never a recommendation"]
    if not shade:
        lines.insert(0, "The same bars with the shade removed: each breached cell stays distinguishable by its word "
                        "and its glyph slot alone (AC 3; R2 forced colours: word and glyph, no fill)")
    return ui.chart(fid, p), k.frame_block(fid, lines)


def symbol_set() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-thresholds-symbol-set"
    bars = k.window(16, k.SYM2)
    hits = [b for b in bars if k.breached("Delta %", b, k.SYM2) and not b.forming]
    b = hits[0]
    acc = k.W("W-4", label="Delta %", value=k.value("Delta %", b), side=k.side("Delta %", b),
              bound=f"{k.SET2_PCT} %")
    p = ui.P(sym=k.SYM2, set_wid="W-2", markers=[ui.acc_name(f"accessible text · Delta % {b.t}", acc)])
    k.decide(f"W-2 names {k.SYM2}, so this frame charts the second synthetic series ({k.SYM2}, seed {k.SEED + 1}); "
             f"its set's Delta % bound {k.SET2_PCT} % is a placeholder labelled example (MEMO OQ-3)")
    return ui.chart(fid, p), k.frame_block(fid, [
        "The header cell names the active set: W-2 for a symbol with its own set (11:1918); a symbol with no set "
        "falls back to the default (E20.json:420)",
        f"{k.SYM2}'s set (kit example): Delta % abs > {k.SET2_PCT} % — {len(hits)} closed bar(s) breach in view",
        "With thresholds off every value renders neutral (11:1921)"])


if __name__ == "__main__":
    ui.run(NN, [breached("SCR-030/strip-ThresholdsBreached", True),
                breached("SCR-030/strip-ThresholdsBreached-greyscale", False), symbol_set()], 2)
