"""Board 10 separator-rows-light: the light twin of board 05's first two frames (same builders, light fids)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair5_helpers as h  # noqa: E402

k = h.k
NN = 10


def build() -> Path:
    if k.LIGHT_TWINS.get(NN) != 5:
        raise ValueError("board 10 must be the light twin of 05")
    fids = k.BOARDS[NN].frames
    frames, blocks = [], []
    for fid, fn in zip(fids, (h.frame_non_time, h.frame_time_axis)):
        fr, blk = fn(fid)
        frames.append(fr)
        blocks.append(blk)
    lines = list(h.BOARD_LINES) + ["Same construction, tokens and data as board 05's separators∕non-time and "
                                   "separators∕time-axis frames; the light token set is applied at export"]
    lines.append("Tokens (all frames): " + ", ".join(sorted(h.TOKENS)))
    ann = k.annotations(NN, blocks, board_lines=lines)
    notes = {kd: [ln for ln in v if "captions" not in ln and "W-8" not in ln] for kd, v in h.NOTES_05.items()}
    path = k.write_sheet(NN, frames, ann, notes=notes)
    info = [f"{f["name"]}: {f["w"]} x {f["h"]}" for f in frames]
    info += h.CAPTIONS
    info.append("sources: as board 05 (spec §7.1 L234–242, L244, §7.2 L248, §7.4 L255, §13; E11-D04 §10 L325); "
                "theme light (light twin of 05, §0)")
    k.write_md(NN, path, frames_info=info)
    k.pack_sheet(path)
    return path


if __name__ == "__main__":
    print(build())
