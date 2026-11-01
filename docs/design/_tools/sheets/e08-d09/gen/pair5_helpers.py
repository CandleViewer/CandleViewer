"""Pair E helpers (boards 04 ws-states and 06 simulator-budget): copy tracking per frame, the shared world, the
summary strip, the inspector's connection rows, the Actions section, the budgets table, the simulator and the one
dialog style both boards share (k.dialog). Every string comes from the spec through cw() (§15) or gap() (spec prose,
its line looked up with k.L(), never typed)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e08d09kit as k  # noqa: E402

Node = dict[str, Any]
USED: list[str] = []


def start() -> None:
    """A new frame: clear the copy cites."""
    USED.clear()


def _cite(tag: str) -> None:
    if tag not in USED:
        USED.append(tag)


def cw(key: str, piece: int | None = None, *vals: Any) -> str:
    """k.w() plus a per-frame cite "W-n L<line>"."""
    s = k.w(key, piece, *vals)
    _cite(f"{key} L{k.COPY[key].line}")
    return s


def gap(chars: str, needle: str, where: str) -> str:
    """A string the deck lacks, taken from the spec's prose at the line holding `needle` (looked up)."""
    ln = k.L(needle)
    k.copy_gap(f'"{chars}": {where}, from the spec prose at L{ln} (not in §15)')
    _cite(f'"{chars}" L{ln}')
    return chars


def copy_line() -> str:
    return "Strings on this frame (spec line): " + "; ".join(USED)


def h2(name: str) -> str:
    """A section h2: §2.2's anatomy names (kit reading, build-notes ambiguity 7)."""
    return gap(name, f"**{name}.**", "section h2, §2.2 anatomy")


# --- the one illustrative world (AS_OF 14:02:11; every time derived with k.at)
SOCKETS = 3
TOPICS_PER_SOCKET = 40
TOPICS = SOCKETS * TOPICS_PER_SOCKET  # 120 (W-44, W-52)
SINCE_S = 4660  # sockets connected since AS_OF - 4660 s
PING_MS = (18, 21, 19)
LIM = k.LIM["order_per_s"]  # 10 requests per second (§3.2 documented default)
RESERVE = 2  # requests per account per 1 s window (served-form assumption, D09-G14)
USED_NOW = {"Main": 3, "Swing": 1, "Scalp": 4, "Hedge": 2, "Desk": 0}
BUDGET_MIN = 100  # Main's request budget per minute (our setting, D09-G8); the reserve is kept out of it (W-64)
ALLOWED = (60, 420)  # W-61's own figures, read from the server
VIEW_AS = "Sam"  # kit alias for W-74's {user} (no sample in §15)


def tiles(public: Node | None = None, *, public_sid: str = "S-01", extra: list[Node] | None = None) -> Node:
    """The five CMP-178 tiles (§2.2 item 2). Public market data carries the frame's connection state."""
    tw = k.tile_widths()
    inner = tw[1] - 2 * k.PX[k.INSET_LG]
    num = cw("W-52", None, SOCKETS, TOPICS)
    ex = list(extra or [])
    act = k.origin_action(public_sid)
    if act:
        _cite(f"W-12 L{k.COPY['W-12'].line}")
        ex.append(k.text("action line", act, k.CAPTION, k.TEXT_2, w=inner))
    pub = public or k.tile(k.TILE_HEADINGS[1], public_sid, num, w_=tw[1], extra=ex)
    for t in k.TILE_HEADINGS:
        gap(t, "**Summary strip.**", "tile heading")
    _cite(f"W-29 L{k.COPY['W-29'].line}")
    _cite(f"W-05 L{k.COPY['W-05'].line}")
    return k.summary_strip([
        k.tile(k.TILE_HEADINGS[0], None, None, w_=tw[0], gid="D09-G1"), pub,
        k.tile(k.TILE_HEADINGS[2], None, None, w_=tw[2], gid="D09-G1"),
        k.tile(k.TILE_HEADINGS[3], None, None, w_=tw[3], status=k.clock_ok_status(12)),
        k.tile(k.TILE_HEADINGS[4], "S-01", None, w_=tw[4])])


def strip_inner() -> int:
    return k.tile_widths()[1] - 2 * k.PX[k.INSET_LG]


# --- the inspector's connection header rows (§9: label W-45, the state word, topics held, connected since,
# reconnects in the last hour, last ping in ms). Topic groups and topic rows are board 07's.
_CONN_NEEDLE = "**Connection header row:**"
CONN_COLS = (k.Col("conn", "Connection", 228), k.Col("state", "State", 220), k.Col("topics", "Topics held", 88, True),
             k.Col("since", "Connected since", 120, True), k.Col("reconn", "Reconnects in the last hour", 184, True),
             k.Col("ping", "Last ping", 104, True))
assert sum(c.w for c in CONN_COLS) == k.INNER_W


def conn_header() -> Node:
    for c in CONN_COLS[1:]:
        gap(c.label, _CONN_NEEDLE, "connection header column (§9's field list)")
    _cite(f"W-45 L{k.COPY['W-45'].line} (Connection column holds W-45's label)")
    return k.header_row(CONN_COLS)


STATE_W = CONN_COLS[1].w - 2 * k.PX[k.INSET_SM]  # 232


def conn_state(sid: str, chars: str | None = None, figures: tuple[str, ...] = ()) -> Node:
    """A connection row's state cell: origin label, glyph, then `chars` (a W-n form that begins with the register's
    word, e.g. W-18's long form) or the register word with figures (k.state_line)."""
    if chars is None:
        return k.state_line(sid, list(figures), origin=sid != "S-01", w_=STATE_W, name=f"state · {sid}")
    st = k.REGISTER[sid]
    word = k.state_word(sid)
    if not chars.startswith(word):
        raise ValueError(f"{chars!r} does not begin with {sid}'s word {word!r}")
    kids = [k.text("origin", k.origin_label(sid), k.CAPTION, k.TEXT_2), k.glyph(st.glyph, k.tone_color(sid)),
            k.text("word", chars, k.BODY_STRONG, k.TEXT_1,
                   **({"w": STATE_W - 80} if k.text_w(chars, k.BODY_STRONG) > STATE_W - 80 else {}))]
    return k.hbox(f"state · {sid}", kids, {"gap": k.INSET_XS, "wrap": "wrap"}, w=STATE_W,
                  note=f"{sid} {st.state}: the glyph is aria-hidden beside its word")


def conn_row(i: int, state: Node, *, since: str, reconn: int, ping: int, old: str | None = None) -> Node:
    """Socket i's header row. old = a data-confidence kind ("disconnected", "reconnecting"): its old values bind
    color.data-confidence.<kind>.text (§16)."""
    label = cw("W-45", None, i)
    cells = {"conn": label, "state": state, "topics": str(TOPICS_PER_SOCKET), "since": since,
             "reconn": str(reconn), "ping": f"{ping} ms"}
    colors = ({c: f"{k.DC}.{old}.text" for c in ("topics", "since", "reconn", "ping")} if old else None)
    return k.table_row(CONN_COLS, cells, f"row {i:02d} · socket {i}", i, colors=colors)


def healthy_row(i: int) -> Node:
    return conn_row(i, conn_state("S-01"), since=k.at(-SINCE_S), reconn=0, ping=PING_MS[i - 1])


def inspector(rows: list[Node], *, open_: bool = True, waits: tuple[str, ...] = ("D09-G3",)) -> Node:
    """§9: the disclosure W-44 (closed by default; open on the WS-state frames to show the connection rows)."""
    disc = k.disclosure(cw("W-44", None, SOCKETS, TOPICS), open_=open_)
    kids: list[Node] = [disc]
    if open_:
        kids.append(k.table("CMP-049 connections", None, conn_header(), rows,
                            note="grouped by connection (§9); topic groups and rows are board 07's"))
    return k.section(h2("Subscription inspector"), kids, waits=list(waits))


def reconnect_trigger(*, focused: bool = False) -> Node:
    return k.button(cw("W-50"), "secondary", focused=focused, name="Reconnect market data (trigger)")


def private_placeholder() -> Node:
    """§11: the private stream per account, a placeholder row with its own confirm text (W-53) and S-19."""
    lab = cw("W-53", 0, k.ACCOUNTS[0])
    return k.hbox("private stream placeholder · Main", [
        k.text("label", lab, k.BODY, k.TEXT_2), k.not_connected("value", "D09-G1", both=False)],
        {"gap": k.INSET_MD}, h=k.CONTROL_H, note=f'confirm text W-53: "{k.w("W-53", 1)}"')


def actions(trigger: Node, extra: list[Node] | None = None) -> Node:
    return k.section(h2("Actions"), [trigger, *(extra or [])], waits=["D09-G7"])


def fit_scroll(sections: list[Node], margin: int = 8) -> int:
    """The scroll that brings the last section's end into the 672 px view (0 when the page fits)."""
    page = k.vbox("probe", [k.band(), k.rule(), k.page_header(), *sections], {"gap": k.STACK_LG}, w=k.INNER_W)
    need = k.est_height(page)
    return 0 if need <= k.VIEW_H else int(need - k.VIEW_H + margin)


# --- the one dialog style both boards share (k.dialog: CMP-044 standard, alertdialog, [Cancel] focused first)
DIALOG_IW = k.DIALOG_W - 2 * k.PX[k.DIALOG_PAD]  # 512


def contract_mark(gid: str) -> Node:
    return k.text("contract-first", "Waits on " + k.g(gid), k.CAPTION, k.TEXT_3, w=DIALOG_IW,
                  note="§0: a section waiting on a G-row is marked with it; the dialog is contract-first")


def cancel(*, focused: bool) -> Node:
    return k.button(gap("Cancel", "[Cancel] (focus)", "dialog button"), "secondary", focused=focused,
                    name="button · Cancel")


def reconnect_dialog() -> Node:
    """§11: title W-50, five consequences W-51 then W-56 last, blast radius W-52, step-up W-54, audit marker W-55 as
    the last line before the buttons; [Cancel] (focus) [Reconnect market data]."""
    cons = [cw("W-51", i) for i in range(5)] + [cw("W-56")]
    body = [contract_mark("D09-G7"),
            k.lines_block("consequences (W-51, W-56)", cons, w_=DIALOG_IW),
            k.text("blast radius (W-52)", cw("W-52", None, SOCKETS, TOPICS), k.BODY_STRONG, k.TEXT_1,
                   note="fetched before render; confirm enabled once the counts loaded"),
            k.text("step-up (W-54)", cw("W-54"), k.BODY, k.TEXT_2),
            k.text("audit marker (W-55)", cw("W-55"), k.CAPTION, k.TEXT_2, note="CMP-093 marker; code withheld")]
    return k.dialog(cw("W-50"), body, [cancel(focused=True), k.button(cw("W-50"), "primary",
                                                                       name="button · confirm")],
                    name="CMP-044 dialog · Force reconnect")


def budget_dialog(*, value: str, refused: bool = False) -> Node:
    """§12: rung 1; the current value, a new-value field with its unit, W-61 allowed range, W-62, the four W-64
    invariants, W-54, the W-63 marker; [Cancel] (focus) [Save budget]. refused: the field keeps the value, the
    server's mapped reason under it (CMP-027), focus kept in the field (SCR-147-T2-4)."""
    acct = k.ACCOUNTS[0]
    unit = gap("requests per minute", "Allowed: {60} to {420} requests per minute", "the field's unit (W-61's unit)")
    cur = gap("Current value", "the current value, a new-value field", "label of the current value")
    newv = gap("New value", "the current value, a new-value field", "label of the new-value field")
    reason = None
    if refused:
        reason = gap("{mapped reason}", "Not reconnected · {mapped reason}",
                     "the server's mapped reason (§12) has no string; drawn as W-59's own slot")
    body = [contract_mark("D09-G8"),
            k.kv_row("current value", cur, f"{BUDGET_MIN} {unit}", w_=DIALOG_IW, label_w=160, numeric=True),
            k.number_field(newv, value, unit=unit, w_=240, focused=refused, error=reason),
            k.text("allowed (W-61)", cw("W-61", None, *ALLOWED), k.BODY, k.TEXT_2, w=DIALOG_IW),
            k.text("effect (W-62)", cw("W-62", None, acct), k.BODY, k.TEXT_1, w=DIALOG_IW),
            k.lines_block("invariants (W-64)", [cw("W-64", i) for i in range(4)], w_=DIALOG_IW),
            k.text("step-up (W-54)", cw("W-54"), k.BODY, k.TEXT_2),
            k.text("audit marker (W-63)", cw("W-63"), k.CAPTION, k.TEXT_2, w=DIALOG_IW)]
    title = gap("Change budget", "\"Change budget…\" (W-60)", "dialog title: W-60 without its ellipsis")
    save = gap("Save budget", "[Save budget]", "dialog confirm")
    return k.dialog(f"{title} · {acct}", body, [cancel(focused=not refused),
                                                k.button(save, "primary", name="button · Save budget")],
                    name="CMP-044 dialog · Change budget")


# --- the per-class table for board 06 (served form: D09-G1 and D09-G14 assumed served; Main..Desk order.create)
def budget_rows(*, focus_main: bool = False) -> list[Node]:
    rows = []
    for i, acct in enumerate(k.ACCOUNTS, 1):
        used = USED_NOW[acct]
        head = k.headroom(LIM, used, RESERVE)[0]
        rows.append(k.table_row(k.BUDGET_COLS, {
            "class": "order.create", "account": acct, "limit": f"{LIM} / s", "used": str(used), "window": "1 s",
            "headroom": k.headroom_cell(LIM, used, RESERVE),
            "meter": k.meter(used, LIM, valuetext=k.w("W-09", None, used, LIM, head)),
            "state": k.state_line("S-01", origin=False, w_=160), "action": k.row_action(focused=focus_main and i == 1)},
            f"row {i:02d} · order.create · {acct}", i, second={"class": "order"}))
    _cite(f"W-09 L{k.COPY['W-09'].line}")
    _cite(f"W-13 L{k.COPY['W-13'].line}")
    return rows


def budgets(*, focus_main: bool = False) -> Node:
    tbl = k.table("CMP-049 budgets", cw("W-07"), k.budget_header(), budget_rows(focus_main=focus_main))
    _cite(f"W-08 L{k.COPY['W-08'].line}")
    _cite(f"W-06b L{k.COPY['W-06b'].line}")
    band_ = k.reserve_band([(a, RESERVE) for a in k.ACCOUNTS], label_w=288)  # live SHEET-FIX: label 288, value 656
    return k.section(h2("Rate budgets"), [tbl, band_], waits=["D09-G1", "D09-G14"])


# --- the fan-out simulator (§8): inputs live; output S-19 (D09-G10) or the served result
_OUT = "- **Output** (a CMP-049 table"
SIM_COLS = (k.Col("account", "Account", 200), k.Col("requests", "Requests", 160, True),
            k.Col("share", "Share of spendable budget", 240, True), k.Col("outcome", "Outcome", 344))
assert sum(c.w for c in SIM_COLS) == k.INNER_W
LEGS_ENTRY, LEGS_TP, SL_COST = 1, 1, 1  # a bracket: 1 entry + 1 take-profit + a separate stop (sl_cost 1, §7)
PER_ACCOUNT = LEGS_ENTRY + LEGS_TP + SL_COST  # 3: §7's "1 + sl_cost" (entry + separate stop) + 1 take-profit
IP_LIMIT = k.LIM["ip_per_5s"]  # 600 per 5 s
DEFERRED = ("Hedge", "Desk")  # best effort: these two have under 3 spendable requests left this minute (illustrative)


def sim_inputs(*, focus_estimate: bool = False, policy: str = "best") -> list[Node]:
    lab = [cw("W-41", i) for i in range(8)]
    accts = k.vbox("accounts", [k.text("label", lab[0], k.LABEL, k.TEXT_2),
                                k.hbox("checkbox list", [k.checkbox(a, checked=True) for a in k.ACCOUNTS],
                                       {"gap": k.INSET_LG}, h=24)], {"gap": k.STACK_XS},
                   note="a checkbox list of the Owner's accounts by alias, never typed ids (§8)")
    seg = k.vbox("fan-out policy", [k.text("label", lab[4], k.LABEL, k.TEXT_2),
                                    k.segmented([lab[5], lab[6]], lab[6] if policy == "best" else lab[5])],
                 {"gap": k.STACK_XS})
    sl = k.vbox("stop-loss (static)", [k.text("label", lab[3], k.BODY_STRONG, k.TEXT_1)], {"gap": k.STACK_XS},
                note="static text, not a control (C-2.6); no 'without stop' option, no sl_cost field (§7 item 3)")
    row = k.hbox("legs and policy", [k.number_field(lab[1], str(LEGS_ENTRY)), k.number_field(lab[2], str(LEGS_TP)),
                                     sl, seg], {"gap": k.INSET_LG, "align": "end"})
    est = k.button(lab[7], "primary", focused=focus_estimate, name="button · Estimate cost")
    return [accts, row, est]


def sim_result() -> list[Node]:
    n = len(k.ACCOUNTS)
    total = n * PER_ACCOUNT
    share = k.pct(PER_ACCOUNT, BUDGET_MIN)
    line = cw("W-40", None, n, total, share)
    heads = [gap(c.label, _OUT, "simulator output column") for c in SIM_COLS[1:]]
    del heads
    rows = []
    for i, a in enumerate(k.ACCOUNTS, 1):
        ok = a not in DEFERRED
        word = cw("W-42", 0 if ok else 1)
        out = k.hbox("outcome", [k.icon("glyph", "check" if ok else "pending", k.OK_STRONG if ok else k.WARN_STRONG),
                                 k.text("word", word, k.BODY_STRONG, k.TEXT_1)], {"gap": k.INSET_XS})
        rows.append(k.table_row(SIM_COLS, {"account": a, "requests": str(PER_ACCOUNT), "share": f"{share} %",
                                           "outcome": out}, f"row {i:02d} · {a}", i))
    ip_lab = gap("Shared IP bucket", "plus one line for the shared IP bucket", "the IP bucket line's label")
    ip_share = f"{100 * total / IP_LIMIT:.1f} %"
    ip = k.text("IP bucket line", f"{ip_lab} · {total} of {IP_LIMIT} requests per 5 s · {ip_share}", k.NUM, k.TEXT_1)
    tbl = k.table("CMP-049 simulator result", None, k.header_row(SIM_COLS), rows)
    return [k.text("result line (W-40)", line, k.BODY_STRONG, k.TEXT_1, w=k.INNER_W), tbl, ip]


def sim_announce() -> str:
    """SCR-147-SR-11's line (W-42's last piece), for the annotation: the shell's polite region, not the page."""
    served = [a for a in k.ACCOUNTS if a not in DEFERRED]
    return cw("W-42", 3, len(served), len(DEFERRED))


def simulator(*, served: bool) -> Node:
    kids = sim_inputs(focus_estimate=served)
    kids += sim_result() if served else [k.not_connected("output (S-19)", "D09-G10", w_=k.INNER_W)]
    return k.section(h2("Fan-out simulator"), kids, waits=["D09-G10"])


# --- T2 view-as forms (§17.5 T2-1, T2-2; W-74): the lock leads the full label, the reason under it
def row_menu_t2(x: int, y: int) -> Node:
    """SCR-147-T2-2 rendering 2a in the row menu: the item's second line is the reason; focus kept on the item."""
    item = k.hbox("item · Change budget… (T2)", [k.icon("lock", "locked", k.TEXT_3),
                                                 k.text("label", cw("W-60"), k.BODY_STRONG, k.TEXT_3)],
                  {"gap": k.INSET_XS}, h=24)
    body = k.vbox("item (aria-disabled)", [item, k.text("second line", cw("W-74", None, VIEW_AS), k.CAPTION,
                                                        k.TEXT_2)],
                  {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS, "radius": k.R_CONTROL,
                   "fill": k.HOVER}, note='aria-disabled="true"; reason by aria-describedby; focus kept on the item')
    menu = k.vbox("row menu · Main", [k.ring(body)], {"pad": k.INSET_XS, "fill": k.OVERLAY, "radius": k.R_CARD,
                                                      "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                      "strokeAlign": "inner"}, x=x, y=y, w=264)
    return k.box("row menu overlay", [menu], None, w=k.FRAME_W, h=k.FRAME_H, x=0, y=0, abs=True)
