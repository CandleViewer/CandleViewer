"""E42-D05 board 03 scr143-144-populated (dark, ★): HL-2 1280 (client-tile inset) + 2560, HL-5 1280 (gate inset),
HL-6 1280 (HL-7 inset), IL-2 1280 + 2560. Offline generator; writes 03-scr143-144-populated.json/.md only.
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 3
KB143 = (
    "Tab: incidents link → Re-read → Export → tiles in DOM order (heading link, Runbook link, Retry, history "
    "disclosure; no roving grid) → Table view → build line; Alt+T toggles Table view; focus ring "
    "color.border.focus on each stop (E42-D05 L324-327)"
)
KB144 = (
    "Segmented control = radio group (arrows move and select) → filter row (each T2 control by Tab; Enter "
    "re-shows the reason) → table, APG grid (one tab stop; ↑ ↓ rows, ← → cells, Home/End, PgUp/PgDn; "
    "Space/Enter expands; Enter on Acknowledge acts once) → Load more; focus stays on the cell that then holds "
    "the outcome line (E42-D05 L375-378)"
)
BLOCKS = {
    "HL-2": {
        "decisions": "D1, D2, D3, D4 (client tile; inset 'No chart open in this window'), D5, D8, D10, D13",
        "keyboard": KB143,
    },
    "HL-5": {
        "decisions": "D2, D6, D9 (stops, health.safe; inset: safe withheld on an oms fault or missing gate "
        "read), D10, D11 (CMP-092 banner, one voice)",
        "keyboard": KB143 + "; down announced assertive once, recovery polite once",
    },
    "HL-6": {
        "decisions": "D2 (words + glyphs, never colour alone), D3, D4, D9, D10 (overall = the worst); HL-7 "
        "inset: not_deployed as 'not built yet', neutral tone, ranks healthy",
        "keyboard": KB143,
    },
    "IL-2": {
        "decisions": "D15 (six columns, segmented control, no dimming), D16 (filters/export T2 under one "
        "notice), D17, D18 (outcome line in place of Acknowledge, ruling Q13)",
        "keyboard": KB144,
    },
}

# Review fixes (board-local; the kit is untouched):
# 1. IL-2: §1 L86-88 names no severity for the break_glass and recorder rows, but §6 scopes SCR-144 to "error and
#    critical" only (incident.scope, §15 L709), so the vocabulary is closed: DJ — break_glass reads critical (a
#    safety row, D03 OV-10), recorder reads error; each drawn as word + octagon like the other two rows (§6 L343).
# 2. IL-2: the break_glass row's Subsystem is its row identity (D03's break-glass row): drawn as text, not a bar.
# 3. HL-2 / HL-6: the degraded tile shows the plain state word "degraded" + triangle like the other tiles (HL-3 row
#    L305: triangle + "degraded", `detail`), the worked-example detail on its own line beneath; tile.degraded's two
#    parts ("Degraded — {detail}") are split across the two lines.
SEV_DJ = {"break_glass": "critical", "recorder": "error"}
_incident_row = d.incident_row


def incident_row_fixed(px, inc, cols, **kw):
    cells = _incident_row(px, inc, cols, **kw)
    sev = inc.severity or SEV_DJ.get(inc.component, "")
    if sev and not inc.severity:
        d.note(
            "fallbacks",
            f"IL-2 {inc.component}: severity {sev!r} (DJ: §6 scope is error and critical only; §1 "
            "names none for this row)",
        )
        cells["severity"] = dict(
            d.severity_cell(sev),
            note=f"severity {sev} (DJ: §1 L86-88 names none; SCR-144 lists "
            "error and critical only, incident.scope)",
        )
    if inc.component == "break_glass":
        cells["subsystem"] = d.text("value", inc.component, d.NUM_SM, d.TEXT_1)
    return cells


d.incident_row = incident_row_fixed
_health_tile = d.health_tile


def health_tile_fixed(px, c, **kw):
    t = _health_tile(px, c, **kw)
    if c.state == "degraded" and c.detail:
        kids = []
        for n in t["kids"]:
            if n.get("name") == "status":
                d.note("copy_keys", "tile.degraded")
                kids.append(
                    d.vbox(
                        "status",
                        [
                            d.health_status("degraded"),
                            dict(
                                d.text(
                                    "detail", c.detail, d.BODY, d.TEXT_1, w=n["kids"][1].get("w")
                                ),
                                note="tile.degraded 'Degraded — {detail}': the word on the status "
                                "line, the detail beneath (HL-3 row L305)",
                            ),
                        ],
                        {"gap": d.INSET_XS},
                    )
                )
            else:
                kids.append(n)
        t = dict(t, kids=kids)
    return t


d.health_tile = health_tile_fixed

rows, groups = d.board_parts(NN, BLOCKS)
hl7 = d.state("HL-7")
extra = [
    d.ann_block(
        "Inset · HL-7 (on HL-6) — not built",
        [
            (
                f"State row E42-D05 L309: {hl7}"
                if isinstance(hl7, str)
                else "State row E42-D05 L309 (HL-7, inset on old board 10)"
            ),
            (
                "Trigger: a not_deployed component · ring + 'not built yet', neutral tone (color.neutral.default), "
                "no number; ranks healthy (D2, D10)"
            ),
        ],
        name="inset · HL-7",
    ),
    *[d.focus_overlay(s) for s in d.BOARDS[NN].keys],
]
ann = d.ann_column(NN, groups, extra)
r = d.write_board(NN, rows, ann)
print(
    r.get("valid"),
    r.get("nodes"),
    r.get("sections"),
    {k_: v for k_, v in r.items() if k_ not in ("notes",)},
)
MD = d.Path(r["json"]).with_suffix(".md")
MD.write_text(
    MD.read_text(encoding="utf-8").rstrip("\n") + "\n\n## Review fixes (r2, board-local)\n\n"
    "- IL-2 1280 + 2560: the break_glass and recorder rows draw Severity as word + octagon (DJ: §1 L86-88 "
    "names none; SCR-144 lists error and critical only, `incident.scope` §15 L709): break_glass critical "
    "(a safety row, D03 OV-10), recorder error.\n"
    "- IL-2: the break_glass row's Subsystem is drawn as text `break_glass` (its row identity).\n"
    '- HL-6 (and every degraded tile on this board): triangle + the plain word "degraded" on the status '
    "line, the worked-example detail on its own line beneath (HL-3 row L305); `tile.degraded` "
    '"Degraded — {detail}" split across the two lines. Other boards\' degraded tiles still draw the '
    "joined string (kit unchanged).\n",
    encoding="utf-8",
)
