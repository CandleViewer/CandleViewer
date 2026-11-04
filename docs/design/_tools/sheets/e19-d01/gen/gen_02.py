"""Board 02 competitive-teardown: memo §8 as a text-only matrix (public documentation only; URLs stay in the memo) and
four greyscale schematics redrawn from the vendor's public words — no vendor screenshot, asset, logo or trade dress."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 2
_Q = re.compile(r'"([^"]+)"', re.DOTALL)


def source(cell: str) -> str:
    m = re.search(r"fetched (\d{4}-\d{2}-\d{2})", cell, re.DOTALL)
    if "://" in cell:
        if not m:
            raise ValueError(f"a URL without a fetched date: {cell[:40]!r}")
        return f"public documentation page, fetched {m.group(1)} (URL in memo §8)"
    return cell


def matrix(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rows = [{"v": c[0], "lab": c[1], "dev": c[2], "src": source(c[3])} for _i, c in k.COMPETITIVE]
    t = rb.table("competitive matrix", [("v", "vendor / surface", 240), ("lab", "POC / VAH / VAL labelling", 440),
                                        ("dev", "developing value area", 400), ("src", "source", 312)], rows,
                 cap=f"memo §8 L{k.COMPETITIVE_LINE}: six rows, text only; vendor words in straight quotes as read on "
                     "the fetched date; 'unsourced observation' rows are not established")
    reading = k.sentence_after("**Reading (heuristic):**")
    k.deviate("matrix: the three fetched rows' URLs are written as 'public documentation page, fetched <date> (URL in "
              "memo §8)' — a board carries no URL (kit rule); the memo keeps the links")
    return (k.frame(fid, [t, rb.card("reading", [k.text("label", "Reading (heuristic)", k.LABEL, k.TEXT_2),
                                                 rb.para("words", reading, rb.IW - 24)], rb.IW)], rb.FW,
                    "Research — how three tools label POC / VAH / VAL and the developing value area, from public "
                    "documentation; PD-1 and PD-2 rest on the findings, not on this review"),
            k.frame_block(fid, ["Rows verbatim from memo §8 but the URL cells; no screenshot (BQ-12)"]))


def letters(name: str, rows: list[int], *, hi: int | None = None, x0: int = 0, w: int = 16) -> list[k.Node]:
    """A generic letter-block column: row i holds rows[i] blocks; block hi drawn with a thick outline."""
    out: list[k.Node] = []
    for i, n in enumerate(rows):
        for j in range(n):
            out.append(k.rect(f"{name} block {i + 1}.{j + 1}", w - 2, 12, k.TEXT_3, x=x0 + j * w, y=8 + i * 14))
        if hi == i:
            out.append(k.rect(f"{name} highlight", n * w + 2, 16, None, {"stroke": k.TEXT_1, "strokeWidth": k.THICK,
                                                                         "strokeAlign": "outer"},
                              x=x0 - 2, y=6 + i * 14))
    return out


def schematic(name: str, kids: list[k.Node], w: int, h: int) -> k.Node:
    k.fallback("schematic")
    return k.box(name, kids, {"fill": k.SUNKEN, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                 w=w, h=h, note="schematic redrawn from public text; not a vendor image")


def schematics(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cw = (rb.IW - 3 * 16) // 4
    r0, r1, r2 = (c for _i, c in k.COMPETITIVE[:3])
    q0, q1, q2 = _Q.findall(r0[1]), _Q.findall(r1[2]), _Q.findall(r2[1])
    shape = [2, 3, 4, 6, 5, 3, 2, 1]
    a = schematic("poc highlighted", letters("a", shape, hi=3, x0=24), cw - 24, 136)
    steps = [(0, 5, 4), (1, 5, 3), (2, 4, 3), (3, 4, 2), (4, 3, 2), (5, 3, 1)]
    bk: list[k.Node] = []
    for i, top, bot in steps:
        bk += [k.rect(f"bar {i + 1}", 6, 72, k.TEXT_3, x=24 + i * 40, y=24),
               k.rect(f"upper line {i + 1}", 32, 2, k.TEXT_1, x=20 + i * 40, y=24 + top * 6),
               k.rect(f"lower line {i + 1}", 32, 2, k.TEXT_1, x=20 + i * 40, y=24 + 72 - bot * 6)]
    b = schematic("developing lines", bk, cw - 24, 136)
    c = schematic("initial balance line", [k.rect("vertical line", 3, 44, k.TEXT_1, x=12, y=8),
                                           *letters("c", shape, x0=24)], cw - 24, 136)
    d = schematic("until future intersection", [*letters("d", [3, 4, 6, 4, 2], hi=2, x0=12),
                                                k.rect("extended line", cw - 140, 2, k.TEXT_1, x=110, y=43),
                                                k.rect("later bar", 6, 64, k.TEXT_3, x=cw - 32, y=12)], cw - 24, 136)
    cards = [rb.card(f"schematic · {n}", [k.text("vendor", r[0], k.LABEL, k.TEXT_2, w=cw - 24), s,
                                          *[k.text(f"quote {i + 1}", f'"{q}"', k.CAPTION, k.TEXT_1, w=cw - 24)
                                            for i, q in enumerate(qs)],
                                          k.text("note", note, k.CAPTION, k.TEXT_3, w=cw - 24)], cw)
             for n, r, s, qs, note in (
                 ("1", r0, a, q0[:1], "POC as highlighted blocks; no word on the level"),
                 ("2", r1, b, q1, k.memo("no word on the chart says developing")),
                 ("3", r2, c, q2, "IB as a vertical line left of the letters"),
                 ("4", r0, d, q0[1:], "POC line extended until a later bar trades it (a naked-POC ray)"))]
    for n in ("POC as highlighted blocks; no word on the level", "IB as a vertical line left of the letters",
              "POC line extended until a later bar trades it (a naked-POC ray)"):
        k.ui(n, "schematic caption, paraphrasing the quoted vendor words above it")
    return (k.frame(fid, [k.hbox("schematics", cards, {"gap": k.INSET_LG, "align": "start"}, w=rb.IW),
                          rb.marker("schematics redrawn in greyscale from the vendor's public words (memo §8); no "
                                    "vendor screenshot, asset or logo", 640)], rb.FW,
                    "Research — four documented patterns redrawn as schematics: highlighted POC blocks, developing "
                    "lines with no word, the IB line, the extended (naked) POC"),
            k.frame_block(fid, ["Only the fetched Sierra Chart rows are drawn; TradingView and DeepCharts rows are "
                                "unsourced and get no schematic", "Block counts are abstract shapes, not data"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((matrix, schematics), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 1)
