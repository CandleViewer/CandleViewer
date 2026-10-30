"""E12-D07 board 02 `tick-volume-delta` (dark): §0 L55 — the non-time row header (§2.2); tick's `trades`; the volume
and delta variants as frames of one board, delta's `buy` and `sell` among them; `close time` and `duration` as auto
columns. Frames (hand-off §H L97): tick/default, tick/wide-auto, volume/default, delta/default (2 x 2).
Writes build/02-tick-volume-delta.json (validated), 02-tick-volume-delta.md beside the kit, and packs v4/.
Usage: python3 -I -B gen/gen_02.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair2_helpers as h  # noqa: E402

k = h.k
NN = 2


def build() -> tuple[list[dict], dict]:
    f = k.BOARDS[NN].frames  # tick/default, tick/wide-auto, volume/default, delta/default
    frames, blocks = [], []
    specs = [
        (f[0], "tick", "open", "tick/default: §2.2 L113–116 row header; `trades` P (§3.1 L135), the closing quantity "
                               "(§3.2 L152); RightRail open, auto columns hidden (A-1)", []),
        (f[1], "tick", "strip", "tick/wide-auto: `close time`, `duration` join (§3.1 L141–142; 1,168 ≥ 1,004.4, §5 "
                                "L186); caption + “durations as h:mm:ss” (§7.4 L257)", []),
        (f[2], "volume", "strip", "volume/default: volume closes the bar, no second column (§3.2 L153); the sweep is "
                                  "bar 1–8 of 8 (§2.2 L114)", []),
        (f[3], "delta", "strip", "delta/default: `buy` (v + delta) ÷ 2, `sell` (v − delta) ÷ 2, A derived (§3.1 "
                                 "L136–137; §3.2 L155)", []),
    ]
    base = tuple(k.shown_columns("tick"))
    for i, (fid, mode, rail, state, extra) in enumerate(specs):
        fr, blk = h.table_frame(fid, mode, rail=rail, state=state, extra=extra, full=i == 0, base_cols=base,
                                focus_k=3 if mode == "tick" else None,
                                announce=("Data table, row k of N (D04E11:115 D2), on Alt+T" if mode == "tick" else
                                          "none: the frame is a reading state (no step announced)"))
        frames.append(fr)
        blocks.append(blk)
    toks = sorted({t for fr in frames for t in k.frame_tokens(fr)})
    ann = k.annotations(NN, blocks, board_lines=[
        "Tokens (all four frames): " + ", ".join(toks) + "; buy / sell text falls back to color.buy.default / "
        "color.sell.default (A-12)",
        "Frames 2 × 2 (§H L97): 1280 × 800 windows, one panel, table in place (D04E11:115), compact; seeded data "
        "(A-8), sweep 2026-10-20 10:22:11.412"])
    notes = {
        "spec_gaps": [
            "A-1: at 1280 the one panel is 1,168 CSS px and tick's auto set (1,004.4, §5 L186) fits, so tick/default "
            "and tick/wide-auto would be one picture; tick/default opens the RightRail (dock 976) so the auto columns "
            "stay hidden there",
            "A-2: §2.2 L116's example “closed 10:22:14.020 after 0:02.6” cannot hold under its own rule (L114): bars "
            "sharing one open time are consecutive, so bars 1–4 of 5 close at 10:22:11.412 after 0:00.0; the data keeps "
            "the rule and the example string is not drawn",
            "A-8: hand-off §H L92's recorded fixtures cannot build tick / volume / delta bars; seeded synthetic stream, "
            "the instrument's tick size and qty step from the fixture",
            "A-11: the caption's date sits inside the visible-range clause",
            "A-12: color.text.buy / color.text.sell unregistered: signed cells use color.buy.default / "
            "color.sell.default, the sign carries the meaning"],
        "live_checks": [
            "frame tick∕default: the RightRail is 240 px wide (open) and the dock 976; the header has no `close time` "
            "or `duration`",
            "frames tick∕wide-auto, volume∕default, delta∕default: the RightRail is the 48 px strip and the header ends "
            "`state · close time · duration`"],
    }
    return frames, {"ann": ann, "notes": notes}


def main() -> int:
    frames, rest = build()
    p = k.write_sheet(NN, frames, rest["ann"], notes=rest["notes"])
    k.write_md(NN, p, frames_info=[
        "tick/default: tick set, RightRail open, P columns only; bar 3 of 5 focused (spec §2.2 L113–116, §3.1 L135)",
        "tick/wide-auto: + close time, duration (§3.1 L141–142, §5 L186, §7.4 L257); bar 3 of 5 focused",
        "volume/default: volume set + auto columns; bar k of 8 at the sweep (§3.2 L153, §5 L187)",
        "delta/default: delta set + buy, sell, close time, duration (§3.1 L136–137, §3.2 L155, §5 L189)",
        "Walkthrough (hand-off §E L58): a tick row says when it opened and its position (row header), when it "
        "closed and how long it took (row name close clause, §2.2 L116; the wide frame's cells), and its `trades`",
        "Copy: W-10 (spec L332), W-11 (L333), W-12 (L334), W-14 (L336); theme dark; export "
        "docs/design/E12/img/E12-D07-02-tick-volume-delta.png"])
    v4 = k.pack_sheet(p)
    print(p, v4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
