"""Board 08 `E47-D07 / 08 verbosity-matrix` (dark): §6.4 — announce × verbosity × Reduce announcements, what each cell
reads, with the fast script's replay counts re-derived by the tool in every cell."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 8
PAD = 24
WIDTHS = (230, 110, 100, 330, 150, 160)
BAR_PX = 4  # annotation bar: px per field read


def build_frame(fid: str) -> tuple[dict, dict]:
    if len(k.MATRIX_HEAD) != len(WIDTHS):
        raise SystemExit("board 08: §6.4's columns changed")
    hdr = k.hbox("header row", [k.hbox(f"h · {i}", [k.text("t", c, k.LABEL, k.TEXT_2, w=wd - 16)],
                                       {"padX": k.INSET_SM, "padY": k.INSET_XS}, w=wd)
                                for i, (c, wd) in enumerate(zip(k.MATRIX_HEAD, WIDTHS), 1)],
                  {"fill": k.RAISED, "align": "start"}, w=sum(WIDTHS))
    rows, ass_sets = [hdr], {}
    for i, m in enumerate(k.MATRIX, 1):
        n = k.field_reads("fast", m["cell"])
        if str(n) != m["reads"]:
            raise SystemExit(f"board 08: the replay of {m['cell']} gives {n}, §6.4 says {m['reads']}")
        r = k.replay("fast", **k.AUD.CELLS[m["cell"]])
        ass_sets[m["cell"]] = [(x.t, x.text) for x in r.lines if x.channel != "polite"]
        vals = [m["setting"], m["assertive"], m["status"], m["fields"], m["whale"]]
        cells = [k.hbox(f"c · {j}", [k.text("t", v, k.BODY if j == 1 else k.CAPTION, k.TEXT_1 if v != "—" else
                                            k.TEXT_3, w=wd - 16)], {"padX": k.INSET_SM, "padY": k.INSET_XS}, w=wd)
                 for j, (v, wd) in enumerate(zip(vals, WIDTHS), 1)]
        bar = [k.rect("bar", max(2, n * BAR_PX), 10, k.MARK_FILL)] if n else []
        cells.append(k.hbox("c · 6", [k.text("t", str(n), k.NUM, k.TEXT_1), *bar], {"padX": k.INSET_SM, "gap":
                                                                                     k.INSET_SM}, w=WIDTHS[5], h=28))
        rows.append(k.hbox(f"row {i}", cells, {"align": "start", **({"fill": k.SELECTED} if i % 2 == 0 else {})},
                           w=sum(WIDTHS), note=f"§6.4 L{m['line']}; cell {m['cell']}"))
    first = next(iter(ass_sets.values()))
    if any(v != first for v in ass_sets.values()):
        raise SystemExit("board 08: the assertive lines differ between cells")
    table = k.vbox("CMP-049 table · §6.4", rows, None, w=sum(WIDTHS), x=PAD, y=72,
                   note=f"the bar is annotation: {BAR_PX} px per field read")
    th = round(k.est_height(table))
    ass = k.vbox("assertive in every cell", [
        k.text("h", f"The assertive writes, identical in all {len(ass_sets)} cells (T AC2):", k.LABEL, k.TEXT_1),
        *[k.text(f"line {j}", f"{k.secs(t)} s  {s}", k.CAPTION, k.TEXT_1) for j, (t, s) in enumerate(first, 1)]],
        {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=sum(WIDTHS), x=PAD,
        y=72 + th + 24)
    kids = [k.heading("h", f"What each setting reads (§6.4 L{k.MATRIX_LINE}), the fast script (§10.2) re-run per cell",
                      PAD, PAD, 1000), table, ass,
            k.tag(f"flush composite at {k.val('SIM', 'fast.flush-at')} s counted apart (after the stream's minute)",
                  PAD, 72 + th + 24 + round(k.est_height(ass)) + 16), k.synthetic_tag(PAD, k.FRAME_H - 28)]
    return k.specimen(fid, kids), dict(first=first)


def main() -> None:
    b = k.BOARDS[NN]
    fr, f = build_frame(b.frames[0])
    blocks = [(b.frames[0], [
        f"§6.4 L{k.MATRIX_LINE}: shouldAnnounce gates ambient reads only; assertive and status rows are never gated "
        "(MODEL:87–95)",
        "The shipped default is significant, which reads a field only when its caller flags it, and no caller does "
        "today (PW:103): T AC3 is measured under Always (D07-C6)",
        "Normal and High read the same until the owner splits them (D05:391; MODEL:93; BQ-7, D07-C9); whale prints are "
        "opt-in through the panel's Whale prints class",
        f"The last column is the tool's replay of the fast script in each cell, counted over the stream's minute (the "
        f"steady state, {k.val('SIM', 'fast.composites')} composites under Always · Normal); every count equals the "
        "spec's figure",
        "Off, significant and Low read no prices; the tape is never read (T-35, BQ-7)"])]
    p, md, pk = k.build(NN, [fr], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
