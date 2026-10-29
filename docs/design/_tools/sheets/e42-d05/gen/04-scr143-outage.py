"""E42-D05 board 04 `scr143-outage` (dark, ★): HL-11 1280+2560 [14], HL-12 1280 with the HL-15 inset [15],
HL-14 1280+2560 [17], HL-18 1280 [20]. Built from the kit's presets (board_parts); this file only adds the per-state
Decision ids and Keyboard path and focus (E42-D05 §2 D-rows, §5 Keys L324-327, §13 L686)."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 4
TAB = (
    "Tab: incidents link → Re-read → Export → tiles in DOM order (each heading link, then its Runbook link, Retry "
    "and history disclosure; no roving grid) → Table view → build line; Alt+T toggles the Table view (E42-D05 L324)"
)
BLOCKS = {
    "HL-11": {
        "decisions": "D5, D6, D7, D8, D10; D48 (Q10 stale only on an observed failure); D2 (words live from frames)",
        "keyboard": [
            TAB,
            (
                "[Retry] under the overall line sits after Re-read in reading order; focus stays where it "
                "was when the read fails (no refresh steals focus, §13 L686); 'as of' and ages never announced"
            ),
        ],
    },
    "HL-12": {
        "decisions": "D5, D6, D7, D10; HL-15 inset: D7 (guard refusal keeps words live), D10 (overall line)",
        "keyboard": [
            TAB,
            (
                "On a failed first mount focus stays on the page heading; [Retry] is reached after the "
                "overall line; numbers read '— not received', words come from frames"
            ),
        ],
    },
    "HL-14": {
        "decisions": "D6, D7, D11 (one voice: E17's banner), D14 (Export diagnostics T2 §4.1 admin.server_unreachable)",
        "keyboard": [
            TAB,
            (
                "Export diagnostics… is T2: focusable, aria-disabled, its reason read as its description; "
                "Enter/Space send nothing (§4.1 L191); [Retry] enabled; shell, NavRail, strip and links usable"
            ),
        ],
    },
    "HL-18": {
        "decisions": "D14 (rung 1: From/To UTC, last 24 h, at most 24 h, CG-29; written on the server, never "
        "uploaded), D37 (registry marker health.diagnostics_exported)",
        "keyboard": [
            (
                "Dialog (§13 L686): focus opens on Cancel; Tab through From → To in reading order → Cancel → the "
                "confirm; Esc cancels and returns focus to Export diagnostics…"
            ),
            "The confirm waits on form validity (From/To ≤ 24 h), native disabled allowed — not T2",
        ],
    },
}

rows, groups = d.board_parts(NN, BLOCKS)
ann = d.ann_column(NN, groups, [d.focus_overlay("SCR-143", dialogs=True)])
r = d.write_board(NN, rows, ann)
print(r.get("valid"), r.get("nodes"), r.get("sections"))
print({k: v for k, v in r.items() if k not in ("valid", "nodes", "sections")})
