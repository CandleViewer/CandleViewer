"""E47-D13 / 08 entry-insets (dark): the entry links on SCR-117 and SCR-119 as insets (with E47-D05 #1304's SCR-117
frame) (§7.1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, stop, tag_right  # noqa: E402

NN = 8
F_117, F_119 = k.frames_of(NN)
L71 = k.L("### 7.1 Route, entry and chunk")
ST = k.State()


def option_row(i: int) -> k.Node:
    k.fallback("chrome")
    return k.hbox(f"option {i} (placeholder)", [k.placeholder("toggle", 38, 20),
                                                k.vbox("text", [k.placeholder("label", 180 + 20 * (i % 3), 12),
                                                                k.placeholder("description", 280, 10)],
                                                       {"gap": k.STACK_XS}, h=26)],
                  {"gap": k.INSET_MD, "align": "start"}, w=560, h=28)


def page_117() -> tuple[k.Node, dict[str, int]]:
    k.copy_gap(f'h1 "{k.SCR117}": the settings nav entry of `14` SCR-110 L{k.SCR110_LINE} (SCR-117\'s page title is '
               "E47-D05's)")
    opts = [option_row(i) for i in range(1, 8)]
    links = k.hbox("links · ASS:150-151", [k.link(k.w("W-1"), ST, name="link · statement", focused=True),
                                           k.text("separator", "|", k.BODY, k.TEXT_2),
                                           k.link(k.w("W-3"), ST, name="link · SCR-013")],
                   {"gap": k.INSET_SM}, h=34, note="the shipped paragraph: two CMP-021 links (ASS:150, :151)")
    col = k.vbox("SCR-117 body", [k.text("h1", k.SCR117, k.HEADING_LG, k.TEXT_1), *opts, links], {"gap": k.STACK_LG},
                 w=k.PAGE_W, x=k.PAGE_PAD, y=k.PAGE_PAD)
    y_links = k.PAGE_PAD + int(sum(k.est_height(n) for n in (k.text("p", "x", k.HEADING_LG), *opts))
                               + 8 * k.PX[k.STACK_LG])
    return k.box("page · SCR-117", [col], {"fill": k.APP}, w=k.CONTENT_W, h=k.BODY_H), {"links": y_links}


def page_119() -> tuple[k.Node, dict[str, int]]:
    k.copy_gap(f'h1 "{k.SCR119}": `14` SCR-119\'s title (L{k.SCR119_LINE - 2})')
    kv = [k.hbox(f"KeyValueRow {i} (placeholder)", [k.placeholder("key", 120), k.placeholder("value", 160)],
                 {"gap": k.INSET_LG}, w=560, h=24) for i in range(1, 5)]
    links = k.vbox("links", [k.hbox("link 1 (placeholder)", [k.placeholder("hotkey cheatsheet link", 140)], None, h=20),
                             k.link(k.w("W-1"), ST, name="link · statement", focused=True),
                             k.hbox("link 3 (placeholder)", [k.placeholder("methodology link", 160)], None, h=20)],
                   {"gap": k.STACK_SM}, w=560)
    col = k.vbox("SCR-119 body", [k.text("h1", k.SCR119, k.HEADING_LG, k.TEXT_1),
                                  k.vbox("version table (placeholder)", kv, {"gap": k.STACK_XS}, w=560), links],
                 {"gap": k.STACK_LG}, w=k.PAGE_W, x=k.PAGE_PAD, y=k.PAGE_PAD)
    y_links = k.PAGE_PAD + 24 + 16 + 4 * 24 + 3 * 4 + 16 + 20 + k.PX[k.STACK_SM]
    return k.box("page · SCR-119", [col], {"fill": k.APP}, w=k.CONTENT_W, h=k.BODY_H), {"links": y_links}


def frame_117() -> tuple[k.Node, tuple[str, list[str]]]:
    pg, sp = page_117()
    y = k.MAIN_Y + sp["links"]
    ov = [stop(1, y + 4, "entry link"),
          k.outline("inset · the entry", k.MAIN_X + k.PAGE_PAD - 8, y - 8, 379, 50),  # 8 px a side (live check)
          tag_right(f"entry: {k.wcite('W-1')} (ASS:150, verbatim) -> /accessibility · focused", y + 4),
          tag_right("SCR-117's body: E47-D05 (#1304, unmerged) · placeholders", k.MAIN_Y + 30)]
    fr = k.window(F_117, pg, current=k.SCR117, overlays=ov, note="SCR-117 with the statement link focused")
    lines = [f"§7.1 L{L71}: entries are SCR-117's link (W-1; `14`:2476) and SCR-119's link (`14`:2503); a direct "
             "visit works; every role sees the same page",
             f"`14` SCR-117 L{k.SCR117_LINE}: the section's options and \"a link to the a11y statement\"; the "
             "options are E47-D05's (#1304, unmerged): drawn as placeholders, never decided here",
             "The as-built paragraph (ASS:150-151): W-1 then W-3, two CMP-021 links",
             "On browser Back from the statement, focus returns to this link (router restore-on-back, §7.4)"]
    return fr, k.frame_block(F_117, lines, keyboard="Enter on the focused link opens /accessibility; Back restores "
                                                    "focus here")


def frame_119() -> tuple[k.Node, tuple[str, list[str]]]:
    pg, sp = page_119()
    y = k.MAIN_Y + sp["links"]
    ov = [stop(1, y + 2, "entry link"),
          k.outline("inset · the entry", k.MAIN_X + k.PAGE_PAD - 8, y - 8, 171, 38),  # 8 px a side (live check)
          tag_right(f"entry: the statement link ({k.wcite('W-1')}'s words) · focused", y + 4),
          tag_right("SCR-119's other items: placeholders (`14` SCR-119)", k.MAIN_Y + 30)]
    fr = k.window(F_119, pg, overlays=ov, note="SCR-119 with the statement link focused")
    lines = [f"`14` SCR-119 L{k.SCR119_CHECK_LINE}: \"links to the hotkey cheatsheet, accessibility statement and "
             "the detector methodology drawer\"; the version table and the other links are placeholders",
             f"The statement is SCR-119∕statement, a sub-view with no SCR id of its own (D13-C7; `14`:33 band full); "
             f"{k.SCR119} stays selected in the nav on the statement page",
             "The link's words: W-1 (the shipped SCR-117 link's words), reused here (copy gap)"]
    k.copy_gap("SCR-119's statement link reuses W-1's words (`14` names the link, not its text)")
    return fr, k.frame_block(F_119, lines, keyboard="Enter follows the link; Back restores focus to it")


def build() -> None:
    fr = [frame_117(), frame_119()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
