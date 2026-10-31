"""Board 1D: the redline (BTCUSDT, Owner, recorded, compact, dark). k.board1() + the strings block + the r2 credit."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a_helpers import R2_CREDIT, emit, k, strings_block  # noqa: E402

GLYPH_NOTE = "(§10.3 L{}: state glyphs are text characters)"


def build(theme: str = "dark") -> tuple[list, dict]:
    key = "1D" if theme == "dark" else "1L"
    k.NOTES.reset()
    frames, ann0 = k.board1(theme)
    fr = k.frames_of(key)[0]
    blk = k.frame_block(fr, lines=["24 h high / low: 'not available yet' (CR-11; §4.2), not the snapshot's values "
                                   "(board 18 draws them after CR-11)"])
    lv = k.live_values()
    extra = {v: f"derived (§5 formatters on the recorded fixtures; {nm})" for nm, v in lv.items()
             if not k.cite(v)}
    ann = k.annotations(key, [blk, strings_block(frames, extra),
                              *[k.marker_block(m) for m in k.R2_BOARDS[1]["markers"]]], board_lines=[R2_CREDIT])
    return frames, ann


if __name__ == "__main__":
    f, a = build("dark")
    emit("1D", f, a, notes={"live_checks": ["board 1D: the drawer's body ends at the footer rule; the last band "
                                            "(Recording in CandleViewer) is not cut"]})
