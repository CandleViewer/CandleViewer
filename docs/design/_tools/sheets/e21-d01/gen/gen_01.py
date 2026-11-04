"""Board 01 questions-hypotheses: RQ1–RQ5 and H1–H5 with the heuristic leaning (memo §2), the findings F-1..F-17 that
lean each question (§3, every one (heuristic)) and the persona walkthrough W1–W4 (§4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 1
FW = 1440
IW = FW - 2 * k.FRAME_PAD


def rqs(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("rq", "RQ", 56), k.Col("q", "Question (ticket Context)", 344),
            k.Col("h", "Hypothesis (pre-registered)", 552), k.Col("lean", "Heuristic leaning (§3)", 336),
            k.Col("st", "Status", 104)]
    rows = [{"rq": c[0], "q": c[1], "h": c[2], "lean": c[3], "st": c[4]} for c, _i in k.RQS.values()]
    fs = {rq: [f for f, (c, _i) in k.FINDINGS.items() if c[5] == rq] for rq in k.RQS}
    k.derive("findings per RQ (§3's RQ column): " + "; ".join(f"{rq} {', '.join(v)}" for rq, v in fs.items()))
    lean = [rb.card(f"{rq} · leaning from", [", ".join(v)], (IW - 4 * 12) // 5, name=f"card · {rq}")
            for rq, v in fs.items()]
    return (k.frame(fid, [k.grid_table("research questions (memo §2)", cols, rows, row_h=24,
                                       cap="Research questions and pre-registered hypotheses (memo §2); every status "
                                           "untested"),
                          k.hbox("findings per question", lean, {"gap": k.INSET_MD, "align": "start"}, w=IW)], FW,
                    k.memo("## 2. Research questions and pre-registered hypotheses").lstrip("# ")),
            k.frame_block(fid, ["Rows verbatim from memo §2; the cards list §3's findings by their RQ column",
                                "Nothing was observed: the hypotheses are tested by the owner session protocol "
                                "(board 08)"]))


def findings(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("f", "F", 56), k.Col("finding", "Finding", 600), k.Col("ev", "Evidence", 432),
            k.Col("h", "Heuristic", 136), k.Col("sev", "Severity", 104), k.Col("rq", "RQ", 64)]
    rows = [{"f": c[0], "finding": c[1], "ev": c[2], "h": c[3], "sev": c[4], "rq": c[5]}
            for c, _i in k.FINDINGS.values()]
    sev = {s: sum(1 for c, _i in k.FINDINGS.values() if c[4] == s) for s in ("Blocker", "Major", "Minor")}
    k.derive(f"severity counts from §3: {', '.join(f'{v} {s}' for s, v in sev.items())}")
    return (k.frame(fid, [k.text("scale", k.memo("Severity: Blocker (a trade or a read goes wrong) · Major (a read is "
                                                 "slow or doubtful) · Minor."), k.BODY, k.TEXT_2, w=IW),
                          k.grid_table("findings (memo §3)", cols, rows, row_h=24,
                                       cap="Heuristic evaluation F-1..F-17 (memo §3), every finding (heuristic)")],
                    FW, k.memo("## 3. Heuristic evaluation (every finding (heuristic))").lstrip("# ")),
            k.frame_block(fid, [f"{sev['Blocker']} Blocker, {sev['Major']} Major, {sev['Minor']} Minor (counted from "
                                "§3)", "Evidence cells keep the memo's citations (`doc`:line)"]))


def walkthroughs(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("w", "W", 48), k.Col("p", "Persona and probe", 504), k.Col("path", "Path through the catalogued "
                                                                              "SCR-050", 384),
            k.Col("br", "Where it breaks (heuristic)", 456)]
    rows = [{"w": c[0], "p": c[1], "path": c[2], "br": c[3]} for c, _i in k.WALKS.values()]
    return (k.frame(fid, [k.text("lead", k.memo("Each step walks one probe as a persona would, from the persona's "
                                                "documented goals; nothing was observed."), k.BODY, k.TEXT_2, w=IW),
                          k.grid_table("walkthrough (memo §4)", cols, rows, row_h=24,
                                       cap="Persona walkthrough W1–W4 (memo §4)")], FW,
                    k.memo("## 4. Persona walkthrough").lstrip("# ")),
            k.frame_block(fid, ["W → AD (memo §7 From cells): " + "; ".join(
                f"{w} → {', '.join(a for a, (c, _i) in k.ADS.items() if w in c[5].split(', ')) or 'via F-n only'}"
                for w in k.WALKS)]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((rqs, findings, walkthroughs), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["Every finding stays (heuristic) and every decision PROPOSED (BQ list RULED, memo L46)"])
