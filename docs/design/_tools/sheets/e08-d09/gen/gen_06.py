"""Board 06 simulator-budget (§0): the simulator in S-19 and with its result (served now and deferred accounts),
the Change budget dialog and its refusal (§12), and the T2 view-as forms of both actions (§13.1, §17.5 T2-1, T2-2).
Run: python3 -I -B gen_06.py"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair5_helpers as h  # noqa: E402
from pair5_helpers import cw, k  # noqa: E402

NN = 6
REFUSED_VALUE = 600  # above W-61's 420: refused by the server, kept in the field


def frame(fid: str, theme: str, sections: list, *, overlays: Any = (), scroll: int | None = None):  # noqa: ANN202
    return k.window(fid, theme, sections, scroll=h.fit_scroll(sections) if scroll is None else scroll,
                    overlays=overlays)


def y_of(n: dict, name: str) -> tuple[float, float] | None:
    """(top, height) of the first descendant named `name`, through column boxes (estimates)."""
    if n.get("name") == name:
        return 0.0, k.est_height(n)
    o, y = n.get("o") or {}, 0.0
    pad = k._px(o.get("pad")) + k._px(o.get("padY")) + k._px(o.get("padT"))
    for c in n.get("kids") or []:
        r = y_of(c, name)
        if r is not None:
            return (pad + (y if o.get("dir") == "column" else 0.0) + r[0]), r[1]
        y += k.est_height(c) + k._px(o.get("gap"))
    return None


def build(theme: str = "dark") -> tuple[list, dict]:
    fids = [f for f, _s in k.frames_of(NN)]
    frames, blocks = [], []
    kb_sim = "SCR-147-KB-4: Space on a checkbox, type in the number fields, arrows in the segmented control, " \
             "Enter / Space on Estimate cost (PP-3)"
    world = (f"Illustrative world: order.create {h.LIM} / s per account, reserve {h.RESERVE} requests (served form "
             f"assumes D09-G1, D09-G14); Headroom = limit - reserve - used now")

    # 1. the simulator in S-19: inputs live, output not connected (D09-G10)
    h.start()
    secs = [h.budgets(), h.simulator(served=False)]
    frames.append(frame(fids[0], theme, secs))
    blocks.append(k.frame_block(fids[0], waits=["D09-G10"], keyboard=kb_sim,
                                lines=["Inputs drawn live; the output reads S-19 until a cost read exists (§8; the "
                                       "arithmetic stays server-side, C-2.12)",
                                       "Scrolled so the simulator is in view; the budgets above it as served", world,
                                       h.copy_line()]))

    # 2. the simulator's result: 5 accounts, a bracket each, best effort
    h.start()
    secs = [h.budgets(), h.simulator(served=True)]
    frames.append(frame(fids[1], theme, secs))
    n, tot = len(k.ACCOUNTS), len(k.ACCOUNTS) * h.PER_ACCOUNT
    blocks.append(k.frame_block(fids[1], waits=["D09-G10"], keyboard=kb_sim + "; focus stays on Estimate cost",
                                lines=[f"Per account {h.PER_ACCOUNT} requests = {h.LEGS_ENTRY} entry + {h.LEGS_TP} "
                                       f"take-profit + {h.SL_COST} separate stop (sl_cost 1, §7); {n} x "
                                       f"{h.PER_ACCOUNT} = {tot} (derived)",
                                       f"Share {k.pct(h.PER_ACCOUNT, h.BUDGET_MIN)} % = {h.PER_ACCOUNT} of "
                                       f"{h.BUDGET_MIN} spendable requests per minute (our budget, the reserve kept "
                                       "out of it, W-64); not the catalogue's 9 % (D09-C7)",
                                       f"IP bucket {tot} of {k.LIM['ip_per_5s']} per 5 s = "
                                       f"{100 * tot / k.LIM['ip_per_5s']:.1f} % (derived)",
                                       f"Deferred: {', '.join(h.DEFERRED)} have under {h.PER_ACCOUNT} spendable "
                                       "requests left this minute (illustrative)",
                                       f'SCR-147-SR-11 polite, once per estimate: "{h.sim_announce()}"',
                                       f'Editing an input marks the result "{k.w("W-43")}" (W-43) without clearing it',
                                       h.copy_line()]))

    # 3. the Change budget dialog (rung 1), opened from Main's row action
    h.start()
    dlg = h.budget_dialog(value=str(h.BUDGET_MIN))
    secs = [h.budgets()]
    frames.append(frame(fids[2], theme, secs, overlays=k.modal(dlg, measured_h=490), scroll=0))  # h as drawn
    blocks.append(k.frame_block(fids[2], waits=["D09-G8", "D09-G12", "D09-G17"],
                                keyboard="SCR-147-KB-3: Tab, type, Enter in the field never saves, Esc; opened by "
                                         "SCR-147-KB-2 (Enter on the action cell, Shift+F10)",
                                lines=["Rung 1, reversible (§12); contract-first: no field, route or setting "
                                       "(D09-G8); the audit code is withheld until registered (W-63)",
                                       f"Current {h.BUDGET_MIN} requests per minute, inside W-61's {h.ALLOWED[0]} to "
                                       f"{h.ALLOWED[1]}; the exchange's {h.LIM} / s = {h.LIM * 60} per minute is the "
                                       "ceiling (W-64)", world, h.copy_line()]))

    # 4. the refusal: an out-of-range value kept, the server's mapped reason under the field
    h.start()
    dlg = h.budget_dialog(value=str(REFUSED_VALUE), refused=True)
    secs = [h.budgets()]
    frames.append(frame(fids[3], theme, secs, overlays=k.modal(dlg, measured_h=521), scroll=0))  # h as drawn
    blocks.append(k.frame_block(fids[3], waits=["D09-G8"],
                                keyboard="SCR-147-T2-4: validity, inline under the field; focus kept in the field; "
                                         "once per change",
                                lines=[f"{REFUSED_VALUE} is above the allowed {h.ALLOWED[1]} (W-61): refused by the "
                                       "server; the dialog stays open with the value kept (§12)",
                                       "The reason is the server's mapped sentence (CMP-027), never the body (§6, "
                                       "§13.2); §15 has no string: drawn as W-59's slot", h.copy_line()]))

    # 5. T2 view-as forms: Change budget… in the row menu (T2-2), Reconnect market data (T2-1)
    h.start()
    reason = cw("W-74", None, h.VIEW_AS)
    t2 = k.t2_button(cw("W-50"), reason, name="T2 · Reconnect market data + reason")
    secs = [h.budgets(focus_main=False), h.actions(t2)]
    sc = h.fit_scroll(secs)
    page = k.vbox("probe", [k.band(), k.rule(), k.page_header(), *secs], {"gap": k.STACK_LG}, w=k.INNER_W)
    top, rh = y_of(page, "row 01 · order.create · Main") or (0.0, 0.0)
    my = round(k.TOP_H + 16 - sc + top + rh + 4)
    mx = k.NAV_W + 16 + k.INNER_W - 264
    frames.append(frame(fids[4], theme, secs, overlays=[h.row_menu_t2(mx, my)], scroll=sc))
    k.live(f"T2 frame: the row menu sits under Main's row action (estimated x {mx}, y {my}); re-anchor it to the "
           "row's bottom-right after relayout")
    blocks.append(k.frame_block(fids[4], waits=["D09-G17"],
                                keyboard="T2 keys announce the reason once per press (SCR-147-SR-13); focus kept on "
                                         "the control or the menu item",
                                lines=["SCR-147-T2-2: rendering 2a in the row menu, the reason as the item's second "
                                       "line; SCR-147-T2-1: the lock leads the full label, the reason under it",
                                       "Legs: rbac.view_as (3a), then the permission (3b: not defined yet, D09-G17), "
                                       "then the state (§17.5)",
                                       f'"{h.VIEW_AS}" is a kit alias for W-74\'s {{user}} slot (§15 gives no sample)',
                                       "Re-measure is a read and stays enabled under view-as (§13.1): board 05",
                                       h.copy_line()]))

    ann = k.annotations(NN, blocks, board_lines=[
        "Frames draw Rate budgets (served form) with the simulator, the dialogs or Actions, in §2.2's order; "
        "sections between them are off the frame", world])
    k.deviate(f"W-74's {{user}} slot filled with the kit alias {h.VIEW_AS!r} (no sample in §15)")
    k.deviate("board 06: the dialogs open over Rate budgets; the T2 frame draws Rate budgets then Actions (the "
              "simulator, inspector and clock between them are off the frame)")
    k.deviate("the T2 row menu is drawn as an overlay anchored under Main's row action (position estimated)")
    k.spec_gap("§12's refusal: the server's mapped reason has no §15 string; drawn as W-59's slot {mapped reason}")
    k.spec_gap("§8's output columns and the IP bucket line have no §15 strings: headings from §8's Output prose")
    return frames, ann


def main(theme: str = "dark", nn: int = NN) -> None:
    frames, ann = build(theme)
    k.live("simulator result: read back 5 rows, 3 'Served now' and 2 'Deferred', and the W-40 line with 15 requests "
           "and 3 %")
    k.live("Change budget dialog: read back the focus ring on Cancel; refusal frame: the ring on the field, the "
           "field's value 600 and the danger stroke")
    p = k.write_sheet(nn, frames, ann)
    md = k.write_md(nn, p)
    packed = k.pack_sheet(p)
    rc, msg = k.validate(p)
    print(p, md, packed, f"validator exit {rc}: {msg.splitlines()[-1] if msg else ''}", sep="\n")


if __name__ == "__main__":
    main()
