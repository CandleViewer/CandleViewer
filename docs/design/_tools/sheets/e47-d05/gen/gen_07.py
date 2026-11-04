"""Board 07 `E47-D05 / 07 announcement-tile` (dark): §6.3, §7 — the announcement tile under off / significant /
always, and the low-verbosity sample (T AC5): three lines, one per class event, none for a tick."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, view_window  # noqa: E402

NN = 7
SECS = ("Announcements", "Interaction")
MID = Decimal(10)  # the "significant" frame mid-play: the reveal has reached second 10 of the burst


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    pss = [k.PS(values=(("announce_prices", "off"),), ann_done=True, header=False, sections=SECS),
           k.PS(ann_at=MID, focus="tile:Announcements", header=False, sections=SECS),
           k.PS(values=(("announce_prices", "always"),), ann_done=True, header=False, sections=SECS),
           k.PS(values=(("verbosity", "low"),), ann_done=True, header=False, sections=SECS)]
    frames = [view_window(fid, ps, note=fid) for fid, ps in zip(b.frames, pss)]
    s63, s71, s72, s73 = (k.L("### 6.3 Announcements"), k.L("### 7.1 The controls"), k.CLASSES_LINE,
                          k._S73)
    ev = "; ".join(f"{k.fmt_s(e.t)} {e.cls}" for e in k.WORLD.events)
    n_all = len(k.sample_lines(pss[2]))
    cad = k.KEYS["announce_throttle_s"]["default"]
    low = k.sample_lines(pss[3])
    if len(low) != 3:
        raise SystemExit("board 07: the low-verbosity sample must hold exactly three lines (§7.3)")
    burst = (f"The burst (§7.3 L{s73 + 2}): {k.BURST_S} s of {k.SYMBOL} at {k.PRINTS_PER_S} prints a second "
             f"({k.BURST_S * k.PRINTS_PER_S} prints, seed {k.SEED}); its three events: {ev}")
    blocks = [
        (b.frames[0], [
            f"§7.1 L{s71}: announce_prices Off governs the polite price reads only; the six classes of §7.2 are "
            "assertive, never throttled, and Off does not silence them (`05`:152): the sample keeps its three event "
            "lines", burst,
            f"The tile (§6.3 L{s63}): a static list behind \"Play sample\", a plain ul, never a live region; played to "
            "the end here (lines append at the end, focus never moves)"]),
        (b.frames[1], [
            f"On significant change (the default, \"{k.ANNOUNCE_OPTIONS['significant']}\"): the events listed under the "
            f"choice only (§4's description); the CMP-069 InfoPanel \"{k.INFO_TITLE}\" names the "
            f"{len(k.CLASSES)} classes verbatim from `05`:152 (§7.2 L{s72})",
            f"Mid-play at second {MID}: the button reads \"{k.w('W-27')}\" (W-27) and reveals the rest at once; the "
            f"lines so far: {len([x for x in k.sample_lines(pss[1]) if x[0] <= MID])} of {len(k.sample_lines(pss[1]))}",
            "Under reduced motion the list renders whole, no timed reveal (R-6)"]),
        (b.frames[2], [
            f"Always with normal verbosity: the three events plus one [{k.PRICE_CLASS}] line per field per cadence "
            f"({cad} s, the default from `05`:151, PROPOSED D05-Q1): {n_all} lines over {k.BURST_S} s; each price is "
            "the last print at that second",
            f"The cadence row (announce_throttle_s, \"{k.ROWS['announce_throttle_s']['label']}\") is shown only when "
            "Always is chosen, inserted directly after the group, its value kept when hidden (§7.1)",
            "The words are E47-D07's: the tile shows each class in brackets until they exist (MODEL:91–94)"]),
        (b.frames[3], [
            f"T AC5 (§7.3 L{s73}): verbosity Low — the transcript holds exactly three lines, one per event, each named "
            "by its class, and none for a tick: " + "; ".join(f"{k.fmt_s(t)} {s}" for t, s in low),
            "Low reads only the events listed above, never each trade (§4's verbosity description)"]),
    ]
    k.ambiguity("Board 07: §0's \"off / significant / always\" frames show the same three event lines under Off and "
                "On significant change — §7.1 reads Off and the cadence as governing the polite price reads only, and "
                "the seeded burst has no price line under either; they differ in the radio and the tile's name")
    k.copy_gap(f'"[{k.PRICE_CLASS}]": the price lines\' bracketed label (§7.3 L{s73 + 2}: "one latest-price line per '
               'field per cadence"; the words are E47-D07\'s)')
    p, md, pk = k.build(NN, frames, blocks, per_row=2)
    print(p.name, md.name, pk.name, n_all)


if __name__ == "__main__":
    main()
