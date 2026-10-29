"""E42-D05 board 02 `status-sheet` (dark, ★): dark, light and hc status columns at 1280 x 800 plus old board 04's
forced-colours inset (HL-6, RW-3, WZ-5, §4.3) as a fourth column. Run: python3 -I -B gen/02-status-sheet.py
"""

import copy as copy_mod
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import e42d05kit as K
from e42d05kit import Node

NN = 2
G = K.L_GREY
F = K.L_FORCED
COMMON = {
    "roles": "a static proof sheet: no role gate; every status shown is the one Owner and Manager see on SCR-143, "
    "SCR-144, SCR-146, the restore and onboarding steppers and the inspector (no state is role-specific)",
    "keyboard": "none: the sheet is a non-interactive specimen; each family's focus path is on its own board's "
    "focus overlay (03 SCR-143/144, 05 SCR-146, 06 restore, 08-09 wizard, SCR-062, inspector); "
    "T2 controls stay focusable (aria-disabled) per §4.1",
    "announcement": "none on the sheet; each status's announcement is its state row's (HL-, IL-, BK-, RW-, WZ-, SI-)",
    "events": "none: no analytics or audit event fires from a specimen sheet (D37 registry names live on the "
    "state boards)",
}
BLOCKS = {
    "sheet-dark · dark": dict(
        COMMON,
        source=f"E42-D05 §16 L{G - 22}-{G + 9} (contrast, greyscale and colour-vision pair); D2 L{K.D2_LINE}; "
        "deviation (4) L40; old board [02]",
        state="status sheet · dark — every status family as word + glyph: health (D2), stale (D6/CMP-239), "
        "incident resolution and severity (D15, D18), backup statuses (D19), stepper statuses (D27), "
        "machine statuses (D35), T2 (§4.1), CMP-023",
        decisions="D2, D6, D9, D15, D18, D19, D27, D35, D48, D49; §4.1 T2; deviation (4)",
    ),
    "sheet-light · light": dict(
        COMMON,
        source=f"E42-D05 §16 L{G - 22}-{G + 9}; deviation (4) L40 (light draws one representative state per "
        "surface); old board [02]",
        state="status sheet · light — the same construction; the theme switches at export (light layers on the "
        "dark set through tok/themes.json)",
        decisions="D2, D6, D27, D35; §4.1 T2; deviation (4); OQ-2",
    ),
    "sheet-hc · hc": dict(
        COMMON,
        source=f"E42-D05 §16 L{G - 22}-{G + 9} (hc aim 7 for body text, 05:130); deviation (4) L40; OQ-2; "
        "old board [02]",
        state="status sheet · high contrast — the same construction exported in the hc theme; high contrast is "
        "proven by §16's computed matrix and this column (deviation (4))",
        decisions="D2, D6, D27, D35; §4.1 T2; deviation (4); OQ-2; CG-30 (hc links miss 7:1 on *.subtle)",
    ),
    "sheet-fc · forced colours": dict(
        COMMON,
        source=f"E42-D05 §4.3 L{F}-{F + 7} (spec line 230's 'Board 04 adds a forced-colours inset' moves here "
        "per the confirmed plan); old board [04]",
        state="forced colours (forced-colors: active) — HL-6, RW-3 and WZ-5 crops under forced(): words, borders "
        "and glyphs carry state; current step and selected row Highlight/HighlightText; CMP-023 bar "
        "Highlight beside its '{n} %'; the diagram's current state keeps 3 px border + 'current'",
        decisions="§4.3; D2, D24, D27, D29; deviation (4)",
    ),
}

_status_col = K.status_sheet_column


def status_column(theme: str, px: int = 1280) -> Node:
    """The kit's status-sheet column without its visible 'Theme column: …' line (not spec copy): the theme moves
    into the frame's note (review r1 finding 2)."""
    fr = _status_col(theme, px)
    fr["kids"] = [c for c in fr["kids"] if c.get("name") != "theme"]
    fr["note"] = (
        f"theme column: {theme} (the theme is applied at export; the three columns share one construction)"
    )
    return fr


def fc_column(px: int = 1280) -> Node:
    """Board 02's fourth column (generator-local replacement of K.fc_column, review r1 findings 3-5): old board 04's
    forced-colours inset of HL-6, RW-3 and WZ-5 (§4.3), each crop sized to its content so no text is clipped:
    row 1 the HL-6 frame's first tile row (healthy, degraded, down) 1:1; row 2 RW-3 (the 6-step stepper with step 1
    'Done {date}' and the step-2 h2) beside WZ-5 (stepper steps 1-6 of 8: step 3 the one aria-current step, blocked;
    step 4 'Not started'; and the step-3 body at the crop's width)."""
    K.deviate("status-cols")
    K.src(f"forced colours: E42-D05 §4.3 L{F}-{F + 7}")
    g = K.SIZES[px]
    cw = g.w - 2 * K.PX[K.INSET_LG]
    half = (cw - K.PX[K.INSET_LG]) // 2
    bw = half - K.STEPPER_W - K.PX[K.INSET_XL]
    comps = K.hl6_comps()
    tiles = K.hbox(
        "HL-6 tiles",
        [dict(K.health_tile(px, c, col=i), w=K.TILE_W[px][i]) for i, c in enumerate(comps[:3])],
        {"gap": K.STEP, "align": "start"},
    )
    rw_st = [("done", {"date": K.DATE}), ("current", {})] + [("not_started", {})] * 4
    K.note(
        "deviations",
        "board 02 fc RW-3 crop: step 1 reads 'Done 2026-10-22' (the worked example's date; §8 names "
        "no restore step dates, the kit uses §9.1's 'Done {yyyy-mm-dd}')",
    )
    rw = K.hbox(
        "wizard",
        [K.stepper(K.RESTORE_STEPS, rw_st, 2), K.step_body(px, K.RESTORE_STEPS[1], [], [], w=bw)],
        {"gap": K.INSET_XL, "align": "start"},
        note="RW-3 crop: the stepper and the step-2 h2; the §8.2 impact lines and scope picker are on board 06",
    )
    d_ = {"date": K.DATE}
    wz_st = [("done", d_), ("done", d_), ("blocked", {"until": K.ONBOARD_EXAMPLE["opens"]})] + [
        ("not_started", {})
    ] * 3
    y_, m_ = K.ONBOARD_EXAMPLE["opens"], K.ONBOARD_EXAMPLE["opens_in"]
    opens = K.words("onboard.opens", K.BODY, K.TEXT_2, w=bw, yyyy_mm_dd_hh_mm=y_, d=m_[0], h=m_[1])
    add = K.t2(
        K.label("Add key", K.STATES["WZ-5"].line, "WZ-5's control"),
        "admin.key_cooldown",
        variant="primary",
        w=bw,
    )
    wz_body = K.step_body(
        px,
        "3 API key",
        [K.words("onboard.key_wait", K.BODY, K.TEXT_1, w=bw), add, opens],
        [K.button("Back", "secondary"), K.continue_to(4)],
        w=bw,
    )
    wz = K.hbox(
        "wizard",
        [K.stepper(K.ONBOARD_STEPS[:6], wz_st, 3), wz_body],
        {"gap": K.INSET_XL, "align": "start"},
        note="WZ-5 crop: stepper steps 1-6 of 8 (7 Limits and 8 Invite, both Not started, below the crop); "
        "the exact time sits under the reason at this crop width (the reason row wraps)",
    )

    def crop(sid: str, part: Node, w: int) -> Node:
        h = int(K.k.est_height(part)) + 8
        return K.vbox(
            f"crop · {sid}",
            [
                K.text("label", f"{sid} · forced-colors: active", K.LABEL, K.TEXT_2),
                K.box("crop", [dict(part, x=0, y=0)], {"clip": True}, w=w, h=h),
            ],
            {"gap": K.STACK_XS},
            w=w,
        )

    row2 = K.hbox(
        "row 2",
        [crop("RW-3", rw, half), crop("WZ-5", wz, half)],
        {"gap": K.INSET_LG, "align": "start"},
        w=cw,
    )
    fr = K.vbox(
        f"frame-{px}",
        [crop("HL-6", tiles, cw), row2],
        {"fill": K.APP, "clip": True, "pad": K.INSET_LG, "gap": K.STACK_SM},
        w=g.w,
        h=g.h,
    )
    used = K.k.est_height(dict(fr, h=None))
    if used > g.h:
        raise SystemExit(f"fc column overflows: {used:.0f} > {g.h}")
    return K.forced(fr)


K.status_sheet_column = status_column
K.fc_column = fc_column

rows, groups = K.board_parts(NN, BLOCKS)

# Review r1 finding 1: the light and hc groups repeat the dark group's copy keys and tokens (same construction).
_dark = next(g_ for g_ in groups if g_["name"] == "group · status sheet · dark")
_shared = {b["name"]: b for b in _dark["kids"] if b["name"] in ("block · copy", "block · tokens")}
for g_ in groups:
    if g_["name"] in ("group · status sheet · light", "group · status sheet · hc"):
        names = [c["name"] for c in g_["kids"]]
        for nm in ("block · copy", "block · tokens"):
            if nm in names:
                continue
            blk = copy_mod.deepcopy(_shared[nm])
            v1 = next(c for c in blk["kids"] if c["name"] == "value-1")
            v1["chars"] = "as the dark frame (same construction): " + v1["chars"]
            at_ = names.index("block · events") if "block · events" in names else len(names)
            g_["kids"].insert(at_, blk)
            names.insert(at_, nm)
summary = K.write_board(
    NN,
    rows,
    K.ann_column(NN, groups),
    md_extra=[
        "",
        "## Ambiguities",
        "",
        "- §4.3 L230 puts the forced-colours inset on board 04; the confirmed plan moves it to board 02's fourth column.",
        (
            "- Forced colours have no cvsheet token theme: Canvas / CanvasText / LinkText / Highlight / HighlightText are "
            "stand-ins (FALLBACKS['FC']); light and hc themes switch at export, so the three columns share one construction."
        ),
        (
            "- The 3 px current-state border is border.thick + border.hairline nested; incident statuses beyond §1 (chain "
            "break open, break-glass acknowledged) are kit judgements."
        ),
        "- The status sheet has no state row: roles, keyboard, announcement and events read 'none / see the state boards'.",
        "- Light and hc groups: copy keys and tokens are the dark frame's (same construction), stated as such.",
        (
            "- Board labels (deliberate, not spec copy): the crop labels 'HL-6 · forced-colors: active', 'RW-3 · …', "
            "'WZ-5 · …'. The old visible 'Theme column: …' line is gone; each column's theme is in the frame name and note."
        ),
        (
            "- Forced-colours crops are generator-local (fc_column in this file replaces K.fc_column; the kit is unchanged) "
            "and sized to their estimated content (no clipped text): HL-6 crop = the frame's first tile row (bybit_public_ws "
            "healthy, bybit_private_ws degraded, bybit_rest down); the HL-6 'warning' (disk) and 'Not built yet' "
            "(bars_writer) tiles and the healthy tiles below are omitted (drawn on board 03, HL-6 at 1280)."
        ),
        (
            "- RW-3 crop: the 6-step stepper plus the step-2 h2; the §8.2 impact lines and scope picker are omitted (board "
            "06). Step 1 reads 'Done 2026-10-22': §8 names no restore step dates, so the worked example's date is used."
        ),
        (
            "- WZ-5 crop: stepper steps 1-6 of 8 (7 Limits, 8 Invite: Not started, omitted). Step 3 is the one aria-current "
            "step (status 'Blocked until 2026-10-24 09:15 UTC'); step 4 reads 'Not started' (the spec leaves step 4's "
            "status open; D27 allows one current step). At the 352 px crop body width the exact time sits on its own line under the reason."
        ),
    ],
)
print(
    json.dumps({k_: v for k_, v in summary.items() if k_ not in ("meta",)}, default=str, indent=1)
)
print([m["name"] for m in summary["meta"]])
