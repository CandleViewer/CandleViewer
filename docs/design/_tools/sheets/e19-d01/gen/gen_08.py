"""Board 08 decisions: memo §7 PD-1..PD-8, each with the PASS / FAIL check E19-D02 runs, its evidence and its target
(every one PROPOSED), and where each decision and gap goes next (§11 traceability, §9.1 contradictions, §9.2 gaps)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 8


def decisions(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hd = k.table_head("## 7. Proposed decisions")
    keys = ("pd", "dec", "chk", "ev", "tg", "st")
    rows = [dict(zip(keys, c)) for c in k.PDS.values()]
    t = rb.table("decisions", list(zip(keys, hd, (64, 288, 616, 152, 176, 96))), rows,
                 cap=f"memo §7 L{k.PD_LINE['PD-1'] - 2}: PD-1..PD-8 verbatim; each is one sentence a greyscale "
                     "wireframe satisfies or violates")
    lead = k.LINES["spec"][k.L("## 7. Proposed decisions") + 1].strip().replace(" :", ":")
    return (k.frame(fid, [rb.card("adoption", [rb.para("words", lead, rb.IW - 24)], rb.IW), t], rb.FW,
                    "Research — eight PROPOSED decisions with their checks; the design approval adopts them as "
                    "interim rulings, each reversible by the owner in one line"),
            k.frame_block(fid, ["Every decision PROPOSED; the owner's sessions (§10) can overturn any of them"]))


def trace(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t1 = rb.table("traceability", list(zip(("a", "b"), k.table_head("## 11. Traceability"), (240, 1152))),
                  [{"a": c[0], "b": c[1]} for _i, c in k.TRACE], cap="memo §11: where each decision goes next")
    hc = k.table_head("### 9.1 Contradictions")
    t2 = rb.table("contradictions", list(zip(("c", "x", "s", "r", "o"), hc, (56, 480, 240, 456, 160))),
                  [dict(zip(("c", "x", "s", "r", "o"), c)) for _i, c in k.CONTRA],
                  cap="memo §9.1: contradictions, none resolved silently")
    hg = k.table_head("### 9.2 Contract and definition gaps")
    t3 = rb.table("gaps", list(zip(("g", "x", "e", "r"), hg, (56, 760, 312, 264))),
                  [dict(zip(("g", "x", "e", "r"), c)) for _i, c in k.GAPS],
                  cap="memo §9.2: contract first; no field invented")
    return (k.frame(fid, [t1, t2, t3], rb.FW,
                    "Research — traceability: each decision's next ticket, the contradictions and the contract gaps "
                    "the wireframes must not paper over"),
            k.frame_block(fid, ["Tables verbatim from memo §11, §9.1, §9.2; A-rows on the boards that use them "
                                "(03, 04, 06, 09)"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((decisions, trace), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
