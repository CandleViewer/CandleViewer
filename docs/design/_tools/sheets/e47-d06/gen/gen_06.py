"""Board 06 `E47-D06 / 06 equal-status-headers` (dark): §7 — the `View │ Table` switch in every inventory panel's
header; §10's T2 controls: the row actions, My levels only, Export CSV, the ladder's trade keys (one notice) and the
view-as one notice."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BODY_H, PW, PX0, PY0, grid_y, k, ladder_body, ladder_panel,  # noqa: E402
                    ladder_table_rows, native_left, profile_body, profile_panel)

NN = 6
LEFT_W = 328
TX = PX0 + k.PX[k.INSET_SM] + LEFT_W + 12
# the inventory panels with a canvas (§2's screens; SCR-049 is a grid of SCR-030s and has no row, BQ-2's rider)
PANELS = (("SCR-030", "candles", "Chart"), ("SCR-038", "profile", "View"), ("SCR-050", "heatmap", "View"),
          ("SCR-052", "cvd", "View"), ("SCR-053", "bubbles", "View"), ("SCR-055", "speed", "View"),
          ("SCR-056", "strip", "View"), ("SCR-082", "graph", "View"))
MENU_W = 276
ACT_X = PX0 + k.PX[k.INSET_SM] + sum(c.w for c in k.PROFILE_COLS)  # the profile rows' actions column (frame x)


def switches() -> dict:
    screens = {s for iv in k.INV.values() for s in k.re.findall(r"SCR-\d+", iv["screen"])}
    if {p[0] for p in PANELS} | {"SCR-049"} != screens:
        raise SystemExit(f"gen_06: the panels {sorted(p[0] for p in PANELS)} are not §2's screens {sorted(screens)}")
    pw, ph = (PW - k.GUTTER) // 2, (BODY_H + k.HEAD_H - 3 * k.GUTTER) // 4
    cells = [k.panel(f"CMP-080 DockPanel · {scr}", k.screen_title(scr),
                     k.mini_plot(f"canvas · {kind}", kind, pw - 2, ph - k.HEAD_H - 2), w_=pw, h=ph, first=first,
                     note=f"{scr}: the switch in the header for every role, the Viewer included (R-8)")
             for scr, kind, first in PANELS]
    rows = [k.hbox(f"dock row {i + 1}", cells[2 * i:2 * i + 2], {"gap": k.INSET_SM, "align": "start"}, w=PW, h=ph)
            for i in range(4)]
    return k.window(k.BOARDS[NN].frames[0], rows)


def _menu_y(row: int) -> int:
    return grid_y(row) + k.ROW_H


def row_action(why: bool = True) -> list[dict]:
    items = [k.t2_item(lab, k.reason(perm) if why else None, focused=(i == 0 and why), wd=MENU_W - 8)
             for i, (lab, perm) in enumerate(k.ROW_ACTIONS)]
    return [*items, k.menu_item(k.COPY_ROW, wd=MENU_W - 8, lead="copy")]


def t2_row_action() -> dict:
    poc = k.PROF_META["poc"]
    row = [x.k for x in k.PROFILE].index(poc) + 1
    items = row_action()
    mh = round(k.est_height(k.menu("probe", items, wd=MENU_W, x=0, y=0)))
    m = k.menu(f"Actions for {k.prof_px(poc)}", items, wd=MENU_W, x=ACT_X - MENU_W + 40, y=grid_y(row) - mh,
               )  # opens upward: the row sits low in the grid
    return k.window(k.BOARDS[NN].frames[1], [profile_panel(profile_body(focus_k=poc))], overlays=[
        m, k.callout("T2 row actions", [f"{len(k.ROW_ACTIONS)} gated items keep their role and full label with "
                                        "aria-disabled=\"true\" (2a inline); ↑ / ↓ land on them without activating",
                                        f"Enter re-shows the reason with one polite announcement (W-11); "
                                        f"{k.COPY_ROW} is not gated"], ACT_X + 56, grid_y(2), wd=280)])


def t2_my_levels() -> dict:
    rows = ladder_table_rows(k.ladder_window_rows(4), None, mine=False)
    body = ladder_body(rows, mine=False, sort="Price", direction="descending", shown=len(k.BOOK), total=len(k.BOOK),
                       left=native_left(11, 11))
    m = k.menu("Add filter", [k.t2_item(k.MY_LEVELS_LABEL, k.reason(k.MY_LEVELS_PERM), focused=True, wd=MENU_W - 8)],
               wd=MENU_W, x=PX0 + 8, y=k.TOP_H + k.DOCK_PAD + 2 * k.HEAD_H)
    return k.window(k.BOARDS[NN].frames[2], [ladder_panel(body)], overlays=[
        m, k.callout("without orders:read", [f"{k.MY_LEVELS_LABEL} is T2 (2a inline) with \""
                                             f"{k.reason(k.MY_LEVELS_PERM)}\"",
                                             "The panel draws no own orders: the My orders column and the N-6 flag "
                                             "word are absent (§10)"], TX, grid_y(11), wd=360)])


def t2_export() -> dict:
    body = profile_body(focus_k=None)
    ft = k.walk(body)
    fx = 0
    for p, n in ft:
        if n["name"].startswith("button · Export CSV"):
            fx = 1
    if not fx:
        raise SystemExit("gen_06: no Export CSV button")
    ring_y = PY0 + k.HEAD_H + BODY_H - k.HEAD_H
    return k.window(k.BOARDS[NN].frames[3], [profile_panel(body)], overlays=[
        k.tag("focus: Export CSV (aria-disabled, in the Tab order)", PX0 + PW - 420, ring_y - 20),
        k.callout("Export CSV", [f"A state, not a permission: \"{k.EXPORT_REASON}\" is the PROPOSED key "
                                 f"{k.EXPORT_KEY} (owner E11-D04), never an rbac.* reason (§10)",
                                 "2a inline: the reason beside the button in the CMP-099 footer; the lock glyph "
                                 "leads the full label; raised fill, hairline, no opacity"],
                  PX0 + 860, grid_y(16), wd=320)])


def t2_trade_keys() -> dict:
    why = k.reason(k.TRADE_PERM)
    nat = native_left(12, 12, focus_k=k.BOOK_BEST_BID_K, describedby=True, h=BODY_H - 16)
    body = k.hbox("view", [nat, k.mini_plot("canvas · heatmap", "heatmap", PW - LEFT_W - 24, BODY_H - 16)],
                  {"gap": k.INSET_SM, "pad": k.INSET_SM, "align": "start"}, w=PW, h=BODY_H)
    return k.window(k.BOARDS[NN].frames[4], [ladder_panel(body, table_on=False,
                                                         head_extra=[k.notice(why, wd=240)])], overlays=[
        k.callout("one notice", [f"The trade keys are gated without {k.TRADE_PERM}: one 2a notice in the panel "
                                 f"header (\"{why}\"); every row's aria-describedby points at it",
                                 "No key is named here: `05`:67–68, `14`:1217 and `15`:1235 disagree (D06-C16); the "
                                 "table alternatives expose data only"], PX0 + LEFT_W + 40, grid_y(3), wd=360)])


def t2_view_as() -> dict:
    why = k.view_as_reason()
    win = k.ladder_window_rows(6)
    fk = k.BOOK_BEST_BID_K
    rows = ladder_table_rows(win, fk)
    t2f = k.t2_button(k.MY_LEVELS_LABEL, None)
    body = ladder_body(rows, sort="Price", direction="descending", chips=(), shown=len(k.BOOK), total=len(k.BOOK),
                       left=native_left(11, 11, describedby=True), filter_t2=t2f, export_reason=None)
    act_x = TX + sum(c.w for c in k.LADDER_COLS)
    m = k.menu(f"Actions for {k.px_fmt(k.price(fk))}", row_action(why=False), wd=MENU_W, x=act_x - MENU_W + 40,
               y=_menu_y([r.k for r in win].index(fk) + 1))
    return k.window(k.BOARDS[NN].frames[5], [ladder_panel(body, head_extra=[k.notice(why, wd=260)])], overlays=[
        m, k.callout("view-as", [f"Under an active view-as the panel is read-only for the session: one notice "
                                 f"carries \"{why}\" (rbac.view_as)",
                                 f"The trade keys, the row actions, {k.MY_LEVELS_LABEL} and {k.EXPORT_LABEL} all "
                                 "point their aria-describedby at it, with no per-item reason (§10)"],
                  TX, grid_y(15), wd=360)])


def frames() -> list[dict]:
    return [switches(), t2_row_action(), t2_my_levels(), t2_export(), t2_trade_keys(), t2_view_as()]


def blocks() -> list[tuple[str, list[str]]]:
    f = k.BOARDS[NN].frames
    t2 = f"§10 L{k.T2_LINE}"
    return [(f[0], [f"§7 L{k.L('## 7. Equal-status')}: the switch in each of {len(PANELS)} canvas panels' headers "
                    "(SCR-049 is a grid of SCR-030s); Alt+T per panel context (D06-A16)"]),
            (f[1], [f"{t2}: " + "; ".join(f"{lab} → \"{k.reason(p)}\"" for lab, p in k.ROW_ACTIONS)]),
            (f[2], [f"{t2}: {k.MY_LEVELS_LABEL} without {k.MY_LEVELS_PERM} → \"{k.reason(k.MY_LEVELS_PERM)}\""]),
            (f[3], [f"{t2}: {k.EXPORT_LABEL} → \"{k.EXPORT_REASON}\" ({k.EXPORT_KEY}, PROPOSED)"]),
            (f[4], [f"{t2}: the ladder's trade keys without {k.TRADE_PERM} → one notice \"{k.reason(k.TRADE_PERM)}\""]),
            (f[5], [f"{t2}: rbac.view_as → one notice \"{k.view_as_reason()}\" (synthetic target name)"]),
            ("T2 look (every frame)", ["CMP-079 RbacGate; aria-disabled=\"true\", never disabled or inert; the "
                                       "CMP-019 lock glyph (\"Not available\") leads the full label in "
                                       "color.text.tertiary; the reason in color.text.secondary; raised fill with a "
                                       "color.border.default hairline; never the disabled text colour or opacity"])]


def notes() -> None:
    k.copy_key(f"{k.EXPORT_KEY} (PROPOSED, owner E11-D04): \"{k.EXPORT_REASON}\", the Export CSV T2 reason")
    k.copy_key("rbac.permission (E09-D09 §3.1 template): the row-action, My levels only and trade-key reasons")
    k.copy_key("rbac.view_as (E09-D09 §3.1 template, PROPOSED use here): the view-as notice, synthetic target name")
    k.deviate("the row-action reasons follow §10 (E09-D09 §3.1's rbac.permission), not D04E11:794's older "
              "\"your role can't create alerts\" wording")
    k.ambiguity("the switch's first segment reads \"Chart\" on the chart panel (D04E11 D1 verbatim) and \"View\" "
                "on the others (§7's generic name); each panel's own words are its spec's (copy gap)")
    k.copy_gap("the panel titles are `14`'s screen headings, \" panel\" and the parenthesis dropped")
    k.ambiguity("the one notice sits in the panel header after the switch (§10: \"the panel header carries one 2a "
                "notice\"); its width is a kit choice")


def main() -> None:
    notes()
    p, md, pk = k.build(NN, frames(), blocks(), per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
