"""Board 09 protocol-table-alternative: memo §10 — the owner's session plan (tasks T0..T11 with budgets and pass
criteria, the rotation, the rule that rewrites each decision, the recording sheet) — and the profile table
alternative with `05` §6's columns plus A-6's six, filled from the synthetic developing session."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 9


def tasks(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hd = k.table_head("### 10.3 Tasks")
    rows = [dict(zip(("t", "task", "b", "p"), c)) for _i, c in k.TASKS]
    t = rb.table("tasks", list(zip(("t", "task", "b", "p"), hd, (56, 720, 80, 536))), rows,
                 cap=f"memo §10.3 L{k.TASKS_LINE}: T0..T11 verbatim; budgets are (heuristic) planning values")
    budgets = sum(int(re.match(r"(\d+) min", c[2]).group(1)) for _i, c in k.TASKS)  # type: ignore[union-attr]
    lead = k.LINES["spec"][k.L("Budgets and thresholds are") - 1].strip()
    m = re.search(r"Setup and consent take (\d+) minutes and the debrief (\d+); the tasks below total (\d+); a session "
                  r"totals (\d+) minutes", lead, re.DOTALL)
    if not m or int(m.group(3)) != budgets or int(m.group(1)) + int(m.group(2)) + budgets != int(m.group(4)):
        raise ValueError(f"§10.3: the budgets ({budgets}) do not add up to the memo's totals")
    k.derive(f"§10.3 budgets: T0..T11 sum to {budgets} min; + setup {m.group(1)} + debrief {m.group(2)} = "
             f"{m.group(4)} min (the memo's totals agree)")
    return (k.frame(fid, [rb.card("budgets", [rb.para("words", lead, rb.IW - 24)], rb.IW), t], rb.FW,
                    "Research — the owner's session plan: twelve tasks, each with a budget and a pass criterion; "
                    "nothing below has been run"),
            k.frame_block(fid, [f"OQ-6: {k.OQS[5][1][1]}", "Entry criteria (memo §10.2): the harness built, the named "
                                                            "fixtures (G-5), both switcher variants, a screen reader"]))


def rotation(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hr = k.table_head("### 10.4 Rotation")
    t1 = rb.table("rotation", list(zip(("s", "o", "d", "c"), hr, (88, 344, 112, 848))),
                  [dict(zip(("s", "o", "d", "c"), c)) for _i, c in k.ROTATION], cap="memo §10.4: rotation")
    hq = k.table_head("The four probes are verbatim from the ticket")
    t2 = rb.table("decision rule", list(zip(("q", "t", "o"), hq, (272, 112, 1008))),
                  [dict(zip(("q", "t", "o"), c)) for _i, c in k.RULES],
                  cap="memo §10.3: the outcome that rewrites each decision")
    lim = k.LINES["spec"][k.L("The composite task (T4) never directly follows") - 1].replace("**", "").strip()
    sheet = k.LINES["spec"][k.L("Per session: date, initials") - 1].strip()
    cw = (rb.IW - 16) // 2
    cards = k.hbox("cards", [rb.card("validity", [k.text("label", "Order rules and validity limits (memo §10.4)",
                                                         k.LABEL, k.TEXT_2), rb.para("words", lim, cw - 24)], cw),
                             rb.card("recording sheet", [k.text("label", "Recording sheet and decision rule (memo "
                                                                         "§10.5)", k.LABEL, k.TEXT_2),
                                                         rb.para("words", sheet, cw - 24)], cw)],
                   {"gap": k.INSET_LG, "align": "start"}, w=rb.IW)
    return (k.frame(fid, [t1, t2, cards], rb.FW,
                    "Research — rotation, the rule that rewrites a decision, and the recording sheet: two coders agree "
                    "and the owner approves before an interim ruling becomes final"),
            k.frame_block(fid, ["Three sessions cannot counterbalance nine tasks: a rotation, not a Latin square "
                                "(memo §10.4)"]))


def alternative(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pr = k.DEVELOPING
    base = [c[0] for _i, c in k.A11Y_PROFILE]
    a6 = k.AMEND["A-6"][2]
    m = re.search(r"add (.*) columns", a6, re.DOTALL)
    extra = [x.strip() for x in re.split(r", | and ", m.group(1))] if m else []  # type: ignore[union-attr]
    if extra != ["TPO count", "node (HVN / LVN)", "naked POC", "single print", "developing / final", "estimated"]:
        raise ValueError(f"A-6 columns moved: {extra}")
    hvn, lvn = k.nodes(pr)
    sp = set(k.single_prints(pr))
    top = pr.vol[pr.poc]
    words = k.developing_words(pr)
    rs = sorted(pr.rows, reverse=True)
    pick = rs
    in_va = {c for c in (re.findall(r'"([^"]+)"', k.A11Y_PROFILE[4][1][1]))}
    if in_va != {"In VA", "Outside VA"}:
        raise ValueError(f"`05` value-area words moved: {in_va}")
    rows = []
    for r in pick:
        rows.append({"price": k.row_price(pr, r), "vol": k.fmt_vol(pr.vol[r]), "delta": k.fmt_delta(pr.delta.get(r, 0)),
                     "pct": f"{pr.vol[r] * 100 // top} %",
                     "va": "In VA" if pr.va[0] <= r <= pr.va[1] else "Outside VA", "tpo": str(pr.tpo.get(r, 0)),
                     "node": "HVN" if r == hvn else "LVN" if r == lvn else "—", "npoc": "—",
                     "sp": "single print" if r in sp else "—", "dev": words, "est": "—"})
    keys = ("price", "vol", "delta", "pct", "va", "tpo", "node", "npoc", "sp", "dev", "est")
    heads = [*base, *extra]
    t = rb.table("table alternative", list(zip(keys, heads, (104, 104, 104, 88, 104, 96, 136, 104, 112, 232, 96))),
                 rows, selected=[pick.index(pr.poc)],
                 cap=f"all {len(pick)} rows, price descending (`05`'s default sort); "
                     f"{pr.label}, rows of {k.ROW_TICKS} ticks; the POC row selected")
    k.derive(f"table alternative: {pr.label} as of {k.hhmm(pr.as_of)} UTC; volume BTC on the {k.QTY_STEP} step; delta "
             f"and TPO over recorded trades; % of POC floored; nodes HVN {k.row_price(pr, hvn)}, LVN "
             f"{k.row_price(pr, lvn)}; naked POCs lie outside this session's range (that is what naked means), so the "
             "column reads — here; no approximated portion on 30 Oct, so estimated reads —")
    k.spec_gap("A-6 names the six columns but not their cell words: 'single print', 'HVN' / 'LVN', the developing "
               "words and '—' are kit readings (E19-D06 owns the table)")
    return (k.frame(fid, [t, rb.hidden("caption read by a screen reader", k.ui(
        f"Profile table, {pr.label}, {words}, {len(pr.rows)} rows", "the table's accessible caption"), 640)], rb.FW,
                    "Research — the table alternative P3 reads: `05` §6's five columns plus A-6's six, so every level "
                    "the canvas shows is in a cell"),
            k.frame_block(fid, [k.f_line("F-18"), f"A-6: {a6}"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((tasks, rotation, alternative), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
