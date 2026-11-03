"""Board 04 derived-level-ladder: memo §5 — the ten levels with their label, non-colour cue, rank and prominence — and
the same cues in situ on a greyscale profile of the synthetic developing session (every row the same fill, so no
level is carried by fill: PD-2, PD-3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 4
N_SHOWN = 1  # kit choice: the nearest N naked POCs drawn (memo §5 "the nearest N + "N hidden""; N unset)
GLYPH = {"POC": "rail", "VAH": None, "VAL": None, "Value-area shading": "bracket", "HVN": "HVN", "LVN": "LVN",
         "Naked POC": "ray", "Single prints": "single", "Developing state": "bracket", "Initial balance": "IB"}


def cue(level: str) -> list[k.Node]:
    g = GLYPH[level]
    if g is None:
        return [k.rect("glyph · tick", 6, 2, k.TEXT_1), k.rect("glyph · bracket end", 2, 12, k.TEXT_1)]
    return [rb.glyph(g)]


def ladder(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hd = k.table_head("## 5. Derived levels")
    rows = [{"lvl": c[0], "lab": c[1], "cue": c[2], "draw": cue(c[0]), "rank": c[3], "prom": c[4], "f": c[5]}
            for _i, c in k.LEVELS]
    t = rb.table("levels", [("lvl", hd[0], 136), ("lab", hd[1], 272), ("cue", hd[2], 392), ("draw", "cue (drawn)", 88),
                            ("rank", hd[3], 96), ("prom", hd[4], 232), ("f", hd[5], 176)], rows,
                 cap=f"memo §5 L{k.LEVELS_LINE}: ten levels, verbatim; 'cue (drawn)' is the kit's greyscale stand-in")
    rank = k.sentence_after("**The labelled-vs-implied ranking (the ticket's deliverable):**")
    cls = k.LINES["spec"][k.L("The non-colour cue column states a constraint class") - 1].strip()
    key = k.LINES["spec"][k.LEVELS_LINE + 1].replace("**", "").strip().replace(" :", ":")
    k.fallback("glyph")
    return (k.frame(fid, [rb.card("rank key", [rb.para("words", key, rb.IW - 24)], rb.IW), t,
                          rb.card("ranking", [k.text("label", "The labelled-vs-implied ranking (the ticket's "
                                                                "deliverable)", k.LABEL, k.TEXT_2),
                                              rb.para("words", rank, rb.IW - 24, k.BODY_STRONG),
                                              rb.para("class", cls, rb.IW - 24, k.CAPTION, k.TEXT_2)], rb.IW,
                                  strong=True)], rb.FW,
                    "Research — every level's word, non-colour cue and rank; no cue uses fill colour alone or a "
                    "dashed, hollow or hatched mark (reserved, F-3)"),
            k.frame_block(fid, [k.f_line("F-11"), k.f_line("F-12"), k.f_line("F-21"),
                                f"A-7: {k.AMEND['A-7'][2]}"], ["PD-2"]))


def in_situ(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pr = k.DEVELOPING
    naked = sorted([(abs(p - pr.price(pr.poc)), d, p) for d, p, t in k.naked_pocs() if not t])
    shown, hidden_n = naked[:N_SHOWN], len(naked) - N_SHOWN
    pane = rb.profile_pane(pr, row_px=10, tpo=True, nodes_on=True, npocs=[(k.day_word(d), p) for _x, d, p in shown])
    hvn, lvn = k.nodes(pr)
    ib_lo, ib_hi = rb.ib_range(pr)
    pw = pane["w"] + 32
    words = k.developing_words(pr)
    head = [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[0]),
            k.text("state", words, k.LABEL, k.TEXT_1)]
    leg = rb.legend([(k.memo("Value area 70 %"), rb.glyph("bracket")), ("HVN", rb.glyph("HVN")),
                     ("LVN", rb.glyph("LVN")), (k.memo("Single prints"), rb.glyph("single")),
                     (f"IB {k.fmt_price(ib_lo)}–{k.fmt_price(ib_hi)}", rb.glyph("IB")),
                     (k.memo_tpl("N hidden", N=str(hidden_n)), rb.glyph("ray")), (words, None),
                     (k.ui(f"Row size {k.ROW_TICKS} ticks"), None)], pw - 16)
    k.memo("\"IB\" + its range")
    k.memo("\"nPOC\" + the session date at the ray's end")
    p = rb.panel(head, [k.hbox("pane row", [pane], {"padX": k.INSET_LG}, w=pw, h=pane["h"]),
                        k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw)
    mirror = rb.hidden("DOM mirror words (E18-D02 :307–308, via memo §5)", " · ".join(
        k.memo(w_) for w_ in ("point of control", "value area high", "value area low", "high-volume node",
                              "low-volume node")), 360)
    k.derive(f"{pr.label} as of {k.hhmm(pr.as_of)} UTC: {len(pr.rows)} rows of {k.ROW_TICKS} ticks, POC "
             f"{k.row_price(pr, pr.poc)}, VA {k.row_price(pr, pr.va[0])}–{k.row_price(pr, pr.va[1])}, HVN "
             f"{k.row_price(pr, hvn)}, LVN {k.row_price(pr, lvn)}, single prints "
             f"{', '.join(k.row_price(pr, r) for r in k.single_prints(pr))}, IB {k.fmt_price(ib_lo)}–"
             f"{k.fmt_price(ib_hi)} (periods 00:00–01:00 UTC), TPO max {max(pr.tpo.values())} periods")
    k.derive("naked POCs: " + ", ".join(f"{k.day_word(d)} {k.fmt_price(p_)} (untested through "
                                        f"{k.hhmm(k.NOW)} UTC)" for _x, d, p_ in naked) +
             f"; the nearest {N_SHOWN} drawn, {hidden_n} hidden")
    return (k.frame(fid, [k.hbox("panel and mirror", [p, mirror], {"gap": k.INSET_LG, "align": "start"},
                                 w=pw + 16 + 360)], pw + 16 + 360 + 2 * k.FRAME_PAD,
                    "Research — the cues in situ, greyscale: every row the same fill; POC rails, VAH / VAL ticks, "
                    "the value-area bracket (open: developing), HVN / LVN glyphs, the nPOC ray, the IB bar and "
                    "single-print bars in the TPO margin"),
            k.frame_block(fid, [k.f_line("F-13"), "Glyph shapes are kit stand-ins: E19-D03 chooses (memo §5)",
                                "HVN / LVN by a kit illustration rule (3-row smoothed local extremes), not a "
                                "definition; IB = the first two TPO periods (kit choice)"], ["PD-3"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((ladder, in_situ), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
