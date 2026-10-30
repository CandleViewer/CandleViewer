"""Board 05 separator-rows (dark): every separator row of §7.1 and the rebuild / cache-loading captions (§7.3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair5_helpers as h  # noqa: E402

k = h.k
NN = 5


def build(nn: int = NN) -> Path:
    fids = k.BOARDS[nn].frames
    builders = (h.frame_non_time, h.frame_time_axis, h.frame_captions)
    frames, blocks = [], []
    for fid, fn in zip(fids, builders):
        fr, blk = fn(fid)
        frames.append(fr)
        blocks.append(blk)
    lines = list(h.BOARD_LINES)
    if k.BOARDS[nn].twin:
        lines.append(f"Same construction, tokens and data as board {k.BOARDS[nn].twin:02d}'s first two frames; "
                     f"the light token set is applied at export")
    lines.append("Tokens (all frames): " + ", ".join(sorted(h.TOKENS)))
    ann = k.annotations(nn, blocks, board_lines=lines)
    path = k.write_sheet(nn, frames, ann, notes=h.NOTES_05)
    info = [f"{f["name"]}: {f["w"]} x {f["h"]}" for f in frames]
    info += h.CAPTIONS
    info.append("sources: spec §7.1 L234–242 (nine kinds), L244 (order where two meet), §7.2 L248, §7.3 L250–253, "
                "§7.4 L255, §13 W-1…W-12, W-18; E11-D04 §10 L325–326 (bands); hand-off §H, §E")
    k.write_md(nn, path, frames_info=info)
    k.pack_sheet(path)
    return path


if __name__ == "__main__":
    print(build())
