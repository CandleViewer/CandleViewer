"""Board 07 inspector-history: the inspector at 36 / 120 / 480 topic rows over 3 connections, S-14, the history
sparkline and its table, history empty, and S-19 for both (§0 L89, §9, §14). Dark.
Run: python3 -I -B gen/gen_07.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair4_helpers import Node, cite, clip_rows, filler, fixed_box, k, num, scroll_to, select_box  # noqa: E402

NN = 7
# Illustrative symbols (W-01); socket s holds SYMS[s*n:(s+1)*n]
SYMS = ("BTC ETH SOL XRP DOGE ADA AVAX LINK DOT LTC BCH TRX NEAR ATOM UNI APT ARB OP SUI SEI INJ TIA FIL ETC AAVE "
        "MKR LDO RUNE STX IMX ICP HBAR VET ALGO SAND MANA AXS GALA APE CRV DYDX GMX PEPE WIF BONK ORDI TON NOT JUP "
        "PYTH ENA ONDO WLD FET TAO KAS EGLD XLM THETA ZIL").split()
TYPES4 = (("orderbook", ("orderbook.50.{s}",)), ("publicTrade", ("publicTrade.{s}",)), ("tickers", ("tickers.{s}",)),
          ("kline", ("kline.1.{s}",)))
TYPES8 = (("orderbook", ("orderbook.50.{s}", "orderbook.200.{s}")), ("publicTrade", ("publicTrade.{s}",)),
          ("tickers", ("tickers.{s}",)), ("kline", ("kline.1.{s}", "kline.5.{s}", "kline.15.{s}", "kline.60.{s}")))
SCALES = {36: (3, TYPES4), 120: (10, TYPES4), 480: (20, TYPES8)}  # total rows -> (symbols per socket, topic types)
CONNS = 3
PING = (38, 41, 36)
SINCE = (-4012, -4415, -4818)  # connected since, seconds from AS_OF (over an hour: 0 reconnects in the last hour)
COLS = (k.Col("topic", "Topic", 304), k.Col("age", "Last message", 120), k.Col("gaps", "Gaps", 112),
        k.Col("resub", "Last resubscribe", 208), k.Col("reseed", "Last re-seed", 200))
COLS19 = (k.Col("topic", "Topic", 224), k.Col("age", "Last message", 180), k.Col("gaps", "Gaps", 180),
          k.Col("resub", "Last resubscribe", 180), k.Col("reseed", "Last re-seed", 180))
assert sum(c.w for c in COLS) == sum(c.w for c in COLS19) == k.INNER_W
L9 = k.L("- **Grouping:**")


def socket(total: int, s: int) -> list[tuple[str, list[str]]]:
    n, types = SCALES[total]
    syms = [f"{x}USDT" for x in SYMS[s * n:(s + 1) * n]]
    return [(t, [p.format(s=x) for x in syms for p in pats]) for t, pats in types]


def requests(topics: list[str]) -> list[list[str]]:
    lim = k.LIM["topics_per_request"]
    return [topics[i:i + lim] for i in range(0, len(topics), lim)]


def args_chars(batch: list[str]) -> int:
    """Characters of one subscribe request's arguments, as the compact JSON array (the planner's 21 000 cap)."""
    return len(json.dumps(batch, separators=(",", ":")))


def figures(total: int, s: int) -> dict[str, int | str]:
    topics = [t for _g, ts in socket(total, s) for t in ts]
    reqs = requests(topics)
    big = max(reqs, key=lambda b: (len(b), args_chars(b)))
    chars = max(args_chars(b) for b in reqs)
    ratios = (len(big) / k.LIM["topics_per_request"], chars / k.LIM["chars_per_request"],
              len(topics) / k.LIM["topics_per_socket"])
    return {"held": len(topics), "largest": len(big), "chars": chars, "binding": ratios.index(max(ratios))}


def copy_gaps() -> None:
    k.copy_gap(f'connection header "connected since {{t}}", "{{n}} reconnects in the last hour", "ping {{n}} ms": '
               f"§9 L{L9} names the fields, the deck has no strings")
    k.copy_gap(f'inspector column headings "Topic", "Last message", "Gaps", "Last resubscribe", "Last re-seed": '
               f"§9 L{L9} (topic row fields)")


def conn_header(total: int, s: int, *, served: bool = True) -> Node:
    f = figures(total, s)
    line1 = [k.text("label", k.w("W-45", None, s + 1), k.BODY_STRONG, k.TEXT_1),
             k.state_line("S-01", origin=False, name="state"),
             k.text("since", f"connected since {k.at(SINCE[s])}", k.BODY, k.TEXT_2),
             k.text("reconnects", "0 reconnects in the last hour", k.BODY, k.TEXT_2),
             k.text("ping", f"ping {PING[s]} ms", k.NUM, k.TEXT_2)]
    if served:
        line2: list[Node] = [k.text("largest", k.w("W-46", 0, f["largest"]), k.NUM, k.TEXT_1),
                             k.text("chars", k.w("W-46", 1, num(int(f["chars"]))), k.NUM, k.TEXT_1),
                             k.text("socket", k.w("W-46", 2, f["held"]), k.NUM, k.TEXT_1),
                             k.text("binding", k.w("W-47", int(f["binding"])), k.BODY_STRONG, k.TEXT_1)]
    else:
        line2 = [k.text("held", k.w("W-52", 1, f["held"]), k.NUM, k.TEXT_1),
                 k.not_connected("per-request figures", "D09-G3", both=False)]
    inner = k.INNER_W - 16
    cell = k.vbox("cell", [k.hbox("line-1", line1, {"gap": k.INSET_LG}, w=inner, h=20),
                           k.hbox("line-2", line2, {"gap": k.INSET_MD}, w=inner, h=20)],
                  {"padX": k.INSET_SM, "padY": k.INSET_SM, "gap": k.STACK_XS, "justify": "center"},
                  w=k.INNER_W, h=60)
    return k.hbox(f"row · socket {s + 1} header", [cell], {"fill": k.SUNKEN}, w=k.INNER_W, h=60,
                  note="connection header row (rowheader); label built by the page, never the served endpoint (R-7)")


def group_row(name: str, kind: str, n: int) -> Node:
    c = k.cell("group", [k.text("type", kind, k.BODY_STRONG, k.TEXT_1),
                         k.text("count", k.w("W-52", 1, n), k.CAPTION, k.TEXT_2)], k.INNER_W)
    return k.hbox(name, [c], {"fill": k.HOVER}, w=k.INNER_W, h=k.ROW_H, note="topic type group with its count")


def row_specs(total: int) -> list[tuple]:
    """Every row of the list in order: ("conn", s) · ("group", s, kind, n) · ("topic", s, kind, j, ti, topic, i)."""
    out: list[tuple] = []
    n_sym = SCALES[total][0]
    for s in range(CONNS):
        out.append(("conn", s))
        for kind, topics in socket(total, s):
            out.append(("group", s, kind, len(topics)))
            per = len(topics) // n_sym
            for i, t in enumerate(topics):
                out.append(("topic", s, kind, i // per, i % per, t, i))
    return out


def topic_row(spec: tuple, *, served: bool = True) -> Node:
    _t, s, kind, j, ti, topic, i = spec
    if served:
        gaps = 1 if (s == 1 and kind == "publicTrade" and j == 0) else 0
        cells = {"topic": topic, "age": k.w("W-48", 0, (j * 7 + ti) % 3), "gaps": k.w("W-48", 1, gaps),
                 "resub": k.w("W-48", 2, k.at(-(70 + 13 * j + 5 * s))),
                 "reseed": k.w("W-48", 3, k.at(-(200 + 37 * j + 11 * s)))}
        return k.table_row(COLS, cells, f"row · {topic}", i + 1)
    cells19 = {"topic": topic, **{c: k.not_connected("value", gid, w_=164, both=False) for c, gid in
                                  (("age", "D09-G3"), ("gaps", "D09-G3"), ("resub", "D09-G4"), ("reseed", "D09-G4"))}}
    return k.table_row(COLS19, cells19, f"row · {topic}", i + 1)


def build_rows(total: int, start: int, room: float, *, served: bool = True, limit: int | None = None) -> list[Node]:
    specs = row_specs(total)[start:]
    out, used = [], 0.0
    for sp in specs[:limit] if limit else specs:
        if used > room:
            break
        if sp[0] == "conn":
            r = conn_header(total, sp[1], served=served)
        elif sp[0] == "group":
            r = group_row(f"row · socket {sp[1] + 1} · {sp[2]}", sp[2], sp[3])
        else:
            r = topic_row(sp, served=served)
        out.append(r)
        used += k.est_height(r)
    return out


VIEWPORT_H = 512
ROOM = 560.0  # the view under the inspector's heading, disclosure and column headers (672 - about 112)


def start_of(total: int, s: int) -> int:
    return next(i for i, sp in enumerate(row_specs(total)) if sp == ("conn", s))


def inspector(total: int) -> tuple[Node, list[str]]:
    """Served form at `total` topic rows; returns the section and the frame's derived lines."""
    copy_gaps()
    specs = row_specs(total)
    head = k.disclosure(k.w("W-44", None, CONNS, total), open_=True)
    hdr = [k.header_row(COLS), k.rect("header rule", k.INNER_W, 1, k.BORDER)]
    figs = [figures(total, s) for s in range(CONNS)]
    lines = [f"{total} topic rows = {CONNS} sockets × {figs[0]['held']} topics "
             f"({SCALES[total][0]} symbols × {sum(len(p) for _t, p in SCALES[total][1])} topics); {len(specs)} "
             f"list rows with the connection and type rows"]
    lines += [f"socket {s + 1}: largest request {f['largest']} of 10 topics, {num(int(f['chars']))} characters "
              f"(compact JSON args of the request), {f['held']} of 500 on the socket: binding = the largest ratio "
              f"({k.w('W-47', int(f['binding']))})" for s, f in enumerate(figs)]
    if total <= k.LIM["virtualize_rows"]:
        rows = build_rows(total, 0, ROOM)
        lst = k.vbox("CMP-049 inspector list", [*hdr, *rows], {"gap": k.STACK_XS}, w=k.INNER_W,
                     note=f'role="table"; {total} topic rows, not virtualised (≤ 60, §9 L{k.L("- **Scale and")})')
        lines.append(f"Not virtualised: {total} ≤ 60 rows; {len(specs) - len(rows)} list rows below the view, "
                     "not drawn")
    else:
        sock = 1 if total == 120 else 2
        st = start_of(total, sock)
        rows = build_rows(total, st, VIEWPORT_H)
        thumb_h = max(24, round(VIEWPORT_H * len(rows) / len(specs)))
        thumb = k.rect("scroll thumb", 4, thumb_h, k.BORDER_STRONG, {"radius": k.R_BADGE}, x=k.INNER_W - 6,
                       y=round((VIEWPORT_H - thumb_h) * st / max(len(specs) - len(rows), 1)), abs=True)
        vp = fixed_box("grid viewport", [*rows, thumb], VIEWPORT_H,
                       note=f"virtualised window: aria-rowindex {st + 2} … {st + 1 + len(rows)}")
        lst = k.vbox("CMP-049 inspector grid", [*hdr, vp], {"gap": k.STACK_XS}, w=k.INNER_W,
                     note=f'role="grid" aria-rowcount="{len(specs) + 1}"; virtualised past 60 rows')
        lines.append(f"Virtualised: {total} > 60 rows (§9 L{k.L('- **Scale and')}); role grid, aria-rowcount "
                     f"{len(specs) + 1} (column headers + {len(specs)} rows); the view is scrolled to socket "
                     f"{sock + 1}, aria-rowindex {st + 2}; rows keyed connection + topic (T:95)")
    return k.section("Subscription inspector", [head, lst], waits=["D09-G3", "D09-G4"]), lines


def clock_section() -> Node:
    meas = k.hbox("measurement", [k.text("cadence", k.w("W-39", 0), k.BODY, k.TEXT_2),
                                  k.text("last", k.w("W-39", 1, k.at(-128), k.ago(128)), k.BODY, k.TEXT_2)],
                  {"gap": k.INSET_LG}, h=20)
    return k.section("Clock", [k.clock_ok_status(12), meas, k.button(k.w("W-35", 0))])


def actions_section() -> Node:
    return k.section("Actions", [k.button(k.w("W-50"))])


def history_closed() -> Node:
    return k.section("History", [k.disclosure(k.w("W-70"))])


# --- history (§14): one value per minute for the last hour, the per-minute peak in requests per second (illustrative)
H_ACCT, H_CLASS = k.ACCOUNTS[0], "order.create"
OSC = (0.0, 0.4, -0.4, 0.2, -0.2)


def series() -> list[int]:
    v = [min(8, max(3, round(3 + 5 * m / 59 + OSC[m % 5]))) for m in range(60)]
    v[0], v[-1] = 3, 8
    return v


def minute(m: int) -> str:
    """Minute m of the window (0 = oldest): 59 is the last whole minute before AS_OF (14:01)."""
    return k.at(-(int(k.AS_OF[-2:]) + 60 * (60 - m)))[:5]


def pickers(acct: str, cls: str, win: str) -> Node:
    heads = k.w("W-08").split(" · ")
    return k.hbox("pickers", [select_box(heads[1], acct, w_=160), select_box(heads[0], cls, w_=200),
                              k.segmented([k.w("W-71", i) for i in range(3)], win)],
                  {"gap": k.INSET_LG, "align": "end"}, h=52)


H_COLS = (k.Col("time", "Time", 120), k.Col("used", "Used (requests per second)", 240, True),
          k.Col("limit", "Limit (requests per second)", 240, True))


def history_open() -> tuple[Node, list[str]]:
    vals, lim = series(), k.LIM["order_per_s"]
    trend = k.w("W-72", None, H_CLASS, H_ACCT, vals[0], vals[-1])
    k.copy_gap(f'history table headings "Time", "Used (requests per second)", "Limit (requests per second)": §14 '
               f'L{k.L("- A disclosure \"Usage history\"")} ("Time, Used, Limit, unit in the header")')
    spark = k.sparkline(vals, w_=600, h=48, vmax=lim)
    spark["note"] = f'role="img" aria-label "{trend}"; scaled to the limit {lim} per second'
    rows = []
    used = 0.0
    for r, m in enumerate(range(59, -1, -1), 1):
        if used > 260:
            break
        row = k.table_row(H_COLS, {"time": minute(m), "used": str(vals[m]), "limit": str(lim)},
                          f"row · {minute(m)}", r)
        rows.append(row)
        used += k.est_height(row)
    tbl = k.table("CMP-049 history table", None, k.header_row(H_COLS), rows,
                  note="the sparkline's alternative: the same 60 values (§14); newest first")
    kids = [k.disclosure(k.w("W-70"), open_=True), pickers(H_ACCT, H_CLASS, k.w("W-71", 0)),
            k.text("as of", f"as of {k.AS_OF}", k.CAPTION, k.TEXT_3), spark,
            k.text("trend label", trend, k.BODY, k.TEXT_1), k.disclosure(k.w("W-71", 3), open_=True), tbl]
    lines = [f"Series: 60 per-minute peaks {minute(0)}–{minute(59)} (the last whole minute before as of "
             f"{k.AS_OF}); first {vals[0]}, last {vals[-1]}, max {max(vals)} ≤ the limit {lim} per second, so W-72 "
             f'reads "rising, {vals[0]} to {vals[-1]}" (the spec\'s 12 to 41 would pass order.create\'s 10 / s limit)',
             f"Table: newest first, {len(rows)} of 60 rows in the view, the rest below; same values as the sparkline",
             "Fetched on open and on a window change, never on the 1 Hz sample (§14); as of = the fetch"]
    return k.section("History", kids, waits=["D09-G9"]), lines


def history_empty() -> Node:
    kids = [k.disclosure(k.w("W-70"), open_=True), pickers(k.ACCOUNTS[2], "order.amend", k.w("W-71", 1)),
            k.text("as of", f"as of {k.AS_OF}", k.CAPTION, k.TEXT_3),
            k.text("empty", k.w("W-73"), k.BODY, k.TEXT_1)]
    return k.section("History", kids, waits=["D09-G9"])


def history_s19() -> Node:
    return k.section("History", [k.disclosure(k.w("W-70"), open_=True),
                                 k.not_connected("history · S-19", "D09-G9", w_=k.INNER_W)], waits=["D09-G9"])


def inspector_s14() -> Node:
    st = k.state_line("S-14", [k.w("W-30", 1)], origin=False, w_=k.INNER_W, name="state · S-14")
    return k.section("Subscription inspector", [k.disclosure(k.w("W-44", None, 0, 0), open_=True), st])


def inspector_s19() -> Node:
    copy_gaps()
    rows = build_rows(120, 0, 1e9, served=False, limit=4)
    lst = k.vbox("CMP-049 inspector list", [k.header_row(COLS19), k.rect("header rule", k.INNER_W, 1, k.BORDER),
                                            *rows], {"gap": k.STACK_XS}, w=k.INNER_W,
                 note="S-19: the planner figures, gaps, resubscribe and re-seed are not in a read (§9)")
    return k.section("Subscription inspector", [k.disclosure(k.w("W-44", None, CONNS, 120), open_=True), lst],
                     waits=["D09-G3", "D09-G4"])


FILL_A, FILL_B = 1500, 2100  # nominal heights of the sections above (scrolled out of view)
LBL_A = "sections 2 to 4 (summary strip, Rate budgets, Fan-out simulator), scrolled out of view"
LBL_B = "sections 2 to 7 (summary strip to Actions), scrolled out of view"


def tail() -> list[Node]:
    return [clock_section(), actions_section()]


def build(theme: str = "dark") -> tuple[list[Node], Node]:
    fids = [f for f, _s in k.frames_of(NN)]
    frames, blocks = [], []
    kb6 = "Enter / Space on the disclosure; the grid is one Tab stop; arrows, PageUp / PageDown, Home / End (SCR-147-KB-6)"
    for fid, total in zip(fids[:3], (36, 120, 480)):
        sec, lines = inspector(total)
        frames.append(k.window(fid, theme, [filler(LBL_A, FILL_A), sec, *tail(), history_closed()],
                               scroll=scroll_to(FILL_A)))
        blocks.append(k.frame_block(fid, waits=["D09-G3", "D09-G4"], keyboard=kb6, lines=[
            "Served form (D09-G3, D09-G4 assumed served); its S-19 form is the last frame", *lines,
            "Connection state word: S-01's (§9: \"the state word (§5)\"; the register has no connected-socket word)",
            cite(["W-44", "W-45", "W-46", "W-47", "W-48", "W-52", "W-13", "W-29", "W-39", "W-35", "W-50", "W-70"])]))
    frames.append(k.window(fids[3], theme, [filler(LBL_A, FILL_A), inspector_s14(), *tail(), history_closed()],
                           scroll=scroll_to(FILL_A)))
    blocks.append(k.frame_block(fids[3], keyboard=kb6, lines=[
        f"A served inspector read with zero topics: W-44 reads 0 connections, 0 topics (a measured zero, R-2); never "
        f'a bare "No data" (§9 L{k.L("- **Empty:**")})', cite(["W-44", "W-30", "W-29", "W-39", "W-35", "W-50", "W-70"])]))
    hsec, hlines = history_open()
    frames.append(k.window(fids[4], theme, [filler(LBL_B, FILL_B), hsec], scroll=scroll_to(FILL_B)))
    blocks.append(k.frame_block(fids[4], waits=["D09-G9"], keyboard="Enter / Space on each disclosure; arrows in the "
                                "window control (SCR-147-KB-5); the table is the hover's keyboard path (SCR-147-PP-4)",
                                lines=["Served form (D09-G9 assumed served); its S-19 form is the last frame", *hlines,
                                       cite(["W-70", "W-08", "W-71", "W-72"])]))
    frames.append(k.window(fids[5], theme, [filler(LBL_B, FILL_B), history_empty()], scroll=scroll_to(FILL_B)))
    blocks.append(k.frame_block(fids[5], waits=["D09-G9"], keyboard="as the history frame", lines=[
        f"Scalp, order.amend, {k.w('W-71', 1)}: no usage recorded; W-73, never 0 (R-2)",
        cite(["W-70", "W-08", "W-71", "W-73"])]))
    frames.append(k.window(fids[6], theme, [filler(LBL_A, FILL_A), inspector_s19(), *tail(), history_s19()],
                           scroll=scroll_to(FILL_A)))
    blocks.append(k.frame_block(fids[6], waits=["D09-G3", "D09-G4", "D09-G9"], keyboard=kb6, lines=[
        f"Each unserved cell shows S-19 with its G-row (§9 L{k.L('- **Not served:**')}; §14 "
        f"L{k.L('- **Source:** no history read')}); served forms: the inspector frames and the history frame",
        "The connection rows, topics held and the topic list stay (GET /recording/status per connection, §2.4); "
        "4 list rows drawn, the rest below", cite(["W-44", "W-45", "W-52", "W-05", "W-13", "W-29", "W-39", "W-35",
                                                    "W-50", "W-70"])]))
    ann = k.annotations(NN, blocks, board_lines=[
        f"Each frame scrolls the page so its section leads the view; one clock: as of {k.AS_OF}",
        "§0's \"the last past the threshold\": 120 is past 60 too (§9); both 120 and 480 are drawn virtualised"])
    return frames, ann


def main() -> int:
    frames, ann = build(k.BOARDS[NN].theme)
    k.live("inspector frames: read back the disclosure labels 'Subscriptions (3 connections, 36 topics)', "
           "'(… 120 topics)', '(… 480 topics)' and each socket header's 'Binding: topics per request'")
    k.live("each frame: the drawn section's top sits at about y 16 in the main column (scroll offset in its note); "
           "if not, set the page's y so it does")
    k.live("history frame: 60 sparkline marks, the tallest 8 of 10 (scaled to the limit); the table's first row is "
           f"{minute(59)} with {series()[-1]}")
    k.live("120 and 480 frames: the grid viewport is 512 px high and clips; the scroll thumb sits inside it")
    p = k.write_sheet(NN, frames, ann)
    md = k.write_md(NN, p)
    packed = k.pack_sheet(p)
    print(p, md, packed, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
