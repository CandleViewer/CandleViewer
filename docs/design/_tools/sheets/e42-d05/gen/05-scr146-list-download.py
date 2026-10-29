"""E42-D05 board 05 `scr146-list-download` (dark): BK-4 1280+2560, BK-2 · BK-12 1280+2560, BK-9 · BK-13 (link-expired,
404 insets), BK-14. Built from the kit's presets; this generator passes Decision ids and Keyboard path per state and
adds the SCR-146 focus overlay (keyboard rider).

Review fixes (2026-10-28): BK-9 draws no header-level banner (the kit preset's extra_top banner is dropped here: §7's
BK-9 row names only Failed + backup.error.<code> with the code in a disclosure); BK-9 and BK-14 carry their own Tokens
and Copy keys, measured by building each state's frame alone (the kit's note log dedups across states, so a state
drawn after BK-4/BK-12 otherwise records few or no tokens)."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

_kit_scr146 = d.scr146


def _scr146(px, sid="BK-4", **kw):  # type: ignore[no-untyped-def]
    """BK-9 without the preset's header banner: the spec row draws the failure in the row, not above the table."""
    if sid == "BK-9":
        kw.pop("extra_top", None)
    return _kit_scr146(px, sid, **kw)


d.scr146 = _scr146


def alone(nn: int, sid: str) -> tuple[str, list[str]]:
    """Build one state's frames on a clean note log; return its tokens line and copy keys, then clear the log."""
    d.reset_notes()
    d.mark()
    for f in d.plan_frames(nn):
        if f.sid == sid:
            d.build_frame(f)
    out = d.k.tokens_line(d._since("tokens")), list(d._since("copy_keys"))
    d.reset_notes()
    return out


NN = 5
TABLE_KEYS = (
    "Tab: Back up now → Restore… → the table (APG grid; row actions reached by ← →; Enter acts once, "
    "ignoring event.repeat) → Load more (E42-D05 L428). T2 controls stay focusable and announce their "
    "reason; Enter/Space send nothing (§4.1 L191)."
)
DIALOG_KEYS = (
    "Dialog opens with focus on Cancel (ring); Tab through the fields in reading order → Cancel → the "
    "confirm; Enter in the token field never confirms; Esc cancels; focus returns to the opening control; "
    "a refusal speaks once (E42-D05 L428-430)."
)

BLOCKS = {
    "BK-4": {
        "decisions": "D1, D19, D20, D21, D36, D37, D38, D47 (T2 legs per §4.1)",
        "keyboard": TABLE_KEYS,
    },
    "BK-2": {
        "decisions": "D19, D37, D38; §4.1 T2 (one notice, many pointers: admin.backups_not_built)",
        "keyboard": TABLE_KEYS
        + " Back up now, Restore… and every row action are T2 pointing at the one notice.",
    },
    "BK-12": {
        "decisions": "D21, D47, D37, D38 (rung 4, typed timestamp token as client ceremony, fresh code)",
        "keyboard": DIALOG_KEYS,
    },
    "BK-9": {
        "decisions": "D19, D20, D36, D37, D38 (Failed + backup.error.<code> in a disclosure; inconclusive keeps status)",
        "keyboard": TABLE_KEYS
        + " The failed row's code disclosure is a button (Enter/Space toggles).",
    },
    "BK-13": {
        "decisions": "D21, D47, D51 (link shown once with [Download], never [Copy link]; at expires_at the "
        "outcome line replaces [Download], never T2)",
        "keyboard": "Focus on [Download] when the link is shown; Tab → [Close]; Esc closes (closing hides the "
        "link, never ends it); focus returns to the row's Download (E42-D05 L428-430).",
    },
    "BK-14": {
        "decisions": "D19, D37, D38, D50 (rung 4 + token; the row stays; usable backups of this kind left)",
        "keyboard": DIALOG_KEYS,
    },
}

tok9, copy9 = alone(NN, "BK-9")
tok14, copy14 = alone(NN, "BK-14")
assert (
    "backup.del.outcome" in copy14 and "backup.dl.token" in copy14 and "fresh_code" in copy14
), copy14
BLOCKS["BK-9"].update(
    {
        "tokens": tok9,
        "copy": (
            "`backup.error.*`: backup.error.checksum_mismatch (the failed row's sentence, in words); "
            "backup.status.failed; backup.summary.last_verified (the last-verified line states its age, E42J:215); "
            "the kit's disclosure label 'Code' (copy gap). The raw code `checksum_mismatch` appears only inside the "
            "opened disclosure, never in a sentence or a header. Inconclusive: status unchanged + "
            "backup.verify_inconclusive (not drawn: the row keeps its status)."
        ),
        "announcement": (
            "assertive once (the conclusive failure: the row's status turning Failed, spoken once from the "
            "row's status cell; no header banner is drawn, §7 BK-9 names none); polite (inconclusive: "
            "backup.verify_inconclusive)"
        ),
    }
)
BLOCKS["BK-14"].update(
    {
        "tokens": tok14,
        "copy": (
            "`backup.del.*`: backup.del.title, backup.del.list (the row stays; {n} usable backups of this kind "
            "left), backup.del.outcome (the Deleted row behind the scrim); the token label backup.dl.token (§15 "
            'lists no delete-specific token key: deviation noted); the fresh-code line "This always needs a fresh '
            'code." (fresh_code, D04 §11); the CMP-093 marker backup.deleted (the audit action code)'
        ),
    }
)

rows, groups = d.board_parts(NN, BLOCKS)
extra = [d.focus_overlay("SCR-146", dialogs=True)]
ann = d.ann_column(NN, groups, extra)
r = d.write_board(NN, rows, ann)
print(r["valid"], r["nodes"], r["sections"])
print({k: v for k, v in r.items() if k not in ("valid", "nodes", "sections")})
