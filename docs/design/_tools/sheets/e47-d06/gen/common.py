"""Shared imports for the generators: the kit on sys.path and the panel frames several boards draw (the profile
table over SCR-038, the ladder table beside the native grid over SCR-050)."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d06kit as k  # noqa: E402

PW, PH = k.DOCK_W - 2 * k.DOCK_PAD, k.DOCK_H - 2 * k.DOCK_PAD  # one panel fills the dock: 1200 x 688
BODY_H = PH - k.HEAD_H  # 656
PX0, PY0 = k.NAV_W + k.DOCK_PAD, k.TOP_H + k.DOCK_PAD  # the panel's origin in frame coordinates (72, 56)
TABLE_Y0 = PY0 + k.HEAD_H  # the table view's top (88)
PROFILE_TITLE, LADDER_TITLE, CHART_TITLE = k.screen_title("SCR-038"), k.screen_title("SCR-050"), \
    k.screen_title("SCR-030")
PROFILE_SCOPE = f"{k.hhmm(k.PROFILE_FROM)} to 14:00 UTC, rows of {k.PROF_ROW} ticks"
LADDER_SCOPE = f"{k.BOOK_LEVELS} levels a side"
LAST_SEC = max(p.sec for p in k._RAW)
STALE_AGE = "7s"  # kit choice: the chip's age at the frame (E11-D02 LD-1's form)
STALE_CHIP_TEXT = k.re.sub(r"Stale \d+s · last [\d:]+", f"Stale {STALE_AGE} · last {k.hms(LAST_SEC)}", k.STALE_CHIP)


def grid_y(row: int, *, banner: bool = False) -> int:
    """Frame y of grid row `row` (0 = the header row) in a one-panel window."""
    return TABLE_Y0 + k.HEAD_H + (k.HEAD_H if banner else 0) + 20 + row * k.ROW_H


def profile_rows(levels: list["k.ProfLevel"], focus_k: int | None, n: int) -> list[dict]:
    rows = []
    for i, x in enumerate(levels[:n], 1):
        rows.append(k.data_row(i, k.PROFILE_COLS, k.prof_values(x), focused=x.k == focus_k,
                               colors={"Delta": k.BUY if x.delta > 0 else k.SELL if x.delta < 0 else k.TEXT_1},
                               actions=k.prof_px(x.k),
                               note=f'aria-label "{k.acc_name(k.prof_px(x.k), [f"volume {k.q_fmt(x.vol)}"])}…" (N-3)'
                               if x.k == focus_k else None))
    return rows


def profile_body(*, levels: list["k.ProfLevel"] | None = None, focus_k: int | None = None, sort: str | None = "Price",
                 direction: str = "descending", chips=(), banner_text=None, clause=None, empty=None,
                 export_reason=k.EXPORT_REASON, paused: bool = False) -> dict:
    lv = k.PROFILE if levels is None else levels
    fit = (BODY_H - (k.HEAD_H + (k.HEAD_H if banner_text else 0) + 20 + k.HEAD_H) - k.ROW_H - 16) // k.ROW_H
    rows = [] if empty else profile_rows(lv, focus_k, fit)
    below = (f"{len(lv) - fit} more rows below (the grid scrolls; rows are virtualised, `14`:1108)"
             if not empty and len(lv) > fit else None)
    return k.table_body(k.PROFILE_COLS, rows, wd=PW, h=BODY_H, sort=sort, direction=direction,
                        filter_only=("Value area",), chips=chips, shown=0 if empty else len(lv),
                        total=0 if empty else len(k.PROFILE), banner_text=banner_text,
                        caption=(PROFILE_TITLE, PROFILE_SCOPE), clause=clause, empty=empty, below=below,
                        export_reason=export_reason, paused=paused)


def profile_panel(body: dict, *, chips=(), head_extra=(), table_on: bool = True) -> dict:
    return k.panel("CMP-080 DockPanel · profile (SCR-038)", PROFILE_TITLE, body, w_=PW, h=PH, table_on=table_on,
                   chips=chips or [k.feed_chip("Live")], head_extra=head_extra,
                   note="the table opens in place of the canvas (D04E11 D2); toolbar and status kept")


def ladder_table_rows(rows: list["k.BookRow"], focus_k: int | None, *, mine: bool = True,
                      patched: dict[int, set[str]] | None = None) -> list[dict]:
    cols = k.LADDER_COLS if mine else k.LADDER_COLS[:4]
    out = []
    for i, r in enumerate(rows, 1):
        out.append(k.data_row(i, cols, k.ladder_values(r, mine=mine), focused=r.k == focus_k,
                              colors=k.side_colors(r), actions=k.px_fmt(k.price(r.k)),
                              patched=(patched or {}).get(r.k, ())))
    return out


def ladder_body(rows: list[dict], *, mine: bool = True, sort: str | None = "Cumulative depth",
                direction: str = "ascending", chips=(), shown: int, total: int, banner_text=None, empty=None,
                left=None, filter_t2=None, export_reason=k.EXPORT_REASON, load_more: bool = True,
                focus_load: bool = False, below=None) -> dict:
    cols = k.LADDER_COLS if mine else k.LADDER_COLS[:4]
    return k.table_body(cols, rows, wd=PW, h=BODY_H, sort=sort, direction=direction,
                        filter_only=("My orders",), chips=chips, shown=shown, total=total, banner_text=banner_text,
                        banner_key="Shift+R", caption=("DOM ladder", LADDER_SCOPE), empty=empty, left=left,
                        filter_t2=filter_t2, export_reason=export_reason, load_more=load_more,
                        focus_load=focus_load, below=below)


def ladder_panel(body: dict, *, head_extra=(), table_on: bool = True, chips=()) -> dict:
    return k.panel("CMP-080 DockPanel · heatmap + DOM ladder (SCR-050)", LADDER_TITLE, body, w_=PW, h=PH,
                   table_on=table_on, chips=chips or [k.feed_chip("Live")], head_extra=head_extra,
                   note="the ladder table is kept beside the native grid (§6.2); the heatmap canvas is replaced in "
                        "place while Table is on")


def native_left(n_ask: int, n_bid: int, *, focus_k: int | None = None, book=None, describedby: bool = False,
                h: int | None = None) -> dict:
    """The native grid's visible depth: n_ask ask levels over n_bid bid levels around the touch."""
    rows = [r for r in (book or k.BOOK) if k.BOOK_BEST_BID_K - n_bid < r.k < k.BEST_ASK_K + n_ask]
    hh = h or BODY_H - (k.HEAD_H + 20 + k.HEAD_H)
    if k.ROW_H * (len(rows) + 1) > hh:
        raise ValueError(f"native ladder: {len(rows)} rows do not fit {hh} px")
    return k.native_ladder(rows, hh, focus_k=focus_k, describedby=describedby)


def sheet_table(name: str, cols: list[tuple[str, int]], rows: list[list[str]], *, typo: str | None = None,
                hi: int | None = None) -> dict:
    """A spec table drawn on a sheet frame: wrapped cells, 8 px padding a side, row heights from the text."""
    ty = typo or k.CAPTION
    hdr = k.hbox("header row", [k.hbox(f"th · {n}", [k.text("label", n, k.LABEL, k.TEXT_2, w=wd - 16)],
                                       {"padX": k.INSET_SM}, w=wd, h=24) for n, wd in cols],
                 {"fill": k.RAISED}, w=sum(wd for _n, wd in cols), h=24)
    out = [hdr]
    for i, r in enumerate(rows, 1):
        hs = [k.text_h(ty, k.text_lines(v, ty, wd - 16)) for v, (_n, wd) in zip(r, cols)]
        h = int(max(hs) + 8)
        cells = [k.vbox(f"td · {n}", [k.text("value", v, ty, k.TEXT_1, w=wd - 16)],
                        {"padX": k.INSET_SM, "padY": k.INSET_XS}, w=wd, h=h) for v, (n, wd) in zip(r, cols)]
        out.append(k.hbox(f"row {i:02d}", cells, {"align": "start", "fill": k.SELECTED if i == hi else None,
                                                  "stroke": k.BORDER_SUBTLE, "strokeWidth": k.HAIR,
                                                  "strokeAlign": "inner"}, w=sum(wd for _n, wd in cols), h=h))
    return k.vbox(name, out, None, w=sum(wd for _n, wd in cols))
