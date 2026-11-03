"""Board 07 trading-t2-arm-env: §5 the one notice and the T2 legs, SCR-050/arm-locked, SCR-050/demo,
SCR-050/live (C-2.11) and the ARMED inset (E30-D04's, labelled E31); dark, exported again under light (the twin)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 7


def arm_locked() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/arm-locked"
    p = ui.P(menu="overflow-arm")
    return ui.panel(fid, p, markers=[ui.announce(k.W("W-20"), how="polite, each press (R-7)")]), k.frame_block(fid, [
        "CMP-229 drawn LOCKED with arm.locked (W-13, E30-D02's, D02E30:405), T2 2a on W-20 while E21 holds; "
        "Ctrl+Shift+T re-shows W-20 and changes nothing; the pill's text is never shortened below \"LOCKED\"",
        "At 1280 px the pill sits in ⋯ (drawn open, focus on the pill) and its state is echoed after the title",
        f"{{size}} = the footer's selected qty {k.PRESETS[0]} (`14`:1211); {{account}} = {k.ACCOUNTS[0]} (synthetic)",
        "Cancel and close are never gated on the arm (R-4; C-2.6)"])


def env(e: str) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = f"SCR-050/{e.lower()}"
    p = ui.P(env=e, own=e == "DEMO")
    lines = [f"Badge {e} from the session environment, never the feed (R-5, C-2.11); in the region's name; never "
             "shed (`14`:3115)", "DEMO and LIVE are separate frames, never a toggle on this panel (SCR-074 / SCR-075)"]
    if e == "LIVE":
        lines.append("Your orders shows only the LIVE session's orders: the synthetic LIVE session holds none, so no "
                     "demo account appears under LIVE; the Owner here has live allowed, so the rbac.env leg does not "
                     "apply and W-20 leads (legs frame)")
    else:
        lines.append(f"Your orders: the DEMO session's synthetic orders ({k.ACCOUNTS[0]}, {k.ACCOUNTS[1]})")
    return ui.panel(fid, p, markers=[ui.acc_name("region name", ui.region_name(e))]), k.frame_block(fid, lines)


def legs() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.LEGS
    tbl = k.grid_table("§5.1 legs", [k.Col("o", "Order", 64), k.Col("leg", "Leg", 120),
                                     k.Col("key", "Key (string)", 640), k.Col("when", "When", 344)],
                       [{"o": c[0], "leg": k.plain(c[1]), "key": k.plain(c[2]), "when": k.plain(c[3])}
                        for _i, c in k.LEG_ROWS], cap=f"§5.1 L{k.LEG_ROWS[0][0]}: legs in E09-D09 order, the first "
                                                      "missing leg shown")
    specs = []
    for _i, c in k.LEG_ROWS:
        qs = re.findall(r'"([^"]+)"', c[2])
        words = [q.replace("{user}", k.VIEW_AS_USER) for q in qs]
        if not words:
            words = [k.W("W-8", age=f"{k.STALE_T1_AGE} s")] if "feed" in c[2] else [k.W("W-20")]
        for w_ in words:
            k.S(w_.replace(k.VIEW_AS_USER, "{user}")) if "{user}" in c[2] else None
            specs.append(ui.hbox(f"notice specimen · leg {c[0]} · {w_[:24]}".replace("/", k.SLASH),
                                 [ui.lock(), k.text("reason", w_, k.CAPTION, k.TEXT_2)],
                                 {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": k.RAISED}, w=1168, h=32))
    gated = k.grid_table("§5.2 gated controls", [k.Col("c", "Control", 300), k.Col("r", "Rendering", 360),
                                                 k.Col("l", "Leg shown", 240), k.Col("n", "Never", 268)],
                         [{"c": k.plain(c[0]), "r": k.plain(c[1]), "l": k.plain(c[2]), "n": k.plain(c[3])}
                          for _i, c in k.GATED], cap=f"§5.2 L{k.GATED[0][0]}: the gated controls")
    lab = k.text("label", k.ui("the one notice as each leg renders it (rendering 2a)", "board-marker caption"),
                 k.CAPTION, k.TEXT_2)
    return k.marker_frame(fid, [tbl, lab, *specs, gated], 1232), k.frame_block(fid, [
        f"The viewing-as {{user}} is \"{k.VIEW_AS_USER}\" (synthetic); the feed leg is drawn with W-8 (T1, "
        f"{k.STALE_T1_AGE} s), its other keys on board 05 and 06",
        "Every press, click or bound key on a gated control changes nothing and re-announces the shown leg's reason "
        "once, polite (R-7); the sighted cue a static 1 s color.focus.ring outline on the notice"])


def armed() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.ARMED
    words = k.ui("ARMED is E30-D04's frame, cited here as an inset and labelled E31; this board draws no ARMED pill "
                 "(§0: not drawn — the text is binding). dom.arm_toggled is annotated on this inset only; in E21 the "
                 "toggle sends nothing (§11.1).", "the inset's citation")
    return k.marker_frame(fid, [k.text("words", words, k.BODY, k.TEXT_1, w=560)], 608), k.frame_block(fid, [
        "In LIVE the pill and the badge sit together at the header's right (§5.3); E31 retires W-20"])


if __name__ == "__main__":
    ui.run(NN, [arm_locked(), env("DEMO"), env("LIVE"), legs(), armed()], 3)
