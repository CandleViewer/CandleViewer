"""Board 01 `E08-D09 / 01 healthy` (§0): the whole SCR-147 page served and healthy in three scroll positions, then
the Rate budgets section in S-13, S-15, S-16, S-17, S-18 and S-19. build(theme) is reused by board 08 (light twin).
Run: python3 -I -B gen_01.py"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair1_helpers as h  # noqa: E402

k = h.k
Node = dict[str, Any]
NN = 1
G_BUD = ["D09-G1", "D09-G14"]
MEASURED_PAGE_H = 1868  # the S-01 page height as drawn (the live check's SHEET-FIX; the kit estimates 1860)


def _line(sid: str, figures: list[str]) -> Node:
    return k.state_line(sid, figures, w_=k.INNER_W, name=f"section state · {sid}")


def budgets(state: str) -> tuple[Node, list[str]]:
    """The Rate budgets section in `state`, and its annotation lines (derivations, readings)."""
    L = k.L
    if state == "S-01":
        sec = k.section("Rate budgets", [h.budgets_table(h.served_rows()), h.reserve(True)], waits=G_BUD)
        u = h.ORDER_ROWS[0][2]
        hd, hs, us = k.headroom(h.LIM_O, u, h.RESERVE)
        return sec, [f"Headroom = Limit − Used now − reserve {h.RESERVE} (R-4, order rows): order.create Main "
                     f"{h.LIM_O} − {u} − {h.RESERVE} = {hd} · {hs} %; the share is of the spendable "
                     f"{h.LIM_O - h.RESERVE} (§3.2 L{L('| Headroom |')}; W-14's base), so {us} % used + {hs} % = 100 %"
                     f" (k.headroom, every board)",
                     f"Served form: D09-G1 and D09-G14 taken as served (reserve {h.RESERVE} requests per account, "
                     f"W-06b); query and WS rows hold no reserve (kit reading, §7 gives no per-class split)"]
    if state == "S-13":
        sk = k.skeleton("CMP-015 skeleton", k.INNER_W, 5)
        sec = k.section("Rate budgets", [sk], waits=G_BUD, note='region aria-busy="true"; visually hidden "Loading"')
        return sec, [f"S-13: skeleton only; the word \"Loading\" is visually hidden (§5.2 L{k.REGISTER['S-13'].line})"]
    if state == "S-15":
        vas, since, age = k.at(-h.STALE_AGE), k.at(-h.STALE_AGE + k.LIM["stale_s"]), h.STALE_AGE - k.LIM["stale_s"]
        line = k.hbox("section state · S-15", [k.glyph("clock", f"{k.DC}.stale.indicator"),
                                               k.text("text", k.w("W-04", None, vas, since, k.ago(age)), k.BODY,
                                                      f"{k.DC}.stale.text")], {"gap": k.INSET_XS})
        cols = {c.key: f"{k.DC}.stale.text" for c in k.BUDGET_COLS}
        rows = h.served_rows(colors=cols, state=h.stale_chip(age), subset=(
            "order.create · Main", "order.amend · Main", "order.cancel · Main", "position.read · Main",
            "market.read · Public"))
        sec = k.section("Rate budgets", [line, h.budgets_table(rows), h.reserve(True)], waits=G_BUD)
        return sec, [f"as of {vas} = {k.AS_OF} − {h.STALE_AGE} s; stale since {since} = as of + {k.LIM['stale_s']} s "
                     f"(S-15 > 5 s, D09-Q6); Stale {k.ago(age)} = {k.AS_OF} − {since}",
                     "Values kept in data-confidence.stale.text; each row's State cell is the stale chip"]
    if state == "S-16":
        lg = k.w("W-25", 2, k.at(-h.LAST_GOOD))
        err = h.word_rows("S-17", [("order.create", "order", "Main", f"{h.LIM_O} / s", "1 s"),
                                   ("order.cancel", "order", "Main", f"{h.LIM_O} / s", "1 s")], figures=(lg,))
        ok = h.served_rows(cols=h.S_COLS, subset=("market.read · Public", "Public WS · concurrent"), start=3)
        sec = k.section("Rate budgets", [_line("S-16", []), h.budgets_table(err + ok, h.S_COLS), h.reserve(True)],
                        waits=G_BUD)
        return sec, ["One slice error (REST order rows, S-17, last good kept) beside one ok (market.read and Public "
                     "WS, S-01); the section line reads Degraded (D09-Q7)",
                     f"last good {k.at(-h.LAST_GOOD)} = {k.AS_OF} − {h.LAST_GOOD} s"]
    if state == "S-17":
        lg = k.w("W-25", 2, k.at(-h.LAST_GOOD))
        picks = [(c, "order", "Main", f"{h.LIM_O} / s", "1 s") for c in ("order.create", "order.amend", "order.cancel")]
        picks += [("position.read", "position", "Main", f"{h.LIM_R} / s", "1 s"),
                  ("market.read", "market_data", "Public", f"{h.LIM_R} / s", "1 s")]
        sec = k.section("Rate budgets", [_line("S-17", [k.w("W-25", 1), lg, k.w("W-25", 3)]),
                                         h.budgets_table(h.word_rows("S-17", picks, figures=(lg,)), h.S_COLS),
                                         h.reserve(True)], waits=G_BUD)
        return sec, [f"Limit and Window kept from the last good read ({k.AS_OF} − {h.LAST_GOOD} s); Used now, "
                     f"Headroom and the meter's place read Error (§3.2 L{L('a row whose read failed reads S-17')}); "
                     "never the served detail (D09-C21)"]
    if state == "S-18":
        p = k.w("W-26").split(" · ")
        sec = k.section("Rate budgets", [_line("S-18", [p[1]]), k.button(p[2]),
                                         h.budgets_table([], h.S_COLS)], waits=G_BUD)
        return sec, ["The read failed: no row is known, so only the header is kept (layout reserved); Retry re-reads "
                     "(W-26)"]
    if state == "S-19":
        picks = [("order.create", "order", "Main", None, None), ("order.cancel", "order", "Main", None, None),
                 ("position.read", "position", "Main", None, None),
                 ("market.read", "market_data", "Public", None, None)]
        picks += [(k.w("W-10"), None, a, None, None) for a in h.ACCTS]
        sec = k.section("Rate budgets", [h.budgets_table(h.word_rows("S-19", picks), h.S_COLS), h.reserve(False)],
                        waits=["D09-G1", "D09-G2", "D09-G14"])
        return sec, [f"Not connected yet in Used now, Headroom and the meter's place; meter not drawn (§3.2 "
                     f"L{L('reads S-19')}); Limit and Window print \"—\" (kit reading: no figure, never 0, R-2)",
                     f"Per-minute fallback rows \"{k.w('W-10')}\" one per account (§3.3 L{L('### 3.3')}), also S-19 "
                     "until D09-G2"]
    raise KeyError(state)


def below(served: bool = True) -> list[Node]:
    return [h.simulator(output_s19=not served), h.inspector(), h.clock(served), h.actions(served), h.history()]


KB = ("Tab order §17.3: header → tiles → budgets grid (one stop, SCR-147-KB-2) → simulator (SCR-147-KB-4) → "
      "inspector (SCR-147-KB-6) → Re-measure (SCR-147-KB-7) → Reconnect (SCR-147-KB-1) → history (SCR-147-KB-5)")


def build(theme: str) -> tuple[list[Node], Node]:
    plan = [f for f, _s in k.frames_of(NN)]
    frames: list[Node] = []
    blocks: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    bud, bud_lines = budgets("S-01")
    secs = [h.strip(), bud, *below()]
    ph = h.page_height(secs)
    scrolls = [0, round((ph - k.VIEW_H) / 2), round(ph - k.VIEW_H)]  # as annotated on the board (the estimate)
    drawn = [scrolls[0], scrolls[1], MEASURED_PAGE_H - k.VIEW_H]  # the bottom view as drawn (the live SHEET-FIX)
    where = ("band, header, summary strip, budgets table", "budgets, reserve band, simulator form",
             "inspector (closed), clock in sync, actions, history (closed)")
    for i, fid in enumerate(plan[:3]):
        fr = k.window(fid, theme, secs, scroll=drawn[i], note=f"the page scrolled {drawn[i]} px")
        frames.append(fr)
        extra = [f"Scroll {scrolls[i]} px of a page about {ph:.0f} px (view {k.VIEW_H}): shows {where[i]}"]
        if i == 0:
            extra += bud_lines + [f"REST budget tile: busiest order row {h.ORDER_ROWS[0][2]} of {h.LIM_O - h.RESERVE} "
                                  f"spendable = {k.headroom(h.LIM_O, h.ORDER_ROWS[0][2], h.RESERVE)[2]} % (W-14's figure "
                                  "piece reused; S-02 starts at 80 %)",
                                  f"Public market data: {h.TOPICS} topics on {h.CONNS} sockets = W-44's slots"]
        if i == 2:
            extra += [f"Clock: {h.CLOCK_MS} ms behind = {k.offset_s(h.CLOCK_MS)} s (W-29, W-38's two-decimal slot); last measured "
                      f"{k.at(-h.CLOCK_AGE)} = {k.AS_OF} − {h.CLOCK_AGE} s (< 300 s cadence, < 900 s stale)"]
        if i == 0:
            blocks.append(k.frame_block(fid, waits=["D09-G1", "D09-G14"], keyboard=KB,
                                        lines=[*extra, "Lower sections: simulator D09-G10, inspector D09-G3, clock "
                                               "D09-G5 / G6, actions D09-G7, history D09-G9 (each marked)",
                                               h.strings_line(fr, seen)]))
        else:
            blocks.append((fid, [f"S-01 healthy as top (§5.2 L{k.REGISTER['S-01'].line}); the same page", *extra,
                                 h.strings_line(fr, seen)]))
    for fid, sid in zip(plan[3:], ("S-13", "S-15", "S-16", "S-17", "S-18", "S-19")):
        served = sid != "S-19"
        sec, lines = budgets(sid)
        secs_s = [h.strip(served), sec]
        rest = below(served)
        while rest and h.page_height(secs_s) < k.VIEW_H + 32:  # fill the view; sections past the fold not drawn
            secs_s.append(rest.pop(0))
        fr = k.window(fid, theme, secs_s)
        frames.append(fr)
        if served:
            lines = [*lines, "Waits on D09-G1, D09-G14; strip and the rest served (own states, §2.2)"]

        else:
            lines = [*lines, "Every tile and section in S-19 with its G-row; their served form is S-01 top / middle "
                             "/ bottom (§0 L78)"]
        if not served:
            lines.insert(0, "Waits on " + ", ".join(k.g(x) for x in ("D09-G1", "D09-G2", "D09-G3", "D09-G5", "D09-G7",
                                                                    "D09-G9", "D09-G10", "D09-G14")))
        blocks.append(k.frame_block(fid, recovery=sid in ("S-16", "S-17", "S-18"),
                                    lines=[*lines, h.strings_line(fr, seen)]))
    return frames, blocks


def board_lines() -> list[str]:
    L = k.L
    return [f"Section h2s from §2.2 L{L('### 2.2 Anatomy')}–L{L('8. **History.**')}; \"Meter\" / \"State\" from "
            f"§3.2 L{L('| Meter    |')}–L{L('| State    |')}; row groups \"Public WS\" / \"Private WS\" and their "
            f"second lines from §3.1 L{L('| Public WS  |')}–L{L('| Private WS |')}",
            f"Clock labels Offset / Last measured / Next due / State from §10 L{L('| ok (≤ 500 ms)')} (copy gap)",
            f"Accounts: \"Main\" is the spec's slot; {', '.join(k.ACCOUNTS[1:])} are kit aliases",
            f"S-13 … S-19 frames are drawn to the fold: sections past the {k.VIEW_H} px view are not drawn"]


def main(nn: int = NN, theme: str | None = None) -> None:
    b = k.BOARDS[nn]
    frames, blocks = build(theme or b.theme)
    ann = k.annotations(nn, blocks, board_lines=board_lines())
    k.deviate(f"accounts {', '.join(k.ACCOUNTS[1:])}: kit aliases (only \"Main\" is a spec slot)")
    k.copy_gap(f"clock dl labels Offset, Last measured, Next due, State: §10 L{k.L('| ok (≤ 500 ms)')} prose")
    k.copy_gap(f"Public WS / Private WS row-group words and second lines: §3.1 L{k.L('| Public WS  |')}")
    k.live(f"S-01 top / middle / bottom: the page ends inside the bottom frame's view (est. page "
           f"{h.page_height([h.strip(), budgets('S-01')[0], *below()]):.0f} px); re-set the bottom scroll to "
           f"page h − {k.VIEW_H} if the drawn height differs")
    k.live("every budgets row: read back each cell's text; no two adjacent texts closer than 16 px")
    p = k.write_sheet(nn, frames, ann)
    md = k.write_md(nn, p)
    packed = k.pack_sheet(p)
    print(p, md, packed, sep="\n")


if __name__ == "__main__":
    main()
