"""Board 07 `E47-D06 / 07 parity-oracle` (dark): §9 as a sheet — AC2's footprint bar traced from the canvas to the
mirror label, the table row and the oracle rows P-1 … P-5."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, sheet_table  # noqa: E402

NN = 7
FP_COLS = [k.Col("Price", 88), k.Col("Bid vol", 80), k.Col("Ask vol", 80), k.Col("Delta", 80),
           k.Col("Imbalance flag", 112, False), k.Col("Estimated badge", 160, False)]  # 600
if [c.name for c in FP_COLS] != k.COLS["footprint"]:
    raise SystemExit("gen_07: the drawn columns are not §6.2's footprint set")
F = k.FP_FOCUS


def fp_values(x: "k.FpLevel") -> list[str]:
    return [k.px_fmt(k.price(x.k)), k.q_fmt(x.bid), k.q_fmt(x.ask), k.signed(x.delta), x.flag,
            f"Estimated, {x.estimated}" if x.estimated else "—"]


def canvas() -> dict:
    k.fallback("plot")
    rows = []
    for x in k.FOOTPRINT:
        foc = x is F
        cells = [k.text("price", k.px_fmt(k.price(x.k)), k.NUM_SM, k.AXIS, w=64),
                 k.hbox("cell", [k.text("bid", k.q_fmt(x.bid), k.NUM_SM, k.FP_BID),
                                 k.text("x", "×", k.NUM_SM, k.TEXT_3),
                                 k.text("ask", k.q_fmt(x.ask), k.NUM_SM, k.FP_ASK)],
                        {"gap": k.INSET_XS, "padX": k.INSET_SM, "justify": "center",
                         **({"stroke": k.FP_IMB, "strokeWidth": k.THICK, "strokeAlign": "inner"} if foc else {})},
                        w=140, h=28, note="imbalance outline (canvas); the estimated hatch is not drawn: no hatch token yet "
                             "(spec §18)" if foc else None)]
        if foc:
            cells.append(k.hbox("CMP-227 marker", [k.text("word", "(estimated)", k.CAPTION, k.TEXT_1)],
                                {"padX": k.INSET_XS, "radius": k.R_BADGE, "stroke": k.TEXT_2, "strokeWidth": k.HAIR,
                                 "strokeAlign": "inner"}, h=18))
        rows.append(k.hbox(f"level {k.px_fmt(k.price(x.k))}", cells, {"gap": k.INSET_XS}, w=300, h=28))
    head = k.text("head", f"On the canvas: the {k.hhmm(k.CURSOR.minute)} footprint bar (CMP-182, role=\"img\")",
                  k.LABEL, k.TEXT_2, w=284)
    return k.vbox("canvas · footprint bar", [head, *rows], {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.SUNKEN},
                  w=300)


def mirror() -> dict:
    name = k.fp_name(F)
    parts = name.split(k.SLOT_JOIN)
    slots = ["unit", "values", "flags", "Estimated, display name"]
    kids = [k.text("head", "Mirror: the Enter detail's level node (aria-label)", k.LABEL, k.TEXT_2, w=284),
            k.text("name", f"\"{name}\"", k.BODY_STRONG, k.TEXT_1, w=284),
            *[k.text(f"slot {i}", f"{i}. {s}: {p}", k.CAPTION, k.TEXT_1, w=284)
              for i, (s, p) in enumerate(zip(slots, parts), 1)]]
    return k.vbox("mirror", kids, {"gap": k.STACK_SM, "pad": k.INSET_SM, "fill": k.RAISED}, w=300)


def table() -> dict:
    hdr = k.header_row(FP_COLS, sort="Price", direction="descending", filter_only=("Estimated badge",))
    rows = [k.data_row(i, FP_COLS, fp_values(x), focused=x is F,
                       colors={"Delta": k.BUY if x.delta > 0 else k.SELL if x.delta < 0 else k.TEXT_1})
            for i, x in enumerate(k.FOOTPRINT, 1)]
    head = k.text("head", f"Table: the level sub-table of bar {k.hhmm(k.CURSOR.minute)} (`05`'s set, D04E11:243–248)",
                  k.LABEL, k.TEXT_2, w=584)
    return k.vbox("table · footprint levels", [head, hdr, *rows], {"gap": k.STACK_XS, "pad": k.INSET_SM,
                                                                   "fill": k.CANVAS}, w=616)


def frame() -> dict:
    vals = {"P-1": k.q_fmt(F.bid), "P-2": k.q_fmt(F.ask), "P-3": k.signed(F.delta), "P-4": F.flag,
            "P-5": f"Estimated, {F.estimated}"}
    cols = [("P", 48), ("On the canvas", 200), ("Mirror field", 200), ("Table column", 152), ("Label slot", 176),
            ("Source", 200), ("Fixture value: mirror = table", 272)]  # 1248
    rows = [[p, o["canvas"], o["mirror"], o["column"], o["slot"], o["source"], f"{vals[p]} = {vals[p]}"]
            for p, o in k.ORACLE.items() if p in vals]
    title = k.text("title", f"The parity oracle, AC2's footprint bar (§9 L{k.L('## 9. The parity oracle')}): one "
                   "datum, one value, in the canvas, the mirror label, the table row and the oracle row",
                   k.HEADING_SM, k.TEXT_1, w=1248)
    trace = k.hbox("trace", [canvas(), mirror(), table()], {"gap": k.INSET_LG, "align": "start"}, w=1248, h=260)
    f = k.sheet_frame(k.BOARDS[NN].frames[0], [title, trace, sheet_table("oracle P-1 … P-5", cols, rows),
                                               k.text("foot", "QA-1 (hand-off §G): bid, ask, delta with + / −, the "
                                                      "flag word and \"Estimated, {display name}\" equal in the label "
                                                      "and the table; the other "
                                                      f"{len(k.ORACLE) - len(rows)} oracle rows are text (§9)",
                                                      k.CAPTION, k.TEXT_2, w=1248)])
    return f


def main() -> None:
    k.ambiguity(f"the estimated level's reason is CMP-227's display name \"{k.EST_NAME}\" (`iceberg`, a `05`:169 "
                "token; R-5); the values slot names each value (\"bid …, ask …, delta …\")")
    k.ambiguity(f"the imbalance flag reads ask ≥ {k.IMB_RATIO} × bid at one level (`05`'s 300 % example); the "
                "diagonal comparison is E18's")
    b = k.BOARDS[NN]
    blocks = [(b.frames[0], [f"Bar {k.hhmm(k.CURSOR.minute)}, level {k.px_fmt(k.price(F.k))} ({len(k.FOOTPRINT)} "
                             f"levels of {k.FP_ROW} ticks): imbalanced and estimated (QA-1)",
                             f"Name grammar (§5): {k.NAME_GRAMMAR}"])]
    p, md, pk = k.build(NN, [frame()], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
