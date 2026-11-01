"""E47-D04 / 06 overlay-palette: SCR-012 and SCR-013: the field and the list stop, Esc restore, and a menu's
Tab-out (§4, §9)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies, at_body  # noqa: E402

NN = 6
F_PAL, F_CHEAT, F_MENU = k.frames_of(NN)
L_SCR012 = "`14` SCR-012 wireframe, `14`:354-361"
PAL_W = 560
# SCR-012's wireframe rows for the query "flat" (`14` SCR-012); the result count W-6 is derived from them
QUERY = "flat"
RESULTS = ("Flatten all positions (all accounts)", "Flatten BTCUSDT on Main", "Settings -> Flatten confirmation",
           "Symbol: FLOKIUSDT")
PAL_HINT = "Enter run - Tab complete - Esc close"


def field(chars: str, w_: int, *, focused: bool, name: str) -> k.Node:
    f = k.hbox(name, [k.icon("glyph", "search", k.TEXT_2), k.text("value", chars, k.BODY, k.TEXT_1)],
               {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.CANVAS, "radius": k.R_CONTROL, "stroke": k.BORDER,
                "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w_, h=k.CONTROL_H)
    return k.focus_ring(f) if focused else f


def frame_palette() -> tuple[k.Node, tuple[str, list[str]]]:
    iw = PAL_W - 2 * 12
    rows = [k.hbox(f"option {i}", [k.text("label", r, k.BODY, k.TEXT_1)],
                   {"padX": k.INSET_SM, **({"fill": k.SELECTED} if i == 1 else {})}, w=iw, h=k.ROW_H,
                   note="aria-selected (the active descendant)" if i == 1 else None)
            for i, r in enumerate(RESULTS, 1)]
    pal = k.vbox("CMP-059 command palette", [field(QUERY, iw - 12, focused=True, name="combobox field"),
                                             k.vbox("listbox", rows, None, w=iw, h=len(rows) * k.ROW_H),
                                             k.text("hint", PAL_HINT, k.CAPTION, k.TEXT_2)],
                 {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.OVERLAY, "radius": k.R_DIALOG, "stroke": k.BORDER,
                  "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=PAL_W,
                 note='role="combobox" + aria-activedescendant; the results role="listbox"')
    ovl, (dx, dy, dw, dh) = k.modal(pal, y=96)
    say = k.w("W-6", len(RESULTS))
    ov = [ovl, k.marker(1, dx - 28, dy + 18, name="stop 1 · field"), k.marker(2, dx - 28, dy + 56,
                                                                             name="stop 2 · list"),
          k.callout("W-6", ["Result count (polite, ≤ 1 Hz):", f'"{say}"', "Esc: focus returns to the invoker (R-7)"],
                    dx + dw + 24, dy, 280)]
    fr = k.workspace_window(F_PAL, bodies(), overlays=ov, note="Ctrl+K opened the palette; focus in its field")
    lines = [k.arch("Tab sequence", "overlay / palette"), k.arch("Initial target", "overlay / palette"),
             k.arch("Restore on exit", "overlay / palette"),
             f"Drawn: the query \"{QUERY}\" and SCR-012's wireframe rows ({L_SCR012}); the first row is the active "
             f"descendant (selected surface, no second ring); W-6 (§15 L{k.COPY['W-6'].line}, PROPOSED): \"{say}\"",
             f"{k.rule('R-6')}: the field, never a destructive command, has initial focus; a destructive row routes "
             "into its confirm flow",
             k.arch("Roles (T2 / T3)", "overlay / palette")]
    return fr, k.frame_block(F_PAL, lines, keyboard="↑/↓ move the active option; Enter runs; Esc closes and restores")


CHEAT = (("Global", (("Ctrl+K", "command palette"), ("Ctrl+/", "hotkey cheatsheet"),
                     ("Ctrl+\\", "cycle the regions (§3)"), ("F11", "full-screen workspace"), ("Alt+1..9", "nav rail"))),
         ("DOM", (("Tab", "leave the ladder in one press (§6.1)"), ("Esc", "innermost transient, then the header"),
                  ("Ctrl+Delete", "cancel the focused order (§6.3)"))))


def frame_cheat() -> tuple[k.Node, tuple[str, list[str]]]:
    cw = 340
    cols = []
    for grp, rows in CHEAT:
        rs = [k.hbox(f"row {key}".replace("/", k.SLASH), [k.text("keys", key, k.NUM, k.TEXT_1, w=96), k.text("action", act, k.BODY, k.TEXT_2)],
                     {"gap": k.INSET_MD, "padX": k.INSET_SM}, w=cw, h=k.ROW_H) for key, act in rows]
        cols.append(k.vbox(f"group {grp}", [k.text("h3", grp, k.LABEL, k.TEXT_2), *rs], {"gap": k.STACK_XS}, w=cw))
    sheet = k.vbox("CMP-094 hotkey overlay", [k.text("title", "Hotkey cheatsheet", k.HEADING_MD, k.TEXT_1),
                                              field("Search hotkeys", 300, focused=True, name="search field"),
                                              k.hbox("columns", cols, {"gap": k.INSET_LG, "align": "start"})],
                   {"gap": k.STACK_MD, "pad": k.DIALOG_PAD, "fill": k.OVERLAY, "radius": k.R_DIALOG,
                    "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=2 * cw + 16 + 48,
                   note="rendered as a real table for screen readers (`14` SCR-013)")
    ovl, (dx, dy, dw, _dh) = k.modal(sheet, y=110)
    ov = [ovl, k.marker(1, dx - 28, dy + 52, name="stop 1 · search"), k.marker(2, dx - 28, dy + 110,
                                                                              name="stop 2 · table"),
          # live check fold: flush with the sheet's right edge (at + 24 it spilled 16 px past the frame)
          k.callout("restore", ["Esc: closes; focus returns to the invoker (R-7)"], dx + dw, dy, 260)]
    fr = k.workspace_window(F_CHEAT, bodies(), overlays=ov, note="Ctrl+/ opened SCR-013; focus in its search")
    k.copy_gap('"Hotkey cheatsheet", "Search hotkeys" and the action words: `14` SCR-013 / SCR-010 (L376, L302 of '
               "14) and §3 / §6; the bindings themselves are E47-D09's (#1308)")
    lines = [k.arch("Initial target", "overlay / palette"), k.arch("Entry and exit keys", "overlay / palette"),
             "Drawn: SCR-013 grouped by context (Global, DOM: `14` SCR-013's groups); Global rows from `14`:302; DOM "
             "rows from this spec's §6.1 and §6.3 (the keys are E47-D09's rows; out of scope here)",
             f"Overlay archetype (§3 L{k.L('| overlay / palette | none; a modal overlay')}): a modal overlay traps like "
             "a dialog"]
    return fr, k.frame_block(F_CHEAT, lines, keyboard="type to filter; Tab to the table; Esc closes and restores")


def frame_menu() -> tuple[k.Node, tuple[str, list[str]]]:
    px, py, pw, _ph = k.GEO["positions"]
    items = [k.placeholder(f"menu item {i}", 160, 12) for i in (1, 2, 3, 4)]
    rows = [k.hbox(f"menuitem {i}", [it], {"padX": k.INSET_SM}, w=200, h=k.ROW_H) for i, it in enumerate(items, 1)]
    rows[0] = k.focus_ring(dict(rows[0], w=188), name="menuitem 1 (focused)")
    menu = k.vbox("menu · Positions header", rows, {"gap": k.STACK_XS, "pad": k.INSET_XS, "fill": k.OVERLAY,
                                                    "radius": k.R_CARD, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                    "strokeAlign": "inner"}, w=212, h=round(sum(k.est_height(r) for r in rows) + 4 * (len(rows) - 1) + 8), x=px + pw - 216, y=py + 28,
                  abs=True, note='role="menu"; no Tab stops of its own')
    ov = [menu, k.marker(1, px + pw - 244, py + 36, name="menu · focused item"),
          k.marker(2, *at_body("positions", 0.5, 0.92), name="after Tab · next stop"),
          k.callout("Tab-out", ["Tab in an open menu: the menu closes (R-7), then focus moves to the next stop — the "
                                "Positions grid"], px + 20, py + 200, 300)]
    fr = k.workspace_window(F_MENU, bodies(), focus_panel="positions", overlays=ov,
                            note="the Positions header's menu open, first item focused; Tab closes it and moves on")
    lines = [k.arch("Tab sequence", "overlay / palette"),
             f"§3 L{k.L('| overlay / palette | none; a modal overlay')}: a ring key in a non-modal menu or popover "
             "closes it (R-7), then moves",
             f"§9.1 L{k.L('| menu, popover')}: initial target the first item that is neither T2 nor sentence-form; "
             "never a destructive item (R-6)",
             "Drawn: the menu's items are the host's (placeholders); stop 1 the focused item, stop 2 where Tab lands"]
    return fr, k.frame_block(F_MENU, lines, keyboard="↑/↓ inside; Esc closes and restores to the menu button; Tab "
                                                     "closes and moves on")


def build(theme: str = "dark") -> None:
    del theme
    fr = [frame_palette(), frame_cheat(), frame_menu()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
