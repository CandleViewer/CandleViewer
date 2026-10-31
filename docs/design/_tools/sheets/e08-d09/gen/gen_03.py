"""Board 03 held-banned: S-04 held by IP and S-05 banned, side by side (§0 L85, §6). Dark.
Run: python3 -I -B gen/gen_03.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair4_helpers import Node, cite, k, lines_panel  # noqa: E402

NN = 3
HOLD_SET_S, HOLD_LEN_S = -100, 600  # our hold set 100 s before AS_OF for 600 s (§6: at least 600 s, capped at 900 s)
LEFT_S = HOLD_SET_S + HOLD_LEN_S  # 500 s left at AS_OF
TOPICS = 120  # Public market data tile (W-52's form)
RESERVE = 2  # requests held back per account in the 1 s order window (W-06b's slot; D09-G14 served, as on 01 and 02)
SCROLL = 180  # band 56 + rule 4 + PageHeader 72 + three 16 px gaps: the summary strip at the top of the view
# One scroll for both frames: the live check's SHEET-FIX scrolled S-05 30 px further because its W-17 word wrapped
# under a glyph left alone and grew the strip 18 px; k.tile now wraps the word beside its glyph, the strip keeps its
# height, so S-05 shows the strip's top and three account rows at S-04's scroll
SCROLL_OF = {"S-04": SCROLL, "S-05": SCROLL}


def tiles(sid: str) -> list[Node]:
    tw = k.tile_widths()
    ip_number = k.w("W-16", 1, k.at(LEFT_S), k.dur(LEFT_S)) if sid == "S-04" else k.w("W-17", 2)
    # W-16's and W-17's words are wider than the room beside the glyph: k.tile wraps them there (the glyph stays on
    # the word's first line; the live SHEET-FIX wrapped W-17 at the full inner width and left the glyph alone)
    return [k.tile(k.TILE_HEADINGS[0], sid, None, w_=tw[0]),
            k.tile(k.TILE_HEADINGS[1], "S-01", k.w("W-52", 1, TOPICS), w_=tw[1]),
            k.tile(k.TILE_HEADINGS[2], "S-01", None, w_=tw[2]),
            k.tile(k.TILE_HEADINGS[3], None, None, w_=tw[3], status=k.clock_ok_status(12)),
            k.tile(k.TILE_HEADINGS[4], sid, ip_number, w_=tw[4])]


def hold_panel(sid: str) -> Node:
    if sid == "S-04":
        head = k.state_line("S-04", [k.w("W-16", 1, k.at(LEFT_S), k.dur(LEFT_S)), k.w("W-16", 2)],
                            w_=k.INNER_W - 32, name="state · S-04")
        lines = [("cause", k.w("W-16", 3), k.BODY)]
        dont = [k.w("W-34", i) for i in (0, 1, 2)]  # §6: retry; reconnect; raise the budget
    else:
        head = k.state_line("S-05", [k.w("W-17", 2)], w_=k.INNER_W - 32, name="state · S-05")
        lines = [("cause", k.w("W-17", 1), k.BODY)]
        dont = [k.w("W-34", i) for i in (0, 1, 2, 3)]  # §6: as held; check the egress setup
    lines += [("condition", k.w("W-33"), k.BODY), ("reads", k.w("W-32"), k.BODY)]
    lines += [(f"don't-{i}", s, k.BODY) for i, s in enumerate(dont, 1)]
    lines += [("action", k.origin_action(sid) or "", k.BODY_STRONG)]
    return lines_panel(f"hold panel · {sid}", head, lines, stroke=k.tone_color(sid))


def rows(sid: str) -> list[Node]:
    lim = k.LIM["order_per_s"]
    out = []
    for i, acct in enumerate(k.ACCOUNTS, 1):
        out.append(k.table_row(k.BUDGET_COLS, {
            "class": "order.create", "account": acct, "limit": f"{lim} / s", "used": "0", "window": "1 s",
            "headroom": k.headroom_cell(lim, 0, RESERVE),
            "meter": k.meter(0, lim, valuetext=k.w("W-09", None, 0, lim, k.headroom(lim, 0, RESERVE)[0])),
            "state": k.state_line(sid, origin=False, w_=160), "action": k.row_action()},
            f"row {i:02d} · order.create · {acct}", i, second={"class": "order"}))
    return out


def frame(sid: str, theme: str) -> Node:
    fid = dict((s[0], f) for f, s in k.frames_of(NN))[sid]
    waits = ["D09-G1", "D09-G14"] + (["D09-G13"] if sid == "S-05" else [])
    budgets = k.section("Rate budgets", [hold_panel(sid),
                                         k.table("CMP-049 budgets", k.w("W-07"), k.budget_header(), rows(sid)),
                                         k.reserve_band([(a, RESERVE) for a in k.ACCOUNTS])], waits=waits)
    return k.window(fid, theme, [k.summary_strip(tiles(sid)), budgets], scroll=SCROLL_OF[sid])


def blocks() -> list[tuple[str, list[str]]]:
    (f4, _), (f5, _) = k.frames_of(NN)
    sr3 = k._SLOT.sub(str(LEFT_S // 60), k.SR["SCR-147-SR-3"][1])
    t2 = (f'Below the fold, both T2 (R-9, 2a, aria-disabled, the lock leading the full label): "{k.w("W-50")}" '
          f'with "{k.w("W-36")}" (§11 L{k.L("**Under S-04 or S-05**")}; SCR-147-T2-1) and "{k.w("W-35", 0)}" '
          f'with "{k.w("W-36")}" (SCR-147-T2-3); the row menu\'s "{k.w("W-60")}" likewise (SCR-147-T2-2)')
    common = [f"Scrolled {SCROLL} px: band, rule and PageHeader sit above the view; the strip leads it",
              f"Condition sentence W-33 only; W-31 (the throttle's) never prints here (§6 L{k.L('- **Two conditions')})",
              "Rows: order.create for all five accounts (scope \"all accounts\", §6 L290 table); Used now 0 (nothing "
              f"reaches the exchange), meter empty; Headroom {k.headroom_cell(k.LIM['order_per_s'], 0, RESERVE)} "
              f"of the {k.LIM['order_per_s'] - RESERVE} spendable (§3.2 L{k.L('| Headroom |')}): D09-G1, D09-G14 "
              "served as on 01 and 02, so Private streams reads Within budget (the hold is REST-wide, W-33)", t2]
    b4 = k.frame_block(f4, waits=["D09-G1", "D09-G14"], recovery=True, keyboard="Tab: tile heading links → budgets "
                       "grid (one stop, SCR-147-KB-2); the T2 controls keep focus, their reason is the "
                       "aria-describedby", lines=[
        f"Hold set at {k.at(HOLD_SET_S)} for {HOLD_LEN_S} s (§6: at least 600 s, capped at 900 s); ends "
        f"{k.at(LEFT_S)} = as of {k.AS_OF} + {LEFT_S} s, shown as \"in {k.dur(LEFT_S)}\" (derived)",
        f"Time left is our hold's, set by our adapter, not a time the exchange states (§6 L{k.L('| Recovery time is')})",
        f'SR-3 as spoken here: "{sr3}" ({LEFT_S} s, whole minutes)',
        "W-34 pieces 1-3 (§6: retry; reconnect; raise the budget)", *common,
        cite(["W-16", "W-33", "W-32", "W-34", "W-12", "W-52", "W-29", "W-07", "W-08", "W-09", "W-06b"])])
    b5 = k.frame_block(f5, waits=["D09-G1", "D09-G14", "D09-G13"], keyboard="as S-04", lines=[
        f"Contract-first placeholder (§0 L85; D09-G13): the lockout's time left is not served, so \"{k.w('W-17', 2)}\"; "
        "no time is invented", "W-34 all four pieces (§6: as held; check the egress setup)", *common,
        cite(["W-17", "W-33", "W-32", "W-34", "W-12", "W-52", "W-29", "W-07", "W-08", "W-09", "W-06b"])])
    return [b4, b5]


def build(theme: str = "dark") -> tuple[list[Node], Node]:
    frames = [frame("S-04", theme), frame("S-05", theme)]
    ann = k.annotations(NN, blocks(), board_lines=["Side by side: S-04 (left) and S-05 (right), each with its own "
                                                   "word, glyph and row (§6); clock fixed at as of " + k.AS_OF])
    return frames, ann


def main() -> int:
    frames, ann = build(k.BOARDS[NN].theme)
    k.live("S-04 frame: read back the hold panel's state line 'On hold — all accounts' and "
           f"'{k.w('W-16', 1, k.at(LEFT_S), k.dur(LEFT_S))}'; the IP hold tile shows the same time")
    k.live("S-05 frame: read back 'Time left: not received' in both the panel and the IP hold tile; no W-31 text on "
           "either frame (search the frames for 'reserved budget')")
    k.live(f"each frame: scrolled {SCROLL} px, the summary strip's top (its tiles' top borders) sits at about y 16 "
           "in the main column; three account rows show under the hold panel; in the REST budget and IP hold tiles "
           "the glyph sits on the first line of its wrapped word")
    k.live("each frame: the hold panel's stroke is the state's tone token (color.status.danger.strong)")
    p = k.write_sheet(NN, frames, ann)
    md = k.write_md(NN, p)
    packed = k.pack_sheet(p)
    print(p, md, packed, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
