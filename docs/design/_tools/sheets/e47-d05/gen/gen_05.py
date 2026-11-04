"""Board 05 `E47-D05 / 05 motion-table-tiles` (dark): §6.1, §6.4 — the motion tile full (looping, Pause visible) and
reduced (still Before / After frames), and the table-alternative tile."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, view_window  # noqa: E402

NN = 5


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    pss = [k.PS(motion_running=True, focus="tile:Motion", sections=("Motion", "Contrast and focus")),
           k.PS(values=(("disable_canvas_animation", "true"),), sections=("Motion", "Contrast and focus")),
           k.PS(values=(("always_show_tables", "true"),), header=False, sections=("Data views", "Announcements"))]
    frames = [view_window(fid, ps, note=f"{fid}") for fid, ps in zip(b.frames, pss)]
    s6, s61, s64 = k.L("## 6. Preview tiles"), k.L("### 6.1 Motion"), k.L("### 6.4 Table alternative")
    c = k.WORLD.candles
    blocks = [
        (b.frames[0], [
            f"§6.1 L{s61}: effective motion full (OS no preference, canvas animation on): a heatmap column and a price "
            f"cell on a {k.LOOP_S}-second loop; the trail fades and the price flashes once per change (drawn at "
            f"t = {k.LOOP_S} s: {k.px_fmt(k.WORLD.price_at(k.Decimal(0)))} -> "
            f"{k.px_fmt(k.WORLD.price_at(k.Decimal(k.LOOP_S)))}, the flash in color.buy.subtle)",
            f"§6 L{s6 + 2}: the loop runs while focus or the pointer is in its group (§13.2); a visible Pause (2.2.2, "
            "`05`:217), one button whose label swaps Pause / Play, no aria-pressed; drawn focused (CMP-039 normal); a "
            "paused tile stays paused for the visit; never above three flashes a second (`05`:218)",
            "Structure (D05-A2): role=\"group\" named in words, the role=\"img\" preview inside, Pause outside the img",
            "Zero requestAnimationFrame while hidden, offscreen or in a background tab (BQ-5)"]),
        (b.frames[1], [
            f"§6.1 L{s61}: canvas animation disabled (the row's explicit choice): the loop stops and two still frames "
            f"sit side by side, \"{k.w('W-18', 0)}\" and \"{k.w('W-18', 1)}\" (W-18), no tween (R-6); the same holds "
            "under reduced motion (board 04, following-system)",
            "No Pause: nothing runs. A preview that animates while demonstrating reduced motion is a defect (T Tech)",
            "The row is modified (§10): \"Changed\" and its Reset; \"Reset this section\" under the group"]),
        (b.frames[2], [
            f"§6.4 L{s64}: always_show_tables on — the tile's candle chart flips to its CMP-049 table, the same rows, "
            f"no refetch (S07:24–25); {len(c)} seeded 1-minute candles, high {k.px_fmt(max(x.h for x in c))}, low "
            f"{k.px_fmt(min(x.l for x in c))} (each row's high >= open, close >= low)",
            "Under reduce the flip is instant; at 400 % the table sits in a named, focusable scroll region (\"Sample "
            "candle table\"), 1.4.10's data-table exception — 400 % is not drawn (§0)",
            "Cells padded 8 px a side; numbers end-aligned in type.num.sm",
            "The window is scrolled to Data views (the page top above it, as board 01)"]),
    ]
    for x in c:
        assert x.l <= min(x.o, x.c) and x.h >= max(x.o, x.c)
    k.ambiguity("Board 05 motion-reduced: §0 asks for the motion tile \"full / reduced\"; reduced is drawn through "
                "disable_canvas_animation (§6.1's second trigger), since board 04 already draws the OS-reduce route")
    p, md, pk = k.build(NN, frames, blocks, per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
