"""Board 05 "E08-D09 / 05 clock" (§0 L87): S-09, S-10, S-11, S-12, re-measure busy and cooldown. build(nn) is shared
with board 09 (its light twin, §0 L91). Run: python3 -I -B gen_05.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair2_helpers import (COOLDOWN_LEFT_S, MEASURED_S, OK_DIR, OK_MS, REMEASURED_S, cite, clock_section,  # noqa: E402
                           crop_note, k, offset_sentence, secs, tiles)

# Offsets per frame (ms, direction): each one's size picks its state against §10's 500 / 2 000 ms lines
S09 = (620, "behind")  # > 500, <= 2 000: S-09 (W-38's and SR-8's own 0.62 s sample)
S10 = (2310, "ahead")  # > 2 000: S-10 (S-09 suppressed by precedence)
S11 = (840, "behind")  # <= 2 000, a 10002 refusal seen: S-11 (S-09 suppressed by precedence)


def _l(needle: str, start: int = 1) -> int:
    return k.L(needle, start)


def build(nn: int) -> tuple[list, dict]:
    theme = k.BOARDS[nn].theme
    fids = [f for f, _s in k.frames_of(nn)]
    crop_note()
    thr = _l("**Thresholds as shipped:**")
    fields = _l("- **Fields (T:24):**")
    rem = _l("- **Re-measure (AC3):**")
    never0 = _l("- **Never 0")
    prec = _l("- **Precedence on one row:**")
    t10 = {s: _l(n, 340) for s, n in (("ok", "| ok (≤ 500 ms)"), ("S-09", "| S-09 warning (> 500 ms)"),
                                      ("S-10", "| S-10 alarm (> 2 000 ms)"), ("S-11", "| S-11 `10002` seen"),
                                      ("S-12", "| S-12 not measured yet"))}
    kb = f"Tab reaches Re-measure now in the clock section; Enter / Space presses it (SCR-147-KB-7, §17.3 L" \
         f"{_l('| SCR-147-KB-7')}; Tab order §17.3 L{_l('**Tab order:**')})"
    w37, w22, w27 = k.w("W-37"), k.w("W-22", 1), k.w("W-27")
    frames, blocks = [], []
    common = [f"Clock section = §10 (L{thr}–L{rem}) as a dl of CMP-036 rows (§17.1 L{_l('The clock section is a `dl`')});"
              f" served form, marked Waits on D09-G5, D09-G6 (§0 L{_l('**Penpot** (RULED BQ-25)')}); its S-19 form "
              f"is board 01's S-19 frame",
              f"Last measured {k.at(-MEASURED_S)} = as of {k.AS_OF} − {MEASURED_S} s; age {k.ago(MEASURED_S)} "
              f"(W-39 {cite('W-39')}); under 900 s, so not stale (§10 L{thr})",
              f"Next due: \"{k.w('W-39', 0)}\" ({cite('W-39')}); an exact time only once served (D09-G5, §10 L{fields})"]

    def off_line(sid: str, ms: int, d: str) -> str:
        return (f"Offset {ms} ms {d} → \"{offset_sentence(ms, d)}\" ({cite('W-38')}; size + direction word, no sign, "
                f"§10 L{fields}); {ms} ms vs 500 / 2 000 ms (§10 L{thr}) → {sid}")

    # S-09 clock warning
    ms, d = S09
    frames.append(k.window(fids[0], theme, [tiles("S-09", offset_sentence(ms, d)),
                                            clock_section("S-09", ms=ms, direction=d, lines=[w37])]))
    blocks.append(k.frame_block(fids[0], keyboard=kb, waits=["D09-G5", "D09-G6"], lines=[
        f"§10 L{t10['S-09']}: as ok + the consequences line W-37 ({cite('W-37')}); word {cite('W-21')}",
        off_line("S-09", ms, d), f"SR-8's slot {{0.62}} = this frame's {secs(ms)} s"]))
    # S-10 clock alarm: order entry halted
    ms, d = S10
    frames.append(k.window(fids[1], theme, [tiles("S-10", offset_sentence(ms, d)),
                                            clock_section("S-10", ms=ms, direction=d, lines=[w37, w22])]))
    blocks.append(k.frame_block(fids[1], keyboard=kb, waits=["D09-G5", "D09-G6"], suppressed=["S-09"], lines=[
        f"§10 L{t10['S-10']}: as S-09 + the halt sentence W-22 ({cite('W-22')})", off_line("S-10", ms, d),
        f"Exit (§10 L{rem}): a measurement within 2 000 ms, through the guard's own check; Re-measure can end it",
        ]))
    # S-11 10002 seen
    ms, d = S11
    frames.append(k.window(fids[2], theme, [tiles("S-11", offset_sentence(ms, d)),
                                            clock_section("S-11", ms=ms, direction=d, lines=[w37, w22, w27])]))
    blocks.append(k.frame_block(fids[2], keyboard=kb, waits=["D09-G5", "D09-G6"], suppressed=["S-09"], lines=[
        f"§10 L{t10['S-11']}: as S-10 + W-27 ({cite('W-27')}); the offset ({ms} ms) is under 2 000 ms, so S-10 is "
        f"not active and S-11 shows (precedence §5.2 L{prec}: S-10 > S-11 > S-09)", off_line("S-11", ms, d),
        f"Exit (§10 L{rem}): a successful resync"]))
    # S-12 clock not measured yet
    frames.append(k.window(fids[3], theme, [tiles("S-12", None),
                                            clock_section("S-12", ms=None, measured_s=None,
                                                          lines=[k.w("W-23", 2)])]))
    blocks.append(k.frame_block(fids[3], keyboard=kb, waits=["D09-G5", "D09-G6"], lines=[
        f"§10 L{t10['S-12']}: no number; \"{k.w('W-23', 1)}\" and W-23's second sentence ({cite('W-23')})",
        f"Never 0, never \"In sync\" while unmeasured (§10 L{never0}); no Measurement row (nothing measured)",
        f"Warning tone, not the neutral ring (§5.2 L{_l('- **S-12 uses the warning tone**')})"]))
    # re-measure busy (during the S-10 episode)
    ms, d = S10
    frames.append(k.window(fids[4], theme, [tiles("S-10", offset_sentence(ms, d)),
                                            clock_section("S-10", ms=ms, direction=d, lines=[w37, w22],
                                                          button="busy")]))
    blocks.append(k.frame_block(fids[4], keyboard=kb, waits=["D09-G5", "D09-G6"], lines=[
        f"Re-measure pressed during S-10 (frame 2's values kept): the button is aria-busy with \"{k.w('W-35', 1)}\" "
        f"({cite('W-35')}; §10 L{rem}); focus stays on it", off_line("S-10", ms, d),
        f"Not an audited write: no audit marker (§10 L{rem}; D09-G16)"]))
    # re-measure cooldown (the measurement brought the offset back: In sync)
    frames.append(k.window(fids[5], theme, [tiles(None, None, k.clock_ok_status(OK_MS, OK_DIR)),
                                            clock_section(None, ms=OK_MS, direction=OK_DIR,
                                                          measured_s=REMEASURED_S, button="cooldown")]))
    blocks.append(k.frame_block(fids[5], keyboard=kb + "; inside the cooldown the button stays focusable "
                                "(aria-disabled, T2)", waits=["D09-G5", "D09-G6"], recovery=True, lines=[
        f"The re-measure ran at {k.at(-REMEASURED_S)} (= as of − {REMEASURED_S} s) and measured {OK_MS} ms {OK_DIR}: "
        f"≤ 500 ms → the ok state \"{k.w('W-29', 0)}\" · \"{k.w('W-29', 1, OK_MS, OK_DIR)}\" ({cite('W-29')}; "
        f"§10 L{t10['ok']}); the S-10 halt ended through the guard's check",
        f"Cooldown: T2 (R-9) rendering 2a, lock leading the full label, reason \"{k.w('W-36b', None, COOLDOWN_LEFT_S)}\""
        f" ({cite('W-36b')}; SCR-147-T2-3, §17.5 L{_l('| SCR-147-T2-3')})",
        f"Cooldown length {REMEASURED_S + COOLDOWN_LEFT_S} s is implied by this frame (ran {REMEASURED_S} s ago, "
        f"{COOLDOWN_LEFT_S} s left); the server's cooldown is D09-G6, not given by the spec"]))
    k.deviate(f"re-measure cooldown: {REMEASURED_S + COOLDOWN_LEFT_S} s implied (ran {REMEASURED_S} s before as of, "
              f"W-36b's {COOLDOWN_LEFT_S} s left); the server's cooldown is unspecified (D09-G6)")
    k.deviate("summary strip on board 05: REST budget and Private streams in S-19 (D09-G1), Public market data "
              "'Within budget' with W-52's '3 connections', IP hold 'Within budget' (D09-G13 assumed served): "
              "fixed across the six frames; only the Clock tile varies")
    for i, f in enumerate(frames, 1):
        k.live(f"frame {i} '{f['name']}': read back the Clock section's h2 'Clock' and the Re-measure control "
               f"inside the main column's 672 px view (not clipped)")
    k.live("frames 1-3: the Clock tile's number and the dl's Offset row read the same W-38 sentence")
    k.live("frame 4 (S-12): no figure in the Offset row; the text reads W-23's sentence, never '0' or 'In sync'")
    k.live("frame 6: the T2 button shows the 'locked' icon first, then 'Re-measure now'; the reason sits under it")
    ann = k.annotations(nn, blocks, board_lines=[
        f"One clock: as of {k.AS_OF} (W-03); every time derived from it; thresholds 500 / 2 000 ms, every 300 s, "
        f"stale 900 s (§10 L{thr})", *common])
    return frames, ann


def main(nn: int = 5) -> None:
    frames, ann = build(nn)
    p = k.write_sheet(nn, frames, ann)
    md = k.write_md(nn, p)
    packed = k.pack_sheet(p)
    rc, msg = k.validate(p)
    print(p, md, packed, f"validator exit {rc}: {msg.splitlines()[-1] if msg else ''}", sep="\n")


if __name__ == "__main__":
    main()
