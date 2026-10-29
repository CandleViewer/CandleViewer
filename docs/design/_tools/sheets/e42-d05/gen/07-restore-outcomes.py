"""E42-D05 board 07 restore-outcomes: RW-8 (1280 + 2560, outcome-unknown inset), RW-10, RW-12, RW-14 x2."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 7
KB_STEPS = (
    "On a step change focus moves to the step heading (D27); Tab: the step's content in reading order "
    "-> Back -> Next or the confirm; the confirm ignores event.repeat (§9 Keys, L513-516)"
)
BLOCKS = {
    "RW-8": {
        "decisions": "D23, D24, D26, D36, D37, D38; §4.1 'not T2: a server refusal after a press'",
        "keyboard": "Focus stays on the refused confirm; the refusal is announced assertive once; inputs kept; "
        "Tab: the refusal line -> [Try again] (same body, same Idempotency-Key) -> Back; inset: "
        "[Send again…] opens the fresh-code dialog (RW-7), Cancel focused; Esc on step 3 is "
        "'Cancel restore' (restore.not_restored, polite once)",
    },
    "RW-10": {
        "decisions": "D26, D36 (D04 X1-X12)",
        "keyboard": "Esc inert on steps 4-6; restore.lost read once, then the row read; after the switch-over "
        "ends the session focus lands on sign-in; next sign-in SCR-146 focuses its heading with "
        "restore.after_signin; CMP-023 aria-live off",
    },
    "RW-12": {
        "decisions": "D24, D25, D26, D27, D38",
        "keyboard": "On a step change focus moves to the step heading (D27); step 6 heading focused; Tab: "
        "Orders link (restore.summary.review) -> the trading target (CG-11) -> Close ('Close' leaves "
        "the job running, §8.1 L451); Esc inert on step 6",
    },
}
RW14_KB = (
    KB_STEPS
    + "; at 200 % the step heading 'Step 2 of 6: What a restore does' and its disclosure come first "
    "(Enter or Space opens it: the six steps, each with its status word), the body scrolls, Back and Next "
    "stay one sticky row; focus never hides under the sticky row"
)
RW14_COPY = (
    "restore.impact.bybit, restore.impact.rewind, restore.impact.config, restore.impact.trading"
)
for tag in ("200 % zoom", "200 % text"):  # board_parts keys RW-14 by "<sid> · <frame tag>"
    BLOCKS[f"RW-14 · {tag}"] = {
        "decisions": f"D1, D24, D27; §4.2 ({tag}: the one 200 % proof)",
        "keyboard": RW14_KB,
        "Insets (generator-drawn)": f"RW-14 · {tag} · the collapsed stepper's disclosure, shown open: the six steps "
        "and their status words (Done, Current, Not started; §4.2)",
    }
BLOCKS["RW-14 · 200 % text"][
    "copy"
] = RW14_COPY  # the kit dedups recorded keys: the 2nd group would get none
BLOCKS["RW-10"]["Insets (generator-drawn)"] = (
    "RW-10 · step 4 before the switch-over ends the session: the body "
    "reads restore.lost (CMP-023 aria-live off); the frame is the next "
    "sign-in's SCR-146 (D26)"
)

_orig_preset = d._restore_preset


def _preset(px, sid, insets, tag=""):
    """The kit's preset plus two generator-drawn insets (the kit has neither; kept here, not in the kit)."""
    fr = _orig_preset(px, sid, insets, tag)
    if sid == "RW-10":
        card = d.inset(
            px,
            "RW-10",
            "step 4 'Restoring' before sign-out: restore.lost",
            [d.progress(None, 420), d.words("restore.lost", d.BODY, d.TEXT_1, w=420)],
            w=460,
            corner="tr",
        )
        return dict(fr, kids=list(fr["kids"]) + [card])
    if sid == "RW-14":
        rows_ = [
            d.hbox(
                f"step {i}",
                [
                    d.text("step", f"{i} {nm}", d.BODY, d.TEXT_1, w=220),
                    d.text("status", d.step_word(st, **fl), d.CAPTION, d.TEXT_2, w=120),
                ],
                {"gap": d.INSET_XS},
            )
            for i, (nm, (st, fl)) in enumerate(zip(d.RESTORE_STEPS, d.restore_statuses(2)), 1)
        ]
        card = d.inset(
            px,
            "RW-14",
            "the disclosure open: every step and its status word",
            rows_,
            w=400,
            corner="tr",
        )
        return dict(fr, kids=list(fr["kids"]) + [card])
    return fr


d._restore_preset = _preset

rows, groups = d.board_parts(NN, BLOCKS)
# The kit dedups recorded tokens, so the second RW-14 group (the same drawing at 200 % text) records none: give it the
# first group's computed Tokens block (same nodes, same tokens), placed where ann_group puts it (before Events).
_g14 = [g for g in groups if g["name"] == "group · RW-14"]
_tok = next(c for c in _g14[0]["kids"] if c["name"] == "block · tokens")
_kids = _g14[1]["kids"]
assert not any(c["name"] == "block · tokens" for c in _kids)
_kids.insert(next(i for i, c in enumerate(_kids) if c["name"] == "block · events"), _tok)
ann = d.ann_column(NN, groups, [])
r = d.write_board(NN, rows, ann)
print(r.get("valid"), r.get("nodes"), r.get("sections"))
print({k: v for k, v in r.items() if k not in ("valid", "nodes", "sections")})
