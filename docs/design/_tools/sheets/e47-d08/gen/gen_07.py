"""Board 07 `E47-D08 / 07 pause-controls` (dark): §8's three keyboard pauses, each frame the paused state with the
control focused (CMP-039 ring, E47-D04 §7.1 geometry) and its announcement once, politely: replay (`Space`, W-6),
the tape (`P`, W-8) and follow-live (the `auto` toggle, W-4; `End` resumes, W-10). The feed keeps running in all three."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FOCUS_SYMBOL, chart_body, fmt, k, nb, seeded  # noqa: E402

NN = 7
E22 = k._git_show(k.BASE_SHA, "docs/design/E22/E22-D04.md")
E22_LN = k.find_line("prints buffered", E22)
CHIP_TPL = re.search(r'"(Paused — \d+ prints buffered)"', E22[E22_LN - 1]).group(1)
E26 = k._git_show(k.BASE_SHA, "docs/design/E26/E26-D02.md")
E26_LN = k.find_line('"Playing at 4×"', E26)
SPEED = re.search(r'"Playing at (\d+×)"', E26[E26_LN - 1]).group(1)
CLOCK = re.search(r"Paused at (\d\d:\d\d:\d\d)", k.w("W-6")).group(1)  # the replay clock W-6 names
ROW = {p["mover"].split(" (")[0]: p for p in k.PAUSE}
PAUSE_AT, NOW = 4000, k.BURST_MS  # the tape: paused at 4 000 ms of the burst, the frame at its end


def callout_lines(mover: str, key: str, words: list[str]) -> list[str]:
    p = ROW[mover]
    return [f"{key} (§8 L{p['line']})", *words, f"Announced: {p['announced']}", f"The feed: {p['feed']}"]


def chart_panel(name: str, w_: int, h: int, *, strip: k.Node | None = None) -> k.Node:
    body, _sc = chart_body(w_, h - k.HEADER_H - (36 if strip else 0), 100)
    inner = k.vbox("chart + strip", [body, strip], None, w=w_, h=h - k.HEADER_H) if strip else body
    return k.panel(name, f"Chart · {FOCUS_SYMBOL}", inner, w_, h)


def frame_replay(fid: str) -> tuple[k.Node, list[str]]:
    ch = chart_panel("CMP-080 panel · chart (replay)", 900, 520)
    k.fallback("markers")
    frame4 = k.box("replay frame · 4 px", [k.box("inner 2 px", [], {"stroke": k.INFO_STRONG, "strokeWidth": k.THICK,
                                                                     "strokeAlign": "inner"}, w=896, h=516, x=2, y=2)],
                   {"stroke": k.INFO_STRONG, "strokeWidth": k.THICK, "strokeAlign": "inner"}, w=900, h=520,
                   note="SCR-030's 4 px replay frame drawn as two 2 px strokes (no 4 px token); a real border")
    chip = k.chip(f"REPLAY {CLOCK}", fill_=k.INFO_SUBTLE, name="replay chip", stroke=k.INFO_STRONG,
                  note="static: 0 ms enter / exit, the clock a 1 Hz text swap (I-26), never announced")
    play = k.button("Play", focused="normal", note="CMP-001 in the transport: Pause / Play swap names, no "
                                                   "aria-pressed (§8); focus stays here (R-6)")
    bar = k.hbox("replay transport", [play, k.button("Step"), k.button(SPEED, name="speed picker"),
                                      k.text("clock", CLOCK, k.NUM, k.TEXT_1),
                                      k.text("status", k.w("W-6"), k.BODY, k.TEXT_2)],
                 {"gap": k.INSET_MD, "padX": k.INSET_MD, "fill": k.RAISED}, w=900, h=48,
                 note="SCR-097 transport; one Tab stop for the pause / play button")
    co = k.callout("replay", callout_lines("Replay auto-play", "Space pauses; Space again plays (W-7 \""
                                           f"{k.w('W-7')}\")", [f"Polite, once: \"{k.w('W-6')}\" (W-6)"]),
                   940, 16, 268)
    content = k.box("workspace", [dict(ch, x=16, y=16), dict(frame4, x=16, y=16), dict(chip, x=32, y=52),
                                  dict(bar, x=16, y=552), co], None, w=k.MAIN_W, h=k.BODY_H)
    return k.window(fid, content, note="§8 replay"), [
        f"§8 L{ROW['Replay auto-play']['line']}: {ROW['Replay auto-play']['control']}",
        f"W-6 \"{k.w('W-6')}\" and W-7 \"{k.w('W-7')}\" verbatim (E26-D02); the speed label {SPEED} from E26-D02 at "
        f"{k.BASE_SHA} L{E26_LN}", "Focus ring: CMP-039 normal (E47-D04 §7.1 at " + k.D04_SHA + ")"]


def tape_rows(n: int = 14) -> list[k.Node]:
    cols = (k.Col("t", "Time", 104, True), k.Col("p", "Price", 104, True), k.Col("q", "Size", 80, True))
    ticks = [t for t in k.BURST if t.t_ms <= PAUSE_AT][-n:][::-1]
    sizes = seeded(71, n, 1, 250)
    rows = []
    for i, (t, q) in enumerate(zip(ticks, sizes), 1):
        s = 38 * 60 + 0 + t.t_ms // 1000  # synthetic session clock: 13:38:00 at t 0
        rows.append(k.table_row(cols, {"t": f"13:{s // 60:02d}:{s % 60:02d}.{t.t_ms % 1000:03d}",
                                       "p": fmt(t.price_ticks), "q": f"{q / 1000:.3f}"}, f"row {i}", i,
                                colors={"p": k.BUY if t.move == "up" else k.SELL if t.move == "down" else k.TEXT_1}))
    return [k.table("CMP-049 grid · tape", None, k.header_row(cols), rows)]


def frame_tape(fid: str) -> tuple[k.Node, list[str]]:
    buffered = sum(1 for t in k.BURST if PAUSE_AT < t.t_ms <= NOW - 1) + 1
    chip_txt = re.sub(r"\d+", str(buffered), CHIP_TPL, count=1)
    pause = k.button("Pause", pressed=True, note='CMP-001; aria-pressed="true", a stable name (E22-D04 :101)')
    # the ring is drawn over the panel, not inside its 28 px header: a 36 px ring in the header's tools was clipped
    # top and bottom (the first render showed only its sides); the header keeps an empty slot of the button's size
    slot = k.box("Pause slot", [], None, w=pause["w"], h=pause["h"])
    ring = k.focus_ring(pause, "normal")
    e = k.extent("normal")
    chip = k.chip(chip_txt, fill_=k.WARN_SUBTLE, name="Paused chip", stroke=k.WARN_STRONG)
    body = k.vbox("tape body", [k.hbox("state", [chip], {"padX": k.INSET_SM}, h=28), *tape_rows()], {"gap": k.STACK_XS})
    tp = k.panel("CMP-080 panel · tape SCR-053", f"Tape · {FOCUS_SYMBOL}", body, 320, 480, tools=[slot])
    tp_x, tp_y = 584, 16
    bx = tp_x + 320 - k.PX[k.INSET_SM] - pause["w"]  # the header's tools sit right, inside its 8 px padding
    by = tp_y + (k.HEADER_H - pause["h"]) // 2
    ch = chart_panel("CMP-080 panel · chart", 560, 480)
    co = k.callout("tape", callout_lines("Tape auto-scroll", "P (focus inside the tape panel; never in a text field)",
                                         [f"Polite, once: \"{k.w('W-8')}\" (W-8); \"{k.w('W-9')}\" on resume (W-9)",
                                          f"The chip counts new prints: {buffered} since the pause at "
                                          f"{nb(PAUSE_AT)} ms (TICKS, {k.BURST_HZ} Hz)"]), 920, 16, 288)
    content = k.box("workspace", [dict(ch, x=16, y=16), dict(tp, x=tp_x, y=tp_y), dict(ring, x=bx - e, y=by - e), co],
                    None, w=k.MAIN_W, h=k.BODY_H)
    return k.window(fid, content, note="§8 tape"), [
        f"§8 L{ROW['Tape auto-scroll']['line']}: {ROW['Tape auto-scroll']['control']}",
        f"Chip words from E22-D04 at {k.BASE_SHA} L{E22_LN} (\"{CHIP_TPL}\") with the derived count {buffered}",
        f"W-8 / W-9 PROPOSED (§15; words E47-D07)"]


def frame_follow(fid: str) -> tuple[k.Node, list[str]]:
    hh, mm = (int(x) for x in CLOCK.split(":")[:2])
    view = f"{hh:02d}:{mm - 2:02d}"  # the view's right edge: two one-minute bars behind live (kit choice)
    w4 = k.fill_slot(k.w("W-4"), "hh:mm", view)
    auto = k.button("auto", pressed=False, focused="normal",
                    note='the follow toggle keeps its name, aria-pressed="false"; W-4 by aria-describedby (D08-C3)')
    strip = k.hbox("time-axis strip", [auto, k.text("W-4 status", w4, k.BODY, k.TEXT_2)],
                   {"gap": k.INSET_MD, "padX": k.INSET_SM, "fill": k.RAISED}, w=900, h=36)
    ch = chart_panel("CMP-080 panel · chart (follow-live off)", 900, 560, strip=strip)
    co = k.callout("follow", callout_lines("Follow-live", "The auto toggle turns follow off; End resumes "
                                           f"(W-10 \"{k.w('W-10')}\")", [f"Visible and polite once: \"{w4}\" (W-4, "
                                                                         "hh:mm filled); never \"Paused\""]),
                   940, 16, 268)
    content = k.box("workspace", [dict(ch, x=16, y=16), co], None, w=k.MAIN_W, h=k.BODY_H)
    return k.window(fid, content, note="§8 follow-live"), [
        f"§8 L{ROW['Follow-live']['line']}: {ROW['Follow-live']['control']}",
        f"W-4 \"{k.w('W-4')}\" filled with {view}: the view two one-minute bars behind the live clock {CLOCK[:5]} "
        "(kit choice; synthetic)", "W-4 replaces W-5: pausing follow-live is a view choice, not a feed pause (§8)"]


def main() -> None:
    fr = k.BOARDS[NN].frames
    built = [frame_replay(fr[0]), frame_tape(fr[1]), frame_follow(fr[2])]
    p, md, pk = k.build(NN, [b[0] for b in built], [(f, b[1]) for f, b in zip(fr, built)], per_row=3, board_lines=[
        "Pause controls are never gated (§12); reaching each needs no pointer; pausing never moves focus (R-6)",
        f"Not drawn: the heatmap's interim (D08-G7) and the preview tile's pause (SCR-117) (§0 L{k.NOT_DRAWN_LINE})"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
