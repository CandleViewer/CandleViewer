"""Board 03 `E12-D07 / 03 range-renko`: range/default, renko/default, renko/seam (all dark, strip rail)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair3_helpers import HL, L, fit_frame, is_sep, k  # noqa: E402

NN = 3
FIDS = k.BOARDS[NN].frames  # ("range/default · dark", "renko/default · dark", "renko/seam · dark")
KEYS = ("Alt+T opens the table in place, focus on the cursor bar's row (D04E11 D2); ↑ / ↓ move it, origin table "
        "(§9.1 L{s91}); 2 px color.focus.ring, aria-current")


def sweep_frame(fid: str, mode: str, before: int, focus_k: int, closing: str) -> tuple[dict, tuple[str, list[str]]]:
    s = k.series(mode)
    i0 = k.at(mode, "10:22:11.412") - before
    r = fit_frame(fid, mode, s, start=i0, loaded=len(s),
                  focus=lambda b: not is_sep(b) and b.t == k.SWEEP_AT and b.k == focus_k)
    f = r["focus"]
    sweep = [b for b in r["bars"] if b.t == k.SWEEP_AT]
    col = "range" if mode == "range" else "brick"
    cl = k.COLUMNS[col].line
    extra = [
        f"Rows: {len(r['bars'])} {mode} bars of generation 2, {k.row_header(r['bars'][0], mode)} to "
        f"{k.row_header(r['bars'][-1], mode)}; the buy sweep at 10:22:11.412 builds {len(sweep)} bars that share one "
        f"open time: bar 1 … {len(sweep)} of {len(sweep)} (§2.2 L{L('**Position.**')})",
        (f"`range` = (h − l) ÷ tick size, whole ticks (§3.1 L{cl}; §3.2 L{L('| range  | high − low in ticks')}): every "
         f"closed row reads 40 or more, the number the closing rule W-13 names; never a fill alone (hand-off "
         f"L{HL('Board 03: a range row')})") if mode == "range" else
        (f"`brick` = up when c > o, else down (§3.1 L{cl}; §3.2 L{L('| renko  | none: a brick')}): a word, never a "
         f"fill alone (hand-off L{HL('Board 03: a range row')}); high and low stay cells though renko draws no wick "
         f"(§3.1 L{k.COLUMNS['high'].line})"),
        f"Width: P + A {k.set_width(mode, 'PA')} CSS px (§5 L{L(f'WIDTH:{mode}.auto')}) fits the {k.dock_w()} px "
        f"panel; caption adds \"durations as h:mm:ss\" (§7.4 L{L('### 7.4')})",
    ]
    blk = k.frame_block(
        fid, state=f"{fid.split(' · ')[0]} (§2.2 non-time row header; §3.1 {mode} set P + A; {closing})",
        mode=mode, cols=r["cols"], row_header_form=f"{k.row_header(f, mode)} — name: {k.row_name(f, mode)}",
        keyboard=KEYS.format(s91=L("### 9.1 Sync")),
        announcement="Data table, row k of N (D04E11 D2) on arrival; ↑ / ↓ steps are announced by the grid",
        copy_keys=("W-10", "W-13" if mode == "range" else "W-15"), tokens=(), extra=extra)
    return r["frame"], blk


def seam_frame(fid: str) -> tuple[dict, tuple[str, list[str]]]:
    mode = "renko"
    s = k.series(mode)
    j = next(i for i, b in enumerate(s) if b.gen == 3)
    seq = s[:j] + [("sep", "seam", {})] + s[j:]
    r = fit_frame(fid, mode, seq, start=j - 11, loaded=len(s), rows_all=s, focus=lambda x: is_sep(x))
    g2 = [b for b in r["bars"] if b.gen == 2]
    g3 = [b for b in r["bars"] if b.gen == 3]
    seam_txt = k.COPY["W-1"][0]
    extra = [
        f"Rows: {len(g2)} generation-2 bricks to {k.row_header(g2[-1], mode)}, the seam row, then {len(g3)} "
        f"generation-3 bricks from {k.row_header(g3[0], mode)} (the builder's 11:30 cold start; the brick open then "
        f"is lost) (§7.1 L{L('| seam ')})",
        f"Seam row: §7.2's band row (L{L('### 7.2 The band-row form')}), no action; ↑ / ↓ stop on it; counted in "
        f"aria-rowcount; never selected or sorted",
        f"\"bar k of n\" restarts after the seam and never counts across it (§2.2 L{L('**Never across a seam.**')}); "
        f"every brick here is alone at its open time, so each reads bar 1 of 1 in its own generation",
    ]
    blk = k.frame_block(
        fid, state=f"renko/seam (§7.1 seam row between generations 2 and 3; §2.2 count restarts)", mode=mode,
        cols=r["cols"], row_header_form=f"{k.row_header(g3[0], mode)} (first after the seam) — name: "
                                       f"{k.row_name(g3[0], mode)}",
        keyboard=KEYS.format(s91=L("### 9.1 Sync")) + "; here ↓ from the last generation-2 brick stopped on the "
                 f"seam row, which holds focus (§7.2 L{L('### 7.2 The band-row form')})",
        announcement=f"none on arrival (separator rows are not announced when they arrive, §7.2); on reaching it the "
                     f"screen reader reads its accessible name \"{seam_txt}\"",
        copy_keys=("W-1", "W-10", "W-15"), tokens=(), extra=extra)
    return r["frame"], blk


def build() -> None:
    frames, blocks = [], []
    toks: set[str] = set()
    for fn in (lambda: sweep_frame(FIDS[0], "range", 7, 2, "W-13 closing rule"),
               lambda: sweep_frame(FIDS[1], "renko", 9, 2, "W-15 brick size"),
               lambda: seam_frame(FIDS[2])):
        fr, blk = fn()
        frames.append(fr)
        toks |= set(k.frame_tokens(fr))
        blocks.append(blk)
    b = k.BOARDS[NN]
    ann = k.annotations(NN, blocks, board_lines=[
        f"Owner walkthrough item (hand-off L{HL('Board 03: a range row')}): a range row's ticks and a renko row's "
        "direction are words or numbers, never a fill alone",
        "Tokens (every frame binds from this set): " + ", ".join(sorted(toks))])  # live-check fold: the old data line is superseded by data-line
    k.live("frame 1: read back every closed row's `range` cell as a whole number of ticks >= 40 and the 10:22:11.412 "
           "rows' headers as bar 1 of 3, bar 2 of 3, bar 3 of 3")
    k.live("frame 2: read back the `brick` cells as the words up / down (no colour-only cue) and the high / low cells "
           "present on every row")
    k.live("frame 3: read back the seam row's text exactly \"Series restarted 09:15 UTC\", its 2 px color.focus.ring "
           "stroke (inner), its fill color.surface.hover, and its width equal to the header row's")
    k.live("each frame: read back the focused row's ring as 2 px color.focus.ring and exactly one focused row per frame")
    notes = {
        "spec_gaps": [
            "A-3: the seam with no recording gap is the data's 11:30 builder cold start; its row keeps W-1 verbatim, "
            "so its \"09:15\" is a placeholder time (spec §13 gives one seam string)",
            "A-8: the recorded fixtures cannot build range or renko bars (1m klines, sparse prints); the rows come "
            "from a seeded synthetic stream; only tick size and qty step come from the fixture",
            "hand-off §H gives range/default and renko/default no focus or announcement; the frames focus the cursor "
            "bar's row as E11-D04 D2 opens the table, and announce \"Data table, row k of N\""],
    }
    path = k.write_sheet(NN, frames, ann, notes=notes)
    k.write_md(NN, path, frames_info=[
        f"sources: spec §0 L{b.line}; §2.2 L{L('### 2.2 Non-time bars')}; §3.1 range L{k.COLUMNS['range'].line}, brick "
        f"L{k.COLUMNS['brick'].line}; §3.2 L{L('### 3.2')}; §5 L{L('## 5. Widths')}; §7.1 seam L{L('| seam ')}; §7.2 "
        f"L{L('### 7.2 The band-row form')}; §7.4 L{L('### 7.4')}; §13 W-1 L{k.COPY['W-1'][1]}, W-10 "
        f"L{k.COPY['W-10'][1]}, W-13 L{k.COPY['W-13'][1]}, W-15 L{k.COPY['W-15'][1]}; hand-off §H "
        f"L{HL('| 03    |')}",
        f"theme dark; export {b.export}"])
    packed = k.pack_sheet(path)
    print(path, packed)


if __name__ == "__main__":
    build()
