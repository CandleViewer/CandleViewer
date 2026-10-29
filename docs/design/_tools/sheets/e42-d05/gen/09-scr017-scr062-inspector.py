"""E42-D05 board 09: scr017-scr062-inspector (IW-3 + IW-9 inset, IW-4, GV-1 / SI-1 + rowless inset, SI-6)."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 9
BLOCKS = {
    "IW-3": {
        "decisions": "D33, D46 (SCR-017 in scope; TOTP is SCR-003 with E09-D04's frames), D38 (copy by key)",
        "roles": "the invitee on SCR-017 (no session until done)",
        "keyboard": "Wizard keys (§13): focus lands on the step heading (D27); SCR-003's own field order (E09-D04); "
        "the recovery codes are shown once; no refresh steals focus; no new binding (D02 D18)",
    },
    "IW-4": {
        "decisions": "D33, D46; D38 (`14:439-444` and D09 by reference)",
        "roles": "a manager on first sign-in",
        "keyboard": "Focus on the orientation card heading on first sign-in; Tab walks the card's links in reading "
        "order; no new binding (D02 D18)",
    },
    "GV-1": {
        "decisions": "D34, D44 (governance layer only, labelled targets, CG-25), D37 (registry names only)",
        "keyboard": "CMP-049 table, Tab walks the buttons in row order; Move up / Move down once per press "
        "(event.repeat ignored); Rename: Enter saves, Esc cancels, focus back on [Rename] (E42-D05 L623)",
    },
    "SI-1": {
        "decisions": "D35, D45 (E42-S08 inspector, records only), D02 D4 (never 0 for a missing count)",
        "keyboard": "Machine table is an APG grid, Enter opens a machine; 'Latched only' toggle (aria-pressed); "
        "a latch while open: assertive once, a clear: polite once",
    },
    "SI-6": {
        "decisions": "D50 (rung 4: a fresh code every time, titled with the machine key and prior chain-trip "
        "count), D35, D37 (marker without a code, CG-26)",
        "keyboard": "Dialog focuses Cancel; Esc cancels; focus returns to [Acknowledge latch…] (§13); the title "
        "names its machine (E42J:907): {machine_key} is drawn as a placeholder bar (§1's worked example "
        "gives no machine id); the live step fills the latched B1 order machine's key",
    },
}

_kit_build_frame = d.build_frame


def _build_frame(f: d.F) -> d.Node:
    """SI-1's rowless inset drawn here (the kit's preset has no octagon in it): the danger octagon (size.icon) before
    machine.rowless, as the in-frame 'rowless' line and E42-D05 L652 ('machine.rowless with the octagon').
    """
    if f.sid != "SI-1" or "rowless" not in f.insets:
        return _kit_build_frame(f)
    line = d.hbox(
        "rowless",
        [
            d.glyph("octagon", d.DANGER_STRONG),
            d.words("machine.rowless", d.BODY, d.TEXT_1, w=388, kind="position_protection", n=1),
        ],
        {"gap": d.INSET_XS, "align": "start"},
    )
    fr = d.inspector(
        f.px,
        f.sid,
        rowless=True,
        insets=[d.inset(f.px, "SI-1", "a latched kind with no rows (B8)", [line], w=460)],
    )
    return d.at(fr, f)


d.build_frame = _build_frame  # in-process only; the kit file is untouched
rows, groups = d.board_parts(NN, BLOCKS)
extra = [d.focus_overlay(s, dialogs=True, stepper=(s == "wizard")) for s in d.BOARDS[NN].keys]
ann = d.ann_column(NN, groups, extra)
r = d.write_board(NN, rows, ann)
print(r["valid"], r["nodes"], r["sections"], r["largest"], r.get("pack"))
print([m["name"] for m in r["meta"]])
