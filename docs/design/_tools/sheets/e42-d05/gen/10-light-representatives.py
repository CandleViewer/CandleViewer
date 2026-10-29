"""E42-D05 board 10 `light-representatives`: HL-20 (= HL-6), RW-15 (= RW-3), WZ-16 (= WZ-5) at 1280 in light.
Light is the same construction as the dark state (build notes: the theme switches at export, deviation (4), OQ-2).
No focus overlay on this board (the plan's keyboard rider is boards 03, 05, 06, 08, 09); the keyboard path is still
given per state in the annotation column, quoted from the screen's Keys paragraph."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 10
LIGHT = "deviation (4) and OQ-2: light draws one representative state per surface; tokens resolve in semantic-light at export"
BLOCKS = {
    "HL-20": {
        "decisions": f"D1 layout (3 tile columns at 1280), D2 contract health words with glyphs, D4 one tile per component, "
        f"D9 stops / still-safe sentences, D10 overall = the worst + incidents link, D11 one voice; {LIGHT}",
        "keyboard": "As HL-6 (L324): Tab incidents link → Re-read → Export → tiles in DOM order (heading link, Runbook, "
        "Retry, history disclosure; no roving grid) → Table view → build line; Alt+T toggles the Table view. "
        "Focus ring visible on the light surface.",
    },
    "RW-15": {
        "decisions": f"D22 restore scope (postgres + config ticked, questdb / parquet labelled targets), D24 six steps, "
        f"D25 impact copy from §8.2 only, D27 stepper, D39 Q1 restore set, D40 Q2 later security changes; {LIGHT}",
        "keyboard": "As RW-3 (L513): focus moves to the step heading on a step change; Tab the step's content in reading "
        "order → Back → Next; Esc on steps 1–3 is Cancel restore (restore.not_restored, polite once).",
    },
    "WZ-16": {
        "decisions": f"D27 stepper, D28 server onboarding state, D29 the 48-hour wait (Add key T2 admin.key_cooldown, "
        f"onboard.opens beside it), D43 Q5, §4.1 T2; [Continue to step 4] enabled (AC-4); {LIGHT}",
        "keyboard": "As WZ-5 (L585): focus moves to the step heading on a step change; Tab the step's fields → Save → "
        "Back → Continue; Add key is reached (aria-disabled) and Enter / Space send nothing (L191); "
        "a stepper link reaches any step.",
    },
}

rows, groups = d.board_parts(NN, BLOCKS)
ann = d.ann_column(NN, groups, [])
r = d.write_board(NN, rows, ann)
print(r.get("valid"), r.get("nodes"), r.get("sections"))
print({k: v for k, v in r.items() if k not in ("valid", "nodes", "sections")})
