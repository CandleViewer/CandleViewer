"""SCR-096 Tag manager parts (board 09 and board 10)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf  # noqa: E402
from wf import k  # noqa: E402

TCOLS = [k.Col("name", "name", 136), k.Col("cat", "category", 96), k.Col("n", "usage", 88, k.NUM_SM),
         k.Col("colour", "colour", 136), k.Col("auto", "auto rule", 168), k.Col("act", "", 48)]
TW = sum(c.w for c in TCOLS)
DW = TW + 2 * 24
FRAME_W = DW + 2 * k.FRAME_PAD + 2 * 24
COLOUR = k.quote("tag.neutral", "schema")


def usage(name: str) -> int:
    """Trades (LIVE and DEMO: tags are global, `21`:3379) carrying the tag."""
    return sum(1 for t in k.JOURNAL if name in [n for n, _a in t.tags])


def swatch() -> list[k.Node]:
    return [k.rect("swatch", 12, 12, k.NEUTRAL, {"radius": k.R_CONTROL, "stroke": k.BORDER_STRONG,
                                                 "strokeWidth": k.HAIR}),
            k.text("token", COLOUR, k.CAPTION, k.TEXT_1)]


def tag_rows(tags: list[tuple[str, str, str]] | None = None, *, t2: bool = False) -> list[dict[str, Any]]:
    out = []
    for name, cat_, auto in tags if tags is not None else list(k.TAGS):
        assert cat_ in k.TAG_CATEGORIES and len(name) <= 24
        out.append({"name": name, "cat": cat_, "n": f"{usage(name)} trades", "colour": swatch(),
                    "auto": auto or "—", "act": [k.icon("more", "more-horizontal", k.TEXT_2)]})
    return out


def table(**kw: Any) -> Any:
    k.derive("usage counts: trades carrying each tag in the whole journal (LIVE and DEMO; tags are global): " +
             ", ".join(f"{n} {usage(n)}" for n, _c, _a in k.TAGS))
    return k.grid_table("CMP-049 tag table", TCOLS, tag_rows(**kw), row_h=28)


def modal(kids: list[Any], actions: list[Any] | None = None, *, focus_create: bool = False) -> Any:
    create = wf.btn(k.ui("Create tag"), primary=True)
    search = k.hbox("search field", [k.icon("glyph", "search", k.TEXT_2), k.text("placeholder", k.ui("Search tags"),
                                                                             k.BODY, k.TEXT_2)],
                    {"padX": k.INSET_SM, "gap": k.INSET_XS, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                     "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=240, h=wf.CTRL_H)
    top = k.hbox("toolbar", [search, wf.ring(create) if focus_create else create],
                 {"justify": "space-between"}, w=TW, h=wf.CTRL_H)
    return wf.dialog(k.memo('"Manage tags"')[1:-1], [top, *kids], actions or [wf.btn(k.ui("Close"))], DW,
                     name="CMP-043 dialog · SCR-096")


def behind() -> str:
    return "SCR-093 Journal behind the modal"
