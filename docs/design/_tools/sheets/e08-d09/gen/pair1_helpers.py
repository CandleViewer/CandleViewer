"""Pair A helpers (boards 01 healthy and 08 healthy-light): the SCR-147 page in its served form and the budgets
section in S-13 / S-15 / S-16 / S-17 / S-18 / S-19. Builds on e08d09kit (never edits it). Every string comes from the
spec through k.w() / k.state_word() / k.L()-cited prose; every figure derives from the world below."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e08d09kit as k  # noqa: E402

Node = dict[str, Any]

# --- the illustrative world (one clock: k.AS_OF; reserve served as D09-G14 in the served frames)
LIM_O, LIM_R = k.LIM["order_per_s"], k.LIM["read_per_s"]
RESERVE = 2  # requests per account in the 1 s order window (W-06b's count; illustrative, D09-G14 assumed served)
ACCTS = k.ACCOUNTS[:2]  # table and reserve-band rows: Main, Swing (the simulator lists all five)
# (class, adapter class, account, used now)
ORDER_ROWS = [("order.create", "Main", 3), ("order.amend", "Main", 1), ("order.cancel", "Main", 0),
              ("order.cancel_all", "Main", 0), ("batch", "Main", 0), ("order.create", "Swing", 2)]
QUERY_ROWS = [("position.read", "position", "Main", 4), ("account.read", "account", "Main", 1),
              ("market.read", "market_data", "Public", 12)]
CONNS, TOPICS = 3, 120  # public market-data sockets and topics (W-44, W-52 slots)
WS_OPENED = CONNS  # opened in the last 5 minutes (the three sockets)
CLOCK_MS = 12  # In sync, 12 ms behind (W-29); W-38 in seconds
CLOCK_AGE = 128  # last measured 128 s before AS_OF (< 300 s cadence, < 900 s stale)
STALE_AGE = 9  # S-15: the budgets read is 9 s old; stale since as-of + 5 s
LAST_GOOD = 13  # S-17: last good read 13 s before AS_OF


def order_head(used: int) -> int:
    return k.headroom(LIM_O, used, RESERVE)[0]


# --- §15 string finder: which W-keys a frame's texts carry (for the per-frame "Strings" cite line)
def _piece_res() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for key, c in k.COPY.items():
        for piece in [c.text, *c.text.split(" · ")]:
            pat = re.escape(piece)
            pat = re.sub(r"\\\{[^{}]*?\\\}", ".+?", pat)
            out.append((key, re.compile(f"^{pat}$")))
    return out


_PIECES = _piece_res()


def keys_in(n: Node) -> list[str]:
    found: set[str] = set()
    for _p, x in k.walk(n):
        if x["t"] == "text":
            for key, rx in _PIECES:
                if rx.match(x["chars"]):
                    found.add(key)
    return sorted(found, key=lambda s: (int(re.sub(r"\D", "", s)), s))


def strings_line(n: Node, seen: set[str] | None = None) -> str:
    """The frame's §15 keys with their lines; with seen=, only the keys not cited on an earlier frame."""
    ks = [x for x in keys_in(n) if not seen or x not in seen]
    if seen is not None:
        seen.update(ks)
    head = "Strings (§15, verbatim)" if not seen or len(seen) == len(ks) else "More strings (§15, verbatim)"
    return f"{head}: " + (", ".join(f"{x} L{k.COPY[x].line}" for x in ks) or "none beyond the earlier frames")


# --- cells
def word_cell(sid: str, *, inner: int, figures: tuple[str, ...] = ()) -> Node:
    """A cell's state as glyph + word (the S-19 / S-17 form of Used now, Headroom and the meter's place)."""
    st = k.REGISTER[sid]
    kids = [k.glyph(st.glyph, k.tone_color(sid)),
            k.text("word", k.state_word(sid), k.BODY_STRONG, k.TEXT_1, w=inner - 20)]
    out = k.hbox(f"state · {sid}", kids, {"gap": k.INSET_XS, "align": "start"}, w=inner)
    if figures:
        out = k.vbox(f"state · {sid} + figures", [out, *[k.text(f"figure-{i}", f, k.CAPTION, k.TEXT_2, w=inner)
                                                       for i, f in enumerate(figures, 1)]], {"gap": k.STACK_XS},
                     w=inner)
    return out


def stale_chip(age_s: int, name: str = "state · S-15") -> Node:
    """S-15's chip: clock glyph (pending) in data-confidence.stale.indicator + "Stale {4s}" (W-04 piece 2)."""
    return k.hbox(name, [k.glyph("clock", f"{k.DC}.stale.indicator"),
                         k.text("word", k.w("W-04", 2, k.ago(age_s)), k.BODY_STRONG, f"{k.DC}.stale.text")],
                  {"gap": k.INSET_XS})


# --- the per-class table (§3): served rows, and the wider column set for word cells (S-17, S-19)
C = k.Col
# Account 76 and Window 60 (the live check's SHEET-FIX: the header "Window" is 43 px, past a 56 px column's 40 inner)
S_COLS = (C("class", "Class", 152), C("account", "Account", 76), C("limit", "Limit", 64, True),
          C("used", "Used now", 136, True), C("window", "Window", 60, True), C("headroom", "Headroom", 136, True),
          C("meter", "Meter", 136), C("state", "State", 136), C("action", "", 48))
assert sum(c.w for c in S_COLS) == k.INNER_W


def header(cols: tuple[k.Col, ...]) -> Node:
    heads = k.w("W-08").split(" · ")
    return k.header_row([k.Col(c.key, heads[i] if i < len(heads) else c.label, c.w, c.numeric)
                         for i, c in enumerate(cols)])


def _inner(cols: tuple[k.Col, ...], key: str) -> int:
    return next(c.w for c in cols if c.key == key) - 16


def class_cell(cls: str, second: str | None, inner: int, color: str = k.TEXT_1) -> Node:
    """The Class cell's two lines (§3.1: endpoint_class, then the adapter class), both width-bound to the cell so a
    long second line wraps inside it (kit cell()'s second line is not width-bound)."""
    kids = [k.text("value", cls, k.BODY, color, w=inner)]
    if second:
        kids.append(k.text("second", second, k.CAPTION, k.TEXT_2, w=inner))
    return k.vbox("lines", kids, {"gap": k.STACK_XS}, w=inner)


def served_rows(*, colors: dict[str, str] | None = None, state: Node | None = None,
                subset: tuple[str, ...] | None = None, cols: tuple[k.Col, ...] = k.BUDGET_COLS,
                start: int = 1) -> list[Node]:
    """Every row of board 01's served table. state= replaces each row's S-01 cell (S-15's chip); subset= keeps the
    rows whose "class · account" is listed (order kept)."""
    rows: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def st() -> Node:
        return dict(state) if state else k.state_line("S-01", origin=False, w_=_inner(cols, "state"))

    for cls, acct, used in ORDER_ROWS:
        h = order_head(used)
        rows.append((f"{cls} · {acct}", {
            "class": cls, "account": acct, "limit": f"{LIM_O} / s", "used": str(used), "window": "1 s",
            "headroom": k.headroom_cell(LIM_O, used, RESERVE),
            "meter": k.meter(used, LIM_O, valuetext=k.w("W-09", None, used, LIM_O, h)), "state": st(),
            "action": k.row_action()}, {"class": "order"}))
    for cls, adapter, acct, used in QUERY_ROWS:
        h = k.headroom(LIM_R, used)[0]
        rows.append((f"{cls} · {acct}", {
            "class": cls, "account": acct, "limit": f"{LIM_R} / s", "used": str(used), "window": "1 s",
            "headroom": k.headroom_cell(LIM_R, used),
            "meter": k.meter(used, LIM_R, valuetext=k.w("W-09", None, used, LIM_R, h)), "state": st(),
            "action": k.row_action()}, {"class": adapter}))
    lo, lc = k.LIM["ws_new_per_5min"], k.LIM["ws_concurrent"]
    rows.append(("Public WS · opened", {
        "class": "Public WS", "account": "Public", "limit": f"{lo} / 5 min", "used": str(WS_OPENED),
        "window": "300 s", "headroom": k.headroom_cell(lo, WS_OPENED),
        "meter": k.meter(WS_OPENED, lo), "state": st()},
        {"class": "connections opened in the last 5 minutes"}))
    rows.append(("Public WS · concurrent", {
        "class": "Public WS", "account": "Public", "limit": str(lc), "used": str(CONNS), "window": "—",
        "headroom": k.headroom_cell(lc, CONNS), "meter": k.meter(CONNS, lc), "state": st()},
        {"class": "concurrent connections"}))
    for acct in ACCTS:
        rows.append((f"Private WS · {acct}", {
            "class": "Private WS", "account": acct, "limit": "—", "used": "—", "window": "—", "headroom": "—",
            "state": st()}, {}))
    if subset is not None:
        rows = [r for s in subset for r in rows if r[0] == s]
    ci = _inner(cols, "class")
    out = []
    for i, (nm, cells, sec) in enumerate(rows, start):
        cc = class_cell(cells["class"], sec.get("class"), ci, (colors or {}).get("class", k.TEXT_1))
        out.append(k.table_row(cols, dict(cells, **{"class": cc}), f"row {i:02d} · {nm}", i, colors=colors))
    return out


def word_rows(sid: str, picks: list[tuple[str, str | None, str, str | None, str | None]],
              figures: tuple[str, ...] = (), start: int = 1) -> list[Node]:
    """Rows whose Used now, Headroom and meter's place read sid's word (§3.2: S-19, or S-17 / S-18 after a failed
    read); picks = (class, second line, account, limit text or None, window text or None). None prints "—"."""
    out = []
    for i, (cls, sec, acct, lim, win) in enumerate(picks, start):
        cells: dict[str, Any] = {"class": class_cell(cls, sec, _inner(S_COLS, "class")), "account": acct,
                                 "limit": lim or "—", "window": win or "—"}
        for key in ("used", "headroom", "meter"):
            cells[key] = word_cell(sid, inner=_inner(S_COLS, key))
        cells["state"] = word_cell(sid, inner=_inner(S_COLS, "state"), figures=figures)
        out.append(k.table_row(S_COLS, cells, f"row {i:02d} · {cls} · {acct}", i))
    return out


def budgets_table(rows: list[Node], cols: tuple[k.Col, ...] = k.BUDGET_COLS) -> Node:
    return k.table("CMP-049 budgets", k.w("W-07"), header(cols), rows)


def reserve(served: bool, label_w: int = 344) -> Node:
    """k.reserve_band's pattern (§7 item 1) with a wider label column: "Reserved for stops and cancels · Swing" plus
    its glyph needs about 305 px, past the kit's 280."""
    out = []
    for alias in ACCTS:
        lab = f"{k.w('W-06a', 0)} · {alias}"
        val = (k.text("text", k.w("W-06b", 1, RESERVE), k.NUM, k.TEXT_1) if served else
               k.not_connected("value", "D09-G14", both=False))
        out.append(k.kv_row(f"reserve · {alias}", lab, val, glyph_kind="ring", label_w=label_w))
    return k.vbox("reserve band", out, {"stroke": k.NEUTRAL, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                        "radius": k.R_CARD}, w=k.INNER_W,
                  note="separate labelled band (§7 item 1); never focusable (§17.3)")


# --- the summary strip (§2.2 item 2)
def strip(served: bool = True) -> Node:
    tw = k.tile_widths()
    H = k.TILE_HEADINGS
    if not served:  # S-19: every tile waits on its read (R-2: never 0)
        gids = ("D09-G1", "D09-G3", "D09-G1", "D09-G5", "D09-G1")
        return k.summary_strip([k.tile(H[i], None, None, w_=tw[i], gid=gids[i]) for i in range(5)])
    busiest = max(u for _c, _a, u in ORDER_ROWS)
    tiles = [k.tile(H[0], "S-01", k.w("W-14", 1, k.headroom(LIM_O, busiest, RESERVE)[2]), w_=tw[0]),
             k.tile(H[1], "S-01", k.w("W-52", 1, TOPICS), w_=tw[1]),
             k.tile(H[2], "S-01", None, w_=tw[2]),
             k.tile(H[3], None, None, w_=tw[3], status=k.clock_ok_status(CLOCK_MS)),
             k.tile(H[4], "S-01", None, w_=tw[4])]
    return k.summary_strip(tiles)


# --- the sections below the budgets (§8, §9, §10, §11, §14)
def simulator(output_s19: bool = False) -> Node:
    p = k.w("W-41").split(" · ")
    accts = k.vbox("accounts", [k.text("label", p[0], k.LABEL, k.TEXT_2),
                                k.hbox("checkbox list", [k.checkbox(a, checked=True) for a in k.ACCOUNTS],
                                       {"gap": k.INSET_LG}, h=24)], {"gap": k.INSET_XS},
                   note="fieldset; the Owner's accounts by alias, never typed ids (§8)")
    fields = k.hbox("legs", [k.number_field(p[1], "1"), k.number_field(p[2], "2"),
                             k.vbox("stop-loss", [k.text("text", p[3], k.BODY_STRONG, k.TEXT_1)], {"gap": k.INSET_XS},
                                    note="static text, not a control (C-2.6)")],
                    {"gap": k.STACK_LG, "align": "end"})
    policy = k.vbox("fan-out policy", [k.text("label", p[4], k.LABEL, k.TEXT_2), k.segmented([p[5], p[6]], p[6])],
                    {"gap": k.INSET_XS})
    kids: list[Node | None] = [accts, fields, policy, k.button(p[7], "primary")]
    if output_s19:
        kids.append(k.not_connected("output", "D09-G10", w_=k.INNER_W))
    return k.section("Fan-out simulator", kids, waits=["D09-G10"])


def inspector() -> Node:
    return k.section("Subscription inspector", [k.disclosure(k.w("W-44", None, CONNS, TOPICS))], waits=["D09-G3"])


def clock(served: bool = True) -> Node:
    lab = k.CLOCK_LABELS[1:]
    if served:
        vals = [k.w("W-38", 0, k.offset_s(CLOCK_MS)), k.w("W-39", 1, k.at(-CLOCK_AGE), k.ago(CLOCK_AGE)),
                k.w("W-39", 0)]
        rows = [k.kv_row("dl · state", "State", k.clock_ok_status(CLOCK_MS))]
        rows += [k.kv_row(f"dl · {lab[i].lower()}", lab[i], vals[i]) for i in range(3)]
    else:
        rows = [k.kv_row(f"dl · {x.lower()}", x, k.not_connected("value", "D09-G5", both=False))
                for x in k.CLOCK_LABELS]
    dl = k.vbox("CMP-036 dl", rows, None, w=k.INNER_W)
    return k.section("Clock", [dl, k.button(k.w("W-35", 0))], waits=["D09-G5", "D09-G6"])


def actions(served: bool = True) -> Node:
    trig = (k.button(k.w("W-50")) if served else
            k.hbox("trigger · S-19", [k.button(k.w("W-50")), k.not_connected("state", "D09-G7", both=False)],
                   {"gap": k.INSET_SM}))
    priv = k.hbox("private stream placeholder · Main",
                  [k.text("label", k.w("W-53", 0, k.ACCOUNTS[0]), k.BODY, k.TEXT_2),
                   k.not_connected("state", "D09-G7", both=False)], {"gap": k.INSET_SM},
                  note="placeholder row (§11): its own confirm text W-53, S-19")
    return k.section("Actions", [trig, priv], waits=["D09-G7"])


def history() -> Node:
    return k.section("History", [k.disclosure(k.w("W-70"))], waits=["D09-G9"])


def page_height(sections: list[Node]) -> float:
    page = k.vbox("page", [k.band(), k.rule(), k.page_header(), *sections], {"gap": k.STACK_LG}, w=k.INNER_W)
    return k.est_height(page)
