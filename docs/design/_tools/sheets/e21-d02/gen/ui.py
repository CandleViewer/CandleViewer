"""E21-D02 widgets and frames: the SCR-050 panel (header, the one notice, the heatmap pane, the six-column ladder, the
footer, the detector strip) at the three tiers and three densities, its states, menus, the reveal and the expanded
aggregate. Every string comes from the spec through k.W / k.Wf / k.S (or is a listed copy gap via k.ui); every number
from the kit's seeded world."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e21d02kit as k  # noqa: E402

Node = k.Node
text, icon, rect, ellipse, box, hbox, vbox = k.text, k.icon, k.rect, k.ellipse, k.box, k.hbox, k.vbox
D = Decimal
# the panel's vertical plan in a 1280 × 800 window (kit geometry; §2 gives the order, not the heights)
HEAD_H, NOTICE_H, COLHEAD_H, FOOT_H, STRIP_H = 48, 32, 24, 56, 40
BODY_H = k.WIN_H - HEAD_H - NOTICE_H - COLHEAD_H - FOOT_H - STRIP_H  # 600: §3.1's "about 600 px" ladder body
CTRL = 32  # header and footer controls
# the ladder's six fixed columns (§2.3 says "fixed"; the widths are the kit's), the pane the rest of the width
LCOL_W = (176, 88, 88, 72, 96, 220)
LADDER_W = sum(LCOL_W)
PANE_X = 0
LADDER_X = k.PANE_W
if k.PANE_W + LADDER_W != k.WIN_W:
    raise ValueError(f"pane {k.PANE_W} + ladder {LADDER_W} != {k.WIN_W}")
ROW_H = {"compact": k.COMPACT_ROW, "cosy": k.COMPACT_ROW, "comfortable": k.ROW_H}


# --- board markers (never product UI)
def marker_box(name: str, kids: list[Node], *, w: int | None = None, **kw: Any) -> Node:
    k.fallback("marker")
    n = vbox(f"board marker · {name}", kids, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.CANVAS,
                                              "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                              "strokeAlign": "inner", "radius": k.R_CONTROL},
             **({"w": w} if w else {}), note="board marker, not product UI", **kw)
    n["h"] = math.ceil(k.est_height(n) / 4) * 4
    return n


def announce(chars: str, *, how: str = "polite, once", w: int = 520) -> Node:
    """The words a screen reader hears (R-7), drawn as a board marker."""
    return marker_box("announcement", [text("how", k.ui(f"announced: {how}", "board-marker label"), k.CAPTION,
                                            k.TEXT_3), text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)


def acc_name(role: str, chars: str, *, w: int = 520) -> Node:
    """An accessible name or a visually hidden string, drawn as a board marker: role, then the words."""
    return marker_box("accessible name", [text("how", k.ui(f"{role} (not on screen)", "board-marker label"),
                                               k.CAPTION, k.TEXT_3), text("words", chars, k.CAPTION, k.TEXT_1,
                                                                          w=w - 16)], w=w)


def note_marker(chars: str, *, w: int = 520) -> Node:
    return marker_box("note", [text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)


def order_marker(n: int, x: float, y: float) -> Node:
    k.fallback("badge")
    return hbox(f"focus order marker {n:02d}", [text("number", str(n), k.CAPTION, k.TEXT_ON_ACTION)],
                {"fill": k.RING, "radius": k.R_BADGE, "justify": "center"}, w=20, h=20, x=round(x), y=round(y),
                note="board marker, not product UI")


# --- primitives of the controls
def ring(n: Node, radius: str = k.R_CONTROL, name: str = "focus ring") -> Node:
    """color.focus.ring, 2 px outside the control (§9.3): a wrapper padded 4 around it."""
    w = round(k.est_width(n)) + 8
    return box(name, [dict(n, x=4, y=4)], {"radius": radius, "stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                           "strokeAlign": "inner"}, w=w, h=round(k.est_height(n)) + 8,
               note="focus-visible: color.focus.ring 2 px outside the control")


def ring_rect(w: int, h: int, x: int, y: int, name: str = "focus ring") -> Node:
    """The ring drawn over a row or region, 2 px outside its box (the row keeps its full 24 px target, §9.3)."""
    return rect(name, w + 4, h + 4, None, {"stroke": k.RING, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner",
                                          "radius": k.R_CONTROL}, x=x - 2, y=y - 2,
                note="focus-visible: color.focus.ring 2 px, outside the row box")


def lock(name: str = "CMP-019 lock") -> Node:
    """CMP-019 `lock` (decorative=false, name "Not available"), leading the label, color.text.tertiary (R-3)."""
    return icon(name, "locked", k.TEXT_3, k.ICON_SM, note='CMP-019 lock, accessible name "Not available"')


def t2_box(label: str, *, name: str, typo: str = k.BODY_STRONG, h: int = CTRL, w: int | None = None,
           focused: bool = False, note: str = "") -> Node:
    """R-3 rendering 2a: the CMP-019 lock leads the full label in color.text.tertiary, on color.surface.raised with a
    color.border.default hairline; aria-disabled, never color.text.disabled, never opacity.disabled."""
    lw = round(k.text_w(label, typo))
    b = hbox(f"{name} · T2 2a", [lock(), text("label", label, typo, k.TEXT_3)],
             {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w or lw + 12 + 4 + 18, h=h,
             note=note or 'T2 2a (R-3): aria-disabled="true", in the Tab order, aria-describedby → the header notice')
    return ring(b) if focused else b


def button(label: str, *, kind: str = "secondary", focused: bool = False, name: str | None = None,
           h: int = CTRL) -> Node:
    """CMP-001 primary / secondary / ghost."""
    lw = round(k.text_w(label, k.BODY_STRONG))
    fill, col = {"primary": (k.ACTION_PRIMARY, k.TEXT_ON_ACTION), "secondary": (k.ACTION_SECONDARY, k.TEXT_1),
                 "ghost": (None, k.TEXT_1)}[kind]
    o: dict[str, Any] = {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "justify": "center"}
    if fill:
        o["fill"] = fill
    else:
        o.update({"stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
    b = hbox(name or f"CMP-001 {label}", [text("label", label, k.BODY_STRONG, col)], o, w=lw + 26, h=h, note=kind)
    return ring(b) if focused else b


def listbox(label: str | None, value: str, *, name: str, w: int = 64, open_: bool = False) -> Node:
    """A header listbox: its label, then the value and the chevron in a 24 px field."""
    k.fallback("icon-sm")
    field_ = hbox("field", [text("value", value, k.NUM_SM, k.TEXT_1), icon("chevron", "chevron-down", k.TEXT_2,
                                                                           k.ICON_SM)],
                  {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.SUNKEN, "stroke": k.RING if open_ else k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL, "justify": "space-between"},
                  w=w, h=24)
    kids = ([text("label", label, k.CAPTION, k.TEXT_2)] if label else []) + [field_]
    return hbox(name, kids, {"gap": k.INSET_XS}, h=24)


def env_badge(env: str) -> Node:
    """The env badge (§2.4): the word with its icon, color.env.demo / color.env.live outline and glyph; from the
    session environment (R-5), never the feed; never shed."""
    k.fallback("env-glyph")
    tok = {"DEMO": k.ENV_DEMO, "LIVE": k.ENV_LIVE}[env]
    dot = ellipse("glyph", 8, 8, {"stroke": tok, "strokeWidth": k.THICK, "strokeAlign": "inner"} if env == "DEMO"
                  else {"fill": tok})
    return hbox(f"env badge · {env}", [dot, text("word", k.S(env), k.LABEL, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": tok, "strokeWidth": k.THICK,
                 "strokeAlign": "inner", "radius": k.R_BADGE}, w=round(k.text_w(env, k.LABEL)) + 36, h=22,
                note="the session environment (R-5, C-2.11), never the feed")


def view_switch(table: bool = False) -> Node:
    """`Ladder │ Table` (§10): a radiogroup of two, never overflowing."""
    k.fallback("segmented")
    words = k.S("Ladder │ Table").split(" │ ")
    segs = []
    for i, wd in enumerate(words):
        on = (i == 1) == table
        o: dict[str, Any] = {"padX": k.INSET_SM, "justify": "center", "radius": k.R_CONTROL}
        if on:
            o.update({"fill": k.SELECTED, "stroke": k.BORDER_SELECTED, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
        segs.append(hbox(f"radio · {wd}", [text("label", wd, k.LABEL, k.TEXT_1 if on else k.TEXT_2)], o,
                         w=round(k.text_w(wd, k.LABEL)) + 18, h=24, note="checked" if on else "radio"))
    return hbox("view switch (radiogroup)", segs, {"gap": k.INSET_XS, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                   "strokeAlign": "inner", "radius": k.R_CONTROL}, h=28,
                note="Alt+T; in the never-overflow set (§10)")


# --- the panel configuration (one frame)
@dataclass
class P:
    tier: int = k.DEFAULT_TIER
    density: str = "compact"  # compact | cosy (compact rows, the `dense` pane) | comfortable
    env: str = "DEMO"
    state: str = "streaming"  # streaming free-scroll loading empty-owner empty-other stale stale-t2 disconnected
    #                           resyncing rebuilt shed
    cvd: bool = False
    chips: bool = False
    own: bool = True  # the session's own orders and position (False: the LIVE session holds none)
    menu: str | None = None  # overflow | overflow-arm | depth | row
    expanded: bool = False  # the aggregate's Your-orders cell expanded (§8.1)
    reveal: bool = False  # the heatmap reveal open for the pulled level (§8.3, §9.2)
    focus: str | None = None  # row:<price> | cta | heading | pin
    tier_notice: str | None = None  # the tier notice row (§11.1)
    w2: bool = False  # the header reads W-2 (§3.2)
    table: bool = False  # the Table view (§10)
    extra: list[Node] = field(default_factory=list)  # board markers stacked at the pane's foot

    @property
    def row_h(self) -> int:
        return ROW_H[self.density]

    @property
    def stale(self) -> bool:
        return self.state in ("stale", "stale-t2", "disconnected")


def notice_words(p: P) -> tuple[str, str]:
    """The one notice's (key, sentence): §5.1's first missing leg — the feed key leads in stale, disconnected and
    resyncing; otherwise the E21 state key W-20 (the session is the Owner's: legs 1-4 hold)."""
    if p.state == "stale":
        return "feed.stale", k.W("W-8", age=f"{k.STALE_T1_AGE} s")
    if p.state == "stale-t2":
        return "feed.stale_t2", k.W("W-27", age=f"{k.STALE_T2_AGE} s")
    if p.state == "disconnected":
        return "feed.disconnected", k.W("W-9")
    if p.state == "resyncing":
        return "feed.resyncing", k.W("W-11")
    return "ladder.not_built", k.W("W-20")


def state_text(p: P) -> list[Node]:
    """The header's text state (SR-038): the stale chip and line, the disconnected line, the resync line, the tag."""
    if p.state in ("stale", "stale-t2"):
        chip_words = k.W("W-5") if p.state == "stale" else k.W("W-26")  # verbatim: the world's age is theirs
        strong = p.state == "stale-t2"
        chip = hbox("stale chip" + (" (strong, ≥ T2)" if strong else " (T1)"),
                    [text("words", chip_words, k.LABEL, k.TEXT_ON_ACTION if strong else k.STALE_TEXT)],
                    {"padX": k.INSET_SM, "fill": k.STALE_IND if strong else k.STALE_SURFACE, "radius": k.R_BADGE,
                     "stroke": k.STALE_IND, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                    w=round(k.text_w(chip_words, k.LABEL)) + 18, h=20, note='aria-live="off"; the age ticks visually')
        if strong:  # §4 names W-6 for T1 only; the ≥ T2 step draws W-26 and W-27 (no W-n with a figure it lacks)
            return [chip]
        return [chip, text("stale line (W-6)", k.W("W-6"), k.CAPTION, k.TEXT_2)]
    if p.state == "disconnected":
        hm_ = k.hms(k.DISC_LAST)[:5]
        return [text("disconnected (W-7)", k.Wf("W-7", {"00:12": hm_}), k.CAPTION, k.DISC_TEXT)]
    if p.state == "resyncing":
        return [text("resync line (W-10)", k.W("W-10"), k.CAPTION, k.RESYNC_TEXT)]
    if p.state == "rebuilt":
        t = k.W("W-12")
        return [hbox("rebuilt tag (W-12, visual only)", [text("words", t, k.LABEL, k.TEXT_1)],
                     {"padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                      "radius": k.R_BADGE}, w=round(k.text_w(t, k.LABEL)) + 18, h=20)]
    return []


def header(p: P) -> Node:
    """§2.1 at 1280 px: title · the LOCKED echo · depth · (W-2) · env badge · view switch · follow state · ⋯; scale,
    trail, cell and ARM sit in ⋯ (drawn open by menu="overflow")."""
    left: list[Node] = [text("title", k.S("BTCUSDT · Heatmap + Ladder"), k.BODY_STRONG, k.TEXT_1),
                        text("arm echo (plain text)", k.S("LOCKED"), k.CAPTION, k.TEXT_2,
                             note="the ARM pill's state echoed while the pill sits in ⋯ (§2.1)"),
                        *state_text(p)]
    dep = listbox(k.ui("depth", "§2.1's `depth [200 ▾]` slot, its label word"), str(p.tier), name="depth listbox",
                  open_=p.menu == "depth")
    left.append(ring(dep, name="depth listbox · focus ring") if p.menu == "depth" else dep)
    if p.w2:
        rows = k.rows_window(math.ceil(body_h(p) / p.row_h))[:body_h(p) // p.row_h]  # the fully visible rows
        left.append(text("tier extent (W-2)", k.Wf("W-2", {"63,950": k.price0(rows[-1]), "64,120": k.price0(rows[0])}),
                         k.CAPTION, k.TEXT_2))
    paused = p.state == "free-scroll"
    follow = hbox("follow state", [text("state", k.Wf("W-4", {}) if paused else k.S("Following"), k.CAPTION, k.TEXT_2),
                                   button(k.S("Follow") if paused else k.S("Pause"), kind="ghost", h=24,
                                          name="follow toggle (aria-pressed)")], {"gap": k.INSET_SM}, h=24)
    more = box("⋯ menu button", [icon("glyph", "more-horizontal", k.TEXT_2, k.ICON, x=4, y=4)],
               {"radius": k.R_CONTROL, **({"stroke": k.RING, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner"}
                                          if p.menu in ("overflow", "overflow-arm") else {})}, w=24, h=24,
               note='aria-haspopup="menu"; scale, trail, cell and ARM inside at 1280 px')
    right = [env_badge(p.env), view_switch(p.table), follow, more]
    lb = hbox("header · left", left, {"gap": k.INSET_MD}, h=CTRL)
    rb = hbox("header · right", right, {"gap": k.INSET_MD}, h=CTRL)
    rw = round(k.est_width(rb))
    return box("panel header", [dict(lb, x=12, y=(HEAD_H - CTRL) // 2),
                                dict(rb, x=k.WIN_W - rw - 12, y=(HEAD_H - CTRL) // 2),
                                rect("rule", k.WIN_W, 1, k.BORDER, x=0, y=HEAD_H - 1)],
               {"fill": k.CANVAS}, w=k.WIN_W, h=HEAD_H, x=0, y=0, note=f"region name: {region_name(p.env)}")


def region_name(env: str) -> str:
    return k.W("W-1") if env == "DEMO" else k.S("DOM ladder, BTCUSDT, LIVE")


def notice(p: P, *, w: int = k.WIN_W) -> Node:
    """The one notice under the header row (§5.1, rendering 2a): the lock and the first missing leg's reason; every
    gated control's aria-describedby points here (G-T2.5)."""
    key, words = notice_words(p)
    return hbox("header notice (G-T2.5)", [lock(), text("reason", words, k.CAPTION, k.TEXT_2)],
                {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": k.RAISED}, w=w, h=NOTICE_H, x=0, y=HEAD_H,
                note=f"the notice node; key {key}; every gated control's aria-describedby points here")


def colhead(y: int) -> Node:
    kids: list[Node] = [text("pane label", k.ui("Heatmap · time →", "§2.2's heading words as the pane's label"),
                             k.CAPTION, k.TEXT_2, x=8, y=5)]
    x = LADDER_X
    for nm, w in zip(k.COL_HEADS, LCOL_W):
        kids.append(text(f"th · {nm}", nm, k.CAPTION, k.TEXT_2, x=x + 8, y=5))
        x += w
    kids.append(rect("rule", k.WIN_W, 1, k.BORDER, x=0, y=COLHEAD_H - 1))
    return box("column header row", kids, {"fill": k.CANVAS}, w=k.WIN_W, h=COLHEAD_H, x=0, y=y,
               note='role="row" of columnheaders; aria-colcount="6" (§9.1)')


def side_cell(r: Decimal, side: str, tier: int) -> str:
    v = k.row_size(r, side, tier)
    return "" if v is None or k.row_side(r) != side else k.qty1(v)


def own_words(r: Decimal) -> str:
    os_ = k.own_at(r)
    if not os_:
        return ""
    if len(os_) == 1:
        o = os_[0]
        return k.Wf("W-22", {"Buy": o.side.capitalize(), "0.5": k.qty1(o.qty)})
    buys = sum((o.qty for o in os_ if o.side == "buy"), Decimal(0))
    return k.Wf("W-23", {"3": str(len(os_)), "1.2": k.qty1(buys)})


def account_words(o: k.Own) -> str:
    """The expanded row's words, `15`:2976's form ("Buy 0.5 limit, account Acct B")."""
    form = k.S("Buy 0.5 limit, account Acct B")
    out = f"{o.side.capitalize()} {k.qty1(o.qty)} {o.kind}, account {o.acct}"
    if form != f"Buy 0.5 limit, account {k.ACCOUNTS[1]}":
        raise ValueError(form)
    return out


def row_reading(r: Decimal, tier: int) -> str:
    """A focused row's reading, §9.2's form: six cells in order, empty cells "none"."""
    none = k.S("none")
    side = k.row_side(r)
    pos = f", {k.Wf('W-25', {}).replace(' ·', '')}" if r == k.POSITION_AT else ""
    cells = [f"Bid {side_cell(r, 'bid', tier) or none}", f"Ask {side_cell(r, 'ask', tier) or none}",
             f"Prints {k.qty1(v) if (v := k.row_prints(r, tier)) else none}",
             f"Cum. depth {k.qty1(v) if (v := k.cum_depth(r, tier)) else none}",
             f"Your orders {own_words(r).replace(' · ', ', ') or none}"]
    del side
    return f"{k.price0(r)}{pos}, " + ", ".join(cells)


@dataclass
class Row:
    kind: str  # level | account
    price: Decimal
    own: k.Own | None = None
    first: bool = False


def body_rows(p: P, n: int, offset: int = 0) -> list[Row]:
    rows = [Row("level", r) for r in k.rows_window(n + (0 if not p.expanded else 0))]
    if offset:
        rows = [Row("level", r.price + k.STEP * offset) for r in rows]
    if p.expanded:
        i = next(j for j, r in enumerate(rows) if r.price == k.AGG_AT)
        acc = [Row("account", k.AGG_AT, o, j == 0) for j, o in enumerate(k.own_at(k.AGG_AT))]
        rows = rows[:i + 1] + acc + rows[i + 1:]
        rows = rows[:n]
    return rows


def hatch(name: str, w: int, h: int, *, x: int = 0, y: int = 0) -> Node:
    """The pulled mark's hatch (FALLBACKS["hatch"]): 2 × 2 steps on a 6 px 45° track."""
    k.fallback("hatch")
    kids: list[Node] = []
    for row in range(0, h - 1, 2):
        for s0 in range(-h, w + h, 6):
            x0 = s0 + (h - 2 - row)
            if 0 <= x0 <= w - 2:
                kids.append(rect(f"step {len(kids):03d}", 2, 2, k.TEXT_1, x=x0, y=row))
    return box(name, kids, {"clip": True}, w=w, h=h, x=x, y=y, note="the pulled mark: heatmap only (R-1, M AD-6)")


def heat_cells(p: P, r: Decimal, ry: int, an: tuple[Decimal, ...]) -> list[Node]:
    """One price row of the pane: equal-stop runs over the trail columns (stop 0 = the pane's color.heatmap.zero)."""
    k.fallback("cells")
    side = k.row_side(r)
    lv = [k.stop_of(k.row_size(r, side, p.tier, c), an) for c in range(k.COLS)]
    gut = 0 if p.density == "cosy" else 1
    out, c0 = [], 0
    for c in range(1, k.COLS + 1):
        if c == k.COLS or lv[c] != lv[c0]:
            if lv[c0]:
                out.append(rect(f"hm · {k.price0(r)} · {c0 + 1}-{c}", (c - c0) * k.COL_W, p.row_h - 2 * gut,
                                k.hm(side, lv[c0], p.cvd), x=PANE_X + c0 * k.COL_W, y=ry + gut))
            c0 = c
    if r == k.row_of(k.PULL_PRICE, "bid") and p.tier >= k.LEVEL_PX["bid"].index(k.PULL_PRICE) + 1:
        out.append(hatch(f"pulled mark · {k.price0(r)}", k.COL_W, p.row_h - 2 * gut, x=PANE_X + k.PULL_COL * k.COL_W,
                         y=ry + gut))
    return out


def own_glyph(o: k.Own) -> Node:
    k.fallback("own-glyph")
    return rect("CMP-230 glyph", 8, 8, k.BUY if o.side == "buy" else k.SELL)


def level_texts(p: P, r: Decimal, ry: int) -> list[Node]:
    """The six cells of one price row (texts placed in their fixed columns, 8 px padding a side)."""
    fg = k.STALE_TEXT if p.stale else k.TEXT_1
    ty = ry + (p.row_h - 13) // 2
    side = k.row_side(r)
    xs = [LADDER_X + sum(LCOL_W[:i]) for i in range(6)]
    out: list[Node] = [text(f"td · {k.price0(r)} · Price", k.price0(r), k.NUM_SM, fg, x=xs[0] + 8, y=ty)]
    if p.own and r == k.POSITION_AT:
        out.append(text(f"td · {k.price0(r)} · position marker (W-25)", k.Wf("W-25", {}), k.NUM_SM,
                        k.TEXT_2 if not p.stale else fg, x=xs[0] + 8 + round(k.text_w(k.price0(r), k.NUM_SM)) + 8,
                        y=ty, note="part of the Price cell (the row header), never a glyph alone (§8.2)"))
    for i, sd in ((1, "bid"), (2, "ask")):
        v = side_cell(r, sd, p.tier)
        if v:
            out.append(text(f"td · {k.price0(r)} · {sd} letter", "B" if sd == "bid" else "A", k.NUM_SM, k.TEXT_2
                            if not p.stale else fg, x=xs[i] + 8, y=ty, note="aria-hidden: the header names the side"))
            out.append(text(f"td · {k.price0(r)} · {sd}", v, k.NUM_SM, fg, x=xs[i] + 8 + 14, y=ty))
    if p.tier and (v := k.row_prints(r, p.tier)):
        out.append(text(f"td · {k.price0(r)} · Prints", k.qty1(v), k.NUM_SM, fg, x=xs[3] + 8, y=ty))
    if (v := k.cum_depth(r, p.tier)) is not None:
        out.append(text(f"td · {k.price0(r)} · Cum. depth", k.qty1(v), k.NUM_SM, fg, x=xs[4] + 8, y=ty))
    if p.own and (wd := own_words(r)):
        os_ = k.own_at(r)
        out.append(text(f"td · {k.price0(r)} · Your orders", wd, k.NUM_SM, fg, x=xs[5] + 8, y=ty))
        gx = xs[5] + 8 + round(k.text_w(wd, k.NUM_SM)) + 6
        if len(os_) == 1:
            out.append(dict(own_glyph(os_[0]), x=gx, y=ry + (p.row_h - 8) // 2))
        else:
            out.append(icon(f"td · {k.price0(r)} · expand cue", "chevron-down" if p.expanded else "chevron-right",
                            k.TEXT_2, k.ICON_SM, x=gx, y=ry + (p.row_h - 12) // 2,
                            note=f"aria-expanded={'true' if p.expanded else 'false'}; Enter expands (§8.1)"))
    del side
    return out


def account_texts(p: P, row: Row, ry: int) -> list[Node]:
    """An expanded account row (§8.1): indented under the aggregate, text first; the first carries W-24 with CMP-227."""
    assert row.own is not None
    x0 = LADDER_X + LCOL_W[0]
    ty = ry + (p.row_h - 13) // 2
    out: list[Node] = [rect(f"account row · {row.own.acct} · {k.qty1(row.own.qty)} · fill", LADDER_W - LCOL_W[0],
                            p.row_h, k.RAISED, x=x0, y=ry),
                       text(f"account row · {row.own.acct} · {k.qty1(row.own.qty)}", account_words(row.own), k.NUM_SM,
                            k.TEXT_1, x=x0 + 8, y=ty, note='role="row"; Esc collapses, focus back on the cell')]
    if row.first:
        words = k.W("W-24")  # verbatim, one string; the world's queue ahead (k.AHEAD) is its figure
        x1 = x0 + 8 + round(k.text_w(account_words(row.own), k.NUM_SM)) + 16
        out.append(dict(estimated_badge(words, "queue estimate (W-24) · CMP-227 inline"), x=x1,
                        y=ry + (p.row_h - 16) // 2))
    return out


def estimated_badge(word: str, name: str = "CMP-227 EstimatedBadge · inline") -> Node:
    """CMP-227 `inline`: the local 'info' glyph as its stand-in and the copy carrying "(estimated)" in full (W-24 is
    one string, so the word stays inside it)."""
    k.fallback("chip")
    assert word.endswith("(estimated)"), word
    return hbox(name, [icon("glyph (stand-in: info)", "info", k.INFO, k.ICON_SM),
                                                     text("word", word, k.CAPTION, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.INFO_SUBTLE, "radius": k.R_BADGE},
                w=round(12 + 4 + k.text_w(word, k.CAPTION) + 10), h=16, note="the word in full (C-5)")


def body(p: P, y0: int, h: int, offset: int = 0) -> tuple[list[Node], dict[Decimal, int]]:
    """The pane and the ladder body from y0, h tall: rows in 8-row bands (fewer render sections); returns the nodes and
    each level row's y (for rings and menus)."""
    n = math.ceil(h / p.row_h)
    rows = body_rows(p, n, offset)
    an = k.stops(p.tier)
    out: list[Node] = [rect("pane · color.heatmap.zero", k.PANE_W, h, k.HM_ZERO, x=0, y=y0,
                            note='the pane: role="img", one focus stop (§9.1); no per-cell DOM (R-6)'),
                       rect("ladder body", LADDER_W, h, k.STALE_SURFACE if p.stale else k.CANVAS, x=LADDER_X, y=y0,
                            note='role="grid"; only the windowed rows exist, each with aria-rowindex (§9.1)')]
    ys: dict[Decimal, int] = {}
    cells: list[tuple[int, Node]] = []
    for i, row in enumerate(rows):
        ry = y0 + i * p.row_h
        if row.kind == "account":
            cells += [(i, x) for x in account_texts(p, row, ry)]
            continue
        r = row.price
        ys[r] = ry
        if p.state != "loading":
            if k.row_size(r, k.row_side(r), p.tier) is not None or p.state == "resyncing":
                cells += [(i, x) for x in heat_cells(p, r, ry, an)]
                cells += [(i, x) for x in level_texts(p, r, ry)]
        else:
            k.fallback("skeleton")
            for j, (wd, cw) in enumerate(zip((56, 40, 40, 28, 44, 0), LCOL_W)):
                if wd:
                    cells.append((i, rect(f"skeleton · {i:02d} · {j}", wd, p.row_h - 8, k.RAISED,
                                          x=LADDER_X + sum(LCOL_W[:j]) + 8, y=ry + 4)))
        cells.append((i, rect(f"row rule · {i:02d}", LADDER_W, 1, k.GRID, x=LADDER_X, y=ry + p.row_h - 1)))
    for b0 in range(0, len(rows), 3):
        ks = [x for i, x in cells if b0 <= i < b0 + 3]
        by = y0 + b0 * p.row_h
        if ks:
            # the band clips at the body's foot unless that cuts a row's text; then it keeps whole rows (the live
            # check's fix on 02's tier-500 frame: the footer, opaque and above, covers the rest)
            bh = min(3 * p.row_h, y0 + h - by)
            if any(x["t"] == "text" and x["y"] - by + k.est_height(x) > bh for x in ks):
                bh = (min(len(rows), b0 + 3) - b0) * p.row_h
            out.append(box(f"rows {b0 + 1}-{min(len(rows), b0 + 3)}", [dict(x, y=x["y"] - by) for x in ks], {},
                           w=k.WIN_W, h=bh, x=0, y=by))
    if p.state != "loading":
        my = ys.get(k.row_of(k.BEST_BID, "bid"))
        if my is not None:
            words = k.MARK_WORDS
            out.append(rect("mark rule", k.WIN_W, 1, k.TEXT_2, x=0, y=my, note="the mark, a full-width rule (§2.2)"))
            out.append(hbox("mark label", [text("words", words, k.CAPTION, k.TEXT_1)],
                            {"padX": k.INSET_XS, "fill": k.APP, "radius": k.R_BADGE},
                            w=round(k.text_w(words, k.CAPTION)) + 10, h=16, x=k.PANE_W - round(k.text_w(words, k.CAPTION))
                            - 18, y=my - 8))
    return out, ys


def empty_state(p: P, y0: int, h: int) -> list[Node]:
    """CMP-026 `recording-not-started` over the pane and the ladder (§4): Owner — W-16, W-17, the W-19 CTA (focused);
    others — W-16, W-17 and the sentence form W-18 (the heading focused, tabindex -1)."""
    w = 560
    # the sentence form's heading sits in its focus ring: live, the ring (w - 8) and the heading (w - 24) end inside
    # the card (the live check's fix; at w - 16 the ring ran 8 px and the heading 4 px past the card's right edge)
    hw = w - 16 if p.state == "empty-owner" else w - 24
    head = text("heading (W-16)", k.W("W-16"), k.HEADING_SM, k.TEXT_1, w=hw)
    cause = text("cause (W-17)", k.W("W-17"), k.BODY, k.TEXT_2, w=w - 16)
    if p.state == "empty-owner":
        tail = button(k.W("W-19"), kind="primary", focused=True, name="CMP-001 primary · Record this symbol")
        kids = [head, cause, tail]
    else:
        # live, the heading sets on one line at w - 24 (h 17); the kit's width estimate would wrap it to two
        hd = ring(vbox("heading (tabindex -1)", [head], {}, w=hw, h=round(k.text_h(k.HEADING_SM, 1))))
        # G-T2.1d: the sentence form is CMP-026 with `cta` omitted and `description` carrying the sentence, so W-18
        # is drawn alone, with no glyph and no button (the design read of #5638)
        sent = hbox("sentence form (W-18)", [text("words", k.W("W-18"), k.BODY, k.TEXT_2)],
                    {}, h=20, note="no control, no glyph: the sentence form (D09E09); rbac.owner_only")
        kids = [hd, cause, sent]
    card = vbox("CMP-026 EmptyState · recording-not-started", kids,
                {"gap": k.STACK_MD, "pad": k.INSET_LG, "fill": k.RAISED, "radius": k.R_CARD, "align": "start"}, w=w)
    ch = math.ceil(k.est_height(card))
    return [rect("panel body (no book)", k.WIN_W, h, k.CANVAS, x=0, y=y0),
            dict(card, h=ch, x=(k.WIN_W - w) // 2, y=y0 + (h - ch) // 2)]


def scrim(y0: int, h: int) -> list[Node]:
    """The resync scrim over the ladder and the pane (visual only; the grid takes aria-busy) with W-10 on it."""
    k.fallback("scrim")
    t = k.W("W-10")
    lab = hbox("scrim label (W-10)", [icon("glyph", "refresh", k.TEXT_1, k.ICON), text("words", t, k.BODY_STRONG,
                                                                                     k.TEXT_1)],
               {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD},
               w=round(k.text_w(t, k.BODY_STRONG)) + 16 + 8 + 26, h=36)
    return [rect("resync scrim · color.surface.overlay", k.WIN_W, h, k.OVERLAY, {"opacity": k.SCRIM}, x=0, y=y0),
            dict(lab, x=(k.WIN_W - lab["w"]) // 2, y=y0 + h // 4)]


def footer(y: int, w: int = k.WIN_W, two_rows: bool = False) -> Node:
    """§5.2's footer in `14`:1211's order: qty listbox, the presets (enabled), BUY MKT, SELL MKT, FLAT, CXL (each T2
    2a on the notice's leg; FLAT and CXL never on the arm, R-4)."""
    qty = listbox(k.ui("qty", "`14`:1211's footer label"), k.PRESETS[0], name="qty listbox", w=72)
    pres = [button(v, kind="ghost", h=24, name=f"CMP-122 preset {v}") for v in k.PRESETS[1:]]
    k.ui("0.10 · 0.25 · 0.50 · 1.0", "`14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing")
    t2 = [t2_box(k.S(lbl), name=f"footer {lbl}") for lbl in ("BUY MKT", "SELL MKT", "FLAT", "CXL")]
    g1 = hbox("qty and presets", [qty, *pres], {"gap": k.INSET_SM}, h=CTRL)
    g2 = hbox("trade buttons", t2, {"gap": k.INSET_SM}, h=CTRL)
    if two_rows:
        kids = [dict(g1, x=12, y=8), dict(g2, x=12, y=8 + CTRL + 8)]
        hh = 2 * CTRL + 24
    else:
        kids = [dict(g1, x=12, y=(FOOT_H - CTRL) // 2), dict(g2, x=w - round(k.est_width(g2)) - 12,
                                                              y=(FOOT_H - CTRL) // 2)]
        hh = FOOT_H
    return box("panel footer", [rect("rule", w, 1, k.BORDER, x=0, y=0), *kids], {"fill": k.CANVAS}, w=w, h=hh, x=0,
               y=y, note="every trade button: aria-describedby → the header notice (G-T2.5)")


def strip(p: P, y: int, w: int = k.WIN_W) -> Node:
    """The detector strip (§8.3): CMP-134 chips with "(estimated)" in full; the last Tab stop (§9.1)."""
    kids: list[Node] = [rect("rule", w, 1, k.BORDER, x=0, y=0),
                        text("label", k.ui("Detectors", "the strip's label; CMP-134's words are E25's"), k.CAPTION,
                             k.TEXT_2, x=12, y=(STRIP_H - 13) // 2)]
    if p.chips:
        k.fallback("chip")
        x = 96
        for wid in ("W-14", "W-15"):
            words = k.W(wid)
            c = hbox(f"CMP-134 chip · {wid}", [icon("glyph (stand-in)", "info", k.INFO, k.ICON_SM),
                                               text("words", words, k.CAPTION, k.TEXT_1)],
                     {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                      "strokeAlign": "inner", "radius": k.R_PILL}, w=round(k.text_w(words, k.CAPTION)) + 36, h=24,
                     x=x, y=(STRIP_H - 24) // 2, note="CMP-227 carries the word in full (C-5)")
            kids.append(c)
            x += c["w"] + 8
    return box("detector strip", kids, {"fill": k.CANVAS}, w=w, h=STRIP_H, x=0, y=y)


# --- popovers: the ⋯ menu, the depth listbox, the row menu; the reveal region
def card(name: str, kids: list[Node], w: int, note: str) -> Node:
    k.fallback("menu")
    n = vbox(name, kids, {"gap": k.STACK_XS, "pad": k.INSET_XS, "fill": k.OVERLAY, "stroke": k.BORDER,
                          "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w, note=note)
    n["h"] = math.ceil(k.est_height(n))
    return n


def item(label: str, w: int, *, value: str | None = None, sel: bool = False) -> Node:
    kids = [text("label", label, k.BODY, k.TEXT_1)] + ([text("value", value, k.NUM_SM, k.TEXT_2)] if value else []) \
        + ([icon("checked", "check", k.TEXT_1, k.ICON)] if sel else [])
    return hbox(f"item · {label}", kids, {"gap": k.INSET_SM, "padX": k.INSET_SM, "justify": "space-between",
                                          **({"fill": k.SELECTED} if sel else {})}, w=w, h=28)


def arm_pill(*, focused: bool = False) -> Node:
    """CMP-229 drawn LOCKED (W-13, `arm.locked`, E30-D02's) and T2 on W-20 while E21 holds (§5.3, R-3)."""
    k.fallback("icon-sm")
    words = k.W("W-13", account=k.ACCOUNTS[0], size=k.PRESETS[0], coin=k.COIN)
    return t2_box(words, name="CMP-229 ArmToggle · LOCKED", typo=k.LABEL, h=28, focused=focused,
                  note='switch, aria-pressed="false", aria-disabled="true"; Ctrl+Shift+T re-shows W-20 (R-3)')


def overflow_menu(p: P) -> Node:
    """⋯ open (§2.1): scale, trail, cell, ARM in that order; Esc or a choice returns focus to ⋯."""
    w = 300
    kids = [item(k.ui("scale", "§2.1's `scale [log ▾]` slot word"), w - 8, value="log ▾"),
            item(k.ui("trail", "§2.1's `trail [60 s ▾]` slot word"), w - 8, value=f"{k.TRAIL_S} s ▾"),
            item(k.ui("cell", "§2.1's cell chip (D03E17 §3's words)"), w - 8, value=k.ui("auto · 1 s", "the cell chip")),
            arm_pill(focused=p.menu == "overflow-arm")]
    return card("⋯ menu (role=menu)", kids, w, "scale · trail · cell · ARM, the §2.1 overflow order")


def depth_listbox(p: P) -> Node:
    """The depth listbox open (§3.2): 50, 200 (selected), the 500 option T2 2a with W-3 under it (reason at mount),
    arrow-reachable, focused."""
    w = 340
    opts: list[Node] = [item(str(t), w - 8, sel=t == p.tier) for t in k.TIERS[:2]]
    o5 = vbox("option 500 · T2 2a", [hbox("option row", [lock(), text("label", "500", k.BODY, k.TEXT_3)],
                                          {"gap": k.INSET_XS}, h=20),
                                     text("reason (W-3)", k.W("W-3"), k.CAPTION, k.TEXT_2, w=w - 40)],
              {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS, "fill": k.RAISED, "stroke": k.BORDER,
               "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w - 16,
              note='role="option", aria-disabled="true", aria-describedby → its reason (book.tier_unavailable)')
    o5["h"] = math.ceil(k.est_height(o5))
    opts.append(ring(o5))
    return card("depth listbox (open)", opts, w, "Enter on 500 re-shows W-3 and changes nothing (R-3)")


def row_menu(r: Decimal) -> Node:
    """Enter on a row (§5.2): role=menu, the notice's sentence as its label, limit · stop · TP T2 2a, then "alert
    here" and "copy price" enabled; focus on the first item."""
    w = 340
    label = hbox("menu label (aria-labelledby)", [lock(), text("reason", k.W("W-20"), k.CAPTION, k.TEXT_2,
                                                                w=w - 44)], {"gap": k.INSET_XS, "padX": k.INSET_SM,
                                                                             "align": "start"}, w=w - 8, h=32)
    items = [t2_box(k.S(x), name=f"menu item {x}", typo=k.BODY, h=28, w=w - 16, focused=i == 0)
             for i, x in enumerate(("limit", "stop", "TP"))]
    en = [item(k.S(x), w - 8) for x in ("alert here", "copy price")]
    return card(f"row menu · {k.price0(r)} (role=menu)", [label, *items, *en], w,
                "first-letter typeahead; Esc closes and focus returns to the row")


def reveal(r: Decimal) -> Node:
    """The heatmap reveal for a price row (§2.2, §8.3): the row's history as a windowed table, the pulled level named
    in words; opened by Shift+Enter (PROPOSED, C-4); focus on its heading; Esc returns to the opener."""
    w = 520
    heading = text("heading", k.ui(f"{k.price0(r)} · history, last {k.TRAIL_S} s", "the reveal's heading; E21-D04 "
                                   "W-14 words it"), k.HEADING_SM, k.TEXT_1)
    cols = (("time", 96), ("bid resting", 104), ("ask resting", 104), ("pulled", 200))
    for c, _w in cols:
        k.ui(c, "the reveal table's column words (E21-D04's CMP-111 reveal)")
    hdr = hbox("header row", [hbox(f"th · {c}", [text("value", c, k.CAPTION, k.TEXT_3)], {"padX": k.INSET_SM},
                                   w=cw, h=24) for c, cw in cols], {"fill": k.RAISED}, w=w - 16, h=24)
    rows = []
    for j, c in enumerate(range(k.PULL_COL - 8, k.PULL_COL + 4, 2)):
        v = k.row_size(r, "bid", k.DEFAULT_TIER, c) or Decimal(0)
        pulled = k.PULL_WORDS if c <= k.PULL_COL < c + 2 else ""
        vals = [k.hms(k.NOW, k.COLS - 1 - c), k.qty1(v), k.S("none"), pulled]
        rows.append(hbox(f"row · {j + 1:02d}", [hbox(f"td · {cn}", [text("value", vv, k.NUM_SM, k.TEXT_1)]
                                                     if vv else [], {"padX": k.INSET_SM}, w=cw, h=24)
                                                for (cn, cw), vv in zip(cols, vals)],
                         {"fill": k.CANVAS if j % 2 else k.RAISED}, w=w - 16, h=24))
    tbl = vbox("windowed table", [hdr, *rows], {}, w=w - 16, h=24 * (len(rows) + 1))
    n = vbox(f"heatmap reveal · {k.price0(r)}", [ring(heading), tbl],
             {"gap": k.STACK_SM, "pad": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_CARD}, w=w, note='role="region"; the pulled level named in words')
    n["h"] = math.ceil(k.est_height(n))
    return n


# --- the panel (one frame)
def info_row(name: str, kids: list[Node], y: int, fill: str, note: str) -> Node:
    return hbox(name, kids, {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": fill}, w=k.WIN_W, h=NOTICE_H, x=0, y=y,
                note=note)


def tier_notice(words: str, y: int) -> Node:
    return info_row("tier notice", [icon("glyph", "info", k.INFO_STRONG, k.ICON), text("words", words, k.CAPTION,
                                                                                       k.TEXT_1)], y, k.INFO_SUBTLE,
                    'dom.depth_changed {from: 200, to: 500, cause: user}; polite once (R-7)')


def shed_notice(y: int, *, focused: bool = False) -> Node:
    """W-21 with its pin (§4 depth-shed): stays until the tier is restored or pinned (no timeout)."""
    w21 = k.W("W-21")
    words, pin = w21.split(" · ", 1)
    b = button(pin, kind="secondary", h=24, name="pin button", focused=focused)
    b["note"] = f'native button, name "{k.S("Pin depth 200")}"'
    return info_row("shed notice (W-21)", [icon("glyph", "warning", k.WARN_STRONG, k.ICON),
                                           text("words", words, k.CAPTION, k.TEXT_1), b], y, k.WARN_SUBTLE,
                    "dom.depth_changed {from: 200, to: 50, cause: shed}; degraded.entered; polite once")


def body_h(p: P) -> int:
    """The ladder body's height in this frame (the tier and shed notices take a row each)."""
    extra = NOTICE_H * (bool(p.tier_notice) + (p.state == "shed"))
    return k.WIN_H - HEAD_H - NOTICE_H - extra - COLHEAD_H - FOOT_H - STRIP_H


# the depth control's left edge as the live header relayout placed it (the live check's fix; the estimate is 262)
LIVE_DEPTH_X = {"SCR-050/500-unavailable": 273}


def left_x(p: P, target: str) -> int:
    """x of a header-left child (by name prefix), from the kit's width estimates."""
    lb = header(p)["kids"][0]
    x = lb["x"]
    for c in lb["kids"]:
        if c["name"].startswith(target):
            return round(x)
        x += k.est_width(c) + k.PX[k.INSET_MD]
    raise LookupError(target)


def panel(fid: str, p: P, *, offset: int = 0, focus_row: Decimal | None = None, menu_row: Decimal | None = None,
          reveal_row: Decimal | None = None, markers: Iterable[Node] = ()) -> Node:
    """One SCR-050 frame (1280 × 800): header, notice, [tier / shed notice], column header, pane + ladder body (or the
    empty state), footer, detector strip; then the popovers, the rings and the board markers."""
    kids: list[Node] = [header(p), notice(p)]
    y = HEAD_H + NOTICE_H
    if p.tier_notice:
        kids.append(tier_notice(p.tier_notice, y))
        y += NOTICE_H
    if p.state == "shed":
        kids.append(shed_notice(y))
        y += NOTICE_H
    bh = k.WIN_H - y - COLHEAD_H - FOOT_H - STRIP_H
    ys: dict[Decimal, int] = {}
    fn = k.frame_name(fid)
    if p.state in ("empty-owner", "empty-other"):
        kids += empty_state(p, y, bh + COLHEAD_H)
        c = kids[-1]
        k.live(f"frame {fn!r}: the EmptyState card ({c['w']} wide) — centre horizontally in the frame (x {c['x']}) "
               f"and vertically in the panel body (y {y}–{y + bh + COLHEAD_H}, card top y {c['y']}); re-measure its h "
               f"after touchTexts and re-centre this card only")
    else:
        kids.append(colhead(y) if not p.table else table_caption(y))
        if p.table:
            kids += table_view(p, y + COLHEAD_H, bh)
        else:
            nodes, ys = body(p, y + COLHEAD_H, bh, offset)
            kids += nodes
        if p.state == "resyncing":
            kids += scrim(y + COLHEAD_H, bh)
            c = kids[-1]
            k.live(f"frame {fn!r}: the scrim label (W-10) — centre horizontally in the frame (x {c['x']}); its top stays "
                   f"at y {c['y']} (a quarter down the scrim), never centred vertically")
    kids.append(footer(k.WIN_H - FOOT_H - STRIP_H))
    kids.append(strip(p, k.WIN_H - STRIP_H))
    if focus_row is not None:
        kids.append(ring_rect(LADDER_W - 4, p.row_h, LADDER_X + 2, ys[focus_row]))
    if p.expanded:
        acc_y = ys[k.AGG_AT] + p.row_h
        kids.append(ring_rect(LADDER_W - LCOL_W[0] - 4, p.row_h, LADDER_X + LCOL_W[0] + 2, acc_y,
                              name="focus ring · first account row"))
    if p.menu in ("overflow", "overflow-arm"):
        m = overflow_menu(p)
        kids.append(dict(m, x=k.WIN_W - m["w"] - 12, y=HEAD_H - 6))
        k.live(f"frame {fn!r}: the ⋯ menu is anchored by its right edge 12 px inside the frame's right (x "
               f"{k.WIN_W - m['w'] - 12}, y {HEAD_H - 6}); keep the right edge if its w changes; never centre it")
    if p.menu == "depth":
        m = depth_listbox(p)
        dx = LIVE_DEPTH_X.get(fid, left_x(p, "depth"))
        kids.append(dict(m, x=dx, y=HEAD_H - 6))
        k.live(f"frame {fn!r}: the depth listbox popup is anchored at the depth control's left edge (x {dx}, y "
               f"{HEAD_H - 6}; the kit's estimate {left_x(p, 'depth')}); if the header relayout moves that control, "
               f"move the popup with it; never centre it")
    if menu_row is not None:
        m = row_menu(menu_row)
        kids.append(dict(m, x=LADDER_X + LCOL_W[0] + 24, y=min(ys[menu_row] + p.row_h + 2,
                                                                  k.WIN_H - FOOT_H - STRIP_H - m["h"] - 4)))
        k.live(f"frame {fn!r}: the row menu is anchored at x {kids[-1]['x']}, y {kids[-1]['y']} (below the "
               f"{k.price0(menu_row)} row); never centre it")
    if reveal_row is not None:
        m = reveal(reveal_row)
        kids.append(dict(m, x=24, y=max(y + COLHEAD_H + 8, ys[reveal_row] - m["h"] // 2)))
        k.live(f"frame {fn!r}: the reveal is anchored at x 24, y {kids[-1]['y']} (beside the {k.price0(reveal_row)} "
               f"row); never centre it")
    my = k.WIN_H - FOOT_H - STRIP_H - 8
    markers = list(markers)
    if markers:
        k.live(f"frame {fn!r}: the board markers stack bottom-left at x 12, the last ending at y {my} (8 px "
               f"above the footer); keep that anchor, never centre them")
    for mk in reversed(list(markers)):
        my -= mk["h"]
        kids.append(dict(mk, x=12, y=my))
        my -= 8
    return k.window(fid, kids)


def run(nn: int, built: list[tuple[Node, tuple[str, list[str]]]], cols: int, board_lines: Iterable[str] = ()) -> None:
    """The generators' last step: the twin's live check, then k.build (validator exit 0, .md, packed)."""
    b = k.BOARDS[nn]
    k.live("centring: only a node a line here names is centred, and only on the axis it names; every other node "
           "keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre")
    if b.twin:
        k.live(f"light twin: after the dark export, switch to the light theme (wait as the sheets README says) and "
               f"export the same board as {b.export_light}")
    k.build(nn, [x[0] for x in built], [x[1] for x in built], cols, board_lines=board_lines)
    print("ok", b.sheet)


# --- the Table view (§10) and the header positions (board 10's order markers)
def table_caption(y: int) -> Node:
    t = k.ui("Ladder table · the six columns of §2.3, `05`'s sort and filter", "the table's caption")
    filt = hbox("filter · My levels only", [box("box", [], {"stroke": k.TEXT_3, "strokeWidth": k.HAIR,
                                                            "strokeAlign": "inner", "radius": k.R_CONTROL}, w=14, h=14),
                                            text("label", k.S("My levels only"), k.CAPTION, k.TEXT_1)],
                {"gap": k.INSET_XS}, h=16)
    return box("table caption row", [text("caption", t, k.CAPTION, k.TEXT_2, x=12, y=5),
                                     dict(filt, x=k.WIN_W - round(k.est_width(filt)) - 12, y=4),
                                     rect("rule", k.WIN_W, 1, k.BORDER, x=0, y=COLHEAD_H - 1)],
               {"fill": k.CANVAS}, w=k.WIN_W, h=COLHEAD_H, x=0, y=y)


def table_view(p: P, y0: int, h: int) -> list[Node]:
    """`Table` (§10): the ladder as a semantic table, the six columns in §2.3's order, windowed with `05`'s "load more
    rows" control; under it the PROPOSED heatmap table (Price, Side, Resting size, Change over the trail, Estimated)."""
    cw = (176, 140, 140, 120, 140, 260)
    cols = [k.Col(f"c{i}", nm, w) for i, (nm, w) in enumerate(zip(k.COL_HEADS, cw))]
    rows = []
    for r in k.rows_window(25)[6:16]:
        side = k.row_side(r)
        pos = f" {k.Wf('W-25', {})}" if r == k.POSITION_AT else ""
        vals = [k.price0(r) + pos, side_cell(r, "bid", p.tier), side_cell(r, "ask", p.tier),
                k.qty1(v) if (v := k.row_prints(r, p.tier)) else "", k.qty1(k.cum_depth(r, p.tier) or Decimal(0)),
                own_words(r)]
        del side
        rows.append({f"c{i}": v or None for i, v in enumerate(vals)})
    lt = k.grid_table("ladder table (role=table)", cols, rows, row_h=24)
    more = button(k.S("load more rows"), kind="secondary", h=28, name="load more rows (05:195)")
    hcols = [k.Col("p", "Price", 176), k.Col("s", "Side", 120), k.Col("r", "Resting size", 160),
             k.Col("c", "Change over the trail", 220), k.Col("e", "Estimated", 200)]
    for c in hcols:
        k.S(c.label)
    hrows = []
    for r in (k.row_of(k.ICEBERG, "bid"), k.row_of(k.PULL_PRICE, "bid"), k.AGG_AT):
        now_, then = k.row_size(r, "bid", p.tier) or Decimal(0), k.row_size(r, "bid", p.tier, 0) or Decimal(0)
        d = now_ - then
        est = k.S("(estimated)") if r in (k.row_of(k.ICEBERG, "bid"), k.row_of(k.PULL_PRICE, "bid")) else None
        hrows.append({"p": k.price0(r), "s": k.ui("Bid", "the Side column's word"), "r": k.qty1(now_),
                      "c": (k.MINUS if d < 0 else "+") + k.qty1(abs(d)), "e": est})
    ht = k.grid_table("heatmap table (PROPOSED, role=table)", hcols, hrows, row_h=24,
                      cap=k.ui("Heatmap table (PROPOSED; `05` has no column set: G-4)", "the table's caption"))
    k.derive("Table view: 10 rows of the window (the table's own scroll, windowed); Change over the trail = the "
             f"row's size now less its size {k.TRAIL_S} s ago")
    stack = vbox("Table view", [lt, more, ht], {"gap": k.STACK_MD, "pad": k.INSET_MD}, w=k.WIN_W)
    return [rect("table body", k.WIN_W, h, k.CANVAS, x=0, y=y0), dict(stack, h=h, x=0, y=y0)]


def header_x(p: P, part: str, prefix: str) -> tuple[int, int]:
    """(x, y) of a header child ("left" / "right" group, by name prefix), from the kit's width estimates."""
    hd = header(p)
    grp = hd["kids"][0 if part == "left" else 1]
    x = grp["x"]
    for c in grp["kids"]:
        if c["name"].startswith(prefix):
            return round(x), grp["y"]
        x += k.est_width(c) + k.PX[k.INSET_MD]
    raise LookupError(prefix)
