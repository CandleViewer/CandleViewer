"""Board 02 `E08-D09 / 02 approaching-throttled` (dark); build(theme) is reused by board 10 (hc twin).
Run: python3 -I -B gen/gen_02.py  -> build/02-approaching-throttled.{json,md}, the .md here, v4/ packed copy."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for p in (GEN_DIR, GEN_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import e08d09kit as k  # noqa: E402
import pair3_helpers as h  # noqa: E402

BASE = 2


def tiles(frame_sid: str) -> list:
    tw = k.tile_widths()
    if frame_sid == "S-02":
        rest = k.tile(k.TILE_HEADINGS[0], "S-02", k.w("W-14", 1, h.used_share(h.USED["S-02"]["Main"])), w_=tw[0])
    else:
        rest = k.tile(k.TILE_HEADINGS[0], "S-03", k.w("W-15", 2, h.LIMIT), w_=tw[0])
    return [rest,
            k.tile(k.TILE_HEADINGS[1], "S-01", k.w("W-52", 1, 120), w_=tw[1]),
            k.tile(k.TILE_HEADINGS[2], None, None, w_=tw[2], gid="D09-G1"),
            k.tile(k.TILE_HEADINGS[3], None, None, w_=tw[3], status=k.clock_ok_status(12)),
            k.tile(k.TILE_HEADINGS[4], "S-01", None, w_=tw[4])]


def frame(fid: str, frame_sid: str, theme: str) -> tuple[dict, tuple[str, list[str]]]:
    rows, row_lines = h.budget_rows(frame_sid)
    kids = [k.table("CMP-049 budgets", k.w("W-07"), k.budget_header(), rows)]
    det_lines: list[str] = []
    if frame_sid == "S-03":
        det, det_lines = h.throttle_detail()
        kids.append(det)
    kids.append(k.reserve_band([(a, h.RESERVE) for a in h.ACCTS]))
    budgets = k.section("Rate budgets", kids, waits=["D09-G1", "D09-G14"],
                        note='role="region" "Rate budgets": served form (D09-G1, D09-G14 assumed served)')
    secs = [k.summary_strip(tiles(frame_sid)), budgets]
    scroll = h.fit_scroll(secs)
    fr = k.window(fid, theme, secs, scroll=scroll)
    top, total = h.page_offsets(secs)
    used = h.USED[frame_sid]["Main"]
    lines = [
        f"Served form: D09-G1 (per-class usage) and D09-G14 (the reserve) assumed served; their \"Not connected yet\" "
        f"forms are on board 01 (§0 L{k.L('| 01  |')}; kit ambiguity 8)",
        f"Limit {h.LIMIT} / s = §3.2's documented order.create default (L{k.L('Illustrative figures on the boards')}); "
        f"reserve {h.RESERVE} requests per account in the {h.WINDOW_S} s window = W-06b's slot (illustrative); "
        f"spendable {h.SPENDABLE}",
        cite_reserve(),
        *row_lines,
        f"REST budget tile: the strip's worst state ({frame_sid}); "
        + (h.cite("W-14", k.state_word("S-02"), k.w("W-14", 1, h.used_share(used)))
           + f"; {h.used_share(used)} % = {used} of {h.SPENDABLE} spendable (§5.2 L{k.L('- **S-02')})"
           if frame_sid == "S-02" else h.cite("W-15", k.state_word("S-03"), k.w("W-15", 2, h.LIMIT))),
        h.cite("W-07", k.w("W-07")),
        "Other tiles as board 01's served page: Public market data 120 topics (W-52 piece 2, the inspector's "
        "board 07 count); Private streams Not connected yet (D09-G1); Clock In sync 12 ms behind (W-29); IP hold "
        "Within budget",
        *det_lines,
        (f"Page about {total:.0f} px for the {k.VIEW_H} px view; scroll {scroll} px "
         + ("(the summary strip at the view's top; band and header scrolled away)" if scroll >= top else
            f"(the page's end meets the view's bottom; {scroll} px of band and header above the view)"))
        if scroll else f"Page about {total:.0f} px: fits the {k.VIEW_H} px view",
    ]
    if frame_sid == "S-03":
        lines.append(f"Used {used} = the exchange's limit {h.LIMIT} / s when it returned code 10006 (§6 trigger "
                     f"L{k.L('| Trigger ')})")
    blk = k.frame_block(fid, waits=["D09-G1", "D09-G14"],
                        suppressed=["S-02"] if frame_sid == "S-03" else [],
                        keyboard="Tab reaches the budgets grid as one stop; arrows move; Shift+F10 opens a row's "
                                 "Change budget… (SCR-147-KB-2, SCR-147-PP-2)",
                        lines=lines)
    return fr, blk


def cite_reserve() -> str:
    return h.cite("W-06b", k.w("W-06b", 0), k.w("W-06b", 1, h.RESERVE)) + " (one row per account; outside the meter, " \
                                                                            "never added to Headroom, §7 item 1)"


def build(theme: str) -> tuple[list[dict], list[tuple[str, list[str]]], list[str]]:
    (f2, _s2), (f3, _s3) = k.frames_of(BASE)
    fr2, b2 = frame(f2, "S-02", theme)
    fr3, b3 = frame(f3, "S-03", theme)
    k.deviate("account Swing: a kit alias (only \"Main\" is a spec slot)")
    k.deviate(f"reserve {h.RESERVE} requests per account per {h.WINDOW_S} s order window: an illustrative W-06b "
              "slot; D09-G14 serves the real figure")
    k.deviate("meter fill for S-02 and S-03 uses the warning tone (the register's color.status.warning.strong for "
              "both states, §5.2); §16 lists CMP-023's three fills")
    k.copy_gap("Used now and Window cells print the figure; the unit \"requests\" is in the meter's aria-valuetext "
               "(W-09), per R-3's \"in the cell, the header or the accessible name\"")
    k.copy_gap("IP hold tile at S-01 has no number string in §15 (no W-n for the IP figure when healthy)")
    board_lines = [
        f"Hand-off checklist (L{k.HL('- [ ] Board 02:')}): approaching limit and throttled name the account, the "
        "class, the limit and the retry time",
        "S-02 sits on one account's order row (Main, order.create); S-03 on the same row, the other rows within "
        "budget",
        "Served form throughout: D09-G1 and D09-G14 assumed served (sections marked \"Waits on\")",
    ]
    if theme != "dark":
        board_lines.append(f"Hand-off checklist (L{k.HL('- [ ] Boards 08–10:')}): light and high contrast keep every "
                           f"state as a word and a glyph; this {theme} twin draws 02's frames and values unchanged")
    return [fr2, fr3], [b2, b3], board_lines


def live_checks() -> list[str]:
    u2, u3 = h.USED["S-02"]["Main"], h.USED["S-03"]["Main"]
    hr2, hr3 = h.headroom(u2), h.headroom(u3)
    return [
        f"frame S-02: row 01's state cell reads \"Exchange\", the warning glyph, \"{k.state_word('S-02')}\", "
        f"\"{k.w('W-14', 1, h.used_share(u2))}\"; Headroom \"{hr2} · {k.pct(hr2, h.SPENDABLE)} %\"",
        f"frame S-03: row 01's state cell reads \"{k.state_word('S-03')}\" and "
        f"\"{k.w('W-15', 3, k.at(h.RETRY_S), h.RETRY_S)}\"; Headroom \"{hr3} · {k.pct(hr3, h.SPENDABLE)} %\"; the S-03 "
        f"detail shows \"{k.w('W-15', 1, 'Main', 'order')}\", \"{k.w('W-15', 2, h.LIMIT)}\", \"{k.w('W-15', 4)}\"",
        f"both frames: the reserve band has {len(h.ACCTS)} rows \"Reserved for stops and cancels · <alias>\" with "
        f"\"{k.w('W-06b', 1, h.RESERVE)}\"; no text overlaps a neighbour in any budgets row (cells 8 px padded a side)",
        "both frames: the REST budget tile's state word equals row 01's state word",
        "after relayout: each frame's main column clips the page (scroll recorded in the frame block); the S-03 "
        "detail and the reserve band end inside the 704 px body",
]


def main(nn: int = BASE) -> int:
    b = k.BOARDS[nn]
    k.NOTES.reset()
    frames, blocks, board_lines = build(b.theme)
    ann = k.annotations(nn, blocks, board_lines=board_lines)
    p = k.write_sheet(nn, frames, ann, notes={"live_checks": live_checks()})
    md = k.write_md(nn, p)
    packed = k.pack_sheet(p)
    rc, msg = k.validate(p)
    print(f"{p.name}: validator exit {rc}: {msg.splitlines()[-1] if msg else ''}")
    print(f"md {md.name}; packed {packed.name}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
