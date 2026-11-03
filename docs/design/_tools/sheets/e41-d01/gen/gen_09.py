"""Board 09 scr096-tag-manager: the SCR-096 modal — default (name, category, usage count, colour as text), create,
rename, merge and delete (each confirm restates the affected trade count), empty and error."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s096  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 9
FW = s096.FRAME_W
BW = FW - 2 * k.FRAME_PAD
H = "### SCR-096"


def default(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    m = s096.modal([s096.table()])
    return (k.frame(fid, [wf.backdrop(m, BW, words=s096.behind())], FW,
                    "SCR-096 default — a modal from SCR-093's header; one row per tag: name, category, usage, the "
                    "colour token in text, the auto rule"),
            k.frame_block(fid, ["`14` A11y lists a description column; `21` journal_tags has none — not drawn "
                                "(E41-D02 #1018 decides)", "Colour: tag.neutral is `21`'s default colour_token; "
                                "the hue picker is hi-fi (E41-D02) and always paired with the text"],
                          wds=["WD-7", "WD-12"]))


def create(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    name = "breakout-retest"
    row = k.hbox("create row", [wf.textfield(k.ui("Name"), name, 240, counter=f"{len(name)} / 24", focused=True),
                                wf.select(k.ui("Category"), "setup", 160),
                                wf.btn(k.ui("Save"), primary=True), wf.btn(k.ui("Cancel"))],
                 {"gap": k.INSET_SM, "align": "end", "padX": k.INSET_SM, "padY": k.INSET_SM, "fill": k.RAISED},
                 w=s096.TW)
    k.derive(f"create: '{name}' is {len(name)} characters (≤ 24, `14` SCR-096 validation); category from `21`'s "
             f"enum {', '.join(k.TAG_CATEGORIES)}")
    return (k.frame(fid, [wf.backdrop(s096.modal([row, s096.table()]), BW, words=s096.behind())], FW,
                    "SCR-096 create — an inline row: name with a 24-character counter, an optional category"),
            k.frame_block(fid, [f"`14`: {k.cat('tag names unique, ≤24 chars', H)}; `22` allows 40 (memo G-3)"],
                          wds=["WD-7"]))


def confirm(title: str, lines: list[str], action: str, *, field: k.Node | None = None) -> k.Node:
    body = [field] + [k.text(f"line {i + 1}", ln, k.BODY, k.TEXT_1, w=440) for i, ln in enumerate(lines)]
    return wf.dialog(title, body, [wf.btn(k.ui("Cancel")), wf.btn(action, primary=True)], 488,
                     name="CMP-044 confirm dialog")


def rename(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    old, new = "fomo", "chased-entry"
    n = s096.usage(old)
    d = confirm(k.ui(f"Rename '{old}'"), [k.ui(f"Renames the tag on {n} trades.")], k.ui("Rename"),
                field=wf.textfield(k.ui("New name"), new, 240, counter=f"{len(new)} / 24"))
    k.derive(f"rename: '{old}' is on {n} trades")
    return (k.frame(fid, [wf.backdrop(d, BW, words="SCR-096 tag manager behind the confirm")], FW,
                    "SCR-096 rename — the confirm restates the affected trade count"),
            k.frame_block(fid, ["Audited: journal.tag_renamed with {affectedTrades} (`14` SCR-096)"], wds=["WD-7"]))


def merge(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    a, b = "late-entry", "moved-stop"
    ta = {t.no for t in k.JOURNAL if a in [x for x, _y in t.tags]}
    tb = {t.no for t in k.JOURNAL if b in [x for x, _y in t.tags]}
    d = confirm(k.ui(f"Merge '{a}' into '{b}'"), [k.ui(f"{len(ta)} trades move from '{a}' to '{b}'; {len(ta & tb)} "
                                                       f"of them already carry '{b}'."),
                                                  k.ui(f"'{b}' will be on {len(ta | tb)} trades.")], k.ui("Merge"))
    k.derive(f"merge: '{a}' on {len(ta)} trades, '{b}' on {len(tb)}, both on {len(ta & tb)}; union {len(ta | tb)}")
    return (k.frame(fid, [wf.backdrop(d, BW, words="SCR-096 tag manager behind the confirm")], FW,
                    "SCR-096 merge — the confirm warns how many trades are affected (`14` validation)"),
            k.frame_block(fid, ["Audited: journal.tag_merged with {affectedTrades}; `22` has no merge operation "
                                "(memo G-3)"], wds=["WD-7"]))


def delete(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    name = "news"
    n = s096.usage(name)
    d = confirm(k.ui(f"Delete '{name}'"), [k.ui(f"{n} trades lose the tag. The trades themselves stay.")],
                k.ui("Delete tag"))
    k.derive(f"delete: '{name}' is on {n} trades")
    return (k.frame(fid, [wf.backdrop(d, BW, words="SCR-096 tag manager behind the confirm")], FW,
                    "SCR-096 delete — the confirmation restates how many trades lose the tag"),
            k.frame_block(fid, ["`14` checklist: delete confirmation restates how many trades lose the tag"],
                          wds=["WD-7"]))


def empty(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    es = wf.empty_state(k.ui("No tags yet"), k.ui("Tags created here, or added on a trade, are listed with their "
                                                  "usage"), s096.TW, actions=[wf.btn(k.ui("Create tag"))])
    return (k.frame(fid, [wf.backdrop(s096.modal([es]), BW, words=s096.behind())], FW,
                    "SCR-096 empty — no tag exists yet"),
            k.frame_block(fid, ["`14` checklist: empty state; §7.1 has no tag-manager empty string (kit label)"]))


def error(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    name = "Breakout"
    clash = next(n for n, _c, _a in k.TAGS if n.lower() == name.lower())
    row = k.hbox("create row", [wf.textfield(k.ui("Name"), name, 240, counter=f"{len(name)} / 24",
                                             error=k.ui(f"'{clash}' exists; names are unique ignoring case"),
                                             focused=True),
                                wf.select(k.ui("Category"), "setup", 160), wf.btn(k.ui("Save"), primary=True),
                                wf.btn(k.ui("Cancel"))],
                 {"gap": k.INSET_SM, "align": "start", "padX": k.INSET_SM, "padY": k.INSET_SM, "fill": k.RAISED},
                 w=s096.TW)
    k.derive(f"error: '{name}' clashes with '{clash}' under `21`'s unique index on lower(name)")
    return (k.frame(fid, [wf.backdrop(s096.modal([row, s096.table()]), BW, words=s096.behind())], FW,
                    "SCR-096 error — a duplicate name; the message sits under the field, in words and a glyph"),
            k.frame_block(fid, ["`21` ux_jtag_name: unique lower(name)"], wds=["WD-7"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((default, create, rename, merge, delete, empty, error), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 3)
