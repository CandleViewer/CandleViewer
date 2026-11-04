"""Board 08 protocol-and-keyboard: the probes T1–T7 with their decision rules, the 45-minute agenda with its
counterbalanced order, and T6's keyboard walkthrough path on the paper prototype (memo §10; F-15; C2, C3). Nothing on
this board has been run."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 8
FW = 1600
IW = FW - 2 * k.FRAME_PAD


def probes(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cols = [k.Col("t", "T", 48), k.Col("probe", "Probe (say it aloud)", 400), k.Col("stim", "Stimulus", 368),
            k.Col("rule", "Decision rule", 448), k.Col("dec", "Decides", 288)]
    rows = [{"t": c[0], "probe": c[1], "stim": c[2], "rule": c[3], "dec": c[4]} for c, _i in k.PROBES.values()]
    rule = k.plain(k.LINES["spec"][k.find_line("Decision rule, per probe") - 1])
    return (k.frame(fid, [k.grid_table("probes (memo §10.2)", cols, rows, row_h=24,
                                       cap="Probes T1–T7 (memo §10.2), fixed order"),
                          rb.card("Decision rule (memo §10.3)", [k.memo(rule)], IW)],
                    FW, k.memo("## 10. Owner session protocol (ready to run; nothing below has been run)").lstrip("# ")),
            k.frame_block(fid, ["Each probe names the default it can overturn; a one-one split keeps the PROPOSED "
                                "default and goes to the owner as an OQ (memo §10.3)"]))


def agenda(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    spans = []
    for mins, (c, _i) in k.AGENDA.items():
        a, b = (int(x) for x in re.split("–", mins))
        spans.append((a, b, c[1]))
    total = spans[-1][1]
    sc = IW / total
    kids: list[k.Node] = []
    for i, (a, b, step) in enumerate(spans):
        x, w = int(a * sc), int((b - a) * sc)
        kids.append(k.rect(f"span · {a}-{b}", w - 2, 24, (k.RAISED, k.HOVER)[i % 2],
                           {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR}, x=x, y=0))
        kids.append(k.text(f"minutes · {a}-{b}", f"{a}–{b}", k.NUM_SM, k.TEXT_1, x=x + 4, y=6))
    k.derive(f"agenda: {len(spans)} steps over {total} min drawn {IW} px wide ({sc:.1f} px a minute)")
    acols = [k.Col("m", "Minutes", 96), k.Col("s", "Step", IW - 96)]
    atab = k.grid_table("agenda steps", acols, [{"m": f"{a}–{b}", "s": st} for a, b, st in spans], row_h=24,
                        cap="Agenda (memo §10.4)")
    order = k.plain(k.LINES["spec"][k.ORDER_LINE - 1])
    part = k.plain(k.LINES["spec"][k.find_line("Three sessions of 45 min") - 1]).split(". ")[0] + "."
    return (k.frame(fid, [k.box("agenda", kids, {}, w=IW, h=24), atab,
                          rb.card("Order (memo §10.4)", [k.memo(order)], IW),
                          rb.card("Participants (memo §10.1)", [k.memo(part)], IW),
                          rb.card("Harness precondition (G4)", [k.memo("A recorder-captured BTCUSDT volatile window at "
                                                                       "depths 50, 200 and 500, declared on the sheet "
                                                                       "by capture date and window; until it exists "
                                                                       "the sessions do not run.")], IW)],
                    FW, k.memo("### 10.4 Agenda (45 min) and counterbalancing").lstrip("# ")),
            k.frame_block(fid, ["Minutes and steps verbatim from §10.4's table"]))


def walkthrough(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t6, _ln = k.PROBES["T6"]
    steps = ["reach the ladder", "move rows", "reveal one level's history", "cycle regions", "say what Enter would do"]
    for s_ in steps:
        k.memo(s_)
    pw, ph = 760, 360
    regions = [("header", 0, 0, pw, 40), ("heatmap region", 0, 48, 400, ph - 48), ("ladder region", 408, 48,
                                                                                   pw - 408, ph - 48)]
    kids: list[k.Node] = []
    for name, x, y, w, h in regions:
        kids.append(k.box(f"dashed · {name}", [k.text("name", name, k.CAPTION, k.TEXT_2, x=8, y=6)],
                          {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w, h=h,
                          x=x, y=y))
    kids.append(dict(rb.badge(k.memo("trail [60s v]")), x=120, y=10))
    spots = [(420, 80), (560, 140), (440, 200), (120, 160), (440, 300)]
    for i, ((x, y), s_) in enumerate(zip(spots, steps), 1):
        kids.append(dict(rb.marker(f"{i} · {s_}", None, name=f"dashed · step {i}"), x=x, y=y))
    proto = k.box("paper prototype · SCR-050", kids, {"fill": k.RAISED}, w=pw, h=ph,
                  note="the paper prototype: SCR-050's ASCII regions (memo §10.1), lo-fi")
    c2, _c = k.CONTRAS["C2"]
    c3, _d = k.CONTRAS["C3"]
    keys = rb.card("Keys the memo cites (14:1214)", [k.memo("Space = re-centre + resume auto-follow"),
                                                        k.memo("C centres on the mark"),
                                                        k.memo("+/- = price zoom")], IW - pw - 24)
    enter = rb.card("Enter: three meanings (C2, no ruling here)", [k.FINDINGS["F-15"][0][2]], IW - pw - 24)
    return (k.frame(fid, [k.text("probe", f"T6 · {t6[1]}", k.BODY, k.TEXT_1, w=IW),
                          k.hbox("pair", [proto, k.vbox("cards", [keys, enter,
                                                                  rb.card("C3", [c3[1], c3[2]], IW - pw - 24)],
                                                        {"gap": k.STACK_SM}, w=IW - pw - 24)],
                                 {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          k.hbox("cards2", [rb.card("F-15 (heuristic) · Blocker", [k.FINDINGS["F-15"][0][1]],
                                                    (IW - 12) // 2),
                                            rb.card(f"C2 → {c2[2]}", [c2[1]], (IW - 12) // 2)],
                                 {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "T6: the keyboard-only path on the paper prototype; the moderator never demonstrates Enter"),
            k.frame_block(fid, ["Step markers are board markers in the probe's order; no key is assigned to a step "
                                "the memo does not name (E21-D06 #506 owns the keyboard model)",
                                "T6 runs in S3 only and changes no default (memo §10.3)"], fs=["F-15"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((probes, agenda, walkthrough), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["Nothing on this board has been run; the protocol is ready for the owner (memo §10, §11)"])
