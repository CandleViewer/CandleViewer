"""Pair 4 (boards 04 row-states and 09 row-states-light): the shared frame builders. Imports the kit; adds nothing to
it. Every string is the spec's (E12-D07 §6, §6.2, §7.4), E11-D04's (:183, :254, :264) or the kit's seeded data."""
from __future__ import annotations

import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import e12d07kit as k  # noqa: E402
from pair1_helpers import median_denom  # noqa: E402

MODE = "time"
SPAN = ("13:24", "13:42")  # build notes §4 row "04 states/all-words": 13:24-13:42, the forming bar last

# §6's specimen rows on the all-words frame: hh:mm -> tagged words (forming and `no range` are derived, never tagged).
# `corrected` lasts "until the next close" (§6 L225), so it sits on the last closed bar (13:41).
SPECIMENS = {"13:25": ("POC",), "13:27": ("Est.",), "13:29": ("Est.", "POC"), "13:31": ("width capped",),
             "13:37": ("stale",), "13:41": ("corrected",)}
WORD_LINE = {w: k.find_line(f"| `{w}`") for w in ("forming", "corrected", "stale", "width capped", "no range",
                                                  "Est.", "POC", "—")}


def width_n(b: k.Bar) -> str:
    """§6's N for `width capped`: D06's r = v ÷ max(median v, smallest non-zero v) over the loaded series, to one
    decimal (ruling P-3: the board shows the computed factor, as board 06 does)."""
    return f"{b.v / median_denom(k.series(MODE)):.1f}"


def name_adds(word: str, b: k.Bar | None = None) -> str:
    """§6's "Accessible name adds" cell for a word, verbatim (quotes kept); for `width capped` the quoted name with
    N filled in from row b's data (§6: "N the computed factor")."""
    c = k._cells(k.SPEC_LINES[WORD_LINE[word] - 1])
    if word != "width capped":
        return c[3]
    m = re.match(r'"([^"]*\(N × median\))"', c[3])
    if not m or b is None:
        raise LookupError(f"§6 `width capped` name cell changed or no row given: {c[3]!r}")
    return '"' + m.group(1).replace("(N ×", f"({width_n(b)} ×") + '"'


def words_of(b: k.Bar) -> list[str]:
    """Every applicable §6 word of a row, in §6's precedence (all of them go into the accessible name)."""
    ws = set(b.words) | ({"forming"} if not b.confirm else set()) | ({"no "
                                                                      "range"} if b.o == b.h == b.l == b.c else set())
    return [w for w in k.STATE_ORDER if w in ws]


def full_name(b: k.Bar) -> str:
    adds = [name_adds(w, b).strip('"').split('" (')[0].strip('"') for w in words_of(b)]
    return ", ".join([k.row_name(b, MODE), *adds])


def rows_span(stale_all: bool = False) -> tuple[list[k.Bar], int]:
    s = k.series(MODE)
    i0, i1 = k.at(MODE, SPAN[0]), k.at(MODE, SPAN[1])
    out = []
    for b in s[i0:i1 + 1]:
        hm = k.hhmm(b.t)
        if stale_all:
            b = k.tag(b, "stale") if b.confirm else b
        elif hm in SPECIMENS:
            b = k.tag(b, *SPECIMENS[hm])
        out.append(b)
    return out, len(s)


def all_words_frame(fid: str) -> tuple[k.Node, tuple[str, list[str]], list[k.Bar]]:
    """states/all-words: time 1m, chart type Equi-volume (state 12 chars, §5), RightRail strip; one row per §6 word."""
    rows, loaded = rows_span()
    w = k.dock_w("strip")
    cols = k.shown_columns(MODE)
    cap = k.caption_text(rows, MODE, loaded=loaded)
    focus = next(b for b in rows if k.hhmm(b.t) == "13:29")
    body = [k.bar_row(b, cols, MODE, i + 1, focused=b is focus, equi=True) for i, b in enumerate(rows)]
    t = k.table(body, w=w, h=k.table_room(), caption_chars=cap, header=k.header_row(cols, MODE, equi=True),
                footer=k.footer_row(w - 16))
    fr = k.window(fid, k.panel(MODE, t, w=w, chart="Equi-volume"), rail="strip")
    per_row = []
    for b in rows:
        ws = words_of(b)
        if ws:
            per_row.append(f"{k.hhmm(b.t)} `{b.state}` — name adds " + "; ".join(
                f"{name_adds(x, b)} (§6 L{WORD_LINE[x]})" for x in ws))
    closed_plain = [k.hhmm(b.t) for b in rows if not words_of(b)]
    blk = k.frame_block(
        fid, state=f"{fid.split(' · ')[0]} (§6 L{k.L('## 6. The')}-{k.L('| `—`            |')}: every `state` word "
                   "once, precedence forming, stale, corrected, "
                   f"width capped, no range, Est., POC; `Est.·POC` the one joined form, D04E11:183; chart type "
                   f"Equi-volume widens `state` to 12 characters, §5)",
        mode=MODE, cols=cols, chart="Equi-volume",
        row_header_form=f"{k.row_header(focus, MODE)} — name: {full_name(focus)}",
        keyboard="Alt+T opened the table in place; focus on the cursor bar's row (D04E11 D2), 13:29 (Est.·POC); ↑ / ↓ "
                 "move the row (origin table); Esc or Alt+T back to the chart. The focused row carries the 2 px "
                 "color.focus.ring (aria-current)",
        announcement="Data table, row k of N (D04E11 D2); the words are in each row's accessible name, not announced",
        tokens=k.frame_tokens(fr),
        extra=["Row words (each word's accessible-name addition, §6 table):", *per_row,
               f"Closed rows unmarked (§6 L{k.L('| `—`            |')} `—`, \"nothing\"; no word \"closed\", §6 "
               f"L{k.L('One lowercase')}): {', '.join(closed_plain)}",
               f"Forming row 13:42: values color.text.secondary, `forming` primary, aria-describedby "
               f"{name_adds('forming').split(' (')[0]} (D04E11:254)"])
    return fr, blk, rows


def stale_caption_frame(fid: str) -> tuple[k.Node, tuple[str, list[str]], list[k.Bar]]:
    """states/stale-caption: time 1m, Candle, strip; the feed chip Stale; the snapshot's rows `stale`, the forming row
    `forming` (stale too, in its name); the caption ends "values as of 13:42:05" (§6.2, D04E11:264)."""
    rows, loaded = rows_span(stale_all=True)
    w = k.dock_w("strip")
    cols = k.shown_columns(MODE)
    cap = k.caption_text(rows, MODE, loaded=loaded, feed_stale=True)
    assert cap.endswith("values as of 13:42:05"), cap
    focus = rows[-1]
    focus = k.tag(focus, "stale")  # §6 L226: the forming row while the feed is Stale is stale too (forming shows first)
    rows[-1] = focus
    body = [k.bar_row(b, cols, MODE, i + 1, focused=b is focus) for i, b in enumerate(rows)]
    t = k.table(body, w=w, h=k.table_room(), caption_chars=cap, header=k.header_row(cols, MODE),
                footer=k.footer_row(w - 16))
    fr = k.window(fid, k.panel(MODE, t, w=w, chips=[k.stale_chip()]), rail="strip")
    blk = k.frame_block(
        fid, state=f"{fid.split(' · ')[0]} (§6.2 L{k.L('### 6.2 Stale')}-{k.L('`stale` sits')}: `stale` in the state "
                   "cell of the snapshot's rows, the "
                   f"caption keeps E11-D04's clause \"values as of 13:42:05\", D04E11:264; status-row chip "
                   f"\"Stale 7s · last 13:42:05\", D04E11:59)",
        mode=MODE, cols=cols, chart="Candle",
        row_header_form=f"{k.row_header(focus, MODE)} — name: {full_name(focus)}",
        keyboard="Alt+T opened the table in place; focus on the cursor bar's row, the forming row 13:42 (D04E11 D2); "
                 "↑ / ↓ move the row (origin table). The focused row carries the 2 px color.focus.ring",
        announcement="Data table, row k of N (D04E11 D2); the caption is not a live region (the status chip carries "
                     "the feed state, D04E11:264)",
        tokens=k.frame_tokens(fr),
        extra=[f"Rows 13:24-13:41 came in a bars snapshot whose meta.stale is true (§6 L{k.L('| `stale')}): `stale`, "
               "values "
               f"color.text.secondary; 13:33 shows `stale` before `no range` (precedence, §6 L{k.L('One lowercase')}) "
               "and its name "
               f"adds both: {full_name(next(b for b in rows if k.hhmm(b.t) == '13:33')).split(' UTC, ')[1]}",
               "Forming row 13:42: `forming` first (precedence); stale while the feed is Stale (§6 "
               f"L{k.L('| `stale')}), in its name",
               f"Caption ends: values as of {k.LAST_GOOD} (§6.2 L{k.L('`stale` sits')}; D04E11:264)",
               f"Name add for stale: {name_adds('stale')} (§6 L{WORD_LINE['stale']})"])
    return fr, blk, rows


SPEC_GAPS = [
    f"§6 L{k.L('| `POC`          |')}: POC is \"the visible range's POC bar\" (one bar), yet the board shows both "
    "`POC` (13:25) and `Est.·POC` "
    "(13:29) so each form appears (build notes §4); in a live table only one row of a visible range carries POC",
    f"§6 L{k.L('| `width')}: `width capped` is drawn on 13:31 as a tagged specimen; its computed N is "
    f"{width_n(k.series(MODE)[k.at(MODE, '13:31')])} (the name shows it, ruling P-3), below the cap (14 r rounds above "
    "48), which is the chart's equi-volume rule (D06:311), not recomputed by the table",
    f"§6 L{k.L('| `stale')} / §6.2: the specimen `stale` on all-words (13:37) is one row of a stale snapshot; "
    "stale-caption shows the "
    "real case, every row of that snapshot `stale`",
    "§6 accessible-name join: the spec gives each word's addition, not the separator; the annotation joins the row "
    "name and the additions with \", \" (E11-D04's row name form)",
]
