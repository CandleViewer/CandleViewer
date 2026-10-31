"""Board 10D: SCR-103/load-error-catalogue-owner (AC 4; 404 and 403 strips). r2's d10a-d10c stacked in 480 x 760."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from b_helpers import R2_CREDIT, cl, k, run  # noqa: E402


def build(theme: str = "dark"):
    key = f"10{'D' if theme == 'dark' else 'L'}"
    fr = k.frames_of(key)[0]
    stack = [k.drawer(d, name=f"CMP-046 drawer · {tag}") for d, tag in
             (("d10a", "A contract load failed"), ("d10b", "B not in the instrument list"), ("d10c", "C forbidden"))]
    need = sum(k.est_height(s) for s in stack) + 2 * k.PX[k.STACK_SM]
    frame = k.free_frame(fr, theme, stack, {"dir": "column", "align": "start", "gap": k.STACK_SM},
                         note="three hugging drawers (h=None strips), top to bottom: A 5xx/unreachable, B 404, C 403")
    k.live(f"frame 10: the three stacked drawers need about {need:.0f} px of the {fr.h} px frame; read back that C's "
           f"bottom edge sits inside the frame (clip on, nothing cut)")
    k.live("A: the CMP-027 block's Retry is the primary button; B: Search symbols then Retry; C: no button")
    k.derived("no numbers on this board: the three strips carry the spec's sentences only (§6 rows, §8 T4)")
    a_lines = ["Couldn't load BTCUSDT's contract rules.", "CandleViewer can't reach its server.",
               "CandleViewer can't check BTCUSDT orders against these rules until they load."]
    blk = k.frame_block(fr, lines=[
        "Top to bottom: A Contract load failed (danger, CMP-027), B Not in the instrument list, C Forbidden "
        "(plain, sentence only)",
        *[f"A: {cl(s)}" for s in a_lines],
        f"A: {cl('Ref urn:cv:req:…')} only when the problem carries instance",
        "B: " + cl("BTCUSDT isn't in Bybit's instrument list as CandleViewer last read it."),
        f"B: buttons {cl('Search symbols')} and Retry",
        "C: " + cl("Your role can't see instruments."),
        f"Band title {cl('Contract rules')}, tag {cl('Set by Bybit')}",
    ])
    ann = k.annotations(key, [blk, *[k.marker_block(m) for m in k.R2_BOARDS[10]["markers"]]], board_lines=[R2_CREDIT])
    return [frame], ann


if __name__ == "__main__":
    th = sys.argv[1] if len(sys.argv) > 1 else "dark"
    frames, ann = build(th)
    run(f"10{'D' if th == 'dark' else 'L'}", frames, ann,
        frames_info=["Stacked: A (top), B, C; each a hugging CMP-046 drawer, no footer actions (r2 actions [])"])
