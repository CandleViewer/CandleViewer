"""E42-D05 board 08 `onboard-key` (dark): row 1 WZ-4 at 1280 + 2560 [70], WZ-5 at 1280 [71];
row 2 WZ-1 with the WZ-15 inset [67], WZ-6 [72], WZ-11 [77], WZ-12 [78], each 1280.
Frames by the kit's presets; decision ids and keyboard paths per state from E42-D05 §2/§3, §9.1-9.2, §9.3 Keys
(L585-587), §13 (L684-694) and §4.1's T2 keys (L191)."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 8
STEP = "on a step change focus moves to the step heading (h2, tabindex -1; D27, L585)"
BLOCKS = {
    "WZ-4": {
        "decisions": "D30 (secret write-only, no reveal, onboard.secret_once on warning.subtle), D27 (stepper), "
        "D28 (server record), D31 (step order; IP precondition line), D37 (marker api_key.import), "
        "D38 (copy by key); step-up `keys` (§9.1 step 3)",
        "keyboard": f"{STEP}; Tab: API key → API secret (type=password, autocomplete=off, no reveal control) → Save "
        "→ Back → Continue to step 4; Enter in a field submits only step 3's form; Save ignores "
        "event.repeat; Save opens SCR-006 (`keys`): Cancel focused, Esc cancels, focus returns to Save "
        "(§13); a 422 refusal speaks once (assertive)",
    },
    "WZ-5": {
        "decisions": "D29 (Add key T2 admin.key_cooldown, the unlock time a separate line, steps 4-8 stay "
        "available), D43 (ruling Q5, 48 h restriction; UTC only), §4.1 T2, D27, D28; stepper marks: step 3 "
        "reads 'Blocked until …' and step 4 is Current, because D29 keeps steps 4-8 available while "
        "D43's 48 h block runs (the flow does not halt, AC-4); §9.2 names no current step here",
        "keyboard": f"{STEP}; Tab: Add key (T2: aria-disabled, stays focusable; Enter/Space sends nothing and "
        "re-shows the reason with one polite announcement, L191) → Back → Continue to step 4 (enabled: "
        "the flow does not halt, AC-4); the stepper link for step 3 reads 'Blocked until …'",
    },
    "WZ-1": {
        "decisions": "D28 (steps[] from the server record, no local draft), D27 (CMP-066 stepper), D31 (US-ADMIN-013's "
        "eight steps in order); WZ-15 inset: §4.1 T2 admin.wizard_not_built (CG-3 target)",
        "keyboard": "focus starts at the h1; Tab: the stepper's eight step links (nav, ordered list, aria-current) → "
        "Start with step 1; inset WZ-15 (today): Start is T2 (focusable, sends nothing, re-shows the "
        "reason once) → Sub-accounts (SCR-125) link → Invite (SCR-123) link",
    },
    "WZ-6": {
        "decisions": "D30 (revisit: 'Key …{last4} · {status} · checked {hh:mm} UTC' and 'Secret — not shown "
        "again', never a value or hash), D27, D28; the key list GET is a target (M:577-581)",
        "keyboard": f"{STEP}; Tab: Back → Continue to step 4 (no field, value or hash exists to focus); stepper "
        "links reach any step (navigable)",
    },
    "WZ-11": {
        "decisions": "D32 (D03's SCR-123 embedded, never a fork; T2 admin.invite_pending after it), D31, D27, "
        "D37 (marker users.invited); step-up `users`",
        "keyboard": f"{STEP}; Tab: D03 SCR-123's order — role (inv.role) → the invite controls → Save; after create "
        "the link shown once: Copy → Back → Continue; closing with the link shown gives inv.close_warning "
        "(D03's announcements)",
    },
    "WZ-12": {
        "decisions": "D28 (resume lands on the first incomplete step, server truth), D27, D29 (step 3 keeps "
        "'Blocked until …')",
        "keyboard": "on resume focus moves to the first incomplete step's heading (D27, D28); onboard.resume is "
        "announced politely once; Tab: that step's fields → Save → Back → Continue; any stepper link "
        "reaches a done step",
    },
}

rows, groups = d.board_parts(NN, BLOCKS)


def _drop_wz1_dupes(node, in_wz1=False):
    """WZ-1: the page head already carries h1 'Onboard a manager' and meta onboard.saved_server (§9.1 anatomy,
    L526; WZ-1 row L549 lists the saved_server line once), so the step body's repeated h2 and saved_server line are
    dropped here (the kit's onboard_frame adds both; the kit is not edited). Focus on WZ-1 starts at the h1.
    """
    n = 0
    if not isinstance(node, dict):
        return 0
    in_wz1 = in_wz1 or str(node.get("name", "")).startswith("WZ-1 ")
    kids = node.get("kids") or []
    if in_wz1 and node.get("name") == "step body":
        keep = [
            k
            for k in kids
            if not (
                isinstance(k, dict)
                and k.get("t") == "text"
                and k.get("name") in ("h2", "onboard.saved_server")
            )
        ]
        n += len(kids) - len(keep)
        node["kids"] = keep
        kids = keep
    for k in kids:
        n += _drop_wz1_dupes(k, in_wz1)
    return n


dropped = sum(_drop_wz1_dupes(f) for row in rows for f in row)
assert dropped == 2, dropped
extra = [d.focus_overlay("wizard", stepper=True)]
ann = d.ann_column(NN, groups, extra)
r = d.write_board(NN, rows, ann)
print(r.get("valid"), r.get("nodes"), r.get("sections"))
print({k: v for k, v in r.items() if k not in ("notes",)})
