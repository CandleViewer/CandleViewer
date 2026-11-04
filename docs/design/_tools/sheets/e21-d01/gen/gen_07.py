"""Board 07 ranked-decisions: AD-1..AD-10 with their satisfies / violates clauses (memo §7, ranked), and the
performance kill-list K1–K5 that bounds them (memo §8). Every cell verbatim; every decision PROPOSED."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 7
FW = 1760
IW = FW - 2 * k.FRAME_PAD
COLS = [k.Col("ad", "AD", 64), k.Col("dec", "Decision (PROPOSED)", 352), k.Col("sat", "Satisfies if", 408),
        k.Col("vio", "Violates if", 408), k.Col("el", "Element", 160), k.Col("from", "From", 128),
        k.Col("own", "Owner", 192)]


def ad_frame(fid: str, ids: list[str]) -> tuple[k.Node, tuple[str, list[str]]]:
    rows = [{"ad": c[0], "dec": c[1], "sat": c[2], "vio": c[3], "el": c[4], "from": c[5], "own": c[6]}
            for a, (c, _i) in k.ADS.items() if a in ids]
    lead = k.memo("Ranked by the cost of getting it wrong on a click-to-trade surface. A wireframe reviewer marks "
                  "each one satisfied or violated from the frames alone.")
    return (k.frame(fid, [k.text("lead", lead, k.BODY, k.TEXT_2, w=IW),
                          k.grid_table("decisions (memo §7)", COLS, rows, row_h=24,
                                       cap=f"{ids[0]}..{ids[-1]} (memo §7), rank order")],
                    FW, k.memo("## 7. Adopted decisions AD-1..AD-10 (ranked; heuristic, PROPOSED)").lstrip("# "),
                    proposed=True),
            k.frame_block(fid, ["Illustrated on: " + "; ".join(f"{a} board {k.AD_DRAWN[a]:02d}" for a in ids),
                                "Every AD stays PROPOSED; the owner can reverse any one by one line (memo §7)"]))


def kill_list(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("k", "K", 56), k.Col("req", "Requested behaviour", 400), k.Col("num", "Killing number", 856),
            k.Col("ver", "Verdict", 400)]
    rows = [{"k": c[0], "req": c[1], "num": c[2], "ver": c[3]} for c, _i in k.KILLS.values()]
    budgets = k.plain(k.LINES["spec"][k.BUDGET_LINE - 1])
    return (k.frame(fid, [k.text("budgets", k.memo(budgets), k.BODY, k.TEXT_2, w=IW),
                          k.grid_table("kill-list (memo §8)", cols, rows, row_h=24, cap="K1–K5 (memo §8)")],
                    FW, k.memo("## 8. Performance kill-list (budgets #1 and #14; heuristic, PROPOSED)").lstrip("# "),
                    proposed=True),
            k.frame_block(fid, ["Killed defaults stay opt-ins where the verdict says so (K3 → AD-8, K5 → AD-9)"]))


if __name__ == "__main__":
    fr = k.BOARDS[NN].frames
    built = [ad_frame(fr[0], [f"AD-{i}" for i in range(1, 6)]), ad_frame(fr[1], [f"AD-{i}" for i in range(6, 11)]),
             kill_list(fr[2])]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["Rank order is the memo's; the 'illustrated on' lines point at this set's boards"])
