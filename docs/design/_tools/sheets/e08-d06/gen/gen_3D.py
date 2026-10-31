"""Board 3D: Stale, T1 (left, d03a) and Stale, T2 (right, d03b, the CMP-078 strip), BTCUSDT, Owner, compact (AC 2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a_helpers import R2_CREDIT, emit, k, strings_block  # noqa: E402

KEY = "3D"
T2_H = 1341  # the measured cut: T2 body 1181 + sticky header 103 + sticky footer 57


def build(theme: str = "dark") -> tuple[list, dict]:
    key = f"3{'D' if theme == 'dark' else 'L'}"
    k.NOTES.reset()
    fr = k.frames_of(key)[0]
    left = k.drawer("d03a", density=fr.density, h=fr.h, name="CMP-046 drawer · Stale, T1")
    # live-check fold (2026-10-31): the T2 body is cut at the line boundary above "link · Recorder settings" (body
    # 1181, the sticky footer under it, so the drawer is 1341 and ends 19 px above T1's inside the 1360 frame)
    right = k.drawer("d03b", density=fr.density, h=T2_H, name="CMP-046 drawer · Stale, T2")
    gap = k.PX[k.STACK_LG]
    pad = (fr.w - 2 * k.DRAWER_W - gap) // 2  # 12 px a side: two 480 drawers + the 16 px gap in 1000
    frame = k.free_frame(fr, theme, [left, right], {"dir": "row", "align": "start", "gap": k.STACK_LG,
                                                    "padX": k.INSET_MD})
    k.derived(f"frame 3: two {k.DRAWER_W} px drawers, gap {gap} (space.stack.lg), {pad} px a side "
              f"(space.inset.md) = {fr.w}; each drawer {fr.h} tall")
    lv = k.live_values()
    k.derived(f"stale values kept (never live-updating): last {lv['last']}, index {lv['index']}, {lv['updated']}")
    blk = k.frame_block(fr, lines=[
        "Left drawer: Stale, T1 (CMP-239 chip in the Live market header; band on the stale surface)",
        "Right drawer: Stale, T2 (as T1 plus the CMP-078 escalated strip under the as-of line)",
        f"Contract rules band identical in both, no stale treatment (L{k.L('The contract band never takes a stale')})"])
    extra = {"Stale 15s": f"(not verbatim: the CMP-239 chip of L{k.cite('Stale 7s')[1:]} "
                          f"at the T2 age of L{k.L('| **Stale, T2**')}, 15 s; the strip keeps L"
                          f"{k.cite('Stale 15 s — new orders blocked on BTCUSDT')[1:]}'s \"Stale 15 s\")"}
    k.deviate("board 3 right drawer (T2): the body scrolls (§6 Stale, T2) and is cut at the line boundary above the "
              "link row, so \"Recorder settings\" (L" + k.cite("Recorder settings")[1:] + ") sits wholly below the cut, "
              "hidden, not clipped; the T1 drawer shows it whole")
    k.deviate("board 3 right drawer: CMP-239 reads \"Stale 15s\" (the T2 age in L" + k.cite("Stale 7s")[1:]
              + "'s \"Stale 7s\" form); the spec gives no T2 chip text")
    ann = k.annotations(key, [blk, strings_block([frame], extra),
                              *[k.marker_block(m) for m in k.R2_BOARDS[3]["markers"]]], board_lines=[R2_CREDIT])
    return [frame], ann


if __name__ == "__main__":
    f, a = build("dark")
    emit(KEY, f, a, notes={"live_checks": [
        "board 3D: drawers 480 x 1360 (T1) and 480 x 1341 (T2) at x 12 and 508 inside the frame; neither spills the "
        "1000 px frame",
        "board 3D right drawer: the strip sits under 'Last update 06:35:46 UTC'; the T2 body (1181) ends at the top "
        "of the link row, 'Retention (owner)' is the last whole line, the sticky footer follows the body",
        "board 3D right drawer: a 1 px body shift needs a re-check (the cut sits on a line boundary)"]})
