"""Board 01 anatomy-redlines: §2 on Depth & scale (SCR-051/default) — header, tabs, fields, the preview, the footer —
and §2.4's redlines and token map; dark, exported again under light (the twin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 1


def default() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/default"
    tn = ui.tile_name()
    name = ui.hidden_name(tn)
    d = ui.Dlg(focus="tier 200")
    w = ui.dialog_window(fid, d)
    w["kids"].append(dict(name, x=ui.DLG_X + ui.TILE_X, y=ui.DLG_Y + ui.BODY_Y + 24 + ui.TILE_H + 12))
    return w, k.frame_block(fid, [
        f"§2.1 L{k.L('### 2.1 Anatomy') + 2}: CMP-043 size lg, role=\"dialog\", aria-modal=\"true\", named by W-2 "
        f"\"{k.W('W-2', symbol=k.SYM, env='DEMO')}\"; header W-1, the env badge (R-4), close",
        "Body left: CMP-042 tabs (automatic) over the Depth & scale tabpanel; right: the CMP-228 tile (§2.3), static "
        "sample frames of the seeded book, its role=\"img\" name drawn as a board marker under it (not a live region)",
        "Footer (sticky): Reset to defaults, Reset this tab (ghost), the status node (R-5), Cancel, Save (primary)",
        f"Initial focus: the checked tier radio (200, M AD-7); the 500 option is drawn available here (§3.2's "
        f"unavailable variant is board 02)",
        f"Cost warning (§3.4): W-7 for {', '.join(map(str, k.MEASURED_TIERS))} and W-8 for 500 — figures "
        f"{k.ILLUSTRATIVE}, a kit model, never product copy",
        f"Save of this board fires dom.settings_changed {{key}} per changed key (§14.1 L{k.L('`dom.settings_changed {key}` (`14`:1254)')})",
        f"Stops on the Colour tab at this tier: {', '.join(k.size_fmt(a) for a in k.stops())} BTC (board 03)"])


def redlines() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.REDLINES
    cols = [k.Col("el", "Element", 200), k.Col("tok", "Token (§2.4)", 880), k.Col("val", "Value", 152)]
    rows = [{"el": k.plain(c[0]), "tok": k.plain(c[1]), "val": k.plain(c[2])} for _i, c in k.REDLINE_ROWS]
    tbl = k.grid_table("§2.4 token map", cols, rows, cap=f"§2.4 redlines and the token map (L{k.REDLINE_ROWS[0][0]}"
                                                         f"–L{k.REDLINE_ROWS[-1][0]}), verbatim", row_h=24)
    tgt = k.plain(next(c for _i, c in k.REDLINE_ROWS if k.plain(c[0]) == "targets")[2])
    specimens = [ui.close_btn(), ui.radio("200", checked=True), ui.checkbox(k.W("W-15"), on=False),
                 k.box("handle · Stop 1", [], {"fill": k.SUNKEN, "stroke": k.TEXT_3, "strokeWidth": k.HAIR,
                                               "strokeAlign": "inner", "radius": k.R_CONTROL}, w=24, h=24),
                 ui.button(k.W("W-25"))]
    spec_row = k.hbox("targets · specimens", [k.vbox(f"specimen {i}", [s, k.text("redline", tgt, k.CAPTION, k.TEXT_2)],
                                                     {"gap": k.STACK_XS}, h=round(k.est_height(s)) + 18)
                                              for i, s in enumerate(specimens, 1)], {"gap": k.INSET_XL,
                                                                                      "align": "start"}, w=1232, h=52)
    fr = k.marker_frame(fid, [tbl, k.text("targets", k.S("redlined on boards 01, 09, 10"), k.LABEL, k.TEXT_1),
                              spec_row], 1280)
    return fr, k.frame_block(fid, [
        "The §2.4 rows drawn verbatim; the specimens are the close button, a CMP-006 hit row, a CMP-005, a stop handle "
        f"and the W-25 pin button, each ≥ {tgt}",
        "No PROPOSED token: every name ships in token-sync.json (G-TOKENS); color.text.disabled and opacity.disabled "
        "are bound nowhere on the set (R-3)"])


if __name__ == "__main__":
    built = [default(), redlines()]
    b = k.BOARDS[NN]
    k.live(f"light twin: after the dark export, switch to the light theme (wait as the README says) and export the same "
           f"board as {b.export_light}")
    k.build(NN, [x[0] for x in built], [x[1] for x in built], 2,
            board_lines=["Owner walkthrough item 1 (§18): the cost warning reads measured or not yet measured, never "
                         "guessed"])
    print("ok", b.sheet)
