"""Board 02 `E47-D06 / 02 surrogate-grammar` (dark): §3 — the cursor window over the chart (one plot stop, the
windowed hidden table, the Enter detail), the sparse set over the big-trade bubbles (a button per item, aria-setsize
the full count) and the 24 px targets with the overlap rule."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BODY_H, CHART_TITLE, PH, PX0, PY0, k  # noqa: E402

NN = 2
CW = 772  # kit choice: the chart panel's width; the hidden layers are drawn as callouts in the dock beside it
AX = PX0 + CW + 16  # the callout column's x (frame coordinates)
PLOT_Y = PY0 + k.HEAD_H
ROW_CAP = int(next(c["figure"] for c in k.CAPS if c["cap"].startswith("mirror rows (the window")).replace(",", ""))
TARGET = 24  # `05`:100 / R-4: at least 24 x 24 CSS px
SET_CAP = int(next(c["figure"] for c in k.CAPS if c["cap"].startswith("bubble")).replace(",", ""))


def _window() -> tuple[int, int, int]:
    """(first, last, cursor) bar ordinals (1-based) of the hidden table's window: ROW_CAP rows centred on the cursor,
    shifted inside the series."""
    c = k.BARS.index(k.CURSOR) + 1
    first = max(1, min(c - ROW_CAP // 2, len(k.BARS) - ROW_CAP + 1))
    return first, first + ROW_CAP - 1, c


def chart_panel(extra=(), *, focused: bool = True) -> tuple[dict, "k.PriceScale", float]:
    plot, sc, slot = k.candle_plot("CMP-180 ChartRoot canvas", k.VISIBLE, CW, BODY_H, cursor=k.CURSOR.minute,
                                   extra=[*extra, *([dict(k.inset_ring(CW, BODY_H), name="CMP-039 ring · plot stop")]
                                                    if focused else [])])
    return k.panel("CMP-080 DockPanel · chart (SCR-030)", CHART_TITLE, plot, w_=CW, h=PH, first="Chart",
                   chips=[k.feed_chip("Live")]), sc, slot


def cursor_window() -> dict:
    first, last, c = _window()
    near = [b for b in k.BARS if abs(k.BARS.index(b) + 1 - c) <= 2]
    rows = [f"aria-rowindex {k.BARS.index(b) + 2}: \"{k.bar_name(b)}\"" + (" — aria-current" if b is k.CURSOR else "")
            for b in near]
    panel, _sc, _sl = chart_panel()
    return k.window(k.BOARDS[NN].frames[0], [panel], overlays=[
        k.callout("mirror (hidden)", [f"The mirror: a windowed hidden table (clip-path, never display:none, R-4); "
                                      f"aria-rowcount {len(k.BARS) + 1}; rows {first} to {last} of {len(k.BARS)} "
                                      f"materialised ({ROW_CAP}, the window's cap, §4)", *rows,
                                      "The window follows the cursor, never the pixels (§3.1)"],
                  AX, PY0, wd=400),
        k.callout("Enter detail", [f"Enter: the cursor bar's footprint levels ({len(k.FOOTPRINT)} nodes; the cap is "
                                   f"{next(c_['figure'] for c_ in k.CAPS if 'Enter' in c_['cap'])}, §4); Esc returns "
                                   "to the plot stop at the same bar",
                                   *[f"\"{k.fp_name(x)}\"" for x in k.FOOTPRINT]], AX, PY0 + 300, wd=400),
        k.callout("canvas label", [f"Layer 4: role=\"img\", \"{k.l1_label(k.VISIBLE)}\" (L-1)",
                                   "One Tab stop: the plot stop (ring), the cursor column its focus mark"],
                  AX, PY0 + 560, wd=400)])


def _items() -> list["k.Bubble"]:
    """The set: the bubbles intersecting the visible range (+ the selected / focused one, here inside it)."""
    return k.BUBBLES_VIS


def _rank(b: "k.Bubble") -> int:
    order = sorted(k.BUBBLES, key=lambda x: (x.sec, x.k))  # time-then-price order (§3.2)
    return order.index(b) + 1


def bubble_layer(sc, slot, *, focus=None, overlap=False) -> tuple[list[dict], list[tuple]]:
    nodes, boxes = [], []
    for b in _items():
        x, y = k.bubble_xy(b, sc, slot, k.VISIBLE[0].minute)
        r = k.bubble_r(b)
        nodes.append(k.ellipse(f"bubble {k.hms(b.sec)}", 2 * r, 2 * r, {"fill": k.C_UP if b.buy else k.C_DOWN,
                                                                         "opacity": "opacity.muted"},
                               x=x - r, y=y - r, note="CMP-112 (synthetic size encoding, kit choice)"))
        s = max(TARGET, 2 * r)
        boxes.append((b, x - s // 2, y - s // 2, s))
    k.fallback("hidden-layer")
    for b, bx, by, s in boxes:
        # "dashed · " names the bounds for the post-step's dashed stroke (render README, post.tmpl.js)
        sur = k.box(f"dashed · surrogate {k.hms(b.sec)}", [], {"stroke": k.MARK_FILL, "strokeWidth": k.HAIR,
                                                       "strokeAlign": "inner"}, w=s, h=s,
                    note=f"button surrogate (hidden), {s} x {s} CSS px, aligned to the bubble (R-4); aria-label "
                         f"\"{k.bubble_name(b)}\"")
        if b is focus:
            sur = k.focus_ring(sur, radius=None)
            e = k.extent("normal")
            nodes.append(dict(sur, x=bx - e, y=by - e))
        else:
            nodes.append(dict(sur, x=bx, y=by))
    return nodes, boxes


def sparse_set() -> dict:
    _p, sc, slot = chart_panel(focused=False)
    focus = next(b for b in _items() if b.n > 1)
    layer, _boxes = bubble_layer(sc, slot, focus=focus)
    panel, _sc, _sl = chart_panel(layer, focused=False)
    names = [f"posinset {_rank(b)}: \"{k.bubble_name(b)}\"" for b in _items()[:4]]
    return k.window(k.BOARDS[NN].frames[1], [panel], overlays=[
        k.callout("the set", [f"One roving group of button surrogates after the plot stop; {len(_items())} items "
                              f"intersect the visible range (cap {SET_CAP}, PROPOSED, §4); aria-setsize "
                              f"{len(k.BUBBLES)} (the full count)",
                              *names, "…",
                              f"Focused: posinset {_rank(focus)}: \"{k.bubble_name(focus)}\"",
                              "Arrows move within the set, Home / End reach its ends, Tab leaves it; a window "
                              "change never moves focus (§3.2)"], AX, PY0, wd=400),
        k.callout("names", ["N-8: {unit}. {values}. {flags}. {Estimated, display name}; a cluster carries "
                            "\"Cluster of n\" and \"Estimated, Trade cluster\" (CMP-227's display name)"],
                  AX, PY0 + 420, wd=400)])


def targets() -> dict:
    _p, sc, slot = chart_panel(focused=False)
    layer, boxes = bubble_layer(sc, slot)
    pairs = [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:]
             if a[1] < b[1] + b[3] and b[1] < a[1] + a[3] and a[2] < b[2] + b[3] and b[2] < a[2] + a[3]]
    if not pairs:
        raise SystemExit("gen_02: no overlapping surrogate pair at this scale")
    a, b = pairs[0]
    later = b if (b[0].sec, b[0].k) > (a[0].sec, a[0].k) else a
    small = [x for x in boxes if 2 * k.bubble_r(x[0]) < TARGET]
    marks = [k.tag(f"{TARGET} x {TARGET}", small[0][1] + small[0][3] + 4, small[0][2]),
             k.tag("overlap: the later anchor wins", later[1] + later[3] + 4, later[2] + 18)]
    panel, _sc, _sl = chart_panel([*layer, *marks], focused=True)
    return k.window(k.BOARDS[NN].frames[2], [panel], overlays=[
        k.callout("targets", [f"Every pointer-reachable surrogate is aligned to its target and at least {TARGET} x "
                              f"{TARGET} CSS px (`05`:100, R-4): {len(small)} of {len(boxes)} bubbles draw smaller "
                              "and their surrogates grow into the gutter, never over another target",
                              f"Overlap ({k.hms(a[0].sec)} / {k.hms(b[0].sec)}): the focused target wins, else the "
                              f"later anchor ({k.hms(later[0].sec)}) (§3.3)",
                              "The plot stop is sized to the plot; its focus-visible mark is the cursor column "
                              "(D07E11:139); CMP-039 is the only ring"], AX, PY0, wd=400)])


def frames() -> list[dict]:
    return [cursor_window(), sparse_set(), targets()]


def blocks() -> list[tuple[str, list[str]]]:
    f = k.BOARDS[NN].frames
    return [(f[0], [f"§3.1 L{k.L('### 3.1')}: the cursor-window grammar (R-3); the cursor on {k.hhmm(k.CURSOR.minute)}",
                    f"The mirror rows read N-1 (§5 L{k.NAMES['N-1']['line']}); slots joined by \". \", values by \", \""]),
            (f[1], [f"§3.2 L{k.L('### 3.2')}: the sparse-set grammar over CMP-112 (IV-8); posinset in time-then-price "
                    f"order over all {len(k.BUBBLES)} big trades of the loaded series"]),
            (f[2], [f"§3.3 L{k.L('### 3.3')}: size and alignment (R-4); dashed squares are the hidden surrogates' "
                    "bounds (annotation)"])]


def notes() -> None:
    k.ambiguity("a single big print carries no estimated slot; a cluster carries \"Estimated, Trade cluster\" "
                "(CMP-112 names a cluster \"…, estimated\", `15`:1326; CMP-227's display name for trade_cluster)")
    k.ambiguity(f"the big-trade threshold is the loaded series' 99th size percentile ({k.q_fmt(k.BIG_QTY)} BTC, kit "
                "choice); the bubble radius 4 + sqrt(notional / 10,000) px is a kit encoding")
    k.copy_gap("the hidden table's and the set's group names are not in §13 (E47-D07 words them)")
    k.live("surrogate squares: the post-step dashes every 'dashed · surrogate …' bound (36: 18 in each of the "
           "sparse-set and targets frames); read the count back")


def main() -> None:
    notes()
    p, md, pk = k.build(NN, frames(), blocks(), per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
