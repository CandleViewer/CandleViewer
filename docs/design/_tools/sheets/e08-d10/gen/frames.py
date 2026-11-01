"""The frame builders of the nine boards, keyed by the §H frame id without its theme ("backfill/known-target").
Each builder takes the full §H id ("backfill/known-target · light") and returns (frame, annotation block); a twin board
calls the same builder with its own id, so its frames are its base board's, same values (sheets are theme-free)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e08d10kit as k  # noqa: E402

Built = tuple[dict, tuple[str, list[str]]]
BUILDERS: dict[str, Callable[[str], Built]] = {}


def builder(base: str) -> Callable[[Callable[[str], Built]], Callable[[str], Built]]:
    def deco(fn: Callable[[str], Built]) -> Callable[[str], Built]:
        BUILDERS[base] = fn
        return fn
    return deco


def header_h(title_node: dict, status: list, w_: int = k.PANEL_W) -> int:
    probe = k.panel("probe", title_node, status, [], w_=w_, h=2000)
    return probe["kids"][0]["h"]


def hist_panel(status: list, *, bars_k: int = 40, skip: tuple[int, ...] = (), hole_at: int | None = None,
               hole_node: dict | None = None, footer: str | None, h: int = k.PANEL_H, w_: int = k.PANEL_W,
               title_node: dict | None = None, name: str = "host panel · E08 history panel") -> dict:
    """The generic E08 history panel (§H): title, the status slot, the column header row and the newest rows."""
    t = title_node or k.title(k.history_title())
    room = h - header_h(t, status, w_) - 1 - (k.ROW_H if footer else 0)
    body = k.history_body(k.latest(bars_k, skip=skip), hole_at=hole_at, hole_node=hole_node, room=room, total=w_)
    return k.panel(name, t, status, body, w_=w_, h=h, footer=footer)


def block_panel(blk: dict, *, h: int = k.PANEL_H, status: list | None = None,
                name: str = "host panel · E08 history panel (no rows)") -> dict:
    """The panel with no row: the column header row kept (E11-D04's empty form), the CMP-026 block centred."""
    t = k.title(k.history_title())
    return k.panel(name, t, status or [], [k.header_row(k.hist_cols()), blk], h=h, center_last=True)


def below(panel_node: dict, marker: dict, *, gap: int = 8) -> list[dict]:
    """The panel at (16, 16) and a board marker under it (the panel's h leaves the room)."""
    return [dict(panel_node, x=16, y=16), dict(marker, x=16, y=16 + panel_node["h"] + gap)]


MARK_H = 64  # room under a shortened panel for one board marker (hidden string or focus-order strip)


# --- board 01: backfill-in-progress (§3)
@builder("backfill/known-target")
def known_target(fid: str) -> Built:
    n = k.N_FULL
    blk = k.block(k.w("W-1"), [k.w("W-2")], progress=k.bar(n), value=k.w3(n), actions=[k.show_coverage()],
                  name="CMP-026 EmptyState · backfill-in-progress")
    fr = k.window(fid, block_panel(blk), proposed=True)
    return fr, k.frame_block(fid, cites=[("V3", "Surface", 0), ("V3", "Copy", 0), ("V3", "Tokens", 0),
                                         ("V3", "Keyboard and focus", 0)],
                             lines=[f"n = {k.grp(n)} bars of this episode, m = {k.grp(k.TARGET)}: the panel's own "
                                    f"window holds no row yet (kit reading, build-notes ambiguity 1)",
                                    f"bar fill {round((k.BLOCK_W - 48) * n / k.TARGET)} of {k.BLOCK_W - 48} px = "
                                    f"n / m; aria-valuetext = the visible words (§3)", "PROPOSED fields (R-7)"])


@builder("backfill/open-target")
def open_target(fid: str) -> Built:
    n = k.N_FULL
    blk = k.block(k.w("W-1"), [k.w("W-2")], progress=k.spinner_words(k.w4(n)), actions=[k.show_coverage()],
                  name="CMP-026 EmptyState · backfill-in-progress · open target")
    fr = k.window(fid, block_panel(blk), proposed=True)
    return fr, k.frame_block(fid, cites=[("V3", "Surface", 0), ("V3", "Copy", 0)],
                             lines=[f"No target known: CMP-038 kind=\"load\" carries W-4; no progressbar exists "
                                    f"(D10-C5, L{k.L('`aria-valuetext` equals the visible words')})",
                                    f"W-4's date = the oldest of the {k.grp(n)} bars loaded ({k.ts(k.oldest(n).t)})",
                                    "PROPOSED fields (R-7)"])


@builder("backfill/in-context")
def in_context(fid: str) -> Built:
    n = k.N_CONTEXT
    st = [k.bf_chip(), k.words("progress words", k.w3(n))]
    fr = k.window(fid, hist_panel(st, footer=k.loaded_caption(n)), proposed=True)
    return fr, k.frame_block(fid, cites=[("V3", "Surface", 1), ("V3", "Copy", 1), ("V3", "Tokens", 1),
                                         ("V3", "Announcement", 1)],
                             lines=[f"Rows: the newest {k.INTERVAL_MIN}-min bars to {k.hhmm(k.NOW_OPEN)} UTC "
                                    f"{k.day(k.NOW_OPEN)}; caption {k.grp(n)} bars loaded = W-3's n",
                                    "No bar, no overlay, no scrim over the rows (R-1)", "PROPOSED fields (R-7)"])


@builder("backfill/cut")
def cut(fid: str) -> Built:
    p = hist_panel([], footer=k.loaded_caption(k.TARGET), h=k.PANEL_H - MARK_H)
    mk = k.hidden(f'role="status" (polite): {k.w("W-5")}', w_=480, name="visually hidden · status region")
    fr = k.window(fid, below(p, mk))
    return fr, k.frame_block(fid, lines=[
        f"The cut (T-3, L{k.L('| T-3 |')}): {k.TIMING['T-3'][3]}",
        f"Status slot empty: the chip leaves at the cut; caption {k.grp(k.TARGET)} = the target reached "
        f"(oldest bar {k.ts(k.oldest(k.TARGET).t)})",
        f"W-5 is announced only because W-1 was (§10.2 Coalescing, L{k.L('**Coalescing.**')})",
        f"Analytics: {k.plain(k.V3['Analytics'][1])}"])


# --- board 02: backfill-throttled (§4); the in-context frame is SCR-053's header (§H, D10-Q3)
def throttled_status(*, owner: bool, focused_partial: bool = False) -> list:
    st = [k.bf_chip(), k.words("throttled line (W-6)", k.w("W-6")), k.partial_chip(k.N_CONTEXT,
                                                                                    focused=focused_partial)]
    return st + ([k.owner_link()] if owner else []) + [k.show_coverage()]


@builder("throttled/in-context")
def thr_in_context(fid: str) -> Built:
    st = throttled_status(owner=True)
    t = k.title(k.tape_title())
    room = k.PANEL_H - header_h(t, st) - 1
    p = k.panel("host panel · SCR-053 tape", t, st, k.tape_body(room))
    fr = k.window(fid, p, proposed=True)
    return fr, k.frame_block(fid, cites=[("V4", "Surface", 1), ("V4", "Copy", 1), ("V4", "Roles", 1),
                                         ("V4", "Announcement", 1)],
                             lines=["Host: SCR-053's header (§H; BQ-6 narrowed by D10-Q3); S15 and S16 kept "
                                    "(D10-Q2); Owner session: W-9 present",
                                    f"Partial chip: {k.grp(k.N_CONTEXT)} bars back to {k.back_to(k.N_CONTEXT)}: W-7's "
                                    f"words as ruled, on the tape too (build-notes ambiguity 2)",
                                    "No spinner anywhere on the throttled path (BQ-9; D10-C6)",
                                    "PROPOSED fields (R-7)"])


@builder("throttled/long-wait")
def thr_long_wait(fid: str) -> Built:
    fr = k.window(fid, hist_panel(throttled_status(owner=True), footer=k.loaded_caption(k.N_CONTEXT)), proposed=True)
    return fr, k.frame_block(fid, lines=[
        f"The long wait (L{k.L('**The long wait.**')}): the words never count seconds (R-3); after T-6 "
        f"({k.TIMING['T-6'][1]}) nothing changes: the same words and numbers as the first hold-back",
        f"W-6 announced once per episode, never per retry; max_rate {k.ANNOUNCE[2][1][3]} (§10.2 L{k.ANNOUNCE[2][0]})",
        f"Analytics: {k.plain(k.V4['Analytics'][1])}", "PROPOSED fields (R-7)"])


@builder("throttled/gave-up")
def thr_gave_up(fid: str) -> Built:
    st = [k.partial_chip(k.N_CONTEXT), k.gave_up_line(), k.owner_link(), k.show_coverage()]
    fr = k.window(fid, hist_panel(st, footer=k.loaded_caption(k.N_CONTEXT)), proposed=True)
    return fr, k.frame_block(fid, cites=[("V4", "Copy", 1), ("V4", "Keyboard and focus", 1)], lines=[
        "After give-up (PROPOSED backfill.state = failed): no backfilling chip; W-8's words then Retry (CMP-001 "
        "secondary, an ungated read, R-5)",
        "Order in the slot = the focus order: the Partial chip, Retry, the Owner's link, Show coverage (§10.1)",
        f"The hole older than the loaded rows has no rows around it: no separator row on screen (§6); the full-panel "
        f"give-up (W-18) is board 06's a11y/retry-focus reading (§4 L{k.L('With no row loaded, the give-up keeps')})",
        "PROPOSED fields (R-7)"])


@builder("throttled/owner-vs-manager")
def thr_owner_vs_manager(fid: str) -> Built:
    each = (k.PANEL_H - 2 * 20 - 16) // 2
    nodes, y = [], 16
    for role, owner in (("Owner", True), ("Manager", False)):
        lab = k.text(f"session label · {role}", role, k.LABEL, k.TEXT_2, note="board marker: the session's role")
        p = hist_panel(throttled_status(owner=owner), footer=k.loaded_caption(k.N_CONTEXT), h=each, bars_k=12,
                       name=f"host panel · {role} session")
        nodes += [dict(lab, x=16, y=y), dict(p, x=16, y=y + 20)]
        y += 20 + each + 16
    k.copy_gap(f'session labels "Owner" / "Manager": §0 L{k.BOARDS[2].line} ("the Owner\'s link beside a Manager\'s '
               f'frame without it")')
    fr = k.window(fid, nodes, proposed=True)
    return fr, k.frame_block(fid, cites=[("V4", "Roles", 0)], lines=[
        "Two sessions stacked in one window (kit choice; §0 'beside'): the Owner's slot carries W-9 (CMP-021 → "
        "SCR-147); the Manager's has no link and no mention that one exists (T3, D09E09:38)",
        "Every other control identical for both roles (R-5)", "PROPOSED fields (R-7)"])


# --- board 03: coverage-gap (§6)
HOLE_K = ("09:30", 6)  # the kline hole on board 03 / 08 / 09 (kit choice; every figure derived from it)
REC_GAP = ("08:50", 3)  # the recording gap on gap/both


@builder("gap/gapped")
def gap_gapped(fid: str) -> Built:
    fr = k.window(fid, hist_panel([k.gapped_chip()], footer=k.loaded_caption(k.TARGET)))
    return fr, k.frame_block(fid, cites=[("V6", "Surface", 0), ("V6", "Tokens", 0), ("V6", "Keyboard and focus", 0),
                                         ("V6", "Announcement", 0)],
                             lines=["The reconstructed window's rows stay unmarked one by one; the chip carries it "
                                    "(BQ-7)", f"Caption {k.grp(k.TARGET)}: every bar present after the backfill"])


@builder("gap/hole-row")
def gap_hole_row(fid: str) -> Built:
    idx, a, b, _d = k.hole(*HOLE_K)
    row = k.hole_row(k.w("W-13", **{"from": a, "to": b}))
    fr = k.window(fid, hist_panel([], skip=tuple(idx), hole_at=idx[0] - 1, hole_node=row,
                                  footer=k.loaded_caption(k.TARGET - len(idx))))
    return fr, k.frame_block(fid, cites=[("V6", "Surface", 1), ("V6", "Copy", 1), ("V6", "Keyboard and focus", 1)],
                             lines=[f"W-13 {{from}}–{{to}} = {a}–{b}: the first missing bar's open and the next bar's "
                                    f"open; caption {k.grp(k.TARGET)} − {len(idx)} = {k.grp(k.TARGET - len(idx))}",
                                    "Never announced (§10.2); a row of the grid, its name its text"])


@builder("gap/both")
def gap_both(fid: str) -> Built:
    idx, a, b, d = k.hole(*REC_GAP)
    cause, ln = k.quote("connection lost", "spec")
    row = k.hole_row(k.w("W-14", **{"from": a, "to": b, "duration": d, "short_cause": cause}))
    fr = k.window(fid, hist_panel([k.gapped_chip()], skip=tuple(idx), hole_at=idx[0] - 1, hole_node=row,
                                  footer=k.loaded_caption(k.TARGET - len(idx))))
    return fr, k.frame_block(fid, lines=[
        "Both markers, never merged (BQ-7): the gapped chip for a window the backfill reconstructed, a separator row "
        "for a recording gap it could not fill",
        f"W-14: {a}–{b} UTC, {d} = {len(idx)} bars × {k.INTERVAL_MIN} min; short cause '{cause}' (W-14's own, "
        f"§13 L{ln}, illustrative)",
        f"Caption {k.grp(k.TARGET - len(idx))} = {k.grp(k.TARGET)} − {len(idx)}"])


@builder("gap/vs-stale")
def gap_vs_stale(fid: str) -> Built:
    t = k.history_title()
    stale, ln = k.quote('"Stale 4s"', "D04")
    p = hist_panel([k.gapped_chip()], footer=k.loaded_caption(k.TARGET), h=k.PANEL_H - MARK_H)
    k.copy_gap(f"stale words {stale}: E08-D04 L{ln} (the chip text, here in the panel's name only)")
    mk = k.hidden(f"panel name: {t} · {stale.strip(chr(34))}", w_=480, name="visually hidden · panel name")
    fr = k.window(fid, below(p, mk))
    return fr, k.frame_block(fid, lines=[
        f"gapped meets stale (L{k.L('Where `gapped` meets `stale`')}): the chip shows gapped; stale stays in the "
        f"panel's name, never stacked (D04:50)", "The stale age is E08-D04's example (4 s)"])


# --- board 04: classes-e08-delta (§5.1, §5.2)
REC_START = k.SERIES[0].t  # recording began at the oldest bar of the synthetic history


@builder("classes/e08-delta")
def classes_delta(fid: str) -> Built:
    stamp = k.ts(REC_START)
    head = k.w("W-10", ts=stamp)
    blk = k.block(k.ts_heading(head, stamp, k.BLOCK_W - 48), [k.w("W-11")], glyph_="pending",
                  name="CMP-026 EmptyState · recording-not-started")
    k.fallback("pending")
    k.deviate("classes/e08-delta: CMP-026's recording-not-started glyph drawn with the local icon 'pending' (the "
              "E16-D05 calendar glyph is not in the local set)")
    d1, l1 = k.quote("No recorded history before", "D02")
    d2, l2 = k.quote("Backfill in progress — Ns remaining", "D02")
    fr = k.window(fid, block_panel(blk))
    return fr, k.frame_block(fid, cites=[("V51", "Copy", 0), ("V51", "Tokens", 0), ("V51", "Analytics", 0)], lines=[
        f"Supersedes (D10-C1): D02 L{l1} '{d1} <date> — recording starts there' and L{l2} '{d2}'",
        f"{{ts}} = {stamp}: the recording start, after the requested window (the synthetic history's first bar)",
        "Backfill is a status over partial data, not an empty class (BQ-13); E16-D05 board 01's legs cited, not drawn"])


@builder("classes/e08-exemplars")
def classes_exemplars(fid: str) -> Built:
    hl = k.L("### 5.2 The three classes")
    cols = [k.Col("cls", "Class", 152), k.Col("var", "CMP-026 variant", 168), k.Col("reason", "reason", 136),
            k.Col("head", "Heading exemplar", 224), k.Col("cause", "Cause names", 232)]

    def exemplar(cellv: str) -> str:
        m = k.re.match(r"(W-\d+)", cellv)
        if not m:
            return cellv
        tx = k.TEMPLATES.get(m.group(1), k.COPY[m.group(1)].text)
        k.NOTES.add("copy_keys", f"{m.group(1)} {k.COPY[m.group(1)].key} (§13 L{k.COPY[m.group(1)].line})")
        return f'"{tx}" ({cellv})'

    rows = [{"cls": c[0], "var": c[1], "reason": c[2], "head": exemplar(c[3]), "cause": c[4]} for _i, c in k.CLASSES]
    tbl = k.spec_table("E08 exemplars", cols, rows, cap=k.plain(k.SPEC_LINES[hl - 1].lstrip("# ")), w_=k.PANEL_W - 32)
    card = k.vbox("card · E08 exemplars", [tbl], {"fill": k.RAISED, "pad": k.INSET_LG, "radius": k.R_CARD,
                                                  "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                  w=k.PANEL_W)
    fr = k.window(fid, card)
    return fr, k.frame_block(fid, lines=[
        f"§5.2 L{hl}'s table as drawn: the exemplars are E16-D05's and the catalogue's, cited; D10 adds no class "
        f"string (the three classes stay E16-D05 board 01's)",
        "W-10's {ts} kept as its key's slot here (a table of exemplars, not a frame of data)",
        "reason `no_matches`: E08-D05's merged reason, reused (BQ-10 ruled)"])


# --- board 05: timing (§7)
TL_H = 196


def t_lines(tid: str) -> list[str]:
    const, val, src, rule, _ln = k.TIMING[tid]
    return [f"{tid} {const}" + (f" · {val}" if val != "—" else ""), rule]


def timed(fid: str, marks: list, max_ms: int, panel_node: dict, name: str) -> dict:
    tl = k.timeline(name, max_ms, marks, h=TL_H)
    return k.window(fid, [dict(tl, x=16, y=16), dict(panel_node, x=16, y=16 + TL_H + 16)], proposed=True)


@builder("timing/cache-hit")
def timing_cache_hit(fid: str) -> Built:
    ms1 = int(k.re.search(r"\d+", k.TIMING["T-1"][1]).group(0))
    ms2 = int(k.re.search(r"\d+", k.TIMING["T-2"][1]).group(0))
    marks = [(0, "0 ms", []), (ms1, f"{ms1} ms", t_lines("T-1")), (ms2, f"{ms2} ms", t_lines("T-2"))]
    p = hist_panel([], footer=k.loaded_caption(k.TARGET), h=k.PANEL_H - TL_H - 16)
    fr = timed(fid, marks, 900, p, "timeline · cache hit (board diagram)")
    return fr, k.frame_block(fid, lines=[
        f"T-1 ≤ {ms1} ms: data at once, no skeleton, no words, no chip (L{k.TIMING['T-1'][4]})",
        "The panel as drawn at first paint: rows, an empty status slot; no event emitted (§12: a trader who never "
        "waits is not counted as waiting)"])


@builder("timing/slow-path")
def timing_slow_path(fid: str) -> Built:
    ms2 = int(k.re.search(r"\d+", k.TIMING["T-2"][1]).group(0))
    hz = int(k.re.search(r"\d+", k.TIMING["T-4"][1]).group(0))
    s1, s2 = ms2 + 1000 // hz, ms2 + 2000 // hz
    k.derive(f"timeline: the treatment at T-2 = {ms2} ms; samples at ≤ {hz} Hz → {s1} ms and {s2} ms")
    marks = [(0, "0 ms", []), (ms2, f"{ms2} ms", t_lines("T-2")), (s1, f"{k.grp(s1)} ms", t_lines("T-4")),
             (None, "fetch complete", t_lines("T-3"))]
    st = [k.bf_chip(), k.words("progress words", k.w3(k.N_CONTEXT))]
    p = hist_panel(st, footer=k.loaded_caption(k.N_CONTEXT), h=k.PANEL_H - TL_H - 16)
    fr = timed(fid, marks, 2400, p, "timeline · slow path (board diagram)")
    return fr, k.frame_block(fid, lines=[
        f"Nothing before {ms2} ms without data (T-2); then the chip and W-3 in the status slot; the words step per "
        f"sample at ≤ {hz} Hz (T-4)",
        f"No minimum display: the content replaces the treatment as a cut at fetch complete (T-3, BQ-11 ruled, "
        f"L{k.TIMING['T-3'][4]})", "PROPOSED fields (R-7)"])


@builder("timing/definitive-empty")
def timing_definitive(fid: str) -> Built:
    ms2 = int(k.re.search(r"\d+", k.TIMING["T-2"][1]).group(0))
    marks = [(0, "0 ms", []), (ms2, f"{ms2} ms", t_lines("T-2")), (None, "definitive answer", t_lines("T-7"))]
    stamp = k.ts(REC_START)
    blk = k.block(k.ts_heading(k.w("W-10", ts=stamp), stamp, k.BLOCK_W - 48), [k.w("W-11")], glyph_="pending",
                  name="CMP-026 EmptyState · recording-not-started")
    p = block_panel(blk, h=k.PANEL_H - TL_H - 16)
    fr = timed(fid, marks, 1200, p, "timeline · definitive empty (board diagram)")
    return fr, k.frame_block(fid, lines=[
        "The empty verdict renders only on a definitive answer (recording_started_at after the window), never on a "
        "timer; a failed request cannot establish emptiness (T-7)",
        f"Announced once per reason entry: \"{{heading}} {{cause}}\" (§10.2); empty_state_shown reason not_recorded"])


# --- board 06: keyboard-a11y (§4, §10)
def order_strip(stops: list[str], current: int) -> dict:
    """A board marker under the panel: the focus stops in order, each with its numbered marker."""
    kids = []
    for i, s in enumerate(stops, 1):
        mk = k.order_marker(i, 0, 0)
        mk = {kk: v for kk, v in mk.items() if kk not in ("x", "y")}
        kids.append(k.hbox(f"stop {i}", [mk, k.text("label", s + (" (focused)" if i == current else ""), k.CAPTION,
                                                     k.TEXT_1)], {"gap": k.INSET_XS}, h=20))
    return k.hbox("board marker · focus order", kids, {"gap": k.INSET_LG, "pad": k.INSET_SM, "fill": k.SUNKEN,
                                                       "radius": k.R_CONTROL}, w=k.PANEL_W, h=36,
                  note="board marker, not product UI: the Tab order (§10.1)")


@builder("a11y/focus-order")
def a11y_focus_order(fid: str) -> Built:
    st = [k.partial_chip(k.N_CONTEXT, focused=True), k.gave_up_line(), k.owner_link(), k.show_coverage()]
    p = hist_panel(st, footer=k.loaded_caption(k.N_CONTEXT), h=k.PANEL_H - MARK_H)
    stops = ["panel title", "Partial chip", k.piece(k.w("W-8"), 1), k.w("W-9"), "Show coverage"]
    k.copy_gap('focus-stop labels "panel title", "Partial chip": §10.1 Focus order row (the stops by name)')
    fr = k.window(fid, below(p, order_strip(stops, 2)))
    return fr, k.frame_block(fid, cites=[("V4", "Keyboard and focus", 1)], lines=[
        f"§10.1 L{k.L('| Focus order and visible focus')}: title → the Partial chip (KB-19) → Retry → the Owner's link "
        f"→ Show coverage; the backfilling and gapped chips are not stops",
        "The Partial chip focused: role=\"note\", tabindex=\"0\", the missing range in its description; "
        "color.focus.ring 2 px"])


@builder("a11y/retry-focus")
def a11y_retry_focus(fid: str) -> Built:
    t = k.title(k.history_title(), focused=True)
    st = [k.bf_chip(), k.words("progress words", k.w3(k.N_CONTEXT))]
    p = hist_panel(st, footer=k.loaded_caption(k.N_CONTEXT), h=k.PANEL_H - MARK_H, title_node=t)
    mk = k.hidden(f'role="status" (polite): {k.w("W-1")}', w_=480, name="visually hidden · status region")
    fr = k.window(fid, below(p, mk))
    return fr, k.frame_block(fid, cites=[("V4", "Keyboard and focus", 0)], lines=[
        "After Retry in context: the control leaves and focus moves to the panel title (tabindex=\"-1\"), never to "
        "the body; a new episode starts (W-1 announced once, past T-2)",
        f"Full panel (not drawn, the text binds): heading W-18 \"{k.w('W-18')}\", cause W-8, Retry first; on Retry "
        f"focus moves to the heading"])


@builder("a11y/status-rows")
def a11y_status_rows(fid: str) -> Built:
    hl = k.L("### 10.2 The announcement rows")
    cols = [k.Col("ev", "Event", 216), k.Col("reg", "Region", 192), k.Col("pol", "Politeness", 88),
            k.Col("rate", "max_rate", 184), k.Col("str", "String", 232)]

    def resolve(cellv: str) -> str:
        ids = k.re.findall(r"W-\d+", cellv)
        if not ids:
            return cellv
        for i in ids:
            k.NOTES.add("copy_keys", f"{i} {k.COPY[i].key} (§13 L{k.COPY[i].line})")
        return " or ".join(f'"{k.TEMPLATES.get(i, k.COPY[i].text)}"' for i in ids) + f" ({cellv})"

    rows = [{"ev": c[0], "reg": c[1], "pol": c[2], "rate": c[3], "str": resolve(c[4])} for _i, c in k.ANNOUNCE]
    tbl = k.spec_table("status-region rows", cols, rows, cap=k.plain(k.SPEC_LINES[hl - 1].lstrip("# ")),
                       w_=k.PANEL_W - 32)
    card = k.vbox("card · status-region rows", [tbl], {"fill": k.RAISED, "pad": k.INSET_LG, "radius": k.R_CARD,
                                                       "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                       "strokeAlign": "inner"}, w=k.PANEL_W)
    fr = k.window(fid, card)
    return fr, k.frame_block(fid, lines=[
        f"§10.2 L{hl}'s rows as drawn, every one with its max_rate; progress is never announced per sample",
        "Coalescing: W-5 only if W-1 was; a later W-6 or W-8 replaces the region's text (the 5 s limit counts repeats "
        "of one string)"])


# --- board 07: redlines (§11 on boards 01-03)
SLOT_MEASURED_H = {1: 44}  # live check: redline 01's specimen (W-1 over W-2) measures 44 px, the estimate 43 cut W-2


@builder("redlines")
def redlines(fid: str) -> Built:
    th = k.theme_of(fid)
    spec_w, call_w = 456, k.PANEL_W - 32 - 456 - 16
    inner = k.BLOCK_W - 48
    idx, a, b, _d = k.hole(*HOLE_K)
    specimens = [
        (k.vbox("specimen · block heading and cause", [k.text("heading (h3)", k.w("W-1"), k.HEADING_SM, k.TEXT_1),
                                                       k.text("cause", k.w("W-2"), k.BODY, k.TEXT_2, w=spec_w)],
                {"gap": k.STACK_SM}, w=spec_w), ["heading", "cause and progress words"], "board 01"),
        (k.hbox("specimen · backfilling chip and words", [k.bf_chip(), k.words("progress words", k.w3(k.N_CONTEXT))],
                {"gap": k.INSET_SM}, h=20), ["backfilling chip words", "backfilling chip glyph"], "board 01"),
        (k.vbox("specimen · bar", [k.bar(k.N_FULL, w_=inner)], None, w=inner, h=8),
         ["bar fill on its track", "bar fill on the panel"], "board 01"),
        (k.partial_chip(k.N_CONTEXT), ["Partial chip words"], "board 02"),
        (k.ring(k.button(k.piece(k.w("W-8"), 1))), ["focus ring"], "boards 02, 06"),
        (k.gapped_chip(), ["gapped chip words", "gapped chip glyph"], "board 03"),
        (k.hole_row(k.w("W-13", **{"from": a, "to": b}), w_=spec_w), ["hole separator row"], "board 03"),
    ]
    rows = []
    for i, (node, elems, where) in enumerate(specimens, 1):
        lines = [f"{e} ({where}): {k.ratio_line(e, th)}" for e in elems]
        call = k.callout(lines, w_=call_w, name=f"redline callout {i}")
        hh = max(round(k.est_height(node)), round(k.est_height(call)))
        slot_h = SLOT_MEASURED_H.get(i, round(k.est_height(node)))
        rows.append(k.hbox(f"redline {i:02d}", [k.box("specimen slot", [dict(node, x=0, y=0)], None, w=spec_w,
                                                      h=slot_h), call],
                           {"gap": k.INSET_LG, "align": "center"}, w=k.PANEL_W - 32, h=hh))
    fl, fln = k.quote("Every pair passes its bar in every theme", "spec")
    card = k.vbox("card · redlines on color.surface.raised", rows, {"fill": k.RAISED, "pad": k.INSET_LG,
                                                                    "gap": k.STACK_LG, "radius": k.R_CARD,
                                                                    "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                                    "strokeAlign": "inner"}, w=k.PANEL_W)
    fr = k.window(fid, card)
    return fr, k.frame_block(fid, lines=[
        f"§11's eleven pairs on the specimens of boards 01-03, ratios as §11 states them ({th}); '{fl}' (L{fln})",
        "Specimens are on color.surface.raised, the measured background; the hole row on color.surface.hover",
        "Light and high-contrast ratios: §11's columns; drawn on boards 08 and 09 (twins)"])


def build_board(nn: int) -> tuple:
    """Every frame of board nn by its §H id (twins call their base's builders), then write, md and pack."""
    b = k.BOARDS[nn]
    frames, blocks = [], []
    for fid in b.frames:
        fr, blk = BUILDERS[k.base_of(fid)](fid)
        frames.append(fr)
        blocks.append(blk)
    lines = []
    if b.twin:
        lines.append(f"Twin ({b.theme}): the frames of boards " + ", ".join(sorted({
            f"{nb:02d}" for f in b.frames for nb, bb in k.BOARDS.items() if not bb.twin and
            any(k.base_of(x) == k.base_of(f) for x in bb.frames)})) + " with the same builders and values; the "
                     f"{b.theme} token set at export")
    return k.build(nn, frames, blocks, board_lines=lines)
