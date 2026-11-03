"""Board 02 `E47-D08 / 02 budget-timeline` (dark): §4.4's 40 Hz burst on a 0–2 000 ms axis. Frame 1: every source's
requests and the starts it admits alone (FR-1, FR-5, FR-6), and the sum without the arbiter. Frame 2: the region
arbiter (FR-3, FR-9): admitted starts, refused requests and the count per half-open 1 000 ms window. Every mark is
k.SIM (the burst through §4's rules); the self-test checks its maxima against §4.4's figures."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Timeline, k  # noqa: E402

NN = 2
T1 = 2000
INNER_W = k.FRAME_W - 2 * k.PX[k.INSET_XL]  # 1232
LABEL_W = 168
TL = Timeline(0, T1, LABEL_W + 16, 1040)
LANE_H = 92
TOP = 40  # the windows' label row
COLOR = {"price": k.BUY, "liq": k.WARN_STRONG, "heat": k.HM[5]}
NAME = {"price": "I-5 value flash, one cell", "liq": "I-24 liquidation flash, one panel",
        "heat": "I-21 heatmap live-column cell", "bubble": "I-22 big-trade bubble"}
RULE = {"price": "FR-1", "liq": "FR-5", "heat": "FR-6"}


def in_range(ts: list[int]) -> list[int]:
    return [t for t in ts if t < T1]


def marks(prefix: str, ts: list[int], y: int, h: int, w_: int, color: str, dx: int = 0) -> list[k.Node]:
    """One group of marks (a non-flex box at the lane's y), so the packer splits per group, not per mark."""
    ms = [k.rect(f"{prefix} {t}", w_, h, color, x=TL.x(t) + dx, y=0) for t in in_range(ts)]
    return [k.box(f"{prefix}s", ms, None, w=INNER_W, h=h, x=0, y=y)] if ms else []


def lane_label(i: int, title: str, lines: list[str], y: int) -> k.Node:
    return k.vbox(f"lane {i} · label", [k.text("title", title, k.LABEL, k.TEXT_1, w=LABEL_W),
                                        *[k.text(f"line {j}", s, k.CAPTION, k.TEXT_2, w=LABEL_W)
                                          for j, s in enumerate(lines, 1)]],
                  {"gap": k.STACK_XS}, w=LABEL_W, x=0, y=y)


def sim_row(src: str) -> tuple[str, str, str, int]:
    return next(r for r in k.SIM_ROWS if r[0].startswith(NAME[src].split(",")[0]))


def frame_requests() -> tuple[k.Node, list[str]]:
    s = k.SIM
    kids: list[k.Node] = TL.windows(0, TOP + 5 * LANE_H)
    for i, src in enumerate(("price", "liq", "heat", "bubble"), 1):
        y = TOP + (i - 1) * LANE_H
        row = sim_row(src)
        if src == "bubble":
            kids.append(lane_label(i, NAME[src], [f"no request: no flash (§4.2 L{k.PER_SURFACE['I-22 big-trade bubble']['line']})",
                                                  f"max {row[2]} starts (§4.4 L{row[3]})"], y))
            continue
        solo = k.max_window(s.solo[src])
        kids.append(lane_label(i, NAME[src], [f"{len(in_range(s.requests[src]))} requests; alone ({RULE[src]}) "
                                              f"max {solo} starts in any window (§4.4 L{row[3]}: {row[2]})"], y))
        kids += marks(f"lane {i} · request", s.requests[src], y + 8, 14, 2, k.TEXT_3)
        kids += marks(f"lane {i} · start", s.solo[src], y + 28, 40, 4, COLOR[src])
    y = TOP + 4 * LANE_H
    naive = k.max_window([t for src in k.SOURCES for t in s.solo[src]])
    gate = k.fr_int("FR-7")
    kids.append(lane_label(5, "all four, no arbiter", [f"max {naive} starts in a window ≥ FR-7 ({gate}): fails the "
                                                       "gate; why FR-3 exists (§4.4)"], y))
    for j, src in enumerate(k.SOURCES):  # side by side: starts at the same ms would hide each other
        kids += marks(f"lane 5 · {src} start", s.solo[src], y + 28, 40, 4, COLOR[src], 6 * j)
    kids += TL.axis(TOP + 5 * LANE_H + 4, 250)
    box = k.box("timeline", kids, None, w=INNER_W, h=TOP + 5 * LANE_H + 32)
    title = k.text("title", f"§4.4 · the TICKS burst at {k.BURST_HZ} Hz on one FR-2 region ({k.REGION_W} × "
                            f"{k.REGION_H} px): requests and starts per source, 0–{T1:,} ms of {k.BURST_MS:,}"
                   .replace(",", " "), k.HEADING_SM, k.TEXT_1, w=INNER_W)
    key = k.text("key", "Short grey marks: a request (every tick changes in the worst direction; the heatmap every "
                        f"{k.HEAT_MS} ms). Tall marks: a start the source admits by its own rule. Shaded: the "
                        "half-open 1 000 ms windows. In the sum lane, starts at the same ms sit side by side, 6 px apart, in "
                        "FR-9's order.", k.CAPTION, k.TEXT_2, w=INNER_W)
    return (k.specimen(k.BOARDS[NN].frames[0], [title, key, box], note="§4.4; the requests and each source alone"),
            [f"Requests: {', '.join(f'{NAME[x].split(',')[0]} {len(in_range(s.requests[x]))}' for x in k.SOURCES)} in "
             f"0–{T1} ms; starts alone: {', '.join(f'{RULE[x]} max {k.max_window(s.solo[x])}' for x in k.SOURCES)}",
             f"Without the arbiter the four sum to {naive} starts in a window (§4.4 'all four, no arbiter'), above "
             f"FR-7's {gate} (§4.1 L{k.FR['FR-7']['line']})"])


def frame_admitted() -> tuple[k.Node, list[str]]:
    s = k.SIM
    kids: list[k.Node] = TL.windows(0, TOP + 4 * LANE_H)
    cap = k.fr_int("FR-3")
    for i, src in enumerate(k.SOURCES, 1):
        y = TOP + (i - 1) * LANE_H
        held = [t for t in s.requests[src] if t not in s.admitted[src] and t not in s.refused[src]]
        kids.append(lane_label(i, f"{i}. {NAME[src]}", [
            f"rank {i} of FR-9; {len(in_range(s.admitted[src]))} admitted, {len(in_range(s.refused[src]))} refused "
            f"by the region, {len(in_range(held))} held by {RULE[src]}"], y))
        kids += marks(f"lane {i} · held", held, y + 8, 14, 2, k.TEXT_3)
        kids += marks(f"lane {i} · refused", s.refused[src], y + 72, 10, 2, k.DANGER_DEF)
        kids += marks(f"lane {i} · admitted", s.admitted[src], y + 28, 40, 4, COLOR[src])
    y = TOP + 3 * LANE_H
    allx = sorted(t for src in k.SOURCES for t in s.admitted[src])
    comb = k.max_window(allx)
    kids.append(lane_label(4, "all four, with the arbiter", [f"max {comb} starts in any half-open window "
                                                             f"(FR-3 = {cap}; §4.4 L{k.SIM_ROWS[-1][3]}: "
                                                             f"{k.SIM_ROWS[-1][2]})"], y))
    for j, src in enumerate(k.SOURCES):
        kids += marks(f"lane 4 · {src} admitted", s.admitted[src], y + 28, 40, 4, COLOR[src], 6 * j)
    for i, w0 in enumerate(range(0, T1, k.WINDOW_MS), 1):
        n = sum(1 for t in allx if w0 <= t < w0 + k.WINDOW_MS)
        kids.append(k.tag(f"{n} starts", TL.x(w0) + 8, y + 72, name=f"lane 4 · window {i} count"))
    kids += TL.axis(TOP + 4 * LANE_H + 4, 250)
    box = k.box("timeline", kids, None, w=INNER_W, h=TOP + 4 * LANE_H + 32)
    title = k.text("title", "§4.3 · the region arbiter on the same burst: who is admitted, ranked by FR-9 "
                            f"(liquidation, then the focused symbol, then the rest); at most {cap} starts a window",
                   k.HEADING_SM, k.TEXT_1, w=INNER_W)
    key = k.text("key", "Tall marks: an admitted start. Short grey marks: a request held by the source's own interval. "
                        "Red marks low in the lane: a request the region refused — dropped, never queued; the source "
                        "asks again on its next change and its value still updates (R-4).", k.CAPTION, k.TEXT_2,
                 w=INNER_W)
    return (k.specimen(k.BOARDS[NN].frames[1], [title, key, box], note="§4.3, §4.4; with the arbiter"),
            [f"§4.3 L{k.L('### 4.3 The region arbiter') + 2}: a start is drawn only if the region has seen fewer than "
             f"FR-3 ({cap}) starts in the half-open {k.WINDOW_MS} ms window ending now; ranked by FR-9",
             f"Result: {comb} starts in any window (§4.4's {k.val('SIM', 'combined')}); the heatmap cell is refused "
             "every time in this burst (rank 3), its true size still reaching the readout (§7, R-4)",
             f"The arbiter runs once per frame on the existing cadence: FR-4 = {k.val('SIM', 'frames')} frames at "
             "60 Hz, no new timer (§4.1 FR-4)"])


def main() -> None:
    f1, b1 = frame_requests()
    f2, b2 = frame_admitted()
    fr = k.BOARDS[NN].frames
    p, md, pk = k.build(NN, [f1, f2], [(fr[0], b1), (fr[1], b2)], per_row=2, board_lines=[
        f"Window: the first {T1} ms of the {k.BURST_MS} ms burst; the pattern repeats each second",
        f"Not drawn: light and high-contrast cells of this board (§0 L{k.NOT_DRAWN_LINE})"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
