"""Board 01 questions-hypotheses: memo §2's research questions RQ1..RQ6 with their pre-registered hypotheses (all
untested), each with the protocol task that tests it and the outcome that rewrites its decision (§10.3); the method
note, its honest limits and deviations, and the acceptance-criteria trace."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 1


def questions(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rows = []
    for rq, q, h in k.RQS:
        hits = [c for _i, c in k.RULES if c[0].split(",")[0] == rq]
        rows.append({"rq": rq, "q": q, "h": f"H{rq[2:]}: {h}", "state": "untested",
                     "task": "; ".join(c[1] for c in hits) or "—", "out": " · ".join(c[2] for c in hits) or "—"})
    k.derive("tested by / rewrites: each RQ's rows of memo §10.3's 'RQ / decision' table (" +
             ", ".join(f"{r['rq']} → {r['task']}" for r in rows) + ")")
    lead = k.memo("Research questions and hypotheses (all untested).")
    t = rb.table("research questions", [("rq", "RQ", 56), ("q", "question", 280), ("h", "hypothesis", 360),
                                        ("state", "state", 88), ("task", "tested by", 96),
                                        ("out", "outcome that rewrites the decision (memo §10.3)", 512)], rows,
                 cap=f"memo §2 L{k.RQ_LINE}: RQ1..RQ6, verbatim; the hypotheses are pre-registered and untested")
    return (k.frame(fid, [rb.title(lead, rb.IW), t, rb.marker(k.memo(
        "no session was run — no participant, timing, score or quote exists"), 520)], rb.FW,
        "Research — the six questions, their hypotheses and the task that will test each; nothing here is observed"),
        k.frame_block(fid, [f"RQ text verbatim from memo §2 L{k.RQ_LINE}", "Outcome column verbatim from memo §10.3"]))


def method(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cw = (rb.IW - 16) // 2
    meth = k.METHOD.replace("**", "").strip()
    dev = k.sentence_after("**Deviations (recorded, not hidden).**")
    cards = k.hbox("cards", [rb.card("method", [k.text("label", "Method note (memo §2)", k.LABEL, k.TEXT_2),
                                                rb.para("words", meth, cw - 24)], cw),
                             rb.card("deviations", [k.text("label", "Deviations (recorded, not hidden)", k.LABEL,
                                                           k.TEXT_2), rb.para("words", dev, cw - 24)], cw)],
                   {"gap": k.INSET_LG, "align": "start"}, w=rb.IW)
    ac = [{"ac": c[0], "where": c[1], "st": c[2]} for _i, c in
          k.rows_of("## Acceptance-criteria trace")]
    t = rb.table("acceptance-criteria trace", [("ac", "ticket AC or deliverable", 600), ("where", "where", 340),
                                               ("st", "status", 452)], ac,
                 cap="Acceptance-criteria trace (memo, verbatim): heuristic-only = delivered by the adaptation, "
                     "pending the owner's sessions")
    return (k.frame(fid, [cards, t], rb.FW, "Research — method, honest limits and deviations; the acceptance-criteria "
                                           "trace shows what stays open until the owner's sessions"),
            k.frame_block(fid, [f"Method paragraph verbatim from memo §2 L{k.METHOD_LINE + 2}; deviations "
                                f"L{k.DEVIATIONS_LINE}", "AC 2, AC 3 and the sessions stay open (memo BQ-1)"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((questions, method), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
