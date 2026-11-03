"""Board 03 `E47-D06 / 03 profile-table` (dark): §6.2's profile table over SCR-038 — sorted by volume, the In VA
filter, POC / VAH / VAL as words, the TPO Periods column. Board 08 (the light twin) calls frames() and blocks()."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PH, PROFILE_TITLE, PROFILE_SCOPE, PW, PX0, grid_y, k, profile_body, profile_panel  # noqa: E402

NN = 3
POC_K = k.PROF_META["poc"]
CX = PX0 + sum(c.w for c in k.PROFILE_COLS) + 40 + 2 * k.PX[k.INSET_SM] + 24  # callouts right of the grid


def frames(nn: int) -> list[dict]:
    b = k.BOARDS[nn]
    by_vol = sorted(k.PROFILE, key=lambda x: (-x.vol, -x.k))
    in_va = [x for x in k.PROFILE if x.in_va]
    f1 = k.window(b.frames[0], [profile_panel(profile_body(levels=by_vol, focus_k=POC_K, sort="Volume",
                                                           direction="descending"))],
                  overlays=[k.tag('aria-sort="descending" on Volume', CX, grid_y(0) + 4),
                            k.callout("the sort", [k.fill(k.w("W-4"), column="volume", direction="descending"),
                                                   "W-4, polite, once per sort change (§6.3); the level table resets "
                                                   "to its default when the profile period changes (W-7)"],
                                      CX, grid_y(1), wd=300),
                            k.callout("the focused row", [f"Focus on the POC row ({k.prof_px(POC_K)}), aria-current",
                                                          "Value area carries the POC / VAH / VAL words (PROPOSED, "
                                                          "D06-A17); Periods = letters, TPO count, Initial balance "
                                                          "(PROPOSED, §6.2)"], CX, grid_y(6), wd=300),
                            k.callout("the canvas label", ["Layer 4 (hidden while Table is on): " + k.l2_label(),
                                                           "L-2 (§8)"], CX, grid_y(12), wd=300)])
    f2 = k.window(b.frames[1], [profile_panel(profile_body(levels=in_va, focus_k=POC_K, chips=("In VA",)))],
                  overlays=[k.callout("the filter", [k.fill(k.re.sub(r"\d+ of \d+", "{k} of {n}", k.w("W-2"))
                                                            .replace("Bid-stacked", "{f}"), k=str(len(in_va)),
                                                            n=str(len(k.PROFILE)), f="In VA"),
                                                     "W-2's form, polite, once per filter change; rows narrow, "
                                                     "columns never (§6.3)"], CX, grid_y(1), wd=300),
                            k.callout("natural order", [f"Price, descending: the natural order (§6.2 Profile: "
                                                        f"{k.COL_RULE['profile']['Price']})",
                                                        "VAH, POC and VAL read as words in Value area"],
                                      CX, grid_y(6), wd=300)])
    return [f1, f2]


def blocks(nn: int) -> list[tuple[str, list[str]]]:
    b = k.BOARDS[nn]
    in_va = sum(x.in_va for x in k.PROFILE)
    common = [f"Columns (§6.2 L{k.L('**Profile**', k._S62)}): " + " · ".join(c.name for c in k.PROFILE_COLS)
              + " + the actions column (D04E11 §5.1)",
              f"Caption: \"{k.fill(k.CAPTION_FORM, panel=PROFILE_TITLE, symbol=k.SYMBOL, scope=PROFILE_SCOPE)}\"; "
              "the profile is built from prints, so no \"approximated from bars\" clause (`14`:1009)",
              f"POC {k.prof_px(k.PROF_META['poc'])}, VAH {k.prof_px(k.PROF_META['vah'])}, VAL "
              f"{k.prof_px(k.PROF_META['val'])} ({k.VA_PCT} % value area, kit choice); {len(k.PROFILE)} levels",
              f"Export CSV T2 (2a inline): \"{k.EXPORT_REASON}\", PROPOSED key {k.EXPORT_KEY} (§10 L{k.T2_LINE})"]
    return [(b.frames[0], [f"Sorted by volume, descending (§0 L{k.BOARDS[3].line}; §6.3 L{k.L('### 6.3')})", *common]),
            (b.frames[1], [f"In VA filter: {in_va} of {len(k.PROFILE)} rows (§6.2: Value area is filter-only)",
                           "Tab order: switch → filter toolbar → Pause updates → grid (one stop) → export "
                           f"(§6.7 L{k.L('### 6.7')})"])]


def notes() -> dict:
    k.copy_key(f"{k.EXPORT_KEY} (PROPOSED, owner E11-D04): \"{k.EXPORT_REASON}\", the Export CSV T2 reason")
    k.ambiguity("\"sorted by volume\" (§0 board 03) names no direction: drawn descending (the second activation of "
                "§6.3's tri-state), so the largest level leads")
    k.ambiguity("Value area cell: \"In VA\" / \"Outside VA\" then the POC / VAH / VAL word, joined by \", \" (§5's "
                "value joiner); Periods cell: letters, the TPO count as \"n TPO\", then \"Initial balance\" — §6.2 "
                "names the three parts, not their order or format")
    k.copy_gap("\"Add filter\", \"Columns\": SCR-045's toolbar labels (D04E11:788), reused by §6.1's shell")
    k.copy_gap("the panel title \"" + PROFILE_TITLE + "\": `14`'s SCR-038 heading, \" panel\" and the parenthesis "
               "dropped (the panel header's own words are its spec's)")
    k.deviate(f"{k.VA_PCT} % value area, rows of {k.PROF_ROW} ticks, 30-minute periods lettered from A: kit "
              "choices (SCR-038's settings, `14`:1025); the profile itself is E19's")
    return {}


def main() -> None:
    notes()
    p, md, pk = k.build(NN, frames(NN), blocks(NN), per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
