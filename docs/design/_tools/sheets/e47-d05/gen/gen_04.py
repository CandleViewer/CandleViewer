"""Board 04 `E47-D05 / 04 system-states` (dark): §5 — following-system, os-changed-while-open with its status line,
forced-colours with the T2 contrast row (§5.4's T2 paragraph). Each frame a 1280 x 800 window at the page top."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, view_window  # noqa: E402

NN = 4
TOP = ("Motion", "Contrast and focus")


def states() -> list[k.PS]:
    w15 = k.fill(k._quoted(k.COPY["W-15"].s)[0], a="increased contrast", b="off")
    k.NOTES.add("copy_keys", f"W-15 (§15 L{k.COPY['W-15'].line}, {k.COPY['W-15'].status}): {w15}")
    return [k.PS(os_reduce=True, sections=TOP),
            k.PS(values=(("reduced_motion", "on"),), status=w15, w16=("reduced_motion",), sections=TOP),
            k.PS(forced=True, focus="increased_contrast", sections=TOP)]


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    pss = states()
    frames = [view_window(fid, ps, note=f"{fid}: the page top (header, Motion, Contrast and focus)")
              for fid, ps in zip(b.frames, pss)]
    s52, s53, s54 = k.L("### 5.2 Following the system"), k.L("### 5.3 The OS changes"), k.L("### 5.4 Forced colours")
    st = k.STATES
    blocks = [
        (b.frames[0], [
            f"§10 L{st['SCR-117/following-system']['line']}: {st['SCR-117/following-system']['shows']}",
            f"§5.2 L{s52}: the OS reports reduce, the row on \"{k.TRI_OPTIONS[0]}\" reads "
            f"\"{k.effective(pss[0], 'reduced_motion')[1]}\" (W-12); the override is the two other radios, no extra "
            "control (T AC2)",
            "The motion tile shows still Before / After frames (R-6): the effective motion is reduced",
            "Keyboard: the RadioGroup is one Tab stop; arrows move and check (`15`:108); the change is spoken once by "
            "the control's own state (R-5)"]),
        (b.frames[1], [
            f"§10 L{st['SCR-117/os-changed-while-open']['line']}: {st['SCR-117/os-changed-while-open']['shows']}",
            f"§5.3 L{s53}: the OS turned reduce motion and increase contrast off while the screen is open. The contrast "
            f"row follows the system: its Effective line updates in place to \"{k.effective(pss[1], 'increased_contrast')[1]}"
            f"\" and the status region (ASS:74) is replaced with \"{pss[1].status}\" (W-15), spoken once, politely",
            f"The motion row holds an explicit On: it stays (\"{k.effective(pss[1], 'reduced_motion')[1]}\", W-13) and "
            f"shows W-16 \"{k.w('W-16')}\" — visible text only, never in the status region (R-4)",
            "A second flip inside the polite cadence replaces the pending text, latest wins (`05`:151; PROPOSED)",
            "The explicit On is a modified row (§10): \"Changed\" and its \"Reset\" button (W-24)"]),
        (b.frames[2], [
            f"§10 L{st['SCR-117/forced-colours']['line']}: {st['SCR-117/forced-colours']['shows']}",
            f"§5.4 L{s54}: forced-colors: active forces contrast on (D03:480): the RadioGroup is T2, reason "
            f"\"{k.w('W-17')}\" (W-17, PROPOSED key a11y.forced_colors, D05-A7), Effective \"{k.w('W-26')}\" (W-26)",
            "T2 anatomy (E09-D09 §2.2): the lock glyph (CMP-019, name \"Not available\") leads the full label, both in "
            "color.text.tertiary; the group's fill color.surface.raised with a color.border.default hairline; the "
            "reason under the control in color.text.secondary; never color.text.disabled or opacity.disabled",
            "aria-disabled=\"true\" on every radio, never disabled: the group stays in the Tab order (drawn focused, "
            "CMP-039 normal); Enter / Space change nothing and re-show the reason with one polite announcement; the "
            "arrows move the roving focus without checking (PROPOSED)",
            "The stored choice (Follow my system) stays visible on its radio and returns when forced colours end (R-4); "
            "aria-describedby order: description, Effective line, reason",
            "Drawn in the dark token set: under forced colours the system maps the carriers (§11: the ring a solid "
            "Highlight outline, the lock glyph and tile frame CanvasText, the checked radio Highlight)"]),
    ]
    k.ambiguity(f"Board 04 frame 2: §5.3 shows the in-place update (a following row) and W-16 (an explicit row) but W-16's "
                "words are fixed (\"…asks for off; your choice of On stays\"): drawn as one OS change that turns both "
                "signals off — the contrast row follows (W-15, its line updated), the motion row keeps its explicit On "
                "(W-16); an explicit contrast On would switch the theme to high contrast, so the explicit row is motion")
    k.ambiguity("Effective lines with no OS preference read \"the product default\" (W-14): the kit reads "
                "\"no-preference\" as no OS signal (§5.1's override ?? OS signal ?? default)")
    k.ambiguity("T2 label colour (design-read minor): §5.4 and E09-D09 §2.2 put the T2 label and its lock in "
                "color.text.tertiary; §11's \"labels color.text.primary\" is read as the enabled rows' rule — drawn "
                "tertiary on the forced-colours contrast row only")
    p, md, pk = k.build(NN, frames, blocks, per_row=3, board_lines=[
        f"Not drawn — the text is binding (§0 L{k.NOT_DRAWN_LINE}): the view-as T2 notice (§5.4; every write T2 with "
        "rbac.view_as, one CMP-065 notice the gated controls point at)"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
