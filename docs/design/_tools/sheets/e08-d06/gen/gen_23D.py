"""Board 23D: SCR-103/states-matrix (§15; §6 States × bands, every row incl. the two T2 rows). Dark only (no twin).
Run: python3 -I -B gen/gen_23D.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c_helpers as c  # noqa: E402

k = c.k
KEY = "23D"


def build(theme: str = "dark") -> tuple[list[k.Node], k.Node]:
    fr = k.frames_of(KEY)[0]
    inner = fr.w - 2 * k.PX[k.INSET_LG]
    title = "States × bands"
    tl = k.L("## 6. States × bands")
    tbl, th = c.matrix(inner, density=fr.density)
    heading = k.text("title", title, k.HEADING_SM, k.TEXT_1, w=inner)
    frame = k.free_frame(fr, theme, [heading, tbl], o={"dir": "column", "align": "start", "gap": k.STACK_MD,
                                                       "pad": k.INSET_LG})
    used = 2 * k.PX[k.INSET_LG] + k.text_h(k.HEADING_SM) + k.PX[k.STACK_MD] + th
    if used > fr.h:
        raise ValueError(f"matrix needs {used:.0f} px of the {fr.h} px frame")
    head, rows, ex = c.matrix_rows()
    hl = k.L("| State (trigger)")
    others = {s for kk in k.PROPOSED_TEN if kk != KEY for f in k.frames_of(kk) for s in f.states}
    only_here = [s for s in k.STATES if s not in others]
    t2 = [f"L{k.STATES[s]}" for s in c.T2_ROWS]
    lines = [
        f"Title \"{title}\" (L{tl}, §6's heading); columns: {' | '.join(head)} (L{hl}; the first drawn \"State\", "
        f"the triggers stay in the spec's column)",
        f"Every cell is verbatim from its row's §6 line above; {len(ex)} are shortened excerpts and the full cell in "
        f"the spec binds: " + ", ".join(f"L{ln} c{j}" for ln, j, _a, _b in ex),
        f"The two T2 rows ({', '.join(t2)}) sit on color.surface.sunken; their words carry the state (§8 sentence "
        f"form: \"{k.T2_OWNER_ONLY}\" L{k.L(k.T2_OWNER_ONLY)}, \"{k.T2_VIEW_AS}\" L{k.L(k.T2_VIEW_AS)})",
        f"Drawn only on this board under the cap: {', '.join(only_here)}",
        f"Table {inner} × {th:.0f} px (estimated) in the {fr.w} × {fr.h} frame; state column {c.MATRIX_STATE_W} px, "
        f"four {(inner - c.MATRIX_STATE_W) // 4} px columns; every cell padded 8 px a side (space.inset.sm)",
    ]
    blk = k.frame_block(fr, lines=lines)
    ann = k.annotations(KEY, [blk, *[k.marker_block(m) for m in k.R2_BOARDS[23]["markers"]]], board_lines=[c.R2_CREDIT])
    k.deviate(f"§6's first column header \"State (trigger)\" (L{hl}) is drawn \"State\"; the triggers are not drawn "
              f"(they stay binding in the spec)")
    for ln, j, a, b in ex:
        k.copy_gap(f"L{ln} column {j} ({head[j]}): a verbatim excerpt of {a} of the cell's {b} characters "
                   f"(r2's cell); the full cell binds")
    k.live(f"table: read back its height (estimated {th:.0f} px) and that the last row (Demo / live) ends at or above "
           f"y {fr.h - k.PX[k.INSET_LG]} inside the frame; no cell text is clipped (each row's h >= its tallest "
           f"cell's text + 8)")
    k.live("the two T2 rows read back fill color.surface.sunken; every other body row has no fill")
    k.live(c.CVD_LIVE)
    k.NOTES.add("sources", c.R2_CREDIT)
    return [frame], ann


def main() -> None:
    frames, ann = build()
    p = k.write_sheet(KEY, frames, ann)
    md = k.write_md(KEY, p, frames_info=["one table: a header row and the 23 §6 rows (r2 `matrix`)"])
    c.finish(KEY, p, md)


if __name__ == "__main__":
    main()
