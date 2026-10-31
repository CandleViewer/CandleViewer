"""Pair 4 (boards 03 and 07) helpers on top of e08d09kit. No kit edits; every string comes from the spec through
k.w() / k.state_word() or is recorded as a copy gap with its spec line."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e08d09kit as k  # noqa: E402

Node = dict[str, Any]


def cite(keys: Iterable[str]) -> str:
    """'Strings: W-44 (§15 L460) · …' for the annotation (every drawn string with its spec line)."""
    return "Strings: " + " · ".join(f"{x} (§15 L{k.COPY[x].line})" for x in keys)


def num(n: int) -> str:
    """Thousands with a space, as the deck writes "21 000" (W-46)."""
    return f"{n:,}".replace(",", " ")


def page_top() -> float:
    """Height of band + rule + PageHeader + their gaps inside the page (window() order, space.stack.lg 16)."""
    return k.est_height(k.band()) + 16 + k.RULE_H + 16 + k.est_height(k.page_header()) + 16


def filler(label: str, h: int) -> Node:
    """An unfilled stand-in for the sections above the drawn one; scrolled out of the view, so never visible."""
    k.deviate(f"'{label}': the sections above are scrolled out of the view and stand in as one unfilled "
              f"{h} px block (drawn on board 01); the scroll offset in the main column's note is therefore nominal")
    return k.rect(label, k.INNER_W, h, None, note="scrolled out of view; drawn on board 01")


def scroll_to(filler_h: int) -> int:
    """The scroll that puts the first section after the filler at the top of the main column's view."""
    return int(round(page_top() + filler_h + 16))


def select_box(label_: str, value: str, *, w_: int = 200) -> Node:
    """A native select (§14 'account and class pickers (native selects)'): label, then a 32 px field with the value
    and a chevron-down."""
    fld = k.hbox("field", [k.text("value", value, k.BODY, k.TEXT_1),
                           k.icon("chevron", "chevron-down", k.TEXT_2)],
                 {"padX": k.INSET_SM, "justify": "space-between", "radius": k.R_CONTROL, "fill": k.CANVAS,
                  "stroke": k.TEXT_3, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w_, h=k.CONTROL_H)
    return k.vbox(f"select · {label_}", [k.text("label", label_, k.LABEL, k.TEXT_2), fld], {"gap": k.INSET_XS},
                  note="native <select>")


def lines_panel(name: str, head: Node, lines: list[tuple[str, str, str]], *, w_: int = k.INNER_W,
                stroke: str | None = None) -> Node:
    """A raised panel: the state line, then text lines (name, chars, typo)."""
    inner = w_ - 2 * k.PX[k.INSET_LG]
    kids = [head] + [k.text(n, c, t, k.TEXT_1 if t != k.CAPTION else k.TEXT_2, w=inner) for n, c, t in lines]
    o: dict[str, Any] = {"fill": k.RAISED, "radius": k.R_CARD, "pad": k.INSET_LG, "gap": k.STACK_SM}
    if stroke:
        o.update(stroke=stroke, strokeWidth=k.HAIR, strokeAlign="inner")
    return k.vbox(name, kids, o, w=w_)


def clip_rows(rows: list[Node], room: float) -> tuple[list[Node], int]:
    """Rows that reach into a view of `room` px (one past the edge is kept, clipped); returns (drawn, not drawn)."""
    out, used = [], 0.0
    for r in rows:
        if used > room:
            break
        out.append(r)
        used += k.est_height(r)
    return out, len(rows) - len(out)


def fixed_box(name: str, kids: list[Node], h: int, *, w_: int = k.INNER_W, note: str | None = None) -> Node:
    """A clipped column of fixed height (a virtualised grid's viewport)."""
    return k.vbox(name, kids, {"clip": True}, w=w_, h=h, note=note)
