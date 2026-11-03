"""Board 03 period-mode-map: memo §6.1 — the four source vocabularies mapped onto the five user-facing modes and the
`24` kinds — and §6.2's PROPOSED defaults: Session for the docked panel, Visible range for the overlay, a header menu
button, and SCR-039's radio group (PD-6, PD-7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 3
HEAD = "### 6.1 The user-facing vocabulary"


def vocabulary(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hd = k.table_head(HEAD)
    keys = ("mode", "kind", "req", "w14", "cmp")
    widths = (232, 280, 328, 256, 296)
    rows = [dict(zip(keys, c)) for _i, c in k.MODES]
    t = rb.table("vocabulary map", list(zip(keys, hd, widths)), rows,
                 cap=f"memo §6.1 L{k.MODES_LINE}: one row per user-facing mode (PROPOSED words); the other four "
                     "columns are the source vocabularies it replaces")
    after = k.LINES["spec"][k.MODES_LINE + 9].replace("**", "").strip()
    if not after.startswith("`bar` belongs"):
        raise ValueError("§6.1: the sentence after the table moved")
    srcs = [(hd[i], [c[i] for _j, c in k.MODES]) for i in (3, 4, 1, 2)]
    lanes = [rb.card(f"source · {i + 1}", [k.text("label", lab, k.LABEL, k.TEXT_2, w=300),
                                           *[rb.badge(w_, name=f"word · {j + 1}") for j, w_ in enumerate(ws)]], 332)
             for i, (lab, ws) in enumerate(srcs)]
    return (k.frame(fid, [t, k.hbox("source lanes", lanes, {"gap": k.INSET_LG, "align": "start"}, w=rb.IW),
                          rb.card("not user-facing", [rb.para("words", after, rb.IW - 24)], rb.IW)], rb.FW,
                    "Research — five user-facing modes, each mapped to one `24` kind; the four source vocabularies "
                    "(`14`, CMP-183, `24`, `22`) shown as lanes of their own words"),
            k.frame_block(fid, [k.f_line("F-7"), k.f_line("F-8"), f"A-1: {k.AMEND['A-1'][2]}"], ["PD-6"]))


def defaults(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    words = k.mode_words()
    items = [(c[0], c[1]) for _i, c in k.MODES]
    pw = 420
    docked = rb.card("docked panel", [
        k.text("label", "Docked panel — opens on Session (the UTC day)", k.LABEL, k.TEXT_2, w=pw - 24),
        k.hbox("panel header", [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1),
                                rb.menu_button(words[0], open_=True)], {"gap": k.INSET_SM, "padX": k.INSET_SM,
                                                                        "fill": k.RAISED}, w=pw - 24, h=32),
        rb.menu(items, words[0], pw - 24)], pw)
    overlay = rb.card("chart overlay", [
        k.text("label", "Chart overlay — opens on Visible range", k.LABEL, k.TEXT_2, w=pw - 24),
        k.hbox("overlay legend row", [k.text("title", k.ui("Volume profile"), k.BODY_STRONG, k.TEXT_1),
                                      rb.menu_button(words[2])], {"gap": k.INSET_SM, "padX": k.INSET_SM,
                                                                   "fill": k.RAISED}, w=pw - 24, h=32),
        k.text("follows", k.memo("it follows the viewport the trader is already reading"), k.CAPTION, k.TEXT_2,
               w=pw - 24)], pw)
    dialog = rb.card("SCR-039 settings", [
        k.text("label", "SCR-039 settings dialog — keeps its radio group", k.LABEL, k.TEXT_2, w=pw - 24),
        rb.radio_group(k.ui("Period mode"), words, words[0], pw - 24)], pw)
    for s in ("Docked panel — opens on Session (the UTC day)", "Chart overlay — opens on Visible range",
              "SCR-039 settings dialog — keeps its radio group"):
        k.ui(s, "board label summarising memo §6.2")
    para = k.LINES["spec"][k.L("### 6.2 Default mode and switcher") + 1].replace("**", "").strip()
    k.derive("menu items: memo §6.1's five modes in order, each with its `24` kind cell (Anchored: none — A-1)")
    return (k.frame(fid, [k.hbox("three surfaces", [docked, overlay, dialog], {"gap": k.INSET_LG, "align": "start"},
                                 w=rb.IW),
                          rb.card("memo §6.2", [rb.para("words", para, rb.IW - 24)], rb.IW)], rb.FW,
                    "Research — the PROPOSED defaults and switcher: a menu button showing the current mode word in "
                    "the header (five words do not fit a compact segmented control, F-10)"),
            k.frame_block(fid, [k.f_line("F-9"), k.f_line("F-10"), f"A-4: {k.AMEND['A-4'][2]}",
                                "Both defaults PROPOSED for the owner (memo §6.2); RQ1 / RQ2 untested (T1, T3)"],
                          ["PD-7"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((vocabulary, defaults), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
