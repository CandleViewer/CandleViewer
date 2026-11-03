"""E19-D04 frame builders: the preset flow (§2; boards 01–03, 10), period anchoring (§3; boards 04, 05, 09, 10), drawing
anchors (§4; boards 06, 07, 09), the gesture-conflict matrix (§5; board 08). Every drawn word is the spec's §9 deck
(k.W), D03's or D02's deck, an E14 / E17 source string (say / k.S check it verbatim) or a copy gap noted with its
source; every number is derived from the kit's synthetic world (seed 439)."""
from __future__ import annotations

import math
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d04kit as k  # noqa: E402
import panel as P  # noqa: E402
from e19d04kit import Node, box, ellipse, hbox, icon, rect, text, vbox  # noqa: E402
from panel import ChartGeo, Host, Panel, control, gap_word, hidden, marker_box, say  # noqa: E402

T2_ITEM_H = 40  # a T2 item: the 13 px label (19 px line at 1.4 in Penpot) over the 11 px reason, 4 px above and below
ITEM_H = 24  # CMP-041 items: size.row.height at compact (`15` CMP-041 tokens)
MENU_W = 264  # kit choice: the panel's width less its 8 px insets
DLG_W = 400  # CMP-043 size sm: at most 420 px wide (`15` CMP-043 props)
SCRIM_KIT = "the CMP-043 scrim drawn as color.surface.sunken at opacity.scrim (its palette.black is a primitive)"


# --- words
def utc(t: datetime) -> str:
    return f"{k.ts(t)} UTC"


def range_words(a: datetime, b: datetime) -> str:
    """Kit reading R-K2: the legend's two times (R-2) in R-7's form, as W-26 joins them."""
    k.reading("R-K2: a range's legend words are its two times joined as W-26 joins them, \"{start} to {end} UTC\" "
              "(R-2, R-7); {start} / {end} fill as YYYY-MM-DD HH:MM and the deck's own \"UTC\" closes the pair, so a "
              "sentence never reads \"UTC UTC\"")
    return f"{k.ts(a)} to {k.ts(b)} UTC"


def preset_name(p: k.Preset) -> str:
    if p.builtin:
        return k.W(2)
    k.copy_gap(f'"{p.name}": a synthetic user preset name (kit choice; 1–80 characters, `22`:10802)')
    return p.name


def preset_profile(p: k.Preset, row_ticks: int | None = None) -> k.Profile:
    return k.build_profile(k.SESSION.label, "Session", k.bars_between(k.DAY0, k.NOW), complete=False,
                           row_ticks=row_ticks or p.row_ticks, va_pct=p.va_pct)


def at_bottom_left(nodes: list[Node], *, x: int = 16, bottom: int = k.WIN_H - P.STATUS_H - P.TIME_AXIS - 8,
                   gap: int = 8) -> list[Node]:
    """Board markers stacked upward from the chart's lower-left corner (over the plot, never over the panel)."""
    out, y = [], bottom
    for n in reversed(nodes):
        h = math.ceil(k.est_height(n))
        y -= h
        out.append(n | {"x": x, "y": y, "h": h})
        y -= gap
    return list(reversed(out))


def announce(chars: str, *, label: str = "polite announcement (once)", w: int = 380) -> Node:
    return hidden(chars, w=w, label=label)


# --- CMP-041 menu
def menu(name: str, items: list[dict[str, Any]], *, w: int = MENU_W, note: str | None = None) -> Node:
    """CMP-041 (`15` tokens): color.surface.overlay, elevation.popover, radius.card, a 1 px color.border.default edge
    and separators; items at size.row.height, type.ui.body color.text.primary; the active item color.surface.hover
    with the inset ring color.focus.ring. Item kinds: radio (checked), action, text (a row, not an item), sep, t2 (2a:
    CMP-019 lock + label color.text.tertiary, its own reason as the second line, color.text.secondary; no fill of its
    own: the item sits on the menu's color.surface.overlay, §1.4)."""
    rows: list[Node] = []
    inner = w - 2 * k.PX[k.INSET_XS]

    def item(it: dict[str, Any]) -> Node:
        kind, label = it["kind"], it.get("label", "")
        lead: Node | None = None
        color = k.TEXT_1
        if kind == "radio":
            lead = icon("check", "check", k.TEXT_1, k.ICON_SM) if it.get("checked") else box("check slot", [], w=12,
                                                                                               h=12)
        elif kind == "t2":
            lead, color = P.lock(), k.TEXT_3
        else:
            lead = box("glyph slot", [], w=12, h=12)
        if kind == "t2":
            kids = [lead, vbox("label + reason", [text("label", label, k.BODY, color),
                                                  text("reason · W-20", it["reason"], k.CAPTION, k.TEXT_2)],
                               note="the full label, then its own reason as the item's second line "
                                                "(CMP-041 disabledReason?, §1.4)")]
        else:
            kids = [lead, text("label", label, k.BODY, color)]
        if it.get("shortcut"):
            kids.append(text("shortcut", it["shortcut"], k.NUM_SM, k.TEXT_3))
        active = it.get("active", False)
        o = {"padX": k.INSET_SM, "gap": k.INSET_SM, "radius": k.R_CONTROL,
             **({"fill": k.HOVER, "stroke": k.RING, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner"} if active
                else {})}
        role = {"radio": 'menuitemradio' + (', aria-checked="true"' if it.get("checked") else ""),
                "t2": 'menuitem, aria-disabled="true" (never disabled), aria-describedby -> its own second line (§1.4)',
                "action": "menuitem"}[kind]
        return hbox(f"item · {it.get('key', label)}".replace("/", k.SLASH), kids, o, w=inner,
                    h=T2_ITEM_H if kind == "t2" else ITEM_H,
                    note=role + ("; the active item" if active else ""))

    for it in items:
        kind = it["kind"]
        if kind == "sep":
            rows.append(rect("separator", inner, 1, k.BORDER, note="CMP-041 separator"))
        elif kind == "text":
            rows.append(hbox(f"row · {it['label']}", [box("glyph slot", [], w=12, h=12),
                                                     text("label", it["label"], k.CAPTION, k.TEXT_2)],
                             {"padX": k.INSET_SM, "gap": k.INSET_SM}, w=inner, h=ITEM_H,
                             note="a text row, not a menu item (§2.2)"))
        else:
            rows.append(item(it))
    m = vbox(f"CMP-041 {name}", rows, {"pad": k.INSET_XS, "fill": k.OVERLAY, "stroke": k.BORDER,
                                        "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD,
                                        "shadow": k.EL_POPOVER}, w=w, note=note or 'role="menu"')
    m["h"] = math.ceil(k.est_height(m))
    return m


def preset_items(applied: k.Preset, *, modified: bool = False, restore: bool = False, empty: bool = False,
                 view_as: bool = False, active: str | None = None) -> list[dict[str, Any]]:
    """§2.2's items, in order, for the state: the list (built-in first, the applied one checked), then the writes,
    Reset, Restore."""
    its: list[dict[str, Any]] = [{"kind": "radio", "label": preset_name(k.BUILTIN), "checked": applied.builtin}]
    if empty:
        its.append({"kind": "text", "label": k.W(10)})
    else:
        its += [{"kind": "radio", "label": preset_name(p), "checked": p == applied} for p in k.USER_PRESETS]
    its.append({"kind": "sep"})
    name = preset_name(applied)
    writes: list[dict[str, Any]] = [{"kind": "action", "label": k.W(3), "key": "Save as new"}]
    if not applied.builtin and modified:
        writes.append({"kind": "action", "label": k.W(4, name=name), "key": "Save changes"})
    if not applied.builtin and not empty:
        writes += [{"kind": "action", "label": k.W(5), "key": "Rename"},
                   {"kind": "action", "label": k.W(6), "key": "Delete"}]
    if view_as:
        user = gap_word(k.VIEW_AS_USER, "W-20's {user}: a synthetic display name (no account identifier, R-1)")
        writes = [dict(w_, kind="t2", reason=k.W(20, user=user)) for w_ in writes]
    its += writes
    tail: list[dict[str, Any]] = []
    if modified:
        tail.append({"kind": "action", "label": k.W(7, name=name), "key": "Reset"})
    if restore:
        tail.append({"kind": "action", "label": k.W(18), "key": "Restore"})
    if tail:
        its += [{"kind": "sep"}, *tail]
    for it in its:
        if active and it.get("key", it.get("label")) == active:
            it["active"] = True
    return its


# --- buttons, field, dialog, toast
def btn_primary(name: str, label: str, *, danger: bool = False, h: int = 28) -> Node:
    return hbox(name, [text("label", label, k.CAPTION, k.TEXT_ON_ACTION)],
                {"padX": k.INSET_MD, "radius": k.R_CONTROL, "fill": k.DANGER if danger else k.ACTION_PRIMARY}, h=h,
                note="CMP-001 danger" if danger else "CMP-001 primary")


# live-check fold: drawn widths of a selected field value, read back on the live board (board 02's rename field drew
# "Scalp tight" 66 px wide, the estimate 80), so the selection box is the drawn name + 2 px
LIVE_TEXT_W = {"Scalp tight": 66}


def btn(name: str, label: str, *, focused: bool = False, h: int = 28) -> Node:
    return control(name, label, h=h, focused=focused)


def field(label: str, value: str, *, w: int, selected: bool = False, invalid: bool = False,
          focused: bool = True, below: list[Node] | None = None) -> Node:
    """CMP-040 text input: the label W-12, the input (color.surface.sunken, 1 px border; the 2 px focus ring when
    focused), the selection, and what stands under it (helper, error)."""
    kids: list[Node] = []
    tw = LIVE_TEXT_W.get(value, round(k.text_w(value, k.BODY)))
    if selected:
        k.fallback("selection")
        kids.append(rect("selection", tw + 2, 18, k.SELECTED, x=7, y=5, note="the name selected"))
        k.live("the field's selection box is sized from the estimated text width: after touchTexts, fit its width to "
               "the drawn name (+ 2 px)")
    kids.append(text("value", value, k.BODY, k.TEXT_1, x=8, y=5))
    inp = box("input", kids, {"fill": k.SUNKEN, "radius": k.R_CONTROL, "stroke": k.RING if focused else k.BORDER,
                              "strokeWidth": k.FOCUS_W if focused else k.HAIR,
                              "strokeAlign": "outer" if focused else "inner"}, w=w, h=28,
              note=('aria-invalid="true", aria-describedby -> the conflict message (§2.3)' if invalid else
                    "initial focus (§2.3)" if focused else None))
    # never clips: the focused input's 2 px outer ring stands outside the column (PNG review: board 02's rings were
    # cut to their top edge)
    return vbox(f"CMP-040 field · {label}", [text("label", label, k.CAPTION, k.TEXT_2), inp, *(below or [])],
                {"gap": k.STACK_XS, "clip": False}, w=w)


def dialog(name: str, title: str, body: list[Node], footer: list[Node], *, role: str = "dialog") -> Node:
    """CMP-043 size sm (`15` tokens): color.surface.overlay, elevation.dialog, radius.dialog, 1 px default edge,
    space.dialog.padding, space.stack.md; title type.ui.heading-sm; the footer right-aligned."""
    inner = DLG_W - 2 * k.PX[k.DIALOG_PAD]
    # the footer never clips: a focused button's 2 px outer ring stands outside the 28 px row (PNG review: board 02's
    # Cancel ring was cut top and bottom)
    foot = hbox("footer", footer, {"gap": k.INSET_SM, "justify": "end", "clip": False}, w=inner, h=28)
    d = vbox(name, [text("title", title, k.HEADING_SM, k.TEXT_1, w=inner), *body, foot],
             {"gap": k.STACK_MD, "pad": k.DIALOG_PAD, "fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_DIALOG, "shadow": k.EL_DIALOG}, w=DLG_W,
             note=f'role="{role}", aria-modal, aria-labelledby the title; Esc and Cancel return focus to the Presets '
                  "menu button")
    d["h"] = math.ceil(k.est_height(d))
    return d


def over_window(kids: list[Node], dlg: Node) -> list[Node]:
    k.fallback("scrim")
    k.reading(SCRIM_KIT)
    return kids + [rect("scrim", k.WIN_W, k.WIN_H, k.SUNKEN, {"opacity": k.SCRIM}, x=0, y=0),
                   dlg | {"x": (k.WIN_W - DLG_W) // 2, "y": max(48, (k.WIN_H - dlg["h"]) // 2)}]


def toast(name: str, words: str, action: str, *, note: str, words_w: int | None = None) -> Node:
    """CMP-045 with an action (`15` CMP-045): color.surface.raised, elevation.3 (D07E14 L299's binding), the action a
    CMP-001 secondary button; never takes focus."""
    k.fallback("elevation3")
    t = hbox(f"CMP-045 toast · {name}", [text("words", words, k.CAPTION, k.TEXT_1, **({"w": words_w} if words_w else {})),
                     control("action", action, h=24)],
             {"gap": k.INSET_MD, "padX": k.INSET_MD, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_CARD, "shadow": "elevation.3"}, h=40, note=note)
    t["w"] = math.ceil(k.est_width(t))
    return t


def toast_at(t: Node) -> Node:
    """Kit reading R-K4: CMP-045's stack sits bottom-right, over the docked panel's legend row, never over the plot
    stop, an edge handle or the Presets button (§2.6)."""
    k.reading("R-K4: CMP-045's stack is drawn at the window's lower right, 8 px above the status bar, over the docked "
              "panel's legend controls — never over the chart's plot stop, an edge handle or the Presets button "
              "(§2.6)")
    return t | {"x": k.WIN_W - t["w"] - 8, "y": k.WIN_H - P.STATUS_H - t["h"] - 8}


# --- marks on the bound chart (pane coordinates)
def band(g: ChartGeo, a: datetime, b: datetime | None, *, edges: tuple[str, ...] = ("start", "end"),
         name: str = "profile range band") -> list[Node]:
    """The range band: color.surface.selected over the plot with color.focus.ring edges (§11; D03 L336); b None: open
    toward the plot's right edge (Anchored)."""
    x0 = g.x_at(a)
    x1 = g.x_at(b) if b else g.plot_w
    top, hgt = g.plot_top, g.plot_bot - g.plot_top
    out = [rect(name, round(x1 - x0), round(hgt), k.SELECTED, x=round(x0), y=round(top),
                note="color.surface.selected; one Tab stop: the plot stop (the band is not focusable)")]
    for e, x in (("start", x0), ("end", x1)):
        if e in edges:
            out.append(rect(f"{name} · {e} edge", 2, round(hgt), k.RING, x=round(x - 1), y=round(top)))
    return out


def handle_glyph(name: str, cx: float, cy: float, *, note: str | None = None) -> Node:
    """E14's handle language (§11): a color.text.primary dot in a color.border.strong ring, 8 px."""
    k.fallback("handle")
    return ellipse(name, 8, 8, {"fill": k.TEXT_1, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                "strokeAlign": "outer"}, x=round(cx - 4), y=round(cy - 4), note=note)


def target_outline(name: str, cx: float, cy: float) -> Node:
    return rect(f"board marker · {name} 24 × 24 target", 24, 24, None, {"stroke": k.BORDER_STRONG,
                                                                        "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                x=round(cx - 12), y=round(cy - 12), note="board marker: the size.target.min pointer target")


def edge_handles(g: ChartGeo, a: datetime, b: datetime, *, target: str | None = None) -> list[Node]:
    cy = (g.plot_top + g.plot_bot) / 2
    out = []
    for word, t in (("start", a), ("end", b)):
        out.append(handle_glyph(f"edge handle · {word}", g.x_at(t), cy, note="ew-resize on hover; 24 × 24 target"))
        if target == word:
            out.append(target_outline(f"edge handle {word}", g.x_at(t), cy))
    return out


def cursor(kind: str, x: float, y: float) -> Node:
    """A CSS cursor stand-in at (x, y) (FALLBACKS cursor): the shape plus its keyword; PROPOSED (D04-OQ3)."""
    k.fallback("cursor")
    ink = k.TEXT_1
    if kind == "crosshair":
        shape = [rect("h", 15, 1, ink, x=0, y=7), rect("v", 1, 15, ink, x=7, y=0)]
    elif kind == "ew-resize":
        shape = [rect("bar", 15, 2, ink, x=0, y=7), rect("end a", 2, 8, ink, x=0, y=4), rect("end b", 2, 8, ink, x=13,
                                                                                          y=4)]
    elif kind == "ns-resize":
        shape = [rect("bar", 2, 15, ink, x=7, y=0), rect("end a", 8, 2, ink, x=4, y=0), rect("end b", 8, 2, ink, x=4,
                                                                                          y=13)]
    else:
        shape = [rect("glyph box", 10, 12, None, {"stroke": ink, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=3,
                      y=2)]
    word = text("keyword", kind, k.NUM_SM, k.TEXT_1, x=20, y=1)
    w = 20 + round(k.text_w(kind, k.NUM_SM)) + 4
    return box(f"board marker · cursor {kind}", [rect("backing", w, 16, k.CANVAS, x=0, y=0), *shape, word],
               w=w, h=16, x=round(x - 7), y=round(y - 7), note="board marker: the CSS cursor keyword (§5)")


def anchor_mark(g: ChartGeo, t: datetime) -> list[Node]:
    """The anchor marker, color.text.primary (§11; D03 L337): a 2 px line the plot's height and an 8 × 8 head."""
    x = g.x_at(t)
    top, hgt = g.plot_top, g.plot_bot - g.plot_top
    return [rect("anchor marker · line", 2, round(hgt), k.TEXT_1, x=round(x - 1), y=round(top)),
            rect("anchor marker · head", 8, 8, k.TEXT_1, x=round(x - 4), y=round(top))]


def open_end(g: ChartGeo) -> Node:
    return icon("open end · chevron-right", "chevron-right", k.TEXT_1, k.ICON, x=round(g.plot_w - 20),
                y=round((g.plot_top + g.plot_bot) / 2 - 8), note="the open end: the profile extends with new bars")


def rectangle(g: ChartGeo, span: tuple[datetime, datetime], *, selected: bool = False, locked: bool = False,
              name: str = "drawing · rectangle") -> list[Node]:
    """The synthetic rectangle (E14's drawing; its ink is E14-D03's, a greyscale placeholder here: a 1 px
    color.text.secondary outline): the selected state carries the four corner handles; locked, E14's lock glyph at the
    first anchor (D02E14 L283)."""
    lo, hi = k.rect_prices(span)
    x0, x1 = g.x_at(span[0]), g.x_at(span[1])
    y0, y1 = g.y(hi), g.y(lo)
    out = [rect(name, round(x1 - x0), round(y1 - y0), None, {"stroke": k.TEXT_2, "strokeWidth": k.HAIR,
                                                             "strokeAlign": "center"}, x=round(x0), y=round(y0),
                note=f"E14 rectangle {k.drawing_label(span)}; anchors {k.hm(span[0])} {P.price(hi)} and "
                     f"{k.hm(span[1])} {P.price(lo)}")]
    if selected:
        for i, (cx, cy) in enumerate(((x0, y0), (x1, y0), (x1, y1), (x0, y1)), 1):
            out.append(handle_glyph(f"drawing handle {i}", cx, cy))
    if locked:
        out.append(icon("E14 lock glyph", "locked", k.TEXT_2, k.ICON_SM, x=round(x0 + 2), y=round(y0 + 2),
                        note="E14's lock glyph at the first anchor; drag and nudge refused \"Locked\" (D02E14 L283)"))
    return out


def data_cursor(g: ChartGeo, t: datetime) -> Node:
    return rect("keyboard data cursor", round(g.slot), round(g.plot_bot - g.plot_top), k.HOVER, x=round(g.x_at(t)),
                y=round(g.plot_top), note="the plot stop's data cursor column (E06-D03 D10)")


def plot_marker(g: ChartGeo, node: Node, *, x: float, y: float) -> Node:
    """A board marker placed inside the chart pane (pane coordinates)."""
    return node | {"x": round(x), "y": round(y), "h": math.ceil(k.est_height(node))}


def context_menu(name: str, items: list[tuple[str, bool]], *, w: int = 200, note: str) -> Node:
    return menu(name, [{"kind": "action", "label": lab, "active": act} for lab, act in items], w=w, note=note)


# --- boards 01–03, 10: presets (§2)
SCALP, WIDE = k.USER_PRESETS


def menu_at(host: Host, m: Node) -> Node:
    """The Presets menu opens under the header band (the button's row), inside the panel's column."""
    return m | {"x": host.panel_x + 8, "y": round(host.panel_y + host.header_h + 2)}


def preset_window(applied: k.Preset, *, modified: bool = False, expanded: bool = True,
                  focused: bool = False) -> tuple[list[Node], Host, Panel]:
    name = preset_name(applied)
    pr = preset_profile(applied, k.MODIFIED_ROWS if modified else None)
    k.W(8)
    lab = k.W(9, name=name) if modified else None
    p = Panel(pr, preset=applied, presets_label=lab, presets_expanded=expanded, presets_focused=focused)
    kids, host = P.window(p)
    return kids, host, p


def held_line(p: k.Preset, rows: int | None = None) -> str:
    return (f"held keys on screen: period {p.period}; row size {rows or p.row_ticks} ticks; value area {p.va_pct} %; "
            f"VWAP {'on' if p.vwap else 'off'}; HVN / LVN marking {'on' if p.nodes else 'off'} (§2.1's five keys)")


def f_preset_menu(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(SCALP)
    m = menu("Presets menu", preset_items(SCALP, active="Wide value"))
    return P.frame(fid, kids + [menu_at(host, m)]), [
        f"\"{SCALP.name}\" applied (not modified): §2.2's items in order — the built-in first, the user's presets "
        f"(the applied one menuitemradio checked), Save as new…, Rename…, Delete…; no Save changes or Reset (not "
        f"Modified), no Restore (no apply in this session)", held_line(SCALP),
        "ArrowUp / ArrowDown move (the active item drawn hovered with the inset ring), Enter / Space choose, Esc closes "
        "and returns focus to the button (§2.2)",
        "the menu sits under the header band in the panel's column (kit placement; CMP-041 opens below its trigger)"]


def f_preset_empty(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(k.BUILTIN)
    m = menu("Presets menu · empty", preset_items(k.BUILTIN, empty=True))
    return P.frame(fid, kids + [menu_at(host, m)]), [
        "The user has no preset: Session value (checked), the text row W-10 (not a menu item), then Save as new… "
        "(§2.5 Empty); nothing is offered on the built-in (no Save, Rename or Delete, §2.1)", held_line(k.BUILTIN),
        "kit reading: the built-in's held values are the panel defaults (D02 L302 names \"Session value\" only)"]


def f_preset_modified(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(SCALP, modified=True)
    m = menu("Presets menu · modified", preset_items(SCALP, modified=True, active="Save changes"))
    ann = at_bottom_left([announce(k.W(9, name=preset_name(SCALP)), label="polite announcement (once, on entering "
                                                                          "Modified)")])
    return P.frame(fid, kids + [menu_at(host, m), *ann]), [
        f"\"{SCALP.name}\" applied, then the row size changed by hand {SCALP.row_ticks} -> {k.MODIFIED_ROWS} ticks: "
        "the menu button reads W-9 — the word W-8 is text in its accessible name, never a dot, a colour or an icon "
        "alone (R-2)", held_line(SCALP, k.MODIFIED_ROWS),
        "from a Modified user preset the menu offers Save changes to {name} and Save as new…, then Reset to {name} "
        "(§2.4; D04-C2: from the Modified built-in only Save as new… and Reset)",
        "announced once on entering the state, never per change (R-3); SCR-039's header shows the same words (not "
        "drawn here)"]


def save_dialog(*, title: str, value: str, selected: bool = False, conflict: bool = False,
                helper: bool = True) -> Node:
    inner = DLG_W - 2 * k.PX[k.DIALOG_PAD]
    below: list[Node] = []
    if helper:
        below.append(text("helper · W-11", k.W(11), k.CAPTION, k.TEXT_2, w=inner))
    if conflict:
        msg = k.W(13, name=preset_name(SCALP))
        below.append(hbox("conflict · W-13", [icon("error glyph", "danger", k.DANGER_STRONG, k.ICON_SM),
                                              text("message", msg, k.CAPTION, k.TEXT_1, w=inner - 20)],
                          {"gap": k.INSET_XS, "align": "start"}, w=inner,
                          note="CMP-040's error: the glyph color.status.danger.strong, the message color.text.primary "
                               "(§11); the field's aria-describedby"))
        below.append(hbox("conflict actions", [btn("Overwrite", k.W(13, 1), h=24), btn("Rename", k.W(13, 2), h=24)],
                          {"gap": k.INSET_SM}, w=inner, h=24, note="Overwrite replaces the named preset and closes; "
                                                                   "Rename returns focus to the field, its text "
                                                                   "selected (§2.3)"))
    f = field(k.W(12), value, w=inner, selected=selected, invalid=conflict, below=below)
    return dialog("CMP-043 dialog · sm", title, [f], [btn("Cancel", say("Cancel")), btn_primary("Save", say("Save"))])


def dialog_window(d: Node, *, modified: bool = True) -> list[Node]:
    kids, _host, _p = preset_window(SCALP, modified=modified, expanded=False)
    return over_window(kids, d)


def f_preset_save(fid: str) -> tuple[Node, list[str]]:
    typed = gap_word("Scalp tight 80", "a synthetic name typed into the field (kit choice)")
    d = save_dialog(title=say("Save as new"), value=typed)
    note = marker_box("export frame note", [say("export holds these keys only — no time, symbol, drawing or account")],
                      w=300, title="Frame note (§2.1, T Security)")
    kids = dialog_window(d) + at_bottom_left([note])
    return P.frame(fid, kids), [
        "Save as new… from the Modified state: CMP-043 size sm (≤ 420 px; drawn 400), title, the field W-12 with the "
        "helper W-11, footer Cancel · Save; initial focus the field; Enter submits; Esc and Cancel return focus to the "
        "Presets menu button (§2.3)",
        "the frame note T asks for: a preset travels per user in the workspace export, which holds §2.1's keys only; "
        "the field and its import validation are D04-G1 (E19-S09, E15-S07)",
        "a name is 1–80 characters after trimming, unique per user and case-insensitive (`22`:10802–10803)"]


def f_preset_conflict(fid: str) -> tuple[Node, list[str]]:
    typed = gap_word(SCALP.name.lower(), "the typed name: the applied preset's name in another case (kit choice; "
                                         "uniqueness is case-insensitive)")
    d = save_dialog(title=say("Save as new"), value=typed, conflict=True, helper=False)
    kids = dialog_window(d) + at_bottom_left([announce(k.W(13, name=preset_name(SCALP)))])
    return P.frame(fid, kids), [
        f"Save with \"{typed}\": the name matches \"{SCALP.name}\" case-insensitively, so the dialog stays open and "
        "shows W-13 inline under the field with Overwrite · Rename — never a silent replace (§2.3)",
        "the field keeps aria-invalid=\"true\" and aria-describedby on W-13, announced once; Tab reaches Overwrite and "
        "Rename (§6)",
        "kit reading: W-13's {name} is the stored preset's name (\"" + SCALP.name + "\"), the one Overwrite would "
        "replace",
        "the helper W-11 gives way to the message (kit layout; both are the field's descriptions)"]


def f_preset_rename(fid: str) -> tuple[Node, list[str]]:
    d = save_dialog(title=say("Rename preset"), value=preset_name(SCALP), selected=True, helper=False)
    rule = marker_box("name rule", [f"W-15 \"{k.W(15)}\" shows under the field when the trimmed name is outside "
                                    "1–80 characters; the same inline conflict (W-13 or W-14) as Save as new",
                                    f"on success W-21's rename form \"{k.DECK['spec']['W-21'][0][1]}\" is announced "
                                    "once"], w=340, title="Rename rules (§2.5)")
    kids = dialog_window(d, modified=False) + at_bottom_left([rule])
    return P.frame(fid, kids), [
        "Rename…: the save dialog titled \"Rename preset\", the field pre-filled and its text selected; footer Cancel "
        "· Save (kit reading: §2.5 reuses §2.3's dialog and footer)", "the name rules and the conflict are §2.3's"]


def f_preset_delete(fid: str) -> tuple[Node, list[str]]:
    inner = DLG_W - 2 * k.PX[k.DIALOG_PAD]
    name = preset_name(SCALP)
    d = dialog("CMP-044 confirm dialog", k.W(16, 0, name=name),
               [text("message", k.W(16, 1), k.BODY, k.TEXT_2, w=inner)],
               [btn("Cancel", k.W(16, 2), focused=True), btn_primary("Delete", k.W(16, 3), danger=True)],
               role="alertdialog")
    out = marker_box("delete outcome", [f"on Delete W-21's delete form \"{k.DECK['spec']['W-21'][0][2]}\" is announced "
                                        "once and focus returns to the Presets menu button; there is no undo after "
                                        "the confirm"], w=340, title="Outcome (§2.5)")
    kids = dialog_window(d, modified=False) + at_bottom_left([out])
    return P.frame(fid, kids), [
        "Delete…: CMP-044, role=\"alertdialog\", W-16's title and message, Cancel focused (`15`:525) and Delete (a "
        "CMP-001 danger); profiles using the preset keep their current values, which become unnamed (§2.5)"]


def f_preset_applied(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(WIDE)
    m = menu("Presets menu · reopened", preset_items(WIDE, restore=True, active="Restore"))
    name = preset_name(WIDE)
    t = toast("Applied", k.W(17, 0, preset=name), k.W(17, 1),
              note="CMP-045 with an action: persistent until dismissed or the next settings change on this instance "
                   "(`15`:531); never takes focus (`15`:533)")
    ann = at_bottom_left([announce(k.W(17, 0, preset=name) + ".", label="polite announcement (once; the toast's "
                                                                         "sentence, CMP-212's region)")])
    return P.frame(fid, kids + [menu_at(host, m), toast_at(t), *ann]), [
        f"\"{name}\" applied over \"{SCALP.name}\": every held key switched at once — " + held_line(WIDE),
        "the toast W-17 with Undo and, for exactly the same lifetime, the menu's Restore previous settings (W-18; the "
        "menu drawn reopened to show it, the active item); one level, per instance, session-only; never on the "
        "drawings Ctrl+Z stack (§2.6; D04-C7)",
        "kit reading: the announcement is the toast's sentence written once into the polite region, closed with a "
        "full stop",
        "observability: profile.preset_applied {builtin: false, host: docked} is the apply's only event; no per-key "
        "settings_changed and no period_changed is re-emitted by an apply (§10; PROPOSED)"]


def f_preset_restored(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(SCALP)
    m = menu("Presets menu · after restore", preset_items(SCALP))
    ann = at_bottom_left([announce(k.W(19))])
    return P.frame(fid, kids + [menu_at(host, m), *ann]), [
        f"Undo (or Restore previous settings): the values before the apply are back — {held_line(SCALP)}; the toast "
        "and the Restore item are gone (the affordance ended); W-19 announced once (§2.6)",
        "the menu drawn reopened to show the Restore item absent",
        "observability: profile.settings_changed {key}, one per changed key, for the Undo or Restore (§10; PROPOSED); "
        "the recovery verbs stay apart: Reset (SCR-039, the defaults), Reset to {name}, Restore previous settings "
        "(§2.7)"]


# --- boards 04, 05, 09: period anchoring (§3, §6)
def tool_chip() -> Node:
    return P.chip("tool chip · W-22", k.W(22), kind="armed", glyph=None,
                  note="E14's tool-chip slot (D02E14 L153; the label an A-row, D04-A11): role=\"status\", aria-live=\"off\", read on demand, "
                       "never re-announced; the plot stop references it by aria-describedby")


def mid_y(g: ChartGeo) -> float:
    return (g.plot_top + g.plot_bot) / 2


def f_range_mode(fid: str) -> tuple[Node, list[str]]:
    a, b = k.RANGE[0], k.DRAG_TO
    p = Panel(k.SESSION, period=say("Fixed range"), legend_extra=[range_words(a, b)], hint=k.W(23))

    def marks(g: ChartGeo) -> list[Node]:
        return band(g, a, b) + [cursor("crosshair", g.x_at(b), mid_y(g) + 40)]

    kids, _host = P.window(p, chart_status=[tool_chip()], chart_extra=marks)
    ann = at_bottom_left([announce(k.W(23), label="polite announcement (once, on entering the mode)")])
    return P.frame(fid, kids + ann), [
        f"Fixed range chosen from the Period menu: the Profile range mode is entered (R-8) — the chip W-22 in the status row's "
        f"tool-chip slot, the hint W-23 in the header (replacing D02 W-30, D04-C1), focus on the plot stop (§3.1)",
        f"a plain drag in progress from {k.hm(a)} to the bar edge {k.hm(b)} (cursor crosshair): the band "
        "color.surface.selected with color.focus.ring edges; the legend reads the two times as the drag moves; no "
        "announcement until release",
        "the plot keeps the previous profile (the Session) until release: release commits, recomputes once and "
        "leaves the mode (§3.1; D02E14 L80)",
        "Esc before release leaves the mode and keeps the previous period; Space + drag pans without leaving it; "
        "without a drag a click sets the start and a second click the end (SC 2.5.7)"]


def f_range_handles(fid: str) -> tuple[Node, list[str]]:
    a, b = k.RANGE
    pr = k.range_profile(k.RANGE)
    p = Panel(pr, period=say("Fixed range"), legend_extra=[range_words(a, b)])

    def marks(g: ChartGeo) -> list[Node]:
        return band(g, a, b) + edge_handles(g, a, b, target="end") + [cursor("ew-resize", g.x_at(b) + 16,
                                                                              mid_y(g) + 22)]

    kids, _host = P.window(p, chart_extra=marks)
    ann = at_bottom_left([announce(k.W(26, start=k.ts(a), end=k.ts(b)), label="polite announcement (once per "
                                                                              "commit)")])
    return P.frame(fid, kids + ann), [
        f"the committed range {k.hm(a)} → {k.hm(b)} ({len(k.bars_between(a, b))} bars; the profile recomputed once "
        f"over exactly that window, {len(pr.rows)} rows, POC {P.price(pr.poc * pr.row_ticks)}): two edge handles, "
        "E14's handle glyph on full-height edges, a 24 × 24 target (size.target.min), ew-resize on hover (§3.2)",
        "a handle drag moves that edge by whole bars, the profile keeping its last state until release; Esc mid-drag "
        "restores; start never passes end (W-41 once)",
        "observability: profile.period_changed {from, to, host} once per commit (§10; PROPOSED)"]


def f_anchored(fid: str) -> tuple[Node, list[str]]:
    a = k.RANGE[0]
    pr = k.range_profile((a, k.NOW), "Anchored")
    p = Panel(pr, period=say("Anchored"), legend_extra=[utc(a)])
    pending = marker_box("contract pending", [say("contract pending A-1")], w=150)

    def marks(g: ChartGeo) -> list[Node]:
        return (band(g, a, None, edges=("start",)) + anchor_mark(g, a) + [open_end(g)]
                + [plot_marker(g, pending, x=g.x_at(a) + 8, y=g.plot_top + 6)])

    kids, _host = P.window(p, chart_extra=marks)
    path = marker_box("click path", [f"from SCR-038/range-handles-dark: the range's context menu → \"{k.W(27)}\" "
                                     "(the start stays, the end is released); or Anchored chosen directly, its hint "
                                     f"\"{k.W(24)}\", then a click on a bar"], w=360, title="Click path (§3.3)")
    ann = at_bottom_left([path, announce(k.W(28, time=k.ts(a)))])
    return P.frame(fid, kids + ann), [
        f"Anchored at {k.hm(a)}: the anchor marker color.text.primary (D03 L337), the band open toward the right "
        f"edge, the profile accumulating forward and extending with new bars ({len(pr.rows)} rows as of "
        f"{k.hm(k.NOW)}; `11`:1725–1727)",
        "Anchored has no contract kind (`24`:970): drawn and annotated \"contract pending A-1\", never wired to an "
        "invented field (R-4; D04-C3, D04-G3)",
        "kit reading: the legend reads the anchor time in R-7's form (one time; the open end is the Developing state "
        "word)"]


def f_anchor_removed(fid: str) -> tuple[Node, list[str]]:
    p = Panel(k.SESSION)
    kids, _host = P.window(p)
    cm = context_menu("range context menu", [(k.W(27), False), (k.W(29), True)],
                      note="the range's context menu (opened by right-click, Shift+F10 or the Menu key); "
                           "Remove anchor the active item")
    path = marker_box("click path", ["from SCR-038/anchored-dark: the range's context menu (or the Period menu) → "
                                     f"\"{k.W(29)}\"; no confirm and no restore item — the range is re-made by a "
                                     "drag, two clicks or §6's keys (§3.4)"], w=360, title="Click path (§3.4)",
                      extra=[cm])
    ann = at_bottom_left([path, announce(k.W(30, mode=say("Session")))])
    return P.frame(fid, kids + ann), [
        "Remove anchor: the period returns to the host default — docked Session (D02's PD-7 defaults); the band, "
        "the marker and the open end are gone; W-30 announced once",
        "observability: profile.period_changed {from, to, host} (§10; PROPOSED)"]


def f_range_keyboard(fid: str) -> tuple[Node, list[str]]:
    a, b = k.RANGE
    pend = a - k.NUDGE * k.BAR
    pr = k.range_profile(k.RANGE)
    p = Panel(pr, period=say("Fixed range"), legend_extra=[range_words(a, b)])
    value = k.tpl("Range start {time} UTC", {"{time}": k.ts(pend)})

    def marks(g: ChartGeo) -> list[Node]:
        cy = mid_y(g)
        x = g.x_at(pend)
        ring = rect("thumb focus ring (offset)", 16, 16, None, {"stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                                               "strokeAlign": "inner"}, x=round(x - 8),
                    y=round(cy - 8), note="color.focus.ring, border.focus, offset outside the thumb (§11)")
        tag = hbox("thumb value text", [text("words", value, k.NUM_SM, k.TEXT_1)],
                   {"padX": k.INSET_XS, "fill": k.CANVAS, "stroke": k.RING, "strokeWidth": k.HAIR,
                    "strokeAlign": "inner", "radius": k.R_CONTROL}, h=18, x=round(x + 12), y=round(cy - 30))
        k.fallback("chart-ring")
        return band(g, pend, b) + edge_handles(g, pend, b) + [ring, tag]

    kids, _host = P.window(p, chart_extra=marks)
    keys = marker_box("keys", [f"Tab to the profile range stop (after the overlay handles stop); \"{k.W(25, 0)}\" "
                               f"focused; ← pressed {k.NUDGE} times (one bar each; Shift ×10, PageUp / PageDown ×100, "
                               "Home / End the first / last loaded bar)",
                               "Enter commits (W-26 once); Esc, or focus leaving the stop, restores the value at "
                               "selection; Shift+F10 or the Menu key opens the range's context menu"], w=360,
                      title="Keyboard (§6)")
    ann = at_bottom_left([keys, announce(f"{k.W(25, 0)}, {k.ts(pend)} UTC", label="polite, coalesced while a key is "
                                                                                    "held (K-6): the pending value")])
    return P.frame(fid, kids + ann), [
        f"the profile range stop: two role=\"slider\" thumbs, W-25, aria-orientation horizontal, aria-valuemin / "
        f"aria-valuemax the first / last loaded bar ({k.hm(k.BARS[0].start)} / {k.hm(k.BARS[-1].start)}), "
        "aria-valuetext \"{time} UTC\" in R-7's form (PROPOSED; D04-C6)",
        f"Range start moved {k.NUDGE} bars from {k.hm(a)} to {k.hm(pend)} (pending): the edge follows; the profile "
        "keeps its last state until Enter; the focused thumb carries the offset ring and its value text — shape and "
        "words, not hue, set it apart (SC 2.4.7, 2.4.11)",
        "kit reading: the spoken pending value is the slider's name and aria-valuetext"]


# --- boards 06, 07, 09: drawing anchors (§4)
def cap_say(s: str, doc: str | None = None) -> str:
    """A source word written lower case in prose, drawn in sentence case."""
    say(s, doc)
    return s[0].upper() + s[1:]


def popover(span: tuple[datetime, datetime]) -> Node:
    """E14's properties popover (D02E14 §7.1): non-modal CMP-017, 280 px at compact; the title, the anchors (one time
    + price pair each), the extension slot (D02E14 §7.2) holding Attach profile, Clone · Delete. §7.1's other fields
    are elided (named in a marker row)."""
    lo, hi = k.rect_prices(span)
    w = 280
    inner = w - 2 * k.PX[k.INSET_MD]
    title = k.tpl("Trendline properties", {"Trendline": "Rectangle"}, "d02e14")

    def anchor_row(i: int, t: datetime, px: int) -> Node:
        return hbox(f"anchor {i}", [text("label", f"{i}", k.CAPTION, k.TEXT_2, w=12),
                                    P.stepper(f"time {i}", k.hm(t), w=84), P.stepper(f"price {i}", P.price(px), w=110)],
                    {"gap": k.INSET_SM}, w=inner, h=24)

    elided = text("elided fields", "colour · width · style · extend · lock · visibility · alert · Save as default",
                  k.CAPTION, k.TEXT_3, w=inner, note="board marker: §7.1's other fields, elided on this board")
    k.copy_gap("the popover's elided-fields line lists D02E14 §7.1's field names as a board marker (not product UI)")
    slot = vbox("extension slot", [control("Attach profile", k.W(32, 0), h=24, focused=True)],
                {"gap": k.STACK_XS, "padY": k.INSET_XS, "clip": False}, w=inner,  # the focused ring stands outside
                note="E14's popover extension slot (D02E14 §7.2): Attach profile, the focused item (§4.1; D04-A2)")
    foot = hbox("actions", [control("Clone", say("Clone"), h=24), control("Delete", say("Delete"), h=24)],
                {"gap": k.INSET_SM}, w=inner, h=24)
    pop = vbox("CMP-017 popover · E14 properties", [
        text("title", title, k.LABEL, k.TEXT_1, w=inner), text("anchors label", cap_say("anchors", "d02e14"),
                                                               k.CAPTION, k.TEXT_2),
        anchor_row(1, span[0], hi), anchor_row(2, span[1], lo), elided, rect("rule", inner, 1, k.BORDER), slot, foot],
        {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR,
         "strokeAlign": "inner", "radius": k.R_CARD, "shadow": k.EL_POPOVER}, w=w,
        note='role="dialog", aria-modal="false" (D02E14 L358); Esc closes and returns focus to the surrogate')
    pop["h"] = math.ceil(k.est_height(pop))
    return pop


def attached_panel(span: tuple[datetime, datetime], *, hidden_: bool = False, link: bool = True) -> Panel:
    label = k.drawing_label(span)
    pr = k.range_profile(span)
    words = (k.W(34, drawing_name=label) if hidden_ else k.W(33, drawing_name=label)) if link else None
    return Panel(pr, period=say("Fixed range"), legend_extra=[range_words(*span)],
                 link=words)


def follows(span: tuple[datetime, datetime]) -> str:
    return k.W(38, drawing_name=k.drawing_label(span), start=k.ts(span[0]), end=k.ts(span[1]))


def f_attach_menu(fid: str) -> tuple[Node, list[str]]:
    p = Panel(k.SESSION)
    pop = popover(k.RECT)
    kids, host = P.window(p, chart_extra=lambda g: rectangle(g, k.RECT, selected=True))
    g = host.chart
    x = round(g.ox + g.x_at(k.RECT[0]) - 16 - pop["w"])  # beside the selection, left: never over the price gutter
    y = round(g.oy + g.y(k.rect_prices(k.RECT)[1]) - 40)
    y = max(g.oy + P.CHART_HEAD + 4, min(y, k.WIN_H - P.STATUS_H - pop["h"] - 8))
    return P.frame(fid, kids + [pop | {"x": x, "y": y}]), [
        f"\"{k.DRAWING_NAME}\" selected (E14's four corner handles), its properties popover open beside the selection "
        "(flipped to stay inside the pane, never over the price gutter or the focused handle, D02E14 §7.1)",
        f"Attach profile (W-32) in E14's popover extension slot (D02E14 L342; D04-A2): offered only on rectangle, "
        f"date_range and vertical_line (`22`:22987–22991); a rectangle's two times -> a Fixed range",
        "the panel still shows the Session: nothing is attached yet"]


def f_attached(fid: str) -> tuple[Node, list[str]]:
    p = attached_panel(k.RECT)
    kids, _host = P.window(p, chart_extra=lambda g: rectangle(g, k.RECT, selected=True))
    ann = at_bottom_left([hidden(f"{k.DRAWING_NAME}{say(', profile attached')}", w=380,
                                 label="the drawing's accessible name and tree row (§4.2)"),
                          announce(follows(k.RECT))])
    return P.frame(fid, kids + ann), [
        f"Attach profile chosen: the instance stores the drawing's stable id (`26`:328; a field no contract carries — "
        f"D04-G2, E19-S02); the profile becomes a Fixed range over {k.hm(k.RECT[0])} → {k.hm(k.RECT[1])}, recomputed "
        "once",
        "the legend: the link glyph + W-33, words carrying the state (R-2); W-38 announced once",
        "kit reading: an attached range is marked on the chart by its drawing alone (no band or edge handles of its "
        "own); the handles are E14's"]


def f_drawing_moved(fid: str) -> tuple[Node, list[str]]:
    p = attached_panel(k.RECT_MOVED)
    kids, _host = P.window(p, chart_extra=lambda g: rectangle(g, k.RECT_MOVED, selected=True))
    ann = at_bottom_left([announce(follows(k.RECT_MOVED), label="polite announcement (once, on release)")])
    return P.frame(fid, kids + ann), [
        f"the drawing dragged {k.MOVE_BARS} bars later and released: {k.DRAWING_NAME} -> "
        f"{k.drawing_label(k.RECT_MOVED)}; the profile kept its last state during the drag and recomputed once on "
        "release over the new times (`14`:978); a price-only move would not recompute (§4.3)",
        "kit reading: E14's label is type + anchor (D02E14 L372), so the name in W-33 / W-38 follows the moved times"]


def f_drawing_locked(fid: str) -> tuple[Node, list[str]]:
    p = attached_panel(k.RECT)
    kids, _host = P.window(p, chart_extra=lambda g: rectangle(g, k.RECT, locked=True))
    return P.frame(fid, kids), [
        "locked: E14's lock glyph at the first anchor; the drawing stays selectable for inspection, never moved "
        "(D02E14 L283, L291); the profile stays still with it; no announcement here (§4.3)"]


def f_drawing_hidden(fid: str) -> tuple[Node, list[str]]:
    p = attached_panel(k.RECT, hidden_=True)
    kids, _host = P.window(p)
    return P.frame(fid, kids), [
        "hidden: the drawing is not drawn (its tree row is the way to it, D02E14 L283); the profile is kept and "
        "still drawn; the legend reads W-34; E14 announces the hide, this flow adds none (§4.3); shown again, the "
        "legend returns to W-33"]


def f_drawing_deleted(fid: str) -> tuple[Node, list[str]]:
    a, b = k.RECT
    pr = k.range_profile(k.RECT)
    p = Panel(pr, period=say("Fixed range"), legend_extra=[range_words(a, b)])
    kids, _host = P.window(p, chart_extra=lambda g: band(g, a, b) + edge_handles(g, a, b))
    label = k.drawing_label(k.RECT)
    line = k.W(35)
    words = gap_word(f"{label} removed from this pane.", "E14-D07's toast.removed.local with {label} filled "
                                                         "(D07E14 L548; the drawing is this-pane-only)") + " " + line
    t = toast("drawing deleted", words, say("Undo", "d07e14"), words_w=300,
              note="E14's one delete toast, its own copy plus the profile line W-35 (D04-A4): CMP-045, 10 s, pausing "
                   "on hover and focus (D07E14 L299); Undo re-creates the drawing under a new id")
    ann = at_bottom_left([announce(gap_word(f"{label} removed from this pane. {line} Undo available.",
                                            "E14-D07's removed announcement (announce.removed.synced form) gaining the "
                                            "line once (§4.4)"))])
    return P.frame(fid, kids + [toast_at(t), *ann]), [
        f"the drawing deleted (Del): the profile is converted — never removed, never blocked by a confirmation — to a "
        f"Fixed range at the drawing's last two times {k.hm(a)} → {k.hm(b)}; the link is gone (§4.4)",
        "one toast, never a second: E14's own copy with the profile line W-35 added (D04-A4); E14's lifetime and Undo, "
        "and E14's announcement gains the line once; E14's one Ctrl+Z does the same, so the timed toast is never the "
        "only path",
        "Undo (or Ctrl+Z) re-creates the drawing under a new id: the undone drawing comes back unlinked and the profile "
        "stays the Fixed range of the conversion until a re-link exists (D04-G5; §2.7)",
        "kit reading: the drawing is a this-pane-only one, so E14's local form \"removed from this pane.\" stands",
        "observability: profile.period_changed once for the conversion (§10; PROPOSED)"]


def f_drawing_shared(fid: str) -> tuple[Node, list[str]]:
    body_h = k.WIN_H - P.TOP_H - P.STATUS_H
    ha = round(body_h * 0.6)  # kit: pane A (the profile's pane) takes 60 % so its panel keeps a readable plot
    pa = attached_panel(k.RECT_MOVED)
    bars = k.bars_between(k.CHART_FROM, k.NOW)
    nodes_a, _ha = P.docked(pa, bars, y=P.TOP_H, h=ha, chart_extra=lambda g: rectangle(g, k.RECT_MOVED),
                            pane=" · pane A")
    lo, hi = min(b.l for b in bars), max(b.h for b in bars)
    sc = P.fit_scale(lo, hi, P.TOP_H + ha + P.CHART_HEAD + 4, k.WIN_H - P.STATUS_H - P.TIME_AXIS - 4,
                     P.TOP_H + ha + P.CHART_HEAD + 16, k.WIN_H - P.STATUS_H - P.TIME_AXIS - 16)
    slots_b = round(k.CHART_SLOTS * k.WIN_W / (k.WIN_W - k.PANEL_W))

    def marks_b(g: ChartGeo) -> list[Node]:
        lo_, hi_ = k.rect_prices(k.RECT_MOVED)
        cx = (g.x_at(k.RECT_MOVED[0]) + g.x_at(k.RECT_MOVED[1])) / 2
        return rectangle(g, k.RECT_MOVED, selected=True) + [cursor("move", cx, (g.y(lo_) + g.y(hi_)) / 2)]

    pane_b, _gb = P.chart_pane(bars, slots_b, 0, k.WIN_W, P.TOP_H + ha, k.WIN_H - P.STATUS_H, sc, extra=marks_b,
                               name="SCR-030 price pane · pane B")
    rule = rect("pane divider", k.WIN_W, 1, k.BORDER_STRONG, x=0, y=P.TOP_H + ha)
    ann = at_bottom_left([announce(follows(k.RECT_MOVED), label="polite announcement (once, in pane A's region)")],
                         bottom=k.WIN_H - P.STATUS_H - P.TIME_AXIS - 8)
    return P.frame(fid, [*P.chrome(k.WIN_W, k.WIN_H), *nodes_a, pane_b, rule, *ann]), [
        f"two BTCUSDT panes in one layout: the drawing (one stable id, `26`:328) is shared symbol-wide by every pane "
        f"showing the symbol, not by sync group (D07E14 L260); it was moved in pane B to "
        f"{k.drawing_label(k.RECT_MOVED)} (cursor move)",
        "pane A's profile instance, attached to it, follows: a Fixed range over the new times; a \"this pane only\" "
        "drawing would drive only its own pane's instance; a Clone carries no link (§4.5; D04-C4)",
        "kit layout: pane A (top) holds the docked profile panel, pane B (bottom) the chart alone; both 5m"]


def f_attach_keyboard(fid: str) -> tuple[Node, list[str]]:
    p = Panel(k.SESSION)
    kids, host = P.window(p, chart_extra=lambda g: rectangle(g, k.RECT, selected=True) + [
        rect("surrogate focus ring", 16, 16, None, {"stroke": k.RING, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner"},
             x=round(g.x_at(k.RECT[0]) - 8), y=round(g.y(k.rect_prices(k.RECT)[1]) - 8),
             note="the overlay handles stop's surrogate (the first handle with the whole-object name, D02E14 L428)")])
    k.fallback("chart-ring")
    items = [(say(x, "d02e14"), False) for x in ("Clone", "Lock", "Hide", "Properties", "Delete")]
    m = menu("drawing context menu", [{"kind": "action", "label": lab} for lab, _ in items] + [
        {"kind": "sep"}, {"kind": "action", "label": k.W(32, 0), "active": True}], w=200,
        note="the drawing's context menu (D02E14 L321) opened with Shift+F10 on its surrogate; Attach profile added")
    g = host.chart
    x = round(g.ox + g.x_at(k.RECT[0]) + 8)
    y = round(g.oy + g.y(k.rect_prices(k.RECT)[1]) + 12)
    path = marker_box("keys", ["the overlay handles stop: PageUp / PageDown rove the surrogates (D02E14 L428); "
                               "Shift+F10 or the Menu key opens the context menu; ↓ to Attach profile; Enter attaches "
                               "(W-38 once); Detach profile, the same item's other state, the same way (§6)"], w=360,
                      title="Keyboard (§6)")
    ann = at_bottom_left([path])
    return P.frame(fid, kids + [m | {"x": x, "y": y}, *ann]), [
        f"Shift+F10 on \"{k.DRAWING_NAME}\"'s surrogate: E14's context menu (Clone · Lock · Hide · Properties · "
        "Delete) with Attach profile (W-32), the active item",
        "kit reading: Attach profile sits after E14's items behind a separator (its place in the menu is not worded)"]


# --- board 10: Visible range in a pan, a stalled feed (§3.5), view-as (§1.4)
PAN_BARS = 6  # kit: the pan has moved the view six bars (30 minutes) back in time


def visible_profile(bars: list[k.Bar]) -> k.Profile:
    return k.build_profile("Visible range", "Visible range", bars, complete=False)


def f_visible_pan(fid: str) -> tuple[Node, list[str]]:
    now_bars = k.bars_between(k.CHART_FROM, k.NOW)
    panned = k.bars_between(k.CHART_FROM - PAN_BARS * k.BAR,
                            k.NOW - PAN_BARS * k.BAR)
    pr = visible_profile(now_bars)
    p = Panel(pr, period=say("Visible range"))
    lo, hi = min(b.l for b in now_bars + panned), max(b.h for b in now_bars + panned)
    kids, _host = P.window(p, bars=panned, view=(lo, hi), chart_extra=lambda g: [cursor("grab", g.plot_w / 2,
                                                                                         mid_y(g))])
    note = marker_box("catch-up", ["the last computed profile stays drawn at full ink — no dim, no skeleton, no busy "
                                   "bar; it catches up at most 10 times a second while the gesture runs and once more "
                                   "after the pan-end debounce (`11`:1730)"], w=360, title="During a pan (§3.5)")
    ann = at_bottom_left([note])
    return P.frame(fid, kids + ann), [
        f"a fast pan in Visible range: the chart already shows {k.hm(panned[0].start)}–{k.hm(panned[-1].end)}; the "
        f"profile still holds the last computed window {k.hm(now_bars[0].start)}–{k.hm(now_bars[-1].end)} "
        f"({len(pr.rows)} rows), lagging — correct, and it says nothing",
        "a lagging profile moves when the pan stops; a stale one carries E17's word (SCR-038/visible-stale-dark, "
        "beside it)"]


def f_visible_stale(fid: str) -> tuple[Node, list[str]]:
    bars = k.bars_between(k.CHART_FROM, k.NOW)
    pr = visible_profile(bars)
    last = k.NOW - timedelta(seconds=k.STALE_S)
    stale = P.chip("D02 stale state", k.W(18, doc="d02", **{"HH:MM:SS": f"{last:%H:%M:%S}"}), kind="warning",
                   glyph="warning")
    feed = P.chip("E17 feed chip", k.W(39), kind="warning", glyph="warning",
                  note="E17's feed chip in the status row (D02E17 L65); its own announcement")
    p = Panel(pr, period=say("Visible range"), status=[stale], shade=True)
    kids, _host = P.window(p, chart_status=[feed], chart_shade=True)
    return P.frame(fid, kids), [
        f"the feed stalls: only E17's vocabulary — the feed chip W-39 (oldest topic {k.STALE_S} s; the figure "
        f"illustrative) and its shade — with D02's stale state on the panel (last update {last:%H:%M:%S} UTC, the "
        "clock less those seconds) and CMP-078's shade; never the profile's own ink (§3.5)",
        "the profile keeps its shapes under the shade; the announcement is E17's"]


def f_preset_view_as(fid: str) -> tuple[Node, list[str]]:
    kids, host, _p = preset_window(SCALP, modified=True)
    m = menu("Presets menu · view-as", preset_items(SCALP, modified=True, view_as=True, active="Rename"))
    ann = at_bottom_left([announce(k.W(20, user=k.VIEW_AS_USER), label="polite announcement (Enter, Space or a hotkey "
                                                                       "on a T2 item: nothing changes, G-T2.3)")])
    return P.frame(fid, kids + [menu_at(host, m), *ann]), [
        "T2 (§1.4): under view-as the four writes — Save as new…, Save changes to {name}, Rename…, Delete… — are 2a "
        "inline inside the menu, CMP-079 RbacGate: each item leads with the CMP-019 lock (decorative=false, "
        "\"Not available\") and carries W-20 as its own second line through CMP-041 disabledReason?, mounted with the "
        "menu; the items keep CMP-041's color.surface.overlay with no fill of their own",
        "each T2 item keeps its role and full label, aria-disabled=\"true\" (never disabled), arrow-reachable (the "
        "active item is one), aria-describedby its own second line; label and glyph color.text.tertiary, the reason "
        "color.text.secondary; never color.text.disabled or opacity.disabled (G-T2.2)",
        "applying a preset, Reset to {name}, Restore, the range mode, Keep open-ended, Remove anchor and Attach / "
        "Detach stay operable and change the view only (T1); the name-conflict Overwrite is never reached",
        f"{{user}} = \"{k.VIEW_AS_USER}\", a synthetic display name (R-1)"]


# --- board 08: the gesture-conflict matrix (§5), parsed
CELL = re.compile(r"\*\*(Chart|Drawing|Profile|Trading)\*\* · `([a-z-]+)` — (.+)", re.DOTALL)


def matrix_rows() -> tuple[list[str], list[tuple[str, str, list[tuple[str, str, str]]]], int]:
    """§5's header cells and its sixteen rows: (#, input, [(owner, cursor, words) per mode column]); raises on an
    undecided cell (G-MATRIX)."""
    a = k.L("| #   | Input (source)")
    head = [k.plain(c) for c in k._cells(k.LINES["spec"][a - 1])]
    rows = []
    for ln in k.LINES["spec"][a + 1:]:
        if not ln.startswith("| "):
            break
        c = k._cells(ln)
        cells = []
        for cc in c[2:6]:
            m = CELL.fullmatch(cc)
            if not m:
                raise ValueError(f"§5 L{a}: undecided cell {cc!r}")
            cells.append((m.group(1), m.group(2), k.plain(m.group(3))))
        rows.append((c[0], k.plain(c[1]), cells))
    return head, rows, a


def owner_cell(owner: str, cur: str, words: str, w: int) -> Node:
    inner = w - 2 * k.PX[k.INSET_SM]
    top = hbox("owner · cursor", [text("owner", owner, k.LABEL, k.TEXT_1), mini_cursor(cur)], {"gap": k.INSET_SM},
               h=16)
    return vbox("cell body", [top, text("words", words, k.CAPTION, k.TEXT_2, w=inner)], {"gap": k.STACK_XS}, w=inner)


def mini_cursor(kind: str) -> Node:
    c = cursor(kind, 7, 7)
    return box(f"cursor · {kind}", [n for n in c["kids"] if n["name"] != "backing"], w=c["w"], h=16)


MAT_COLS = (36, 236, 236, 236, 236, 236)


def f_matrix(fid: str) -> tuple[Node, list[str]]:
    head, rows, line = matrix_rows()
    keys = ["n", "input", "c1", "c2", "c3", "c4"]
    cols = [k.Col(kk, lab, w) for kk, lab, w in zip(keys, head, MAT_COLS)]
    k.copy_key(f"§5 L{line}: the header and the sixteen rows' cells, parsed (backticks and bold dropped; the cursor "
               "keyword drawn beside its owner)")
    tw = sum(MAT_COLS)
    body = [k.header_row(cols)]
    for i, (n, inp, cells) in enumerate(rows):
        content: dict[str, Any] = {"n": n, "input": inp}
        for kk, (owner, cur, words) in zip(keys[2:], cells):
            content[kk] = owner_cell(owner, cur, words, MAT_COLS[keys.index(kk)])
        body.append(k.table_row(cols, content, f"row · {n}", fill=k.RAISED if i % 2 else k.CANVAS))
    table = k.rows_block(body, "matrix")
    owners = {}
    for _n, _i, cells in rows:
        for owner, cur, _w in cells:
            owners.setdefault(cur, set()).add(owner)
    key_rows = [hbox(f"key · {cur}", [box("shape", [cursor(cur, 7, 7) | {"x": 0, "y": 0}], w=120, h=16),
                                      text("owners", ", ".join(sorted(owners[cur])), k.CAPTION, k.TEXT_2)],
                     {"gap": k.INSET_SM}, w=420, h=20) for cur in sorted(owners)]
    key = vbox("cursor key", [text("title", gap_word("Cursor key", "the key's heading (kit; §5 names \"the cursor key\")"),
                                   k.LABEL, k.TEXT_1), *key_rows], {"gap": k.STACK_XS}, w=440)
    notes = vbox("matrix notes", [text(f"note {i}", s_, k.CAPTION, k.TEXT_2, w=700) for i, s_ in enumerate([
        say("one active tool at a time"), say("identical in DEMO and LIVE"),
        f"\"Said once\" in rows 8 and 9 is W-31: \"{k.W(31, command=say('chart.limit_at_price'))}\"",
        "every cursor keyword is PROPOSED (D04-OQ3); E14's rows keep E14's owners; the Profile column is proposed "
        "to E14-D02's register (D04-A1)",
        "the chips (E14's tool name, W-22) say the tool or the mode in words, so the cursor is never the only signal (R-2)"],
        1)], {"gap": k.STACK_XS}, w=700)
    title = text("title", gap_word("Gesture-conflict matrix (§5)", "the reference frame's heading (kit)"),
                 k.HEADING_SM, k.TEXT_1)
    col = vbox("matrix sheet", [title, table, hbox("key and notes", [key, notes], {"gap": k.INSET_XL,
                                                                                  "align": "start"}, w=tw)],
               {"gap": k.STACK_LG, "pad": k.INSET_LG}, w=tw + 32)
    need = math.ceil(k.est_height(col))
    w, h = k.frame_size(fid)
    if need > h - 16 or tw + 32 > w:
        raise ValueError(f"{fid}: the matrix needs {tw + 32} x {need}, the frame is {w} x {h}")
    return P.frame(fid, [col | {"x": (w - tw - 32) // 2, "y": 8, "h": need}]), [
        f"§5's sixteen rows × four modes (L{line}): each cell one owner and one cursor (a CSS keyword), none undecided; "
        f"the profile mode takes plain drag and plain click only; the trading chords stay trading's in every column",
        "with trading armed and the Profile range mode on, the Profile column governs plain inputs and the Trading "
        "column the chords; one active tool at a time",
        f"identical in DEMO and LIVE: no cell reads, mixes or switches an environment (R-1, C-2.11)",
        f"reference frame {w} × {h} (kit size; the table's estimated height {need} px)"]
