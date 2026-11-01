"""Pair C helpers (boards 02 approaching-throttled and 10 throttled-hc): the order-row world, the budgets rows, the
S-03 detail panel and the scroll fit. Built on e08d09kit only; the kit is never edited."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_DIR = Path(__file__).resolve().parent.parent
if str(KIT_DIR) not in sys.path:
    sys.path.insert(0, str(KIT_DIR))

import e08d09kit as k  # noqa: E402

Node = dict[str, Any]

# --- the illustrative world of board 02 (one clock: k.AS_OF; one limit: k.LIM["order_per_s"], §3.2's default).
LIMIT = k.LIM["order_per_s"]  # order.create 10 requests per second (§3.2 documented default)
WINDOW_S = 1  # the order bucket's window (§3.1 "requests per second, per account")
RESERVE = 2  # requests held back per account in the 1 s order window (W-06b's slot; D09-G14 assumed served)
SPENDABLE = LIMIT - RESERVE  # R-4: headroom and S-02's share are on the spendable part
S02_LINE = SPENDABLE * k.LIM["s02_pct"] / 100  # §5.2 S-02: Used now >= 80 % of the spendable limit
RETRY_S = 42  # the exchange's retry hint as served (W-15's own sample slot, kept as the relative figure)
ACCTS = k.ACCOUNTS[:2]  # Main (the spec's slot), Swing (a kit alias); two rows keep the S-03 page inside the view
USED = {"S-02": {"Main": 7, "Swing": 4, "Scalp": 2}, "S-03": {"Main": 10, "Swing": 4, "Scalp": 2}}


def headroom(used: int) -> int:
    return k.headroom(LIMIT, used, RESERVE)[0]


def head_share(used: int) -> int:
    return k.headroom(LIMIT, used, RESERVE)[1]


def used_share(used: int) -> int:
    return k.headroom(LIMIT, used, RESERVE)[2]


def row_state(used: int, throttled: bool) -> str:
    if throttled:
        return "S-03"
    return "S-02" if used >= S02_LINE else "S-01"


def cite(key: str, *strings: str) -> str:
    """An annotation line quoting the drawn string(s) of a §15 key with its spec line."""
    c = k.COPY[key]
    return f'{key} (§15 L{c.line}): ' + " · ".join(f'"{s}"' for s in strings)


def budget_rows(frame_sid: str) -> tuple[list[Node], list[str]]:
    """order.create rows for Main, Swing, Scalp; Main carries the frame's state. Returns rows + derivation lines."""
    rows, lines = [], []
    for i, acct in enumerate(ACCTS, 1):
        used = USED[frame_sid][acct]
        sid = row_state(used, frame_sid == "S-03" and acct == "Main")
        hr = headroom(used)
        hr_pct = head_share(used)
        tone = {"S-01": "normal", "S-02": "warning", "S-03": "warning"}[sid]
        vt = k.w("W-09", None, used, LIMIT, hr)
        if sid == "S-02":
            figs = [k.w("W-14", 1, used_share(used))]
        elif sid == "S-03":
            figs = [k.w("W-15", 3, k.at(RETRY_S), RETRY_S)]
        else:
            figs = []
        st = k.state_line(sid, figs, origin=sid != "S-01", w_=160)
        rows.append(k.table_row(k.BUDGET_COLS, {
            "class": "order.create", "account": acct, "limit": f"{LIMIT} / s", "used": str(used),
            "window": f"{WINDOW_S} s", "headroom": k.headroom_cell(LIMIT, used, RESERVE),
            "meter": k.meter(used, LIMIT, w_=72, tone=tone, valuetext=vt), "state": st,
            "action": k.row_action()}, f"row {i:02d} · order.create · {acct}", i, second={"class": "order"}))
        lines.append(f"Row {i:02d} {acct}: Used {used} of {LIMIT} / s; Headroom {hr} = max(0, {LIMIT} − {RESERVE} "
                     f"reserve − {used}); share {hr_pct} % of {SPENDABLE} spendable; {sid} "
                     f"({'≥' if used >= S02_LINE else '<'} {S02_LINE:g} = 80 % of {SPENDABLE}); meter "
                     f'aria-valuetext "{vt}"')
    return rows, lines


def throttle_detail(acct: str = "Main", cls: str = "order") -> tuple[Node, list[str]]:
    """S-03's detail under the table (§6: scope, figures, the condition W-31, what not to do W-34 pieces 1-2, the
    operator action W-12): every sentence prints under its own state only."""
    iw = k.INNER_W - 2 * k.PX[k.INSET_LG]
    p1, p2 = k.w("W-15", 1, acct, cls), k.w("W-15", 2, LIMIT)
    p3, p4 = k.w("W-15", 3, k.at(RETRY_S), RETRY_S), k.w("W-15", 4)
    act = k.origin_action("S-03") or ""
    c1, c2 = (k.w("W-31", i) for i in (0, 1))
    n1, n2 = (k.w("W-34", i) for i in (0, 1))
    kids = [k.state_line("S-03", [p1, p2, p3, p4], w_=iw, name="state · S-03 · full"),
            k.text("operator action", act, k.BODY, k.TEXT_2, w=iw),
            k.lines_block("condition · W-31", [c1, c2], w_=iw),
            k.lines_block("what not to do · W-34", [n1, n2], w_=iw)]
    node = k.vbox(f"S-03 detail · {acct} · order.create", kids,
                  {"fill": k.RAISED, "radius": k.R_CARD, "pad": k.INSET_LG, "gap": k.STACK_SM,
                   "stroke": k.WARN_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=k.INNER_W,
                  note="S-03's own detail: W-31 and W-34 print under S-03 only, never under S-04/S-05 (§6)")
    lines = [cite("W-15", k.state_word("S-03"), p1, p2, p3, p4),
             f"Retry at {k.at(RETRY_S)} = as of {k.AS_OF} + {RETRY_S} s (derived; the exchange's hint as served, §6 "
             f"L{k.L('| Recovery time is')})",
             f'W-12 (§15 L{k.COPY["W-12"].line}): "{act}"', cite("W-31", c1, c2), cite("W-34", n1, n2),
             f"W-34 pieces 3-4 (reconnect, outbound setup) belong to S-04 / S-05 (§6 L{k.L('| What not to do (W-34)')}"
             f"): not drawn here"]
    return node, lines


def page_offsets(sections: list[Node]) -> tuple[float, float]:
    """(y of the first section inside the page, the page's estimated height), mirroring window()'s vbox."""
    gap = k.PX[k.STACK_LG]
    head = [k.band(), k.rule(), k.page_header(k.AS_OF)]
    top = sum(k.est_height(n) for n in head) + gap * len(head)
    total = top + sum(k.est_height(n) for n in sections) + gap * (len(sections) - 1)
    return top, total


def fit_scroll(sections: list[Node]) -> int:
    """0 when the page fits the 672 px view; else scroll so the summary strip starts at the view's top (never past
    the page's end), rounded down to 4 px."""
    top, total = page_offsets(sections)
    if total <= k.VIEW_H:
        return 0
    return int(min(top, total - k.VIEW_H) // 4 * 4)
