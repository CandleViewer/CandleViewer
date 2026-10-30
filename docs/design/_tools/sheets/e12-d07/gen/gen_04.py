"""Board 04 `E12-D07 / 04 row-states` (dark): states/all-words + states/stale-caption. Run: python3 -I gen_04.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair4_helpers as h  # noqa: E402

k = h.k
NN = 4


def build(nn: int = NN) -> list[Path]:
    b = k.BOARDS[nn]
    fids = list(b.frames)
    frames, blocks = [], []
    f1, blk1, _ = h.all_words_frame(fids[0])
    frames.append(f1)
    blocks.append(blk1)
    if len(fids) > 1:
        f2, blk2, _ = h.stale_caption_frame(fids[1])
        frames.append(f2)
        blocks.append(blk2)
    twin = f"light twin of board {b.twin:02d}: same construction, same data, the theme switched at export" if b.twin \
        else "light twin: board 09 (states/all-words · light)"
    ann = k.annotations(nn, blocks, board_lines=[
        f"§0 L{k.BOARDS[4].line} (board 04 draws): every §6 word once, the closed row unmarked (`—`), the stale caption clause (§6.2)",
        twin, "Owner walkthrough (hand-off §E): every `state` word appears once; a closed bar is unmarked"])
    lc = [f"read back the focused row's ring on {k.frame_name(fids[0])}: row 06 (13:29, Est.·POC) stroke 2 px "
          "color.focus.ring, inner",
          f"read back the `state` cell texts on {k.frame_name(fids[0])} top to bottom: —, POC, —, Est., —, Est.·POC, —, "
          "width capped, —, no range, —, —, —, stale, —, —, —, corrected, forming (19 rows)",
          f"measure the `state` column on {k.frame_name(fids[0])}: 95 px (12 characters, Equi-volume, §5)"]
    if len(fids) > 1:
        lc += [f"read back the caption's last clause on {k.frame_name(fids[1])}: \"values as of 13:42:05\"",
               f"read back the status-row chip on {k.frame_name(fids[1])}: \"Stale 7s · last 13:42:05\" with the "
               "warning glyph",
               f"on {k.frame_name(fids[1])}: every closed row's `state` reads stale and its values bind "
               "color.text.secondary; the last row reads forming"]
    notes = {"live_checks": lc, "spec_gaps": h.SPEC_GAPS,
             "sources": ["E12-D07 §6 L197-210 (the words and name additions), §6.2 L218-220, §5 (equi-volume state "
                         "width), §0 L58; E11-D04 :183 (Est.·POC), :254 (forming describedby), :264 (values as of), "
                         ":59 (stale chip)"]}
    sheet = k.write_sheet(nn, frames, ann, notes=notes)
    info = [f"{k.frame_name(f)}: 1280 x 800 window, one chart panel, table open in place (time 1m, 13:24-13:42, 19 rows)"
            for f in fids]
    md = k.write_md(nn, sheet, frames_info=info)
    packed = k.pack_sheet(sheet)
    return [sheet, md, packed]


if __name__ == "__main__":
    for p in build():
        print(p)
