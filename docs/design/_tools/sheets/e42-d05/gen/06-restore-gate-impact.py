"""E42-D05 board 06 restore-gate-impact (dark, ★): RW-1 (+RW-16 inset), RW-3, RW-4 (loading inset), RW-5 (today's
inset), RW-6 (config-only inset). Kit presets only; decisions and keyboard per state from §2 / §8.3 Keys (L513).
"""

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

KEYS, KL = d.keys_text("restore")
KB = f"§8.3 Keys (E42-D05 L{KL}); §13 shared (L{d.SHARED_KEYS_LINE}). "
blocks = {
    "RW-1": {
        "decisions": "D24 (maintenance stated first in step 1; nothing sent before step 3), D27 (stepper, focus to the "
        "step heading), D22 (scope), §4.1 T2 (Next: admin.maintenance_first); RW-16 inset: CG-16, "
        "restore route not mounted (M:90-96) → Restore… T2 admin.restore_not_built",
        "keyboard": KB + "Focus lands on the step-1 heading; Tab: restore.step1.needs_maint → the "
        '"Turn on maintenance mode → Maintenance" link → backup radio group (arrows move and '
        "select; never onto a T2 radio's check) → [Back up now first…] → Back → Next (T2: "
        "aria-disabled, focusable, reason read as its description) → Cancel restore; Esc = Cancel "
        "restore (restore.not_restored, polite once).",
    },
    "RW-3": {
        "decisions": "D25 (impact copy only from §8.2's sources, its order and shown-when rules), D22 / D39 (scope: "
        "postgres + config ticked by default; questdb, parquet labelled target, CG-9), D24, D27; "
        "ruling Q1",
        "keyboard": KB
        + "Focus to the step-2 heading so the impact lines read first; Tab: the impact lines (text) → "
        "scope checkboxes postgres, config, questdb (target), parquet (target) → Back → Next → "
        "Cancel restore; unticking the last store shows restore.scope_one.",
    },
    "RW-4": {
        "decisions": "D24 (ticks before step 3), D25, §4.1 (busy is a read in flight, not T2: aria-busy; then T2 "
        "admin.ack_first until every shown tick is ticked); acknowledge_open_positions and "
        "acknowledge_unknown_positions separate (Y:13773-13791)",
        "keyboard": KB
        + "Tab: positions block → its tick (open or unknown branch; Space toggles) → Back → Next "
        "(busy while GET /admin/overview runs: aria-busy, no focus move; then T2 admin.ack_first "
        "until ticked) → Cancel restore.",
    },
    "RW-5": {
        "decisions": 'D40 / ruling Q2 (target labelled "if D7 decides as proposed": security_list + security_ack '
        "tick, signout before step 3; today's inset: security_today only, no list, no tick), D25, "
        "CG-7 (#3084), C-2.6, C-12.4",
        "keyboard": KB + "Tab: target label → security list → restore.impact.security_ack tick → "
        "restore.impact.signout (text) → Back → Next (T2 admin.ack_first until ticked) → Cancel "
        "restore. Today's inset: no tick, so Next is reachable after the line.",
    },
    "RW-6": {
        "decisions": "D23 (typed token = the start time as titled, client ceremony, said so; server checks "
        "confirm_backup_id), D24 (rung 4 inside the step; a refusal spends the code), D25, CG-7 / "
        "SR-E42-04 (reason_replaced + marker_replaced while postgres in scope; config-only inset: "
        'restore.confirm.reason + "Backup restored (backup.restore)"), §4.1 (confirm waits on form '
        "validity: native disabled, not T2)",
        "keyboard": KB
        + "Focus to the step-3 heading; Tab: title → kind and size → token field → Why? (3–280) → "
        "step-up line → marker → Back → [Restore from 2026-10-21 01:00] (enabled when the token "
        "matches and Why? has 3 characters); Enter in token or Why? never confirms; the confirm "
        "ignores event.repeat; the code dialog replaces the step (focus Cancel) and returns.",
    },
}
rows, groups = d.board_parts(6, blocks)

# --- Review r2 fixes (written here, the kit is read-only).
# (1) RW-4's when is "2 open; unreadable": the kit preset draws the open branch only. A second inset in the same
#     1280 frame draws the unknown branch (today's real answer, §8.1): restore.positions.unknown + its own tick,
#     stacked above the loading inset (same br corner, 16 px apart). Its keys join RW-4's Copy keys.
# (2) Tokens rows: board_parts counts tokens only where first recorded (RW-1), so RW-3..RW-6 looked de-duplicated.
#     Every group's Tokens row is rebuilt from the tokens its own frames bind (walk of the frame nodes).
TOKEN_RE = re.compile(
    r"^(color|type|space|size|radius|opacity|border|elevation|motion|shadow)\.[a-z0-9.\-]+$"
)


def frame_tokens(nodes):
    out = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and TOKEN_RE.match(v):
            out.add(v)

    walk(nodes)
    return out


frames = [f for r in rows for f in r]
rw4 = next(f for f in frames if f["name"].startswith("RW-4 · "))
loading = next(c for c in rw4["kids"] if c.get("abs") and c["name"].startswith("inset · RW-4"))
unk = d.inset(
    1280,
    "RW-4",
    "unknown branch: the positions read failed",
    [
        d.words("restore.positions.unknown", d.BODY, d.TEXT_1, w=420),
        d.tick(d.copy("restore.positions.unknown_ack"), checked=False, w=420),
    ],
    w=460,
)
unk["y"] = round(loading["y"] - d.est_height(unk) - d.PX[d.INSET_LG])
rw4["kids"].insert(rw4["kids"].index(loading), unk)
d.note(
    "live_checks",
    f"inset '{unk['name']}' (RW-4 1280): stacked above the loading inset at y {unk['y']}; after "
    "relayout keep both inside the frame above the StatusBar, not overlapping",
)

INSETS = {
    "RW-1": ["RW-1 · RW-16"],
    "RW-4": ["RW-4 · loading", "RW-4 · unknown branch"],
    "RW-5": ["RW-5 · today"],
    "RW-6": ["RW-6 · config-only"],
}
EXTRA_COPY = {"RW-4": ["restore.positions.unknown", "restore.positions.unknown_ack"]}


def block_text(g, name):
    b = next((c for c in g["kids"] if c.get("name") == name), None)
    return b["kids"][1]["chars"] if b else None


new_groups = []
for g in groups:
    sid = g["name"].split(" · ", 1)[1]
    fs = [f for f in frames if f["name"].startswith(sid + " · ")]
    bl = dict(blocks.get(sid, {}))
    cp = [x.strip() for x in (block_text(g, "block · copy") or "").split(", ") if x.strip()]
    bl["copy"] = ", ".join(dict.fromkeys(cp + EXTRA_COPY.get(sid, [])))
    bl["tokens"] = (
        d.k.tokens_line(frame_tokens(fs))
        + " (every token this state's frames bind, insets included)"
    )
    new_groups.append(d.ann_group(sid, fs, bl, insets=INSETS.get(sid, [])))
groups = new_groups
extra = [d.focus_overlay(s, dialogs=True, stepper=True) for s in d.BOARDS[6].keys]
ann = d.ann_column(6, groups, extra)
r = d.write_board(6, rows, ann)
print(r["valid"], r["nodes"], r["sections"])
print({k: v for k, v in r.items() if k not in ("valid", "nodes", "sections")})
