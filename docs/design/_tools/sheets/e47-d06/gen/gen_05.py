"""Board 05 `E47-D06 / 05 table-states` (dark): §6.5 and §6.6 — the stale banner (the ladder table's W-5, each
surface's condition listed), the feed Stale clause, empty, no data, filtered to zero and load more."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BODY_H, LAST_SEC, PROFILE_TITLE, PW, PX0, STALE_CHIP_TEXT, grid_y, k,  # noqa: E402
                    ladder_body, ladder_panel, ladder_table_rows, native_left, profile_body, profile_panel)

NN = 5
LEFT_W = 328
TX = PX0 + k.PX[k.INSET_SM] + LEFT_W + 12
NO_DATA = k.scr047("1a never recorded")
EMPTY_HEADING = "No order book yet"  # copy gap (kit label): §6.6 names the state, not its words
EMPTY_CAUSE = "The table fills from the first book snapshot."  # copy gap (kit label)


def _conditions() -> list[str]:
    """§6.5's banner condition per surface, read from its prose."""
    ln = k.SPEC_LINES[k.L("### 6.5 The stale banner") + 1]
    m = k.re.search(r"The condition per surface: (.+?)\. `Shift\+R`", ln)
    return [s.strip() for s in m.group(1).split(";")]


def stale() -> dict:
    # W-1 verbatim (D04E11:272): a bar table's banner, on the level table of the focused bar
    body = profile_body(focus_k=k.PROF_META["poc"], chips=(), banner_text=k.w("W-1"))
    return k.window(k.BOARDS[NN].frames[0], [profile_panel(body)],
                    overlays=[k.callout("W-1 (§6.5)", ["W-1, verbatim (SCR-045's own banner): polite, once when the "
                                                       "banner appears; focus never moves; no Tab stop when absent",
                                                       "The banner's condition, per surface:",
                                                       *_conditions(),
                                                       "Ladder table: W-5 (PROPOSED), W-1's form; not drawn, the "
                                                       "text is binding"],
                                        # 380 px wide: x 898 (PX0 + 826), the first free x right of the
                                        # table's band (it ends at 896); at PX0 + 860 it ran 32 px past the frame
                                        PX0 + 826, grid_y(3, banner=True), wd=380)])


def feed_stale() -> dict:
    clause = k.fill(k.AS_OF, time=k.hms(LAST_SEC))
    body = profile_body(focus_k=k.PROF_META["poc"], clause=clause)
    return k.window(k.BOARDS[NN].frames[1], [profile_panel(body, chips=[k.feed_chip("Stale", STALE_CHIP_TEXT)])],
                    overlays=[k.callout("feed Stale", [f"The caption adds \"{clause}\" (D04E11:264); values keep "
                                                       "patching from the cache, nothing reads as live (R-7)",
                                                       "Every layer carries the clause: the mirror label and the "
                                                       "canvas label too (\"as of {time}\", §8)"],
                                        PX0 + 860, grid_y(2), wd=320)])


def empty() -> dict:
    blk = k.empty_block(EMPTY_HEADING, EMPTY_CAUSE, PW - 400)
    body = ladder_body([], chips=(), shown=0, total=0, empty=blk, sort=None, load_more=False,
                       left=native_left(0, 0, h=k.ROW_H * 2))
    return k.window(k.BOARDS[NN].frames[2], [ladder_panel(body)],
                    overlays=[k.callout("empty", ["The header row stays; the CMP-026 block says why (§6.6)",
                                                  "Copy gap: the heading and cause are kit labels for E47-D07"],
                                        TX, grid_y(6), wd=320)])


def no_data() -> dict:
    blk = k.empty_block(NO_DATA["heading"], NO_DATA["cause"], PW - 400, action=NO_DATA["action"],
                        link=NO_DATA["link"], live_=NO_DATA["live"])
    body = profile_body(empty=blk)
    return k.window(k.BOARDS[NN].frames[3], [profile_panel(body)],
                    overlays=[k.callout("no data", [f"SCR-047's never-recorded reason, verbatim (D04E11:"
                                                    f"{NO_DATA['line']}); the Owner's action shown",
                                                    "Manager and Viewer read the sentence form instead (D04E11)"],
                                        PX0 + 860, grid_y(7), wd=320)])


def filtered() -> dict:
    blk = k.empty_block(k.fill(k.NO_MATCH, filters=k.MY_LEVELS_LABEL), k.w("W-8"), PW - 400, action=k.CLEAR)
    body = ladder_body([], chips=(k.MY_LEVELS_LABEL,), shown=0, total=len(k.BOOK), empty=blk,
                       left=native_left(11, 11), load_more=False)
    return k.window(k.BOARDS[NN].frames[4], [ladder_panel(body)],
                    overlays=[k.callout("filtered to zero", [f"W-8 \"{k.w('W-8')}\", polite, once per change to "
                                                             "zero rows (D04E11:291)",
                                                             f"{k.CLEAR} is a button; the header row stays",
                                                             "Synthetic: this panel's account has no working order"],
                                        TX, grid_y(7), wd=360)])


def load_more() -> dict:
    deep = sorted((r for r in k.BOOK if r.side == "buy"), key=lambda r: -r.k)[-16:]
    rows = ladder_table_rows(deep, None)
    body = ladder_body(rows, sort="Price", direction="descending", shown=len(k.BOOK), total=len(k.BOOK),
                       left=native_left(11, 11), focus_load=True)
    return k.window(k.BOARDS[NN].frames[5], [ladder_panel(body)],
                    overlays=[k.callout("load more", [f"{k.LOAD_MORE}: keyboard-operable, focus-preserving "
                                                      "(`05`:195); it appends the next levels below and focus stays "
                                                      "on the control",
                                                      f"Scrolled to the deepest drawn bid ({k.px_fmt(k.price(deep[-1].k))}"
                                                      f", level {k.BOOK_LEVELS} of the side); the cap is 200 (§4)"],
                                        TX, grid_y(18), wd=420)])


def frames() -> list[dict]:
    return [stale(), feed_stale(), empty(), no_data(), filtered(), load_more()]


def blocks() -> list[tuple[str, list[str]]]:
    f = k.BOARDS[NN].frames
    return [(f[0], [f"§6.5 L{k.L('### 6.5')}: W-1 verbatim \"{k.w('W-1')}\" (D04E11:272); the ladder's W-5 "
                    f"(PROPOSED) is not drawn",
                    f"Shift+R only while the grid or the banner's button has focus, never in a text field (QA-6)"]),
            (f[1], [f"Feed chip \"{STALE_CHIP_TEXT}\" (E11-D02 LD-1's form, D04E11); caption clause "
                    f"\"{k.fill(k.AS_OF, time=k.hms(LAST_SEC))}\""]),
            (f[2], [f"§6.6 L{k.L('### 6.6')}: empty (no series yet) keeps the header row and says why"]),
            (f[3], ["No data: not recorded, SCR-047's reasons; the CMP-026 block under the kept header row"]),
            (f[4], [f"Filtered to zero: \"{k.fill(k.NO_MATCH, filters=k.MY_LEVELS_LABEL)}\" + {k.CLEAR}"]),
            (f[5], [f"{k.LOAD_MORE} (CMP-053) focused; the table is in its natural order (Price, best outward)"])]


def notes() -> None:
    k.copy_key(f"{k.EXPORT_KEY} (PROPOSED, owner E11-D04): \"{k.EXPORT_REASON}\", the Export CSV T2 reason")
    k.copy_gap(f"empty: \"{EMPTY_HEADING}\" / \"{EMPTY_CAUSE}\" are kit labels (§6.6 names the state only)")
    k.ambiguity("states/stale draws one surface (the ladder, whose W-5 is fully specified); the other surfaces' "
                "conditions are listed from §6.5; the profile table's banner words are not in §13 (a level table "
                "takes W-1's form for its focused bar or period; E47-D07 words it)")
    k.ambiguity("filtered to zero needs a filter that can empty the table: My levels only on an account without "
                "working orders (synthetic); the In VA filter can never reach zero rows")
    k.copy_gap(f"\"{PROFILE_TITLE}\", \"DOM ladder\" in the captions are kit labels for {{panel}}")


def main() -> None:
    notes()
    p, md, pk = k.build(NN, frames(), blocks(), per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
