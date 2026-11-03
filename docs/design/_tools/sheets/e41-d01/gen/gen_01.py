"""Board 01 research-board: the `17` §1.6 journey (predicted scores, designer judgement), the F → WD map with the
board each WD is drawn on, and the three persona walkthroughs with the research questions — all `(heuristic)`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 1
FW = 1440
IW = FW - 2 * k.FRAME_PAD


def score_cells(n: int) -> k.Node:
    return k.hbox("score", [k.rect(f"cell {i + 1}", 12, 12, k.TEXT_2 if i < n else None,
                                   {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR}) for i in range(5)] +
                  [k.text("words", f"{n} / 5 (DJ)", k.CAPTION, k.TEXT_1)], {"gap": k.INSET_XS}, h=16)


def journey(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cw = (IW - 5 * 12) // len(k.JOURNEY)
    cols = []
    for sec, steps in k.JOURNEY:
        cards = [k.vbox(f"step · {i + 1}", [k.text("step", st, k.BODY, k.TEXT_1, w=cw - 16), score_cells(sc),
                                            k.text("who", who, k.CAPTION, k.TEXT_2)],
                        {"pad": k.INSET_SM, "gap": k.STACK_XS, "fill": k.RAISED, "radius": k.R_CARD,
                         "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=cw)
                 for i, (st, sc, who) in enumerate(steps)]
        cols.append(k.vbox(f"section · {sec}", [k.text("title", sec, k.HEADING_SM, k.TEXT_1), *cards],
                           {"gap": k.STACK_SM}, w=cw))
    cols_w = [k.Col("step", "step", 168), k.Col("why", "why a trader abandons", 360),
              k.Col("show", "what the screen must show", 440), k.Col("basis", "basis", 120)]
    ab = k.grid_table("abandonment points (`17` §1.6)", cols_w,
                      [dict(zip(("step", "why", "show", "basis"), c)) for _i, c in k.ABANDON], row_h=24,
                      cap="Abandonment points (WD ids as in the memo §6)")
    k.derive(f"journey: `17` L{k.JOURNEY_LINE} — {sum(len(s) for _x, s in k.JOURNEY)} steps in {len(k.JOURNEY)} "
             "sections, scores verbatim; abandonment rows verbatim")
    return (k.frame(fid, [k.text("title", k.JOURNEY_TITLE, k.HEADING_MD, k.TEXT_1),
                          k.hbox("journey", cols, {"gap": k.INSET_MD, "align": "start"}, w=IW), ab], FW,
                    "Research — `17` §1.6 review journey: predicted scores (designer judgement, not measurements; "
                    "the owner's sessions replace them)"),
            k.frame_block(fid, ["Scores are DJ; Trigger's 2 rests on H1 (untested)", "Owner and Manager share each "
                                "score (`17` §1.6)"]))


def board_of(frame: str) -> str:
    hits = [nn for nn, b in k.BOARDS.items() if any(f.split(" · ")[0] == frame for f in b.frames)]
    return f"board {hits[0]:02d}" if hits else "not drawn"


def f_to_wd(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    fcols = [k.Col("f", "F", 48), k.Col("finding", "finding (heuristic)", 520), k.Col("h", "heuristic", 88),
             k.Col("sev", "severity", 80), k.Col("wd", "→ WD", 136)]
    frows = [{"f": f, "finding": a, "h": b, "sev": c, "wd": d} for f, (a, b, c, d, _i) in k.FINDINGS.items()]
    wcols = [k.Col("wd", "WD", 64), k.Col("dec", "decision (PROPOSED)", 560), k.Col("frame", "frame", 232),
             k.Col("board", "drawn on", 96), k.Col("owner", "owner ticket", 216)]
    wrows = [{"wd": w.wid, "dec": w.decision, "frame": w.frame, "board": board_of(w.frame), "owner": w.owner}
             for w in k.WDS.values()]
    k.derive("drawn on: each WD's §6 frame looked up in the board plan (" +
             ", ".join(f"{w.wid} {board_of(w.frame)}" for w in k.WDS.values()) + ")")
    return (k.frame(fid, [k.grid_table("findings (memo §5)", fcols, frows, row_h=24, cap="Findings F-1..F-8 (memo §5), "
                                                                                       "each (heuristic)"),
                          k.grid_table("decisions (memo §6)", wcols, wrows, row_h=24,
                                       cap="Wireframe decisions WD-1..WD-14 (memo §6) and where each is drawn")],
                    FW, "Research — the F → WD map: every finding feeds at least one decision; every decision names "
                        "its frame and the board that draws it"),
            k.frame_block(fid, ["Rows verbatim from memo §5 / §6; the 'drawn on' column is the kit's board plan"]))


def walkthroughs(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cw = (IW - 2 * 16) // 3
    cards = [k.vbox(f"walkthrough · {i + 1}", [k.text("words", k.plain(txt), k.BODY, k.TEXT_1, w=cw - 24)],
                    {"pad": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD, "stroke": k.BORDER,
                     "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=cw) for i, (_ln, txt) in enumerate(k.WALKS)]
    rq = [(k.plain(c[0]), k.plain(c[1]), k.plain(c[2])) for _i, c in k.table("## 2. Research questions")]
    rcols = [k.Col("rq", "RQ", 56), k.Col("q", "question (ticket)", 320), k.Col("h", "hypothesis (untested)", 760)]
    return (k.frame(fid, [k.text("title", "Persona walkthroughs (heuristic) — memo §4", k.HEADING_MD, k.TEXT_1),
                          k.hbox("cards", cards, {"gap": k.INSET_LG, "align": "start"}, w=IW),
                          k.grid_table("research questions (memo §2)", rcols,
                                       [{"rq": a, "q": b, "h": c} for a, b, c in rq], row_h=24,
                                       cap="Research questions and pre-registered hypotheses (all untested)")], FW,
                    "Research — persona walkthroughs P1, P2b, P3 and the research questions; no session was run, no "
                    "participant, timing or quote exists"),
            k.frame_block(fid, ["Walkthrough text verbatim from memo §4 (markdown emphasis dropped)"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((journey, f_to_wd, walkthroughs), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 1)
